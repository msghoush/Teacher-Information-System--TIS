from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from saas import commercial_authority_service, models, promo_grant_service


@dataclass(frozen=True)
class PromoCapacityView:
    key: str
    label: str
    used: int
    limit: int
    remaining: int


@dataclass(frozen=True)
class PromoCommercialPortalView:
    commercial_source: str
    access_label: str
    plan_code: str
    plan_name: str
    status_label: str
    status_tone: str
    status_message: str
    effective_from_label: str
    effective_to_label: str
    recovery_until_label: str
    masked_promo_reference: str
    access_active: bool
    capacity_available: bool
    capacities: tuple[PromoCapacityView, ...]
    continuation_available: bool
    continuation_url: str


def _date_label(value: date | datetime | None) -> str:
    if not isinstance(value, (date, datetime)):
        return "Not available"
    return value.strftime("%d %b %Y")


def resolve_portal_authority(db: Session, school_group_id: int):
    return commercial_authority_service.resolve_commercial_authority(
        db,
        school_group_id,
    )


def _promo_reference(db: Session, promo_resolution) -> str:
    if not promo_resolution.grant_id:
        return ""
    grant = db.get(models.PromoGrant, int(promo_resolution.grant_id))
    if grant is None or int(grant.school_group_id) != int(
        promo_resolution.school_group_id
    ):
        return ""
    redemption = db.get(models.PromoRedemption, int(grant.promo_redemption_id))
    if redemption is None or int(redemption.school_group_id) != int(grant.school_group_id):
        return ""
    return str(redemption.masked_promo_reference or "").strip()


def build_promo_commercial_portal(
    db: Session,
    school_group_id: int,
    *,
    authority=None,
    continuation_available: bool = False,
    continuation_url: str = "",
) -> PromoCommercialPortalView:
    authority = authority or resolve_portal_authority(db, school_group_id)
    if authority.source != commercial_authority_service.PROMO_GRANT:
        raise ValueError(
            "Promotional commercial access is not available for this workspace."
        )

    promo = promo_grant_service.resolve_promo_grant(db, school_group_id)
    active = bool(authority.access_allowed and authority.resolved and promo.active)
    recovery = bool(promo.recovery_active)
    expired = bool(promo.resolved and promo.status == "expired")
    if active:
        status_label = "Active"
        status_tone = "active"
        status_message = "Your promotional access is active."
    elif recovery:
        status_label = "Recovery Period"
        status_tone = "recovery"
        status_message = (
            "Your promotional access period has ended. Operational access remains "
            "blocked while you review continuation options for this existing workspace."
        )
    elif expired:
        status_label = "Expired"
        status_tone = "expired"
        status_message = (
            "Your promotional access period has ended. "
            "Contact the TIS team for assistance."
        )
    else:
        status_label = "Access unavailable"
        status_tone = "unavailable"
        status_message = (
            "Promotional access information is currently unavailable. "
            "Contact the TIS team for assistance."
        )

    capacity_available = bool(
        active
        and authority.limits.branches is not None
        and authority.limits.staff_users is not None
        and authority.limits.teachers is not None
    )
    capacities = ()
    if capacity_available:
        capacities = tuple(
            PromoCapacityView(
                key=key,
                label=label,
                used=authority.usage.value(key),
                limit=int(authority.limits.value(key)),
                remaining=authority.remaining.value(key),
            )
            for key, label in (
                ("branches", "Branches"),
                ("staff_users", "System Users"),
                ("teachers", "Teachers"),
            )
        )

    return PromoCommercialPortalView(
        commercial_source="promo",
        access_label="Promotional Access",
        plan_code=str(authority.plan_code or promo.plan_code or ""),
        plan_name=str(authority.plan_name or promo.plan_name or "Not available"),
        status_label=status_label,
        status_tone=status_tone,
        status_message=status_message,
        effective_from_label=_date_label(promo.effective_from or authority.effective_from),
        effective_to_label=_date_label(promo.effective_to or authority.effective_to),
        recovery_until_label=(
            _date_label(promo.recovery_until) if recovery else ""
        ),
        masked_promo_reference=_promo_reference(db, promo),
        access_active=active,
        capacity_available=capacity_available,
        capacities=capacities,
        continuation_available=bool(continuation_available),
        continuation_url=str(continuation_url or ""),
    )
