from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from saas import entitlement_service, models, subscription_change_service, subscription_plan_change_service


ACTIVE = "active"
PROCESSING = "processing"
SCHEDULED_DOWNGRADE = "scheduled_downgrade"
SCHEDULED_QUANTITY_CHANGE = "scheduled_quantity_change"
SCHEDULED_CANCELLATION = "scheduled_cancellation"
CANCELED = "canceled"
EXPIRED = "expired"
PAYMENT_ISSUE = "payment_issue"
UNAVAILABLE = "unavailable"

CANCELLATION_REQUEST = "subscription_cancellation"
CANCELLATION_REVERSAL = "subscription_cancellation_reversal"


@dataclass(frozen=True)
class SubscriptionAllowedActions:
    can_upgrade: bool = False
    can_downgrade: bool = False
    can_increase_quantity: bool = False
    can_decrease_quantity: bool = False
    can_cancel: bool = False
    can_undo_cancellation: bool = False


@dataclass(frozen=True)
class SubscriptionLifecycle:
    resolution_status: str
    reason_code: str
    raw_subscription_status: str
    lifecycle_status: str
    display_status: str
    display_badge: str
    display_message: str
    current_plan: str
    current_plan_code: str
    billing_interval: str
    current_quantity: int | None
    active_branch_count: int
    current_period_start: datetime | None
    current_period_end: datetime | None
    next_billing_date: datetime | None
    pending_request_uuid: str | None
    pending_change_type: str | None
    pending_change_status: str | None
    pending_target_plan: str | None
    pending_target_plan_code: str | None
    pending_target_quantity: int | None
    pending_effective_date: datetime | None
    cancellation_scheduled: bool
    cancellation_effective_date: datetime | None
    timezone_name: str
    allowed_actions: SubscriptionAllowedActions


def _clean(value) -> str:
    return str(value or "").strip()


def _workspace_timezone(db: Session, subscription) -> str:
    if subscription is None:
        return "UTC"
    value = db.query(models.PendingOrganization.timezone).filter(
        models.PendingOrganization.id == subscription.pending_organization_id
    ).scalar()
    return _clean(value) or "UTC"


