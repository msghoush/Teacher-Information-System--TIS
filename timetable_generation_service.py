from __future__ import annotations

import copy
import json
import logging
import math
import os
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from timetable_problem_builder import TimetableProblemBuilder, TimetableProblemError
from timetable_readiness_service import TimetableReadinessService
from timetable_snapshot_service import (
    build_current_snapshot_data,
    create_current_input_snapshot,
)
from timetable_solution_validator import TimetableSolutionValidator
from timetable_version_service import (
    TimetableVersionError,
    _allocate_next_version_number,
    resolve_scope_school_group_id,
    resolve_operational_version,
    resolve_version,
)


ACTIVE_STATUSES = ("queued", "running", "validating", "cancel_requested")
TERMINAL_STATUSES = (
    "succeeded", "infeasible", "timed_out", "stale_input", "cancelled",
    "internal_error", "concurrent_run_rejected",
)
PHASE_LABELS = {
    "queued": "Queued",
    "building": "Building Timetable",
    "solving": "Solving",
    "checking": "Checking Result",
    "saving": "Saving",
    "complete": "Complete",
    "failed": "Generation Failed",
    "cancelled": "Generation Cancelled",
}
FAILURE_LABELS = {
    "infeasible": "No Valid Timetable Found",
    "timed_out": "Generation Timed Out",
    "stale_input": "Inputs Changed — Generate Again",
    "cancelled": "Generation Cancelled",
    "internal_error": "Generation Failed",
    "concurrent_run_rejected": "Generation Already Running",
}
logger = logging.getLogger("tis.timetable_generation_service")


def _fingerprint_differences(expected, current) -> dict[str, dict[str, str]]:
    fields = (
        ("planning", "planning_fingerprint"),
        ("period_configuration", "period_configuration_fingerprint"),
        ("constraints", "constraint_fingerprint"),
        ("locks", "lock_fingerprint"),
        ("full_input", "full_input_fingerprint"),
    )
    return {
        name: {"expected": str(getattr(expected, field, "") or ""), "current": str(getattr(current, field, "") or "")}
        for name, field in fields
        if str(getattr(expected, field, "") or "") != str(getattr(current, field, "") or "")
    }


class TimetableGenerationError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _serialize_entries(entries) -> list[dict]:
    return [
        {
            "section_id": int(row.planning_section_id),
            "subject_code": str(row.subject_code or "").strip().upper(),
            "teacher_id": int(row.teacher_id),
            "day_key": str(row.day_key or "").strip().lower(),
            "period_index": int(row.period_index),
            "is_locked": bool(row.is_locked),
        }
        for row in sorted(entries, key=lambda row: (
            str(row.day_key or ""), int(row.period_index or 0),
            int(row.planning_section_id or 0), str(row.subject_code or ""),
            int(row.teacher_id or 0),
        ))
    ]


def _minimum_difference(unlocked_count: int, percent: int = 25) -> int:
    if unlocked_count <= 0:
        return 0
    return math.ceil((min(max(int(percent or 25), 1), 100) / 100) * unlocked_count)


def resolve_generated_working_candidate(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> models.TimetableVersion | None:
    pointer = db.query(models.TimetableActiveVersion).filter(
        models.TimetableActiveVersion.school_group_id == school_group_id,
        models.TimetableActiveVersion.branch_id == branch_id,
        models.TimetableActiveVersion.academic_year_id == academic_year_id,
    ).first()
    active_id = int(pointer.timetable_version_id) if pointer else 0
    return db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
        models.TimetableVersion.origin.in_(("generated", "regenerated")),
        models.TimetableVersion.lifecycle_status.in_(("draft", "publication_ready")),
        models.TimetableVersion.id != active_id,
    ).order_by(
        models.TimetableVersion.version_number.desc(),
        models.TimetableVersion.id.desc(),
    ).first()


def _active_run_query(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int):
    return db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.school_group_id == school_group_id,
        models.TimetableGenerationRun.branch_id == branch_id,
        models.TimetableGenerationRun.academic_year_id == academic_year_id,
        models.TimetableGenerationRun.status.in_(ACTIVE_STATUSES),
    )


