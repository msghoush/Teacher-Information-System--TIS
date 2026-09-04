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
from database import Base
from dependencies import get_db
from auth import get_current_user
from routers.students import router as students_router
from student_academic_service import (
    StudentAcademicError, add_external_identifier, correct_placement, create_placement, create_student,
    deactivate_external_identifier, end_placement, get_student, list_placements, list_students,
    resolve_placement, transition_placement, update_student,
)


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")]); db.commit()
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=101, school_group_id=1, year_name="2027-2028"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ]); db.commit()
    db.add_all([
        models.PlanningSection(id=1000, branch_id=10, academic_year_id=100, grade_level="1", section_name="A", class_status="Current"),
        models.PlanningSection(id=1001, branch_id=10, academic_year_id=100, grade_level="2", section_name="B", class_status="Current"),
        models.PlanningSection(id=1002, branch_id=11, academic_year_id=101, grade_level="3", section_name="C", class_status="New"),
        models.PlanningSection(id=2000, branch_id=20, academic_year_id=200, grade_level="4", section_name="D", class_status="Current"),
    ]); db.commit()
    yield engine, db
    db.close()


def _student(db, group=1, first="Maya"):
    row = create_student(db, school_group_id=group, first_name=first, father_name="Samir", last_name="Haddad", gender="female")
    db.commit(); return row


def test_student_crud_search_status_audit_and_tenant_non_enumeration(database):
    _, db = database
    student = _student(db)
    assert get_student(db, 1, student.id).first_name == "Maya"
    assert get_student(db, 2, student.id) is None
    update_student(db, school_group_id=1, student_id=student.id, first_name="Mia", status="inactive")
    db.commit()
    assert [row.id for row in list_students(db, school_group_id=1, search="mia", status="inactive")] == [student.id]
    assert list_students(db, school_group_id=2, search="mia") == []
    assert [row.action for row in db.query(models.StudentAudit).order_by(models.StudentAudit.id)] == ["create", "status_change"]


def test_external_identifier_uniqueness_is_tenant_scoped_and_relation_is_guarded(database):
    _, db = database
    one, two = _student(db, 1), _student(db, 2, "Rami")
    identifier = add_external_identifier(db, school_group_id=1, student_id=one.id, namespace="sis", value="ABC")
    add_external_identifier(db, school_group_id=2, student_id=two.id, namespace="sis", value="ABC")
    db.commit()
    with pytest.raises(StudentAcademicError, match="already exists"):
        add_external_identifier(db, school_group_id=1, student_id=one.id, namespace="sis", value="ABC")
    db.rollback()
    deactivate_external_identifier(db, school_group_id=1, student_id=one.id, identifier_id=identifier.id)
    db.commit()
    assert identifier.status == "inactive"
    db.add(models.StudentExternalIdentifier(school_group_id=2, student_id=one.id, namespace="legacy", value="X"))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


def test_placement_snapshot_resolvers_order_and_planning_mutation_independence(database):
    _, db = database
    student = _student(db)
    first = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10,
        academic_year_id=100, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    db.commit()
    assert (first.grade_level, first.section_name) == ("1", "A")
    section = db.get(models.PlanningSection, 1000); section.grade_level = "9"; section.section_name = "Z"; db.commit()
    resolved = resolve_placement(db, school_group_id=1, student_id=student.id, at=datetime(2026, 10, 1))
    assert (resolved.grade_level, resolved.section_name) == ("1", "A")
    _, second = transition_placement(db, school_group_id=1, student_id=student.id, placement_id=first.id,
        transition_at=datetime(2027, 9, 1), branch_id=11, academic_year_id=101, planning_section_id=1002)
    db.commit()
    assert [(row.grade_level, row.section_name) for row in list_placements(db, school_group_id=1, student_id=student.id)] == [("1", "A"), ("3", "C")]
    assert resolve_placement(db, school_group_id=1, student_id=student.id, at=datetime(2027, 10, 1), academic_year_id=101).id == second.id


