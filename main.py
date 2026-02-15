import os
import re
import uvicorn
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pydantic import BaseModel, validator
from sqlalchemy import (
    create_engine, Column, Integer, String,
    ForeignKey, Boolean, DateTime
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from passlib.context import CryptContext
from jose import JWTError, jwt


# =====================================================
# CONFIGURATION
# =====================================================

DATABASE_URL = "sqlite:///./tis_master.db"

SECRET_KEY = "CHANGE_THIS_TO_A_SECURE_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# =====================================================
# DATABASE MODELS
# =====================================================

class BranchDB(Base):
    __tablename__ = "branches"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    location = Column(String)
    is_active = Column(Boolean, default=True)


class AcademicYearDB(Base):
    __tablename__ = "academic_years"

    id = Column(Integer, primary_key=True)
    year_name = Column(String, unique=True, nullable=False)
    start_date = Column(String)
    end_date = Column(String)
    is_active = Column(Boolean, default=True)


class UserDB(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)
    first_name = Column(String, nullable=False)
    middle_name = Column(String)
    last_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # Admin / BranchUser
    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SubjectDB(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    weekly_hours = Column(Integer, nullable=False)
    grade = Column(String, nullable=False)

    branch_id = Column(Integer, ForeignKey("branches.id"))
    academic_year_id = Column(Integer, ForeignKey("academic_years.id"))


# =====================================================
# CREATE TABLES
# =====================================================

Base.metadata.create_all(bind=engine)


# =====================================================
# FASTAPI APP
# =====================================================

app = FastAPI(title="Teacher Information System (TIS)")


# =====================================================
# DEPENDENCIES
# =====================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire})
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_admin(user: UserDB = Depends(get_current_user)):
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# =====================================================
# SCHEMAS
# =====================================================

class BranchCreate(BaseModel):
    name: str
    location: Optional[str]


class AcademicYearCreate(BaseModel):
    year_name: str
    start_date: str
    end_date: str


class UserCreate(BaseModel):
    user_id: str
    first_name: str
    middle_name: Optional[str]
    last_name: str
    password: str
    role: str
    branch_id: int
    academic_year_id: int

    @validator("user_id")
    def validate_id(cls, v):
        if not re.fullmatch(r"\d{8,9}", v):
            raise ValueError("User ID must be 8 or 9 digits")
        return v


class SubjectCreate(BaseModel):
    code: str
    name: str
    weekly_hours: int
    grade: str

    @validator("code")
    def validate_code(cls, v):
        if not re.fullmatch(r"[A-Z]{3}\d{3}", v):
            raise ValueError("Format must be AAA999")
        return v


# =====================================================
# AUTHENTICATION
# =====================================================

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):

    user = db.query(UserDB).filter(UserDB.user_id == form_data.username).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token_data = {
        "user_id": user.user_id,
        "branch_id": user.branch_id,
        "academic_year_id": user.academic_year_id,
        "role": user.role
    }

    access_token = create_access_token(token_data)

    return {"access_token": access_token, "token_type": "bearer"}


# =====================================================
# ADMIN ROUTES
# =====================================================

@app.post("/admin/branches")
def create_branch(data: BranchCreate, db: Session = Depends(get_db), admin=Depends(require_admin)):
    branch = BranchDB(**data.dict())
    db.add(branch)
    db.commit()
    return {"message": "Branch created"}


@app.post("/admin/academic-years")
def create_year(data: AcademicYearCreate, db: Session = Depends(get_db), admin=Depends(require_admin)):
    year = AcademicYearDB(**data.dict())
    db.add(year)
    db.commit()
    return {"message": "Academic Year created"}


@app.post("/admin/users")
def create_user(data: UserCreate, db: Session = Depends(get_db), admin=Depends(require_admin)):

    if db.query(UserDB).filter(UserDB.user_id == data.user_id).first():
        raise HTTPException(status_code=400, detail="User already exists")

    user = UserDB(
        user_id=data.user_id,
        first_name=data.first_name,
        middle_name=data.middle_name,
        last_name=data.last_name,
        password_hash=hash_password(data.password),
        role=data.role,
        branch_id=data.branch_id,
        academic_year_id=data.academic_year_id
    )

    db.add(user)
    db.commit()
    return {"message": "User created successfully"}


# =====================================================
# SUBJECT ROUTES (BRANCH FILTERED)
# =====================================================

@app.post("/subjects")
def create_subject(data: SubjectCreate,
                   db: Session = Depends(get_db),
                   user: UserDB = Depends(get_current_user)):

    subject = SubjectDB(
        code=data.code,
        name=data.name,
        weekly_hours=data.weekly_hours,
        grade=data.grade,
        branch_id=user.branch_id,
        academic_year_id=user.academic_year_id
    )

    db.add(subject)
    db.commit()
    return {"message": "Subject added"}


@app.get("/subjects")
def get_subjects(db: Session = Depends(get_db),
                 user: UserDB = Depends(get_current_user)):

    if user.role == "Admin":
        return db.query(SubjectDB).all()

    return db.query(SubjectDB).filter(
        SubjectDB.branch_id == user.branch_id,
        SubjectDB.academic_year_id == user.academic_year_id
    ).all()


# =====================================================
# DEFAULT ADMIN AUTO-CREATION
# =====================================================

def create_default_admin():
    db = SessionLocal()

    if not db.query(UserDB).filter(UserDB.user_id == "99999999").first():
        admin = UserDB(
            user_id="99999999",
            first_name="System",
            middle_name="",
            last_name="Admin",
            password_hash=hash_password("admin123"),
            role="Admin",
            branch_id=None,
            academic_year_id=None
        )
        db.add(admin)
        db.commit()

    db.close()


create_default_admin()


# =====================================================
# RUN SERVER
# =====================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
