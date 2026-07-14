import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import models


DEFAULT_FIRST_REMINDER_HOURS = 24
DEFAULT_SECOND_REMINDER_DAYS = 7
DEFAULT_FINAL_REMINDER_DAYS = 25
DEFAULT_DELETION_DAYS = 30

ACTIVE_STATES = {"active", "tenant_active", "provisioning_completed"}
PROVISIONING_STATES = {
    "ready_for_provisioning",
    "provisioning_started",
    "provisioning_retrying",
    "provisioning_completed",
}
PAYMENT_PENDING_STATES = {"payment_processing", "payment_reconciliation_required"}
CHECKOUT_STARTED_STATES = {"checkout_initiated", "checkout_started"}
READY_FOR_CHECKOUT_STATES = {"ready_for_checkout", "plan_selected", "checkout_ready"}
CONFIRMED_ATTEMPT_STATES = {"payment_confirmed", "completed", "paid", "succeeded"}
PENDING_PROVISIONING_STATES = {"queued", "processing", "retrying", "pending"}
ACTIVE_SUBSCRIPTION_STATES = {"active", "trialing", "past_due", "paused"}
PROCESSING_PAYMENT_STATES = {"pending", "processing", "payment_processing", "payment_pending"}
CONTRACT_PROCESSING_STATES = {"processing", "payment_processing", "payment_pending"}
SUCCESSFUL_WEBHOOK_EVENTS = {
    "transaction.paid",
    "transaction.completed",
    "subscription.created",
    "subscription.activated",
    "subscription.resumed",
}


@dataclass(frozen=True)
class DraftRetentionSettings:
    first_reminder_after: timedelta
    second_reminder_after: timedelta
    final_reminder_after: timedelta
    deletion_after: timedelta


@dataclass(frozen=True)
class DraftLifecycleResult:
    state: str
    base_state: str
    deletion_eligible: bool
    deletion_status: str
    effective_activity_at: datetime
    deletion_eligible_at: datetime
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_retention_settings(db: Session) -> DraftRetentionSettings:
    row = db.query(models.SaaSDraftLifecycleSetting).filter(
        models.SaaSDraftLifecycleSetting.id == 1
    ).first()
    first_hours = _positive_int(
        getattr(row, "first_reminder_hours", None), DEFAULT_FIRST_REMINDER_HOURS
    )
    second_days = _positive_int(
        getattr(row, "second_reminder_days", None), DEFAULT_SECOND_REMINDER_DAYS
    )
    final_days = _positive_int(
        getattr(row, "final_reminder_days", None), DEFAULT_FINAL_REMINDER_DAYS
    )
    deletion_days = _positive_int(
        getattr(row, "deletion_days", None), DEFAULT_DELETION_DAYS
    )
    return DraftRetentionSettings(
        first_reminder_after=timedelta(hours=first_hours),
        second_reminder_after=timedelta(days=second_days),
        final_reminder_after=timedelta(days=final_days),
        deletion_after=timedelta(days=deletion_days),
    )


def _owned_organizations(db: Session, account):
    return db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account.id
    ).order_by(models.PendingOrganization.id.asc()).all()


def resolve_activity_timestamp(db: Session, account, organization=None) -> tuple[datetime, tuple[str, ...]]:
    organizations = _owned_organizations(db, account)
    warnings = []
    if organization is not None and getattr(organization, "owner_saas_account_id", None) != account.id:
        warnings.append("The supplied pending organization is not owned by this SaaS account.")
    if len(organizations) == 1:
        timestamp = getattr(organizations[0], "last_meaningful_activity_at", None)
        if timestamp:
            return timestamp, tuple(warnings)
    elif len(organizations) > 1:
        warnings.append("Multiple pending organizations prevent an unambiguous activity owner.")
    timestamp = (
        getattr(account, "last_meaningful_activity_at", None)
        or getattr(account, "updated_at", None)
        or getattr(account, "created_at", None)
        or _utcnow()
    )
    return timestamp, tuple(warnings)


