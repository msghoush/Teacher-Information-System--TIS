import os

os.environ["TIS_SESSION_SECRET"] = "user-permission-override-route-test-secret-long-enough"

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
from routers import users as users_router

ADMIN = auth.ROLE_ADMINISTRATOR
EDITOR = auth.ROLE_EDITOR


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

        acting_admin = models.User(
            user_id="1000", username="acting_admin", first_name="Acting", last_name="Admin",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id, is_active=True,
        )
        user_a = models.User(
            user_id="1001", username="admin_a", first_name="Admin", last_name="A",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id, is_active=True,
        )
        user_b = models.User(
            user_id="1002", username="admin_b", first_name="Admin", last_name="B",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id, is_active=True,
        )
        editor_actor = models.User(
            user_id="1004", username="editor_actor", first_name="Editor", last_name="Actor",
            role=EDITOR, position="Teacher", password=auth.get_password_hash("password123"),
            school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id, is_active=True,
        )
        other_user = models.User(
            user_id="2001", username="admin_other", first_name="Admin", last_name="Other",
            role=ADMIN, position="Principal", password=auth.get_password_hash("password123"),
            school_group_id=other_school.id, branch_id=other_branch.id, academic_year_id=other_year.id,
            is_active=True,
        )
        platform_owner = models.User(
            user_id="9000", username="platform_owner", first_name="Platform", last_name="Owner",
            role=None, position="Owner",
            password=auth.get_password_hash("password123"),
            user_type=auth.USER_TYPE_PLATFORM, platform_role=auth.PLATFORM_ROLE_OWNER,
            # Deliberately stale tenant fields pointed at the OTHER SchoolGroup:
            # is_platform_user() must make auth.get_user_school_group_id ignore
            # these for the acting admin, so a route-level fix that (wrongly)
            # trusted this stale field would be caught by the assertions below.
            school_group_id=other_school.id, branch_id=other_branch.id,
            academic_year_id=other_year.id, is_active=True,
        )
        db.add_all([acting_admin, user_a, user_b, editor_actor, other_user, platform_owner])
        db.commit()
        return {
            "school_id": school.id,
            "other_school_id": other_school.id,
            "acting_admin_id": acting_admin.id,
            "user_a_id": user_a.id,
            "user_b_id": user_b.id,
            "editor_actor_id": editor_actor.id,
            "other_user_id": other_user.id,
            "platform_owner_id": platform_owner.id,
        }
    finally:
        db.close()


def _request(path, user, method="GET"):
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
        "type": "http", "http_version": "1.1", "method": method, "path": path,
        "raw_path": path.encode("utf-8"), "query_string": b"",
        "headers": headers, "scheme": "http",
        "server": ("testserver", 80), "client": ("testclient", 50000),
        "root_path": "", "app": main.app,
    }
    return Request(scope)


def _save_overrides(db, acting_user, target_user_id, decisions: dict):
    """Call the route function directly, mirroring the existing
    main.update_role_permissions direct-call test convention."""
    return users_router.update_user_permissions(
        _request(f"/users/permissions/{target_user_id}", acting_user, method="POST"),
        user_pk=target_user_id,
        permission_keys=list(decisions.keys()),
        permission_decisions=list(decisions.values()),
        db=db,
    )


def _allowed_after(Session, user_id, school_id):
    read = Session()
    try:
        fresh = read.query(models.User).get(user_id)
        return auth.get_allowed_permission_keys(read, fresh, school_id)
    finally:
        read.close()


def _guard(Session, user_id, path):
    read = Session()
    try:
        fresh = read.query(models.User).get(user_id)
        return authorization.enforce_route_permission(_request(path, fresh), read, current_user=fresh)
    finally:
        read.close()


def _nav_hrefs(db, user):
    context = ui_shell.build_shell_context(
        _request("/dashboard", user), db, user, page_key="dashboard",
    )
    return {item["href"] for item in context["shell"]["nav_items"]}


# ---------------------------------------------------------------------------
# Persist + immediate reflection, no stale cache
# ---------------------------------------------------------------------------

def test_route_persists_deny_then_inherit_and_reflects_immediately():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])

        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        assert _guard(Session, ids["user_b_id"], "/dashboard") is None

        resp = _save_overrides(db, acting_admin, ids["user_b_id"], {"dashboard.view": "deny"})
        db.commit()
        assert getattr(resp, "status_code", 200) == 200

        row = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_b_id"],
            models.UserPermissionOverride.permission_key == "dashboard.view",
        ).first()
        assert row is not None
        assert row.is_allowed is False

        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        denied = _guard(Session, ids["user_b_id"], "/dashboard")
        assert denied is not None and denied.status_code == 403

        resp = _save_overrides(db, acting_admin, ids["user_b_id"], {"dashboard.view": "inherit"})
        db.commit()
        assert getattr(resp, "status_code", 200) == 200

        row = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_b_id"],
            models.UserPermissionOverride.permission_key == "dashboard.view",
        ).first()
        assert row is None

        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        assert _guard(Session, ids["user_b_id"], "/dashboard") is None
    finally:
        db.close()
        engine.dispose()


