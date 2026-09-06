"""M10 B5-B8 privacy-closed Organization Intelligence APIs."""

from __future__ import annotations

from fractions import Fraction
from typing import Optional

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
import talent_org_talent_map as talent_map
import talent_org_b7 as b7
import talent_org_participation_overlap as participation_overlap
import talent_org_student_drill as student_drill
import talent_org_longitudinal as longitudinal
import academic_grade
import models


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


@router.get("/talent-map")
def organization_talent_map(
    academic_year_id: int = Query(..., gt=0), dimension: str = Query("program_branch"),
    metric: str = Query(MetricCode.COMPLETION_COVERAGE.value),
    program_ids: Optional[list[int]] = Query(None), branch_id: Optional[int] = Query(None, gt=0),
    grade_level: Optional[str] = Query(None), db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    breadth_policy=Depends(svc.resolve_organization_analytics_breadth_policy),
    policy=Depends(resolve_privacy_policy_provider),
):
    try:
        context = svc.resolve_access_context(db, user=current_user, academic_year_id=academic_year_id, availability_provider=availability_provider)
    except svc.OrganizationAnalyticsError as exc:
        status = 401 if exc.code == "authentication_required" else 404 if exc.code == "not_found" else 403
        return _error(exc.code, exc.message, 503 if exc.code == "organization_analytics_unavailable" else status)
    except Exception:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    canonical_dimension = "branch" if dimension in {"program_branch", "branch_program"} else "grade" if dimension == "program_grade" else None
    if canonical_dimension is None:
        return _error("invalid_filter", "Talent Map dimension is unsupported.", 400)
    try:
        selected_metric = MetricCode(metric)
    except ValueError:
        return _error("invalid_filter", "Talent Map metric is unsupported.", 400)
    if selected_metric not in talent_map.COUNT_METRICS | set(talent_map.RATE_METRICS):
        return _error("invalid_filter", "Talent Map metric is unsupported.", 400)
    candidate_metric = selected_metric in {MetricCode.CANDIDATE_COUNT, MetricCode.CANDIDATE_OF_ELIGIBLE}
    identification_metric = selected_metric in {MetricCode.IDENTIFIED_COUNT, MetricCode.IDENTIFIED_OF_ELIGIBLE}
    if candidate_metric and not context.candidate_projection_allowed or identification_metric and not context.identification_projection_allowed:
        return _error("forbidden", "Talent Map metric access is denied.", 403)
    if policy is None:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    try:
        authorized = svc.authorized_program_universe(db, context)
        filters = svc.resolve_filters(db, context, {"program_ids": program_ids or (), "branch_id": branch_id, "grade_level": grade_level}, authorized_program_ids=authorized)
        selected = filters.program_ids or authorized
        program_rows = db.query(models.TalentProgram.id, models.TalentProgram.name).filter(models.TalentProgram.school_group_id == context.school_group_id, models.TalentProgram.id.in_(selected or (-1,))).order_by(models.TalentProgram.name, models.TalentProgram.id).all()
        programs = tuple({"id": int(row.id), "label": row.name} for row in program_rows)
        selected = tuple(item["id"] for item in programs)
        if canonical_dimension == "branch":
            query = db.query(models.Branch.id, models.Branch.name).filter(models.Branch.school_group_id == context.school_group_id)
            if not context.all_branches:
                query = query.filter(models.Branch.id.in_(context.accessible_historical_branch_ids or (-1,)))
            if filters.branch_id is not None:
                query = query.filter(models.Branch.id == filters.branch_id)
            columns = tuple({"id": int(row.id), "label": row.name} for row in query.order_by(models.Branch.name, models.Branch.id).all())
        else:
            grades = (filters.grade_level,) if filters.grade_level else academic_grade.GRADE_LEVELS
            columns = tuple({"id": grade, "label": grade} for grade in grades)
        multiplier = 2 if selected_metric in talent_map.RATE_METRICS else 1
        breadth_version = svc.enforce_breadth(
            breadth_policy, projection_family=f"program_{canonical_dimension}", row_count=len(programs), column_count=len(columns),
            prospective_cells=len(programs) * len(columns) * multiplier,
            relationship_estimate=(len(programs) + len(columns) + 1) * multiplier, program_count=len(programs),
        )
        population = svc.frozen_membership_query(db, context, filters, authorized_program_ids=authorized)
        coverage = svc.coverage_by_program_branch(db, population) if canonical_dimension == "branch" else svc.coverage_by_program_grade(db, population)
        facts = {}
        for row in coverage:
            value = int(row.branch_id) if canonical_dimension == "branch" else str(row.grade_level)
            fact = facts.setdefault((int(row.program_id), value), {"population": 0, "completed": 0, "started": 0})
            fact["population"] += row.count
            fact["completed"] += row.count if row.status == "completed" else 0
            fact["started"] += row.count if row.status != "unassessed" else 0
        if candidate_metric or identification_metric:
            resource = "candidate" if candidate_metric else "identification"
            for row in svc.sensitive_membership_by_dimension(db, context, population, dimension=canonical_dimension, resource=resource) or ():
                value = row.branch_id if canonical_dimension == "branch" else row.grade_level
                facts.setdefault((row.program_id, value), {"population": 0, "completed": 0, "started": 0})["candidate" if candidate_metric else "identified"] = row.count
        result = talent_map.build_talent_map_closed(context=context, dimension=canonical_dimension, metric=selected_metric, program_ids=selected, column_values=tuple(item["id"] for item in columns), facts=facts, policy=policy)
        fingerprint = svc.compute_request_context_fingerprint(context, projection_family=f"program_{canonical_dimension}", metric=selected_metric.value, authorized_program_ids=selected, filters=filters, privacy_policy_version=str(policy.privacy_policy_version), semantic_contract_version="m10-b6-v1")
        return talent_map.serialize_talent_map(
            result, requested_orientation=dimension, canonical_dimension=canonical_dimension, metric=selected_metric,
            programs=programs, columns=columns, context_payload={
                "academic_year_id": academic_year_id, "authorization_scope": "organization" if context.all_branches else "authorized_branches",
                "privacy_policy_version": str(policy.privacy_policy_version), "breadth_policy_version": breadth_version,
                "request_context_fingerprint": fingerprint,
            },
        )
    except svc.OrganizationAnalyticsError as exc:
        return _error(exc.code, exc.message, 413 if exc.code == "analytics_breadth_unavailable" else 400)
    except Exception:
        return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)


