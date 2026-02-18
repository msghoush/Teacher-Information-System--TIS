from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import Request, Depends
import bcrypt
import models
from dependencies import get_db

ROLE_DEVELOPER = "Developer"
ROLE_ADMINISTRATOR = "Administrator"
ROLE_EDITOR = "Editor"
ROLE_USER = "User"
ROLE_LIMITED = "Limited Access"


def normalize_role(role: str) -> str:
    if not role:
        return ""
    cleaned = str(role).strip()
    lowered = cleaned.lower()
    if lowered == "developer":
        return ROLE_DEVELOPER
    if lowered in {"admin", "administrator"}:
        return ROLE_ADMINISTRATOR
    if lowered == "editor":
        return ROLE_EDITOR
    if lowered == "user":
        return ROLE_USER
    if lowered in {"limited access", "limited"}:
        return ROLE_LIMITED
    return cleaned


def can_manage_users(user) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    return role in {ROLE_DEVELOPER, ROLE_ADMINISTRATOR}


def can_modify_data(user) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    return role in {ROLE_DEVELOPER, ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_USER}


def can_delete_data(user) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    return role in {ROLE_DEVELOPER, ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_USER}


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
    login_value = username.strip()
    lowered_login_value = login_value.lower()
    user = db.query(models.User).filter(
        or_(
            models.User.username == login_value,
            models.User.username == lowered_login_value,
            models.User.user_id == login_value
        )
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

    user = db.query(models.User).filter(
        models.User.user_id == user_id
    ).first()

    if not user:
        return None

    branch_cookie = request.cookies.get("branch_id")
    year_cookie = request.cookies.get("academic_year_id")

    scoped_branch_id = user.branch_id
    scoped_academic_year_id = user.academic_year_id

    try:
        parsed_branch_id = int(branch_cookie) if branch_cookie else None
    except ValueError:
        parsed_branch_id = None

    try:
        parsed_year_id = int(year_cookie) if year_cookie else None
    except ValueError:
        parsed_year_id = None

    if parsed_branch_id and parsed_branch_id == user.branch_id:
        scoped_branch_id = parsed_branch_id

    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()

    if active_year:
        if parsed_year_id:
            selected_active_year = db.query(models.AcademicYear).filter(
                models.AcademicYear.id == parsed_year_id,
                models.AcademicYear.is_active == True
            ).first()
            if selected_active_year:
                scoped_academic_year_id = selected_active_year.id
            else:
                scoped_academic_year_id = active_year.id
        else:
            scoped_academic_year_id = active_year.id
    elif parsed_year_id:
        scoped_academic_year_id = parsed_year_id

    user.scope_branch_id = scoped_branch_id
    user.scope_academic_year_id = scoped_academic_year_id
    user.effective_role = normalize_role(user.role)

    return user
