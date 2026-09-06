"""M10 B9 Student Drill end-to-end tests."""

from __future__ import annotations

import inspect
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event

import models
from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import (
    AllowAllTestPolicy, DeterministicSuppressionTestPolicy, resolve_privacy_policy_provider,
)
import talent_org_intelligence_service as svc
from talent_org_intelligence_service import (
    resolve_organization_analytics_availability_provider, resolve_organization_analytics_breadth_policy,
)
import talent_org_student_drill as drill
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import AllowAvailability, AllowBreadth, RejectBreadth, actor, db, permissions


def seed_base_students(db):
    db.add_all((
        models.Student(id=1001, school_group_id=1, first_name="Ann", father_name="Q", last_name="One", status="active"),
        models.Student(id=1002, school_group_id=1, first_name="Ben", last_name="Two", status="active"),
        models.Student(id=1003, school_group_id=1, first_name="Cid", last_name="Three", status="active"),
        models.Student(id=2001, school_group_id=2, first_name="For", last_name="Eign", status="active"),
    ))
    db.commit()


def add_full_member(
    db, *, member_id, cycle_id, program_id, framework_id, student_id, branch_id, grade,
    first_name="Extra", assessment_id=None, assessment_status=None, kpi_result=None,
    candidate_id=None, candidate_status=None, identification_id=None, identification_decision=None,
    school_group_id=1, academic_year_id=100,
):
    placement_id = 9000 + member_id
    db.add(models.Student(id=student_id, school_group_id=school_group_id, first_name=first_name, last_name="Learner", status="active"))
    db.add(models.StudentAcademicPlacement(
        id=placement_id, school_group_id=school_group_id, student_id=student_id, academic_year_id=academic_year_id,
        branch_id=branch_id, grade_level=grade, section_name="Placement",
        effective_from=datetime(2026, 9, 1), status="active",
    ))
    db.flush()
    db.add(models.TalentAssessmentCyclePopulationMember(
        id=member_id, school_group_id=school_group_id, cycle_id=cycle_id, program_id=program_id,
        academic_year_id=academic_year_id, framework_version_id=framework_id, student_id=student_id,
        academic_placement_id=placement_id, branch_id=branch_id, grade_level=grade,
        section_name="Frozen", population_effective_at=datetime(2026, 10, 1),
    ))
    if assessment_status is not None:
        db.add(models.TalentStudentAssessment(
            id=assessment_id, school_group_id=school_group_id, cycle_id=cycle_id, cycle_population_member_id=member_id,
            student_id=student_id, program_id=program_id, academic_year_id=academic_year_id, framework_version_id=framework_id,
            status=assessment_status, kpi_result=kpi_result,
        ))
    if candidate_status is not None:
        db.add(models.TalentReviewCandidate(
            id=candidate_id, school_group_id=school_group_id, cycle_id=cycle_id, cycle_population_member_id=member_id,
            student_id=student_id, program_id=program_id, academic_year_id=academic_year_id, framework_version_id=framework_id,
            assessment_id=assessment_id, policy_id=1, match_mode="all", evaluation_fingerprint="e" * 64,
            evaluation_snapshot_json="{}", status=candidate_status,
        ))
    if identification_decision is not None:
        db.add(models.TalentOfficialIdentification(
            id=identification_id, school_group_id=school_group_id, cycle_id=cycle_id, cycle_population_member_id=member_id,
            student_id=student_id, program_id=program_id, academic_year_id=academic_year_id, framework_version_id=framework_id,
            assessment_id=assessment_id, review_candidate_id=candidate_id, decision=identification_decision,
        ))
    db.commit()


@pytest.fixture()
def client(db):
    seed_base_students(db)
    app = FastAPI()
    app.include_router(route.router)
    state = {
        "user": actor(scope="ORGANIZATION"), "availability": AllowAvailability(),
        "breadth": AllowBreadth(), "policy": AllowAllTestPolicy(),
    }
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: state["availability"]
    app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: state["breadth"]
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: state["policy"]
    return TestClient(app), state


