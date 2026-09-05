"""M9 Deterministic Talent Analytics focused coverage.

Covers: the standalone complementary-suppression engine (no DB), permission
composition/defaults, historical frozen-context security (branch transfer),
tenant isolation, Candidate/Identification zero-leakage across all four
permission combinations, privacy states via explicit injected test policies
(fail-closed, visible, suppressed, no_data), complementary-suppression
identity-based tie-break proof, KPI R1 minimal contract, comparability
(framework_changed / comparable), fingerprint non-freshness proof, a
query-count regression baseline, Student drill pagination/restriction, and
M8/raw-API non-escalation.
"""

import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import talent_analytics_service as svc
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_analytics import router as analytics_router
from routers.talent_assessment_cycles import router as cycle_router
from routers.talent_evaluation_plans import router as plan_router
from student_academic_service import create_placement, create_student, transition_placement
from talent_analytics_privacy import (
    AllowAllTestPolicy,
    Cell,
    COARSENED,
    CoarsenWithoutReplacementTestPolicy,
    CoarsenWithReplacementTestPolicy,
    DeterministicSuppressionTestPolicy,
    Group,
    NO_DATA,
    PrivacyDecision,
    RESTRICTED,
    SUPPRESSED,
    VISIBLE,
    apply_primary_privacy,
    derive_from_visible_cells,
    resolve_privacy_policy_provider,
    run_complementary_suppression,
)
from talent_assessment_cycle_service import create_cycle, open_cycle, close_cycle
from talent_evaluation_plan_service import activate_plan, add_period, cancel_period, create_plan, validate_cycle_period_link
from talent_official_identification_service import record_decision
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, configure_kpi,
    configure_review_candidate_policy, create_competency, create_framework_draft,
    create_program, transition_program, upsert_annual_configuration, upsert_rubric,
)
from talent_review_candidate_service import evaluate_review_candidate, mark_reviewed
from talent_student_assessment_service import complete_assessment, mark_non_complete, set_competency_result, start_assessment


# ---------------------------------------------------------------------------
# Section 1: standalone suppression-engine unit tests (no DB)
# ---------------------------------------------------------------------------


class OverviewSelectivePrivacyPolicy:
    """Test-only policy for independently controlling /overview source cells."""

    privacy_policy_version = "test-overview-selective-v1"

    def __init__(self, states=None):
        self.states = states or {}

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        metric = (context or {}).get("metric")
        state = self.states.get(metric, VISIBLE)
        if state == VISIBLE:
            return PrivacyDecision(VISIBLE, value=int(raw_value))
        if state == COARSENED:
            return PrivacyDecision(COARSENED, value=0, reason_code="test_coarsened")
        return PrivacyDecision(state, reason_code=f"test_{state}")

    def prefers_coarsening(self, *, privacy_class):
        return False


def test_derived_value_helper_requires_every_source_to_be_visible():
    numerator = Cell(key=("n",), privacy_class="P5", raw_value=2, state=VISIBLE, value=2)
    denominator = Cell(key=("d",), privacy_class="P2", raw_value=10, state=VISIBLE, value=10)
    assert derive_from_visible_cells([numerator, denominator], lambda n, d: n * 100 / d) == 20

    for state in (SUPPRESSED, RESTRICTED, COARSENED, NO_DATA):
        denominator.state = state
        denominator.value = 5 if state == COARSENED else None
        assert derive_from_visible_cells([numerator, denominator], lambda n, d: n * 100 / d) is None


def test_parent_total_reconstruction_triggers_complementary_suppression():
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
    total = Cell(key=("total", "x"), privacy_class="P2", raw_value=20, depth=0)
    a = Cell(key=("child", "x", "a"), privacy_class="P2", raw_value=17, depth=1)
    b = Cell(key=("child", "x", "b"), privacy_class="P2", raw_value=3, depth=1)  # below threshold -> suppressed
    apply_primary_privacy([total, a, b], policy)
    assert (total.state, a.state, b.state) == (VISIBLE, VISIBLE, SUPPRESSED)
    group = Group(name="x", total=total, children=[a, b])
    converged = run_complementary_suppression([group], policy)
    assert converged is True
    # b was already hidden; a is the only other sibling, so a must also be hidden now
    # to break total - b reconstruction.
    assert a.state == SUPPRESSED
    assert a.value is None


def test_tie_break_is_identity_based_not_value_based():
    """Two scenarios with the same shape but different actual numbers must
    suppress the SAME identity-selected cell both times."""
    def scenario(value_a, value_b, value_c):
        policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
        total = Cell(key=("total", "g"), privacy_class="P2", raw_value=value_a + value_b + value_c, depth=0)
        a = Cell(key=("child", "g", "a"), privacy_class="P2", raw_value=value_a, depth=1)
        b = Cell(key=("child", "g", "b"), privacy_class="P2", raw_value=value_b, depth=1)
        c = Cell(key=("child", "g", "c"), privacy_class="P2", raw_value=value_c, depth=1)
        apply_primary_privacy([total, a, b, c], policy)
        group = Group(name="g", total=total, children=[a, b, c])
        run_complementary_suppression([group], policy)
        return {cell.key: cell.state for cell in (total, a, b, c)}

    # c is always below threshold (suppressed already); a and b start visible
    # and tied for eligibility - the identity tie-break (stable dimension key)
    # must pick the same one regardless of the actual magnitudes involved.
    first = scenario(value_a=9, value_b=11, value_c=1)
    second = scenario(value_a=50, value_b=6, value_c=2)
    hidden_first = {key for key, state in first.items() if state != VISIBLE}
    hidden_second = {key for key, state in second.items() if state != VISIBLE}
    assert hidden_first == hidden_second
    assert ("child", "g", "a") in hidden_first  # alphabetically-first sibling is the deterministic pick


def test_suppression_is_monotonic_and_reaches_fixed_point():
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
    total = Cell(key=("total", "y"), privacy_class="P2", raw_value=10, depth=0)
    a = Cell(key=("child", "y", "a"), privacy_class="P2", raw_value=1, depth=1)
    b = Cell(key=("child", "y", "b"), privacy_class="P2", raw_value=9, depth=1)
    apply_primary_privacy([total, a, b], policy)
    group = Group(name="y", total=total, children=[a, b])
    assert run_complementary_suppression([group], policy) is True
    # a already suppressed by primary privacy; b visible alone with total visible -> b must also hide.
    assert b.state == SUPPRESSED
    states_before = (total.state, a.state, b.state)
    # Re-running must never re-expose anything (monotonic).
    run_complementary_suppression([group], policy)
    assert (total.state, a.state, b.state) == states_before


def test_no_reconstruction_risk_when_zero_or_multiple_hidden():
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
    total = Cell(key=("total", "z"), privacy_class="P2", raw_value=30, depth=0)
    a = Cell(key=("child", "z", "a"), privacy_class="P2", raw_value=10, depth=1)
    b = Cell(key=("child", "z", "b"), privacy_class="P2", raw_value=20, depth=1)
    apply_primary_privacy([total, a, b], policy)
    group = Group(name="z", total=total, children=[a, b])
    assert run_complementary_suppression([group], policy) is True
    assert (total.state, a.state, b.state) == (VISIBLE, VISIBLE, VISIBLE)


def test_allow_all_test_policy_never_suppresses():
    policy = AllowAllTestPolicy()
    cell = Cell(key=("x",), privacy_class="P7", raw_value=1)
    apply_primary_privacy([cell], policy)
    assert cell.state == VISIBLE and cell.value == 1
    none_cell = Cell(key=("y",), privacy_class="P7", raw_value=None)
    apply_primary_privacy([none_cell], policy)
    assert none_cell.state == NO_DATA


def test_production_privacy_provider_defaults_to_none_fail_closed():
    assert resolve_privacy_policy_provider() is None


# ---------------------------------------------------------------------------
# Section 2: full DB fixture and API-level coverage
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


def grant(db, role, *keys):
    db.add_all([models.RolePermission(school_group_id=1, role=role, permission_key=key, is_allowed=True) for key in keys])
    db.commit()


def client(db, current, *, policy=None):
    app = FastAPI()
    app.include_router(analytics_router)
    app.include_router(cycle_router)
    app.include_router(plan_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    if policy is not None:
        app.dependency_overrides[resolve_privacy_policy_provider] = lambda: policy
    return TestClient(app)


def qualitative_program(db, *, group=1, year=100, grades=("1",)):
    program = create_program(db, school_group_id=group, name="Potential")
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title="Potential Framework")
    competency = create_competency(db, school_group_id=group, program_id=program.id, code="CREA", name="Creativity")
    fw_competency, framework = add_framework_competency(db, school_group_id=group, program_id=program.id, framework_id=framework.id, competency_id=competency.id, expected_revision=framework.revision)
    rubric, framework = upsert_rubric(db, school_group_id=group, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, name="Potential Rubric")
    levels = []
    for code, label in (("EMERGING", "Emerging"), ("DEVELOPING", "Developing"), ("ADVANCED", "Advanced")):
        level, framework = add_rubric_level(db, school_group_id=group, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code=code, label=label)
        levels.append(level)
    configure_review_candidate_policy(
        db, school_group_id=group, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
        is_enabled=True, match_mode="all", description="Advanced level review",
        rules=[{"rule_type": "rubric_level_at_or_above", "framework_competency_id": fw_competency.id, "rubric_level_id": levels[-1].id}],
    )
    framework = activate_framework(db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                                   expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                                   organization_authorized=True)
    config = upsert_annual_configuration(db, school_group_id=group, program_id=program.id, academic_year_id=year, is_enabled=True, eligible_grade_levels=list(grades))
    db.commit()
    return program, framework, fw_competency, rubric, levels, config


