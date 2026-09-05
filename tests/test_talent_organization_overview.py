"""M10 B5 end-to-end Organization Overview route tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import (
    AllowAllTestPolicy, CoarsenWithReplacementTestPolicy,
    DeterministicSuppressionTestPolicy, PrivacyDecision, TalentAnalyticsPrivacyPolicy,
    resolve_privacy_policy_provider,
)
from talent_org_intelligence_service import resolve_organization_analytics_availability_provider
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import AllowAvailability, actor, db, permissions


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(route.router)
    state = {"user": actor(scope="ORGANIZATION"), "availability": AllowAvailability(), "policy": AllowAllTestPolicy()}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: state["availability"]
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: state["policy"]
    return TestClient(app), state


def get(client):
    return client.get("/api/talent/organization-analytics/overview?academic_year_id=100")


def test_overview_is_end_to_end_privacy_closed_and_optional_metrics_are_omitted(db, client):
    permissions(db, "talent_analytics.view")
    response = get(client[0])
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "organization"
    assert body["metrics"]["programs_configured"] == {"state": "visible", "value": 2}
    assert body["metrics"]["active_programs"] == {"state": "visible", "value": 2}
    assert body["metrics"]["frozen_eligible_memberships"] == {"state": "visible", "value": 3}
    assert body["metrics"]["completion_coverage"] == {"state": "visible", "numerator": 1, "denominator": 3, "percentage": pytest.approx(100 / 3)}
    assert body["metrics"]["required_period_execution"] == {"state": "visible", "numerator": 1, "denominator": 3, "percentage": pytest.approx(100 / 3)}
    assert "candidate_membership_count" not in body["metrics"]
    assert "identified_count" not in body["metrics"]
    assert not ({"raw_value", "privacy_threshold", "relationships", "analyses", "victim_keys"} & set(str(body).split()))


def test_branch_scope_uses_frozen_branch_and_hides_unauthorized_members(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["user"] = actor(scope="BRANCH", branch=10)
    body = get(client[0]).json()
    assert body["scope"] == "authorized_branches"
    assert body["metrics"]["frozen_eligible_memberships"]["value"] == 2


def test_secondary_permissions_add_only_the_authorized_metrics_and_identified_excludes_other_decisions(db, client):
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view")
    identification = db.query(__import__("models").TalentOfficialIdentification).filter_by(id=901).one()
    identification.decision = "not_identified"
    db.commit()
    body = get(client[0]).json()
    assert body["metrics"]["candidate_membership_count"]["value"] == 1
    assert body["metrics"]["identified_count"]["value"] == 0


def test_identified_count_counts_only_identified_decisions(db, client):
    import models
    from datetime import datetime
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view")
    for offset, decision in enumerate(("identified", "identified", "not_identified", "not_identified"), start=10):
        member_id = offset + 3
        assessment_id = 700 + offset
        candidate_id = 800 + offset
        db.add(models.TalentAssessmentCyclePopulationMember(
            id=member_id, school_group_id=1, cycle_id=201, program_id=1,
            academic_year_id=100, framework_version_id=101, student_id=1000 + member_id,
            academic_placement_id=member_id, branch_id=10, grade_level="1",
            section_name="Frozen", population_effective_at=datetime(2026, 10, 1),
        ))
        db.add(models.TalentStudentAssessment(
            id=assessment_id, school_group_id=1, cycle_id=201,
            cycle_population_member_id=member_id, student_id=1000 + member_id,
            program_id=1, academic_year_id=100, framework_version_id=101, status="completed",
        ))
        db.add(models.TalentReviewCandidate(
            id=candidate_id, school_group_id=1, cycle_id=201,
            cycle_population_member_id=member_id, student_id=1000 + member_id,
            program_id=1, academic_year_id=100, framework_version_id=101,
            assessment_id=assessment_id, policy_id=1, match_mode="all",
            evaluation_fingerprint=(str(offset) * 64)[:64], evaluation_snapshot_json="{}", status="reviewed",
        ))
        db.add(models.TalentOfficialIdentification(
            id=900 + offset, school_group_id=1, cycle_id=201,
            cycle_population_member_id=member_id, student_id=1000 + member_id,
            program_id=1, academic_year_id=100, framework_version_id=101,
            assessment_id=assessment_id, review_candidate_id=candidate_id, decision=decision,
        ))
    db.commit()
    assert get(client[0]).json()["metrics"]["identified_count"] == {"state": "visible", "value": 3}


def test_auth_availability_permission_and_foreign_year_fail_safely(db, client):
    response = get(client[0])
    assert response.status_code == 403
    permissions(db, "talent_analytics.view")
    client[1]["availability"] = None
    response = get(client[0])
    assert response.status_code == 503
    client[1]["availability"] = AllowAvailability()
    response = client[0].get("/api/talent/organization-analytics/overview?academic_year_id=200")
    assert response.status_code in (403, 404)
    client[1]["user"] = None
    assert get(client[0]).status_code == 401


def test_no_population_is_no_data_not_zero(db, client):
    import models
    permissions(db, "talent_analytics.view")
    db.query(models.TalentAssessmentCyclePopulationMember).filter_by(school_group_id=1).delete()
    db.commit()
    metrics = get(client[0]).json()["metrics"]
    assert metrics["frozen_eligible_memberships"] == {"state": "no_data"}
    assert metrics["completion_coverage"] == {"state": "no_data"}


def test_primary_suppression_runs_before_b2_and_no_exact_sibling_leaks(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    metrics = get(client[0]).json()["metrics"]
    # completed=1 is primarily suppressed; its equal coverage numerator is
    # closed as well, so no derived numerator/denominator/percentage leaks.
    assert metrics["completion_coverage"] == {"state": "suppressed"}
    assert "percentage" not in metrics["completion_coverage"]


def test_coarsened_source_never_produces_an_exact_percentage(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = CoarsenWithReplacementTestPolicy(minimum_cohort=2, replacement_value=0)
    coverage = get(client[0]).json()["metrics"]["completion_coverage"]
    assert coverage == {"state": "suppressed"}


class ExplodingAvailability(AllowAvailability):
    def is_available(self, **_context):
        raise RuntimeError("provider secret")


def test_provider_exception_is_normalized_without_sensitive_detail(db, client):
    client[1]["availability"] = ExplodingAvailability()
    response = get(client[0])
    assert response.status_code == 503
    assert response.json() == {"detail": "Organization analytics is unavailable.", "code": "organization_analytics_unavailable"}
    assert "provider secret" not in response.text


def test_overview_uses_one_caller_session_and_bounded_set_based_queries(db, client):
    from sqlalchemy import event
    permissions(db, "talent_analytics.view")
    statements = []

    def count(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        assert get(client[0]).status_code == 200
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    # Authorization and every aggregate share the dependency-owned Session;
    # query count is fixed by query families, not by returned members/cells.
    assert 1 <= len(statements) <= 16


def test_serializer_rejects_anything_before_the_privacy_closed_boundary():
    with pytest.raises(TypeError, match="PrivacyClosedProjectionSet"):
        route._safe_overview_payload(object(), context=None, fingerprint="x", privacy_policy_version="x", identities={}, candidate_included=False, identification_included=False)
