"""M4 Authoritative Evaluation Progress API.

Student Evaluation Progress is governed by the existing
``talent_learner_profiles.view`` permission plus frozen-historical-Branch
scope (owner-ratified M4 Decision 2: normal Student/Talent authorization,
never aggregate cohort-size privacy suppression). Branch/Organization
Evaluation Progress and the seven approved Branch comparison metrics reuse
the existing ``talent_analytics.view`` aggregate permission, exactly like
the M9/M10 analytics routers, and are fully privacy-gated
(``talent_evaluation_progress_service.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import auth
import talent_branch_scope as branch_scope
import authorization
import models
import talent_analytics_service as svc
import talent_evaluation_progress_service as progress_svc
from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import resolve_privacy_policy_provider

router = APIRouter(prefix="/api/talent/evaluation-progress", tags=["Talent Evaluation Progress"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _visible_branches(db, user):
    # Batch 1 closure: organization scope is bounded by the active global Branch.
    return branch_scope.visible_branch_ids_or_none(db, user)


def _fail_closed():
    return JSONResponse({"detail": "Analytics are unavailable.", "code": "analytics_query_failed"}, status_code=503)


def _error(exc):
    status = 404 if exc.code == "not_found" else 403 if exc.code == "permission_denied" else 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _resolve_context(request, db, user, program_id, academic_year_id, permission_key):
    user, denied = authorization.require_any_permission(request, db, permission_key, current_user=user, page_key="talent_evaluation_progress")
    if denied:
        return None, None, None, None, denied
    group_id = _scope(db, user)
    if not group_id:
        return user, None, None, None, JSONResponse({"detail": "Select an organization scope.", "code": "organization_scope_required"}, status_code=403)
    try:
        ctx = svc.resolve_context(db, school_group_id=int(group_id), program_id=program_id, academic_year_id=academic_year_id)
    except svc.TalentAnalyticsError as exc:
        return user, int(group_id), None, None, _error(exc)
    visible_branch_ids = _visible_branches(db, user)
    return user, int(group_id), ctx, visible_branch_ids, None


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/students/{student_id}")
def student_progress(program_id: int, academic_year_id: int, student_id: int, request: Request,
                      db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, ctx, visible_branch_ids, denied = _resolve_context(
        request, db, current_user, program_id, academic_year_id, "talent_learner_profiles.view",
    )
    if denied:
        return denied
    student = progress_svc.resolve_student_progress_access(
        db, school_group_id=group_id, program_id=program_id, academic_year_id=academic_year_id,
        student_id=student_id, visible_branch_ids=visible_branch_ids,
    )
    if student is None:
        return JSONResponse({"detail": "Student was not found.", "code": "not_found"}, status_code=404)
    payload = progress_svc.build_student_progress(db, ctx, student_id=student_id)
    return jsonable_encoder({"program_id": program_id, "academic_year_id": academic_year_id, **payload})


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/branches/{branch_id}")
def branch_progress(program_id: int, academic_year_id: int, branch_id: int, request: Request,
                     db: Session = Depends(get_db), current_user=Depends(get_current_user),
                     policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, denied = _resolve_context(
        request, db, current_user, program_id, academic_year_id, "talent_analytics.view",
    )
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    if not auth.can_access_branch(db, user, branch_id) or not branch_scope.branch_within_ceiling(user, branch_id):
        return JSONResponse({"detail": "Branch was not found.", "code": "not_found"}, status_code=404)
    payload = progress_svc.build_branch_progress(db, ctx, branch_id=branch_id, visible_branch_ids=visible_branch_ids, policy=policy)
    return jsonable_encoder({"program_id": program_id, "academic_year_id": academic_year_id,
                              "privacy_policy_version": policy.privacy_policy_version, **payload})


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/organization")
def organization_progress(program_id: int, academic_year_id: int, request: Request,
                           db: Session = Depends(get_db), current_user=Depends(get_current_user),
                           policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, denied = _resolve_context(
        request, db, current_user, program_id, academic_year_id, "talent_analytics.view",
    )
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    payload = progress_svc.build_organization_progress(db, ctx, visible_branch_ids=visible_branch_ids, policy=policy)
    return jsonable_encoder({"program_id": program_id, "academic_year_id": academic_year_id,
                              "privacy_policy_version": policy.privacy_policy_version, **payload})


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/branch-comparison")
def branch_comparison(program_id: int, academic_year_id: int, request: Request,
                       metric: str = Query(...),
                       db: Session = Depends(get_db), current_user=Depends(get_current_user),
                       policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, denied = _resolve_context(
        request, db, current_user, program_id, academic_year_id, "talent_analytics.view",
    )
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    has_candidate = auth.has_permission(db, user, "talent_review_candidates.view", school_group_id=group_id)
    has_identification = auth.has_permission(db, user, "talent_official_identifications.view", school_group_id=group_id)
    try:
        payload = progress_svc.branch_comparison_metric(
            db, ctx, metric=metric, visible_branch_ids=visible_branch_ids,
            has_candidate_permission=has_candidate, has_identification_permission=has_identification,
            policy=policy,
        )
    except progress_svc.EvaluationProgressError as exc:
        return _error(exc)
    return jsonable_encoder({"program_id": program_id, "academic_year_id": academic_year_id,
                              "privacy_policy_version": policy.privacy_policy_version, **payload})
