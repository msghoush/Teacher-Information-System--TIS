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
from routers.talent_learner_profiles import router
from student_academic_service import create_placement, create_student, transition_placement
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_educator_input_service import add_input
from talent_learner_profile_service import build_learner_profile
from talent_official_identification_service import record_decision
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, configure_review_candidate_policy,
    create_competency, create_framework_draft, create_program, transition_program, upsert_annual_configuration,
    upsert_descriptor, upsert_rubric,
)
from talent_review_candidate_service import evaluate_review_candidate, mark_reviewed
from talent_student_assessment_service import complete_assessment, set_competency_result, start_assessment


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
        models.Branch(id=10, school_group_id=1, name="A"), models.Branch(id=11, school_group_id=1, name="B"),
        models.Branch(id=20, school_group_id=2, name="Foreign"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=101, school_group_id=1, year_name="2027-2028"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=11, academic_year_id=101, grade_level="2", section_name="B", class_status="Current"),
    ])
    session.commit()
    yield session
    session.close()


def _profile_data(session):
    student = create_student(session, school_group_id=1, first_name="Maya", last_name="Learner")
    first = create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                             branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    _, second = transition_placement(session, school_group_id=1, student_id=student.id, placement_id=first.id,
                                     transition_at=datetime(2027, 9, 1), academic_year_id=101,
                                     branch_id=11, planning_section_id=1001)
    program = models.TalentProgram(school_group_id=1, name="Performing Arts", status="active")
    session.add(program); session.flush()
    first_input = add_input(session, school_group_id=1, student_id=student.id, program_id=program.id,
                            academic_year_id=100, observed_at=datetime(2026, 10, 1), category="observation",
                            content="Sensitive branch A input")
    second_input = add_input(session, school_group_id=1, student_id=student.id, program_id=program.id,
                             academic_year_id=101, observed_at=datetime(2027, 10, 1), category="context",
                             content="Sensitive branch B input")
    session.commit()
    return student, first, second, program, first_input, second_input


def _user(user_id, branch, scope, role="Editor"):
    return models.User(user_id=user_id, username=f"u{user_id}", role=role, user_type="TENANT", access_scope=scope,
                       school_group_id=1, branch_id=branch, academic_year_id=100, is_active=True)


def test_profile_filters_placement_and_sensitive_inputs_by_historical_branch(db):
    student, first, second, program, first_input, second_input = _profile_data(db)
    branch_profile = build_learner_profile(db, school_group_id=1, student_id=student.id, visible_branch_ids={10}, include_educator_inputs=False)
    assert [row["id"] for row in branch_profile["placements"]] == [first.id]
    assert "educator_inputs" not in branch_profile
    assert all(event["branch_id"] == 10 for event in branch_profile["timeline"] if event["event_type"].startswith("placement"))
    with_inputs = build_learner_profile(db, school_group_id=1, student_id=student.id, visible_branch_ids={10}, include_educator_inputs=True)
    assert [row["id"] for row in with_inputs["educator_inputs"]] == [first_input.id]
    assert "Sensitive branch B input" not in str(with_inputs)
    organization = build_learner_profile(db, school_group_id=1, student_id=student.id, visible_branch_ids=None, include_educator_inputs=True)
    assert [row["id"] for row in organization["placements"]] == [first.id, second.id]
    assert [row["id"] for row in organization["educator_inputs"]] == [first_input.id, second_input.id]


