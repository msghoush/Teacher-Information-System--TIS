from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from student_academic_service import resolve_placement
from talent_operational_context import authorized_contexts, authorized_payload
from talent_review_candidate_service import evaluate_review_candidate
from talent_student_assessment_service import (
    TalentStudentAssessmentError, assessment_payload, can_delete_assessment,
    continue_empty_assessment_on_current_rubric,
    complete_assessment, competency_result_payload, delete_assessment,
    get_assessment, list_assessments, list_competency_results,
    mark_non_complete, overall_program_result, reassessment_requirement, remove_competency_result,
    reset_completed_assessment_for_reassessment, set_competency_result,
    start_assessment, start_assessment_for_evaluation, start_reassessment,
)

router = APIRouter(prefix="/api/talent/assessments", tags=["Talent Student Assessments"])


def _with_actions(db, user, row, payload):
    """Attach a real backend-computed capability list; never a client-side guess.

    ADR 0034: "delete" is only offered when the Assessment actually has zero
    dependent evidence/history rows AND the actor holds talent_assessments.delete.
    """
    actions = []
    if auth.has_permission(db, user, "talent_assessments.delete") and can_delete_assessment(db, assessment_id=row.id):
        actions.append("delete")
    newer_framework = reassessment_requirement(db, row)
    payload["reassessment"] = {
        "required": newer_framework is not None,
        "framework_version_id": newer_framework.id if newer_framework is not None else None,
        "framework_version_number": newer_framework.version_number if newer_framework is not None else None,
        "historical": not bool(getattr(row, "is_current", True)),
    }
    if newer_framework is not None and auth.has_permission(db, user, "talent_assessments.manage"):
        actions.append("reassess")
    if (
        row.status == "completed"
        and bool(getattr(row, "is_current", True))
        and auth.has_permission(db, user, "talent_assessments.reset_for_reassessment")
    ):
        actions.append("reset_for_reassessment")
    payload["actions"] = actions
    return payload


def _display_payload(db, user, row):
    payload = authorized_payload(db, row, assessment_payload)
    payload["overall_result"] = overall_program_result(db, row)
    return _with_actions(db, user, row, payload)


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


@router.get("/contexts")
def assessment_contexts(request: Request, program_id: int | None = Query(None),
                        academic_year_id: int | None = Query(None),
                        db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Minimal Evaluation contexts for the normal Student Assessments UI.

    ADR 0035 deliberately avoids requiring Cycle-management/view permissions
    just to choose an Evaluation and assess enrolled Students.
    """
    _, group_id, denied = _authorize(request, db, current_user, "talent_assessments.view")
    if denied:
        return denied
    query = db.query(models.TalentAssessmentCycle).filter_by(school_group_id=group_id)
    if program_id is not None:
        query = query.filter_by(program_id=program_id)
    if academic_year_id is not None:
        query = query.filter_by(academic_year_id=academic_year_id)
    # Evaluation Plan sequence is the canonical display order. Fall back to
    # deterministic creation/id order only for legacy unlinked Cycles.
    query = query.outerjoin(
        models.TalentPlannedEvaluationPeriod,
        models.TalentAssessmentCycle.planned_evaluation_period_id == models.TalentPlannedEvaluationPeriod.id,
    )
    rows = query.order_by(
        case((models.TalentPlannedEvaluationPeriod.sequence.is_(None), 1), else_=0),
        models.TalentPlannedEvaluationPeriod.sequence.asc(),
        models.TalentAssessmentCycle.created_at.asc(),
        models.TalentAssessmentCycle.id.asc(),
    ).all()
    private_cycle_ids = {
        row[0] for row in db.query(models.TalentStudentAssessment.cycle_id).filter(
            models.TalentStudentAssessment.school_group_id == group_id,
            models.TalentStudentAssessment.evaluation_context_cycle_id.isnot(None),
            models.TalentStudentAssessment.cycle_id != models.TalentStudentAssessment.evaluation_context_cycle_id,
        ).all()
    }
    rows = [row for row in rows if row.id not in private_cycle_ids]
    period_ids = {row.planned_evaluation_period_id for row in rows if row.planned_evaluation_period_id is not None}
    periods = {
        row.id: row for row in db.query(models.TalentPlannedEvaluationPeriod).filter(
            models.TalentPlannedEvaluationPeriod.school_group_id == group_id,
            models.TalentPlannedEvaluationPeriod.id.in_(period_ids or [-1]),
        ).all()
    }
    return [{
        "id": row.id,
        "program_id": row.program_id,
        "academic_year_id": row.academic_year_id,
        "framework_version_id": row.framework_version_id,
        "title": row.title,
        "evaluation_period_id": row.planned_evaluation_period_id,
        "evaluation_label": periods[row.planned_evaluation_period_id].label if row.planned_evaluation_period_id in periods else row.title,
        "evaluation_sequence": periods[row.planned_evaluation_period_id].sequence if row.planned_evaluation_period_id in periods else None,
    } for row in rows]


@router.post("")
def assessments_start(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    try:
        cycle_id = int(payload.get("cycle_id"))
    except (TypeError, ValueError):
        return JSONResponse({"detail": "Invalid Assessment payload.", "code": "invalid_input"}, status_code=400)

    # ADR 0035: the normal path starts from a Student's current Academic
    # Placement, not from a pre-frozen population-member id. The legacy member
    # form remains accepted for backward compatibility with existing clients.
    student_id = payload.get("student_id")
    member_id = payload.get("cycle_population_member_id")
    if student_id is None and member_id is None:
        return JSONResponse({"detail": "Choose a Student to assess.", "code": "invalid_input"}, status_code=400)

    if student_id is not None:
        try:
            student_id = int(student_id)
        except (TypeError, ValueError):
            return JSONResponse({"detail": "Invalid Student.", "code": "invalid_input"}, status_code=400)
        cycle = db.query(models.TalentAssessmentCycle).filter_by(
            id=cycle_id, school_group_id=group_id
        ).one_or_none()
        if cycle is None:
            return JSONResponse({"detail": "Talent Assessment context was not found.", "code": "not_found"}, status_code=404)
        placement = resolve_placement(
            db, school_group_id=group_id, student_id=student_id,
            academic_year_id=cycle.academic_year_id, at=datetime.utcnow(),
        )
        if placement is not None and not auth.can_access_all_branches(user) and placement.branch_id not in _visible_branch_ids(db, user):
            return JSONResponse({"detail": "Assessment is outside your authorized Branch scope."}, status_code=403)
        return _run(db, lambda: _display_payload(db, user, start_assessment_for_evaluation(
            db, school_group_id=group_id, evaluation_cycle_id=cycle_id,
            student_id=student_id, actor=user,
        )), created=True)

    try:
        member_id = int(member_id)
    except (TypeError, ValueError):
        return JSONResponse({"detail": "Invalid Assessment payload.", "code": "invalid_input"}, status_code=400)
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=member_id, school_group_id=group_id, cycle_id=cycle_id,
    ).one_or_none()
    if member is None:
        return JSONResponse({"detail": "Student Assessment context is unavailable.", "code": "invalid_student_context"}, status_code=400)
    if not auth.can_access_all_branches(user) and member.branch_id not in _visible_branch_ids(db, user):
        return JSONResponse({"detail": "Assessment is outside your authorized Branch scope."}, status_code=403)
    return _run(db, lambda: _display_payload(db, user, start_assessment(
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
    contexts = authorized_contexts(db, group_id, rows)
    return [_with_actions(db, user, row, {
        **assessment_payload(row),
        "context": contexts[row.id],
        "overall_result": overall_program_result(db, row),
    }) for row in rows]


@router.get("/{assessment_id}")
def assessments_read(assessment_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.view")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    return error or _display_payload(db, user, assessment)


@router.post("/{assessment_id}/continue")
def assessments_continue(assessment_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Refresh only a zero-result current In Progress attempt to the latest rubric."""
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: _display_payload(
        db, user, continue_empty_assessment_on_current_rubric(
            db, school_group_id=group_id, assessment_id=assessment.id, actor=user
        )
    ))


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
        "assessment": _display_payload(db, user, get_assessment(db, school_group_id=group_id, assessment_id=assessment.id)),
    })


