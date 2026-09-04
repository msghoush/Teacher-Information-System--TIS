from datetime import datetime

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
import models
from dependencies import get_db
from auth import get_current_user
from homeroom_defaults import (
    get_homeroom_bundle_subject_labels,
    LOWER_PRIMARY_HOMEROOM_SUBJECT_LABELS,
    is_default_homeroom_subject,
    is_lower_primary_homeroom_grade,
)
from teacher_qualifications import (
    get_qualification_lookup,
    get_subject_qualification_alignment,
    infer_qualification_keys_from_legacy_text,
)
from teacher_capacity import get_teacher_international_capacity_hours
from planning_subject_demand_service import (
    resolve_scope_subject_demands,
    resolve_section_subject_demands,
)
from curriculum_adjustment_preview_service import (
    CurriculumAdjustmentPreviewError,
    CurriculumAdjustmentPreviewRequest,
    build_curriculum_adjustment_preview,
)
from curriculum_adjustment_apply_service import (
    CurriculumAdjustmentApplyError,
    CurriculumAdjustmentApplyRequest,
    apply_curriculum_adjustment,
)
from ui_shell import build_shell_context
from year_copy import get_copy_year_choices, get_academic_year
from subject_colors import build_subject_theme, resolve_subject_color
from redirect_utils import safe_redirect_path
from academic_grade import GRADE_LEVELS, normalize_grade_level

router = APIRouter(prefix="/planning", tags=["Planning"])
templates = Jinja2Templates(directory="templates")

GRADE_OPTIONS = list(GRADE_LEVELS)
SECTION_OPTIONS = [chr(code) for code in range(ord("A"), ord("L") + 1)]
STATUS_OPTIONS = ["Current", "New"]


def _get_scope_ids(current_user):
    branch_id = getattr(current_user, "scope_branch_id", current_user.branch_id)
    academic_year_id = getattr(
        current_user,
        "scope_academic_year_id",
        current_user.academic_year_id,
    )
    return branch_id, academic_year_id


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _normalize_grade_level(value) -> str:
    return normalize_grade_level(value)


def _normalize_section_name(value) -> str:
    cleaned = str(value).strip().upper()
    if cleaned.startswith("SECTION "):
        cleaned = cleaned.replace("SECTION ", "", 1).strip()
    return cleaned


def _normalize_class_status(value) -> str:
    cleaned = str(value).strip().lower()
    if cleaned == "current":
        return "Current"
    if cleaned == "new":
        return "New"
    return ""


@router.post("/curriculum-adjustments/preview")
async def curriculum_adjustment_preview(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    current_user, denied_response = authorization.require_any_permission(
        request, db, "planning.edit_section", "curriculum.adjust",
        current_user=current_user, page_key="planning"
    )
    if denied_response:
        return denied_response
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "invalid_json", "message": "Submit a valid JSON preview request."}, status_code=400)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    school_group_id = getattr(current_user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, current_user)
    try:
        preview_request = CurriculumAdjustmentPreviewRequest(
            adjustment_type=payload.get("adjustment_type", "transfer"),
            scope_type=payload.get("scope_type", ""),
            source_subject_code=payload.get("source_subject_code", ""),
            target_subject_code=payload.get("target_subject_code", ""),
            grade_level=payload.get("grade_level"),
            section_ids=tuple(payload.get("section_ids") or ()),
            requested_transfer_periods=int(payload.get("requested_transfer_periods", 0)),
        )
        result = build_curriculum_adjustment_preview(
            db,
            school_group_id=int(school_group_id or 0),
            branch_id=int(branch_id or 0),
            academic_year_id=int(academic_year_id or 0),
            request=preview_request,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CurriculumAdjustmentPreviewError):
            return JSONResponse({"error": exc.code, "message": str(exc)}, status_code=400)
        return JSONResponse({"error": "invalid_request", "message": "Preview values are invalid."}, status_code=400)
    return JSONResponse(result)


@router.get("/curriculum-adjustments")
def curriculum_adjustment_page(
    request: Request,
    action: str = "",
    source_subject_code: str = "",
    grade_level: str = "",
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")
    current_user, denied_response = authorization.require_permission(
        request, db, "curriculum.adjust", current_user=current_user, page_key="planning"
    )
    if denied_response:
        return denied_response
    branch_id, academic_year_id = _get_scope_ids(current_user)
    sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
        models.PlanningSection.class_status.in_(("Current", "New")),
    ).order_by(models.PlanningSection.grade_level.asc(), models.PlanningSection.section_name.asc()).all()
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.grade.asc(), models.Subject.subject_name.asc()).all()
    section_items = [
        {
            "id": int(section.id),
            "grade_level": _normalize_grade_level(section.grade_level),
            "section_name": str(section.section_name or "").strip(),
            "class_status": str(section.class_status or ""),
            "label": f"Grade {_normalize_grade_level(section.grade_level)} · Section {str(section.section_name or '').strip()} · {section.class_status}",
        }
        for section in sections
    ]
    subject_items = [
        {
            "code": str(subject.subject_code or "").strip().upper(),
            "name": str(subject.subject_name or "").strip(),
            "grade_level": _normalize_grade_level(subject.grade),
            "weekly_periods": int(subject.weekly_hours or 0),
            "label": f"{str(subject.subject_name or '').strip()} · Grade {_normalize_grade_level(subject.grade)}",
        }
        for subject in subjects if str(subject.subject_code or "").strip()
    ]
    grades = sorted(
        {item["grade_level"] for item in section_items},
        key=_grade_sort_value,
    )
    requested_source_code = str(source_subject_code or "").strip().upper()
    requested_grade = _normalize_grade_level(grade_level)
    valid_prefill = next((
        subject for subject in subject_items
        if subject["code"] == requested_source_code and subject["grade_level"] == requested_grade
    ), None)
    return templates.TemplateResponse(
        request,
        "curriculum_adjustment.html",
        {
            "request": request,
            "user": current_user,
            "grades": grades,
            "sections": section_items,
            "subjects": subject_items,
            "prefill_adjustment_type": "reduce_only" if action == "reduce" and valid_prefill else "transfer",
            "prefill_source_subject_code": valid_prefill["code"] if valid_prefill else "",
            "prefill_grade_level": requested_grade if valid_prefill else "",
            **build_shell_context(request, db, current_user, page_key="planning"),
        },
    )


@router.post("/curriculum-adjustments/apply")
async def curriculum_adjustment_apply(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return JSONResponse({"error": "authentication_required"}, status_code=401)
    current_user, denied_response = authorization.require_permission(
        request, db, "curriculum.adjust", current_user=current_user, page_key="planning"
    )
    if denied_response:
        return denied_response
    try:
        payload = await request.json()
        preview_request = CurriculumAdjustmentPreviewRequest(
            adjustment_type=payload.get("adjustment_type", "transfer"),
            scope_type=payload.get("scope_type", ""),
            source_subject_code=payload.get("source_subject_code", ""),
            target_subject_code=payload.get("target_subject_code", ""),
            grade_level=payload.get("grade_level"),
            section_ids=tuple(payload.get("section_ids") or ()),
            requested_transfer_periods=int(payload.get("requested_transfer_periods", 0)),
        )
        raw_decisions = payload.get("teacher_decisions")
        if not isinstance(raw_decisions, dict):
            raise ValueError("teacher_decisions")
        apply_request = CurriculumAdjustmentApplyRequest(
            preview_request=preview_request,
            preview_fingerprint=str(payload.get("preview_fingerprint") or ""),
            teacher_decisions={int(key): (int(value) if value is not None else None) for key, value in raw_decisions.items()},
        )
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid_request", "message": "Apply values are invalid."}, status_code=400)
    branch_id, academic_year_id = _get_scope_ids(current_user)
    school_group_id = getattr(current_user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, current_user)
    try:
        result = apply_curriculum_adjustment(
            db, school_group_id=int(school_group_id or 0), branch_id=int(branch_id or 0),
            academic_year_id=int(academic_year_id or 0), actor_user_id=str(current_user.user_id),
            request=apply_request,
        )
    except (CurriculumAdjustmentApplyError, CurriculumAdjustmentPreviewError) as exc:
        return JSONResponse({"error": exc.code, "message": str(exc)}, status_code=409 if exc.code in {"stale_preview", "active_generation_conflict"} else 400)
    return JSONResponse(result)


def _grade_sort_value(grade_level: str) -> int:
    if grade_level == "KG":
        return 0
    parsed_value = _parse_int(grade_level)
    if parsed_value is None:
        return 99
    return parsed_value


def _get_subject_alignment_map(db: Session, branch_id: int, academic_year_id: int):
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(
        models.Subject.grade.asc(),
        models.Subject.subject_code.asc(),
    ).all()

    alignment_map = {grade: [] for grade in GRADE_OPTIONS}
    for subject in subjects:
        if not subject.subject_code:
            continue
        if subject.grade is None:
            continue
        grade_label = "KG" if int(subject.grade) == 0 else str(int(subject.grade))
        if grade_label not in alignment_map:
            continue
        subject_color = resolve_subject_color(
            subject.subject_code,
            getattr(subject, "color", ""),
            subject_name=subject.subject_name,
        )
        theme = build_subject_theme(subject_color)
        alignment_map[grade_label].append(
            {
                "subject_code": subject.subject_code,
                "subject_name": subject.subject_name or "Unnamed Subject",
                "weekly_hours": int(subject.weekly_hours or 0),
                "subject_color": subject_color,
                "subject_color_soft": theme["soft"],
                "subject_color_text": theme["text"],
                "subject_color_border": theme["border"],
            }
        )

    return alignment_map


def _get_subject_map_by_code(db: Session, branch_id: int, academic_year_id: int):
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).all()
    return {
        subject.subject_code: subject
        for subject in subjects
        if subject.subject_code
    }


