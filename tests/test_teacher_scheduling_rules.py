import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, text

import db_migrations
import models
from permission_registry import ALL_PERMISSION_KEYS, get_default_permissions_for_role
from teacher_scheduling_rules import (
    TeacherSchedulingRuleError, canonical_rules, list_rules, save_rule, ui_context,
    validate_draft_entries, validate_manual_placement,
)
from timetable_problem_builder import TimetableProblemBuilder, TimetableProblemError
from timetable_readiness_service import TimetableReadinessService
from timetable_publication_service import (
    TimetableDraftValidationService, TimetablePublicationService,
)
from timetable_snapshot_service import build_current_snapshot_data
from timetable_generation_worker import _problem_error_status
from timetable_solution_validator import TimetableSolutionValidator
from timetable_version_service import (
    TimetableVersionError, create_manual_draft, mutate_draft_placement,
)
from test_timetable_versioning import db  # noqa: F401


def _solve(problem):
    pytest.importorskip("ortools")
    from timetable_cp_sat_solver import solve_timetable
    return solve_timetable(problem, timeout_seconds=10, seed=13, search_workers=1)


def _demand(section, code, teacher, periods):
    return {
        "demand_id": f"section:{section}|subject:{code}|teacher:{teacher}",
        "section_id": section, "subject_code": code, "teacher_id": teacher,
        "required_weekly_periods": periods,
    }


def _problem(rule_type=None, *, target_section=None):
    demands = [_demand(1, "MAT", 10, 1), _demand(2, "SCI", 10, 1)]
    rules = []
    if rule_type:
        eligible = [demands[0]["demand_id"]] if target_section else [item["demand_id"] for item in demands]
        rules.append({
            "id": 1, "teacher_id": 10, "rule_type": rule_type,
            "strictness": "hard" if rule_type in {"schedule_within", "must_teach", "unavailable"} else "soft",
            "target_scope": "selected_sections" if target_section else "any_assigned",
            "eligible_demand_ids": eligible,
            "resolved_slots": [{"day_key": "monday", "period_index": 1}],
        })
    return {
        "schema_version": 4,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "working_days": ["monday"],
        "slots": [
            {"slot_id": "monday:1", "day_key": "monday", "period_index": 1},
            {"slot_id": "monday:2", "day_key": "monday", "period_index": 2},
            {"slot_id": "monday:3", "day_key": "monday", "period_index": 3},
        ],
        "sections": [{"id": 1}, {"id": 2}], "demands": demands,
        "locks": [], "request_mode": "generate", "source_arrangement": [],
        "minimum_difference": 0, "quality_rules": {}, "grouped_activities": [],
        "teacher_scheduling_rules": rules,
    }


def test_solver_enforces_must_teach_any_assigned_class_and_validator_parity():
    problem = _problem("must_teach")
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert any(item["teacher_id"] == 10 and item["period_index"] == 1 for item in result["placements"])
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]
    invalid = [dict(item, period_index=3) if item["period_index"] == 1 else item for item in result["placements"]]
    validation = TimetableSolutionValidator().validate(
        problem=problem, placements=invalid,
        expected_fingerprint="same", current_fingerprint="same",
    )
    assert "teacher_must_teach_missing" in {item["code"] for item in validation["errors"]}


def test_solver_enforces_selected_section_and_unavailable():
    section_problem = _problem("must_teach", target_section=1)
    section_result = _solve(section_problem)
    assert any(item["section_id"] == 1 and item["period_index"] == 1 for item in section_result["placements"])
    unavailable_problem = _problem("unavailable")
    unavailable_result = _solve(unavailable_problem)
    assert all(item["period_index"] != 1 for item in unavailable_result["placements"])


