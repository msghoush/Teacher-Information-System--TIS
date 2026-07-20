from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from saas import entitlement_service, subscription_change_service, subscription_lifecycle_service, subscription_plan_change_service


CATEGORY_LABELS = {
    "ai": "AI",
    "reporting": "Reporting",
    "planning": "Planning",
    "administration": "Administration",
    "communication": "Communication",
    "analytics": "Analytics",
}

@dataclass(frozen=True)
class SubscriptionPortalView:
    resolution_status: str
    lifecycle_status: str
    status_label: str
    status_message: str
    health_label: str
    health_tone: str
    plan_name: str
    plan_code: str
    billing_interval_label: str
    billing_cadence_label: str
    paid_branch_quantity: int | None
    active_branch_count: int
    remaining_paid_capacity: int | None
    is_at_capacity: bool
    is_over_capacity: bool
    next_billing_date_label: str
    current_period_end_label: str
    current_recurring_total_label: str
    overview_date_label: str
    overview_date_value: str
    pending_change: dict | None
    can_manage_branch_capacity: bool
    can_manage_plan: bool
    can_increase_quantity: bool
    can_decrease_quantity: bool
    can_upgrade: bool
    can_downgrade: bool
    can_cancel: bool
    can_undo_cancellation: bool
    cancellation_effective_date_label: str
    feature_groups: tuple[dict, ...]
    plan_comparison: tuple[dict, ...]


def _date_label(value, timezone_name: str = "UTC") -> str:
    if not isinstance(value, (date, datetime)):
        return "Not Available"
    return subscription_lifecycle_service.format_date(
        value,
        timezone_name,
        "%B %d, %Y",
    ) or "Not Available"


def _money_label(amount_minor, currency_code: str) -> str:
    if amount_minor is None:
        return "Not Available"
    currency = str(currency_code or "USD").upper()
    symbols = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}
    return f"{symbols.get(currency, currency + ' ')}{int(amount_minor) / 100:,.2f}"


def _feature_groups(db: Session, resolution) -> tuple[dict, ...]:
    grouped = {}
    for definition in entitlement_service.list_entitlement_catalog(db):
        if definition.key == "quota.active_branches":
            continue
        value = resolution.entitlements.get(definition.key) if resolution.resolved else None
        category_key = definition.category.lower()
        grouped.setdefault(category_key, []).append({
            "key": definition.key,
            "name": definition.display_name,
            "description": definition.description,
            "included": bool(value and value.granted),
        })
    return tuple(
        {
            "key": category_key,
            "label": CATEGORY_LABELS.get(category_key, category_key.replace("_", " ").title()),
            "features": tuple(features),
        }
        for category_key, features in grouped.items()
    )


def _plan_comparison(db: Session, current_plan_code: str) -> tuple[dict, ...]:
    profiles = entitlement_service.list_plan_entitlement_profiles(db)
    return tuple(
        {
            "plan_code": profile.plan_code,
            "plan_name": profile.plan_name,
            "is_current": profile.plan_code == current_plan_code,
            "direction": (
                "upgrade" if subscription_plan_change_service.PLAN_ORDER.get(profile.plan_code, 0) > subscription_plan_change_service.PLAN_ORDER.get(current_plan_code, 0)
                else "downgrade"
            ),
            "included_features": tuple(
                value.display_name
                for value in profile.entitlements.values()
                if value.granted and value.key != "quota.active_branches"
            ),
        }
        for profile in profiles
    )


