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


def clear_draft_approval(version: models.TimetableVersion) -> None:
    """Invalidate approval after a content or authority-affecting draft change."""
    version.approved_at = None
    version.approved_by_user_id = None


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
    working_draft = query.filter(
        models.TimetableVersion.id != (int(active_version.id) if active_version else 0),
    ).order_by(
        models.TimetableVersion.version_number.desc(),
        models.TimetableVersion.id.desc(),
    ).first()
    if working_draft is not None:
        return working_draft
    if active_version is not None:
        return active_version
    return query.order_by(
        models.TimetableVersion.version_number.desc(),
        models.TimetableVersion.id.desc(),
    ).first()


def resolve_working_version(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> models.TimetableVersion | None:
    """Return the single newest mutable, unpublished customer working copy."""
    active = resolve_active_version(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    active_id = int(active.id) if active else 0
    return db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
        models.TimetableVersion.lifecycle_status.in_(MUTABLE_LIFECYCLE_STATUSES),
        models.TimetableVersion.id != active_id,
    ).order_by(
        models.TimetableVersion.version_number.desc(),
        models.TimetableVersion.id.desc(),
    ).first()


def is_logical_draft_source(db: Session, version: models.TimetableVersion) -> bool:
    """Return whether a manual source has a generated successor in this scope."""
    if version.origin != "manual" or version.source_version_id is not None:
        return False
    return db.query(models.TimetableVersion.id).filter(
        models.TimetableVersion.source_version_id == version.id,
        models.TimetableVersion.school_group_id == version.school_group_id,
        models.TimetableVersion.branch_id == version.branch_id,
        models.TimetableVersion.academic_year_id == version.academic_year_id,
        models.TimetableVersion.origin.in_(("generated", "regenerated")),
    ).first() is not None


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


def is_active_version(db: Session, version: models.TimetableVersion) -> bool:
    return db.query(models.TimetableActiveVersion.id).filter(
        models.TimetableActiveVersion.school_group_id == version.school_group_id,
        models.TimetableActiveVersion.branch_id == version.branch_id,
        models.TimetableActiveVersion.academic_year_id == version.academic_year_id,
        models.TimetableActiveVersion.timetable_version_id == version.id,
    ).first() is not None


def _version_scope_query(db: Session, version: models.TimetableVersion):
    return db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == version.school_group_id,
        models.TimetableVersion.branch_id == version.branch_id,
        models.TimetableVersion.academic_year_id == version.academic_year_id,
    )


def _unpublished_version_descendants(
    db: Session,
    version: models.TimetableVersion,
) -> list[models.TimetableVersion]:
    descendants = []
    pending = [int(version.id)]
    seen = set(pending)
    while pending:
        children = db.query(models.TimetableVersion).filter(
            models.TimetableVersion.source_version_id.in_(pending),
        ).all()
        pending = []
        for child in children:
            child_scope = (
                int(child.school_group_id),
                int(child.branch_id),
                int(child.academic_year_id),
            )
            version_scope = (
                int(version.school_group_id),
                int(version.branch_id),
                int(version.academic_year_id),
            )
            if child_scope != version_scope or int(child.id) in seen:
                continue
            seen.add(int(child.id))
            descendants.append(child)
            pending.append(int(child.id))
    return descendants