def _build_teacher_display_name(teacher) -> str:
    name_parts = [teacher.first_name]
    if teacher.middle_name:
        name_parts.append(teacher.middle_name)
    name_parts.append(teacher.last_name)
    full_name = " ".join(part for part in name_parts if part).strip()
    return full_name if full_name else f"Teacher #{teacher.id}"


def _is_override_enabled(value) -> bool:
    cleaned = str(value or "").strip().lower()
    return cleaned in {"1", "true", "yes", "on"}


def _build_assignment_alignment_warnings(
    aligned_subjects,
    parsed_assignment_teacher_ids_by_subject,
    scoped_teacher_map,
    qualification_lookup=None,
):
    warnings = []
    for subject in aligned_subjects:
        subject_code = subject.get("subject_code")
        teacher_id = parsed_assignment_teacher_ids_by_subject.get(subject_code)
        if teacher_id is None:
            continue
        teacher = scoped_teacher_map.get(teacher_id)
        if not teacher:
            continue
        qualification_keys = infer_qualification_keys_from_legacy_text(
            getattr(teacher, "degree_major", "") or "",
            qualification_lookup=qualification_lookup,
        )
        alignment = get_subject_qualification_alignment(
            subject_name=subject.get("subject_name") or "",
            fallback_code=subject_code or "",
            qualification_keys=qualification_keys,
            qualification_lookup=qualification_lookup,
        )
        if alignment.get("status") == "match":
            continue
        warnings.append(
            {
                "teacher_name": _build_teacher_display_name(teacher),
                "subject_code": subject_code,
                "subject_name": subject.get("subject_name") or "Unnamed Subject",
                "degree": getattr(teacher, "degree_major", "") or "Not recorded",
                "major": ", ".join(alignment.get("matched_qualification_labels", [])) or "Review fit",
                "reason": (
                    "The assigned subject is not aligned with the teacher's recorded qualifications."
                ),
            }
        )
    return warnings


def _get_teacher_choices(db: Session, branch_id: int, academic_year_id: int):
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(
        models.Teacher.first_name.asc(),
        models.Teacher.last_name.asc(),
    ).all()

    choices = []
    names_by_id = {}
    for teacher in teachers:
        display_name = _build_teacher_display_name(teacher)
        names_by_id[teacher.id] = display_name
        choices.append(
            {
                "id": teacher.id,
                "label": f"{teacher.teacher_id} - {display_name}",
            }
        )

    return choices, names_by_id


def _get_teacher_subject_option_map(
    db: Session,
    branch_id: int,
    academic_year_id: int,
):
    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(
        models.Teacher.first_name.asc(),
        models.Teacher.last_name.asc(),
    ).all()

    teacher_ids = [teacher.id for teacher in teachers if getattr(teacher, "id", None)]
    subject_codes_by_teacher = {
        teacher.id: set()
        for teacher in teachers
        if getattr(teacher, "id", None)
    }

    if teacher_ids:
        allocations = db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)
        ).all()
    else:
        allocations = []

    for allocation in allocations:
        if allocation.subject_code:
            subject_codes_by_teacher.setdefault(allocation.teacher_id, set()).add(
                allocation.subject_code
            )

    for teacher in teachers:
        fallback_code = str(teacher.subject_code or "").strip().upper()
        if fallback_code:
            subject_codes_by_teacher.setdefault(teacher.id, set()).add(fallback_code)

    options_by_subject = {}
    for teacher in teachers:
        display_name = _build_teacher_display_name(teacher)
        option = {
            "id": teacher.id,
            "label": f"{teacher.teacher_id} - {display_name}",
        }
        for subject_code in sorted(subject_codes_by_teacher.get(teacher.id, set())):
            options_by_subject.setdefault(subject_code, []).append(option)

    for subject_code in options_by_subject:
        options_by_subject[subject_code].sort(key=lambda item: item["label"])

    return options_by_subject


def _get_section_assignment_map(
    db: Session,
    planning_sections,
    teacher_names_by_id,
    subject_alignment_map,
    subject_map_by_code,
):
    section_ids = [
        section.id
        for section in planning_sections
        if getattr(section, "id", None)
    ]
    if not section_ids:
        return {}

    assignments = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.planning_section_id.in_(section_ids)
    ).all()

    assignment_map = {}
    for assignment in assignments:
        subject = subject_map_by_code.get(assignment.subject_code)
        assignment_map.setdefault(assignment.planning_section_id, {})[
            assignment.subject_code
        ] = {
            "teacher_id": assignment.teacher_id,
            "teacher_name": teacher_names_by_id.get(assignment.teacher_id, "-"),
            "weekly_hours": int(subject.weekly_hours or 0) if subject else 0,
            "assignment_source": "manual",
        }

    for section in planning_sections:
        grade_label = _normalize_grade_level(section.grade_level)
        if (
            not section.homeroom_teacher_id
            or not is_lower_primary_homeroom_grade(grade_label)
        ):
            continue

        homeroom_teacher_name = teacher_names_by_id.get(
            section.homeroom_teacher_id,
            "-",
        )
        section_assignment_details = assignment_map.setdefault(section.id, {})
        for subject in subject_alignment_map.get(grade_label, []):
            subject_code = str(subject.get("subject_code") or "").strip().upper()
            if not subject_code or subject_code in section_assignment_details:
                continue
            if not is_default_homeroom_subject(
                grade_label,
                subject_name=subject.get("subject_name", ""),
                subject_code=subject_code,
            ):
                continue

            section_assignment_details[subject_code] = {
                "teacher_id": section.homeroom_teacher_id,
                "teacher_name": homeroom_teacher_name,
                "weekly_hours": int(subject.get("weekly_hours", 0) or 0),
                "assignment_source": "homeroom_default",
            }

    return assignment_map


def _build_section_assignment_rows(
    aligned_subjects,
    subject_teacher_options,
    selected_teacher_ids_by_subject,
):
    rows = []
    for subject in aligned_subjects:
        subject_code = subject.get("subject_code")
        if not subject_code:
            continue
        rows.append(
            {
                "subject_code": subject_code,
                "subject_name": subject.get("subject_name") or "Unnamed Subject",
                "weekly_hours": int(subject.get("weekly_hours", 0) or 0),
                "subject_color": subject.get("subject_color") or resolve_subject_color(
                    subject_code,
                    subject_name=subject.get("subject_name", ""),
                ),
                "subject_color_soft": subject.get("subject_color_soft", "#EDF4FF"),
                "subject_color_text": subject.get("subject_color_text", "#1F3759"),
                "teacher_options": subject_teacher_options.get(subject_code, []),
                "selected_teacher_id": str(
                    selected_teacher_ids_by_subject.get(subject_code, "")
                ),
            }
        )
    return rows


def _build_planning_subject_display_entries(
    subject,
    teacher_name: str,
    assignment_source: str,
    grade_label=None,
):
    subject_code = subject.get("subject_code") or ""
    subject_name = subject.get("subject_name") or "Unnamed Subject"
    weekly_hours = int(subject.get("weekly_hours", 0) or 0)
    bundle_subject_labels = get_homeroom_bundle_subject_labels(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=weekly_hours,
        grade_label=grade_label,
    )
    if bundle_subject_labels:
        return [
            {
                **subject,
                "display_preview": bundle_subject,
                "display_label": (
                    f"{subject_code} - {bundle_subject} "
                    f"(included in {subject_name}, {weekly_hours}h homeroom bundle)"
                ),
                "teacher_name": teacher_name,
                "assignment_source": assignment_source,
            }
            for bundle_subject in bundle_subject_labels
        ]

    return [
        {
            **subject,
            "display_preview": subject_code,
            "display_label": f"{subject_code} - {subject_name} ({weekly_hours}h)",
            "teacher_name": teacher_name,
            "assignment_source": assignment_source,
        }
    ]


