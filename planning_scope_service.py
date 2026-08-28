"""Read-only operational Planning scope authority.

Operational selectors must use real Current/New PlanningSection rows for the
selected branch and academic year, never global grade catalogs.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models
from homeroom_defaults import normalize_grade_label


OPERATIONAL_CLASS_STATUSES = frozenset({"current", "new"})


def _grade_sort_key(value: str):
    if value == "KG":
        return (0, 0, "")
    try:
        return (1, int(value), "")
    except (TypeError, ValueError):
        return (2, 0, str(value))


def is_operational_planning_section(section) -> bool:
    return (
        str(getattr(section, "class_status", "") or "").strip().lower()
        in OPERATIONAL_CLASS_STATUSES
    )


def list_operational_planning_sections(
    db: Session, branch_id: int, academic_year_id: int,
) -> list[models.PlanningSection]:
    """Return selector-safe Planning sections for exactly one branch/year."""
    rows = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).all()
    rows = [row for row in rows if is_operational_planning_section(row)]
    return sorted(
        rows,
        key=lambda row: (
            _grade_sort_key(normalize_grade_label(row.grade_level)),
            str(row.section_name or "").strip().upper(),
            int(row.id or 0),
        ),
    )


def list_operational_planning_grades(
    db: Session, branch_id: int, academic_year_id: int,
) -> list[str]:
    values = {
        normalize_grade_label(row.grade_level)
        for row in list_operational_planning_sections(db, branch_id, academic_year_id)
        if normalize_grade_label(row.grade_level)
    }
    return sorted(values, key=_grade_sort_key)
