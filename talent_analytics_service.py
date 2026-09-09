"""M9 Deterministic Talent Analytics - read-only aggregation authority.

Strictly inside ONE Program + ONE Academic Year (Section E). Historical scope
uses ONLY `TalentAssessmentCyclePopulationMember` frozen fields (branch_id,
grade_level, section_name/planning_section_id) - current Student Placement is
never consulted anywhere in this module. An optional M8 Annual Evaluation
Plan is resolved when present; a valid ad-hoc (no-Plan) context works fully
without one.

Call order matches Section D: resolve_context -> resolve filters ->
execute authorized aggregate queries -> derive metrics -> compose secondary
domains (Candidate/Identification, query-skipped without permission) ->
apply privacy -> complementary suppression -> comparability -> insights ->
serialization. This module never re-runs M6 Review Candidate policy
evaluation and never recomputes M5 KPI - both are pure reads over already-
materialized rows.

No Talent Score/Index/Potential Rate, no cross-Program analytics, no ranking
field, no matched-cohort growth, and no KPI mean/median/percentile/bins exist
anywhere in this module (see docs M9 governance closure).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

import academic_grade
import models
from talent_analytics_privacy import (
    COARSENED,
    NO_DATA,
    RESTRICTED,
    SUPPRESSED,
    VISIBLE,
    Cell,
    Group,
    apply_primary_privacy,
    run_complementary_suppression,
)


class TalentAnalyticsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


ASSESSMENT_STATES = ("in_progress", "completed", "incomplete", "insufficient_evidence")
COVERAGE_STATUS_KEYS = ("unassessed",) + ASSESSMENT_STATES
DIMENSION_TYPES = ("branch", "grade", "section")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def percentage(numerator: int, denominator: int):
    if not denominator:
        return None
    return (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Context resolution (Section E)
# ---------------------------------------------------------------------------


@dataclass
class AnalyticsContext:
    school_group_id: int
    program: object
    year: object
    config: Optional[object]
    plan: Optional[object]
    periods: list
    cycles: list

    @property
    def periods_by_id(self):
        return {row.id: row for row in self.periods}

    @property
    def cycles_by_id(self):
        return {row.id: row for row in self.cycles}

    @property
    def cycle_by_period_id(self):
        return {row.planned_evaluation_period_id: row for row in self.cycles if row.planned_evaluation_period_id is not None}


def resolve_context(db: Session, *, school_group_id: int, program_id: int, academic_year_id: int) -> AnalyticsContext:
    program = db.query(models.TalentProgram).filter_by(id=program_id, school_group_id=school_group_id).one_or_none()
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=school_group_id).one_or_none()
    if program is None or year is None:
        raise TalentAnalyticsError("not_found", "Program or Academic Year was not found.")
    config = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        school_group_id=school_group_id, program_id=program_id, academic_year_id=academic_year_id,
    ).one_or_none()
    plan = None
    periods = []
    if config is not None:
        plan = db.query(models.TalentAnnualEvaluationPlan).filter_by(program_academic_year_configuration_id=config.id).one_or_none()
        if plan is not None:
            periods = db.query(models.TalentPlannedEvaluationPeriod).filter_by(
                annual_evaluation_plan_id=plan.id
            ).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()
    cycles = db.query(models.TalentAssessmentCycle).filter_by(
        school_group_id=school_group_id, program_id=program_id, academic_year_id=academic_year_id,
    ).all()
    return AnalyticsContext(school_group_id=school_group_id, program=program, year=year, config=config, plan=plan, periods=periods, cycles=cycles)


# ---------------------------------------------------------------------------
# Filter resolution (Section F)
# ---------------------------------------------------------------------------


@dataclass
class ResolvedFilters:
    period_id: Optional[int] = None
    cycle_id: Optional[int] = None
    branch_id: Optional[int] = None
    grade: Optional[str] = None
    section_id: Optional[int] = None
    framework_version_id: Optional[int] = None
    competency_id: Optional[int] = None
    assessment_state: Optional[str] = None
    candidate_state: Optional[str] = None
    identification_state: Optional[str] = None

    def fingerprint_payload(self):
        return {key: value for key, value in vars(self).items() if value is not None}


def _clean_int(raw, name):
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise TalentAnalyticsError("invalid_filter", f"{name} must be an integer.")


def resolve_filters(
    ctx: AnalyticsContext,
    raw: dict,
    *,
    db: Session,
    branch_scope: Optional[set],
    has_candidate_permission: bool,
    has_identification_permission: bool,
) -> ResolvedFilters:
    period_id = _clean_int(raw.get("period_id"), "period_id")
    if period_id is not None and period_id not in ctx.periods_by_id:
        raise TalentAnalyticsError("invalid_filter", "period_id is not within the analytical context.")

    cycle_id = _clean_int(raw.get("cycle_id"), "cycle_id")
    if cycle_id is not None and cycle_id not in ctx.cycles_by_id:
        raise TalentAnalyticsError("invalid_filter", "cycle_id is not within the analytical context.")

    branch_id = _clean_int(raw.get("branch_id"), "branch_id")
    if branch_id is not None and branch_scope is not None and branch_id not in branch_scope:
        raise TalentAnalyticsError("invalid_filter", "branch_id is not within the authorized scope.")

    grade = raw.get("grade")
    if grade is not None and grade not in academic_grade.GRADE_LEVELS:
        raise TalentAnalyticsError("invalid_filter", "grade is not a recognized grade level.")

    section_id = _clean_int(raw.get("section_id"), "section_id")

    framework_version_id = _clean_int(raw.get("framework_version_id"), "framework_version_id")
    known_frameworks = {row.framework_version_id for row in ctx.cycles}
    if framework_version_id is not None and framework_version_id not in known_frameworks:
        raise TalentAnalyticsError("invalid_filter", "framework_version_id is not within the analytical context.")

    competency_id = _clean_int(raw.get("competency_id"), "competency_id")
    if competency_id is not None:
        competency_query = db.query(models.FrameworkCompetency.id).filter_by(
            school_group_id=ctx.school_group_id, id=competency_id,
        )
        if framework_version_id is not None:
            competency_query = competency_query.filter_by(framework_version_id=framework_version_id)
        else:
            competency_query = competency_query.filter(
                models.FrameworkCompetency.framework_version_id.in_(known_frameworks or {-1})
            )
        if competency_query.first() is None:
            raise TalentAnalyticsError("invalid_filter", "competency_id is not within the analytical context.")

    assessment_state = raw.get("assessment_state")
    if assessment_state is not None and assessment_state not in COVERAGE_STATUS_KEYS:
        raise TalentAnalyticsError("invalid_filter", "assessment_state is not a recognized Assessment state.")

    candidate_state = raw.get("candidate_state") if has_candidate_permission else None
    if candidate_state is not None and candidate_state not in ("pending_review", "reviewed"):
        raise TalentAnalyticsError("invalid_filter", "candidate_state is not a recognized Review Candidate state.")

    identification_state = raw.get("identification_state") if has_identification_permission else None
    if identification_state is not None and identification_state not in ("identified", "not_identified", "no_decision"):
        raise TalentAnalyticsError("invalid_filter", "identification_state is not a recognized Official Identification state.")

    return ResolvedFilters(
        period_id=period_id, cycle_id=cycle_id, branch_id=branch_id, grade=grade, section_id=section_id,
        framework_version_id=framework_version_id, competency_id=competency_id, assessment_state=assessment_state,
        candidate_state=candidate_state, identification_state=identification_state,
    )


def _scoped_cycle_ids(ctx: AnalyticsContext, filters: ResolvedFilters):
    cycles = ctx.cycles
    if filters.cycle_id is not None:
        cycles = [row for row in cycles if row.id == filters.cycle_id]
    if filters.period_id is not None:
        cycles = [row for row in cycles if row.planned_evaluation_period_id == filters.period_id]
    if filters.framework_version_id is not None:
        cycles = [row for row in cycles if row.framework_version_id == filters.framework_version_id]
    # Only an Opened (population-frozen) Cycle has authoritative historical
    # scope; a Draft Cycle has nothing to analyze yet.
    return [row.id for row in cycles if row.status in ("open", "closed")]


def population_query(db: Session, ctx: AnalyticsContext, filters: ResolvedFilters, visible_branch_ids: Optional[set]):
    cycle_ids = _scoped_cycle_ids(ctx, filters)
    query = db.query(models.TalentAssessmentCyclePopulationMember).filter(
        models.TalentAssessmentCyclePopulationMember.school_group_id == ctx.school_group_id,
        models.TalentAssessmentCyclePopulationMember.cycle_id.in_(cycle_ids or [-1]),
    )
    if visible_branch_ids is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible_branch_ids or {-1}))
    if filters.branch_id is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.branch_id == filters.branch_id)
    if filters.grade is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.grade_level == filters.grade)
    if filters.section_id is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.planning_section_id == filters.section_id)
    return query


# ---------------------------------------------------------------------------
# Execution summary (Section K) and Period timeline (Section L)
# ---------------------------------------------------------------------------


def compute_execution_summary(ctx: AnalyticsContext) -> dict:
    periods = ctx.periods
    cycle_by_period = ctx.cycle_by_period_id
    required_executed = required_cancelled = required_outstanding = 0
    optional_state_counts = {"planned": 0, "cancelled": 0}
    for period in periods:
        cycle = cycle_by_period.get(period.id)
        if period.is_required:
            if period.status == "cancelled":
                required_cancelled += 1
            elif period.status == "planned" and cycle is not None and cycle.status == "closed":
                required_executed += 1
            else:
                required_outstanding += 1
        else:
            optional_state_counts[period.status] = optional_state_counts.get(period.status, 0) + 1
    return {
        "planned_period_count": len(periods),
        "required_period_count": sum(1 for row in periods if row.is_required),
        "required_executed_count": required_executed,
        "required_cancelled_count": required_cancelled,
        "required_outstanding_count": required_outstanding,
        "optional_period_state_counts": optional_state_counts,
        "ad_hoc_cycle_count": sum(1 for row in ctx.cycles if row.planned_evaluation_period_id is None),
    }


def build_period_timeline(ctx: AnalyticsContext, *, cycle_view_permission: bool):
    cycle_by_period = ctx.cycle_by_period_id
    timeline = []
    for period in sorted(ctx.periods, key=lambda row: row.sequence):
        item = {
            "period_id": period.id, "sequence": period.sequence, "label": period.label,
            "is_required": period.is_required, "status": period.status,
        }
        cycle = cycle_by_period.get(period.id)
        if cycle_view_permission and cycle is not None:
            item["cycle"] = {"id": cycle.id, "status": cycle.status, "framework_version_id": cycle.framework_version_id}
        timeline.append(item)
    ad_hoc = []
    if cycle_view_permission:
        ad_hoc = [
            {"id": row.id, "status": row.status, "framework_version_id": row.framework_version_id}
            for row in ctx.cycles if row.planned_evaluation_period_id is None
        ]
    return timeline, ad_hoc


# ---------------------------------------------------------------------------
# Coverage (Section M) - single grouped/outer-join query, no per-row loop
# ---------------------------------------------------------------------------


def raw_coverage_counts(db: Session, pop_query) -> dict:
    base = pop_query.with_entities(models.TalentAssessmentCyclePopulationMember.id.label("member_id")).subquery()
    rows = db.query(
        func.coalesce(models.TalentStudentAssessment.status, "unassessed").label("status"),
        func.count(base.c.member_id),
    ).select_from(base).outerjoin(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).group_by("status").all()
    counts = {key: 0 for key in COVERAGE_STATUS_KEYS}
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    return counts


def coverage_metrics(counts: dict) -> dict:
    frozen_eligible = sum(counts.values())
    started = sum(counts[key] for key in ASSESSMENT_STATES)
    completed = counts["completed"]
    return {
        "frozen_eligible": frozen_eligible,
        "counts": dict(counts),
        "assessment_started": started,
        "started_coverage_percentage": percentage(started, frozen_eligible),
        "completion_coverage_percentage": percentage(completed, frozen_eligible),
    }


def raw_coverage_by_dimension(db: Session, pop_query, dimension_type: str) -> dict:
    dim_col = _dimension_column(dimension_type)
    base = pop_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        dim_col.label("dim_key"),
    ).subquery()
    rows = db.query(
        base.c.dim_key,
        func.coalesce(models.TalentStudentAssessment.status, "unassessed").label("status"),
        func.count(base.c.member_id),
    ).select_from(base).outerjoin(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).group_by(base.c.dim_key, "status").all()
    per_dim = defaultdict(lambda: {key: 0 for key in COVERAGE_STATUS_KEYS})
    for dim_key, status, count in rows:
        per_dim[dim_key][status] = int(count)
    return dict(per_dim)


def _dimension_column(dimension_type: str):
    if dimension_type == "branch":
        return models.TalentAssessmentCyclePopulationMember.branch_id
    if dimension_type == "grade":
        return models.TalentAssessmentCyclePopulationMember.grade_level
    if dimension_type == "section":
        return models.TalentAssessmentCyclePopulationMember.planning_section_id
    raise TalentAnalyticsError("invalid_filter", "dimension_type must be one of branch, grade, section.")


def section_labels(db: Session, pop_query) -> dict:
    rows = pop_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.planning_section_id,
        models.TalentAssessmentCyclePopulationMember.section_name,
    ).distinct().all()
    labels = {}
    for section_id, name in sorted(rows, key=lambda row: (row[0] is None, row[0], row[1])):
        labels.setdefault(section_id, name)
    return labels


# ---------------------------------------------------------------------------
# Candidate (Section Q) / Identification (Section R) - query-skip on permission
# ---------------------------------------------------------------------------


def _assessment_ids_subquery(db: Session, pop_query):
    return db.query(models.TalentStudentAssessment.id).filter(
        models.TalentStudentAssessment.cycle_population_member_id.in_(
            pop_query.with_entities(models.TalentAssessmentCyclePopulationMember.id)
        )
    )


def raw_candidate_count(db: Session, pop_query, *, has_permission: bool):
    if not has_permission:
        return None
    return int(db.query(func.count(models.TalentReviewCandidate.id)).filter(
        models.TalentReviewCandidate.assessment_id.in_(_assessment_ids_subquery(db, pop_query))
    ).scalar() or 0)


def raw_candidate_by_dimension(db: Session, pop_query, dimension_type: str, *, has_permission: bool):
    if not has_permission:
        return None
    dim_col = _dimension_column(dimension_type)
    base = pop_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        dim_col.label("dim_key"),
    ).subquery()
    rows = db.query(base.c.dim_key, func.count(models.TalentReviewCandidate.id)).select_from(base).join(
        models.TalentStudentAssessment, models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).join(
        models.TalentReviewCandidate, models.TalentReviewCandidate.assessment_id == models.TalentStudentAssessment.id,
    ).group_by(base.c.dim_key).all()
    return {dim_key: int(count) for dim_key, count in rows}


def _candidate_ids_subquery(db: Session, pop_query):
    return db.query(models.TalentReviewCandidate.id).filter(
        models.TalentReviewCandidate.assessment_id.in_(_assessment_ids_subquery(db, pop_query))
    )


def raw_identification_counts(db: Session, pop_query, *, has_permission: bool):
    if not has_permission:
        return None
    rows = db.query(
        models.TalentOfficialIdentification.decision, func.count(models.TalentOfficialIdentification.id),
    ).filter(
        models.TalentOfficialIdentification.review_candidate_id.in_(_candidate_ids_subquery(db, pop_query))
    ).group_by(models.TalentOfficialIdentification.decision).all()
    counts = {"identified": 0, "not_identified": 0}
    for decision, count in rows:
        counts[decision] = int(count)
    return counts


def raw_identification_by_dimension(db: Session, pop_query, dimension_type: str, *, has_permission: bool):
    if not has_permission:
        return None
    dim_col = _dimension_column(dimension_type)
    base = pop_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        dim_col.label("dim_key"),
    ).subquery()
    rows = db.query(
        base.c.dim_key, models.TalentOfficialIdentification.decision, func.count(models.TalentOfficialIdentification.id),
    ).select_from(base).join(
        models.TalentStudentAssessment, models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).join(
        models.TalentReviewCandidate, models.TalentReviewCandidate.assessment_id == models.TalentStudentAssessment.id,
    ).join(
        models.TalentOfficialIdentification, models.TalentOfficialIdentification.review_candidate_id == models.TalentReviewCandidate.id,
    ).group_by(base.c.dim_key, models.TalentOfficialIdentification.decision).all()
    per_dim = defaultdict(lambda: {"identified": 0, "not_identified": 0})
    for dim_key, decision, count in rows:
        per_dim[dim_key][decision] = int(count)
    return dict(per_dim)


def identified_metrics(counts: Optional[dict], candidate_count: Optional[int]) -> Optional[dict]:
    if counts is None:
        return None
    identified = counts["identified"]
    not_identified = counts["not_identified"]
    decision_state = "no_decisions" if identified == 0 and not_identified == 0 else "decisions_recorded"
    result = {
        "identified_count": identified, "not_identified_count": not_identified, "decision_state": decision_state,
    }
    if candidate_count:
        result["identified_of_eligible_candidates_percentage"] = percentage(identified, candidate_count)
    return result


# ---------------------------------------------------------------------------
# Rubric distribution (Section N) and Competency distribution (Section P)
# ---------------------------------------------------------------------------


def raw_rubric_level_counts(db: Session, pop_query, framework_version_id: int) -> dict:
    assessment_ids = _assessment_ids_subquery(db, pop_query).filter(
        models.TalentStudentAssessment.framework_version_id == framework_version_id
    )
    rows = db.query(
        models.TalentStudentCompetencyResult.rubric_level_id, func.count(models.TalentStudentCompetencyResult.id),
    ).filter(
        models.TalentStudentCompetencyResult.assessment_id.in_(assessment_ids)
    ).group_by(models.TalentStudentCompetencyResult.rubric_level_id).all()
    return {level_id: int(count) for level_id, count in rows}


def raw_competency_matrix(db: Session, pop_query, framework_version_id: int) -> dict:
    """Single GROUP BY (competency_id, rubric_level_id) query for the whole matrix (Section P)."""
    assessment_ids = _assessment_ids_subquery(db, pop_query).filter(
        models.TalentStudentAssessment.framework_version_id == framework_version_id
    )
    rows = db.query(
        models.TalentStudentCompetencyResult.framework_competency_id,
        models.TalentStudentCompetencyResult.rubric_level_id,
        func.count(models.TalentStudentCompetencyResult.id),
    ).filter(
        models.TalentStudentCompetencyResult.assessment_id.in_(assessment_ids)
    ).group_by(
        models.TalentStudentCompetencyResult.framework_competency_id, models.TalentStudentCompetencyResult.rubric_level_id,
    ).all()
    matrix = defaultdict(dict)
    for competency_id, level_id, count in rows:
        matrix[competency_id][level_id] = int(count)
    return dict(matrix)


def raw_kpi_valid_result_count(db: Session, pop_query, framework_version_id: int) -> int:
    return int(_assessment_ids_subquery(db, pop_query).filter(
        models.TalentStudentAssessment.framework_version_id == framework_version_id,
        models.TalentStudentAssessment.kpi_result.isnot(None),
    ).count())


# ---------------------------------------------------------------------------
# Insights (Section AB) - privacy-filtered inputs only
# ---------------------------------------------------------------------------


def build_insights(*, coverage_state: str, coverage: Optional[dict], execution_summary: dict,
                    kpi_configured: bool, comparison_state: Optional[str] = None,
                    comparison_reason: Optional[str] = None, any_hidden: bool = False) -> list:
    insights = []
    if coverage_state == NO_DATA or coverage is None:
        insights.append({"code": "no_authoritative_data", "severity": "info", "safe_parameters": {}})
    elif coverage_state == VISIBLE:
        insights.append({
            "code": "coverage_summary", "severity": "info",
            "safe_parameters": {
                "started_coverage_percentage": coverage["started_coverage_percentage"],
                "completion_coverage_percentage": coverage["completion_coverage_percentage"],
            },
        })
    insights.append({
        "code": "required_period_execution_summary", "severity": "info",
        "safe_parameters": {
            "required_period_count": execution_summary["required_period_count"],
            "required_executed_count": execution_summary["required_executed_count"],
            "required_cancelled_count": execution_summary["required_cancelled_count"],
            "required_outstanding_count": execution_summary["required_outstanding_count"],
        },
    })
    if not kpi_configured:
        insights.append({"code": "no_kpi_configured", "severity": "info", "safe_parameters": {}})
    if comparison_state == "not_comparable" and comparison_reason == "framework_changed":
        insights.append({"code": "framework_changed_comparison_blocked", "severity": "warning", "safe_parameters": {}})
    if comparison_state == "comparable":
        insights.append({"code": "full_period_population_comparison", "severity": "info", "safe_parameters": {}})
    if any_hidden:
        insights.append({"code": "value_suppressed_for_privacy", "severity": "info", "safe_parameters": {}})
    return insights


# ---------------------------------------------------------------------------
# Request context fingerprint (Section Z) - request parameters only, never
# underlying row data, so it is explicitly NOT a freshness/ETag proof.
# ---------------------------------------------------------------------------


def compute_request_context_fingerprint(*, program_id: int, academic_year_id: int, scope_signature,
                                         filters: ResolvedFilters, permission_projection: list,
                                         privacy_policy_version: str) -> str:
    payload = {
        "program_id": program_id,
        "academic_year_id": academic_year_id,
        "scope": scope_signature if scope_signature == "all" else sorted(scope_signature),
        "filters": filters.fingerprint_payload(),
        "permission_projection": sorted(permission_projection),
        "privacy_policy_version": privacy_policy_version,
    }
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def scope_signature(visible_branch_ids: Optional[set]):
    return "all" if visible_branch_ids is None else sorted(visible_branch_ids)


# ---------------------------------------------------------------------------
# Complementary-suppression wiring helpers for a single-dimension breakdown
# ---------------------------------------------------------------------------


def build_breakdown_group(*, name: str, privacy_class: str, total_raw: int, children_raw: dict) -> Group:
    total_cell = Cell(key=("total", name), privacy_class=privacy_class, raw_value=total_raw, depth=0)
    children = [
        Cell(key=("child", name, key), privacy_class=privacy_class, raw_value=value, depth=1)
        for key, value in sorted(children_raw.items(), key=lambda item: (item[0] is None, item[0]))
    ]
    return Group(name=name, total=total_cell, children=children)


def build_privacy_safe_coverage_bundle(*, name: str, counts: dict, privacy_class: str, policy) -> tuple:
    """Build the canonical privacy-safe coverage projection shared by every
    route that publishes a `frozen_eligible` + 5-status coverage breakdown
    (``/overview``, ``/rubric-distribution``, ``/period-comparison``).

    This is the single authority for the governing invariant: no
    privacy-sensitive value may be serialized merely because its parent/
    total/headline (``frozen_eligible``) passed privacy. Every per-status
    count is built as its own ``Cell`` and independently run through
    ``apply_primary_privacy``; ``frozen_eligible`` and the 5 status counts
    then form one ``Group`` (total = sum(children)) so
    ``run_complementary_suppression`` can hide an additional sibling whenever
    exactly one count would otherwise let the hidden count be reconstructed
    by subtraction from a visible total and its visible siblings.

    The full ``coverage_metrics`` shape (raw-looking numbers plus
    ``assessment_started``/percentage derivations) is only ever returned when
    EVERY source cell in the group - the total and all 5 statuses - is
    independently ``visible`` (matching ``/overview``'s existing, already-
    reviewed convention). Any other outcome collapses to a compact
    state-only projection (``coarsened`` with its policy-supplied safe
    replacement, ``no_data``, ``suppressed``, or ``restricted``) so a
    suppressed/coarsened/restricted count can never be reconstructed from a
    partially-published sibling set or from a percentage computed against a
    hidden value.

    Returns ``(coverage_payload_or_None, projection_state, group)``. The
    caller renders the response as
    ``coverage_payload if coverage_payload is not None else {"state": projection_state}``.
    """
    frozen_eligible = sum(counts.values())
    group = build_breakdown_group(
        name=name, privacy_class=privacy_class,
        total_raw=(frozen_eligible if frozen_eligible else None),
        children_raw={key: (value if frozen_eligible else None) for key, value in counts.items()},
    )
    group.total.context = {"metric": "frozen_eligible", "group": name}
    for cell in group.children:
        cell.context = {"metric": cell.key[2], "group": name}
    apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression([group], policy)
    total_cell = group.total
    by_status = {cell.key[2]: cell for cell in group.children}
    sources_visible = converged and all(cell.state == VISIBLE for cell in group.all_cells())
    projection_state = total_cell.state
    if sources_visible:
        # Derive only after every directly disclosed source count has passed
        # primary and complementary privacy evaluation.
        payload = coverage_metrics({key: by_status[key].value for key in COVERAGE_STATUS_KEYS})
    elif total_cell.state == COARSENED:
        # A coarsened headline count is a policy-supplied safe replacement for
        # frozen_eligible alone - it never licenses publishing the full raw
        # per-status coverage_metrics breakdown, whose raw source counts have
        # independent privacy decisions and could still leak real values.
        payload = {"state": COARSENED, "value": total_cell.value}
    elif total_cell.state == NO_DATA:
        payload = None
    else:
        projection_state = RESTRICTED if (
            not converged or any(cell.state == RESTRICTED for cell in group.all_cells())
        ) else SUPPRESSED
        payload = None
    return payload, projection_state, group


def cell_payload(cell: Cell) -> dict:
    # cell.value already carries either the visible raw value or a policy-
    # supplied coarsened safe replacement; every other state's value is
    # already None per apply_primary_privacy/run_complementary_suppression,
    # so no extra gating is needed (and gating on VISIBLE alone would drop a
    # legitimate coarsened replacement, publishing a misleading null).
    return {"state": cell.state, "value": cell.value}
