"""M17 automatic Assessment classification tests (ADR 0037, 2026-09-23 amendment).

Covers: exact boundary/interior/invalid classification bands, Talented
semantics, the N-agnostic (Option B) linear projection, the normal
completion workflow (no manual Review Candidate/Official Identification
required), legacy historical preservation, immutability, and tenant/scope
isolation.
"""

from datetime import datetime
from decimal import Decimal

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
from routers.talent_assessments import router as assessments_router
from student_academic_service import create_placement, create_student
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_classification_service import (
    CLASSIFICATION_SCALE_MAX, CLASSIFICATION_SCALE_MIN, TalentClassificationError,
    assessment_classification, classify_score, is_talented, project_to_classification_scale,
)
from talent_official_identification_service import record_decision
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, configure_review_candidate_policy,
    create_competency, create_framework_draft, create_program, transition_program,
    upsert_annual_configuration, upsert_descriptor, upsert_rubric,
)
from talent_review_candidate_service import evaluate_review_candidate, mark_reviewed
from talent_student_assessment_service import complete_assessment, mark_non_complete, set_competency_result, start_assessment


# --------------------------------------------------------------------------
# A. classify_score - exact boundary / interior / invalid bands (17 cases)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    ("1.00", "Needs Improvement"), ("1.99", "Needs Improvement"),
    ("2.00", "Developing"), ("2.99", "Developing"),
    ("3.00", "Meets Expectations"), ("3.74", "Meets Expectations"),
    ("3.75", "Advanced"), ("4.49", "Advanced"),
    ("4.50", "Exceptional"), ("5.00", "Exceptional"),
])
def test_classify_score_exact_boundaries(score, expected):
    assert classify_score(Decimal(score)) == expected


@pytest.mark.parametrize("score,expected", [
    ("1.50", "Needs Improvement"),
    ("2.50", "Developing"),
    ("3.25", "Meets Expectations"),
    ("4.00", "Advanced"),
    ("4.75", "Exceptional"),
])
def test_classify_score_interior_values(score, expected):
    assert classify_score(Decimal(score)) == expected


@pytest.mark.parametrize("score", ["0.99", "5.01", "0.00", "10.00"])
def test_classify_score_invalid_values_fail_closed(score):
    with pytest.raises(TalentClassificationError) as exc:
        classify_score(Decimal(score))
    assert exc.value.code == "score_out_of_range"


@pytest.mark.parametrize("classification,expected_talented", [
    ("Needs Improvement", False), ("Developing", False), ("Meets Expectations", False),
    ("Advanced", False), ("Exceptional", True),
])
def test_is_talented_only_exceptional(classification, expected_talented):
    assert is_talented(classification) is expected_talented


def test_bands_are_gapless_and_non_overlapping_across_full_range():
    # Every hundredth of the governed range maps to exactly one band.
    cents = range(100, 501)  # 1.00 .. 5.00 inclusive, in hundredths
    for c in cents:
        classify_score(Decimal(c) / 100)  # must not raise


# --------------------------------------------------------------------------
# B. project_to_classification_scale - N-agnostic deterministic projection
# --------------------------------------------------------------------------

def test_projection_five_level_scale_is_identity():
    # N=5 is the ADR 0037 worked example; the projection is the identity map.
    assert project_to_classification_scale(44, 1, 5) == Decimal("4.40")
    assert project_to_classification_scale(10, 1, 5) == Decimal("1.00")
    assert project_to_classification_scale(50, 1, 5) == Decimal("5.00")


def test_projection_three_level_scale():
    # avg=1.0 -> 1.00; avg=2.0 -> midpoint 3.00; avg=3.0 -> 5.00.
    assert project_to_classification_scale(10, 1, 3) == Decimal("1.00")
    assert project_to_classification_scale(20, 1, 3) == Decimal("3.00")
    assert project_to_classification_scale(30, 1, 3) == Decimal("5.00")


def test_projection_four_level_scale():
    assert project_to_classification_scale(10, 1, 4) == Decimal("1.00")
    assert project_to_classification_scale(25, 1, 4) == Decimal("3.00")
    assert project_to_classification_scale(40, 1, 4) == Decimal("5.00")


def test_projection_reaches_hundredths_precision_on_a_larger_scale():
    # N=41 exercises exact Decimal math beyond one decimal place of input.
    projected = project_to_classification_scale(109, 1, 41)
    assert projected == Decimal("1") + (Decimal("10.9") - Decimal("1")) * Decimal("4") / Decimal("40")
    assert projected == Decimal("1.99")
    assert classify_score(projected) == "Needs Improvement"


def test_projection_is_never_a_percentage():
    # A percentage-style mapping would give 88.0 for avg=4.4/5; the governed
    # projection must stay within [1.00, 5.00].
    projected = project_to_classification_scale(44, 1, 5)
    assert CLASSIFICATION_SCALE_MIN <= projected <= CLASSIFICATION_SCALE_MAX


