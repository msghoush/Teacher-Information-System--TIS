"""Read-only Paddle Sandbox plan-preview diagnostic for temporary operator use."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import auth
import saas.models  # noqa: F401 - register SaaS metadata
from database import SessionLocal
from saas import (
    models,
    paddle_client,
    subscription_change_service,
    subscription_plan_change_service,
)


class DiagnosticError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _clean(value) -> str:
    return str(value or "").strip()


def _mask_provider_id(value) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return f"{cleaned[:7]}...{cleaned[-4:]}" if len(cleaned) > 12 else f"{cleaned[:3]}..."


def _pick(payload, names) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {name: payload[name] for name in names if payload.get(name) is not None}


def _billing_period(payload) -> dict | None:
    result = _pick(payload, ("starts_at", "ends_at"))
    return result or None


def _totals(payload) -> dict | None:
    result = _pick(
        payload,
        (
            "subtotal",
            "discount",
            "tax",
            "total",
            "credit",
            "credit_to_balance",
            "balance",
            "grand_total",
            "grand_total_tax",
            "currency_code",
        ),
    )
    return result or None


def _proration(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    result = _pick(payload, ("rate",))
    period = _billing_period(payload.get("billing_period"))
    if period:
        result["billing_period"] = period
    return result or None


def _price(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    result = _pick(payload, ("id", "product_id", "name", "description", "type", "tax_mode"))
    result["unit_price"] = _pick(payload.get("unit_price"), ("amount", "currency_code")) or None
    result["billing_cycle"] = _pick(payload.get("billing_cycle"), ("interval", "frequency")) or None
    return {key: value for key, value in result.items() if value is not None} or None


def _subscription_item(payload) -> dict:
    result = _pick(payload, ("status", "quantity", "created_at", "updated_at", "previously_billed_at", "next_billed_at"))
    price = _price(payload.get("price"))
    if price:
        result["price"] = price
    return result


def _line_item(payload) -> dict:
    result = _pick(payload, ("price_id", "quantity", "tax_rate"))
    product = _pick(payload.get("product"), ("id", "name", "type", "tax_category"))
    unit_totals = _totals(payload.get("unit_totals"))
    totals = _totals(payload.get("totals"))
    proration = _proration(payload.get("proration"))
    if product:
        result["product"] = product
    if unit_totals:
        result["unit_totals"] = unit_totals
    if totals:
        result["totals"] = totals
    if proration:
        result["proration"] = proration
    return result


def _adjustment_item(payload) -> dict:
    result = _pick(payload, ("type", "amount"))
    if payload.get("item_id"):
        result["item_id_masked"] = _mask_provider_id(payload.get("item_id"))
    proration = _proration(payload.get("proration"))
    if proration:
        result["proration"] = proration
    return result


def _adjustment(payload) -> dict:
    result = _pick(payload, ("action", "type", "status", "reason", "currency_code", "created_at", "updated_at"))
    for name in ("id", "transaction_id"):
        if payload.get(name):
            result[f"{name}_masked"] = _mask_provider_id(payload.get(name))
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if items:
        result["items"] = [_adjustment_item(item) for item in items if isinstance(item, dict)]
    totals = _totals(payload.get("totals"))
    if totals:
        result["totals"] = totals
    return result


def _transaction_section(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    result = _pick(payload, ("status", "currency_code", "created_at", "updated_at", "billed_at"))
    period = _billing_period(payload.get("billing_period"))
    if period:
        result["billing_period"] = period
    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    clean_details = {}
    totals = _totals(details.get("totals") or payload.get("totals"))
    if totals:
        clean_details["totals"] = totals
    line_items = details.get("line_items") if isinstance(details.get("line_items"), list) else []
    if line_items:
        clean_details["line_items"] = [_line_item(item) for item in line_items if isinstance(item, dict)]
    tax_rates = details.get("tax_rates_used") if isinstance(details.get("tax_rates_used"), list) else []
    if tax_rates:
        clean_details["tax_rates_used"] = [
            {**_pick(item, ("tax_rate",)), **({"totals": _totals(item.get("totals"))} if _totals(item.get("totals")) else {})}
            for item in tax_rates
            if isinstance(item, dict)
        ]
    if clean_details:
        result["details"] = clean_details
    adjustments = payload.get("adjustments") if isinstance(payload.get("adjustments"), list) else []
    if adjustments:
        result["adjustments"] = [_adjustment(item) for item in adjustments if isinstance(item, dict)]
    return result or None


def sanitize_subscription(payload: dict) -> dict:
    result = _pick(
        payload,
        (
            "status",
            "currency_code",
            "collection_mode",
            "started_at",
            "first_billed_at",
            "next_billed_at",
            "created_at",
            "updated_at",
        ),
    )
    result["subscription_id_masked"] = _mask_provider_id(payload.get("id"))
    result["billing_cycle"] = _pick(payload.get("billing_cycle"), ("interval", "frequency")) or None
    result["current_billing_period"] = _billing_period(payload.get("current_billing_period"))
    result["scheduled_change"] = _pick(
        payload.get("scheduled_change"), ("action", "effective_at", "resume_at")
    ) or None
    result["items"] = [
        _subscription_item(item)
        for item in (payload.get("items") if isinstance(payload.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    result["recurring_transaction_details"] = _transaction_section(payload.get("recurring_transaction_details"))
    result["next_transaction"] = _transaction_section(payload.get("next_transaction"))
    return {key: value for key, value in result.items() if value is not None}


def sanitize_preview(payload: dict) -> dict:
    result = _pick(
        payload,
        (
            "status",
            "currency_code",
            "collection_mode",
            "started_at",
            "first_billed_at",
            "next_billed_at",
            "created_at",
            "updated_at",
        ),
    )
    result["billing_cycle"] = _pick(payload.get("billing_cycle"), ("interval", "frequency")) or None
    result["current_billing_period"] = _billing_period(payload.get("current_billing_period"))
    result["items"] = [
        _subscription_item(item)
        for item in (payload.get("items") if isinstance(payload.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    summary = payload.get("update_summary") if isinstance(payload.get("update_summary"), dict) else {}
    result["update_summary"] = {
        name: _pick(summary.get(name), ("action", "amount", "currency_code"))
        for name in ("credit", "charge", "result")
        if isinstance(summary.get(name), dict)
    } or None
    for name in ("immediate_transaction", "next_transaction", "recurring_transaction_details"):
        result[name] = _transaction_section(payload.get(name))
    return {key: value for key, value in result.items() if value is not None}


def sanitize_transaction(payload: dict) -> dict:
    result = _pick(
        payload,
        ("status", "origin", "collection_mode", "currency_code", "created_at", "updated_at", "billed_at"),
    )
    result["transaction_id_masked"] = _mask_provider_id(payload.get("id"))
    result["billing_period"] = _billing_period(payload.get("billing_period"))
    result["items"] = [
        {"quantity": item.get("quantity"), "price": _price(item.get("price"))}
        for item in (payload.get("items") if isinstance(payload.get("items"), list) else [])
        if isinstance(item, dict)
    ]
    section = _transaction_section(payload)
    if section and section.get("details"):
        result["details"] = section["details"]
    if section and section.get("adjustments"):
        result["adjustments"] = section["adjustments"]
    adjustment_totals = _totals(payload.get("adjustments_totals"))
    if adjustment_totals:
        result["adjustments_totals"] = adjustment_totals
    return {key: value for key, value in result.items() if value is not None}


def require_sandbox() -> None:
    environment = _clean(os.environ.get("PADDLE_ENVIRONMENT")).lower()
    hostname = (urlparse(paddle_client._base_url()).hostname or "").lower()
    if environment != "sandbox" or hostname != "sandbox-api.paddle.com":
        raise DiagnosticError(
            "sandbox_required",
            "This temporary diagnostic runs only with PADDLE_ENVIRONMENT=sandbox and the Sandbox API endpoint.",
        )


def _find_account(db, email: str):
    normalized = auth.normalize_email(email)
    account = db.query(models.SaaSAccount).filter(models.SaaSAccount.email_normalized == normalized).one_or_none()
    if account is None:
        raise DiagnosticError("account_not_found", "The SaaS account was not found.")
    return account


def run_diagnostic(db, *, email: str, target_plan_code: str) -> dict:
    require_sandbox()
    account = _find_account(db, email)
    context = subscription_change_service.resolve_change_context(db, account, lock=False)
    plan, target_price, direction = subscription_plan_change_service._target(db, context, target_plan_code)
    if direction != subscription_plan_change_service.UPGRADE:
        raise DiagnosticError("upgrade_required", "The target must be a higher plan than the confirmed current plan.")

    provider = paddle_client.get_subscription(
        subscription_id=context.subscription.provider_subscription_id,
        include="recurring_transaction_details,next_transaction",
    )
    quantity = int(context.subscription.quantity)
    current_items = subscription_plan_change_service._items(
        provider, context.subscription.provider_price_id, quantity
    )
    subscription_change_service._validate_provider_terms(
        provider,
        context.subscription.provider_price_id,
        context.subscription.billing_interval,
        context.subscription.currency_code,
    )
    target_items = subscription_plan_change_service._replace_price(
        current_items,
        context.subscription.provider_price_id,
        target_price.provider_price_id,
        quantity,
    )
    preview_body = {
        "items": target_items,
        "proration_billing_mode": "prorated_immediately",
    }
    preview = paddle_client.preview_subscription_update(
        subscription_id=context.subscription.provider_subscription_id,
        **preview_body,
    )

    observed = subscription_plan_change_service._items(preview, target_price.provider_price_id, quantity)
    subscription_change_service._validate_provider_terms(
        preview,
        target_price.provider_price_id,
        context.subscription.billing_interval,
        context.subscription.currency_code,
    )
    if subscription_change_service._items_signature(observed) != subscription_change_service._items_signature(target_items):
        raise DiagnosticError("preview_items_mismatch", "Paddle returned a different item set from the requested preview.")
    financials = subscription_plan_change_service._financials(
        preview,
        provider,
        direction,
        _clean(context.subscription.currency_code).upper(),
    )

    transactions = paddle_client._request_list(
        "GET",
        "/transactions",
        params={
            "subscription_id": context.subscription.provider_subscription_id,
            "include": "adjustments,adjustments_totals",
            "order_by": "created_at[DESC]",
            "per_page": 30,
        },
    )
    active_prices = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.billing_interval == context.subscription.billing_interval,
        models.SubscriptionPlanPrice.currency_code == context.subscription.currency_code,
        models.SubscriptionPlanPrice.is_active == True,
    ).all()
    recognized = sorted({_clean(row.provider_price_id) for row in active_prices if _clean(row.provider_price_id)})
    current_recognized = [item for item in current_items if item["price_id"] in recognized]
    proposed_recognized = [item for item in target_items if item["price_id"] in recognized]

    charge, credit, immediate, current_total, next_total = financials
    return {
        "diagnostic": "paddle_sandbox_plan_upgrade_preview",
        "database_transaction": "rolled_back_read_only",
        "paddle_operation": "preview_only_no_subscription_update",
        "current_local_commercial_state": {
            "plan_code": context.resolution.plan_code,
            "billing_interval": context.subscription.billing_interval,
            "currency_code": context.subscription.currency_code,
            "quantity": quantity,
            "provider_price_id": context.subscription.provider_price_id,
            "provider_subscription_id_masked": _mask_provider_id(context.subscription.provider_subscription_id),
        },
        "target_local_commercial_state": {
            "plan_code": plan.plan_code,
            "billing_interval": target_price.billing_interval,
            "currency_code": target_price.currency_code,
            "quantity": quantity,
            "provider_price_id": target_price.provider_price_id,
        },
        "recognized_base_plan_item_check": {
            "current": current_recognized,
            "proposed": proposed_recognized,
            "current_count": len(current_recognized),
            "proposed_count": len(proposed_recognized),
            "safe": len(current_recognized) == 1 and len(proposed_recognized) == 1,
        },
        "current_paddle_subscription": sanitize_subscription(provider),
        "preview_request": {
            "method": "PATCH",
            "path": f"/subscriptions/{_mask_provider_id(context.subscription.provider_subscription_id)}/preview",
            "body": preview_body,
        },
        "preview_response": sanitize_preview(preview),
        "validated_financial_totals_minor": {
            "update_summary_charge": charge,
            "update_summary_credit": credit,
            "immediate_transaction_balance": immediate,
            "current_recurring_balance": current_total,
            "next_recurring_balance": next_total,
            "currency_code": _clean(context.subscription.currency_code).upper(),
        },
        "recent_subscription_transactions": [sanitize_transaction(row) for row in transactions],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a sanitized, read-only Paddle Sandbox plan preview.")
    parser.add_argument("--email", required=True, help="Exact SaaS account email used only to resolve the local subscription.")
    parser.add_argument("--target-plan-code", default="enterprise_ai", help="Target active plan code (default: enterprise_ai).")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        result = run_diagnostic(db, email=args.email, target_plan_code=args.target_plan_code)
        db.rollback()
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    except (DiagnosticError, subscription_change_service.SubscriptionChangeError) as exc:
        db.rollback()
        print(json.dumps({"status": "blocked", "reason_code": getattr(exc, "code", "diagnostic_blocked"), "message": str(exc)}, sort_keys=True))
        return 2
    except paddle_client.PaddleAPIError as exc:
        db.rollback()
        print(json.dumps({"status": "failed", "reason_code": exc.error_code or "paddle_request_failed", "http_status": exc.status_code}, sort_keys=True))
        return 3
    except Exception:
        db.rollback()
        print(json.dumps({"status": "failed", "reason_code": "unexpected_diagnostic_error"}, sort_keys=True))
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
