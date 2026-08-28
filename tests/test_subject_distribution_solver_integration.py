"""Focused Stage 2 tests wiring resolved Subject Distribution Rules into the
CP-SAT solver and the independent validator, with true physical adjacency."""
import pytest

from timetable_solution_validator import TimetableSolutionValidator


def _solve(problem, seed=17):
    pytest.importorskip("ortools")
    from timetable_cp_sat_solver import solve_timetable

    return solve_timetable(problem, timeout_seconds=20, seed=seed, search_workers=1)


def _slots(days, periods, non_adjacent_after=()):
    """``non_adjacent_after`` is an iterable of (day, period_index) pairs after
    which the composed timeline places a Break/Prayer/other non-teaching item,
    so the next period is not physically adjacent."""
    blocked = set(non_adjacent_after)
    slots = []
    for day in days:
        for period in range(1, periods + 1):
            slots.append({
                "slot_id": f"{day}:{period}", "day_key": day, "period_index": period,
                "next_period_physically_adjacent": period < periods and (day, period) not in blocked,
            })
    return slots


def _problem(demands, *, periods=5, days=None, quality=None, groups=None,
             non_adjacent_after=(), request_mode="generate", source_arrangement=None,
             minimum_difference=0):
    days = days or ["monday", "tuesday", "wednesday", "thursday", "friday"]
    return {
        "schema_version": 3,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "working_days": days,
        "slots": _slots(days, periods, non_adjacent_after),
        "sections": [],
        "demands": demands,
        "locks": [],
        "request_mode": request_mode,
        "source_arrangement": source_arrangement or [],
        "minimum_difference": minimum_difference,
        "quality_rules": quality or {},
        "grouped_activities": groups or [],
    }


def _rule(**overrides):
    rule = {
        "block_length": 2, "block_count": 0, "single_count": 0,
        "min_teaching_days": None, "max_periods_per_day": None,
        "require_daily_coverage": "auto", "spread_distinct_days": True,
        "avoid_consecutive": True, "min_day_gap": None, "strictness": "soft",
        "source_scope_level": "grade",
    }
    rule.update(overrides)
    return rule


def _demand(section, code, teacher, count, rule=None):
    demand = {
        "demand_id": f"section:{section}|subject:{code}|teacher:{teacher}",
        "section_id": section, "subject_code": code, "teacher_id": teacher,
        "required_weekly_periods": count,
    }
    if rule is not None:
        demand["distribution_rule"] = rule
    return demand


def _days_for(placements, code):
    return {item["day_key"] for item in placements if item["subject_code"] == code}


def _periods_for_day(placements, code, day):
    return sorted(item["period_index"] for item in placements if item["subject_code"] == code and item["day_key"] == day)


def _count_true_blocks(placements, code, slot_lookup):
    total = 0
    by_day = {}
    for item in placements:
        if item["subject_code"] != code:
            continue
        by_day.setdefault(item["day_key"], []).append(item["period_index"])
    for day, periods in by_day.items():
        selected = sorted(periods)
        consumed = set()
        for period in selected:
            if period in consumed:
                continue
            if (period + 1) in selected and slot_lookup.get((day, period), {}).get("next_period_physically_adjacent"):
                total += 1
                consumed.update({period, period + 1})
    return total


# --- Blocks -------------------------------------------------------------------

def test_english_8_periods_two_doubles_four_singles():
    rule = _rule(block_count=2, single_count=4)
    problem = _problem([_demand(1, "ENG", 11, 8, rule)])
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    slot_lookup = {(s["day_key"], s["period_index"]): s for s in problem["slots"]}
    assert _count_true_blocks(result["placements"], "ENG", slot_lookup) == 2
    assert len(result["placements"]) == 8
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


def test_exact_configured_block_count_enforced():
    rule = _rule(block_count=1, single_count=2)
    problem = _problem([_demand(1, "SCI", 11, 4, rule)], periods=4)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    slot_lookup = {(s["day_key"], s["period_index"]): s for s in problem["slots"]}
    assert _count_true_blocks(result["placements"], "SCI", slot_lookup) == 1


