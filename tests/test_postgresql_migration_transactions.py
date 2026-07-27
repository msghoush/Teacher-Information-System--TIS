import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

import db_migrations


POSTGRESQL_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "")


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
