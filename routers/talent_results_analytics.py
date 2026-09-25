"""M18b-1 Results & Analytics backend contract API.

One coherent route family (never one endpoint per card) returning the
selected analytics family with shared scope/filter context. See
``talent_results_analytics_service.py`` for the full contract decision.

Families:

- ``learning_style``  - Student-domain-wide (never Program-scoped), reuses
  the exact same governed functions as the pre-existing
  ``/students/analytics/learning-style-distribution`` route, gated on the
  same ``students.view`` permission (no new permission, no new computation).
- ``classification``/``talented`` - Program+AcademicYear-bound, reuse the
  existing M9 ``talent_analytics_service`` context/filter/scope
  architecture and are gated on the existing ``talent_analytics.view``
  permission, exactly like every other Talent analytics route.

``competency`` and ``progress`` are intentionally NOT served here - see the
module docstring in ``talent_results_analytics_service.py`` for why the
pre-existing ``/api/talent/analytics/.../rubric-distribution`` and
``/api/talent/evaluation-progress/...`` routes already satisfy those two
families and are not duplicated.
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
import talent_results_analytics_service as results_svc
from auth import get_current_user
from dependencies import get_db, get_m10_organization_analytics_db
from student_learning_style_analytics import build_distribution as build_learning_style_distribution
from student_learning_style_analytics import resolve_population as resolve_learning_style_population
from talent_analytics_privacy import resolve_privacy_policy_provider
from talent_dashboard_service import build_dashboard, DashboardError

router = APIRouter(prefix="/api/talent/results-analytics", tags=["Talent Results Analytics"])

_FILTER_KEYS = ("period_id", "cycle_id", "branch_id", "grade", "section_id", "framework_version_id")


@router.get('/academic-years/{academic_year_id}/dashboard')
def dashboard(academic_year_id: int, request: Request,
              db: Session = Depends(get_m10_organization_analytics_db), current_user=Depends(get_current_user),
              policy=Depends(resolve_privacy_policy_provider)):
    user, denied = authorization.require_any_permission(
        request, db, 'talent_analytics.view', current_user=current_user, page_key='talent_results_analytics',
    )
    if denied:
        return denied
    group_id = _scope(db, user)
    if not group_id:
        return JSONResponse({'detail': 'Select an organization scope.'}, status_code=403)
    keys = ('branch_id', 'grade_level', 'section_id', 'program_id', 'period_id', 'classification',
            'compare_by', 'compare_ids', 'competency_id', 'rubric_id')
    filters = {key: request.query_params.get(key) for key in keys}
    try:
        payload = build_dashboard(
            db, group_id=int(group_id), year_id=academic_year_id,
            visible_branches=_visible_branches(db, user), filters=filters, policy=policy,
            learning_style_allowed=auth.has_permission(db, user, 'students.view', school_group_id=int(group_id)),
        )
    except (DashboardError, ValueError) as exc:
        return JSONResponse({'detail': str(exc), 'code': 'invalid_filter'}, status_code=400)
    return jsonable_encoder(payload)


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _visible_branches(db, user):
    # Batch 1 closure: organization scope is bounded by the active global Branch.
    return branch_scope.visible_branch_ids_or_none(db, user)


def _fail_closed():
    return JSONResponse({"detail": "Analytics is unavailable.", "code": "analytics_unavailable"}, status_code=503)


def _error(exc):
    status = 404 if exc.code == "not_found" else 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


@router.get("/academic-years/{academic_year_id}/learning-style")
def learning_style(academic_year_id: int, request: Request,
                    branch_id: int | None = Query(None), grade_level: str | None = Query(None),
                    section_name: str | None = Query(None),
                    db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Family 1. ``academic_year_id`` is accepted for URL-shape symmetry with
    the Program-bound families only; Learning Style population resolution is
    Student-domain-wide by design (ADR 0031/M14) and never Program/Cycle/
    Academic-Year filtered - see ``student_learning_style_analytics.py``.
    Acceptance C: authorized Student-domain aggregation; the Talent small-cell
    suppression pipeline is deliberately not applied to this family (the other
    families below keep it). The denominator includes Unassigned Students.
    """
    user, denied = authorization.require_any_permission(
        request, db, "students.view", current_user=current_user, page_key="talent_results_analytics",
    )
    if denied:
        return denied
    group_id = _scope(db, user)
    if not group_id:
        return JSONResponse({"detail": "Select an organization scope.", "code": "organization_scope_required"}, status_code=403)
    # Batch 1 closure: the active global Branch is a hard ceiling. An omitted
    # Branch resolves to it (never organization-wide); another Branch is rejected.
    ceiling = branch_scope.talent_branch_ceiling(user)
    if ceiling is not None:
        if branch_id is not None and int(branch_id) != ceiling:
            return JSONResponse({"detail": "Branch is outside your authorized scope.", "code": "invalid_filter"}, status_code=403)
        branch_id = ceiling
    rows = resolve_learning_style_population(
        db, school_group_id=group_id, user=user, branch_id=branch_id,
        grade_level=grade_level, section_name=section_name,
    )
    if rows is None:
        return JSONResponse({"detail": "Branch is outside your authorized scope.", "code": "invalid_filter"}, status_code=403)
    return jsonable_encoder({
        "family": "learning_style",
        "academic_year_id": academic_year_id,
        "distribution": build_learning_style_distribution(rows),
    })