def _b7_response(*, db, context, policy, breadth_policy, program_ids, branch=None):
    raw_filters = {"program_ids": program_ids or ()}
    if branch is not None:
        raw_filters["branch_id"] = branch["id"]
    authorized = svc.authorized_program_universe(db, context)
    filters = svc.resolve_filters(db, context, raw_filters, authorized_program_ids=authorized)
    selected = filters.program_ids or authorized
    program_rows = db.query(models.TalentProgram.id, models.TalentProgram.name, models.TalentProgram.status).filter(
        models.TalentProgram.school_group_id == context.school_group_id,
        models.TalentProgram.id.in_(selected or (-1,)),
    ).order_by(models.TalentProgram.name, models.TalentProgram.id).all()
    programs = tuple({"id": int(row.id), "name": row.name, "status": row.status, "configured": True, "active": row.status == "active"} for row in program_rows)
    selected = tuple(item["id"] for item in programs)
    metrics = list(b7.BRANCH_METRICS if branch else b7.PORTFOLIO_METRICS)
    if context.candidate_projection_allowed: metrics.append(MetricCode.CANDIDATE_COUNT)
    if context.identification_projection_allowed: metrics.append(MetricCode.IDENTIFIED_COUNT)
    multiplier = sum(2 if metric in b7.RATE_SOURCE else 1 for metric in metrics)
    breadth_version = svc.enforce_breadth(
        breadth_policy, projection_family="branch_intelligence" if branch else "program_portfolio",
        row_count=len(programs), column_count=len(metrics), prospective_cells=len(programs) * multiplier,
        relationship_estimate=multiplier, program_count=len(programs),
    )
    population = svc.frozen_membership_query(db, context, filters, authorized_program_ids=authorized)
    coverage = svc.coverage_program_totals(db, population)
    facts = {program_id: {"population": 0, "completed": 0, "started": 0} for program_id in selected}
    for row in coverage:
        fact = facts[int(row.program_id)]; fact["population"] += row.count
        fact["completed"] += row.count if row.status == "completed" else 0
        fact["started"] += row.count if row.status != "unassessed" else 0
    if context.candidate_projection_allowed:
        for row in svc.candidate_membership_counts(db, context, population) or (): facts[row.program_id]["candidate"] = row.count
    if context.identification_projection_allowed:
        for row in svc.identification_membership_counts(db, context, population) or (): facts[row.program_id]["identified"] = row.count
    if branch is None:
        for row in svc.required_period_execution_counts(db, context, authorized_program_ids=selected):
            facts[row.program_id].update(executed=row.executed, execution_denominator=row.executed + row.cancelled + row.outstanding)
    result = b7.build_closed_projection(
        context=context, program_ids=selected, facts=facts, metrics=tuple(metrics), policy=policy,
        branch_id=None if branch is None else branch["id"],
    )
    fingerprint = svc.compute_request_context_fingerprint(
        context, projection_family="branch_intelligence" if branch else "program_portfolio",
        metric=MetricCode.FROZEN_ELIGIBLE.value, authorized_program_ids=selected, filters=filters,
        privacy_policy_version=str(policy.privacy_policy_version), semantic_contract_version="m10-b7-v1",
    )
    return b7.serialize_projection(result, programs=programs, metrics=tuple(metrics), branch=branch, context_payload={
        "academic_year_id": context.academic_year_id,
        "authorization_scope": "organization" if context.all_branches else "authorized_branches",
        "privacy_policy_version": str(policy.privacy_policy_version), "breadth_policy_version": breadth_version,
        "request_context_fingerprint": fingerprint,
    })