def build_subscription_portal(db: Session, account) -> SubscriptionPortalView:
    resolution = entitlement_service.resolve_customer_entitlements(db, account)
    lifecycle = subscription_lifecycle_service.resolve_subscription_lifecycle(
        db, account, resolution=resolution
    )
    interval = str(lifecycle.billing_interval or resolution.billing_interval or "").strip().lower()
    interval_label = {"monthly": "Monthly", "annual": "Annual"}.get(interval, "Not Available")
    cadence_label = {"monthly": "month", "annual": "year"}.get(interval, "billing period")
    pending = None
    if resolution.subscription_id and lifecycle.pending_request_uuid:
        row = subscription_change_service.get_pending_change(db, resolution.subscription_id)
        if row:
            is_plan_change = row.change_type in subscription_plan_change_service.PLAN_CHANGE_TYPES
            is_cancellation = row.change_type == subscription_lifecycle_service.CANCELLATION_REQUEST
            is_reversal = row.change_type == subscription_lifecycle_service.CANCELLATION_REVERSAL
            pending = {
                "request_uuid": row.request_uuid,
                "change_type": row.change_type,
                "status": row.status,
                "status_label": {
                    "previewed": "Awaiting confirmation",
                    "payment_pending": "Upgrade payment confirmation pending" if is_plan_change else "Payment confirmation pending",
                    "scheduled": (
                        "Cancellation scheduled" if is_cancellation
                        else "Plan downgrade scheduled" if is_plan_change
                        else "Reduction scheduled"
                    ),
                    "manual_review": "Manual review required",
                    "submitted": "Awaiting provider confirmation",
                }.get(row.status, "Change in progress"),
                "is_plan_change": is_plan_change,
                "is_cancellation": is_cancellation,
                "is_cancellation_reversal": is_reversal,
                "title": (
                    "Scheduled Cancellation" if is_cancellation and row.status == "scheduled"
                    else "Cancellation Reversal" if is_reversal
                    else "Scheduled Plan Change" if is_plan_change and row.status == "scheduled"
                    else "Pending Subscription Change" if is_plan_change or is_cancellation
                    else "Pending branch-capacity change"
                ),
                "target_plan_name": (
                    db.query(subscription_plan_change_service.models.SubscriptionPlan.plan_name)
                    .filter(subscription_plan_change_service.models.SubscriptionPlan.id == row.target_plan_id)
                    .scalar()
                    if is_plan_change else ""
                ),
                "target_plan_code": (
                    db.query(subscription_plan_change_service.models.SubscriptionPlan.plan_code)
                    .filter(subscription_plan_change_service.models.SubscriptionPlan.id == row.target_plan_id)
                    .scalar()
                    if is_plan_change else ""
                ),
                "can_manage_schedule": bool(is_plan_change and row.status == "scheduled"),
                "requested_quantity": row.requested_quantity,
                "effective_date_label": _date_label(row.effective_at, lifecycle.timezone_name),
                "expected_total_label": _money_label(row.next_renewal_total_minor, row.currency_code),
                "can_cancel": row.change_type == subscription_change_service.REDUCTION and row.status == "scheduled",
            }
    actions = lifecycle.allowed_actions
    can_manage_branch_capacity = actions.can_increase_quantity or actions.can_decrease_quantity
    can_manage_plan = actions.can_upgrade or actions.can_downgrade
    next_billing_date_label = _date_label(lifecycle.next_billing_date, lifecycle.timezone_name)
    current_period_end_label = _date_label(
        lifecycle.current_period_end or lifecycle.next_billing_date,
        lifecycle.timezone_name,
    )
    if pending and pending["effective_date_label"] != "Not Available":
        overview_date_label = "Effective Date"
        overview_date_value = pending["effective_date_label"]
    elif next_billing_date_label != "Not Available":
        overview_date_label = "Next Renewal"
        overview_date_value = next_billing_date_label
    else:
        overview_date_label = "Current Period End"
        overview_date_value = current_period_end_label
    return SubscriptionPortalView(
        resolution_status=resolution.resolution_status,
        lifecycle_status=lifecycle.lifecycle_status,
        status_label=lifecycle.display_status,
        status_message=lifecycle.display_message,
        health_label=lifecycle.display_status,
        health_tone=lifecycle.display_badge,
        plan_name=lifecycle.current_plan or resolution.plan_name or "Not Available",
        plan_code=lifecycle.current_plan_code or resolution.plan_code,
        billing_interval_label=interval_label,
        billing_cadence_label=cadence_label,
        paid_branch_quantity=resolution.paid_branch_quantity,
        active_branch_count=resolution.active_branch_count,
        remaining_paid_capacity=resolution.remaining_paid_capacity,
        is_at_capacity=resolution.is_at_capacity,
        is_over_capacity=resolution.is_over_capacity,
        next_billing_date_label=next_billing_date_label,
        current_period_end_label=current_period_end_label,
        current_recurring_total_label=_money_label(resolution.recurring_amount_minor, resolution.currency_code),
        overview_date_label=overview_date_label,
        overview_date_value=overview_date_value,
        pending_change=pending,
        can_manage_branch_capacity=can_manage_branch_capacity,
        can_manage_plan=can_manage_plan,
        can_increase_quantity=actions.can_increase_quantity,
        can_decrease_quantity=actions.can_decrease_quantity,
        can_upgrade=actions.can_upgrade,
        can_downgrade=actions.can_downgrade,
        can_cancel=actions.can_cancel,
        can_undo_cancellation=actions.can_undo_cancellation,
        cancellation_effective_date_label=_date_label(
            lifecycle.cancellation_effective_date,
            lifecycle.timezone_name,
        ),
        feature_groups=_feature_groups(db, resolution),
        plan_comparison=_plan_comparison(db, resolution.plan_code),
    )
