"""M10 B6 canonical Talent Map graph construction and closed serialization."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from talent_analytics_privacy import Cell, COARSENED, VISIBLE
from talent_analytics_privacy_closure import apply_primary_privacy_and_close
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import (
    CellIdentity, MeasureComponent, MembershipGrain, MetricCode, Relationship, RelationshipTerm,
)
from talent_org_intelligence_service import PrivacyClosedProjectionSet


COUNT_METRICS = {
    MetricCode.FROZEN_ELIGIBLE, MetricCode.COMPLETED, MetricCode.ASSESSMENT_STARTED,
    MetricCode.CANDIDATE_COUNT, MetricCode.IDENTIFIED_COUNT,
}
RATE_METRICS = {
    MetricCode.COMPLETION_COVERAGE: "completed",
    MetricCode.STARTED_COVERAGE: "started",
    MetricCode.CANDIDATE_OF_ELIGIBLE: "candidate",
    MetricCode.IDENTIFIED_OF_ELIGIBLE: "identified",
}
PRIVACY_CLASS = {
    MetricCode.FROZEN_ELIGIBLE: "P2", MetricCode.COMPLETED: "P2",
    MetricCode.COMPLETION_COVERAGE: "P2", MetricCode.ASSESSMENT_STARTED: "P2",
    MetricCode.STARTED_COVERAGE: "P2", MetricCode.CANDIDATE_COUNT: "P5",
    MetricCode.CANDIDATE_OF_ELIGIBLE: "P5", MetricCode.IDENTIFIED_COUNT: "P6",
    MetricCode.IDENTIFIED_OF_ELIGIBLE: "P6",
}


@dataclass(frozen=True)
class TalentMapClosedResult:
    closed: PrivacyClosedProjectionSet
    identities: dict[tuple, tuple[CellIdentity, ...]]
    relationships: tuple[Relationship, ...]


def _identity(context, metric, component, *, program_id=None, dimension="branch", dimension_value=None):
    return CellIdentity(
        school_group_id=context.school_group_id, academic_year_id=context.academic_year_id,
        metric=metric, measure_component=component,
        membership_grain=(
            MembershipGrain.REVIEW_CANDIDATE_MEMBERSHIP if metric in {MetricCode.CANDIDATE_COUNT, MetricCode.CANDIDATE_OF_ELIGIBLE}
            else MembershipGrain.IDENTIFICATION_MEMBERSHIP if metric in {MetricCode.IDENTIFIED_COUNT, MetricCode.IDENTIFIED_OF_ELIGIBLE}
            else MembershipGrain.FROZEN_MEMBERSHIP
        ),
        program_id=program_id,
        branch_id=int(dimension_value) if dimension == "branch" and dimension_value is not None else None,
        grade_level=str(dimension_value) if dimension == "grade" and dimension_value is not None else None,
    )


def build_talent_map_closed(
    *, context, dimension: str, metric: MetricCode, program_ids: tuple[int, ...],
    column_values: tuple[object, ...], facts: dict[tuple[int, object], dict[str, int]], policy,
) -> TalentMapClosedResult:
    components = (MeasureComponent.COUNT,) if metric in COUNT_METRICS else (MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR)
    identities: dict[tuple, tuple[CellIdentity, ...]] = {}
    raw: dict[CellIdentity, int | None] = {}

    def authoritative_children(children):
        """One source for both total arithmetic and additive topology."""
        return tuple(item for item in children if raw[item] is not None)

    def add_total(total, children):
        authoritative = authoritative_children(children)
        raw[total] = sum(raw[item] for item in authoritative) if authoritative else None
        if authoritative:
            relationships.append(Relationship((
                RelationshipTerm(total, 1),
                *(RelationshipTerm(item, -1) for item in authoritative),
            ), 0))

    def values_for(fact):
        population = fact.get("population", 0)
        if not population:
            return (None,) * len(components)
        if metric == MetricCode.FROZEN_ELIGIBLE:
            return (population,)
        if metric == MetricCode.COMPLETED:
            return (fact.get("completed", 0),)
        if metric == MetricCode.ASSESSMENT_STARTED:
            return (fact.get("started", 0),)
        if metric == MetricCode.CANDIDATE_COUNT:
            return (fact.get("candidate", 0),)
        if metric == MetricCode.IDENTIFIED_COUNT:
            return (fact.get("identified", 0),)
        return (fact.get(RATE_METRICS[metric], 0), population)

    for program_id in program_ids:
        for value in column_values:
            ids = tuple(_identity(context, metric, component, program_id=program_id, dimension=dimension, dimension_value=value) for component in components)
            identities[("cell", program_id, value)] = ids
            raw.update(zip(ids, values_for(facts.get((program_id, value), {}))))

    relationships = []
    for component_index, component in enumerate(components):
        for program_id in program_ids:
            children = tuple(identities[("cell", program_id, value)][component_index] for value in column_values)
            total = _identity(context, metric, component, program_id=program_id, dimension=dimension)
            identities[("row_total", program_id)] = tuple(
                total if index == component_index else identities[("row_total", program_id)][index]
                for index in range(len(components))
            ) if ("row_total", program_id) in identities else tuple(
                _identity(context, metric, item, program_id=program_id, dimension=dimension) for item in components
            )
            add_total(total, children)
        for value in column_values:
            children = tuple(identities[("cell", program_id, value)][component_index] for program_id in program_ids)
            total = _identity(context, metric, component, dimension=dimension, dimension_value=value)
            identities[("column_total", value)] = tuple(
                _identity(context, metric, item, dimension=dimension, dimension_value=value) for item in components
            )
            add_total(total, children)
        row_totals = tuple(identities[("row_total", program_id)][component_index] for program_id in program_ids)
        organization = _identity(context, metric, component, dimension=dimension)
        identities["organization_total"] = tuple(
            _identity(context, metric, item, dimension=dimension) for item in components
        )
        add_total(organization, row_totals)

    cells = {identity: Cell(identity.canonical_key(), PRIVACY_CLASS[metric], value, context={
        "metric": metric.value, "component": identity.measure_component.value,
        "program_id": identity.program_id, "branch_id": identity.branch_id,
        "grade_level": identity.grade_level,
    }) for identity, value in raw.items()}
    graph = PrivacyRelationshipGraph.from_contract(
        school_group_id=context.school_group_id, cells=cells, relationships=relationships,
    )
    closed = PrivacyClosedProjectionSet(apply_primary_privacy_and_close(graph, cells, policy))
    return TalentMapClosedResult(closed, identities, tuple(relationships))


def _payload(closed, identities):
    if len(identities) == 1:
        projection = closed.projection(identities[0])
        result = {"state": projection.state}
        if projection.state in (VISIBLE, COARSENED):
            result["value"] = projection.value
        return result
    rate = closed.derive_rate(*identities)
    if rate.state != VISIBLE:
        return {"state": rate.state}
    percentage = int(rate.percentage) if rate.percentage.denominator == 1 else float(rate.percentage)
    return closed.derived_payload(identities, {"numerator": rate.numerator, "denominator": rate.denominator, "percentage": percentage})


def serialize_talent_map(
    result: TalentMapClosedResult, *, requested_orientation: str, canonical_dimension: str,
    metric: MetricCode, programs: tuple[dict, ...], columns: tuple[dict, ...], context_payload: dict,
) -> dict:
    if not isinstance(result, TalentMapClosedResult) or not isinstance(result.closed, PrivacyClosedProjectionSet):
        raise TypeError("a privacy-closed Talent Map result is required")
    cells = []
    for program in programs:
        for column in columns:
            value = column["id"]
            payload = _payload(result.closed, result.identities[("cell", program["id"], value)])
            coordinates = {"program_id": program["id"], f"{canonical_dimension}_id" if canonical_dimension == "branch" else "grade_level": value}
            cells.append({"coordinates": coordinates, **payload})
    return {
        "projection_family": f"program_{canonical_dimension}", "orientation": requested_orientation,
        "metric": metric.value, "scope": context_payload,
        "rows": programs if requested_orientation != "branch_program" else columns,
        "columns": columns if requested_orientation != "branch_program" else programs,
        "cells": cells,
        "row_totals": [{"program_id": item["id"], **_payload(result.closed, result.identities[("row_total", item["id"])])} for item in programs],
        "column_totals": [{("branch_id" if canonical_dimension == "branch" else "grade_level"): item["id"], **_payload(result.closed, result.identities[("column_total", item["id"])])} for item in columns],
        "organization_total": _payload(result.closed, result.identities["organization_total"]),
        "comparability": {"mode": "common_factual_metric", "cross_program_score": False},
    }
