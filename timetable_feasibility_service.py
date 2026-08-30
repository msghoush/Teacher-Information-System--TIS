from __future__ import annotations

import json
import secrets

from sqlalchemy.orm import Session

import models
from timetable_snapshot_service import build_current_snapshot_data, create_current_input_snapshot
from timetable_version_service import resolve_operational_version, resolve_scope_school_group_id


def _locks(db: Session, school_group_id: int, branch_id: int, academic_year_id: int) -> list[dict]:
    version = resolve_operational_version(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if version is None:
        return []
    rows = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == version.id,
        models.TimetableEntry.is_locked.is_(True),
    ).all()
    return [{
        "section_id": int(row.planning_section_id),
        "subject_code": str(row.subject_code or "").strip().upper(),
        "teacher_id": int(row.teacher_id),
        "day_key": str(row.day_key or "").strip().lower(),
        "period_index": int(row.period_index),
        "is_locked": True,
    } for row in rows]


def feasibility_constraint_configuration() -> dict:
    return {
        "stage": "feasibility-gate-1",
        "rules": [
            "exact_demand", "section_slot_exclusivity", "teacher_slot_exclusivity",
            "canonical_slots", "planning_teacher_authority", "preserve_locks",
            "hard_subject_distribution_rules", "hard_teacher_scheduling_rules",
            "grouped_activities_resources",
        ],
        "generation": {"request_mode": "generate", "source_edit_revision": None},
    }


def current_feasibility_input(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int):
    return build_current_snapshot_data(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
        locks=_locks(db, school_group_id, branch_id, academic_year_id),
        constraint_configuration=feasibility_constraint_configuration(),
    )


def latest_feasibility_payload(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int) -> dict:
    current = current_feasibility_input(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    row = db.query(models.TimetableFeasibilityVerification).filter(
        models.TimetableFeasibilityVerification.school_group_id == school_group_id,
        models.TimetableFeasibilityVerification.branch_id == branch_id,
        models.TimetableFeasibilityVerification.academic_year_id == academic_year_id,
        models.TimetableFeasibilityVerification.authority_fingerprint == current.full_input_fingerprint,
    ).first()
    return {
        "status": row.status if row else "not_checked",
        "verified": bool(row and row.status == "verified"),
        "public_id": row.public_id if row else None,
        "authority_fingerprint": current.full_input_fingerprint,
        "diagnostics": json.loads(row.diagnostics_json or "[]") if row else [],
        "reusable": bool(row and row.status == "verified"),
    }


def enqueue_feasibility_verification(db: Session, *, school_group_id: int, branch_id: int,
                       academic_year_id: int, requested_by_user_id: str | None) -> tuple[models.TimetableFeasibilityVerification, models.TimetableGenerationRun | None]:
    if int(resolve_scope_school_group_id(db, branch_id=branch_id, academic_year_id=academic_year_id)) != int(school_group_id):
        raise ValueError("The selected timetable scope is invalid.")
    current = current_feasibility_input(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    existing = db.query(models.TimetableFeasibilityVerification).filter(
        models.TimetableFeasibilityVerification.school_group_id == school_group_id,
        models.TimetableFeasibilityVerification.branch_id == branch_id,
        models.TimetableFeasibilityVerification.academic_year_id == academic_year_id,
        models.TimetableFeasibilityVerification.authority_fingerprint == current.full_input_fingerprint,
    ).first()
    if existing and existing.status in {"verified", "conflict"}:
        return existing, None
    active = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.school_group_id == school_group_id,
        models.TimetableGenerationRun.branch_id == branch_id,
        models.TimetableGenerationRun.academic_year_id == academic_year_id,
        models.TimetableGenerationRun.status.in_(("queued", "running", "validating", "cancel_requested")),
    ).first()
    if active:
        if existing and json.loads(active.diversity_configuration_json or "{}").get("feasibility_verification_id") == existing.id:
            return existing, active
        raise ValueError("A timetable generation or feasibility check is already running for this scope.")
    snapshot = create_current_input_snapshot(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id, created_by_user_id=requested_by_user_id,
        provenance="feasibility", locks=_locks(db, school_group_id, branch_id, academic_year_id),
        constraint_configuration=feasibility_constraint_configuration(),
    )
    row = existing or models.TimetableFeasibilityVerification(
        school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id, input_snapshot_id=snapshot.id,
        authority_fingerprint=current.full_input_fingerprint, status="checking",
        requested_by_user_id=requested_by_user_id,
    )
    if not existing:
        db.add(row)
    else:
        row.input_snapshot_id = snapshot.id
        row.status = "checking"
    db.flush()
    run = models.TimetableGenerationRun(
        school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id, requested_by_user_id=requested_by_user_id,
        request_mode="generate", input_snapshot_id=snapshot.id, status="queued",
        progress_phase="queued", solver_name="OR-Tools CP-SAT", solver_version="9.15.6755",
        solver_configuration_json=json.dumps({"constraint_contract": "hard-only-feasibility"}, separators=(",", ":")),
        generation_seed=secrets.randbelow(2_147_483_647),
        diversity_configuration_json=json.dumps({
            "feasibility_verification_id": row.id, "verification_run": True,
        }, separators=(",", ":")),
        # Retry attempts after an inconclusive timeout need a new durable run;
        # the verification row + active-run guard prevent duplicate work.
        idempotency_key=(
            f"feasibility:{current.full_input_fingerprint[:48]}:{secrets.token_hex(8)}"
        ),
    )
    db.add(run)
    db.flush()
    return row, run
