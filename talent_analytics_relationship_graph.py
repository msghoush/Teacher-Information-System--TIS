"""M10 B1 structural privacy relationship graph primitives.

The graph is deliberately topology-only.  It registers canonical B0 Cell
identities and additive Relationships, maintains bipartite adjacency, and
discovers deterministic connected components.  It does not inspect values or
privacy states and contains no reconstruction, rank, suppression, query, ORM,
router, Student, Candidate, or Identification behavior.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from talent_org_intelligence_contract import CellIdentity, Relationship


RelationshipIdentity = tuple


class PrivacyRelationshipGraphError(ValueError):
    """Deterministic fail-closed structural graph validation error."""


def relationship_identity(relationship: Relationship) -> RelationshipIdentity:
    """Value-independent canonical identity for an approved Relationship."""

    return relationship.canonical_key()


@dataclass(frozen=True)
class PrivacyRelationshipComponent:
    """One deterministic Cell <-> Relationship connected component."""

    cells: tuple[CellIdentity, ...]
    relationships: tuple[Relationship, ...]

    def canonical_key(self) -> tuple:
        return (
            tuple(cell.canonical_key() for cell in self.cells),
            tuple(relationship_identity(item) for item in self.relationships),
        )


class PrivacyRelationshipGraph:
    """Tenant-bound registry and bipartite topology for M10 B1."""

    def __init__(self, *, school_group_id: int):
        if isinstance(school_group_id, bool) or not isinstance(school_group_id, int) or school_group_id <= 0:
            raise PrivacyRelationshipGraphError("school_group_id must be a positive integer")
        self.school_group_id = school_group_id
        self._cells: dict[CellIdentity, CellIdentity] = {}
        self._relationships: dict[RelationshipIdentity, Relationship] = {}
        self._adjacency: dict[CellIdentity, set[RelationshipIdentity]] = {}

    @classmethod
    def from_contract(
        cls,
        *,
        school_group_id: int,
        cells: Iterable[CellIdentity],
        relationships: Iterable[Relationship],
    ) -> "PrivacyRelationshipGraph":
        graph = cls(school_group_id=school_group_id)
        for cell in cells:
            graph.register_cell(cell)
        for relationship in relationships:
            graph.add_relationship(relationship)
        graph.validate()
        return graph

    @property
    def cells(self) -> tuple[CellIdentity, ...]:
        return tuple(sorted(self._cells, key=CellIdentity.canonical_key))

    @property
    def relationships(self) -> tuple[Relationship, ...]:
        return tuple(self._relationships[key] for key in sorted(self._relationships))

    def register_cell(self, cell: CellIdentity) -> CellIdentity:
        if not isinstance(cell, CellIdentity):
            raise PrivacyRelationshipGraphError("graph Cells must use canonical CellIdentity")
        if cell.school_group_id != self.school_group_id:
            raise PrivacyRelationshipGraphError("cross-tenant graph registration is prohibited")
        canonical = self._cells.setdefault(cell, cell)
        self._adjacency.setdefault(canonical, set())
        return canonical

    def add_relationship(self, relationship: Relationship) -> Relationship:
        if not isinstance(relationship, Relationship):
            raise PrivacyRelationshipGraphError("graph relationships must use the B0 Relationship contract")
        for term in relationship.terms:
            if term.cell.school_group_id != self.school_group_id:
                raise PrivacyRelationshipGraphError("cross-tenant relationships are prohibited")
            if term.cell not in self._cells:
                raise PrivacyRelationshipGraphError("relationship references an unknown Cell")
        identity = relationship_identity(relationship)
        canonical = self._relationships.setdefault(identity, relationship)
        for term in canonical.terms:
            self._adjacency[term.cell].add(identity)
        return canonical

    def relationships_for(self, cell: CellIdentity) -> tuple[Relationship, ...]:
        if cell not in self._cells:
            raise PrivacyRelationshipGraphError("unknown Cell")
        return tuple(self._relationships[key] for key in sorted(self._adjacency[cell]))

    def validate(self) -> bool:
        """Fail closed if registry, relationship, or adjacency structure drifts."""

        for cell in self._cells:
            if cell.school_group_id != self.school_group_id:
                raise PrivacyRelationshipGraphError("cross-tenant graph membership is prohibited")
            if cell not in self._adjacency:
                raise PrivacyRelationshipGraphError("Cell adjacency is missing")
        expected = {cell: set() for cell in self._cells}
        for identity, relationship in self._relationships.items():
            if identity != relationship_identity(relationship):
                raise PrivacyRelationshipGraphError("relationship identity is not canonical")
            for term in relationship.terms:
                if term.cell not in self._cells:
                    raise PrivacyRelationshipGraphError("relationship references an unknown Cell")
                if term.cell.school_group_id != self.school_group_id:
                    raise PrivacyRelationshipGraphError("cross-tenant relationships are prohibited")
                expected[term.cell].add(identity)
        if expected != self._adjacency:
            raise PrivacyRelationshipGraphError("Cell relationship adjacency is inconsistent")
        return True

    def connected_components(self) -> tuple[PrivacyRelationshipComponent, ...]:
        self.validate()
        unseen_cells = set(self._cells)
        components = []
        while unseen_cells:
            start = min(unseen_cells, key=CellIdentity.canonical_key)
            queued_cells = deque([start])
            component_cells = set()
            component_relationship_ids = set()
            while queued_cells:
                current = queued_cells.popleft()
                if current in component_cells:
                    continue
                component_cells.add(current)
                unseen_cells.discard(current)
                for relation_id in sorted(self._adjacency[current]):
                    if relation_id in component_relationship_ids:
                        continue
                    component_relationship_ids.add(relation_id)
                    for term in self._relationships[relation_id].terms:
                        if term.cell not in component_cells:
                            queued_cells.append(term.cell)
            component = PrivacyRelationshipComponent(
                cells=tuple(sorted(component_cells, key=CellIdentity.canonical_key)),
                relationships=tuple(self._relationships[key] for key in sorted(component_relationship_ids)),
            )
            components.append(component)
        return tuple(sorted(components, key=PrivacyRelationshipComponent.canonical_key))
