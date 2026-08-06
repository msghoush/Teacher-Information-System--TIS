"""M4B CONTROLLED EXISTING WORKSPACE CONVERSION CLI.

Dry-run is the default. Write mode prepares a verified ownership claim or, once
that claim and setup are complete, performs the activation-required conversion.
It never creates passwords, calls Paddle, redeems promos, or sends email.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXIT_SUCCESS = 0
EXIT_BLOCKED = 2
EXIT_FAILURE = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare or execute a controlled existing-workspace conversion")
    parser.add_argument("--school-group-id", type=int, required=True)
    parser.add_argument("--workspace-uuid", required=True)
    parser.add_argument("--expected-name", required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--audit-snapshot-hash", required=True)
    parser.add_argument("--operation-uuid", required=True)
    parser.add_argument("--idempotency-key", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation-phrase", default="")
    parser.add_argument("--approved-actor-user-id", type=int)
    parser.add_argument("--execution-actor-user-id", type=int)
    parser.add_argument("--approve-owner-transfer", action="store_true")
    return parser


def _result_payload(result) -> dict:
    return {
        "status": result.status,
        "reason_code": result.reason_code,
        "operation_uuid": result.operation_uuid,
        "school_group_id": result.school_group_id,
        "stage": result.stage,
        "changed": result.changed,
        "approved_audit_snapshot_hash": result.audit_snapshot_hash,
        "current_snapshot_hash": result.current_snapshot_hash or None,
        "assurances": {
            "branch_data_changed": False,
            "paddle_called": False,
            "email_sent_by_cli": False,
            "fake_commercial_source_created": False,
        },
    }


def _failure(reason_code: str, *, status: str = "blocked") -> dict:
    return {
        "status": status,
        "reason_code": reason_code,
        "changed": False,
        "assurances": {
            "branch_data_changed": False,
            "paddle_called": False,
            "email_sent_by_cli": False,
            "fake_commercial_source_created": False,
        },
    }


def _run(args) -> tuple[dict, int]:
    if not os.getenv("DATABASE_URL", "").strip():
        return _failure("database_url_missing", status="failed"), EXIT_FAILURE
    import models  # noqa: F401 - register operational mappings
    import saas.models  # noqa: F401 - register SaaS mappings
    from database import SessionLocal
    from saas import existing_workspace_conversion_service as conversion

    db = SessionLocal()
    try:
        if db.get_bind().dialect.name != "postgresql":
            return _failure("postgresql_required", status="failed"), EXIT_FAILURE
        common = {
            "school_group_id": args.school_group_id,
            "workspace_uuid": args.workspace_uuid,
            "expected_name": args.expected_name,
            "owner_email": args.owner_email,
            "audit_snapshot_hash": args.audit_snapshot_hash,
            "operation_uuid": args.operation_uuid,
            "idempotency_key": args.idempotency_key,
        }
        if not args.execute:
            result = conversion.inspect_conversion(
                db,
                **common,
                owner_transfer_approved=args.approve_owner_transfer,
            )
            db.rollback()
            return _result_payload(result), EXIT_SUCCESS

        if not args.approved_actor_user_id or not args.execution_actor_user_id:
            raise conversion.ExistingWorkspaceConversionError("platform_actor_required")
        existing = db.query(saas.models.ExistingWorkspaceConversionOperation).filter(
            saas.models.ExistingWorkspaceConversionOperation.operation_uuid == args.operation_uuid
        ).one_or_none()
        if existing is None:
            expected_confirmation = f"PREPARE {args.operation_uuid}"
            if args.confirmation_phrase.strip() != expected_confirmation:
                raise conversion.ExistingWorkspaceConversionError("confirmation_required")
            _operation, result = conversion.prepare_registration(
                db,
                **common,
                approved_actor_user_id=args.approved_actor_user_id,
                execution_actor_user_id=args.execution_actor_user_id,
                owner_transfer_approved=args.approve_owner_transfer,
            )
        else:
            parameter_hash = conversion.canonical_parameter_hash(**common)
            result = conversion.execute_conversion(
                db,
                operation_uuid=args.operation_uuid,
                idempotency_key=args.idempotency_key,
                parameter_hash=parameter_hash,
                confirmation_phrase=args.confirmation_phrase,
                execution_actor_user_id=args.execution_actor_user_id,
            )
        db.commit()
        return _result_payload(result), EXIT_SUCCESS
    except conversion.ExistingWorkspaceConversionError as exc:
        db.rollback()
        try:
            conversion.record_failed_execution(
                db,
                operation_uuid=args.operation_uuid,
                actor_user_id=args.execution_actor_user_id,
                failure_code=exc.reason_code,
            )
            db.commit()
        except Exception:
            db.rollback()
        return _failure(exc.reason_code), EXIT_BLOCKED
    except Exception as exc:
        db.rollback()
        return _failure(f"unexpected_{type(exc).__name__}", status="failed"), EXIT_FAILURE
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload, exit_code = _run(args)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
