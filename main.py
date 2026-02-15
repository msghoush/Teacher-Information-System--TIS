import os, uvicorn
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from passlib.context import CryptContext
from jose import JWTError, jwt

# --- CONFIGURATION ---
DATABASE_URL = "sqlite:///./tis_master.db"
SECRET_KEY = "TIS_SUPER_SECRET_2026" # Change for production
ALGORITHM = "HS256"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")
app = FastAPI()

# --- DATABASE MODELS ---
class BranchDB(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True, index=True) #
    name = Column(String, unique=True) #

class AcademicYearDB(Base):
    __tablename__ = "academic_years"
    id = Column(Integer, primary_key=True, index=True) #
    name = Column(String, unique=True) # e.g., "2025–2026"

class UserDB(Base):
    __tablename__ = "users"
    user_id = Column(String(9), primary_key=True) #
    first_name = Column(String); middle_name = Column(String); last_name = Column(String) #
    role = Column(String) # Admin / Branch User
    branch_id = Column(Integer, ForeignKey("branches.id")) #
    year_id = Column(Integer, ForeignKey("academic_years.id")) #
    password_hash = Column(String) #

class SubjectDB(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True)
    code = Column(String) # Format: AAA999
    name = Column(String) #
    hours = Column(Integer) #
    branch_id = Column(Integer, ForeignKey("branches.id")) #
    year_id = Column(Integer, ForeignKey("academic_years.id")) #

# --- SCHEMAS ---
class UserCreate(BaseModel):
    user_id: str; first_name: str; middle_name: str; last_name: str
    role: str; branch_id: int; year_id: int; password: str

class SubjectCreate(BaseModel):
    code: str; name: str; hours: int

# --- STARTUP ENGINE (SEEDING) ---
@app.on_event("startup")
def startup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # 1. Create Default Branch/Year if missing
    if not db.query(BranchDB).first():
        branch = BranchDB(name="Obhur")
        year = AcademicYearDB(name="2025–2026")
        db.add_all([branch, year]); db.commit()
        
        # 2. Create Initial Admin User
        if not db.query(UserDB).filter(UserDB.user_id == "123456789").first():
            admin = UserDB(
                user_id="123456789", first_name="Mohamad", middle_name="El", last_name="Ghoche",
                role="Admin", branch_id=branch.id, year_id=year.id,
                password_hash=pwd_context.hash("admin123")
            )
            db.add(admin); db.commit()
    db.close()

# --- API ROUTES ---
@app.post("/api/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.user_id == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid Credentials")
    
    # Include branch/year info in token for isolation
    token_data = {
        "sub": user.user_id, 
        "name": f"{user.first_name} {user.last_name}",
        "branch": user.branch_id,
        "year": user.year_id,
        "role": user.role
    }
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/register")
def register(user: UserCreate):
    db = SessionLocal()
    new_user = UserDB(
        **user.dict(exclude={'password'}),
        password_hash=pwd_context.hash(user.password)
    )
    db.add(new_user); db.commit()
    return {"message": "User created"}

@app.get("/api/users")
def get_users():
    db = SessionLocal()
    return db.query(UserDB).all()

@app.get("/")
async def home(): return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)