def test_break_separated_periods_do_not_satisfy_block():
    rule = _rule(block_count=1, single_count=0)
    problem = _problem([_demand(1, "PE", 20, 2, rule)], periods=2)
    # Manually craft an invalid candidate: two selected periods on the same
    # day are consecutive period_index but a Break sits between them.
    problem["slots"] = _slots(problem["working_days"], 2, non_adjacent_after={("monday", 1)})
    invalid = [
        {"section_id": 1, "subject_code": "PE", "teacher_id": 20,
         "day_key": "monday", "period_index": 1, "is_locked": False},
        {"section_id": 1, "subject_code": "PE", "teacher_id": 20,
         "day_key": "monday", "period_index": 2, "is_locked": False},
    ]
    result = TimetableSolutionValidator().validate(
        problem=problem, placements=invalid,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "distribution_block_count_mismatch" in {item["code"] for item in result["errors"]}


def test_prayer_separated_periods_do_not_satisfy_block():
    rule = _rule(block_count=1, single_count=0)
    problem = _problem([_demand(1, "PE", 20, 2, rule)], periods=2)
    problem["slots"] = _slots(problem["working_days"], 2, non_adjacent_after={("monday", 1)})
    invalid = [
        {"section_id": 1, "subject_code": "PE", "teacher_id": 20,
         "day_key": "monday", "period_index": 1, "is_locked": False},
        {"section_id": 1, "subject_code": "PE", "teacher_id": 20,
         "day_key": "monday", "period_index": 2, "is_locked": False},
    ]
    result = TimetableSolutionValidator().validate(
        problem=problem, placements=invalid,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "distribution_block_count_mismatch" in {item["code"] for item in result["errors"]}


def test_intentional_block_is_not_penalized_as_unwanted_consecutive_placement():
    rule = _rule(block_count=1, single_count=0, avoid_consecutive=True)
    problem = _problem([_demand(1, "PE", 20, 2, rule)], periods=2)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    slot_lookup = {(s["day_key"], s["period_index"]): s for s in problem["slots"]}
    assert _count_true_blocks(result["placements"], "PE", slot_lookup) == 1
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


# --- Daily coverage -------------------------------------------------------------

def test_weekly_demand_meets_teaching_days_hard_daily_coverage_succeeds():
    rule = _rule(require_daily_coverage="always")
    problem = _problem([_demand(1, "ENG", 11, 5, rule)], periods=3)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "ENG")) == 5


def test_weekly_demand_below_teaching_days_maximizes_distinct_days_without_infeasibility():
    rule = _rule(require_daily_coverage="auto", spread_distinct_days=True)
    problem = _problem([_demand(1, "ENG", 11, 3, rule)], periods=3)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "ENG")) == 3


# --- PE ------------------------------------------------------------------------

def test_pe_normal_mode_two_singles_distribute_across_different_days_hard_max_one():
    rule = _rule(block_count=0, single_count=2, spread_distinct_days=True,
                 max_periods_per_day=1, strictness="hard")
    problem = _problem([_demand(1, "PE", 20, 2, rule)], periods=2)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "PE")) == 2
    for day in problem["working_days"]:
        assert len(_periods_for_day(result["placements"], "PE", day)) <= 1
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


def test_pe_swimming_two_periods_form_exactly_one_true_double_block():
    rule = _rule(block_count=1, block_length=2, single_count=0)
    problem = _problem([_demand(1, "PE", 20, 2, rule)], periods=2)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    slot_lookup = {(s["day_key"], s["period_index"]): s for s in problem["slots"]}
    assert _count_true_blocks(result["placements"], "PE", slot_lookup) == 1


def test_pe_swimming_four_periods_form_two_double_blocks():
    rule = _rule(block_count=2, block_length=2, single_count=0)
    problem = _problem([_demand(1, "PE", 20, 4, rule)], periods=2)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    slot_lookup = {(s["day_key"], s["period_index"]): s for s in problem["slots"]}
    assert _count_true_blocks(result["placements"], "PE", slot_lookup) == 2
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