def make_student(db, *, first, branch, section, start=datetime(2026, 9, 1)):
    student = create_student(db, school_group_id=1, first_name=first, last_name="Learner")
    placement = create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100,
                                 branch_id=branch, planning_section_id=section, effective_from=start)
    return student, placement


@pytest.fixture()
def scenario(db):
    program, framework, fw_competency, rubric, levels, config = qualitative_program(db)
    emerging, developing, advanced = levels

    branch_a_students = {name: make_student(db, first=name, branch=10, section=1000) for name in ("S1", "S2", "S3", "S4", "Transfer")}
    branch_b_students = {name: make_student(db, first=name, branch=11, section=1001) for name in ("S5", "S6", "S7", "S8")}
    db.commit()

    cycle = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="Autumn Review",
                         population_effective_at=datetime(2026, 10, 1))
    db.commit()
    cycle = open_cycle(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    db.commit()

    # Move Transfer's CURRENT placement to Branch B AFTER the Cycle froze the
    # population - the frozen member must keep branch_id=10 regardless.
    transition_placement(db, school_group_id=1, student_id=branch_a_students["Transfer"][0].id,
                         placement_id=branch_a_students["Transfer"][1].id, transition_at=datetime(2026, 11, 1),
                         academic_year_id=100, branch_id=11, planning_section_id=1001)
    db.commit()

    members = {row.student_id: row for row in db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).all()}

    def _complete(student, level):
        member = members[student.id]
        assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
        _, assessment = set_competency_result(db, school_group_id=1, assessment_id=assessment.id, framework_competency_id=fw_competency.id, rubric_level_id=level.id, expected_revision=assessment.revision)
        return complete_assessment(db, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)

    a_s1 = _complete(branch_a_students["S1"][0], advanced)
    _complete(branch_a_students["S2"][0], emerging)
    start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=members[branch_a_students["S3"][0].id].id)
    incomplete_assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=members[branch_a_students["S4"][0].id].id)
    mark_non_complete(db, school_group_id=1, assessment_id=incomplete_assessment.id, expected_revision=incomplete_assessment.revision, status="incomplete")
    a_transfer = _complete(branch_a_students["Transfer"][0], advanced)
    a_s5 = _complete(branch_b_students["S5"][0], advanced)
    insufficient_assessment = start_assessment(db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=members[branch_b_students["S6"][0].id].id)
    mark_non_complete(db, school_group_id=1, assessment_id=insufficient_assessment.id, expected_revision=insufficient_assessment.revision, status="insufficient_evidence")
    # S7, S8 stay unassessed.
    db.commit()

    close_cycle(db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    db.commit()

    candidate_s1, outcome_s1 = evaluate_review_candidate(db, school_group_id=1, assessment_id=a_s1.id)
    candidate_transfer, _ = evaluate_review_candidate(db, school_group_id=1, assessment_id=a_transfer.id)
    candidate_s5, _ = evaluate_review_candidate(db, school_group_id=1, assessment_id=a_s5.id)
    db.commit()
    assert outcome_s1 == "qualified"
    mark_reviewed(db, school_group_id=1, candidate_id=candidate_s1.id)
    mark_reviewed(db, school_group_id=1, candidate_id=candidate_s5.id)
    db.commit()
    record_decision(db, school_group_id=1, review_candidate_id=candidate_s1.id, decision="identified", organization_authorized=True)
    record_decision(db, school_group_id=1, review_candidate_id=candidate_s5.id, decision="not_identified", organization_authorized=True)
    db.commit()
    # candidate_transfer stays pending_review with no Identification decision.

    # A separate ad-hoc Cycle (no Plan link) with no assessments - exercises
    # ad_hoc_cycle_count and pre-M8-style Cycle shape.
    ad_hoc = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                          framework_version_id=framework.id, title="Ad Hoc Spring Check",
                          population_effective_at=datetime(2026, 10, 1))
    db.commit()

    return {
        "program": program, "framework": framework, "fw_competency": fw_competency, "rubric": rubric,
        "levels": {"emerging": emerging, "developing": developing, "advanced": advanced},
        "cycle": cycle, "ad_hoc_cycle": ad_hoc,
        "branch_a_students": branch_a_students, "branch_b_students": branch_b_students,
        "members": members,
    }


def test_coverage_invariants_and_zero_denominator(db, scenario):
    program = scenario["program"]
    admin = user("1000000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        coverage = overview["coverage"]
        assert coverage["frozen_eligible"] == 9
        counts = coverage["counts"]
        assert counts == {"unassessed": 2, "in_progress": 1, "completed": 4, "incomplete": 1, "insufficient_evidence": 1}
        assert sum(counts.values()) == coverage["frozen_eligible"]
        assert coverage["assessment_started"] == counts["in_progress"] + counts["completed"] + counts["incomplete"] + counts["insufficient_evidence"]
        assert coverage["assessment_started"] == 7
        assert float(coverage["completion_coverage_percentage"]) == pytest.approx(44.44, abs=0.01)
        assert float(coverage["started_coverage_percentage"]) == pytest.approx(77.78, abs=0.01)

        # Zero-denominator scope (an out-of-scope grade) must be no_data, never 0%.
        empty = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview?grade=2").json()
        assert empty["coverage"] == {"state": "no_data"}


def test_historical_branch_security_survives_current_placement_transfer(db, scenario):
    program = scenario["program"]
    branch_a_actor = user("2000000001", role="Administrator", scope="BRANCH", branch=10)
    branch_b_actor = user("2000000002", role="Administrator", scope="BRANCH", branch=11)
    org_actor = user("2000000003", role="Administrator", scope="ORGANIZATION")
    db.add_all([branch_a_actor, branch_b_actor, org_actor])
    db.commit()

    with client(db, branch_a_actor, policy=AllowAllTestPolicy()) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        assert overview["coverage"]["frozen_eligible"] == 5  # S1-S4 + Transfer, still frozen at Branch A

    with client(db, branch_b_actor, policy=AllowAllTestPolicy()) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        assert overview["coverage"]["frozen_eligible"] == 4  # S5-S8 only - Transfer's CURRENT branch does not leak in

    with client(db, org_actor, policy=AllowAllTestPolicy()) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        assert overview["coverage"]["frozen_eligible"] == 9


def test_tenant_isolation_foreign_program_and_filters(db, scenario):
    program = scenario["program"]
    admin = user("3000000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        foreign_program = api.get("/api/talent/analytics/programs/999999/academic-years/100/overview")
        assert foreign_program.status_code == 404 and foreign_program.json()["code"] == "not_found"

        nonexistent_program = api.get("/api/talent/analytics/programs/424242/academic-years/100/overview")
        assert nonexistent_program.status_code == 404
        assert nonexistent_program.json() == foreign_program.json()

        crafted_branch = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview?branch_id=20")
        assert crafted_branch.status_code == 400 and crafted_branch.json()["code"] == "invalid_filter"

        # Authorized same-tenant analytics are unaffected by the foreign-ID probing above.
        authorized = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview")
        assert authorized.status_code == 200 and authorized.json()["coverage"]["frozen_eligible"] == 9


@pytest.mark.parametrize("grant_candidate,grant_identification", [(False, False), (True, False), (False, True), (True, True)])
def test_candidate_identification_zero_leakage_matrix(db, scenario, grant_candidate, grant_identification):
    program = scenario["program"]
    keys = ["talent_analytics.view", "talent_analytics.view_students"]
    if grant_candidate:
        keys.append("talent_review_candidates.view")
    if grant_identification:
        keys.append("talent_official_identifications.view")
    grant(db, "Editor", *keys)
    actor = user("4000000001", role="Editor")
    db.add(actor)
    db.commit()
    with client(db, actor, policy=AllowAllTestPolicy()) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        assert ("candidate" in overview) is grant_candidate
        assert ("identification" in overview) is grant_identification
        if grant_candidate:
            assert overview["candidate"]["candidate_count"] == 3
        if grant_identification:
            assert overview["identification"]["identified_count"] == 1
            assert overview["identification"]["not_identified_count"] == 1

        ctx = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/context").json()
        assert (ctx["filters"]["candidate_states"] is not None) is grant_candidate
        assert (ctx["filters"]["identification_states"] is not None) is grant_identification

        students = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/students").json()
        for item in students["items"]:
            assert ("candidate_state" in item) is grant_candidate
            assert ("identification_state" in item) is grant_identification


def test_privacy_states_visible_suppressed_no_data_and_fail_closed(db, scenario):
    program = scenario["program"]
    admin = user("5000000001")
    db.add(admin)
    db.commit()

    with client(db, admin) as api:  # no policy override at all -> production default (None) -> fail closed
        response = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview")
        assert response.status_code == 500 and response.json()["code"] == "analytics_query_failed"
        assert "threshold" not in response.text.lower()

    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=6)) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        # The headline is visible, but every independently disclosed status
        # count is below threshold. The compound bundle therefore fails
        # closed instead of using a visible total to unlock hidden children.
        assert overview["coverage"] == {"state": "suppressed"}

    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=50)) as api:
        overview = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        assert overview["coverage"] == {"state": "suppressed"}
        assert any(item["code"] == "value_suppressed_for_privacy" for item in overview["insights"])


