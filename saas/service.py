import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from fastapi import Request
from sqlalchemy.orm import Session

import auth
import branding_storage
import email_service
import email_templates
import public_url
from saas import models
from saas.branch_pricing_quote_service import normalize_branch_name

SAAS_SESSION_COOKIE = "tis_saas_session"
SAAS_CSRF_COOKIE = "tis_saas_csrf"
SAAS_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
SAAS_EMAIL_VERIFICATION_MAX_AGE_SECONDS = 60 * 60
SAAS_PASSWORD_RESET_MAX_AGE_SECONDS = 60 * 60
LOGIN_RATE_LIMIT_ATTEMPTS = 10
LOGIN_RATE_LIMIT_WINDOW_MINUTES = 15
SIGNUP_RATE_LIMIT_ATTEMPTS = 8
SIGNUP_RATE_LIMIT_WINDOW_MINUTES = 60
VERIFICATION_RATE_LIMIT_ATTEMPTS = 5
VERIFICATION_RATE_LIMIT_WINDOW_MINUTES = 60
PASSWORD_RESET_RATE_LIMIT_ATTEMPTS = 5
PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES = 60
ONBOARDING_STEPS = ("organization", "branches", "academic_setup", "contacts", "review")
ONBOARDING_STEP_LABELS = {
    "organization": "Organization Profile",
    "branches": "Branch Setup",
    "academic_setup": "Academic Setup",
    "contacts": "Primary Contact",
    "review": "Review School Workspace Setup",
}
PENDING_ORGANIZATION_ACTIVE_STATUSES = (
    "draft",
    "in_progress",
    "changes_requested",
    "ready_for_checkout",
    "under_review",
    "activated",
)
BLOCKED_DELETE_BILLING_STATUSES = {
    "ready_for_provisioning",
    "provisioning_started",
    "provisioning_completed",
    "provisioning_retrying",
    "provisioning_failed",
    "tenant_active",
}
SETUP_EDIT_LOCKED_BILLING_STATUSES = {
    "payment_confirmed",
    "ready_for_provisioning",
    "provisioning_started",
    "provisioning_completed",
    "provisioning_retrying",
    "provisioning_failed",
    "tenant_active",
}
SETUP_EDIT_LOCKED_PAYMENT_STATUSES = {"paid"}
READY_FOR_CHECKOUT_STATUS = "ready_for_checkout"
PERSONAL_EMAIL_WARNING = (
    "Personal email domains are not recommended for school onboarding. You can continue now, "
    "but a work email will be requested during organization setup."
)
DISPOSABLE_EMAIL_BLOCK_MESSAGE = (
    "Disposable email domains are not allowed for TIS Account registration."
)


@dataclass(frozen=True)
class DomainPolicyResult:
    domain: str
    allowed: bool
    warning: str = ""
    reason: str = ""
    enforcement: str = ""