def _get_current_assignment_selection_map(
    section_assignment_map,
    planning_section_id: int,
):
    return {
        subject_code: details.get("teacher_id")
        for subject_code, details in section_assignment_map.get(planning_section_id, {}).items()
        if details.get("assignment_source") == "manual"
    }


def _get_section_demand_alignment_map(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    planning_sections,
    subject_map_by_code,
):
    resolved = resolve_scope_subject_demands(
        db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        planning_section_ids=[section.id for section in planning_sections],
    )

    explicit_demand_ids = [
        demand.demand_id
        for demands in resolved.values()
        for demand in demands
        if demand.demand_id is not None
    ]
    removable_demand_ids = set()
    if explicit_demand_ids:
        untouched_rows = db.query(models.PlanningSubjectDemand.id).filter(
            models.PlanningSubjectDemand.id.in_(explicit_demand_ids),
            models.PlanningSubjectDemand.updated_by_user_id.is_(None),
        ).all()
        removable_demand_ids = {row_id for (row_id,) in untouched_rows}

    result = {}
    for section in planning_sections:
        items = []
        for demand in resolved.get(section.id, []):
            if not demand.is_active or int(demand.weekly_periods or 0) <= 0:
                continue
            subject = subject_map_by_code.get(demand.subject_code)
            if subject is None:
                continue
            subject_color = resolve_subject_color(
                subject.subject_code, getattr(subject, "color", ""),
                subject_name=subject.subject_name,
            )
            theme = build_subject_theme(subject_color)
            if demand.demand_id is None:
                requirement_status = "fallback"
            elif demand.demand_id in removable_demand_ids:
                requirement_status = "removable"
            else:
                requirement_status = "permanent"
            items.append({
                "subject_code": demand.subject_code,
                "subject_name": subject.subject_name or "Unnamed Subject",
                "weekly_hours": int(demand.weekly_periods),
                "subject_color": subject_color,
                "subject_color_soft": theme["soft"],
                "subject_color_text": theme["text"],
                "subject_color_border": theme["border"],
                "demand_id": demand.demand_id,
                "requirement_status": requirement_status,
                "requirement_target": f"{section.id}:{demand.subject_code}",
            })
        result[section.id] = items
    return result


