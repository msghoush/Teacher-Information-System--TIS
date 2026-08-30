from __future__ import annotations

from collections import defaultdict
from threading import Event, Thread

from ortools.sat.python import cp_model


SOLVER_NAME = "OR-Tools CP-SAT"
HARD_CONSTRAINT_FAMILIES = frozenset({
    "locks", "grouped_activities", "subject_distribution_rules",
    "teacher_scheduling_rules", "regeneration_diversity",
})


def solve_timetable(
    problem: dict,
    *,
    timeout_seconds: float,
    seed: int,
    search_workers: int,
    cancel_event: Event | None = None,
    enabled_constraint_families: set[str] | frozenset[str] | None = None,
) -> dict:
    """Solve one immutable timetable problem. Imported only by the worker."""
    model = cp_model.CpModel()
    enabled = (
        HARD_CONSTRAINT_FAMILIES
        if enabled_constraint_families is None
        else frozenset(enabled_constraint_families)
    )
    variables = {}
    by_section_slot = defaultdict(list)
    by_teacher_slot = defaultdict(list)
    grouped_representative = {}
    grouped_by_key = {}
    for group in (
        problem.get("grouped_activities") or []
        if "grouped_activities" in enabled else []
    ):
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
    for lock in problem["locks"] if "locks" in enabled else []:
        demand_id = demand_id_by_key[(
            lock["section_id"], lock["subject_code"], lock["teacher_id"]
        )]
        model.add(variables[(demand_id, lock["day_key"], lock["period_index"])] == 1)

    quality = (
        problem.get("quality_rules") or {}
        if "subject_distribution_rules" in enabled else {}
    )
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
    schedule_windows = {
        demand_id: {
            (slot["day_key"], int(slot["period_index"])) for slot in allowed
        }
        for demand_id, allowed in (
            (problem.get("teacher_schedule_windows_by_demand") or {})
            if "teacher_scheduling_rules" in enabled else {}
        ).items()
    }
    if not schedule_windows:
        for rule in (
            problem.get("teacher_scheduling_rules") or []
            if "teacher_scheduling_rules" in enabled else []
        ):
            if rule["rule_type"] != "schedule_within":
                continue
            allowed = {
                (slot["day_key"], int(slot["period_index"]))
                for slot in rule.get("resolved_slots") or []
            }
            for demand_id in rule.get("eligible_demand_ids") or []:
                representative = grouped_representative.get(demand_id, demand_id)
                schedule_windows.setdefault(representative, set()).update(allowed)
    for demand_id, allowed_slots in schedule_windows.items():
        for slot in problem["slots"]:
            if (slot["day_key"], slot["period_index"]) not in allowed_slots:
                model.add(variables[(demand_id, slot["day_key"], slot["period_index"])] == 0)

    for rule in (
        problem.get("teacher_scheduling_rules") or []
        if "teacher_scheduling_rules" in enabled else []
    ):
        demand_ids = sorted({
            grouped_representative.get(demand_id, demand_id)
            for demand_id in rule.get("eligible_demand_ids") or []
        })
        allowed_slots = {
            (slot["day_key"], slot["period_index"])
            for slot in rule.get("resolved_slots") or []
        }
        if rule["rule_type"] == "schedule_within":
            continue
        for slot in rule.get("resolved_slots") or []:
            values = [
                variables[(demand_id, slot["day_key"], slot["period_index"])]
                for demand_id in demand_ids
            ]
            occupancy = sum(values)
            if rule["rule_type"] == "must_teach":
                model.add(occupancy == 1)
            elif rule["rule_type"] == "unavailable":
                model.add(occupancy == 0)
            elif rule["rule_type"] in {"prefer_teaching", "prefer_free"}:
                occupied = model.new_bool_var(
                    f"teacher_preference|{rule['id']}|{slot['day_key']}|{slot['period_index']}"
                )
                model.add_max_equality(occupied, values)
                objective_terms.append((12 if rule["rule_type"] == "prefer_teaching" else -12) * occupied)
    slots_by_day = defaultdict(list)
    for slot in problem["slots"]:
        slots_by_day[slot["day_key"]].append(slot)
    working_days = list(problem.get("working_days") or [])
    num_days = len(working_days)
    for demand in problem["demands"]:
        code = demand["subject_code"]
        demand_id = demand["demand_id"]
        rule = (
            demand.get("distribution_rule")
            if "subject_distribution_rules" in enabled else None
        )
        day_used = []
        for day in working_days:
            day_vars = [variables[(demand_id, day, slot["period_index"])] for slot in slots_by_day[day]]
            if not day_vars:
                continue
            used = model.new_bool_var(f"day_used|{demand_id}|{day}")
            model.add_max_equality(used, day_vars)
            day_used.append(used)

            if rule is not None:
                # Generalized Subject Distribution Rule replaces the flat
                # code-list checks below for this demand.
                coverage_mode = rule["require_daily_coverage"]
                if coverage_mode != "never" and int(demand["required_weekly_periods"]) >= num_days:
                    model.add(sum(day_vars) >= 1)
                if rule["spread_distinct_days"] and coverage_mode != "never":
                    objective_terms.append(20 * used)
                max_per_day = rule["max_periods_per_day"]
                if max_per_day:
                    if rule["strictness"] == "hard":
                        model.add(sum(day_vars) <= max_per_day)
                    else:
                        over = model.new_bool_var(f"over_max|{demand_id}|{day}")
                        model.add(sum(day_vars) <= max_per_day + len(day_vars) * over)
                        objective_terms.append(-25 * over)
                # Intentional blocks are exempt from the consecutive-avoidance
                # penalty; the exact-block constraint below governs them.
                if rule["avoid_consecutive"] and rule["block_count"] <= 0:
                    ordered = sorted(slots_by_day[day], key=lambda item: item["period_index"])
                    for left, right in zip(ordered, ordered[1:]):
                        if not left.get("next_period_physically_adjacent"):
                            continue
                        adjacent = model.new_bool_var(f"adjacent|{demand_id}|{day}|{left['period_index']}")
                        model.add_multiplication_equality(adjacent, [
                            variables[(demand_id, day, left["period_index"])],
                            variables[(demand_id, day, right["period_index"])],
                        ])
                        objective_terms.append(-8 * adjacent)
            else:
                # Legacy fallback: no normalized rule configured for this
                # demand, so the existing branch/year quality_rules_json
                # behavior applies unchanged.
                if code in core_codes and int(demand["required_weekly_periods"]) >= num_days:
                    model.add(sum(day_vars) >= 1)
                if code in ict_codes and quality.get("ict_hard_one_per_day") and int(demand["required_weekly_periods"]) <= num_days:
                    model.add(sum(day_vars) <= 1)
                if code in core_codes or code in spread_codes or code in ict_codes:
                    objective_terms.append(20 * used)
                if code in avoid_consecutive and code not in allow_double:
                    ordered = sorted(slots_by_day[day], key=lambda item: item["period_index"])
                    for left, right in zip(ordered, ordered[1:]):
                        if int(right["period_index"]) != int(left["period_index"]) + 1:
                            continue
                        adjacent = model.new_bool_var(f"adjacent|{demand_id}|{day}|{left['period_index']}")
                        model.add_multiplication_equality(adjacent, [
                            variables[(demand_id, day, left["period_index"])],
                            variables[(demand_id, day, right["period_index"])],
                        ])
                        objective_terms.append(-8 * adjacent)

        if rule is not None:
            coverage_mode = rule["require_daily_coverage"]
            if (
                day_used and rule["spread_distinct_days"] and coverage_mode != "never"
                and int(demand["required_weekly_periods"]) < num_days
            ):
                objective_terms.extend(30 * used for used in day_used)
            if rule["strictness"] == "hard" and rule.get("min_teaching_days"):
                model.add(sum(day_used) >= int(rule["min_teaching_days"]))
            if rule["block_count"] > 0:
                # Exactly ``block_count`` true consecutive block_length-period
                # blocks must exist; a period may belong to at most one
                # counted block so overlapping runs cannot fake extra blocks.
                pair_vars = []
                covering_by_slot = defaultdict(list)
                for day in working_days:
                    ordered = sorted(slots_by_day[day], key=lambda item: item["period_index"])
                    for left, right in zip(ordered, ordered[1:]):
                        if not left.get("next_period_physically_adjacent"):
                            continue
                        pair_var = model.new_bool_var(
                            f"block|{demand_id}|{day}|{left['period_index']}"
                        )
                        model.add_multiplication_equality(pair_var, [
                            variables[(demand_id, day, left["period_index"])],
                            variables[(demand_id, day, right["period_index"])],
                        ])
                        pair_vars.append(pair_var)
                        covering_by_slot[(day, left["period_index"])].append(pair_var)
                        covering_by_slot[(day, right["period_index"])].append(pair_var)
                for covering in covering_by_slot.values():
                    if len(covering) > 1:
                        model.add(sum(covering) <= 1)
                model.add(sum(pair_vars) == int(rule["block_count"]))
        elif day_used and int(demand["required_weekly_periods"]) < num_days and code in core_codes:
            objective_terms.extend(30 * used for used in day_used)

    if (
        problem.get("request_mode") == "regenerate"
        and "regeneration_diversity" in enabled
    ):

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