def test_projection_degenerate_single_level_rubric_is_incompatible():
    assert project_to_classification_scale(10, 1, 1) is None


def test_projection_invalid_scale_shape_is_incompatible():
    assert project_to_classification_scale(10, 5, 3) is None


# --------------------------------------------------------------------------
# C. End-to-end workflow / legacy-history / immutability / tenant isolation
# --------------------------------------------------------------------------

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


def build_program(session, *, group_id=1, year_id=100, branch_id=10, section_id=1000,
                   level_count=5, review_policy=False):
    program = create_program(session, school_group_id=group_id, name="Mental Math")
    transition_program(session, school_group_id=group_id, program_id=program.id, target_status="active")
    framework = create_framework_draft(session, school_group_id=group_id, program_id=program.id, title="Framework")
    competency = create_competency(session, school_group_id=group_id, program_id=program.id, code="C1", name="Competency 1")
    fw_competency, framework = add_framework_competency(
        session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
        competency_id=competency.id, expected_revision=framework.revision,
    )
    _, framework = upsert_rubric(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                                  expected_revision=framework.revision, name="Rubric")
    levels = []
    for index in range(level_count):
        level, framework = add_rubric_level(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, code=f"L{index+1}", label=f"Level {index+1}",
        )
        levels.append(level)
    for level in levels:
        _, framework = upsert_descriptor(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            framework_competency_id=fw_competency.id, rubric_level_id=level.id,
            expected_revision=framework.revision, descriptor=f"Evidence for {level.label}",
        )
    if review_policy:
        rules = [{"rule_type": "rubric_level_at_or_above", "framework_competency_id": fw_competency.id,
                  "rubric_level_id": levels[-1].id}]
        _, framework = configure_review_candidate_policy(
            session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
            expected_revision=framework.revision, is_enabled=True, match_mode="all", description=None, rules=rules,
        )
    activate_framework(session, school_group_id=group_id, program_id=program.id, framework_id=framework.id,
                        expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                        organization_authorized=True)
    upsert_annual_configuration(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                                 is_enabled=True, eligible_grade_levels=["1"])
    student = create_student(session, school_group_id=group_id, first_name="Test", last_name="Student")
    create_placement(session, school_group_id=group_id, student_id=student.id, academic_year_id=year_id,
                      branch_id=branch_id, planning_section_id=section_id, effective_from=datetime(2026, 9, 1))
    cycle = create_cycle(session, school_group_id=group_id, program_id=program.id, academic_year_id=year_id,
                          framework_version_id=framework.id, title="Cycle", population_effective_at=datetime(2026, 10, 1))
    open_cycle(session, school_group_id=group_id, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    session.commit()
    member = session.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id, student_id=student.id).one()
    return program, framework, cycle, member, fw_competency, levels, student


