import re
import os
from urllib.parse import quote_plus

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
import models
import permission_registry
from dependencies import get_db
from auth import get_current_user, get_password_hash
from ui_shell import build_shell_context

router = APIRouter(prefix="/users", tags=["Users"])
templates = Jinja2Templates(directory="templates")

POSITIONS = [
    "Teacher",
    "Academic Supervisor",
    "Principal",
    "Vice Principal",
    "Education Excellence",
    "Educational Specialist",
    "Academic Coach",
    "Admission Officer",
    "Management",
]

POSITION_ALIASES = {
    "Principle": "Principal",
    "Priciple": "Principal",
    "Vice Principle": "Vice Principal",
    "Education Excelency": "Education Excellence",
}

ROLE_CHOICES = [
    auth.ROLE_ADMINISTRATOR,
    auth.ROLE_EDITOR,
    auth.ROLE_USER,
    auth.ROLE_LIMITED,
]

USER_ID_PATTERN = re.compile(r"^\d{1,10}$")
NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z\s'-]*$")


def _normalize_name(value: str) -> str:
    return " ".join(part.capitalize() for part in value.strip().split())


def _normalize_user_id(value: str) -> str:
    return value.strip()


def _get_user_roles_for_creator(current_user):
    if auth.is_platform_user(current_user):
        return ROLE_CHOICES
    if auth._has_cached_permission(current_user, "users.assign_role"):
        return [
            auth.ROLE_ADMINISTRATOR,
            auth.ROLE_EDITOR,
            auth.ROLE_USER,
            auth.ROLE_LIMITED,
        ]
    return [auth.normalize_role(getattr(current_user, "role", "")) or auth.ROLE_LIMITED]


def _get_user_school_group_id(db: Session, current_user) -> int | None:
    return getattr(current_user, "scope_school_group_id", None) or auth.get_user_school_group_id(
        db,
        current_user,
    )


def _get_role_permission_rows(db: Session, role: str, school_group_id: int | None = None):
    query = db.query(models.RolePermission).filter(models.RolePermission.role == role)
    if school_group_id is None:
        query = query.filter(models.RolePermission.school_group_id.is_(None))
    else:
        query = query.filter(models.RolePermission.school_group_id == school_group_id)
    return query.all()


def _get_allowed_permission_keys(db: Session, role: str, school_group_id: int | None = None) -> set[str]:
    normalized_role = permission_registry.normalize_managed_role(role)
    allowed_keys = permission_registry.get_default_permissions_for_role(normalized_role)
    for permission_row in _get_role_permission_rows(db, normalized_role, None):
        if permission_row.permission_key in permission_registry.PERMISSION_LABELS:
            if permission_row.is_allowed:
                allowed_keys.add(permission_row.permission_key)
            else:
                allowed_keys.discard(permission_row.permission_key)
    if school_group_id:
        for permission_row in _get_role_permission_rows(db, normalized_role, school_group_id):
            if permission_row.permission_key in permission_registry.PERMISSION_LABELS:
                if permission_row.is_allowed:
                    allowed_keys.add(permission_row.permission_key)
            else:
                allowed_keys.discard(permission_row.permission_key)
    return permission_registry.constrain_role_permissions(normalized_role, allowed_keys)


def _build_role_permission_summary_map(db: Session, current_user):
    school_group_id = _get_user_school_group_id(db, current_user)
    return {
        role: permission_registry.build_role_permission_payload(
            role,
            auth.get_allowed_permission_keys(
                db,
                type("RoleSubject", (), {"role": role, "is_active": True, "school_group_id": school_group_id})(),
                school_group_id,
            ),
        )
        for role in permission_registry.MANAGED_ROLES
    }


def _get_available_branches(db: Session, current_user):
    if auth.can_access_all_branches(current_user, db):
        query = db.query(models.Branch).filter(
            models.Branch.status == True
        )
        scope_school_group_id = getattr(current_user, "scope_school_group_id", None) or _get_user_school_group_id(
            db,
            current_user,
        )
        if scope_school_group_id and not auth.is_platform_user(current_user):
            query = query.filter(models.Branch.school_group_id == scope_school_group_id)
        return query.order_by(models.Branch.name.asc()).all()

    own_branch_id = current_user.branch_id
    own_branch = db.query(models.Branch).filter(
        models.Branch.id == own_branch_id,
        models.Branch.status == True
    ).first()
    return [own_branch] if own_branch else []


