from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from sqlalchemy.orm import Session

import models
from saas import (
    demo_lifecycle_service,
    entitlement_service,
    models as saas_models,
    subscription_change_service,
    subscription_plan_change_service,
)
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


logger = logging.getLogger(__name__)


ACTIVE = "active"
TRIALING = "trialing"
PAYMENT_PROCESSING = "payment_processing"
PAST_DUE = "past_due"
PAUSED = "paused"
CANCELED = "canceled"
EXPIRED = "expired"
SUSPENDED = "suspended"
ARCHIVED = "archived"
INCONSISTENT = "inconsistent"


@dataclass(frozen=True)
class CommercialAccessState:
    blocked: bool
    kind: str = ""
    reason_code: str = ""
    commercial_state: str = ACTIVE
    current_plan_code: str = ""
    current_plan_name: str = ""
    subscription_status: str = ""
    current_period_end: datetime | None = None
    next_billed_at: datetime | None = None
    workspace_lifecycle: str = ""
    pending_change_type: str = ""
    pending_change_status: str = ""
    pending_target_plan_code: str = ""
    pending_target_plan_name: str = ""
    recommended_action: str = ""
    customer_message_key: str = ""

    @property
    def allowed_access(self) -> bool:
        return not self.blocked


@dataclass(frozen=True)
class CommercialAccessPresentation:
    title: str
    message: str
    action_label: str
    action_url: str


def _clean(value) -> str:
    return str(value or "").strip()


def _paid_state(
    *,
    blocked: bool,
    state: str,
    reason: str,
    group,
    resolution,
    subscription=None,
    pending=None,
    target_plan=None,
    action: str,
    message_key: str,
) -> CommercialAccessState:
    return CommercialAccessState(
        blocked=blocked,
        kind="subscription",
        reason_code=reason,
        commercial_state=state,
        current_plan_code=_clean(getattr(resolution, "plan_code", "")),
        current_plan_name=_clean(getattr(resolution, "plan_name", "")),
        subscription_status=_clean(getattr(subscription, "status", "")).lower(),
        current_period_end=getattr(subscription, "current_period_end", None),
        next_billed_at=getattr(subscription, "next_billed_at", None),
        workspace_lifecycle=_clean(getattr(group, "workspace_lifecycle_status", "")).lower(),
        pending_change_type=_clean(getattr(pending, "change_type", "")),
        pending_change_status=_clean(getattr(pending, "status", "")),
        pending_target_plan_code=_clean(getattr(target_plan, "plan_code", "")),
        pending_target_plan_name=_clean(getattr(target_plan, "plan_name", "")),
        recommended_action=action,
        customer_message_key=message_key,
    )


def _pending_context(db: Session, subscription):
    if subscription is None:
        return None, None
    pending = subscription_change_service.get_pending_change(db, subscription.id)
    target_plan = (
        db.get(saas_models.SubscriptionPlan, pending.target_plan_id)
        if pending is not None and pending.target_plan_id
        else None
    )
    return pending, target_plan


def _log_inconsistent(group_id: int, reason: str, *, resolution=None) -> None:
    logger.warning(
        "Commercial access requires review school_group_id=%s reason=%s entitlement_reason=%s",
        group_id,
        reason,
        _clean(getattr(resolution, "reason_code", "")),
    )