def _b7_context(db, current_user, academic_year_id, availability_provider):
    try:
        return svc.resolve_access_context(db, user=current_user, academic_year_id=academic_year_id, availability_provider=availability_provider), None
    except svc.OrganizationAnalyticsError as exc:
        status = 401 if exc.code == "authentication_required" else 404 if exc.code == "not_found" else 403
        return None, _error(exc.code, exc.message, 503 if exc.code == "organization_analytics_unavailable" else status)
    except Exception:
        return None, _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)


@router.get("/program-portfolio")
def organization_program_portfolio(
    academic_year_id: int = Query(..., gt=0), program_ids: Optional[list[int]] = Query(None),
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    breadth_policy=Depends(svc.resolve_organization_analytics_breadth_policy), policy=Depends(resolve_privacy_policy_provider),
):
    context, error = _b7_context(db, current_user, academic_year_id, availability_provider)
    if error: return error
    if policy is None: return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    try: return _b7_response(db=db, context=context, policy=policy, breadth_policy=breadth_policy, program_ids=program_ids, branch=None)
    except svc.OrganizationAnalyticsError as exc: return _error(exc.code, exc.message, 413 if exc.code == "analytics_breadth_unavailable" else 400)
    except Exception: return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)


@router.get("/branches/{branch_id}")
def organization_branch_intelligence(
    branch_id: int, academic_year_id: int = Query(..., gt=0), program_ids: Optional[list[int]] = Query(None),
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    breadth_policy=Depends(svc.resolve_organization_analytics_breadth_policy), policy=Depends(resolve_privacy_policy_provider),
):
    context, error = _b7_context(db, current_user, academic_year_id, availability_provider)
    if error: return error
    branch_row = db.query(models.Branch.id, models.Branch.name).filter_by(id=branch_id, school_group_id=context.school_group_id).one_or_none()
    if branch_row is None or (not context.all_branches and branch_id not in context.accessible_historical_branch_ids):
        return _error("not_found", "Branch was not found.", 404)
    if policy is None: return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    try: return _b7_response(db=db, context=context, policy=policy, breadth_policy=breadth_policy, program_ids=program_ids, branch={"id": int(branch_row.id), "name": branch_row.name})
    except svc.OrganizationAnalyticsError as exc: return _error(exc.code, exc.message, 413 if exc.code == "analytics_breadth_unavailable" else 400)
    except Exception: return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)