def _add_activity_event(db: Session, account, organization, event_type: str, details: dict):
    details_json = json.dumps(details, separators=(",", ":"))
    if organization is not None:
        db.add(models.PendingOrganizationEvent(
            pending_organization_id=organization.id,
            actor_saas_account_id=account.id,
            event_type=event_type,
            details_json=details_json,
        ))
        return
    db.add(models.SaaSAuthEvent(
        saas_account_id=account.id,
        event_type=event_type,
        event_status="ok",
        details_json=details_json,
    ))


def record_meaningful_activity(
    db: Session,
    account,
    *,
    organization=None,
    source: str,
    occurred_at: datetime | None = None,
) -> datetime:
    now = occurred_at or _utcnow()
    owned_organizations = _owned_organizations(db, account)
    authoritative_organization = None
    if organization is not None and getattr(organization, "owner_saas_account_id", None) == account.id:
        authoritative_organization = organization
    elif len(owned_organizations) == 1:
        authoritative_organization = owned_organizations[0]

    had_reminders = any((
        getattr(account, "first_reminder_sent_at", None),
        getattr(account, "second_reminder_sent_at", None),
        getattr(account, "final_reminder_sent_at", None),
    ))
    account.last_meaningful_activity_at = now
    if authoritative_organization is not None:
        authoritative_organization.last_meaningful_activity_at = now

    cycle = int(getattr(account, "reminder_cycle", 1) or 1)
    if had_reminders:
        cycle += 1
        account.reminder_cycle = cycle
        account.first_reminder_sent_at = None
        account.second_reminder_sent_at = None
        account.final_reminder_sent_at = None
        account.recovered_after_reminder_at = now

    event_organization = authoritative_organization
    details = {"source": str(source or "customer_action")[:80], "reminder_cycle": cycle}
    _add_activity_event(db, account, event_organization, "meaningful_activity_recorded", details)
    if had_reminders:
        _add_activity_event(db, account, event_organization, "draft_recovered_after_inactivity", details)
        _add_activity_event(db, account, event_organization, "reminder_cycle_reset", details)
    return now


def _base_state(account, organization, *, has_tenant_link: bool, has_active_job: bool) -> str:
    onboarding_status = str(getattr(account, "onboarding_status", "") or "").strip().lower()
    organization_status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    lifecycle_statuses = {onboarding_status, organization_status, billing_status}
    if has_tenant_link or lifecycle_statuses.intersection(ACTIVE_STATES):
        return "active"
    if has_active_job or lifecycle_statuses.intersection(PROVISIONING_STATES):
        return "provisioning"
    if lifecycle_statuses.intersection(PAYMENT_PENDING_STATES):
        return "payment_pending"
    if lifecycle_statuses.intersection(CHECKOUT_STARTED_STATES):
        return "checkout_started"
    if lifecycle_statuses.intersection(READY_FOR_CHECKOUT_STATES):
        return "ready_for_checkout"
    if organization is not None:
        return "onboarding_in_progress"
    return "account_created"


