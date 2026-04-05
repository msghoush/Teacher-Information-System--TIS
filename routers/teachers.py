import re

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from auth import get_current_user
from ui_shell import build_shell_context

router = APIRouter(prefix="/teachers", tags=["Teachers"])
templates = Jinja2Templates(directory="templates")

TEACHER_ID_PATTERN = re.compile(r"^\d{1,10}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'\-]*$")
STANDARD_MAX_HOURS = 24
SECTION_ASSIGNMENT_SEPARATOR = "::"


def _get_scope_ids(current_user):
    branch_id = getattr(current_user, "scope_branch_id", current_user.branch_id)
    academic_year_id = getattr(
        current_user,
        "scope_academic_year_id",
        current_user.academic_year_id
    )
    return branch_id, academic_year_id


def _normalize_spaces(value: str) -> str:
    return " ".join(str(value).split())


def _normalize_teacher_id(value: str) -> str:
    return _normalize_spaces(value).strip()


def _normalize_name(value: str) -> str:
    cleaned = _normalize_spaces(value).strip()
    if not cleaned:
        return ""
    return " ".join(part.capitalize() for part in cleaned.split(" "))


def _normalize_subject_codes(values):
    cleaned_codes = []
    seen_codes = set()
    for raw_value in values or []:
        code = _normalize_spaces(raw_value).strip().upper()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        cleaned_codes.append(code)
    return cleaned_codes


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


def _is_extra_hours_allowed(value) -> bool:
    cleaned = str(value).strip().lower()
    return cleaned in {"1", "true", "yes", "on"}


def _get_subject_choices(db: Session, branch_id: int, academic_year_id: int):
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.subject_code.asc()).all()
    return [
        {
            "subject_code": subject.subject_code,
            "subject_name": subject.subject_name or "",
            "weekly_hours": subject.weekly_hours or 0,
            "grade": subject.grade,
        }
        for subject in subjects
        if subject.subject_code
    ]


def _build_teacher_display_name(teacher) -> str:
    name_parts = [teacher.first_name]
    if teacher.middle_name:
        name_parts.append(teacher.middle_name)
    name_parts.append(teacher.last_name)
    full_name = " ".join(part for part in name_parts if part).strip()
    return full_name if full_name else f"Teacher #{teacher.id}"


def _subject_grade_label(subject_grade) -> str:
    parsed_grade = _parse_int(subject_grade)
    if parsed_grade is None:
        return ""
    return "KG" if parsed_grade == 0 else str(parsed_grade)


def _format_section_label(section) -> str:
    if not section:
        return "-"
    grade_value = str(section.grade_level or "").strip().upper()
    if grade_value == "KG":
        return f"KG-{section.section_name}"
    return f"Grade {grade_value}-{section.section_name}"


def _format_section_assignment_value(subject_code: str, planning_section_id: int) -> str:
    return f"{subject_code}{SECTION_ASSIGNMENT_SEPARATOR}{planning_section_id}"


def _parse_section_assignment_values(values):
    assignment_map = {}
    normalized_values = []
    invalid_values = []
    seen_values = set()

    for raw_value in values or []:
        text = str(raw_value or "").strip()
        if not text:
            continue
        if SECTION_ASSIGNMENT_SEPARATOR not in text:
            invalid_values.append(text)
            continue

        subject_code_raw, section_id_raw = text.split(SECTION_ASSIGNMENT_SEPARATOR, 1)
        subject_code = _normalize_spaces(subject_code_raw).strip().upper()
        planning_section_id = _parse_int(section_id_raw)
        if not subject_code or planning_section_id is None:
            invalid_values.append(text)
            continue

        normalized_value = _format_section_assignment_value(
            subject_code,
            planning_section_id,
        )
        if normalized_value in seen_values:
            continue
        seen_values.add(normalized_value)
        normalized_values.append(normalized_value)
        assignment_map.setdefault(subject_code, set()).add(planning_section_id)

    return assignment_map, normalized_values, invalid_values