@dataclass(frozen=True)
class PendingOrganizationCard:
    organization: object
    owner_account: object
    progress: object
    branches_count: int
    current_step_url: str
    current_plan: object = None
    current_plan_selection: object = None
    current_checkout_session: object = None
    current_subscription_contract: object = None
    current_payment_customer: object = None
    current_payment_attempt: object = None
    current_payment_subscription: object = None
    current_provisioning_job: object = None
    current_tenant_link: object = None


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _get_positive_int_env(name: str, default: int) -> int:
    raw_value = str(os.environ.get(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def session_max_age_seconds() -> int:
    return _get_positive_int_env("TIS_SAAS_SESSION_MAX_AGE_SECONDS", SAAS_SESSION_MAX_AGE_SECONDS)


def _verification_max_age_seconds() -> int:
    return _get_positive_int_env(
        "TIS_SAAS_EMAIL_VERIFICATION_MAX_AGE_SECONDS",
        SAAS_EMAIL_VERIFICATION_MAX_AGE_SECONDS,
    )


def _password_reset_max_age_seconds() -> int:
    return _get_positive_int_env(
        "TIS_SAAS_PASSWORD_RESET_MAX_AGE_SECONDS",
        SAAS_PASSWORD_RESET_MAX_AGE_SECONDS,
    )


def _hash_value(value: str) -> str:
    return auth.hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _extract_domain(email: str | None) -> str:
    normalized = auth.normalize_email(email)
    if not normalized or "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[-1]


def get_domain_policy(db: Session, email: str | None) -> DomainPolicyResult:
    domain = _extract_domain(email)
    if not domain:
        return DomainPolicyResult(domain="", allowed=True)
    row = db.query(models.BlockedEmailDomain).filter(
        models.BlockedEmailDomain.domain == domain,
        models.BlockedEmailDomain.is_active == True,
    ).first()
    if not row:
        return DomainPolicyResult(domain=domain, allowed=True)
    enforcement = str(getattr(row, "enforcement", "") or "").strip().lower()
    if enforcement == "warn":
        return DomainPolicyResult(
            domain=domain,
            allowed=True,
            warning=PERSONAL_EMAIL_WARNING,
            reason=str(getattr(row, "reason", "") or ""),
            enforcement="warn",
        )
    return DomainPolicyResult(
        domain=domain,
        allowed=False,
        reason=str(getattr(row, "reason", "") or DISPOSABLE_EMAIL_BLOCK_MESSAGE),
        enforcement="block",
    )


def log_auth_event(
    db: Session,
    *,
    event_type: str,
    event_status: str = "ok",
    account_id: int | None = None,
    request: Request | None = None,
    details: dict | None = None,
):
    db.add(
        models.SaaSAuthEvent(
            saas_account_id=account_id,
            event_type=str(event_type or "").strip()[:40] or "unknown",
            event_status=str(event_status or "").strip()[:20] or "ok",
            ip_address=str(getattr(getattr(request, "client", None), "host", "") or "")[:80],
            user_agent=str(request.headers.get("user-agent", "") if request else "")[:255],
            details_json=json.dumps(details or {}, separators=(",", ":")) if details else None,
        )
    )


def recent_auth_event_count(
    db: Session,
    *,
    event_type: str,
    request: Request | None = None,
    event_status: str | None = None,
    window_minutes: int = 15,
) -> int:
    window_start = _utcnow() - timedelta(minutes=max(1, int(window_minutes)))
    query = db.query(models.SaaSAuthEvent).filter(
        models.SaaSAuthEvent.event_type == str(event_type or "").strip(),
        models.SaaSAuthEvent.created_at >= window_start,
    )
    if event_status:
        query = query.filter(models.SaaSAuthEvent.event_status == str(event_status or "").strip())
    request_ip = str(getattr(getattr(request, "client", None), "host", "") or "").strip()
    if request_ip:
        query = query.filter(models.SaaSAuthEvent.ip_address == request_ip[:80])
    return int(query.count() or 0)


def is_rate_limited(
    db: Session,
    *,
    event_type: str,
    request: Request | None = None,
    event_status: str | None = None,
    max_attempts: int,
    window_minutes: int,
) -> bool:
    return recent_auth_event_count(
        db,
        event_type=event_type,
        request=request,
        event_status=event_status,
        window_minutes=window_minutes,
    ) >= max(1, int(max_attempts))


def get_account_by_email(db: Session, email: str | None):
    normalized = auth.normalize_email(email)
    if not normalized:
        return None
    return db.query(models.SaaSAccount).filter(
        models.SaaSAccount.email_normalized == normalized
    ).first()


def create_account(
    db: Session,
    *,
    email: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    request: Request | None = None,
):
    cleaned_email = str(email or "").strip()
    normalized = auth.normalize_email(cleaned_email)
    if not auth.is_valid_email(cleaned_email) or not normalized:
        raise ValueError("Enter a valid email address.")
    policy = get_domain_policy(db, cleaned_email)
    if not policy.allowed:
        raise ValueError(policy.reason or DISPOSABLE_EMAIL_BLOCK_MESSAGE)
    if len(str(password or "")) < 12:
        raise ValueError("Password must be at least 12 characters.")
    if get_account_by_email(db, cleaned_email):
        raise ValueError("This email is already registered for a TIS Account.")

    account = models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email=cleaned_email,
        email_normalized=normalized,
        password_hash=auth.get_password_hash(password),
        first_name=str(first_name or "").strip()[:120],
        last_name=str(last_name or "").strip()[:120],
        status="pending_verification",
        onboarding_status="not_started",
    )
    db.add(account)
    db.flush()
    db.add(
        models.SaaSAuthIdentity(
            saas_account_id=account.id,
            provider="password",
            provider_subject=normalized,
            provider_email=cleaned_email,
            provider_email_normalized=normalized,
        )
    )
    log_auth_event(
        db,
        event_type="signup",
        account_id=account.id,
        request=request,
        details={"provider": "password", "warning": policy.warning},
    )
    return account, policy


def create_email_verification_token(db: Session, account, request: Request | None = None) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_value(token)
    db.query(models.SaaSEmailVerificationToken).filter(
        models.SaaSEmailVerificationToken.saas_account_id == account.id,
        models.SaaSEmailVerificationToken.consumed_at.is_(None),
    ).update({models.SaaSEmailVerificationToken.consumed_at: _utcnow()}, synchronize_session=False)
    db.add(
        models.SaaSEmailVerificationToken(
            saas_account_id=account.id,
            token_hash=token_hash,
            email_normalized=account.email_normalized,
            expires_at=_utcnow() + timedelta(seconds=_verification_max_age_seconds()),
            request_ip=str(getattr(getattr(request, "client", None), "host", "") or "")[:80],
            user_agent=str(request.headers.get("user-agent", "") if request else "")[:255],
        )
    )
    return token


def email_public_base_url(request: Request) -> str:
    return public_url.public_base_url(request)


def build_verification_url(request: Request, token: str) -> str:
    return f"{email_public_base_url(request)}/saas/auth/verify-email?token={token}"


def send_verification_email(db: Session, account, request: Request) -> None:
    token = create_email_verification_token(db, account, request=request)
    verification_url = build_verification_url(request, token)
    logo_url = public_url.public_static_asset_url(
        branding_storage.tis_logo_relative_path(theme="light", compact=True),
        request,
    )
    email_content = email_templates.build_email_verification_email(
        verification_url=verification_url,
        logo_url=logo_url,
    )
    email_service.send_email(
        to=str(account.email or "").strip(),
        subject=email_content.subject,
        text=email_content.text,
        html=email_content.html,
    )
    log_auth_event(
        db,
        event_type="verification_sent",
        account_id=account.id,
        request=request,
    )


def create_password_reset_token(db: Session, account, request: Request | None = None) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_value(token)
    db.query(models.SaaSPasswordResetToken).filter(
        models.SaaSPasswordResetToken.saas_account_id == account.id,
        models.SaaSPasswordResetToken.consumed_at.is_(None),
    ).update({models.SaaSPasswordResetToken.consumed_at: _utcnow()}, synchronize_session=False)
    db.add(
        models.SaaSPasswordResetToken(
            saas_account_id=account.id,
            token_hash=token_hash,
            email_normalized=account.email_normalized,
            expires_at=_utcnow() + timedelta(seconds=_password_reset_max_age_seconds()),
            request_ip=str(getattr(getattr(request, "client", None), "host", "") or "")[:80],
            user_agent=str(request.headers.get("user-agent", "") if request else "")[:255],
        )
    )
    return token


def build_password_reset_url(request: Request, token: str) -> str:
    return f"{email_public_base_url(request)}/saas/auth/reset-password?token={token}"


def send_password_reset_email(db: Session, account, request: Request) -> None:
    token = create_password_reset_token(db, account, request=request)
    reset_url = build_password_reset_url(request, token)
    logo_url = public_url.public_static_asset_url(
        branding_storage.tis_logo_relative_path(theme="light", compact=True),
        request,
    )
    email_content = email_templates.build_saas_password_reset_email(
        reset_url=reset_url,
        logo_url=logo_url,
    )
    email_service.send_email(
        to=str(account.email or "").strip(),
        subject=email_content.subject,
        text=email_content.text,
        html=email_content.html,
    )
    log_auth_event(
        db,
        event_type="password_reset_sent",
        account_id=account.id,
        request=request,
    )


def get_account_for_password_reset_token(db: Session, token: str):
    token_hash = _hash_value(token)
    row = db.query(models.SaaSPasswordResetToken).filter(
        models.SaaSPasswordResetToken.token_hash == token_hash
    ).first()
    if not row:
        return None, "This password reset link is invalid or expired."
    if row.consumed_at is not None or row.expires_at < _utcnow():
        return None, "This password reset link is invalid or expired."
    account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == row.saas_account_id
    ).first()
    if not account or account.email_normalized != row.email_normalized:
        return None, "This password reset link no longer matches the account."
    if not getattr(account, "password_hash", None):
        return None, "Password reset is not available for this sign-in method."
    if str(getattr(account, "status", "") or "").strip().lower() in {"locked", "disabled"}:
        return None, "Password reset is not available for this account."
    return account, ""


def reset_password_with_token(db: Session, token: str, password: str):
    if len(str(password or "")) < 12:
        raise ValueError("Password must be at least 12 characters.")
    account, error = get_account_for_password_reset_token(db, token)
    if not account:
        raise ValueError(error)
    token_hash = _hash_value(token)
    row = db.query(models.SaaSPasswordResetToken).filter(
        models.SaaSPasswordResetToken.token_hash == token_hash
    ).first()
    row.consumed_at = _utcnow()
    account.password_hash = auth.get_password_hash(password)
    db.query(models.SaaSSession).filter(
        models.SaaSSession.saas_account_id == account.id,
        models.SaaSSession.revoked_at.is_(None),
    ).update(
        {
            models.SaaSSession.revoked_at: _utcnow(),
            models.SaaSSession.revoke_reason: "password_reset",
        },
        synchronize_session=False,
    )
    log_auth_event(db, event_type="password_reset_completed", account_id=account.id)
    return account


def verify_email_token(db: Session, token: str):
    token_hash = _hash_value(token)
    row = db.query(models.SaaSEmailVerificationToken).filter(
        models.SaaSEmailVerificationToken.token_hash == token_hash
    ).first()
    if not row:
        return None, "This email verification link is invalid or expired."
    if row.consumed_at is not None or row.expires_at < _utcnow():
        return None, "This email verification link is invalid or expired."
    account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == row.saas_account_id
    ).first()
    if not account or account.email_normalized != row.email_normalized:
        return None, "This email verification link no longer matches the account."
    row.consumed_at = _utcnow()
    if not account.email_verified_at:
        account.email_verified_at = _utcnow()
    if account.status == "pending_verification":
        account.status = "active"
    return account, ""


def authenticate_account(db: Session, email: str, password: str):
    account = get_account_by_email(db, email)
    if not account or not getattr(account, "password_hash", None):
        return None
    if not auth.verify_password(password, account.password_hash):
        return None
    if str(getattr(account, "status", "") or "").strip().lower() in {"locked", "disabled"}:
        return None
    return account