def _can_manage_target_user(db: Session, current_user, target_user) -> bool:
    if not auth.can_manage_target_user_account(current_user, target_user):
        return False
    if auth.is_platform_user(current_user):
        return True
    current_group_id = getattr(current_user, "scope_school_group_id", None) or _get_user_school_group_id(
        db,
        current_user,
    )
    target_group_id = auth.get_user_school_group_id(db, target_user)
    return not current_group_id or target_group_id == current_group_id


def _get_user_for_management(db: Session, current_user, user_pk: int):
    user_row = db.query(models.User).filter(
        models.User.id == user_pk
    ).first()
    if not user_row:
        return None
    if not _can_manage_target_user(db, current_user, user_row):
        return None
    return user_row


def _parse_is_active(value: str):
    cleaned = str(value).strip().lower()
    if cleaned in {"active", "true", "1", "yes", "on"}:
        return True
    if cleaned in {"inactive", "false", "0", "no", "off"}:
        return False
    return None


def _build_user_initials(first_name: str = "", last_name: str = "") -> str:
    first = str(first_name or "").strip()
    last = str(last_name or "").strip()
    if first and last:
        return f"{first[:1]}{last[:1]}".upper()
    if first:
        return first[:1].upper()
    if last:
        return last[:1].upper()
    return "U"


def _build_user_avatar_summary(request: Request, user_row) -> dict:
    profile_image_data = getattr(user_row, "profile_image_data", None)
    has_profile_photo = bool(profile_image_data)
    profile_image_path = str(getattr(user_row, "profile_image_path", "") or "").strip()
    normalized_profile_image_path = profile_image_path.replace("\\", "/").lstrip("/")
    static_photo_url = ""
    if normalized_profile_image_path:
        absolute_profile_image_path = os.path.join(
            "static",
            *normalized_profile_image_path.split("/"),
        )
        if os.path.exists(absolute_profile_image_path):
            static_photo_url = str(request.url_for("static", path=normalized_profile_image_path))
    image_version = quote_plus(
        str(
            getattr(user_row, "profile_image_updated_at", "")
            or normalized_profile_image_path
            or f"user-{getattr(user_row, 'id', 0)}"
        )
    )
    return {
        "initials": _build_user_initials(
            getattr(user_row, "first_name", ""),
            getattr(user_row, "last_name", ""),
        ),
        "has_photo": has_profile_photo,
        "photo_url": (
            f"{request.url_for('get_user_profile_photo', user_pk=getattr(user_row, 'id', 0))}?v={image_version}"
            if has_profile_photo
            else static_photo_url
        ),
    }


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
    if "access_scope" not in form_data:
        form_data["access_scope"] = auth.get_access_scope(user_row)

    role_choices = list(_get_user_roles_for_creator(current_user))
    normalized_row_role = auth.normalize_role(getattr(user_row, "role", ""))
    selected_role = auth.normalize_role(form_data.get("role", normalized_row_role))
    if normalized_row_role and normalized_row_role not in role_choices:
        role_choices.insert(0, normalized_row_role)

    return templates.TemplateResponse(
        request,
        "edit_user.html",
        {
            "request": request,
            "user_row": user_row,
            "positions": POSITIONS,
            "role_choices": role_choices,
            "access_scope_choices": auth.TENANT_ACCESS_SCOPE_CHOICES,
            "role_permission_summary_map": _build_role_permission_summary_map(db, current_user),
            "can_set_inactive": True,
            "available_branches": _get_available_branches(db, current_user),
            "error": error,
            "detail_errors": detail_errors or [],
            "form_data": form_data,
            "user_avatar": _build_user_avatar_summary(request, user_row),
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="users",
                title="Edit User",
                eyebrow="Access Control",
                intro="Adjust account access, branch ownership, and status from the same visual admin workspace.",
                icon="users",
            ),
        },
    )


