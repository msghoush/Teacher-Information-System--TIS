import pytest

from timetable_cp_sat_solver import diagnose_infeasible_problem, solve_timetable
from timetable_solution_validator import TimetableSolutionValidator


pytest.importorskip("ortools")


def _demand(section, subject, teacher, periods, rule=None):
    return {
        "demand_id": f"section:{section}|subject:{subject}|teacher:{teacher}",
        "section_id": section,
        "subject_code": subject,
        "teacher_id": teacher,
        "required_weekly_periods": periods,
        "distribution_rule": rule,
    }


def _problem(demands, slots, **overrides):
    problem = {
        "schema_version": 4,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "working_days": list(dict.fromkeys(slot["day_key"] for slot in slots)),
        "slots": slots,
        "sections": [{"id": section} for section in sorted({item["section_id"] for item in demands})],
        "demands": demands,
        "locks": [],
        "request_mode": "generate",
        "source_arrangement": [],
        "minimum_difference": 0,
        "quality_rules": {},
        "grouped_activities": [],
        "teacher_scheduling_rules": [],
        "teacher_schedule_windows_by_demand": {},
    }
    problem.update(overrides)
    return problem


def _slot(day, period, adjacent=False):
    return {
        "slot_id": f"{day}:{period}", "day_key": day,
        "period_index": period, "next_period_physically_adjacent": adjacent,
    }


def test_diagnostic_isolates_base_collision_infeasibility():
    slots = [_slot("sunday", 1)]
    problem = _problem([
        _demand(1, "A", 10, 1), _demand(2, "B", 10, 1),
    ], slots)
    result = diagnose_infeasible_problem(problem, timeout_seconds=2)
    assert result["category"] == "base"


def test_diagnostic_isolates_locks():
    slots = [_slot("sunday", 1), _slot("sunday", 2)]
    demands = [_demand(1, "A", 10, 1), _demand(2, "B", 10, 1)]
    problem = _problem(demands, slots, locks=[
        {"section_id": 1, "subject_code": "A", "teacher_id": 10,
         "day_key": "sunday", "period_index": 1},
        {"section_id": 2, "subject_code": "B", "teacher_id": 10,
         "day_key": "sunday", "period_index": 1},
    ])
    result = diagnose_infeasible_problem(problem, timeout_seconds=2)
    assert result["category"] == "locks"
    assert result["lock_count"] == 2


def test_diagnostic_isolates_grouped_resource_capacity():
    slots = [_slot("sunday", 1), _slot("sunday", 2)]
    demands = []
    groups = []
    for group_index, teacher in enumerate((10, 20, 30), 1):
        members = []
        for offset in (0, 1):
            section = (group_index - 1) * 2 + offset + 1
            demand = _demand(section, f"G{group_index}", teacher, 1)
            demands.append(demand)
            members.append(demand["demand_id"])
        groups.append({
            "key": f"group-{group_index}", "demand_ids": members,
            "section_ids": [(group_index - 1) * 2 + 1, (group_index - 1) * 2 + 2],
            "subject_code": f"G{group_index}", "teacher_id": teacher,
            "required_weekly_periods": 1, "resource_key": "shared-pool",
            "resource_capacity": 1,
        })
    result = diagnose_infeasible_problem(
        _problem(demands, slots, grouped_activities=groups), timeout_seconds=2,
    )
    assert result["category"] == "grouped_activities"
    assert result["grouped_activity_count"] == 3


def test_diagnostic_isolates_subject_distribution_rules():
    rule = {
        "block_length": 2, "block_count": 1, "single_count": 0,
        "min_teaching_days": None, "max_periods_per_day": None,
        "require_daily_coverage": "never", "spread_distinct_days": False,
        "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard",
    }
    problem = _problem(
        [_demand(1, "A", 10, 2, rule)],
        [_slot("sunday", 1), _slot("monday", 1)],
    )
    assert diagnose_infeasible_problem(problem, timeout_seconds=2)["category"] == "subject_distribution_rules"


def test_diagnostic_isolates_teacher_scheduling_rules():
    demand = _demand(1, "A", 10, 2)
    problem = _problem(
        [demand], [_slot("sunday", 1), _slot("sunday", 2)],
        teacher_schedule_windows_by_demand={
            demand["demand_id"]: [{"day_key": "sunday", "period_index": 1}],
        },
    )
    assert diagnose_infeasible_problem(problem, timeout_seconds=2)["category"] == "teacher_scheduling_rules"


