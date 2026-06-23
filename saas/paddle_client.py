import os

import httpx


class PaddleAPIError(RuntimeError):
    pass


def _base_url() -> str:
    return str(os.environ.get("PADDLE_API_BASE_URL") or "https://sandbox-api.paddle.com").rstrip("/")


def _api_key() -> str:
    value = str(os.environ.get("PADDLE_API_KEY") or "").strip()
    if not value:
        raise PaddleAPIError("Paddle API key is not configured.")
    return value


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    response = httpx.request(
        method,
        f"{_base_url()}{path}",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=20.0,
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        raise PaddleAPIError(str(body.get("error", {}).get("detail") or body or "Paddle request failed."))
    data = body.get("data")
    if not isinstance(data, dict):
        raise PaddleAPIError("Unexpected Paddle API response.")
    return data


def create_customer(*, email: str, name: str, custom_data: dict | None = None) -> dict:
    payload = {
        "email": str(email or "").strip(),
        "name": str(name or "").strip() or None,
        "custom_data": custom_data or {},
    }
    return _request("POST", "/customers", payload)


def create_transaction(
    *,
    customer_id: str,
    price_id: str,
    quantity: int = 1,
    custom_data: dict | None = None,
    checkout_url: str | None = None,
) -> dict:
    payload = {
        "customer_id": customer_id,
        "items": [{"price_id": price_id, "quantity": int(quantity or 1)}],
        "collection_mode": "automatic",
        "custom_data": custom_data or {},
        "checkout": {"url": checkout_url or None},
    }
    return _request("POST", "/transactions", payload)
