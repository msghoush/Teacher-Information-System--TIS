"""Canonical Students presentation layer.

Reads and writes exclusively through ``student_academic_service`` (the canonical
Student domain/backend) and integrates the approved Talent learner-history into a
single cross-TIS Student Profile. No Student domain architecture is recreated here.
Tenant isolation (SchoolGroup), branch scope, and permission checks mirror
``routers/students.py``.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from student_academic_service import (
    StudentAcademicError,
    audit_event_payload,
    create_placement,
    create_student,
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
from talent_learner_profile_service import TalentLearnerProfileError, build_learner_profile
from ui_shell import build_shell_context

router = APIRouter(prefix="/students", tags=["Students UI"])
templates = Jinja2Templates(directory="templates")

GRADE_LEVELS = ["KG", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
GENDER_OPTIONS = ["", "Male", "Female"]
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


def _redirect(student_id, section=None, success=None):
    url = f"/students/{student_id}"
    if section:
        url += f"?section={section}"
    if success:
        url += ("&" if "?" in url else "?") + f"success={success}"
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

    rows = list_students(db, school_group_id=group_id, search=search, status=status)
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
    years = _years(db, group_id)

    return _render(request, db, current_user, "students.html", {
        "request": request,
        "students": students,
        "search": search,
        "status": status or "",
        "years": years,
        "scoped_year_id": getattr(current_user, "scope_academic_year_id", None) or getattr(current_user, "academic_year_id", None),
        "can_create": can_create,
        "error": request.query_params.get("error") or "",
        "success": request.query_params.get("success") or "",
    })


@router.get("/new", response_class=HTMLResponse)
def students_new(request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.create")
    if denied:
        return denied
    return _render(request, db, current_user, "student_form.html", {
        "request": request,
        "student": None,
        "gender_options": GENDER_OPTIONS,
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
            "error": exc.message,
            "form": {"first_name": first_name, "last_name": last_name, "father_name": father_name, "gender": gender},
            "mode": "new",
        })


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
        "grades": GRADE_LEVELS,
        "gender_options": GENDER_OPTIONS,
        "can_edit": can_edit,
        "can_activate_deactivate": can_activate_deactivate,
        "can_manage_placements": can_manage_placements,
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
    grade_level: str = Form(...),
    section_name: str = Form(...),
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
        create_placement(
            db,
            school_group_id=group_id,
            student_id=student_id,
            academic_year_id=academic_year_id,
            branch_id=branch_id,
            grade_level=grade_level,
            section_name=section_name,
            effective_from=_parse_date(effective_from, "effective_from"),
            effective_to=_parse_date(effective_to, "effective_to"),
            reason=reason or None,
            actor=user,
        )
        db.commit()
        return _redirect(student_id, "placement", "placement")
    except StudentAcademicError:
        db.rollback()
    return _redirect(student_id, "placement")
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
    grade_level: str = Form(...),
    section_name: str = Form(...),
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
        transition_placement(
            db,
            school_group_id=group_id,
            student_id=student_id,
            placement_id=placement_id,
            transition_at=_parse_date(transition_at, "transition_at"),
            academic_year_id=academic_year_id,
            branch_id=branch_id,
            grade_level=grade_level,
            section_name=section_name,
            reason=reason or None,
            actor=user,
        )
        db.commit()
        return _redirect(student_id, "placement", "placement")
    except StudentAcademicError:
        db.rollback()
        return _redirect(student_id, "placement")
# End of module.
