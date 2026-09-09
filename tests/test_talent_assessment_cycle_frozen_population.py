from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
import permission_registry
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_assessment_cycles import router
from student_academic_service import create_placement, create_student, transition_placement, update_student
from talent_assessment_cycle_service import (
    TalentAssessmentCycleError, close_cycle, create_cycle, frozen_population,
    open_cycle, population_fingerprint, preview_population, update_cycle,
)
from talent_program_service import (
    activate_framework, create_framework_draft, create_program, retire_framework,
    transition_program, upsert_annual_configuration,
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
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    session.commit()
    session.add_all([
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=11, academic_year_id=100, grade_level="1", section_name="B", class_status="Current"),
        models.PlanningSection(id=1002, branch_id=10, academic_year_id=100, grade_level="4", section_name="D", class_status="Current"),
    ])
    session.commit()
    yield engine, session
    session.close()


def foundation(db, *, group=1, year=100, name="Potential", grades=("1", "2")):
    program = create_program(db, school_group_id=group, name=name)
    transition_program(db, school_group_id=group, program_id=program.id, target_status="active")
    framework = create_framework_draft(db, school_group_id=group, program_id=program.id, title=f"{name} Framework")
    activate_framework(db, school_group_id=group, program_id=program.id, framework_id=framework.id,
                       expected_revision=framework.revision, expected_fingerprint=framework.semantic_fingerprint,
                       organization_authorized=True)
    config = upsert_annual_configuration(db, school_group_id=group, program_id=program.id,
                                         academic_year_id=year, is_enabled=True,
                                         eligible_grade_levels=list(grades))
    db.commit()
    return program, framework, config


def student_placement(db, *, first, branch=10, section=1000, grade=None,
                      start=datetime(2026, 9, 1), end=None):
    student = create_student(db, school_group_id=1, first_name=first, last_name="Learner")
    placement = create_placement(
        db, school_group_id=1, student_id=student.id, academic_year_id=100,
        branch_id=branch, planning_section_id=section,
        grade_level=grade, section_name="Direct" if section is None else None,
        effective_from=start, effective_to=end,
    )
    db.commit()
    return student, placement


def draft_cycle(db, program, framework, *, effective=datetime(2026, 10, 1)):
    row = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                       framework_version_id=framework.id, title="Autumn Review",
                       population_effective_at=effective)
    db.commit()
    return row


def test_draft_cycle_context_alignment_and_stale_metadata_edits(db):
    _, session = db
    program, framework, _ = foundation(session)
    cycle = draft_cycle(session, program, framework)
    assert cycle.status == "draft" and cycle.population_effective_at == datetime(2026, 10, 1)
    updated = update_cycle(session, school_group_id=1, cycle_id=cycle.id,
                           expected_revision=1, title="Updated", population_effective_at=datetime(2026, 11, 1))
    assert updated.revision == 2
    with pytest.raises(TalentAssessmentCycleError) as stale:
        update_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1, title="Lost")
    assert stale.value.code == "stale_cycle"
    with pytest.raises(TalentAssessmentCycleError) as foreign:
        create_cycle(session, school_group_id=2, program_id=program.id, academic_year_id=200,
                     framework_version_id=framework.id, title="Forged")
    assert foreign.value.code == "invalid_scope"


def test_effective_time_grade_eligibility_and_dynamic_draft_preview(db):
    _, session = db
    program, framework, config = foundation(session, grades=("1",))
    eligible, placement = student_placement(session, first="Eligible", start=datetime(2026, 9, 1))
    student_placement(session, first="Late", start=datetime(2026, 11, 1))
    student_placement(session, first="Ended", start=datetime(2026, 8, 1), end=datetime(2026, 10, 1))
    student_placement(session, first="Grade Four", section=1002)
    create_student(session, school_group_id=1, first_name="No Placement", last_name="Learner")
    session.commit()
    cycle = draft_cycle(session, program, framework)
    _, preview = preview_population(session, school_group_id=1, cycle_id=cycle.id)
    assert [(row["student_id"], row["academic_placement_id"]) for row in preview] == [(eligible.id, placement.id)]
    config.eligible_grade_levels_csv = "1,4"
    session.commit()
    _, changed = preview_population(session, school_group_id=1, cycle_id=cycle.id)
    assert len(changed) == 2