def test_schedule_within_places_existing_workload_without_creating_demand_and_validator_matches():
    days = ["sunday", "monday", "tuesday", "wednesday", "thursday"]
    problem = _problem("schedule_within")
    problem["working_days"] = days
    problem["slots"] = [
        {"slot_id": f"{day}:{period}", "day_key": day, "period_index": period}
        for day in days for period in range(1, 9)
    ]
    problem["demands"] = [_demand(1, "MAT", 10, 18)]
    problem["teacher_scheduling_rules"][0]["eligible_demand_ids"] = [problem["demands"][0]["demand_id"]]
    problem["teacher_scheduling_rules"][0]["resolved_slots"] = [
        {"day_key": day, "period_index": period}
        for day in days for period in range(4, 9)
    ]
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(result["placements"]) == 18
    assert {item["period_index"] for item in result["placements"]} <= {4, 5, 6, 7, 8}
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]
    invalid = [dict(result["placements"][0], period_index=1), *result["placements"][1:]]
    errors = TimetableSolutionValidator().validate(
        problem=problem, placements=invalid,
        expected_fingerprint="same", current_fingerprint="same",
    )["errors"]
    assert "teacher_schedule_window_violated" in {item["code"] for item in errors}


def test_schedule_within_selected_section_does_not_restrict_other_sections():
    problem = _problem("schedule_within", target_section=1)
    problem["teacher_scheduling_rules"][0]["resolved_slots"] = [
        {"day_key": "monday", "period_index": 2}
    ]
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert next(item for item in result["placements"] if item["section_id"] == 1)["period_index"] == 2


def test_multiple_schedule_windows_union_for_same_demand_and_validator_parity():
    problem = _problem()
    problem["demands"] = [_demand(1, "MAT", 10, 2)]
    problem["teacher_scheduling_rules"] = [
        {
            "id": 1, "teacher_id": 10, "rule_type": "schedule_within",
            "strictness": "hard", "target_scope": "any_assigned",
            "eligible_demand_ids": [problem["demands"][0]["demand_id"]],
            "resolved_slots": [{"day_key": "monday", "period_index": 1}],
        },
        {
            "id": 2, "teacher_id": 10, "rule_type": "schedule_within",
            "strictness": "hard", "target_scope": "any_assigned",
            "eligible_demand_ids": [problem["demands"][0]["demand_id"]],
            "resolved_slots": [{"day_key": "monday", "period_index": 2}],
        },
    ]
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert {item["period_index"] for item in result["placements"]} == {1, 2}
    assert TimetableSolutionValidator().validate(
        problem=problem, placements=result["placements"],
        expected_fingerprint="same", current_fingerprint="same",
    )["valid"]


def test_must_teach_and_schedule_window_union_are_compatible():
    problem = _problem()
    problem["demands"] = [_demand(1, "MAT", 10, 1)]
    demand_id = problem["demands"][0]["demand_id"]
    problem["teacher_scheduling_rules"] = [
        {
            "id": 1, "teacher_id": 10, "rule_type": "schedule_within",
            "strictness": "hard", "target_scope": "any_assigned",
            "eligible_demand_ids": [demand_id],
            "resolved_slots": [{"day_key": "monday", "period_index": 1}],
        },
        {
            "id": 2, "teacher_id": 10, "rule_type": "must_teach",
            "strictness": "hard", "target_scope": "any_assigned",
            "eligible_demand_ids": [demand_id],
            "resolved_slots": [{"day_key": "monday", "period_index": 1}],
        },
    ]
    assert _solve(problem)["outcome"] == "feasible"


def test_grouped_activity_schedule_windows_union_without_double_counting_teacher():
    problem = _problem()
    problem["demands"] = [_demand(1, "SWI", 10, 1), _demand(2, "SWI", 10, 1)]
    demand_ids = [item["demand_id"] for item in problem["demands"]]
    problem["grouped_activities"] = [{
        "key": "swim", "demand_ids": demand_ids, "section_ids": [1, 2],
        "subject_code": "SWI", "teacher_id": 10, "required_weekly_periods": 1,
        "resource_key": "pool", "resource_capacity": 1,
    }]
    problem["teacher_scheduling_rules"] = [
        {
            "id": index, "teacher_id": 10, "rule_type": "schedule_within",
            "strictness": "hard", "target_scope": "selected_sections",
            "eligible_demand_ids": [demand_id],
            "resolved_slots": [{"day_key": "monday", "period_index": index}],
        }
        for index, demand_id in enumerate(demand_ids, 1)
    ]
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert len(result["placements"]) == 2
    assert len({item["period_index"] for item in result["placements"]}) == 1


