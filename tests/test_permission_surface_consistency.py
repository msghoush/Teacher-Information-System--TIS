"""Whole-application surface consistency: ONE canonical effective permission result.

For every nav module (plus the Talent sub-nav and Dashboard tabs) this proves the
sidebar, Dashboard surface and direct route agree with `auth.get_allowed_permission_keys`
on FRESH sessions/requests, then covers mutation families, freshness (Role Package ->
School Override -> User Exception), role change, tenant isolation and platform-only
protection. No permission cache exists between requests (each check opens a new
SQLAlchemy session and rebuilds the request/user).
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["TIS_SESSION_SECRET"] = "permission-surface-consistency-secret-long-enough"

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
import user_permission_service as ups
from routers import students as students_api
from routers import students_ui, talent_ui

_PW = auth.get_password_hash("password123")  # hashed once; bcrypt is slow

ADMIN, EDITOR, USER, LIMITED = (
    auth.ROLE_ADMINISTRATOR, auth.ROLE_EDITOR, auth.ROLE_USER, auth.ROLE_LIMITED,
)


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------
class World:
    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        models.Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        db = self.Session()
        a = models.SchoolGroup(name="School A", status=True)
        b = models.SchoolGroup(name="School B", status=True)
        db.add_all([a, b])
        db.flush()
        ba = models.Branch(name="A Main", school_group_id=a.id, status=True)
        bb = models.Branch(name="B Main", school_group_id=b.id, status=True)
        db.add_all([ba, bb])
        db.flush()
        ya = models.AcademicYear(school_group_id=a.id, year_name="2026-2027", is_active=True)
        yb = models.AcademicYear(school_group_id=b.id, year_name="2026-2027", is_active=True)
        db.add_all([ya, yb])
        db.flush()
        self.a, self.b, self.ba, self.bb, self.ya, self.yb = a.id, b.id, ba.id, bb.id, ya.id, yb.id

        def tenant(uid, role, group, branch, year):
            user = models.User(
                user_id=uid, username=f"u{uid}", first_name="T", last_name=uid, role=role,
                position="Staff", password=_PW,
                school_group_id=group, branch_id=branch, academic_year_id=year, is_active=True,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            )
            db.add(user)
            return user

        users = {
            "admin": tenant("1001", ADMIN, a.id, ba.id, ya.id),
            "editor": tenant("1002", EDITOR, a.id, ba.id, ya.id),
            "user": tenant("1003", USER, a.id, ba.id, ya.id),
            "limited": tenant("1004", LIMITED, a.id, ba.id, ya.id),
            "admin_b": tenant("2001", ADMIN, b.id, bb.id, yb.id),
        }
        owner = models.User(
            user_id="9000", username="owner", first_name="Platform", last_name="Owner",
            role=None, position="Owner", password=_PW,
            user_type=auth.USER_TYPE_PLATFORM, platform_role=auth.PLATFORM_ROLE_OWNER,
            is_active=True,
        )
        dev = models.User(
            user_id="9001", username="dev", first_name="Platform", last_name="Dev",
            role=None, position="Dev", password=_PW,
            user_type=auth.USER_TYPE_PLATFORM, platform_role=auth.PLATFORM_ROLE_DEVELOPER,
            platform_permissions_initialized=True, is_active=True,
        )
        db.add_all([owner, dev])
        db.flush()
        users["owner"], users["dev"] = owner, dev
        db.commit()
        self.ids = {name: user.id for name, user in users.items()}
        db.close()

    def close(self):
        self.engine.dispose()

    # -- fresh requests ---------------------------------------------------
    def request(self, path, user, method="GET", scope_group=None):
        cookies = [f"{auth.SESSION_COOKIE_KEY}={auth.create_session_token(user)}"]
        if user.branch_id:
            cookies.append(f"branch_id={user.branch_id}")
        if scope_group:
            cookies.append(f"school_group_id={scope_group}")
        scope = {
            "type": "http", "http_version": "1.1", "method": method, "path": path,
            "raw_path": path.encode(), "query_string": b"",
            "headers": [(b"host", b"testserver"), (b"cookie", "; ".join(cookies).encode())],
            "scheme": "http", "server": ("testserver", 80), "client": ("testclient", 50000),
            "root_path": "", "app": main.app,
        }
        return Request(scope)

    def fresh(self, who, path="/dashboard", method="GET", scope_group=None):
        db = self.Session()
        raw = db.get(models.User, self.ids[who])
        request = self.request(path, raw, method, scope_group)
        user = auth.get_current_user(request, db)
        return db, request, user

    # -- surfaces ---------------------------------------------------------
    def effective(self, who):
        db = self.Session()
        try:
            user = db.get(models.User, self.ids[who])
            return auth.get_allowed_permission_keys(db, user, user.school_group_id)
        finally:
            db.close()

    def sidebar(self, who):
        db, request, user = self.fresh(who)
        try:
            shell = ui_shell.build_shell_context(request, db, user, page_key="dashboard")["shell"]
            hrefs = {item["href"] for item in shell["nav_items"]}
            hrefs |= {c["href"] for item in shell["nav_items"] for c in item.get("children", ())}
            return hrefs
        finally:
            db.close()

    def dashboard_html(self, who):
        db, request, user = self.fresh(who)
        try:
            response = main.dashboard(request, db)
            assert response.status_code == 200
            return response.body.decode("utf-8")
        finally:
            db.close()

    def route_allowed(self, who, method, path):
        db, request, user = self.fresh(who, path, method)
        try:
            rule = authorization._find_permission_rule(path, method)
            if rule is not None:
                return authorization.enforce_route_permission(request, db, current_user=user) is None
            if path.startswith("/talent"):
                view = path.strip("/").split("/", 1)[1] if "/" in path.strip("/") else "overview"
                response = talent_ui.talent_page(request, view, db, user)
            elif path.startswith("/students"):
                response = students_ui.students_home(request, db, user)
            else:
                raise AssertionError(f"no route evaluator for {path}")
            return response.status_code != 403
        finally:
            db.close()

    # -- policy mutation --------------------------------------------------
    def school_override(self, role, remove=(), add=(), group=None):
        db = self.Session()
        group = group or self.a
        baseline = role_permission_service.get_allowed_permission_keys(db, role, None)
        current = role_permission_service.get_allowed_permission_keys(db, role, group)
        target = (current - set(remove)) | set(add)
        # apply relative to the global baseline the service diffs against
        role_permission_service.apply_role_permission_overrides(
            db, role=role, allowed_keys=target, school_group_id=group, updated_by_user_id="t",
        )
        db.commit()
        db.close()
        return baseline

    def role_package(self, role, remove=(), add=()):
        db = self.Session()
        current = role_permission_service.get_allowed_permission_keys(db, role, None)
        role_permission_service.apply_role_permission_overrides(
            db, role=role, allowed_keys=(current - set(remove)) | set(add),
            school_group_id=None, updated_by_user_id="t",
        )
        db.commit()
        db.close()

    def user_exception(self, who, key, decision):
        db = self.Session()
        target = db.get(models.User, self.ids[who])
        ups.apply_user_override(
            db, target_user=target, permission_key=key, decision=decision,
            school_group_id=target.school_group_id, updated_by_user_id="t",
        )
        db.commit()
        db.close()


@pytest.fixture()
def world():
    w = World()
    yield w
    w.close()


# ---------------------------------------------------------------------------
# STEP 4: every nav module
# ---------------------------------------------------------------------------
SYSTEM_CONFIG_KEYS = (
    "configuration.view", "schools.view", "branches.view", "academic_years.view",
    "branding.view", "configuration.manage_permissions", "configuration.manage_degrees",
    "configuration.manage_specializations", "timetable.manage_settings",
    "timetable.manage_teacher_rules", "timetable.manage_blocks", "calendar.manage_event_types",
)
TALENT_KEYS = (
    "talent_programs.view", "talent_evaluation_plans.view", "talent_assessments.view",
    "talent_review_candidates.view", "talent_learner_profiles.view", "talent_analytics.view",
)

# id, nav href, keys, mode, direct route, dashboard panel id
MODULES = (
    ("dashboard", "/dashboard", ("dashboard.view",), "all", "/dashboard", None),
    ("subjects", "/subjects/", ("subjects.view",), "all", "/subjects/", "panel-subjects"),
    ("teachers", "/teachers/", ("teachers.view",), "all", "/teachers/", "panel-teachers"),
    ("planning", "/planning/", ("planning.view",), "all", "/planning/", "panel-planning"),
    ("timetable", "/timetable/", ("timetable.view",), "all", "/timetable/", None),
    ("calendar", "/academic-calendar/", ("calendar.view",), "all", "/academic-calendar/", None),
    ("observations", "/observations/", ("observations.view",), "all", "/observations/", None),
    ("notifications", "/notifications", ("notifications.view",), "all", "/notifications", None),
    ("students", "/students/", ("students.view",), "all", "/students/", None),
    ("system_configuration", "/system-configuration", SYSTEM_CONFIG_KEYS, "any", "/system-configuration", None),
    ("talent", "/talent", TALENT_KEYS, "any", "/talent", None),
)


def _module_ids():
    return [m[0] for m in MODULES]


@pytest.mark.parametrize("module", MODULES, ids=_module_ids())
def test_module_deny_hides_sidebar_dashboard_and_denies_route(world, module):
    _mid, nav, keys, _mode, route, panel = module
    world.school_override(ADMIN, remove=keys)
    effective = world.effective("admin")
    assert not (set(keys) & effective)
    assert nav not in world.sidebar("admin")
    assert world.route_allowed("admin", "GET", route) is False
    if panel:
        assert f'id="{panel}"' not in world.dashboard_html("admin")


@pytest.mark.parametrize("module", MODULES, ids=_module_ids())
def test_module_allow_shows_sidebar_dashboard_and_allows_route(world, module):
    _mid, nav, keys, _mode, route, panel = module
    assert set(keys) <= world.effective("admin")
    assert nav in world.sidebar("admin")
    assert world.route_allowed("admin", "GET", route) is True
    if panel:
        assert f'id="{panel}"' in world.dashboard_html("admin")


@pytest.mark.parametrize("key", SYSTEM_CONFIG_KEYS)
def test_system_configuration_multikey_any_gate(world, key):
    others = tuple(k for k in SYSTEM_CONFIG_KEYS if k != key)
    world.school_override(ADMIN, remove=others)
    assert world.effective("admin") & set(SYSTEM_CONFIG_KEYS) == {key}
    assert "/system-configuration" in world.sidebar("admin")
    assert world.route_allowed("admin", "GET", "/system-configuration") is True


@pytest.mark.parametrize("key", TALENT_KEYS)
def test_talent_multikey_any_gate_and_overview(world, key):
    world.school_override(ADMIN, remove=tuple(k for k in TALENT_KEYS if k != key))
    assert "/talent" in world.sidebar("admin")
    assert world.route_allowed("admin", "GET", "/talent") is True


TALENT_SUBNAV = (
    ("talent_programs.view", "/talent/programs"),
    ("talent_assessments.view", "/talent/assessments"),
    ("talent_review_candidates.view", "/talent/reviews"),
    ("talent_analytics.view", "/talent/analytics"),
    ("students.view", "/students/"),
)


@pytest.mark.parametrize("key,href", TALENT_SUBNAV, ids=[k for k, _ in TALENT_SUBNAV])
def test_talent_subnav_matches_route_for_deny_and_allow(world, key, href):
    assert href in world.sidebar("admin")
    assert world.route_allowed("admin", "GET", href) is True
    world.school_override(ADMIN, remove=(key,))
    assert href not in world.sidebar("admin")
    assert world.route_allowed("admin", "GET", href) is False


def test_dashboard_reports_tab_gated_by_view_reports(world):
    html = world.dashboard_html("admin")
    assert 'id="panel-reports"' in html
    world.school_override(ADMIN, remove=("dashboard.view_reports",))
    assert 'id="panel-reports"' not in world.dashboard_html("admin")


def test_platform_console_and_demo_requests_are_platform_only(world):
    for who in ("admin", "editor", "user", "limited"):
        nav = world.sidebar(who)
        assert "/platform" not in nav and "/demo-requests" not in nav
        assert world.route_allowed(who, "GET", "/platform") is False
        assert world.route_allowed(who, "GET", "/demo-requests") is False
    assert "/platform" in world.sidebar("owner")
    assert world.route_allowed("owner", "GET", "/platform") is True


# ---------------------------------------------------------------------------
# STEP 5a: mutation families (crafted POST / export / bulk)
# ---------------------------------------------------------------------------
MUTATION_FAMILIES = (
    ("users create", "POST", "/users", "users.create"),
    ("users bulk delete", "POST", "/users/delete-bulk", "users.bulk_delete"),
    ("users status", "POST", "/users/status/1", "users.activate_deactivate"),
    ("subjects create", "POST", "/subjects/", "subjects.create"),
    ("subjects import", "POST", "/subjects/import", "subjects.import"),
    ("subjects export", "GET", "/subjects/export", "subjects.export"),
    ("subjects bulk delete", "POST", "/subjects/delete-bulk", "subjects.delete"),
    ("teachers create", "POST", "/teachers/", "teachers.create"),
    ("teachers bulk delete", "POST", "/teachers/delete-bulk", "teachers.bulk_delete"),
    ("teachers copy year", "POST", "/teachers/copy-from-year", "teachers.copy_year_data"),
    ("planning create", "POST", "/planning/", "planning.create_section"),
    ("planning delete", "GET", "/planning/delete/1", "planning.delete_section"),
    ("planning copy year", "POST", "/planning/copy-from-year", "planning.copy_year_data"),
    ("curriculum apply", "POST", "/planning/curriculum-adjustments/apply", "curriculum.adjust"),
    ("timetable generate", "POST", "/timetable/api/generation-runs", "timetable.generate"),
    ("timetable publish", "POST", "/timetable/api/versions/abc/publish", "timetable.publish"),
    ("timetable export", "GET", "/timetable/export.xlsx", "timetable.export"),
    ("academic year activate", "POST", "/admin/current-year", "academic_years.activate"),
    ("academic year delete", "POST", "/system-configuration/academic-years/1/delete", "academic_years.delete"),
    ("branch create", "POST", "/system-configuration/branches", "branches.create"),
    ("branch delete", "POST", "/system-configuration/branches/1/delete", "branches.delete"),
    ("notification archive", "POST", "/notifications/1/archive", "notifications.archive"),
    ("notification resolve", "POST", "/notifications/1/resolved", "notifications.resolve"),
    ("observation delete", "POST", "/observations/1/delete", "observations.delete"),
    ("observation export", "GET", "/observations/1/export/pdf", "observations.export_reports"),
    ("report export", "GET", "/reports/allocation-plan.xlsx", "dashboard.export_reports"),
    ("hiring plan save", "POST", "/dashboard/api/hiring-plan/save", "hiring_plan.edit"),
    ("calendar delete", "POST", "/academic-calendar/events/1/delete", "calendar.delete"),
    ("role permissions save", "POST", "/system-configuration/role-permissions", "configuration.manage_permissions"),
    ("logo manage", "POST", "/system-configuration/logos/reset", ("branding.manage_school_logos", "branding.manage_branch_logos")),
    ("qualification manage", "POST", "/system-configuration/qualifications", ("configuration.manage_degrees", "configuration.manage_specializations")),
)


@pytest.mark.parametrize("name,method,path,key", MUTATION_FAMILIES, ids=[f[0] for f in MUTATION_FAMILIES])
def test_mutation_family_refused_without_key_and_allowed_with_it(world, monkeypatch, name, method, path, key):
    keys = (key,) if isinstance(key, str) else tuple(key)
    if path.startswith("/reports/"):
        # Entitlement (feature.advanced_reporting) is a separate commercial gate; assert
        # the PERMISSION layer in isolation by bypassing the entitlement lookup.
        import saas.entitlement_service as entitlement_service

        monkeypatch.setattr(entitlement_service, "can_use_feature", lambda *a, **k: True)
    assert world.route_allowed("admin", method, path) is True
    world.school_override(ADMIN, remove=keys)
    assert world.route_allowed("admin", method, path) is False, f"{name}: crafted request must be refused"
    # A user exception Deny on a different user is not needed: restore to prove it recovers.
    db = world.Session()
    baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, None)
    role_permission_service.apply_role_permission_overrides(
        db, role=ADMIN, allowed_keys=baseline, school_group_id=world.a, updated_by_user_id="t",
    )
    db.commit()
    db.close()
    assert world.route_allowed("admin", method, path) is True


def test_students_api_create_is_refused_before_mutation_and_succeeds_when_granted(world):
    def attempt():
        db, request, user = world.fresh("admin", "/api/students", "POST")
        try:
            response = students_api.student_create(
                request, {"first_name": "Ada", "father_name": "F", "last_name": "L", "gender": "F"},
                db, user,
            )
            count = db.query(models.Student).count()
            return response.status_code, count
        finally:
            db.close()

    world.school_override(ADMIN, remove=("students.create",))
    status, count = attempt()
    assert status == 403 and count == 0
    db = world.Session()
    baseline = role_permission_service.get_allowed_permission_keys(db, ADMIN, None)
    role_permission_service.apply_role_permission_overrides(
        db, role=ADMIN, allowed_keys=baseline, school_group_id=world.a, updated_by_user_id="t",
    )
    db.commit()
    db.close()
    status, count = attempt()
    assert status == 201 and count == 1


def test_students_ui_and_talent_ui_are_view_guarded_per_request(world):
    world.school_override(EDITOR, remove=("students.view",))
    assert world.route_allowed("editor", "GET", "/students/") is False
    assert world.route_allowed("admin", "GET", "/students/") is True


# ---------------------------------------------------------------------------
# STEP 5b: freshness (Allow -> Deny -> Allow) for each policy layer
# ---------------------------------------------------------------------------
def _all_surfaces(world, who="admin"):
    return (
        "subjects.view" in world.effective(who),
        "/subjects/" in world.sidebar(who),
        'id="panel-subjects"' in world.dashboard_html(who),
        world.route_allowed(who, "GET", "/subjects/"),
        world.route_allowed(who, "POST", "/subjects/"),
    )


def test_freshness_role_package_allow_deny_allow(world):
    assert _all_surfaces(world) == (True,) * 5
    world.role_package(ADMIN, remove=("subjects.view", "subjects.create"))
    assert _all_surfaces(world) == (False,) * 5
    world.role_package(ADMIN, add=("subjects.view", "subjects.create"))
    assert _all_surfaces(world) == (True,) * 5


def test_freshness_school_override_allow_deny_allow(world):
    assert _all_surfaces(world) == (True,) * 5
    world.school_override(ADMIN, remove=("subjects.view", "subjects.create"))
    assert _all_surfaces(world) == (False,) * 5
    world.school_override(ADMIN, add=("subjects.view", "subjects.create"))
    assert _all_surfaces(world) == (True,) * 5


def test_freshness_user_exception_allow_deny_allow(world):
    assert _all_surfaces(world) == (True,) * 5
    world.user_exception("admin", "subjects.view", "deny")
    world.user_exception("admin", "subjects.create", "deny")
    assert _all_surfaces(world) == (False,) * 5
    world.user_exception("admin", "subjects.view", "inherit")
    world.user_exception("admin", "subjects.create", "inherit")
    assert _all_surfaces(world) == (True,) * 5


def test_no_request_independent_permission_cache_survives_a_policy_change(world):
    """The same user id, new request/session: effective set tracks the DB immediately."""
    before = world.effective("admin")
    world.school_override(ADMIN, remove=("teachers.delete",))
    after = world.effective("admin")
    assert "teachers.delete" in before and "teachers.delete" not in after
    # Second resolver call on an OLD session object also sees the write (no stash).
    db = world.Session()
    user = db.get(models.User, world.ids["admin"])
    first = auth.get_allowed_permission_keys(db, user, world.a)
    world.school_override(ADMIN, add=("teachers.delete",))
    db.expire_all()
    second = auth.get_allowed_permission_keys(db, user, world.a)
    db.close()
    assert "teachers.delete" not in first and "teachers.delete" in second


def test_permission_state_is_never_module_level_or_session_stored():
    import inspect

    for module in (auth, authorization, ui_shell, role_permission_service, ups, permission_registry):
        source = inspect.getsource(module)
        assert "lru_cache" not in source and "functools.cache" not in source, module.__name__
        assert "_permission_cache" not in source, module.__name__
    source = inspect.getsource(auth)
    assert "session[" not in source.lower() or "permission" not in source.lower().split("session[")[1][:60]


# ---------------------------------------------------------------------------
# STEP 5c: role change with exceptions and School Override present
# ---------------------------------------------------------------------------
def test_role_change_recomputes_on_next_request_and_retains_exceptions(world):
    world.user_exception("editor", "subjects.edit", "deny")
    world.school_override(EDITOR, remove=("subjects.create",))
    world.school_override(ADMIN, remove=("teachers.delete",))
    editor_keys = world.effective("editor")
    assert "subjects.edit" not in editor_keys and "subjects.create" not in editor_keys

    def set_role(role):
        db = world.Session()
        db.get(models.User, world.ids["editor"]).role = role
        db.commit()
        db.close()

    set_role(ADMIN)
    admin_keys = world.effective("editor")
    assert "subjects.edit" not in admin_keys  # retained user Deny
    assert "subjects.create" in admin_keys  # Editor-only School Override does not apply to Administrator
    assert "teachers.delete" not in admin_keys  # Administrator School Override now applies
    set_role(EDITOR)
    back = world.effective("editor")
    assert back == editor_keys
    set_role(USER)
    user_keys = world.effective("editor")
    assert "subjects.edit" not in user_keys
    # exception row retained across all role changes (ADR 0040)
    db = world.Session()
    rows = db.query(models.UserPermissionOverride).filter_by(user_id=world.ids["editor"]).all()
    db.close()
    assert [(r.permission_key, r.is_allowed) for r in rows] == [("subjects.edit", False)]


# ---------------------------------------------------------------------------
# STEP 5d: tenant isolation
# ---------------------------------------------------------------------------
def test_school_override_and_user_exception_do_not_cross_tenants(world):
    world.school_override(ADMIN, remove=("subjects.view",))
    world.user_exception("admin", "teachers.view", "deny")
    assert "subjects.view" in world.effective("admin_b")
    assert "teachers.view" in world.effective("admin_b")
    assert world.route_allowed("admin_b", "GET", "/subjects/") is True


def test_user_exception_scope_is_the_target_users_school_not_the_actors(world):
    db = world.Session()
    target = db.get(models.User, world.ids["admin_b"])
    with pytest.raises(ValueError):
        ups.apply_user_override(
            db, target_user=target, permission_key="subjects.view", decision="deny",
            school_group_id=world.a, updated_by_user_id="t",
        )
    assert db.query(models.UserPermissionOverride).count() == 0
    db.close()


def test_tenant_actor_cannot_write_another_tenants_role_policy_or_global_packages(world):
    def post(mode, group):
        db, request, user = world.fresh("admin", "/system-configuration/role-permissions", "POST")
        try:
            response = main.update_role_permissions(
                request, role=ADMIN, mode=mode, school_group_id=group,
                permission_keys=["dashboard.view"], db=db,
            )
            return response.status_code, response.headers.get("location", "")
        finally:
            db.close()

    status, location = post("overrides", world.b)
    assert status == 302 and location == "/dashboard"
    status, location = post("packages", None)
    assert status == 302 and location == "/dashboard"
    db = world.Session()
    assert db.query(models.RolePermission).count() == 0
    db.close()


def test_platform_owner_management_target_does_not_grant_tenant_membership(world):
    db, request, user = world.fresh("owner", "/system-configuration/role-permissions", scope_group=world.b)
    try:
        assert auth.is_platform_user(user)
        assert user.school_group_id is None and user.branch_id is None
        role_permission_service.apply_role_permission_overrides(
            db, role=ADMIN, allowed_keys={"dashboard.view"}, school_group_id=world.b,
            updated_by_user_id=user.user_id,
        )
        db.commit()
        db.expire_all()
        assert db.get(models.User, world.ids["owner"]).school_group_id is None
    finally:
        db.close()
    # Tenant B gets the override; tenant A is untouched.
    assert world.effective("admin_b") == {"dashboard.view"}
    assert "subjects.view" in world.effective("admin")


# ---------------------------------------------------------------------------
# STEP 5e: platform-only protection
# ---------------------------------------------------------------------------
PLATFORM_KEY = "system_owner.full_access"


def test_platform_only_keys_cannot_be_granted_by_role_package_school_override_or_exception(world):
    platform = set(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS)
    world.role_package(ADMIN, add=tuple(platform))
    world.school_override(ADMIN, add=tuple(platform))
    keys = world.effective("admin")
    assert keys & platform == set()
    db = world.Session()
    target = db.get(models.User, world.ids["admin"])
    for key in list(platform)[:5]:
        for decision in ("allow", "deny"):
            with pytest.raises(ValueError):
                ups.apply_user_override(
                    db, target_user=target, permission_key=key, decision=decision,
                    school_group_id=world.a, updated_by_user_id="t",
                )
    db.close()


def test_crafted_role_permission_post_cannot_resurrect_platform_only_keys(world):
    platform = sorted(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS)
    db, request, user = world.fresh("owner", "/system-configuration/role-permissions", "POST")
    try:
        main.update_role_permissions(
            request, role=ADMIN, mode="overrides", school_group_id=world.a,
            permission_keys=platform + ["dashboard.view"], db=db,
        )
    finally:
        db.close()
    assert world.effective("admin") & set(platform) == set()
    for who in ("editor", "user", "limited"):
        assert world.effective(who) & set(platform) == set()


def test_platform_routes_stay_identity_guarded_for_tenant_users_with_any_policy(world):
    world.role_package(ADMIN, add=(PLATFORM_KEY,))
    world.school_override(ADMIN, add=(PLATFORM_KEY,))
    assert world.route_allowed("admin", "GET", "/platform") is False
    assert "/platform" not in world.sidebar("admin")


# ---------------------------------------------------------------------------
# DEFECT: /scope/organization ignored the platform-only switch capability
# ---------------------------------------------------------------------------
def _grant_developer(world, *keys):
    db = world.Session()
    dev = db.get(models.User, world.ids["dev"])
    for key in keys:
        db.add(models.PlatformUserPermission(platform_user_id=dev.id, permission_key=key, is_allowed=True))
    db.commit()
    db.close()


def _switch_org(world, who, group_id):
    db, request, user = world.fresh(who, "/scope/organization", "POST")
    try:
        response = main.set_scope_organization(request, school_group_id=group_id, return_to="/platform", db=db)
        return response.status_code, "school_group_id" in response.headers.get("set-cookie", "")
    finally:
        db.close()


def test_scope_organization_requires_the_switch_capability_for_platform_developers(world):
    _grant_developer(world, "dashboard.view", "schools.view")  # no switch/manage-all capability
    status, cookie_set = _switch_org(world, "dev", world.b)
    assert status == 403 and cookie_set is False
    _grant_developer(world, "system_owner.switch_all_schools")
    status, cookie_set = _switch_org(world, "dev", world.b)
    assert status == 302 and cookie_set is True


def test_scope_organization_still_allowed_for_owner_and_denied_for_tenant(world):
    assert _switch_org(world, "owner", world.b) == (302, True)
    status, cookie_set = _switch_org(world, "admin", world.b)
    assert status == 403 and cookie_set is False
