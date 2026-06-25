import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jose import JWTError, jwt

import auth

OAUTH_STATE_COOKIE = "tis_saas_oauth_state"
OAUTH_PKCE_COOKIE = "tis_saas_oauth_pkce"
OAUTH_MAX_AGE_SECONDS = 600


def _base64url_encode(raw_value: bytes) -> str:
    return base64.urlsafe_b64encode(raw_value).rstrip(b"=").decode("ascii")


def _sha256_hexdigest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _public_base_url(request) -> str:
    configured = str(os.getenv("TIS_PUBLIC_BASE_URL") or "").strip()
    return (configured or str(request.base_url)).rstrip("/")


def _provider_config(provider: str) -> dict:
    cleaned = str(provider or "").strip().lower()
    if cleaned == "google":
        return {
            "provider": "google",
            "client_id_env": "GOOGLE_CLIENT_ID",
            "client_secret_env": "GOOGLE_CLIENT_SECRET",
            "discovery_url": "https://accounts.google.com/.well-known/openid-configuration",
            "scopes": ["openid", "email", "profile"],
            "issuer_aliases": {"accounts.google.com", "https://accounts.google.com"},
        }
    if cleaned == "microsoft":
        tenant = str(os.getenv("MICROSOFT_TENANT_ID") or "common").strip() or "common"
        return {
            "provider": "microsoft",
            "client_id_env": "MICROSOFT_CLIENT_ID",
            "client_secret_env": "MICROSOFT_CLIENT_SECRET",
            "discovery_url": f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
            "scopes": ["openid", "email", "profile"],
            "issuer_aliases": set(),
        }
    raise ValueError("Unsupported OAuth provider.")


def is_provider_configured(provider: str) -> bool:
    config = _provider_config(provider)
    return bool(
        str(os.getenv(config["client_id_env"]) or "").strip()
        and str(os.getenv(config["client_secret_env"]) or "").strip()
    )


def build_callback_url(request, provider: str) -> str:
    return f"{_public_base_url(request)}/saas/auth/{provider}/callback"


def _sign_payload(payload_b64: str) -> str:
    signature = auth.hmac.new(
        auth._session_secret().encode("utf-8"),
        payload_b64.encode("ascii"),
        auth.hashlib.sha256,
    ).digest()
    return _base64url_encode(signature)


def create_state_token(provider: str) -> str:
    payload = {
        "provider": str(provider or "").strip().lower(),
        "iat": int(time.time()),
        "nonce": secrets.token_urlsafe(16),
    }
    payload_b64 = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{payload_b64}.{_sign_payload(payload_b64)}"


def decode_state_token(token: str) -> dict | None:
    cleaned = str(token or "").strip()
    if "." not in cleaned:
        return None
    payload_b64, signature_b64 = cleaned.split(".", 1)
    if not auth.hmac.compare_digest(signature_b64, _sign_payload(payload_b64)):
        return None
    try:
        payload = json.loads(auth._base64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    issued_at = int(payload.get("iat") or 0)
    now = int(time.time())
    if issued_at <= 0 or issued_at > now + 300 or now - issued_at > OAUTH_MAX_AGE_SECONDS:
        return None
    return payload


def create_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def create_pkce_challenge(verifier: str) -> str:
    return _base64url_encode(hashlib.sha256(str(verifier or "").encode("utf-8")).digest())


def fetch_openid_configuration(provider: str) -> dict:
    config = _provider_config(provider)
    request = Request(
        config["discovery_url"],
        headers={"User-Agent": "TIS-Platform/1.0"},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def build_authorization_url(request, provider: str) -> tuple[str, str, str]:
    provider_config = _provider_config(provider)
    oidc = fetch_openid_configuration(provider)
    client_id = str(os.getenv(provider_config["client_id_env"]) or "").strip()
    if not client_id:
        raise RuntimeError(f"{provider_config['client_id_env']} is not configured.")
    state = create_state_token(provider)
    verifier = create_pkce_verifier()
    params = {
        "client_id": client_id,
        "redirect_uri": build_callback_url(request, provider),
        "response_type": "code",
        "scope": " ".join(provider_config["scopes"]),
        "state": state,
        "nonce": decode_state_token(state)["nonce"],
        "code_challenge": create_pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{oidc['authorization_endpoint']}?{urlencode(params)}", state, verifier


def exchange_code_for_tokens(request, provider: str, code: str, code_verifier: str) -> dict:
    provider_config = _provider_config(provider)
    oidc = fetch_openid_configuration(provider)
    client_id = str(os.getenv(provider_config["client_id_env"]) or "").strip()
    client_secret = str(os.getenv(provider_config["client_secret_env"]) or "").strip()
    payload = urlencode(
        {
            "grant_type": "authorization_code",
            "code": str(code or "").strip(),
            "redirect_uri": build_callback_url(request, provider),
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")
    http_request = Request(
        oidc["token_endpoint"],
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TIS-Platform/1.0",
        },
        method="POST",
    )
    with urlopen(http_request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def _verify_with_any_key(id_token: str, jwks: dict, *, audience: str, issuer: str):
    for key in jwks.get("keys", []):
        try:
            return jwt.decode(
                id_token,
                key,
                algorithms=[key.get("alg", "RS256"), "RS256"],
                audience=audience,
                issuer=issuer,
            )
        except JWTError:
            continue
    raise JWTError("Unable to verify the identity token.")


def verify_identity_token(provider: str, token_payload: dict, expected_nonce: str) -> dict:
    id_token = str(token_payload.get("id_token") or "").strip()
    if not id_token:
        raise JWTError("Identity token is missing.")
    provider_config = _provider_config(provider)
    oidc = fetch_openid_configuration(provider)
    jwks_request = Request(oidc["jwks_uri"], headers={"User-Agent": "TIS-Platform/1.0"})
    with urlopen(jwks_request, timeout=10) as response:
        jwks = json.loads(response.read().decode("utf-8"))
    client_id = str(os.getenv(provider_config["client_id_env"]) or "").strip()
    claims = _verify_with_any_key(
        id_token,
        jwks,
        audience=client_id,
        issuer=str(oidc.get("issuer") or "").strip(),
    )
    issuer_aliases = set(provider_config.get("issuer_aliases") or ())
    if issuer_aliases and str(claims.get("iss") or "").strip() not in issuer_aliases:
        raise JWTError("Identity token issuer is invalid.")
    if expected_nonce and str(claims.get("nonce") or "") != str(expected_nonce):
        raise JWTError("Identity token nonce mismatch.")
    return claims


def hash_secret(value: str) -> str:
    return _sha256_hexdigest(value)
