import os

os.environ["TIS_SESSION_SECRET"] = "permission-qualification-test-secret-long-enough"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import authorization
import main
import models
import permission_registry
import role_permission_service
import ui_shell
from routers import students_ui

ADMIN = auth.ROLE_ADMINISTRATOR


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def _seed(Session):
    db = Session()
    try:
        school = models.SchoolGroup(name="School A", status=True)
        db.add(school)
        db.flush()
        branch = models.Branch(name="Main", school_group_id=school.id, status=True)
        db.add(branch)
        db.flush()
        year = models.AcademicYear(school_group_id=school.id, year_name="2026-2027", is_active=True)
        db.add(year)
        db.flush()
        user = models.User(
            user_id="1001", username="admin", first_name="Admin", last_name="User",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return school.id, user.id
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
    """Run the real middleware route guard against a fresh session (next request)."""
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
# Phase 12 — coverage / architectural-consistency invariants
# ---------------------------------------------------------------------------

def test_all_route_guard_keys_are_registered():
    registered = set(permission_registry.PERMISSION_LABELS)
    missing = set()
    for rule in authorization.PROTECTED_ROUTE_RULES:
        missing.update(set(rule.permission_keys) - registered)
    for rule in authorization.ENTITLEMENT_ROUTE_RULES:
        missing.add(rule.permission_key)
    missing -= registered
    assert not missing, f"route guard keys not in registry: {sorted(missing)}"


def test_no_duplicate_permission_keys():
    labels = permission_registry.PERMISSION_LABELS
    assert len(labels) == len(permission_registry.ALL_PERMISSION_KEYS)
    assert all(labels[key] for key in labels), "empty permission label(s) present"


def test_platform_only_keys_are_never_assignable():
    platform_only = permission_registry.PLATFORM_ONLY_PERMISSION_KEYS
    for role in permission_registry.MANAGED_ROLES:
        constrained = permission_registry.constrain_role_permissions(
            role, permission_registry.ALL_PERMISSION_KEYS
        )
        assert not (constrained & platform_only), f"{role} retained platform-only keys"
        payload = permission_registry.build_role_permission_payload(role)
        for group in payload["groups"]:
            for perm in group["permissions"]:
                if perm["platform_only"]:
                    assert perm["assignable"] is False, perm["key"]


def test_role_defaults_contain_only_valid_registered_keys():
    registered = set(permission_registry.PERMISSION_LABELS)
    for role, keys in permission_registry.DEFAULT_ROLE_PERMISSIONS.items():
        assert keys <= registered, f"{role} default contains unregistered keys: {sorted(keys - registered)}"
        assert not (keys & permission_registry.PLATFORM_ONLY_PERMISSION_KEYS)


# ---------------------------------------------------------------------------
# Phase 11 — real route-guard enable / disable / re-enable
# ---------------------------------------------------------------------------

def test_dashboard_route_guard_toggle_roundtrip():
    engine, Session = _make_db()
    school_id, user_id = _seed(Session)
    db = Session()
    try:
        defaults = role_permission_service.get_allowed_permission_keys(db, ADMIN, school_id)
        assert "dashboard.view" in defaults
        assert _guard(Session, user_id, "/dashboard") is None

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults - {"dashboard.view"},
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        denied = _guard(Session, user_id, "/dashboard")
        assert denied is not None and denied.status_code == 403

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults,
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        assert _guard(Session, user_id, "/dashboard") is None
    finally:
        db.close()
        engine.dispose()


def test_subjects_route_guard_toggle_roundtrip():
    engine, Session = _make_db()
    school_id, user_id = _seed(Session)
    db = Session()
    try:
        defaults = role_permission_service.get_allowed_permission_keys(db, ADMIN, school_id)
        assert "subjects.view" in defaults
        assert _guard(Session, user_id, "/subjects/") is None

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults - {"subjects.view"},
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        denied = _guard(Session, user_id, "/subjects/")
        assert denied is not None and denied.status_code == 403

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults,
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        assert _guard(Session, user_id, "/subjects/") is None
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Phase 7 — no stale permission cache across requests
# ---------------------------------------------------------------------------

def test_permission_change_reflects_on_next_fresh_request():
    engine, Session = _make_db()
    school_id, user_id = _seed(Session)
    db = Session()
    try:
        defaults = role_permission_service.get_allowed_permission_keys(db, ADMIN, school_id)
        assert "teachers.view" in defaults

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults - {"teachers.view"},
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        assert "teachers.view" not in _allowed_after(Session, user_id, school_id)

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=defaults,
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        assert "teachers.view" in _allowed_after(Session, user_id, school_id)
    finally:
        db.close()
        engine.dispose()


VIEW_CASES = (
    ("dashboard.view", "/dashboard", "/dashboard"),
    ("subjects.view", "/subjects/", "/subjects/"),
    ("students.view", "/students/", "/students/"),
    ("teachers.view", "/teachers/", "/teachers/"),
    ("planning.view", "/planning/", "/planning/"),
    ("timetable.view", "/timetable/", "/timetable/"),
    ("calendar.view", "/academic-calendar/", "/academic-calendar/"),
    ("observations.view", "/observations/", "/observations/"),
    ("users.view", "/users", None),
    ("configuration.view", "/system-configuration", "/system-configuration"),
)

CONFIGURATION_LANDING_KEYS = {
    "configuration.view", "schools.view", "branches.view",
    "academic_years.view", "branding.view", "configuration.manage_permissions",
    "configuration.manage_degrees", "configuration.manage_specializations",
    "timetable.manage_settings", "timetable.manage_teacher_rules", "timetable.manage_blocks",
    "calendar.manage_event_types",
}


def _fresh_view_state(Session, user_id, school_id, key, path, nav_href):
    """Resolve each layer on a new ORM user, as on a new request."""
    read = Session()
    try:
        user = read.get(models.User, user_id)
        allowed = auth.get_allowed_permission_keys(read, user, school_id)
        assert auth.has_permission(read, user, key, school_group_id=school_id) == (key in allowed)

        request = _request(path)
        if key == "students.view":
            # Students HTML is protected by its router-local canonical guard.
            _, _, denied = students_ui._authorize(request, read, user, key)
        else:
            denied = authorization.enforce_route_permission(request, read, current_user=user)

        can = lambda candidate: candidate in allowed
        nav_items = ui_shell._build_nav_items(
            current_path=path, can=can,
            can_any=lambda *candidates: any(can(candidate) for candidate in candidates),
        )
        nav_hrefs = {item["href"] for item in nav_items}
        nav_hrefs.update(
            child["href"] for item in nav_items for child in item.get("children", ())
        )
        if nav_href is not None:
            if key == "configuration.view":
                # Configuration nav has an any-of gate over several independent keys.
                assert (nav_href in nav_hrefs) == bool(
                    allowed & CONFIGURATION_LANDING_KEYS
                )
            else:
                assert (nav_href in nav_hrefs) == (key in allowed)
        else:
            # Users is a System Configuration card, not a top-level sidebar item.
            assert ("/users" in {item["href"] for item in main._get_configuration_modules("users", read, user)}) == (key in allowed)
        return key in allowed, denied
    finally:
        read.close()


@pytest.mark.parametrize("key,path,nav_href", VIEW_CASES, ids=[case[0] for case in VIEW_CASES])
def test_role_view_permission_on_off_on_matches_resolver_route_and_navigation(key, path, nav_href):
    engine, Session = _make_db()
    school_id, user_id = _seed(Session)
    db = Session()
    try:
        baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, school_id)
        assert key in baseline
        enabled, denied = _fresh_view_state(Session, user_id, school_id, key, path, nav_href)
        assert enabled and denied is None

        off_keys = CONFIGURATION_LANDING_KEYS if key == "configuration.view" else {key}
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline - off_keys,
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        deny_row = db.query(models.RolePermission).filter_by(
            school_group_id=school_id, role=ADMIN, permission_key=key,
        ).one()
        assert deny_row.is_allowed is False
        enabled, denied = _fresh_view_state(Session, user_id, school_id, key, path, nav_href)
        assert not enabled and denied is not None and denied.status_code == 403

        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys=baseline,
            school_group_id=school_id, updated_by_user_id="1001",
        )
        db.commit()
        enabled, denied = _fresh_view_state(Session, user_id, school_id, key, path, nav_href)
        assert enabled and denied is None
    finally:
        db.close()
        engine.dispose()
