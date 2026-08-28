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
    grouped_representative = {}
    grouped_by_key = {}
    for group in problem.get("grouped_activities") or []:
        demand_ids = list(group.get("demand_ids") or [])
        if not demand_ids:
            continue
        representative = demand_ids[0]
        grouped_by_key[group["key"]] = (group, representative)
        for demand_id in demand_ids:
            grouped_representative[demand_id] = representative

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
            if grouped_representative.get(demand_id, demand_id) == demand_id:
                by_teacher_slot[(
                    demand["teacher_id"], slot["day_key"], slot["period_index"]
                )].append(variable)
        model.add(sum(demand_variables) == int(demand["required_weekly_periods"]))

    for values in by_section_slot.values():
        model.add(sum(values) <= 1)
    for values in by_teacher_slot.values():
        model.add(sum(values) <= 1)

    resource_slot_groups = defaultdict(list)
    for group, representative in grouped_by_key.values():
        for member in group["demand_ids"][1:]:
            for slot in problem["slots"]:
                model.add(
                    variables[(member, slot["day_key"], slot["period_index"])]
                    == variables[(representative, slot["day_key"], slot["period_index"])]
                )
        if group.get("resource_key"):
            for slot in problem["slots"]:
                resource_slot_groups[(group["resource_key"], slot["day_key"], slot["period_index"])].append(
                    (variables[(representative, slot["day_key"], slot["period_index"])], int(group.get("resource_capacity") or 1))
                )
    for values in resource_slot_groups.values():
        capacity = min(item[1] for item in values)
        model.add(sum(item[0] for item in values) <= capacity)

    demand_id_by_key = {
        (item["section_id"], item["subject_code"], item["teacher_id"]): item["demand_id"]
        for item in problem["demands"]
    }
    for lock in problem["locks"]:
        demand_id = demand_id_by_key[(
            lock["section_id"], lock["subject_code"], lock["teacher_id"]
        )]
        model.add(variables[(demand_id, lock["day_key"], lock["period_index"])] == 1)

    quality = problem.get("quality_rules") or {}
    core_codes = {
        str(code).upper()
        for values in (quality.get("core_subject_codes") or {}).values()
        for code in values or []
    }
    spread_codes = {str(code).upper() for code in quality.get("spread_subject_codes") or []}
    ict_codes = {str(code).upper() for code in quality.get("ict_subject_codes") or []}
    avoid_consecutive = {str(code).upper() for code in quality.get("avoid_consecutive_subject_codes") or []}
    allow_double = {str(code).upper() for code in quality.get("allow_double_period_subject_codes") or []}
    objective_terms = []
    slots_by_day = defaultdict(list)
    for slot in problem["slots"]:
        slots_by_day[slot["day_key"]].append(slot)
    for demand in problem["demands"]:
        code = demand["subject_code"]
        day_used = []
        for day in problem.get("working_days") or []:
            day_vars = [variables[(demand["demand_id"], day, slot["period_index"])] for slot in slots_by_day[day]]
            if not day_vars:
                continue
            used = model.new_bool_var(f"day_used|{demand['demand_id']}|{day}")
            model.add_max_equality(used, day_vars)
            day_used.append(used)
            if code in core_codes and int(demand["required_weekly_periods"]) >= len(problem.get("working_days") or []):
                model.add(sum(day_vars) >= 1)
            if code in ict_codes and quality.get("ict_hard_one_per_day") and int(demand["required_weekly_periods"]) <= len(problem.get("working_days") or []):
                model.add(sum(day_vars) <= 1)
            if code in core_codes or code in spread_codes or code in ict_codes:
                objective_terms.append(20 * used)
            if code in avoid_consecutive and code not in allow_double:
                ordered = sorted(slots_by_day[day], key=lambda item: item["period_index"])
                for left, right in zip(ordered, ordered[1:]):
                    if int(right["period_index"]) != int(left["period_index"]) + 1:
                        continue
                    adjacent = model.new_bool_var(f"adjacent|{demand['demand_id']}|{day}|{left['period_index']}")
                    model.add_multiplication_equality(adjacent, [
                        variables[(demand["demand_id"], day, left["period_index"])],
                        variables[(demand["demand_id"], day, right["period_index"])],
                    ])
                    objective_terms.append(-8 * adjacent)
        if day_used and int(demand["required_weekly_periods"]) < len(problem.get("working_days") or []) and code in core_codes:
            objective_terms.extend(30 * used for used in day_used)

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

    if objective_terms:
        model.maximize(sum(objective_terms))

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