def timetable_version_delete_eligibility(
    db: Session,
    *,
    version: models.TimetableVersion,
) -> dict:
    reasons = []
    if is_active_version(db, version):
        reasons.append("This is the active Published Timetable.")
    if version.published_at is not None:
        reasons.append("This timetable has official publication evidence.")
    if version.lifecycle_status == "superseded":
        reasons.append("This timetable is protected published history.")
    active_run = db.query(models.TimetableGenerationRun.id).filter(
        models.TimetableGenerationRun.school_group_id == version.school_group_id,
        models.TimetableGenerationRun.branch_id == version.branch_id,
        models.TimetableGenerationRun.academic_year_id == version.academic_year_id,
        models.TimetableGenerationRun.status.in_(
            ("queued", "running", "validating", "cancel_requested")
        ),
    ).first()
    if active_run:
        reasons.append("Timetable generation is still active for this scope.")

    descendants = _unpublished_version_descendants(db, version)
    cross_scope_child = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.source_version_id == version.id,
        ~(
            (models.TimetableVersion.school_group_id == version.school_group_id)
            & (models.TimetableVersion.branch_id == version.branch_id)
            & (models.TimetableVersion.academic_year_id == version.academic_year_id)
        ),
    ).first()
    if cross_scope_child is not None:
        reasons.append("A version in another scope references this timetable.")
    protected_descendant = next(
        (
            child
            for child in descendants
            if child.published_at is not None
            or child.lifecycle_status == "superseded"
            or is_active_version(db, child)
        ),
        None,
    )
    if protected_descendant is not None:
        reasons.append("A protected published timetable depends on this version.")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "version_ids": [int(version.id)] + [int(child.id) for child in descendants],
    }


def lock_scoped_version(
    db: Session,
    *,
    version_id: int,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> models.TimetableVersion:
    """Lock and refresh one exact-scope version before a state change.

    PostgreSQL uses the row lock to serialize publication and draft mutation.
    SQLite ignores ``FOR UPDATE`` but retains the same validation behavior for
    local/test compatibility.
    """
    with db.no_autoflush:
        resolved_group_id = resolve_scope_school_group_id(
            db,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        if int(resolved_group_id) != int(school_group_id):
            raise TimetableVersionError(
                "scope_mismatch",
                "The timetable version scope does not match the selected organization.",
            )
        version = db.query(models.TimetableVersion).filter(
            models.TimetableVersion.id == version_id,
            models.TimetableVersion.school_group_id == school_group_id,
            models.TimetableVersion.branch_id == branch_id,
            models.TimetableVersion.academic_year_id == academic_year_id,
        ).populate_existing().with_for_update().first()
    if version is None:
        raise TimetableVersionError(
            "version_not_found",
            "The selected timetable version is outside the current scope.",
        )
    return version


def lock_mutable_version(
    db: Session,
    *,
    version: models.TimetableVersion,
    expected_edit_revision: int | None = None,
    revision_message: str = "This draft changed in another browser. Refresh before editing it.",
) -> models.TimetableVersion:
    """Lock first, then re-evaluate pointer authority, lifecycle, and revision."""
    locked = lock_scoped_version(
        db,
        version_id=int(version.id),
        school_group_id=int(version.school_group_id),
        branch_id=int(version.branch_id),
        academic_year_id=int(version.academic_year_id),
    )
    if is_active_version(db, locked):
        raise TimetableVersionError(
            "immutable_active_version",
            "The active timetable cannot be edited in place; create a draft copy first.",
        )
    if locked.lifecycle_status not in MUTABLE_LIFECYCLE_STATUSES:
        raise TimetableVersionError(
            "immutable_version",
            "Published, superseded, or archived timetable versions cannot be edited in place.",
        )
    if (
        expected_edit_revision is not None
        and int(locked.edit_revision or 0) != int(expected_edit_revision)
    ):
        raise TimetableVersionError("edit_revision_conflict", revision_message)
    return locked


def assert_version_mutable(db: Session, version: models.TimetableVersion) -> None:
    if version.lifecycle_status not in MUTABLE_LIFECYCLE_STATUSES:
        raise TimetableVersionError(
            "immutable_version",
            "Published, superseded, or archived timetable versions cannot be edited in place.",
        )
    if is_active_version(db, version):
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
    expected_edit_revision: int | None = None,
) -> models.TimetableEntry | None:
    version = lock_mutable_version(
        db,
        version=version,
        expected_edit_revision=expected_edit_revision,
    )
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
        if not projection.get("valid"):
            raise TimetableVersionError(
                "slot_not_schedulable",
                "Correct the timetable timeline configuration before assigning lessons.",
            )
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
    clear_draft_approval(version)
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
    expected_edit_revision: int | None = None,
) -> None:
    entry_id = int(entry.id or 0)
    version = lock_mutable_version(
        db,
        version=version,
        expected_edit_revision=expected_edit_revision,
        revision_message="This draft changed in another browser. Refresh before changing lesson locks.",
    )
    with db.no_autoflush:
        entry = db.query(models.TimetableEntry).filter(
            models.TimetableEntry.id == entry_id,
            models.TimetableEntry.timetable_version_id == version.id,
        ).populate_existing().first()
    if entry is None:
        raise TimetableVersionError(
            "entry_version_mismatch",
            "The lesson does not belong to the selected timetable version.",
        )
    entry.is_locked = bool(is_locked)
    entry.locked_at = datetime.utcnow() if is_locked else None
    entry.locked_by_user_id = actor_user_id if is_locked else None
    entry.updated_at = datetime.utcnow()
    version.lifecycle_status = "draft"
    clear_draft_approval(version)
    version.has_manual_changes = True
    version.manual_change_count = int(version.manual_change_count or 0) + 1
    version.edit_revision = int(version.edit_revision or 0) + 1
    version.updated_at = datetime.utcnow()
    _refresh_version_authority(db, version)
    db.flush()


