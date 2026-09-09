"""M10 B10 privacy-closed Longitudinal Organization Intelligence (ADR 0027).

Read-only. One Talent Program x one Academic Year, ordered by the governed
M8 `TalentPlannedEvaluationPeriod.sequence`, aggregate/non-identifiable,
exactly one selected metric per response. This module contains NO
server-computed delta/change/percent-change arithmetic anywhere (the single
most safety-critical constraint in ADR 0027): adjacent points are compared
only through a `comparable`/`not_comparable` state plus an optional governed
reason code, never through a numeric difference.

Time model: the Period is the ordering/presentation authority; its optional
linked `TalentAssessmentCycle`, when authoritative (`open`/`closed`), is the
factual evidence authority for that point (ADR 0027's explicit correction of
an earlier Cycle-as-anchor draft). An unlinked/ad-hoc Cycle (no governed
Period) is excluded from this series entirely because it is never looked up
by period-linked `cycle_id`.

Every Cell built here uses ``relationships=()`` - there is no additive
Relationship of any kind, cross-time or same-point (no
``current = previous + delta`` topology, and no numerator/denominator total
fabrication). Each point/component is privacy-closed independently through
the identical B2 `apply_primary_privacy_and_close` pipeline every other M10
route uses; a rate is derived only from two already-closed components via
the shared `derive_exact_rate`/`project_safe_derived_payload` helpers,
matching every other M10 rate metric exactly - this module implements no
percentage math of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func

import models
from talent_analytics_privacy import Cell, COARSENED, VISIBLE
from talent_analytics_privacy_closure import apply_primary_privacy_and_close
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import (
    METRIC_IDENTITY_MAPPING, CellIdentity, MetricCode,
)
from talent_org_intelligence_service import PrivacyClosedProjectionSet


PROJECTION_FAMILY = "program_longitudinal"

LONGITUDINAL_METRICS = frozenset({
    MetricCode.FROZEN_ELIGIBLE, MetricCode.COMPLETED, MetricCode.COMPLETION_COVERAGE,
    MetricCode.ASSESSMENT_STARTED, MetricCode.STARTED_COVERAGE,
    MetricCode.CANDIDATE_COUNT, MetricCode.CANDIDATE_OF_ELIGIBLE,
    MetricCode.IDENTIFIED_COUNT, MetricCode.IDENTIFIED_OF_ELIGIBLE,
})
EXCLUDED_METRICS = frozenset({
    MetricCode.REQUIRED_PERIOD_EXECUTION, MetricCode.PROGRAMS_CONFIGURED,
    MetricCode.ACTIVE_PROGRAMS, MetricCode.PARTICIPATION_OVERLAP,
    MetricCode.STUDENT_DRILL_POPULATION,
})
COUNT_METRICS = frozenset({
    MetricCode.FROZEN_ELIGIBLE, MetricCode.COMPLETED, MetricCode.ASSESSMENT_STARTED,
    MetricCode.CANDIDATE_COUNT, MetricCode.IDENTIFIED_COUNT,
})
COUNT_SOURCE = {
    MetricCode.FROZEN_ELIGIBLE: "population", MetricCode.COMPLETED: "completed",
    MetricCode.ASSESSMENT_STARTED: "started", MetricCode.CANDIDATE_COUNT: "candidate",
    MetricCode.IDENTIFIED_COUNT: "identified",
}
RATE_NUMERATOR_SOURCE = {
    MetricCode.COMPLETION_COVERAGE: "completed", MetricCode.STARTED_COVERAGE: "started",
    MetricCode.CANDIDATE_OF_ELIGIBLE: "candidate", MetricCode.IDENTIFIED_OF_ELIGIBLE: "identified",
}
FRAMEWORK_SENSITIVE_METRICS = frozenset({
    MetricCode.CANDIDATE_COUNT, MetricCode.CANDIDATE_OF_ELIGIBLE,
    MetricCode.IDENTIFIED_COUNT, MetricCode.IDENTIFIED_OF_ELIGIBLE,
})
PRIVACY_CLASS = {
    MetricCode.FROZEN_ELIGIBLE: "P2", MetricCode.COMPLETED: "P2", MetricCode.COMPLETION_COVERAGE: "P2",
    MetricCode.ASSESSMENT_STARTED: "P2", MetricCode.STARTED_COVERAGE: "P2",
    MetricCode.CANDIDATE_COUNT: "P5", MetricCode.CANDIDATE_OF_ELIGIBLE: "P5",
    MetricCode.IDENTIFIED_COUNT: "P6", MetricCode.IDENTIFIED_OF_ELIGIBLE: "P6",
}
NOT_COMPARABLE_REASON_CODES = frozenset({
    "missing_cycle", "cycle_not_authoritative", "cancelled_period", "no_frozen_population",
    "metric_unavailable", "framework_changed", "privacy_protected",
})


def requires_candidate_permission(metric: MetricCode) -> bool:
    return metric in (MetricCode.CANDIDATE_COUNT, MetricCode.CANDIDATE_OF_ELIGIBLE)


def requires_identification_permission(metric: MetricCode) -> bool:
    return metric in (MetricCode.IDENTIFIED_COUNT, MetricCode.IDENTIFIED_OF_ELIGIBLE)


@dataclass(frozen=True)
class PeriodSlot:
    """One ordered M8 Period presentation point and its structural status.

    ``reason_code`` is ``None`` only when the Period is `planned` and its
    linked Cycle (if any) is `open`/`closed` - i.e. structurally eligible to
    carry factual evidence. It does NOT yet account for an empty frozen
    population; that is resolved later once the bounded coverage query runs.
    """

    period_id: int
    sequence: int
    label: str
    period_status: str
    cycle_id: Optional[int]
    cycle_status: Optional[str]
    framework_version_id: Optional[int]
    reason_code: Optional[str]


@dataclass(frozen=True)
class LongitudinalClosedProjection:
    """The only accepted B10 serialization input.

    Mirrors B8's/B9's strict closed-wrapper discipline: construction itself
    raises ``TypeError`` for anything but a real B2 `PrivacyClosedProjectionSet`
    and real `PeriodSlot` instances, so no raw SQL row, ORM object, or
    unclosed point can ever reach the serializer.
    """

    closed: PrivacyClosedProjectionSet
    metric: MetricCode
    slots: tuple
    identities: dict

    def __post_init__(self):
        if not isinstance(self.closed, PrivacyClosedProjectionSet):
            raise TypeError("a B2 PrivacyClosedProjectionSet is required")
        if not isinstance(self.metric, MetricCode):
            raise TypeError("a canonical MetricCode is required")
        if not isinstance(self.slots, tuple) or not all(isinstance(slot, PeriodSlot) for slot in self.slots):
            raise TypeError("only closed PeriodSlot projections may serialize")
        if not isinstance(self.identities, dict) or set(self.identities) != {slot.period_id for slot in self.slots}:
            raise TypeError("identities must exactly cover the closed PeriodSlot series")


def fetch_plan(db, *, school_group_id: int, program_id: int, academic_year_id: int):
    """Return the single governed M8 Plan for this Program/AY, or ``None``.

    ``uq_talent_annual_evaluation_plans_config`` guarantees at most one Plan
    per Program Academic-Year configuration, so this is never ambiguous. A
    missing Plan means zero Periods can exist (Period has a mandatory FK to
    its Plan) - the caller returns an empty, non-fabricated ordered series.
    """

    return db.query(models.TalentAnnualEvaluationPlan).filter_by(
        school_group_id=school_group_id, program_id=program_id, academic_year_id=academic_year_id,
    ).one_or_none()


def fetch_period_slots(db, *, school_group_id: int, program_id: int, plan_id: int) -> tuple:
    """One bounded set-based query for every ordered Period + its linked Cycle.

    Never one query per Period. An ad-hoc Cycle with no
    ``planned_evaluation_period_id`` is never joined here and therefore can
    never enter the series (ADR 0027's unlinked-Cycle exclusion).
    """

    rows = db.query(
        models.TalentPlannedEvaluationPeriod, models.TalentAssessmentCycle,
    ).select_from(models.TalentPlannedEvaluationPeriod).outerjoin(
        models.TalentAssessmentCycle,
        (models.TalentAssessmentCycle.planned_evaluation_period_id == models.TalentPlannedEvaluationPeriod.id)
        & (models.TalentAssessmentCycle.school_group_id == school_group_id)
        & (models.TalentAssessmentCycle.program_id == program_id),
    ).filter(
        models.TalentPlannedEvaluationPeriod.school_group_id == school_group_id,
        models.TalentPlannedEvaluationPeriod.program_id == program_id,
        models.TalentPlannedEvaluationPeriod.annual_evaluation_plan_id == plan_id,
    ).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()

    slots = []
    for period, cycle in rows:
        if period.status == "cancelled":
            reason = "cancelled_period"
        elif cycle is None:
            reason = "missing_cycle"
        elif cycle.status == "draft":
            reason = "cycle_not_authoritative"
        else:
            reason = None
        slots.append(PeriodSlot(
            period_id=period.id, sequence=period.sequence, label=period.label,
            period_status=period.status,
            cycle_id=(cycle.id if cycle is not None else None),
            cycle_status=(cycle.status if cycle is not None else None),
            framework_version_id=(cycle.framework_version_id if cycle is not None else None),
            reason_code=reason,
        ))
    return tuple(slots)


def coverage_by_cycle(db, population_query) -> dict[int, dict[str, int]]:
    """One grouped-by-Cycle aggregate: population/completed/started counts.

    ``population_query`` already applies tenant/AY/Program/historical-Branch
    scope and any Grade/Section filters (``frozen_membership_query``) and is
    already restricted to `open`/`closed` Cycles - so this single query
    covers every Period point regardless of how many Periods exist.
    """

    base = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        models.TalentAssessmentCyclePopulationMember.cycle_id.label("cycle_id"),
    ).subquery()
    status = func.coalesce(models.TalentStudentAssessment.status, "unassessed").label("status")
    rows = db.query(base.c.cycle_id, status, func.count(base.c.member_id)).select_from(base).outerjoin(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).group_by(base.c.cycle_id, status).all()
    result: dict[int, dict[str, int]] = {}
    for cycle_id, status_value, count in rows:
        fact = result.setdefault(int(cycle_id), {"population": 0, "completed": 0, "started": 0})
        fact["population"] += int(count)
        if status_value == "completed":
            fact["completed"] += int(count)
        if status_value != "unassessed":
            fact["started"] += int(count)
    return result


def _sensitive_counts_by_cycle(db, population_query, *, resource: str) -> dict[int, int]:
    base = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        models.TalentAssessmentCyclePopulationMember.cycle_id.label("cycle_id"),
    ).subquery()
    query = db.query(base.c.cycle_id).select_from(base).join(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).join(
        models.TalentReviewCandidate,
        models.TalentReviewCandidate.assessment_id == models.TalentStudentAssessment.id,
    )
    if resource == "candidate":
        query = query.add_columns(func.count(models.TalentReviewCandidate.id))
    else:
        query = query.join(
            models.TalentOfficialIdentification,
            models.TalentOfficialIdentification.review_candidate_id == models.TalentReviewCandidate.id,
        ).filter(models.TalentOfficialIdentification.decision == "identified").add_columns(
            func.count(models.TalentOfficialIdentification.id)
        )
    rows = query.group_by(base.c.cycle_id).all()
    return {int(cycle_id): int(count) for cycle_id, count in rows}


def candidate_counts_by_cycle(db, population_query) -> dict[int, int]:
    """Bounded one-query Candidate count grouped by Cycle. Caller MUST gate
    this behind both the selected metric and `talent_review_candidates.view`
    - it must never be invoked otherwise."""

    return _sensitive_counts_by_cycle(db, population_query, resource="candidate")


def identified_counts_by_cycle(db, population_query) -> dict[int, int]:
    """Bounded one-query identified count grouped by Cycle. Caller MUST gate
    this behind both the selected metric and
    `talent_official_identifications.view` - it must never be invoked
    otherwise."""

    return _sensitive_counts_by_cycle(db, population_query, resource="identification")


def _values_for(metric: MetricCode, fact: dict, authoritative: bool) -> tuple:
    if not authoritative:
        return (None,) if metric in COUNT_METRICS else (None, None)
    if metric in COUNT_METRICS:
        return (int(fact.get(COUNT_SOURCE[metric], 0)),)
    return (int(fact.get(RATE_NUMERATOR_SOURCE[metric], 0)), int(fact.get("population", 0)))


def build_closed_projection(
    *, context, program_id: int, metric: MetricCode, slots: tuple,
    coverage: dict[int, dict[str, int]],
    candidate_counts: Optional[dict[int, int]],
    identified_counts: Optional[dict[int, int]],
    policy,
) -> LongitudinalClosedProjection:
    """Build every point's Cell(s), then run ONE shared B2 closure pass.

    There is deliberately no Relationship of any kind here (``relationships
    =()``) - no same-point numerator/denominator total, and no cross-time
    additive equation. Each point's Cell(s) are therefore always trivially
    their own connected component; this is an intentional structural
    guarantee that no cross-time reconstruction topology can ever exist.
    """

    components, grain = METRIC_IDENTITY_MAPPING[metric]
    privacy_class = PRIVACY_CLASS[metric]
    identities: dict[int, tuple] = {}
    raw: dict[CellIdentity, Optional[int]] = {}

    for slot in slots:
        fact = dict(coverage.get(slot.cycle_id, {})) if slot.reason_code is None and slot.cycle_id is not None else {}
        authoritative = slot.reason_code is None and fact.get("population", 0) > 0
        if candidate_counts is not None:
            fact["candidate"] = candidate_counts.get(slot.cycle_id, 0)
        if identified_counts is not None:
            fact["identified"] = identified_counts.get(slot.cycle_id, 0)
        no_data_reason = slot.reason_code if slot.reason_code is not None else (None if authoritative else "no_frozen_population")
        ids = tuple(
            CellIdentity(
                school_group_id=context.school_group_id, academic_year_id=context.academic_year_id,
                metric=metric, measure_component=component, membership_grain=grain,
                program_id=program_id, period_id=slot.period_id,
                cycle_id=(slot.cycle_id if authoritative else None),
                framework_version_id=(slot.framework_version_id if authoritative else None),
            )
            for component in components
        )
        identities[slot.period_id] = (ids, no_data_reason)
        raw.update(zip(ids, _values_for(metric, fact, authoritative)))

    cells = {
        identity: Cell(
            key=identity.canonical_key(), privacy_class=privacy_class, raw_value=value,
            context={"metric": metric.value, "program_id": program_id, "period_id": identity.period_id},
        )
        for identity, value in raw.items()
    }
    graph = PrivacyRelationshipGraph.from_contract(
        school_group_id=context.school_group_id, cells=cells, relationships=(),
    )
    closed = PrivacyClosedProjectionSet(apply_primary_privacy_and_close(graph, cells, policy))
    return LongitudinalClosedProjection(closed=closed, metric=metric, slots=slots, identities=identities)


def _point_payload(closed: PrivacyClosedProjectionSet, ids: tuple) -> tuple[dict, str]:
    if len(ids) == 1:
        projection = closed.projection(ids[0])
        payload = {"state": projection.state}
        if projection.state in (VISIBLE, COARSENED):
            payload["value"] = projection.value
        return payload, projection.state
    derived = closed.derive_rate(ids[0], ids[1])
    if derived.state != VISIBLE:
        return {"state": derived.state}, derived.state
    percentage = int(derived.percentage) if derived.percentage.denominator == 1 else float(derived.percentage)
    payload = closed.derived_payload(ids, {
        "numerator": derived.numerator, "denominator": derived.denominator, "percentage": percentage,
    })
    return payload, derived.state


def _comparability(first: tuple, second: tuple, metric: MetricCode) -> tuple[str, Optional[str]]:
    """Deterministic ADR 0027 precedence: missing/cancelled/no-population
    reasons outrank privacy, which outranks Framework sensitivity.

    ``first``/``second`` are ``(reason_code, disclosure_state,
    framework_version_id)`` tuples, in ordered-sequence order; when both
    points are independently non-authoritative, the earlier (lower-sequence)
    point's reason is reported, purely for determinism.
    """

    for reason, _state, _framework_version_id in (first, second):
        if reason is not None:
            return "not_comparable", reason
    for _reason, state, _framework_version_id in (first, second):
        if state not in (VISIBLE, COARSENED):
            return "not_comparable", "privacy_protected"
    if metric in FRAMEWORK_SENSITIVE_METRICS and first[2] != second[2]:
        return "not_comparable", "framework_changed"
    return "comparable", None


def build_points_and_comparisons(result: LongitudinalClosedProjection, *, plan, academic_year_id: int) -> tuple[list, list]:
    """Serialize the ordered points, then the adjacent comparisons.

    Comparison construction re-reads the already-computed disclosure state
    captured while building each point - it never re-evaluates privacy, and
    it never computes or exposes any numeric difference.
    """

    if not isinstance(result, LongitudinalClosedProjection):
        raise TypeError("a B10 privacy-closed longitudinal projection is required")
    points = []
    disclosure = {}
    for slot in result.slots:
        ids, reason = result.identities[slot.period_id]
        payload, state = _point_payload(result.closed, ids)
        if reason is not None:
            payload = {"state": "no_data"}
        point = {
            "academic_year_id": academic_year_id,
            "program_academic_year_configuration_id": plan.program_academic_year_configuration_id,
            "annual_evaluation_plan_id": plan.id,
            "evaluation_period": {
                "id": slot.period_id, "sequence": slot.sequence,
                "label": slot.label, "status": slot.period_status,
            },
            "cycle": (
                {
                    "id": slot.cycle_id, "status": slot.cycle_status,
                    "framework_version_id": (slot.framework_version_id if reason is None else None),
                } if slot.cycle_id is not None else None
            ),
            "metric_result": payload,
        }
        if reason is not None:
            point["no_data_reason"] = reason
        points.append(point)
        disclosure[slot.period_id] = (reason, ("no_data" if reason is not None else state), (
            slot.framework_version_id if reason is None else None
        ))
    comparisons = []
    for first_slot, second_slot in zip(result.slots, result.slots[1:]):
        state, reason_code = _comparability(
            disclosure[first_slot.period_id], disclosure[second_slot.period_id], result.metric,
        )
        comparisons.append({
            "evaluation_period_ids": [first_slot.period_id, second_slot.period_id],
            "state": state, "reason_code": reason_code,
        })
    return points, comparisons


def serialize_projection(result: LongitudinalClosedProjection, *, program: dict, academic_year: dict, plan, scope: dict) -> dict:
    if not isinstance(result, LongitudinalClosedProjection):
        raise TypeError("a B10 privacy-closed longitudinal projection is required")
    points, comparisons = ([], []) if plan is None else build_points_and_comparisons(
        result, plan=plan, academic_year_id=academic_year["id"],
    )
    return {
        "projection_family": PROJECTION_FAMILY,
        "program": program,
        "academic_year": academic_year,
        "metric": result.metric.value,
        "scope": scope,
        "points": points,
        "comparisons": comparisons,
    }
