from __future__ import annotations

from sqlalchemy.orm import Session

import auth
import models as operational_models


EVENT_CONTENT = {
    "submitted": ("New demo request", "A customer demo request is awaiting review.", "info"),
    "approved": ("Demo approved and activated", "A customer demo workspace is active.", "info"),
    "declined": ("Demo request declined", "A customer demo request was declined.", "info"),
    "day_six_reminder": ("Demo expires soon", "A customer demo reaches expiry in approximately one day.", "warning"),
    "expired": ("Demo expired", "A customer demo expired and its workspace data remains preserved.", "warning"),
    "reactivated": ("Demo reactivated", "A customer demo was reactivated with a new expiry.", "info"),
    "expiry_changed": ("Demo expiry updated", "A customer demo expiry date was updated.", "info"),
    "manual_reminder": ("Demo reminder sent", "A final-day demo reminder was sent.", "info"),
    "access_profile_changed": ("Demo access updated", "Customer-visible demo feature access was updated.", "info"),
}


def notify_platform_owners(
    db: Session,
    demo_request,
    event_type: str,
    *,
    provisioning=None,
    operation_key: str | None = None,
) -> int:
    title, message, severity = EVENT_CONTENT[event_type]
    owners = db.query(operational_models.User).filter(
        operational_models.User.user_type == auth.USER_TYPE_PLATFORM,
        operational_models.User.platform_role == auth.PLATFORM_ROLE_OWNER,
        operational_models.User.is_active.is_(True),
    ).all()
    created = 0
    platform_scope_group_id = getattr(provisioning, "school_group_id", None)
    if not platform_scope_group_id:
        platform_scope_group_id = db.query(operational_models.SchoolGroup.id).order_by(
            operational_models.SchoolGroup.id
        ).limit(1).scalar()
    for owner in owners:
        operation_suffix = f":{str(operation_key).strip()}" if operation_key else ""
        key = f"demo:{demo_request.id}:notification:{event_type}{operation_suffix}:owner:{owner.id}"
        if db.query(operational_models.SystemNotification).filter_by(deduplication_key=key).first():
            continue
        db.add(operational_models.SystemNotification(
            school_group_id=platform_scope_group_id,
            recipient_user_id=str(owner.user_id),
            request_type=f"saas_demo_{event_type}",
            title=title,
            message=message,
            status="New",
            recipient_scope="User",
            destination_url=f"/saas-admin/demo-requests/{demo_request.request_uuid}",
            deduplication_key=key,
            category="saas_demo",
            severity=severity,
        ))
        created += 1
    return created
