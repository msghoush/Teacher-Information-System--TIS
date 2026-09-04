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
from talent_assessment_cycle_service import (
    TalentAssessmentCycleError, close_cycle, create_cycle, cycle_payload,
    frozen_population, get_cycle, list_cycles, open_cycle, population_fingerprint,
    population_member_payload, preview_population, update_cycle,
)

router = APIRouter(prefix="/api/talent/assessment-cycles", tags=["Talent Assessment Cycles"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, key):
    user, denied = authorization.require_any_permission(
        request, db, key, current_user=user, page_key="talent_assessment_cycles"
    )
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _organization_authorized(user):
    return auth.get_access_scope(user) in {auth.ACCESS_SCOPE_ORGANIZATION, auth.ACCESS_SCOPE_GLOBAL}


def _parse_datetime(value, field, *, required=False):
    if value in (None, "") and not required:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError) as exc:
        raise TalentAssessmentCycleError("invalid_datetime", f"{field} must be an ISO-8601 date-time.") from exc


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {"stale_cycle", "population_conflict", "invalid_lifecycle"}:
        status = 409
    elif exc.code == "organization_authority_required":
        status = 403
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _run(db, work, *, created=False):
    try:
        result = work()
        db.commit()
        return JSONResponse(jsonable_encoder(result), status_code=201 if created else 200)
    except TalentAssessmentCycleError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent or duplicate Cycle change.", "code": "cycle_conflict"}, status_code=409)
    except (TypeError, ValueError):
        db.rollback()
        return JSONResponse({"detail": "Invalid Cycle payload.", "code": "invalid_input"}, status_code=400)


def _visible_branch_ids(db, user):
    return {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}


def _student_names(db, group_id, student_ids):
    rows = db.query(models.Student).filter(
        models.Student.school_group_id == group_id,
        models.Student.id.in_(student_ids or [-1]),
    ).all()
    return {row.id: {"first_name": row.first_name, "father_name": row.father_name, "last_name": row.last_name} for row in rows}


@router.post("")
def cycles_create(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.manage")
    if denied:
        return denied
    return _run(db, lambda: cycle_payload(create_cycle(
        db, school_group_id=group_id, program_id=int(payload.get("program_id")),
        academic_year_id=int(payload.get("academic_year_id")),
        framework_version_id=int(payload.get("framework_version_id")),
        title=payload.get("title"), description=payload.get("description"),
        population_effective_at=_parse_datetime(payload.get("population_effective_at"), "population_effective_at"),
        actor=user,
    ), include_integrity=False), created=True)


@router.get("")
def cycles_list(request: Request, program_id: int | None = Query(None), academic_year_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view")
    if denied:
        return denied
    return [cycle_payload(row, include_integrity=False) for row in list_cycles(
        db, school_group_id=group_id, program_id=program_id, academic_year_id=academic_year_id
    )]


@router.get("/{cycle_id}")
def cycles_read(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view")
    if denied:
        return denied
    try:
        return cycle_payload(get_cycle(db, school_group_id=group_id, cycle_id=cycle_id), include_integrity=False)
    except TalentAssessmentCycleError as exc:
        return _error(exc)


@router.patch("/{cycle_id}")
def cycles_update(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.manage")
    if denied:
        return denied
    effective_at = "__unchanged__"
    if "population_effective_at" in payload:
        effective_at = _parse_datetime(payload.get("population_effective_at"), "population_effective_at")
    return _run(db, lambda: cycle_payload(update_cycle(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        title=payload.get("title") if "title" in payload else None,
        description=payload.get("description") if "description" in payload else None,
        population_effective_at=effective_at, actor=user,
    ), include_integrity=False))


@router.get("/{cycle_id}/population/preview")
def cycles_preview(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view_population")
    if denied:
        return denied
    try:
        cycle, population = preview_population(db, school_group_id=group_id, cycle_id=cycle_id)
    except TalentAssessmentCycleError as exc:
        return _error(exc)
    organization = _organization_authorized(user)
    if not organization:
        visible = _visible_branch_ids(db, user)
        population = [row for row in population if row["branch_id"] in visible]
    names = _student_names(db, group_id, [row["student_id"] for row in population])
    members = [{**row, **names.get(row["student_id"], {})} for row in population]
    result = {"cycle_id": cycle.id, "population_state": "preview", "scope": "organization" if organization else "authorized_branches", "is_filtered": not organization, "count": len(members), "members": members}
    if organization:
        result["population_fingerprint"] = population_fingerprint(cycle, population)
    return jsonable_encoder(result)


@router.post("/{cycle_id}/open")
def cycles_open(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.govern")
    if denied:
        return denied
    return _run(db, lambda: cycle_payload(open_cycle(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        organization_authorized=_organization_authorized(user), actor=user,
    )))


@router.post("/{cycle_id}/close")
def cycles_close(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.govern")
    if denied:
        return denied
    return _run(db, lambda: cycle_payload(close_cycle(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        organization_authorized=_organization_authorized(user), actor=user,
    )))


@router.get("/{cycle_id}/population")
def cycles_population(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view_population")
    if denied:
        return denied
    try:
        cycle, rows = frozen_population(db, school_group_id=group_id, cycle_id=cycle_id)
    except TalentAssessmentCycleError as exc:
        return _error(exc)
    organization = _organization_authorized(user)
    if not organization:
        visible = _visible_branch_ids(db, user)
        rows = [row for row in rows if row.branch_id in visible]
    names = _student_names(db, group_id, [row.student_id for row in rows])
    members = [{**population_member_payload(row), **names.get(row.student_id, {})} for row in rows]
    result = {"cycle_id": cycle.id, "population_state": "frozen", "scope": "organization" if organization else "authorized_branches", "is_filtered": not organization, "count": len(members), "members": members}
    if organization:
        result["population_count"] = cycle.population_count
        result["population_fingerprint"] = cycle.population_fingerprint
    return result