def _calculate_teacher_section_hours(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    subject_alignment_map,
    subject_map_by_code,
    exclude_planning_section_id: int | None = None,
):
    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).all()
    if exclude_planning_section_id is not None:
        planning_sections = [
            section
            for section in planning_sections
            if getattr(section, "id", None) != exclude_planning_section_id
        ]
    if not planning_sections:
        return {}

    _, teacher_names_by_id = _get_teacher_choices(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_assignment_map = _get_section_assignment_map(
        db=db,
        planning_sections=planning_sections,
        teacher_names_by_id=teacher_names_by_id,
        subject_alignment_map=subject_alignment_map,
        subject_map_by_code=subject_map_by_code,
    )
    resolved_by_section = _get_section_demand_alignment_map(
        db, branch_id, academic_year_id, planning_sections, subject_map_by_code
    )

    teacher_hours = {}
    for section in planning_sections:
        aligned_subjects = resolved_by_section.get(section.id, [])
        for subject in aligned_subjects:
            subject_code = str(subject.get("subject_code") or "").strip().upper()
            if not subject_code:
                continue
            assignment_details = section_assignment_map.get(section.id, {}).get(
                subject_code,
                {},
            )
            teacher_id = assignment_details.get("teacher_id")
            if teacher_id is None:
                continue
            teacher_hours[teacher_id] = (
                teacher_hours.get(teacher_id, 0)
                + int(subject.get("weekly_hours", 0) or 0)
            )

    return teacher_hours


def _build_planning_rows(
    planning_sections,
    subject_alignment_map,
    teacher_names_by_id,
    section_assignment_map,
    section_demand_map=None,
):
    rows = []
    for section in planning_sections:
        aligned_subjects = (section_demand_map or {}).get(
            section.id, subject_alignment_map.get(section.grade_level, [])
        )
        allocated_hours = sum(
            int(item.get("weekly_hours", 0))
            for item in aligned_subjects
        )
        subject_assignments = []
        assigned_hours = 0
        for subject in aligned_subjects:
            assignment_details = section_assignment_map.get(section.id, {}).get(
                subject.get("subject_code"),
                {},
            )
            subject_teacher_name = assignment_details.get("teacher_name") or ""
            if subject_teacher_name:
                assigned_hours += int(subject.get("weekly_hours", 0) or 0)
            subject_assignments.extend(
                _build_planning_subject_display_entries(
                    subject=subject,
                    teacher_name=subject_teacher_name,
                    assignment_source=assignment_details.get(
                        "assignment_source",
                        "",
                    ),
                    grade_label=section.grade_level,
                )
            )
        subject_count = len(subject_assignments)
        assigned_subject_count = sum(
            1 for subject in subject_assignments if subject.get("teacher_name")
        )
        subject_preview = subject_assignments[:2]
        rows.append(
            {
                "record": section,
                "aligned_subjects": aligned_subjects,
                "subject_assignments": subject_assignments,
                "subject_count": subject_count,
                "assigned_subject_count": assigned_subject_count,
                "unassigned_subject_count": max(
                    subject_count - assigned_subject_count,
                    0,
                ),
                "subject_preview": subject_preview,
                "subject_hidden_count": max(subject_count - len(subject_preview), 0),
                "allocated_hours": allocated_hours,
                "assigned_hours": assigned_hours,
                "homeroom_teacher_name": teacher_names_by_id.get(
                    section.homeroom_teacher_id,
                    "-",
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            _grade_sort_value(row["record"].grade_level),
            row["record"].section_name,
            row["record"].id,
        )
    )
    return rows


def _render_planning_page(
    request: Request,
    db: Session,
    current_user,
    error: str = "",
    success: str = "",
    detail_errors=None,
    form_data=None,
    open_section_id: str = "",
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    can_modify = auth.has_permission(db, current_user, "planning.create_section")
    can_edit = auth.has_permission(db, current_user, "planning.edit_section")
    can_delete = auth.has_permission(db, current_user, "planning.delete_section")
    can_copy_year_data = auth.has_permission(db, current_user, "planning.copy_year_data")
    can_adjust_curriculum = auth.has_permission(db, current_user, "curriculum.adjust")
    copy_year_choices = (
        get_copy_year_choices(db, academic_year_id)
        if can_copy_year_data
        else []
    )

    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).all()

    subject_alignment_map = _get_subject_alignment_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    subject_map_by_code = _get_subject_map_by_code(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_demand_map = _get_section_demand_alignment_map(
        db, branch_id, academic_year_id, planning_sections, subject_map_by_code
    )
    teacher_choices, teacher_names_by_id = _get_teacher_choices(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_assignment_map = _get_section_assignment_map(
        db=db,
        planning_sections=planning_sections,
        teacher_names_by_id=teacher_names_by_id,
        subject_alignment_map=subject_alignment_map,
        subject_map_by_code=subject_map_by_code,
    )
    planning_rows = _build_planning_rows(
        planning_sections=planning_sections,
        subject_alignment_map=subject_alignment_map,
        teacher_names_by_id=teacher_names_by_id,
        section_assignment_map=section_assignment_map,
        section_demand_map=section_demand_map,
    )

    current_sections_count = sum(
        1 for row in planning_rows
        if row["record"].class_status == "Current"
    )
    new_sections_count = sum(
        1 for row in planning_rows
        if row["record"].class_status == "New"
    )
    total_allocated_hours = sum(
        row["allocated_hours"] for row in planning_rows
    )

    normalized_form_data = {
        "grade_level": "1",
        "section_name": "A",
        "class_status": "Current",
        "homeroom_teacher_id": "",
    }
    if form_data:
        normalized_form_data.update(form_data)

    return templates.TemplateResponse(
        request,
        "planning.html",
        {
            "request": request,
            "planning_rows": planning_rows,
            "grade_options": GRADE_OPTIONS,
            "section_options": SECTION_OPTIONS,
            "status_options": STATUS_OPTIONS,
            "subject_alignment_map": subject_alignment_map,
            "teacher_choices": teacher_choices,
            "lower_primary_homeroom_subject_labels": list(
                LOWER_PRIMARY_HOMEROOM_SUBJECT_LABELS
            ),
            "current_sections_count": current_sections_count,
            "new_sections_count": new_sections_count,
            "total_allocated_hours": total_allocated_hours,
            "can_modify": can_modify,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "can_copy_year_data": can_copy_year_data,
            "can_adjust_curriculum": can_adjust_curriculum,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": normalized_form_data,
            "copy_year_choices": copy_year_choices,
            "open_section_id": open_section_id,
            "user": current_user,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="planning",
            ),
        },
    )


def _render_edit_planning_page(
    request: Request,
    db: Session,
    current_user,
    planning_section,
    error: str = "",
    form_data=None,
    selected_assignment_teacher_ids=None,
    qualification_warning=None,
    status_code: int = 200,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    subject_alignment_map = _get_subject_alignment_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    teacher_choices, teacher_names_by_id = _get_teacher_choices(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    subject_teacher_options = _get_teacher_subject_option_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    subject_map_by_code = _get_subject_map_by_code(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_demand_map = _get_section_demand_alignment_map(
        db, branch_id, academic_year_id, [planning_section], subject_map_by_code
    )
    section_assignment_map = _get_section_assignment_map(
        db=db,
        planning_sections=[planning_section],
        teacher_names_by_id=teacher_names_by_id,
        subject_alignment_map=subject_alignment_map,
        subject_map_by_code=subject_map_by_code,
    )

    normalized_form_data = {
        "grade_level": planning_section.grade_level,
        "section_name": planning_section.section_name,
        "class_status": planning_section.class_status,
        "homeroom_teacher_id": (
            str(planning_section.homeroom_teacher_id)
            if planning_section.homeroom_teacher_id is not None
            else ""
        ),
    }
    if form_data:
        normalized_form_data.update(form_data)

    selected_grade_level = normalized_form_data.get("grade_level") or planning_section.grade_level
    aligned_subjects = (
        section_demand_map.get(planning_section.id, [])
        if _normalize_grade_level(selected_grade_level)
        == _normalize_grade_level(planning_section.grade_level)
        else subject_alignment_map.get(selected_grade_level, [])
    )
    allocated_hours = sum(
        int(item.get("weekly_hours", 0))
        for item in aligned_subjects
    )

    current_assignment_teacher_ids = _get_current_assignment_selection_map(
        section_assignment_map=section_assignment_map,
        planning_section_id=planning_section.id,
    )
    if selected_assignment_teacher_ids is None:
        selected_assignment_teacher_ids = current_assignment_teacher_ids

    section_assignment_rows = _build_section_assignment_rows(
        aligned_subjects=aligned_subjects,
        subject_teacher_options=subject_teacher_options,
        selected_teacher_ids_by_subject=selected_assignment_teacher_ids,
    )

    return templates.TemplateResponse(
        request,
        "edit_planning.html",
        {
            "request": request,
            "planning_section": planning_section,
            "grade_options": GRADE_OPTIONS,
            "section_options": SECTION_OPTIONS,
            "status_options": STATUS_OPTIONS,
            "teacher_choices": teacher_choices,
            "subject_alignment_map": subject_alignment_map,
            "aligned_subjects": aligned_subjects,
            "allocated_hours": allocated_hours,
            "subject_teacher_options": subject_teacher_options,
            "section_assignment_rows": section_assignment_rows,
            "lower_primary_homeroom_subject_labels": list(
                LOWER_PRIMARY_HOMEROOM_SUBJECT_LABELS
            ),
            "selected_assignment_teacher_ids": {
                subject_code: str(teacher_id)
                for subject_code, teacher_id in (selected_assignment_teacher_ids or {}).items()
                if teacher_id is not None
            },
            "form_data": normalized_form_data,
            "error": error,
            "qualification_warning": qualification_warning,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="planning",
                title="Edit Planning Section",
                eyebrow="Section Planning",
                intro="Update section structure, homeroom ownership, and assign each grade-aligned subject to the right teacher for this section.",
                icon="planning",
            ),
        },
        status_code=status_code,
    )


@router.get("/")
def planning_page(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    return _render_planning_page(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/copy-from-year")
def copy_planning_from_year(
    request: Request,
    source_academic_year_id: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    current_user, denied_response = authorization.require_permission(
        request,
        db,
        "planning.copy_year_data",
        current_user=current_user,
        page_key="planning",
    )
    if denied_response:
        return denied_response

    branch_id, target_academic_year_id = _get_scope_ids(current_user)
    if source_academic_year_id == target_academic_year_id:
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Select a different academic year to copy planning from.",
        )

    source_year = get_academic_year(db, source_academic_year_id)
    target_year = get_academic_year(db, target_academic_year_id)
    if not source_year or not target_year:
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error="The selected academic year was not found.",
        )

    source_sections = (
        db.query(models.PlanningSection)
        .filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == source_academic_year_id,
        )
        .order_by(
            models.PlanningSection.grade_level.asc(),
            models.PlanningSection.section_name.asc(),
            models.PlanningSection.id.asc(),
        )
        .all()
    )
    if not source_sections:
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error=f"No planning sections were found in {source_year.year_name} for the current branch.",
        )

    source_teacher_ids = sorted({
        section.homeroom_teacher_id
        for section in source_sections
        if section.homeroom_teacher_id is not None
    })
    source_section_ids = [
        section.id for section in source_sections if getattr(section, "id", None)
    ]
    source_assignments = []
    if source_section_ids:
        source_assignments = (
            db.query(models.TeacherSectionAssignment)
            .filter(
                models.TeacherSectionAssignment.planning_section_id.in_(source_section_ids)
            )
            .all()
        )
        source_teacher_ids = sorted({
            *source_teacher_ids,
            *[
                assignment.teacher_id
                for assignment in source_assignments
                if assignment.teacher_id is not None
            ],
        })

    source_teachers_by_id = {}
    if source_teacher_ids:
        source_teachers_by_id = {
            teacher.id: teacher
            for teacher in db.query(models.Teacher).filter(
                models.Teacher.id.in_(source_teacher_ids),
                models.Teacher.branch_id == branch_id,
                models.Teacher.academic_year_id == source_academic_year_id,
            ).all()
        }

    target_teachers = (
        db.query(models.Teacher)
        .filter(
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == target_academic_year_id,
        )
        .all()
    )
    target_teachers_by_teacher_id = {
        str(teacher.teacher_id or "").strip(): teacher
        for teacher in target_teachers
        if str(teacher.teacher_id or "").strip()
    }

    target_teacher_ids = [
        teacher.id for teacher in target_teachers if getattr(teacher, "id", None)
    ]
    existing_target_allocation_keys = set()
    if target_teacher_ids:
        for allocation in db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id.in_(target_teacher_ids)
        ).all():
            existing_target_allocation_keys.add(
                (allocation.teacher_id, allocation.subject_code)
            )

    target_subject_codes = {
        subject_code
        for (subject_code,) in (
            db.query(models.Subject.subject_code)
            .filter(
                models.Subject.branch_id == branch_id,
                models.Subject.academic_year_id == target_academic_year_id,
            )
            .all()
        )
        if subject_code
    }

    target_sections = (
        db.query(models.PlanningSection)
        .filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == target_academic_year_id,
        )
        .all()
    )
    target_sections_by_key = {
        (section.grade_level, section.section_name): section
        for section in target_sections
    }
    target_section_ids = [
        section.id for section in target_sections if getattr(section, "id", None)
    ]
    existing_target_assignment_map = {}
    if target_section_ids:
        for assignment in db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id.in_(target_section_ids)
        ).all():
            existing_target_assignment_map[
                (assignment.planning_section_id, assignment.subject_code)
            ] = assignment.teacher_id

    source_assignments_by_section = {}
    for assignment in source_assignments:
        source_assignments_by_section.setdefault(
            assignment.planning_section_id,
            [],
        ).append(assignment)

    created_section_count = 0
    existing_section_count = 0
    copied_homeroom_count = 0
    copied_subject_link_count = 0
    copied_assignment_count = 0
    skipped_missing_teacher_count = 0
    skipped_missing_subject_count = 0
    skipped_assignment_conflict_count = 0

    for source_section in source_sections:
        section_key = (source_section.grade_level, source_section.section_name)
        target_section = target_sections_by_key.get(section_key)
        if target_section is None:
            target_section = models.PlanningSection(
                grade_level=source_section.grade_level,
                section_name=source_section.section_name,
                class_status=source_section.class_status,
                homeroom_teacher_id=None,
                branch_id=branch_id,
                academic_year_id=target_academic_year_id,
            )
            db.add(target_section)
            db.flush()
            target_sections_by_key[section_key] = target_section
            created_section_count += 1
        else:
            existing_section_count += 1

        if (
            source_section.homeroom_teacher_id is not None
            and target_section.homeroom_teacher_id is None
        ):
            source_homeroom_teacher = source_teachers_by_id.get(
                source_section.homeroom_teacher_id
            )
            normalized_teacher_id = (
                str(getattr(source_homeroom_teacher, "teacher_id", "") or "").strip()
            )
            target_homeroom_teacher = target_teachers_by_teacher_id.get(
                normalized_teacher_id
            )
            if target_homeroom_teacher is None:
                skipped_missing_teacher_count += 1
            else:
                target_section.homeroom_teacher_id = target_homeroom_teacher.id
                copied_homeroom_count += 1

        for source_assignment in source_assignments_by_section.get(source_section.id, []):
            subject_code = str(source_assignment.subject_code or "").strip().upper()
            if not subject_code:
                continue
            if subject_code not in target_subject_codes:
                skipped_missing_subject_count += 1
                continue

            source_teacher = source_teachers_by_id.get(source_assignment.teacher_id)
            normalized_teacher_id = (
                str(getattr(source_teacher, "teacher_id", "") or "").strip()
            )
            target_teacher = target_teachers_by_teacher_id.get(normalized_teacher_id)
            if target_teacher is None:
                skipped_missing_teacher_count += 1
                continue

            allocation_key = (target_teacher.id, subject_code)
            if allocation_key not in existing_target_allocation_keys:
                db.add(
                    models.TeacherSubjectAllocation(
                        teacher_id=target_teacher.id,
                        subject_code=subject_code,
                    )
                )
                existing_target_allocation_keys.add(allocation_key)
                copied_subject_link_count += 1

            assignment_key = (target_section.id, subject_code)
            existing_teacher_id = existing_target_assignment_map.get(assignment_key)
            if existing_teacher_id is not None:
                if existing_teacher_id != target_teacher.id:
                    skipped_assignment_conflict_count += 1
                continue

            db.add(
                models.TeacherSectionAssignment(
                    teacher_id=target_teacher.id,
                    planning_section_id=target_section.id,
                    subject_code=subject_code,
                )
            )
            existing_target_assignment_map[assignment_key] = target_teacher.id
            copied_assignment_count += 1

    db.commit()

    success_parts = [
        (
            f"Planning copied from {source_year.year_name} to {target_year.year_name}: "
            f"{created_section_count} sections added"
        ),
        f"{copied_homeroom_count} homeroom links added",
        f"{copied_subject_link_count} teacher-subject links added",
        f"{copied_assignment_count} subject-teacher assignments added.",
    ]
    if existing_section_count:
        success_parts.append(
            f"{existing_section_count} matching sections already existed and were reused."
        )
    if skipped_missing_teacher_count:
        success_parts.append(
            f"{skipped_missing_teacher_count} teacher links were skipped because the teacher does not exist in the target year."
        )
    if skipped_missing_subject_count:
        success_parts.append(
            f"{skipped_missing_subject_count} subject-teacher links were skipped because the subject does not exist in the target year."
        )
    if skipped_assignment_conflict_count:
        success_parts.append(
            f"{skipped_assignment_conflict_count} subject-teacher links were skipped because the section already has an assigned teacher for that subject."
        )

    return _render_planning_page(
        request=request,
        db=db,
        current_user=current_user,
        success=" ".join(success_parts),
    )


@router.post("/")
def create_planning_section(
    request: Request,
    grade_level: str = Form(...),
    section_name: str = Form(...),
    class_status: str = Form(...),
    homeroom_teacher_id: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.has_permission(db, current_user, "planning.create_section"):
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Your role has read-only access and cannot create planning records.",
        )

    normalized_grade_level = _normalize_grade_level(grade_level)
    normalized_section_name = _normalize_section_name(section_name)
    normalized_class_status = _normalize_class_status(class_status)
    parsed_homeroom_teacher_id = _parse_int(homeroom_teacher_id)
    branch_id, academic_year_id = _get_scope_ids(current_user)

    errors = []
    if normalized_grade_level not in GRADE_OPTIONS:
        errors.append("Grade level is required and must be KG or Grade 1 to Grade 12.")

    if normalized_section_name not in SECTION_OPTIONS:
        errors.append("Section must be selected from the predefined dropdown list.")

    if normalized_class_status not in STATUS_OPTIONS:
        errors.append("Class status is required and must be either Current or New.")

    homeroom_teacher = None
    if parsed_homeroom_teacher_id is not None:
        homeroom_teacher = db.query(models.Teacher).filter(
            models.Teacher.id == parsed_homeroom_teacher_id,
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        ).first()
        if not homeroom_teacher:
            errors.append("Selected homeroom teacher is not available in the current branch/year scope.")

    subject_alignment_map = _get_subject_alignment_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    aligned_subjects = subject_alignment_map.get(normalized_grade_level, [])
    allocated_hours = sum(
        int(item.get("weekly_hours", 0))
        for item in aligned_subjects
    )
    if not aligned_subjects:
        errors.append(
            "No subjects were found for the selected grade. Add grade-aligned subjects first in Subjects module."
        )

    duplicate_section = db.query(models.PlanningSection).filter(
        models.PlanningSection.grade_level == normalized_grade_level,
        models.PlanningSection.section_name == normalized_section_name,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if duplicate_section:
        errors.append("This grade and section already exists in planning for the current scope.")

    if errors:
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Unable to create planning section. Please fix the highlighted issues.",
            detail_errors=errors,
            form_data={
                "grade_level": normalized_grade_level or "1",
                "section_name": normalized_section_name or "A",
                "class_status": normalized_class_status or "Current",
                "homeroom_teacher_id": (
                    str(parsed_homeroom_teacher_id)
                    if parsed_homeroom_teacher_id is not None
                    else ""
                ),
            },
        )

    planning_section = models.PlanningSection(
        grade_level=normalized_grade_level,
        section_name=normalized_section_name,
        class_status=normalized_class_status,
        homeroom_teacher_id=(
            homeroom_teacher.id if homeroom_teacher else None
        ),
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )

    try:
        db.add(planning_section)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Planning section creation failed due to duplicate or invalid data.",
        )

    return _render_planning_page(
        request=request,
        db=db,
        current_user=current_user,
        success=(
            f"Planning section created successfully: Grade {normalized_grade_level} - "
            f"Section {normalized_section_name} ({allocated_hours} allocated hours). "
            "Open Edit to assign teachers to each aligned subject."
        ),
    )


