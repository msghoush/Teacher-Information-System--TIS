from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

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
    user = auth.authenticate_user(db, username, password)

    if not user:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "error": "Invalid credentials"
            }
        )

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="user_id", value=user.user_id)
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

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "branch": branch,
            "academic_year": academic_year
        }
    )


# ---------------------------------------
# Startup Initialization
# ---------------------------------------
@app.on_event("startup")
def setup_initial_data():

    db = SessionLocal()

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
        User.user_id == "2623252018"
    ).first()

    if not existing_user:
        admin_user = User(
            user_id="2623252018",
            first_name="mohamad",
            last_name="El Ghoche",
            password=get_password_hash("UnderProcess1984"),
            role="Admin",
            branch_id=branch.id,
            academic_year_id=academic_year.id,
            is_active=True
        )
        db.add(admin_user)
        db.commit()

    db.close()
