from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import db_migrations
import auth
import permission_registry
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_assessment_cycles import router as cycle_router
from routers.talent_evaluation_plans import router as plan_router
from talent_assessment_cycle_service import TalentAssessmentCycleError, create_cycle, open_cycle
from talent_evaluation_plan_service import (
    TalentEvaluationPlanError, activate_plan, add_period, cancel_period,
    close_plan, closure_preflight, create_plan, delete_period, plan_warnings,
    reorder_periods, rollover_plan, update_period, validate_cycle_period_link,
)
from talent_program_service import (
    activate_framework, create_framework_draft, create_program,
    transition_program, upsert_annual_configuration,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=101, school_group_id=1, year_name="2027-2028"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    session.commit()
    yield session
    session.close()


def foundation(db):
    program = create_program(db, school_group_id=1, name="Potential")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Potential Framework")
    activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    config = upsert_annual_configuration(db, school_group_id=1, program_id=program.id,
                                         academic_year_id=100, is_enabled=True, eligible_grade_levels=["1"])
    next_config = upsert_annual_configuration(db, school_group_id=1, program_id=program.id,
                                              academic_year_id=101, is_enabled=True, eligible_grade_levels=["1"])
    db.commit()
    return program, framework, config, next_config


def plan_with_periods(db, count=3):
    program, framework, config, next_config = foundation(db)
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    for index in range(1, count + 1):
        plan, _ = add_period(db, school_group_id=1, plan_id=plan.id,
                             expected_plan_revision=plan.revision, label=f"Term {index}",
                             short_code=f"T{index}", is_required=index < 3)
    db.commit()
    return program, framework, config, next_config, plan


def user(user_id, *, role="Administrator", scope="ORGANIZATION", group=1, branch=10):
    return models.User(user_id=user_id, username=f"u{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=group, branch_id=branch,
                       academic_year_id=100 if group == 1 else 200, is_active=True)


def client(db, current):
    app = FastAPI()
    app.include_router(cycle_router)
    app.include_router(plan_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


def grant(db, role, *keys):
    db.add_all([models.RolePermission(school_group_id=1, role=role, permission_key=key, is_allowed=True) for key in keys])
    db.commit()


def test_plan_create_context_uniqueness_and_tenant_isolation(db):
    _, _, config, _ = foundation(db)
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    assert (plan.status, plan.revision, plan.program_id, plan.academic_year_id) == ("draft", 1, config.program_id, 100)
    with pytest.raises(TalentEvaluationPlanError) as foreign:
        create_plan(db, school_group_id=2, configuration_id=config.id)
    assert foreign.value.code == "not_found"
    db.commit()
    with pytest.raises(TalentEvaluationPlanError) as duplicate:
        create_plan(db, school_group_id=1, configuration_id=config.id)
    assert duplicate.value.code == "plan_conflict"


def test_plan_and_period_api_create_get_list(db):
    _, _, config, _ = foundation(db)
    admin = user("1000000001")
    db.add(admin)
    db.commit()
    with client(db, admin) as api:
        created = api.post("/api/talent/evaluation-plans", json={"program_academic_year_configuration_id": config.id})
        assert created.status_code == 201
        plan = created.json()
        assert plan["status"] == "draft" and plan["revision"] == 1 and plan["periods"] == []
        added = api.post(f"/api/talent/evaluation-plans/{plan['id']}/periods", json={
            "expected_plan_revision": 1, "label": "Term Review", "short_code": "TR",
            "planned_start_date": "2026-09-01", "planned_end_date": "2026-10-01",
        })
        assert added.status_code == 201 and added.json()["period"]["sequence"] == 1
        assert api.get(f"/api/talent/evaluation-plans/{plan['id']}").json()["period_count"] == 1
        assert len(api.get("/api/talent/evaluation-plans").json()) == 1


def test_period_normalization_dates_contiguity_edit_delete_and_stale_revision(db):
    _, _, config, _ = foundation(db)
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, first = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=1,
                             label="Term Review", short_code=" TR ", planned_start_date="2026-09-01", planned_end_date="2026-09-30")
    with pytest.raises(TalentEvaluationPlanError) as duplicate:
        add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=2, label=" term review ")
    assert duplicate.value.code == "period_identity_conflict"
    with pytest.raises(TalentEvaluationPlanError) as invalid:
        add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision,
                   label="Invalid", planned_start_date="2026-10-02", planned_end_date="2026-10-01")
    assert invalid.value.code == "invalid_date_range"
    plan, second = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Second")
    plan, second = update_period(db, school_group_id=1, period_id=second.id,
                                 expected_plan_revision=plan.revision, label="Second Updated", notes="Bounded")
    with pytest.raises(TalentEvaluationPlanError) as stale:
        update_period(db, school_group_id=1, period_id=second.id, expected_plan_revision=1, label="Lost")
    assert stale.value.code == "stale_plan"
    plan = delete_period(db, school_group_id=1, period_id=first.id, expected_plan_revision=plan.revision)
    assert [(row.label, row.sequence) for row in db.query(models.TalentPlannedEvaluationPeriod).all()] == [("Second Updated", 1)]


