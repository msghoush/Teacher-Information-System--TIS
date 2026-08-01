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


def update_customer(
    *,
    customer_id: str,
    email: str | None = None,
    name: str | None = None,
    custom_data: dict | None = None,
) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    if not cleaned_customer_id:
        raise ValueError("Paddle customer ID is required.")
    payload = {}
    if email is not None:
        cleaned_email = str(email or "").strip()
        if not cleaned_email:
            raise ValueError("Paddle customer email is required.")
        payload["email"] = cleaned_email
    if name is not None:
        payload["name"] = str(name or "").strip() or None
    if custom_data is not None:
        payload["custom_data"] = custom_data
    if not payload:
        raise ValueError("At least one Paddle customer field is required.")
    return _request(
        "PATCH",
        f"/customers/{cleaned_customer_id}",
        payload,
    )


def _address_payload(
    *,
    country_code: str,
    region: str | None = None,
    city: str | None = None,
    first_line: str | None = None,
    second_line: str | None = None,
) -> dict:
    payload = {"country_code": str(country_code or "").strip().upper()}
    for key, value in (
        ("region", region),
        ("city", city),
        ("first_line", first_line),
        ("second_line", second_line),
    ):
        cleaned = str(value or "").strip()
        payload[key] = cleaned or None
    return payload


def create_customer_address(
    *,
    customer_id: str,
    country_code: str,
    region: str | None = None,
    city: str | None = None,
    first_line: str | None = None,
    second_line: str | None = None,
) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    cleaned_country_code = str(country_code or "").strip().upper()
    if not cleaned_customer_id.startswith("ctm_"):
        raise ValueError("Paddle customer ID is required.")
    if len(cleaned_country_code) != 2 or not cleaned_country_code.isalpha():
        raise ValueError("A two-letter country code is required for Paddle checkout.")
    return _request(
        "POST",
        f"/customers/{cleaned_customer_id}/addresses",
        _address_payload(
            country_code=cleaned_country_code,
            region=region,
            city=city,
            first_line=first_line,
            second_line=second_line,
        ),
    )


def update_customer_address(
    *,
    customer_id: str,
    address_id: str,
    country_code: str,
    region: str | None = None,
    city: str | None = None,
    first_line: str | None = None,
    second_line: str | None = None,
) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    cleaned_address_id = str(address_id or "").strip()
    if not cleaned_customer_id.startswith("ctm_") or not cleaned_address_id.startswith("add_"):
        raise ValueError("Paddle customer and address IDs are required.")
    return _request(
        "PATCH",
        f"/customers/{cleaned_customer_id}/addresses/{cleaned_address_id}",
        _address_payload(
            country_code=country_code,
            region=region,
            city=city,
            first_line=first_line,
            second_line=second_line,
        ),
    )


def list_customer_addresses(*, customer_id: str) -> list[dict]:
    cleaned_customer_id = str(customer_id or "").strip()
    if not cleaned_customer_id.startswith("ctm_"):
        raise ValueError("Paddle customer ID is required.")
    return _request_list(
        "GET",
        f"/customers/{cleaned_customer_id}/addresses",
        params={"status": "active", "per_page": 200},
    )


def find_or_create_customer_address(
    *,
    customer_id: str,
    country_code: str,
    region: str | None = None,
    city: str | None = None,
    first_line: str | None = None,
    second_line: str | None = None,
) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    cleaned_country_code = str(country_code or "").strip().upper()
    if not cleaned_customer_id.startswith("ctm_"):
        raise ValueError("Paddle customer ID is required.")
    if len(cleaned_country_code) != 2 or not cleaned_country_code.isalpha():
        raise ValueError("A two-letter country code is required for Paddle checkout.")
    expected = _address_payload(
        country_code=cleaned_country_code,
        region=region,
        city=city,
        first_line=first_line,
        second_line=second_line,
    )
    for address in list_customer_addresses(customer_id=cleaned_customer_id):
        if (
            isinstance(address, dict)
            and str(address.get("status") or "active").strip().lower() == "active"
            and str(address.get("customer_id") or "").strip() == cleaned_customer_id
            and all(
                str(address.get(key) or "").strip().casefold()
                == str(value or "").strip().casefold()
                for key, value in expected.items()
            )
            and str(address.get("id") or "").strip().startswith("add_")
        ):
            return address
    return create_customer_address(
        customer_id=cleaned_customer_id,
        country_code=cleaned_country_code,
        region=region,
        city=city,
        first_line=first_line,
        second_line=second_line,
    )


