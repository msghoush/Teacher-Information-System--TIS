import os

os.environ["TIS_SESSION_SECRET"] = "user-permission-override-test-secret-that-is-long-enough"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import authorization
import main
import models
import permission_registry
import role_permission_service
import user_permission_service as ups

ADMIN = auth.ROLE_ADMINISTRATOR


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def _seed_two_admins(Session):
    db = Session()
    try:
        school = models.SchoolGroup(name="Al-Andalus Schools", status=True)
        db.add(school)
        db.flush()
        other_school = models.SchoolGroup(name="Other Schools", status=True)
        db.add(other_school)
        db.flush()
        branch = models.Branch(name="Hamadania-Boys", school_group_id=school.id, status=True)
        db.add(branch)
        db.flush()
        other_branch = models.Branch(name="Other Branch", school_group_id=other_school.id, status=True)
        db.add(other_branch)
        db.flush()
        year = models.AcademicYear(school_group_id=school.id, year_name="2026-2027", is_active=True)
        db.add(year)
        db.flush()
        other_year = models.AcademicYear(school_group_id=other_school.id, year_name="2026-2027", is_active=True)
        db.add(other_year)
        db.flush()
        user_a = models.User(
            user_id="1001", username="admin_a", first_name="Admin", last_name="A",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id,
            is_active=True,
        )
        user_b = models.User(
            user_id="1002", username="admin_b", first_name="Admin", last_name="B",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id,
            is_active=True,
        )
        other_user = models.User(
            user_id="2001", username="admin_other", first_name="Admin", last_name="Other",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=other_school.id, branch_id=other_branch.id, academic_year_id=other_year.id,
            is_active=True,
        )
        inactive_user = models.User(
            user_id="1003", username="admin_inactive", first_name="Admin", last_name="Inactive",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id,
            is_active=False,
        )
        db.add_all([user_a, user_b, other_user, inactive_user])
        db.commit()
        return {
            "school_id": school.id,
            "other_school_id": other_school.id,
            "user_a_id": user_a.id,
            "user_b_id": user_b.id,
            "other_user_id": other_user.id,
            "inactive_user_id": inactive_user.id,
        }
    finally:
        db.close()


def _request(path, method="GET"):
    scope = {
        "type": "http", "http_version": "1.1", "method": method, "path": path,
        "raw_path": path.encode("utf-8"), "query_string": b"",
        "headers": [(b"host", b"testserver")], "scheme": "http",
        "server": ("testserver", 80), "client": ("testclient", 50000),
        "root_path": "", "app": main.app,
    }
    return Request(scope)


def _guard(Session, user_id, path):
    read = Session()
    try:
        fresh = read.query(models.User).get(user_id)
        return authorization.enforce_route_permission(_request(path), read, current_user=fresh)
    finally:
        read.close()


def _allowed_after(Session, user_id, school_id):
    read = Session()
    try:
        fresh = read.query(models.User).get(user_id)
        return auth.get_allowed_permission_keys(read, fresh, school_id)
    finally:
        read.close()


# ---------------------------------------------------------------------------
# Two Administrators, one SchoolGroup: deny for B only, A unaffected
# ---------------------------------------------------------------------------

def test_deny_override_affects_only_target_user_not_sibling_admin():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        # Both A and B inherit dashboard.view from the role by default.
        assert "dashboard.view" in _allowed_after(Session, ids["user_a_id"], ids["school_id"])
        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        assert _guard(Session, ids["user_a_id"], "/dashboard") is None
        assert _guard(Session, ids["user_b_id"], "/dashboard") is None

        user_b = db.query(models.User).get(ids["user_b_id"])
        ups.apply_user_override(
            db,
            target_user=user_b,
            permission_key="dashboard.view",
            decision=ups.DECISION_DENY,
            school_group_id=ids["school_id"],
            updated_by_user_id="1001",
        )
        db.commit()

        # B loses dashboard.view (nav-equivalent set + route guard); A is unaffected.
        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        denied = _guard(Session, ids["user_b_id"], "/dashboard")
        assert denied is not None and denied.status_code == 403

        assert "dashboard.view" in _allowed_after(Session, ids["user_a_id"], ids["school_id"])
        assert _guard(Session, ids["user_a_id"], "/dashboard") is None

        # Removing the override restores inheritance for B.
        ups.apply_user_override(
            db,
            target_user=user_b,
            permission_key="dashboard.view",
            decision=ups.DECISION_INHERIT,
            school_group_id=ids["school_id"],
            updated_by_user_id="1001",
        )
        db.commit()
        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        assert _guard(Session, ids["user_b_id"], "/dashboard") is None
    finally:
        db.close()
        engine.dispose()


