import json
from datetime import datetime, timedelta

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
from routers.talent_programs import router as programs_router
from student_academic_service import create_placement, create_student, transition_placement
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_program_service import (
    TalentProgramError, activate_framework, add_framework_competency, add_rubric_level, configure_kpi,
    create_competency, create_framework_draft, create_program, remove_framework_competency, transition_program,
    upsert_annual_configuration, upsert_descriptor, upsert_rubric,
)
from talent_student_assessment_service import (
    TalentStudentAssessmentError, complete_assessment, get_assessment,
    mark_non_complete, overall_program_result, reassessment_requirement, remove_competency_result, set_competency_result,
    start_assessment, start_assessment_for_evaluation, start_reassessment,
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



def ensure_competency_owned_rubrics(session, program, framework):
    """Make a Draft Framework fully assessable under the current canonical rubric model."""
    members = session.query(models.FrameworkCompetency).filter_by(
        school_group_id=1, program_id=program.id, framework_version_id=framework.id
    ).order_by(models.FrameworkCompetency.display_order).all()
    for member in members:
        existing = session.query(models.TalentRubric).filter_by(
            school_group_id=1, program_id=program.id, framework_version_id=framework.id,
            framework_competency_id=member.id,
        ).one_or_none()
        if existing is not None:
            continue
        _, framework = upsert_rubric(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            framework_competency_id=member.id, expected_revision=framework.revision,
            name=f"{member.label} rubric",
        )
        for code, label in (("LEVEL_1", "Beginning"), ("LEVEL_2", "Secure")):
            _, framework = add_rubric_level(
                session, school_group_id=1, program_id=program.id, framework_id=framework.id,
                framework_competency_id=member.id, expected_revision=framework.revision,
                code=code, label=label, description=f"{member.label} {label}",
            )
    return framework

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


def test_start_assessment_uses_configured_evaluation_framework_without_active_status_gate(db):
    _, session = db
    program, framework, cycle, member, _, _, _, _ = foundation(session)
    # Reproduce the Owner-reported state: the Evaluation already points at a
    # configured Framework with competencies/rubric, but lifecycle labels are
    # still Draft. These labels are not assessment eligibility authority.
    program.status = "draft"
    framework.status = "draft"
    session.commit()
    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=member.id,
    )
    assert assessment.status == "in_progress"
    assert assessment.framework_version_id == framework.id


def test_start_assessment_requires_real_assessable_framework_content(db):
    _, session = db
    program, framework, cycle, member, _, _, _, _ = foundation(session)
    # Remove dependent descriptor rows before deleting rubric levels so the
    # test creates a valid "configured framework with no rubric levels" state
    # without violating the schema's foreign-key integrity.
    session.query(models.TalentGradeCompetencyRubricDescriptor).filter_by(
        framework_version_id=framework.id
    ).delete()
    session.query(models.TalentCompetencyRubricDescriptor).filter_by(
        framework_version_id=framework.id
    ).delete()
    session.query(models.TalentRubricLevel).filter_by(
        framework_version_id=framework.id
    ).delete()
    session.flush()
    with pytest.raises(TalentStudentAssessmentError) as error:
        start_assessment(
            session, school_group_id=1, cycle_id=cycle.id,
            cycle_population_member_id=member.id,
        )
    assert error.value.code == "assessment_tool_unavailable"


def test_legacy_population_member_start_remains_compatible_and_duplicate_is_blocked(db):
    _, session = db
    _, _, cycle, member, _, _, _, _ = foundation(session)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    assert assessment.status == "in_progress"
    with pytest.raises(TalentStudentAssessmentError, match="already has"):
        start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    with pytest.raises(TalentStudentAssessmentError) as invalid:
        start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=99999)
    assert invalid.value.code == "invalid_student_context"


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


