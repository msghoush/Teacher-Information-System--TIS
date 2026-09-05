"""M10 B5 privacy-closed organization Overview API."""

from __future__ import annotations

from fractions import Fraction

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import Cell, COARSENED, VISIBLE, resolve_privacy_policy_provider
from talent_analytics_privacy_closure import PrivacyClosureError, apply_primary_privacy_and_close
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import (
    CellIdentity, MeasureComponent, MembershipGrain, MetricCode, Relationship, RelationshipTerm,
)
import talent_org_intelligence_service as svc


router = APIRouter(prefix="/api/talent/organization-analytics", tags=["Talent Organization Analytics"])


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"detail": message, "code": code}, status_code=status)


def _identity(context, metric, component, grain):
    return CellIdentity(
        school_group_id=context.school_group_id, academic_year_id=context.academic_year_id,
        metric=metric, measure_component=component, membership_grain=grain,
    )


def _count_payload(closed: svc.PrivacyClosedProjectionSet, identity: CellIdentity) -> dict:
    projection = closed.projection(identity)
    payload = {"state": projection.state}
    if projection.state in (VISIBLE, COARSENED):
        payload["value"] = projection.value
    return payload


def _rate_payload(closed: svc.PrivacyClosedProjectionSet, numerator: CellIdentity, denominator: CellIdentity) -> dict:
    derived = closed.derive_rate(numerator, denominator)
    if derived.state != VISIBLE:
        return {"state": derived.state}
    percentage = derived.percentage
    value = int(percentage) if isinstance(percentage, Fraction) and percentage.denominator == 1 else float(percentage)
    return closed.derived_payload((numerator, denominator), {
        "numerator": derived.numerator, "denominator": derived.denominator, "percentage": value,
    })


def _safe_overview_payload(
    closed: svc.PrivacyClosedProjectionSet, *, context, fingerprint: str, privacy_policy_version: str,
    identities: dict[str, CellIdentity], candidate_included: bool, identification_included: bool,
) -> dict:
    """Serialize only the privacy-closed boundary; raw rows/Cells are unaccepted."""
    if not isinstance(closed, svc.PrivacyClosedProjectionSet):
        raise TypeError("PrivacyClosedProjectionSet is required")
    metrics = {
        "programs_configured": _count_payload(closed, identities["programs_configured"]),
        "active_programs": _count_payload(closed, identities["active_programs"]),
        "frozen_eligible_memberships": _count_payload(closed, identities["frozen"]),
        "completion_coverage": _rate_payload(closed, identities["coverage_n"], identities["coverage_d"]),
        "required_period_execution": _rate_payload(closed, identities["period_n"], identities["period_d"]),
    }
    if candidate_included:
        metrics["candidate_membership_count"] = _count_payload(closed, identities["candidate"])
    if identification_included:
        metrics["identified_count"] = _count_payload(closed, identities["identified"])
    return {
        "academic_year_id": context.academic_year_id,
        "scope": "organization" if context.all_branches else "authorized_branches",
        "privacy_policy_version": privacy_policy_version,
        "request_context_fingerprint": fingerprint,
        "metrics": metrics,
    }


