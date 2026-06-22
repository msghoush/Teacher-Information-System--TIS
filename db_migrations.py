import logging
import unicodedata
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


def _normalize_identity_email(value: str | None) -> str | None:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return normalized or None


def _identity_foundation(engine, connection):
    if not _table_exists(connection, "users"):
        return

    rows = connection.execute(
        text("SELECT id, user_id, email FROM users WHERE email IS NOT NULL")
    ).mappings().all()
    normalized_by_user_id = {}
    users_by_email = {}
    for row in rows:
        normalized = _normalize_identity_email(row["email"])
        if not normalized:
            continue
        user_pk = int(row["id"])
        normalized_by_user_id[user_pk] = normalized
        users_by_email.setdefault(normalized, []).append(
            str(row["user_id"] or f"pk:{user_pk}")
        )

    collisions = {
        email: user_ids
        for email, user_ids in users_by_email.items()
        if len(user_ids) > 1
    }
    if collisions:
        details = "; ".join(
            f"{email}: {', '.join(user_ids)}"
            for email, user_ids in sorted(collisions.items())
        )
        raise RuntimeError(
            "Identity migration stopped: duplicate normalized emails found ("
            f"{details}). Resolve the collisions before retrying."
        )

    datetime_type = _datetime_type(engine)
    _add_column_if_missing(connection, connection, "users", "email_normalized", "email_normalized VARCHAR(180)")
    _add_column_if_missing(connection, connection, "users", "email_verified_at", f"email_verified_at {datetime_type}")
    _add_column_if_missing(connection, connection, "users", "last_login_at", f"last_login_at {datetime_type}")
    _add_column_if_missing(connection, connection, "users", "created_at", f"created_at {datetime_type}")
    _add_column_if_missing(connection, connection, "users", "updated_at", f"updated_at {datetime_type}")

    _execute(connection, "UPDATE users SET email = NULL WHERE email IS NOT NULL AND TRIM(email) = ''")
    for user_pk, normalized in normalized_by_user_id.items():
        _execute(
            connection,
            "UPDATE users SET email_normalized = :email WHERE id = :user_pk",
            {"email": normalized, "user_pk": user_pk},
        )
    _execute(
        connection,
        """
        UPDATE users
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
            updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """,
    )

    if not _index_exists(connection, "users", "uq_users_email_normalized"):
        _execute(
            connection,
            """
            CREATE UNIQUE INDEX uq_users_email_normalized
            ON users (email_normalized)
            WHERE email_normalized IS NOT NULL
            """,
        )


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
            status_updated_by_user_id VARCHAR(10),
            seen_at {datetime_type},
            seen_by_user_id VARCHAR(10)
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


def _demo_request_seen_columns(engine, connection):
    datetime_type = _datetime_type(engine)
    _add_column_if_missing(
        connection,
        connection,
        "demo_requests",
        "seen_at",
        f"seen_at {datetime_type}",
    )
    _add_column_if_missing(
        connection,
        connection,
        "demo_requests",
        "seen_by_user_id",
        "seen_by_user_id VARCHAR(10)",
    )
    _create_index_if_missing(
        connection,
        connection,
        "demo_requests",
        "ix_demo_requests_seen_at",
        "seen_at",
    )


def _platform_identity_and_access_scope(engine, connection):
    _add_column_if_missing(connection, connection, "users", "user_type", "user_type VARCHAR(20) NOT NULL DEFAULT 'TENANT'")
    _add_column_if_missing(connection, connection, "users", "platform_role", "platform_role VARCHAR(40)")
    _add_column_if_missing(connection, connection, "users", "access_scope", "access_scope VARCHAR(20) NOT NULL DEFAULT 'BRANCH'")
    if not _table_exists(connection, "users"):
        return

    _execute(
        connection,
        """
        UPDATE users
        SET user_type = 'TENANT', platform_role = NULL,
            access_scope = CASE
                WHEN LOWER(TRIM(COALESCE(position, ''))) IN
                    ('education excellence', 'education excelency', 'management')
                THEN 'ORGANIZATION' ELSE 'BRANCH' END,
            role = CASE
                WHEN LOWER(TRIM(COALESCE(position, ''))) IN
                    ('education excellence', 'education excelency', 'management')
                THEN 'Limited'
                WHEN LOWER(TRIM(COALESCE(role, ''))) = 'limited access' THEN 'Limited'
                ELSE role
            END
        WHERE LOWER(TRIM(COALESCE(role, ''))) != 'developer'
        """,
    )
    _execute(
        connection,
        """
        UPDATE users
        SET user_type = 'PLATFORM', platform_role = 'Platform Developer',
            access_scope = 'GLOBAL', role = NULL, position = NULL,
            branch_id = NULL, academic_year_id = NULL
        WHERE LOWER(TRIM(COALESCE(role, ''))) = 'developer'
           OR (UPPER(TRIM(COALESCE(user_type, ''))) = 'PLATFORM'
               AND LOWER(TRIM(COALESCE(platform_role, ''))) IN ('developer', 'platform developer'))
        """,
    )
    if engine.dialect.name == "postgresql":
        _execute(connection, "ALTER TABLE users ALTER COLUMN school_group_id DROP NOT NULL")
        _execute(connection, "UPDATE users SET school_group_id = NULL WHERE user_type = 'PLATFORM'")

    for index_name, column_name in (
        ("ix_users_user_type", "user_type"),
        ("ix_users_platform_role", "platform_role"),
        ("ix_users_access_scope", "access_scope"),
    ):
        _create_index_if_missing(connection, connection, "users", index_name, column_name)


