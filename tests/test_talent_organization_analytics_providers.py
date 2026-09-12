"""Focused B11-E F1 provider and sanctioned-local-path checks."""

from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from auth import get_current_user
from dependencies import get_db, get_m10_organization_analytics_db
from routers import talent_organization_analytics, talent_ui
from saas import customer_feature_policy, demo_feature_registry
from talent_analytics_privacy import (
    SUPPRESSED,
    VISIBLE,
    Cell,
    Group,
    apply_primary_privacy,
    run_complementary_suppression,
)
from talent_org_intelligence_service import (
    OrganizationAnalyticsError,
    enforce_breadth,
    resolve_access_context,
)
import talent_organization_analytics_providers as providers
from test_talent_org_intelligence_queries import actor, db, permissions


PROVIDER_ENV_KEYS = (
    providers.PRIVACY_MINIMUM_ENV,
    providers.MATRIX_LIMIT_ENV,
    providers.RELATIONSHIP_LIMIT_ENV,
    providers.PAIR_LIMIT_ENV,
)


def clear_provider_environment(monkeypatch):
    for key in (*PROVIDER_ENV_KEYS, "TIS_ENV", "ENV", "FASTAPI_ENV", "DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)


def configure_production_limits(monkeypatch):
    monkeypatch.setenv(providers.PRIVACY_MINIMUM_ENV, "5")
    monkeypatch.setenv(providers.MATRIX_LIMIT_ENV, "1000")
    monkeypatch.setenv(providers.RELATIONSHIP_LIMIT_ENV, "1000")
    monkeypatch.setenv(providers.PAIR_LIMIT_ENV, "1000")


def sanctioned_database_url():
    target = Path(__file__).resolve().parents[1] / ".local_test_data" / "talent_local_test.db"
    return f"sqlite:///{target.as_posix()}"


def test_release1_privacy_floor_and_complementary_suppression(monkeypatch):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("TIS_ENV", "production")
    configure_production_limits(monkeypatch)
    policy = providers.build_privacy_provider()
    four = Cell(("four",), "P2", 4)
    five = Cell(("five",), "P7", 5)
    apply_primary_privacy((four, five), policy)
    assert (four.state, four.value) == (SUPPRESSED, None)
    assert (five.state, five.value) == (VISIBLE, 5)

    total = Cell(("total",), "P2", 10, depth=0)
    protected = Cell(("protected",), "P2", 4, depth=1)
    sibling = Cell(("sibling",), "P2", 6, depth=1)
    apply_primary_privacy((total, protected, sibling), policy)
    assert run_complementary_suppression(
        (Group("sum", total, [protected, sibling]),), policy
    ) is True
    assert sum(cell.state == SUPPRESSED for cell in (total, protected, sibling)) == 2
    assert all(cell.value is None for cell in (total, protected, sibling) if cell.state == SUPPRESSED)


@pytest.mark.parametrize("value", [None, "", "four", "4", "6", "-5"])
def test_privacy_missing_or_invalid_configuration_fails_closed(monkeypatch, value):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("TIS_ENV", "production")
    if value is not None:
        monkeypatch.setenv(providers.PRIVACY_MINIMUM_ENV, value)
    assert providers.build_privacy_provider() is None


def test_provider_configuration_exception_fails_closed(monkeypatch):
    clear_provider_environment(monkeypatch)
    monkeypatch.setattr(providers, "_configured_approved_int", lambda *_: (_ for _ in ()).throw(RuntimeError("secret")))
    assert providers.build_privacy_provider() is None
    assert providers.build_breadth_provider() is None


def test_feature_key_is_registered_in_customer_and_demo_registries():
    key = providers.ORGANIZATION_INTELLIGENCE_FEATURE_KEY
    assert key in customer_feature_policy.NORMAL_CUSTOMER_FEATURE_KEYS
    assert demo_feature_registry.get_feature(key).enabled is True


def test_production_availability_is_permission_scoped_not_commercially_gated():
    provider = providers.PermissionScopedOrganizationAnalyticsAvailabilityProvider()
    assert provider.is_available(school_group_id=7, academic_year_id=9)
    assert not provider.is_available(school_group_id=0, academic_year_id=9)
    assert not provider.is_available(school_group_id=7, academic_year_id=0)


def test_build_availability_provider_never_returns_entitlement_gate(monkeypatch):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("TIS_ENV", "production")
    provider = providers.build_availability_provider(object())
    assert isinstance(provider, providers.PermissionScopedOrganizationAnalyticsAvailabilityProvider)
    assert provider.is_available(school_group_id=1, academic_year_id=1)


def test_permission_is_enforced_independently_after_availability(db):
    provider = providers.PermissionScopedOrganizationAnalyticsAvailabilityProvider()
    with pytest.raises(OrganizationAnalyticsError) as exc:
        resolve_access_context(
            db, user=actor(), academic_year_id=100, availability_provider=provider,
        )
    assert exc.value.code == "forbidden"


@pytest.mark.parametrize(
    ("field", "accepted", "rejected"),
    (("prospective_cells", 1000, 1001),
     ("relationship_estimate", 1000, 1001),
     ("prospective_pair_count", 1000, 1001)),
)
def test_breadth_accepts_1000_rejects_1001_without_truncation(field, accepted, rejected):
    policy = providers.ConfiguredRelease1BreadthPolicy(
        max_matrix_cells=1000,
        max_relationship_results=1000,
        max_program_pair_results=1000,
    )
    shape = dict(
        projection_family="participation_overlap" if field == "prospective_pair_count" else "program_branch",
        row_count=1, column_count=1, prospective_cells=1,
        relationship_estimate=1, program_count=1,
        prospective_pair_count=1 if field == "prospective_pair_count" else None,
    )
    shape[field] = accepted
    assert enforce_breadth(policy, **shape) == "release1-2026-09"
    shape[field] = rejected
    with pytest.raises(OrganizationAnalyticsError) as exc:
        enforce_breadth(policy, **shape)
    assert exc.value.code == "analytics_breadth_unavailable"
    assert shape[field] == 1001


def test_breadth_missing_and_invalid_configuration_fails_closed(monkeypatch):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("TIS_ENV", "production")
    assert providers.build_breadth_provider() is None
    configure_production_limits(monkeypatch)
    monkeypatch.setenv(providers.PAIR_LIMIT_ENV, "1001")
    assert providers.build_breadth_provider() is None


def test_sanctioned_local_provider_resolution_is_bounded_and_private(monkeypatch):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", sanctioned_database_url())
    assert providers.is_sanctioned_local_analytics_environment()
    privacy = providers.build_privacy_provider()
    breadth = providers.build_breadth_provider()
    availability = providers.build_availability_provider(object())
    assert privacy.evaluate_cell(privacy_class="P2", raw_value=4).state == SUPPRESSED
    assert privacy.evaluate_cell(privacy_class="P2", raw_value=5).state == VISIBLE
    assert availability.is_available(school_group_id=1, academic_year_id=1)
    assert breadth.allows(
        projection_family="program_branch", row_count=1, column_count=1,
        prospective_cells=1000, relationship_estimate=1000, program_count=1,
    )


def test_normal_local_endpoint_and_page_use_canonical_data(monkeypatch, db):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", sanctioned_database_url())
    permissions(db, "talent_analytics.view")
    current = actor(scope="ORGANIZATION")
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(talent_ui.router)
    app.include_router(talent_organization_analytics.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_m10_organization_analytics_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    client = TestClient(app)

    overview = client.get(
        "/api/talent/organization-analytics/overview?academic_year_id=100"
    )
    talent_map = client.get(
        "/api/talent/organization-analytics/talent-map"
        "?academic_year_id=100&dimension=program_branch&metric=frozen_eligible"
    )
    page = client.get("/talent/analytics?academic_year_id=100")
    assert overview.status_code == talent_map.status_code == page.status_code == 200
    assert overview.json()["metrics"]["programs_configured"]["state"] == SUPPRESSED
    assert talent_map.json()["projection_family"] == "program_branch"
    assert "Organization Overview" in page.text


@pytest.mark.parametrize("production_name", ["prod", "production", "live"])
def test_production_like_environment_never_activates_local_providers(monkeypatch, production_name):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", sanctioned_database_url())
    monkeypatch.setenv("TIS_ENV", production_name)
    assert not providers.is_sanctioned_local_analytics_environment()
    assert providers.build_privacy_provider() is None
    assert providers.build_breadth_provider() is None
    availability = providers.build_availability_provider(object())
    assert isinstance(availability, providers.PermissionScopedOrganizationAnalyticsAvailabilityProvider)


def test_other_nonproduction_database_never_activates_sanctioned_local_path(monkeypatch):
    clear_provider_environment(monkeypatch)
    monkeypatch.setenv("TIS_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tis.db")
    assert not providers.is_sanctioned_local_analytics_environment()
    assert providers.build_privacy_provider() is None
    assert providers.build_breadth_provider() is None
