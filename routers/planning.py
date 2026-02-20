from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from auth import get_current_user

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
        name_parts = [teacher.first_name]
        if teacher.middle_name:
            name_parts.append(teacher.middle_name)
        name_parts.append(teacher.last_name)
        full_name = " ".join(part for part in name_parts if part).strip()
        display_name = full_name if full_name else f"Teacher #{teacher.id}"
        names_by_id[teacher.id] = display_name
        choices.append(
            {
                "id": teacher.id,
                "label": f"{teacher.teacher_id} - {display_name}",
            }
        )

    return choices, names_by_id


def _build_planning_rows(
    planning_sections,
    subject_alignment_map,
    teacher_names_by_id,
):
    rows = []
    for section in planning_sections:
        aligned_subjects = subject_alignment_map.get(section.grade_level, [])
        allocated_hours = sum(
            int(item.get("weekly_hours", 0))
            for item in aligned_subjects
        )
        rows.append(
            {
                "record": section,
                "aligned_subjects": aligned_subjects,
                "allocated_hours": allocated_hours,
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

    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).all()

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
    planning_rows = _build_planning_rows(
        planning_sections=planning_sections,
        subject_alignment_map=subject_alignment_map,
        teacher_names_by_id=teacher_names_by_id,
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
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": normalized_form_data,
            "user": current_user,
        },
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
            f"Section {normalized_section_name} ({allocated_hours} allocated hours)."
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

    subject_alignment_map = _get_subject_alignment_map(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    aligned_subjects = subject_alignment_map.get(planning_section.grade_level, [])
    allocated_hours = sum(
        int(item.get("weekly_hours", 0))
        for item in aligned_subjects
    )
    teacher_choices, _ = _get_teacher_choices(
        db=db,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )

    return templates.TemplateResponse(
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
            "error": "",
        },
    )


@router.post("/edit/{planning_pk}")
def update_planning_section(
    request: Request,
    planning_pk: int,
    grade_level: str = Form(...),
    section_name: str = Form(...),
    class_status: str = Form(...),
    homeroom_teacher_id: str = Form(""),
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
        models.PlanningSection.id != planning_section.id,
        models.PlanningSection.grade_level == normalized_grade_level,
        models.PlanningSection.section_name == normalized_section_name,
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).first()
    if duplicate_section:
        errors.append("This grade and section already exists in planning for the current scope.")

    if errors:
        teacher_choices, _ = _get_teacher_choices(
            db=db,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        return templates.TemplateResponse(
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
                "error": " ".join(errors),
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
        db.commit()
    except IntegrityError:
        db.rollback()
        teacher_choices, _ = _get_teacher_choices(
            db=db,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        return templates.TemplateResponse(
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
                "error": "Unable to update planning section due to duplicate or invalid data.",
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
        db.delete(planning_section)
        db.commit()

    return RedirectResponse(url="/planning", status_code=302)