def get(client, query="", academic_year_id=100):
    url = f"/api/talent/organization-analytics/students?academic_year_id={academic_year_id}"
    if query:
        url += "&" + query
    return client.get(url)


def by_id(body, student_id):
    return next((item for item in body["items"] if item["student_id"] == student_id), None)


def contexts(body, student_id):
    return by_id(body, student_id)["contexts"]


def add_existing_student_context(db, *, member_id, cycle_id, program_id, framework_id, student_id, placement_id, branch_id=10, grade="1"):
    db.add(models.TalentAssessmentCyclePopulationMember(
        id=member_id, school_group_id=1, cycle_id=cycle_id, program_id=program_id,
        academic_year_id=100, framework_version_id=framework_id, student_id=student_id,
        academic_placement_id=placement_id, branch_id=branch_id, grade_level=grade,
        section_name="Frozen", population_effective_at=datetime(2026, 10, 1),
    ))
    db.commit()


# ---------------------------------------------------------------- ROUTE/PERMISSION

def test_route_exists():
    assert "/api/talent/organization-analytics/students" in {r.path for r in route.router.routes}


def test_unauthenticated_and_true_and_permission_composition(db, client):
    api, state = client
    state["user"] = None
    assert get(api).status_code == 401

    state["user"] = actor(scope="ORGANIZATION")
    denied = get(api)
    assert denied.status_code == 403  # no talent_analytics.view at all

    permissions(db, "talent_analytics.view")
    state["user"] = actor(scope="ORGANIZATION")
    still_denied = get(api)
    assert still_denied.status_code == 403
    assert still_denied.json()["code"] == "forbidden"  # base permission alone is not enough

    permissions(db, "talent_analytics.view_students")
    state["user"] = actor(scope="ORGANIZATION")
    assert get(api).status_code == 200  # true AND composition satisfied


