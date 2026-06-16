from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import auth
from ui_shell import build_shell_context


templates = Jinja2Templates(directory="templates")


@dataclass(frozen=True)
class PermissionRule:
    pattern: str
    methods: tuple[str, ...]
    permission_keys: tuple[str, ...]
    page_key: str
    match: str = "all"

    def matches(self, path: str, method: str) -> bool:
        normalized_method = str(method or "").upper()
        if self.methods and normalized_method not in self.methods:
            return False
        return re.fullmatch(self.pattern, path) is not None


PUBLIC_PATH_PATTERNS = (
    r"/",
    r"/login",
    r"/logout",
    r"/forgot-password",
    r"/request-demo",
    r"/favicon\.ico",
    r"/docs(?:/.*)?",
    r"/redoc(?:/.*)?",
    r"/openapi\.json",
)


PROTECTED_ROUTE_RULES = (
    PermissionRule(r"/dashboard", ("GET",), ("dashboard.view",), "dashboard"),
    PermissionRule(r"/dashboard/api/hiring-plan", ("GET",), ("hiring_plan.view",), "dashboard"),
    PermissionRule(r"/dashboard/api/hiring-plan/effective", ("GET",), ("hiring_plan.view",), "dashboard"),
    PermissionRule(r"/dashboard/api/hiring-plan/save", ("POST",), ("hiring_plan.edit",), "dashboard"),
    PermissionRule(r"/reports/allocation-plan\.pdf", ("GET",), ("reports.export",), "dashboard"),
    PermissionRule(r"/reports/allocation-plan\.xlsx", ("GET",), ("reports.export",), "dashboard"),
    PermissionRule(r"/subjects/?", ("GET",), ("subjects.view",), "subjects"),
    PermissionRule(r"/subjects/?", ("POST",), ("subjects.create",), "subjects"),
    PermissionRule(r"/subjects/export", ("GET",), ("subjects.export",), "subjects"),
    PermissionRule(r"/subjects/template", ("GET",), ("subjects.import",), "subjects"),
    PermissionRule(r"/subjects/import", ("POST",), ("subjects.import",), "subjects"),
    PermissionRule(r"/subjects/copy-from-year", ("POST",), ("subjects.copy_year_data",), "subjects"),
    PermissionRule(r"/subjects/edit/\d+", ("GET", "POST"), ("subjects.edit",), "subjects"),
    PermissionRule(r"/subjects/delete/\d+", ("GET",), ("subjects.delete",), "subjects"),
    PermissionRule(r"/subjects/delete-bulk", ("POST",), ("subjects.delete",), "subjects"),
    PermissionRule(r"/teachers/?", ("GET",), ("teachers.view",), "teachers"),
    PermissionRule(r"/teachers/?", ("POST",), ("teachers.create",), "teachers"),
    PermissionRule(r"/teachers/auto-matching-data", ("GET",), ("teachers.view",), "teachers"),
    PermissionRule(r"/teachers/copy-from-year", ("POST",), ("teachers.copy_year_data",), "teachers"),
    PermissionRule(r"/teachers/edit/\d+", ("GET", "POST"), ("teachers.edit",), "teachers"),
    PermissionRule(r"/teachers/delete/\d+", ("GET",), ("teachers.delete",), "teachers"),
    PermissionRule(r"/teachers/delete-bulk", ("POST",), ("teachers.delete",), "teachers"),
    PermissionRule(r"/planning/?", ("GET",), ("planning.view",), "planning"),
    PermissionRule(r"/planning/?", ("POST",), ("planning.create_section",), "planning"),
    PermissionRule(r"/planning/copy-from-year", ("POST",), ("planning.copy_year_data",), "planning"),
    PermissionRule(r"/planning/edit/\d+", ("GET", "POST"), ("planning.edit_section",), "planning"),
    PermissionRule(r"/planning/delete/\d+", ("GET",), ("planning.delete_section",), "planning"),
    PermissionRule(r"/timetable/?", ("GET",), ("timetable.view",), "timetable"),
    PermissionRule(r"/timetable/api/assign", ("POST",), ("timetable.edit",), "timetable"),
    PermissionRule(r"/timetable/export\.xlsx", ("GET",), ("timetable.export",), "timetable"),
    PermissionRule(r"/timetable/export\.pdf", ("GET",), ("timetable.export",), "timetable"),
    PermissionRule(r"/academic-calendar", ("GET",), ("calendar.view",), "academic-calendar"),
    PermissionRule(r"/academic-calendar/?", ("GET",), ("calendar.view",), "academic-calendar"),
    PermissionRule(r"/academic-calendar/export\.pdf", ("GET",), ("calendar.export",), "academic-calendar"),
    PermissionRule(r"/academic-calendar/events", ("POST",), ("calendar.create",), "academic-calendar"),
    PermissionRule(r"/academic-calendar/events/\d+", ("POST",), ("calendar.edit",), "academic-calendar"),
    PermissionRule(r"/academic-calendar/events/\d+/delete", ("POST",), ("calendar.delete",), "academic-calendar"),
    PermissionRule(r"/academic-calendar/events/\d+/status", ("POST",), ("calendar.edit",), "academic-calendar"),
    PermissionRule(r"/observations", ("GET",), ("observations.view",), "observations"),
    PermissionRule(r"/observations/?", ("GET",), ("observations.view",), "observations"),
    PermissionRule(
        r"/observations/?",
        ("POST",),
        ("observations.create_formal", "observations.create_non_formal"),
        "observations",
        match="any",
    ),
    PermissionRule(
        r"/observations/new",
        ("GET",),
        ("observations.create_formal", "observations.create_non_formal"),
        "observations",
        match="any",
    ),
    PermissionRule(r"/observations/teacher/\d+/history", ("GET",), ("observations.view",), "observations"),
    PermissionRule(
        r"/observations/teacher/\d+/export/pdf",
        ("GET",),
        ("observations.export_reports",),
        "observations",
    ),
    PermissionRule(r"/observations/\d+", ("GET",), ("observations.view",), "observations"),
    PermissionRule(r"/observations/\d+/edit", ("GET", "POST"), ("observations.edit_draft",), "observations"),
    PermissionRule(r"/observations/\d+/delete", ("POST",), ("observations.delete",), "observations"),
    PermissionRule(
        r"/observations/\d+/evaluatee-notes",
        ("POST",),
        ("observations.edit_draft", "observations.sign_teacher"),
        "observations",
        match="any",
    ),
    PermissionRule(
        r"/observations/\d+/self-evaluation",
        ("POST",),
        ("observations.self_evaluate",),
        "observations",
    ),
    PermissionRule(
        r"/observations/\d+/teacher-signature",
        ("POST",),
        ("observations.sign_teacher",),
        "observations",
    ),
    PermissionRule(
        r"/observations/\d+/export/pdf",
        ("GET",),
        ("observations.export_reports",),
        "observations",
    ),
    PermissionRule(r"/notifications", ("GET",), ("notifications.view",), "notifications"),
    PermissionRule(r"/notifications/compose", ("GET",), ("notifications.send_direct", "notifications.broadcast"), "notifications", match="any"),
    PermissionRule(r"/notifications/compose", ("POST",), ("notifications.send_direct", "notifications.broadcast"), "notifications", match="any"),
    PermissionRule(r"/notifications/group-action", ("POST",), ("notifications.mark_read", "notifications.resolve", "notifications.archive"), "notifications", match="any"),
    PermissionRule(r"/notifications/mark-all-read", ("POST",), ("notifications.mark_read",), "notifications"),
    PermissionRule(r"/notifications/\d+", ("GET",), ("notifications.view",), "notifications"),
    PermissionRule(r"/notifications/\d+/archive", ("POST",), ("notifications.archive",), "notifications"),
    PermissionRule(r"/notifications/\d+/resolved", ("POST",), ("notifications.resolve",), "notifications"),
    PermissionRule(r"/users", ("GET",), ("users.view",), "users"),
    PermissionRule(r"/users", ("POST",), ("users.create",), "users"),
    PermissionRule(r"/users/edit/\d+", ("GET", "POST"), ("users.edit_profile", "users.assign_position", "users.assign_role", "users.assign_branch", "users.reset_password", "users.activate_deactivate"), "users", match="any"),
    PermissionRule(r"/users/delete/\d+", ("GET",), ("users.delete",), "users"),
    PermissionRule(r"/users/delete-bulk", ("POST",), ("users.bulk_delete",), "users"),
    PermissionRule(r"/users/photo/\d+", ("GET",), ("users.view",), "users"),
    PermissionRule(r"/users/status/\d+", ("POST",), ("users.activate_deactivate",), "users"),
    PermissionRule(r"/profile/photo", ("POST",), ("users.manage_profile_photo",), "dashboard"),
    PermissionRule(r"/profile/photo/current", ("GET",), ("users.manage_profile_photo",), "dashboard"),
    PermissionRule(r"/admin/audit-log", ("GET",), ("configuration.export_audit_log",), "system-configuration"),
    PermissionRule(r"/admin/current-year", ("POST",), ("academic_years.activate",), "system-configuration"),
    PermissionRule(r"/developer/open-academic-year", ("POST",), ("academic_years.create",), "system-configuration"),
    PermissionRule(r"/demo-requests", ("GET",), ("demo_requests.view",), "demo-requests"),
    PermissionRule(r"/demo-requests/export", ("GET",), ("demo_requests.export",), "demo-requests"),
    PermissionRule(r"/demo-requests/\d+", ("GET",), ("demo_requests.view",), "demo-requests"),
    PermissionRule(r"/demo-requests/\d+/status", ("POST",), ("demo_requests.update_status",), "demo-requests"),
    PermissionRule(r"/demo-requests/\d+/delete", ("POST",), ("demo_requests.update_status",), "demo-requests"),
    PermissionRule(r"/school-branding", ("GET",), ("branding.view",), "school-branding"),
    PermissionRule(r"/system-configuration", ("GET",), ("configuration.view", "schools.view", "branches.view", "academic_years.view", "branding.view", "configuration.manage_permissions", "configuration.manage_degrees", "configuration.manage_specializations", "timetable.manage_settings", "timetable.manage_blocks", "calendar.manage_event_types"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/role-permissions", ("GET", "POST"), ("configuration.manage_permissions",), "system-configuration"),
    PermissionRule(r"/api/design-studio/config", ("GET",), ("design_control.manage",), "system-configuration"),
    PermissionRule(r"/api/design-studio/component-settings", ("POST",), ("design_control.manage",), "system-configuration"),
    PermissionRule(r"/api/design-studio/reset", ("POST",), ("design_control.manage",), "system-configuration"),
    PermissionRule(r"/api/design-studio/reset-hidden", ("POST",), ("design_control.manage",), "system-configuration"),
    PermissionRule(r"/api/design-studio/reset-all", ("POST",), ("design_control.manage",), "system-configuration"),
    PermissionRule(r"/system-configuration/logos", ("GET",), ("branding.view",), "system-configuration"),
    PermissionRule(r"/system-configuration/logos", ("POST",), ("branding.manage_school_logos", "branding.manage_branch_logos"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/logos/reset", ("POST",), ("branding.manage_school_logos", "branding.manage_branch_logos"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/schools", ("GET",), ("schools.view",), "system-configuration"),
    PermissionRule(r"/system-configuration/schools", ("POST",), ("schools.create",), "system-configuration"),
    PermissionRule(r"/system-configuration/schools/\d+", ("POST",), ("schools.edit",), "system-configuration"),
    PermissionRule(r"/system-configuration/schools/\d+/delete", ("POST",), ("schools.delete",), "system-configuration"),
    PermissionRule(r"/system-configuration/academic-years", ("GET",), ("academic_years.view",), "system-configuration"),
    PermissionRule(r"/system-configuration/branches", ("GET",), ("branches.view",), "system-configuration"),
    PermissionRule(r"/system-configuration/branches", ("POST",), ("branches.create",), "system-configuration"),
    PermissionRule(r"/system-configuration/branches/\d+", ("POST",), ("branches.edit", "branches.activate_deactivate"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/branches/\d+/delete", ("POST",), ("branches.delete",), "system-configuration"),
    PermissionRule(r"/system-configuration/degrees", ("GET",), ("configuration.manage_degrees",), "system-configuration"),
    PermissionRule(r"/system-configuration/specializations", ("GET",), ("configuration.manage_specializations",), "system-configuration"),
    PermissionRule(r"/system-configuration/qualifications", ("POST",), ("configuration.manage_degrees", "configuration.manage_specializations"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/qualifications/[^/]+", ("POST",), ("configuration.manage_degrees", "configuration.manage_specializations"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/qualifications/[^/]+/delete", ("POST",), ("configuration.manage_degrees", "configuration.manage_specializations"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/timetable-settings", ("GET",), ("timetable.manage_settings", "timetable.manage_blocks"), "system-configuration", match="any"),
    PermissionRule(r"/system-configuration/timetable-settings", ("POST",), ("timetable.manage_settings",), "system-configuration"),
    PermissionRule(r"/system-configuration/timetable-settings/blocks", ("POST",), ("timetable.manage_blocks",), "system-configuration"),
    PermissionRule(r"/system-configuration/timetable-settings/blocks/\d+", ("POST",), ("timetable.manage_blocks",), "system-configuration"),
    PermissionRule(r"/system-configuration/timetable-settings/blocks/\d+/delete", ("POST",), ("timetable.manage_blocks",), "system-configuration"),
    PermissionRule(r"/system-configuration/timetable-settings/recalculate", ("POST",), ("timetable.manage_settings",), "system-configuration"),
    PermissionRule(r"/system-configuration/calendar", ("GET",), ("calendar.manage_event_types",), "system-configuration"),
    PermissionRule(r"/system-configuration/calendar/event-types", ("POST",), ("calendar.manage_event_types",), "system-configuration"),
    PermissionRule(r"/system-configuration/calendar/event-types/\d+", ("POST",), ("calendar.manage_event_types",), "system-configuration"),
    PermissionRule(r"/system-configuration/calendar/event-types/\d+/delete", ("POST",), ("calendar.manage_event_types",), "system-configuration"),
)


def is_public_path(path: str) -> bool:
    return any(re.fullmatch(pattern, path) for pattern in PUBLIC_PATH_PATTERNS)


def _find_permission_rule(path: str, method: str) -> PermissionRule | None:
    for rule in PROTECTED_ROUTE_RULES:
        if rule.matches(path, method):
            return rule
    return None


def _is_api_or_download_request(request: Request) -> bool:
    path = str(request.url.path or "")
    if "/api/" in path or path.endswith((".pdf", ".xlsx", ".json")):
        return True
    accept = str(request.headers.get("accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept


def build_access_denied_response(
    request: Request,
    db: Session,
    *,
    current_user=None,
    permission_keys: tuple[str, ...] = (),
    page_key: str = "dashboard",
    message: str | None = None,
    status_code: int = 403,
):
    if not current_user:
        return RedirectResponse(url="/", status_code=302)

    denied_message = message or "You do not have permission to access this action."
    if _is_api_or_download_request(request):
        return JSONResponse(
            {
                "detail": denied_message,
                "required_permissions": list(permission_keys),
            },
            status_code=status_code,
        )

    if request.method.upper() != "GET":
        return PlainTextResponse(denied_message, status_code=status_code)

    return templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "request": request,
            "denied_message": denied_message,
            "required_permissions": list(permission_keys),
            **build_shell_context(
                request,
                db,
                current_user,
                page_key=page_key,
                title="Access Denied",
                eyebrow="Permissions",
                intro="This page or action is currently restricted by your assigned role permissions.",
                icon="shield",
            ),
        },
        status_code=status_code,
    )


def require_permission(
    request: Request,
    db: Session,
    permission_key: str,
    *,
    current_user=None,
    page_key: str = "dashboard",
    message: str | None = None,
):
    return require_any_permission(
        request,
        db,
        permission_key,
        current_user=current_user,
        page_key=page_key,
        message=message,
    )


def require_any_permission(
    request: Request,
    db: Session,
    *permission_keys: str,
    current_user=None,
    page_key: str = "dashboard",
    message: str | None = None,
):
    resolved_user = current_user or auth.get_current_user(request, db)
    if not resolved_user:
        return None, RedirectResponse(url="/", status_code=302)
    if any(auth.has_permission(db, resolved_user, permission_key) for permission_key in permission_keys):
        return resolved_user, None
    return (
        resolved_user,
        build_access_denied_response(
            request,
            db,
            current_user=resolved_user,
            permission_keys=tuple(permission_keys),
            page_key=page_key,
            message=message,
        ),
    )


def require_all_permissions(
    request: Request,
    db: Session,
    *permission_keys: str,
    current_user=None,
    page_key: str = "dashboard",
    message: str | None = None,
):
    resolved_user = current_user or auth.get_current_user(request, db)
    if not resolved_user:
        return None, RedirectResponse(url="/", status_code=302)
    if all(auth.has_permission(db, resolved_user, permission_key) for permission_key in permission_keys):
        return resolved_user, None
    return (
        resolved_user,
        build_access_denied_response(
            request,
            db,
            current_user=resolved_user,
            permission_keys=tuple(permission_keys),
            page_key=page_key,
            message=message,
        ),
    )


def enforce_route_permission(
    request: Request,
    db: Session,
    *,
    current_user=None,
):
    path = str(request.url.path or "")
    if path.startswith("/static/") or path.startswith("/landing-public/"):
        return None
    if is_public_path(path):
        return None

    rule = _find_permission_rule(path, request.method)
    if not rule:
        return None

    resolved_user = current_user or auth.get_current_user(request, db)
    if not resolved_user:
        return RedirectResponse(url="/", status_code=302)

    if rule.match == "any":
        allowed = any(
            auth.has_permission(db, resolved_user, permission_key)
            for permission_key in rule.permission_keys
        )
    else:
        allowed = all(
            auth.has_permission(db, resolved_user, permission_key)
            for permission_key in rule.permission_keys
        )
    if allowed:
        return None

    return build_access_denied_response(
        request,
        db,
        current_user=resolved_user,
        permission_keys=rule.permission_keys,
        page_key=rule.page_key,
    )