def test_profile_permission_is_independent_and_educator_domain_omits_without_view(db):
    student, *_ = _profile_data(db)
    no_profile = _user("3000000001", 10, "BRANCH", role="User")
    profile_only = _user("3000000002", 10, "BRANCH")
    educator_profile = _user("3000000003", 10, "BRANCH")
    db.add_all([no_profile, profile_only, educator_profile])
    db.add_all([
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_assessments.view", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_learner_profiles.view", is_allowed=True),
        models.RolePermission(school_group_id=1, role="User", permission_key="talent_assessments.view", is_allowed=True),
    ])
    db.commit()
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: no_profile
    with TestClient(app) as client:
        assert client.get(f"/api/talent/learner-profiles/{student.id}").status_code == 403
    app.dependency_overrides[get_current_user] = lambda: profile_only
    with TestClient(app) as client:
        body = client.get(f"/api/talent/learner-profiles/{student.id}").json()
        assert "educator_inputs" not in body
        assert "educator_input" not in str(body)
    db.add(models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_educator_inputs.view", is_allowed=True)); db.commit()
    app.dependency_overrides[get_current_user] = lambda: educator_profile
    with TestClient(app) as client:
        body = client.get(f"/api/talent/learner-profiles/{student.id}").json()
        assert len(body["educator_inputs"]) == 1


def _build_program_cycle_decision(session, *, student, year_id, section_id, grade, member_branch,
                                   population_effective_at, decision, name):
    """Builds one complete Program/Framework/Cycle/Assessment/Candidate/Identification
    chain for an already-existing Student, using the exact M3-M6 service authorities
    (mirrors tests/test_talent_review_official_identification_educator_input.py's
    `foundation`/`qualifying_candidate` pattern, adapted to reuse one shared Student
    across two independent frozen Branch contexts instead of creating a new Student)."""
    group_id = 1
    program = create_program(session, school_group_id=group_id, name=name)
    transition_program(session, school_group_id=group_id, program_id=program.id, target_status="active")
    framework = create_framework_draft(session, school_group_id=group_id, program_id=program.id, title="Framework")
    lineage = create_competency(session, school_group_id=group_id, program_id=program.id, code="ONE", name="One")
    competency, framework = add_framework_competency(
        session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
        competency_id=lineage.id, expected_revision=framework.revision,
    )
    _, framework = upsert_rubric(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                                 expected_revision=framework.revision, name="Rubric")
    level, framework = add_rubric_level(
        session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, code="HIGH", label="High", numeric_value=90,
    )
    _, framework = upsert_descriptor(
        session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
        framework_competency_id=competency.id, rubric_level_id=level.id,
        expected_revision=framework.revision, descriptor="descriptor",
    )
    _, framework = configure_review_candidate_policy(
        session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, is_enabled=True, match_mode="all", description=None,
        rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": competency.id,
                "rubric_level_id": level.id}],
    )
    activate_framework(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    upsert_annual_configuration(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                                is_enabled=True, eligible_grade_levels=[grade])
    cycle = create_cycle(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                         framework_version_id=framework.id, title=f"Cycle {name}",
                         population_effective_at=population_effective_at)
    open_cycle(session, school_group_id=group_id, cycle_id=cycle.id, expected_revision=cycle.revision,
              organization_authorized=True)
    session.commit()
    member = session.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        cycle_id=cycle.id, student_id=student.id).one()
    assert member.branch_id == member_branch
    assessment = start_assessment(session, school_group_id=group_id, cycle_id=member.cycle_id,
                                  cycle_population_member_id=member.id)
    revision = assessment.revision
    _, assessment = set_competency_result(
        session, school_group_id=group_id, assessment_id=assessment.id,
        framework_competency_id=competency.id, rubric_level_id=level.id,
        expected_revision=revision, evidence="private evidence text",
    )
    completed = complete_assessment(session, school_group_id=group_id, assessment_id=assessment.id,
                                    expected_revision=assessment.revision)
    candidate, outcome = evaluate_review_candidate(session, school_group_id=group_id, assessment_id=completed.id)
    assert outcome == "qualified"
    admin = models.User(user_id=f"90000{member_branch}", username=f"admin{member_branch}", role="Administrator",
                        user_type="TENANT", access_scope="ORGANIZATION", school_group_id=group_id, is_active=True)
    session.add(admin); session.commit()
    mark_reviewed(session, school_group_id=group_id, candidate_id=candidate.id, actor=admin)
    identification = record_decision(session, school_group_id=group_id, review_candidate_id=candidate.id,
                                     decision=decision, organization_authorized=True, actor=admin)
    session.commit()
    return program, cycle, member, completed, candidate, identification