def _refresh_version_authority(db: Session, version: models.TimetableVersion) -> None:
    locks = [
        {
            "section_id": row.planning_section_id,
            "subject_code": row.subject_code,
            "teacher_id": row.teacher_id,
            "day_key": row.day_key,
            "period_index": row.period_index,
        }
        for row in db.query(models.TimetableEntry).filter(
            models.TimetableEntry.timetable_version_id == version.id,
            models.TimetableEntry.is_locked.is_(True),
        ).order_by(models.TimetableEntry.id.asc()).all()
    ]
    snapshot = create_current_input_snapshot(
        db,
        school_group_id=int(version.school_group_id),
        branch_id=int(version.branch_id),
        academic_year_id=int(version.academic_year_id),
        created_by_user_id=version.created_by_user_id,
        provenance="lock_edit",
        locks=locks,
    )
    version.input_snapshot_id = snapshot.id
    version.authority_fingerprint = _authority_fingerprint_from_snapshot(snapshot)
    version.is_stale = False
    version.stale_reason_json = "[]"


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
    version = lock_scoped_version(
        db,
        version_id=int(version.id),
        school_group_id=int(version.school_group_id),
        branch_id=int(version.branch_id),
        academic_year_id=int(version.academic_year_id),
    )
    if is_active_version(db, version):
        raise TimetableVersionError(
            "active_version_archive_forbidden",
            "The active timetable cannot be archived.",
        )
    if version.lifecycle_status not in {"draft", "superseded"}:
        raise TimetableVersionError(
            "archive_status_invalid",
            "Only a draft or superseded timetable can be archived.",
        )
    version.lifecycle_status = "archived"
    version.archived_at = datetime.utcnow()
    version.archived_by_user_id = actor_user_id
    version.updated_at = datetime.utcnow()
    db.flush()


