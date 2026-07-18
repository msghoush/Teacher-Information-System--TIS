"""Read-only diagnostics for a SaaS organization's initial Paddle lifecycle.

This utility is intended for a deployed Render Shell. It reads local lifecycle
records and the matching Paddle Sandbox transaction/subscription, emits a
sanitized JSON report, and always rolls back its database session.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import desc

from database import SessionLocal
from saas.models import (
    CheckoutSession,
    PaymentAttempt,
    PaymentSubscription,
    PaymentWebhook,
    PendingOrganization,
    ProvisioningJob,
    SaaSAccount,
    SubscriptionChangeRequest,
    SubscriptionContract,
    TenantProvisioningLink,
)
from saas import paddle_client


RELEVANT_WEBHOOK_TYPES = {
    "transaction.created",
    "transaction.paid",
    "transaction.completed",
    "subscription.created",
    "subscription.updated",
}


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _normalized_email(value: str) -> str:
    return value.strip().lower()


def _parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _paddle_data(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    return data if isinstance(data, dict) else response


def _require_sandbox() -> dict[str, str]:
    environment = os.getenv("PADDLE_ENVIRONMENT", "").strip().lower()
    base_url = paddle_client._base_url()  # noqa: SLF001 - diagnostic validation
    hostname = (urlparse(base_url).hostname or "").lower()
    if environment != "sandbox" or hostname != "sandbox-api.paddle.com":
        raise RuntimeError(
            "Refusing provider inspection: PADDLE_ENVIRONMENT and the resolved "
            "Paddle API endpoint must both identify Sandbox."
        )
    return {"environment": environment, "api_hostname": hostname}


def _safe_custom_ids(data: dict[str, Any]) -> set[str]:
    custom_data = data.get("custom_data")
    if not isinstance(custom_data, dict):
        return set()
    allowed = {
        "organization_uuid",
        "pending_organization_uuid",
        "payment_attempt_uuid",
        "checkout_session_uuid",
    }
    return {
        str(value)
        for key, value in custom_data.items()
        if key in allowed and value not in (None, "")
    }


def _webhook_matches(
    payload: dict[str, Any],
    *,
    transaction_id: str | None,
    subscription_id: str | None,
    local_ids: set[str],
) -> bool:
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    event_type = str(payload.get("event_type") or "")
    data_id = str(data.get("id") or "")
    payload_transaction_id = str(data.get("transaction_id") or "")
    payload_subscription_id = str(data.get("subscription_id") or "")
    if event_type.startswith("transaction.") and transaction_id and data_id == transaction_id:
        return True
    if event_type.startswith("subscription.") and subscription_id and data_id == subscription_id:
        return True
    if transaction_id and payload_transaction_id == transaction_id:
        return True
    if subscription_id and payload_subscription_id == subscription_id:
        return True
    return bool(local_ids.intersection(_safe_custom_ids(data)))


def _sanitize_transaction(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "status": data.get("status"),
        "origin": data.get("origin"),
        "billed_at": data.get("billed_at"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "subscription_id": data.get("subscription_id"),
    }


def _sanitize_subscription(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "status": data.get("status"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "next_billed_at": data.get("next_billed_at"),
        "scheduled_change_present": bool(data.get("scheduled_change")),
    }


def _webhook_disposition(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"processed", "completed"}:
        return "completed"
    if normalized == "duplicate":
        return "ignored_duplicate"
    if normalized in {"ignored", "rejected", "manual_review", "failed"}:
        return normalized
    if normalized in {"pending", "processing"}:
        return normalized
    return "unknown"


def _classify_root_cause(
    *,
    paddle_transaction_status: str | None,
    billing_status: str | None,
    transaction_completed_events: list[dict[str, Any]],
    matching_change_request_count: int,
) -> str:
    provider_completed = (paddle_transaction_status or "").lower() == "completed"
    local_stale = (billing_status or "").lower() == "payment_processing"
    if not provider_completed:
        return "provider_transaction_not_completed"
    if not local_stale:
        return "local_lifecycle_already_reconciled"
    if not transaction_completed_events:
        return "completed_provider_transaction_missing_local_webhook"
    statuses = {
        str(event.get("processing_status") or "").lower()
        for event in transaction_completed_events
    }
    if statuses.intersection({"rejected", "failed", "manual_review"}):
        return "completed_webhook_failed_or_requires_review"
    if statuses.intersection({"ignored", "duplicate"}):
        return "completed_webhook_ignored"
    if statuses.intersection({"pending", "processing"}):
        return "completed_webhook_not_finished"
    if matching_change_request_count:
        return "completed_webhook_processed_with_matching_subscription_change"
    return "completed_webhook_processed_without_lifecycle_transition"


def _record_snapshot(record: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if record is None:
        return None
    return {field: _serialize(getattr(record, field, None)) for field in fields}


def _single(records: list[Any], label: str, warnings: list[str]) -> Any | None:
    if not records:
        warnings.append(f"No {label} record was found.")
        return None
    if len(records) > 1:
        warnings.append(
            f"Multiple {label} records were found; the newest row is shown and "
            "the count is included for manual review."
        )
    return records[0]


def build_report(email: str) -> dict[str, Any]:
    provider = _require_sandbox()
    db = SessionLocal()
    warnings: list[str] = []
    try:
        normalized = _normalized_email(email)
        accounts = (
            db.query(SaaSAccount)
            .filter(SaaSAccount.email_normalized == normalized)
            .all()
        )
        if len(accounts) != 1:
            raise RuntimeError(
                f"Expected exactly one SaaS account for the normalized email; found {len(accounts)}."
            )
        account = accounts[0]
        organizations = (
            db.query(PendingOrganization)
            .filter(PendingOrganization.owner_saas_account_id == account.id)
            .order_by(desc(PendingOrganization.id))
            .all()
        )
        if len(organizations) != 1:
            raise RuntimeError(
                f"Expected exactly one pending organization for the account; found {len(organizations)}."
            )
        organization = organizations[0]

        attempts = (
            db.query(PaymentAttempt)
            .filter(PaymentAttempt.pending_organization_id == organization.id)
            .order_by(desc(PaymentAttempt.id))
            .all()
        )
        attempt = next(
            (row for row in attempts if row.id == organization.last_payment_attempt_id),
            attempts[0] if attempts else None,
        )
        checkouts = (
            db.query(CheckoutSession)
            .filter(CheckoutSession.pending_organization_id == organization.id)
            .order_by(desc(CheckoutSession.id))
            .all()
        )
        checkout = next(
            (
                row
                for row in checkouts
                if attempt is not None and row.id == attempt.checkout_session_id
            ),
            checkouts[0] if checkouts else None,
        )
        contracts = (
            db.query(SubscriptionContract)
            .filter(SubscriptionContract.pending_organization_id == organization.id)
            .order_by(desc(SubscriptionContract.id))
            .all()
        )
        contract = _single(contracts, "subscription contract", warnings)
        subscriptions = (
            db.query(PaymentSubscription)
            .filter(PaymentSubscription.pending_organization_id == organization.id)
            .order_by(desc(PaymentSubscription.id))
            .all()
        )
        subscription = _single(subscriptions, "payment subscription", warnings)
        tenant_links = (
            db.query(TenantProvisioningLink)
            .filter(TenantProvisioningLink.pending_organization_id == organization.id)
            .order_by(desc(TenantProvisioningLink.id))
            .all()
        )
        tenant_link = _single(tenant_links, "tenant provisioning link", warnings)
        provisioning_jobs = (
            db.query(ProvisioningJob)
            .filter(ProvisioningJob.pending_organization_id == organization.id)
            .order_by(desc(ProvisioningJob.id))
            .all()
        )
        provisioning_job = provisioning_jobs[0] if provisioning_jobs else None

        transaction_id = getattr(attempt, "provider_transaction_id", None)
        if not transaction_id:
            warnings.append("The selected payment attempt has no provider transaction ID.")
        subscription_id = (
            getattr(attempt, "provider_subscription_id", None)
            or getattr(subscription, "provider_subscription_id", None)
        )

        paddle_transaction: dict[str, Any] | None = None
        if transaction_id:
            response = paddle_client._request(  # noqa: SLF001 - read-only diagnostic
                "GET", f"/transactions/{transaction_id}"
            )
            paddle_transaction = _sanitize_transaction(_paddle_data(response))
            subscription_id = subscription_id or paddle_transaction.get("subscription_id")

        paddle_subscription: dict[str, Any] | None = None
        if subscription_id:
            paddle_subscription = _sanitize_subscription(
                paddle_client.get_subscription(subscription_id=subscription_id)
            )

        local_ids = {
            str(value)
            for value in (
                organization.organization_uuid,
                getattr(attempt, "attempt_uuid", None),
            )
            if value not in (None, "")
        }
        webhook_rows = (
            db.query(PaymentWebhook)
            .filter(PaymentWebhook.event_type.in_(RELEVANT_WEBHOOK_TYPES))
            .order_by(PaymentWebhook.received_at.asc(), PaymentWebhook.id.asc())
            .all()
        )
        webhook_timeline: list[dict[str, Any]] = []
        for row in webhook_rows:
            payload = _parse_json_object(row.payload_json)
            if not _webhook_matches(
                payload,
                transaction_id=transaction_id,
                subscription_id=subscription_id,
                local_ids=local_ids,
            ):
                continue
            webhook_timeline.append(
                {
                    "event_type": row.event_type,
                    "provider_event_id": row.provider_event_id,
                    "received_at": _serialize(row.received_at),
                    "processed_at": _serialize(row.processed_at),
                    "signature_valid": row.signature_valid,
                    "delivery_attempt": row.delivery_attempt,
                    "processing_status": row.processing_status,
                    "processing_result": _webhook_disposition(row.processing_status),
                    "processing_error": row.processing_error,
                    "disposition": _webhook_disposition(row.processing_status),
                }
            )

        change_query = db.query(SubscriptionChangeRequest)
        if subscription is not None:
            change_query = change_query.filter(
                SubscriptionChangeRequest.payment_subscription_id == subscription.id
            )
            change_requests = change_query.order_by(desc(SubscriptionChangeRequest.id)).all()
        elif contract is not None:
            change_query = change_query.filter(
                SubscriptionChangeRequest.subscription_contract_id == contract.id
            )
            change_requests = change_query.order_by(desc(SubscriptionChangeRequest.id)).all()
        else:
            change_requests = []
        transaction_completed_events = [
            row for row in webhook_timeline if row["event_type"] == "transaction.completed"
        ]
        root_cause = _classify_root_cause(
            paddle_transaction_status=(paddle_transaction or {}).get("status"),
            billing_status=organization.billing_status,
            transaction_completed_events=transaction_completed_events,
            matching_change_request_count=len(change_requests),
        )
        observed_event_types = {row["event_type"] for row in webhook_timeline}

        return {
            "diagnostic": {
                "mode": "read_only",
                "database_session_end": "rollback",
                "manual_status_updates": False,
                "webhook_replay_performed": False,
                "provider": provider,
            },
            "identity": {
                "email_normalized": normalized,
                "saas_account_id": account.id,
                "pending_organization_id": organization.id,
                "pending_organization_uuid": str(organization.organization_uuid),
                "organization_name": organization.organization_name,
            },
            "local_lifecycle": {
                "saas_account": _record_snapshot(
                    account, ("id", "status", "onboarding_status")
                ),
                "pending_organization": _record_snapshot(
                    organization,
                    ("id", "status", "billing_status", "payment_status"),
                ),
                "checkout_session": _record_snapshot(
                    checkout,
                    ("id", "status", "provider_checkout_id", "started_at", "abandoned_at"),
                ),
                "payment_attempt": _record_snapshot(
                    attempt,
                    (
                        "id",
                        "attempt_uuid",
                        "status",
                        "provider_transaction_id",
                        "provider_subscription_id",
                        "completed_at",
                    ),
                ),
                "payment_subscription": _record_snapshot(
                    subscription,
                    (
                        "id",
                        "status",
                        "provider_subscription_id",
                        "quantity",
                        "current_period_start",
                        "current_period_end",
                    ),
                ),
                "subscription_contract": _record_snapshot(
                    contract,
                    ("id", "contract_status", "payment_status", "paid_at", "school_group_id"),
                ),
                "tenant_provisioning_link": _record_snapshot(
                    tenant_link,
                    ("id", "tenant_status", "school_group_id", "activated_at"),
                ),
                "provisioning_job": _record_snapshot(
                    provisioning_job,
                    ("id", "job_status", "attempt_count", "completed_at", "last_error"),
                ),
                "record_counts": {
                    "checkout_sessions": len(checkouts),
                    "payment_attempts": len(attempts),
                    "payment_subscriptions": len(subscriptions),
                    "subscription_contracts": len(contracts),
                    "tenant_provisioning_links": len(tenant_links),
                    "provisioning_jobs": len(provisioning_jobs),
                    "matching_subscription_change_requests": len(change_requests),
                },
            },
            "paddle": {
                "transaction": paddle_transaction,
                "subscription": paddle_subscription,
            },
            "webhooks": {
                "timeline": webhook_timeline,
                "missing_relevant_event_types": sorted(
                    RELEVANT_WEBHOOK_TYPES - observed_event_types
                ),
                "transaction_completed_present": bool(transaction_completed_events),
                "matching_subscription_change_requests": [
                    _record_snapshot(
                        row,
                        (
                            "id",
                            "change_type",
                            "status",
                            "provider_subscription_id",
                            "created_at",
                            "submitted_at",
                            "confirmed_at",
                            "failure_code",
                        ),
                    )
                    for row in change_requests
                ],
                "rollback_evidence": (
                    "A rolled-back webhook row cannot persist in this table. Absence of an event "
                    "therefore cannot distinguish provider non-delivery from transaction rollback."
                ),
            },
            "assessment": {
                "root_cause_code": root_cause,
                "expected_final_state": {
                    "pending_organization.billing_status": "tenant_active",
                    "pending_organization.payment_status": "paid",
                    "payment_attempt.status": "payment_confirmed",
                    "checkout_session.status": "completed",
                    "payment_subscription.status": "active",
                    "subscription_contract.contract_status": "tenant_active",
                    "tenant_provisioning_link.tenant_status": "tenant_active",
                },
                "safe_next_step": (
                    "If Paddle is completed and the local lifecycle is stale, inspect the stored "
                    "transaction.completed outcome above. Use only the existing signed Paddle "
                    "Dashboard webhook replay/reconciliation path after review; never edit statuses "
                    "manually. This diagnostic does not replay events."
                ),
                "warnings": warnings,
            },
        }
    finally:
        db.rollback()
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect one SaaS account's local and Paddle Sandbox payment lifecycle."
    )
    parser.add_argument("--email", required=True, help="Exact SaaS account email")
    args = parser.parse_args()
    try:
        report = build_report(args.email)
    except Exception as exc:  # CLI boundary: emit a safe diagnostic without credentials.
        print(
            json.dumps(
                {
                    "diagnostic": "payment_lifecycle",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
            )
        )
        return 1
    print(json.dumps(report, indent=2, default=_serialize))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
