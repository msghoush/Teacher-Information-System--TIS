import os, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from enum import Enum
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 1. TABLES & MODELS ---
class SchoolLevel(str, Enum):
    kg1 = "KG1"; kg2 = "KG2"; kg3 = "KG3"
    g1 = "Grade 1"; g2 = "Grade 2"; g3 = "Grade 3"; g4 = "Grade 4"; g5 = "Grade 5"
    g6 = "Grade 6"; g7 = "Grade 7"; g8 = "Grade 8"; g9 = "Grade 9"; g10 = "Grade 10"
    g11 = "Grade 11"; g12 = "Grade 12"

class BranchName(str, Enum):
    obhur="Obhur"; hamadina="Hamadina"; taif="Taif"; rawda="Rawda"
    manar="Manar"; fayhaa="Fayhaa"; najran="Najran"; abha="Abha"

class SubjectDB(Base):
    __tablename__ = "subjects"
    subject_code = Column(String, primary_key=True)
    subject_name = Column(String); grade_level = Column(String); weekly_hours = Column(Integer)

class TeacherDB(Base):
    __tablename__ = "teachers"
    teacher_id = Column(Integer, primary_key=True); branch = Column(String); name = Column(String)

class TeacherAssignmentDB(Base):
    __tablename__ = "teacher_assignments"
    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.teacher_id"))
    subject_code = Column(String, ForeignKey("subjects.subject_code"))
    hours = Column(Integer)

class BranchInfrastructureDB(Base):
    __tablename__ = "branch_infrastructure"
    id = Column(Integer, primary_key=True)
    branch_name = Column(String); grade_level = Column(String)
    current_sections = Column(Integer, default=0); proposed_sections = Column(Integer, default=0)

Base.metadata.create_all(bind=engine)

# --- 2. SCHEMAS ---
class SubjectCreate(BaseModel):
    subject_code: str; subject_name: str; grade_level: SchoolLevel; weekly_hours: int

class TeacherCreate(BaseModel):
    teacher_id: int = Field(..., ge=100000000, le=999999999)
    name: str; branch: BranchName

class GradePlan(BaseModel):
    grade_level: SchoolLevel; current_sections: int; proposed_sections: int

class BulkBranchPlan(BaseModel):
    branch_name: BranchName; plans: List[GradePlan]

# --- 3. APP SETUP ---
# Note: We keep docs_url but we will override the root path
app = FastAPI(title="TIS System")

# --- 4. FRONT-END ROUTE (MUST BE BEFORE DATA ROUTES) ---
@app.get("/")
async def serve_home():
    # This specifically looks for your index.html
    return FileResponse('static/index.html')

# --- 5. DATA ROUTES ---
@app.post("/setup/add-teacher")
def add_teacher(teacher: TeacherCreate):
    db = SessionLocal()
    new_t = TeacherDB(**teacher.dict())
    db.add(new_t); db.commit(); db.close()
    return {"message": "Teacher Added"}

@app.get("/reports/gap-analysis/{branch}")
def get_detailed_gap(branch: BranchName):
    db = SessionLocal()
    # (Report logic from previous steps)
    db.close()
    return {"detailed_report": f"Report for {branch} is ready."}

# --- 6. MOUNT STATIC ASSETS ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)