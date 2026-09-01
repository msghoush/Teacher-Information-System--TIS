from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

import models
from homeroom_defaults import is_default_homeroom_subject
from planning_subject_demand_service import resolve_scope_subject_demands


class RequirementProjectionScopeError(ValueError):
    """Raised when a requested scheduling scope crosses tenant authority."""


@dataclass(frozen=True)
class TimetableLessonRequirement:
    school_group_id: int
    branch_id: int
    academic_year_id: int
    planning_section_id: int
    subject_id: int
    subject_code: str
    required_weekly_periods: int
    is_active: bool
    demand_authority: str
    demand_source_id: int
    assigned_teacher_id: int | None
    assignment_source: str
    requirement_id: str
    source_fingerprint: str

    @property
    def is_schedulable(self) -> bool:
        return self.is_active and self.required_weekly_periods > 0

    def as_snapshot_dict(self) -> dict:
        return asdict(self)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _grade_label(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"K", "KG", "KINDERGARTEN", "0"}:
        return "KG"
    return text


def project_timetable_lesson_requirements(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    planning_section_ids: list[int] | None = None,
) -> list[TimetableLessonRequirement]:
    """Project Planning authority into deterministic timetable requirements.

    This is a read-only domain projection. It never creates or mutates Planning
    demand and it deliberately retains authoritative zero/retired rows.
    """
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()
    if (
        branch is None
        or year is None
        or int(branch.school_group_id or 0) != int(school_group_id)
        or int(year.school_group_id or 0) != int(school_group_id)
    ):
        raise RequirementProjectionScopeError(
            "The selected timetable scope is outside the requested organization."
        )

    section_query = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    )
    if planning_section_ids is not None:
        requested_ids = sorted({int(value) for value in planning_section_ids})
        if not requested_ids:
            return []
        section_query = section_query.filter(models.PlanningSection.id.in_(requested_ids))
    sections = section_query.order_by(models.PlanningSection.id.asc()).all()
    section_ids = [int(section.id) for section in sections]
    if not section_ids:
        return []

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.id.asc()).all()
    subjects_by_code = {
        str(subject.subject_code or "").strip().upper(): subject
        for subject in subjects
        if str(subject.subject_code or "").strip()
    }
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).all()
    valid_teacher_ids = {int(teacher.id) for teacher in teachers}
    assignments = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.planning_section_id.in_(section_ids)
    ).order_by(models.TeacherSectionAssignment.id.asc()).all()
    assignment_rows_by_key = {
        (int(row.planning_section_id), str(row.subject_code or "").strip().upper()): row
        for row in assignments
    }
    resolved_by_section = resolve_scope_subject_demands(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        planning_section_ids=section_ids,
    )

    projected = []
    for section in sections:
        section_id = int(section.id)
        grade = _grade_label(section.grade_level)
        for demand in resolved_by_section.get(section_id, []):
            subject = subjects_by_code.get(demand.subject_code)
            if subject is None:
                continue
            assignment = assignment_rows_by_key.get((section_id, demand.subject_code))
            teacher_id = (
                int(assignment.teacher_id)
                if assignment is not None and int(assignment.teacher_id) in valid_teacher_ids
                else None
            )
            assignment_source = "planning_invalid" if assignment is not None and teacher_id is None else "planning"
            if (
                teacher_id is None
                and section.homeroom_teacher_id is not None
                and int(section.homeroom_teacher_id) in valid_teacher_ids
                and is_default_homeroom_subject(
                    grade,
                    subject_name=str(subject.subject_name or ""),
                    subject_code=demand.subject_code,
                )
            ):
                teacher_id = int(section.homeroom_teacher_id)
                assignment_source = "homeroom_default"

            demand_source_id = int(demand.demand_id or subject.id)
            identity_authority = {
                "scope": [int(school_group_id), int(branch_id), int(academic_year_id)],
                "planning_section_id": section_id,
                "subject_id": int(subject.id),
                "subject_code": demand.subject_code,
                "demand_authority": demand.authority,
                "demand_source_id": demand_source_id,
            }
            source_authority = {
                **identity_authority,
                "required_weekly_periods": int(demand.weekly_periods or 0),
                "is_active": bool(demand.is_active),
                "assigned_teacher_id": teacher_id,
                "assignment_source": assignment_source,
            }
            projected.append(TimetableLessonRequirement(
                school_group_id=int(school_group_id),
                branch_id=int(branch_id),
                academic_year_id=int(academic_year_id),
                planning_section_id=section_id,
                subject_id=int(subject.id),
                subject_code=demand.subject_code,
                required_weekly_periods=int(demand.weekly_periods or 0),
                is_active=bool(demand.is_active),
                demand_authority=demand.authority,
                demand_source_id=demand_source_id,
                assigned_teacher_id=teacher_id,
                assignment_source=assignment_source,
                requirement_id=f"requirement:{_digest(identity_authority)}",
                source_fingerprint=_digest(source_authority),
            ))
    return sorted(
        projected,
        key=lambda item: (
            item.planning_section_id,
            item.subject_code,
            item.demand_authority,
            item.demand_source_id,
        ),
    )
