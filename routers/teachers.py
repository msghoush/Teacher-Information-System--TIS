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

TEACHER_ID_PATTERN = re.compile(r"^\d{9}$")
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
MAX_ALLOWED_HOURS = 24


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


def _clamp_max_hours(value):
    parsed_value = _parse_int(value)
    if parsed_value is None:
        return None
    return min(parsed_value, MAX_ALLOWED_HOURS)


def _is_extra_hours_allowed(value) -> bool:
    cleaned = str(value).strip().lower()
    return cleaned in {"1", "true", "yes", "on"}


def _get_subject_choices(db: Session):
    subjects = db.query(models.Subject).order_by(models.Subject.subject_code.asc()).all()
    return [
        {
            "subject_code": subject.subject_code,
            "subject_name": subject.subject_name or "",
        }
        for subject in subjects
        if subject.subject_code
    ]


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

    return templates.TemplateResponse(
        "teachers.html",
        {
            "request": request,
            "teachers": teachers,
            "subject_choices": _get_subject_choices(db),
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
    subject_code: str = Form(...),
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
    subject_code = _normalize_spaces(subject_code).strip().upper()
    level = _normalize_spaces(level).strip()
    parsed_max_hours = _clamp_max_hours(max_hours)
    allowed_extra = _is_extra_hours_allowed(extra_hours_allowed)
    parsed_extra_hours_count = _parse_int(extra_hours_count)

    errors = []
    if not TEACHER_ID_PATTERN.match(teacher_id):
        errors.append("Teacher ID must be numeric and exactly 9 digits.")

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

    if not subject_code:
        errors.append("Subject code is required.")
    else:
        subject_exists = db.query(models.Subject).filter(
            models.Subject.subject_code == subject_code
        ).first()
        if not subject_exists:
            errors.append("Selected subject code does not exist.")

    if level not in LEVEL_OPTIONS:
        errors.append("Invalid level selected.")

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")

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

    branch_id, academic_year_id = _get_scope_ids(current_user)
    teacher = models.Teacher(
        teacher_id=teacher_id,
        first_name=first_name,
        middle_name=middle_name if middle_name else None,
        last_name=last_name,
        subject_code=subject_code,
        level=level,
        max_hours=parsed_max_hours if parsed_max_hours is not None else MAX_ALLOWED_HOURS,
        extra_hours_allowed=allowed_extra,
        extra_hours_count=parsed_extra_hours_count if parsed_extra_hours_count is not None else 0,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )

    try:
        db.add(teacher)
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

    return templates.TemplateResponse(
        "edit_teacher.html",
        {
            "request": request,
            "teacher": teacher,
            "subject_choices": _get_subject_choices(db),
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
    subject_code: str = Form(...),
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
    subject_code = _normalize_spaces(subject_code).strip().upper()
    level = _normalize_spaces(level).strip()
    parsed_max_hours = _clamp_max_hours(max_hours)
    allowed_extra = _is_extra_hours_allowed(extra_hours_allowed)
    parsed_extra_hours_count = _parse_int(extra_hours_count)

    errors = []
    if not TEACHER_ID_PATTERN.match(teacher_id):
        errors.append("Teacher ID must be numeric and exactly 9 digits.")

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

    subject_exists = db.query(models.Subject).filter(
        models.Subject.subject_code == subject_code
    ).first()
    if not subject_exists:
        errors.append("Selected subject code does not exist.")

    if level not in LEVEL_OPTIONS:
        errors.append("Invalid level selected.")

    if parsed_max_hours is None or parsed_max_hours <= 0:
        errors.append("Max hours must be a positive whole number.")

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
        return templates.TemplateResponse(
            "edit_teacher.html",
            {
                "request": request,
                "teacher": teacher,
                "subject_choices": _get_subject_choices(db),
                "level_options": LEVEL_OPTIONS,
                "error": " ".join(errors),
            },
            status_code=400,
        )

    teacher.teacher_id = teacher_id
    teacher.first_name = first_name
    teacher.middle_name = middle_name if middle_name else None
    teacher.last_name = last_name
    teacher.subject_code = subject_code
    teacher.level = level
    teacher.max_hours = parsed_max_hours if parsed_max_hours is not None else MAX_ALLOWED_HOURS
    teacher.extra_hours_allowed = allowed_extra
    teacher.extra_hours_count = parsed_extra_hours_count if parsed_extra_hours_count is not None else 0

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "edit_teacher.html",
            {
                "request": request,
                "teacher": teacher,
                "subject_choices": _get_subject_choices(db),
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
        db.delete(teacher)
        db.commit()

    return RedirectResponse(url="/teachers", status_code=302)
