"""M6 continuation: Review workflow, Official Identification, and Educator Input.

Covers the 18 approved governance decisions layered on top of the existing
Review Candidate materialization slice (see
tests/test_talent_review_candidate_foundation.py for that foundation's own
coverage, preserved and updated separately). Deliberately does NOT cover
anything explicitly deferred by these decisions: revocation, supersession of
Official Identification, a second identification decision, re-identification,
`deferred`/`revoked`/`superseded`/`re-identified`/`reinstated`/`expired`
states, a generic free-text review-note system, or Educator Input
analytics/export/AI/attachments.
"""

import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_educator_inputs import router as educator_inputs_router
from routers.talent_official_identifications import router as official_identifications_router
from routers.talent_review_candidates import router as review_candidates_router
from student_academic_service import create_placement, create_student, transition_placement
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_educator_input_service import (
    TalentEducatorInputError, add_input, amend_input, get_input, input_history,
    input_payload, list_inputs,
)
from talent_official_identification_service import (
    TalentOfficialIdentificationError, get_identification, record_decision,
)
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, create_competency,
    create_framework_draft, create_program, transition_program, upsert_annual_configuration,
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
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=11, academic_year_id=100, grade_level="1", section_name="B", class_status="Current"),
        models.PlanningSection(id=2000, branch_id=20, academic_year_id=200, grade_level="1", section_name="A", class_status="Current"),
    ])
    session.commit()
    yield engine, session
    session.close()


def rubric_rule(competency, level):
    return {"rule_type": "rubric_level_at_or_above", "framework_competency_id": competency.id, "rubric_level_id": level.id}


def foundation(session, *, policy_fn=None, match_mode="all", student_count=1, branch=10,
               group_id=1, year_id=100, section_id=1000, name="Program"):
    program = create_program(session, school_group_id=group_id, name=name)
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
    for code, value in zip(("LOW", "MID", "HIGH"), (60, 75, 90)):
        level, framework = add_rubric_level(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, code=code, label=code.title(), numeric_value=value,
        )
        levels.append(level)
    for competency in competencies:
        for lvl in levels:
            _, framework = upsert_descriptor(
                session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                framework_competency_id=competency.id, rubric_level_id=lvl.id,
                expected_revision=framework.revision, descriptor=f"{competency.id}-{lvl.id}",
            )
    if policy_fn is not None:
        from talent_program_service import configure_review_candidate_policy
        rules = policy_fn(competencies, levels)
        _, framework = configure_review_candidate_policy(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True,
            match_mode=match_mode, description=None, rules=rules,
        )
    activate_framework(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    upsert_annual_configuration(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                                is_enabled=True, eligible_grade_levels=["1"])
    students = []
    for index in range(student_count):
        student = create_student(session, school_group_id=group_id, first_name=f"Student{index}", last_name="Test")
        placement = create_placement(session, school_group_id=group_id, student_id=student.id, academic_year_id=year_id,
                                     branch_id=branch, planning_section_id=section_id, effective_from=datetime(2026, 9, 1))
        students.append((student, placement))
    cycle = create_cycle(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                         framework_version_id=framework.id, title="Cycle",
                         population_effective_at=datetime(2026, 10, 1))
    open_cycle(session, school_group_id=group_id, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    session.commit()
    members = []
    for student, placement in students:
        member = session.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id, student_id=student.id).one()
        members.append((student, placement, member))
    return program, framework, cycle, members, competencies, levels


def complete_with_levels(session, member, competencies, level_choices, *, group_id=1):
    assessment = start_assessment(session, school_group_id=group_id, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    revision = assessment.revision
    for competency, lvl in zip(competencies, level_choices):
        _, assessment = set_competency_result(
            session, school_group_id=group_id, assessment_id=assessment.id,
            framework_competency_id=competency.id, rubric_level_id=lvl.id,
            expected_revision=revision, evidence="private evidence text",
        )
        revision = assessment.revision
    return complete_assessment(session, school_group_id=group_id, assessment_id=assessment.id, expected_revision=revision)


def qualifying_candidate(session, *, group_id=1, branch=10, year_id=100, section_id=1000):
    _, framework, cycle, members, competencies, levels = foundation(
        session, group_id=group_id, branch=branch, year_id=year_id, section_id=section_id,
        policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    student, placement, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]], group_id=group_id)
    candidate, outcome = evaluate_review_candidate(session, school_group_id=group_id, assessment_id=completed.id)
    assert outcome == "qualified"
    return candidate, student, placement, member, completed, cycle


