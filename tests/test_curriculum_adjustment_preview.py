from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

import models
from curriculum_adjustment_preview_service import (
    CurriculumAdjustmentPreviewRequest,
    build_curriculum_adjustment_preview,
    is_curriculum_adjustment_preview_current,
)
from database import Base


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    db.add_all([
        models.SchoolGroup(id=1, name="Group One"), models.SchoolGroup(id=2, name="Group Two"),
    ])
    db.commit()
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="Branch A"),
        models.Branch(id=20, school_group_id=2, name="Branch B"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026"),
    ])
    db.commit()
    db.add_all([
        models.Subject(id=1000, subject_code="SOC3", subject_name="Social Studies", weekly_hours=1, grade=3, branch_id=10, academic_year_id=100),
        models.Subject(id=1001, subject_code="WEL3", subject_name="Well Being", weekly_hours=1, grade=3, branch_id=10, academic_year_id=100),
        models.Subject(id=2000, subject_code="SOC3", subject_name="Social Studies", weekly_hours=1, grade=3, branch_id=20, academic_year_id=200),
        models.Subject(id=2001, subject_code="WEL3", subject_name="Well Being", weekly_hours=1, grade=3, branch_id=20, academic_year_id=200),
        models.PlanningSection(id=3000, grade_level="3", section_name="A", class_status="Current", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=3001, grade_level="3", section_name="B", class_status="New", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=3002, grade_level="4", section_name="A", class_status="Current", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=3003, grade_level="3", section_name="C", class_status="Closed", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=4000, grade_level="3", section_name="A", class_status="Current", branch_id=20, academic_year_id=200),
        models.Teacher(id=5000, teacher_id="T1", first_name="Source", last_name="One", max_hours=24, branch_id=10, academic_year_id=100),
        models.Teacher(id=5001, teacher_id="T2", first_name="Target", last_name="One", max_hours=24, branch_id=10, academic_year_id=100),
        models.Teacher(id=5002, teacher_id="T3", first_name="Target", last_name="Two", max_hours=24, branch_id=10, academic_year_id=100),
    ])
    db.commit()
    for section_id in (3000, 3001):
        db.add_all([
            models.PlanningSubjectDemand(branch_id=10, academic_year_id=100, planning_section_id=section_id, subject_code="SOC3", weekly_periods=1, is_active=True),
            models.PlanningSubjectDemand(branch_id=10, academic_year_id=100, planning_section_id=section_id, subject_code="WEL3", weekly_periods=1, is_active=True),
        ])
    db.add_all([
        models.TeacherSectionAssignment(teacher_id=5000, planning_section_id=3000, subject_code="SOC3"),
        models.TeacherSectionAssignment(teacher_id=5001, planning_section_id=3000, subject_code="WEL3"),
        models.TeacherSectionAssignment(teacher_id=5002, planning_section_id=3001, subject_code="SOC3"),
        models.TeacherSectionAssignment(teacher_id=5002, planning_section_id=3001, subject_code="WEL3"),
    ])
    db.commit()


def _request(scope_type, **kwargs):
    return CurriculumAdjustmentPreviewRequest(
        scope_type=scope_type, source_subject_code="SOC3", target_subject_code="WEL3",
        requested_transfer_periods=kwargs.pop("requested_transfer_periods", 1), **kwargs
    )


def _preview(db, request):
    return build_curriculum_adjustment_preview(
        db, school_group_id=1, branch_id=10, academic_year_id=100, request=request
    )


def test_grade_scope_is_current_new_only_and_increases_target_demand():
    db = _db(); _seed(db)
    result = _preview(db, _request("grade", grade_level="3"))
    assert [item["section"]["id"] for item in result["sections"]] == [3000, 3001]
    assert all(item["source"]["current_weekly_periods"] == 1 for item in result["sections"])
    assert all(item["source"]["after_weekly_periods"] == 0 for item in result["sections"])
    assert all(item["target"]["after_weekly_periods"] == 2 for item in result["sections"])


def test_partial_transfer_uses_requested_amount_not_catalog_default():
    db = _db(); _seed(db)
    source = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=3000, subject_code="SOC3"
    ).one()
    source.weekly_periods = 2
    db.commit()
    result = _preview(db, _request("selected_sections", section_ids=(3000,)))
    item = result["sections"][0]
    assert (item["source"]["current_weekly_periods"], item["source"]["after_weekly_periods"]) == (2, 1)
    assert (item["target"]["current_weekly_periods"], item["target"]["after_weekly_periods"]) == (1, 2)
    assert item["released_weekly_periods"] == 1