def _get_section_options_by_subject(
    db: Session,
    branch_id: int,
    academic_year_id: int,
    current_teacher_id: int | None = None,
):
    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(models.Subject.subject_code.asc()).all()
    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).order_by(
        models.PlanningSection.grade_level.asc(),
        models.PlanningSection.section_name.asc(),
        models.PlanningSection.id.asc(),
    ).all()

    planning_sections_by_id = {
        section.id: section
        for section in planning_sections
        if getattr(section, "id", None)
    }
    planning_sections_by_grade = {}
    for section in planning_sections:
        grade_label = str(section.grade_level or "").strip().upper()
        if not grade_label:
            continue
        planning_sections_by_grade.setdefault(grade_label, []).append(section)

    scoped_teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).all()
    teacher_names_by_id = {
        teacher.id: _build_teacher_display_name(teacher)
        for teacher in scoped_teachers
        if getattr(teacher, "id", None)
    }

    planning_section_ids = list(planning_sections_by_id.keys())
    if planning_section_ids:
        section_assignments = db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.planning_section_id.in_(planning_section_ids)
        ).all()
    else:
        section_assignments = []

    occupied_assignments = {}
    for assignment in section_assignments:
        occupied_assignments[
            (assignment.subject_code, assignment.planning_section_id)
        ] = assignment.teacher_id

    section_options_by_subject = {}
    for subject in subjects:
        if not subject.subject_code:
            continue
        grade_label = _subject_grade_label(subject.grade)
        subject_options = []
        for section in planning_sections_by_grade.get(grade_label, []):
            occupying_teacher_id = occupied_assignments.get(
                (subject.subject_code, section.id)
            )
            assigned_to_other = (
                occupying_teacher_id is not None
                and occupying_teacher_id != current_teacher_id
            )
            subject_options.append(
                {
                    "section_id": section.id,
                    "label": (
                        f"{_format_section_label(section)}"
                        f" ({section.class_status})"
                    ),
                    "teacher_id": occupying_teacher_id,
                    "teacher_name": teacher_names_by_id.get(occupying_teacher_id, ""),
                    "is_available": not assigned_to_other,
                }
            )
        section_options_by_subject[subject.subject_code] = subject_options

    return {
        "section_options_by_subject": section_options_by_subject,
        "planning_sections_by_id": planning_sections_by_id,
        "occupied_assignments": occupied_assignments,
    }


def _get_teacher_section_assignment_values(db: Session, teacher_id: int):
    rows = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.teacher_id == teacher_id
    ).order_by(
        models.TeacherSectionAssignment.subject_code.asc(),
        models.TeacherSectionAssignment.planning_section_id.asc(),
    ).all()
    return [
        _format_section_assignment_value(
            row.subject_code,
            row.planning_section_id,
        )
        for row in rows
        if row.subject_code and row.planning_section_id is not None
    ]


