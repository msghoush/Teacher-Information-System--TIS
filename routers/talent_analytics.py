"""M9 Deterministic Talent Analytics API.

Analytics permission (`talent_analytics.view`) never implies raw access to
the Plan/Cycle/Assessment/Candidate/Identification/Learner-Profile APIs -
those remain independently gated on their own existing routes. This router
composes only bounded, aggregate, privacy-filtered analytical projections.
"""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from talent_analytics_privacy import COARSENED, NO_DATA, RESTRICTED, SUPPRESSED, VISIBLE, Cell, apply_primary_privacy, derive_from_visible_cells, run_complementary_suppression
from talent_analytics_privacy import resolve_privacy_policy_provider
import talent_analytics_service as svc

router = APIRouter(prefix="/api/talent/analytics", tags=["Talent Analytics"])

_FILTER_KEYS = (
    "period_id", "cycle_id", "branch_id", "grade", "section_id", "framework_version_id",
    "competency_id", "assessment_state", "candidate_state", "identification_state",
)


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _visible_branches(db, user):
    if auth.can_access_all_branches(user):
        return None
    return {row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()}


def _permissions(db, user, group_id):
    return {
        "candidate": auth.has_permission(db, user, "talent_review_candidates.view", school_group_id=group_id),
        "identification": auth.has_permission(db, user, "talent_official_identifications.view", school_group_id=group_id),
        "students": auth.has_permission(db, user, "talent_analytics.view_students", school_group_id=group_id),
        "cycle_view": auth.has_permission(db, user, "talent_assessment_cycles.view", school_group_id=group_id),
        "learner_profile": auth.has_permission(db, user, "talent_learner_profiles.view", school_group_id=group_id),
    }


def _projection_list(perms):
    return ["base"] + [key for key, value in perms.items() if value]


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code == "invalid_filter" or exc.code == "invalid_analytics_context":
        status = 400
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _authorize(request, db, user, program_id, academic_year_id, *, require_students=False):
    keys = ["talent_analytics.view"]
    if require_students:
        keys.append("talent_analytics.view_students")
    checker = authorization.require_all_permissions if require_students else authorization.require_any_permission
    user, denied = checker(request, db, *keys, current_user=user, page_key="talent_analytics")
    if denied:
        return None, None, None, None, None, denied
    group_id = _scope(db, user)
    if not group_id:
        return user, None, None, None, None, JSONResponse({"detail": "Select an organization scope.", "code": "organization_scope_required"}, status_code=403)
    try:
        ctx = svc.resolve_context(db, school_group_id=int(group_id), program_id=program_id, academic_year_id=academic_year_id)
    except svc.TalentAnalyticsError as exc:
        return user, int(group_id), None, None, None, _error(exc)
    visible_branch_ids = _visible_branches(db, user)
    perms = _permissions(db, user, group_id)
    return user, int(group_id), ctx, visible_branch_ids, perms, None


def _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms):
    raw = {key: request.query_params.get(key) for key in _FILTER_KEYS}
    # Filter validation must use a tenant-bound branch set even for an
    # organization/global viewer (visible_branch_ids is None = "all branches
    # I may query", not "all branches exist" - a foreign tenant's Branch id
    # must still be rejected as invalid_filter, never silently accepted).
    if visible_branch_ids is not None:
        validation_branch_ids = visible_branch_ids
    else:
        validation_branch_ids = {
            row[0] for row in db.query(models.Branch.id).filter_by(school_group_id=ctx.school_group_id).all()
        }
    return svc.resolve_filters(
        ctx, raw, db=db, branch_scope=validation_branch_ids,
        has_candidate_permission=perms["candidate"], has_identification_permission=perms["identification"],
    )


def _fail_closed():
    return JSONResponse(
        {"detail": "Talent analytics is not available (configuration error).", "code": "analytics_query_failed"},
        status_code=500,
    )


