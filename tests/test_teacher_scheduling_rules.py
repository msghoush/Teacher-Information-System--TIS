import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect

import db_migrations
import models
from permission_registry import ALL_PERMISSION_KEYS, get_default_permissions_for_role
from teacher_scheduling_rules import (
    TeacherSchedulingRuleError, canonical_rules, list_rules, save_rule,
)
from timetable_problem_builder import TimetableProblemBuilder, TimetableProblemError
from timetable_snapshot_service import build_current_snapshot_data
from timetable_solution_validator import TimetableSolutionValidator
from timetable_version_service import create_manual_draft
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
            "strictness": "hard" if rule_type in {"must_teach", "unavailable"} else "soft",
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
    assert payload["schema_version"] == 4
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


def test_no_rules_backward_compatibility_and_permission_ui_contract():
    problem = _problem()
    assert _solve(problem)["outcome"] == "feasible"
    assert "timetable.manage_teacher_rules" in ALL_PERMISSION_KEYS
    assert "timetable.manage_teacher_rules" in get_default_permissions_for_role("Administrator")
    template = open("templates/system_configuration_timetable.html", encoding="utf-8").read()
    assert "Teacher Scheduling Rules" in template
    assert "timetable.manage_teacher_rules" in template


def test_migration_order_and_idempotency_without_local_database():
    engine = create_engine("sqlite:///:memory:")
    deferred = {"teacher_scheduling_rules", "teacher_scheduling_rule_slots", "teacher_scheduling_rule_targets"}
    models.Base.metadata.create_all(engine, tables=[
        table for table in models.Base.metadata.tables.values() if table.name not in deferred
    ])
    with engine.begin() as connection:
        db_migrations._teacher_scheduling_rules_foundation(engine, connection)
    with engine.begin() as connection:
        db_migrations._teacher_scheduling_rules_foundation(engine, connection)
    names = set(inspect(engine).get_table_names())
    assert deferred <= names
    assert any(index["name"] == "uq_teachers_id_scope" for index in inspect(engine).get_indexes("teachers"))
    engine.dispose()
