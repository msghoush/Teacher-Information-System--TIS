import os
from urllib.parse import quote_plus

from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models
from branding_storage import (
    BrandingStorageError,
    ORGANIZATION_LOGO_SLOTS,
    organization_asset_subpath,
    resolve_owned_logo_path,
)
from design_tokens import build_design_css, merge_design_settings
import permission_registry
from visual_design import build_visual_design_config, build_visual_design_css, rows_to_visual_settings


DEFAULT_SCHOOL_LOGO_SLOTS = ORGANIZATION_LOGO_SLOTS


def _logo_payload(
    request,
    *,
    school_group_id: int,
    branch_id: int | None,
    slot_key: str,
    label: str,
    image_path: str,
    class_name: str,
    sort_order: int,
    source: str,
    recommendation: str,
) -> dict:
    normalized_path = str(image_path or "").replace("\\", "/").lstrip("/")
    url = ""
    absolute_path = ""
    if normalized_path:
        logo_branch_id = branch_id if source == "branch" else None
        try:
            resolved_path = resolve_owned_logo_path(
                normalized_path,
                school_group_id=school_group_id,
                branch_id=logo_branch_id,
                allow_legacy=True,
                require_file=True,
            )
            absolute_path = str(resolved_path)
            try:
                asset_path = organization_asset_subpath(
                    school_group_id,
                    normalized_path,
                )
                url = str(
                    request.url_for(
                        "organization_asset",
                        school_group_id=str(school_group_id),
                        asset_path=asset_path,
                    )
                )
            except BrandingStorageError:
                normalized_path = ""
                absolute_path = ""
        except (BrandingStorageError, FileNotFoundError):
            normalized_path = ""
    return {
        "slot_key": slot_key,
        "label": label,
        "path": normalized_path,
        "url": url,
        "absolute_path": absolute_path,
        "class_name": class_name,
        "is_configured": bool(normalized_path and url),
        "is_default": False,
        "source": source,
        "sort_order": sort_order,
        "recommendation": recommendation,
    }


def get_school_logo_slots(
    request,
    db: Session,
    branch_id: int | None,
    school_group_id: int | None = None,
    *,
    include_empty: bool = False,
    include_all_slots: bool = False,
) -> list[dict]:
    configured_by_slot = {}
    group_configured_by_slot = {}
    resolved_group_id = school_group_id
    if branch_id:
        try:
            branch = db.query(models.Branch).filter(models.Branch.id == int(branch_id)).first()
            if branch:
                resolved_group_id = getattr(branch, "school_group_id", None)
                configured_rows = db.query(models.BranchLogo).filter(
                    models.BranchLogo.branch_id == int(branch.id)
                ).all()
                configured_by_slot = {
                    str(row.slot_key or "").strip(): row
                    for row in configured_rows
                    if str(row.slot_key or "").strip()
                }
        except Exception:
            configured_by_slot = {}
    if resolved_group_id:
        try:
            group_rows = db.query(models.SchoolGroupLogo).filter(
                models.SchoolGroupLogo.school_group_id == int(resolved_group_id)
            ).all()
            group_configured_by_slot = {
                str(row.slot_key or "").strip(): row
                for row in group_rows
                if str(row.slot_key or "").strip()
            }
        except Exception:
            group_configured_by_slot = {}

    logos = []
    for default_slot in DEFAULT_SCHOOL_LOGO_SLOTS:
        if not include_all_slots and not default_slot["show_in_brand_strip"]:
            continue
        slot_key = default_slot["slot_key"]
        configured = configured_by_slot.get(slot_key)
        group_configured = group_configured_by_slot.get(slot_key)
        source = "branch" if configured else "school_group" if group_configured else "none"
        row = configured or group_configured
        image_path = str(getattr(row, "image_path", "") or "").replace("\\", "/").lstrip("/")
        label = str(getattr(row, "label", "") or "").strip() or default_slot["label"]
        if not row and not include_empty:
            continue
        if not resolved_group_id:
            continue
        logos.append(
            _logo_payload(
                request,
                school_group_id=int(resolved_group_id),
                branch_id=int(branch_id) if branch_id else None,
                slot_key=slot_key,
                label=label,
                image_path=image_path,
                class_name=default_slot["class_name"],
                sort_order=default_slot["sort_order"],
                source=source,
                recommendation=default_slot["recommendation"],
            )
        )
    return logos


