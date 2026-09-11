import os
import uuid
from types import SimpleNamespace

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


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL migration tests",
)
def test_student_talent_prerequisite_unblocks_full_fresh_chain_and_is_idempotent():
    schema_name = f"tis_student_talent_chain_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRESQL_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_engine(POSTGRESQL_URL, connect_args={
        "connect_timeout": 10,
        "options": f"-c search_path={schema_name} -c lock_timeout=5s -c statement_timeout=60s",
    })
    try:
        models.Base.metadata.create_all(
            engine, tables=run_migrations._baseline_metadata_tables(),
        )
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE branches DROP CONSTRAINT uq_branches_id_school_group"
            ))
            connection.execute(text(
                "ALTER TABLE academic_years DROP CONSTRAINT uq_academic_years_id_school_group"
            ))
        assert not inspect(engine).has_table("student_academic_placements")

        applied = db_migrations.run_pending_migrations(engine)
        assert "20260904_000_student_talent_parent_scope_prerequisites" in applied
        assert "20260904_001_student_academic_placement_foundation" in applied
        assert "20260905_001_talent_annual_evaluation_plan_period_foundation" in applied
        assert db_migrations.run_pending_migrations(engine) == []

        inspector = inspect(engine)
        for table_name in ("branches", "academic_years", "students"):
            unique_keys = {
                tuple(item.get("column_names") or [])
                for item in inspector.get_unique_constraints(table_name)
            }
            assert ("id", "school_group_id") in unique_keys
        assert inspector.has_table("student_academic_placements")
        assert inspector.has_table("talent_educator_inputs")
        assert inspector.has_table("talent_planned_evaluation_periods")
        migration_tables = {
            name for name in models.Base.metadata.tables
            if name == "students" or name.startswith("student_") or name.startswith("talent_")
        }
        for child_table in migration_tables:
            for foreign_key in inspector.get_foreign_keys(child_table):
                referred_columns = tuple(foreign_key.get("referred_columns") or [])
                if len(referred_columns) < 2:
                    continue
                parent_table = foreign_key["referred_table"]
                parent_keys = {
                    tuple(item.get("column_names") or [])
                    for item in inspector.get_unique_constraints(parent_table)
                }
                parent_keys.add(tuple(
                    inspector.get_pk_constraint(parent_table).get("constrained_columns") or []
                ))
                assert referred_columns in parent_keys, (
                    child_table, foreign_key.get("name"), parent_table, referred_columns,
                )

        # Simulate a development database where 001+ already ran before the new
        # prerequisite ID existed. Reapplying 000 detects equivalent keys.
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM schema_migrations "
                "WHERE migration_id = '20260904_000_student_talent_parent_scope_prerequisites'"
            ))
        assert db_migrations.run_pending_migrations(engine) == [
            "20260904_000_student_talent_parent_scope_prerequisites"
        ]
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL migration tests",
)
def test_student_talent_prerequisite_duplicate_preflight_fails_without_marker_or_rewrite():
    schema_name = f"tis_student_talent_duplicate_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRESQL_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_engine(POSTGRESQL_URL, connect_args={
        "connect_timeout": 10,
        "options": f"-c search_path={schema_name} -c lock_timeout=5s -c statement_timeout=30s",
    })
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE branches (id INTEGER NOT NULL, school_group_id INTEGER)"
            ))
            connection.execute(text(
                "INSERT INTO branches (id, school_group_id) VALUES (1, 9), (1, 9)"
            ))
        db_migrations._ensure_schema_migrations_table(engine)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO schema_migrations (migration_id, description) "
                "VALUES (:migration_id, :description)"
            ), [
                {"migration_id": migration.migration_id, "description": migration.description}
                for migration in db_migrations.MIGRATIONS
                if migration.migration_id != "20260904_000_student_talent_parent_scope_prerequisites"
            ])

        with pytest.raises(RuntimeError, match="duplicate branches parent scope"):
            db_migrations.run_pending_migrations(engine)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM branches")).scalar() == 2
            assert connection.execute(text(
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE migration_id = '20260904_000_student_talent_parent_scope_prerequisites'"
            )).scalar() == 0
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.skipif(
    not POSTGRESQL_URL.startswith("postgresql"),
    reason="TIS_TEST_POSTGRESQL_URL is required for PostgreSQL migration tests",
)
def test_postgresql_failed_preledger_create_all_rolls_back_partial_student_tables():
    schema_name = f"tis_student_old_runner_{uuid.uuid4().hex}"
    admin_engine = create_engine(POSTGRESQL_URL)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_engine(POSTGRESQL_URL, connect_args={
        "connect_timeout": 10,
        "options": f"-c search_path={schema_name} -c lock_timeout=5s -c statement_timeout=30s",
    })
    try:
        models.Base.metadata.create_all(
            engine, tables=run_migrations._baseline_metadata_tables(),
        )
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE branches DROP CONSTRAINT uq_branches_id_school_group"
            ))
        with pytest.raises(Exception, match="no unique constraint"):
            models.Base.metadata.create_all(engine, tables=[
                models.Student.__table__,
                models.StudentExternalIdentifier.__table__,
                models.StudentAcademicPlacement.__table__,
                models.StudentAudit.__table__,
            ])
        inspector = inspect(engine)
        assert not inspector.has_table("students")
        assert not inspector.has_table("student_external_identifiers")
        assert not inspector.has_table("student_academic_placements")
        assert not inspector.has_table("student_audits")
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin_engine.dispose()


def test_talent_reassessment_migration_uses_postgresql_boolean_default(monkeypatch):
    added_columns = []
    monkeypatch.setattr(db_migrations, "_table_exists", lambda connection, table: True)
    monkeypatch.setattr(
        db_migrations,
        "_add_column_if_missing",
        lambda engine, connection, table, column, column_sql: added_columns.append(
            (table, column, column_sql)
        ),
    )
    monkeypatch.setattr(db_migrations, "_execute", lambda connection, sql, params=None: None)
    monkeypatch.setattr(
        db_migrations, "_create_index_if_missing",
        lambda engine, connection, table, index_name, columns: None,
    )

    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    db_migrations._talent_assessment_reassessment_attempts(engine, object())

    is_current = next(
        sql for table, column, sql in added_columns
        if table == "talent_student_assessments" and column == "is_current"
    )
    assert "BOOLEAN NOT NULL DEFAULT TRUE" in is_current
    assert "DEFAULT 1" not in is_current