def test_overview_candidate_percentages_require_visible_denominators(db, scenario):
    program = scenario["program"]
    admin = user("5000000011")
    db.add(admin)
    db.commit()

    with client(db, admin, policy=OverviewSelectivePrivacyPolicy({"frozen_eligible": SUPPRESSED})) as api:
        candidate = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview"
        ).json()["candidate"]
        assert candidate["candidate_count"] == 3
        assert candidate["candidate_of_eligible_percentage"] is None

    with client(db, admin, policy=OverviewSelectivePrivacyPolicy({"completed": SUPPRESSED})) as api:
        candidate = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview"
        ).json()["candidate"]
        assert candidate["candidate_count"] == 3
        assert float(candidate["candidate_of_eligible_percentage"]) == pytest.approx(33.33, abs=0.01)
        assert candidate["candidate_of_completed_percentage"] is None

    with client(db, admin, policy=OverviewSelectivePrivacyPolicy()) as api:
        candidate = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview"
        ).json()["candidate"]
        assert float(candidate["candidate_of_eligible_percentage"]) == pytest.approx(33.33, abs=0.01)
        assert float(candidate["candidate_of_completed_percentage"]) == pytest.approx(75.0, abs=0.01)


@pytest.mark.parametrize("hidden_component", ["identified_count", "not_identified_count"])
def test_overview_identification_split_uses_primary_and_complementary_privacy(
    db, scenario, hidden_component,
):
    program = scenario["program"]
    admin = user(f"500000002{1 if hidden_component == 'identified_count' else 2}")
    db.add(admin)
    db.commit()
    policy = OverviewSelectivePrivacyPolicy({hidden_component: SUPPRESSED})

    with client(db, admin, policy=policy) as api:
        identification = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview"
        ).json()["identification"]
        assert identification == {"state": SUPPRESSED}
        assert "identified_count" not in identification
        assert "not_identified_count" not in identification
        assert "identified_of_eligible_candidates_percentage" not in identification


def test_overview_identification_percentage_requires_visible_candidate_denominator(db, scenario):
    program = scenario["program"]
    admin = user("5000000031")
    db.add(admin)
    db.commit()
    policy = OverviewSelectivePrivacyPolicy({"candidate_count": RESTRICTED})

    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview"
        ).json()
        assert body["candidate"] == {"state": RESTRICTED}
        assert body["identification"]["identified_count"] == 1
        assert body["identification"]["identified_of_eligible_candidates_percentage"] is None


@pytest.mark.parametrize("source_state", [COARSENED, RESTRICTED])
def test_overview_nonvisible_source_never_produces_exact_percentage(db, scenario, source_state):
    program = scenario["program"]
    admin = user(f"500000004{1 if source_state == COARSENED else 2}")
    db.add(admin)
    db.commit()
    policy = OverviewSelectivePrivacyPolicy({"completed": source_state})

    with client(db, admin, policy=policy) as api:
        candidate = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview"
        ).json()["candidate"]
        assert candidate["candidate_of_completed_percentage"] is None


def test_overview_zero_is_visible_only_when_policy_allows(db, scenario):
    program = scenario["program"]
    admin = user("5000000051")
    db.add(admin)
    db.commit()
    url = f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview?branch_id=10"

    with client(db, admin, policy=OverviewSelectivePrivacyPolicy()) as api:
        identification = api.get(url).json()["identification"]
        assert identification["not_identified_count"] == 0

    with client(db, admin, policy=OverviewSelectivePrivacyPolicy({"not_identified_count": SUPPRESSED})) as api:
        identification = api.get(url).json()["identification"]
        assert identification == {"state": SUPPRESSED}
        assert "not_identified_count" not in identification


def test_kpi_r1_minimal_contract(db):
    engine_db = db
    program = create_program(engine_db, school_group_id=1, name="KPI Potential")
    transition_program(engine_db, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(engine_db, school_group_id=1, program_id=program.id, title="KPI Framework")
    competency = create_competency(engine_db, school_group_id=1, program_id=program.id, code="NUM", name="Numeracy")
    fw_competency, framework = add_framework_competency(engine_db, school_group_id=1, program_id=program.id, framework_id=framework.id, competency_id=competency.id, expected_revision=framework.revision)
    rubric, framework = upsert_rubric(engine_db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, name="KPI Rubric")
    low, framework = add_rubric_level(engine_db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code="LOW", label="Low", numeric_value=0)
    high, framework = add_rubric_level(engine_db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision, code="HIGH", label="High", numeric_value=2)
    configure_kpi(engine_db, school_group_id=1, program_id=program.id, framework_id=framework.id, expected_revision=framework.revision,
                 is_enabled=True, result_scale_min=0, result_scale_max=2, interpretation="Weighted mean",
                 components=[{"framework_competency_id": fw_competency.id, "weight_basis_points": 10000}])
    framework = activate_framework(engine_db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                                   expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                                   organization_authorized=True)
    upsert_annual_configuration(engine_db, school_group_id=1, program_id=program.id, academic_year_id=100, is_enabled=True, eligible_grade_levels=["1"])
    engine_db.commit()

    zero_student, _ = make_student(engine_db, first="Zero", branch=10, section=1000)
    high_student, _ = make_student(engine_db, first="High", branch=10, section=1000)
    engine_db.commit()
    cycle = create_cycle(engine_db, school_group_id=1, program_id=program.id, academic_year_id=100,
                         framework_version_id=framework.id, title="KPI Cycle", population_effective_at=datetime(2026, 10, 1))
    engine_db.commit()
    cycle = open_cycle(engine_db, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision, organization_authorized=True)
    engine_db.commit()
    members = {row.student_id: row for row in engine_db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).all()}

    def _complete(student_id, level):
        member = members[student_id]
        assessment = start_assessment(engine_db, school_group_id=1, cycle_id=cycle.id, cycle_population_member_id=member.id)
        _, assessment = set_competency_result(engine_db, school_group_id=1, assessment_id=assessment.id, framework_competency_id=fw_competency.id, rubric_level_id=level.id, expected_revision=assessment.revision)
        return complete_assessment(engine_db, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision)

    zero_assessment = _complete(zero_student.id, low)
    _complete(high_student.id, high)
    engine_db.commit()
    assert zero_assessment.kpi_result == 0  # a valid KPI result of exactly 0 counts as valid, not missing

    admin = user("6000000001")
    engine_db.add(admin)
    engine_db.commit()
    with client(engine_db, admin, policy=AllowAllTestPolicy()) as api:
        result = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/kpi-distribution?framework_version_id={framework.id}").json()
        assert result["distribution_mode"] == "unavailable"
        assert result["reason_code"] == "numeric_binning_rule_unapproved"
        assert result["valid_result_count"]["value"] == 2  # both completed results counted, including the zero
        for banned in ("mean", "median", "percentile", "bins", "numeric_bins"):
            assert banned not in result


