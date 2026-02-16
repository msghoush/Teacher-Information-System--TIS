import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from passlib.context import CryptContext
from jose import jwt, JWTError


# =====================================================
# CONFIGURATION
# =====================================================

DATABASE_URL = "sqlite:///./tis_master.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

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
app = FastAPI()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =====================================================
# DATABASE MODELS
# =====================================================

class UserDB(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, index=True)
    first_name = Column(String)
    middle_name = Column(String)
    last_name = Column(String)
    role = Column(String)      # Admin / Branch
    branch = Column(String)
    password_hash = Column(String)


class SubjectDB(Base):
    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String)
    name = Column(String)
    hours = Column(Integer)
    grade = Column(String)


Base.metadata.create_all(bind=engine)


# =====================================================
# SCHEMAS
# =====================================================

class RegisterSchema(BaseModel):
    user_id: str
    first_name: str
    middle_name: str
    last_name: str
    role: str
    branch: str
    password: str


class LoginSchema(BaseModel):
    user_id: str
    password: str


class SubjectSchema(BaseModel):
    code: str
    name: str
    hours: int
    grade: str


# =====================================================
# DATABASE SESSION
# =====================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =====================================================
# SECURITY FUNCTIONS
# =====================================================

def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)


def create_token(user_id: str):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization token missing")

    token = authorization.split(" ")[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(UserDB).filter(UserDB.user_id == user_id).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


# =====================================================
# API ROUTES
# =====================================================

@app.post("/api/register")
def register_user(data: RegisterSchema, db: Session = Depends(get_db)):

    existing = db.query(UserDB).filter(UserDB.user_id == data.user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    new_user = UserDB(
        user_id=data.user_id,
        first_name=data.first_name,
        middle_name=data.middle_name,
        last_name=data.last_name,
        role=data.role,
        branch=data.branch,
        password_hash=hash_password(data.password)
    )

    db.add(new_user)
    db.commit()

    return {"message": "User registered successfully"}


@app.post("/api/login")
def login_user(data: LoginSchema, db: Session = Depends(get_db)):

    user = db.query(UserDB).filter(UserDB.user_id == data.user_id).first()

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(user.user_id)

    return {
        "access_token": token,
        "role": user.role,
        "branch": user.branch
    }


@app.post("/api/subjects")
def create_subject(
    subject: SubjectSchema,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):

    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    new_subject = SubjectDB(**subject.dict())
    db.add(new_subject)
    db.commit()

    return {"message": "Subject created successfully"}


@app.get("/api/subjects")
def get_subjects(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    return db.query(SubjectDB).all()


# =====================================================
# STATIC HOME PAGE
# =====================================================

@app.get("/")
async def serve_home():
    return FileResponse(os.path.join("static", "index.html"))

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# =====================================================
# RUN SERVER
# =====================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