def test_section_grade_branch_changes_and_withdrawal_reentry_preserve_segments(database):
    _, db = database
    student = _student(db)
    p1 = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    _, p2 = transition_placement(db, school_group_id=1, student_id=student.id, placement_id=p1.id,
        transition_at=datetime(2027, 1, 1), branch_id=10, academic_year_id=100, planning_section_id=1001)
    end_placement(db, school_group_id=1, student_id=student.id, placement_id=p2.id, effective_to=datetime(2027, 3, 1))
    p3 = create_placement(db, school_group_id=1, student_id=student.id, branch_id=11, academic_year_id=101,
        grade_level="03", section_name="Re-entry", effective_from=datetime(2027, 9, 1))
    db.commit()
    history = list_placements(db, school_group_id=1, student_id=student.id)
    assert [(p.grade_level, p.section_name, p.branch_id) for p in history] == [("1", "A", 10), ("2", "B", 10), ("3", "Re-entry", 11)]
    assert resolve_placement(db, school_group_id=1, student_id=student.id, at=datetime(2027, 4, 1)) is None
    assert p3.status == "active"


def test_overlap_range_grade_and_foreign_scope_rejections(database):
    _, db = database
    student = _student(db)
    create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        planning_section_id=1000, effective_from=datetime(2026, 9, 1), effective_to=datetime(2027, 1, 1))
    with pytest.raises(StudentAcademicError) as overlap:
        create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
            grade_level="1", section_name="B", effective_from=datetime(2026, 12, 1))
    assert overlap.value.code == "placement_overlap"
    with pytest.raises(StudentAcademicError) as invalid_range:
        create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
            grade_level="1", section_name="B", effective_from=datetime(2028, 1, 2), effective_to=datetime(2028, 1, 1))
    assert invalid_range.value.code == "invalid_effective_range"
    for kwargs in ({"branch_id": 20, "academic_year_id": 100}, {"branch_id": 10, "academic_year_id": 200}):
        with pytest.raises(StudentAcademicError) as foreign:
            create_placement(db, school_group_id=1, student_id=student.id, planning_section_id=None,
                grade_level="1", section_name="X", effective_from=datetime(2028, 1, 1), **kwargs)
        assert foreign.value.code == "invalid_scope"
    with pytest.raises(StudentAcademicError) as section:
        create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
            planning_section_id=1002, effective_from=datetime(2028, 1, 1))
    assert section.value.code == "invalid_section_scope"
    with pytest.raises(StudentAcademicError):
        create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
            grade_level="13", section_name="X", effective_from=datetime(2028, 1, 1))


def test_half_open_boundary_and_backdated_gap_insertion(database):
    _, db = database
    student = _student(db)
    first = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        grade_level="1", section_name="A", effective_from=datetime(2026, 9, 1), effective_to=datetime(2026, 10, 1))
    # Independently created (not via transition_placement) placement starting exactly when the
    # prior one ends must be treated as non-overlapping under half-open [from, to) semantics.
    second = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        grade_level="2", section_name="B", effective_from=datetime(2026, 10, 1), effective_to=datetime(2026, 10, 15))
    db.commit()
    assert second.effective_from == first.effective_to
    third = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        grade_level="4", section_name="D", effective_from=datetime(2026, 11, 1), effective_to=datetime(2027, 1, 1))
    db.commit()
    # A backdated placement inserted strictly inside the genuine gap between two already
    # closed historical placements (2026-10-15 -> 2026-11-01) must succeed.
    gap_fill = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        grade_level="9", section_name="Z", effective_from=datetime(2026, 10, 20), effective_to=datetime(2026, 10, 25))
    db.commit()
    assert gap_fill.id is not None
    # A new open-ended placement sharing the exact same start instant as an existing closed
    # placement must still conflict with it.
    with pytest.raises(StudentAcademicError) as same_start:
        create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
            grade_level="3", section_name="C", effective_from=third.effective_from)
    assert same_start.value.code == "placement_overlap"


def test_planning_section_delete_nulls_provenance_but_keeps_snapshot(database):
    _, db = database
    student = _student(db)
    row = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        planning_section_id=1000, effective_from=datetime(2026, 9, 1)); db.commit()
    db.delete(db.get(models.PlanningSection, 1000)); db.commit(); db.refresh(row)
    assert row.planning_section_id is None
    assert (row.grade_level, row.section_name) == ("1", "A")


def test_audit_is_append_only_in_service_and_preserves_before_after(database):
    _, db = database
    student = _student(db)
    row = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        planning_section_id=1000, effective_from=datetime(2026, 9, 1)); db.commit()
    end_placement(db, school_group_id=1, student_id=student.id, placement_id=row.id, effective_to=datetime(2027, 1, 1)); db.commit()
    audits = db.query(models.StudentAudit).order_by(models.StudentAudit.id).all()
    assert [a.action for a in audits] == ["create", "create", "end"]
    assert '"effective_to": null' in audits[2].before_json
    assert "2027-01-01" in audits[2].after_json