def create_session(db: Session, account, request: Request | None = None) -> tuple[str, str, models.SaaSSession]:
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    session_row = models.SaaSSession(
        saas_account_id=account.id,
        session_token_hash=_hash_value(session_token),
        session_family_id=secrets.token_hex(16),
        csrf_token_hash=_hash_value(csrf_token),
        ip_address=str(getattr(getattr(request, "client", None), "host", "") or "")[:80],
        user_agent=str(request.headers.get("user-agent", "") if request else "")[:255],
        issued_at=_utcnow(),
        last_seen_at=_utcnow(),
        expires_at=_utcnow() + timedelta(seconds=session_max_age_seconds()),
    )
    account.last_login_at = _utcnow()
    db.add(session_row)
    return session_token, csrf_token, session_row


def _active_session_query(db: Session):
    now = _utcnow()
    return db.query(models.SaaSSession).filter(
        models.SaaSSession.revoked_at.is_(None),
        models.SaaSSession.expires_at > now,
    )


def get_session_from_request(db: Session, request: Request):
    session_token = str(request.cookies.get(SAAS_SESSION_COOKIE) or "").strip()
    if not session_token:
        return None
    session_row = _active_session_query(db).filter(
        models.SaaSSession.session_token_hash == _hash_value(session_token)
    ).first()
    if not session_row:
        return None
    session_row.last_seen_at = _utcnow()
    return session_row


def get_current_account(db: Session, request: Request):
    session_row = get_session_from_request(db, request)
    if not session_row:
        return None
    account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == session_row.saas_account_id
    ).first()
    if not account:
        return None
    return account


def revoke_session(db: Session, session_row, reason: str = "logout"):
    if session_row and session_row.revoked_at is None:
        session_row.revoked_at = _utcnow()
        session_row.revoke_reason = str(reason or "logout")[:80]


def revoke_other_sessions(db: Session, account, current_session_id: int):
    db.query(models.SaaSSession).filter(
        models.SaaSSession.saas_account_id == account.id,
        models.SaaSSession.id != int(current_session_id),
        models.SaaSSession.revoked_at.is_(None),
    ).update(
        {
            models.SaaSSession.revoked_at: _utcnow(),
            models.SaaSSession.revoke_reason: "revoke_others",
        },
        synchronize_session=False,
    )


def set_session_cookies(response, *, session_token: str, csrf_token: str, request: Request):
    response.set_cookie(
        key=SAAS_SESSION_COOKIE,
        value=session_token,
        **auth.secure_cookie_kwargs(request, max_age=session_max_age_seconds()),
    )
    response.set_cookie(
        key=SAAS_CSRF_COOKIE,
        value=csrf_token,
        secure=auth.should_use_secure_cookies(request),
        samesite="lax",
        httponly=False,
        max_age=session_max_age_seconds(),
    )
    return response


def clear_session_cookies(response, request: Request):
    cookie_kwargs = auth.secure_cookie_kwargs(request)
    response.delete_cookie(SAAS_SESSION_COOKIE, **cookie_kwargs)
    response.delete_cookie(SAAS_CSRF_COOKIE, secure=auth.should_use_secure_cookies(request), samesite="lax")
    return response


def validate_csrf(request: Request, session_row) -> bool:
    submitted = str(request.headers.get("x-csrf-token") or "").strip()
    if not submitted:
        return False
    return _hash_value(submitted) == str(getattr(session_row, "csrf_token_hash", "") or "")


hash_value = _hash_value


def _workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def pending_logo_dir() -> Path:
    target = _workspace_root() / "static" / "uploads" / "saas" / "pending_logos"
    target.mkdir(parents=True, exist_ok=True)
    return target


def pending_logo_public_path(filename: str) -> str:
    return f"uploads/saas/pending_logos/{filename}"


def _delete_pending_logo_file(logo_path: str | None) -> None:
    relative = str(logo_path or "").strip()
    if not relative:
        return
    static_root = (_workspace_root() / "static").resolve()
    target_path = (static_root / Path(*relative.split("/"))).resolve()
    try:
        target_path.relative_to(static_root)
    except ValueError:
        return
    if target_path.is_file():
        target_path.unlink(missing_ok=True)


def save_pending_logo(upload_file) -> str:
    filename = str(getattr(upload_file, "filename", "") or "").strip()
    if not filename:
        return ""
    content_type = str(getattr(upload_file, "content_type", "") or "").strip().lower()
    allowed_content_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if content_type not in allowed_content_types:
        raise ValueError("Organization logo must be a PNG, JPG, or WEBP image.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Organization logo file extension is not supported.")
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target_path = pending_logo_dir() / stored_name
    with target_path.open("wb") as output:
        output.write(upload_file.file.read())
    return pending_logo_public_path(stored_name)


def get_pending_organization_for_account(db: Session, account):
    return db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account.id,
        models.PendingOrganization.status.in_(PENDING_ORGANIZATION_ACTIVE_STATUSES),
    ).order_by(models.PendingOrganization.updated_at.desc(), models.PendingOrganization.id.desc()).first()


def get_pending_organization_by_uuid(db: Session, organization_uuid: str):
    return db.query(models.PendingOrganization).filter(
        models.PendingOrganization.organization_uuid == str(organization_uuid or "").strip()
    ).first()


def get_owned_pending_organization(db: Session, account, organization_uuid: str):
    organization = get_pending_organization_by_uuid(db, organization_uuid)
    if not organization or organization.owner_saas_account_id != account.id:
        return None
    return organization


def get_or_create_pending_progress(db: Session, organization):
    row = db.query(models.PendingOrganizationProgress).filter(
        models.PendingOrganizationProgress.pending_organization_id == organization.id
    ).first()
    if row:
        return row
    row = models.PendingOrganizationProgress(pending_organization_id=organization.id)
    db.add(row)
    db.flush()
    return row


def get_or_create_academic_setup(db: Session, organization):
    row = db.query(models.PendingOrganizationAcademicSetup).filter(
        models.PendingOrganizationAcademicSetup.pending_organization_id == organization.id
    ).first()
    if row:
        return row
    row = models.PendingOrganizationAcademicSetup(pending_organization_id=organization.id)
    db.add(row)
    db.flush()
    return row


def get_primary_contact(db: Session, organization):
    return db.query(models.PendingOrganizationContact).filter(
        models.PendingOrganizationContact.pending_organization_id == organization.id,
        models.PendingOrganizationContact.is_primary == True,
    ).order_by(models.PendingOrganizationContact.id.asc()).first()


def create_pending_organization(db: Session, account, request: Request | None = None):
    existing = get_pending_organization_for_account(db, account)
    if existing:
        return existing
    organization = models.PendingOrganization(
        organization_uuid=str(uuid.uuid4()),
        owner_saas_account_id=account.id,
        status="draft",
        onboarding_step="organization",
        draft_saved_at=_utcnow(),
    )
    db.add(organization)
    db.flush()
    get_or_create_pending_progress(db, organization)
    log_pending_event(
        db,
        organization=organization,
        account=account,
        event_type="created",
        details={"status": "draft"},
    )
    account.onboarding_status = "organization_in_progress"
    return organization


def log_pending_event(db: Session, *, organization, account=None, event_type: str, details: dict | None = None):
    db.add(
        models.PendingOrganizationEvent(
            pending_organization_id=organization.id,
            actor_saas_account_id=getattr(account, "id", None),
            event_type=str(event_type or "").strip()[:40] or "unknown",
            details_json=json.dumps(details or {}, separators=(",", ":")) if details else None,
        )
    )


def _safe_int(value, default: int | None = None) -> int | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _clean_text(value, max_length: int = 180) -> str:
    return str(value or "").strip()[:max_length]