@router.get("/participation-overlap")
def organization_participation_overlap(
    academic_year_id: int = Query(..., gt=0), program_ids: Optional[list[int]] = Query(None),
    branch_id: Optional[int] = Query(None, gt=0), db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    breadth_policy=Depends(svc.resolve_organization_analytics_breadth_policy),
    policy=Depends(resolve_privacy_policy_provider),
):
    context, error = _b7_context(db, current_user, academic_year_id, availability_provider)
    if error:
        return error
    if policy is None:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    try:
        authorized = svc.authorized_program_universe(db, context)
        filters = svc.resolve_filters(
            db, context, {"program_ids": program_ids or (), "branch_id": branch_id},
            authorized_program_ids=authorized,
        )
        selected = filters.program_ids or authorized
        program_rows = db.query(models.TalentProgram.id, models.TalentProgram.name).filter(
            models.TalentProgram.school_group_id == context.school_group_id,
            models.TalentProgram.id.in_(selected or (-1,)),
        ).order_by(models.TalentProgram.name, models.TalentProgram.id).all()
        programs = tuple({"id": int(row.id), "name": row.name} for row in program_rows)
        selected = tuple(program["id"] for program in programs)
        pair_count = len(selected) * (len(selected) + 1) // 2
        breadth_version = svc.enforce_breadth(
            breadth_policy, projection_family="participation_overlap",
            row_count=len(selected), column_count=len(selected),
            prospective_cells=len(selected) * len(selected), relationship_estimate=0,
            program_count=len(selected), prospective_pair_count=pair_count,
        )
        population = svc.frozen_membership_query(db, context, filters, authorized_program_ids=authorized)
        overlap_rows = svc.participation_overlap_counts(db, population)
        counts = {(row.first_program_id, row.second_program_id): row.count for row in overlap_rows}
        result = participation_overlap.build_closed_projection(
            context=context, program_ids=selected, overlap_counts=counts, policy=policy,
        )
        fingerprint = svc.compute_request_context_fingerprint(
            context, projection_family="participation_overlap",
            metric=MetricCode.PARTICIPATION_OVERLAP.value, authorized_program_ids=selected,
            filters=filters, privacy_policy_version=str(policy.privacy_policy_version),
            semantic_contract_version="m10-b8-v1",
        )
        return participation_overlap.serialize_projection(result, programs=programs, context_payload={
            "academic_year_id": academic_year_id,
            "authorization_scope": "organization" if context.all_branches else "authorized_branches",
            "branch_id": filters.branch_id,
            "canonical_pair_count": pair_count,
            "presentation_cell_count": len(selected) * len(selected),
            "privacy_policy_version": str(policy.privacy_policy_version),
            "breadth_policy_version": breadth_version,
            "request_context_fingerprint": fingerprint,
        })
    except svc.OrganizationAnalyticsError as exc:
        return _error(exc.code, exc.message, 413 if exc.code == "analytics_breadth_unavailable" else 400)
    except Exception:
        return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)