def test_current_student_status_never_reinterprets_historical_eligibility(db):
    # Student.status is only current mutable state with no effective-dated
    # history (see models.py Student / student_academic_service.py). A
    # present-day status change must never retroactively alter eligibility
    # for an already-defined historical population_effective_at instant.
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="LaterInactive", start=datetime(2026, 9, 1))
    session.commit()
    cycle = draft_cycle(session, program, framework, effective=datetime(2026, 10, 1))
    _, preview_before = preview_population(session, school_group_id=1, cycle_id=cycle.id)
    assert [row["student_id"] for row in preview_before] == [student.id]
    update_student(session, school_group_id=1, student_id=student.id, status="inactive")
    session.commit()
    _, preview_after = preview_population(session, school_group_id=1, cycle_id=cycle.id)
    assert [row["student_id"] for row in preview_after] == [student.id]
    opened = open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=cycle.revision,
                        organization_authorized=True)
    session.commit()
    assert opened.population_count == 1
    _, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert [member.student_id for member in members] == [student.id]


def test_missing_disabled_config_and_unusable_framework_block_atomic_open(db):
    _, session = db
    program, framework, config = foundation(session)
    cycle = draft_cycle(session, program, framework)
    config.is_enabled = False
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as disabled:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=True)
    assert disabled.value.code == "annual_configuration_unavailable"
    assert cycle.status == "draft" and session.query(models.TalentAssessmentCyclePopulationMember).count() == 0
    session.delete(config)
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as missing:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=True)
    assert missing.value.code == "annual_configuration_unavailable"
    upsert_annual_configuration(session, school_group_id=1, program_id=program.id,
                                academic_year_id=100, is_enabled=True,
                                eligible_grade_levels=["1", "2"])
    framework.status = "retired"
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as unusable:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=True)
    assert unusable.value.code == "unusable_framework"
    assert session.query(models.TalentAssessmentCyclePopulationMember).count() == 0


def test_open_freezes_exact_context_and_fingerprint_then_close_is_final(db):
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="Maya")
    cycle = draft_cycle(session, program, framework)
    opened = open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                        organization_authorized=True)
    session.commit()
    _, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert opened.status == "open" and opened.population_count == 1
    member = members[0]
    assert (member.student_id, member.academic_placement_id, member.branch_id, member.grade_level, member.section_name) == (student.id, placement.id, 10, "1", "A")
    canonical = [dict(student_id=member.student_id, academic_placement_id=member.academic_placement_id,
                      academic_year_id=member.academic_year_id, branch_id=member.branch_id,
                      grade_level=member.grade_level, section_name=member.section_name)]
    assert population_fingerprint(cycle, canonical) == opened.population_fingerprint
    assert population_fingerprint(cycle, list(reversed(canonical))) == opened.population_fingerprint
    closed = close_cycle(session, school_group_id=1, cycle_id=cycle.id,
                         expected_revision=opened.revision, organization_authorized=True)
    session.commit()
    assert closed.status == "closed"
    with pytest.raises(TalentAssessmentCycleError):
        open_cycle(session, school_group_id=1, cycle_id=cycle.id,
                   expected_revision=closed.revision, organization_authorized=True)
    with pytest.raises(TalentAssessmentCycleError) as immutable:
        update_cycle(session, school_group_id=1, cycle_id=cycle.id,
                     expected_revision=closed.revision, title="Rewrite")
    assert immutable.value.code == "immutable_cycle"


def test_post_open_sources_cannot_reinterpret_frozen_population(db):
    _, session = db
    program, framework, config = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="Historical")
    cycle = draft_cycle(session, program, framework)
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    session.commit()
    section = session.get(models.PlanningSection, 1000)
    section.section_name = "RENAMED"
    section.grade_level = "4"
    config.eligible_grade_levels_csv = "4"
    _, later = transition_placement(
        session, school_group_id=1, student_id=student.id, placement_id=placement.id,
        transition_at=datetime(2026, 12, 1), academic_year_id=100, branch_id=11,
        planning_section_id=1001,
    )
    retire_framework(session, school_group_id=1, program_id=program.id,
                     framework_id=framework.id, organization_authorized=True)
    session.commit()
    cycle, members = frozen_population(session, school_group_id=1, cycle_id=cycle.id)
    assert cycle.framework_version_id == framework.id and framework.status == "retired"
    assert later.branch_id == 11
    assert [(row.branch_id, row.grade_level, row.section_name, row.planning_section_id) for row in members] == [(10, "1", "A", 1000)]


