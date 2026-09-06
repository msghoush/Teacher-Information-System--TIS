"""M10 B0 Organization Intelligence contract scaffolding.

This module contains structural types only.  It performs no aggregate query,
privacy decision, reconstruction analysis, entitlement check, or routing.
The contracts remain the stable foundation for the B1/B2 graph engine:
canonical Cell identity, +/-1 additive Relationship topology, inherited M9
privacy states, and an explicit V01-V25 implementation ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Optional

from talent_analytics_privacy import COARSENED, NO_DATA, RESTRICTED, SUPPRESSED, VISIBLE


PRIVACY_STATES = (VISIBLE, SUPPRESSED, COARSENED, RESTRICTED, NO_DATA)
RELATIONSHIP_COEFFICIENTS = (-1, 1)
PARTICIPATION_OVERLAP_PRIVACY_CLASS = "P2"


class _SerializedStringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class MetricCode(_SerializedStringEnum):
    PROGRAMS_CONFIGURED = "programs_configured"
    ACTIVE_PROGRAMS = "active_programs"
    FROZEN_ELIGIBLE = "frozen_eligible"
    COMPLETED = "completed"
    COMPLETION_COVERAGE = "completion_coverage"
    ASSESSMENT_STARTED = "assessment_started"
    STARTED_COVERAGE = "started_coverage"
    REQUIRED_PERIOD_EXECUTION = "required_period_execution"
    CANDIDATE_COUNT = "candidate_count"
    CANDIDATE_OF_ELIGIBLE = "candidate_of_eligible"
    IDENTIFIED_COUNT = "identified_count"
    IDENTIFIED_OF_ELIGIBLE = "identified_of_eligible"
    PARTICIPATION_OVERLAP = "participation_overlap"


class MeasureComponent(_SerializedStringEnum):
    COUNT = "count"
    NUMERATOR = "numerator"
    DENOMINATOR = "denominator"


class MembershipGrain(_SerializedStringEnum):
    PROGRAM_CONFIGURATION = "program_configuration"
    FROZEN_MEMBERSHIP = "frozen_membership"
    DISTINCT_STUDENT = "distinct_student"
    PROGRAM_PARTICIPATION = "program_participation"
    REVIEW_CANDIDATE_MEMBERSHIP = "review_candidate_membership"
    IDENTIFICATION_MEMBERSHIP = "identification_membership"
    PERIOD_EXECUTION = "period_execution"


METRIC_IDENTITY_MAPPING = MappingProxyType({
    MetricCode.PROGRAMS_CONFIGURED: ((MeasureComponent.COUNT,), MembershipGrain.PROGRAM_CONFIGURATION),
    MetricCode.ACTIVE_PROGRAMS: ((MeasureComponent.COUNT,), MembershipGrain.PROGRAM_CONFIGURATION),
    MetricCode.FROZEN_ELIGIBLE: ((MeasureComponent.COUNT,), MembershipGrain.FROZEN_MEMBERSHIP),
    MetricCode.COMPLETED: ((MeasureComponent.COUNT,), MembershipGrain.FROZEN_MEMBERSHIP),
    MetricCode.COMPLETION_COVERAGE: ((MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR), MembershipGrain.FROZEN_MEMBERSHIP),
    MetricCode.ASSESSMENT_STARTED: ((MeasureComponent.COUNT,), MembershipGrain.FROZEN_MEMBERSHIP),
    MetricCode.STARTED_COVERAGE: ((MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR), MembershipGrain.FROZEN_MEMBERSHIP),
    MetricCode.REQUIRED_PERIOD_EXECUTION: ((MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR), MembershipGrain.PERIOD_EXECUTION),
    MetricCode.CANDIDATE_COUNT: ((MeasureComponent.COUNT,), MembershipGrain.REVIEW_CANDIDATE_MEMBERSHIP),
    MetricCode.CANDIDATE_OF_ELIGIBLE: ((MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR), MembershipGrain.REVIEW_CANDIDATE_MEMBERSHIP),
    MetricCode.IDENTIFIED_COUNT: ((MeasureComponent.COUNT,), MembershipGrain.IDENTIFICATION_MEMBERSHIP),
    MetricCode.IDENTIFIED_OF_ELIGIBLE: ((MeasureComponent.NUMERATOR, MeasureComponent.DENOMINATOR), MembershipGrain.IDENTIFICATION_MEMBERSHIP),
    MetricCode.PARTICIPATION_OVERLAP: ((MeasureComponent.COUNT,), MembershipGrain.PROGRAM_PARTICIPATION),
})


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _required_id(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _optional_id(value: Optional[int], name: str) -> Optional[int]:
    return None if value is None else _required_id(value, name)


@dataclass(frozen=True)
class CellIdentity:
    """Canonical M10 analytical coordinate, independent of value/presentation.

    Provenance: M10 Technical Architecture, Security/Privacy Architecture,
    Backend/API Contract, and B0-B2 QA Contract (V01).
    """

    school_group_id: int
    academic_year_id: int
    metric: MetricCode
    measure_component: MeasureComponent
    membership_grain: MembershipGrain
    program_id: Optional[int] = None
    branch_id: Optional[int] = None
    grade_level: Optional[str] = None
    section_id: Optional[int] = None
    period_id: Optional[int] = None
    cycle_id: Optional[int] = None
    framework_version_id: Optional[int] = None
    framework_competency_id: Optional[int] = None
    overlap_program_ids: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "school_group_id", _required_id(self.school_group_id, "school_group_id"))
        object.__setattr__(self, "academic_year_id", _required_id(self.academic_year_id, "academic_year_id"))
        try:
            object.__setattr__(self, "metric", MetricCode(self.metric))
        except (TypeError, ValueError) as exc:
            raise ValueError("metric is not an approved M10 metric code") from exc
        try:
            object.__setattr__(self, "measure_component", MeasureComponent(self.measure_component))
        except (TypeError, ValueError) as exc:
            raise ValueError("measure_component is not an approved M10 component") from exc
        try:
            object.__setattr__(self, "membership_grain", MembershipGrain(self.membership_grain))
        except (TypeError, ValueError) as exc:
            raise ValueError("membership_grain is not an approved M10 grain") from exc
        for name in (
            "program_id", "branch_id", "section_id", "period_id", "cycle_id",
            "framework_version_id", "framework_competency_id",
        ):
            object.__setattr__(self, name, _optional_id(getattr(self, name), name))
        if self.grade_level is not None:
            object.__setattr__(self, "grade_level", _required_text(self.grade_level, "grade_level"))
        normalized_program_ids = tuple(sorted({_required_id(value, "overlap_program_id") for value in self.overlap_program_ids}))
        object.__setattr__(self, "overlap_program_ids", normalized_program_ids)

    def canonical_key(self) -> tuple:
        """Total ordering with explicit presence tags for optional dimensions."""

        def optional(value):
            return (value is not None, value if value is not None else "")

        return (
            self.school_group_id, self.academic_year_id, self.metric,
            self.measure_component, self.membership_grain,
            optional(self.program_id), optional(self.branch_id),
            optional(self.grade_level), optional(self.section_id),
            optional(self.period_id), optional(self.cycle_id),
            optional(self.framework_version_id), optional(self.framework_competency_id),
            self.overlap_program_ids,
        )


@dataclass(frozen=True)
class PrivacyProjection:
    """Public privacy result; deliberately has no raw-value field (V15-V18)."""

    identity: CellIdentity
    state: str
    value: Optional[int] = None
    reason_code: Optional[str] = None

    def __post_init__(self):
        if self.state not in PRIVACY_STATES:
            raise ValueError("state must use the inherited M9 privacy-state family")
        if self.state == VISIBLE and self.value is None:
            raise ValueError("visible requires an exact publishable value")
        if self.state == COARSENED and self.value is None:
            raise ValueError("coarsened requires an explicit safe replacement")
        if self.state in (SUPPRESSED, RESTRICTED, NO_DATA) and self.value is not None:
            raise ValueError(f"{self.state} cannot expose an exact value")
        if self.value is not None and (isinstance(self.value, bool) or not isinstance(self.value, int)):
            raise ValueError("projection value must be an integer count")


@dataclass(frozen=True)
class RelationshipTerm:
    """One approved +/-1 term in an additive M10 relationship (V02)."""

    cell: CellIdentity
    coefficient: int

    def __post_init__(self):
        if type(self.coefficient) is not int or self.coefficient not in RELATIONSHIP_COEFFICIENTS:
            raise ValueError("relationship coefficient must be exactly +1 or -1")


@dataclass(frozen=True)
class Relationship:
    """Canonical structural form for sum(coefficient * Cell) = constant.

    This is topology only: there is no parser, evaluator, solver, or formula
    language.  Terms are stable-sorted and equivalent global signs normalize
    to the representation whose first term has coefficient +1 (V03).
    """

    terms: tuple[RelationshipTerm, ...]
    constant: int

    def __post_init__(self):
        if isinstance(self.constant, bool) or not isinstance(self.constant, int):
            raise ValueError("relationship constant must be an integer")
        if not self.terms:
            raise ValueError("relationship requires at least one term")
        ordered = tuple(sorted(self.terms, key=lambda term: term.cell.canonical_key()))
        identities = [term.cell for term in ordered]
        if len(set(identities)) != len(identities):
            raise ValueError("a Cell may occur only once in a relationship")
        tenants = {identity.school_group_id for identity in identities}
        if len(tenants) != 1:
            raise ValueError("cross-tenant relationships are prohibited")
        constant = self.constant
        if ordered[0].coefficient == -1:
            ordered = tuple(RelationshipTerm(term.cell, -term.coefficient) for term in ordered)
            constant = -constant
        object.__setattr__(self, "terms", ordered)
        object.__setattr__(self, "constant", constant)

    def canonical_key(self) -> tuple:
        """Stable ordering for relationship sets, independent of input order."""

        return (
            tuple((term.cell.canonical_key(), term.coefficient) for term in self.terms),
            self.constant,
        )


def require_single_tenant_membership(cells: Iterable[CellIdentity]) -> int:
    """Validate only the tenant boundary of future graph membership (V03)."""

    materialized = tuple(cells)
    if not materialized:
        raise ValueError("graph membership requires at least one Cell")
    tenants = {cell.school_group_id for cell in materialized}
    if len(tenants) != 1:
        raise ValueError("cross-tenant graph membership is prohibited")
    return next(iter(tenants))


@dataclass(frozen=True)
class PrivacyVectorLedgerEntry:
    vector_id: str
    title: str
    owner_milestone: str
    implementation_status: str
    security_property: str


_VECTOR_TITLES = (
    ("V01", "canonical Cell identity"),
    ("V02", "+/-1 RelationshipTerm"),
    ("V03", "invalid, degenerate, and cross-tenant relationship"),
    ("V04", "connected components"),
    ("V05", "exact reconstruction"),
    ("V06", "coordinate uniqueness"),
    ("V07", "redundant equations"),
    ("V08", "inconsistent equations"),
    ("V09", "underdetermined with no unique coordinate"),
    ("V10", "underdetermined with one unique coordinate"),
    ("V11", "primary privacy before closure"),
    ("V12", "monotonic closure"),
    ("V13", "deterministic victim selection"),
    ("V14", "value permutation independence"),
    ("V15", "visible zero"),
    ("V16", "no_data"),
    ("V17", "coarsened replacement"),
    ("V18", "restricted non-exact state"),
    ("V19", "nested Organization to Branch to Grade"),
    ("V20", "shared Program by Branch row and column Cell"),
    ("V21", "transposition independence"),
    ("V22", "overlap symmetry"),
    ("V23", "component localization"),
    ("V24", "fail-closed graph failure"),
    ("V25", "derived-rate and sibling-leak safety"),
)


PRIVACY_VECTOR_LEDGER = tuple(
    PrivacyVectorLedgerEntry(
        vector_id=vector_id,
        title=title,
        owner_milestone=(
            "B0" if vector_id in {"V01", "V02", "V03"}
            else "B1" if vector_id in {"V04", "V20", "V22"}
            else "B2"
        ),
        implementation_status="implemented",
        security_property=(
            "Executable structural contract in B0."
            if vector_id in {"V01", "V02", "V03"}
            else "Executable structural graph contract in B1."
            if vector_id in {"V04", "V20", "V22"}
            else "Executable exact reconstruction and privacy-closure behavior in B2."
        ),
    )
    for vector_id, title in _VECTOR_TITLES
)


def contract_field_names(contract_type) -> frozenset[str]:
    """Stable introspection helper used by the executable forbidden-field guard."""

    return frozenset(field.name for field in fields(contract_type))
