"""Phase 2 coverage: User Exceptions UX on the edit-user page.

The normal UI is binary Allow / Deny plus "Reset to Role Settings" (internal
"inherit" == delete the override row). ADR 0040 precedence is unchanged.
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TIS_SESSION_SECRET"] = "user-permission-override-route-test-secret-long-enough"

import re

import auth
import models
import permission_registry
import role_permission_service
import user_permission_service as ups
from routers import users as users_router
from tests.test_user_permission_override_routes import _make_db, _request, _seed

ADMIN = auth.ROLE_ADMINISTRATOR
EDITOR = auth.ROLE_EDITOR
KEY = "subjects.view"


def _change(db, actor, target_id, value):
    return users_router.update_user_permissions(
        _request(f"/users/permissions/{target_id}", actor, method="POST"),
        user_pk=target_id,
        change=value,
        db=db,
    )


def _html(db, actor, target_id):
    resp = users_router.edit_user_page(
        _request(f"/users/edit/{target_id}", actor), user_pk=target_id, db=db
    )
    assert resp.status_code == 200
    return resp.body.decode("utf-8")


def _panel(html):
    start = html.index('<section class="user-override-panel"')
    return html[start:html.index("</section>", start)]


def _row(html, key):
    panel = _panel(html)
    start = panel.index(f'id="perm-{key}"')
    end = panel.find('id="perm-', start + 10)
    return panel[start:end if end != -1 else len(panel)]


def _payload_item(db, user_id, key, school_id):
    user = db.get(models.User, user_id)
    payload = ups.build_user_permission_payload(
        db, target_user=user, normalized_role=ADMIN, school_group_id=school_id
    )
    for group in payload["groups"]:
        for item in group["permissions"]:
            if item["key"] == key:
                return item
    raise AssertionError(key)


def _override(db, user_id, key):
    db.expire_all()
    return db.query(models.UserPermissionOverride).filter_by(user_id=user_id, permission_key=key).first()


def _setup():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    return engine, Session, ids, db


def _tenant_role_row(db, school_id, role, key, allowed):
    db.add(models.RolePermission(
        school_group_id=school_id, role=role, permission_key=key,
        is_allowed=allowed, updated_by_user_id="system",
    ))
    db.commit()


def test_case1_role_allow_no_exception_standard_source_no_reset():
    engine, Session, ids, db = _setup()
    try:
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is True and item["source"] == "standard_role"
        assert item["exception"] is None and item["has_exception"] is False
        actor = db.get(models.User, ids["acting_admin_id"])
        row = _row(_html(db, actor, ids["user_a_id"]), KEY)
        assert "Standard Role Package" in row and "Allow</dd>" in row
        assert "Reset to Role Settings" not in row
        # School Override variant.
        _tenant_role_row(db, ids["school_id"], ADMIN, KEY, True)
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["source"] == "school_override" and item["effective"] is True
        assert "School Override" in _row(_html(db, actor, ids["user_a_id"]), KEY)
    finally:
        db.close(); engine.dispose()


def test_case2_user_deny_over_role_allow():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _change(db, actor, ids["user_a_id"], f"{KEY}|deny")
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is False and item["source"] == "user_exception"
        assert item["exception"] == "deny"
        row = _row(_html(db, actor, ids["user_a_id"]), KEY)
        assert "Reset to Role Settings" in row
        assert 'value="subjects.view|deny"' in row and 'aria-pressed="true"' in row
    finally:
        db.close(); engine.dispose()


def test_case3_user_allow_with_role_allow():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _change(db, actor, ids["user_a_id"], f"{KEY}|allow")
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is True and item["source"] == "user_exception"
        assert item["exception_inert"] is False
        assert "Reset to Role Settings" in _row(_html(db, actor, ids["user_a_id"]), KEY)
    finally:
        db.close(); engine.dispose()


def test_case4_inert_allow_when_role_denies_is_kept_and_explained():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _change(db, actor, ids["user_a_id"], f"{KEY}|allow")
        _tenant_role_row(db, ids["school_id"], ADMIN, KEY, False)
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is False and item["exception"] == "allow"
        assert item["exception_inert"] is True and item["source"] == "school_override"
        row = _row(_html(db, actor, ids["user_a_id"]), KEY)
        assert "stored, currently ineffective" in row
        assert "cannot override it" in row and "applies again" in row
        assert "Reset to Role Settings" in row
        assert _override(db, ids["user_a_id"], KEY) is not None
        # Re-granting the role makes the stored Allow effective again.
        role_row = db.query(models.RolePermission).filter_by(permission_key=KEY, role=ADMIN).first()
        role_row.is_allowed = True
        db.commit()
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is True and item["source"] == "user_exception"
    finally:
        db.close(); engine.dispose()


def test_case4b_inert_allow_standard_source_without_school_row():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        db.add(models.RolePermission(
            school_group_id=None, role=ADMIN, permission_key=KEY,
            is_allowed=False, updated_by_user_id="system",
        ))
        db.commit()
        _change(db, actor, ids["user_a_id"], f"{KEY}|allow")
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["exception_inert"] is True and item["source"] == "standard_role"
    finally:
        db.close(); engine.dispose()


def test_case5_role_deny_and_user_deny():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _tenant_role_row(db, ids["school_id"], ADMIN, KEY, False)
        _change(db, actor, ids["user_a_id"], f"{KEY}|deny")
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is False and item["source"] == "user_exception"
        assert "Reset to Role Settings" in _row(_html(db, actor, ids["user_a_id"]), KEY)
    finally:
        db.close(); engine.dispose()


def _reset_case(decision):
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _tenant_role_row(db, ids["school_id"], ADMIN, "teachers.view", True)
        _change(db, actor, ids["user_b_id"], f"{KEY}|deny")  # sibling untouched
        _change(db, actor, ids["user_a_id"], f"{KEY}|{decision}")
        role_rows_before = db.query(models.RolePermission).count()
        resp = _change(db, actor, ids["user_a_id"], f"{KEY}|reset")
        assert resp.status_code == 200
        assert "reset to role settings" in resp.body.decode("utf-8")
        assert _override(db, ids["user_a_id"], KEY) is None
        assert db.query(models.RolePermission).count() == role_rows_before
        assert _override(db, ids["user_b_id"], KEY).is_allowed is False
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is True and item["source"] == "standard_role"
    finally:
        db.close(); engine.dispose()


def test_case6_reset_deny_deletes_row_only():
    _reset_case("deny")


def test_case7_reset_allow_deletes_row_only():
    _reset_case("allow")


def test_case8_role_change_keeps_override_and_recomputes():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _change(db, actor, ids["user_a_id"], f"{KEY}|allow")
        user = db.get(models.User, ids["user_a_id"])
        user.role = EDITOR
        db.commit()
        editor_defaults = role_permission_service.get_allowed_permission_keys(db, EDITOR, ids["school_id"])
        assert _override(db, ids["user_a_id"], KEY) is not None
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["role_allowed"] == (KEY in editor_defaults)
        assert item["effective"] == (KEY in editor_defaults)
        assert item["exception_inert"] == (KEY not in editor_defaults)
        user.role = ADMIN
        db.commit()
        assert _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])["effective"] is True
    finally:
        db.close(); engine.dispose()


def test_case9_tenant_isolation_and_platform_target_scope():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])
        _change(db, admin, ids["other_user_id"], f"{KEY}|deny")
        assert _override(db, ids["other_user_id"], KEY) is None
        # Client-supplied school_group_id is not a route parameter at all.
        import inspect
        assert "school_group_id" not in inspect.signature(users_router.update_user_permissions).parameters

        owner = db.get(models.User, ids["platform_owner_id"])
        _change(db, owner, ids["user_a_id"], f"{KEY}|deny")
        row = _override(db, ids["user_a_id"], KEY)
        assert row.school_group_id == ids["school_id"]
        _change(db, owner, ids["other_user_id"], f"{KEY}|deny")
        assert _override(db, ids["other_user_id"], KEY).school_group_id == ids["other_school_id"]
    finally:
        db.close(); engine.dispose()


def test_case10_platform_only_key_rejected_and_row_is_locked():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])
        key = sorted(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS)[0]
        resp = _change(db, admin, ids["user_a_id"], f"{key}|allow")
        assert "platform-only" in resp.body.decode("utf-8")
        assert _override(db, ids["user_a_id"], key) is None
        row = _row(_html(db, admin, ids["user_a_id"]), key)
        assert "Platform only - cannot be set per user" in row
        assert "<button" not in row
    finally:
        db.close(); engine.dispose()


def test_malformed_change_rejected_without_write():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])
        for bad in ("nopipe", f"{KEY}|inherit", "|deny", f"{KEY}|"):
            resp = _change(db, admin, ids["user_a_id"], bad)
            assert "invalid permission change" in resp.body.decode("utf-8")
        assert db.query(models.UserPermissionOverride).count() == 0
        resp = _change(db, admin, ids["user_a_id"], "not.a.key|deny")
        assert "unknown permission key" in resp.body.decode("utf-8")
        assert db.query(models.UserPermissionOverride).count() == 0
    finally:
        db.close(); engine.dispose()


def test_case11_inactive_and_missing_target_fail_closed():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])
        target = db.get(models.User, ids["user_a_id"])
        target.is_active = False
        db.commit()
        item = _payload_item(db, ids["user_a_id"], KEY, ids["school_id"])
        assert item["effective"] is False and item["blocked_by_account"] is True
        html = _html(db, admin, ids["user_a_id"])
        assert "account is inactive" in _panel(html)
        assert "Effective:</dt><dd class=\"is-deny\">Deny" in _row(html, KEY)
        resp = _change(db, admin, 999999, f"{KEY}|deny")
        assert "User not found or access denied." in resp.body.decode("utf-8")
        assert db.query(models.UserPermissionOverride).count() == 0
    finally:
        db.close(); engine.dispose()


def test_case12_freshness_allow_deny_reset_allow():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])

        def fresh_effective():
            read = Session()
            try:
                user = read.get(models.User, ids["user_a_id"])
                return KEY in auth.get_allowed_permission_keys(read, user, ids["school_id"])
            finally:
                read.close()

        assert fresh_effective() is True
        _change(db, admin, ids["user_a_id"], f"{KEY}|allow")
        assert fresh_effective() is True
        _change(db, admin, ids["user_a_id"], f"{KEY}|deny")
        assert fresh_effective() is False
        _change(db, admin, ids["user_a_id"], f"{KEY}|reset")
        assert fresh_effective() is True
        _change(db, admin, ids["user_a_id"], f"{KEY}|allow")
        assert fresh_effective() is True
    finally:
        db.close(); engine.dispose()


def test_effective_matches_auth_for_subjects_and_teachers():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])
        _tenant_role_row(db, ids["school_id"], ADMIN, "teachers.view", False)
        _change(db, admin, ids["user_a_id"], "subjects.view|deny")
        _change(db, admin, ids["user_b_id"], "teachers.view|allow")
        for uid in (ids["user_a_id"], ids["user_b_id"]):
            user = db.get(models.User, uid)
            expected = auth.get_allowed_permission_keys(db, user, ids["school_id"])
            for key in ("subjects.view", "teachers.view"):
                assert _payload_item(db, uid, key, ids["school_id"])["effective"] == (key in expected)
    finally:
        db.close(); engine.dispose()


def test_rendered_panel_accessibility_and_content():
    engine, Session, ids, db = _setup()
    try:
        admin = db.get(models.User, ids["acting_admin_id"])
        _change(db, admin, ids["user_a_id"], "subjects.view|deny")
        _change(db, admin, ids["user_a_id"], "teachers.view|allow")
        html = _html(db, admin, ids["user_a_id"])
        panel = _panel(html)
        assert "User Permission Exceptions" in panel
        assert "Per-User Permission Overrides" not in html
        assert "inherit" not in panel.lower()
        assert 'type="radio"' not in panel
        assert "aria-expanded" not in panel
        assert "Al-Andalus Schools" in panel and "Hamadania-Boys" in panel and "Active" in panel
        # No button inside a label.
        assert not re.search(r"<label[^>]*>(?:(?!</label>).)*<button", panel, re.S)
        # Every action button has an accessible name and a return anchor.
        buttons = re.findall(r"<button[^>]*>", panel)
        assert buttons
        for tag in buttons:
            assert 'aria-label="' in tag
            assert 'formaction="/users/permissions/' in tag and "#perm-" in tag
        assert 'id="perm-subjects.view"' in panel
        assert ":focus-visible" in html
        # Per-group exception counts: subjects.view and teachers.view are both
        # in groups; total of group counts must equal stored exceptions (2).
        counts = [int(n) for n in re.findall(r"<span>(\d+) exceptions?</span>", panel)]
        assert sum(counts) == 2
        # Groups with an exception are open by default; others are closed.
        assert len(re.findall(r'<details class="exc-group" open>', panel)) == sum(1 for c in counts if c)
    finally:
        db.close(); engine.dispose()


# ---------------------------------------------------------------------------
# Locked / non-assignable keys: stale exceptions can be removed, never created
# ---------------------------------------------------------------------------

def _admin_only_key():
    keys = sorted(
        permission_registry.ADMINISTRATOR_ONLY_PERMISSION_KEYS
        - permission_registry.PLATFORM_ONLY_PERMISSION_KEYS
    )
    assert keys
    return keys[0]


def _role_rows_snapshot(db):
    db.expire_all()
    return sorted(
        (r.school_group_id, r.role, r.permission_key, bool(r.is_allowed))
        for r in db.query(models.RolePermission).all()
    )


def _button_actions(row):
    return re.findall(r'name="change" value="[^"|]+\|(\w+)"', row)


def test_stale_exception_on_key_that_became_non_assignable_can_only_be_reset():
    engine, Session, ids, db = _setup()
    try:
        key = _admin_only_key()
        actor = db.get(models.User, ids["acting_admin_id"])
        user_id = ids["user_a_id"]

        # Assignable while the user is an Administrator; store an exception.
        assert _payload_item(db, user_id, key, ids["school_id"])["assignable"] is True
        _change(db, actor, user_id, f"{key}|deny")
        assert _override(db, user_id, key).is_allowed is False

        # Role change makes the key non-assignable; the stored exception remains.
        user = db.get(models.User, user_id)
        user.role = EDITOR
        db.commit()
        role_rows_before = _role_rows_snapshot(db)
        item = _payload_item(db, user_id, key, ids["school_id"])
        assert item["assignable"] is False and item["has_exception"] is True
        assert _override(db, user_id, key) is not None

        # UI: locked row, no Allow/Deny, only Reset to Role Settings.
        row = _row(_html(db, actor, user_id), key)
        assert "Not available for the Editor role" in row
        assert _button_actions(row) == ["reset"]
        assert "Reset to Role Settings" in row

        # Creation / modification on the locked key is still refused.
        _change(db, actor, user_id, f"{key}|allow")
        assert _override(db, user_id, key).is_allowed is False
        assert _override(db, user_id, key) is not None

        # Reset succeeds: row deleted, effective recomputed from role/school policy.
        _change(db, actor, user_id, f"{key}|reset")
        assert _override(db, user_id, key) is None
        editor_keys = role_permission_service.get_allowed_permission_keys(db, EDITOR, ids["school_id"])
        item = _payload_item(db, user_id, key, ids["school_id"])
        assert item["effective"] == (key in editor_keys) and item["effective"] is False
        assert item["has_exception"] is False

        # Locked row with no exception now has no actions at all.
        row = _row(_html(db, actor, user_id), key)
        assert _button_actions(row) == []
        assert "Reset to Role Settings" not in row

        # No RolePermission row was changed by any of this.
        assert _role_rows_snapshot(db) == role_rows_before
    finally:
        db.close(); engine.dispose()


def test_locked_key_without_exception_has_no_actions_including_platform_only():
    engine, Session, ids, db = _setup()
    try:
        key = _admin_only_key()
        actor = db.get(models.User, ids["acting_admin_id"])
        user_id = ids["user_a_id"]
        user = db.get(models.User, user_id)
        user.role = EDITOR
        db.commit()

        html = _html(db, actor, user_id)
        locked_row = _row(html, key)
        assert "Not available for the Editor role" in locked_row
        assert _button_actions(locked_row) == []
        assert "Reset to Role Settings" not in locked_row

        platform_key = sorted(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS)[0]
        platform_row = _row(html, platform_key)
        assert "Platform only" in platform_row
        assert _button_actions(platform_row) == []
    finally:
        db.close(); engine.dispose()


def test_legacy_inherit_api_still_clears_an_override():
    engine, Session, ids, db = _setup()
    try:
        actor = db.get(models.User, ids["acting_admin_id"])
        _change(db, actor, ids["user_a_id"], f"{KEY}|deny")
        assert _override(db, ids["user_a_id"], KEY) is not None
        users_router.update_user_permissions(
            _request(f"/users/permissions/{ids['user_a_id']}", actor, method="POST"),
            user_pk=ids["user_a_id"],
            permission_keys=[KEY],
            permission_decisions=["inherit"],
            db=db,
        )
        assert _override(db, ids["user_a_id"], KEY) is None
    finally:
        db.close(); engine.dispose()
