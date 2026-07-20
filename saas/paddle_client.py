import os
from urllib.parse import parse_qs, urlparse

import httpx


class PaddleAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}
        error = self.body.get("error") if isinstance(self.body.get("error"), dict) else {}
        self.error_code = str(error.get("code") or "").strip() or None
        self.detail = str(error.get("detail") or message or "").strip()


def _base_url() -> str:
    return str(os.environ.get("PADDLE_API_BASE_URL") or "https://sandbox-api.paddle.com").rstrip("/")


def _api_key() -> str:
    value = str(os.environ.get("PADDLE_API_KEY") or "").strip()
    if not value:
        raise PaddleAPIError("Paddle API key is not configured.")
    return value


def _request_body(method: str, path: str, payload: dict | None = None, *, params: dict | None = None) -> dict:
    response = httpx.request(
        method,
        f"{_base_url()}{path}",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        params=params or None,
        json=payload,
        timeout=20.0,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        raise PaddleAPIError(
            str(body.get("error", {}).get("detail") or body or "Paddle request failed."),
            status_code=response.status_code,
            body=body,
        )
    data = body.get("data")
    if not isinstance(data, (dict, list)):
        raise PaddleAPIError("Unexpected Paddle API response.")
    return body


def _request_data(method: str, path: str, payload: dict | None = None, *, params: dict | None = None):
    return _request_body(method, path, payload, params=params)["data"]


def _request(method: str, path: str, payload: dict | None = None, *, params: dict | None = None) -> dict:
    data = _request_data(method, path, payload, params=params)
    if not isinstance(data, dict):
        raise PaddleAPIError("Unexpected Paddle API response.")
    return data


def _request_list(method: str, path: str, payload: dict | None = None, *, params: dict | None = None) -> list:
    data = _request_data(method, path, payload, params=params)
    if not isinstance(data, list):
        raise PaddleAPIError("Unexpected Paddle API response.")
    return data


def create_customer(*, email: str, name: str, custom_data: dict | None = None) -> dict:
    payload = {
        "email": str(email or "").strip(),
        "name": str(name or "").strip() or None,
        "custom_data": custom_data or {},
    }
    return _request("POST", "/customers", payload)


def list_customers_by_email(email: str) -> list[dict]:
    cleaned = str(email or "").strip()
    if not cleaned:
        return []
    return _request_list("GET", "/customers", params={"email": cleaned})


def update_customer(*, customer_id: str, custom_data: dict) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    if not cleaned_customer_id:
        raise ValueError("Paddle customer ID is required.")
    return _request(
        "PATCH",
        f"/customers/{cleaned_customer_id}",
        {"custom_data": custom_data},
    )


def create_transaction(
    *,
    customer_id: str,
    price_id: str,
    quantity: int,
    custom_data: dict | None = None,
    checkout_url: str | None = None,
) -> dict:
    try:
        validated_quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Paddle transaction quantity must be a positive integer.") from exc
    if validated_quantity < 1:
        raise ValueError("Paddle transaction quantity must be a positive integer.")
    payload = {
        "customer_id": customer_id,
        "items": [{"price_id": price_id, "quantity": validated_quantity}],
        "collection_mode": "automatic",
        "custom_data": custom_data or {},
        "checkout": {"url": checkout_url or None},
    }
    return _request("POST", "/transactions", payload)


def list_transactions(*, subscription_id: str) -> list[dict]:
    cleaned = str(subscription_id or "").strip()
    if not cleaned.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    params = {
        "subscription_id": cleaned,
        "include": "adjustments,adjustments_totals",
        "order_by": "billed_at[DESC]",
        "per_page": 30,
    }
    transactions: list[dict] = []
    seen_pages: set[str] = set()
    while True:
        body = _request_body("GET", "/transactions", params=params)
        data = body.get("data")
        if not isinstance(data, list):
            raise PaddleAPIError("Unexpected Paddle API response.")
        transactions.extend(row for row in data if isinstance(row, dict))
        pagination = ((body.get("meta") or {}).get("pagination") or {})
        if not pagination.get("has_more"):
            break
        next_url = str(pagination.get("next") or "").strip()
        if not next_url or next_url in seen_pages:
            raise PaddleAPIError("Unexpected Paddle pagination response.")
        seen_pages.add(next_url)
        query = parse_qs(urlparse(next_url).query)
        next_params = {key: values[-1] for key, values in query.items() if values}
        if not next_params:
            raise PaddleAPIError("Unexpected Paddle pagination response.")
        params = {**params, **next_params}
    return transactions


def get_transaction_invoice(*, transaction_id: str, disposition: str = "attachment") -> dict:
    cleaned = str(transaction_id or "").strip()
    if not cleaned.startswith("txn_"):
        raise ValueError("Paddle transaction ID is required.")
    cleaned_disposition = str(disposition or "").strip().lower()
    if cleaned_disposition not in {"attachment", "inline"}:
        raise ValueError("A supported invoice disposition is required.")
    return _request(
        "GET",
        f"/transactions/{cleaned}/invoice",
        params={"disposition": cleaned_disposition},
    )


def _subscription_items(items: list[dict]) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ValueError("At least one retained Paddle subscription item is required.")
    normalized = []
    for item in items:
        price_id = str((item or {}).get("price_id") or "").strip()
        try:
            quantity = int((item or {}).get("quantity"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Each retained Paddle subscription item requires a positive quantity.") from exc
        if not price_id.startswith("pri_") or quantity < 1:
            raise ValueError("Each retained Paddle subscription item requires a price and positive quantity.")
        normalized.append({"price_id": price_id, "quantity": quantity})
    return normalized


def get_subscription(*, subscription_id: str, include: str | None = None) -> dict:
    cleaned = str(subscription_id or "").strip()
    if not cleaned.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    params = {"include": include} if include else None
    return _request("GET", f"/subscriptions/{cleaned}", params=params)


def preview_subscription_update(
    *,
    subscription_id: str,
    items: list[dict],
    proration_billing_mode: str,
) -> dict:
    cleaned = str(subscription_id or "").strip()
    if not cleaned.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    mode = str(proration_billing_mode or "").strip()
    if mode not in {
        "prorated_immediately",
        "prorated_next_billing_period",
        "full_immediately",
        "full_next_billing_period",
        "do_not_bill",
    }:
        raise ValueError("A supported Paddle proration billing mode is required.")
    return _request(
        "PATCH",
        f"/subscriptions/{cleaned}/preview",
        {"items": _subscription_items(items), "proration_billing_mode": mode},
    )


def update_subscription(
    *,
    subscription_id: str,
    items: list[dict],
    proration_billing_mode: str,
    on_payment_failure: str = "prevent_change",
) -> dict:
    cleaned = str(subscription_id or "").strip()
    if not cleaned.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    mode = str(proration_billing_mode or "").strip()
    if mode not in {
        "prorated_immediately",
        "prorated_next_billing_period",
        "full_immediately",
        "full_next_billing_period",
        "do_not_bill",
    }:
        raise ValueError("A supported Paddle proration billing mode is required.")
    payment_failure = str(on_payment_failure or "").strip()
    if payment_failure not in {"prevent_change", "apply_change"}:
        raise ValueError("A supported Paddle payment-failure mode is required.")
    return _request(
        "PATCH",
        f"/subscriptions/{cleaned}",
        {
            "items": _subscription_items(items),
            "proration_billing_mode": mode,
            "on_payment_failure": payment_failure,
        },
    )


def cancel_subscription_at_period_end(*, subscription_id: str) -> dict:
    cleaned = str(subscription_id or "").strip()
    if not cleaned.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    return _request(
        "POST",
        f"/subscriptions/{cleaned}/cancel",
        {"effective_from": "next_billing_period"},
    )


def remove_subscription_scheduled_change(*, subscription_id: str) -> dict:
    cleaned = str(subscription_id or "").strip()
    if not cleaned.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    return _request(
        "PATCH",
        f"/subscriptions/{cleaned}",
        {"scheduled_change": None},
    )
