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
import role_permission_service
import user_permission_service
from dependencies import get_db
from auth import get_current_user, get_password_hash
from saas import commercial_authority_service
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


def _get_user_roles_for_creator(db: Session, current_user):
    if auth.has_permission(db, current_user, "users.assign_role"):
        return [
            auth.ROLE_ADMINISTRATOR,
            auth.ROLE_EDITOR,
            auth.ROLE_USER,
            auth.ROLE_LIMITED,
        ]
    if auth.is_platform_user(current_user):
        return [auth.ROLE_LIMITED]
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
    return role_permission_service.get_allowed_permission_keys(db, role, school_group_id)


def _build_role_permission_summary_map(db: Session, current_user):
    school_group_id = _get_user_school_group_id(db, current_user)
    return {
        role: permission_registry.build_role_permission_payload(
            role,
            role_permission_service.get_allowed_permission_keys(db, role, school_group_id),
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
    if not auth.can_manage_target_user_account(db, current_user, target_user):
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


def _can_manage_user_permissions(db: Session, current_user) -> bool:
    return auth.has_permission(db, current_user, "configuration.manage_permissions")


def _build_user_permission_context(db: Session, current_user, user_row) -> dict:
    normalized_role = auth.get_effective_tenant_role(user_row)
    target_school_group_id = auth.get_user_school_group_id(db, user_row)
    payload = user_permission_service.build_user_permission_payload(
        db,
        target_user=user_row,
        normalized_role=normalized_role,
        school_group_id=target_school_group_id,
    )
    school = (
        db.query(models.SchoolGroup).filter(models.SchoolGroup.id == target_school_group_id).first()
        if target_school_group_id
        else None
    )
    branch_id = getattr(user_row, "branch_id", None)
    branch = (
        db.query(models.Branch).filter(models.Branch.id == branch_id).first()
        if branch_id
        else None
    )
    first = getattr(user_row, "first_name", "") or ""
    last = getattr(user_row, "last_name", "") or ""
    summary = {
        "name": f"{first} {last}".strip() or getattr(user_row, "user_id", "") or "",
        "login": (
            getattr(user_row, "email", None)
            or getattr(user_row, "username", None)
            or getattr(user_row, "user_id", "")
            or ""
        ),
        "role": payload.get("role") or "",
        "school": getattr(school, "name", None) or "Not assigned",
        "branch": getattr(branch, "name", None) or "Not assigned",
        "is_active": bool(auth.is_user_active(user_row)),
    }
    return {
        "can_manage_user_permissions": _can_manage_user_permissions(db, current_user),
        "user_permission_payload": payload,
        "user_permission_summary": summary,
    }


def _render_edit_user_page(
    request: Request,
    db: Session,
    current_user,
    user_row,
    error: str = "",
    success: str = "",
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

    role_choices = list(_get_user_roles_for_creator(db, current_user))
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
            "success": success,
            "detail_errors": detail_errors or [],
            "form_data": form_data,
            "user_avatar": _build_user_avatar_summary(request, user_row),
            **_build_user_permission_context(db, current_user, user_row),
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
    can_manage_users = auth.can_manage_users(db, current_user)
    can_edit_user_accounts = auth.can_edit_user_accounts(db, current_user)
    can_delete_user_accounts = auth.can_delete_user_accounts(db, current_user)
    can_delete_single_users = auth.has_permission(db, current_user, "users.delete")
    can_bulk_delete_users = auth.has_permission(db, current_user, "users.bulk_delete")
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
            "role_choices": _get_user_roles_for_creator(db, current_user),
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
            "can_delete_single_users": can_delete_single_users,
            "can_bulk_delete_users": can_bulk_delete_users,
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

    if not auth.can_manage_users(db, current_user):
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

    if not auth.can_manage_users(db, current_user):
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

    allowed_roles = _get_user_roles_for_creator(db, current_user)
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
    selected_school_group_id = (
        auth.get_branch_school_group_id(db, branch_id)
        if branch_id in allowed_branch_ids
        else None
    )
    if not errors and selected_school_group_id:
        try:
            commercial_authority_service.require_capacity_change(
                db,
                selected_school_group_id,
                staff_user_delta=1,
            )
        except commercial_authority_service.CapacityAuthorityError as exc:
            db.rollback()
            errors.append(str(exc))

    duplicate_user_id = db.query(models.User).filter(
        or_(
            models.User.user_id == user_id,
            models.User.username == user_id
        )
    ).first()
    if duplicate_user_id:
        errors.append("User ID already exists.")

    email_error = auth.get_email_registration_error(db, email)
    if email_error:
        errors.append(email_error)

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

    if not auth.can_manage_users(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_edit_user_accounts(db, current_user):
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

    if not auth.can_manage_users(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_edit_user_accounts(db, current_user):
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
    target_group_id = auth.get_user_school_group_id(db, user_row)
    exact_permissions = {
        "profile": auth.has_permission(db, current_user, "users.edit_profile", school_group_id=target_group_id),
        "position": auth.has_permission(db, current_user, "users.assign_position", school_group_id=target_group_id),
        "role": auth.has_permission(db, current_user, "users.assign_role", school_group_id=target_group_id),
        "branch": auth.has_permission(db, current_user, "users.assign_branch", school_group_id=target_group_id),
        "active": auth.has_permission(db, current_user, "users.activate_deactivate", school_group_id=target_group_id),
        "password": auth.has_permission(db, current_user, "users.reset_password", school_group_id=target_group_id),
    }
    if not exact_permissions["profile"] and (
        user_id != str(user_row.user_id or user_row.username or "")
        or email_normalized != str(user_row.email_normalized or "")
        or first_name != str(user_row.first_name or "")
        or last_name != str(user_row.last_name or "")
    ):
        errors.append("You do not have permission to edit user profile details.")
    if not exact_permissions["position"] and position != str(user_row.position or ""):
        errors.append("You do not have permission to assign positions.")
    if not exact_permissions["role"] and role != auth.normalize_role(user_row.role):
        errors.append("You do not have permission to assign roles.")
    if not exact_permissions["branch"] and (
        access_scope != auth.get_access_scope(user_row) or branch_id != user_row.branch_id
    ):
        errors.append("You do not have permission to assign access scope or branches.")
    if not exact_permissions["active"] and parsed_is_active is not None and parsed_is_active != bool(user_row.is_active):
        errors.append("You do not have permission to activate or deactivate users.")
    if password and not exact_permissions["password"]:
        errors.append("You do not have permission to reset passwords.")
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

    allowed_roles = _get_user_roles_for_creator(db, current_user)
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
    selected_school_group_id = (
        auth.get_branch_school_group_id(db, branch_id)
        if branch_id in allowed_branch_ids
        else None
    )
    old_group_id = int(getattr(user_row, "school_group_id", 0) or 0)
    old_consumes_capacity = bool(
        user_row.is_active
        and auth.normalize_user_type(getattr(user_row, "user_type", ""))
        == auth.USER_TYPE_TENANT
        and old_group_id
    )
    new_consumes_capacity = bool(parsed_is_active is True and selected_school_group_id)
    capacity_increases_target = bool(
        new_consumes_capacity
        and (not old_consumes_capacity or old_group_id != int(selected_school_group_id))
    )
    if not errors and capacity_increases_target:
        try:
            commercial_authority_service.lock_school_groups(
                db,
                {
                    group_id
                    for group_id in (old_group_id, selected_school_group_id)
                    if group_id
                },
            )
            commercial_authority_service.require_capacity_change(
                db,
                selected_school_group_id,
                lock=False,
                staff_user_delta=1,
            )
        except commercial_authority_service.CapacityAuthorityError as exc:
            db.rollback()
            errors.append(str(exc))

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

    email_error = auth.get_email_registration_error(
        db,
        email,
        exclude_user_pk=user_row.id,
    )
    if email_error:
        errors.append(email_error)

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


@router.post("/permissions/{user_pk}")
def update_user_permissions(
    request: Request,
    user_pk: int,
    permission_keys: list[str] = Form([]),
    permission_decisions: list[str] = Form([]),
    change: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Persist per-user permission exceptions for one target user.

    The User Exceptions panel submits a single ``change`` value of
    ``"<permission_key>|<allow|deny|reset>"`` (reset maps to the service's
    internal ``inherit`` deletion primitive). When ``change`` is absent the
    legacy paired lists below are applied unchanged.

    ``permission_keys`` and ``permission_decisions`` are parallel lists (the
    edit-user template renders one hidden key + one decision control per
    permission, in matching order). The acting admin's own active
    SchoolGroup is used as the override scope -- never a client-supplied
    school_group_id -- and ``_get_user_for_management`` re-verifies the
    target user is inside the acting admin's tenant boundary before any
    write is attempted.
    """
    current_user = get_current_user(request, db)
    if not current_user:
        return RedirectResponse(url="/")

    if not auth.can_manage_users(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not _can_manage_user_permissions(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    user_row = _get_user_for_management(db, current_user, user_pk)
    if not user_row:
        return _render_users_page(
            request=request,
            db=db,
            current_user=current_user,
            error="User not found or access denied.",
        )

    if auth.is_platform_user(current_user):
        # A platform-level actor (owner/developer) has no tenant SchoolGroup
        # of their own -- and, unlike a tenant admin, is already independently
        # authorized above (can_manage_users + configuration.manage_permissions)
        # and by _can_manage_target_user/can_manage_target_user_account to
        # manage ANY tenant user's account cross-tenant, regardless of
        # whatever branch/SchoolGroup the platform actor's own session
        # happens to have selected via the ordinary branch-selector cookie.
        # The override scope must always be the already server-loaded
        # target user's own verified school_group_id in this case -- never
        # the acting platform user's own (possibly mismatched) selected
        # scope, and never any client-supplied request input -- mirroring
        # _build_user_permission_context's identical read-side resolution
        # for this same page.
        acting_school_group_id = auth.get_user_school_group_id(db, user_row)
    else:
        acting_school_group_id = _get_user_school_group_id(db, current_user)
    if not acting_school_group_id:
        return _render_edit_user_page(
            request=request,
            db=db,
            current_user=current_user,
            user_row=user_row,
            error="No school context was found for permission overrides.",
        )

    if not isinstance(change, str):
        change = None  # direct calls receive the Form() default object
    change_action = None
    change_key = None
    if change is not None:
        change_key, separator, change_action = change.rpartition("|")
        change_key = change_key.strip()
        change_action = change_action.strip().lower()
        if not separator or not change_key or change_action not in {"allow", "deny", "reset"}:
            return _render_edit_user_page(
                request=request,
                db=db,
                current_user=current_user,
                user_row=user_row,
                error="Unable to update permission overrides. Please fix the highlighted issues.",
                detail_errors=["invalid permission change"],
            )
        changes = [(change_key, "inherit" if change_action == "reset" else change_action)]
    else:
        changes = list(zip(permission_keys, permission_decisions))
    errors = []
    for permission_key, decision in changes:
        try:
            user_permission_service.apply_user_override(
                db,
                target_user=user_row,
                permission_key=permission_key,
                decision=decision,
                school_group_id=acting_school_group_id,
                updated_by_user_id=getattr(current_user, "user_id", None),
            )
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        db.rollback()
        return _render_edit_user_page(
            request=request,
            db=db,
            current_user=current_user,
            user_row=user_row,
            error="Unable to update permission overrides. Please fix the highlighted issues.",
            detail_errors=errors,
        )

    db.commit()
    display_name = f"{user_row.first_name} {user_row.last_name}".strip() or user_row.user_id
    if change_action == "reset":
        success_message = f"{change_key} reset to role settings for {display_name}."
    elif change_action:
        success_message = f"{change_key} set to {change_action.capitalize()} for {display_name}."
    else:
        success_message = f"Permission overrides updated for {display_name}."
    return _render_edit_user_page(
        request=request,
        db=db,
        current_user=current_user,
        user_row=user_row,
        success=success_message,
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

    if not auth.can_manage_users(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_edit_user_accounts(db, current_user):
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
    if parsed_is_active and not bool(user_row.is_active):
        try:
            commercial_authority_service.require_capacity_change(
                db,
                int(user_row.school_group_id),
                staff_user_delta=1,
            )
        except commercial_authority_service.CapacityAuthorityError as exc:
            db.rollback()
            return _render_users_page(
                request=request,
                db=db,
                current_user=current_user,
                error=str(exc),
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

    if not auth.can_manage_users(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_delete_user_accounts(db, current_user):
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

    if not auth.can_manage_users(db, current_user):
        return RedirectResponse(url="/dashboard", status_code=302)

    if not auth.can_delete_user_accounts(db, current_user):
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
