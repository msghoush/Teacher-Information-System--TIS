import os, uvicorn
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, constr
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from passlib.context import CryptContext
from jose import JWTError, jwt

# CONFIGURATION [cite: 15, 17]
DATABASE_URL = "sqlite:///./tis_master.db"
SECRET_KEY = "TIS_SUPER_SECRET_2026"
ALGORITHM = "HS256"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")
app = FastAPI()

# DATABASE MODELS [cite: 32, 56, 62, 178]
class BranchDB(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True) # e.g., Obhur [cite: 58]

class AcademicYearDB(Base):
    __tablename__ = "academic_years"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True) # e.g., 2025-2026 [cite: 64]

class UserDB(Base):
    __tablename__ = "users"
    user_id = Column(String(9), primary_key=True) # 
    full_name = Column(String)
    role = Column(String) # Admin/Branch User [cite: 46]
    branch_id = Column(Integer, ForeignKey("branches.id"))
    year_id = Column(Integer, ForeignKey("academic_years.id"))
    password_hash = Column(String)

class SubjectDB(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True)
    code = Column(String) # AAA999 format [cite: 75]
    name = Column(String)
    hours = Column(Integer)
    branch_id = Column(Integer, ForeignKey("branches.id"))
    year_id = Column(Integer, ForeignKey("academic_years.id"))

# SCHEMAS [cite: 14, 75]
class Token(BaseModel):
    access_token: str
    token_type: str

# INITIAL SEEDING [cite: 25, 186]
@app.on_event("startup")
def startup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if not db.query(BranchDB).first():
        branch = BranchDB(name="Obhur")
        year = AcademicYearDB(name="2025-2026")
        db.add_all([branch, year])
        db.commit()
        # Admin: 123456789 / admin123 [cite: 39, 45]
        admin = UserDB(
            user_id="123456789", full_name="Mohamad El Ghoche", role="Admin",
            branch_id=branch.id, year_id=year.id,
            password_hash=pwd_context.hash("admin123")
        )
        db.add(admin); db.commit()
    db.close()

# AUTHENTICATION [cite: 12, 113]
@app.post("/api/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(SessionLocal)):
    user = db.query(UserDB).filter(UserDB.user_id == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid Credentials")
    
    token_data = {"sub": user.user_id, "name": user.full_name}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/")
async def serve_home(): return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)