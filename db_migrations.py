import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import inspect, text


logger = logging.getLogger("tis.db_migrations")


@dataclass(frozen=True)
class Migration:
    migration_id: str
    description: str
    apply: Callable


def _table_exists(bind, table_name: str) -> bool:
    return table_name in inspect(bind).get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return column_name in {column["name"] for column in inspect(bind).get_columns(table_name)}


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return index_name in {
        index.get("name")
        for index in inspect(bind).get_indexes(table_name)
        if index.get("name")
    }


def _execute(connection, sql: str, params: dict | None = None):
    connection.execute(text(sql), params or {})


def _add_column_if_missing(bind, connection, table_name: str, column_name: str, column_sql: str):
    if not _table_exists(bind, table_name) or _column_exists(bind, table_name, column_name):
        return
    _execute(connection, f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def _create_index_if_missing(bind, connection, table_name: str, index_name: str, columns_sql: str):
    if not _table_exists(bind, table_name) or _index_exists(bind, table_name, index_name):
        return
    _execute(connection, f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns_sql})")


def _create_unique_index_if_missing(bind, connection, table_name: str, index_name: str, columns_sql: str):
    if not _table_exists(bind, table_name) or _index_exists(bind, table_name, index_name):
        return
    _execute(connection, f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns_sql})")


def _ensure_schema_migrations_table(engine):
    with engine.begin() as connection:
        _execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                migration_id VARCHAR(120) PRIMARY KEY,
                description VARCHAR(255) NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )


def _get_applied_migration_ids(engine) -> set[str]:
    _ensure_schema_migrations_table(engine)
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT migration_id FROM schema_migrations")).all()
    return {str(row[0]) for row in rows}


def _mark_migration_applied(connection, migration: Migration):
    _execute(
        connection,
        """
        INSERT INTO schema_migrations (migration_id, description, applied_at)
        VALUES (:migration_id, :description, CURRENT_TIMESTAMP)
        """,
        {
            "migration_id": migration.migration_id,
            "description": migration.description,
        },
    )


