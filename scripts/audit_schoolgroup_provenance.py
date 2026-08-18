"""Read-only audit for SchoolGroups with incomplete creation provenance."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from sqlalchemy import text


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_REVIEW_REQUIRED = 2


def _workspace_ref(workspace_uuid: str) -> str:
    value = str(workspace_uuid or "").strip().encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:16]


def _failure(reason_code: str, exception_type: str | None = None) -> dict:
    report = {
        "audit_version": "schoolgroup-provenance-1",
        "mode": "read_only",
        "status": "failed",
        "reason_code": reason_code,
        "candidate_count": 0,
        "candidates": [],
        "assurances": {"data_changed": False, "rollback_on_exit": True},
    }
    if exception_type:
        report["exception_type"] = exception_type
    return report


def _run() -> tuple[dict, int]:
    if not os.getenv("DATABASE_URL", "").strip():
        return _failure("database_url_missing"), EXIT_FAILURE

    from database import SessionLocal

    db = SessionLocal()
    try:
        connection = db.connection()
        if connection.dialect.name != "postgresql":
            return _failure("postgresql_required"), EXIT_FAILURE
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        db.execute(text("SET LOCAL statement_timeout = '120s'"))
        rows = db.execute(text("""
            SELECT
                sg.id AS school_group_id,
                sg.workspace_uuid,
                sg.created_at,
                (SELECT COUNT(*) FROM branches b WHERE b.school_group_id = sg.id) AS branch_count,
                (SELECT COUNT(*) FROM users u WHERE u.school_group_id = sg.id) AS user_count,
                (
                    SELECT COUNT(*)
                    FROM teachers t
                    JOIN branches b ON b.id = t.branch_id
                    WHERE b.school_group_id = sg.id
                ) AS teacher_count,
                (
                    SELECT COUNT(*)
                    FROM academic_years ay
                    WHERE ay.school_group_id = sg.id
                ) AS academic_year_count
            FROM school_groups sg
            WHERE sg.workspace_classification = 'internal_sandbox'
              AND sg.workspace_lifecycle_status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM tenant_provisioning_links tpl
                  WHERE tpl.school_group_id = sg.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM workspace_entitlements we
                  WHERE we.school_group_id = sg.id
              )
            ORDER BY sg.id
        """)).mappings().all()
        candidates = []
        for row in rows:
            branch_count = int(row["branch_count"] or 0)
            user_count = int(row["user_count"] or 0)
            teacher_count = int(row["teacher_count"] or 0)
            academic_year_count = int(row["academic_year_count"] or 0)
            candidates.append({
                "school_group_id": int(row["school_group_id"]),
                "workspace_ref": _workspace_ref(row["workspace_uuid"]),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "branch_count": branch_count,
                "user_count": user_count,
                "teacher_count": teacher_count,
                "academic_year_count": academic_year_count,
                "minimal_operational_data": bool(
                    branch_count <= 1
                    and user_count == 0
                    and teacher_count == 0
                    and academic_year_count == 0
                ),
                "provenance_evidence": "no_creator_attribution_available",
                "recommended_action": "platform_owner_review",
            })
        status = "review_required" if candidates else "clear"
        return ({
            "audit_version": "schoolgroup-provenance-1",
            "mode": "read_only",
            "status": status,
            "reason_code": "candidate_workspaces_found" if candidates else "no_candidates_found",
            "candidate_count": len(candidates),
            "candidates": candidates,
            "transaction": {
                "isolation": db.execute(text("SHOW transaction_isolation")).scalar_one(),
                "read_only": db.execute(text("SHOW transaction_read_only")).scalar_one(),
                "rollback_on_exit": True,
            },
            "assurances": {"data_changed": False, "rollback_on_exit": True},
        }, EXIT_REVIEW_REQUIRED if candidates else EXIT_SUCCESS)
    except Exception as exc:
        return _failure("audit_execution_failed", type(exc).__name__), EXIT_FAILURE
    finally:
        try:
            db.rollback()
        finally:
            db.close()


def main() -> int:
    report, exit_code = _run()
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
