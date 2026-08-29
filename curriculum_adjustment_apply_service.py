from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

import models
from curriculum_adjustment_preview_service import (
    CurriculumAdjustmentPreviewRequest,
    build_curriculum_adjustment_preview,
)
from teacher_capacity import get_teacher_international_capacity_hours
from timetable_generation_service import ACTIVE_STATUSES
from timetable_version_service import clear_draft_approval


class CurriculumAdjustmentApplyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CurriculumAdjustmentApplyRequest:
    preview_request: CurriculumAdjustmentPreviewRequest
    preview_fingerprint: str
    teacher_decisions: dict[int, int | None]


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _lock_scope(db: Session, *, school_group_id: int, branch_id: int, academic_year_id: int) -> None:
    db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
        models.PlanningSection.class_status.in_(("Current", "New")),
    ).with_for_update().all()
    db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.branch_id == branch_id,
        models.PlanningSubjectDemand.academic_year_id == academic_year_id,
    ).with_for_update().all()
    db.query(models.TeacherSectionAssignment).join(
        models.PlanningSection,
        models.PlanningSection.id == models.TeacherSectionAssignment.planning_section_id,
    ).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).with_for_update().all()
    db.query(models.SubjectDistributionRule).filter(
        models.SubjectDistributionRule.branch_id == branch_id,
        models.SubjectDistributionRule.academic_year_id == academic_year_id,
    ).with_for_update().all()
    db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
    ).with_for_update().all()


def _active_demand_row(db, *, branch_id, academic_year_id, section_id, subject_code):
    return db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.branch_id == branch_id,
        models.PlanningSubjectDemand.academic_year_id == academic_year_id,
        models.PlanningSubjectDemand.planning_section_id == section_id,
        models.PlanningSubjectDemand.subject_code == subject_code,
        models.PlanningSubjectDemand.is_active.is_(True),
    ).with_for_update().first()


def _set_demand(
    db, *, branch_id, academic_year_id, section_id, subject_code,
    weekly_periods, actor_user_id, retire_zero,
):
    row = _active_demand_row(
        db, branch_id=branch_id, academic_year_id=academic_year_id,
        section_id=section_id, subject_code=subject_code,
    )
    now = datetime.utcnow()
    if row is None:
        row = models.PlanningSubjectDemand(
            branch_id=branch_id, academic_year_id=academic_year_id,
            planning_section_id=section_id, subject_code=subject_code,
            weekly_periods=int(weekly_periods), is_active=not (retire_zero and int(weekly_periods) == 0),
            retired_at=now if retire_zero and int(weekly_periods) == 0 else None,
            created_by_user_id=actor_user_id, updated_by_user_id=actor_user_id,
        )
        db.add(row)
    else:
        row.weekly_periods = int(weekly_periods)
        row.is_active = not (retire_zero and int(weekly_periods) == 0)
        row.retired_at = now if not row.is_active else None
        row.updated_by_user_id = actor_user_id
        row.updated_at = now
    return row


def _existing_applied_audit(db, *, school_group_id, branch_id, academic_year_id, fingerprint):
    return db.query(models.CurriculumAdjustmentAudit).filter(
        models.CurriculumAdjustmentAudit.school_group_id == school_group_id,
        models.CurriculumAdjustmentAudit.branch_id == branch_id,
        models.CurriculumAdjustmentAudit.academic_year_id == academic_year_id,
        models.CurriculumAdjustmentAudit.preview_fingerprint == fingerprint,
        models.CurriculumAdjustmentAudit.status == "applied",
    ).first()


def _result_from_audit(audit, *, duplicate: bool) -> dict:
    sections = json.loads(audit.per_section_json or "[]")
    return {
        "adjustment_id": audit.public_id,
        "affected_sections": [int(item["section_id"]) for item in sections],
        "draft_stale": bool(audit.draft_marked_stale),
        "warnings": json.loads(audit.warnings_json or "[]"),
        "regeneration_required": bool(audit.regeneration_required),
        "duplicate": duplicate,
    }


