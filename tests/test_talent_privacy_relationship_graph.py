"""M10 B1 structural Privacy Relationship Graph behavioral tests.

Provenance: M10 Technical Architecture, Security/Privacy Architecture,
Backend/API Contract, and B0-B2 QA Contract.  These tests cover graph topology
only; they deliberately make no reconstruction or disclosure-safety claim.
"""

import ast
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from talent_org_intelligence_contract import (
    PRIVACY_VECTOR_LEDGER,
    CellIdentity,
    PrivacyProjection,
    Relationship,
    RelationshipTerm,
)
from talent_analytics_relationship_graph import (
    PrivacyRelationshipGraph,
    PrivacyRelationshipGraphError,
    relationship_identity,
)


_COORDINATE_IDS = {
    name: index for index, name in enumerate(
        ("program_branch", "foreign", "a", "b", "unknown", "total", "x", "y", "isolated", "lone", "org", "branch", "grade", "program_total", "branch_total", "participation_overlap"),
        start=1,
    )
}


def cell(coordinate, *, tenant=1, program=None, branch=None, grade=None, overlap=()):
    return CellIdentity(
        school_group_id=tenant,
        academic_year_id=2027,
        metric="frozen_eligible",
        measure_component="count",
        membership_grain="frozen_membership",
        program_id=program,
        branch_id=branch,
        grade_level=grade,
        cycle_id=_COORDINATE_IDS[coordinate],
        overlap_program_ids=overlap,
    )


def relation(*terms, constant=0):
    return Relationship(tuple(RelationshipTerm(item, coefficient) for item, coefficient in terms), constant)


def component_signature(graph):
    return tuple(component.canonical_key() for component in graph.connected_components())


def test_cell_registration_reuses_one_canonical_coordinate_and_allows_isolation():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    original = cell("program_branch", program=10, branch=20)
    equivalent = cell("program_branch", program=10, branch=20)
    assert graph.register_cell(original) is original
    assert graph.register_cell(equivalent) is original
    assert graph.cells == (original,)
    assert graph.connected_components()[0].relationships == ()


def test_cell_registration_rejects_cross_tenant_and_noncanonical_cells():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    with pytest.raises(PrivacyRelationshipGraphError, match="cross-tenant"):
        graph.register_cell(cell("foreign", tenant=2))
    with pytest.raises(PrivacyRelationshipGraphError, match="canonical"):
        graph.register_cell(("not", "a", "CellIdentity"))


@pytest.mark.parametrize("coefficient", [1, -1])
def test_relationship_term_accepts_only_signed_unit_coefficients(coefficient):
    assert RelationshipTerm(cell("a"), coefficient).coefficient == coefficient


@pytest.mark.parametrize("coefficient", [
    True, False, 0, 2, -2, 1.0, -1.0, Fraction(1, 1), Fraction(-1, 1),
    Decimal("1"), Decimal("-1"), None, "1", "-1",
])
def test_relationship_term_rejects_forbidden_coefficients(coefficient):
    with pytest.raises(ValueError, match=r"exactly \+1 or -1"):
        RelationshipTerm(cell("a"), coefficient)


def test_relationship_rejects_duplicate_same_or_opposite_sign_cells():
    a = cell("a")
    for signs in ((1, 1), (1, -1)):
        with pytest.raises(ValueError, match="only once"):
            relation((a, signs[0]), (a, signs[1]))


def test_graph_rejects_unknown_and_cross_tenant_relationship_cells():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    a = graph.register_cell(cell("a"))
    with pytest.raises(PrivacyRelationshipGraphError, match="unknown Cell"):
        graph.add_relationship(relation((a, 1), (cell("unknown"), -1)))
    foreign = cell("foreign", tenant=2)
    with pytest.raises(ValueError, match="cross-tenant"):
        relation((a, 1), (foreign, -1))


def test_relationship_order_global_sign_and_identity_are_canonical():
    a, b, total = cell("a"), cell("b"), cell("total")
    first = relation((a, 1), (b, 1), (total, -1))
    reordered = relation((total, -1), (b, 1), (a, 1))
    sign_flipped = relation((total, 1), (a, -1), (b, -1))
    assert first == reordered == sign_flipped
    assert relationship_identity(first) == relationship_identity(reordered) == relationship_identity(sign_flipped)


def test_same_relationship_registration_is_idempotent_and_adjacency_is_shared():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    a, b, total = (graph.register_cell(cell(name)) for name in ("a", "b", "total"))
    first = relation((a, 1), (b, 1), (total, -1))
    duplicate = relation((total, 1), (b, -1), (a, -1))
    assert graph.add_relationship(first) is first
    assert graph.add_relationship(duplicate) is first
    assert graph.relationships == (first,)
    assert graph.relationships_for(a) == (first,)


def test_v04_simple_and_disconnected_components_are_deterministic():
    cells = [cell(name) for name in ("a", "b", "x", "y", "isolated")]
    relations = [relation((cells[0], 1), (cells[1], -1)), relation((cells[2], 1), (cells[3], -1))]
    graph_a = PrivacyRelationshipGraph.from_contract(school_group_id=1, cells=cells, relationships=relations)
    graph_b = PrivacyRelationshipGraph.from_contract(
        school_group_id=1, cells=reversed(cells), relationships=reversed(relations),
    )
    assert component_signature(graph_a) == component_signature(graph_b)
    assert sorted(len(component.cells) for component in graph_a.connected_components()) == [1, 2, 2]