def test_transfer_must_be_positive_and_cannot_exceed_section_source_demand():
    db = _db(); _seed(db)
    with pytest.raises(ValueError) as exc:
        _preview(db, _request("selected_sections", section_ids=(3000,), requested_transfer_periods=0))
    assert getattr(exc.value, "code", None) == "invalid_transfer_periods"
    result = _preview(db, _request("selected_sections", section_ids=(3000,), requested_transfer_periods=2))
    assert {item["code"] for item in result["blockers"]} == {"transfer_exceeds_source_demand"}


def test_selected_section_scope_changes_only_requested_section():
    db = _db(); _seed(db)
    result = _preview(db, _request("selected_sections", section_ids=(3001,)))
    assert [item["section"]["id"] for item in result["sections"]] == [3001]


def test_all_active_uses_scope_omits_inactive_and_other_tenant_uses():
    db = _db(); _seed(db)
    row = db.query(models.PlanningSubjectDemand).filter_by(planning_section_id=3001, subject_code="SOC3").one()
    row.is_active = False; row.weekly_periods = 0; db.commit()
    result = _preview(db, _request("all_active_uses"))
    assert [item["section"]["id"] for item in result["sections"]] == [3000]
    assert all(item["section"]["id"] != 4000 for item in result["sections"])


def test_inactive_source_demand_is_a_section_blocker():
    db = _db(); _seed(db)
    row = db.query(models.PlanningSubjectDemand).filter_by(planning_section_id=3000, subject_code="SOC3").one()
    row.is_active = False; row.weekly_periods = 0; db.commit()
    result = _preview(db, _request("selected_sections", section_ids=(3000,)))
    assert result["sections"][0]["released_weekly_periods"] == 0
    assert result["sections"][0]["current_source_teacher"]["teacher"]["id"] == 5000
    assert {item["code"] for item in result["blockers"]} == {"source_demand_inactive"}


def test_teacher_suggestions_preserve_different_current_teachers_per_section():
    db = _db(); _seed(db)
    result = _preview(db, _request("grade", grade_level="3"))
    by_id = {item["section"]["id"]: item for item in result["sections"]}
    assert by_id[3000]["current_source_teacher"]["teacher"]["id"] == 5000
    assert by_id[3000]["current_target_teacher"]["teacher"]["id"] == 5001
    assert by_id[3001]["current_target_teacher"]["teacher"]["id"] == 5002
    assert by_id[3000]["suggested_teacher_options"][0]["reason"] == "current_target_teacher"


def test_capacity_excess_is_reported_without_assigning_teacher():
    db = _db(); _seed(db)
    teacher = db.get(models.Teacher, 5002); teacher.max_hours = 1
    db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.planning_section_id == 3001,
        models.TeacherSectionAssignment.subject_code == "SOC3",
    ).delete()
    db.commit()
    result = _preview(db, _request("selected_sections", section_ids=(3001,)))
    assert "teacher_capacity_exceeded" in {item["code"] for item in result["blockers"]}
    assert result["sections"][0]["current_target_teacher"]["teacher"]["id"] == 5002


def test_branch_year_isolation_rejects_mismatched_school_group():
    db = _db(); _seed(db)
    try:
        build_curriculum_adjustment_preview(
            db, school_group_id=2, branch_id=10, academic_year_id=100,
            request=_request("grade", grade_level="3"),
        )
        assert False, "expected scope mismatch"
    except ValueError as exc:
        assert getattr(exc, "code", None) == "scope_mismatch"


def test_preview_fingerprint_changes_when_authority_changes():
    db = _db(); _seed(db)
    request = _request("selected_sections", section_ids=(3000,))
    result = _preview(db, request)
    assert is_curriculum_adjustment_preview_current(
        db, expected_fingerprint=result["preview_fingerprint"], school_group_id=1,
        branch_id=10, academic_year_id=100, request=request,
    )
    demand = db.query(models.PlanningSubjectDemand).filter_by(planning_section_id=3000, subject_code="WEL3").one()
    demand.weekly_periods = 2; db.commit()
    assert not is_curriculum_adjustment_preview_current(
        db, expected_fingerprint=result["preview_fingerprint"], school_group_id=1,
        branch_id=10, academic_year_id=100, request=request,
    )


def test_preview_is_read_only():
    db = _db(); _seed(db)
    before = db.query(models.PlanningSubjectDemand).count(), db.query(models.TeacherSectionAssignment).count()
    result = _preview(db, _request("grade", grade_level="3"))
    assert result["preview_only"] is True
    assert result["timetable_impact"]["published_history_untouched"] is True
    assert before == (db.query(models.PlanningSubjectDemand).count(), db.query(models.TeacherSectionAssignment).count())
