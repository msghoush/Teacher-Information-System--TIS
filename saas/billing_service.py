from datetime import UTC, datetime

from sqlalchemy.orm import Session

from saas import branch_pricing_quote_service, models, pricing_service, service

NOT_STARTED = "not_started"
PLAN_SELECTED = "plan_selected"
CHECKOUT_READY = "checkout_ready"
CHECKOUT_INITIATED = "checkout_initiated"
OPEN_CHECKOUT_SESSION_STATUSES = ("ready", "started", "processing")
OPEN_PAYMENT_ATTEMPT_STATUSES = ("checkout_started", "payment_processing")


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


def supersede_checkout_lineage(
    db: Session,
    organization,
    checkout_sessions: list,
    *,
    reason: str,
) -> int:
    sessions = [row for row in checkout_sessions if row is not None]
    if not sessions:
        return 0
    now = _utcnow()
    session_ids = {int(row.id) for row in sessions if getattr(row, "id", None)}
    for checkout_session in sessions:
        checkout_session.status = "stale"
        checkout_session.abandoned_at = now

    superseded_attempt_ids = set()
    if session_ids:
        attempts = db.query(models.PaymentAttempt).filter(
            models.PaymentAttempt.pending_organization_id == organization.id,
            models.PaymentAttempt.checkout_session_id.in_(session_ids),
            models.PaymentAttempt.status.in_(OPEN_PAYMENT_ATTEMPT_STATUSES),
        ).all()
        for attempt in attempts:
            attempt.status = "superseded"
            attempt.failure_reason = reason
            superseded_attempt_ids.add(int(attempt.id))

    if int(getattr(organization, "last_payment_attempt_id", 0) or 0) in superseded_attempt_ids:
        organization.last_payment_attempt_id = None
    contract = get_current_subscription_contract(db, organization)
    if (
        contract
        and int(getattr(contract, "selected_checkout_session_id", 0) or 0)
        in session_ids
        and str(getattr(contract, "payment_status", "") or "").lower() != "paid"
    ):
        contract.selected_checkout_session_id = None
    return len(sessions)


def select_plan(
    db: Session,
    organization,
    *,
    plan_id: int,
    billing_interval: str,
) -> models.PendingOrganizationPlanSelection:
    service.ensure_initial_checkout_available(db, organization)
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
    quote = branch_pricing_quote_service.require_ready_quote(
        branch_pricing_quote_service.build_quote(
            db,
            organization,
            plan_id=plan_view.plan.id,
            billing_interval=cleaned_interval,
        )
    )

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
        billable_branch_count=quote.billable_branch_count,
        quoted_base_amount_minor=quote.total_amount_minor,
        quoted_display_amount_minor=quote.display_total_amount_minor,
        quote_fingerprint=quote.fingerprint or None,
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
            billable_branch_count=quote.billable_branch_count,
            quoted_base_amount_minor=quote.total_amount_minor,
            quoted_display_amount_minor=quote.display_total_amount_minor,
            quote_fingerprint=quote.fingerprint or None,
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
        contract.billable_branch_count = quote.billable_branch_count
        contract.quoted_base_amount_minor = quote.total_amount_minor
        contract.quoted_display_amount_minor = quote.display_total_amount_minor
        contract.quote_fingerprint = quote.fingerprint or None
    obsolete_checkout_sessions = db.query(models.CheckoutSession).filter(
        models.CheckoutSession.pending_organization_id == organization.id,
        models.CheckoutSession.status.in_(OPEN_CHECKOUT_SESSION_STATUSES),
    ).all()
    obsolete_checkout_sessions = [
        row
        for row in obsolete_checkout_sessions
        if (
            str(getattr(row, "quote_fingerprint", "") or "") != quote.fingerprint
            or int(getattr(row, "plan_selection_id", 0) or 0) != int(selection.id)
        )
    ]
    supersede_checkout_lineage(
        db,
        organization,
        obsolete_checkout_sessions,
        reason="Checkout superseded after the selected plan or billing interval changed.",
    )
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
    quote = branch_pricing_quote_service.build_quote(db, organization)
    return {
        "selection": selection,
        "plan": plan,
        "checkout_session": checkout_session,
        "contract": contract,
        "quote": quote,
    }