def _clean_timezone(value: str) -> str:
    cleaned = _clean_text(value, 80)
    if not cleaned:
        return ""
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Select a valid time zone.") from exc
    return cleaned


def organization_step_url(organization) -> str:
    status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    if billing_status in {
        "checkout_started",
        "payment_processing",
        "payment_confirmed",
        "ready_for_provisioning",
        "provisioning_started",
        "provisioning_completed",
        "provisioning_retrying",
        "provisioning_failed",
        "tenant_active",
        "payment_failed",
        "payment_cancelled",
        "payment_refunded",
    }:
        return f"/saas/onboarding/{organization.organization_uuid}/billing-status"
    if status == READY_FOR_CHECKOUT_STATUS:
        return f"/saas/onboarding/{organization.organization_uuid}/plan"
    step = str(getattr(organization, "onboarding_step", "") or "organization").strip() or "organization"
    return f"/saas/onboarding/{organization.organization_uuid}/{step}"


@lru_cache(maxsize=1)
def list_iana_timezones() -> tuple[str, ...]:
    return tuple(sorted(available_timezones()))


def is_setup_editing_locked(organization) -> bool:
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    payment_status = str(getattr(organization, "payment_status", "") or "").strip().lower()
    return billing_status in SETUP_EDIT_LOCKED_BILLING_STATUSES or payment_status in SETUP_EDIT_LOCKED_PAYMENT_STATUSES


def build_onboarding_step_access(db: Session, organization, *, current_step: str = "") -> dict:
    progress = recalculate_pending_progress(db, organization)
    org_uuid = str(getattr(organization, "organization_uuid", "") or "")
    saved_step = str(getattr(organization, "onboarding_step", "") or "organization").strip()
    if saved_step not in ONBOARDING_STEPS:
        saved_step = "organization"

    reached_index = ONBOARDING_STEPS.index(saved_step)
    if progress.organization_profile_complete:
        reached_index = max(reached_index, ONBOARDING_STEPS.index("branches"))
    if progress.branches_complete:
        reached_index = max(reached_index, ONBOARDING_STEPS.index("academic_setup"))
    if progress.academic_setup_complete:
        reached_index = max(reached_index, ONBOARDING_STEPS.index("contacts"))
    if progress.contacts_complete:
        reached_index = max(reached_index, ONBOARDING_STEPS.index("review"))

    status = str(getattr(organization, "status", "") or "").strip().lower()
    if status in {READY_FOR_CHECKOUT_STATUS, "under_review", "changes_requested", "rejected", "activated"}:
        reached_index = max(reached_index, ONBOARDING_STEPS.index("review"))

    completed = {
        "organization": bool(progress.organization_profile_complete),
        "branches": bool(progress.branches_complete),
        "academic_setup": bool(progress.academic_setup_complete),
        "contacts": bool(progress.contacts_complete),
        "review": bool(getattr(progress, "review_complete", False) or status == READY_FOR_CHECKOUT_STATUS),
    }
    editing_locked = is_setup_editing_locked(organization)
    requested_current = current_step if current_step in ONBOARDING_STEPS else saved_step
    steps = []
    for index, key in enumerate(ONBOARDING_STEPS):
        allowed = index <= reached_index and not editing_locked
        state = "locked"
        if allowed:
            state = "complete" if completed.get(key) else "available"
        if key == requested_current and allowed:
            state = "current"
        steps.append(
            {
                "key": key,
                "label": ONBOARDING_STEP_LABELS[key],
                "state": state,
                "allowed": allowed,
                "url": f"/saas/onboarding/{org_uuid}/{key}",
            }
        )

    return {
        "steps": steps,
        "steps_by_key": {step["key"]: step for step in steps},
        "reached_step": ONBOARDING_STEPS[reached_index],
        "resume_url": organization_step_url(organization),
        "editing_locked": editing_locked,
    }


def build_setup_edit_navigation_steps(db: Session, organization, *, current_key: str = "") -> list[dict]:
    access = build_onboarding_step_access(db, organization, current_step=current_key)
    if access["editing_locked"]:
        return []
    status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    steps = []
    for step in access["steps"]:
        steps.append(
            {
                "key": step["key"],
                "label": step["label"],
                "url": step["url"],
                "state": "current" if step["key"] == current_key and step["allowed"] else step["state"],
                "allowed": step["allowed"],
            }
        )
    if status == READY_FOR_CHECKOUT_STATUS:
        steps.append(
            {
                "key": "subscription_selection",
                "label": "Subscription Selection",
                "url": f"/saas/onboarding/{organization.organization_uuid}/plan",
                "state": "current" if current_key == "subscription_selection" else ("complete" if billing_status in {"plan_selected", "checkout_ready", "checkout_initiated", "checkout_started", "payment_processing"} else "available"),
                "allowed": True,
            }
        )
    return steps


def recalculate_pending_progress(db: Session, organization):
    progress = get_or_create_pending_progress(db, organization)
    progress.organization_profile_complete = bool(
        _clean_text(getattr(organization, "organization_name", ""), 160)
        and _clean_text(getattr(organization, "educational_program", ""), 20)
        and _clean_text(getattr(organization, "timezone", ""), 80)
    )
    branches_count = count_billable_pending_branches(db, organization)
    progress.branches_complete = branches_count > 0
    academic_setup = get_or_create_academic_setup(db, organization)
    progress.academic_setup_complete = bool(_clean_text(academic_setup.first_academic_year_name, 40))
    primary_contact = get_primary_contact(db, organization)
    progress.contacts_complete = bool(
        primary_contact
        and _clean_text(primary_contact.first_name, 120)
        and _clean_text(primary_contact.last_name, 120)
        and auth.is_valid_email(primary_contact.email)
    )
    completion_flags = [
        progress.organization_profile_complete,
        progress.branches_complete,
        progress.academic_setup_complete,
        progress.contacts_complete,
    ]
    progress.completion_percent = int(round((sum(1 for flag in completion_flags if flag) / len(completion_flags)) * 100))
    last_completed_step = ""
    if progress.organization_profile_complete:
        last_completed_step = "organization"
    if progress.branches_complete:
        last_completed_step = "branches"
    if progress.academic_setup_complete:
        last_completed_step = "academic_setup"
    if progress.contacts_complete:
        last_completed_step = "contacts"
    progress.last_completed_step = last_completed_step or None
    return progress


def get_onboarding_missing_requirements(db: Session, organization) -> list[dict]:
    missing = []
    if not _clean_text(getattr(organization, "organization_name", ""), 160):
        missing.append({"step": "Organization Profile", "field": "Organization name"})
    if not _clean_text(getattr(organization, "educational_program", ""), 20):
        missing.append({"step": "Organization Profile", "field": "Educational program"})
    if not _clean_text(getattr(organization, "timezone", ""), 80):
        missing.append({"step": "Organization Profile", "field": "Time Zone"})

    branches_count = count_billable_pending_branches(db, organization)
    if branches_count <= 0:
        missing.append({"step": "Branch Setup", "field": "At least one branch"})

    academic_setup = get_or_create_academic_setup(db, organization)
    if not _clean_text(academic_setup.first_academic_year_name, 40):
        missing.append({"step": "Academic Setup", "field": "First academic year"})

    primary_contact = get_primary_contact(db, organization)
    if not primary_contact:
        missing.append({"step": "Primary Contact", "field": "Primary contact"})
    else:
        if not _clean_text(primary_contact.first_name, 120):
            missing.append({"step": "Primary Contact", "field": "First name"})
        if not _clean_text(primary_contact.last_name, 120):
            missing.append({"step": "Primary Contact", "field": "Last name"})
        if not auth.is_valid_email(primary_contact.email):
            missing.append({"step": "Primary Contact", "field": "Valid email"})
    return missing