def _get_teacher_allocation_map(db: Session, teachers, branch_id: int, academic_year_id: int):
    teacher_ids = [teacher.id for teacher in teachers if getattr(teacher, "id", None)]
    if not teacher_ids:
        return {}

    allocations = db.query(models.TeacherSubjectAllocation).filter(
        models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)
    ).order_by(
        models.TeacherSubjectAllocation.teacher_id.asc(),
        models.TeacherSubjectAllocation.subject_code.asc(),
    ).all()

    section_assignments = db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.teacher_id.in_(teacher_ids)
    ).order_by(
        models.TeacherSectionAssignment.teacher_id.asc(),
        models.TeacherSectionAssignment.subject_code.asc(),
        models.TeacherSectionAssignment.planning_section_id.asc(),
    ).all()

    subject_codes = sorted({
        code
        for code in (
            [allocation.subject_code for allocation in allocations if allocation.subject_code]
            + [assignment.subject_code for assignment in section_assignments if assignment.subject_code]
        )
        if code
    })
    subjects_by_code = {}
    if subject_codes:
        subjects_by_code = {
            subject.subject_code: subject
            for subject in db.query(models.Subject).filter(
                models.Subject.subject_code.in_(subject_codes),
                models.Subject.branch_id == branch_id,
                models.Subject.academic_year_id == academic_year_id,
            ).all()
            if subject.subject_code
        }

    allocation_map = {
        teacher.id: {
            "subject_codes": [],
            "subject_labels": [],
            "allocated_hours": 0,
            "teaching_load_labels": [],
            "required_hours": (
                (teacher.max_hours or STANDARD_MAX_HOURS)
                + (
                    (teacher.extra_hours_count or 0)
                    if teacher.extra_hours_allowed
                    else 0
                )
            ),
            "matches_max_hours": False,
            "within_capacity": False,
        }
        for teacher in teachers
    }

    for allocation in allocations:
        teacher_data = allocation_map.get(allocation.teacher_id)
        if not teacher_data:
            continue
        subject = subjects_by_code.get(allocation.subject_code)
        subject_name = "Unnamed Subject"
        subject_hours = 0
        subject_grade = "-"
        if subject and subject.weekly_hours is not None:
            subject_hours = int(subject.weekly_hours)
        if subject and subject.subject_name:
            subject_name = subject.subject_name
        if subject and subject.grade is not None:
            subject_grade = str(subject.grade)
        teacher_data["subject_codes"].append(allocation.subject_code)
        teacher_data["subject_labels"].append(
            f"{allocation.subject_code} - {subject_name} (Grade {subject_grade}, {subject_hours}h)"
        )

    planning_section_ids = sorted({
        assignment.planning_section_id
        for assignment in section_assignments
        if assignment.planning_section_id
    })
    planning_sections_by_id = {}
    if planning_section_ids:
        planning_sections_by_id = {
            section.id: section
            for section in db.query(models.PlanningSection).filter(
                models.PlanningSection.id.in_(planning_section_ids),
                models.PlanningSection.branch_id == branch_id,
                models.PlanningSection.academic_year_id == academic_year_id,
            ).all()
        }

    teaching_load_map = {}
    for assignment in section_assignments:
        teacher_data = allocation_map.get(assignment.teacher_id)
        if not teacher_data:
            continue
        subject = subjects_by_code.get(assignment.subject_code)
        if not subject:
            continue
        subject_hours = int(subject.weekly_hours or 0)
        section = planning_sections_by_id.get(assignment.planning_section_id)
        section_label = _format_section_label(section)
        subject_key = (assignment.teacher_id, assignment.subject_code)
        subject_entry = teaching_load_map.setdefault(
            subject_key,
            {
                "subject_code": assignment.subject_code,
                "subject_name": subject.subject_name or "Unnamed Subject",
                "hours": 0,
                "sections": [],
            },
        )
        subject_entry["hours"] += subject_hours
        subject_entry["sections"].append(section_label)
        teacher_data["allocated_hours"] += subject_hours

    for teacher in teachers:
        teacher_data = allocation_map.get(teacher.id)
        if not teacher_data:
            continue
        teacher_entries = [
            data
            for (teacher_id, _), data in teaching_load_map.items()
            if teacher_id == teacher.id
        ]
        teacher_entries.sort(
            key=lambda item: (item["subject_code"], item["subject_name"])
        )
        teacher_data["teaching_load_labels"] = [
            (
                f"{entry['subject_code']} - {entry['subject_name']} | "
                f"Sections: {', '.join(entry['sections'])} | {entry['hours']}h"
            )
            for entry in teacher_entries
        ]

    for teacher in teachers:
        teacher_data = allocation_map.get(teacher.id, {})
        allocated_hours = teacher_data.get("allocated_hours", 0)
        required_hours = teacher_data.get("required_hours", 0)
        is_within_capacity = allocated_hours <= required_hours
        teacher_data["within_capacity"] = is_within_capacity
        # Keep legacy key name for template compatibility.
        teacher_data["matches_max_hours"] = is_within_capacity

    return allocation_map


def _render_teachers_page(
    request: Request,
    db: Session,
    current_user,
    error: str = "",
    success: str = "",
    detail_errors=None,
    form_data=None,
    selected_subject_codes=None,
    selected_section_assignment_values=None,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    can_modify = auth.can_modify_data(current_user)
    can_edit = auth.can_edit_data(current_user)
    can_delete = auth.can_delete_data(current_user)

    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).order_by(models.Teacher.id.desc()).all()
    teacher_allocations = _get_teacher_allocation_map(
        db,
        teachers,
        branch_id,
        academic_year_id,
    )
    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    normalized_form_data = {
        "teacher_id": "",
        "first_name": "",
        "middle_name": "",
        "last_name": "",
        "max_hours": "24",
        "extra_hours_allowed": False,
        "extra_hours_count": "1",
    }
    if form_data:
        normalized_form_data.update(form_data)

    return templates.TemplateResponse(
        request,
        "teachers.html",
        {
            "request": request,
            "teachers": teachers,
            "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
            "section_options_by_subject": section_assignment_support["section_options_by_subject"],
            "teacher_allocations": teacher_allocations,
            "can_modify": can_modify,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": normalized_form_data,
            "selected_subject_codes": selected_subject_codes or [],
            "selected_section_assignment_values": selected_section_assignment_values or [],
            "user": current_user,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="teachers",
            ),
        },
    )


