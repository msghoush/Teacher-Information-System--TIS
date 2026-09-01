from __future__ import annotations

from datetime import datetime

import pytest

import models
from timetable_feasibility_service import (
    enqueue_feasibility_verification,
    latest_feasibility_payload,
)
from timetable_conflicts import (
    canonical_conflict_code,
    conflict_from_legacy,
    durable_terminal_conflict,
    safe_entity_reference,
)
from timetable_generation_service import generation_run_payload
from timetable_solution_validator import TimetableSolutionValidator
from timetable_readiness_service import TimetableReadinessService
from test_timetable_versioning import db  # noqa: F401 - shared isolated database


def test_taxonomy_distinguishes_domain_and_terminal_outcomes():
    assert canonical_conflict_code("teacher_collision") == "TEACHER_COLLISION"
    assert canonical_conflict_code("section_collision") == "SECTION_COLLISION"
    assert canonical_conflict_code("demand_mismatch") == "LESSON_REQUIREMENT_COUNT_VIOLATION"
    assert canonical_conflict_code("distribution_rule_invalid") == "SUBJECT_DISTRIBUTION_VIOLATION"
    assert canonical_conflict_code("grouped_activity_incomplete") == "GROUPED_ACTIVITY_VIOLATION"
    assert canonical_conflict_code("lock_missing") == "REGENERATION_LOCK_CONFLICT"
    assert canonical_conflict_code("solver_timeout") == "TIMEOUT"
    assert canonical_conflict_code("worker_error") == "SOLVER_EXECUTION_FAILURE"
    assert canonical_conflict_code("cancelled") == "CANCELLATION"


def test_public_conflict_hides_internal_requirement_and_constraint_ids():
    conflict = conflict_from_legacy(
        "demand_mismatch",
        "A section-subject demand is not scheduled exactly.",
        requirement_id="requirement:secret-hash",
        constraint_id="solver-clause-x",
    ).to_public_dict()

    rendered = str(conflict)
    assert conflict["correlation"] == {
        "requirement": True, "allocation": False, "constraint": True,
    }
    assert "secret-hash" not in rendered
    assert "solver-clause-x" not in rendered


def test_cross_tenant_entity_reference_is_redacted():
    reference = safe_entity_reference(
        kind="teacher", entity_id=999, label="Foreign Teacher", authorized=False
    )
    assert reference == {"kind": "teacher", "redacted": True}
    assert "999" not in str(reference)
    assert "Foreign Teacher" not in str(reference)


def test_validator_keeps_legacy_errors_and_adds_safe_requirement_correlation():
    problem = {
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "demands": [{
            "demand_id": "requirement:secret",
            "requirement_id": "requirement:secret",
            "requirement_source_fingerprint": "source-secret",
            "section_id": 1, "subject_code": "MAT", "teacher_id": 2,
            "required_weekly_periods": 1,
        }],
        "slots": [{"day_key": "monday", "period_index": 1}],
        "locks": [], "grouped_activities": [],
    }
    result = TimetableSolutionValidator().validate(
        problem=problem, placements=[], expected_fingerprint="same",
        current_fingerprint="same", expected_scope=problem["scope"],
        current_scope=problem["scope"],
    )

    assert "demand_mismatch" in {item["code"] for item in result["errors"]}
    conflict = next(
        item for item in result["conflicts"]
        if item["source_code"] == "demand_mismatch"
    )
    assert conflict["correlation"]["requirement"] is True
    assert "requirement:secret" not in str(conflict)
    assert "source-secret" not in str(conflict)


def test_generation_payload_distinguishes_infeasible_timeout_and_failure():
    expectations = {
        ("infeasible", "solver_infeasible_locks"): "REGENERATION_LOCK_CONFLICT",
        ("timed_out", "solver_timeout"): "TIMEOUT",
        ("internal_error", "worker_error"): "SOLVER_EXECUTION_FAILURE",
        ("cancelled", "cancelled"): "CANCELLATION",
    }
    for (status, category), expected in expectations.items():
        run = models.TimetableGenerationRun(
            public_id="run", request_mode="generate", status=status,
            progress_phase="failed", attempt_count=1,
            failure_category=category, safe_failure_details="Safe message.",
            finished_at=datetime(2026, 9, 1), diversity_configuration_json="{}",
        )
        payload = generation_run_payload(run)
        assert payload["failure_category"] == category
        assert payload["message"] == "Safe message."
        assert payload["conflicts"][0]["code"] == expected
        assert payload["conflicts"][0]["evidence_class"] == "DURABLE"


def test_transient_conflict_evidence_is_supported_without_persistence():
    conflict = conflict_from_legacy(
        "diagnostic_inconclusive", "Diagnostic isolation was inconclusive.",
        evidence_class="TRANSIENT", provenance="solver_diagnostic",
    ).to_public_dict()
    assert conflict["code"] == "INFEASIBLE"
    assert conflict["evidence_class"] == "TRANSIENT"


def test_readiness_preserves_legacy_finding_fields_and_adds_safe_conflict(db):
    result = TimetableReadinessService(db).evaluate(1, 10, 100)
    blocker = result["blockers"][0]
    assert {"code", "message", "severity", "display_label"} <= set(blocker)
    assert blocker["conflict"] in result["conflicts"]
    assert "requirement:" not in str(result["conflicts"])


@pytest.mark.parametrize(
    "status,diagnostic_code,expected_code",
    [
        ("conflict", "base", "INFEASIBLE"),
        ("timed_out", "verification_timeout", "TIMEOUT"),
        ("internal_error", "verification_failed", "SOLVER_EXECUTION_FAILURE"),
    ],
)
def test_feasibility_distinguishes_conflict_timeout_and_execution_failure(
    db, status, diagnostic_code, expected_code
):
    row, _run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    row.status = status
    row.diagnostics_json = (
        '[{"code":"' + diagnostic_code + '","message":"Safe diagnostic."}]'
    )
    db.flush()
    payload = latest_feasibility_payload(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    assert payload["diagnostics"][0]["code"] == diagnostic_code
    assert payload["conflicts"][0]["code"] == expected_code
    assert payload["conflicts"][0]["evidence_class"] == "DURABLE"
