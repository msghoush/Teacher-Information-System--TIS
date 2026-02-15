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

# --- DATABASE SETUP ---
DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 1. TABLES (Full Logic - Nothing Simplified) ---
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
app = FastAPI(title="TIS Master System")

# --- 4. THE POWERFUL HOME ROUTE ---
@app.get("/")
async def serve_home():
    # We check three possible locations for the index.html
    possible_paths = [
        os.path.join(os.getcwd(), "static", "index.html"),
        "static/index.html",
        "/opt/render/project/src/static/index.html" # Specific for Render
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return FileResponse(path)
            
    return {
        "status": "API is Live",
        "error": "Dashboard HTML not found",
        "debug_info": f"Current Directory: {os.getcwd()}, Contents: {os.listdir()}"
    }

# --- 5. DATA ROUTES ---
@app.post("/setup/add-subject", tags=["Admin Setup"])
def add_subject(sub: SubjectCreate):
    db = SessionLocal()
    db.add(SubjectDB(**sub.dict())); db.commit(); db.close()
    return {"message": "Subject Added"}

@app.post("/setup/add-teacher", tags=["Admin Setup"])
def add_teacher(teacher: TeacherCreate):
    db = SessionLocal()
    db.add(TeacherDB(**teacher.dict())); db.commit(); db.close()
    return {"message": "Teacher Added"}

@app.post("/planning/update-sections", tags=["Supervisor Planning"])
def update_sections(data: BulkBranchPlan):
    db = SessionLocal()
    for plan in data.plans:
        record = db.query(BranchInfrastructureDB).filter(
            BranchInfrastructureDB.branch_name == data.branch_name,
            BranchInfrastructureDB.grade_level == plan.grade_level
        ).first()
        if record:
            record.current_sections = plan.current_sections; record.proposed_sections = plan.proposed_sections
        else:
            db.add(BranchInfrastructureDB(branch_name=data.branch_name, **plan.dict()))
    db.commit(); db.close()
    return {"message": "Sections Updated"}

@app.get("/reports/gap-analysis/{branch}", tags=["Reports"])
def get_detailed_gap(branch: BranchName):
    return {"message": f"Report for {branch} is active."}

# --- 6. STATIC MOUNT ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)