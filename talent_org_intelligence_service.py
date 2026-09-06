"""M10 B3/B4 access context and common organization-query primitives.

Internal only: no router imports this module. Historical dimensions come only
from frozen Cycle population rows. Query functions return raw internal counts
that must pass through ``PrivacyClosedProjectionSet`` before future exposure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Optional

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

import academic_grade
import auth
import models
from talent_analytics_privacy_closure import (
    DerivedRateProjection,
    PrivacyClosureResult,
    derive_exact_rate,
    project_safe_derived_payload,
)
from talent_org_intelligence_contract import CellIdentity, MetricCode, PrivacyProjection


class OrganizationAnalyticsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class OrganizationAnalyticsAvailabilityProvider:
    """Commercial availability adapter; no production mapping is approved."""

    availability_version = "unconfigured"

    def is_available(self, *, school_group_id: int, academic_year_id: int) -> bool:
        raise NotImplementedError


class OrganizationAnalyticsBreadthPolicy:
    """Matrix breadth policy interface with no built-in production ceiling."""

    breadth_policy_version = "unconfigured"

    def allows(self, *, projection_family: str, row_count: int, column_count: int,
               prospective_cells: int, relationship_estimate: int, program_count: int,
               prospective_pair_count: Optional[int] = None) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class OrganizationAnalyticsAccessContext:
    school_group_id: int
    academic_year_id: int
    all_branches: bool
    accessible_historical_branch_ids: tuple[int, ...]
    candidate_projection_allowed: bool
    identification_projection_allowed: bool
    student_drill_allowed: bool
    learner_profile_action_allowed: bool
    commercial_available: bool
    permission_projection_class: str
    availability_version: str

    @property
    def branch_scope(self) -> Optional[set[int]]:
        return None if self.all_branches else set(self.accessible_historical_branch_ids)


@dataclass(frozen=True)
class OrganizationAnalyticsFilters:
    program_ids: tuple[int, ...] = ()
    branch_id: Optional[int] = None
    grade_level: Optional[str] = None
    planning_section_id: Optional[int] = None

    def fingerprint_payload(self) -> dict:
        return {
            key: value for key, value in (
                ("program_ids", list(self.program_ids)),
                ("branch_id", self.branch_id),
                ("grade_level", self.grade_level),
                ("planning_section_id", self.planning_section_id),
            ) if value not in (None, [], ())
        }


@dataclass(frozen=True)
class CoverageCountRow:
    program_id: Optional[int]
    branch_id: Optional[int]
    grade_level: Optional[str]
    status: str
    count: int


@dataclass(frozen=True)
class MembershipCountRow:
    program_id: int
    count: int


@dataclass(frozen=True)
class DimensionMembershipCountRow:
    program_id: int
    branch_id: Optional[int]
    grade_level: Optional[str]
    count: int


@dataclass(frozen=True)
class RequiredExecutionRow:
    program_id: int
    executed: int
    cancelled: int
    outstanding: int


@dataclass(frozen=True)
class ProgramConfigurationCounts:
    configured: int
    active: int


@dataclass(frozen=True)
class ParticipationOverlapRow:
    first_program_id: int
    second_program_id: int
    count: int


class PrivacyClosedProjectionSet:
    """Mandatory B2 seam for future response construction.

    It can only be created from a completed B2 closure result and exposes
    derived output through B2's safe helpers; it carries no raw query rows.
    """

    __slots__ = ("_projections",)

    def __init__(self, closure: PrivacyClosureResult):
        if not isinstance(closure, PrivacyClosureResult):
            raise TypeError("a B2 PrivacyClosureResult is required")
        self._projections = {item.identity: item for item in closure.projections}

    def projection(self, identity: CellIdentity) -> PrivacyProjection:
        return self._projections[identity]

    def derive_rate(self, numerator: CellIdentity, denominator: CellIdentity) -> DerivedRateProjection:
        return derive_exact_rate(self.projection(numerator), self.projection(denominator))

    def derived_payload(self, source_ids: tuple[CellIdentity, ...], payload: Mapping[str, object]) -> dict[str, object]:
        return project_safe_derived_payload((self.projection(item) for item in source_ids), payload)


def _permission(db: Session, user, key: str, school_group_id: int) -> bool:
    return auth.has_permission(db, user, key, school_group_id=school_group_id)


def resolve_access_context(
    db: Session,
    *,
    user,
    academic_year_id: int,
    availability_provider: Optional[OrganizationAnalyticsAvailabilityProvider],
) -> OrganizationAnalyticsAccessContext:
    """Resolve auth -> tenant -> availability -> base permission -> AY -> scope."""

    if user is None or not auth.is_user_active(user):
        raise OrganizationAnalyticsError("authentication_required", "Authentication is required.")
    school_group_id = getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)
    if not school_group_id:
        raise OrganizationAnalyticsError("organization_scope_required", "Select an organization scope.")
    school_group_id = int(school_group_id)
    available = False if availability_provider is None else availability_provider.is_available(
        school_group_id=school_group_id, academic_year_id=academic_year_id,
    )
    if available is not True:
        raise OrganizationAnalyticsError("organization_analytics_unavailable", "Organization analytics is unavailable.")
    if not _permission(db, user, "talent_analytics.view", school_group_id):
        raise OrganizationAnalyticsError("forbidden", "Organization analytics access is denied.")
    year = db.query(models.AcademicYear.id).filter_by(
        id=academic_year_id, school_group_id=school_group_id,
    ).one_or_none()
    if year is None:
        raise OrganizationAnalyticsError("not_found", "Academic Year was not found.")
    all_branches = auth.can_access_all_branches(user)
    branch_ids = () if all_branches else tuple(sorted(
        int(row[0]) for row in auth.get_accessible_branch_query(db, user)
        .with_entities(models.Branch.id).all()
    ))
    capabilities = {
        "candidate": _permission(db, user, "talent_review_candidates.view", school_group_id),
        "identification": _permission(db, user, "talent_official_identifications.view", school_group_id),
        "student_drill": _permission(db, user, "talent_analytics.view_students", school_group_id),
        "learner_profile": _permission(db, user, "talent_learner_profiles.view", school_group_id),
    }
    permission_class = "+".join(("base", *(key for key, allowed in capabilities.items() if allowed)))
    return OrganizationAnalyticsAccessContext(
        school_group_id=school_group_id,
        academic_year_id=academic_year_id,
        all_branches=all_branches,
        accessible_historical_branch_ids=branch_ids,
        candidate_projection_allowed=capabilities["candidate"],
        identification_projection_allowed=capabilities["identification"],
        student_drill_allowed=capabilities["student_drill"],
        learner_profile_action_allowed=capabilities["learner_profile"],
        commercial_available=True,
        permission_projection_class=permission_class,
        availability_version=str(getattr(availability_provider, "availability_version", "unversioned")),
    )


def enforce_breadth(
    policy: Optional[OrganizationAnalyticsBreadthPolicy],
    *,
    projection_family: str,
    row_count: int,
    column_count: int,
    prospective_cells: int,
    relationship_estimate: int,
    program_count: int,
    prospective_pair_count: Optional[int] = None,
) -> str:
    values = (row_count, column_count, prospective_cells, relationship_estimate, program_count)
    if not projection_family or any(type(value) is not int or value < 0 for value in values):
        raise OrganizationAnalyticsError("invalid_breadth_request", "Breadth inputs are invalid.")
    if prospective_pair_count is not None and (type(prospective_pair_count) is not int or prospective_pair_count < 0):
        raise OrganizationAnalyticsError("invalid_breadth_request", "Breadth inputs are invalid.")
    shape = dict(
        projection_family=projection_family, row_count=row_count, column_count=column_count,
        prospective_cells=prospective_cells, relationship_estimate=relationship_estimate,
        program_count=program_count,
    )
    if prospective_pair_count is not None:
        shape["prospective_pair_count"] = prospective_pair_count
    allowed = False if policy is None else policy.allows(**shape)
    if allowed is not True:
        raise OrganizationAnalyticsError("analytics_breadth_unavailable", "The requested analytical breadth is unavailable.")
    return str(getattr(policy, "breadth_policy_version", "unversioned"))


def authorized_program_universe(db: Session, context: OrganizationAnalyticsAccessContext) -> tuple[int, ...]:
    query = db.query(models.TalentProgram.id).join(
        models.TalentProgramAcademicYearConfiguration,
        (models.TalentProgramAcademicYearConfiguration.program_id == models.TalentProgram.id)
        & (models.TalentProgramAcademicYearConfiguration.school_group_id == models.TalentProgram.school_group_id),
    ).filter(
        models.TalentProgram.school_group_id == context.school_group_id,
        models.TalentProgramAcademicYearConfiguration.academic_year_id == context.academic_year_id,
        models.TalentProgramAcademicYearConfiguration.is_enabled == True,
    )
    if not context.all_branches:
        scoped_programs = db.query(models.TalentAssessmentCyclePopulationMember.program_id).join(
            models.TalentAssessmentCycle,
            (models.TalentAssessmentCycle.id == models.TalentAssessmentCyclePopulationMember.cycle_id)
            & (models.TalentAssessmentCycle.school_group_id == models.TalentAssessmentCyclePopulationMember.school_group_id),
        ).filter(
            models.TalentAssessmentCyclePopulationMember.school_group_id == context.school_group_id,
            models.TalentAssessmentCyclePopulationMember.academic_year_id == context.academic_year_id,
            models.TalentAssessmentCyclePopulationMember.branch_id.in_(context.accessible_historical_branch_ids or (-1,)),
            models.TalentAssessmentCycle.status.in_(("open", "closed")),
        ).distinct()
        query = query.filter(models.TalentProgram.id.in_(scoped_programs))
    rows = query.order_by(models.TalentProgram.id).all()
    return tuple(int(row[0]) for row in rows)


def program_configuration_counts(
    db: Session, context: OrganizationAnalyticsAccessContext, *, authorized_program_ids: tuple[int, ...],
) -> ProgramConfigurationCounts:
    """Count the governed AY configuration universe and its active-Program subset."""

    configured, active = db.query(
        func.count(models.TalentProgramAcademicYearConfiguration.id),
        func.sum(case((models.TalentProgram.status == "active", 1), else_=0)),
    ).join(
        models.TalentProgram,
        (models.TalentProgram.id == models.TalentProgramAcademicYearConfiguration.program_id)
        & (models.TalentProgram.school_group_id == models.TalentProgramAcademicYearConfiguration.school_group_id),
    ).filter(
        models.TalentProgramAcademicYearConfiguration.school_group_id == context.school_group_id,
        models.TalentProgramAcademicYearConfiguration.academic_year_id == context.academic_year_id,
        models.TalentProgramAcademicYearConfiguration.is_enabled == True,
        models.TalentProgramAcademicYearConfiguration.program_id.in_(authorized_program_ids or (-1,)),
    ).one()
    return ProgramConfigurationCounts(int(configured or 0), int(active or 0))


def resolve_filters(
    db: Session,
    context: OrganizationAnalyticsAccessContext,
    raw: Mapping[str, object],
    *,
    authorized_program_ids: tuple[int, ...],
) -> OrganizationAnalyticsFilters:
    def optional_int(name):
        value = raw.get(name)
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise OrganizationAnalyticsError("invalid_filter", f"{name} must be an integer.")
        if parsed <= 0:
            raise OrganizationAnalyticsError("invalid_filter", f"{name} must be a positive integer.")
        return parsed

    requested = raw.get("program_ids") or ()
    if isinstance(requested, (str, int)):
        requested = (requested,)
    try:
        program_ids = tuple(sorted({int(value) for value in requested}))
    except (TypeError, ValueError):
        raise OrganizationAnalyticsError("invalid_filter", "Program filter must contain integer IDs.")
    if any(value <= 0 for value in program_ids):
        raise OrganizationAnalyticsError("invalid_filter", "Program filter must contain positive integer IDs.")
    allowed_programs = set(authorized_program_ids)
    if not set(program_ids).issubset(allowed_programs):
        raise OrganizationAnalyticsError("invalid_filter", "Program filter is outside the authorized context.")
    branch_id = optional_int("branch_id")
    tenant_branch_ids = {
        int(row[0]) for row in db.query(models.Branch.id).filter_by(school_group_id=context.school_group_id).all()
    }
    if branch_id is not None and (
        branch_id not in tenant_branch_ids
        or (not context.all_branches and branch_id not in context.accessible_historical_branch_ids)
    ):
        raise OrganizationAnalyticsError("invalid_filter", "Branch filter is outside the authorized context.")
    grade = raw.get("grade_level")
    if grade not in (None, "") and grade not in academic_grade.GRADE_LEVELS:
        raise OrganizationAnalyticsError("invalid_filter", "Grade filter is invalid.")
    return OrganizationAnalyticsFilters(
        program_ids=program_ids,
        branch_id=branch_id,
        grade_level=None if grade in (None, "") else str(grade),
        planning_section_id=optional_int("planning_section_id"),
    )


def compute_request_context_fingerprint(
    context: OrganizationAnalyticsAccessContext,
    *,
    projection_family: str,
    metric: str,
    authorized_program_ids: tuple[int, ...],
    filters: OrganizationAnalyticsFilters,
    privacy_policy_version: str,
    semantic_contract_version: str = "m10-b3-b4-v1",
) -> str:
    try:
        normalized_metric = MetricCode(metric).value
    except (TypeError, ValueError) as exc:
        raise OrganizationAnalyticsError("invalid_filter", "Metric is not an approved M10 metric.") from exc
    payload = {
        "school_group_id": context.school_group_id,
        "academic_year_id": context.academic_year_id,
        "projection_family": projection_family,
        "metric": normalized_metric,
        "program_ids": sorted(set(authorized_program_ids)),
        "branch_scope": "all" if context.all_branches else list(context.accessible_historical_branch_ids),
        "filters": filters.fingerprint_payload(),
        "permission_projection_class": context.permission_projection_class,
        "availability_version": context.availability_version,
        "privacy_policy_version": privacy_policy_version,
        "semantic_contract_version": semantic_contract_version,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def frozen_membership_query(
    db: Session,
    context: OrganizationAnalyticsAccessContext,
    filters: OrganizationAnalyticsFilters,
    *,
    authorized_program_ids: tuple[int, ...],
):
    selected_programs = filters.program_ids or authorized_program_ids
    if not set(selected_programs).issubset(set(authorized_program_ids)):
        raise OrganizationAnalyticsError("invalid_filter", "Program filter is outside the authorized context.")
    query = db.query(models.TalentAssessmentCyclePopulationMember).join(
        models.TalentAssessmentCycle,
        (models.TalentAssessmentCycle.id == models.TalentAssessmentCyclePopulationMember.cycle_id)
        & (models.TalentAssessmentCycle.school_group_id == models.TalentAssessmentCyclePopulationMember.school_group_id),
    ).filter(
        models.TalentAssessmentCyclePopulationMember.school_group_id == context.school_group_id,
        models.TalentAssessmentCyclePopulationMember.academic_year_id == context.academic_year_id,
        models.TalentAssessmentCyclePopulationMember.program_id.in_(selected_programs or (-1,)),
        models.TalentAssessmentCycle.status.in_(("open", "closed")),
    )
    if not context.all_branches:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.branch_id.in_(context.accessible_historical_branch_ids or (-1,)))
    if filters.branch_id is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.branch_id == filters.branch_id)
    if filters.grade_level is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.grade_level == filters.grade_level)
    if filters.planning_section_id is not None:
        query = query.filter(models.TalentAssessmentCyclePopulationMember.planning_section_id == filters.planning_section_id)
    return query


def participation_overlap_counts(db: Session, population_query) -> tuple[ParticipationOverlapRow, ...]:
    """Aggregate canonical Program-pair intersections without materializing Students."""

    participation = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.program_id.label("program_id"),
        models.TalentAssessmentCyclePopulationMember.student_id.label("student_id"),
    ).distinct().subquery()
    first = participation.alias("participation_first")
    second = participation.alias("participation_second")
    rows = db.query(
        first.c.program_id,
        second.c.program_id,
        func.count(func.distinct(first.c.student_id)),
    ).select_from(first).join(
        second,
        (first.c.student_id == second.c.student_id)
        & (first.c.program_id <= second.c.program_id),
    ).group_by(first.c.program_id, second.c.program_id).order_by(
        first.c.program_id, second.c.program_id,
    ).all()
    return tuple(ParticipationOverlapRow(int(a), int(b), int(count)) for a, b, count in rows)


def _coverage_grouped(db: Session, population_query, dimensions: tuple[str, ...]) -> tuple[CoverageCountRow, ...]:
    columns = {
        "program": models.TalentAssessmentCyclePopulationMember.program_id,
        "branch": models.TalentAssessmentCyclePopulationMember.branch_id,
        "grade": models.TalentAssessmentCyclePopulationMember.grade_level,
    }
    selected = [columns[name].label(name) for name in dimensions]
    base = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"), *selected,
    ).subquery()
    grouped = [getattr(base.c, name) for name in dimensions]
    status = func.coalesce(models.TalentStudentAssessment.status, "unassessed").label("status")
    rows = db.query(*grouped, status, func.count(base.c.member_id)).select_from(base).outerjoin(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).group_by(*grouped, status).all()
    result = []
    for row in rows:
        values = dict(zip(dimensions, row[:len(dimensions)]))
        result.append(CoverageCountRow(
            program_id=values.get("program"), branch_id=values.get("branch"),
            grade_level=values.get("grade"), status=row[-2], count=int(row[-1]),
        ))
    return tuple(sorted(result, key=lambda item: (
        item.program_id is None, item.program_id or 0, item.branch_id is None,
        item.branch_id or 0, item.grade_level or "", item.status,
    )))


def coverage_by_program_branch(db: Session, population_query) -> tuple[CoverageCountRow, ...]:
    return _coverage_grouped(db, population_query, ("program", "branch"))


def coverage_by_program_grade(db: Session, population_query) -> tuple[CoverageCountRow, ...]:
    return _coverage_grouped(db, population_query, ("program", "grade"))


def coverage_program_totals(db: Session, population_query) -> tuple[CoverageCountRow, ...]:
    return _coverage_grouped(db, population_query, ("program",))


def coverage_branch_totals(db: Session, population_query) -> tuple[CoverageCountRow, ...]:
    return _coverage_grouped(db, population_query, ("branch",))


def coverage_organization_total(db: Session, population_query) -> tuple[CoverageCountRow, ...]:
    return _coverage_grouped(db, population_query, ())


def candidate_membership_counts(
    db: Session, context: OrganizationAnalyticsAccessContext, population_query,
) -> Optional[tuple[MembershipCountRow, ...]]:
    if not context.candidate_projection_allowed:
        return None
    base = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        models.TalentAssessmentCyclePopulationMember.program_id.label("program_id"),
    ).subquery()
    rows = db.query(base.c.program_id, func.count(models.TalentReviewCandidate.id)).select_from(base).join(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).join(
        models.TalentReviewCandidate,
        models.TalentReviewCandidate.assessment_id == models.TalentStudentAssessment.id,
    ).group_by(base.c.program_id).all()
    return tuple(MembershipCountRow(int(program_id), int(count)) for program_id, count in rows)


def identification_membership_counts(
    db: Session, context: OrganizationAnalyticsAccessContext, population_query,
) -> Optional[tuple[MembershipCountRow, ...]]:
    if not context.identification_projection_allowed:
        return None
    base = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        models.TalentAssessmentCyclePopulationMember.program_id.label("program_id"),
    ).subquery()
    rows = db.query(base.c.program_id, func.count(models.TalentOfficialIdentification.id)).select_from(base).join(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).join(
        models.TalentReviewCandidate,
        models.TalentReviewCandidate.assessment_id == models.TalentStudentAssessment.id,
    ).join(
        models.TalentOfficialIdentification,
        models.TalentOfficialIdentification.review_candidate_id == models.TalentReviewCandidate.id,
    ).filter(
        models.TalentOfficialIdentification.decision == "identified",
    ).group_by(base.c.program_id).all()
    return tuple(MembershipCountRow(int(program_id), int(count)) for program_id, count in rows)


def sensitive_membership_by_dimension(
    db: Session, context: OrganizationAnalyticsAccessContext, population_query,
    *, dimension: str, resource: str,
) -> Optional[tuple[DimensionMembershipCountRow, ...]]:
    """One permission-gated set query for Candidate/identified matrix cells."""
    if dimension not in {"branch", "grade"} or resource not in {"candidate", "identification"}:
        raise OrganizationAnalyticsError("invalid_filter", "Matrix membership query is invalid.")
    if resource == "candidate" and not context.candidate_projection_allowed:
        return None
    if resource == "identification" and not context.identification_projection_allowed:
        return None
    dimension_column = (
        models.TalentAssessmentCyclePopulationMember.branch_id
        if dimension == "branch" else models.TalentAssessmentCyclePopulationMember.grade_level
    )
    base = population_query.with_entities(
        models.TalentAssessmentCyclePopulationMember.id.label("member_id"),
        models.TalentAssessmentCyclePopulationMember.program_id.label("program_id"),
        dimension_column.label("dimension_value"),
    ).subquery()
    query = db.query(base.c.program_id, base.c.dimension_value)
    query = query.select_from(base).join(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == base.c.member_id,
    ).join(
        models.TalentReviewCandidate,
        models.TalentReviewCandidate.assessment_id == models.TalentStudentAssessment.id,
    )
    if resource == "candidate":
        query = query.add_columns(func.count(models.TalentReviewCandidate.id))
    else:
        query = query.join(
            models.TalentOfficialIdentification,
            models.TalentOfficialIdentification.review_candidate_id == models.TalentReviewCandidate.id,
        ).filter(models.TalentOfficialIdentification.decision == "identified").add_columns(
            func.count(models.TalentOfficialIdentification.id)
        )
    rows = query.group_by(base.c.program_id, base.c.dimension_value).all()
    return tuple(DimensionMembershipCountRow(
        int(program_id), int(value) if dimension == "branch" else None,
        str(value) if dimension == "grade" else None, int(count),
    ) for program_id, value, count in rows)


def required_period_execution_counts(
    db: Session, context: OrganizationAnalyticsAccessContext, *, authorized_program_ids: tuple[int, ...],
) -> tuple[RequiredExecutionRow, ...]:
    executed_condition = (
        (models.TalentPlannedEvaluationPeriod.status == "planned")
        & (models.TalentAssessmentCycle.status == "closed")
    )
    cancelled_condition = models.TalentPlannedEvaluationPeriod.status == "cancelled"
    outstanding_condition = (
        (models.TalentPlannedEvaluationPeriod.status == "planned")
        & or_(models.TalentAssessmentCycle.id.is_(None), models.TalentAssessmentCycle.status != "closed")
    )
    rows = db.query(
        models.TalentAnnualEvaluationPlan.program_id,
        func.sum(case((executed_condition, 1), else_=0)),
        func.sum(case((cancelled_condition, 1), else_=0)),
        func.sum(case((outstanding_condition, 1), else_=0)),
    ).join(
        models.TalentPlannedEvaluationPeriod,
        models.TalentPlannedEvaluationPeriod.annual_evaluation_plan_id == models.TalentAnnualEvaluationPlan.id,
    ).outerjoin(
        models.TalentAssessmentCycle,
        (models.TalentAssessmentCycle.planned_evaluation_period_id == models.TalentPlannedEvaluationPeriod.id)
        & (models.TalentAssessmentCycle.school_group_id == context.school_group_id),
    ).filter(
        models.TalentAnnualEvaluationPlan.school_group_id == context.school_group_id,
        models.TalentAnnualEvaluationPlan.academic_year_id == context.academic_year_id,
        models.TalentAnnualEvaluationPlan.program_id.in_(authorized_program_ids or (-1,)),
        models.TalentPlannedEvaluationPeriod.is_required == True,
    ).group_by(models.TalentAnnualEvaluationPlan.program_id).all()
    return tuple(
        RequiredExecutionRow(int(program_id), int(executed or 0), int(cancelled or 0), int(outstanding or 0))
        for program_id, executed, cancelled, outstanding in rows
    )


def resolve_organization_analytics_availability_provider():
    """Production dependency hook; fail closed until commercial mapping is configured."""

    return None


def resolve_organization_analytics_breadth_policy():
    """Production dependency hook; fail closed until breadth policy is configured."""

    return None