# --- ICT / spread ----------------------------------------------------------------

def test_max_per_day_hard_enforcement_generalized():
    rule = _rule(max_periods_per_day=1, strictness="hard", spread_distinct_days=True)
    problem = _problem([_demand(1, "ICT", 11, 2, rule)], periods=3)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    for day in problem["working_days"]:
        assert len(_periods_for_day(result["placements"], "ICT", day)) <= 1


def test_soft_spread_behavior_generalized():
    rule = _rule(spread_distinct_days=True)
    problem = _problem([_demand(1, "ART", 11, 3, rule)], periods=3)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "ART")) == 3


def test_avoid_consecutive_soft_behavior_generalized():
    rule = _rule(block_count=0, avoid_consecutive=True, spread_distinct_days=True)
    problem = _problem([_demand(1, "WLB", 11, 2, rule)], periods=3, days=["monday", "tuesday"])
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "WLB")) == 2


# --- Validator -------------------------------------------------------------------

def test_validator_rejects_missing_hard_daily_coverage_and_max_per_day():
    rule = _rule(require_daily_coverage="always")
    problem = _problem([_demand(1, "ENG", 11, 3, rule)], periods=3, days=["monday", "tuesday", "wednesday"])
    invalid = [
        {"section_id": 1, "subject_code": "ENG", "teacher_id": 11,
         "day_key": "monday", "period_index": 1, "is_locked": False},
        {"section_id": 1, "subject_code": "ENG", "teacher_id": 11,
         "day_key": "monday", "period_index": 2, "is_locked": False},
        {"section_id": 1, "subject_code": "ENG", "teacher_id": 11,
         "day_key": "tuesday", "period_index": 1, "is_locked": False},
    ]
    result = TimetableSolutionValidator().validate(
        problem=problem, placements=invalid,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "distribution_daily_coverage_missing" in {item["code"] for item in result["errors"]}

    rule_max = _rule(max_periods_per_day=1, strictness="hard")
    problem_max = _problem([_demand(1, "ICT", 11, 2, rule_max)], periods=2, days=["monday", "tuesday"])
    over_max = [
        {"section_id": 1, "subject_code": "ICT", "teacher_id": 11,
         "day_key": "monday", "period_index": 1, "is_locked": False},
        {"section_id": 1, "subject_code": "ICT", "teacher_id": 11,
         "day_key": "monday", "period_index": 2, "is_locked": False},
    ]
    result_max = TimetableSolutionValidator().validate(
        problem=problem_max, placements=over_max,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "distribution_max_per_day_exceeded" in {item["code"] for item in result_max["errors"]}


# --- Backward compatibility --------------------------------------------------------

def test_no_normalized_rule_preserves_legacy_quality_rule_behavior():
    quality = {"core_subject_codes": {"english": ["ENG"], "mathematics": [], "science": []}}
    problem = _problem([_demand(1, "ENG", 11, 5)], periods=3, quality=quality)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "ENG")) == 5
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


# --- Regeneration ------------------------------------------------------------------

def test_regeneration_preserves_hard_distribution_rules_while_reshuffling():
    rule = _rule(block_count=2, single_count=4)
    demand = _demand(1, "ENG", 11, 8, rule)
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    source_arrangement = []
    ordinal = 0
    for day in days:
        for period in (1, 2):
            source_arrangement.append({
                "section_id": 1, "subject_code": "ENG", "teacher_id": 11,
                "day_key": day, "period_index": period, "is_locked": ordinal == 0,
            })
            ordinal += 1
    problem = _problem(
        [demand], periods=5, days=days, request_mode="regenerate",
        source_arrangement=source_arrangement, minimum_difference=3,
    )
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    slot_lookup = {(s["day_key"], s["period_index"]): s for s in problem["slots"]}
    assert _count_true_blocks(result["placements"], "ENG", slot_lookup) == 2
    validation = TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert validation["valid"]