@router.get("/edit/{planning_pk}")
def edit_planning_page(
    request: Request,
    planning_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.has_permission(db, current_user, "planning.edit_section"):
        return RedirectResponse(url="/planning", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    planning_section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == planning_pk,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if not planning_section:
        return RedirectResponse(url="/planning", status_code=302)

    return _render_edit_planning_page(
        request=request,
        db=db,
        current_user=current_user,
        planning_section=planning_section,
    )


@router.post("/edit/{planning_pk}")
def update_planning_section(
    request: Request,
    planning_pk: int,
    grade_level: str = Form(...),
    section_name: str = Form(...),
    class_status: str = Form(...),
    homeroom_teacher_id: str = Form(""),
    assignment_subject_codes: list[str] = Form([]),
    assignment_teacher_ids: list[str] = Form([]),
    qualification_override: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.has_permission(db, current_user, "planning.edit_section"):
        return RedirectResponse(url="/planning", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    planning_section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == planning_pk,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if not planning_section:
        return RedirectResponse(url="/planning", status_code=302)

    normalized_grade_level = _normalize_grade_level(grade_level)
    normalized_section_name = _normalize_section_name(section_name)
    normalized_class_status = _normalize_class_status(class_status)
    parsed_homeroom_teacher_id = _parse_int(homeroom_teacher_id)
    parsed_assignment_teacher_ids_by_subject = {}
    for index, raw_subject_code in enumerate(assignment_subject_codes or []):
        subject_code = str(raw_subject_code or "").strip().upper()
        if not subject_code:
            continue
        raw_teacher_id = (
            assignment_teacher_ids[index]
            if index < len(assignment_teacher_ids)
            else ""
        )
        parsed_assignment_teacher_ids_by_subject[subject_code] = _parse_int(raw_teacher_id)

    errors = []
    if normalized_grade_level not in GRADE_OPTIONS:
        errors.append("Grade level is required and must be KG or Grade 1 to Grade 12.")

    if normalized_section_name not in SECTION_OPTIONS:
        errors.append("Section must be selected from the predefined dropdown list.")

    if normalized_class_status not in STATUS_OPTIONS:
        errors.append("Class status is required and must be either Current or New.")

    homeroom_teacher = None
    if parsed_homeroom_teacher_id is not None:
        homeroom_teacher = db.query(models.Teacher).filter(
            models.Teacher.id == parsed_homeroom_teacher_id,
            models.Teacher.branch_id == branch_id,
            models.Teacher.academic_year_id == academic_year_id,
        ).first()
        if not homeroom_teacher:
            errors.append("Selected homeroom teacher is not available in the current branch/year scope.")

    subject_alignment_map = _get_subject_alignment_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    subject_map_by_code = _get_subject_map_by_code(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    aligned_subjects = subject_alignment_map.get(normalized_grade_level, [])
    if normalized_grade_level == _normalize_grade_level(planning_section.grade_level):
        aligned_subjects = _get_section_demand_alignment_map(
            db, branch_id, academic_year_id, [planning_section], subject_map_by_code
        ).get(planning_section.id, [])
    aligned_subject_codes = {
        item.get("subject_code")
        for item in aligned_subjects
        if item.get("subject_code")
    }
    allocated_hours = sum(
        int(item.get("weekly_hours", 0))
        for item in aligned_subjects
    )
    if not aligned_subjects:
        errors.append(
            "No subjects were found for the selected grade. Add grade-aligned subjects first in Subjects module."
        )

    duplicate_section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id != planning_section.id,
        models.PlanningSection.grade_level == normalized_grade_level,
        models.PlanningSection.section_name == normalized_section_name,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if duplicate_section:
        errors.append("This grade and section already exists in planning for the current scope.")

    selected_teacher_ids = sorted({
        teacher_id
        for subject_code, teacher_id in parsed_assignment_teacher_ids_by_subject.items()
        if subject_code in aligned_subject_codes and teacher_id is not None
    })
    scoped_teacher_map = {}
    if selected_teacher_ids:
        scoped_teacher_map = {
            teacher.id: teacher
            for teacher in db.query(models.Teacher).filter(
                models.Teacher.id.in_(selected_teacher_ids),
                models.Teacher.branch_id == branch_id,
                models.Teacher.academic_year_id == academic_year_id,
            ).all()
        }

    teacher_subject_option_map = _get_teacher_subject_option_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    teacher_hours_by_id = _calculate_teacher_section_hours(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        subject_alignment_map=subject_alignment_map,
        subject_map_by_code=subject_map_by_code,
        exclude_planning_section_id=planning_section.id,
    )

    for subject in aligned_subjects:
        subject_code = subject.get("subject_code")
        teacher_id = parsed_assignment_teacher_ids_by_subject.get(subject_code)
        default_homeroom_assignment = bool(
            homeroom_teacher
            and teacher_id is None
            and is_default_homeroom_subject(
                normalized_grade_level,
                subject_name=subject.get("subject_name", ""),
                subject_code=subject_code or "",
            )
        )
        if teacher_id is None and not default_homeroom_assignment:
            continue

        if default_homeroom_assignment:
            teacher = homeroom_teacher
            teacher_id = homeroom_teacher.id
        else:
            teacher = scoped_teacher_map.get(teacher_id)
            if not teacher:
                errors.append(
                    f"Selected teacher for {subject_code} is not available in the current branch/year scope."
                )
                continue

            eligible_teacher_ids = {
                option.get("id")
                for option in teacher_subject_option_map.get(subject_code, [])
            }
            if teacher_id not in eligible_teacher_ids:
                errors.append(
                    f"{_build_teacher_display_name(teacher)} cannot be assigned to {subject_code} because that subject is not enabled in Teachers module."
                )
                continue

        projected_hours = (
            teacher_hours_by_id.get(teacher_id, 0)
            + int(subject.get("weekly_hours", 0) or 0)
        )
        teacher_hours_by_id[teacher_id] = projected_hours
        allowed_hours = get_teacher_international_capacity_hours(
            teacher,
            default_max_hours=24,
        )
        if projected_hours > allowed_hours:
            errors.append(
                f"{_build_teacher_display_name(teacher)} would reach {projected_hours}h after assigning {subject_code}, which exceeds the available capacity of {allowed_hours}h."
            )

    if errors:
        return _render_edit_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            planning_section=planning_section,
            error=" ".join(errors),
            form_data={
                "grade_level": normalized_grade_level or planning_section.grade_level,
                "section_name": normalized_section_name or planning_section.section_name,
                "class_status": normalized_class_status or planning_section.class_status,
                "homeroom_teacher_id": (
                    str(parsed_homeroom_teacher_id)
                    if parsed_homeroom_teacher_id is not None
                    else ""
                ),
            },
            selected_assignment_teacher_ids={
                subject_code: teacher_id
                for subject_code, teacher_id in parsed_assignment_teacher_ids_by_subject.items()
                if subject_code in aligned_subject_codes and teacher_id is not None
            },
            status_code=400,
        )

    qualification_warnings = _build_assignment_alignment_warnings(
        aligned_subjects=aligned_subjects,
        parsed_assignment_teacher_ids_by_subject=parsed_assignment_teacher_ids_by_subject,
        scoped_teacher_map=scoped_teacher_map,
        qualification_lookup=get_qualification_lookup(db),
    )
    if qualification_warnings and not _is_override_enabled(qualification_override):
        return _render_edit_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            planning_section=planning_section,
            form_data={
                "grade_level": normalized_grade_level or planning_section.grade_level,
                "section_name": normalized_section_name or planning_section.section_name,
                "class_status": normalized_class_status or planning_section.class_status,
                "homeroom_teacher_id": (
                    str(parsed_homeroom_teacher_id)
                    if parsed_homeroom_teacher_id is not None
                    else ""
                ),
            },
            selected_assignment_teacher_ids={
                subject_code: teacher_id
                for subject_code, teacher_id in parsed_assignment_teacher_ids_by_subject.items()
                if subject_code in aligned_subject_codes and teacher_id is not None
            },
            qualification_warning={
                "title": "Qualification mismatch warning",
                "message": (
                    "One or more teacher-subject assignments do not align with the "
                    "teacher's recorded degree/major. Review the warning below and "
                    "use the override checkbox if this section assignment is intentional."
                ),
                "items": qualification_warnings,
            },
            status_code=400,
        )

    planning_section.grade_level = normalized_grade_level
    planning_section.section_name = normalized_section_name
    planning_section.class_status = normalized_class_status
    planning_section.homeroom_teacher_id = (
        homeroom_teacher.id if homeroom_teacher else None
    )

    try:
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id == planning_section.id
        ).delete(synchronize_session=False)
        for subject in aligned_subjects:
            subject_code = subject.get("subject_code")
            teacher_id = parsed_assignment_teacher_ids_by_subject.get(subject_code)
            if not subject_code or teacher_id is None:
                continue
            db.add(
                models.TeacherSectionAssignment(
                    teacher_id=teacher_id,
                    planning_section_id=planning_section.id,
                    subject_code=subject_code,
                )
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_edit_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            planning_section=planning_section,
            error="Unable to update planning section due to duplicate or invalid data.",
            form_data={
                "grade_level": normalized_grade_level,
                "section_name": normalized_section_name,
                "class_status": normalized_class_status,
                "homeroom_teacher_id": (
                    str(parsed_homeroom_teacher_id)
                    if parsed_homeroom_teacher_id is not None
                    else ""
                ),
            },
            selected_assignment_teacher_ids={
                subject_code: teacher_id
                for subject_code, teacher_id in parsed_assignment_teacher_ids_by_subject.items()
                if subject_code in aligned_subject_codes and teacher_id is not None
            },
            status_code=400,
        )

    return RedirectResponse(url="/planning", status_code=302)


_PLANNING_SECTION_DELETE_BLOCKER_CHECKS = (
    ("teacher assignments", models.TeacherSectionAssignment, "planning_section_id"),
    ("Planning subject demand", models.PlanningSubjectDemand, "planning_section_id"),
    ("timetable placements", models.TimetableEntry, "planning_section_id"),
    ("teacher scheduling rules", models.TeacherSchedulingRuleTarget, "planning_section_id"),
    ("academic calendar events", models.CalendarEvent, "target_section_id"),
    ("academic calendar events", models.CalendarEventSectionTarget, "section_id"),
    ("subject scheduling rules", models.SubjectDistributionRule, "section_id"),
)

_PLANNING_SECTION_DELETE_DEMAND_LABEL = "Planning subject demand"

_PLANNING_SECTION_DELETE_ACTIONS = {
    "teacher assignments": "Remove the teacher assignments first, then try again.",
    "timetable placements": (
        "Remove or reschedule those placements if they are in a mutable "
        "Draft; placements in a published or archived timetable are "
        "permanent history and cannot be removed."
    ),
    "teacher scheduling rules": "Remove this section from that rule's targets first, then try again.",
    "academic calendar events": "Remove or retarget those calendar events first, then try again.",
    "subject scheduling rules": "Clear that subject scheduling rule override first, then try again.",
}

_PLANNING_SUBJECT_DEMAND_REMOVABLE_ACTION = (
    "This demand was set automatically during setup and has not been used in "
    "any Curriculum Adjustment. Use \"Remove Subject Requirement\" next to that subject in "
    "this section's subject list, then try again."
)
_PLANNING_SUBJECT_DEMAND_PERMANENT_ACTION = (
    "TIS preserves Planning demand history permanently, even after retirement "
    "through Curriculum Adjustment, so this section cannot be made deletable "
    "by removing it."
)

_PLANNING_SECTION_DELETE_INTEGRITY_FALLBACK_MESSAGE = (
    "Cannot delete this Planning section because it is still referenced by "
    "related records. Remove those related records first, then try again."
)


def _get_planning_section_delete_blockers(db: Session, planning_section_id: int):
    """Read-only check for records that would block deleting a Planning section.

    Mirrors the real FK protections on planning_sections.id so the user gets a
    customer-safe explanation instead of an unhandled IntegrityError. This does
    not delete or retire anything. Setup-only inactive suppression rows are
    implementation artifacts, not blockers; every active demand and every
    Curriculum-Adjustment-touched demand remains protected. Teacher assignments
    remain blockers rather than being auto-purged.
    """
    found_labels = []
    for label, model_cls, column_name in _PLANNING_SECTION_DELETE_BLOCKER_CHECKS:
        column = getattr(model_cls, column_name)
        query = db.query(model_cls.id).filter(column == planning_section_id)
        if model_cls is models.PlanningSubjectDemand:
            query = query.filter(or_(
                models.PlanningSubjectDemand.is_active.is_(True),
                models.PlanningSubjectDemand.weekly_periods != 0,
                models.PlanningSubjectDemand.updated_by_user_id.is_not(None),
            ))
        exists = query.first()
        if exists and label not in found_labels:
            found_labels.append(label)
    return found_labels


def _delete_setup_only_suppressions_for_section(
    db: Session, *, planning_section_id: int, branch_id: int, academic_year_id: int,
) -> int:
    """Delete only inert Remove-Subject-Requirement suppression artifacts."""
    return db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.planning_section_id == planning_section_id,
        models.PlanningSubjectDemand.branch_id == branch_id,
        models.PlanningSubjectDemand.academic_year_id == academic_year_id,
        models.PlanningSubjectDemand.is_active.is_(False),
        models.PlanningSubjectDemand.weekly_periods == 0,
        models.PlanningSubjectDemand.updated_by_user_id.is_(None),
    ).delete(synchronize_session=False)


def _get_planning_section_demand_status(db: Session, planning_section_id: int):
    """Classify this section's Planning demand as None, "removable", or "permanent".

    Curriculum Adjustment (`curriculum_adjustment_apply_service._set_demand`)
    always stamps `updated_by_user_id` on a row it creates or touches, while
    the one-time backfill migration never sets it. A row with no
    `updated_by_user_id` has therefore never been acted on by an admin and is
    pure setup scaffolding, safe to hard-delete through the dedicated
    Remove-demand action. Any row that has been touched - whether currently
    active or retired - is genuine Curriculum Adjustment history TIS
    preserves permanently, and remains a permanent blocker.
    """
    rows = db.query(models.PlanningSubjectDemand.updated_by_user_id).filter(
        models.PlanningSubjectDemand.planning_section_id == planning_section_id,
    ).all()
    if not rows:
        return None
    if any(updated_by is not None for (updated_by,) in rows):
        return "permanent"
    return "removable"


def _planning_section_delete_action_for(db: Session, planning_section_id: int, label: str) -> str:
    if label == _PLANNING_SECTION_DELETE_DEMAND_LABEL:
        status = _get_planning_section_demand_status(db, planning_section_id)
        if status == "removable":
            return _PLANNING_SUBJECT_DEMAND_REMOVABLE_ACTION
        return _PLANNING_SUBJECT_DEMAND_PERMANENT_ACTION
    return _PLANNING_SECTION_DELETE_ACTIONS[label]


def _build_planning_section_delete_blocked_response(db: Session, planning_section_id: int, blockers):
    """Build (error, detail_errors) naming every blocker and its real fix.

    Permanent Planning demand and published/archived timetable placements
    cannot actually be removed (see the per-category action text), so the
    combined message never promises a blanket "remove and retry" - each
    blocker gets its own honest action instead.
    """
    if len(blockers) == 1:
        label = blockers[0]
        action = _planning_section_delete_action_for(db, planning_section_id, label)
        error = f"Cannot delete this Planning section because it still has {label}. {action}"
        return error, None

    error = "Cannot delete this Planning section. It is still referenced by:"
    detail_errors = [
        f"{label}: {_planning_section_delete_action_for(db, planning_section_id, label)}"
        for label in blockers
    ]
    return error, detail_errors


@router.get("/delete/{planning_pk}")
def delete_planning_section(
    request: Request,
    planning_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.has_permission(db, current_user, "planning.delete_section"):
        return RedirectResponse(url="/planning", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    planning_section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == planning_pk,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if not planning_section:
        return RedirectResponse(url="/planning", status_code=302)

    blockers = _get_planning_section_delete_blockers(db, planning_section.id)
    if blockers:
        error, detail_errors = _build_planning_section_delete_blocked_response(
            db, planning_section.id, blockers,
        )
        return _render_planning_page(
            request,
            db,
            current_user,
            error=error,
            detail_errors=detail_errors,
            open_section_id=f"planning-section-{planning_section.id}",
        )

    try:
        _delete_setup_only_suppressions_for_section(
            db,
            planning_section_id=planning_section.id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        db.delete(planning_section)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_planning_page(
            request,
            db,
            current_user,
            error=_PLANNING_SECTION_DELETE_INTEGRITY_FALLBACK_MESSAGE,
            open_section_id=f"planning-section-{planning_section.id}",
        )

    return RedirectResponse(url="/planning", status_code=302)


_PLANNING_SUBJECT_DEMAND_PERMANENT_MESSAGE = (
    "This Planning demand has Curriculum Adjustment history, so TIS preserves "
    "it permanently and it cannot be removed."
)

_PLANNING_SUBJECT_DEMAND_INTEGRITY_FALLBACK_MESSAGE = (
    "Unable to remove this Planning demand because it is still referenced by "
    "related records."
)


@router.get("/subject-demand/delete/{demand_id}")
def delete_planning_subject_demand(
    request: Request,
    demand_id: int,
    return_to: str = "/planning/",
    db: Session = Depends(get_db),
):
    """Hard-delete one untouched, setup-only Planning demand row.

    This is the only existing action that physically removes a
    PlanningSubjectDemand row rather than retiring it in place. It is
    intentionally restricted to rows that have never been acted on through
    Curriculum Adjustment (see _get_planning_section_demand_status) so that
    genuine curriculum history is never destroyed.

    `return_to` lets the caller (the Planning page's per-section "Remove
    demand" link) ask to land back on the same expanded section afterward
    - e.g. "/planning/#planning-section-2001" - via the shared safe-redirect
    guard in redirect_utils.py. The trailing slash matches this route's own
    registered path ("/") so the redirect never takes an extra same-origin
    hop through Starlette's redirect_slashes handling. It is validated the
    same way regardless of outcome and always falls back to plain
    "/planning/" when absent or unsafe.
    """
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.has_permission(db, current_user, "planning.delete_section"):
        return RedirectResponse(url="/planning", status_code=302)

    target = safe_redirect_path(return_to, default="/planning/")

    branch_id, academic_year_id = _get_scope_ids(current_user)
    demand = db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.id == demand_id,
        models.PlanningSubjectDemand.branch_id == branch_id,
        models.PlanningSubjectDemand.academic_year_id == academic_year_id,
    ).first()
    if not demand:
        return RedirectResponse(url=target, status_code=302)

    if demand.updated_by_user_id is not None:
        return _render_planning_page(
            request,
            db,
            current_user,
            error=_PLANNING_SUBJECT_DEMAND_PERMANENT_MESSAGE,
            open_section_id=f"planning-section-{demand.planning_section_id}",
        )

    try:
        db.delete(demand)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_planning_page(
            request,
            db,
            current_user,
            error=_PLANNING_SUBJECT_DEMAND_INTEGRITY_FALLBACK_MESSAGE,
            open_section_id=f"planning-section-{demand.planning_section_id}",
        )

    return RedirectResponse(url=target, status_code=302)


# ---------------------------------------------------------------------------
# Subject Requirement removal: single or bulk, explicit-row or legacy-fallback.
#
# This is the customer-facing "Remove Subject Requirement" / "Bulk Remove
# Subject Requirements" action. It supersedes the GET-only demand-id route
# above for new UI, which only ever covered rows that already had an
# explicit PlanningSubjectDemand row. A legacy-fallback requirement (no
# explicit row - the section-subject is still resolved from the Subject
# catalog's weekly_hours) has nothing to delete; "removing" it means
# creating an explicit is_active=False/weekly_periods=0 suppression row.
#
# That suppression row is deliberately NOT stamped the way
# curriculum_adjustment_apply_service._set_demand stamps a zero-out
# retirement. _set_demand always sets updated_by_user_id, which every
# removability check in this module treats as "touched by Curriculum
# Adjustment, therefore permanent". Doing the same here would make a plain
# admin cleanup permanently undeletable the instant it happened, breaking
# the remove-requirement -> remove-section -> remove-subject workflow this
# action exists for. Instead the suppression row gets created_by_user_id
# set (who suppressed it stays auditable) and updated_by_user_id left NULL,
# so it stays classified "setup-only" and can still be fully cleared later
# via the GET demand-id delete route above. A row only becomes permanent by
# actually being touched by Curriculum Adjustment, never merely by being
# suppressed from here.
# ---------------------------------------------------------------------------

def _parse_planning_requirement_target(raw: str):
    text = str(raw or "").strip()
    if ":" not in text:
        return None
    section_part, _, subject_part = text.partition(":")
    subject_code = subject_part.strip().upper()
    if not subject_code:
        return None
    try:
        section_id = int(section_part.strip())
    except ValueError:
        return None
    return section_id, subject_code


def _get_planning_requirement_removal_status(
    db: Session, *, branch_id: int, academic_year_id: int,
    planning_section_id: int, subject_code: str,
):
    """Classify one section+subject Planning requirement for removal.

    Reuses resolve_section_subject_demands - the same explicit-first/legacy-
    fallback authority the rest of Planning already displays - so this can
    never diverge from what is actually shown as an active requirement.
    Returns "removable", "permanent", "fallback", or "not_found".
    """
    resolved = resolve_section_subject_demands(
        db, branch_id=branch_id, academic_year_id=academic_year_id,
        planning_section_id=planning_section_id,
    )
    entry = next(
        (item for item in resolved if item.subject_code == subject_code), None
    )
    if entry is None or not entry.is_active or int(entry.weekly_periods or 0) <= 0:
        return "not_found"
    if entry.authority == "legacy_fallback":
        return "fallback"
    row = db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.id == entry.demand_id
    ).first()
    if row is None:
        return "not_found"
    return "permanent" if row.updated_by_user_id is not None else "removable"


def _apply_planning_requirement_removal(
    db: Session, *, branch_id: int, academic_year_id: int,
    planning_section_id: int, subject_code: str, actor_user_id,
):
    """Mutate exactly one requirement already confirmed removable/fallback.

    A fallback suppression row is deliberately stamped with
    created_by_user_id=actor (who suppressed it stays auditable) but
    updated_by_user_id=None. Curriculum Adjustment (_set_demand) is the only
    code path that ever sets updated_by_user_id, and every removability
    check in this module (_get_planning_requirement_removal_status,
    _get_planning_section_demand_status, routers.subjects._get_subject_demand_status)
    treats updated_by_user_id IS NULL as "never touched by Curriculum
    Adjustment, therefore setup-only and still removable". Stamping the
    acting admin into updated_by_user_id here would make this row look
    identical to genuine Curriculum Adjustment history and become
    permanently undeletable the instant it was created - defeating the
    admin cleanup workflow (remove requirement -> remove section -> remove
    subject) this action exists for.

    Never touches TeacherSectionAssignment, TimetableEntry, or
    CurriculumAdjustmentAudit rows.
    """
    row = db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.planning_section_id == planning_section_id,
        models.PlanningSubjectDemand.subject_code == subject_code,
        models.PlanningSubjectDemand.is_active.is_(True),
    ).first()
    if row is not None:
        db.delete(row)
        return
    db.add(models.PlanningSubjectDemand(
        branch_id=branch_id, academic_year_id=academic_year_id,
        planning_section_id=planning_section_id, subject_code=subject_code,
        weekly_periods=0, is_active=False, retired_at=datetime.utcnow(),
        created_by_user_id=actor_user_id, updated_by_user_id=None,
    ))


_PLANNING_REQUIREMENT_REMOVE_INTEGRITY_FALLBACK_MESSAGE = (
    "Unable to remove the selected Planning requirements because they are "
    "still referenced by related records."
)


@router.post("/subject-requirements/remove")
def remove_planning_subject_requirements(
    request: Request,
    target: list[str] = Form(...),
    return_to: str = "/planning/",
    db: Session = Depends(get_db),
):
    """Atomically remove one or more safely-removable Planning requirements.

    Each `target` is "<planning_section_id>:<subject_code>" (one checkbox
    value per requirement row). Every target is classified first; if any is
    protected, invalid, or out of scope, nothing is mutated and every
    blocked target is named with its reason (atomic from the admin's
    perspective, same contract as Subject bulk delete).
    """
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.has_permission(db, current_user, "planning.delete_section"):
        return RedirectResponse(url="/planning/", status_code=302)

    target_path = safe_redirect_path(return_to, default="/planning/")
    branch_id, academic_year_id = _get_scope_ids(current_user)

    approved = []
    blockers = []
    seen = set()
    first_blocked_section_id = None

    for raw in target:
        parsed = _parse_planning_requirement_target(raw)
        if parsed is None:
            blockers.append("One of the selected requirements was not valid.")
            continue
        section_id, subject_code = parsed
        if (section_id, subject_code) in seen:
            continue
        seen.add((section_id, subject_code))

        section = db.query(models.PlanningSection).filter(
            models.PlanningSection.id == section_id,
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
        ).first()
        if section is None:
            blockers.append(
                "One of the selected requirements is outside your current scope."
            )
            continue

        subject = db.query(models.Subject).filter(
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
            models.Subject.subject_code == subject_code,
        ).first()
        subject_label = subject.subject_name if subject else subject_code
        location_label = f"{subject_label} (Grade {section.grade_level} Section {section.section_name})"

        status = _get_planning_requirement_removal_status(
            db, branch_id=branch_id, academic_year_id=academic_year_id,
            planning_section_id=section_id, subject_code=subject_code,
        )
        if status in ("removable", "fallback"):
            approved.append((section_id, subject_code))
        elif status == "permanent":
            blockers.append(
                f"{location_label}: has Curriculum Adjustment history and is "
                "preserved permanently"
            )
            first_blocked_section_id = first_blocked_section_id or section_id
        else:
            blockers.append(f"{location_label}: is no longer an active Planning requirement")
            first_blocked_section_id = first_blocked_section_id or section_id

    if not approved and not blockers:
        return _render_planning_page(
            request, db, current_user,
            error="Select at least one Planning requirement to remove.",
        )

    if blockers:
        is_plural = len(target) > 1 or len(blockers) > 1
        return _render_planning_page(
            request,
            db,
            current_user,
            error=(
                "Cannot remove the selected Planning requirements."
                if is_plural else "Cannot remove this Planning requirement."
            ),
            detail_errors=blockers,
            open_section_id=(
                f"planning-section-{first_blocked_section_id}"
                if first_blocked_section_id else ""
            ),
        )

    distinct_sections = {section_id for section_id, _ in approved}
    if target_path == "/planning/" and len(distinct_sections) == 1:
        target_path = f"/planning/#planning-section-{next(iter(distinct_sections))}"

    try:
        for section_id, subject_code in approved:
            _apply_planning_requirement_removal(
                db, branch_id=branch_id, academic_year_id=academic_year_id,
                planning_section_id=section_id, subject_code=subject_code,
                actor_user_id=getattr(current_user, "user_id", None),
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_planning_page(
            request,
            db,
            current_user,
            error=_PLANNING_REQUIREMENT_REMOVE_INTEGRITY_FALLBACK_MESSAGE,
        )

    return RedirectResponse(url=target_path, status_code=302)
