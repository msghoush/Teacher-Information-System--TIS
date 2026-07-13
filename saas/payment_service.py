import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from saas import branch_pricing_quote_service, models, paddle_client, service

PROVIDER = "paddle"
CHECKOUT_READY = "checkout_ready"
CHECKOUT_STARTED = "checkout_started"
PAYMENT_PROCESSING = "payment_processing"
PAYMENT_CONFIRMED = "payment_confirmed"
READY_FOR_PROVISIONING = "ready_for_provisioning"
PAYMENT_FAILED = "payment_failed"
PAYMENT_CANCELLED = "payment_cancelled"
PAYMENT_REFUNDED = "payment_refunded"

PAYMENT_PENDING = "pending"
PAYMENT_STATUS_PROCESSING = "processing"
PAYMENT_PAID = "paid"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_CANCELLED = "cancelled"
PAYMENT_STATUS_REFUNDED = "refunded"

CHECKOUT_SESSION_READY = "ready"
CHECKOUT_SESSION_STARTED = "started"
CHECKOUT_SESSION_PROCESSING = "processing"
CHECKOUT_SESSION_COMPLETED = "completed"
CHECKOUT_SESSION_FAILED = "failed"
CHECKOUT_SESSION_CANCELLED = "cancelled"

ATTEMPT_STATUS_CHECKOUT_STARTED = "checkout_started"
ATTEMPT_STATUS_PAYMENT_PROCESSING = "payment_processing"
ATTEMPT_STATUS_PAYMENT_CONFIRMED = "payment_confirmed"
ATTEMPT_STATUS_PAYMENT_FAILED = "payment_failed"
ATTEMPT_STATUS_PAYMENT_CANCELLED = "payment_cancelled"
ATTEMPT_STATUS_PAYMENT_REFUNDED = "payment_refunded"
ATTEMPT_STATUS_MANUAL_RECONCILIATION = "manual_reconciliation"
CUSTOMER_SAFE_PAYMENT_CONFIG_MESSAGE = (
    "Secure payment is temporarily unavailable for this subscription option. Please contact TIS support."
)

logger = logging.getLogger(__name__)


class MissingPaddlePriceConfiguration(ValueError):
    def __init__(self, *, plan_code: str, billing_interval: str, currency_code: str = "USD"):
        self.plan_code = plan_code
        self.billing_interval = billing_interval
        self.currency_code = currency_code
        super().__init__(
            "Missing Paddle provider_price_id "
            f"for plan_code={plan_code or 'unknown'} "
            f"billing_interval={billing_interval or 'unknown'} "
            f"currency_code={currency_code or 'unknown'}."
        )


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def _parse_datetime(value):
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)
    except ValueError:
        return None


def _json(value) -> str:
    return json.dumps(value or {}, separators=(",", ":"))


def _payment_link_base_url(request: Request) -> str:
    configured = str(os.environ.get("PADDLE_CHECKOUT_BASE_URL") or "").strip()
    if configured:
        return configured
    public_base = service.email_public_base_url(request)
    return public_base


def _webhook_secret() -> str:
    value = str(os.environ.get("PADDLE_WEBHOOK_SECRET") or "").strip()
    if not value:
        raise ValueError("Paddle webhook secret is not configured.")
    return value


def _webhook_tolerance_seconds() -> int:
    raw_value = str(os.environ.get("PADDLE_WEBHOOK_TOLERANCE_SECONDS") or "").strip()
    try:
        parsed = int(raw_value or "5")
    except ValueError:
        parsed = 5
    return max(1, parsed)


def get_payment_customer(db: Session, organization):
    return db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.pending_organization_id == organization.id,
        models.PaymentCustomer.provider == PROVIDER,
    ).order_by(models.PaymentCustomer.updated_at.desc(), models.PaymentCustomer.id.desc()).first()


def _clean_text(value) -> str:
    return str(value or "").strip()


def _account_email(account) -> str:
    return _clean_text(getattr(account, "email", "")).lower()


def _remote_customer_context_matches(remote_customer: dict, organization, account) -> bool:
    if not isinstance(remote_customer, dict):
        return False
    custom_data = remote_customer.get("custom_data")
    if not isinstance(custom_data, dict):
        return False
    remote_account_uuid = _clean_text(custom_data.get("saas_account_uuid"))
    remote_organization_uuid = _clean_text(custom_data.get("pending_organization_uuid"))
    account_uuid = _clean_text(getattr(account, "account_uuid", ""))
    organization_uuid = _clean_text(getattr(organization, "organization_uuid", ""))
    return bool(
        (remote_account_uuid and account_uuid and remote_account_uuid == account_uuid)
        or (remote_organization_uuid and organization_uuid and remote_organization_uuid == organization_uuid)
    )


