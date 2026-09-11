"""Canonical Students presentation layer.

Reads and writes exclusively through ``student_academic_service`` (the canonical
Student domain/backend) and integrates the approved Talent learner-history into a
single cross-TIS Student Profile. No Student domain architecture is recreated here.
Tenant isolation (SchoolGroup), branch scope, and permission checks mirror
``routers/students.py``.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import auth
import authorization
import models
from academic_grade import GRADE_LEVELS as ALL_GRADE_LEVELS
from academic_grade import normalize_grade_level
from auth import get_current_user
from dependencies import get_db
from homeroom_defaults import normalize_grade_label
from planning_scope_service import list_operational_planning_grades, list_operational_planning_sections
from student_academic_service import (
    LEARNING_STYLES,
    StudentAcademicError,
    audit_event_payload,
    create_placement,
    create_student,
    delete_student,
    delete_students,
    force_delete_student_history,
    student_delete_blockers,
    end_placement,
    get_student,
    list_audit_events,
    list_placements,
    list_students,
    placement_payload,
    resolve_placement,
    transition_placement,
    update_student,
)
from student_learning_style_analytics import build_distribution as build_learning_style_distribution
from student_learning_style_analytics import resolve_population as resolve_learning_style_population
from talent_analytics_privacy import resolve_privacy_policy_provider
from talent_assessment_cycle_service import (
    TalentAssessmentCycleError,
    eligible_open_cycles_for_placement_scope,
    synchronize_placement_to_open_cycles,
)
from talent_learner_profile_service import TalentLearnerProfileError, build_learner_profile
from ui_shell import build_shell_context

router = APIRouter(prefix="/students", tags=["Students UI"])
templates = Jinja2Templates(directory="templates")

# The Student/Talent workflow scopes its Grade selectors to 1-12 only (no KG),
# reusing the exact shared ordered Grade representation from academic_grade.py
# (also used by Planning/Timetable/Talent elsewhere) rather than inventing a
# parallel Grade list - this restriction applies only at this point of use.
GRADE_LEVELS = list(ALL_GRADE_LEVELS[1:])
GENDER_OPTIONS = ["", "Male", "Female"]
# Learning Style V1 (ADR 0031): "" renders as "Not specified" (neutral, not
# an error state) and clears the field on submit; the four values mirror the
# exact canonical set enforced server-side in student_academic_service.py.
LEARNING_STYLE_OPTIONS = ["", *LEARNING_STYLES]
PROFILE_SECTIONS = ("overview", "placement", "talent", "history")


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, current_user, *keys):
    user, denied = authorization.require_any_permission(
        request, db, *keys, current_user=current_user, page_key="students"
    )
    if denied:
        return None, None, denied
    group_id = _scope(db, user)
    if not group_id:
        return user, None, HTMLResponse("Select an organization scope to open Students.", status_code=403)
    return user, int(group_id), None


def _parse_date(value, field):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise StudentAcademicError("invalid_datetime", f"{field} must be a valid date.")


def _visible_branch_ids(db, user):
    if auth.can_access_all_branches(user):
        return None
    return {
        row[0]
        for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()
    }


def _can_view_branch(db, user, branch_id):
    return auth.can_access_all_branches(user) or auth.can_access_branch(db, user, branch_id)


def _student_view(row):
    return {
        "id": row.id,
        "school_group_id": row.school_group_id,
        "first_name": row.first_name,
        "father_name": row.father_name,
        "last_name": row.last_name,
        "gender": row.gender,
        "status": row.status,
        "learning_style": row.learning_style,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _display_name(student):
    return " ".join(
        part for part in (student.get("first_name"), student.get("father_name"), student.get("last_name")) if part
    )


def _initials(student):
    parts = [student.get("first_name") or "", student.get("last_name") or ""]
    return "".join((p[0] if p else "").upper() for p in parts) or "S"


def _years(db, group_id):
    return db.query(models.AcademicYear).filter_by(school_group_id=group_id).order_by(
        models.AcademicYear.year_name
    ).all()


def _branches(db, user, group_id):
    return auth.get_accessible_branch_query(db, user).filter(
        models.Branch.school_group_id == group_id
    ).order_by(models.Branch.name).all()


def _sections_for(db, branch_id, academic_year_id, grade_level):
    """Real Sections for one Branch+Academic-Year+Grade combination.

    Reuses Planning's own canonical ``list_operational_planning_sections``
    authority (the same function Timetable/Subject-Scheduling and the
    Academic Calendar already use for this exact Current/New Section
    selector pattern) rather than a parallel PlanningSection query, then
    narrows to the one requested Grade the same way
    ``routers/planning.py``'s ``list_sections_for_grade`` already does.
    """
    if not branch_id or not academic_year_id or not grade_level:
        return []
    grade = normalize_grade_label(grade_level)
    sections = list_operational_planning_sections(db, int(branch_id), int(academic_year_id))
    return [
        {"id": int(section.id), "section_name": str(section.section_name or "").strip()}
        for section in sections
        if normalize_grade_label(section.grade_level) == grade
    ]


def _learning_style_filter_options(db, branches, academic_year_id, branch_id=None, grade_level=None):
    """Planning-owned Branch -> Grade -> Section choices for read-only analytics."""
    if not academic_year_id:
        return [], []
    branch_ids = {branch.id for branch in branches}
    if branch_id is not None and branch_id not in branch_ids:
        return [], []
    selected_branch_ids = [branch_id] if branch_id is not None else sorted(branch_ids)
    sections = [
        section
        for selected_branch_id in selected_branch_ids
        for section in list_operational_planning_sections(db, int(selected_branch_id), int(academic_year_id))
    ]
    configured = {normalize_grade_level(row.grade_level) for row in sections}
    grades = [grade for grade in GRADE_LEVELS if grade in configured]
    names = [] if grade_level not in configured else sorted({
        str(row.section_name or "").strip()
        for row in sections
        if normalize_grade_level(row.grade_level) == grade_level and row.section_name
    })
    return grades, names


def _placement_view(db, row):
    payload = placement_payload(row)
    payload["branch_name"] = None
    payload["year_name"] = None
    branch = db.get(models.Branch, row.branch_id) if row.branch_id else None
    year = db.get(models.AcademicYear, row.academic_year_id) if row.academic_year_id else None
    if branch:
        payload["branch_name"] = branch.name
    if year:
        payload["year_name"] = year.year_name
    payload["effective_from_display"] = row.effective_from.strftime("%d %b %Y") if row.effective_from else None
    payload["effective_to_display"] = row.effective_to.strftime("%d %b %Y") if row.effective_to else None
    return payload


def _render(request, db, current_user, template_name, context):
    return templates.TemplateResponse(
        request,
        template_name,
        {**context, **build_shell_context(request, db, current_user, page_key="students")},
    )


def _redirect(student_id, section=None, success=None, error=None):
    url = f"/students/{student_id}"
    params = []
    if section:
        params.append(f"section={section}")
    if success:
        params.append(f"success={success}")
    if error:
        params.append(f"error={quote(str(error))}")
    if params:
        url += "?" + "&".join(params)
    return RedirectResponse(url=url, status_code=302)


@router.get("/", response_class=HTMLResponse)
def students_home(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied:
        return denied
    search = str(request.query_params.get("search", "") or "").strip()
    status = request.query_params.get("status") or None
    if status not in (None, "", "active", "inactive"):
        status = None

    branches = _branches(db, user, group_id)
    accessible_branch_ids = {b.id for b in branches}
    branch_filter = request.query_params.get("branch_id") or ""
    branch_id = int(branch_filter) if branch_filter.isdigit() and int(branch_filter) in accessible_branch_ids else None

    scoped_year_id = getattr(current_user, "scope_academic_year_id", None) or getattr(current_user, "academic_year_id", None)
    grade_filter = str(request.query_params.get("grade", "") or "").strip()
    requested_grade = normalize_grade_level(grade_filter) if grade_filter in GRADE_LEVELS else None
    grade_options, section_options = _learning_style_filter_options(
        db, branches, scoped_year_id, branch_id=branch_id, grade_level=requested_grade,
    )
    grade_level = requested_grade if requested_grade in grade_options else None
    section_filter = str(request.query_params.get("section", "") or "").strip()
    allowed_section_options = section_options
    if section_filter and not requested_grade:
        selected_branch_ids = [branch_id] if branch_id is not None else [branch.id for branch in branches]
        allowed_section_options = sorted({
            str(section.section_name or "").strip()
            for selected_branch_id in selected_branch_ids
            for section in list_operational_planning_sections(db, int(selected_branch_id), int(scoped_year_id))
            if section.section_name
        }) if scoped_year_id else []
    section_name = section_filter if section_filter in allowed_section_options else None

    # Grade/Branch/Section reuse the same real current-effective-placement
    # query capability shared with GET /api/students (student_academic_service.
    # list_students) - never a client-only/fabricated filter.
    rows = list_students(
        db, school_group_id=group_id, search=search, status=status,
        branch_id=branch_id, grade_level=grade_level, section_name=section_name,
    )
    visible_ids = _visible_branch_ids(db, user)
    now = datetime.utcnow()
    students = []
    for row in rows:
        student = _student_view(row)
        current = None
        placement = resolve_placement(db, school_group_id=group_id, student_id=row.id, at=now)
        if placement is not None and (visible_ids is None or placement.branch_id in visible_ids):
            current = _placement_view(db, placement)
        student["current_placement"] = current
        student["display_name"] = _display_name(student)
        student["initials"] = _initials(student)
        students.append(student)

    can_create = auth.has_permission(db, user, "students.create", school_group_id=group_id)
    organization_scope = auth.can_access_all_branches(user)
    can_delete = organization_scope and auth.has_permission(db, user, "students.delete", school_group_id=group_id)
    can_bulk_delete = organization_scope and auth.has_permission(db, user, "students.bulk_delete", school_group_id=group_id)
    can_force_delete_history = organization_scope and auth.has_permission(db, user, "students.force_delete_history", school_group_id=group_id)
    years = _years(db, group_id)

    # Learning Style V1 (ADR 0031, Sections 6-8): Branch/Organization
    # distribution, reusing the SAME Branch/Grade/Section context filters
    # already applied above rather than a separate filter UI. Privacy
    # suppression reuses the governed Talent privacy contract; a
    # misconfigured/unavailable policy fails closed to "restricted" instead
    # of publishing raw counts. Search/status are intentionally not applied
    # here - the distribution reflects the Branch/Grade/Section scope, not
    # an incidental text search.
    learning_style_distribution = None
    policy = resolve_privacy_policy_provider()
    if policy is not None:
        ls_population = resolve_learning_style_population(
            db, school_group_id=group_id, user=user, branch_id=branch_id,
            grade_level=grade_level, section_name=section_name,
        )
        if ls_population is not None:
            learning_style_distribution = build_learning_style_distribution(ls_population, policy)

    return _render(request, db, current_user, "students.html", {
        "request": request,
        "students": students,
        "branches": branches,
        "selected_branch_id": branch_id,
        "grade_levels": grade_options,
        "selected_grade": grade_level or "",
        "section_options": section_options,
        "selected_section": section_name or "",
        "search": search,
        "status": status or "",
        "years": years,
        "learning_style_distribution": learning_style_distribution,
        "scoped_year_id": scoped_year_id,
        "can_create": can_create,
        "can_delete": can_delete,
        "can_bulk_delete": can_bulk_delete,
        "can_force_delete_history": can_force_delete_history,
        "error": request.query_params.get("error") or "",
        "success": request.query_params.get("success") or "",
    })


@router.post("/bulk-delete")
def students_bulk_delete_post(
    request: Request,
    student_ids: list[int] = Form([]),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.bulk_delete")
    if denied:
        return denied
    if not auth.can_access_all_branches(user):
        return HTMLResponse("Organization scope is required to permanently delete Students.", status_code=403)
    try:
        count = delete_students(db, school_group_id=group_id, student_ids=student_ids)
        db.commit()
        return RedirectResponse(url=f"/students/?success=deleted-{count}", status_code=302)
    except StudentAcademicError as exc:
        db.rollback()
        return RedirectResponse(url=f"/students/?error={quote(exc.message)}", status_code=302)


@router.get("/{student_id}/delete-preview")
def student_delete_preview_ui(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.delete")
    if denied:
        return denied
    if not auth.can_access_all_branches(user):
        return JSONResponse({"detail": "Organization scope is required to permanently delete a Student."}, status_code=403)
    try:
        blockers = student_delete_blockers(db, school_group_id=group_id, student_id=student_id)
        return {
            "student_id": student_id,
            "has_history": bool(blockers),
            "blockers": blockers,
            "can_force_delete_history": auth.has_permission(
                db, user, "students.force_delete_history", school_group_id=group_id
            ),
        }
    except StudentAcademicError as exc:
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=404 if exc.code == "not_found" else 400)


@router.post("/{student_id}/delete")
def student_delete_post(
    request: Request,
    student_id: int,
    db: Session = Depends(get_db),
    force_history: str = Form(""),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.delete")
    if denied:
        return denied
    if not auth.can_access_all_branches(user):
        return HTMLResponse("Organization scope is required to permanently delete a Student.", status_code=403)
    try:
        if str(force_history or "").strip().lower() in {"1", "true", "yes", "on"}:
            if not auth.has_permission(db, user, "students.force_delete_history", school_group_id=group_id):
                return HTMLResponse("Force delete history permission is required.", status_code=403)
            force_delete_student_history(db, school_group_id=group_id, student_id=student_id)
        else:
            delete_student(db, school_group_id=group_id, student_id=student_id)
        db.commit()
        return RedirectResponse(url="/students/?success=deleted-1", status_code=302)
    except StudentAcademicError as exc:
        db.rollback()
        return RedirectResponse(url=f"/students/?error={quote(exc.message)}", status_code=302)


@router.get("/new", response_class=HTMLResponse)
def students_new(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.create")
    if denied:
        return denied
    return _render(request, db, current_user, "student_form.html", {
        "request": request,
        "student": None,
        "gender_options": GENDER_OPTIONS,
        "learning_style_options": LEARNING_STYLE_OPTIONS,
        "error": request.query_params.get("error") or "",
        "mode": "new",
    })


@router.post("/new")
def students_new_post(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    father_name: str = Form(""),
    gender: str = Form(""),
    learning_style: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.create")
    if denied:
        return denied
    try:
        row = create_student(
            db,
            school_group_id=group_id,
            first_name=first_name,
            last_name=last_name,
            father_name=father_name or None,
            gender=gender or None,
            learning_style=learning_style or None,
            actor=user,
        )
        db.commit()
        return RedirectResponse(url=f"/students/{row.id}?section=overview&success=student", status_code=302)
    except StudentAcademicError as exc:
        db.rollback()
        return _render(request, db, current_user, "student_form.html", {
            "request": request,
            "student": None,
            "gender_options": GENDER_OPTIONS,
            "learning_style_options": LEARNING_STYLE_OPTIONS,
            "error": exc.message,
            "form": {"first_name": first_name, "last_name": last_name, "father_name": father_name, "gender": gender, "learning_style": learning_style},
            "mode": "new",
        })


@router.get("/sections")
def students_sections_for_grade(
    request: Request,
    branch_id: int = 0,
    academic_year_id: int = 0,
    grade_level: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Real cascading Section options for one Academic Year + Branch + Grade.

    Backs the Academic Placement form's live cascade. Reuses the exact
    canonical Planning Section authority (``_sections_for`` ->
    ``list_operational_planning_sections``) - no parallel Section data
    structure. Gated by the same ``students.manage_placements`` permission
    the placement mutation routes already require, plus the actor's real
    Branch access scope.
    """
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied:
        return denied
    if not branch_id or not academic_year_id:
        return {"items": []}
    if not auth.can_access_branch(db, user, branch_id):
        return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
    branch = db.query(models.Branch).filter_by(id=branch_id, school_group_id=group_id).one_or_none()
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=group_id).one_or_none()
    if branch is None or year is None:
        return JSONResponse({"detail": "Branch or academic year is outside the organization."}, status_code=400)
    if not grade_level:
        return {"grades": list_operational_planning_grades(db, branch_id, academic_year_id)}
    return {"items": _sections_for(db, branch_id, academic_year_id, grade_level)}