def test_atomic_reorder_and_used_anchor_immutability(db):
    program, framework, _, _, plan = plan_with_periods(db)
    rows = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()
    plan = reorder_periods(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision,
                           period_ids=[rows[2].id, rows[1].id, rows[0].id])
    assert [row.id for row in db.query(models.TalentPlannedEvaluationPeriod).order_by(models.TalentPlannedEvaluationPeriod.sequence)] == [rows[2].id, rows[1].id, rows[0].id]
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Cycle", population_effective_at=datetime(2026, 10, 1))
    plan, _, cycle = validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=rows[2].id,
                                                expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    with pytest.raises(TalentEvaluationPlanError) as anchored:
        reorder_periods(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision,
                        period_ids=[rows[1].id, rows[2].id, rows[0].id])
    assert anchored.value.code == "historical_anchor_immutable"


def test_activation_cancellation_closure_and_optional_unresolved(db):
    _, _, _, _, plan = plan_with_periods(db)
    rows = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    plan, _ = cancel_period(db, school_group_id=1, period_id=rows[0].id, expected_plan_revision=plan.revision, cancellation_reason="Not run")
    plan, _ = cancel_period(db, school_group_id=1, period_id=rows[1].id, expected_plan_revision=plan.revision, cancellation_reason="Not run")
    preflight = closure_preflight(db, school_group_id=1, plan_id=plan.id)
    assert preflight["can_close"] is True  # third Period is optional and unresolved
    plan = close_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    assert plan.status == "closed"
    with pytest.raises(TalentEvaluationPlanError):
        cancel_period(db, school_group_id=1, period_id=rows[2].id, expected_plan_revision=plan.revision, cancellation_reason="Again")


def test_required_open_or_draft_cycle_blocks_close_but_closed_executes(db):
    program, framework, _, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Cycle", population_effective_at=datetime(2026, 10, 1))
    plan, _, cycle = validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
                                                expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    assert closure_preflight(db, school_group_id=1, plan_id=plan.id)["can_close"] is False
    open_cycle(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    assert closure_preflight(db, school_group_id=1, plan_id=plan.id)["can_close"] is False
    cycle.status = "closed"
    db.flush()
    assert closure_preflight(db, school_group_id=1, plan_id=plan.id)["can_close"] is True


def test_link_unlink_context_revisions_and_one_to_one_constraints(db):
    program, framework, _, _, plan = plan_with_periods(db, count=2)
    periods = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    first = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="First")
    second = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Second")
    plan, _, first = validate_cycle_period_link(db, school_group_id=1, cycle_id=first.id, period_id=periods[0].id,
                                                expected_plan_revision=plan.revision, expected_cycle_revision=first.revision)
    with pytest.raises(TalentEvaluationPlanError) as duplicate:
        validate_cycle_period_link(db, school_group_id=1, cycle_id=second.id, period_id=periods[0].id,
                                   expected_plan_revision=plan.revision, expected_cycle_revision=second.revision)
    assert duplicate.value.code == "period_link_conflict"
    plan, _, first = validate_cycle_period_link(db, school_group_id=1, cycle_id=first.id, period_id=periods[0].id,
                                                expected_plan_revision=plan.revision, expected_cycle_revision=first.revision, unlink=True)
    assert first.planned_evaluation_period_id is None


def test_link_rejects_stale_plan_and_stale_cycle_revision_independently(db):
    program, framework, _, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Cycle")
    with pytest.raises(TalentEvaluationPlanError) as stale_plan:
        validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
                                   expected_plan_revision=plan.revision + 1, expected_cycle_revision=cycle.revision)
    assert stale_plan.value.code == "stale_plan"
    with pytest.raises(TalentEvaluationPlanError) as stale_cycle:
        validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
                                   expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision + 1)
    assert stale_cycle.value.code == "stale_cycle"
    # Neither rejected attempt mutated anything: the link still succeeds
    # cleanly with the true current revisions.
    fresh_plan, _, fresh_cycle = validate_cycle_period_link(
        db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
        expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision,
    )
    assert fresh_cycle.planned_evaluation_period_id == period.id


