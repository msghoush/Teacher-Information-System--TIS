from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os
from typing import Optional

from database import engine, SessionLocal
import models
import auth
from dependencies import get_db
from routers import subjects
from auth import get_password_hash
from models import User, Branch, AcademicYear

# ---------------------------------------
# Create Tables
# ---------------------------------------
models.Base.metadata.create_all(bind=engine)

# ---------------------------------------
# App Initialization
# ---------------------------------------
app = FastAPI(title="Teacher Information System")

templates = Jinja2Templates(directory="templates")


def _build_login_context(
    db: Session,
    username: str = "",
    selected_branch_id: Optional[int] = None,
    selected_academic_year_id: Optional[int] = None,
    error: Optional[str] = None,
):
    branches = db.query(models.Branch).filter(
        models.Branch.status == True
    ).order_by(models.Branch.name.asc()).all()
    academic_years = db.query(models.AcademicYear).order_by(
        models.AcademicYear.year_name.desc()
    ).all()
    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()

    if selected_academic_year_id is None and active_year:
        selected_academic_year_id = active_year.id

    return {
        "username": username,
        "branches": branches,
        "academic_years": academic_years,
        "selected_branch_id": selected_branch_id,
        "selected_academic_year_id": selected_academic_year_id,
        "active_year_id": active_year.id if active_year else None,
        "error": error,
    }


def _render_login_page(
    request: Request,
    db: Session,
    username: str = "",
    selected_branch_id: Optional[int] = None,
    selected_academic_year_id: Optional[int] = None,
    error: Optional[str] = None,
    status_code: int = 200,
):
    context = _build_login_context(
        db=db,
        username=username,
        selected_branch_id=selected_branch_id,
        selected_academic_year_id=selected_academic_year_id,
        error=error,
    )
    context["request"] = request
    return templates.TemplateResponse(
        "index.html",
        context,
        status_code=status_code,
    )

# ---------------------------------------
# Include Routers
# ---------------------------------------
app.include_router(subjects.router)

# ---------------------------------------
# ROOT (Login Page)
# ---------------------------------------
@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request,
    db: Session = Depends(get_db)
):
    return _render_login_page(
        request=request,
        db=db,
    )

# ---------------------------------------
# LOGIN
# ---------------------------------------
@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    branch_id: int = Form(...),
    academic_year_id: int = Form(...),
    db: Session = Depends(get_db)
):
    username = username.strip()
    user = auth.authenticate_user(db, username, password)

    if not user:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            selected_branch_id=branch_id,
            selected_academic_year_id=academic_year_id,
            error="Invalid User ID or password.",
            status_code=401
        )

    if not user.is_active:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            selected_branch_id=branch_id,
            selected_academic_year_id=academic_year_id,
            error="Your account is inactive. Please contact Admin.",
            status_code=403
        )

    selected_branch = db.query(models.Branch).filter(
        models.Branch.id == branch_id,
        models.Branch.status == True
    ).first()
    if not selected_branch:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            selected_branch_id=branch_id,
            selected_academic_year_id=academic_year_id,
            error="Selected branch is unavailable.",
            status_code=400
        )

    if user.branch_id != branch_id:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            selected_branch_id=branch_id,
            selected_academic_year_id=academic_year_id,
            error="This branch is not assigned to your account.",
            status_code=403
        )

    selected_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()
    if not selected_year:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            selected_branch_id=branch_id,
            selected_academic_year_id=academic_year_id,
            error="Selected academic year is invalid.",
            status_code=400
        )

    if not selected_year.is_active:
        return _render_login_page(
            request=request,
            db=db,
            username=username,
            selected_branch_id=branch_id,
            selected_academic_year_id=academic_year_id,
            error="Selected academic year is not current. Please choose the current year.",
            status_code=403
        )

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="user_id",
        value=user.user_id,
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="branch_id",
        value=str(branch_id),
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="academic_year_id",
        value=str(academic_year_id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# LOGOUT
# ---------------------------------------
@app.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("user_id")
    response.delete_cookie("branch_id")
    response.delete_cookie("academic_year_id")
    return response


# ---------------------------------------
# ADMIN: SET CURRENT YEAR
# ---------------------------------------
@app.post("/admin/current-year")
def set_current_year(
    request: Request,
    academic_year_id: int = Form(...),
    db: Session = Depends(get_db)
):
    current_user = auth.get_current_user(request, db)

    if not current_user or current_user.role != "Admin":
        return RedirectResponse(url="/", status_code=302)

    target_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == academic_year_id
    ).first()

    if not target_year:
        return RedirectResponse(url="/dashboard", status_code=302)

    db.query(models.AcademicYear).update(
        {models.AcademicYear.is_active: False},
        synchronize_session=False
    )
    target_year.is_active = True
    db.commit()

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="academic_year_id",
        value=str(target_year.id),
        httponly=True,
        samesite="lax"
    )
    return response