def _sqlite_platform_user_scope_trigger(engine, connection):
    if (
        engine.dialect.name != "sqlite"
        or not _table_exists(connection, "users")
        or not _table_exists(connection, "school_groups")
    ):
        return

    _execute(connection, "DROP TRIGGER IF EXISTS trg_users_school_group_fk_insert")
    _execute(connection, "DROP TRIGGER IF EXISTS trg_users_school_group_fk_update")
    _execute(
        connection,
        """
        CREATE TRIGGER trg_users_school_group_fk_insert
        BEFORE INSERT ON users
        FOR EACH ROW
        WHEN UPPER(TRIM(COALESCE(NEW.user_type, 'TENANT'))) != 'PLATFORM'
         AND (
             NEW.school_group_id IS NULL
             OR NOT EXISTS (SELECT 1 FROM school_groups WHERE id = NEW.school_group_id)
         )
        BEGIN
            SELECT RAISE(ABORT, 'users.school_group_id tenant foreign key violation');
        END
        """,
    )
    _execute(
        connection,
        """
        CREATE TRIGGER trg_users_school_group_fk_update
        BEFORE UPDATE OF school_group_id, user_type ON users
        FOR EACH ROW
        WHEN UPPER(TRIM(COALESCE(NEW.user_type, 'TENANT'))) != 'PLATFORM'
         AND (
             NEW.school_group_id IS NULL
             OR NOT EXISTS (SELECT 1 FROM school_groups WHERE id = NEW.school_group_id)
         )
        BEGIN
            SELECT RAISE(ABORT, 'users.school_group_id tenant foreign key violation');
        END
        """,
    )


def _normalize_organization_read_only_users(engine, connection):
    if not _table_exists(connection, "users"):
        return
    _execute(
        connection,
        """
        UPDATE users
        SET role = 'Limited', access_scope = 'ORGANIZATION'
        WHERE UPPER(TRIM(COALESCE(user_type, 'TENANT'))) = 'TENANT'
          AND LOWER(TRIM(COALESCE(position, ''))) IN
              ('education excellence', 'education excelency', 'management')
        """,
    )


def _platform_hierarchy_and_permissions(engine, connection):
    _add_column_if_missing(connection, connection, "users", "email", "email VARCHAR(180)")
    _add_column_if_missing(
        connection,
        connection,
        "users",
        "platform_owner_kind",
        "platform_owner_kind VARCHAR(20)",
    )
    _add_column_if_missing(
        connection,
        connection,
        "users",
        "platform_permissions_initialized",
        "platform_permissions_initialized BOOLEAN NOT NULL DEFAULT FALSE",
    )
    if _table_exists(connection, "users"):
        _execute(
            connection,
            """
            UPDATE users
            SET platform_owner_kind = 'CO_OWNER'
            WHERE UPPER(TRIM(COALESCE(user_type, ''))) = 'PLATFORM'
              AND LOWER(TRIM(COALESCE(platform_role, ''))) IN ('owner', 'platform owner')
              AND platform_owner_kind IS NULL
            """,
        )
        _create_unique_index_if_missing(
            connection,
            connection,
            "users",
            "ix_users_email",
            "email",
        )

    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS platform_user_permissions (
            id {id_sql},
            platform_user_id INTEGER NOT NULL,
            permission_key VARCHAR(120) NOT NULL,
            is_allowed BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by_user_id VARCHAR(10),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_platform_user_permissions_user_key
                UNIQUE (platform_user_id, permission_key),
            FOREIGN KEY (platform_user_id) REFERENCES users (id)
        )
        """,
    )
    _create_index_if_missing(
        connection,
        connection,
        "platform_user_permissions",
        "ix_platform_user_permissions_user",
        "platform_user_id",
    )


def _create_system_design_settings_table(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS system_design_settings (
            id {id_sql},
            key VARCHAR(80) NOT NULL UNIQUE,
            value VARCHAR(120) NOT NULL DEFAULT '',
            updated_by_user_id VARCHAR(10),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "system_design_settings",
        "ix_system_design_settings_key",
        "key",
    )


def _create_visual_design_settings_table(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS visual_design_settings (
            id {id_sql},
            page_key VARCHAR(80) NOT NULL,
            component_key VARCHAR(120) NOT NULL,
            component_type VARCHAR(40) NOT NULL,
            setting_key VARCHAR(80) NOT NULL,
            setting_value VARCHAR(255) NOT NULL DEFAULT '',
            scope_type VARCHAR(20) NOT NULL DEFAULT 'global',
            school_group_id INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by_user_id VARCHAR(10),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_visual_design_component_setting UNIQUE (page_key, component_key, setting_key)
        )
        """,
    )
    _create_index_if_missing(
        connection,
        connection,
        "visual_design_settings",
        "ix_visual_design_page_component",
        "page_key, component_key",
    )