def test_one_visible_branch_talent_record_does_not_unlock_the_other_branchs_history(db):
    """Section E (CRITICAL): a Student with Assessment/Review-Candidate/Official-
    Identification history frozen in two different Branches must show a Branch-A
    actor ONLY the Branch-A records - not all records merely because one Branch is
    authorized. Exercises the actual frozen `TalentAssessmentCyclePopulationMember`
    Branch discipline (M4/M5/M6), not just the simpler Placement/EducatorInput
    Branch columns already covered above."""
    student = create_student(db, school_group_id=1, first_name="Riley", last_name="Talent")
    placement_a = create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100,
                                   branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    transition_placement(db, school_group_id=1, student_id=student.id, placement_id=placement_a.id,
                         transition_at=datetime(2027, 9, 1), academic_year_id=101, branch_id=11,
                         planning_section_id=1001)
    db.commit()

    program_a, cycle_a, member_a, assessment_a, candidate_a, identification_a = _build_program_cycle_decision(
        db, student=student, year_id=100, section_id=1000, grade="1", member_branch=10,
        population_effective_at=datetime(2026, 10, 1), decision="identified", name="Program A",
    )
    program_b, cycle_b, member_b, assessment_b, candidate_b, identification_b = _build_program_cycle_decision(
        db, student=student, year_id=101, section_id=1001, grade="2", member_branch=11,
        population_effective_at=datetime(2027, 10, 1), decision="not_identified", name="Program B",
    )

    branch_a_profile = build_learner_profile(db, school_group_id=1, student_id=student.id,
                                             visible_branch_ids={10}, include_educator_inputs=False)
    visible_program_ids = {group["program"]["id"] for group in branch_a_profile["programs"]}
    assert visible_program_ids == {program_a.id}
    assessment_ids_seen = {
        cycle["assessment"]["id"]
        for group in branch_a_profile["programs"] for year in group["academic_years"] for cycle in year["cycles"]
    }
    assert assessment_ids_seen == {assessment_a.id}
    branch_a_cycle_item = branch_a_profile["programs"][0]["academic_years"][0]["cycles"][0]
    assert branch_a_cycle_item["review_candidate"]["id"] == candidate_a.id
    assert branch_a_cycle_item["official_identification"]["id"] == identification_a.id
    assert branch_a_cycle_item["official_identification"]["decision"] == "identified"
    timeline_ids = {(event["event_type"], event["id"]) for event in branch_a_profile["timeline"]}
    assert ("assessment_completed", assessment_b.id) not in timeline_ids
    assert ("review_candidate_created", candidate_b.id) not in timeline_ids
    assert ("official_identification_recorded", identification_b.id) not in timeline_ids
    assert ("assessment_completed", assessment_a.id) in timeline_ids
    assert ("review_candidate_created", candidate_a.id) in timeline_ids
    assert ("official_identification_recorded", identification_a.id) in timeline_ids

    branch_b_profile = build_learner_profile(db, school_group_id=1, student_id=student.id,
                                             visible_branch_ids={11}, include_educator_inputs=False)
    visible_program_ids_b = {group["program"]["id"] for group in branch_b_profile["programs"]}
    assert visible_program_ids_b == {program_b.id}
    branch_b_cycle_item = branch_b_profile["programs"][0]["academic_years"][0]["cycles"][0]
    assert branch_b_cycle_item["official_identification"]["decision"] == "not_identified"

    organization_profile = build_learner_profile(db, school_group_id=1, student_id=student.id,
                                                  visible_branch_ids=None, include_educator_inputs=False)
    assert {group["program"]["id"] for group in organization_profile["programs"]} == {program_a.id, program_b.id}


def test_profile_is_non_enumerating_without_any_visible_historical_record(db):
    student, *_ = _profile_data(db)
    with pytest.raises(Exception) as hidden:
        build_learner_profile(db, school_group_id=1, student_id=student.id, visible_branch_ids={999}, include_educator_inputs=False)
    assert getattr(hidden.value, "code", None) == "not_found"
    with pytest.raises(Exception) as foreign:
        build_learner_profile(db, school_group_id=2, student_id=student.id, visible_branch_ids=None)
    assert getattr(foreign.value, "code", None) == "not_found"


def test_route_returns_uniform_non_enumerating_404_shape(db):
    """Router-level check (not just the service function): a missing Student, a
    cross-tenant Student, and a same-tenant Student with zero authorized historical
    Branch visibility must all return the identical uniform 404 shape through the
    real HTTP route/dependency wiring, while a Student with authorized history
    returns 200 for the same actor."""
    student, first, *_ = _profile_data(db)
    other_group_student = create_student(db, school_group_id=2, first_name="Other", last_name="Tenant")
    no_visible_history_student = create_student(db, school_group_id=1, first_name="Unrelated", last_name="Branch11Only")
    create_placement(db, school_group_id=1, student_id=no_visible_history_student.id, academic_year_id=101,
                     branch_id=11, planning_section_id=1001, effective_from=datetime(2027, 9, 1))
    db.commit()
    branch_10_user = _user("4000000001", 10, "BRANCH")
    db.add_all([branch_10_user, models.RolePermission(
        school_group_id=1, role="Editor", permission_key="talent_learner_profiles.view", is_allowed=True,
    )])
    db.commit()
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: branch_10_user
    with TestClient(app) as client:
        missing = client.get("/api/talent/learner-profiles/999999")
        foreign = client.get(f"/api/talent/learner-profiles/{other_group_student.id}")
        no_visible_history = client.get(f"/api/talent/learner-profiles/{no_visible_history_student.id}")
        visible = client.get(f"/api/talent/learner-profiles/{student.id}")
        uniform_body = {"detail": "Student was not found.", "code": "not_found"}
        assert missing.status_code == 404 == foreign.status_code == no_visible_history.status_code
        assert missing.json() == foreign.json() == no_visible_history.json() == uniform_body
        assert visible.status_code == 200
        assert [row["id"] for row in visible.json()["placements"]] == [first.id]


