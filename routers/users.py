import re

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import models
from dependencies import get_db
from auth import get_current_user, get_password_hash

router = APIRouter(prefix="/users", tags=["Users"])
templates = Jinja2Templates(directory="templates")

POSITIONS = [
    "Academic Supervisor",
    "Principle",
    "Education Excelency",
]

POSITION_ALIASES = {
    "Principal": "Principle",
    "Education Excellence": "Education Excelency",
}

ROLE_CHOICES = [
    auth.ROLE_DEVELOPER,
    auth.ROLE_ADMINISTRATOR,
    auth.ROLE_USER,
    auth.ROLE_LIMITED,
]

ID_NUMBER_PATTERN = re.compile(r"^\d{6,20}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'-]*$")


def _normalize_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.strip().split())


def _get_users_scope_branch_id(current_user):
    return getattr(current_user, "scope_branch_id", current_user.branch_id)


def _get_user_roles_for_creator(current_user):
    role = auth.normalize_role(current_user.role)
    if role == auth.ROLE_DEVELOPER:
        return ROLE_CHOICES
    return [auth.ROLE_ADMINISTRATOR, auth.ROLE_USER, auth.ROLE_LIMITED]


def _get_available_branches(db: Session, current_user):
    role = auth.normalize_role(current_user.role)
    if role == auth.ROLE_DEVELOPER:
        return db.query(models.Branch).filter(
            models.Branch.status == True
        ).order_by(models.Branch.name.asc()).all()

    own_branch_id = _get_users_scope_branch_id(current_user)
    own_branch = db.query(models.Branch).filter(
        models.Branch.id == own_branch_id,
        models.Branch.status == True
    ).first()
    return [own_branch] if own_branch else []


def _render_users_page(
    request: Request,
    db: Session,
    current_user,
    error: str = "",
    success: str = "",
    detail_errors=None,
):
    available_branches = _get_available_branches(db, current_user)
    role = auth.normalize_role(current_user.role)

    users_query = db.query(models.User)
    if role != auth.ROLE_DEVELOPER:
        scope_branch_id = _get_users_scope_branch_id(current_user)
        users_query = users_query.filter(models.User.branch_id == scope_branch_id)

    users = users_query.order_by(models.User.id.desc()).all()
    branch_map = {
        branch.id: branch.name
        for branch in db.query(models.Branch).all()
    }

    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "users": users,
            "branch_map": branch_map,
            "positions": POSITIONS,
            "role_choices": _get_user_roles_for_creator(current_user),
            "available_branches": available_branches,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "current_user": current_user,
        },
    )


@router.get("")
def users_page(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post("")
def create_user(
    request: Request,
    id_number: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    position: str = Form(...),
    role: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    branch_id: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    id_number = id_number.strip()
    username = username.strip().lower()
    first_name = _normalize_name(first_name)
    last_name = _normalize_name(last_name)
    role = auth.normalize_role(role)
    position = POSITION_ALIASES.get(position.strip(), position.strip())

    errors = []
    if not ID_NUMBER_PATTERN.match(id_number):
        errors.append("ID Number must be numeric and 6-20 digits.")

    if not USERNAME_PATTERN.match(username):
        errors.append("Username must be 3-30 characters using letters, numbers, underscore, dot, or dash.")

    if not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if position not in POSITIONS:
        errors.append("Invalid position selected.")

    allowed_roles = _get_user_roles_for_creator(current_user)
    if role not in allowed_roles:
        errors.append("You are not allowed to assign this role.")

    if len(password.strip()) < 8:
        errors.append("Password must be at least 8 characters.")

    available_branches = _get_available_branches(db, current_user)
    allowed_branch_ids = {branch.id for branch in available_branches if branch}
    if branch_id not in allowed_branch_ids:
        errors.append("You are not allowed to assign this branch.")

    active_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.is_active == True
    ).first()
    if not active_year:
        errors.append("No active academic year found. Set current year first.")

    duplicate_id = db.query(models.User).filter(
        models.User.user_id == id_number
    ).first()
    if duplicate_id:
        errors.append("ID Number already exists.")

    duplicate_username = db.query(models.User).filter(
        models.User.username == username
    ).first()
    if duplicate_username:
        errors.append("Username already exists.")

    if errors:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Unable to create user. Please fix the highlighted issues.",
            detail_errors=errors,
        )

    new_user = models.User(
        user_id=id_number,
        username=username,
        first_name=first_name,
        last_name=last_name,
        position=position,
        role=role,
        password=get_password_hash(password),
        branch_id=branch_id,
        academic_year_id=active_year.id,
        is_active=True,
    )

    try:
        db.add(new_user)
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="User creation failed due to a duplicate value. Check ID Number and Username.",
        )

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"User created successfully: {first_name} {last_name}",
    )
