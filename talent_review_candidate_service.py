"""M6 deterministic Review Candidate evaluation, materialization, and review workflow.

Evaluates the exact M3 `TalentReviewCandidatePolicy`/`TalentReviewCandidateRule`
attached to a Completed `TalentStudentAssessment`'s exact Framework Version.
Only `rubric_level_at_or_above` (using `TalentRubricLevel.display_order`, never
`numeric_value`) and `kpi_at_or_above` (using the assessment's persisted
`kpi_result`, never a recomputation) are supported - matching M3's governance-
closed semantics exactly. No policy attached = no candidate (never inferred).

Evaluation never writes to `TalentStudentAssessment`, `TalentStudentCompetencyResult`,
or `TalentAssessmentCyclePopulationMember` - it only reads them.

A qualifying (policy-satisfied) evaluation is persisted as one `TalentReviewCandidate`
row per Assessment, starting in `pending_review` (M6 Decision 2). A non-qualifying
evaluation is NOT persisted as a `TalentReviewCandidate` row (Decision 1), but IS
recorded structurally in `TalentAssessmentAudit` (assessment/Framework/Policy
identity, `outcome=false`, evaluation fingerprint, no free text, no durable
negative entity) so the deterministic non-qualifying outcome is auditable.

`mark_reviewed` implements the M6 Decision 2 review workflow: exactly two
states, `pending_review` -> `reviewed`, one-way, no reverse transition. It never
alters assessment evidence/competency results/KPI and never automatically
identifies the Student - see `talent_official_identification_service.py` for
the separate, review-gated (Decision 5) identification decision.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

import models


class TalentReviewCandidateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def candidate_payload(row):
    return {
        "id": row.id, "school_group_id": row.school_group_id, "cycle_id": row.cycle_id,
        "cycle_population_member_id": row.cycle_population_member_id, "student_id": row.student_id,
        "program_id": row.program_id, "academic_year_id": row.academic_year_id,
        "framework_version_id": row.framework_version_id, "assessment_id": row.assessment_id,
        "policy_id": row.policy_id, "match_mode": row.match_mode,
        "evaluation_fingerprint": row.evaluation_fingerprint,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        "evaluated_by_user_id": row.evaluated_by_user_id,
        "status": row.status,
        "reviewed_by_user_id": row.reviewed_by_user_id,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
    }


def _assessment(db, school_group_id, assessment_id):
    return db.query(models.TalentStudentAssessment).filter_by(
        id=assessment_id, school_group_id=school_group_id,
    ).one_or_none()


def _audit(db, candidate, *, actor, action, resource_type="review_candidate", before=None, after=None):
    canonical = _json({"action": action, "before": before, "after": after})
    db.add(models.TalentAssessmentAudit(
        school_group_id=candidate.school_group_id, cycle_id=candidate.cycle_id,
        program_id=candidate.program_id, academic_year_id=candidate.academic_year_id,
        framework_version_id=candidate.framework_version_id, assessment_id=candidate.assessment_id,
        cycle_population_member_id=candidate.cycle_population_member_id,
        student_id=candidate.student_id, actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type=resource_type, resource_id=candidate.id, action=action,
        before_json=_json(before) if before is not None else None,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def _audit_non_qualifying(db, assessment, *, actor, policy, snapshot, fingerprint):
    """M6 Decision 1: a non-qualifying evaluation never creates a durable
    `TalentReviewCandidate` row, but MAY be (and is, here) structurally
    recorded in `TalentAssessmentAudit` - assessment identity, exact Framework/
    Policy context, `outcome=false`, and the evaluation fingerprint, with no
    free text and no durable negative entity. ``resource_id`` uses the
    Assessment id (the only durable identity available) since no candidate
    row exists to anchor it to.
    """
    after = {
        "assessment_id": assessment.id, "policy_id": policy.id, "match_mode": policy.match_mode,
        "framework_version_id": assessment.framework_version_id,
        "evaluation_fingerprint": fingerprint, "outcome": snapshot["outcome"],
    }
    canonical = _json({"action": "evaluate_non_qualifying", "after": after})
    db.add(models.TalentAssessmentAudit(
        school_group_id=assessment.school_group_id, cycle_id=assessment.cycle_id,
        program_id=assessment.program_id, academic_year_id=assessment.academic_year_id,
        framework_version_id=assessment.framework_version_id, assessment_id=assessment.id,
        cycle_population_member_id=assessment.cycle_population_member_id,
        student_id=assessment.student_id, actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type="review_candidate", resource_id=assessment.id, action="evaluate_non_qualifying",
        after_json=_json(after),
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def _evaluate_rules(db, assessment, policy, rules):
    results_by_competency = {
        row.framework_competency_id: row for row in db.query(models.TalentStudentCompetencyResult).filter_by(
            school_group_id=assessment.school_group_id, assessment_id=assessment.id,
        ).all()
    }
    evaluations = []
    for rule in rules:
        if rule.rule_type == "rubric_level_at_or_above":
            result = results_by_competency.get(rule.framework_competency_id)
            threshold_level = db.query(models.TalentRubricLevel).filter_by(
                id=rule.rubric_level_id, school_group_id=assessment.school_group_id,
                framework_version_id=assessment.framework_version_id,
            ).one_or_none()
            actual_level = None
            if result is not None:
                actual_level = db.query(models.TalentRubricLevel).filter_by(
                    id=result.rubric_level_id, school_group_id=assessment.school_group_id,
                    framework_version_id=assessment.framework_version_id,
                ).one_or_none()
            satisfied = bool(
                actual_level is not None and threshold_level is not None
                and actual_level.display_order >= threshold_level.display_order
            )
            evaluations.append({
                "rule_id": rule.id, "rule_type": rule.rule_type, "display_order": rule.display_order,
                "framework_competency_id": rule.framework_competency_id,
                "threshold_rubric_level_id": rule.rubric_level_id,
                "threshold_display_order": threshold_level.display_order if threshold_level else None,
                "actual_rubric_level_id": actual_level.id if actual_level else None,
                "actual_display_order": actual_level.display_order if actual_level else None,
                "satisfied": satisfied,
            })
        elif rule.rule_type == "kpi_at_or_above":
            satisfied = assessment.kpi_result is not None and assessment.kpi_result >= rule.threshold_value
            evaluations.append({
                "rule_id": rule.id, "rule_type": rule.rule_type, "display_order": rule.display_order,
                "threshold_value": rule.threshold_value, "actual_kpi_result": assessment.kpi_result,
                "satisfied": satisfied,
            })
        else:
            raise TalentReviewCandidateError("invalid_policy", "Unsupported candidate rule type.")
    return evaluations


def evaluate_review_candidate(db: Session, *, school_group_id, assessment_id, actor=None):
    """Deterministically evaluate (and, if qualifying, materialize) one Review Candidate.

    Returns ``(candidate_or_none, outcome)`` where ``outcome`` is one of
    ``"already_materialized"``, ``"qualified"``, ``"not_qualified"``, or
    ``"no_policy"``. Repeated calls are idempotent: a Completed Assessment's
    evidence never changes, so re-evaluation always reaches the same outcome;
    an already-materialized qualifying candidate is returned unchanged rather
    than recomputed or overwritten.
    """
    assessment = _assessment(db, school_group_id, assessment_id)
    if assessment is None:
        raise TalentReviewCandidateError("not_found", "Student Assessment was not found.")
    if assessment.status != "completed":
        raise TalentReviewCandidateError("assessment_not_completed", "Review Candidate evaluation requires a Completed Assessment.")

    existing = db.query(models.TalentReviewCandidate).filter_by(
        assessment_id=assessment.id, school_group_id=school_group_id,
    ).one_or_none()
    if existing is not None:
        return existing, "already_materialized"

    policy = db.query(models.TalentReviewCandidatePolicy).filter_by(
        school_group_id=school_group_id, framework_version_id=assessment.framework_version_id, is_enabled=True,
    ).one_or_none()
    if policy is None:
        return None, "no_policy"
    rules = db.query(models.TalentReviewCandidateRule).filter_by(policy_id=policy.id).order_by(
        models.TalentReviewCandidateRule.display_order
    ).all()
    if not rules:
        return None, "no_policy"

    evaluations = _evaluate_rules(db, assessment, policy, rules)
    satisfied_flags = [item["satisfied"] for item in evaluations]
    outcome_satisfied = all(satisfied_flags) if policy.match_mode == "all" else any(satisfied_flags)

    framework = db.query(models.TalentProgramFrameworkVersion).filter_by(
        id=assessment.framework_version_id, school_group_id=school_group_id,
    ).one_or_none()
    snapshot = {
        "assessment_id": assessment.id, "cycle_id": assessment.cycle_id, "student_id": assessment.student_id,
        "program_id": assessment.program_id, "academic_year_id": assessment.academic_year_id,
        "framework_version_id": assessment.framework_version_id,
        "framework_semantic_fingerprint": framework.semantic_fingerprint if framework else None,
        "policy_id": policy.id, "match_mode": policy.match_mode, "rules": evaluations,
        "outcome": "qualified" if outcome_satisfied else "not_qualified",
    }
    fingerprint = hashlib.sha256(_json(snapshot).encode()).hexdigest()

    if not outcome_satisfied:
        # Decision 1: no TalentReviewCandidate row is created for a
        # non-qualifying evaluation, but the deterministic negative outcome is
        # structurally audited (assessment identity, Framework/Policy context,
        # outcome=false, fingerprint - no free text, no durable negative
        # entity). Repeated non-qualifying evaluation of the same immutable
        # Completed Assessment remains idempotent in the sense that the
        # outcome never changes; each call appends one audit event, matching
        # every other append-only operational audit in this milestone chain.
        _audit_non_qualifying(db, assessment, actor=actor, policy=policy, snapshot=snapshot, fingerprint=fingerprint)
        return None, "not_qualified"

    candidate = models.TalentReviewCandidate(
        school_group_id=school_group_id, cycle_id=assessment.cycle_id,
        cycle_population_member_id=assessment.cycle_population_member_id, student_id=assessment.student_id,
        program_id=assessment.program_id, academic_year_id=assessment.academic_year_id,
        framework_version_id=assessment.framework_version_id, assessment_id=assessment.id,
        policy_id=policy.id, match_mode=policy.match_mode, evaluation_fingerprint=fingerprint,
        evaluation_snapshot_json=_json(snapshot), evaluated_at=datetime.utcnow(),
        evaluated_by_user_id=getattr(actor, "user_id", None), status="pending_review",
    )
    db.add(candidate)
    db.flush()
    _audit(db, candidate, actor=actor, action="materialize", after=candidate_payload(candidate))
    return candidate, "qualified"


def mark_reviewed(db: Session, *, school_group_id, candidate_id, actor=None):
    """M6 Decision 2 review workflow: `pending_review` -> `reviewed`, one-way only.

    Never alters assessment evidence/competency results/KPI and never
    automatically records an Official Identification decision.
    """
    candidate = db.query(models.TalentReviewCandidate).filter_by(
        id=candidate_id, school_group_id=school_group_id,
    ).with_for_update().one_or_none()
    if candidate is None:
        raise TalentReviewCandidateError("not_found", "Review Candidate was not found.")
    if candidate.status == "reviewed":
        raise TalentReviewCandidateError("already_reviewed", "Review Candidate has already been Reviewed.")
    before = candidate_payload(candidate)
    candidate.status = "reviewed"
    candidate.reviewed_by_user_id = getattr(actor, "user_id", None)
    candidate.reviewed_at = datetime.utcnow()
    db.flush()
    _audit(db, candidate, actor=actor, action="reviewed", resource_type="review_candidate_review",
           before=before, after=candidate_payload(candidate))
    return candidate


def get_candidate(db, *, school_group_id, candidate_id):
    row = db.query(models.TalentReviewCandidate).filter_by(id=candidate_id, school_group_id=school_group_id).one_or_none()
    if row is None:
        raise TalentReviewCandidateError("not_found", "Review Candidate was not found.")
    return row


def get_candidate_for_assessment(db, *, school_group_id, assessment_id):
    return db.query(models.TalentReviewCandidate).filter_by(
        school_group_id=school_group_id, assessment_id=assessment_id,
    ).one_or_none()


def list_candidates(db, *, school_group_id, cycle_id=None):
    query = db.query(models.TalentReviewCandidate).filter_by(school_group_id=school_group_id)
    if cycle_id is not None:
        query = query.filter_by(cycle_id=cycle_id)
    return query.order_by(models.TalentReviewCandidate.id).all()