def format_onboarding_missing_requirements(missing: list[dict]) -> str:
    if not missing:
        return ""
    grouped = {}
    for item in missing:
        step = str(item.get("step") or "Setup").strip()
        field = str(item.get("field") or "Required information").strip()
        grouped.setdefault(step, []).append(field)
    details = "; ".join(f"{step}: {', '.join(fields)}" for step, fields in grouped.items())
    return f"Complete these items before submitting: {details}."


def update_pending_dashboard_status(account, organization, progress):
    if not organization:
        account.onboarding_status = "not_started"
        return
    status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    if billing_status in {
        "plan_selected",
        "checkout_ready",
        "checkout_initiated",
        "checkout_started",
        "payment_processing",
        "payment_confirmed",
        "ready_for_provisioning",
        "provisioning_started",
        "provisioning_completed",
        "provisioning_retrying",
        "provisioning_failed",
        "tenant_active",
        "payment_failed",
        "payment_cancelled",
        "payment_refunded",
    }:
        account.onboarding_status = billing_status
    elif status == READY_FOR_CHECKOUT_STATUS:
        account.onboarding_status = READY_FOR_CHECKOUT_STATUS
    elif status in {"under_review", "changes_requested", "rejected"}:
        account.onboarding_status = status
    elif int(getattr(progress, "completion_percent", 0) or 0) > 0:
        account.onboarding_status = "organization_in_progress"
    else:
        account.onboarding_status = "not_started"


def save_organization_profile(
    db: Session,
    organization,
    *,
    organization_name: str,
    legal_name: str,
    website: str,
    primary_domain: str,
    phone: str,
    educational_program: str,
    country_code: str,
    country_name: str,
    region_name: str,
    city_name: str,
    district_name: str,
    neighborhood_name: str,
    school_type: str,
    expected_branch_count,
    expected_student_count,
    expected_teacher_count,
    estimated_staff_users,
    timezone: str,
    logo_file=None,
):
    cleaned_program = _clean_text(educational_program, 20).upper()
    if cleaned_program not in {"NATIONAL", "INTERNATIONAL", "BOTH"}:
        raise ValueError("Educational Program must be National, International, or Both.")
    organization.organization_name = _clean_text(organization_name, 160)
    if not organization.organization_name:
        raise ValueError("Organization name is required.")
    organization.legal_name = _clean_text(legal_name, 180)
    organization.website = _clean_text(website, 180)
    organization.primary_domain = _extract_domain(primary_domain) or _clean_text(primary_domain, 180)
    organization.phone = _clean_text(phone, 80)
    organization.educational_program = cleaned_program
    organization.country_code = _clean_text(country_code, 2).upper()
    organization.country_name = _clean_text(country_name, 120)
    organization.region_name = _clean_text(region_name, 160)
    organization.city_name = _clean_text(city_name, 160)
    organization.district_name = _clean_text(district_name, 160)
    organization.neighborhood_name = _clean_text(neighborhood_name, 160)
    organization.school_type = _clean_text(school_type, 120)
    existing_branch_rows = db.query(models.PendingOrganizationBranch).filter(
        models.PendingOrganizationBranch.pending_organization_id == organization.id
    ).all()
    if existing_branch_rows:
        organization.expected_branch_count = sum(1 for row in existing_branch_rows if bool(row.status))
    else:
        organization.expected_branch_count = _safe_int(expected_branch_count)
    organization.expected_student_count = _safe_int(expected_student_count)
    organization.expected_teacher_count = _safe_int(expected_teacher_count)
    organization.estimated_staff_users = _safe_int(estimated_staff_users)
    organization.timezone = _clean_timezone(timezone)
    if logo_file is not None and str(getattr(logo_file, "filename", "") or "").strip():
        organization.organization_logo_path = save_pending_logo(logo_file)
    organization.onboarding_step = "branches"
    organization.status = "in_progress"
    organization.draft_saved_at = _utcnow()


def replace_branches(db: Session, organization, branch_rows: list[dict]):
    if str(getattr(organization, "payment_status", "") or "").strip().lower() == "paid":
        raise ValueError("Branches cannot be changed after payment is confirmed.")
    if db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).first():
        raise ValueError("Provisioned branches cannot be changed from onboarding.")
    existing_rows = db.query(models.PendingOrganizationBranch).filter(
        models.PendingOrganizationBranch.pending_organization_id == organization.id
    ).order_by(
        models.PendingOrganizationBranch.sort_order.asc(),
        models.PendingOrganizationBranch.id.asc(),
    ).all()
    existing_by_uuid = {
        str(row.branch_uuid or "").strip(): row
        for row in existing_rows
        if str(row.branch_uuid or "").strip()
    }
    has_submitted_branch_identity = any(
        _clean_text(row.get("branch_uuid"), 36) for row in branch_rows
    )
    cleaned_rows: list[tuple[int, dict, str]] = []
    for index, row in enumerate(branch_rows):
        branch_name = _clean_text(row.get("branch_name"), 160)
        if not branch_name:
            if any(_clean_text(value) for value in row.values()):
                raise ValueError("Every active branch must have a branch name.")
            continue
        cleaned_rows.append((index, row, branch_name))
    if not cleaned_rows:
        raise ValueError("Add at least one branch.")

    normalized_names = [normalize_branch_name(branch_name) for _index, _row, branch_name in cleaned_rows]
    if len(normalized_names) != len(set(normalized_names)):
        raise ValueError("Active branch names must be unique within the organization.")

    claimed_ids: set[int] = set()
    changed = False
    active_by_order = {int(row.sort_order or 0): row for row in existing_rows if bool(row.status)}
    editable_fields = (
        ("branch_name", 160), ("location", 180), ("country_name", 120),
        ("region_name", 160), ("city_name", 160), ("district_name", 160),
        ("neighborhood_name", 160),
    )
    for index, submitted, branch_name in cleaned_rows:
        submitted_uuid = _clean_text(submitted.get("branch_uuid"), 36)
        target = existing_by_uuid.get(submitted_uuid) if submitted_uuid else None
        if submitted_uuid and target is None:
            raise ValueError("Branch identity could not be validated. Refresh Branch Setup and try again.")
        if target is not None and not bool(target.status):
            raise ValueError("A removed branch cannot be restored. Add it as a new branch instead.")
        if target is None and not has_submitted_branch_identity:
            fallback = active_by_order.get(index)
            if fallback is not None and int(fallback.id) not in claimed_ids:
                target = fallback
        if target is None:
            target = models.PendingOrganizationBranch(
                branch_uuid=str(uuid.uuid4()),
                pending_organization_id=organization.id,
            )
            db.add(target)
            changed = True
        elif int(target.id) in claimed_ids:
            raise ValueError("A branch identity cannot be submitted more than once.")

        values = {field: _clean_text(submitted.get(field), max_length) for field, max_length in editable_fields}
        values["branch_name"] = branch_name
        values["country_code"] = _clean_text(submitted.get("country_code"), 2).upper()
        values["sort_order"] = index
        values["status"] = True
        for field, value in values.items():
            if getattr(target, field, None) != value:
                setattr(target, field, value)
                changed = True
        db.flush()
        claimed_ids.add(int(target.id))

    for existing in existing_rows:
        if int(existing.id) not in claimed_ids and bool(existing.status):
            existing.status = False
            changed = True

    organization.expected_branch_count = len(cleaned_rows)

    if changed:
        now = _utcnow()
        for checkout_session in db.query(models.CheckoutSession).filter(
            models.CheckoutSession.pending_organization_id == organization.id,
            models.CheckoutSession.status.in_(("ready", "started")),
        ).all():
            checkout_session.status = "stale"
            checkout_session.abandoned_at = now
        if getattr(organization, "selected_plan_id", None) and str(getattr(organization, "payment_status", "") or "").lower() != "paid":
            organization.billing_status = "plan_selected"
    organization.onboarding_step = "academic_setup"
    organization.status = "in_progress"
    organization.draft_saved_at = _utcnow()


