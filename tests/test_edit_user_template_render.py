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


def test_edit_user_page_renders_all_three_controls_reason_text_and_inert_platform_only_row():
    engine, Session = _make_db()
    ids = _seed(Session)
    db = Session()
    try:
        acting_admin = db.query(models.User).get(ids["acting_admin_id"])

        # Produce a Deny-override case: dashboard.view is role-granted by
        # default for Administrator, so denying it exercises the
        # "User override: Deny (overrides role grant)" reason branch.
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

        # --- All three Inherit/Allow/Deny controls present for a normal
        # (non-locked) permission, e.g. dashboard.view. ---
        assert 'name="permission_decisions" value="inherit"' in html
        assert 'name="permission_decisions" value="allow"' in html
        assert 'name="permission_decisions" value="deny"' in html
        assert '<input type="radio" name="permission_decisions" value="inherit"' in html
        assert '<input type="radio" name="permission_decisions" value="allow"' in html
        assert '<input type="radio" name="permission_decisions" value="deny"' in html

        # --- Deny-override reason text (dashboard.view, denied above). ---
        assert 'User override: Deny' in html
        assert 'overrides role grant' in html

        # --- Allow-inherited (role-granted, no override) reason text: at
        # least one other permission the Administrator role grants by
        # default must show the plain inherited-grant reason. ---
        assert 'Inherited from role (granted)' in html

        # --- Platform-only / non-assignable keys render as inert: no live
        # radio control, only the exact disabled markup the template uses. ---
        platform_key = next(iter(permission_registry.PLATFORM_ONLY_PERMISSION_KEYS))
        assert f'value="{platform_key}"' in html
        assert 'Platform only</span>' in html
        assert 'aria-disabled="true"' in html
        assert '<span class="override-choice">Allow (unavailable)</span>' in html
        assert '<span class="override-choice">Deny (unavailable)</span>' in html
    finally:
        db.close()
        engine.dispose()
