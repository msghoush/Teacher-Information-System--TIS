"""M8 annual Talent evaluation planning and period/cycle linkage authority."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

import models


class TalentEvaluationPlanError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _clean(value, field, *, required=False, maximum=160):
    cleaned = " ".join(str(value or "").split())
    if required and not cleaned:
        raise TalentEvaluationPlanError("invalid_input", f"{field} is required.")
    if len(cleaned) > maximum:
        raise TalentEvaluationPlanError("invalid_input", f"{field} is too long.")
    return cleaned or None


def normalize_period_identity(value):
    cleaned = _clean(value, "period identity", required=True)
    return unicodedata.normalize("NFKC", cleaned).casefold()


def _date(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise TalentEvaluationPlanError("invalid_date", f"{field} must be an ISO date.") from exc


def _actor_id(actor):
    return getattr(actor, "user_id", None)


def _actor_branch(actor):
    return getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None)


def _plan(db, school_group_id, plan_id, *, lock=False):
    query = db.query(models.TalentAnnualEvaluationPlan).filter_by(id=plan_id, school_group_id=school_group_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _period(db, school_group_id, period_id, *, lock=False):
    query = db.query(models.TalentPlannedEvaluationPeriod).filter_by(id=period_id, school_group_id=school_group_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _cycle_for_period(db, period_id, *, lock=False):
    query = db.query(models.TalentAssessmentCycle).filter_by(planned_evaluation_period_id=period_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _require_plan(db, school_group_id, plan_id, *, lock=False):
    row = _plan(db, school_group_id, plan_id, lock=lock)
    if row is None:
        raise TalentEvaluationPlanError("not_found", "Annual Evaluation Plan was not found.")
    return row


def _require_period(db, school_group_id, period_id, *, lock=False):
    row = _period(db, school_group_id, period_id, lock=lock)
    if row is None:
        raise TalentEvaluationPlanError("not_found", "Planned Evaluation Period was not found.")
    return row


def _check_revision(plan, expected):
    if plan.revision != int(expected):
        raise TalentEvaluationPlanError("stale_plan", "Annual Evaluation Plan changed since it was read.")


def _periods(db, plan_id, *, lock=False):
    query = db.query(models.TalentPlannedEvaluationPeriod).filter_by(annual_evaluation_plan_id=plan_id).order_by(
        models.TalentPlannedEvaluationPeriod.sequence,
        models.TalentPlannedEvaluationPeriod.id,
    )
    return (query.with_for_update() if lock else query).all()


def _audit(db, plan, *, actor, resource_type, resource_id, action, before=None, after=None):
    canonical = _json({"resource_type": resource_type, "resource_id": resource_id, "action": action, "before": before, "after": after})
    db.add(models.TalentConfigurationAudit(
        school_group_id=plan.school_group_id,
        program_id=plan.program_id,
        actor_user_id=_actor_id(actor),
        actor_branch_id=_actor_branch(actor),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        before_json=_json(before) if before is not None else None,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def _bump(plan):
    plan.revision += 1
    plan.updated_at = datetime.utcnow()


def plan_warnings(db, plan, *, include_cycle_context=True):
    rows = _periods(db, plan.id)
    warnings = []
    dated = [row for row in rows if row.status == "planned" and row.planned_start_date and row.planned_end_date]
    for index, left in enumerate(dated):
        for right in dated[index + 1:]:
            if left.planned_start_date <= right.planned_end_date and right.planned_start_date <= left.planned_end_date:
                warnings.append({"code": "period_window_overlap", "period_ids": sorted([left.id, right.id])})
    ordered = [row for row in rows if row.planned_start_date]
    for left, right in zip(ordered, ordered[1:]):
        if left.planned_start_date > right.planned_start_date:
            warnings.append({"code": "chronological_inconsistency", "period_ids": [left.id, right.id]})
    for row in rows if include_cycle_context else []:
        cycle = _cycle_for_period(db, row.id)
        if cycle and row.planned_start_date and cycle.population_effective_at:
            point = cycle.population_effective_at.date()
            if point < row.planned_start_date or (row.planned_end_date and point > row.planned_end_date):
                warnings.append({"code": "cycle_outside_planned_window", "period_ids": [row.id]})
    return warnings


def period_payload(row, *, cycle=None, actions=None):
    result = {
        "id": row.id,
        "annual_evaluation_plan_id": row.annual_evaluation_plan_id,
        "sequence": row.sequence,
        "label": row.label,
        "short_code": row.short_code,
        "planned_start_date": row.planned_start_date.isoformat() if row.planned_start_date else None,
        "planned_end_date": row.planned_end_date.isoformat() if row.planned_end_date else None,
        "is_required": row.is_required,
        "status": row.status,
        "notes": row.notes,
        "cancellation_reason": row.cancellation_reason,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "actions": actions or [],
    }
    if cycle is not None:
        result["cycle"] = {
            "id": cycle.id,
            "title": cycle.title,
            "status": cycle.status,
            "revision": cycle.revision,
            "framework_version_id": cycle.framework_version_id,
        }
    return result


def plan_payload(db, row, *, include_cycles=False, action_resolver=None):
    periods = []
    for period in _periods(db, row.id):
        cycle = _cycle_for_period(db, period.id) if include_cycles else None
        actions = action_resolver(row, period, cycle) if action_resolver else []
        periods.append(period_payload(period, cycle=cycle, actions=actions))
    return {
        "id": row.id,
        "school_group_id": row.school_group_id,
        "program_id": row.program_id,
        "academic_year_id": row.academic_year_id,
        "program_academic_year_configuration_id": row.program_academic_year_configuration_id,
        "source_plan_id": row.source_plan_id,
        "status": row.status,
        "revision": row.revision,
        "period_count": len(periods),
        "required_period_count": sum(1 for p in periods if p["is_required"]),
        "periods": periods,
        "warnings": plan_warnings(db, row, include_cycle_context=include_cycles),
    }


def create_plan(db: Session, *, school_group_id, configuration_id, actor=None):
    config = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        id=configuration_id, school_group_id=school_group_id
    ).one_or_none()
    if config is None:
        raise TalentEvaluationPlanError("not_found", "Program Academic Year Configuration was not found.")
    if db.query(models.TalentAnnualEvaluationPlan.id).filter_by(program_academic_year_configuration_id=config.id).first():
        raise TalentEvaluationPlanError("plan_conflict", "This Program Academic Year Configuration already has an Annual Evaluation Plan.")
    row = models.TalentAnnualEvaluationPlan(
        school_group_id=school_group_id,
        program_id=config.program_id,
        academic_year_id=config.academic_year_id,
        program_academic_year_configuration_id=config.id,
        status="draft",
        revision=1,
        created_by_user_id=_actor_id(actor),
    )
    db.add(row)
    db.flush()
    _audit(db, row, actor=actor, resource_type="annual_evaluation_plan", resource_id=row.id, action="create", after={"status": "draft", "configuration_id": config.id})
    return row


def list_plans(db, *, school_group_id, program_id=None, academic_year_id=None):
    query = db.query(models.TalentAnnualEvaluationPlan).filter_by(school_group_id=school_group_id)
    if program_id is not None:
        query = query.filter_by(program_id=program_id)
    if academic_year_id is not None:
        query = query.filter_by(academic_year_id=academic_year_id)
    return query.order_by(models.TalentAnnualEvaluationPlan.created_at.desc(), models.TalentAnnualEvaluationPlan.id.desc()).all()


def add_period(db, *, school_group_id, plan_id, expected_plan_revision, label, short_code=None,
               planned_start_date=None, planned_end_date=None, is_required=True, notes=None, actor=None):
    plan = _require_plan(db, school_group_id, plan_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status == "closed":
        raise TalentEvaluationPlanError("plan_closed", "A Closed Plan cannot be changed.")
    start, end = _date(planned_start_date, "planned_start_date"), _date(planned_end_date, "planned_end_date")
    if start and end and start > end:
        raise TalentEvaluationPlanError("invalid_date_range", "planned_start_date must not be after planned_end_date.")
    clean_label = _clean(label, "label", required=True)
    clean_code = _clean(short_code, "short_code", maximum=40)
    normalized_label = normalize_period_identity(clean_label)
    normalized_code = normalize_period_identity(clean_code) if clean_code else None
    duplicate = db.query(models.TalentPlannedEvaluationPeriod.id).filter(
        models.TalentPlannedEvaluationPeriod.annual_evaluation_plan_id == plan.id,
        (models.TalentPlannedEvaluationPeriod.normalized_label == normalized_label)
        | ((models.TalentPlannedEvaluationPeriod.normalized_short_code == normalized_code) if normalized_code else False),
    ).first()
    if duplicate:
        raise TalentEvaluationPlanError("period_identity_conflict", "Period label or short code already exists in this Plan.")
    row = models.TalentPlannedEvaluationPeriod(
        school_group_id=plan.school_group_id, program_id=plan.program_id, academic_year_id=plan.academic_year_id,
        annual_evaluation_plan_id=plan.id,
        sequence=(db.query(func.max(models.TalentPlannedEvaluationPeriod.sequence)).filter_by(annual_evaluation_plan_id=plan.id).scalar() or 0) + 1,
        label=clean_label, normalized_label=normalized_label,
        short_code=clean_code, normalized_short_code=normalized_code,
        planned_start_date=start, planned_end_date=end, is_required=bool(is_required),
        notes=_clean(notes, "notes", maximum=1000), status="planned",
    )
    db.add(row)
    _bump(plan)
    db.flush()
    _audit(db, plan, actor=actor, resource_type="planned_evaluation_period", resource_id=row.id, action="create", after=period_payload(row))
    return plan, row


def update_period(db, *, school_group_id, period_id, expected_plan_revision, actor=None, **changes):
    # Resolve the owning Plan id via an unlocked read, then lock strictly in
    # canonical Plan -> Period order (matching every other cross-row mutation
    # in this module) so a concurrent Plan-first operation (e.g. reorder,
    # activate, close) can never deadlock against this Period-first one.
    period_ref = _require_period(db, school_group_id, period_id)
    plan = _require_plan(db, school_group_id, period_ref.annual_evaluation_plan_id, lock=True)
    period = _require_period(db, school_group_id, period_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status == "closed" or _cycle_for_period(db, period.id):
        raise TalentEvaluationPlanError("period_immutable", "A used Period or Closed Plan cannot be edited.")
    if period.status != "planned":
        raise TalentEvaluationPlanError("period_immutable", "A Cancelled Period cannot be edited.")
    before = period_payload(period)
    if "label" in changes:
        period.label = _clean(changes["label"], "label", required=True)
        period.normalized_label = normalize_period_identity(period.label)
    if "short_code" in changes:
        period.short_code = _clean(changes["short_code"], "short_code", maximum=40)
        period.normalized_short_code = normalize_period_identity(period.short_code) if period.short_code else None
    if "planned_start_date" in changes:
        period.planned_start_date = _date(changes["planned_start_date"], "planned_start_date")
    if "planned_end_date" in changes:
        period.planned_end_date = _date(changes["planned_end_date"], "planned_end_date")
    if period.planned_start_date and period.planned_end_date and period.planned_start_date > period.planned_end_date:
        raise TalentEvaluationPlanError("invalid_date_range", "planned_start_date must not be after planned_end_date.")
    if "is_required" in changes:
        period.is_required = bool(changes["is_required"])
    if "notes" in changes:
        period.notes = _clean(changes["notes"], "notes", maximum=1000)
    with db.no_autoflush:
        duplicate = db.query(models.TalentPlannedEvaluationPeriod.id).filter(
            models.TalentPlannedEvaluationPeriod.annual_evaluation_plan_id == plan.id,
            models.TalentPlannedEvaluationPeriod.id != period.id,
            (models.TalentPlannedEvaluationPeriod.normalized_label == period.normalized_label)
            | ((models.TalentPlannedEvaluationPeriod.normalized_short_code == period.normalized_short_code) if period.normalized_short_code else False),
        ).first()
    if duplicate:
        raise TalentEvaluationPlanError("period_identity_conflict", "Period label or short code already exists in this Plan.")
    period.updated_at = datetime.utcnow()
    _bump(plan)
    db.flush()
    _audit(db, plan, actor=actor, resource_type="planned_evaluation_period", resource_id=period.id, action="update", before=before, after=period_payload(period))
    return plan, period


def delete_period(db, *, school_group_id, period_id, expected_plan_revision, actor=None):
    # See update_period: lock Plan before Period to keep every cross-row path
    # in this module on the same canonical Plan -> Period lock order.
    period_ref = _require_period(db, school_group_id, period_id)
    plan = _require_plan(db, school_group_id, period_ref.annual_evaluation_plan_id, lock=True)
    period = _require_period(db, school_group_id, period_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status != "draft" or _cycle_for_period(db, period.id):
        raise TalentEvaluationPlanError("period_immutable", "Only an unused Draft Plan Period may be removed.")
    before = period_payload(period)
    removed_sequence = period.sequence
    db.delete(period)
    db.flush()
    for row in _periods(db, plan.id, lock=True):
        if row.sequence > removed_sequence:
            row.sequence -= 1
    _bump(plan)
    _audit(db, plan, actor=actor, resource_type="planned_evaluation_period", resource_id=period.id, action="remove", before=before)
    return plan


def reorder_periods(db, *, school_group_id, plan_id, expected_plan_revision, period_ids, actor=None):
    plan = _require_plan(db, school_group_id, plan_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status == "closed":
        raise TalentEvaluationPlanError("plan_closed", "A Closed Plan cannot be reordered.")
    rows = _periods(db, plan.id, lock=True)
    requested = [int(value) for value in period_ids]
    if len(requested) != len(set(requested)) or set(requested) != {row.id for row in rows}:
        raise TalentEvaluationPlanError("invalid_period_order", "Period order must contain each Plan Period exactly once.")
    by_id = {row.id: row for row in rows}
    old = [row.id for row in rows]
    anchors = {row.id: row.sequence for row in rows if _cycle_for_period(db, row.id)}
    last_anchor = max(anchors.values(), default=0)
    if requested[:last_anchor] != old[:last_anchor]:
        raise TalentEvaluationPlanError("historical_anchor_immutable", "Only the future tail after the last used Period may be reordered.")
    for position, period_id in enumerate(requested, 1):
        if period_id in anchors and anchors[period_id] != position:
            raise TalentEvaluationPlanError("historical_anchor_immutable", "Used Period positions cannot be changed.")
    # Temporary positive values avoid transient UNIQUE(plan, sequence) conflicts
    # without violating the sequence > 0 database invariant.
    offset = len(rows) + 1
    for index, row in enumerate(rows, 1):
        row.sequence = offset + index
    db.flush()
    for position, period_id in enumerate(requested, 1):
        by_id[period_id].sequence = position
    _bump(plan)
    db.flush()
    _audit(db, plan, actor=actor, resource_type="annual_evaluation_plan", resource_id=plan.id, action="reorder_periods", before={"period_ids": old}, after={"period_ids": requested})
    return plan


def activate_plan(db, *, school_group_id, plan_id, expected_plan_revision, actor=None):
    plan = _require_plan(db, school_group_id, plan_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status != "draft":
        raise TalentEvaluationPlanError("invalid_lifecycle", "Only a Draft Plan can be activated.")
    config = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        id=plan.program_academic_year_configuration_id, school_group_id=school_group_id,
        program_id=plan.program_id, academic_year_id=plan.academic_year_id,
    ).one_or_none()
    rows = _periods(db, plan.id, lock=True)
    if config is None or not config.is_enabled:
        raise TalentEvaluationPlanError("annual_configuration_unavailable", "An enabled Program Academic Year Configuration is required.")
    if not rows or [row.sequence for row in rows] != list(range(1, len(rows) + 1)):
        raise TalentEvaluationPlanError("invalid_period_set", "Activation requires a non-empty contiguous Period set.")
    before = {"status": plan.status, "revision": plan.revision}
    plan.status = "active"
    plan.activated_at = datetime.utcnow()
    plan.activated_by_user_id = _actor_id(actor)
    _bump(plan)
    _audit(db, plan, actor=actor, resource_type="annual_evaluation_plan", resource_id=plan.id, action="activate", before=before, after={"status": plan.status, "revision": plan.revision})
    return plan


def cancel_period(db, *, school_group_id, period_id, expected_plan_revision, cancellation_reason, actor=None):
    # See update_period: lock Plan before Period to keep every cross-row path
    # in this module on the same canonical Plan -> Period lock order.
    period_ref = _require_period(db, school_group_id, period_id)
    plan = _require_plan(db, school_group_id, period_ref.annual_evaluation_plan_id, lock=True)
    period = _require_period(db, school_group_id, period_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status != "active" or period.status != "planned":
        raise TalentEvaluationPlanError("invalid_lifecycle", "Only a Planned Period in an Active Plan can be cancelled.")
    if _cycle_for_period(db, period.id):
        raise TalentEvaluationPlanError("period_linked", "Unlink the Draft Cycle before cancelling this Period.")
    before = period_payload(period)
    period.status = "cancelled"
    period.cancellation_reason = _clean(cancellation_reason, "cancellation_reason", required=True, maximum=500)
    period.cancelled_at = datetime.utcnow()
    period.cancelled_by_user_id = _actor_id(actor)
    period.updated_at = period.cancelled_at
    _bump(plan)
    _audit(db, plan, actor=actor, resource_type="planned_evaluation_period", resource_id=period.id, action="cancel", before=before, after=period_payload(period))
    return plan, period


def closure_preflight(db, *, school_group_id, plan_id, include_cycle_details=False):
    plan = _require_plan(db, school_group_id, plan_id)
    items, outstanding = [], []
    for period in _periods(db, plan.id):
        cycle = _cycle_for_period(db, period.id)
        resolution = "cancelled" if period.status == "cancelled" and cycle is None else (
            "executed" if period.status == "planned" and cycle is not None and cycle.status == "closed" else "outstanding"
        )
        if period.is_required and resolution == "outstanding":
            outstanding.append(period.id)
        item = {"period_id": period.id, "sequence": period.sequence, "is_required": period.is_required}
        if include_cycle_details:
            item["resolution"] = resolution
        if include_cycle_details and cycle is not None:
            item["cycle"] = {"id": cycle.id, "status": cycle.status, "revision": cycle.revision}
        items.append(item)
    return {"plan_id": plan.id, "can_close": plan.status == "active" and not outstanding, "outstanding_required_period_ids": outstanding, "periods": items}


def close_plan(db, *, school_group_id, plan_id, expected_plan_revision, actor=None):
    plan = _require_plan(db, school_group_id, plan_id, lock=True)
    _check_revision(plan, expected_plan_revision)
    if plan.status != "active":
        raise TalentEvaluationPlanError("invalid_lifecycle", "Only an Active Plan can be closed.")
    preflight = closure_preflight(db, school_group_id=school_group_id, plan_id=plan.id)
    if not preflight["can_close"]:
        raise TalentEvaluationPlanError("required_periods_outstanding", "Required Periods remain outstanding.")
    before = {"status": plan.status, "revision": plan.revision}
    plan.status = "closed"
    plan.closed_at = datetime.utcnow()
    plan.closed_by_user_id = _actor_id(actor)
    _bump(plan)
    _audit(db, plan, actor=actor, resource_type="annual_evaluation_plan", resource_id=plan.id, action="close", before=before, after={"status": plan.status, "revision": plan.revision})
    return plan


def eligible_periods(db, *, school_group_id, cycle_id):
    cycle = db.query(models.TalentAssessmentCycle).filter_by(id=cycle_id, school_group_id=school_group_id).one_or_none()
    if cycle is None:
        raise TalentEvaluationPlanError("not_found", "Talent Assessment Cycle was not found.")
    return db.query(models.TalentPlannedEvaluationPeriod).join(models.TalentAnnualEvaluationPlan).filter(
        models.TalentPlannedEvaluationPeriod.school_group_id == school_group_id,
        models.TalentPlannedEvaluationPeriod.program_id == cycle.program_id,
        models.TalentPlannedEvaluationPeriod.academic_year_id == cycle.academic_year_id,
        models.TalentPlannedEvaluationPeriod.status == "planned",
        models.TalentAnnualEvaluationPlan.status == "active",
        ~models.TalentPlannedEvaluationPeriod.id.in_(
            db.query(models.TalentAssessmentCycle.planned_evaluation_period_id).filter(models.TalentAssessmentCycle.planned_evaluation_period_id.is_not(None))
        ),
    ).order_by(models.TalentPlannedEvaluationPeriod.sequence).all()


def validate_cycle_period_link(db, *, school_group_id, cycle_id, period_id, expected_plan_revision,
                               expected_cycle_revision, unlink=False, actor=None):
    period_ref = _require_period(db, school_group_id, period_id)
    plan = _require_plan(db, school_group_id, period_ref.annual_evaluation_plan_id, lock=True)
    period = _require_period(db, school_group_id, period_id, lock=True)
    cycle = db.query(models.TalentAssessmentCycle).filter_by(id=cycle_id, school_group_id=school_group_id).with_for_update().one_or_none()
    if cycle is None:
        raise TalentEvaluationPlanError("not_found", "Talent Assessment Cycle was not found.")
    _check_revision(plan, expected_plan_revision)
    if cycle.revision != int(expected_cycle_revision):
        raise TalentEvaluationPlanError("stale_cycle", "Cycle changed since it was read.")
    if cycle.status != "draft":
        raise TalentEvaluationPlanError("cycle_immutable", "Only a Draft Cycle link may change.")
    if (cycle.program_id, cycle.academic_year_id) != (plan.program_id, plan.academic_year_id):
        raise TalentEvaluationPlanError("period_context_mismatch", "Cycle and Period must share the same Program and Academic Year.")
    before = {"period_id": cycle.planned_evaluation_period_id, "plan_revision": plan.revision, "cycle_revision": cycle.revision}
    if unlink:
        if cycle.planned_evaluation_period_id != period.id:
            raise TalentEvaluationPlanError("period_link_mismatch", "Cycle is not linked to this Period.")
        if plan.status == "closed" and period.is_required:
            raise TalentEvaluationPlanError("closed_plan_link_immutable", "Only an optional Draft Cycle may be unlinked from a Closed Plan.")
        if plan.status not in {"active", "closed"}:
            raise TalentEvaluationPlanError("invalid_lifecycle", "Plan does not permit unlinking.")
        cycle.planned_evaluation_period_id = None
        action = "unlink_cycle"
    else:
        if plan.status != "active" or period.status != "planned":
            raise TalentEvaluationPlanError("invalid_lifecycle", "Linking requires an Active Plan and Planned Period.")
        if cycle.planned_evaluation_period_id is not None or _cycle_for_period(db, period.id):
            raise TalentEvaluationPlanError("period_link_conflict", "Cycle or Period is already linked.")
        cycle.planned_evaluation_period_id = period.id
        action = "link_cycle"
    _bump(plan)
    cycle.revision += 1
    cycle.updated_at = datetime.utcnow()
    cycle.updated_by_user_id = _actor_id(actor)
    db.flush()
    after = {"period_id": cycle.planned_evaluation_period_id, "plan_revision": plan.revision, "cycle_revision": cycle.revision}
    _audit(db, plan, actor=actor, resource_type="planned_evaluation_period", resource_id=period.id, action=action, before=before, after=after)
    return plan, period, cycle


def validate_linked_cycle_open(db, *, cycle):
    if cycle.planned_evaluation_period_id is None:
        return None, None
    period_ref = _require_period(db, cycle.school_group_id, cycle.planned_evaluation_period_id)
    plan = _require_plan(db, cycle.school_group_id, period_ref.annual_evaluation_plan_id, lock=True)
    period = _require_period(db, cycle.school_group_id, cycle.planned_evaluation_period_id, lock=True)
    if plan.status != "active" or period.status != "planned" or (plan.program_id, plan.academic_year_id) != (cycle.program_id, cycle.academic_year_id):
        raise TalentEvaluationPlanError("linked_period_context_invalid", "Linked planning context is no longer valid.")
    return plan, period


def rollover_preview(db, *, school_group_id, source_plan_id, destination_configuration_id):
    source = _require_plan(db, school_group_id, source_plan_id)
    if source.status not in {"active", "closed"}:
        raise TalentEvaluationPlanError("invalid_lifecycle", "Only an Active or Closed Plan may roll over.")
    config = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(id=destination_configuration_id, school_group_id=school_group_id).one_or_none()
    if config is None:
        raise TalentEvaluationPlanError("not_found", "Destination Program Academic Year Configuration was not found.")
    if not config.is_enabled:
        raise TalentEvaluationPlanError("annual_configuration_unavailable", "Destination Program Academic Year Configuration must be enabled.")
    if config.program_id != source.program_id or config.academic_year_id == source.academic_year_id:
        raise TalentEvaluationPlanError("rollover_context_invalid", "Destination must be the same Program in a different Academic Year.")
    if db.query(models.TalentAnnualEvaluationPlan).filter_by(program_academic_year_configuration_id=config.id).first():
        raise TalentEvaluationPlanError("plan_conflict", "Destination already has an Annual Evaluation Plan.")
    copied = [{"label": row.label, "short_code": row.short_code, "sequence": row.sequence, "is_required": row.is_required} for row in _periods(db, source.id)]
    return source, config, copied


def rollover_plan(db, *, school_group_id, source_plan_id, destination_configuration_id, expected_plan_revision, actor=None):
    source = _require_plan(db, school_group_id, source_plan_id, lock=True)
    _check_revision(source, expected_plan_revision)
    source, config, copied = rollover_preview(db, school_group_id=school_group_id, source_plan_id=source.id, destination_configuration_id=destination_configuration_id)
    destination = models.TalentAnnualEvaluationPlan(
        school_group_id=school_group_id, program_id=source.program_id, academic_year_id=config.academic_year_id,
        program_academic_year_configuration_id=config.id, source_plan_id=source.id, status="draft", revision=1,
        created_by_user_id=_actor_id(actor),
    )
    db.add(destination)
    db.flush()
    for item in copied:
        db.add(models.TalentPlannedEvaluationPeriod(
            school_group_id=school_group_id, program_id=source.program_id, academic_year_id=config.academic_year_id,
            annual_evaluation_plan_id=destination.id, sequence=item["sequence"], label=item["label"],
            normalized_label=normalize_period_identity(item["label"]), short_code=item["short_code"],
            normalized_short_code=normalize_period_identity(item["short_code"]) if item["short_code"] else None,
            is_required=item["is_required"], status="planned",
        ))
    db.flush()
    _audit(db, destination, actor=actor, resource_type="annual_evaluation_plan", resource_id=destination.id, action="rollover", after={"source_plan_id": source.id, "period_count": len(copied)})
    return destination