def complete_with_level(session, member, fw_competency, level, *, group_id=1):
    assessment = start_assessment(session, school_group_id=group_id, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    revision = assessment.revision
    _, assessment = set_competency_result(
        session, school_group_id=group_id, assessment_id=assessment.id,
        framework_competency_id=fw_competency.id, rubric_level_id=level.id,
        expected_revision=revision, evidence="evidence text",
    )
    return complete_assessment(session, school_group_id=group_id, assessment_id=assessment.id, expected_revision=assessment.revision)


def test_draft_assessment_has_no_final_automatic_classification(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    assert assessment_classification(db, assessment) is None


def test_incomplete_assessment_cannot_become_final_classification(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    marked = mark_non_complete(db, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision, status="incomplete")
    assert assessment_classification(db, marked) is None


def test_complete_submit_computes_classification_backend_side_exceptional(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=5)
    completed = complete_with_level(db, member, fw_competency, levels[-1])  # top of 5 -> average=5.0
    result = assessment_classification(db, completed)
    assert result["available"] is True
    assert result["classification"] == "Exceptional"
    assert result["is_talented"] is True
    assert result["classification_score"] == "5.00"


def test_advanced_does_not_produce_talented_and_needs_no_manual_identification(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=5)
    completed = complete_with_level(db, member, fw_competency, levels[3])  # position 4/5 -> average=4.0 -> Advanced
    result = assessment_classification(db, completed)
    assert result["classification"] == "Advanced"
    assert result["is_talented"] is False
    # No Review Candidate policy configured, no Official Identification recorded,
    # yet the classification is already final and authoritative.
    assert db.query(models.TalentReviewCandidate).count() == 0
    assert db.query(models.TalentOfficialIdentification).count() == 0


def test_current_workflow_does_not_require_review_candidate_or_official_identification(db):
    # No Review Candidate policy is configured for this Program at all.
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=5, review_policy=False)
    completed = complete_with_level(db, member, fw_competency, levels[-1])
    result = assessment_classification(db, completed)
    assert result["is_talented"] is True
    assert db.query(models.TalentReviewCandidate).count() == 0
    assert db.query(models.TalentOfficialIdentification).count() == 0


def test_historical_review_candidate_and_identification_preserved_but_do_not_override_classification(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=5, review_policy=True)
    completed = complete_with_level(db, member, fw_competency, levels[-1])  # Exceptional by classification
    candidate, outcome = evaluate_review_candidate(db, school_group_id=1, assessment_id=completed.id)
    assert outcome == "qualified"
    mark_reviewed(db, school_group_id=1, candidate_id=candidate.id)
    # Legacy human decision deliberately disagrees ("not_identified") - the
    # automatic classification must still govern is_talented, and the legacy
    # record must remain untouched (not silently rewritten or deleted).
    identification = record_decision(
        db, school_group_id=1, review_candidate_id=candidate.id, decision="not_identified",
        organization_authorized=True,
    )
    result = assessment_classification(db, completed)
    assert result["classification"] == "Exceptional"
    assert result["is_talented"] is True
    stored_candidate = db.query(models.TalentReviewCandidate).filter_by(id=candidate.id).one()
    stored_identification = db.query(models.TalentOfficialIdentification).filter_by(id=identification.id).one()
    assert stored_candidate.status == "reviewed"
    assert stored_identification.decision == "not_identified"


def test_completed_result_remains_immutable_and_classification_is_stable(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=5)
    completed = complete_with_level(db, member, fw_competency, levels[-1])
    first = assessment_classification(db, completed)
    second = assessment_classification(db, completed)
    assert first == second
    from talent_student_assessment_service import TalentStudentAssessmentError
    with pytest.raises(TalentStudentAssessmentError) as exc:
        set_competency_result(
            db, school_group_id=1, assessment_id=completed.id,
            framework_competency_id=fw_competency.id, rubric_level_id=levels[0].id,
            expected_revision=completed.revision, evidence="attempted post-completion edit",
        )
    assert exc.value.code == "immutable_assessment"


def test_classification_supports_a_four_level_program_without_five_level_mandate(db):
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=4)
    completed = complete_with_level(db, member, fw_competency, levels[-1])  # top of 4 -> average=4.0
    result = assessment_classification(db, completed)
    assert result["available"] is True
    assert result["scale_max"] == 4
    assert result["classification_score"] == "5.00"
    assert result["classification"] == "Exceptional"
    assert result["is_talented"] is True


def test_classification_respects_school_group_tenant_scope(db):
    _, _, _, member1, fw_competency1, levels1, _ = build_program(db, group_id=1, year_id=100, branch_id=10, section_id=1000, level_count=5)
    _, _, _, member2, fw_competency2, levels2, _ = build_program(db, group_id=2, year_id=200, branch_id=20, section_id=2000, level_count=5)
    completed1 = complete_with_level(db, member1, fw_competency1, levels1[-1], group_id=1)
    completed2 = complete_with_level(db, member2, fw_competency2, levels2[0], group_id=2)
    result1 = assessment_classification(db, completed1)
    result2 = assessment_classification(db, completed2)
    assert result1["classification"] == "Exceptional"
    assert result2["classification"] == "Needs Improvement"
    # Cross-tenant assessment ids never collide/leak - each Assessment's
    # classification is computed only from its own school_group_id's data
    # (ADR 0037's existing scoped query pattern, unchanged by M17).
    assert completed1.school_group_id == 1
    assert completed2.school_group_id == 2


def _admin_user(user_id="1000000099"):
    return models.User(user_id=user_id, username=f"user{user_id}", role="Administrator", user_type="TENANT",
                        access_scope="ORGANIZATION", school_group_id=1, branch_id=None, academic_year_id=100, is_active=True)


def test_api_complete_endpoint_exposes_backend_classification_and_cannot_be_spoofed(db):
    """D. API contract: the /complete response carries backend-computed
    classification/is_talented; a client cannot pass its own classification
    or is_talented value to influence the result (frontend cannot spoof)."""
    _, _, _, member, fw_competency, levels, _ = build_program(db, level_count=5)
    admin = _admin_user()
    db.add(admin)
    db.commit()
    assessment = start_assessment(db, school_group_id=1, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    app = FastAPI()
    app.include_router(assessments_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        write = client.put(
            f"/api/talent/assessments/{assessment.id}/competency-results/{fw_competency.id}",
            json={"rubric_level_id": levels[-1].id, "expected_revision": assessment.revision, "evidence": "evidence text"},
        )
        assert write.status_code == 200
        current_revision = write.json()["assessment"]["revision"]
        response = client.post(
            f"/api/talent/assessments/{assessment.id}/complete",
            json={
                "expected_revision": current_revision,
                # Attempted spoof payload - the backend must ignore these entirely.
                "classification": "Exceptional", "is_talented": True, "classification_score": "999.99",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["classification"] == "Exceptional"
        assert payload["is_talented"] is True
        assert payload["classification_score"] == "5.00"
        # Draft read before completion never carried a classification; confirm
        # the value now visible is the backend's own post-completion result,
        # not an echo of the client-supplied spoof fields.
        assert payload["overall_result"]["average"] == 5.0
