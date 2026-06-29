import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy.orm import Session

from saas import models, paddle_client, service

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
    full_name = " ".join(
        part for part in [str(getattr(account, "first_name", "") or "").strip(), str(getattr(account, "last_name", "") or "").strip()] if part
    ).strip() or str(getattr(organization, "organization_name", "") or "").strip()
    remote = paddle_client.create_customer(
        email=str(getattr(account, "email", "") or "").strip(),
        name=full_name,
        custom_data={
            "pending_organization_uuid": str(getattr(organization, "organization_uuid", "") or ""),
            "saas_account_uuid": str(getattr(account, "account_uuid", "") or ""),
        },
    )
    row = models.PaymentCustomer(
        pending_organization_id=organization.id,
        saas_account_id=account.id,
        provider=PROVIDER,
        provider_customer_id=str(remote.get("id") or "").strip(),
        email=str(remote.get("email") or getattr(account, "email", "") or "").strip() or None,
        name=str(remote.get("name") or full_name or "").strip() or None,
        country_code=str(getattr(organization, "country_code", "") or "").strip().upper() or None,
        status=str(remote.get("status") or "active").strip() or "active",
    )
    db.add(row)
    db.flush()
    return row


def build_checkout_launch_context(db: Session, organization):
    checkout_session = _ensure_checkout_launchable(db, organization)
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
    return checkout_session, selection, contract, plan_price


def launch_checkout(db: Session, organization, account, request: Request):
    checkout_session, selection, contract, plan_price = build_checkout_launch_context(db, organization)
    payment_customer = _find_or_create_payment_customer(db, organization, account)
    attempt = models.PaymentAttempt(
        pending_organization_id=organization.id,
        checkout_session_id=checkout_session.id,
        plan_selection_id=selection.id,
        payment_customer_id=payment_customer.id,
        provider=PROVIDER,
        attempt_uuid=str(uuid.uuid4()),
        status=ATTEMPT_STATUS_CHECKOUT_STARTED,
        currency_code="USD",
        amount_minor=int(getattr(plan_price, "amount_minor", 0) or 0),
        billing_interval=str(selection.billing_interval or "").strip(),
        started_at=_utcnow(),
        expires_at=_utcnow() + timedelta(hours=2),
    )
    db.add(attempt)
    db.flush()

    transaction = paddle_client.create_transaction(
        customer_id=payment_customer.provider_customer_id,
        price_id=str(plan_price.provider_price_id or "").strip(),
        quantity=1,
        custom_data={
            "pending_organization_uuid": organization.organization_uuid,
            "payment_attempt_uuid": attempt.attempt_uuid,
            "checkout_session_id": checkout_session.id,
            "subscription_contract_id": contract.id,
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


def _upsert_subscription_from_payload(db: Session, organization, contract, payment_customer, payload: dict, attempt=None):
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
            status="pending",
        )
        db.add(row)
        db.flush()
    row.payment_customer_id = getattr(payment_customer, "id", None)
    row.plan_id = contract.plan_id
    row.billing_interval = contract.billing_interval
    row.status = str(data.get("status") or row.status or "pending").strip() or "pending"
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if items and isinstance(items[0], dict):
        price = items[0].get("price") if isinstance(items[0].get("price"), dict) else {}
        row.provider_price_id = str(price.get("id") or row.provider_price_id or "").strip() or row.provider_price_id
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
            _upsert_subscription_from_payload(
                db,
                organization,
                contract,
                payment_customer,
                payload,
                attempt=attempt,
            )
        service.log_pending_event(db, organization=organization, event_type="subscription_sync", details={"event_type": event_type, "provider_subscription_id": provider_subscription_id})
    else:
        webhook_row.processing_status = "ignored"
        webhook_row.processed_at = _utcnow()
        return {"status": "ignored", "event_type": event_type}

    webhook_row.processing_status = "processed"
    webhook_row.processed_at = _utcnow()
    return {"status": "processed", "event_type": event_type}
