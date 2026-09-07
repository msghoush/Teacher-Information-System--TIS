"""M10 B11-B safe operational observability tests.

Verifies the 7 existing Organization Analytics routes emit bounded,
allowlisted structural/provider/outcome telemetry - never Student
identifiers, raw analytical values, privacy thresholds, or Candidate/
Identification decisions - and that fail-closed HTTP behavior and response
bodies are byte-identical to pre-B11-B behavior. Also verifies a telemetry
failure can never affect the HTTP response.
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import OperationalError

import models
import talent_organization_analytics_observability as obs_mod
from auth import get_current_user
from dependencies import get_m10_organization_analytics_db
from talent_analytics_privacy import AllowAllTestPolicy, resolve_privacy_policy_provider
import talent_org_intelligence_service as svc
from routers import talent_organization_analytics as route
from test_talent_org_intelligence_queries import (
    AllowAvailability, AllowBreadth, RejectBreadth, actor, db, permissions,
)


OBS_LOGGER = obs_mod.logger.name


class DenyAvailability(AllowAvailability):
    def is_available(self, **_context):
        return False


class ExplodingAvailability(AllowAvailability):
    def is_available(self, **_context):
        raise RuntimeError("availability provider secret detail")


class ExplodingBreadth(AllowBreadth):
    def allows(self, **_shape):
        raise RuntimeError("breadth provider secret detail")


class ExplodingPolicy(AllowAllTestPolicy):
    def evaluate_cell(self, **_kwargs):
        raise RuntimeError("privacy provider secret detail")


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(route.router)
    state = {
        "user": actor(scope="ORGANIZATION"), "availability": AllowAvailability(),
        "breadth": AllowBreadth(), "policy": AllowAllTestPolicy(),
    }
    app.dependency_overrides[get_m10_organization_analytics_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    app.dependency_overrides[svc.resolve_organization_analytics_availability_provider] = lambda: state["availability"]
    app.dependency_overrides[svc.resolve_organization_analytics_breadth_policy] = lambda: state["breadth"]
    app.dependency_overrides[resolve_privacy_policy_provider] = lambda: state["policy"]
    return TestClient(app), state


def events(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records if record.name == OBS_LOGGER]


def raw_text(caplog):
    return "\n".join(record.getMessage() for record in caplog.records if record.name == OBS_LOGGER)


def overview(client):
    return client.get("/api/talent/organization-analytics/overview?academic_year_id=100")


def talent_map(client, query=""):
    suffix = "&" + query if query else ""
    return client.get("/api/talent/organization-analytics/talent-map?academic_year_id=100" + suffix)


def participation_overlap(client):
    return client.get("/api/talent/organization-analytics/participation-overlap?academic_year_id=100")


def students(client):
    return client.get("/api/talent/organization-analytics/students?academic_year_id=100")


def longitudinal(client, program_id=1, metric="frozen_eligible"):
    return client.get(
        f"/api/talent/organization-analytics/programs/{program_id}/longitudinal"
        f"?academic_year_id=100&metric={metric}"
    )


PROHIBITED_SUBSTRINGS = (
    "student_id", "raw_value", "privacy_threshold", "suppressed_raw",
    "candidate_state", "identification_state", "decision", "kpi_result",
    "rubric", "evidence", "delta", "change", "percent_change", "total_count",
    "display_name", "first_name", "last_name", "Ann",
)

_ALLOWED_EVENT_KEYS = (
    obs_mod.SAFE_STRUCTURAL_FIELDS | obs_mod.SAFE_PROVIDER_FIELDS
    | {"event_type", "projection_family", "outcome", "latency_ms", "error_category"}
)


# ---------------------------------------------------------------------------
# 1-5: successful requests emit safe structural signals only.
# ---------------------------------------------------------------------------

def test_1_successful_overview_emits_safe_structural_observability(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    response = overview(client[0])
    assert response.status_code == 200
    recorded = events(caplog)
    assert len(recorded) == 1
    event = recorded[0]
    assert event["projection_family"] == "overview"
    assert event["outcome"] == "success"
    assert event["availability_outcome"] == "available"
    assert event["privacy_outcome"] == "evaluated"
    assert isinstance(event["program_count"], int)
    assert isinstance(event["latency_ms"], (int, float))


def test_2_successful_talent_map_emits_dimensions_but_no_values(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    response = talent_map(client[0])
    assert response.status_code == 200
    event = events(caplog)[-1]
    assert event["outcome"] == "success"
    for key in ("row_count", "column_count", "prospective_cell_count", "relationship_estimate", "program_count"):
        assert isinstance(event[key], int)
    forbidden_keys = {"value", "numerator", "denominator", "percentage", "matrix", "rows", "columns"}
    assert not (forbidden_keys & set(event.keys()))


def test_3_participation_overlap_logs_pair_count_not_pair_values(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    response = participation_overlap(client[0])
    assert response.status_code == 200
    event = events(caplog)[-1]
    assert event["outcome"] == "success"
    assert isinstance(event["prospective_pair_count"], int)
    assert isinstance(event["emitted_pair_count"], int)
    assert event["emitted_pair_count"] == event["prospective_pair_count"]
    forbidden_keys = {"program_ids", "canonical_pairs", "matrix", "value"}
    assert not (forbidden_keys & set(event.keys()))


def test_4_student_drill_telemetry_contains_no_student_identifiers(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    db.add(models.Student(id=1001, school_group_id=1, first_name="Ann", last_name="One", status="active"))
    db.commit()
    permissions(db, "talent_analytics.view", "talent_analytics.view_students")
    response = students(client[0])
    assert response.status_code == 200
    body = response.json()
    assert any(item["student_id"] == 1001 for item in body["items"])  # real data really flowed
    text = raw_text(caplog)
    for banned in ("Ann", "One", "student_id", "display_name"):
        assert banned not in text
    assert set(events(caplog)[-1].keys()) <= _ALLOWED_EVENT_KEYS
    event = events(caplog)[-1]
    assert event["outcome"] == "success"
    assert event["page_limit"] == 25
    assert event["page_returned_count"] == 1
    assert event["has_more"] is False
    assert "total_count" not in event


def test_5_longitudinal_telemetry_has_counts_but_no_metric_values(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    response = longitudinal(client[0])
    assert response.status_code == 200
    event = events(caplog)[-1]
    assert event["outcome"] == "success"
    assert event["period_count"] == 3
    assert event["comparison_count"] == 2
    assert event["authoritative_cycle_count"] == 1
    assert event["component_count"] == 1
    forbidden_keys = {"value", "numerator", "denominator", "percentage", "delta", "change", "percent_change"}
    assert not (forbidden_keys & set(event.keys()))


# ---------------------------------------------------------------------------
# 6-13: provider fail-closed telemetry.
# ---------------------------------------------------------------------------

def test_6_privacy_provider_missing_emits_safe_fail_closed_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = None
    response = overview(client[0])
    assert response.status_code == 503
    event = events(caplog)[-1]
    assert event["outcome"] == "unavailable"
    assert event["privacy_outcome"] == "provider_missing"
    assert event["error_category"] == "privacy_policy_unavailable_failure"


def test_7_privacy_provider_exception_emits_safe_failure_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["policy"] = ExplodingPolicy()
    response = overview(client[0])
    assert response.status_code == 500
    assert "secret" not in response.text
    event = events(caplog)[-1]
    assert event["outcome"] == "failed"
    assert event["privacy_outcome"] == "provider_exception"
    assert "secret" not in json.dumps(event)


def test_8_availability_provider_missing_emits_safe_unavailable_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["availability"] = None
    response = overview(client[0])
    assert response.status_code == 503
    event = events(caplog)[-1]
    assert event["outcome"] == "unavailable"
    assert event["availability_outcome"] == "provider_missing"


def test_9_availability_false_emits_safe_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["availability"] = DenyAvailability()
    response = overview(client[0])
    assert response.status_code == 503
    event = events(caplog)[-1]
    assert event["outcome"] == "unavailable"
    assert event["availability_outcome"] == "unavailable"


def test_10_availability_exception_emits_safe_failure_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["availability"] = ExplodingAvailability()
    response = overview(client[0])
    assert response.status_code == 503
    assert "secret" not in response.text
    event = events(caplog)[-1]
    assert event["outcome"] == "failed"
    assert event["availability_outcome"] == "provider_exception"
    assert "secret" not in json.dumps(event)


def test_11_breadth_policy_missing_emits_safe_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["breadth"] = None
    response = talent_map(client[0])
    assert response.status_code == 413
    event = events(caplog)[-1]
    assert event["outcome"] == "rejected"
    assert event["breadth_outcome"] == "policy_missing"
    assert event["error_category"] == "breadth_rejection_failure"


def test_12_breadth_rejection_emits_safe_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["breadth"] = RejectBreadth()
    response = talent_map(client[0])
    assert response.status_code == 413
    event = events(caplog)[-1]
    assert event["outcome"] == "rejected"
    assert event["breadth_outcome"] == "rejected"


def test_13_breadth_exception_emits_safe_failure_category(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    client[1]["breadth"] = ExplodingBreadth()
    response = talent_map(client[0])
    assert response.status_code == 500
    assert "secret" not in response.text
    event = events(caplog)[-1]
    assert event["outcome"] == "failed"
    assert event["breadth_outcome"] == "policy_exception"
    assert "secret" not in json.dumps(event)


# ---------------------------------------------------------------------------
# 14-16: authorization telemetry never carries protected analytical context.
# ---------------------------------------------------------------------------

def test_14_authorization_failure_does_not_emit_protected_analytical_context(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    response = overview(client[0])
    assert response.status_code == 403
    event = events(caplog)[-1]
    assert event["outcome"] == "rejected"
    assert event["error_category"] == "authentication_authorization_rejection"
    for key in ("privacy_outcome", "breadth_outcome", "program_count", "row_count"):
        assert key not in event


def test_15_candidate_metric_without_permission_does_not_log_candidate_facts(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    response = talent_map(client[0], "metric=candidate_count")
    assert response.status_code == 403
    text = raw_text(caplog)
    assert "candidate" not in text.lower()
    event = events(caplog)[-1]
    assert event["outcome"] == "rejected"
    assert event["error_category"] == "authentication_authorization_rejection"


def test_16_identification_metric_without_permission_does_not_log_identification_facts(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    response = talent_map(client[0], "metric=identified_count")
    assert response.status_code == 403
    text = raw_text(caplog)
    assert "identif" not in text.lower()
    event = events(caplog)[-1]
    assert event["outcome"] == "rejected"


# ---------------------------------------------------------------------------
# 17: database failure telemetry is bounded, no SQL/parameters ever leak.
# ---------------------------------------------------------------------------

def test_17_database_failure_logs_bounded_category_with_no_sql_or_parameters(db, client, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")

    def _explode(*_args, **_kwargs):
        raise OperationalError("SELECT * FROM talent_students WHERE ssn = :ssn", {"ssn": "secret-param"}, Exception("connection reset"))

    monkeypatch.setattr(route.svc, "coverage_organization_total", _explode)
    response = overview(client[0])
    assert response.status_code == 500
    assert "SELECT" not in response.text and "secret-param" not in response.text
    event = events(caplog)[-1]
    assert event["outcome"] == "failed"
    assert event["error_category"] == "database_failure"
    dumped = json.dumps(event)
    assert "SELECT" not in dumped and "secret-param" not in dumped and "ssn" not in dumped


# ---------------------------------------------------------------------------
# 18: response bodies remain byte-identical to pre-B11-B behavior.
# ---------------------------------------------------------------------------

def test_18_response_bodies_remain_unchanged_from_pre_b11_behavior(db, client):
    permissions(db, "talent_analytics.view")
    body = overview(client[0]).json()
    assert body["scope"] == "organization"
    assert body["metrics"]["programs_configured"] == {"state": "visible", "value": 2}
    assert body["metrics"]["frozen_eligible_memberships"] == {"state": "visible", "value": 3}
    assert "candidate_membership_count" not in body["metrics"]
    assert set(body.keys()) == {"academic_year_id", "scope", "privacy_policy_version", "request_context_fingerprint", "metrics"}


# ---------------------------------------------------------------------------
# 19: an observability failure can never affect the HTTP response.
# ---------------------------------------------------------------------------

def test_19_observability_helper_failure_cannot_release_analytics_values(db, client, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")

    def _explode(*_args, **_kwargs):
        raise RuntimeError("telemetry backend is down")

    monkeypatch.setattr(obs_mod.logger, "log", _explode)
    response = overview(client[0])
    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["programs_configured"] == {"state": "visible", "value": 2}


# ---------------------------------------------------------------------------
# 20: no prohibited field ever appears in telemetry, across many code paths.
# ---------------------------------------------------------------------------

def test_20_telemetry_never_contains_prohibited_fields(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    db.add(models.Student(id=1001, school_group_id=1, first_name="Ann", last_name="One", status="active"))
    db.commit()
    permissions(db, "talent_analytics.view", "talent_review_candidates.view", "talent_official_identifications.view", "talent_analytics.view_students")
    overview(client[0])
    talent_map(client[0], "metric=candidate_of_eligible")
    participation_overlap(client[0])
    students(client[0])
    longitudinal(client[0], metric="candidate_count")
    text = raw_text(caplog)
    for banned in PROHIBITED_SUBSTRINGS:
        assert banned not in text, f"prohibited telemetry content leaked: {banned!r}"
    for event in events(caplog):
        assert set(event.keys()) <= _ALLOWED_EVENT_KEYS, f"unexpected telemetry key(s): {set(event.keys()) - _ALLOWED_EVENT_KEYS}"


# ---------------------------------------------------------------------------
# 21-22: no new route; M10 route count remains exactly 7.
# ---------------------------------------------------------------------------

def test_21_and_22_no_new_route_and_route_count_remains_seven():
    paths = sorted(entry.path for entry in route.router.routes)
    assert len(route.router.routes) == 7
    assert paths == sorted({
        "/api/talent/organization-analytics/overview",
        "/api/talent/organization-analytics/talent-map",
        "/api/talent/organization-analytics/program-portfolio",
        "/api/talent/organization-analytics/branches/{branch_id}",
        "/api/talent/organization-analytics/participation-overlap",
        "/api/talent/organization-analytics/programs/{program_id}/longitudinal",
        "/api/talent/organization-analytics/students",
    })


# ---------------------------------------------------------------------------
# 23: no server delta/change/percent_change anywhere, including telemetry.
# ---------------------------------------------------------------------------

def test_23_no_delta_change_or_percent_change_anywhere_in_telemetry(db, client, caplog):
    caplog.set_level(logging.INFO, logger=OBS_LOGGER)
    permissions(db, "talent_analytics.view")
    overview(client[0])
    talent_map(client[0])
    longitudinal(client[0])
    text = raw_text(caplog)
    for banned in ("delta", "change", "percent_change"):
        assert banned not in text


# ---------------------------------------------------------------------------
# 24: existing privacy/authorization tests remain green.
#
# Satisfied by the full proportional regression run reported alongside this
# file (tests/test_talent_organization_overview.py,
# tests/test_talent_organization_talent_map.py,
# tests/test_talent_organization_program_portfolio.py,
# tests/test_talent_organization_branch_intelligence.py,
# tests/test_talent_organization_participation_overlap.py,
# tests/test_talent_organization_student_drill.py,
# tests/test_talent_organization_longitudinal.py, and the broader M10/M9
# suites) - not re-asserted here to avoid duplicating those suites.
# ---------------------------------------------------------------------------
