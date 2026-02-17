from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Request, Depends
import models
from dependencies import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str):
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(db: Session, username: str, password: str):
    user = db.query(models.User).filter(
        models.User.user_id == username
    ).first()

    if not user:
        return None

    if not verify_password(password, user.password):
        return None

    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return None

    return db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()
