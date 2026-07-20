from datetime import datetime, timezone
import hashlib
import json
import logging

import httpx
from sqlalchemy.orm import Session

import audit
from saas import models, paddle_client, subscription_change_service, subscription_lifecycle_service


CANCELLATION = subscription_lifecycle_service.CANCELLATION_REQUEST
REVERSAL = subscription_lifecycle_service.CANCELLATION_REVERSAL
NEXT_PERIOD = "next_billing_period"
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(value) -> str:
    return str(value or "").strip()


def _parse_datetime(value) -> datetime | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _scheduled_change(data: dict) -> dict | None:
    value = data.get("scheduled_change")
    return value if isinstance(value, dict) else None


def _validate_provider_subscription(context, data: dict) -> list[dict]:
    if (
        _clean(data.get("id")) != context.subscription.provider_subscription_id
        or _clean(data.get("status")).lower() != "active"
    ):
        raise subscription_change_service.SubscriptionChangeError(
            "This subscription requires review before cancellation can continue.",
            code="provider_subscription_mismatch",
            status_code=409,
        )
    retained = subscription_change_service._retained_items(
        data,
        context.subscription.provider_price_id,
        int(context.subscription.quantity or 0),
    )
    subscription_change_service._validate_provider_terms(
        data,
        context.subscription.provider_price_id,
        context.subscription.billing_interval,
        context.subscription.currency_code,
    )
    return retained


def _request_key(context, change_type: str, attempt_number: int) -> str:
    raw = ":".join((
        "subscription-lifecycle",
        str(context.subscription.id),
        change_type,
        str(attempt_number),
    ))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _attempt_number(db: Session, context, change_type: str) -> int:
    return db.query(models.SubscriptionChangeRequest.id).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.change_type == change_type,
    ).count() + 1


def _new_request(
    db: Session,
    context,
    *,
    change_type: str,
    status: str,
    effective_at: datetime | None,
    retained_items: list[dict],
    failure_code: str = "",
    failure_message: str = "",
):
    now = _utcnow()
    row = models.SubscriptionChangeRequest(
        school_group_id=context.resolution.school_group_id,
        subscription_contract_id=context.contract.id,
        payment_subscription_id=context.subscription.id,
        provider_subscription_id=context.subscription.provider_subscription_id,
        requested_by_user_id=getattr(context.actor, "id", None),
        requested_by_saas_account_id=context.account.id,
        change_type=change_type,
        current_quantity=int(context.subscription.quantity or 0),
        requested_quantity=int(context.subscription.quantity or 0),
        quantity_delta=0,
        current_plan_price_id=context.plan_price.id,
        provider_price_id=context.subscription.provider_price_id,
        billing_interval=context.subscription.billing_interval,
        currency_code=context.subscription.currency_code,
        effective_mode=NEXT_PERIOD if change_type == CANCELLATION else "remove_scheduled_change",
        status=status,
        current_renewal_total_minor=context.subscription.amount_minor,
        next_renewal_total_minor=0 if change_type == CANCELLATION else context.subscription.amount_minor,
        retained_items_json=json.dumps(retained_items, separators=(",", ":"), sort_keys=True),
        idempotency_key=_request_key(context, change_type, _attempt_number(db, context, change_type)),
        requested_at=now,
        submitted_at=now if status in {"submitted", "failed"} else None,
        effective_at=effective_at,
        failure_code=_clean(failure_code) or None,
        failure_message=_clean(failure_message) or None,
    )
    db.add(row)
    db.flush()
    return row


def _audit(event_type: str, context, row, **details) -> None:
    audit.write_audit_event({
        "event_type": event_type,
        "actor_saas_account_id": context.account.id,
        "actor_user_id": getattr(context.actor, "id", None),
        "school_group_id": context.resolution.school_group_id,
        "subscription_change_request_uuid": row.request_uuid,
        "provider_subscription_reference": context.subscription.provider_subscription_id,
        **details,
    })


def _provider_failure(exc: Exception):
    code = _clean(getattr(exc, "error_code", "")) or "provider_request_failed"
    return code, "The billing provider could not complete this request."


def _record_provider_failure(db: Session, context, *, change_type: str, retained_items: list[dict], exc: Exception):
    if isinstance(exc, subscription_change_service.SubscriptionChangeError):
        code = exc.code
        message = str(exc)
    else:
        code, message = _provider_failure(exc)
    row = _new_request(
        db,
        context,
        change_type=change_type,
        status="failed",
        effective_at=None,
        retained_items=retained_items,
        failure_code=code,
        failure_message=message,
    )
    event_type = (
        "subscription_cancellation_reversal_failed"
        if change_type == REVERSAL
        else "subscription_cancellation_failed"
    )
    _audit(event_type, context, row, failure_code=code)
    logger.warning("Subscription lifecycle provider request failed: type=%s code=%s", change_type, code)
    return code


