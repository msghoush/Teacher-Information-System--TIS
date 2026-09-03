"""Shared safe-redirect helpers usable by main.py and any router.

`safe_redirect_path` is the single open-redirect guard: it accepts only a
same-origin path starting with exactly one "/", rejecting absolute URLs
(`http://...`, `https://...`) and protocol-relative targets (`//...`). A
validated path may still carry its own `?query` and `#fragment` unchanged.

`redirect_with_notice`/`redirect_with_error` additionally inject a
`notice`/`error` query parameter while preserving a trailing `#fragment`,
since a fragment must stay after the query string in a valid URL.
"""
from urllib.parse import quote_plus

from fastapi.responses import RedirectResponse


def safe_redirect_path(path: str, default: str = "/dashboard") -> str:
    cleaned = str(path or "").strip()
    if not cleaned.startswith("/") or cleaned.startswith("//"):
        return default
    return cleaned


def redirect_with_notice(path: str, notice: str, default: str = "/dashboard") -> RedirectResponse:
    safe_path = safe_redirect_path(path, default)
    base_path, _, fragment = safe_path.partition("#")
    separator = "&" if "?" in base_path else "?"
    url = f"{base_path}{separator}notice={quote_plus(str(notice or '').strip())}"
    if fragment:
        url = f"{url}#{fragment}"
    return RedirectResponse(url=url, status_code=302)


def redirect_with_error(path: str, error: str, default: str = "/dashboard") -> RedirectResponse:
    safe_path = safe_redirect_path(path, default)
    base_path, _, fragment = safe_path.partition("#")
    separator = "&" if "?" in base_path else "?"
    url = f"{base_path}{separator}error={quote_plus(str(error or '').strip())}"
    if fragment:
        url = f"{url}#{fragment}"
    return RedirectResponse(url=url, status_code=302)
