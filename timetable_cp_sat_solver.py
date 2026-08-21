from __future__ import annotations

from collections import defaultdict
from threading import Event, Thread

from ortools.sat.python import cp_model


SOLVER_NAME = "OR-Tools CP-SAT"


def solve_timetable(
    problem: dict,
    *,
    timeout_seconds: float,
    seed: int,
    search_workers: int,
    cancel_event: Event | None = None,
) -> dict:
    """Solve one immutable timetable problem. Imported only by the worker."""
    model = cp_model.CpModel()
    variables = {}
    by_section_slot = defaultdict(list)
    by_teacher_slot = defaultdict(list)

    for demand in problem["demands"]:
        demand_id = demand["demand_id"]
        demand_variables = []
        for slot in problem["slots"]:
            variable = model.new_bool_var(f"x|{demand_id}|{slot['slot_id']}")
            variables[(demand_id, slot["day_key"], slot["period_index"])] = variable
            demand_variables.append(variable)
            by_section_slot[(
                demand["section_id"], slot["day_key"], slot["period_index"]
            )].append(variable)
            by_teacher_slot[(
                demand["teacher_id"], slot["day_key"], slot["period_index"]
            )].append(variable)
        model.add(sum(demand_variables) == int(demand["required_weekly_periods"]))

    for values in by_section_slot.values():
        model.add(sum(values) <= 1)
    for values in by_teacher_slot.values():
        model.add(sum(values) <= 1)

    demand_id_by_key = {
        (item["section_id"], item["subject_code"], item["teacher_id"]): item["demand_id"]
        for item in problem["demands"]
    }
    for lock in problem["locks"]:
        demand_id = demand_id_by_key[(
            lock["section_id"], lock["subject_code"], lock["teacher_id"]
        )]
        model.add(variables[(demand_id, lock["day_key"], lock["period_index"])] == 1)

    if problem.get("request_mode") == "regenerate":
        same_unlocked = []
        for item in problem.get("source_arrangement") or []:
            if item.get("is_locked"):
                continue
            demand_id = demand_id_by_key[(
                item["section_id"], item["subject_code"], item["teacher_id"]
            )]
            same_unlocked.append(
                variables[(demand_id, item["day_key"], item["period_index"])]
            )
        minimum_difference = int(problem.get("minimum_difference") or 0)
        if minimum_difference > 0:
            model.add(sum(same_unlocked) <= len(same_unlocked) - minimum_difference)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(float(timeout_seconds), 0.01)
    solver.parameters.random_seed = int(seed)
    solver.parameters.num_search_workers = max(int(search_workers), 1)

    monitor = None
    if cancel_event is not None:
        def stop_when_cancelled() -> None:
            cancel_event.wait()
            if cancel_event.is_set():
                solver.stop_search()

        monitor = Thread(target=stop_when_cancelled, daemon=True)
        monitor.start()

    status = solver.solve(model)
    if cancel_event is not None and cancel_event.is_set():
        outcome = "cancelled"
    elif status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        outcome = "feasible"
    elif status == cp_model.INFEASIBLE:
        outcome = "infeasible"
    elif status == cp_model.MODEL_INVALID:
        outcome = "model_invalid"
    else:
        outcome = "timed_out"

    placements = []
    if outcome == "feasible":
        for demand in problem["demands"]:
            for slot in problem["slots"]:
                variable = variables[(
                    demand["demand_id"], slot["day_key"], slot["period_index"]
                )]
                if solver.value(variable):
                    placements.append({
                        "section_id": demand["section_id"],
                        "subject_code": demand["subject_code"],
                        "teacher_id": demand["teacher_id"],
                        "day_key": slot["day_key"],
                        "period_index": slot["period_index"],
                    })
        placements.sort(key=lambda item: (
            item["day_key"], item["period_index"], item["section_id"],
            item["subject_code"], item["teacher_id"],
        ))

    return {
        "outcome": outcome,
        "placements": placements,
        "wall_time_seconds": float(solver.wall_time),
        "status_code": int(status),
        "solver_name": SOLVER_NAME,
    }
