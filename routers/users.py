import re

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
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
    "Education Excellence",
]

POSITION_ALIASES = {
    "Principal": "Principle",
    "Education Excelency": "Education Excellence",
}

ROLE_CHOICES = [
    auth.ROLE_DEVELOPER,
    auth.ROLE_ADMINISTRATOR,
    auth.ROLE_EDITOR,
    auth.ROLE_USER,
    auth.ROLE_LIMITED,
]

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'-]*$")


def _normalize_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.strip().split())


def _normalize_user_id(value: str) -> str:
    return value.strip().lower()


def _get_users_scope_branch_id(current_user):
    return getattr(current_user, "scope_branch_id", current_user.branch_id)


def _get_user_roles_for_creator(current_user):
    role = auth.normalize_role(current_user.role)
    if role == auth.ROLE_DEVELOPER:
        return ROLE_CHOICES
    if role == auth.ROLE_ADMINISTRATOR:
        return [
            auth.ROLE_ADMINISTRATOR,
            auth.ROLE_EDITOR,
            auth.ROLE_USER,
            auth.ROLE_LIMITED,
        ]
    return [auth.ROLE_EDITOR, auth.ROLE_USER, auth.ROLE_LIMITED]


def _get_available_branches(db: Session, current_user):
    role = auth.normalize_role(current_user.role)
    if role == auth.ROLE_DEVELOPER:
        return db.query(models.Branch).filter(
            models.Branch.status == True
        ).order_by(models.Branch.name.asc()).all()

    own_branch_id = current_user.branch_id
    own_branch = db.query(models.Branch).filter(
        models.Branch.id == own_branch_id,
        models.Branch.status == True
    ).first()
    return [own_branch] if own_branch else []


def _can_manage_target_user(current_user, target_user) -> bool:
    return auth.can_manage_target_user_account(current_user, target_user)


def _get_user_for_management(db: Session, current_user, user_pk: int):
    user_row = db.query(models.User).filter(
        models.User.id == user_pk
    ).first()
    if not user_row:
        return None
    if not _can_manage_target_user(current_user, user_row):
        return None
    return user_row


def _parse_is_active(value: str):
    cleaned = str(value).strip().lower()
    if cleaned in {"active", "true", "1", "yes", "on"}:
        return True
    if cleaned in {"inactive", "false", "0", "no", "off"}:
        return False
    return None


def _render_edit_user_page(
    request: Request,
    db: Session,
    current_user,
    user_row,
    error: str = "",
    detail_errors=None,
    form_data=None,
):
    form_data = dict(form_data or {})
    if "position" not in form_data and getattr(user_row, "position", None):
        form_data["position"] = POSITION_ALIASES.get(
            str(user_row.position).strip(),
            str(user_row.position).strip(),
        )

    role_choices = list(_get_user_roles_for_creator(current_user))
    normalized_row_role = auth.normalize_role(getattr(user_row, "role", ""))
    if normalized_row_role and normalized_row_role not in role_choices:
        role_choices.insert(0, normalized_row_role)

    return templates.TemplateResponse(
        "edit_user.html",
        {
            "request": request,
            "user_row": user_row,
            "positions": POSITIONS,
            "role_choices": role_choices,
            "available_branches": _get_available_branches(db, current_user),
            "error": error,
            "detail_errors": detail_errors or [],
            "form_data": form_data,
        },
    )


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
    can_manage_users = auth.can_manage_users(current_user)
    can_edit_user_accounts = auth.can_edit_user_accounts(current_user)
    scope_academic_year_id = getattr(
        current_user,
        "scope_academic_year_id",
        current_user.academic_year_id
    )

    users_query = db.query(models.User).filter(
        models.User.academic_year_id == scope_academic_year_id
    )
    if role not in {auth.ROLE_DEVELOPER, auth.ROLE_ADMINISTRATOR}:
        scope_branch_id = _get_users_scope_branch_id(current_user)
        users_query = users_query.filter(models.User.branch_id == scope_branch_id)

    users = users_query.order_by(models.User.id.desc()).all()
    manageable_user_ids = set()
    if can_edit_user_accounts:
        manageable_user_ids = {
            user_row.id for user_row in users
            if _can_manage_target_user(current_user, user_row)
        }
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
            "can_manage_users": can_manage_users,
            "can_edit_user_accounts": can_edit_user_accounts,
            "manageable_user_ids": manageable_user_ids,
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
    user_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    position: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    branch_id: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    user_id = _normalize_user_id(user_id)
    first_name = _normalize_name(first_name)
    last_name = _normalize_name(last_name)
    role = auth.normalize_role(role)
    position = POSITION_ALIASES.get(position.strip(), position.strip())

    errors = []
    if not USER_ID_PATTERN.match(user_id):
        errors.append("User ID must be 3-30 characters using letters, numbers, underscore, dot, or dash.")

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

    duplicate_user_id = db.query(models.User).filter(
        or_(
            models.User.user_id == user_id,
            models.User.username == user_id
        )
    ).first()
    if duplicate_user_id:
        errors.append("User ID already exists.")

    if errors:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Unable to create user. Please fix the highlighted issues.",
            detail_errors=errors,
        )

    new_user = models.User(
        user_id=user_id,
        username=user_id,
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
            error="User creation failed due to a duplicate value. Check User ID.",
        )

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"User created successfully: {first_name} {last_name}",
    )


