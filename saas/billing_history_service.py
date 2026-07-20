from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

import audit
from saas import models, paddle_client, subscription_change_service


logger = logging.getLogger(__name__)
VISIBLE_TRANSACTION_STATUSES = {"billed", "paid", "completed", "past_due", "canceled"}


class BillingHistoryAccessError(PermissionError):
    pass


class InvoiceUnavailableError(ValueError):
    pass


@dataclass(frozen=True)
class BillingHistoryEntry:
    occurred_at: datetime
    date_label: str
    description: str
    amount_label: str
    currency_code: str
    status_label: str
    transaction_type_label: str


@dataclass(frozen=True)
class InvoiceHistoryEntry:
    invoice_number: str
    invoice_date_label: str
    total_label: str
    currency_code: str
    status_label: str
    download_path: str


@dataclass(frozen=True)
class BillingHistoryView:
    available: bool
    error_message: str
    current_plan: str
    recurring_cost_label: str
    recurring_cost_title: str
    billing_interval: str
    next_renewal: str
    latest_payment: str
    paid_branch_quantity: int | None
    history: tuple[BillingHistoryEntry, ...]
    invoices: tuple[InvoiceHistoryEntry, ...]


@dataclass(frozen=True)
class BillingContext:
    account: object
    actor: object
    subscription: models.PaymentSubscription
    customer: models.PaymentCustomer | None
    school_group_id: int


def _clean(value) -> str:
    return str(value or "").strip()


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        cleaned = _clean(value)
        if not cleaned:
            return None
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_label(value) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%B %d, %Y") if parsed else "Not Available"


def _minor_amount(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _money_label(amount_minor: int | None, currency_code: str) -> str:
    if amount_minor is None:
        return "Not Available"
    currency = _clean(currency_code).upper() or "USD"
    sign = "-" if amount_minor < 0 else ""
    symbols = {"USD": "$", "EUR": "EUR ", "GBP": "GBP "}
    return f"{sign}{symbols.get(currency, currency + ' ')}{abs(amount_minor) / 100:,.2f}"


def _transaction_amount(transaction: dict) -> int | None:
    totals = ((transaction.get("details") or {}).get("totals") or {})
    return _minor_amount(totals.get("grand_total"))


def _status_label(value) -> str:
    status = _clean(value).lower()
    return {
        "billed": "Billed",
        "paid": "Paid",
        "completed": "Paid",
        "past_due": "Payment Failed",
        "canceled": "Canceled",
        "approved": "Completed",
        "pending_approval": "Pending",
        "rejected": "Rejected",
        "reversed": "Reversed",
    }.get(status, status.replace("_", " ").title() or "Not Available")


def _transaction_type(origin: str) -> tuple[str, str]:
    normalized = _clean(origin).lower()
    return {
        "subscription_recurring": ("Renewal payment", "Renewal"),
        "subscription_update": ("Prorated subscription change", "Subscription update"),
        "subscription_charge": ("Subscription charge", "One-time charge"),
        "subscription_payment_method_change": ("Payment method verification", "Payment method update"),
        "subscription_import": ("Imported subscription payment", "Subscription import"),
        "web": ("Initial subscription payment", "Initial payment"),
        "api": ("Subscription payment", "Subscription payment"),
    }.get(normalized, ("Subscription transaction", normalized.replace("_", " ").title() or "Transaction"))


def _adjustment_entries(transaction: dict, currency_code: str) -> list[BillingHistoryEntry]:
    entries = []
    for adjustment in transaction.get("adjustments") or []:
        if not isinstance(adjustment, dict):
            continue
        action = _clean(adjustment.get("action")).lower()
        if action not in {"credit", "refund", "chargeback", "chargeback_reverse", "credit_reverse"}:
            continue
        totals = adjustment.get("totals") or {}
        amount = _minor_amount(totals.get("total"))
        if amount is not None and action in {"credit", "refund", "chargeback"}:
            amount = -abs(amount)
        occurred_at = _parse_datetime(adjustment.get("created_at"))
        if occurred_at is None:
            continue
        label = {
            "credit": "Credit",
            "refund": "Refund",
            "chargeback": "Chargeback",
            "chargeback_reverse": "Chargeback reversal",
            "credit_reverse": "Credit reversal",
        }[action]
        entries.append(BillingHistoryEntry(
            occurred_at=occurred_at,
            date_label=_date_label(occurred_at),
            description=label,
            amount_label=_money_label(amount, currency_code),
            currency_code=currency_code,
            status_label=_status_label(adjustment.get("status")),
            transaction_type_label="Adjustment",
        ))
    return entries


def _transaction_credit_entry(transaction: dict, currency_code: str, occurred_at: datetime) -> BillingHistoryEntry | None:
    adjustments = transaction.get("adjustments") or []
    if any(
        isinstance(row, dict) and _clean(row.get("action")).lower() in {"credit", "refund"}
        for row in adjustments
    ):
        return None
    totals = ((transaction.get("details") or {}).get("totals") or {})
    credit = _minor_amount(totals.get("credit"))
    if credit is None or credit <= 0:
        return None
    return BillingHistoryEntry(
        occurred_at=occurred_at,
        date_label=_date_label(occurred_at),
        description="Credit applied",
        amount_label=_money_label(-abs(credit), currency_code),
        currency_code=currency_code,
        status_label="Applied",
        transaction_type_label="Credit",
    )


def resolve_billing_context(db: Session, account) -> BillingContext:
    from saas import entitlement_service

    resolution = entitlement_service.resolve_customer_entitlements(db, account)
    if not resolution.school_group_id or not resolution.subscription_id:
        raise BillingHistoryAccessError("Billing information is not available for this account.")
    subscription = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.id == resolution.subscription_id,
    ).one_or_none()
    if subscription is None or not _clean(subscription.provider_subscription_id):
        raise BillingHistoryAccessError("Billing information is not available for this account.")
    try:
        actor = subscription_change_service.resolve_billing_actor(
            db, account, int(resolution.school_group_id)
        )
    except subscription_change_service.SubscriptionChangeError as exc:
        raise BillingHistoryAccessError("Billing information is not available for this account.") from exc
    customer = None
    if subscription.payment_customer_id:
        customer = db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.id == subscription.payment_customer_id,
            models.PaymentCustomer.saas_account_id == account.id,
        ).one_or_none()
    return BillingContext(account, actor, subscription, customer, int(resolution.school_group_id))


