"""Reconcile missing inactive promo branch entitlements for one workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal, engine
import models  # noqa: F401 - register operational metadata
import saas.models  # noqa: F401 - register SaaS metadata
from saas import promo_branch_entitlement_reconciliation_service as reconciliation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely reconcile missing inactive promo branch entitlement evidence."
    )
    parser.add_argument("--school-group-id", type=int, required=True)
    parser.add_argument("--workspace-uuid", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the planned inactive-entitlement repairs. Default is dry-run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if engine.dialect.name != "postgresql":
        print(json.dumps({
            "status": "failed",
            "reason_code": "postgresql_required",
        }, sort_keys=True))
        return 1
    db = SessionLocal()
    try:
        result = reconciliation.reconcile_promo_branch_entitlements(
            db,
            school_group_id=args.school_group_id,
            workspace_uuid=args.workspace_uuid,
            apply=bool(args.apply),
        )
        if not result.safe_to_apply:
            db.rollback()
            print(json.dumps(result.to_dict(), sort_keys=True, default=str))
            return 2
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(result.to_dict(), sort_keys=True, default=str))
        return 0
    except Exception as exc:
        db.rollback()
        print(json.dumps({
            "status": "failed",
            "reason_code": "unexpected_reconciliation_error",
            "exception_type": type(exc).__name__,
        }, sort_keys=True))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
