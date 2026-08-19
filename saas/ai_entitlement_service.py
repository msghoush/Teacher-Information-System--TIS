from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import (
    ai_consumption_policy,
    ai_feature_registry,
    commercial_state_service,
    entitlement_service,
    models,
)
from workspace_classification import WorkspaceClassification


DEMO_LIMIT_MESSAGE = "You have reached the demo limit for this AI feature."
SUBSCRIBE_CTA = {"label": "Subscribe Now", "url": "/saas/subscription"}


@dataclass(frozen=True)
class AIEntitlementDecision:
    allowed: bool
    reason_code: str
    feature_key: str
    feature_name: str = ""
    current_usage: int = 0
    usage_limit: int | None = None
    remaining_usage: int | None = None
    workspace_classification: str = ""
    plan_code: str = ""
    plan_name: str = ""
    message: str = ""
    cta_label: str = ""
    cta_url: str = ""
    idempotent_replay: bool = False
    entitlement_type: str = ""


def _decision(feature_key: str, *, allowed: bool, reason_code: str, feature=None, **details):
    return AIEntitlementDecision(
        allowed=allowed,
        reason_code=reason_code,
        feature_key=feature_key,
        feature_name=feature.display_name if feature else "",
        **details,
    )


def _metric_context(entitlement_type: str) -> str:
    return ai_consumption_policy.metric_context_for_entitlement_type(entitlement_type)


def _authorized_workspace(db: Session, user, school_group_id: int):
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        return None
    if group_id <= 0 or user is None or not auth.is_user_active(user):
        return None
    if not auth.is_platform_user(user):
        assigned_group_id = auth.get_user_school_group_id(db, user)
        scoped_group_id = getattr(user, "scope_school_group_id", None)
        if int(scoped_group_id or assigned_group_id or 0) != group_id:
            return None
    return db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == group_id
    ).one_or_none()


def _usage_count(db: Session, school_group_id: int, feature_key: str, metric_context: str) -> int:
    row = db.query(models.AIFeatureUsageCounter).filter_by(
        school_group_id=school_group_id,
        feature_key=feature_key,
        metric_context=metric_context,
    ).one_or_none()
    return int(row.successful_uses or 0) if row else 0


def _paid_plan_context(db: Session, commercial):
    workspace_entitlement = commercial.workspace_entitlement
    subscription_id = getattr(workspace_entitlement, "payment_subscription_id", None)
    subscription = db.get(models.PaymentSubscription, subscription_id) if subscription_id else None
    plan = db.get(models.SubscriptionPlan, subscription.plan_id) if subscription else None
    return plan, workspace_entitlement


def evaluate_ai_availability(
    db: Session,
    *,
    user,
    school_group_id: int,
    feature_key: str,
    branch_id: int | None = None,
) -> AIEntitlementDecision:
    cleaned_key = str(feature_key or "").strip().lower()
    group = _authorized_workspace(db, user, school_group_id)
    if group is None:
        return _decision(
            cleaned_key,
            allowed=False,
            reason_code="workspace_access_denied",
        )
    classification = str(group.workspace_classification or "")
    commercial = commercial_state_service.resolve_commercial_state(db, group.id)
    if not commercial.resolved:
        return _decision(
            cleaned_key,
            allowed=False,
            reason_code="commercial_state_unresolved",
            workspace_classification=classification,
            message="AI access is temporarily unavailable for this workspace.",
        )
    state = commercial.commercial_state
    if classification == WorkspaceClassification.CUSTOMER_DEMO.value and state != "customer_demo_active":
        return _decision(
            cleaned_key,
            allowed=False,
            reason_code="demo_expired",
            workspace_classification=classification,
            message="This demo has expired. Subscribe to continue using AI features.",
            cta_label=SUBSCRIBE_CTA["label"],
            cta_url=SUBSCRIBE_CTA["url"],
        )
    feature = ai_feature_registry.get_feature(cleaned_key)
    if feature is None:
        return _decision(
            cleaned_key,
            allowed=False,
            reason_code="unknown_ai_feature",
            workspace_classification=classification,
        )
    if not feature.enabled:
        return _decision(
            cleaned_key,
            allowed=False,
            reason_code="ai_feature_disabled",
            feature=feature,
            workspace_classification=classification,
            message="This AI feature is not currently available.",
        )
    feature_access = entitlement_service.evaluate_feature_access(
        db,
        user,
        feature.entitlement_key,
        feature.permission_key,
        school_group_id=group.id,
        branch_id=branch_id,
        academic_year_id=(
            getattr(user, "scope_academic_year_id", None)
            if branch_id is not None
            else None
        ),
    )
    if not feature_access.allowed:
        reason = (
            "ai_permission_denied"
            if feature_access.reason_code == "permission_denied"
            else "ai_commercial_access_denied"
        )
        return _decision(
            cleaned_key,
            allowed=False,
            reason_code=reason,
            feature=feature,
            workspace_classification=classification,
            entitlement_type=feature_access.entitlement_type,
            message=(
                "You do not have permission to use this AI feature."
                if reason == "ai_permission_denied"
                else "AI access is unavailable for this workspace."
            ),
        )

    entitlement_type = feature_access.entitlement_type
    plan_code = ""
    plan_name = ""
    if entitlement_type == "paid":
        plan, workspace_entitlement = _paid_plan_context(db, commercial)
        plan_code = str(getattr(plan, "plan_code", "") or "")
        plan_name = str(getattr(plan, "plan_name", "") or "")
    return _decision(
        cleaned_key,
        allowed=True,
        reason_code="ai_feature_available",
        feature=feature,
        workspace_classification=classification,
        entitlement_type=entitlement_type,
        plan_code=plan_code,
        plan_name=plan_name,
    )