def get_organization_identity_logo(
    request,
    db: Session,
    branch_id: int | None,
    school_group_id: int | None = None,
    *,
    background: str = "light",
    favicon: bool = False,
) -> dict | None:
    logos = get_school_logo_slots(
        request,
        db,
        branch_id,
        school_group_id,
        include_empty=False,
        include_all_slots=True,
    )
    by_slot = {logo["slot_key"]: logo for logo in logos if logo.get("is_configured")}
    if favicon:
        preferred_slots = ("favicon", "primary")
    elif str(background or "light").strip().lower() in {
        "dark",
        "navy",
        "colored",
        "gradient",
    }:
        preferred_slots = ("light", "primary", "dark")
    else:
        preferred_slots = ("dark", "primary", "light")
    return next((by_slot.get(slot) for slot in preferred_slots if by_slot.get(slot)), None)


def _build_user_initials(first_name: str = "", last_name: str = "", fallback_name: str = "") -> str:
    first = str(first_name or "").strip()
    last = str(last_name or "").strip()
    if first and last:
        return f"{first[:1]}{last[:1]}".upper()
    if first:
        return first[:1].upper()
    if last:
        return last[:1].upper()

    name_text = str(fallback_name or "").strip()
    if name_text:
        parts = [part for part in name_text.split() if part]
        if len(parts) >= 2:
            return f"{parts[0][:1]}{parts[1][:1]}".upper()
        return parts[0][:2].upper()
    return "U"


def build_user_avatar_payload(request, user_row) -> dict:
    profile_image_path = str(getattr(user_row, "profile_image_path", "") or "").strip()
    normalized_profile_image_path = profile_image_path.replace("\\", "/").lstrip("/")
    profile_image_data = getattr(user_row, "profile_image_data", None)
    image_url = ""
    if profile_image_data:
        version_token = quote_plus(normalized_profile_image_path or f"user-{getattr(user_row, 'id', '0')}")
        image_url = f"{request.url_for('get_current_profile_photo')}?v={version_token}"
    elif normalized_profile_image_path:
        absolute_profile_image_path = os.path.join("static", *normalized_profile_image_path.split("/"))
        if os.path.exists(absolute_profile_image_path):
            image_url = str(request.url_for("static", path=normalized_profile_image_path))

    initials = _build_user_initials(
        getattr(user_row, "first_name", ""),
        getattr(user_row, "last_name", ""),
        fallback_name=f"{getattr(user_row, 'first_name', '')} {getattr(user_row, 'last_name', '')}".strip(),
    )
    return {
        "image_url": image_url,
        "initials": initials,
    }


PAGE_META = {
    "dashboard": {
        "eyebrow": "Command Center",
        "title": "Operations Dashboard",
        "intro": "Track branch activity, staffing, planning, and reporting from one visual workspace.",
        "icon": "dashboard",
    },
    "subjects": {
        "eyebrow": "Academic Catalog",
        "title": "Subjects",
        "intro": "Manage the subject library for the active branch and academic year without losing visual context.",
        "icon": "subjects",
    },
    "teachers": {
        "eyebrow": "Staffing Desk",
        "title": "Teachers",
        "intro": "Review assignments, workload capacity, and staffing decisions in one screen.",
        "icon": "teachers",
    },
    "planning": {
        "eyebrow": "Section Planning",
        "title": "Planning",
        "intro": "Shape section structure, homeroom ownership, and aligned teaching hours for the active scope.",
        "icon": "planning",
    },
    "timetable": {
        "eyebrow": "Weekly Scheduling",
        "title": "Timetable",
        "intro": "Place section lessons into the weekly school grid using the current planning and timetable settings.",
        "icon": "timetable",
    },
    "academic-calendar": {
        "eyebrow": "Academic Calendar",
        "title": "Academic Calendar",
        "intro": "Plan assessments, school events, meetings, vacations, and assigned responsibilities in one scoped calendar.",
        "icon": "calendar",
    },
    "observations": {
        "eyebrow": "Teacher Growth",
        "title": "Observations",
        "intro": "Track formal and informal observations, evidence, scoring, and feedback for every teacher.",
        "icon": "clipboard-check",
    },
    "users": {
        "eyebrow": "Access Control",
        "title": "Users",
        "intro": "Manage accounts, roles, and branch ownership using the same system-wide controls.",
        "icon": "users",
    },
    "notifications": {
        "eyebrow": "Notification Center",
        "title": "Messages",
        "intro": "View messages sent to your account by administrators and system alerts.",
        "icon": "notifications",
    },
    "demo-requests": {
        "eyebrow": "Platform Leads",
        "title": "Demo Requests",
        "intro": "Review public marketing demo requests and manage platform follow-up status.",
        "icon": "message",
    },
    "platform": {
        "eyebrow": "Platform Administration",
        "title": "Platform Console",
        "intro": "Switch between organizations and branches without changing platform identity.",
        "icon": "shield",
    },
    "system-configuration": {
        "eyebrow": "Platform Controls",
        "title": "System Configuration",
        "intro": "Manage branches, academic years, and future system-level modules from one controlled workspace.",
        "icon": "settings",
    },
    "school-branding": {
        "eyebrow": "School Setup",
        "title": "School Branding",
        "intro": "Manage the logo references for your school subscription.",
        "icon": "upload",
    },
}


