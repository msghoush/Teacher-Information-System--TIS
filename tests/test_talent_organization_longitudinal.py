"""M10 B10 Longitudinal Organization Intelligence end-to-end tests (ADR 0027)."""

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event

import models
from auth import get_current_user
from dependencies import get_m10_organization_analytics_db
from talent_analytics_privacy import (
    AllowAllTestPolicy, CoarsenWithReplacementTestPolicy,
    DeterministicSuppressionTestPolicy, resolve_privacy_policy_provider,
)
from talent_org_intelligence_contract import MeasureComponent, MembershipGrain, MetricCode
from talent_org_intelligence_service import (
    resolve_organization_analytics_availability_provider,
    resolve_organization_analytics_breadth_policy,
)
import talent_org_longitudinal as longitudinal
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import (
    AllowAvailability, AllowBreadth, RejectBreadth, actor, db, permissions,
)


# ---------------------------------------------------------------------------
# Fixture extension helpers - additive, tenant-consistent rows on top of the
# shared M10 B3/B4 fixture (Program 1 Arts / Program 2 STEM already seeded).
# ---------------------------------------------------------------------------

def add_program(db, *, program_id, name, school_group_id=1, status="active"):
    db.add(models.TalentProgram(id=program_id, school_group_id=school_group_id, name=name, status=status))


def add_config(db, *, config_id, program_id, academic_year_id=100, school_group_id=1):
    db.add(models.TalentProgramAcademicYearConfiguration(
        id=config_id, school_group_id=school_group_id, program_id=program_id,
        academic_year_id=academic_year_id, is_enabled=True, eligible_grade_levels_csv="1,2",
    ))


def add_framework(db, *, framework_id, program_id, status="active", version_number=1, school_group_id=1):
    db.add(models.TalentProgramFrameworkVersion(
        id=framework_id, school_group_id=school_group_id, program_id=program_id,
        version_number=version_number, status=status, title=f"fw{framework_id}", revision=1,
        semantic_fingerprint=str(framework_id).zfill(64),
    ))


def add_plan(db, *, plan_id, program_id, config_id, academic_year_id=100, school_group_id=1, status="active"):
    db.add(models.TalentAnnualEvaluationPlan(
        id=plan_id, school_group_id=school_group_id, program_id=program_id,
        academic_year_id=academic_year_id, program_academic_year_configuration_id=config_id,
        status=status, revision=1, activated_at=datetime(2026, 9, 1),
    ))


def add_period(db, *, period_id, plan_id, program_id, sequence, label, status="planned",
                academic_year_id=100, school_group_id=1, **extra):
    db.add(models.TalentPlannedEvaluationPeriod(
        id=period_id, school_group_id=school_group_id, program_id=program_id,
        academic_year_id=academic_year_id, annual_evaluation_plan_id=plan_id, sequence=sequence,
        label=label, normalized_label=label.lower(), is_required=True, status=status, **extra,
    ))


def add_cycle(db, *, cycle_id, program_id, framework_id, period_id=None, status="open",
              academic_year_id=100, school_group_id=1):
    db.add(models.TalentAssessmentCycle(
        id=cycle_id, school_group_id=school_group_id, program_id=program_id,
        academic_year_id=academic_year_id, framework_version_id=framework_id,
        planned_evaluation_period_id=period_id, title=f"cycle{cycle_id}", status=status, revision=1,
        population_effective_at=datetime(2026, 10, 1),
    ))


def add_member(db, *, member_id, cycle_id, program_id, framework_id, student_id, branch_id=10,
                grade="1", academic_year_id=100, school_group_id=1):
    db.add(models.TalentAssessmentCyclePopulationMember(
        id=member_id, school_group_id=school_group_id, cycle_id=cycle_id, program_id=program_id,
        academic_year_id=academic_year_id, framework_version_id=framework_id, student_id=student_id,
        academic_placement_id=member_id, branch_id=branch_id, grade_level=grade,
        section_name="Frozen", population_effective_at=datetime(2026, 10, 1),
    ))


def add_assessment(db, *, assessment_id, cycle_id, member_id, student_id, program_id, framework_id,
                    status="completed", academic_year_id=100, school_group_id=1):
    db.add(models.TalentStudentAssessment(
        id=assessment_id, school_group_id=school_group_id, cycle_id=cycle_id,
        cycle_population_member_id=member_id, student_id=student_id, program_id=program_id,
        academic_year_id=academic_year_id, framework_version_id=framework_id, status=status,
    ))


def add_candidate(db, *, candidate_id, cycle_id, member_id, student_id, program_id, framework_id,
                   assessment_id, status="reviewed", academic_year_id=100, school_group_id=1):
    db.add(models.TalentReviewCandidate(
        id=candidate_id, school_group_id=school_group_id, cycle_id=cycle_id,
        cycle_population_member_id=member_id, student_id=student_id, program_id=program_id,
        academic_year_id=academic_year_id, framework_version_id=framework_id, assessment_id=assessment_id,
        policy_id=1, match_mode="all", evaluation_fingerprint=str(candidate_id).zfill(64),
        evaluation_snapshot_json="{}", status=status,
    ))


