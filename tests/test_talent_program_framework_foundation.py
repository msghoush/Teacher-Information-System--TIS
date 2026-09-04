import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_programs import router
from talent_program_service import (
    TalentProgramError, activate_framework, add_framework_competency, create_competency,
    create_framework_draft, create_program, list_programs, remove_framework_competency,
    reorder_framework_competencies, retire_framework, transition_program, update_competency,
    update_framework_competency, update_framework_draft, update_program,
    upsert_annual_configuration,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _): connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine); session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")]); session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"), models.Branch(id=11, school_group_id=1, name="One B"), models.Branch(id=20, school_group_id=2, name="Two"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"), models.AcademicYear(id=101, school_group_id=1, year_name="2027-2028"), models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ]); session.commit(); yield session; session.close()


def program(db, group=1, name="Potential"):
    row = create_program(db, school_group_id=group, name=name, description="Purpose"); db.commit(); return row


def test_program_lifecycle_update_tenant_scope_and_history(db):
    row = program(db)
    update_program(db, school_group_id=1, program_id=row.id, name="Talent & Potential"); db.commit()
    assert [p.id for p in list_programs(db, school_group_id=1, search="Talent")] == [row.id]
    assert list_programs(db, school_group_id=2) == []
    assert update_program
    transition_program(db, school_group_id=1, program_id=row.id, target_status="active")
    transition_program(db, school_group_id=1, program_id=row.id, target_status="retired"); db.commit()
    with pytest.raises(TalentProgramError) as lifecycle: transition_program(db, school_group_id=1, program_id=row.id, target_status="active")
    assert lifecycle.value.code == "invalid_lifecycle"
    with pytest.raises(TalentProgramError) as immutable: update_program(db, school_group_id=1, program_id=row.id, name="Changed")
    assert immutable.value.code == "immutable_program"
    assert [a.action for a in db.query(models.TalentConfigurationAudit).filter_by(resource_type="program").order_by(models.TalentConfigurationAudit.id)] == ["create", "update", "activate", "retire"]


def test_annual_configuration_normalizes_grades_and_rejects_foreign_year(db):
    row = program(db)
    config = upsert_annual_configuration(db, school_group_id=1, program_id=row.id, academic_year_id=100,
        is_enabled=True, eligible_grade_levels=["2", "kg", "01"]); db.commit()
    assert config.eligible_grade_levels_csv == "KG,1,2"
    updated = upsert_annual_configuration(db, school_group_id=1, program_id=row.id, academic_year_id=100,
        is_enabled=False, eligible_grade_levels=["3"]); db.commit()
    assert updated.id == config.id and updated.is_enabled is False
    with pytest.raises(TalentProgramError) as foreign:
        upsert_annual_configuration(db, school_group_id=1, program_id=row.id, academic_year_id=200, is_enabled=True, eligible_grade_levels=["1"])
    assert foreign.value.code == "invalid_scope"
    with pytest.raises(TalentProgramError):
        upsert_annual_configuration(db, school_group_id=1, program_id=row.id, academic_year_id=101, is_enabled=True, eligible_grade_levels=["13"])


def test_framework_version_allocation_stale_guard_immutability_and_retirement(db):
    p = program(db)
    transition_program(db, school_group_id=1, program_id=p.id, target_status="active")
    one = create_framework_draft(db, school_group_id=1, program_id=p.id, title="Framework")
    two = create_framework_draft(db, school_group_id=1, program_id=p.id, title="Framework v2", supersedes_framework_version_id=one.id)
    assert (one.version_number, two.version_number) == (1, 2)
    original_fingerprint = one.semantic_fingerprint
    update_framework_draft(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1, title="Framework One")
    with pytest.raises(TalentProgramError) as stale:
        update_framework_draft(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1, title="Lost update")
    assert stale.value.code == "stale_framework"
    activate_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=2,
        expected_fingerprint=one.semantic_fingerprint, organization_authorized=True)
    with pytest.raises(TalentProgramError) as immutable:
        update_framework_draft(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=2, title="No")
    assert immutable.value.code == "immutable_framework" and one.semantic_fingerprint != original_fingerprint
    retire_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, organization_authorized=True); db.commit()
    assert one.status == "retired" and db.get(models.TalentProgramFrameworkVersion, one.id) is not None