def get_cancellation_confirmation(db: Session, account):
    lifecycle = subscription_lifecycle_service.resolve_subscription_lifecycle(db, account)
    if not lifecycle.allowed_actions.can_cancel:
        raise subscription_change_service.SubscriptionChangeError(
            "Subscription cancellation is not available while another billing action is pending.",
            code="cancellation_unavailable",
            status_code=409,
        )
    return lifecycle


def request_cancellation(db: Session, account):
    context = subscription_change_service.resolve_change_context(db, account, lock=True)
    pending = subscription_change_service.get_pending_change(db, context.subscription.id)
    if pending is not None:
        if pending.change_type == CANCELLATION and pending.status in {"submitted", "scheduled"}:
            return pending
        raise subscription_change_service.SubscriptionChangeError(
            "Another subscription change is already in progress.",
            code="pending_change_exists",
            status_code=409,
        )
    lifecycle = subscription_lifecycle_service.resolve_subscription_lifecycle(
        db, account, resolution=context.resolution
    )
    if not lifecycle.allowed_actions.can_cancel:
        raise subscription_change_service.SubscriptionChangeError(
            "Subscription cancellation is not currently available.",
            code="cancellation_unavailable",
            status_code=409,
        )
    retained = []
    try:
        provider = paddle_client.get_subscription(
            subscription_id=context.subscription.provider_subscription_id
        )
        retained = _validate_provider_subscription(context, provider)
    except subscription_change_service.SubscriptionChangeError as exc:
        _record_provider_failure(
            db, context, change_type=CANCELLATION, retained_items=retained, exc=exc
        )
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        code = _record_provider_failure(
            db, context, change_type=CANCELLATION, retained_items=retained, exc=exc
        )
        raise subscription_change_service.SubscriptionChangeError(
            "Secure subscription management is temporarily unavailable. Please try again later.",
            code=code,
            status_code=502,
        ) from exc
    scheduled = _scheduled_change(provider)
    if scheduled is not None and _clean(scheduled.get("action")) != "cancel":
        raise subscription_change_service.SubscriptionChangeError(
            "Another provider subscription change is already scheduled.",
            code="provider_scheduled_change_conflict",
            status_code=409,
        )
    try:
        response = provider if scheduled is not None else paddle_client.cancel_subscription_at_period_end(
            subscription_id=context.subscription.provider_subscription_id
        )
        retained = _validate_provider_subscription(context, response)
        scheduled = _scheduled_change(response)
        if scheduled is None or _clean(scheduled.get("action")) != "cancel":
            raise subscription_change_service.SubscriptionChangeError(
                "The billing provider did not confirm a scheduled cancellation.",
                code="provider_cancellation_not_scheduled",
                status_code=502,
            )
        effective_at = _parse_datetime(scheduled.get("effective_at"))
        if effective_at is None:
            raise subscription_change_service.SubscriptionChangeError(
                "The billing provider did not return a cancellation date.",
                code="provider_cancellation_date_missing",
                status_code=502,
            )
    except subscription_change_service.SubscriptionChangeError as exc:
        _record_provider_failure(
            db, context, change_type=CANCELLATION, retained_items=retained, exc=exc
        )
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        code = _record_provider_failure(
            db, context, change_type=CANCELLATION, retained_items=retained, exc=exc
        )
        raise subscription_change_service.SubscriptionChangeError(
            "Secure subscription management is temporarily unavailable. Please try again later.",
            code=code,
            status_code=502,
        ) from exc
    row = _new_request(
        db,
        context,
        change_type=CANCELLATION,
        status="submitted",
        effective_at=effective_at,
        retained_items=retained,
    )
    row.provider_scheduled_at = _parse_datetime(response.get("updated_at")) or _utcnow()
    row.provider_preview_reference = _clean(response.get("updated_at")) or None
    _audit("subscription_cancellation_requested", context, row, effective_at=effective_at.isoformat())
    return row


