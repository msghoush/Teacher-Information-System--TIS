import pytest

import db_migrations
from timetable_generation_service import _minimum_difference
from timetable_logic import normalize_timetable_quality_rules
from timetable_solution_validator import TimetableSolutionValidator


def _solve(problem, seed=17):
    pytest.importorskip("ortools")
    from timetable_cp_sat_solver import solve_timetable

    return solve_timetable(problem, timeout_seconds=20, seed=seed, search_workers=1)


def _problem(demands, *, periods=4, quality=None, groups=None):
    days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    return {
        "schema_version": 3,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "working_days": days,
        "slots": [
            {"slot_id": f"{day}:{period}", "day_key": day, "period_index": period}
            for day in days for period in range(1, periods + 1)
        ],
        "sections": [],
        "demands": demands,
        "locks": [],
        "request_mode": "generate",
        "source_arrangement": [],
        "minimum_difference": 0,
        "quality_rules": quality or {},
        "grouped_activities": groups or [],
    }


def _demand(section, code, teacher, count):
    return {
        "demand_id": f"section:{section}|subject:{code}|teacher:{teacher}",
        "section_id": section,
        "subject_code": code,
        "teacher_id": teacher,
        "required_weekly_periods": count,
    }


def _days_for(placements, code):
    return {item["day_key"] for item in placements if item["subject_code"] == code}


def test_core_subjects_cover_every_day_when_weekly_demand_allows():
    quality = {"core_subject_codes": {"english": ["ENG"], "mathematics": ["MAT"], "science": ["SCI"]}}
    problem = _problem([
        _demand(1, "ENG", 11, 5), _demand(1, "MAT", 12, 5), _demand(1, "SCI", 13, 5),
    ], periods=3, quality=quality)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    for code in ("ENG", "MAT", "SCI"):
        assert len(_days_for(result["placements"], code)) == 5
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


def test_short_core_and_spread_subjects_maximize_distinct_days_without_infeasibility():
    quality = {
        "core_subject_codes": {"english": ["ENG"], "mathematics": [], "science": []},
        "spread_subject_codes": ["ART", "WLB", "SOC", "REF"],
        "avoid_consecutive_subject_codes": ["ART", "WLB", "SOC", "REF"],
    }
    demands = [_demand(1, "ENG", 11, 3)] + [
        _demand(1, code, teacher, 2)
        for code, teacher in (("ART", 12), ("WLB", 13), ("SOC", 14), ("REF", 15))
    ]
    result = _solve(_problem(demands, periods=3, quality=quality))
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "ENG")) == 3
    for code in ("ART", "WLB", "SOC", "REF"):
        assert len(_days_for(result["placements"], code)) == 2


def test_ict_hard_one_per_day_and_nonconsecutive_preference():
    quality = {
        "core_subject_codes": {}, "ict_subject_codes": ["ICT"],
        "ict_hard_one_per_day": True, "avoid_consecutive_subject_codes": ["ICT"],
    }
    problem = _problem([_demand(1, "ICT", 11, 2)], periods=3, quality=quality)
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(_days_for(result["placements"], "ICT")) == 2
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


def test_grouped_swimming_is_simultaneous_without_weakening_teacher_exclusivity():
    demands = [
        _demand(1, "PE", 20, 2), _demand(2, "PE", 20, 2),
        _demand(3, "ART", 20, 2),
    ]
    group = {
        "key": "p1_p2_swimming", "subject_code": "PE", "section_ids": [1, 2],
        "teacher_id": 20, "required_weekly_periods": 2,
        "demand_ids": [demands[0]["demand_id"], demands[1]["demand_id"]],
        "resource_key": "pool", "resource_capacity": 1,
    }
    problem = _problem(demands, periods=2, groups=[group])
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    section_one = {(item["day_key"], item["period_index"]) for item in result["placements"] if item["section_id"] == 1}
    section_two = {(item["day_key"], item["period_index"]) for item in result["placements"] if item["section_id"] == 2}
    art = {(item["day_key"], item["period_index"]) for item in result["placements"] if item["section_id"] == 3}
    assert section_one == section_two
    assert section_one.isdisjoint(art)
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


def test_validator_independently_rejects_missing_core_day_and_split_group():
    core_problem = _problem(
        [_demand(1, "ENG", 11, 5)], periods=2,
        quality={"core_subject_codes": {"english": ["ENG"]}},
    )
    invalid_core = [
        {"section_id": 1, "subject_code": "ENG", "teacher_id": 11,
         "day_key": day, "period_index": period, "is_locked": False}
        for day, period in (("monday", 1), ("monday", 2), ("tuesday", 1),
                            ("wednesday", 1), ("thursday", 1))
    ]
    result = TimetableSolutionValidator().validate(
        problem=core_problem, placements=invalid_core,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "core_daily_coverage_missing" in {item["code"] for item in result["errors"]}

    demands = [_demand(1, "PE", 20, 1), _demand(2, "PE", 20, 1)]
    group = {
        "key": "swim", "subject_code": "PE", "section_ids": [1, 2],
        "teacher_id": 20, "required_weekly_periods": 1,
        "demand_ids": [item["demand_id"] for item in demands],
    }
    split = [
        {"section_id": 1, "subject_code": "PE", "teacher_id": 20,
         "day_key": "monday", "period_index": 1, "is_locked": False},
        {"section_id": 2, "subject_code": "PE", "teacher_id": 20,
         "day_key": "tuesday", "period_index": 1, "is_locked": False},
    ]
    result = TimetableSolutionValidator().validate(
        problem=_problem(demands, groups=[group]), placements=split,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "grouped_activity_incomplete" in {item["code"] for item in result["errors"]}


def test_quality_settings_normalize_safely_and_migration_is_registered():
    rules = normalize_timetable_quality_rules({
        "core_subject_codes": {"english": "eng,ELA"},
        "swimming_groups": [{
            "subject_code": "pe", "section_ids": [2, 1],
            "teacher_id": "invalid", "resource_capacity": "invalid",
        }],
        "regeneration_diversity_percent": "30",
    })
    assert rules["core_subject_codes"]["english"] == ["ELA", "ENG"]
    assert rules["swimming_groups"][0]["teacher_id"] is None
    assert rules["swimming_groups"][0]["resource_capacity"] == 1
    assert rules["regeneration_diversity_percent"] == 30
    assert _minimum_difference(240, 25) == 60
    assert any(
        item.migration_id == "20260828_002_smart_timetable_academic_quality_rules"
        for item in db_migrations.MIGRATIONS
    )
