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
POSITION_EDUCATION_EXCELLENCE = "Education Excellence"


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


def normalize_position(position: str) -> str:
    if not position:
        return ""
    cleaned = str(position).strip()
    lowered = cleaned.lower()
    if lowered in {"education excellence", "education excelency"}:
        return POSITION_EDUCATION_EXCELLENCE
    return cleaned


def can_access_all_branches(user) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    raw_role = str(getattr(user, "role", "")).strip().lower()
    position = normalize_position(getattr(user, "position", ""))

    if role == ROLE_DEVELOPER:
        return True

    if raw_role in {"education excellence", "education excelency"}:
        return True

    return position == POSITION_EDUCATION_EXCELLENCE


def is_developer(user) -> bool:
    return normalize_role(getattr(user, "role", "")) == ROLE_DEVELOPER


def can_access_all_years(user) -> bool:
    return is_developer(user)


def can_manage_system_settings(user) -> bool:
    return is_developer(user)


def can_manage_users(user) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    return role in {ROLE_DEVELOPER, ROLE_ADMINISTRATOR}


def can_modify_data(user) -> bool:
    role = normalize_role(getattr(user, "role", ""))
    return role in {ROLE_DEVELOPER, ROLE_ADMINISTRATOR, ROLE_EDITOR, ROLE_USER}


def can_edit_data(user) -> bool:
    return is_developer(user)


def can_delete_data(user) -> bool:
    return is_developer(user)


def can_edit_user_accounts(user) -> bool:
    return is_developer(user)


def can_delete_user_accounts(user) -> bool:
    return is_developer(user)


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

    can_all_branch_scope = can_access_all_branches(user)
    active_branches = db.query(models.Branch).filter(
        models.Branch.status == True
    ).order_by(models.Branch.name.asc()).all()
    active_branch_ids = {branch.id for branch in active_branches}

    if can_all_branch_scope:
        if parsed_branch_id and parsed_branch_id in active_branch_ids:
            scoped_branch_id = parsed_branch_id
        elif user.branch_id in active_branch_ids:
            scoped_branch_id = user.branch_id
        elif active_branches:
            scoped_branch_id = active_branches[0].id
    elif parsed_branch_id and parsed_branch_id == user.branch_id:
        scoped_branch_id = parsed_branch_id

    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()

    can_all_year_scope = can_access_all_years(user)
    if can_all_year_scope and parsed_year_id:
        selected_year = db.query(models.AcademicYear).filter(
            models.AcademicYear.id == parsed_year_id
        ).first()
        if selected_year:
            scoped_academic_year_id = selected_year.id
        elif active_year:
            scoped_academic_year_id = active_year.id
    elif active_year:
        scoped_academic_year_id = active_year.id
    elif parsed_year_id:
        scoped_academic_year_id = parsed_year_id

    user.scope_branch_id = scoped_branch_id
    user.scope_academic_year_id = scoped_academic_year_id
    user.effective_role = normalize_role(user.role)
    user.effective_position = normalize_position(getattr(user, "position", ""))
    user.can_access_all_branches = can_all_branch_scope
    user.can_access_all_years = can_all_year_scope

    return user
