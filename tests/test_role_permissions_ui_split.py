"""Phase 1 regression coverage for the Role Packages / School Overrides split.

Covers the corrective structural change to
`/system-configuration/role-permissions`: the old single combined editor
("Permission Scope: Global defaults / Selected school") is replaced by two
explicit modes (`mode=packages`, `mode=overrides`) on the same route, reusing
`role_permission_service.py` for both. See docs/PROJECT_STATE.md and
docs/engineering/PERMISSION_CLOSURE_REVIEW.md for the incident this closes
(Al-Andalus Administrator subjects.view: built-in=Allow, global override=none,
tenant override=Deny, effective=Deny, while the old combined UI made "Global
defaults" and a specific tenant visually ambiguous).
"""

import os

os.environ["TIS_SESSION_SECRET"] = "role-permissions-ui-split-test-secret-long-enough"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import main
import models
import permission_registry
import role_permission_service

ADMIN = auth.ROLE_ADMINISTRATOR


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


def _tenant_admin(db, school, branch, *, user_id="1001"):
    year = _year(db, school)
    user = models.User(
        user_id=user_id,
        username=user_id,
        first_name="Tenant",
        last_name="Admin",
        user_type=auth.USER_TYPE_TENANT,
        role=ADMIN,
        position="Principal",
        password=auth.get_password_hash("password123"),
        school_group_id=school.id,
        branch_id=branch.id,
        academic_year_id=year.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _platform_owner(db, *, user_id="9001"):
    user = models.User(
        user_id=user_id,
        username=f"owner{user_id}",
        first_name="Platform",
        last_name="Owner",
        user_type=auth.USER_TYPE_PLATFORM,
        platform_role=auth.PLATFORM_ROLE_OWNER,
        platform_owner_kind=auth.PLATFORM_OWNER_PRIMARY,
        access_scope=auth.ACCESS_SCOPE_GLOBAL,
        role=None,
        position=None,
        school_group_id=None,
        branch_id=None,
        academic_year_id=None,
        password=auth.get_password_hash("password123"),
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _request(path, user, method="GET", query=""):
    headers = [(b"host", b"testserver")]
    token = auth.create_session_token(user)
    cookie_parts = [f"{auth.SESSION_COOKIE_KEY}={token}"]
    if getattr(user, "branch_id", None):
        cookie_parts.append(f"branch_id={user.branch_id}")
    headers.append((b"cookie", "; ".join(cookie_parts).encode("utf-8")))
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


def _item(payload, key):
    for group in payload["groups"]:
        for permission in group["permissions"]:
            if permission["key"] == key:
                return permission
    return None


# ---------------------------------------------------------------------------
# A. Role Packages — no SchoolGroup/tenant concept anywhere
# ---------------------------------------------------------------------------

def test_role_packages_mode_context_has_no_school_group_concept():
    engine, db = _make_db()
    try:
        owner = _platform_owner(db)
        req = _request("/system-configuration/role-permissions", owner, query="mode=packages&role=Administrator")
        context = main._build_role_permissions_context(req, db, owner)

        assert context["role_permissions_mode"] == "packages"
        assert context["selected_permission_school_group"] is None
        assert context["selected_permission_school_group_id"] is None
        assert "role_permission_school_groups" not in context
    finally:
        db.close()
        engine.dispose()


def test_role_packages_template_renders_with_no_school_selector_or_tenant_name():
    engine, db = _make_db()
    try:
        school = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        req = _request("/system-configuration/role-permissions", owner, query="mode=packages&role=Administrator")
        resp = main.system_configuration_role_permissions(req, db)
        body = resp.body.decode("utf-8")

        assert "Al-Andalus" not in body
        assert "Permission Scope" not in body
        assert 'id="school_group_id"' not in body
        assert "Selected school" not in body
        assert "Role Packages" in body
    finally:
        db.close()
        engine.dispose()


def test_role_packages_administrator_allow_and_deny_persist_for_platform_owner():
    engine, db = _make_db()
    try:
        owner = _platform_owner(db)
        key = "users.assign_role"
        before = role_permission_service.get_allowed_permission_keys(db, ADMIN, None)
        assert key in before

        req = _request("/system-configuration/role-permissions", owner)
        main.update_role_permissions(
            req, role=ADMIN, mode="packages", school_group_id=None,
            permission_keys=sorted(before - {key}), db=db,
        )
        assert key not in role_permission_service.get_allowed_permission_keys(db, ADMIN, None)

        main.update_role_permissions(
            req, role=ADMIN, mode="packages", school_group_id=None,
            permission_keys=sorted(before), db=db,
        )
        assert key in role_permission_service.get_allowed_permission_keys(db, ADMIN, None)
    finally:
        db.close()
        engine.dispose()


def test_role_packages_platform_only_permissions_remain_locked():
    engine, db = _make_db()
    try:
        owner = _platform_owner(db)
        req = _request("/system-configuration/role-permissions", owner, query="mode=packages&role=Administrator")
        context = main._build_role_permissions_context(req, db, owner)
        payload = context["role_permission_payload"]
        item = _item(payload, "system_owner.manage_ownership")
        assert item["platform_only"] is True
        assert item["assignable"] is False
        assert item["allowed"] is False
    finally:
        db.close()
        engine.dispose()


def test_non_platform_actor_cannot_edit_role_packages():
    engine, db = _make_db()
    try:
        school = _school(db)
        admin = _tenant_admin(db, school, _branch(db, school))
        key = "users.assign_role"
        before = role_permission_service.get_allowed_permission_keys(db, ADMIN, None)

        req = _request("/system-configuration/role-permissions", admin)
        resp = main.update_role_permissions(
            req, role=ADMIN, mode="packages", school_group_id=None,
            permission_keys=sorted(before - {key}), db=db,
        )
        assert getattr(resp, "status_code", None) == 302
        assert getattr(resp, "headers", {}).get("location") == "/dashboard"
        assert role_permission_service.get_allowed_permission_keys(db, ADMIN, None) == before

        context = main._build_role_permissions_context(
            _request("/system-configuration/role-permissions", admin, query="mode=packages"), db, admin,
        )
        assert context["can_edit_selected_role_permissions"] is False
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# B/E. School Overrides — Al-Andalus-style scenario, comparison payload
# ---------------------------------------------------------------------------

def test_school_overrides_al_andalus_style_case_shows_standard_override_effective():
    """Constructed fixture proving the real production incident is now legible:
    Administrator -> subjects.view standard Allow, this school's override Deny,
    effective Deny. No production row is read or touched - this is a fixture."""
    engine, db = _make_db()
    try:
        al_andalus = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        key = "subjects.view"

        assert key in role_permission_service.get_allowed_permission_keys(db, ADMIN, None)  # built-in Allow

        db.add(models.RolePermission(
            school_group_id=al_andalus.id,
            role=ADMIN,
            permission_key=key,
            is_allowed=False,
        ))
        db.commit()

        req = _request(
            "/system-configuration/role-permissions", owner,
            query=f"mode=overrides&role=Administrator&school_group_id={al_andalus.id}",
        )
        context = main._build_role_permissions_context(req, db, owner)
        assert context["role_permissions_mode"] == "overrides"
        item = _item(context["role_permission_payload"], key)

        assert item["standard_allowed"] is True
        assert item["has_override"] is True
        assert item["override_allowed"] is False
        assert item["effective_allowed"] is False
        assert item["allowed"] is False
    finally:
        db.close()
        engine.dispose()


def test_school_overrides_no_local_override_shows_using_standard():
    engine, db = _make_db()
    try:
        school = _school(db, "North Campus")
        owner = _platform_owner(db)
        key = "subjects.view"

        req = _request(
            "/system-configuration/role-permissions", owner,
            query=f"mode=overrides&role=Administrator&school_group_id={school.id}",
        )
        context = main._build_role_permissions_context(req, db, owner)
        item = _item(context["role_permission_payload"], key)

        assert item["has_override"] is False
        assert item["is_using_standard"] is True
        assert item["standard_allowed"] == item["effective_allowed"]
    finally:
        db.close()
        engine.dispose()


def test_school_overrides_get_creates_no_override_row():
    """Read-only GET must never create a tenant RolePermission row."""
    engine, db = _make_db()
    try:
        school = _school(db)
        owner = _platform_owner(db)
        req = _request(
            "/system-configuration/role-permissions", owner,
            query=f"mode=overrides&role=Administrator&school_group_id={school.id}",
        )
        before_count = db.query(models.RolePermission).filter(
            models.RolePermission.school_group_id == school.id,
        ).count()
        assert before_count == 0

        main._build_role_permissions_context(req, db, owner)
        main.system_configuration_role_permissions(req, db)

        after_count = db.query(models.RolePermission).filter(
            models.RolePermission.school_group_id == school.id,
        ).count()
        assert after_count == 0
    finally:
        db.close()
        engine.dispose()


def test_school_overrides_tenant_a_and_tenant_b_isolated():
    engine, db = _make_db()
    try:
        school_a = _school(db, "School A")
        school_b = _school(db, "School B")
        owner = _platform_owner(db)
        key = "users.assign_role"
        before = role_permission_service.get_allowed_permission_keys(db, ADMIN, None)

        req = _request("/system-configuration/role-permissions", owner)
        main.update_role_permissions(
            req, role=ADMIN, mode="overrides", school_group_id=school_a.id,
            permission_keys=sorted(before - {key}), db=db,
        )

        assert key not in role_permission_service.get_allowed_permission_keys(db, ADMIN, school_a.id)
        assert key in role_permission_service.get_allowed_permission_keys(db, ADMIN, school_b.id)
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# C. Platform Owner context preserved; management target is not actor context
# ---------------------------------------------------------------------------

def test_platform_owner_selecting_school_for_management_does_not_mutate_identity():
    engine, db = _make_db()
    try:
        al_andalus = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        assert owner.school_group_id is None
        assert auth.get_user_school_group_id(db, owner) is None

        req = _request(
            "/system-configuration/role-permissions", owner,
            query=f"mode=overrides&role=Administrator&school_group_id={al_andalus.id}",
        )
        context = main._build_role_permissions_context(req, db, owner)

        # Management target reflects the selection...
        assert context["selected_permission_school_group_id"] == al_andalus.id
        # ...but the Platform Owner's own identity/scope is untouched.
        assert owner.school_group_id is None
        assert owner.branch_id is None
        assert owner.academic_year_id is None
        assert auth.get_user_school_group_id(db, owner) is None
        assert getattr(owner, "scope_school_group_id", None) is None
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# H. Tenant actor authorization boundaries on the refactored routes
# ---------------------------------------------------------------------------

def test_tenant_actor_locked_to_own_school_even_with_foreign_query_param():
    engine, db = _make_db()
    try:
        own_school = _school(db, "Own School")
        other_school = _school(db, "Other School")
        admin = _tenant_admin(db, own_school, _branch(db, own_school))

        req = _request(
            "/system-configuration/role-permissions", admin,
            query=f"mode=overrides&role=Administrator&school_group_id={other_school.id}",
        )
        context = main._build_role_permissions_context(req, db, admin)

        assert context["selected_permission_school_group_id"] == own_school.id
        assert context["role_permission_school_groups"] == [context["selected_permission_school_group"]]
    finally:
        db.close()
        engine.dispose()


def test_tenant_actor_cannot_write_another_tenants_school_override():
    engine, db = _make_db()
    try:
        own_school = _school(db, "Own School")
        other_school = _school(db, "Other School")
        admin = _tenant_admin(db, own_school, _branch(db, own_school))
        before_other = role_permission_service.get_allowed_permission_keys(db, ADMIN, other_school.id)

        req = _request("/system-configuration/role-permissions", admin)
        resp = main.update_role_permissions(
            req, role=ADMIN, mode="overrides", school_group_id=other_school.id,
            permission_keys=[], db=db,
        )
        assert getattr(resp, "status_code", None) == 302
        assert getattr(resp, "headers", {}).get("location") == "/dashboard"
        assert role_permission_service.get_allowed_permission_keys(db, ADMIN, other_school.id) == before_other
    finally:
        db.close()
        engine.dispose()


def test_school_overrides_template_renders_management_target_not_actor_context():
    engine, db = _make_db()
    try:
        al_andalus = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        req = _request(
            "/system-configuration/role-permissions", owner,
            query=f"mode=overrides&role=Administrator&school_group_id={al_andalus.id}",
        )
        resp = main.system_configuration_role_permissions(req, db)
        body = resp.body.decode("utf-8")

        assert "Managing School" in body
        assert "Al-Andalus" in body
        assert "management target" in body.lower()
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Owner-review pass: explicit school selection, override legibility, ARIA
# ---------------------------------------------------------------------------

def _render_overrides(db, owner, school_id=None):
    query = "mode=overrides&role=Administrator"
    if school_id is not None:
        query += f"&school_group_id={school_id}"
    req = _request("/system-configuration/role-permissions", owner, query=query)
    return main.system_configuration_role_permissions(req, db).body.decode("utf-8")


def test_platform_owner_school_overrides_has_no_preselected_school():
    engine, db = _make_db()
    try:
        _school(db, "Al-Andalus")
        _school(db, "North Campus")
        owner = _platform_owner(db)
        req = _request(
            "/system-configuration/role-permissions", owner, query="mode=overrides&role=Administrator",
        )
        context = main._build_role_permissions_context(req, db, owner)

        assert context["selected_permission_school_group_id"] is None
        assert context["selected_permission_school_group"] is None
        assert context["can_edit_selected_role_permissions"] is False

        body = _render_overrides(db, owner)
        assert "Select a school..." in body
        assert "No school is pre-selected" in body
        assert 'id="ovr-' not in body
        assert "Save School Overrides" not in body
        assert 'name="school_group_id" value=' not in body
    finally:
        db.close()
        engine.dispose()


def test_school_override_group_with_override_opens_and_reports_count():
    engine, db = _make_db()
    try:
        school = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        db.add(models.RolePermission(
            school_group_id=school.id, role=ADMIN, permission_key="subjects.view",
            is_allowed=False, updated_by_user_id="seed",
        ))
        db.flush()

        body = _render_overrides(db, owner, school.id)

        assert body.count('<details class="permission-group" open>') == 1
        assert "1 School override for this role" in body
        assert "School Override: Deny" in body
        assert "Standard Role Package: Allow / Effective: Deny" in body
    finally:
        db.close()
        engine.dispose()


def test_school_override_without_rows_says_using_standard_and_opens_nothing():
    engine, db = _make_db()
    try:
        school = _school(db, "North Campus")
        owner = _platform_owner(db)
        body = _render_overrides(db, owner, school.id)

        assert "No School-specific override. Using Standard Role Package." in body
        assert '<details class="permission-group" open' not in body
    finally:
        db.close()
        engine.dispose()


def test_mode_navigation_uses_aria_current_and_no_misleading_aria():
    engine, db = _make_db()
    try:
        school = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        packages = main.system_configuration_role_permissions(
            _request("/system-configuration/role-permissions", owner, query="mode=packages&role=Administrator"), db,
        ).body.decode("utf-8")
        overrides = _render_overrides(db, owner, school.id)

        for body in (packages, overrides):
            assert "aria-expanded" not in body
            assert 'role="tab' not in body
            assert 'aria-selected' not in body
            assert 'aria-current="page"' in body
    finally:
        db.close()
        engine.dispose()


def test_reset_button_is_not_nested_inside_a_label():
    import re

    engine, db = _make_db()
    try:
        school = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        db.add(models.RolePermission(
            school_group_id=school.id, role=ADMIN, permission_key="subjects.view",
            is_allowed=False, updated_by_user_id="seed",
        ))
        db.flush()

        body = _render_overrides(db, owner, school.id)

        assert "data-reset-override" in body
        assert re.search(r"<label[^>]*>(?:(?!</label>).)*data-reset-override", body, re.S) is None
        assert 'for="ovr-subjects.view"' in body
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Sparse-override rule: bulk controls belong to Role Packages only
# ---------------------------------------------------------------------------

def test_role_packages_keeps_select_all_and_clear_all():
    engine, db = _make_db()
    try:
        owner = _platform_owner(db)
        body = main.system_configuration_role_permissions(
            _request("/system-configuration/role-permissions", owner, query="mode=packages&role=Administrator"), db,
        ).body.decode("utf-8")

        assert "data-permission-select-all" in body
        assert "data-permission-clear-all" in body
        assert ">Select All<" in body
        assert ">Clear All<" in body
    finally:
        db.close()
        engine.dispose()


def test_school_overrides_has_no_select_all_or_clear_all_but_keeps_reset():
    import re

    engine, db = _make_db()
    try:
        school = _school(db, "Al-Andalus")
        owner = _platform_owner(db)
        db.add(models.RolePermission(
            school_group_id=school.id, role=ADMIN, permission_key="subjects.view",
            is_allowed=False, updated_by_user_id="seed",
        ))
        db.flush()

        body = _render_overrides(db, owner, school.id)

        assert "<button" in body
        assert not re.search(r"<button[^>]*data-permission-select-all", body)
        assert not re.search(r"<button[^>]*data-permission-clear-all", body)
        assert ">Select All<" not in body
        assert ">Clear All<" not in body
        assert "Save School Overrides" in body
        assert "data-reset-override" in body
        assert 'data-target="ovr-subjects.view"' in body
        assert 'data-standard-allowed="true"' in body
    finally:
        db.close()
        engine.dispose()


def test_per_permission_reset_persists_as_row_delete_and_stays_sparse():
    engine, db = _make_db()
    try:
        school = _school(db, "Al-Andalus")
        db.add(models.RolePermission(
            school_group_id=school.id, role=ADMIN, permission_key="subjects.view",
            is_allowed=False, updated_by_user_id="seed",
        ))
        db.flush()
        standard = role_permission_service.get_allowed_permission_keys(db, ADMIN, None)

        # What the Reset button does client-side: subjects.view back to the standard value.
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=set(standard), school_group_id=school.id, updated_by_user_id="owner",
        )
        db.flush()

        assert role_permission_service.get_role_permission_rows(db, ADMIN, school.id) == []
        assert "subjects.view" in role_permission_service.get_allowed_permission_keys(db, ADMIN, school.id)
    finally:
        db.close()
        engine.dispose()
