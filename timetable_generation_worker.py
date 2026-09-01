from __future__ import annotations

import logging
import json
import os
import threading
from dataclasses import dataclass

import models
from database import SessionLocal
from timetable_generation_service import (
    TimetableGenerationError,
    claim_next_run,
    claim_run_by_public_id,
    heartbeat_run,
    load_problem_for_run,
    mark_run_terminal,
    persist_generated_result,
    set_run_progress,
)
from timetable_problem_builder import TimetableProblemError
from timetable_solution_validator import TimetableSolutionValidator
from timetable_solver import DEFAULT_TIMETABLE_SOLVER, TimetableSolver


logger = logging.getLogger("tis.timetable_generation_worker")


def _problem_error_status(code: str) -> str:
    if code.startswith("teacher_rule") or code.startswith("distribution_rule"):
        return "infeasible"
    if code in {
        "insufficient_teaching_slots", "lock_conflict", "locked_count_exceeds_demand",
        "lock_slot_invalid", "lock_authority_invalid",
    }:
        return "infeasible"
    return "internal_error"


def _positive_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class WorkerSettings:
    poll_seconds: int = 2
    lease_seconds: int = 90
    heartbeat_seconds: int = 15
    max_attempts: int = 2
    solver_timeout_seconds: int = 60
    feasibility_timeout_seconds: int = 60
    diagnostic_timeout_seconds: int = 60
    cp_sat_workers: int = 1

    @classmethod
    def from_environment(cls) -> "WorkerSettings":
        return cls(
            poll_seconds=_positive_int("TIS_TIMETABLE_POLL_SECONDS", 2),
            lease_seconds=_positive_int("TIS_TIMETABLE_LEASE_SECONDS", 90, 10),
            heartbeat_seconds=_positive_int("TIS_TIMETABLE_HEARTBEAT_SECONDS", 15),
            max_attempts=_positive_int("TIS_TIMETABLE_MAX_ATTEMPTS", 2),
            solver_timeout_seconds=_positive_int("TIS_TIMETABLE_SOLVER_TIMEOUT_SECONDS", 60),
            feasibility_timeout_seconds=_positive_int("TIS_TIMETABLE_FEASIBILITY_TIMEOUT_SECONDS", 60),
            diagnostic_timeout_seconds=_positive_int(
                "TIS_TIMETABLE_DIAGNOSTIC_TIMEOUT_SECONDS", 60
            ),
            cp_sat_workers=_positive_int("TIS_TIMETABLE_CP_SAT_WORKERS", 1),
        )


def _terminal(run_id: int, owner: str, status: str, category: str, message: str) -> None:
    session = SessionLocal()
    try:
        mark_run_terminal(
            session,
            run_id=run_id,
            lease_owner=owner,
            status=status,
            failure_category=category,
            safe_message=message,
        )
        session.commit()
    except TimetableGenerationError:
        session.rollback()
        logger.info("Run %s terminal update skipped after lease loss.", run_id)
    finally:
        session.close()


def _mark_infeasible(
    run_id: int, owner: str, problem: dict, settings: WorkerSettings | None = None,
    solver: TimetableSolver = DEFAULT_TIMETABLE_SOLVER,
) -> None:
    if problem.get("request_mode") == "regenerate":
        _terminal(
            run_id, owner, "infeasible", "regeneration_diversity_unavailable",
            "No sufficiently different valid timetable could be generated while preserving all current requirements and locks.",
        )
        return
    settings = settings or WorkerSettings()
    diagnostic = solver.diagnose_infeasible(
        problem,
        timeout_seconds=settings.diagnostic_timeout_seconds,
        seed=13,
        search_workers=settings.cp_sat_workers,
    )
    category = diagnostic["category"]
    lock_source = (
        "the selected Draft source"
        if diagnostic.get("has_source_version") else "no Draft source"
    )
    message = (
        f"{diagnostic['message']} "
        f"{diagnostic.get('details_summary', '')} "
        f"This {diagnostic.get('request_mode', 'generate')} run used "
        f"{diagnostic['lock_count']} intentional lesson lock(s) from {lock_source} and "
        f"{diagnostic['grouped_activity_count']} grouped activity configuration(s)."
    )
    _terminal(
        run_id, owner, "infeasible", f"solver_infeasible_{category}", message,
    )