def _render_edit_teacher_page(
    request: Request,
    db: Session,
    current_user,
    teacher,
    error: str = "",
    assigned_subject_codes=None,
    selected_section_assignment_values=None,
    status_code: int = 200,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        current_teacher_id=teacher.id,
    )

    if assigned_subject_codes is None:
        assigned_subject_codes = [
            row.subject_code
            for row in db.query(models.TeacherSubjectAllocation).filter(
                models.TeacherSubjectAllocation.teacher_id == teacher.id
            ).order_by(models.TeacherSubjectAllocation.subject_code.asc()).all()
            if row.subject_code
        ]

    if selected_section_assignment_values is None:
        selected_section_assignment_values = _get_teacher_section_assignment_values(
            db,
            teacher.id,
        )

    return templates.TemplateResponse(
        request,
        "edit_teacher.html",
        {
            "request": request,
            "teacher": teacher,
            "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
            "section_options_by_subject": section_assignment_support["section_options_by_subject"],
            "assigned_subject_codes": assigned_subject_codes,
            "selected_section_assignment_values": selected_section_assignment_values,
            "error": error,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="teachers",
                title="Edit Teacher",
                eyebrow="Staffing Desk",
                intro="Adjust eligible subjects, section teaching load, workload limits, and extra-hours settings without leaving the unified layout.",
                icon="teachers",
            ),
        },
        status_code=status_code,
    )


def _validate_section_assignments(
    subject_assignment_map,
    normalized_subject_codes,
    subject_map,
    section_assignment_support,
    current_teacher_id: int | None = None,
):
    errors = []
    total_assigned_hours = 0
    planning_sections_by_id = section_assignment_support["planning_sections_by_id"]
    occupied_assignments = section_assignment_support["occupied_assignments"]

    for subject_code, planning_section_ids in subject_assignment_map.items():
        if subject_code not in normalized_subject_codes:
            errors.append(
                f"Section assignments were provided for {subject_code}, but that subject is not selected for this teacher."
            )
            continue

        subject = subject_map.get(subject_code)
        if not subject:
            errors.append(
                f"Section assignments were provided for {subject_code}, but the subject is not available in the current scope."
            )
            continue

        expected_grade_label = _subject_grade_label(subject.grade)
        for planning_section_id in sorted(planning_section_ids):
            planning_section = planning_sections_by_id.get(planning_section_id)
            if not planning_section:
                errors.append(
                    f"Selected section #{planning_section_id} for {subject_code} was not found in the current branch and academic year."
                )
                continue

            actual_grade_label = str(planning_section.grade_level or "").strip().upper()
            if expected_grade_label != actual_grade_label:
                errors.append(
                    f"{subject_code} belongs to Grade {expected_grade_label}, so it cannot be assigned to {_format_section_label(planning_section)}."
                )
                continue

            occupied_teacher_id = occupied_assignments.get(
                (subject_code, planning_section_id)
            )
            if (
                occupied_teacher_id is not None
                and occupied_teacher_id != current_teacher_id
            ):
                errors.append(
                    f"{subject_code} is already assigned in {_format_section_label(planning_section)} to another teacher."
                )
                continue

            total_assigned_hours += int(subject.weekly_hours or 0)

    return errors, total_assigned_hours


