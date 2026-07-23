from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

import auth
import models as operational_models
from commercial_entitlements import CommercialState, WorkspaceEntitlementStatus
from demo_workflow import (
    DemoLifecycleEventType,
    DemoLifecycleNotificationRecipient,
    DemoLifecycleNotificationType,
    DemoLifecycleProcessingStatus,
    DemoLifecycleState,
)
from saas import commercial_state_service, models
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


DEMO_DURATION = timedelta(days=7)
DEMO_REMINDER_AFTER = timedelta(days=6)


@dataclass(frozen=True)
class DemoLifecycleResolution:
    resolution_status: str
    reason_code: str
    lifecycle_state: str
    school_group_id: int | None
    demo_provisioning_id: int | None
    demo_started_at: datetime | None
    reminder_due_at: datetime | None
    demo_expires_at: datetime | None
    reminder_sent_at: datetime | None
    expired_at: datetime | None
    lifecycle_processing_status: str
    timezone_name: str
    display_started_at: datetime | None
    display_reminder_due_at: datetime | None
    display_expires_at: datetime | None
    display_expired_at: datetime | None
    seconds_remaining: int | None
    days_remaining: int | None
    time_remaining_label: str

    @property
    def resolved(self) -> bool:
        return self.resolution_status == "resolved"

    @property
    def can_access(self) -> bool:
        return self.resolved and self.lifecycle_state in {
            DemoLifecycleState.ACTIVE.value,
            DemoLifecycleState.REMINDER_DUE.value,
        }


@dataclass
class DemoLifecycleBatchResult:
    dry_run: bool
    scanned: int = 0
    reminders_due: int = 0
    reminders_created: int = 0
    expirations_due: int = 0
    expired: int = 0
    unchanged: int = 0
    manual_review: int = 0
    failed: int = 0
    rows: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": "failed" if self.failed else "ok",
            "mode": "dry_run" if self.dry_run else "apply",
            "scanned": self.scanned,
            "reminders_due": self.reminders_due,
            "reminders_created": self.reminders_created,
            "expirations_due": self.expirations_due,
            "expired": self.expired,
            "unchanged": self.unchanged,
            "manual_review": self.manual_review,
            "failed": self.failed,
            "rows": self.rows,
        }


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def storage_datetime(value: datetime | None) -> datetime | None:
    observed = as_utc(value)
    return observed.replace(tzinfo=None) if observed else None


def calculate_lifecycle_dates(activated_at) -> tuple[datetime, datetime]:
    started_at = as_utc(activated_at)
    if started_at is None:
        raise ValueError("Demo activation timestamp is required.")
    return started_at + DEMO_REMINDER_AFTER, started_at + DEMO_DURATION


def _manual_review(
    reason_code: str,
    *,
    provisioning=None,
    school_group_id: int | None = None,
) -> DemoLifecycleResolution:
    return DemoLifecycleResolution(
        resolution_status="manual_review",
        reason_code=reason_code,
        lifecycle_state=DemoLifecycleState.MANUAL_REVIEW.value,
        school_group_id=school_group_id or getattr(provisioning, "school_group_id", None),
        demo_provisioning_id=getattr(provisioning, "id", None),
        demo_started_at=as_utc(getattr(provisioning, "activated_at", None)),
        reminder_due_at=as_utc(getattr(provisioning, "reminder_due_at", None)),
        demo_expires_at=as_utc(getattr(provisioning, "demo_expires_at", None)),
        reminder_sent_at=as_utc(getattr(provisioning, "reminder_sent_at", None)),
        expired_at=as_utc(getattr(provisioning, "expired_at", None)),
        lifecycle_processing_status=str(
            getattr(provisioning, "lifecycle_processing_status", "") or ""
        ),
        timezone_name="UTC",
        display_started_at=None,
        display_reminder_due_at=None,
        display_expires_at=None,
        display_expired_at=None,
        seconds_remaining=None,
        days_remaining=None,
        time_remaining_label="Unavailable",
    )


def get_provisioning_for_school_group(db: Session, school_group_id: int):
    return db.query(models.SaaSDemoWorkspaceProvisioning).filter(
        models.SaaSDemoWorkspaceProvisioning.school_group_id == school_group_id
    ).one_or_none()