def test_framework_read_ids_are_accepted_end_to_end_by_the_write_route(db):
    """Regression for the M11 assessment-entry read/write contract gap: the framework
    read routes must expose the exact `FrameworkCompetency.id` and `TalentRubricLevel.id`
    values the write route requires, not the parent `talent_competency_id` catalog FK.
    This proves a UI built purely from the read payloads can successfully write results."""
    _, session = db
    program, framework, cycle, member, _, _, competencies, levels = foundation(session)
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    session.commit()
    admin = _user("1000000009", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.include_router(programs_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        framework_read = client.get(f"/api/talent/programs/{program.id}/frameworks/{framework.id}")
        assert framework_read.status_code == 200
        read_competencies = framework_read.json()["competencies"]
        # The read payload must expose the actual FrameworkCompetency.id (the value the
        # write route is FK-constrained on) alongside the pre-existing competency_id
        # (the parent talent_competency catalog FK). They are separate columns/tables
        # (talent_framework_competencies.id vs talent_framework_competencies.talent_competency_id)
        # and only coincidentally share numeric values in this small fixture.
        assert {row["id"] for row in read_competencies} == {c.id for c in competencies}
        assert {row["competency_id"] for row in read_competencies} == {c.talent_competency_id for c in competencies}

        configuration = client.get(f"/api/talent/programs/{program.id}/frameworks/{framework.id}/configuration")
        assert configuration.status_code == 200
        read_levels = configuration.json()["levels"]
        assert {row["id"] for row in read_levels} == {level.id for level in levels}

        target_competency_id = read_competencies[0]["id"]
        target_level_id = read_levels[0]["id"]
        write = client.put(
            f"/api/talent/assessments/{assessment.id}/competency-results/{target_competency_id}",
            json={"rubric_level_id": target_level_id, "expected_revision": assessment.revision, "evidence": "from read ids"},
        )
        assert write.status_code == 200
        assert write.json()["result"]["framework_competency_id"] == target_competency_id
        assert write.json()["result"]["rubric_level_id"] == target_level_id


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
        # This test is about payload validation, not current-rubric selection.
        # Use the supported legacy population-member form as the valid control;
        # the normal student_id path is covered separately by the strict
        # competency-owned-rubric tests.
        valid = client.post("/api/talent/assessments", json={
            "cycle_id": cycle.id, "cycle_population_member_id": member.id,
        })
        assert valid.status_code == 201
        assert valid.json()["student_id"] == member.student_id


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

def test_assessment_contexts_follow_evaluation_period_sequence_not_creation_order(db):
    _, session = db
    program, framework, cycle2, _, _, _, _, _ = foundation(session)
    config = session.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        program_id=program.id, academic_year_id=100
    ).one()
    plan = models.TalentAnnualEvaluationPlan(
        school_group_id=1, program_id=program.id, academic_year_id=100,
        program_academic_year_configuration_id=config.id, status="draft", revision=1,
    )
    session.add(plan); session.flush()
    period1 = models.TalentPlannedEvaluationPeriod(
        school_group_id=1, program_id=program.id, academic_year_id=100,
        annual_evaluation_plan_id=plan.id, sequence=1, label="Term 1",
        normalized_label="term 1", status="planned", is_required=True,
    )
    period2 = models.TalentPlannedEvaluationPeriod(
        school_group_id=1, program_id=program.id, academic_year_id=100,
        annual_evaluation_plan_id=plan.id, sequence=2, label="Term 2",
        normalized_label="term 2", status="planned", is_required=True,
    )
    session.add_all([period1, period2]); session.flush()
    cycle2.title = "Term 2"
    cycle2.planned_evaluation_period_id = period2.id
    cycle1 = models.TalentAssessmentCycle(
        school_group_id=1, program_id=program.id, academic_year_id=100,
        framework_version_id=framework.id, planned_evaluation_period_id=period1.id,
        title="Term 1", status="draft", revision=1,
        created_at=datetime(2026, 12, 1),
    )
    cycle2.created_at = datetime(2026, 9, 1)
    session.add(cycle1); session.commit()

    admin = _user("1000000010", branch=None, scope="ORGANIZATION")
    session.add(admin); session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        response = client.get(
            f"/api/talent/assessments/contexts?program_id={program.id}&academic_year_id=100"
        )
        assert response.status_code == 200
        assert [item["title"] for item in response.json()][:2] == ["Term 1", "Term 2"]


def test_completed_assessment_requires_and_starts_new_reassessment_after_rubric_change(db):
    _, session = db
    program, framework, cycle, member, student, _, competencies, levels = foundation(session)
    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=member.id,
    )
    assessment = set_all_results(session, assessment, competencies, levels)
    completed = complete_assessment(
        session, school_group_id=1, assessment_id=assessment.id,
        expected_revision=assessment.revision,
    )
    session.commit()

    # A completed legacy/shared-rubric Assessment is not stale merely because
    # the old representation exists; re-evaluation begins only after a complete
    # current competency-owned rubric actually supersedes its persisted binding.
    assert reassessment_requirement(session, completed) is None

    # An unchanged legacy-compatible clone alone must not force re-evaluation.
    revised = create_framework_draft(
        session, school_group_id=1, program_id=program.id,
        title="Updated rubric", clone_from_id=framework.id,
        supersedes_framework_version_id=framework.id,
    )
    assert reassessment_requirement(session, completed) is None

    # The current authoring model moves the newer version onto complete
    # competency-owned rubrics. A real Student-facing change then requires
    # re-evaluation in the original visible Evaluation context.
    revised = ensure_competency_owned_rubrics(session, program, revised)
    lineage = create_competency(
        session, school_group_id=1, program_id=program.id,
        code="THREE", name="THREE",
    )
    new_member, revised = add_framework_competency(
        session, school_group_id=1, program_id=program.id, framework_id=revised.id,
        competency_id=lineage.id, expected_revision=revised.revision,
    )
    _, revised = upsert_rubric(
        session, school_group_id=1, program_id=program.id, framework_id=revised.id,
        framework_competency_id=new_member.id, expected_revision=revised.revision,
        name="THREE rubric",
    )
    _, revised = add_rubric_level(
        session, school_group_id=1, program_id=program.id, framework_id=revised.id,
        framework_competency_id=new_member.id, expected_revision=revised.revision,
        code="LEVEL_1", label="Beginning", description="THREE Beginning",
    )
    assert reassessment_requirement(session, completed).id == revised.id

    replacement = start_reassessment(
        session, school_group_id=1, assessment_id=completed.id,
    )
    session.flush()

    historical = get_assessment(
        session, school_group_id=1, assessment_id=completed.id,
    )
    assert historical.status == "completed"
    assert historical.is_current is False
    assert historical.framework_version_id == framework.id
    assert replacement.status == "in_progress"
    assert replacement.is_current is True
    assert replacement.reassessment_of_assessment_id == completed.id
    assert replacement.framework_version_id == revised.id
    assert replacement.student_id == student.id
    assert replacement.cycle_id != cycle.id
    # Historical evidence is preserved rather than moved to the new attempt.
    assert session.query(models.TalentStudentCompetencyResult).filter_by(
        assessment_id=completed.id
    ).count() == len(competencies)
    assert session.query(models.TalentStudentCompetencyResult).filter_by(
        assessment_id=replacement.id
    ).count() == 0