@router.get("/")
def teachers_page(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("/")
def create_teacher(
    request: Request,
    teacher_id: str = Form(...),
    first_name: str = Form(...),
    middle_name: str = Form(""),
    last_name: str = Form(...),
    subject_codes: list[str] = Form([]),
    section_assignment_values: list[str] = Form([]),
    max_hours: str = Form("24"),
    extra_hours_allowed: str = Form(""),
    extra_hours_count: str = Form("0"),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_modify_data(current_user):
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Your role has read-only access and cannot create teachers.",
        )

    teacher_id = _normalize_teacher_id(teacher_id)
    first_name = _normalize_name(first_name)
    middle_name = _normalize_name(middle_name)
    last_name = _normalize_name(last_name)
    normalized_subject_codes = _normalize_subject_codes(subject_codes)
    (
        section_assignment_map,
        normalized_section_assignment_values,
        invalid_section_assignment_values,
    ) = _parse_section_assignment_values(section_assignment_values)
    parsed_max_hours = _parse_int(max_hours)
    allowed_extra = _is_extra_hours_allowed(extra_hours_allowed)
    parsed_extra_hours_count = _parse_int(extra_hours_count)
    branch_id, academic_year_id = _get_scope_ids(current_user)

    errors = []
    if not TEACHER_ID_PATTERN.match(teacher_id):
        errors.append("Teacher ID (Iqama/National ID) must be numeric and up to 10 digits.")

    if not first_name:
        errors.append("First name is required.")
    elif not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if middle_name and not NAME_PATTERN.match(middle_name):
        errors.append("Middle name must contain letters only.")

    if not last_name:
        errors.append("Last name is required.")
    elif not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if invalid_section_assignment_values:
        errors.append("One or more section assignments were invalid. Please reselect the sections.")

    subject_map = {}
    if not normalized_subject_codes:
        errors.append("Select at least one subject for this teacher.")
    else:
        scoped_subjects = db.query(models.Subject).filter(
            models.Subject.subject_code.in_(normalized_subject_codes),
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).all()
        subject_map = {
            subject.subject_code: subject
            for subject in scoped_subjects
            if subject.subject_code
        }
        missing_subject_codes = [
            code for code in normalized_subject_codes
            if code not in subject_map
        ]
        if missing_subject_codes:
            errors.append(
                "Selected subject codes do not exist in the current branch/academic year: "
                + ", ".join(missing_subject_codes)
            )

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")
    elif parsed_max_hours > STANDARD_MAX_HOURS and not allowed_extra:
        errors.append("To set max hours above 24, enable Extra Hours Allowed first.")

    if allowed_extra:
        if parsed_extra_hours_count is None or parsed_extra_hours_count <= 0:
            errors.append("Extra hours count must be a positive whole number when extra hours are allowed.")
    else:
        parsed_extra_hours_count = 0

    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    section_assignment_errors, total_assigned_hours = _validate_section_assignments(
        subject_assignment_map=section_assignment_map,
        normalized_subject_codes=normalized_subject_codes,
        subject_map=subject_map,
        section_assignment_support=section_assignment_support,
    )
    errors.extend(section_assignment_errors)

    if parsed_max_hours is not None and parsed_max_hours > 0:
        required_allocation_hours = parsed_max_hours + (
            parsed_extra_hours_count if allowed_extra and parsed_extra_hours_count else 0
        )
        if total_assigned_hours > required_allocation_hours:
            errors.append(
                "Assigned section hours "
                f"({total_assigned_hours}) exceed allowed capacity "
                f"({required_allocation_hours}) based on Max Hours ({parsed_max_hours}) "
                f"+ Extra Hours ({parsed_extra_hours_count if allowed_extra else 0}). "
                "Reduce the selected sections or increase allowed extra hours."
            )

    duplicate_teacher = db.query(models.Teacher).filter(
        models.Teacher.teacher_id == teacher_id
    ).first()
    if duplicate_teacher:
        errors.append("Teacher ID already exists.")

    if errors:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Unable to create teacher. Please fix the highlighted issues.",
            detail_errors=errors,
            form_data={
                "teacher_id": teacher_id,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "max_hours": str(parsed_max_hours or 24),
                "extra_hours_allowed": allowed_extra,
                "extra_hours_count": str(parsed_extra_hours_count or 1),
            },
            selected_subject_codes=normalized_subject_codes,
            selected_section_assignment_values=normalized_section_assignment_values,
        )

    teacher = models.Teacher(
        teacher_id=teacher_id,
        first_name=first_name,
        middle_name=middle_name if middle_name else None,
        last_name=last_name,
        subject_code=normalized_subject_codes[0] if normalized_subject_codes else None,
        level=None,
        max_hours=parsed_max_hours if parsed_max_hours is not None else STANDARD_MAX_HOURS,
        extra_hours_allowed=allowed_extra,
        extra_hours_count=parsed_extra_hours_count if parsed_extra_hours_count is not None else 0,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )

    try:
        db.add(teacher)
        db.flush()
        for subject_code in normalized_subject_codes:
            db.add(
                models.TeacherSubjectAllocation(
                    teacher_id=teacher.id,
                    subject_code=subject_code,
                )
            )
        for subject_code, planning_section_ids in section_assignment_map.items():
            for planning_section_id in sorted(planning_section_ids):
                db.add(
                    models.TeacherSectionAssignment(
                        teacher_id=teacher.id,
                        planning_section_id=planning_section_id,
                        subject_code=subject_code,
                    )
                )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Teacher creation failed due to duplicate or invalid data.",
            form_data={
                "teacher_id": teacher_id,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "max_hours": str(parsed_max_hours or 24),
                "extra_hours_allowed": allowed_extra,
                "extra_hours_count": str(parsed_extra_hours_count or 1),
            },
            selected_subject_codes=normalized_subject_codes,
            selected_section_assignment_values=normalized_section_assignment_values,
        )

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"Teacher created successfully: {first_name} {last_name}",
    )