@router.get("/overview")
def organization_overview(
    academic_year_id: int = Query(..., gt=0), db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    policy=Depends(resolve_privacy_policy_provider),
):
    try:
        context = svc.resolve_access_context(
            db, user=current_user, academic_year_id=academic_year_id,
            availability_provider=availability_provider,
        )
    except svc.OrganizationAnalyticsError as exc:
        status = 401 if exc.code == "authentication_required" else 404 if exc.code == "not_found" else 403
        if exc.code == "organization_analytics_unavailable":
            status = 503
        return _error(exc.code, exc.message, status)
    except Exception:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    if policy is None:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)

    try:
        programs = svc.authorized_program_universe(db, context)
        filters = svc.OrganizationAnalyticsFilters()
        program_counts = svc.program_configuration_counts(db, context, authorized_program_ids=programs)
        population_query = svc.frozen_membership_query(db, context, filters, authorized_program_ids=programs)
        coverage_rows = svc.coverage_organization_total(db, population_query)
        population_count = sum(row.count for row in coverage_rows)
        completed_count = sum(row.count for row in coverage_rows if row.status == "completed")
        authoritative_population = population_count > 0
        candidate_rows = svc.candidate_membership_counts(db, context, population_query)
        identification_rows = svc.identification_membership_counts(db, context, population_query)
        period_rows = svc.required_period_execution_counts(db, context, authorized_program_ids=programs)
        period_n = sum(row.executed for row in period_rows)
        period_d = sum(row.executed + row.cancelled + row.outstanding for row in period_rows)

        identities = {
            "programs_configured": _identity(context, MetricCode.PROGRAMS_CONFIGURED, MeasureComponent.COUNT, MembershipGrain.PROGRAM_CONFIGURATION),
            "active_programs": _identity(context, MetricCode.ACTIVE_PROGRAMS, MeasureComponent.COUNT, MembershipGrain.PROGRAM_CONFIGURATION),
            "frozen": _identity(context, MetricCode.FROZEN_ELIGIBLE, MeasureComponent.COUNT, MembershipGrain.FROZEN_MEMBERSHIP),
            "completed": _identity(context, MetricCode.COMPLETED, MeasureComponent.COUNT, MembershipGrain.FROZEN_MEMBERSHIP),
            "coverage_n": _identity(context, MetricCode.COMPLETION_COVERAGE, MeasureComponent.NUMERATOR, MembershipGrain.FROZEN_MEMBERSHIP),
            "coverage_d": _identity(context, MetricCode.COMPLETION_COVERAGE, MeasureComponent.DENOMINATOR, MembershipGrain.FROZEN_MEMBERSHIP),
            "period_n": _identity(context, MetricCode.REQUIRED_PERIOD_EXECUTION, MeasureComponent.NUMERATOR, MembershipGrain.PERIOD_EXECUTION),
            "period_d": _identity(context, MetricCode.REQUIRED_PERIOD_EXECUTION, MeasureComponent.DENOMINATOR, MembershipGrain.PERIOD_EXECUTION),
        }
        raw = {
            "programs_configured": program_counts.configured, "active_programs": program_counts.active,
            "frozen": population_count if authoritative_population else None,
            "completed": completed_count if authoritative_population else None,
            "coverage_n": completed_count if authoritative_population else None,
            "coverage_d": population_count if authoritative_population else None,
            "period_n": period_n if period_d else None, "period_d": period_d if period_d else None,
        }
        privacy_classes = {"programs_configured": "P1", "active_programs": "P1", "frozen": "P2", "completed": "P2", "coverage_n": "P2", "coverage_d": "P2", "period_n": "P1", "period_d": "P1"}
        if candidate_rows is not None:
            identities["candidate"] = _identity(context, MetricCode.CANDIDATE_COUNT, MeasureComponent.COUNT, MembershipGrain.REVIEW_CANDIDATE_MEMBERSHIP)
            raw["candidate"] = sum(row.count for row in candidate_rows) if authoritative_population else None
            privacy_classes["candidate"] = "P5"
        if identification_rows is not None:
            identities["identified"] = _identity(context, MetricCode.IDENTIFIED_COUNT, MeasureComponent.COUNT, MembershipGrain.IDENTIFICATION_MEMBERSHIP)
            raw["identified"] = sum(row.count for row in identification_rows) if authoritative_population else None
            privacy_classes["identified"] = "P6"

        cells = {
            identities[name]: Cell(key=identities[name].canonical_key(), privacy_class=privacy_classes[name], raw_value=value, context={"metric": name})
            for name, value in raw.items()
        }
        relationships = (
            Relationship((RelationshipTerm(identities["completed"], 1), RelationshipTerm(identities["coverage_n"], -1)), 0),
            Relationship((RelationshipTerm(identities["frozen"], 1), RelationshipTerm(identities["coverage_d"], -1)), 0),
        )
        graph = PrivacyRelationshipGraph.from_contract(
            school_group_id=context.school_group_id, cells=cells, relationships=relationships,
        )
        closed = svc.PrivacyClosedProjectionSet(apply_primary_privacy_and_close(graph, cells, policy))
        fingerprint = svc.compute_request_context_fingerprint(
            context, projection_family="overview", metric=MetricCode.FROZEN_ELIGIBLE.value,
            authorized_program_ids=programs, filters=filters,
            privacy_policy_version=str(policy.privacy_policy_version), semantic_contract_version="m10-b5-v1",
        )
        return _safe_overview_payload(
            closed, context=context, fingerprint=fingerprint,
            privacy_policy_version=str(policy.privacy_policy_version), identities=identities,
            candidate_included=candidate_rows is not None, identification_included=identification_rows is not None,
        )
    except (svc.OrganizationAnalyticsError, PrivacyClosureError, KeyError, TypeError, ValueError):
        return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)
    except Exception:
        return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)
