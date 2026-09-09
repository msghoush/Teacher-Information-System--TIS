"""M10 B3/B4 authorization, breadth, and set-based query primitives."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from talent_analytics_privacy import SUPPRESSED, VISIBLE
from talent_analytics_privacy_closure import close_privacy_graph
from talent_analytics_relationship_graph import PrivacyRelationshipGraph
from talent_org_intelligence_contract import CellIdentity, PrivacyProjection, Relationship, RelationshipTerm
from talent_org_intelligence_service import (
    OrganizationAnalyticsAvailabilityProvider,
    OrganizationAnalyticsBreadthPolicy,
    OrganizationAnalyticsError,
    PrivacyClosedProjectionSet,
    authorized_program_universe,
    candidate_membership_counts,
    compute_request_context_fingerprint,
    coverage_branch_totals,
    coverage_by_program_branch,
    coverage_by_program_grade,
    coverage_organization_total,
    coverage_program_totals,
    enforce_breadth,
    frozen_membership_query,
    identification_membership_counts,
    program_configuration_counts,
    required_period_execution_counts,
    resolve_access_context,
    resolve_filters,
)


class AllowAvailability(OrganizationAnalyticsAvailabilityProvider):
    availability_version = "test-allow-v1"

    def is_available(self, **_context):
        return True


class AllowBreadth(OrganizationAnalyticsBreadthPolicy):
    breadth_policy_version = "test-breadth-allow-v1"

    def allows(self, **_shape):
        return True


class RejectBreadth(OrganizationAnalyticsBreadthPolicy):
    def allows(self, **_shape):
        return False


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all((models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")))
    session.add_all((
        models.Branch(id=10, school_group_id=1, name="North", status=True),
        models.Branch(id=11, school_group_id=1, name="South", status=True),
        models.Branch(id=20, school_group_id=2, name="Foreign", status=True),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ))
    session.add_all((
        models.TalentProgram(id=1, school_group_id=1, name="Arts", status="active"),
        models.TalentProgram(id=2, school_group_id=1, name="STEM", status="active"),
        models.TalentProgram(id=3, school_group_id=2, name="Foreign", status="active"),
    ))
    session.add_all((
        models.TalentProgramAcademicYearConfiguration(id=1, school_group_id=1, program_id=1, academic_year_id=100, is_enabled=True, eligible_grade_levels_csv="1,2"),
        models.TalentProgramAcademicYearConfiguration(id=2, school_group_id=1, program_id=2, academic_year_id=100, is_enabled=True, eligible_grade_levels_csv="1,2"),
        models.TalentProgramAcademicYearConfiguration(id=3, school_group_id=2, program_id=3, academic_year_id=200, is_enabled=True, eligible_grade_levels_csv="1"),
    ))
    session.add_all((
        models.TalentProgramFrameworkVersion(id=101, school_group_id=1, program_id=1, version_number=1, status="active", title="Arts", revision=1, semantic_fingerprint="a" * 64),
        models.TalentProgramFrameworkVersion(id=102, school_group_id=1, program_id=2, version_number=1, status="active", title="STEM", revision=1, semantic_fingerprint="b" * 64),
        models.TalentProgramFrameworkVersion(id=103, school_group_id=2, program_id=3, version_number=1, status="active", title="Foreign", revision=1, semantic_fingerprint="c" * 64),
    ))
    session.add_all((
        models.TalentAnnualEvaluationPlan(id=501, school_group_id=1, program_id=1, academic_year_id=100, program_academic_year_configuration_id=1, status="active", revision=1, activated_at=datetime(2026, 9, 1)),
        models.TalentAnnualEvaluationPlan(id=502, school_group_id=1, program_id=2, academic_year_id=100, program_academic_year_configuration_id=2, status="active", revision=1, activated_at=datetime(2026, 9, 1)),
    ))
    session.add_all((
        models.TalentPlannedEvaluationPeriod(id=601, school_group_id=1, program_id=1, academic_year_id=100, annual_evaluation_plan_id=501, sequence=1, label="Executed", normalized_label="executed", is_required=True, status="planned"),
        models.TalentPlannedEvaluationPeriod(id=602, school_group_id=1, program_id=1, academic_year_id=100, annual_evaluation_plan_id=501, sequence=2, label="Cancelled", normalized_label="cancelled", is_required=True, status="cancelled", cancellation_reason="Test", cancelled_at=datetime(2027, 1, 1)),
        models.TalentPlannedEvaluationPeriod(id=603, school_group_id=1, program_id=1, academic_year_id=100, annual_evaluation_plan_id=501, sequence=3, label="Outstanding", normalized_label="outstanding", is_required=True, status="planned"),
        models.TalentPlannedEvaluationPeriod(id=604, school_group_id=1, program_id=2, academic_year_id=100, annual_evaluation_plan_id=502, sequence=1, label="Optional", normalized_label="optional", is_required=False, status="planned"),
    ))
    session.add_all((
        models.TalentAssessmentCycle(id=201, school_group_id=1, program_id=1, academic_year_id=100, framework_version_id=101, planned_evaluation_period_id=601, title="Arts Cycle", status="closed", revision=1, population_effective_at=datetime(2026, 10, 1)),
        models.TalentAssessmentCycle(id=202, school_group_id=1, program_id=2, academic_year_id=100, framework_version_id=102, title="STEM Cycle", status="open", revision=1, population_effective_at=datetime(2026, 10, 1)),
        models.TalentAssessmentCycle(id=203, school_group_id=2, program_id=3, academic_year_id=200, framework_version_id=103, title="Foreign", status="open", revision=1, population_effective_at=datetime(2026, 10, 1)),
    ))
    populations = (
        (1, 201, 1, 101, 1001, 10, "1"),
        (2, 201, 1, 101, 1002, 11, "2"),
        (3, 202, 2, 102, 1003, 10, "2"),
        (4, 203, 3, 103, 2001, 20, "1"),
    )
    for member_id, cycle_id, program_id, framework_id, student_id, branch_id, grade in populations:
        session.add(models.TalentAssessmentCyclePopulationMember(
            id=member_id, school_group_id=1 if member_id < 4 else 2,
            cycle_id=cycle_id, program_id=program_id,
            academic_year_id=100 if member_id < 4 else 200,
            framework_version_id=framework_id, student_id=student_id,
            academic_placement_id=member_id, branch_id=branch_id,
            grade_level=grade, section_name="Frozen", population_effective_at=datetime(2026, 10, 1),
        ))
    session.add(models.StudentAcademicPlacement(
        id=1, school_group_id=1, student_id=1001, academic_year_id=100,
        branch_id=10, grade_level="1", section_name="Original",
        effective_from=datetime(2026, 9, 1), status="active",
    ))
    session.add_all((
        models.TalentStudentAssessment(id=701, school_group_id=1, cycle_id=201, cycle_population_member_id=1, student_id=1001, program_id=1, academic_year_id=100, framework_version_id=101, status="completed"),
        models.TalentStudentAssessment(id=702, school_group_id=1, cycle_id=201, cycle_population_member_id=2, student_id=1002, program_id=1, academic_year_id=100, framework_version_id=101, status="in_progress"),
    ))
    session.add(models.TalentReviewCandidate(
        id=801, school_group_id=1, cycle_id=201, cycle_population_member_id=1,
        student_id=1001, program_id=1, academic_year_id=100, framework_version_id=101,
        assessment_id=701, policy_id=1, match_mode="all", evaluation_fingerprint="d" * 64,
        evaluation_snapshot_json="{}", status="reviewed",
    ))
    session.add(models.TalentOfficialIdentification(
        id=901, school_group_id=1, cycle_id=201, cycle_population_member_id=1,
        student_id=1001, program_id=1, academic_year_id=100, framework_version_id=101,
        assessment_id=701, review_candidate_id=801, decision="identified",
    ))
    session.commit()
    yield session
    session.close()


def actor(*, scope="ORGANIZATION", branch=10, role="Editor", group=1):
    return models.User(
        user_id=f"u{group}{branch}", username=f"u{group}{branch}", role=role,
        user_type="TENANT", access_scope=scope, school_group_id=group,
        branch_id=branch, academic_year_id=100 if group == 1 else 200, is_active=True,
    )


def permissions(db, *keys, allow=True):
    db.add_all(models.RolePermission(school_group_id=1, role="Editor", permission_key=key, is_allowed=allow) for key in keys)
    db.commit()


def context(db, current, *extra_permissions):
    permissions(db, "talent_analytics.view", *extra_permissions)
    return resolve_access_context(db, user=current, academic_year_id=100, availability_provider=AllowAvailability())


def test_program_configuration_counts_use_enabled_config_and_exact_program_active_lifecycle(db):
    ctx = context(db, actor(scope="ORGANIZATION"))
    ids = authorized_program_universe(db, ctx)
    initial = program_configuration_counts(db, ctx, authorized_program_ids=ids)
    assert (initial.configured, initial.active) == (2, 2)
    db.query(models.TalentProgram).filter_by(id=2).update({"status": "retired"})
    db.commit()
    counts = program_configuration_counts(db, ctx, authorized_program_ids=ids)
    assert counts.configured == 2
    assert counts.active == 1


def test_access_context_requires_auth_availability_permission_and_tenant_year(db):
    with pytest.raises(OrganizationAnalyticsError, match="Authentication"):
        resolve_access_context(db, user=None, academic_year_id=100, availability_provider=AllowAvailability())
    with pytest.raises(OrganizationAnalyticsError) as unavailable:
        resolve_access_context(db, user=actor(), academic_year_id=100, availability_provider=None)
    assert unavailable.value.code == "organization_analytics_unavailable"
    with pytest.raises(OrganizationAnalyticsError) as forbidden:
        resolve_access_context(db, user=actor(), academic_year_id=100, availability_provider=AllowAvailability())
    assert forbidden.value.code == "forbidden"
    permissions(db, "talent_analytics.view")
    with pytest.raises(OrganizationAnalyticsError) as foreign_year:
        resolve_access_context(db, user=actor(), academic_year_id=200, availability_provider=AllowAvailability())
    assert foreign_year.value.code == "not_found"


def test_branch_and_secondary_permission_context_is_composed_without_role_logic(db):
    ctx = context(db, actor(scope="BRANCH"), "talent_review_candidates.view")
    assert not ctx.all_branches and ctx.accessible_historical_branch_ids == (10,)
    assert ctx.candidate_projection_allowed
    assert not ctx.identification_projection_allowed
    assert not ctx.student_drill_allowed
    assert not ctx.learner_profile_action_allowed
    assert ctx.permission_projection_class == "base+candidate"
    all_ctx = context(db, actor(scope="ORGANIZATION"))
    assert all_ctx.all_branches and all_ctx.accessible_historical_branch_ids == ()


def test_availability_and_breadth_are_injected_fail_closed_boundaries():
    with pytest.raises(OrganizationAnalyticsError) as missing:
        enforce_breadth(None, projection_family="matrix", row_count=2, column_count=2, prospective_cells=4, relationship_estimate=4, program_count=1)
    assert missing.value.code == "analytics_breadth_unavailable"
    assert enforce_breadth(AllowBreadth(), projection_family="matrix", row_count=2, column_count=2, prospective_cells=4, relationship_estimate=4, program_count=1) == "test-breadth-allow-v1"
    with pytest.raises(OrganizationAnalyticsError):
        enforce_breadth(RejectBreadth(), projection_family="matrix", row_count=2, column_count=2, prospective_cells=4, relationship_estimate=4, program_count=1)


def test_authorized_programs_and_filters_are_tenant_and_branch_safe(db):
    branch_ctx = context(db, actor(scope="BRANCH"))
    assert authorized_program_universe(db, branch_ctx) == (1, 2)
    org_ctx = context(db, actor(scope="ORGANIZATION"))
    programs = authorized_program_universe(db, org_ctx)
    assert programs == (1, 2) and 3 not in programs
    with pytest.raises(OrganizationAnalyticsError):
        resolve_filters(db, branch_ctx, {"branch_id": 11}, authorized_program_ids=(1, 2))
    with pytest.raises(OrganizationAnalyticsError):
        resolve_filters(db, org_ctx, {"branch_id": 20}, authorized_program_ids=(1, 2))
    with pytest.raises(OrganizationAnalyticsError):
        resolve_filters(db, org_ctx, {"program_ids": [3]}, authorized_program_ids=(1, 2))


def test_frozen_scope_and_set_based_program_branch_grade_totals(db):
    ctx = context(db, actor(scope="BRANCH"))
    programs = authorized_program_universe(db, ctx)
    filters = resolve_filters(db, ctx, {}, authorized_program_ids=programs)
    population = frozen_membership_query(db, ctx, filters, authorized_program_ids=programs)
    assert {row.id for row in population.all()} == {1, 3}
    assert {(row.program_id, row.branch_id, row.status, row.count) for row in coverage_by_program_branch(db, population)} == {
        (1, 10, "completed", 1), (2, 10, "unassessed", 1),
    }
    assert {(row.program_id, row.grade_level, row.count) for row in coverage_by_program_grade(db, population)} == {
        (1, "1", 1), (2, "2", 1),
    }
    assert sum(row.count for row in coverage_program_totals(db, population)) == 2
    assert sum(row.count for row in coverage_branch_totals(db, population)) == 2
    assert sum(row.count for row in coverage_organization_total(db, population)) == 2

    placement = db.get(models.StudentAcademicPlacement, 1)
    placement.branch_id = 11
    placement.grade_level = "12"
    placement.section_name = "Transferred"
    db.flush()
    repeated = frozen_membership_query(db, ctx, filters, authorized_program_ids=programs)
    assert {(row.program_id, row.branch_id, row.grade_level) for row in repeated.all()} == {
        (1, 10, "1"), (2, 10, "2"),
    }
    assert "StudentAcademicPlacement" not in frozen_membership_query.__code__.co_names
    member = db.get(models.TalentAssessmentCyclePopulationMember, 1)
    assert (member.branch_id, member.grade_level) == (10, "1")


def test_sensitive_queries_are_not_executed_without_independent_permissions(db):
    ctx = context(db, actor(scope="ORGANIZATION"))
    programs = authorized_program_universe(db, ctx)
    population = frozen_membership_query(db, ctx, resolve_filters(db, ctx, {}, authorized_program_ids=programs), authorized_program_ids=programs)
    statements = []
    listener = lambda _conn, _cursor, statement, _parameters, _context, _many: statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        before = len(statements)
        assert candidate_membership_counts(db, ctx, population) is None
        assert identification_membership_counts(db, ctx, population) is None
        assert len(statements) == before
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)


def test_sensitive_membership_queries_and_required_execution_are_program_grain(db):
    ctx = context(db, actor(scope="ORGANIZATION"), "talent_review_candidates.view", "talent_official_identifications.view")
    programs = authorized_program_universe(db, ctx)
    population = frozen_membership_query(db, ctx, resolve_filters(db, ctx, {}, authorized_program_ids=programs), authorized_program_ids=programs)
    candidates = candidate_membership_counts(db, ctx, population)
    assert [(row.program_id, row.count) for row in candidates] == [(1, 1)]
    identifications = identification_membership_counts(db, ctx, population)
    assert [(row.program_id, row.count) for row in identifications] == [(1, 1)]
    assert [(row.program_id, row.executed, row.cancelled, row.outstanding) for row in required_period_execution_counts(db, ctx, authorized_program_ids=programs)] == [(1, 1, 1, 1)]


def test_query_family_count_is_bounded_not_matrix_cell_proportional(db):
    ctx = context(db, actor(scope="ORGANIZATION"))
    programs = authorized_program_universe(db, ctx)
    population = frozen_membership_query(db, ctx, resolve_filters(db, ctx, {}, authorized_program_ids=programs), authorized_program_ids=programs)
    statements = []
    listener = lambda _conn, _cursor, statement, _parameters, _context, _many: statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        coverage_by_program_branch(db, population)
        coverage_by_program_grade(db, population)
        coverage_program_totals(db, population)
        coverage_branch_totals(db, population)
        coverage_organization_total(db, population)
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert len(statements) == 5
    assert all("GROUP BY" in statement.upper() for statement in statements)


def test_fingerprint_is_normalized_context_evidence_not_authorization_or_freshness(db):
    ctx = context(db, actor(scope="ORGANIZATION"))
    filters = resolve_filters(db, ctx, {"program_ids": [2, 1]}, authorized_program_ids=(1, 2))
    first = compute_request_context_fingerprint(ctx, projection_family="program_branch", metric="completed", authorized_program_ids=(1, 2), filters=filters, privacy_policy_version="test-v1")
    second = compute_request_context_fingerprint(ctx, projection_family="program_branch", metric="completed", authorized_program_ids=(1, 2), filters=filters, privacy_policy_version="test-v1")
    assert first == second and len(first) == 64
    db.get(models.TalentAssessmentCyclePopulationMember, 1).section_name = "Changed"
    db.flush()
    assert compute_request_context_fingerprint(ctx, projection_family="program_branch", metric="completed", authorized_program_ids=(1, 2), filters=filters, privacy_policy_version="test-v1") == first


def test_future_serialization_must_enter_through_b2_closed_projection_seam():
    def cell(number):
        return CellIdentity(school_group_id=1, academic_year_id=100, metric="completion_coverage", measure_component="numerator" if number == 1 else "denominator", membership_grain="frozen_membership", cycle_id=number)
    numerator, denominator = cell(1), cell(2)
    topology = PrivacyRelationshipGraph.from_contract(school_group_id=1, cells=(numerator, denominator), relationships=(Relationship((RelationshipTerm(numerator, 1), RelationshipTerm(denominator, -1)), 0),))
    closure = close_privacy_graph(topology, (PrivacyProjection(numerator, SUPPRESSED), PrivacyProjection(denominator, VISIBLE, 10)))
    with pytest.raises(TypeError):
        PrivacyClosedProjectionSet({})
    closed = PrivacyClosedProjectionSet(closure)
    assert closed.derived_payload((numerator, denominator), {"numerator": 2, "denominator": 10, "percentage": 20}) == {"state": SUPPRESSED}


def test_no_new_permission_or_entitlement_vocabulary_is_invented():
    source = __import__("pathlib").Path(__file__).resolve().parents[1].joinpath("talent_org_intelligence_service.py").read_text(encoding="utf-8")
    assert "feature.cross_branch_reporting" not in source
    assert "feature.advanced_reporting" not in source
    assert "entitlement_key" not in source
    assert "talent_org_intelligence." not in source
