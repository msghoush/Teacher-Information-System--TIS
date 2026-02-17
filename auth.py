from sqlalchemy.orm import Session
from fastapi import Request, Depends
import bcrypt
import models
from dependencies import get_db


def _to_bytes(value):
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def get_password_hash(password: str):
    # bcrypt limits password input to 72 bytes. Truncate to keep startup safe.
    password_bytes = _to_bytes(password)[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password, hashed_password):
    try:
        plain_bytes = _to_bytes(plain_password)[:72]
        hashed_bytes = _to_bytes(hashed_password)
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception:
        return False


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
