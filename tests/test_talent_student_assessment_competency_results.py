from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_assessments import router
from student_academic_service import create_placement, create_student, transition_placement
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, configure_kpi,
    create_competency, create_framework_draft, create_program, transition_program,
    upsert_annual_configuration, upsert_descriptor, upsert_rubric,
)
from talent_student_assessment_service import (
    TalentStudentAssessmentError, complete_assessment, get_assessment,
    mark_non_complete, remove_competency_result, set_competency_result,
    start_assessment,
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
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=11, academic_year_id=100, grade_level="1", section_name="B", class_status="Current"),
    ])
    session.commit()
    yield engine, session
    session.close()


def foundation(session, *, kpi=False, branch=10):
    program = create_program(session, school_group_id=1, name="Performing Arts" if not kpi else "Academic")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(session, school_group_id=1, program_id=program.id, title="Framework")
    competencies = []
    for code in ("ONE", "TWO"):
        lineage = create_competency(session, school_group_id=1, program_id=program.id, code=code, name=code)
        membership, framework = add_framework_competency(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            competency_id=lineage.id, expected_revision=framework.revision,
        )
        competencies.append(membership)
    rubric, framework = upsert_rubric(session, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, name="Rubric")
    levels = []
    for code, value in (("SEVENTY_THREE", 73), ("SEVENTY_FOUR", 74)):
        level, framework = add_rubric_level(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, code=code, label=code.replace("_", " "),
            numeric_value=value if kpi else None,
        )
        levels.append(level)
    for competency in competencies:
        for level in levels:
            _, framework = upsert_descriptor(
                session, school_group_id=1, program_id=program.id, framework_id=framework.id,
                framework_competency_id=competency.id, rubric_level_id=level.id,
                expected_revision=framework.revision, descriptor=f"{competency.id}-{level.id}",
            )
    if kpi:
        _, framework = configure_kpi(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, result_scale_min=0,
            result_scale_max=100, interpretation="Framework-specific result",
            components=[{"framework_competency_id": item.id, "weight_basis_points": 5000} for item in competencies],
        )
    activate_framework(session, school_group_id=1, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    upsert_annual_configuration(session, school_group_id=1, program_id=program.id, academic_year_id=100,
                                is_enabled=True, eligible_grade_levels=["1"])
    student = create_student(session, school_group_id=1, first_name="Student", last_name="One")
    placement = create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                                 branch_id=branch, planning_section_id=1000 if branch == 10 else 1001,
                                 effective_from=datetime(2026, 9, 1))
    cycle = create_cycle(session, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Cycle",
                         population_effective_at=datetime(2026, 10, 1))
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    session.commit()
    member = session.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id, student_id=student.id).one()
    return program, framework, cycle, member, student, placement, competencies, levels


def set_all_results(session, assessment, competencies, levels, *, weights=(None, None)):
    revision = assessment.revision
    for index, competency in enumerate(competencies):
        level = levels[index]
        _, assessment = set_competency_result(
            session, school_group_id=1, assessment_id=assessment.id,
            framework_competency_id=competency.id, rubric_level_id=level.id,
            expected_revision=revision, evidence="private evidence",
        )
        revision = assessment.revision
    return assessment


def test_only_open_frozen_member_can_start_and_only_one_assessment(db):
    _, session = db
    _, _, cycle, member, _, _, _, _ = foundation(session)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    assert assessment.status == "in_progress"
    with pytest.raises(TalentStudentAssessmentError, match="already has"):
        start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    with pytest.raises(TalentStudentAssessmentError) as invalid:
        start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=99999)
    assert invalid.value.code == "invalid_population_member"
    cycle.status = "closed"
    with pytest.raises(TalentStudentAssessmentError) as closed:
        start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    assert closed.value.code == "cycle_not_open"


def test_qualitative_assessment_completes_without_kpi_or_numeric_levels(db):
    _, session = db
    _, framework, cycle, member, _, _, competencies, levels = foundation(session, kpi=False)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    assessment = set_all_results(session, assessment, competencies, levels)
    completed = complete_assessment(session, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)
    assert completed.status == "completed" and completed.kpi_result is None
    assert all(level.numeric_value is None for level in levels)
    with pytest.raises(TalentStudentAssessmentError) as immutable:
        set_competency_result(session, school_group_id=1, assessment_id=completed.id,
                              framework_competency_id=competencies[0].id, rubric_level_id=levels[0].id,
                              expected_revision=completed.revision)
    assert immutable.value.code == "immutable_assessment"
    assert framework.status == "active"


@pytest.mark.parametrize("weights, expected_numerator, expected_result", [
    ((5100, 4900), 734900, 73),
    ((5000, 5000), 735000, 74),
    ((4900, 5100), 735100, 74),
])
def test_kpi_uses_integer_half_up_and_persists_provenance(db, weights, expected_numerator, expected_result):
    _, session = db
    _, framework, cycle, member, _, _, competencies, levels = foundation(session, kpi=True)
    components = session.query(models.TalentKpiComponent).filter_by(framework_version_id=framework.id).order_by(models.TalentKpiComponent.framework_competency_id).all()
    for component, weight in zip(components, weights):
        component.weight_basis_points = weight
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    assessment = set_all_results(session, assessment, competencies, levels)
    completed = complete_assessment(session, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)
    assert completed.kpi_weighted_numerator == expected_numerator
    assert completed.kpi_result == expected_result and type(completed.kpi_result) is int
    assert (completed.kpi_result_scale_min, completed.kpi_result_scale_max) == (0, 100)
    assert completed.kpi_calculation_method == "weighted_level_average"
    assert len(completed.kpi_calculation_fingerprint) == 64
    assert completed.kpi_calculated_at is not None