def build_generation_state(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    draft_version_id: int | None = None,
) -> dict:
    active = _active_run_query(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    ).order_by(models.TimetableGenerationRun.queued_at.desc()).first()
    latest = active or db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.school_group_id == school_group_id,
        models.TimetableGenerationRun.branch_id == branch_id,
        models.TimetableGenerationRun.academic_year_id == academic_year_id,
    ).order_by(models.TimetableGenerationRun.created_at.desc()).first()
    current_draft = None
    if draft_version_id is not None:
        current_draft = resolve_version(
            db,
            version_id=int(draft_version_id),
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        if current_draft is not None and (
            current_draft.lifecycle_status not in {"draft", "publication_ready"}
            or db.query(models.TimetableActiveVersion.id).filter(
                models.TimetableActiveVersion.timetable_version_id == current_draft.id
            ).first()
        ):
            current_draft = None
    current_draft = current_draft or resolve_operational_version(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    candidate = (
        current_draft
        if current_draft is not None
        and current_draft.origin in {"generated", "regenerated"}
        else None
    )
    return {
        "active_run": generation_run_payload(active) if active else None,
        "latest_run": generation_run_payload(latest) if latest else None,
        "working_candidate": ({
            "public_id": candidate.public_id,
            "version_number": int(candidate.version_number),
            "origin": candidate.origin,
            "edit_revision": int(candidate.edit_revision or 0),
        } if candidate else None),
        "primary_action": "regenerate" if candidate else "generate",
        "draft_version_public_id": current_draft.public_id if current_draft else None,
    }


def generation_run_payload(run: models.TimetableGenerationRun | None) -> dict | None:
    if run is None:
        return None
    phase_label = FAILURE_LABELS.get(run.status) or PHASE_LABELS.get(
        run.progress_phase, "Generation"
    )
    message = run.safe_failure_details or ""
    if run.status == "queued" and run.queued_at:
        try:
            warning_seconds = max(
                int(os.getenv("TIS_TIMETABLE_WORKFLOW_START_WARNING_SECONDS", "60")), 10
            )
        except (TypeError, ValueError):
            warning_seconds = 60
        if datetime.utcnow() - run.queued_at >= timedelta(seconds=warning_seconds):
            phase_label = "Waiting for Generation Service"
            message = (
                "Generation is queued and waiting for compute to start. "
                "You can leave this page and return later."
            )
    return {
        "public_id": run.public_id,
        "request_mode": run.request_mode,
        "status": run.status,
        "progress_phase": run.progress_phase,
        "phase_label": phase_label,
        "active": run.status in ACTIVE_STATUSES,
        "attempt_count": int(run.attempt_count or 0),
        "failure_category": run.failure_category or "",
        "message": message,
        "result_version_id": run.result_version_id,
        "queued_at": run.queued_at.isoformat() if run.queued_at else "",
        "started_at": run.started_at.isoformat() if run.started_at else "",
        "finished_at": run.finished_at.isoformat() if run.finished_at else "",
    }


def _load_source_entries(db: Session, source: models.TimetableVersion | None):
    if source is None:
        return []
    return db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == source.id,
    ).order_by(models.TimetableEntry.id.asc()).all()


def enqueue_generation(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    requested_by_user_id: str | None,
    request_mode: str,
    idempotency_key: str,
    source_public_id: str | None = None,
    draft_public_id: str | None = None,
) -> models.TimetableGenerationRun:
    if request_mode not in {"generate", "regenerate"}:
        raise TimetableGenerationError("request_mode_invalid", "Generation mode is invalid.")
    if not idempotency_key or len(idempotency_key) > 120:
        raise TimetableGenerationError(
            "idempotency_key_invalid", "A valid generation request key is required."
        )
    resolved_group = resolve_scope_school_group_id(
        db, branch_id=branch_id, academic_year_id=academic_year_id
    )
    if int(resolved_group) != int(school_group_id):
        raise TimetableGenerationError("scope_mismatch", "The selected timetable scope is invalid.")

    db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == school_group_id
    ).with_for_update().one()
    existing = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.school_group_id == school_group_id,
        models.TimetableGenerationRun.branch_id == branch_id,
        models.TimetableGenerationRun.academic_year_id == academic_year_id,
        models.TimetableGenerationRun.idempotency_key == idempotency_key,
    ).first()
    if existing:
        return existing
    active = _active_run_query(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    ).first()
    if active:
        raise TimetableGenerationError(
            "active_generation_exists",
            "A timetable generation is already running for this branch and academic year.",
            409,
        )

    selected_draft = None
    if draft_public_id:
        selected_draft = db.query(models.TimetableVersion).filter(
            models.TimetableVersion.public_id == draft_public_id,
            models.TimetableVersion.school_group_id == school_group_id,
            models.TimetableVersion.branch_id == branch_id,
            models.TimetableVersion.academic_year_id == academic_year_id,
        ).first()
        if selected_draft is None or selected_draft.lifecycle_status not in {"draft", "publication_ready"}:
            raise TimetableGenerationError(
                "generation_draft_invalid", "The selected Draft Timetable is no longer available.", 409
            )
        if db.query(models.TimetableActiveVersion.id).filter(
            models.TimetableActiveVersion.timetable_version_id == selected_draft.id
        ).first():
            raise TimetableGenerationError(
                "generation_draft_invalid", "The Published Timetable cannot be used as a draft.", 409
            )
    current_draft = selected_draft or resolve_operational_version(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    candidate = (
        current_draft
        if current_draft is not None
        and current_draft.origin in {"generated", "regenerated"}
        and current_draft.lifecycle_status in {"draft", "publication_ready"}
        else None
    )
    source = None
    if request_mode == "generate" and source_public_id:
        raise TimetableGenerationError(
            "generation_source_invalid",
            "Generate does not accept a regeneration source.",
        )
    if request_mode == "generate" and candidate is not None:
        raise TimetableGenerationError(
            "regeneration_required", "Regenerate the existing working timetable instead.", 409
        )
    if request_mode == "regenerate":
        source = candidate
        if source is None or source.origin not in {"generated", "regenerated"}:
            raise TimetableGenerationError(
                "regeneration_source_missing", "No generated working timetable is available.", 409
            )
        if source_public_id and source.public_id != source_public_id:
            raise TimetableGenerationError(
                "regeneration_source_changed",
                "The generated working timetable changed; reload before regenerating.",
                409,
            )
    if request_mode == "generate" and source is None:
        source = current_draft

    readiness = TimetableReadinessService(db).evaluate(
        school_group_id, branch_id, academic_year_id
    )
    if readiness["status"] != "generation_ready":
        message = (
            readiness["blockers"][0]["message"]
            if readiness.get("blockers") else "Timetable inputs are not ready to generate."
        )
        raise TimetableGenerationError("not_generation_ready", message, 409)

    source_entries = _load_source_entries(db, source)
    locks = [item for item in _serialize_entries(source_entries) if item["is_locked"]]
    source_arrangement = _serialize_entries(source_entries) if request_mode == "regenerate" else []
    unlocked = sum(1 for item in source_arrangement if not item["is_locked"])
    from timetable_logic import get_timetable_settings_payload
    quality_rules = get_timetable_settings_payload(db, branch_id, academic_year_id).get("quality_rules") or {}
    diversity_percent = int(quality_rules.get("regeneration_diversity_percent") or 25)
    minimum_difference = _minimum_difference(unlocked, diversity_percent) if request_mode == "regenerate" else 0
    if request_mode == "regenerate" and unlocked == 0:
        raise TimetableGenerationError(
            "regeneration_fully_locked",
            "Regeneration is unavailable because every lesson is locked.",
            409,
        )

    constraint_configuration = {
        "stage": "5.1",
        "rules": [
            "exact_demand", "section_slot_exclusivity", "teacher_slot_exclusivity",
            "canonical_slots", "planning_teacher_authority", "preserve_locks",
        ],
        "generation": {
            "request_mode": request_mode,
            "source_version_id": int(source.id) if source else None,
            "source_edit_revision": int(source.edit_revision or 0) if source else None,
            "source_lifecycle_status": str(source.lifecycle_status) if source else None,
            "source_arrangement": source_arrangement,
            "minimum_difference": minimum_difference,
            "diversity_percent": diversity_percent,
        },
    }
    snapshot = create_current_input_snapshot(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        created_by_user_id=requested_by_user_id,
        provenance=request_mode,
        locks=locks,
        constraint_configuration=constraint_configuration,
    )
    run = models.TimetableGenerationRun(
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        requested_by_user_id=requested_by_user_id,
        request_mode=request_mode,
        source_version_id=int(source.id) if source else None,
        source_edit_revision=int(source.edit_revision or 0) if source else None,
        input_snapshot_id=snapshot.id,
        status="queued",
        progress_phase="queued",
        attempt_count=0,
        solver_name="OR-Tools CP-SAT",
        solver_version="9.15.6755",
        solver_configuration_json=json.dumps({"constraint_contract": "5.1"}, separators=(",", ":")),
        generation_seed=secrets.randbelow(2_147_483_647),
        diversity_configuration_json=json.dumps({
            "unlocked_lessons": unlocked,
            "minimum_difference": minimum_difference,
            "diversity_percent": diversity_percent,
        }, separators=(",", ":")),
        idempotency_key=idempotency_key,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        raise TimetableGenerationError(
            "active_generation_exists",
            "A timetable generation is already running for this branch and academic year.",
            409,
        ) from exc
    return run


def recover_expired_runs(db: Session, *, max_attempts: int, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    rows = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.status.in_(("running", "validating", "cancel_requested")),
        models.TimetableGenerationRun.lease_expires_at.is_not(None),
        models.TimetableGenerationRun.lease_expires_at < now,
    ).with_for_update(skip_locked=True).all()
    recovered = 0
    for run in rows:
        if run.status == "cancel_requested":
            run.status = "cancelled"
            run.progress_phase = "cancelled"
            run.finished_at = now
            run.safe_failure_details = "Generation was cancelled."
        elif int(run.attempt_count or 0) >= int(max_attempts):
            run.status = "internal_error"
            run.progress_phase = "failed"
            run.finished_at = now
            run.failure_category = "worker_recovery_exhausted"
            run.safe_failure_details = "Generation could not recover after a worker restart."
        else:
            run.status = "queued"
            run.progress_phase = "queued"
            recovered += 1
        run.lease_owner = None
        run.lease_expires_at = None
        run.heartbeat_at = None
        run.updated_at = now
    db.flush()
    return recovered


def claim_next_run(
    db: Session,
    *,
    lease_seconds: int,
    max_attempts: int,
    lease_owner: str | None = None,
) -> models.TimetableGenerationRun | None:
    recover_expired_runs(db, max_attempts=max_attempts)
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.status == "queued",
    ).order_by(
        models.TimetableGenerationRun.queued_at.asc(),
        models.TimetableGenerationRun.id.asc(),
    ).with_for_update(skip_locked=True).first()
    if run is None:
        return None
    now = datetime.utcnow()
    run.status = "running"
    run.progress_phase = "building"
    run.attempt_count = int(run.attempt_count or 0) + 1
    run.started_at = run.started_at or now
    run.lease_owner = lease_owner or str(uuid.uuid4())
    run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=max(int(lease_seconds), 10))
    run.updated_at = now
    db.flush()
    return run