def _select_usable_remote_customer(remote_customers: list[dict], organization, account) -> dict | None:
    matches = []
    exact_email_candidates = []
    email = _account_email(account)
    for remote_customer in remote_customers or []:
        if not isinstance(remote_customer, dict):
            continue
        if _clean_text(remote_customer.get("status")).lower() not in {"", "active"}:
            continue
        if _clean_text(remote_customer.get("email")).lower() != email:
            continue
        if not _clean_text(remote_customer.get("id")):
            continue
        exact_email_candidates.append(remote_customer)
        if _remote_customer_context_matches(remote_customer, organization, account):
            matches.append(remote_customer)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1 or exact_email_candidates:
        raise ValueError("Secure payment is temporarily unavailable for this account. Please contact TIS support.")
    return None


def _find_local_payment_customer_by_account(db: Session, account):
    email = _account_email(account)
    if not email:
        return None
    return db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account.id,
        models.PaymentCustomer.provider == PROVIDER,
        func.lower(models.PaymentCustomer.email) == email,
    ).order_by(models.PaymentCustomer.updated_at.desc(), models.PaymentCustomer.id.desc()).first()


def _persist_payment_customer_link(db: Session, *, organization, account, remote_customer: dict):
    existing = get_payment_customer(db, organization)
    if existing:
        return existing
    row = models.PaymentCustomer(
        pending_organization_id=organization.id,
        saas_account_id=account.id,
        provider=PROVIDER,
        provider_customer_id=_clean_text(remote_customer.get("id")),
        email=_clean_text(remote_customer.get("email") or getattr(account, "email", "")).lower() or None,
        name=_clean_text(remote_customer.get("name") or "").strip() or None,
        country_code=_clean_text(getattr(organization, "country_code", "")).upper() or None,
        status=_clean_text(remote_customer.get("status") or "active") or "active",
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def _lookup_remote_payment_customer_by_email(organization, account):
    remote_customers = paddle_client.list_customers_by_email(_account_email(account))
    return _select_usable_remote_customer(remote_customers, organization, account)


def _is_customer_email_conflict(exc: paddle_client.PaddleAPIError) -> bool:
    detail = _clean_text(getattr(exc, "detail", "") or str(exc)).lower()
    code = _clean_text(getattr(exc, "error_code", "")).lower()
    return (
        "email" in detail
        and "conflict" in detail
        and "customer" in detail
    ) or (
        "customer" in code
        and "email" in code
        and "conflict" in code
    )


def get_current_payment_attempt(db: Session, organization):
    return db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.pending_organization_id == organization.id,
        models.PaymentAttempt.provider == PROVIDER,
    ).order_by(models.PaymentAttempt.updated_at.desc(), models.PaymentAttempt.id.desc()).first()


def get_payment_subscription(db: Session, organization):
    return db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.pending_organization_id == organization.id,
        models.PaymentSubscription.provider == PROVIDER,
    ).order_by(models.PaymentSubscription.updated_at.desc(), models.PaymentSubscription.id.desc()).first()


def list_payment_attempts(db: Session):
    return db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.provider == PROVIDER
    ).order_by(models.PaymentAttempt.updated_at.desc(), models.PaymentAttempt.id.desc()).all()


def _current_plan_price(db: Session, organization):
    if not getattr(organization, "selected_plan_id", None) or not getattr(organization, "selected_billing_interval", None):
        return None
    return db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == organization.selected_plan_id,
        models.SubscriptionPlanPrice.billing_interval == organization.selected_billing_interval,
        models.SubscriptionPlanPrice.currency_code == "USD",
        models.SubscriptionPlanPrice.is_active == True,
    ).order_by(
        models.SubscriptionPlanPrice.plan_version.desc(),
        models.SubscriptionPlanPrice.id.desc(),
    ).first()


def _ensure_checkout_launchable(db: Session, organization):
    if str(getattr(organization, "status", "") or "").strip().lower() != service.READY_FOR_CHECKOUT_STATUS:
        raise ValueError("Organization setup must reach ready_for_checkout before payment can begin.")
    if str(getattr(organization, "billing_status", "") or "").strip().lower() not in {
        CHECKOUT_READY,
        CHECKOUT_STARTED,
        PAYMENT_PROCESSING,
        PAYMENT_FAILED,
        PAYMENT_CANCELLED,
    }:
        raise ValueError("Checkout is not ready for launch yet.")
    if str(getattr(organization, "payment_status", "") or "").strip().lower() == PAYMENT_PAID:
        raise ValueError("This organization already has a confirmed payment.")
    checkout_session = db.query(models.CheckoutSession).filter(
        models.CheckoutSession.pending_organization_id == organization.id
    ).order_by(models.CheckoutSession.updated_at.desc(), models.CheckoutSession.id.desc()).first()
    if not checkout_session:
        raise ValueError("Prepare checkout before launching Paddle checkout.")
    return checkout_session