def _kpi_configured(db, ctx, framework_version_id):
    return db.query(models.TalentKpiConfiguration.id).filter_by(
        school_group_id=ctx.school_group_id, framework_version_id=framework_version_id, is_enabled=True,
    ).first() is not None


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/context")
def analytics_context(program_id: int, academic_year_id: int, request: Request,
                       db: Session = Depends(get_db), current_user=Depends(get_current_user),
                       policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)

    pop_query = svc.population_query(db, ctx, svc.ResolvedFilters(), visible_branch_ids)
    branch_ids = sorted({row[0] for row in pop_query.with_entities(models.TalentAssessmentCyclePopulationMember.branch_id).distinct().all()})
    grades = sorted({row[0] for row in pop_query.with_entities(models.TalentAssessmentCyclePopulationMember.grade_level).distinct().all()})
    section_labels = svc.section_labels(db, pop_query)
    framework_ids = sorted({row.framework_version_id for row in ctx.cycles})
    competencies = []
    if framework_ids:
        competencies = [
            {"id": row.id, "framework_version_id": row.framework_version_id, "label": row.label, "display_order": row.display_order}
            for row in db.query(models.FrameworkCompetency).filter(
                models.FrameworkCompetency.school_group_id == ctx.school_group_id,
                models.FrameworkCompetency.framework_version_id.in_(framework_ids),
            ).order_by(models.FrameworkCompetency.framework_version_id, models.FrameworkCompetency.display_order).all()
        ]
    frameworks = [
        {"id": row.id, "version_number": row.version_number, "title": row.title, "status": row.status}
        for row in db.query(models.TalentProgramFrameworkVersion).filter(
            models.TalentProgramFrameworkVersion.school_group_id == ctx.school_group_id,
            models.TalentProgramFrameworkVersion.id.in_(framework_ids or [-1]),
        ).all()
    ]

    counts = svc.raw_coverage_counts(db, svc.population_query(db, ctx, filters, visible_branch_ids))
    frozen_eligible = sum(counts.values())
    drill_cell = Cell(key=("drill", "eligible"), privacy_class="P7", raw_value=(frozen_eligible if frozen_eligible else None))
    apply_primary_privacy([drill_cell], policy)
    drill_available = perms["students"] and drill_cell.state == VISIBLE and (drill_cell.value or 0) > 0

    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id,
        scope_signature=svc.scope_signature(visible_branch_ids), filters=filters,
        permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return {
        "program": {"id": ctx.program.id, "name": ctx.program.name},
        "academic_year": {"id": ctx.year.id, "year_name": getattr(ctx.year, "year_name", None)},
        "plan": None if ctx.plan is None else {"id": ctx.plan.id, "status": ctx.plan.status},
        "analytical_scope_class": "organization" if visible_branch_ids is None else "branch",
        "periods": [{"id": row.id, "sequence": row.sequence, "label": row.label, "status": row.status, "is_required": row.is_required} for row in sorted(ctx.periods, key=lambda row: row.sequence)],
        "cycles": ([{"id": row.id, "status": row.status, "framework_version_id": row.framework_version_id, "planned_evaluation_period_id": row.planned_evaluation_period_id} for row in ctx.cycles] if perms["cycle_view"] else None),
        "frameworks": frameworks,
        "filters": {
            "branch_ids": branch_ids, "grades": grades,
            "sections": [{"planning_section_id": key, "section_name": value} for key, value in section_labels.items()],
            "competencies": competencies,
            "assessment_states": list(svc.ASSESSMENT_STATES),
            "candidate_states": ["pending_review", "reviewed"] if perms["candidate"] else None,
            "identification_states": ["identified", "not_identified", "no_decision"] if perms["identification"] else None,
        },
        "capabilities": {
            "candidate_analytics": perms["candidate"], "identification_analytics": perms["identification"],
            "student_drill": drill_available,
        },
        "privacy_policy_version": policy.privacy_policy_version,
        "request_context_fingerprint": fingerprint,
    }


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/overview")
def analytics_overview(program_id: int, academic_year_id: int, request: Request,
                        db: Session = Depends(get_db), current_user=Depends(get_current_user),
                        policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)

    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    counts = svc.raw_coverage_counts(db, pop_query)
    frozen_eligible = sum(counts.values())
    coverage_group = svc.build_breakdown_group(
        name="overview_coverage", privacy_class="P2",
        total_raw=(frozen_eligible if frozen_eligible else None),
        children_raw={key: (value if frozen_eligible else None) for key, value in counts.items()},
    )
    coverage_group.total.context = {"metric": "frozen_eligible"}
    for cell in coverage_group.children:
        cell.context = {"metric": cell.key[2]}
    apply_primary_privacy(coverage_group.all_cells(), policy)
    coverage_converged = run_complementary_suppression([coverage_group], policy)
    coverage_cell = coverage_group.total
    coverage_by_status = {cell.key[2]: cell for cell in coverage_group.children}
    coverage_sources_visible = coverage_converged and all(
        cell.state == VISIBLE for cell in coverage_group.all_cells()
    )
    coverage_payload = None
    coverage_projection_state = coverage_cell.state
    if coverage_sources_visible:
        # Derive only after every directly disclosed source count has passed
        # primary and complementary privacy evaluation.
        coverage_payload = svc.coverage_metrics(
            {key: coverage_by_status[key].value for key in svc.COVERAGE_STATUS_KEYS}
        )
    elif coverage_cell.state == COARSENED:
        # A coarsened headline count is a policy-supplied safe replacement for
        # frozen_eligible alone - it never licenses publishing the full raw
        # per-status coverage_metrics breakdown, whose raw source counts have
        # independent privacy decisions and could still leak real values.
        coverage_payload = {"state": COARSENED, "value": coverage_cell.value}
    elif coverage_cell.state == NO_DATA:
        coverage_payload = None
    else:
        coverage_projection_state = RESTRICTED if (
            not coverage_converged or any(cell.state == RESTRICTED for cell in coverage_group.all_cells())
        ) else SUPPRESSED

    candidate_summary = None
    if perms["candidate"]:
        candidate_count = svc.raw_candidate_count(db, pop_query, has_permission=True)
        cand_cell = Cell(
            key=("overview", "candidate"), privacy_class="P5", raw_value=candidate_count,
            context={"metric": "candidate_count"},
        )
        apply_primary_privacy([cand_cell], policy)
        if cand_cell.state == VISIBLE:
            value = cand_cell.value
            candidate_summary = {
                "candidate_count": value,
                "candidate_of_eligible_percentage": derive_from_visible_cells(
                    [cand_cell, coverage_cell], svc.percentage,
                ),
                "candidate_of_completed_percentage": derive_from_visible_cells(
                    [cand_cell, coverage_by_status["completed"]], svc.percentage,
                ),
                "state": VISIBLE,
            }
        elif cand_cell.state == COARSENED:
            # Safe replacement only - no percentage derived against a raw,
            # independently-sourced denominator.
            candidate_summary = {"state": COARSENED, "candidate_count": cand_cell.value}
        else:
            candidate_summary = {"state": cand_cell.state}

    identification_summary = None
    if perms["identification"]:
        ident_counts = svc.raw_identification_counts(db, pop_query, has_permission=True)
        total_decisions = ident_counts["identified"] + ident_counts["not_identified"]
        ident_group = svc.build_breakdown_group(
            name="overview_identification", privacy_class="P6", total_raw=total_decisions,
            children_raw=ident_counts,
        )
        ident_group.total.context = {"metric": "identification_total"}
        for cell in ident_group.children:
            cell.context = {"metric": f"{cell.key[2]}_count"}
        apply_primary_privacy(ident_group.all_cells(), policy)
        ident_converged = run_complementary_suppression([ident_group], policy)
        ident_cell = ident_group.total
        ident_by_decision = {cell.key[2]: cell for cell in ident_group.children}
        if ident_converged and all(cell.state == VISIBLE for cell in ident_group.all_cells()):
            identified_cell = ident_by_decision["identified"]
            identification_summary = {
                "identified_count": identified_cell.value,
                "not_identified_count": ident_by_decision["not_identified"].value,
                "decision_state": "no_decisions" if ident_cell.value == 0 else "decisions_recorded",
                "identified_of_eligible_candidates_percentage": derive_from_visible_cells(
                    [identified_cell, cand_cell], svc.percentage,
                ) if perms["candidate"] else None,
                "state": VISIBLE,
            }
        elif ident_cell.state == COARSENED:
            identification_summary = {"state": COARSENED, "decisions_count": ident_cell.value}
        else:
            identification_summary = {
                "state": RESTRICTED if (
                    not ident_converged or any(cell.state == RESTRICTED for cell in ident_group.all_cells())
                ) else SUPPRESSED
            }

    execution_summary = svc.compute_execution_summary(ctx)
    timeline, ad_hoc = svc.build_period_timeline(ctx, cycle_view_permission=perms["cycle_view"])
    kpi_configured = filters.framework_version_id is not None and _kpi_configured(db, ctx, filters.framework_version_id)
    any_hidden = coverage_projection_state not in (VISIBLE, NO_DATA)
    insights = svc.build_insights(
        coverage_state=coverage_projection_state, coverage=coverage_payload, execution_summary=execution_summary,
        kpi_configured=kpi_configured, any_hidden=any_hidden,
    )
    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id,
        scope_signature=svc.scope_signature(visible_branch_ids), filters=filters,
        permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    result = {
        "execution_summary": execution_summary,
        "period_timeline": timeline,
        "ad_hoc_cycles": ad_hoc,
        "coverage": coverage_payload if coverage_payload is not None else {"state": coverage_projection_state},
        "insights": insights,
        "privacy_policy_version": policy.privacy_policy_version,
        "request_context_fingerprint": fingerprint,
    }
    if perms["candidate"]:
        result["candidate"] = candidate_summary
    if perms["identification"]:
        result["identification"] = identification_summary
    return jsonable_encoder(result)


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/rubric-distribution")
def analytics_rubric_distribution(program_id: int, academic_year_id: int, request: Request,
                                   db: Session = Depends(get_db), current_user=Depends(get_current_user),
                                   policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)

    scoped_ids = svc._scoped_cycle_ids(ctx, filters)
    frameworks_in_scope = sorted({row.framework_version_id for row in ctx.cycles if row.id in scoped_ids})
    if filters.framework_version_id is not None:
        frameworks_in_scope = [fv for fv in frameworks_in_scope if fv == filters.framework_version_id]

    distributions = []
    for framework_version_id in frameworks_in_scope:
        rubric = db.query(models.TalentRubric).filter_by(school_group_id=ctx.school_group_id, framework_version_id=framework_version_id).one_or_none()
        if rubric is None:
            continue
        levels = db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric.id).order_by(models.TalentRubricLevel.display_order).all()
        scoped_filters = replace(filters, framework_version_id=framework_version_id)
        pop_query = svc.population_query(db, ctx, scoped_filters, visible_branch_ids)
        raw_counts = svc.raw_rubric_level_counts(db, pop_query, framework_version_id)
        total_raw = sum(raw_counts.values())
        children_raw = {level.id: raw_counts.get(level.id, 0) for level in levels}
        group = svc.build_breakdown_group(name=f"rubric:{framework_version_id}", privacy_class="P3", total_raw=total_raw, children_raw=children_raw)
        apply_primary_privacy(group.all_cells(), policy)
        converged = run_complementary_suppression([group], policy)
        framework = db.query(models.TalentProgramFrameworkVersion).filter_by(id=framework_version_id, school_group_id=ctx.school_group_id).one_or_none()
        if not converged:
            distributions.append({
                "framework_version_id": framework_version_id, "framework_title": framework.title if framework else None,
                "rubric_id": rubric.id, "state": RESTRICTED,
            })
            continue
        # Every per-status coverage count (and the frozen_eligible headline)
        # must be independently privacy-evaluated with complementary sibling/
        # total protection - a visible rubric-level total never licenses
        # publishing the raw coverage_metrics() breakdown directly (Section
        # C/E of the M9 coverage-privacy remediation).
        coverage_counts = svc.raw_coverage_counts(db, pop_query)
        coverage_payload, coverage_projection_state, _ = svc.build_privacy_safe_coverage_bundle(
            name=f"rubric_coverage:{framework_version_id}", counts=coverage_counts, privacy_class="P2", policy=policy,
        )
        coverage = coverage_payload if coverage_payload is not None else {"state": coverage_projection_state}
        level_by_id = {level.id: level for level in levels}
        levels_payload = []
        for cell in group.children:
            level = level_by_id[cell.key[2]]
            levels_payload.append({
                "rubric_level_id": level.id, "code": level.code, "label": level.label, "display_order": level.display_order,
                "state": cell.state,
                "count": cell.value,
                "percentage": svc.percentage(cell.value, total_raw) if cell.state == VISIBLE and group.total.state == VISIBLE else None,
            })
        distributions.append({
            "framework_version_id": framework_version_id, "framework_title": framework.title if framework else None,
            "rubric_id": rubric.id, "rubric_name": rubric.name,
            "valid_result_count": {"state": group.total.state, "value": group.total.value},
            "levels": levels_payload,
            "coverage": coverage,
        })
    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id, scope_signature=svc.scope_signature(visible_branch_ids),
        filters=filters, permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return jsonable_encoder({"distributions": distributions, "privacy_policy_version": policy.privacy_policy_version, "request_context_fingerprint": fingerprint})


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/kpi-distribution")
def analytics_kpi_distribution(program_id: int, academic_year_id: int, request: Request,
                                db: Session = Depends(get_db), current_user=Depends(get_current_user),
                                policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)
    if filters.framework_version_id is None:
        return JSONResponse({"detail": "framework_version_id is required for KPI distribution.", "code": "invalid_filter"}, status_code=400)

    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    configured = _kpi_configured(db, ctx, filters.framework_version_id)
    raw_count = svc.raw_kpi_valid_result_count(db, pop_query, filters.framework_version_id) if configured else 0
    cell = Cell(key=("kpi", filters.framework_version_id), privacy_class="P3", raw_value=(raw_count if configured else None))
    apply_primary_privacy([cell], policy)
    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id, scope_signature=svc.scope_signature(visible_branch_ids),
        filters=filters, permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return jsonable_encoder({
        "framework_version_id": filters.framework_version_id,
        "kpi_configured": configured,
        "valid_result_count": {"state": cell.state, "value": cell.value},
        "distribution_mode": "unavailable",
        "reason_code": "numeric_binning_rule_unapproved",
        "privacy_policy_version": policy.privacy_policy_version,
        "request_context_fingerprint": fingerprint,
    })


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/competencies")
def analytics_competencies(program_id: int, academic_year_id: int, request: Request,
                            db: Session = Depends(get_db), current_user=Depends(get_current_user),
                            policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)
    if filters.framework_version_id is None:
        return JSONResponse({"detail": "framework_version_id is required for competency distribution.", "code": "invalid_filter"}, status_code=400)

    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    competency_query = db.query(models.FrameworkCompetency).filter_by(
        school_group_id=ctx.school_group_id, framework_version_id=filters.framework_version_id,
    )
    if filters.competency_id is not None:
        competency_query = competency_query.filter_by(id=filters.competency_id)
    competencies = competency_query.order_by(models.FrameworkCompetency.display_order).all()
    levels = db.query(models.TalentRubricLevel).filter_by(school_group_id=ctx.school_group_id, framework_version_id=filters.framework_version_id).order_by(models.TalentRubricLevel.display_order).all()
    matrix = svc.raw_competency_matrix(db, pop_query, filters.framework_version_id)

    groups = []
    for competency in competencies:
        raw_counts = matrix.get(competency.id, {})
        total_raw = sum(raw_counts.values())
        children_raw = {level.id: raw_counts.get(level.id, 0) for level in levels}
        groups.append((competency, svc.build_breakdown_group(name=f"competency:{competency.id}", privacy_class="P4", total_raw=total_raw, children_raw=children_raw)))
    for _, group in groups:
        apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression([group for _, group in groups], policy)

    level_by_id = {level.id: level for level in levels}
    payload = []
    for competency, group in groups:
        if not converged:
            payload.append({"framework_competency_id": competency.id, "label": competency.label, "display_order": competency.display_order, "state": RESTRICTED})
            continue
        levels_payload = []
        for cell in group.children:
            level = level_by_id[cell.key[2]]
            levels_payload.append({
                "rubric_level_id": level.id, "code": level.code, "label": level.label, "display_order": level.display_order,
                "state": cell.state, "count": cell.value,
                "percentage": svc.percentage(cell.value, group.total.value) if cell.state == VISIBLE and group.total.state == VISIBLE else None,
            })
        payload.append({
            "framework_competency_id": competency.id, "label": competency.label, "display_order": competency.display_order,
            "valid_result_count": {"state": group.total.state, "value": group.total.value},
            "levels": levels_payload,
        })
    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id, scope_signature=svc.scope_signature(visible_branch_ids),
        filters=filters, permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return jsonable_encoder({"framework_version_id": filters.framework_version_id, "competencies": payload,
                              "privacy_policy_version": policy.privacy_policy_version, "request_context_fingerprint": fingerprint})


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/breakdowns/{dimension_type}")
def analytics_breakdown(program_id: int, academic_year_id: int, dimension_type: str, request: Request,
                         db: Session = Depends(get_db), current_user=Depends(get_current_user),
                         policy=Depends(resolve_privacy_policy_provider)):
    if dimension_type not in svc.DIMENSION_TYPES:
        return JSONResponse({"detail": "dimension_type must be one of branch, grade, section.", "code": "invalid_filter"}, status_code=400)
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)

    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    coverage_counts = svc.raw_coverage_counts(db, pop_query)
    frozen_eligible = sum(coverage_counts.values())
    coverage_by_dim = svc.raw_coverage_by_dimension(db, pop_query, dimension_type)

    groups = {}
    groups["frozen_eligible"] = svc.build_breakdown_group(
        name="frozen_eligible", privacy_class="P2", total_raw=frozen_eligible,
        children_raw={key: sum(value.values()) for key, value in coverage_by_dim.items()},
    )
    groups["completed"] = svc.build_breakdown_group(
        name="completed", privacy_class="P2", total_raw=coverage_counts["completed"],
        children_raw={key: value["completed"] for key, value in coverage_by_dim.items()},
    )
    if perms["candidate"]:
        candidate_total = svc.raw_candidate_count(db, pop_query, has_permission=True)
        candidate_by_dim = svc.raw_candidate_by_dimension(db, pop_query, dimension_type, has_permission=True) or {}
        groups["candidate"] = svc.build_breakdown_group(
            name="candidate", privacy_class="P5", total_raw=candidate_total,
            children_raw={key: candidate_by_dim.get(key, 0) for key in coverage_by_dim},
        )
    if perms["identification"]:
        ident_by_dim = svc.raw_identification_by_dimension(db, pop_query, dimension_type, has_permission=True) or {}
        ident_totals = svc.raw_identification_counts(db, pop_query, has_permission=True)
        groups["identified"] = svc.build_breakdown_group(
            name="identified", privacy_class="P6", total_raw=ident_totals["identified"],
            children_raw={key: ident_by_dim.get(key, {}).get("identified", 0) for key in coverage_by_dim},
        )

    for group in groups.values():
        apply_primary_privacy(group.all_cells(), policy)
    converged = run_complementary_suppression(list(groups.values()), policy)
    if not converged:
        return jsonable_encoder({"dimension_type": dimension_type, "state": RESTRICTED, "reason_code": "suppression_fixed_point_unreachable"})

    section_label_by_id = svc.section_labels(db, pop_query) if dimension_type == "section" else {}
    rows = []
    dim_keys = sorted(coverage_by_dim.keys(), key=lambda value: (value is None, value))
    for dim_key in dim_keys:
        row = {"dimension_value": dim_key}
        if dimension_type == "section":
            row["section_name"] = section_label_by_id.get(dim_key)
        for metric_name, group in groups.items():
            cell = next(child for child in group.children if child.key[2] == dim_key)
            row[metric_name] = {"state": cell.state, "value": cell.value}
        rows.append(row)

    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id, scope_signature=svc.scope_signature(visible_branch_ids),
        filters=filters, permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return jsonable_encoder({
        "dimension_type": dimension_type, "rows": rows,
        "totals": {metric_name: {"state": group.total.state, "value": group.total.value} for metric_name, group in groups.items()},
        "privacy_policy_version": policy.privacy_policy_version, "request_context_fingerprint": fingerprint,
    })


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/period-comparison")
def analytics_period_comparison(program_id: int, academic_year_id: int, request: Request,
                                 left_period_id: int | None = Query(None), right_period_id: int | None = Query(None),
                                 left_cycle_id: int | None = Query(None), right_cycle_id: int | None = Query(None),
                                 db: Session = Depends(get_db), current_user=Depends(get_current_user),
                                 policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()

    def _resolve_side(period_id, cycle_id):
        if period_id is not None:
            if period_id not in ctx.periods_by_id:
                raise svc.TalentAnalyticsError("invalid_filter", "period_id is not within the analytical context.")
            cycle = ctx.cycle_by_period_id.get(period_id)
            if cycle is None:
                return period_id, None, "missing_cycle"
            return period_id, cycle, None
        if cycle_id is not None:
            cycle = ctx.cycles_by_id.get(cycle_id)
            if cycle is None:
                raise svc.TalentAnalyticsError("invalid_filter", "cycle_id is not within the analytical context.")
            return None, cycle, None
        raise svc.TalentAnalyticsError("invalid_filter", "A period_id or cycle_id is required for each comparison side.")

    try:
        left_period, left_cycle, left_reason = _resolve_side(left_period_id, left_cycle_id)
        right_period, right_cycle, right_reason = _resolve_side(right_period_id, right_cycle_id)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)

    def _side_payload(cycle, reason):
        if cycle is None:
            return {"cycle_id": None, "coverage": {"state": NO_DATA}, "reason_code": reason}, NO_DATA, None
        side_filters = svc.ResolvedFilters(cycle_id=cycle.id)
        pop_query = svc.population_query(db, ctx, side_filters, visible_branch_ids)
        counts = svc.raw_coverage_counts(db, pop_query)
        frozen_eligible = sum(counts.values())
        # Every per-status coverage count (and the frozen_eligible headline)
        # must be independently privacy-evaluated with complementary sibling/
        # total protection per side - a visible frozen_eligible total never
        # licenses publishing the raw coverage_metrics() breakdown directly
        # (Section C/F of the M9 coverage-privacy remediation).
        coverage_payload, coverage_projection_state, _ = svc.build_privacy_safe_coverage_bundle(
            name=f"period_comparison_coverage:{cycle.id}", counts=counts, privacy_class="P2", policy=policy,
        )
        coverage = coverage_payload if coverage_payload is not None else {"state": coverage_projection_state}
        payload = {
            "cycle_id": cycle.id, "framework_version_id": cycle.framework_version_id,
            "coverage": coverage, "reason_code": None if frozen_eligible else "no_frozen_population",
        }
        # Safe-to-use privacy-filtered counts, exposed only to this route's
        # own internal comparability logic (never re-serialized), and only
        # when every source cell in the bundle - including "completed" -
        # independently passed privacy.
        safe_counts = counts if coverage_projection_state == VISIBLE else None
        return payload, coverage_projection_state, safe_counts

    left_payload, left_coverage_state, left_safe_counts = _side_payload(left_cycle, left_reason)
    right_payload, right_coverage_state, right_safe_counts = _side_payload(right_cycle, right_reason)

    def _outcome_state():
        if left_cycle is None or right_cycle is None:
            return "not_comparable", "missing_cycle"
        if left_cycle.framework_version_id != right_cycle.framework_version_id:
            return "not_comparable", "framework_changed"
        left_completed = (left_safe_counts or {}).get("completed", 0)
        right_completed = (right_safe_counts or {}).get("completed", 0)
        if not left_completed or not right_completed:
            return "not_comparable", "no_completed_result"
        return "comparable", None

    rubric_state, rubric_reason = _outcome_state()
    kpi_state, kpi_reason = rubric_state, rubric_reason
    if kpi_state == "comparable" and left_cycle is not None and not _kpi_configured(db, ctx, left_cycle.framework_version_id):
        kpi_state, kpi_reason = "not_comparable", "metric_unavailable"
    candidate_state, candidate_reason = rubric_state, rubric_reason
    if candidate_state == "comparable" and perms["candidate"]:
        left_policy = db.query(models.TalentReviewCandidatePolicy.id).filter_by(framework_version_id=left_cycle.framework_version_id, school_group_id=ctx.school_group_id, is_enabled=True).first()
        right_policy = db.query(models.TalentReviewCandidatePolicy.id).filter_by(framework_version_id=right_cycle.framework_version_id, school_group_id=ctx.school_group_id, is_enabled=True).first()
        if bool(left_policy) != bool(right_policy):
            candidate_state, candidate_reason = "not_comparable", "candidate_policy_changed"

    comparisons = {
        "coverage": {"state": "comparable" if (left_payload["reason_code"] is None and right_payload["reason_code"] is None) else "not_comparable", "reason_code": left_payload["reason_code"] or right_payload["reason_code"]},
        "rubric": {"state": rubric_state, "reason_code": rubric_reason},
        "kpi": {"state": kpi_state, "reason_code": kpi_reason},
    }
    if perms["candidate"]:
        comparisons["candidate"] = {"state": candidate_state, "reason_code": candidate_reason}

    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id, scope_signature=svc.scope_signature(visible_branch_ids),
        filters=svc.ResolvedFilters(period_id=left_period, cycle_id=left_cycle.id if left_cycle else None),
        permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return jsonable_encoder({
        "analysis_mode": "full_period_populations",
        "left": {**left_payload, "period_id": left_period}, "right": {**right_payload, "period_id": right_period},
        "comparisons": comparisons,
        "privacy_policy_version": policy.privacy_policy_version, "request_context_fingerprint": fingerprint,
    })