def test_linked_cycle_open_validates_active_context_and_adhoc_unchanged(db):
    program, framework, _, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    linked = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Linked", population_effective_at=datetime(2026, 10, 1))
    adhoc = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Ad hoc", population_effective_at=datetime(2026, 10, 1))
    plan, _, linked = validate_cycle_period_link(db, school_group_id=1, cycle_id=linked.id, period_id=period.id,
                                                 expected_plan_revision=plan.revision, expected_cycle_revision=linked.revision)
    plan.status = "closed"
    plan.closed_at = datetime.utcnow()
    db.flush()
    with pytest.raises(TalentAssessmentCycleError) as invalid:
        open_cycle(db, school_group_id=1, cycle_id=linked.id, expected_revision=linked.revision, organization_authorized=True)
    assert invalid.value.code == "linked_period_context_invalid"
    assert open_cycle(db, school_group_id=1, cycle_id=adhoc.id, expected_revision=adhoc.revision, organization_authorized=True).status == "open"


def test_closed_plan_optional_draft_unlink_only(db):
    program, framework, _, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    period.is_required = False
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Optional")
    plan, _, cycle = validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id, expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    plan = close_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    plan, _, cycle = validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id, expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision, unlink=True)
    assert plan.status == "closed" and cycle.planned_evaluation_period_id is None


def test_closed_plan_required_draft_unlink_is_rejected(db):
    # The approved Closed-Plan unlink exception is Optional-Period-only. A
    # Required Period can never reach Closed with an unresolved (Draft) linked
    # Cycle through the normal lifecycle (closure itself would have blocked
    # on required_periods_outstanding), so this proves the service-layer
    # boundary is defense-in-depth exact rather than accidentally broader.
    program, framework, _, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    assert period.is_required is True
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Required")
    plan, _, cycle = validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id, expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    plan.status = "closed"
    plan.closed_at = datetime.utcnow()
    db.flush()
    with pytest.raises(TalentEvaluationPlanError) as blocked:
        validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
                                   expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision, unlink=True)
    assert blocked.value.code == "closed_plan_link_immutable"
    assert cycle.planned_evaluation_period_id == period.id


def test_rollover_copies_identity_and_resets_execution_fields(db):
    _, _, _, destination_config, plan = plan_with_periods(db, count=2)
    source_revision = plan.revision
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=source_revision)
    destination = rollover_plan(db, school_group_id=1, source_plan_id=plan.id,
                                destination_configuration_id=destination_config.id,
                                expected_plan_revision=plan.revision)
    copied = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=destination.id).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()
    assert destination.status == "draft" and destination.revision == 1 and destination.source_plan_id == plan.id
    assert [(p.label, p.short_code, p.sequence, p.is_required) for p in copied] == [("Term 1", "T1", 1, True), ("Term 2", "T2", 2, True)]
    assert all(p.planned_start_date is None and p.notes is None and p.status == "planned" for p in copied)
    assert plan.revision == source_revision + 1


def test_warnings_are_advisory_and_deterministic(db):
    _, _, config, _ = foundation(db)
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, _ = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=1, label="One", planned_start_date="2026-09-01", planned_end_date="2026-10-01")
    plan, _ = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=2, label="Two", planned_start_date="2026-09-15", planned_end_date="2026-09-20")
    assert [warning["code"] for warning in plan_warnings(db, plan)] == ["period_window_overlap"]


def test_audit_uses_bounded_plan_and_period_resources(db):
    _, _, config, _ = foundation(db)
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, period = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=1, label="Review")
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    rows = db.query(models.TalentConfigurationAudit).filter_by(program_id=plan.program_id).order_by(models.TalentConfigurationAudit.id).all()
    resources = {(row.resource_type, row.action) for row in rows}
    assert ("annual_evaluation_plan", "create") in resources
    assert ("planned_evaluation_period", "create") in resources
    assert ("annual_evaluation_plan", "activate") in resources
    assert all("student" not in (row.after_json or "").casefold() for row in rows if row.resource_type in {"annual_evaluation_plan", "planned_evaluation_period"})


