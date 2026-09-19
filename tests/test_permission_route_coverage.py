"""Mutating / state-changing route authorization coverage enumeration.

Enumerates the real `main.app` route table (all included routers) and asserts that
every non-GET route, and every GET route that exports/streams data or changes state,
is authorised by (in order of evidence):

  MW        an `authorization.PROTECTED_ROUTE_RULES` middleware rule
  HANDLER   a permission guard call in the handler body itself
  HELPER    a permission guard reached through a same-module helper
  PLATFORM  a platform-identity guard (Owner/Developer)
  SAAS      a SaaS-account session guard (separate SaaS account auth domain)
  ALLOWLIST an explicit reviewed allowlist entry with a reason

Anything else fails the test, so a NEW route without a guard must be reviewed.
Static reachability of a guard is necessary, not sufficient, evidence; runtime denial
is proven separately (middleware rules here, handlers in test_permission_surface_*).
"""
import collections
import inspect
import re

import authorization
import permission_registry
from tests import permission_audit_support as support

PERMISSION_GUARD_NAME = re.compile(
    r"^(has_(any_|all_)?permission|require_(any_|all_)?permission|_authorize\w*|_?can_\w+"
    r"|_get_\w*_access|_require_promo_permission|require_capacity_change)$"
)
PLATFORM_GUARD_NAME = re.compile(
    r"^(_get_platform_owner_access|_require_platform_owner|_require_workspace_analyzer"
    r"|is_platform_owner|is_primary_platform_owner|is_platform_developer)$"
)
SAAS_GUARD_NAME = re.compile(
    r"^(_require_account|_require_verified_account|_current_account|get_current_account"
    r"|_require_saas_csrf|_require_org)$"
)

# Reviewed public / pre-authentication / scope-selector endpoints. (method, path) -> reason
ALLOWLIST = {
    ("GET", "/"): "Public landing / login entrypoint.",
    ("GET", "/login"): "Public login page.",
    ("POST", "/login"): "Authentication endpoint (credential check).",
    ("POST", "/forgot-password"): "Public password-reset request.",
    ("GET", "/logout"): "Ends the caller's own session; no data access.",
    ("POST", "/request-demo"): "Public demo request form (anti-abuse in SaaS service).",
    ("GET", "/favicon.ico"): "Static asset.",
    ("GET", "/demo-expired"): "Static commercial notice page (no tenant data).",
    ("GET", "/commercial-access-ended"): "Static commercial notice page (no tenant data).",
    ("GET", "/api/locations/countries"): "Reference geography lookup, authenticated read-only, no tenant data.",
    ("GET", "/api/locations/regions"): "Reference geography lookup, authenticated read-only, no tenant data.",
    ("GET", "/api/locations/cities"): "Reference geography lookup, authenticated read-only, no tenant data.",
    ("GET", "/platform/account/verify-email"): "Token-verified email confirmation link for the platform owner.",
    ("GET", "/openapi.json"): "FastAPI docs (public path in authorization.PUBLIC_PATH_PATTERNS).",
    ("GET", "/docs"): "FastAPI docs (public path in authorization.PUBLIC_PATH_PATTERNS).",
    ("GET", "/docs/oauth2-redirect"): "FastAPI docs.",
    ("GET", "/redoc"): "FastAPI docs (public path in authorization.PUBLIC_PATH_PATTERNS).",
    ("POST", "/scope/academic-year"): "Scope selector; validates target year belongs to the actor's authoritative scope.",
    ("POST", "/scope/branch"): "Scope selector; restricted to all-branch access scopes and accessible-branch query.",
    ("POST", "/saas/webhooks/paddle"): "Provider webhook; authenticated by signature verification, not a session.",
}
_SAAS_PUBLIC_PATHS = {
    "/saas/payment": "Provider-hosted checkout launcher; validates the transaction id server-side.",
    "/saas/auth/login": "SaaS pre-authentication redirect.",
    "/saas/auth/forgot-password": "SaaS pre-authentication password reset request.",
    "/saas/auth/reset-password": "SaaS token-based password reset.",
    "/saas/auth/signup": "SaaS pre-authentication signup.",
    "/saas/auth/logout": "Ends the caller's own SaaS session.",
    "/saas/auth/verification-sent": "SaaS pre-authentication notice page.",
    "/saas/auth/verification-required": "SaaS pre-authentication notice page.",
    "/saas/auth/verify-email": "Token-based email verification link.",
    "/saas/auth/resend-verification": "SaaS pre-authentication verification resend.",
    "/saas/auth/{provider}/start": "SaaS OAuth start (pre-authentication).",
}
ALLOWLIST.update({("GET", p): r for p, r in _SAAS_PUBLIC_PATHS.items()})
ALLOWLIST.update({("POST", p): r for p, r in _SAAS_PUBLIC_PATHS.items()})
_SERVICE_LAYER_PREFIXES = {
    "/api/talent/organization-analytics": (
        "Guarded in the service layer: talent_org_intelligence_service.resolve_access_context "
        "requires talent_analytics.view (+ capability keys) before any data is read."
    ),
}


