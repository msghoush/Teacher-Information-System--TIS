import asyncio
from types import SimpleNamespace

import pytest

import models
from routers import timetable as timetable_router
from timetable_logic import build_time_slots, build_timetable_workspace_payload
from timetable_readiness_service import TimetableReadinessService
from timetable_slot_service import build_canonical_slot_projection
from timetable_version_service import TimetableVersionError, create_manual_draft, mutate_draft_placement
from test_timetable_versioning import db  # noqa: F401 - focused shared fixture
from test_timetable_stage2_routes import _request


def _project(blocks=None, days=None, slots=None, periods=2):
    slots = slots or build_time_slots(periods, 45, "08:00")
    return build_canonical_slot_projection(
        school_group_id=1, branch_id=10, academic_year_id=100,
        working_day_keys=days or ["monday", "tuesday"],
        periods_per_day=periods, period_duration_minutes=45,
        school_start_time="08:00", school_end_time="12:00",
        time_slots=slots, blocks=blocks or [],
    )


def _block(day="monday", start="08:00", end="08:45", label="Assembly"):
    return {"id": 1, "block_type": "assembly", "block_type_label": "Assembly", "label": label,
            "day_key": day, "start_time": start, "end_time": end}


def test_canonical_slot_semantics_are_composed_and_deterministic():
    normal = _project()
    assert normal["slot_map"][("monday", 1)]["schedulable"] is True
    full = _project([_block()])
    assert full["slot_map"][("monday", 1)]["start_time"] == "08:45"
    assert full["slot_map"][("tuesday", 1)]["status"] == "teaching"
    every_day = _project([_block(day="all")])
    assert all(every_day["slot_map"][(day, 1)]["start_time"] == "08:45" for day in ("monday", "tuesday"))
    partial = _project([_block(start="08:15", end="08:30")])
    assert partial["valid"] is False
    assert {issue["code"] for issue in partial["issues"]} == {"invalid_non_teaching_block"}
    assert _project([_block()])["fingerprint"] == full["fingerprint"]
    assert full["periods"] != normal["periods"]


def test_between_period_block_and_all_day_closure():
    slots = [
        {"period_index": 1, "label": "Period 1", "start_time": "08:00", "end_time": "08:45"},
        {"period_index": 2, "label": "Period 2", "start_time": "09:00", "end_time": "09:45"},
    ]
    between = _project([_block(start="08:45", end="09:00", label="Break")], slots=slots)
    assert between["blocks"][0]["start_time"] == "08:45"
    assert between["counts"]["teaching_slots"] == 4
    closure = _project([_block(start="07:00", end="12:00", label="Closure")], days=["monday"])
    assert closure["valid"] is False


def test_readiness_reports_uncovered_then_generation_ready(db):
    service = TimetableReadinessService(db)
    result = service.evaluate(1, 10, 100)
    assert result["status"] == "allocation_incomplete"
    assert result["ready"] is False
    assert "hrt_assignment_invalid" in {item["code"] for item in result["blockers"]}
    assert result["counts"]["uncovered_periods"] == 4

    db.add(models.TeacherSectionAssignment(
        teacher_id=1001, planning_section_id=2001, subject_code="MAT"
    ))
    db.flush()
    ready = service.evaluate(1, 10, 100)
    assert ready["status"] == "generation_ready"
    assert ready["ready"] is True
    assert ready["counts"]["coverage_percent"] == 100
    assert "does not guarantee" in ready["feasibility_notice"]


def test_readiness_scope_and_configuration_fail_closed(db):
    service = TimetableReadinessService(db)
    assert service.evaluate(None, 10, 100)["blockers"][0]["code"] == "missing_scope"
    assert service.evaluate(2, 10, 100)["blockers"][0]["code"] == "scope_mismatch"
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    setting.working_days_csv = ""
    setting.periods_per_day = 0
    result = service.evaluate(1, 10, 100)
    codes = {item["code"] for item in result["blockers"]}
    assert {"working_days_missing", "periods_missing", "no_schedulable_slots"} <= codes


def test_readiness_missing_settings_sections_and_subjects(db):
    db.query(models.TimetableSetting).delete()
    assert "settings_missing" in {
        item["code"] for item in TimetableReadinessService(db).evaluate(1, 10, 100)["blockers"]
    }
    db.rollback()
    db.query(models.TeacherSectionAssignment).delete()
    db.query(models.PlanningSection).delete()
    no_sections = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "sections_missing" in {item["code"] for item in no_sections["blockers"]}
    db.rollback()
    db.query(models.TeacherSectionAssignment).delete()
    db.query(models.Subject).delete()
    no_subjects = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "subjects_missing" in {item["code"] for item in no_subjects["blockers"]}


