from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from saas import entitlement_service


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
    feature_groups: tuple[dict, ...]
    plan_comparison: tuple[dict, ...]


def _date_label(value) -> str:
    if not isinstance(value, (date, datetime)):
        return "Not Available"
    return value.strftime("%B %d, %Y")


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
        feature_groups=_feature_groups(db, resolution),
        plan_comparison=_plan_comparison(db, resolution.plan_code),
    )