def _load_context(db: Session, provisioning):
    demo_request = db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.id == provisioning.demo_request_id
    ).one_or_none()
    group = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == provisioning.school_group_id
    ).one_or_none()
    entitlement = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.id == provisioning.workspace_entitlement_id
    ).one_or_none()
    tenant_link = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.id == provisioning.tenant_provisioning_link_id
    ).one_or_none()
    organization = (
        db.query(models.PendingOrganization).filter(
            models.PendingOrganization.id == demo_request.pending_organization_id
        ).one_or_none()
        if demo_request
        else None
    )
    account = (
        db.query(models.SaaSAccount).filter(
            models.SaaSAccount.id == demo_request.requester_saas_account_id
        ).one_or_none()
        if demo_request
        else None
    )
    return demo_request, group, entitlement, tenant_link, organization, account


def resolve_demo_lifecycle(
    db: Session,
    *,
    provisioning=None,
    school_group_id: int | None = None,
    observed_at: datetime | None = None,
) -> DemoLifecycleResolution:
    if provisioning is None:
        try:
            group_id = int(school_group_id or 0)
        except (TypeError, ValueError):
            group_id = 0
        if group_id <= 0:
            return _manual_review("invalid_school_group")
        provisioning = get_provisioning_for_school_group(db, group_id)
        if provisioning is None:
            return _manual_review("missing_demo_provisioning", school_group_id=group_id)

    (
        demo_request,
        group,
        entitlement,
        tenant_link,
        organization,
        account,
    ) = _load_context(db, provisioning)
    if not all((demo_request, group, entitlement, tenant_link, organization, account)):
        return _manual_review("incomplete_demo_lifecycle_relationships", provisioning=provisioning)
    if (
        group.workspace_classification != WorkspaceClassification.CUSTOMER_DEMO.value
        or entitlement.entitlement_type != "demo"
        or tenant_link.demo_request_id != demo_request.id
        or tenant_link.school_group_id != group.id
        or demo_request.school_group_id != group.id
        or demo_request.status != "approved"
    ):
        return _manual_review("inconsistent_demo_lifecycle_relationships", provisioning=provisioning)

    started_at = as_utc(provisioning.activated_at)
    reminder_due_at = as_utc(provisioning.reminder_due_at)
    expires_at = as_utc(provisioning.demo_expires_at)
    if not all((started_at, reminder_due_at, expires_at)):
        return _manual_review("missing_demo_lifecycle_timestamps", provisioning=provisioning)
    expected_reminder, expected_expiration = calculate_lifecycle_dates(started_at)
    if (
        abs((reminder_due_at - expected_reminder).total_seconds()) > 1
        or abs((expires_at - expected_expiration).total_seconds()) > 1
        or reminder_due_at >= expires_at
    ):
        return _manual_review("inconsistent_demo_lifecycle_timestamps", provisioning=provisioning)

    timezone_name = str(organization.timezone or "UTC").strip() or "UTC"
    try:
        display_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return _manual_review("invalid_demo_workspace_timezone", provisioning=provisioning)

    now = as_utc(observed_at) or utc_now()
    expired_at = as_utc(provisioning.expired_at)
    processing_status = str(provisioning.lifecycle_processing_status or "").strip().lower()
    if processing_status not in {
        item.value for item in DemoLifecycleProcessingStatus
    }:
        return _manual_review("invalid_lifecycle_processing_status", provisioning=provisioning)
    if expired_at and abs((expired_at - expires_at).total_seconds()) > 1:
        return _manual_review("inconsistent_demo_expired_timestamp", provisioning=provisioning)
    reminder_sent_at = as_utc(provisioning.reminder_sent_at)
    if reminder_sent_at and (
        reminder_sent_at < reminder_due_at - timedelta(seconds=1)
        or reminder_sent_at > now + timedelta(seconds=1)
    ):
        return _manual_review("inconsistent_demo_reminder_timestamp", provisioning=provisioning)
    if expired_at and expired_at > now + timedelta(seconds=1):
        return _manual_review("future_demo_expired_timestamp", provisioning=provisioning)

    lifecycle_state = DemoLifecycleState.ACTIVE
    if expired_at:
        if (
            group.workspace_lifecycle_status != WorkspaceLifecycleStatus.SUSPENDED.value
            or entitlement.status not in {
                WorkspaceEntitlementStatus.INACTIVE.value,
                WorkspaceEntitlementStatus.SUSPENDED.value,
                WorkspaceEntitlementStatus.ENDED.value,
            }
            or processing_status != DemoLifecycleProcessingStatus.EXPIRED.value
        ):
            return _manual_review("incomplete_demo_expiration_state", provisioning=provisioning)
        lifecycle_state = DemoLifecycleState.EXPIRED
    elif group.workspace_lifecycle_status == WorkspaceLifecycleStatus.SUSPENDED.value:
        lifecycle_state = DemoLifecycleState.SUSPENDED
    elif (
        group.workspace_lifecycle_status != WorkspaceLifecycleStatus.ACTIVE.value
        or entitlement.status != WorkspaceEntitlementStatus.ACTIVE.value
    ):
        return _manual_review("active_demo_state_mismatch", provisioning=provisioning)
    elif now >= expires_at:
        lifecycle_state = DemoLifecycleState.EXPIRED
    elif now >= reminder_due_at:
        lifecycle_state = DemoLifecycleState.REMINDER_DUE

    remaining = max(0, math.ceil((expires_at - now).total_seconds()))
    remaining_days, remainder = divmod(remaining, 86400)
    remaining_hours, remainder = divmod(remainder, 3600)
    remaining_minutes = math.ceil(remainder / 60) if remainder else 0
    if remaining <= 0:
        remaining_label = "Expired"
    elif remaining_days:
        remaining_label = (
            f"{remaining_days} day(s), {remaining_hours} hour(s)"
        )
    elif remaining_hours:
        remaining_label = (
            f"{remaining_hours} hour(s), {remaining_minutes} minute(s)"
        )
    else:
        remaining_label = f"{max(1, remaining_minutes)} minute(s)"
    return DemoLifecycleResolution(
        resolution_status="resolved",
        reason_code="resolved",
        lifecycle_state=lifecycle_state.value,
        school_group_id=group.id,
        demo_provisioning_id=provisioning.id,
        demo_started_at=started_at,
        reminder_due_at=reminder_due_at,
        demo_expires_at=expires_at,
        reminder_sent_at=reminder_sent_at,
        expired_at=expired_at,
        lifecycle_processing_status=processing_status,
        timezone_name=timezone_name,
        display_started_at=started_at.astimezone(display_timezone),
        display_reminder_due_at=reminder_due_at.astimezone(display_timezone),
        display_expires_at=expires_at.astimezone(display_timezone),
        display_expired_at=(
            expired_at.astimezone(display_timezone) if expired_at else None
        ),
        seconds_remaining=remaining,
        days_remaining=math.ceil(remaining / 86400),
        time_remaining_label=remaining_label,
    )