def test_sibling_user_unaffected_by_route_level_override_before_and_after():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])

        assert "dashboard.view" in _allowed_after(Session, ids["user_a_id"], ids["school_id"])
        assert _guard(Session, ids["user_a_id"], "/dashboard") is None

        _save_overrides(db, acting_admin, ids["user_b_id"], {"dashboard.view": "deny"})
        db.commit()

        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        assert "dashboard.view" in _allowed_after(Session, ids["user_a_id"], ids["school_id"])
        assert _guard(Session, ids["user_a_id"], "/dashboard") is None
    finally:
        db.close()
        engine.dispose()


def test_role_change_recalculates_and_stale_allow_cannot_resurrect_access():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])

        # Give user_b a stale per-user Allow override while still Administrator.
        _save_overrides(db, acting_admin, ids["user_b_id"], {"dashboard.view": "allow"})
        db.commit()
        assert "dashboard.view" in _allowed_after(Session, ids["user_b_id"], ids["school_id"])

        # Move user_b to Editor, then deny dashboard.view at the role/tenant level
        # for Editor in this SchoolGroup (no default managed role fully lacks
        # dashboard.view, so the role-level deny is what removes it).
        user_b = db.query(models.User).get(ids["user_b_id"])
        user_b.role = EDITOR
        db.commit()

        editor_defaults = role_permission_service.get_allowed_permission_keys(db, EDITOR, ids["school_id"])
        role_permission_service.apply_role_permission_overrides(
            db, role=EDITOR, allowed_keys=editor_defaults - {"dashboard.view"},
            school_group_id=ids["school_id"], updated_by_user_id="1000",
        )
        db.commit()

        # Deny-over-Allow: the stale user-level Allow must not resurrect access
        # the new role does not grant.
        assert "dashboard.view" not in _allowed_after(Session, ids["user_b_id"], ids["school_id"])
        denied = _guard(Session, ids["user_b_id"], "/dashboard")
        assert denied is not None and denied.status_code == 403
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Route-level rejections
# ---------------------------------------------------------------------------

def test_route_rejects_platform_only_key():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])
        platform_key = next(iter(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS))

        resp = _save_overrides(db, acting_admin, ids["user_a_id"], {platform_key: "deny"})
        assert getattr(resp, "status_code", 200) == 200

        row = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_a_id"],
            models.UserPermissionOverride.permission_key == platform_key,
        ).first()
        assert row is None
    finally:
        db.close()
        engine.dispose()


def test_route_rejects_cross_school_group_target():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])

        resp = _save_overrides(db, acting_admin, ids["other_user_id"], {"dashboard.view": "deny"})
        assert getattr(resp, "status_code", 200) == 200

        row = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["other_user_id"],
        ).first()
        assert row is None
        # Target in the other SchoolGroup keeps its role-resolved access untouched.
        assert "dashboard.view" in _allowed_after(Session, ids["other_user_id"], ids["other_school_id"])
    finally:
        db.close()
        engine.dispose()


def test_route_rejects_unauthorized_acting_user():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        editor_actor = db.query(models.User).get(ids["editor_actor_id"])
        assert not auth.has_permission(db, editor_actor, "configuration.manage_permissions")

        resp = _save_overrides(db, editor_actor, ids["user_a_id"], {"dashboard.view": "deny"})
        assert getattr(resp, "status_code", None) == 302
        assert getattr(resp, "headers", {}).get("location") == "/dashboard"

        row = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_a_id"],
        ).first()
        assert row is None
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Nav visibility seam (ui_shell.build_shell_context)
# ---------------------------------------------------------------------------

def test_nav_dashboard_item_absent_for_denied_present_for_unaffected():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])
        _save_overrides(db, acting_admin, ids["user_b_id"], {"dashboard.view": "deny"})
        db.commit()

        user_b = db.query(models.User).get(ids["user_b_id"])
        user_a = db.query(models.User).get(ids["user_a_id"])
        # Prime request-scoped permission_keys the way get_current_user does.
        user_b.permission_keys = frozenset(auth.get_allowed_permission_keys(db, user_b, ids["school_id"]))
        user_a.permission_keys = frozenset(auth.get_allowed_permission_keys(db, user_a, ids["school_id"]))
        user_b.scope_branch_id = user_b.branch_id
        user_a.scope_branch_id = user_a.branch_id
        user_b.scope_academic_year_id = user_b.academic_year_id
        user_a.scope_academic_year_id = user_a.academic_year_id

        assert "/dashboard" not in _nav_hrefs(db, user_b)
        assert "/dashboard" in _nav_hrefs(db, user_a)
    finally:
        db.close()
        engine.dispose()


