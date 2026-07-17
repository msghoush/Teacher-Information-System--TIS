from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from saas import entitlement_service, subscription_change_service, subscription_plan_change_service


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
    status_label: str
    health_label: str
    health_tone: str
    plan_name: str
    plan_code: str
    billing_interval_label: str
    paid_branch_quantity: int | None
    active_branch_count: int
    remaining_paid_capacity: int | None
    is_at_capacity: bool
    is_over_capacity: bool
    next_billing_date_label: str
    current_recurring_total_label: str
    pending_change: dict | None
    can_manage_branch_capacity: bool
    can_manage_plan: bool
    feature_groups: tuple[dict, ...]
    plan_comparison: tuple[dict, ...]


def _date_label(value) -> str:
    if not isinstance(value, (date, datetime)):
        return "Not Available"
    return value.strftime("%B %d, %Y")


def _money_label(amount_minor, currency_code: str) -> str:
    if amount_minor is None:
        return "Not Available"
    currency = str(currency_code or "USD").upper()
    symbols = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}
    return f"{symbols.get(currency, currency + ' ')}{int(amount_minor) / 100:,.2f}"


def _status_display(resolution) -> tuple[str, str, str]:
    observed_status = str(resolution.subscription_status or "").strip().lower()
    if resolution.resolved:
        if observed_status == "trialing":
            return "Trial", "Trial subscription is active", "info"
        return "Active", "Subscription is active", "healthy"
    if observed_status in {"past_due"}:
        return "Past Due", "Billing requires attention", "attention"
    if observed_status == "paused":
        return "Paused", "Subscription access is paused", "attention"
    if observed_status in {"canceled", "cancelled"}:
        return "Canceled", "Subscription is no longer active", "muted"
    if resolution.reason_code in {
        "missing_customer_subscription",
        "missing_operational_subscription_link",
        "missing_confirmed_subscription",
    }:
        return "Missing Subscription", "Subscription information is not available", "attention"
    return "Manual Review", "Subscription information is being reviewed", "attention"


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
    status_label, health_label, health_tone = _status_display(resolution)
    interval = str(resolution.billing_interval or "").strip().lower()
    interval_label = {"monthly": "Monthly", "annual": "Annual"}.get(interval, "Not Available")
    pending = None
    if resolution.subscription_id:
        row = subscription_change_service.get_pending_change(db, resolution.subscription_id)
        if row:
            is_plan_change = row.change_type in subscription_plan_change_service.PLAN_CHANGE_TYPES
            pending = {
                "request_uuid": row.request_uuid,
                "change_type": row.change_type,
                "status": row.status,
                "status_label": {
                    "previewed": "Awaiting confirmation",
                    "payment_pending": "Upgrade payment confirmation pending" if is_plan_change else "Payment confirmation pending",
                    "scheduled": "Plan downgrade scheduled" if is_plan_change else "Reduction scheduled",
                    "manual_review": "Manual review required",
                }.get(row.status, "Change in progress"),
                "is_plan_change": is_plan_change,
                "target_plan_name": (
                    db.query(subscription_plan_change_service.models.SubscriptionPlan.plan_name)
                    .filter(subscription_plan_change_service.models.SubscriptionPlan.id == row.target_plan_id)
                    .scalar()
                    if is_plan_change else ""
                ),
                "requested_quantity": row.requested_quantity,
                "effective_date_label": _date_label(row.effective_at),
                "expected_total_label": _money_label(row.next_renewal_total_minor, row.currency_code),
                "can_cancel": row.change_type == subscription_change_service.REDUCTION and row.status == "scheduled",
            }
    try:
        subscription_change_service.resolve_change_context(db, account)
        can_manage_branch_capacity = True
    except subscription_change_service.SubscriptionChangeError:
        can_manage_branch_capacity = False
    can_manage_branch_capacity = can_manage_branch_capacity and pending is None
    can_manage_plan = can_manage_branch_capacity and pending is None
    return SubscriptionPortalView(
        resolution_status=resolution.resolution_status,
        status_label=status_label,
        health_label=health_label,
        health_tone=health_tone,
        plan_name=resolution.plan_name or "Not Available",
        plan_code=resolution.plan_code,
        billing_interval_label=interval_label,
        paid_branch_quantity=resolution.paid_branch_quantity,
        active_branch_count=resolution.active_branch_count,
        remaining_paid_capacity=resolution.remaining_paid_capacity,
        is_at_capacity=resolution.is_at_capacity,
        is_over_capacity=resolution.is_over_capacity,
        next_billing_date_label=_date_label(resolution.next_billed_at),
        current_recurring_total_label=_money_label(resolution.recurring_amount_minor, resolution.currency_code),
        pending_change=pending,
        can_manage_branch_capacity=can_manage_branch_capacity,
        can_manage_plan=can_manage_plan,
        feature_groups=_feature_groups(db, resolution),
        plan_comparison=_plan_comparison(db, resolution.plan_code),
    )