def test_permissions_branch_read_only_and_cycle_projection_zero_leakage(db):
    program, framework, config, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Hidden")
    validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id, expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    branch_reader = user("1000000001", role="Editor", scope="BRANCH")
    cycle_reader = user("1000000002", role="Editor", scope="BRANCH")
    branch_manager = user("1000000003", role="User", scope="BRANCH")
    db.add_all([branch_reader, branch_manager])
    grant(db, "Editor", "talent_evaluation_plans.view")
    grant(db, "User", "talent_evaluation_plans.view", "talent_evaluation_plans.manage", "talent_evaluation_plans.govern")
    assert auth.has_permission(db, branch_manager, "talent_evaluation_plans.manage")
    assert auth.has_permission(db, branch_manager, "talent_evaluation_plans.govern")
    with client(db, branch_reader) as api:
        body = api.get(f"/api/talent/evaluation-plans/{plan.id}").json()
        assert "cycle" not in body["periods"][0]
        assert not {"link_cycle", "unlink_cycle"}.intersection(body["periods"][0]["actions"])
    db.add(cycle_reader)
    grant(db, "Editor", "talent_assessment_cycles.view")
    with client(db, cycle_reader) as api:
        assert api.get(f"/api/talent/evaluation-plans/{plan.id}").json()["periods"][0]["cycle"]["id"] == cycle.id
    with client(db, branch_manager) as api:
        assert api.post("/api/talent/evaluation-plans", json={"program_academic_year_configuration_id": config.id}).status_code == 403
        assert api.post(f"/api/talent/evaluation-plans/{plan.id}/close", json={"expected_plan_revision": plan.revision}).status_code == 403


def test_closure_preflight_hides_cycle_execution_state_without_cycle_view(db):
    # closure-preflight's can_close/outstanding_required_period_ids are derived
    # entirely from linked Cycle status (Draft/Open vs Closed). A caller with
    # only talent_evaluation_plans.view must see byte-identical responses
    # whether the linked Cycle is unresolved or Closed - otherwise Cycle
    # execution state leaks through an aggregate placeholder with no Cycle
    # object ever attached (Section N zero-leakage).
    program, framework, config, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Hidden", population_effective_at=datetime(2026, 10, 1))
    validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
                               expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    db.commit()
    viewer = user("1000000001", role="Editor")
    db.add(viewer)
    grant(db, "Editor", "talent_evaluation_plans.view")
    with client(db, viewer) as api:
        before_close = api.get(f"/api/talent/evaluation-plans/{plan.id}/closure-preflight").json()
    assert before_close == {
        "plan_id": plan.id,
        "periods": [{"period_id": period.id, "sequence": period.sequence, "is_required": True}],
    }
    fresh_cycle = db.query(models.TalentAssessmentCycle).filter_by(id=cycle.id).one()
    fresh_cycle.status = "closed"
    db.commit()
    with client(db, viewer) as api:
        after_close = api.get(f"/api/talent/evaluation-plans/{plan.id}/closure-preflight").json()
    assert after_close == before_close
    grant(db, "Editor", "talent_assessment_cycles.view")
    # A fresh user object (not the already-`has_permission`-cached `viewer`
    # instance) mirrors a real new HTTP request/dependency-injected user, so
    # the newly granted permission is actually reflected.
    disclosed_viewer = user("1000000004", role="Editor")
    db.add(disclosed_viewer)
    db.commit()
    with client(db, disclosed_viewer) as api:
        disclosed = api.get(f"/api/talent/evaluation-plans/{plan.id}/closure-preflight").json()
    assert disclosed["can_close"] is True
    assert disclosed["periods"][0]["cycle"]["id"] == cycle.id


