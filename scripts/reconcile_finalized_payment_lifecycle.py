"""Strict repair for initial lifecycle fields regressed by a paid subscription change."""

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import SessionLocal
import models  # noqa: F401 - register operational metadata before SaaS metadata
import saas.models  # noqa: F401 - register SaaS metadata
from saas import paddle_client, payment_lifecycle_reconciliation_service


SENSITIVE_ENVIRONMENT_KEYS = (
    "DATABASE_URL",
    "PADDLE_API_KEY",
    "PADDLE_WEBHOOK_SECRET",
    "PADDLE_CLIENT_TOKEN",
)


def _redact_secrets(value: str) -> str:
    redacted = str(value or "")
    for key in SENSITIVE_ENVIRONMENT_KEYS:
        secret = str(os.getenv(key) or "")
        if secret:
            redacted = redacted.replace(secret, f"[{key}_REDACTED]")
    return redacted


def _log_traceback(exc: Exception) -> None:
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(_redact_secrets(rendered), file=sys.stderr, end="")


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
    phase = "sandbox_validation"
    try:
        _require_sandbox()
        phase = "lifecycle_reconciliation"
        result = payment_lifecycle_reconciliation_service.reconcile_finalized_lifecycle(
            db, email=args.email, apply=args.apply
        )
        if args.apply:
            phase = "database_commit"
            db.commit()
        else:
            phase = "dry_run_rollback"
            db.rollback()
        phase = "result_serialization"
        print(json.dumps(result, indent=2, default=str))
        return 0
    except payment_lifecycle_reconciliation_service.LifecycleReconciliationError as exc:
        db.rollback()
        print(json.dumps({"status": "blocked", "reason_code": exc.code, "message": str(exc)}, indent=2))
        return 2
    except Exception as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        failing_frame = frames[-1] if frames else None
        print(
            f"Unexpected reconciliation failure during {phase}:",
            file=sys.stderr,
        )
        _log_traceback(exc)
        try:
            db.rollback()
        except Exception as rollback_exc:
            print("Database rollback also failed:", file=sys.stderr)
            _log_traceback(rollback_exc)
        print(json.dumps({
            "status": "failed",
            "reason_code": "unexpected_reconciliation_error",
            "phase": phase,
            "exception_type": type(exc).__name__,
            "exception_message": _redact_secrets(str(exc)),
            "failing_function": failing_frame.name if failing_frame else None,
            "failing_file": Path(failing_frame.filename).name if failing_frame else None,
            "failing_line": failing_frame.lineno if failing_frame else None,
            "traceback_location": "Render stderr/logs",
        }, indent=2))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