def format_date(value, timezone_name: str, date_format: str = "%d %B %Y") -> str:
    if not isinstance(value, (date, datetime)):
        return ""
    observed = value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            observed = value.replace(tzinfo=timezone.utc)
        try:
            observed = observed.astimezone(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            observed = observed.astimezone(timezone.utc)
    return observed.strftime(date_format)


def _unavailable(reason_code: str, *, raw_status: str = "", subscription=None) -> SubscriptionLifecycle:
    missing = reason_code in {
        "missing_customer_subscription",
        "missing_operational_subscription_link",
        "missing_confirmed_subscription",
    }
    return SubscriptionLifecycle(
        resolution_status=entitlement_service.MANUAL_REVIEW,
        reason_code=reason_code,
        raw_subscription_status=raw_status,
        lifecycle_status=UNAVAILABLE,
        display_status="Missing Subscription" if missing else "Status Unavailable",
        display_badge="attention",
        display_message=(
            "Subscription information is not available."
            if missing
            else "Subscription information is currently unavailable. Please contact TIS Support."
        ),
        current_plan="Not Available",
        current_plan_code="",
        billing_interval="",
        current_quantity=getattr(subscription, "quantity", None),
        active_branch_count=0,
        current_period_start=getattr(subscription, "current_period_start", None),
        current_period_end=getattr(subscription, "current_period_end", None),
        next_billing_date=getattr(subscription, "next_billed_at", None),
        pending_request_uuid=None,
        pending_change_type=None,
        pending_change_status=None,
        pending_target_plan=None,
        pending_target_plan_code=None,
        pending_target_quantity=None,
        pending_effective_date=None,
        cancellation_scheduled=False,
        cancellation_effective_date=None,
        timezone_name="UTC",
        allowed_actions=SubscriptionAllowedActions(),
    )


def resolve_subscription_lifecycle(
    db: Session,
    account,
    *,
    resolution: entitlement_service.EntitlementResolution | None = None,
) -> SubscriptionLifecycle:
    resolution = resolution or entitlement_service.resolve_customer_entitlements(db, account)
    if not resolution.subscription_id:
        return _unavailable(resolution.reason_code)
    subscription = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.id == resolution.subscription_id
    ).one_or_none()
    if subscription is None:
        return _unavailable("missing_payment_subscription")
    raw_status = _clean(subscription.status).lower()
    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == subscription.plan_id
    ).one_or_none()
    if plan is None:
        return _unavailable("missing_subscription_plan", raw_status=raw_status, subscription=subscription)
    pending = subscription_change_service.get_pending_change(db, subscription.id)
    timezone_name = _workspace_timezone(db, subscription)
    pending_plan = None
    if pending is not None and pending.target_plan_id:
        pending_plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == pending.target_plan_id
        ).one_or_none()

    cancellation_scheduled = bool(
        pending is not None
        and pending.change_type == CANCELLATION_REQUEST
        and pending.status == "scheduled"
        and subscription.cancel_at_period_end
    )
    lifecycle_status = UNAVAILABLE
    display_status = "Status Unavailable"
    display_badge = "attention"
    display_message = "Subscription information is currently unavailable. Please contact TIS Support."

    effective_date = getattr(pending, "effective_at", None)
    renewal_date = subscription.next_billed_at or subscription.current_period_end
    if raw_status == "expired":
        lifecycle_status = EXPIRED
        display_status = "Expired"
        display_badge = "muted"
        display_message = "This subscription has expired."
    elif raw_status in {"canceled", "cancelled"}:
        lifecycle_status = CANCELED
        display_status = "Canceled"
        display_badge = "muted"
        display_message = "This subscription has ended."
    elif raw_status == "past_due":
        lifecycle_status = PAYMENT_ISSUE
        display_status = "Payment Issue"
        display_badge = "attention"
        display_message = "Billing requires attention before subscription changes can continue."
    elif raw_status == "paused":
        lifecycle_status = PAYMENT_ISSUE
        display_status = "Paused"
        display_badge = "attention"
        display_message = "Subscription access is paused."
    elif pending is not None and pending.status in {"submitted", "payment_pending", "manual_review"}:
        lifecycle_status = PROCESSING if pending.status != "manual_review" else UNAVAILABLE
        display_status = "Processing" if pending.status != "manual_review" else "Status Unavailable"
        display_badge = "info" if pending.status != "manual_review" else "attention"
        display_message = (
            "Your request is being confirmed by the billing provider."
            if pending.status != "manual_review"
            else "Subscription information is currently unavailable. Please contact TIS Support."
        )
    elif cancellation_scheduled:
        lifecycle_status = SCHEDULED_CANCELLATION
        display_status = "Cancellation Scheduled"
        display_badge = "attention"
        label = format_date(effective_date, timezone_name)
        display_message = (
            f"Your subscription is scheduled to end on {label}."
            if label else "Your subscription is scheduled to end at the close of the paid period."
        )
    elif pending is not None and pending.status == "scheduled" and pending.change_type == subscription_plan_change_service.DOWNGRADE:
        lifecycle_status = SCHEDULED_DOWNGRADE
        display_status = "Scheduled Downgrade"
        display_badge = "info"
        label = format_date(effective_date, timezone_name)
        target = _clean(getattr(pending_plan, "plan_name", "")) or "the selected plan"
        display_message = (
            f"Your downgrade to {target} will take effect on {label}."
            if label else f"Your downgrade to {target} is scheduled for the next billing period."
        )
    elif pending is not None and pending.status == "scheduled" and pending.change_type == subscription_change_service.REDUCTION:
        lifecycle_status = SCHEDULED_QUANTITY_CHANGE
        display_status = "Scheduled Branch Change"
        display_badge = "info"
        label = format_date(effective_date, timezone_name)
        display_message = (
            f"Your paid branch quantity will change on {label}."
            if label else "Your paid branch quantity will change at the next billing period."
        )
    elif subscription.cancel_at_period_end:
        display_message = "Subscription information is currently unavailable. Please contact TIS Support."
    elif raw_status in {"active", "trialing"} and resolution.resolved and pending is None:
        lifecycle_status = ACTIVE
        display_status = "Active" if raw_status == "active" else "Trial"
        display_badge = "healthy" if raw_status == "active" else "info"
        label = format_date(renewal_date, timezone_name)
        display_message = (
            f"Your subscription renews on {label}."
            if label else "Your subscription is active."
        )

    authorized = False
    if raw_status in {"active", "trialing"} and resolution.resolved:
        try:
            subscription_change_service.resolve_change_context(db, account)
            authorized = True
        except subscription_change_service.SubscriptionChangeError:
            authorized = False
    no_pending = pending is None
    plan_rank = subscription_plan_change_service.PLAN_ORDER.get(_clean(plan.plan_code), 0)
    max_rank = max(subscription_plan_change_service.PLAN_ORDER.values(), default=0)
    active_actions = authorized and lifecycle_status == ACTIVE and raw_status == "active" and no_pending
    actions = SubscriptionAllowedActions(
        can_upgrade=bool(active_actions and plan_rank < max_rank),
        can_downgrade=bool(active_actions and plan_rank > min(subscription_plan_change_service.PLAN_ORDER.values(), default=0)),
        can_increase_quantity=bool(active_actions),
        can_decrease_quantity=bool(
            active_actions
            and int(subscription.quantity or 0) > max(int(resolution.active_branch_count or 0), 1)
        ),
        can_cancel=bool(active_actions),
        can_undo_cancellation=bool(authorized and lifecycle_status == SCHEDULED_CANCELLATION),
    )
    return SubscriptionLifecycle(
        resolution_status=resolution.resolution_status,
        reason_code=resolution.reason_code,
        raw_subscription_status=raw_status,
        lifecycle_status=lifecycle_status,
        display_status=display_status,
        display_badge=display_badge,
        display_message=display_message,
        current_plan=_clean(plan.plan_name),
        current_plan_code=_clean(plan.plan_code),
        billing_interval=_clean(subscription.billing_interval).lower(),
        current_quantity=int(subscription.quantity or 0),
        active_branch_count=int(resolution.active_branch_count or 0),
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        next_billing_date=subscription.next_billed_at,
        pending_request_uuid=getattr(pending, "request_uuid", None),
        pending_change_type=getattr(pending, "change_type", None),
        pending_change_status=getattr(pending, "status", None),
        pending_target_plan=_clean(getattr(pending_plan, "plan_name", "")) or None,
        pending_target_plan_code=_clean(getattr(pending_plan, "plan_code", "")) or None,
        pending_target_quantity=getattr(pending, "requested_quantity", None),
        pending_effective_date=effective_date,
        cancellation_scheduled=cancellation_scheduled,
        cancellation_effective_date=effective_date if cancellation_scheduled else None,
        timezone_name=timezone_name,
        allowed_actions=actions,
    )
