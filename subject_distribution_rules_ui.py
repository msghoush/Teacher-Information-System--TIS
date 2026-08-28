"""Subject Scheduling Rules UI service.

Lists Grade+Subject rows sourced from Planning, and creates/updates/resets
grade-level or section-override Subject Distribution Rules. Planning remains
the authoritative weekly-period source; this module only manages HOW those
periods are distributed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models
from homeroom_defaults import normalize_grade_label
from subject_distribution_rules import resolve_subject_distribution_rule
from subject_distribution_validator import validate_subject_distribution_rule

DAILY_COVERAGE_OPTIONS = (
    {"key": "auto", "label": "Automatic"},
    {"key": "always", "label": "Always require every teaching day"},
    {"key": "never", "label": "Never require daily coverage"},
)
STRICTNESS_OPTIONS = (
    {"key": "soft", "label": "Preference"},
    {"key": "hard", "label": "Hard rule"},
)
RULE_FIELDS = (
    "block_length", "block_count", "single_count", "min_teaching_days",
    "max_periods_per_day", "require_daily_coverage", "spread_distinct_days",
    "avoid_consecutive", "min_day_gap", "strictness",
)
DEFAULT_RULE_FIELDS = {
    "block_length": 2, "block_count": 0, "single_count": 0,
    "min_teaching_days": None, "max_periods_per_day": None,
    "require_daily_coverage": "auto", "spread_distinct_days": True,
    "avoid_consecutive": True, "min_day_gap": None, "strictness": "soft",
}


def describe_distribution(block_count: int, block_length: int, single_count: int) -> str:
    parts = []
    if block_count:
        block_word = "block" if block_count == 1 else "blocks"
        block_label = "double" if block_length == 2 else f"{block_length}-period"
        parts.append(f"{block_count} {block_label} {block_word}")
    if single_count:
        parts.append(f"{single_count} single{'' if single_count == 1 else 's'}")
    return " + ".join(parts) if parts else "No sessions configured"


def _grade_sort_key(value: str):
    if value == "KG":
        return (0, 0, "")
    try:
        return (1, int(value), "")
    except (TypeError, ValueError):
        return (2, 0, str(value))


def _subject_grade_label(subject) -> str:
    return "KG" if int(subject.grade or 0) == 0 else str(int(subject.grade or 0))


def list_subject_scheduling_rows(db: Session, branch_id: int, academic_year_id: int) -> list[dict]:
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
        models.Subject.weekly_hours > 0,
    ).order_by(models.Subject.grade.asc(), models.Subject.subject_code.asc()).all()

    rows = []
    sections_by_grade: dict[str, list[dict]] = {}
    for subject in subjects:
        grade_label = _subject_grade_label(subject)
        code = str(subject.subject_code or "").strip().upper()
        if not code:
            continue
        weekly = int(subject.weekly_hours or 0)
        resolved = resolve_subject_distribution_rule(
            db, branch_id=branch_id, academic_year_id=academic_year_id,
            grade_level=grade_label, subject_code=code, section_id=None,
        )
        is_configured = bool(resolved) and resolved.get("source_scope_level") == "grade"
        effective = resolved or {**DEFAULT_RULE_FIELDS, "single_count": weekly}
        if grade_label not in sections_by_grade:
            sections_by_grade[grade_label] = list_sections_for_grade(
                db, branch_id, academic_year_id, grade_label
            )
        section_overrides = []
        for section in sections_by_grade[grade_label]:
            section_resolved = resolve_subject_distribution_rule(
                db, branch_id=branch_id, academic_year_id=academic_year_id,
                grade_level=grade_label, subject_code=code, section_id=section["id"],
            )
            has_override = bool(section_resolved) and section_resolved.get("source_scope_level") == "section"
            section_overrides.append({
                **section, "rule": section_resolved, "has_override": has_override,
            })
        rows.append({
            "grade_level": grade_label,
            "subject_code": code,
            "subject_name": str(subject.subject_name or code).strip(),
            "weekly_periods": weekly,
            "rule": resolved,
            "effective": effective,
            "is_configured": is_configured,
            "status_label": "Configured" if is_configured else "Using Default Scheduling Rules",
            "distribution_summary": describe_distribution(
                int(effective.get("block_count") or 0),
                int(effective.get("block_length") or 2),
                int(effective.get("single_count") or 0),
            ),
            "min_teaching_days": effective.get("min_teaching_days"),
            "max_periods_per_day": effective.get("max_periods_per_day"),
            "section_override_count": sum(1 for item in section_overrides if item["has_override"]),
            "section_overrides": section_overrides,
        })
    rows.sort(key=lambda item: (_grade_sort_key(item["grade_level"]), item["subject_code"]))
    return rows


def list_grade_levels(db: Session, branch_id: int, academic_year_id: int) -> list[str]:
    values = {
        _subject_grade_label(row)
        for row in db.query(models.Subject).filter(
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).all()
    }
    return sorted(values, key=_grade_sort_key)


def list_sections_for_grade(db: Session, branch_id: int, academic_year_id: int, grade_level: str) -> list[dict]:
    grade = normalize_grade_label(grade_level)
    sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).order_by(models.PlanningSection.section_name.asc()).all()
    return [
        {"id": int(section.id), "section_name": str(section.section_name or "").strip()}
        for section in sections
        if normalize_grade_label(section.grade_level) == grade
    ]


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value) -> int | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def normalize_rule_form_fields(form: dict) -> dict:
    return {
        "block_length": _int_or(form.get("block_length"), 2),
        "block_count": _int_or(form.get("block_count"), 0),
        "single_count": _int_or(form.get("single_count"), 0),
        "min_teaching_days": _optional_int(form.get("min_teaching_days")),
        "max_periods_per_day": _optional_int(form.get("max_periods_per_day")),
        "require_daily_coverage": str(form.get("require_daily_coverage") or "auto"),
        "spread_distinct_days": bool(form.get("spread_distinct_days")),
        "avoid_consecutive": bool(form.get("avoid_consecutive")),
        "min_day_gap": _optional_int(form.get("min_day_gap")),
        "strictness": str(form.get("strictness") or "soft"),
    }


def _weekly_periods_for(db: Session, branch_id: int, academic_year_id: int, grade_level: str, subject_code: str) -> int | None:
    grade = normalize_grade_label(grade_level)
    code = str(subject_code or "").strip().upper()
    for subject in db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
        models.Subject.subject_code == code,
    ).all():
        if _subject_grade_label(subject) == grade:
            return int(subject.weekly_hours or 0)
    return None


def save_subject_distribution_rule(
    db: Session, *, branch_id: int, academic_year_id: int, grade_level: str,
    subject_code: str, section_id: int | None, fields: dict,
    teaching_day_count: int, actor_user_id: str | None,
) -> list[dict]:
    """Validate then create/update exactly the intended Grade+Subject (or
    section-override) rule. Returns validation errors; empty means saved."""
    grade = normalize_grade_label(grade_level)
    code = str(subject_code or "").strip().upper()
    weekly = _weekly_periods_for(db, branch_id, academic_year_id, grade, code)
    if weekly is None:
        return [{"code": "subject_not_found", "message": "That grade and subject no longer exist in Planning."}]

    normalized = normalize_rule_form_fields(fields)
    errors = validate_subject_distribution_rule(
        normalized, planning_weekly_periods=weekly, available_teaching_days=teaching_day_count,
    )
    if errors:
        return errors

    scope_level = "section" if section_id else "grade"
    query = db.query(models.SubjectDistributionRule).filter(
        models.SubjectDistributionRule.branch_id == branch_id,
        models.SubjectDistributionRule.academic_year_id == academic_year_id,
        models.SubjectDistributionRule.scope_level == scope_level,
        models.SubjectDistributionRule.grade_level == grade,
        models.SubjectDistributionRule.subject_code == code,
    )
    query = (
        query.filter(models.SubjectDistributionRule.section_id == int(section_id))
        if section_id else query.filter(models.SubjectDistributionRule.section_id.is_(None))
    )
    row = query.first()
    if row is None:
        row = models.SubjectDistributionRule(
            branch_id=branch_id, academic_year_id=academic_year_id,
            scope_level=scope_level, grade_level=grade, subject_code=code,
            section_id=int(section_id) if section_id else None,
            created_by_user_id=actor_user_id,
        )
        db.add(row)
    for field in RULE_FIELDS:
        setattr(row, field, normalized[field])
    row.is_active = True
    row.updated_by_user_id = actor_user_id
    db.commit()
    return []


def reset_subject_distribution_rule(
    db: Session, *, branch_id: int, academic_year_id: int, grade_level: str, subject_code: str,
) -> bool:
    """Remove the grade-level override so the effective rule falls back to
    the branch/year default (or legacy behavior). Section overrides are
    untouched."""
    grade = normalize_grade_label(grade_level)
    code = str(subject_code or "").strip().upper()
    row = db.query(models.SubjectDistributionRule).filter(
        models.SubjectDistributionRule.branch_id == branch_id,
        models.SubjectDistributionRule.academic_year_id == academic_year_id,
        models.SubjectDistributionRule.scope_level == "grade",
        models.SubjectDistributionRule.grade_level == grade,
        models.SubjectDistributionRule.subject_code == code,
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def clear_section_override(
    db: Session, *, branch_id: int, academic_year_id: int, grade_level: str,
    subject_code: str, section_id: int,
) -> bool:
    grade = normalize_grade_label(grade_level)
    code = str(subject_code or "").strip().upper()
    row = db.query(models.SubjectDistributionRule).filter(
        models.SubjectDistributionRule.branch_id == branch_id,
        models.SubjectDistributionRule.academic_year_id == academic_year_id,
        models.SubjectDistributionRule.scope_level == "section",
        models.SubjectDistributionRule.grade_level == grade,
        models.SubjectDistributionRule.subject_code == code,
        models.SubjectDistributionRule.section_id == int(section_id),
    ).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def copy_grade_rules(
    db: Session, *, branch_id: int, academic_year_id: int, source_grade: str,
    target_grade: str, teaching_day_count: int, actor_user_id: str | None,
) -> dict:
    """Copy every grade-level rule from ``source_grade`` to ``target_grade``,
    skipping subjects whose arithmetic does not fit the target's Planning
    weekly requirement instead of blindly copying an invalid configuration.

    Subject codes are unique per branch/year and therefore grade-specific
    (e.g. Grade 3 and Grade 4 English use different codes), so subjects are
    matched across grades by name rather than by code.
    """
    source = normalize_grade_label(source_grade)
    target = normalize_grade_label(target_grade)
    source_rules = db.query(models.SubjectDistributionRule).filter(
        models.SubjectDistributionRule.branch_id == branch_id,
        models.SubjectDistributionRule.academic_year_id == academic_year_id,
        models.SubjectDistributionRule.scope_level == "grade",
        models.SubjectDistributionRule.grade_level == source,
        models.SubjectDistributionRule.is_active.is_(True),
    ).all()
    all_subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).all()
    source_subjects_by_code = {
        str(item.subject_code or "").strip().upper(): item
        for item in all_subjects if _subject_grade_label(item) == source
    }
    target_subjects_by_name = {
        str(item.subject_name or "").strip().lower(): item
        for item in all_subjects if _subject_grade_label(item) == target
    }

    applied, skipped = [], []
    for rule_row in source_rules:
        code = str(rule_row.subject_code or "").strip().upper()
        source_subject = source_subjects_by_code.get(code)
        label = str(getattr(source_subject, "subject_name", "") or code).strip()
        target_subject = target_subjects_by_name.get(label.lower())
        if target_subject is None:
            skipped.append(f"{label} (not offered in Grade {target})")
            continue
        weekly = int(target_subject.weekly_hours or 0)
        candidate = {field: getattr(rule_row, field) for field in RULE_FIELDS}
        errors = validate_subject_distribution_rule(
            candidate, planning_weekly_periods=weekly, available_teaching_days=teaching_day_count,
        )
        if errors:
            skipped.append(f"{label} ({errors[0]['message']})")
            continue
        target_code = str(target_subject.subject_code or "").strip().upper()
        target_row = db.query(models.SubjectDistributionRule).filter(
            models.SubjectDistributionRule.branch_id == branch_id,
            models.SubjectDistributionRule.academic_year_id == academic_year_id,
            models.SubjectDistributionRule.scope_level == "grade",
            models.SubjectDistributionRule.grade_level == target,
            models.SubjectDistributionRule.subject_code == target_code,
        ).first()
        if target_row is None:
            target_row = models.SubjectDistributionRule(
                branch_id=branch_id, academic_year_id=academic_year_id,
                scope_level="grade", grade_level=target, subject_code=target_code,
                created_by_user_id=actor_user_id,
            )
            db.add(target_row)
        for field in RULE_FIELDS:
            setattr(target_row, field, candidate[field])
        target_row.is_active = True
        target_row.updated_by_user_id = actor_user_id
        applied.append(label)
    db.commit()
    return {"applied": applied, "skipped": skipped}