def evaluate_ai_entitlement(
    db: Session,
    *,
    user,
    school_group_id: int,
    feature_key: str,
    branch_id: int | None = None,
) -> AIEntitlementDecision:
    availability = evaluate_ai_availability(
        db,
        user=user,
        school_group_id=school_group_id,
        feature_key=feature_key,
        branch_id=branch_id,
    )
    if not availability.allowed:
        return availability
    policy = ai_consumption_policy.resolve_ai_consumption_policy(
        db,
        school_group_id=school_group_id,
        entitlement_type=availability.entitlement_type,
        feature_key=availability.feature_key,
        branch_id=branch_id,
    )
    usage = _usage_count(
        db, school_group_id, availability.feature_key, policy.metric_context
    )
    remaining = (
        max(policy.usage_limit - usage, 0)
        if policy.usage_limit is not None
        else None
    )
    allowed = remaining is None or remaining > 0
    source_reason = {
        "internal_sandbox": "internal_sandbox_allowed",
        "demo": "demo_allowed",
        "paid": "paid_plan_allowed",
        "promo": "promo_allowed",
    }.get(availability.entitlement_type, "ai_feature_allowed")
    return AIEntitlementDecision(
        **{
            **availability.__dict__,
            "allowed": allowed,
            "reason_code": (
                source_reason
                if allowed
                else "demo_feature_limit_exhausted"
                if availability.entitlement_type == "demo"
                else "ai_consumption_limit_exhausted"
            ),
            "current_usage": usage,
            "usage_limit": policy.usage_limit,
            "remaining_usage": remaining,
            "message": "" if allowed else DEMO_LIMIT_MESSAGE,
            "cta_label": "" if allowed else SUBSCRIBE_CTA["label"],
            "cta_url": "" if allowed else SUBSCRIBE_CTA["url"],
        }
    )


def _ensure_counter(
    db: Session,
    *,
    school_group_id: int,
    feature_key: str,
    metric_context: str,
    classification: str,
    plan_code: str,
):
    params = {
        "school_group_id": school_group_id,
        "feature_key": feature_key,
        "metric_context": metric_context,
        "classification": classification,
        "plan_code": plan_code or None,
    }
    if db.get_bind().dialect.name == "postgresql":
        sql = """
            INSERT INTO ai_feature_usage_counters (
                school_group_id, feature_key, metric_context,
                workspace_classification, plan_code, successful_uses,
                reserved_uses, created_at, updated_at
            ) VALUES (
                :school_group_id, :feature_key, :metric_context,
                :classification, :plan_code, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            ON CONFLICT (school_group_id, feature_key, metric_context) DO NOTHING
        """
    else:
        sql = """
            INSERT OR IGNORE INTO ai_feature_usage_counters (
                school_group_id, feature_key, metric_context,
                workspace_classification, plan_code, successful_uses,
                reserved_uses, created_at, updated_at
            ) VALUES (
                :school_group_id, :feature_key, :metric_context,
                :classification, :plan_code, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """
    db.execute(text(sql), params)
    return db.query(models.AIFeatureUsageCounter).filter_by(
        school_group_id=school_group_id,
        feature_key=feature_key,
        metric_context=metric_context,
    ).with_for_update().one()


