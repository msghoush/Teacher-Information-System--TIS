from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

import models
import auth
import permission_registry
import role_permission_service

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_INHERIT = "inherit"
VALID_DECISIONS = (DECISION_ALLOW, DECISION_DENY, DECISION_INHERIT)


def get_user_overrides(db: Session, user_pk: int, school_group_id: int | None = None) -> dict[str, bool]:
    query = db.query(models.UserPermissionOverride).filter(
        models.UserPermissionOverride.user_id == user_pk
    )
    if school_group_id is not None:
        query = query.filter(models.UserPermissionOverride.school_group_id == school_group_id)
    return {row.permission_key: bool(row.is_allowed) for row in query.all()}


def apply_user_override(
    db: Session,
    *,
    target_user,
    permission_key: str,
    decision: str,
    school_group_id: int | None,
    updated_by_user_id: str | None = None,
) -> dict:
    """Persist one per-user Allow/Deny decision, or remove it for Inherit.

    Raises ValueError for unknown/platform-only or nonassignable keys, invalid
    decisions, or a target outside the caller's SchoolGroup. Inherit can remove
    a previously stored nonassignable override after a role change."""
    permission_key = str(permission_key or "").strip()
    decision = str(decision or "").strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be allow, deny, or inherit")
    if permission_key not in permission_registry.PERMISSION_LABELS:
        raise ValueError("unknown permission key")
    if permission_key in permission_registry.PLATFORM_ONLY_PERMISSION_KEYS:
        raise ValueError("platform-only permissions cannot be overridden per user")

    target_group = getattr(target_user, "school_group_id", None)
    if not target_group or target_group != school_group_id:
        raise ValueError("target user is not in the active SchoolGroup")

    existing = (
        db.query(models.UserPermissionOverride)
        .filter(
            models.UserPermissionOverride.user_id == target_user.id,
            models.UserPermissionOverride.permission_key == permission_key,
        )
        .first()
    )

    if decision == DECISION_INHERIT:
        if existing is not None:
            db.delete(existing)
        return {"permission_key": permission_key, "decision": DECISION_INHERIT}

    normalized_role = permission_registry.normalize_managed_role(
        auth.get_effective_tenant_role(target_user)
    )
    if not normalized_role or not _is_assignable(normalized_role, permission_key):
        raise ValueError("permission cannot be overridden for this user's role")

    is_allowed = decision == DECISION_ALLOW
    now = datetime.now(UTC).replace(tzinfo=None)
    if existing is not None:
        existing.is_allowed = is_allowed
        existing.school_group_id = school_group_id
        existing.updated_by_user_id = updated_by_user_id
        existing.updated_at = now
    else:
        db.add(
            models.UserPermissionOverride(
                school_group_id=school_group_id,
                user_id=target_user.id,
                permission_key=permission_key,
                is_allowed=is_allowed,
                updated_by_user_id=updated_by_user_id,
                created_at=now,
                updated_at=now,
            )
        )
    return {"permission_key": permission_key, "decision": decision}


def apply_overrides_to_keys(allowed_keys: set[str], overrides: dict[str, bool]) -> set[str]:
    """Fold per-user Allow/Deny overrides onto a role-resolved key set.

    Precedence is Deny-over-Allow: a per-user Deny override always removes a
    key. A per-user Allow override is intentionally NOT permitted to exceed
    (override) a role-level Deny -- there is no approved security-architecture
    decision authorizing a user-level Allow to grant access the role itself
    does not currently have. An Allow override therefore only has effect when
    the key is already present in ``allowed_keys`` (i.e. it is a no-op against
    the role-resolved set); it never adds a key the role denies. This is a
    deliberate, conservative default pending explicit Owner sign-off -- see
    docs/TIS_MASTER_CONTEXT.md "Per-User Permission Overrides" for the
    recorded decision and escalation note.
    """
    result = set(allowed_keys)
    for key, is_allowed in overrides.items():
        if is_allowed:
            continue  # Allow cannot override a role-level Deny (see docstring).
        result.discard(key)
    return result


def _is_assignable(normalized_role: str, key: str) -> bool:
    return key in permission_registry.constrain_role_permissions(normalized_role, {key})


def build_user_permission_payload(
    db: Session,
    *,
    target_user,
    normalized_role: str,
    school_group_id: int | None,
) -> dict:
    normalized_role = permission_registry.normalize_managed_role(
        auth.get_effective_tenant_role(target_user)
    )
    role_allowed = role_permission_service.get_allowed_permission_keys(db, normalized_role, school_group_id)
    overrides = get_user_overrides(db, target_user.id, school_group_id)
    effective = auth.get_allowed_permission_keys(db, target_user, school_group_id)

    groups = []
    for group in permission_registry.PERMISSION_GROUPS:
        permissions = []
        for key, label in group["permissions"]:
            platform_only = key in permission_registry.PLATFORM_ONLY_PERMISSION_KEYS
            override = overrides.get(key)
            if override is True:
                state = "allow"
            elif override is False:
                state = "deny"
            else:
                state = "inherit"
            permissions.append(
                {
                    "key": key,
                    "label": label,
                    "platform_only": platform_only,
                    "assignable": _is_assignable(normalized_role, key),
                    "role_allowed": key in role_allowed,
                    "override": override,
                    "effective": key in effective,
                    "state": state,
                }
            )
        groups.append(
            {
                "key": group["key"],
                "label": group["label"],
                "permissions": permissions,
                "override_count": sum(1 for item in permissions if item["state"] != "inherit"),
            }
        )
    return {
        "user_id": target_user.id,
        "role": normalized_role,
        "groups": groups,
    }
