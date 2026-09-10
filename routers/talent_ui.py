"""M11 presentation routes. Data and mutations remain owned by Talent APIs."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from ui_shell import build_shell_context

router = APIRouter(prefix="/talent", tags=["Talent & Potential UI"])
templates = Jinja2Templates(directory="templates")

VIEWS = {
    "overview": ("Overview", "talent_programs.view"),
    "programs": ("Programs", "talent_programs.view"),
    "evaluation-plans": ("Evaluation Plan", "talent_evaluation_plans.view"),
    "assessments": ("Student Assessments", "talent_assessments.view"),
    # User-facing label is "Talent Review"; backend permission key and route
    # segment stay "review_candidates"/"reviews" for deterministic/audit continuity.
    "reviews": ("Talent Review", "talent_review_candidates.view"),
    "learner-profile": ("Learner Profile", "talent_learner_profiles.view"),
    "analytics": ("Organization Overview", "talent_analytics.view"),
    "talent-map": ("Talent Map", "talent_analytics.view"),
    "portfolio": ("Program Results", "talent_analytics.view"),
    "branch": ("Branch Results", "talent_analytics.view"),
    "overlap": ("Students Across Programs", "talent_analytics.view"),
    "students": ("Students", "talent_analytics.view"),
    "longitudinal": ("Progress Over Time", "talent_analytics.view"),
}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
@router.get("/{view}", response_class=HTMLResponse)
def talent_page(request: Request, view: str = "overview", db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if view not in VIEWS:
        return HTMLResponse("Page not found", status_code=404)
    keys = (VIEWS[view][1],)
    if view == "overview":
        keys = tuple({entry[1] for entry in VIEWS.values()})
    checker = authorization.require_any_permission
    if view == "students":
        keys += ("talent_analytics.view_students",)
        checker = authorization.require_all_permissions
    user, denied = checker(request, db, *keys, current_user=current_user, page_key="talent")
    if denied:
        return denied
    if view == "learner-profile":
        student_id = request.query_params.get("student_id")
        if student_id and str(student_id).isdigit():
            return RedirectResponse(url=f"/students/{student_id}?section=talent", status_code=302)
    # Evaluation Plan/Period configuration is presented as embedded inside a
    # Program's own guided setup (its #tp-schedule step) and no longer has a
    # standalone top-level Talent nav entry - see templates/talent/workspace.html.
    # This route intentionally still renders the "evaluation-plans" view exactly
    # as before (same permission gate, same template/config): the underlying
    # standalone workspace and its `talent_evaluation_plans.*`-only authorized
    # persona (a role holding Evaluation Plan permissions without
    # `talent_programs.view`) both remain fully functional deep-link targets.
    # A user who also holds `talent_programs.view` gets the richer, merged
    # Program-context experience client-side (static/js/talent.js), which can
    # safely resolve program_id/academic_year_id into the equivalent Program
    # workspace URL without an extra authorization round-trip.
    group_id = getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)
    if not group_id:
        return HTMLResponse("Select an organization scope to open Talent & Potential.", status_code=403)
    context = build_shell_context(request, db, user, page_key="talent")
    years = db.query(models.AcademicYear).filter_by(school_group_id=int(group_id)).order_by(models.AcademicYear.id).all()
    allowed = {key: auth.has_permission(db, user, key, school_group_id=group_id)
               for key in {entry[1] for entry in VIEWS.values()} | {
                   "talent_analytics.view_students", "talent_official_identifications.view",
                   "talent_assessment_cycles.view", "talent_assessment_cycles.view_population",
                   "talent_assessment_cycles.manage", "talent_assessment_cycles.govern",
                   "talent_programs.manage", "talent_programs.govern",
                   "talent_evaluation_plans.manage", "talent_evaluation_plans.govern",
                   "talent_assessments.manage", "talent_assessments.complete",
                   "talent_review_candidates.manage", "talent_official_identifications.record",
                   "talent_educator_inputs.view", "talent_educator_inputs.add", "talent_educator_inputs.amend"}}
    # Mirror the existing organization-only API gates for action presentation.
    if not auth.can_access_all_branches(user):
        for key in ("talent_programs.govern", "talent_evaluation_plans.manage", "talent_evaluation_plans.govern", "talent_assessment_cycles.govern",
                    "talent_official_identifications.record"):
            allowed[key] = False
    return templates.TemplateResponse(request=request, name="talent/workspace.html", context={
        "request": request, **context, "talent_view": view,
        "talent_title": VIEWS[view][0], "talent_views": VIEWS,
        "talent_permissions": allowed,
        "talent_years": years,
    }, headers={"Cache-Control": "no-store"})
