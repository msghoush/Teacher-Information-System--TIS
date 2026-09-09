"""M10 B7 Branch Intelligence route tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import models
from auth import get_current_user
from dependencies import get_m10_organization_analytics_db
from talent_analytics_privacy import AllowAllTestPolicy, resolve_privacy_policy_provider
from talent_org_intelligence_service import resolve_organization_analytics_availability_provider, resolve_organization_analytics_breadth_policy
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import AllowAvailability, AllowBreadth, actor, db, permissions

@pytest.fixture()
def branch_client(db):
    app=FastAPI(); app.include_router(route.router)
    state={"user":actor(scope="ORGANIZATION"),"availability":AllowAvailability(),"breadth":AllowBreadth(),"policy":AllowAllTestPolicy()}
    app.dependency_overrides[get_m10_organization_analytics_db]=lambda:db; app.dependency_overrides[get_current_user]=lambda:state["user"]
    app.dependency_overrides[resolve_organization_analytics_availability_provider]=lambda:state["availability"]
    app.dependency_overrides[resolve_organization_analytics_breadth_policy]=lambda:state["breadth"]
    app.dependency_overrides[resolve_privacy_policy_provider]=lambda:state["policy"]
    return TestClient(app),state

def get(c,b=10,q=""): return c.get(f"/api/talent/organization-analytics/branches/{b}?academic_year_id=100"+("&"+q if q else ""))

def test_branch_program_facts_historical_scope_and_no_execution(db,branch_client):
    permissions(db,"talent_analytics.view")
    b=get(branch_client[0]).json(); assert b["branch"]=={"id":10,"name":"North"}
    assert b["totals"]["frozen_eligible"]["value"]==2
    assert all("required_period_execution" not in row["metrics"] for row in b["programs"])
    placement=db.get(models.StudentAcademicPlacement,1); placement.branch_id=11; placement.grade_level="12"; db.commit()
    assert get(branch_client[0]).json()["totals"]["frozen_eligible"]["value"]==2

def test_branch_scope_and_foreign_branch_are_non_enumerating(db,branch_client):
    permissions(db,"talent_analytics.view"); branch_client[1]["user"]=actor(scope="BRANCH",branch=10)
    assert get(branch_client[0],10).status_code==200
    assert get(branch_client[0],11).status_code==404
    assert get(branch_client[0],20).status_code==404

def test_branch_sensitive_omission_and_shared_b6_identity(db,branch_client):
    permissions(db,"talent_analytics.view")
    b=get(branch_client[0]).json(); assert "candidate_count" not in b["totals"]
    permissions(db,"talent_review_candidates.view","talent_official_identifications.view"); branch_client[1]["user"]=actor(scope="ORGANIZATION")
    b=get(branch_client[0]).json(); assert b["totals"]["candidate_count"]["value"]==1 and b["totals"]["identified_count"]["value"]==1
    import talent_org_b7, talent_org_talent_map as tm
    context=type("C",(),{"school_group_id":1,"academic_year_id":100})()
    b7id=talent_org_b7._identity(context, talent_org_b7.MetricCode.COMPLETED, talent_org_b7.MeasureComponent.COUNT, program_id=1, branch_id=10)
    b6id=tm._identity(context, tm.MetricCode.COMPLETED, tm.MeasureComponent.COUNT, program_id=1, dimension="branch", dimension_value=10)
    assert b7id==b6id