def customer_access_presentation(
    state: CommercialAccessState,
) -> CommercialAccessPresentation:
    if state.kind == "demo":
        return CommercialAccessPresentation(
            title="Your TIS demo has ended.",
            message=(
                "Your organization and data are safely preserved. Subscribe to a TIS "
                "plan to continue accessing your workspace."
            ),
            action_label="Subscribe Now",
            action_url="/saas/subscription",
        )
    presentations = {
        PAYMENT_PROCESSING: CommercialAccessPresentation(
            "Your subscription payment is still processing.",
            "We are waiting for billing confirmation before workspace access can continue.",
            "View Subscription",
            "/saas/subscription",
        ),
        PAST_DUE: CommercialAccessPresentation(
            "Your payment is past due.",
            "Review your subscription billing to restore workspace access.",
            "Review Payment",
            "/saas/subscription",
        ),
        PAUSED: CommercialAccessPresentation(
            "Your subscription is paused.",
            "Review your subscription or contact the TIS team for help restoring access.",
            "Review Subscription",
            "/saas/subscription",
        ),
        EXPIRED: CommercialAccessPresentation(
            "Your TIS subscription has expired.",
            "Renew your subscription to restore access to your workspace.",
            "Renew Subscription",
            "/saas/subscription",
        ),
        SUSPENDED: CommercialAccessPresentation(
            "Your workspace access is suspended.",
            "Please contact the TIS team to review the workspace status.",
            "Contact the TIS Team",
            "",
        ),
        ARCHIVED: CommercialAccessPresentation(
            "Your workspace is archived.",
            "Please contact the TIS team if this workspace should be restored.",
            "Contact the TIS Team",
            "",
        ),
        INCONSISTENT: CommercialAccessPresentation(
            "We need to verify your subscription status.",
            "Please contact the TIS team. Your workspace data remains safely preserved.",
            "Contact the TIS Team",
            "",
        ),
    }
    return presentations.get(state.commercial_state, presentations[INCONSISTENT])


