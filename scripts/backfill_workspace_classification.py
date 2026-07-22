import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import models  # noqa: F401 - register operational metadata
import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas.workspace_classification_admin_service import (
    apply_workspace_classification_backfill,
    build_workspace_classification_backfill_plan,
)


logger = logging.getLogger("tis.workspace_classification_backfill")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill confirmed pre-M8B-1 TIS test data as internal sandbox metadata."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the transaction. Without this flag the command is read-only.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    db = SessionLocal()
    try:
        result = (
            apply_workspace_classification_backfill(db)
            if args.apply
            else build_workspace_classification_backfill_plan(db)
        )
        if args.apply:
            db.commit()
            logger.info("Workspace classification backfill transaction committed: %s", result["status"])
        else:
            db.rollback()
            logger.info("Workspace classification dry run completed; no data changed")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception:
        db.rollback()
        logger.exception("Workspace classification backfill failed; transaction rolled back")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