def add_identification(db, *, identification_id, cycle_id, member_id, student_id, program_id,
                        framework_id, assessment_id, candidate_id, decision="identified",
                        academic_year_id=100, school_group_id=1):
    db.add(models.TalentOfficialIdentification(
        id=identification_id, school_group_id=school_group_id, cycle_id=cycle_id,
        cycle_population_member_id=member_id, student_id=student_id, program_id=program_id,
        academic_year_id=academic_year_id, framework_version_id=framework_id,
        assessment_id=assessment_id, review_candidate_id=candidate_id, decision=decision,
    ))


@pytest.fixture()
def client(db):
    app = FastAPI(); app.include_router(route.router)
    state = {
        "user": actor(scope="ORGANIZATION"), "availability": AllowAvailability(),
        "breadth": AllowBreadth(), "policy": AllowAllTestPolicy(),
    }
    app.dependency_overrides[get_m10_organization_analytics_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: state["availability"]
    app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: state["breadth"]
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: state["policy"]
    return TestClient(app), state


def get(client, program_id=1, academic_year_id=100, metric="frozen_eligible", query=""):
    url = f"/api/talent/organization-analytics/programs/{program_id}/longitudinal?academic_year_id={academic_year_id}&metric={metric}"
    return client.get(url + ("&" + query if query else ""))


def point(body, period_id):
    return next(item for item in body["points"] if item["evaluation_period"]["id"] == period_id)


def comparison(body, first_id, second_id):
    return next(item for item in body["comparisons"] if item["evaluation_period_ids"] == [first_id, second_id])


# ---------------------------------------------------------------------------
# ROUTE / CONTRACT
# ---------------------------------------------------------------------------

def test_route_exists_exactly_once_and_total_route_count_is_seven():
    paths = sorted(r.path for r in route.router.routes)
    assert "/api/talent/organization-analytics/programs/{program_id}/longitudinal" in paths
    assert len(route.router.routes) == 7
    assert not any("trend" in p or "cohort" in p or "growth" in p for p in paths)


def test_academic_year_id_and_metric_are_required(db, client):
    permissions(db, "talent_analytics.view")
    resp = client[0].get("/api/talent/organization-analytics/programs/1/longitudinal?metric=frozen_eligible")
    assert resp.status_code == 422
    resp = client[0].get("/api/talent/organization-analytics/programs/1/longitudinal?academic_year_id=100")
    assert resp.status_code == 422


def test_all_nine_approved_metrics_are_recognized(db, client):
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view")
    for metric in longitudinal.LONGITUDINAL_METRICS:
        resp = get(client[0], metric=metric.value)
        assert resp.status_code == 200, (metric.value, resp.json())
        assert resp.json()["metric"] == metric.value


def test_all_five_excluded_metrics_are_rejected(db, client):
    permissions(db, "talent_analytics.view")
    for metric in longitudinal.EXCLUDED_METRICS:
        resp = get(client[0], metric=metric.value)
        assert resp.status_code == 400
        assert resp.json()["code"] == "invalid_filter"
    resp = get(client[0], metric="not_a_real_metric")
    assert resp.status_code == 400


def test_metric_contract_inventory_is_unchanged():
    assert len(MetricCode) == 14
    assert len(MeasureComponent) == 3
    assert len(MembershipGrain) == 7
    assert len(longitudinal.LONGITUDINAL_METRICS) == 9
    assert len(longitudinal.EXCLUDED_METRICS) == 5
    assert not (longitudinal.LONGITUDINAL_METRICS & longitudinal.EXCLUDED_METRICS)
    assert longitudinal.LONGITUDINAL_METRICS | longitudinal.EXCLUDED_METRICS == set(MetricCode)


# ---------------------------------------------------------------------------
# AUTHORIZATION
# ---------------------------------------------------------------------------

def test_unauthenticated_is_rejected(db, client):
    client[1]["user"] = None
    assert get(client[0]).status_code == 401


def test_missing_talent_analytics_view_is_rejected(db, client):
    assert get(client[0]).status_code == 403


def test_foreign_academic_year_is_not_found(db, client):
    permissions(db, "talent_analytics.view")
    assert get(client[0], academic_year_id=200).status_code == 404


def test_foreign_program_is_not_found_indistinguishably_from_unconfigured(db, client):
    permissions(db, "talent_analytics.view")
    foreign = get(client[0], program_id=3)
    unconfigured = get(client[0], program_id=999)
    assert foreign.status_code == unconfigured.status_code == 404
    assert foreign.json() == unconfigured.json()


def test_program_not_configured_in_requested_ay_is_not_found(db, client):
    add_program(db, program_id=5, name="Unconfigured"); db.commit()
    permissions(db, "talent_analytics.view")
    assert get(client[0], program_id=5).status_code == 404


def test_availability_missing_or_false_is_unavailable(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["availability"] = None
    assert get(client[0]).status_code == 503

    class Explodes:
        availability_version = "boom"
        def is_available(self, **_k):
            raise RuntimeError("boom")
    client[1]["availability"] = Explodes()
    assert get(client[0]).status_code == 503


def test_unauthorized_branch_filter_is_rejected(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["user"] = actor(scope="BRANCH", branch=10)
    assert get(client[0], query="branch_id=11").status_code == 400


def test_historical_branch_scope_applied_before_aggregation_and_placement_is_irrelevant(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["user"] = actor(scope="BRANCH", branch=10)
    body = get(client[0], metric="frozen_eligible").json()
    # member 2 (student 1002) is branch 11 - excluded from a branch-10 actor.
    assert point(body, 601)["metric_result"] == {"state": "visible", "value": 1}
    placement = db.get(models.StudentAcademicPlacement, 1)
    placement.branch_id = 11; placement.grade_level = "12"; db.commit()
    body = get(client[0], metric="frozen_eligible").json()
    assert point(body, 601)["metric_result"] == {"state": "visible", "value": 1}


# ---------------------------------------------------------------------------
# PERIOD / CYCLE / PLAN
# ---------------------------------------------------------------------------

def test_program1_baseline_series_states_and_sequence_order(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], metric="frozen_eligible").json()
    ids_in_order = [p["evaluation_period"]["id"] for p in body["points"]]
    assert ids_in_order == [601, 602, 603]
    assert point(body, 601)["metric_result"] == {"state": "visible", "value": 2}
    assert point(body, 601)["cycle"] == {"id": 201, "status": "closed", "framework_version_id": 101}
    assert point(body, 602)["no_data_reason"] == "cancelled_period"
    assert point(body, 602)["metric_result"] == {"state": "no_data"}
    assert point(body, 603)["no_data_reason"] == "missing_cycle"
    assert point(body, 603)["cycle"] is None


def test_completed_and_coverage_and_started_metrics(db, client):
    permissions(db, "talent_analytics.view")
    assert point(get(client[0], metric="completed").json(), 601)["metric_result"] == {"state": "visible", "value": 1}
    assert point(get(client[0], metric="assessment_started").json(), 601)["metric_result"] == {"state": "visible", "value": 2}
    coverage = point(get(client[0], metric="completion_coverage").json(), 601)["metric_result"]
    assert coverage == {"state": "visible", "numerator": 1, "denominator": 2, "percentage": 50}
    started_coverage = point(get(client[0], metric="started_coverage").json(), 601)["metric_result"]
    assert started_coverage == {"state": "visible", "numerator": 2, "denominator": 2, "percentage": 100}


def test_unlinked_adhoc_cycle_is_excluded_from_program2_series(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], program_id=2, metric="frozen_eligible").json()
    assert len(body["points"]) == 1
    assert point(body, 604)["no_data_reason"] == "missing_cycle"
    assert point(body, 604)["cycle"] is None
    assert body["comparisons"] == []


def test_period_insertion_order_and_label_never_control_sequence(db, client):
    add_program(db, program_id=6, name="Insertion")
    add_config(db, config_id=6, program_id=6)
    add_framework(db, framework_id=601601, program_id=6)
    add_plan(db, plan_id=506, program_id=6, config_id=6)
    add_period(db, period_id=9002, plan_id=506, program_id=6, sequence=2, label="Zzz-Second")
    add_period(db, period_id=9001, plan_id=506, program_id=6, sequence=1, label="Aaa-First")
    add_cycle(db, cycle_id=9101, program_id=6, framework_id=601601, period_id=9001, status="closed")
    add_cycle(db, cycle_id=9102, program_id=6, framework_id=601601, period_id=9002, status="open")
    add_member(db, member_id=9201, cycle_id=9101, program_id=6, framework_id=601601, student_id=5001)
    add_member(db, member_id=9202, cycle_id=9102, program_id=6, framework_id=601601, student_id=5002)
    db.commit()
    permissions(db, "talent_analytics.view")
    body = get(client[0], program_id=6, metric="frozen_eligible").json()
    assert [p["evaluation_period"]["id"] for p in body["points"]] == [9001, 9002]


def test_draft_cycle_is_cycle_not_authoritative(db, client):
    add_program(db, program_id=7, name="DraftProg")
    add_config(db, config_id=7, program_id=7)
    add_framework(db, framework_id=701, program_id=7)
    add_plan(db, plan_id=507, program_id=7, config_id=7)
    add_period(db, period_id=9301, plan_id=507, program_id=7, sequence=1, label="OnlyDraft")
    add_cycle(db, cycle_id=9401, program_id=7, framework_id=701, period_id=9301, status="draft")
    db.commit()
    permissions(db, "talent_analytics.view")
    body = get(client[0], program_id=7, metric="frozen_eligible").json()
    assert point(body, 9301)["no_data_reason"] == "cycle_not_authoritative"
    assert point(body, 9301)["cycle"] == {"id": 9401, "status": "draft", "framework_version_id": None}


def test_authoritative_cycle_with_no_frozen_population_is_no_frozen_population(db, client):
    add_program(db, program_id=8, name="EmptyPop")
    add_config(db, config_id=8, program_id=8)
    add_framework(db, framework_id=801, program_id=8)
    add_plan(db, plan_id=508, program_id=8, config_id=8)
    add_period(db, period_id=9501, plan_id=508, program_id=8, sequence=1, label="NoPop")
    add_cycle(db, cycle_id=9601, program_id=8, framework_id=801, period_id=9501, status="open")
    db.commit()
    permissions(db, "talent_analytics.view")
    body = get(client[0], program_id=8, metric="frozen_eligible").json()
    assert point(body, 9501)["no_data_reason"] == "no_frozen_population"
    assert point(body, 9501)["metric_result"] == {"state": "no_data"}


def test_no_plan_at_all_yields_empty_series_not_fabricated(db, client):
    add_program(db, program_id=9, name="NoPlan")
    add_config(db, config_id=9, program_id=9)
    db.commit()
    permissions(db, "talent_analytics.view")
    body = get(client[0], program_id=9, metric="frozen_eligible").json()
    assert body["points"] == [] and body["comparisons"] == []


def test_varying_cadence_two_three_five_periods(db, client):
    permissions(db, "talent_analytics.view")
    # Program 1 already has 3 periods (601/602/603).
    three = get(client[0], program_id=1, metric="frozen_eligible").json()
    assert len(three["points"]) == 3 and len(three["comparisons"]) == 2
    # Program 2 has exactly 1 period.
    one = get(client[0], program_id=2, metric="frozen_eligible").json()
    assert len(one["points"]) == 1 and len(one["comparisons"]) == 0

    add_program(db, program_id=10, name="FivePeriods")
    add_config(db, config_id=10, program_id=10)
    add_framework(db, framework_id=1001, program_id=10)
    add_plan(db, plan_id=510, program_id=10, config_id=10)
    for sequence in range(1, 6):
        pid, cid = 9700 + sequence, 9800 + sequence
        add_period(db, period_id=pid, plan_id=510, program_id=10, sequence=sequence, label=f"P{sequence}")
        add_cycle(db, cycle_id=cid, program_id=10, framework_id=1001, period_id=pid, status="closed")
        add_member(db, member_id=9900 + sequence, cycle_id=cid, program_id=10, framework_id=1001, student_id=6000 + sequence)
    db.commit()
    five = get(client[0], program_id=10, metric="frozen_eligible").json()
    assert len(five["points"]) == 5 and len(five["comparisons"]) == 4
    assert [p["evaluation_period"]["sequence"] for p in five["points"]] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# FRAMEWORK SENSITIVITY
# ---------------------------------------------------------------------------

def _seed_framework_change_program(db, *, second_status="open"):
    add_program(db, program_id=11, name="FrameworkChange")
    add_config(db, config_id=11, program_id=11)
    add_framework(db, framework_id=1101, program_id=11, status="retired")
    add_framework(db, framework_id=1102, program_id=11, status="active", version_number=2)
    add_plan(db, plan_id=511, program_id=11, config_id=11)
    add_period(db, period_id=9601, plan_id=511, program_id=11, sequence=1, label="Before")
    add_period(db, period_id=9602, plan_id=511, program_id=11, sequence=2, label="After")
    add_cycle(db, cycle_id=9701, program_id=11, framework_id=1101, period_id=9601, status="closed")
    add_cycle(db, cycle_id=9702, program_id=11, framework_id=1102, period_id=9602, status=second_status)
    add_member(db, member_id=9801, cycle_id=9701, program_id=11, framework_id=1101, student_id=7001)
    add_member(db, member_id=9802, cycle_id=9702, program_id=11, framework_id=1102, student_id=7002)
    assess_id_a, assess_id_b = 9901, 9902
    add_assessment(db, assessment_id=assess_id_a, cycle_id=9701, member_id=9801, student_id=7001, program_id=11, framework_id=1101)
    add_assessment(db, assessment_id=assess_id_b, cycle_id=9702, member_id=9802, student_id=7002, program_id=11, framework_id=1102)
    add_candidate(db, candidate_id=9910, cycle_id=9701, member_id=9801, student_id=7001, program_id=11, framework_id=1101, assessment_id=assess_id_a)
    add_candidate(db, candidate_id=9920, cycle_id=9702, member_id=9802, student_id=7002, program_id=11, framework_id=1102, assessment_id=assess_id_b)
    add_identification(db, identification_id=9930, cycle_id=9701, member_id=9801, student_id=7001, program_id=11, framework_id=1101, assessment_id=assess_id_a, candidate_id=9910)
    add_identification(db, identification_id=9940, cycle_id=9702, member_id=9802, student_id=7002, program_id=11, framework_id=1102, assessment_id=assess_id_b, candidate_id=9920)
    db.commit()


def test_framework_changed_affects_only_candidate_identification_metrics(db, client):
    _seed_framework_change_program(db)
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view")
    for metric in ("frozen_eligible", "completed", "completion_coverage", "assessment_started", "started_coverage"):
        body = get(client[0], program_id=11, metric=metric).json()
        assert comparison(body, 9601, 9602)["state"] == "comparable", metric
        assert comparison(body, 9601, 9602)["reason_code"] is None
    for metric in ("candidate_count", "candidate_of_eligible", "identified_count", "identified_of_eligible"):
        body = get(client[0], program_id=11, metric=metric).json()
        assert comparison(body, 9601, 9602)["state"] == "not_comparable", metric
        assert comparison(body, 9601, 9602)["reason_code"] == "framework_changed", metric
    body = get(client[0], program_id=11, metric="frozen_eligible").json()
    assert point(body, 9601)["cycle"]["framework_version_id"] == 1101
    assert point(body, 9602)["cycle"]["framework_version_id"] == 1102


def test_same_framework_candidate_metric_is_comparable_when_safe(db, client):
    add_program(db, program_id=12, name="SameFramework")
    add_config(db, config_id=12, program_id=12)
    add_framework(db, framework_id=1201, program_id=12)
    add_plan(db, plan_id=512, program_id=12, config_id=12)
    add_period(db, period_id=9611, plan_id=512, program_id=12, sequence=1, label="A")
    add_period(db, period_id=9612, plan_id=512, program_id=12, sequence=2, label="B")
    add_cycle(db, cycle_id=9711, program_id=12, framework_id=1201, period_id=9611, status="closed")
    add_cycle(db, cycle_id=9712, program_id=12, framework_id=1201, period_id=9612, status="open")
    add_member(db, member_id=9811, cycle_id=9711, program_id=12, framework_id=1201, student_id=7101)
    add_member(db, member_id=9812, cycle_id=9712, program_id=12, framework_id=1201, student_id=7102)
    add_assessment(db, assessment_id=9911, cycle_id=9711, member_id=9811, student_id=7101, program_id=12, framework_id=1201)
    add_assessment(db, assessment_id=9912, cycle_id=9712, member_id=9812, student_id=7102, program_id=12, framework_id=1201)
    add_candidate(db, candidate_id=9921, cycle_id=9711, member_id=9811, student_id=7101, program_id=12, framework_id=1201, assessment_id=9911)
    add_candidate(db, candidate_id=9922, cycle_id=9712, member_id=9812, student_id=7102, program_id=12, framework_id=1201, assessment_id=9912)
    db.commit()
    permissions(db, "talent_analytics.view", "talent_review_candidates.view")
    body = get(client[0], program_id=12, metric="candidate_count").json()
    assert comparison(body, 9611, 9612)["state"] == "comparable"
    assert comparison(body, 9611, 9612)["reason_code"] is None


def test_precedence_missing_reason_overrides_framework_changed(db, client):
    """Mandatory ADR 0027 precedence test: a missing/non-authoritative point's
    reason must win over framework_changed even when the Framework versions
    also differ between the pair."""
    add_program(db, program_id=13, name="Precedence")
    add_config(db, config_id=13, program_id=13)
    add_framework(db, framework_id=1301, program_id=13, status="retired")
    add_framework(db, framework_id=1302, program_id=13, status="active", version_number=2)
    add_plan(db, plan_id=513, program_id=13, config_id=13)
    add_period(db, period_id=9621, plan_id=513, program_id=13, sequence=1, label="Authoritative")
    add_period(db, period_id=9622, plan_id=513, program_id=13, sequence=2, label="DraftLinked")
    add_cycle(db, cycle_id=9721, program_id=13, framework_id=1301, period_id=9621, status="closed")
    # Different framework AND non-authoritative (draft) - missing/non-authoritative reason must win.
    add_cycle(db, cycle_id=9722, program_id=13, framework_id=1302, period_id=9622, status="draft")
    add_member(db, member_id=9821, cycle_id=9721, program_id=13, framework_id=1301, student_id=7201)
    add_assessment(db, assessment_id=9921, cycle_id=9721, member_id=9821, student_id=7201, program_id=13, framework_id=1301)
    add_candidate(db, candidate_id=9931, cycle_id=9721, member_id=9821, student_id=7201, program_id=13, framework_id=1301, assessment_id=9921)
    db.commit()
    permissions(db, "talent_analytics.view", "talent_review_candidates.view")
    body = get(client[0], program_id=13, metric="candidate_count").json()
    result = comparison(body, 9621, 9622)
    assert result["state"] == "not_comparable"
    assert result["reason_code"] == "cycle_not_authoritative"
    assert result["reason_code"] != "framework_changed"


# ---------------------------------------------------------------------------
# PRIVACY
# ---------------------------------------------------------------------------

def test_no_delta_change_percent_change_fields_anywhere(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], metric="completion_coverage").json()
    rendered = str(body).lower()
    for forbidden in ("delta", "\"change\"", "percent_change", "growth", "improvement", "decline", "progress"):
        assert forbidden not in rendered, forbidden


def test_privacy_provider_exception_fails_closed(db, client):
    permissions(db, "talent_analytics.view")
    class Explodes(AllowAllTestPolicy):
        def evaluate_cell(self, **kwargs):
            raise RuntimeError("boom")
    client[1]["policy"] = Explodes()
    resp = get(client[0], metric="frozen_eligible")
    assert resp.status_code == 500
    assert "boom" not in resp.text


def test_no_data_is_never_a_factual_zero_and_factual_zero_passes_privacy(db, client):
    permissions(db, "talent_analytics.view", "talent_review_candidates.view")
    body = get(client[0], metric="candidate_count").json()
    # period 601 has population 2 but only member 1 is a candidate: exact 1.
    assert point(body, 601)["metric_result"] == {"state": "visible", "value": 1}
    # a program with an authoritative cycle and zero candidates must show a
    # real visible zero, never no_data.
    add_program(db, program_id=14, name="ZeroCandidates")
    add_config(db, config_id=14, program_id=14)
    add_framework(db, framework_id=1401, program_id=14)
    add_plan(db, plan_id=514, program_id=14, config_id=14)
    add_period(db, period_id=9631, plan_id=514, program_id=14, sequence=1, label="Zero")
    add_cycle(db, cycle_id=9731, program_id=14, framework_id=1401, period_id=9631, status="open")
    add_member(db, member_id=9831, cycle_id=9731, program_id=14, framework_id=1401, student_id=7301)
    db.commit()
    body = get(client[0], program_id=14, metric="candidate_count").json()
    assert point(body, 9631)["metric_result"] == {"state": "visible", "value": 0}
    assert "no_data_reason" not in point(body, 9631)


def test_suppressed_component_yields_privacy_protected_comparison(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=3)
    body = get(client[0], metric="frozen_eligible").json()
    # population 2 at period 601 falls below the threshold of 3 -> suppressed.
    assert point(body, 601)["metric_result"]["state"] == "suppressed"
    result = comparison(body, 601, 602)
    assert result["state"] == "not_comparable"
    # 602 is cancelled_period, which must still win over privacy per precedence.
    assert result["reason_code"] == "cancelled_period"


def test_privacy_protected_reason_when_both_points_are_otherwise_authoritative(db, client):
    add_program(db, program_id=15, name="BothAuthoritative")
    add_config(db, config_id=15, program_id=15)
    add_framework(db, framework_id=1501, program_id=15)
    add_plan(db, plan_id=515, program_id=15, config_id=15)
    add_period(db, period_id=9641, plan_id=515, program_id=15, sequence=1, label="A")
    add_period(db, period_id=9642, plan_id=515, program_id=15, sequence=2, label="B")
    add_cycle(db, cycle_id=9741, program_id=15, framework_id=1501, period_id=9641, status="closed")
    add_cycle(db, cycle_id=9742, program_id=15, framework_id=1501, period_id=9642, status="open")
    add_member(db, member_id=9841, cycle_id=9741, program_id=15, framework_id=1501, student_id=7401)
    add_member(db, member_id=9842, cycle_id=9742, program_id=15, framework_id=1501, student_id=7402)
    db.commit()
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    body = get(client[0], program_id=15, metric="frozen_eligible").json()
    assert point(body, 9641)["metric_result"]["state"] == "suppressed"
    assert point(body, 9642)["metric_result"]["state"] == "suppressed"
    result = comparison(body, 9641, 9642)
    assert result == {"evaluation_period_ids": [9641, 9642], "state": "not_comparable", "reason_code": "privacy_protected"}


def test_coarsened_source_suppresses_rate_by_default(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = CoarsenWithReplacementTestPolicy(minimum_cohort=3, replacement_value=0)
    body = get(client[0], metric="completion_coverage").json()
    assert point(body, 601)["metric_result"]["state"] == "suppressed"
    assert "numerator" not in point(body, 601)["metric_result"]


def test_comparison_metadata_does_not_trigger_a_second_privacy_evaluation(db, client):
    permissions(db, "talent_analytics.view")
    class CountingPolicy(AllowAllTestPolicy):
        def __init__(self):
            super().__init__(); self.calls = 0
        def evaluate_cell(self, **kwargs):
            self.calls += 1
            return super().evaluate_cell(**kwargs)
    counting = CountingPolicy()
    client[1]["policy"] = counting
    get(client[0], metric="frozen_eligible")
    # exactly one privacy evaluation per period point Cell (3 periods, count metric = 1 component each).
    assert counting.calls == 3


def test_no_cross_time_relationship_and_no_same_point_relationship():
    assert "Relationship(" not in open("talent_org_longitudinal.py", encoding="utf-8").read()


# ---------------------------------------------------------------------------
# RATES
# ---------------------------------------------------------------------------

def test_numerator_suppressed_denominator_visible_suppresses_rate(db, client):
    permissions(db, "talent_analytics.view")
    # completed=1 (below threshold), population=2 (at/above threshold).
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    body = get(client[0], metric="completion_coverage").json()
    result = point(body, 601)["metric_result"]
    assert result["state"] == "suppressed"
    assert "numerator" not in result and "denominator" not in result and "percentage" not in result


def test_denominator_zero_and_source_no_data_are_no_data_not_zero(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], metric="completion_coverage").json()
    assert point(body, 603)["metric_result"] == {"state": "no_data"}
    assert point(body, 602)["metric_result"] == {"state": "no_data"}


def test_rate_percentages_are_independent_per_period_not_averaged(db, client):
    permissions(db, "talent_analytics.view")
    add_program(db, program_id=16, name="TwoRatePoints")
    add_config(db, config_id=16, program_id=16)
    add_framework(db, framework_id=1601, program_id=16)
    add_plan(db, plan_id=516, program_id=16, config_id=16)
    add_period(db, period_id=9651, plan_id=516, program_id=16, sequence=1, label="A")
    add_period(db, period_id=9652, plan_id=516, program_id=16, sequence=2, label="B")
    add_cycle(db, cycle_id=9751, program_id=16, framework_id=1601, period_id=9651, status="closed")
    add_cycle(db, cycle_id=9752, program_id=16, framework_id=1601, period_id=9652, status="closed")
    add_member(db, member_id=9851, cycle_id=9751, program_id=16, framework_id=1601, student_id=7501)
    add_member(db, member_id=9852, cycle_id=9751, program_id=16, framework_id=1601, student_id=7502)
    add_member(db, member_id=9853, cycle_id=9752, program_id=16, framework_id=1601, student_id=7503)
    add_member(db, member_id=9854, cycle_id=9752, program_id=16, framework_id=1601, student_id=7504)
    add_assessment(db, assessment_id=9951, cycle_id=9751, member_id=9851, student_id=7501, program_id=16, framework_id=1601, status="completed")
    add_assessment(db, assessment_id=9952, cycle_id=9752, member_id=9853, student_id=7503, program_id=16, framework_id=1601, status="completed")
    add_assessment(db, assessment_id=9953, cycle_id=9752, member_id=9854, student_id=7504, program_id=16, framework_id=1601, status="completed")
    db.commit()
    body = get(client[0], program_id=16, metric="completion_coverage").json()
    assert point(body, 9651)["metric_result"]["percentage"] == 50
    assert point(body, 9652)["metric_result"]["percentage"] == 100


# ---------------------------------------------------------------------------
# SECONDARY PERMISSIONS
# ---------------------------------------------------------------------------

def test_candidate_metric_without_permission_is_rejected_before_any_sql(db, client):
    permissions(db, "talent_analytics.view")
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        resp = get(client[0], metric="candidate_count")
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert resp.status_code == 403
    assert not any("talent_review_candidates" in sql for sql in statements)


def test_identification_metric_without_permission_is_rejected_before_any_sql(db, client):
    permissions(db, "talent_analytics.view")
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        resp = get(client[0], metric="identified_of_eligible")
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert resp.status_code == 403
    assert not any("talent_official_identifications" in sql for sql in statements)


def test_candidate_and_identification_sql_never_run_for_unrelated_metric_even_with_permission(db, client):
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view")
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        resp = get(client[0], metric="frozen_eligible")
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert resp.status_code == 200
    assert not any("talent_review_candidates" in sql or "talent_official_identifications" in sql for sql in statements)


def test_candidate_permission_present_yields_deterministic_persisted_facts(db, client):
    permissions(db, "talent_analytics.view", "talent_review_candidates.view")
    body = get(client[0], metric="candidate_count").json()
    assert point(body, 601)["metric_result"] == {"state": "visible", "value": 1}


def test_identification_permission_present_yields_deterministic_persisted_facts(db, client):
    permissions(db, "talent_analytics.view", "talent_official_identifications.view")
    body = get(client[0], metric="identified_count").json()
    assert point(body, 601)["metric_result"] == {"state": "visible", "value": 1}


# ---------------------------------------------------------------------------
# QUERY SCALE / BREADTH
# ---------------------------------------------------------------------------

def test_breadth_is_enforced_before_aggregation_with_correct_shape(db, client):
    permissions(db, "talent_analytics.view")
    class CaptureBreadth(AllowBreadth):
        def allows(self, **shape):
            self.shape = shape
            return True
    capture = CaptureBreadth(); client[1]["breadth"] = capture
    get(client[0], metric="frozen_eligible")
    assert capture.shape == {
        "projection_family": "program_longitudinal", "row_count": 3, "column_count": 1,
        "prospective_cells": 3, "relationship_estimate": 0, "program_count": 1,
        "prospective_pair_count": 2,
    }
    get(client[0], metric="completion_coverage")
    assert capture.shape["column_count"] == 2
    assert capture.shape["prospective_cells"] == 6


def test_breadth_rejection_fails_closed(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["breadth"] = RejectBreadth()
    assert get(client[0]).status_code == 413


def test_query_count_is_bounded_by_period_count_not_proportional(db, client):
    permissions(db, "talent_analytics.view")
    add_program(db, program_id=17, name="TwoPeriods")
    add_config(db, config_id=17, program_id=17)
    add_framework(db, framework_id=1701, program_id=17)
    add_plan(db, plan_id=517, program_id=17, config_id=17)
    add_period(db, period_id=9661, plan_id=517, program_id=17, sequence=1, label="A")
    add_period(db, period_id=9662, plan_id=517, program_id=17, sequence=2, label="B")
    add_cycle(db, cycle_id=9761, program_id=17, framework_id=1701, period_id=9661, status="closed")
    add_cycle(db, cycle_id=9762, program_id=17, framework_id=1701, period_id=9662, status="closed")
    add_member(db, member_id=9861, cycle_id=9761, program_id=17, framework_id=1701, student_id=7601)
    add_member(db, member_id=9862, cycle_id=9762, program_id=17, framework_id=1701, student_id=7602)

    add_program(db, program_id=18, name="FivePeriodsScale")
    add_config(db, config_id=18, program_id=18)
    add_framework(db, framework_id=1801, program_id=18)
    add_plan(db, plan_id=518, program_id=18, config_id=18)
    for sequence in range(1, 6):
        pid, cid = 9770 + sequence, 9780 + sequence
        add_period(db, period_id=pid, plan_id=518, program_id=18, sequence=sequence, label=f"S{sequence}")
        add_cycle(db, cycle_id=cid, program_id=18, framework_id=1801, period_id=pid, status="closed")
        add_member(db, member_id=9990 + sequence, cycle_id=cid, program_id=18, framework_id=1801, student_id=7700 + sequence)
    db.commit()

    def count_statements(program_id):
        # A fresh actor avoids auth's per-user `_permission_cache` mutation
        # from confounding this comparison across repeated calls.
        client[1]["user"] = actor(scope="ORGANIZATION")
        statements = []
        listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement)
        event.listen(db.bind, "before_cursor_execute", listener)
        try:
            resp = get(client[0], program_id=program_id, metric="frozen_eligible")
            assert resp.status_code == 200
        finally:
            event.remove(db.bind, "before_cursor_execute", listener)
        return len(statements)

    two_period_count = count_statements(17)
    five_period_count = count_statements(18)
    assert two_period_count == five_period_count


def test_no_student_orm_fetch_and_no_student_id_python_sets():
    source = open("talent_org_longitudinal.py", encoding="utf-8").read()
    assert "models.Student)" not in source
    assert "student_id" not in source


# ---------------------------------------------------------------------------
# SERIALIZER ISOLATION
# ---------------------------------------------------------------------------

def test_serializer_rejects_non_closed_projection_inputs():
    with pytest.raises(TypeError):
        longitudinal.serialize_projection({}, program={}, academic_year={}, plan=None, scope={})
    with pytest.raises(TypeError):
        longitudinal.LongitudinalClosedProjection(closed={}, metric=MetricCode.FROZEN_ELIGIBLE, slots=(), identities={})
    with pytest.raises(TypeError):
        longitudinal.LongitudinalClosedProjection(closed=None, metric="frozen_eligible", slots=(), identities={})
    with pytest.raises(TypeError):
        longitudinal.build_points_and_comparisons({}, plan=None, academic_year_id=100)


def test_no_student_identifiers_in_response(db, client):
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view")
    body = get(client[0], metric="identified_count").json()
    rendered = str(body).lower()
    assert "1001" not in rendered and "1002" not in rendered
    assert "student" not in rendered


# ---------------------------------------------------------------------------
# SEMANTICS
# ---------------------------------------------------------------------------

def test_no_growth_ranking_score_ai_or_matched_cohort_semantics(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], metric="frozen_eligible").json()
    rendered = str(body).lower()
    for forbidden in ("rank", "talent_score", "ai_", "cohort", "matched"):
        assert forbidden not in rendered


def test_academic_year_name_never_used_for_ordering():
    source = open("talent_org_longitudinal.py", encoding="utf-8").read()
    assert "year_name" not in source
    assert "order_by(models.TalentPlannedEvaluationPeriod.sequence)" in source