def _render_users_page(
    request: Request,
    db: Session,
    current_user,
    error: str = "",
    success: str = "",
    detail_errors=None,
    form_data=None,
):
    form_data = dict(form_data or {})
    available_branches = _get_available_branches(db, current_user)
    can_manage_users = auth.can_manage_users(current_user)
    can_edit_user_accounts = auth.can_edit_user_accounts(current_user)
    can_delete_user_accounts = auth.can_delete_user_accounts(current_user)
    users_query = db.query(models.User).filter(
        models.User.user_type != auth.USER_TYPE_PLATFORM
    )
    scope_school_group_id = getattr(current_user, "scope_school_group_id", None) or _get_user_school_group_id(
        db,
        current_user,
    )
    if auth.get_access_scope(current_user) in {
        auth.ACCESS_SCOPE_GLOBAL,
        auth.ACCESS_SCOPE_ORGANIZATION,
    }:
        if scope_school_group_id:
            users_query = auth.filter_user_query_by_school_group(db, users_query, scope_school_group_id)
        elif not auth.is_platform_user(current_user):
            users_query = users_query.filter(models.User.id == -1)
    else:
        users_query = users_query.filter(
            models.User.branch_id == getattr(current_user, "scope_branch_id", current_user.branch_id)
        )

    users = users_query.order_by(models.User.id.desc()).all()
    user_avatar_map = {
        user_row.id: _build_user_avatar_summary(request, user_row)
        for user_row in users
    }
    manageable_user_ids = set()
    if can_edit_user_accounts or can_delete_user_accounts:
        manageable_user_ids = {
            user_row.id for user_row in users
            if _can_manage_target_user(db, current_user, user_row)
        }
    branch_map = {
        branch.id: branch.name
        for branch in available_branches
    }

    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "request": request,
            "users": users,
            "user_avatar_map": user_avatar_map,
            "branch_map": branch_map,
            "positions": POSITIONS,
            "role_choices": _get_user_roles_for_creator(current_user),
            "access_scope_choices": auth.TENANT_ACCESS_SCOPE_CHOICES,
            "role_permission_summary_map": _build_role_permission_summary_map(db, current_user),
            "available_branches": available_branches,
            "error": error,
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": form_data,
            "current_user": current_user,
            "can_manage_users": can_manage_users,
            "can_edit_user_accounts": can_edit_user_accounts,
            "can_delete_user_accounts": can_delete_user_accounts,
            "manageable_user_ids": manageable_user_ids,
            **build_shell_context(
                request,
                db,
                current_user,
                page_key="users",
            ),
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

    current_user, denied_response = authorization.require_permission(
        request,
        db,
        "users.view",
        current_user=current_user,
        page_key="users",
    )
    if denied_response:
        return denied_response

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.get("/photo/{user_pk}", name="get_user_profile_photo")
def get_user_profile_photo(
    request: Request,
    user_pk: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return Response(status_code=401)

    if not auth.can_manage_users(current_user):
        return Response(status_code=403)

    user_row = _get_user_for_management(db, current_user, user_pk)
    if not user_row:
        return Response(status_code=404)

    profile_image_data = getattr(user_row, "profile_image_data", None)
    if not profile_image_data:
        return Response(status_code=404)

    content_type = str(getattr(user_row, "profile_image_content_type", "") or "").strip()
    if not content_type.startswith("image/"):
        content_type = "image/png"

    return Response(
        content=bytes(profile_image_data),
        media_type=content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("")
def create_user(
    request: Request,
    user_id: str = Form(...),
    email: str = Form(""),
    first_name: str = Form(...),
    last_name: str = Form(...),
    position: str = Form(...),
    role: str = Form(...),
    access_scope: str = Form(auth.ACCESS_SCOPE_BRANCH),
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
    email = email.strip() if isinstance(email, str) else ""
    email_normalized = auth.normalize_email(email)
    first_name = _normalize_name(first_name)
    last_name = _normalize_name(last_name)
    role = auth.normalize_role(role)
    position = POSITION_ALIASES.get(position.strip(), position.strip())
    access_scope = auth.normalize_access_scope(access_scope)
    if auth.is_organization_read_only_position(position):
        access_scope = auth.ACCESS_SCOPE_ORGANIZATION
        role = auth.ROLE_LIMITED

    errors = []
    if not USER_ID_PATTERN.match(user_id):
        errors.append("User ID (Iqama/National ID) must be numeric and up to 10 digits.")

    if email and not auth.is_valid_email(email):
        errors.append("Enter a valid email address.")

    if not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if position not in POSITIONS:
        errors.append("Invalid position selected.")

    allowed_roles = _get_user_roles_for_creator(current_user)
    if role not in allowed_roles:
        errors.append("You are not allowed to assign this role.")

    if access_scope not in auth.TENANT_ACCESS_SCOPE_CHOICES:
        errors.append("Tenant users must have ORGANIZATION or BRANCH access scope.")

    if len(password.strip()) < 8:
        errors.append("Password must be at least 8 characters.")

    available_branches = _get_available_branches(db, current_user)
    allowed_branch_ids = {branch.id for branch in available_branches if branch}
    if branch_id not in allowed_branch_ids:
        errors.append("You are not allowed to assign this branch.")

    duplicate_user_id = db.query(models.User).filter(
        or_(
            models.User.user_id == user_id,
            models.User.username == user_id
        )
    ).first()
    if duplicate_user_id:
        errors.append("User ID already exists.")

    if email_normalized and db.query(models.User).filter(
        models.User.email_normalized == email_normalized
    ).first():
        errors.append("Email address already belongs to another user.")

    if errors:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Unable to create user. Please fix the highlighted issues.",
            detail_errors=errors,
            form_data={
                "user_id": user_id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "position": position,
                "role": role,
                "access_scope": access_scope,
                "branch_id": branch_id,
            },
        )

    selected_school_group_id = auth.get_branch_school_group_id(db, branch_id)
    selected_academic_year = auth.get_academic_year_for_school_group(
        db,
        getattr(current_user, "scope_academic_year_id", None) or getattr(current_user, "academic_year_id", None),
        selected_school_group_id,
    ) or auth.get_active_academic_year_for_school_group(db, selected_school_group_id)

    new_user = models.User(
        user_id=user_id,
        username=user_id,
        email=email or None,
        email_normalized=email_normalized,
        first_name=first_name,
        last_name=last_name,
        position=position,
        role=role,
        user_type=auth.USER_TYPE_TENANT,
        platform_role=None,
        access_scope=access_scope,
        password=get_password_hash(password),
        school_group_id=selected_school_group_id,
        branch_id=branch_id,
        academic_year_id=getattr(selected_academic_year, "id", None),
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
            error="User creation failed due to a duplicate User ID or email address.",
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
    email: str = Form(""),
    first_name: str = Form(...),
    last_name: str = Form(...),
    position: str = Form(...),
    role: str = Form(...),
    access_scope: str = Form(auth.ACCESS_SCOPE_BRANCH),
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
    email = email.strip() if isinstance(email, str) else ""
    email_normalized = auth.normalize_email(email)
    first_name = _normalize_name(first_name)
    last_name = _normalize_name(last_name)
    role = auth.normalize_role(role)
    position = POSITION_ALIASES.get(position.strip(), position.strip())
    access_scope = auth.normalize_access_scope(access_scope)
    if auth.is_organization_read_only_position(position):
        access_scope = auth.ACCESS_SCOPE_ORGANIZATION
        role = auth.ROLE_LIMITED
    password = password.strip()
    parsed_is_active = _parse_is_active(is_active)

    errors = []
    if not USER_ID_PATTERN.match(user_id):
        errors.append("User ID (Iqama/National ID) must be numeric and up to 10 digits.")

    if email and not auth.is_valid_email(email):
        errors.append("Enter a valid email address.")

    if not NAME_PATTERN.match(first_name):
        errors.append("First name must contain letters only.")

    if not NAME_PATTERN.match(last_name):
        errors.append("Last name must contain letters only.")

    if position not in POSITIONS:
        errors.append("Invalid position selected.")

    allowed_roles = _get_user_roles_for_creator(current_user)
    if role not in allowed_roles:
        errors.append("You are not allowed to assign this role.")

    if access_scope not in auth.TENANT_ACCESS_SCOPE_CHOICES:
        errors.append("Tenant users must have ORGANIZATION or BRANCH access scope.")

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

    if email_normalized and db.query(models.User).filter(
        models.User.email_normalized == email_normalized,
        models.User.id != user_row.id,
    ).first():
        errors.append("Email address already belongs to another user.")

    if errors:
        form_data = {
            "user_id": user_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "role": role,
            "access_scope": access_scope,
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
    user_row.email = email or None
    user_row.email_normalized = email_normalized
    user_row.first_name = first_name
    user_row.last_name = last_name
    user_row.position = position
    user_row.role = role
    user_row.user_type = auth.USER_TYPE_TENANT
    user_row.platform_role = None
    user_row.access_scope = access_scope
    selected_school_group_id = auth.get_branch_school_group_id(db, branch_id)
    selected_academic_year = auth.get_academic_year_for_school_group(
        db,
        getattr(user_row, "academic_year_id", None),
        selected_school_group_id,
    ) or auth.get_active_academic_year_for_school_group(db, selected_school_group_id)
    user_row.school_group_id = selected_school_group_id
    user_row.branch_id = branch_id
    user_row.academic_year_id = getattr(selected_academic_year, "id", None)
    user_row.is_active = parsed_is_active

    if password:
        user_row.password = get_password_hash(password)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        form_data = {
            "user_id": user_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "role": role,
            "access_scope": access_scope,
            "branch_id": branch_id,
            "is_active": "active" if parsed_is_active else "inactive",
        }
        return _render_edit_user_page(
            request=request,
            db=db,
            current_user=current_user,
            user_row=user_row,
            error="User update failed due to a duplicate User ID or email address.",
            form_data=form_data,
        )

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"User updated successfully: {first_name} {last_name}",
    )


@router.post("/status/{user_pk}")
def update_user_status(
    request: Request,
    user_pk: int,
    is_active: str = Form(...),
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

    parsed_is_active = _parse_is_active(is_active)
    if parsed_is_active is None:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Invalid status selected.",
        )

    user_row.is_active = parsed_is_active
    db.commit()

    display_name = f"{user_row.first_name} {user_row.last_name}".strip()
    display_name = display_name or (user_row.user_id or user_row.username or "User")
    status_label = "Active" if parsed_is_active else "Inactive"
    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=f"User status updated: {display_name} is now {status_label}.",
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


@router.post("/delete-bulk")
def delete_users_bulk(
    request: Request,
    selected_user_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_delete_user_accounts(current_user):
        return RedirectResponse(url="/users", status_code=302)

    unique_user_ids = sorted({int(user_id) for user_id in selected_user_ids if user_id})
    if not unique_user_ids:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="Select at least one user to delete.",
        )

    user_rows = db.query(models.User).filter(
        models.User.id.in_(unique_user_ids)
    ).all()
    user_map = {user_row.id: user_row for user_row in user_rows}

    users_to_delete = []
    for user_id in unique_user_ids:
        target_user = user_map.get(user_id)
        if not target_user or not _can_manage_target_user(db, current_user, target_user):
            return _render_users_page(
                request=request,
                db=db,
                current_user=current_user,
                error="One or more selected users cannot be deleted due to access rules.",
            )
        if target_user.id == current_user.id:
            return _render_users_page(
                request=request,
                db=db,
                current_user=current_user,
                error="You cannot delete the account you are currently logged in with.",
            )
        users_to_delete.append(target_user)

    for target_user in users_to_delete:
        db.delete(target_user)

    db.commit()

    deleted_count = len(users_to_delete)
    success_message = (
        "User deleted successfully."
        if deleted_count == 1
        else f"{deleted_count} users deleted successfully."
    )

    return _render_users_page(
        request=request,
        db=db,
        current_user=current_user,
        success=success_message,
    )