def discard_working_version(
    db: Session,
    *,
    version_id: int,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    actor_user_id: str | None,
) -> models.TimetableVersion:
    """Archive the current working copy while preserving every historical row."""
    db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == school_group_id
    ).with_for_update().one()
    version = lock_scoped_version(
        db, version_id=version_id, school_group_id=school_group_id,
        branch_id=branch_id, academic_year_id=academic_year_id,
    )
    current = resolve_working_version(
        db, school_group_id=school_group_id, branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    if current is None or int(current.id) != int(version.id):
        raise TimetableVersionError(
            "working_version_changed",
            "The working timetable changed. Refresh before deleting it.",
        )
    if is_active_version(db, version):
        raise TimetableVersionError(
            "published_delete_forbidden", "The published timetable cannot be deleted."
        )
    active_run = db.query(models.TimetableGenerationRun.id).filter(
        models.TimetableGenerationRun.school_group_id == school_group_id,
        models.TimetableGenerationRun.branch_id == branch_id,
        models.TimetableGenerationRun.academic_year_id == academic_year_id,
        models.TimetableGenerationRun.status.in_(
            ("queued", "running", "validating", "cancel_requested")
        ),
    ).first()
    if active_run:
        raise TimetableVersionError(
            "generation_in_progress",
            "Wait for timetable generation to finish before deleting the working timetable.",
        )
    version.lifecycle_status = "archived"
    version.archived_at = datetime.utcnow()
    version.archived_by_user_id = actor_user_id
    version.updated_at = datetime.utcnow()
    db.flush()
    return version


def delete_unused_timetable_version(
    db: Session,
    *,
    version_id: int,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> None:
    """Permanently remove an unpublished, unreferenced candidate from History."""
    db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == school_group_id
    ).with_for_update().one()
    version = lock_scoped_version(
        db, version_id=version_id, school_group_id=school_group_id,
        branch_id=branch_id, academic_year_id=academic_year_id,
    )
    eligibility = timetable_version_delete_eligibility(db, version=version)
    if not eligibility["eligible"]:
        error_code = "version_delete_forbidden"
        if is_active_version(db, version):
            error_code = "published_delete_forbidden"
        elif version.published_at is not None or version.lifecycle_status == "superseded":
            error_code = "published_history_delete_forbidden"
        raise TimetableVersionError(
            error_code,
            eligibility["reasons"][0],
        )
    _delete_unpublished_version_ids(db, eligibility["version_ids"])


def _delete_unpublished_version_ids(db: Session, version_ids: list[int]) -> None:
    version_ids = {int(version_id) for version_id in version_ids}
    if not version_ids:
        return
    entries = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id.in_(version_ids)
    ).all()
    for entry in entries:
        db.delete(entry)
    db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.source_version_id.in_(version_ids)
    ).update({models.TimetableGenerationRun.source_version_id: None}, synchronize_session="fetch")
    db.query(models.TimetableGenerationRun).filter(
        models.TimetableGenerationRun.result_version_id.in_(version_ids)
    ).update({models.TimetableGenerationRun.result_version_id: None}, synchronize_session="fetch")
    versions = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.id.in_(version_ids)
    ).all()
    for candidate in sorted(versions, key=lambda item: int(item.id), reverse=True):
        db.delete(candidate)
    db.flush()


def delete_all_unused_timetable_versions(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
) -> dict:
    db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == school_group_id
    ).with_for_update().one()
    versions = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
    ).order_by(models.TimetableVersion.id.desc()).all()
    pending = {
        int(version.id): version
        for version in versions
        if version.published_at is None
        and not is_active_version(db, version)
    }
    deleted_ids = set()
    remaining = []
    while pending:
        progress = False
        for version_id, version in list(pending.items()):
            if version_id in deleted_ids:
                pending.pop(version_id, None)
                continue
            eligibility = timetable_version_delete_eligibility(db, version=version)
            if not eligibility["eligible"]:
                remaining.append({
                    "version_id": version_id,
                    "version_number": int(version.version_number),
                    "reasons": eligibility["reasons"],
                })
                pending.pop(version_id, None)
                continue
            ids = set(eligibility["version_ids"]) & set(pending)
            _delete_unpublished_version_ids(db, sorted(ids, reverse=True))
            deleted_ids.update(ids)
            for deleted_id in ids:
                pending.pop(deleted_id, None)
            progress = True
        if not progress:
            break
    for version in pending.values():
        remaining.append({
            "version_id": int(version.id),
            "version_number": int(version.version_number),
            "reasons": ["This version is part of a protected lineage."],
        })
    return {
        "deleted_version_ids": sorted(deleted_ids),
        "deleted_count": len(deleted_ids),
        "remaining": remaining,
    }


