"""TIS Student Number global managed-identifier invariant (ADR 0043) foundation.

M1 scope: schema/migration only. There is no Student ID create/edit
API/service yet, so these tests exercise the ORM model and migration
function directly: existing tenant-scoped uniqueness for every other
namespace is unchanged, ``tis_student_number`` is globally unique
(including inactive/retired rows), and at most one row per Student may be
``active``.
"""

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from database import Base


NAMESPACE = "tis_student_number"


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
        models.Student(id=100, school_group_id=1, first_name="A", last_name="One", status="active"),
        models.Student(id=200, school_group_id=1, first_name="B", last_name="Two", status="active"),
        models.Student(id=300, school_group_id=2, first_name="C", last_name="Three", status="active"),
    ])
    db.commit()
    yield db
    db.close()


def _identifier(db, *, student_id, school_group_id, namespace, value, status="active"):
    row = models.StudentExternalIdentifier(
        school_group_id=school_group_id, student_id=student_id,
        namespace=namespace, value=value, status=status,
    )
    db.add(row)
    return row


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _bare_engine_with_students_and_identifiers():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE students (id INTEGER PRIMARY KEY, school_group_id INTEGER NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE student_external_identifiers (id INTEGER PRIMARY KEY, "
            "school_group_id INTEGER NOT NULL, student_id INTEGER NOT NULL, "
            "namespace VARCHAR(80) NOT NULL, value VARCHAR(180) NOT NULL, "
            "source VARCHAR(120), status VARCHAR(16) NOT NULL DEFAULT 'active', "
            "created_at DATETIME, updated_at DATETIME)"
        ))
    return engine


def test_migration_is_registered_additive_and_idempotent():
    engine = _bare_engine_with_students_and_identifiers()
    assert not db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_student_number_value",
    )
    with engine.begin() as connection:
        db_migrations._student_tis_number_identifier_integrity(engine, connection)
        db_migrations._student_tis_number_identifier_integrity(engine, connection)  # idempotent
    assert db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_student_number_value",
    )
    assert db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_number_active_student",
    )
    assert any(
        m.migration_id == "20260922_002_student_tis_number_identifier_integrity"
        for m in db_migrations.MIGRATIONS
    )


def test_migration_is_a_no_op_when_table_is_missing():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        db_migrations._student_tis_number_identifier_integrity(engine, connection)


def test_migration_fails_safely_on_non_canonical_existing_value():
    engine = _bare_engine_with_students_and_identifiers()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO student_external_identifiers "
            "(school_group_id, student_id, namespace, value, status) "
            "VALUES (1, 1, :ns, 'NOT-CANONICAL', 'active')"
        ), {"ns": NAMESPACE})
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="canonical"):
            db_migrations._student_tis_number_identifier_integrity(engine, connection)
    # Fails safely: neither index is installed and the offending row is untouched.
    assert not db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_student_number_value",
    )
    with engine.begin() as connection:
        remaining = connection.execute(text(
            "SELECT value FROM student_external_identifiers WHERE namespace = :ns"
        ), {"ns": NAMESPACE}).scalar()
    assert remaining == "NOT-CANONICAL"


def test_migration_fails_safely_on_duplicate_value_across_school_groups():
    engine = _bare_engine_with_students_and_identifiers()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO student_external_identifiers "
            "(school_group_id, student_id, namespace, value, status) "
            "VALUES (1, 1, :ns, 'STD1234567890', 'active'), "
            "(2, 2, :ns, 'STD1234567890', 'active')"
        ), {"ns": NAMESPACE})
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="duplicated across SchoolGroups"):
            db_migrations._student_tis_number_identifier_integrity(engine, connection)
    assert not db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_student_number_value",
    )


def test_migration_fails_safely_on_multiple_active_rows_for_one_student():
    engine = _bare_engine_with_students_and_identifiers()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO student_external_identifiers "
            "(school_group_id, student_id, namespace, value, status) "
            "VALUES (1, 1, :ns, 'STD1111111111', 'active'), "
            "(1, 1, :ns, 'STD2222222222', 'active')"
        ), {"ns": NAMESPACE})
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="more than one active"):
            db_migrations._student_tis_number_identifier_integrity(engine, connection)
    assert not db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_number_active_student",
    )


