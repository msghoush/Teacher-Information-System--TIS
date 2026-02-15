import os, uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from enum import Enum
from typing import List, Dict
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
    subject_name = Column(String)
    grade_level = Column(String)
    weekly_hours = Column(Integer)

class TeacherDB(Base):
    __tablename__ = "teachers"
    teacher_id = Column(Integer, primary_key=True); branch = Column(String)

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

# --- 2. APP ---
app = FastAPI(title="TIS - Advanced Planning & Gap Analysis")

@app.get("/planning/detailed-gap-report/{branch}")
def get_detailed_gap(branch: BranchName):
    db = SessionLocal()
    
    # 1. ACTUAL SUPPLY PER SUBJECT
    teachers = db.query(TeacherDB).filter(TeacherDB.branch == branch).all()
    t_ids = [t.teacher_id for t in teachers]
    assignments = db.query(TeacherAssignmentDB).filter(TeacherAssignmentDB.teacher_id.in_(t_ids)).all()
    
    supply_by_subject = {} # { "Math": 40, "Science": 20 }
    for a in assignments:
        # Get subject name for better reporting
        sub = db.query(SubjectDB).filter(SubjectDB.subject_code == a.subject_code).first()
        name = sub.subject_name if sub else "Unknown"
        supply_by_subject[name] = supply_by_subject.get(name, 0) + a.hours

    # 2. FUTURE DEMAND PER SUBJECT
    infra = db.query(BranchInfrastructureDB).filter(BranchInfrastructureDB.branch_name == branch).all()
    demand_by_subject = {}

    for level in infra:
        subjects_in_grade = db.query(SubjectDB).filter(SubjectDB.grade_level == level.grade_level).all()
        for s in subjects_in_grade:
            needed = level.proposed_sections * s.weekly_hours
            demand_by_subject[s.subject_name] = demand_by_subject.get(s.subject_name, 0) + needed

    # 3. CONSTRUCT TEXT REPORT
    report = f"DETAILED SUBJECT GAP ANALYSIS: {branch.upper()}\n"
    report += "="*70 + "\n"
    report += f"{'SUBJECT NAME':<25} | {'SUPPLY':<10} | {'DEMAND':<10} | {'GAP (SHORTAGE)':<15}\n"
    report += "-"*70 + "\n"

    all_subject_names = set(list(supply_by_subject.keys()) + list(demand_by_subject.keys()))
    total_shortage = 0

    for name in sorted(all_subject_names):
        s_hours = supply_by_subject.get(name, 0)
        d_hours = demand_by_subject.get(name, 0)
        gap = d_hours - s_hours
        gap_str = f"{gap} hrs" if gap > 0 else "COVERED"
        if gap > 0: total_shortage += gap
        
        report += f"{name:<25} | {s_hours:<10} | {d_hours:<10} | {gap_str:<15}\n"

    report += "="*70 + "\n"
    report += f"TOTAL ADDITIONAL HOURS TO HIRE: {total_shortage} hrs\n"
    report += f"EQUIVALENT TO: {round(total_shortage/24, 1)} Full-Time Teachers (@24h/week)\n"
    
    db.close()
    return {"detailed_report": report}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)