from pathlib import Path

import authorization


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "curriculum_adjustment.html").read_text(encoding="utf-8")
PLANNING_TEMPLATE = (ROOT / "templates" / "planning.html").read_text(encoding="utf-8")
SUBJECTS_TEMPLATE = (ROOT / "templates" / "subjects.html").read_text(encoding="utf-8")


def test_curriculum_adjustment_page_and_apply_require_dedicated_permission():
    page_rule = next(
        rule for rule in authorization.PROTECTED_ROUTE_RULES
        if rule.pattern == r"/planning/curriculum-adjustments" and rule.methods == ("GET",)
    )
    apply_rule = next(
        rule for rule in authorization.PROTECTED_ROUTE_RULES
        if rule.pattern == r"/planning/curriculum-adjustments/apply"
    )
    assert page_rule.permission_keys == ("curriculum.adjust",)
    assert apply_rule.permission_keys == ("curriculum.adjust",)
    assert '{% if can_adjust_curriculum %}' in PLANNING_TEMPLATE
    assert '{% if can_adjust_curriculum %}' in SUBJECTS_TEMPLATE


def test_guided_ui_exposes_all_scopes_and_preview_impact_categories():
    for scope in ('value="grade"', 'value="selected_sections"', 'value="all_active_uses"'):
        assert scope in TEMPLATE
    assert "Only Current and New Planning sections" in TEMPLATE
    assert "/planning/curriculum-adjustments/preview" in TEMPLATE
    assert "subject_scheduling_rule_impact" in TEMPLATE
    assert "grouped_legacy_warnings" in TEMPLATE
    assert "Current source teacher" in TEMPLATE
    assert "Current target teacher" in TEMPLATE
    assert "blocker" in TEMPLATE
    assert "warning" in TEMPLATE


def test_teacher_decisions_are_explicit_dropdown_choices():
    assert '<select data-teacher-section="${id}">' in TEMPLATE
    assert '<option value="">Choose a teacher decision</option>' in TEMPLATE
    assert '<option value="unassigned">Leave unassigned</option>' in TEMPLATE
    assert "eligible_for_target&&!option.over_capacity" in TEMPLATE
    assert "Choose a teacher decision for every affected section." in TEMPLATE


def test_apply_uses_preview_revision_handles_refresh_and_never_regenerates():
    assert "preview_fingerprint:state.preview.preview_fingerprint" in TEMPLATE
    assert "data.error==='stale_preview'" in TEMPLATE
    assert "Planning changed while you were reviewing." in TEMPLATE
    assert "teacherDecisions" in TEMPLATE
    assert "/planning/curriculum-adjustments/apply" in TEMPLATE
    assert "fetch('/timetable" not in TEMPLATE
    assert 'href="/timetable/?action=regenerate"' in TEMPLATE


def test_success_state_has_required_summary_and_timetable_actions():
    assert "Curriculum adjustment applied" in TEMPLATE
    assert "affected section" in TEMPLATE
    assert "Draft Timetable" in TEMPLATE
    assert "Go to Timetable" in TEMPLATE
    assert "Regenerate Draft" in TEMPLATE