def _ensure_default_school_group(connection) -> int | None:
    if not _table_exists(connection, "school_groups"):
        return None

    default_group_id = connection.execute(
        text("SELECT id FROM school_groups ORDER BY id ASC LIMIT 1")
    ).scalar()
    if default_group_id:
        return int(default_group_id)

    _execute(
        connection,
        """
        INSERT INTO school_groups (name, status, created_at, updated_at)
        VALUES (:name, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        {"name": "Al-Andalus Schools", "status": True},
    )
    default_group_id = connection.execute(
        text("SELECT id FROM school_groups WHERE name = :name ORDER BY id ASC LIMIT 1"),
        {"name": "Al-Andalus Schools"},
    ).scalar()
    return int(default_group_id) if default_group_id else None


def _ensure_postgres_fk(engine, connection, *, table_name: str, constraint_name: str, column_name: str, target_table: str):
    if engine.dialect.name != "postgresql" or not _table_exists(connection, table_name):
        return

    foreign_keys = inspect(connection).get_foreign_keys(table_name)
    for foreign_key in foreign_keys:
        if (
            foreign_key.get("referred_table") == target_table
            and tuple(foreign_key.get("constrained_columns") or []) == (column_name,)
        ):
            return

    _execute(
        connection,
        (
            f"ALTER TABLE {table_name} "
            f"ADD CONSTRAINT {constraint_name} "
            f"FOREIGN KEY ({column_name}) REFERENCES {target_table} (id) NOT VALID"
        ),
    )


def _datetime_type(engine) -> str:
    return "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"


def _binary_type(engine) -> str:
    return "BYTEA" if engine.dialect.name == "postgresql" else "BLOB"


def _dialect_column_sql(column_sql: str, engine) -> str:
    if engine.dialect.name != "postgresql":
        return column_sql
    return column_sql.replace("DATETIME", "TIMESTAMP")


def _tenant_scope_columns_and_backfill(engine, connection):
    default_group_id = _ensure_default_school_group(connection)

    _add_column_if_missing(connection, connection, "branches", "school_group_id", "school_group_id INTEGER")
    _add_column_if_missing(connection, connection, "academic_years", "school_group_id", "school_group_id INTEGER")
    _create_index_if_missing(connection, connection, "branches", "ix_branches_school_group_id", "school_group_id")
    _create_index_if_missing(connection, connection, "academic_years", "ix_academic_years_school_group_id", "school_group_id")

    if default_group_id:
        if _table_exists(connection, "branches"):
            _execute(
                connection,
                "UPDATE branches SET school_group_id = :group_id WHERE school_group_id IS NULL",
                {"group_id": default_group_id},
            )
        if _table_exists(connection, "academic_years"):
            _execute(
                connection,
                "UPDATE academic_years SET school_group_id = :group_id WHERE school_group_id IS NULL",
                {"group_id": default_group_id},
            )

    _add_column_if_missing(connection, connection, "users", "school_group_id", "school_group_id INTEGER")
    _create_index_if_missing(connection, connection, "users", "ix_users_school_group_id", "school_group_id")
    if _table_exists(connection, "users"):
        _execute(
            connection,
            """
            UPDATE users
            SET school_group_id = (
                SELECT branches.school_group_id
                FROM branches
                WHERE branches.id = users.branch_id
            )
            WHERE school_group_id IS NULL AND branch_id IS NOT NULL
            """,
        )
        if default_group_id:
            _execute(
                connection,
                "UPDATE users SET school_group_id = :group_id WHERE school_group_id IS NULL",
                {"group_id": default_group_id},
            )

    _add_column_if_missing(connection, connection, "system_notifications", "school_group_id", "school_group_id INTEGER")
    _add_column_if_missing(connection, connection, "system_notifications", "branch_id", "branch_id INTEGER")
    _add_column_if_missing(connection, connection, "system_notifications", "academic_year_id", "academic_year_id INTEGER")
    _create_index_if_missing(
        connection,
        connection,
        "system_notifications",
        "ix_system_notifications_school_group_id",
        "school_group_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "system_notifications",
        "ix_system_notifications_branch_year",
        "branch_id, academic_year_id",
    )
    if _table_exists(connection, "system_notifications"):
        _execute(
            connection,
            """
            UPDATE system_notifications
            SET school_group_id = (
                SELECT users.school_group_id
                FROM users
                WHERE users.user_id = system_notifications.recipient_user_id
            )
            WHERE school_group_id IS NULL AND recipient_user_id IS NOT NULL
            """,
        )
        _execute(
            connection,
            """
            UPDATE system_notifications
            SET school_group_id = (
                SELECT users.school_group_id
                FROM users
                WHERE users.user_id = system_notifications.requesting_user_id
            )
            WHERE school_group_id IS NULL AND requesting_user_id IS NOT NULL
            """,
        )
        _execute(
            connection,
            """
            UPDATE system_notifications
            SET branch_id = (
                SELECT users.branch_id
                FROM users
                WHERE users.user_id = system_notifications.recipient_user_id
            )
            WHERE branch_id IS NULL AND recipient_user_id IS NOT NULL
            """,
        )
        _execute(
            connection,
            """
            UPDATE system_notifications
            SET academic_year_id = (
                SELECT users.academic_year_id
                FROM users
                WHERE users.user_id = system_notifications.recipient_user_id
            )
            WHERE academic_year_id IS NULL AND recipient_user_id IS NOT NULL
            """,
        )
        if default_group_id:
            _execute(
                connection,
                "UPDATE system_notifications SET school_group_id = :group_id WHERE school_group_id IS NULL",
                {"group_id": default_group_id},
            )

    _ensure_postgres_fk(
        engine,
        connection,
        table_name="users",
        constraint_name="fk_users_school_group_id",
        column_name="school_group_id",
        target_table="school_groups",
    )
    _ensure_postgres_fk(
        engine,
        connection,
        table_name="system_notifications",
        constraint_name="fk_system_notifications_school_group_id",
        column_name="school_group_id",
        target_table="school_groups",
    )
    _ensure_postgres_fk(
        engine,
        connection,
        table_name="system_notifications",
        constraint_name="fk_system_notifications_branch_id",
        column_name="branch_id",
        target_table="branches",
    )
    _ensure_postgres_fk(
        engine,
        connection,
        table_name="system_notifications",
        constraint_name="fk_system_notifications_academic_year_id",
        column_name="academic_year_id",
        target_table="academic_years",
    )


OBSERVATION_SCHEMA_COLUMNS = {
    "observation_criteria": {
        "domain_key": "VARCHAR(8) NOT NULL DEFAULT ''",
        "domain_title": "VARCHAR(160) NOT NULL DEFAULT ''",
        "indicator_number": "INTEGER NOT NULL DEFAULT 0",
        "title": "TEXT NOT NULL DEFAULT ''",
        "guidelines": "TEXT NOT NULL DEFAULT ''",
        "evidence_examples": "TEXT NOT NULL DEFAULT ''",
        "rubric_descriptors": "TEXT NOT NULL DEFAULT '{}'",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
    },
    "observations": {
        "branch_id": "INTEGER NOT NULL DEFAULT 0",
        "academic_year_id": "INTEGER NOT NULL DEFAULT 0",
        "teacher_id": "INTEGER NOT NULL DEFAULT 0",
        "evaluator_user_id": "VARCHAR(10) NOT NULL DEFAULT ''",
        "observation_type": "VARCHAR(20) NOT NULL DEFAULT 'Formal'",
        "observation_date": "VARCHAR(10) NOT NULL DEFAULT ''",
        "term": "VARCHAR(20)",
        "grade": "VARCHAR(20)",
        "section": "VARCHAR(20)",
        "period": "VARCHAR(20)",
        "subject": "VARCHAR(120)",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'Final'",
        "overall_score": "VARCHAR(20)",
        "evaluator_notes": "TEXT",
        "evaluatee_notes": "TEXT",
        "teacher_signature_data": "TEXT",
        "evaluator_signature_data": "TEXT",
        "locked_at": "DATETIME",
        "smart_feedback": "TEXT",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "observation_scores": {
        "observation_id": "INTEGER NOT NULL DEFAULT 0",
        "criterion_id": "INTEGER NOT NULL DEFAULT 0",
        "rating": "VARCHAR(4) NOT NULL DEFAULT 'NA'",
        "evidence": "TEXT",
    },
    "observation_self_evaluations": {
        "observation_id": "INTEGER NOT NULL DEFAULT 0",
        "teacher_id": "INTEGER NOT NULL DEFAULT 0",
        "reflection": "TEXT",
        "strengths": "TEXT",
        "growth_areas": "TEXT",
        "support_needed": "TEXT",
        "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    },
    "observation_self_evaluation_scores": {
        "self_evaluation_id": "INTEGER NOT NULL DEFAULT 0",
        "criterion_id": "INTEGER NOT NULL DEFAULT 0",
        "rating": "VARCHAR(4) NOT NULL DEFAULT 'NA'",
        "evidence": "TEXT",
    },
}


def _legacy_runtime_schema_columns(engine, connection):
    _add_column_if_missing(connection, connection, "users", "username", "username VARCHAR(50)")
    _add_column_if_missing(connection, connection, "users", "position", "position VARCHAR(50)")
    _add_column_if_missing(connection, connection, "users", "profile_image_path", "profile_image_path VARCHAR(255)")
    _add_column_if_missing(
        connection,
        connection,
        "users",
        "profile_image_content_type",
        "profile_image_content_type VARCHAR(50)",
    )
    _add_column_if_missing(
        connection,
        connection,
        "users",
        "profile_image_data",
        f"profile_image_data {_binary_type(engine)}",
    )
    _add_column_if_missing(connection, connection, "users", "is_active", "is_active BOOLEAN DEFAULT TRUE")
    _create_index_if_missing(connection, connection, "users", "ix_users_username", "username")
    if _table_exists(connection, "users") and _column_exists(connection, "users", "is_active"):
        _execute(connection, "UPDATE users SET is_active = TRUE WHERE is_active IS NULL")

    _add_column_if_missing(connection, connection, "subjects", "color", "color VARCHAR(7)")
    _add_column_if_missing(connection, connection, "subjects", "branch_id", "branch_id INTEGER")
    _add_column_if_missing(connection, connection, "subjects", "academic_year_id", "academic_year_id INTEGER")
    _create_index_if_missing(connection, connection, "subjects", "ix_subjects_subject_code", "subject_code")
    _create_unique_index_if_missing(
        connection,
        connection,
        "subjects",
        "uq_subjects_scope_code",
        "branch_id, academic_year_id, subject_code",
    )

    _add_column_if_missing(connection, connection, "teachers", "middle_name", "middle_name VARCHAR(100)")
    _add_column_if_missing(connection, connection, "teachers", "degree_major", "degree_major VARCHAR(120)")
    _add_column_if_missing(connection, connection, "teachers", "extra_hours_allowed", "extra_hours_allowed BOOLEAN DEFAULT FALSE")
    _add_column_if_missing(connection, connection, "teachers", "extra_hours_count", "extra_hours_count INTEGER DEFAULT 0")
    _add_column_if_missing(
        connection,
        connection,
        "teachers",
        "teaches_national_section",
        "teaches_national_section BOOLEAN DEFAULT FALSE",
    )
    _add_column_if_missing(connection, connection, "teachers", "national_section_hours", "national_section_hours INTEGER DEFAULT 0")
    _add_column_if_missing(connection, connection, "teachers", "is_new_teacher", "is_new_teacher BOOLEAN DEFAULT FALSE")
    _create_unique_index_if_missing(
        connection,
        connection,
        "teachers",
        "uq_teachers_scope_teacher_id",
        "branch_id, academic_year_id, teacher_id",
    )
    if _table_exists(connection, "teachers"):
        for column_name, default_value in (
            ("extra_hours_allowed", "FALSE"),
            ("extra_hours_count", "0"),
            ("teaches_national_section", "FALSE"),
            ("national_section_hours", "0"),
            ("is_new_teacher", "FALSE"),
        ):
            if _column_exists(connection, "teachers", column_name):
                _execute(
                    connection,
                    f"UPDATE teachers SET {column_name} = {default_value} WHERE {column_name} IS NULL",
                )

    _add_column_if_missing(
        connection,
        connection,
        "teacher_subject_allocations",
        "compatibility_override",
        "compatibility_override BOOLEAN DEFAULT FALSE",
    )
    if _table_exists(connection, "teacher_subject_allocations") and _column_exists(connection, "teacher_subject_allocations", "compatibility_override"):
        _execute(
            connection,
            """
            UPDATE teacher_subject_allocations
            SET compatibility_override = FALSE
            WHERE compatibility_override IS NULL
            """,
        )

    _add_column_if_missing(connection, connection, "timetable_non_teaching_blocks", "start_time", "start_time VARCHAR(5)")
    _add_column_if_missing(connection, connection, "timetable_non_teaching_blocks", "end_time", "end_time VARCHAR(5)")

    datetime_type = _datetime_type(engine)
    for column_name, column_sql in (
        ("recipient_user_id", "recipient_user_id VARCHAR(10) NOT NULL DEFAULT ''"),
        ("requesting_user_id", "requesting_user_id VARCHAR(10)"),
        ("request_type", "request_type VARCHAR(80) NOT NULL DEFAULT 'Message'"),
        ("title", "title VARCHAR(160) NOT NULL DEFAULT 'System Notification'"),
        ("message", "message TEXT"),
        ("details", "details TEXT"),
        ("status", "status VARCHAR(20) NOT NULL DEFAULT 'New'"),
        ("recipient_scope", "recipient_scope VARCHAR(10) NOT NULL DEFAULT 'User'"),
        ("created_at", f"created_at {datetime_type}"),
        ("seen_at", f"seen_at {datetime_type}"),
        ("resolved_at", f"resolved_at {datetime_type}"),
        ("resolved_by_user_id", "resolved_by_user_id VARCHAR(10)"),
        ("recipient_archived_at", f"recipient_archived_at {datetime_type}"),
        ("recipient_archived_by_user_id", "recipient_archived_by_user_id VARCHAR(10)"),
        ("requester_archived_at", f"requester_archived_at {datetime_type}"),
        ("requester_archived_by_user_id", "requester_archived_by_user_id VARCHAR(10)"),
    ):
        _add_column_if_missing(connection, connection, "system_notifications", column_name, column_sql)

    if _table_exists(connection, "system_notifications"):
        for index_name, index_columns_sql in (
            ("ix_system_notifications_recipient_status", "recipient_user_id, status"),
            ("ix_system_notifications_created_at", "created_at"),
            ("ix_system_notifications_recipient_user_id", "recipient_user_id"),
            ("ix_system_notifications_requesting_user_id", "requesting_user_id"),
        ):
            _create_index_if_missing(
                connection,
                connection,
                "system_notifications",
                index_name,
                index_columns_sql,
            )
        _execute(
            connection,
            "UPDATE system_notifications SET recipient_scope = 'User' WHERE recipient_scope IS NULL OR recipient_scope = ''",
        )
        _execute(
            connection,
            "UPDATE system_notifications SET status = 'New' WHERE status IS NULL OR status = ''",
        )
        _execute(
            connection,
            "UPDATE system_notifications SET request_type = 'Message' WHERE request_type IS NULL OR request_type = ''",
        )
        _execute(
            connection,
            "UPDATE system_notifications SET title = 'System Notification' WHERE title IS NULL OR title = ''",
        )
        if _column_exists(connection, "system_notifications", "created_at"):
            _execute(
                connection,
                "UPDATE system_notifications SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL",
            )

    if _table_exists(connection, "calendar_events"):
        _add_column_if_missing(connection, connection, "calendar_events", "end_date", "end_date VARCHAR(10)")
        if _column_exists(connection, "calendar_events", "end_date"):
            _execute(
                connection,
                """
                UPDATE calendar_events
                SET end_date = event_date
                WHERE end_date IS NULL OR TRIM(end_date) = ''
                """,
            )

    if _table_exists(connection, "calendar_events") and not _table_exists(connection, "calendar_event_grade_targets"):
        _execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS calendar_event_grade_targets (
                id INTEGER PRIMARY KEY,
                calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id),
                grade_level VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_calendar_event_grade_targets_event_grade
                UNIQUE (calendar_event_id, grade_level)
            )
            """,
        )
    _create_index_if_missing(
        connection,
        connection,
        "calendar_event_grade_targets",
        "ix_calendar_event_grade_targets_event",
        "calendar_event_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "calendar_event_grade_targets",
        "ix_calendar_event_grade_targets_grade",
        "grade_level",
    )

    if (
        _table_exists(connection, "calendar_events")
        and _table_exists(connection, "planning_sections")
        and not _table_exists(connection, "calendar_event_section_targets")
    ):
        _execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS calendar_event_section_targets (
                id INTEGER PRIMARY KEY,
                calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id),
                section_id INTEGER NOT NULL REFERENCES planning_sections(id),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_calendar_event_section_targets_event_section
                UNIQUE (calendar_event_id, section_id)
            )
            """,
        )
    _create_index_if_missing(
        connection,
        connection,
        "calendar_event_section_targets",
        "ix_calendar_event_section_targets_event",
        "calendar_event_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "calendar_event_section_targets",
        "ix_calendar_event_section_targets_section",
        "section_id",
    )

    for table_name, column_sql_map in OBSERVATION_SCHEMA_COLUMNS.items():
        if not _table_exists(connection, table_name):
            continue
        for column_name, column_sql in column_sql_map.items():
            _add_column_if_missing(
                connection,
                connection,
                table_name,
                column_name,
                f"{column_name} {_dialect_column_sql(column_sql, engine)}",
            )


def _sqlite_tenant_fk_guard_triggers(engine, connection):
    if engine.dialect.name != "sqlite":
        return

    if _table_exists(connection, "users") and _table_exists(connection, "school_groups"):
        _execute(
            connection,
            """
            CREATE TRIGGER IF NOT EXISTS trg_users_school_group_fk_insert
            BEFORE INSERT ON users
            FOR EACH ROW
            WHEN NEW.school_group_id IS NULL
              OR NOT EXISTS (
                  SELECT 1 FROM school_groups WHERE id = NEW.school_group_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'users.school_group_id tenant foreign key violation');
            END
            """,
        )
        _execute(
            connection,
            """
            CREATE TRIGGER IF NOT EXISTS trg_users_school_group_fk_update
            BEFORE UPDATE OF school_group_id ON users
            FOR EACH ROW
            WHEN NEW.school_group_id IS NULL
              OR NOT EXISTS (
                  SELECT 1 FROM school_groups WHERE id = NEW.school_group_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'users.school_group_id tenant foreign key violation');
            END
            """,
        )

    if not _table_exists(connection, "system_notifications"):
        return

    required_tables = {"school_groups", "branches", "academic_years"}
    if not all(_table_exists(connection, table_name) for table_name in required_tables):
        return

    for action, timing in (("insert", "INSERT"), ("update", "UPDATE OF school_group_id, branch_id, academic_year_id")):
        _execute(
            connection,
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_system_notifications_tenant_fk_{action}
            BEFORE {timing} ON system_notifications
            FOR EACH ROW
            WHEN NEW.school_group_id IS NULL
              OR NOT EXISTS (
                  SELECT 1 FROM school_groups WHERE id = NEW.school_group_id
              )
              OR (
                  NEW.branch_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM branches WHERE id = NEW.branch_id
                  )
              )
              OR (
                  NEW.academic_year_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM academic_years WHERE id = NEW.academic_year_id
                  )
              )
              OR (
                  NEW.branch_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM branches
                      WHERE id = NEW.branch_id
                        AND school_group_id IS NOT NEW.school_group_id
                  )
              )
              OR (
                  NEW.academic_year_id IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM academic_years
                      WHERE id = NEW.academic_year_id
                        AND school_group_id IS NOT NEW.school_group_id
                  )
              )
            BEGIN
                SELECT RAISE(ABORT, 'system_notifications tenant foreign key violation');
            END
            """,
        )


