from pathlib import Path

from ui_shell import _build_nav_items


def test_academic_planning_groups_existing_routes_without_changing_permissions():
    allowed = {"dashboard.view", "subjects.view", "teachers.view", "planning.view"}
    items = _build_nav_items(
        "/subjects/",
        can=lambda key: key in allowed,
        can_any=lambda *keys: any(key in allowed for key in keys),
    )
    academic = next(item for item in items if item["label"] == "Academic Planning")
    assert academic["active"] is True
    assert [(child["label"], child["href"]) for child in academic["children"]] == [
        ("Dashboard", "/dashboard"),
        ("Subjects", "/subjects/"),
        ("Teachers", "/teachers/"),
        ("Planning", "/planning/"),
    ]
    assert next(child for child in academic["children"] if child["label"] == "Subjects")["active"] is True


def test_academic_planning_does_not_leak_a_denied_child_route():
    items = _build_nav_items(
        "/subjects/",
        can=lambda key: key == "subjects.view",
        can_any=lambda *keys: "subjects.view" in keys,
    )
    academic = next(item for item in items if item["label"] == "Academic Planning")
    assert [(child["label"], child["href"]) for child in academic["children"]] == [
        ("Subjects", "/subjects/"),
    ]
    assert academic["href"] == "/subjects/"


def test_configuration_hub_is_a_searchable_tree_not_a_card_dashboard():
    source = Path("templates/system_configuration_hub.html").read_text(encoding="utf-8")
    assert 'data-config-search' in source
    assert 'class="config-tree"' in source
    assert 'class="config-node" open' in source
    for label in (
        "Organization", "Academic Setup", "Users & Access", "Talent &amp; Potential",
        "Programs", "Rubrics &amp; Competencies", "Evaluation Periods", "Criteria / KPI",
    ):
        assert label in source
    assert "config-module-card" not in source
    assert "config-stat-card" not in source


def test_sidebar_uses_native_expandable_tree_groups():
    source = Path("templates/base.html").read_text(encoding="utf-8")
    assert 'details class="sidebar-nav-group"' in source
    assert '<summary class="sidebar-link' in source


def test_light_sidebar_icons_override_the_legacy_white_icon_rule():
    css = Path("static/css/app-shell.css").read_text(encoding="utf-8")
    light_layer = css[css.index("/* Light, objective-based navigation tree. */"):]
    assert '.app-sidebar .sidebar-link svg[data-tis-icon]' in light_layer
    assert 'color: #1767d7 !important' in light_layer
    for icon_name in ("planning", "sparkles", "calendar", "clipboard-check", "notifications"):
        assert f'data-tis-icon="{icon_name}"' in light_layer
