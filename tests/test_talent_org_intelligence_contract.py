"""M10 B0 executable Contract / Conformance Harness.

Provenance: approved M10 Technical Architecture, Security/Privacy
Architecture, Backend/API Contract, and B0-B2 QA Contract.  V04-V25 are an
explicit ledger, not silently skipped or falsely claimed as implemented.
"""

from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path

import pytest

from talent_org_intelligence_contract import (
    PRIVACY_STATES,
    PRIVACY_VECTOR_LEDGER,
    CellIdentity,
    METRIC_IDENTITY_MAPPING,
    MeasureComponent,
    MembershipGrain,
    MetricCode,
    PrivacyProjection,
    Relationship,
    RelationshipTerm,
    contract_field_names,
    require_single_tenant_membership,
)


def cell(**changes):
    coordinate = changes.pop("coordinate", None)
    values = {
        "school_group_id": 1,
        "academic_year_id": 2027,
        "metric": "frozen_eligible",
        "measure_component": "count",
        "membership_grain": "frozen_membership",
    }
    if coordinate is not None:
        values["cycle_id"] = coordinate
    values.update(changes)
    return CellIdentity(**values)


def test_v01_canonical_identity_requires_authority_and_all_approved_dimensions():
    identity = cell(
        program_id=10, branch_id=20, grade_level="KG", section_id=30,
        period_id=40, cycle_id=50, framework_version_id=60,
        framework_competency_id=70, overlap_program_ids=(12, 11),
    )
    assert identity.overlap_program_ids == (11, 12)
    assert contract_field_names(CellIdentity) == {
        "school_group_id", "academic_year_id", "metric", "measure_component",
        "membership_grain", "program_id", "branch_id", "grade_level",
        "section_id", "period_id", "cycle_id", "framework_version_id",
        "framework_competency_id", "overlap_program_ids",
    }
    for field_name, invalid in (
        ("school_group_id", None), ("academic_year_id", None),
        ("metric", ""), ("measure_component", " "), ("membership_grain", None),
    ):
        with pytest.raises((TypeError, ValueError)):
            cell(**{field_name: invalid})


def test_v01_identity_is_independent_of_value_privacy_and_presentation():
    identity = cell(overlap_program_ids=(3, 2))
    same_identity = cell(overlap_program_ids=(2, 3))
    assert identity == same_identity
    assert hash(identity) == hash(same_identity)
    forbidden = {
        "raw_value", "value", "privacy_state", "state", "reason_code",
        "coarsened_replacement", "route_name", "matrix_orientation",
        "ui_layout", "ui_x", "ui_y",
    }
    assert contract_field_names(CellIdentity).isdisjoint(forbidden)


def test_closed_metric_vocabulary_accepts_every_approved_serialized_value():
    expected = (
        "programs_configured", "active_programs",
        "frozen_eligible", "completed", "completion_coverage",
        "assessment_started", "started_coverage", "required_period_execution",
        "candidate_count", "candidate_of_eligible", "identified_count",
        "identified_of_eligible",
    )
    assert tuple(item.value for item in MetricCode) == expected
    for metric in expected:
        assert cell(metric=metric).metric.value == metric
    with pytest.raises(ValueError, match="approved M10 metric"):
        cell(metric="potential_rate")


def test_closed_measure_component_vocabulary_excludes_rates_and_unknowns():
    expected = ("count", "numerator", "denominator")
    assert tuple(item.value for item in MeasureComponent) == expected
    for component in expected:
        assert cell(measure_component=component).measure_component.value == component
    for invalid in ("rate", "percentage", "score", ""):
        with pytest.raises(ValueError, match="approved M10 component"):
            cell(measure_component=invalid)


def test_closed_membership_grain_vocabulary_accepts_only_approved_values():
    expected = (
        "program_configuration",
        "frozen_membership", "distinct_student", "program_participation",
        "review_candidate_membership", "identification_membership",
        "period_execution",
    )
    assert tuple(item.value for item in MembershipGrain) == expected
    for grain in expected:
        assert cell(membership_grain=grain).membership_grain.value == grain
    with pytest.raises(ValueError, match="approved M10 grain"):
        cell(membership_grain="student")


def test_approved_initial_metric_mapping_is_exact_and_declarative():
    assert METRIC_IDENTITY_MAPPING == {
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
    }


def test_closed_vocabulary_canonical_key_and_hash_are_stable_for_strings_or_enums():
    from_strings = cell()
    from_enums = cell(
        metric=MetricCode.FROZEN_ELIGIBLE,
        measure_component=MeasureComponent.COUNT,
        membership_grain=MembershipGrain.FROZEN_MEMBERSHIP,
    )
    assert from_strings == from_enums
    assert hash(from_strings) == hash(from_enums)
    assert from_strings.canonical_key() == from_enums.canonical_key()
    assert tuple(str(value) for value in from_strings.canonical_key()[2:5]) == (
        "frozen_eligible", "count", "frozen_membership",
    )
    assert json.loads(json.dumps({
        "metric": from_strings.metric,
        "measure_component": from_strings.measure_component,
        "membership_grain": from_strings.membership_grain,
    })) == {
        "metric": "frozen_eligible",
        "measure_component": "count",
        "membership_grain": "frozen_membership",
    }


@pytest.mark.parametrize("coefficient", [-1, 1])
def test_v02_relationship_term_accepts_only_approved_coefficients(coefficient):
    assert RelationshipTerm(cell(), coefficient).coefficient == coefficient