def save_academic_setup(db: Session, organization, *, first_academic_year_name: str, create_default_branch: str, notes: str):
    row = get_or_create_academic_setup(db, organization)
    row.first_academic_year_name = _clean_text(first_academic_year_name, 40)
    if not row.first_academic_year_name:
        raise ValueError("First academic year is required.")
    row.create_default_branch = str(create_default_branch or "").strip().lower() in {"1", "true", "yes", "on"}
    row.notes = str(notes or "").strip()[:4000]
    organization.onboarding_step = "contacts"
    organization.status = "in_progress"
    organization.draft_saved_at = _utcnow()
    return row


def save_primary_contact(
    db: Session,
    organization,
    *,
    first_name: str,
    last_name: str,
    job_title: str,
    email: str,
    phone: str,
):
    cleaned_email = _clean_text(email, 180)
    if not auth.is_valid_email(cleaned_email):
        raise ValueError("Primary contact email is invalid.")
    row = get_primary_contact(db, organization)
    if not row:
        row = models.PendingOrganizationContact(
            pending_organization_id=organization.id,
            contact_type="owner",
            is_primary=True,
        )
        db.add(row)
    row.first_name = _clean_text(first_name, 120)
    row.last_name = _clean_text(last_name, 120)
    row.job_title = _clean_text(job_title, 120)
    row.email = cleaned_email
    row.email_normalized = auth.normalize_email(cleaned_email)
    row.phone = _clean_text(phone, 80)
    if not row.first_name or not row.last_name:
        raise ValueError("Primary contact first and last name are required.")
    organization.onboarding_step = "review"
    organization.status = "in_progress"
    organization.draft_saved_at = _utcnow()
    return row


def save_draft(db: Session, account, organization, *, current_step: str):
    organization.onboarding_step = current_step if current_step in ONBOARDING_STEPS else "organization"
    organization.status = "in_progress"
    organization.draft_saved_at = _utcnow()
    progress = recalculate_pending_progress(db, organization)
    update_pending_dashboard_status(account, organization, progress)
    log_pending_event(
        db,
        organization=organization,
        account=account,
        event_type="draft_saved",
        details={"step": organization.onboarding_step, "completion_percent": progress.completion_percent},
    )
    return progress


def submit_pending_organization(db: Session, account, organization):
    progress = recalculate_pending_progress(db, organization)
    missing = get_onboarding_missing_requirements(db, organization)
    if missing:
        raise ValueError(format_onboarding_missing_requirements(missing))
    progress.review_complete = True
    organization.status = READY_FOR_CHECKOUT_STATUS
    organization.onboarding_step = "review"
    organization.submitted_at = _utcnow()
    organization.draft_saved_at = _utcnow()
    update_pending_dashboard_status(account, organization, progress)
    log_pending_event(
        db,
        organization=organization,
        account=account,
        event_type="submitted",
        details={"status": READY_FOR_CHECKOUT_STATUS},
    )
    return progress


def list_pending_branches(db: Session, organization, *, include_inactive: bool = False):
    query = db.query(models.PendingOrganizationBranch).filter(
        models.PendingOrganizationBranch.pending_organization_id == organization.id
    )
    if not include_inactive:
        query = query.filter(models.PendingOrganizationBranch.status == True)
    return query.order_by(
        models.PendingOrganizationBranch.sort_order.asc(),
        models.PendingOrganizationBranch.id.asc(),
    ).all()


def list_billable_pending_branches(db: Session, organization):
    return [
        branch for branch in list_pending_branches(db, organization)
        if _clean_text(getattr(branch, "branch_name", ""), 160)
    ]


def count_billable_pending_branches(db: Session, organization) -> int:
    return len(list_billable_pending_branches(db, organization))


def list_pending_events(db: Session, organization):
    return db.query(models.PendingOrganizationEvent).filter(
        models.PendingOrganizationEvent.pending_organization_id == organization.id
    ).order_by(models.PendingOrganizationEvent.created_at.desc(), models.PendingOrganizationEvent.id.desc()).all()


def build_pending_card(db: Session, organization):
    if not organization:
        return None
    from saas import billing_service, payment_service, provisioning_service

    owner_account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == organization.owner_saas_account_id
    ).first()
    progress = recalculate_pending_progress(db, organization)
    branches_count = count_billable_pending_branches(db, organization)
    selection = billing_service.get_current_plan_selection(db, organization)
    checkout_session = billing_service.get_current_checkout_session(db, organization)
    contract = billing_service.get_current_subscription_contract(db, organization)
    current_plan = None
    if selection:
        current_plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == selection.plan_id
        ).first()
    payment_customer = payment_service.get_payment_customer(db, organization)
    payment_attempt = payment_service.get_current_payment_attempt(db, organization)
    payment_subscription = payment_service.get_payment_subscription(db, organization)
    provisioning_job = provisioning_service.get_latest_provisioning_job(db, organization)
    tenant_link = provisioning_service.get_tenant_provisioning_link(db, organization)
    return PendingOrganizationCard(
        organization=organization,
        owner_account=owner_account,
        progress=progress,
        branches_count=int(branches_count or 0),
        current_step_url=organization_step_url(organization),
        current_plan=current_plan,
        current_plan_selection=selection,
        current_checkout_session=checkout_session,
        current_subscription_contract=contract,
        current_payment_customer=payment_customer,
        current_payment_attempt=payment_attempt,
        current_payment_subscription=payment_subscription,
        current_provisioning_job=provisioning_job,
        current_tenant_link=tenant_link,
    )


def build_pending_dashboard_summary(db: Session, account):
    organization = get_pending_organization_for_account(db, account)
    if not organization:
        update_pending_dashboard_status(account, None, None)
        return None
    from saas import billing_service, payment_service, provisioning_service

    progress = recalculate_pending_progress(db, organization)
    update_pending_dashboard_status(account, organization, progress)
    branches_count = count_billable_pending_branches(db, organization)
    selection = billing_service.get_current_plan_selection(db, organization)
    checkout_session = billing_service.get_current_checkout_session(db, organization)
    contract = billing_service.get_current_subscription_contract(db, organization)
    current_plan = None
    if selection:
        current_plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == selection.plan_id
        ).first()
    payment_customer = payment_service.get_payment_customer(db, organization)
    payment_attempt = payment_service.get_current_payment_attempt(db, organization)
    payment_subscription = payment_service.get_payment_subscription(db, organization)
    provisioning_job = provisioning_service.get_latest_provisioning_job(db, organization)
    tenant_link = provisioning_service.get_tenant_provisioning_link(db, organization)
    return {
        "organization": organization,
        "progress": progress,
        "branches_count": int(branches_count or 0),
        "current_step_url": organization_step_url(organization),
        "current_plan": current_plan,
        "current_plan_selection": selection,
        "current_checkout_session": checkout_session,
        "current_subscription_contract": contract,
        "current_payment_customer": payment_customer,
        "current_payment_attempt": payment_attempt,
        "current_payment_subscription": payment_subscription,
        "current_provisioning_job": provisioning_job,
        "current_tenant_link": tenant_link,
    }