def checkout_quote_is_fresh(db: Session, organization) -> bool:
    checkout_session = get_current_checkout_session(db, organization)
    if not checkout_session or checkout_session.status == "stale":
        return False
    quote = branch_pricing_quote_service.build_quote(db, organization)
    return quote.is_ready and str(checkout_session.quote_fingerprint or "") == quote.fingerprint


def create_or_update_checkout_session(db: Session, organization):
    service.ensure_initial_checkout_available(db, organization)
    ensure_ready_for_checkout(organization)
    selection = get_current_plan_selection(db, organization)
    if not selection:
        raise ValueError("Select a subscription plan before continuing to checkout.")
    quote = branch_pricing_quote_service.require_ready_quote(
        branch_pricing_quote_service.build_quote(db, organization)
    )
    plan_price = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.id == quote.plan_price_id
    ).first()
    selection.billable_branch_count = quote.billable_branch_count
    selection.quoted_base_amount_minor = quote.total_amount_minor
    selection.quoted_display_amount_minor = quote.display_total_amount_minor
    selection.quote_fingerprint = quote.fingerprint

    checkout_session = get_current_checkout_session(db, organization)
    current_status = str(getattr(checkout_session, "status", "") or "").lower()
    current_lineage_matches = bool(
        checkout_session
        and str(getattr(checkout_session, "quote_fingerprint", "") or "")
        == quote.fingerprint
        and int(getattr(checkout_session, "plan_selection_id", 0) or 0)
        == int(selection.id)
    )
    if (
        current_lineage_matches
        and current_status == "started"
        and str(checkout_session.checkout_url or "").strip()
    ):
        return checkout_session
    if checkout_session and (
        not current_lineage_matches
        or current_status not in {"ready", "started"}
        or (current_status == "started" and not str(checkout_session.checkout_url or "").strip())
    ):
        supersede_checkout_lineage(
            db,
            organization,
            [checkout_session],
            reason="Checkout superseded because its local payment session was incomplete or obsolete.",
        )
        checkout_session = None
    if not checkout_session or checkout_session.status == "stale":
        checkout_session = models.CheckoutSession(
            pending_organization_id=organization.id,
            plan_selection_id=selection.id,
            status="ready",
            provider="paddle",
            currency_code=selection.display_currency_code,
            amount_minor=quote.display_total_amount_minor,
            billing_interval=selection.billing_interval,
            provider_price_id=str(getattr(plan_price, "provider_price_id", "") or "").strip() or None,
            billable_branch_count=quote.billable_branch_count,
            quoted_base_amount_minor=quote.total_amount_minor,
            quoted_display_amount_minor=quote.display_total_amount_minor,
            quote_fingerprint=quote.fingerprint,
            started_at=_utcnow(),
        )
        db.add(checkout_session)
        db.flush()
    else:
        checkout_session.plan_selection_id = selection.id
        checkout_session.status = "ready"
        checkout_session.provider = "paddle"
        checkout_session.currency_code = selection.display_currency_code
        checkout_session.amount_minor = quote.display_total_amount_minor
        checkout_session.billing_interval = selection.billing_interval
        checkout_session.provider_price_id = str(getattr(plan_price, "provider_price_id", "") or "").strip() or None
        checkout_session.billable_branch_count = quote.billable_branch_count
        checkout_session.quoted_base_amount_minor = quote.total_amount_minor
        checkout_session.quoted_display_amount_minor = quote.display_total_amount_minor
        checkout_session.quote_fingerprint = quote.fingerprint
        checkout_session.started_at = checkout_session.started_at or _utcnow()

    contract = get_current_subscription_contract(db, organization)
    if not contract:
        raise ValueError("Subscription contract could not be prepared.")
    contract.selected_checkout_session_id = checkout_session.id
    contract.contract_status = "checkout_pending"
    contract.billable_branch_count = quote.billable_branch_count
    contract.quoted_base_amount_minor = quote.total_amount_minor
    contract.quoted_display_amount_minor = quote.display_total_amount_minor
    contract.quote_fingerprint = quote.fingerprint

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