def test_same_id_rubric_semantic_edit_after_completion_requires_reassessment(db):
    _, session = db
    program, framework, cycle, member, _, _, competencies, _ = foundation(session)

    # Build the canonical competency-owned rubric structure before the Student
    # is assessed so persisted result bindings already point at these exact
    # rubric/level IDs. This isolates the same-ID semantic-edit path from the
    # separate legacy binding-mismatch compatibility rule.
    owned_levels = {}
    for index, competency in enumerate(competencies, 1):
        rubric = models.TalentRubric(
            school_group_id=1,
            program_id=program.id,
            framework_version_id=framework.id,
            framework_competency_id=competency.id,
            name=f"Owned rubric {index}",
        )
        session.add(rubric)
        session.flush()
        level = models.TalentRubricLevel(
            school_group_id=1,
            program_id=program.id,
            framework_version_id=framework.id,
            rubric_id=rubric.id,
            code="LEVEL_1",
            label="Beginning",
            description=f"Original description {index}",
            display_order=1,
        )
        session.add(level)
        session.flush()
        owned_levels[competency.id] = level
    session.commit()

    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=member.id,
    )
    revision = assessment.revision
    for competency in competencies:
        _, assessment = set_competency_result(
            session, school_group_id=1, assessment_id=assessment.id,
            framework_competency_id=competency.id,
            rubric_level_id=owned_levels[competency.id].id,
            expected_revision=revision,
            evidence="private evidence",
        )
        revision = assessment.revision
    completed = complete_assessment(
        session, school_group_id=1, assessment_id=assessment.id,
        expected_revision=assessment.revision,
    )
    session.commit()

    # Legacy production state: Student-facing semantics changed in place after
    # completion while every persisted rubric/level ID stayed exactly the same.
    current_level = owned_levels[competencies[0].id]
    current_level.description = "Changed after Student completion"
    session.add(models.TalentConfigurationAudit(
        school_group_id=1,
        program_id=program.id,
        resource_type="rubric_level",
        resource_id=current_level.id,
        action="level_update",
        before_json=json.dumps({
            "framework_id": framework.id,
            "description": "Original description 1",
        }),
        after_json=json.dumps({
            "framework_id": framework.id,
            "description": current_level.description,
        }),
        correlation_id="same-id-rubric-semantic-edit",
        created_at=completed.completed_at + timedelta(seconds=1),
    ))
    session.commit()

    # Bindings still match: reassessment must be coming from the audited
    # post-completion semantic edit, not from changed rubric/level IDs.
    persisted = {
        row.framework_competency_id: row
        for row in session.query(models.TalentStudentCompetencyResult).filter_by(
            assessment_id=completed.id
        ).all()
    }
    assert persisted[competencies[0].id].rubric_level_id == current_level.id

    required = reassessment_requirement(session, completed)
    assert required is not None
    assert required.id == framework.id


