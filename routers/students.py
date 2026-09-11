from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from student_academic_service import (
    StudentAcademicError, add_external_identifier, audit_event_payload, correct_placement, create_placement,
    create_student, deactivate_external_identifier, delete_student, delete_students, force_delete_student_history,
    student_delete_blockers, end_placement, get_student,
    list_audit_events, list_placements, list_students, placement_payload, resolve_placement, transition_placement,
    update_student,
)
from student_learning_style_analytics import build_distribution as build_learning_style_distribution
from student_learning_style_analytics import resolve_population as resolve_learning_style_population
from talent_analytics_privacy import resolve_privacy_policy_provider

router = APIRouter(prefix="/api/students", tags=["Students"])


def _error(exc, status=400):
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=404 if exc.code == "not_found" else status)


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, current_user, *keys):
    user, denied = authorization.require_any_permission(request, db, *keys, current_user=current_user, page_key="students")
    if denied:
        return None, None, denied
    school_group_id = _scope(db, user)
    if not school_group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(school_group_id), None


def _parse_datetime(value, field):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        raise StudentAcademicError("invalid_datetime", f"{field} must be an ISO-8601 date or date-time.")


def _student_json(row):
    return {"id": row.id, "school_group_id": row.school_group_id, "first_name": row.first_name,
            "father_name": row.father_name, "last_name": row.last_name, "gender": row.gender,
            "status": row.status, "learning_style": row.learning_style,
            "created_at": row.created_at, "updated_at": row.updated_at}


