"""Template/render integration coverage for templates/edit_user.html's
per-user permission override panel.

Renders the actual `GET /users/edit/{user_pk}` route (not a hand-built
Jinja context) so the assertions below prove real, currently-shipping
markup/text rather than an assumption about the template's shape.
"""
import os

os.environ["TIS_SESSION_SECRET"] = "user-permission-override-route-test-secret-long-enough"

import auth
import models
import permission_registry
import user_permission_service as ups
from routers import users as users_router
from tests.test_user_permission_override_routes import _make_db, _request, _seed


def _render_edit_user_page_html(db, acting_user, target_user_id):
    resp = users_router.edit_user_page(
        _request(f"/users/edit/{target_user_id}", acting_user, method="GET"),
        user_pk=target_user_id,
        db=db,
    )
    assert getattr(resp, "status_code", 200) == 200
    return resp.body.decode("utf-8")


def test_edit_user_page_renders_allow_deny_reset_reason_text_and_locked_platform_only_row():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])

        # dashboard.view is role-granted by default for Administrator, so
        # denying it exercises the direct-Deny exception rendering.
        ups.apply_user_override(
            db,
            target_user=db.query(models.User).get(ids["user_a_id"]),
            permission_key="dashboard.view",
            decision="deny",
            school_group_id=ids["school_id"],
            updated_by_user_id=acting_admin.user_id,
        )
        db.commit()

        html = _render_edit_user_page_html(db, acting_admin, ids["user_a_id"])

        # Binary Allow/Deny actions plus Reset; no Inherit radios (Phase 2).
        assert 'name="change" value="dashboard.view|allow"' in html
        assert 'name="change" value="dashboard.view|deny"' in html
        assert 'name="change" value="dashboard.view|reset"' in html
        assert 'type="radio"' not in html
        assert "User Permission Exceptions" in html

        # Direct Deny is described as a User Exception.
        assert "User Exception:" in html and "Deny" in html

        # Platform-only keys render as locked rows with no live controls.
        platform_key = next(iter(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS))
        assert f'id="perm-{platform_key}"' in html
        assert f'value="{platform_key}|' not in html
        assert "Platform only - cannot be set per user" in html
    finally:
        db.close()
        engine.dispose()
