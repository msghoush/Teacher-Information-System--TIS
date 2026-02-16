from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
import schemas
import auth

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Teacher Information System")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("templates/index.html", "r", encoding="utf-8") as f:
        return f.read()


# 🔐 LOGIN
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = auth.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = auth.create_access_token(data={"sub": user.user_id})
    return {"access_token": access_token, "token_type": "bearer"}


# ➕ CREATE SUBJECT
@app.post("/subjects/")
def create_subject(subject: schemas.SubjectCreate, db: Session = Depends(get_db)):
    db_subject = models.Subject(**subject.dict())
    db.add(db_subject)
    db.commit()
    db.refresh(db_subject)
    return db_subject


# ➕ CREATE TEACHER
@app.post("/teachers/")
def create_teacher(teacher: schemas.TeacherCreate, db: Session = Depends(get_db)):
    db_teacher = models.Teacher(**teacher.dict())
    db.add(db_teacher)
    db.commit()
    db.refresh(db_teacher)
    return db_teacher
from auth import get_password_hash
from models import User, Branch, AcademicYear
from database import SessionLocal


@app.on_event("startup")
def setup_initial_data():
    db = SessionLocal()

    # Create Branch if not exists
    branch = db.query(Branch).filter(Branch.name == "Hamadania").first()
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
    academic_year = db.query(AcademicYear).filter(AcademicYear.year_name == "2025-2026").first()
    if not academic_year:
        academic_year = AcademicYear(
            year_name="2025-2026",
            is_active=True
        )
        db.add(academic_year)
        db.commit()
        db.refresh(academic_year)

    # Create Admin User if not exists
    existing_user = db.query(User).filter(User.user_id == "2623252018").first()
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
