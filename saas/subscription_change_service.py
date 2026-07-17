from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import uuid

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import audit
import models as operational_models
from saas import entitlement_service, models, paddle_client


INCREASE = "branch_quantity_increase"
REDUCTION = "branch_quantity_reduction"
IMMEDIATE = "immediate_prorated"
NEXT_PERIOD = "next_billing_period"
PREVIEW_ONLY_STATUSES = {"draft", "previewed", "awaiting_confirmation"}
PROVIDER_SUBMITTED_STATUSES = {"submitted", "payment_pending", "scheduled"}
UNRESOLVED_STATUSES = {
    "draft", "previewed", "awaiting_confirmation", "submitted",
    "payment_pending", "scheduled", "manual_review",
}
TERMINAL_STATUSES = {"completed", "confirmed", "canceled", "expired", "failed", "superseded"}
PREVIEW_FRESHNESS = timedelta(minutes=30)
logger = logging.getLogger(__name__)


class SubscriptionChangeError(ValueError):
    def __init__(self, message: str, *, code: str = "change_unavailable", status_code: int = 400, diagnostics: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.diagnostics = diagnostics or {}


@dataclass(frozen=True)
class ChangeContext:
    account: object
    actor: object
    resolution: entitlement_service.EntitlementResolution
    subscription: models.PaymentSubscription
    contract: models.SubscriptionContract
    plan_price: models.SubscriptionPlanPrice


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(value) -> str:
    return str(value or "").strip()


def _audit(event_type: str, context: ChangeContext, request_row=None, **details):
    audit.write_audit_event({
        "event_type": event_type,
        "actor_saas_account_id": int(context.account.id),
        "actor_user_id": getattr(context.actor, "id", None),
        "school_group_id": context.resolution.school_group_id,
        "subscription_change_request_uuid": getattr(request_row, "request_uuid", None),
        "provider_subscription_reference": context.subscription.provider_subscription_id,
        **details,
    })


def _safe_provider_failure(exc: Exception) -> SubscriptionChangeError:
    code = _clean(getattr(exc, "error_code", "")) or "provider_request_failed"
    return SubscriptionChangeError(
        "Secure subscription management is temporarily unavailable. Please try again later.",
        code=code,
        status_code=502,
    )


def _resolve_actor(db: Session, account, school_group_id: int):
    links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.school_group_id == school_group_id,
    ).all()
    user_ids = {int(link.operational_user_id) for link in links if link.operational_user_id}
    if not user_ids:
        raise SubscriptionChangeError("Billing access is not available for this account.", code="missing_billing_identity", status_code=403)
    users = db.query(operational_models.User).filter(
        operational_models.User.id.in_(user_ids),
        operational_models.User.school_group_id == school_group_id,
        operational_models.User.is_active == True,
    ).all()
    authorized = [
        user for user in users
        if auth.has_permission(db, user, "subscriptions.manage_billing", school_group_id=school_group_id)
    ]
    if len(authorized) != 1:
        raise SubscriptionChangeError("Billing access is not available for this account.", code="ambiguous_billing_identity", status_code=403)
    return authorized[0]


def resolve_change_context(db: Session, account, *, lock: bool = False) -> ChangeContext:
    resolution = entitlement_service.resolve_customer_entitlements(db, account)
    if not resolution.resolved or not resolution.subscription_id or not resolution.school_group_id:
        raise SubscriptionChangeError("This subscription requires review before it can be changed.", code=resolution.reason_code, status_code=409)
    query = db.query(models.PaymentSubscription).filter(models.PaymentSubscription.id == resolution.subscription_id)
    subscription = query.with_for_update().one_or_none() if lock else query.one_or_none()
    if subscription is None or _clean(subscription.status).lower() != "active":
        raise SubscriptionChangeError("Only an active subscription can be changed.", code="unsupported_subscription_status", status_code=409)
    if not _clean(subscription.provider_subscription_id):
        raise SubscriptionChangeError("This subscription requires review before it can be changed.", code="missing_provider_subscription", status_code=409)
    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.id == subscription.subscription_contract_id,
        models.SubscriptionContract.school_group_id == resolution.school_group_id,
    ).one_or_none()
    if contract is None:
        raise SubscriptionChangeError("This subscription requires review before it can be changed.", code="missing_confirmed_contract", status_code=409)
    plan_prices = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == subscription.plan_id,
        models.SubscriptionPlanPrice.billing_interval == subscription.billing_interval,
        models.SubscriptionPlanPrice.currency_code == subscription.currency_code,
        models.SubscriptionPlanPrice.provider_price_id == subscription.provider_price_id,
        models.SubscriptionPlanPrice.is_active == True,
    ).all()
    if len(plan_prices) != 1:
        raise SubscriptionChangeError("This subscription requires review before it can be changed.", code="ambiguous_plan_price", status_code=409)
    actor = _resolve_actor(db, account, int(resolution.school_group_id))
    return ChangeContext(account, actor, resolution, subscription, contract, plan_prices[0])


