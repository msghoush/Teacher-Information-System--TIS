import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RESEND_EMAILS_URL = "https://api.resend.com/emails"


class EmailDeliveryError(RuntimeError):
    pass


class EmailServiceNotConfigured(EmailDeliveryError):
    pass


def is_resend_configured() -> bool:
    return bool(str(os.getenv("RESEND_API_KEY") or "").strip())


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(str(os.getenv(name) or default).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _clean_address(value: str | None, setting_name: str) -> str:
    address = str(value or "").strip()
    if not address or "\r" in address or "\n" in address:
        raise EmailDeliveryError(f"{setting_name} is missing or invalid.")
    return address


def _safe_provider_detail(raw_body: bytes, api_key: str) -> str:
    detail = raw_body.decode("utf-8", errors="replace")[:1000].strip()
    if api_key:
        detail = detail.replace(api_key, "[redacted]")
    return detail or "No provider response body."


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str | None = None,
) -> str:
    api_key = str(os.getenv("RESEND_API_KEY") or "").strip()
    if not api_key:
        raise EmailServiceNotConfigured("RESEND_API_KEY is not configured.")

    sender = _clean_address(os.getenv("EMAIL_FROM"), "EMAIL_FROM")
    reply_to = _clean_address(os.getenv("EMAIL_REPLY_TO"), "EMAIL_REPLY_TO")
    recipient = _clean_address(to, "Recipient email")
    subject = str(subject or "").replace("\r", " ").replace("\n", " ").strip()
    if not subject:
        raise EmailDeliveryError("Email subject is required.")

    payload = {
        "from": sender,
        "to": [recipient],
        "reply_to": [reply_to],
        "subject": subject,
        "text": str(text or ""),
    }
    if html:
        payload["html"] = str(html)

    request = Request(
        RESEND_EMAILS_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "TIS-Platform/1.0",
        },
        method="POST",
    )
    timeout_seconds = _positive_int_env("RESEND_TIMEOUT_SECONDS", 12)

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_body = response.read()
            status_code = int(getattr(response, "status", 200) or 200)
    except HTTPError as exc:
        detail = _safe_provider_detail(exc.read(), api_key)
        raise EmailDeliveryError(
            f"Resend returned HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise EmailDeliveryError(
            f"Resend connection failed: {str(getattr(exc, 'reason', exc))[:300]}"
        ) from exc
    except OSError as exc:
        raise EmailDeliveryError(
            f"Resend transport failed: {exc.__class__.__name__}: {str(exc)[:300]}"
        ) from exc

    if not 200 <= status_code < 300:
        detail = _safe_provider_detail(raw_body, api_key)
        raise EmailDeliveryError(f"Resend returned HTTP {status_code}: {detail}")

    try:
        response_payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        response_payload = {}
    return str(response_payload.get("id") or "")