def test_comparability_framework_changed_and_side_by_side(db, scenario):
    program = scenario["program"]
    framework_v1 = scenario["framework"]
    ad_hoc = scenario["ad_hoc_cycle"]
    admin = user("7000000001")
    db.add(admin)
    db.commit()

    # Second Framework Version (supersedes V1) with its own separate cycle.
    framework_v2 = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Potential Framework V2",
                                          supersedes_framework_version_id=framework_v1.id)
    competency2 = create_competency(db, school_group_id=1, program_id=program.id, code="CREA2", name="Creativity 2")
    fw_competency2, framework_v2 = add_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework_v2.id, competency_id=competency2.id, expected_revision=framework_v2.revision)
    upsert_rubric(db, school_group_id=1, program_id=program.id, framework_id=framework_v2.id, expected_revision=framework_v2.revision, name="Potential Rubric V2")
    framework_v2 = activate_framework(db, school_group_id=1, program_id=program.id, framework_id=framework_v2.id,
                                      expected_revision=framework_v2.revision, expected_fingerprint=framework_v2.semantic_fingerprint,
                                      organization_authorized=True)
    db.commit()

    cycle_v2 = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                            framework_version_id=framework_v2.id, title="Spring Review V2", population_effective_at=datetime(2026, 10, 1))
    db.commit()
    cycle_v2 = open_cycle(db, school_group_id=1, cycle_id=cycle_v2.id, expected_revision=cycle_v2.revision, organization_authorized=True)
    db.commit()

    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        comparison = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={scenario['cycle'].id}&right_cycle_id={cycle_v2.id}"
        ).json()
        assert comparison["analysis_mode"] == "full_period_populations"
        assert comparison["comparisons"]["rubric"] == {"state": "not_comparable", "reason_code": "framework_changed"}
        assert comparison["comparisons"]["kpi"] == {"state": "not_comparable", "reason_code": "framework_changed"}
        # Factual standalone coverage remains independently visible on both sides.
        assert comparison["left"]["coverage"]["frozen_eligible"] == 9
        assert "improvement" not in comparison and "growth" not in comparison

        same_side = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={scenario['cycle'].id}&right_cycle_id={scenario['cycle'].id}"
        ).json()
        assert same_side["comparisons"]["rubric"]["state"] == "comparable"


def test_fingerprint_is_not_a_freshness_proof(db, scenario):
    program = scenario["program"]
    admin = user("8000000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        first = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/context").json()

    # Mutate underlying data (a completed Assessment's status) with no change
    # to any request parameter or privacy policy version.
    assessment = db.query(models.TalentStudentAssessment).filter_by(school_group_id=1, status="completed").first()
    assessment.kpi_result = 999
    db.commit()

    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        second = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/context").json()
    assert first["request_context_fingerprint"] == second["request_context_fingerprint"]

    with client(db, admin, policy=AllowAllTestPolicy(version="test-allow-all-v2")) as api:
        third = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/context").json()
    assert third["request_context_fingerprint"] != first["request_context_fingerprint"]


def test_query_count_does_not_grow_with_branch_or_student_count(db, scenario):
    from sqlalchemy import event as sa_event

    program = scenario["program"]
    admin = user("9000000001")
    db.add(admin)
    db.commit()

    counter = {"n": 0}

    def _count(*args, **kwargs):
        counter["n"] += 1

    engine = db.get_bind()
    url = f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/branch"

    # Warm the (per-actor, in-process) permission cache with an uncounted call
    # first so both measured phases start from the same steady state - the
    # baseline being asserted is query count vs. ROW/DIMENSION count, not
    # first-request-ever permission resolution.
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        api.get(url)

    sa_event.listen(engine, "before_cursor_execute", _count)
    try:
        with client(db, admin, policy=AllowAllTestPolicy()) as api:
            api.get(url)
        small_count = counter["n"]
    finally:
        sa_event.remove(engine, "before_cursor_execute", _count)

    # Add a third Branch with three more Students/placements (larger dataset).
    db.add(models.Branch(id=12, school_group_id=1, name="Branch C"))
    db.add(models.PlanningSection(id=1002, branch_id=12, academic_year_id=100, grade_level="1", section_name="Gamma", class_status="Current"))
    db.commit()
    for name in ("S9", "S10", "S11"):
        make_student(db, first=name, branch=12, section=1002)
    db.commit()

    counter["n"] = 0
    sa_event.listen(engine, "before_cursor_execute", _count)
    try:
        with client(db, admin, policy=AllowAllTestPolicy()) as api:
            api.get(url)
        large_count = counter["n"]
    finally:
        sa_event.remove(engine, "before_cursor_execute", _count)

    # Query count must not grow proportionally with Student/Branch/row count -
    # a per-row or per-dimension loop would add several statements per added
    # Student/Branch here; at most one incidental statement of slack is
    # tolerated for warm-cache/session bookkeeping noise.
    assert large_count - small_count <= 1, (small_count, large_count)


def test_student_drill_pagination_and_restriction(db, scenario):
    program = scenario["program"]
    admin = user("1100000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        page = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/students?limit=5&offset=0").json()
        assert "total_count" not in page
        assert page["pagination"] == {"limit": 5, "offset": 0, "has_more": True}
        assert len(page["items"]) == 5
        rest = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/students?limit=5&offset=5").json()
        assert rest["pagination"]["has_more"] is False
        assert len(rest["items"]) == 4

    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=50)) as api:
        restricted = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/students")
        assert restricted.status_code == 403
        assert restricted.json()["code"] == "analytics_drill_restricted"
        assert "9" not in restricted.text  # no cohort size disclosed


def test_analytics_only_actor_cannot_escalate_to_raw_talent_apis(db, scenario):
    program = scenario["program"]
    cycle = scenario["cycle"]
    grant(db, "Editor", "talent_analytics.view", "talent_analytics.view_students")
    actor = user("1200000001", role="Editor")
    db.add(actor)
    db.commit()
    with client(db, actor, policy=AllowAllTestPolicy()) as api:
        # Bounded aggregate Cycle projection is denied entirely without Cycle-view.
        ctx = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/context").json()
        assert ctx["cycles"] is None

        denied_plan = api.get("/api/talent/evaluation-plans")
        assert denied_plan.status_code == 403
        denied_cycle = api.get(f"/api/talent/assessment-cycles/{cycle.id}")
        assert denied_cycle.status_code == 403


def test_administrator_gets_analytics_permissions_by_default_editor_does_not(db):
    import auth
    admin = user("1300000001")
    editor = user("1300000002", role="Editor")
    db.add_all([admin, editor])
    db.commit()
    assert auth.has_permission(db, admin, "talent_analytics.view") is True
    assert auth.has_permission(db, admin, "talent_analytics.view_students") is True
    assert auth.has_permission(db, editor, "talent_analytics.view") is False


# ---------------------------------------------------------------------------
# M9 remediation: BLOCKER fix - primary privacy evaluation on group-based
# routes (rubric-distribution, competencies, breakdowns), Section D/E.
# ---------------------------------------------------------------------------


def test_rubric_distribution_visible_under_allow_all_previously_crashed(db, scenario):
    """This exact request raised an unhandled 500 TypeError before the
    remediation fix: apply_primary_privacy was never called before
    run_complementary_suppression on this route, so every child Cell reached
    svc.percentage(cell.value=None, total_raw=<real int>) -> `Decimal(None)`.
    """
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2100000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        response = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution")
        assert response.status_code == 200
        body = response.json()
        dist = next(d for d in body["distributions"] if d["framework_version_id"] == framework.id)
        assert dist["valid_result_count"] == {"state": "visible", "value": 4}
        levels_by_code = {lvl["code"]: lvl for lvl in dist["levels"]}
        assert levels_by_code["ADVANCED"]["state"] == "visible"
        assert levels_by_code["ADVANCED"]["count"] == 3
        assert float(levels_by_code["ADVANCED"]["percentage"]) == pytest.approx(75.0)
        assert levels_by_code["EMERGING"]["count"] == 1
        # A genuine zero count is a real, visible zero - never suppressed/no_data.
        assert levels_by_code["DEVELOPING"]["count"] == 0
        assert levels_by_code["DEVELOPING"]["state"] == "visible"


def test_rubric_distribution_suppressed_under_deterministic_policy(db, scenario):
    program = scenario["program"]
    admin = user("2100000002")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=2)) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution").json()
        dist = body["distributions"][0]
        levels_by_code = {lvl["code"]: lvl for lvl in dist["levels"]}
        assert levels_by_code["EMERGING"]["state"] == "suppressed"
        assert levels_by_code["EMERGING"]["count"] is None
        assert levels_by_code["EMERGING"]["percentage"] is None
        assert levels_by_code["DEVELOPING"]["state"] == "suppressed"  # raw 0 < 2
        assert levels_by_code["ADVANCED"]["state"] == "visible"
        assert levels_by_code["ADVANCED"]["count"] == 3
        assert dist["valid_result_count"] == {"state": "visible", "value": 4}


def test_competencies_visible_under_allow_all_asserts_body(db, scenario):
    """Asserts response body content (counts/percentages), not just query
    count - the prior test only checked query count, which is exactly the
    gap that let the missing apply_primary_privacy call through undetected.
    """
    program = scenario["program"]
    framework = scenario["framework"]
    fw_competency = scenario["fw_competency"]
    admin = user("2200000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies?framework_version_id={framework.id}"
        ).json()
        assert len(body["competencies"]) == 1
        comp = body["competencies"][0]
        assert comp["framework_competency_id"] == fw_competency.id
        assert comp["valid_result_count"] == {"state": "visible", "value": 4}
        levels_by_code = {lvl["code"]: lvl for lvl in comp["levels"]}
        assert levels_by_code["ADVANCED"]["state"] == "visible"
        assert levels_by_code["ADVANCED"]["count"] == 3
        assert float(levels_by_code["ADVANCED"]["percentage"]) == pytest.approx(75.0)
        assert levels_by_code["DEVELOPING"]["count"] == 0
        assert levels_by_code["DEVELOPING"]["state"] == "visible"