def _classify(method, path, endpoint):
    rule = authorization._find_permission_rule(support.sample_path(path), method)
    if rule:
        return "MW", ""
    if (method, path) in ALLOWLIST:
        return "ALLOWLIST", ALLOWLIST[(method, path)]
    for prefix, reason in _SERVICE_LAYER_PREFIXES.items():
        if path.startswith(prefix):
            return "ALLOWLIST", reason
    module = inspect.getmodule(endpoint)
    own_node = support._module_info(module).get(endpoint.__name__)
    own = support._names_in(own_node) if own_node is not None else set()
    closure, _consts = support.handler_closure(endpoint)
    closure = closure or set()
    if any(PERMISSION_GUARD_NAME.match(name) for name in own):
        return "HANDLER", ""
    if any(PLATFORM_GUARD_NAME.match(name) for name in own):
        return "PLATFORM", ""
    if any(PERMISSION_GUARD_NAME.match(name) for name in closure):
        return "HELPER", ""
    if any(PLATFORM_GUARD_NAME.match(name) for name in closure):
        return "PLATFORM", ""
    if path.startswith(("/saas", "/saas-admin")) and any(SAAS_GUARD_NAME.match(name) for name in closure | own):
        return "SAAS", ""
    if path.startswith(("/saas", "/saas-admin")) and any(PLATFORM_GUARD_NAME.match(n) for n in closure | own):
        return "PLATFORM", ""
    return "UNCOVERED", ""


def _enumerate():
    return [(m, p, e, *_classify(m, p, e)) for m, p, e in support.all_routes()]


def _is_state_changing_or_export(method, path):
    if method != "GET":
        return True
    return bool(re.search(r"export|download|delete|\.xlsx|\.pdf|template", path, re.I))


def test_route_table_enumerates_the_whole_application():
    routes = support.all_routes()
    # Pin the audited size loosely: a large drop means enumeration silently broke.
    assert len(routes) >= 450
    methods = collections.Counter(m for m, _p, _e in routes)
    assert methods["POST"] >= 200 and methods["GET"] >= 200


def test_every_route_is_covered_or_explicitly_allowlisted():
    uncovered = [(m, p) for m, p, _e, cls, _r in _enumerate() if cls == "UNCOVERED"]
    assert uncovered == [], f"Routes with no reviewed authorization evidence: {uncovered}"


def test_every_state_changing_or_export_route_has_real_evidence():
    weak = [
        (m, p, cls)
        for m, p, _e, cls, _r in _enumerate()
        if _is_state_changing_or_export(m, p) and cls in {"UNCOVERED"}
    ]
    assert weak == []


def test_allowlist_entries_are_real_routes_and_have_reasons():
    real = {(m, p) for m, p, _e in support.all_routes()}
    stale = [
        key
        for key in ALLOWLIST
        if key not in real
        and key[1] not in {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
        and not (key[1] in _SAAS_PUBLIC_PATHS)
    ]
    assert stale == []
    assert all(ALLOWLIST.values())


def test_middleware_rules_reference_only_registered_keys_and_real_routes():
    registered = set(permission_registry.ALL_PERMISSION_KEYS)
    for rule in authorization.PROTECTED_ROUTE_RULES:
        assert set(rule.permission_keys) <= registered
        assert rule.match in {"all", "any"}


def test_middleware_rule_denies_a_user_without_the_required_keys(monkeypatch):
    """Runtime proof for every middleware-covered route: with an empty effective
    permission set the real `enforce_route_permission` returns a denial (never None)."""
    from starlette.requests import Request

    import auth
    import main

    class _User:
        id = 1
        is_active = True
        role = "Limited"
        user_type = "tenant"
        school_group_id = 1

    monkeypatch.setattr(auth, "get_allowed_permission_keys", lambda *a, **k: set())
    monkeypatch.setattr(auth, "is_platform_owner", lambda user: False)
    monkeypatch.setattr(auth, "is_user_active", lambda user: True)
    monkeypatch.setattr(authorization, "build_shell_context", lambda *a, **k: {})
    monkeypatch.setattr(
        authorization,
        "build_access_denied_response",
        lambda *a, **k: "DENIED",
    )
    checked = 0
    for method, path, _endpoint in support.all_routes():
        rule = authorization._find_permission_rule(support.sample_path(path), method)
        if rule is None:
            continue
        scope = {
            "type": "http", "http_version": "1.1", "method": method,
            "path": support.sample_path(path), "raw_path": support.sample_path(path).encode(),
            "query_string": b"", "headers": [(b"host", b"testserver")], "scheme": "http",
            "server": ("testserver", 80), "client": ("testclient", 5000), "root_path": "",
            "app": main.app,
        }
        result = authorization.enforce_route_permission(Request(scope), None, current_user=_User())
        assert result == "DENIED", (method, path)
        checked += 1
    assert checked >= 130


def test_route_coverage_class_counts_are_reported_and_stable():
    counts = collections.Counter(cls for *_rest, cls, _r in [(r[0], r[1], r[2], r[3], r[4]) for r in _enumerate()])
    assert counts["UNCOVERED"] == 0
    assert counts["MW"] >= 130
    assert counts["HANDLER"] >= 100
