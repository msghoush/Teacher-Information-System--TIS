import os, uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from enum import Enum
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserRole(str, Enum):
    admin = "Admin"
    supervisor = "Supervisor"
    teacher = "Teacher"

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String); branch = Column(String); role = Column(String); status = Column(String, default="Active")

class BranchInfrastructureDB(Base):
    __tablename__ = "branch_infrastructure"
    id = Column(Integer, primary_key=True)
    branch_name = Column(String); grade_level = Column(String); current_sections = Column(Integer, default=0)

class SubjectDB(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    subject_name = Column(String); subject_code = Column(String, unique=True); weekly_hours = Column(Integer); level = Column(String)

Base.metadata.create_all(bind=engine)

class UserCreate(BaseModel):
    id: int; name: str; branch: str; role: UserRole
class SectionUpdate(BaseModel):
    branch_name: str; grade_level: str; new_sections_count: int
class SubjectCreate(BaseModel):
    subject_name: str; subject_code: str; weekly_hours: int; level: str

app = FastAPI(title="TIS")

@app.get("/")
def home(): return {"status": "Online"}

@app.post("/users/register")
def register_user(user: UserCreate):
    db = SessionLocal()
    if db.query(UserDB).filter(UserDB.id == user.id).first():
        db.close(); raise HTTPException(status_code=400, detail="Exists")
    new_user = UserDB(**user.dict()); db.add(new_user); db.commit(); db.close()
    return {"message": "Success"}

@app.get("/users/all")
def get_all_users():
    db = SessionLocal(); users = db.query(UserDB).all(); db.close(); return users

@app.post("/infrastructure/update-sections")
def update_sections(data: SectionUpdate):
    db = SessionLocal()
    infra = db.query(BranchInfrastructureDB).filter(BranchInfrastructureDB.branch_name == data.branch_name, BranchInfrastructureDB.grade_level == data.grade_level).first()
    if not infra:
        infra = BranchInfrastructureDB(branch_name=data.branch_name, grade_level=data.grade_level, current_sections=data.new_sections_count)
        db.add(infra)
    else:
        infra.current_sections = data.new_sections_count
    db.commit(); db.close()
    return {"message": "Updated"}

@app.post("/subjects/add")
def add_subject(subject: SubjectCreate):
    db = SessionLocal()
    if db.query(SubjectDB).filter(SubjectDB.subject_code == subject.subject_code).first():
        db.close(); raise HTTPException(status_code=400, detail="Code Exists")
    new_subject = SubjectDB(**subject.dict()); db.add(new_subject); db.commit(); db.close()
    return {"message": "Subject Added"}

@app.get("/subjects/all")
def get_all_subjects():
    db = SessionLocal(); subjects = db.query(SubjectDB).all(); db.close(); return subjects

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)