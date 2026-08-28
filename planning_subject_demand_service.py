from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

import models


@dataclass(frozen=True)
class ResolvedPlanningSubjectDemand:
    planning_section_id: int
    subject_code: str
    weekly_periods: int
    is_active: bool
    authority: str
    demand_id: int | None = None


def _grade_label(subject_grade) -> str:
    parsed = int(subject_grade or 0)
    return "KG" if parsed == 0 else str(parsed)


def resolve_section_subject_demands(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
    planning_section_id: int,
) -> list[ResolvedPlanningSubjectDemand]:
    """Resolve explicit rows first and legacy grade demand only when absent.

    An inactive explicit row is authoritative retirement evidence and therefore
    suppresses legacy fallback for the same section and subject.
    """
    section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == planning_section_id,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if section is None:
        return []

    explicit_rows = db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.planning_section_id == planning_section_id,
        models.PlanningSubjectDemand.branch_id == branch_id,
        models.PlanningSubjectDemand.academic_year_id == academic_year_id,
    ).order_by(
        models.PlanningSubjectDemand.subject_code.asc(),
        models.PlanningSubjectDemand.is_active.desc(),
        models.PlanningSubjectDemand.id.desc(),
    ).all()
    explicit_by_code = {}
    for row in explicit_rows:
        code = str(row.subject_code or "").strip().upper()
        if code and code not in explicit_by_code:
            explicit_by_code[code] = row

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.subject_code.asc()).all()
    subject_by_code = {
        str(subject.subject_code or "").strip().upper(): subject
        for subject in subjects
        if subject.subject_code and _grade_label(subject.grade) == str(section.grade_level).strip().upper()
    }

    resolved = []
    for code in sorted(set(subject_by_code) | set(explicit_by_code)):
        explicit = explicit_by_code.get(code)
        if explicit is not None:
            resolved.append(ResolvedPlanningSubjectDemand(
                planning_section_id=int(section.id),
                subject_code=code,
                weekly_periods=int(explicit.weekly_periods or 0),
                is_active=bool(explicit.is_active),
                authority="explicit",
                demand_id=int(explicit.id),
            ))
            continue
        subject = subject_by_code[code]
        resolved.append(ResolvedPlanningSubjectDemand(
            planning_section_id=int(section.id),
            subject_code=code,
            weekly_periods=int(subject.weekly_hours or 0),
            is_active=True,
            authority="legacy_fallback",
        ))
    return resolved


def resolve_scope_subject_demands(
    db: Session,
    *,
    branch_id: int,
    academic_year_id: int,
    planning_section_ids: list[int] | None = None,
) -> dict[int, list[ResolvedPlanningSubjectDemand]]:
    """Bulk exact-scope resolver used by operational demand consumers."""
    section_query = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    )
    if planning_section_ids is not None:
        scoped_ids = sorted({int(value) for value in planning_section_ids if value is not None})
        if not scoped_ids:
            return {}
        section_query = section_query.filter(models.PlanningSection.id.in_(scoped_ids))
    sections = section_query.order_by(models.PlanningSection.id.asc()).all()
    if not sections:
        return {}

    section_ids = [int(section.id) for section in sections]
    explicit_rows = db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.branch_id == branch_id,
        models.PlanningSubjectDemand.academic_year_id == academic_year_id,
        models.PlanningSubjectDemand.planning_section_id.in_(section_ids),
    ).order_by(
        models.PlanningSubjectDemand.planning_section_id.asc(),
        models.PlanningSubjectDemand.subject_code.asc(),
        models.PlanningSubjectDemand.is_active.desc(),
        models.PlanningSubjectDemand.id.desc(),
    ).all()
    explicit_by_key = {}
    for row in explicit_rows:
        code = str(row.subject_code or "").strip().upper()
        key = (int(row.planning_section_id), code)
        if code and key not in explicit_by_key:
            explicit_by_key[key] = row

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.subject_code.asc()).all()
    subjects_by_grade = {}
    for subject in subjects:
        code = str(subject.subject_code or "").strip().upper()
        if code:
            subjects_by_grade.setdefault(_grade_label(subject.grade), {})[code] = subject

    result = {}
    for section in sections:
        section_id = int(section.id)
        grade = str(section.grade_level or "").strip().upper()
        if grade in {"K", "KINDERGARTEN", "0"}:
            grade = "KG"
        legacy_by_code = subjects_by_grade.get(grade, {})
        explicit_codes = {
            code for explicit_section_id, code in explicit_by_key
            if explicit_section_id == section_id
        }
        rows = []
        for code in sorted(set(legacy_by_code) | explicit_codes):
            explicit = explicit_by_key.get((section_id, code))
            if explicit is not None:
                rows.append(ResolvedPlanningSubjectDemand(
                    planning_section_id=section_id,
                    subject_code=code,
                    weekly_periods=int(explicit.weekly_periods or 0),
                    is_active=bool(explicit.is_active),
                    authority="explicit",
                    demand_id=int(explicit.id),
                ))
            else:
                subject = legacy_by_code[code]
                rows.append(ResolvedPlanningSubjectDemand(
                    planning_section_id=section_id,
                    subject_code=code,
                    weekly_periods=int(subject.weekly_hours or 0),
                    is_active=True,
                    authority="legacy_fallback",
                ))
        result[section_id] = rows
    return result
