"""Run all database schema work outside the TIS web process."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import db_migrations
import models
import saas.models  # noqa: F401 - register SaaS tables with shared metadata
from database import DATABASE_URL
from sqlalchemy import create_engine, text


logger = logging.getLogger("tis.migrations")
POSTGRES_CONNECT_TIMEOUT_SECONDS = 10
POSTGRES_LOCK_TIMEOUT = "5s"
POSTGRES_STATEMENT_TIMEOUT = "30s"


def _progress(message: str, *args) -> None:
    logger.info(message, *args)
    for handler in logging.getLogger().handlers:
        handler.flush()


def _migration_engine():
    _progress("Phase engine.create: starting.")
    engine_kwargs = {}
    if DATABASE_URL.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    elif DATABASE_URL.startswith(("postgresql://", "postgresql+")):
        engine_kwargs["connect_args"] = {
            "connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS,
            "options": (
                f"-c lock_timeout={POSTGRES_LOCK_TIMEOUT} "
                f"-c statement_timeout={POSTGRES_STATEMENT_TIMEOUT}"
            ),
        }
    migration_engine = create_engine(DATABASE_URL, **engine_kwargs)
    _progress(
        "Phase engine.create: complete (dialect=%s, connect_timeout=%s, "
        "lock_timeout=%s, statement_timeout=%s).",
        migration_engine.dialect.name,
        f"{POSTGRES_CONNECT_TIMEOUT_SECONDS}s"
        if migration_engine.dialect.name == "postgresql"
        else "driver-default",
        POSTGRES_LOCK_TIMEOUT if migration_engine.dialect.name == "postgresql" else "not-applicable",
        POSTGRES_STATEMENT_TIMEOUT if migration_engine.dialect.name == "postgresql" else "not-applicable",
    )
    return migration_engine


def run() -> int:
    engine = None
    try:
        engine = _migration_engine()
        _progress("Phase database.connect: starting.")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        _progress("Phase database.connect: complete.")

        # The legacy repository schema uses SQLAlchemy metadata for its baseline
        # and the ordered migration ledger for additive/backfill changes.
        _progress("Phase metadata.create_all: starting.")
        models.Base.metadata.create_all(bind=engine)
        _progress("Phase metadata.create_all: complete.")

        _progress("Phase run_pending_migrations: starting.")
        applied = db_migrations.run_pending_migrations(engine)
        _progress("Phase run_pending_migrations: complete.")
    except Exception:
        logger.exception("Database migration failed.")
        for handler in logging.getLogger().handlers:
            handler.flush()
        return 1
    finally:
        if engine is not None:
            engine.dispose()

    if applied:
        for migration_id in applied:
            _progress("Applied migration: %s", migration_id)
    else:
        _progress("No pending migrations.")
    _progress("Database migrations completed successfully.")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