def test_foreign_academic_year_is_not_found(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    assert get(api, academic_year_id=200).status_code == 404


def test_availability_missing_false_and_exception_all_fail_closed(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")

    state["availability"] = None
    assert get(api).status_code == 503

    class FalseAvailability(AllowAvailability):
        def is_available(self, **_context):
            return False
    state["availability"] = FalseAvailability()
    assert get(api).status_code == 503

    class ExplodingAvailability(AllowAvailability):
        def is_available(self, **_context):
            raise RuntimeError("boom")
    state["availability"] = ExplodingAvailability()
    assert get(api).status_code == 503


# ---------------------------------------------------------------------------- SCOPE

def test_org_wide_branch_scope_and_foreign_tenant_exclusion(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    body = get(api).json()
    ids = {item["student_id"] for item in body["items"]}
    assert {1001, 1002, 1003}.issubset(ids)
    assert 2001 not in ids  # foreign tenant Student never appears

    state["user"] = actor(scope="BRANCH", branch=10)
    body = get(api).json()
    assert {item["student_id"] for item in body["items"]} == {1001, 1003}
    assert 1002 not in {item["student_id"] for item in body["items"]}  # unauthorized historical Branch


def test_current_placement_transfer_does_not_reinterpret_frozen_historical_access(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    placement = db.get(models.StudentAcademicPlacement, 1)  # student 1001's current placement
    placement.branch_id = 11
    placement.grade_level = "12"
    db.commit()

    state["user"] = actor(scope="BRANCH", branch=10)
    body = get(api).json()
    item = by_id(body, 1001)
    assert item is not None
    assert contexts(body, 1001)[0]["branch_id"] == 10
    assert contexts(body, 1001)[0]["grade_level"] == "1"  # frozen, never current placement

    state["user"] = actor(scope="BRANCH", branch=11)
    body = get(api).json()
    assert by_id(body, 1001) is None  # current placement never grants retroactive access


# -------------------------------------------------------------------------- FILTERS

def test_program_branch_grade_filters_and_rejection(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")

    assert {item["student_id"] for item in get(api, "program_ids=2").json()["items"]} == {1003}
    assert {item["student_id"] for item in get(api, "branch_id=11").json()["items"]} == {1002}
    assert {item["student_id"] for item in get(api, "grade_level=1").json()["items"]} == {1001}

    invalid_program = get(api, "program_ids=999")
    assert invalid_program.status_code == 400
    assert invalid_program.json()["code"] == "invalid_filter"
    assert get(api, "branch_id=20").status_code == 400  # foreign-tenant Branch, non-enumerating rejection

    # Aggregate-context consistency: identical filters return only the matching Student.
    assert {item["student_id"] for item in get(api, "program_ids=1&branch_id=10").json()["items"]} == {1001}


def test_no_student_id_filter_is_exposed_to_avoid_an_existence_oracle():
    sig = inspect.signature(route.organization_student_drill)
    assert "student_id" not in sig.parameters


# ----------------------------------------------------------------------- PAGINATION

def test_pagination_default_bounds_and_no_total_count(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    body = get(api).json()
    assert body["pagination"]["limit"] == 25
    assert "total_count" not in body and "total_count" not in body["pagination"]

    over_limit = get(api, "limit=101")
    assert over_limit.status_code == 400
    assert over_limit.json()["code"] == "invalid_pagination"
    assert get(api, "offset=-1").status_code == 422


def test_pagination_has_more_and_stable_deterministic_ordering(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    first = get(api, "limit=2&offset=0").json()
    assert first["pagination"] == {"limit": 2, "offset": 0, "has_more": True}
    assert [item["student_id"] for item in first["items"]] == [1001, 1002]
    second = get(api, "limit=2&offset=2").json()
    assert second["pagination"] == {"limit": 2, "offset": 2, "has_more": False}
    assert [item["student_id"] for item in second["items"]] == [1003]
    repeat = get(api, "limit=2&offset=0").json()
    assert [item["student_id"] for item in repeat["items"]] == [item["student_id"] for item in first["items"]]


# -------------------------------------------------------------- IDENTITY/MINIMIZATION

def test_identity_fields_are_minimized_to_the_approved_set(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    item = by_id(get(api).json(), 1002)
    assert set(item.keys()) == {"student_id", "display_name", "contexts"}
    assert set(item["contexts"][0]) == {
        "program_id", "cycle_id", "branch_id", "grade_level", "section_name", "assessment_state",
    }
    assert "kpi_result" not in item["contexts"][0]  # in_progress assessment, no completed KPI
    for forbidden in ("date_of_birth", "guardian", "email", "phone", "current_placement"):
        assert forbidden not in item


# ------------------------------------------------------------------------------- P7

def test_p7_gate_restricts_drill_without_disclosing_cohort_size(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    state["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=50)
    response = get(api)
    assert response.status_code == 403
    assert response.json()["code"] == "analytics_drill_restricted"
    assert "1001" not in response.text and "student_id" not in response.text


def test_p7_gate_counts_distinct_students_not_multi_program_memberships(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    add_existing_student_context(
        db, member_id=70, cycle_id=202, program_id=2, framework_id=102,
        student_id=1001, placement_id=1,
    )
    state["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=4)
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        response = get(api)
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert response.status_code == 403
    assert response.json()["code"] == "analytics_drill_restricted"
    assert not any(" join students" in sql or " from students" in sql for sql in statements)
    distinct_gate_sql = [sql for sql in statements if "count(distinct" in sql]
    assert len(distinct_gate_sql) == 1


def test_multi_cycle_membership_is_one_student_with_distinct_contexts(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    db.add(models.TalentAssessmentCycle(
        id=210, school_group_id=1, program_id=1, academic_year_id=100,
        framework_version_id=101, title="Second Arts Cycle", status="open",
        revision=1, population_effective_at=datetime(2026, 11, 1),
    ))
    db.commit()
    add_existing_student_context(
        db, member_id=71, cycle_id=210, program_id=1, framework_id=101,
        student_id=1001, placement_id=1,
    )
    add_existing_student_context(
        db, member_id=72, cycle_id=202, program_id=2, framework_id=102,
        student_id=1001, placement_id=1,
    )
    body = get(api).json()
    assert [item["student_id"] for item in body["items"]].count(1001) == 1
    assert [(item["program_id"], item["cycle_id"]) for item in contexts(body, 1001)] == [
        (1, 201), (1, 210), (2, 202),
    ]


def test_distinct_student_pagination_is_not_split_by_membership_multiplicity(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    add_existing_student_context(
        db, member_id=73, cycle_id=202, program_id=2, framework_id=102,
        student_id=1001, placement_id=1,
    )
    for index in range(26):
        add_full_member(
            db, member_id=100 + index, cycle_id=202, program_id=2,
            framework_id=102, student_id=7000 + index, branch_id=10,
            grade="2", first_name=f"Student{index:02d}",
        )
    page_one = get(api).json()
    page_two = get(api, "offset=25").json()
    ids_one = [item["student_id"] for item in page_one["items"]]
    ids_two = [item["student_id"] for item in page_two["items"]]
    assert len(ids_one) == len(set(ids_one)) == 25
    assert not set(ids_one).intersection(ids_two)
    assert page_one["pagination"]["has_more"] is True
    assert page_two["pagination"]["has_more"] is False
    assert sum(item["student_id"] == 1001 for item in page_one["items"] + page_two["items"]) == 1


def test_limit_100_counts_distinct_students_not_memberships(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    add_existing_student_context(
        db, member_id=74, cycle_id=202, program_id=2, framework_id=102,
        student_id=1001, placement_id=1,
    )
    body = get(api, "limit=100").json()
    assert len(body["items"]) == 3
    assert len({item["student_id"] for item in body["items"]}) == 3


def test_privacy_provider_failure_fails_closed(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")

    class ExplodingPolicy(AllowAllTestPolicy):
        def evaluate_cell(self, **kwargs):
            raise RuntimeError("boom")
    state["policy"] = ExplodingPolicy()
    response = get(api)
    assert response.status_code == 500
    assert response.json()["code"] == "organization_analytics_failed"


def test_no_cross_student_additive_relationship_graph():
    assert not hasattr(drill.StudentDrillClosedProjection, "relationships")
    assert "Relationship(" not in inspect.getsource(drill)


def test_no_privacy_internals_leak_into_response(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    text = get(api).text.lower()
    assert "raw_value" not in text and "threshold" not in text


# -------------------------------------------------------------------------- CANDIDATE

def test_candidate_field_and_sql_are_permission_isolated(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")

    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        body = get(api).json()
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert all("candidate_state" not in context for context in contexts(body, 1001))
    assert not any("talent_review_candidates" in sql for sql in statements)

    permissions(db, "talent_review_candidates.view")
    state["user"] = actor(scope="ORGANIZATION")
    body = get(api).json()
    assert contexts(body, 1001)[0]["candidate_state"] == "reviewed"  # exact persisted context
    assert contexts(body, 1002)[0]["candidate_state"] is None  # no qualifying candidate, never inferred


# --------------------------------------------------------------------- IDENTIFICATION

def test_identification_field_and_sql_are_permission_isolated(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")

    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        body = get(api).json()
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert all("identification_state" not in context for context in contexts(body, 1001))
    assert not any("talent_official_identifications" in sql for sql in statements)

    permissions(db, "talent_official_identifications.view")
    state["user"] = actor(scope="ORGANIZATION")
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        body = get(api).json()
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert contexts(body, 1001)[0]["identification_state"] == "identified"
    assert not any("talent_review_candidates" in sql for sql in statements)


def test_identification_semantics_distinguish_pending_not_identified_and_identified(db, client):
    api, state = client
    permissions(
        db, "talent_analytics.view", "talent_analytics.view_students",
        "talent_review_candidates.view", "talent_official_identifications.view",
    )
    add_full_member(
        db, member_id=50, cycle_id=202, program_id=2, framework_id=102, student_id=5001, branch_id=10, grade="2",
        first_name="Pending", assessment_id=750, assessment_status="completed",
        candidate_id=850, candidate_status="reviewed",
    )
    add_full_member(
        db, member_id=51, cycle_id=202, program_id=2, framework_id=102, student_id=5002, branch_id=10, grade="2",
        first_name="Declined", assessment_id=751, assessment_status="completed",
        candidate_id=851, candidate_status="reviewed",
        identification_id=951, identification_decision="not_identified",
    )
    state["user"] = actor(scope="ORGANIZATION")
    body = get(api, "limit=100").json()
    pending, declined, identified = by_id(body, 5001), by_id(body, 5002), by_id(body, 1001)
    assert pending["contexts"][0]["identification_state"] is None
    assert declined["contexts"][0]["identification_state"] == "not_identified"
    assert identified["contexts"][0]["identification_state"] == "identified"
    assert declined["contexts"][0]["identification_state"] != pending["contexts"][0]["identification_state"]


# ---------------------------------------------------------------------- LEARNER PROFILE

def test_learner_profile_capability_hint_is_permission_gated_and_advisory_only(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    assert "can_view_learner_profile" not in by_id(get(api).json(), 1001)

    permissions(db, "talent_learner_profiles.view")
    state["user"] = actor(scope="ORGANIZATION")
    assert by_id(get(api).json(), 1001)["can_view_learner_profile"] is True


def test_learner_profile_permission_alone_does_not_grant_drill_access(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_learner_profiles.view")
    response = get(api)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


# ------------------------------------------------------------------------ SERIALIZER

def test_serializer_rejects_raw_and_malformed_projections(db, client):
    api, state = client
    with pytest.raises(TypeError):
        drill.serialize_projection({}, context_payload={})
    with pytest.raises(TypeError):
        drill.StudentDrillClosedProjection(closed={}, gate_identity=None, rows=(), has_more=False)

    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    ctx = svc.resolve_access_context(
        db, user=actor(scope="ORGANIZATION"), academic_year_id=100, availability_provider=AllowAvailability(),
    )
    closed, gate_id = drill.build_gate_closure(context=ctx, eligible_count=5, policy=AllowAllTestPolicy())
    with pytest.raises(TypeError):
        drill.StudentDrillClosedProjection(
            closed=closed, gate_identity=gate_id,
            rows=(models.Student(id=1, school_group_id=1, first_name="x", last_name="y"),), has_more=False,
        )
    with pytest.raises(TypeError):
        drill.StudentDrillClosedProjection(
            closed=closed, gate_identity=gate_id, rows=({"student_id": 1},), has_more=False,
        )


# ----------------------------------------------------------------------------- QUERY

def test_query_family_is_bounded_and_not_row_proportional(db, client):
    api, state = client
    permissions(
        db, "talent_analytics.view", "talent_analytics.view_students",
        "talent_review_candidates.view", "talent_official_identifications.view",
    )
    # A fresh actor object is used for each capture so `auth.has_permission`'s
    # per-user-object permission cache cannot mask (or fake) query growth -
    # this isolates genuine row-count-driven query growth from permission caching.
    state["user"] = actor(scope="ORGANIZATION")
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement)
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        get(api, "limit=100")
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    baseline = len(statements)
    assert baseline <= 12

    add_full_member(db, member_id=60, cycle_id=202, program_id=2, framework_id=102, student_id=6001, branch_id=10, grade="2", first_name="Extra1")
    add_full_member(db, member_id=61, cycle_id=202, program_id=2, framework_id=102, student_id=6002, branch_id=10, grade="2", first_name="Extra2")
    state["user"] = actor(scope="ORGANIZATION")
    statements2 = []
    listener2 = lambda _c, _u, statement, _p, _x, _m: statements2.append(statement)
    event.listen(db.bind, "before_cursor_execute", listener2)
    try:
        get(api, "limit=100")
    finally:
        event.remove(db.bind, "before_cursor_execute", listener2)
    assert len(statements2) == baseline  # bounded query family, not N+1 per additional Student


# -------------------------------------------------------------------------- REGRESSION

def test_breadth_rejection_and_aggregate_routes_are_unaffected(db, client):
    api, state = client
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    state["breadth"] = RejectBreadth()
    rejected = get(api)
    assert rejected.status_code == 413
    assert rejected.json()["code"] == "analytics_breadth_unavailable"

    state["breadth"] = AllowBreadth()
    overview = api.get("/api/talent/organization-analytics/overview?academic_year_id=100")
    assert overview.status_code == 200