def move_or_swap_timetable_entry(
    db: Session,
    *,
    version: models.TimetableVersion,
    entry_id: int,
    destination_section_id: int,
    destination_day_key: str,
    destination_period_index: int,
    expected_edit_revision: int | None = None,
) -> str:
    """Atomically move one lesson, or swap it with the destination lesson."""
    version = lock_mutable_version(
        db, version=version, expected_edit_revision=expected_edit_revision,
        revision_message="This timetable changed in another browser. Refresh before moving the lesson.",
    )
    entries = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.timetable_version_id == version.id
    ).with_for_update().all()
    source = next((row for row in entries if int(row.id) == int(entry_id)), None)
    if source is None:
        raise TimetableVersionError("entry_not_found", "The selected lesson is not in this timetable.")
    if source.is_locked:
        raise TimetableVersionError("locked_lesson", "Unlock this lesson before moving it")
    section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == destination_section_id,
        models.PlanningSection.branch_id == version.branch_id,
        models.PlanningSection.academic_year_id == version.academic_year_id,
    ).first()
    if section is None:
        raise TimetableVersionError("section_scope_mismatch", "The destination class is outside this timetable.")

    from timetable_logic import get_timetable_settings_payload
    projection = get_timetable_settings_payload(
        db, int(version.branch_id), int(version.academic_year_id)
    )["slot_projection"]
    slot = projection.get("slot_map", {}).get(
        (str(destination_day_key).strip().lower(), int(destination_period_index))
    )
    if not projection.get("valid") or slot is None or not slot.get("schedulable"):
        raise TimetableVersionError("non_teaching_period", "This is a non-teaching period")

    destination = next((
        row for row in entries
        if int(row.planning_section_id) == int(destination_section_id)
        and str(row.day_key) == str(destination_day_key)
        and int(row.period_index) == int(destination_period_index)
    ), None)
    if destination is source:
        return "moved"
    if destination is not None and destination.is_locked:
        raise TimetableVersionError("locked_lesson", "Unlock this lesson before moving it")

    source_position = (
        int(source.planning_section_id), str(source.day_key), int(source.period_index)
    )
    proposed = [(source, int(destination_section_id), str(destination_day_key), int(destination_period_index))]
    if destination is not None:
        proposed.append((destination, *source_position))
    ignored_ids = {int(item[0].id) for item in proposed}
    for moving, section_id, day_key, period_index in proposed:
        section_collision = next((
            row for row in entries if int(row.id) not in ignored_ids
            and int(row.planning_section_id) == section_id
            and str(row.day_key) == day_key and int(row.period_index) == period_index
        ), None)
        if section_collision:
            raise TimetableVersionError("section_collision", "Class already has a lesson at this time")
        teacher_collision = next((
            row for row in entries if int(row.id) not in ignored_ids
            and int(row.teacher_id) == int(moving.teacher_id)
            and str(row.day_key) == day_key and int(row.period_index) == period_index
        ), None)
        if teacher_collision:
            raise TimetableVersionError("teacher_collision", "Teacher already has a lesson at this time")

    # Temporarily vacate both unique keys before applying the final positions.
    for index, (moving, _, _, _) in enumerate(proposed, start=1):
        moving.day_key = f"__moving_{index}"
        moving.period_index = -index
    db.flush()
    now = datetime.utcnow()
    for moving, section_id, day_key, period_index in proposed:
        moving.planning_section_id = section_id
        moving.day_key = day_key
        moving.period_index = period_index
        moving.updated_at = now
    version.lifecycle_status = "draft"
    clear_draft_approval(version)
    version.has_manual_changes = True
    version.manual_change_count = int(version.manual_change_count or 0) + 1
    version.edit_revision = int(version.edit_revision or 0) + 1
    version.updated_at = now
    db.flush()
    return "swapped" if destination is not None else "moved"
