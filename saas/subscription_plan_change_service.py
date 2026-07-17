import hashlib
import json
from datetime import datetime

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import audit
from saas import models, paddle_client, subscription_change_service as changes


UPGRADE = "plan_upgrade"
DOWNGRADE = "plan_downgrade"
PLAN_CHANGE_TYPES = {UPGRADE, DOWNGRADE}
PLAN_ORDER = {"starter": 1, "professional": 2, "enterprise_ai": 3}
HARD_CONFLICT_DETECTORS = {}


def _clean(value):
    return str(value or "").strip()


def _profiles(db):
    return {row.plan_code: row for row in changes.entitlement_service.list_plan_entitlement_profiles(db)}


def _impact(db: Session, context, target_plan):
    profiles = _profiles(db)
    current = profiles.get(context.resolution.plan_code)
    target = profiles.get(target_plan.plan_code)
    if current is None or target is None:
        raise changes.SubscriptionChangeError("Plan entitlement information is unavailable.", code="ambiguous_plan_entitlements", status_code=409)
    losses = []
    conflicts = []
    for key, current_value in current.entitlements.items():
        target_value = target.entitlements.get(key)
        if current_value.granted and not (target_value and target_value.granted):
            losses.append({"key": key, "name": current_value.display_name, "data_preserved": True})
        if target_value is None:
            continue
        detector = HARD_CONFLICT_DETECTORS.get(key)
        if detector is None or target_value.value_type not in {"integer", "decimal"} or target_value.value is None:
            continue
        usage = detector(db, context)
        if usage is not None and usage > target_value.value:
            conflicts.append({"key": key, "name": target_value.display_name, "usage": usage, "limit": target_value.value})
    return {"feature_losses": losses, "blocking_conflicts": conflicts, "historical_data_preserved": True}


def _target(db: Session, context, plan_code: str):
    code = _clean(plan_code).lower()
    current_code = context.resolution.plan_code
    if code == current_code:
        raise changes.SubscriptionChangeError("Choose a different subscription plan.", code="same_plan")
    if code not in PLAN_ORDER or current_code not in PLAN_ORDER:
        raise changes.SubscriptionChangeError("This plan transition is unavailable.", code="unknown_plan_order", status_code=409)
    plans = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.plan_code == code,
        models.SubscriptionPlan.is_active == True,
        models.SubscriptionPlan.is_public == True,
    ).all()
    if len(plans) != 1:
        raise changes.SubscriptionChangeError("The selected plan is unavailable.", code="ambiguous_target_plan", status_code=409)
    plan = plans[0]
    prices = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == plan.id,
        models.SubscriptionPlanPrice.billing_interval == context.subscription.billing_interval,
        models.SubscriptionPlanPrice.currency_code == context.subscription.currency_code,
        models.SubscriptionPlanPrice.is_active == True,
    ).all()
    if len(prices) != 1 or not _clean(prices[0].provider_price_id):
        raise changes.SubscriptionChangeError("The selected plan price is unavailable.", code="ambiguous_target_price", status_code=409)
    direction = UPGRADE if PLAN_ORDER[code] > PLAN_ORDER[current_code] else DOWNGRADE
    return plan, prices[0], direction


def _items(payload, expected_price, expected_quantity):
    result = []
    matches = 0
    for item in payload.get("items") if isinstance(payload.get("items"), list) else []:
        price = item.get("price") if isinstance(item, dict) and isinstance(item.get("price"), dict) else {}
        price_id = _clean(price.get("id") or item.get("price_id"))
        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError):
            quantity = 0
        if not price_id or quantity < 1:
            raise changes.SubscriptionChangeError("Paddle subscription items require review.", code="invalid_provider_items", status_code=409)
        result.append({"price_id": price_id, "quantity": quantity})
        if price_id == expected_price:
            matches += 1
            if quantity != expected_quantity:
                raise changes.SubscriptionChangeError("The Paddle branch quantity does not match.", code="provider_quantity_mismatch", status_code=409)
    if matches != 1:
        raise changes.SubscriptionChangeError("The subscribed Paddle price could not be resolved uniquely.", code="provider_price_mismatch", status_code=409)
    return result