def test_must_teach_selected_section_rejects_wrong_section_in_validator():
    problem = _problem("must_teach", target_section=1)
    placements = [
        {"section_id": 2, "subject_code": "SCI", "teacher_id": 10,
         "day_key": "monday", "period_index": 1}
    ]
    errors = TimetableSolutionValidator().validate(
        problem=problem, placements=placements,
        expected_fingerprint="same", current_fingerprint="same",
    )["errors"]
    assert "teacher_must_teach_missing" in {item["code"] for item in errors}


def test_hard_teacher_rule_conflicting_with_subject_distribution_is_infeasible():
    problem = _problem("must_teach", target_section=1)
    problem["working_days"] = ["monday", "tuesday"]
    problem["slots"] = [
        {"slot_id": f"{day}:{period}", "day_key": day, "period_index": period,
         "next_period_physically_adjacent": period == 1}
        for day in problem["working_days"] for period in (1, 2)
    ]
    problem["demands"] = [dict(
        problem["demands"][0], required_weekly_periods=2,
        distribution_rule={
            "block_length": 2, "block_count": 1, "single_count": 0,
            "min_teaching_days": None, "max_periods_per_day": None,
            "require_daily_coverage": "never", "spread_distinct_days": False,
            "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard",
        },
    )]
    problem["teacher_scheduling_rules"][0]["eligible_demand_ids"] = [problem["demands"][0]["demand_id"]]
    problem["teacher_scheduling_rules"][0]["resolved_slots"] = [
        {"day_key": "monday", "period_index": 1},
        {"day_key": "tuesday", "period_index": 1},
    ]
    assert _solve(problem)["outcome"] == "infeasible"


@pytest.mark.parametrize("rule_type,expected_period", [
    ("prefer_teaching", 1), ("prefer_free", 2),
])
def test_soft_preferences_influence_optimization(rule_type, expected_period):
    problem = _problem(rule_type)
    problem["demands"] = problem["demands"][:1]
    problem["teacher_scheduling_rules"][0]["eligible_demand_ids"] = [problem["demands"][0]["demand_id"]]
    result = _solve(problem)
    assert result["outcome"] == "feasible"
    assert result["placements"][0]["period_index"] == expected_period


def test_service_scope_first_last_snapshot_fingerprint_and_draft_stale(db):
    first = build_current_snapshot_data(db, school_group_id=1, branch_id=10, academic_year_id=100)
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        actor_user_id="U1",
    )
    draft.approved_at = datetime.utcnow()
    draft.approved_by_user_id = "U1"
    db.commit()
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="must_teach", all_working_days=True, days=[],
        period_selector="first", periods=[], target_scope="selected_sections",
        grades=[], section_ids=[2000], actor_user_id="U1",
    )
    second = build_current_snapshot_data(db, school_group_id=1, branch_id=10, academic_year_id=100)
    payload = json.loads(second.canonical_json)
    assert second.constraint_fingerprint != first.constraint_fingerprint
    assert payload["schema_version"] == 5
    assert payload["constraints"]["teacher_scheduling_rules"][0]["resolved_slots"] == [
        {"day_key": "monday", "period_index": 1},
        {"day_key": "tuesday", "period_index": 1},
    ]
    db.refresh(draft)
    assert draft.is_stale is True
    assert draft.approved_by_user_id is None
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="prefer_free", all_working_days=False,
        days=["monday"], period_selector="last", periods=[],
        target_scope="any_assigned", grades=[], section_ids=[], actor_user_id="U1",
    )
    last = next(rule for rule in canonical_rules(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        working_days=["monday"], slots=[
            {"day_key": "monday", "period_index": 1},
            {"day_key": "monday", "period_index": 4},
        ],
    ) if rule["rule_type"] == "prefer_free")
    assert last["resolved_slots"][0]["period_index"] == 4


