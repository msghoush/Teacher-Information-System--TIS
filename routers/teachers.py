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

router = APIRouter(prefix="/teachers", tags=["Teachers"])
templates = Jinja2Templates(directory="templates")

TEACHER_ID_PATTERN = re.compile(r"^\d{1,10}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'\-]*$")

LEVEL_OPTIONS = [
    "Homeroom Teacher",
    "K1",
    "K2",
    "Grade 1",
    "Grade 2",
    "Grade 3",
    "Grade 4",
    "Grade 5",
    "Grade 6",
    "Grade 7",
    "Grade 8",
    "Grade 9",
    "Grade 10",
    "Grade 11",
    "Grade 12",
]
STANDARD_MAX_HOURS = 24


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


def _get_teacher_allocation_map(db: Session, teachers):
    teacher_ids = [teacher.id for teacher in teachers if getattr(teacher, "id", None)]
    if not teacher_ids:
        return {}

    allocations = db.query(models.TeacherSubjectAllocation).filter(
        models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)
    ).order_by(
        models.TeacherSubjectAllocation.teacher_id.asc(),
        models.TeacherSubjectAllocation.subject_code.asc(),
    ).all()

    subject_codes = sorted({
        allocation.subject_code
        for allocation in allocations
        if allocation.subject_code
    })
    subjects_by_code = {}
    if subject_codes:
        subjects_by_code = {
            subject.subject_code: subject
            for subject in db.query(models.Subject).filter(
                models.Subject.subject_code.in_(subject_codes)
            ).all()
            if subject.subject_code
        }

    allocation_map = {
        teacher.id: {
            "subject_codes": [],
            "subject_labels": [],
            "allocated_hours": 0,
            "matches_max_hours": False,
        }
        for teacher in teachers
    }

    for allocation in allocations:
        teacher_data = allocation_map.get(allocation.teacher_id)
        if not teacher_data:
            continue
        subject = subjects_by_code.get(allocation.subject_code)
        subject_hours = 0
        if subject and subject.weekly_hours is not None:
            subject_hours = int(subject.weekly_hours)
        teacher_data["subject_codes"].append(allocation.subject_code)
        teacher_data["subject_labels"].append(f"{allocation.subject_code} ({subject_hours}h)")
        teacher_data["allocated_hours"] += subject_hours

    for teacher in teachers:
        teacher_data = allocation_map.get(teacher.id, {})
        teacher_data["matches_max_hours"] = (
            teacher_data.get("allocated_hours", 0) == (teacher.max_hours or STANDARD_MAX_HOURS)
        )

    return allocation_map