def get_pending_change(db: Session, payment_subscription_id: int):
    """Return only a change whose provider update is unresolved."""
    return db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == payment_subscription_id,
        (
            models.SubscriptionChangeRequest.status.in_(PROVIDER_SUBMITTED_STATUSES)
            | (
                (models.SubscriptionChangeRequest.status == "manual_review")
                & models.SubscriptionChangeRequest.submitted_at.isnot(None)
            )
        ),
    ).order_by(models.SubscriptionChangeRequest.created_at.desc()).first()


def _preview_is_fresh(row, *, now: datetime | None = None) -> bool:
    observed_at = row.previewed_at
    if row.status not in PREVIEW_ONLY_STATUSES or not isinstance(observed_at, datetime):
        return False
    return observed_at + PREVIEW_FRESHNESS > (now or _utcnow())


def _expire_stale_previews(db: Session, context: ChangeContext, *, now: datetime | None = None):
    now = now or _utcnow()
    rows = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        (
            models.SubscriptionChangeRequest.status.in_(PREVIEW_ONLY_STATUSES)
            | (
                (models.SubscriptionChangeRequest.status == "manual_review")
                & models.SubscriptionChangeRequest.submitted_at.is_(None)
            )
        ),
    ).with_for_update().all()
    for row in rows:
        if row.status == "manual_review" and row.submitted_at is None:
            row.status = "failed"
            row.failure_code = "pre_submission_uncertainty"
            row.failure_message = "The preview failed before a provider update was submitted."
            _audit("branch_quantity_preview_failed", context, row, failure_code=row.failure_code)
        elif not _preview_is_fresh(row, now=now):
            row.status = "expired"
            row.failure_code = "preview_expired"
            row.failure_message = "The billing preview expired before confirmation."
            _audit("branch_quantity_preview_expired", context, row)
    return [row for row in rows if row.status in PREVIEW_ONLY_STATUSES]


def _validate_preview_context(context: ChangeContext, row) -> None:
    expected_current = int(context.subscription.quantity or 0)
    valid = (
        row.school_group_id == context.resolution.school_group_id
        and row.subscription_contract_id == context.contract.id
        and row.payment_subscription_id == context.subscription.id
        and row.provider_subscription_id == context.subscription.provider_subscription_id
        and row.current_plan_price_id == context.plan_price.id
        and row.provider_price_id == context.subscription.provider_price_id
        and row.billing_interval == context.subscription.billing_interval
        and _clean(row.currency_code).upper() == _clean(context.subscription.currency_code).upper()
        and row.current_quantity == expected_current
        and row.requested_quantity >= 1
        and row.requested_quantity != row.current_quantity
        and row.quantity_delta == row.requested_quantity - row.current_quantity
        and row.change_type == (INCREASE if row.requested_quantity > row.current_quantity else REDUCTION)
    )
    if not valid:
        raise SubscriptionChangeError(
            "The billing preview is no longer valid. Generate a new preview to continue.",
            code="stale_preview",
            status_code=409,
        )


def get_confirmation_preview(db: Session, account, request_uuid: str):
    context = resolve_change_context(db, account, lock=True)
    row = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.request_uuid == _clean(request_uuid),
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
    ).with_for_update().one_or_none()
    if row is None:
        raise SubscriptionChangeError("Branch-capacity request not found.", code="change_not_found", status_code=404)
    if row.status != "previewed" or not _preview_is_fresh(row):
        if row.status in PREVIEW_ONLY_STATUSES:
            row.status = "expired"
            row.failure_code = "preview_expired"
            row.failure_message = "The billing preview expired before confirmation."
            _audit("branch_quantity_preview_expired", context, row)
        raise SubscriptionChangeError(
            "The billing preview is no longer valid. Generate a new preview to continue.",
            code="stale_preview",
            status_code=409,
        )
    _validate_preview_context(context, row)
    _stored_items(row)
    return row


