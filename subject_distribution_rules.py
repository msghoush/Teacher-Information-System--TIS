"""Configuration-hierarchy resolver for normalized Subject Distribution Rules.

Precedence: Section override -> Grade+Subject rule -> Branch/Year default.
Field-level inheritance applies: a more specific row only overrides a field
when that field is actually set (non-NULL); unset nullable fields fall
through to the next tier. Returns ``None`` when no normalized row exists at
any tier for the scope, which callers must treat as "legacy fallback" -
existing branch/year ``quality_rules_json`` behavior applies unchanged.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models
from homeroom_defaults import normalize_grade_label

INHERITABLE_FIELDS = (
    "block_length",
    "block_count",
    "single_count",
    "min_teaching_days",
    "max_periods_per_day",
    "require_daily_coverage",
    "spread_distinct_days",
    "avoid_consecutive",
    "min_day_gap",
    "strictness",
)


def resolve_subject_distribution_rule(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
    grade_level: str,
    subject_code: str,
    section_id: int | None = None,
) -> dict | None:
    """Resolve the effective Subject Distribution Rule for one grade+subject,
    optionally narrowed to one section. Returns ``None`` for legacy fallback."""
    grade = normalize_grade_label(grade_level)
    code = str(subject_code or "").strip().upper()
    rows = db.query(models.SubjectDistributionRule).filter(
        models.SubjectDistributionRule.branch_id == int(branch_id),
        models.SubjectDistributionRule.academic_year_id == int(academic_year_id),
        models.SubjectDistributionRule.is_active.is_(True),
    ).all()

    branch_default = None
    grade_rule = None
    section_rule = None
    for row in rows:
        if row.scope_level == "branch_default":
            branch_default = row
        elif row.scope_level == "grade" and normalize_grade_label(row.grade_level) == grade \
                and str(row.subject_code or "").strip().upper() == code:
            grade_rule = row
        elif row.scope_level == "section" and section_id and int(row.section_id or 0) == int(section_id) \
                and normalize_grade_label(row.grade_level) == grade \
                and str(row.subject_code or "").strip().upper() == code:
            section_rule = row

    chain = [row for row in (section_rule, grade_rule, branch_default) if row is not None]
    if not chain:
        return None

    resolved = {"grade_level": grade, "subject_code": code, "section_id": section_id}
    for field in INHERITABLE_FIELDS:
        value = None
        for row in chain:
            value = getattr(row, field)
            if value is not None:
                break
        resolved[field] = value
    resolved["source_scope_level"] = chain[0].scope_level
    resolved["source_rule_id"] = int(chain[0].id)
    return resolved