@router.get("/programs/{program_id}/longitudinal")
def organization_program_longitudinal(
    program_id: int, academic_year_id: int = Query(..., gt=0), metric: str = Query(...),
    branch_id: Optional[int] = Query(None, gt=0), grade_level: Optional[str] = Query(None),
    planning_section_id: Optional[int] = Query(None, gt=0),
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    breadth_policy=Depends(svc.resolve_organization_analytics_breadth_policy),
    policy=Depends(resolve_privacy_policy_provider),
):
    """M10 B10 Longitudinal Organization Intelligence (ADR 0027).

    One Program x one Academic Year, ordered by M8 Period ``sequence``,
    exactly one selected metric, privacy-closed, and with NO server-computed
    delta/change/percent-change field anywhere in the response - see
    ``talent_org_longitudinal`` for the full safety rationale.
    """
    context, error = _b7_context(db, current_user, academic_year_id, availability_provider)
    if error:
        return error
    try:
        selected_metric = MetricCode(metric)
    except ValueError:
        return _error("invalid_filter", "Longitudinal metric is unsupported.", 400)
    if selected_metric not in longitudinal.LONGITUDINAL_METRICS:
        return _error("invalid_filter", "Longitudinal metric is unsupported.", 400)
    if policy is None:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    authorized = svc.authorized_program_universe(db, context)
    if program_id not in authorized:
        return _error("not_found", "Program was not found.", 404)
    try:
        filters = svc.resolve_filters(
            db, context, {
                "program_ids": (program_id,), "branch_id": branch_id,
                "grade_level": grade_level, "planning_section_id": planning_section_id,
            },
            authorized_program_ids=authorized,
        )
        candidate_metric = longitudinal.requires_candidate_permission(selected_metric)
        identification_metric = longitudinal.requires_identification_permission(selected_metric)
        if candidate_metric and not context.candidate_projection_allowed:
            return _error("forbidden", "Longitudinal Candidate metric access is denied.", 403)
        if identification_metric and not context.identification_projection_allowed:
            return _error("forbidden", "Longitudinal Identification metric access is denied.", 403)

        plan = longitudinal.fetch_plan(
            db, school_group_id=context.school_group_id, program_id=program_id, academic_year_id=academic_year_id,
        )
        slots = () if plan is None else longitudinal.fetch_period_slots(
            db, school_group_id=context.school_group_id, program_id=program_id, plan_id=plan.id,
        )
        component_count = 1 if selected_metric in longitudinal.COUNT_METRICS else 2
        period_count = len(slots)
        breadth_version = svc.enforce_breadth(
            breadth_policy, projection_family=longitudinal.PROJECTION_FAMILY,
            row_count=period_count, column_count=component_count,
            prospective_cells=period_count * component_count, relationship_estimate=0,
            program_count=1, prospective_pair_count=max(period_count - 1, 0),
        )
        population = svc.frozen_membership_query(db, context, filters, authorized_program_ids=authorized)
        coverage = longitudinal.coverage_by_cycle(db, population)
        candidate_counts = longitudinal.candidate_counts_by_cycle(db, population) if candidate_metric else None
        identified_counts = longitudinal.identified_counts_by_cycle(db, population) if identification_metric else None
        result = longitudinal.build_closed_projection(
            context=context, program_id=program_id, metric=selected_metric, slots=slots,
            coverage=coverage, candidate_counts=candidate_counts, identified_counts=identified_counts,
            policy=policy,
        )
        program_row = db.query(models.TalentProgram.id, models.TalentProgram.name).filter_by(
            id=program_id, school_group_id=context.school_group_id,
        ).one()
        year_row = db.query(models.AcademicYear.year_name).filter_by(
            id=academic_year_id, school_group_id=context.school_group_id,
        ).one()
        fingerprint = svc.compute_request_context_fingerprint(
            context, projection_family=longitudinal.PROJECTION_FAMILY, metric=selected_metric.value,
            authorized_program_ids=(program_id,), filters=filters,
            privacy_policy_version=str(policy.privacy_policy_version), semantic_contract_version="m10-b10-v1",
        )
        return longitudinal.serialize_projection(
            result, program={"id": program_id, "name": program_row.name},
            academic_year={"id": academic_year_id, "label": year_row.year_name}, plan=plan,
            scope={
                "authorization_scope": "organization" if context.all_branches else "authorized_branches",
                "branch_id": filters.branch_id, "grade_level": filters.grade_level,
                "planning_section_id": filters.planning_section_id,
                "privacy_policy_version": str(policy.privacy_policy_version),
                "breadth_policy_version": breadth_version,
                "request_context_fingerprint": fingerprint,
            },
        )
    except svc.OrganizationAnalyticsError as exc:
        return _error(exc.code, exc.message, 413 if exc.code == "analytics_breadth_unavailable" else 400)
    except Exception:
        return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)