def claim_run_by_public_id(
    db: Session,
    *,
    public_id: str,
    lease_seconds: int,
    lease_owner: str | None = None,
    expected_school_group_id: int | None = None,
    expected_branch_id: int | None = None,
    expected_academic_year_id: int | None = None,
) -> models.TimetableGenerationRun | None:
    """Claim exactly one queued durable run for an on-demand task.

    Terminal, already-active, and already-completed runs are deliberate no-ops.
    Optional scope assertions support internal callers and isolation tests without
    placing tenant data in the Render task input.
    """
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.public_id == public_id,
    ).with_for_update().first()
    if run is None:
        raise TimetableGenerationError("generation_run_not_found", "Generation run not found.", 404)
    expected = (
        expected_school_group_id,
        expected_branch_id,
        expected_academic_year_id,
    )
    actual = (run.school_group_id, run.branch_id, run.academic_year_id)
    if any(value is not None for value in expected) and any(
        value is not None and int(value) != int(actual[index])
        for index, value in enumerate(expected)
    ):
        raise TimetableGenerationError(
            "scope_mismatch", "Generation run not found in the selected scope.", 404
        )
    if run.status != "queued":
        return None
    now = datetime.utcnow()
    run.status = "running"
    run.progress_phase = "building"
    run.attempt_count = int(run.attempt_count or 0) + 1
    run.started_at = run.started_at or now
    run.lease_owner = lease_owner or str(uuid.uuid4())
    run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=max(int(lease_seconds), 10))
    run.updated_at = now
    db.flush()
    return run