def test_legacy_same_framework_rubric_replacement_resets_completed_student_for_reassessment(db):
    _, session = db
    program, framework, cycle, member, student, _, competencies, levels = foundation(session)
    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=member.id,
    )
    assessment = set_all_results(session, assessment, competencies, levels)
    completed = complete_assessment(
        session, school_group_id=1, assessment_id=assessment.id,
        expected_revision=assessment.revision,
    )
    session.commit()

    # Reproduce the real legacy defect: before the assessed-Framework mutation
    # guard was consistently enforced, the same Framework Version could acquire
    # the new competency-owned rubric structure after Students had already
    # completed against its legacy shared rubric. Insert the current canonical
    # structure directly to model that historical database state.
    for index, competency in enumerate(competencies, 1):
        rubric = models.TalentRubric(
            school_group_id=1,
            program_id=program.id,
            framework_version_id=framework.id,
            framework_competency_id=competency.id,
            name=f"Current rubric {index}",
        )
        session.add(rubric)
        session.flush()
        session.add_all([
            models.TalentRubricLevel(
                school_group_id=1, program_id=program.id,
                framework_version_id=framework.id, rubric_id=rubric.id,
                code="LEVEL_1", label="Beginning", description="Current beginning",
                display_order=1,
            ),
            models.TalentRubricLevel(
                school_group_id=1, program_id=program.id,
                framework_version_id=framework.id, rubric_id=rubric.id,
                code="LEVEL_2", label="Secure", description="Current secure",
                display_order=2,
            ),
        ])
    session.commit()

    required = reassessment_requirement(session, completed)
    assert required is not None
    assert required.id == framework.id

    replacement = start_reassessment(
        session, school_group_id=1, assessment_id=completed.id,
    )
    session.flush()

    historical = get_assessment(
        session, school_group_id=1, assessment_id=completed.id,
    )
    assert historical.status == "completed"
    assert historical.is_current is False
    assert replacement.status == "in_progress"
    assert replacement.is_current is True
    assert replacement.reassessment_of_assessment_id == completed.id
    assert replacement.framework_version_id == framework.id
    assert replacement.evaluation_context_cycle_id == cycle.id
    assert replacement.student_id == student.id
    assert session.query(models.TalentStudentCompetencyResult).filter_by(
        assessment_id=replacement.id
    ).count() == 0


def test_reassessment_migration_is_additive_and_idempotent(db):
    engine, _ = db
    with engine.begin() as connection:
        db_migrations._talent_assessment_reassessment_attempts(engine, connection)
        db_migrations._talent_assessment_reassessment_attempts(engine, connection)
    columns = {row["name"] for row in inspect(engine).get_columns("talent_student_assessments")}
    assert {"is_current", "reassessment_of_assessment_id"}.issubset(columns)


def test_framework_with_assessment_history_requires_new_version_before_semantic_edit(db):
    _, session = db
    program, framework, cycle, member, _, _, _, _ = foundation(session)
    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=member.id,
    )
    session.commit()
    # Legacy/simple assessment flow can leave evidence against a Draft-labelled
    # framework. The presence of Assessment history, not the label alone, makes
    # semantic edits unsafe.
    framework.status = "draft"
    session.commit()
    lineage = create_competency(
        session, school_group_id=1, program_id=program.id,
        code="LATE", name="Late competency",
    )
    with pytest.raises(TalentProgramError) as blocked:
        add_framework_competency(
            session, school_group_id=1, program_id=program.id,
            framework_id=framework.id, competency_id=lineage.id,
            expected_revision=framework.revision,
        )
    assert blocked.value.code == "framework_in_use"
    existing_member = session.query(models.FrameworkCompetency).filter_by(
        framework_version_id=framework.id
    ).order_by(models.FrameworkCompetency.display_order).first()
    with pytest.raises(TalentProgramError) as blocked_rubric:
        upsert_rubric(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            framework_competency_id=existing_member.id, expected_revision=framework.revision,
            name="Unsafe in-place rubric",
        )
    assert blocked_rubric.value.code == "framework_in_use"
    with pytest.raises(TalentProgramError) as blocked_delete:
        remove_framework_competency(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            competency_id=existing_member.talent_competency_id, expected_revision=framework.revision,
        )
    assert blocked_delete.value.code == "framework_in_use"
    assert get_assessment(session, school_group_id=1, assessment_id=assessment.id).framework_version_id == framework.id