def test_activation_requires_organization_authority_and_explicit_supersession(db):
    p = program(db); transition_program(db, school_group_id=1, program_id=p.id, target_status="active"); one = create_framework_draft(db, school_group_id=1, program_id=p.id, title="One")
    with pytest.raises(TalentProgramError) as denied:
        activate_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1,
            expected_fingerprint=one.semantic_fingerprint, organization_authorized=False)
    assert denied.value.code == "organization_authority_required"
    activate_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1, expected_fingerprint=one.semantic_fingerprint, organization_authorized=True)
    two = create_framework_draft(db, school_group_id=1, program_id=p.id, title="Two")
    with pytest.raises(TalentProgramError) as supersession:
        activate_framework(db, school_group_id=1, program_id=p.id, framework_id=two.id, expected_revision=1, expected_fingerprint=two.semantic_fingerprint, organization_authorized=True)
    assert supersession.value.code == "supersession_required"
    update_framework_draft(db, school_group_id=1, program_id=p.id, framework_id=two.id, expected_revision=1, supersedes_framework_version_id=one.id)
    activate_framework(db, school_group_id=1, program_id=p.id, framework_id=two.id, expected_revision=2, expected_fingerprint=two.semantic_fingerprint, organization_authorized=True)
    db.commit()
    assert one.status == "retired" and two.status == "active"


def test_competency_lineage_membership_order_snapshots_and_active_immutability(db):
    p = program(db); transition_program(db, school_group_id=1, program_id=p.id, target_status="active"); framework = create_framework_draft(db, school_group_id=1, program_id=p.id, title="One")
    c1 = create_competency(db, school_group_id=1, program_id=p.id, code="CRE", name="Creativity")
    c2 = create_competency(db, school_group_id=1, program_id=p.id, code="CRT", name="Critical Thinking")
    m1, framework = add_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_id=c1.id, expected_revision=1)
    m2, framework = add_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_id=c2.id, expected_revision=2)
    with pytest.raises(TalentProgramError) as duplicate:
        add_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_id=c1.id, expected_revision=3)
    assert duplicate.value.code == "duplicate_membership"
    _, framework = reorder_framework_competencies(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_ids=[c2.id, c1.id], expected_revision=3)
    m1, framework = update_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_id=c1.id, expected_revision=4, label="Creative Capacity")
    update_competency(db, school_group_id=1, program_id=p.id, competency_id=c1.id, name="Creativity Renamed"); db.flush()
    assert m1.label == "Creative Capacity"
    activate_framework(db, school_group_id=1, program_id=p.id, framework_id=framework.id, expected_revision=5, expected_fingerprint=framework.semantic_fingerprint, organization_authorized=True)
    with pytest.raises(TalentProgramError) as immutable:
        remove_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_id=c1.id, expected_revision=5)
    assert immutable.value.code == "immutable_framework"
    db.commit()


def test_cross_program_and_cross_tenant_membership_rejected(db):
    p1, p2, foreign = program(db, 1, "One Program"), program(db, 1, "Other Program"), program(db, 2, "Foreign")
    framework = create_framework_draft(db, school_group_id=1, program_id=p1.id, title="One")
    other = create_competency(db, school_group_id=1, program_id=p2.id, code="X", name="Other")
    outsider = create_competency(db, school_group_id=2, program_id=foreign.id, code="X", name="Foreign")
    for competency in (other, outsider):
        with pytest.raises(TalentProgramError) as invalid:
            add_framework_competency(db, school_group_id=1, program_id=p1.id, framework_id=framework.id, competency_id=competency.id, expected_revision=1)
        assert invalid.value.code == "invalid_competency"
    db.add(models.FrameworkCompetency(school_group_id=1, program_id=p1.id, framework_version_id=framework.id,
        talent_competency_id=other.id, display_order=1, label="Forged"))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


