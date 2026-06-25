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
    return query.all()


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
    existing_rows = {
        row.permission_key: row
        for row in get_role_permission_rows(db, normalized_role, school_group_id)
    }
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
