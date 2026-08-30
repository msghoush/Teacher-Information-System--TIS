import json

import pytest
from sqlalchemy import create_engine, inspect

import models
from timetable_feasibility_service import (
    enqueue_feasibility_verification,
    latest_feasibility_payload,
)
from timetable_generation_service import TimetableGenerationError, enqueue_generation
from timetable_readiness_service import TimetableReadinessService
from test_timetable_versioning import db  # noqa: F401
import db_migrations
from scripts import run_migrations


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


def test_metadata_first_migration_sequence_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'feasibility-order.db'}")
    models.Base.metadata.create_all(engine, tables=run_migrations._baseline_metadata_tables())
    assert "timetable_feasibility_verifications" in inspect(engine).get_table_names()
    applied = db_migrations.run_pending_migrations(engine)
    assert "20260830_003_timetable_feasibility_verification" in applied
    assert db_migrations.run_pending_migrations(engine) == []