def list_customer_businesses(*, customer_id: str) -> list[dict]:
    cleaned_customer_id = str(customer_id or "").strip()
    if not cleaned_customer_id.startswith("ctm_"):
        raise ValueError("Paddle customer ID is required.")
    return _request_list(
        "GET",
        f"/customers/{cleaned_customer_id}/businesses",
        params={"status": "active", "per_page": 200},
    )


def _business_payload(
    *,
    name: str,
    company_number: str | None = None,
    tax_identifier: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    custom_data: dict | None = None,
) -> dict:
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        raise ValueError("Paddle business name is required.")
    payload = {
        "name": cleaned_name,
        "company_number": str(company_number or "").strip() or None,
        "tax_identifier": str(tax_identifier or "").strip() or None,
        "contacts": [],
    }
    if custom_data:
        payload["custom_data"] = custom_data
    cleaned_email = str(contact_email or "").strip()
    if cleaned_email:
        payload["contacts"] = [{
            "name": str(contact_name or "").strip() or cleaned_name,
            "email": cleaned_email,
        }]
    return payload


def create_customer_business(*, customer_id: str, **details) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    if not cleaned_customer_id.startswith("ctm_"):
        raise ValueError("Paddle customer ID is required.")
    return _request(
        "POST",
        f"/customers/{cleaned_customer_id}/businesses",
        _business_payload(**details),
    )


def update_customer_business(
    *, customer_id: str, business_id: str, **details
) -> dict:
    cleaned_customer_id = str(customer_id or "").strip()
    cleaned_business_id = str(business_id or "").strip()
    if not cleaned_customer_id.startswith("ctm_") or not cleaned_business_id.startswith("biz_"):
        raise ValueError("Paddle customer and business IDs are required.")
    return _request(
        "PATCH",
        f"/customers/{cleaned_customer_id}/businesses/{cleaned_business_id}",
        _business_payload(**details),
    )


def bill_transaction(*, transaction_id: str) -> dict:
    cleaned_transaction_id = str(transaction_id or "").strip()
    if not cleaned_transaction_id.startswith("txn_"):
        raise ValueError("Paddle transaction ID is required.")
    return _request(
        "PATCH",
        f"/transactions/{cleaned_transaction_id}",
        {"status": "billed"},
    )


def get_transaction(*, transaction_id: str) -> dict:
    cleaned_transaction_id = str(transaction_id or "").strip()
    if not cleaned_transaction_id.startswith("txn_"):
        raise ValueError("Paddle transaction ID is required.")
    return _request("GET", f"/transactions/{cleaned_transaction_id}")


def _validate_ready_transaction(
    transaction: dict,
    *,
    price_id: str,
    quantity: int,
    expected_subtotal: int,
    quote_fingerprint: str,
) -> None:
    items = transaction.get("items")
    matching_items = [
        item
        for item in items
        if isinstance(item, dict)
        and str((item.get("price") or {}).get("id") or "").strip() == str(price_id or "").strip()
    ] if isinstance(items, list) else []
    if (
        len(matching_items) != 1
        or int(matching_items[0].get("quantity") or 0) != quantity
    ):
        raise PaddleAPIError("Paddle transaction items do not match the authoritative TIS quote.")
    totals = (transaction.get("details") or {}).get("totals") or {}
    try:
        subtotal = int(totals.get("subtotal"))
    except (TypeError, ValueError) as exc:
        raise PaddleAPIError("Paddle did not return a transaction subtotal.") from exc
    if subtotal != expected_subtotal:
        raise PaddleAPIError("Paddle transaction subtotal does not match the authoritative TIS quote.")
    custom_data = transaction.get("custom_data") or {}
    if str(custom_data.get("quote_fingerprint") or "").strip() != quote_fingerprint:
        raise PaddleAPIError("Paddle transaction quote fingerprint does not match TIS.")


