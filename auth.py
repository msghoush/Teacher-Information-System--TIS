import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import unicodedata

from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import Request, Depends
import bcrypt
import models
from dependencies import get_db

ROLE_DEVELOPER = "Developer"  # Legacy value migrated to PLATFORM/Platform Developer.
ROLE_ADMINISTRATOR = "Administrator"
ROLE_EDITOR = "Editor"
ROLE_USER = "User"
ROLE_LIMITED = "Limited"
ROLE_MANAGED_CHOICES = (
    ROLE_ADMINISTRATOR,
    ROLE_EDITOR,
    ROLE_USER,
    ROLE_LIMITED,
)
USER_TYPE_TENANT = "TENANT"
USER_TYPE_PLATFORM = "PLATFORM"
PLATFORM_ROLE_OWNER = "Platform Owner"
PLATFORM_ROLE_DEVELOPER = "Platform Developer"
PLATFORM_ROLE_CHOICES = (PLATFORM_ROLE_OWNER, PLATFORM_ROLE_DEVELOPER)
PLATFORM_OWNER_PRIMARY = "PRIMARY"
PLATFORM_OWNER_CO_OWNER = "CO_OWNER"
PLATFORM_OWNER_KINDS = (PLATFORM_OWNER_PRIMARY, PLATFORM_OWNER_CO_OWNER)
ACCESS_SCOPE_GLOBAL = "GLOBAL"
ACCESS_SCOPE_ORGANIZATION = "ORGANIZATION"
ACCESS_SCOPE_BRANCH = "BRANCH"
TENANT_ACCESS_SCOPE_CHOICES = (ACCESS_SCOPE_ORGANIZATION, ACCESS_SCOPE_BRANCH)
POSITION_EDUCATION_EXCELLENCE = "Education Excellence"
POSITION_MANAGEMENT = "Management"
ORGANIZATION_READ_ONLY_POSITIONS = frozenset(
    {POSITION_EDUCATION_EXCELLENCE, POSITION_MANAGEMENT}
)
INACTIVE_ACCOUNT_MESSAGE = "Your account is currently inactive. Please contact the system developer."
SESSION_COOKIE_KEY = "tis_session"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
SESSION_SECRET_ENV_NAME = "TIS_SESSION_SECRET"
MIN_SESSION_SECRET_LENGTH = 32

SYSTEM_CONFIGURATION_PERMISSION_PREFIXES = (
    "configuration.",
    "schools.",
    "branches.",
    "academic_years.",
    "branding.",
)
USER_MANAGEMENT_PREFIX = "users."
DATA_MODIFICATION_PERMISSION_PREFIXES = (
    "subjects.",
    "teachers.",
    "planning.",
    "timetable.",
    "calendar.",
    "observations.",
    "hiring_plan.",
)
DATA_DELETE_PERMISSIONS = frozenset(
    {
        "subjects.delete",
        "teachers.delete",
        "planning.delete_section",
        "timetable.delete",
        "calendar.delete",
        "observations.delete",
    }
)


def normalize_role(role: str) -> str:
    if not role:
        return ""
    cleaned = str(role).strip()
    lowered = cleaned.lower()
    if lowered == "developer":
        return ROLE_DEVELOPER
    if lowered in {"admin", "administrator"}:
        return ROLE_ADMINISTRATOR
    if lowered == "editor":
        return ROLE_EDITOR
    if lowered == "user":
        return ROLE_USER
    if lowered in {"limited access", "limited"}:
        return ROLE_LIMITED
    return cleaned


def normalize_user_type(user_type: str) -> str:
    cleaned = str(user_type or "").strip().upper()
    return cleaned if cleaned in {USER_TYPE_TENANT, USER_TYPE_PLATFORM} else ""


def normalize_platform_role(platform_role: str) -> str:
    cleaned = str(platform_role or "").strip().lower()
    if cleaned in {"owner", "platform owner"}:
        return PLATFORM_ROLE_OWNER
    if cleaned in {"developer", "platform developer"}:
        return PLATFORM_ROLE_DEVELOPER
    return ""


