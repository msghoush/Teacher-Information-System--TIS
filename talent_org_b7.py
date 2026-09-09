"""M10 B7 Program Portfolio and Branch Intelligence closed projections."""

from __future__ import annotations

from dataclasses import dataclass

from talent_analytics_privacy import Cell, COARSENED, VISIBLE
from talent_analytics_privacy_closure import apply_primary_privacy_and_close
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import CellIdentity, MeasureComponent, MembershipGrain, MetricCode, Relationship, RelationshipTerm
from talent_org_intelligence_service import PrivacyClosedProjectionSet


PORTFOLIO_METRICS = (
    MetricCode.FROZEN_ELIGIBLE, MetricCode.COMPLETED, MetricCode.COMPLETION_COVERAGE,
    MetricCode.ASSESSMENT_STARTED, MetricCode.STARTED_COVERAGE,
    MetricCode.REQUIRED_PERIOD_EXECUTION,
)
BRANCH_METRICS = PORTFOLIO_METRICS[:5]
RATE_SOURCE = {
    MetricCode.COMPLETION_COVERAGE: ("completed", "population"),
    MetricCode.STARTED_COVERAGE: ("started", "population"),
    MetricCode.REQUIRED_PERIOD_EXECUTION: ("executed", "execution_denominator"),
}
COUNT_SOURCE = {
    MetricCode.FROZEN_ELIGIBLE: "population", MetricCode.COMPLETED: "completed",
    MetricCode.ASSESSMENT_STARTED: "started", MetricCode.CANDIDATE_COUNT: "candidate",
    MetricCode.IDENTIFIED_COUNT: "identified",
}
PRIVACY_CLASS = {metric: "P2" for metric in (*BRANCH_METRICS,)} | {
    MetricCode.REQUIRED_PERIOD_EXECUTION: "P1", MetricCode.CANDIDATE_COUNT: "P5",
    MetricCode.IDENTIFIED_COUNT: "P6",
}


@dataclass(frozen=True)
class B7ClosedProjection:
    closed: PrivacyClosedProjectionSet
    identities: dict[tuple, tuple[CellIdentity, ...]]
    relationships: tuple[Relationship, ...]


def _identity(context, metric, component, *, program_id=None, branch_id=None):
    grain = MembershipGrain.PERIOD_EXECUTION if metric == MetricCode.REQUIRED_PERIOD_EXECUTION else (
        MembershipGrain.REVIEW_CANDIDATE_MEMBERSHIP if metric == MetricCode.CANDIDATE_COUNT else
        MembershipGrain.IDENTIFICATION_MEMBERSHIP if metric == MetricCode.IDENTIFIED_COUNT else
        MembershipGrain.FROZEN_MEMBERSHIP
    )
    return CellIdentity(
        school_group_id=context.school_group_id, academic_year_id=context.academic_year_id,
        metric=metric, measure_component=component, membership_grain=grain,
        program_id=program_id, branch_id=branch_id,
    )


def build_closed_projection(*, context, program_ids, facts, metrics, policy, branch_id=None):
    identities = {}; raw = {}; relationships = []
    for metric in metrics:
        components = (MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR) if metric in RATE_SOURCE else (MeasureComponent.COUNT,)
        source_names = RATE_SOURCE.get(metric) or (COUNT_SOURCE[metric],)
        children = []
        for program_id in program_ids:
            ids = tuple(_identity(context, metric, component, program_id=program_id, branch_id=branch_id) for component in components)
            identities[("program", program_id, metric)] = ids
            fact = facts.get(program_id, {})
            authoritative = fact.get("population", 0) > 0 if metric != MetricCode.REQUIRED_PERIOD_EXECUTION else fact.get("execution_denominator", 0) > 0
            for identity, source in zip(ids, source_names):
                raw[identity] = int(fact.get(source, 0)) if authoritative else None
            children.append(ids)
        totals = tuple(_identity(context, metric, component, branch_id=branch_id) for component in components)
        identities[("total", metric)] = totals
        for index, total in enumerate(totals):
            authoritative_children = tuple(ids[index] for ids in children if raw[ids[index]] is not None)
            raw[total] = sum(raw[item] for item in authoritative_children) if authoritative_children else None
            if authoritative_children:
                relationships.append(Relationship((RelationshipTerm(total, 1), *(RelationshipTerm(item, -1) for item in authoritative_children)), 0))
    cells = {identity: Cell(identity.canonical_key(), PRIVACY_CLASS[identity.metric], value, context={
        "metric": identity.metric.value, "component": identity.measure_component.value,
        "program_id": identity.program_id, "branch_id": identity.branch_id,
    }) for identity, value in raw.items()}
    graph = PrivacyRelationshipGraph.from_contract(school_group_id=context.school_group_id, cells=cells, relationships=relationships)
    return B7ClosedProjection(PrivacyClosedProjectionSet(apply_primary_privacy_and_close(graph, cells, policy)), identities, tuple(relationships))


def _payload(result, identities):
    if len(identities) == 1:
        projection = result.closed.projection(identities[0]); payload = {"state": projection.state}
        if projection.state in (VISIBLE, COARSENED): payload["value"] = projection.value
        return payload
    rate = result.closed.derive_rate(*identities)
    if rate.state != VISIBLE: return {"state": rate.state}
    percentage = int(rate.percentage) if rate.percentage.denominator == 1 else float(rate.percentage)
    return result.closed.derived_payload(identities, {"numerator": rate.numerator, "denominator": rate.denominator, "percentage": percentage})


def serialize_projection(result, *, programs, metrics, context_payload, branch=None):
    if not isinstance(result, B7ClosedProjection) or not isinstance(result.closed, PrivacyClosedProjectionSet):
        raise TypeError("a B7 privacy-closed projection is required")
    rows = []
    for program in programs:
        row = {"program": program, "metrics": {metric.value: _payload(result, result.identities[("program", program["id"], metric)]) for metric in metrics}}
        rows.append(row)
    payload = {
        "projection_family": "branch_intelligence" if branch else "program_portfolio",
        "scope": context_payload, "programs": rows,
        "totals": {metric.value: _payload(result, result.identities[("total", metric)]) for metric in metrics},
        "comparability": {"mode": "common_factual_metrics", "ranking": False, "universal_score": False},
    }
    if branch: payload["branch"] = branch
    return payload