def customer_summary(row) -> dict:
    currency = _clean(row.currency_code).upper() or "USD"
    symbol = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}.get(currency, currency + " ")

    def money(value):
        return "Not Available" if value is None else f"{symbol}{int(value) / 100:,.2f}"

    def date_label(value):
        return value.strftime("%B %d, %Y") if isinstance(value, datetime) else "Not Available"

    return {
        "request_uuid": row.request_uuid,
        "change_type": row.change_type,
        "is_increase": row.change_type == INCREASE,
        "current_quantity": row.current_quantity,
        "requested_quantity": row.requested_quantity,
        "quantity_delta": abs(row.quantity_delta),
        "billing_interval": {"monthly": "Monthly", "annual": "Annual"}.get(row.billing_interval, "Not Available"),
        "charge_label": money(row.previewed_charge_minor),
        "credit_label": money(row.previewed_credit_minor),
        "net_label": money(row.previewed_net_minor),
        "current_total_label": money(row.current_renewal_total_minor),
        "next_total_label": money(row.next_renewal_total_minor),
        "effective_date_label": date_label(row.effective_at),
        "status": row.status,
        "failure_message": row.failure_message or "",
    }


def _minor_amount(value, *, required: bool = False, allow_negative: bool = False) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        if required:
            raise ValueError("missing monetary value")
        return None
    if parsed < 0 and not allow_negative:
        raise ValueError("negative monetary value")
    return parsed


def _preview_diagnostic(code: str, *, missing_fields: list[str], sections: list[str]) -> SubscriptionChangeError:
    diagnostics = {
        "reason_code": code,
        "missing_fields": sorted(set(missing_fields)),
        "response_sections": sorted(set(sections)),
    }
    logger.warning("paddle_subscription_preview_validation %s", json.dumps(diagnostics, separators=(",", ":"), sort_keys=True))
    return SubscriptionChangeError(
        "Secure subscription preview is temporarily unavailable. Please try again later.",
        code=code,
        status_code=502,
        diagnostics=diagnostics,
    )


def _available_sections(payload: dict) -> list[str]:
    return sorted(key for key, value in payload.items() if isinstance(value, (dict, list)) or value is not None)


def _transaction_total(transaction: dict | None, section_name: str, currency_code: str) -> int:
    sections = _available_sections(transaction) if isinstance(transaction, dict) else []
    if not isinstance(transaction, dict):
        raise _preview_diagnostic(
            "preview_financial_data_incomplete",
            missing_fields=[section_name],
            sections=sections,
        )
    details = transaction.get("details") if isinstance(transaction.get("details"), dict) else {}
    if isinstance(details.get("totals"), dict):
        totals = details["totals"]
        totals_path = f"{section_name}.details.totals"
    elif isinstance(transaction.get("totals"), dict):
        totals = transaction["totals"]
        totals_path = f"{section_name}.totals"
    else:
        raise _preview_diagnostic(
            "preview_financial_data_incomplete",
            missing_fields=[f"{section_name}.totals"],
            sections=sections,
        )
    provider_currency = _clean(totals.get("currency_code")).upper()
    if provider_currency != _clean(currency_code).upper():
        raise _preview_diagnostic(
            "preview_currency_mismatch",
            missing_fields=[] if provider_currency else [f"{totals_path}.currency_code"],
            sections=[*sections, totals_path],
        )
    value = totals.get("balance")
    value_field = "balance"
    if value is None:
        value = totals.get("grand_total")
        value_field = "grand_total"
    try:
        parsed = _minor_amount(value, required=True)
    except ValueError:
        raise _preview_diagnostic(
            "preview_financial_data_incomplete",
            missing_fields=[f"{totals_path}.{value_field}"],
            sections=[*sections, totals_path],
        ) from None
    return int(parsed)


def _retained_items(provider_subscription: dict, expected_price_id: str, expected_quantity: int):
    raw_items = provider_subscription.get("items") if isinstance(provider_subscription.get("items"), list) else []
    retained = []
    expected_matches = 0
    for item in raw_items:
        price = item.get("price") if isinstance(item, dict) and isinstance(item.get("price"), dict) else {}
        price_id = _clean(price.get("id"))
        try:
            quantity = int(item.get("quantity"))
        except (TypeError, ValueError):
            quantity = 0
        if not price_id or quantity < 1:
            raise SubscriptionChangeError("Paddle subscription items require manual review.", code="invalid_provider_items", status_code=409)
        retained.append({"price_id": price_id, "quantity": quantity})
        if price_id == expected_price_id:
            expected_matches += 1
            if quantity != expected_quantity:
                raise SubscriptionChangeError("The local and Paddle branch quantities do not match.", code="provider_quantity_mismatch", status_code=409)
    if expected_matches != 1:
        raise SubscriptionChangeError("The subscribed Paddle price could not be resolved uniquely.", code="provider_price_mismatch", status_code=409)
    return retained