def _replace_price(items, current_price, target_price, quantity):
    replaced = []
    matches = 0
    for item in items:
        if item["price_id"] == current_price:
            replaced.append({"price_id": target_price, "quantity": quantity})
            matches += 1
        else:
            replaced.append(dict(item))
    if matches != 1:
        raise changes.SubscriptionChangeError("The current Paddle item could not be replaced safely.", code="provider_price_mismatch", status_code=409)
    return replaced


def _financials(preview, provider, direction, currency):
    summary = preview.get("update_summary") if isinstance(preview.get("update_summary"), dict) else {}
    sections = [summary.get(name) if isinstance(summary.get(name), dict) else {} for name in ("credit", "charge", "result")]
    if not summary or any(not section for section in sections):
        raise changes._preview_diagnostic("preview_financial_data_incomplete", missing_fields=["update_summary"], sections=changes._available_sections(preview))
    credit, charge, result = sections
    if {_clean(x.get("currency_code")).upper() for x in sections} != {currency}:
        raise changes._preview_diagnostic("preview_currency_mismatch", missing_fields=[], sections=changes._available_sections(summary))
    try:
        charge_minor = changes._minor_amount(charge.get("amount"), required=True)
        credit_minor = abs(changes._minor_amount(credit.get("amount"), required=True, allow_negative=True))
        changes._minor_amount(result.get("amount"), required=True, allow_negative=True)
    except ValueError:
        raise changes._preview_diagnostic("preview_financial_data_incomplete", missing_fields=["update_summary.amount"], sections=changes._available_sections(summary)) from None
    immediate = changes._transaction_total(preview.get("immediate_transaction"), "immediate_transaction", currency) if direction == UPGRADE else 0
    current = changes._transaction_total(provider.get("recurring_transaction_details"), "current_subscription.recurring_transaction_details", currency)
    recurring = changes._transaction_total(preview.get("recurring_transaction_details"), "recurring_transaction_details", currency)
    return charge_minor, credit_minor, immediate, current, recurring


def _key(context, target_plan_id):
    material = f"plan:{context.subscription.id}:{context.subscription.plan_id}:{target_plan_id}:{context.subscription.quantity}:{changes._utcnow().timestamp()}"
    return hashlib.sha256(material.encode()).hexdigest()


