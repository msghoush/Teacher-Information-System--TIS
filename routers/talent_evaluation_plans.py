from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
from auth import get_current_user
from dependencies import get_db
from talent_evaluation_plan_service import (
    TalentEvaluationPlanError, activate_plan, add_period, cancel_period,
    close_plan, closure_preflight, create_plan, delete_period, eligible_periods,
    list_plans, period_payload, plan_payload, reorder_periods, rollover_plan,
    rollover_preview, update_period, validate_cycle_period_link, _require_plan,
)

router = APIRouter(prefix="/api/talent", tags=["Talent Annual Evaluation Plans"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _organization(user):
    return auth.get_access_scope(user) in {auth.ACCESS_SCOPE_ORGANIZATION, auth.ACCESS_SCOPE_GLOBAL}


def _authorize(request, db, user, *keys, all_required=False):
    checker = authorization.require_all_permissions if all_required else authorization.require_any_permission
    user, denied = checker(request, db, *keys, current_user=user, page_key="talent_evaluation_plans")
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope.", "code": "organization_scope_required"}, status_code=403)
    return user, int(group_id), None


def _require_org(user):
    if not _organization(user):
        raise TalentEvaluationPlanError("organization_authority_required", "Organization or global scope is required.")


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {"organization_authority_required"}:
        status = 403
    elif exc.code in {
        "stale_plan", "stale_cycle", "plan_conflict", "period_link_conflict",
        "period_identity_conflict",
        "period_linked", "period_immutable", "historical_anchor_immutable",
        "invalid_lifecycle", "plan_closed", "cycle_immutable",
        "closed_plan_link_immutable", "required_periods_outstanding",
        "linked_period_context_invalid",
    }:
        status = 409
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _run(db, work, *, created=False):
    try:
        result = work()
        db.commit()
        return JSONResponse(jsonable_encoder(result), status_code=201 if created else 200)
    except TalentEvaluationPlanError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent or duplicate evaluation planning change.", "code": "plan_conflict"}, status_code=409)
    except (TypeError, ValueError, KeyError):
        db.rollback()
        return JSONResponse({"detail": "Invalid evaluation planning payload.", "code": "invalid_input"}, status_code=400)


def _capabilities(db, user, plan, period=None, cycle=None, *, cycle_disclosed=False):
    if not _organization(user):
        return []
    manage = auth.has_permission(db, user, "talent_evaluation_plans.manage")
    govern = auth.has_permission(db, user, "talent_evaluation_plans.govern")
    cycle_manage = auth.has_permission(db, user, "talent_assessment_cycles.manage")
    if period is None:
        actions = []
        if manage and plan.status in {"draft", "active"}:
            actions.extend(["add_period", "reorder_periods"])
        if govern and plan.status == "draft":
            actions.append("activate")
        if govern and plan.status == "active":
            actions.append("close")
        if manage and plan.status in {"active", "closed"}:
            actions.append("rollover")
        return actions
    if not cycle_disclosed:
        return []
    actions = []
    if manage and plan.status != "closed" and period.status == "planned" and cycle is None:
        actions.extend(["edit", "reorder"])
        if plan.status == "draft":
            actions.append("remove")
    if govern and plan.status == "active" and period.status == "planned" and cycle is None:
        actions.append("cancel")
    if manage and cycle_manage and period.status == "planned":
        if cycle is None and plan.status == "active":
            actions.append("link_cycle")
        elif cycle is not None and cycle.status == "draft" and (plan.status == "active" or (plan.status == "closed" and not period.is_required)):
            actions.append("unlink_cycle")
    return actions


def _serialize(db, user, plan):
    cycle_view = auth.has_permission(db, user, "talent_assessment_cycles.view")
    return {
        **plan_payload(
            db, plan, include_cycles=cycle_view,
            action_resolver=lambda p, period, cycle: _capabilities(db, user, p, period, cycle, cycle_disclosed=cycle_view),
        ),
        "actions": _capabilities(db, user, plan),
    }


@router.get("/evaluation-plans")
def plans_list(request: Request, program_id: int | None = Query(None), academic_year_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.view")
    if denied:
        return denied
    return [_serialize(db, user, row) for row in list_plans(db, school_group_id=group_id, program_id=program_id, academic_year_id=academic_year_id)]


@router.post("/evaluation-plans")
def plans_create(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.manage")
    if denied:
        return denied
    return _run(db, lambda: (_require_org(user), _serialize(db, user, create_plan(db, school_group_id=group_id, configuration_id=int(payload["program_academic_year_configuration_id"]), actor=user)))[1], created=True)


@router.get("/evaluation-plans/{plan_id}")
def plans_read(plan_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.view")
    if denied:
        return denied
    try:
        return _serialize(db, user, _require_plan(db, group_id, plan_id))
    except TalentEvaluationPlanError as exc:
        return _error(exc)


@router.post("/evaluation-plans/{plan_id}/periods")
def periods_add(plan_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.manage")
    if denied:
        return denied
    def work():
        _require_org(user)
        plan, period = add_period(db, school_group_id=group_id, plan_id=plan_id, expected_plan_revision=payload["expected_plan_revision"], label=payload.get("label"), short_code=payload.get("short_code"), planned_start_date=payload.get("planned_start_date"), planned_end_date=payload.get("planned_end_date"), is_required=payload.get("is_required", True), notes=payload.get("notes"), actor=user)
        return {"plan_revision": plan.revision, "period": period_payload(period)}
    return _run(db, work, created=True)


@router.patch("/evaluation-periods/{period_id}")
def periods_update(period_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.manage")
    if denied:
        return denied
    allowed = {key: payload[key] for key in ("label", "short_code", "planned_start_date", "planned_end_date", "is_required", "notes") if key in payload}
    def work():
        _require_org(user)
        if not allowed:
            raise TalentEvaluationPlanError("invalid_input", "At least one mutable Period field is required.")
        plan, period = update_period(db, school_group_id=group_id, period_id=period_id, expected_plan_revision=payload["expected_plan_revision"], actor=user, **allowed)
        return {"plan_revision": plan.revision, "period": period_payload(period)}
    return _run(db, work)


@router.delete("/evaluation-periods/{period_id}")
def periods_delete(period_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.manage")
    if denied:
        return denied
    return _run(db, lambda: (_require_org(user), {"plan_revision": delete_period(db, school_group_id=group_id, period_id=period_id, expected_plan_revision=payload["expected_plan_revision"], actor=user).revision})[1])


@router.post("/evaluation-plans/{plan_id}/periods/reorder")
def periods_reorder(plan_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.manage")
    if denied:
        return denied
    return _run(db, lambda: (_require_org(user), {"plan_revision": reorder_periods(db, school_group_id=group_id, plan_id=plan_id, expected_plan_revision=payload["expected_plan_revision"], period_ids=payload.get("period_ids", []), actor=user).revision})[1])


@router.post("/evaluation-plans/{plan_id}/activate")
def plans_activate(plan_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.govern")
    if denied:
        return denied
    return _run(db, lambda: (_require_org(user), _serialize(db, user, activate_plan(db, school_group_id=group_id, plan_id=plan_id, expected_plan_revision=payload["expected_plan_revision"], actor=user)))[1])


@router.post("/evaluation-periods/{period_id}/cancel")
def periods_cancel(period_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.govern")
    if denied:
        return denied
    def work():
        _require_org(user)
        plan, period = cancel_period(db, school_group_id=group_id, period_id=period_id, expected_plan_revision=payload["expected_plan_revision"], cancellation_reason=payload.get("cancellation_reason"), actor=user)
        return {"plan_revision": plan.revision, "period": period_payload(period)}
    return _run(db, work)


@router.get("/evaluation-plans/{plan_id}/closure-preflight")
def plans_preflight(plan_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.view")
    if denied:
        return denied
    try:
        cycle_view = auth.has_permission(db, user, "talent_assessment_cycles.view")
        result = closure_preflight(db, school_group_id=group_id, plan_id=plan_id, include_cycle_details=cycle_view)
        if not cycle_view:
            # can_close / outstanding_required_period_ids are derived from linked
            # Cycle execution state (Draft/Open/Closed); without Cycle view they
            # would leak that state through an aggregate placeholder that differs
            # based on Cycle existence/status, even though no cycle object is
            # ever attached. Omit them entirely rather than only stripping the
            # per-item cycle detail, matching the same zero-leakage boundary
            # already enforced for Plan/Period cycle projection.
            result = {
                "plan_id": result["plan_id"],
                "periods": [
                    {"period_id": item["period_id"], "sequence": item["sequence"], "is_required": item["is_required"]}
                    for item in result["periods"]
                ],
            }
        return result
    except TalentEvaluationPlanError as exc:
        return _error(exc)


@router.post("/evaluation-plans/{plan_id}/close")
def plans_close(plan_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.govern")
    if denied:
        return denied
    return _run(db, lambda: (_require_org(user), _serialize(db, user, close_plan(db, school_group_id=group_id, plan_id=plan_id, expected_plan_revision=payload["expected_plan_revision"], actor=user)))[1])


@router.get("/evaluation-plans/{plan_id}/rollover-preview")
def plans_rollover_preview(plan_id: int, destination_configuration_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.view", "talent_evaluation_plans.manage", all_required=True)
    if denied:
        return denied
    try:
        _require_org(user)
        source, config, periods = rollover_preview(db, school_group_id=group_id, source_plan_id=plan_id, destination_configuration_id=destination_configuration_id)
        return {"source_plan_id": source.id, "destination_configuration_id": config.id, "periods": periods}
    except TalentEvaluationPlanError as exc:
        return _error(exc)


@router.post("/evaluation-plans/{plan_id}/rollover")
def plans_rollover(plan_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.view", "talent_evaluation_plans.manage", all_required=True)
    if denied:
        return denied
    return _run(db, lambda: (_require_org(user), _serialize(db, user, rollover_plan(db, school_group_id=group_id, source_plan_id=plan_id, destination_configuration_id=int(payload["destination_configuration_id"]), expected_plan_revision=payload["expected_plan_revision"], actor=user)))[1], created=True)


@router.get("/assessment-cycles/{cycle_id}/eligible-periods")
def cycles_eligible_periods(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.view", "talent_assessment_cycles.view", all_required=True)
    if denied:
        return denied
    try:
        return [period_payload(row) for row in eligible_periods(db, school_group_id=group_id, cycle_id=cycle_id)]
    except TalentEvaluationPlanError as exc:
        return _error(exc)


def _relationship_change(cycle_id, request, payload, db, current_user, *, unlink):
    user, group_id, denied = _authorize(request, db, current_user, "talent_evaluation_plans.manage", "talent_assessment_cycles.manage", all_required=True)
    if denied:
        return denied
    def work():
        _require_org(user)
        plan, period, cycle = validate_cycle_period_link(db, school_group_id=group_id, cycle_id=cycle_id, period_id=int(payload["planned_period_id"]), expected_plan_revision=payload["expected_plan_revision"], expected_cycle_revision=payload["expected_cycle_revision"], unlink=unlink, actor=user)
        return {"plan_id": plan.id, "plan_revision": plan.revision, "cycle_id": cycle.id, "cycle_revision": cycle.revision, "planned_period_id": cycle.planned_evaluation_period_id}
    return _run(db, work)


@router.post("/assessment-cycles/{cycle_id}/link-period")
def cycles_link_period(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return _relationship_change(cycle_id, request, payload, db, current_user, unlink=False)


@router.post("/assessment-cycles/{cycle_id}/unlink-period")
def cycles_unlink_period(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    return _relationship_change(cycle_id, request, payload, db, current_user, unlink=True)
