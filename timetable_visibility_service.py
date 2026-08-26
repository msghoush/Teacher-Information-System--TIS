from __future__ import annotations

from sqlalchemy.orm import Session

import models
from timetable_version_service import resolve_active_version, resolve_scope_school_group_id


class PublishedTimetableAccessError(ValueError):
    pass


def resolve_published_version(
    db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int
):
    resolved_group = resolve_scope_school_group_id(
        db, branch_id=branch_id, academic_year_id=academic_year_id
    )
    if int(resolved_group) != int(school_group_id):
        raise PublishedTimetableAccessError("The selected timetable scope is invalid.")
    return resolve_active_version(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )


def resolve_scoped_teacher(db: Session, *, user, branch_id: int, academic_year_id: int):
    user_id = str(getattr(user, "user_id", "") or "").strip()
    if not user_id:
        return None
    return db.query(models.Teacher).filter(
        models.Teacher.teacher_id == user_id,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).one_or_none()


def build_published_timetable_payload(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    teacher_id: int | None = None,
) -> dict:
    version = resolve_published_version(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    branch = db.query(models.Branch).filter(
        models.Branch.id == branch_id, models.Branch.school_group_id == school_group_id,
    ).one_or_none()
    year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id,
        models.AcademicYear.school_group_id == school_group_id,
    ).one_or_none()
    if branch is None or year is None:
        raise PublishedTimetableAccessError("The selected timetable scope is invalid.")
    payload = {
        "published": version is not None, "entries": [], "branch_name": branch.name,
        "academic_year_name": year.year_name,
        "published_at": version.published_at if version else None,
    }
    if version is None:
        return payload
    from timetable_logic import build_timetable_workspace_payload
    workspace = build_timetable_workspace_payload(
        db, branch_id, academic_year_id, version_id=version.id, include_validation=False
    )
    entries = workspace.get("entries", [])
    if teacher_id is not None:
        entries = [row for row in entries if int(row.get("teacher_id") or 0) == int(teacher_id)]
    times = {
        int(row.get("period_index") or 0): f'{row.get("start_time", "")} - {row.get("end_time", "")}'
        for row in workspace.get("time_slots", [])
    }
    payload["entries"] = [{
        "day": row.get("day_label"), "day_key": row.get("day_key"),
        "period": row.get("period_index"),
        "time": times.get(int(row.get("period_index") or 0), ""),
        "subject": row.get("subject_name"), "subject_code": row.get("subject_code"),
        "section": row.get("section_label"),
    } for row in entries]
    return payload
