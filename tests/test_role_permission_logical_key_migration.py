import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import db_migrations
import models


MIGRATION_ID = "20260915_001_role_permission_logical_key_uniqueness"


def _legacy_engine():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE role_permissions (
                id INTEGER PRIMARY KEY,
                school_group_id INTEGER,
                role VARCHAR(50) NOT NULL,
                permission_key VARCHAR(120) NOT NULL,
                is_allowed BOOLEAN NOT NULL
            )
        """))
    return engine


def _rows(engine):
    with engine.connect() as connection:
        return connection.execute(text("""
            SELECT id, school_group_id, role, permission_key, is_allowed
            FROM role_permissions ORDER BY id
        """)).all()


@pytest.mark.parametrize("scope", [None, 17])
def test_duplicate_preflight_rolls_back_without_deleting_rows_or_marker(monkeypatch, scope):
    engine = _legacy_engine()
    try:
        with engine.begin() as connection:
            for row_id, allowed in ((1, True), (2, False)):
                connection.execute(text("""
                    INSERT INTO role_permissions
                        (id, school_group_id, role, permission_key, is_allowed)
                    VALUES (:id, :scope, 'Administrator', 'dashboard.view', :allowed)
                """), {"id": row_id, "scope": scope, "allowed": allowed})
        before = _rows(engine)
        monkeypatch.setattr(db_migrations, "MIGRATIONS", (
            next(m for m in db_migrations.MIGRATIONS if m.migration_id == MIGRATION_ID),
        ))

        with pytest.raises(RuntimeError, match="duplicate scope/role/key"):
            db_migrations.run_pending_migrations(engine)

        assert _rows(engine) == before
        assert not any(i["name"].startswith("uq_role_permissions_")
                       for i in inspect(engine).get_indexes("role_permissions"))
        with engine.connect() as connection:
            assert connection.execute(text("""
                SELECT COUNT(*) FROM schema_migrations WHERE migration_id = :id
            """), {"id": MIGRATION_ID}).scalar_one() == 0
    finally:
        engine.dispose()


def test_migration_installs_both_scope_indexes_and_is_idempotent(monkeypatch):
    engine = _legacy_engine()
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO role_permissions (id, school_group_id, role, permission_key, is_allowed)
                VALUES (1, NULL, 'Administrator', 'dashboard.view', 1),
                       (2, 17, 'Administrator', 'dashboard.view', 1),
                       (3, 18, 'Administrator', 'dashboard.view', 1)
            """))
        monkeypatch.setattr(db_migrations, "MIGRATIONS", (
            next(m for m in db_migrations.MIGRATIONS if m.migration_id == MIGRATION_ID),
        ))
        assert db_migrations.run_pending_migrations(engine) == [MIGRATION_ID]
        assert db_migrations.run_pending_migrations(engine) == []
        assert {i["name"] for i in inspect(engine).get_indexes("role_permissions")} == {
            "uq_role_permissions_global_role_key", "uq_role_permissions_tenant_role_key",
        }

        for duplicate_scope in (None, 17):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.execute(text("""
                        INSERT INTO role_permissions
                            (school_group_id, role, permission_key, is_allowed)
                        VALUES (:scope, 'Administrator', 'dashboard.view', 0)
                    """), {"scope": duplicate_scope})
        # Distinct tenant and global scopes may legitimately use the same key.
        assert len(_rows(engine)) == 3
    finally:
        engine.dispose()


def test_fresh_metadata_schema_has_matching_partial_unique_indexes():
    engine = create_engine("sqlite:///:memory:")
    try:
        models.Base.metadata.create_all(engine)
        names = {i["name"] for i in inspect(engine).get_indexes("role_permissions")}
        assert {"uq_role_permissions_global_role_key", "uq_role_permissions_tenant_role_key"} <= names
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO role_permissions
                    (school_group_id, role, permission_key, is_allowed, created_at, updated_at)
                VALUES (NULL, 'Administrator', 'dashboard.view', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("""
                    INSERT INTO role_permissions
                        (school_group_id, role, permission_key, is_allowed, created_at, updated_at)
                    VALUES (NULL, 'Administrator', 'dashboard.view', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """))
    finally:
        engine.dispose()