def preview_plan_change(db: Session, account, target_plan_code: str):
    context = changes.resolve_change_context(db, account, lock=True)
    pending = changes.get_pending_change(db, context.subscription.id)
    if pending:
        raise changes.SubscriptionChangeError("Another subscription change is already in progress.", code="change_already_pending", status_code=409)
    plan, price, direction = _target(db, context, target_plan_code)
    preview_rows = changes._expire_stale_previews(db, context)
    reusable = next((row for row in preview_rows if changes._preview_is_fresh(row) and row.change_type in PLAN_CHANGE_TYPES and row.target_plan_id == plan.id), None)
    if reusable:
        return reusable
    impact = _impact(db, context, plan)
    quantity = int(context.subscription.quantity)
    try:
        provider = paddle_client.get_subscription(subscription_id=context.subscription.provider_subscription_id, include="recurring_transaction_details")
        if _clean(provider.get("id")) != context.subscription.provider_subscription_id or _clean(provider.get("status")).lower() != "active":
            raise changes.SubscriptionChangeError("The Paddle subscription is unavailable for changes.", code="provider_subscription_unavailable", status_code=409)
        current_items = _items(provider, context.subscription.provider_price_id, quantity)
        changes._validate_provider_terms(provider, context.subscription.provider_price_id, context.subscription.billing_interval, context.subscription.currency_code)
        target_items = _replace_price(current_items, context.subscription.provider_price_id, price.provider_price_id, quantity)
        mode = "prorated_immediately" if direction == UPGRADE else "prorated_next_billing_period"
        preview = paddle_client.preview_subscription_update(subscription_id=context.subscription.provider_subscription_id, items=target_items, proration_billing_mode=mode)
    except changes.SubscriptionChangeError:
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        raise changes._safe_provider_failure(exc) from exc
    if _clean(preview.get("status")).lower() != "active" or _clean(preview.get("currency_code")).upper() != _clean(context.subscription.currency_code).upper():
        raise changes._preview_diagnostic("preview_subscription_mismatch", missing_fields=[], sections=changes._available_sections(preview))
    observed = _items(preview, price.provider_price_id, quantity)
    changes._validate_provider_terms(preview, price.provider_price_id, context.subscription.billing_interval, context.subscription.currency_code)
    if changes._items_signature(observed) != changes._items_signature(target_items):
        raise changes._preview_diagnostic("preview_items_mismatch", missing_fields=[], sections=changes._available_sections(preview))
    currency = _clean(context.subscription.currency_code).upper()
    charge, credit, immediate, current_total, next_total = _financials(preview, provider, direction, currency)
    from saas.payment_service import _parse_datetime
    effective_at = (_parse_datetime(provider.get("next_billed_at")) or context.subscription.next_billed_at) if direction == DOWNGRADE else None
    if direction == DOWNGRADE and effective_at is None:
        raise changes.SubscriptionChangeError("Paddle did not return the downgrade effective date.", code="missing_provider_renewal_date", status_code=409)
    row = models.SubscriptionChangeRequest(
        school_group_id=context.resolution.school_group_id, subscription_contract_id=context.contract.id,
        payment_subscription_id=context.subscription.id, provider_subscription_id=context.subscription.provider_subscription_id,
        requested_by_user_id=context.actor.id, requested_by_saas_account_id=context.account.id,
        change_type=direction, current_quantity=quantity, requested_quantity=quantity, quantity_delta=0,
        current_plan_price_id=context.plan_price.id, provider_price_id=context.subscription.provider_price_id,
        target_plan_id=plan.id, target_plan_price_id=price.id, target_provider_price_id=price.provider_price_id,
        entitlement_impact_json=json.dumps(impact, separators=(",", ":"), sort_keys=True),
        billing_interval=context.subscription.billing_interval, currency_code=currency,
        effective_mode=changes.IMMEDIATE if direction == UPGRADE else changes.NEXT_PERIOD, status="previewed",
        previewed_charge_minor=charge, previewed_credit_minor=credit, previewed_net_minor=immediate,
        current_renewal_total_minor=current_total, next_renewal_total_minor=next_total,
        retained_items_json=json.dumps(target_items, separators=(",", ":"), sort_keys=True),
        idempotency_key=_key(context, plan.id), requested_at=changes._utcnow(), previewed_at=changes._utcnow(), effective_at=effective_at,
    )
    for previous in preview_rows:
        if changes._preview_is_fresh(previous):
            previous.status = "superseded"
            previous.failure_code = "preview_superseded"
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise changes.SubscriptionChangeError("Another subscription change is already in progress.", code="change_already_pending", status_code=409) from exc
    changes._audit("subscription_plan_preview_created", context, row, target_plan_code=plan.plan_code, direction=direction)
    return row


def _row_context(db, account, request_uuid):
    context = changes.resolve_change_context(db, account, lock=True)
    row = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.request_uuid == _clean(request_uuid),
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
        models.SubscriptionChangeRequest.change_type.in_(PLAN_CHANGE_TYPES),
    ).with_for_update().one_or_none()
    if row is None:
        raise changes.SubscriptionChangeError("Plan-change request not found.", code="change_not_found", status_code=404)
    return context, row


