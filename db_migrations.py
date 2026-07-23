import logging
import unicodedata
import uuid
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


def _check_constraint_exists(bind, table_name: str, constraint_name: str) -> bool:
    if not _table_exists(bind, table_name):
        return False
    return any(
        constraint.get("name") == constraint_name
        for constraint in inspect(bind).get_check_constraints(table_name)
    )


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

    if _column_exists(connection, "school_groups", "workspace_uuid"):
        _execute(
            connection,
            """
            INSERT INTO school_groups (
                name, workspace_uuid, workspace_classification,
                workspace_lifecycle_status, status, created_at, updated_at
            ) VALUES (
                :name, :workspace_uuid, 'internal_sandbox',
                'active', :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {
                "name": "Al-Andalus Schools",
                "workspace_uuid": str(uuid.uuid4()),
                "status": True,
            },
        )
    else:
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


def _saas_identity_foundation(engine, connection):
    datetime_type = _datetime_type(engine)
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_accounts (
            id INTEGER PRIMARY KEY,
            account_uuid VARCHAR(36) NOT NULL,
            email VARCHAR(180) NOT NULL,
            email_normalized VARCHAR(180) NOT NULL,
            password_hash VARCHAR(255),
            first_name VARCHAR(120),
            last_name VARCHAR(120),
            status VARCHAR(20) NOT NULL DEFAULT 'pending_verification',
            onboarding_status VARCHAR(30) NOT NULL DEFAULT 'not_started',
            email_verified_at {datetime_type},
            last_login_at {datetime_type},
            locked_at {datetime_type},
            locked_reason VARCHAR(120),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "saas_accounts", "uq_saas_accounts_email_normalized", "email_normalized")
    _create_unique_index_if_missing(connection, connection, "saas_accounts", "uq_saas_accounts_account_uuid", "account_uuid")
    _create_index_if_missing(connection, connection, "saas_accounts", "ix_saas_accounts_status", "status")
    _create_index_if_missing(connection, connection, "saas_accounts", "ix_saas_accounts_onboarding_status", "onboarding_status")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_auth_identities (
            id INTEGER PRIMARY KEY,
            saas_account_id INTEGER NOT NULL,
            provider VARCHAR(30) NOT NULL,
            provider_subject VARCHAR(255) NOT NULL,
            provider_email VARCHAR(180),
            provider_email_normalized VARCHAR(180),
            provider_tenant_hint VARCHAR(255),
            provider_profile_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "saas_auth_identities",
        "uq_saas_auth_identities_provider_subject",
        "provider, provider_subject",
    )
    _create_index_if_missing(connection, connection, "saas_auth_identities", "ix_saas_auth_identities_account", "saas_account_id")
    _create_index_if_missing(
        connection,
        connection,
        "saas_auth_identities",
        "ix_saas_auth_identities_email_normalized",
        "provider_email_normalized",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_sessions (
            id INTEGER PRIMARY KEY,
            saas_account_id INTEGER NOT NULL,
            session_token_hash VARCHAR(128) NOT NULL,
            session_family_id VARCHAR(64) NOT NULL,
            csrf_token_hash VARCHAR(128),
            ip_address VARCHAR(80),
            user_agent VARCHAR(255),
            issued_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at {datetime_type} NOT NULL,
            revoked_at {datetime_type},
            revoke_reason VARCHAR(80),
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "saas_sessions", "uq_saas_sessions_token_hash", "session_token_hash")
    _create_index_if_missing(connection, connection, "saas_sessions", "ix_saas_sessions_account", "saas_account_id")
    _create_index_if_missing(connection, connection, "saas_sessions", "ix_saas_sessions_expires_at", "expires_at")
    _create_index_if_missing(connection, connection, "saas_sessions", "ix_saas_sessions_revoked_at", "revoked_at")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_email_verification_tokens (
            id INTEGER PRIMARY KEY,
            saas_account_id INTEGER NOT NULL,
            token_hash VARCHAR(128) NOT NULL,
            email_normalized VARCHAR(180) NOT NULL,
            expires_at {datetime_type} NOT NULL,
            consumed_at {datetime_type},
            request_ip VARCHAR(80),
            user_agent VARCHAR(255),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "saas_email_verification_tokens",
        "uq_saas_email_verification_tokens_hash",
        "token_hash",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_email_verification_tokens",
        "ix_saas_email_verification_tokens_account",
        "saas_account_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_email_verification_tokens",
        "ix_saas_email_verification_tokens_expires_at",
        "expires_at",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_email_verification_tokens",
        "ix_saas_email_verification_tokens_account_consumed",
        "saas_account_id, consumed_at",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS blocked_email_domains (
            id INTEGER PRIMARY KEY,
            domain VARCHAR(180) NOT NULL,
            domain_category VARCHAR(20) NOT NULL DEFAULT 'blocked',
            enforcement VARCHAR(20) NOT NULL DEFAULT 'block',
            reason VARCHAR(255),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "blocked_email_domains", "uq_blocked_email_domains_domain", "domain")
    _create_index_if_missing(connection, connection, "blocked_email_domains", "ix_blocked_email_domains_active", "is_active")
    _create_index_if_missing(connection, connection, "blocked_email_domains", "ix_blocked_email_domains_enforcement", "enforcement")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_auth_events (
            id INTEGER PRIMARY KEY,
            saas_account_id INTEGER,
            event_type VARCHAR(40) NOT NULL,
            event_status VARCHAR(20) NOT NULL DEFAULT 'ok',
            ip_address VARCHAR(80),
            user_agent VARCHAR(255),
            details_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_index_if_missing(connection, connection, "saas_auth_events", "ix_saas_auth_events_account", "saas_account_id")
    _create_index_if_missing(connection, connection, "saas_auth_events", "ix_saas_auth_events_event_type", "event_type")
    _create_index_if_missing(connection, connection, "saas_auth_events", "ix_saas_auth_events_created_at", "created_at")

    seeds = (
        ("gmail.com", "personal", "warn", "Common personal email domain"),
        ("outlook.com", "personal", "warn", "Common personal email domain"),
        ("yahoo.com", "personal", "warn", "Common personal email domain"),
        ("hotmail.com", "personal", "warn", "Common personal email domain"),
        ("mailinator.com", "disposable", "block", "Disposable email domains are not permitted."),
        ("guerrillamail.com", "disposable", "block", "Disposable email domains are not permitted."),
        ("10minutemail.com", "disposable", "block", "Disposable email domains are not permitted."),
        ("temp-mail.org", "disposable", "block", "Disposable email domains are not permitted."),
    )
    for domain, category, enforcement, reason in seeds:
        existing = connection.execute(
            text("SELECT id FROM blocked_email_domains WHERE domain = :domain LIMIT 1"),
            {"domain": domain},
        ).scalar()
        if existing:
            _execute(
                connection,
                """
                UPDATE blocked_email_domains
                SET domain_category = :category,
                    enforcement = :enforcement,
                    reason = :reason,
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :row_id
                """,
                {
                    "row_id": existing,
                    "category": category,
                    "enforcement": enforcement,
                    "reason": reason,
                },
            )
        else:
            _execute(
                connection,
                """
                INSERT INTO blocked_email_domains
                    (domain, domain_category, enforcement, reason, is_active, created_at, updated_at)
                VALUES
                    (:domain, :category, :enforcement, :reason, TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                {
                    "domain": domain,
                    "category": category,
                    "enforcement": enforcement,
                    "reason": reason,
                },
            )


def _pending_organizations_zone(engine, connection):
    datetime_type = _datetime_type(engine)
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organizations (
            id INTEGER PRIMARY KEY,
            organization_uuid VARCHAR(36) NOT NULL,
            owner_saas_account_id INTEGER NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'draft',
            onboarding_step VARCHAR(40) NOT NULL DEFAULT 'organization',
            organization_name VARCHAR(160) NOT NULL DEFAULT '',
            legal_name VARCHAR(180),
            website VARCHAR(180),
            primary_domain VARCHAR(180),
            phone VARCHAR(80),
            organization_logo_path VARCHAR(255),
            educational_program VARCHAR(20),
            country_code VARCHAR(2),
            country_name VARCHAR(120),
            region_name VARCHAR(160),
            city_name VARCHAR(160),
            district_name VARCHAR(160),
            neighborhood_name VARCHAR(160),
            school_type VARCHAR(120),
            expected_branch_count INTEGER,
            expected_student_count INTEGER,
            expected_teacher_count INTEGER,
            estimated_staff_users INTEGER,
            timezone VARCHAR(80),
            draft_saved_at {datetime_type},
            submitted_at {datetime_type},
            reviewed_at {datetime_type},
            reviewed_by_user_id VARCHAR(10),
            rejection_reason TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "pending_organizations", "uq_pending_organizations_uuid", "organization_uuid")
    _create_index_if_missing(connection, connection, "pending_organizations", "ix_pending_organizations_owner", "owner_saas_account_id")
    _create_index_if_missing(connection, connection, "pending_organizations", "ix_pending_organizations_status", "status")
    _create_index_if_missing(connection, connection, "pending_organizations", "ix_pending_organizations_step", "onboarding_step")
    _create_index_if_missing(connection, connection, "pending_organizations", "ix_pending_organizations_name", "organization_name")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_branches (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            branch_name VARCHAR(160) NOT NULL,
            location VARCHAR(180),
            country_code VARCHAR(2),
            country_name VARCHAR(120),
            region_name VARCHAR(160),
            city_name VARCHAR(160),
            district_name VARCHAR(160),
            neighborhood_name VARCHAR(160),
            status BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id)
        )
        """,
    )
    _create_index_if_missing(connection, connection, "pending_organization_branches", "ix_pending_organization_branches_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "pending_organization_branches", "ix_pending_organization_branches_order", "pending_organization_id, sort_order")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_academic_setup (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            first_academic_year_name VARCHAR(40) NOT NULL DEFAULT '',
            create_default_branch BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id)
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "pending_organization_academic_setup", "uq_pending_organization_academic_setup_org", "pending_organization_id")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_contacts (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            contact_type VARCHAR(30) NOT NULL DEFAULT 'owner',
            first_name VARCHAR(120) NOT NULL DEFAULT '',
            last_name VARCHAR(120) NOT NULL DEFAULT '',
            job_title VARCHAR(120),
            email VARCHAR(180) NOT NULL DEFAULT '',
            email_normalized VARCHAR(180),
            phone VARCHAR(80),
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id)
        )
        """,
    )
    _create_index_if_missing(connection, connection, "pending_organization_contacts", "ix_pending_organization_contacts_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "pending_organization_contacts", "ix_pending_organization_contacts_email_normalized", "email_normalized")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_progress (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            organization_profile_complete BOOLEAN NOT NULL DEFAULT FALSE,
            branches_complete BOOLEAN NOT NULL DEFAULT FALSE,
            academic_setup_complete BOOLEAN NOT NULL DEFAULT FALSE,
            contacts_complete BOOLEAN NOT NULL DEFAULT FALSE,
            review_complete BOOLEAN NOT NULL DEFAULT FALSE,
            completion_percent INTEGER NOT NULL DEFAULT 0,
            last_completed_step VARCHAR(40),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id)
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "pending_organization_progress", "uq_pending_organization_progress_org", "pending_organization_id")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_events (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            actor_saas_account_id INTEGER,
            event_type VARCHAR(40) NOT NULL,
            details_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (actor_saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_index_if_missing(connection, connection, "pending_organization_events", "ix_pending_organization_events_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "pending_organization_events", "ix_pending_organization_events_type", "event_type")
    _create_index_if_missing(connection, connection, "pending_organization_events", "ix_pending_organization_events_created_at", "created_at")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_notes (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            author_type VARCHAR(20) NOT NULL DEFAULT 'owner',
            author_ref VARCHAR(80),
            note TEXT NOT NULL DEFAULT '',
            is_internal BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id)
        )
        """,
    )
    _create_index_if_missing(connection, connection, "pending_organization_notes", "ix_pending_organization_notes_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "pending_organization_notes", "ix_pending_organization_notes_created_at", "created_at")


def _plans_pricing_billing_foundation(engine, connection):
    datetime_type = _datetime_type(engine)

    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "billing_status",
        "billing_status VARCHAR(30) NOT NULL DEFAULT 'not_started'",
    )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "selected_plan_id",
        "selected_plan_id INTEGER",
    )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "selected_billing_interval",
        "selected_billing_interval VARCHAR(20)",
    )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "checkout_ready_at",
        f"checkout_ready_at {datetime_type}",
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organizations",
        "ix_pending_organizations_selected_plan_id",
        "selected_plan_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organizations",
        "ix_pending_organizations_billing_status",
        "billing_status",
    )
    if _table_exists(connection, "pending_organizations"):
        _execute(
            connection,
            """
            UPDATE pending_organizations
            SET billing_status = 'not_started'
            WHERE billing_status IS NULL OR TRIM(billing_status) = ''
            """,
        )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS subscription_plans (
            id INTEGER PRIMARY KEY,
            plan_code VARCHAR(40) NOT NULL,
            plan_name VARCHAR(120) NOT NULL,
            plan_family VARCHAR(80),
            description TEXT,
            badge_text VARCHAR(60),
            is_most_popular BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_public BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            max_branches INTEGER,
            max_staff_users INTEGER,
            ai_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            multi_branch_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            advanced_reporting_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            priority_support BOOLEAN NOT NULL DEFAULT FALSE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "subscription_plans",
        "uq_subscription_plans_code",
        "plan_code",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_plans",
        "ix_subscription_plans_active",
        "is_active",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_plans",
        "ix_subscription_plans_public",
        "is_public",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_plans",
        "ix_subscription_plans_sort_order",
        "sort_order",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS subscription_plan_prices (
            id INTEGER PRIMARY KEY,
            plan_id INTEGER NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,
            currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
            amount_minor INTEGER NOT NULL,
            compare_at_amount_minor INTEGER,
            display_savings_percent INTEGER,
            display_savings_amount_minor INTEGER,
            plan_version INTEGER NOT NULL DEFAULT 1,
            is_founding_offer BOOLEAN NOT NULL DEFAULT FALSE,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            effective_from {datetime_type},
            effective_to {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (plan_id) REFERENCES subscription_plans (id)
        )
        """,
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_plan_prices",
        "ix_subscription_plan_prices_plan",
        "plan_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_plan_prices",
        "ix_subscription_plan_prices_active",
        "is_active",
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "subscription_plan_prices",
        "uq_subscription_plan_prices_version",
        "plan_id, billing_interval, currency_code, plan_version",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS currency_profiles (
            id INTEGER PRIMARY KEY,
            currency_code VARCHAR(3) NOT NULL,
            currency_name VARCHAR(60) NOT NULL,
            currency_symbol VARCHAR(8) NOT NULL,
            minor_unit INTEGER NOT NULL DEFAULT 2,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "currency_profiles",
        "uq_currency_profiles_code",
        "currency_code",
    )
    _create_index_if_missing(
        connection,
        connection,
        "currency_profiles",
        "ix_currency_profiles_active",
        "is_active",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS country_currency_map (
            id INTEGER PRIMARY KEY,
            country_code VARCHAR(2) NOT NULL,
            currency_code VARCHAR(3) NOT NULL,
            display_locale VARCHAR(20),
            usd_display_rate NUMERIC(12, 6) NOT NULL DEFAULT 1,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (currency_code) REFERENCES currency_profiles (currency_code)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "country_currency_map",
        "uq_country_currency_map_country",
        "country_code",
    )
    _create_index_if_missing(
        connection,
        connection,
        "country_currency_map",
        "ix_country_currency_map_currency",
        "currency_code",
    )
    _create_index_if_missing(
        connection,
        connection,
        "country_currency_map",
        "ix_country_currency_map_active",
        "is_active",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS pending_organization_plan_selections (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            plan_id INTEGER NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,
            base_currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
            base_amount_minor INTEGER NOT NULL,
            display_currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
            display_amount_minor INTEGER NOT NULL,
            display_exchange_rate NUMERIC(12, 6) NOT NULL DEFAULT 1,
            annual_savings_amount_minor INTEGER,
            annual_savings_percent INTEGER,
            plan_version INTEGER NOT NULL DEFAULT 1,
            is_founding_offer BOOLEAN NOT NULL DEFAULT FALSE,
            selection_status VARCHAR(20) NOT NULL DEFAULT 'selected',
            selected_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (plan_id) REFERENCES subscription_plans (id)
        )
        """,
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organization_plan_selections",
        "ix_pending_organization_plan_selections_org",
        "pending_organization_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organization_plan_selections",
        "ix_pending_organization_plan_selections_status",
        "selection_status",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS checkout_sessions (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            plan_selection_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'not_started',
            provider VARCHAR(30),
            provider_checkout_id VARCHAR(120),
            currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
            amount_minor INTEGER NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,
            started_at {datetime_type},
            expires_at {datetime_type},
            abandoned_at {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (plan_selection_id) REFERENCES pending_organization_plan_selections (id)
        )
        """,
    )
    _create_index_if_missing(
        connection,
        connection,
        "checkout_sessions",
        "ix_checkout_sessions_org",
        "pending_organization_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "checkout_sessions",
        "ix_checkout_sessions_status",
        "status",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS subscription_contracts (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            school_group_id INTEGER,
            plan_id INTEGER NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,
            contract_status VARCHAR(30) NOT NULL DEFAULT 'draft',
            base_currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
            base_amount_minor INTEGER NOT NULL,
            display_currency_code VARCHAR(3) NOT NULL DEFAULT 'USD',
            display_amount_minor INTEGER NOT NULL,
            selected_checkout_session_id INTEGER,
            contract_type VARCHAR(30) NOT NULL DEFAULT 'self_serve',
            plan_version INTEGER NOT NULL DEFAULT 1,
            is_founding_offer BOOLEAN NOT NULL DEFAULT FALSE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (plan_id) REFERENCES subscription_plans (id),
            FOREIGN KEY (selected_checkout_session_id) REFERENCES checkout_sessions (id)
        )
        """,
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_contracts",
        "ix_subscription_contracts_pending_org",
        "pending_organization_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_contracts",
        "ix_subscription_contracts_status",
        "contract_status",
    )

    plan_rows = (
        {
            "plan_code": "starter",
            "plan_name": "Starter",
            "description": "Starter plan for smaller schools beginning with TIS SaaS.",
            "badge_text": None,
            "is_most_popular": False,
            "sort_order": 10,
            "max_branches": 1,
            "max_staff_users": 25,
            "ai_enabled": False,
            "multi_branch_enabled": False,
            "advanced_reporting_enabled": False,
            "priority_support": False,
        },
        {
            "plan_code": "professional",
            "plan_name": "Professional",
            "description": "Professional plan for growing schools and multi-campus operations.",
            "badge_text": "Most Popular",
            "is_most_popular": True,
            "sort_order": 20,
            "max_branches": 5,
            "max_staff_users": 100,
            "ai_enabled": False,
            "multi_branch_enabled": True,
            "advanced_reporting_enabled": True,
            "priority_support": False,
        },
        {
            "plan_code": "enterprise_ai",
            "plan_name": "Enterprise AI",
            "description": "Enterprise AI plan for larger organizations requiring advanced support.",
            "badge_text": "AI Enabled",
            "is_most_popular": False,
            "sort_order": 30,
            "max_branches": 25,
            "max_staff_users": 500,
            "ai_enabled": True,
            "multi_branch_enabled": True,
            "advanced_reporting_enabled": True,
            "priority_support": True,
        },
    )
    for plan in plan_rows:
        existing_id = connection.execute(
            text("SELECT id FROM subscription_plans WHERE plan_code = :plan_code LIMIT 1"),
            {"plan_code": plan["plan_code"]},
        ).scalar()
        params = {
            "plan_code": plan["plan_code"],
            "plan_name": plan["plan_name"],
            "plan_family": "standard",
            "description": plan["description"],
            "badge_text": plan["badge_text"],
            "is_most_popular": plan["is_most_popular"],
            "is_active": True,
            "is_public": True,
            "sort_order": plan["sort_order"],
            "max_branches": plan["max_branches"],
            "max_staff_users": plan["max_staff_users"],
            "ai_enabled": plan["ai_enabled"],
            "multi_branch_enabled": plan["multi_branch_enabled"],
            "advanced_reporting_enabled": plan["advanced_reporting_enabled"],
            "priority_support": plan["priority_support"],
        }
        if existing_id:
            _execute(
                connection,
                """
                UPDATE subscription_plans
                SET plan_name = :plan_name,
                    plan_family = :plan_family,
                    description = :description,
                    badge_text = :badge_text,
                    is_most_popular = :is_most_popular,
                    is_active = :is_active,
                    is_public = :is_public,
                    sort_order = :sort_order,
                    max_branches = :max_branches,
                    max_staff_users = :max_staff_users,
                    ai_enabled = :ai_enabled,
                    multi_branch_enabled = :multi_branch_enabled,
                    advanced_reporting_enabled = :advanced_reporting_enabled,
                    priority_support = :priority_support,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :row_id
                """,
                {**params, "row_id": existing_id},
            )
        else:
            _execute(
                connection,
                """
                INSERT INTO subscription_plans (
                    plan_code, plan_name, plan_family, description, badge_text,
                    is_most_popular, is_active, is_public, sort_order,
                    max_branches, max_staff_users, ai_enabled, multi_branch_enabled,
                    advanced_reporting_enabled, priority_support, created_at, updated_at
                ) VALUES (
                    :plan_code, :plan_name, :plan_family, :description, :badge_text,
                    :is_most_popular, :is_active, :is_public, :sort_order,
                    :max_branches, :max_staff_users, :ai_enabled, :multi_branch_enabled,
                    :advanced_reporting_enabled, :priority_support, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                params,
            )

    price_rows = (
        ("starter", "monthly", 2900, None, None),
        ("starter", "annual", 29000, 5800, 17),
        ("professional", "monthly", 7900, None, None),
        ("professional", "annual", 79000, 15800, 17),
        ("enterprise_ai", "monthly", 14900, None, None),
        ("enterprise_ai", "annual", 149000, 29800, 17),
    )
    for plan_code, interval, amount_minor, savings_minor, savings_percent in price_rows:
        plan_id = connection.execute(
            text("SELECT id FROM subscription_plans WHERE plan_code = :plan_code LIMIT 1"),
            {"plan_code": plan_code},
        ).scalar()
        if not plan_id:
            continue
        existing_price_id = connection.execute(
            text(
                """
                SELECT id FROM subscription_plan_prices
                WHERE plan_id = :plan_id
                  AND billing_interval = :billing_interval
                  AND currency_code = 'USD'
                  AND plan_version = 1
                LIMIT 1
                """
            ),
            {"plan_id": plan_id, "billing_interval": interval},
        ).scalar()
        price_params = {
            "plan_id": int(plan_id),
            "billing_interval": interval,
            "currency_code": "USD",
            "amount_minor": amount_minor,
            "compare_at_amount_minor": (amount_minor + savings_minor) if savings_minor else None,
            "display_savings_percent": savings_percent,
            "display_savings_amount_minor": savings_minor,
            "plan_version": 1,
            "is_founding_offer": True,
            "is_active": True,
        }
        if existing_price_id:
            _execute(
                connection,
                """
                UPDATE subscription_plan_prices
                SET amount_minor = :amount_minor,
                    compare_at_amount_minor = :compare_at_amount_minor,
                    display_savings_percent = :display_savings_percent,
                    display_savings_amount_minor = :display_savings_amount_minor,
                    is_founding_offer = :is_founding_offer,
                    is_active = :is_active,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :row_id
                """,
                {**price_params, "row_id": existing_price_id},
            )
        else:
            _execute(
                connection,
                """
                INSERT INTO subscription_plan_prices (
                    plan_id, billing_interval, currency_code, amount_minor,
                    compare_at_amount_minor, display_savings_percent,
                    display_savings_amount_minor, plan_version, is_founding_offer,
                    is_active, created_at, updated_at
                ) VALUES (
                    :plan_id, :billing_interval, :currency_code, :amount_minor,
                    :compare_at_amount_minor, :display_savings_percent,
                    :display_savings_amount_minor, :plan_version, :is_founding_offer,
                    :is_active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                price_params,
            )

    currency_rows = (
        ("USD", "US Dollar", "$", 2),
        ("SAR", "Saudi Riyal", "SAR ", 2),
        ("AED", "UAE Dirham", "AED ", 2),
        ("QAR", "Qatari Riyal", "QAR ", 2),
        ("EGP", "Egyptian Pound", "EGP ", 2),
        ("EUR", "Euro", "EUR ", 2),
    )
    for code, name, symbol, minor_unit in currency_rows:
        existing_currency_id = connection.execute(
            text("SELECT id FROM currency_profiles WHERE currency_code = :currency_code LIMIT 1"),
            {"currency_code": code},
        ).scalar()
        currency_params = {
            "currency_code": code,
            "currency_name": name,
            "currency_symbol": symbol,
            "minor_unit": minor_unit,
        }
        if existing_currency_id:
            _execute(
                connection,
                """
                UPDATE currency_profiles
                SET currency_name = :currency_name,
                    currency_symbol = :currency_symbol,
                    minor_unit = :minor_unit,
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :row_id
                """,
                {**currency_params, "row_id": existing_currency_id},
            )
        else:
            _execute(
                connection,
                """
                INSERT INTO currency_profiles (
                    currency_code, currency_name, currency_symbol, minor_unit,
                    is_active, created_at, updated_at
                ) VALUES (
                    :currency_code, :currency_name, :currency_symbol, :minor_unit,
                    TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                currency_params,
            )

    country_rows = (
        ("US", "USD", "en-US", "1.000000"),
        ("SA", "SAR", "ar-SA", "3.750000"),
        ("AE", "AED", "ar-AE", "3.670000"),
        ("QA", "QAR", "ar-QA", "3.640000"),
        ("EG", "EGP", "ar-EG", "48.000000"),
        ("DE", "EUR", "de-DE", "0.920000"),
        ("FR", "EUR", "fr-FR", "0.920000"),
        ("ES", "EUR", "es-ES", "0.920000"),
        ("IT", "EUR", "it-IT", "0.920000"),
        ("NL", "EUR", "nl-NL", "0.920000"),
    )
    for country_code, currency_code, locale, usd_display_rate in country_rows:
        existing_map_id = connection.execute(
            text("SELECT id FROM country_currency_map WHERE country_code = :country_code LIMIT 1"),
            {"country_code": country_code},
        ).scalar()
        map_params = {
            "country_code": country_code,
            "currency_code": currency_code,
            "display_locale": locale,
            "usd_display_rate": usd_display_rate,
        }
        if existing_map_id:
            _execute(
                connection,
                """
                UPDATE country_currency_map
                SET currency_code = :currency_code,
                    display_locale = :display_locale,
                    usd_display_rate = :usd_display_rate,
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :row_id
                """,
                {**map_params, "row_id": existing_map_id},
            )
        else:
            _execute(
                connection,
                """
                INSERT INTO country_currency_map (
                    country_code, currency_code, display_locale, usd_display_rate,
                    is_active, created_at, updated_at
                ) VALUES (
                    :country_code, :currency_code, :display_locale, :usd_display_rate,
                    TRUE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                map_params,
            )


def _paddle_payment_collection(engine, connection):
    datetime_type = _datetime_type(engine)

    _add_column_if_missing(
        connection,
        connection,
        "subscription_plan_prices",
        "provider_price_id",
        "provider_price_id VARCHAR(120)",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_plan_prices",
        "ix_subscription_plan_prices_provider_price_id",
        "provider_price_id",
    )

    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "payment_status",
        "payment_status VARCHAR(30) NOT NULL DEFAULT 'pending'",
    )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "payment_confirmed_at",
        f"payment_confirmed_at {datetime_type}",
    )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "payment_failed_at",
        f"payment_failed_at {datetime_type}",
    )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "last_payment_attempt_id",
        "last_payment_attempt_id INTEGER",
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organizations",
        "ix_pending_organizations_payment_status",
        "payment_status",
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organizations",
        "ix_pending_organizations_last_payment_attempt_id",
        "last_payment_attempt_id",
    )
    if _table_exists(connection, "pending_organizations"):
        _execute(
            connection,
            """
            UPDATE pending_organizations
            SET payment_status = 'pending'
            WHERE payment_status IS NULL OR TRIM(payment_status) = ''
            """,
        )

    _add_column_if_missing(
        connection,
        connection,
        "checkout_sessions",
        "checkout_url",
        "checkout_url TEXT",
    )
    _add_column_if_missing(
        connection,
        connection,
        "checkout_sessions",
        "provider_price_id",
        "provider_price_id VARCHAR(120)",
    )
    _add_column_if_missing(
        connection,
        connection,
        "checkout_sessions",
        "last_payment_attempt_id",
        "last_payment_attempt_id INTEGER",
    )
    _create_index_if_missing(
        connection,
        connection,
        "checkout_sessions",
        "ix_checkout_sessions_last_payment_attempt_id",
        "last_payment_attempt_id",
    )

    _add_column_if_missing(
        connection,
        connection,
        "subscription_contracts",
        "payment_status",
        "payment_status VARCHAR(30) NOT NULL DEFAULT 'pending'",
    )
    _add_column_if_missing(
        connection,
        connection,
        "subscription_contracts",
        "paid_at",
        f"paid_at {datetime_type}",
    )
    _add_column_if_missing(
        connection,
        connection,
        "subscription_contracts",
        "payment_provider",
        "payment_provider VARCHAR(30)",
    )
    _create_index_if_missing(
        connection,
        connection,
        "subscription_contracts",
        "ix_subscription_contracts_payment_status",
        "payment_status",
    )
    if _table_exists(connection, "subscription_contracts"):
        _execute(
            connection,
            """
            UPDATE subscription_contracts
            SET payment_status = 'pending'
            WHERE payment_status IS NULL OR TRIM(payment_status) = ''
            """,
        )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS payment_customers (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER,
            saas_account_id INTEGER NOT NULL,
            provider VARCHAR(30) NOT NULL DEFAULT 'paddle',
            provider_customer_id VARCHAR(120) NOT NULL,
            email VARCHAR(180),
            name VARCHAR(180),
            country_code VARCHAR(2),
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "payment_customers",
        "uq_payment_customers_provider_customer_id",
        "provider_customer_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "payment_customers",
        "ix_payment_customers_pending_org",
        "pending_organization_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "payment_customers",
        "ix_payment_customers_saas_account",
        "saas_account_id",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS payment_attempts (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            checkout_session_id INTEGER NOT NULL,
            plan_selection_id INTEGER NOT NULL,
            payment_customer_id INTEGER,
            provider VARCHAR(30) NOT NULL DEFAULT 'paddle',
            attempt_uuid VARCHAR(36) NOT NULL,
            provider_checkout_id VARCHAR(120),
            provider_transaction_id VARCHAR(120),
            provider_subscription_id VARCHAR(120),
            status VARCHAR(30) NOT NULL DEFAULT 'checkout_started',
            currency_code VARCHAR(3),
            amount_minor INTEGER,
            billing_interval VARCHAR(20) NOT NULL,
            started_at {datetime_type},
            expires_at {datetime_type},
            completed_at {datetime_type},
            failed_at {datetime_type},
            cancelled_at {datetime_type},
            failure_reason TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (checkout_session_id) REFERENCES checkout_sessions (id),
            FOREIGN KEY (plan_selection_id) REFERENCES pending_organization_plan_selections (id),
            FOREIGN KEY (payment_customer_id) REFERENCES payment_customers (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "payment_attempts",
        "uq_payment_attempts_attempt_uuid",
        "attempt_uuid",
    )
    _create_index_if_missing(connection, connection, "payment_attempts", "ix_payment_attempts_pending_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "payment_attempts", "ix_payment_attempts_checkout_session", "checkout_session_id")
    _create_index_if_missing(connection, connection, "payment_attempts", "ix_payment_attempts_status", "status")
    _create_index_if_missing(connection, connection, "payment_attempts", "ix_payment_attempts_provider_transaction_id", "provider_transaction_id")
    _create_index_if_missing(connection, connection, "payment_attempts", "ix_payment_attempts_provider_subscription_id", "provider_subscription_id")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS payment_subscriptions (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            subscription_contract_id INTEGER NOT NULL,
            payment_customer_id INTEGER,
            provider VARCHAR(30) NOT NULL DEFAULT 'paddle',
            provider_subscription_id VARCHAR(120) NOT NULL,
            provider_price_id VARCHAR(120),
            plan_id INTEGER NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'pending',
            current_period_start {datetime_type},
            current_period_end {datetime_type},
            next_billed_at {datetime_type},
            cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
            cancelled_at {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (subscription_contract_id) REFERENCES subscription_contracts (id),
            FOREIGN KEY (payment_customer_id) REFERENCES payment_customers (id),
            FOREIGN KEY (plan_id) REFERENCES subscription_plans (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "payment_subscriptions",
        "uq_payment_subscriptions_provider_subscription_id",
        "provider_subscription_id",
    )
    _create_index_if_missing(connection, connection, "payment_subscriptions", "ix_payment_subscriptions_pending_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "payment_subscriptions", "ix_payment_subscriptions_contract", "subscription_contract_id")
    _create_index_if_missing(connection, connection, "payment_subscriptions", "ix_payment_subscriptions_status", "status")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS payment_webhooks (
            id INTEGER PRIMARY KEY,
            provider VARCHAR(30) NOT NULL DEFAULT 'paddle',
            provider_event_id VARCHAR(120),
            event_type VARCHAR(80),
            signature_valid BOOLEAN NOT NULL DEFAULT FALSE,
            delivery_attempt INTEGER NOT NULL DEFAULT 1,
            payload_hash VARCHAR(128),
            headers_json TEXT,
            payload_json TEXT,
            received_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            processed_at {datetime_type},
            processing_status VARCHAR(30) NOT NULL DEFAULT 'pending',
            processing_error TEXT
        )
        """,
    )
    if not _index_exists(connection, "payment_webhooks", "uq_payment_webhooks_provider_event_id"):
        _execute(
            connection,
            """
            CREATE UNIQUE INDEX uq_payment_webhooks_provider_event_id
            ON payment_webhooks (provider_event_id)
            WHERE provider_event_id IS NOT NULL
            """,
        )
    _create_index_if_missing(connection, connection, "payment_webhooks", "ix_payment_webhooks_event_type", "event_type")
    _create_index_if_missing(connection, connection, "payment_webhooks", "ix_payment_webhooks_processing_status", "processing_status")
    _create_index_if_missing(connection, connection, "payment_webhooks", "ix_payment_webhooks_received_at", "received_at")


def _saas_password_reset_tokens(engine, connection):
    datetime_type = _datetime_type(engine)
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_password_reset_tokens (
            id INTEGER PRIMARY KEY,
            saas_account_id INTEGER NOT NULL,
            token_hash VARCHAR(128) NOT NULL,
            email_normalized VARCHAR(180) NOT NULL,
            expires_at {datetime_type} NOT NULL,
            consumed_at {datetime_type},
            request_ip VARCHAR(80),
            user_agent VARCHAR(255),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "saas_password_reset_tokens",
        "uq_saas_password_reset_tokens_hash",
        "token_hash",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_password_reset_tokens",
        "ix_saas_password_reset_tokens_account",
        "saas_account_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_password_reset_tokens",
        "ix_saas_password_reset_tokens_expires_at",
        "expires_at",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_password_reset_tokens",
        "ix_saas_password_reset_tokens_account_consumed",
        "saas_account_id, consumed_at",
    )


def _phase5_provisioning_engine(engine, connection):
    datetime_type = _datetime_type(engine)

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS tenant_profiles (
            id INTEGER PRIMARY KEY,
            school_group_id INTEGER NOT NULL,
            website VARCHAR(180),
            timezone VARCHAR(80),
            educational_program VARCHAR(20),
            school_type VARCHAR(120),
            estimated_staff_users INTEGER,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "tenant_profiles",
        "uq_tenant_profiles_school_group",
        "school_group_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "tenant_profiles",
        "ix_tenant_profiles_school_group",
        "school_group_id",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS tenant_provisioning_links (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            subscription_contract_id INTEGER NOT NULL,
            school_group_id INTEGER NOT NULL,
            owner_operational_user_id INTEGER NOT NULL,
            primary_branch_id INTEGER,
            primary_academic_year_id INTEGER,
            tenant_status VARCHAR(30) NOT NULL DEFAULT 'tenant_active',
            activated_at {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (subscription_contract_id) REFERENCES subscription_contracts (id),
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (owner_operational_user_id) REFERENCES users (id),
            FOREIGN KEY (primary_branch_id) REFERENCES branches (id),
            FOREIGN KEY (primary_academic_year_id) REFERENCES academic_years (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "tenant_provisioning_links",
        "uq_tenant_provisioning_links_pending_org",
        "pending_organization_id",
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "tenant_provisioning_links",
        "uq_tenant_provisioning_links_contract",
        "subscription_contract_id",
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "tenant_provisioning_links",
        "uq_tenant_provisioning_links_school_group",
        "school_group_id",
    )
    _create_index_if_missing(
        connection,
        connection,
        "tenant_provisioning_links",
        "ix_tenant_provisioning_links_status",
        "tenant_status",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_account_user_links (
            id INTEGER PRIMARY KEY,
            saas_account_id INTEGER NOT NULL,
            operational_user_id INTEGER NOT NULL,
            pending_organization_id INTEGER,
            school_group_id INTEGER NOT NULL,
            link_type VARCHAR(30) NOT NULL DEFAULT 'tenant_owner',
            linked_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (saas_account_id) REFERENCES saas_accounts (id),
            FOREIGN KEY (operational_user_id) REFERENCES users (id),
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection,
        connection,
        "saas_account_user_links",
        "uq_saas_account_user_links_account_user_group",
        "saas_account_id, operational_user_id, school_group_id",
    )
    _create_index_if_missing(connection, connection, "saas_account_user_links", "ix_saas_account_user_links_account", "saas_account_id")
    _create_index_if_missing(connection, connection, "saas_account_user_links", "ix_saas_account_user_links_user", "operational_user_id")
    _create_index_if_missing(connection, connection, "saas_account_user_links", "ix_saas_account_user_links_school_group", "school_group_id")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS provisioning_jobs (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            subscription_contract_id INTEGER NOT NULL,
            job_uuid VARCHAR(36) NOT NULL,
            idempotency_key VARCHAR(160) NOT NULL,
            job_type VARCHAR(40) NOT NULL DEFAULT 'tenant_provisioning',
            trigger_source VARCHAR(40) NOT NULL DEFAULT 'payment_webhook',
            job_status VARCHAR(30) NOT NULL DEFAULT 'queued',
            target_school_group_id INTEGER,
            tenant_provisioning_link_id INTEGER,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            next_attempt_at {datetime_type},
            started_at {datetime_type},
            completed_at {datetime_type},
            failed_at {datetime_type},
            last_error TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (subscription_contract_id) REFERENCES subscription_contracts (id),
            FOREIGN KEY (target_school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (tenant_provisioning_link_id) REFERENCES tenant_provisioning_links (id)
        )
        """,
    )
    _create_unique_index_if_missing(connection, connection, "provisioning_jobs", "uq_provisioning_jobs_job_uuid", "job_uuid")
    _create_unique_index_if_missing(connection, connection, "provisioning_jobs", "uq_provisioning_jobs_idempotency_key", "idempotency_key")
    _create_index_if_missing(connection, connection, "provisioning_jobs", "ix_provisioning_jobs_pending_org", "pending_organization_id")
    _create_index_if_missing(connection, connection, "provisioning_jobs", "ix_provisioning_jobs_status", "job_status")
    _create_index_if_missing(connection, connection, "provisioning_jobs", "ix_provisioning_jobs_next_attempt_at", "next_attempt_at")

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS provisioning_job_events (
            id INTEGER PRIMARY KEY,
            provisioning_job_id INTEGER NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            event_status VARCHAR(20) NOT NULL DEFAULT 'ok',
            details_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provisioning_job_id) REFERENCES provisioning_jobs (id)
        )
        """,
    )
    _create_index_if_missing(connection, connection, "provisioning_job_events", "ix_provisioning_job_events_job", "provisioning_job_id")
    _create_index_if_missing(connection, connection, "provisioning_job_events", "ix_provisioning_job_events_type", "event_type")
    _create_index_if_missing(connection, connection, "provisioning_job_events", "ix_provisioning_job_events_created_at", "created_at")


def _branch_billing_quote_foundation(engine, connection):
    _add_column_if_missing(
        connection, connection, "pending_organization_branches", "branch_uuid", "branch_uuid VARCHAR(36)"
    )
    if _table_exists(connection, "pending_organization_branches"):
        rows = connection.execute(text(
            "SELECT id FROM pending_organization_branches WHERE branch_uuid IS NULL OR TRIM(branch_uuid) = ''"
        )).all()
        for row in rows:
            connection.execute(
                text("UPDATE pending_organization_branches SET branch_uuid = :branch_uuid WHERE id = :row_id"),
                {"branch_uuid": str(uuid.uuid4()), "row_id": int(row[0])},
            )
    _create_unique_index_if_missing(
        connection,
        connection,
        "pending_organization_branches",
        "uq_pending_organization_branches_uuid",
        "branch_uuid",
    )

    for table_name in (
        "pending_organization_plan_selections",
        "checkout_sessions",
        "subscription_contracts",
    ):
        _add_column_if_missing(
            connection, connection, table_name, "billable_branch_count", "billable_branch_count INTEGER NOT NULL DEFAULT 0"
        )
        _add_column_if_missing(
            connection, connection, table_name, "quoted_base_amount_minor", "quoted_base_amount_minor INTEGER"
        )
        _add_column_if_missing(
            connection, connection, table_name, "quoted_display_amount_minor", "quoted_display_amount_minor INTEGER"
        )
        _add_column_if_missing(
            connection, connection, table_name, "quote_fingerprint", "quote_fingerprint VARCHAR(64)"
        )
        _create_index_if_missing(
            connection,
            connection,
            table_name,
            f"ix_{table_name}_quote_fingerprint",
            "quote_fingerprint",
        )


def _paddle_branch_quantity_reconciliation(engine, connection):
    for table_name in ("payment_attempts", "payment_subscriptions"):
        _add_column_if_missing(
            connection, connection, table_name, "provider_price_id", "provider_price_id VARCHAR(120)"
        )
        _add_column_if_missing(
            connection, connection, table_name, "quantity", "quantity INTEGER NOT NULL DEFAULT 0"
        )
        _add_column_if_missing(
            connection, connection, table_name, "unit_amount_minor", "unit_amount_minor INTEGER"
        )
        _add_column_if_missing(
            connection, connection, table_name, "amount_minor", "amount_minor INTEGER"
        )
        _add_column_if_missing(
            connection, connection, table_name, "currency_code", "currency_code VARCHAR(3)"
        )
        _add_column_if_missing(
            connection, connection, table_name, "quote_fingerprint", "quote_fingerprint VARCHAR(64)"
        )
        _create_index_if_missing(
            connection,
            connection,
            table_name,
            f"ix_{table_name}_quote_fingerprint",
            "quote_fingerprint",
        )


def _draft_account_lifecycle_foundation(engine, connection):
    datetime_type = _datetime_type(engine)
    account_columns = (
        ("last_meaningful_activity_at", f"last_meaningful_activity_at {datetime_type}"),
        ("first_reminder_sent_at", f"first_reminder_sent_at {datetime_type}"),
        ("second_reminder_sent_at", f"second_reminder_sent_at {datetime_type}"),
        ("final_reminder_sent_at", f"final_reminder_sent_at {datetime_type}"),
        ("recovered_after_reminder_at", f"recovered_after_reminder_at {datetime_type}"),
        ("reminder_cycle", "reminder_cycle INTEGER NOT NULL DEFAULT 1"),
    )
    for column_name, column_sql in account_columns:
        _add_column_if_missing(
            connection, connection, "saas_accounts", column_name, column_sql
        )
    _add_column_if_missing(
        connection,
        connection,
        "pending_organizations",
        "last_meaningful_activity_at",
        f"last_meaningful_activity_at {datetime_type}",
    )
    _create_index_if_missing(
        connection,
        connection,
        "saas_accounts",
        "ix_saas_accounts_last_meaningful_activity",
        "last_meaningful_activity_at",
    )
    _create_index_if_missing(
        connection,
        connection,
        "pending_organizations",
        "ix_pending_organizations_last_meaningful_activity",
        "last_meaningful_activity_at",
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_draft_lifecycle_settings (
            id INTEGER PRIMARY KEY,
            first_reminder_hours INTEGER NOT NULL DEFAULT 24,
            second_reminder_days INTEGER NOT NULL DEFAULT 7,
            final_reminder_days INTEGER NOT NULL DEFAULT 25,
            deletion_days INTEGER NOT NULL DEFAULT 30,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    existing_setting = connection.execute(text(
        "SELECT id FROM saas_draft_lifecycle_settings WHERE id = 1"
    )).first()
    if not existing_setting:
        _execute(
            connection,
            """
            INSERT INTO saas_draft_lifecycle_settings (
                id, first_reminder_hours, second_reminder_days,
                final_reminder_days, deletion_days, created_at, updated_at
            ) VALUES (1, 24, 7, 25, 30, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        )

    # Historical activity cannot be reconstructed reliably. Migration time grants
    # every legacy draft a complete retention grace period before future cleanup.
    if _table_exists(connection, "saas_accounts"):
        _execute(
            connection,
            """
            UPDATE saas_accounts
            SET last_meaningful_activity_at = CURRENT_TIMESTAMP
            WHERE last_meaningful_activity_at IS NULL
            """,
        )
    if _table_exists(connection, "pending_organizations"):
        _execute(
            connection,
            """
            UPDATE pending_organizations
            SET last_meaningful_activity_at = CURRENT_TIMESTAMP
            WHERE last_meaningful_activity_at IS NULL
            """,
        )


def _subscription_entitlement_foundation(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS entitlement_definitions (
            id {id_sql},
            key VARCHAR(120) NOT NULL,
            display_name VARCHAR(160) NOT NULL,
            category VARCHAR(60) NOT NULL,
            scope VARCHAR(40) NOT NULL DEFAULT 'organization',
            value_type VARCHAR(20) NOT NULL DEFAULT 'boolean',
            description TEXT,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    _create_unique_index_if_missing(
        connection, connection, "entitlement_definitions",
        "uq_entitlement_definitions_key", "key",
    )
    _create_index_if_missing(
        connection, connection, "entitlement_definitions",
        "ix_entitlement_definitions_active", "active",
    )
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS plan_entitlements (
            id {id_sql},
            subscription_plan_id INTEGER NOT NULL,
            entitlement_definition_id INTEGER NOT NULL,
            value TEXT,
            status VARCHAR(40) NOT NULL DEFAULT 'owner_approval_required',
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (subscription_plan_id) REFERENCES subscription_plans (id),
            FOREIGN KEY (entitlement_definition_id) REFERENCES entitlement_definitions (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection, connection, "plan_entitlements",
        "uq_plan_entitlements_plan_definition",
        "subscription_plan_id, entitlement_definition_id",
    )
    _create_index_if_missing(
        connection, connection, "plan_entitlements",
        "ix_plan_entitlements_plan", "subscription_plan_id",
    )
    _create_index_if_missing(
        connection, connection, "plan_entitlements",
        "ix_plan_entitlements_definition", "entitlement_definition_id",
    )
    _create_index_if_missing(
        connection, connection, "plan_entitlements",
        "ix_plan_entitlements_status", "status",
    )

    definitions = (
        ("module.teacher_management", "Teacher Management", "administration", "boolean", "Access to teacher-management capabilities."),
        ("module.branch_management", "Branch Management", "administration", "boolean", "Access to branch-management capabilities."),
        ("module.observation", "Observation", "analytics", "boolean", "Access to teacher observation capabilities."),
        ("module.hiring", "Hiring", "planning", "boolean", "Access to hiring-plan capabilities."),
        ("module.reporting", "Reporting", "reporting", "boolean", "Access to core reporting capabilities."),
        ("module.ai", "AI", "ai", "boolean", "Access to commercial AI capabilities."),
        ("feature.advanced_reporting", "Advanced Reporting", "reporting", "boolean", "Access to advanced reporting and allocation-plan exports."),
        ("feature.export", "Export", "reporting", "boolean", "Access to general data exports."),
        ("feature.audit_log", "Audit Log", "administration", "boolean", "Access to commercial audit-log capabilities."),
        ("feature.cross_branch_reporting", "Cross-Branch Reporting", "analytics", "boolean", "Access to consolidated cross-branch reporting."),
        ("quota.active_branches", "Paid Active Branches", "administration", "integer", "Active branch capacity derived from the confirmed paid subscription quantity."),
    )
    for key, display_name, category, value_type, description in definitions:
        definition_id = connection.execute(
            text("SELECT id FROM entitlement_definitions WHERE key = :key LIMIT 1"),
            {"key": key},
        ).scalar()
        params = {
            "key": key,
            "display_name": display_name,
            "category": category,
            "scope": "organization",
            "value_type": value_type,
            "description": description,
            "active": True,
        }
        if definition_id:
            _execute(
                connection,
                """
                UPDATE entitlement_definitions
                SET display_name = :display_name, category = :category,
                    scope = :scope, value_type = :value_type,
                    description = :description, active = :active,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :row_id
                """,
                {**params, "row_id": definition_id},
            )
        else:
            _execute(
                connection,
                """
                INSERT INTO entitlement_definitions (
                    key, display_name, category, scope, value_type,
                    description, active, created_at, updated_at
                ) VALUES (
                    :key, :display_name, :category, :scope, :value_type,
                    :description, :active, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                params,
            )

    plan_rows = connection.execute(text(
        """
        SELECT id, ai_enabled, advanced_reporting_enabled
        FROM subscription_plans
        WHERE plan_code IN ('starter', 'professional', 'enterprise_ai')
        """
    )).all()
    definition_rows = {
        row[1]: row[0]
        for row in connection.execute(text("SELECT id, key FROM entitlement_definitions")).all()
    }
    for plan_id, ai_enabled, advanced_reporting_enabled in plan_rows:
        for key, definition_id in definition_rows.items():
            status = "owner_approval_required"
            value = None
            if key == "module.ai":
                status = "active"
                value = "true" if ai_enabled else "false"
            elif key == "feature.advanced_reporting":
                status = "active"
                value = "true" if advanced_reporting_enabled else "false"
            elif key == "quota.active_branches":
                status = "derived"
            existing_id = connection.execute(
                text(
                    """
                    SELECT id FROM plan_entitlements
                    WHERE subscription_plan_id = :plan_id
                      AND entitlement_definition_id = :definition_id
                    LIMIT 1
                    """
                ),
                {"plan_id": plan_id, "definition_id": definition_id},
            ).scalar()
            params = {
                "plan_id": plan_id,
                "definition_id": definition_id,
                "value": value,
                "status": status,
            }
            if existing_id:
                _execute(
                    connection,
                    """
                    UPDATE plan_entitlements
                    SET value = :value, status = :status,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :row_id
                    """,
                    {**params, "row_id": existing_id},
                )
            else:
                _execute(
                    connection,
                    """
                    INSERT INTO plan_entitlements (
                        subscription_plan_id, entitlement_definition_id,
                        value, status, created_at, updated_at
                    ) VALUES (
                        :plan_id, :definition_id, :value, :status,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """,
                    params,
                )


def _subscription_branch_quantity_changes(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS subscription_change_requests (
            id {id_sql},
            request_uuid VARCHAR(36) NOT NULL,
            school_group_id INTEGER NOT NULL,
            subscription_contract_id INTEGER NOT NULL,
            payment_subscription_id INTEGER NOT NULL,
            provider_subscription_id VARCHAR(120) NOT NULL,
            requested_by_user_id INTEGER,
            requested_by_saas_account_id INTEGER NOT NULL,
            change_type VARCHAR(50) NOT NULL,
            current_quantity INTEGER NOT NULL,
            requested_quantity INTEGER NOT NULL,
            quantity_delta INTEGER NOT NULL,
            current_plan_price_id INTEGER NOT NULL,
            provider_price_id VARCHAR(120) NOT NULL,
            billing_interval VARCHAR(20) NOT NULL,
            currency_code VARCHAR(3) NOT NULL,
            effective_mode VARCHAR(30) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'draft',
            previewed_charge_minor INTEGER,
            previewed_credit_minor INTEGER,
            previewed_net_minor INTEGER,
            current_renewal_total_minor INTEGER,
            next_renewal_total_minor INTEGER,
            provider_preview_reference VARCHAR(120),
            retained_items_json TEXT,
            idempotency_key VARCHAR(64) NOT NULL,
            provider_observed_quantity INTEGER,
            requested_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            previewed_at {datetime_type},
            submitted_at {datetime_type},
            provider_payment_confirmed_at {datetime_type},
            confirmed_at {datetime_type},
            effective_at {datetime_type},
            canceled_at {datetime_type},
            failure_code VARCHAR(80),
            failure_message VARCHAR(255),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (subscription_contract_id) REFERENCES subscription_contracts (id),
            FOREIGN KEY (payment_subscription_id) REFERENCES payment_subscriptions (id),
            FOREIGN KEY (requested_by_user_id) REFERENCES users (id),
            FOREIGN KEY (requested_by_saas_account_id) REFERENCES saas_accounts (id),
            FOREIGN KEY (current_plan_price_id) REFERENCES subscription_plan_prices (id)
        )
        """,
    )
    for index_name, columns in (
        ("uq_subscription_change_requests_uuid", "request_uuid"),
        ("uq_subscription_change_requests_idempotency", "idempotency_key"),
    ):
        _create_unique_index_if_missing(connection, connection, "subscription_change_requests", index_name, columns)
    for index_name, columns in (
        ("ix_subscription_change_requests_group", "school_group_id"),
        ("ix_subscription_change_requests_subscription", "payment_subscription_id"),
        ("ix_subscription_change_requests_status", "status"),
        ("ix_subscription_change_requests_provider_subscription", "provider_subscription_id"),
    ):
        _create_index_if_missing(connection, connection, "subscription_change_requests", index_name, columns)
    _execute(
        connection,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_subscription_change_requests_unresolved
        ON subscription_change_requests (payment_subscription_id)
        WHERE status IN ('draft','previewed','awaiting_confirmation','submitted','payment_pending','scheduled','manual_review')
        """,
    )


def _subscription_plan_changes(engine, connection):
    datetime_type = _datetime_type(engine)
    for column_name, column_sql in (
        ("target_plan_id", "target_plan_id INTEGER"),
        ("target_plan_price_id", "target_plan_price_id INTEGER"),
        ("target_provider_price_id", "target_provider_price_id VARCHAR(120)"),
        ("provider_observed_price_id", "provider_observed_price_id VARCHAR(120)"),
        ("entitlement_impact_json", "entitlement_impact_json TEXT"),
        ("provider_scheduled_at", f"provider_scheduled_at {datetime_type}"),
    ):
        _add_column_if_missing(connection, connection, "subscription_change_requests", column_name, column_sql)
    for index_name, columns in (
        ("ix_subscription_change_requests_target_plan", "target_plan_id"),
        ("ix_subscription_change_requests_target_price", "target_plan_price_id"),
        ("ix_subscription_change_requests_target_provider_price", "target_provider_price_id"),
    ):
        _create_index_if_missing(connection, connection, "subscription_change_requests", index_name, columns)


def _workspace_classification_foundation(engine, connection):
    if _table_exists(connection, "school_groups"):
        _add_column_if_missing(
            connection, connection, "school_groups", "workspace_uuid",
            "workspace_uuid VARCHAR(36)",
        )
        _add_column_if_missing(
            connection, connection, "school_groups", "workspace_classification",
            "workspace_classification VARCHAR(32) NOT NULL DEFAULT 'internal_sandbox'",
        )
        _add_column_if_missing(
            connection, connection, "school_groups", "workspace_lifecycle_status",
            "workspace_lifecycle_status VARCHAR(20) NOT NULL DEFAULT 'active'",
        )
        missing_uuid_rows = connection.execute(
            text("SELECT id FROM school_groups WHERE workspace_uuid IS NULL OR workspace_uuid = ''")
        ).all()
        for row in missing_uuid_rows:
            _execute(
                connection,
                "UPDATE school_groups SET workspace_uuid = :workspace_uuid WHERE id = :row_id",
                {"workspace_uuid": str(uuid.uuid4()), "row_id": row[0]},
            )
        _execute(
            connection,
            """
            UPDATE school_groups
            SET workspace_lifecycle_status = 'suspended'
            WHERE status = FALSE AND workspace_lifecycle_status = 'active'
            """,
        )
        _create_unique_index_if_missing(
            connection, connection, "school_groups", "uq_school_groups_workspace_uuid", "workspace_uuid"
        )
        _create_index_if_missing(
            connection, connection, "school_groups",
            "ix_school_groups_workspace_classification", "workspace_classification",
        )
        _create_index_if_missing(
            connection, connection, "school_groups",
            "ix_school_groups_workspace_lifecycle_status", "workspace_lifecycle_status",
        )

    if _table_exists(connection, "pending_organizations"):
        _add_column_if_missing(
            connection, connection, "pending_organizations", "workspace_intent",
            "workspace_intent VARCHAR(32) NOT NULL DEFAULT 'internal_sandbox'",
        )
        _create_index_if_missing(
            connection, connection, "pending_organizations",
            "ix_pending_organizations_workspace_intent", "workspace_intent",
        )

    if _table_exists(connection, "saas_accounts"):
        _add_column_if_missing(
            connection, connection, "saas_accounts", "account_purpose",
            "account_purpose VARCHAR(20) NOT NULL DEFAULT 'internal_test'",
        )
        _create_index_if_missing(
            connection, connection, "saas_accounts",
            "ix_saas_accounts_account_purpose", "account_purpose",
        )

    if _table_exists(connection, "users"):
        _add_column_if_missing(
            connection, connection, "users", "is_internal_test_identity",
            "is_internal_test_identity BOOLEAN NOT NULL DEFAULT FALSE",
        )
        _create_index_if_missing(
            connection, connection, "users",
            "ix_users_internal_test_identity", "is_internal_test_identity",
        )

    dialect = connection.dialect.name
    constraints = (
        (
            "school_groups", "ck_school_groups_workspace_classification", "workspace_classification",
            "workspace_classification IN ('internal_sandbox','customer_demo','customer_paid')",
        ),
        (
            "school_groups", "ck_school_groups_workspace_lifecycle_status", "workspace_lifecycle_status",
            "workspace_lifecycle_status IN ('provisioning','active','suspended','archived')",
        ),
        (
            "pending_organizations", "ck_pending_organizations_workspace_intent", "workspace_intent",
            "workspace_intent IN ('internal_sandbox','customer_demo','customer_paid')",
        ),
        (
            "saas_accounts", "ck_saas_accounts_account_purpose", "account_purpose",
            "account_purpose IN ('internal_test','customer')",
        ),
    )
    if dialect == "postgresql":
        for table_name, constraint_name, _column_name, expression in constraints:
            if _table_exists(connection, table_name) and not _check_constraint_exists(
                connection, table_name, constraint_name
            ):
                _execute(
                    connection,
                    f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} CHECK ({expression})",
                )
        if _table_exists(connection, "school_groups"):
            _execute(
                connection,
                "ALTER TABLE school_groups ALTER COLUMN workspace_uuid SET NOT NULL",
            )
    elif dialect == "sqlite":
        for table_name, constraint_name, column_name, expression in constraints:
            if not _table_exists(connection, table_name):
                continue
            for operation in ("INSERT", "UPDATE"):
                trigger_name = f"trg_{constraint_name}_{operation.lower()}"
                _execute(
                    connection,
                    f"""
                    CREATE TRIGGER IF NOT EXISTS {trigger_name}
                    BEFORE {operation} ON {table_name}
                    WHEN NOT ({expression.replace(column_name, f'NEW.{column_name}')})
                    BEGIN
                        SELECT RAISE(ABORT, '{constraint_name}');
                    END
                    """,
                )
        if _table_exists(connection, "school_groups"):
            for operation in ("INSERT", "UPDATE"):
                _execute(
                    connection,
                    f"""
                    CREATE TRIGGER IF NOT EXISTS trg_school_groups_workspace_uuid_{operation.lower()}
                    BEFORE {operation} ON school_groups
                    WHEN NEW.workspace_uuid IS NULL OR length(NEW.workspace_uuid) != 36
                    BEGIN
                        SELECT RAISE(ABORT, 'ck_school_groups_workspace_uuid');
                    END
                    """,
                )


def _commercial_entitlement_foundation(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS workspace_entitlements (
            id {id_sql},
            entitlement_uuid VARCHAR(36) NOT NULL,
            school_group_id INTEGER NOT NULL,
            entitlement_type VARCHAR(32) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            source VARCHAR(20) NOT NULL DEFAULT 'system',
            payment_subscription_id INTEGER,
            effective_from {datetime_type},
            effective_to {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_workspace_entitlements_type
                CHECK (entitlement_type IN ('internal_sandbox','demo','paid')),
            CONSTRAINT ck_workspace_entitlements_status
                CHECK (status IN ('pending','active','inactive','suspended','ended')),
            CONSTRAINT ck_workspace_entitlements_source
                CHECK (source IN ('system','migration','subscription','platform')),
            CONSTRAINT ck_workspace_entitlements_effective_window
                CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from),
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (payment_subscription_id) REFERENCES payment_subscriptions (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection, connection, "workspace_entitlements",
        "uq_workspace_entitlements_uuid", "entitlement_uuid",
    )
    for index_name, columns in (
        ("ix_workspace_entitlements_group", "school_group_id"),
        ("ix_workspace_entitlements_type", "entitlement_type"),
        ("ix_workspace_entitlements_status", "status"),
        ("ix_workspace_entitlements_subscription", "payment_subscription_id"),
    ):
        _create_index_if_missing(
            connection, connection, "workspace_entitlements", index_name, columns
        )
    _execute(
        connection,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_entitlements_active_group
        ON workspace_entitlements (school_group_id)
        WHERE status = 'active'
        """,
    )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS workspace_entitlement_values (
            id {id_sql},
            workspace_entitlement_id INTEGER NOT NULL,
            entitlement_definition_id INTEGER NOT NULL,
            value TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_workspace_entitlement_values_status
                CHECK (status IN ('active','inactive')),
            FOREIGN KEY (workspace_entitlement_id) REFERENCES workspace_entitlements (id),
            FOREIGN KEY (entitlement_definition_id) REFERENCES entitlement_definitions (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection, connection, "workspace_entitlement_values",
        "uq_workspace_entitlement_values_definition",
        "workspace_entitlement_id, entitlement_definition_id",
    )
    for index_name, columns in (
        ("ix_workspace_entitlement_values_workspace", "workspace_entitlement_id"),
        ("ix_workspace_entitlement_values_definition", "entitlement_definition_id"),
        ("ix_workspace_entitlement_values_status", "status"),
    ):
        _create_index_if_missing(
            connection, connection, "workspace_entitlement_values", index_name, columns
        )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS branch_entitlements (
            id {id_sql},
            branch_entitlement_uuid VARCHAR(36) NOT NULL,
            school_group_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            workspace_entitlement_id INTEGER NOT NULL,
            entitlement_mode VARCHAR(20) NOT NULL DEFAULT 'inherit',
            reason_code VARCHAR(80),
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_branch_entitlements_mode
                CHECK (entitlement_mode IN ('inherit','active','inactive')),
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (branch_id) REFERENCES branches (id),
            FOREIGN KEY (workspace_entitlement_id) REFERENCES workspace_entitlements (id)
        )
        """,
    )
    _create_unique_index_if_missing(
        connection, connection, "branch_entitlements",
        "uq_branch_entitlements_uuid", "branch_entitlement_uuid",
    )
    _create_unique_index_if_missing(
        connection, connection, "branch_entitlements",
        "uq_branch_entitlements_branch", "branch_id",
    )
    for index_name, columns in (
        ("ix_branch_entitlements_group", "school_group_id"),
        ("ix_branch_entitlements_workspace", "workspace_entitlement_id"),
        ("ix_branch_entitlements_mode", "entitlement_mode"),
    ):
        _create_index_if_missing(
            connection, connection, "branch_entitlements", index_name, columns
        )

    if not _table_exists(connection, "school_groups"):
        return
    group_rows = connection.execute(text(
        """
        SELECT id, workspace_classification, workspace_lifecycle_status
        FROM school_groups
        ORDER BY id
        """
    )).all()
    type_by_classification = {
        "internal_sandbox": "internal_sandbox",
        "customer_demo": "demo",
        "customer_paid": "paid",
    }
    status_by_lifecycle = {
        "provisioning": "pending",
        "active": "active",
        "suspended": "suspended",
        "archived": "ended",
    }
    for group_id, classification, lifecycle in group_rows:
        existing_id = connection.execute(
            text("SELECT id FROM workspace_entitlements WHERE school_group_id = :group_id LIMIT 1"),
            {"group_id": group_id},
        ).scalar()
        if existing_id:
            continue
        entitlement_type = type_by_classification.get(str(classification or "").lower())
        entitlement_status = status_by_lifecycle.get(str(lifecycle or "").lower())
        if not entitlement_type or not entitlement_status:
            logger.warning(
                "Skipped workspace entitlement seed for school_group_id=%s due to invalid classification metadata",
                group_id,
            )
            continue
        payment_subscription_id = None
        if entitlement_type == "paid" and _table_exists(connection, "payment_subscriptions"):
            candidates = connection.execute(
                text(
                    """
                    SELECT ps.id
                    FROM payment_subscriptions ps
                    JOIN subscription_contracts sc ON sc.id = ps.subscription_contract_id
                    WHERE sc.school_group_id = :group_id
                      AND ps.status IN ('active', 'trialing')
                    ORDER BY ps.id
                    """
                ),
                {"group_id": group_id},
            ).all()
            if len(candidates) == 1:
                payment_subscription_id = candidates[0][0]
        _execute(
            connection,
            """
            INSERT INTO workspace_entitlements (
                entitlement_uuid, school_group_id, entitlement_type, status,
                source, payment_subscription_id, created_at, updated_at
            ) VALUES (
                :entitlement_uuid, :school_group_id, :entitlement_type, :status,
                'migration', :payment_subscription_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {
                "entitlement_uuid": str(uuid.uuid4()),
                "school_group_id": group_id,
                "entitlement_type": entitlement_type,
                "status": entitlement_status,
                "payment_subscription_id": payment_subscription_id,
            },
        )


def _saas_demo_request_workflow(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_requests (
            id {id_sql},
            request_uuid VARCHAR(36) NOT NULL UNIQUE,
            requester_saas_account_id INTEGER NOT NULL,
            pending_organization_id INTEGER NOT NULL,
            school_group_id INTEGER,
            workspace_uuid_snapshot VARCHAR(36),
            workspace_classification_snapshot VARCHAR(32) NOT NULL,
            commercial_state_snapshot VARCHAR(40) NOT NULL,
            entitlement_snapshot_json TEXT NOT NULL DEFAULT '{{}}',
            status VARCHAR(24) NOT NULL DEFAULT 'pending_review',
            rejection_reason TEXT,
            submitted_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            approved_at {datetime_type},
            rejected_at {datetime_type},
            cancelled_at {datetime_type},
            status_updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_saas_demo_requests_requester
                FOREIGN KEY (requester_saas_account_id) REFERENCES saas_accounts(id) ON DELETE CASCADE,
            CONSTRAINT fk_saas_demo_requests_organization
                FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations(id) ON DELETE CASCADE,
            CONSTRAINT fk_saas_demo_requests_workspace
                FOREIGN KEY (school_group_id) REFERENCES school_groups(id) ON DELETE SET NULL,
            CONSTRAINT ck_saas_demo_requests_status
                CHECK (status IN ('pending_review','approved','rejected','cancelled')),
            CONSTRAINT ck_saas_demo_requests_classification
                CHECK (workspace_classification_snapshot IN ('internal_sandbox','customer_demo','customer_paid')),
            CONSTRAINT ck_saas_demo_requests_commercial_state
                CHECK (commercial_state_snapshot IN ('provisioning','internal_sandbox_active','customer_demo_active','customer_paid_active','inactive','suspended','archived','manual_review'))
        )
        """,
    )
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_request_reviews (
            id {id_sql},
            review_uuid VARCHAR(36) NOT NULL UNIQUE,
            demo_request_id INTEGER NOT NULL UNIQUE,
            reviewer_user_id INTEGER,
            decision VARCHAR(20) NOT NULL,
            reason TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_saas_demo_request_reviews_request
                FOREIGN KEY (demo_request_id) REFERENCES saas_demo_requests(id) ON DELETE CASCADE,
            CONSTRAINT fk_saas_demo_request_reviews_reviewer
                FOREIGN KEY (reviewer_user_id) REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_saas_demo_request_reviews_decision
                CHECK (decision IN ('approved','rejected')),
            CONSTRAINT ck_saas_demo_request_reviews_rejection_reason
                CHECK (decision != 'rejected' OR (reason IS NOT NULL AND length(trim(reason)) > 0))
        )
        """,
    )
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_request_events (
            id {id_sql},
            demo_request_id INTEGER NOT NULL,
            event_category VARCHAR(20) NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            actor_type VARCHAR(24) NOT NULL,
            actor_saas_account_id INTEGER,
            actor_user_id INTEGER,
            details_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_saas_demo_request_events_request
                FOREIGN KEY (demo_request_id) REFERENCES saas_demo_requests(id) ON DELETE CASCADE,
            CONSTRAINT fk_saas_demo_request_events_saas_actor
                FOREIGN KEY (actor_saas_account_id) REFERENCES saas_accounts(id) ON DELETE SET NULL,
            CONSTRAINT fk_saas_demo_request_events_platform_actor
                FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT ck_saas_demo_request_events_category
                CHECK (event_category IN ('audit','notification')),
            CONSTRAINT ck_saas_demo_request_events_type
                CHECK (event_type IN ('request_submitted','request_approved','request_rejected','request_cancelled','request_withdrawn')),
            CONSTRAINT ck_saas_demo_request_events_actor_type
                CHECK (actor_type IN ('customer','platform_owner','system'))
        )
        """,
    )
    for table_name, index_name, column_name in (
        ("saas_demo_requests", "ix_saas_demo_requests_requester", "requester_saas_account_id"),
        ("saas_demo_requests", "ix_saas_demo_requests_organization", "pending_organization_id"),
        ("saas_demo_requests", "ix_saas_demo_requests_workspace", "school_group_id"),
        ("saas_demo_requests", "ix_saas_demo_requests_status", "status"),
        ("saas_demo_requests", "ix_saas_demo_requests_submitted", "submitted_at"),
        ("saas_demo_request_reviews", "ix_saas_demo_request_reviews_reviewer", "reviewer_user_id"),
        ("saas_demo_request_reviews", "ix_saas_demo_request_reviews_decision", "decision"),
        ("saas_demo_request_events", "ix_saas_demo_request_events_request", "demo_request_id"),
        ("saas_demo_request_events", "ix_saas_demo_request_events_category", "event_category"),
        ("saas_demo_request_events", "ix_saas_demo_request_events_type", "event_type"),
        ("saas_demo_request_events", "ix_saas_demo_request_events_created", "created_at"),
    ):
        _create_index_if_missing(engine, connection, table_name, index_name, column_name)
    _execute(
        connection,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_saas_demo_requests_pending_org
        ON saas_demo_requests (pending_organization_id)
        WHERE status = 'pending_review'
        """,
    )


def _sqlite_generalize_tenant_provisioning_links(connection):
    columns = {
        column["name"]: column
        for column in inspect(connection).get_columns("tenant_provisioning_links")
    }
    contract_column = columns.get("subscription_contract_id")
    if (
        "demo_request_id" in columns
        and contract_column is not None
        and bool(contract_column.get("nullable"))
    ):
        return

    _execute(connection, "PRAGMA defer_foreign_keys = ON")
    _execute(connection, "PRAGMA legacy_alter_table = ON")
    _execute(
        connection,
        "ALTER TABLE tenant_provisioning_links RENAME TO tenant_provisioning_links_m8b4_legacy",
    )
    _execute(
        connection,
        """
        CREATE TABLE tenant_provisioning_links (
            id INTEGER PRIMARY KEY,
            pending_organization_id INTEGER NOT NULL,
            subscription_contract_id INTEGER,
            demo_request_id INTEGER,
            school_group_id INTEGER NOT NULL,
            owner_operational_user_id INTEGER NOT NULL,
            primary_branch_id INTEGER,
            primary_academic_year_id INTEGER,
            tenant_status VARCHAR(30) NOT NULL DEFAULT 'tenant_active',
            activated_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_tenant_provisioning_links_commercial_source CHECK (
                (subscription_contract_id IS NOT NULL AND demo_request_id IS NULL)
                OR (subscription_contract_id IS NULL AND demo_request_id IS NOT NULL)
            ),
            FOREIGN KEY (pending_organization_id) REFERENCES pending_organizations (id),
            FOREIGN KEY (subscription_contract_id) REFERENCES subscription_contracts (id),
            FOREIGN KEY (demo_request_id) REFERENCES saas_demo_requests (id),
            FOREIGN KEY (school_group_id) REFERENCES school_groups (id),
            FOREIGN KEY (owner_operational_user_id) REFERENCES users (id),
            FOREIGN KEY (primary_branch_id) REFERENCES branches (id),
            FOREIGN KEY (primary_academic_year_id) REFERENCES academic_years (id)
        )
        """,
    )
    _execute(
        connection,
        """
        INSERT INTO tenant_provisioning_links (
            id, pending_organization_id, subscription_contract_id, demo_request_id,
            school_group_id, owner_operational_user_id, primary_branch_id,
            primary_academic_year_id, tenant_status, activated_at, created_at, updated_at
        )
        SELECT
            id, pending_organization_id, subscription_contract_id, NULL,
            school_group_id, owner_operational_user_id, primary_branch_id,
            primary_academic_year_id, tenant_status, activated_at, created_at, updated_at
        FROM tenant_provisioning_links_m8b4_legacy
        """,
    )
    _execute(connection, "DROP TABLE tenant_provisioning_links_m8b4_legacy")
    _execute(connection, "PRAGMA legacy_alter_table = OFF")


def _demo_workspace_provisioning(engine, connection):
    datetime_type = _datetime_type(engine)
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"

    if engine.dialect.name == "sqlite":
        _sqlite_generalize_tenant_provisioning_links(connection)
    else:
        _add_column_if_missing(
            connection,
            connection,
            "tenant_provisioning_links",
            "demo_request_id",
            "demo_request_id INTEGER",
        )
        _execute(
            connection,
            """
            ALTER TABLE tenant_provisioning_links
            ALTER COLUMN subscription_contract_id DROP NOT NULL
            """,
        )
        _ensure_postgres_fk(
            engine,
            connection,
            table_name="tenant_provisioning_links",
            constraint_name="fk_tenant_provisioning_links_demo_request",
            column_name="demo_request_id",
            target_table="saas_demo_requests",
        )
        if not _check_constraint_exists(
            connection,
            "tenant_provisioning_links",
            "ck_tenant_provisioning_links_commercial_source",
        ):
            _execute(
                connection,
                """
                ALTER TABLE tenant_provisioning_links
                ADD CONSTRAINT ck_tenant_provisioning_links_commercial_source
                CHECK (
                    (subscription_contract_id IS NOT NULL AND demo_request_id IS NULL)
                    OR (subscription_contract_id IS NULL AND demo_request_id IS NOT NULL)
                ) NOT VALID
                """,
            )
            _execute(
                connection,
                """
                ALTER TABLE tenant_provisioning_links
                VALIDATE CONSTRAINT ck_tenant_provisioning_links_commercial_source
                """,
            )

    for index_name, column_name, unique in (
        ("uq_tenant_provisioning_links_pending_org", "pending_organization_id", True),
        ("uq_tenant_provisioning_links_contract", "subscription_contract_id", True),
        ("uq_tenant_provisioning_links_demo_request", "demo_request_id", True),
        ("uq_tenant_provisioning_links_school_group", "school_group_id", True),
        ("ix_tenant_provisioning_links_status", "tenant_status", False),
    ):
        creator = _create_unique_index_if_missing if unique else _create_index_if_missing
        creator(
            connection,
            connection,
            "tenant_provisioning_links",
            index_name,
            column_name,
        )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_workspace_provisioning (
            id {id_sql},
            provisioning_uuid VARCHAR(36) NOT NULL UNIQUE,
            demo_request_id INTEGER NOT NULL UNIQUE,
            school_group_id INTEGER UNIQUE,
            workspace_entitlement_id INTEGER UNIQUE,
            tenant_provisioning_link_id INTEGER UNIQUE,
            triggered_by_user_id INTEGER,
            provisioning_status VARCHAR(24) NOT NULL DEFAULT 'provisioning',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            result_code VARCHAR(80),
            failure_reason TEXT,
            started_at {datetime_type},
            completed_at {datetime_type},
            activated_at {datetime_type},
            failed_at {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_saas_demo_workspace_provisioning_status
                CHECK (provisioning_status IN ('provisioning','active','failed')),
            FOREIGN KEY (demo_request_id) REFERENCES saas_demo_requests(id) ON DELETE CASCADE,
            FOREIGN KEY (school_group_id) REFERENCES school_groups(id) ON DELETE SET NULL,
            FOREIGN KEY (workspace_entitlement_id) REFERENCES workspace_entitlements(id) ON DELETE SET NULL,
            FOREIGN KEY (tenant_provisioning_link_id) REFERENCES tenant_provisioning_links(id) ON DELETE SET NULL,
            FOREIGN KEY (triggered_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
    )
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_provisioning_events (
            id {id_sql},
            demo_provisioning_id INTEGER NOT NULL,
            event_category VARCHAR(20) NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            actor_type VARCHAR(24) NOT NULL,
            actor_user_id INTEGER,
            event_status VARCHAR(20) NOT NULL DEFAULT 'ok',
            details_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_saas_demo_provisioning_events_category
                CHECK (event_category IN ('audit','notification')),
            CONSTRAINT ck_saas_demo_provisioning_events_type
                CHECK (event_type IN ('provisioning_started','provisioning_completed','provisioning_failed','activation_completed')),
            CONSTRAINT ck_saas_demo_provisioning_events_actor_type
                CHECK (actor_type IN ('platform_owner','system')),
            FOREIGN KEY (demo_provisioning_id)
                REFERENCES saas_demo_workspace_provisioning(id) ON DELETE CASCADE,
            FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
    )
    for table_name, index_name, column_name in (
        (
            "saas_demo_workspace_provisioning",
            "ix_saas_demo_workspace_provisioning_status",
            "provisioning_status",
        ),
        (
            "saas_demo_provisioning_events",
            "ix_saas_demo_provisioning_events_provisioning",
            "demo_provisioning_id",
        ),
        (
            "saas_demo_provisioning_events",
            "ix_saas_demo_provisioning_events_category",
            "event_category",
        ),
        (
            "saas_demo_provisioning_events",
            "ix_saas_demo_provisioning_events_type",
            "event_type",
        ),
        (
            "saas_demo_provisioning_events",
            "ix_saas_demo_provisioning_events_created",
            "created_at",
        ),
    ):
        _create_index_if_missing(
            connection,
            connection,
            table_name,
            index_name,
            column_name,
        )


def _demo_workspace_lifecycle(engine, connection):
    datetime_type = (
        "TIMESTAMPTZ" if engine.dialect.name == "postgresql" else "DATETIME"
    )
    id_sql = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    table_name = "saas_demo_workspace_provisioning"
    for column_name, column_sql in (
        ("demo_expires_at", f"demo_expires_at {datetime_type}"),
        ("reminder_due_at", f"reminder_due_at {datetime_type}"),
        ("reminder_sent_at", f"reminder_sent_at {datetime_type}"),
        ("expired_at", f"expired_at {datetime_type}"),
        (
            "lifecycle_processing_status",
            "lifecycle_processing_status VARCHAR(24) NOT NULL DEFAULT 'pending'",
        ),
        (
            "lifecycle_last_processed_at",
            f"lifecycle_last_processed_at {datetime_type}",
        ),
        ("lifecycle_failure_code", "lifecycle_failure_code VARCHAR(80)"),
    ):
        _add_column_if_missing(
            connection,
            connection,
            table_name,
            column_name,
            column_sql,
        )
    for index_name, column_name in (
        ("ix_saas_demo_workspace_provisioning_expires", "demo_expires_at"),
        ("ix_saas_demo_workspace_provisioning_reminder_due", "reminder_due_at"),
        (
            "ix_saas_demo_workspace_provisioning_lifecycle_status",
            "lifecycle_processing_status",
        ),
    ):
        _create_index_if_missing(
            connection,
            connection,
            table_name,
            index_name,
            column_name,
        )

    if engine.dialect.name == "postgresql":
        if not _check_constraint_exists(
            connection,
            table_name,
            "ck_saas_demo_workspace_provisioning_lifecycle_status",
        ):
            _execute(
                connection,
                """
                ALTER TABLE saas_demo_workspace_provisioning
                ADD CONSTRAINT ck_saas_demo_workspace_provisioning_lifecycle_status
                CHECK (lifecycle_processing_status IN ('pending','processing','failed','expired'))
                """,
            )
        _execute(
            connection,
            """
            UPDATE saas_demo_workspace_provisioning
            SET reminder_due_at = activated_at AT TIME ZONE 'UTC' + INTERVAL '6 days',
                demo_expires_at = activated_at AT TIME ZONE 'UTC' + INTERVAL '7 days'
            WHERE activated_at IS NOT NULL
              AND (reminder_due_at IS NULL OR demo_expires_at IS NULL)
            """,
        )
    else:
        for operation in ("INSERT", "UPDATE"):
            _execute(
                connection,
                f"""
                CREATE TRIGGER IF NOT EXISTS
                    trg_demo_provisioning_lifecycle_status_{operation.lower()}
                BEFORE {operation} ON saas_demo_workspace_provisioning
                WHEN NEW.lifecycle_processing_status NOT IN
                    ('pending','processing','failed','expired')
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'ck_saas_demo_workspace_provisioning_lifecycle_status'
                    );
                END
                """,
            )
        _execute(
            connection,
            """
            UPDATE saas_demo_workspace_provisioning
            SET reminder_due_at = datetime(activated_at, '+6 days'),
                demo_expires_at = datetime(activated_at, '+7 days')
            WHERE activated_at IS NOT NULL
              AND (reminder_due_at IS NULL OR demo_expires_at IS NULL)
            """,
        )

    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_lifecycle_events (
            id {id_sql},
            demo_provisioning_id INTEGER NOT NULL,
            event_type VARCHAR(48) NOT NULL,
            actor_type VARCHAR(24) NOT NULL DEFAULT 'system',
            actor_user_id INTEGER,
            event_status VARCHAR(20) NOT NULL DEFAULT 'ok',
            reason_code VARCHAR(80),
            deduplication_key VARCHAR(180) NOT NULL UNIQUE,
            details_json TEXT,
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_saas_demo_lifecycle_events_type
                CHECK (event_type IN (
                    'reminder_became_due','reminder_notification_created',
                    'expiration_processing_started','demo_expired',
                    'workspace_suspended','access_blocked',
                    'lifecycle_processing_failed'
                )),
            CONSTRAINT ck_saas_demo_lifecycle_events_actor_type
                CHECK (actor_type IN ('system','tenant_user')),
            CONSTRAINT ck_saas_demo_lifecycle_events_status
                CHECK (event_status IN ('ok','failed')),
            FOREIGN KEY (demo_provisioning_id)
                REFERENCES saas_demo_workspace_provisioning(id) ON DELETE CASCADE,
            FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
    )
    _execute(
        connection,
        f"""
        CREATE TABLE IF NOT EXISTS saas_demo_lifecycle_notifications (
            id {id_sql},
            demo_provisioning_id INTEGER NOT NULL,
            notification_type VARCHAR(40) NOT NULL,
            recipient_type VARCHAR(24) NOT NULL,
            recipient_saas_account_id INTEGER,
            recipient_user_id INTEGER,
            title VARCHAR(160) NOT NULL,
            message TEXT NOT NULL,
            deduplication_key VARCHAR(180) NOT NULL UNIQUE,
            read_at {datetime_type},
            created_at {datetime_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT ck_saas_demo_lifecycle_notifications_type
                CHECK (notification_type IN ('expiration_reminder')),
            CONSTRAINT ck_saas_demo_lifecycle_notifications_recipient
                CHECK (recipient_type IN ('saas_account','platform_owner')),
            CONSTRAINT ck_saas_demo_lifecycle_notifications_recipient_target
                CHECK (
                    (
                        recipient_type = 'saas_account'
                        AND recipient_saas_account_id IS NOT NULL
                        AND recipient_user_id IS NULL
                    )
                    OR (
                        recipient_type = 'platform_owner'
                        AND recipient_user_id IS NOT NULL
                        AND recipient_saas_account_id IS NULL
                    )
                ),
            FOREIGN KEY (demo_provisioning_id)
                REFERENCES saas_demo_workspace_provisioning(id) ON DELETE CASCADE,
            FOREIGN KEY (recipient_saas_account_id)
                REFERENCES saas_accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (recipient_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
    )
    for target_table, index_name, columns in (
        (
            "saas_demo_lifecycle_events",
            "ix_saas_demo_lifecycle_events_provisioning",
            "demo_provisioning_id",
        ),
        (
            "saas_demo_lifecycle_events",
            "ix_saas_demo_lifecycle_events_type",
            "event_type",
        ),
        (
            "saas_demo_lifecycle_events",
            "ix_saas_demo_lifecycle_events_created",
            "created_at",
        ),
        (
            "saas_demo_lifecycle_notifications",
            "ix_saas_demo_lifecycle_notifications_provisioning",
            "demo_provisioning_id",
        ),
        (
            "saas_demo_lifecycle_notifications",
            "ix_saas_demo_lifecycle_notifications_saas_account",
            "recipient_saas_account_id",
        ),
        (
            "saas_demo_lifecycle_notifications",
            "ix_saas_demo_lifecycle_notifications_user",
            "recipient_user_id",
        ),
    ):
        _create_index_if_missing(
            connection,
            connection,
            target_table,
            index_name,
            columns,
        )

    if engine.dialect.name == "postgresql":
        _execute(
            connection,
            """
            UPDATE workspace_entitlements AS entitlement
            SET effective_to = provisioning.demo_expires_at
            FROM saas_demo_workspace_provisioning AS provisioning
            WHERE entitlement.id = provisioning.workspace_entitlement_id
              AND entitlement.entitlement_type = 'demo'
              AND provisioning.demo_expires_at IS NOT NULL
              AND entitlement.effective_to IS NULL
            """,
        )
    else:
        _execute(
            connection,
            """
            UPDATE workspace_entitlements
            SET effective_to = (
                SELECT provisioning.demo_expires_at
                FROM saas_demo_workspace_provisioning AS provisioning
                WHERE provisioning.workspace_entitlement_id = workspace_entitlements.id
            )
            WHERE entitlement_type = 'demo'
              AND effective_to IS NULL
              AND EXISTS (
                SELECT 1
                FROM saas_demo_workspace_provisioning AS provisioning
                WHERE provisioning.workspace_entitlement_id = workspace_entitlements.id
                  AND provisioning.demo_expires_at IS NOT NULL
              )
            """,
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
    Migration(
        migration_id="20260623_001_saas_identity_foundation",
        description="Create SaaS identity, sessions, verification, and domain policy tables",
        apply=_saas_identity_foundation,
    ),
    Migration(
        migration_id="20260623_002_pending_organizations_zone",
        description="Create pending organizations onboarding zone tables",
        apply=_pending_organizations_zone,
    ),
    Migration(
        migration_id="20260623_003_plans_pricing_billing_foundation",
        description="Create SaaS plans, pricing, currency, and checkout foundation tables",
        apply=_plans_pricing_billing_foundation,
    ),
    Migration(
        migration_id="20260623_004_paddle_payment_collection",
        description="Add Paddle customer, attempt, subscription, and webhook payment collection tables",
        apply=_paddle_payment_collection,
    ),
    Migration(
        migration_id="20260710_001_saas_password_reset_tokens",
        description="Add SaaS password reset tokens for TIS Account recovery",
        apply=_saas_password_reset_tokens,
    ),
    Migration(
        migration_id="20260623_005_phase5_provisioning_engine",
        description="Add provisioning jobs, links, and tenant profile storage for tenant activation",
        apply=_phase5_provisioning_engine,
    ),
    Migration(
        migration_id="20260713_001_branch_billing_quote_foundation",
        description="Stabilize pending branch identity and persist branch-based quote snapshots",
        apply=_branch_billing_quote_foundation,
    ),
    Migration(
        migration_id="20260713_002_paddle_branch_quantity_reconciliation",
        description="Persist Paddle branch quantity and aggregate payment reconciliation snapshots",
        apply=_paddle_branch_quantity_reconciliation,
    ),
    Migration(
        migration_id="20260714_001_draft_account_lifecycle_foundation",
        description="Add draft inactivity tracking, reminder cycles, and retention settings",
        apply=_draft_account_lifecycle_foundation,
    ),
    Migration(
        migration_id="20260716_001_subscription_entitlement_foundation",
        description="Add normalized commercial subscription entitlement definitions and plan values",
        apply=_subscription_entitlement_foundation,
    ),
    Migration(
        migration_id="20260716_002_subscription_branch_quantity_changes",
        description="Add durable branch quantity change requests for active subscriptions",
        apply=_subscription_branch_quantity_changes,
    ),
    Migration(
        migration_id="20260717_001_subscription_plan_changes",
        description="Extend active subscription changes with provider-confirmed plan transitions",
        apply=_subscription_plan_changes,
    ),
    Migration(
        migration_id="20260722_001_workspace_classification_foundation",
        description="Add workspace classification, lifecycle, intent, and internal identity metadata",
        apply=_workspace_classification_foundation,
    ),
    Migration(
        migration_id="20260722_003_commercial_entitlement_foundation",
        description="Add workspace and branch commercial entitlement foundations",
        apply=_commercial_entitlement_foundation,
    ),
    Migration(
        migration_id="20260722_004_saas_demo_request_workflow",
        description="Add the customer demo request and Platform Owner review workflow",
        apply=_saas_demo_request_workflow,
    ),
    Migration(
        migration_id="20260723_001_demo_workspace_provisioning",
        description="Add atomic customer demo workspace provisioning and activation records",
        apply=_demo_workspace_provisioning,
    ),
    Migration(
        migration_id="20260723_002_demo_workspace_lifecycle",
        description="Add seven-day customer demo lifecycle processing and notification records",
        apply=_demo_workspace_lifecycle,
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
