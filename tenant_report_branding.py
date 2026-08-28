"""Central branding authority for tenant-facing reports and exports.

Tenant artifacts may use configured branch/organization logos. They never
inherit a TIS product-logo fallback; an unbranded tenant receives no logo.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ui_shell import get_school_logo_slots


def get_tenant_report_logos(
    request,
    db: Session,
    branch_id: int,
    school_group_id: int | None = None,
) -> list[dict]:
    logos = []
    for logo in get_school_logo_slots(
        request,
        db,
        branch_id,
        school_group_id,
        include_empty=False,
    ):
        absolute_path = str(logo.get("absolute_path") or "").strip()
        if not logo.get("is_configured") or not absolute_path:
            continue
        logos.append({**logo, "absolute_path": absolute_path})
    return logos


def get_tenant_report_logo_paths(
    request,
    db: Session,
    branch_id: int,
    school_group_id: int | None = None,
) -> tuple[Path, ...]:
    return tuple(
        Path(logo["absolute_path"])
        for logo in get_tenant_report_logos(
            request, db, branch_id, school_group_id,
        )
    )
