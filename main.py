from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from database import engine
import models
from routers import subjects
from dependencies import get_db
from auth import get_password_hash
from models import User, Branch, AcademicYear
from database import SessionLocal

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Teacher Information System")

templates = Jinja2Templates(directory="templates")

# Include Routers
app.include_router(subjects.router)

# ---------------------------
# Startup Initialization
# ---------------------------
@app.on_event("startup")
def setup_initial_data():

    db = SessionLocal()

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
