"""Regression coverage for the live Owner-reproduced permission inconsistency:

Role Permissions showed Administrator -> Global defaults -> Subjects 8/8
(including subjects.view), but a real tenant Administrator had Subjects
hidden from the sidebar while the Dashboard's Subjects tab/workspace
remained fully visible for that exact same current user.

Root cause: `templates/dashboard.html` rendered its Subjects/Teachers/Planning
tab buttons and panels unconditionally, never checking the already-available
canonical `can("subjects.view")` / `can("teachers.view")` / `can("planning.view")`
helper that `build_shell_context` supplies from `auth.get_allowed_permission_keys`
(the same canonical resolver the sidebar and direct route guard already used).
The Reports tab was the only one already gated (`can("dashboard.view_reports")`).

This suite proves the Owner's exact cases (A-F) and, per task instruction,
uses a *second* module (`teachers.view`) as a sentinel proving the fix is a
generic template-gating fix and not a Subjects-only special case.

Every case checks the SAME three surfaces for the SAME current user and
the SAME final effective permission:
  - sidebar navigation (`ui_shell._build_nav_items`)
  - Dashboard tab/panel markup (`GET /dashboard`, rendered via `main.dashboard`)
  - direct route guard (`authorization.enforce_route_permission`)
"""
import os

os.environ["TIS_SESSION_SECRET"] = "dashboard-sidebar-permission-consistency-secret-long-enough"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import authorization
import main
import models
import role_permission_service
import ui_shell
import user_permission_service as ups

ADMIN = auth.ROLE_ADMINISTRATOR

# (permission_key, route_path, nav_href, dashboard_panel_id, dashboard_tab_data_panel)
SENTINELS = (
    ("subjects.view", "/subjects/", "/subjects/", "panel-subjects", "subjects"),
    ("teachers.view", "/teachers/", "/teachers/", "panel-teachers", "teachers"),
)


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def _seed(Session):
    db = Session()
    try:
        school = models.SchoolGroup(name="Al-Andalus Schools", status=True)
        db.add(school)
        db.flush()
        other_school = models.SchoolGroup(name="Other Tenant Schools", status=True)
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
        admin_user = models.User(
            user_id="1001", username="al_andalus_admin", first_name="Tenant", last_name="Administrator",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id, is_active=True,
        )
        other_admin_user = models.User(
            user_id="2001", username="other_tenant_admin", first_name="Other", last_name="Administrator",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=other_school.id, branch_id=other_branch.id, academic_year_id=other_year.id,
            is_active=True,
        )
        db.add_all([admin_user, other_admin_user])
        db.commit()
        return {
            "school_id": school.id,
            "branch_id": branch.id,
            "other_school_id": other_school.id,
            "other_branch_id": other_branch.id,
            "admin_user_id": admin_user.id,
            "other_admin_user_id": other_admin_user.id,
        }
    finally:
        db.close()


def _request(path, user):
    token = auth.create_session_token(user)
    headers = [
        (b"host", b"testserver"),
        (
            b"cookie",
            f"{auth.SESSION_COOKIE_KEY}={token}; branch_id={user.branch_id}".encode("utf-8"),
        ),
    ]
    scope = {
        "type": "http", "http_version": "1.1", "method": "GET", "path": path,
        "raw_path": path.encode("utf-8"), "query_string": b"",
        "headers": headers, "scheme": "http",
        "server": ("testserver", 80), "client": ("testclient", 50000),
        "root_path": "", "app": main.app,
    }
    return Request(scope)


def _dashboard_html(db, user):
    resp = main.dashboard(_request("/dashboard", user), db)
    assert resp.status_code == 200
    return resp.body.decode("utf-8")


def _sidebar_visible(db, user, school_id, nav_href):
    allowed = auth.get_allowed_permission_keys(db, user, school_id)

    def can(key):
        return key in allowed

    def can_any(*keys):
        return any(can(key) for key in keys)

    nav_items = ui_shell._build_nav_items(current_path="/dashboard", can=can, can_any=can_any)
    hrefs = {item["href"] for item in nav_items}
    hrefs.update(child["href"] for item in nav_items for child in item.get("children", ()))
    return nav_href in hrefs


def _route_allowed(db, user, path):
    fresh = db.query(models.User).get(user.id)
    denied = authorization.enforce_route_permission(_request(path, fresh), db, current_user=fresh)
    return denied is None


