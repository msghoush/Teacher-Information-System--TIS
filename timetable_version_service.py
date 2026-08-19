from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from timetable_snapshot_service import create_current_input_snapshot


MUTABLE_LIFECYCLE_STATUSES = {"draft", "publication_ready"}
IMMUTABLE_LIFECYCLE_STATUSES = {"superseded", "archived"}
ALLOWED_ORIGINS = {"manual", "imported", "generated", "regenerated"}


class TimetableVersionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def resolve_scope_school_group_id(
    db: Session,
    *,
    branch_id: int | None,
    academic_year_id: int | None,
) -> int:
    if not branch_id or not academic_year_id:
        raise TimetableVersionError(
            "missing_scope",
            "Select an organization, branch, and academic year before changing the timetable.",
        )
    branch = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()
    if not branch or not academic_year:
        raise TimetableVersionError(
            "missing_scope",
            "The selected timetable scope is no longer available.",
        )
    branch_group_id = int(branch.school_group_id or 0)
    year_group_id = int(academic_year.school_group_id or 0)
    if not branch_group_id or branch_group_id != year_group_id:
        raise TimetableVersionError(
            "scope_mismatch",
            "The selected branch and academic year do not belong to the same organization.",
        )
    return branch_group_id


def resolve_version(
    db: Session,
    *,
    version_id: int,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> models.TimetableVersion | None:
    return db.query(models.TimetableVersion).filter(
        models.TimetableVersion.id == version_id,
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
    ).first()


def resolve_active_version(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> models.TimetableVersion | None:
    return db.query(models.TimetableVersion).join(
        models.TimetableActiveVersion,
        models.TimetableActiveVersion.timetable_version_id
        == models.TimetableVersion.id,
    ).filter(
        models.TimetableActiveVersion.school_group_id == school_group_id,
        models.TimetableActiveVersion.branch_id == branch_id,
        models.TimetableActiveVersion.academic_year_id == academic_year_id,
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
    ).first()


def resolve_operational_version(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> models.TimetableVersion | None:
    """Resolve the Stage 2 compatibility working set without changing authority.

    A mutable draft copied from the immutable active version is preferred so the
    legacy page can keep displaying edits until Stage 4 adds explicit publication.
    """
    active_version = resolve_active_version(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    query = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
        models.TimetableVersion.lifecycle_status.in_(MUTABLE_LIFECYCLE_STATUSES),
    )
    if active_version is not None:
        working_draft = query.filter(
            models.TimetableVersion.source_version_id == active_version.id,
            models.TimetableVersion.id != active_version.id,
        ).order_by(
            models.TimetableVersion.version_number.desc(),
            models.TimetableVersion.id.desc(),
        ).first()
        return working_draft or active_version
    return query.order_by(
        models.TimetableVersion.version_number.desc(),
        models.TimetableVersion.id.desc(),
    ).first()


def _allocate_next_version_number(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> int:
    # PostgreSQL serializes allocation on the tenant root. SQLite ignores
    # FOR UPDATE but retains the unique constraint as the final guard.
    db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == school_group_id
    ).with_for_update().one()
    current = db.query(func.max(models.TimetableVersion.version_number)).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
    ).scalar()
    return int(current or 0) + 1


def create_manual_draft(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    actor_user_id: str | None = None,
    origin: str = "manual",
    source_version_id: int | None = None,
    is_stale: bool = False,
    stale_reason_json: str = "[]",
    locks: list[dict] | None = None,
) -> models.TimetableVersion:
    resolved_group_id = resolve_scope_school_group_id(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if resolved_group_id != int(school_group_id):
        raise TimetableVersionError(
            "scope_mismatch",
            "The timetable version scope does not match the selected organization.",
        )
    if origin not in ALLOWED_ORIGINS:
        raise TimetableVersionError("invalid_origin", "Timetable version origin is invalid.")
    if source_version_id is not None and resolve_version(
        db,
        version_id=source_version_id,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    ) is None:
        raise TimetableVersionError(
            "source_scope_mismatch",
            "The source timetable version is outside the selected scope.",
        )
    snapshot = create_current_input_snapshot(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        created_by_user_id=actor_user_id,
        provenance=origin,
        locks=locks,
    )
    version = models.TimetableVersion(
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        version_number=_allocate_next_version_number(
            db,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        ),
        lifecycle_status="draft",
        origin=origin,
        source_version_id=source_version_id,
        input_snapshot_id=snapshot.id,
        created_by_user_id=actor_user_id,
        authority_fingerprint=_authority_fingerprint_from_snapshot(snapshot),
        is_stale=is_stale,
        stale_reason_json=stale_reason_json or "[]",
    )
    db.add(version)
    db.flush()
    return version


def _authority_fingerprint_from_snapshot(
    snapshot: models.TimetableInputSnapshot,
) -> str:
    from timetable_snapshot_service import fingerprint

    return fingerprint(
        {
            "scope": {
                "school_group_id": int(snapshot.school_group_id),
                "branch_id": int(snapshot.branch_id),
                "academic_year_id": int(snapshot.academic_year_id),
            },
            "planning_fingerprint": snapshot.planning_fingerprint,
            "period_configuration_fingerprint": snapshot.period_configuration_fingerprint,
            "constraint_fingerprint": snapshot.constraint_fingerprint,
            "lock_fingerprint": snapshot.lock_fingerprint,
        }
    )


def copy_version_to_draft(
    db: Session,
    *,
    source_version: models.TimetableVersion,
    actor_user_id: str | None = None,
    preserve_locks: bool = True,
) -> models.TimetableVersion:
    source = resolve_version(
        db,
        version_id=int(source_version.id),
        school_group_id=int(source_version.school_group_id),
        branch_id=int(source_version.branch_id),
        academic_year_id=int(source_version.academic_year_id),
    )
    if source is None:
        raise TimetableVersionError(
            "version_not_found",
            "The source timetable version is no longer available.",
        )
    entries = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == source.id
    ).order_by(models.TimetableEntry.id.asc()).all()
    locks = [
        {
            "section_id": entry.planning_section_id,
            "subject_code": entry.subject_code,
            "teacher_id": entry.teacher_id,
            "day_key": entry.day_key,
            "period_index": entry.period_index,
        }
        for entry in entries
        if preserve_locks and entry.is_locked
    ]
    draft = create_manual_draft(
        db,
        school_group_id=int(source.school_group_id),
        branch_id=int(source.branch_id),
        academic_year_id=int(source.academic_year_id),
        actor_user_id=actor_user_id,
        origin=str(source.origin or "manual"),
        source_version_id=int(source.id),
        is_stale=bool(source.is_stale),
        stale_reason_json=str(source.stale_reason_json or "[]"),
        locks=locks,
    )
    for entry in entries:
        is_locked = bool(entry.is_locked) if preserve_locks else False
        db.add(
            models.TimetableEntry(
                timetable_version_id=draft.id,
                branch_id=draft.branch_id,
                academic_year_id=draft.academic_year_id,
                planning_section_id=entry.planning_section_id,
                subject_code=entry.subject_code,
                teacher_id=entry.teacher_id,
                day_key=entry.day_key,
                period_index=entry.period_index,
                is_locked=is_locked,
                locked_at=entry.locked_at if is_locked else None,
                locked_by_user_id=entry.locked_by_user_id if is_locked else None,
            )
        )
    db.flush()
    return draft


def _is_active_version(db: Session, version: models.TimetableVersion) -> bool:
    return db.query(models.TimetableActiveVersion.id).filter(
        models.TimetableActiveVersion.school_group_id == version.school_group_id,
        models.TimetableActiveVersion.branch_id == version.branch_id,
        models.TimetableActiveVersion.academic_year_id == version.academic_year_id,
        models.TimetableActiveVersion.timetable_version_id == version.id,
    ).first() is not None


def assert_version_mutable(db: Session, version: models.TimetableVersion) -> None:
    if version.lifecycle_status not in MUTABLE_LIFECYCLE_STATUSES:
        raise TimetableVersionError(
            "immutable_version",
            "Published, superseded, or archived timetable versions cannot be edited in place.",
        )
    if _is_active_version(db, version):
        raise TimetableVersionError(
            "immutable_active_version",
            "The active timetable cannot be edited in place; create a draft copy first.",
        )


def ensure_compatibility_editable_version(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    actor_user_id: str | None = None,
) -> models.TimetableVersion:
    current = resolve_operational_version(
        db,
        school_group_id=school_group_id,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if current is None:
        return create_manual_draft(
            db,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
            actor_user_id=actor_user_id,
        )
    try:
        assert_version_mutable(db, current)
        return current
    except TimetableVersionError as exc:
        if exc.code not in {"immutable_active_version", "immutable_version"}:
            raise
    return copy_version_to_draft(
        db,
        source_version=current,
        actor_user_id=actor_user_id,
        preserve_locks=True,
    )


def mutate_draft_placement(
    db: Session,
    *,
    version: models.TimetableVersion,
    planning_section_id: int,
    day_key: str,
    period_index: int,
    subject_code: str | None,
    teacher_id: int | None,
) -> models.TimetableEntry | None:
    assert_version_mutable(db, version)
    section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == planning_section_id,
        models.PlanningSection.branch_id == version.branch_id,
        models.PlanningSection.academic_year_id == version.academic_year_id,
    ).first()
    if section is None:
        raise TimetableVersionError(
            "section_scope_mismatch",
            "The selected section is outside the timetable version scope.",
        )
    existing = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == version.id,
        models.TimetableEntry.planning_section_id == planning_section_id,
        models.TimetableEntry.day_key == day_key,
        models.TimetableEntry.period_index == period_index,
    ).first()
    normalized_subject_code = str(subject_code or "").strip().upper()
    if not normalized_subject_code:
        if existing is None:
            raise TimetableVersionError("slot_empty", "That slot is already empty.")
        if existing.is_locked:
            raise TimetableVersionError(
                "locked_lesson",
                "Unlock this lesson before clearing it.",
            )
        db.delete(existing)
        result = None
    else:
        from timetable_logic import get_timetable_settings_payload

        projection = get_timetable_settings_payload(
            db, int(version.branch_id), int(version.academic_year_id)
        )["slot_projection"]
        slot = projection["slot_map"].get(
            (str(day_key).strip().lower(), int(period_index))
        )
        if slot is None or not slot.get("schedulable"):
            raise TimetableVersionError(
                "slot_not_schedulable",
                "This timetable slot is unavailable or has invalid configuration.",
            )
        teacher = db.query(models.Teacher).filter(
            models.Teacher.id == teacher_id,
            models.Teacher.branch_id == version.branch_id,
            models.Teacher.academic_year_id == version.academic_year_id,
        ).first()
        if teacher is None:
            raise TimetableVersionError(
                "teacher_scope_mismatch",
                "The assigned teacher is outside the timetable version scope.",
            )
        if existing is not None and existing.is_locked and (
            str(existing.subject_code or "").strip().upper() != normalized_subject_code
            or int(existing.teacher_id or 0) != int(teacher_id or 0)
        ):
            raise TimetableVersionError(
                "locked_lesson",
                "Unlock this lesson before replacing it.",
            )
        if existing is None:
            existing = models.TimetableEntry(
                timetable_version_id=version.id,
                branch_id=version.branch_id,
                academic_year_id=version.academic_year_id,
                planning_section_id=planning_section_id,
                subject_code=normalized_subject_code,
                teacher_id=teacher_id,
                day_key=day_key,
                period_index=period_index,
            )
            db.add(existing)
        else:
            existing.subject_code = normalized_subject_code
            existing.teacher_id = teacher_id
            existing.updated_at = datetime.utcnow()
        result = existing

    version.lifecycle_status = "draft"
    version.has_manual_changes = True
    version.manual_change_count = int(version.manual_change_count or 0) + 1
    version.edit_revision = int(version.edit_revision or 0) + 1
    version.updated_at = datetime.utcnow()
    db.flush()
    return result


def set_entry_lock(
    db: Session,
    *,
    version: models.TimetableVersion,
    entry: models.TimetableEntry,
    is_locked: bool,
    actor_user_id: str | None,
) -> None:
    assert_version_mutable(db, version)
    if int(entry.timetable_version_id or 0) != int(version.id or 0):
        raise TimetableVersionError(
            "entry_version_mismatch",
            "The lesson does not belong to the selected timetable version.",
        )
    entry.is_locked = bool(is_locked)
    entry.locked_at = datetime.utcnow() if is_locked else None
    entry.locked_by_user_id = actor_user_id if is_locked else None
    entry.updated_at = datetime.utcnow()
    version.lifecycle_status = "draft"
    version.has_manual_changes = True
    version.manual_change_count = int(version.manual_change_count or 0) + 1
    version.edit_revision = int(version.edit_revision or 0) + 1
    version.updated_at = datetime.utcnow()
    db.flush()


def set_imported_active_pointer(
    db: Session,
    *,
    version: models.TimetableVersion,
) -> models.TimetableActiveVersion:
    if version.origin != "imported":
        raise TimetableVersionError(
            "invalid_imported_version",
            "Only an imported compatibility version may use the Stage 2 migration pointer operation.",
        )
    existing = db.query(models.TimetableActiveVersion).filter(
        models.TimetableActiveVersion.school_group_id == version.school_group_id,
        models.TimetableActiveVersion.branch_id == version.branch_id,
        models.TimetableActiveVersion.academic_year_id == version.academic_year_id,
    ).first()
    if existing:
        if int(existing.timetable_version_id) != int(version.id):
            raise TimetableVersionError(
                "active_pointer_conflict",
                "A different active timetable already exists in this scope.",
            )
        return existing
    pointer = models.TimetableActiveVersion(
        school_group_id=version.school_group_id,
        branch_id=version.branch_id,
        academic_year_id=version.academic_year_id,
        timetable_version_id=version.id,
        activated_by_user_id=None,
        revision=0,
    )
    db.add(pointer)
    db.flush()
    return pointer


def archive_version(
    db: Session,
    *,
    version: models.TimetableVersion,
    actor_user_id: str | None,
) -> None:
    if _is_active_version(db, version):
        raise TimetableVersionError(
            "active_version_archive_forbidden",
            "The active timetable cannot be archived.",
        )
    version.lifecycle_status = "archived"
    version.archived_at = datetime.utcnow()
    version.archived_by_user_id = actor_user_id
    version.updated_at = datetime.utcnow()
    db.flush()
