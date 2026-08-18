from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from saas import commercial_access_service, promo_grant_service


@dataclass(frozen=True)
class CommercialBadgeView:
    source: str
    access_label: str
    status_label: str
    plan_name: str
    icon: str
    source_tone: str
    status_tone: str
    plan_tone: str
    aria_label: str


def _clean(value) -> str:
    return str(value or "").strip()


def _plan_tone(plan_code: str, plan_name: str) -> str:
    identity = f"{_clean(plan_code)} {_clean(plan_name)}".lower()
    if "enterprise" in identity:
        return "enterprise"
    if "professional" in identity:
        return "professional"
    if "starter" in identity or "core" in identity:
        return "starter"
    return "standard"


def build_commercial_badge(
    db: Session,
    school_group_id: int,
) -> CommercialBadgeView | None:
    access = commercial_access_service.resolve_workspace_access(db, school_group_id)
    promo = (
        promo_grant_service.resolve_promo_grant(db, school_group_id)
        if access.kind == "promo"
        else None
    )
    return build_badge_from_access(access, promo_resolution=promo)


def build_badge_from_access(
    access,
    *,
    promo_resolution=None,
) -> CommercialBadgeView | None:
    plan_name = _clean(access.current_plan_name)
    plan_code = _clean(access.current_plan_code)
    state = _clean(access.commercial_state).lower()

    if access.kind == "promo":
        promo = promo_resolution
        if promo is None or not promo.resolved:
            return None
        plan_name = plan_name or _clean(promo.plan_name)
        plan_code = plan_code or _clean(promo.plan_code)
        if promo.recovery_active:
            status_label, status_tone = "Recovery Period", "warning"
        elif state == commercial_access_service.ACTIVE:
            status_label, status_tone = "Active", "active"
        elif state == commercial_access_service.EXPIRED:
            status_label, status_tone = "Expired", "warning"
        else:
            status_label, status_tone = "Review Required", "review"
        source, label, icon, source_tone = "promo", "Promotional Access", "sparkles", "promo"
    elif access.kind == "demo":
        status_label = "Active" if access.allowed_access else "Expired" if state == commercial_access_service.EXPIRED else "Review Required"
        status_tone = "active" if access.allowed_access else "warning" if state == commercial_access_service.EXPIRED else "review"
        source, label, icon, source_tone = "demo", "Demo Access", "eye", "demo"
    elif access.kind == "subscription":
        paid_labels = {
            commercial_access_service.ACTIVE: ("Active", "active"),
            commercial_access_service.TRIALING: ("Trial", "info"),
            commercial_access_service.PAYMENT_PROCESSING: ("Payment Processing", "info"),
            commercial_access_service.PAST_DUE: ("Payment Issue", "warning"),
            commercial_access_service.PAUSED: ("Paused", "warning"),
            commercial_access_service.CANCELED: ("Cancellation Scheduled", "info"),
            commercial_access_service.EXPIRED: ("Expired", "warning"),
        }
        status_label, status_tone = paid_labels.get(state, ("Review Required", "review"))
        source, label, icon, source_tone = "paid", "Subscription Active", "shield", "paid"
    else:
        return None

    aria = f"{label}, {status_label}"
    if plan_name:
        aria += f", {plan_name} plan"
    return CommercialBadgeView(
        source=source,
        access_label=label,
        status_label=status_label,
        plan_name=plan_name,
        icon=icon,
        source_tone=source_tone,
        status_tone=status_tone,
        plan_tone=_plan_tone(plan_code, plan_name),
        aria_label=aria,
    )
