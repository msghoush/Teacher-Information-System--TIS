"""ADR 0045: Al-Andalus Section display - Student/Talent surface wiring.

Covers the shared ``academic_grade.format_section_display`` helper wired into
the real Student and Talent presentation surfaces: Students UI current
placement/placement history, the placement Section selector, the Talent
frozen historical Learner Profile context, the Talent Student Assessment
eligible-students roster, and the Talent Results/Analytics Section filter.

Pure formatting-edge-case coverage lives in
``tests/test_academic_grade_section_display.py``.
"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from academic_grade import AL_ANDALUS_SECTION_DISPLAY_WORKSPACE_UUID as AL_ANDALUS_UUID
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers import students_ui
from routers.talent_assessment_cycles import router as talent_assessment_cycles_router
from routers.talent_programs import router as talent_programs_router
from student_academic_service import create_placement, create_student, transition_placement
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_learner_profile_service import build_learner_profile
from talent_student_assessment_service import start_assessment
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, create_competency,
    create_framework_draft, create_program, transition_program, upsert_annual_configuration,
    upsert_descriptor, upsert_rubric,
)

SAME_NAME_DIFFERENT_UUID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_UUID = "22222222-2222-2222-2222-222222222222"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        # Exact ADR 0045-authorized workspace.
        models.SchoolGroup(id=1, name="Al-Andalus", workspace_uuid=AL_ANDALUS_UUID),
        # A different SchoolGroup row with a DIFFERENT name but sharing no
        # special relationship to the authorized UUID (its own random-style
        # UUID) - the counterpart to the workspace-rename test below, which
        # proves activation survives an in-place name change on the SAME
        # authorized row rather than by name matching a second row.
        models.SchoolGroup(id=2, name="Al-Andalus Overseas Campus", workspace_uuid=SAME_NAME_DIFFERENT_UUID),
        # A completely unrelated tenant.
        models.SchoolGroup(id=3, name="Other School", workspace_uuid=OTHER_TENANT_UUID),
    ])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="Main"),
        models.Branch(id=20, school_group_id=2, name="Main"),
        models.Branch(id=30, school_group_id=3, name="Main"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
        models.AcademicYear(id=300, school_group_id=3, year_name="2026-2027"),
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=10, academic_year_id=100, grade_level="2", section_name="B", class_status="Current"),
        models.PlanningSection(id=2000, branch_id=20, academic_year_id=200, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=3000, branch_id=30, academic_year_id=300, grade_level="1", section_name="A", class_status="Current"),
    ])
    session.commit()
    yield session
    session.close()


def _placement_for(db, *, school_group_id, branch_id, academic_year_id, planning_section_id, name):
    student = create_student(db, school_group_id=school_group_id, first_name=name, last_name="Learner")
    placement = create_placement(
        db, school_group_id=school_group_id, student_id=student.id, academic_year_id=academic_year_id,
        branch_id=branch_id, planning_section_id=planning_section_id, effective_from=datetime(2026, 9, 1),
    )
    db.commit()
    return student, placement


# --- Students UI: current placement / placement history (_placement_view) ---

def test_placement_view_activates_deterministic_display_for_exact_uuid(db):
    _, placement = _placement_for(
        db, school_group_id=1, branch_id=10, academic_year_id=100, planning_section_id=1000, name="Amal",
    )
    view = students_ui._placement_view(db, placement)
    assert view["section_display"] == "1.1"
    # Canonical values remain fully intact and separately available.
    assert view["grade_level"] == "1"
    assert view["section_name"] == "A"


def test_placement_view_different_uuid_row_is_unaffected(db):
    _, placement = _placement_for(
        db, school_group_id=2, branch_id=20, academic_year_id=200, planning_section_id=2000, name="Sami",
    )
    view = students_ui._placement_view(db, placement)
    assert view["section_display"] == "A"
    assert view["grade_level"] == "1"
    assert view["section_name"] == "A"


def test_same_organization_name_with_a_different_uuid_does_not_activate():
    """A SchoolGroup literally named "Al-Andalus" but NOT the authorized UUID
    must never activate the numeric mapping - proves activation is keyed
    exclusively off the UUID, never the editable organization name."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(models.SchoolGroup(id=1, name="Al-Andalus", workspace_uuid=SAME_NAME_DIFFERENT_UUID))
    session.commit()
    session.add(models.Branch(id=10, school_group_id=1, name="Main"))
    session.add(models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"))
    session.add(models.PlanningSection(
        id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current",
    ))
    session.commit()
    student, placement = _placement_for(
        session, school_group_id=1, branch_id=10, academic_year_id=100, planning_section_id=1000, name="Karim",
    )
    view = students_ui._placement_view(session, placement)
    assert view["section_display"] == "A"
    session.close()


def test_placement_view_other_tenant_is_completely_unaffected(db):
    _, placement = _placement_for(
        db, school_group_id=3, branch_id=30, academic_year_id=300, planning_section_id=3000, name="Nora",
    )
    view = students_ui._placement_view(db, placement)
    assert view["section_display"] == "A"


def test_workspace_rename_does_not_change_activation(db):
    _, placement = _placement_for(
        db, school_group_id=1, branch_id=10, academic_year_id=100, planning_section_id=1000, name="Rami",
    )
    group = db.get(models.SchoolGroup, 1)
    group.name = "Something Else Entirely"
    db.commit()
    view = students_ui._placement_view(db, placement)
    assert view["section_display"] == "1.1"


def test_placement_view_does_not_mutate_canonical_placement_row(db):
    _, placement = _placement_for(
        db, school_group_id=1, branch_id=10, academic_year_id=100, planning_section_id=1000, name="Leila",
    )
    students_ui._placement_view(db, placement)
    reloaded = db.get(models.StudentAcademicPlacement, placement.id)
    assert reloaded.grade_level == "1"
    assert reloaded.section_name == "A"
    planning_section = db.get(models.PlanningSection, 1000)
    assert planning_section.grade_level == "1"
    assert planning_section.section_name == "A"


# --- Placement Section selector (_sections_for) ---

def test_sections_selector_exposes_display_alongside_unchanged_canonical_value(db):
    items = students_ui._sections_for(db, 10, 100, "1", AL_ANDALUS_UUID)
    assert items == [{"id": 1000, "section_name": "A", "section_display": "1.1"}]


def test_sections_selector_falls_back_without_authorized_uuid(db):
    items = students_ui._sections_for(db, 20, 200, "1", SAME_NAME_DIFFERENT_UUID)
    assert items == [{"id": 2000, "section_name": "A", "section_display": "A"}]


# --- Talent frozen historical Learner Profile context ---

def _al_andalus_program_cycle(db, *, student, year_id, grade, population_effective_at):
    program = create_program(db, school_group_id=1, name=f"Program {grade}")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Framework")
    lineage = create_competency(db, school_group_id=1, program_id=program.id, code="ONE", name="One")
    competency, framework = add_framework_competency(
        db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        competency_id=lineage.id, expected_revision=framework.revision,
    )
    _, framework = upsert_rubric(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                                 expected_revision=framework.revision, name="Rubric")
    level, framework = add_rubric_level(
        db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, code="HIGH", label="High", numeric_value=90,
    )
    _, framework = upsert_descriptor(
        db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        framework_competency_id=competency.id, rubric_level_id=level.id,
        expected_revision=framework.revision, descriptor="descriptor",
    )
    activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    upsert_annual_configuration(db, school_group_id=1, program_id=program.id, academic_year_id=year_id,
                                is_enabled=True, eligible_grade_levels=[grade])
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=year_id,
                         framework_version_id=framework.id, title=f"Cycle {grade}",
                         population_effective_at=population_effective_at)
    open_cycle(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision,
              organization_authorized=True)
    db.commit()
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        cycle_id=cycle.id, student_id=student.id).one()
    start_assessment(db, school_group_id=1, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    db.commit()
    return program, cycle, member


def test_frozen_talent_context_uses_frozen_grade_section_not_current_student_placement(db):
    student, placement_a = _placement_for(
        db, school_group_id=1, branch_id=10, academic_year_id=100, planning_section_id=1000, name="Yousef",
    )
    # Cycle opens and freezes the population while the Student is still in
    # Grade 1 / Section A.
    _, _, member = _al_andalus_program_cycle(
        db, student=student, year_id=100, grade="1", population_effective_at=datetime(2026, 10, 1),
    )
    assert member.grade_level == "1" and member.section_name == "A"

    # The Student is later moved to a different Grade/Section - the frozen
    # Talent attribution must NOT follow this change.
    transition_placement(
        db, school_group_id=1, student_id=student.id, placement_id=placement_a.id,
        transition_at=datetime(2026, 11, 1), academic_year_id=100, branch_id=10,
        planning_section_id=1001,
    )
    db.commit()

    current_view = students_ui._placement_view(
        db, students_ui.resolve_placement(db, school_group_id=1, student_id=student.id, at=datetime(2026, 12, 1))
    )
    assert current_view["section_display"] == "2.2"  # current placement: Grade 2 / Section B

    profile = build_learner_profile(db, school_group_id=1, student_id=student.id)
    cycles = profile["programs"][0]["academic_years"][0]["cycles"]
    frozen = cycles[0]["frozen_context"]
    assert frozen["grade_level"] == "1" and frozen["section_name"] == "A"
    assert frozen["section_display"] == "1.1"  # frozen, not the Grade 2/Section B current placement


# --- Talent Student Assessment context (eligible-students) ---

def _admin(*, group, user_id):
    return models.User(user_id=user_id, username=f"admin{user_id}", role="Administrator",
                       user_type="TENANT", access_scope="ORGANIZATION", school_group_id=group, is_active=True)


def test_eligible_students_endpoint_exposes_section_display(db):
    student, _ = _placement_for(
        db, school_group_id=1, branch_id=10, academic_year_id=100, planning_section_id=1000, name="Huda",
    )
    program = create_program(db, school_group_id=1, name="Any Program")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Framework")
    activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    upsert_annual_configuration(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                                is_enabled=True, eligible_grade_levels=["1"])
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Cycle",
                         population_effective_at=datetime(2026, 10, 1))
    db.commit()

    app = FastAPI()
    app.include_router(talent_assessment_cycles_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _admin(group=1, user_id="9000000001")
    with TestClient(app) as client:
        response = client.get(f"/api/talent/assessment-cycles/{cycle.id}/eligible-students")
    assert response.status_code == 200
    members = response.json()["members"]
    assert any(m["student_id"] == student.id for m in members)
    row = next(m for m in members if m["student_id"] == student.id)
    assert row["grade_level"] == "1"
    assert row["section_name"] == "A"
    assert row["section_display"] == "1.1"


# --- Results & Analytics Grade/Section filter (planning-sections) ---

def test_planning_sections_filter_endpoint_exposes_section_display(db):
    app = FastAPI()
    app.include_router(talent_programs_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _admin(group=1, user_id="9000000002")
    with TestClient(app) as client:
        response = client.get(
            "/api/talent/programs/planning-sections",
            params={"academic_year_id": 100, "branch_id": 10, "grade_level": "1"},
        )
    assert response.status_code == 200
    items = response.json()
    assert items == [{"id": 1000, "section_name": "A", "section_display": "1.1"}]


def test_planning_sections_filter_endpoint_other_tenant_unaffected(db):
    app = FastAPI()
    app.include_router(talent_programs_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _admin(group=2, user_id="9000000003")
    with TestClient(app) as client:
        response = client.get(
            "/api/talent/programs/planning-sections",
            params={"academic_year_id": 200, "branch_id": 20, "grade_level": "1"},
        )
    assert response.status_code == 200
    items = response.json()
    assert items == [{"id": 2000, "section_name": "A", "section_display": "A"}]