def test_v04_bridge_merges_only_intended_components():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    a, b, x, y, lone = (graph.register_cell(cell(name)) for name in ("a", "b", "x", "y", "lone"))
    graph.add_relationship(relation((a, 1), (b, -1)))
    graph.add_relationship(relation((x, 1), (y, -1)))
    assert sorted(len(component.cells) for component in graph.connected_components()) == [1, 2, 2]
    graph.add_relationship(relation((b, 1), (x, -1)))
    assert sorted(len(component.cells) for component in graph.connected_components()) == [1, 4]
    assert graph.connected_components()[0 if graph.connected_components()[0].cells == (lone,) else 1].cells == (lone,)


def test_shared_cell_connects_many_relationships_and_nested_topology():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    org = graph.register_cell(cell("org"))
    branch = graph.register_cell(cell("branch", branch=10))
    grade = graph.register_cell(cell("grade", branch=10, grade="1"))
    other_grade = graph.register_cell(cell("grade", branch=10, grade="2"))
    graph.add_relationship(relation((grade, 1), (other_grade, 1), (branch, -1)))
    graph.add_relationship(relation((branch, 1), (org, -1)))
    assert len(graph.relationships_for(branch)) == 2
    assert len(graph.connected_components()) == 1
    assert graph.connected_components()[0].cells == tuple(sorted((org, branch, grade, other_grade), key=CellIdentity.canonical_key))


def test_v20_shared_program_branch_cell_is_one_row_column_coordinate():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    shared_row = graph.register_cell(cell("program_branch", program=10, branch=20))
    shared_column = graph.register_cell(cell("program_branch", branch=20, program=10))
    program_total = graph.register_cell(cell("program_total", program=10))
    branch_total = graph.register_cell(cell("branch_total", branch=20))
    graph.add_relationship(relation((shared_row, 1), (program_total, -1)))
    graph.add_relationship(relation((shared_column, 1), (branch_total, -1)))
    assert shared_row is shared_column
    assert len(graph.cells) == 3
    assert len(graph.relationships_for(shared_row)) == 2
    assert len(graph.connected_components()) == 1


def _matrix_graph(*, transposed):
    graph = PrivacyRelationshipGraph(school_group_id=1)
    coordinates = {
        (program, branch): graph.register_cell(cell("program_branch", program=program, branch=branch))
        for program in (10, 11) for branch in (20, 21)
    }
    program_totals = {program: graph.register_cell(cell("program_total", program=program)) for program in (10, 11)}
    branch_totals = {branch: graph.register_cell(cell("branch_total", branch=branch)) for branch in (20, 21)}
    row_relations = [
        relation(*[((coordinates[(program, branch)], 1)) for branch in (20, 21)], (program_totals[program], -1))
        for program in (10, 11)
    ]
    column_relations = [
        relation(*[((coordinates[(program, branch)], 1)) for program in (10, 11)], (branch_totals[branch], -1))
        for branch in (20, 21)
    ]
    relationships = column_relations + row_relations if transposed else row_relations + column_relations
    for item in relationships:
        graph.add_relationship(item)
    return graph


def test_transposed_program_branch_topology_is_equivalent():
    rows_first = _matrix_graph(transposed=False)
    columns_first = _matrix_graph(transposed=True)
    assert rows_first.cells == columns_first.cells
    assert rows_first.relationships == columns_first.relationships
    assert component_signature(rows_first) == component_signature(columns_first)


def test_v22_overlap_pair_symmetry_reuses_one_coordinate():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    ab = graph.register_cell(cell("participation_overlap", overlap=(10, 20)))
    ba = graph.register_cell(cell("participation_overlap", overlap=(20, 10)))
    assert ab is ba
    assert len(graph.cells) == 1


def test_value_and_no_data_projection_do_not_change_graph_identity_or_topology():
    identity = cell("a")
    visible = PrivacyProjection(identity, "visible", value=0)
    no_data = PrivacyProjection(identity, "no_data")
    graph = PrivacyRelationshipGraph(school_group_id=1)
    assert graph.register_cell(visible.identity) is graph.register_cell(no_data.identity)
    assert len(graph.cells) == 1


def test_v24_graph_validation_fails_closed_on_invalid_adjacency():
    graph = PrivacyRelationshipGraph(school_group_id=1)
    a = graph.register_cell(cell("a"))
    b = graph.register_cell(cell("b"))
    graph.add_relationship(relation((a, 1), (b, -1)))
    graph._adjacency[a].clear()  # deliberate corruption fixture for validator behavior
    with pytest.raises(PrivacyRelationshipGraphError, match="adjacency"):
        graph.validate()
    with pytest.raises(PrivacyRelationshipGraphError, match="adjacency"):
        graph.connected_components()


def test_b1_vector_ledger_updates_are_truthful():
    status = {entry.vector_id: entry.implementation_status for entry in PRIVACY_VECTOR_LEDGER}
    assert set(status) == {f"V{number:02d}" for number in range(1, 26)}
    assert set(status.values()) == {"implemented"}


def test_graph_module_has_no_database_router_or_b2_dependency():
    source = (Path(__file__).resolve().parents[1] / "talent_analytics_relationship_graph.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = set()
    defined_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined_names.add(node.name.lower())
    assert imported_roots <= {"__future__", "collections", "dataclasses", "typing", "talent_org_intelligence_contract"}
    prohibited_behavior_names = {"solve", "rref", "rank", "nullspace", "suppress", "select_victim", "query"}
    assert defined_names.isdisjoint(prohibited_behavior_names)
