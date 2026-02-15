import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from passlib.context import CryptContext
from jose import JWTError, jwt


# ==============================
# CONFIGURATION
# ==============================

DATABASE_URL = "sqlite:///./tis_master.db"
SECRET_KEY = os.environ.get("SECRET_KEY", "CHANGE_THIS_IN_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

app = FastAPI()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


# ==============================
# DATABASE MODELS
# ==============================

class UserDB(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, index=True)
    first_name = Column(String)
    middle_name = Column(String)
    last_name = Column(String)
    role = Column(String)  # Admin or Branch
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


# ==============================
# SCHEMAS
# ==============================

class UserCreate(BaseModel):
    user_id: str
    first_name: str
    middle_name: str
    last_name: str
    role: str
    branch: str
    password: str


class SubjectCreate(BaseModel):
    code: str
    name: str
    hours: int
    grade: str


class Token(BaseModel):
    access_token: str
    token_type: str


# ==============================
# UTILITY FUNCTIONS
# ==============================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme),
                     db: Session = Depends(get_db)):

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials"
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(UserDB).filter(UserDB.user_id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


# ==============================
# API ROUTES
# ==============================

@app.post("/api/register")
def register_user(user: UserCreate, db: Session = Depends(get_db)):

    existing = db.query(UserDB).filter(UserDB.user_id == user.user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")

    new_user = UserDB(
        user_id=user.user_id,
        first_name=user.first_name,
        middle_name=user.middle_name,
        last_name=user.last_name,
        role=user.role,
        branch=user.branch,
        password_hash=hash_password(user.password)
    )

    db.add(new_user)
    db.commit()

    return {"message": "User registered successfully"}


@app.post("/api/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(),
          db: Session = Depends(get_db)):

    user = db.query(UserDB).filter(
        UserDB.user_id == form_data.username
    ).first()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect credentials")

    access_token = create_access_token(
        data={"sub": user.user_id}
    )

    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/subjects")
def create_subject(subject: SubjectCreate,
                   db: Session = Depends(get_db),
                   current_user: UserDB = Depends(get_current_user)):

    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    new_subject = SubjectDB(**subject.dict())
    db.add(new_subject)
    db.commit()

    return {"message": "Subject added successfully"}


@app.get("/api/users")
def get_users(db: Session = Depends(get_db),
              current_user: UserDB = Depends(get_current_user)):

    if current_user.role != "Admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    return db.query(UserDB).all()


# ==============================
# STATIC FILES
# ==============================

@app.get("/")
async def serve_home():
    return FileResponse(os.path.join("static", "index.html"))

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ==============================
# RUN SERVER
# ==============================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