def format_lifecycle_datetime(value: datetime | None) -> str:
    if value is None:
        return "Not available"
    return value.strftime("%B %d, %Y at %H:%M %Z")


def list_lifecycle_events(db: Session, provisioning):
    if provisioning is None:
        return []
    return db.query(models.SaaSDemoLifecycleEvent).filter(
        models.SaaSDemoLifecycleEvent.demo_provisioning_id == provisioning.id
    ).order_by(
        models.SaaSDemoLifecycleEvent.created_at.asc(),
        models.SaaSDemoLifecycleEvent.id.asc(),
    ).all()


def list_lifecycle_notifications(db: Session, provisioning):
    if provisioning is None:
        return []
    return db.query(models.SaaSDemoLifecycleNotification).filter(
        models.SaaSDemoLifecycleNotification.demo_provisioning_id == provisioning.id
    ).order_by(
        models.SaaSDemoLifecycleNotification.created_at.desc(),
        models.SaaSDemoLifecycleNotification.id.desc(),
    ).all()


def list_customer_notifications(db: Session, provisioning, saas_account_id: int):
    if provisioning is None:
        return []
    return db.query(models.SaaSDemoLifecycleNotification).filter(
        models.SaaSDemoLifecycleNotification.demo_provisioning_id == provisioning.id,
        models.SaaSDemoLifecycleNotification.recipient_saas_account_id == saas_account_id,
    ).order_by(
        models.SaaSDemoLifecycleNotification.created_at.desc(),
        models.SaaSDemoLifecycleNotification.id.desc(),
    ).all()


