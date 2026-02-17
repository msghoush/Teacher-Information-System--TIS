from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os

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

# ---------------------------------------
# Include Routers
# ---------------------------------------
app.include_router(subjects.router)

# ---------------------------------------
# ROOT (Login Page)
# ---------------------------------------
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )

# ---------------------------------------
# LOGIN
# ---------------------------------------
@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    username = username.strip()
    user = auth.authenticate_user(db, username, password)

    if not user:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": "Invalid User ID or password.",
                "username": username
            },
            status_code=401
        )

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="user_id",
        value=user.user_id,
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
    return response


# ---------------------------------------
# DASHBOARD
# ---------------------------------------
@app.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return RedirectResponse(url="/")

    user = db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()

    if not user:
        return RedirectResponse(url="/")

    branch = db.query(models.Branch).filter(
        models.Branch.id == user.branch_id
    ).first()

    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == user.academic_year_id
    ).first()

    branch_name = branch.name if branch else "Not assigned"
    academic_year_name = (
        academic_year.year_name if academic_year else "Not assigned"
    )
    subjects_query = db.query(models.Subject).filter(
        models.Subject.branch_id == user.branch_id,
        models.Subject.academic_year_id == user.academic_year_id
    )
    teachers_query = db.query(models.Teacher).filter(
        models.Teacher.branch_id == user.branch_id,
        models.Teacher.academic_year_id == user.academic_year_id
    )
    subject_count = subjects_query.count()
    teacher_count = teachers_query.count()
    subjects_preview = subjects_query.order_by(
        models.Subject.id.desc()
    ).limit(8).all()
    teachers_preview = teachers_query.order_by(
        models.Teacher.id.desc()
    ).limit(8).all()

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
            "teachers_preview": teachers_preview
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

        if existing_user.branch_id != branch.id:
            existing_user.branch_id = branch.id
            updated = True

        if existing_user.academic_year_id != academic_year.id:
            existing_user.academic_year_id = academic_year.id
            updated = True

        if not existing_user.is_active:
            existing_user.is_active = True
            updated = True

        if updated:
            db.commit()

    db.close()
