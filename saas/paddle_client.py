import os

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


def _request_data(method: str, path: str, payload: dict | None = None, *, params: dict | None = None):
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
    return data


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