def _create_demo_requests_table(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS demo_requests (
            id {id_sql},
            submitted_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            school_name VARCHAR(180) NOT NULL DEFAULT '',
            full_name VARCHAR(160) NOT NULL DEFAULT '',
            email VARCHAR(180) NOT NULL DEFAULT '',
            phone VARCHAR(80) NOT NULL DEFAULT '',
            country VARCHAR(120) NOT NULL DEFAULT '',
            school_type VARCHAR(120) NOT NULL DEFAULT '',
            number_of_teachers VARCHAR(40) NOT NULL DEFAULT '',
            number_of_students VARCHAR(40) NOT NULL DEFAULT '',
            number_of_branches VARCHAR(40) NOT NULL DEFAULT '',
            interested_plan VARCHAR(80) NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            status VARCHAR(40) NOT NULL DEFAULT 'New',
            source_host VARCHAR(180) NOT NULL DEFAULT '',
            source_ip VARCHAR(80) NOT NULL DEFAULT '',
            status_updated_at {datetime_type},
            status_updated_by_user_id VARCHAR(10)
        )
        """,
    )
    for index_name, index_columns_sql in (
        ("ix_demo_requests_submitted_at", "submitted_at"),
        ("ix_demo_requests_status", "status"),
        ("ix_demo_requests_interested_plan", "interested_plan"),
        ("ix_demo_requests_email", "email"),
    ):
        _create_index_if_missing(
            connection,
            connection,
            "demo_requests",
            index_name,
            index_columns_sql,
        )


MIGRATIONS = (
    Migration(
        migration_id="20260613_001_tenant_scope_columns",
        description="Add and backfill tenant scope columns for SaaS isolation",
        apply=_tenant_scope_columns_and_backfill,
    ),
    Migration(
        migration_id="20260613_002_legacy_runtime_schema_columns",
        description="Move legacy runtime schema compatibility columns into formal migration",
        apply=_legacy_runtime_schema_columns,
    ),
    Migration(
        migration_id="20260613_003_sqlite_tenant_fk_guards",
        description="Enforce tenant foreign keys with SQLite triggers for legacy migrated databases",
        apply=_sqlite_tenant_fk_guard_triggers,
    ),
    Migration(
        migration_id="20260613_004_demo_requests",
        description="Create platform-level demo request lead table",
        apply=_create_demo_requests_table,
    ),
)


def run_pending_migrations(engine) -> list[str]:
    applied_ids = _get_applied_migration_ids(engine)
    newly_applied = []
    for migration in MIGRATIONS:
        if migration.migration_id in applied_ids:
            continue
        with engine.begin() as connection:
            migration.apply(engine, connection)
            _mark_migration_applied(connection, migration)
        newly_applied.append(migration.migration_id)
        logger.info("Applied database migration %s", migration.migration_id)
    return newly_applied