def test_profile_composes_sensitive_view_permissions_without_metadata_leakage(db):
    student = create_student(db, school_group_id=1, first_name="Casey", last_name="Composition")
    placement = create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100,
                                 branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    db.commit()
    _, _, member, assessment, candidate, identification = _build_program_cycle_decision(
        db, student=student, year_id=100, section_id=1000, grade="1", member_branch=10,
        population_effective_at=datetime(2026, 10, 1), decision="identified", name="Composition Program",
    )
    educator_input = add_input(
        db, school_group_id=1, student_id=student.id, program_id=assessment.program_id,
        academic_year_id=100, observed_at=datetime(2026, 10, 2), category="observation",
        content="Sensitive composition input", cycle_population_member_id=member.id,
    )
    db.commit()
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db

    def response_for(*permission_keys):
        db.query(models.RolePermission).filter_by(school_group_id=1, role="Editor").delete()
        for key in permission_keys:
            db.add(models.RolePermission(school_group_id=1, role="Editor", permission_key=key, is_allowed=True))
        db.commit()
        user = _user("5000000001", 10, "BRANCH")
        app.dependency_overrides[get_current_user] = lambda: user
        with TestClient(app) as client:
            return client.get(f"/api/talent/learner-profiles/{student.id}")

    denied = response_for("talent_review_candidates.view")
    assert denied.status_code == 403

    base = response_for("talent_learner_profiles.view")
    assert base.status_code == 200
    base_item = base.json()["programs"][0]["academic_years"][0]["cycles"][0]
    assert base_item["assessment"]["id"] == assessment.id
    assert "review_candidate" not in base_item and "official_identification" not in base_item
    assert "educator_inputs" not in base.json()
    assert all("review_candidate" not in event["event_type"] and "official_identification" not in event["event_type"] and "educator_input" not in event["event_type"] for event in base.json()["timeline"])
    assert "review_candidate" not in str(base.json())
    assert "official_identification" not in str(base.json())
    assert "educator_input" not in str(base.json())
    assert "Sensitive composition input" not in str(base.json())

    candidates = response_for("talent_learner_profiles.view", "talent_review_candidates.view")
    candidate_item = candidates.json()["programs"][0]["academic_years"][0]["cycles"][0]
    assert candidate_item["review_candidate"]["id"] == candidate.id
    assert "official_identification" not in candidate_item and "educator_inputs" not in candidates.json()
    assert any(event["event_type"] == "review_candidate_created" for event in candidates.json()["timeline"])
    assert not any(event["event_type"] == "official_identification_recorded" for event in candidates.json()["timeline"])

    identifications = response_for("talent_learner_profiles.view", "talent_official_identifications.view")
    identification_item = identifications.json()["programs"][0]["academic_years"][0]["cycles"][0]
    assert identification_item["official_identification"]["id"] == identification.id
    assert "review_candidate" not in identification_item and "educator_inputs" not in identifications.json()
    assert any(event["event_type"] == "official_identification_recorded" for event in identifications.json()["timeline"])
    assert not any(event["event_type"] == "review_candidate_created" for event in identifications.json()["timeline"])

    educator = response_for("talent_learner_profiles.view", "talent_educator_inputs.view")
    educator_item = educator.json()["programs"][0]["academic_years"][0]["cycles"][0]
    assert [row["id"] for row in educator.json()["educator_inputs"]] == [educator_input.id]
    assert "review_candidate" not in educator_item and "official_identification" not in educator_item

    all_sections = response_for("talent_learner_profiles.view", "talent_review_candidates.view",
                                "talent_official_identifications.view", "talent_educator_inputs.view")
    all_item = all_sections.json()["programs"][0]["academic_years"][0]["cycles"][0]
    assert all_item["review_candidate"]["id"] == candidate.id
    assert all_item["official_identification"]["id"] == identification.id
    assert all_sections.json()["educator_inputs"][0]["id"] == educator_input.id

    transition_placement(db, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2027, 9, 1), academic_year_id=101, branch_id=11,
                         planning_section_id=1001)
    db.commit()
    after_transfer = response_for("talent_learner_profiles.view", "talent_review_candidates.view",
                                  "talent_official_identifications.view", "talent_educator_inputs.view")
    assert after_transfer.status_code == 200
    assert [row["id"] for row in after_transfer.json()["placements"]] == [placement.id]