@router.get("/students")
def organization_student_drill(
    academic_year_id: int = Query(..., gt=0), program_ids: Optional[list[int]] = Query(None),
    branch_id: Optional[int] = Query(None, gt=0), grade_level: Optional[str] = Query(None),
    limit: int = Query(25, ge=1), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
    availability_provider=Depends(svc.resolve_organization_analytics_availability_provider),
    breadth_policy=Depends(svc.resolve_organization_analytics_breadth_policy),
    policy=Depends(resolve_privacy_policy_provider),
):
    """M10 B9 identifiable Student Drill.

    Requires BOTH `talent_analytics.view` (enforced inside
    `resolve_access_context`) AND `talent_analytics.view_students` (checked
    explicitly below) - a true AND composition, matching the M9
    `analytics_students` precedent. No identifiable Student fact is queried
    before both permissions and historical Branch/AY scope are established.
    """
    context, error = _b7_context(db, current_user, academic_year_id, availability_provider)
    if error:
        return error
    if not context.student_drill_allowed:
        return _error("forbidden", "Student drill access is denied.", 403)
    if policy is None:
        return _error("organization_analytics_unavailable", "Organization analytics is unavailable.", 503)
    if limit > 100 or offset < 0:
        return _error("invalid_pagination", "limit must be at most 100 and offset must be non-negative.", 400)
    try:
        authorized = svc.authorized_program_universe(db, context)
        filters = svc.resolve_filters(
            db, context, {"program_ids": program_ids or (), "branch_id": branch_id, "grade_level": grade_level},
            authorized_program_ids=authorized,
        )
        selected = filters.program_ids or authorized
        field_count = 6 + sum((
            context.candidate_projection_allowed, context.identification_projection_allowed,
            context.learner_profile_action_allowed,
        ))
        breadth_version = svc.enforce_breadth(
            breadth_policy, projection_family="student_drill", row_count=limit, column_count=field_count,
            prospective_cells=limit * field_count, relationship_estimate=0, program_count=len(selected),
        )
        population = svc.frozen_membership_query(db, context, filters, authorized_program_ids=authorized)
        eligible_count = student_drill.count_distinct_students(population)
        closed_gate, gate_id = student_drill.build_gate_closure(context=context, eligible_count=eligible_count, policy=policy)
        if not student_drill.gate_visible(closed_gate, gate_id):
            return _error("analytics_drill_restricted", "This Student cohort is not available for drill.", 403)
        rows, has_more = student_drill.fetch_student_rows(
            db, population, limit=limit, offset=offset,
            has_candidate=context.candidate_projection_allowed,
            has_identification=context.identification_projection_allowed,
            has_learner_profile=context.learner_profile_action_allowed,
        )
        result = student_drill.StudentDrillClosedProjection(
            closed=closed_gate, gate_identity=gate_id, rows=rows, has_more=has_more,
        )
        fingerprint = svc.compute_request_context_fingerprint(
            context, projection_family="student_drill", metric=MetricCode.STUDENT_DRILL_POPULATION.value,
            authorized_program_ids=selected, filters=filters,
            privacy_policy_version=str(policy.privacy_policy_version), semantic_contract_version="m10-b9-v1",
        )
        return student_drill.serialize_projection(result, context_payload={
            "academic_year_id": academic_year_id,
            "authorization_scope": "organization" if context.all_branches else "authorized_branches",
            "pagination": {"limit": limit, "offset": offset, "has_more": has_more},
            "privacy_policy_version": str(policy.privacy_policy_version),
            "breadth_policy_version": breadth_version,
            "request_context_fingerprint": fingerprint,
        })
    except svc.OrganizationAnalyticsError as exc:
        return _error(exc.code, exc.message, 413 if exc.code == "analytics_breadth_unavailable" else 400)
    except Exception:
        return _error("organization_analytics_failed", "Organization analytics could not be produced.", 500)
