import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

import db_migrations
import models


LEGACY_TIMETABLE_ENTRIES_SQL = """
CREATE TABLE timetable_entries (
    id INTEGER PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    academic_year_id INTEGER NOT NULL REFERENCES academic_years(id),
    planning_section_id INTEGER NOT NULL REFERENCES planning_sections(id),
    subject_code VARCHAR NOT NULL,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id),
    day_key VARCHAR(16) NOT NULL,
    period_index INTEGER NOT NULL,
    CONSTRAINT uq_timetable_entries_section_slot UNIQUE
        (branch_id, academic_year_id, planning_section_id, day_key, period_index),
    CONSTRAINT uq_timetable_entries_teacher_slot UNIQUE
        (branch_id, academic_year_id, teacher_id, day_key, period_index)
)
"""


def _legacy_engine(*, mismatched_year=False, with_entry=True):
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            models.SchoolGroup(id=1, name="One"),
            models.SchoolGroup(id=2, name="Two"),
            models.Branch(id=10, school_group_id=1, name="Main"),
            models.AcademicYear(
                id=100, school_group_id=2 if mismatched_year else 1,
                year_name="2026",
            ),
            models.Teacher(
                id=1000, teacher_id="T1", first_name="A", last_name="Teacher",
                branch_id=10, academic_year_id=100,
            ),
            models.PlanningSection(
                id=2000, grade_level="1", section_name="A", class_status="Current",
                branch_id=10, academic_year_id=100,
            ),
            models.Subject(
                id=3000, subject_code="MAT", subject_name="Mathematics",
                weekly_hours=4, grade=1, branch_id=10, academic_year_id=100,
            ),
            models.TeacherSectionAssignment(
                id=4000, teacher_id=1000, planning_section_id=2000,
                subject_code="MAT",
            ),
        ])
        session.commit()
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF"))
        connection.execute(text("DROP TABLE timetable_entries"))
        for table_name in (
            "timetable_active_versions", "timetable_generation_runs",
            "timetable_versions", "timetable_input_snapshots",
        ):
            connection.execute(text(f"DROP TABLE {table_name}"))
        connection.execute(text(LEGACY_TIMETABLE_ENTRIES_SQL))
        connection.execute(text("PRAGMA foreign_keys = ON"))
        if with_entry:
            connection.execute(text(
                "INSERT INTO timetable_entries "
                "(id, branch_id, academic_year_id, planning_section_id, subject_code, teacher_id, day_key, period_index) "
                "VALUES (9000, 10, 100, 2000, 'MAT', 1000, 'monday', 1)"
            ))
    return engine


def test_migration_preserves_placements_and_creates_imported_active_version():
    engine = _legacy_engine()
    with engine.begin() as connection:
        db_migrations._smart_timetable_stage2_version_foundation(engine, connection)
    with engine.connect() as connection:
        entry = connection.execute(text(
            "SELECT id, branch_id, academic_year_id, planning_section_id, subject_code, "
            "teacher_id, day_key, period_index, timetable_version_id, is_locked "
            "FROM timetable_entries"
        )).mappings().one()
        version = connection.execute(text("SELECT * FROM timetable_versions")).mappings().one()
        pointer = connection.execute(text("SELECT * FROM timetable_active_versions")).mappings().one()
        assert tuple(entry[key] for key in (
            "id", "branch_id", "academic_year_id", "planning_section_id",
            "subject_code", "teacher_id", "day_key", "period_index",
        )) == (9000, 10, 100, 2000, "MAT", 1000, "monday", 1)
        assert entry["timetable_version_id"] == version["id"]
        assert entry["is_locked"] in (0, False)
        assert version["origin"] == "imported"
        assert pointer["timetable_version_id"] == version["id"]
        assert inspect(connection).get_columns("timetable_entries")[1]
    with engine.begin() as connection:
        db_migrations._smart_timetable_stage2_version_foundation(engine, connection)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM timetable_versions")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM timetable_active_versions")).scalar_one() == 1
    engine.dispose()


def test_migration_creates_no_version_for_settings_only_scope():
    engine = _legacy_engine(with_entry=False)
    with engine.begin() as connection:
        db_migrations._smart_timetable_stage2_version_foundation(engine, connection)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM timetable_versions")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM timetable_active_versions")).scalar_one() == 0
    engine.dispose()


def test_migration_fails_closed_and_rolls_back_mismatched_scope():
    engine = _legacy_engine(mismatched_year=True)
    try:
        with engine.begin() as connection:
            db_migrations._smart_timetable_stage2_version_foundation(engine, connection)
    except RuntimeError as exc:
        assert "SchoolGroup ownership does not match" in str(exc)
    else:
        raise AssertionError("Expected migration to reject a mismatched tenant scope")
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM timetable_entries WHERE id = 9000"
        )).scalar_one() == 1
        if "timetable_versions" in inspect(connection).get_table_names():
            assert connection.execute(text("SELECT COUNT(*) FROM timetable_versions")).scalar_one() == 0
    engine.dispose()


def test_migration_preserves_stale_row_and_records_safe_evidence():
    engine = _legacy_engine()
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE timetable_entries SET subject_code = 'OLD', teacher_id = 1000 WHERE id = 9000"
        ))
        db_migrations._smart_timetable_stage2_version_foundation(engine, connection)
    with engine.connect() as connection:
        entry = connection.execute(text(
            "SELECT subject_code, teacher_id, day_key, period_index FROM timetable_entries WHERE id = 9000"
        )).one()
        version = connection.execute(text(
            "SELECT is_stale, stale_reason_json FROM timetable_versions"
        )).one()
        assert tuple(entry) == ("OLD", 1000, "monday", 1)
        assert version[0] in (1, True)
        assert "subject_not_in_current_plan" in version[1]
    engine.dispose()


POSTGRESQL_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "")


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL timetable validation",
)
def test_postgresql_stage2_schema_and_empty_migration_are_compatible():
    schema_name = f"tis_timetable_s2_{uuid.uuid4().hex}"
    admin = create_engine(POSTGRESQL_URL)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_engine(
        POSTGRESQL_URL,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c search_path={schema_name} -c lock_timeout=5s -c statement_timeout=30s",
        },
    )
    try:
        models.Base.metadata.create_all(engine)
        with engine.begin() as connection:
            db_migrations._smart_timetable_stage2_version_foundation(engine, connection)
        with engine.connect() as connection:
            unique_sets = {
                tuple(item.get("column_names") or [])
                for item in inspect(connection).get_unique_constraints("timetable_entries")
            }
            assert (
                "timetable_version_id", "planning_section_id", "day_key", "period_index"
            ) in unique_sets
            assert connection.execute(text("SELECT COUNT(*) FROM timetable_versions")).scalar_one() == 0
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin.dispose()