def test_true_and_permissions_for_link_and_rollover(db):
    program, framework, _, destination_config, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Cycle")
    one = user("1000000001", role="Editor")
    two = user("1000000002", role="User")
    db.add_all([one, two])
    grant(db, "Editor", "talent_evaluation_plans.view", "talent_evaluation_plans.manage")
    grant(db, "User", "talent_assessment_cycles.view", "talent_assessment_cycles.manage")
    assert auth.has_permission(db, one, "talent_evaluation_plans.manage")
    assert not auth.has_permission(db, one, "talent_assessment_cycles.manage")
    assert auth.has_permission(db, two, "talent_assessment_cycles.manage")
    assert not auth.has_permission(db, two, "talent_evaluation_plans.manage")
    payload = {"planned_period_id": period.id, "expected_plan_revision": plan.revision, "expected_cycle_revision": cycle.revision}
    with client(db, one) as api:
        assert api.post(f"/api/talent/assessment-cycles/{cycle.id}/link-period", json=payload).status_code == 403
    with client(db, two) as api:
        assert api.post(f"/api/talent/assessment-cycles/{cycle.id}/link-period", json=payload).status_code == 403
    assert "talent_evaluation_plans.view" in permission_registry.get_default_permissions_for_role("Administrator")
    assert not any(key.startswith("talent_evaluation_plans.") for key in permission_registry.get_default_permissions_for_role("Editor"))


def test_link_and_unlink_api_with_both_permissions(db):
    program, framework, _, _, plan = plan_with_periods(db, count=1)
    period = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan.id).one()
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id, title="Cycle")
    admin = user("1000000001")
    db.add(admin)
    db.commit()
    with client(db, admin) as api:
        linked = api.post(f"/api/talent/assessment-cycles/{cycle.id}/link-period", json={
            "planned_period_id": period.id, "expected_plan_revision": plan.revision,
            "expected_cycle_revision": cycle.revision,
        })
        assert linked.status_code == 200 and linked.json()["planned_period_id"] == period.id
        unlinked = api.post(f"/api/talent/assessment-cycles/{cycle.id}/unlink-period", json={
            "planned_period_id": period.id, "expected_plan_revision": linked.json()["plan_revision"],
            "expected_cycle_revision": linked.json()["cycle_revision"],
        })
        assert unlinked.status_code == 200 and unlinked.json()["planned_period_id"] is None


def test_manage_and_govern_are_independent_and_rollover_requires_view_and_manage(db):
    _, _, config, destination, plan = plan_with_periods(db, count=1)
    governor = user("1000000001", role="Editor")
    manager = user("1000000002", role="User")
    viewer = user("1000000003", role="Limited")
    db.add_all([governor, manager, viewer])
    grant(db, "Editor", "talent_evaluation_plans.govern")
    grant(db, "User", "talent_evaluation_plans.manage")
    grant(db, "Limited", "talent_evaluation_plans.view")
    with client(db, manager) as api:
        assert api.post(f"/api/talent/evaluation-plans/{plan.id}/activate", json={"expected_plan_revision": plan.revision}).status_code == 403
    with client(db, governor) as api:
        response = api.post(f"/api/talent/evaluation-plans/{plan.id}/activate", json={"expected_plan_revision": plan.revision})
        assert response.status_code == 200
    plan = db.get(models.TalentAnnualEvaluationPlan, plan.id)
    with client(db, manager) as api:
        assert api.get(f"/api/talent/evaluation-plans/{plan.id}/rollover-preview?destination_configuration_id={destination.id}").status_code == 403
    with client(db, viewer) as api:
        assert api.get(f"/api/talent/evaluation-plans/{plan.id}/rollover-preview?destination_configuration_id={destination.id}").status_code == 403


def test_plan_responses_contain_no_student_or_analytics_domains(db):
    _, _, _, _, plan = plan_with_periods(db, count=1)
    admin = user("1000000001")
    db.add(admin)
    db.commit()
    with client(db, admin) as api:
        body = api.get(f"/api/talent/evaluation-plans/{plan.id}").json()
    text = str(body).casefold()
    for forbidden in ("student_id", "student_name", "placement", "competency_result", "kpi_result", "review_candidate", "official_identification", "educator_input", "progress", "growth"):
        assert forbidden not in text


def test_m8_sqlite_migration_is_idempotent_and_schema_is_complete(db):
    engine = db.get_bind()
    with engine.begin() as connection:
        db_migrations._talent_annual_evaluation_plan_period_foundation(engine, connection)
        db_migrations._talent_annual_evaluation_plan_period_foundation(engine, connection)
    inspector = inspect(engine)
    assert inspector.has_table("talent_annual_evaluation_plans")
    assert inspector.has_table("talent_planned_evaluation_periods")
    assert "planned_evaluation_period_id" in {column["name"] for column in inspector.get_columns("talent_assessment_cycles")}
    cycle_indexes = {index["name"] for index in inspector.get_indexes("talent_assessment_cycles")}
    cycle_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("talent_assessment_cycles")}
    assert "uq_talent_assessment_cycles_period" in cycle_indexes | cycle_uniques