@router.get("/edit/{user_pk}")
def edit_user_page(
    request: Request,
    user_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_edit_user_accounts(current_user):
        return RedirectResponse(url="/users", status_code=302)

    user_row = _get_user_for_management(db, current_user, user_pk)
    if not user_row:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="User not found or access denied.",
        )

    return _render_edit_user_page(
        request=request,
        db=db,
        current_user=current_user,
        user_row=user_row,
    )


@router.post("/edit/{user_pk}")
def update_user(
    request: Request,
    user_pk: int,
    user_id: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    position: str = Form(...),
    role: str = Form(...),
    branch_id: int = Form(...),
    is_active: str = Form("active"),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_edit_user_accounts(current_user):
        return RedirectResponse(url="/users", status_code=302)

    user_row = _get_user_for_management(db, current_user, user_pk)
    if not user_row:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="User not found or access denied.",
        )

    user_id = _normalize_user_id(user_id)
    first_name = _normalize_name(first_name)
    last_name = _normalize_name(last_name)
    role = auth.normalize_role(role)
    position = POSITION_ALIASES.get(position.strip(), position.strip())
    password = password.strip()
    parsed_is_active = _parse_is_active(is_active)

    errors = []
    if not USER_ID_PATTERN.match(user_id):
        errors.append("User ID must be 3-30 characters using letters, numbers, underscore, dot, or dash.")

    if not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if position not in POSITIONS:
        errors.append("Invalid position selected.")

    allowed_roles = _get_user_roles_for_creator(current_user)
    if role not in allowed_roles:
        errors.append("You are not allowed to assign this role.")

    available_branches = _get_available_branches(db, current_user)
    allowed_branch_ids = {branch.id for branch in available_branches if branch}
    if branch_id not in allowed_branch_ids:
        errors.append("You are not allowed to assign this branch.")

    if parsed_is_active is None:
        errors.append("Invalid status selected.")

    if password and len(password) < 8:
        errors.append("Password must be at least 8 characters.")

    duplicate_user_id = db.query(models.User).filter(
        or_(
            models.User.user_id == user_id,
            models.User.username == user_id
        ),
        models.User.id != user_row.id
    ).first()
    if duplicate_user_id:
        errors.append("User ID already exists.")

    if errors:
        form_data = {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "role": role,
            "branch_id": branch_id,
            "is_active": (
                "active"
                if parsed_is_active is True
                else "inactive"
                if parsed_is_active is False
                else str(is_active).strip().lower()
            ),
        }

        return _render_edit_user_page(
            request=request,
            db=db,
            current_user=current_user,
            user_row=user_row,
            error="Unable to update user. Please fix the highlighted issues.",
            detail_errors=errors,
            form_data=form_data,
        )

    user_row.user_id = user_id
    user_row.username = user_id
    user_row.first_name = first_name
    user_row.last_name = last_name
    user_row.position = position
    user_row.role = role
    user_row.branch_id = branch_id
    user_row.is_active = parsed_is_active

    if password:
        user_row.password = get_password_hash(password)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        form_data = {
            "user_id": user_id,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "role": role,
            "branch_id": branch_id,
            "is_active": "active" if parsed_is_active else "inactive",
        }
        return _render_edit_user_page(
            request=request,
            db=db,
            current_user=current_user,
            user_row=user_row,
            error="User update failed due to a duplicate value. Check User ID.",
            form_data=form_data,
        )

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"User updated successfully: {first_name} {last_name}",
    )


@router.get("/delete/{user_pk}")
def delete_user(
    request: Request,
    user_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_delete_user_accounts(current_user):
        return RedirectResponse(url="/users", status_code=302)

    user_row = _get_user_for_management(db, current_user, user_pk)
    if not user_row:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="User not found or access denied.",
        )

    if user_row.id == current_user.id:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="You cannot delete the account you are currently logged in with.",
        )

    deleted_name = f"{user_row.first_name} {user_row.last_name}".strip()
    db.delete(user_row)
    db.commit()

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"User deleted successfully: {deleted_name}",
    )