def test_normal_evaluation_start_never_uses_legacy_shared_rubric(db):
    _, session = db
    _, _, cycle, member, _, _, _, _ = foundation(session)
    with pytest.raises(TalentStudentAssessmentError) as blocked:
        start_assessment_for_evaluation(
            session, school_group_id=1, evaluation_cycle_id=cycle.id,
            student_id=member.student_id,
        )
    assert blocked.value.code == "assessment_tool_unavailable"


def test_new_student_uses_newest_saved_rubric_but_stays_in_original_evaluation_context(db):
    _, session = db
    program, framework, cycle, member, _, _, competencies, levels = foundation(session)

    revised = create_framework_draft(
        session, school_group_id=1, program_id=program.id,
        title="Revised rubric", clone_from_id=framework.id,
        supersedes_framework_version_id=framework.id,
    )
    revised = ensure_competency_owned_rubrics(session, program, revised)
    new_competency = create_competency(
        session, school_group_id=1, program_id=program.id,
        code="NEW", name="New competency",
    )
    revised_member, revised = add_framework_competency(
        session, school_group_id=1, program_id=program.id, framework_id=revised.id,
        competency_id=new_competency.id, expected_revision=revised.revision,
        grade_level="1",
    )
    revised_rubric, revised = upsert_rubric(
        session, school_group_id=1, program_id=program.id, framework_id=revised.id,
        framework_competency_id=revised_member.id, expected_revision=revised.revision,
        name="New competency rubric",
    )
    _, revised = add_rubric_level(
        session, school_group_id=1, program_id=program.id, framework_id=revised.id,
        framework_competency_id=revised_member.id, expected_revision=revised.revision,
        code="LEVEL_1", label="Beginning", description="New level",
    )
    session.commit()

    started = start_assessment_for_evaluation(
        session, school_group_id=1, evaluation_cycle_id=cycle.id,
        student_id=member.student_id,
    )
    assert started.framework_version_id == revised.id
    assert started.cycle_id != cycle.id
    assert started.evaluation_context_cycle_id == cycle.id

    rows = session.query(models.TalentStudentAssessment).filter_by(
        school_group_id=1, student_id=member.student_id, is_current=True
    ).all()
    assert [row.id for row in rows] == [started.id]


def test_competency_result_rejects_level_from_another_competency_rubric(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Independent Rubrics")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(
        session, school_group_id=1, program_id=program.id, title="Framework"
    )
    members = []
    levels = []
    for code, name in (("READ", "Reading"), ("WRITE", "Writing")):
        competency = create_competency(
            session, school_group_id=1, program_id=program.id, code=code, name=name
        )
        member_row, framework = add_framework_competency(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            competency_id=competency.id, expected_revision=framework.revision, grade_level="1",
        )
        rubric, framework = upsert_rubric(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            framework_competency_id=member_row.id, expected_revision=framework.revision,
            name=f"{name} rubric",
        )
        level, framework = add_rubric_level(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            framework_competency_id=member_row.id, expected_revision=framework.revision,
            code="LEVEL_1", label="Beginning", description=f"{name} description",
        )
        members.append(member_row)
        levels.append(level)

    upsert_annual_configuration(
        session, school_group_id=1, program_id=program.id, academic_year_id=100,
        is_enabled=True, eligible_grade_levels=["1"],
    )
    student = create_student(session, school_group_id=1, first_name="Scope", last_name="Test")
    create_placement(
        session, school_group_id=1, student_id=student.id, academic_year_id=100,
        branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1),
    )
    cycle = create_cycle(
        session, school_group_id=1, program_id=program.id, academic_year_id=100,
        framework_version_id=framework.id, title="Term 1",
        population_effective_at=datetime(2026, 10, 1),
    )
    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id, student_id=student.id
    )

    with pytest.raises(TalentStudentAssessmentError) as error:
        set_competency_result(
            session, school_group_id=1, assessment_id=assessment.id,
            framework_competency_id=members[0].id,
            rubric_level_id=levels[1].id,
            expected_revision=assessment.revision,
        )
    assert error.value.code == "invalid_result_scope"


