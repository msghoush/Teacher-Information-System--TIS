import json
from datetime import timedelta

import audit
from saas import models, paddle_client


FINALIZED_FIELDS = {
    "pending_organization.billing_status": "tenant_active",
    "pending_organization.payment_status": "paid",
    "checkout_session.status": "completed",
    "payment_attempt.status": "payment_confirmed",
    "subscription_contract.payment_status": "paid",
}
PAID_CHANGE_TYPES = {"branch_quantity_increase", "plan_upgrade"}
ALLOWED_CURRENT_VALUES = {
    "pending_organization.billing_status": {"payment_processing", "tenant_active"},
    "pending_organization.payment_status": {"processing", "paid"},
    "checkout_session.status": {"processing", "completed"},
    "payment_attempt.status": {"payment_processing", "payment_confirmed"},
    "subscription_contract.payment_status": {"processing", "paid"},
}


class LifecycleReconciliationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _clean(value) -> str:
    return str(value or "").strip()


def _one(rows, *, code: str, label: str):
    if len(rows) != 1:
        raise LifecycleReconciliationError(code, f"Expected exactly one {label}; found {len(rows)}.")
    return rows[0]


def _payload(row) -> dict:
    try:
        value = json.loads(row.payload_json or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _transaction_price_ids(data: dict) -> set[str]:
    return {
        _clean((item.get("price") or {}).get("id") or item.get("price_id"))
        for item in data.get("items", [])
        if isinstance(item, dict)
    }


def _find_completed_change_webhook(db, *, subscription_id: str, change):
    rows = db.query(models.PaymentWebhook).filter(
        models.PaymentWebhook.event_type == "transaction.completed",
        models.PaymentWebhook.signature_valid.is_(True),
        models.PaymentWebhook.processing_status.in_(("processed", "duplicate")),
    ).order_by(models.PaymentWebhook.received_at.desc(), models.PaymentWebhook.id.desc()).all()
    expected_price_id = _clean(change.target_provider_price_id or change.provider_price_id)
    candidates = []
    for row in rows:
        payload = _payload(row)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if (
            _clean(data.get("subscription_id")) != subscription_id
            or _clean(data.get("origin")) != "subscription_update"
            or _clean(data.get("status")).lower() != "completed"
            or expected_price_id not in _transaction_price_ids(data)
        ):
            continue
        if change.submitted_at and row.received_at and row.received_at < change.submitted_at:
            continue
        if change.confirmed_at and row.received_at:
            if abs(row.received_at - change.confirmed_at) > timedelta(minutes=5):
                continue
        candidates.append((row, data))
    if len(candidates) != 1:
        raise LifecycleReconciliationError(
            "ambiguous_completed_change_transaction",
            f"Expected exactly one attributable completed subscription-change transaction; found {len(candidates)}.",
        )
    return candidates[0]


def reconcile_finalized_lifecycle(db, *, email: str, apply: bool = False) -> dict:
    normalized_email = _clean(email).lower()
    account = _one(
        db.query(models.SaaSAccount).filter(
            models.SaaSAccount.email_normalized == normalized_email
        ).all(),
        code="account_not_unique",
        label="SaaS account",
    )
    organization = _one(
        db.query(models.PendingOrganization).filter(
            models.PendingOrganization.owner_saas_account_id == account.id
        ).all(),
        code="organization_not_unique",
        label="pending organization",
    )
    contract = _one(
        db.query(models.SubscriptionContract).filter(
            models.SubscriptionContract.pending_organization_id == organization.id,
            models.SubscriptionContract.contract_status == "tenant_active",
        ).all(),
        code="active_contract_not_unique",
        label="active subscription contract",
    )
    subscription = _one(
        db.query(models.PaymentSubscription).filter(
            models.PaymentSubscription.subscription_contract_id == contract.id,
            models.PaymentSubscription.status == "active",
        ).all(),
        code="active_subscription_not_unique",
        label="active payment subscription",
    )
    tenant_link = _one(
        db.query(models.TenantProvisioningLink).filter(
            models.TenantProvisioningLink.subscription_contract_id == contract.id,
            models.TenantProvisioningLink.tenant_status == "tenant_active",
            models.TenantProvisioningLink.school_group_id == contract.school_group_id,
        ).all(),
        code="active_tenant_link_not_unique",
        label="active tenant provisioning link",
    )
    completed_jobs = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id == organization.id,
        models.ProvisioningJob.subscription_contract_id == contract.id,
        models.ProvisioningJob.job_status == "completed",
    ).all()
    if not completed_jobs:
        raise LifecycleReconciliationError(
            "provisioning_not_completed", "No completed provisioning job proves tenant activation."
        )
    if _clean(account.status).lower() != "active" or _clean(account.onboarding_status).lower() != "tenant_active":
        raise LifecycleReconciliationError(
            "account_not_tenant_active", "The SaaS account is not in the finalized tenant-active state."
        )
    change = _one(
        db.query(models.SubscriptionChangeRequest).filter(
            models.SubscriptionChangeRequest.payment_subscription_id == subscription.id,
            models.SubscriptionChangeRequest.change_type.in_(PAID_CHANGE_TYPES),
            models.SubscriptionChangeRequest.status == "confirmed",
            models.SubscriptionChangeRequest.provider_payment_confirmed_at.isnot(None),
        ).order_by(
            models.SubscriptionChangeRequest.confirmed_at.desc(),
            models.SubscriptionChangeRequest.id.desc(),
        ).limit(1).all(),
        code="confirmed_change_missing",
        label="latest confirmed paid subscription change",
    )
    webhook, webhook_data = _find_completed_change_webhook(
        db,
        subscription_id=subscription.provider_subscription_id,
        change=change,
    )
    transaction_id = _clean(webhook_data.get("id"))
    if not transaction_id:
        raise LifecycleReconciliationError(
            "provider_transaction_id_missing", "The attributable webhook has no provider transaction ID."
        )
    provider_transaction = paddle_client._request("GET", f"/transactions/{transaction_id}")
    provider_subscription = paddle_client.get_subscription(
        subscription_id=subscription.provider_subscription_id
    )
    if (
        _clean(provider_transaction.get("id")) != transaction_id
        or _clean(provider_transaction.get("status")).lower() != "completed"
        or _clean(provider_transaction.get("origin")) != "subscription_update"
        or _clean(provider_transaction.get("subscription_id")) != subscription.provider_subscription_id
    ):
        raise LifecycleReconciliationError(
            "provider_transaction_not_authoritative",
            "Paddle does not confirm the attributable subscription-change transaction as completed.",
        )
    if (
        _clean(provider_subscription.get("id")) != subscription.provider_subscription_id
        or _clean(provider_subscription.get("status")).lower() != "active"
    ):
        raise LifecycleReconciliationError(
            "provider_subscription_not_active", "Paddle does not confirm the subscription as active."
        )
    checkout = db.query(models.CheckoutSession).filter(
        models.CheckoutSession.id == contract.selected_checkout_session_id,
        models.CheckoutSession.pending_organization_id == organization.id,
    ).one_or_none()
    if checkout is None:
        raise LifecycleReconciliationError(
            "initial_checkout_missing", "The contract's initial checkout session cannot be resolved."
        )
    attempt_id = checkout.last_payment_attempt_id or organization.last_payment_attempt_id
    attempt = db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.id == attempt_id,
        models.PaymentAttempt.checkout_session_id == checkout.id,
        models.PaymentAttempt.pending_organization_id == organization.id,
        models.PaymentAttempt.provider_subscription_id == subscription.provider_subscription_id,
    ).one_or_none()
    if attempt is None:
        raise LifecycleReconciliationError(
            "initial_payment_attempt_missing", "The finalized initial payment attempt cannot be resolved."
        )

    field_bindings = {
        "pending_organization.billing_status": (organization, "billing_status"),
        "pending_organization.payment_status": (organization, "payment_status"),
        "checkout_session.status": (checkout, "status"),
        "payment_attempt.status": (attempt, "status"),
        "subscription_contract.payment_status": (contract, "payment_status"),
    }
    before = {key: _clean(getattr(record, field)) for key, (record, field) in field_bindings.items()}
    unsafe = {
        key: value
        for key, value in before.items()
        if value not in ALLOWED_CURRENT_VALUES[key]
    }
    if unsafe:
        raise LifecycleReconciliationError(
            "unexpected_current_lifecycle_state",
            f"Lifecycle reconciliation blocked by unexpected current values: {sorted(unsafe)}.",
        )
    changed_fields = [key for key, value in before.items() if value != FINALIZED_FIELDS[key]]
    if apply:
        for key in changed_fields:
            record, field = field_bindings[key]
            setattr(record, field, FINALIZED_FIELDS[key])
        audit.write_audit_event(
            {
                "event_type": "finalized_payment_lifecycle_reconciled",
                "saas_account_id": account.id,
                "pending_organization_id": organization.id,
                "subscription_contract_id": contract.id,
                "payment_subscription_id": subscription.id,
                "subscription_change_request_uuid": change.request_uuid,
                "provider_event_id": webhook.provider_event_id,
                "changed_fields": changed_fields,
            }
        )
    return {
        "status": "reconciled" if apply else "dry_run",
        "email_normalized": normalized_email,
        "authoritative_evidence": {
            "provider_transaction_status": "completed",
            "provider_subscription_status": "active",
            "local_subscription_status": subscription.status,
            "contract_status": contract.contract_status,
            "tenant_link_status": tenant_link.tenant_status,
            "provisioning_job_status": "completed",
            "subscription_change_status": change.status,
        },
        "before": before,
        "after": {**before, **{key: FINALIZED_FIELDS[key] for key in changed_fields}},
        "changed_fields": changed_fields,
        "database_write_performed": apply,
    }