def _validate_row(db, context, row):
    plan = db.query(models.SubscriptionPlan).filter(models.SubscriptionPlan.id == row.target_plan_id, models.SubscriptionPlan.is_active == True).one_or_none()
    price = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.id == row.target_plan_price_id,
        models.SubscriptionPlanPrice.plan_id == row.target_plan_id,
        models.SubscriptionPlanPrice.provider_price_id == row.target_provider_price_id,
        models.SubscriptionPlanPrice.billing_interval == context.subscription.billing_interval,
        models.SubscriptionPlanPrice.currency_code == context.subscription.currency_code,
        models.SubscriptionPlanPrice.is_active == True,
    ).one_or_none()
    valid = plan and price and row.subscription_contract_id == context.contract.id and row.current_plan_price_id == context.plan_price.id and row.provider_price_id == context.subscription.provider_price_id and row.current_quantity == int(context.subscription.quantity) and row.requested_quantity == row.current_quantity
    if not valid:
        raise changes.SubscriptionChangeError("The plan preview is no longer valid. Generate a new preview to continue.", code="stale_preview", status_code=409)
    return plan, price


def get_confirmation_preview(db, account, request_uuid):
    context, row = _row_context(db, account, request_uuid)
    if row.status != "previewed" or not changes._preview_is_fresh(row):
        if row.status in changes.PREVIEW_ONLY_STATUSES:
            row.status = "expired"
        raise changes.SubscriptionChangeError("The plan preview is no longer valid. Generate a new preview to continue.", code="stale_preview", status_code=409)
    plan, _ = _validate_row(db, context, row)
    impact = _impact(db, context, plan)
    return row, plan, impact


def submit_plan_change(db, account, request_uuid):
    context, row = _row_context(db, account, request_uuid)
    if row.status in {"payment_pending", "scheduled", "confirmed"}:
        return row
    if row.status != "previewed" or not changes._preview_is_fresh(row):
        if row.status in changes.PREVIEW_ONLY_STATUSES:
            row.status = "expired"
        raise changes.SubscriptionChangeError("The plan preview is no longer valid. Generate a new preview to continue.", code="stale_preview", status_code=409)
    plan, _ = _validate_row(db, context, row)
    impact = _impact(db, context, plan)
    if impact["blocking_conflicts"]:
        raise changes.SubscriptionChangeError("Resolve the listed plan compatibility issues before downgrading.", code="downgrade_conflict", status_code=409)
    items = changes._stored_items(row)
    attempted = False
    accepted = False
    try:
        provider = paddle_client.get_subscription(subscription_id=row.provider_subscription_id)
        current = _items(provider, row.provider_price_id, row.current_quantity)
        if _clean(provider.get("id")) != row.provider_subscription_id or _clean(provider.get("status")).lower() != "active":
            raise changes.SubscriptionChangeError("The Paddle subscription changed after this preview.", code="stale_provider_subscription", status_code=409)
        changes._validate_provider_terms(provider, row.provider_price_id, row.billing_interval, row.currency_code)
        expected = _replace_price(current, row.provider_price_id, row.target_provider_price_id, row.current_quantity)
        if changes._items_signature(expected) != changes._items_signature(items):
            raise changes.SubscriptionChangeError("The Paddle subscription changed after this preview.", code="stale_provider_items", status_code=409)
        row.submitted_at = changes._utcnow()
        attempted = True
        response = paddle_client.update_subscription(subscription_id=row.provider_subscription_id, items=items, proration_billing_mode="prorated_immediately" if row.change_type == UPGRADE else "prorated_next_billing_period", on_payment_failure="prevent_change")
        accepted = True
        observed = _items(response, row.target_provider_price_id, row.current_quantity)
        changes._validate_provider_terms(response, row.target_provider_price_id, row.billing_interval, row.currency_code)
        if _clean(response.get("id")) != row.provider_subscription_id or changes._items_signature(observed) != changes._items_signature(items):
            raise changes.SubscriptionChangeError("Paddle returned an unexpected subscription response.", code="provider_items_mismatch", status_code=409)
    except changes.SubscriptionChangeError:
        if accepted:
            row.status = "manual_review"
            row.failure_code = "provider_update_response_mismatch"
        elif not attempted:
            row.status = "expired"
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        status = getattr(exc, "status_code", None)
        unknown = attempted and (isinstance(exc, httpx.HTTPError) or (isinstance(status, int) and status >= 500))
        row.status = "manual_review" if unknown else "failed"
        row.failure_code = "provider_outcome_unknown" if unknown else (_clean(getattr(exc, "error_code", "")) or "provider_update_failed")
        raise changes._safe_provider_failure(exc) from exc
    row.provider_observed_price_id = row.target_provider_price_id
    if row.change_type == UPGRADE:
        row.status = "payment_pending"
    else:
        row.status = "scheduled"
        row.provider_scheduled_at = changes._utcnow()
    changes._audit("subscription_plan_change_submitted", context, row, target_plan_id=row.target_plan_id, direction=row.change_type)
    return row