def _validated_transactions(context: BillingContext) -> list[dict]:
    rows = paddle_client.list_transactions(
        subscription_id=context.subscription.provider_subscription_id,
    )
    expected_subscription_id = _clean(context.subscription.provider_subscription_id)
    expected_customer_id = _clean(getattr(context.customer, "provider_customer_id", ""))
    validated = []
    for row in rows:
        if _clean(row.get("subscription_id")) != expected_subscription_id:
            logger.warning("Paddle transaction list returned a mismatched subscription row.")
            continue
        if expected_customer_id and _clean(row.get("customer_id")) != expected_customer_id:
            logger.warning("Paddle transaction list returned a mismatched customer row.")
            continue
        validated.append(row)
    return validated


def _history_entries(transactions: list[dict]) -> tuple[BillingHistoryEntry, ...]:
    entries: list[BillingHistoryEntry] = []
    for transaction in transactions:
        status = _clean(transaction.get("status")).lower()
        if status not in VISIBLE_TRANSACTION_STATUSES:
            continue
        occurred_at = _parse_datetime(transaction.get("billed_at") or transaction.get("created_at"))
        if occurred_at is None:
            continue
        currency = _clean(transaction.get("currency_code")).upper() or "USD"
        description, transaction_type = _transaction_type(transaction.get("origin"))
        entries.append(BillingHistoryEntry(
            occurred_at=occurred_at,
            date_label=_date_label(occurred_at),
            description=description,
            amount_label=_money_label(_transaction_amount(transaction), currency),
            currency_code=currency,
            status_label=_status_label(status),
            transaction_type_label=transaction_type,
        ))
        entries.extend(_adjustment_entries(transaction, currency))
        credit_entry = _transaction_credit_entry(transaction, currency, occurred_at)
        if credit_entry:
            entries.append(credit_entry)
    return tuple(sorted(entries, key=lambda entry: entry.occurred_at, reverse=True))


def _invoice_entries(transactions: list[dict]) -> tuple[InvoiceHistoryEntry, ...]:
    entries = []
    for transaction in transactions:
        status = _clean(transaction.get("status")).lower()
        collection_mode = _clean(transaction.get("collection_mode")).lower()
        amount = _transaction_amount(transaction)
        invoice_number = _clean(transaction.get("invoice_number"))
        eligible = (
            status == "completed"
            or (collection_mode == "manual" and status == "billed")
        )
        occurred_at = _parse_datetime(transaction.get("billed_at") or transaction.get("created_at"))
        if not eligible or amount in {None, 0} or not invoice_number or occurred_at is None:
            continue
        currency = _clean(transaction.get("currency_code")).upper() or "USD"
        entries.append(InvoiceHistoryEntry(
            invoice_number=invoice_number,
            invoice_date_label=_date_label(occurred_at),
            total_label=_money_label(amount, currency),
            currency_code=currency,
            status_label=_status_label(status),
            download_path=f"/saas/subscription/invoices/{quote(invoice_number, safe='')}/download",
        ))
    return tuple(entries)