def _authorize_program_scope(request, db, user, program_id, academic_year_id):
    user, denied = authorization.require_any_permission(
        request, db, "talent_analytics.view", current_user=user, page_key="talent_results_analytics",
    )
    if denied:
        return None, None, None, None, denied
    group_id = _scope(db, user)
    if not group_id:
        return user, None, None, None, JSONResponse(
            {"detail": "Select an organization scope.", "code": "organization_scope_required"}, status_code=403,
        )
    try:
        ctx = svc.resolve_context(db, school_group_id=int(group_id), program_id=program_id, academic_year_id=academic_year_id)
    except svc.TalentAnalyticsError as exc:
        return user, int(group_id), None, None, _error(exc)
    visible_branch_ids = _visible_branches(db, user)
    return user, int(group_id), ctx, visible_branch_ids, None


def _resolve_filters(request, db, ctx, visible_branch_ids):
    raw = {key: request.query_params.get(key) for key in _FILTER_KEYS}
    validation_branch_ids = visible_branch_ids if visible_branch_ids is not None else {
        row[0] for row in db.query(models.Branch.id).filter_by(school_group_id=ctx.school_group_id).all()
    }
    return svc.resolve_filters(
        ctx, raw, db=db, branch_scope=validation_branch_ids,
        has_candidate_permission=False, has_identification_permission=False,
    )


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/classification")
def classification(program_id: int, academic_year_id: int, request: Request,
                    classification: str | None = Query(None),
                    db: Session = Depends(get_db), current_user=Depends(get_current_user),
                    policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, denied = _authorize_program_scope(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters(request, db, ctx, visible_branch_ids)
        payload = results_svc.classification_family(
            db, ctx, filters, visible_branch_ids, policy, classification_filter=classification,
        )
    except (svc.TalentAnalyticsError, results_svc.ResultsAnalyticsError) as exc:
        return _error(exc)
    return jsonable_encoder({
        "program_id": program_id, "academic_year_id": academic_year_id,
        "privacy_policy_version": policy.privacy_policy_version, **payload,
    })


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/talented")
def talented(program_id: int, academic_year_id: int, request: Request,
             db: Session = Depends(get_db), current_user=Depends(get_current_user),
             policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, denied = _authorize_program_scope(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters(request, db, ctx, visible_branch_ids)
        payload = results_svc.talented_family(db, ctx, filters, visible_branch_ids, policy)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)
    return jsonable_encoder({
        "program_id": program_id, "academic_year_id": academic_year_id,
        "privacy_policy_version": policy.privacy_policy_version, **payload,
    })
