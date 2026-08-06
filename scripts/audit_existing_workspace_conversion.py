"""M4A READ-ONLY EXISTING WORKSPACE CONVERSION AUDIT.

This script must not be imported by runtime application code. It performs no
conversion and must be invoked only against PostgreSQL with explicit identity
arguments.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXIT_SUCCESS = 0
EXIT_EXECUTION_FAILURE = 1
EXIT_MANUAL_REVIEW = 2
EXIT_IDENTITY_MISMATCH = 3
IDENTITY_BLOCKERS = {
    "school_group_not_found",
    "workspace_uuid_mismatch",
    "workspace_name_mismatch",
    "duplicate_normalized_workspace_name",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit an existing workspace for future conversion")
    parser.add_argument("--school-group-id", type=int, required=True)
    parser.add_argument("--workspace-uuid", required=True)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    return parser


def _failure(reason_code: str, exception_type: str | None = None) -> dict:
    result = {
        "audit_version": "m4a-1",
        "mode": "read_only",
        "status": "failed",
        "reason_code": reason_code,
        "exit_code": EXIT_EXECUTION_FAILURE,
        "assurances": {"data_changed": False, "paddle_called": False, "email_sent": False},
    }
    if exception_type:
        result["exception_type"] = exception_type
    return result


def _classify_report_exit(report: dict) -> int:
    blockers = set(report.get("conversion_readiness", {}).get("blockers", []))
    if blockers.intersection(IDENTITY_BLOCKERS):
        report["status"] = "identity_mismatch"
        report["reason_code"] = "workspace_identity_mismatch"
        report["exit_code"] = EXIT_IDENTITY_MISMATCH
        return EXIT_IDENTITY_MISMATCH
    if report.get("conversion_readiness", {}).get("status") == "manual_review_required":
        report["status"] = "manual_review_required"
        report["reason_code"] = "manual_review_required"
        report["exit_code"] = EXIT_MANUAL_REVIEW
        return EXIT_MANUAL_REVIEW
    report["status"] = "complete"
    report["reason_code"] = "audit_complete"
    report["exit_code"] = EXIT_SUCCESS
    return EXIT_SUCCESS


def _run(args: argparse.Namespace) -> tuple[dict, int]:
    if not os.getenv("DATABASE_URL", "").strip():
        return _failure("database_url_missing"), EXIT_EXECUTION_FAILURE

    import models  # noqa: F401 - register operational metadata
    import saas.models  # noqa: F401 - register SaaS metadata
    from database import SessionLocal
    from saas.existing_workspace_conversion_audit_service import (
        audit_existing_workspace_conversion,
    )

    db = SessionLocal()
    try:
        connection = db.connection()
        if connection.dialect.name != "postgresql":
            return _failure("postgresql_required"), EXIT_EXECUTION_FAILURE
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '120s'"))
        transaction_isolation = db.execute(text("SHOW transaction_isolation")).scalar_one()
        transaction_read_only = db.execute(text("SHOW transaction_read_only")).scalar_one()
        report = audit_existing_workspace_conversion(
            db,
            school_group_id=args.school_group_id,
            workspace_uuid=args.workspace_uuid,
            expected_name=args.expected_name,
            owner_email=args.owner_email,
        )
        report["transaction"] = {
            "isolation": transaction_isolation,
            "read_only": transaction_read_only,
            "rollback_on_exit": True,
        }
        exit_code = _classify_report_exit(report)
        return report, exit_code
    except Exception as exc:
        return _failure("audit_execution_failed", type(exc).__name__), EXIT_EXECUTION_FAILURE
    finally:
        try:
            db.rollback()
        finally:
            db.close()


def _render_text(report: dict) -> str:
    readiness = report.get("conversion_readiness", {})
    transaction = report.get("transaction", {})
    lines = [
        "M4A Existing Workspace Conversion Audit",
        f"Status: {report.get('status', 'failed')}",
        f"Reason: {report.get('reason_code', 'unavailable')}",
        f"Exit code: {report.get('exit_code', EXIT_EXECUTION_FAILURE)}",
        f"Snapshot SHA-256: {report.get('snapshot_hash', 'unavailable')}",
        f"Transaction isolation: {transaction.get('isolation', 'unavailable')}",
        f"Transaction read only: {transaction.get('read_only', 'unavailable')}",
        f"Rollback on exit: {str(bool(transaction.get('rollback_on_exit'))).lower()}",
        f"Readiness: {readiness.get('status', 'unavailable')}",
        "Blockers: " + (", ".join(readiness.get("blockers", [])) or "none"),
        "Warnings: " + (", ".join(readiness.get("warnings", [])) or "none"),
        "Recommended archival branch IDs: "
        + (", ".join(str(value) for value in readiness.get("recommended_archival_branch_ids", [])) or "none"),
        f"Hard deletion approved: {str(bool(readiness.get('hard_delete_approved'))).lower()}",
        f"Write conversion approved: {str(bool(readiness.get('write_conversion_approved'))).lower()}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        report, exit_code = _run(args)
    if args.format == "text":
        sys.stdout.write(_render_text(report))
    else:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