def _add_event(
    db: Session,
    provisioning,
    event_type: DemoLifecycleEventType,
    *,
    deduplication_key: str,
    actor_type: str = "system",
    actor_user_id: int | None = None,
    event_status: str = "ok",
    reason_code: str | None = None,
    details: dict | None = None,
):
    existing = db.query(models.SaaSDemoLifecycleEvent).filter(
        models.SaaSDemoLifecycleEvent.deduplication_key == deduplication_key
    ).one_or_none()
    if existing:
        return existing
    row = models.SaaSDemoLifecycleEvent(
        demo_provisioning_id=provisioning.id,
        event_type=event_type.value,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        event_status=event_status,
        reason_code=reason_code,
        deduplication_key=deduplication_key,
        details_json=json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
    )
    db.add(row)
    return row


def _create_reminder_notifications(db: Session, provisioning, demo_request) -> int:
    title = "Your TIS demo expires soon"
    message = (
        "Your demo expires in approximately one day. A subscription is required "
        "to retain operational access. Your workspace data will be preserved."
    )
    created = 0
    recipients = [
        (
            DemoLifecycleNotificationRecipient.SAAS_ACCOUNT.value,
            demo_request.requester_saas_account_id,
            None,
            f"demo:{provisioning.id}:reminder:saas:{demo_request.requester_saas_account_id}",
        )
    ]
    owners = db.query(operational_models.User).filter(
        operational_models.User.user_type == auth.USER_TYPE_PLATFORM,
        operational_models.User.platform_role == auth.PLATFORM_ROLE_OWNER,
        operational_models.User.is_active.is_(True),
    ).all()
    if not owners:
        raise ValueError("No active Platform Owner is available for demo lifecycle notification.")
    for owner in owners:
        recipients.append(
            (
                DemoLifecycleNotificationRecipient.PLATFORM_OWNER.value,
                None,
                owner.id,
                f"demo:{provisioning.id}:reminder:owner:{owner.id}",
            )
        )
    for recipient_type, account_id, user_id, deduplication_key in recipients:
        existing = db.query(models.SaaSDemoLifecycleNotification).filter(
            models.SaaSDemoLifecycleNotification.deduplication_key == deduplication_key
        ).one_or_none()
        if existing:
            continue
        db.add(
            models.SaaSDemoLifecycleNotification(
                demo_provisioning_id=provisioning.id,
                notification_type=DemoLifecycleNotificationType.EXPIRATION_REMINDER.value,
                recipient_type=recipient_type,
                recipient_saas_account_id=account_id,
                recipient_user_id=user_id,
                title=title,
                message=message,
                deduplication_key=deduplication_key,
            )
        )
        created += 1
    return created


def _process_reminder(db: Session, provisioning, resolution, now: datetime) -> int:
    demo_request = db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.id == provisioning.demo_request_id
    ).one()
    with db.begin_nested():
        _add_event(
            db,
            provisioning,
            DemoLifecycleEventType.REMINDER_BECAME_DUE,
            deduplication_key=f"demo:{provisioning.id}:reminder-due",
            details={"demo_expires_at": resolution.demo_expires_at.isoformat()},
        )
        created = _create_reminder_notifications(db, provisioning, demo_request)
        provisioning.reminder_sent_at = storage_datetime(now)
        provisioning.lifecycle_processing_status = DemoLifecycleProcessingStatus.PENDING.value
        provisioning.lifecycle_last_processed_at = storage_datetime(now)
        provisioning.lifecycle_failure_code = None
        _add_event(
            db,
            provisioning,
            DemoLifecycleEventType.REMINDER_NOTIFICATION_CREATED,
            deduplication_key=f"demo:{provisioning.id}:reminder-notification-created",
            details={"recipient_count": created},
        )
        db.flush()
    return created


def _record_processing_failure(
    db: Session,
    provisioning,
    *,
    now: datetime,
    reason_code: str,
    exception_type: str,
) -> None:
    provisioning.lifecycle_processing_status = DemoLifecycleProcessingStatus.FAILED.value
    provisioning.lifecycle_last_processed_at = storage_datetime(now)
    provisioning.lifecycle_failure_code = reason_code
    _add_event(
        db,
        provisioning,
        DemoLifecycleEventType.LIFECYCLE_PROCESSING_FAILED,
        deduplication_key=(
            f"demo:{provisioning.id}:lifecycle-failed:{reason_code}:"
            f"{int(now.timestamp())}:{uuid.uuid4().hex[:8]}"
        ),
        event_status="failed",
        reason_code=reason_code,
        details={"exception_type": exception_type},
    )
    db.flush()