def normalize_platform_owner_kind(owner_kind: str) -> str:
    cleaned = str(owner_kind or "").strip().upper()
    return cleaned if cleaned in PLATFORM_OWNER_KINDS else ""


def normalize_access_scope(access_scope: str) -> str:
    cleaned = str(access_scope or "").strip().upper()
    if cleaned in {ACCESS_SCOPE_GLOBAL, ACCESS_SCOPE_ORGANIZATION, ACCESS_SCOPE_BRANCH}:
        return cleaned
    return ""


def is_platform_user(user) -> bool:
    user_type = normalize_user_type(getattr(user, "user_type", ""))
    if user_type == USER_TYPE_PLATFORM:
        return normalize_platform_role(getattr(user, "platform_role", "")) in PLATFORM_ROLE_CHOICES
    if user_type == USER_TYPE_TENANT:
        return False
    # Compatibility for objects loaded before the platform-identity migration.
    return normalize_role(getattr(user, "role", "")) == ROLE_DEVELOPER


def is_platform_owner(user) -> bool:
    return is_platform_user(user) and normalize_platform_role(
        getattr(user, "platform_role", "")
    ) == PLATFORM_ROLE_OWNER


def is_platform_developer(user) -> bool:
    if not is_platform_user(user):
        return False
    platform_role = normalize_platform_role(getattr(user, "platform_role", ""))
    return platform_role == PLATFORM_ROLE_DEVELOPER or not platform_role


def is_primary_platform_owner(user) -> bool:
    return is_platform_owner(user) and normalize_platform_owner_kind(
        getattr(user, "platform_owner_kind", "")
    ) == PLATFORM_OWNER_PRIMARY


def get_access_scope(user) -> str:
    if is_platform_user(user):
        return ACCESS_SCOPE_GLOBAL
    access_scope = normalize_access_scope(getattr(user, "access_scope", ""))
    if is_organization_read_only_position(getattr(user, "position", "")):
        return ACCESS_SCOPE_ORGANIZATION
    if access_scope in TENANT_ACCESS_SCOPE_CHOICES:
        return access_scope
    return ACCESS_SCOPE_BRANCH


def normalize_position(position: str) -> str:
    if not position:
        return ""
    cleaned = str(position).strip()
    lowered = cleaned.lower()
    if lowered in {"education excellence", "education excelency"}:
        return POSITION_EDUCATION_EXCELLENCE
    return cleaned


def is_organization_read_only_position(position: str) -> bool:
    return normalize_position(position) in ORGANIZATION_READ_ONLY_POSITIONS


def get_effective_tenant_role(user) -> str:
    if is_organization_read_only_position(getattr(user, "position", "")):
        return ROLE_LIMITED
    return normalize_role(getattr(user, "role", ""))


def _permission_registry_module():
    import permission_registry

    return permission_registry


def get_user_permission_keys(user) -> set[str]:
    cached = getattr(user, "permission_keys", None)
    if not cached:
        return set()
    return set(cached)


def _has_cached_permission(user, permission_key: str) -> bool:
    if is_platform_owner(user):
        return True
    return str(permission_key or "").strip() in get_user_permission_keys(user)


def _has_any_cached_permission(user, permission_keys) -> bool:
    return any(_has_cached_permission(user, permission_key) for permission_key in permission_keys)


def _has_cached_permission_prefix(user, prefixes) -> bool:
    if is_platform_owner(user):
        return True
    cached_keys = get_user_permission_keys(user)
    return any(
        str(permission_key).startswith(prefix)
        for permission_key in cached_keys
        for prefix in prefixes
    )


def _get_role_permission_rows(
    db: Session,
    role: str,
    school_group_id: int | None = None,
):
    permission_registry = _permission_registry_module()
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return []

    query = db.query(models.RolePermission).filter(
        models.RolePermission.role == normalized_role
    )
    if school_group_id is None:
        query = query.filter(models.RolePermission.school_group_id.is_(None))
    else:
        query = query.filter(models.RolePermission.school_group_id == school_group_id)
    return query.all()


