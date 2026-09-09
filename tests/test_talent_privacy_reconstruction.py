"""M10 B2 exact reconstruction and privacy-closure security vectors."""

import ast
from fractions import Fraction
from pathlib import Path

import pytest

from talent_analytics_privacy import (
    COARSENED, NO_DATA, RESTRICTED, SUPPRESSED, VISIBLE,
    Cell, DeterministicSuppressionTestPolicy,
)
from talent_analytics_privacy_closure import (
    PrivacyClosureError,
    analyze_reconstruction,
    apply_primary_privacy_and_close,
    close_privacy_graph,
    derive_exact_rate,
    project_safe_derived_payload,
)
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import (
    PRIVACY_VECTOR_LEDGER, CellIdentity, PrivacyProjection, Relationship, RelationshipTerm,
)


def identity(number, *, branch=None, grade=None, program=10):
    return CellIdentity(
        school_group_id=1, academic_year_id=2027,
        metric="frozen_eligible", measure_component="count",
        membership_grain="frozen_membership", program_id=program,
        branch_id=branch, grade_level=grade, cycle_id=number,
    )


def relationship(*terms, constant=0):
    return Relationship(tuple(RelationshipTerm(cell, coefficient) for cell, coefficient in terms), constant)


def graph(cells, relationships):
    return PrivacyRelationshipGraph.from_contract(
        school_group_id=1, cells=cells, relationships=relationships,
    )


def projection(cell, state, value=None):
    return PrivacyProjection(cell, state, value=value)


def analyze(cells, relationships, projections):
    component = graph(cells, relationships).connected_components()[0]
    return analyze_reconstruction(component, {item.identity: item for item in projections})


def test_v05_protected_child_and_zero_are_exactly_reconstructable():
    total, hidden, sibling = identity(1), identity(2), identity(3)
    relation = relationship((total, 1), (hidden, -1), (sibling, -1))
    for hidden_raw, total_raw in ((4, 10), (0, 6)):
        result = analyze(
            (total, hidden, sibling), (relation,),
            (projection(total, VISIBLE, total_raw), projection(hidden, SUPPRESSED), projection(sibling, VISIBLE, 6)),
        )
        assert result.consistent and result.rank == result.augmented_rank == 1
        assert result.uniquely_reconstructable_keys == (hidden,)
        assert not result.safe


def test_v09_two_unknowns_are_not_individually_unique():
    total, x, y = identity(1), identity(2), identity(3)
    result = analyze(
        (total, x, y), (relationship((total, 1), (x, -1), (y, -1)),),
        (projection(total, VISIBLE, 10), projection(x, SUPPRESSED), projection(y, SUPPRESSED)),
    )
    assert result.rank == 1 and result.protected_unknown_keys == (x, y)
    assert result.uniquely_reconstructable_keys == () and result.safe


def test_v10_one_coordinate_unique_while_system_has_free_variables():
    x, y, z = identity(1), identity(2), identity(3)
    result = analyze(
        (x, y, z),
        (relationship((x, 1), (y, 1), (z, 1), constant=14), relationship((y, 1), (z, 1), constant=10)),
        tuple(projection(item, SUPPRESSED) for item in (x, y, z)),
    )
    assert result.rank == 2
    assert result.uniquely_reconstructable_keys == (x,)


def test_v07_redundant_equations_and_global_sign_are_invariant():
    x, y, z = identity(1), identity(2), identity(3)
    base = relationship((x, 1), (y, 1), (z, 1), constant=14)
    dependent = relationship((x, 1), (y, 1), constant=9)
    projections = tuple(projection(item, SUPPRESSED) for item in (x, y, z))
    first = analyze((x, y, z), (base, dependent), projections)
    second = analyze((x, y, z), (relationship((z, -1), (y, -1), (x, -1), constant=-14), dependent), projections)
    assert first == second


def test_v08_inconsistent_system_fails_closed():
    x, y = identity(1), identity(2)
    relations = (relationship((x, 1), (y, 1), constant=4), relationship((x, 1), (y, 1), constant=5))
    projections = (projection(x, SUPPRESSED), projection(y, SUPPRESSED))
    analysis = analyze((x, y), relations, projections)
    assert not analysis.consistent and analysis.augmented_rank > analysis.rank
    result = close_privacy_graph(graph((x, y), relations), projections)
    assert all(item.state == RESTRICTED for item in result.projections)
    assert not result.safe


def test_v11_primary_privacy_precedes_closure_and_breaks_reconstruction():
    total, small, sibling = identity(1), identity(2), identity(3)
    topology = graph((total, small, sibling), (relationship((total, 1), (small, -1), (sibling, -1)),))
    source = {
        total: Cell(("total",), "P1", 10, depth=0),
        small: Cell(("small",), "P1", 2, depth=1),
        sibling: Cell(("sibling",), "P1", 8, depth=1),
    }
    result = apply_primary_privacy_and_close(topology, source, DeterministicSuppressionTestPolicy(minimum_cohort=5))
    assert result.projection_for(small).state == SUPPRESSED
    assert result.projection_for(sibling).state == SUPPRESSED
    assert result.safe and result.victim_keys == (sibling,)


