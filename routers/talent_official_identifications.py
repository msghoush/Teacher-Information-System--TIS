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
from talent_official_identification_service import (
    TalentOfficialIdentificationError, get_identification, identification_payload,
    list_identifications, record_decision,
)

router = APIRouter(prefix="/api/talent/official-identifications", tags=["Talent Official Identifications"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, key):
    user, denied = authorization.require_any_permission(
        request, db, key, current_user=user, page_key="talent_official_identifications"
    )
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _organization_authorized(user):
    # Decision 6: recording an Official Identification requires BOTH the
    # dedicated .record permission AND organization/global access scope - a
    # Branch-scoped actor may never record a decision even if somehow granted
    # the permission. This mirrors M4's Cycle `.govern` organization-authority
    # gate exactly (`auth.can_access_all_branches` is organization/global scope).
    return auth.can_access_all_branches(user)


def _visible_branch_ids(db, user):
    return {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}


def _member_branch(db, school_group_id, cycle_population_member_id):
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=cycle_population_member_id, school_group_id=school_group_id,
    ).one_or_none()
    return member.branch_id if member else None


def _identification_authorized(db, user, row):
    if auth.can_access_all_branches(user):
        return True
    branch_id = _member_branch(db, row.school_group_id, row.cycle_population_member_id)
    return branch_id is not None and branch_id in _visible_branch_ids(db, user)


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {"candidate_not_reviewed", "already_decided"}:
        status = 409
    elif exc.code == "organization_authority_required":
        status = 403
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


@router.post("")
def official_identifications_record(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_official_identifications.record")
    if denied:
        return denied
    try:
        review_candidate_id = int(payload.get("review_candidate_id"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "Invalid Official Identification payload.", "code": "invalid_input"}, status_code=400)
    decision = payload.get("decision")
    rationale = payload.get("rationale")
    try:
        row = record_decision(
            db, school_group_id=group_id, review_candidate_id=review_candidate_id, decision=decision,
            rationale=rationale, organization_authorized=_organization_authorized(user), actor=user,
        )
        db.commit()
    except TalentOfficialIdentificationError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "An Official Identification decision already exists for this Review Candidate.", "code": "identification_conflict"}, status_code=409)
    return JSONResponse(jsonable_encoder(identification_payload(row)), status_code=201)


@router.get("")
def official_identifications_list(request: Request, cycle_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_official_identifications.view")
    if denied:
        return denied
    rows = list_identifications(db, school_group_id=group_id, cycle_id=cycle_id)
    if not auth.can_access_all_branches(user):
        visible = _visible_branch_ids(db, user)
        member_ids = {row[0] for row in db.query(models.TalentAssessmentCyclePopulationMember.id).filter(
            models.TalentAssessmentCyclePopulationMember.school_group_id == group_id,
            models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible or [-1]),
        ).all()}
        rows = [row for row in rows if row.cycle_population_member_id in member_ids]
    return [identification_payload(row) for row in rows]


@router.get("/{identification_id}")
def official_identifications_read(identification_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_official_identifications.view")
    if denied:
        return denied
    try:
        row = get_identification(db, school_group_id=group_id, identification_id=identification_id)
    except TalentOfficialIdentificationError as exc:
        return _error(exc)
    if not _identification_authorized(db, user, row):
        return JSONResponse({"detail": "Official Identification was not found.", "code": "not_found"}, status_code=404)
    return identification_payload(row)