def test_schedule_within_storage_is_explicit_and_existing_must_teach_is_unchanged(db):
    saved = save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="schedule_within", all_working_days=True,
        days=[], period_selector="period", periods=[2, 3, 4],
        target_scope="any_assigned", grades=[], section_ids=[], actor_user_id="U1",
    )
    assert saved.rule_type == "must_teach"
    assert saved.restrict_to_window is True
    assert list_rules(db, school_group_id=1, branch_id=10, academic_year_id=100)[0]["rule_type"] == "schedule_within"
    existing = models.TeacherSchedulingRule(
        school_group_id=1, branch_id=10, academic_year_id=100, teacher_id=1001,
        rule_type="must_teach", restrict_to_window=False, target_scope="any_assigned",
        strictness="hard", is_active=True,
    )
    db.add(existing); db.flush()
    db.add(models.TeacherSchedulingRuleSlot(
        rule_id=existing.id, day_key="monday", period_selector="period", period_index=1,
    )); db.commit()
    rules = list_rules(db, school_group_id=1, branch_id=10, academic_year_id=100)
    assert next(rule for rule in rules if rule["id"] == existing.id)["rule_type"] == "must_teach"


def test_service_rejects_cross_tenant_teacher_and_hard_conflict(db):
    db.add(models.Teacher(
        id=9000, teacher_id="OTHER", first_name="Other", last_name="Teacher",
        branch_id=20, academic_year_id=200,
    )); db.commit()
    with pytest.raises(TeacherSchedulingRuleError) as exc:
        save_rule(
            db, school_group_id=1, branch_id=10, academic_year_id=100,
            teacher_id=9000, rule_type="must_teach", all_working_days=True, days=[],
            period_selector="period", periods=[1], target_scope="any_assigned",
            grades=[], section_ids=[], actor_user_id="U1",
        )
    assert exc.value.code == "teacher_scope_mismatch"
    db.rollback()
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="must_teach", all_working_days=False, days=["monday"],
        period_selector="period", periods=[1], target_scope="any_assigned",
        grades=[], section_ids=[], actor_user_id="U1",
    )
    with pytest.raises(TeacherSchedulingRuleError) as exc:
        save_rule(
            db, school_group_id=1, branch_id=10, academic_year_id=100,
            teacher_id=1000, rule_type="unavailable", all_working_days=False, days=["monday"],
            period_selector="period", periods=[1], target_scope="any_assigned",
            grades=[], section_ids=[], actor_user_id="U1",
        )
    assert exc.value.code == "hard_rule_conflict"
    db.rollback()


def test_problem_builder_rejects_workload_and_lock_conflicts():
    snapshot = {
        "schema_version": 4,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "planning": {
            "sections": [{"id": 1, "grade_level": "5", "class_status": "Current"}],
            "valid_teacher_ids": [10],
            "demands": [{"section_id": 1, "subject_id": 1, "subject_code": "MAT", "assigned_teacher_id": 10, "required_weekly_periods": 1}],
        },
        "period_configuration": {
            "settings": {"quality_rules": {}},
            "canonical_slot_projection": {"working_day_keys": ["sunday"], "timelines": [{"day_key": "sunday", "items": [
                {"type": "teaching", "schedulable": True, "day_key": "sunday", "period_index": 1}
            ]}]},
        },
        "constraints": {"teacher_scheduling_rules": [{
            "id": 1, "teacher_id": 10, "rule_type": "must_teach", "strictness": "hard",
            "target_scope": "any_assigned", "targets": [],
            "resolved_slots": [{"day_key": "sunday", "period_index": 1}, {"day_key": "sunday", "period_index": 2}],
        }]}, "locks": [],
    }
    with pytest.raises(TimetableProblemError) as exc:
        TimetableProblemBuilder().build(json.dumps(snapshot))
    assert exc.value.code == "teacher_rule_slot_invalid"
    snapshot["constraints"]["teacher_scheduling_rules"][0]["rule_type"] = "unavailable"
    snapshot["constraints"]["teacher_scheduling_rules"][0]["resolved_slots"] = [{"day_key": "sunday", "period_index": 1}]
    snapshot["locks"] = [{"section_id": 1, "subject_code": "MAT", "teacher_id": 10, "day_key": "sunday", "period_index": 1}]
    with pytest.raises(TimetableProblemError) as exc:
        TimetableProblemBuilder().build(json.dumps(snapshot))
    assert exc.value.code == "teacher_rule_availability_infeasible"