def _process_expiration(db: Session, provisioning, resolution, now: datetime) -> bool:
    attempt_key = f"{int(now.timestamp())}-{uuid.uuid4().hex[:8]}"
    provisioning.lifecycle_processing_status = DemoLifecycleProcessingStatus.PROCESSING.value
    provisioning.lifecycle_last_processed_at = storage_datetime(now)
    _add_event(
        db,
        provisioning,
        DemoLifecycleEventType.EXPIRATION_PROCESSING_STARTED,
        deduplication_key=f"demo:{provisioning.id}:expiration-start:{attempt_key}",
    )
    db.flush()
    try:
        with db.begin_nested():
            (
                demo_request,
                group,
                entitlement,
                tenant_link,
                _organization,
                _account,
            ) = _load_context(db, provisioning)
            group.workspace_lifecycle_status = WorkspaceLifecycleStatus.SUSPENDED.value
            entitlement.status = WorkspaceEntitlementStatus.ENDED.value
            entitlement.effective_to = storage_datetime(resolution.demo_expires_at)
            tenant_link.tenant_status = "demo_expired"
            demo_request.commercial_state_snapshot = CommercialState.SUSPENDED.value
            try:
                snapshot = json.loads(demo_request.entitlement_snapshot_json or "{}")
            except (TypeError, ValueError):
                snapshot = {}
            snapshot.update(
                {
                    "resolution_status": "resolved",
                    "commercial_state": CommercialState.SUSPENDED.value,
                    "demo_lifecycle_state": DemoLifecycleState.EXPIRED.value,
                    "demo_expires_at": resolution.demo_expires_at.isoformat(),
                    "workspace_entitlement": {
                        "entitlement_type": "demo",
                        "status": WorkspaceEntitlementStatus.ENDED.value,
                        "source": entitlement.source,
                    },
                }
            )
            demo_request.entitlement_snapshot_json = json.dumps(
                snapshot,
                separators=(",", ":"),
                sort_keys=True,
            )
            provisioning.expired_at = storage_datetime(resolution.demo_expires_at)
            provisioning.lifecycle_processing_status = DemoLifecycleProcessingStatus.EXPIRED.value
            provisioning.lifecycle_last_processed_at = storage_datetime(now)
            provisioning.lifecycle_failure_code = None
            _add_event(
                db,
                provisioning,
                DemoLifecycleEventType.DEMO_EXPIRED,
                deduplication_key=f"demo:{provisioning.id}:expired",
                details={"expired_at": resolution.demo_expires_at.isoformat()},
            )
            _add_event(
                db,
                provisioning,
                DemoLifecycleEventType.WORKSPACE_SUSPENDED,
                deduplication_key=f"demo:{provisioning.id}:workspace-suspended",
            )
            db.flush()
            commercial = commercial_state_service.resolve_commercial_state(db, group.id)
            if (
                not commercial.resolved
                or commercial.commercial_state != CommercialState.SUSPENDED.value
            ):
                raise ValueError("Expired demo workspace did not resolve as suspended.")
    except Exception as exc:
        _record_processing_failure(
            db,
            provisioning,
            reason_code="demo_expiration_failed",
            exception_type=exc.__class__.__name__,
            now=now,
        )
        return False
    return True


