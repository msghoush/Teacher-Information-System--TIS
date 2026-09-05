"""M10 B2 exact reconstruction analysis and privacy graph closure.

This module is deliberately query-, ORM-, router-, and UI-free. It consumes
the canonical B0/B1 topology, applies M9 primary privacy through one explicit
pipeline, and uses exact rational linear algebra for complementary closure.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Iterable, Mapping, Optional

from talent_analytics_privacy import (
    COARSENED,
    NO_DATA,
    PRIVACY_CLASSES,
    RESTRICTED,
    SUPPRESSED,
    VISIBLE,
    Cell,
    apply_primary_privacy,
)
from talent_analytics_relationship_graph import (
    PrivacyRelationshipComponent,
    PrivacyRelationshipGraph,
)
from talent_org_intelligence_contract import CellIdentity, PrivacyProjection


_PROTECTED = frozenset((SUPPRESSED, COARSENED, RESTRICTED))
_CLASS_ORDER = {privacy_class: index for index, privacy_class in enumerate(PRIVACY_CLASSES)}


class PrivacyClosureError(ValueError):
    """Invalid or untrusted B2 input; callers must fail closed."""


@dataclass(frozen=True)
class ReconstructionAnalysis:
    protected_unknown_keys: tuple[CellIdentity, ...]
    uniquely_reconstructable_keys: tuple[CellIdentity, ...]
    consistent: bool
    rank: int
    augmented_rank: int
    safe: bool
    reason_code: Optional[str] = None


@dataclass(frozen=True)
class PrivacyClosureResult:
    projections: tuple[PrivacyProjection, ...]
    analyses: tuple[ReconstructionAnalysis, ...]
    victim_keys: tuple[CellIdentity, ...]
    safe: bool

    def projection_for(self, identity: CellIdentity) -> PrivacyProjection:
        for projection in self.projections:
            if projection.identity == identity:
                return projection
        raise KeyError(identity)


@dataclass(frozen=True)
class DerivedRateProjection:
    state: str
    numerator: Optional[int] = None
    denominator: Optional[int] = None
    rate: Optional[Fraction] = None
    percentage: Optional[Fraction] = None
    reason_code: Optional[str] = None


def _rref(matrix: list[list[Fraction]], variable_count: int) -> tuple[list[list[Fraction]], tuple[int, ...]]:
    rows = [row[:] for row in matrix]
    pivots = []
    pivot_row = 0
    for column in range(variable_count):
        selected = next((index for index in range(pivot_row, len(rows)) if rows[index][column]), None)
        if selected is None:
            continue
        rows[pivot_row], rows[selected] = rows[selected], rows[pivot_row]
        divisor = rows[pivot_row][column]
        rows[pivot_row] = [value / divisor for value in rows[pivot_row]]
        for index, row in enumerate(rows):
            if index == pivot_row or not row[column]:
                continue
            factor = row[column]
            rows[index] = [value - factor * pivot for value, pivot in zip(row, rows[pivot_row])]
        pivots.append(column)
        pivot_row += 1
        if pivot_row == len(rows):
            break
    return rows, tuple(pivots)


def analyze_reconstruction(
    component: PrivacyRelationshipComponent,
    projections: Mapping[CellIdentity, PrivacyProjection],
) -> ReconstructionAnalysis:
    """Analyze exact uniqueness of each protected coordinate independently."""

    missing = set(component.cells) - set(projections)
    if missing:
        raise PrivacyClosureError("component has Cells without privacy projections")
    unknowns = tuple(sorted(
        (cell for cell in component.cells if projections[cell].state in _PROTECTED),
        key=CellIdentity.canonical_key,
    ))
    unknown_index = {cell: index for index, cell in enumerate(unknowns)}
    matrix: list[list[Fraction]] = []
    for relationship in component.relationships:
        # A no_data coordinate means this asserted aggregate equation is not
        # authoritative for this request; it is never substituted as zero.
        if any(projections[term.cell].state == NO_DATA for term in relationship.terms):
            continue
        rhs = Fraction(relationship.constant)
        coefficients = [Fraction(0) for _ in unknowns]
        for term in relationship.terms:
            projection = projections[term.cell]
            if projection.state == VISIBLE:
                if projection.value is None:
                    raise PrivacyClosureError("visible Cell lacks an exact value")
                rhs -= Fraction(term.coefficient * projection.value)
            elif projection.state in _PROTECTED:
                coefficients[unknown_index[term.cell]] += Fraction(term.coefficient)
            else:
                raise PrivacyClosureError("unknown privacy state")
        matrix.append([*coefficients, rhs])

    reduced, pivots = _rref(matrix, len(unknowns))
    rank = len(pivots)
    inconsistent = any(
        all(value == 0 for value in row[:len(unknowns)]) and row[len(unknowns)] != 0
        for row in reduced
    )
    augmented_rank = rank + int(inconsistent)
    if inconsistent:
        return ReconstructionAnalysis(
            unknowns, (), False, rank, augmented_rank, False,
            "inconsistent_relationship_system",
        )
    free_columns = set(range(len(unknowns))) - set(pivots)
    unique = []
    for row_index, pivot_column in enumerate(pivots):
        if all(reduced[row_index][column] == 0 for column in free_columns):
            unique.append(unknowns[pivot_column])
    unique_tuple = tuple(sorted(unique, key=CellIdentity.canonical_key))
    return ReconstructionAnalysis(
        unknowns, unique_tuple, True, rank, rank, not unique_tuple,
        None if not unique_tuple else "protected_coordinate_uniquely_reconstructable",
    )


def _restricted(projection: PrivacyProjection, reason: str) -> PrivacyProjection:
    return PrivacyProjection(projection.identity, RESTRICTED, reason_code=reason)


def _victim_key(identity: CellIdentity, cells: Mapping[CellIdentity, Cell], policy) -> tuple:
    source = cells[identity]
    prefers = getattr(policy, "prefers_coarsening", None)
    preference = bool(prefers(privacy_class=source.privacy_class)) if callable(prefers) else False
    return (
        _CLASS_ORDER.get(source.privacy_class, len(_CLASS_ORDER)),
        -source.depth,
        0 if preference else 1,
        identity.canonical_key(),
    )


def close_privacy_graph(
    graph: PrivacyRelationshipGraph,
    projections: Iterable[PrivacyProjection],
    *,
    source_cells: Optional[Mapping[CellIdentity, Cell]] = None,
    policy=None,
    victim_eligible: Optional[Callable[[CellIdentity], bool]] = None,
    analyzer: Callable[[PrivacyRelationshipComponent, Mapping[CellIdentity, PrivacyProjection]], ReconstructionAnalysis] = analyze_reconstruction,
) -> PrivacyClosureResult:
    """Reach a deterministic monotonic fixed point, local to each component."""

    graph.validate()
    current = {projection.identity: projection for projection in projections}
    if set(current) != set(graph.cells):
        raise PrivacyClosureError("privacy projections must exactly cover graph Cells")
    if source_cells is not None and set(source_cells) != set(graph.cells):
        raise PrivacyClosureError("source Cells must exactly cover graph Cells")
    eligible = victim_eligible or (lambda _identity: True)
    analyses = []
    victims = []
    for component in graph.connected_components():
        initial_candidates = {
            cell for cell in component.cells
            if current[cell].state == VISIBLE and current[cell].value is not None and eligible(cell)
        }
        remaining_transitions = len(initial_candidates)
        while True:
            try:
                analysis = analyzer(component, current)
            except Exception:
                for cell in component.cells:
                    current[cell] = _restricted(current[cell], "reconstruction_analyzer_failed")
                analyses.append(ReconstructionAnalysis((), (), False, 0, 0, False, "reconstruction_analyzer_failed"))
                break
            if not analysis.consistent:
                for cell in component.cells:
                    current[cell] = _restricted(current[cell], analysis.reason_code or "inconsistent_relationship_system")
                analyses.append(analysis)
                break
            if analysis.safe:
                analyses.append(analysis)
                break
            if remaining_transitions <= 0:
                for cell in component.cells:
                    current[cell] = _restricted(current[cell], "privacy_closure_no_progress")
                analyses.append(analysis)
                break
            candidates = []
            for candidate in initial_candidates:
                if current[candidate].state != VISIBLE:
                    continue
                simulated = dict(current)
                simulated[candidate] = PrivacyProjection(candidate, SUPPRESSED, reason_code="complementary_suppression")
                try:
                    after = analyzer(component, simulated)
                except Exception:
                    continue
                # Multi-equation row/column systems can require consecutive
                # suppressions before the exposed set shrinks. Rank and the
                # unique-coordinate count rank structural progress; neither
                # uses disclosed/raw magnitude.
                if after.consistent:
                    candidates.append((len(after.uniquely_reconstructable_keys), after.rank, candidate))
            if not candidates:
                for cell in component.cells:
                    current[cell] = _restricted(current[cell], "privacy_closure_no_safe_victim")
                analyses.append(analysis)
                break
            if source_cells is None:
                victim = min(candidates, key=lambda item: (item[0], item[1], item[2].canonical_key()))[2]
            else:
                victim = min(candidates, key=lambda item: (item[0], item[1], _victim_key(item[2], source_cells, policy)))[2]
            current[victim] = PrivacyProjection(victim, SUPPRESSED, reason_code="complementary_suppression")
            victims.append(victim)
            remaining_transitions -= 1
    ordered = tuple(current[cell] for cell in graph.cells)
    return PrivacyClosureResult(ordered, tuple(analyses), tuple(victims), all(item.safe for item in analyses))


def apply_primary_privacy_and_close(
    graph: PrivacyRelationshipGraph,
    cells: Mapping[CellIdentity, Cell],
    policy,
    **closure_options,
) -> PrivacyClosureResult:
    """Canonical B2 order: primary classification, then graph closure."""

    if policy is None:
        raise PrivacyClosureError("an approved privacy policy is required")
    if set(cells) != set(graph.cells):
        raise PrivacyClosureError("primary privacy Cells must exactly cover graph Cells")
    apply_primary_privacy([cells[identity] for identity in graph.cells], policy)
    projections = tuple(
        PrivacyProjection(identity, cells[identity].state, cells[identity].value, cells[identity].reason_code)
        for identity in graph.cells
    )
    return close_privacy_graph(
        graph, projections, source_cells=cells, policy=policy, **closure_options,
    )


def derive_exact_rate(numerator: PrivacyProjection, denominator: PrivacyProjection) -> DerivedRateProjection:
    """Derive an exact Fraction only from two exact-visible source Cells."""

    if numerator.state == NO_DATA or denominator.state == NO_DATA:
        return DerivedRateProjection(NO_DATA, reason_code="source_no_data")
    if numerator.state != VISIBLE or denominator.state != VISIBLE:
        state = RESTRICTED if RESTRICTED in (numerator.state, denominator.state) else SUPPRESSED
        return DerivedRateProjection(state, reason_code="derived_source_not_exact_visible")
    if denominator.value == 0:
        return DerivedRateProjection(NO_DATA, reason_code="zero_denominator")
    rate = Fraction(numerator.value, denominator.value)
    return DerivedRateProjection(
        VISIBLE, numerator.value, denominator.value, rate, rate * 100,
    )


def project_safe_derived_payload(
    sources: Iterable[PrivacyProjection],
    exact_payload: Mapping[str, object],
) -> dict[str, object]:
    """All-or-nothing projection preventing exact sibling-field leakage."""

    materialized = tuple(sources)
    if not materialized or any(item.state == NO_DATA for item in materialized):
        return {"state": NO_DATA}
    if any(item.state == RESTRICTED for item in materialized):
        return {"state": RESTRICTED}
    if any(item.state != VISIBLE or item.value is None for item in materialized):
        return {"state": SUPPRESSED}
    return {"state": VISIBLE, **dict(exact_payload)}
