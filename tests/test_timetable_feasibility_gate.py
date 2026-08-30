import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

import models
from routers import timetable as timetable_router
from timetable_feasibility_service import (
    enqueue_feasibility_verification,
    latest_feasibility_payload,
)
from timetable_generation_service import (
    TimetableGenerationError, build_generation_state, enqueue_generation,
)
from timetable_readiness_service import TimetableReadinessService
from test_timetable_versioning import db  # noqa: F401
import db_migrations
from scripts import run_migrations
from timetable_version_service import create_manual_draft
from test_timetable_stage2_routes import _request


def _configuration_complete(db):
    if not db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2001, subject_code="MAT"
    ).first():
        db.add(models.TeacherSectionAssignment(
            teacher_id=1001, planning_section_id=2001, subject_code="MAT"
        ))
    db.flush()
    assert TimetableReadinessService(db).evaluate(1, 10, 100)["status"] == "configuration_complete"


def test_configuration_complete_is_not_generation_ready_without_solver_proof(db):
    _configuration_complete(db)
    with pytest.raises(TimetableGenerationError) as exc:
        enqueue_generation(
            db, school_group_id=1, branch_id=10, academic_year_id=100,
            requested_by_user_id="U1", request_mode="generate",
            idempotency_key="blocked-before-verification",
        )
    assert exc.value.code == "feasibility_not_verified"


def test_feasibility_request_is_durable_reusable_and_not_duplicated(db):
    _configuration_complete(db)
    verification, run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    assert verification.status == "checking"
    assert run is not None
    assert json.loads(run.solver_configuration_json)["constraint_contract"] == "hard-only-feasibility"
    same, same_run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    assert same.id == verification.id
    assert same_run.id == run.id
    assert db.query(models.TimetableFeasibilityVerification).count() == 1


def test_verified_result_is_invalidated_by_authority_fingerprint_change(db):
    _configuration_complete(db)
    verification, _ = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    verification.status = "verified"
    verification.feasible_placements_json = "[]"
    db.query(models.TimetableGenerationRun).delete()
    db.flush()
    assert latest_feasibility_payload(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )["verified"] is True
    db.get(models.Subject, 3000).weekly_hours = 3
    db.flush()
    changed = latest_feasibility_payload(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    assert changed["verified"] is False
    assert changed["status"] == "not_checked"


def test_stale_only_inputs_remain_configuration_complete_and_verification_eligible(db):
    _configuration_complete(db)
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        origin="generated",
    )
    original_fingerprint = draft.authority_fingerprint
    db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000, subject_code="MAT"
    ).one().teacher_id = 1001
    db.flush()

    readiness = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert readiness["status"] == "stale_input"
    assert readiness["configuration_complete"] is True
    assert readiness["verification_eligible"] is True
    assert readiness["ready"] is False
    assert readiness["authority_fingerprint"] != original_fingerprint
    assert db.get(models.TimetableVersion, draft.id).authority_fingerprint == original_fingerprint


def test_stale_input_does_not_mask_configuration_blocker(db):
    _configuration_complete(db)
    create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    setting.periods_per_day = 0
    db.flush()

    readiness = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert readiness["status"] == "configuration_incomplete"
    assert readiness["configuration_complete"] is False
    assert readiness["verification_eligible"] is False
    assert readiness["inputs_stale"] is True
    assert {"periods_missing", "input_changed"} <= {
        item["code"] for item in readiness["blockers"]
    }