def test_problem_builder_blocks_insufficient_schedule_window_capacity():
    snapshot = {
        "schema_version": 4,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "planning": {
            "sections": [{"id": 1, "grade_level": "5", "class_status": "Current"}],
            "valid_teacher_ids": [10],
            "demands": [{"section_id": 1, "subject_id": 1, "subject_code": "MAT", "assigned_teacher_id": 10, "required_weekly_periods": 2}],
        },
        "period_configuration": {
            "settings": {"quality_rules": {}},
            "canonical_slot_projection": {"working_day_keys": ["sunday"], "timelines": [{"day_key": "sunday", "items": [
                {"type": "teaching", "schedulable": True, "day_key": "sunday", "period_index": 1},
                {"type": "teaching", "schedulable": True, "day_key": "sunday", "period_index": 2},
            ]}]},
        },
        "constraints": {"teacher_scheduling_rules": [{
            "id": 1, "teacher_id": 10, "rule_type": "schedule_within", "strictness": "hard",
            "target_scope": "any_assigned", "targets": [],
            "resolved_slots": [{"day_key": "sunday", "period_index": 2}],
        }]}, "locks": [],
    }
    with pytest.raises(TimetableProblemError) as exc:
        TimetableProblemBuilder().build(json.dumps(snapshot))
    assert exc.value.code == "teacher_rule_window_capacity_insufficient"


def test_problem_builder_unions_multiple_schedule_windows_before_solver():
    snapshot = _distribution_window_snapshot(
        periods=2,
        allowed_slots=[("sunday", 1), ("monday", 2)],
        distribution_rule={
            "block_length": 1, "block_count": 0, "single_count": 2,
            "min_teaching_days": None, "max_periods_per_day": None,
            "require_daily_coverage": "never", "spread_distinct_days": False,
            "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard",
        },
    )
    snapshot["constraints"]["teacher_scheduling_rules"].append({
        **snapshot["constraints"]["teacher_scheduling_rules"][0],
        "id": 2,
        "resolved_slots": [
            {"day_key": "monday", "period_index": 2},
            {"day_key": "tuesday", "period_index": 3},
        ],
    })
    problem = TimetableProblemBuilder().build(json.dumps(snapshot))
    demand_id = problem["demands"][0]["demand_id"]
    assert problem["teacher_schedule_windows_by_demand"][demand_id] == [
        {"day_key": "monday", "period_index": 2},
        {"day_key": "sunday", "period_index": 1},
        {"day_key": "tuesday", "period_index": 3},
    ]
    assert _solve(problem)["outcome"] == "feasible"


def _distribution_window_snapshot(*, periods, allowed_slots, distribution_rule):
    days = ["sunday", "monday", "tuesday"]
    timelines = []
    for day in days:
        timelines.append({"day_key": day, "items": [
            {
                "type": "teaching", "schedulable": True, "day_key": day,
                "period_index": period,
                "next_period_physically_adjacent": period in {1, 2},
            }
            for period in (1, 2, 3)
        ]})
    return {
        "schema_version": 4,
        "scope": {"school_group_id": 1, "branch_id": 10, "academic_year_id": 100},
        "planning": {
            "sections": [{"id": 1, "grade": "5", "section_name": "A", "class_status": "Current"}],
            "valid_teacher_ids": [10],
            "demands": [{
                "section_id": 1, "subject_id": 1, "subject_code": "MAT",
                "assigned_teacher_id": 10, "required_weekly_periods": periods,
                "distribution_rule": distribution_rule,
            }],
        },
        "period_configuration": {
            "settings": {"quality_rules": {}},
            "canonical_slot_projection": {
                "working_day_keys": days, "timelines": timelines,
            },
        },
        "constraints": {"teacher_scheduling_rules": [{
            "id": 1, "teacher_id": 10, "rule_type": "schedule_within",
            "strictness": "hard", "target_scope": "any_assigned", "targets": [],
            "resolved_slots": [
                {"day_key": day, "period_index": period}
                for day, period in allowed_slots
            ],
        }]},
        "locks": [],
    }


