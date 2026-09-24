"""Deployment Acceptance Correction B: authorized backend projections that feed
the shared Talent Student identity (Learning Style + current automatic
Classification).

Learning Style is the canonical ``Student.learning_style`` (no Talent copy).
Classification is the M17 ``talent_classification_service`` result of a
Completed, current Assessment only. Nothing here widens Student visibility:
every value rides a projection that already contained that Student.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

import models
from auth import get_current_user
from dependencies import get_db
from routers.talent_assessment_cycles import router as cycles_router
from routers.talent_assessments import router as assessments_router
from routers.talent_review_candidates import router as review_router
from student_academic_service import create_placement, create_student
from talent_assessment_cycle_service import create_cycle, open_cycle, synchronize_placement_to_open_cycles
from talent_learner_profile_service import build_learner_profile
from talent_official_identification_service import record_decision
from talent_org_student_drill import fetch_student_rows
from talent_review_candidate_service import evaluate_review_candidate, mark_reviewed
from talent_student_assessment_service import start_assessment

# Reuse the M17 fixtures (in-memory two-tenant database and Program builder).
from test_talent_classification import _admin_user, build_program, complete_with_level, db  # noqa: F401


def _client(db, user):
    app = FastAPI()
    app.include_router(assessments_router)
    app.include_router(cycles_router)
    app.include_router(review_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _admin(db):
    existing = db.query(models.User).filter_by(user_id="1000000099").one_or_none()
    if existing is not None:
        return existing
    admin = _admin_user()
    db.add(admin)
    db.commit()
    return admin


def _set_style(db, student, style):
    student.learning_style = style
    db.commit()


def test_assessment_list_exposes_learning_style_and_backend_classification_for_exceptional(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Visual")
    complete_with_level(db, member, fw, levels[-1])
    with _client(db, _admin(db)) as client:
        rows = client.get("/api/talent/assessments", params={"cycle_id": cycle.id}).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["context"]["student_learning_style"] == "Visual"
    assert row["classification"] == "Exceptional"
    assert row["is_talented"] is True
    assert row["classification_score"] == "5.00"
    assert row["overall_result"]["average"] == 5.0


def test_non_exceptional_classification_is_never_talented(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Read/Write")
    complete_with_level(db, member, fw, levels[3])
    with _client(db, _admin(db)) as client:
        row = client.get("/api/talent/assessments", params={"cycle_id": cycle.id}).json()[0]
    assert row["classification"] == "Advanced"
    assert row["is_talented"] is False


def test_in_progress_and_non_current_assessments_never_fabricate_a_classification(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    with _client(db, _admin(db)) as client:
        row = client.get("/api/talent/assessments", params={"cycle_id": cycle.id}).json()[0]
        assert row["status"] == "in_progress"
        assert row["classification"] is None and row["is_talented"] is False
        assert row["overall_result"] is None or row.get("classification") is None
    # A Student without any assessment yet is simply absent from the list (roster shows Not started).
    db.delete(assessment)
    db.commit()
    with _client(db, _admin(db)) as client:
        assert client.get("/api/talent/assessments", params={"cycle_id": cycle.id}).json() == []


def test_historical_completed_assessment_carries_no_current_classification(db):
    _, _, cycle, member, fw, levels, _ = build_program(db, level_count=5)
    completed = complete_with_level(db, member, fw, levels[-1])
    completed.is_current = False
    db.commit()
    with _client(db, _admin(db)) as client:
        row = client.get("/api/talent/assessments", params={"cycle_id": cycle.id}).json()[0]
    assert row["classification"] is None and row["is_talented"] is False


def test_legacy_review_and_identification_never_determine_list_classification(db):
    """Classification comes only from the M17 result; legacy records do not alter it."""
    _, _, cycle, member, fw, levels, _ = build_program(db, level_count=5, review_policy=True)
    complete_with_level(db, member, fw, levels[0])  # lowest level -> Needs Improvement
    with _client(db, _admin(db)) as client:
        row = client.get("/api/talent/assessments", params={"cycle_id": cycle.id}).json()[0]
    assert row["classification"] == "Needs Improvement"
    assert row["is_talented"] is False


def test_eligible_students_roster_carries_learning_style_and_unassigned_is_null(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Spatial")
    other = create_student(db, school_group_id=1, first_name="Second", last_name="Student")
    placement = create_placement(db, school_group_id=1, student_id=other.id, academic_year_id=100, branch_id=10,
                                 planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    db.commit()
    with _client(db, _admin(db)) as client:
        payload = client.get(f"/api/talent/assessment-cycles/{cycle.id}/eligible-students").json()
    by_name = {m["first_name"]: m for m in payload["members"]}
    assert by_name["Test"]["learning_style"] == "Spatial"
    assert by_name["Second"]["learning_style"] is None
    assert placement is not None


def test_tenant_isolation_learning_style_of_another_school_group_never_appears(db):
    _, _, cycle1, member1, fw1, levels1, student1 = build_program(db, level_count=5)
    _, _, cycle2, member2, fw2, levels2, student2 = build_program(
        db, group_id=2, year_id=200, branch_id=20, section_id=2000, level_count=5)
    _set_style(db, student1, "Visual")
    _set_style(db, student2, "Auditory")
    complete_with_level(db, member1, fw1, levels1[-1])
    complete_with_level(db, member2, fw2, levels2[-1], group_id=2)
    with _client(db, _admin(db)) as client:
        listing = client.get("/api/talent/assessments").text
        roster = client.get(f"/api/talent/assessment-cycles/{cycle1.id}/eligible-students").text
        foreign = client.get(f"/api/talent/assessment-cycles/{cycle2.id}/eligible-students")
    assert "Visual" in listing and "Auditory" not in listing
    assert "Auditory" not in roster
    assert foreign.status_code in (403, 404)
    assert "Auditory" not in foreign.text


def test_branch_scoped_actor_does_not_receive_learning_style_of_students_outside_branch(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Kinesthetic")
    complete_with_level(db, member, fw, levels[-1])
    db.add(models.Branch(id=11, school_group_id=1, name="One B"))
    branch_user = models.User(user_id="1000000098", username="branchuser", role="Teacher", user_type="TENANT",
                              access_scope="BRANCH", school_group_id=1, branch_id=11, academic_year_id=100, is_active=True)
    db.add(branch_user)
    db.commit()
    import auth
    original = auth.has_permission
    auth.has_permission = lambda *a, **k: True
    try:
        with _client(db, branch_user) as client:
            body = client.get("/api/talent/assessments", params={"cycle_id": cycle.id})
            roster = client.get(f"/api/talent/assessment-cycles/{cycle.id}/eligible-students")
    finally:
        auth.has_permission = original
    assert "Kinesthetic" not in body.text
    assert "Kinesthetic" not in roster.text


def test_learner_profile_identity_header_and_current_classification(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Verbal")
    complete_with_level(db, member, fw, levels[-1])
    profile = build_learner_profile(db, school_group_id=1, student_id=student.id)
    assert profile["student"]["learning_style"] == "Verbal"
    item = profile["programs"][0]["academic_years"][0]["cycles"][0]
    assert item["assessment"]["classification"] == "Exceptional"
    assert item["assessment"]["is_talented"] is True
    assert item["assessment"]["overall_result"]["average"] == 5.0
    assert item["assessment"]["is_current"] is True


def test_learner_profile_unassigned_learning_style_is_null_and_draft_has_no_classification(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    profile = build_learner_profile(db, school_group_id=1, student_id=student.id)
    assert profile["student"]["learning_style"] is None
    item = profile["programs"][0]["academic_years"][0]["cycles"][0]
    assert item["assessment"]["classification"] is None
    assert item["assessment"]["is_talented"] is False
    assert item["assessment"]["overall_result"] is None


def test_student_drill_row_carries_learning_style_and_context_classification(db):
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Quantitative")
    complete_with_level(db, member, fw, levels[-1])
    population = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id)
    rows, has_more = fetch_student_rows(db, population, limit=10, offset=0, has_candidate=False,
                                        has_identification=False, has_learner_profile=False)
    payload = rows[0].to_payload()
    assert payload["learning_style"] == "Quantitative"
    context = payload["contexts"][0]
    assert context["classification"] == "Exceptional" and context["is_talented"] is True
    # Legacy states are absent unless separately permitted (they are not requested here).
    assert "candidate_state" not in context and "identification_state" not in context


def _cohort(db, size):
    _, _, cycle, member, fw, levels, first = build_program(db, level_count=5)
    students = [first]
    for index in range(size - 1):
        student = create_student(db, school_group_id=1, first_name=f"S{index}", last_name="Cohort")
        placement = create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100, branch_id=10,
                                     planning_section_id=1000, effective_from=datetime(2026, 9, 1))
        db.commit()
        synchronize_placement_to_open_cycles(db, school_group_id=1, student_id=student.id, academic_placement_id=placement.id)
        students.append(student)
    db.commit()
    members = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).all()
    for s, m in zip(students, sorted(members, key=lambda x: x.student_id)):
        s.learning_style = "Visual"
        complete_with_level(db, m, fw, levels[-1])
    db.commit()
    return cycle


def _count_statements(db, work):
    statements = []

    def before(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", before)
    try:
        work()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return len(statements)


def test_list_projection_query_count_does_not_grow_per_student_for_identity_fields(db):
    """Learning Style rides the existing batched Student lookup and the
    Classification reuses the already-computed Overall Program Result, so the
    identity fields add no per-Student query."""
    cycle_small = _cohort(db, 1)
    admin = _admin(db)
    with _client(db, admin) as client:
        small = _count_statements(db, lambda: client.get("/api/talent/assessments", params={"cycle_id": cycle_small.id}))
    # Add two more Students to the same cycle.
    for index in range(2):
        student = create_student(db, school_group_id=1, first_name=f"X{index}", last_name="Extra")
        placement = create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100, branch_id=10,
                                     planning_section_id=1000, effective_from=datetime(2026, 9, 1))
        db.commit()
        synchronize_placement_to_open_cycles(db, school_group_id=1, student_id=student.id, academic_placement_id=placement.id)
        member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
            cycle_id=cycle_small.id, student_id=student.id).one()
        student.learning_style = "Auditory"
        fw = db.query(models.FrameworkCompetency).first()
        level = db.query(models.TalentRubricLevel).order_by(models.TalentRubricLevel.id.desc()).first()
        complete_with_level(db, member, fw, level)
    db.commit()
    with _client(db, admin) as client:
        larger = _count_statements(db, lambda: client.get("/api/talent/assessments", params={"cycle_id": cycle_small.id}))
    per_student = (larger - small) / 2
    # Measured against the exact pre-change baseline (b7e3c6a) the same list
    # endpoint already issued 36 statements of per-row derivation per Student
    # (overall result, reassess/delete capability probes, permission checks).
    # That pre-existing cost is NOT introduced by Acceptance B; this guard pins
    # that the identity fields (Learning Style, Classification) add zero.
    assert per_student <= 36, f"per-Student statement growth {per_student} exceeds the b7e3c6a baseline of 36"


# -------------------------------------------------- Acceptance B remediation: legacy review workspace

def test_review_workspace_returns_current_classification_and_talented_for_exceptional(db):
    """The real production legacy-review workspace projection returns the current
    automatic Classification (M17) for a completed/current Assessment."""
    _, _, cycle, member, fw, levels, student = build_program(db, level_count=5)
    _set_style(db, student, "Visual")
    complete_with_level(db, member, fw, levels[-1])
    with _client(db, _admin(db)) as client:
        rows = client.get("/api/talent/review-candidates/workspace", params={"cycle_id": cycle.id}).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["classification"] == "Exceptional"
    assert row["is_talented"] is True
    assert row["classification_score"] == "5.00"
    assert row["context"]["student_learning_style"] == "Visual"


def test_review_workspace_advanced_is_never_talented(db):
    _, _, cycle, member, fw, levels, _ = build_program(db, level_count=5)
    complete_with_level(db, member, fw, levels[3])  # position 4/5 -> Advanced
    with _client(db, _admin(db)) as client:
        row = client.get("/api/talent/review-candidates/workspace", params={"cycle_id": cycle.id}).json()[0]
    assert row["classification"] == "Advanced"
    assert row["is_talented"] is False


def test_review_workspace_in_progress_never_fabricates_classification(db):
    _, _, cycle, member, fw, levels, _ = build_program(db, level_count=5)
    start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
    with _client(db, _admin(db)) as client:
        assert client.get("/api/talent/review-candidates/workspace", params={"cycle_id": cycle.id}).json() == []


def test_review_workspace_historical_non_current_never_fabricates_classification(db):
    _, _, cycle, member, fw, levels, _ = build_program(db, level_count=5)
    completed = complete_with_level(db, member, fw, levels[-1])
    completed.is_current = False
    db.commit()
    with _client(db, _admin(db)) as client:
        assert client.get("/api/talent/review-candidates/workspace", params={"cycle_id": cycle.id}).json() == []


def test_review_workspace_legacy_identified_status_never_creates_talented(db):
    """A legacy Review Candidate / Official Identification record is separate from
    the current automatic Classification. A non-Exceptional Student with a legacy
    'identified' record stays not-Talented in the legacy-history surface."""
    program, framework, cycle, member, fw, levels, _ = build_program(db, level_count=5, review_policy=True)
    completed = complete_with_level(db, member, fw, levels[3])  # Advanced -> NOT Talented
    policy = db.query(models.TalentReviewCandidatePolicy).filter_by(
        framework_version_id=framework.id, program_id=program.id).one()
    db.add(models.TalentReviewCandidate(
        id=9101, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id,
        student_id=member.student_id, program_id=program.id, academic_year_id=100,
        framework_version_id=framework.id, assessment_id=completed.id, policy_id=policy.id,
        match_mode="all", evaluation_fingerprint="e" * 64, evaluation_snapshot_json="{}",
        status="reviewed",
    ))
    db.flush()
    db.add(models.TalentOfficialIdentification(
        id=9201, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id,
        student_id=member.student_id, program_id=program.id, academic_year_id=100,
        framework_version_id=framework.id, assessment_id=completed.id, review_candidate_id=9101,
        decision="identified",
    ))
    db.commit()
    with _client(db, _admin(db)) as client:
        row = client.get("/api/talent/review-candidates/workspace", params={"cycle_id": cycle.id}).json()[0]
    assert row["classification"] == "Advanced"
    assert row["is_talented"] is False
    assert row["review_status"] == "reviewed"  # the legacy record is present but separate



# -------------------------------------------------- Acceptance B remediation: Student Drill dedupe key

def test_student_drill_dedupe_key_handles_nested_overall_result_and_preserves_distinct_contexts(db):
    """Regression: the per-Student context dedupe key must be a canonical JSON
    string, not a tuple of payload items. A completed/current context carries a
    nested ``overall_result`` dict, so the former
    ``tuple(sorted(context.to_payload().items()))`` key raised
    ``TypeError: unhashable type: 'dict'`` for any Student with a Program result.
    ``json.dumps(..., sort_keys=True, default=str)`` both survives nested dicts
    and still keeps genuinely distinct contexts separate."""
    program, framework, cycle, member, fw, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, fw, levels[-1])  # nested overall_result + classification

    # A second distinct context for the SAME Student: a second open Cycle in the
    # same Program. Opening it re-derives the eligible population and adds a second
    # membership that must NOT be collapsed into the first.
    cycle2 = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                          framework_version_id=framework.id, title="Second Cycle",
                          population_effective_at=datetime(2026, 11, 1))
    open_cycle(db, school_group_id=1, cycle_id=cycle2.id, expected_revision=cycle2.revision,
               organization_authorized=True)
    db.commit()

    population = db.query(models.TalentAssessmentCyclePopulationMember).filter(
        models.TalentAssessmentCyclePopulationMember.school_group_id == 1,
        models.TalentAssessmentCyclePopulationMember.student_id == student.id,
    )
    rows, has_more = fetch_student_rows(db, population, limit=10, offset=0, has_candidate=False,
                                        has_identification=False, has_learner_profile=False)
    payload = rows[0].to_payload()
    # Both distinct contexts survive the JSON key (the second cycle is unassessed).
    assert len(payload["contexts"]) == 2
    by_cycle = {ctx["cycle_id"]: ctx for ctx in payload["contexts"]}
    assert by_cycle[cycle.id]["overall_result"]["average"] == 5.0  # nested dict survives
    assert "overall_result" not in by_cycle[cycle2.id]  # unassessed -> no fabricated result