def build_billing_history(db: Session, account, portal) -> BillingHistoryView:
    context = resolve_billing_context(db, account)
    recurring_title = "Monthly Cost" if portal.billing_interval_label == "Monthly" else "Annual Cost" if portal.billing_interval_label == "Annual" else "Recurring Cost"
    base = {
        "current_plan": portal.plan_name,
        "recurring_cost_label": portal.current_recurring_total_label,
        "recurring_cost_title": recurring_title,
        "billing_interval": portal.billing_interval_label,
        "next_renewal": portal.next_billing_date_label,
        "paid_branch_quantity": portal.paid_branch_quantity,
    }
    try:
        transactions = _validated_transactions(context)
        history = _history_entries(transactions)
        invoices = _invoice_entries(transactions)
    except (paddle_client.PaddleAPIError, httpx.HTTPError) as exc:
        logger.warning(
            "Paddle billing history retrieval failed for school group %s: %s",
            context.school_group_id,
            getattr(exc, "error_code", None) or type(exc).__name__,
        )
        return BillingHistoryView(
            available=False,
            error_message="Billing information is temporarily unavailable. Please try again.",
            latest_payment="Not Available",
            history=(),
            invoices=(),
            **base,
        )
    except (AttributeError, TypeError, ValueError):
        logger.exception(
            "Paddle billing history response could not be parsed for school group %s.",
            context.school_group_id,
        )
        return BillingHistoryView(
            available=False,
            error_message="Billing information is temporarily unavailable. Please try again.",
            latest_payment="Not Available",
            history=(),
            invoices=(),
            **base,
        )
    latest_payment = next(
        (entry.date_label for entry in history if entry.status_label == "Paid"),
        "Not Available",
    )
    return BillingHistoryView(
        available=True,
        error_message="",
        latest_payment=latest_payment,
        history=history,
        invoices=invoices,
        **base,
    )


def get_invoice_download_url(db: Session, account, invoice_number: str) -> str:
    context = resolve_billing_context(db, account)
    cleaned_invoice_number = _clean(invoice_number)
    if not cleaned_invoice_number:
        raise InvoiceUnavailableError("Invoice is unavailable.")
    try:
        matches = [
            row for row in _validated_transactions(context)
            if _clean(row.get("invoice_number")) == cleaned_invoice_number
        ]
        eligible = [row for row in matches if (
            _clean(row.get("status")).lower() == "completed"
            or (
                _clean(row.get("collection_mode")).lower() == "manual"
                and _clean(row.get("status")).lower() == "billed"
            )
        ) and _transaction_amount(row) not in {None, 0}]
        if len(eligible) != 1:
            raise InvoiceUnavailableError("Invoice is unavailable.")
        transaction_id = _clean(eligible[0].get("id"))
        response = paddle_client.get_transaction_invoice(
            transaction_id=transaction_id,
            disposition="attachment",
        )
    except InvoiceUnavailableError:
        raise
    except (paddle_client.PaddleAPIError, httpx.HTTPError) as exc:
        logger.warning(
            "Paddle invoice retrieval failed for school group %s: %s",
            context.school_group_id,
            getattr(exc, "error_code", None) or type(exc).__name__,
        )
        raise InvoiceUnavailableError("Invoice is temporarily unavailable. Please try again.") from exc
    except (AttributeError, TypeError, ValueError) as exc:
        logger.exception(
            "Paddle invoice response could not be parsed for school group %s.",
            context.school_group_id,
        )
        raise InvoiceUnavailableError("Invoice is temporarily unavailable. Please try again.") from exc
    url = _clean(response.get("url"))
    if not url.lower().startswith("https://"):
        raise InvoiceUnavailableError("Invoice is temporarily unavailable. Please try again.")
    audit.write_audit_event({
        "event_type": "saas_invoice_download_requested",
        "actor_saas_account_id": int(account.id),
        "actor_user_id": getattr(context.actor, "id", None),
        "school_group_id": context.school_group_id,
        "invoice_number": cleaned_invoice_number,
    })
    return url
