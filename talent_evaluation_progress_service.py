"""M4 Authoritative Evaluation Progress backend.

Implements, strictly inside one Talent Program + one Academic Year (the same
boundary every M9/M10 module already uses - see ADR 0037's "Multiple
Programs" rule that separate Program results are never averaged together):

- Student Evaluation Progress (per-active-Period results, Current Overall
  Result, authoritative counts).
- Branch Evaluation Progress (BranchPeriodResult / BranchOverallResult).
- Organization Evaluation Progress (OrganizationPeriodResult /
  OrganizationOverallResult), computed directly from governed Student
  results - never as an average of Branch averages.
- The six approved Branch comparison metrics (``APPROVED_BRANCH_METRICS``),
  reusing existing M9 coverage/candidate/identification breakdown providers
  wherever the metric is not new. (A seventh, "Learning Style", was removed
  as of M14 and its dead computation code was removed outright as of M18a -
  see the M14/M18a notes above ``APPROVED_BRANCH_METRICS``.)

Governance this module implements exactly, without reopening it:

- **Canonical Period result**: ADR 0037's ``overall_program_result(...)
  ["normalized_percent"]`` (``talent_student_assessment_service.py``) is the
  only numeric Evaluation Period result input. ADR 0037's educational
  rubric-scale/KPI semantics are read-only here and are never altered.
- **Active/opened Evaluation Period predicate** (verified directly against
  ``models.py`` and ``talent_evaluation_plan_service.validate_cycle_period_link``,
  which only ever links a Draft Cycle to a Planned Period on an Active Plan):
  ``TalentPlannedEvaluationPeriod.status == 'planned'`` AND its linked
  ``TalentAssessmentCycle.status IN ('open', 'closed')``. A cancelled Period,
  an unlinked/not-yet-opened Period, and an ad-hoc (unlinked) Cycle are never
  an active weighting position. Configured Period label/short_code never
  affects order or weight - only ``sequence`` orders Periods, and for A
  active Periods the derived (never persisted) nominal weight is ``1/A``.
- **Framework comparability (owner-ratified M4 Decision 1)**: Evaluation
  Period results combine into one Overall Result only when every
  contributing active Period's linked Cycle shares one identical governed
  ``framework_version_id``. A mixed-framework active set returns every
  Period individually with ``comparability_state="not_comparable"`` /
  ``comparability_reason_code="framework_changed"`` and a ``null`` combined
  Overall Result - never a cross-framework delta, normalization, or
  equivalence inference.
- **Single-Student disclosure (owner-ratified M4 Decision 2)**: an
  individually authorized Student's own Evaluation Progress is governed by
  the existing ``talent_learner_profiles.view`` permission plus the same
  frozen-historical-Branch scope check
  ``talent_learner_profile_service.build_learner_profile`` already applies -
  never by aggregate cohort-size privacy suppression. Branch/Organization
  aggregate outputs below remain fully privacy-gated.

Privacy: every Branch/Organization aggregate reuses ONLY the M9 generic
``Cell``/``Group``/``apply_primary_privacy``/``run_complementary_suppression``
primitives (``talent_analytics_privacy.py``) - never the M10
``talent_org_intelligence_contract.py`` ``MetricCode``/``CellIdentity``
vocabulary, which stays frozen and unmodified by this module. Every
aggregate is gated on an authorized contributing-count ``Cell`` (parent
total = sum(per-Branch counts), exactly like the existing M9 coverage/
Learning-Style-distribution ``Group`` pattern): a derived mean is
serialized only when its own count ``Cell`` is independently ``visible``
after complementary suppression closure; a non-visible count never lets its
associated numeric mean pass through, and a ``coarsened`` count never
licenses publishing a derived mean either (mirroring
``talent_analytics_service.build_privacy_safe_coverage_bundle``'s exact
all-or-nothing convention).

Performance note (documented, not hidden): unlike the pure-count M9
aggregates, ``normalized_percent`` is not a stored column - it is a
deterministic read projection over each Completed Assessment's own
competency results and rubric levels
(``talent_student_assessment_service.overall_program_result``). This module
therefore calls that existing, already-reviewed function once per Completed
Assessment inside the requested Cycle/Period rather than duplicating its
logic in raw SQL. This is a bounded per-assessment cost, not a per-row
cross-join, and is acceptable at the same Program+AcademicYear-bounded scale
every other M9/M10 module already operates at; it is not a claimed
PostgreSQL performance qualification.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
import talent_analytics_service as svc
from talent_current_students import current_student_exists
from talent_analytics_privacy import (
    COARSENED,
    NO_DATA,
    RESTRICTED,
    SUPPRESSED,
    VISIBLE,
    apply_primary_privacy,
    run_complementary_suppression,
)
from talent_read_batch import read_batch
from talent_student_assessment_service import overall_program_result, prime_assessment_batch


class EvaluationProgressError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Student per-Period result-state vocabulary (Unavailable states)
# ---------------------------------------------------------------------------

RESULT_STATE_AVAILABLE = "available"
RESULT_STATE_PENDING = "pending"
RESULT_STATE_INCOMPLETE = "incomplete"
RESULT_STATE_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
RESULT_STATE_UNASSESSED = "unassessed"
RESULT_STATE_NOT_APPLICABLE = "not_applicable"

_UNAVAILABLE_RESULT_STATES = (
    RESULT_STATE_PENDING,
    RESULT_STATE_INCOMPLETE,
    RESULT_STATE_INSUFFICIENT_EVIDENCE,
    RESULT_STATE_UNASSESSED,
    RESULT_STATE_NOT_APPLICABLE,
)

# M14 owner correction: the "learning_style" Branch-comparison metric is
# REMOVED as of M14. It computed the arithmetic mean of the four
# ``learning_style_*_percentage`` columns (ADR 0042) across a Branch
# population - semantically wrong under the corrected model, where
# "percentage" means population/aggregate distribution over the single
# categorical ``learning_style`` field, never a mean of per-Student scores.
# A request for this metric now falls through to the existing
# ``invalid_filter``/400 handling below, the same as any other unrecognized
# metric value, rather than silently returning a wrong number. A categorical
# distribution replacement (if any) for this Branch-comparison surface is
# out of M14 scope and is left for a later, separately governed milestone.
#
# M18a: ``learning_style_branch_aggregate``/``_learning_style_values_by_branch``
# (kept unreferenced since M14, purely so the deprecated-column mean
# computation was not silently mutated) are now confirmed genuinely
# unreachable from any current endpoint/service path - the Branch-comparison
# dispatcher below (the only caller of any Branch-comparison metric) has
# rejected "learning_style" since M14 - and have been removed outright,
# along with their stale direct-call tests. The four
# ``learning_style_*_percentage`` columns remain on ``models.Student``,
# untouched, for separately-gated historical/physical-removal decisions.
#
# M18b-1: the ``learning_style_dimension`` query parameter/keyword argument
# on ``routers/talent_evaluation_progress.py``'s ``branch_comparison`` route
# and this function's signature is REMOVED. It was a no-op since M14: the
# "learning_style" metric it existed to parameterize is not, and never was
# after M14, a member of ``APPROVED_BRANCH_METRICS`` above, so
# ``branch_comparison_metric`` always raised ``invalid_filter`` before the
# argument's value could ever be read - confirmed genuinely unreferenced
# inside this function's own body prior to removal (audited directly, not
# assumed). No current Talent Branch-comparison metric consumes a Learning
# Style dimension; the correct Family 1 Learning Style backend contract
# (categorical distribution, never a per-dimension mean) is
# ``student_learning_style_analytics.py``/``talent_results_analytics_service.py``.
APPROVED_BRANCH_METRICS = (
    "evaluation_period_result",
    "current_overall_progress",
    "assessment_completion",
    "assessments_started",
    "meets_program_criteria",
    "officially_confirmed",
)


def _mean_percent(values) -> Optional[float]:
    """Deterministic 2-decimal half-up mean, matching the worked M4 examples
    (80+90+84 -> 84.67). ``None`` for an empty contributing set - never 0."""
    if not values:
        return None
    total = sum(Decimal(int(value)) for value in values)
    return float((total / Decimal(len(values))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Active/opened Evaluation Period predicate
# ---------------------------------------------------------------------------


def resolve_active_periods(ctx: "svc.AnalyticsContext"):
    """Ordered ``[(period, cycle), ...]`` active/opened weighting positions.

    ``TalentPlannedEvaluationPeriod.status == 'planned'`` AND its linked
    ``TalentAssessmentCycle.status IN ('open', 'closed')``. Cancelled
    Periods, unlinked/not-yet-opened Periods, and ad-hoc (unlinked) Cycles
    are excluded. Order is exclusively governed ``sequence`` - the
    configured label/short_code never affects order or weight.
    """
    active = []
    cycle_by_period = ctx.cycle_by_period_id
    for period in sorted(ctx.periods, key=lambda row: row.sequence):
        if period.status != "planned":
            continue
        cycle = cycle_by_period.get(period.id)
        if cycle is None or cycle.status not in ("open", "closed"):
            continue
        active.append((period, cycle))
    return active


def nominal_weight(active_period_count: int) -> Optional[float]:
    if not active_period_count:
        return None
    return 1 / active_period_count


# ---------------------------------------------------------------------------
# Student Evaluation Progress (Decision 2: authorization-governed, no
# aggregate cohort-size suppression)
# ---------------------------------------------------------------------------


def _current_assessment_for_cycle(db: Session, school_group_id: int, student_id: int, cycle_id: int):
    return db.query(models.TalentStudentAssessment).filter(
        models.TalentStudentAssessment.school_group_id == school_group_id,
        models.TalentStudentAssessment.student_id == student_id,
        models.TalentStudentAssessment.is_current.is_(True),
        func.coalesce(
            models.TalentStudentAssessment.evaluation_context_cycle_id,
            models.TalentStudentAssessment.cycle_id,
        ) == cycle_id,
    ).one_or_none()


def _period_result_for_student(db: Session, assessment):
    """One (result_state, normalized_percent_or_None) pair for a Student's
    assessment in one active Period's Cycle. ``None`` for the assessment
    itself means the Student had no frozen population membership/assessment
    for this Cycle at all - Unassessed, never a silent zero."""
    if assessment is None:
        return RESULT_STATE_UNASSESSED, None
    if assessment.status == "in_progress":
        return RESULT_STATE_PENDING, None
    if assessment.status == "incomplete":
        return RESULT_STATE_INCOMPLETE, None
    if assessment.status == "insufficient_evidence":
        return RESULT_STATE_INSUFFICIENT_EVIDENCE, None
    # status == "completed"
    overall = overall_program_result(db, assessment)
    if overall is None or overall.get("available") is False:
        # No applicable Grade-scoped competencies, or (defensively - this is
        # blocked at completion time) an inconsistent rubric scale: Not
        # Applicable, never a fabricated zero/None-as-zero result.
        return RESULT_STATE_NOT_APPLICABLE, None
    return RESULT_STATE_AVAILABLE, overall["normalized_percent"]


def resolve_student_progress_access(db: Session, *, school_group_id: int, program_id: int,
                                     academic_year_id: int, student_id: int, visible_branch_ids):
    """Frozen-historical-Branch authorization for direct single-Student
    Evaluation Progress access (owner-ratified M4 Decision 2). Mirrors
    ``talent_learner_profile_service.build_learner_profile``'s existing
    frozen-Branch check: an out-of-scope Student is a non-enumerating
    ``None`` (caller renders 404), never a 403 that would confirm existence,
    and never a cohort-suppression decision."""
    student = db.query(models.Student).filter_by(id=student_id, school_group_id=school_group_id).one_or_none()
    if student is None:
        return None
    if visible_branch_ids is None:
        return student
    has_visible_membership = db.query(models.TalentAssessmentCyclePopulationMember.id).filter_by(
        school_group_id=school_group_id, student_id=student_id, program_id=program_id, academic_year_id=academic_year_id,
    ).filter(
        models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible_branch_ids or {-1})
    ).first()
    return student if has_visible_membership is not None else None


def build_student_progress(db: Session, ctx: "svc.AnalyticsContext", *, student_id: int) -> dict:
    active_periods = resolve_active_periods(ctx)
    weight = nominal_weight(len(active_periods))
    framework_ids = set()
    periods_payload = []
    numeric_results = []
    for period, cycle in active_periods:
        assessment = _current_assessment_for_cycle(db, ctx.school_group_id, student_id, cycle.id)
        result_state, value = _period_result_for_student(db, assessment)
        framework_ids.add(cycle.framework_version_id)
        periods_payload.append({
            "period_id": period.id, "label": period.label, "sequence": period.sequence,
            "lifecycle_state": "active", "nominal_weight": weight,
            "framework_version_id": cycle.framework_version_id,
            "result_state": result_state,
            "normalized_percent": value if result_state == RESULT_STATE_AVAILABLE else None,
        })
        if result_state == RESULT_STATE_AVAILABLE:
            numeric_results.append(value)

    comparable = len(framework_ids) <= 1
    current_overall_result = _mean_percent(numeric_results) if comparable else None

    return {
        "student_id": student_id,
        "active_period_count": len(active_periods),
        "available_result_count": len(numeric_results),
        "pending_or_unavailable_count": len(active_periods) - len(numeric_results),
        "comparability_state": "comparable" if comparable else "not_comparable",
        "comparability_reason_code": None if comparable else "framework_changed",
        "periods": periods_payload,
        "current_overall_result": current_overall_result,
    }


# ---------------------------------------------------------------------------
# Branch / Organization Evaluation Progress (privacy-gated aggregates)
# ---------------------------------------------------------------------------


def _cycle_branch_results(db: Session, school_group_id: int, cycle_id: int, visible_branch_ids):
    """``{branch_id: [normalized_percent, ...]}`` of every valid governed
    Student result attributed to one Cycle, grouped by the FROZEN historical
    ``TalentAssessmentCyclePopulationMember.branch_id`` (never current
    Placement). Restricted to the authorized/visible Branch set first."""
    query = db.query(models.TalentStudentAssessment, models.TalentAssessmentCyclePopulationMember).join(
        models.TalentAssessmentCyclePopulationMember,
        models.TalentAssessmentCyclePopulationMember.id == models.TalentStudentAssessment.cycle_population_member_id,
    ).filter(
        models.TalentStudentAssessment.school_group_id == school_group_id,
        models.TalentStudentAssessment.is_current.is_(True),
        models.TalentStudentAssessment.status == "completed",
        func.coalesce(
            models.TalentStudentAssessment.evaluation_context_cycle_id,
            models.TalentStudentAssessment.cycle_id,
        ) == cycle_id,
        current_student_exists(),  # Batch 1: never an orphan/deleted Student's result
    )
    if visible_branch_ids is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible_branch_ids or {-1}))
    per_branch = defaultdict(list)
    pairs = query.all()
    # Request-scoped read memoization + set-based priming (talent_read_batch.py).
    with read_batch(db):
        prime_assessment_batch(db, [assessment for assessment, _ in pairs])
        for assessment, member in pairs:
            overall = overall_program_result(db, assessment)
            if overall is None or overall.get("available") is False:
                continue
            per_branch[member.branch_id].append(overall["normalized_percent"])
    return dict(per_branch)


def _member_branch_ids_for_cycle(db: Session, school_group_id: int, cycle_id: int, visible_branch_ids):
    rows = db.query(models.TalentAssessmentCyclePopulationMember.branch_id).filter_by(
        school_group_id=school_group_id, cycle_id=cycle_id,
    ).filter(current_student_exists()).distinct().all()
    branch_ids = {row[0] for row in rows}
    if visible_branch_ids is not None:
        branch_ids &= set(visible_branch_ids)
    return branch_ids


def _privacy_safe_branch_mean_group(*, name: str, per_branch_values: dict, branch_ids, privacy_class: str, policy):
    """One privacy-closed Branch-mean projection: a `Group` whose total is
    the org-wide contributing-count (sum of per-Branch contributing counts)
    and whose children are each Branch's own contributing count. A visible
    count licenses publishing that scope's own derived mean; the mean itself
    is computed directly from the already-authorized raw values (never a
    policy-supplied replacement, and never averaged across sibling means)."""
    counts = {branch_id: len(per_branch_values.get(branch_id, [])) for branch_id in branch_ids}
    total_count = sum(counts.values())
    group = svc.build_breakdown_group(
        name=name, privacy_class=privacy_class,
        total_raw=(total_count if total_count else None),
        children_raw={bid: (count if total_count else None) for bid, count in counts.items()},
    )
    apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression([group], policy)
    return group, converged


def _cell_mean_payload(cell, converged: bool, raw_values) -> dict:
    if not converged:
        return {"state": RESTRICTED, "count": None, "mean_normalized_percent": None}
    if cell.state == VISIBLE:
        return {"state": VISIBLE, "count": cell.value, "mean_normalized_percent": _mean_percent(raw_values)}
    if cell.state == COARSENED:
        # A coarsened count is a policy-supplied safe replacement for the
        # count alone - it never licenses publishing a derived mean whose
        # raw inputs were never themselves privacy-evaluated.
        return {"state": COARSENED, "count": cell.value, "mean_normalized_percent": None}
    return {"state": cell.state, "count": None, "mean_normalized_percent": None}


def _period_branch_results(db: Session, ctx: "svc.AnalyticsContext", cycle, visible_branch_ids, policy):
    """One active Period's privacy-closed ``({branch_id: payload}, org_payload)``.

    ``org_payload``'s mean is computed directly from the flattened raw
    per-Student values across every authorized Branch - never from the
    per-Branch means - so it structurally cannot become an
    average-of-Branch-averages."""
    per_branch_values = _cycle_branch_results(db, ctx.school_group_id, cycle.id, visible_branch_ids)
    branch_ids = set(per_branch_values.keys())
    branch_ids |= _member_branch_ids_for_cycle(db, ctx.school_group_id, cycle.id, visible_branch_ids)
    group, converged = _privacy_safe_branch_mean_group(
        name=f"evaluation_period_result:{cycle.id}", per_branch_values=per_branch_values,
        branch_ids=branch_ids, privacy_class="P2", policy=policy,
    )
    by_branch = {}
    for cell in group.children:
        branch_id = cell.key[2]
        by_branch[branch_id] = _cell_mean_payload(cell, converged, per_branch_values.get(branch_id, []))
    org_values = [value for values in per_branch_values.values() for value in values]
    org_payload = _cell_mean_payload(group.total, converged, org_values)
    return by_branch, org_payload


def _all_active_period_results(db: Session, ctx: "svc.AnalyticsContext", visible_branch_ids, policy):
    """``[(period, cycle, by_branch, org_payload), ...]`` for every active
    Period, each independently privacy-closed."""
    results = []
    for period, cycle in resolve_active_periods(ctx):
        by_branch, org_payload = _period_branch_results(db, ctx, cycle, visible_branch_ids, policy)
        results.append((period, cycle, by_branch, org_payload))
    return results


def _overall_from_period_payloads(period_payloads, *, comparable: bool):
    if not comparable:
        return {"state": NO_DATA, "value": None}
    visible_values = [payload["mean_normalized_percent"] for payload in period_payloads if payload["state"] == VISIBLE and payload["mean_normalized_percent"] is not None]
    if not visible_values:
        return {"state": NO_DATA, "value": None}
    return {"state": VISIBLE, "value": _mean_percent(visible_values)}


def build_branch_progress(db: Session, ctx: "svc.AnalyticsContext", *, branch_id: int, visible_branch_ids, policy) -> dict:
    active = _all_active_period_results(db, ctx, visible_branch_ids, policy)
    framework_ids = {cycle.framework_version_id for _, cycle, _, _ in active}
    comparable = len(framework_ids) <= 1
    periods_payload = []
    branch_period_payloads = []
    for period, cycle, by_branch, _ in active:
        payload = by_branch.get(branch_id, {"state": NO_DATA, "count": None, "mean_normalized_percent": None})
        periods_payload.append({
            "period_id": period.id, "label": period.label, "sequence": period.sequence,
            "framework_version_id": cycle.framework_version_id, **payload,
        })
        branch_period_payloads.append(payload)
    overall = _overall_from_period_payloads(branch_period_payloads, comparable=comparable)
    return {
        "branch_id": branch_id,
        "active_period_count": len(active),
        "comparability_state": "comparable" if comparable else "not_comparable",
        "comparability_reason_code": None if comparable else "framework_changed",
        "periods": periods_payload,
        "current_overall_result": overall,
    }


def build_organization_progress(db: Session, ctx: "svc.AnalyticsContext", *, visible_branch_ids, policy) -> dict:
    active = _all_active_period_results(db, ctx, visible_branch_ids, policy)
    framework_ids = {cycle.framework_version_id for _, cycle, _, _ in active}
    comparable = len(framework_ids) <= 1
    periods_payload = []
    org_period_payloads = []
    for period, cycle, _, org_payload in active:
        periods_payload.append({
            "period_id": period.id, "label": period.label, "sequence": period.sequence,
            "framework_version_id": cycle.framework_version_id, **org_payload,
        })
        org_period_payloads.append(org_payload)
    overall = _overall_from_period_payloads(org_period_payloads, comparable=comparable)
    return {
        "active_period_count": len(active),
        "comparability_state": "comparable" if comparable else "not_comparable",
        "comparability_reason_code": None if comparable else "framework_changed",
        "periods": periods_payload,
        "current_overall_result": overall,
    }


# ---------------------------------------------------------------------------
# Bounded Branch comparison metric dispatcher (7 approved metrics only).
# Reuses existing M9 coverage/candidate/identification breakdown providers;
# never extends the frozen M10 MetricCode registry.
# ---------------------------------------------------------------------------


def _breakdown_percentage(cell, total_cell):
    if cell.state != VISIBLE or total_cell.state != VISIBLE or not total_cell.value:
        return None
    return float(svc.percentage(cell.value, total_cell.value))


def branch_comparison_metric(db: Session, ctx: "svc.AnalyticsContext", *, metric: str,
                              visible_branch_ids, has_candidate_permission: bool,
                              has_identification_permission: bool, policy) -> dict:
    if metric not in APPROVED_BRANCH_METRICS:
        raise EvaluationProgressError("invalid_filter", "metric is not one of the six approved Branch comparison metrics.")

    if metric == "evaluation_period_result":
        active = _all_active_period_results(db, ctx, visible_branch_ids, policy)
        branch_ids = sorted({bid for _, _, by_branch, _ in active for bid in by_branch}, key=lambda v: (v is None, v))
        rows = []
        for branch_id in branch_ids:
            periods = []
            for period, cycle, by_branch, _ in active:
                payload = by_branch.get(branch_id, {"state": NO_DATA, "count": None, "mean_normalized_percent": None})
                periods.append({"period_id": period.id, "label": period.label, "sequence": period.sequence,
                                 "framework_version_id": cycle.framework_version_id, **payload})
            rows.append({"branch_id": branch_id, "periods": periods})
        return {"metric": metric, "rows": rows}

    if metric == "current_overall_progress":
        active = _all_active_period_results(db, ctx, visible_branch_ids, policy)
        framework_ids = {cycle.framework_version_id for _, cycle, _, _ in active}
        comparable = len(framework_ids) <= 1
        branch_ids = sorted({bid for _, _, by_branch, _ in active for bid in by_branch}, key=lambda v: (v is None, v))
        rows = []
        for branch_id in branch_ids:
            payloads = [by_branch.get(branch_id, {"state": NO_DATA, "count": None, "mean_normalized_percent": None}) for _, _, by_branch, _ in active]
            rows.append({"branch_id": branch_id, **_overall_from_period_payloads(payloads, comparable=comparable)})
        return {"metric": metric, "comparability_state": "comparable" if comparable else "not_comparable",
                "comparability_reason_code": None if comparable else "framework_changed", "rows": rows}

    filters = svc.ResolvedFilters()
    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)

    coverage_by_dim = svc.raw_coverage_by_dimension(db, pop_query, "branch")
    branch_ids = sorted(coverage_by_dim.keys(), key=lambda v: (v is None, v))

    if metric == "assessment_completion":
        group = svc.build_breakdown_group(
            name="assessment_completion", privacy_class="P2",
            total_raw=sum(value["completed"] for value in coverage_by_dim.values()),
            children_raw={bid: value["completed"] for bid, value in coverage_by_dim.items()},
        )
    elif metric == "assessments_started":
        group = svc.build_breakdown_group(
            name="assessments_started", privacy_class="P2",
            total_raw=sum(sum(value[key] for key in svc.ASSESSMENT_STATES) for value in coverage_by_dim.values()),
            children_raw={bid: sum(value[key] for key in svc.ASSESSMENT_STATES) for bid, value in coverage_by_dim.items()},
        )
    elif metric == "meets_program_criteria":
        if not has_candidate_permission:
            raise EvaluationProgressError("permission_denied", "talent_review_candidates.view is required for meets_program_criteria.")
        candidate_by_dim = svc.raw_candidate_by_dimension(db, pop_query, "branch", has_permission=True) or {}
        group = svc.build_breakdown_group(
            name="meets_program_criteria", privacy_class="P5",
            total_raw=sum(candidate_by_dim.values()),
            children_raw={bid: candidate_by_dim.get(bid, 0) for bid in branch_ids},
        )
    else:  # officially_confirmed
        if not has_identification_permission:
            raise EvaluationProgressError("permission_denied", "talent_official_identifications.view is required for officially_confirmed.")
        identification_by_dim = svc.raw_identification_by_dimension(db, pop_query, "branch", has_permission=True) or {}
        group = svc.build_breakdown_group(
            name="officially_confirmed", privacy_class="P6",
            total_raw=sum(value.get("identified", 0) for value in identification_by_dim.values()),
            children_raw={bid: identification_by_dim.get(bid, {}).get("identified", 0) for bid in branch_ids},
        )

    apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression([group], policy)
    if not converged:
        return {"metric": metric, "state": RESTRICTED, "rows": [], "total": {"state": RESTRICTED, "value": None}}
    rows = []
    for cell in group.children:
        rows.append({
            "branch_id": cell.key[2], "state": cell.state, "count": cell.value,
            "percentage": _breakdown_percentage(cell, group.total),
        })
    return {"metric": metric, "rows": rows, "total": {"state": group.total.state, "value": group.total.value}}