def _user(user_id, *, branch, scope, role="Administrator"):
    return models.User(user_id=user_id, username=f"user{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=1, branch_id=branch, academic_year_id=100, is_active=True)


# ---------------------------------------------------------------------------
# Decision 2/14 - Review workflow
# ---------------------------------------------------------------------------

def test_qualifying_candidate_starts_pending_review(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    assert candidate.status == "pending_review"
    assert candidate.reviewed_by_user_id is None and candidate.reviewed_at is None


def test_mark_reviewed_requires_manage_permission_at_router(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    editor = _user("2000000001", branch=10, scope="ORGANIZATION", role="Editor")
    session.add(editor)
    session.commit()
    app = FastAPI()
    app.include_router(review_candidates_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: editor
    with TestClient(app) as client:
        response = client.post(f"/api/talent/review-candidates/{candidate.id}/review")
        assert response.status_code == 403
    session.refresh(candidate)
    assert candidate.status == "pending_review"


def test_mark_reviewed_persists_actor_and_time_and_is_one_way(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    admin = _user("2000000002", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    reviewed = mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    assert reviewed.status == "reviewed"
    assert reviewed.reviewed_by_user_id == "2000000002"
    assert reviewed.reviewed_at is not None
    audit = session.query(models.TalentAssessmentAudit).filter_by(
        resource_type="review_candidate_review", resource_id=candidate.id,
    ).one()
    assert audit.action == "reviewed"

    from talent_review_candidate_service import TalentReviewCandidateError
    with pytest.raises(TalentReviewCandidateError) as exc:
        mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    assert exc.value.code == "already_reviewed"


def test_review_does_not_alter_assessment_evidence_or_auto_identify(db):
    _, session = db
    candidate, student, placement, member, completed, cycle = qualifying_candidate(session)

    def snapshot():
        assessment_row = session.query(models.TalentStudentAssessment).filter_by(id=completed.id).one()
        assessment_dict = {c.name: getattr(assessment_row, c.name) for c in models.TalentStudentAssessment.__table__.columns}
        result_rows = session.query(models.TalentStudentCompetencyResult).filter_by(assessment_id=completed.id).order_by(models.TalentStudentCompetencyResult.id).all()
        results_dict = [{c.name: getattr(row, c.name) for c in models.TalentStudentCompetencyResult.__table__.columns} for row in result_rows]
        return assessment_dict, results_dict

    before = snapshot()
    admin = _user("2000000003", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    after = snapshot()
    assert before == after
    assert session.query(models.TalentOfficialIdentification).filter_by(review_candidate_id=candidate.id).count() == 0


# ---------------------------------------------------------------------------
# Decisions 3-7, 17 - Official Identification
# ---------------------------------------------------------------------------

def test_pending_review_candidate_cannot_be_identified(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    with pytest.raises(TalentOfficialIdentificationError) as exc:
        record_decision(session, school_group_id=1, review_candidate_id=candidate.id, decision="identified",
                        organization_authorized=True)
    assert exc.value.code == "candidate_not_reviewed"
    assert session.query(models.TalentOfficialIdentification).count() == 0


def test_reviewed_candidate_can_be_identified_and_decision_is_durable(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    admin = _user("2000000010", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    row = record_decision(session, school_group_id=1, review_candidate_id=candidate.id, decision="identified",
                          organization_authorized=True, actor=admin)
    session.commit()
    assert row.decision == "identified"
    assert row.decided_by_user_id == "2000000010"
    assert row.decided_at is not None
    fetched = get_identification(session, school_group_id=1, identification_id=row.id)
    assert fetched.decision == "identified"


def test_not_identified_is_durable_and_exactly_one_decision_per_candidate(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    admin = _user("2000000011", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    row = record_decision(session, school_group_id=1, review_candidate_id=candidate.id, decision="not_identified",
                          organization_authorized=True, actor=admin)
    session.commit()
    assert row.decision == "not_identified"

    # Exactly one decision per candidate - a second attempt is cleanly rejected
    # (service-layer check), not an unhandled IntegrityError.
    with pytest.raises(TalentOfficialIdentificationError) as exc:
        record_decision(session, school_group_id=1, review_candidate_id=candidate.id, decision="identified",
                        organization_authorized=True, actor=admin)
    assert exc.value.code == "already_decided"
    assert session.query(models.TalentOfficialIdentification).filter_by(review_candidate_id=candidate.id).count() == 1

    # The DB-level unique constraint independently backs this up (layered
    # enforcement, matching M2's stale-write pattern): a raw insert bypassing
    # the service check must also fail.
    from sqlalchemy.exc import IntegrityError
    duplicate = models.TalentOfficialIdentification(
        school_group_id=1, cycle_id=row.cycle_id, cycle_population_member_id=row.cycle_population_member_id,
        student_id=row.student_id, program_id=row.program_id, academic_year_id=row.academic_year_id,
        framework_version_id=row.framework_version_id, assessment_id=row.assessment_id,
        review_candidate_id=candidate.id, decision="identified",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    # No mutation/revocation path exists anywhere in this service module.
    import talent_official_identification_service as svc
    assert not hasattr(svc, "revoke_decision")
    assert not hasattr(svc, "update_decision")
    assert not hasattr(svc, "supersede_decision")
    assert not hasattr(svc, "reidentify")


def test_record_permission_and_organization_scope_are_both_required(db):
    """The single most important test: BOTH the .record permission AND
    organization/global access scope are required - a Branch-scoped actor is
    denied even if somehow granted the .record permission (Decision 6)."""
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    admin = _user("2000000020", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()

    # Branch-scoped actor WITHOUT the permission -> denied at the permission gate.
    branch_user_no_perm = _user("2000000021", branch=10, scope="BRANCH", role="Editor")
    session.add(branch_user_no_perm)
    session.commit()
    app = FastAPI()
    app.include_router(official_identifications_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: branch_user_no_perm
    with TestClient(app) as client:
        response = client.post("/api/talent/official-identifications", json={
            "review_candidate_id": candidate.id, "decision": "identified",
        })
        assert response.status_code == 403

    # Branch-scoped actor WITH the .record permission explicitly granted -
    # still denied because access scope is BRANCH, not organization/global.
    # (A fresh User object is used since `auth.has_permission` caches allowed
    # keys per-user-object once resolved.)
    session.add(models.RolePermission(
        school_group_id=1, role="Editor", permission_key="talent_official_identifications.record", is_allowed=True,
    ))
    session.commit()
    branch_user_with_perm = _user("2000000021", branch=10, scope="BRANCH", role="Editor")
    app.dependency_overrides[get_current_user] = lambda: branch_user_with_perm
    with TestClient(app) as client:
        response = client.post("/api/talent/official-identifications", json={
            "review_candidate_id": candidate.id, "decision": "identified",
        })
        assert response.status_code == 403
        assert response.json()["code"] == "organization_authority_required"
    assert session.query(models.TalentOfficialIdentification).count() == 0

    # Organization-scoped actor WITH the permission succeeds (the AND is
    # satisfiable, not permanently broken).
    org_user = _user("2000000022", branch=None, scope="ORGANIZATION", role="Editor")
    session.add(org_user)
    session.add(models.RolePermission(
        school_group_id=1, role="Editor", permission_key="talent_official_identifications.record", is_allowed=True,
    ))
    session.commit()
    app.dependency_overrides[get_current_user] = lambda: org_user
    with TestClient(app) as client:
        response = client.post("/api/talent/official-identifications", json={
            "review_candidate_id": candidate.id, "decision": "identified",
        })
        assert response.status_code == 201
    assert session.query(models.TalentOfficialIdentification).count() == 1


def test_second_decision_via_router_is_409_not_crash(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    admin = _user("2000000030", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    app = FastAPI()
    app.include_router(official_identifications_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app, raise_server_exceptions=False) as client:
        first = client.post("/api/talent/official-identifications", json={
            "review_candidate_id": candidate.id, "decision": "identified",
        })
        assert first.status_code == 201
        second = client.post("/api/talent/official-identifications", json={
            "review_candidate_id": candidate.id, "decision": "not_identified",
        })
        assert second.status_code == 409
        assert second.json()["code"] == "already_decided"


def test_identification_frozen_branch_visibility_survives_transfer(db):
    _, session = db
    candidate, student, placement, member, completed, cycle = qualifying_candidate(session, branch=10)
    admin = _user("2000000040", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    row = record_decision(session, school_group_id=1, review_candidate_id=candidate.id, decision="identified",
                          organization_authorized=True, actor=admin)
    session.commit()

    branch_user = _user("2000000041", branch=10, scope="BRANCH")
    other_branch_user = _user("2000000042", branch=11, scope="BRANCH")
    session.add_all([branch_user, other_branch_user])
    session.commit()
    app = FastAPI()
    app.include_router(official_identifications_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/official-identifications/{row.id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other_branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/official-identifications/{row.id}").status_code == 404

    # A current Student transfer after the decision must not reinterpret the
    # frozen Branch-based read access.
    transition_placement(session, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.commit()
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/official-identifications/{row.id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other_branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/official-identifications/{row.id}").status_code == 404


def test_identification_structurally_distinct_from_review_candidate(db):
    _, session = db
    candidate, *_ = qualifying_candidate(session)
    admin = _user("2000000050", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    mark_reviewed(session, school_group_id=1, candidate_id=candidate.id, actor=admin)
    session.commit()
    row = record_decision(session, school_group_id=1, review_candidate_id=candidate.id, decision="identified",
                          organization_authorized=True, actor=admin)
    session.commit()
    assert row.id != candidate.id or type(row) is not type(candidate)
    assert models.TalentOfficialIdentification.__tablename__ != models.TalentReviewCandidate.__tablename__
    assert not hasattr(candidate, "decision")


# ---------------------------------------------------------------------------
# Decisions 8-13 - Educator Input
# ---------------------------------------------------------------------------

def test_requires_valid_historical_placement_rejects_cleanly(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="EI Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="No", last_name="Placement")
    session.commit()
    with pytest.raises(TalentEducatorInputError) as exc:
        add_input(
            session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
            observed_at=datetime(2026, 9, 15), category="observation", content="Some observation text.",
        )
    assert exc.value.code == "no_historical_placement"
    assert session.query(models.TalentEducatorInput).count() == 0


def test_resolved_placement_success_and_category_content_validation(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="EI Program 2")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Has", last_name="Placement")
    create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    session.commit()

    with pytest.raises(TalentEducatorInputError) as exc:
        add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                  observed_at=datetime(2026, 9, 15), category="not_a_real_category", content="text")
    assert exc.value.code == "invalid_category"

    with pytest.raises(TalentEducatorInputError) as exc:
        add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                  observed_at=datetime(2026, 9, 15), category="observation", content="   ")
    assert exc.value.code == "invalid_input"

    with pytest.raises(TalentEducatorInputError) as exc:
        add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                  observed_at=datetime(2026, 9, 15), category="observation", content="x" * 2001)
    assert exc.value.code == "invalid_input"

    row = add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                    observed_at=datetime(2026, 9, 15), category="context", content="A valid bounded note.")
    session.commit()
    assert row.branch_id == 10
    assert row.grade_level == "1" and row.section_name == "A"
    assert row.academic_placement_id is not None


def test_frozen_cycle_context_wins_over_resolved_placement(db):
    _, session = db
    candidate, student, placement, member, completed, cycle = qualifying_candidate(session, branch=10)
    # Transfer the Student to a different Branch AFTER the Cycle froze the
    # population - a naive observed_at resolution against CURRENT placement
    # history would now resolve to Branch 11, not the frozen Branch 10.
    transition_placement(session, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2026, 11, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.commit()
    observed_at = datetime(2026, 11, 15)  # after the transfer

    row = add_input(
        session, school_group_id=1, student_id=student.id, program_id=cycle.program_id,
        academic_year_id=100, observed_at=observed_at, category="observation", content="Frozen context wins.",
        cycle_population_member_id=member.id,
    )
    session.commit()
    assert row.branch_id == 10  # frozen member Branch, not the post-transfer Branch 11
    assert row.cycle_population_member_id == member.id


def test_optional_context_alignment_is_validated_not_trusted(db):
    _, session = db
    candidate, student, placement, member, completed, cycle = qualifying_candidate(session, branch=10)
    other_program = create_program(session, school_group_id=1, name="Other Program")
    transition_program(session, school_group_id=1, program_id=other_program.id, target_status="active")
    session.commit()
    with pytest.raises(TalentEducatorInputError) as exc:
        add_input(
            session, school_group_id=1, student_id=student.id, program_id=other_program.id,
            academic_year_id=100, observed_at=datetime(2026, 10, 15), category="observation",
            content="Mismatched Program.", cycle_population_member_id=member.id,
        )
    assert exc.value.code == "context_mismatch"


def test_permission_separation_add_view_amend(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Perm Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Perm", last_name="Student")
    create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    session.commit()

    viewer_only = _user("2000000060", branch=10, scope="ORGANIZATION", role="Editor")
    session.add_all([
        viewer_only,
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_educator_inputs.view", is_allowed=True),
        # Deliberately NOT granting talent_educator_inputs.add/.amend, and
        # deliberately granting an unrelated Talent permission family to prove
        # no cross-family substitution occurs.
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_assessments.manage", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_review_candidates.manage", is_allowed=True),
    ])
    session.commit()
    app = FastAPI()
    app.include_router(educator_inputs_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: viewer_only
    with TestClient(app) as client:
        add_response = client.post("/api/talent/educator-inputs", json={
            "student_id": student.id, "program_id": program.id, "academic_year_id": 100,
            "observed_at": "2026-09-15T00:00:00", "category": "observation", "content": "Blocked add.",
        })
        assert add_response.status_code == 403
        list_response = client.get("/api/talent/educator-inputs")
        assert list_response.status_code == 200
    assert session.query(models.TalentEducatorInput).count() == 0


def test_branch_visibility_from_persisted_snapshot_survives_transfer(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Snapshot Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Snap", last_name="Shot")
    placement = create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                                 branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    session.commit()
    admin = _user("2000000070", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    row = add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                    observed_at=datetime(2026, 9, 15), category="observation", content="Branch snapshot test.",
                    actor=admin)
    session.commit()
    assert row.branch_id == 10

    branch_user = _user("2000000071", branch=10, scope="BRANCH")
    other_branch_user = _user("2000000072", branch=11, scope="BRANCH")
    session.add_all([branch_user, other_branch_user])
    session.commit()
    app = FastAPI()
    app.include_router(educator_inputs_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/educator-inputs/{row.id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other_branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/educator-inputs/{row.id}").status_code == 404

    # Transfer to Branch 11 after the input was recorded: the PERSISTED
    # historical snapshot (Branch 10), not current Placement, still governs access.
    transition_placement(session, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.commit()
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/educator-inputs/{row.id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other_branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/educator-inputs/{row.id}").status_code == 404


def test_amendment_creates_new_row_and_lineage_is_walkable(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Amend Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Amend", last_name="Student")
    create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    session.commit()
    original = add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                         observed_at=datetime(2026, 9, 15), category="observation", content="Original text.")
    session.commit()
    original_content = original.content
    original_created_at = original.created_at

    amended, superseded = amend_input(
        session, school_group_id=1, student_id=student.id, program_id=program.id,
        supersedes_educator_input_id=original.id, category="context", content="Amended text.",
    )
    session.commit()
    assert amended.id != original.id
    assert amended.supersedes_educator_input_id == original.id
    assert amended.content == "Amended text."
    # Original row is completely unchanged - no in-place edit.
    session.refresh(original)
    assert original.content == original_content
    assert original.created_at == original_created_at
    assert original.category == "observation"

    # Default reads return only the current/latest version.
    current = list_inputs(session, school_group_id=1, student_id=student.id, program_id=program.id)
    assert [row.id for row in current] == [amended.id]

    # Explicit history read returns the full chain, oldest -> newest.
    chain = input_history(session, school_group_id=1, input_id=amended.id)
    assert [row.id for row in chain] == [original.id, amended.id]
    chain_from_original = input_history(session, school_group_id=1, input_id=original.id)
    assert [row.id for row in chain_from_original] == [original.id, amended.id]

    # A row that has already been superseded cannot be amended again (keeps
    # the lineage a single walkable chain, never a branching tree).
    with pytest.raises(TalentEducatorInputError) as exc:
        amend_input(session, school_group_id=1, student_id=student.id, program_id=program.id,
                   supersedes_educator_input_id=original.id, category="observation", content="Branch attempt.")
    assert exc.value.code == "already_superseded"


def test_cross_tenant_and_cross_student_supersession_rejected(db):
    _, session = db
    program1 = create_program(session, school_group_id=1, name="Tenant1 Program")
    transition_program(session, school_group_id=1, program_id=program1.id, target_status="active")
    student1 = create_student(session, school_group_id=1, first_name="Tenant1", last_name="Student")
    create_placement(session, school_group_id=1, student_id=student1.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    student1b = create_student(session, school_group_id=1, first_name="Tenant1B", last_name="Student")
    create_placement(session, school_group_id=1, student_id=student1b.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    program2 = create_program(session, school_group_id=2, name="Tenant2 Program")
    transition_program(session, school_group_id=2, program_id=program2.id, target_status="active")
    student2 = create_student(session, school_group_id=2, first_name="Tenant2", last_name="Student")
    create_placement(session, school_group_id=2, student_id=student2.id, academic_year_id=200,
                     branch_id=20, planning_section_id=2000, effective_from=datetime(2026, 9, 1))
    session.commit()

    original = add_input(session, school_group_id=1, student_id=student1.id, program_id=program1.id, academic_year_id=100,
                         observed_at=datetime(2026, 9, 15), category="observation", content="Tenant 1 original.")
    session.commit()

    # Cross-Student supersession: same tenant, different Student -> rejected.
    with pytest.raises(TalentEducatorInputError) as exc:
        amend_input(session, school_group_id=1, student_id=student1b.id, program_id=program1.id,
                   supersedes_educator_input_id=original.id, category="observation", content="Wrong student.")
    assert exc.value.code == "cross_student_supersession"

    # Cross-tenant supersession: a tenant-2 caller cannot even find the
    # tenant-1 row (uniform not_found, non-enumerating).
    with pytest.raises(TalentEducatorInputError) as exc:
        amend_input(session, school_group_id=2, student_id=student2.id, program_id=program2.id,
                   supersedes_educator_input_id=original.id, category="observation", content="Wrong tenant.")
    assert exc.value.code == "not_found"
    assert session.query(models.TalentEducatorInput).filter_by(school_group_id=1).count() == 1
    assert session.query(models.TalentEducatorInput).filter_by(school_group_id=2).count() == 0


def test_no_hard_delete_path_exists(db):
    import talent_educator_input_service as svc
    assert not hasattr(svc, "delete_input")
    assert not hasattr(svc, "remove_input")
    assert not hasattr(svc, "hard_delete_input")


def test_sensitive_body_text_absent_from_audit(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Audit Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Audit", last_name="Student")
    create_placement(session, school_group_id=1, student_id=student.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    session.commit()
    secret_text = "This is sensitive qualitative narrative text that must never leak into audit payloads."
    row = add_input(session, school_group_id=1, student_id=student.id, program_id=program.id, academic_year_id=100,
                    observed_at=datetime(2026, 9, 15), category="supporting_evidence", content=secret_text)
    session.commit()
    audit = session.query(models.TalentAssessmentAudit).filter_by(
        resource_type="educator_input", resource_id=row.id, action="add",
    ).one()
    assert audit.before_json is None
    assert secret_text not in (audit.after_json or "")
    assert "content" not in json.loads(audit.after_json)

    amended, _ = amend_input(session, school_group_id=1, student_id=student.id, program_id=program.id,
                             supersedes_educator_input_id=row.id, category="supporting_evidence",
                             content="Different but still sensitive amended text.")
    session.commit()
    amend_audit = session.query(models.TalentAssessmentAudit).filter_by(
        resource_type="educator_input", resource_id=amended.id, action="amend",
    ).one()
    assert secret_text not in (amend_audit.before_json or "")
    assert "Different but still sensitive amended text." not in (amend_audit.after_json or "")
    assert "content" not in json.loads(amend_audit.before_json)
    assert "content" not in json.loads(amend_audit.after_json)


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_migration_007_is_idempotent_and_creates_new_tables(db):
    engine, session = db
    session.close()
    with engine.begin() as connection:
        models.TalentOfficialIdentification.__table__.drop(connection)
        models.TalentEducatorInput.__table__.drop(connection)
        db_migrations._talent_review_workflow_identification_educator_input_foundation(engine, connection)
        db_migrations._talent_review_workflow_identification_educator_input_foundation(engine, connection)
    names = inspect(engine).get_table_names()
    assert "talent_official_identifications" in names
    assert "talent_educator_inputs" in names
    assert any(
        row.migration_id == "20260904_007_talent_review_workflow_identification_educator_input_foundation"
        for row in db_migrations.MIGRATIONS
    )


def test_branch_actor_cannot_add_or_amend_into_foreign_historical_branch(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Branch Guard Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Scoped", last_name="Student")
    placement = create_placement(
        session, school_group_id=1, student_id=student.id, academic_year_id=100,
        branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1),
    )
    branch_user = _user("2000000091", branch=10, scope="BRANCH")
    session.add(branch_user)
    session.commit()
    app = FastAPI()
    app.include_router(educator_inputs_router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: branch_user

    with TestClient(app) as client:
        original_response = client.post("/api/talent/educator-inputs", json={
            "student_id": student.id, "program_id": program.id, "academic_year_id": 100,
            "observed_at": "2026-10-01T00:00:00Z", "category": "observation",
            "content": "Authorized historical observation.",
        })
        assert original_response.status_code == 201
        original_id = original_response.json()["id"]

    transition_placement(
        session, school_group_id=1, student_id=student.id, placement_id=placement.id,
        transition_at=datetime(2026, 11, 1), academic_year_id=100,
        branch_id=11, planning_section_id=1001,
    )
    session.commit()
    with TestClient(app) as client:
        denied_add = client.post("/api/talent/educator-inputs", json={
            "student_id": student.id, "program_id": program.id, "academic_year_id": 100,
            "observed_at": "2026-12-01T00:00:00Z", "category": "context",
            "content": "Must not cross the historical Branch boundary.",
        })
        assert denied_add.status_code == 404
        denied_amend = client.post(f"/api/talent/educator-inputs/{original_id}/amend", json={
            "student_id": student.id, "program_id": program.id,
            "observed_at": "2026-12-01T00:00:00Z", "category": "context",
            "content": "Must not move the lineage into another Branch.",
        })
        assert denied_amend.status_code == 404
    assert session.query(models.TalentEducatorInput).count() == 1


def test_identification_context_cannot_drift_from_review_candidate_at_db_boundary(db):
    _, session = db
    _, _, _, members, competencies, levels = foundation(
        session, student_count=2, name="Identification Scope Program",
        policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    candidates = []
    for _, _, member in members:
        assessment = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
        candidate, _ = evaluate_review_candidate(session, school_group_id=1, assessment_id=assessment.id)
        mark_reviewed(session, school_group_id=1, candidate_id=candidate.id)
        candidates.append(candidate)
    session.commit()
    first, second = candidates
    session.add(models.TalentOfficialIdentification(
        school_group_id=second.school_group_id, cycle_id=second.cycle_id,
        cycle_population_member_id=second.cycle_population_member_id,
        student_id=second.student_id, program_id=second.program_id,
        academic_year_id=second.academic_year_id,
        framework_version_id=second.framework_version_id,
        assessment_id=second.assessment_id, review_candidate_id=first.id,
        decision="identified",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_educator_input_lineage_fork_is_rejected_by_database(db):
    _, session = db
    program = create_program(session, school_group_id=1, name="Linear Input Program")
    transition_program(session, school_group_id=1, program_id=program.id, target_status="active")
    student = create_student(session, school_group_id=1, first_name="Linear", last_name="Student")
    create_placement(
        session, school_group_id=1, student_id=student.id, academic_year_id=100,
        branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1),
    )
    original = add_input(
        session, school_group_id=1, student_id=student.id, program_id=program.id,
        academic_year_id=100, observed_at=datetime(2026, 10, 1),
        category="observation", content="Original",
    )
    amend_input(
        session, school_group_id=1, student_id=student.id, program_id=program.id,
        supersedes_educator_input_id=original.id, category="context", content="First amendment",
    )
    session.commit()
    session.add(models.TalentEducatorInput(
        school_group_id=1, student_id=student.id, program_id=program.id,
        academic_year_id=100, observed_at=datetime(2026, 10, 1),
        academic_placement_id=original.academic_placement_id, branch_id=10,
        planning_section_id=1000, grade_level="1", section_name="A",
        category="context", content="Fork", supersedes_educator_input_id=original.id,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
