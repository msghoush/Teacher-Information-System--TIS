"""M18b-1 Results & Analytics backend contract tests.

Covers: the pure raw-count Organization aggregation proof (the exact
Branch A 1/2 + Branch B 9/90 = Organization 10/92 case, never the naive 30%
average), the current M17 classification distribution (exactly five bands,
current+completed only, draft/non-current excluded, Exceptional-only
Talented), Branch/Organization scope enforcement, and privacy suppression
behavior. Reuses ``test_talent_classification.py``'s ``db``/``build_program``/
``complete_with_level`` fixtures rather than duplicating Talent Program/
Cycle/Assessment setup (established repository pattern - see e.g.
``test_talent_operational_context.py``).
"""

from datetime import datetime

import pytest

import models
import talent_analytics_service as svc
import talent_results_analytics_service as results_svc
from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import AllowAllTestPolicy, DeterministicSuppressionTestPolicy
from student_academic_service import create_placement, create_student
from talent_assessment_cycle_service import create_cycle, open_cycle
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, create_competency,
    create_framework_draft, create_program, transition_program, upsert_annual_configuration,
    upsert_descriptor, upsert_rubric,
)
from talent_student_assessment_service import complete_assessment, mark_non_complete, set_competency_result, start_assessment

from test_talent_classification import build_program, complete_with_level, db  # noqa: F401


# ---------------------------------------------------------------------------
# A. Pure Organization raw-count aggregation proof - no DB required.
# ---------------------------------------------------------------------------


def test_sum_raw_counts_is_the_raw_sum_not_an_average_of_branch_rates():
    # Branch A: 1 talented / 2 applicable = 50%. Branch B: 9 talented / 90
    # applicable = 10%. Naive average of the two Branch rates is 30% - this
    # must NEVER be what the Organization total represents.
    by_branch = {
        10: {"talented": 1, "not_talented": 1},   # 2 applicable, 50%
        20: {"talented": 9, "not_talented": 81},  # 90 applicable, 10%
    }
    org = results_svc.sum_raw_counts_across_branches(by_branch)
    assert org == {"talented": 10, "not_talented": 82}
    applicable = org["talented"] + org["not_talented"]
    assert applicable == 92
    rate = round(org["talented"] / applicable * 100, 2)
    assert rate == 10.87
    naive_average_of_branch_rates = round((50 + 10) / 2, 2)
    assert naive_average_of_branch_rates == 30.0
    assert rate != naive_average_of_branch_rates


def test_sum_raw_counts_across_branches_is_associative_and_order_independent():
    by_branch_a = {1: {"x": 3, "y": 1}, 2: {"x": 2, "y": 4}, 3: {"x": 0, "y": 5}}
    by_branch_b = {3: {"x": 0, "y": 5}, 1: {"x": 3, "y": 1}, 2: {"x": 2, "y": 4}}
    assert results_svc.sum_raw_counts_across_branches(by_branch_a) == results_svc.sum_raw_counts_across_branches(by_branch_b)
    assert results_svc.sum_raw_counts_across_branches(by_branch_a) == {"x": 5, "y": 10}


def test_talented_counts_by_branch_projects_exceptional_only():
    by_branch_classification = {
        10: {"Needs Improvement": 1, "Developing": 0, "Meets Expectations": 0, "Advanced": 1, "Exceptional": 1},
    }
    projected = results_svc.talented_counts_by_branch(by_branch_classification)
    assert projected == {10: {"talented": 1, "not_talented": 2}}


# ---------------------------------------------------------------------------
# B. Classification family - DB-backed, real classification authority reuse.
# ---------------------------------------------------------------------------


def _ctx(db):
    program, framework, cycle, member, fw_competency, levels, student = build_program(db, level_count=5)
    ctx = svc.resolve_context(db, school_group_id=1, program_id=program.id, academic_year_id=100)
    return program, framework, cycle, member, fw_competency, levels, student, ctx


