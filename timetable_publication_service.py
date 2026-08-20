from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

import models
from timetable_snapshot_service import build_current_snapshot_data
from timetable_version_service import (
    TimetableVersionError,
    is_active_version,
    lock_mutable_version,
    lock_scoped_version,
)


def _blocker(code: str, message: str, label: str = "Timetable") -> dict:
    return {"code": code, "severity": "blocker", "message": message, "display_label": label}


def _locks_for_version(db: Session, version_id: int) -> list[dict]:
    return [
        {
            "section_id": row.planning_section_id,
            "subject_code": row.subject_code,
            "teacher_id": row.teacher_id,
            "day_key": row.day_key,
            "period_index": row.period_index,
        }
        for row in db.query(models.TimetableEntry).filter(
            models.TimetableEntry.timetable_version_id == version_id,
            models.TimetableEntry.is_locked.is_(True),
        ).order_by(models.TimetableEntry.id.asc()).all()
    ]


class TimetableDraftValidationService:
    """Validate one concrete version for publication without invoking a solver."""

    def __init__(self, db: Session):
        self.db = db

    def validate(
        self,
        *,
        version: models.TimetableVersion,
        expected_edit_revision: int | None = None,
        transition: bool = False,
    ) -> dict:
        if transition:
            version = lock_mutable_version(
                self.db,
                version=version,
                expected_edit_revision=expected_edit_revision,
                revision_message="This draft changed in another browser. Refresh before continuing.",
            )
        else:
            if expected_edit_revision is not None and int(version.edit_revision or 0) != int(expected_edit_revision):
                raise TimetableVersionError(
                    "edit_revision_conflict",
                    "This draft changed in another browser. Refresh before continuing.",
                )
            if version.lifecycle_status not in {"draft", "publication_ready"}:
                raise TimetableVersionError(
                    "immutable_version",
                    "Only a mutable draft can be validated for publication.",
                )

        from timetable_logic import build_timetable_workspace_payload

        payload = build_timetable_workspace_payload(
            self.db,
            int(version.branch_id),
            int(version.academic_year_id),
            version_id=int(version.id),
            include_validation=False,
        )
        blockers: list[dict] = []
        current = build_current_snapshot_data(
            self.db,
            school_group_id=int(version.school_group_id),
            branch_id=int(version.branch_id),
            academic_year_id=int(version.academic_year_id),
            locks=_locks_for_version(self.db, int(version.id)),
        )
        if current.authority_fingerprint != str(version.authority_fingerprint or ""):
            blockers.append(_blocker(
                "stale_input",
                "Planning, timetable configuration, or lesson locks changed after this version was prepared.",
            ))

        for issue in payload.get("settings", {}).get("configuration_issues", []):
            blockers.append(_blocker(issue.get("code") or "period_structure_invalid", issue.get("message") or "Timetable configuration is invalid.", issue.get("display_label") or "Configuration"))

        entries = payload.get("entries", [])
        section_slots, teacher_slots = set(), set()
        for entry in entries:
            label = f"{entry.get('section_label', 'Section')} {entry.get('subject_name', 'lesson')}"
            if entry.get("status") == "stale":
                code = "invalid_lock" if entry.get("is_locked") else "placement_invalid"
                blockers.append(_blocker(code, entry.get("stale_reason") or "A placement no longer matches current timetable authority.", label))
            section_key = (entry.get("section_id"), entry.get("day_key"), entry.get("period_index"))
            teacher_key = (entry.get("teacher_id"), entry.get("day_key"), entry.get("period_index"))
            if section_key in section_slots:
                blockers.append(_blocker("section_collision", "A section has two lessons in the same timetable slot.", entry.get("section_label") or "Section"))
            if teacher_key in teacher_slots:
                blockers.append(_blocker("teacher_collision", "A teacher has two lessons in the same timetable slot.", entry.get("teacher_name") or "Teacher"))
            section_slots.add(section_key)
            teacher_slots.add(teacher_key)

        for section in payload.get("sections", []):
            for demand in section.get("options", []):
                required = int(demand.get("weekly_hours") or 0)
                scheduled = int(demand.get("scheduled_count") or 0)
                if scheduled != required:
                    blockers.append(_blocker(
                        "demand_incomplete",
                        f"{section.get('section_label')} {demand.get('subject_name')} requires {required} periods and has {scheduled} scheduled.",
                        f"{section.get('section_label')} {demand.get('subject_name')}",
                    ))

        unique = []
        seen = set()
        for item in blockers:
            key = (item["code"], item["message"], item["display_label"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        valid = not unique
        if transition:
            version.lifecycle_status = "publication_ready" if valid else "draft"
            version.is_stale = any(item["code"] == "stale_input" for item in unique)
            version.stale_reason_json = "[\"input_changed\"]" if version.is_stale else "[]"
            version.updated_at = datetime.utcnow()
            self.db.flush()
        return {
            "valid": valid,
            "status": "ready_to_publish" if valid else "not_ready_to_publish",
            "version_number": int(version.version_number),
            "edit_revision": int(version.edit_revision or 0),
            "authority_fingerprint": current.authority_fingerprint,
            "blockers": unique,
            "counts": {"placements": len(entries), "locked_lessons": sum(1 for item in entries if item.get("is_locked")), "blockers": len(unique)},
        }


class TimetablePublicationService:
    def __init__(self, db: Session):
        self.db = db

    def publish(self, *, version_id: int, school_group_id: int, branch_id: int, academic_year_id: int, actor_user_id: str | None, expected_edit_revision: int, expected_pointer_revision: int | None) -> models.TimetableVersion:
        # Shared lock order for publication and draft mutation:
        # candidate TimetableVersion -> active pointer -> previous active version.
        version = lock_scoped_version(
            self.db,
            version_id=version_id,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        if int(version.edit_revision or 0) != int(expected_edit_revision):
            raise TimetableVersionError(
                "edit_revision_conflict",
                "This draft changed in another browser. Refresh before publishing it.",
            )
        if is_active_version(self.db, version):
            raise TimetableVersionError(
                "immutable_active_version",
                "The active timetable is already published and cannot be published again in place.",
            )
        if version.lifecycle_status != "publication_ready":
            raise TimetableVersionError("not_publication_ready", "Validate this draft successfully before publishing it.")
        validation = TimetableDraftValidationService(self.db).validate(version=version, expected_edit_revision=expected_edit_revision)
        if not validation["valid"]:
            version.lifecycle_status = "draft"
            raise TimetableVersionError("publication_validation_failed", validation["blockers"][0]["message"])

        pointer = self.db.query(models.TimetableActiveVersion).filter(
            models.TimetableActiveVersion.school_group_id == school_group_id,
            models.TimetableActiveVersion.branch_id == branch_id,
            models.TimetableActiveVersion.academic_year_id == academic_year_id,
        ).with_for_update().first()
        actual_revision = int(pointer.revision or 0) if pointer else 0
        if expected_pointer_revision is not None and actual_revision != int(expected_pointer_revision):
            raise TimetableVersionError("pointer_revision_conflict", "The active timetable changed. Refresh before publishing.")
        now = datetime.utcnow()
        previous = None
        if pointer:
            previous = self.db.query(models.TimetableVersion).filter(models.TimetableVersion.id == pointer.timetable_version_id).with_for_update().first()
            pointer.timetable_version_id = version.id
            pointer.activated_by_user_id = actor_user_id
            pointer.activated_at = now
            pointer.revision = actual_revision + 1
            pointer.updated_at = now
        else:
            pointer = models.TimetableActiveVersion(
                school_group_id=school_group_id, branch_id=branch_id,
                academic_year_id=academic_year_id, timetable_version_id=version.id,
                activated_by_user_id=actor_user_id, activated_at=now, revision=1,
            )
            self.db.add(pointer)
        if previous is not None and int(previous.id) != int(version.id):
            previous.lifecycle_status = "superseded"
            previous.superseded_at = now
            previous.superseded_by_version_id = version.id
            previous.updated_at = now
        version.lifecycle_status = "publication_ready"
        version.published_at = now
        version.published_by_user_id = actor_user_id
        version.is_stale = False
        version.stale_reason_json = "[]"
        version.updated_at = now
        self.db.flush()
        return version


def compare_timetable_versions(db: Session, *, left: models.TimetableVersion, right: models.TimetableVersion) -> dict:
    if (left.school_group_id, left.branch_id, left.academic_year_id) != (right.school_group_id, right.branch_id, right.academic_year_id):
        raise TimetableVersionError("comparison_scope_mismatch", "Timetable versions can be compared only within the same organization, branch, and academic year.")
    def rows(version):
        return db.query(models.TimetableEntry).filter(models.TimetableEntry.timetable_version_id == version.id).all()
    def identity(row):
        return (int(row.planning_section_id), str(row.subject_code or "").upper(), int(row.teacher_id))
    left_rows, right_rows = rows(left), rows(right)
    from timetable_logic import build_teacher_display_name, format_section_label
    section_ids = {int(row.planning_section_id) for row in left_rows + right_rows}
    teacher_ids = {int(row.teacher_id) for row in left_rows + right_rows}
    section_labels = {int(row.id): format_section_label(row) for row in db.query(models.PlanningSection).filter(models.PlanningSection.id.in_(section_ids)).all()} if section_ids else {}
    teacher_labels = {int(row.id): build_teacher_display_name(row) for row in db.query(models.Teacher).filter(models.Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
    left_groups, right_groups = defaultdict(list), defaultdict(list)
    for row in left_rows: left_groups[identity(row)].append(row)
    for row in right_rows: right_groups[identity(row)].append(row)
    differences, unchanged = [], 0
    for key in sorted(set(left_groups) | set(right_groups)):
        old = sorted(left_groups.get(key, []), key=lambda r: (r.day_key, r.period_index))
        new = sorted(right_groups.get(key, []), key=lambda r: (r.day_key, r.period_index))
        for index in range(max(len(old), len(new))):
            before = old[index] if index < len(old) else None
            after = new[index] if index < len(new) else None
            if before and after and (before.day_key, before.period_index) == (after.day_key, after.period_index):
                unchanged += 1
                continue
            change = "moved" if before and after else ("removed" if before else "added")
            differences.append({
                "change": change, "section_label": section_labels.get(key[0], "Unavailable section"), "subject_code": key[1], "teacher_name": teacher_labels.get(key[2], "Unavailable teacher"),
                "from": ({"day_key": before.day_key, "period_index": before.period_index} if before else None),
                "to": ({"day_key": after.day_key, "period_index": after.period_index} if after else None),
            })
    def summary(version, rows_):
        return {"version_number": version.version_number, "status": version.lifecycle_status, "origin": version.origin, "stale": bool(version.is_stale), "manual_changes": bool(version.has_manual_changes), "scheduled_periods": len(rows_), "locked_lessons": sum(1 for row in rows_ if row.is_locked)}
    return {"left": summary(left, left_rows), "right": summary(right, right_rows), "unchanged_lessons": unchanged, "differences": differences, "counts": dict(Counter(item["change"] for item in differences))}