def _global_location_columns(engine, connection):
    for table_name in ("school_groups", "branches"):
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            "country_code",
            "country_code VARCHAR(2)",
        )
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            "country_name",
            "country_name VARCHAR(120)",
        )
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            "region_name",
            "region_name VARCHAR(160)",
        )
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            "city_name",
            "city_name VARCHAR(160)",
        )

    if _table_exists(connection, "branches"):
        _execute(
            connection,
            """
            UPDATE branches
            SET region_name = location
            WHERE (region_name IS NULL OR TRIM(region_name) = '')
              AND location IS NOT NULL
              AND TRIM(location) != ''
            """,
        )
        _execute(
            connection,
            """
            UPDATE branches
            SET country_code = 'SA', country_name = 'Saudi Arabia'
            WHERE LOWER(TRIM(COALESCE(location, ''))) IN (
                'riyadh', 'riyadh region', 'makkah', 'makkah region',
                'madinah', 'madinah region',
                'eastern province', 'al qassim region', 'hail region',
                'qassim', 'ha''il', 'tabuk', 'tabuk region',
                'northern borders', 'northern borders region',
                'al jawf', 'al jawf region', 'jazan', 'jazan region',
                'najran', 'najran region', 'al bahah', 'al bahah region',
                'asir', 'asir region'
            )
            """,
        )

    if _table_exists(connection, "school_groups") and _table_exists(connection, "branches"):
        _execute(
            connection,
            """
            UPDATE school_groups
            SET country_code = 'SA', country_name = 'Saudi Arabia'
            WHERE (country_code IS NULL OR TRIM(country_code) = '')
              AND EXISTS (
                  SELECT 1
                  FROM branches
                  WHERE branches.school_group_id = school_groups.id
                    AND branches.country_code = 'SA'
              )
            """,
        )


def _phase1_address_detail_columns(engine, connection):
    for table_name in ("school_groups", "branches"):
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            "district_name",
            "district_name VARCHAR(160)",
        )
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            "neighborhood_name",
            "neighborhood_name VARCHAR(160)",
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
    Migration(
        migration_id="20260615_001_demo_request_seen_columns",
        description="Track viewed demo requests for sidebar unread counts",
        apply=_demo_request_seen_columns,
    ),
    Migration(
        migration_id="20260615_002_system_design_settings",
        description="Create developer-controlled design settings table",
        apply=_create_system_design_settings_table,
    ),
    Migration(
        migration_id="20260615_003_visual_design_settings",
        description="Create visual design studio component settings table",
        apply=_create_visual_design_settings_table,
    ),
    Migration(
        migration_id="20260619_001_platform_identity_access_scope",
        description="Separate platform identities, tenant roles, positions, and data scope",
        apply=_platform_identity_and_access_scope,
    ),
    Migration(
        migration_id="20260619_002_platform_sqlite_scope_trigger",
        description="Keep SQLite tenant user guards while allowing unassigned platform identities",
        apply=_sqlite_platform_user_scope_trigger,
    ),
    Migration(
        migration_id="20260619_003_organization_read_only_positions",
        description="Force Education Excellence and Management to Limited organization access",
        apply=_normalize_organization_read_only_users,
    ),
    Migration(
        migration_id="20260620_001_platform_hierarchy_permissions",
        description="Add owner hierarchy and per-developer platform permissions",
        apply=_platform_hierarchy_and_permissions,
    ),
    Migration(
        migration_id="20260620_002_global_location_columns",
        description="Add country, region, and city fields for organizations and branches",
        apply=_global_location_columns,
    ),
    Migration(
        migration_id="20260620_003_phase1_address_details",
        description="Add optional district and neighborhood fields to organizations and branches",
        apply=_phase1_address_detail_columns,
    ),
    Migration(
        migration_id="20260622_001_identity_foundation",
        description="Add canonical email identity fields and login audit timestamps",
        apply=_identity_foundation,
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