@router.get("/edit/{teacher_pk}")
def edit_teacher_page(
    request: Request,
    teacher_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_edit_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).first()
    if not teacher:
        return RedirectResponse(url="/teachers", status_code=302)

    return _render_edit_teacher_page(
        request=request,
        db=db,
        current_user=current_user,
        teacher=teacher,
    )


@router.post("/edit/{teacher_pk}")
def update_teacher(
    request: Request,
    teacher_pk: int,
    teacher_id: str = Form(...),
    first_name: str = Form(...),
    middle_name: str = Form(""),
    last_name: str = Form(...),
    subject_codes: list[str] = Form([]),
    section_assignment_values: list[str] = Form([]),
    max_hours: str = Form("24"),
    extra_hours_allowed: str = Form(""),
    extra_hours_count: str = Form("0"),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_edit_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).first()
    if not teacher:
        return RedirectResponse(url="/teachers", status_code=302)

    teacher_id = _normalize_teacher_id(teacher_id)
    first_name = _normalize_name(first_name)
    middle_name = _normalize_name(middle_name)
    last_name = _normalize_name(last_name)
    normalized_subject_codes = _normalize_subject_codes(subject_codes)
    (
        section_assignment_map,
        normalized_section_assignment_values,
        invalid_section_assignment_values,
    ) = _parse_section_assignment_values(section_assignment_values)
    parsed_max_hours = _parse_int(max_hours)
    allowed_extra = _is_extra_hours_allowed(extra_hours_allowed)
    parsed_extra_hours_count = _parse_int(extra_hours_count)

    errors = []
    if not TEACHER_ID_PATTERN.match(teacher_id):
        errors.append("Teacher ID (Iqama/National ID) must be numeric and up to 10 digits.")

    if not first_name:
        errors.append("First name is required.")
    elif not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if middle_name and not NAME_PATTERN.match(middle_name):
        errors.append("Middle name must contain letters only.")

    if not last_name:
        errors.append("Last name is required.")
    elif not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if invalid_section_assignment_values:
        errors.append("One or more section assignments were invalid. Please reselect the sections.")

    subject_map = {}
    if not normalized_subject_codes:
        errors.append("Select at least one subject for this teacher.")
    else:
        scoped_subjects = db.query(models.Subject).filter(
            models.Subject.subject_code.in_(normalized_subject_codes),
            models.Subject.branch_id == branch_id,
            models.Subject.academic_year_id == academic_year_id,
        ).all()
        subject_map = {
            subject.subject_code: subject
            for subject in scoped_subjects
            if subject.subject_code
        }
        missing_subject_codes = [
            code for code in normalized_subject_codes
            if code not in subject_map
        ]
        if missing_subject_codes:
            errors.append(
                "Selected subject codes do not exist in the current branch/academic year: "
                + ", ".join(missing_subject_codes)
            )

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")
    elif parsed_max_hours > STANDARD_MAX_HOURS and not allowed_extra:
        errors.append("To set max hours above 24, enable Extra Hours Allowed first.")

    if allowed_extra:
        if parsed_extra_hours_count is None or parsed_extra_hours_count <= 0:
            errors.append("Extra hours count must be a positive whole number when extra hours are allowed.")
    else:
        parsed_extra_hours_count = 0

    section_assignment_support = _get_section_options_by_subject(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
        current_teacher_id=teacher.id,
    )
    section_assignment_errors, total_assigned_hours = _validate_section_assignments(
        subject_assignment_map=section_assignment_map,
        normalized_subject_codes=normalized_subject_codes,
        subject_map=subject_map,
        section_assignment_support=section_assignment_support,
        current_teacher_id=teacher.id,
    )
    errors.extend(section_assignment_errors)

    if parsed_max_hours is not None and parsed_max_hours > 0:
        required_allocation_hours = parsed_max_hours + (
            parsed_extra_hours_count if allowed_extra and parsed_extra_hours_count else 0
        )
        if total_assigned_hours > required_allocation_hours:
            errors.append(
                "Assigned section hours "
                f"({total_assigned_hours}) exceed allowed capacity "
                f"({required_allocation_hours}) based on Max Hours ({parsed_max_hours}) "
                f"+ Extra Hours ({parsed_extra_hours_count if allowed_extra else 0}). "
                "Reduce the selected sections or increase allowed extra hours."
            )

    duplicate_teacher = db.query(models.Teacher).filter(
        models.Teacher.teacher_id == teacher_id,
        models.Teacher.id != teacher.id
    ).first()
    if duplicate_teacher:
        errors.append("Teacher ID already exists.")

    if errors:
        return _render_edit_teacher_page(
            request=request,
            db=db,
            current_user=current_user,
            teacher=teacher,
            error=" ".join(errors),
            assigned_subject_codes=list(normalized_subject_codes),
            selected_section_assignment_values=normalized_section_assignment_values,
            status_code=400,
        )

    teacher.teacher_id = teacher_id
    teacher.first_name = first_name
    teacher.middle_name = middle_name if middle_name else None
    teacher.last_name = last_name
    teacher.subject_code = normalized_subject_codes[0] if normalized_subject_codes else None
    teacher.level = None
    teacher.max_hours = parsed_max_hours if parsed_max_hours is not None else STANDARD_MAX_HOURS
    teacher.extra_hours_allowed = allowed_extra
    teacher.extra_hours_count = parsed_extra_hours_count if parsed_extra_hours_count is not None else 0

    try:
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        for subject_code in normalized_subject_codes:
            db.add(
                models.TeacherSubjectAllocation(
                    teacher_id=teacher.id,
                    subject_code=subject_code,
                )
            )
        for subject_code, planning_section_ids in section_assignment_map.items():
            for planning_section_id in sorted(planning_section_ids):
                db.add(
                    models.TeacherSectionAssignment(
                        teacher_id=teacher.id,
                        planning_section_id=planning_section_id,
                        subject_code=subject_code,
                    )
                )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_edit_teacher_page(
            request=request,
            db=db,
            current_user=current_user,
            teacher=teacher,
            error="Unable to update teacher due to duplicate or invalid data.",
            assigned_subject_codes=list(normalized_subject_codes),
            selected_section_assignment_values=normalized_section_assignment_values,
            status_code=400,
        )

    return RedirectResponse(url="/teachers", status_code=302)