def _setup_step(key: str, label: str, state: str, *, url: str = "", summary: str = "") -> dict:
    return {
        "key": key,
        "label": label,
        "state": state,
        "url": url,
        "summary": summary,
    }


def build_setup_console_context(db: Session, account) -> dict:
    summary = build_pending_dashboard_summary(db, account)
    organization = summary["organization"] if summary else None
    progress = summary["progress"] if summary else None
    organization_status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    payment_status = str(getattr(organization, "payment_status", "") or "").strip().lower()
    progress_percent = int(getattr(progress, "completion_percent", 0) or 0)
    has_plan = bool(summary and summary.get("current_plan_selection"))
    has_tenant_link = bool(summary and summary.get("current_tenant_link"))
    workspace_name = str(getattr(organization, "organization_name", "") or "").strip() or "School Workspace"
    account_verified = bool(getattr(account, "email_verified_at", None))

    payment_attention = billing_status in {"payment_failed", "payment_cancelled", "payment_refunded"} or payment_status in {
        "failed",
        "cancelled",
        "refunded",
    }
    payment_complete = billing_status in {
        "payment_confirmed",
        "ready_for_provisioning",
        "provisioning_started",
        "provisioning_completed",
        "provisioning_retrying",
        "provisioning_failed",
        "tenant_active",
    }
    payment_started = billing_status in {"checkout_ready", "checkout_initiated", "checkout_started", "payment_processing"}
    activation_started = billing_status in {
        "ready_for_provisioning",
        "provisioning_started",
        "provisioning_retrying",
        "provisioning_failed",
        "provisioning_completed",
        "tenant_active",
    }
    activation_complete = billing_status in {"provisioning_completed", "tenant_active"} or has_tenant_link

    school_setup_complete = progress_percent >= 100
    review_complete = organization_status == READY_FOR_CHECKOUT_STATUS or has_plan or payment_started or payment_complete or activation_started

    if not organization:
        current_key = "school_workspace_setup"
        title = "Start your School Workspace Setup"
        subtitle = "Your TIS Account is ready. Set up your school workspace to continue."
        status_banner = "Next step: start School Workspace Setup."
        primary_action = {
            "label": "Start School Workspace Setup",
            "url": "/saas/onboarding/start",
            "method": "post",
        }
        help_text = "This guided setup collects your organization profile, branches, academic setup, and primary contact."
    elif not school_setup_complete:
        current_key = "school_workspace_setup"
        title = "Continue your School Workspace Setup"
        subtitle = f"{workspace_name} is saved as a draft."
        status_banner = f"School Workspace Setup is {progress_percent}% complete."
        primary_action = {
            "label": "Continue School Workspace Setup",
            "url": summary["current_step_url"],
            "method": "get",
        }
        help_text = "Complete the workspace setup sections, then review and confirm the information before choosing a subscription."
    elif not review_complete:
        current_key = "review_confirmation"
        title = "Review and confirm your setup"
        subtitle = f"{workspace_name} is ready for review."
        status_banner = "Next step: review and submit your School Workspace Setup."
        primary_action = {
            "label": "Review School Workspace Setup",
            "url": summary["current_step_url"],
            "method": "get",
        }
        help_text = "After confirmation, you can choose a subscription and continue to Secure Payment."
    elif not has_plan:
        current_key = "subscription_selection"
        title = "Choose your subscription"
        subtitle = f"{workspace_name} is ready for Subscription Selection."
        status_banner = "Next step: select the subscription that fits your school."
        primary_action = {
            "label": "Choose Subscription",
            "url": f"/saas/onboarding/{organization.organization_uuid}/plan",
            "method": "get",
        }
        help_text = "Subscription Selection opens after your School Workspace Setup is submitted."
    elif payment_attention:
        current_key = "secure_payment"
        title = "Secure Payment needs attention"
        subtitle = f"{workspace_name} has a saved subscription selection."
        status_banner = "Your payment was not completed. You can return to Secure Payment when ready."
        primary_action = {
            "label": "Continue to Secure Payment",
            "url": f"/saas/onboarding/{organization.organization_uuid}/checkout",
            "method": "get",
        }
        help_text = "Your setup remains saved. Workspace Activation begins only after payment is confirmed."
    elif not payment_complete:
        current_key = "secure_payment"
        title = "Continue to Secure Payment"
        subtitle = f"{workspace_name} has a saved subscription selection."
        status_banner = "Next step: complete Secure Payment."
        primary_action = {
            "label": "Continue to Secure Payment",
            "url": f"/saas/onboarding/{organization.organization_uuid}/checkout",
            "method": "get",
        }
        help_text = "Payment confirmation is processed securely before Workspace Activation begins."
    elif not activation_complete:
        current_key = "workspace_activation"
        title = "Workspace Activation is in progress"
        subtitle = f"{workspace_name} is waiting for activation to complete."
        status_banner = "Payment is confirmed. Workspace Activation is the next step."
        primary_action = {
            "label": "View Subscription Status",
            "url": "/saas/account/billing",
            "method": "get",
        }
        help_text = "The TIS team completes Workspace Activation after secure payment confirmation."
    else:
        current_key = "enter_tis_platform"
        title = "Your workspace is active"
        subtitle = f"{workspace_name} is ready."
        status_banner = "Workspace Activation is complete."
        primary_action = {
            "label": "View Account Status",
            "url": "/saas/account/billing",
            "method": "get",
        }
        help_text = "TIS Platform access is available after Workspace Activation. Use your TIS Account credentials when access is provided."

    order = [
        ("tis_account", "TIS Account"),
        ("email_verification", "Email Verification"),
        ("school_workspace_setup", "School Workspace Setup"),
        ("review_confirmation", "Review & Confirmation"),
        ("subscription_selection", "Subscription Selection"),
        ("secure_payment", "Secure Payment"),
        ("workspace_activation", "Workspace Activation"),
        ("enter_tis_platform", "Enter TIS Platform"),
    ]
    completed = {
        "tis_account": True,
        "email_verification": account_verified,
        "school_workspace_setup": bool(organization and school_setup_complete),
        "review_confirmation": bool(organization and review_complete),
        "subscription_selection": has_plan,
        "secure_payment": payment_complete,
        "workspace_activation": activation_complete,
        "enter_tis_platform": activation_complete,
    }
    current_index = next((idx for idx, (key, _label) in enumerate(order) if key == current_key), 0)
    steps = []
    for idx, (key, label) in enumerate(order):
        state = "complete" if completed.get(key) else "locked"
        if key == current_key and not completed.get(key):
            state = "attention" if key == "secure_payment" and payment_attention else "current"
        elif idx < current_index and not completed.get(key):
            state = "pending"
        steps.append(_setup_step(key, label, state))

    return {
        "title": title,
        "subtitle": subtitle,
        "status_banner": status_banner,
        "steps": steps,
        "current_step": current_key,
        "primary_action": primary_action,
        "help_title": "What happens next?",
        "help_text": help_text,
        "portal_access_message": "TIS Platform access becomes available after Workspace Activation.",
        "workspace_name": workspace_name,
        "progress_percent": progress_percent,
    }


def list_pending_organizations(db: Session, *, status: str = ""):
    query = db.query(models.PendingOrganization)
    cleaned_status = str(status or "").strip().lower()
    if cleaned_status:
        query = query.filter(models.PendingOrganization.status == cleaned_status)
    return query.order_by(models.PendingOrganization.updated_at.desc(), models.PendingOrganization.id.desc()).all()


