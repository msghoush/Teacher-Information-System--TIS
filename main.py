import os, uvicorn
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from passlib.context import CryptContext
from jose import JWTError, jwt

# CONFIGURATION
DATABASE_URL = "sqlite:///./tis_master.db"
SECRET_KEY = "TIS_SUPER_SECRET_KEY_2024"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
app = FastAPI()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

# DATABASE MODELS
class UserDB(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True, index=True)
    first_name = Column(String); middle_name = Column(String); last_name = Column(String)
    role = Column(String); branch = Column(String); password_hash = Column(String)

class SubjectDB(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String); name = Column(String); hours = Column(Integer); grade = Column(String)

Base.metadata.create_all(bind=engine)

# SCHEMAS
class UserCreate(BaseModel):
    user_id: str; first_name: str; middle_name: str; last_name: str; role: str; branch: str; password: str

class SubjectCreate(BaseModel):
    code: str; name: str; hours: int; grade: str

class Token(BaseModel):
    access_token: str; token_type: str

# UTILITIES
def get_db():
    db = SessionLocal(); yield db; db.close()

def hash_password(password: str): return pwd_context.hash(password)
def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
        if not user: raise HTTPException(status_code=401)
        return user
    except JWTError: raise HTTPException(status_code=401)

# API ROUTES
@app.on_event("startup")
def seed_admin():
    db = SessionLocal()
    if not db.query(UserDB).filter(UserDB.user_id == "123456789").first():
        admin = UserDB(user_id="123456789", first_name="Mohamad", middle_name="El", last_name="Ghoche",
                       role="Admin", branch="Obhur", password_hash=hash_password("admin123"))
        db.add(admin); db.commit()
    db.close()

@app.post("/api/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.user_id == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid Credentials")
    return {"access_token": create_access_token({"sub": user.user_id}), "token_type": "bearer"}

@app.get("/api/users")
def list_users(db: Session = Depends(get_db), current: UserDB = Depends(get_current_user)):
    return db.query(UserDB).all()

@app.post("/api/subjects")
def add_subject(sub: SubjectCreate, db: Session = Depends(get_db), current: UserDB = Depends(get_current_user)):
    new_s = SubjectDB(**sub.dict()); db.add(new_s); db.commit(); return {"message": "Subject Added"}

@app.get("/")
async def home(): return FileResponse("static/index.html")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)