def _find_or_create_payment_customer(db: Session, organization, account):
    existing = get_payment_customer(db, organization)
    if existing:
        return existing
    existing_for_account = _find_local_payment_customer_by_account(db, account)
    if existing_for_account:
        return existing_for_account
    remote_existing = _lookup_remote_payment_customer_by_email(organization, account)
    if remote_existing:
        return _persist_payment_customer_link(
            db,
            organization=organization,
            account=account,
            remote_customer=remote_existing,
        )
    full_name = " ".join(
        part for part in [str(getattr(account, "first_name", "") or "").strip(), str(getattr(account, "last_name", "") or "").strip()] if part
    ).strip() or str(getattr(organization, "organization_name", "") or "").strip()
    try:
        remote = paddle_client.create_customer(
            email=str(getattr(account, "email", "") or "").strip(),
            name=full_name,
            custom_data={
                "pending_organization_uuid": str(getattr(organization, "organization_uuid", "") or ""),
                "saas_account_uuid": str(getattr(account, "account_uuid", "") or ""),
            },
        )
    except paddle_client.PaddleAPIError as exc:
        if not _is_customer_email_conflict(exc):
            raise
        remote = _lookup_remote_payment_customer_by_email(organization, account)
        if not remote:
            raise ValueError("Secure payment is temporarily unavailable for this account. Please contact TIS support.") from exc
    return _persist_payment_customer_link(
        db,
        organization=organization,
        account=account,
        remote_customer=remote,
    )


def build_checkout_launch_context(db: Session, organization):
    checkout_session = _ensure_checkout_launchable(db, organization)
    quote = branch_pricing_quote_service.require_ready_quote(
        branch_pricing_quote_service.build_quote(db, organization)
    )
    if str(getattr(checkout_session, "quote_fingerprint", "") or "") != quote.fingerprint:
        checkout_session.status = "stale"
        checkout_session.abandoned_at = _utcnow()
        raise ValueError("Subscription details changed. Please continue again to refresh Secure Payment.")
    plan_price = _current_plan_price(db, organization)
    if not plan_price or not str(getattr(plan_price, "provider_price_id", "") or "").strip():
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == getattr(organization, "selected_plan_id", None)
        ).first()
        plan_code = str(getattr(plan, "plan_code", "") or "").strip()
        billing_interval = str(getattr(organization, "selected_billing_interval", "") or "").strip()
        logger.error(
            "Missing Paddle provider_price_id for plan_code=%s billing_interval=%s currency_code=USD",
            plan_code or "unknown",
            billing_interval or "unknown",
        )
        raise MissingPaddlePriceConfiguration(
            plan_code=plan_code,
            billing_interval=billing_interval,
            currency_code="USD",
        )
    selection = db.query(models.PendingOrganizationPlanSelection).filter(
        models.PendingOrganizationPlanSelection.id == checkout_session.plan_selection_id
    ).first()
    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == organization.id
    ).order_by(models.SubscriptionContract.updated_at.desc(), models.SubscriptionContract.id.desc()).first()
    if not selection or not contract:
        raise ValueError("Selected plan contract could not be prepared.")
    expected_quantity = int(quote.quantity or 0)
    expected_total = int(quote.total_amount_minor or 0)
    expected_provider_price_id = _clean_text(quote.provider_price_id)
    snapshots_match = (
        expected_quantity >= 1
        and expected_total == int(quote.unit_amount_minor or 0) * expected_quantity
        and int(getattr(organization, "selected_plan_id", 0) or 0) == int(quote.plan_id or 0)
        and _clean_text(getattr(organization, "selected_billing_interval", "")).lower() == quote.billing_interval
        and int(getattr(plan_price, "id", 0) or 0) == int(quote.plan_price_id or 0)
        and _clean_text(getattr(plan_price, "provider_price_id", "")) == expected_provider_price_id
        and int(getattr(plan_price, "amount_minor", 0) or 0) == int(quote.unit_amount_minor or 0)
        and int(getattr(selection, "plan_id", 0) or 0) == int(quote.plan_id or 0)
        and _clean_text(getattr(selection, "billing_interval", "")).lower() == quote.billing_interval
        and int(getattr(selection, "billable_branch_count", 0) or 0) == expected_quantity
        and int(getattr(selection, "quoted_base_amount_minor", 0) or 0) == expected_total
        and _clean_text(getattr(selection, "quote_fingerprint", "")) == quote.fingerprint
        and int(getattr(contract, "plan_id", 0) or 0) == int(quote.plan_id or 0)
        and _clean_text(getattr(contract, "billing_interval", "")).lower() == quote.billing_interval
        and int(getattr(contract, "billable_branch_count", 0) or 0) == expected_quantity
        and int(getattr(contract, "quoted_base_amount_minor", 0) or 0) == expected_total
        and _clean_text(getattr(contract, "quote_fingerprint", "")) == quote.fingerprint
        and int(getattr(checkout_session, "plan_selection_id", 0) or 0) == int(selection.id)
        and _clean_text(getattr(checkout_session, "provider_price_id", "")) == expected_provider_price_id
        and _clean_text(getattr(checkout_session, "billing_interval", "")).lower() == quote.billing_interval
        and int(getattr(checkout_session, "billable_branch_count", 0) or 0) == expected_quantity
        and int(getattr(checkout_session, "quoted_base_amount_minor", 0) or 0) == expected_total
    )
    if not snapshots_match:
        checkout_session.status = "stale"
        checkout_session.abandoned_at = _utcnow()
        raise ValueError("Subscription details changed. Please continue again to refresh Secure Payment.")
    return checkout_session, selection, contract, plan_price, quote


