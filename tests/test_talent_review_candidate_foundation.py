"""M6 deterministic Review Candidate evaluation and materialization tests.

Only the scope actually implemented in M6 is covered here: deterministic
candidate evaluation/materialization for a Completed Assessment. Official
Identification, Educator Input, and a review-lifecycle ("Pending Review")
layer are NOT implemented (see the M6 governance review) and are therefore
not asserted here.
"""

import json
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
from routers.talent_review_candidates import router
from student_academic_service import create_placement, create_student, transition_placement
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, configure_kpi,
    configure_review_candidate_policy, create_competency, create_framework_draft,
    create_program, transition_program, upsert_annual_configuration, upsert_descriptor,
    upsert_rubric,
)
from talent_review_candidate_service import TalentReviewCandidateError, evaluate_review_candidate
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


def kpi_rule(threshold):
    return {"rule_type": "kpi_at_or_above", "threshold_value": threshold}


def foundation(session, *, kpi=False, policy_fn=None, match_mode="all", student_count=1, branch=10,
               group_id=1, year_id=100, section_id=1000, name="Program",
               level_numeric_values=(60, 75, 90)):
    """Build a Program/Framework/Cycle with an optional Review Candidate Policy.

    ``policy_fn``, if given, is called as ``policy_fn(competencies, levels)`` and
    must return a list of rule dicts (see ``rubric_rule``/``kpi_rule``) - the
    Framework Competency/Rubric Level rows only exist once this helper has
    created them, so the policy cannot be built before that point.
    """
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
    for code, value in zip(("LOW", "MID", "HIGH"), level_numeric_values):
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
    if kpi:
        _, framework = configure_kpi(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, result_scale_min=0, result_scale_max=100,
            interpretation="Framework-specific result",
            components=[{"framework_competency_id": item.id, "weight_basis_points": 5000} for item in competencies],
        )
    if policy_fn is not None:
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