def _check_all_surfaces(db, user_id, school_id, key, path, nav_href, panel_id, tab_panel, *, expected):
    fresh = db.query(models.User).get(user_id)
    allowed = auth.get_allowed_permission_keys(db, fresh, school_id)
    assert (key in allowed) == expected, f"resolver mismatch for {key}"

    sidebar_visible = _sidebar_visible(db, fresh, school_id, nav_href)
    assert sidebar_visible == expected, f"sidebar mismatch for {key}"

    html = _dashboard_html(db, fresh)
    panel_present = f'id="{panel_id}"' in html
    tab_present = f'data-panel="{tab_panel}"' in html
    assert panel_present == expected, f"dashboard panel mismatch for {key}"
    assert tab_present == expected, f"dashboard tab mismatch for {key}"

    route_allowed = _route_allowed(db, fresh, path)
    assert route_allowed == expected, f"route mismatch for {key}"


@pytest.mark.parametrize(
    "key,path,nav_href,panel_id,tab_panel",
    SENTINELS,
    ids=[case[0] for case in SENTINELS],
)
def test_case_a_global_allow_no_overrides_all_surfaces_visible(key, path, nav_href, panel_id, tab_panel):
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        assert key in baseline
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=True,
        )
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "key,path,nav_href,panel_id,tab_panel",
    SENTINELS,
    ids=[case[0] for case in SENTINELS],
)
def test_case_b_global_allow_tenant_deny_all_surfaces_hidden(key, path, nav_href, panel_id, tab_panel):
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline - {key},
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=False,
        )
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "key,path,nav_href,panel_id,tab_panel",
    SENTINELS,
    ids=[case[0] for case in SENTINELS],
)
def test_case_c_global_allow_tenant_allow_user_deny_all_surfaces_hidden(key, path, nav_href, panel_id, tab_panel):
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        # Explicit tenant-level Allow (a no-op relative to baseline, but written
        # as a real direct row to prove Allow-at-tenant does not mask a User Deny).
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline,
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        admin_user = db.query(models.User).get(ids["admin_user_id"])
        ups.apply_user_override(
            db, target_user=admin_user, permission_key=key, decision="deny",
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=False,
        )
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "key,path,nav_href,panel_id,tab_panel",
    SENTINELS,
    ids=[case[0] for case in SENTINELS],
)
def test_case_d_role_deny_then_regrant_user_inherit_all_surfaces_restored(key, path, nav_href, panel_id, tab_panel):
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline - {key},
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=False,
        )

        # Re-grant at the role level; user override stays Inherit (never set).
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline,
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=True,
        )
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "key,path,nav_href,panel_id,tab_panel",
    SENTINELS,
    ids=[case[0] for case in SENTINELS],
)
def test_case_e_role_deny_then_regrant_user_deny_remains_hidden(key, path, nav_href, panel_id, tab_panel):
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline - {key},
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        admin_user = db.query(models.User).get(ids["admin_user_id"])
        ups.apply_user_override(
            db, target_user=admin_user, permission_key=key, decision="deny",
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=False,
        )

        # Re-grant at the role level; the stored User Deny override remains and
        # must keep the key hidden (Deny-over-Allow, ADR 0040).
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline,
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=False,
        )
    finally:
        db.close()
        engine.dispose()


@pytest.mark.parametrize(
    "key,path,nav_href,panel_id,tab_panel",
    SENTINELS,
    ids=[case[0] for case in SENTINELS],
)
def test_case_f_tenant_a_deny_does_not_affect_tenant_b(key, path, nav_href, panel_id, tab_panel):
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline - {key},
            school_group_id=ids["school_id"], updated_by_user_id="1001",
        )
        db.commit()

        # Tenant A (Al-Andalus) is hidden.
        _check_all_surfaces(
            db, ids["admin_user_id"], ids["school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=False,
        )
        # Tenant B (Other Tenant) is unaffected and remains fully visible/allowed.
        other_baseline = role_permission_service.get_allowed_permission_keys(
            db, ADMIN, ids["other_school_id"]
        )
        assert key in other_baseline
        _check_all_surfaces(
            db, ids["other_admin_user_id"], ids["other_school_id"], key, path, nav_href, panel_id, tab_panel,
            expected=True,
        )
    finally:
        db.close()
        engine.dispose()