def test_readiness_valid_hrt_capacity_and_slot_sanity(db):
    db.query(models.TeacherSectionAssignment).delete()
    sections = db.query(models.PlanningSection).order_by(models.PlanningSection.id).all()
    sections[0].homeroom_teacher_id = 1000
    sections[1].homeroom_teacher_id = 1001
    assert TimetableReadinessService(db).evaluate(1, 10, 100)["status"] == "generation_ready"

    db.query(models.Teacher).filter_by(id=1000).one().max_hours = 3
    over_capacity = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "teacher_over_capacity" in {item["code"] for item in over_capacity["blockers"]}

    db.query(models.Teacher).filter_by(id=1000).one().max_hours = 24
    db.query(models.TeacherSectionAssignment).delete()
    db.add_all([
        models.TeacherSectionAssignment(teacher_id=1000, planning_section_id=2000, subject_code="MAT"),
        models.TeacherSectionAssignment(teacher_id=1000, planning_section_id=2001, subject_code="MAT"),
    ])
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    setting.periods_per_day = 3
    slot_result = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "teacher_slot_capacity_insufficient" in {item["code"] for item in slot_result["blockers"]}
    db.query(models.Subject).filter_by(id=3000).one().weekly_hours = 7
    section_result = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "section_capacity_insufficient" in {item["code"] for item in section_result["blockers"]}


def test_readiness_detects_invalid_block_cross_scope_teacher_and_changed_input(db):
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    db.add(models.TimetableNonTeachingBlock(
        timetable_setting_id=setting.id, block_type="break", label="Bad break",
        day_key="tuesday", start_time="08:10", end_time="08:25",
        start_period=1, end_period=1,
    ))
    invalid = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "invalid_non_teaching_block" in {item["code"] for item in invalid["blockers"]}
    db.rollback()

    db.add(models.Teacher(
        id=2000, teacher_id="OTHER", first_name="Other", last_name="Teacher",
        branch_id=20, academic_year_id=200,
    ))
    db.flush()
    db.query(models.TeacherSectionAssignment).filter_by(id=4000).one().teacher_id = 2000
    missing = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "teacher_missing" in {item["code"] for item in missing["blockers"]}
    db.rollback()

    draft = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    db.query(models.Subject).filter_by(id=3000).one().weekly_hours = 5
    changed = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert changed["status"] == "stale_input"
    assert "input_changed" in {item["code"] for item in changed["blockers"]}


def test_blocked_assignment_is_rejected_and_existing_placement_is_preserved_stale(db):
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    db.add(models.TimetableNonTeachingBlock(
        timetable_setting_id=setting.id, block_type="assembly", label="Assembly",
        day_key="monday", start_time="08:10", end_time="08:25",
        start_period=1, end_period=1,
    ))
    db.flush()
    draft = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    with pytest.raises(TimetableVersionError) as exc:
        mutate_draft_placement(
            db, version=draft, planning_section_id=2000, day_key="monday",
            period_index=1, subject_code="MAT", teacher_id=1000,
        )
    assert exc.value.code == "slot_not_schedulable"

    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    db.flush()
    payload = build_timetable_workspace_payload(db, 10, 100)
    assert payload["entries"][0]["status"] == "stale"
    assert db.query(models.TimetableEntry).filter_by(timetable_version_id=draft.id).count() == 1


def test_crafted_route_request_cannot_assign_blocked_slot(db, monkeypatch):
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    db.add(models.TimetableNonTeachingBlock(
        timetable_setting_id=setting.id, block_type="assembly", label="Assembly",
        day_key="monday", start_time="08:10", end_time="08:25",
        start_period=1, end_period=1,
    ))
    db.commit()
    user = SimpleNamespace(user_id="U1", branch_id=10, academic_year_id=100)
    monkeypatch.setattr(timetable_router, "_get_current_user_or_redirect", lambda request, session: (user, None))
    monkeypatch.setattr(timetable_router.auth, "has_any_permission", lambda *args: True)
    response = asyncio.run(timetable_router.assign_timetable_slot(
        _request({"section_id": 2000, "day_key": "monday", "period_index": 1, "subject_code": "MAT"}),
        db,
    ))
    assert response.status_code == 400
    assert db.query(models.TimetableVersion).count() == 0


def test_readiness_ui_has_customer_safe_states_and_no_generate_action():
    source = open("templates/timetable.html", encoding="utf-8").read()
    assert "Ready to Generate" in source
    assert "Not Ready to Generate" in source
    assert "A valid automatic timetable is not guaranteed" in source
    assert 'href="/planning/"' in source
    assert 'href="/system-configuration/timetable-settings"' in source
    assert "/generate" not in source
