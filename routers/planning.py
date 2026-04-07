from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from auth import get_current_user
from teacher_capacity import get_teacher_international_capacity_hours
from ui_shell import build_shell_context
from year_copy import get_copy_year_choices, get_academic_year

router = APIRouter(prefix="/planning", tags=["Planning"])
templates = Jinja2Templates(directory="templates")

GRADE_OPTIONS = ["KG"] + [str(value) for value in range(1, 13)]
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
    cleaned = str(value).strip().upper()
    if cleaned in {"K", "KG", "KINDERGARTEN"}:
        return "KG"
    parsed_value = _parse_int(cleaned)
    if parsed_value is None:
        return ""
    if 1 <= parsed_value <= 12:
        return str(parsed_value)
    return ""


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
        alignment_map[grade_label].append(
            {
                "subject_code": subject.subject_code,
                "subject_name": subject.subject_name or "Unnamed Subject",
                "weekly_hours": int(subject.weekly_hours or 0),
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
                "teacher_options": subject_teacher_options.get(subject_code, []),
                "selected_teacher_id": str(
                    selected_teacher_ids_by_subject.get(subject_code, "")
                ),
            }
        )
    return rows


def _get_current_assignment_selection_map(
    section_assignment_map,
    planning_section_id: int,
):
    return {
        subject_code: details.get("teacher_id")
        for subject_code, details in section_assignment_map.get(planning_section_id, {}).items()
    }


def _calculate_teacher_section_hours(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    subject_map_by_code,
    exclude_planning_section_id: int | None = None,
):
    planning_section_ids = [
        section_id
        for (section_id,) in db.query(models.PlanningSection.id).filter(
            models.PlanningSection.branch_id == branch_id,
            models.PlanningSection.academic_year_id == academic_year_id,
        ).all()
    ]
    if not planning_section_ids:
        return {}

    assignments_query = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.planning_section_id.in_(planning_section_ids)
    )
    if exclude_planning_section_id is not None:
        assignments_query = assignments_query.filter(
            models.TeacherSectionAssignment.planning_section_id != exclude_planning_section_id
        )

    teacher_hours = {}
    for assignment in assignments_query.all():
        subject = subject_map_by_code.get(assignment.subject_code)
        if not subject:
            continue
        teacher_hours[assignment.teacher_id] = (
            teacher_hours.get(assignment.teacher_id, 0)
            + int(subject.weekly_hours or 0)
        )

    return teacher_hours


def _build_planning_rows(
    planning_sections,
    subject_alignment_map,
    teacher_names_by_id,
    section_assignment_map,
):
    rows = []
    for section in planning_sections:
        aligned_subjects = subject_alignment_map.get(section.grade_level, [])
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
            subject_assignments.append(
                {
                    **subject,
                    "teacher_name": subject_teacher_name,
                }
            )
        rows.append(
            {
                "record": section,
                "aligned_subjects": aligned_subjects,
                "subject_assignments": subject_assignments,
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
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    can_modify = auth.can_modify_data(current_user)
    can_edit = auth.can_edit_data(current_user)
    can_delete = auth.can_delete_data(current_user)
    can_copy_year_data = auth.is_developer(current_user)
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
    teacher_choices, teacher_names_by_id = _get_teacher_choices(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_assignment_map = _get_section_assignment_map(
        db=db,
        planning_sections=planning_sections,
        teacher_names_by_id=teacher_names_by_id,
        subject_map_by_code=subject_map_by_code,
    )
    planning_rows = _build_planning_rows(
        planning_sections=planning_sections,
        subject_alignment_map=subject_alignment_map,
        teacher_names_by_id=teacher_names_by_id,
        section_assignment_map=section_assignment_map,
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
            "current_sections_count": current_sections_count,
            "new_sections_count": new_sections_count,
            "total_allocated_hours": total_allocated_hours,
            "can_modify": can_modify,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "can_copy_year_data": can_copy_year_data,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": normalized_form_data,
            "copy_year_choices": copy_year_choices,
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
    section_assignment_map = _get_section_assignment_map(
        db=db,
        planning_sections=[planning_section],
        teacher_names_by_id=teacher_names_by_id,
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
    aligned_subjects = subject_alignment_map.get(selected_grade_level, [])
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
            "selected_assignment_teacher_ids": {
                subject_code: str(teacher_id)
                for subject_code, teacher_id in (selected_assignment_teacher_ids or {}).items()
                if teacher_id is not None
            },
            "form_data": normalized_form_data,
            "error": error,
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

    if not auth.is_developer(current_user):
        return _render_planning_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Only the developer user can copy planning data between academic years.",
        )

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

    if not auth.can_modify_data(current_user):
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

    if not auth.can_edit_data(current_user):
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
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_edit_data(current_user):
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
        subject_map_by_code=subject_map_by_code,
        exclude_planning_section_id=planning_section.id,
    )

    for subject in aligned_subjects:
        subject_code = subject.get("subject_code")
        teacher_id = parsed_assignment_teacher_ids_by_subject.get(subject_code)
        if teacher_id is None:
            continue

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
                f"{_build_teacher_display_name(teacher)} would reach {projected_hours}h after assigning {subject_code}, which exceeds the available international capacity of {allowed_hours}h."
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


@router.get("/delete/{planning_pk}")
def delete_planning_section(
    request: Request,
    planning_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_delete_data(current_user):
        return RedirectResponse(url="/planning", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    planning_section = db.query(models.PlanningSection).filter(
        models.PlanningSection.id == planning_pk,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if planning_section:
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id == planning_section.id
        ).delete(synchronize_session=False)
        db.delete(planning_section)
        db.commit()

    return RedirectResponse(url="/planning", status_code=302)