def _validate_billed_checkout_transaction(
    transaction: dict,
    *,
    transaction_id: str,
    customer_id: str,
    address_id: str,
    business_id: str | None = None,
) -> None:
    checkout_url = str(((transaction.get("checkout") or {}).get("url")) or "").strip()
    if (
        str(transaction.get("id") or "").strip() != transaction_id
        or str(transaction.get("status") or "").strip().lower() != "billed"
        or str(transaction.get("collection_mode") or "").strip().lower()
        != "automatic"
        or str(transaction.get("customer_id") or "").strip() != customer_id
        or str(transaction.get("address_id") or "").strip() != address_id
        or (
            business_id is not None
            and str(transaction.get("business_id") or "").strip() != business_id
        )
        or not checkout_url
    ):
        raise PaddleAPIError(
            "Paddle transaction was not billed with a launchable checkout."
        )


def create_transaction(
    *,
    customer_id: str,
    price_id: str,
    quantity: int,
    country_code: str,
    expected_subtotal: int,
    quote_fingerprint: str,
    custom_data: dict | None = None,
    checkout_url: str | None = None,
    address_id: str | None = None,
    business_id: str | None = None,
    billing_address: dict | None = None,
) -> dict:
    try:
        validated_quantity = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Paddle transaction quantity must be a positive integer.") from exc
    if validated_quantity < 1:
        raise ValueError("Paddle transaction quantity must be a positive integer.")
    resolved_address_id = str(address_id or "").strip()
    if not resolved_address_id:
        address_kwargs = dict(billing_address or {})
        address = find_or_create_customer_address(
            customer_id=customer_id,
            country_code=country_code,
            **address_kwargs,
        )
        resolved_address_id = str(address.get("id") or "").strip()
    if not resolved_address_id.startswith("add_"):
        raise PaddleAPIError("Paddle did not create the checkout address.")
    cleaned_business_id = str(business_id or "").strip() or None
    if cleaned_business_id is not None and not cleaned_business_id.startswith("biz_"):
        raise ValueError("Paddle business ID is invalid.")
    normalized_custom_data = dict(custom_data or {})
    normalized_custom_data["quote_fingerprint"] = str(quote_fingerprint or "").strip()
    payload = {
        "customer_id": customer_id,
        "address_id": resolved_address_id,
        "business_id": cleaned_business_id,
        "items": [{"price_id": price_id, "quantity": validated_quantity}],
        "collection_mode": "automatic",
        "custom_data": normalized_custom_data,
        "checkout": {"url": checkout_url or None},
    }
    transaction = _request("POST", "/transactions", payload)
    transaction_id = str(transaction.get("id") or "").strip()
    if not transaction_id.startswith("txn_") or str(transaction.get("status") or "").strip() != "ready":
        raise PaddleAPIError("Paddle transaction did not reach ready state.")
    _validate_ready_transaction(
        transaction,
        price_id=price_id,
        quantity=validated_quantity,
        expected_subtotal=int(expected_subtotal),
        quote_fingerprint=str(quote_fingerprint or "").strip(),
    )
    billed_transaction = bill_transaction(transaction_id=transaction_id)
    _validate_billed_checkout_transaction(
        billed_transaction,
        transaction_id=transaction_id,
        customer_id=str(customer_id or "").strip(),
        address_id=resolved_address_id,
        business_id=cleaned_business_id,
    )
    return billed_transaction


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


def update_subscription_billing_identity(
    *,
    subscription_id: str,
    customer_id: str,
    address_id: str,
    business_id: str,
) -> dict:
    cleaned_subscription_id = str(subscription_id or "").strip()
    cleaned_customer_id = str(customer_id or "").strip()
    cleaned_address_id = str(address_id or "").strip()
    cleaned_business_id = str(business_id or "").strip()
    if not cleaned_subscription_id.startswith("sub_"):
        raise ValueError("Paddle subscription ID is required.")
    if not cleaned_customer_id.startswith("ctm_"):
        raise ValueError("Paddle customer ID is required.")
    if not cleaned_address_id.startswith("add_"):
        raise ValueError("Paddle address ID is required.")
    if not cleaned_business_id.startswith("biz_"):
        raise ValueError("Paddle business ID is required.")
    return _request(
        "PATCH",
        f"/subscriptions/{cleaned_subscription_id}",
        {
            "customer_id": cleaned_customer_id,
            "address_id": cleaned_address_id,
            "business_id": cleaned_business_id,
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