def test_completion_rejects_missing_competency_and_kpi_input(db):
    _, session = db
    _, framework, cycle, member, _, _, competencies, levels = foundation(session, kpi=True)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    _, assessment = set_competency_result(session, school_group_id=1, assessment_id=assessment.id,
                                          framework_competency_id=competencies[0].id, rubric_level_id=levels[0].id,
                                          expected_revision=assessment.revision)
    with pytest.raises(TalentStudentAssessmentError) as missing:
        complete_assessment(session, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)
    assert missing.value.code == "incomplete_assessment"
    assert get_assessment(session, school_group_id=1, assessment_id=assessment.id).kpi_result is None
    assert framework.status == "active"


def test_stale_and_non_complete_terminal_states_have_no_kpi(db):
    _, session = db
    _, _, cycle, member, _, _, competencies, levels = foundation(session, kpi=True)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    _, updated = set_competency_result(session, school_group_id=1, assessment_id=assessment.id,
                                       framework_competency_id=competencies[0].id, rubric_level_id=levels[0].id,
                                       expected_revision=assessment.revision)
    with pytest.raises(TalentStudentAssessmentError) as stale:
        mark_non_complete(session, school_group_id=1, assessment_id=assessment.id,
                          expected_revision=1, status="incomplete")
    assert stale.value.code == "stale_assessment"
    terminal = mark_non_complete(session, school_group_id=1, assessment_id=assessment.id,
                                 expected_revision=updated.revision, status="insufficient_evidence")
    assert terminal.status == "insufficient_evidence" and terminal.kpi_result is None
    with pytest.raises(TalentStudentAssessmentError):
        remove_competency_result(session, school_group_id=1, assessment_id=terminal.id,
                                 framework_competency_id=competencies[0].id, expected_revision=terminal.revision)


def test_fingerprint_is_deterministic_and_framework_retirement_does_not_reinterpret_result(db):
    _, session = db
    _, framework, cycle, member, _, placement, competencies, levels = foundation(session, kpi=True)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    assessment = set_all_results(session, assessment, competencies, levels)
    completed = complete_assessment(session, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)
    fingerprint = completed.kpi_calculation_fingerprint
    framework.status = "retired"
    transition_placement(session, school_group_id=1, student_id=member.student_id, placement_id=placement.id,
                         transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.commit()
    persisted = get_assessment(session, school_group_id=1, assessment_id=completed.id)
    assert persisted.kpi_calculation_fingerprint == fingerprint
    assert persisted.kpi_result == completed.kpi_result


def _user(user_id, *, branch, scope, role="Administrator"):
    return models.User(user_id=user_id, username=f"user{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=1, branch_id=branch, academic_year_id=100, is_active=True)


def test_branch_scope_uses_frozen_member_and_dedicated_permissions(db):
    _, session = db
    _, _, cycle, member, student, placement, _, _ = foundation(session, branch=10)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    branch_user = _user("1000000001", branch=10, scope="BRANCH")
    denied_user = _user("1000000002", branch=11, scope="BRANCH", role="Editor")
    session.add_all([branch_user, denied_user, models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_assessments.view", is_allowed=True)])
    transition_placement(session, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/assessments/{assessment.id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: denied_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/assessments/{assessment.id}").status_code == 403


def test_start_assessment_rejects_malformed_payload_without_500(db):
    _, session = db
    _, _, cycle, member, _, _, _, _ = foundation(session)
    admin = _user("1000000003", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app, raise_server_exceptions=False) as client:
        empty = client.post("/api/talent/assessments", json={})
        assert empty.status_code == 400
        assert empty.json()["code"] == "invalid_input"
        non_numeric = client.post("/api/talent/assessments", json={
            "cycle_id": "not-a-number", "cycle_population_member_id": member.id,
        })
        assert non_numeric.status_code == 400
        assert non_numeric.json()["code"] == "invalid_input"
        valid = client.post("/api/talent/assessments", json={
            "cycle_id": cycle.id, "cycle_population_member_id": member.id,
        })
        assert valid.status_code == 201


def test_audit_omits_evidence_and_m5_migration_is_idempotent(db):
    engine, session = db
    _, _, cycle, member, _, _, competencies, levels = foundation(session)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    set_competency_result(session, school_group_id=1, assessment_id=assessment.id,
                          framework_competency_id=competencies[0].id, rubric_level_id=levels[0].id,
                          expected_revision=assessment.revision, evidence="must not enter audit")
    session.commit()
    audit = session.query(models.TalentAssessmentAudit).filter_by(
        assessment_id=assessment.id, resource_type="competency_result"
    ).one()
    assert "must not enter audit" not in (audit.after_json or "")
    session.close()
    with engine.begin() as connection:
        models.TalentStudentCompetencyResult.__table__.drop(connection)
        models.TalentStudentAssessment.__table__.drop(connection)
        db_migrations._talent_student_assessment_competency_results_foundation(engine, connection)
        db_migrations._talent_student_assessment_competency_results_foundation(engine, connection)
    assert {"talent_student_assessments", "talent_student_competency_results"}.issubset(inspect(engine).get_table_names())
    assert any(row.migration_id == "20260904_005_talent_student_assessment_competency_results" for row in db_migrations.MIGRATIONS)