def launch_checkout(db: Session, organization, account, request: Request):
    checkout_session, selection, contract, plan_price, quote = build_checkout_launch_context(db, organization)
    existing_checkout_url = _clean_text(getattr(checkout_session, "checkout_url", ""))
    if _clean_text(getattr(checkout_session, "status", "")).lower() == CHECKOUT_SESSION_STARTED and existing_checkout_url:
        existing_attempt = None
        if getattr(checkout_session, "last_payment_attempt_id", None):
            existing_attempt = db.query(models.PaymentAttempt).filter(
                models.PaymentAttempt.id == checkout_session.last_payment_attempt_id
            ).first()
        if not existing_attempt or not (
            _clean_text(getattr(existing_attempt, "provider_price_id", "")) == quote.provider_price_id
            and int(getattr(existing_attempt, "quantity", 0) or 0) == quote.quantity
            and int(getattr(existing_attempt, "unit_amount_minor", 0) or 0) == quote.unit_amount_minor
            and int(getattr(existing_attempt, "amount_minor", 0) or 0) == quote.total_amount_minor
            and _clean_text(getattr(existing_attempt, "billing_interval", "")).lower() == quote.billing_interval
            and _clean_text(getattr(existing_attempt, "currency_code", "")).upper() == quote.currency_code
            and _clean_text(getattr(existing_attempt, "quote_fingerprint", "")) == quote.fingerprint
        ):
            checkout_session.status = "stale"
            checkout_session.abandoned_at = _utcnow()
            raise ValueError("Subscription details changed. Please continue again to refresh Secure Payment.")
        return {
            "attempt": existing_attempt,
            "checkout_url": existing_checkout_url,
            "transaction": {},
        }
    payment_customer = _find_or_create_payment_customer(db, organization, account)
    attempt = models.PaymentAttempt(
        pending_organization_id=organization.id,
        checkout_session_id=checkout_session.id,
        plan_selection_id=selection.id,
        payment_customer_id=payment_customer.id,
        provider=PROVIDER,
        attempt_uuid=str(uuid.uuid4()),
        status=ATTEMPT_STATUS_CHECKOUT_STARTED,
        provider_price_id=quote.provider_price_id,
        currency_code=quote.currency_code,
        quantity=quote.quantity,
        unit_amount_minor=quote.unit_amount_minor,
        amount_minor=quote.total_amount_minor,
        billing_interval=quote.billing_interval,
        quote_fingerprint=quote.fingerprint,
        started_at=_utcnow(),
        expires_at=_utcnow() + timedelta(hours=2),
    )
    db.add(attempt)
    db.flush()

    transaction = paddle_client.create_transaction(
        customer_id=payment_customer.provider_customer_id,
        price_id=quote.provider_price_id,
        quantity=quote.quantity,
        custom_data={
            "pending_organization_uuid": organization.organization_uuid,
            "payment_attempt_uuid": attempt.attempt_uuid,
            "checkout_session_id": checkout_session.id,
            "subscription_contract_id": contract.id,
            "quote_fingerprint": quote.fingerprint,
        },
        checkout_url=_payment_link_base_url(request),
    )

    checkout_data = transaction.get("checkout") or {}
    attempt.provider_checkout_id = str((checkout_data.get("id") or transaction.get("id") or "")).strip() or None
    attempt.provider_transaction_id = str(transaction.get("id") or "").strip() or None
    attempt.currency_code = str(transaction.get("currency_code") or attempt.currency_code or "USD").strip() or "USD"
    checkout_session.status = CHECKOUT_SESSION_STARTED
    checkout_session.provider = PROVIDER
    checkout_session.provider_checkout_id = attempt.provider_checkout_id or attempt.provider_transaction_id
    checkout_session.checkout_url = str(checkout_data.get("url") or "").strip() or None
    checkout_session.provider_price_id = str(plan_price.provider_price_id or "").strip() or None
    checkout_session.last_payment_attempt_id = attempt.id
    organization.billing_status = CHECKOUT_STARTED
    organization.payment_status = PAYMENT_PENDING
    organization.last_payment_attempt_id = attempt.id
    contract.payment_status = PAYMENT_PENDING
    contract.payment_provider = PROVIDER
    service.log_pending_event(
        db,
        organization=organization,
        account=account,
        event_type="checkout_started",
        details={
            "payment_attempt_uuid": attempt.attempt_uuid,
            "provider_transaction_id": attempt.provider_transaction_id,
        },
    )
    return {
        "attempt": attempt,
        "checkout_url": str(checkout_session.checkout_url or "").strip(),
        "transaction": transaction,
    }


