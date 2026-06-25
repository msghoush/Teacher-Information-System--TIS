from dataclasses import dataclass

from sqlalchemy.orm import Session

from saas import currency_service, models


@dataclass(frozen=True)
class PlanIntervalView:
    billing_interval: str
    base_amount_minor: int
    display_amount_minor: int
    display_formatted: str
    base_currency_code: str
    display_currency_code: str
    annual_savings_amount_minor: int
    annual_savings_percent: int
    plan_version: int
    is_founding_offer: bool


@dataclass(frozen=True)
class PlanView:
    plan: object
    monthly: PlanIntervalView
    annual: PlanIntervalView


def _active_price_query(db: Session, plan_id: int, billing_interval: str):
    return db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == plan_id,
        models.SubscriptionPlanPrice.billing_interval == billing_interval,
        models.SubscriptionPlanPrice.currency_code == "USD",
        models.SubscriptionPlanPrice.is_active == True,
    )


def get_active_public_plans(db: Session):
    return db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.is_active == True,
        models.SubscriptionPlan.is_public == True,
    ).order_by(models.SubscriptionPlan.sort_order.asc(), models.SubscriptionPlan.id.asc()).all()


def _build_interval_view(
    *,
    price_row,
    display_currency,
    annual_savings_amount_minor: int = 0,
    annual_savings_percent: int = 0,
) -> PlanIntervalView:
    display_amount_minor = currency_service.convert_minor_from_usd(
        int(price_row.amount_minor or 0),
        display_currency,
    )
    return PlanIntervalView(
        billing_interval=price_row.billing_interval,
        base_amount_minor=int(price_row.amount_minor or 0),
        display_amount_minor=display_amount_minor,
        display_formatted=currency_service.format_minor_amount(display_amount_minor, display_currency),
        base_currency_code=str(price_row.currency_code or "USD"),
        display_currency_code=display_currency.currency_code,
        annual_savings_amount_minor=int(annual_savings_amount_minor or 0),
        annual_savings_percent=int(annual_savings_percent or 0),
        plan_version=int(price_row.plan_version or 1),
        is_founding_offer=bool(price_row.is_founding_offer),
    )


def _compute_annual_savings(monthly_price_row, annual_price_row) -> tuple[int, int]:
    monthly_total = int(monthly_price_row.amount_minor or 0) * 12
    annual_total = int(annual_price_row.amount_minor or 0)
    savings = max(0, monthly_total - annual_total)
    percent = int(round((savings / monthly_total) * 100)) if monthly_total else 0
    return savings, percent


def build_plan_catalog(db: Session, *, country_code: str = "") -> list[PlanView]:
    display_currency = currency_service.resolve_display_currency(db, country_code=country_code)
    plan_views = []
    for plan in get_active_public_plans(db):
        monthly_price = _active_price_query(db, plan.id, "monthly").order_by(
            models.SubscriptionPlanPrice.plan_version.desc(),
            models.SubscriptionPlanPrice.id.desc(),
        ).first()
        annual_price = _active_price_query(db, plan.id, "annual").order_by(
            models.SubscriptionPlanPrice.plan_version.desc(),
            models.SubscriptionPlanPrice.id.desc(),
        ).first()
        if not monthly_price or not annual_price:
            continue
        annual_savings_amount_minor, annual_savings_percent = _compute_annual_savings(monthly_price, annual_price)
        plan_views.append(
            PlanView(
                plan=plan,
                monthly=_build_interval_view(price_row=monthly_price, display_currency=display_currency),
                annual=_build_interval_view(
                    price_row=annual_price,
                    display_currency=display_currency,
                    annual_savings_amount_minor=annual_savings_amount_minor,
                    annual_savings_percent=annual_savings_percent,
                ),
            )
        )
    return plan_views


def get_plan_view(db: Session, *, plan_id: int, country_code: str = "") -> PlanView | None:
    for plan_view in build_plan_catalog(db, country_code=country_code):
        if int(plan_view.plan.id) == int(plan_id):
            return plan_view
    return None