def _scheduled_row(db, context, account, request_uuid):
    return db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.request_uuid == _clean(request_uuid),
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
        models.SubscriptionChangeRequest.change_type == DOWNGRADE,
    ).with_for_update().one_or_none()


def _cancel_provider_schedule(context, row):
    attempted = False
    accepted = False
    try:
        provider = paddle_client.get_subscription(subscription_id=row.provider_subscription_id)
        scheduled_items = _items(provider, row.target_provider_price_id, row.current_quantity)
        changes._validate_provider_terms(provider, row.target_provider_price_id, row.billing_interval, row.currency_code)
        restored = _replace_price(scheduled_items, row.target_provider_price_id, row.provider_price_id, row.current_quantity)
        paddle_client.preview_subscription_update(
            subscription_id=row.provider_subscription_id,
            items=restored,
            proration_billing_mode="prorated_next_billing_period",
        )
        attempted = True
        response = paddle_client.update_subscription(
            subscription_id=row.provider_subscription_id,
            items=restored,
            proration_billing_mode="prorated_next_billing_period",
            on_payment_failure="prevent_change",
        )
        accepted = True
        observed = _items(response, row.provider_price_id, row.current_quantity)
        changes._validate_provider_terms(response, row.provider_price_id, row.billing_interval, row.currency_code)
        if _clean(response.get("id")) != row.provider_subscription_id or changes._items_signature(observed) != changes._items_signature(restored):
            raise changes.SubscriptionChangeError("Paddle returned an unexpected cancellation response.", code="provider_cancellation_mismatch", status_code=409)
        return restored
    except changes.SubscriptionChangeError:
        if accepted:
            row.status = "manual_review"
            row.failure_code = "provider_cancellation_response_mismatch"
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        status = getattr(exc, "status_code", None)
        unknown = attempted and (isinstance(exc, httpx.HTTPError) or (isinstance(status, int) and status >= 500))
        if unknown:
            row.status = "manual_review"
            row.failure_code = "provider_cancellation_outcome_unknown"
        raise changes._safe_provider_failure(exc) from exc


def cancel_scheduled_plan_change(db: Session, account, request_uuid: str):
    context = changes.resolve_change_context(db, account, lock=True)
    row = _scheduled_row(db, context, account, request_uuid)
    if row is None:
        raise changes.SubscriptionChangeError("Scheduled plan change not found.", code="change_not_found", status_code=404)
    if row.status == "canceled":
        return row
    if row.status != "scheduled":
        raise changes.SubscriptionChangeError("This plan change cannot be canceled.", code="change_not_cancelable", status_code=409)
    if row.effective_at and row.effective_at <= changes._utcnow():
        raise changes.SubscriptionChangeError("This scheduled plan change has reached its effective date.", code="change_already_effective", status_code=409)
    _cancel_provider_schedule(context, row)
    row.status = "canceled"
    row.canceled_at = changes._utcnow()
    changes._audit("subscription_plan_change_canceled", context, row, target_plan_id=row.target_plan_id)
    return row