def _validate_provider_terms(provider_subscription: dict, price_id: str, billing_interval: str, currency_code: str):
    items = provider_subscription.get("items") if isinstance(provider_subscription.get("items"), list) else []
    matches = []
    for item in items:
        price = item.get("price") if isinstance(item, dict) and isinstance(item.get("price"), dict) else {}
        if _clean(price.get("id")) == price_id:
            matches.append(price)
    if len(matches) != 1:
        raise SubscriptionChangeError("The subscribed Paddle price could not be resolved uniquely.", code="provider_price_mismatch", status_code=409)
    price = matches[0]
    cycle = price.get("billing_cycle") if isinstance(price.get("billing_cycle"), dict) else {}
    provider_interval = {"month": "monthly", "year": "annual"}.get(_clean(cycle.get("interval")).lower(), "")
    unit_price = price.get("unit_price") if isinstance(price.get("unit_price"), dict) else {}
    provider_currency = _clean(unit_price.get("currency_code")).upper()
    if provider_interval != billing_interval or provider_currency != currency_code:
        raise SubscriptionChangeError("Paddle subscription billing terms require manual review.", code="provider_terms_mismatch", status_code=409)


def _with_quantity(items: list[dict], provider_price_id: str, quantity: int) -> list[dict]:
    return [
        {"price_id": item["price_id"], "quantity": quantity if item["price_id"] == provider_price_id else item["quantity"]}
        for item in items
    ]


def _items_signature(items: list[dict]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((_clean(item.get("price_id")), int(item.get("quantity") or 0)) for item in items))


def _retained_items_match(current_items: list[dict], changed_items: list[dict], provider_price_id: str) -> bool:
    current_retained = [item for item in current_items if item["price_id"] != provider_price_id]
    changed_retained = [item for item in changed_items if item["price_id"] != provider_price_id]
    return _items_signature(current_retained) == _items_signature(changed_retained)