def test_fresh_request_no_stale_cache_across_users():
    """A permission_cache mutation on one User ORM object must never leak to
    another user's fresh request-scoped lookup."""
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_a = db.query(models.User).get(ids["user_a_id"])
        user_b = db.query(models.User).get(ids["user_b_id"])
        # Prime A's cache first.
        keys_a = auth.get_allowed_permission_keys(db, user_a, ids["school_id"])
        assert "dashboard.view" in keys_a

        ups.apply_user_override(
            db,
            target_user=user_b,
            permission_key="dashboard.view",
            decision=ups.DECISION_DENY,
            school_group_id=ids["school_id"],
            updated_by_user_id="1001",
        )
        db.commit()

        # B's fresh lookup (distinct ORM instance/cache) must reflect the deny;
        # A's already-primed cache must not have been corrupted by B's change.
        keys_b = auth.get_allowed_permission_keys(db, user_b, ids["school_id"])
        assert "dashboard.view" not in keys_b
        assert "dashboard.view" in auth.get_allowed_permission_keys(db, user_a, ids["school_id"])
    finally:
        db.close()
        engine.dispose()


def test_role_change_recalculates_effective_permissions():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_b = db.query(models.User).get(ids["user_b_id"])
        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])

        user_b.role = auth.ROLE_LIMITED
        db.commit()
        # Limited retains dashboard.view by default, but loses an editor-only key.
        limited_keys = _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        assert "dashboard.view" in limited_keys
        assert "users.assign_role" not in limited_keys
    finally:
        db.close()
        engine.dispose()


def test_inactive_user_cannot_gain_access_via_override():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        inactive_user = db.query(models.User).get(ids["inactive_user_id"])
        # Even an explicit Allow override cannot resurrect an inactive account.
        ups.apply_user_override(
            db,
            target_user=inactive_user,
            permission_key="dashboard.view",
            decision=ups.DECISION_ALLOW,
            school_group_id=ids["school_id"],
            updated_by_user_id="1001",
        )
        db.commit()
        fresh = db.query(models.User).get(ids["inactive_user_id"])
        assert auth.get_allowed_permission_keys(db, fresh, ids["school_id"]) == set()
        denied = _guard(Session, ids["inactive_user_id"], "/dashboard")
        assert denied is not None and denied.status_code in (302, 403)
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Tenant isolation / platform-only rejection (service layer)
# ---------------------------------------------------------------------------

def test_cross_tenant_override_mutation_denied():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        other_user = db.query(models.User).get(ids["other_user_id"])
        with pytest.raises(ValueError):
            ups.apply_user_override(
                db,
                target_user=other_user,
                permission_key="dashboard.view",
                decision=ups.DECISION_DENY,
                school_group_id=ids["school_id"],  # caller's SchoolGroup, not other_user's
                updated_by_user_id="1001",
            )
    finally:
        db.close()
        engine.dispose()


def test_platform_only_override_denied_service_layer():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_a = db.query(models.User).get(ids["user_a_id"])
        platform_key = next(iter(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS))
        with pytest.raises(ValueError):
            ups.apply_user_override(
                db,
                target_user=user_a,
                permission_key=platform_key,
                decision=ups.DECISION_ALLOW,
                school_group_id=ids["school_id"],
                updated_by_user_id="1001",
            )
    finally:
        db.close()
        engine.dispose()


def test_nonassignable_override_decisions_rejected_but_inherit_cleans_old_row():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        target = db.get(models.User, ids["user_b_id"])
        key = "students.view_all_branches"  # Administrator-only, not Editor-assignable.
        ups.apply_user_override(
            db, target_user=target, permission_key=key,
            decision=ups.DECISION_DENY, school_group_id=ids["school_id"],
        )
        db.commit()
        target.role = auth.ROLE_EDITOR
        db.commit()

        for decision in (ups.DECISION_ALLOW, ups.DECISION_DENY):
            with pytest.raises(ValueError, match="cannot be overridden"):
                ups.apply_user_override(
                    db, target_user=target, permission_key=key,
                    decision=decision, school_group_id=ids["school_id"],
                )
        assert db.query(models.UserPermissionOverride).filter_by(
            user_id=target.id, permission_key=key,
        ).count() == 1

        ups.apply_user_override(
            db, target_user=target, permission_key=key,
            decision=ups.DECISION_INHERIT, school_group_id=ids["school_id"],
        )
        db.commit()
        assert db.query(models.UserPermissionOverride).filter_by(
            user_id=target.id, permission_key=key,
        ).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_read_only_position_uses_effective_limited_role_for_override_write():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        target = db.get(models.User, ids["user_b_id"])
        target.position = auth.POSITION_MANAGEMENT
        db.commit()
        with pytest.raises(ValueError, match="cannot be overridden"):
            ups.apply_user_override(
                db, target_user=target, permission_key="subjects.edit",
                decision=ups.DECISION_DENY, school_group_id=ids["school_id"],
            )
        assert db.query(models.UserPermissionOverride).filter_by(
            user_id=target.id, permission_key="subjects.edit",
        ).count() == 0
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Allow-over-Deny architecture: Allow must NOT exceed the role-resolved set
# ---------------------------------------------------------------------------

