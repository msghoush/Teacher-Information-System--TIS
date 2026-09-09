"""Governed Release 1 providers for M10 Organization Analytics.

Production construction is configuration-driven and fail-closed. The only
automatic local path is the dedicated Phase D SQLite database; merely running
with a non-production environment name does not enable analytics elsewhere.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import auth
from talent_analytics_privacy import (
    NO_DATA,
    PRIVACY_CLASSES,
    RESTRICTED,
    SUPPRESSED,
    VISIBLE,
    DeterministicSuppressionTestPolicy,
    PrivacyDecision,
    TalentAnalyticsPrivacyPolicy,
)
from talent_org_intelligence_service import (
    OrganizationAnalyticsAvailabilityProvider,
    OrganizationAnalyticsBreadthPolicy,
)


ORGANIZATION_INTELLIGENCE_FEATURE_KEY = "feature.organization_intelligence"
RELEASE_1_MINIMUM_COHORT = 5
RELEASE_1_MAX_MATRIX_CELLS = 1_000
RELEASE_1_MAX_RELATIONSHIP_RESULTS = 1_000
RELEASE_1_MAX_PROGRAM_PAIR_RESULTS = 1_000

PRIVACY_MINIMUM_ENV = "TIS_ORGANIZATION_ANALYTICS_MINIMUM_COHORT"
MATRIX_LIMIT_ENV = "TIS_ORGANIZATION_ANALYTICS_MAX_MATRIX_CELLS"
RELATIONSHIP_LIMIT_ENV = "TIS_ORGANIZATION_ANALYTICS_MAX_RELATIONSHIP_RESULTS"
PAIR_LIMIT_ENV = "TIS_ORGANIZATION_ANALYTICS_MAX_PROGRAM_PAIR_RESULTS"


def _configured_approved_int(name: str, approved: int) -> int | None:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value == approved else None


def is_sanctioned_local_analytics_environment() -> bool:
    """Return true only for the dedicated local Talent database target."""

    if auth.is_production_environment():
        return False
    raw_url = str(os.getenv("DATABASE_URL", "") or "").strip()
    if not raw_url.startswith("sqlite:///"):
        return False
    raw_path = raw_url[len("sqlite:///"):]
    if not raw_path or raw_path == ":memory:":
        return False
    target = Path(raw_path)
    if not target.is_absolute():
        target = Path(__file__).resolve().parent / target
    sanctioned = Path(__file__).resolve().parent / ".local_test_data" / "talent_local_test.db"
    return target.resolve() == sanctioned.resolve()


class ConfiguredRelease1PrivacyPolicy(TalentAnalyticsPrivacyPolicy):
    """Uniform governed cohort floor while preserving P1-P7 identities."""

    privacy_policy_version = "release1-2026-09"

    def __init__(self, *, minimum_cohort: int):
        if type(minimum_cohort) is not int or minimum_cohort != RELEASE_1_MINIMUM_COHORT:
            raise ValueError("Invalid Organization Analytics privacy configuration.")
        self._minimum_cohort = minimum_cohort

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if privacy_class not in PRIVACY_CLASSES:
            return PrivacyDecision(RESTRICTED, reason_code="privacy_class_unavailable")
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        if type(raw_value) is not int or raw_value < 0:
            return PrivacyDecision(RESTRICTED, reason_code="invalid_analytical_value")
        if raw_value < self._minimum_cohort:
            return PrivacyDecision(SUPPRESSED, reason_code="below_minimum_cohort")
        return PrivacyDecision(VISIBLE, value=raw_value)


class EntitlementOrganizationAnalyticsAvailabilityProvider(OrganizationAnalyticsAvailabilityProvider):
    availability_version = "organization-intelligence-entitlement-v1"

    def __init__(self, db, evaluator: Callable | None = None):
        self._db = db
        self._evaluator = evaluator

    def is_available(self, *, school_group_id: int, academic_year_id: int) -> bool:
        if type(school_group_id) is not int or school_group_id <= 0:
            return False
        if type(academic_year_id) is not int or academic_year_id <= 0:
            return False
        try:
            if self._evaluator is not None:
                return self._evaluator(self._db, school_group_id, ORGANIZATION_INTELLIGENCE_FEATURE_KEY) is True
            from saas.entitlement_service import organization_feature_available
            return organization_feature_available(
                self._db, school_group_id, ORGANIZATION_INTELLIGENCE_FEATURE_KEY,
            ) is True
        except Exception:
            return False


class LocalOrganizationAnalyticsAvailabilityProvider(OrganizationAnalyticsAvailabilityProvider):
    availability_version = "local-canonical-data-v1"

    def is_available(self, *, school_group_id: int, academic_year_id: int) -> bool:
        return (
            not auth.is_production_environment()
            and is_sanctioned_local_analytics_environment()
            and type(school_group_id) is int and school_group_id > 0
            and type(academic_year_id) is int and academic_year_id > 0
        )


class ConfiguredRelease1BreadthPolicy(OrganizationAnalyticsBreadthPolicy):
    breadth_policy_version = "release1-2026-09"

    def __init__(self, *, max_matrix_cells: int, max_relationship_results: int,
                 max_program_pair_results: int):
        values = (max_matrix_cells, max_relationship_results, max_program_pair_results)
        approved = (
            RELEASE_1_MAX_MATRIX_CELLS,
            RELEASE_1_MAX_RELATIONSHIP_RESULTS,
            RELEASE_1_MAX_PROGRAM_PAIR_RESULTS,
        )
        if any(type(value) is not int for value in values) or values != approved:
            raise ValueError("Invalid Organization Analytics breadth configuration.")
        self._max_matrix_cells, self._max_relationship_results, self._max_program_pair_results = values

    def allows(self, *, projection_family: str, row_count: int, column_count: int,
               prospective_cells: int, relationship_estimate: int, program_count: int,
               prospective_pair_count: int | None = None) -> bool:
        values = (row_count, column_count, prospective_cells, relationship_estimate, program_count)
        if not projection_family or any(type(value) is not int or value < 0 for value in values):
            return False
        if prospective_pair_count is not None and (
            type(prospective_pair_count) is not int or prospective_pair_count < 0
        ):
            return False
        return (
            prospective_cells <= self._max_matrix_cells
            and relationship_estimate <= self._max_relationship_results
            and (
                prospective_pair_count is None
                or prospective_pair_count <= self._max_program_pair_results
            )
        )


def build_privacy_provider() -> TalentAnalyticsPrivacyPolicy | None:
    try:
        if is_sanctioned_local_analytics_environment():
            return DeterministicSuppressionTestPolicy(
                minimum_cohort=RELEASE_1_MINIMUM_COHORT,
                version="local-release1-deterministic-v1",
            )
        minimum = _configured_approved_int(PRIVACY_MINIMUM_ENV, RELEASE_1_MINIMUM_COHORT)
        if minimum is None:
            return None
        return ConfiguredRelease1PrivacyPolicy(minimum_cohort=minimum)
    except Exception:
        return None


def build_availability_provider(db) -> OrganizationAnalyticsAvailabilityProvider:
    try:
        if is_sanctioned_local_analytics_environment():
            return LocalOrganizationAnalyticsAvailabilityProvider()
    except Exception:
        pass
    return EntitlementOrganizationAnalyticsAvailabilityProvider(db)


def build_breadth_provider() -> OrganizationAnalyticsBreadthPolicy | None:
    try:
        if is_sanctioned_local_analytics_environment():
            return ConfiguredRelease1BreadthPolicy(
                max_matrix_cells=RELEASE_1_MAX_MATRIX_CELLS,
                max_relationship_results=RELEASE_1_MAX_RELATIONSHIP_RESULTS,
                max_program_pair_results=RELEASE_1_MAX_PROGRAM_PAIR_RESULTS,
            )
        values = (
            _configured_approved_int(MATRIX_LIMIT_ENV, RELEASE_1_MAX_MATRIX_CELLS),
            _configured_approved_int(RELATIONSHIP_LIMIT_ENV, RELEASE_1_MAX_RELATIONSHIP_RESULTS),
            _configured_approved_int(PAIR_LIMIT_ENV, RELEASE_1_MAX_PROGRAM_PAIR_RESULTS),
        )
        if any(value is None for value in values):
            return None
        return ConfiguredRelease1BreadthPolicy(
            max_matrix_cells=values[0],
            max_relationship_results=values[1],
            max_program_pair_results=values[2],
        )
    except Exception:
        return None
