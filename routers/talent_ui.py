"""M11 presentation routes. Data and mutations remain owned by Talent APIs."""

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import auth
import authorization
import models
import talent_configuration_access
from auth import get_current_user
from dependencies import get_db
from ui_shell import build_shell_context

router = APIRouter(prefix="/talent", tags=["Talent & Potential UI"])
templates = Jinja2Templates(directory="templates")

_STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
_ASSET_VERSIONS: dict = {}


def talent_asset_version(relative_path: str) -> str:
    """Short content hash for a Talent static asset (cache-busting query value).

    /static is served without a Cache-Control policy, so a browser may keep using a
    copy of talent.js from an EARLIER deployment (heuristic freshness) against the
    freshly rendered no-store page - the exact mixed-version state the loading
    hardening cannot protect against. Versioning the URL by content guarantees the
    page and its scripts always come from the same deployment. Re-hashed only when
    the file's mtime/size changes.
    """
    path = _STATIC_ROOT / relative_path
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = _ASSET_VERSIONS.get(relative_path)
        if cached and cached[0] == signature:
            return cached[1]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        _ASSET_VERSIONS[relative_path] = (signature, digest)
        return digest
    except OSError:
        return "0"


templates.env.globals["talent_asset_version"] = talent_asset_version

VIEWS = {
    "overview": ("Overview", "talent_programs.view"),
    "programs": ("Programs", "talent_programs.view"),
    "evaluation-plans": ("Evaluation Plan", "talent_evaluation_plans.view"),
    "assessments": ("Student Assessments", "talent_assessments.view"),
    # Acceptance B: Review Candidate / Official Identification are legacy history,
    # no longer part of the current workflow (Student -> Program -> Assessment ->
    # automatic Classification). The route stays reachable (same permission gate)
    # for audit, labeled as legacy history and removed from primary navigation;
    # the backend permission key and "reviews" route segment are unchanged.
    "reviews": ("Legacy Review & Identification History", "talent_review_candidates.view"),
    "learner-profile": ("Learner Profile", "talent_learner_profiles.view"),
    "analytics": ("Organization Overview", "talent_analytics.view"),
    "talent-map": ("Talent Map", "talent_analytics.view"),
    "portfolio": ("Program Results", "talent_analytics.view"),
    "branch": ("Branch Results", "talent_analytics.view"),
    "overlap": ("Students Across Programs", "talent_analytics.view"),
    "students": ("Students", "talent_analytics.view"),
    "longitudinal": ("Progress Over Time", "talent_analytics.view"),
}