def get_replacement_confirmation(db: Session, account, request_uuid: str, target_plan_code: str):
    context = changes.resolve_change_context(db, account, lock=True)
    row = _scheduled_row(db, context, account, request_uuid)
    if row is None or row.status != "scheduled":
        raise changes.SubscriptionChangeError("Scheduled plan change not found.", code="change_not_replaceable", status_code=409)
    plan, _price, direction = _target(db, context, target_plan_code)
    if plan.id == row.target_plan_id:
        raise changes.SubscriptionChangeError("That plan is already scheduled.", code="same_scheduled_plan", status_code=409)
    return row, plan, direction


def replace_scheduled_plan_change(db: Session, account, request_uuid: str, target_plan_code: str):
    context = changes.resolve_change_context(db, account, lock=True)
    row = _scheduled_row(db, context, account, request_uuid)
    plan, _price, _direction = _target(db, context, target_plan_code)
    if row is None:
        raise changes.SubscriptionChangeError("Scheduled plan change not found.", code="change_not_found", status_code=404)
    if row.status == "superseded":
        replacement = db.query(models.SubscriptionChangeRequest).filter(
            models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
            models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
            models.SubscriptionChangeRequest.target_plan_id == plan.id,
            models.SubscriptionChangeRequest.status.in_(changes.PREVIEW_ONLY_STATUSES),
        ).order_by(models.SubscriptionChangeRequest.created_at.desc()).first()
        if replacement and changes._preview_is_fresh(replacement):
            return replacement
    if row.status != "scheduled":
        raise changes.SubscriptionChangeError("This plan change cannot be replaced.", code="change_not_replaceable", status_code=409)
    if plan.id == row.target_plan_id:
        raise changes.SubscriptionChangeError("That plan is already scheduled.", code="same_scheduled_plan", status_code=409)
    if row.effective_at and row.effective_at <= changes._utcnow():
        raise changes.SubscriptionChangeError("This scheduled plan change has reached its effective date.", code="change_already_effective", status_code=409)
    _cancel_provider_schedule(context, row)
    row.status = "superseded"
    row.canceled_at = changes._utcnow()
    changes._audit("subscription_plan_change_superseded", context, row, replacement_plan_id=plan.id)
    db.flush()
    try:
        return preview_plan_change(db, account, plan.plan_code)
    except Exception:
        row.status = "canceled"
        row.failure_code = "replacement_preview_failed"
        raise


def customer_summary(row, plan, impact, current_plan_name):
    summary = changes.customer_summary(row)
    summary.update({"current_plan_name": current_plan_name, "target_plan_name": plan.plan_name, "is_upgrade": row.change_type == UPGRADE, "feature_losses": impact["feature_losses"], "blocking_conflicts": impact["blocking_conflicts"]})
    return summary


def _apply_confirmed(db, row, subscription):
    contract = db.query(models.SubscriptionContract).filter(models.SubscriptionContract.id == row.subscription_contract_id, models.SubscriptionContract.school_group_id == row.school_group_id).with_for_update().one_or_none()
    price = db.query(models.SubscriptionPlanPrice).filter(models.SubscriptionPlanPrice.id == row.target_plan_price_id, models.SubscriptionPlanPrice.plan_id == row.target_plan_id, models.SubscriptionPlanPrice.provider_price_id == row.target_provider_price_id).one_or_none()
    if contract is None or price is None or subscription.subscription_contract_id != contract.id:
        row.status = "manual_review"; row.failure_code = "local_plan_relationship_mismatch"
        return False
    subscription.plan_id = row.target_plan_id
    subscription.provider_price_id = row.target_provider_price_id
    subscription.unit_amount_minor = price.amount_minor
    subscription.amount_minor = row.next_renewal_total_minor
    contract.plan_id = row.target_plan_id
    contract.base_amount_minor = price.amount_minor
    contract.display_amount_minor = price.amount_minor
    contract.plan_version = price.plan_version
    row.status = "confirmed"; row.confirmed_at = changes._utcnow()
    audit.write_audit_event({"event_type": "subscription_plan_change_confirmed", "school_group_id": row.school_group_id, "subscription_change_request_uuid": row.request_uuid, "target_plan_id": row.target_plan_id})
    return True