def mark_workflow_dispatch_failed(
    db: Session,
    *,
    run_id: int,
) -> bool:
    """Fail a run only while it is still unclaimed after dispatch failure."""
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run_id,
    ).with_for_update().one()
    if run.status != "queued":
        return False
    mark_run_terminal(
        db,
        run_id=run.id,
        lease_owner=None,
        status="internal_error",
        failure_category="workflow_dispatch_failed",
        safe_message="Generation could not start. Please try Generate Again.",
    )
    return True


def heartbeat_run(
    db: Session,
    *,
    run_id: int,
    lease_owner: str,
    lease_seconds: int,
) -> str:
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run_id,
    ).with_for_update().first()
    if run is None or run.lease_owner != lease_owner or run.status not in ACTIVE_STATUSES:
        return "lost"
    if run.status == "cancel_requested":
        return "cancel_requested"
    now = datetime.utcnow()
    run.heartbeat_at = now
    run.lease_expires_at = now + timedelta(seconds=max(int(lease_seconds), 10))
    run.updated_at = now
    db.flush()
    return "active"


def set_run_progress(
    db: Session,
    *,
    run_id: int,
    lease_owner: str,
    phase: str,
) -> models.TimetableGenerationRun:
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run_id,
    ).with_for_update().one()
    if run.lease_owner != lease_owner or run.status not in ACTIVE_STATUSES:
        raise TimetableGenerationError("lease_lost", "The generation worker lost its lease.", 409)
    if run.status == "cancel_requested":
        raise TimetableGenerationError(
            "cancel_requested", "Generation was cancelled.", 409
        )
    run.progress_phase = phase
    if phase in {"checking", "saving"}:
        run.status = "validating"
        run.validating_at = run.validating_at or datetime.utcnow()
    else:
        run.status = "running"
    run.updated_at = datetime.utcnow()
    db.flush()
    return run