def test_competencies_suppressed_under_deterministic_policy_no_raw_leak(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2200000002")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=2)) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies?framework_version_id={framework.id}"
        ).json()
        comp = body["competencies"][0]
        levels_by_code = {lvl["code"]: lvl for lvl in comp["levels"]}
        assert levels_by_code["EMERGING"]["state"] == "suppressed" and levels_by_code["EMERGING"]["count"] is None
        assert levels_by_code["DEVELOPING"]["state"] == "suppressed" and levels_by_code["DEVELOPING"]["count"] is None
        assert levels_by_code["ADVANCED"]["state"] == "visible" and levels_by_code["ADVANCED"]["count"] == 3


def test_breakdowns_branch_visible_and_suppressed(db, scenario):
    program = scenario["program"]
    admin = user("2300000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/branch").json()
        rows_by_branch = {row["dimension_value"]: row for row in body["rows"]}
        assert rows_by_branch[10]["frozen_eligible"] == {"state": "visible", "value": 5}
        assert rows_by_branch[10]["completed"] == {"state": "visible", "value": 3}
        assert rows_by_branch[10]["candidate"] == {"state": "visible", "value": 2}
        assert rows_by_branch[10]["identified"] == {"state": "visible", "value": 1}
        assert rows_by_branch[11]["frozen_eligible"] == {"state": "visible", "value": 4}
        assert rows_by_branch[11]["identified"] == {"state": "visible", "value": 0}
        assert body["totals"]["frozen_eligible"] == {"state": "visible", "value": 9}
        assert body["totals"]["completed"] == {"state": "visible", "value": 4}
        assert body["totals"]["candidate"] == {"state": "visible", "value": 3}
        assert body["totals"]["identified"] == {"state": "visible", "value": 1}

    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=6)) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/branch").json()
        assert body["totals"]["frozen_eligible"] == {"state": "visible", "value": 9}
        assert body["totals"]["completed"] == {"state": "suppressed", "value": None}
        assert body["totals"]["candidate"] == {"state": "suppressed", "value": None}
        assert body["totals"]["identified"] == {"state": "suppressed", "value": None}
        for row in body["rows"]:
            assert row["frozen_eligible"]["state"] == "suppressed" and row["frozen_eligible"]["value"] is None
            assert row["completed"]["state"] == "suppressed" and row["completed"]["value"] is None
            assert row["candidate"]["state"] == "suppressed" and row["candidate"]["value"] is None
            assert row["identified"]["state"] == "suppressed" and row["identified"]["value"] is None


def test_breakdowns_grade_visible_and_suppressed(db, scenario):
    program = scenario["program"]
    admin = user("2300000002")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/grade").json()
        assert len(body["rows"]) == 1
        row = body["rows"][0]
        assert row["dimension_value"] == "1"
        assert row["frozen_eligible"] == {"state": "visible", "value": 9}
        assert row["completed"] == {"state": "visible", "value": 4}

    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=50)) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/grade").json()
        row = body["rows"][0]
        assert row["frozen_eligible"]["state"] == "suppressed"
        assert row["frozen_eligible"]["value"] is None


def test_breakdowns_section_visible_and_suppressed(db, scenario):
    program = scenario["program"]
    admin = user("2300000003")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/section").json()
        rows_by_section = {row["dimension_value"]: row for row in body["rows"]}
        assert rows_by_section[1000]["section_name"] == "Alpha"
        assert rows_by_section[1000]["frozen_eligible"] == {"state": "visible", "value": 5}
        assert rows_by_section[1001]["section_name"] == "Beta"
        assert rows_by_section[1001]["frozen_eligible"] == {"state": "visible", "value": 4}

    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=6)) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/section").json()
        for row in body["rows"]:
            assert row["frozen_eligible"]["state"] == "suppressed"
            assert row["frozen_eligible"]["value"] is None


# ---------------------------------------------------------------------------
# M9 remediation: Section G/H - COARSENED semantics (Product Owner decision).
# ---------------------------------------------------------------------------


def test_coarsened_with_explicit_safe_replacement_is_published():
    policy = CoarsenWithReplacementTestPolicy(minimum_cohort=5, replacement_value=0)
    cell = Cell(key=("x",), privacy_class="P2", raw_value=3)
    apply_primary_privacy([cell], policy)
    assert cell.state == COARSENED
    assert cell.value == 0
    assert cell.reason_code == "below_minimum_cohort_coarsened"


def test_coarsened_without_replacement_fails_closed_to_suppressed():
    policy = CoarsenWithoutReplacementTestPolicy(minimum_cohort=5)
    cell = Cell(key=("x",), privacy_class="P2", raw_value=3)
    apply_primary_privacy([cell], policy)
    # The policy REQUESTED coarsened but supplied no usable safe replacement -
    # this must never be serialized as coarsened+null as if coarsening
    # actually happened; it fails closed to suppressed instead.
    assert cell.state == SUPPRESSED
    assert cell.value is None
    # The policy's own reason_code is preserved when it supplies one; the
    # generic "coarsening_replacement_unavailable" fallback only applies when
    # the policy gives no reason_code at all (see the next assertion).
    assert cell.reason_code == "below_minimum_cohort_no_replacement"

    fallback_policy = CoarsenWithoutReplacementTestPolicy.__new__(CoarsenWithoutReplacementTestPolicy)
    fallback_policy.minimum_cohort = 5
    fallback_policy.privacy_policy_version = "test-coarsen-without-replacement-no-reason-v1"
    fallback_policy.evaluate_cell = lambda *, privacy_class, raw_value, denominator=None, context=None: (
        PrivacyDecision(COARSENED) if raw_value is not None and raw_value < 5 else PrivacyDecision(VISIBLE, value=raw_value)
    )
    fallback_cell = Cell(key=("y",), privacy_class="P2", raw_value=3)
    apply_primary_privacy([fallback_cell], fallback_policy)
    assert fallback_cell.state == SUPPRESSED
    assert fallback_cell.value is None
    assert fallback_cell.reason_code == "coarsening_replacement_unavailable"


def test_coarsened_replacement_cannot_leak_original_raw_value():
    import talent_analytics_service as svc

    policy = CoarsenWithReplacementTestPolicy(minimum_cohort=5, replacement_value=0)
    cell = Cell(key=("x",), privacy_class="P2", raw_value=3)
    apply_primary_privacy([cell], policy)
    assert cell.value == 0
    assert cell.value != cell.raw_value  # published value is the safe replacement, never the true 3
    payload = svc.cell_payload(cell)
    assert payload == {"state": COARSENED, "value": 0}


def test_complementary_suppression_never_reexposes_coarsened_children():
    policy = CoarsenWithReplacementTestPolicy(minimum_cohort=5, replacement_value=0)
    total = Cell(key=("total", "g"), privacy_class="P2", raw_value=20, depth=0)
    a = Cell(key=("child", "g", "a"), privacy_class="P2", raw_value=17, depth=1)
    b = Cell(key=("child", "g", "b"), privacy_class="P2", raw_value=3, depth=1)  # below threshold -> coarsened
    apply_primary_privacy([total, a, b], policy)
    assert b.state == COARSENED and b.value == 0
    group = Group(name="g", total=total, children=[a, b])
    converged = run_complementary_suppression([group], policy)
    assert converged is True
    # b (coarsened, with its safe replacement) must never be re-exposed,
    # overwritten, or turned into a second fake coarsened+null cell.
    assert b.state == COARSENED and b.value == 0
    # a is the only remaining visible sibling once b counts as hidden, so it
    # must be suppressed to break total-b reconstruction - as plain
    # suppressed, never as an invented second coarsened cell (Section G).
    assert a.state == SUPPRESSED and a.value is None
    # Re-running must remain stable (monotonic, no re-exposure on repeat).
    run_complementary_suppression([group], policy)
    assert b.state == COARSENED and b.value == 0
    assert a.state == SUPPRESSED and a.value is None


def test_breakdown_route_end_to_end_coarsened_replacement_and_no_reexposure(db, scenario):
    program = scenario["program"]
    admin = user("2300000004")
    db.add(admin)
    db.commit()
    policy = CoarsenWithReplacementTestPolicy(minimum_cohort=5, replacement_value=2)
    with client(db, admin, policy=policy) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/breakdowns/branch").json()
        rows_by_branch = {row["dimension_value"]: row for row in body["rows"]}
        # Branch 11's raw frozen_eligible count is 4 (< minimum_cohort=5) -
        # the provider supplies an explicit safe replacement (2) rather than
        # a generic bucket-merge; the response publishes ONLY that
        # replacement, never the real 4.
        assert rows_by_branch[11]["frozen_eligible"] == {"state": "coarsened", "value": 2}
        # Branch 10's raw count (5) meets the threshold and starts visible,
        # but becomes the only other sibling once branch 11 counts as hidden -
        # complementary suppression must hide it too, WITHOUT fabricating a
        # second coarsened+null cell (Section G): it becomes suppressed.
        assert rows_by_branch[10]["frozen_eligible"] == {"state": "suppressed", "value": None}
        published_values = {rows_by_branch[10]["frozen_eligible"]["value"], rows_by_branch[11]["frozen_eligible"]["value"]}
        assert 4 not in published_values and 5 not in published_values
        assert body["totals"]["frozen_eligible"] == {"state": "visible", "value": 9}