def parse_signature_header(signature_header: str) -> tuple[str, str]:
    parts = {}
    for chunk in str(signature_header or "").split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[str(key or "").strip()] = str(value or "").strip()
    timestamp = str(parts.get("ts") or "").strip()
    signature = str(parts.get("h1") or "").strip()
    if not timestamp or not signature:
        raise ValueError("Paddle-Signature header is invalid.")
    return timestamp, signature


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> None:
    timestamp, signature = parse_signature_header(signature_header)
    try:
        event_time = int(timestamp)
    except ValueError as exc:
        raise ValueError("Paddle-Signature timestamp is invalid.") from exc
    if abs(int(time.time()) - event_time) > _webhook_tolerance_seconds():
        raise ValueError("Paddle webhook timestamp is outside the allowed tolerance.")
    signed_payload = f"{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(_webhook_secret().encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Paddle webhook signature verification failed.")


def _record_webhook(
    db: Session,
    *,
    payload: dict,
    raw_body: bytes,
    headers: dict,
    signature_valid: bool,
    processing_status: str,
    processing_error: str = "",
):
    row = models.PaymentWebhook(
        provider=PROVIDER,
        provider_event_id=str(payload.get("event_id") or "").strip() or None,
        event_type=str(payload.get("event_type") or "").strip() or None,
        signature_valid=bool(signature_valid),
        delivery_attempt=int(payload.get("delivery_attempt") or 1),
        payload_hash=hashlib.sha256(raw_body).hexdigest(),
        headers_json=_json(headers),
        payload_json=raw_body.decode("utf-8", errors="replace"),
        received_at=_utcnow(),
        processing_status=processing_status,
        processing_error=str(processing_error or "").strip() or None,
    )
    db.add(row)
    db.flush()
    return row


def _parse_payload(raw_body: bytes) -> dict:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except ValueError as exc:
        raise ValueError("Webhook payload is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Webhook payload is invalid.")
    return payload


def _find_attempt_by_payload(db: Session, payload: dict):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    custom_data = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    event_type = str(payload.get("event_type") or "").strip().lower()
    attempt_uuid = str(custom_data.get("payment_attempt_uuid") or "").strip()
    transaction_id = str(data.get("id") or "").strip()
    if event_type.startswith("subscription."):
        transaction_id = str(data.get("transaction_id") or "").strip()
    subscription_id = (
        str(data.get("id") or "").strip()
        if event_type.startswith("subscription.")
        else str(data.get("subscription_id") or "").strip()
    )
    if attempt_uuid:
        attempt = db.query(models.PaymentAttempt).filter(
            models.PaymentAttempt.attempt_uuid == attempt_uuid
        ).first()
        if attempt:
            return attempt
    if transaction_id:
        attempt = db.query(models.PaymentAttempt).filter(
            models.PaymentAttempt.provider_transaction_id == transaction_id
        ).order_by(models.PaymentAttempt.updated_at.desc(), models.PaymentAttempt.id.desc()).first()
        if attempt:
            return attempt
    if subscription_id:
        attempt = db.query(models.PaymentAttempt).filter(
            models.PaymentAttempt.provider_subscription_id == subscription_id
        ).order_by(models.PaymentAttempt.updated_at.desc(), models.PaymentAttempt.id.desc()).first()
        if attempt:
            return attempt
    pending_uuid = str(custom_data.get("pending_organization_uuid") or "").strip()
    if pending_uuid:
        organization = db.query(models.PendingOrganization).filter(
            models.PendingOrganization.organization_uuid == pending_uuid
        ).first()
        if organization:
            return get_current_payment_attempt(db, organization)
    return None


