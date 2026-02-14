import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from enum import Enum
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# --- DATABASE SETUP ---
# Use an absolute path for the database to ensure Render finds it
DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- 1. THE MODELS (TABLES) ---

class UserRole(str, Enum):
    admin = "Admin"
    supervisor = "Supervisor"
    teacher = "Teacher"

class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    branch = Column(String)
    role = Column(String)
    status = Column(String, default="Active")

class BranchInfrastructureDB(Base):
    __tablename__ = "branch_infrastructure"
    id = Column(Integer, primary_key=True)
    branch_name = Column(String)
    grade_level = Column(String)
    current_sections = Column(Integer, default=0)
    proposed_new_sections = Column(Integer, default=0)

Base.metadata.create_all(bind=engine)

# --- 2. SCHEMAS ---

class UserCreate(BaseModel):
    id: int
    name: str
    branch: str
    role: UserRole

class SectionUpdate(BaseModel):
    branch_name: str
    grade_level: str
    new_sections_count: int

# --- 3. THE APP ---
app = FastAPI(title="TIS - Unified User & Infrastructure System")

# --- 4. ROUTES ---

@app.get("/")
def home():
    return {"status": "System Online", "message": "Welcome to TIS"}

@app.post("/users/register")
def register_user(user: UserCreate):
    db = SessionLocal()
    existing = db.query(UserDB).filter(UserDB.id == user.id).first()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="ID already exists in system")
    
    new_user = UserDB(**user.dict())
    db.add(new_user)
    db.commit()
    db.close()
    return {"message": f"Successfully registered {user.name} as {user.role}"}

@app.post("/infrastructure/update-sections")
def update_sections(data: SectionUpdate):
    db = SessionLocal()
    infra = db.query(BranchInfrastructureDB).filter(
        BranchInfrastructureDB.branch_name == data.branch_name,
        BranchInfrastructureDB.grade_level == data.grade_level
    ).first()

    if not infra:
        infra = BranchInfrastructureDB(
            branch_name=data.branch_name, 
            grade_level=data.grade_level, 
            current_sections=data.new_sections_count
        )
        db.add(infra)
    else:
        infra.current_sections = data.new_sections_count
    
    db.commit()
    db.close()
    return {"message": f"Updated sections for {data.grade_level} in {data.branch_name}"}

@app.get("/users/all")
def get_all_users():
    db = SessionLocal()
    users = db.query(UserDB).all()
    db.close()
    return users

# --- 5. THE RENDER FIX ---
# This block tells the code to use the port Render provides
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)