@pytest.mark.parametrize("coefficient", [
    True, False, 0, 2, -2, 1.0, -1.0, Fraction(1, 1), Fraction(-1, 1),
    Decimal("1"), Decimal("-1"), None, "1", "-1",
])
def test_v02_relationship_term_rejects_arbitrary_coefficients(coefficient):
    with pytest.raises(ValueError, match=r"exactly \+1 or -1"):
        RelationshipTerm(cell(), coefficient)


def test_v03_relationship_is_additive_canonical_and_global_sign_equivalent():
    a = cell(coordinate=1)
    b = cell(coordinate=2)
    left = Relationship((RelationshipTerm(b, -1), RelationshipTerm(a, 1)), 7)
    sign_flipped = Relationship((RelationshipTerm(a, -1), RelationshipTerm(b, 1)), -7)
    assert left == sign_flipped
    assert left.terms == (RelationshipTerm(a, 1), RelationshipTerm(b, -1))


def test_v03_relationship_rejects_degenerate_duplicate_and_cross_tenant_forms():
    with pytest.raises(ValueError, match="at least one"):
        Relationship((), 0)
    with pytest.raises(ValueError, match="only once"):
        Relationship((RelationshipTerm(cell(), 1), RelationshipTerm(cell(), -1)), 0)
    with pytest.raises(ValueError, match="cross-tenant"):
        Relationship((RelationshipTerm(cell(coordinate=1), 1), RelationshipTerm(cell(school_group_id=2, coordinate=2), -1)), 0)
    with pytest.raises(ValueError, match="cross-tenant"):
        require_single_tenant_membership((cell(), cell(school_group_id=2)))


def test_canonicalization_is_order_transposition_and_overlap_symmetric():
    overlap_a = cell(overlap_program_ids=(20, 10), branch_id=2)
    overlap_b = cell(overlap_program_ids=(10, 20), branch_id=2)
    assert overlap_a == overlap_b
    relationship_a = Relationship((RelationshipTerm(overlap_a, 1), RelationshipTerm(cell(coordinate=2), -1)), 0)
    relationship_b = Relationship(tuple(reversed(relationship_a.terms)), 0)
    assert relationship_a == relationship_b
    assert sorted((relationship_b, relationship_a), key=lambda item: item.canonical_key())[0] == relationship_a


def test_privacy_state_family_is_exactly_inherited_from_m9():
    assert PRIVACY_STATES == ("visible", "suppressed", "coarsened", "restricted", "no_data")


def test_semantic_state_distinctions_visible_zero_coarsened_and_restricted():
    identity = cell()
    assert PrivacyProjection(identity, "visible", value=0).value == 0
    assert PrivacyProjection(identity, "no_data").value is None
    assert PrivacyProjection(identity, "coarsened", value=10).value == 10
    assert PrivacyProjection(identity, "restricted").value is None
    with pytest.raises(ValueError):
        PrivacyProjection(identity, "suppressed", value=0)
    with pytest.raises(ValueError):
        PrivacyProjection(identity, "coarsened")
    with pytest.raises(ValueError):
        PrivacyProjection(identity, "visible")
    with pytest.raises(ValueError):
        PrivacyProjection(identity, "invented_state")


def test_forbidden_contract_fields_and_behaviors_are_absent():
    all_fields = set().union(*(
        contract_field_names(CellIdentity), contract_field_names(PrivacyProjection),
        contract_field_names(RelationshipTerm), contract_field_names(Relationship),
    ))
    forbidden = {
        "privacy_threshold", "minimum_cohort", "confidence", "confidence_score",
        "raw_magnitude_priority", "ui_coordinate", "raw_value", "expression",
        "formula", "script", "entitlement_key", "production_limit",
        "talent_score", "potential_rate", "cross_program_normalization",
    }
    assert all_fields.isdisjoint(forbidden)
    assert not hasattr(Relationship, "evaluate")
    assert not hasattr(Relationship, "solve")


@pytest.mark.parametrize("entry", PRIVACY_VECTOR_LEDGER, ids=lambda entry: entry.vector_id)
def test_v01_v25_vector_ledger_is_complete_and_truthful(entry):
    assert entry.vector_id == f"V{int(entry.vector_id[1:]):02d}"
    assert entry.title
    assert entry.owner_milestone in {"B0", "B1", "B2"}
    assert entry.implementation_status in {"implemented", "partially_implemented", "not_implemented"}
    assert entry.security_property
    assert entry.implementation_status == "implemented"


def test_vector_ledger_has_every_slot_once_and_records_completed_b0_b2_kernel():
    assert [entry.vector_id for entry in PRIVACY_VECTOR_LEDGER] == [f"V{number:02d}" for number in range(1, 26)]
    assert {entry.vector_id for entry in PRIVACY_VECTOR_LEDGER if entry.implementation_status == "implemented"} == {
        *(f"V{number:02d}" for number in range(1, 26)),
    }
    assert not {entry.vector_id for entry in PRIVACY_VECTOR_LEDGER if entry.implementation_status != "implemented"}


def test_b0_registers_no_real_m10_organization_aggregate_route():
    repository = Path(__file__).resolve().parents[1]
    assert not (repository / "routers" / "talent_org_intelligence.py").exists()
    registered_source = (repository / "main.py").read_text(encoding="utf-8")
    prohibited_route_tokens = (
        "organization-intelligence", "talent-map", "organization-overview",
        "program-portfolio", "branch-intelligence",
    )
    assert all(token not in registered_source for token in prohibited_route_tokens)
