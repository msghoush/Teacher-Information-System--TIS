import os
from urllib.parse import quote

from fastapi import Request


LOCAL_PUBLIC_BASE_URL = "http://localhost:8000"


def is_production_like_environment() -> bool:
    env_value = str(
        os.getenv("TIS_ENV")
        or os.getenv("ENV")
        or os.getenv("FASTAPI_ENV")
        or ""
    ).strip().lower()
    return env_value in {"prod", "production", "live"}


def public_base_url(request: Request | None = None) -> str:
    configured = str(os.getenv("TIS_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    if is_production_like_environment():
        raise RuntimeError("TIS_PUBLIC_BASE_URL must be configured before generating production email URLs.")
    if request is not None:
        return str(request.base_url).rstrip("/")
    return LOCAL_PUBLIC_BASE_URL


def public_static_asset_url(static_path: str, request: Request | None = None) -> str:
    cleaned_path = str(static_path or "").strip().replace("\\", "/").lstrip("/")
    base_url = public_base_url(request)
    return f"{base_url}/static/{quote(cleaned_path, safe='/')}"
