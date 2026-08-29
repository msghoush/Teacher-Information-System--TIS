from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

import models
from homeroom_defaults import is_default_homeroom_subject
from planning_subject_demand_service import resolve_scope_subject_demands
from subject_distribution_rules import resolve_subject_distribution_rule
from subject_distribution_validator import validate_subject_distribution_rule
from teacher_capacity import get_teacher_international_capacity_hours
from timetable_logic import normalize_timetable_quality_rules
from timetable_version_service import MUTABLE_LIFECYCLE_STATUSES, resolve_scope_school_group_id


class CurriculumAdjustmentPreviewError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CurriculumAdjustmentPreviewRequest:
    scope_type: str
    source_subject_code: str
    target_subject_code: str
    grade_level: str | None = None
    section_ids: tuple[int, ...] = ()
    source_after_weekly_periods: int = 0


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _grade(value) -> str:
    text = str(value or "").strip().upper()
    return "KG" if text in {"0", "K", "KG", "KINDERGARTEN"} else text


def _teacher_payload(teacher) -> dict | None:
    if teacher is None:
        return None
    name = " ".join(
        value for value in (
            str(teacher.first_name or "").strip(),
            str(teacher.middle_name or "").strip(),
            str(teacher.last_name or "").strip(),
        ) if value
    )
    return {"id": int(teacher.id), "teacher_id": str(teacher.teacher_id or ""), "name": name}


def _resolve_teacher(section, subject, explicit_teacher_id):
    if explicit_teacher_id is not None:
        return int(explicit_teacher_id), "planning"
    if section.homeroom_teacher_id is not None and is_default_homeroom_subject(
        _grade(section.grade_level),
        subject_name=str(subject.subject_name or ""),
        subject_code=str(subject.subject_code or ""),
    ):
        return int(section.homeroom_teacher_id), "homeroom_default"
    return None, "unassigned"


def _current_teacher_loads(db, *, branch_id: int, academic_year_id: int, sections, subjects_by_code):
    section_ids = [int(section.id) for section in sections]
    demands = resolve_scope_subject_demands(
        db, branch_id=branch_id, academic_year_id=academic_year_id,
        planning_section_ids=section_ids,
    )
    assignments = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.planning_section_id.in_(section_ids)
    ).all() if section_ids else []
    explicit = {
        (int(row.planning_section_id), str(row.subject_code or "").strip().upper()): int(row.teacher_id)
        for row in assignments
    }
    loads: dict[int, int] = {}
    resolved_teachers = {}
    for section in sections:
        for demand in demands.get(int(section.id), []):
            subject = subjects_by_code.get(demand.subject_code)
            if subject is None:
                continue
            teacher_id, source = _resolve_teacher(
                section, subject, explicit.get((int(section.id), demand.subject_code))
            )
            resolved_teachers[(int(section.id), demand.subject_code)] = (teacher_id, source)
            if teacher_id is not None and demand.is_active and int(demand.weekly_periods) > 0:
                loads[teacher_id] = loads.get(teacher_id, 0) + int(demand.weekly_periods)
    return demands, resolved_teachers, loads