# ---------------------------------------------------------------------------
# M9 remediation: Section I - complementary-suppression regression guard.
# ---------------------------------------------------------------------------


def test_regression_guard_every_complementary_suppression_call_has_preceding_primary_privacy():
    """Structural regression guard for the exact BLOCKER fixed in this pass:
    every run_complementary_suppression(...) call site in the analytics
    router must be preceded, within the same function, by at least one
    apply_primary_privacy(...) call. Cell defaults to
    state=visible/value=None, so a Group whose cells skip primary privacy
    evaluation trivially "converges" as all-visible with no real policy
    decision ever made - this is exactly what caused the original
    rubric-distribution 500 and the competencies/breakdowns silent
    all-null-but-"visible" leak.
    """
    import ast
    import inspect

    import routers.talent_analytics as router_module

    source = inspect.getsource(router_module)
    tree = ast.parse(source)
    checked_functions = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        call_names_and_lines = [
            (child.func.id, child.lineno)
            for child in ast.walk(node)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        ]
        suppression_lines = [line for name, line in call_names_and_lines if name == "run_complementary_suppression"]
        if not suppression_lines:
            continue
        checked_functions += 1
        primary_lines = [line for name, line in call_names_and_lines if name == "apply_primary_privacy"]
        for suppression_line in suppression_lines:
            assert any(primary_line < suppression_line for primary_line in primary_lines), (
                f"{node.name} calls run_complementary_suppression at line {suppression_line} "
                "with no preceding apply_primary_privacy call in the same function - this is "
                "exactly the BLOCKER regression this test guards against."
            )
    # Sanity: this must exercise /overview plus all three distribution routes
    # (rubric-distribution, competencies, breakdowns), never silently match nothing.
    assert checked_functions == 4


# ---------------------------------------------------------------------------
# M9 remediation: Section F - competency_id filter real enforcement.
# ---------------------------------------------------------------------------


def test_competency_id_filter_no_filter_returns_all(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2400000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies?framework_version_id={framework.id}"
        ).json()
        assert len(body["competencies"]) == 1  # only Creativity exists on this framework


def test_competency_id_filter_narrows_to_one(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    fw_competency = scenario["fw_competency"]
    admin = user("2400000002")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies"
            f"?framework_version_id={framework.id}&competency_id={fw_competency.id}"
        ).json()
        assert len(body["competencies"]) == 1
        assert body["competencies"][0]["framework_competency_id"] == fw_competency.id


def test_competency_id_filter_foreign_competency_rejected(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    _, _, foreign_fw_competency, *_ = qualitative_program(db, group=2, year=200, grades=("1",))
    admin = user("2400000003")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        response = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies"
            f"?framework_version_id={framework.id}&competency_id={foreign_fw_competency.id}"
        )
        assert response.status_code == 400 and response.json()["code"] == "invalid_filter"


def test_competency_id_filter_wrong_framework_context_rejected(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    framework_v2 = create_framework_draft(
        db, school_group_id=1, program_id=program.id, title="Other Framework", supersedes_framework_version_id=framework.id
    )
    competency2 = create_competency(db, school_group_id=1, program_id=program.id, code="OTHERX", name="Other")
    fw_competency2, framework_v2 = add_framework_competency(
        db, school_group_id=1, program_id=program.id, framework_id=framework_v2.id, competency_id=competency2.id,
        expected_revision=framework_v2.revision,
    )
    upsert_rubric(db, school_group_id=1, program_id=program.id, framework_id=framework_v2.id,
                  expected_revision=framework_v2.revision, name="Other Rubric")
    framework_v2 = activate_framework(
        db, school_group_id=1, program_id=program.id, framework_id=framework_v2.id,
        expected_revision=framework_v2.revision, expected_fingerprint=framework_v2.semantic_fingerprint,
        organization_authorized=True,
    )
    db.commit()
    admin = user("2400000004")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        # framework_version_id resolves to the ORIGINAL (valid) framework;
        # competency_id belongs to a DIFFERENT framework in the same tenant/
        # Program - must be rejected, not silently ignored or cross-matched.
        response = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies"
            f"?framework_version_id={framework.id}&competency_id={fw_competency2.id}"
        )
        assert response.status_code == 400 and response.json()["code"] == "invalid_filter"


def test_competency_id_filter_query_count_does_not_grow(db, scenario):
    from sqlalchemy import event as sa_event

    program = scenario["program"]
    framework = scenario["framework"]
    fw_competency = scenario["fw_competency"]
    admin = user("2400000005")
    db.add(admin)
    db.commit()

    counter = {"n": 0}

    def _count(*args, **kwargs):
        counter["n"] += 1

    engine = db.get_bind()
    url = (
        f"/api/talent/analytics/programs/{program.id}/academic-years/100/competencies"
        f"?framework_version_id={framework.id}&competency_id={fw_competency.id}"
    )
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        api.get(url)  # warm the permission cache first, matching the existing methodology

    sa_event.listen(engine, "before_cursor_execute", _count)
    try:
        with client(db, admin, policy=AllowAllTestPolicy()) as api:
            api.get(url)
        small_count = counter["n"]
    finally:
        sa_event.remove(engine, "before_cursor_execute", _count)

    db.add(models.Branch(id=13, school_group_id=1, name="Branch D"))
    db.add(models.PlanningSection(id=1003, branch_id=13, academic_year_id=100, grade_level="1", section_name="Delta", class_status="Current"))
    db.commit()
    for name in ("S20", "S21", "S22"):
        make_student(db, first=name, branch=13, section=1003)
    db.commit()

    counter["n"] = 0
    sa_event.listen(engine, "before_cursor_execute", _count)
    try:
        with client(db, admin, policy=AllowAllTestPolicy()) as api:
            api.get(url)
        large_count = counter["n"]
    finally:
        sa_event.remove(engine, "before_cursor_execute", _count)

    assert large_count - small_count <= 1, (small_count, large_count)


# ---------------------------------------------------------------------------
# M9 remediation: Section J - comparability reason-code coverage gaps.
# ---------------------------------------------------------------------------


def test_comparability_missing_cycle(db, scenario):
    program = scenario["program"]
    config = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        school_group_id=1, program_id=program.id, academic_year_id=100,
    ).one()
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    db.commit()
    plan, period = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Unlinked Period")
    db.commit()
    admin = user("2500000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_period_id={period.id}&right_cycle_id={scenario['cycle'].id}"
        ).json()
        assert body["left"]["coverage"] == {"state": "no_data"}
        assert body["left"]["reason_code"] == "missing_cycle"
        assert body["comparisons"]["rubric"] == {"state": "not_comparable", "reason_code": "missing_cycle"}


def test_comparability_no_frozen_population(db, scenario):
    program = scenario["program"]
    admin = user("2500000002")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={scenario['ad_hoc_cycle'].id}&right_cycle_id={scenario['cycle'].id}"
        ).json()
        assert body["left"]["coverage"] == {"state": "no_data"}
        assert body["left"]["reason_code"] == "no_frozen_population"
        assert body["comparisons"]["coverage"] == {"state": "not_comparable", "reason_code": "no_frozen_population"}


def test_comparability_metric_unavailable_when_kpi_not_configured(db, scenario):
    program = scenario["program"]
    admin = user("2500000003")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={scenario['cycle'].id}&right_cycle_id={scenario['cycle'].id}"
        ).json()
        assert body["comparisons"]["rubric"]["state"] == "comparable"
        # The scenario's qualitative Framework never configures KPI - the
        # rubric side stays comparable while KPI is independently and
        # explicitly reported unavailable, never silently defaulted.
        assert body["comparisons"]["kpi"] == {"state": "not_comparable", "reason_code": "metric_unavailable"}