@router.post("")
def student_create(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.create")
    if denied: return denied
    try:
        row = create_student(db, school_group_id=group_id, actor=user, **{key: payload.get(key) for key in ("first_name", "father_name", "last_name", "gender", "learning_style")})
        db.commit(); db.refresh(row)
        return JSONResponse(jsonable_encoder(_student_json(row)), status_code=201)
    except StudentAcademicError as exc:
        db.rollback(); return _error(exc)


@router.get("")
def student_list(request: Request, search: str = Query(""), status: str | None = Query(None),
                  branch_id: int | None = Query(None), grade_level: str | None = Query(None),
                  section_name: str | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied: return denied
    return [_student_json(row) for row in list_students(
        db, school_group_id=group_id, search=search, status=status,
        branch_id=branch_id, grade_level=grade_level, section_name=section_name,
    )]


@router.get("/analytics/learning-style-distribution")
def student_learning_style_distribution(
    request: Request, branch_id: int | None = Query(None), grade_level: str | None = Query(None),
    section_name: str | None = Query(None), db: Session = Depends(get_db),
    current_user=Depends(get_current_user), policy=Depends(resolve_privacy_policy_provider),
):
    """Branch/Organization Learning Style distribution (ADR 0031, Sections 6-8).

    Population: Students with a current effective academic placement in the
    actor's authorized Branch scope, optionally narrowed to one Branch/Grade/
    Section via the same filters the Students list already supports - never
    filtered by Talent Program/Cycle participation. Gated by the same
    ``students.view`` permission the Students list itself already requires
    (no new permission). A misconfigured/unavailable privacy policy fails
    closed rather than publishing raw counts.
    """
    user, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied:
        return denied
    if policy is None:
        return JSONResponse({"detail": "Analytics is unavailable.", "code": "analytics_unavailable"}, status_code=503)
    rows = resolve_learning_style_population(
        db, school_group_id=group_id, user=user, branch_id=branch_id,
        grade_level=grade_level, section_name=section_name,
    )
    if rows is None:
        return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
    return jsonable_encoder(build_learning_style_distribution(rows, policy))


@router.get("/{student_id}")
def student_read(student_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied: return denied
    row = get_student(db, group_id, student_id)
    return _student_json(row) if row else JSONResponse({"detail": "Student was not found.", "code": "not_found"}, status_code=404)


@router.patch("/{student_id}")
def student_update(student_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    keys = ("students.activate_deactivate",) if set(payload) == {"status"} else ("students.edit",)
    user, group_id, denied = _authorize(request, db, current_user, *keys)
    if denied: return denied
    allowed = {key: payload[key] for key in ("first_name", "father_name", "last_name", "gender", "learning_style", "status") if key in payload}
    try:
        row = update_student(db, school_group_id=group_id, student_id=student_id, actor=user, **allowed)
        db.commit(); db.refresh(row); return _student_json(row)
    except StudentAcademicError as exc:
        db.rollback(); return _error(exc)


@router.get("/{student_id}/delete-preview")
def student_delete_preview(student_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
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
        return _error(exc)


@router.delete("/{student_id}")
def student_delete(student_id: int, request: Request, force_history: bool = Query(False), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.delete")
    if denied:
        return denied
    if not auth.can_access_all_branches(user):
        return JSONResponse({"detail": "Organization scope is required to permanently delete a Student."}, status_code=403)
    try:
        if force_history:
            if not auth.has_permission(db, user, "students.force_delete_history", school_group_id=group_id):
                return JSONResponse({"detail": "Force delete history permission is required."}, status_code=403)
            force_delete_student_history(db, school_group_id=group_id, student_id=student_id)
        else:
            delete_student(db, school_group_id=group_id, student_id=student_id)
        db.commit()
        return {"deleted": True, "student_id": student_id, "history_deleted": bool(force_history)}
    except StudentAcademicError as exc:
        db.rollback()
        return _error(exc, status=409 if exc.code == "student_delete_blocked" else 400)


@router.post("/bulk-delete")
def student_bulk_delete(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.bulk_delete")
    if denied:
        return denied
    if not auth.can_access_all_branches(user):
        return JSONResponse({"detail": "Organization scope is required to permanently delete Students."}, status_code=403)
    try:
        count = delete_students(db, school_group_id=group_id, student_ids=payload.get("student_ids"))
        db.commit()
        return {"deleted": count}
    except StudentAcademicError as exc:
        db.rollback()
        return _error(exc, status=409 if exc.code == "student_delete_blocked" else 400)


@router.get("/{student_id}/audit")
def student_audit(student_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Read-only history trail for the canonical Student Profile History section.

    Reuses the existing append-only StudentAudit rows every mutation already
    writes; no new persistence authority or resource_type is introduced.
    """
    _, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied: return denied
    try:
        rows = list_audit_events(db, school_group_id=group_id, student_id=student_id)
    except StudentAcademicError as exc:
        return _error(exc)
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id}
    actors = {}
    if actor_ids:
        actors = {u.user_id: f"{u.first_name or ''} {u.last_name or ''}".strip() or u.username
                  for u in db.query(models.User).filter(models.User.user_id.in_(actor_ids)).all()}
    return [dict(audit_event_payload(row), actor_name=actors.get(row.actor_user_id)) for row in rows]


@router.post("/{student_id}/external-identifiers")
def identifier_add(student_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_identifiers")
    if denied: return denied
    try:
        row = add_external_identifier(db, school_group_id=group_id, student_id=student_id, actor=user,
            namespace=payload.get("namespace"), value=payload.get("value"), source=payload.get("source"))
        db.commit(); db.refresh(row)
        return JSONResponse(jsonable_encoder({"id": row.id, "student_id": row.student_id, "namespace": row.namespace, "value": row.value, "source": row.source, "status": row.status}), status_code=201)
    except (StudentAcademicError, IntegrityError) as exc:
        db.rollback()
        return _error(exc) if isinstance(exc, StudentAcademicError) else JSONResponse({"detail": "Identifier already exists.", "code": "duplicate_identifier"}, status_code=409)


@router.post("/{student_id}/external-identifiers/{identifier_id}/deactivate")
def identifier_deactivate(student_id: int, identifier_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_identifiers")
    if denied: return denied
    try:
        row = deactivate_external_identifier(db, school_group_id=group_id, student_id=student_id, identifier_id=identifier_id, actor=user)
        db.commit(); return {"id": row.id, "status": row.status}
    except StudentAcademicError as exc: db.rollback(); return _error(exc)


def _existing_placement_branch_denied(db, user, group_id, student_id, placement_id):
    """Deny mutating an existing placement whose current branch is outside the actor's scope.

    Sibling checks against a request-supplied branch_id only validate the new/target
    branch; a caller-supplied branch_id within scope must not be enough to reach an
    existing placement that currently belongs to a different, inaccessible branch.
    A missing row is intentionally not flagged here so the underlying service still
    produces the canonical not_found response instead of leaking existence via 403.
    """
    existing = db.query(models.StudentAcademicPlacement).filter_by(
        id=placement_id, school_group_id=group_id, student_id=student_id
    ).one_or_none()
    if existing is not None and not auth.can_access_branch(db, user, existing.branch_id):
        return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
    return None


def _placement_authorized(db, user, placement):
    return placement is not None and auth.can_access_branch(db, user, placement.branch_id)


def _placement_args(payload):
    return dict(academic_year_id=int(payload.get("academic_year_id")), branch_id=int(payload.get("branch_id")),
        planning_section_id=int(payload["planning_section_id"]) if payload.get("planning_section_id") is not None else None,
        grade_level=payload.get("grade_level"), section_name=payload.get("section_name"),
        effective_from=_parse_datetime(payload.get("effective_from"), "effective_from"),
        effective_to=_parse_datetime(payload["effective_to"], "effective_to") if payload.get("effective_to") else None,
        reason=payload.get("reason"))


@router.post("/{student_id}/placements")
def placement_create(student_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied: return denied
    try:
        args = _placement_args(payload)
        if not auth.can_access_branch(db, user, args["branch_id"]):
            return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
        row = create_placement(db, school_group_id=group_id, student_id=student_id, actor=user, **args)
        db.commit(); db.refresh(row); return JSONResponse(jsonable_encoder(placement_payload(row)), status_code=201)
    except (StudentAcademicError, TypeError, ValueError) as exc:
        db.rollback(); return _error(exc) if isinstance(exc, StudentAcademicError) else JSONResponse({"detail": "Invalid placement payload."}, status_code=400)


@router.get("/{student_id}/placements")
def placement_history(student_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied: return denied
    try:
        rows = list_placements(db, school_group_id=group_id, student_id=student_id)
        return [placement_payload(row) for row in rows if _placement_authorized(db, current_user, row)]
    except StudentAcademicError as exc: return _error(exc)


@router.get("/{student_id}/placements/effective")
def placement_effective(student_id: int, request: Request, at: str = Query(...), academic_year_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied: return denied
    try: row = resolve_placement(db, school_group_id=group_id, student_id=student_id, at=_parse_datetime(at, "at"), academic_year_id=academic_year_id)
    except StudentAcademicError as exc: return _error(exc)
    return placement_payload(row) if _placement_authorized(db, current_user, row) else JSONResponse({"detail": "No effective academic placement.", "code": "no_effective_placement"}, status_code=404)


@router.get("/{student_id}/placements/{placement_id}")
def placement_read(student_id: int, placement_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "students.view")
    if denied: return denied
    rows = db.query(models.StudentAcademicPlacement).filter_by(
        id=placement_id, student_id=student_id, school_group_id=group_id
    ).one_or_none()
    return placement_payload(rows) if _placement_authorized(db, current_user, rows) else JSONResponse({"detail": "Academic placement was not found.", "code": "not_found"}, status_code=404)


@router.post("/{student_id}/placements/{placement_id}/end")
def placement_end(student_id: int, placement_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied: return denied
    branch_denied = _existing_placement_branch_denied(db, user, group_id, student_id, placement_id)
    if branch_denied: return branch_denied
    try:
        row = end_placement(db, school_group_id=group_id, student_id=student_id, placement_id=placement_id,
            effective_to=_parse_datetime(payload.get("effective_to"), "effective_to"), reason=payload.get("reason"), actor=user)
        db.commit(); db.refresh(row); return placement_payload(row)
    except StudentAcademicError as exc: db.rollback(); return _error(exc)


@router.post("/{student_id}/placements/{placement_id}/transition")
def placement_transition(student_id: int, placement_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied: return denied
    branch_denied = _existing_placement_branch_denied(db, user, group_id, student_id, placement_id)
    if branch_denied: return branch_denied
    try:
        args = _placement_args({**payload, "effective_from": payload.get("transition_at")})
        if not auth.can_access_branch(db, user, args["branch_id"]): return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
        transition_at = args.pop("effective_from"); _, row = transition_placement(db, school_group_id=group_id,
            student_id=student_id, placement_id=placement_id, transition_at=transition_at, actor=user, **args)
        db.commit(); db.refresh(row); return JSONResponse(jsonable_encoder(placement_payload(row)), status_code=201)
    except (StudentAcademicError, TypeError, ValueError) as exc:
        db.rollback(); return _error(exc) if isinstance(exc, StudentAcademicError) else JSONResponse({"detail": "Invalid placement payload."}, status_code=400)


@router.patch("/{student_id}/placements/{placement_id}")
def placement_correct(student_id: int, placement_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "students.manage_placements")
    if denied: return denied
    branch_denied = _existing_placement_branch_denied(db, user, group_id, student_id, placement_id)
    if branch_denied: return branch_denied
    try:
        args = _placement_args(payload)
        if not auth.can_access_branch(db, user, args["branch_id"]): return JSONResponse({"detail": "Branch is outside your authorized scope."}, status_code=403)
        row = correct_placement(db, school_group_id=group_id, student_id=student_id, placement_id=placement_id, actor=user, **args)
        db.commit(); db.refresh(row); return placement_payload(row)
    except (StudentAcademicError, TypeError, ValueError) as exc:
        db.rollback(); return _error(exc) if isinstance(exc, StudentAcademicError) else JSONResponse({"detail": "Invalid placement payload."}, status_code=400)