def test_open_requires_organization_scope_and_cannot_duplicate_members(db):
    _, session = db
    program, framework, _ = foundation(session)
    student_placement(session, first="One")
    cycle = draft_cycle(session, program, framework)
    with pytest.raises(TalentAssessmentCycleError) as denied:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
                   organization_authorized=False)
    assert denied.value.code == "organization_authority_required"
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    session.commit()
    with pytest.raises(TalentAssessmentCycleError) as reopened:
        open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=2,
                   organization_authorized=True)
    assert reopened.value.code == "invalid_lifecycle"
    assert session.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).count() == 1


def _user(user_id, *, branch, scope, role="Administrator", group=1):
    return models.User(user_id=user_id, username=f"user{user_id}", role=role, user_type="TENANT",
                       access_scope=scope, school_group_id=group, branch_id=branch,
                       academic_year_id=100 if group == 1 else 200, is_active=True)


def _client(db, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_branch_manage_can_author_draft_but_never_open(db):
    _, session = db
    program, framework, _ = foundation(session)
    branch_admin = _user("1000000001", branch=10, scope="BRANCH")
    session.add(branch_admin)
    session.commit()
    with _client(session, branch_admin) as client:
        created = client.post("/api/talent/assessment-cycles", json={
            "program_id": program.id, "academic_year_id": 100,
            "framework_version_id": framework.id, "title": "Branch Authored",
            "population_effective_at": "2026-10-01T00:00:00Z",
        })
        assert created.status_code == 201
        cycle_id = created.json()["id"]
        assert client.patch(f"/api/talent/assessment-cycles/{cycle_id}", json={"expected_revision": 1, "title": "Edited"}).status_code == 200
        denied = client.post(f"/api/talent/assessment-cycles/{cycle_id}/open", json={"expected_revision": 2})
        assert denied.status_code == 403 and denied.json()["code"] == "organization_authority_required"


def test_population_permission_and_branch_filtered_preview_do_not_leak_totals(db):
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student_placement(session, first="Branch A", branch=10, section=1000)
    student_placement(session, first="Branch B", branch=11, section=1001)
    cycle = draft_cycle(session, program, framework)
    branch_admin = _user("1000000001", branch=10, scope="BRANCH")
    view_only = _user("1000000002", branch=10, scope="BRANCH", role="Editor")
    session.add_all([branch_admin, view_only, models.RolePermission(
        school_group_id=1, role="Editor", permission_key="talent_assessment_cycles.view", is_allowed=True
    )])
    session.commit()
    with _client(session, view_only) as client:
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}").status_code == 200
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}/population/preview").status_code == 403
    with _client(session, branch_admin) as client:
        result = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population/preview")
        assert result.status_code == 200
        body = result.json()
        assert body["scope"] == "authorized_branches" and body["is_filtered"] is True
        assert body["count"] == 1 and body["members"][0]["branch_id"] == 10
        assert "population_fingerprint" not in body and "population_count" not in body


def test_frozen_read_uses_historical_branch_while_organization_sees_integrity(db):
    _, session = db
    program, framework, _ = foundation(session, grades=("1",))
    student, placement = student_placement(session, first="Transfer", branch=10, section=1000)
    student_placement(session, first="Other", branch=11, section=1001)
    cycle = draft_cycle(session, program, framework)
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1,
               organization_authorized=True)
    _, current = transition_placement(session, school_group_id=1, student_id=student.id,
                                      placement_id=placement.id, transition_at=datetime(2026, 12, 1),
                                      academic_year_id=100, branch_id=11, planning_section_id=1001)
    branch_admin = _user("1000000001", branch=10, scope="BRANCH")
    org_admin = _user("1000000002", branch=10, scope="ORGANIZATION")
    session.add_all([branch_admin, org_admin])
    session.commit()
    assert current.branch_id == 11
    with _client(session, branch_admin) as client:
        body = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population").json()
        assert body["count"] == 1 and body["members"][0]["student_id"] == student.id
        assert body["members"][0]["branch_id"] == 10
        assert "population_count" not in body and "population_fingerprint" not in body
    with _client(session, org_admin) as client:
        body = client.get(f"/api/talent/assessment-cycles/{cycle.id}/population").json()
        assert body["count"] == body["population_count"] == 2
        assert body["population_fingerprint"] == cycle.population_fingerprint