def test_comparability_candidate_policy_changed_is_unreachable_same_framework(db, scenario):
    """``candidate_policy_changed`` requires the two comparison sides to
    disagree on Review Candidate Policy enablement while already sharing an
    identical ``framework_version_id`` (``_outcome_state`` requires the same
    framework on both sides to ever reach "comparable"). A Framework
    Version's Review Candidate Policy is immutable once Active (M3
    governance), so two same-framework Cycles always see an identical
    ``is_enabled`` policy row set - this branch is dead/unreachable under the
    current R1 data model. This test documents that finding empirically
    rather than manufacturing a new code path solely to exercise it
    (Section J instructs against inventing reachability for aspirational
    codes)."""
    program = scenario["program"]
    admin = user("2500000004")
    db.add(admin)
    db.commit()
    second_cycle = create_cycle(
        db, school_group_id=1, program_id=program.id, academic_year_id=100,
        framework_version_id=scenario["framework"].id, title="Second Same-Framework Cycle",
        population_effective_at=datetime(2026, 10, 1),
    )
    db.commit()
    second_cycle = open_cycle(db, school_group_id=1, cycle_id=second_cycle.id, expected_revision=second_cycle.revision, organization_authorized=True)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={scenario['cycle'].id}&right_cycle_id={second_cycle.id}"
        ).json()
        assert body["comparisons"]["candidate"]["reason_code"] != "candidate_policy_changed"


# ---------------------------------------------------------------------------
# M9 coverage-privacy remediation (pass 4 -> pass 5): a route privacy-
# evaluating only the frozen_eligible headline Cell and then publishing the
# full raw svc.coverage_metrics() per-status bundle is the same reconstruction-
# risk bug class as the pass-3 BLOCKER, relocated to /rubric-distribution's
# and /period-comparison's coverage side-bundles. Section D/E/F/G/H.
# ---------------------------------------------------------------------------


class SidedCoveragePrivacyPolicy:
    """Test-only policy that independently controls each coverage bundle's
    Cells by (group name, metric) - the group name encodes the caller's
    identity (e.g. a specific comparison side's Cycle id or a specific
    Framework Version's rubric-distribution coverage bundle), proving one
    bundle's privacy decision can never influence, borrow visibility from, or
    leak into an unrelated bundle in the same response."""

    privacy_policy_version = "test-sided-coverage-v1"

    def __init__(self, states):
        # states: {(group, metric_or_None): state}. A ``None`` metric applies
        # to every cell in that group (used for whole-group coarsen/restrict).
        self.states = states

    def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
        if raw_value is None:
            return PrivacyDecision(NO_DATA)
        group = (context or {}).get("group")
        metric = (context or {}).get("metric")
        state = self.states.get((group, metric), self.states.get((group, None), VISIBLE))
        if state == VISIBLE:
            return PrivacyDecision(VISIBLE, value=int(raw_value))
        if state == COARSENED:
            return PrivacyDecision(COARSENED, value=0, reason_code="test_sided_coarsened")
        return PrivacyDecision(state, reason_code=f"test_sided_{state}")

    def prefers_coarsening(self, *, privacy_class):
        return False


_COVERAGE_SIBLING_KEYS = frozenset((
    "counts", "frozen_eligible", "assessment_started",
    "started_coverage_percentage", "completion_coverage_percentage",
))


def _assert_no_raw_coverage_leak(node):
    """Recursively walk a JSON-decoded response body and assert that no dict
    anywhere carries both a non-visible privacy ``state`` and a raw coverage-
    shaped sibling field (``counts``/``frozen_eligible``/derived percentages).
    This is a runtime, structural proof of the Section C governing invariant
    across the WHOLE serialized payload - not just at the two known call
    sites - unlike the narrower AST ordering guard."""
    if isinstance(node, dict):
        if node.get("state") not in (None, VISIBLE):
            leaking = set(node.keys()) & _COVERAGE_SIBLING_KEYS
            assert not leaking, f"non-visible coverage state dict leaks raw fields: {node}"
        for value in node.values():
            _assert_no_raw_coverage_leak(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_raw_coverage_leak(item)


# --- Section D: direct unit tests for the shared helper (no DB/HTTP) -------

_UNIT_COUNTS = {"unassessed": 2, "in_progress": 1, "completed": 4, "incomplete": 1, "insufficient_evidence": 1}


def test_coverage_bundle_helper_fully_visible_derives_real_metrics():
    payload, state, group = svc.build_privacy_safe_coverage_bundle(
        name="unit_test_visible", counts=_UNIT_COUNTS, privacy_class="P2", policy=AllowAllTestPolicy(),
    )
    assert state == VISIBLE
    assert payload["frozen_eligible"] == 9
    assert payload["counts"] == _UNIT_COUNTS
    assert payload["assessment_started"] == 7
    assert float(payload["completion_coverage_percentage"]) == pytest.approx(44.44, abs=0.01)
    assert all(cell.state == VISIBLE for cell in group.all_cells())


def test_coverage_bundle_helper_partial_hidden_collapses_to_state_only():
    payload, state, group = svc.build_privacy_safe_coverage_bundle(
        name="unit_test_partial", counts=_UNIT_COUNTS, privacy_class="P2",
        policy=DeterministicSuppressionTestPolicy(minimum_cohort=6),
    )
    # frozen_eligible (9) alone clears the threshold, but every individual
    # status count does not - the bundle must fail closed as a whole rather
    # than publish the visible total next to null-valued siblings.
    assert payload is None
    assert state == SUPPRESSED
    assert all(cell.value is None for cell in group.children)


def test_coverage_bundle_helper_zero_population_is_no_data_not_zero():
    zero_counts = {key: 0 for key in svc.COVERAGE_STATUS_KEYS}
    payload, state, group = svc.build_privacy_safe_coverage_bundle(
        name="unit_test_zero", counts=zero_counts, privacy_class="P2", policy=AllowAllTestPolicy(),
    )
    assert payload is None
    assert state == NO_DATA


def test_coverage_bundle_helper_coarsened_total_has_no_percentage():
    payload, state, group = svc.build_privacy_safe_coverage_bundle(
        name="unit_test_coarsened", counts=_UNIT_COUNTS, privacy_class="P2",
        policy=CoarsenWithReplacementTestPolicy(minimum_cohort=10, replacement_value=0),
    )
    assert payload == {"state": COARSENED, "value": 0}
    assert state == COARSENED
    assert "started_coverage_percentage" not in payload
    assert "completion_coverage_percentage" not in payload


# --- Section E: /rubric-distribution coverage-privacy route tests ----------


def test_rubric_distribution_coverage_permissive_shows_real_values(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2600000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution").json()
        dist = next(d for d in body["distributions"] if d["framework_version_id"] == framework.id)
        assert dist["coverage"]["frozen_eligible"] == 9
        assert dist["coverage"]["counts"] == {"unassessed": 2, "in_progress": 1, "completed": 4, "incomplete": 1, "insufficient_evidence": 1}
        assert float(dist["coverage"]["completion_coverage_percentage"]) == pytest.approx(44.44, abs=0.01)


def test_rubric_distribution_coverage_total_visible_incomplete_suppressed_collapses(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2600000002")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=OverviewSelectivePrivacyPolicy({"incomplete": SUPPRESSED})) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution").json()
        dist = next(d for d in body["distributions"] if d["framework_version_id"] == framework.id)
        # A single suppressed status count must not leave the other four
        # siblings + the visible total published (which would let the
        # suppressed "incomplete" value be reconstructed by subtraction) -
        # the whole coverage bundle fails closed instead.
        assert dist["coverage"] == {"state": "suppressed"}
        assert "counts" not in dist["coverage"]


def test_rubric_distribution_coverage_total_visible_insufficient_evidence_suppressed_collapses(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2600000003")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=OverviewSelectivePrivacyPolicy({"insufficient_evidence": SUPPRESSED})) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution").json()
        dist = next(d for d in body["distributions"] if d["framework_version_id"] == framework.id)
        assert dist["coverage"] == {"state": "suppressed"}
        assert "counts" not in dist["coverage"]


def test_rubric_distribution_coverage_suppressive_policy_hides_all_status_counts_no_raw_leak(db, scenario):
    """Empirically proves the exact leak the pass-4 review found is gone:
    under a suppressive policy, small exact per-status values (incomplete=1,
    insufficient_evidence=1) must never reach the response body."""
    program = scenario["program"]
    admin = user("2600000004")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=DeterministicSuppressionTestPolicy(minimum_cohort=6)) as api:
        response = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution")
        body = response.json()
        _assert_no_raw_coverage_leak(body)
        raw_text = json.dumps(body)
        assert '"insufficient_evidence"' not in raw_text
        assert '"incomplete"' not in raw_text
        for dist in body["distributions"]:
            if "coverage" in dist:
                assert dist["coverage"] == {"state": "suppressed"}


def test_rubric_distribution_coverage_zero_population_is_no_data(db, scenario):
    program = scenario["program"]
    admin = user("2600000005")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution?grade=2").json()
        for dist in body["distributions"]:
            if "coverage" in dist:
                assert dist["coverage"] == {"state": "no_data"}


def test_rubric_distribution_coverage_coarsened_source_yields_no_exact_percentage(db, scenario):
    program = scenario["program"]
    framework = scenario["framework"]
    admin = user("2600000006")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=CoarsenWithReplacementTestPolicy(minimum_cohort=10, replacement_value=0)) as api:
        body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution").json()
        dist = next(d for d in body["distributions"] if d["framework_version_id"] == framework.id)
        assert dist["coverage"] == {"state": "coarsened", "value": 0}
        assert "started_coverage_percentage" not in dist["coverage"]
        assert "completion_coverage_percentage" not in dist["coverage"]