def resolve_draft_lifecycle(
    db: Session,
    account=None,
    *,
    organization=None,
    now: datetime | None = None,
    deletion_after_override: timedelta | None = None,
) -> DraftLifecycleResult:
    now = now or _utcnow()
    settings = get_retention_settings(db)
    if account is None and organization is not None:
        account = db.query(models.SaaSAccount).filter(
            models.SaaSAccount.id == organization.owner_saas_account_id
        ).first()
    if account is None:
        raise ValueError("A SaaS account or pending organization is required.")
    organizations = _owned_organizations(db, account)
    warnings = []
    blockers = []
    if organization is not None and getattr(organization, "owner_saas_account_id", None) != account.id:
        warnings.append("The supplied pending organization is not owned by this SaaS account.")
        organization = None
    if len(organizations) == 1:
        organization = organizations[0]
    elif len(organizations) > 1:
        warnings.append("Multiple pending organizations require manual review.")
        organization = None

    organization_ids = [row.id for row in organizations]
    tenant_links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    account_user_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id
    ).all()
    jobs = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    subscriptions = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    contracts = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    attempts = db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    payment_customer_filters = [models.PaymentCustomer.saas_account_id == account.id]
    if organization_ids:
        payment_customer_filters.append(
            models.PaymentCustomer.pending_organization_id.in_(organization_ids)
        )
    payment_customers = db.query(models.PaymentCustomer).filter(
        or_(*payment_customer_filters)
    ).all()
    provider_customer_keys = {
        (str(getattr(row, "provider", "") or ""), str(getattr(row, "provider_customer_id", "") or ""))
        for row in payment_customers
        if getattr(row, "provider_customer_id", None)
    }
    shared_payment_customer = False
    for provider, provider_customer_id in provider_customer_keys:
        if db.query(models.PaymentCustomer.id).filter(
            models.PaymentCustomer.provider == provider,
            models.PaymentCustomer.provider_customer_id == provider_customer_id,
            models.PaymentCustomer.id.notin_([row.id for row in payment_customers]),
        ).first() is not None:
            shared_payment_customer = True
            break
    actor_events = db.query(models.PendingOrganizationEvent).filter(
        models.PendingOrganizationEvent.actor_saas_account_id == account.id
    ).all()

    if len(organizations) > 1:
        blockers.append("multiple_pending_organizations")
    if (
        str(getattr(account, "status", "") or "").strip().lower() in {"locked", "disabled"}
        or getattr(account, "locked_at", None)
        or str(getattr(account, "locked_reason", "") or "").strip()
    ):
        blockers.append("manual_account_protection")
    platform_identity = db.query(operational_models.User).filter(
        or_(
            operational_models.User.email_normalized == getattr(account, "email_normalized", None),
            func.lower(operational_models.User.email) == getattr(account, "email_normalized", None),
        )
    ).all()
    if any(auth.is_platform_user(row) for row in platform_identity):
        blockers.append("platform_identity_protected")
    if any(
        not auth.is_platform_user(row)
        and int(getattr(row, "school_group_id", 0) or 0) > 0
        for row in platform_identity
    ):
        blockers.append("operational_identity_relationship")
    if tenant_links:
        blockers.append("tenant_provisioning_link")
    if account_user_links:
        blockers.append("operational_account_link")
    if any(getattr(row, "school_group_id", None) for row in contracts):
        blockers.append("operational_school_group")
    if any(str(getattr(row, "job_status", "") or "").lower() in PENDING_PROVISIONING_STATES for row in jobs):
        blockers.append("active_or_pending_provisioning")
    if any(
        str(getattr(row, "job_status", "") or "").lower() != "failed"
        and str(getattr(row, "job_status", "") or "").lower() not in PENDING_PROVISIONING_STATES
        for row in jobs
    ) or any(
        getattr(row, "target_school_group_id", None)
        or getattr(row, "tenant_provisioning_link_id", None)
        for row in jobs
    ):
        warnings.append("Provisioning history requires manual review.")
        blockers.append("provisioning_history")
    if any(str(getattr(row, "status", "") or "").lower() in ACTIVE_SUBSCRIPTION_STATES for row in subscriptions):
        blockers.append("active_subscription")
    if subscriptions and "active_subscription" not in blockers:
        warnings.append("Subscription history requires manual review.")
        blockers.append("subscription_history")
    if any(
        str(getattr(row, "payment_status", "") or "").lower() == "paid" or getattr(row, "paid_at", None)
        for row in contracts
    ):
        blockers.append("successful_payment")
    if any(str(getattr(row, "status", "") or "").lower() in CONFIRMED_ATTEMPT_STATES for row in attempts):
        blockers.append("confirmed_payment_attempt")
    if any(
        str(getattr(row, "status", "") or "").lower() in PROCESSING_PAYMENT_STATES
        for row in attempts
    ):
        blockers.append("payment_attempt_processing")
    if any(
        getattr(row, "provider_transaction_id", None)
        and str(getattr(row, "status", "") or "").lower() not in {"failed", "cancelled", "expired"}
        for row in attempts
    ):
        warnings.append("An unresolved provider transaction requires manual review.")
        blockers.append("unresolved_payment_attempt")
    if any(
        getattr(row, "pending_organization_id", None) is not None
        and int(row.pending_organization_id) not in organization_ids
        for row in payment_customers
    ) or any(
        int(getattr(row, "saas_account_id", 0) or 0) != int(account.id)
        for row in payment_customers
    ) or shared_payment_customer:
        warnings.append("An account-level payment customer mapping requires manual review.")
        blockers.append("unresolved_payment_customer")
    if any(
        int(getattr(row, "pending_organization_id", 0) or 0) not in organization_ids
        for row in actor_events
    ):
        warnings.append("An account audit event belongs to another pending organization.")
        blockers.append("unresolved_identity_relationship")
    if any(
        str(getattr(row, "payment_status", "") or "").lower() == "paid"
        or getattr(row, "payment_confirmed_at", None)
        for row in organizations
    ):
        blockers.append("successful_payment")

    attempt_uuids = {str(getattr(row, "attempt_uuid", "") or "") for row in attempts}
    provider_transaction_ids = {
        str(getattr(row, "provider_transaction_id", "") or "") for row in attempts
        if getattr(row, "provider_transaction_id", None)
    }
    provider_subscription_ids = {
        str(getattr(row, "provider_subscription_id", "") or "") for row in attempts
        if getattr(row, "provider_subscription_id", None)
    }
    provider_subscription_ids.update(
        str(getattr(row, "provider_subscription_id", "") or "") for row in subscriptions
        if getattr(row, "provider_subscription_id", None)
    )
    organization_uuids = {
        str(getattr(row, "organization_uuid", "") or "") for row in organizations
    }
    successful_webhook = False
    for webhook in db.query(models.PaymentWebhook).filter(
        models.PaymentWebhook.provider == "paddle",
        models.PaymentWebhook.event_type.in_(SUCCESSFUL_WEBHOOK_EVENTS),
    ).all():
        try:
            payload = json.loads(str(getattr(webhook, "payload_json", "") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        data = payload.get("data") if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else {}
        custom_data = data.get("custom_data")
        custom_data = custom_data if isinstance(custom_data, dict) else {}
        if (
            str(custom_data.get("pending_organization_uuid") or "") in organization_uuids
            or str(custom_data.get("payment_attempt_uuid") or "") in attempt_uuids
            or str(data.get("id") or "") in provider_transaction_ids
            or str(data.get("subscription_id") or data.get("id") or "") in provider_subscription_ids
        ):
            successful_webhook = True
            break
    if successful_webhook:
        blockers.append("successful_webhook_evidence")

    if any(
        str(getattr(row, "payment_status", "") or "").lower() in CONTRACT_PROCESSING_STATES
        for row in contracts
    ):
        blockers.append("contract_payment_processing")

    has_tenant_link = bool(tenant_links or account_user_links)
    has_active_job = any(
        str(getattr(row, "job_status", "") or "").lower() in PENDING_PROVISIONING_STATES
        for row in jobs
    )
    base_state = _base_state(account, organization, has_tenant_link=has_tenant_link, has_active_job=has_active_job)
    activity_at, activity_warnings = resolve_activity_timestamp(db, account, organization)
    warnings.extend(activity_warnings)
    deletion_after = deletion_after_override or settings.deletion_after
    if deletion_after <= timedelta(0):
        raise ValueError("Deletion inactivity threshold must be positive.")
    deletion_at = activity_at + deletion_after
    due = now >= deletion_at
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))

    if base_state in {"active", "provisioning", "payment_pending"}:
        state = base_state
        deletion_status = "ineligible"
    elif blockers or warnings:
        state = "deletion_ineligible"
        deletion_status = "manual_review" if warnings else "ineligible"
    elif due:
        state = "deletion_candidate"
        deletion_status = "candidate"
    else:
        state = base_state
        deletion_status = "not_due"
    return DraftLifecycleResult(
        state=state,
        base_state=base_state,
        deletion_eligible=state == "deletion_candidate",
        deletion_status=deletion_status,
        effective_activity_at=activity_at,
        deletion_eligible_at=deletion_at,
        blocking_reasons=tuple(blockers),
        warnings=tuple(warnings),
    )
