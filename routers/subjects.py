from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError

import models
from dependencies import get_db
from auth import get_current_user

router = APIRouter(prefix="/subjects", tags=["Subjects"])
templates = Jinja2Templates(directory="templates")


@router.get("/")
def subjects_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):

    if not current_user:
        return RedirectResponse(url="/")

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == current_user.branch_id,
        models.Subject.academic_year_id == current_user.academic_year_id
    ).all()

    return templates.TemplateResponse(
        "subjects.html",
        {
            "request": request,
            "subjects": subjects,
            "user": current_user
        }
    )


# --------------------------------------------------
# ADD SUBJECT
# URL: POST /subjects
# --------------------------------------------------
@router.post("/")
def add_subject(
    request: Request,
    subject_code: str = Form(...),
    subject_name: str = Form(...),
    weekly_hours: int = Form(...),
    grade: int = Form(...),
    db: Session = Depends(get_db),
):

    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/")

    new_subject = models.Subject(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=weekly_hours,
        grade=grade,
        branch_id=current_user.branch_id,
        academic_year_id=current_user.academic_year_id
    )

    try:
        db.add(new_subject)
        db.commit()
    except IntegrityError:
        db.rollback()

        subjects = db.query(models.Subject).filter(
            models.Subject.branch_id == current_user.branch_id,
            models.Subject.academic_year_id == current_user.academic_year_id
        ).all()

        return templates.TemplateResponse(
            "subjects.html",
            {
                "request": request,
                "subjects": subjects,
                "user": current_user,
                "error": "Duplicate subject code is not allowed."
            }
        )

    return RedirectResponse(url="/subjects", status_code=302)


# --------------------------------------------------
# EDIT SUBJECT (GET)
# URL: /subjects/edit/{id}
# --------------------------------------------------
@router.get("/edit/{subject_id}")
def edit_subject_page(
    request: Request,
    subject_id: int,
    db: Session = Depends(get_db),
):

    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/")

    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id,
        models.Subject.branch_id == current_user.branch_id
    ).first()

    if not subject:
        return RedirectResponse(url="/subjects")

    return templates.TemplateResponse(
        "edit_subject.html",
        {
            "request": request,
            "subject": subject,
            "user": current_user
        }
    )


# --------------------------------------------------
# UPDATE SUBJECT (POST)
# --------------------------------------------------
@router.post("/edit/{subject_id}")
def update_subject(
    request: Request,
    subject_id: int,
    subject_code: str = Form(...),
    subject_name: str = Form(...),
    weekly_hours: int = Form(...),
    grade: int = Form(...),
    db: Session = Depends(get_db),
):

    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse(url="/")

    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id,
        models.Subject.branch_id == current_user.branch_id
    ).first()

    if not subject:
        return RedirectResponse(url="/subjects")

    subject.subject_code = subject_code
    subject.subject_name = subject_name
    subject.weekly_hours = weekly_hours
    subject.grade = grade

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/subjects", status_code=302)

    return RedirectResponse(url="/subjects", status_code=302)


# --------------------------------------------------
# DELETE SUBJECT (ADMIN ONLY)
# --------------------------------------------------
@router.get("/delete/{subject_id}")
def delete_subject(
    request: Request,
    subject_id: int,
    db: Session = Depends(get_db),
):

    current_user = get_current_user(request, db)

    if not current_user or current_user.role != "Admin":
        return RedirectResponse(url="/subjects")

    subject = db.query(models.Subject).filter(
        models.Subject.id == subject_id,
        models.Subject.branch_id == current_user.branch_id
    ).first()

    if subject:
        db.delete(subject)
        db.commit()

    return RedirectResponse(url="/subjects", status_code=302)
