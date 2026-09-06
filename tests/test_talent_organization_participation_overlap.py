"""M10 B8 Participation Overlap end-to-end tests."""

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event

import models
from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import (
    AllowAllTestPolicy, DeterministicSuppressionTestPolicy,
    resolve_privacy_policy_provider,
)
from talent_org_intelligence_service import (
    resolve_organization_analytics_availability_provider,
    resolve_organization_analytics_breadth_policy,
)
import talent_org_participation_overlap as overlap
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import (
    AllowAvailability, AllowBreadth, RejectBreadth, actor, db, permissions,
)


@pytest.fixture()
def client(db):
    app = FastAPI(); app.include_router(route.router)
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


def get(client, query=""):
    return client.get("/api/talent/organization-analytics/participation-overlap?academic_year_id=100" + ("&" + query if query else ""))


def add_member(db, *, member_id, cycle_id, program_id, framework_id, student_id, branch_id):
    db.add(models.TalentAssessmentCyclePopulationMember(
        id=member_id, school_group_id=1, cycle_id=cycle_id, program_id=program_id,
        academic_year_id=100, framework_version_id=framework_id, student_id=student_id,
        academic_placement_id=member_id, branch_id=branch_id, grade_level="1",
        section_name="Frozen", population_effective_at=datetime(2026, 10, 1),
    ))
    db.commit()


def pair(body, first, second):
    canonical = sorted((first, second))
    return next(item for item in body["canonical_pairs"] if item["program_ids"] == canonical)


def test_route_auth_availability_year_filters_and_breadth(db, client):
    assert get(client[0]).status_code == 403
    permissions(db, "talent_analytics.view")
    client[1]["user"] = actor(scope="ORGANIZATION")
    assert client[0].get("/api/talent/organization-analytics/participation-overlap?academic_year_id=200").status_code == 404
    assert get(client[0], "program_ids=999").status_code == 400
    client[1]["availability"] = None; assert get(client[0]).status_code == 503
    client[1]["availability"] = AllowAvailability(); client[1]["breadth"] = RejectBreadth()
    assert get(client[0]).status_code == 413


def test_distinct_semantics_diagonal_symmetry_zero_and_no_data(db, client):
    permissions(db, "talent_analytics.view")
    add_member(db, member_id=5, cycle_id=202, program_id=2, framework_id=102, student_id=1001, branch_id=10)
    db.add(models.TalentAssessmentCycle(id=205, school_group_id=1, program_id=1, academic_year_id=100, framework_version_id=101, title="Draft", status="draft", revision=1, population_effective_at=datetime(2026,10,1)))
    db.commit(); add_member(db, member_id=7, cycle_id=205, program_id=1, framework_id=101, student_id=1999, branch_id=10)
    body = get(client[0]).json()
    assert pair(body, 1, 1)["value"] == 2
    assert pair(body, 2, 2)["value"] == 2
    assert pair(body, 1, 2)["value"] == 1
    assert body["matrix"][0]["cells"][1] == {"program_id": 2, "state": "visible", "value": 1}
    assert body["matrix"][1]["cells"][0] == {"program_id": 1, "state": "visible", "value": 1}
    db.add(models.TalentAssessmentCycle(id=204, school_group_id=1, program_id=1, academic_year_id=100, framework_version_id=101, title="Duplicate", status="open", revision=1, population_effective_at=datetime(2026,10,1)))
    db.commit(); add_member(db, member_id=6, cycle_id=204, program_id=1, framework_id=101, student_id=1001, branch_id=10)
    assert pair(get(client[0]).json(), 1, 1)["value"] == 2
    db.query(models.TalentAssessmentCyclePopulationMember).filter_by(id=5).delete(); db.commit()
    assert pair(get(client[0]).json(), 1, 2) == {"program_ids": [1, 2], "state": "visible", "value": 0}
    db.query(models.TalentAssessmentCyclePopulationMember).filter_by(program_id=2).delete(); db.commit()
    assert pair(get(client[0]).json(), 1, 2)["state"] == "no_data"
    assert pair(get(client[0]).json(), 2, 2)["state"] == "no_data"


def test_historical_branch_scope_is_applied_before_intersection(db, client):
    permissions(db, "talent_analytics.view")
    add_member(db, member_id=5, cycle_id=202, program_id=2, framework_id=102, student_id=1001, branch_id=10)
    add_member(db, member_id=6, cycle_id=202, program_id=2, framework_id=102, student_id=1002, branch_id=11)
    assert pair(get(client[0]).json(), 1, 2)["value"] == 2
    client[1]["user"] = actor(scope="BRANCH", branch=10)
    assert pair(get(client[0]).json(), 1, 2)["value"] == 1
    placement = db.get(models.StudentAcademicPlacement, 1)
    placement.branch_id = 11; placement.grade_level = "12"; db.commit()
    assert pair(get(client[0]).json(), 1, 2)["value"] == 1