def diagnose_infeasible_problem(
    problem: dict, *, timeout_seconds: float = 10, seed: int = 13,
    search_workers: int = 1,
) -> dict:
    """Isolate a proven infeasible hard-constraint family without relaxing the real run."""
    profiles = [
        ("base", frozenset()),
        ("locks", frozenset({"locks"})),
        ("grouped_activities", frozenset({"grouped_activities"})),
        ("subject_distribution_rules", frozenset({"subject_distribution_rules"})),
        ("teacher_scheduling_rules", frozenset({"teacher_scheduling_rules"})),
        ("subject_teacher_interaction", frozenset({
            "subject_distribution_rules", "teacher_scheduling_rules",
        })),
    ]
    outcomes = {}
    for name, families in profiles:
        result = solve_timetable(
            problem,
            timeout_seconds=max(float(timeout_seconds), 0.01),
            seed=seed,
            search_workers=search_workers,
            enabled_constraint_families=families,
        )
        outcomes[name] = result["outcome"]
        if result["outcome"] == "infeasible":
            if name != "base" and outcomes.get("base") != "feasible":
                continue
            if name == "subject_teacher_interaction" and not all(
                outcomes.get(component) == "feasible"
                for component in (
                    "subject_distribution_rules", "teacher_scheduling_rules",
                )
            ):
                continue
            messages = {
                "base": "Base demand cannot fit section and teacher collision constraints even without locks or scheduling rules.",
                "locks": "The timetable becomes infeasible when current lesson locks are enforced.",
                "grouped_activities": "The timetable becomes infeasible when grouped activities and shared resources are enforced.",
                "subject_distribution_rules": "The timetable becomes infeasible when Subject Distribution Rules are enforced.",
                "teacher_scheduling_rules": "The timetable becomes infeasible when Teacher Scheduling Rules are enforced.",
                "subject_teacher_interaction": "Subject Distribution Rules and Teacher Scheduling Rules are individually feasible but conflict when enforced together.",
            }
            return {
                "category": name,
                "message": messages[name],
                "outcomes": outcomes,
                "lock_count": len(problem.get("locks") or []),
                "grouped_activity_count": len(problem.get("grouped_activities") or []),
                "request_mode": str(problem.get("request_mode") or "generate"),
                "has_source_version": problem.get("source_version_id") is not None,
            }
    inconclusive = any(value == "timed_out" for value in outcomes.values())
    return {
        "category": "diagnostic_inconclusive" if inconclusive else "combined_hard_constraints",
        "message": (
            "Diagnostic isolation timed out before proving one conflicting family."
            if inconclusive else
            "The conflict requires a combination involving locks, grouped activities, or multiple hard-rule families."
        ),
        "outcomes": outcomes,
        "lock_count": len(problem.get("locks") or []),
        "grouped_activity_count": len(problem.get("grouped_activities") or []),
        "request_mode": str(problem.get("request_mode") or "generate"),
        "has_source_version": problem.get("source_version_id") is not None,
    }
