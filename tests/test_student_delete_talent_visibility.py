"""M15 Part 1: Student integrity / Talent visibility after permanent delete.

Verifies independently that a permanently force-deleted Student no longer
survives in any Student-owned Talent table (frozen population membership,
assessments, competency results, Review Candidate, Official Identification,
Educator Input, assessment audit) and therefore cannot appear as a current/
live Student in any Talent operational surface. Also locks down the
create-only blockers and the service's transaction boundary (it never
commits; rollback still restores the Student).
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from student_academic_service import (
    StudentAcademicError,
    create_placement,
    create_student,
    delete_student,
    force_delete_student_history,
    list_students,
    student_delete_blockers,
)


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")]); db.commit()
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ]); db.commit()
    db.add_all([
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=2000, branch_id=20, academic_year_id=200, grade_level="4", section_name="D", class_status="Current"),
    ]); db.commit()
    yield engine, db
    db.close()


def _student(db, first="Maya"):
    row = create_student(db, school_group_id=1, first_name=first, father_name="Samir", last_name="Haddad", gender="female")
    db.commit()
    return row


def _seed_talent_chain(db, student_id):
    """Insert one row in every Student-owned Talent table (minimal fields).

    Foreign keys are not enforced in this fixture, so dummy cycle/program/
    framework ids are sufficient; only NOT NULL columns are supplied. The
    point is to prove force-delete removes every row keyed by ``student_id``.
    """
    member = models.TalentAssessmentCyclePopulationMember(
        school_group_id=1, cycle_id=1, program_id=1, academic_year_id=100,
        framework_version_id=1, student_id=student_id, academic_placement_id=5001,
        branch_id=10, grade_level="1", section_name="A", population_effective_at=datetime(2026, 9, 1),
    )
    db.add(member); db.flush()

    assessment = models.TalentStudentAssessment(
        school_group_id=1, cycle_id=1, cycle_population_member_id=member.id,
        student_id=student_id, program_id=1, academic_year_id=100, framework_version_id=1,
    )
    db.add(assessment); db.flush()

    db.add(models.TalentStudentCompetencyResult(
        school_group_id=1, assessment_id=assessment.id, cycle_id=1, student_id=student_id,
        program_id=1, academic_year_id=100, framework_version_id=1,
        framework_competency_id=1, rubric_id=1, rubric_level_id=1,
    ))

    candidate = models.TalentReviewCandidate(
        school_group_id=1, cycle_id=1, cycle_population_member_id=member.id,
        student_id=student_id, program_id=1, academic_year_id=100, framework_version_id=1,
        assessment_id=assessment.id, policy_id=1, match_mode="all",
        evaluation_fingerprint="fp", evaluation_snapshot_json="{}",
    )
    db.add(candidate); db.flush()

    db.add(models.TalentOfficialIdentification(
        school_group_id=1, cycle_id=1, cycle_population_member_id=member.id,
        student_id=student_id, program_id=1, academic_year_id=100, framework_version_id=1,
        assessment_id=assessment.id, review_candidate_id=candidate.id, decision="identified",
    ))

    db.add(models.TalentEducatorInput(
        school_group_id=1, student_id=student_id, program_id=1, academic_year_id=100,
        observed_at=datetime(2026, 9, 2), academic_placement_id=5001, branch_id=10,
        grade_level="1", section_name="A", category="observation", content="note",
    ))

    db.add(models.TalentAssessmentAudit(
        school_group_id=1, program_id=1, academic_year_id=100, cycle_id=1,
        framework_version_id=1, assessment_id=assessment.id, cycle_population_member_id=member.id,
        student_id=student_id, resource_type="student_assessment", resource_id=assessment.id,
        action="create", correlation_id="corr",
    ))
    db.commit()


def test_student_delete_blockers_report_talent_history(database):
    _, db = database
    student = _student(db)
    _seed_talent_chain(db, student.id)
    blockers = student_delete_blockers(db, school_group_id=1, student_id=student.id)
    codes = {b["code"] for b in blockers}
    assert {"talent_population", "talent_assessment", "talent_review",
            "official_identification", "educator_input"} <= codes


def test_delete_student_blocks_and_rolls_back_when_talent_history_exists(database):
    _, db = database
    student = _student(db)
    _seed_talent_chain(db, student.id)
    with pytest.raises(StudentAcademicError) as err:
        delete_student(db, school_group_id=1, student_id=student.id)
    assert err.value.code == "student_delete_blocked"
    db.rollback()
    assert db.get(models.Student, student.id) is not None
    assert db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        school_group_id=1, student_id=student.id).count() == 1


def test_force_delete_removes_complete_talent_chain(database):
    _, db = database
    student = _student(db)
    create_placement(db, school_group_id=1, student_id=student.id, branch_id=10,
                     academic_year_id=100, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    _seed_talent_chain(db, student.id)

    force_delete_student_history(db, school_group_id=1, student_id=student.id)
    db.commit()

    assert db.get(models.Student, student.id) is None
    for model in (
        models.TalentOfficialIdentification,
        models.TalentEducatorInput,
        models.TalentReviewCandidate,
        models.TalentAssessmentAudit,
        models.TalentStudentCompetencyResult,
        models.TalentStudentAssessment,
        models.TalentAssessmentCyclePopulationMember,
        models.StudentAcademicPlacement,
        models.StudentExternalIdentifier,
        models.StudentAudit,
    ):
        assert db.query(model).filter_by(school_group_id=1, student_id=student.id).count() == 0, model.__name__


def test_force_deleted_student_absent_from_list_students(database):
    _, db = database
    student = _student(db)
    create_placement(db, school_group_id=1, student_id=student.id, branch_id=10,
                     academic_year_id=100, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    _seed_talent_chain(db, student.id)
    force_delete_student_history(db, school_group_id=1, student_id=student.id)
    db.commit()
    assert [s.id for s in list_students(db, school_group_id=1)] == []


def test_force_delete_does_not_commit_caller_controls_transaction(database):
    _, db = database
    student = _student(db)
    _seed_talent_chain(db, student.id)
    force_delete_student_history(db, school_group_id=1, student_id=student.id)
    # The service never commits: a rollback restores the Student intact.
    db.rollback()
    assert db.get(models.Student, student.id) is not None
    assert db.query(models.TalentStudentAssessment).filter_by(
        school_group_id=1, student_id=student.id).count() == 1


def test_force_delete_is_tenant_scoped(database):
    _, db = database
    mine = _student(db, first="Mine")
    other = create_student(db, school_group_id=2, first_name="Other", father_name="X", last_name="Y", gender="female")
    db.commit()
    _seed_talent_chain(db, mine.id)
    force_delete_student_history(db, school_group_id=1, student_id=mine.id)
    db.commit()
    assert db.get(models.Student, mine.id) is None
    # Cross-tenant Student is untouched.
    assert db.get(models.Student, other.id) is not None
