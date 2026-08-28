"""Stage 3 tests for the Subject Scheduling Rules Timetable Settings UI."""
import re
from types import SimpleNamespace

import pytest
from starlette.requests import Request

import main
import models
import subject_distribution_rules_ui as ui
from subject_distribution_rules import resolve_subject_distribution_rule
from test_timetable_versioning import db  # noqa: F401 - shared isolated database


def _request(path):
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET", "path": path,
        "raw_path": path.encode("utf-8"), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80), "client": ("testclient", 50000),
        "root_path": "", "app": main.app,
    })


def _add_subject(db, *, id, grade, code, weekly, name=None, branch_id=10, academic_year_id=100):
    db.add(models.Subject(
        id=id, subject_code=code, subject_name=name or code.title(), weekly_hours=weekly,
        grade=grade, branch_id=branch_id, academic_year_id=academic_year_id,
    ))
    db.commit()


def test_table_loads_subjects_from_planning_and_weekly_is_authoritative(db):
    rows = ui.list_subject_scheduling_rows(db, 10, 100)
    assert len(rows) == 1
    row = rows[0]
    assert row["grade_level"] == "1" and row["subject_code"] == "MAT"
    assert row["weekly_periods"] == 4
    assert row["status_label"] == "Using Default Scheduling Rules"


def test_creating_grade_level_rule(db):
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "1", "single_count": "2"},
        teaching_day_count=2, actor_user_id="U1",
    )
    assert errors == []
    row = db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade", grade_level="1", subject_code="MAT",
    ).one()
    assert row.block_count == 1 and row.single_count == 2
    rows = ui.list_subject_scheduling_rows(db, 10, 100)
    assert rows[0]["status_label"] == "Configured"
    assert rows[0]["distribution_summary"] == "1 double block + 2 singles"


def test_editing_existing_rule_updates_same_row_not_a_duplicate(db):
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "1", "single_count": "2"},
        teaching_day_count=2, actor_user_id="U1",
    )
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "0", "single_count": "4"},
        teaching_day_count=2, actor_user_id="U1",
    )
    rows = db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade", grade_level="1", subject_code="MAT",
    ).all()
    assert len(rows) == 1
    assert rows[0].block_count == 0 and rows[0].single_count == 4


def test_invalid_arithmetic_rejected(db):
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "1", "single_count": "1"},
        teaching_day_count=2, actor_user_id="U1",
    )
    assert any(error["code"] == "distribution_total_mismatch" for error in errors)
    assert db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade",
    ).count() == 0


def test_reset_to_default_removes_grade_rule(db):
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "1", "single_count": "2"},
        teaching_day_count=2, actor_user_id="U1",
    )
    assert ui.reset_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
    ) is True
    assert db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade",
    ).count() == 0
    rows = ui.list_subject_scheduling_rows(db, 10, 100)
    assert rows[0]["status_label"] == "Using Default Scheduling Rules"


def test_section_override_creation_and_update(db):
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "0", "single_count": "4"},
        teaching_day_count=2, actor_user_id="U1",
    )
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=2000, fields={"block_count": "1", "single_count": "2"},
        teaching_day_count=2, actor_user_id="U1",
    )
    assert errors == []
    section_resolved = resolve_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT", section_id=2000,
    )
    other_section_resolved = resolve_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT", section_id=2001,
    )
    assert section_resolved["source_scope_level"] == "section"
    assert section_resolved["block_count"] == 1
    assert other_section_resolved["source_scope_level"] == "grade"
    assert other_section_resolved["block_count"] == 0

    # Editing the same section override updates the same row.
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=2000, fields={"block_count": "0", "single_count": "4"},
        teaching_day_count=2, actor_user_id="U1",
    )
    assert db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="section", section_id=2000,
    ).count() == 1

    assert ui.clear_section_override(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT", section_id=2000,
    ) is True
    assert db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="section",
    ).count() == 0


def test_field_inheritance_unset_section_field_falls_back_to_grade(db):
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="1", subject_code="MAT", block_count=0, single_count=4,
        min_teaching_days=2,
    ))
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="section",
        grade_level="1", subject_code="MAT", section_id=2000,
        block_count=0, single_count=4, min_teaching_days=None,
    ))
    db.commit()
    resolved = resolve_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT", section_id=2000,
    )
    assert resolved["min_teaching_days"] == 2


def test_pe_normal_configuration(db):
    _add_subject(db, id=3001, grade=1, code="PE", weekly=2)
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="PE",
        section_id=None,
        fields={
            "block_count": "0", "single_count": "2", "spread_distinct_days": "1",
            "max_periods_per_day": "1", "strictness": "hard",
        },
        teaching_day_count=2, actor_user_id="U1",
    )
    assert errors == []
    rows = {row["subject_code"]: row for row in ui.list_subject_scheduling_rows(db, 10, 100)}
    assert rows["PE"]["distribution_summary"] == "2 singles"
    assert rows["PE"]["max_periods_per_day"] == 1


