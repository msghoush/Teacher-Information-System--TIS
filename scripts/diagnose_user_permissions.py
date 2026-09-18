"""Read-only permission-resolution diagnostic for a specific TIS user.

Reuses the canonical permission services (``role_permission_service``,
``user_permission_service``, ``auth.get_allowed_permission_keys``) end to
end for one account and one permission key. It never writes any database
row, never duplicates permission-resolution logic, and never prints
password hashes, tokens, secrets, or the ``DATABASE_URL``/connection
string -- including on database-connectivity failure paths.

This tool is generic and reusable for any future permission-visibility
report, not specific to any one permission key or account. Run it against
whichever database your environment's ``DATABASE_URL`` points to (local
SQLite fallback, or a real Postgres instance) -- it never overrides that
value itself.

Usage:
    python scripts/diagnose_user_permissions.py --email someone@example.com --permission-key subjects.view
"""

from __future__ import annotations

import argparse
import json

import auth
import models
import permission_registry
import role_permission_service
import user_permission_service
from database import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only trace of one user's effective permission resolution "
            "through the canonical TIS permission services."
        )
    )
    parser.add_argument("--email", required=True, help="Exact account email to inspect.")
    parser.add_argument(
        "--permission-key",
        required=True,
        help=(
            "A single registered permission key to trace in detail (e.g. "
            "subjects.view). Reports the built-in role default, global "
            "RolePermission, tenant RolePermission, user override, "
            "role-effective result, and final-effective result for this key."
        ),
    )
    return parser


def _school_group_summary(db, school_group_id):
    if not school_group_id:
        return None
    row = db.query(models.SchoolGroup).filter(models.SchoolGroup.id == school_group_id).first()
    if row is None:
        return {"id": school_group_id, "name": None, "exists": False}
    return {"id": row.id, "name": getattr(row, "name", None), "exists": True}


def _branch_summary(db, branch_id):
    if not branch_id:
        return None
    row = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    if row is None:
        return {"id": branch_id, "name": None, "exists": False}
    return {
        "id": row.id,
        "name": getattr(row, "name", None),
        "school_group_id": getattr(row, "school_group_id", None),
        "exists": True,
    }


def _trace_permission_key(db, user, normalized_role, school_group_id, permission_key):
    """Report built-in default, global row, tenant row, user override, and
    role-effective / final-effective results for one permission key."""
    built_in_default = permission_key in permission_registry.get_default_permissions_for_role(
        normalized_role
    )

    global_rows = role_permission_service.get_role_permission_rows(db, normalized_role, None)
    global_row = next((r for r in global_rows if r.permission_key == permission_key), None)
    global_state = None if global_row is None else bool(global_row.is_allowed)

    tenant_row = None
    tenant_state = None
    if school_group_id is not None:
        tenant_rows = role_permission_service.get_role_permission_rows(
            db, normalized_role, school_group_id
        )
        tenant_row = next((r for r in tenant_rows if r.permission_key == permission_key), None)
        tenant_state = None if tenant_row is None else bool(tenant_row.is_allowed)

    role_effective_keys = role_permission_service.get_allowed_permission_keys(
        db, normalized_role, school_group_id
    )
    role_effective = permission_key in role_effective_keys

    overrides = user_permission_service.get_user_overrides(db, int(user.id), school_group_id)
    user_override_state = overrides.get(permission_key)
    if permission_key in overrides:
        user_override_decision = "allow" if overrides[permission_key] else "deny"
    else:
        user_override_decision = "inherit"

    final_effective_keys = auth.get_allowed_permission_keys(db, user, school_group_id)
    final_effective = permission_key in final_effective_keys

    return {
        "permission_key": permission_key,
        "built_in_default_for_role": built_in_default,
        "global_role_permission_row": (
            None if global_row is None else {"is_allowed": global_state}
        ),
        "tenant_role_permission_row": (
            None if tenant_row is None else {"is_allowed": tenant_state}
        ),
        "user_override": {
            "decision": user_override_decision,
            "is_allowed": user_override_state,
        },
        "role_effective_before_user_override": role_effective,
        "final_effective_after_user_override": final_effective,
    }


def diagnose(db, *, email: str, permission_key: str) -> dict:
    email = str(email or "").strip()
    permission_key = str(permission_key or "").strip()
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        return {
            "status": "not_found",
            "email": email,
            "message": "No user row with this exact email exists in the connected database.",
        }

    stored_role = getattr(user, "role", None)
    normalized_role = permission_registry.normalize_managed_role(
        auth.get_effective_tenant_role(user)
    )
    school_group_id = auth.get_user_school_group_id(db, user)
    branch_id = getattr(user, "branch_id", None)

    allowed_keys_for_key_scan = auth.get_allowed_permission_keys(db, user, school_group_id)

    result = {
        "status": "found",
        "email": email,
        "user_id": user.id,
        "stored_role": stored_role,
        "normalized_effective_role": normalized_role or None,
        "user_type": getattr(user, "user_type", None),
        "is_active": bool(auth.is_user_active(user)),
        "position": getattr(user, "position", None),
        "stored_school_group_id": getattr(user, "school_group_id", None),
        "stored_branch_id": branch_id,
        "resolved_school_group": _school_group_summary(db, school_group_id),
        "resolved_branch": _branch_summary(db, branch_id),
        "branch_derived_school_group_id": auth.get_branch_school_group_id(db, branch_id),
        "permission_key": permission_key,
        "get_allowed_permission_keys_contains_requested_key": None,
    }

    if permission_key not in permission_registry.PERMISSION_LABELS:
        result["status"] = "unknown_permission_key"
        return result

    if not normalized_role:
        result["note"] = (
            "Role does not normalize to a managed role (Administrator/Editor/"
            "User/Limited Access); no role-permission resolution applies."
        )
        return result

    result["permission_trace"] = _trace_permission_key(
        db, user, normalized_role, school_group_id, permission_key
    )
    result["get_allowed_permission_keys_contains_requested_key"] = (
        permission_key in allowed_keys_for_key_scan
    )

    return result


def main() -> int:
    args = build_parser().parse_args()
    try:
        db = SessionLocal()
    except Exception:
        # A connection/engine construction failure can embed the raw
        # DATABASE_URL (including any credentials) in its exception
        # message. Never surface that detail -- fail with a generic,
        # safe message instead of a raw stack trace.
        print(
            json.dumps(
                {
                    "status": "database_unavailable",
                    "message": (
                        "Could not establish a database session. Check that "
                        "DATABASE_URL is configured correctly; no connection "
                        "details are shown for safety."
                    ),
                },
                indent=2,
            )
        )
        return 2

    try:
        try:
            result = diagnose(db, email=args.email, permission_key=args.permission_key)
        except Exception:
            db.rollback()
            print(
                json.dumps(
                    {
                        "status": "database_unavailable",
                        "message": (
                            "The database query failed. Check that "
                            "DATABASE_URL is configured correctly and the "
                            "target database is reachable; no connection "
                            "details are shown for safety."
                        ),
                    },
                    indent=2,
                )
            )
            return 2
        print(json.dumps(result, indent=2, sort_keys=False, default=str))
        return 0 if result.get("status") == "found" else 1
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
