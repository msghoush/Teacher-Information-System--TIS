"""Student Learning Style four-dimension profile service/API (ADR 0042, M3;
OPERATIONALLY DEPRECATED as of M14 - see ADR 0042's M14 amendment section).

M3 implemented the server-side service/API for the four independent,
optional, integer 0-100 percentages introduced as a schema-only foundation
in M1 (``tests/test_student_learning_style_profile_foundation.py``):
``learning_style_verbal_percentage``, ``learning_style_non_verbal_percentage``,
``learning_style_quantitative_percentage``, ``learning_style_spatial_percentage``.

M14 owner correction: these four columns are corrected/superseded product
model (a misinterpretation of "percentage" as a per-Student dimension score,
when it was always meant as population/aggregate distribution). The
SERVICE-layer functions below (``student_academic_service.create_student``/
``update_student``) are intentionally left able to accept these fields, so
that any already-stored value is never silently rewritten by an unrelated
change and so the deprecated columns remain fully preserved/inspectable -
but the API/router layer (``routers/students.py``) no longer forwards them
from request bodies at all, so the CREATE/UPDATE API sections below assert
the field is silently ignored (never written, never a validation error),
not that it is still writable end-to-end. The SERVICE-level validation
sections (null/partial/0/100/no-sum-rule/invalid low/high/type) remain
accurate and unchanged, since they exercise the service layer directly.

M18a completes the deprecation for READ exposure: ``routers/students.py``'s
``_student_json`` and ``routers/students_ui.py``'s ``_student_view`` no
longer serialize any of the four fields in the current normal API/UI
projection at all (previously they were still echoed back, including as
literal ``null``). The CREATE/UPDATE/SERIALIZATION sections below were
updated accordingly to assert field absence from the response body, with a
direct DB-level (``get_student``) check proving the stored value and its
exact null/zero semantics remain completely untouched.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from dependencies import get_db
from auth import get_current_user
from routers.students import router as students_router
from student_academic_service import (
    LEARNING_STYLE_PERCENTAGE_FIELDS,
    StudentAcademicError,
    create_student,
    create_student_with_number,
    get_student,
    update_student,
)


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
    ])
    db.commit()
    yield db
    db.close()


_counter = [0]


def _next_student_number():
    _counter[0] += 1
    return f"{_counter[0]:010d}"


def _admin(db, *, user_id="1000000001", school_group_id=1, branch_id=10, access_scope="ORGANIZATION"):
    user = models.User(
        user_id=user_id, username=f"admin.{user_id}", first_name="Admin", last_name=user_id,
        role="Administrator", user_type="TENANT", access_scope=access_scope,
        school_group_id=school_group_id, branch_id=branch_id, academic_year_id=None, is_active=True,
    )
    db.add(user)
    db.commit()
    user.scope_school_group_id = school_group_id
    user.scope_branch_id = branch_id
    return user


def _editor(db, *, user_id="1000000002", school_group_id=1, branch_id=10):
    user = models.User(
        user_id=user_id, username=f"editor.{user_id}", first_name="Editor", last_name=user_id,
        role="Editor", user_type="TENANT", access_scope="BRANCH",
        school_group_id=school_group_id, branch_id=branch_id, academic_year_id=None, is_active=True,
    )
    db.add(user)
    db.commit()
    user.scope_school_group_id = school_group_id
    user.scope_branch_id = branch_id
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _create(db, **overrides):
    student = create_student_with_number(
        db, school_group_id=overrides.pop("school_group_id", 1),
        student_number=overrides.pop("student_number", None) or _next_student_number(),
        first_name=overrides.pop("first_name", "Maya"), last_name=overrides.pop("last_name", "Haddad"),
        **overrides,
    )
    db.commit()
    return student


# ---------------------------------------------------------------------------
# SERVICE: independent validation, null/partial/no-sum-rule, invalid values
# ---------------------------------------------------------------------------

def test_four_independent_values_persist_on_create(database):
    db = database
    student = _create(
        db,
        learning_style_verbal_percentage=72,
        learning_style_non_verbal_percentage=48,
        learning_style_quantitative_percentage=86,
        learning_style_spatial_percentage=None,
    )
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style_verbal_percentage == 72
    assert refreshed.learning_style_non_verbal_percentage == 48
    assert refreshed.learning_style_quantitative_percentage == 86
    assert refreshed.learning_style_spatial_percentage is None


def test_all_null_profile_is_valid_on_create(database):
    db = database
    student = _create(db)
    refreshed = get_student(db, 1, student.id)
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert getattr(refreshed, field) is None


@pytest.mark.parametrize("profile", [
    {"learning_style_verbal_percentage": 100, "learning_style_non_verbal_percentage": 100,
     "learning_style_quantitative_percentage": 100, "learning_style_spatial_percentage": 100},
    {"learning_style_verbal_percentage": 0, "learning_style_non_verbal_percentage": 0,
     "learning_style_quantitative_percentage": 0, "learning_style_spatial_percentage": 0},
    {"learning_style_verbal_percentage": 80, "learning_style_non_verbal_percentage": 20,
     "learning_style_quantitative_percentage": None, "learning_style_spatial_percentage": 95},
])
def test_boundary_and_no_sum_rule_profiles_are_accepted(database, profile):
    db = database
    student = _create(db, **profile)
    refreshed = get_student(db, 1, student.id)
    for field, expected in profile.items():
        assert getattr(refreshed, field) == expected


@pytest.mark.parametrize("value", [-1, 101, -50, 500])
@pytest.mark.parametrize("field", LEARNING_STYLE_PERCENTAGE_FIELDS)
def test_out_of_range_value_is_rejected(database, field, value):
    db = database
    with pytest.raises(StudentAcademicError) as exc_info:
        _create(db, **{field: value})
    assert exc_info.value.code == "invalid_learning_style_percentage"


@pytest.mark.parametrize("value", [50.5, True, False, "75", "abc", [], {}])
@pytest.mark.parametrize("field", LEARNING_STYLE_PERCENTAGE_FIELDS)
def test_invalid_type_is_rejected(database, field, value):
    db = database
    with pytest.raises(StudentAcademicError) as exc_info:
        _create(db, **{field: value})
    assert exc_info.value.code == "invalid_learning_style_percentage"


def test_invalid_dimension_prevents_student_creation_with_no_orphan_row(database):
    db = database
    before_count = db.query(models.Student).count()
    with pytest.raises(StudentAcademicError):
        _create(db, first_name="Orphan-Check", learning_style_verbal_percentage=101)
    db.rollback()
    after_count = db.query(models.Student).count()
    assert after_count == before_count


def test_update_one_dimension_does_not_corrupt_others(database):
    db = database
    student = _create(
        db,
        learning_style_verbal_percentage=10,
        learning_style_non_verbal_percentage=20,
        learning_style_quantitative_percentage=30,
        learning_style_spatial_percentage=40,
    )
    update_student(db, school_group_id=1, student_id=student.id, learning_style_verbal_percentage=99)
    db.commit()
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style_verbal_percentage == 99
    assert refreshed.learning_style_non_verbal_percentage == 20
    assert refreshed.learning_style_quantitative_percentage == 30
    assert refreshed.learning_style_spatial_percentage == 40


def test_update_multiple_dimensions_at_once(database):
    db = database
    student = _create(db)
    update_student(
        db, school_group_id=1, student_id=student.id,
        learning_style_verbal_percentage=1, learning_style_spatial_percentage=99,
    )
    db.commit()
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style_verbal_percentage == 1
    assert refreshed.learning_style_spatial_percentage == 99
    assert refreshed.learning_style_non_verbal_percentage is None
    assert refreshed.learning_style_quantitative_percentage is None


def test_update_can_explicitly_clear_a_dimension_to_null(database):
    db = database
    student = _create(db, learning_style_verbal_percentage=55)
    update_student(db, school_group_id=1, student_id=student.id, learning_style_verbal_percentage=None)
    db.commit()
    assert get_student(db, 1, student.id).learning_style_verbal_percentage is None


def test_update_unspecified_dimensions_are_left_untouched(database):
    db = database
    student = _create(db, learning_style_quantitative_percentage=77)
    # Update an unrelated field only; the percentage field is never passed.
    update_student(db, school_group_id=1, student_id=student.id, gender="female")
    db.commit()
    assert get_student(db, 1, student.id).learning_style_quantitative_percentage == 77


def test_update_rejects_invalid_value_without_mutating_valid_siblings(database):
    db = database
    student = _create(db, learning_style_verbal_percentage=10)
    with pytest.raises(StudentAcademicError):
        update_student(db, school_group_id=1, student_id=student.id, learning_style_non_verbal_percentage=101)
    db.rollback()
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style_verbal_percentage == 10


# ---------------------------------------------------------------------------
# LEGACY: categorical field preserved, never rewritten by the new profile
# ---------------------------------------------------------------------------

def test_legacy_categorical_field_is_untouched_by_percentage_create(database):
    db = database
    student = _create(db, learning_style="Visual", learning_style_verbal_percentage=90)
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style == "Visual"
    assert refreshed.learning_style_verbal_percentage == 90


def test_legacy_categorical_field_is_untouched_by_percentage_update(database):
    db = database
    student = _create(db, learning_style="Kinesthetic")
    update_student(db, school_group_id=1, student_id=student.id, learning_style_spatial_percentage=42)
    db.commit()
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style == "Kinesthetic"
    assert refreshed.learning_style_spatial_percentage == 42


def test_legacy_student_with_no_percentage_profile_remains_valid_and_readable(database):
    db = database
    # Uses the original create_student (no number), mirroring an existing
    # legacy Student created before this milestone.
    student = create_student(db, school_group_id=1, first_name="Legacy", last_name="Student")
    db.commit()
    refreshed = get_student(db, 1, student.id)
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert getattr(refreshed, field) is None
    assert refreshed.learning_style is None


# ---------------------------------------------------------------------------
# CREATE API
# ---------------------------------------------------------------------------

def test_api_create_no_longer_writes_the_four_dimensions_m14_correction(database):
    # M14 owner correction: the four percentage fields are operationally
    # deprecated - the API create route silently ignores them (never a 400)
    # and never writes them, rather than persisting a per-Student percentage.
    # M18a: the API response no longer serializes these fields at all (see
    # test_api_response_no_longer_exposes_the_four_fields_m18a for the
    # dedicated projection-removal proof), so absence from the body is the
    # correct current assertion here.
    db = database
    client = _client(db, _admin(db))
    response = client.post("/api/students", json={
        "first_name": "Rana", "last_name": "Amin", "student_number": _next_student_number(),
        "learning_style_verbal_percentage": 72, "learning_style_non_verbal_percentage": 48,
        "learning_style_quantitative_percentage": 86, "learning_style_spatial_percentage": 10,
    })
    assert response.status_code == 201
    body = response.json()
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert field not in body
    created = db.query(models.Student).filter_by(first_name="Rana").one()
    assert created.learning_style_verbal_percentage is None


def test_api_create_may_omit_all_four_dimensions(database):
    db = database
    client = _client(db, _admin(db))
    response = client.post("/api/students", json={
        "first_name": "Omar", "last_name": "Nasser", "student_number": _next_student_number(),
    })
    assert response.status_code == 201
    body = response.json()
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert field not in body


def test_api_create_still_requires_student_number_m2_regression(database):
    db = database
    client = _client(db, _admin(db))
    response = client.post("/api/students", json={
        "first_name": "No", "last_name": "Number",
        "learning_style_verbal_percentage": 50,
    })
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_student_number"


def test_api_create_silently_ignores_out_of_range_dimension_m14_correction(database):
    # M14 owner correction: since the API create route no longer forwards
    # these fields to the service at all, an out-of-range value is never
    # even validated - it is silently ignored and the Student is created
    # normally (this is the deprecated-field write-path being fully removed,
    # not a validation regression on a field that is still authoritative).
    db = database
    client = _client(db, _admin(db))
    before_count = db.query(models.Student).count()
    response = client.post("/api/students", json={
        "first_name": "Bad", "last_name": "Dimension", "student_number": _next_student_number(),
        "learning_style_quantitative_percentage": 101,
    })
    assert response.status_code == 201
    assert "learning_style_quantitative_percentage" not in response.json()
    assert db.query(models.Student).count() == before_count + 1


# ---------------------------------------------------------------------------
# UPDATE API: partial semantics, permissions, tenant isolation
# ---------------------------------------------------------------------------

def test_api_update_no_longer_writes_a_dimension_m14_correction(database):
    # M14 owner correction: a pre-existing stored percentage value survives
    # completely untouched through an API update that attempts to change it
    # - the field is silently ignored, never overwritten to the new value.
    # M18a: the API response no longer serializes these fields at all, so
    # the untouched-stored-value proof is asserted directly against the DB.
    db = database
    student = _create(
        db, learning_style_verbal_percentage=10, learning_style_non_verbal_percentage=20,
        learning_style_quantitative_percentage=30, learning_style_spatial_percentage=40,
    )
    client = _client(db, _admin(db))
    response = client.patch(f"/api/students/{student.id}", json={"learning_style_verbal_percentage": 99})
    assert response.status_code == 200
    body = response.json()
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert field not in body
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style_verbal_percentage == 10
    assert refreshed.learning_style_non_verbal_percentage == 20
    assert refreshed.learning_style_quantitative_percentage == 30
    assert refreshed.learning_style_spatial_percentage == 40


def test_api_update_ignores_multiple_dimensions_at_once_m14_correction(database):
    db = database
    student = _create(db)
    client = _client(db, _admin(db))
    response = client.patch(f"/api/students/{student.id}", json={
        "learning_style_verbal_percentage": 5, "learning_style_spatial_percentage": 95,
    })
    assert response.status_code == 200
    body = response.json()
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert field not in body
    refreshed = get_student(db, 1, student.id)
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert getattr(refreshed, field) is None


def test_api_update_does_not_clear_a_previously_set_dimension_m14_correction(database):
    db = database
    student = _create(db, learning_style_verbal_percentage=63)
    client = _client(db, _admin(db))
    response = client.patch(f"/api/students/{student.id}", json={"learning_style_verbal_percentage": None})
    assert response.status_code == 200
    assert "learning_style_verbal_percentage" not in response.json()
    assert get_student(db, 1, student.id).learning_style_verbal_percentage == 63


def test_api_update_ignores_an_out_of_range_value_rather_than_rejecting_m14_correction(database):
    db = database
    student = _create(db)
    client = _client(db, _admin(db))
    response = client.patch(f"/api/students/{student.id}", json={"learning_style_spatial_percentage": -1})
    assert response.status_code == 200
    assert "learning_style_spatial_percentage" not in response.json()
    assert get_student(db, 1, student.id).learning_style_spatial_percentage is None


def test_api_update_unauthorized_editor_is_denied(database):
    db = database
    student = _create(db)
    client = _client(db, _editor(db))
    response = client.patch(f"/api/students/{student.id}", json={"learning_style_verbal_percentage": 50})
    assert response.status_code == 403


def test_api_update_cross_tenant_student_is_denied(database):
    db = database
    student = _create(db, school_group_id=1)
    other_org_admin = _admin(db, user_id="1000000009", school_group_id=2, branch_id=20)
    client = _client(db, other_org_admin)
    response = client.patch(f"/api/students/{student.id}", json={"learning_style_verbal_percentage": 50})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# SERIALIZATION
# ---------------------------------------------------------------------------

def test_api_response_no_longer_exposes_the_four_fields_m18a(database):
    # M18a: completes the M14 operational deprecation - the current normal
    # Student API projection (routers/students.py _student_json) no longer
    # serializes any of the four fields at all, regardless of stored value
    # (null, zero, or a real number). The stored columns and their exact
    # null/zero semantics remain fully intact and are asserted directly
    # against the DB, not the API response.
    db = database
    student = _create(
        db, learning_style_verbal_percentage=0, learning_style_non_verbal_percentage=100,
        learning_style_quantitative_percentage=None, learning_style_spatial_percentage=50,
    )
    client = _client(db, _admin(db))
    response = client.get(f"/api/students/{student.id}")
    assert response.status_code == 200
    body = response.json()
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        assert field not in body
    refreshed = get_student(db, 1, student.id)
    assert refreshed.learning_style_verbal_percentage == 0
    assert refreshed.learning_style_non_verbal_percentage == 100
    assert refreshed.learning_style_quantitative_percentage is None
    assert refreshed.learning_style_spatial_percentage == 50


def test_api_response_has_no_dominant_style_total_or_normalized_field(database):
    db = database
    student = _create(db, learning_style_verbal_percentage=80, learning_style_non_verbal_percentage=20)
    client = _client(db, _admin(db))
    body = client.get(f"/api/students/{student.id}").json()
    forbidden_keys = {
        "learning_style_dominant", "dominant_learning_style", "learning_style_total",
        "learning_style_normalized", "learning_style_percentage_total",
    }
    assert forbidden_keys.isdisjoint(body.keys())


def test_api_response_retains_legacy_categorical_field(database):
    db = database
    student = _create(db, learning_style="Auditory", learning_style_verbal_percentage=10)
    client = _client(db, _admin(db))
    body = client.get(f"/api/students/{student.id}").json()
    assert body["learning_style"] == "Auditory"
    assert "learning_style_verbal_percentage" not in body


# ---------------------------------------------------------------------------
# AUDIT
# ---------------------------------------------------------------------------

def test_percentage_update_participates_in_existing_student_audit(database):
    db = database
    student = _create(db, learning_style_verbal_percentage=10)
    update_student(db, school_group_id=1, student_id=student.id, learning_style_verbal_percentage=88)
    db.commit()
    audit_rows = db.query(models.StudentAudit).filter_by(
        school_group_id=1, student_id=student.id, resource_type="student", action="update",
    ).order_by(models.StudentAudit.id.desc()).all()
    assert audit_rows, "expected an existing-audit-mechanism row for the percentage update"
    latest = audit_rows[0]
    before = json.loads(latest.before_json)
    after = json.loads(latest.after_json)
    assert before["learning_style_verbal_percentage"] == 10
    assert after["learning_style_verbal_percentage"] == 88


# ---------------------------------------------------------------------------
# TALENT REGRESSION: zero scoring/eligibility dependency
# ---------------------------------------------------------------------------

def test_no_talent_module_reads_the_four_percentage_fields_or_this_services_helper():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    modules = (
        "talent_program_service.py",
        "talent_analytics_service.py",
        "talent_org_intelligence_service.py",
        "talent_analytics_privacy.py",
        "talent_student_assessment_service.py",
        "routers/talent_assessments.py",
        "routers/talent_review_candidates.py",
        "routers/talent_assessment_cycles.py",
        "routers/talent_programs.py",
    )
    checked = 0
    for relative in modules:
        path = root / relative
        if not path.exists():
            continue
        checked += 1
        source = path.read_text(encoding="utf-8")
        for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
            assert field not in source, f"{relative} must never read {field}"
        assert "_clean_learning_style_percentage" not in source
    assert checked >= 5