def test_competency_rubric_migration_is_idempotent(db):
    engine, _ = db
    with engine.begin() as connection:
        db_migrations._talent_competency_specific_rubrics(engine, connection)
        db_migrations._talent_competency_specific_rubrics(engine, connection)
    columns = {row["name"] for row in inspect(engine).get_columns("talent_rubrics")}
    assert "framework_competency_id" in columns


def test_overall_program_result_requires_one_coherent_rubric_scale(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Coherent Talent Scale")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(
        session, school_group_id=1, program_id=program.id, title="Grade 1 rubric"
    )
    members = []
    rubric_levels = []
    for code, name, count in (
        ("SPEED", "Mental Speed", 3),
        ("STRATEGY", "Strategy Flexibility", 5),
    ):
        competency = create_competency(
            session, school_group_id=1, program_id=program.id, code=code, name=name
        )
        member, framework = add_framework_competency(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            competency_id=competency.id, expected_revision=framework.revision, grade_level="1",
        )
        _, framework = upsert_rubric(
            session, school_group_id=1, program_id=program.id, framework_id=framework.id,
            framework_competency_id=member.id, expected_revision=framework.revision,
            name=f"{name} rubric",
        )
        levels = []
        for level_no in range(1, count + 1):
            level, framework = add_rubric_level(
                session, school_group_id=1, program_id=program.id, framework_id=framework.id,
                framework_competency_id=member.id, expected_revision=framework.revision,
                code=f"L{level_no}", label=f"Level {level_no}",
            )
            levels.append(level)
        members.append(member)
        rubric_levels.append(levels)

    upsert_annual_configuration(
        session, school_group_id=1, program_id=program.id, academic_year_id=100,
        is_enabled=True, eligible_grade_levels=["1"],
    )
    student = create_student(session, school_group_id=1, first_name="Overall", last_name="Result")
    create_placement(
        session, school_group_id=1, student_id=student.id, academic_year_id=100,
        branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1),
    )
    cycle = create_cycle(
        session, school_group_id=1, program_id=program.id, academic_year_id=100,
        framework_version_id=framework.id, title="Term 1",
        population_effective_at=datetime(2026, 10, 1),
    )
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, student_id=student.id)
    for member, level in ((members[0], rubric_levels[0][1]), (members[1], rubric_levels[1][3])):
        _, assessment = set_competency_result(
            session, school_group_id=1, assessment_id=assessment.id,
            framework_competency_id=member.id, rubric_level_id=level.id,
            expected_revision=assessment.revision,
        )

    overall = overall_program_result(session, assessment)
    assert overall["available"] is False
    assert overall["reason"] == "inconsistent_rubric_scale"
    with pytest.raises(TalentStudentAssessmentError) as error:
        complete_assessment(
            session, school_group_id=1, assessment_id=assessment.id,
            expected_revision=assessment.revision,
        )
    assert error.value.code == "inconsistent_rubric_scale"


def test_assessment_api_exposes_overall_program_result(db):
    _, session = db
    _, _, cycle, member, _, _, competencies, levels = foundation(session)
    assessment = start_assessment(
        session, school_group_id=1, cycle_id=cycle.id,
        cycle_population_member_id=member.id,
    )
    # Shared two-level legacy rubric: first competency low=0, second high=100 => 50.
    for competency, level in zip(competencies, (levels[0], levels[1])):
        _, assessment = set_competency_result(
            session, school_group_id=1, assessment_id=assessment.id,
            framework_competency_id=competency.id, rubric_level_id=level.id,
            expected_revision=assessment.revision,
        )
    session.commit()

    admin = _user("1000000098", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        response = client.get(f"/api/talent/assessments/{assessment.id}")
        assert response.status_code == 200
        overall = response.json()["overall_result"]
        assert overall["available"] is True
        assert overall["average"] == 1.5
        assert overall["scale_max"] == 2
        assert overall["normalized_percent"] == 75
        assert overall["competency_count"] == 2
