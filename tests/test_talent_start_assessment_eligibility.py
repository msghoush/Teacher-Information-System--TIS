"""Start Assessment must actually work (Final Production Follow-Up Closure, Part A).

Root cause proven here: the Student Assessments roster is Grade-agnostic
(ADR 0035/0039: every currently placed Student is listed) while Start Assessment
is Grade-aligned (ADR 0039 amendment 2026-09-12: only criteria for the Student's
Grade plus intentionally unscoped criteria may be used). The two used different
predicates, so the roster offered an enabled Start for a Student whose Start was
guaranteed to fail with ``assessment_tool_unavailable``.

The fix has the backend compute one per-row ``can_start`` (+ bounded reason) from
the SAME predicate the start route uses (``_newest_assessable_framework`` and the
duplicate-current-Assessment guard). These tests pin that agreement as a
property over eligible and ineligible fixtures, plus the stale-context, Branch
and authorization boundaries.
"""

from __future__ import annotations

import pytest

import auth
import models
from test_talent_batch1_data_scope import World
from test_talent_start_assessment_flow import make_program, workspace_reads


@pytest.fixture()
def world():
    instance = World(foreign_keys=True)
    yield instance
    instance.close()


def roster(world, cycle_id, query=""):
    response = world.get(f"/api/talent/assessment-cycles/{cycle_id}/eligible-students{query}")
    assert response.status_code == 200, response.text
    return response.json()["members"]


def start(world, cycle_id, student_id, **extra):
    return world.client.post("/api/talent/assessments", json={"cycle_id": cycle_id, "student_id": student_id, **extra})


def assessment_count(world):
    world.db.expire_all()
    return world.db.query(models.TalentStudentAssessment).count()


def test_roster_marks_students_whose_grade_has_no_criteria_as_not_startable(world):
    """Criteria authored for Grade 3 only: Grade 3 can start, Grades 4 and 5 cannot (and say why)."""
    program, cycle = make_program(world, name="Grade Three Only", competency_grade="3")
    world.as_admin()
    members = roster(world, cycle.id)
    assert {m["grade_level"] for m in members} == {"3", "4", "5"}, "the roster stays Grade-agnostic (ADR 0035/0039)"
    for member in members:
        if member["grade_level"] == "3":
            assert member["can_start"] is True
            assert member["start_block_code"] is None and member["start_block_reason"] is None
        else:
            assert member["can_start"] is False
            assert member["start_block_code"] == "assessment_tool_unavailable"
            assert member["start_block_reason"] == "No assessment criteria are configured for this Grade in this Program."


@pytest.mark.parametrize("competency_grade", [None, "3", "9"])
@pytest.mark.parametrize("actor", ["org_all", "org_north", "limited_north"])
def test_roster_can_start_agrees_with_the_start_route_for_every_row(world, competency_grade, actor):
    """Property: can_start is True exactly when Start succeeds; the reason code is the route's code."""
    program, cycle = make_program(world, name=f"Property {competency_grade}", competency_grade=competency_grade)
    if actor == "org_all":
        world.as_admin()
    elif actor == "org_north":
        world.as_admin(world.north)
    else:
        world.branch_limited_user(world.north)
    members = roster(world, cycle.id)
    assert members
    for member in members:
        before = assessment_count(world)
        response = start(world, cycle.id, member["student_id"])
        if member["can_start"]:
            assert response.status_code == 201, (member, response.text)
            assert assessment_count(world) == before + 1
        else:
            assert response.status_code in (400, 409), (member, response.status_code, response.text)
            assert response.json()["code"] == member["start_block_code"]
            assert assessment_count(world) == before, "a rejected Start creates nothing"
    # After every Start the roster reflects it: nothing that started can start again.
    after = {m["student_id"]: m for m in roster(world, cycle.id)}
    for member in members:
        if member["can_start"]:
            assert after[member["student_id"]]["can_start"] is False
            assert after[member["student_id"]]["start_block_code"] == "duplicate_assessment"