def test_rubric_distribution_route_no_longer_exposes_raw_coverage_metrics_directly():
    import ast
    import inspect

    import routers.talent_analytics as router_module

    source = inspect.getsource(router_module.analytics_rubric_distribution)
    tree = ast.parse(source)
    calls = [
        child.func.attr for child in ast.walk(tree)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    ]
    assert "coverage_metrics" not in calls
    assert "build_privacy_safe_coverage_bundle" in calls


# --- Section F: /period-comparison coverage-privacy route tests ------------


def _second_cycle(db, scenario, *, title="Second Cycle (all-unassessed)"):
    second_cycle = create_cycle(
        db, school_group_id=1, program_id=scenario["program"].id, academic_year_id=100,
        framework_version_id=scenario["framework"].id, title=title,
        population_effective_at=datetime(2026, 10, 1),
    )
    db.commit()
    second_cycle = open_cycle(db, school_group_id=1, cycle_id=second_cycle.id, expected_revision=second_cycle.revision, organization_authorized=True)
    db.commit()
    return second_cycle


def test_period_comparison_coverage_both_sides_permissive_show_real_values(db, scenario):
    program = scenario["program"]
    cycle = scenario["cycle"]
    admin = user("2700000001")
    db.add(admin)
    db.commit()
    with client(db, admin, policy=AllowAllTestPolicy()) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={cycle.id}&right_cycle_id={cycle.id}"
        ).json()
        assert body["left"]["coverage"]["frozen_eligible"] == 9
        assert body["right"]["coverage"]["frozen_eligible"] == 9
        assert body["left"]["coverage"]["counts"]["completed"] == 4


def test_period_comparison_coverage_left_total_visible_child_suppressed_collapses(db, scenario):
    # Two DISTINCT Cycles (different group identity per side) so the policy
    # can target ONLY the left side's group without also matching the right
    # side's group by coincidence of sharing one Cycle id.
    program = scenario["program"]
    left_cycle = scenario["cycle"]
    right_cycle = _second_cycle(db, scenario)
    admin = user("2700000002")
    db.add(admin)
    db.commit()
    left_group = f"period_comparison_coverage:{left_cycle.id}"
    policy = SidedCoveragePrivacyPolicy({(left_group, "incomplete"): SUPPRESSED})
    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={left_cycle.id}&right_cycle_id={right_cycle.id}"
        ).json()
        # The fix must not let a hidden left sibling be reconstructed from
        # the visible left total + the other visible left siblings.
        assert body["left"]["coverage"] == {"state": "suppressed"}
        # The right side's own, unrelated Cycle group is untouched.
        assert body["right"]["coverage"]["frozen_eligible"] == 9


def test_period_comparison_coverage_right_total_visible_child_suppressed_collapses(db, scenario):
    program = scenario["program"]
    left_cycle = scenario["cycle"]
    right_cycle = _second_cycle(db, scenario)
    admin = user("2700000003")
    db.add(admin)
    db.commit()
    right_group = f"period_comparison_coverage:{right_cycle.id}"
    # The second Cycle's real per-status counts are all zero except
    # "unassessed" (9) - target that one real nonzero status so the group's
    # sibling-protection mechanics are meaningfully exercised on this side.
    policy = SidedCoveragePrivacyPolicy({(right_group, "unassessed"): SUPPRESSED})
    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={left_cycle.id}&right_cycle_id={right_cycle.id}"
        ).json()
        assert body["right"]["coverage"] == {"state": "suppressed"}
        # The left side's own, unrelated Cycle group is untouched.
        assert body["left"]["coverage"]["frozen_eligible"] == 9


def test_period_comparison_coverage_one_side_suppressed_other_visible_no_cross_leak(db, scenario):
    program = scenario["program"]
    left_cycle = scenario["cycle"]
    right_cycle = _second_cycle(db, scenario)
    admin = user("2700000004")
    db.add(admin)
    db.commit()
    left_group = f"period_comparison_coverage:{left_cycle.id}"
    policy = SidedCoveragePrivacyPolicy({(left_group, None): SUPPRESSED})
    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={left_cycle.id}&right_cycle_id={right_cycle.id}"
        ).json()
        assert body["left"]["coverage"] == {"state": "suppressed"}
        # The right side's own, unrelated Cycle group is entirely untouched by
        # the left side's suppression - no cross-side leakage or borrowing.
        assert body["right"]["coverage"]["frozen_eligible"] == 9
        assert body["right"]["coverage"]["counts"]["unassessed"] == 9


def test_period_comparison_coverage_hidden_child_cannot_be_reconstructed_from_percentage(db, scenario):
    program = scenario["program"]
    left_cycle = scenario["cycle"]
    right_cycle = _second_cycle(db, scenario)
    admin = user("2700000005")
    db.add(admin)
    db.commit()
    left_group = f"period_comparison_coverage:{left_cycle.id}"
    policy = SidedCoveragePrivacyPolicy({(left_group, "incomplete"): SUPPRESSED})
    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={left_cycle.id}&right_cycle_id={right_cycle.id}"
        ).json()
        coverage = body["left"]["coverage"]
        assert "started_coverage_percentage" not in coverage
        assert "completion_coverage_percentage" not in coverage
        assert "counts" not in coverage
        # The untouched right side's real percentages remain independently derivable.
        assert float(body["right"]["coverage"]["completion_coverage_percentage"]) == pytest.approx(0.0)


def test_period_comparison_coverage_coarsened_headline_reveals_no_raw_side_fields(db, scenario):
    program = scenario["program"]
    left_cycle = scenario["cycle"]
    right_cycle = _second_cycle(db, scenario)
    admin = user("2700000006")
    db.add(admin)
    db.commit()
    left_group = f"period_comparison_coverage:{left_cycle.id}"
    policy = SidedCoveragePrivacyPolicy({(left_group, None): COARSENED})
    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={left_cycle.id}&right_cycle_id={right_cycle.id}"
        ).json()
        assert body["left"]["coverage"] == {"state": "coarsened", "value": 0}
        # The coarsened left headline never licenses the right side's real
        # values either - the right side is independently, correctly visible.
        assert body["right"]["coverage"]["frozen_eligible"] == 9


def test_period_comparison_coverage_restricted_source_reveals_no_raw_side_fields(db, scenario):
    program = scenario["program"]
    left_cycle = scenario["cycle"]
    right_cycle = _second_cycle(db, scenario)
    admin = user("2700000007")
    db.add(admin)
    db.commit()
    left_group = f"period_comparison_coverage:{left_cycle.id}"
    policy = SidedCoveragePrivacyPolicy({(left_group, "completed"): RESTRICTED})
    with client(db, admin, policy=policy) as api:
        body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={left_cycle.id}&right_cycle_id={right_cycle.id}"
        ).json()
        assert body["left"]["coverage"] == {"state": "restricted"}
        assert body["right"]["coverage"]["frozen_eligible"] == 9


def test_period_comparison_route_no_longer_exposes_raw_coverage_metrics_directly():
    import ast
    import inspect

    import routers.talent_analytics as router_module

    source = inspect.getsource(router_module.analytics_period_comparison)
    tree = ast.parse(source)
    calls = [
        child.func.attr for child in ast.walk(tree)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
    ]
    assert "coverage_metrics" not in calls
    assert "build_privacy_safe_coverage_bundle" in calls


# --- Section G: runtime regression guard (recursive, empirical) ------------


def test_runtime_regression_guard_no_raw_coverage_bundle_leaks_under_suppressive_policy(db, scenario):
    """Stronger than the Section I AST ordering guard, which only proves
    call-site ordering: this recursively inspects the fully serialized
    /rubric-distribution and /period-comparison bodies under a suppressive
    policy and proves no dict anywhere carries a non-visible state next to a
    raw coverage-shaped sibling field, across the WHOLE payload."""
    program = scenario["program"]
    cycle = scenario["cycle"]
    admin = user("2800000001")
    db.add(admin)
    db.commit()
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=6)
    with client(db, admin, policy=policy) as api:
        rubric_body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/rubric-distribution").json()
        _assert_no_raw_coverage_leak(rubric_body)

        comparison_body = api.get(
            f"/api/talent/analytics/programs/{program.id}/academic-years/100/period-comparison"
            f"?left_cycle_id={cycle.id}&right_cycle_id={cycle.id}"
        ).json()
        _assert_no_raw_coverage_leak(comparison_body)

        overview_body = api.get(f"/api/talent/analytics/programs/{program.id}/academic-years/100/overview").json()
        _assert_no_raw_coverage_leak(overview_body)