def mark_run_terminal(
    db: Session,
    *,
    run_id: int,
    lease_owner: str | None,
    status: str,
    failure_category: str | None = None,
    safe_message: str | None = None,
) -> models.TimetableGenerationRun:
    if status not in TERMINAL_STATUSES:
        raise ValueError("Terminal generation status is invalid.")
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run_id,
    ).with_for_update().one()
    if lease_owner is not None and run.lease_owner != lease_owner:
        raise TimetableGenerationError("lease_lost", "The generation worker lost its lease.", 409)
    run.status = status
    run.progress_phase = "cancelled" if status == "cancelled" else "failed"
    run.failure_category = failure_category
    run.safe_failure_details = safe_message
    run.finished_at = datetime.utcnow()
    run.lease_owner = None
    run.lease_expires_at = None
    run.heartbeat_at = None
    run.updated_at = datetime.utcnow()
    db.flush()
    return run


def request_cancellation(
    db: Session,
    *,
    run: models.TimetableGenerationRun,
    actor_user_id: str | None,
) -> models.TimetableGenerationRun:
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run.id,
    ).with_for_update().one()
    now = datetime.utcnow()
    if run.status == "queued":
        run.status = "cancelled"
        run.progress_phase = "cancelled"
        run.finished_at = now
        run.safe_failure_details = "Generation was cancelled."
    elif run.status in {"running", "validating"}:
        run.status = "cancel_requested"
        run.safe_failure_details = "Cancellation requested."
    run.cancel_requested_at = run.cancel_requested_at or now
    run.cancel_requested_by_user_id = actor_user_id
    run.updated_at = now
    db.flush()
    return run


