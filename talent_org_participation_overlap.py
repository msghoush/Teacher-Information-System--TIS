"""M10 B8 privacy-closed Program participation intersections."""

from __future__ import annotations

from dataclasses import dataclass

from talent_analytics_privacy import Cell, COARSENED, VISIBLE
from talent_analytics_privacy_closure import apply_primary_privacy_and_close
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import (
    PARTICIPATION_OVERLAP_PRIVACY_CLASS, CellIdentity, MeasureComponent,
    MembershipGrain, MetricCode,
)
from talent_org_intelligence_service import PrivacyClosedProjectionSet


PRIVACY_CLASS = PARTICIPATION_OVERLAP_PRIVACY_CLASS


@dataclass(frozen=True)
class ParticipationOverlapClosedProjection:
    closed: PrivacyClosedProjectionSet
    identities: dict[tuple[int, int], CellIdentity]


def canonical_pair_key(first_program_id: int, second_program_id: int) -> tuple[int, int]:
    """Return the data/privacy key independently of presentation ordering."""

    return tuple(sorted((first_program_id, second_program_id)))


def identity(context, first_program_id: int, second_program_id: int) -> CellIdentity:
    return CellIdentity(
        school_group_id=context.school_group_id,
        academic_year_id=context.academic_year_id,
        metric=MetricCode.PARTICIPATION_OVERLAP,
        measure_component=MeasureComponent.COUNT,
        membership_grain=MembershipGrain.PROGRAM_PARTICIPATION,
        overlap_program_ids=(first_program_id, second_program_id),
    )


def build_closed_projection(*, context, program_ids, overlap_counts, policy):
    identities = {}
    cells = {}
    participant_basis = {program_id for pair, value in overlap_counts.items() for program_id in pair if value is not None}
    for index, first_program_id in enumerate(program_ids):
        for second_program_id in program_ids[index:]:
            pair = canonical_pair_key(first_program_id, second_program_id)
            cell_identity = identity(context, *pair)
            identities[pair] = cell_identity
            authoritative = first_program_id in participant_basis and second_program_id in participant_basis
            raw_value = int(overlap_counts.get(pair, 0)) if authoritative else None
            cells[cell_identity] = Cell(
                cell_identity.canonical_key(), PRIVACY_CLASS, raw_value,
                context={"metric": MetricCode.PARTICIPATION_OVERLAP.value},
            )
    graph = PrivacyRelationshipGraph.from_contract(
        school_group_id=context.school_group_id, cells=cells, relationships=(),
    )
    return ParticipationOverlapClosedProjection(
        PrivacyClosedProjectionSet(apply_primary_privacy_and_close(graph, cells, policy)), identities,
    )


def _cell_payload(result, pair):
    pair_key = canonical_pair_key(*pair)
    projection = result.closed.projection(result.identities[pair_key])
    payload = {"state": projection.state}
    if projection.state in (VISIBLE, COARSENED):
        payload["value"] = projection.value
    return payload


def serialize_projection(result, *, programs, context_payload):
    if not isinstance(result, ParticipationOverlapClosedProjection) or not isinstance(result.closed, PrivacyClosedProjectionSet):
        raise TypeError("a B8 privacy-closed projection is required")
    matrix = []
    for row in programs:
        matrix.append({
            "program_id": row["id"],
            "cells": [
                {"program_id": column["id"], **_cell_payload(result, (row["id"], column["id"]))}
                for column in programs
            ],
        })
    canonical_pairs = [
        {
            "program_ids": [first, second],
            **_cell_payload(result, (first, second)),
        }
        for first, second in sorted(result.identities)
    ]
    return {
        "projection_family": "participation_overlap",
        "scope": context_payload,
        "programs": list(programs),
        "matrix": matrix,
        "canonical_pairs": canonical_pairs,
        "semantics": {"diagonal": "distinct_program_participants", "symmetric": True},
    }