def add_pending_note(db: Session, organization, *, author_type: str, author_ref: str, note: str, is_internal: bool = True):
    cleaned_note = str(note or "").strip()
    if not cleaned_note:
        raise ValueError("Note is required.")
    db.add(
        models.PendingOrganizationNote(
            pending_organization_id=organization.id,
            author_type=str(author_type or "platform_owner")[:20],
            author_ref=str(author_ref or "")[:80] or None,
            note=cleaned_note[:4000],
            is_internal=bool(is_internal),
        )
    )


def list_pending_notes(db: Session, organization):
    return db.query(models.PendingOrganizationNote).filter(
        models.PendingOrganizationNote.pending_organization_id == organization.id
    ).order_by(models.PendingOrganizationNote.created_at.desc(), models.PendingOrganizationNote.id.desc()).all()


def update_pending_status(db: Session, organization, *, status: str, reviewer_user_id: str = "", rejection_reason: str = ""):
    cleaned_status = str(status or "").strip().lower()
    allowed = {"under_review", "changes_requested", "rejected", READY_FOR_CHECKOUT_STATUS}
    if cleaned_status not in allowed:
        raise ValueError("Unsupported pending organization status.")
    organization.status = cleaned_status
    organization.reviewed_at = _utcnow()
    organization.reviewed_by_user_id = str(reviewer_user_id or "").strip()[:10] or None
    organization.rejection_reason = str(rejection_reason or "").strip()[:4000] or None
    return organization


def validate_pending_organization_can_be_deleted(db: Session, organization) -> None:
    if not organization:
        raise ValueError("Pending organization not found.")

    status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    if status in {"activated"} or billing_status in BLOCKED_DELETE_BILLING_STATUSES:
        raise ValueError(
            "This organization cannot be deleted because it is already provisioned or linked to an active tenant."
        )

    tenant_link = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).first()
    if tenant_link:
        raise ValueError(
            "This organization cannot be deleted because it is already provisioned or linked to an active tenant."
        )

    linked_contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == organization.id,
        models.SubscriptionContract.school_group_id.isnot(None),
    ).first()
    if linked_contract:
        raise ValueError(
            "This organization cannot be deleted because it is already provisioned or linked to an active tenant."
        )

    linked_user = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.pending_organization_id == organization.id,
        models.SaaSAccountUserLink.school_group_id.isnot(None),
    ).first()
    if linked_user:
        raise ValueError(
            "This organization cannot be deleted because it is already provisioned or linked to an active tenant."
        )


def delete_pending_organization(db: Session, organization, *, actor_user_id: str = "") -> None:
    validate_pending_organization_can_be_deleted(db, organization)

    pending_organization_id = int(organization.id)
    owner_account_id = int(getattr(organization, "owner_saas_account_id", 0) or 0)
    logo_path = str(getattr(organization, "organization_logo_path", "") or "").strip()

    db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == pending_organization_id
    ).update(
        {models.PendingOrganization.last_payment_attempt_id: None},
        synchronize_session=False,
    )
    db.query(models.CheckoutSession).filter(
        models.CheckoutSession.pending_organization_id == pending_organization_id
    ).update(
        {models.CheckoutSession.last_payment_attempt_id: None},
        synchronize_session=False,
    )
    db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == pending_organization_id
    ).update(
        {models.SubscriptionContract.selected_checkout_session_id: None},
        synchronize_session=False,
    )

    provisioning_job_ids = [
        int(row_id)
        for (row_id,) in db.query(models.ProvisioningJob.id).filter(
            models.ProvisioningJob.pending_organization_id == pending_organization_id
        ).all()
    ]
    if provisioning_job_ids:
        db.query(models.ProvisioningJobEvent).filter(
            models.ProvisioningJobEvent.provisioning_job_id.in_(provisioning_job_ids)
        ).delete(synchronize_session=False)

    db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.CheckoutSession).filter(
        models.CheckoutSession.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.PendingOrganizationPlanSelection).filter(
        models.PendingOrganizationPlanSelection.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.PendingOrganizationBranch).filter(
        models.PendingOrganizationBranch.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)
    db.query(models.PendingOrganizationAcademicSetup).filter(
        models.PendingOrganizationAcademicSetup.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)
    db.query(models.PendingOrganizationContact).filter(
        models.PendingOrganizationContact.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)
    db.query(models.PendingOrganizationProgress).filter(
        models.PendingOrganizationProgress.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)
    db.query(models.PendingOrganizationNote).filter(
        models.PendingOrganizationNote.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)
    db.query(models.PendingOrganizationEvent).filter(
        models.PendingOrganizationEvent.pending_organization_id == pending_organization_id
    ).delete(synchronize_session=False)

    db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == pending_organization_id
    ).delete(synchronize_session=False)

    _delete_pending_logo_file(logo_path)

    owner_account = None
    if owner_account_id > 0:
        owner_account = db.query(models.SaaSAccount).filter(models.SaaSAccount.id == owner_account_id).first()

    if owner_account:
        remaining = get_pending_organization_for_account(db, owner_account)
        if remaining:
            progress = recalculate_pending_progress(db, remaining)
            update_pending_dashboard_status(owner_account, remaining, progress)
        else:
            owner_account.onboarding_status = "not_started"
        log_auth_event(
            db,
            event_type="pending_organization_deleted",
            account_id=owner_account.id,
            details={"actor_user_id": str(actor_user_id or "")[:10]},
        )


def link_or_create_social_account(
    db: Session,
    *,
    provider: str,
    provider_subject: str,
    email: str | None,
    email_verified: bool,
    first_name: str = "",
    last_name: str = "",
    tenant_hint: str = "",
    profile: dict | None = None,
    request: Request | None = None,
):
    policy = get_domain_policy(db, email)
    if email and not policy.allowed:
        raise ValueError(policy.reason or DISPOSABLE_EMAIL_BLOCK_MESSAGE)
    existing_identity = db.query(models.SaaSAuthIdentity).filter(
        models.SaaSAuthIdentity.provider == provider,
        models.SaaSAuthIdentity.provider_subject == provider_subject,
    ).first()
    if existing_identity:
        account = db.query(models.SaaSAccount).filter(
            models.SaaSAccount.id == existing_identity.saas_account_id
        ).first()
        if account:
            return account, policy

    normalized_email = auth.normalize_email(email)
    account = get_account_by_email(db, email) if normalized_email else None
    if not account:
        account = models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=str(email or "").strip(),
            email_normalized=normalized_email or f"{provider_subject}@unverified.local",
            password_hash=None,
            first_name=str(first_name or "").strip()[:120],
            last_name=str(last_name or "").strip()[:120],
            status="active" if email_verified else "pending_verification",
            onboarding_status="not_started",
            email_verified_at=_utcnow() if email_verified and normalized_email else None,
        )
        db.add(account)
        db.flush()
    elif email_verified and normalized_email and not account.email_verified_at:
        account.email_verified_at = _utcnow()
        if account.status == "pending_verification":
            account.status = "active"

    db.add(
        models.SaaSAuthIdentity(
            saas_account_id=account.id,
            provider=provider,
            provider_subject=provider_subject,
            provider_email=str(email or "").strip() or None,
            provider_email_normalized=normalized_email,
            provider_tenant_hint=str(tenant_hint or "").strip() or None,
            provider_profile_json=json.dumps(profile or {}, separators=(",", ":")) if profile else None,
        )
    )
    log_auth_event(
        db,
        event_type="social_login",
        account_id=account.id,
        request=request,
        details={"provider": provider, "warning": policy.warning},
    )
    return account, policy
