"""M10 B7 Program Portfolio route tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from auth import get_current_user
from dependencies import get_m10_organization_analytics_db
from talent_analytics_privacy import AllowAllTestPolicy, DeterministicSuppressionTestPolicy, resolve_privacy_policy_provider
from talent_org_intelligence_service import resolve_organization_analytics_availability_provider, resolve_organization_analytics_breadth_policy
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import AllowAvailability, AllowBreadth, RejectBreadth, actor, db, permissions

@pytest.fixture()
def portfolio_client(db):
    app=FastAPI(); app.include_router(route.router)
    state={"user":actor(scope="ORGANIZATION"),"availability":AllowAvailability(),"breadth":AllowBreadth(),"policy":AllowAllTestPolicy()}
    app.dependency_overrides[get_m10_organization_analytics_db]=lambda:db; app.dependency_overrides[get_current_user]=lambda:state["user"]
    app.dependency_overrides[resolve_organization_analytics_availability_provider]=lambda:state["availability"]
    app.dependency_overrides[resolve_organization_analytics_breadth_policy]=lambda:state["breadth"]
    app.dependency_overrides[resolve_privacy_policy_provider]=lambda:state["policy"]
    return TestClient(app),state

def get(c,q=""): return c.get("/api/talent/organization-analytics/program-portfolio?academic_year_id=100"+("&"+q if q else ""))

def test_portfolio_common_metrics_order_no_data_zero_and_execution(db,portfolio_client):
    permissions(db,"talent_analytics.view")
    r=get(portfolio_client[0]); assert r.status_code==200
    b=r.json(); assert [x["program"]["name"] for x in b["programs"]]==["Arts","STEM"]
    arts,stem=b["programs"]
    assert arts["metrics"]["frozen_eligible"]["value"]==2
    assert arts["metrics"]["completed"]["value"]==1
    assert arts["metrics"]["completion_coverage"]["percentage"]==50
    assert stem["metrics"]["completed"]["value"]==0
    assert stem["metrics"]["required_period_execution"]=={"state":"no_data"}
    assert arts["metrics"]["required_period_execution"]["denominator"]==3
    assert b["comparability"]=={"mode":"common_factual_metrics","ranking":False,"universal_score":False}
    assert "score" not in arts and "rank" not in arts

def test_portfolio_sensitive_fields_omitted_then_identified_only(db,portfolio_client):
    permissions(db,"talent_analytics.view")
    b=get(portfolio_client[0]).json(); assert "candidate_count" not in b["programs"][0]["metrics"] and "identified_count" not in b["totals"]
    permissions(db,"talent_review_candidates.view","talent_official_identifications.view"); portfolio_client[1]["user"]=actor(scope="ORGANIZATION")
    b=get(portfolio_client[0]).json(); assert b["totals"]["candidate_count"]["value"]==1 and b["totals"]["identified_count"]["value"]==1

def test_portfolio_privacy_breadth_auth_filters_and_safe_serializer(db,portfolio_client):
    assert get(portfolio_client[0]).status_code==403
    permissions(db,"talent_analytics.view"); portfolio_client[1]["user"]=actor(scope="ORGANIZATION")
    portfolio_client[1]["breadth"]=RejectBreadth(); assert get(portfolio_client[0]).status_code==413
    portfolio_client[1]["breadth"]=AllowBreadth(); assert get(portfolio_client[0],"program_ids=999").status_code==400
    portfolio_client[1]["policy"]=DeterministicSuppressionTestPolicy(minimum_cohort=2)
    b=get(portfolio_client[0]).json()
    assert any(v["state"]=="suppressed" for row in b["programs"] for v in row["metrics"].values())
    assert "raw_value" not in str(b)
    import talent_org_b7
    with pytest.raises(TypeError): talent_org_b7.serialize_projection({},programs=(),metrics=(),context_payload={})

def test_configured_inactive_program_without_population_is_included_as_no_data(db,portfolio_client):
    import models
    db.add(models.TalentProgram(id=4,school_group_id=1,name="Quiet",status="retired"))
    db.add(models.TalentProgramAcademicYearConfiguration(id=4,school_group_id=1,program_id=4,academic_year_id=100,is_enabled=True,eligible_grade_levels_csv="1"))
    db.commit(); permissions(db,"talent_analytics.view")
    row=next(item for item in get(portfolio_client[0]).json()["programs"] if item["program"]["id"]==4)
    assert row["program"]["configured"] is True and row["program"]["active"] is False
    assert row["metrics"]["frozen_eligible"]=={"state":"no_data"}
    assert row["metrics"]["completed"]=={"state":"no_data"}