def test_governed_correction_revalidates_scope_snapshot_and_overlap(database):
    _, db = database
    student = _student(db)
    row = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        planning_section_id=1000, effective_from=datetime(2026, 9, 1), effective_to=datetime(2027, 1, 1))
    corrected = correct_placement(db, school_group_id=1, student_id=student.id, placement_id=row.id,
        branch_id=10, academic_year_id=100, planning_section_id=1001,
        grade_level="12", section_name="ignored", effective_from=datetime(2026, 9, 2),
        effective_to=datetime(2027, 1, 2), reason="source correction")
    db.commit()
    assert (corrected.grade_level, corrected.section_name) == ("2", "B")
    audit = db.query(models.StudentAudit).filter_by(action="correction").one()
    assert '"section_name": "A"' in audit.before_json and '"section_name": "B"' in audit.after_json


def test_migration_is_registered_additive_and_idempotent():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine, tables=[
        models.SchoolGroup.__table__, models.Branch.__table__, models.AcademicYear.__table__,
        models.User.__table__, models.PlanningSection.__table__,
    ])
    assert "students" not in inspect(engine).get_table_names()
    with engine.begin() as connection:
        db_migrations._student_academic_placement_foundation(engine, connection)
        db_migrations._student_academic_placement_foundation(engine, connection)
    assert {"students", "student_external_identifiers", "student_academic_placements", "student_audits"}.issubset(inspect(engine).get_table_names())
    assert any(m.migration_id == "20260904_001_student_academic_placement_foundation" for m in db_migrations.MIGRATIONS)


def test_api_is_tenant_scoped_and_branch_actor_cannot_forge_branch(database):
    _, db = database
    user = models.User(user_id="1000000001", username="student.admin", first_name="Admin", last_name="One",
        role="Administrator", user_type="TENANT", access_scope="BRANCH", school_group_id=1,
        branch_id=10, academic_year_id=100, is_active=True)
    db.add(user); db.commit()
    user.scope_school_group_id = 1; user.scope_branch_id = 10; user.scope_academic_year_id = 100
    app = FastAPI(); app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        created = client.post("/api/students", json={"first_name": "Lina", "last_name": "Saleh"})
        assert created.status_code == 201
        student_id = created.json()["id"]
        assert client.get(f"/api/students/{student_id}").status_code == 200
        denied = client.post(f"/api/students/{student_id}/placements", json={
            "branch_id": 11, "academic_year_id": 101, "grade_level": "3", "section_name": "C",
            "effective_from": "2027-09-01",
        })
        assert denied.status_code == 403
        foreign = _student(db, 2, "Foreign")
        assert client.get(f"/api/students/{foreign.id}").status_code == 404


def test_editor_role_default_planning_permission_no_longer_authorizes_student_management(database):
    # Editor/User roles default-grant the broad, commonly-assigned planning.edit_section
    # permission, but must not receive the dedicated students.* keys by default: this is
    # the Checkpoint A fix confirming Student identity/placement management follows the
    # same Administrator-only-by-default governance pattern as the Users module.
    _, db = database
    editor_user = models.User(user_id="1000000003", username="editor.branch10", first_name="Editor", last_name="Ten",
        role="Editor", user_type="TENANT", access_scope="BRANCH", school_group_id=1,
        branch_id=10, academic_year_id=100, is_active=True)
    db.add(editor_user); db.commit()
    editor_user.scope_school_group_id = 1; editor_user.scope_branch_id = 10; editor_user.scope_academic_year_id = 100
    app = FastAPI(); app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: editor_user
    with TestClient(app) as client:
        denied_create = client.post("/api/students", json={"first_name": "Should", "last_name": "BeDenied"})
        assert denied_create.status_code == 403
        denied_view = client.get("/api/students")
        assert denied_view.status_code == 403
    assert list_students(db, school_group_id=1, search="Should") == []