def _current_input_for_run(db: Session, run: models.TimetableGenerationRun) -> tuple[object, int | None, list]:
    snapshot = db.query(models.TimetableInputSnapshot).filter(
        models.TimetableInputSnapshot.id == run.input_snapshot_id,
        models.TimetableInputSnapshot.school_group_id == run.school_group_id,
        models.TimetableInputSnapshot.branch_id == run.branch_id,
        models.TimetableInputSnapshot.academic_year_id == run.academic_year_id,
    ).one()
    captured = json.loads(snapshot.canonical_snapshot_json)
    constraints = copy.deepcopy(captured.get("constraints") or {})
    generation = constraints.setdefault("generation", {})
    source = None
    source_entries = []
    current_revision = None
    if run.source_version_id is not None:
        source = resolve_version(
            db,
            version_id=int(run.source_version_id),
            school_group_id=int(run.school_group_id),
            branch_id=int(run.branch_id),
            academic_year_id=int(run.academic_year_id),
        )
        if source is None:
            raise TimetableGenerationError("stale_source", "The generation source is no longer available.")
        current_revision = int(source.edit_revision or 0)
        source_entries = _load_source_entries(db, source)
    current_locks = [item for item in _serialize_entries(source_entries) if item["is_locked"]]
    generation["source_edit_revision"] = current_revision
    generation["source_lifecycle_status"] = (
        str(source.lifecycle_status) if source is not None else None
    )
    if run.request_mode == "regenerate":
        generation["source_arrangement"] = _serialize_entries(source_entries)
    current = build_current_snapshot_data(
        db,
        school_group_id=int(run.school_group_id),
        branch_id=int(run.branch_id),
        academic_year_id=int(run.academic_year_id),
        locks=current_locks,
        constraint_configuration=constraints,
    )
    return current, current_revision, source_entries


