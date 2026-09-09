"""M10 B6 Talent Map end-to-end and canonical-topology tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from auth import get_current_user
from dependencies import get_m10_organization_analytics_db
from talent_analytics_privacy import AllowAllTestPolicy, DeterministicSuppressionTestPolicy, PrivacyDecision, TalentAnalyticsPrivacyPolicy, resolve_privacy_policy_provider
from talent_org_intelligence_service import resolve_organization_analytics_availability_provider, resolve_organization_analytics_breadth_policy
from routers import talent_organization_analytics as route
import talent_org_talent_map as tm
from talent_org_intelligence_contract import MeasureComponent, MetricCode
from test_talent_org_intelligence_queries import AllowAvailability, AllowBreadth, RejectBreadth, actor, db, permissions


@pytest.fixture()
def client(db):
    app = FastAPI(); app.include_router(route.router)
    state = {"user": actor(scope="ORGANIZATION"), "availability": AllowAvailability(), "breadth": AllowBreadth(), "policy": AllowAllTestPolicy()}
    app.dependency_overrides[get_m10_organization_analytics_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[resolve_organization_analytics_availability_provider] = lambda: state["availability"]
    app.dependency_overrides[resolve_organization_analytics_breadth_policy] = lambda: state["breadth"]
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: state["policy"]
    return TestClient(app), state


def get(client, query=""):
    suffix = "&" + query if query else ""
    return client.get("/api/talent/organization-analytics/talent-map?academic_year_id=100" + suffix)


def test_default_program_branch_completion_matrix_and_backend_totals(db, client):
    permissions(db, "talent_analytics.view")
    response = get(client[0]); assert response.status_code == 200
    body = response.json()
    assert body["projection_family"] == "program_branch" and body["metric"] == "completion_coverage"
    assert [row["label"] for row in body["rows"]] == ["Arts", "STEM"]
    assert body["organization_total"] == {"state": "visible", "numerator": 1, "denominator": 3, "percentage": pytest.approx(100 / 3)}
    assert body["comparability"] == {"mode": "common_factual_metric", "cross_program_score": False}


def test_program_grade_uses_governed_grade_order_and_count_metric(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], "dimension=program_grade&metric=frozen_eligible").json()
    assert [item["id"] for item in body["columns"]][:4] == ["KG", "1", "2", "3"]
    assert body["organization_total"] == {"state": "visible", "value": 3}


def test_alias_transposes_presentation_not_canonical_privacy(db, client):
    permissions(db, "talent_analytics.view")
    canonical = get(client[0], "dimension=program_branch").json()
    alias = get(client[0], "dimension=branch_program").json()
    assert canonical["projection_family"] == alias["projection_family"] == "program_branch"
    assert canonical["cells"] == alias["cells"]
    assert canonical["organization_total"] == alias["organization_total"]
    assert canonical["rows"] == alias["columns"] and canonical["columns"] == alias["rows"]


def test_invalid_dimension_execution_metric_and_arbitrary_metric_are_rejected(db, client):
    permissions(db, "talent_analytics.view")
    assert get(client[0], "dimension=section_program").status_code == 400
    assert get(client[0], "metric=required_period_execution").status_code == 400
    assert get(client[0], "metric=talent_score").status_code == 400


def test_sensitive_metrics_require_secondary_permission_and_identified_is_identified_only(db, client):
    permissions(db, "talent_analytics.view")
    assert get(client[0], "metric=candidate_count").status_code == 403
    assert get(client[0], "metric=identified_count").status_code == 403
    permissions(db, "talent_review_candidates.view", "talent_official_identifications.view")
    client[1]["user"] = actor(scope="ORGANIZATION")
    assert get(client[0], "metric=candidate_count").json()["organization_total"]["value"] == 1
    assert get(client[0], "metric=identified_count").json()["organization_total"]["value"] == 1


def test_branch_scope_uses_only_frozen_authorized_branch(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["user"] = actor(scope="BRANCH", branch=10)
    body = get(client[0], "metric=frozen_eligible").json()
    assert [item["id"] for item in body["columns"]] == [10]
    assert body["organization_total"]["value"] == 2
    assert body["scope"]["authorization_scope"] == "authorized_branches"


def test_breadth_is_mandatory_and_fails_closed(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["breadth"] = None
    assert get(client[0]).status_code == 413
    client[1]["breadth"] = RejectBreadth()
    assert get(client[0]).status_code == 413


def test_primary_and_complementary_privacy_prevent_sibling_leaks(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    body = get(client[0]).json()
    assert any(cell["state"] == "suppressed" for cell in body["cells"])
    for value in [*body["cells"], *body["row_totals"], *body["column_totals"], body["organization_total"]]:
        if value["state"] != "visible":
            assert not ({"value", "numerator", "denominator", "percentage"} & value.keys())
    assert "raw_value" not in str(body) and "victim" not in str(body) and "relationship" not in str(body)


class SuppressSouthStem(TalentAnalyticsPrivacyPolicy):
    privacy_policy_version = "test-cross-axis-v1"

    def evaluate_cell(self, *, raw_value, context=None, **_ignored):
        if raw_value is None:
            return PrivacyDecision("no_data")
        if context.get("program_id") == 2 and context.get("branch_id") == 11:
            return PrivacyDecision("suppressed")
        return PrivacyDecision("visible", value=raw_value)


class SuppressCoordinate(TalentAnalyticsPrivacyPolicy):
    privacy_policy_version = "test-sparse-coordinate-v1"

    def __init__(self, *, program_id, branch_id=None, grade_level=None):
        self.program_id = program_id; self.branch_id = branch_id; self.grade_level = grade_level

    def evaluate_cell(self, *, raw_value, context=None, **_ignored):
        if raw_value is None:
            return PrivacyDecision("no_data")
        matches = context.get("program_id") == self.program_id
        if self.branch_id is not None:
            matches = matches and context.get("branch_id") == self.branch_id
        if self.grade_level is not None:
            matches = matches and context.get("grade_level") == self.grade_level
        return PrivacyDecision("suppressed") if matches else PrivacyDecision("visible", value=raw_value)


def test_two_by_two_cross_axis_reconstruction_adds_complementary_suppression(db, client):
    import models
    from datetime import datetime
    permissions(db, "talent_analytics.view")
    db.add(models.TalentAssessmentCyclePopulationMember(
        id=20, school_group_id=1, cycle_id=202, program_id=2, academic_year_id=100,
        framework_version_id=102, student_id=1020, academic_placement_id=20,
        branch_id=11, grade_level="2", section_name="Frozen",
        population_effective_at=datetime(2026, 10, 1),
    )); db.commit()
    client[1]["policy"] = SuppressSouthStem()
    body = get(client[0], "metric=frozen_eligible").json()
    matrix = {(cell["coordinates"]["program_id"], cell["coordinates"]["branch_id"]): cell for cell in body["cells"]}
    assert matrix[(2, 11)] == {"coordinates": {"program_id": 2, "branch_id": 11}, "state": "suppressed"}
    assert sum(cell["state"] == "suppressed" for cell in body["cells"] + body["row_totals"] + body["column_totals"]) >= 2


def _context():
    return type("Context", (), {"school_group_id": 1, "academic_year_id": 100})()


def _suppressed_keys(result):
    return {identity.canonical_key() for identity in result.closed._projections if result.closed.projection(identity).state == "suppressed"}


def test_sparse_grade_relationship_uses_only_authoritative_children_and_blocks_reconstruction():
    result = tm.build_talent_map_closed(
        context=_context(), dimension="grade", metric=MetricCode.FROZEN_ELIGIBLE,
        program_ids=(2,), column_values=("KG", "1", "2", "3"),
        facts={(2, "1"): {"population": 3}, (2, "2"): {"population": 6}},
        policy=SuppressCoordinate(program_id=2, grade_level="1"),
    )
    grade1 = result.identities[("cell", 2, "1")][0]
    grade2 = result.identities[("cell", 2, "2")][0]
    grade3 = result.identities[("cell", 2, "3")][0]
    row_total = result.identities[("row_total", 2)][0]
    row_relationship = next(item for item in result.relationships if row_total in {term.cell for term in item.terms})
    assert {term.cell for term in row_relationship.terms} == {row_total, grade1, grade2}
    assert grade3 not in {term.cell for item in result.relationships for term in item.terms}
    assert result.closed.projection(grade3).state == "no_data"
    assert result.closed.projection(grade1).state == "suppressed"
    assert "suppressed" in {result.closed.projection(grade2).state, result.closed.projection(row_total).state}


def test_sparse_column_scope_total_empty_and_single_child_are_privacy_safe():
    result = tm.build_talent_map_closed(
        context=_context(), dimension="branch", metric=MetricCode.COMPLETED,
        program_ids=(1, 2, 3), column_values=(10, 11, 12),
        facts={(1, 10): {"population": 4, "completed": 3}, (2, 10): {"population": 8, "completed": 6}, (1, 11): {"population": 5, "completed": 0}},
        policy=SuppressCoordinate(program_id=1, branch_id=10),
    )
    protected = result.identities[("cell", 1, 10)][0]
    sibling = result.identities[("cell", 2, 10)][0]
    column_total = result.identities[("column_total", 10)][0]
    assert "suppressed" in {result.closed.projection(sibling).state, result.closed.projection(column_total).state}
    assert result.closed.projection(result.identities[("row_total", 3)][0]).state == "no_data"
    assert result.closed.projection(result.identities[("column_total", 12)][0]).state == "no_data"
    zero = result.identities[("cell", 1, 11)][0]
    assert result.closed.projection(zero).value == 0
    assert any(zero in {term.cell for term in rel.terms} for rel in result.relationships)
    # Branch 11 has one authoritative child: Total - Child = 0 remains present.
    assert any({zero, result.identities[("column_total", 11)][0]} == {term.cell for term in rel.terms} for rel in result.relationships)
    assert any(result.identities["organization_total"][0] in {term.cell for term in rel.terms} for rel in result.relationships)


def test_sparse_value_permutation_and_transpose_keep_same_privacy_identity_pattern():
    kwargs = dict(context=_context(), dimension="branch", metric=MetricCode.FROZEN_ELIGIBLE, program_ids=(1,), column_values=(10, 11, 12), policy=SuppressCoordinate(program_id=1, branch_id=10))
    first = tm.build_talent_map_closed(facts={(1, 10): {"population": 3}, (1, 11): {"population": 6}}, **kwargs)
    second = tm.build_talent_map_closed(facts={(1, 10): {"population": 30}, (1, 11): {"population": 60}}, **kwargs)
    assert _suppressed_keys(first) == _suppressed_keys(second)
    programs = ({"id": 1, "label": "P"},); columns = ({"id": 10, "label": "A"}, {"id": 11, "label": "B"}, {"id": 12, "label": "C"})
    canonical = tm.serialize_talent_map(first, requested_orientation="program_branch", canonical_dimension="branch", metric=MetricCode.FROZEN_ELIGIBLE, programs=programs, columns=columns, context_payload={})
    transpose = tm.serialize_talent_map(first, requested_orientation="branch_program", canonical_dimension="branch", metric=MetricCode.FROZEN_ELIGIBLE, programs=programs, columns=columns, context_payload={})
    assert canonical["cells"] == transpose["cells"] and canonical["organization_total"] == transpose["organization_total"]


def test_dense_program_grade_row_and_grade_column_remain_connected():
    result = tm.build_talent_map_closed(
        context=_context(), dimension="grade", metric=MetricCode.FROZEN_ELIGIBLE,
        program_ids=(1, 2), column_values=("1", "2"),
        facts={(1, "1"): {"population": 3}, (1, "2"): {"population": 6}, (2, "1"): {"population": 7}, (2, "2"): {"population": 8}},
        policy=SuppressCoordinate(program_id=1, grade_level="1"),
    )
    protected = result.identities[("cell", 1, "1")][0]
    row_total = result.identities[("row_total", 1)][0]
    column_total = result.identities[("column_total", "1")][0]
    organization = result.identities["organization_total"][0]
    assert result.closed.projection(protected).state == "suppressed"
    assert "suppressed" in {result.closed.projection(row_total).state, result.closed.projection(column_total).state}
    assert any(organization in {term.cell for term in rel.terms} for rel in result.relationships)


def test_program_grade_partial_branch_scope_uses_only_authorized_historical_population(db, client):
    permissions(db, "talent_analytics.view")
    client[1]["user"] = actor(scope="BRANCH", branch=10)
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    body = get(client[0], "dimension=program_grade&metric=completion_coverage").json()
    assert body["scope"]["authorization_scope"] == "authorized_branches"
    assert body["organization_total"]["state"] in {"suppressed", "no_data"}
    assert all("value" not in cell for cell in body["cells"] if cell["state"] != "visible")


def test_empty_and_filtered_cells_preserve_no_data_not_zero(db, client):
    permissions(db, "talent_analytics.view")
    body = get(client[0], "dimension=program_grade&metric=completed&grade_level=12").json()
    assert body["organization_total"] == {"state": "no_data"}


def test_auth_availability_foreign_year_and_unauthorized_filter(db, client):
    assert get(client[0]).status_code == 403
    permissions(db, "talent_analytics.view")
    client[1]["availability"] = None; assert get(client[0]).status_code == 503
    client[1]["availability"] = AllowAvailability()
    client[1]["user"] = actor(scope="ORGANIZATION")
    assert client[0].get("/api/talent/organization-analytics/talent-map?academic_year_id=200").status_code in (403, 404)
    assert get(client[0], "branch_id=20").status_code == 400


def test_serializer_rejects_raw_or_unclosed_input():
    import talent_org_talent_map as tm
    with pytest.raises(TypeError, match="privacy-closed"):
        tm.serialize_talent_map(object(), requested_orientation="program_branch", canonical_dimension="branch", metric=None, programs=(), columns=(), context_payload={})
