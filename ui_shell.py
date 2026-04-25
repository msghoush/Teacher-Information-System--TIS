import os
from urllib.parse import quote_plus

from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models


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
    "users": {
        "eyebrow": "Access Control",
        "title": "Users",
        "intro": "Manage accounts, roles, and branch ownership using the same system-wide controls.",
        "icon": "users",
    },
    "notifications": {
        "eyebrow": "Message Center",
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
}


def _build_nav_items(
    current_path: str,
    can_manage_users: bool,
    can_manage_system_settings: bool,
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
            "label": "Message Center",
            "href": "/notifications",
            "icon": "notifications",
            "active": is_active("/notifications"),
            "badge_count": new_notification_count,
        },
    ]

    if can_manage_users:
        items.append(
            {
                "label": "Users",
                "href": "/users",
                "icon": "users",
                "active": is_active("/users"),
            }
        )

    if can_manage_system_settings:
        items.append(
            {
                "label": "System Configuration",
                "href": "/system-configuration",
                "icon": "settings",
                "active": is_active("/system-configuration"),
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
    academic_year = db.query(models.AcademicYear).filter(
        models.AcademicYear.id == scoped_academic_year_id
    ).first()

    can_manage_system_settings = auth.can_manage_system_settings(current_user)
    can_manage_users = auth.can_manage_users(current_user)
    meta = PAGE_META.get(page_key, {})

    available_scope_branches = []
    all_years = []
    active_year_id = None

    if can_manage_system_settings:
        available_scope_branches = db.query(models.Branch).filter(
            models.Branch.status == True
        ).order_by(models.Branch.name.asc()).all()
        all_years = db.query(models.AcademicYear).order_by(
            models.AcademicYear.year_name.desc()
        ).all()
        active_year = db.query(models.AcademicYear).filter(
            models.AcademicYear.is_active == True
        ).first()
        active_year_id = active_year.id if active_year else None

    effective_role = getattr(current_user, "effective_role", None) or getattr(current_user, "role", "")
    profile_image_path = str(getattr(current_user, "profile_image_path", "") or "").strip()
    normalized_profile_image_path = profile_image_path.replace("\\", "/").lstrip("/")
    profile_image_data = getattr(current_user, "profile_image_data", None)
    profile_image_url = ""
    if profile_image_data:
        version_token = quote_plus(normalized_profile_image_path or f"user-{current_user.id}")
        profile_image_url = f"{request.url_for('get_current_profile_photo')}?v={version_token}"
    elif normalized_profile_image_path:
        absolute_profile_image_path = os.path.join("static", *normalized_profile_image_path.split("/"))
        if os.path.exists(absolute_profile_image_path):
            profile_image_url = str(
                request.url_for("static", path=normalized_profile_image_path)
            )
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
                new_notification_count,
            ),
            "user_name": f"{current_user.first_name} {current_user.last_name}".strip(),
            "role_label": effective_role,
            "user_image_url": profile_image_url,
            "branch_name": branch.name if branch else "Not assigned",
            "academic_year_name": academic_year.year_name if academic_year else "Not assigned",
            "can_manage_system_settings": can_manage_system_settings,
            "can_manage_users": can_manage_users,
            "available_scope_branches": available_scope_branches,
            "all_years": all_years,
            "scoped_branch_id": scoped_branch_id,
            "scoped_academic_year_id": scoped_academic_year_id,
            "active_year_id": active_year_id,
            "notice": resolved_notice,
            "new_notification_count": new_notification_count,
        }
    }