def _positive_integer(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _minor_amount(value) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _normalized_paddle_interval(value) -> str:
    cleaned = _clean_text(value).lower()
    return {"month": "monthly", "year": "annual"}.get(cleaned, cleaned)


def _paddle_item_summary(data: dict, *, require_reported_total: bool) -> dict:
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if len(items) != 1 or not isinstance(items[0], dict):
        raise ValueError("Payment details require manual reconciliation.")
    item = items[0]
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    unit_price = price.get("unit_price") if isinstance(price.get("unit_price"), dict) else {}
    billing_cycle = price.get("billing_cycle") if isinstance(price.get("billing_cycle"), dict) else {}
    quantity = _positive_integer(item.get("quantity"))
    unit_amount_minor = _minor_amount(unit_price.get("amount"))
    provider_price_id = _clean_text(price.get("id"))
    currency_code = _clean_text(unit_price.get("currency_code")).upper()
    billing_interval = _normalized_paddle_interval(billing_cycle.get("interval"))
    if not all((provider_price_id, quantity, unit_amount_minor is not None, currency_code, billing_interval)):
        raise ValueError("Payment details require manual reconciliation.")

    calculated_amount_minor = int(unit_amount_minor) * int(quantity)
    reported_amount_minor = None
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    line_items = details.get("line_items") if isinstance(details.get("line_items"), list) else []
    if line_items:
        matching = [
            line for line in line_items
            if isinstance(line, dict) and _clean_text(line.get("price_id")) == provider_price_id
        ]
        if len(matching) != 1:
            raise ValueError("Payment details require manual reconciliation.")
        line = matching[0]
        totals = line.get("totals") if isinstance(line.get("totals"), dict) else {}
        reported_amount_minor = _minor_amount(totals.get("subtotal"))
        line_quantity = _positive_integer(line.get("quantity"))
        if line_quantity != quantity:
            raise ValueError("Payment details require manual reconciliation.")
    if require_reported_total and reported_amount_minor is None:
        raise ValueError("Payment details require manual reconciliation.")
    if reported_amount_minor is not None and reported_amount_minor != calculated_amount_minor:
        raise ValueError("Payment details require manual reconciliation.")
    totals = details.get("totals") if isinstance(details.get("totals"), dict) else {}
    totals_currency = _clean_text(totals.get("currency_code")).upper()
    if totals_currency and totals_currency != currency_code:
        raise ValueError("Payment details require manual reconciliation.")
    return {
        "provider_price_id": provider_price_id,
        "quantity": quantity,
        "unit_amount_minor": unit_amount_minor,
        "amount_minor": reported_amount_minor if reported_amount_minor is not None else calculated_amount_minor,
        "currency_code": currency_code,
        "billing_interval": billing_interval,
    }


def _validate_paid_snapshot(db: Session, organization, contract, attempt, summary: dict) -> str:
    try:
        quote = branch_pricing_quote_service.require_ready_quote(
            branch_pricing_quote_service.build_quote(db, organization)
        )
    except ValueError:
        return "The current subscription quote is not valid."
    expected = {
        "provider_price_id": _clean_text(getattr(attempt, "provider_price_id", "")),
        "quantity": int(getattr(attempt, "quantity", 0) or 0),
        "unit_amount_minor": int(getattr(attempt, "unit_amount_minor", 0) or 0),
        "amount_minor": int(getattr(attempt, "amount_minor", 0) or 0),
        "currency_code": _clean_text(getattr(attempt, "currency_code", "")).upper(),
        "billing_interval": _clean_text(getattr(attempt, "billing_interval", "")).lower(),
    }
    if any(summary.get(key) != value for key, value in expected.items()):
        return "Paddle payment details do not match the checkout attempt."
    if not contract or not (
        int(getattr(contract, "plan_id", 0) or 0) == int(quote.plan_id or 0)
        and _clean_text(getattr(contract, "billing_interval", "")).lower() == quote.billing_interval
        and int(getattr(contract, "billable_branch_count", 0) or 0) == quote.quantity
        and int(getattr(contract, "quoted_base_amount_minor", 0) or 0) == quote.total_amount_minor
        and _clean_text(getattr(contract, "quote_fingerprint", "")) == quote.fingerprint
        and _clean_text(getattr(attempt, "quote_fingerprint", "")) == quote.fingerprint
    ):
        return "The paid checkout does not match the current subscription quote."
    return ""


def _mark_manual_reconciliation(db: Session, webhook_row, organization, contract, attempt, *, reason: str):
    safe_reason = "Payment details require manual reconciliation."
    webhook_row.processing_status = "manual_review"
    webhook_row.processing_error = safe_reason
    webhook_row.processed_at = _utcnow()
    attempt.status = ATTEMPT_STATUS_MANUAL_RECONCILIATION
    attempt.failure_reason = safe_reason
    organization.payment_status = "manual_reconciliation"
    organization.billing_status = "payment_reconciliation_required"
    if contract:
        contract.payment_status = "manual_reconciliation"
    logger.error("Paddle payment reconciliation blocked activation: %s", reason)
    service.log_pending_event(
        db,
        organization=organization,
        event_type="payment_reconciliation_required",
        details={"reason": safe_reason},
    )
    return {"status": "manual_review", "event_type": _clean_text(webhook_row.event_type).lower()}


def _upsert_subscription_from_payload(
    db: Session, organization, contract, payment_customer, payload: dict, attempt=None, item_summary: dict | None = None
):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    provider_subscription_id = str(data.get("id") or "").strip()
    if not provider_subscription_id:
        return None
    row = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.provider_subscription_id == provider_subscription_id
    ).first()
    if not row:
        row = models.PaymentSubscription(
            pending_organization_id=organization.id,
            subscription_contract_id=contract.id,
            payment_customer_id=getattr(payment_customer, "id", None),
            provider=PROVIDER,
            provider_subscription_id=provider_subscription_id,
            provider_price_id=None,
            plan_id=contract.plan_id,
            billing_interval=contract.billing_interval,
            currency_code=getattr(attempt, "currency_code", None),
            quantity=int(getattr(attempt, "quantity", 0) or 0),
            unit_amount_minor=getattr(attempt, "unit_amount_minor", None),
            amount_minor=getattr(attempt, "amount_minor", None),
            quote_fingerprint=getattr(attempt, "quote_fingerprint", None),
            status="pending",
        )
        db.add(row)
        db.flush()
    row.payment_customer_id = getattr(payment_customer, "id", None)
    row.plan_id = contract.plan_id
    row.billing_interval = contract.billing_interval
    row.status = str(data.get("status") or row.status or "pending").strip() or "pending"
    if item_summary:
        row.provider_price_id = item_summary["provider_price_id"]
        row.quantity = item_summary["quantity"]
        row.unit_amount_minor = item_summary["unit_amount_minor"]
        row.amount_minor = item_summary["amount_minor"]
        row.currency_code = item_summary["currency_code"]
        row.billing_interval = item_summary["billing_interval"]
        row.quote_fingerprint = _clean_text(getattr(attempt, "quote_fingerprint", "")) or row.quote_fingerprint
    period = data.get("current_billing_period") if isinstance(data.get("current_billing_period"), dict) else {}
    row.current_period_start = _parse_datetime(period.get("starts_at")) or row.current_period_start
    row.current_period_end = _parse_datetime(period.get("ends_at")) or row.current_period_end
    row.next_billed_at = _parse_datetime(data.get("next_billed_at")) or row.next_billed_at
    row.cancel_at_period_end = bool(data.get("scheduled_change"))
    if row.status == "canceled":
        row.cancelled_at = _parse_datetime(data.get("canceled_at")) or row.cancelled_at or _utcnow()
    if attempt and not attempt.provider_subscription_id:
        attempt.provider_subscription_id = provider_subscription_id
    return row


