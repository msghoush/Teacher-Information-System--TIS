"""TIS Managed Student Number backend/service/API (ADR 0043, M2).

Covers: business-input format validation, canonical STD-prefixed storage,
atomic new-Student creation, legacy Student assignment, replacement
(retire-old/activate-new) semantics, M1 global-uniqueness enforcement
(same-tenant, cross-tenant, retired-value reuse, IntegrityError race path),
cross-tenant/same-tenant privacy-safe duplicate disclosure, permissions
(students.create / students.manage_identifiers), the managed-namespace
boundary on the generic external-identifier API, audit events, and targeted
regression for unrelated namespaces/workflows.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import models
import role_permission_service
from database import Base
from dependencies import get_db
from auth import get_current_user
from routers.students import router as students_router
from student_academic_service import (
    StudentAcademicError,
    add_external_identifier,
    canonical_student_number,
    create_placement,
    create_student,
    create_student_with_number,
    current_student_number,
    deactivate_external_identifier,
    find_student_number_holder,
    set_student_number,
    validate_student_number_digits,
)


NAMESPACE = "tis_student_number"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    db.commit()
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    db.commit()
    yield db
    db.close()


def _admin(db, *, user_id, school_group_id, branch_id, access_scope="ORGANIZATION"):
    user = models.User(
        user_id=user_id, username=f"admin.{user_id}", first_name="Admin", last_name=user_id,
        role="Administrator", user_type="TENANT", access_scope=access_scope,
        school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=100 if school_group_id == 1 else 200, is_active=True,
    )
    db.add(user)
    db.commit()
    user.scope_school_group_id = school_group_id
    user.scope_branch_id = branch_id
    user.scope_academic_year_id = 100 if school_group_id == 1 else 200
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _deny_students_view(db, *, school_group_id):
    """Give one tenant's Administrator role every default permission EXCEPT students.view."""
    baseline = role_permission_service.get_allowed_permission_keys(db, auth.ROLE_ADMINISTRATOR, school_group_id)
    assert "students.view" in baseline and "students.manage_identifiers" in baseline
    role_permission_service.apply_role_permission_overrides(
        db, role=auth.ROLE_ADMINISTRATOR, allowed_keys=baseline - {"students.view"},
        school_group_id=school_group_id, updated_by_user_id="0000000001",
    )
    db.commit()


# ---------------------------------------------------------------------------
# FORMAT validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "1234567890", "0012345678", "0000000001", "9999999999",
])
def test_format_accepts_exactly_ten_digits_and_preserves_leading_zeros(value):
    assert validate_student_number_digits(value) == value
    assert canonical_student_number(value) == f"STD{value}"


@pytest.mark.parametrize("value", [
    "123", "12345678901", "STD1234567890", "12345A7890", "12 34567890",
    "", None, "abcdefghij", "12345678.0", "１２３４５６７８９０",
])
def test_format_rejects_everything_else(value):
    with pytest.raises(StudentAcademicError) as exc_info:
        validate_student_number_digits(value)
    assert exc_info.value.code == "invalid_student_number"
    with pytest.raises(StudentAcademicError):
        canonical_student_number(value)


def test_canonical_formatter_never_accepts_a_client_supplied_prefix():
    with pytest.raises(StudentAcademicError):
        canonical_student_number("STD1234567890")


# ---------------------------------------------------------------------------
# CREATE: atomicity, canonical storage, mandatory number
# ---------------------------------------------------------------------------

def test_create_student_with_number_stores_canonical_value_and_is_readable(database):
    db = database
    student = create_student_with_number(
        db, school_group_id=1, student_number="0012345678",
        first_name="Lina", last_name="Saleh",
    )
    db.commit()
    assert current_student_number(db, school_group_id=1, student_id=student.id) == "STD0012345678"
    row = db.query(models.StudentExternalIdentifier).filter_by(
        school_group_id=1, student_id=student.id, namespace=NAMESPACE,
    ).one()
    assert row.value == "STD0012345678"
    assert row.status == "active"