def _idempotency_key(db: Session, context: ChangeContext, requested_quantity: int) -> str:
    attempt_number = db.query(models.SubscriptionChangeRequest.id).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.current_quantity == context.subscription.quantity,
        models.SubscriptionChangeRequest.requested_quantity == requested_quantity,
    ).count() + 1
    material = ":".join((
        str(context.subscription.id), str(context.subscription.quantity), str(requested_quantity),
        _clean(context.subscription.provider_subscription_id), _clean(context.subscription.provider_price_id),
        str(attempt_number),
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def preview_quantity_change(db: Session, account, requested_quantity: int):
    context = resolve_change_context(db, account, lock=True)
    try:
        requested = int(requested_quantity)
    except (TypeError, ValueError) as exc:
        raise SubscriptionChangeError("Enter a valid paid branch quantity.", code="invalid_requested_quantity") from exc
    current = int(context.subscription.quantity or 0)
    if requested < 1 or requested == current:
        message = "Choose a different branch quantity to preview a change." if requested == current else "Enter a valid paid branch quantity."
        raise SubscriptionChangeError(message, code="unchanged_quantity" if requested == current else "invalid_requested_quantity")
    existing = get_pending_change(db, context.subscription.id)
    if existing:
        raise SubscriptionChangeError("Another branch-capacity change is already in progress.", code="change_already_pending", status_code=409)
    preview_rows = _expire_stale_previews(db, context)
    fresh_previews = [row for row in preview_rows if _preview_is_fresh(row)]
    reusable = next((
        row for row in fresh_previews
        if row.status == "previewed"
        and row.current_quantity == current
        and row.requested_quantity == requested
    ), None)
    if reusable:
        return reusable
    change_type = INCREASE if requested > current else REDUCTION
    if change_type == REDUCTION and requested < context.resolution.active_branch_count:
        raise SubscriptionChangeError("Deactivate branches before reducing paid capacity below current usage.", code="below_active_branch_count", status_code=409)
    try:
        provider = paddle_client.get_subscription(
            subscription_id=context.subscription.provider_subscription_id,
            include="recurring_transaction_details",
        )
        if _clean(provider.get("id")) != context.subscription.provider_subscription_id or _clean(provider.get("status")).lower() != "active":
            raise SubscriptionChangeError("The Paddle subscription is not available for changes.", code="provider_subscription_unavailable", status_code=409)
        retained = _retained_items(provider, context.subscription.provider_price_id, current)
        _validate_provider_terms(provider, context.subscription.provider_price_id, context.subscription.billing_interval, context.subscription.currency_code)
        changed_items = _with_quantity(retained, context.subscription.provider_price_id, requested)
        mode = "prorated_immediately" if change_type == INCREASE else "prorated_next_billing_period"
        preview = paddle_client.preview_subscription_update(
            subscription_id=context.subscription.provider_subscription_id,
            items=changed_items,
            proration_billing_mode=mode,
        )
    except SubscriptionChangeError:
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        raise _safe_provider_failure(exc) from exc
    if _clean(preview.get("status")).lower() != "active":
        raise _preview_diagnostic(
            "preview_subscription_status_mismatch",
            missing_fields=[] if preview.get("status") else ["status"],
            sections=_available_sections(preview),
        )
    try:
        preview_items = _retained_items(preview, context.subscription.provider_price_id, requested)
        _validate_provider_terms(preview, context.subscription.provider_price_id, context.subscription.billing_interval, context.subscription.currency_code)
    except SubscriptionChangeError as exc:
        raise _preview_diagnostic(
            f"preview_{exc.code}",
            missing_fields=[],
            sections=_available_sections(preview),
        ) from exc
    if _items_signature(preview_items) != _items_signature(changed_items):
        raise _preview_diagnostic(
            "preview_items_mismatch",
            missing_fields=[],
            sections=_available_sections(preview),
        )
    preview_currency = _clean(preview.get("currency_code")).upper()
    if preview_currency != _clean(context.subscription.currency_code).upper():
        raise _preview_diagnostic(
            "preview_currency_mismatch",
            missing_fields=[] if preview_currency else ["currency_code"],
            sections=_available_sections(preview),
        )
    summary = preview.get("update_summary") if isinstance(preview.get("update_summary"), dict) else {}
    credit = summary.get("credit") if isinstance(summary.get("credit"), dict) else {}
    charge = summary.get("charge") if isinstance(summary.get("charge"), dict) else {}
    result = summary.get("result") if isinstance(summary.get("result"), dict) else {}
    summary_currencies = {
        _clean(section.get("currency_code")).upper()
        for section in (credit, charge, result)
        if section
    }
    currency = _clean(context.subscription.currency_code).upper()
    if not summary or not credit or not charge or not result:
        missing = []
        if not summary:
            missing.append("update_summary")
        if not credit:
            missing.append("update_summary.credit")
        if not charge:
            missing.append("update_summary.charge")
        if not result:
            missing.append("update_summary.result")
        raise _preview_diagnostic("preview_financial_data_incomplete", missing_fields=missing, sections=_available_sections(preview))
    if summary_currencies != {currency}:
        raise _preview_diagnostic(
            "preview_currency_mismatch",
            missing_fields=["update_summary.currency_code"] if "" in summary_currencies else [],
            sections=_available_sections(summary),
        )
    immediate = preview.get("immediate_transaction") if isinstance(preview.get("immediate_transaction"), dict) else None
    recurring = preview.get("recurring_transaction_details") if isinstance(preview.get("recurring_transaction_details"), dict) else None
    current_recurring = provider.get("recurring_transaction_details") if isinstance(provider.get("recurring_transaction_details"), dict) else None
    try:
        charge_minor = _minor_amount(charge.get("amount"), required=True)
        credit_minor = abs(int(_minor_amount(credit.get("amount", 0), required=True, allow_negative=True)))
        _minor_amount(result.get("amount"), required=True)
        if _clean(result.get("action")).lower() not in {"charge", "credit"}:
            raise ValueError("invalid result action")
    except ValueError:
        raise _preview_diagnostic(
            "preview_financial_data_incomplete",
            missing_fields=["update_summary.amount"],
            sections=_available_sections(summary),
        ) from None
    immediate_total = _transaction_total(immediate, "immediate_transaction", currency) if change_type == INCREASE else 0
    current_total = _transaction_total(current_recurring, "current_subscription.recurring_transaction_details", currency)
    next_total = _transaction_total(recurring, "recurring_transaction_details", currency)
    from saas.payment_service import _parse_datetime
    provider_next_billed_at = _parse_datetime(provider.get("next_billed_at"))
    effective_at = provider_next_billed_at or context.subscription.next_billed_at
    if change_type == REDUCTION and effective_at is None:
        raise SubscriptionChangeError(
            "Paddle did not return the next renewal date.",
            code="missing_provider_renewal_date",
            status_code=409,
        )
    row = models.SubscriptionChangeRequest(
        request_uuid=str(uuid.uuid4()),
        school_group_id=context.resolution.school_group_id,
        subscription_contract_id=context.contract.id,
        payment_subscription_id=context.subscription.id,
        provider_subscription_id=context.subscription.provider_subscription_id,
        requested_by_user_id=context.actor.id,
        requested_by_saas_account_id=context.account.id,
        change_type=change_type,
        current_quantity=current,
        requested_quantity=requested,
        quantity_delta=requested - current,
        current_plan_price_id=context.plan_price.id,
        provider_price_id=context.subscription.provider_price_id,
        billing_interval=context.subscription.billing_interval,
        currency_code=currency,
        effective_mode=IMMEDIATE if change_type == INCREASE else NEXT_PERIOD,
        status="previewed",
        previewed_charge_minor=charge_minor,
        previewed_credit_minor=credit_minor,
        previewed_net_minor=immediate_total,
        current_renewal_total_minor=current_total,
        next_renewal_total_minor=next_total,
        retained_items_json=json.dumps(changed_items, separators=(",", ":"), sort_keys=True),
        idempotency_key=_idempotency_key(db, context, requested),
        requested_at=_utcnow(),
        previewed_at=_utcnow(),
        effective_at=effective_at if change_type == REDUCTION else None,
    )
    for previous in fresh_previews:
        previous.status = "superseded"
        previous.failure_code = "preview_superseded"
        previous.failure_message = "A newer billing preview replaced this preview."
        _audit("branch_quantity_preview_superseded", context, previous, replacement_request_uuid=row.request_uuid)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SubscriptionChangeError("Another branch-capacity change is already in progress.", code="change_already_pending", status_code=409) from exc
    _audit("branch_quantity_preview_created", context, row, current_quantity=current, requested_quantity=requested, change_type=change_type)
    return row


def _stored_items(row) -> list[dict]:
    try:
        items = json.loads(row.retained_items_json or "")
    except (TypeError, ValueError):
        items = None
    if not isinstance(items, list) or not items:
        raise SubscriptionChangeError("The billing preview is no longer valid.", code="stale_preview", status_code=409)
    return items


def submit_quantity_change(db: Session, account, request_uuid: str):
    context = resolve_change_context(db, account, lock=True)
    row = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.request_uuid == _clean(request_uuid),
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
    ).with_for_update().one_or_none()
    if row is None:
        raise SubscriptionChangeError("Branch-capacity request not found.", code="change_not_found", status_code=404)
    if row.status in {"submitted", "payment_pending", "scheduled", "confirmed"}:
        return row
    if row.status != "previewed" or not _preview_is_fresh(row):
        if row.status in PREVIEW_ONLY_STATUSES:
            row.status = "expired"
            row.failure_code = "preview_expired"
            row.failure_message = "The billing preview expired before confirmation."
            _audit("branch_quantity_preview_expired", context, row)
        raise SubscriptionChangeError(
            "The billing preview is no longer valid. Generate a new preview to continue.",
            code="stale_preview",
            status_code=409,
        )
    _validate_preview_context(context, row)
    items = _stored_items(row)
    mode = "prorated_immediately" if row.change_type == INCREASE else "prorated_next_billing_period"
    update_attempted = False
    update_completed = False
    try:
        provider = paddle_client.get_subscription(subscription_id=row.provider_subscription_id)
        if _clean(provider.get("id")) != row.provider_subscription_id or _clean(provider.get("status")).lower() != "active":
            raise SubscriptionChangeError("The Paddle subscription changed after this preview.", code="stale_provider_subscription", status_code=409)
        current_items = _retained_items(provider, row.provider_price_id, row.current_quantity)
        _validate_provider_terms(provider, row.provider_price_id, row.billing_interval, row.currency_code)
        if not _retained_items_match(current_items, items, row.provider_price_id):
            raise SubscriptionChangeError("The Paddle subscription changed after this preview.", code="stale_provider_items", status_code=409)
        row.submitted_at = row.submitted_at or _utcnow()
        update_attempted = True
        response = paddle_client.update_subscription(
            subscription_id=row.provider_subscription_id,
            items=items,
            proration_billing_mode=mode,
            on_payment_failure="prevent_change",
        )
        update_completed = True
        if _clean(response.get("id")) != row.provider_subscription_id or _clean(response.get("status")).lower() != "active":
            raise SubscriptionChangeError("Paddle returned an unexpected subscription response.", code="provider_subscription_mismatch", status_code=409)
        observed = _retained_items(response, row.provider_price_id, row.requested_quantity)
        _validate_provider_terms(response, row.provider_price_id, row.billing_interval, row.currency_code)
        if _items_signature(observed) != _items_signature(items):
            raise SubscriptionChangeError("Paddle returned unexpected subscription items.", code="provider_items_mismatch", status_code=409)
    except SubscriptionChangeError:
        if update_completed:
            row.status = "manual_review"
            row.failure_code = "provider_update_response_mismatch"
            row.failure_message = "The subscription change requires manual review. No local branch capacity was changed."
            _audit("branch_quantity_change_manual_review", context, row, failure_code=row.failure_code)
        elif not update_attempted:
            row.status = "expired"
            row.failure_code = "preview_revalidation_failed"
            row.failure_message = "The billing preview could not be revalidated before submission."
            _audit("branch_quantity_preview_expired", context, row, failure_code=row.failure_code)
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        provider_status = getattr(exc, "status_code", None)
        outcome_unknown = update_attempted and (
            isinstance(exc, httpx.HTTPError)
            or (isinstance(provider_status, int) and provider_status >= 500)
        )
        row.status = "manual_review" if outcome_unknown else "failed"
        row.failure_code = _clean(getattr(exc, "error_code", "")) or ("provider_outcome_unknown" if outcome_unknown else "provider_update_failed")
        row.failure_message = "The subscription change requires review. No local branch capacity was changed." if outcome_unknown else "The subscription change could not be completed. No branch capacity was changed."
        _audit("branch_quantity_change_manual_review" if outcome_unknown else ("branch_quantity_increase_failed" if row.change_type == INCREASE else "branch_quantity_change_manual_review"), context, row, failure_code=row.failure_code)
        raise _safe_provider_failure(exc) from exc
    row.provider_observed_quantity = row.requested_quantity
    if row.change_type == INCREASE:
        row.status = "payment_pending"
        _audit("branch_quantity_increase_submitted", context, row, current_quantity=row.current_quantity, requested_quantity=row.requested_quantity)
    else:
        row.status = "scheduled"
        _audit("branch_quantity_reduction_scheduled", context, row, current_quantity=row.current_quantity, requested_quantity=row.requested_quantity, effective_at=row.effective_at.isoformat() if row.effective_at else None)
    return row


def cancel_scheduled_reduction(db: Session, account, request_uuid: str):
    context = resolve_change_context(db, account, lock=True)
    row = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.request_uuid == _clean(request_uuid),
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
    ).with_for_update().one_or_none()
    if row is None:
        raise SubscriptionChangeError("Scheduled reduction not found.", code="change_not_found", status_code=404)
    if row.status == "canceled":
        return row
    if row.change_type != REDUCTION or row.status != "scheduled":
        raise SubscriptionChangeError("This branch-capacity change cannot be canceled.", code="change_not_cancelable", status_code=409)
    if row.effective_at and row.effective_at <= _utcnow():
        raise SubscriptionChangeError("This scheduled reduction has reached its effective date.", code="change_already_effective", status_code=409)
    try:
        provider = paddle_client.get_subscription(subscription_id=row.provider_subscription_id)
        retained = _retained_items(provider, row.provider_price_id, row.requested_quantity)
        _validate_provider_terms(provider, row.provider_price_id, row.billing_interval, row.currency_code)
        restored = _with_quantity(retained, row.provider_price_id, row.current_quantity)
        paddle_client.preview_subscription_update(
            subscription_id=row.provider_subscription_id,
            items=restored,
            proration_billing_mode="prorated_next_billing_period",
        )
        response = paddle_client.update_subscription(
            subscription_id=row.provider_subscription_id,
            items=restored,
            proration_billing_mode="prorated_next_billing_period",
            on_payment_failure="prevent_change",
        )
        observed = _retained_items(response, row.provider_price_id, row.current_quantity)
        _validate_provider_terms(response, row.provider_price_id, row.billing_interval, row.currency_code)
        if _items_signature(observed) != _items_signature(restored):
            raise SubscriptionChangeError("Paddle returned unexpected subscription items.", code="provider_items_mismatch", status_code=409)
    except SubscriptionChangeError:
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        raise _safe_provider_failure(exc) from exc
    row.status = "canceled"
    row.canceled_at = _utcnow()
    _audit("branch_quantity_reduction_canceled", context, row, current_quantity=row.current_quantity, requested_quantity=row.requested_quantity)
    return row


