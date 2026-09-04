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
from talent_review_candidate_service import (
    TalentReviewCandidateError, candidate_payload, evaluate_review_candidate,
    get_candidate, list_candidates, mark_reviewed,
)

router = APIRouter(prefix="/api/talent/review-candidates", tags=["Talent Review Candidates"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, key):
    user, denied = authorization.require_any_permission(
        request, db, key, current_user=user, page_key="talent_review_candidates"
    )
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _visible_branch_ids(db, user):
    return {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}


def _member_branch(db, school_group_id, cycle_population_member_id):
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=cycle_population_member_id, school_group_id=school_group_id,
    ).one_or_none()
    return member.branch_id if member else None


def _assessment_authorized(db, user, school_group_id, assessment_id):
    assessment = db.query(models.TalentStudentAssessment).filter_by(
        id=assessment_id, school_group_id=school_group_id,
    ).one_or_none()
    if assessment is None:
        return None, False
    if auth.can_access_all_branches(user):
        return assessment, True
    branch_id = _member_branch(db, school_group_id, assessment.cycle_population_member_id)
    return assessment, branch_id is not None and branch_id in _visible_branch_ids(db, user)


def _candidate_authorized(db, user, candidate):
    if auth.can_access_all_branches(user):
        return True
    branch_id = _member_branch(db, candidate.school_group_id, candidate.cycle_population_member_id)
    return branch_id is not None and branch_id in _visible_branch_ids(db, user)


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {"assessment_not_completed", "already_reviewed"}:
        status = 409
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


@router.post("/evaluate")
def review_candidates_evaluate(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_review_candidates.manage")
    if denied:
        return denied
    try:
        assessment_id = int(payload.get("assessment_id"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "Invalid Review Candidate evaluation payload.", "code": "invalid_input"}, status_code=400)
    assessment, authorized = _assessment_authorized(db, user, group_id, assessment_id)
    if assessment is None:
        return JSONResponse({"detail": "Student Assessment was not found.", "code": "not_found"}, status_code=404)
    if not authorized:
        return JSONResponse({"detail": "Student Assessment was not found.", "code": "not_found"}, status_code=404)
    try:
        candidate, outcome = evaluate_review_candidate(db, school_group_id=group_id, assessment_id=assessment_id, actor=user)
        db.commit()
    except TalentReviewCandidateError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent Review Candidate evaluation.", "code": "candidate_conflict"}, status_code=409)
    status_code = 201 if outcome == "qualified" else 200
    body = {"outcome": outcome, "candidate": candidate_payload(candidate) if candidate else None}
    return JSONResponse(jsonable_encoder(body), status_code=status_code)


@router.post("/{candidate_id}/review")
def review_candidates_mark_reviewed(candidate_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_review_candidates.manage")
    if denied:
        return denied
    try:
        candidate = get_candidate(db, school_group_id=group_id, candidate_id=candidate_id)
    except TalentReviewCandidateError as exc:
        return _error(exc)
    if not _candidate_authorized(db, user, candidate):
        return JSONResponse({"detail": "Review Candidate was not found.", "code": "not_found"}, status_code=404)
    try:
        candidate = mark_reviewed(db, school_group_id=group_id, candidate_id=candidate_id, actor=user)
        db.commit()
    except TalentReviewCandidateError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent Review Candidate review.", "code": "candidate_conflict"}, status_code=409)
    return candidate_payload(candidate)


@router.get("")
def review_candidates_list(request: Request, cycle_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_review_candidates.view")
    if denied:
        return denied
    rows = list_candidates(db, school_group_id=group_id, cycle_id=cycle_id)
    if not auth.can_access_all_branches(user):
        visible = _visible_branch_ids(db, user)
        member_ids = {row[0] for row in db.query(models.TalentAssessmentCyclePopulationMember.id).filter(
            models.TalentAssessmentCyclePopulationMember.school_group_id == group_id,
            models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible or [-1]),
        ).all()}
        rows = [row for row in rows if row.cycle_population_member_id in member_ids]
    return [candidate_payload(row) for row in rows]


@router.get("/{candidate_id}")
def review_candidates_read(candidate_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_review_candidates.view")
    if denied:
        return denied
    try:
        candidate = get_candidate(db, school_group_id=group_id, candidate_id=candidate_id)
    except TalentReviewCandidateError as exc:
        return _error(exc)
    if not _candidate_authorized(db, user, candidate):
        return JSONResponse({"detail": "Review Candidate was not found.", "code": "not_found"}, status_code=404)
    return candidate_payload(candidate)
