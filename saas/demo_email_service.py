from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

import branding_storage
import email_service
import email_templates
import public_url
from saas import demo_lifecycle_service, models


EMAIL_TYPES = {
    "request_received",
    "demo_approved",
    "demo_declined",
    "day_six_reminder",
    "demo_expired",
    "subscription_invitation",
    "demo_reactivated",
    "demo_expiry_changed",
    "manual_final_day_reminder",
    "demo_access_profile_changed",
}


def create_intent(
    db: Session,
    demo_request,
    email_type: str,
    *,
    provisioning=None,
    operation_key: str | None = None,
    payload: dict | None = None,
):
    if email_type not in EMAIL_TYPES:
        raise ValueError("Unsupported demo email type.")
    suffix = f":{str(operation_key).strip()}" if operation_key else ""
    key = f"demo:{demo_request.id}:email:{email_type}{suffix}"
    existing = db.query(models.SaaSDemoEmailDelivery).filter_by(deduplication_key=key).one_or_none()
    if existing:
        return existing
    account = db.get(models.SaaSAccount, demo_request.requester_saas_account_id)
    if account is None:
        raise ValueError("Demo requester account is unavailable.")
    row = models.SaaSDemoEmailDelivery(
        demo_request_id=demo_request.id,
        demo_provisioning_id=getattr(provisioning, "id", None),
        email_type=email_type,
        recipient_email=str(account.email or "").strip(),
        deduplication_key=key,
        payload_json=json.dumps(payload or {}, sort_keys=True, separators=(",", ":")),
    )
    db.add(row)
    db.flush()
    return row


def _content(db: Session, row):
    request = db.get(models.SaaSDemoRequest, row.demo_request_id)
    organization = db.get(models.PendingOrganization, request.pending_organization_id)
    provisioning = db.get(models.SaaSDemoWorkspaceProvisioning, row.demo_provisioning_id) if row.demo_provisioning_id else None
    base = public_url.public_base_url()
    logo = public_url.public_static_asset_url(
        branding_storage.tis_logo_relative_path(theme="light", compact=True)
    )
    status_url = f"{base}/saas/demo-requests/{request.request_uuid}"
    subscribe_url = f"{base}/saas/login?next_path=/saas/demo-requests/{request.request_uuid}"
    name = str(organization.organization_name or "Your organization")
    try:
        payload = json.loads(row.payload_json or "{}")
    except (TypeError, ValueError):
        payload = {}
    builders = {
        "request_received": lambda: email_templates.build_demo_request_received_email(
            organization_name=name, status_url=status_url, logo_url=logo
        ),
        "demo_declined": lambda: email_templates.build_demo_declined_email(
            organization_name=name, status_url=status_url, logo_url=logo
        ),
        "demo_expired": lambda: email_templates.build_demo_expired_email(
            organization_name=name, subscribe_url=subscribe_url, logo_url=logo
        ),
        "subscription_invitation": lambda: email_templates.build_demo_subscription_invitation_email(
            organization_name=name, subscribe_url=subscribe_url, logo_url=logo
        ),
    }
    if provisioning:
        lifecycle = demo_lifecycle_service.resolve_demo_lifecycle(db, provisioning=provisioning)
        start = demo_lifecycle_service.format_lifecycle_datetime(lifecycle.display_started_at)
        expiry = demo_lifecycle_service.format_lifecycle_datetime(lifecycle.display_expires_at)
        builders["demo_approved"] = lambda: email_templates.build_demo_approved_email(
            organization_name=name, start_date=start, expiry_date=expiry,
            login_url=f"{base}/login", registered_email=row.recipient_email, logo_url=logo,
        )
        builders["day_six_reminder"] = lambda: email_templates.build_demo_day_six_reminder_email(
            organization_name=name, expiry_date=expiry, subscribe_url=subscribe_url, logo_url=logo
        )
        builders["demo_reactivated"] = lambda: email_templates.build_demo_reactivated_email(
            organization_name=name, expiry_date=expiry, login_url=f"{base}/login", logo_url=logo
        )
        builders["demo_expiry_changed"] = lambda: email_templates.build_demo_expiry_changed_email(
            organization_name=name, expiry_date=expiry, login_url=f"{base}/login", logo_url=logo
        )
        builders["manual_final_day_reminder"] = lambda: email_templates.build_demo_manual_reminder_email(
            organization_name=name, expiry_date=expiry, subscribe_url=subscribe_url,
            logo_url=logo, variant=int(payload.get("variant", 0)),
        )
        builders["demo_access_profile_changed"] = lambda: email_templates.build_demo_access_profile_changed_email(
            organization_name=name, profile_name=str(payload.get("profile_name", "Updated")),
            login_url=f"{base}/login", logo_url=logo,
        )
    return builders[row.email_type]()


def dispatch_delivery(session_factory, delivery_id: int) -> bool:
    with session_factory() as db:
        row = db.query(models.SaaSDemoEmailDelivery).filter_by(id=delivery_id).with_for_update().one_or_none()
        if row is None or row.status == "sent":
            return bool(row and row.status == "sent")
        row.status = "processing"
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.last_attempt_at = datetime.now(UTC).replace(tzinfo=None)
        content = _content(db, row)
        db.commit()
        try:
            message_id = email_service.send_email(
                to=row.recipient_email, subject=content.subject, text=content.text,
                html=content.html, idempotency_key=row.deduplication_key,
            )
        except email_service.EmailDeliveryError as exc:
            row = db.get(models.SaaSDemoEmailDelivery, delivery_id)
            row.status = "failed"
            row.failure_code = exc.__class__.__name__[:80]
            db.commit()
            return False
        row = db.get(models.SaaSDemoEmailDelivery, delivery_id)
        row.status = "sent"
        row.sent_at = datetime.now(UTC).replace(tzinfo=None)
        row.provider_message_id = str(message_id or "")[:180] or None
        row.failure_code = None
        db.commit()
        return True


def dispatch_pending(session_factory, *, limit: int = 100, demo_request_id: int | None = None) -> int:
    with session_factory() as db:
        query = db.query(models.SaaSDemoEmailDelivery.id).filter(
            models.SaaSDemoEmailDelivery.status.in_(("pending", "failed", "processing"))
        )
        if demo_request_id:
            query = query.filter(models.SaaSDemoEmailDelivery.demo_request_id == demo_request_id)
        ids = [row[0] for row in query.order_by(models.SaaSDemoEmailDelivery.id).limit(limit).all()]
    return sum(1 for delivery_id in ids if dispatch_delivery(session_factory, delivery_id))