@router.get("/placement-open-cycle-preview")
def placement_open_cycle_preview(
    request: Request,
    student_id: int,
    academic_year_id: int,
    branch_id: int,
    planning_section_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied:
        return denied
    if get_student(db, group_id, student_id) is None:
        return JSONResponse({"detail": "Student was not found."}, status_code=404)
    if not auth.can_access_branch(db, user, branch_id):
        return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
    section = db.query(models.PlanningSection).filter_by(
        id=planning_section_id, branch_id=branch_id, academic_year_id=academic_year_id
    ).one_or_none()
    if section is None:
        return JSONResponse({"detail": "Planning Section does not match the selected Academic Year and Branch."}, status_code=400)
    cycles = eligible_open_cycles_for_placement_scope(
        db, school_group_id=group_id, academic_year_id=academic_year_id,
        grade_level=normalize_grade_level(section.grade_level),
    )
    existing_cycle_ids = {
        row[0] for row in db.query(models.TalentAssessmentCyclePopulationMember.cycle_id).filter(
            models.TalentAssessmentCyclePopulationMember.school_group_id == group_id,
            models.TalentAssessmentCyclePopulationMember.student_id == student_id,
            models.TalentAssessmentCyclePopulationMember.cycle_id.in_([cycle.id for cycle in cycles]),
        ).all()
    } if cycles else set()
    return {"open_cycle_count": sum(1 for cycle in cycles if cycle.id not in existing_cycle_ids)}


@router.get("/{student_id}", response_class=HTMLResponse)
def student_profile(request: Request, student_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied:
        return denied
    row = get_student(db, group_id, student_id)
    if row is None:
        return HTMLResponse("Student was not found.", status_code=404)

    section = request.query_params.get("section") or "overview"
    if section not in PROFILE_SECTIONS:
        section = "overview"

    student = _student_view(row)
    student["display_name"] = _display_name(student)
    student["initials"] = _initials(student)

    visible_ids = _visible_branch_ids(db, user)
    now = datetime.utcnow()

    current = resolve_placement(db, school_group_id=group_id, student_id=student_id, at=now)
    if current is not None and not (visible_ids is None or current.branch_id in visible_ids):
        current = None
    current_view = _placement_view(db, current) if current is not None else None

    placements = list_placements(db, school_group_id=group_id, student_id=student_id)
    placements = [p for p in placements if visible_ids is None or p.branch_id in visible_ids]
    placement_views = [_placement_view(db, p) for p in placements]

    can_edit = auth.has_permission(db, user, "students.edit", school_group_id=group_id)
    can_activate_deactivate = auth.has_permission(db, user, "students.activate_deactivate", school_group_id=group_id)
    can_manage_placements = auth.has_permission(db, user, "students.manage_placements", school_group_id=group_id)

    talent_visible = auth.has_permission(db, user, "talent_learner_profiles.view", school_group_id=group_id)
    talent_profile = None
    if talent_visible and section == "talent":
        try:
            talent_profile = build_learner_profile(
                db,
                school_group_id=group_id,
                student_id=student_id,
                visible_branch_ids=visible_ids,
                include_competencies=True,
                include_timeline=True,
                include_review_candidates=auth.has_permission(db, user, "talent_review_candidates.view", school_group_id=group_id),
                include_identifications=auth.has_permission(db, user, "talent_official_identifications.view", school_group_id=group_id),
                include_educator_inputs=auth.has_permission(db, user, "talent_educator_inputs.view", school_group_id=group_id),
            )
        except TalentLearnerProfileError:
            talent_profile = None

    audit_events = []
    if section == "history":
        audit_rows = list_audit_events(db, school_group_id=group_id, student_id=student_id)
        actor_ids = {row.actor_user_id for row in audit_rows if row.actor_user_id}
        actor_names = {}
        if actor_ids:
            actor_names = {
                u.user_id: f"{u.first_name or ''} {u.last_name or ''}".strip() or u.username
                for u in db.query(models.User).filter(models.User.user_id.in_(actor_ids)).all()
            }
        for audit in audit_rows:
            audit_events.append({
                **audit_event_payload(audit),
                "created_at": audit.created_at.strftime("%d %b %Y, %H:%M") if audit.created_at else None,
                "actor_name": actor_names.get(audit.actor_user_id),
            })

    years = _years(db, group_id)
    branches = _branches(db, user, group_id)
    year_ids = {int(year.id) for year in years}
    branch_ids = {int(branch.id) for branch in branches}
    shell_year_id = getattr(user, "scope_academic_year_id", None) or getattr(user, "academic_year_id", None)
    shell_branch_id = getattr(user, "scope_branch_id", None) or getattr(user, "branch_id", None)
    placement_academic_year_id = (
        int(current_view["academic_year_id"]) if current_view else
        int(shell_year_id) if shell_year_id and int(shell_year_id) in year_ids else
        None
    )
    placement_branch_id = (
        int(current_view["branch_id"]) if current_view else
        int(shell_branch_id) if shell_branch_id and int(shell_branch_id) in branch_ids else
        None
    )

    return _render(request, db, current_user, "student_profile.html", {
        "request": request,
        "student": student,
        "section": section,
        "sections": PROFILE_SECTIONS,
        "current_placement": current_view,
        "placements": placement_views,
        "talent_visible": talent_visible,
        "talent_profile": talent_profile,
        "audit_events": audit_events,
        "years": years,
        "branches": branches,
        "placement_academic_year_id": placement_academic_year_id,
        "placement_branch_id": placement_branch_id,
        "grades": GRADE_LEVELS,
        "gender_options": GENDER_OPTIONS,
        "learning_style_options": LEARNING_STYLE_OPTIONS,
        "can_edit": can_edit,
        "can_activate_deactivate": can_activate_deactivate,
        "can_manage_placements": can_manage_placements,
        "sections_api_url": "/students/sections",
        "today": datetime.utcnow().strftime("%Y-%m-%d"),
        "error": request.query_params.get("error") or "",
        "success": request.query_params.get("success") or "",
    })


@router.post("/{student_id}/edit")
def student_edit_post(
    request: Request,
    student_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    father_name: str = Form(""),
    gender: str = Form(""),
    learning_style: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.edit")
    if denied:
        return denied
    try:
        update_student(
            db,
            school_group_id=group_id,
            student_id=student_id,
            first_name=first_name,
            last_name=last_name,
            father_name=father_name or None,
            gender=gender or None,
            learning_style=learning_style,
            actor=user,
        )
        db.commit()
        return _redirect(student_id, "overview", "saved")
    except StudentAcademicError:
        db.rollback()
        return _redirect(student_id, "overview")


@router.post("/{student_id}/status")
def student_status_post(
    request: Request,
    student_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.activate_deactivate")
    if denied:
        return denied
    try:
        update_student(db, school_group_id=group_id, student_id=student_id, status=status, actor=user)
        db.commit()
        return _redirect(student_id, "overview", "saved")
    except StudentAcademicError:
        db.rollback()
        return _redirect(student_id, "overview")


@router.post("/{student_id}/placements")
def student_placement_post(
    request: Request,
    student_id: int,
    academic_year_id: int = Form(...),
    branch_id: int = Form(...),
    planning_section_id: str = Form(""),
    grade_level: str = Form(""),
    section_name: str = Form(""),
    effective_from: str = Form(...),
    effective_to: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied:
        return denied
    try:
        if not auth.can_access_branch(db, user, branch_id):
            return HTMLResponse("Branch is outside your authorized scope.", status_code=403)
        # A real configured PlanningSection (planning_section_id) takes precedence
        # and supplies its own canonical grade_level/section_name; raw grade_level/
        # section_name remain the legacy manual-entry fallback used when no
        # PlanningSection is configured for this Branch/Academic-Year/Grade yet.
        placement = create_placement(
            db,
            school_group_id=group_id,
            student_id=student_id,
            academic_year_id=academic_year_id,
            branch_id=branch_id,
            planning_section_id=int(planning_section_id) if str(planning_section_id or "").strip() else None,
            grade_level=grade_level or None,
            section_name=section_name or None,
            effective_from=_parse_date(effective_from, "effective_from"),
            effective_to=_parse_date(effective_to, "effective_to"),
            reason=reason or None,
            actor=user,
        )
        synced = synchronize_placement_to_open_cycles(
            db, school_group_id=group_id, student_id=student_id,
            academic_placement_id=placement.id, actor=user,
        )
        db.commit()
        return _redirect(student_id, "placement", "placement_synced" if synced else "placement")
    except (StudentAcademicError, TalentAssessmentCycleError) as exc:
        db.rollback()
        return _redirect(student_id, "placement", error=exc.message)
@router.post("/{student_id}/placements/{placement_id}/end")
def student_placement_end_post(
    request: Request,
    student_id: int,
    placement_id: int,
    effective_to: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied:
        return denied
    existing = db.query(models.StudentAcademicPlacement).filter_by(
        id=placement_id, school_group_id=group_id, student_id=student_id
    ).one_or_none()
    if existing is None:
        return HTMLResponse("Academic placement was not found.", status_code=404)
    if not _can_view_branch(db, user, existing.branch_id):
        return HTMLResponse("Branch is outside your authorized scope.", status_code=403)
    try:
        end_placement(
            db,
            school_group_id=group_id,
            student_id=student_id,
            placement_id=placement_id,
            effective_to=_parse_date(effective_to, "effective_to"),
            reason=reason or None,
            actor=user,
        )
        db.commit()
        return _redirect(student_id, "placement", "placement")
    except StudentAcademicError:
        db.rollback()
        return _redirect(student_id, "placement")
# End of module.
@router.post("/{student_id}/placements/{placement_id}/transition")
def student_placement_transition_post(
    request: Request,
    student_id: int,
    placement_id: int,
    academic_year_id: int = Form(...),
    branch_id: int = Form(...),
    planning_section_id: str = Form(""),
    grade_level: str = Form(""),
    section_name: str = Form(""),
    transition_at: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied:
        return denied
    existing = db.query(models.StudentAcademicPlacement).filter_by(
        id=placement_id, school_group_id=group_id, student_id=student_id
    ).one_or_none()
    if existing is None:
        return HTMLResponse("Academic placement was not found.", status_code=404)
    if not _can_view_branch(db, user, existing.branch_id):
        return HTMLResponse("Branch is outside your authorized scope.", status_code=403)
    try:
        if not auth.can_access_branch(db, user, branch_id):
            return HTMLResponse("Branch is outside your authorized scope.", status_code=403)
        _, placement = transition_placement(
            db,
            school_group_id=group_id,
            student_id=student_id,
            placement_id=placement_id,
            transition_at=_parse_date(transition_at, "transition_at"),
            academic_year_id=academic_year_id,
            branch_id=branch_id,
            planning_section_id=int(planning_section_id) if str(planning_section_id or "").strip() else None,
            grade_level=grade_level or None,
            section_name=section_name or None,
            reason=reason or None,
            actor=user,
        )
        synced = synchronize_placement_to_open_cycles(
            db, school_group_id=group_id, student_id=student_id,
            academic_placement_id=placement.id, actor=user,
        )
        db.commit()
        return _redirect(student_id, "placement", "placement_synced" if synced else "placement")
    except (StudentAcademicError, TalentAssessmentCycleError) as exc:
        db.rollback()
        return _redirect(student_id, "placement", error=exc.message)
# End of module.