def process_run(
    run_id: int,
    owner: str,
    settings: WorkerSettings,
    solver: TimetableSolver = DEFAULT_TIMETABLE_SOLVER,
) -> None:
    cancel_event = threading.Event()
    stop_heartbeat = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_heartbeat.wait(settings.heartbeat_seconds):
            session = SessionLocal()
            try:
                state = heartbeat_run(
                    session,
                    run_id=run_id,
                    lease_owner=owner,
                    lease_seconds=settings.lease_seconds,
                )
                session.commit()
                if state in {"cancel_requested", "lost"}:
                    cancel_event.set()
                    if state == "lost":
                        return
            except Exception:
                session.rollback()
                logger.exception("Run %s heartbeat failed.", run_id)
            finally:
                session.close()

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    try:
        session = SessionLocal()
        try:
            run, problem = load_problem_for_run(session, run_id)
            snapshot = session.get(models.TimetableInputSnapshot, run.input_snapshot_id)
            expected_fingerprint = str(snapshot.full_input_fingerprint)
            seed = int(run.generation_seed or 0)
            run_metadata = json.loads(run.diversity_configuration_json or "{}")
            feasibility_verification_id = (
                run_metadata.get("feasibility_verification_id")
                if run_metadata.get("verification_run") else None
            )
        finally:
            session.close()

        session = SessionLocal()
        try:
            set_run_progress(session, run_id=run_id, lease_owner=owner, phase="solving")
            session.commit()
        finally:
            session.close()

        result = solver.solve(
            problem,
            timeout_seconds=(
                settings.feasibility_timeout_seconds
                if feasibility_verification_id else settings.solver_timeout_seconds
            ),
            seed=seed,
            search_workers=settings.cp_sat_workers,
            cancel_event=cancel_event,
            solution_hint=problem.get("verified_feasible_placements") or None,
            optimize_soft_constraints=not bool(feasibility_verification_id),
        )
        if feasibility_verification_id:
            diagnostics = []
            status = "internal_error"
            if result["outcome"] == "feasible":
                validation = TimetableSolutionValidator().validate(
                    problem=problem, placements=result["placements"],
                    expected_fingerprint=expected_fingerprint,
                    current_fingerprint=expected_fingerprint,
                    expected_scope=problem.get("scope"), current_scope=problem.get("scope"),
                )
                if validation["valid"]:
                    status = "verified"
                else:
                    diagnostics = validation["errors"]
            elif result["outcome"] == "infeasible":
                status = "conflict"
                diagnostic = solver.diagnose_infeasible(
                    problem, timeout_seconds=settings.diagnostic_timeout_seconds,
                    seed=13, search_workers=settings.cp_sat_workers,
                )
                diagnostics = [{
                    "code": diagnostic["category"], "message": diagnostic["message"],
                    "details": diagnostic.get("details_summary", ""),
                }]
            elif result["outcome"] == "timed_out":
                status = "timed_out"
                diagnostics = [{"code": "verification_timeout", "message": "Feasibility could not be verified within the configured time."}]
            else:
                diagnostics = [{"code": "verification_failed", "message": "Feasibility verification could not be completed."}]
            session = SessionLocal()
            try:
                verification = session.query(models.TimetableFeasibilityVerification).filter(
                    models.TimetableFeasibilityVerification.id == int(feasibility_verification_id),
                    models.TimetableFeasibilityVerification.input_snapshot_id == run.input_snapshot_id,
                ).with_for_update().one()
                verification.status = status
                verification.feasible_placements_json = (
                    json.dumps(result["placements"], separators=(",", ":"))
                    if status == "verified" else None
                )
                verification.diagnostics_json = json.dumps(diagnostics, separators=(",", ":"))
                verification.solver_metadata_json = json.dumps({
                    "timeout_seconds": settings.feasibility_timeout_seconds,
                    "objective": "hard_constraints_only",
                }, separators=(",", ":"))
                if status == "verified":
                    from datetime import datetime
                    verification.verified_at = datetime.utcnow()
                run_row = session.query(models.TimetableGenerationRun).filter(
                    models.TimetableGenerationRun.id == run_id,
                ).with_for_update().one()
                run_row.status = "succeeded" if status == "verified" else (
                    "infeasible" if status == "conflict" else (
                        "timed_out" if status == "timed_out" else "internal_error"
                    )
                )
                run_row.progress_phase = "complete" if status == "verified" else "failed"
                run_row.safe_failure_details = (
                    "Feasibility verified." if status == "verified"
                    else diagnostics[0]["message"]
                )
                from datetime import datetime
                run_row.finished_at = datetime.utcnow()
                run_row.lease_owner = None
                run_row.lease_expires_at = None
                session.commit()
            finally:
                session.close()
            return
        if result["outcome"] == "cancelled":
            _terminal(run_id, owner, "cancelled", "cancelled", "Generation was cancelled.")
            return
        if result["outcome"] == "infeasible":
            _mark_infeasible(run_id, owner, problem, settings, solver)
            return
        if result["outcome"] == "timed_out":
            fallback = problem.get("verified_feasible_placements") or []
            fallback_validation = TimetableSolutionValidator().validate(
                problem=problem, placements=fallback,
                expected_fingerprint=expected_fingerprint,
                current_fingerprint=expected_fingerprint,
                expected_source_revision=problem.get("source_edit_revision"),
                current_source_revision=problem.get("source_edit_revision"),
                expected_scope=problem.get("scope"), current_scope=problem.get("scope"),
            ) if fallback else {"valid": False}
            if not fallback_validation["valid"]:
                _terminal(run_id, owner, "timed_out", "solver_timeout", "Generation timed out.")
                return
            result = {
                **result,
                "outcome": "feasible",
                "placements": fallback,
                "used_verified_fallback": True,
            }
        if result["outcome"] != "feasible":
            _terminal(run_id, owner, "internal_error", "solver_model_invalid", "Generation failed.")
            return

        session = SessionLocal()
        try:
            set_run_progress(session, run_id=run_id, lease_owner=owner, phase="checking")
            session.commit()
        finally:
            session.close()
        validation = TimetableSolutionValidator().validate(
            problem=problem,
            placements=result["placements"],
            expected_fingerprint=expected_fingerprint,
            current_fingerprint=expected_fingerprint,
            expected_source_revision=problem.get("source_edit_revision"),
            current_source_revision=problem.get("source_edit_revision"),
            expected_scope=problem.get("scope"),
            current_scope=problem.get("scope"),
        )
        if not validation["valid"]:
            _terminal(
                run_id, owner, "internal_error", "validator_rejected",
                "Generated result failed validation.",
            )
            return

        session = SessionLocal()
        try:
            set_run_progress(session, run_id=run_id, lease_owner=owner, phase="saving")
            session.commit()
        finally:
            session.close()

        session = SessionLocal()
        try:
            persist_generated_result(
                session,
                run_id=run_id,
                lease_owner=owner,
                problem=problem,
                placements=result["placements"],
                solver_result=result,
            )
            session.commit()
        except TimetableGenerationError:
            # Stale/validator outcomes are deliberately persisted by the service.
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("Run %s persistence failed.", run_id)
            _terminal(run_id, owner, "internal_error", "persistence_failed", "Generation failed while saving.")
        finally:
            session.close()
    except TimetableGenerationError as exc:
        if exc.code == "cancel_requested":
            _terminal(run_id, owner, "cancelled", "cancelled", "Generation was cancelled.")
        else:
            logger.info("Run %s stopped after %s.", run_id, exc.code)
    except TimetableProblemError as exc:
        _terminal(run_id, owner, _problem_error_status(exc.code), exc.code, exc.message)
    except Exception:
        logger.exception("Run %s failed.", run_id)
        _terminal(run_id, owner, "internal_error", "worker_error", "Generation failed.")
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)