def test_diagnostic_isolates_subject_teacher_interaction():
    rule = {
        "block_length": 1, "block_count": 0, "single_count": 2,
        "min_teaching_days": None, "max_periods_per_day": None,
        "require_daily_coverage": "always", "spread_distinct_days": False,
        "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard",
    }
    demand = _demand(1, "A", 10, 2, rule)
    problem = _problem(
        [demand],
        [_slot("sunday", 1, True), _slot("sunday", 2), _slot("monday", 1)],
        teacher_schedule_windows_by_demand={
            demand["demand_id"]: [
                {"day_key": "sunday", "period_index": 1},
                {"day_key": "sunday", "period_index": 2},
            ],
        },
    )
    result = diagnose_infeasible_problem(problem, timeout_seconds=2)
    assert result["category"] == "subject_teacher_interaction"


def test_six_section_full_utilization_with_distribution_and_teacher_rules_is_feasible():
    days = ["sunday", "monday", "tuesday", "wednesday", "thursday"]
    slots = [
        _slot(day, period, adjacent=period < 8)
        for day in days for period in range(1, 9)
    ]
    distribution = {
        "block_length": 2, "block_count": 3, "single_count": 2,
        "min_teaching_days": 5, "max_periods_per_day": 2,
        "require_daily_coverage": "always", "spread_distinct_days": False,
        "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard",
    }
    demands = [
        _demand(section, f"S{subject}", section + 1, 8, distribution)
        for section in range(6) for subject in range(5)
    ]
    baseline = _problem(demands, slots)
    first = solve_timetable(
        baseline, timeout_seconds=20, seed=47498178, search_workers=1,
        optimize_soft_constraints=False,
    )
    assert first["outcome"] == "feasible"
    assert len(first["placements"]) == 240
    assert TimetableSolutionValidator().validate(
        problem=baseline, placements=first["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]

    required = first["placements"][0]
    demand_id = next(
        item["demand_id"] for item in demands
        if item["section_id"] == required["section_id"]
        and item["subject_code"] == required["subject_code"]
        and item["teacher_id"] == required["teacher_id"]
    )
    baseline["teacher_scheduling_rules"] = [{
        "id": 1, "teacher_id": required["teacher_id"], "rule_type": "must_teach",
        "strictness": "hard", "target_scope": "selected_sections",
        "eligible_demand_ids": [demand_id],
        "resolved_slots": [{
            "day_key": required["day_key"], "period_index": required["period_index"],
        }],
    }]
    baseline["teacher_schedule_windows_by_demand"] = {
        demand_id: [
            {"day_key": slot["day_key"], "period_index": slot["period_index"]}
            for slot in slots
        ],
    }
    result = solve_timetable(
        baseline, timeout_seconds=20, seed=13, search_workers=1,
    )
    assert result["outcome"] == "feasible"
    assert len(result["placements"]) == 240
    assert all(
        sum(1 for item in result["placements"] if item["section_id"] == section) == 40
        for section in range(6)
    )


def test_diagnostic_timeout_is_inconclusive_and_zero_lock_group_profiles_are_skipped(monkeypatch):
    import timetable_cp_sat_solver as solver

    calls = []
    monkeypatch.setattr(
        solver,
        "solve_timetable",
        lambda problem, **kwargs: calls.append(kwargs) or {"outcome": "timed_out"},
    )
    demand = _demand(1, "A", 10, 1, {
        "block_length": 1, "block_count": 0, "single_count": 1,
        "min_teaching_days": None, "max_periods_per_day": None,
        "require_daily_coverage": "never", "spread_distinct_days": False,
        "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard",
    })
    problem = _problem(
        [demand], [_slot("sunday", 1)],
        teacher_scheduling_rules=[{
            "id": 1, "teacher_id": 10, "rule_type": "must_teach",
            "strictness": "hard", "eligible_demand_ids": [demand["demand_id"]],
            "resolved_slots": [{"day_key": "sunday", "period_index": 1}],
        }],
    )
    result = solver.diagnose_infeasible_problem(problem, timeout_seconds=61)
    assert result["category"] == "diagnostic_inconclusive"
    assert len(calls) == 4
    assert {call["timeout_seconds"] for call in calls} == {61}
