from datetime import UTC, datetime

from sqlalchemy.orm import Session

from saas import models, pricing_service, service

NOT_STARTED = "not_started"
PLAN_SELECTED = "plan_selected"
CHECKOUT_READY = "checkout_ready"
CHECKOUT_INITIATED = "checkout_initiated"


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def ensure_ready_for_checkout(organization):
    if str(getattr(organization, "status", "") or "").strip().lower() != service.READY_FOR_CHECKOUT_STATUS:
        raise ValueError("Plan selection is available only after organization setup reaches ready_for_checkout.")


def get_current_plan_selection(db: Session, organization):
    return db.query(models.PendingOrganizationPlanSelection).filter(
        models.PendingOrganizationPlanSelection.pending_organization_id == organization.id,
        models.PendingOrganizationPlanSelection.selection_status == "selected",
    ).order_by(
        models.PendingOrganizationPlanSelection.selected_at.desc(),
        models.PendingOrganizationPlanSelection.id.desc(),
    ).first()


def get_current_checkout_session(db: Session, organization):
    return db.query(models.CheckoutSession).filter(
        models.CheckoutSession.pending_organization_id == organization.id
    ).order_by(models.CheckoutSession.updated_at.desc(), models.CheckoutSession.id.desc()).first()


def get_current_subscription_contract(db: Session, organization):
    return db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == organization.id
    ).order_by(models.SubscriptionContract.updated_at.desc(), models.SubscriptionContract.id.desc()).first()


def select_plan(
    db: Session,
    organization,
    *,
    plan_id: int,
    billing_interval: str,
) -> models.PendingOrganizationPlanSelection:
    ensure_ready_for_checkout(organization)
    cleaned_interval = str(billing_interval or "").strip().lower()
    if cleaned_interval not in {"monthly", "annual"}:
        raise ValueError("Billing interval must be monthly or annual.")
    plan_view = pricing_service.get_plan_view(
        db,
        plan_id=int(plan_id),
        country_code=str(getattr(organization, "country_code", "") or ""),
    )
    if not plan_view:
        raise ValueError("Selected subscription plan is not available.")
    interval_view = plan_view.monthly if cleaned_interval == "monthly" else plan_view.annual

    db.query(models.PendingOrganizationPlanSelection).filter(
        models.PendingOrganizationPlanSelection.pending_organization_id == organization.id,
        models.PendingOrganizationPlanSelection.selection_status == "selected",
    ).update(
        {models.PendingOrganizationPlanSelection.selection_status: "superseded"},
        synchronize_session=False,
    )

    selection = models.PendingOrganizationPlanSelection(
        pending_organization_id=organization.id,
        plan_id=plan_view.plan.id,
        billing_interval=cleaned_interval,
        base_currency_code=interval_view.base_currency_code,
        base_amount_minor=interval_view.base_amount_minor,
        display_currency_code=interval_view.display_currency_code,
        display_amount_minor=interval_view.display_amount_minor,
        display_exchange_rate=interval_view.display_amount_minor / interval_view.base_amount_minor if interval_view.base_amount_minor else 1,
        annual_savings_amount_minor=interval_view.annual_savings_amount_minor,
        annual_savings_percent=interval_view.annual_savings_percent,
        plan_version=interval_view.plan_version,
        is_founding_offer=interval_view.is_founding_offer,
        selection_status="selected",
        selected_at=_utcnow(),
    )
    db.add(selection)
    db.flush()

    organization.billing_status = PLAN_SELECTED
    organization.selected_plan_id = plan_view.plan.id
    organization.selected_billing_interval = cleaned_interval

    contract = get_current_subscription_contract(db, organization)
    if not contract:
        contract = models.SubscriptionContract(
            pending_organization_id=organization.id,
            plan_id=plan_view.plan.id,
            billing_interval=cleaned_interval,
            contract_status="draft",
            base_currency_code=interval_view.base_currency_code,
            base_amount_minor=interval_view.base_amount_minor,
            display_currency_code=interval_view.display_currency_code,
            display_amount_minor=interval_view.display_amount_minor,
            contract_type="self_serve",
            plan_version=interval_view.plan_version,
            is_founding_offer=interval_view.is_founding_offer,
        )
        db.add(contract)
    else:
        contract.plan_id = plan_view.plan.id
        contract.billing_interval = cleaned_interval
        contract.contract_status = "draft"
        contract.base_currency_code = interval_view.base_currency_code
        contract.base_amount_minor = interval_view.base_amount_minor
        contract.display_currency_code = interval_view.display_currency_code
        contract.display_amount_minor = interval_view.display_amount_minor
        contract.plan_version = interval_view.plan_version
        contract.is_founding_offer = interval_view.is_founding_offer
    service.log_pending_event(
        db,
        organization=organization,
        event_type="plan_selected",
        details={
            "plan_id": plan_view.plan.id,
            "plan_code": plan_view.plan.plan_code,
            "billing_interval": cleaned_interval,
        },
    )
    return selection


def build_checkout_summary(db: Session, organization):
    selection = get_current_plan_selection(db, organization)
    if not selection:
        return None
    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == selection.plan_id
    ).first()
    checkout_session = get_current_checkout_session(db, organization)
    contract = get_current_subscription_contract(db, organization)
    return {
        "selection": selection,
        "plan": plan,
        "checkout_session": checkout_session,
        "contract": contract,
    }


def create_or_update_checkout_session(db: Session, organization):
    ensure_ready_for_checkout(organization)
    selection = get_current_plan_selection(db, organization)
    if not selection:
        raise ValueError("Select a subscription plan before continuing to checkout.")
    plan_price = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == selection.plan_id,
        models.SubscriptionPlanPrice.billing_interval == selection.billing_interval,
        models.SubscriptionPlanPrice.currency_code == "USD",
        models.SubscriptionPlanPrice.is_active == True,
    ).order_by(
        models.SubscriptionPlanPrice.plan_version.desc(),
        models.SubscriptionPlanPrice.id.desc(),
    ).first()

    checkout_session = get_current_checkout_session(db, organization)
    if not checkout_session:
        checkout_session = models.CheckoutSession(
            pending_organization_id=organization.id,
            plan_selection_id=selection.id,
            status="ready",
            provider="paddle",
            currency_code=selection.display_currency_code,
            amount_minor=selection.display_amount_minor,
            billing_interval=selection.billing_interval,
            provider_price_id=str(getattr(plan_price, "provider_price_id", "") or "").strip() or None,
            started_at=_utcnow(),
        )
        db.add(checkout_session)
        db.flush()
    else:
        checkout_session.plan_selection_id = selection.id
        checkout_session.status = "ready"
        checkout_session.provider = "paddle"
        checkout_session.currency_code = selection.display_currency_code
        checkout_session.amount_minor = selection.display_amount_minor
        checkout_session.billing_interval = selection.billing_interval
        checkout_session.provider_price_id = str(getattr(plan_price, "provider_price_id", "") or "").strip() or None
        checkout_session.started_at = checkout_session.started_at or _utcnow()

    contract = get_current_subscription_contract(db, organization)
    if not contract:
        raise ValueError("Subscription contract could not be prepared.")
    contract.selected_checkout_session_id = checkout_session.id
    contract.contract_status = "checkout_pending"

    organization.billing_status = CHECKOUT_READY
    organization.checkout_ready_at = _utcnow()

    service.log_pending_event(
        db,
        organization=organization,
        event_type="checkout_ready",
        details={
            "checkout_session_id": checkout_session.id,
            "billing_interval": selection.billing_interval,
            "display_currency_code": selection.display_currency_code,
        },
    )
    return checkout_session