@pytest.mark.parametrize("periods,allowed_slots,rule,expected_code", [
    (
        3, [("sunday", 1), ("sunday", 2), ("sunday", 3)],
        {"block_length": 1, "block_count": 0, "single_count": 3,
         "min_teaching_days": None, "max_periods_per_day": None,
         "require_daily_coverage": "always", "spread_distinct_days": False,
         "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard"},
        "teacher_rule_daily_coverage_conflict",
    ),
    (
        3, [("sunday", 1), ("sunday", 2), ("monday", 1)],
        {"block_length": 1, "block_count": 0, "single_count": 3,
         "min_teaching_days": None, "max_periods_per_day": 1,
         "require_daily_coverage": "never", "spread_distinct_days": False,
         "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard"},
        "teacher_rule_max_per_day_conflict",
    ),
    (
        2, [("sunday", 1), ("monday", 1)],
        {"block_length": 2, "block_count": 1, "single_count": 0,
         "min_teaching_days": None, "max_periods_per_day": None,
         "require_daily_coverage": "never", "spread_distinct_days": False,
         "avoid_consecutive": False, "min_day_gap": None, "strictness": "hard"},
        "teacher_rule_double_block_conflict",
    ),
])
def test_deterministic_teacher_window_distribution_conflicts_are_explained(
    periods, allowed_slots, rule, expected_code,
):
    snapshot = _distribution_window_snapshot(
        periods=periods, allowed_slots=allowed_slots, distribution_rule=rule,
    )
    with pytest.raises(TimetableProblemError) as exc:
        TimetableProblemBuilder().build(json.dumps(snapshot))
    assert exc.value.code == expected_code
    assert exc.value.details["teacher_id"] == 10
    assert exc.value.details["section_id"] == 1
    assert exc.value.details["subject_code"] == "MAT"
    assert _problem_error_status(expected_code) == "infeasible"


def test_readiness_reports_schedule_window_capacity_blocker(db):
    db.add(models.TeacherSectionAssignment(
        teacher_id=1001, planning_section_id=2001, subject_code="MAT",
    ))
    db.flush()
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="schedule_within", all_working_days=True,
        days=[], period_selector="period", periods=[4], target_scope="any_assigned",
        grades=[], section_ids=[], actor_user_id="U1",
    )
    result = TimetableReadinessService(db).evaluate(1, 10, 100)
    assert "teacher_rule_window_capacity_insufficient" in {
        item["code"] for item in result["blockers"]
    }


def test_no_rules_backward_compatibility_and_permission_ui_contract():
    problem = _problem()
    assert _solve(problem)["outcome"] == "feasible"
    assert "timetable.manage_teacher_rules" in ALL_PERMISSION_KEYS
    assert "timetable.manage_teacher_rules" in get_default_permissions_for_role("Administrator")
    template = open("templates/system_configuration_timetable.html", encoding="utf-8").read()
    assert "Teacher Scheduling Rules" in template
    assert "timetable.manage_teacher_rules" in template
    assert "Schedule within these periods" in template
    assert 'name="select_all_sections"' in template
    assert 'name="grades"' not in template
    assert "teacher-rule-period-selector" not in template
    assert "teacher-rule-target-scope" not in template
    assert ">First period<" not in template and ">Last period<" not in template
    assert "function setAllSections(selected)" in template
    assert "sectionChecks.forEach" in template
    assert "sectionChecks.every" in template
    assert "setAllSections(true)" in template
    assert "updateSelectAll()" in template


