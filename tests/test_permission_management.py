import os

os.environ["TIS_SESSION_SECRET"] = "permission-management-test-secret-that-is-long-enough"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import main
import models
import permission_registry
import role_permission_service

ADMIN = auth.ROLE_ADMINISTRATOR
EDITOR = auth.ROLE_EDITOR

P = "users.assign_role"  # default-granted, assignable for Administrator
OWNER_KEY = "system_owner.manage_ownership"
DEV_KEY = "dashboard.view_all_schools"


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    return engine, session


def _school(db, name="School A"):
    school = models.SchoolGroup(name=name, status=True)
    db.add(school)
    db.flush()
    return school


def _branch(db, school, name="Main"):
    branch = models.Branch(name=name, school_group_id=school.id, status=True)
    db.add(branch)
    db.flush()
    return branch


def _year(db, school):
    year = models.AcademicYear(school_group_id=school.id, year_name="2026-2027", is_active=True)
    db.add(year)
    db.flush()
    return year


def _user(db, school, branch, *, user_id="1001", role=ADMIN):
    year = _year(db, school)
    user = models.User(
        user_id=user_id,
        username=user_id,
        first_name="Test",
        last_name="User",
        role=role,
        position="Principal" if role == ADMIN else "Teacher",
        password=auth.get_password_hash("password123"),
        school_group_id=school.id,
        branch_id=branch.id,
        academic_year_id=year.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _request(path, user, method="GET", query=""):
    headers = [(b"host", b"testserver")]
    token = auth.create_session_token(user)
    cookie = "; ".join(
        [
            f"{auth.SESSION_COOKIE_KEY}={token}",
            f"branch_id={user.branch_id}",
        ]
    )
    headers.append((b"cookie", cookie.encode("utf-8")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query.encode("utf-8"),
        "headers": headers,
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "app": main.app,
    }
    return Request(scope)


def _allowed(db, role, school_group_id=None):
    return role_permission_service.get_allowed_permission_keys(db, role, school_group_id)


def _item(payload, key):
    for group in payload["groups"]:
        for permission in group["permissions"]:
            if permission["key"] == key:
                return permission
    return None


def _grant(db, *, role=ADMIN, keys, school_group_id, allow=True):
    for key in keys:
        db.add(
            models.RolePermission(
                school_group_id=school_group_id,
                role=role,
                permission_key=key,
                is_allowed=allow,
            )
        )
    db.commit()


def _update(db, request, *, role, keys, school_group_id=None, mode="overrides"):
    return main.update_role_permissions(
        request,
        role=role,
        mode=mode,
        school_group_id=school_group_id,
        permission_keys=sorted(keys),
        db=db,
    )


# ---------------------------------------------------------------------------
# Service / registry model
# ---------------------------------------------------------------------------

def test_owner_only_keys_are_excluded_from_tenant_role_defaults():
    assert OWNER_KEY not in permission_registry.get_default_permissions_for_role(ADMIN)
    assert "system_owner.transfer_ownership" not in permission_registry.get_default_permissions_for_role(ADMIN)
    payload = permission_registry.build_role_permission_payload(ADMIN)
    item = _item(payload, OWNER_KEY)
    assert item["platform_only"] is True
    assert item["assignable"] is False
    assert item["allowed"] is False


def test_constrain_role_permissions_strips_owner_only():
    constrained = permission_registry.constrain_role_permissions(ADMIN, {OWNER_KEY, P})
    assert OWNER_KEY not in constrained
    assert P in constrained


def test_direct_grant_and_revoke_roundtrip():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        before = _allowed(db, ADMIN, school.id)
        assert P in before  # default-granted

        _update(db, req, role=ADMIN, keys=before - {P}, school_group_id=school.id)
        assert P not in _allowed(db, ADMIN, school.id)

        _update(db, req, role=ADMIN, keys=before, school_group_id=school.id)
        assert P in _allowed(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()


def test_repeated_grant_and_revoke_are_idempotent():
    engine, db = _make_db()
    try:
        school = _school(db)
        req = _request("/system-configuration/role-permissions", _user(db, school, _branch(db, school)))
        base = _allowed(db, ADMIN, school.id)

        for _ in range(2):
            _update(db, req, role=ADMIN, keys=base - {P}, school_group_id=school.id)
        assert P not in _allowed(db, ADMIN, school.id)

        for _ in range(2):
            _update(db, req, role=ADMIN, keys=base, school_group_id=school.id)
        assert P in _allowed(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()


def test_invalid_permission_keys_are_ignored():
    engine, db = _make_db()
    try:
        school = _school(db)
        req = _request("/system-configuration/role-permissions", _user(db, school, _branch(db, school)))
        _update(db, req, role=ADMIN, keys={"totally.fake_key"}, school_group_id=school.id)
        assert "totally.fake_key" not in _allowed(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()


def test_payload_distinguishes_default_inherited_from_direct_assignment():
    engine, db = _make_db()
    try:
        school = _school(db)
        payload = role_permission_service.build_role_permission_payload(db, ADMIN, school.id)
        item = _item(payload, P)
        assert item["allowed"] is True
        assert item["direct"] is False
        assert item["inherited"] is True
        assert item["source"] == "default"
    finally:
        db.close()
        engine.dispose()


def test_revoke_default_grant_reappears_as_unchecked_on_rerender():
    """Regression: unchecking a default-granted permission must persist and
    re-render as unchecked (not 'return')."""
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        overrides_req = _request(
            "/system-configuration/role-permissions",
            user,
            query=f"mode=overrides&school_group_id={school.id}",
        )
        before = _allowed(db, ADMIN, school.id)

        _update(db, req, role=ADMIN, keys=before - {P}, school_group_id=school.id)

        payload = main._build_role_permissions_context(overrides_req, db, user)["role_permission_payload"]
        item = _item(payload, P)
        assert item["allowed"] is False
        assert item["direct"] is False
        assert item["inherited"] is False

        _update(db, req, role=ADMIN, keys=before, school_group_id=school.id)
        payload = main._build_role_permissions_context(overrides_req, db, user)["role_permission_payload"]
        item = _item(payload, P)
        assert item["allowed"] is True
        assert item["direct"] is False
        assert item["inherited"] is True
        assert item["source"] == "default"
    finally:
        db.close()
        engine.dispose()


def test_global_default_is_inherited_at_school_scope():
    engine, db = _make_db()
    try:
        school = _school(db)
        _grant(db, role=ADMIN, keys={P}, school_group_id=None, allow=True)
        payload = role_permission_service.build_role_permission_payload(db, ADMIN, school.id)
        item = _item(payload, P)
        assert item["allowed"] is True
        assert item["direct"] is False
        assert item["inherited"] is True
        assert item["source"] == "global"
    finally:
        db.close()
        engine.dispose()


def test_cross_tenant_mutation_is_denied_for_non_global_admin():
    engine, db = _make_db()
    try:
        school_a = _school(db, "School A")
        branch_a = _branch(db, school_a)
        school_b = _school(db, "School B")
        user = _user(db, school_a, branch_a)

        allowed_a_before = _allowed(db, ADMIN, school_a.id)
        allowed_b_before = _allowed(db, ADMIN, school_b.id)

        resp = _update(
            db,
            _request("/system-configuration/role-permissions", user),
            role=ADMIN,
            keys=allowed_a_before - {P},
            school_group_id=school_b.id,
        )
        assert getattr(resp, "status_code", None) == 302
        assert getattr(resp, "headers", {}).get("location") == "/dashboard"
        assert P in _allowed(db, ADMIN, school_a.id)
        assert _allowed(db, ADMIN, school_b.id) == allowed_b_before
    finally:
        db.close()
        engine.dispose()


def test_tenant_deny_does_not_leak_across_school_groups():
    engine, db = _make_db()
    try:
        school_a = _school(db, "School A")
        school_b = _school(db, "School B")
        user_a = _user(db, school_a, _branch(db, school_a), user_id="1001")
        base = _allowed(db, ADMIN, school_a.id)

        _update(db, _request("/system-configuration/role-permissions", user_a), role=ADMIN,
                keys=base - {P}, school_group_id=school_a.id)

        assert P not in _allowed(db, ADMIN, school_a.id)
        assert P in _allowed(db, ADMIN, school_b.id)
    finally:
        db.close()
        engine.dispose()


def test_unprivileged_role_cannot_manage_permissions():
    engine, db = _make_db()
    try:
        school = _school(db)
        editor = _user(db, school, _branch(db, school), user_id="2001", role=EDITOR)
        req = _request("/system-configuration/role-permissions", editor, method="POST")
        current_user, denied = main._get_role_permissions_access(req, db)
        assert current_user is None
        assert denied is not None
    finally:
        db.close()
        engine.dispose()


def test_owner_only_permission_cannot_be_granted_via_write():
    engine, db = _make_db()
    try:
        school = _school(db)
        req = _request("/system-configuration/role-permissions", _user(db, school, _branch(db, school)))
        _update(db, req, role=ADMIN, keys={OWNER_KEY}, school_group_id=school.id)
        assert OWNER_KEY not in _allowed(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()


def test_auth_and_service_resolvers_agree():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        _grant(db, role=ADMIN, keys={P}, school_group_id=school.id, allow=True)
        assert auth.get_allowed_permission_keys(db, user, school.id) == _allowed(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()


def test_invalid_role_returns_error_redirect():
    engine, db = _make_db()
    try:
        school = _school(db)
        req = _request("/system-configuration/role-permissions", _user(db, school, _branch(db, school)))
        resp = main.update_role_permissions(
            req, role="Bogus Role", mode="overrides", school_group_id=school.id,
            permission_keys=[], db=db,
        )
        assert getattr(resp, "status_code", None) == 302
        assert "error=" in getattr(resp, "headers", {}).get("location", "")
    finally:
        db.close()
        engine.dispose()


def _scope_row_map(db, role, school_group_id):
    return {
        row.permission_key: row.is_allowed
        for row in role_permission_service.get_role_permission_rows(db, role, school_group_id)
    }


def test_noop_save_keeps_inherited_allow_as_inherited():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        before = _allowed(db, ADMIN, school.id)
        assert P in before  # default-granted

        _update(db, req, role=ADMIN, keys=before, school_group_id=school.id)

        # No scope-level row created for an untouched inherited allow.
        assert role_permission_service.get_role_permission_rows(db, ADMIN, school.id) == []
        payload = role_permission_service.build_role_permission_payload(db, ADMIN, school.id)
        item = _item(payload, P)
        assert item["allowed"] is True
        assert item["direct"] is False
        assert item["inherited"] is True
    finally:
        db.close()
        engine.dispose()


def test_noop_save_does_not_create_row_for_default_denied():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        key = "users.create"
        editor_effective = _allowed(db, EDITOR, school.id)
        assert key not in editor_effective  # default-denied for Editor

        _update(db, req, role=EDITOR, keys=editor_effective, school_group_id=school.id)

        assert role_permission_service.get_role_permission_rows(db, EDITOR, school.id) == []
        assert key not in _allowed(db, EDITOR, school.id)
    finally:
        db.close()
        engine.dispose()


def test_inherited_allow_explicitly_revoked_creates_deny_override():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        before = _allowed(db, ADMIN, school.id)
        assert P in before

        _update(db, req, role=ADMIN, keys=before - {P}, school_group_id=school.id)

        assert P not in _allowed(db, ADMIN, school.id)
        rows = _scope_row_map(db, ADMIN, school.id)
        assert rows.get(P) is False  # explicit deny override persisted
        payload = role_permission_service.build_role_permission_payload(db, ADMIN, school.id)
        assert _item(payload, P)["source"] == "denied"
    finally:
        db.close()
        engine.dispose()


def test_inherited_deny_explicitly_granted_creates_allow_override():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        key = "users.create"
        editor_effective = _allowed(db, EDITOR, school.id)
        assert key not in editor_effective

        _update(db, req, role=EDITOR, keys=editor_effective | {key}, school_group_id=school.id)

        assert key in _allowed(db, EDITOR, school.id)
        assert _scope_row_map(db, EDITOR, school.id).get(key) is True
    finally:
        db.close()
        engine.dispose()


def test_direct_override_removed_restores_inherited_baseline():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        before = _allowed(db, ADMIN, school.id)

        _update(db, req, role=ADMIN, keys=before - {P}, school_group_id=school.id)
        assert P not in _allowed(db, ADMIN, school.id)

        _update(db, req, role=ADMIN, keys=before, school_group_id=school.id)

        assert P in _allowed(db, ADMIN, school.id)
        # The deny override was removed; no direct allow row remains.
        assert P not in _scope_row_map(db, ADMIN, school.id)
        payload = role_permission_service.build_role_permission_payload(db, ADMIN, school.id)
        item = _item(payload, P)
        assert item["inherited"] is True
        assert item["direct"] is False
    finally:
        db.close()
        engine.dispose()


def test_global_change_propagates_without_direct_override():
    engine, db = _make_db()
    try:
        school = _school(db)
        user = _user(db, school, _branch(db, school))
        req = _request("/system-configuration/role-permissions", user)
        before = _allowed(db, ADMIN, school.id)
        assert P in before

        _update(db, req, role=ADMIN, keys=before, school_group_id=school.id)
        assert role_permission_service.get_role_permission_rows(db, ADMIN, school.id) == []

        _grant(db, role=ADMIN, keys={P}, school_group_id=None, allow=False)
        assert P not in _allowed(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()


def test_existing_direct_override_remains_authoritative():
    engine, db = _make_db()
    try:
        school = _school(db)
        _grant(db, role=ADMIN, keys={P}, school_group_id=school.id, allow=True)

        _grant(db, role=ADMIN, keys={P}, school_group_id=None, allow=False)

        assert P in _allowed(db, ADMIN, school.id)  # tenant override beats global
    finally:
        db.close()
        engine.dispose()
