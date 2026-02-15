import os, uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./tis_master.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- TABLES ---
class UserDB(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True) # 9 digits [cite: 14]
    first_name = Column(String) # [cite: 40]
    middle_name = Column(String) # [cite: 41]
    last_name = Column(String) # [cite: 42]
    role = Column(String) # Admin or Branch User [cite: 46]
    branch = Column(String) # [cite: 43]

class SubjectDB(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String) # AAA999 [cite: 75]
    name = Column(String) # [cite: 76]
    hours = Column(Integer) # [cite: 77]
    grade = Column(String) # K-12 [cite: 91]

Base.metadata.create_all(bind=engine)
app = FastAPI()

# --- SCHEMAS ---
class UserCreate(BaseModel):
    user_id: str; first_name: str; middle_name: str; last_name: str; role: str; branch: str

class SubjectCreate(BaseModel):
    code: str; name: str; hours: int; grade: str

# --- API ROUTES ---
@app.post("/api/users")
def create_user(u: UserCreate):
    db = SessionLocal()
    new_user = UserDB(**u.dict())
    db.add(new_user); db.commit(); db.close()
    return {"message": "User Created Successfully"}

@app.get("/api/users")
def get_users():
    db = SessionLocal()
    users = db.query(UserDB).all()
    db.close()
    return users

@app.post("/api/subjects")
def create_subject(s: SubjectCreate):
    db = SessionLocal()
    new_sub = SubjectDB(**s.dict())
    db.add(new_sub); db.commit(); db.close()
    return {"message": "Subject Added"}

@app.get("/")
async def serve_home():
    return FileResponse(os.path.join("static", "index.html"))

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))