def test_migration_succeeds_when_existing_rows_are_clean():
    engine = _bare_engine_with_students_and_identifiers()
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO student_external_identifiers "
            "(school_group_id, student_id, namespace, value, status) "
            "VALUES (1, 1, :ns, 'STD1111111111', 'active'), "
            "(2, 2, :ns, 'STD2222222222', 'inactive')"
        ), {"ns": NAMESPACE})
    with engine.begin() as connection:
        db_migrations._student_tis_number_identifier_integrity(engine, connection)
    assert db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_student_number_value",
    )
    assert db_migrations._index_exists(
        engine, "student_external_identifiers", "uq_student_external_identifiers_tis_number_active_student",
    )


# ---------------------------------------------------------------------------
# ORM/database-level integrity (fresh schema, current models.py)
# ---------------------------------------------------------------------------

def test_general_namespace_tenant_scoped_uniqueness_is_unchanged(database):
    # Same value, same namespace, DIFFERENT SchoolGroups - allowed for any
    # ordinary namespace exactly as before this task.
    _identifier(database, student_id=100, school_group_id=1, namespace="sis", value="SAME-VALUE")
    _identifier(database, student_id=300, school_group_id=2, namespace="sis", value="SAME-VALUE")
    database.commit()  # must not raise

    # Same value, same namespace, SAME SchoolGroup - still rejected (unchanged).
    _identifier(database, student_id=200, school_group_id=1, namespace="sis", value="SAME-VALUE")
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_tis_student_number_value_is_globally_unique_across_school_groups(database):
    _identifier(database, student_id=100, school_group_id=1, namespace=NAMESPACE, value="STD0000000001")
    database.commit()

    # Different SchoolGroup, different Student, but the SAME canonical value.
    _identifier(database, student_id=300, school_group_id=2, namespace=NAMESPACE, value="STD0000000001")
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_duplicate_tis_student_number_within_the_same_school_group_is_also_rejected(database):
    _identifier(database, student_id=100, school_group_id=1, namespace=NAMESPACE, value="STD0000000002")
    database.commit()

    _identifier(database, student_id=200, school_group_id=1, namespace=NAMESPACE, value="STD0000000002")
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_inactive_tis_student_number_value_remains_permanently_reserved(database):
    retired = _identifier(
        database, student_id=100, school_group_id=1, namespace=NAMESPACE,
        value="STD0000000003", status="inactive",
    )
    database.commit()
    assert retired.status == "inactive"

    # A different Student attempting to claim the retired value must be
    # rejected even though the existing row is inactive.
    _identifier(database, student_id=300, school_group_id=2, namespace=NAMESPACE, value="STD0000000003")
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_one_student_cannot_have_two_active_canonical_ids(database):
    _identifier(database, student_id=100, school_group_id=1, namespace=NAMESPACE, value="STD0000000004")
    database.commit()

    # A second, DIFFERENT active canonical value for the SAME Student.
    _identifier(database, student_id=100, school_group_id=1, namespace=NAMESPACE, value="STD0000000005")
    with pytest.raises(IntegrityError):
        database.commit()
    database.rollback()


def test_a_student_may_have_one_inactive_and_one_active_tis_student_number(database):
    # Retiring an old value and issuing a new active one for the same
    # Student must remain possible - only two ACTIVE rows are forbidden.
    _identifier(database, student_id=100, school_group_id=1, namespace=NAMESPACE, value="STD0000000006", status="inactive")
    _identifier(database, student_id=100, school_group_id=1, namespace=NAMESPACE, value="STD0000000007", status="active")
    database.commit()  # must not raise

    refreshed = database.query(models.StudentExternalIdentifier).filter_by(
        student_id=100, namespace=NAMESPACE,
    ).order_by(models.StudentExternalIdentifier.id).all()
    assert [row.status for row in refreshed] == ["inactive", "active"]


def test_legacy_student_without_any_managed_identifier_remains_valid(database):
    student = database.get(models.Student, 200)
    assert student is not None
    identifiers = database.query(models.StudentExternalIdentifier).filter_by(student_id=200).all()
    assert identifiers == []
