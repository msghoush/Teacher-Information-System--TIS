"""System Configuration > Talent & Potential Configuration (presentation route).

Organization-level Talent configuration (Programs, eligible Grades, Rubrics /
Competencies / Levels, KPI and Evaluation Plans / Periods) is defined here and
nowhere else in the UI. This route only renders the workspace shell; data and
every mutation stay owned by the canonical /api/talent/* routes, which keep
enforcing their semantic permission AND organization/global scope. Access here
uses the same rule (talent_configuration_access) so a Branch-scoped actor or a
user without a Talent configuration permission is denied server-side.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

import auth
import authorization
import models
import talent_configuration_access
from auth import get_current_user
from dependencies import get_db
from routers.talent_ui import talent_permission_hints, templates
from ui_shell import build_shell_context

router = APIRouter(prefix=talent_configuration_access.TALENT_CONFIGURATION_PATH, tags=["Talent & Potential Configuration UI"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def talent_configuration_page(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, denied = authorization.require_any_permission(
        request, db, *talent_configuration_access.TALENT_CONFIGURATION_KEYS,
        current_user=current_user, page_key="system-configuration",
    )
    if denied:
        return denied
    allowed_keys = frozenset(request.state.allowed_permission_keys)
    if not talent_configuration_access.is_authorized(user, allowed_keys):
        return authorization.build_access_denied_response(
            request, db, current_user=user,
            permission_keys=talent_configuration_access.TALENT_CONFIGURATION_KEYS,
            page_key="system-configuration",
            message="Talent & Potential configuration is shared by all Branches and is managed at organization level.",
        )
    group_id = getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)
    if not group_id:
        return HTMLResponse("Select an organization scope to open Talent & Potential configuration.", status_code=403)
    context = build_shell_context(
        request, db, user, page_key="system-configuration", permission_keys=allowed_keys,
        title="System Configuration",
        intro="Define organization-wide settings once; every Branch uses them.",
    )
    years = db.query(models.AcademicYear).filter_by(school_group_id=int(group_id)).order_by(models.AcademicYear.id).all()
    return templates.TemplateResponse(request=request, name="talent/configuration.html", context={
        "request": request, **context,
        "talent_permissions": talent_permission_hints(user, allowed_keys),
        "talent_years": years,
    }, headers={"Cache-Control": "no-store"})