def test_existing_in_progress_assessment_is_not_duplicated_and_completed_is_not_restartable(world):
    program, cycle = make_program(world, name="Existing", competency_grade=None)
    world.as_admin()
    member = roster(world, cycle.id)[0]
    created = start(world, cycle.id, member["student_id"])
    assert created.status_code == 201
    first = created.json()
    workspace_reads(world, first)

    again = start(world, cycle.id, member["student_id"])
    assert again.status_code == 409 and again.json()["code"] == "duplicate_assessment"
    world.db.expire_all()
    assert world.db.query(models.TalentStudentAssessment).filter_by(cycle_id=cycle.id, student_id=member["student_id"]).count() == 1

    row = world.db.get(models.TalentStudentAssessment, first["id"])
    row.status = "completed"
    world.db.commit()
    detail = world.client.get(f"/api/talent/assessments/{first['id']}").json()
    assert detail["status"] == "completed" and "reset_for_reassessment" in detail["actions"]
    completed_row = {m["student_id"]: m for m in roster(world, cycle.id)}[member["student_id"]]
    assert completed_row["can_start"] is False and completed_row["start_block_code"] == "duplicate_assessment"
    assert start(world, cycle.id, member["student_id"]).status_code == 409


def test_stale_program_or_year_context_never_starts_in_a_different_context(world):
    program, cycle = make_program(world, name="Stale Ctx", competency_grade=None)
    other_program, other_cycle = make_program(world, name="Other Program", competency_grade=None)
    world.as_admin()
    member = roster(world, cycle.id)[0]
    before = assessment_count(world)

    wrong_program = start(world, cycle.id, member["student_id"], program_id=other_program.id)
    assert wrong_program.status_code == 409 and wrong_program.json()["code"] == "context_mismatch"
    wrong_year = start(world, cycle.id, member["student_id"], academic_year_id=world.year + 999)
    assert wrong_year.status_code == 409 and wrong_year.json()["code"] == "context_mismatch"
    junk = start(world, cycle.id, member["student_id"], program_id="not-a-number")
    assert junk.status_code == 400
    assert assessment_count(world) == before

    # The matching context (string or number typed) is accepted and lands in the Cycle's own Program.
    ok = start(world, cycle.id, member["student_id"], program_id=str(program.id), academic_year_id=world.year)
    assert ok.status_code == 201, ok.text
    assert ok.json()["program_id"] == program.id


def test_unknown_cycle_is_a_bounded_404_and_nothing_is_created(world):
    make_program(world, name="Unknown Cycle", competency_grade=None)
    world.as_admin()
    student_id = roster(world, world.cycle_a)[0]["student_id"]
    before = assessment_count(world)
    response = start(world, 987654, student_id)
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert "Traceback" not in response.text and "sqlalchemy" not in response.text.lower()
    assert assessment_count(world) == before


def test_wrong_branch_and_missing_permission_are_denied(world, monkeypatch):
    program, cycle = make_program(world, name="Denied", competency_grade=None)
    world.as_admin()
    south = next(m for m in roster(world, cycle.id) if m["branch_id"] == world.south)
    north = next(m for m in roster(world, cycle.id) if m["branch_id"] == world.north)
    world.branch_limited_user(world.north)
    limited_roster = roster(world, cycle.id)
    assert south["student_id"] not in {m["student_id"] for m in limited_roster}
    before = assessment_count(world)
    denied = start(world, cycle.id, south["student_id"])
    assert denied.status_code == 403
    assert assessment_count(world) == before

    # Same actor inside their own Branch may start (a Branch filter elsewhere does not change authority).
    assert start(world, cycle.id, north["student_id"]).status_code == 201

    monkeypatch.setattr(auth, "get_allowed_permission_keys", lambda db, user, **kwargs: frozenset({"talent_assessments.view"}))
    other = next(m for m in limited_roster if m["student_id"] != north["student_id"])
    forbidden = start(world, cycle.id, other["student_id"])
    assert forbidden.status_code in (401, 403)
    assert assessment_count(world) == before + 1


@pytest.mark.parametrize("sidebar", ["north", "south", "all"])
def test_org_actor_can_start_any_authorized_branch_student_under_any_page_branch(world, sidebar):
    program, cycle = make_program(world, name=f"Branch {sidebar}", competency_grade=None)
    world.as_admin(None if sidebar == "all" else getattr(world, sidebar))
    members = roster(world, cycle.id)
    assert {m["branch_id"] for m in members} == {world.north, world.south}
    for branch in (world.north, world.south):
        target = next(m for m in members if m["branch_id"] == branch)
        created = start(world, cycle.id, target["student_id"])
        assert created.status_code == 201, created.text
        workspace_reads(world, created.json())
