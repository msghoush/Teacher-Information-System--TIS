from fastapi import Request, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
import models


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return None

    return db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()