def test_ui_context_uses_exact_section_summaries_and_current_new_sections(db):
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="must_teach", all_working_days=False,
        days=["monday"], period_selector="period", periods=[1],
        target_scope="selected_sections", grades=[], section_ids=[2000, 2001],
        actor_user_id="U1",
    )
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1001, rule_type="schedule_within", all_working_days=False,
        days=["tuesday"], period_selector="period", periods=[2, 3],
        target_scope="any_assigned", grades=[], section_ids=[], actor_user_id="U1",
    )
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1001, rule_type="unavailable", all_working_days=False,
        days=["monday"], period_selector="period", periods=[4],
        target_scope="any_assigned", grades=[], section_ids=[], actor_user_id="U1",
    )
    context = ui_context(db, school_group_id=1, branch_id=10, academic_year_id=100)
    selected = next(item for item in context["teacher_scheduling_rules"] if item["rule_type"] == "must_teach")
    window = next(item for item in context["teacher_scheduling_rules"] if item["rule_type"] == "schedule_within")
    unavailable = next(item for item in context["teacher_scheduling_rules"] if item["rule_type"] == "unavailable")
    assert selected["target_labels"] == ["Grade 1-A", "Grade 1-B"]
    assert selected["edit_payload"]["targets"] == [
        {"target_type": "section", "grade_level": None, "planning_section_id": 2000},
        {"target_type": "section", "grade_level": None, "planning_section_id": 2001},
    ]
    assert window["scope_label"] == "All assigned sections"
    assert unavailable["scope_label"] == "All classes"
    assert context["teacher_rule_sections"] == [
        {"id": 2000, "label": "Grade 1-A"},
        {"id": 2001, "label": "Grade 1-B"},
    ]


def test_manual_edit_rejects_unavailable_and_outside_selected_section_window(db):
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="unavailable", all_working_days=False,
        days=["monday"], period_selector="period", periods=[1],
        target_scope="any_assigned", grades=[], section_ids=[], actor_user_id="U1",
    )
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="schedule_within", all_working_days=False,
        days=["monday"], period_selector="period", periods=[2],
        target_scope="selected_sections", grades=[], section_ids=[2000], actor_user_id="U1",
    )
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, actor_user_id="U1",
    )
    db.commit()
    with pytest.raises(TimetableVersionError) as exc:
        mutate_draft_placement(
            db, version=draft, planning_section_id=2000, day_key="monday",
            period_index=1, subject_code="MAT", teacher_id=1000,
        )
    assert exc.value.code == "teacher_unavailable_violated"
    db.rollback()
    draft = db.query(models.TimetableVersion).filter_by(id=draft.id).one()
    with pytest.raises(TimetableVersionError) as exc:
        mutate_draft_placement(
            db, version=draft, planning_section_id=2000, day_key="tuesday",
            period_index=2, subject_code="MAT", teacher_id=1000,
        )
    assert exc.value.code == "teacher_schedule_window_violated"


def test_manual_and_complete_validation_union_multiple_schedule_windows(db):
    for day, period in (("monday", 1), ("tuesday", 2)):
        save_rule(
            db, school_group_id=1, branch_id=10, academic_year_id=100,
            teacher_id=1000, rule_type="schedule_within", all_working_days=False,
            days=[day], period_selector="period", periods=[period],
            target_scope="selected_sections", grades=[], section_ids=[2000],
            actor_user_id="U1",
        )
    for day, period in (("monday", 1), ("tuesday", 2)):
        assert validate_manual_placement(
            db, school_group_id=1, branch_id=10, academic_year_id=100,
            teacher_id=1000, planning_section_id=2000, grade_level="1",
            day_key=day, period_index=period,
        ) is None
    entries = [
        {"teacher_id": 1000, "section_id": 2000, "day_key": "monday", "period_index": 1},
        {"teacher_id": 1000, "section_id": 2000, "day_key": "tuesday", "period_index": 2},
    ]
    assert validate_draft_entries(
        db, school_group_id=1, branch_id=10, academic_year_id=100, entries=entries,
    ) == []