def apply_curriculum_adjustment(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    actor_user_id: str,
    request: CurriculumAdjustmentApplyRequest,
) -> dict:
    fingerprint = str(request.preview_fingerprint or "").strip().lower()
    if len(fingerprint) != 64:
        raise CurriculumAdjustmentApplyError("preview_fingerprint_required", "A valid reviewed preview fingerprint is required.")

    # Authorization reads may have opened a read transaction. End it before this
    # service takes ownership of the single apply transaction.
    db.rollback()
    with db.begin():
        existing = _existing_applied_audit(
            db, school_group_id=school_group_id, branch_id=branch_id,
            academic_year_id=academic_year_id, fingerprint=fingerprint,
        )
        if existing is not None:
            return _result_from_audit(existing, duplicate=True)

        _lock_scope(
            db, school_group_id=school_group_id, branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        active_run = db.query(models.TimetableGenerationRun).filter(
            models.TimetableGenerationRun.school_group_id == school_group_id,
            models.TimetableGenerationRun.branch_id == branch_id,
            models.TimetableGenerationRun.academic_year_id == academic_year_id,
            models.TimetableGenerationRun.status.in_(ACTIVE_STATUSES),
        ).with_for_update().first()
        if active_run is not None:
            raise CurriculumAdjustmentApplyError(
                "active_generation_conflict",
                "Timetable generation is active for this branch/year. Wait for it to finish before applying curriculum changes.",
            )

        preview = build_curriculum_adjustment_preview(
            db, school_group_id=school_group_id, branch_id=branch_id,
            academic_year_id=academic_year_id, request=request.preview_request,
        )
        if preview["preview_fingerprint"] != fingerprint:
            raise CurriculumAdjustmentApplyError("stale_preview", "Planning or timetable authority changed after preview. Review the adjustment again.")
        if preview["blockers"] or not preview["sections"]:
            raise CurriculumAdjustmentApplyError("preview_blocked", "The reviewed adjustment has unresolved blockers.")

        affected_ids = {int(item["section"]["id"]) for item in preview["sections"]}
        decisions = {int(key): (int(value) if value is not None else None) for key, value in request.teacher_decisions.items()}
        if set(decisions) != affected_ids:
            raise CurriculumAdjustmentApplyError(
                "teacher_decisions_incomplete",
                "Confirm one target-teacher decision, including unassigned when intended, for every affected section.",
            )

        teachers = db.query(models.Teacher).filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        ).with_for_update().all()
        teachers_by_id = {int(row.id): row for row in teachers}
        target_code = str(request.preview_request.target_subject_code).strip().upper()
        qualified_ids = {
            int(row.teacher_id) for row in db.query(models.TeacherSubjectAllocation).filter(
                models.TeacherSubjectAllocation.teacher_id.in_(list(teachers_by_id) or [0]),
                models.TeacherSubjectAllocation.subject_code == target_code,
            ).all()
        }
        for section_id, teacher_id in decisions.items():
            if teacher_id is None:
                continue
            if teacher_id not in teachers_by_id:
                raise CurriculumAdjustmentApplyError("teacher_scope_mismatch", "A selected teacher is outside the branch/year scope.")
            if teacher_id not in qualified_ids:
                raise CurriculumAdjustmentApplyError("teacher_not_qualified", "A selected teacher is not allocated/qualified for the target subject.")

        projected_loads: dict[int, int] = {}
        for teacher in teachers:
            projected_loads[int(teacher.id)] = 0
        all_sections = db.query(models.PlanningSection).filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
            models.PlanningSection.class_status.in_(("Current", "New")),
        ).all()
        from curriculum_adjustment_preview_service import _current_teacher_loads
        subjects = db.query(models.Subject).filter(
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).all()
        subjects_by_code = {str(row.subject_code or "").strip().upper(): row for row in subjects}
        _, _, current_loads = _current_teacher_loads(
            db, branch_id=branch_id, academic_year_id=academic_year_id,
            sections=all_sections, subjects_by_code=subjects_by_code,
        )
        projected_loads.update({int(key): int(value) for key, value in current_loads.items()})
        for item in preview["sections"]:
            source_teacher = (item["current_source_teacher"]["teacher"] or {}).get("id")
            target_teacher = (item["current_target_teacher"]["teacher"] or {}).get("id")
            source_before = int(item["source"]["current_weekly_periods"])
            source_after = int(item["source"]["after_weekly_periods"])
            target_before = int(item["target"]["current_weekly_periods"])
            target_after = int(item["target"]["after_weekly_periods"])
            if source_teacher is not None:
                projected_loads[int(source_teacher)] -= source_before - source_after
            if target_teacher is not None:
                projected_loads[int(target_teacher)] -= target_before
            chosen = decisions[int(item["section"]["id"])]
            if chosen is not None:
                projected_loads[chosen] += target_after
        for teacher_id in {value for value in decisions.values() if value is not None}:
            capacity = int(get_teacher_international_capacity_hours(teachers_by_id[teacher_id]))
            if projected_loads.get(teacher_id, 0) > capacity:
                raise CurriculumAdjustmentApplyError("teacher_over_capacity", "A selected teacher would exceed final capacity.")

        draft_id = preview["timetable_impact"].get("draft_version_id")
        draft = db.query(models.TimetableVersion).filter(
            models.TimetableVersion.id == draft_id,
            models.TimetableVersion.school_group_id == school_group_id,
            models.TimetableVersion.branch_id == branch_id,
            models.TimetableVersion.academic_year_id == academic_year_id,
            models.TimetableVersion.published_at.is_(None),
        ).with_for_update().first() if draft_id else None
        if draft_id and draft is None:
            raise CurriculumAdjustmentApplyError("stale_preview", "The reviewed Draft Timetable changed after preview.")

        source_code = str(request.preview_request.source_subject_code).strip().upper()
        if draft is not None:
            locked_entries = db.query(models.TimetableEntry).filter(
                models.TimetableEntry.timetable_version_id == draft.id,
                models.TimetableEntry.planning_section_id.in_(sorted(affected_ids)),
                models.TimetableEntry.is_locked.is_(True),
                models.TimetableEntry.subject_code.in_((source_code, target_code)),
            ).with_for_update().all()
            locked_by_key = {}
            for entry in locked_entries:
                key = (int(entry.planning_section_id), str(entry.subject_code or "").strip().upper())
                locked_by_key[key] = locked_by_key.get(key, 0) + 1
            for item in preview["sections"]:
                section_id = int(item["section"]["id"])
                if locked_by_key.get((section_id, source_code), 0) > int(item["source"]["after_weekly_periods"]):
                    raise CurriculumAdjustmentApplyError("invalid_locked_placement", "A Draft lock references source demand that would be retired or reduced below the locked count.")
                old_target_teacher = (item["current_target_teacher"]["teacher"] or {}).get("id")
                if locked_by_key.get((section_id, target_code), 0) and decisions[section_id] != old_target_teacher:
                    raise CurriculumAdjustmentApplyError("invalid_locked_placement", "A locked target lesson conflicts with the confirmed teacher decision.")

        per_section_audit = []
        warnings = list(preview["warnings"])
        now = datetime.utcnow()
        for item in preview["sections"]:
            section_id = int(item["section"]["id"])
            source_after = int(item["source"]["after_weekly_periods"])
            target_after = int(item["target"]["after_weekly_periods"])
            _set_demand(
                db, branch_id=branch_id, academic_year_id=academic_year_id,
                section_id=section_id, subject_code=source_code,
                weekly_periods=source_after, actor_user_id=actor_user_id, retire_zero=True,
            )
            _set_demand(
                db, branch_id=branch_id, academic_year_id=academic_year_id,
                section_id=section_id, subject_code=target_code,
                weekly_periods=target_after, actor_user_id=actor_user_id, retire_zero=False,
            )
            if source_after == 0:
                db.query(models.TeacherSectionAssignment).filter(
                    models.TeacherSectionAssignment.planning_section_id == section_id,
                    models.TeacherSectionAssignment.subject_code == source_code,
                ).delete(synchronize_session=False)
                section_rule = db.query(models.SubjectDistributionRule).filter(
                    models.SubjectDistributionRule.branch_id == branch_id,
                    models.SubjectDistributionRule.academic_year_id == academic_year_id,
                    models.SubjectDistributionRule.scope_level == "section",
                    models.SubjectDistributionRule.section_id == section_id,
                    models.SubjectDistributionRule.subject_code == source_code,
                    models.SubjectDistributionRule.is_active.is_(True),
                ).first()
                if section_rule is not None:
                    section_rule.is_active = False
                    section_rule.updated_by_user_id = actor_user_id
                    section_rule.updated_at = now
            target_assignment = db.query(models.TeacherSectionAssignment).filter(
                models.TeacherSectionAssignment.planning_section_id == section_id,
                models.TeacherSectionAssignment.subject_code == target_code,
            ).first()
            chosen_teacher = decisions[section_id]
            if chosen_teacher is None:
                if target_assignment is not None:
                    db.delete(target_assignment)
            elif target_assignment is None:
                db.add(models.TeacherSectionAssignment(
                    teacher_id=chosen_teacher, planning_section_id=section_id,
                    subject_code=target_code,
                ))
            else:
                target_assignment.teacher_id = chosen_teacher
            per_section_audit.append({
                "section_id": section_id,
                "source_before": int(item["source"]["current_weekly_periods"]),
                "source_after": source_after,
                "target_before": int(item["target"]["current_weekly_periods"]),
                "target_after": target_after,
                "target_teacher_id": chosen_teacher,
            })

        draft_stale = draft is not None
        if draft is not None:
            draft.is_stale = True
            draft.stale_reason_json = _json([{
                "code": "curriculum_adjustment_applied",
                "message": "Planning demand changed. Regenerate the Draft Timetable before approval or publication.",
            }])
            clear_draft_approval(draft)
            draft.edit_revision = int(draft.edit_revision or 0) + 1
            draft.updated_at = now

        audit = models.CurriculumAdjustmentAudit(
            school_group_id=school_group_id, branch_id=branch_id,
            academic_year_id=academic_year_id, actor_user_id=actor_user_id,
            scope_type=str(request.preview_request.scope_type).strip().lower(),
            source_subject_code=source_code, target_subject_code=target_code,
            preview_fingerprint=fingerprint,
            request_json=_json(preview["request"]),
            per_section_json=_json(per_section_audit),
            warnings_json=_json(warnings), status="applied",
            draft_version_id=int(draft.id) if draft else None,
            draft_marked_stale=draft_stale,
            regeneration_required=draft_stale,
        )
        db.add(audit)
        db.flush()
        result = _result_from_audit(audit, duplicate=False)
    return result