def test_pe_swimming_block_configuration(db):
    _add_subject(db, id=3001, grade=1, code="PE", weekly=2)
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="PE",
        section_id=None,
        fields={"block_count": "1", "block_length": "2", "single_count": "0"},
        teaching_day_count=2, actor_user_id="U1",
    )
    assert errors == []
    rows = {row["subject_code"]: row for row in ui.list_subject_scheduling_rows(db, 10, 100)}
    assert rows["PE"]["distribution_summary"] == "1 double block"


def test_english_8_period_example(db):
    _add_subject(db, id=3001, grade=1, code="ENG", weekly=8)
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="ENG",
        section_id=None,
        fields={
            "block_count": "2", "block_length": "2", "single_count": "4",
            "min_teaching_days": "5", "max_periods_per_day": "2",
        },
        teaching_day_count=5, actor_user_id="U1",
    )
    assert errors == []
    rows = {row["subject_code"]: row for row in ui.list_subject_scheduling_rows(db, 10, 100)}
    assert rows["ENG"]["distribution_summary"] == "2 double blocks + 4 singles"
    assert rows["ENG"]["min_teaching_days"] == 5
    assert rows["ENG"]["max_periods_per_day"] == 2


def test_copy_rules_from_grade_skips_invalid_and_missing_subjects(db):
    # Subject codes are grade-specific in this schema, so matching subjects
    # is name-based across grades (e.g. two different "Mathematics" codes).
    _add_subject(db, id=3001, grade=1, code="ENG1", weekly=5, name="English")
    db.query(models.Subject).filter_by(id=3000).update({"subject_name": "Mathematics"})
    db.commit()
    _add_subject(db, id=3002, grade=2, code="MAT2", weekly=4)
    db.query(models.Subject).filter_by(id=3002).update({"subject_name": "Mathematics"})
    db.commit()
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "0", "single_count": "4"},
        teaching_day_count=2, actor_user_id="U1",
    )
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="ENG1",
        section_id=None, fields={"block_count": "1", "single_count": "3"},
        teaching_day_count=2, actor_user_id="U1",
    )
    result = ui.copy_grade_rules(
        db, branch_id=10, academic_year_id=100, source_grade="1", target_grade="2",
        teaching_day_count=2, actor_user_id="U1",
    )
    assert "Mathematics" in result["applied"]
    assert any(item.startswith("English") for item in result["skipped"])
    target_row = db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade", grade_level="2", subject_code="MAT2",
    ).one()
    assert target_row.block_count == 0 and target_row.single_count == 4


def test_tenant_branch_isolation_no_cross_branch_leakage(db):
    ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None, fields={"block_count": "0", "single_count": "4"},
        teaching_day_count=2, actor_user_id="U1",
    )
    other_branch_rows = ui.list_subject_scheduling_rows(db, 20, 200)
    assert other_branch_rows == []
    assert db.query(models.SubjectDistributionRule).filter_by(branch_id=20).count() == 0


def test_existing_timetable_settings_route_still_renders(db, monkeypatch):
    user = db.query(models.User).filter_by(user_id="U1").one()
    user.scope_school_group_id = 1
    user.scope_branch_id = 10
    user.scope_academic_year_id = 100
    monkeypatch.setattr(main, "_get_configuration_access", lambda request, session: (user, None))
    monkeypatch.setattr(main.auth, "has_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.auth, "has_any_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.auth, "is_platform_user", lambda *args, **kwargs: False)

    response = main.system_configuration_timetable_settings(
        _request("/system-configuration/timetable-settings"), db
    )
    assert response.status_code == 200
    html = response.body.decode("utf-8")
    assert "Subject Scheduling Rules" in html
    assert "Non-Teaching Blocks" in html


