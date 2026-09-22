"""M4 Authoritative Evaluation Progress focused coverage.

Covers: the active/opened Evaluation Period predicate (planned Period +
Open/Closed linked Cycle only), pure Current-Overall-Result arithmetic
matching the governed worked examples, Student progress
authorization/tenant isolation (owner-ratified Decision 2 - no aggregate
suppression on a single authorized Student), Branch/Organization Period
and Overall Result (including the unequal-Branch-size
not-average-of-Branch-averages proof and Pending/no-data exclusion),
Framework-version comparability (owner-ratified Decision 1), the Learning
Style Branch aggregate (null exclusion / zero inclusion / suppression), the
seven-metric Branch comparison dispatcher, and privacy adversarial cases
(missing provider fails closed, suppression, complementary suppression,
reconstruction safety).
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import talent_analytics_service as svc
import talent_evaluation_progress_service as progress_svc
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_evaluation_progress import router as progress_router
from student_academic_service import create_placement, create_student, transition_placement
from talent_analytics_privacy import (
    AllowAllTestPolicy,
    DeterministicSuppressionTestPolicy,
    NO_DATA,
    RESTRICTED,
    SUPPRESSED,
    VISIBLE,
    resolve_privacy_policy_provider,
)
from talent_assessment_cycle_service import close_cycle, create_cycle, open_cycle
from talent_evaluation_plan_service import activate_plan, add_period, cancel_period, create_plan, validate_cycle_period_link
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, create_competency,
    create_framework_draft, create_program, transition_program, upsert_annual_configuration, upsert_rubric,
)
from talent_student_assessment_service import complete_assessment, mark_non_complete, set_competency_result, start_assessment


# ---------------------------------------------------------------------------
# Section 1: pure arithmetic - proves the exact governed worked examples
# ---------------------------------------------------------------------------


def test_mean_percent_matches_governed_worked_examples():
    assert progress_svc._mean_percent([80]) == 80.0
    assert progress_svc._mean_percent([80, 90]) == 85.0
    assert progress_svc._mean_percent([80, 90, 84]) == 84.67
    assert progress_svc._mean_percent([]) is None  # never zero


def test_nominal_weight_is_one_over_active_period_count():
    assert progress_svc.nominal_weight(0) is None
    assert progress_svc.nominal_weight(1) == 1
    assert progress_svc.nominal_weight(4) == 0.25


# ---------------------------------------------------------------------------
# Section 2: DB fixture and full-stack integration
# ---------------------------------------------------------------------------


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
        models.Branch(id=10, school_group_id=1, name="Branch A"),
        models.Branch(id=11, school_group_id=1, name="Branch B"),
        models.Branch(id=20, school_group_id=2, name="Foreign Branch"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    session.commit()
    session.add_all([
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="Alpha", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=11, academic_year_id=100, grade_level="1", section_name="Beta", class_status="Current"),
    ])
    session.commit()
    yield session
    session.close()


def user(user_id, *, role="Administrator", scope="ORGANIZATION", group=1, branch=10):
    return models.User(user_id=user_id, username=f"u{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=group, branch_id=branch,
                       academic_year_id=100 if group == 1 else 200, is_active=True)


def client(db, current, *, policy=None):
    app = FastAPI()
    app.include_router(progress_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    if policy is not None:
        app.dependency_overrides[resolve_privacy_policy_provider] = lambda: policy
    return TestClient(app)


def make_student(db, *, first, branch, section, start=datetime(2026, 9, 1), group=1):
    student = create_student(db, school_group_id=group, first_name=first, last_name="Learner")
    placement = create_placement(db, school_group_id=group, student_id=student.id, academic_year_id=100 if group == 1 else 200,
                                 branch_id=branch, planning_section_id=section, effective_from=start)
    return student, placement


def _10_level_program(db, *, group=1, year=100, grades=("1",)):
    """One competency, 10 ordered rubric levels (position N -> N*10% exactly),
    so a Completed result's ADR 0037 normalized_percent is directly
    verifiable without any rounding ambiguity."""
    program = create_program(db, school_group_id=group, name="Talent Progress Program")
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title="Framework v1")
    competency = create_competency(db, school_group_id=group, program_id=program.id, code="MATH", name="Mathematics")
    fw_competency, framework = add_framework_competency(db, school_group_id=group, program_id=program.id, framework_id=framework.id, competency_id=competency.id, expected_revision=framework.revision)
    rubric, framework = upsert_rubric(db, school_group_id=group, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, name="10-level Rubric")
    levels = []
    for index in range(1, 11):
        level, framework = add_rubric_level(db, school_group_id=group, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code=f"L{index}", label=f"Level {index}")
        levels.append(level)
    framework = activate_framework(db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                                   expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                                   organization_authorized=True)
    config = upsert_annual_configuration(db, school_group_id=group, program_id=program.id, academic_year_id=year, is_enabled=True, eligible_grade_levels=list(grades))
    db.commit()
    return program, framework, fw_competency, rubric, levels, config


def _make_plan_with_period(db, *, config, label, is_required=True):
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, period = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label=label, is_required=is_required)
    return plan, period


def _link_and_open(db, *, plan, period, cycle, close=True):
    plan, period, cycle = validate_cycle_period_link(db, school_group_id=1, cycle_id=cycle.id, period_id=period.id,
                                                       expected_plan_revision=plan.revision, expected_cycle_revision=cycle.revision)
    cycle = open_cycle(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    if close:
        cycle = close_cycle(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    return plan, period, cycle


@pytest.fixture()
def scenario(db):
    program, framework, fw_competency, rubric, levels, config = _10_level_program(db)

    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, p1 = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Term 1")
    plan, p2 = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Term 2")
    plan, p3_future = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Term 3 (not yet opened)")
    plan, p4_cancelled = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Retired Diagnostic", is_required=False)
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)

    cancel_period(db, school_group_id=1, period_id=p4_cancelled.id, expected_plan_revision=plan.revision, cancellation_reason="No longer administered this year.")
    db.commit()

    # Branch A: 3 students. Branch B: 2 students (unequal populations, proves
    # Organization result cannot be average(BranchPeriodResult)). Students
    # and Placements must exist BEFORE a Cycle Opens - population freeze
    # captures whoever is eligible at Open time.
    a1, _ = make_student(db, first="A1", branch=10, section=1000)
    a2, _ = make_student(db, first="A2", branch=10, section=1000)
    a3, _ = make_student(db, first="A3", branch=10, section=1000)
    b1, _ = make_student(db, first="B1", branch=11, section=1001)
    b2, _ = make_student(db, first="B2", branch=11, section=1001)
    db.commit()

    cycle1 = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id,
                          title="Term 1 Cycle", population_effective_at=datetime(2026, 9, 15))
    db.commit()
    plan, p1, cycle1 = _link_and_open(db, plan=plan, period=p1, cycle=cycle1, close=True)
    db.commit()

    cycle2 = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id,
                          title="Term 2 Cycle", population_effective_at=datetime(2026, 12, 1))
    db.commit()
    plan, p2, cycle2 = _link_and_open(db, plan=plan, period=p2, cycle=cycle2, close=False)
    db.commit()

    ad_hoc = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id,
                          title="Ad Hoc Diagnostic", population_effective_at=datetime(2026, 10, 1))
    db.commit()

    members1 = {row.student_id: row for row in db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle1.id).all()}
    members2 = {row.student_id: row for row in db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle2.id).all()}

    def _complete(cycle_id, members, student, level_index):
        member = members[student.id]
        assessment = start_assessment(db, school_group_id=1, cycle_id=cycle_id, cycle_population_member_id=member.id)
        level = levels[level_index - 1]
        _, assessment = set_competency_result(db, school_group_id=1, assessment_id=assessment.id, framework_competency_id=fw_competency.id, rubric_level_id=level.id, expected_revision=assessment.revision)
        return complete_assessment(db, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)

    # Period 1 (Closed Cycle): Branch A -> 8, 9, incomplete; Branch B -> 6, unassessed.
    a1_p1 = _complete(cycle1.id, members1, a1, 8)   # 80%
    a2_p1 = _complete(cycle1.id, members1, a2, 9)   # 90%
    a3_incomplete = start_assessment(db, school_group_id=1, cycle_id=cycle1.id, cycle_population_member_id=members1[a3.id].id)
    mark_non_complete(db, school_group_id=1, assessment_id=a3_incomplete.id, expected_revision=a3_incomplete.revision, status="incomplete")
    b1_p1 = _complete(cycle1.id, members1, b1, 6)   # 60%
    # b2 stays unassessed in Period 1.
    db.commit()

    # Period 2 (Open Cycle): only Branch A's a1 completes; everyone else Pending.
    a1_p2 = _complete(cycle2.id, members2, a1, 9)   # 90%
    start_assessment(db, school_group_id=1, cycle_id=cycle2.id, cycle_population_member_id=members2[a2.id].id)  # Pending
    db.commit()

    return {
        "program": program, "framework": framework, "config": config, "plan": plan,
        "p1": p1, "p2": p2, "p3_future": p3_future, "p4_cancelled": p4_cancelled,
        "cycle1": cycle1, "cycle2": cycle2, "ad_hoc": ad_hoc,
        "students": {"a1": a1, "a2": a2, "a3": a3, "b1": b1, "b2": b2},
    }


def _ctx(db, program):
    return svc.resolve_context(db, school_group_id=1, program_id=program.id, academic_year_id=100)


# ---------------------------------------------------------------------------
# Section 3: active/opened Evaluation Period predicate
# ---------------------------------------------------------------------------


def test_active_periods_exclude_future_cancelled_and_ad_hoc(db, scenario):
    ctx = _ctx(db, scenario["program"])
    active = progress_svc.resolve_active_periods(ctx)
    active_ids = {period.id for period, _ in active}
    assert active_ids == {scenario["p1"].id, scenario["p2"].id}
    assert scenario["p3_future"].id not in active_ids  # never opened
    assert scenario["p4_cancelled"].id not in active_ids  # cancelled
    # The ad-hoc Cycle has no planned_evaluation_period_id, so it can never
    # appear as a weighting position regardless of its own open/closed state.
    assert all(cycle.id != scenario["ad_hoc"].id for _, cycle in active)


def test_configured_label_never_affects_order_or_weight(db, scenario):
    ctx = _ctx(db, scenario["program"])
    active = progress_svc.resolve_active_periods(ctx)
    # Sequence-derived order regardless of label text/length.
    assert [period.sequence for period, _ in active] == [1, 2]
    assert progress_svc.nominal_weight(len(active)) == 0.5


# ---------------------------------------------------------------------------
# Section 4: Student Evaluation Progress (Decision 2)
# ---------------------------------------------------------------------------


def test_student_progress_excludes_pending_and_averages_available_only(db, scenario):
    ctx = _ctx(db, scenario["program"])
    payload = progress_svc.build_student_progress(db, ctx, student_id=scenario["students"]["a1"].id)
    assert payload["active_period_count"] == 2
    assert payload["available_result_count"] == 2
    assert payload["pending_or_unavailable_count"] == 0
    assert [entry["normalized_percent"] for entry in payload["periods"]] == [80, 90]
    assert payload["current_overall_result"] == 85.0


def test_student_progress_pending_excluded_not_averaged_as_zero(db, scenario):
    ctx = _ctx(db, scenario["program"])
    payload = progress_svc.build_student_progress(db, ctx, student_id=scenario["students"]["a2"].id)
    states = [entry["result_state"] for entry in payload["periods"]]
    assert states == ["available", "pending"]
    assert payload["available_result_count"] == 1
    assert payload["pending_or_unavailable_count"] == 1
    # a2 = 90 in Period 1 only; Pending must not become 0 or reduce the average.
    assert payload["current_overall_result"] == 90.0


def test_student_progress_incomplete_and_unassessed_states(db, scenario):
    ctx = _ctx(db, scenario["program"])
    a3 = progress_svc.build_student_progress(db, ctx, student_id=scenario["students"]["a3"].id)
    assert a3["periods"][0]["result_state"] == "incomplete"
    assert a3["periods"][0]["normalized_percent"] is None
    b2 = progress_svc.build_student_progress(db, ctx, student_id=scenario["students"]["b2"].id)
    assert b2["periods"][0]["result_state"] == "unassessed"
    assert b2["current_overall_result"] is None  # no available result at all -> null, never 0


def test_student_progress_authorized_access_via_api(db, scenario):
    admin = user("1000000001")
    db.add(admin)
    db.commit()
    with client(db, admin) as api:
        response = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/students/{scenario['students']['a1'].id}")
        assert response.status_code == 200
        body = response.json()
        assert body["current_overall_result"] == 85.0
        # Student route is not privacy-gated - no suppression parameters
        # can even be supplied; the raw available result is exact fact.


def test_student_progress_unauthorized_branch_scoped_access_is_non_enumerating_404(db, scenario):
    branch_b_user = user("1000000002", role="Editor", scope="BRANCH", branch=11)
    db.add(branch_b_user)
    db.add(models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_learner_profiles.view", is_allowed=True))
    db.commit()
    with client(db, branch_b_user) as api:
        # a1 is frozen exclusively in Branch A - a Branch B actor must not
        # see this Student's Evaluation Progress at all.
        response = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/students/{scenario['students']['a1'].id}")
        assert response.status_code == 404
        # Their own Branch's Student remains visible.
        own = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/students/{scenario['students']['b1'].id}")
        assert own.status_code == 200


def test_student_progress_denied_without_permission(db, scenario):
    nobody = user("1000000003", role="Nobody", scope="ORGANIZATION")
    db.add(nobody)
    db.commit()
    with client(db, nobody) as api:
        response = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/students/{scenario['students']['a1'].id}")
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Section 5: Branch / Organization Evaluation Progress
# ---------------------------------------------------------------------------


def test_branch_period_result_is_direct_mean_of_frozen_students(db, scenario):
    ctx = _ctx(db, scenario["program"])
    payload = progress_svc.build_branch_progress(db, ctx, branch_id=10, visible_branch_ids=None, policy=AllowAllTestPolicy())
    period1 = payload["periods"][0]
    assert period1["state"] == VISIBLE
    # Branch A Period 1: 80 (a1), 90 (a2); a3 incomplete excluded (Pending never zero).
    assert period1["mean_normalized_percent"] == 85.0
    assert period1["count"] == 2


def test_organization_period_result_is_not_average_of_branch_averages(db, scenario):
    ctx = _ctx(db, scenario["program"])
    org = progress_svc.build_organization_progress(db, ctx, visible_branch_ids=None, policy=AllowAllTestPolicy())
    period1 = org["periods"][0]
    # Branch A mean = 85.0 (80, 90); Branch B mean = 60.0 (only b1 completed).
    # average(BranchPeriodResult) would be (85+60)/2 = 72.5.
    # Direct Student-level mean = (80+90+60)/3 = 76.67.
    assert period1["mean_normalized_percent"] == pytest.approx(76.67)
    assert period1["mean_normalized_percent"] != 72.5


def test_branch_overall_result_pending_period_does_not_reduce_result(db, scenario):
    ctx = _ctx(db, scenario["program"])
    payload = progress_svc.build_branch_progress(db, ctx, branch_id=10, visible_branch_ids=None, policy=AllowAllTestPolicy())
    # Period 1 mean=85.0 (a1,a2); Period 2 has only a1=90 (a2 still Pending in
    # Period 2, and a2's own Pending state does not zero or dilute the
    # Branch's Period-2 mean, nor should Period 2 existing at all reduce the
    # combined Overall below what the two visible Period means produce).
    assert payload["periods"][1]["mean_normalized_percent"] == 90.0
    assert payload["current_overall_result"]["state"] == VISIBLE
    assert payload["current_overall_result"]["value"] == pytest.approx((85.0 + 90.0) / 2, rel=1e-3)


def test_branch_and_organization_progress_via_api(db, scenario):
    admin = user("1000000004")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        branch = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/branches/10").json()
        assert branch["periods"][0]["mean_normalized_percent"] == 85.0
        org = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/organization").json()
        assert org["periods"][0]["mean_normalized_percent"] == pytest.approx(76.67)


def test_organization_progress_scoped_actor_never_escapes_authorized_branches(db, scenario):
    branch_a_user = user("1000000005", role="Editor", scope="BRANCH", branch=10)
    db.add(branch_a_user)
    db.add(models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_analytics.view", is_allowed=True))
    db.commit()
    with client(db, branch_a_user, policy=AllowAllTestPolicy()) as api:
        org = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/organization").json()
        # A Branch-scoped actor's "Organization" view is restricted to their
        # own authorized Branch's Students only (80, 90) -> mean 85.0, never
        # Branch B's contribution.
        assert org["periods"][0]["mean_normalized_percent"] == 85.0
        denied = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/branches/11")
        assert denied.status_code == 404


# ---------------------------------------------------------------------------
# Section 6: Framework comparability (Decision 1)
# ---------------------------------------------------------------------------


def test_cross_framework_active_periods_block_combined_overall(db, scenario):
    program = scenario["program"]
    # A second Framework Version, activated and bound to a brand new Period 3.
    framework2 = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Framework v2", supersedes_framework_version_id=scenario["framework"].id)
    competency2 = create_competency(db, school_group_id=1, program_id=program.id, code="SCI", name="Science")
    fw_competency2, framework2 = add_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework2.id, competency_id=competency2.id, expected_revision=framework2.revision)
    rubric2, framework2 = upsert_rubric(db, school_group_id=1, program_id=program.id, framework_id=framework2.id, expected_revision=framework2.revision, name="v2 Rubric")
    level2, framework2 = add_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework2.id, expected_revision=framework2.revision, code="ONLY", label="Only Level")
    framework2 = activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework2.id,
                                    expected_revision=framework2.revision, expected_fingerprint=framework2.semantic_fingerprint,
                                    organization_authorized=True)
    db.commit()

    plan = scenario["plan"]
    from talent_evaluation_plan_service import _require_plan
    plan = _require_plan(db, 1, plan.id)
    plan, p5 = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="New Framework Term")
    db.commit()
    cycle3 = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework2.id,
                          title="Framework v2 Cycle", population_effective_at=datetime(2027, 1, 1))
    db.commit()
    plan, p5, cycle3 = _link_and_open(db, plan=plan, period=p5, cycle=cycle3, close=True)
    db.commit()

    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle3.id, student_id=scenario["students"]["a1"].id).one()
    assessment = start_assessment(db, school_group_id=1, cycle_id=cycle3.id, cycle_population_member_id=member.id)
    _, assessment = set_competency_result(db, school_group_id=1, assessment_id=assessment.id, framework_competency_id=fw_competency2.id, rubric_level_id=level2.id, expected_revision=assessment.revision)
    complete_assessment(db, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)
    db.commit()

    ctx = _ctx(db, program)
    payload = progress_svc.build_student_progress(db, ctx, student_id=scenario["students"]["a1"].id)
    assert payload["comparability_state"] == "not_comparable"
    assert payload["comparability_reason_code"] == "framework_changed"
    assert payload["current_overall_result"] is None  # never averaged/normalized across frameworks
    # Every individual Period result remains visible/preserved.
    assert {entry["period_id"]: entry["normalized_percent"] for entry in payload["periods"]}[scenario["p1"].id] == 80

    branch_payload = progress_svc.build_branch_progress(db, ctx, branch_id=10, visible_branch_ids=None, policy=AllowAllTestPolicy())
    assert branch_payload["comparability_state"] == "not_comparable"
    assert branch_payload["current_overall_result"] == {"state": NO_DATA, "value": None}
    assert branch_payload["periods"][2]["mean_normalized_percent"] == 100.0  # a1's only Framework v2 result preserved


# ---------------------------------------------------------------------------
# Section 7: Privacy adversarial cases
# ---------------------------------------------------------------------------


def test_missing_privacy_provider_fails_closed_for_branch_and_org(db, scenario, monkeypatch):
    # Force the real provider-resolution path closed regardless of the
    # developer shell's ambient DATABASE_URL/env state, matching the exact
    # established M9 pattern (test_talent_analytics.py's
    # test_production_privacy_provider_fails_closed_without_governed_configuration).
    monkeypatch.setenv("TIS_ENV", "production")
    monkeypatch.delenv("TIS_ORGANIZATION_ANALYTICS_MINIMUM_COHORT", raising=False)
    admin = user("1000000006")
    db.add(admin)
    db.commit()
    with client(db, admin) as api:  # no policy override -> resolve_privacy_policy_provider() runs for real
        response = api.get(f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/branches/10")
        assert response.status_code == 503


def test_branch_period_result_suppressed_below_minimum_cohort(db, scenario):
    ctx = _ctx(db, scenario["program"])
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=3)
    payload = progress_svc.build_branch_progress(db, ctx, branch_id=11, visible_branch_ids=None, policy=policy)
    # Branch B Period 1 has only 1 valid completed result (b1) - below the
    # cohort-5 threshold used here (3) -> suppressed, no mean/count leaked.
    period1 = payload["periods"][0]
    assert period1["state"] == SUPPRESSED
    assert period1["count"] is None
    assert period1["mean_normalized_percent"] is None


def test_complementary_suppression_protects_reconstruction_across_branches(db, scenario):
    ctx = _ctx(db, scenario["program"])
    # minimum_cohort=2: Branch B's count (1) is suppressed by primary
    # privacy; Branch A's count (2) alone would let Org total - BranchA =
    # BranchB be reconstructed by subtraction unless complementary
    # suppression also hides Branch A.
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    payload = progress_svc.build_branch_progress(db, ctx, branch_id=10, visible_branch_ids=None, policy=policy)
    period1 = payload["periods"][0]
    assert period1["state"] == SUPPRESSED
    assert period1["mean_normalized_percent"] is None


def test_organization_overall_never_reconstructs_a_suppressed_period(db, scenario):
    ctx = _ctx(db, scenario["program"])
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=10)  # suppresses every count everywhere
    org = progress_svc.build_organization_progress(db, ctx, visible_branch_ids=None, policy=policy)
    assert all(period["state"] in (SUPPRESSED, NO_DATA) for period in org["periods"])
    assert org["current_overall_result"] == {"state": NO_DATA, "value": None}


# ---------------------------------------------------------------------------
# Section 8: Learning Style Branch aggregate
# ---------------------------------------------------------------------------


def test_learning_style_aggregate_excludes_null_and_includes_zero(db, scenario):
    students = scenario["students"]
    students["a1"].learning_style_verbal_percentage = 80
    students["a2"].learning_style_verbal_percentage = 0  # a real valid value
    students["a3"].learning_style_verbal_percentage = None  # excluded, not treated as 0
    db.commit()

    ctx = _ctx(db, scenario["program"])
    filters = svc.ResolvedFilters()
    pop_query = svc.population_query(db, ctx, filters, None)
    result = progress_svc.learning_style_branch_aggregate(db, ctx, pop_query, dimension="verbal", policy=AllowAllTestPolicy())
    branch_a_row = next(row for row in result["rows"] if row["branch_id"] == 10)
    assert branch_a_row["count"] == 2  # a1 and a2 only; a3's null excluded
    assert branch_a_row["mean_normalized_percent"] == 40.0  # (80 + 0) / 2


def test_learning_style_aggregate_suppressed_below_minimum_cohort(db, scenario):
    students = scenario["students"]
    students["b1"].learning_style_spatial_percentage = 50
    db.commit()
    ctx = _ctx(db, scenario["program"])
    filters = svc.ResolvedFilters()
    pop_query = svc.population_query(db, ctx, filters, None)
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    result = progress_svc.learning_style_branch_aggregate(db, ctx, pop_query, dimension="spatial", policy=policy)
    branch_b_row = next(row for row in result["rows"] if row["branch_id"] == 11)
    assert branch_b_row["count"] is None
    assert branch_b_row["mean_normalized_percent"] is None
    assert branch_b_row["state"] == SUPPRESSED


# ---------------------------------------------------------------------------
# Section 9: Branch comparison metric dispatcher (7 approved metrics)
# ---------------------------------------------------------------------------


def test_branch_comparison_dispatcher_all_seven_metrics(db, scenario):
    admin = user("1000000007")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        base = f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/branch-comparison"
        for metric in ("evaluation_period_result", "current_overall_progress", "assessment_completion",
                       "assessments_started", "meets_program_criteria", "officially_confirmed"):
            response = api.get(base, params={"metric": metric})
            assert response.status_code == 200, (metric, response.text)
            assert response.json()["metric"] == metric
        response = api.get(base, params={"metric": "learning_style", "learning_style_dimension": "verbal"})
        assert response.status_code == 200


def test_branch_comparison_candidate_and_identification_metrics_are_query_skipped_without_permission(db, scenario):
    # A non-Administrator actor holding ONLY the aggregate analytics
    # permission must never receive meets_program_criteria/
    # officially_confirmed - those require their own independent permission
    # (query-skip, not response-filtering), matching the existing M9
    # candidate/identification discipline exactly.
    restricted = user("1000000009", role="Editor", scope="ORGANIZATION")
    db.add(restricted)
    db.add(models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_analytics.view", is_allowed=True))
    db.commit()
    with client(db, restricted, policy=AllowAllTestPolicy()) as api:
        base = f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/branch-comparison"
        denied = api.get(base, params={"metric": "meets_program_criteria"})
        assert denied.status_code == 403
        denied2 = api.get(base, params={"metric": "officially_confirmed"})
        assert denied2.status_code == 403
        # The other five metrics remain available with only talent_analytics.view.
        allowed = api.get(base, params={"metric": "assessment_completion"})
        assert allowed.status_code == 200


def test_branch_comparison_rejects_unapproved_metric(db, scenario):
    admin = user("1000000008")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        base = f"/api/talent/evaluation-progress/programs/{scenario['program'].id}/academic-years/100/branch-comparison"
        response = api.get(base, params={"metric": "invented_metric_not_in_registry"})
        assert response.status_code == 400
