import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

import auth
import email_service
import email_templates
from saas import models

SAAS_SESSION_COOKIE = "tis_saas_session"
SAAS_CSRF_COOKIE = "tis_saas_csrf"
SAAS_SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
SAAS_EMAIL_VERIFICATION_MAX_AGE_SECONDS = 60 * 60
LOGIN_RATE_LIMIT_ATTEMPTS = 10
LOGIN_RATE_LIMIT_WINDOW_MINUTES = 15
SIGNUP_RATE_LIMIT_ATTEMPTS = 8
SIGNUP_RATE_LIMIT_WINDOW_MINUTES = 60
VERIFICATION_RATE_LIMIT_ATTEMPTS = 5
VERIFICATION_RATE_LIMIT_WINDOW_MINUTES = 60
PERSONAL_EMAIL_WARNING = (
    "Personal email domains are not recommended for school onboarding. You can continue now, "
    "but a work email will be requested during organization setup."
)
DISPOSABLE_EMAIL_BLOCK_MESSAGE = (
    "Disposable email domains are not allowed for TIS SaaS account registration."
)


@dataclass(frozen=True)
class DomainPolicyResult:
    domain: str
    allowed: bool
    warning: str = ""
    reason: str = ""
    enforcement: str = ""


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
        raise ValueError("This email is already registered for a TIS SaaS account.")

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
    configured_url = str(os.environ.get("TIS_PUBLIC_BASE_URL") or "").strip()
    return (configured_url or str(request.base_url)).rstrip("/")


def build_verification_url(request: Request, token: str) -> str:
    return f"{email_public_base_url(request)}/saas/auth/verify-email?token={token}"


def send_verification_email(db: Session, account, request: Request) -> None:
    token = create_email_verification_token(db, account, request=request)
    verification_url = build_verification_url(request, token)
    logo_url = f"{email_public_base_url(request)}/static/branding/tis/logos/tis-wordmark-dark-blue.png"
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