def test_complete_draft_rule_validation_is_hard_only_and_checks_selected_section(db):
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="must_teach", all_working_days=False,
        days=["monday"], period_selector="period", periods=[1],
        target_scope="selected_sections", grades=[], section_ids=[2000], actor_user_id="U1",
    )
    soft = models.TeacherSchedulingRule(
        school_group_id=1, branch_id=10, academic_year_id=100, teacher_id=1000,
        rule_type="prefer_free", restrict_to_window=False, target_scope="any_assigned",
        strictness="soft", is_active=True,
    )
    db.add(soft); db.flush()
    db.add(models.TeacherSchedulingRuleSlot(
        rule_id=soft.id, day_key="monday", period_selector="period", period_index=2,
    )); db.commit()
    wrong_section = [{
        "teacher_id": 1000, "section_id": 2001,
        "day_key": "monday", "period_index": 1,
    }]
    issues = validate_draft_entries(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        entries=wrong_section,
    )
    assert {item["code"] for item in issues} == {"teacher_must_teach_missing"}
    matching = [{
        "teacher_id": 1000, "section_id": 2000,
        "day_key": "monday", "period_index": 1,
    }]
    assert validate_draft_entries(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        entries=matching,
    ) == []


def test_hard_rule_violation_blocks_draft_approval_and_publication(db):
    save_rule(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="unavailable", all_working_days=False,
        days=["monday"], period_selector="period", periods=[1],
        target_scope="any_assigned", grades=[], section_ids=[], actor_user_id="U1",
    )
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, actor_user_id="U1",
    )
    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    db.flush()
    validation = TimetableDraftValidationService(db).validate(
        version=draft, transition=True, actor_user_id="U1",
    )
    assert validation["valid"] is False
    assert "teacher_unavailable_violated" in {
        item["code"] for item in validation["blockers"]
    }
    assert draft.lifecycle_status == "draft"
    assert draft.approved_at is None

    draft.lifecycle_status = "publication_ready"
    draft.approved_at = datetime.utcnow()
    draft.approved_by_user_id = "U1"
    db.flush()
    with pytest.raises(TimetableVersionError) as exc:
        TimetablePublicationService(db).publish(
            version_id=draft.id, school_group_id=1, branch_id=10,
            academic_year_id=100, actor_user_id="U1",
            expected_edit_revision=draft.edit_revision, expected_pointer_revision=0,
        )
    assert exc.value.code == "publication_validation_failed"
    assert "unavailable" in str(exc.value).lower()


def test_migration_order_and_idempotency_without_local_database():
    engine = create_engine("sqlite:///:memory:")
    deferred = {"teacher_scheduling_rules", "teacher_scheduling_rule_slots", "teacher_scheduling_rule_targets"}
    models.Base.metadata.create_all(engine, tables=[
        table for table in models.Base.metadata.tables.values() if table.name not in deferred
    ])
    with engine.begin() as connection:
        db_migrations._teacher_scheduling_rules_foundation(engine, connection)
        db_migrations._teacher_scheduling_window_semantics(engine, connection)
    with engine.begin() as connection:
        db_migrations._teacher_scheduling_rules_foundation(engine, connection)
        db_migrations._teacher_scheduling_window_semantics(engine, connection)
    names = set(inspect(engine).get_table_names())
    assert deferred <= names
    assert any(index["name"] == "uq_teachers_id_scope" for index in inspect(engine).get_indexes("teachers"))
    assert "restrict_to_window" in {column["name"] for column in inspect(engine).get_columns("teacher_scheduling_rules")}
    engine.dispose()


def test_window_semantics_migration_adds_column_to_existing_table_idempotently():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE teacher_scheduling_rules (id INTEGER PRIMARY KEY)"
        ))
        db_migrations._teacher_scheduling_window_semantics(engine, connection)
        db_migrations._teacher_scheduling_window_semantics(engine, connection)
    columns = {column["name"] for column in inspect(engine).get_columns("teacher_scheduling_rules")}
    assert "restrict_to_window" in columns
    engine.dispose()
