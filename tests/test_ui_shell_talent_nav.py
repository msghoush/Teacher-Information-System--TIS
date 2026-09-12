"""Owner correction: Students must appear as the first child under Talent &
Potential for Talent-capable users, with the duplicate standalone top-level
Students sidebar item removed - but a Students-only user (no Talent
permission at all) must keep a standalone Students entry so they are never
locked out."""
from ui_shell import _build_nav_items


def _can_factory(allowed_keys):
    allowed = set(allowed_keys)
    return lambda key: key in allowed


def _can_any_factory(allowed_keys):
    allowed = set(allowed_keys)
    return lambda *keys: any(key in allowed for key in keys)


def test_talent_capable_user_gets_one_students_entry_nested_under_talent():
    allowed = {"students.view", "talent_assessments.view", "talent_analytics.view"}
    items = _build_nav_items(
        "/talent",
        can=_can_factory(allowed),
        can_any=_can_any_factory(allowed),
    )
    top_level_hrefs = [item["href"] for item in items]
    assert "/students/" not in top_level_hrefs, "standalone top-level Students must be removed for Talent-capable users"

    talent_item = next(item for item in items if item["href"] == "/talent")
    child_labels = [child["label"] for child in talent_item["children"]]
    assert child_labels[0] == "Students", "Students must be the first child under Talent & Potential"
    assert child_labels.count("Students") == 1, "Students must appear exactly once"


def test_students_only_user_keeps_standalone_students_entry():
    allowed = {"students.view"}
    items = _build_nav_items(
        "/students",
        can=_can_factory(allowed),
        can_any=_can_any_factory(allowed),
    )
    top_level_hrefs = [item["href"] for item in items]
    assert "/students/" in top_level_hrefs, "a Students-only user must not be locked out of a standalone Students entry"

    talent_item = next((item for item in items if item["href"] == "/talent"), None)
    assert talent_item is None, "a user with no Talent permission at all must not see the Talent nav item"


def test_talent_capable_user_without_students_view_gets_no_students_entry_anywhere():
    # students.view itself must never be weakened: someone with Talent access
    # but explicitly no students.view must not see Students standalone NOR
    # nested (the nested child is itself gated by can("students.view")).
    allowed = {"talent_assessments.view"}
    items = _build_nav_items(
        "/talent",
        can=_can_factory(allowed),
        can_any=_can_any_factory(allowed),
    )
    top_level_hrefs = [item["href"] for item in items]
    assert "/students/" not in top_level_hrefs

    talent_item = next(item for item in items if item["href"] == "/talent")
    child_labels = [child["label"] for child in talent_item["children"]]
    assert "Students" not in child_labels
