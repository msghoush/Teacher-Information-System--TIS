from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

import models
import permission_registry


def get_role_permission_rows(
    db: Session,
    role: str,
    school_group_id: int | None = None,
) -> list[models.RolePermission]:
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
    return query.order_by(models.RolePermission.id.asc()).all()


def get_allowed_permission_keys(
    db: Session,
    role: str,
    school_group_id: int | None = None,
) -> set[str]:
    """Resolve built-in defaults, global overrides, then tenant overrides."""
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return set()

    allowed_keys = permission_registry.get_default_permissions_for_role(normalized_role)
    scopes = (None,) if school_group_id is None else (None, school_group_id)
    for scope_id in scopes:
        for row in get_role_permission_rows(db, normalized_role, scope_id):
            if row.permission_key not in permission_registry.PERMISSION_LABELS:
                continue
            if row.is_allowed:
                allowed_keys.add(row.permission_key)
            else:
                allowed_keys.discard(row.permission_key)
    return permission_registry.constrain_role_permissions(normalized_role, allowed_keys)


def resolve_permission_details(
    db: Session,
    role: str,
    school_group_id: int | None = None,
) -> dict[str, dict]:
    """Resolve, per permission key, the granting source, direct-assignment flag,
    and inheritance flag so the UI can distinguish 'directly assigned here' from
    'effective via default/global inheritance'."""
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return {}

    def constrain(keys) -> set[str]:
        return permission_registry.constrain_role_permissions(normalized_role, keys)

    default_keys = permission_registry.get_default_permissions_for_role(normalized_role)

    global_allow: set[str] = set()
    global_deny: set[str] = set()
    for row in get_role_permission_rows(db, normalized_role, None):
        key = row.permission_key
        if key not in permission_registry.PERMISSION_LABELS:
            continue
        if row.is_allowed:
            global_allow.add(key)
        else:
            global_deny.add(key)
    global_allow = constrain(global_allow)
    global_deny = constrain(global_deny)

    school_allow: set[str] = set()
    school_deny: set[str] = set()
    if school_group_id is not None:
        for row in get_role_permission_rows(db, normalized_role, school_group_id):
            key = row.permission_key
            if key not in permission_registry.PERMISSION_LABELS:
                continue
            if row.is_allowed:
                school_allow.add(key)
            else:
                school_deny.add(key)
    school_allow = constrain(school_allow)
    school_deny = constrain(school_deny)

    effective = get_allowed_permission_keys(db, normalized_role, school_group_id)

    details: dict[str, dict] = {}
    for key in permission_registry.ALL_PERMISSION_KEYS:
        allowed = key in effective
        if school_group_id is not None:
            if key in school_allow:
                source, direct = "school", True
            elif key in school_deny:
                source, direct = "denied", False
            elif key in global_allow:
                source, direct = "global", False
            elif key in global_deny:
                source, direct = "denied", False
            elif key in default_keys:
                source, direct = "default", False
            else:
                source, direct = "none", False
        else:
            if key in global_allow:
                source, direct = "global", True
            elif key in global_deny:
                source, direct = "denied", False
            elif key in default_keys:
                source, direct = "default", False
            else:
                source, direct = "none", False
        details[key] = {
            "allowed": allowed,
            "direct": direct,
            "inherited": bool(allowed and not direct),
            "source": source,
        }
    return details



def build_role_permission_payload(
    db: Session,
    role: str,
    school_group_id: int | None = None,
) -> dict:
    return permission_registry.build_role_permission_payload(
        role,
        get_allowed_permission_keys(db, role, school_group_id),
        resolve_permission_details(db, role, school_group_id),
    )