def reconcile_quantity_change_webhook(db: Session, payload: dict, event_type: str):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    provider_subscription_id = _clean(data.get("id") if event_type.startswith("subscription.") else data.get("subscription_id"))
    if not provider_subscription_id:
        return None
    row = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.provider_subscription_id == provider_subscription_id,
        models.SubscriptionChangeRequest.status.in_((*UNRESOLVED_STATUSES, "confirmed")),
    ).order_by(models.SubscriptionChangeRequest.created_at.desc()).with_for_update().first()
    if row is None:
        return None
    subscription = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.id == row.payment_subscription_id
    ).with_for_update().one_or_none()
    if subscription is None:
        row.status = "manual_review"
        row.failure_code = "missing_local_subscription"
        row.failure_message = "Subscription change requires manual review."
        return {"status": "manual_review", "event_type": event_type}
    if event_type.startswith("transaction.") and _clean(data.get("origin")) != "subscription_update":
        return None
    if event_type.startswith("transaction."):
        currency = _clean(data.get("currency_code")).upper()
        if currency != row.currency_code:
            row.status = "manual_review"
            row.failure_code = "provider_currency_mismatch"
            row.failure_message = "Subscription payment requires manual review."
            return {"status": "manual_review", "event_type": event_type}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        price_ids = {
            _clean((item.get("price") or {}).get("id") or item.get("price_id"))
            for item in items if isinstance(item, dict)
        }
        if row.provider_price_id not in price_ids:
            row.status = "manual_review"
            row.failure_code = "provider_price_mismatch"
            row.failure_message = "Subscription payment requires manual review."
            return {"status": "manual_review", "event_type": event_type}
    if event_type in {"transaction.payment_failed", "transaction.past_due"} and row.change_type == INCREASE:
        row.status = "failed"
        row.failure_code = "provider_payment_failed"
        row.failure_message = "Payment was not completed. Paid branch capacity was not changed."
        audit.write_audit_event({"event_type": "branch_quantity_increase_failed", "school_group_id": row.school_group_id, "subscription_change_request_uuid": row.request_uuid, "failure_code": row.failure_code})
        return {"status": "processed", "event_type": event_type}
    if event_type == "transaction.completed" and row.change_type == INCREASE:
        if _clean(data.get("status")).lower() != "completed":
            row.status = "manual_review"
            row.failure_code = "provider_payment_state_mismatch"
            row.failure_message = "Subscription payment requires manual review."
            return {"status": "manual_review", "event_type": event_type}
        row.provider_payment_confirmed_at = row.provider_payment_confirmed_at or _utcnow()
        if row.provider_observed_quantity == row.requested_quantity:
            subscription.quantity = row.requested_quantity
            subscription.amount_minor = row.next_renewal_total_minor
            row.status = "confirmed"
            row.confirmed_at = _utcnow()
            audit.write_audit_event({"event_type": "branch_quantity_increase_confirmed", "school_group_id": row.school_group_id, "subscription_change_request_uuid": row.request_uuid, "current_quantity": row.current_quantity, "requested_quantity": row.requested_quantity})
        return {"status": "processed", "event_type": event_type}
    if not event_type.startswith("subscription."):
        return None
    try:
        retained = _retained_items(data, row.provider_price_id, row.requested_quantity)
        _validate_provider_terms(data, row.provider_price_id, row.billing_interval, row.currency_code)
    except SubscriptionChangeError:
        observed_items = data.get("items") if isinstance(data.get("items"), list) else []
        observed = None
        for item in observed_items:
            price = item.get("price") if isinstance(item, dict) and isinstance(item.get("price"), dict) else {}
            if _clean(price.get("id")) == row.provider_price_id:
                try:
                    observed = int(item.get("quantity"))
                except (TypeError, ValueError):
                    pass
        row.provider_observed_quantity = observed
        row.status = "manual_review"
        row.failure_code = "provider_quantity_mismatch"
        row.failure_message = "Subscription quantity requires manual review."
        audit.write_audit_event({"event_type": "branch_quantity_change_manual_review", "school_group_id": row.school_group_id, "subscription_change_request_uuid": row.request_uuid, "observed_quantity": observed})
        return {"status": "manual_review", "event_type": event_type}
    if _items_signature(retained) != _items_signature(_stored_items(row)):
        row.status = "manual_review"
        row.failure_code = "provider_items_mismatch"
        row.failure_message = "Subscription items require manual review."
        return {"status": "manual_review", "event_type": event_type}
    row.provider_observed_quantity = row.requested_quantity
    period = data.get("current_billing_period") if isinstance(data.get("current_billing_period"), dict) else {}
    from saas.payment_service import _parse_datetime
    period_start = _parse_datetime(period.get("starts_at"))
    period_end = _parse_datetime(period.get("ends_at"))
    next_billed_at = _parse_datetime(data.get("next_billed_at"))
    if row.change_type == INCREASE:
        if row.provider_payment_confirmed_at:
            subscription.quantity = row.requested_quantity
            subscription.amount_minor = row.next_renewal_total_minor
            row.status = "confirmed"
            row.confirmed_at = _utcnow()
            audit.write_audit_event({"event_type": "branch_quantity_increase_confirmed", "school_group_id": row.school_group_id, "subscription_change_request_uuid": row.request_uuid, "current_quantity": row.current_quantity, "requested_quantity": row.requested_quantity})
        else:
            row.status = "payment_pending"
    else:
        effective = row.effective_at
        if effective and period_start and period_start >= effective:
            subscription.quantity = row.requested_quantity
            subscription.amount_minor = row.next_renewal_total_minor
            row.status = "confirmed"
            row.confirmed_at = _utcnow()
            audit.write_audit_event({"event_type": "branch_quantity_reduction_effective", "school_group_id": row.school_group_id, "subscription_change_request_uuid": row.request_uuid, "current_quantity": row.current_quantity, "requested_quantity": row.requested_quantity})
        else:
            row.status = "scheduled"
    subscription.current_period_start = period_start or subscription.current_period_start
    subscription.current_period_end = period_end or subscription.current_period_end
    subscription.next_billed_at = next_billed_at or subscription.next_billed_at
    return {"status": "processed", "event_type": event_type}
