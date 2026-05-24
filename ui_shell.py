import os
from urllib.parse import quote_plus

from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models


DEFAULT_SCHOOL_LOGO_SLOTS = (
    {
        "slot_key": "primary",
        "label": "Little Andalus International Schools",
        "path": "images/andalus-logo.png",
        "class_name": "logo-primary",
        "sort_order": 1,
    },
    {
        "slot_key": "accreditation",
        "label": "Cognia",
        "path": "images/cognia-logo.png",
        "class_name": "logo-accreditation",
        "sort_order": 2,
    },
    {
        "slot_key": "secondary",
        "label": "Andalus International Schools",
        "path": "images/andalus-logo-main.png",
        "class_name": "logo-secondary",
        "sort_order": 3,
    },
)


def _logo_payload(request, *, slot_key: str, label: str, image_path: str, class_name: str, sort_order: int, source: str) -> dict:
    normalized_path = str(image_path or "").replace("\\", "/").lstrip("/")
    return {
        "slot_key": slot_key,
        "label": label,
        "path": normalized_path,
        "url": str(request.url_for("static", path=normalized_path)),
        "class_name": class_name,
        "is_default": source == "default",
        "source": source,
        "sort_order": sort_order,
    }


def get_school_logo_slots(
    request,
    db: Session,
    branch_id: int | None,
    school_group_id: int | None = None,
) -> list[dict]:
    configured_by_slot = {}
    group_configured_by_slot = {}
    resolved_group_id = school_group_id
    if branch_id:
        try:
            branch = db.query(models.Branch).filter(models.Branch.id == int(branch_id)).first()
            if branch and not resolved_group_id:
                resolved_group_id = getattr(branch, "school_group_id", None)
            configured_rows = db.query(models.BranchLogo).filter(
                models.BranchLogo.branch_id == int(branch_id)
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
        slot_key = default_slot["slot_key"]
        configured = configured_by_slot.get(slot_key)
        group_configured = group_configured_by_slot.get(slot_key)
        source = "branch" if configured else "school_group" if group_configured else "default"
        row = configured or group_configured
        image_path = str(getattr(row, "image_path", "") or "").replace("\\", "/").lstrip("/") or default_slot["path"]
        label = str(getattr(row, "label", "") or "").strip() or default_slot["label"]
        logos.append(
            _logo_payload(
                request,
                slot_key=slot_key,
                label=label,
                image_path=image_path,
                class_name=default_slot["class_name"],
                sort_order=default_slot["sort_order"],
                source=source,
            )
        )
    return logos


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
    "system-configuration": {
        "eyebrow": "Developer Controls",
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
    can_manage_users: bool,
    can_manage_system_settings: bool,
    can_manage_school_branding: bool = False,
    can_manage_role_permissions: bool = False,
    new_notification_count: int = 0,
):
    def is_active(target: str) -> bool:
        if target == "/dashboard":
            return current_path == "/dashboard"
        return current_path == target or current_path.startswith(f"{target}/")

    items = [
        {
            "label": "Dashboard",
            "href": "/dashboard",
            "icon": "dashboard",
            "active": is_active("/dashboard"),
        },
        {
            "label": "Subjects",
            "href": "/subjects/",
            "icon": "subjects",
            "active": is_active("/subjects"),
        },
        {
            "label": "Teachers",
            "href": "/teachers/",
            "icon": "teachers",
            "active": is_active("/teachers"),
        },
        {
            "label": "Planning",
            "href": "/planning/",
            "icon": "planning",
            "active": is_active("/planning"),
        },
        {
            "label": "Timetable",
            "href": "/timetable/",
            "icon": "timetable",
            "active": is_active("/timetable"),
        },
        {
            "label": "Academic Calendar",
            "href": "/academic-calendar/",
            "icon": "calendar",
            "active": is_active("/academic-calendar"),
        },
        {
            "label": "Observations",
            "href": "/observations/",
            "icon": "clipboard-check",
            "active": is_active("/observations"),
        },
        {
            "label": "Notification Center",
            "href": "/notifications",
            "icon": "notifications",
            "active": is_active("/notifications"),
            "badge_count": new_notification_count,
        },
    ]

    if can_manage_system_settings:
        items.append(
            {
                "label": "System Configuration",
                "href": "/system-configuration",
                "icon": "settings",
                "active": is_active("/system-configuration"),
            }
        )
    elif can_manage_school_branding:
        items.append(
            {
                "label": "School Branding",
                "href": "/school-branding",
                "icon": "upload",
                "active": is_active("/school-branding"),
            }
        )
    if can_manage_role_permissions and not can_manage_system_settings:
        items.append(
            {
                "label": "Role Permissions",
                "href": "/system-configuration/role-permissions",
                "icon": "shield",
                "active": is_active("/system-configuration/role-permissions"),
            }
        )

    return items


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
    scoped_school_group_id = getattr(branch, "school_group_id", None)
    school_group = db.query(models.SchoolGroup).filter(
        models.SchoolGroup.id == scoped_school_group_id
    ).first() if scoped_school_group_id else None
    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == scoped_academic_year_id
    ).first()

    can_manage_system_settings = auth.can_manage_system_settings(current_user)
    can_manage_users = auth.can_manage_users(current_user)
    can_manage_school_branding = (
        can_manage_system_settings
        or auth.normalize_role(getattr(current_user, "role", "")) == auth.ROLE_ADMINISTRATOR
    )
    can_manage_role_permissions = (
        can_manage_system_settings
        or auth.normalize_role(getattr(current_user, "role", "")) == auth.ROLE_ADMINISTRATOR
    )
    meta = PAGE_META.get(page_key, {})

    available_scope_branches = []
    all_years = []
    active_year_id = None

    if can_manage_system_settings:
        available_scope_branch_query = db.query(models.Branch).filter(
            models.Branch.status == True
        )
        if scoped_school_group_id:
            available_scope_branch_query = available_scope_branch_query.filter(
                models.Branch.school_group_id == scoped_school_group_id
            )
        available_scope_branches = available_scope_branch_query.order_by(models.Branch.name.asc()).all()
        if branch and not branch.status and available_scope_branches:
            branch = available_scope_branches[0]
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

    effective_role = getattr(current_user, "effective_role", None) or getattr(current_user, "role", "")
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
        ).scalar() or 0
    except Exception:
        new_notification_count = 0

    return {
        "shell": {
            "page_key": page_key,
            "page_title": title or meta.get("title", "Teacher Information System"),
            "page_eyebrow": eyebrow or meta.get("eyebrow", "Workspace"),
            "page_intro": intro or meta.get("intro", ""),
            "page_icon": icon or meta.get("icon", "dashboard"),
            "current_path": request.url.path,
            "nav_items": _build_nav_items(
                request.url.path,
                can_manage_users,
                can_manage_system_settings,
                can_manage_school_branding,
                can_manage_role_permissions,
                new_notification_count,
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
            "available_scope_branches": available_scope_branches,
            "all_years": all_years,
            "scoped_branch_id": scoped_branch_id,
            "scoped_academic_year_id": scoped_academic_year_id,
            "active_year_id": active_year_id,
            "notice": resolved_notice,
            "new_notification_count": new_notification_count,
            "school_logos": get_school_logo_slots(request, db, getattr(branch, "id", scoped_branch_id)),
        }
    }