def set_role_permission_rows(
    db: Session,
    *,
    role: str,
    allowed_keys: set[str],
    school_group_id: int | None,
    updated_by_user_id: str | None,
):
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return

    valid_keys = set(permission_registry.ALL_PERMISSION_KEYS)
    allowed_keys = permission_registry.constrain_role_permissions(
        normalized_role,
        allowed_keys & valid_keys,
    )
    existing_rows: dict[str, models.RolePermission] = {}
    for row in get_role_permission_rows(db, normalized_role, school_group_id):
        previous = existing_rows.get(row.permission_key)
        if previous is not None:
            db.delete(previous)
        existing_rows[row.permission_key] = row
    now = datetime.now(UTC).replace(tzinfo=None)
    for permission_key in valid_keys:
        is_allowed = permission_key in allowed_keys
        row = existing_rows.get(permission_key)
        if row:
            row.is_allowed = is_allowed
            row.updated_by_user_id = updated_by_user_id
            row.updated_at = now
        else:
            db.add(
                models.RolePermission(
                    school_group_id=school_group_id,
                    role=normalized_role,
                    permission_key=permission_key,
                    is_allowed=is_allowed,
                    updated_by_user_id=updated_by_user_id,
                    created_at=now,
                    updated_at=now,
                )
            )


def apply_role_permission_overrides(
    db: Session,
    *,
    role: str,
    allowed_keys: set[str],
    school_group_id: int | None,
    updated_by_user_id: str | None,
) -> None:
    """Persist only intentional scope-level overrides (the administrator Save path).

    The submitted ``allowed_keys`` reflect the effective checkboxes. Any key whose
    submitted state equals its inherited baseline is left to fall through to the
    resolver (no scope-level row), so a no-op Save never converts
    inherited/default/global grants into explicit direct rows.
    """
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return

    valid_keys = set(permission_registry.ALL_PERMISSION_KEYS)
    submitted = permission_registry.constrain_role_permissions(
        normalized_role,
        set(allowed_keys or ()) & valid_keys,
    )
    if school_group_id is None:
        baseline = permission_registry.get_default_permissions_for_role(normalized_role)
    else:
        baseline = get_allowed_permission_keys(db, normalized_role, None)

    allow_overrides = submitted - baseline
    deny_overrides = baseline - submitted
    override_keys = allow_overrides | deny_overrides

    existing_rows: dict[str, models.RolePermission] = {}
    for row in get_role_permission_rows(db, normalized_role, school_group_id):
        previous = existing_rows.get(row.permission_key)
        if previous is not None:
            db.delete(previous)
        existing_rows[row.permission_key] = row

    now = datetime.now(UTC).replace(tzinfo=None)
    for key, row in existing_rows.items():
        if key not in override_keys:
            db.delete(row)
            continue
        row.is_allowed = key in allow_overrides
        row.updated_by_user_id = updated_by_user_id
        row.updated_at = now

    for key in sorted(override_keys):
        if key in existing_rows:
            continue
        db.add(
            models.RolePermission(
                school_group_id=school_group_id,
                role=normalized_role,
                permission_key=key,
                is_allowed=key in allow_overrides,
                updated_by_user_id=updated_by_user_id,
                created_at=now,
                updated_at=now,
            )
        )


def seed_global_role_permissions(db: Session, *, updated_by_user_id: str = "system"):
    for role in permission_registry.MANAGED_ROLES:
        if get_role_permission_rows(db, role, None):
            continue
        set_role_permission_rows(
            db,
            role=role,
            allowed_keys=permission_registry.get_default_permissions_for_role(role),
            school_group_id=None,
            updated_by_user_id=updated_by_user_id,
        )


def seed_tenant_role_permissions(
    db: Session,
    *,
    school_group_id: int,
    updated_by_user_id: str = "system",
):
    for role in permission_registry.MANAGED_ROLES:
        if get_role_permission_rows(db, role, school_group_id):
            continue
        set_role_permission_rows(
            db,
            role=role,
            allowed_keys=permission_registry.get_default_permissions_for_role(role),
            school_group_id=school_group_id,
            updated_by_user_id=updated_by_user_id,
        )