def test_evaluation_requires_completed_assessment(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(session)
    _, _, member = members[0]
    assessment = start_assessment(session, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    with pytest.raises(TalentReviewCandidateError) as exc:
        evaluate_review_candidate(session, school_group_id=1, assessment_id=assessment.id)
    assert exc.value.code == "assessment_not_completed"
    assert session.query(models.TalentReviewCandidate).count() == 0


def test_no_policy_means_no_candidate(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(session)
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert candidate is None and outcome == "no_policy"
    assert session.query(models.TalentReviewCandidate).count() == 0
    assert session.query(models.TalentAssessmentAudit).filter_by(resource_type="review_candidate").count() == 0


def test_rubric_only_policy_qualifies_without_kpi(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, kpi=False,
        policy_fn=lambda c, l: [rubric_rule(c[0], l[2])],
    )
    _, _, member = members[0]
    # Competency TWO's level is irrelevant to the single-rule policy; qualitative
    # Programs (no KPI, and here effectively unused numeric values) still work.
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[0]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert outcome == "qualified" and candidate is not None
    assert candidate.match_mode == "all"
    audit = session.query(models.TalentAssessmentAudit).filter_by(resource_type="review_candidate", resource_id=candidate.id).one()
    assert audit.action == "materialize"


def test_rubric_rule_uses_display_order_not_numeric_value(db):
    _, session = db
    # LOW is added first (display_order=1) with a HIGH numeric_value (100); HIGH is
    # added last (display_order=3) with a LOW numeric_value (10). A rule targeting
    # LOW (order 1) must be satisfied by a result at HIGH (order 3) even though
    # HIGH's numeric_value (10) is far below LOW's numeric_value (100).
    _, framework, cycle, members, competencies, levels = foundation(
        session, level_numeric_values=(100, 50, 10),
        policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    low, mid, high = levels
    assert high.numeric_value < low.numeric_value and high.display_order > low.display_order
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [high, low])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert outcome == "qualified"


def test_kpi_rule_uses_persisted_result_not_recomputed(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, kpi=True, student_count=2,
        policy_fn=lambda c, l: [kpi_rule(80)],
    )
    # Student 0: both competencies HIGH (90) -> weighted average 90 >= 80 -> qualifies.
    _, _, member_high = members[0]
    completed_high = complete_with_levels(session, member_high, competencies, [levels[2], levels[2]])
    assert completed_high.kpi_result == 90
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed_high.id)
    assert outcome == "qualified"
    assert '"actual_kpi_result":90' in candidate.evaluation_snapshot_json

    # Student 1: both competencies LOW (60) -> weighted average 60 < 80 -> does not qualify.
    _, _, member_low = members[1]
    completed_low = complete_with_levels(session, member_low, competencies, [levels[0], levels[0]])
    assert completed_low.kpi_result == 60
    candidate_low, outcome_low = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed_low.id)
    assert candidate_low is None and outcome_low == "not_qualified"


def test_all_composition_requires_every_rule(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, student_count=2,
        policy_fn=lambda c, l: [rubric_rule(c[0], l[2]), rubric_rule(c[1], l[2])],
    )
    _, _, both_high = members[0]
    completed_both = complete_with_levels(session, both_high, competencies, [levels[2], levels[2]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed_both.id)
    assert outcome == "qualified"

    _, _, one_high = members[1]
    completed_one = complete_with_levels(session, one_high, competencies, [levels[2], levels[0]])
    candidate2, outcome2 = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed_one.id)
    assert candidate2 is None and outcome2 == "not_qualified"


def test_any_composition_requires_one_rule(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, student_count=2, match_mode="any",
        policy_fn=lambda c, l: [rubric_rule(c[0], l[2]), rubric_rule(c[1], l[2])],
    )
    _, _, one_high = members[0]
    completed_one = complete_with_levels(session, one_high, competencies, [levels[2], levels[0]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed_one.id)
    assert outcome == "qualified"

    _, _, none_high = members[1]
    completed_none = complete_with_levels(session, none_high, competencies, [levels[0], levels[0]])
    candidate2, outcome2 = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed_none.id)
    assert candidate2 is None and outcome2 == "not_qualified"


def test_one_candidate_per_assessment_and_evaluation_is_idempotent(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
    candidate1, outcome1 = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    candidate2, outcome2 = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert outcome1 == "qualified" and outcome2 == "already_materialized"
    assert candidate1.id == candidate2.id
    assert session.query(models.TalentReviewCandidate).filter_by(assessment_id=completed.id).count() == 1
    assert session.query(models.TalentAssessmentAudit).filter_by(resource_type="review_candidate").count() == 1


def test_negative_evaluation_persists_no_candidate_but_is_audited(db):
    # M6 Decision 1: a non-qualifying evaluation never creates a durable
    # TalentReviewCandidate row, but the deterministic negative outcome MAY be
    # (and is) structurally recorded in TalentAssessmentAudit - assessment
    # identity, exact Framework/Policy context, outcome=false, evaluation
    # fingerprint, no free text, no durable negative entity.
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, policy_fn=lambda c, l: [rubric_rule(c[0], l[2])],
    )
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[0], levels[0]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert candidate is None and outcome == "not_qualified"
    assert session.query(models.TalentReviewCandidate).count() == 0
    audits = session.query(models.TalentAssessmentAudit).filter_by(
        resource_type="review_candidate", action="evaluate_non_qualifying",
    ).all()
    assert len(audits) == 1
    audit = audits[0]
    assert audit.resource_id == completed.id
    assert audit.before_json is None
    assert '"outcome":"not_qualified"' in audit.after_json
    assert "evaluation_fingerprint" in audit.after_json
    # No free text/durable negative entity: the after payload is a closed,
    # deterministic identity/outcome shape, not an arbitrary snapshot dump.
    assert set(json.loads(audit.after_json).keys()) == {
        "assessment_id", "policy_id", "match_mode", "framework_version_id",
        "evaluation_fingerprint", "outcome",
    }

    # Repeated non-qualifying evaluation of the same immutable Completed
    # Assessment remains idempotent in outcome (never a candidate, never a
    # changed result); each call appends one more append-only audit event,
    # matching every other operational audit in this milestone chain.
    candidate2, outcome2 = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert candidate2 is None and outcome2 == "not_qualified"
    assert session.query(models.TalentReviewCandidate).count() == 0
    assert session.query(models.TalentAssessmentAudit).filter_by(
        resource_type="review_candidate", action="evaluate_non_qualifying",
    ).count() == 2


def test_candidate_provenance_fingerprint_is_deterministic(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert outcome == "qualified"
    first_fingerprint = candidate.evaluation_fingerprint
    assert len(first_fingerprint) == 64
    # Delete the persisted row and re-evaluate the same immutable Completed
    # Assessment: the recomputed fingerprint must be identical (deterministic).
    session.delete(candidate)
    session.commit()
    candidate2, outcome2 = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert outcome2 == "qualified"
    assert candidate2.evaluation_fingerprint == first_fingerprint


def test_assessment_and_results_unchanged_by_candidate_evaluation(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])

    def snapshot():
        assessment_row = session.query(models.TalentStudentAssessment).filter_by(id=completed.id).one()
        assessment_dict = {c.name: getattr(assessment_row, c.name) for c in models.TalentStudentAssessment.__table__.columns}
        result_rows = session.query(models.TalentStudentCompetencyResult).filter_by(assessment_id=completed.id).order_by(models.TalentStudentCompetencyResult.id).all()
        results_dict = [{c.name: getattr(row, c.name) for c in models.TalentStudentCompetencyResult.__table__.columns} for row in result_rows]
        member_row = session.query(models.TalentAssessmentCyclePopulationMember).filter_by(id=completed.cycle_population_member_id).one()
        member_dict = {c.name: getattr(member_row, c.name) for c in models.TalentAssessmentCyclePopulationMember.__table__.columns}
        return assessment_dict, results_dict, member_dict

    before = snapshot()
    evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    session.commit()
    after = snapshot()
    assert before == after


def test_candidate_is_structurally_distinct_from_official_identification(db):
    # M6 Decisions 3-7 now implement Official Identification as its own
    # append-only table (`TalentOfficialIdentification`), structurally separate
    # from `TalentReviewCandidate`: a candidate itself carries no `decision`/
    # `identified` field, and a qualifying evaluation still never auto-creates
    # or implies an identification decision.
    assert hasattr(models, "TalentOfficialIdentification")
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
    candidate, outcome = evaluate_review_candidate(session, school_group_id=1, assessment_id=completed.id)
    assert outcome == "qualified"
    assert not hasattr(candidate, "decision") and not hasattr(candidate, "identified")
    assert session.query(models.TalentOfficialIdentification).filter_by(review_candidate_id=candidate.id).count() == 0


def _user(user_id, *, branch, scope, role="Administrator"):
    return models.User(user_id=user_id, username=f"user{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=1, branch_id=branch, academic_year_id=100, is_active=True)


def test_review_candidate_permission_is_separate_from_assessment_and_program_permissions(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    _, _, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
    editor = _user("1000000010", branch=10, scope="ORGANIZATION", role="Editor")
    session.add_all([
        editor,
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_assessments.view", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_assessments.manage", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.view", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.manage", is_allowed=True),
    ])
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: editor
    with TestClient(app) as client:
        evaluate_response = client.post("/api/talent/review-candidates/evaluate", json={"assessment_id": completed.id})
        assert evaluate_response.status_code == 403
        list_response = client.get("/api/talent/review-candidates")
        assert list_response.status_code == 403


def test_branch_scope_uses_frozen_member_for_candidate_visibility(db):
    _, session = db
    _, framework, cycle, members, competencies, levels = foundation(
        session, branch=10,
        policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    student, placement, member = members[0]
    completed = complete_with_levels(session, member, competencies, [levels[2], levels[2]])
    admin = _user("1000000020", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        result = client.post("/api/talent/review-candidates/evaluate", json={"assessment_id": completed.id})
        assert result.status_code == 201
        candidate_id = result.json()["candidate"]["id"]

    branch_user = _user("1000000021", branch=10, scope="BRANCH")
    other_branch_user = _user("1000000022", branch=11, scope="BRANCH")
    session.add_all([branch_user, other_branch_user])
    session.commit()
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/review-candidates/{candidate_id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other_branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/review-candidates/{candidate_id}").status_code == 404

    # Current Student transfer to a new Branch must not reinterpret the frozen
    # candidate's historical Branch authorization (matches the M4/M5 precedent).
    transition_placement(session, school_group_id=1, student_id=student.id, placement_id=placement.id,
                         transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
                         planning_section_id=1001)
    session.commit()
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/review-candidates/{candidate_id}").status_code == 200
    app.dependency_overrides[get_current_user] = lambda: other_branch_user
    with TestClient(app) as client:
        assert client.get(f"/api/talent/review-candidates/{candidate_id}").status_code == 404


def test_cross_tenant_lookup_is_non_enumerating(db):
    _, session = db
    # Tenant 1 (no policy needed - only used as the acting admin's own
    # SchoolGroup) and tenant 2 (a separate SchoolGroup with the qualifying
    # Assessment tenant-1 must not be able to see or evaluate).
    foundation(session, group_id=1)
    _, _, cycle2, members2, competencies2, levels2 = foundation(
        session, group_id=2, year_id=200, branch=20, section_id=2000,
        policy_fn=lambda c, l: [rubric_rule(c[0], l[0])],
    )
    _, _, member2 = members2[0]
    completed2 = complete_with_levels(session, member2, competencies2, [levels2[2], levels2[2]], group_id=2)
    admin1 = _user("1000000030", branch=None, scope="ORGANIZATION")
    session.add(admin1)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin1
    with TestClient(app) as client:
        response = client.post("/api/talent/review-candidates/evaluate", json={"assessment_id": completed2.id})
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


def test_evaluate_rejects_malformed_payload_without_500(db):
    _, session = db
    admin = _user("1000000040", branch=None, scope="ORGANIZATION")
    session.add(admin)
    session.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app, raise_server_exceptions=False) as client:
        empty = client.post("/api/talent/review-candidates/evaluate", json={})
        assert empty.status_code == 400
        assert empty.json()["code"] == "invalid_input"
        non_numeric = client.post("/api/talent/review-candidates/evaluate", json={"assessment_id": "not-a-number"})
        assert non_numeric.status_code == 400
        assert non_numeric.json()["code"] == "invalid_input"


def test_migration_is_idempotent_and_widens_audit_check(db):
    engine, session = db
    foundation(session)
    session.close()
    with engine.begin() as connection:
        models.TalentReviewCandidate.__table__.drop(connection)
        db_migrations._talent_review_candidate_foundation(engine, connection)
        db_migrations._talent_review_candidate_foundation(engine, connection)
    assert "talent_review_candidates" in inspect(engine).get_table_names()
    assert any(row.migration_id == "20260904_006_talent_review_candidate_foundation" for row in db_migrations.MIGRATIONS)