def reserve_ai_use(
    db: Session,
    *,
    user,
    school_group_id: int,
    feature_key: str,
    operation_key: str,
    branch_id: int | None = None,
) -> AIEntitlementDecision:
    decision = evaluate_ai_entitlement(
        db,
        user=user,
        school_group_id=school_group_id,
        feature_key=feature_key,
        branch_id=branch_id,
    )
    if not decision.allowed:
        return decision
    feature = ai_feature_registry.get_feature(decision.feature_key)
    metric_context = _metric_context(decision.entitlement_type)
    cleaned_operation_key = str(operation_key or "").strip()
    if not cleaned_operation_key or len(cleaned_operation_key) > 120:
        raise ValueError("AI operation key must contain 1 to 120 characters.")

    counter = _ensure_counter(
        db,
        school_group_id=school_group_id,
        feature_key=decision.feature_key,
        metric_context=metric_context,
        classification=decision.workspace_classification,
        plan_code=decision.plan_code,
    )
    existing = db.query(models.AIFeatureUsageEvent).filter_by(
        school_group_id=school_group_id,
        feature_key=decision.feature_key,
        metric_context=metric_context,
        operation_key=cleaned_operation_key,
    ).one_or_none()
    if existing:
        pending = existing.result_status == "pending"
        return AIEntitlementDecision(
            **{
                **decision.__dict__,
                "current_usage": int(counter.successful_uses or 0),
                "remaining_usage": (
                    max(int(decision.usage_limit) - int(counter.successful_uses or 0), 0)
                    if decision.usage_limit is not None
                    else None
                ),
                "idempotent_replay": True,
                "allowed": existing.result_status in {"pending", "successful"},
                "reason_code": (
                    "ai_operation_reserved" if pending
                    else "ai_operation_completed" if existing.result_status == "successful"
                    else "ai_operation_failed"
                ),
            }
        )

    current = int(counter.successful_uses or 0)
    reserved = int(counter.reserved_uses or 0)
    if (
        decision.usage_limit is not None
        and current + reserved >= decision.usage_limit
    ):
        return _decision(
            decision.feature_key,
            allowed=False,
            reason_code=(
                "demo_feature_limit_exhausted"
                if decision.entitlement_type == "demo"
                else "ai_consumption_limit_exhausted"
            ),
            feature=feature,
            current_usage=current,
            usage_limit=decision.usage_limit,
            remaining_usage=0,
            workspace_classification=decision.workspace_classification,
            message=DEMO_LIMIT_MESSAGE,
            cta_label=SUBSCRIBE_CTA["label"],
            cta_url=SUBSCRIBE_CTA["url"],
        )

    counter.reserved_uses = reserved + 1
    counter.workspace_classification = decision.workspace_classification
    counter.plan_code = decision.plan_code or None
    db.add(models.AIFeatureUsageEvent(
        school_group_id=school_group_id,
        feature_key=decision.feature_key,
        metric_context=metric_context,
        workspace_classification=decision.workspace_classification,
        plan_code=decision.plan_code or None,
        user_id=getattr(user, "id", None),
        operation_key=cleaned_operation_key,
        result_status="pending",
    ))
    db.flush()
    return AIEntitlementDecision(
        **{
            **decision.__dict__,
            "reason_code": "ai_operation_reserved",
            "current_usage": current,
            "remaining_usage": (
                max(int(decision.usage_limit) - current - reserved - 1, 0)
                if decision.usage_limit is not None
                else None
            ),
        }
    )