def test_professional_grade_first_editor_contract_renders(db, monkeypatch):
    user = db.query(models.User).filter_by(user_id="U1").one()
    user.scope_school_group_id = 1
    user.scope_branch_id = 10
    user.scope_academic_year_id = 100
    monkeypatch.setattr(main, "_get_configuration_access", lambda request, session: (user, None))
    monkeypatch.setattr(main.auth, "has_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.auth, "has_any_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.auth, "is_platform_user", lambda *args, **kwargs: False)
    monkeypatch.setattr(main.auth, "get_allowed_permission_keys", lambda *args, **kwargs: {"timetable.manage_settings"})

    response = main.system_configuration_timetable_settings(
        _request("/system-configuration/timetable-settings"), db
    )
    html = response.body.decode("utf-8")
    assert 'id="grade-filter-select"' in html
    assert 'id="subject-filter-search"' in html
    assert 'id="subject-rules-table-wrap" hidden' in html
    assert '<dialog id="subject-rule-dialog">' in html
    assert '<dialog id="subject-rule-dialog" open' not in html
    dialog_css = re.search(r"#subject-rule-dialog\s*\{(?P<rules>.*?)\}", html, re.DOTALL)
    assert dialog_css is not None
    assert "display:" not in dialog_css.group("rules")
    assert "#subject-rule-dialog[open]" not in html
    assert "dialog.showModal()" in html
    assert 'dialog.setAttribute("open", "open")' in html
    assert "titleEl.textContent = subjectName" in html
    assert "fillFormFromRule(effective, weekly)" in html
    assert "gradeInput.value = grade" in html
    assert "subjectInput.value = subject" in html
    assert "weeklyDisplay.textContent = String(weekly)" in html
    assert "dialog.close()" in html
    assert 'dialog.removeAttribute("open")' in html
    assert "Double Blocks" in html and "Single Sessions" in html
    assert 'class="session-structure-grid"' in html
    assert html.count("session-control") >= 2
    assert 'class="rule-summary-pill session-summary"' in html
    assert '"Configured " + configured + " of " + weeklyRequired + " periods"' in html
    assert "Separate Sessions" in html and "Consecutive Double Block" in html
    assert "Choose as many conditions as this subject needs." in html
    assert "Advanced / Legacy Subject Mappings" in html
    assert "name=\"block_length\" value=\"2\"" in html
    assert "rule_block_length" not in html


def test_multiple_conditions_persist_together(db):
    errors = ui.save_subject_distribution_rule(
        db, branch_id=10, academic_year_id=100, grade_level="1", subject_code="MAT",
        section_id=None,
        fields={
            "block_count": "1", "single_count": "2",
            "require_daily_coverage": "always", "spread_distinct_days": "1",
            "avoid_consecutive": "1", "max_periods_per_day": "2",
            "min_teaching_days": "2", "strictness": "hard",
        },
        teaching_day_count=2, actor_user_id="U1",
    )
    assert errors == []
    row = db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade", subject_code="MAT",
    ).one()
    assert row.require_daily_coverage == "always"
    assert row.spread_distinct_days is True
    assert row.avoid_consecutive is True
    assert row.max_periods_per_day == 2
    assert row.min_teaching_days == 2
    assert row.strictness == "hard"


def test_save_route_persists_rule_end_to_end(db, monkeypatch):
    user = db.query(models.User).filter_by(user_id="U1").one()
    user.scope_school_group_id = 1
    user.scope_branch_id = 10
    user.scope_academic_year_id = 100
    monkeypatch.setattr(main.auth, "get_current_user", lambda request, session: user)
    monkeypatch.setattr(main.auth, "has_permission", lambda *args, **kwargs: True)

    response = main.save_subject_scheduling_rule(
        _request("/system-configuration/timetable-settings/subject-rules"),
        grade_level="1", subject_code="MAT", section_id="",
        block_length="2", block_count="1", single_count="2",
        min_teaching_days="", max_periods_per_day="", require_daily_coverage="auto",
        spread_distinct_days="1", avoid_consecutive="1", min_day_gap="", strictness="soft",
        return_to="/system-configuration/timetable-settings", db=db,
    )
    assert response.status_code == 302
    assert "notice=" in response.headers["location"]
    row = db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade", grade_level="1", subject_code="MAT",
    ).one()
    assert row.block_count == 1 and row.single_count == 2


def test_save_route_rejects_invalid_arithmetic_with_error_redirect(db, monkeypatch):
    user = db.query(models.User).filter_by(user_id="U1").one()
    user.scope_school_group_id = 1
    user.scope_branch_id = 10
    user.scope_academic_year_id = 100
    monkeypatch.setattr(main.auth, "get_current_user", lambda request, session: user)
    monkeypatch.setattr(main.auth, "has_permission", lambda *args, **kwargs: True)

    response = main.save_subject_scheduling_rule(
        _request("/system-configuration/timetable-settings/subject-rules"),
        grade_level="1", subject_code="MAT", section_id="",
        block_length="2", block_count="1", single_count="1",
        min_teaching_days="", max_periods_per_day="", require_daily_coverage="auto",
        spread_distinct_days="1", avoid_consecutive="1", min_day_gap="", strictness="soft",
        return_to="/system-configuration/timetable-settings", db=db,
    )
    assert response.status_code == 302
    assert "error=" in response.headers["location"]
    assert db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade",
    ).count() == 0