def build_curriculum_adjustment_preview(
    db: Session,
    *,
    school_group_id: int,
    branch_id: int,
    academic_year_id: int,
    request: CurriculumAdjustmentPreviewRequest,
) -> dict:
    resolved_group = resolve_scope_school_group_id(
        db, branch_id=branch_id, academic_year_id=academic_year_id
    )
    if int(resolved_group) != int(school_group_id):
        raise CurriculumAdjustmentPreviewError("scope_mismatch", "The selected branch/year is outside the organization scope.")

    scope_type = str(request.scope_type or "").strip().lower()
    if scope_type not in {"grade", "selected_sections", "all_active_uses"}:
        raise CurriculumAdjustmentPreviewError("invalid_scope_type", "Select grade, selected sections, or all active uses.")
    source_code = str(request.source_subject_code or "").strip().upper()
    target_code = str(request.target_subject_code or "").strip().upper()
    if not source_code or not target_code or source_code == target_code:
        raise CurriculumAdjustmentPreviewError("invalid_subjects", "Select two different source and target subjects.")
    source_after = int(request.source_after_weekly_periods)
    if source_after < 0:
        raise CurriculumAdjustmentPreviewError("invalid_source_periods", "Source periods cannot be negative.")

    all_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
        models.PlanningSection.class_status.in_(("Current", "New")),
    ).order_by(models.PlanningSection.id.asc()).all()
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).all()
    subjects_by_code = {
        str(subject.subject_code or "").strip().upper(): subject for subject in subjects
        if str(subject.subject_code or "").strip()
    }
    if source_code not in subjects_by_code or target_code not in subjects_by_code:
        raise CurriculumAdjustmentPreviewError("subject_not_found", "Both subjects must exist in the selected branch/year.")

    all_demands, resolved_teachers, current_loads = _current_teacher_loads(
        db, branch_id=branch_id, academic_year_id=academic_year_id,
        sections=all_sections, subjects_by_code=subjects_by_code,
    )
    if scope_type == "grade":
        grade = _grade(request.grade_level)
        if not grade:
            raise CurriculumAdjustmentPreviewError("grade_required", "Select a grade for grade scope.")
        selected = [section for section in all_sections if _grade(section.grade_level) == grade]
    elif scope_type == "selected_sections":
        requested_ids = {int(value) for value in request.section_ids}
        if not requested_ids:
            raise CurriculumAdjustmentPreviewError("sections_required", "Select at least one Current/New section.")
        selected = [section for section in all_sections if int(section.id) in requested_ids]
        if {int(section.id) for section in selected} != requested_ids:
            raise CurriculumAdjustmentPreviewError("section_scope_mismatch", "One or more selected sections are outside the branch/year or are not Current/New.")
    else:
        selected = []
        for section in all_sections:
            source = next((row for row in all_demands.get(int(section.id), []) if row.subject_code == source_code), None)
            if source is not None and source.is_active and int(source.weekly_periods) > 0:
                selected.append(section)

    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).all()
    teachers_by_id = {int(teacher.id): teacher for teacher in teachers}
    qualified_target_ids = {
        int(row.teacher_id) for row in db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id.in_(list(teachers_by_id) or [0]),
            models.TeacherSubjectAllocation.subject_code == target_code,
        ).all()
    }

    setting = db.query(models.TimetableSetting).filter(
        models.TimetableSetting.branch_id == branch_id,
        models.TimetableSetting.academic_year_id == academic_year_id,
    ).first()
    quality = normalize_timetable_quality_rules(setting.quality_rules_json if setting else None)
    grouped = quality.get("swimming_groups") or []
    available_days = len([item for item in str(setting.working_days_csv or "").split(",") if item.strip()]) if setting else None

    draft = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.school_group_id == school_group_id,
        models.TimetableVersion.branch_id == branch_id,
        models.TimetableVersion.academic_year_id == academic_year_id,
        models.TimetableVersion.lifecycle_status.in_(MUTABLE_LIFECYCLE_STATUSES),
        models.TimetableVersion.published_at.is_(None),
    ).order_by(models.TimetableVersion.version_number.desc(), models.TimetableVersion.id.desc()).first()

    section_results = []
    all_blockers = []
    all_warnings = []
    for section in selected:
        section_id = int(section.id)
        demand_by_code = {row.subject_code: row for row in all_demands.get(section_id, [])}
        source = demand_by_code.get(source_code)
        target = demand_by_code.get(target_code)
        source_before = int(source.weekly_periods) if source and source.is_active else 0
        target_before = int(target.weekly_periods) if target and target.is_active else 0
        blockers = []
        warnings = []
        if source is None or not source.is_active or source_before <= 0:
            blockers.append({"code": "source_demand_inactive", "message": "Source subject has no active demand in this section."})
        if source_after > source_before:
            blockers.append({"code": "source_after_exceeds_current", "message": "Source periods after adjustment exceed current demand."})
        source_change_valid = not blockers
        released = max(source_before - source_after, 0) if source_change_valid else 0
        target_after = target_before + released

        source_teacher_id, source_assignment = resolved_teachers.get((section_id, source_code), (None, "unassigned"))
        target_teacher_id, target_assignment = resolved_teachers.get((section_id, target_code), (None, "unassigned"))
        candidate_ids = []
        for teacher_id in (target_teacher_id, source_teacher_id):
            if teacher_id is not None and teacher_id not in candidate_ids:
                candidate_ids.append(teacher_id)
        candidate_ids.extend(sorted(qualified_target_ids - set(candidate_ids)))
        suggestions = []
        for teacher_id in candidate_ids:
            teacher = teachers_by_id.get(teacher_id)
            if teacher is None:
                continue
            current = int(current_loads.get(teacher_id, 0))
            base_after_source = current - (released if teacher_id == source_teacher_id else 0)
            projected = base_after_source + released
            capacity = int(get_teacher_international_capacity_hours(teacher))
            suggestions.append({
                "teacher": _teacher_payload(teacher),
                "reason": "current_target_teacher" if teacher_id == target_teacher_id else ("current_source_teacher" if teacher_id == source_teacher_id else "target_subject_allocation"),
                "current_load": current,
                "projected_load": projected,
                "capacity": capacity,
                "remaining_capacity": capacity - projected,
                "over_capacity": projected > capacity,
            })
        if target_teacher_id is None:
            warnings.append({"code": "target_teacher_unassigned", "message": "The target subject has no current teacher; allocation must be confirmed later."})
        if suggestions and all(item["over_capacity"] for item in suggestions):
            blockers.append({"code": "teacher_capacity_exceeded", "message": "Every suggested teacher would exceed capacity."})
        elif any(item["over_capacity"] for item in suggestions):
            warnings.append({"code": "teacher_capacity_warning", "message": "Some teacher options would exceed capacity."})

        rule_impacts = []
        for code, before, after in ((source_code, source_before, source_after), (target_code, target_before, target_after)):
            rule = resolve_subject_distribution_rule(
                db, branch_id=branch_id, academic_year_id=academic_year_id,
                grade_level=_grade(section.grade_level), subject_code=code, section_id=section_id,
            )
            errors = validate_subject_distribution_rule(
                rule, planning_weekly_periods=after, available_teaching_days=available_days
            ) if rule else []
            rule_impacts.append({"subject_code": code, "before_weekly_periods": before, "after_weekly_periods": after, "rule": rule, "validation_errors": errors})
            if errors:
                blockers.append({"code": "subject_distribution_rule_invalid", "subject_code": code, "message": "The current Subject Scheduling Rule does not fit the proposed demand."})

        grouped_warnings = []
        for group in grouped:
            if str(group.get("subject_code") or "").upper() in {source_code, target_code} and section_id in set(group.get("section_ids") or []):
                grouped_warnings.append({"code": "grouped_activity_review_required", "group_key": group.get("key"), "message": "This section/subject participates in grouped legacy timetable configuration."})
        warnings.extend(grouped_warnings)
        all_blockers.extend({**item, "section_id": section_id} for item in blockers)
        all_warnings.extend({**item, "section_id": section_id} for item in warnings)
        section_results.append({
            "section": {"id": section_id, "grade_level": _grade(section.grade_level), "section_name": str(section.section_name or ""), "class_status": str(section.class_status or "")},
            "source": {"subject_code": source_code, "current_weekly_periods": source_before, "after_weekly_periods": source_after if source_change_valid else source_before, "authority": source.authority if source else None, "is_active": bool(source and source.is_active)},
            "target": {"subject_code": target_code, "current_weekly_periods": target_before, "after_weekly_periods": target_after, "authority": target.authority if target else None, "is_active": bool(target and target.is_active)},
            "released_weekly_periods": released,
            "current_source_teacher": {"teacher": _teacher_payload(teachers_by_id.get(source_teacher_id)), "assignment_source": source_assignment},
            "current_target_teacher": {"teacher": _teacher_payload(teachers_by_id.get(target_teacher_id)), "assignment_source": target_assignment},
            "suggested_teacher_options": suggestions,
            "subject_scheduling_rule_impact": rule_impacts,
            "grouped_legacy_warnings": grouped_warnings,
            "blockers": blockers,
            "warnings": warnings,
        })

    authority = {
        "scope": {"school_group_id": int(school_group_id), "branch_id": int(branch_id), "academic_year_id": int(academic_year_id)},
        "request": {"scope_type": scope_type, "grade_level": _grade(request.grade_level), "section_ids": sorted(int(value) for value in request.section_ids), "source_subject_code": source_code, "target_subject_code": target_code, "source_after_weekly_periods": source_after},
        "sections": section_results,
        "draft": {"id": int(draft.id), "edit_revision": int(draft.edit_revision or 0), "authority_fingerprint": str(draft.authority_fingerprint or "")} if draft else None,
    }
    preview_fingerprint = _fingerprint(authority)
    return {
        "preview_only": True,
        "scope": authority["scope"],
        "request": authority["request"],
        "affected_section_count": len(section_results),
        "sections": section_results,
        "blockers": all_blockers,
        "warnings": all_warnings,
        "can_apply_later": bool(section_results) and not all_blockers,
        "timetable_impact": {
            "draft_exists": draft is not None,
            "draft_version_id": int(draft.id) if draft else None,
            "draft_edit_revision": int(draft.edit_revision or 0) if draft else None,
            "would_become_stale": draft is not None and bool(section_results),
            "regeneration_required_after_apply": draft is not None and bool(section_results),
            "published_history_untouched": True,
        },
        "preview_fingerprint": preview_fingerprint,
    }


def is_curriculum_adjustment_preview_current(db: Session, *, expected_fingerprint: str, **kwargs) -> bool:
    current = build_curriculum_adjustment_preview(db, **kwargs)
    return str(expected_fingerprint or "") == current["preview_fingerprint"]
