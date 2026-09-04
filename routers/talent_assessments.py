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
from talent_student_assessment_service import (
    TalentStudentAssessmentError, assessment_payload, complete_assessment,
    competency_result_payload, get_assessment, list_assessments,
    list_competency_results, mark_non_complete, remove_competency_result,
    set_competency_result, start_assessment,
)

router = APIRouter(prefix="/api/talent/assessments", tags=["Talent Student Assessments"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, key):
    user, denied = authorization.require_any_permission(
        request, db, key, current_user=user, page_key="talent_assessments"
    )
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _visible_branch_ids(db, user):
    return {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}


def _assessment_authorized(db, user, assessment):
    if auth.can_access_all_branches(user):
        return True
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=assessment.cycle_population_member_id, school_group_id=assessment.school_group_id,
        cycle_id=assessment.cycle_id, student_id=assessment.student_id,
    ).one_or_none()
    return member is not None and member.branch_id in _visible_branch_ids(db, user)


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {"stale_assessment", "duplicate_assessment"}:
        status = 409
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _run(db, work, *, created=False):
    try:
        result = work()
        db.commit()
        return JSONResponse(jsonable_encoder(result), status_code=201 if created else 200)
    except TalentStudentAssessmentError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent or duplicate Assessment change.", "code": "assessment_conflict"}, status_code=409)
    except (TypeError, ValueError):
        db.rollback()
        return JSONResponse({"detail": "Invalid Assessment payload.", "code": "invalid_input"}, status_code=400)


def _read_assessment(db, group_id, user, assessment_id):
    try:
        assessment = get_assessment(db, school_group_id=group_id, assessment_id=assessment_id)
    except TalentStudentAssessmentError as exc:
        return None, _error(exc)
    if not _assessment_authorized(db, user, assessment):
        return None, JSONResponse({"detail": "Assessment is outside your authorized Branch scope."}, status_code=403)
    return assessment, None


@router.post("")
def assessments_start(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    try:
        cycle_id = int(payload.get("cycle_id"))
        member_id = int(payload.get("cycle_population_member_id"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "Invalid Assessment payload.", "code": "invalid_input"}, status_code=400)
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=member_id, school_group_id=group_id, cycle_id=cycle_id,
    ).one_or_none()
    if member is None:
        return JSONResponse({"detail": "Student must belong to this Cycle's frozen population.", "code": "invalid_population_member"}, status_code=400)
    if not auth.can_access_all_branches(user) and member.branch_id not in _visible_branch_ids(db, user):
        return JSONResponse({"detail": "Assessment is outside your authorized Branch scope."}, status_code=403)
    return _run(db, lambda: assessment_payload(start_assessment(
        db, school_group_id=group_id, cycle_id=cycle_id,
        cycle_population_member_id=member_id, actor=user,
    )), created=True)


@router.get("")
def assessments_list(request: Request, cycle_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.view")
    if denied:
        return denied
    rows = list_assessments(db, school_group_id=group_id, cycle_id=cycle_id)
    if not auth.can_access_all_branches(user):
        visible = _visible_branch_ids(db, user)
        member_ids = {row[0] for row in db.query(models.TalentAssessmentCyclePopulationMember.id).filter(
            models.TalentAssessmentCyclePopulationMember.school_group_id == group_id,
            models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible or [-1]),
        ).all()}
        rows = [row for row in rows if row.cycle_population_member_id in member_ids]
    return [assessment_payload(row) for row in rows]


@router.get("/{assessment_id}")
def assessments_read(assessment_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.view")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    return error or assessment_payload(assessment)


@router.get("/{assessment_id}/competency-results")
def competency_results_list(assessment_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.view")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    _, rows = list_competency_results(db, school_group_id=group_id, assessment_id=assessment.id)
    return [competency_result_payload(row) for row in rows]


@router.put("/{assessment_id}/competency-results/{framework_competency_id}")
def competency_results_set(assessment_id: int, framework_competency_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: {
        "result": competency_result_payload(set_competency_result(
            db, school_group_id=group_id, assessment_id=assessment.id,
            framework_competency_id=framework_competency_id,
            rubric_level_id=int(payload.get("rubric_level_id")),
            expected_revision=int(payload.get("expected_revision")), evidence=payload.get("evidence"), actor=user,
        )[0]),
        "assessment": assessment_payload(get_assessment(db, school_group_id=group_id, assessment_id=assessment.id)),
    })


@router.delete("/{assessment_id}/competency-results/{framework_competency_id}")
def competency_results_remove(assessment_id: int, framework_competency_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: assessment_payload(remove_competency_result(
        db, school_group_id=group_id, assessment_id=assessment.id,
        framework_competency_id=framework_competency_id,
        expected_revision=expected_revision, actor=user,
    )))


@router.post("/{assessment_id}/complete")
def assessments_complete(assessment_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.complete")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: assessment_payload(complete_assessment(
        db, school_group_id=group_id, assessment_id=assessment.id,
        expected_revision=int(payload.get("expected_revision")), actor=user,
    )))


@router.post("/{assessment_id}/incomplete")
def assessments_incomplete(assessment_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.complete")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: assessment_payload(mark_non_complete(
        db, school_group_id=group_id, assessment_id=assessment.id,
        expected_revision=int(payload.get("expected_revision")), status="incomplete", actor=user,
    )))


@router.post("/{assessment_id}/insufficient-evidence")
def assessments_insufficient_evidence(assessment_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.complete")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: assessment_payload(mark_non_complete(
        db, school_group_id=group_id, assessment_id=assessment.id,
        expected_revision=int(payload.get("expected_revision")), status="insufficient_evidence", actor=user,
    )))