def _build_nav_items(
    current_path: str,
    *,
    can,
    can_any,
    new_notification_count: int = 0,
    new_demo_request_count: int = 0,
):
    def is_active(target: str) -> bool:
        if target == "/dashboard":
            return current_path == "/dashboard"
        return current_path == target or current_path.startswith(f"{target}/")

    items = []
    for item in (
        {
            "label": "Platform Console",
            "href": "/platform",
            "icon": "shield",
            "permission_keys": ("system_owner.full_access",),
        },
        {
            "label": "Dashboard",
            "href": "/dashboard",
            "icon": "dashboard",
            "permission_keys": ("dashboard.view",),
        },
        {
            "label": "Subjects",
            "href": "/subjects/",
            "icon": "subjects",
            "permission_keys": ("subjects.view",),
        },
        {
            "label": "Teachers",
            "href": "/teachers/",
            "icon": "teachers",
            "permission_keys": ("teachers.view",),
        },
        {
            "label": "Planning",
            "href": "/planning/",
            "icon": "planning",
            "permission_keys": ("planning.view",),
        },
        {
            "label": "Timetable",
            "href": "/timetable/",
            "icon": "timetable",
            "permission_keys": ("timetable.view",),
        },
        {
            "label": "Academic Calendar",
            "href": "/academic-calendar/",
            "icon": "calendar",
            "permission_keys": ("calendar.view",),
        },
        {
            "label": "Observations",
            "href": "/observations/",
            "icon": "clipboard-check",
            "permission_keys": ("observations.view",),
        },
        {
            "label": "Notification Center",
            "href": "/notifications",
            "icon": "notifications",
            "permission_keys": ("notifications.view",),
            "badge_count": new_notification_count,
        },
        {
            "label": "Demo Requests",
            "href": "/demo-requests",
            "icon": "message",
            "permission_keys": ("demo_requests.view",),
            "badge_count": new_demo_request_count,
        },
        {
            "label": "System Configuration",
            "href": "/system-configuration",
            "icon": "settings",
            "permission_keys": (
                "configuration.view",
                "schools.view",
                "branches.view",
                "academic_years.view",
                "branding.view",
                "configuration.manage_permissions",
                "configuration.manage_degrees",
                "configuration.manage_specializations",
                "timetable.manage_settings",
                "calendar.manage_event_types",
            ),
            "permission_mode": "any",
        },
    ):
        permission_mode = item.get("permission_mode", "all")
        permission_keys = tuple(item.get("permission_keys", ()))
        if permission_mode == "any":
            allowed = can_any(*permission_keys)
        else:
            allowed = all(can(permission_key) for permission_key in permission_keys)
        if not allowed:
            continue
        items.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"permission_keys", "permission_mode"}
            }
            | {"active": is_active(item["href"].rstrip("/")) if item["href"] != "/dashboard" else is_active("/dashboard")}
        )

    return items


def _get_role_permission_rows(
    db: Session,
    role: str,
    school_group_id: int | None = None,
) -> list[models.RolePermission]:
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return []

    query = db.query(models.RolePermission).filter(
        models.RolePermission.role == normalized_role
    )
    if school_group_id is None:
        query = query.filter(models.RolePermission.school_group_id.is_(None))
    else:
        query = query.filter(models.RolePermission.school_group_id == school_group_id)
    return query.all()