def get_allowed_permission_keys(
    db: Session,
    user,
    school_group_id: int | None = None,
) -> set[str]:
    permission_registry = _permission_registry_module()
    if not user or not is_user_active(user):
        return set()

    if is_platform_owner(user):
        return set(permission_registry.ALL_PERMISSION_KEYS)
    if is_platform_developer(user):
        if not bool(getattr(user, "platform_permissions_initialized", False)):
            return set(permission_registry.PLATFORM_DEVELOPER_DEFAULT_PERMISSION_KEYS)
        try:
            rows = db.query(models.PlatformUserPermission).filter(
                models.PlatformUserPermission.platform_user_id == user.id,
                models.PlatformUserPermission.is_allowed == True,
            ).all()
        except Exception:
            return set()
        return {
            row.permission_key
            for row in rows
            if row.permission_key in permission_registry.DEVELOPER_ASSIGNABLE_PERMISSION_KEYS
        }

    normalized_role = permission_registry.normalize_managed_role(
        get_effective_tenant_role(user)
    )
    if not normalized_role:
        return set()
    resolved_school_group_id = school_group_id
    if resolved_school_group_id is None:
        resolved_school_group_id = (
            getattr(user, "scope_school_group_id", None)
            or getattr(user, "school_group_id", None)
            or get_user_school_group_id(db, user)
        )

    cache_key = (
        "permission_cache",
        normalized_role,
        int(resolved_school_group_id or 0),
    )
    cached_permissions = getattr(user, "_permission_cache", {})
    if cache_key in cached_permissions:
        return set(cached_permissions[cache_key])

    allowed_keys = permission_registry.get_default_permissions_for_role(normalized_role)
    for permission_row in _get_role_permission_rows(db, normalized_role, None):
        if permission_row.permission_key in permission_registry.PERMISSION_LABELS:
            if permission_row.is_allowed:
                allowed_keys.add(permission_row.permission_key)
            else:
                allowed_keys.discard(permission_row.permission_key)
    if resolved_school_group_id:
        for permission_row in _get_role_permission_rows(
            db,
            normalized_role,
            resolved_school_group_id,
        ):
            if permission_row.permission_key in permission_registry.PERMISSION_LABELS:
                if permission_row.is_allowed:
                    allowed_keys.add(permission_row.permission_key)
                else:
                    allowed_keys.discard(permission_row.permission_key)

    allowed_keys = permission_registry.constrain_role_permissions(
        normalized_role,
        allowed_keys,
    )
    cached_permissions[cache_key] = frozenset(allowed_keys)
    user._permission_cache = cached_permissions
    return set(allowed_keys)


def has_permission(
    db: Session,
    user,
    permission_key: str,
    *,
    school_group_id: int | None = None,
) -> bool:
    cleaned_permission_key = str(permission_key or "").strip()
    if not cleaned_permission_key:
        return True
    if not user or not is_user_active(user):
        return False
    if is_platform_owner(user):
        return True
    return cleaned_permission_key in get_allowed_permission_keys(
        db,
        user,
        school_group_id=school_group_id,
    )


def has_any_permission(
    db: Session,
    user,
    *permission_keys: str,
    school_group_id: int | None = None,
) -> bool:
    return any(
        has_permission(
            db,
            user,
            permission_key,
            school_group_id=school_group_id,
        )
        for permission_key in permission_keys
    )


def has_all_permissions(
    db: Session,
    user,
    *permission_keys: str,
    school_group_id: int | None = None,
) -> bool:
    return all(
        has_permission(
            db,
            user,
            permission_key,
            school_group_id=school_group_id,
        )
        for permission_key in permission_keys
    )


def can_access_all_branches(user, db: Session | None = None) -> bool:
    return get_access_scope(user) in {ACCESS_SCOPE_GLOBAL, ACCESS_SCOPE_ORGANIZATION}