@router.get("/programs/{program_id}/academic-years/{academic_year_id}/students")
def analytics_students(program_id: int, academic_year_id: int, request: Request,
                        limit: int = Query(25, ge=1), offset: int = Query(0, ge=0),
                        db: Session = Depends(get_db), current_user=Depends(get_current_user),
                        policy=Depends(resolve_privacy_policy_provider)):
    user, group_id, ctx, visible_branch_ids, perms, denied = _authorize(request, db, current_user, program_id, academic_year_id, require_students=True)
    if denied:
        return denied
    if policy is None:
        return _fail_closed()
    if limit > 100 or offset < 0:
        return JSONResponse({"detail": "limit must be at most 100 and offset must be non-negative.", "code": "invalid_pagination"}, status_code=400)
    try:
        filters = _resolve_filters_from_query(request, db, ctx, visible_branch_ids, perms)
    except svc.TalentAnalyticsError as exc:
        return _error(exc)

    pop_query = svc.population_query(db, ctx, filters, visible_branch_ids)
    counts = svc.raw_coverage_counts(db, pop_query)
    frozen_eligible = sum(counts.values())
    drill_cell = Cell(key=("drill", "eligible"), privacy_class="P7", raw_value=(frozen_eligible if frozen_eligible else None))
    apply_primary_privacy([drill_cell], policy)
    if drill_cell.state != VISIBLE:
        return JSONResponse({"detail": "This Student cohort is not available for drill.", "code": "analytics_drill_restricted"}, status_code=403)

    items, has_more = _list_student_rows(
        db, pop_query, filters, limit=limit, offset=offset,
        has_candidate=perms["candidate"], has_identification=perms["identification"], has_learner_profile=perms["learner_profile"],
    )
    fingerprint = svc.compute_request_context_fingerprint(
        program_id=program_id, academic_year_id=academic_year_id, scope_signature=svc.scope_signature(visible_branch_ids),
        filters=filters, permission_projection=_projection_list(perms), privacy_policy_version=policy.privacy_policy_version,
    )
    return jsonable_encoder({
        "items": items, "pagination": {"limit": limit, "offset": offset, "has_more": has_more},
        "privacy_policy_version": policy.privacy_policy_version, "request_context_fingerprint": fingerprint,
    })