def test_user_allow_override_cannot_exceed_role_level_deny():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        # Revoke dashboard.view at the role/tenant level for Administrator.
        defaults = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults - {"dashboard.view"},
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])

        # An explicit per-user Allow override must not resurrect it: no prior
        # architecture approval exists for Allow-over-Deny (see
        # user_permission_service.apply_overrides_to_keys docstring).
        user_b = db.query(models.User).get(ids["user_b_id"])
        ups.apply_user_override(
            db,
            target_user=user_b,
            permission_key="dashboard.view",
            decision=ups.DECISION_ALLOW,
            school_group_id=ids["school_id"],
            updated_by_user_id="1001",
        )
        db.commit()
        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        denied = _guard(Session, ids["user_b_id"], "/dashboard")
        assert denied is not None and denied.status_code == 403
    finally:
        db.close()
        engine.dispose()


def test_role_level_revoke_removes_access_even_with_stale_allow_override():
    """Regression for the reported symptom: revoking a role permission must
    actually remove access even if a per-user Allow override row exists."""
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_b = db.query(models.User).get(ids["user_b_id"])
        ups.apply_user_override(
            db,
            target_user=user_b,
            permission_key="dashboard.view",
            decision=ups.DECISION_ALLOW,
            school_group_id=ids["school_id"],
            updated_by_user_id="1001",
        )
        db.commit()
        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])

        defaults = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults - {"dashboard.view"},
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Drift / invariant tests
# ---------------------------------------------------------------------------

def test_build_user_permission_payload_keys_all_registered():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_a = db.query(models.User).get(ids["user_a_id"])
        payload = ups.build_user_permission_payload(
            db, target_user=user_a, normalized_role=ADMIN, school_group_id=ids["school_id"],
        )
        registered = set(permission_registry.PERMISSION_LABELS)
        seen = set()
        for group in payload["groups"]:
            for perm in group["permissions"]:
                seen.add(perm["key"])
        assert seen <= registered
        assert seen == registered
    finally:
        db.close()
        engine.dispose()


def test_platform_only_keys_cannot_be_persisted_as_user_overrides():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_a = db.query(models.User).get(ids["user_a_id"])
        for key in permission_registry.PLATFORM_ONLY_PERMISSION_KEYS:
            with pytest.raises(ValueError):
                ups.apply_user_override(
                    db,
                    target_user=user_a,
                    permission_key=key,
                    decision=ups.DECISION_ALLOW,
                    school_group_id=ids["school_id"],
                    updated_by_user_id="1001",
                )
    finally:
        db.close()
        engine.dispose()


def test_duplicate_user_override_rows_cannot_exist_at_db_level():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        now_kwargs = dict(
            school_group_id=ids["school_id"],
            user_id=ids["user_a_id"],
            permission_key="dashboard.view",
            is_allowed=False,
            updated_by_user_id="1001",
        )
        db.add(models.UserPermissionOverride(**now_kwargs))
        db.commit()
        db.add(models.UserPermissionOverride(**now_kwargs))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
        engine.dispose()


def test_apply_user_override_updates_in_place_not_duplicate():
    engine, Session = _make_db()
    ids = _seed_two_admins(Session)
    db = Session()
    try:
        user_a = db.query(models.User).get(ids["user_a_id"])
        for decision in (ups.DECISION_DENY, ups.DECISION_ALLOW, ups.DECISION_DENY):
            ups.apply_user_override(
                db,
                target_user=user_a,
                permission_key="dashboard.view",
                decision=decision,
                school_group_id=ids["school_id"],
                updated_by_user_id="1001",
            )
            db.commit()
        rows = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_a_id"],
            models.UserPermissionOverride.permission_key == "dashboard.view",
        ).all()
        assert len(rows) == 1
        assert rows[0].is_allowed is False
    finally:
        db.close()
        engine.dispose()