@router.delete("/{assessment_id}/competency-results/{framework_competency_id}")
def competency_results_remove(assessment_id: int, framework_competency_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: _display_payload(db, user, remove_competency_result(
        db, school_group_id=group_id, assessment_id=assessment.id,
        framework_competency_id=framework_competency_id,
        expected_revision=expected_revision, actor=user,
    )))


@router.post("/{assessment_id}/reassess")
def assessments_reassess(assessment_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.manage")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(
        db,
        lambda: _display_payload(
            db, user, start_reassessment(
                db, school_group_id=group_id, assessment_id=assessment.id, actor=user
            )
        ),
        created=True,
    )


@router.post("/{assessment_id}/reset-for-reassessment")
def assessments_reset_for_reassessment(
    assessment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user, group_id, denied = _authorize(
        request, db, current_user, "talent_assessments.reset_for_reassessment"
    )
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(
        db,
        lambda: _display_payload(
            db,
            user,
            reset_completed_assessment_for_reassessment(
                db, school_group_id=group_id, assessment_id=assessment.id, actor=user
            ),
        ),
    )


@router.post("/{assessment_id}/complete")
def assessments_complete(assessment_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.complete")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    def work():
        completed = complete_assessment(
            db, school_group_id=group_id, assessment_id=assessment.id,
            expected_revision=int(payload.get("expected_revision")), actor=user,
        )
        # Completion deterministically evaluates the existing Framework policy.
        # No policy/non-qualifying outcome still leaves the Student visible in
        # Talent Review through the completed-Assessment workspace projection.
        evaluate_review_candidate(
            db, school_group_id=group_id, assessment_id=completed.id, actor=user
        )
        return _display_payload(db, user, completed)
    return _run(db, work)


@router.post("/{assessment_id}/incomplete")
def assessments_incomplete(assessment_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.complete")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: _display_payload(db, user, mark_non_complete(
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
    return _run(db, lambda: _display_payload(db, user, mark_non_complete(
        db, school_group_id=group_id, assessment_id=assessment.id,
        expected_revision=int(payload.get("expected_revision")), status="insufficient_evidence", actor=user,
    )))


@router.delete("/{assessment_id}")
def assessments_delete(assessment_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """ADR 0034 scoped exception: hard-delete a Student Assessment with zero dependent evidence.

    Any Assessment with a recorded competency result, Review Candidate, Official
    Identification decision, or Educator Input is rejected with a clear error -
    never a silent no-op. Deleting the Assessment removes only the Assessment
    record itself; it never touches Cycle population members, Student placement
    history, or other Assessments.
    """
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.delete")
    if denied:
        return denied
    assessment, error = _read_assessment(db, group_id, user, assessment_id)
    if error:
        return error
    return _run(db, lambda: {"id": delete_assessment(db, school_group_id=group_id, assessment_id=assessment.id, actor=user), "deleted": True})