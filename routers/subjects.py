from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import models
from dependencies import get_db, get_current_user

router = APIRouter()

templates = Jinja2Templates(directory="templates")


@router.get("/subjects")
def subjects_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
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


@router.post("/subjects")
def add_subject(
    request: Request,
    subject_code: str = Form(...),
    subject_name: str = Form(...),
    weekly_hours: int = Form(...),
    grade: int = Form(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):

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
