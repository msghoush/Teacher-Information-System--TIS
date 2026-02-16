from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
import auth

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Teacher Information System")
templates = Jinja2Templates(directory="templates")


# -----------------------------
# Database Dependency
# -----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------
# Home Page
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


# -----------------------------
# Login
# -----------------------------
@app.post("/login")
def login(request: Request,
          username: str = Form(...),
          password: str = Form(...),
          db: Session = Depends(get_db)):

    user = auth.authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Invalid credentials"}
        )

    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="user_id", value=user.user_id)
    return response


# -----------------------------
# Dashboard
# -----------------------------
@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):

    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")

    user = db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()

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


# -----------------------------
# Subjects Page (GET)
# -----------------------------
@app.get("/subjects")
def subjects_page(request: Request, db: Session = Depends(get_db)):

    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")

    user = db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == user.branch_id,
        models.Subject.academic_year_id == user.academic_year_id
    ).all()

    return templates.TemplateResponse(
        "subjects.html",
        {
            "request": request,
            "subjects": subjects
        }
    )


# -----------------------------
# Add Subject (POST)
# -----------------------------
@app.post("/subjects")
def add_subject(request: Request,
                subject_code: str = Form(...),
                subject_name: str = Form(...),
                weekly_hours: int = Form(...),
                grade: int = Form(...),
                db: Session = Depends(get_db)):

    user_id = request.cookies.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")

    user = db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()

    new_subject = models.Subject(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=weekly_hours,
        grade=grade,
        branch_id=user.branch_id,
        academic_year_id=user.academic_year_id
    )

    db.add(new_subject)
    db.commit()

    return RedirectResponse(url="/subjects", status_code=302)