from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

import auth
import models as operational_models
from commercial_entitlements import CommercialState, WorkspaceEntitlementStatus
from saas import (
    demo_access_service,
    demo_email_service,
    demo_lifecycle_service,
    demo_notification_service,
    models,
)
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


REQUIRED_REASON_ACTIONS = {
    "expire_demo",
    "reactivate_demo",
    "set_custom_expiry",
    "change_access_profile",
    "change_custom_features",
}
REMINDER_VARIANT_COUNT = 3


class DemoOperationError(ValueError):
    def __init__(self, message: str, *, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class LifecycleRunSummary:
    demos_checked: int
    reminders_created: int
    demos_expired: int
    no_action_count: int
    failures: int
    skipped_or_deduplicated: int


def _json(value) -> str:
    def default(item):
        if isinstance(item, datetime):
            return demo_lifecycle_service.as_utc(item).isoformat()
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        raise TypeError
    return json.dumps(value, default=default, sort_keys=True, separators=(",", ":"))


def _operation_key(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        cleaned = str(uuid.uuid4())
    if len(cleaned) > 120:
        raise DemoOperationError("Operation key is too long.", reason_code="invalid_operation_key")
    return cleaned


def _require_owner(actor):
    if not auth.is_platform_owner(actor):
        raise DemoOperationError(
            "Platform Owner access is required.",
            reason_code="platform_owner_required",
        )


def _require_reason(action: str, reason: str | None) -> str:
    cleaned = str(reason or "").strip()
    if action in REQUIRED_REASON_ACTIONS and not cleaned:
        raise DemoOperationError("A reason is required.", reason_code="reason_required")
    return cleaned


def _context(db: Session, provisioning_id: int, *, lock: bool = True):
    query = db.query(models.SaaSDemoWorkspaceProvisioning).filter_by(id=int(provisioning_id))
    provisioning = query.with_for_update().one_or_none() if lock else query.one_or_none()
    if provisioning is None:
        raise DemoOperationError("Demo workspace was not found.", reason_code="demo_not_found")
    context = demo_lifecycle_service._load_context(db, provisioning)
    request, group, entitlement, tenant_link, organization, account = context
    if not all(context):
        raise DemoOperationError(
            "Demo lifecycle relationships are incomplete.",
            reason_code="incomplete_demo_relationships",
        )
    if group.workspace_classification != WorkspaceClassification.CUSTOMER_DEMO.value:
        raise DemoOperationError("Customer Demo workspace is required.", reason_code="not_customer_demo")
    return provisioning, request, group, entitlement, tenant_link, organization, account


def _state(provisioning, group, entitlement, tenant_link) -> dict:
    return {
        "workspace_lifecycle": group.workspace_lifecycle_status,
        "entitlement_status": entitlement.status,
        "tenant_status": tenant_link.tenant_status,
        "demo_expires_at": provisioning.demo_expires_at,
        "reminder_due_at": provisioning.reminder_due_at,
        "expired_at": provisioning.expired_at,
        "processing_status": provisioning.lifecycle_processing_status,
        "expiry_policy": getattr(provisioning, "expiry_policy", "standard"),
    }


def _audit(
    db: Session,
    *,
    provisioning,
    request,
    actor,
    action: str,
    reason: str,
    operation_key: str,
    previous: dict,
    new: dict,
    status: str,
    branch_id: int | None = None,
    email_ids=(),
    notification_ids=(),
    failure_code: str | None = None,
):
    existing = db.query(models.DemoOperationAudit).filter_by(
        school_group_id=provisioning.school_group_id,
        action_type=action,
        operation_key=operation_key,
    ).one_or_none()
    if existing:
        return existing
    row = models.DemoOperationAudit(
        school_group_id=provisioning.school_group_id,
        demo_request_id=request.id,
        demo_provisioning_id=provisioning.id,
        branch_id=branch_id,
        actor_user_id=getattr(actor, "id", None),
        action_type=action,
        reason=reason or None,
        previous_values_json=_json(previous),
        new_values_json=_json(new),
        result_status=status,
        email_delivery_ids_json=_json(list(email_ids)),
        notification_ids_json=_json(list(notification_ids)),
        operation_key=operation_key,
        failure_code=failure_code,
    )
    db.add(row)
    db.flush()
    return row


def _existing_audit(db, provisioning_id: int, action: str, operation_key: str):
    return db.query(models.DemoOperationAudit).filter_by(
        demo_provisioning_id=provisioning_id,
        action_type=action,
        operation_key=operation_key,
    ).one_or_none()


def record_failed_operation(
    db: Session, *, actor, provisioning_id: int, action: str, reason: str = "",
    operation_key: str | None = None, failure_code: str,
):
    """Persist a rejected owner operation after its state transaction is rolled back."""
    key = _operation_key(operation_key)
    provisioning, request, group, entitlement, tenant_link, *_ = _context(
        db, provisioning_id, lock=False
    )
    return _audit(
        db, provisioning=provisioning, request=request, actor=actor,
        action=action, reason=str(reason or "").strip(), operation_key=key,
        previous=_state(provisioning, group, entitlement, tenant_link), new={},
        status="failed", failure_code=failure_code,
    )


def _customer_notification(
    db,
    *,
    provisioning,
    request,
    notification_type: str,
    title: str,
    message: str,
    operation_key: str,
):
    key = f"demo:{provisioning.id}:m8b9:{notification_type}:{operation_key}:saas:{request.requester_saas_account_id}"
    existing = db.query(models.SaaSDemoLifecycleNotification).filter_by(
        deduplication_key=key
    ).one_or_none()
    if existing:
        return existing
    row = models.SaaSDemoLifecycleNotification(
        demo_provisioning_id=provisioning.id,
        notification_type=notification_type,
        recipient_type="saas_account",
        recipient_saas_account_id=request.requester_saas_account_id,
        title=title,
        message=message,
        deduplication_key=key,
    )
    db.add(row)
    db.flush()
    return row


def _communication_refs(db, provisioning, operation_key: str):
    emails = [
        row[0] for row in db.query(models.SaaSDemoEmailDelivery.id).filter(
            models.SaaSDemoEmailDelivery.demo_provisioning_id == provisioning.id,
            models.SaaSDemoEmailDelivery.deduplication_key.like(f"%:{operation_key}"),
        ).all()
    ]
    lifecycle = [
        row[0] for row in db.query(models.SaaSDemoLifecycleNotification.id).filter(
            models.SaaSDemoLifecycleNotification.demo_provisioning_id == provisioning.id,
            models.SaaSDemoLifecycleNotification.deduplication_key.like(f"%:{operation_key}:%"),
        ).all()
    ]
    owner = [
        row[0] for row in db.query(operational_models.SystemNotification.id).filter(
            operational_models.SystemNotification.deduplication_key.like(f"%:{operation_key}:owner:%")
        ).all()
    ]
    return emails, lifecycle + owner


def expire_demo_now(
    db: Session, *, actor, provisioning_id: int, reason: str, operation_key: str | None = None
):
    _require_owner(actor)
    reason = _require_reason("expire_demo", reason)
    key = _operation_key(operation_key)
    existing = _existing_audit(db, provisioning_id, "expire_demo", key)
    if existing:
        return existing
    provisioning, request, group, entitlement, tenant_link, *_ = _context(db, provisioning_id)
    previous = _state(provisioning, group, entitlement, tenant_link)
    resolution = demo_lifecycle_service.resolve_demo_lifecycle(db, provisioning=provisioning)
    if not resolution.resolved or not resolution.can_access:
        raise DemoOperationError("Only an active demo may be expired.", reason_code="demo_not_active")
    now = demo_lifecycle_service.utc_now()
    provisioning.demo_expires_at = demo_lifecycle_service.storage_datetime(now)
    provisioning.reminder_due_at = demo_lifecycle_service.storage_datetime(now - timedelta(days=1))
    provisioning.expiry_policy = "custom"
    provisioning.reminder_sent_at = None
    db.flush()
    outcome = demo_lifecycle_service.process_demo_lifecycle(
        db, provisioning, observed_at=now, dry_run=False
    )
    if outcome["action"] != "expired":
        raise DemoOperationError("Demo expiration failed.", reason_code=outcome["reason_code"])
    emails, notifications = _communication_refs(
        db, provisioning, str(int(now.timestamp()))
    )
    return _audit(
        db, provisioning=provisioning, request=request, actor=actor,
        action="expire_demo", reason=reason, operation_key=key, previous=previous,
        new=_state(provisioning, group, entitlement, tenant_link), status="success",
        email_ids=emails, notification_ids=notifications,
    )


def _set_future_expiry(
    db: Session,
    *,
    actor,
    provisioning_id: int,
    new_expiry: datetime,
    reason: str,
    operation_key: str | None,
    action: str,
):
    _require_owner(actor)
    reason = _require_reason(action, reason)
    key = _operation_key(operation_key)
    existing = _existing_audit(db, provisioning_id, action, key)
    if existing:
        return existing
    expiry = demo_lifecycle_service.as_utc(new_expiry)
    now = demo_lifecycle_service.utc_now()
    if expiry is None or expiry <= now:
        raise DemoOperationError("The new expiry must be in the future.", reason_code="future_expiry_required")
    provisioning, request, group, entitlement, tenant_link, *_ = _context(db, provisioning_id)
    previous = _state(provisioning, group, entitlement, tenant_link)
    was_expired = not demo_lifecycle_service.resolve_demo_lifecycle(
        db, provisioning=provisioning, observed_at=now
    ).can_access
    if action == "reactivate_demo" and not was_expired:
        raise DemoOperationError(
            "Only an expired demo may be reactivated.",
            reason_code="demo_not_expired",
        )
    provisioning.demo_expires_at = demo_lifecycle_service.storage_datetime(expiry)
    provisioning.reminder_due_at = demo_lifecycle_service.storage_datetime(expiry - timedelta(days=1))
    provisioning.expiry_policy = "custom"
    provisioning.expired_at = None
    provisioning.reminder_sent_at = None
    provisioning.lifecycle_processing_status = "pending"
    provisioning.lifecycle_failure_code = None
    group.workspace_lifecycle_status = WorkspaceLifecycleStatus.ACTIVE.value
    entitlement.status = WorkspaceEntitlementStatus.ACTIVE.value
    entitlement.effective_to = demo_lifecycle_service.storage_datetime(expiry)
    tenant_link.tenant_status = "tenant_active"
    request.commercial_state_snapshot = CommercialState.CUSTOMER_DEMO_ACTIVE.value
    db.flush()
    email_type = "demo_reactivated" if was_expired else "demo_expiry_changed"
    notice_type = "demo_reactivated" if was_expired else "demo_expiry_changed"
    email = demo_email_service.create_intent(
        db, request, email_type, provisioning=provisioning, operation_key=key
    )
    customer = _customer_notification(
        db, provisioning=provisioning, request=request, notification_type=notice_type,
        title="Your TIS demo was reactivated" if was_expired else "Your demo expiry was updated",
        message="Your existing workspace is active through the new expiry date.",
        operation_key=key,
    )
    demo_notification_service.notify_platform_owners(
        db, request, "reactivated" if was_expired else "expiry_changed",
        provisioning=provisioning, operation_key=key,
    )
    db.flush()
    emails, notifications = _communication_refs(db, provisioning, key)
    if email.id not in emails:
        emails.append(email.id)
    if customer.id not in notifications:
        notifications.append(customer.id)
    return _audit(
        db, provisioning=provisioning, request=request, actor=actor,
        action=action, reason=reason, operation_key=key, previous=previous,
        new=_state(provisioning, group, entitlement, tenant_link), status="success",
        email_ids=emails, notification_ids=notifications,
    )


def reactivate_demo(db: Session, **kwargs):
    kwargs["action"] = "reactivate_demo"
    return _set_future_expiry(db, **kwargs)


def set_custom_expiry(db: Session, **kwargs):
    kwargs["action"] = "set_custom_expiry"
    return _set_future_expiry(db, **kwargs)


def send_final_day_reminder(
    db: Session, *, actor, provisioning_id: int, reason: str = "",
    operation_key: str | None = None, observed_at: datetime | None = None,
):
    _require_owner(actor)
    key = _operation_key(operation_key)
    existing = _existing_audit(db, provisioning_id, "send_manual_reminder", key)
    if existing:
        return existing
    provisioning, request, group, entitlement, tenant_link, organization, _ = _context(
        db, provisioning_id
    )
    resolution = demo_lifecycle_service.resolve_demo_lifecycle(
        db, provisioning=provisioning, observed_at=observed_at
    )
    now = demo_lifecycle_service.as_utc(observed_at) or demo_lifecycle_service.utc_now()
    timezone = ZoneInfo(resolution.timezone_name) if resolution.resolved else ZoneInfo("UTC")
    if (
        not resolution.can_access
        or (resolution.demo_expires_at.astimezone(timezone).date() - now.astimezone(timezone).date()).days != 1
    ):
        raise DemoOperationError(
            "Manual reminders are available only on the final calendar day before expiry.",
            reason_code="manual_reminder_not_eligible",
        )
    previous = _state(provisioning, group, entitlement, tenant_link)
    prior_count = db.query(models.DemoOperationAudit.id).filter_by(
        demo_provisioning_id=provisioning.id,
        action_type="send_manual_reminder",
        result_status="success",
    ).count()
    variant = prior_count % REMINDER_VARIANT_COUNT
    email = demo_email_service.create_intent(
        db, request, "manual_final_day_reminder", provisioning=provisioning,
        operation_key=key, payload={"variant": variant},
    )
    customer = _customer_notification(
        db, provisioning=provisioning, request=request,
        notification_type="manual_final_day_reminder",
        title="Your TIS demo expires soon",
        message=(
            "A friendly reminder that your demo is in its final day."
            if variant == 0 else
            "Your current TIS demo period is almost complete."
            if variant == 1 else
            "There is still time to review your TIS workspace today."
        ),
        operation_key=key,
    )
    demo_notification_service.notify_platform_owners(
        db, request, "manual_reminder", provisioning=provisioning, operation_key=key
    )
    db.flush()
    emails, notifications = _communication_refs(db, provisioning, key)
    if email.id not in emails:
        emails.append(email.id)
    if customer.id not in notifications:
        notifications.append(customer.id)
    return _audit(
        db, provisioning=provisioning, request=request, actor=actor,
        action="send_manual_reminder", reason=str(reason or "").strip(),
        operation_key=key, previous=previous,
        new={"variant": variant, "expiry": provisioning.demo_expires_at},
        status="success", email_ids=emails, notification_ids=notifications,
    )


def change_access_profile(
    db: Session, *, actor, provisioning_id: int, profile: str, reason: str,
    operation_key: str | None = None, branch_id: int | None = None,
    product_features=(), ai_features=(), ai_allowances=None,
    unrestricted_ai_features=(),
):
    _require_owner(actor)
    reason = _require_reason(
        "change_custom_features" if str(profile).lower() == "custom" else "change_access_profile",
        reason,
    )
    key = _operation_key(operation_key)
    existing = _existing_audit(db, provisioning_id, "change_access_profile", key)
    if existing:
        return existing
    provisioning, request, group, *_ = _context(db, provisioning_id)
    row, previous, effective = demo_access_service.set_access_policy(
        db, actor=actor, school_group_id=group.id, branch_id=branch_id,
        profile=profile, reason=reason, product_features=product_features,
        ai_features=ai_features, ai_allowances=ai_allowances,
        unrestricted_ai_features=unrestricted_ai_features,
    )
    material = asdict(previous) != asdict(effective)
    email_ids, notification_ids = [], []
    if material:
        email = demo_email_service.create_intent(
            db, request, "demo_access_profile_changed", provisioning=provisioning,
            operation_key=key, payload={"profile_name": effective.profile.title()},
        )
        customer = _customer_notification(
            db, provisioning=provisioning, request=request,
            notification_type="demo_access_profile_changed",
            title="Your TIS demo access was updated",
            message="The features available in your demo were updated.",
            operation_key=key,
        )
        demo_notification_service.notify_platform_owners(
            db, request, "access_profile_changed", provisioning=provisioning,
            operation_key=key,
        )
        db.flush()
        email_ids, notification_ids = _communication_refs(db, provisioning, key)
        if email.id not in email_ids:
            email_ids.append(email.id)
        if customer.id not in notification_ids:
            notification_ids.append(customer.id)
    return _audit(
        db, provisioning=provisioning, request=request, actor=actor,
        action="change_access_profile", reason=reason, operation_key=key,
        branch_id=branch_id, previous=asdict(previous), new=asdict(effective),
        status="success", email_ids=email_ids, notification_ids=notification_ids,
    )


def run_lifecycle_for_demo(
    db: Session, *, actor, provisioning_id: int, reason: str = "",
    operation_key: str | None = None, observed_at: datetime | None = None,
) -> LifecycleRunSummary:
    _require_owner(actor)
    key = _operation_key(operation_key)
    existing = _existing_audit(db, provisioning_id, "run_lifecycle", key)
    if existing:
        return LifecycleRunSummary(1, 0, 0, 0, 0, 1)
    provisioning, request, group, entitlement, tenant_link, *_ = _context(
        db, provisioning_id
    )
    previous = _state(provisioning, group, entitlement, tenant_link)
    outcome = demo_lifecycle_service.process_demo_lifecycle(
        db, provisioning, observed_at=observed_at, dry_run=False
    )
    summary = LifecycleRunSummary(
        demos_checked=1,
        reminders_created=1 if outcome["action"] == "reminder_created" else 0,
        demos_expired=1 if outcome["action"] == "expired" else 0,
        no_action_count=1 if outcome["action"] == "unchanged" else 0,
        failures=1 if outcome["action"] in {"failed", "manual_review"} else 0,
        skipped_or_deduplicated=0,
    )
    _audit(
        db, provisioning=provisioning, request=request, actor=actor,
        action="run_lifecycle", reason=str(reason or "").strip(), operation_key=key,
        previous=previous, new={"outcome": outcome, "summary": asdict(summary)},
        status="failed" if summary.failures else "success",
        failure_code=outcome.get("reason_code") if summary.failures else None,
    )
    return summary


def run_lifecycle_for_all(
    session_factory, *, actor, reason: str = "", operation_key: str | None = None,
    observed_at: datetime | None = None,
) -> LifecycleRunSummary:
    _require_owner(actor)
    key = _operation_key(operation_key)
    result = demo_lifecycle_service.process_due_demo_lifecycles(
        session_factory, dry_run=False, observed_at=observed_at
    )
    skipped = sum(1 for row in result.rows if row.get("reason_code") in {"already_expired"})
    summary = LifecycleRunSummary(
        demos_checked=result.scanned,
        reminders_created=result.reminders_created,
        demos_expired=result.expired,
        no_action_count=result.unchanged,
        failures=result.failed + result.manual_review,
        skipped_or_deduplicated=skipped,
    )
    with session_factory() as db:
        for row in result.rows:
            provisioning = None
            if row.get("provisioning_uuid"):
                provisioning = db.query(models.SaaSDemoWorkspaceProvisioning).filter_by(
                    provisioning_uuid=row["provisioning_uuid"]
                ).one_or_none()
            if provisioning is None:
                continue
            request = db.get(models.SaaSDemoRequest, provisioning.demo_request_id)
            _audit(
                db, provisioning=provisioning, request=request, actor=actor,
                action="run_lifecycle_global", reason=str(reason or "").strip(),
                operation_key=key, previous={}, new={"summary": asdict(summary)},
                status="failed" if row.get("action") == "failed" else "success",
                failure_code=row.get("reason_code") if row.get("action") == "failed" else None,
            )
        db.commit()
    return summary
