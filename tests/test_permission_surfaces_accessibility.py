"""Template-source accessibility checks for the permission-management surfaces
(Role Packages / School Overrides and User Permission Exceptions)."""
import re

from tests import permission_audit_support as support

ROLE_TPL = (support.ROOT / "templates" / "system_configuration_role_permissions.html").read_text(encoding="utf-8")
USER_TPL = (support.ROOT / "templates" / "edit_user.html").read_text(encoding="utf-8")


def _labels(text):
    return re.findall(r"<label\b.*?</label>", text, flags=re.S)


def test_no_static_aria_expanded_on_disclosure_widgets():
    for text in (ROLE_TPL, USER_TPL):
        assert "aria-expanded" not in text  # native <details>/<summary> owns the state


def test_focus_visible_styles_exist_for_interactive_controls():
    assert ":focus-visible" in ROLE_TPL
    assert re.search(r"\.reset-override-btn:focus-visible", ROLE_TPL)
    assert re.search(r"\.exc-btn:focus-visible", USER_TPL)
    assert re.search(r"summary:focus-visible", USER_TPL)


def test_no_button_link_or_select_is_nested_inside_a_label():
    for text in (ROLE_TPL, USER_TPL):
        for label in _labels(text):
            assert not re.search(r"<(button|a|select|textarea)\b", label), label[:120]


def test_native_controls_and_accessible_names():
    # checkboxes are native inputs labelled by their <label for=...>
    assert re.search(r'<input type="checkbox" id="pkg-', ROLE_TPL)
    assert re.search(r'<label class="permission-check[^"]*" for="pkg-', ROLE_TPL)
    assert 'for="ovr-' in ROLE_TPL
    # reset buttons name the permission they act on
    assert re.search(r'class="reset-override-btn"[^>]*aria-label="Reset ', ROLE_TPL)
    # exception buttons are real <button> elements with server-rendered pressed state + reset name
    buttons = re.findall(r"<button class=\"exc-btn[^>]*>", USER_TPL)
    assert buttons
    assert all("type=\"submit\"" in b for b in buttons)
    assert any("aria-pressed=" in b for b in buttons)
    assert all("aria-label=" in b for b in buttons if "is-reset" in b)
    assert 'aria-labelledby="user-exceptions-title"' in USER_TPL


def test_state_is_not_conveyed_by_colour_alone():
    # Effective/Source/User Exception are spelled out as text; pressed buttons get a check glyph.
    assert "Effective:" in USER_TPL and '"Allow" if permission.effective else "Deny"' in USER_TPL
    assert 'content: "\\2713' in USER_TPL
    assert "Standard" in ROLE_TPL and "Override" in ROLE_TPL and "Effective" in ROLE_TPL


def _assert_state_carried_by_text(html):
    """Every colour-classed state element must spell its state as visible text, and the
    colour class must agree with that text (colour is never the sole carrier)."""
    cells = re.findall(r'<dd class="is-(allow|deny)">([^<]*)</dd>', html)
    assert cells, "no colour-classed state cell rendered"
    for cls, text in cells:
        assert text.strip() == cls.capitalize(), (cls, text)
    for badge in re.findall(r'<b class="(?:override|standard)-badge">([^<]*)</b>', html):
        assert re.search(r"(Allow|Deny)", badge), badge


def test_allow_and_deny_labels_are_text_not_only_colour_classes():
    """Rendered pages (real services/templates): state is visible text, not colour alone."""
    from tests import test_role_permissions_ui_split as role_ui
    from tests import test_user_exceptions_ui as user_ui

    # User Exceptions panel: Deny exception over a role Allow.
    engine, _Session, ids, db = user_ui._setup()
    try:
        actor = db.get(user_ui.models.User, ids["acting_admin_id"])
        user_ui._change(db, actor, ids["user_a_id"], f"{user_ui.KEY}|deny")
        panel = user_ui._panel(user_ui._html(db, actor, ids["user_a_id"]))
        _assert_state_carried_by_text(panel)
        row = user_ui._row(user_ui._html(db, actor, ids["user_a_id"]), user_ui.KEY)
        assert re.search(r"Effective:</dt><dd class=\"is-deny\">Deny</dd>", row)
        assert re.search(r"User Exception:</dt><dd>Deny</dd>", row)
        assert re.search(r">Allow</button>", row) and re.search(r">Deny</button>", row)
    finally:
        db.close(); engine.dispose()

    # School Overrides: an override Deny and a standard-package Allow are both spelled out.
    engine, db = role_ui._make_db()
    try:
        school = role_ui._school(db, "Accessibility School")
        owner = role_ui._platform_owner(db)
        db.add(role_ui.models.RolePermission(
            school_group_id=school.id, role=role_ui.ADMIN, permission_key="subjects.view",
            is_allowed=False, updated_by_user_id="seed",
        ))
        db.flush()
        body = role_ui._render_overrides(db, owner, school.id)
        assert "School Override: Deny" in body
        assert "Standard Role Package: Allow / Effective: Deny" in body
        assert "Using Standard Role Package (Allow)" in body
        assert re.search(r'<b class="override-badge">School Override: (Allow|Deny)</b>', body)
        assert re.search(r'<b class="standard-badge">Using Standard Role Package \((Allow|Deny)\)</b>', body)
    finally:
        db.close(); engine.dispose()


def test_state_text_assertion_fails_when_only_colour_remains():
    """Guard: the helper rejects a colour class with no/contradicting text."""
    import pytest

    _assert_state_carried_by_text('<dd class="is-deny">Deny</dd>')
    with pytest.raises(AssertionError):
        _assert_state_carried_by_text('<dd class="is-deny"></dd>')
    with pytest.raises(AssertionError):
        _assert_state_carried_by_text('<dd class="is-deny">Allow</dd>')


def test_narrow_width_collapses_to_a_single_column_without_horizontal_overflow():
    assert re.search(r"@media \(max-width: 1050px\) \{[^}]*grid-template-columns: 1fr", ROLE_TPL)
    assert re.search(r"@media \(max-width: 520px\) \{[^}]*flex-direction: column", USER_TPL)
    assert "minmax(0, 1fr)" in ROLE_TPL  # min-content overflow guard on the grid tracks
    assert "overflow-wrap: anywhere" in USER_TPL


def test_select_all_and_clear_all_only_exist_in_role_packages_mode():
    overrides_start = ROLE_TPL.index("Managing School (management target only)")
    for marker in ("data-permission-select-all", "data-permission-clear-all"):
        positions = [m.start() for m in re.finditer(re.escape(marker), ROLE_TPL)]
        rendered = [pos for pos in positions if ROLE_TPL[ROLE_TPL.rfind("<", 0, pos):pos].startswith("<button")]
        assert rendered and all(pos < overrides_start for pos in rendered), marker