# ---------------------------------------
# DASHBOARD
# ---------------------------------------
@app.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    user = auth.get_current_user(request, db)

    if not user:
        return RedirectResponse(url="/")

    scoped_branch_id = getattr(user, "scope_branch_id", user.branch_id)
    scoped_academic_year_id = getattr(
        user,
        "scope_academic_year_id",
        user.academic_year_id
    )

    branch = db.query(models.Branch).filter(
        models.Branch.id == scoped_branch_id
    ).first()

    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == scoped_academic_year_id
    ).first()

    branch_name = branch.name if branch else "Not assigned"
    academic_year_name = (
        academic_year.year_name if academic_year else "Not assigned"
    )
    subjects_query = db.query(models.Subject).filter(
        models.Subject.branch_id == scoped_branch_id,
        models.Subject.academic_year_id == scoped_academic_year_id
    )
    teachers_query = db.query(models.Teacher).filter(
        models.Teacher.branch_id == scoped_branch_id,
        models.Teacher.academic_year_id == scoped_academic_year_id
    )
    subject_count = subjects_query.count()
    teacher_count = teachers_query.count()
    subjects_preview = subjects_query.order_by(
        models.Subject.id.desc()
    ).limit(8).all()
    teachers_preview = teachers_query.order_by(
        models.Teacher.id.desc()
    ).limit(8).all()
    all_years = db.query(models.AcademicYear).order_by(
        models.AcademicYear.year_name.desc()
    ).all()
    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "branch_name": branch_name,
            "academic_year_name": academic_year_name,
            "subject_count": subject_count,
            "teacher_count": teacher_count,
            "subjects_preview": subjects_preview,
            "teachers_preview": teachers_preview,
            "all_years": all_years,
            "active_year_id": active_year.id if active_year else None,
            "is_admin": user.role == "Admin"
        }
    )


# ---------------------------------------
# Startup Initialization
# ---------------------------------------
@app.on_event("startup")
def setup_initial_data():

    db = SessionLocal()
    admin_user_id = os.getenv("ADMIN_USER_ID", "2623252018")
    admin_password = os.getenv("ADMIN_PASSWORD", "UnderProcess1984")

    # Create Branch if not exists
    branch = db.query(Branch).filter(
        Branch.name == "Hamadania"
    ).first()

    if not branch:
        branch = Branch(
            name="Hamadania",
            location="Main Campus",
            status=True
        )
        db.add(branch)
        db.commit()
        db.refresh(branch)

    # Create Academic Year if not exists
    academic_year = db.query(AcademicYear).filter(
        AcademicYear.year_name == "2025-2026"
    ).first()

    if not academic_year:
        academic_year = AcademicYear(
            year_name="2025-2026",
            is_active=True
        )
        db.add(academic_year)
        db.commit()
        db.refresh(academic_year)
    else:
        active_year = db.query(AcademicYear).filter(
            AcademicYear.is_active == True
        ).first()
        if not active_year:
            academic_year.is_active = True
            db.commit()

    # Create Admin User if not exists
    existing_user = db.query(User).filter(
        User.user_id == admin_user_id
    ).first()

    if not existing_user:
        admin_user = User(
            user_id=admin_user_id,
            first_name="mohamad",
            last_name="El Ghoche",
            password=get_password_hash(admin_password),
            role="Admin",
            branch_id=branch.id,
            academic_year_id=academic_year.id,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
    else:
        updated = False

        if not auth.verify_password(admin_password, existing_user.password):
            existing_user.password = get_password_hash(admin_password)
            updated = True

        if existing_user.role != "Admin":
            existing_user.role = "Admin"
            updated = True

        if not existing_user.branch_id:
            existing_user.branch_id = branch.id
            updated = True

        if not existing_user.academic_year_id:
            existing_user.academic_year_id = academic_year.id
            updated = True

        if not existing_user.is_active:
            existing_user.is_active = True
            updated = True

        if updated:
            db.commit()

    db.close()
