"""Strict repair for initial lifecycle fields regressed by a paid subscription change."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import saas.models  # noqa: F401
from database import SessionLocal
from saas import paddle_client, payment_lifecycle_reconciliation_service


def _require_sandbox():
    environment = str(os.getenv("PADDLE_ENVIRONMENT") or "").strip().lower()
    hostname = (urlparse(paddle_client._base_url()).hostname or "").lower()
    if environment != "sandbox" or hostname != "sandbox-api.paddle.com":
        raise payment_lifecycle_reconciliation_service.LifecycleReconciliationError(
            "sandbox_required",
            "This reconciliation is restricted to Paddle Sandbox.",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely reconcile finalized initial payment lifecycle fields.")
    parser.add_argument("--email", required=True, help="Exact SaaS account email")
    parser.add_argument("--apply", action="store_true", help="Apply the five-field repair after all checks pass")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        _require_sandbox()
        result = payment_lifecycle_reconciliation_service.reconcile_finalized_lifecycle(
            db, email=args.email, apply=args.apply
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps(result, indent=2, default=str))
        return 0
    except payment_lifecycle_reconciliation_service.LifecycleReconciliationError as exc:
        db.rollback()
        print(json.dumps({"status": "blocked", "reason_code": exc.code, "message": str(exc)}, indent=2))
        return 2
    except Exception:
        db.rollback()
        print(json.dumps({"status": "failed", "reason_code": "unexpected_reconciliation_error"}, indent=2))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