def test_stale_only_endpoint_captures_fresh_current_snapshot(db, monkeypatch):
    _configuration_complete(db)
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        origin="generated",
    )
    old_snapshot_id = draft.input_snapshot_id
    db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000, subject_code="MAT"
    ).one().teacher_id = 1001
    db.flush()
    user = SimpleNamespace(user_id="U1", branch_id=10, academic_year_id=100)
    monkeypatch.setattr(
        timetable_router, "_get_current_user_or_redirect",
        lambda request, session: (user, None),
    )
    monkeypatch.setattr(timetable_router.auth, "has_permission", lambda *args: True)
    monkeypatch.setattr(timetable_router, "dispatch_timetable_generation", lambda *args: None)

    response = timetable_router.create_feasibility_verification(_request({}), db)
    assert response.status_code == 202
    payload = json.loads(response.body)
    verification = db.query(models.TimetableFeasibilityVerification).one()
    assert payload["ok"] is True
    assert verification.input_snapshot_id != old_snapshot_id
    assert verification.authority_fingerprint == payload["feasibility"]["authority_fingerprint"]
    assert db.get(models.TimetableVersion, draft.id).input_snapshot_id == old_snapshot_id


def test_obsolete_failed_run_is_not_presented_after_authority_change(db):
    _configuration_complete(db)
    _, old_run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    old_run.status = "timed_out"
    old_run.progress_phase = "failed"
    db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000, subject_code="MAT"
    ).one().teacher_id = 1001
    db.flush()

    state = build_generation_state(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
    )
    assert state["active_run"] is None
    assert state["latest_run"] is None


def test_verified_current_inputs_can_enqueue_regeneration_without_mutating_stale_source(db):
    _configuration_complete(db)
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        origin="generated",
    )
    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1, is_locked=False,
    ))
    db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000, subject_code="MAT"
    ).one().teacher_id = 1001
    db.flush()
    current, verification_run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    current.status = "verified"
    current.feasible_placements_json = "[]"
    verification_run.status = "succeeded"
    verification_run.progress_phase = "complete"
    db.flush()

    source_fingerprint = draft.authority_fingerprint
    run = enqueue_generation(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1", request_mode="regenerate",
        source_public_id=draft.public_id, draft_public_id=draft.public_id,
        idempotency_key="stale-current-regeneration",
    )
    assert run.source_version_id == draft.id
    assert db.get(models.TimetableVersion, draft.id).authority_fingerprint == source_fingerprint
    assert db.query(models.TimetableEntry).filter_by(timetable_version_id=draft.id).count() == 1


def test_inconclusive_verification_can_retry_without_duplicate_active_work(db):
    _configuration_complete(db)
    verification, first_run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    verification.status = "timed_out"
    first_run.status = "timed_out"
    first_run.progress_phase = "failed"
    db.flush()
    retried, second_run = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    assert retried.id == verification.id
    assert second_run.id != first_run.id
    assert second_run.idempotency_key != first_run.idempotency_key


def test_feasibility_model_is_exactly_tenant_scoped(db):
    _configuration_complete(db)
    verification, _ = enqueue_feasibility_verification(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1",
    )
    assert latest_feasibility_payload(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )["public_id"] == verification.public_id
    with pytest.raises(ValueError):
        enqueue_feasibility_verification(
            db, school_group_id=2, branch_id=10, academic_year_id=100,
            requested_by_user_id="U1",
        )


def test_ui_uses_explicit_feasibility_states_and_no_optimistic_ready_label():
    source = open("templates/timetable.html", encoding="utf-8").read()
    assert "Configuration Complete — Verify Feasibility" in source
    assert "Checking Feasibility" in source
    assert "Feasibility Verified" in source
    assert "Feasibility could not be verified" in source
    assert 'const verified = Boolean(feasibility.verified)' in source
    assert 'const staleInput = readiness.status === "stale_input"' in source
    assert '? "Draft Needs Regeneration"' in source
    assert 'const verificationEligible = Boolean(readiness.verification_eligible)' in source
    assert 'const actionAvailable = Boolean(canGenerateTimetable && verificationEligible && !activeRun)' in source


def test_metadata_first_migration_sequence_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'feasibility-order.db'}")
    models.Base.metadata.create_all(engine, tables=run_migrations._baseline_metadata_tables())
    assert "timetable_feasibility_verifications" in inspect(engine).get_table_names()
    applied = db_migrations.run_pending_migrations(engine)
    assert "20260830_003_timetable_feasibility_verification" in applied
    assert db_migrations.run_pending_migrations(engine) == []
