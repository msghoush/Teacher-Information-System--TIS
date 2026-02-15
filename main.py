import os, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles # Added for HTML
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

# --- 1. TABLES (Database) ---
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

# --- 3. APP & ROUTES ---
app = FastAPI(title="TIS - Advanced Planning System")

@app.post("/setup/add-subject", tags=["Admin Setup"])
def add_subject(sub: SubjectCreate):
    db = SessionLocal()
    new_sub = SubjectDB(**sub.dict())
    db.add(new_sub); db.commit(); db.close()
    return {"message": "Subject Added"}

@app.post("/setup/add-teacher", tags=["Admin Setup"])
def add_teacher(teacher: TeacherCreate):
    db = SessionLocal()
    new_t = TeacherDB(**teacher.dict())
    db.add(new_t); db.commit(); db.close()
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
            record.current_sections = plan.current_sections
            record.proposed_sections = plan.proposed_sections
        else:
            db.add(BranchInfrastructureDB(branch_name=data.branch_name, **plan.dict()))
    db.commit(); db.close()
    return {"message": "Planning Updated"}

@app.get("/reports/gap-analysis/{branch}", tags=["Reports"])
def get_detailed_gap(branch: BranchName):
    db = SessionLocal()
    teachers = db.query(TeacherDB).filter(TeacherDB.branch == branch).all()
    t_ids = [t.teacher_id for t in teachers]
    assignments = db.query(TeacherAssignmentDB).filter(TeacherAssignmentDB.teacher_id.in_(t_ids)).all()
    
    supply_by_subject = {}
    for a in assignments:
        sub = db.query(SubjectDB).filter(SubjectDB.subject_code == a.subject_code).first()
        name = sub.subject_name if sub else "Unknown"
        supply_by_subject[name] = supply_by_subject.get(name, 0) + a.hours

    infra = db.query(BranchInfrastructureDB).filter(BranchInfrastructureDB.branch_name == branch).all()
    demand_by_subject = {}
    for level in infra:
        subjects_in_grade = db.query(SubjectDB).filter(SubjectDB.grade_level == level.grade_level).all()
        for s in subjects_in_grade:
            needed = level.proposed_sections * s.weekly_hours
            demand_by_subject[s.subject_name] = demand_by_subject.get(s.subject_name, 0) + needed

    report = f"DETAILED SUBJECT GAP ANALYSIS: {branch.upper()}\n"
    report += "="*70 + "\n"
    report += f"{'SUBJECT NAME':<25} | {'SUPPLY':<10} | {'DEMAND':<10} | {'GAP (SHORTAGE)':<15}\n"
    report += "-"*70 + "\n"

    all_subject_names = set(list(supply_by_subject.keys()) + list(demand_by_subject.keys()))
    total_shortage = 0
    for name in sorted(all_subject_names):
        s_hours = supply_by_subject.get(name, 0); d_hours = demand_by_subject.get(name, 0)
        gap = d_hours - s_hours
        gap_str = f"{gap} hrs" if gap > 0 else "COVERED"
        if gap > 0: total_shortage += gap
        report += f"{name:<25} | {s_hours:<10} | {d_hours:<10} | {gap_str:<15}\n"

    report += "="*70 + "\n"
    report += f"TOTAL ADDITIONAL HOURS TO HIRE: {total_shortage} hrs\n"
    report += f"EQUIVALENT TO: {round(total_shortage/24, 1)} Full-Time Teachers (@24h/week)\n"
    db.close()
    return {"detailed_report": report}

# --- MOUNT HTML FRONT-END ---
# This looks for the 'static' folder you created
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)