def test_privacy_closed_serialization_and_no_deferred_domain_queries(db, client):
    permissions(db, "talent_analytics.view")
    add_member(db, member_id=5, cycle_id=202, program_id=2, framework_id=102, student_id=1001, branch_id=10)
    client[1]["policy"] = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    statements = []
    listener = lambda _c, _u, statement, _p, _x, _m: statements.append(statement.lower())
    event.listen(db.bind, "before_cursor_execute", listener)
    try:
        body = get(client[0]).json()
    finally:
        event.remove(db.bind, "before_cursor_execute", listener)
    assert pair(body, 1, 2)["state"] == "suppressed"
    rendered = str(body).lower()
    assert "student_id" not in rendered and "raw_value" not in rendered and "threshold" not in rendered
    assert not any("talent_review_candidates" in sql or "talent_official_identifications" in sql for sql in statements)
    aggregate = [sql for sql in statements if "participation_first" in sql]
    assert len(aggregate) == 1 and "select distinct" in aggregate[0] and "participation_second" in aggregate[0]
    with pytest.raises(TypeError):
        overlap.serialize_projection({}, programs=(), context_payload={})


def test_identity_graph_and_breadth_shape_are_canonical(db, client):
    permissions(db, "talent_analytics.view")
    class CaptureBreadth(AllowBreadth):
        def allows(self, **shape):
            self.shape = shape
            return True
    capture = CaptureBreadth(); client[1]["breadth"] = capture
    body = get(client[0], "program_ids=2&program_ids=1").json()
    assert body["scope"]["canonical_pair_count"] == 3
    assert body["scope"]["presentation_cell_count"] == 4
    assert [program["name"] for program in body["programs"]] == ["Arts", "STEM"]
    assert pair(body, 1, 2)["program_ids"] == [1, 2]
    assert capture.shape == {
        "projection_family": "participation_overlap", "row_count": 2,
        "column_count": 2, "prospective_cells": 4,
        "relationship_estimate": 0, "program_count": 2,
        "prospective_pair_count": 3,
    }
    assert not hasattr(overlap.ParticipationOverlapClosedProjection, "relationships")


def test_route_display_name_order_can_diverge_from_canonical_numeric_pair_order(db, client):
    permissions(db, "talent_analytics.view")
    db.query(models.TalentProgram).filter_by(id=1).update({"name": "Zeta"})
    db.query(models.TalentProgram).filter_by(id=2).update({"name": "Alpha"})
    db.commit()
    add_member(db, member_id=5, cycle_id=202, program_id=2, framework_id=102, student_id=1001, branch_id=10)

    response = get(client[0])
    assert response.status_code == 200
    body = response.json()
    assert [(item["id"], item["name"]) for item in body["programs"]] == [(2, "Alpha"), (1, "Zeta")]
    alpha_zeta = body["matrix"][0]["cells"][1]
    zeta_alpha = body["matrix"][1]["cells"][0]
    assert alpha_zeta == {"program_id": 1, "state": "visible", "value": 1}
    assert zeta_alpha == {"program_id": 2, "state": "visible", "value": 1}
    assert [item["program_ids"] for item in body["canonical_pairs"]].count([1, 2]) == 1
    assert len(body["matrix"]) ** 2 == sum(len(row["cells"]) for row in body["matrix"])
    assert len(body["canonical_pairs"]) == 3


def test_three_program_noncanonical_display_order_uses_one_pair_and_privacy_decision():
    context = SimpleNamespace(school_group_id=1, academic_year_id=100)
    display_program_ids = (7, 10, 2)
    counts = {
        (2, 2): 4, (2, 7): 1, (2, 10): 2,
        (7, 7): 5, (7, 10): 3, (10, 10): 6,
    }

    class CountingPolicy(AllowAllTestPolicy):
        def __init__(self):
            super().__init__(); self.calls = []

        def evaluate_cell(self, **kwargs):
            self.calls.append(kwargs)
            return super().evaluate_cell(**kwargs)

    policy = CountingPolicy()
    result = overlap.build_closed_projection(
        context=context, program_ids=display_program_ids,
        overlap_counts=counts, policy=policy,
    )
    body = overlap.serialize_projection(
        result,
        programs=tuple({"id": item, "name": str(item)} for item in display_program_ids),
        context_payload={},
    )
    expected_pairs = {(2, 2), (2, 7), (2, 10), (7, 7), (7, 10), (10, 10)}
    assert set(result.identities) == expected_pairs
    assert len(policy.calls) == len(expected_pairs)
    assert len(body["canonical_pairs"]) == len(expected_pairs)
    assert len({tuple(item["program_ids"]) for item in body["canonical_pairs"]}) == len(expected_pairs)
    assert sum(len(row["cells"]) for row in body["matrix"]) == 9
    assert body["matrix"][0]["cells"][1]["value"] == body["matrix"][1]["cells"][0]["value"] == 3
    assert body["matrix"][2]["cells"][2]["value"] == 4
    assert overlap.canonical_pair_key(10, 2) == overlap.canonical_pair_key(2, 10) == (2, 10)
