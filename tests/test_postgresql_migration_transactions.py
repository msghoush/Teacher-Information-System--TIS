import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

import db_migrations
import models
import saas.models  # noqa: F401 - register shared metadata
from scripts import run_migrations


POSTGRESQL_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "")


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL migration tests",
)
def test_planning_subject_demand_migration_creates_fk_target_constraints_first():
    schema_name = f"tis_planning_demand_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRESQL_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = create_engine(
        POSTGRESQL_URL,
        connect_args={
            "connect_timeout": 10,
            "options": (
                f"-c search_path={schema_name} "
                "-c lock_timeout=5s -c statement_timeout=30s"
            ),
        },
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE planning_sections ("
                "id SERIAL PRIMARY KEY, grade_level VARCHAR(8) NOT NULL, "
                "section_name VARCHAR(20) NOT NULL, class_status VARCHAR(20) NOT NULL, "
                "homeroom_teacher_id INTEGER, branch_id INTEGER NOT NULL, "
                "academic_year_id INTEGER NOT NULL)"
            ))
            connection.execute(text(
                "CREATE TABLE subjects ("
                "id SERIAL PRIMARY KEY, subject_code VARCHAR, subject_name VARCHAR, "
                "color VARCHAR(7), weekly_hours INTEGER, grade INTEGER, "
                "branch_id INTEGER, academic_year_id INTEGER)"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX uq_subjects_scope_code "
                "ON subjects (branch_id, academic_year_id, subject_code)"
            ))
        models.Base.metadata.create_all(
            engine,
            tables=run_migrations._baseline_metadata_tables(),
        )
        db_migrations._ensure_schema_migrations_table(engine)
        with engine.begin() as connection:
            assert not inspect(connection).has_table("planning_subject_demands")
            connection.execute(text(
                "INSERT INTO schema_migrations (migration_id, description, applied_at) "
                "VALUES (:migration_id, :description, CURRENT_TIMESTAMP)"
            ), [
                {"migration_id": migration.migration_id, "description": migration.description}
                for migration in db_migrations.MIGRATIONS
                if migration.migration_id != "20260828_004_planning_subject_demands_foundation"
            ])

        applied = db_migrations.run_pending_migrations(engine)
        assert applied == ["20260828_004_planning_subject_demands_foundation"]
        assert db_migrations.run_pending_migrations(engine) == []

        inspector = inspect(engine)
        planning_unique = {
            tuple(item.get("column_names") or [])
            for item in inspector.get_unique_constraints("planning_sections")
        }
        subject_unique = {
            tuple(item.get("column_names") or [])
            for item in inspector.get_unique_constraints("subjects")
        }
        demand_fks = {
            tuple(item.get("constrained_columns") or [])
            for item in inspector.get_foreign_keys("planning_subject_demands")
        }
        assert ("id", "branch_id", "academic_year_id") in planning_unique
        assert ("branch_id", "academic_year_id", "subject_code") in subject_unique
        assert ("planning_section_id", "branch_id", "academic_year_id") in demand_fks
        assert ("branch_id", "academic_year_id", "subject_code") in demand_fks
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM planning_subject_demands")).scalar() == 0
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL migration tests",
)
def test_teacher_rule_migration_is_safe_after_baseline_metadata_and_idempotent():
    schema_name = f"tis_teacher_rules_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRESQL_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_engine(POSTGRESQL_URL, connect_args={
        "connect_timeout": 10,
        "options": f"-c search_path={schema_name} -c lock_timeout=5s -c statement_timeout=30s",
    })
    try:
        models.Base.metadata.create_all(engine, tables=run_migrations._baseline_metadata_tables())
        inspector = inspect(engine)
        assert not inspector.has_table("teacher_scheduling_rules")
        with engine.begin() as connection:
            db_migrations._teacher_scheduling_rules_foundation(engine, connection)
            db_migrations._teacher_scheduling_window_semantics(engine, connection)
        with engine.begin() as connection:
            db_migrations._teacher_scheduling_rules_foundation(engine, connection)
            db_migrations._teacher_scheduling_window_semantics(engine, connection)
        inspector = inspect(engine)
        assert inspector.has_table("teacher_scheduling_rules")
        assert inspector.has_table("teacher_scheduling_rule_slots")
        assert inspector.has_table("teacher_scheduling_rule_targets")
        assert "restrict_to_window" in {column["name"] for column in inspector.get_columns("teacher_scheduling_rules")}
        teacher_unique = {tuple(item.get("column_names") or []) for item in inspector.get_unique_constraints("teachers")}
        assert ("id", "branch_id", "academic_year_id") in teacher_unique
        rule_fks = {tuple(item.get("constrained_columns") or []) for item in inspector.get_foreign_keys("teacher_scheduling_rules")}
        assert ("teacher_id", "branch_id", "academic_year_id") in rule_fks
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL migration tests",
)
def test_m8b7_repeated_system_notification_inspection_uses_transaction_connection():
    schema_name = f"tis_m8b7_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRESQL_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = create_engine(
        POSTGRESQL_URL,
        connect_args={
            "connect_timeout": 10,
            "options": (
                f"-c search_path={schema_name} "
                "-c lock_timeout=5s -c statement_timeout=30s"
            ),
        },
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE system_notifications "
                    "(id SERIAL PRIMARY KEY, school_group_id INTEGER NOT NULL)"
                )
            )

        with engine.begin() as connection:
            for name, column_sql in (
                ("destination_url", "destination_url VARCHAR(500)"),
                ("deduplication_key", "deduplication_key VARCHAR(180)"),
                ("category", "category VARCHAR(40)"),
                ("severity", "severity VARCHAR(20)"),
            ):
                db_migrations._add_column_if_missing(
                    engine,
                    connection,
                    "system_notifications",
                    name,
                    column_sql,
                )
            db_migrations._create_unique_index_if_missing(
                engine,
                connection,
                "system_notifications",
                "uq_system_notifications_deduplication_key",
                "deduplication_key",
            )

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("system_notifications")
        }
        indexes = {
            index["name"]
            for index in inspect(engine).get_indexes("system_notifications")
        }
        assert {
            "destination_url",
            "deduplication_key",
            "category",
            "severity",
        } <= columns
        assert "uq_system_notifications_deduplication_key" in indexes
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()