def request_cancellation_reversal(db: Session, account):
    context = subscription_change_service.resolve_change_context(db, account, lock=True)
    existing_reversal = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.change_type == REVERSAL,
        models.SubscriptionChangeRequest.status.in_(("submitted", "confirmed")),
    ).order_by(models.SubscriptionChangeRequest.created_at.desc()).first()
    if existing_reversal is not None:
        return existing_reversal
    cancellation = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.change_type == CANCELLATION,
        models.SubscriptionChangeRequest.status == "scheduled",
    ).with_for_update().one_or_none()
    lifecycle = subscription_lifecycle_service.resolve_subscription_lifecycle(
        db, account, resolution=context.resolution
    )
    if cancellation is None or not lifecycle.allowed_actions.can_undo_cancellation:
        raise subscription_change_service.SubscriptionChangeError(
            "There is no confirmed scheduled cancellation to undo.",
            code="scheduled_cancellation_missing",
            status_code=409,
        )
    retained = []
    try:
        provider = paddle_client.get_subscription(
            subscription_id=context.subscription.provider_subscription_id
        )
        retained = _validate_provider_subscription(context, provider)
    except subscription_change_service.SubscriptionChangeError as exc:
        _record_provider_failure(
            db, context, change_type=REVERSAL, retained_items=retained, exc=exc
        )
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        code = _record_provider_failure(
            db, context, change_type=REVERSAL, retained_items=retained, exc=exc
        )
        raise subscription_change_service.SubscriptionChangeError(
            "Secure subscription management is temporarily unavailable. Please try again later.",
            code=code,
            status_code=502,
        ) from exc
    scheduled = _scheduled_change(provider)
    if scheduled is not None and _clean(scheduled.get("action")) != "cancel":
        raise subscription_change_service.SubscriptionChangeError(
            "The provider subscription state requires review.",
            code="provider_scheduled_change_mismatch",
            status_code=409,
        )
    try:
        response = provider if scheduled is None else paddle_client.remove_subscription_scheduled_change(
            subscription_id=context.subscription.provider_subscription_id
        )
        retained = _validate_provider_subscription(context, response)
        if _scheduled_change(response) is not None:
            raise subscription_change_service.SubscriptionChangeError(
                "The billing provider did not remove the scheduled cancellation.",
                code="provider_cancellation_reversal_not_applied",
                status_code=502,
            )
    except subscription_change_service.SubscriptionChangeError as exc:
        _record_provider_failure(
            db, context, change_type=REVERSAL, retained_items=retained, exc=exc
        )
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError, ValueError) as exc:
        code = _record_provider_failure(
            db, context, change_type=REVERSAL, retained_items=retained, exc=exc
        )
        raise subscription_change_service.SubscriptionChangeError(
            "Secure subscription management is temporarily unavailable. Please try again later.",
            code=code,
            status_code=502,
        ) from exc
    cancellation.status = "superseded"
    cancellation.canceled_at = _utcnow()
    db.flush()
    row = _new_request(
        db,
        context,
        change_type=REVERSAL,
        status="submitted",
        effective_at=None,
        retained_items=retained,
    )
    row.provider_scheduled_at = _parse_datetime(response.get("updated_at")) or _utcnow()
    row.provider_preview_reference = _clean(response.get("updated_at")) or None
    _audit("subscription_cancellation_reversed", context, row)
    return row


def _event_observed_at(payload: dict, data: dict) -> datetime | None:
    return _parse_datetime(payload.get("occurred_at")) or _parse_datetime(data.get("updated_at"))


def _mark_webhook_review(latest, *, code: str, message: str) -> dict:
    latest.status = "manual_review"
    latest.failure_code = code
    latest.failure_message = message
    audit.write_audit_event({
        "event_type": (
            "subscription_cancellation_reversal_failed"
            if latest.change_type == REVERSAL
            else "subscription_cancellation_failed"
        ),
        "school_group_id": latest.school_group_id,
        "subscription_change_request_uuid": latest.request_uuid,
        "failure_code": code,
    })
    return {"status": "manual_review", "reason_code": code}


