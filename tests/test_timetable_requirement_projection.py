from __future__ import annotations

import json

import pytest

import models
from timetable_problem_builder import TimetableProblemBuilder
from timetable_requirement_projection import (
    RequirementProjectionScopeError,
    project_timetable_lesson_requirements,
)
from timetable_snapshot_service import build_current_snapshot_data
from timetable_solution_validator import TimetableSolutionValidator
from test_timetable_versioning import db  # noqa: F401 - shared isolated database


def _project(db):
    return project_timetable_lesson_requirements(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )


def test_projection_is_deterministic_and_fallback_provenance_is_explicit(db):
    first = _project(db)
    second = _project(db)

    assert first == second
    assert [(item.planning_section_id, item.subject_code) for item in first] == [
        (2000, "MAT"), (2001, "MAT")
    ]
    assert {item.demand_authority for item in first} == {"legacy_fallback"}
    assert all(item.demand_source_id == 3000 for item in first)
    assert all(item.requirement_id.startswith("requirement:") for item in first)
    assert len({item.requirement_id for item in first}) == 2


def test_explicit_authority_overrides_fallback_and_source_change_is_detectable(db):
    fallback = next(item for item in _project(db) if item.planning_section_id == 2000)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2000,
        subject_code="MAT", weekly_periods=2, is_active=True,
    )
    db.add(demand)
    db.flush()

    explicit = next(item for item in _project(db) if item.planning_section_id == 2000)
    assert explicit.required_weekly_periods == 2
    assert explicit.demand_authority == "explicit"
    assert explicit.demand_source_id == demand.id
    assert explicit.requirement_id != fallback.requirement_id

    stable_identity = explicit.requirement_id
    old_fingerprint = explicit.source_fingerprint
    demand.weekly_periods = 3
    db.flush()
    changed = next(item for item in _project(db) if item.planning_section_id == 2000)
    assert changed.requirement_id == stable_identity
    assert changed.source_fingerprint != old_fingerprint


@pytest.mark.parametrize("is_active,weekly_periods", [(True, 0), (False, 0)])
def test_explicit_zero_or_retired_demand_never_reactivates_fallback(
    db, is_active, weekly_periods
):
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2000,
        subject_code="MAT", weekly_periods=weekly_periods, is_active=is_active,
    ))
    db.flush()

    requirement = next(item for item in _project(db) if item.planning_section_id == 2000)
    assert requirement.demand_authority == "explicit"
    assert requirement.required_weekly_periods == 0
    assert requirement.is_schedulable is False

    snapshot = json.loads(build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    ).canonical_json)
    assert not any(
        item["section_id"] == 2000 and item["subject_code"] == "MAT"
        for item in snapshot["planning"]["demands"]
    )


@pytest.mark.parametrize(
    "school_group_id,branch_id,academic_year_id",
    [(2, 10, 100), (1, 20, 100), (1, 10, 200)],
)
def test_projection_fails_closed_across_tenant_branch_and_year(
    db, school_group_id, branch_id, academic_year_id
):
    with pytest.raises(RequirementProjectionScopeError):
        project_timetable_lesson_requirements(
            db,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )


def test_projection_does_not_resolve_foreign_teacher_authority(db):
    foreign_teacher = models.Teacher(
        id=9000, teacher_id="FOREIGN", first_name="Foreign", last_name="Teacher",
        branch_id=20, academic_year_id=200,
    )
    db.add(foreign_teacher)
    db.flush()
    db.add(models.TeacherSectionAssignment(
        teacher_id=9000, planning_section_id=2001, subject_code="MAT"
    ))
    db.flush()

    requirement = next(item for item in _project(db) if item.planning_section_id == 2001)
    assert requirement.assigned_teacher_id is None


def test_snapshot_problem_and_validator_preserve_requirement_contract(db):
    db.add(models.TeacherSectionAssignment(
        teacher_id=1001, planning_section_id=2001, subject_code="MAT"
    ))
    db.flush()
    snapshot = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    payload = json.loads(snapshot.canonical_json)
    assert payload["schema_version"] == 5
    assert all(item["requirement_id"] for item in payload["planning"]["demands"])
    assert all(
        item["requirement_source_fingerprint"]
        for item in payload["planning"]["demands"]
    )

    problem = TimetableProblemBuilder().build(snapshot.canonical_json)
    assert all(item["demand_id"] == item["requirement_id"] for item in problem["demands"])
    validation = TimetableSolutionValidator().validate(
        problem=problem,
        placements=[],
        expected_fingerprint="same",
        current_fingerprint="same",
        expected_scope=problem["scope"],
        current_scope=problem["scope"],
    )
    assert "requirement_provenance_missing" not in {
        item["code"] for item in validation["errors"]
    }