def test_create_student_with_number_rejects_missing_or_invalid_number_before_any_write(database):
    db = database
    before_count = db.query(models.Student).count()
    with pytest.raises(StudentAcademicError) as exc_info:
        create_student_with_number(db, school_group_id=1, student_number=None, first_name="No", last_name="Number")
    assert exc_info.value.code == "invalid_student_number"
    with pytest.raises(StudentAcademicError):
        create_student_with_number(db, school_group_id=1, student_number="123", first_name="Bad", last_name="Format")
    assert db.query(models.Student).count() == before_count


def test_create_student_with_number_duplicate_leaves_no_orphan_student(database):
    db = database
    create_student_with_number(db, school_group_id=1, student_number="0000000009", first_name="First", last_name="Holder")
    db.commit()
    before_count = db.query(models.Student).count()
    with pytest.raises(IntegrityError):
        create_student_with_number(db, school_group_id=1, student_number="0000000009", first_name="Second", last_name="Orphan")
    db.rollback()
    assert db.query(models.Student).count() == before_count
    assert db.query(models.Student).filter_by(first_name="Second").first() is None


def test_api_new_student_creation_requires_and_stores_student_number(database):
    db = database
    user = _admin(db, user_id="1000000001", school_group_id=1, branch_id=10)
    client = _client(db, user)

    missing = client.post("/api/students", json={"first_name": "No", "last_name": "Number"})
    assert missing.status_code == 400
    assert missing.json()["code"] == "invalid_student_number"

    created = client.post("/api/students", json={
        "first_name": "Lina", "last_name": "Saleh", "student_number": "0012345678",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["student_number"] == "STD0012345678"

    fetched = client.get(f"/api/students/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["student_number"] == "STD0012345678"

    # Preserve current creation behavior for every unrelated field.
    assert body["first_name"] == "Lina" and body["last_name"] == "Saleh"


def test_api_duplicate_student_number_at_creation_leaves_no_orphan_student(database):
    db = database
    user = _admin(db, user_id="1000000002", school_group_id=1, branch_id=10)
    client = _client(db, user)
    first = client.post("/api/students", json={
        "first_name": "First", "last_name": "Holder", "student_number": "0000000011",
    })
    assert first.status_code == 201

    second = client.post("/api/students", json={
        "first_name": "Second", "last_name": "Orphan", "student_number": "0000000011",
    })
    assert second.status_code == 409
    assert second.json()["code"] == "student_number_unavailable"
    assert db.query(models.Student).filter_by(first_name="Second").first() is None


# ---------------------------------------------------------------------------
# LEGACY: no number required, may be added later
# ---------------------------------------------------------------------------

def test_legacy_student_without_number_reads_successfully(database):
    db = database
    legacy = create_student(db, school_group_id=1, first_name="Legacy", last_name="One")
    db.commit()
    user = _admin(db, user_id="1000000003", school_group_id=1, branch_id=10)
    client = _client(db, user)
    fetched = client.get(f"/api/students/{legacy.id}")
    assert fetched.status_code == 200
    assert fetched.json()["student_number"] is None


def test_legacy_student_can_receive_a_number_when_authorized(database):
    db = database
    legacy = create_student(db, school_group_id=1, first_name="Legacy", last_name="Two")
    db.commit()
    user = _admin(db, user_id="1000000004", school_group_id=1, branch_id=10)
    client = _client(db, user)
    response = client.put(f"/api/students/{legacy.id}/student-number", json={"student_number": "0000000021"})
    assert response.status_code == 200
    assert response.json()["student_number"] == "STD0000000021"
    assert current_student_number(db, school_group_id=1, student_id=legacy.id) == "STD0000000021"


# ---------------------------------------------------------------------------
# REPLACEMENT
# ---------------------------------------------------------------------------

def test_replacement_retires_old_activates_new_and_preserves_student_id(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000031", first_name="Rep", last_name="Lace")
    db.commit()
    student_id = student.id

    replaced = set_student_number(db, school_group_id=1, student_id=student_id, student_number="0000000032")
    db.commit()

    assert replaced.value == "STD0000000032"
    assert replaced.status == "active"

    rows = db.query(models.StudentExternalIdentifier).filter_by(
        school_group_id=1, student_id=student_id, namespace=NAMESPACE,
    ).order_by(models.StudentExternalIdentifier.id).all()
    assert [(row.value, row.status) for row in rows] == [
        ("STD0000000031", "inactive"), ("STD0000000032", "active"),
    ]
    # Student.id is unchanged by a number replacement.
    assert db.get(models.Student, student_id) is not None
    assert current_student_number(db, school_group_id=1, student_id=student_id) == "STD0000000032"


def test_old_replaced_value_remains_permanently_unavailable(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000041", first_name="Old", last_name="Value")
    db.commit()
    set_student_number(db, school_group_id=1, student_id=student.id, student_number="0000000042")
    db.commit()

    with pytest.raises(IntegrityError):
        create_student_with_number(db, school_group_id=1, student_number="0000000041", first_name="Cannot", last_name="Reuse")
    db.rollback()


def test_api_replacement_end_to_end(database):
    db = database
    user = _admin(db, user_id="1000000005", school_group_id=1, branch_id=10)
    client = _client(db, user)
    created = client.post("/api/students", json={
        "first_name": "Api", "last_name": "Replace", "student_number": "0000000051",
    })
    student_id = created.json()["id"]

    replaced = client.put(f"/api/students/{student_id}/student-number", json={"student_number": "0000000052"})
    assert replaced.status_code == 200
    assert replaced.json()["student_number"] == "STD0000000052"

    fetched = client.get(f"/api/students/{student_id}")
    assert fetched.json()["student_number"] == "STD0000000052"
    assert fetched.json()["id"] == student_id


# ---------------------------------------------------------------------------
# UNIQUENESS (global, same-tenant, cross-tenant, retired reuse, race)
# ---------------------------------------------------------------------------

def test_same_tenant_duplicate_is_rejected(database):
    db = database
    create_student_with_number(db, school_group_id=1, student_number="0000000061", first_name="A", last_name="One")
    db.commit()
    with pytest.raises(IntegrityError):
        create_student_with_number(db, school_group_id=1, student_number="0000000061", first_name="B", last_name="Two")
    db.rollback()


def test_cross_tenant_duplicate_is_rejected(database):
    db = database
    create_student_with_number(db, school_group_id=1, student_number="0000000071", first_name="A", last_name="One")
    db.commit()
    with pytest.raises(IntegrityError):
        create_student_with_number(db, school_group_id=2, student_number="0000000071", first_name="Foreign", last_name="Org")
    db.rollback()


def test_inactive_retired_value_cannot_be_reused_by_a_different_student(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000081", first_name="Ret", last_name="Ired")
    db.commit()
    set_student_number(db, school_group_id=1, student_id=student.id, student_number="0000000082")
    db.commit()
    other = create_student(db, school_group_id=1, first_name="Other", last_name="Student")
    db.commit()
    with pytest.raises(IntegrityError):
        set_student_number(db, school_group_id=1, student_id=other.id, student_number="0000000081")
    db.rollback()


def test_database_integrity_error_race_is_handled_safely_by_the_api(database):
    """Simulates a uniqueness race: another row already claims the value at the
    exact moment the API attempts its own insert, proving the IntegrityError
    path rolls back correctly and returns the generic conflict contract."""
    db = database
    user = _admin(db, user_id="1000000006", school_group_id=1, branch_id=10)
    client = _client(db, user)
    winner = create_student_with_number(db, school_group_id=1, student_number="0000000091", first_name="Winner", last_name="Race")
    db.commit()

    response = client.post("/api/students", json={
        "first_name": "Loser", "last_name": "Race", "student_number": "0000000091",
    })
    assert response.status_code == 409
    assert response.json()["code"] == "student_number_unavailable"
    # The session must be usable afterwards - rollback happened correctly.
    assert db.query(models.Student).filter_by(first_name="Loser").first() is None
    assert db.get(models.Student, winner.id) is not None


# ---------------------------------------------------------------------------
# PRIVACY: safe duplicate classification
# ---------------------------------------------------------------------------

def test_same_tenant_authorized_conflict_exposes_only_student_id_and_display_name(database):
    db = database
    holder = create_student_with_number(
        db, school_group_id=1, student_number="0000000101", first_name="Existing", father_name="Holder", last_name="Person",
    )
    db.commit()
    requester = _admin(db, user_id="1000000007", school_group_id=1, branch_id=10)
    client = _client(db, requester)

    response = client.post("/api/students", json={
        "first_name": "New", "last_name": "Applicant", "student_number": "0000000101",
    })
    assert response.status_code == 409
    payload = response.json()
    assert payload["code"] == "student_number_unavailable"
    assert payload["student_id"] == holder.id
    assert payload["display_name"] == "Existing Holder Person"
    # No other identifying metadata is present.
    assert set(payload) == {"detail", "code", "student_id", "display_name"}


def test_same_tenant_unauthorized_conflict_is_generic(database):
    db = database
    create_student_with_number(
        db, school_group_id=1, student_number="0000000111", first_name="Existing", last_name="Person",
    )
    db.commit()
    _deny_students_view(db, school_group_id=1)
    requester = _admin(db, user_id="1000000008", school_group_id=1, branch_id=10)
    client = _client(db, requester)

    response = client.put(f"/api/students/{_legacy_id(db, requester)}/student-number", json={"student_number": "0000000111"})
    payload = response.json()
    assert response.status_code == 409
    assert payload["code"] == "student_number_unavailable"
    assert set(payload) == {"detail", "code"}


def _legacy_id(db, requester):
    row = create_student(db, school_group_id=requester.scope_school_group_id, first_name="Legacy", last_name="Target")
    db.commit()
    return row.id


def test_cross_tenant_conflict_is_generic_and_reveals_no_organization_metadata(database):
    db = database
    foreign_holder = create_student_with_number(
        db, school_group_id=2, student_number="0000000121", first_name="Foreign", last_name="Holder",
    )
    db.commit()
    requester = _admin(db, user_id="1000000009", school_group_id=1, branch_id=10)
    client = _client(db, requester)

    response = client.post("/api/students", json={
        "first_name": "Local", "last_name": "Applicant", "student_number": "0000000121",
    })
    assert response.status_code == 409
    payload = response.json()
    assert payload["code"] == "student_number_unavailable"
    assert set(payload) == {"detail", "code"}
    assert str(foreign_holder.id) not in str(payload)
    assert "Foreign" not in str(payload)


def test_retired_value_conflict_classification_follows_the_same_authorization_rule(database):
    """A retired value is not a distinct disclosure category: the SAME
    same-tenant/authorized-vs-not rule governs it as any other conflict, so
    it cannot be used as a side channel to learn "this was retired" - the
    authorized case discloses the (still knowable) Student exactly like any
    other same-tenant conflict, and the unauthorized case is generic exactly
    like any other same-tenant conflict."""
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000131", first_name="R", last_name="One")
    db.commit()
    set_student_number(db, school_group_id=1, student_id=student.id, student_number="0000000132")
    db.commit()

    authorized = _admin(db, user_id="1000000010", school_group_id=1, branch_id=10)
    authorized_client = _client(db, authorized)
    authorized_response = authorized_client.post("/api/students", json={
        "first_name": "Cannot", "last_name": "Reuse", "student_number": "0000000131",
    })
    assert authorized_response.status_code == 409
    authorized_payload = authorized_response.json()
    assert authorized_payload["code"] == "student_number_unavailable"
    assert authorized_payload["student_id"] == student.id
    assert authorized_payload["display_name"] == "R One"

    _deny_students_view(db, school_group_id=1)
    unauthorized = _admin(db, user_id="1000000015", school_group_id=1, branch_id=10)
    unauthorized_client = _client(db, unauthorized)
    unauthorized_response = unauthorized_client.post("/api/students", json={
        "first_name": "Cannot", "last_name": "ReuseEither", "student_number": "0000000131",
    })
    assert unauthorized_response.status_code == 409
    unauthorized_payload = unauthorized_response.json()
    assert set(unauthorized_payload) == {"detail", "code"}
    assert unauthorized_payload["code"] == "student_number_unavailable"


# ---------------------------------------------------------------------------
# PERMISSIONS
# ---------------------------------------------------------------------------

def test_creating_a_student_still_requires_students_create_permission(database):
    db = database
    editor = models.User(
        user_id="1000000011", username="editor.one", first_name="Editor", last_name="One",
        role="Editor", user_type="TENANT", access_scope="BRANCH",
        school_group_id=1, branch_id=10, academic_year_id=100, is_active=True,
    )
    db.add(editor)
    db.commit()
    editor.scope_school_group_id = 1
    editor.scope_branch_id = 10
    editor.scope_academic_year_id = 100
    client = _client(db, editor)
    response = client.post("/api/students", json={
        "first_name": "Should", "last_name": "BeDenied", "student_number": "0000000141",
    })
    assert response.status_code == 403
    assert db.query(models.Student).filter_by(first_name="Should").first() is None


def test_managing_student_number_requires_manage_identifiers_permission(database):
    db = database
    legacy = create_student(db, school_group_id=1, first_name="Legacy", last_name="Number")
    db.commit()
    editor = models.User(
        user_id="1000000012", username="editor.two", first_name="Editor", last_name="Two",
        role="Editor", user_type="TENANT", access_scope="BRANCH",
        school_group_id=1, branch_id=10, academic_year_id=100, is_active=True,
    )
    db.add(editor)
    db.commit()
    editor.scope_school_group_id = 1
    editor.scope_branch_id = 10
    editor.scope_academic_year_id = 100
    client = _client(db, editor)
    response = client.put(f"/api/students/{legacy.id}/student-number", json={"student_number": "0000000151"})
    assert response.status_code == 403
    assert current_student_number(db, school_group_id=1, student_id=legacy.id) is None


def test_cross_tenant_actor_cannot_assign_a_number_to_a_foreign_student(database):
    db = database
    foreign_student = create_student(db, school_group_id=2, first_name="Foreign", last_name="Student")
    db.commit()
    requester = _admin(db, user_id="1000000013", school_group_id=1, branch_id=10)
    client = _client(db, requester)
    response = client.put(f"/api/students/{foreign_student.id}/student-number", json={"student_number": "0000000161"})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert current_student_number(db, school_group_id=2, student_id=foreign_student.id) is None


def test_global_uniqueness_lookup_does_not_grant_global_student_lookup(database):
    """find_student_number_holder is a bare data lookup, never a Student read API;
    the router only ever discloses identity after an explicit students.view check."""
    db = database
    holder = create_student_with_number(db, school_group_id=2, student_number="0000000171", first_name="Foreign", last_name="Org")
    db.commit()
    result = find_student_number_holder(db, canonical_value="STD0000000171")
    assert result == {"school_group_id": 2, "student_id": holder.id}
    # The raw result carries no name/display metadata by itself.
    assert "display_name" not in result and "first_name" not in result


# ---------------------------------------------------------------------------
# MANAGED NAMESPACE protection
# ---------------------------------------------------------------------------

def test_generic_identifier_create_cannot_create_the_managed_namespace(database):
    db = database
    student = create_student(db, school_group_id=1, first_name="Some", last_name="One")
    db.commit()
    with pytest.raises(StudentAcademicError) as exc_info:
        add_external_identifier(db, school_group_id=1, student_id=student.id, namespace=NAMESPACE, value="STD1234567890")
    assert exc_info.value.code == "managed_namespace"
    assert db.query(models.StudentExternalIdentifier).filter_by(namespace=NAMESPACE).first() is None


def test_generic_identifier_create_api_rejects_managed_namespace(database):
    db = database
    student = create_student(db, school_group_id=1, first_name="Some", last_name="One")
    db.commit()
    user = _admin(db, user_id="1000000014", school_group_id=1, branch_id=10)
    client = _client(db, user)
    response = client.post(f"/api/students/{student.id}/external-identifiers", json={
        "namespace": NAMESPACE, "value": "STD1234567890",
    })
    assert response.status_code == 400
    assert response.json()["code"] == "managed_namespace"


def test_generic_identifier_deactivate_cannot_touch_the_managed_namespace(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000181", first_name="M", last_name="Anaged")
    db.commit()
    row = db.query(models.StudentExternalIdentifier).filter_by(
        school_group_id=1, student_id=student.id, namespace=NAMESPACE,
    ).one()
    with pytest.raises(StudentAcademicError) as exc_info:
        deactivate_external_identifier(db, school_group_id=1, student_id=student.id, identifier_id=row.id)
    assert exc_info.value.code == "managed_namespace"
    assert db.get(models.StudentExternalIdentifier, row.id).status == "active"


def test_canonical_managed_service_still_operates_correctly_alongside_the_guard(database):
    db = database
    student = create_student(db, school_group_id=1, first_name="Canonical", last_name="Path")
    db.commit()
    row = set_student_number(db, school_group_id=1, student_id=student.id, student_number="0000000191")
    db.commit()
    assert row.status == "active"
    assert row.value == "STD0000000191"


# ---------------------------------------------------------------------------
# AUDIT
# ---------------------------------------------------------------------------

def test_creation_of_managed_number_is_audited(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000201", first_name="Audit", last_name="Create")
    db.commit()
    events = db.query(models.StudentAudit).filter_by(
        school_group_id=1, student_id=student.id, resource_type="external_identifier",
    ).order_by(models.StudentAudit.id).all()
    assert [event.action for event in events] == ["create"]


def test_assigning_a_number_to_a_legacy_student_is_audited(database):
    db = database
    legacy = create_student(db, school_group_id=1, first_name="Legacy", last_name="Audit")
    db.commit()
    set_student_number(db, school_group_id=1, student_id=legacy.id, student_number="0000000211")
    db.commit()
    events = db.query(models.StudentAudit).filter_by(
        school_group_id=1, student_id=legacy.id, resource_type="external_identifier",
    ).all()
    assert [event.action for event in events] == ["assign"]


def test_replacement_records_a_retire_and_an_assign_event(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000221", first_name="Rep", last_name="Audit")
    db.commit()
    set_student_number(db, school_group_id=1, student_id=student.id, student_number="0000000222")
    db.commit()
    events = db.query(models.StudentAudit).filter_by(
        school_group_id=1, student_id=student.id, resource_type="external_identifier",
    ).order_by(models.StudentAudit.id).all()
    assert [event.action for event in events] == ["create", "replace_retire", "replace"]


# ---------------------------------------------------------------------------
# REGRESSION
# ---------------------------------------------------------------------------

def test_unrelated_external_identifier_namespaces_are_unaffected(database):
    db = database
    student = create_student(db, school_group_id=1, first_name="Regress", last_name="Ion")
    db.commit()
    row = add_external_identifier(db, school_group_id=1, student_id=student.id, namespace="sis", value="SIS-001")
    db.commit()
    assert row.namespace == "sis" and row.status == "active"
    deactivate_external_identifier(db, school_group_id=1, student_id=student.id, identifier_id=row.id)
    db.commit()
    assert db.get(models.StudentExternalIdentifier, row.id).status == "inactive"


def test_existing_academic_placement_workflow_still_functions_for_a_managed_student(database):
    db = database
    student = create_student_with_number(db, school_group_id=1, student_number="0000000231", first_name="Placed", last_name="Student")
    db.commit()
    placement = create_placement(
        db, school_group_id=1, student_id=student.id, branch_id=10, academic_year_id=100,
        grade_level="3", section_name="C", effective_from=datetime(2026, 9, 1),
    )
    db.commit()
    assert placement.student_id == student.id
    assert current_student_number(db, school_group_id=1, student_id=student.id) == "STD0000000231"