def process_demo_lifecycle(
    db: Session,
    provisioning,
    *,
    observed_at: datetime | None = None,
    dry_run: bool = True,
) -> dict:
    now = as_utc(observed_at) or utc_now()
    resolution = resolve_demo_lifecycle(
        db,
        provisioning=provisioning,
        observed_at=now,
    )
    if not resolution.resolved:
        if not dry_run:
            _record_processing_failure(
                db,
                provisioning,
                now=now,
                reason_code=resolution.reason_code,
                exception_type="DemoLifecycleManualReview",
            )
        return {"action": "manual_review", "reason_code": resolution.reason_code}
    if resolution.lifecycle_state == DemoLifecycleState.EXPIRED.value:
        if provisioning.expired_at:
            return {"action": "unchanged", "reason_code": "already_expired"}
        if dry_run:
            return {"action": "expire", "reason_code": "expiration_due"}
        if not _process_expiration(db, provisioning, resolution, now):
            return {
                "action": "failed",
                "reason_code": "demo_expiration_failed",
            }
        return {"action": "expired", "reason_code": "demo_expired"}
    if (
        resolution.lifecycle_state == DemoLifecycleState.REMINDER_DUE.value
        and not provisioning.reminder_sent_at
    ):
        if dry_run:
            return {"action": "remind", "reason_code": "reminder_due"}
        try:
            created = _process_reminder(db, provisioning, resolution, now)
        except Exception as exc:
            _record_processing_failure(
                db,
                provisioning,
                now=now,
                reason_code="demo_reminder_failed",
                exception_type=exc.__class__.__name__,
            )
            return {"action": "failed", "reason_code": "demo_reminder_failed"}
        return {
            "action": "reminder_created",
            "reason_code": "reminder_created",
            "notification_count": created,
        }
    return {"action": "unchanged", "reason_code": "no_lifecycle_action_due"}


def process_due_demo_lifecycles(
    session_factory,
    *,
    dry_run: bool = True,
    batch_size: int = 100,
    request_uuid: str | None = None,
    observed_at: datetime | None = None,
) -> DemoLifecycleBatchResult:
    result = DemoLifecycleBatchResult(dry_run=dry_run)
    discovery = session_factory()
    try:
        query = discovery.query(models.SaaSDemoWorkspaceProvisioning.id).join(
            models.SaaSDemoRequest,
            models.SaaSDemoRequest.id
            == models.SaaSDemoWorkspaceProvisioning.demo_request_id,
        ).filter(
            models.SaaSDemoWorkspaceProvisioning.provisioning_status == "active"
        )
        if request_uuid:
            query = query.filter(models.SaaSDemoRequest.request_uuid == request_uuid)
        ids = [
            row[0]
            for row in query.order_by(
                models.SaaSDemoWorkspaceProvisioning.id.asc()
            ).limit(max(1, min(int(batch_size or 100), 1000))).all()
        ]
    finally:
        discovery.close()

    for provisioning_id in ids:
        db = session_factory()
        result.scanned += 1
        try:
            provisioning = db.query(models.SaaSDemoWorkspaceProvisioning).filter(
                models.SaaSDemoWorkspaceProvisioning.id == provisioning_id
            ).with_for_update().one()
            outcome = process_demo_lifecycle(
                db,
                provisioning,
                observed_at=observed_at,
                dry_run=dry_run,
            )
            action = outcome["action"]
            if action == "remind":
                result.reminders_due += 1
            elif action == "reminder_created":
                result.reminders_due += 1
                result.reminders_created += 1
            elif action == "expire":
                result.expirations_due += 1
            elif action == "expired":
                result.expirations_due += 1
                result.expired += 1
            elif action == "manual_review":
                result.manual_review += 1
            elif action == "failed":
                result.failed += 1
            else:
                result.unchanged += 1
            result.rows.append(
                {
                    "provisioning_uuid": provisioning.provisioning_uuid,
                    **outcome,
                }
            )
            if dry_run:
                db.rollback()
            else:
                db.commit()
        except Exception as exc:
            db.rollback()
            result.failed += 1
            result.rows.append(
                {
                    "provisioning_id": provisioning_id,
                    "action": "failed",
                    "reason_code": "demo_lifecycle_processing_failed",
                    "exception_type": exc.__class__.__name__,
                }
            )
        finally:
            db.close()
    return result


def record_access_blocked(db: Session, school_group_id: int, user) -> bool:
    provisioning = get_provisioning_for_school_group(db, school_group_id)
    if provisioning is None:
        return False
    deduplication_key = f"demo:{provisioning.id}:access-blocked"
    if db.query(models.SaaSDemoLifecycleEvent.id).filter(
        models.SaaSDemoLifecycleEvent.deduplication_key == deduplication_key
    ).first():
        return False
    _add_event(
        db,
        provisioning,
        DemoLifecycleEventType.ACCESS_BLOCKED,
        deduplication_key=deduplication_key,
        actor_type="tenant_user",
        actor_user_id=getattr(user, "id", None),
    )
    db.flush()
    return True