def is_developer(user) -> bool:
    return is_platform_developer(user)


def is_user_active(user) -> bool:
    return bool(getattr(user, "is_active", False))


def can_access_all_years(user, db: Session | None = None) -> bool:
    if is_platform_user(user):
        return True
    if db is not None:
        return has_any_permission(
            db,
            user,
            "academic_years.view",
            "academic_years.activate",
        )
    return _has_any_cached_permission(
        user,
        ("academic_years.view", "academic_years.activate"),
    )


def can_manage_system_settings(user) -> bool:
    return _has_cached_permission_prefix(user, SYSTEM_CONFIGURATION_PERMISSION_PREFIXES)


def can_manage_users(user) -> bool:
    return _has_cached_permission(user, "users.view")


def can_modify_data(user) -> bool:
    if is_platform_owner(user):
        return True
    permission_registry = _permission_registry_module()
    return any(
        permission_key not in permission_registry.LIMITED_READ_ONLY_PERMISSION_KEYS
        and any(permission_key.startswith(prefix) for prefix in DATA_MODIFICATION_PERMISSION_PREFIXES)
        for permission_key in get_user_permission_keys(user)
    )


def can_edit_data(user) -> bool:
    return can_modify_data(user)


def can_delete_data(user) -> bool:
    return _has_any_cached_permission(user, DATA_DELETE_PERMISSIONS)


def can_edit_user_accounts(user) -> bool:
    return _has_any_cached_permission(
        user,
        (
            "users.edit_profile",
            "users.assign_position",
            "users.assign_role",
            "users.assign_branch",
            "users.activate_deactivate",
            "users.reset_password",
        ),
    )


def can_delete_user_accounts(user) -> bool:
    return _has_any_cached_permission(user, ("users.delete", "users.bulk_delete"))


def can_manage_target_user_account(current_user, target_user) -> bool:
    if not can_manage_users(current_user):
        return False
    if is_platform_user(target_user):
        return False
    if is_platform_user(current_user):
        return True
    current_group_id = getattr(current_user, "scope_school_group_id", None) or getattr(
        current_user,
        "school_group_id",
        None,
    )
    target_group_id = getattr(target_user, "school_group_id", None)
    if current_group_id and target_group_id and current_group_id != target_group_id:
        return False
    return True


def _get_positive_int_env(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, "") or "").strip()
    if not raw_value:
        return default
    try:
        parsed_value = int(raw_value)
    except ValueError:
        return default
    return parsed_value if parsed_value > 0 else default


def _session_max_age_seconds() -> int:
    return _get_positive_int_env("TIS_SESSION_MAX_AGE_SECONDS", SESSION_MAX_AGE_SECONDS)


def is_production_environment() -> bool:
    env_value = str(
        os.getenv("TIS_ENV")
        or os.getenv("ENV")
        or os.getenv("FASTAPI_ENV")
        or ""
    ).strip().lower()
    return env_value in {"prod", "production", "live"}


def _session_secret() -> str:
    value = str(os.getenv(SESSION_SECRET_ENV_NAME, "") or "").strip()
    if len(value) >= MIN_SESSION_SECRET_LENGTH:
        return value
    raise RuntimeError(
        f"{SESSION_SECRET_ENV_NAME} must be set to at least "
        f"{MIN_SESSION_SECRET_LENGTH} characters before sessions can be issued."
    )


def is_session_secret_configured() -> bool:
    return len(str(os.getenv(SESSION_SECRET_ENV_NAME, "") or "").strip()) >= MIN_SESSION_SECRET_LENGTH


def validate_security_configuration():
    _session_secret()
    cookie_secure_setting = str(os.getenv("TIS_COOKIE_SECURE", "") or "").strip().lower()
    if is_production_environment() and cookie_secure_setting in {"0", "false", "no", "off"}:
        raise RuntimeError("TIS_COOKIE_SECURE cannot be disabled in production.")


