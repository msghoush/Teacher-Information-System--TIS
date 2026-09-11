"""Batch 2 corrective reconstruction regression coverage.

Covers:
- ADR 0032's scoped Draft Talent Program hard-delete exception
  (routers/talent_programs.py DELETE /{program_id}, talent_program_service.py
  delete_program/program_delete_blockers).
- Dedicated talent_programs.delete_competency and
  talent_programs.delete_rubric_level permissions narrowing the existing
  Competency and Rubric Level true-delete routes.
- The new talent_evaluation_plans.delete_period and
  talent_evaluation_plans.manage_timeline permissions gating Period delete,
  reorder, and mixed timeline/content PATCH requests.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_evaluation_plans import router as plan_router
from routers.talent_programs import router as programs_router
from talent_evaluation_plan_service import TalentEvaluationPlanError, add_period, create_plan
from talent_program_service import (
    TalentProgramError,
    add_framework_competency,
    add_rubric_level,
    create_competency,
    create_framework_draft,
    create_program,
    delete_program,
    program_delete_blockers,
    transition_program,
    upsert_annual_configuration,
    upsert_rubric,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.PlanningSection(id=900, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
    ])
    session.commit()
    yield session
    session.close()


def user(user_id, *, role="Administrator", scope="ORGANIZATION", group=1, branch=10):
    return models.User(user_id=user_id, username=f"u{user_id}", role=role, user_type="TENANT",
                        access_scope=scope, school_group_id=group, branch_id=branch,
                        academic_year_id=100, is_active=True)


def client(db, current):
    app = FastAPI()
    app.include_router(programs_router)
    app.include_router(plan_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


def grant(db, role, *keys, group=1):
    db.add_all([models.RolePermission(school_group_id=group, role=role, permission_key=key, is_allowed=True) for key in keys])
    db.commit()


def deny(db, role, *keys, group=1):
    db.add_all([models.RolePermission(school_group_id=group, role=role, permission_key=key, is_allowed=False) for key in keys])
    db.commit()


# ---------------------------------------------------------------------------
# ADR 0032 service-layer coverage: exact real FK list re-verified against the
# current models.py schema.
# ---------------------------------------------------------------------------

def test_draft_program_with_zero_related_rows_deletes_and_audits(db):
    program = create_program(db, school_group_id=1, name="Empty Draft", description="Purpose")
    db.commit()
    assert program.status == "draft"
    assert program_delete_blockers(db, program_id=program.id) == []
    deleted_id = delete_program(db, school_group_id=1, program_id=program.id)
    db.commit()
    assert deleted_id == program.id
    assert db.get(models.TalentProgram, program.id) is None
    audits = db.query(models.TalentConfigurationAudit).filter_by(resource_type="program", resource_id=program.id, action="delete").all()
    assert len(audits) == 1 and audits[0].before_json


def test_non_draft_program_delete_is_rejected(db):
    program = create_program(db, school_group_id=1, name="Active Program")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    db.commit()
    with pytest.raises(TalentProgramError) as exc:
        delete_program(db, school_group_id=1, program_id=program.id)
    assert exc.value.code == "not_draft"
    assert db.get(models.TalentProgram, program.id) is not None


@pytest.mark.parametrize("blocker_label", [
    "framework_versions", "academic_year_configurations", "competencies",
    "assessment_cycles", "educator_inputs",
])
def test_each_real_blocker_table_individually_blocks_delete(db, blocker_label):
    program = create_program(db, school_group_id=1, name=f"Blocked by {blocker_label}")
    db.commit()

    if blocker_label == "framework_versions":
        create_framework_draft(db, school_group_id=1, program_id=program.id, title="Setup")
    elif blocker_label == "academic_year_configurations":
        upsert_annual_configuration(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                                     is_enabled=True, eligible_grade_levels=["1"])
    elif blocker_label == "competencies":
        create_competency(db, school_group_id=1, program_id=program.id, code="C1", name="Competency")
    elif blocker_label == "assessment_cycles":
        framework = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Setup")
        db.add(models.TalentAssessmentCycle(
            school_group_id=1, program_id=program.id, academic_year_id=100, framework_version_id=framework.id,
            title="Cycle", status="draft", revision=1,
        ))
    elif blocker_label == "educator_inputs":
        student = models.Student(school_group_id=1, first_name="A", last_name="B", status="active")
        db.add(student)
        db.flush()
        placement = models.StudentAcademicPlacement(
            school_group_id=1, student_id=student.id, academic_year_id=100, branch_id=10,
            grade_level="1", section_name="A", effective_from=datetime(2026, 9, 1), status="active",
        )
        db.add(placement)
        db.flush()
        db.add(models.TalentEducatorInput(
            school_group_id=1, program_id=program.id, student_id=student.id, academic_year_id=100,
            observed_at=datetime(2026, 9, 1), academic_placement_id=placement.id, branch_id=10,
            grade_level="1", section_name="A", category="observation", content="Note",
        ))
    db.commit()

    blockers = program_delete_blockers(db, program_id=program.id)
    assert blocker_label in blockers
    with pytest.raises(TalentProgramError) as exc:
        delete_program(db, school_group_id=1, program_id=program.id)
    assert exc.value.code == "program_has_dependents"
    assert db.get(models.TalentProgram, program.id) is not None


# ---------------------------------------------------------------------------
# Router-level: DELETE /api/talent/programs/{program_id}
# ---------------------------------------------------------------------------

def test_program_delete_route_requires_new_permission_not_manage(db):
    program = create_program(db, school_group_id=1, name="Draft Only")
    db.commit()
    actor = user("1000000001")
    db.add(actor)
    grant(db, "Administrator", "talent_programs.view", "talent_programs.manage", "talent_programs.delete")
    deny(db, "Administrator", "talent_programs.delete_competency", "talent_programs.delete_rubric_level")
    with client(db, actor) as api:
        response = api.delete(f"/api/talent/programs/{program.id}")
        assert response.status_code == 403
    assert db.get(models.TalentProgram, program.id) is not None


def test_program_delete_route_succeeds_with_permission_and_org_authority(db):
    program = create_program(db, school_group_id=1, name="Draft Deletable")
    db.commit()
    actor = user("1000000002")
    db.add(actor)
    grant(db, "Administrator", "talent_programs.view", "talent_programs.delete")
    with client(db, actor) as api:
        read = api.get(f"/api/talent/programs/{program.id}")
        assert read.status_code == 200 and "delete" in read.json()["actions"]
        response = api.delete(f"/api/talent/programs/{program.id}")
        assert response.status_code == 200
        assert response.json() == {"id": program.id, "deleted": True}
    assert db.get(models.TalentProgram, program.id) is None


def test_program_delete_route_rejects_cross_tenant_program(db):
    outsider = create_program(db, school_group_id=2, name="Outside")
    db.commit()
    actor = user("1000000003")
    db.add(actor)
    grant(db, "Administrator", "talent_programs.view", "talent_programs.delete")
    with client(db, actor) as api:
        response = api.delete(f"/api/talent/programs/{outsider.id}")
        assert response.status_code == 404
    assert db.get(models.TalentProgram, outsider.id) is not None


def test_program_actions_omit_delete_when_program_has_dependents(db):
    program = create_program(db, school_group_id=1, name="Has Children")
    create_competency(db, school_group_id=1, program_id=program.id, code="C1", name="Competency")
    db.commit()
    actor = user("1000000004")
    db.add(actor)
    grant(db, "Administrator", "talent_programs.view", "talent_programs.delete")
    with client(db, actor) as api:
        read = api.get(f"/api/talent/programs/{program.id}")
        assert read.status_code == 200 and "delete" not in read.json()["actions"]
        response = api.delete(f"/api/talent/programs/{program.id}")
        assert response.status_code == 400 and response.json()["code"] == "program_has_dependents"
    assert db.get(models.TalentProgram, program.id) is not None


# ---------------------------------------------------------------------------
# Existing true-delete narrowing: Competency framework-membership and Rubric
# Level, from talent_programs.manage to talent_programs.delete.
# ---------------------------------------------------------------------------

def test_framework_competency_and_rubric_level_delete_require_dedicated_permissions(db):
    program = create_program(db, school_group_id=1, name="Setup Program")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Setup")
    competency = create_competency(db, school_group_id=1, program_id=program.id, code="C1", name="Competency")
    member, framework = add_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                                                   competency_id=competency.id, expected_revision=framework.revision)
    rubric, framework = upsert_rubric(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                                       expected_revision=framework.revision, name="Rubric")
    level, framework = add_rubric_level(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                                         expected_revision=framework.revision, code="L1", label="Level One")
    db.commit()

    actor = user("1000000005")
    db.add(actor)
    grant(db, "Administrator", "talent_programs.view", "talent_programs.manage", "talent_programs.delete")
    deny(db, "Administrator", "talent_programs.delete_competency", "talent_programs.delete_rubric_level")
    with client(db, actor) as api:
        comp_response = api.delete(
            f"/api/talent/programs/{program.id}/frameworks/{framework.id}/competencies/{competency.id}",
            params={"expected_revision": framework.revision},
        )
        assert comp_response.status_code == 403
        level_response = api.delete(
            f"/api/talent/programs/{program.id}/frameworks/{framework.id}/rubric/levels/{level.id}",
            params={"expected_revision": framework.revision},
        )
        assert level_response.status_code == 403

    assert db.query(models.FrameworkCompetency).filter_by(id=member.id).one_or_none() is not None
    assert db.query(models.TalentRubricLevel).filter_by(id=level.id).one_or_none() is not None


def test_framework_competency_delete_succeeds_with_new_permission(db):
    program = create_program(db, school_group_id=1, name="Setup Program 2")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=1, program_id=program.id, title="Setup")
    competency = create_competency(db, school_group_id=1, program_id=program.id, code="C1", name="Competency")
    member, framework = add_framework_competency(db, school_group_id=1, program_id=program.id, framework_id=framework.id,
                                                   competency_id=competency.id, expected_revision=framework.revision)
    rubric, framework = upsert_rubric(
        db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        framework_competency_id=member.id, expected_revision=framework.revision, name="Owned Rubric",
    )
    level, framework = add_rubric_level(
        db, school_group_id=1, program_id=program.id, framework_id=framework.id,
        framework_competency_id=member.id, expected_revision=framework.revision,
        code="L1", label="Level One",
    )
    db.commit()

    actor = user("1000000006")
    db.add(actor)
    grant(db, "Administrator", "talent_programs.view", "talent_programs.delete_competency")
    with client(db, actor) as api:
        response = api.delete(
            f"/api/talent/programs/{program.id}/frameworks/{framework.id}/competencies/{competency.id}",
            params={"expected_revision": framework.revision},
        )
        assert response.status_code == 200
    assert db.query(models.FrameworkCompetency).filter_by(id=member.id).one_or_none() is None
    assert db.query(models.TalentRubric).filter_by(id=rubric.id).one_or_none() is None
    assert db.query(models.TalentRubricLevel).filter_by(id=level.id).one_or_none() is None


# ---------------------------------------------------------------------------
# Evaluation Period: delete_period, manage_timeline (reorder + mixed PATCH).
# ---------------------------------------------------------------------------

def evaluation_foundation(db):
    program = create_program(db, school_group_id=1, name="Evaluation Program")
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active")
    config = upsert_annual_configuration(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                                          is_enabled=True, eligible_grade_levels=["1"])
    db.commit()
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, period = add_period(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision, label="Term 1")
    db.commit()
    return plan, period


def test_period_delete_requires_delete_period_permission_not_manage(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000007")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage")
    deny(db, "Administrator", "talent_evaluation_plans.delete_period")
    with client(db, actor) as api:
        response = api.request("DELETE", f"/api/talent/evaluation-periods/{period.id}", json={"expected_plan_revision": plan.revision})
        assert response.status_code == 403
    assert db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period.id).one_or_none() is not None


def test_period_delete_succeeds_with_delete_period_permission(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000008")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.delete_period")
    with client(db, actor) as api:
        response = api.request("DELETE", f"/api/talent/evaluation-periods/{period.id}", json={"expected_plan_revision": plan.revision})
        assert response.status_code == 200
    assert db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period.id).one_or_none() is None


def test_reorder_requires_manage_timeline_not_manage(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000009")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage")
    deny(db, "Administrator", "talent_evaluation_plans.manage_timeline")
    with client(db, actor) as api:
        response = api.post(f"/api/talent/evaluation-plans/{plan.id}/periods/reorder",
                             json={"expected_plan_revision": plan.revision, "period_ids": [period.id]})
        assert response.status_code == 403


def test_reorder_succeeds_with_manage_timeline(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000010")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage_timeline")
    with client(db, actor) as api:
        response = api.post(f"/api/talent/evaluation-plans/{plan.id}/periods/reorder",
                             json={"expected_plan_revision": plan.revision, "period_ids": [period.id]})
        assert response.status_code == 200


def test_mixed_patch_requires_both_permissions_no_partial_application(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000011")
    db.add(actor)
    # Only content permission granted, not timeline.
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage")
    deny(db, "Administrator", "talent_evaluation_plans.manage_timeline")
    with client(db, actor) as api:
        response = api.patch(f"/api/talent/evaluation-periods/{period.id}", json={
            "expected_plan_revision": plan.revision, "label": "Renamed", "planned_start_date": "2026-09-01",
        })
        assert response.status_code == 403
    unchanged = db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period.id).one()
    assert unchanged.label == "Term 1" and unchanged.planned_start_date is None


def test_content_only_patch_still_works_with_manage_alone(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000012")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage")
    deny(db, "Administrator", "talent_evaluation_plans.manage_timeline")
    with client(db, actor) as api:
        response = api.patch(f"/api/talent/evaluation-periods/{period.id}", json={
            "expected_plan_revision": plan.revision, "label": "Renamed Only",
        })
        assert response.status_code == 200
    assert db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period.id).one().label == "Renamed Only"


def test_timeline_only_patch_requires_manage_timeline_alone(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000013")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage_timeline")
    deny(db, "Administrator", "talent_evaluation_plans.manage")
    with client(db, actor) as api:
        response = api.patch(f"/api/talent/evaluation-periods/{period.id}", json={
            "expected_plan_revision": plan.revision, "planned_start_date": "2026-09-01",
        })
        assert response.status_code == 200
    assert db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period.id).one().planned_start_date.isoformat() == "2026-09-01"


def test_mixed_patch_succeeds_with_both_permissions(db):
    plan, period = evaluation_foundation(db)
    actor = user("1000000014")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.view", "talent_evaluation_plans.manage", "talent_evaluation_plans.manage_timeline")
    with client(db, actor) as api:
        response = api.patch(f"/api/talent/evaluation-periods/{period.id}", json={
            "expected_plan_revision": plan.revision, "label": "Both", "planned_start_date": "2026-09-01",
        })
        assert response.status_code == 200
    row = db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period.id).one()
    assert row.label == "Both" and row.planned_start_date.isoformat() == "2026-09-01"


def test_linking_an_evaluation_period_requires_select_period_permission(db):
    actor = user("1000000015")
    db.add(actor)
    grant(db, "Administrator", "talent_evaluation_plans.manage", "talent_assessment_cycles.manage")
    deny(db, "Administrator", "talent_evaluation_plans.select_period")
    with client(db, actor) as api:
        response = api.post(
            "/api/talent/assessment-cycles/999/link-period",
            json={"planned_period_id": 888, "expected_plan_revision": 1, "expected_cycle_revision": 1},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Permission registry shape: additive tuples, no hard-coded role names.
# ---------------------------------------------------------------------------

def test_new_permission_keys_are_registered_with_the_same_additive_shape():
    import permission_registry as pr
    for key in ("talent_programs.delete", "talent_programs.delete_competency", "talent_programs.delete_rubric_level", "talent_evaluation_plans.delete_period", "talent_evaluation_plans.manage_timeline", "talent_evaluation_plans.select_period"):
        assert key in pr.ALL_PERMISSION_KEYS
        assert key in pr.PERMISSION_LABELS and isinstance(pr.PERMISSION_LABELS[key], str) and pr.PERMISSION_LABELS[key]
        assert key in pr.DEVELOPER_ASSIGNABLE_PERMISSION_KEYS
    # No role name is hard-coded onto these new keys beyond the existing
    # Administrator "all permissions" default, mirroring every existing
    # talent_programs.*/talent_evaluation_plans.* key.
    assert "talent_programs.delete" not in pr._EDITOR_LIKE_PERMISSIONS
    assert "talent_programs.delete_competency" not in pr._EDITOR_LIKE_PERMISSIONS
    assert "talent_programs.delete_rubric_level" not in pr._EDITOR_LIKE_PERMISSIONS
    assert "talent_evaluation_plans.delete_period" not in pr._EDITOR_LIKE_PERMISSIONS
    assert "talent_evaluation_plans.manage_timeline" not in pr._EDITOR_LIKE_PERMISSIONS
    assert "talent_evaluation_plans.select_period" not in pr._EDITOR_LIKE_PERMISSIONS
    assert "talent_evaluation_plans.select_period" in pr.DEFAULT_ROLE_PERMISSIONS[pr.auth.ROLE_ADMINISTRATOR]
    assert "talent_evaluation_plans.select_period" not in pr.DEFAULT_ROLE_PERMISSIONS[pr.auth.ROLE_EDITOR]
    assert "talent_evaluation_plans.select_period" not in pr.DEFAULT_ROLE_PERMISSIONS[pr.auth.ROLE_USER]