def reconcile_cancellation_webhook(db: Session, payload: dict, event_type: str):
    if event_type not in {"subscription.updated", "subscription.canceled"}:
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    provider_subscription_id = _clean(data.get("id"))
    if not provider_subscription_id:
        return None
    subscription = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.provider_subscription_id == provider_subscription_id
    ).with_for_update().one_or_none()
    if subscription is None:
        return None
    rows = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.payment_subscription_id == subscription.id,
        models.SubscriptionChangeRequest.provider_subscription_id == provider_subscription_id,
        models.SubscriptionChangeRequest.change_type.in_((CANCELLATION, REVERSAL)),
    ).order_by(models.SubscriptionChangeRequest.created_at.desc()).with_for_update().all()
    if not rows:
        return None
    latest = next(
        (
            row for row in rows
            if row.status in {"submitted", "payment_pending", "scheduled", "manual_review"}
        ),
        rows[0],
    )
    observed_at = _event_observed_at(payload, data)
    if latest.submitted_at and observed_at and observed_at < latest.submitted_at:
        return {"status": "processed", "event_type": event_type, "outcome": "stale_event_ignored"}
    last_reconciled_at = latest.confirmed_at or latest.provider_scheduled_at
    if last_reconciled_at and observed_at and observed_at < last_reconciled_at:
        return {"status": "processed", "event_type": event_type, "outcome": "stale_event_ignored"}
    provider_status = _clean(data.get("status")).lower()
    scheduled = _scheduled_change(data)
    scheduled_action = _clean((scheduled or {}).get("action"))
    from saas.payment_service import _normalized_paddle_subscription_status, _parse_datetime as payment_datetime

    try:
        subscription_change_service._retained_items(
            data,
            subscription.provider_price_id,
            int(subscription.quantity or 0),
        )
        subscription_change_service._validate_provider_terms(
            data,
            subscription.provider_price_id,
            subscription.billing_interval,
            subscription.currency_code,
        )
    except subscription_change_service.SubscriptionChangeError:
        result = _mark_webhook_review(
            latest,
            code="provider_subscription_mismatch",
            message="The provider subscription details require review.",
        )
        result["event_type"] = event_type
        return result

    if _clean(subscription.status).lower() in {"canceled", "cancelled"} and provider_status not in {"canceled", "cancelled"}:
        result = _mark_webhook_review(
            latest,
            code="provider_status_regression",
            message="A later provider event conflicts with the confirmed cancellation.",
        )
        result["event_type"] = event_type
        return result

    subscription.status = _normalized_paddle_subscription_status(data.get("status"), fallback=subscription.status)
    period = data.get("current_billing_period") if isinstance(data.get("current_billing_period"), dict) else {}
    subscription.current_period_start = payment_datetime(period.get("starts_at")) or subscription.current_period_start
    subscription.current_period_end = payment_datetime(period.get("ends_at")) or subscription.current_period_end
    subscription.next_billed_at = payment_datetime(data.get("next_billed_at"))

    if event_type == "subscription.canceled" or provider_status in {"canceled", "cancelled"}:
        subscription.status = "canceled"
        subscription.cancel_at_period_end = False
        subscription.cancelled_at = payment_datetime(data.get("canceled_at")) or subscription.cancelled_at or _utcnow()
        if latest.change_type == REVERSAL and latest.status == "submitted":
            result = _mark_webhook_review(
                latest,
                code="provider_canceled_during_reversal",
                message="The provider canceled the subscription while cancellation reversal was pending.",
            )
            result["event_type"] = event_type
            return result
        cancellation = next((row for row in rows if row.change_type == CANCELLATION and row.status != "superseded"), None)
        if cancellation is not None and cancellation.status != "confirmed":
            cancellation.status = "confirmed"
            cancellation.confirmed_at = observed_at or _utcnow()
            audit.write_audit_event({
                "event_type": "subscription_cancellation_confirmed",
                "school_group_id": cancellation.school_group_id,
                "subscription_change_request_uuid": cancellation.request_uuid,
            })
        return {"status": "processed", "event_type": event_type}

    if scheduled_action == "cancel":
        if latest.change_type == REVERSAL:
            result = _mark_webhook_review(
                latest,
                code="provider_cancellation_reversal_not_confirmed",
                message="The scheduled cancellation still requires review.",
            )
            result["event_type"] = event_type
            return result
        effective_at = payment_datetime(scheduled.get("effective_at")) or latest.effective_at
        if (
            latest.status == "scheduled"
            and subscription.cancel_at_period_end
            and latest.effective_at == effective_at
        ):
            return {"status": "processed", "event_type": event_type, "outcome": "replayed_event_ignored"}
        latest.status = "scheduled"
        latest.effective_at = effective_at
        latest.provider_scheduled_at = observed_at or latest.provider_scheduled_at or _utcnow()
        subscription.cancel_at_period_end = True
        audit.write_audit_event({
            "event_type": "subscription_cancellation_confirmed",
            "school_group_id": latest.school_group_id,
            "subscription_change_request_uuid": latest.request_uuid,
            "effective_at": latest.effective_at.isoformat() if latest.effective_at else None,
        })
        return {"status": "processed", "event_type": event_type}

    subscription.cancel_at_period_end = False
    if latest.change_type == REVERSAL and latest.status == "submitted":
        latest.status = "confirmed"
        latest.confirmed_at = observed_at or _utcnow()
        audit.write_audit_event({
            "event_type": "subscription_cancellation_reversal_confirmed",
            "school_group_id": latest.school_group_id,
            "subscription_change_request_uuid": latest.request_uuid,
        })
        return {"status": "processed", "event_type": event_type}
    if latest.change_type == CANCELLATION and latest.status in {"submitted", "scheduled"}:
        result = _mark_webhook_review(
            latest,
            code="provider_cancellation_not_confirmed",
            message="The scheduled cancellation requires review.",
        )
        result["event_type"] = event_type
        return result
    return {"status": "processed", "event_type": event_type}