def resolve_workspace_access(
    db: Session, school_group_id: int | None
) -> CommercialAccessState:
    if not school_group_id:
        return CommercialAccessState(False)
    group = db.get(models.SchoolGroup, int(school_group_id))
    if group is None:
        return CommercialAccessState(False)
    if group.workspace_classification == WorkspaceClassification.CUSTOMER_DEMO.value:
        lifecycle = demo_lifecycle_service.resolve_demo_lifecycle(
            db, school_group_id=group.id
        )
        if lifecycle.can_access:
            return CommercialAccessState(
                False,
                "demo",
                "demo_active",
                commercial_state=ACTIVE,
                workspace_lifecycle=_clean(group.workspace_lifecycle_status).lower(),
                recommended_action="enter_workspace",
                customer_message_key="demo_active",
            )
        return CommercialAccessState(
            blocked=True,
            kind="demo",
            reason_code=(
                "demo_expired"
                if lifecycle.lifecycle_state == "expired"
                else "demo_access_unavailable"
            ),
            commercial_state=(
                EXPIRED if lifecycle.lifecycle_state == "expired" else INCONSISTENT
            ),
            workspace_lifecycle=_clean(group.workspace_lifecycle_status).lower(),
            recommended_action="subscribe" if lifecycle.lifecycle_state == "expired" else "contact_support",
            customer_message_key=(
                "demo_expired"
                if lifecycle.lifecycle_state == "expired"
                else "demo_access_unavailable"
            ),
        )
    if group.workspace_classification == WorkspaceClassification.CUSTOMER.value:
        from saas import promo_grant_service, workspace_entitlement_service

        lifecycle = _clean(group.workspace_lifecycle_status).lower()
        grant = promo_grant_service.resolve_promo_grant(db, group.id)
        entitlement = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
        if entitlement.active and entitlement.entitlement_type == "paid":
            resolution = entitlement_service.resolve_entitlements(db, group.id)
            subscription = (
                db.get(saas_models.PaymentSubscription, resolution.subscription_id)
                if resolution.subscription_id
                else None
            )
            pending, target_plan = _pending_context(db, subscription)
            if lifecycle == WorkspaceLifecycleStatus.ACTIVE.value and subscription is not None:
                status = _clean(subscription.status).lower()
                if resolution.resolved and status in {"active", "trialing"}:
                    return _paid_state(
                        blocked=False,
                        state=ACTIVE if status == "active" else TRIALING,
                        reason="subscription_entitled",
                        group=group,
                        resolution=resolution,
                        subscription=subscription,
                        pending=pending,
                        target_plan=target_plan,
                        action="enter_workspace",
                        message_key=f"subscription_{status}",
                    )
                if resolution.resolved and status in {"canceled", "cancelled"}:
                    return _paid_state(
                        blocked=False,
                        state=CANCELED,
                        reason="canceled_paid_period_active",
                        group=group,
                        resolution=resolution,
                        subscription=subscription,
                        pending=pending,
                        target_plan=target_plan,
                        action="enter_workspace",
                        message_key="subscription_canceled_paid_period",
                    )
            return _paid_state(
                blocked=True,
                state=(
                    PAYMENT_PROCESSING
                    if lifecycle == WorkspaceLifecycleStatus.PROVISIONING.value
                    else INCONSISTENT
                ),
                reason=resolution.reason_code,
                group=group,
                resolution=resolution,
                subscription=subscription,
                pending=pending,
                target_plan=target_plan,
                action="view_subscription",
                message_key="subscription_status_review",
            )
        paid_activation = db.query(
            saas_models.ExistingWorkspacePaidActivation
        ).filter(
            saas_models.ExistingWorkspacePaidActivation.school_group_id == group.id,
            saas_models.ExistingWorkspacePaidActivation.status.in_(
                {
                    "draft",
                    "checkout_ready",
                    "checkout_started",
                    "payment_processing",
                    "manual_review",
                }
            ),
        ).order_by(
            saas_models.ExistingWorkspacePaidActivation.id.desc()
        ).first()
        if (
            lifecycle == WorkspaceLifecycleStatus.PROVISIONING.value
            and grant.reason_code == "missing_promo_grant"
            and not db.query(saas_models.WorkspaceEntitlement.id).filter(
                saas_models.WorkspaceEntitlement.school_group_id == group.id,
                saas_models.WorkspaceEntitlement.status == "active",
            ).first()
            and not db.query(saas_models.TenantProvisioningLink.id).filter(
                saas_models.TenantProvisioningLink.school_group_id == group.id
            ).first()
            and not db.query(saas_models.PromoGrant.id).filter(
                saas_models.PromoGrant.school_group_id == group.id
            ).first()
            and not db.query(saas_models.SaaSDemoWorkspaceProvisioning.id).filter(
                saas_models.SaaSDemoWorkspaceProvisioning.school_group_id == group.id
            ).first()
        ):
            return CommercialAccessState(
                blocked=True,
                kind="subscription" if paid_activation is not None else "promo",
                reason_code="activation_required",
                commercial_state=PAYMENT_PROCESSING,
                workspace_lifecycle=lifecycle,
                recommended_action=(
                    "view_subscription" if paid_activation is not None else "apply_promo"
                ),
                customer_message_key="existing_workspace_activation_required",
            )
        if (
            lifecycle == WorkspaceLifecycleStatus.ACTIVE.value
            and grant.active
            and entitlement.active
            and entitlement.promo_grant_id == grant.grant_id
        ):
            return CommercialAccessState(
                blocked=False,
                kind="promo",
                reason_code="promo_grant_active",
                commercial_state=ACTIVE,
                current_plan_code=grant.plan_code,
                current_plan_name=grant.plan_name,
                current_period_end=grant.effective_to,
                workspace_lifecycle=lifecycle,
                recommended_action="enter_workspace",
                customer_message_key="promo_access_active",
            )
        state = (
            EXPIRED if grant.resolved and grant.status == "expired"
            else SUSPENDED if lifecycle == WorkspaceLifecycleStatus.SUSPENDED.value
            else ARCHIVED if lifecycle == WorkspaceLifecycleStatus.ARCHIVED.value
            else PAYMENT_PROCESSING if lifecycle == WorkspaceLifecycleStatus.PROVISIONING.value
            else INCONSISTENT
        )
        return CommercialAccessState(
            blocked=True,
            kind="promo",
            reason_code=grant.reason_code if grant.resolved else grant.reason_code,
            commercial_state=state,
            current_plan_code=grant.plan_code,
            current_plan_name=grant.plan_name,
            current_period_end=grant.effective_to,
            workspace_lifecycle=lifecycle,
            recommended_action="contact_support",
            customer_message_key=("promo_access_expired" if state == EXPIRED else "promo_access_unavailable"),
        )
    if (
        group.workspace_classification == WorkspaceClassification.CUSTOMER_PAID.value
    ):
        resolution = entitlement_service.resolve_entitlements(db, group.id)
        subscription = (
            db.get(saas_models.PaymentSubscription, resolution.subscription_id)
            if resolution.subscription_id
            else None
        )
        pending, target_plan = _pending_context(db, subscription)
        lifecycle = _clean(group.workspace_lifecycle_status).lower()

        if lifecycle == WorkspaceLifecycleStatus.SUSPENDED.value:
            return _paid_state(
                blocked=True, state=SUSPENDED, reason="workspace_suspended",
                group=group, resolution=resolution, subscription=subscription,
                pending=pending, target_plan=target_plan, action="contact_support",
                message_key="workspace_suspended",
            )
        if lifecycle == WorkspaceLifecycleStatus.ARCHIVED.value:
            return _paid_state(
                blocked=True, state=ARCHIVED, reason="workspace_archived",
                group=group, resolution=resolution, subscription=subscription,
                pending=pending, target_plan=target_plan, action="contact_support",
                message_key="workspace_archived",
            )
        if lifecycle == WorkspaceLifecycleStatus.PROVISIONING.value:
            return _paid_state(
                blocked=True, state=PAYMENT_PROCESSING, reason="workspace_provisioning",
                group=group, resolution=resolution, subscription=subscription,
                pending=pending, target_plan=target_plan, action="view_subscription",
                message_key="workspace_provisioning",
            )
        if lifecycle != WorkspaceLifecycleStatus.ACTIVE.value:
            _log_inconsistent(group.id, "invalid_workspace_lifecycle", resolution=resolution)
            return _paid_state(
                blocked=True, state=INCONSISTENT, reason="invalid_workspace_lifecycle",
                group=group, resolution=resolution, subscription=subscription,
                pending=pending, target_plan=target_plan, action="contact_support",
                message_key="subscription_status_review",
            )

        if subscription is None:
            _log_inconsistent(group.id, "missing_authoritative_subscription", resolution=resolution)
            return _paid_state(
                blocked=True, state=INCONSISTENT, reason=resolution.reason_code,
                group=group, resolution=resolution, action="contact_support",
                message_key="subscription_status_review",
            )

        stale_count = db.query(saas_models.PaymentSubscription).filter(
            saas_models.PaymentSubscription.pending_organization_id
            == subscription.pending_organization_id,
            saas_models.PaymentSubscription.subscription_contract_id
            != subscription.subscription_contract_id,
        ).count()
        if stale_count:
            logger.info(
                "Ignored non-authoritative subscription rows school_group_id=%s count=%s",
                group.id,
                stale_count,
            )

        status = _clean(subscription.status).lower()
        if resolution.resolved and status in {"active", "trialing"}:
            is_pending_upgrade = bool(
                pending is not None
                and pending.change_type == subscription_plan_change_service.UPGRADE
                and pending.status in {"submitted", "payment_pending", "manual_review"}
            )
            state = ACTIVE if status == "active" else TRIALING
            return _paid_state(
                blocked=False, state=state, reason="subscription_entitled",
                group=group, resolution=resolution, subscription=subscription,
                pending=pending, target_plan=target_plan,
                action="view_pending_upgrade" if is_pending_upgrade else "enter_workspace",
                message_key=(
                    "subscription_active_pending_upgrade"
                    if is_pending_upgrade
                    else f"subscription_{state}"
                ),
            )
        if resolution.resolved and status in {"canceled", "cancelled"}:
            return _paid_state(
                blocked=False, state=CANCELED, reason="canceled_paid_period_active",
                group=group, resolution=resolution, subscription=subscription,
                pending=pending, target_plan=target_plan, action="enter_workspace",
                message_key="subscription_canceled_paid_period",
            )
        if status in {"pending", "created"}:
            state, reason, action, message = (
                PAYMENT_PROCESSING,
                "subscription_payment_processing",
                "view_subscription",
                "subscription_payment_processing",
            )
        elif status == "past_due":
            state, reason, action, message = PAST_DUE, "subscription_past_due", "review_payment", "subscription_past_due"
        elif status == "paused":
            state, reason, action, message = PAUSED, "subscription_paused", "view_subscription", "subscription_paused"
        elif status in {"canceled", "cancelled", "expired", "ended"}:
            state, reason, action, message = EXPIRED, "subscription_expired", "renew_subscription", "subscription_expired"
        else:
            state, reason, action, message = INCONSISTENT, resolution.reason_code, "contact_support", "subscription_status_review"
            _log_inconsistent(group.id, reason, resolution=resolution)
        return _paid_state(
            blocked=True, state=state, reason=reason,
            group=group, resolution=resolution, subscription=subscription,
            pending=pending, target_plan=target_plan, action=action,
            message_key=message,
        )
    if (
        group.workspace_classification
        == WorkspaceClassification.INTERNAL_SANDBOX.value
    ):
        lifecycle = _clean(group.workspace_lifecycle_status).lower()
        if lifecycle == WorkspaceLifecycleStatus.ACTIVE.value:
            return CommercialAccessState(
                blocked=False,
                kind="internal_sandbox",
                reason_code="internal_sandbox_active",
                commercial_state=ACTIVE,
                workspace_lifecycle=lifecycle,
                recommended_action="enter_workspace",
                customer_message_key="internal_sandbox_active",
            )
        state = (
            SUSPENDED
            if lifecycle == WorkspaceLifecycleStatus.SUSPENDED.value
            else ARCHIVED
            if lifecycle == WorkspaceLifecycleStatus.ARCHIVED.value
            else PAYMENT_PROCESSING
            if lifecycle == WorkspaceLifecycleStatus.PROVISIONING.value
            else INCONSISTENT
        )
        return CommercialAccessState(
            blocked=True,
            kind="internal_sandbox",
            reason_code="internal_sandbox_not_active",
            commercial_state=state,
            workspace_lifecycle=lifecycle,
            recommended_action="contact_support",
            customer_message_key="internal_sandbox_not_active",
        )
    _log_inconsistent(group.id, "unsupported_workspace_classification")
    return CommercialAccessState(
        blocked=True,
        kind="",
        reason_code="unsupported_workspace_classification",
        commercial_state=INCONSISTENT,
        workspace_lifecycle=_clean(group.workspace_lifecycle_status).lower(),
        recommended_action="contact_support",
        customer_message_key="subscription_status_review",
    )


def resolve_customer_access(db: Session, account) -> CommercialAccessState:
    resolution = entitlement_service.resolve_customer_entitlements(db, account)
    if resolution.school_group_id:
        return resolve_workspace_access(db, resolution.school_group_id)
    group_ids = {
        int(group_id)
        for (group_id,) in db.query(saas_models.SaaSAccountUserLink.school_group_id).filter(
            saas_models.SaaSAccountUserLink.saas_account_id == getattr(account, "id", None)
        ).all()
        if group_id
    }
    selected_group_id = int(getattr(account, "_selected_school_group_id", 0) or 0)
    if selected_group_id in group_ids:
        return resolve_workspace_access(db, selected_group_id)
    if len(group_ids) == 1:
        return resolve_workspace_access(db, next(iter(group_ids)))
    return CommercialAccessState(
        blocked=True,
        kind="subscription",
        reason_code=resolution.reason_code,
        commercial_state=INCONSISTENT,
        recommended_action="contact_support",
        customer_message_key="subscription_status_review",
    )