def _get_allowed_permission_keys(
    db: Session,
    role: str,
    school_group_id: int | None = None,
) -> set[str]:
    normalized_role = permission_registry.normalize_managed_role(role)
    if not normalized_role:
        return set()
    allowed_keys = permission_registry.get_default_permissions_for_role(normalized_role)
    try:
        permission_rows = [
            *_get_role_permission_rows(db, normalized_role, None),
            *(_get_role_permission_rows(db, normalized_role, school_group_id) if school_group_id else []),
        ]
    except Exception:
        return permission_registry.constrain_role_permissions(normalized_role, allowed_keys)

    for permission_row in permission_rows:
        if permission_row.permission_key not in permission_registry.PERMISSION_LABELS:
            continue
        if permission_row.is_allowed:
            allowed_keys.add(permission_row.permission_key)
        else:
            allowed_keys.discard(permission_row.permission_key)
    return permission_registry.constrain_role_permissions(normalized_role, allowed_keys)


def _build_permission_checker(db: Session, current_user, school_group_id: int | None = None):
    allowed_keys = auth.get_allowed_permission_keys(
        db,
        current_user,
        school_group_id=school_group_id,
    )

    def can(permission_key: str) -> bool:
        key = str(permission_key or "").strip()
        return key in allowed_keys

    return can


