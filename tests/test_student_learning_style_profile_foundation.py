"""Student Learning Style four-dimension profile (ADR 0042) schema foundation.

M1 scope: schema/migration only. No API, service write path, or frontend
exists yet - these tests exercise the ORM model and migration function
directly, proving the four independent percentages are nullable, bounded
0-100 with no sum rule, and that the legacy categorical ``learning_style``
column is completely preserved and untouched.

OPERATIONALLY DEPRECATED as of M14 (see ADR 0042's M14 amendment section):
these columns are no longer written/exposed/read anywhere in the product,
but remain schema-present and are preserved completely untouched - this
file's schema/migration/ORM-level coverage below remains accurate and is
left unchanged.
"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from database import Base


PROFILE_COLUMNS = (
    "learning_style_verbal_percentage",
    "learning_style_non_verbal_percentage",
    "learning_style_quantitative_percentage",
    "learning_style_spatial_percentage",
)


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(models.SchoolGroup(id=1, name="One"))
    db.commit()
    yield db
    db.close()


def _student(db, student_id, **overrides):
    row = models.Student(
        id=student_id, school_group_id=1, first_name="Maya", last_name="Haddad",
        status="active", **overrides,
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_migration_is_registered_additive_and_idempotent():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE students (id INTEGER PRIMARY KEY, school_group_id INTEGER NOT NULL, "
            "first_name VARCHAR(100) NOT NULL, father_name VARCHAR(100), last_name VARCHAR(100) NOT NULL, "
            "gender VARCHAR(24), status VARCHAR(16) NOT NULL DEFAULT 'active', "
            "learning_style VARCHAR(20), "
            "created_at DATETIME, updated_at DATETIME, created_by_user_id VARCHAR(10), updated_by_user_id VARCHAR(10))"
        ))
    columns_before = {c["name"] for c in inspect(engine).get_columns("students")}
    for column in PROFILE_COLUMNS:
        assert column not in columns_before

    with engine.begin() as connection:
        db_migrations._student_learning_style_four_dimension_profile(engine, connection)
        db_migrations._student_learning_style_four_dimension_profile(engine, connection)  # idempotent

    columns_after = {c["name"]: c for c in inspect(engine).get_columns("students")}
    for column in PROFILE_COLUMNS:
        assert column in columns_after
        assert columns_after[column]["nullable"] is True
    # Legacy categorical column and every pre-existing column are untouched.
    assert "learning_style" in columns_after
    assert {"id", "school_group_id", "first_name", "last_name", "status"}.issubset(columns_after)
    assert any(
        m.migration_id == "20260922_001_student_learning_style_four_dimension_profile"
        for m in db_migrations.MIGRATIONS
    )


def test_migration_is_a_no_op_when_students_table_is_missing():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        # Must not raise even though "students" does not exist yet.
        db_migrations._student_learning_style_four_dimension_profile(engine, connection)


# ---------------------------------------------------------------------------
# ORM-level range/nullability/independence
# ---------------------------------------------------------------------------

def test_all_four_fields_are_nullable_by_default(database):
    student = _student(database, 1)
    for column in PROFILE_COLUMNS:
        assert getattr(student, column) is None


def test_zero_and_one_hundred_are_valid_boundary_values(database):
    student = _student(
        database, 2,
        learning_style_verbal_percentage=0,
        learning_style_non_verbal_percentage=100,
        learning_style_quantitative_percentage=0,
        learning_style_spatial_percentage=100,
    )
    database.commit()
    refreshed = database.get(models.Student, student.id)
    assert refreshed.learning_style_verbal_percentage == 0
    assert refreshed.learning_style_non_verbal_percentage == 100
    assert refreshed.learning_style_quantitative_percentage == 0
    assert refreshed.learning_style_spatial_percentage == 100


def test_values_are_independent_and_never_required_to_sum_to_100(database):
    # 10 + 10 + 10 + 10 = 40, nowhere near 100 - must still be accepted.
    student = _student(
        database, 3,
        learning_style_verbal_percentage=10,
        learning_style_non_verbal_percentage=10,
        learning_style_quantitative_percentage=10,
        learning_style_spatial_percentage=10,
    )
    database.commit()
    refreshed = database.get(models.Student, student.id)
    assert refreshed.learning_style_verbal_percentage == 10
    assert refreshed.learning_style_non_verbal_percentage == 10
    assert refreshed.learning_style_quantitative_percentage == 10
    assert refreshed.learning_style_spatial_percentage == 10

    # One field set, the other three left NULL - independence.
    solo = _student(database, 4, learning_style_spatial_percentage=77)
    database.commit()
    refreshed_solo = database.get(models.Student, solo.id)
    assert refreshed_solo.learning_style_spatial_percentage == 77
    assert refreshed_solo.learning_style_verbal_percentage is None
    assert refreshed_solo.learning_style_non_verbal_percentage is None
    assert refreshed_solo.learning_style_quantitative_percentage is None


@pytest.mark.parametrize("column", PROFILE_COLUMNS)
def test_negative_value_is_rejected(database, column):
    with pytest.raises(IntegrityError):
        _student(database, 5, **{column: -1})
    database.rollback()


@pytest.mark.parametrize("column", PROFILE_COLUMNS)
def test_value_above_100_is_rejected(database, column):
    with pytest.raises(IntegrityError):
        _student(database, 6, **{column: 101})
    database.rollback()


def test_legacy_categorical_learning_style_is_preserved_and_independent(database):
    student = _student(
        database, 7, learning_style="Visual",
        learning_style_verbal_percentage=88,
    )
    database.commit()
    refreshed = database.get(models.Student, student.id)
    # Both the legacy categorical value and the new percentage coexist -
    # neither is derived from, nor overwrites, the other.
    assert refreshed.learning_style == "Visual"
    assert refreshed.learning_style_verbal_percentage == 88
    assert refreshed.learning_style_non_verbal_percentage is None


def test_no_talent_scoring_or_eligibility_module_reads_the_new_percentage_columns():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    modules = (
        "talent_program_service.py",
        "talent_analytics_service.py",
        "talent_org_intelligence_service.py",
        "talent_analytics_privacy.py",
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
        for column in PROFILE_COLUMNS:
            assert column not in source, f"{relative} must never read {column}"
    assert checked >= 5