@router.get("/delete/{teacher_pk}")
def delete_teacher(
    request: Request,
    teacher_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_delete_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = db.query(models.Teacher).filter(
        models.Teacher.id == teacher_pk,
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).first()
    if teacher:
        db.query(models.TeacherSectionAssignment).filter(
            models.TeacherSectionAssignment.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.delete(teacher)
        db.commit()

    return RedirectResponse(url="/teachers", status_code=302)


@router.post("/delete-bulk")
def delete_teachers_bulk(
    request: Request,
    selected_teacher_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_delete_data(current_user):
        return RedirectResponse(url="/teachers", status_code=302)

    unique_teacher_ids = sorted({
        int(teacher_id)
        for teacher_id in selected_teacher_ids
        if teacher_id
    })
    if not unique_teacher_ids:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Select at least one teacher to delete.",
        )

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher_rows = db.query(models.Teacher).filter(
        models.Teacher.id.in_(unique_teacher_ids),
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).all()
    teacher_map = {teacher.id: teacher for teacher in teacher_rows}
    missing_ids = [
        teacher_id for teacher_id in unique_teacher_ids
        if teacher_id not in teacher_map
    ]
    if missing_ids:
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="One or more selected teachers were not found in your current scope.",
        )

    teacher_ids_to_delete = list(teacher_map.keys())
    db.query(models.TeacherSectionAssignment).filter(
        models.TeacherSectionAssignment.teacher_id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.query(models.TeacherSubjectAllocation).filter(
        models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.query(models.Teacher).filter(
        models.Teacher.id.in_(teacher_ids_to_delete)
    ).delete(synchronize_session=False)
    db.commit()

    deleted_count = len(teacher_ids_to_delete)
    success_message = (
        "Teacher deleted successfully."
        if deleted_count == 1
        else f"{deleted_count} teachers deleted successfully."
    )

    return _render_teachers_page(
        request=request,
        db=db,
        current_user=current_user,
        success=success_message,
    )