def persist_generated_result(
    db: Session,
    *,
    run_id: int,
    lease_owner: str,
    problem: dict,
    placements: list[dict],
    solver_result: dict,
) -> models.TimetableVersion:
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run_id,
    ).with_for_update().one()
    now = datetime.utcnow()
    if run.lease_owner != lease_owner:
        raise TimetableGenerationError("lease_lost", "The generation worker lost its lease.", 409)
    if run.status == "cancel_requested":
        mark_run_terminal(
            db,
            run_id=run.id,
            lease_owner=lease_owner,
            status="cancelled",
            failure_category="cancelled",
            safe_message="Generation was cancelled.",
        )
        raise TimetableGenerationError("cancel_requested", "Generation was cancelled.", 409)
    if run.status != "validating":
        raise TimetableGenerationError("lease_lost", "The generation worker lost its lease.", 409)
    if run.lease_expires_at is None or run.lease_expires_at < now:
        raise TimetableGenerationError("lease_expired", "The generation worker lease expired.", 409)
    snapshot = db.query(models.TimetableInputSnapshot).filter(
        models.TimetableInputSnapshot.id == run.input_snapshot_id,
    ).one()
    current, current_revision, source_entries = _current_input_for_run(db, run)
    validation = TimetableSolutionValidator().validate(
        problem=problem,
        placements=placements,
        expected_fingerprint=str(snapshot.full_input_fingerprint),
        current_fingerprint=current.full_input_fingerprint,
        expected_source_revision=run.source_edit_revision,
        current_source_revision=current_revision,
        expected_scope={
            "school_group_id": run.school_group_id,
            "branch_id": run.branch_id,
            "academic_year_id": run.academic_year_id,
        },
        current_scope={
            "school_group_id": run.school_group_id,
            "branch_id": run.branch_id,
            "academic_year_id": run.academic_year_id,
        },
    )
    if not validation["valid"]:
        first = validation["errors"][0]
        if first["code"] in {"stale_input", "stale_source"}:
            differences = _fingerprint_differences(snapshot, current)
            logger.warning(
                "Timetable generation run %s freshness mismatch components=%s source_revision_expected=%s source_revision_current=%s",
                run.id,
                sorted(differences),
                run.source_edit_revision,
                current_revision,
            )
            mark_run_terminal(
                db, run_id=run.id, lease_owner=lease_owner, status="stale_input",
                failure_category=first["code"], safe_message="Inputs changed — generate again.",
            )
            raise TimetableGenerationError("stale_input", first["message"], 409)
        mark_run_terminal(
            db, run_id=run.id, lease_owner=lease_owner, status="internal_error",
            failure_category="validator_rejected", safe_message="Generated result failed validation.",
        )
        raise TimetableGenerationError("validator_rejected", first["message"], 500)

    expected_required_periods = sum(
        int(item.get("required_weekly_periods") or 0)
        for item in problem.get("demands") or []
    )
    solver_placements = len(solver_result.get("placements") or [])
    validated_placements = int((validation.get("counts") or {}).get("placements") or 0)
    if not (
        expected_required_periods
        == solver_placements
        == validated_placements
        == len(placements)
    ):
        logger.error(
            "Generation run %s count invariant failed before persistence: expected=%s solver=%s validated=%s candidate=%s",
            run.id,
            expected_required_periods,
            solver_placements,
            validated_placements,
            len(placements),
        )
        mark_run_terminal(
            db, run_id=run.id, lease_owner=lease_owner, status="internal_error",
            failure_category="placement_count_mismatch",
            safe_message="Generated result failed completeness verification.",
        )
        raise TimetableGenerationError(
            "placement_count_mismatch",
            "Generated placement counts do not match required demand.",
            500,
        )

    base_authority = current
    version = models.TimetableVersion(
        school_group_id=run.school_group_id,
        branch_id=run.branch_id,
        academic_year_id=run.academic_year_id,
        version_number=_allocate_next_version_number(
            db,
            school_group_id=int(run.school_group_id),
            branch_id=int(run.branch_id),
            academic_year_id=int(run.academic_year_id),
        ),
        lifecycle_status="publication_ready",
        origin="regenerated" if run.request_mode == "regenerate" else "generated",
        source_version_id=run.source_version_id,
        input_snapshot_id=run.input_snapshot_id,
        generation_run_id=run.id,
        created_by_user_id=run.requested_by_user_id,
        generated_at=now,
        quality_score=None,
        quality_summary_json=None,
        generation_seed=run.generation_seed,
        solver_name=run.solver_name,
        solver_version=run.solver_version,
        solver_configuration_json=run.solver_configuration_json,
        authority_fingerprint=base_authority.authority_fingerprint,
        is_stale=False,
        stale_reason_json="[]",
    )
    db.add(version)
    db.flush()
    source_lock_metadata = {
        (
            int(row.planning_section_id), str(row.subject_code or "").strip().upper(),
            int(row.teacher_id), str(row.day_key or "").strip().lower(), int(row.period_index),
        ): row
        for row in source_entries if row.is_locked
    }
    for item in placements:
        key = (
            int(item["section_id"]), str(item["subject_code"]).upper(), int(item["teacher_id"]),
            str(item["day_key"]).lower(), int(item["period_index"]),
        )
        source_lock = source_lock_metadata.get(key)
        db.add(models.TimetableEntry(
            timetable_version_id=version.id,
            branch_id=run.branch_id,
            academic_year_id=run.academic_year_id,
            planning_section_id=item["section_id"],
            subject_code=item["subject_code"],
            teacher_id=item["teacher_id"],
            day_key=item["day_key"],
            period_index=item["period_index"],
            is_locked=source_lock is not None,
            locked_at=source_lock.locked_at if source_lock else None,
            locked_by_user_id=source_lock.locked_by_user_id if source_lock else None,
        ))
    db.flush()
    persisted_placements = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == version.id,
    ).count()
    db.expire_all()
    reloaded_placements = len(db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == version.id,
    ).all())
    if not (
        expected_required_periods
        == solver_placements
        == validated_placements
        == persisted_placements
        == reloaded_placements
    ):
        logger.error(
            "Generation run %s count invariant failed after persistence: expected=%s solver=%s validated=%s persisted=%s reloaded=%s",
            run.id,
            expected_required_periods,
            solver_placements,
            validated_placements,
            persisted_placements,
            reloaded_placements,
        )
        db.query(models.TimetableEntry).filter(
            models.TimetableEntry.timetable_version_id == version.id,
        ).delete(synchronize_session=False)
        db.delete(version)
        db.flush()
        mark_run_terminal(
            db, run_id=run.id, lease_owner=lease_owner, status="internal_error",
            failure_category="placement_count_mismatch",
            safe_message="Generated result failed completeness verification.",
        )
        raise TimetableGenerationError(
            "placement_count_mismatch",
            "Persisted placement counts do not match required demand.",
            500,
        )
    run.result_version_id = version.id
    run.status = "succeeded"
    run.progress_phase = "complete"
    run.finished_at = now
    run.failure_category = None
    run.safe_failure_details = "Timetable generated successfully."
    run.lease_owner = None
    run.lease_expires_at = None
    run.heartbeat_at = None
    run.updated_at = now
    db.flush()
    return version


def load_problem_for_run(db: Session, run_id: int) -> tuple[models.TimetableGenerationRun, dict]:
    run = db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.id == run_id,
    ).one()
    snapshot = db.query(models.TimetableInputSnapshot).filter(
        models.TimetableInputSnapshot.id == run.input_snapshot_id,
    ).one()
    return run, TimetableProblemBuilder().build(snapshot.canonical_snapshot_json)