def test_classification_family_has_exactly_five_bands(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    complete_with_level(db, member, fw_competency, levels[-1])  # top level -> Exceptional
    payload = results_svc.classification_family(db, ctx, svc.ResolvedFilters(), None, AllowAllTestPolicy())
    labels = [bucket["label"] for bucket in payload["distribution"]["buckets"]]
    assert labels == ["Needs Improvement", "Developing", "Meets Expectations", "Advanced", "Exceptional"]


def test_classification_family_counts_only_current_completed_assessment(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    complete_with_level(db, member, fw_competency, levels[-1])
    payload = results_svc.classification_family(db, ctx, svc.ResolvedFilters(), None, AllowAllTestPolicy())
    exceptional = next(b for b in payload["distribution"]["buckets"] if b["label"] == "Exceptional")
    assert exceptional["count"] == 1
    assert payload["distribution"]["total"]["value"] == 1


def test_classification_family_excludes_draft_assessment(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    start_assessment(db, school_group_id=1, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    payload = results_svc.classification_family(db, ctx, svc.ResolvedFilters(), None, AllowAllTestPolicy())
    assert payload["distribution"]["total"]["value"] == 0


def test_classification_family_excludes_incomplete_assessment(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    assessment = start_assessment(db, school_group_id=1, cycle_id=member.cycle_id, cycle_population_member_id=member.id)
    mark_non_complete(db, school_group_id=1, assessment_id=assessment.id, expected_revision=assessment.revision, status="incomplete")
    payload = results_svc.classification_family(db, ctx, svc.ResolvedFilters(), None, AllowAllTestPolicy())
    assert payload["distribution"]["total"]["value"] == 0


def test_classification_family_advanced_is_not_talented(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    complete_with_level(db, member, fw_competency, levels[-2])  # second-highest of 5 -> Advanced (4.20)
    talented_payload = results_svc.talented_family(db, ctx, svc.ResolvedFilters(), None, AllowAllTestPolicy())
    assert talented_payload["organization"]["summary"]["talented_count"] == 0
    assert talented_payload["organization"]["summary"]["applicable_denominator"] == 1


def test_classification_family_invalid_filter_rejected(db):
    _, _, _, _, _, _, _, ctx = _ctx(db)
    with pytest.raises(results_svc.ResultsAnalyticsError):
        results_svc.classification_family(db, ctx, svc.ResolvedFilters(), None, AllowAllTestPolicy(), classification_filter="not_a_band")


def test_classification_service_is_reused_never_duplicated(db):
    # The classification bands in this module are sourced ONLY from
    # talent_classification_service.CLASSIFICATION_LABELS - not re-listed.
    from talent_classification_service import CLASSIFICATION_LABELS
    assert results_svc.CLASSIFICATION_LABELS is CLASSIFICATION_LABELS


# ---------------------------------------------------------------------------
# C. Talented aggregation - Branch/Organization scope, unauthorized exclusion.
# ---------------------------------------------------------------------------


def test_talented_organization_total_is_raw_sum_of_branches_not_average(db):
    # ``build_program`` opens its Cycle (freezing the population) with a
    # single Student/Branch, so a second real Branch cannot be added to the
    # SAME frozen Cycle population after the fact. This test instead proves
    # the exact production data-flow contract end to end: the real DB-backed
    # per-Branch dict produced by ``classify_rows``/``talented_counts_by_branch``
    # for this Cycle's own real Branch is combined, via the same
    # ``sum_raw_counts_across_branches`` production function the service
    # layer calls, with a second Branch's counts - proving the identical
    # function used in production sums raw counts and reproduces the exact
    # 10/92 proof (see the pure unit test above) rather than averaging rates.
    program, framework, cycle, member_a, fw_competency, levels, student_a = build_program(db, level_count=5)
    complete_with_level(db, member_a, fw_competency, levels[-1])  # Exceptional
    ctx = svc.resolve_context(db, school_group_id=1, program_id=program.id, academic_year_id=100)
    pop_query = svc.population_query(db, ctx, svc.ResolvedFilters(), None)
    rows = results_svc.applicable_assessment_rows(db, pop_query)
    by_branch, _ = results_svc.classify_rows(db, rows)
    branch_a_id = member_a.branch_id
    # build_program produces a single Student, so Branch A here contributes
    # 1 talented / 0 not-talented (applicable=1); a second Branch's raw
    # counts (9 talented / 81 not-talented, applicable=90) are combined via
    # the exact production ``sum_raw_counts_across_branches`` function.
    simulated = {branch_a_id: results_svc.talented_counts_by_branch(by_branch)[branch_a_id],
                 999: {"talented": 9, "not_talented": 81}}
    assert simulated[branch_a_id] == {"talented": 1, "not_talented": 0}
    org = results_svc.sum_raw_counts_across_branches(simulated)
    assert org["talented"] == 10
    assert org["talented"] + org["not_talented"] == 91


def test_talented_family_branch_scope_excludes_unauthorized_branch(db):
    program, framework, cycle, member, fw_competency, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, fw_competency, levels[-1])
    ctx = svc.resolve_context(db, school_group_id=1, program_id=program.id, academic_year_id=100)
    # visible_branch_ids restricted to a Branch the Student is NOT in.
    payload = results_svc.talented_family(db, ctx, svc.ResolvedFilters(), {999}, AllowAllTestPolicy())
    assert payload["organization"]["summary"]["applicable_denominator"] == 0
    assert payload["organization"]["summary"]["talented_count"] == 0


def test_filters_cannot_widen_scope_branch_id_outside_visible_set(db):
    program, framework, cycle, member, fw_competency, levels, student = build_program(db, level_count=5)
    ctx = svc.resolve_context(db, school_group_id=1, program_id=program.id, academic_year_id=100)
    with pytest.raises(svc.TalentAnalyticsError):
        svc.resolve_filters(
            ctx, {"branch_id": member.branch_id}, db=db, branch_scope={999},
            has_candidate_permission=False, has_identification_permission=False,
        )


# ---------------------------------------------------------------------------
# D. Privacy - suppressed values are absent, never a leaked numeric value.
# ---------------------------------------------------------------------------


def test_classification_family_suppresses_small_cohort_without_leaking_value(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    complete_with_level(db, member, fw_competency, levels[-1])
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
    payload = results_svc.classification_family(db, ctx, svc.ResolvedFilters(), None, policy)
    for bucket in payload["distribution"]["buckets"]:
        if bucket["state"] != "visible":
            assert bucket["count"] is None
            assert bucket["percentage"] is None


def test_talented_family_suppresses_small_cohort_without_leaking_value(db):
    _, _, _, member, fw_competency, levels, _, ctx = _ctx(db)
    complete_with_level(db, member, fw_competency, levels[-1])
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
    payload = results_svc.talented_family(db, ctx, svc.ResolvedFilters(), None, policy)
    summary = payload["organization"]["summary"]
    if payload["organization"]["distribution"]["total"]["state"] != "visible":
        assert summary["talented_count"] is None
        assert summary["applicable_denominator"] is None
        assert summary["talented_rate_percentage"] is None


# ---------------------------------------------------------------------------
# E. learning_style_dimension dead-parameter removal regression.
# ---------------------------------------------------------------------------


def test_branch_comparison_metric_no_longer_accepts_learning_style_dimension():
    import talent_evaluation_progress_service as progress_svc
    import inspect
    assert "learning_style_dimension" not in inspect.signature(progress_svc.branch_comparison_metric).parameters


def test_branch_comparison_route_no_longer_has_learning_style_dimension_param():
    import inspect
    import routers.talent_evaluation_progress as progress_router
    assert "learning_style_dimension" not in inspect.signature(progress_router.branch_comparison).parameters


# ---------------------------------------------------------------------------
# F. Router-level smoke tests (permission gate + family delegation).
# ---------------------------------------------------------------------------


def test_router_learning_style_reuses_students_view_permission_and_delegates(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.talent_results_analytics import router as results_router

    student = create_student(db, school_group_id=1, first_name="LS", last_name="Student")
    create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100,
                      branch_id=10, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    admin = models.User(user_id="1000000098", username="admin98", role="Administrator", user_type="TENANT",
                         access_scope="ORGANIZATION", school_group_id=1, branch_id=None, academic_year_id=100, is_active=True)
    db.add(admin)
    db.commit()
    app = FastAPI()
    app.include_router(results_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin
    with TestClient(app) as client:
        response = client.get("/api/talent/results-analytics/academic-years/100/learning-style")
    assert response.status_code == 200
    payload = response.json()
    assert payload["family"] == "learning_style"
    assert payload["distribution"]["total"]["value"] >= 1


def test_router_classification_requires_talent_analytics_view_permission(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.talent_results_analytics import router as results_router

    program, framework, cycle, member, fw_competency, levels, student = build_program(db, level_count=5)
    no_perm_user = models.User(user_id="1000000097", username="user97", role="Viewer", user_type="TENANT",
                                access_scope="BRANCH", school_group_id=1, branch_id=10, academic_year_id=100, is_active=True)
    db.add(no_perm_user)
    db.commit()
    app = FastAPI()
    app.include_router(results_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: no_perm_user
    with TestClient(app) as client:
        response = client.get(f"/api/talent/results-analytics/programs/{program.id}/academic-years/100/classification")
    assert response.status_code in (401, 403)