def test_v11_pipeline_source_orders_primary_privacy_before_closure():
    source = (Path(__file__).resolve().parents[1] / "talent_analytics_privacy_closure.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "apply_primary_privacy_and_close")
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    primary_line = min(node.lineno for node in calls if isinstance(node.func, ast.Name) and node.func.id == "apply_primary_privacy")
    closure_line = min(node.lineno for node in calls if isinstance(node.func, ast.Name) and node.func.id == "close_privacy_graph")
    assert primary_line < closure_line


def test_v12_closure_is_monotonic_idempotent_and_bounded():
    total, hidden, sibling = identity(1), identity(2), identity(3)
    topology = graph((total, hidden, sibling), (relationship((total, 1), (hidden, -1), (sibling, -1)),))
    initial = (projection(total, VISIBLE, 10), projection(hidden, SUPPRESSED), projection(sibling, VISIBLE, 8))
    first = close_privacy_graph(topology, initial)
    second = close_privacy_graph(topology, first.projections)
    assert first.safe and len(first.victim_keys) <= 2
    assert second.projections == first.projections and second.victim_keys == ()
    assert all(not (before.state != VISIBLE and after.state == VISIBLE) for before, after in zip(initial, first.projections))


@pytest.mark.parametrize("reversed_input", (False, True))
def test_v13_v14_victim_is_order_and_value_independent(reversed_input):
    total, hidden, a, b = identity(1), identity(2), identity(3), identity(4)
    relations = [relationship((total, 1), (hidden, -1), (a, -1), (b, -1))]
    cells = [total, hidden, a, b]
    if reversed_input:
        cells.reverse(); relations.reverse()
    topology = graph(cells, relations)
    def execute(values):
        source = {
            total: Cell(("total",), "P1", sum(values), depth=0),
            hidden: Cell(("hidden",), "P1", values[0], depth=2),
            a: Cell(("a",), "P1", values[1], depth=1),
            b: Cell(("b",), "P1", values[2], depth=1),
        }
        return apply_primary_privacy_and_close(topology, source, DeterministicSuppressionTestPolicy(minimum_cohort=5))
    assert execute((2, 10, 20)).victim_keys == execute((2, 20, 10)).victim_keys


def test_v16_no_data_skips_non_authoritative_equation_and_is_not_zero():
    total, hidden, absent = identity(1), identity(2), identity(3)
    result = analyze(
        (total, hidden, absent), (relationship((total, 1), (hidden, -1), (absent, -1)),),
        (projection(total, VISIBLE, 4), projection(hidden, SUPPRESSED), projection(absent, NO_DATA)),
    )
    assert result.rank == 0 and result.safe


@pytest.mark.parametrize("opaque_state", (COARSENED, RESTRICTED))
def test_v17_v18_coarsened_replacement_and_restricted_are_unknown_not_exact(opaque_state):
    total, protected = identity(1), identity(2)
    protected_projection = projection(protected, opaque_state, 999 if opaque_state == COARSENED else None)
    result = analyze(
        (total, protected), (relationship((total, 1), (protected, -1), constant=0),),
        (projection(total, VISIBLE, 4), protected_projection),
    )
    assert result.uniquely_reconstructable_keys == (protected,)


def test_v19_nested_organization_branch_grade_closure():
    org, branch, grade_a, grade_b = identity(1), identity(2, branch=10), identity(3, branch=10, grade="1"), identity(4, branch=10, grade="2")
    topology = graph(
        (org, branch, grade_a, grade_b),
        (relationship((org, 1), (branch, -1)), relationship((branch, 1), (grade_a, -1), (grade_b, -1))),
    )
    initial = (projection(org, VISIBLE, 10), projection(branch, VISIBLE, 10), projection(grade_a, SUPPRESSED), projection(grade_b, VISIBLE, 8))
    result = close_privacy_graph(topology, initial)
    assert result.safe and result.projection_for(grade_b).state != VISIBLE


def _matrix_fixture(transposed=False):
    cells = [identity(index) for index in range(1, 9)]
    a, b, c, d, row1, row2, col1, col2 = cells
    rows = [relationship((row1, 1), (a, -1), (b, -1)), relationship((row2, 1), (c, -1), (d, -1))]
    columns = [relationship((col1, 1), (a, -1), (c, -1)), relationship((col2, 1), (b, -1), (d, -1))]
    return graph(cells, columns + rows if transposed else rows + columns), cells


def test_v20_v21_row_column_attack_and_transposition_have_same_closure():
    graph_a, cells = _matrix_fixture(False)
    graph_b, _ = _matrix_fixture(True)
    values = (1, 2, 3, 4, 3, 7, 4, 6)
    projections = tuple(projection(cell, SUPPRESSED if index == 0 else VISIBLE, None if index == 0 else values[index]) for index, cell in enumerate(cells))
    first = close_privacy_graph(graph_a, projections)
    second = close_privacy_graph(graph_b, reversed(projections))
    assert first.projections == second.projections
    assert first.victim_keys == second.victim_keys and first.safe


def test_v23_analyzer_failure_is_component_local():
    a, b, x, y = (identity(index) for index in range(1, 5))
    topology = graph((a, b, x, y), (relationship((a, 1), (b, -1)), relationship((x, 1), (y, -1))))
    projections = (projection(a, VISIBLE, 1), projection(b, VISIBLE, 1), projection(x, SUPPRESSED), projection(y, VISIBLE, 2))
    def injected(component, current):
        if x in component.cells:
            raise RuntimeError("injected")
        return analyze_reconstruction(component, current)
    result = close_privacy_graph(topology, projections, analyzer=injected)
    assert result.projection_for(a).state == VISIBLE
    assert result.projection_for(b).state == VISIBLE
    assert result.projection_for(x).state == result.projection_for(y).state == RESTRICTED


def test_global_graph_validation_failure_does_not_attempt_best_effort_closure():
    a, b = identity(1), identity(2)
    topology = graph((a, b), (relationship((a, 1), (b, -1)),))
    topology._adjacency[a].clear()
    with pytest.raises(Exception, match="adjacency"):
        close_privacy_graph(topology, (projection(a, VISIBLE, 1), projection(b, SUPPRESSED)))


def test_v25_derived_rate_requires_exact_visible_sources_and_handles_zero():
    numerator, denominator = identity(1), identity(2)
    visible_zero = derive_exact_rate(projection(numerator, VISIBLE, 0), projection(denominator, VISIBLE, 10))
    assert visible_zero.state == VISIBLE and visible_zero.rate == Fraction(0) and visible_zero.percentage == Fraction(0)
    assert derive_exact_rate(projection(numerator, SUPPRESSED), projection(denominator, VISIBLE, 10)).state == SUPPRESSED
    assert derive_exact_rate(projection(numerator, VISIBLE, 2), projection(denominator, RESTRICTED)).state == RESTRICTED
    assert derive_exact_rate(projection(numerator, VISIBLE, 2), projection(denominator, COARSENED, 10)).state == SUPPRESSED
    assert derive_exact_rate(projection(numerator, VISIBLE, 2), projection(denominator, NO_DATA)).state == NO_DATA
    assert derive_exact_rate(projection(numerator, VISIBLE, 0), projection(denominator, VISIBLE, 0)).state == NO_DATA


def test_v25_recursive_sibling_payload_is_all_or_nothing():
    numerator, denominator = identity(1), identity(2)
    secret = {"value": 2, "numerator": 2, "denominator": 10, "percentage": 20, "row_total": 10, "column_total": 10, "metadata": {"count": 2}, "insight": {"parameter": 2}}
    hidden = project_safe_derived_payload((projection(numerator, SUPPRESSED), projection(denominator, VISIBLE, 10)), secret)
    assert hidden == {"state": SUPPRESSED}
    assert not any(key in repr(hidden) for key in ("numerator", "denominator", "percentage", "count", "parameter"))
    visible = project_safe_derived_payload((projection(numerator, VISIBLE, 2), projection(denominator, VISIBLE, 10)), secret)
    assert visible["state"] == VISIBLE and visible["metadata"]["count"] == 2


def test_additional_primary_suppression_never_increases_exact_disclosure():
    total, x, y = identity(1), identity(2), identity(3)
    topology = graph((total, x, y), (relationship((total, 1), (x, -1), (y, -1)),))
    first = close_privacy_graph(topology, (projection(total, VISIBLE, 10), projection(x, SUPPRESSED), projection(y, VISIBLE, 8)))
    second = close_privacy_graph(topology, (projection(total, SUPPRESSED), projection(x, SUPPRESSED), projection(y, VISIBLE, 8)))
    visible_first = {item.identity for item in first.projections if item.state == VISIBLE}
    visible_second = {item.identity for item in second.projections if item.state == VISIBLE}
    assert visible_second <= visible_first


def test_all_b2_vectors_are_executable_and_module_dependency_boundary_is_clean():
    assert all(entry.implementation_status == "implemented" for entry in PRIVACY_VECTOR_LEDGER)
    source = (Path(__file__).resolve().parents[1] / "talent_analytics_privacy_closure.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports <= {
        "__future__", "dataclasses", "fractions", "typing",
        "talent_analytics_privacy", "talent_analytics_relationship_graph",
        "talent_org_intelligence_contract",
    }
    assert all(term not in imports for term in ("fastapi", "sqlalchemy", "models", "routers"))