def _render_teachers_page(
    request: Request,
    db: Session,
    current_user,
    error: str = "",
    success: str = "",
    detail_errors=None,
):
    branch_id, academic_year_id = _get_scope_ids(current_user)
    can_modify = auth.can_modify_data(current_user)
    can_edit = auth.can_edit_data(current_user)
    can_delete = auth.can_delete_data(current_user)

    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id
    ).order_by(models.Teacher.id.desc()).all()
    teacher_allocations = _get_teacher_allocation_map(db, teachers)

    return templates.TemplateResponse(
        "teachers.html",
        {
            "request": request,
            "teachers": teachers,
            "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
            "teacher_allocations": teacher_allocations,
            "level_options": LEVEL_OPTIONS,
            "can_modify": can_modify,
            "can_edit": can_edit,
            "can_delete": can_delete,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "user": current_user,
        },
    )


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
    level: str = Form(...),
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
    level = _normalize_spaces(level).strip()
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

    if level not in LEVEL_OPTIONS:
        errors.append("Invalid level selected.")

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")
    elif parsed_max_hours > STANDARD_MAX_HOURS and not allowed_extra:
        errors.append("To set max hours above 24, enable Extra Hours Allowed first.")

    if parsed_max_hours is not None and parsed_max_hours > 0 and subject_map:
        allocated_subject_hours = sum(
            (subject_map[code].weekly_hours or 0)
            for code in normalized_subject_codes
            if code in subject_map
        )
        if allocated_subject_hours != parsed_max_hours:
            errors.append(
                f"Allocated subject hours ({allocated_subject_hours}) must exactly match Max Hours ({parsed_max_hours})."
            )

    if allowed_extra:
        if parsed_extra_hours_count is None or parsed_extra_hours_count <= 0:
            errors.append("Extra hours count must be a positive whole number when extra hours are allowed.")
    else:
        parsed_extra_hours_count = 0

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
        )

    teacher = models.Teacher(
        teacher_id=teacher_id,
        first_name=first_name,
        middle_name=middle_name if middle_name else None,
        last_name=last_name,
        subject_code=normalized_subject_codes[0] if normalized_subject_codes else None,
        level=level,
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
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_teachers_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Teacher creation failed due to duplicate or invalid data.",
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

    assigned_subject_codes = [
        row.subject_code
        for row in db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id == teacher.id
        ).order_by(models.TeacherSubjectAllocation.subject_code.asc()).all()
        if row.subject_code
    ]

    return templates.TemplateResponse(
        "edit_teacher.html",
        {
            "request": request,
            "teacher": teacher,
            "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
            "assigned_subject_codes": assigned_subject_codes,
            "level_options": LEVEL_OPTIONS,
            "error": "",
        },
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
    level: str = Form(...),
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
    level = _normalize_spaces(level).strip()
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

    if level not in LEVEL_OPTIONS:
        errors.append("Invalid level selected.")

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")
    elif parsed_max_hours > STANDARD_MAX_HOURS and not allowed_extra:
        errors.append("To set max hours above 24, enable Extra Hours Allowed first.")

    if parsed_max_hours is not None and parsed_max_hours > 0 and subject_map:
        allocated_subject_hours = sum(
            (subject_map[code].weekly_hours or 0)
            for code in normalized_subject_codes
            if code in subject_map
        )
        if allocated_subject_hours != parsed_max_hours:
            errors.append(
                f"Allocated subject hours ({allocated_subject_hours}) must exactly match Max Hours ({parsed_max_hours})."
            )

    if allowed_extra:
        if parsed_extra_hours_count is None or parsed_extra_hours_count <= 0:
            errors.append("Extra hours count must be a positive whole number when extra hours are allowed.")
    else:
        parsed_extra_hours_count = 0

    duplicate_teacher = db.query(models.Teacher).filter(
        models.Teacher.teacher_id == teacher_id,
        models.Teacher.id != teacher.id
    ).first()
    if duplicate_teacher:
        errors.append("Teacher ID already exists.")

    if errors:
        assigned_subject_codes = list(normalized_subject_codes)
        return templates.TemplateResponse(
            "edit_teacher.html",
            {
                "request": request,
                "teacher": teacher,
                "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
                "assigned_subject_codes": assigned_subject_codes,
                "level_options": LEVEL_OPTIONS,
                "error": " ".join(errors),
            },
            status_code=400,
        )

    teacher.teacher_id = teacher_id
    teacher.first_name = first_name
    teacher.middle_name = middle_name if middle_name else None
    teacher.last_name = last_name
    teacher.subject_code = normalized_subject_codes[0] if normalized_subject_codes else None
    teacher.level = level
    teacher.max_hours = parsed_max_hours if parsed_max_hours is not None else STANDARD_MAX_HOURS
    teacher.extra_hours_allowed = allowed_extra
    teacher.extra_hours_count = parsed_extra_hours_count if parsed_extra_hours_count is not None else 0

    try:
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
        db.commit()
    except IntegrityError:
        db.rollback()
        assigned_subject_codes = list(normalized_subject_codes)
        return templates.TemplateResponse(
            "edit_teacher.html",
            {
                "request": request,
                "teacher": teacher,
                "subject_choices": _get_subject_choices(db, branch_id, academic_year_id),
                "assigned_subject_codes": assigned_subject_codes,
                "level_options": LEVEL_OPTIONS,
                "error": "Unable to update teacher due to duplicate or invalid data.",
            },
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
        db.query(models.TeacherSubjectAllocation).filter(
            models.TeacherSubjectAllocation.teacher_id == teacher.id
        ).delete(synchronize_session=False)
        db.delete(teacher)
        db.commit()

    return RedirectResponse(url="/teachers", status_code=302)
