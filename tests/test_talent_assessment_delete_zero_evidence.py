"""ADR 0034: Talent Student Assessment delete (zero-evidence exception).

Covers:
- talent_student_assessment_service.assessment_delete_blockers/
  can_delete_assessment/delete_assessment (the real, re-verified dependency
  list: TalentStudentCompetencyResult, TalentReviewCandidate,
  TalentOfficialIdentification, TalentEducatorInput - each carries a direct
  `assessment_id` column in the current schema).
- DELETE /api/talent/assessments/{assessment_id} (routers/talent_assessments.py)
  and the backend-computed "actions" capability field on list/read payloads.
- The new talent_assessments.delete permission key.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_assessments import router
from student_academic_service import create_placement, create_student
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_educator_input_service import add_input
from talent_official_identification_service import record_decision
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level,
    configure_review_candidate_policy, create_competency, create_framework_draft,
    create_program, transition_program, upsert_annual_configuration, upsert_descriptor,
    upsert_rubric,
)
from talent_review_candidate_service import evaluate_review_candidate, mark_reviewed
from talent_student_assessment_service import (
    TalentStudentAssessmentError, assessment_delete_blockers, can_delete_assessment,
    complete_assessment, delete_assessment, set_competency_result, start_assessment,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=2000, branch_id=20, academic_year_id=200, grade_level="1", section_name="A", class_status="Current"),
    ])
    session.commit()
    yield session
    session.close()


def rubric_rule(competency, level):
    return {"rule_type": "rubric_level_at_or_above", "framework_competency_id": competency.id, "rubric_level_id": level.id}


def foundation(session, *, with_policy=False, group_id=1, year_id=100, branch=10, section_id=1000):
    program = create_program(session, school_group_id=group_id, name="Program")
    transition_program(session, school_group_id=group_id, program_id=program.id, target_status="active")
    framework = create_framework_draft(session, school_group_id=group_id, program_id=program.id, title="Framework")
    competencies = []
    for code in ("ONE", "TWO"):
        lineage = create_competency(session, school_group_id=group_id, program_id=program.id, code=code, name=code)
        membership, framework = add_framework_competency(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            competency_id=lineage.id, expected_revision=framework.revision,
        )
        competencies.append(membership)
    _, framework = upsert_rubric(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                                 expected_revision=framework.revision, name="Rubric")
    levels = []
    for code in ("LOW", "HIGH"):
        level, framework = add_rubric_level(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, code=code, label=code.title(),
        )
        levels.append(level)
    for competency in competencies:
        for level in levels:
            _, framework = upsert_descriptor(
                session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                framework_competency_id=competency.id, rubric_level_id=level.id,
                expected_revision=framework.revision, descriptor=f"{competency.id}-{level.id}",
            )
    if with_policy:
        _, framework = configure_review_candidate_policy(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True,
            match_mode="any", description=None, rules=[rubric_rule(competencies[0], levels[0])],
        )
    activate_framework(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    upsert_annual_configuration(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                                is_enabled=True, eligible_grade_levels=["1"])
    student = create_student(session, school_group_id=group_id, first_name="Student", last_name="One")
    create_placement(session, school_group_id=group_id, student_id=student.id, academic_year_id=year_id,
                     branch_id=branch, planning_section_id=section_id, effective_from=datetime(2026, 9, 1))
    cycle = create_cycle(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                         framework_version_id=framework.id, title="Cycle",
                         population_effective_at=datetime(2026, 10, 1))
    open_cycle(session, school_group_id=group_id, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    session.commit()
    member = session.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id, student_id=student.id).one()
    return program, framework, cycle, member, student, competencies, levels


def _user(user_id, *, role="Administrator", scope="ORGANIZATION", group=1, branch=10):
    return models.User(user_id=user_id, username=f"user{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=group, branch_id=branch, academic_year_id=100, is_active=True)


def client(db, current):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


def grant(db, role, *keys, group=1):
    db.add_all([models.RolePermission(school_group_id=group, role=role, permission_key=key, is_allowed=True) for key in keys])
    db.commit()


def deny(db, role, *keys, group=1):
    db.add_all([models.RolePermission(school_group_id=group, role=role, permission_key=key, is_allowed=False) for key in keys])
    db.commit()


# ---------------------------------------------------------------------------
# Service-layer: real, re-verified dependency list.
# ---------------------------------------------------------------------------

def test_zero_evidence_assessment_deletes_and_audits(db):
    _, _, cycle, member, _, _, _ = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    db.commit()
    assert assessment_delete_blockers(db, assessment_id=assessment.id) == []
    assert can_delete_assessment(db, assessment_id=assessment.id) is True
    deleted_id = delete_assessment(db, school_group_id=1, assessment_id=assessment.id)
    db.commit()
    assert deleted_id == assessment.id
    assert db.get(models.TalentStudentAssessment, assessment.id) is None
    audits = db.query(models.TalentAssessmentAudit).filter_by(
        resource_type="student_assessment", resource_id=assessment.id, action="delete",
    ).all()
    assert len(audits) == 1 and audits[0].before_json


def test_delete_rejected_when_competency_results_exist(db):
    _, _, cycle, member, _, competencies, levels = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    set_competency_result(db, school_group_id=1, assessment_id=assessment.id,
                          framework_competency_id=competencies[0].id, rubric_level_id=levels[0].id,
                          expected_revision=assessment.revision)
    db.commit()
    assert "competency results" in assessment_delete_blockers(db, assessment_id=assessment.id)
    assert can_delete_assessment(db, assessment_id=assessment.id) is False
    with pytest.raises(TalentStudentAssessmentError) as exc:
        delete_assessment(db, school_group_id=1, assessment_id=assessment.id)
    assert exc.value.code == "assessment_has_dependents"
    assert "competency results" in exc.value.message
    assert db.get(models.TalentStudentAssessment, assessment.id) is not None


def test_delete_rejected_when_educator_input_exists(db):
    program, _, cycle, member, student, _, _ = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    db.commit()
    add_input(db, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
              observed_at=datetime(2026, 10, 2), category="observation", content="Context note",
              cycle_id=cycle.id, cycle_population_member_id=member.id, assessment_id=assessment.id)
    db.commit()
    blockers = assessment_delete_blockers(db, assessment_id=assessment.id)
    assert "Educator Input" in blockers
    with pytest.raises(TalentStudentAssessmentError) as exc:
        delete_assessment(db, school_group_id=1, assessment_id=assessment.id)
    assert exc.value.code == "assessment_has_dependents"
    assert db.get(models.TalentStudentAssessment, assessment.id) is not None


def test_delete_rejected_when_review_candidate_and_official_identification_exist(db):
    _, _, cycle, member, _, competencies, levels = foundation(db, with_policy=True)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    revision = assessment.revision
    for competency in competencies:
        _, assessment = set_competency_result(
            db, school_group_id=1, assessment_id=assessment.id,
            framework_competency_id=competency.id, rubric_level_id=levels[0].id,
            expected_revision=revision,
        )
        revision = assessment.revision
    completed = complete_assessment(db, school_group_id=1, assessment_id=assessment.id, expected_revision=revision)
    candidate, outcome = evaluate_review_candidate(db, school_group_id=1, assessment_id=completed.id)
    db.commit()
    assert candidate is not None

    # Candidate alone already blocks delete - and blocks it distinctly from the
    # (already-present) competency results, proving Review Candidate is checked
    # independently rather than being masked by the competency-result blocker.
    blockers = assessment_delete_blockers(db, assessment_id=completed.id)
    assert "a Talent Review Candidate record" in blockers

    mark_reviewed(db, school_group_id=1, candidate_id=candidate.id)
    db.commit()
    record_decision(db, school_group_id=1, review_candidate_id=candidate.id, decision="not_identified",
                    organization_authorized=True)
    db.commit()
    blockers = assessment_delete_blockers(db, assessment_id=completed.id)
    assert "an Official Identification decision" in blockers
    with pytest.raises(TalentStudentAssessmentError) as exc:
        delete_assessment(db, school_group_id=1, assessment_id=completed.id)
    assert exc.value.code == "assessment_has_dependents"
    assert db.get(models.TalentStudentAssessment, completed.id) is not None


def test_delete_not_found_is_rejected(db):
    with pytest.raises(TalentStudentAssessmentError) as exc:
        delete_assessment(db, school_group_id=1, assessment_id=999999)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# Router-level: DELETE /api/talent/assessments/{assessment_id}
# ---------------------------------------------------------------------------

def test_delete_route_requires_new_permission_not_manage(db):
    _, _, cycle, member, _, _, _ = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    db.commit()
    actor = _user("1000000001")
    db.add(actor)
    grant(db, "Administrator", "talent_assessments.view", "talent_assessments.manage")
    deny(db, "Administrator", "talent_assessments.delete")
    with client(db, actor) as api:
        response = api.delete(f"/api/talent/assessments/{assessment.id}")
        assert response.status_code == 403
    assert db.get(models.TalentStudentAssessment, assessment.id) is not None


def test_delete_route_succeeds_and_actions_reflect_capability(db):
    _, _, cycle, member, _, _, _ = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    db.commit()
    actor = _user("1000000002")
    db.add(actor)
    grant(db, "Administrator", "talent_assessments.view", "talent_assessments.delete")
    with client(db, actor) as api:
        read = api.get(f"/api/talent/assessments/{assessment.id}")
        assert read.status_code == 200 and "delete" in read.json()["actions"]
        listed = api.get("/api/talent/assessments", params={"cycle_id": cycle.id})
        assert listed.status_code == 200 and "delete" in listed.json()[0]["actions"]
        response = api.delete(f"/api/talent/assessments/{assessment.id}")
        assert response.status_code == 200
        assert response.json() == {"id": assessment.id, "deleted": True}
    assert db.get(models.TalentStudentAssessment, assessment.id) is None


def test_delete_route_rejects_cross_tenant_assessment(db):
    _, _, outsider_cycle, outsider_member, _, _, _ = foundation(db, group_id=2, year_id=200, branch=20, section_id=2000)
    outsider_assessment = start_assessment(db, school_group_id=2, cycle_id=outsider_cycle.id, cycle_population_member_id=outsider_member.id)
    db.commit()
    actor = _user("1000000004", group=1, branch=10)
    db.add(actor)
    grant(db, "Administrator", "talent_assessments.view", "talent_assessments.delete")
    with client(db, actor) as api:
        response = api.delete(f"/api/talent/assessments/{outsider_assessment.id}")
        assert response.status_code == 404
    assert db.get(models.TalentStudentAssessment, outsider_assessment.id) is not None


def test_delete_route_actions_omit_delete_when_dependents_exist(db):
    _, _, cycle, member, _, competencies, levels = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    set_competency_result(db, school_group_id=1, assessment_id=assessment.id,
                          framework_competency_id=competencies[0].id, rubric_level_id=levels[0].id,
                          expected_revision=assessment.revision)
    db.commit()
    actor = _user("1000000003")
    db.add(actor)
    grant(db, "Administrator", "talent_assessments.view", "talent_assessments.delete")
    with client(db, actor) as api:
        read = api.get(f"/api/talent/assessments/{assessment.id}")
        assert read.status_code == 200 and "delete" not in read.json()["actions"]
        response = api.delete(f"/api/talent/assessments/{assessment.id}")
        assert response.status_code == 400 and response.json()["code"] == "assessment_has_dependents"
    assert db.get(models.TalentStudentAssessment, assessment.id) is not None


# ---------------------------------------------------------------------------
# Regression: deletion never touches Cycle population, other Assessments, or
# Student placement history.
# ---------------------------------------------------------------------------

def test_delete_does_not_touch_population_members_or_other_assessments(db):
    program, framework, cycle, member, student, _, _ = foundation(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    db.commit()

    student2 = create_student(db, school_group_id=1, first_name="Student", last_name="Two")
    create_placement(db, school_group_id=1, student_id=student2.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    db.commit()
    from talent_assessment_cycle_service import reconcile_open_cycle_population
    reconcile_open_cycle_population(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    db.commit()
    member2 = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id, student_id=student2.id).one()
    other_assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member2.id)
    db.commit()

    member_count_before = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).count()
    placement_count_before = db.query(models.StudentAcademicPlacement).filter_by(student_id=student.id).count()

    delete_assessment(db, school_group_id=1, assessment_id=assessment.id)
    db.commit()

    assert db.get(models.TalentStudentAssessment, assessment.id) is None
    assert db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).count() == member_count_before
    assert db.get(models.TalentAssessmentCyclePopulationMember, member.id) is not None
    assert db.query(models.StudentAcademicPlacement).filter_by(student_id=student.id).count() == placement_count_before
    assert db.get(models.TalentStudentAssessment, other_assessment.id) is not None


# ---------------------------------------------------------------------------
# Permission registry shape: additive tuple, no hard-coded role names.
# ---------------------------------------------------------------------------

def test_new_permission_key_is_registered_with_the_same_additive_shape():
    import permission_registry as pr
    assert "talent_assessments.delete" in pr.ALL_PERMISSION_KEYS
    assert "talent_assessments.delete" in pr.PERMISSION_LABELS and pr.PERMISSION_LABELS["talent_assessments.delete"]
    assert "talent_assessments.delete" in pr.DEVELOPER_ASSIGNABLE_PERMISSION_KEYS
    assert "talent_assessments.delete" not in pr._EDITOR_LIKE_PERMISSIONS
