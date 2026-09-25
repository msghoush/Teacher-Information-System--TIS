"""Start Assessment end to end (production follow-up, Part 1 B).

Not Started Student -> POST /api/talent/assessments {cycle_id, student_id} -> the
requests the Assessment workspace issues after navigation. The backend stays
authoritative; these tests pin the contract the roster button depends on:

* a Program with a complete Grade-applicable rubric: Start succeeds, returns the
  ids the client navigates with (Student, Program, Academic Year, Evaluation
  Cycle), and every workspace read the next page makes succeeds under the SAME
  Student + Program + Evaluation context, for an organization actor and for a
  Branch-limited actor inside their Branch, whatever the sidebar Branch is;
* a Student whose Grade has no saved assessment criteria is rejected with the
  stable, safe code ``assessment_tool_unavailable`` (HTTP 400) and nothing is
  created (root cause of the production banner: the client collapsed every 400
  into one generic "cannot be displayed" message);
* a Branch-limited actor cannot start a Student placed in another Branch.
"""

from __future__ import annotations

from datetime import datetime

import pytest

import models
from talent_assessment_cycle_service import create_cycle
from talent_program_service import (
    activate_framework, add_framework_competency, add_rubric_level, create_competency,
    create_framework_draft, create_program, transition_program, upsert_rubric,
)
from test_talent_batch1_data_scope import World


@pytest.fixture()
def world():
    instance = World(foreign_keys=True)
    yield instance
    instance.close()


def make_program(world, *, name, competency_grade):
    """Program + active Framework with one competency, its rubric and one level."""
    db, group = world.db, world.group_id
    program = create_program(db, school_group_id=group, name=name)
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title=f"{name} Framework")
    lineage = create_competency(db, school_group_id=group, program_id=program.id, code="SF", name="Start Flow")
    member, framework = add_framework_competency(
        db, school_group_id=group, program_id=program.id, framework_id=framework.id,
        competency_id=lineage.id, expected_revision=framework.revision, grade_level=competency_grade)
    _, framework = upsert_rubric(
        db, school_group_id=group, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, framework_competency_id=member.id)
    _, framework = add_rubric_level(
        db, school_group_id=group, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, code="L1", label="Level 1", framework_competency_id=member.id)
    activate_framework(
        db, school_group_id=group, program_id=program.id, framework_id=framework.id,
        expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
        organization_authorized=True)
    cycle = create_cycle(
        db, school_group_id=group, program_id=program.id, academic_year_id=world.year,
        framework_version_id=framework.id, title="Start Flow Evaluation",
        population_effective_at=datetime.utcnow())
    db.commit()
    return program, cycle


def roster(world, cycle_id, query=""):
    response = world.get(f"/api/talent/assessment-cycles/{cycle_id}/eligible-students{query}")
    assert response.status_code == 200, response.text
    return response.json()["members"]


def workspace_reads(world, created):
    """Exactly what static/js/talent-operations.js requests after Start navigates."""
    aid = created["id"]
    base = f"/api/talent/programs/{created['program_id']}/frameworks/{created['framework_version_id']}"
    reads = [
        ("get", f"/api/talent/assessments/{aid}"),
        ("post", f"/api/talent/assessments/{aid}/continue"),
        ("get", f"/api/talent/assessments/{aid}/competency-results"),
        ("get", f"/api/talent/programs/{created['program_id']}"),
        ("get", base),
        ("get", f"{base}/configuration"),
    ]
    for method, path in reads:
        response = getattr(world.client, method)(path)
        assert response.status_code == 200, (method, path, response.status_code, response.text[:200])


@pytest.mark.parametrize("actor", ["org_north_sidebar", "org_south_sidebar", "org_all", "limited_north"])
def test_start_then_open_workspace_resolves_the_same_context(world, actor):
    program, cycle = make_program(world, name="Start Flow", competency_grade=None)
    if actor == "org_north_sidebar":
        world.as_admin(world.north)
    elif actor == "org_south_sidebar":
        world.as_admin(world.south)
    elif actor == "org_all":
        world.as_admin()
    else:
        world.branch_limited_user(world.north)
    members = roster(world, cycle.id)
    assert members, "the roster lists the current Students of the actor's scope"
    target = members[0]
    assert not world.db.query(models.TalentStudentAssessment).filter_by(cycle_id=cycle.id, student_id=target["student_id"]).count()

    created = world.client.post("/api/talent/assessments", json={"cycle_id": cycle.id, "student_id": target["student_id"]})
    assert created.status_code == 201, created.text
    body = created.json()
    # The ids the client navigates with are all present and belong to the roster row's context.
    assert body["student_id"] == target["student_id"]
    assert body["program_id"] == program.id
    assert body["academic_year_id"] == world.year
    assert (body.get("evaluation_context_cycle_id") or body["cycle_id"]) == cycle.id
    assert body["status"] == "in_progress" and body["is_current"] is True
    workspace_reads(world, body)

    # The started Student is now listed as an in-progress row for the same Program/Evaluation.
    listing = world.get(f"/api/talent/assessments?academic_year_id={world.year}&program_id={program.id}").json()
    match = [row for row in listing if row["id"] == body["id"]]
    assert match and match[0]["student_id"] == target["student_id"] and match[0]["program_id"] == program.id
    assert match[0].get("evaluation_context_cycle_id", match[0]["cycle_id"]) == cycle.id


def test_grade_without_saved_criteria_is_a_stable_safe_400_and_creates_nothing(world):
    """Root cause of the production banner: Grade 3 has no criteria (competency scoped to Grade 9)."""
    program, cycle = make_program(world, name="Other Grade Only", competency_grade="9")
    world.as_admin(world.north)
    target = roster(world, cycle.id)[0]
    before = world.db.query(models.TalentStudentAssessment).count()
    response = world.client.post("/api/talent/assessments", json={"cycle_id": cycle.id, "student_id": target["student_id"]})
    assert response.status_code == 400
    assert response.json()["code"] == "assessment_tool_unavailable"
    world.db.expire_all()
    assert world.db.query(models.TalentStudentAssessment).count() == before


def test_branch_limited_actor_cannot_start_a_student_of_another_branch(world):
    program, cycle = make_program(world, name="Branch Guard", competency_grade=None)
    world.as_admin(world.north)
    south_members = [m for m in roster(world, cycle.id) if m["branch_id"] == world.south] if roster(world, cycle.id) and "branch_id" in roster(world, cycle.id)[0] else []
    south_student = (south_members or [{"student_id": next(iter(
        {row.student_id for row in world.db.query(models.TalentAssessmentCyclePopulationMember).filter_by(branch_id=world.south)}))}])[0]["student_id"]
    world.branch_limited_user(world.north)
    response = world.client.post("/api/talent/assessments", json={"cycle_id": cycle.id, "student_id": south_student})
    assert response.status_code in (400, 403, 404), response.text
    assert not world.db.query(models.TalentStudentAssessment).filter_by(cycle_id=cycle.id, student_id=south_student).count()