def build_shell_context(
    request,
    db: Session,
    current_user,
    *,
    page_key: str,
    title: str | None = None,
    eyebrow: str | None = None,
    intro: str | None = None,
    icon: str | None = None,
    notice: str = "",
):
    scoped_branch_id = getattr(current_user, "scope_branch_id", current_user.branch_id)
    scoped_academic_year_id = getattr(
        current_user,
        "scope_academic_year_id",
        current_user.academic_year_id,
    )

    branch = db.query(models.Branch).filter(
        models.Branch.id == scoped_branch_id
    ).first()
    scoped_school_group_id = (
        getattr(branch, "school_group_id", None)
        or getattr(current_user, "scope_school_group_id", None)
    )
    school_group = db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == scoped_school_group_id
    ).first() if scoped_school_group_id else None
    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == scoped_academic_year_id
    ).first()

    permission_keys = frozenset(
        auth.get_allowed_permission_keys(
            db,
            current_user,
            school_group_id=scoped_school_group_id
            or getattr(current_user, "scope_school_group_id", None)
            or auth.get_user_school_group_id(db, current_user),
        )
    )
    current_user.permission_keys = permission_keys

    def can(permission_key: str) -> bool:
        return str(permission_key or "").strip() in permission_keys

    def can_any(*permission_options: str) -> bool:
        return any(can(permission_key) for permission_key in permission_options)

    can_manage_system_settings = auth.can_manage_system_settings(current_user)
    can_manage_users = auth.can_manage_users(current_user)
    can_manage_school_branding = can_any(
        "branding.view",
        "branding.manage_school_logos",
        "branding.manage_branch_logos",
    )
    can_manage_role_permissions = can("configuration.manage_permissions")
    meta = PAGE_META.get(page_key, {})

    available_scope_branches = []
    all_years = []
    active_year_id = None
    can_switch_branches = auth.can_access_all_branches(current_user, db)
    can_switch_years = auth.can_access_all_years(current_user, db)

    if can_switch_branches:
        available_scope_branch_query = auth.get_accessible_branch_query(db, current_user)
        if scoped_school_group_id:
            available_scope_branch_query = available_scope_branch_query.filter(
                models.Branch.school_group_id == scoped_school_group_id
            )
        elif auth.get_access_scope(current_user) == auth.ACCESS_SCOPE_GLOBAL:
            available_scope_branch_query = available_scope_branch_query.filter(
                models.Branch.id == -1
            )
        available_scope_branches = available_scope_branch_query.order_by(models.Branch.name.asc()).all()
        if branch and not branch.status and available_scope_branches:
            branch = available_scope_branches[0]
    if can_switch_years:
        all_years_query = db.query(models.AcademicYear)
        if scoped_school_group_id:
            all_years_query = all_years_query.filter(
                models.AcademicYear.school_group_id == scoped_school_group_id
            )
        all_years = all_years_query.order_by(
            models.AcademicYear.year_name.desc()
        ).all()
        active_year_query = db.query(models.AcademicYear).filter(
            models.AcademicYear.is_active == True
        )
        if scoped_school_group_id:
            active_year_query = active_year_query.filter(
                models.AcademicYear.school_group_id == scoped_school_group_id
            )
        active_year = active_year_query.first()
        active_year_id = active_year.id if active_year else None

    effective_role = (
        getattr(current_user, "effective_role", None)
        or auth.normalize_platform_role(getattr(current_user, "platform_role", ""))
        or getattr(current_user, "role", "")
    )
    avatar_payload = build_user_avatar_payload(request, current_user)
    profile_image_url = avatar_payload["image_url"]
    profile_initials = avatar_payload["initials"]
    resolved_notice = notice or str(request.query_params.get("notice", "")).strip()
    try:
        # Use an explicit COUNT(id) query to avoid selecting all columns.
        new_notification_count = db.query(
            func.count(models.SystemNotification.id)
        ).filter(
            models.SystemNotification.recipient_user_id == current_user.user_id,
            models.SystemNotification.status == "New",
            models.SystemNotification.recipient_archived_at.is_(None),
        ).scalar() or 0
    except Exception:
        new_notification_count = 0
    try:
        new_demo_request_count = db.query(
            func.count(models.DemoRequest.id)
        ).filter(
            models.DemoRequest.seen_at.is_(None),
        ).scalar() or 0
    except Exception:
        new_demo_request_count = 0
    try:
        design_css = build_design_css(
            merge_design_settings(db.query(models.SystemDesignSetting).all())
        )
    except Exception:
        design_css = ""
    can_use_design_studio = auth.is_platform_user(current_user) and can("design_control.manage")
    design_mode_enabled = (
        can_use_design_studio
        and str(request.query_params.get("design_mode", "") or "").strip().lower() in {"1", "true", "yes"}
    )
    try:
        visual_rows = db.query(models.VisualDesignSetting).filter(
            models.VisualDesignSetting.page_key.in_(("global", page_key)),
            models.VisualDesignSetting.is_active == True,
        ).all()
        visual_settings = rows_to_visual_settings(visual_rows)
        visual_design_css = build_visual_design_css(visual_settings)
        visual_design_config = build_visual_design_config(page_key, visual_settings)
    except Exception:
        visual_design_css = ""
        visual_design_config = build_visual_design_config(page_key, {})

    return {
        "can": _build_permission_checker(db, current_user, scoped_school_group_id),
        "shell": {
            "page_key": page_key,
            "page_title": title or meta.get("title", "Teacher Information System"),
            "page_eyebrow": eyebrow or meta.get("eyebrow", "Workspace"),
            "page_intro": intro or meta.get("intro", ""),
            "page_icon": icon or meta.get("icon", "dashboard"),
            "current_path": request.url.path,
            "nav_items": _build_nav_items(
                request.url.path,
                can=can,
                can_any=can_any,
                new_notification_count=new_notification_count,
                new_demo_request_count=new_demo_request_count,
            ),
            "user_name": f"{current_user.first_name} {current_user.last_name}".strip(),
            "role_label": effective_role,
            "user_image_url": profile_image_url,
            "user_initials": profile_initials,
            "branch_name": branch.name if branch else "Not assigned",
            "school_group_name": school_group.name if school_group else "Not assigned",
            "school_group_id": scoped_school_group_id,
            "academic_year_name": academic_year.year_name if academic_year else "Not assigned",
            "can_manage_system_settings": can_manage_system_settings,
            "can_manage_users": can_manage_users,
            "can_manage_school_branding": can_manage_school_branding,
            "can_manage_role_permissions": can_manage_role_permissions,
            "can_switch_branches": can_switch_branches,
            "can_switch_years": can_switch_years,
            "available_scope_branches": available_scope_branches,
            "all_years": all_years,
            "scoped_branch_id": scoped_branch_id,
            "scoped_academic_year_id": scoped_academic_year_id,
            "active_year_id": active_year_id,
            "notice": resolved_notice,
            "new_notification_count": new_notification_count,
            "new_demo_request_count": new_demo_request_count,
            "school_logos": get_school_logo_slots(request, db, getattr(branch, "id", scoped_branch_id)),
            "design_css": design_css,
            "visual_design_css": visual_design_css,
            "design_studio": {
                "can_use": can_use_design_studio,
                "enabled": design_mode_enabled,
                "config": visual_design_config,
            },
        },
        "permission_keys": sorted(permission_keys),
        "can": can,
        "can_any": can_any,
    }