def talent_permission_hints(user, allowed_keys) -> dict:
    """Server-derived capability hints (`can()`) for the Talent browser modules.

    Shared by the operational Talent pages and the System Configuration > Talent &
    Potential workspace so both present exactly the same, backend-mirroring hints.
    """
    allowed = {key: key in allowed_keys
               for key in {entry[1] for entry in VIEWS.values()} | {
                   "talent_analytics.view_students", "talent_official_identifications.view",
                   # M18b-2: the Results & Analytics page gates its new
                   # Learning Style distribution section on the same
                   # permission the /api/talent/results-analytics/.../
                   # learning-style route itself requires (student-domain-
                   # wide, never Program-bound) - see routers/talent_results_analytics.py.
                   "students.view",
                   "talent_assessment_cycles.view", "talent_assessment_cycles.view_population",
                   "talent_assessment_cycles.manage", "talent_assessment_cycles.govern",
                   "talent_programs.manage", "talent_programs.govern",
                   "talent_programs.delete_competency", "talent_programs.delete_rubric_level",
                   "talent_evaluation_plans.manage", "talent_evaluation_plans.govern",
                   "talent_evaluation_plans.select_period",
                   "talent_assessments.manage", "talent_assessments.complete",
                   "talent_review_candidates.manage", "talent_official_identifications.record",
                   "talent_educator_inputs.view", "talent_educator_inputs.add", "talent_educator_inputs.amend"}}
    # Mirror the existing organization-only API gates for action presentation.
    # Final-closure Part B: shared configuration (Programs, Frameworks, Rubrics,
    # Competencies/KPI, annual configuration, Evaluation Plans/Periods, Cycle
    # definitions) is organization-level, so EVERY configuration mutation capability
    # is withheld from Branch-scoped actors, matching the API gates exactly.
    if not auth.can_access_all_branches(user):
        for key in ("talent_programs.manage", "talent_programs.govern",
                    "talent_programs.delete_competency", "talent_programs.delete_rubric_level",
                    "talent_evaluation_plans.manage", "talent_evaluation_plans.govern",
                    "talent_assessment_cycles.manage", "talent_assessment_cycles.govern",
                    "talent_official_identifications.record"):
            allowed[key] = False
    return allowed


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
    # Evaluation Plan/Period CONFIGURATION now lives only in System Configuration >
    # Talent & Potential (see below). The "evaluation-plans" route stays reachable
    # as a READ-ONLY operational period list (same permission gate) for actors who
    # cannot configure; an authorized organization-level actor is redirected.
    group_id = getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)
    if not group_id:
        return HTMLResponse("Select an organization scope to open Talent & Potential.", status_code=403)
    allowed_keys = frozenset(request.state.allowed_permission_keys)
    context = build_shell_context(
        request,
        db,
        user,
        page_key="talent",
        permission_keys=allowed_keys,
    )
    years = db.query(models.AcademicYear).filter_by(school_group_id=int(group_id)).order_by(models.AcademicYear.id).all()
    # Talent Branch (owner-directed amendment): the active application Branch (sidebar
    # "Change Branch / Campus") is only the DEFAULT page-level Branch for an
    # organization-authorized actor, who may pick All Branches or any authorized
    # Branch in the Talent Branch filter. A Branch-limited actor is LOCKED to their
    # authorized Branch (branch_locked). Rendered only so the client can shape its
    # options; every Talent API re-authorizes its own branch_id server-side.
    active_branch_id = None
    active_branch_name = None
    branch_locked = not auth.can_access_all_branches(user)
    candidate_branch_id = getattr(user, "scope_branch_id", None) or getattr(user, "branch_id", None)
    if candidate_branch_id:
        active_branch = db.query(models.Branch).filter_by(id=int(candidate_branch_id), school_group_id=int(group_id)).one_or_none()
        if active_branch is not None and auth.can_access_branch(db, user, active_branch.id):
            active_branch_id, active_branch_name = int(active_branch.id), active_branch.name
    allowed = talent_permission_hints(user, allowed_keys)
    # Configuration lives ONLY under System Configuration > Talent & Potential
    # (batch "System Configuration + Operational User Flow Separation"). The normal
    # Talent pages are operational and render no configuration mutation control; an
    # authorized organization-level actor gets exactly one non-mutating link to it.
    # UI visibility never replaces the backend gates (403 organization_authority_required).
    can_configure = talent_configuration_access.is_authorized(user, allowed_keys)
    if view == "evaluation-plans" and can_configure:
        # Old deep link: the Evaluation Plan editor left the operational pages. An
        # authorized organization-level actor lands in the canonical configuration
        # workspace with the same Program / Academic Year context.
        return RedirectResponse(
            url=talent_configuration_access.configuration_url(
                tab="evaluation-periods",
                program_id=request.query_params.get("program_id"),
                academic_year_id=request.query_params.get("academic_year_id"),
            ),
            status_code=302,
        )
    return templates.TemplateResponse(request=request, name="talent/workspace.html", context={
        "request": request, **context, "talent_view": view,
        "talent_title": VIEWS[view][0], "talent_views": VIEWS,
        "talent_permissions": allowed,
        "talent_can_configure": can_configure,
        "talent_configuration_url": talent_configuration_access.TALENT_CONFIGURATION_PATH if can_configure else "",
        "talent_years": years,
        "talent_active_branch_id": active_branch_id,
        "talent_active_branch_name": active_branch_name,
        "talent_branch_locked": branch_locked,
    }, headers={"Cache-Control": "no-store"})
