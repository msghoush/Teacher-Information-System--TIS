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
from database import engine


logger = logging.getLogger("tis.migrations")


def run() -> int:
    try:
        # The legacy repository schema uses SQLAlchemy metadata for its baseline
        # and the ordered migration ledger for additive/backfill changes.
        models.Base.metadata.create_all(bind=engine)
        applied = db_migrations.run_pending_migrations(engine)
    except Exception:
        logger.exception("Database migration failed.")
        return 1

    if applied:
        for migration_id in applied:
            logger.info("Applied migration: %s", migration_id)
    else:
        logger.info("No pending migrations.")
    logger.info("Database migrations completed successfully.")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
