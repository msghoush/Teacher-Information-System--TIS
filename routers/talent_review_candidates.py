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
from talent_operational_context import authorized_contexts, authorized_payload
from talent_student_assessment_service import assessment_payload, overall_program_result, reassessment_requirement
from talent_review_candidate_service import (
    TalentReviewCandidateError, candidate_payload, evaluate_review_candidate,
    get_candidate, list_candidates, mark_reviewed,
)

router = APIRouter(prefix="/api/talent/review-candidates", tags=["Talent Review Candidates"])


def _display_payload(db, row):
    payload = {**authorized_payload(db, row, candidate_payload), "rubric_level": _rubric_level(db, row)}
    assessment = db.query(models.TalentStudentAssessment).filter_by(
        id=row.assessment_id, school_group_id=row.school_group_id
    ).one_or_none()
    payload["overall_result"] = overall_program_result(db, assessment) if assessment is not None else None
    return payload


def _rubric_level(db, row):
    """Highest rubric level actually recorded on the candidate Assessment.

    This is an additive read projection only. Candidate qualification continues
    to use its persisted policy evaluation and Official Identification remains
    a separate human decision.
    """
    levels = db.query(models.TalentRubricLevel).filter_by(
        school_group_id=row.school_group_id,
        framework_version_id=row.framework_version_id,
    ).order_by(models.TalentRubricLevel.display_order, models.TalentRubricLevel.id).all()
    recorded_ids = {item[0] for item in db.query(models.TalentStudentCompetencyResult.rubric_level_id).filter_by(
        school_group_id=row.school_group_id,
        assessment_id=row.assessment_id,
    ).all()}
    recorded = [level for level in levels if level.id in recorded_ids]
    if not recorded:
        return None
    level = recorded[-1]
    return {
        "id": level.id,
        "label": level.label,
        "display_order": level.display_order,
        "position": levels.index(level) + 1,
        "total_levels": len(levels),
    }


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
    body = {"outcome": outcome, "candidate": _display_payload(db, candidate) if candidate else None}
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
    return _display_payload(db, candidate)


@router.get("/workspace")
def talent_review_workspace(
    request: Request,
    cycle_id: int | None = Query(None),
    program_id: int | None = Query(None),
    academic_year_id: int | None = Query(None),
    branch_id: int | None = Query(None),
    grade_level: str | None = Query(None),
    planning_section_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """All current Completed Assessments available for educator Talent Review.

    Review Candidate and Official Identification remain separate downstream
    states. A Student is not hidden merely because no Candidate row exists.
    """
    user, group_id, denied = _authorize(request, db, current_user, "talent_review_candidates.view")
    if denied:
        return denied
    query = db.query(models.TalentStudentAssessment).filter_by(
        school_group_id=group_id, status="completed", is_current=True,
    )
    if academic_year_id is not None:
        query = query.filter(models.TalentStudentAssessment.academic_year_id == academic_year_id)
    if program_id is not None:
        query = query.filter(models.TalentStudentAssessment.program_id == program_id)
    if cycle_id is not None:
        query = query.filter(
            (models.TalentStudentAssessment.evaluation_context_cycle_id == cycle_id)
            | (
                models.TalentStudentAssessment.evaluation_context_cycle_id.is_(None)
                & (models.TalentStudentAssessment.cycle_id == cycle_id)
            )
        )
    rows = query.order_by(
        models.TalentStudentAssessment.program_id,
        models.TalentStudentAssessment.student_id,
        models.TalentStudentAssessment.id,
    ).all()

    if branch_id is not None or grade_level is not None or planning_section_id is not None:
        member_ids = {row.cycle_population_member_id for row in rows}
        members = {
            row.id: row
            for row in db.query(models.TalentAssessmentCyclePopulationMember).filter(
                models.TalentAssessmentCyclePopulationMember.school_group_id == group_id,
                models.TalentAssessmentCyclePopulationMember.id.in_(member_ids or [-1]),
            ).all()
        }
        normalized_grade = str(grade_level or "").strip().upper()
        filtered = []
        for assessment in rows:
            member = members.get(assessment.cycle_population_member_id)
            if member is None:
                continue
            if branch_id is not None and member.branch_id != branch_id:
                continue
            if normalized_grade and str(member.grade_level or "").strip().upper() != normalized_grade:
                continue
            if planning_section_id is not None and member.planning_section_id != planning_section_id:
                continue
            filtered.append(assessment)
        rows = filtered

    if not auth.can_access_all_branches(user):
        visible = _visible_branch_ids(db, user)
        member_ids = {row[0] for row in db.query(models.TalentAssessmentCyclePopulationMember.id).filter(
            models.TalentAssessmentCyclePopulationMember.school_group_id == group_id,
            models.TalentAssessmentCyclePopulationMember.branch_id.in_(visible or [-1]),
        ).all()}
        rows = [row for row in rows if row.cycle_population_member_id in member_ids]

    contexts = authorized_contexts(db, group_id, rows)
    assessment_ids = [row.id for row in rows]
    candidates = db.query(models.TalentReviewCandidate).filter(
        models.TalentReviewCandidate.school_group_id == group_id,
        models.TalentReviewCandidate.assessment_id.in_(assessment_ids or [-1]),
    ).all()
    candidate_by_assessment = {row.assessment_id: row for row in candidates}
    result = []
    for assessment in rows:
        candidate = candidate_by_assessment.get(assessment.id)
        newer = reassessment_requirement(db, assessment)
        result.append({
            **assessment_payload(assessment),
            "context": contexts[assessment.id],
            "overall_result": overall_program_result(db, assessment),
            "reassessment": {
                "required": newer is not None,
                "framework_version_id": newer.id if newer is not None else None,
                "framework_version_number": newer.version_number if newer is not None else None,
            },
            "candidate": candidate_payload(candidate) if candidate is not None else None,
            "review_status": candidate.status if candidate is not None else "not_candidate",
        })
    return result


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
    contexts = authorized_contexts(db, group_id, rows)
    result = []
    for row in rows:
        assessment = db.query(models.TalentStudentAssessment).filter_by(
            id=row.assessment_id, school_group_id=row.school_group_id
        ).one_or_none()
        result.append({
            **candidate_payload(row),
            "context": contexts[row.id],
            "rubric_level": _rubric_level(db, row),
            "overall_result": overall_program_result(db, assessment) if assessment is not None else None,
        })
    return result


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
    return _display_payload(db, candidate)