def reconcile_plan_change_webhook(db: Session, payload: dict, event_type: str):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    subscription_id = _clean(data.get("id") if event_type.startswith("subscription.") else data.get("subscription_id"))
    if not subscription_id:
        return None
    row = db.query(models.SubscriptionChangeRequest).filter(models.SubscriptionChangeRequest.provider_subscription_id == subscription_id, models.SubscriptionChangeRequest.change_type.in_(PLAN_CHANGE_TYPES), models.SubscriptionChangeRequest.status.in_((*changes.UNRESOLVED_STATUSES, "confirmed"))).order_by(models.SubscriptionChangeRequest.created_at.desc()).with_for_update().first()
    if row is None:
        return None
    subscription = db.query(models.PaymentSubscription).filter(models.PaymentSubscription.id == row.payment_subscription_id).with_for_update().one_or_none()
    if subscription is None:
        row.status = "manual_review"; row.failure_code = "missing_local_subscription"
        return {"status": "manual_review", "event_type": event_type}
    if event_type.startswith("transaction."):
        if _clean(data.get("origin")) != "subscription_update":
            return None
        price_ids = {_clean((item.get("price") or {}).get("id") or item.get("price_id")) for item in data.get("items", []) if isinstance(item, dict)}
        if _clean(data.get("currency_code")).upper() != row.currency_code or row.target_provider_price_id not in price_ids:
            row.status = "manual_review"; row.failure_code = "provider_transaction_mismatch"
            return {"status": "manual_review", "event_type": event_type}
        if event_type in {"transaction.payment_failed", "transaction.past_due"} and row.change_type == UPGRADE:
            row.status = "failed"; row.failure_code = "provider_payment_failed"
            return {"status": "processed", "event_type": event_type}
        if event_type == "transaction.completed" and row.change_type == UPGRADE and _clean(data.get("status")).lower() == "completed":
            row.provider_payment_confirmed_at = row.provider_payment_confirmed_at or changes._utcnow()
            if row.provider_observed_price_id == row.target_provider_price_id:
                _apply_confirmed(db, row, subscription)
            return {"status": "processed", "event_type": event_type}
        return None
    if not event_type.startswith("subscription."):
        return None
    try:
        observed = _items(data, row.target_provider_price_id, row.current_quantity)
        changes._validate_provider_terms(data, row.target_provider_price_id, row.billing_interval, row.currency_code)
        if changes._items_signature(observed) != changes._items_signature(changes._stored_items(row)):
            raise changes.SubscriptionChangeError("Provider items mismatch.")
    except changes.SubscriptionChangeError:
        row.status = "manual_review"; row.failure_code = "provider_items_mismatch"
        return {"status": "manual_review", "event_type": event_type}
    row.provider_observed_price_id = row.target_provider_price_id
    period = data.get("current_billing_period") if isinstance(data.get("current_billing_period"), dict) else {}
    from saas.payment_service import _parse_datetime
    period_start = _parse_datetime(period.get("starts_at"))
    period_end = _parse_datetime(period.get("ends_at"))
    next_billed = _parse_datetime(data.get("next_billed_at"))
    if row.change_type == UPGRADE:
        if row.provider_payment_confirmed_at:
            _apply_confirmed(db, row, subscription)
        else:
            row.status = "payment_pending"
    elif row.effective_at and period_start and period_start >= row.effective_at:
        _apply_confirmed(db, row, subscription)
    else:
        row.status = "scheduled"
    subscription.current_period_start = period_start or subscription.current_period_start
    subscription.current_period_end = period_end or subscription.current_period_end
    subscription.next_billed_at = next_billed or subscription.next_billed_at
    return {"status": "processed", "event_type": event_type}