def complete_ai_use(
    db: Session,
    *,
    user,
    school_group_id: int,
    feature_key: str,
    operation_key: str,
    successful: bool,
    branch_id: int | None = None,
) -> AIEntitlementDecision:
    cleaned_key = str(feature_key or "").strip().lower()
    feature = ai_feature_registry.get_feature(cleaned_key)
    group = _authorized_workspace(db, user, school_group_id)
    if group is None or feature is None:
        return _decision(cleaned_key, allowed=False, reason_code="workspace_access_denied")
    commercial = commercial_state_service.resolve_commercial_state(db, group.id)
    entitlement_type = str(
        getattr(commercial.workspace_entitlement, "entitlement_type", "") or ""
    )
    policy = ai_consumption_policy.resolve_ai_consumption_policy(
        db,
        school_group_id=group.id,
        entitlement_type=entitlement_type,
        feature_key=cleaned_key,
        branch_id=branch_id,
    )
    metric_context = policy.metric_context
    usage_limit = policy.usage_limit
    counter = db.query(models.AIFeatureUsageCounter).filter_by(
        school_group_id=group.id,
        feature_key=cleaned_key,
        metric_context=metric_context,
    ).with_for_update().one_or_none()
    event = db.query(models.AIFeatureUsageEvent).filter_by(
        school_group_id=group.id,
        feature_key=cleaned_key,
        metric_context=metric_context,
        operation_key=str(operation_key or "").strip(),
    ).with_for_update().one_or_none()
    if counter is None or event is None:
        return _decision(
            cleaned_key, allowed=False, reason_code="ai_operation_not_reserved", feature=feature
        )
    if event.result_status != "pending":
        return _decision(
            cleaned_key,
            allowed=event.result_status == "successful",
            reason_code=(
                "ai_operation_completed"
                if event.result_status == "successful"
                else "ai_operation_failed"
            ),
            feature=feature,
            current_usage=int(counter.successful_uses or 0),
            usage_limit=usage_limit,
            remaining_usage=(
                max(int(usage_limit) - int(counter.successful_uses or 0), 0)
                if usage_limit is not None
                else None
            ),
            workspace_classification=str(group.workspace_classification or ""),
            idempotent_replay=True,
        )
    counter.reserved_uses = max(int(counter.reserved_uses or 0) - 1, 0)
    if successful:
        counter.successful_uses = int(counter.successful_uses or 0) + 1
        event.result_status = "successful"
    else:
        event.result_status = "failed"
    event.completed_at = datetime.now(UTC).replace(tzinfo=None)
    db.flush()
    return _decision(
        cleaned_key,
        allowed=successful,
        reason_code="ai_operation_completed" if successful else "ai_operation_failed",
        feature=feature,
        current_usage=int(counter.successful_uses or 0),
        usage_limit=usage_limit,
        remaining_usage=(
            max(int(usage_limit) - int(counter.successful_uses or 0), 0)
            if usage_limit is not None
            else None
        ),
        workspace_classification=str(group.workspace_classification or ""),
    )


def consume_successful_ai_use(
    db: Session,
    *,
    user,
    school_group_id: int,
    feature_key: str,
    operation_key: str | None = None,
    branch_id: int | None = None,
) -> AIEntitlementDecision:
    key = str(operation_key or "").strip() or str(uuid.uuid4())
    reservation = reserve_ai_use(
        db,
        user=user,
        school_group_id=school_group_id,
        feature_key=feature_key,
        operation_key=key,
        branch_id=branch_id,
    )
    if not reservation.allowed or reservation.reason_code == "ai_operation_completed":
        return reservation
    return complete_ai_use(
        db,
        user=user,
        school_group_id=school_group_id,
        feature_key=feature_key,
        operation_key=key,
        successful=True,
        branch_id=branch_id,
    )


def denial_payload(decision: AIEntitlementDecision) -> dict:
    return {
        "allowed": decision.allowed,
        "code": decision.reason_code,
        "feature": decision.feature_key,
        "message": decision.message,
        "usage": {
            "current": decision.current_usage,
            "limit": decision.usage_limit,
            "remaining": decision.remaining_usage,
        },
        "cta": (
            {"label": decision.cta_label, "url": decision.cta_url}
            if decision.cta_label and decision.cta_url
            else None
        ),
    }