def test_branch_scoped_actor_cannot_end_correct_or_transition_a_foreign_branch_placement(database):
    _, db = database
    student = _student(db)
    placement = create_placement(db, school_group_id=1, student_id=student.id, branch_id=11,
        academic_year_id=101, planning_section_id=1002, effective_from=datetime(2026, 9, 1))
    db.commit()
    user = models.User(user_id="1000000002", username="branch10.admin", first_name="Admin", last_name="Ten",
        role="Administrator", user_type="TENANT", access_scope="BRANCH", school_group_id=1,
        branch_id=10, academic_year_id=100, is_active=True)
    db.add(user); db.commit()
    user.scope_school_group_id = 1; user.scope_branch_id = 10; user.scope_academic_year_id = 100
    app = FastAPI(); app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        end = client.post(f"/api/students/{student.id}/placements/{placement.id}/end",
            json={"effective_to": "2027-01-01"})
        assert end.status_code == 403
        correct = client.patch(f"/api/students/{student.id}/placements/{placement.id}", json={
            "branch_id": 10, "academic_year_id": 100, "grade_level": "1", "section_name": "A",
            "effective_from": "2026-09-01",
        })
        assert correct.status_code == 403
        transition = client.post(f"/api/students/{student.id}/placements/{placement.id}/transition", json={
            "branch_id": 10, "academic_year_id": 100, "grade_level": "1", "section_name": "A",
            "transition_at": "2027-01-01",
        })
        assert transition.status_code == 403
    assert db.get(models.StudentAcademicPlacement, placement.id).branch_id == 11


def test_placement_reads_use_historical_branch_scope_without_transfer_reinterpretation(database):
    _, db = database
    student = _student(db)
    branch_a = create_placement(db, school_group_id=1, student_id=student.id, branch_id=10,
        academic_year_id=100, planning_section_id=1000, effective_from=datetime(2026, 9, 1))
    _, branch_b = transition_placement(db, school_group_id=1, student_id=student.id, placement_id=branch_a.id,
        transition_at=datetime(2027, 9, 1), branch_id=11, academic_year_id=101, planning_section_id=1002)
    branch_user = models.User(user_id="1000000004", username="branch10.viewer", first_name="Branch", last_name="Viewer",
        role="Administrator", user_type="TENANT", access_scope="BRANCH", school_group_id=1,
        branch_id=10, academic_year_id=100, is_active=True)
    organization_user = models.User(user_id="1000000005", username="org.viewer", first_name="Organization", last_name="Viewer",
        role="Administrator", user_type="TENANT", access_scope="ORGANIZATION", school_group_id=1,
        branch_id=10, academic_year_id=100, is_active=True)
    db.add_all([branch_user, organization_user]); db.commit()
    app = FastAPI(); app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: branch_user
    with TestClient(app) as client:
        assert [row["id"] for row in client.get(f"/api/students/{student.id}/placements").json()] == [branch_a.id]
        assert client.get(f"/api/students/{student.id}/placements/{branch_a.id}").status_code == 200
        hidden = client.get(f"/api/students/{student.id}/placements/{branch_b.id}")
        assert hidden.status_code == 404 and hidden.json()["code"] == "not_found"
        assert client.get(f"/api/students/{student.id}/placements/effective", params={"at": "2027-10-01", "academic_year_id": 101}).status_code == 404
        # Positive case: the same actor's own authorized historical Branch interval
        # still resolves correctly (the fix must not become deny-everything).
        own_effective = client.get(f"/api/students/{student.id}/placements/effective",
                                   params={"at": "2026-10-01", "academic_year_id": 100})
        assert own_effective.status_code == 200 and own_effective.json()["id"] == branch_a.id
        # Cross-tenant Student id must remain a uniform non-enumerating 404 on every
        # direct placement-read route, unchanged by the historical Branch fix.
        foreign_student = _student(db, group=2, first="Foreign")
        assert client.get(f"/api/students/{foreign_student.id}/placements").status_code == 404
        assert client.get(f"/api/students/{foreign_student.id}/placements/{branch_a.id}").status_code == 404
        assert client.get(f"/api/students/{foreign_student.id}/placements/effective",
                          params={"at": "2026-10-01", "academic_year_id": 100}).status_code == 404
    app.dependency_overrides[get_current_user] = lambda: organization_user
    with TestClient(app) as client:
        assert [row["id"] for row in client.get(f"/api/students/{student.id}/placements").json()] == [branch_a.id, branch_b.id]
        assert client.get(f"/api/students/{student.id}/placements/effective", params={"at": "2027-10-01", "academic_year_id": 101}).json()["id"] == branch_b.id