def _base64url_encode(raw_value: bytes) -> str:
    return base64.urlsafe_b64encode(raw_value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _sign_session_payload(payload_b64: str) -> str:
    signature = hmac.new(
        _session_secret().encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _base64url_encode(signature)


def create_session_token(user) -> str:
    payload = {
        "v": 1,
        "user_id": str(getattr(user, "user_id", "") or "").strip(),
        "iat": int(time.time()),
        "nonce": secrets.token_urlsafe(16),
    }
    payload_b64 = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{payload_b64}.{_sign_session_payload(payload_b64)}"


def decode_session_token(token: str):
    cleaned = str(token or "").strip()
    if "." not in cleaned:
        return None
    payload_b64, signature_b64 = cleaned.split(".", 1)
    if not payload_b64 or not signature_b64:
        return None
    expected_signature = _sign_session_payload(payload_b64)
    if not hmac.compare_digest(signature_b64, expected_signature):
        return None
    try:
        payload = json.loads(_base64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        return None
    try:
        issued_at = int(payload.get("iat") or 0)
    except (TypeError, ValueError):
        return None
    now = int(time.time())
    if issued_at <= 0 or issued_at > now + 300:
        return None
    if now - issued_at > _session_max_age_seconds():
        return None
    return payload


def create_email_verification_token(user) -> str:
    payload = {
        "v": 1,
        "purpose": "email_verification",
        "user_id": str(getattr(user, "user_id", "") or "").strip(),
        "email": normalize_email(getattr(user, "email", None)),
        "iat": int(time.time()),
        "nonce": secrets.token_urlsafe(16),
    }
    if not payload["user_id"] or not payload["email"]:
        raise ValueError("A user ID and email are required for verification.")
    payload_b64 = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{payload_b64}.{_sign_session_payload(payload_b64)}"


def decode_email_verification_token(token: str, max_age_seconds: int = 3600):
    cleaned = str(token or "").strip()
    if "." not in cleaned:
        return None
    payload_b64, signature_b64 = cleaned.split(".", 1)
    if not payload_b64 or not signature_b64:
        return None
    expected_signature = _sign_session_payload(payload_b64)
    if not hmac.compare_digest(signature_b64, expected_signature):
        return None
    try:
        payload = json.loads(_base64url_decode(payload_b64).decode("utf-8"))
        issued_at = int(payload.get("iat") or 0)
    except Exception:
        return None
    now = int(time.time())
    if (
        payload.get("purpose") != "email_verification"
        or not str(payload.get("user_id") or "").strip()
        or not normalize_email(payload.get("email"))
        or issued_at <= 0
        or issued_at > now + 300
        or now - issued_at > max(1, int(max_age_seconds))
    ):
        return None
    return payload


def get_session_payload_from_request(request: Request):
    return decode_session_token(request.cookies.get(SESSION_COOKIE_KEY))


def get_session_user_id(request: Request) -> str:
    payload = get_session_payload_from_request(request)
    return str(payload.get("user_id") or "").strip() if payload else ""


def should_use_secure_cookies(request: Request | None = None) -> bool:
    if is_production_environment():
        return True
    raw_value = str(os.getenv("TIS_COOKIE_SECURE", "") or "").strip().lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    return bool(request and request.url.scheme == "https")


def secure_cookie_kwargs(request: Request | None = None, *, max_age: int | None = None) -> dict:
    kwargs = {
        "httponly": True,
        "samesite": "lax",
        "secure": should_use_secure_cookies(request),
    }
    if max_age is not None:
        kwargs["max_age"] = max_age
    return kwargs


def set_auth_session_cookie(response, user, request: Request | None = None):
    response.set_cookie(
        key=SESSION_COOKIE_KEY,
        value=create_session_token(user),
        **secure_cookie_kwargs(request, max_age=_session_max_age_seconds()),
    )
    response.delete_cookie("user_id")
    return response


def set_scope_cookie(response, key: str, value, request: Request | None = None):
    response.set_cookie(
        key=key,
        value=str(value),
        **secure_cookie_kwargs(request),
    )
    return response


def _to_bytes(value):
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def get_password_hash(password: str):
    # bcrypt limits password input to 72 bytes. Truncate to keep startup safe.
    password_bytes = _to_bytes(password)[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password, hashed_password):
    try:
        plain_bytes = _to_bytes(plain_password)[:72]
        hashed_bytes = _to_bytes(hashed_password)
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


def normalize_email(value: str | None) -> str | None:
    """Return the canonical form used for login and uniqueness checks."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return normalized or None


def is_valid_email(value: str | None) -> bool:
    normalized = normalize_email(value)
    if not normalized or len(normalized) > 180 or any(char.isspace() for char in normalized):
        return False
    local_part, separator, domain = normalized.rpartition("@")
    return bool(
        separator
        and local_part
        and domain
        and "." in domain
        and not domain.startswith(".")
        and not domain.endswith(".")
    )


def resolve_login_user(db: Session, identifier: str):
    login_value = str(identifier or "").strip()
    if not login_value:
        return None

    # Preserve the established identifier precedence before trying new methods.
    user = db.query(models.User).filter(models.User.user_id == login_value).first()
    if user:
        return user

    normalized_email = normalize_email(login_value)
    if "@" in login_value and normalized_email:
        user = db.query(models.User).filter(
            models.User.email_normalized == normalized_email
        ).first()
        if user:
            return user

    lowered_login_value = login_value.lower()
    return db.query(models.User).filter(
        or_(
            models.User.username == login_value,
            models.User.username == lowered_login_value,
        )
    ).first()


def authenticate_user(db: Session, username: str, password: str):
    user = resolve_login_user(db, username)

    if not user:
        return None

    if not verify_password(password, user.password):
        return None

    return user


def get_branch_school_group_id(db: Session, branch_id) -> int | None:
    if not branch_id:
        return None
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    return getattr(branch, "school_group_id", None) if branch else None


def get_user_school_group_id(db: Session, user) -> int | None:
    if is_platform_user(user):
        return None
    branch_group_id = get_branch_school_group_id(db, getattr(user, "branch_id", None))
    return branch_group_id or getattr(user, "school_group_id", None)


def get_active_academic_year_for_school_group(db: Session, school_group_id: int | None):
    query = db.query(models.AcademicYear).filter(models.AcademicYear.is_active == True)
    if school_group_id:
        query = query.filter(models.AcademicYear.school_group_id == school_group_id)
    return query.order_by(models.AcademicYear.id.desc()).first()


def get_latest_academic_year_for_school_group(db: Session, school_group_id: int | None):
    query = db.query(models.AcademicYear)
    if school_group_id:
        query = query.filter(models.AcademicYear.school_group_id == school_group_id)
    return query.order_by(models.AcademicYear.id.desc()).first()


def get_academic_year_for_school_group(db: Session, academic_year_id, school_group_id: int | None):
    if not academic_year_id:
        return None
    query = db.query(models.AcademicYear).filter(models.AcademicYear.id == academic_year_id)
    if school_group_id:
        query = query.filter(models.AcademicYear.school_group_id == school_group_id)
    return query.first()


def get_accessible_branch_query(db: Session, user):
    access_scope = get_access_scope(user)
    if access_scope == ACCESS_SCOPE_GLOBAL:
        return db.query(models.Branch)

    query = db.query(models.Branch).filter(models.Branch.status == True)

    user_school_group_id = get_user_school_group_id(db, user)
    if access_scope == ACCESS_SCOPE_ORGANIZATION:
        if not user_school_group_id:
            return query.filter(models.Branch.id == -1)
        return query.filter(models.Branch.school_group_id == user_school_group_id)

    return query.filter(models.Branch.id == getattr(user, "branch_id", None))


def can_access_branch(db: Session, user, branch_id) -> bool:
    if not branch_id:
        return False
    return get_accessible_branch_query(db, user).filter(models.Branch.id == branch_id).first() is not None


def validate_branch_year_scope(
    db: Session,
    *,
    branch_id,
    academic_year_id,
    current_user=None,
) -> bool:
    if current_user is not None and not can_access_branch(db, current_user, branch_id):
        return False
    branch_query = db.query(models.Branch).filter(models.Branch.id == branch_id)
    if current_user is None or not is_platform_user(current_user):
        branch_query = branch_query.filter(models.Branch.status == True)
    branch = branch_query.first()
    if not branch:
        return False
    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()
    if not academic_year:
        return False
    return getattr(branch, "school_group_id", None) == getattr(academic_year, "school_group_id", None)


def _user_group_filter(db: Session, query, school_group_id: int | None):
    if not school_group_id:
        return query.filter(models.User.id == -1)
    branch_ids = db.query(models.Branch.id).filter(
        models.Branch.school_group_id == school_group_id
    )
    return query.filter(
        or_(
            models.User.school_group_id == school_group_id,
            models.User.branch_id.in_(branch_ids),
        )
    )


def filter_user_query_by_school_group(db: Session, query, school_group_id: int | None):
    return _user_group_filter(db, query, school_group_id)


def get_notification_recipient_query(db: Session, current_user):
    query = db.query(models.User).filter(models.User.is_active == True)
    scope_school_group_id = getattr(current_user, "scope_school_group_id", None) or get_user_school_group_id(
        db,
        current_user,
    )
    if scope_school_group_id:
        query = _user_group_filter(db, query, scope_school_group_id)
    elif not is_platform_user(current_user):
        query = query.filter(models.User.id == -1)
    if get_access_scope(current_user) == ACCESS_SCOPE_BRANCH:
        scope_branch_id = getattr(current_user, "scope_branch_id", None) or getattr(current_user, "branch_id", None)
        query = query.filter(models.User.branch_id == scope_branch_id)
    return query


def get_notification_school_group_id(db: Session, recipient_user=None, current_user=None):
    if recipient_user is not None:
        group_id = getattr(recipient_user, "school_group_id", None) or get_branch_school_group_id(
            db,
            getattr(recipient_user, "branch_id", None),
        )
        if group_id:
            return group_id
    if current_user is not None:
        return getattr(current_user, "scope_school_group_id", None) or get_user_school_group_id(db, current_user)
    return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = get_session_user_id(request)

    if not user_id:
        return None

    user = db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()

    if not user:
        return None

    if not is_user_active(user):
        request.state.audit_actor_user_id = user.user_id
        request.state.audit_actor_username = user.username or ""
        request.state.audit_actor_role = normalize_role(user.role)
        request.state.audit_actor_branch_id = user.branch_id
        request.state.inactive_user_id = user.user_id
        return None

    user_school_group_id = get_user_school_group_id(db, user)
    if not user_school_group_id and not is_platform_user(user):
        request.state.auth_error = "missing_school_group"
        return None

    if user_school_group_id and not getattr(user, "school_group_id", None):
        user.school_group_id = user_school_group_id

    branch_cookie = request.cookies.get("branch_id")
    school_group_cookie = request.cookies.get("school_group_id")
    year_cookie = request.cookies.get("academic_year_id")

    platform_user = is_platform_user(user)
    scoped_branch_id = None if platform_user else user.branch_id
    scoped_academic_year_id = None if platform_user else user.academic_year_id

    try:
        parsed_branch_id = int(branch_cookie) if branch_cookie else None
    except ValueError:
        parsed_branch_id = None

    try:
        parsed_school_group_id = int(school_group_cookie) if school_group_cookie else None
    except ValueError:
        parsed_school_group_id = None

    try:
        parsed_year_id = int(year_cookie) if year_cookie else None
    except ValueError:
        parsed_year_id = None

    can_all_branch_scope = can_access_all_branches(user, db)
    active_branches = get_accessible_branch_query(db, user).order_by(models.Branch.name.asc()).all()
    active_branch_ids = {branch.id for branch in active_branches}

    selected_platform_group = None
    if platform_user and parsed_school_group_id:
        selected_platform_group = db.query(models.SchoolGroup).filter(
            models.SchoolGroup.id == parsed_school_group_id
        ).first()

    if can_all_branch_scope:
        if parsed_branch_id and parsed_branch_id in active_branch_ids:
            parsed_branch = next(
                (branch for branch in active_branches if branch.id == parsed_branch_id),
                None,
            )
            if (
                not selected_platform_group
                or getattr(parsed_branch, "school_group_id", None) == selected_platform_group.id
            ):
                scoped_branch_id = parsed_branch_id
        elif not platform_user and user.branch_id in active_branch_ids:
            scoped_branch_id = user.branch_id
        elif not platform_user and active_branches:
            scoped_branch_id = active_branches[0].id
    elif parsed_branch_id and parsed_branch_id == user.branch_id:
        scoped_branch_id = parsed_branch_id

    scoped_school_group_id = getattr(selected_platform_group, "id", None)
    if scoped_branch_id:
        scoped_branch = db.query(models.Branch).filter(
            models.Branch.id == scoped_branch_id
        ).first()
        branch_group_id = getattr(scoped_branch, "school_group_id", None) if scoped_branch else None
        if scoped_school_group_id and branch_group_id != scoped_school_group_id:
            scoped_branch_id = None
        else:
            scoped_school_group_id = branch_group_id

    active_year = (
        get_active_academic_year_for_school_group(db, scoped_school_group_id)
        if scoped_branch_id or not platform_user
        else None
    )

    can_all_year_scope = can_access_all_years(user, db)
    selected_year = (
        get_academic_year_for_school_group(db, parsed_year_id, scoped_school_group_id)
        if scoped_branch_id or not platform_user
        else None
    )
    assigned_year = (
        get_academic_year_for_school_group(
            db,
            getattr(user, "academic_year_id", None),
            scoped_school_group_id,
        )
        if not platform_user
        else None
    )
    if can_all_year_scope and selected_year:
        scoped_academic_year_id = selected_year.id
    elif active_year:
        scoped_academic_year_id = active_year.id
    elif assigned_year:
        scoped_academic_year_id = assigned_year.id
    elif selected_year:
        scoped_academic_year_id = selected_year.id
    elif is_platform_user(user) and scoped_branch_id and scoped_school_group_id:
        latest_year = get_latest_academic_year_for_school_group(db, scoped_school_group_id)
        scoped_academic_year_id = getattr(latest_year, "id", None)

    if scoped_branch_id and scoped_academic_year_id and not validate_branch_year_scope(
        db,
        branch_id=scoped_branch_id,
        academic_year_id=scoped_academic_year_id,
        current_user=user,
    ):
        fallback_year = get_active_academic_year_for_school_group(db, scoped_school_group_id)
        if fallback_year:
            scoped_academic_year_id = fallback_year.id
        else:
            scoped_academic_year_id = None

    if (not scoped_branch_id or not scoped_academic_year_id) and not is_platform_user(user):
        request.state.auth_error = "missing_tenant_scope"
        return None

    user.scope_branch_id = scoped_branch_id
    user.scope_academic_year_id = scoped_academic_year_id
    user.scope_school_group_id = scoped_school_group_id
    user.effective_role = (
        normalize_platform_role(getattr(user, "platform_role", ""))
        if is_platform_user(user)
        else get_effective_tenant_role(user)
    )
    user.effective_position = normalize_position(getattr(user, "position", ""))
    user.can_access_all_branches = can_all_branch_scope
    user.can_access_all_years = can_all_year_scope
    user.permission_keys = frozenset(
        get_allowed_permission_keys(
            db,
            user,
            school_group_id=scoped_school_group_id or user_school_group_id,
        )
    )

    request.state.audit_actor_user_id = user.user_id
    request.state.audit_actor_username = user.username or ""
    request.state.audit_actor_role = normalize_role(user.role)
    request.state.audit_actor_branch_id = scoped_branch_id

    return user