def _apply_attempt_state(db: Session, attempt, *, status: str, failure_reason: str = "", provider_subscription_id: str = ""):
    if not attempt:
        return
    attempt.status = status
    if provider_subscription_id:
        attempt.provider_subscription_id = provider_subscription_id
    if status == ATTEMPT_STATUS_PAYMENT_CONFIRMED:
        attempt.completed_at = attempt.completed_at or _utcnow()
    if status == ATTEMPT_STATUS_PAYMENT_FAILED:
        attempt.failed_at = _utcnow()
        attempt.failure_reason = str(failure_reason or "").strip() or None
    if status == ATTEMPT_STATUS_PAYMENT_CANCELLED:
        attempt.cancelled_at = _utcnow()


def process_webhook(db: Session, *, raw_body: bytes, headers: dict):
    signature_header = str(headers.get("paddle-signature") or headers.get("Paddle-Signature") or "").strip()
    payload = _parse_payload(raw_body)

    existing = None
    event_id = str(payload.get("event_id") or "").strip()
    if event_id:
        existing = db.query(models.PaymentWebhook).filter(
            models.PaymentWebhook.provider_event_id == event_id
        ).first()
    if existing and str(existing.processing_status or "").strip().lower() in {"processed", "duplicate"}:
        return {"status": "duplicate", "event_id": event_id}

    try:
        verify_webhook_signature(raw_body, signature_header)
    except ValueError as exc:
        _record_webhook(
            db,
            payload=payload,
            raw_body=raw_body,
            headers=headers,
            signature_valid=False,
            processing_status="rejected",
            processing_error=str(exc),
        )
        raise

    webhook_row = _record_webhook(
        db,
        payload=payload,
        raw_body=raw_body,
        headers=headers,
        signature_valid=True,
        processing_status="processing",
    )

    event_type = str(payload.get("event_type") or "").strip().lower()
    attempt = _find_attempt_by_payload(db, payload)
    if not attempt:
        webhook_row.processing_status = "ignored"
        webhook_row.processed_at = _utcnow()
        return {"status": "ignored", "event_type": event_type}

    organization = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == attempt.pending_organization_id
    ).first()
    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == organization.id
    ).order_by(models.SubscriptionContract.updated_at.desc(), models.SubscriptionContract.id.desc()).first()
    payment_customer = None
    if attempt.payment_customer_id:
        payment_customer = db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.id == attempt.payment_customer_id
        ).first()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    provider_subscription_id = str(data.get("subscription_id") or "").strip()
    if event_type.startswith("subscription."):
        provider_subscription_id = str(data.get("id") or "").strip() or provider_subscription_id

    if str(data.get("customer_id") or "").strip() and payment_customer:
        payment_customer.provider_customer_id = str(data.get("customer_id") or payment_customer.provider_customer_id).strip()

    if event_type == "transaction.paid":
        _apply_attempt_state(db, attempt, status=ATTEMPT_STATUS_PAYMENT_PROCESSING, provider_subscription_id=provider_subscription_id)
        organization.payment_status = PAYMENT_STATUS_PROCESSING
        organization.billing_status = PAYMENT_PROCESSING
        organization.last_payment_attempt_id = attempt.id
        checkout_session = db.query(models.CheckoutSession).filter(models.CheckoutSession.id == attempt.checkout_session_id).first()
        if checkout_session:
            checkout_session.status = CHECKOUT_SESSION_PROCESSING
        if contract:
            contract.payment_status = PAYMENT_STATUS_PROCESSING
            contract.payment_provider = PROVIDER
        service.log_pending_event(db, organization=organization, event_type="payment_processing", details={"provider_transaction_id": str(data.get("id") or "")})
    elif event_type == "transaction.completed":
        try:
            item_summary = _paddle_item_summary(data, require_reported_total=True)
        except ValueError as exc:
            return _mark_manual_reconciliation(
                db, webhook_row, organization, contract, attempt, reason=str(exc)
            )
        reconciliation_error = _validate_paid_snapshot(db, organization, contract, attempt, item_summary)
        if reconciliation_error:
            return _mark_manual_reconciliation(
                db, webhook_row, organization, contract, attempt, reason=reconciliation_error
            )
        _apply_attempt_state(db, attempt, status=ATTEMPT_STATUS_PAYMENT_CONFIRMED, provider_subscription_id=provider_subscription_id)
        organization.payment_status = PAYMENT_PAID
        organization.billing_status = READY_FOR_PROVISIONING
        organization.payment_confirmed_at = organization.payment_confirmed_at or _utcnow()
        organization.last_payment_attempt_id = attempt.id
        checkout_session = db.query(models.CheckoutSession).filter(models.CheckoutSession.id == attempt.checkout_session_id).first()
        if checkout_session:
            checkout_session.status = CHECKOUT_SESSION_COMPLETED
        if contract:
            contract.payment_status = PAYMENT_PAID
            contract.payment_provider = PROVIDER
            contract.paid_at = contract.paid_at or _utcnow()
            contract.contract_status = "paid_pending_provisioning"
            if provider_subscription_id:
                subscription_payload = {
                    "data": {
                        **data,
                        "id": provider_subscription_id,
                        "status": "active",
                    }
                }
                _upsert_subscription_from_payload(
                    db,
                    organization,
                    contract,
                    payment_customer,
                    subscription_payload,
                    attempt=attempt,
                    item_summary=item_summary,
                )
            from saas import provisioning_service

            provisioning_service.enqueue_ready_for_provisioning(
                db,
                organization,
                contract,
                trigger_source="payment_webhook",
            )
            provisioning_service.process_pending_jobs(db, limit=1)
        service.log_pending_event(db, organization=organization, event_type="payment_confirmed", details={"provider_transaction_id": str(data.get("id") or "")})
    elif event_type in {"transaction.payment_failed", "transaction.past_due"}:
        _apply_attempt_state(db, attempt, status=ATTEMPT_STATUS_PAYMENT_FAILED, failure_reason=str(data.get("status") or event_type))
        organization.payment_status = PAYMENT_STATUS_FAILED
        organization.billing_status = PAYMENT_FAILED
        organization.payment_failed_at = _utcnow()
        checkout_session = db.query(models.CheckoutSession).filter(models.CheckoutSession.id == attempt.checkout_session_id).first()
        if checkout_session:
            checkout_session.status = CHECKOUT_SESSION_FAILED
        if contract:
            contract.payment_status = PAYMENT_STATUS_FAILED
            contract.payment_provider = PROVIDER
        service.log_pending_event(db, organization=organization, event_type="payment_failed", details={"provider_transaction_id": str(data.get("id") or ""), "event_type": event_type})
    elif event_type == "transaction.canceled":
        _apply_attempt_state(db, attempt, status=ATTEMPT_STATUS_PAYMENT_CANCELLED)
        organization.payment_status = PAYMENT_STATUS_CANCELLED
        organization.billing_status = PAYMENT_CANCELLED
        checkout_session = db.query(models.CheckoutSession).filter(models.CheckoutSession.id == attempt.checkout_session_id).first()
        if checkout_session:
            checkout_session.status = CHECKOUT_SESSION_CANCELLED
        if contract:
            contract.payment_status = PAYMENT_STATUS_CANCELLED
            contract.payment_provider = PROVIDER
        service.log_pending_event(db, organization=organization, event_type="payment_cancelled", details={"provider_transaction_id": str(data.get("id") or "")})
    elif event_type.startswith("subscription."):
        if contract:
            try:
                item_summary = _paddle_item_summary(data, require_reported_total=False)
            except ValueError as exc:
                return _mark_manual_reconciliation(
                    db, webhook_row, organization, contract, attempt, reason=str(exc)
                )
            reconciliation_error = _validate_paid_snapshot(db, organization, contract, attempt, item_summary)
            if reconciliation_error:
                return _mark_manual_reconciliation(
                    db, webhook_row, organization, contract, attempt, reason=reconciliation_error
                )
            _upsert_subscription_from_payload(
                db,
                organization,
                contract,
                payment_customer,
                payload,
                attempt=attempt,
                item_summary=item_summary,
            )
        service.log_pending_event(db, organization=organization, event_type="subscription_sync", details={"event_type": event_type, "provider_subscription_id": provider_subscription_id})
    else:
        webhook_row.processing_status = "ignored"
        webhook_row.processed_at = _utcnow()
        return {"status": "ignored", "event_type": event_type}

    webhook_row.processing_status = "processed"
    webhook_row.processed_at = _utcnow()
    return {"status": "processed", "event_type": event_type}
