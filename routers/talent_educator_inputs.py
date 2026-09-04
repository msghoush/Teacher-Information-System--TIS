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
from talent_educator_input_service import (
    TalentEducatorInputError, add_input, amend_input, get_input, input_history,
    input_payload, list_inputs,
)

router = APIRouter(prefix="/api/talent/educator-inputs", tags=["Talent Educator Inputs"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, key):
    user, denied = authorization.require_any_permission(
        request, db, key, current_user=user, page_key="talent_educator_inputs"
    )
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _visible_branch_ids(db, user):
    return {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}


def _input_authorized(db, user, row):
    # Decision 12/15: Branch-scoped access uses the PERSISTED HISTORICAL Branch
    # context stored on the Educator Input row itself (from Decision 8's
    # resolution) - never current Student Placement, so a later transfer never
    # reinterprets an already-recorded Educator Input's access.
    if auth.can_access_all_branches(user):
        return True
    return row.branch_id in _visible_branch_ids(db, user)


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {
        "no_historical_placement", "already_superseded", "cross_student_supersession",
        "cross_program_supersession", "invalid_supersession",
    }:
        status = 409
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _parse_datetime(value, field, *, required=True):
    from datetime import datetime, timezone
    if value in (None, "") and not required:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError) as exc:
        raise TalentEducatorInputError("invalid_input", f"{field} must be an ISO-8601 date-time.") from exc


@router.post("")
def educator_inputs_add(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_educator_inputs.add")
    if denied:
        return denied
    try:
        student_id = int(payload.get("student_id"))
        program_id = int(payload.get("program_id"))
        academic_year_id = int(payload.get("academic_year_id"))
        observed_at = _parse_datetime(payload.get("observed_at"), "observed_at")
        cycle_id = payload.get("cycle_id")
        cycle_population_member_id = payload.get("cycle_population_member_id")
        assessment_id = payload.get("assessment_id")
        review_candidate_id = payload.get("review_candidate_id")
        row = add_input(
            db, school_group_id=group_id, student_id=student_id, program_id=program_id,
            academic_year_id=academic_year_id, observed_at=observed_at,
            category=payload.get("category"), content=payload.get("content"),
            cycle_id=int(cycle_id) if cycle_id not in (None, "") else None,
            cycle_population_member_id=int(cycle_population_member_id) if cycle_population_member_id not in (None, "") else None,
            assessment_id=int(assessment_id) if assessment_id not in (None, "") else None,
            review_candidate_id=int(review_candidate_id) if review_candidate_id not in (None, "") else None,
            actor=user,
        )
        if not _input_authorized(db, user, row):
            db.rollback()
            return JSONResponse({"detail": "Educator Input was not found.", "code": "not_found"}, status_code=404)
        db.commit()
    except TalentEducatorInputError as exc:
        db.rollback()
        return _error(exc)
    except (TypeError, ValueError):
        db.rollback()
        return JSONResponse({"detail": "Invalid Educator Input payload.", "code": "invalid_input"}, status_code=400)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent Educator Input change.", "code": "educator_input_conflict"}, status_code=409)
    return JSONResponse(jsonable_encoder(input_payload(row)), status_code=201)


@router.post("/{input_id}/amend")
def educator_inputs_amend(input_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_educator_inputs.amend")
    if denied:
        return denied
    try:
        original = get_input(db, school_group_id=group_id, input_id=input_id)
    except TalentEducatorInputError as exc:
        return _error(exc)
    if not _input_authorized(db, user, original):
        return JSONResponse({"detail": "Educator Input was not found.", "code": "not_found"}, status_code=404)
    try:
        student_id = int(payload.get("student_id"))
        program_id = int(payload.get("program_id"))
        observed_at = _parse_datetime(payload.get("observed_at"), "observed_at", required=False)
        cycle_id = payload.get("cycle_id")
        cycle_population_member_id = payload.get("cycle_population_member_id")
        assessment_id = payload.get("assessment_id")
        review_candidate_id = payload.get("review_candidate_id")
        row, _ = amend_input(
            db, school_group_id=group_id, student_id=student_id, program_id=program_id,
            supersedes_educator_input_id=input_id, category=payload.get("category"),
            content=payload.get("content"), observed_at=observed_at,
            cycle_id=int(cycle_id) if cycle_id not in (None, "") else None,
            cycle_population_member_id=int(cycle_population_member_id) if cycle_population_member_id not in (None, "") else None,
            assessment_id=int(assessment_id) if assessment_id not in (None, "") else None,
            review_candidate_id=int(review_candidate_id) if review_candidate_id not in (None, "") else None,
            actor=user,
        )
        if not _input_authorized(db, user, row):
            db.rollback()
            return JSONResponse({"detail": "Educator Input was not found.", "code": "not_found"}, status_code=404)
        db.commit()
    except TalentEducatorInputError as exc:
        db.rollback()
        return _error(exc)
    except (TypeError, ValueError):
        db.rollback()
        return JSONResponse({"detail": "Invalid Educator Input amendment payload.", "code": "invalid_input"}, status_code=400)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent Educator Input amendment.", "code": "educator_input_conflict"}, status_code=409)
    return JSONResponse(jsonable_encoder(input_payload(row)), status_code=201)


@router.get("")
def educator_inputs_list(request: Request, student_id: int | None = Query(None), program_id: int | None = Query(None),
                         db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_educator_inputs.view")
    if denied:
        return denied
    rows = list_inputs(db, school_group_id=group_id, student_id=student_id, program_id=program_id, current_only=True)
    if not auth.can_access_all_branches(user):
        visible = _visible_branch_ids(db, user)
        rows = [row for row in rows if row.branch_id in visible]
    return [input_payload(row) for row in rows]


@router.get("/{input_id}")
def educator_inputs_read(input_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_educator_inputs.view")
    if denied:
        return denied
    try:
        row = get_input(db, school_group_id=group_id, input_id=input_id)
    except TalentEducatorInputError as exc:
        return _error(exc)
    if not _input_authorized(db, user, row):
        return JSONResponse({"detail": "Educator Input was not found.", "code": "not_found"}, status_code=404)
    return input_payload(row)


@router.get("/{input_id}/history")
def educator_inputs_history(input_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_educator_inputs.view")
    if denied:
        return denied
    try:
        row = get_input(db, school_group_id=group_id, input_id=input_id)
    except TalentEducatorInputError as exc:
        return _error(exc)
    if not _input_authorized(db, user, row):
        return JSONResponse({"detail": "Educator Input was not found.", "code": "not_found"}, status_code=404)
    chain = input_history(db, school_group_id=group_id, input_id=input_id)
    return [input_payload(item) for item in chain]
