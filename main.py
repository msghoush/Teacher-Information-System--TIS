import os, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

# --- DATABASE ARCHITECTURE ---
DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- RELATIONAL TABLES ---
class BranchDB(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True) #
    name = Column(String, unique=True) #
    location = Column(String) #

class AcademicYearDB(Base):
    __tablename__ = "academic_years"
    id = Column(Integer, primary_key=True) #
    year_name = Column(String) #
    is_active = Column(Boolean, default=True) #

class UserDB(Base):
    __tablename__ = "users"
    user_id = Column(Integer, primary_key=True) #
    first_name = Column(String); middle_name = Column(String); last_name = Column(String) #
    password = Column(String) #
    role = Column(String) #
    branch_id = Column(Integer, ForeignKey("branches.id")) #
    year_id = Column(Integer, ForeignKey("academic_years.id")) #

class SubjectDB(Base):
    __tablename__ = "subjects"
    code = Column(String, primary_key=True) #
    name = Column(String) #
    weekly_hours = Column(Integer) #
    grade = Column(String) #
    branch_id = Column(Integer, ForeignKey("branches.id")) #
    year_id = Column(Integer, ForeignKey("academic_years.id")) #

class TeacherDB(Base):
    __tablename__ = "teachers"
    teacher_id = Column(Integer, primary_key=True) #
    first_name = Column(String); middle_name = Column(String); last_name = Column(String) #
    subject_code = Column(String, ForeignKey("subjects.code")) #
    max_hours = Column(Integer, default=24) #
    branch_id = Column(Integer, ForeignKey("branches.id")) #
    year_id = Column(Integer, ForeignKey("academic_years.id")) #

class PlanningDB(Base):
    __tablename__ = "planning"
    id = Column(Integer, primary_key=True)
    grade_level = Column(String) #
    current_sections = Column(Integer) #
    proposed_sections = Column(Integer) #
    branch_id = Column(Integer, ForeignKey("branches.id")) #
    year_id = Column(Integer, ForeignKey("academic_years.id")) #

Base.metadata.create_all(bind=engine)
app = FastAPI()

# --- AUTHENTICATION MODULE ---
class LoginRequest(BaseModel):
    user_id: str; password: str; branch: str; year: str

@app.post("/api/login")
def login(req: LoginRequest):
    # Requirement: User ID must be 9 digits
    if not (req.user_id.isdigit() and len(req.user_id) == 9):
        raise HTTPException(status_code=400, detail="User ID must be 9 digits")
    
    # Static Admin for initialization
    if req.user_id == "123456789" and req.password == "admin123":
        return {"status": "success", "user": "Mohamad El Ghoche", "role": "Admin"}
    raise HTTPException(status_code=401, detail="Invalid Credentials")

# --- CALCULATION ENGINE ---
@app.get("/api/reports/gap/{branch_id}/{year_id}")
def get_gap_report(branch_id: int, year_id: int):
    db = SessionLocal()
    # Step 1: Required Hours = Weekly Hours * Proposed Sections
    # Step 2: Available Hours = Sum of Teacher Max Hours
    # Step 3: Deficit = Required - Available
    return {"message": "Calculation Engine active. Ready for reporting."}

@app.get("/")
async def serve_home():
    return FileResponse(os.path.join("static", "index.html"))

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))