# ---------------------------------------------------------------------------
# Platform-level actor with no tenant scope of their own (item 1)
# ---------------------------------------------------------------------------

def test_platform_actor_with_no_own_tenant_scopes_override_to_target_school_group():
    """A platform owner has no resolvable tenant school_group_id of their own
    (auth.get_user_school_group_id always returns None for a platform user,
    even with stale tenant fields present). The route must not hard-error;
    it must derive the override's scope from the already server-loaded
    target user's own verified school_group_id, matching
    _build_user_permission_context's identical read-side resolution."""
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        platform_owner = db.query(models.User).get(ids["platform_owner_id"])
        assert auth.get_user_school_group_id(db, platform_owner) is None

        resp = _save_overrides(db, platform_owner, ids["user_a_id"], {"dashboard.view": "deny"})
        assert getattr(resp, "status_code", 200) == 200

        row = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_a_id"],
            models.UserPermissionOverride.permission_key == "dashboard.view",
        ).first()
        assert row is not None
        # Scope must be the TARGET's own SchoolGroup ("school"), never the
        # platform actor's stale tenant field (which points at "other_school").
        assert row.school_group_id == ids["school_id"]
        assert row.school_group_id != ids["other_school_id"]

        assert "dashboard.view" not in _allowed_after(Session, ids["user_a_id"], ids["school_id"])
    finally:
        db.close()
        engine.dispose()


def test_platform_actor_override_scope_tracks_each_targets_own_school_group_not_a_shared_value():
    """The same platform actor writing overrides for two different targets
    in two different SchoolGroups must scope each write to that specific
    target -- proving there is no single actor-controlled scope value (and
    therefore no privilege-escalation vector into an arbitrary SchoolGroup)."""
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        platform_owner = db.query(models.User).get(ids["platform_owner_id"])

        resp_a = _save_overrides(db, platform_owner, ids["user_a_id"], {"dashboard.view": "deny"})
        assert getattr(resp_a, "status_code", 200) == 200
        db.commit()

        platform_owner = db.query(models.User).get(ids["platform_owner_id"])
        resp_other = _save_overrides(db, platform_owner, ids["other_user_id"], {"dashboard.view": "deny"})
        assert getattr(resp_other, "status_code", 200) == 200
        db.commit()

        row_a = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["user_a_id"],
        ).first()
        row_other = db.query(models.UserPermissionOverride).filter(
            models.UserPermissionOverride.user_id == ids["other_user_id"],
        ).first()
        assert row_a.school_group_id == ids["school_id"]
        assert row_other.school_group_id == ids["other_school_id"]
        assert row_a.school_group_id != row_other.school_group_id
    finally:
        db.close()
        engine.dispose()


def test_platform_actor_cannot_use_service_layer_to_write_into_a_mismatched_school_group():
    """Even bypassing the route and calling the service directly, a decision
    whose supplied school_group_id does not match the target's own real
    school_group_id is rejected -- confirming the route's target-derived
    scope is the only value that can ever succeed, not an
    attacker-controlled/arbitrary one."""
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        user_a = db.query(models.User).get(ids["user_a_id"])
        with pytest.raises(ValueError):
            ups.apply_user_override(
                db,
                target_user=user_a,
                permission_key="dashboard.view",
                decision="deny",
                school_group_id=ids["other_school_id"],
                updated_by_user_id="9000",
            )
    finally:
        db.close()
        engine.dispose()


def test_edit_profile_permission_cannot_change_role_branch_status_or_password():
    engine, Session = _make_db()
    data = _seed(Session)
    db = Session()
    try:
        actor = db.get(models.User, data["editor_actor_id"])
        target = db.get(models.User, data["user_a_id"])
        for key in ("users.view", "users.edit_profile"):
            db.add(models.RolePermission(
                school_group_id=data["school_id"], role=EDITOR,
                permission_key=key, is_allowed=True, updated_by_user_id="system",
            ))
        db.commit()
        response = users_router.update_user(
            request=_request(f"/users/edit/{target.id}", actor, method="POST"),
            user_pk=target.id, user_id=target.user_id, email=target.email or "",
            first_name=target.first_name, last_name=target.last_name,
            position=target.position, role=EDITOR, access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            branch_id=target.branch_id, is_active="inactive", password="changed-password",
            db=db,
        )
        assert response.status_code == 200
        db.expire_all()
        unchanged = db.get(models.User, data["user_a_id"])
        assert unchanged.role == ADMIN
        assert unchanged.access_scope == auth.ACCESS_SCOPE_BRANCH
        assert unchanged.is_active is True
        assert not auth.verify_password("changed-password", unchanged.password)
    finally:
        db.close()
        engine.dispose()
