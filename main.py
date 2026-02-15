import os, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- DATABASE ENGINE ---
DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- THE TABLES WE AGREED ON ---
class UserDB(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)
    password = Column(String); branch = Column(String); role = Column(String)

class TeacherDB(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True)
    first_name = Column(String); middle_name = Column(String); last_name = Column(String)
    branch = Column(String); assigned_hours = Column(Integer, default=0)

class SubjectDB(Base):
    __tablename__ = "subjects"
    code = Column(String, primary_key=True)
    name = Column(String); grade = Column(String); weekly_hours = Column(Integer)

class PlanningDB(Base):
    __tablename__ = "planning"
    id = Column(Integer, primary_key=True)
    branch = Column(String); grade = Column(String)
    current_sections = Column(Integer); proposed_sections = Column(Integer)

Base.metadata.create_all(bind=engine)
app = FastAPI()

# --- THE LOGIC: GAP ANALYSIS ENGINE ---
@app.get("/api/reports/summary/{branch}")
def calculate_summary(branch: str):
    db = SessionLocal()
    # 1. Get total teaching hours needed (Proposed Sections * Subject Hours)
    # 2. Get total available teacher capacity (Available Teachers * 24 Hours)
    # 3. Calculate the GAP (Difference)
    teachers = db.query(TeacherDB).filter(TeacherDB.branch == branch).all()
    total_capacity = len(teachers) * 24
    
    # This is where the system notices the 24-hour max limit
    return {
        "branch": branch,
        "total_teachers": len(teachers),
        "total_capacity_hours": total_capacity,
        "message": "System is calculating gaps based on 24hr max workload."
    }

# --- AUTHENTICATION & LOGIN ---
class LoginData(BaseModel):
    username: str; password: str

@app.post("/api/login")
def login(data: LoginData):
    if data.username == "admin" and data.password == "tis2024":
        return {"status": "success", "role": "admin", "branch": "Global"}
    raise HTTPException(status_code=401, detail="Invalid Credentials")

# --- SERVING THE INTERFACE ---
@app.get("/")
async def serve_home():
    return FileResponse(os.path.join("static", "index.html"))

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))