def test_clone_creates_independent_membership_and_preserves_lineage(db):
    p = program(db); source = create_framework_draft(db, school_group_id=1, program_id=p.id, title="One")
    competency = create_competency(db, school_group_id=1, program_id=p.id, code="COL", name="Collaboration")
    _, source = add_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=source.id, competency_id=competency.id, expected_revision=1)
    clone = create_framework_draft(db, school_group_id=1, program_id=p.id, title="Two", clone_from_id=source.id, supersedes_framework_version_id=source.id)
    source_member = db.query(models.FrameworkCompetency).filter_by(framework_version_id=source.id).one()
    clone_member = db.query(models.FrameworkCompetency).filter_by(framework_version_id=clone.id).one()
    assert clone_member.id != source_member.id and clone_member.talent_competency_id == source_member.talent_competency_id
    update_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=clone.id, competency_id=competency.id, expected_revision=1, label="Teamwork")
    assert source_member.label == "Collaboration"


def test_supersession_rejects_self_and_other_program(db):
    p1, p2 = program(db, 1, "One"), program(db, 1, "Two")
    one = create_framework_draft(db, school_group_id=1, program_id=p1.id, title="One")
    other = create_framework_draft(db, school_group_id=1, program_id=p2.id, title="Other")
    with pytest.raises(TalentProgramError) as foreign:
        update_framework_draft(db, school_group_id=1, program_id=p1.id, framework_id=one.id, expected_revision=1, supersedes_framework_version_id=other.id)
    assert foreign.value.code == "invalid_supersession"
    with pytest.raises(TalentProgramError) as self_ref:
        update_framework_draft(db, school_group_id=1, program_id=p1.id, framework_id=one.id, expected_revision=1, supersedes_framework_version_id=one.id)
    assert self_ref.value.code == "invalid_supersession"


def test_supersession_rejects_two_node_cycle(db):
    p = program(db)
    a = create_framework_draft(db, school_group_id=1, program_id=p.id, title="A")
    b = create_framework_draft(db, school_group_id=1, program_id=p.id, title="B", supersedes_framework_version_id=a.id)
    with pytest.raises(TalentProgramError) as cycle:
        update_framework_draft(db, school_group_id=1, program_id=p.id, framework_id=a.id, expected_revision=1, supersedes_framework_version_id=b.id)
    assert cycle.value.code == "invalid_supersession"


def test_activation_rejects_stale_revision_and_stale_fingerprint(db):
    p = program(db); transition_program(db, school_group_id=1, program_id=p.id, target_status="active")
    one = create_framework_draft(db, school_group_id=1, program_id=p.id, title="One")
    update_framework_draft(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1, title="One Revised")
    with pytest.raises(TalentProgramError) as stale_revision:
        activate_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1,
            expected_fingerprint=one.semantic_fingerprint, organization_authorized=True)
    assert stale_revision.value.code == "stale_framework"
    with pytest.raises(TalentProgramError) as stale_fingerprint:
        activate_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=2,
            expected_fingerprint="not-the-real-fingerprint", organization_authorized=True)
    assert stale_fingerprint.value.code == "stale_framework"
    assert one.status == "draft"


def test_program_retirement_blocked_while_framework_active(db):
    p = program(db); transition_program(db, school_group_id=1, program_id=p.id, target_status="active")
    one = create_framework_draft(db, school_group_id=1, program_id=p.id, title="One")
    activate_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, expected_revision=1,
        expected_fingerprint=one.semantic_fingerprint, organization_authorized=True)
    with pytest.raises(TalentProgramError) as blocked:
        transition_program(db, school_group_id=1, program_id=p.id, target_status="retired")
    assert blocked.value.code == "active_framework_exists"
    retire_framework(db, school_group_id=1, program_id=p.id, framework_id=one.id, organization_authorized=True)
    transition_program(db, school_group_id=1, program_id=p.id, target_status="retired")
    assert p.status == "retired"