def test_dedicated_permissions_and_cross_tenant_ids_are_non_enumerating(db):
    _, session = db
    program, framework, _ = foundation(session)
    cycle = draft_cycle(session, program, framework)
    editor = _user("1000000001", branch=10, scope="ORGANIZATION", role="Editor")
    foreign_admin = _user("1000000002", branch=20, scope="ORGANIZATION", group=2)
    session.add_all([editor, foreign_admin])
    session.add_all([
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.manage", is_allowed=True),
        models.RolePermission(school_group_id=1, role="Editor", permission_key="talent_programs.govern", is_allowed=True),
    ])
    session.commit()
    with _client(session, editor) as client:
        assert client.post("/api/talent/assessment-cycles", json={}).status_code == 403
        assert client.post(f"/api/talent/assessment-cycles/{cycle.id}/open", json={"expected_revision": 1}).status_code == 403
    with _client(session, foreign_admin) as client:
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}").status_code == 404
        assert client.get(f"/api/talent/assessment-cycles/{cycle.id}/population/preview").status_code == 404
    defaults = permission_registry.get_default_permissions_for_role("Administrator")
    editor_defaults = permission_registry.get_default_permissions_for_role("Editor")
    assert all(key in defaults for key in {
        "talent_assessment_cycles.view", "talent_assessment_cycles.manage",
        "talent_assessment_cycles.view_population", "talent_assessment_cycles.govern",
    })
    assert not any(key.startswith("talent_assessment_cycles.") for key in editor_defaults)


def test_cycle_audit_is_append_only_and_open_records_population_provenance(db):
    _, session = db
    program, framework, _ = foundation(session)
    student_placement(session, first="Audited")
    cycle = draft_cycle(session, program, framework)
    update_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=1, title="Audited Cycle")
    open_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=2,
               organization_authorized=True)
    close_cycle(session, school_group_id=1, cycle_id=cycle.id, expected_revision=3,
                organization_authorized=True)
    session.commit()
    audits = session.query(models.TalentAssessmentAudit).filter_by(cycle_id=cycle.id).order_by(models.TalentAssessmentAudit.id).all()
    assert [row.action for row in audits] == ["create", "update", "open", "close"]
    assert cycle.population_fingerprint in audits[2].after_json
    assert "effective_at" in audits[2].after_json and '"count":1' in audits[2].after_json


def test_m4_migration_is_additive_and_idempotent(db):
    engine, session = db
    session.close()
    with engine.begin() as connection:
        models.TalentAssessmentAudit.__table__.drop(connection)
        models.TalentAssessmentCyclePopulationMember.__table__.drop(connection)
        models.TalentAssessmentCycle.__table__.drop(connection)
        db_migrations._talent_assessment_cycle_frozen_population_foundation(engine, connection)
        db_migrations._talent_assessment_cycle_frozen_population_foundation(engine, connection)
    expected = {"talent_assessment_cycles", "talent_assessment_cycle_population_members", "talent_assessment_audits"}
    assert expected.issubset(inspect(engine).get_table_names())
    assert any(row.migration_id == "20260904_004_talent_assessment_cycle_frozen_population" for row in db_migrations.MIGRATIONS)


def test_forged_cross_tenant_population_relationship_is_rejected(db):
    _, session = db
    program, framework, _ = foundation(session)
    student, placement = student_placement(session, first="Scoped")
    cycle = draft_cycle(session, program, framework)
    session.add(models.TalentAssessmentCyclePopulationMember(
        school_group_id=2, cycle_id=cycle.id, program_id=program.id,
        academic_year_id=100, framework_version_id=framework.id,
        student_id=student.id, academic_placement_id=placement.id, branch_id=10,
        grade_level="1", section_name="A", population_effective_at=datetime(2026, 10, 1),
    ))
    with pytest.raises(IntegrityError):
        session.commit()