def execute_generation_run(
    generation_run_public_id: str,
    settings: WorkerSettings | None = None,
) -> bool:
    """Claim and execute one exact durable run; duplicate invocations are no-ops."""
    settings = settings or WorkerSettings.from_environment()
    session = SessionLocal()
    try:
        run = claim_run_by_public_id(
            session,
            public_id=generation_run_public_id,
            lease_seconds=settings.lease_seconds,
        )
        if run is None:
            session.commit()
            return False
        run_id = int(run.id)
        owner = str(run.lease_owner)
        session.commit()
    finally:
        session.close()
    process_run(run_id, owner, settings)
    return True


def run_once(settings: WorkerSettings | None = None) -> bool:
    settings = settings or WorkerSettings.from_environment()
    session = SessionLocal()
    try:
        run = claim_next_run(
            session,
            lease_seconds=settings.lease_seconds,
            max_attempts=settings.max_attempts,
        )
        if run is None:
            session.commit()
            return False
        run_id = int(run.id)
        owner = str(run.lease_owner)
        session.commit()
    finally:
        session.close()
    process_run(run_id, owner, settings)
    return True


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    settings = WorkerSettings.from_environment()
    stop = threading.Event()
    logger.info("Optional local timetable generation polling worker started.")
    while True:
        if not run_once(settings):
            stop.wait(settings.poll_seconds)


if __name__ == "__main__":
    main()