def test_api_branch_author_can_draft_but_not_activate_and_ids_do_not_leak(db):
    branch_user = models.User(user_id="1000000001", username="branch.talent", role="Administrator", user_type="TENANT",
        access_scope="BRANCH", school_group_id=1, branch_id=10, academic_year_id=100, is_active=True)
    db.add(branch_user); db.commit(); branch_user.scope_school_group_id = 1; branch_user.scope_branch_id = 10
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_db] = lambda: db; app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        created = client.post("/api/talent/programs", json={"name": "Branch-authored"}); assert created.status_code == 201
        framework = client.post(f"/api/talent/programs/{created.json()['id']}/frameworks", json={"title": "Draft"}); assert framework.status_code == 201
        denied = client.post(f"/api/talent/programs/{created.json()['id']}/frameworks/{framework.json()['id']}/activate", json={"expected_revision": 1, "expected_fingerprint": framework.json()["semantic_fingerprint"]})
        assert denied.status_code == 403
        audit = db.query(models.TalentConfigurationAudit).filter_by(resource_type="framework_version", action="create").one()
        assert audit.actor_user_id == branch_user.user_id and audit.actor_branch_id == 10 and audit.school_group_id == 1
        outsider = program(db, 2, "Outside")
        assert client.get(f"/api/talent/programs/{outsider.id}").status_code == 404


def test_editor_role_default_planning_permission_no_longer_authorizes_talent_authorship(db):
    # Editor/User roles default-grant the broad, commonly-assigned planning.edit_section
    # permission, but must not receive the dedicated talent_programs.manage/.view keys by
    # default: this is the Checkpoint A fix for the previously unrestricted Branch-actor
    # organization-wide Talent authorship gap.
    editor_user = models.User(user_id="1000000003", username="editor.branch10", role="Editor", user_type="TENANT",
        access_scope="BRANCH", school_group_id=1, branch_id=10, academic_year_id=100, is_active=True)
    db.add(editor_user); db.commit(); editor_user.scope_school_group_id = 1; editor_user.scope_branch_id = 10
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_db] = lambda: db; app.dependency_overrides[get_current_user] = lambda: editor_user
    with TestClient(app) as client:
        denied_create = client.post("/api/talent/programs", json={"name": "Should Be Denied"})
        assert denied_create.status_code == 403
        denied_view = client.get("/api/talent/programs")
        assert denied_view.status_code == 403
    assert db.query(models.TalentProgram).count() == 0


def test_framework_and_membership_events_append_audit_history(db):
    p = program(db); transition_program(db, school_group_id=1, program_id=p.id, target_status="active"); framework = create_framework_draft(db, school_group_id=1, program_id=p.id, title="One")
    competency = create_competency(db, school_group_id=1, program_id=p.id, code="LEAD", name="Leadership")
    _, framework = add_framework_competency(db, school_group_id=1, program_id=p.id, framework_id=framework.id, competency_id=competency.id, expected_revision=1)
    activate_framework(db, school_group_id=1, program_id=p.id, framework_id=framework.id, expected_revision=2, expected_fingerprint=framework.semantic_fingerprint, organization_authorized=True)
    retire_framework(db, school_group_id=1, program_id=p.id, framework_id=framework.id, organization_authorized=True); db.commit()
    events = db.query(models.TalentConfigurationAudit).filter_by(program_id=p.id).order_by(models.TalentConfigurationAudit.id).all()
    assert [(e.resource_type, e.action) for e in events] == [
        ("program", "create"), ("program", "activate"), ("framework_version", "create"), ("competency", "create"),
        ("framework_competency", "add"), ("framework_version", "activate"), ("framework_version", "retire"),
    ]
    assert events[-2].before_json and events[-2].after_json and all(e.correlation_id for e in events)


def test_migration_clean_and_idempotent():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[models.SchoolGroup.__table__, models.Branch.__table__, models.AcademicYear.__table__, models.User.__table__])
    with engine.begin() as connection:
        db_migrations._talent_program_framework_foundation(engine, connection)
        db_migrations._talent_program_framework_foundation(engine, connection)
    expected = {"talent_programs", "talent_program_academic_year_configurations", "talent_program_framework_versions", "talent_competencies", "talent_framework_competencies", "talent_configuration_audits"}
    assert expected.issubset(inspect(engine).get_table_names())
    assert any(m.migration_id == "20260904_002_talent_program_framework_foundation" for m in db_migrations.MIGRATIONS)