def _display_name(student):
    parts = [student.first_name, student.father_name, student.last_name]
    return " ".join(part for part in parts if part)


def _list_student_rows(db, pop_query, filters, *, limit, offset, has_candidate, has_identification, has_learner_profile):
    query = db.query(models.TalentAssessmentCyclePopulationMember, models.TalentStudentAssessment, models.Student).select_from(
        models.TalentAssessmentCyclePopulationMember
    ).outerjoin(
        models.TalentStudentAssessment,
        models.TalentStudentAssessment.cycle_population_member_id == models.TalentAssessmentCyclePopulationMember.id,
    ).join(
        models.Student, models.Student.id == models.TalentAssessmentCyclePopulationMember.student_id,
    ).filter(
        models.TalentAssessmentCyclePopulationMember.id.in_(pop_query.with_entities(models.TalentAssessmentCyclePopulationMember.id))
    )
    if filters.assessment_state is not None:
        if filters.assessment_state == "unassessed":
            query = query.filter(models.TalentStudentAssessment.id.is_(None))
        else:
            query = query.filter(models.TalentStudentAssessment.status == filters.assessment_state)
    query = query.order_by(models.TalentAssessmentCyclePopulationMember.student_id).offset(offset).limit(limit + 1)
    rows = query.all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    assessment_ids = [assessment.id for _, assessment, _ in rows if assessment is not None]
    candidates_by_assessment = {}
    if has_candidate and assessment_ids:
        candidates_by_assessment = {
            row.assessment_id: row for row in db.query(models.TalentReviewCandidate).filter(models.TalentReviewCandidate.assessment_id.in_(assessment_ids)).all()
        }
    identifications_by_candidate = {}
    if has_identification and candidates_by_assessment:
        candidate_ids = [row.id for row in candidates_by_assessment.values()]
        identifications_by_candidate = {
            row.review_candidate_id: row for row in db.query(models.TalentOfficialIdentification).filter(models.TalentOfficialIdentification.review_candidate_id.in_(candidate_ids)).all()
        }

    items = []
    for member, assessment, student in rows:
        item = {
            "student_id": student.id, "display_name": _display_name(student),
            "branch_id": member.branch_id, "grade_level": member.grade_level, "section_name": member.section_name,
            "assessment_state": assessment.status if assessment else "unassessed",
        }
        if assessment is not None and assessment.status == "completed" and assessment.kpi_result is not None:
            item["kpi_result"] = assessment.kpi_result
        candidate = candidates_by_assessment.get(assessment.id) if assessment else None
        if has_candidate:
            item["candidate_state"] = candidate.status if candidate else None
        if has_identification:
            identification = identifications_by_candidate.get(candidate.id) if candidate else None
            item["identification_state"] = identification.decision if identification else None
        if has_learner_profile:
            item["learner_profile_available"] = True
        items.append(item)
    return items, has_more
