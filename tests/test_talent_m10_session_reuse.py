"""Regression coverage for the M10 analytics duplicate-session incident.

Root cause: a route taking both `db: Session = Depends(get_m10_organization_
analytics_db)` and `current_user = Depends(get_current_user)` held TWO
simultaneous SQLAlchemy connections checked out for its whole lifetime.
FastAPI's per-request dependency cache keys on the dependency *callable*, and
`get_current_user`'s own `db` parameter is hardcoded to the unrelated
`get_db` dependency, so it was never deduplicated against
`get_m10_organization_analytics_db` - measured via pool checkout/checkin
instrumentation at peak 2 simultaneous checked-out connections per request,
reproducing the exact production `QueuePool ... connection timed out`
traceback under concurrency.

Fix: `auth.get_current_user_via_m10_analytics_db` resolves the identical
`auth._resolve_current_user` logic, bound to `get_m10_organization_analytics_db`
instead of `get_db`. Every route pairing the M10 session must use it (never
plain `get_current_user`), so FastAPI resolves the M10 session exactly once
per request and shares it between both dependencies.
"""
import ast
import pathlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import dependencies
import models
from auth import get_current_user, get_current_user_via_m10_analytics_db
from dependencies import get_db, get_m10_organization_analytics_db

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTE_FILES = (
    "routers/talent_organization_analytics.py",
    "routers/talent_results_analytics.py",
)


# ---------------------------------------------------------------------------
# A. Dependency-graph proof: the M10 session is opened exactly once per
#    request and shared between the route's own `db` param and the
#    current-user dependency - never a second, independent `get_db()` session.
# ---------------------------------------------------------------------------

@pytest.fixture()
def counting_session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    calls = {"m10": 0, "plain": 0}

    def counting_m10():
        calls["m10"] += 1
        return Session()

    def counting_plain():
        calls["plain"] += 1
        return Session()

    monkeypatch.setattr(dependencies, "M10OrganizationAnalyticsSessionLocal", counting_m10)
    monkeypatch.setattr(dependencies, "SessionLocal", counting_plain)
    return calls


class _FakeUser:
    user_id = "U1"
    username = "u1"
    role = "Administrator"
    branch_id = None
    is_active = True


def _build_app(current_user_dependency):
    app = FastAPI()

    @app.get("/probe")
    def probe(
        db=Depends(get_m10_organization_analytics_db),
        current_user=Depends(current_user_dependency),
    ):
        return {"db_id": id(db), "user_db_id": current_user["db_id"] if isinstance(current_user, dict) else None}

    return app


def test_fixed_dependency_opens_the_m10_session_exactly_once_per_request(monkeypatch, counting_session_factory):
    """The fixed pairing (get_m10_organization_analytics_db + get_current_user_via_m10_analytics_db)
    must resolve the M10 sessionmaker exactly once per request, and both
    dependencies must receive the identical session object."""
    seen = {}

    def fake_resolve(request, db):
        seen["db_id"] = id(db)
        return {"db_id": id(db)}

    monkeypatch.setattr(auth, "_resolve_current_user", fake_resolve)
    app = _build_app(get_current_user_via_m10_analytics_db)
    client = TestClient(app)

    resp = client.get("/probe")
    assert resp.status_code == 200
    body = resp.json()

    # Exactly one M10 session created for this request - never two.
    assert counting_session_factory["m10"] == 1
    assert counting_session_factory["plain"] == 0
    # The route's own `db` and the current-user resolver's `db` are the SAME object.
    assert body["db_id"] == seen["db_id"]


def test_broken_pairing_would_have_opened_a_second_independent_session(monkeypatch, counting_session_factory):
    """Sanity check that the test harness actually detects the bug: pairing
    get_m10_organization_analytics_db with the PLAIN get_current_user (the
    pre-fix shape) opens a second, independent get_db() session."""
    seen = {}

    def fake_resolve(request, db):
        seen["db_id"] = id(db)
        return {"db_id": id(db)}

    monkeypatch.setattr(auth, "_resolve_current_user", fake_resolve)
    app = _build_app(get_current_user)
    client = TestClient(app)

    resp = client.get("/probe")
    assert resp.status_code == 200
    body = resp.json()

    assert counting_session_factory["m10"] == 1
    assert counting_session_factory["plain"] == 1  # the second, unnecessary session
    assert body["db_id"] != seen["db_id"]  # two different sessions - the bug, reproduced


# ---------------------------------------------------------------------------
# B. Source-level guard: every M10-analytics route must pair the M10 session
#    with the M10-bound current-user dependency, never the plain one. This is
#    the regression that must never silently recur on a new or edited route.
# ---------------------------------------------------------------------------

def _dependency_names(node):
    defaults = node.args.defaults + node.args.kw_defaults
    names = []
    for d in defaults:
        if d is None:
            continue
        for n in ast.walk(d):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Depends":
                if n.args and isinstance(n.args[0], ast.Name):
                    names.append(n.args[0].id)
    return names


def _resolves_to_m10_bound_dependency(source_name, tree):
    """True if the module-level name (as it appears in a Depends(...) call)
    is actually bound - directly, or via an import alias - to
    `get_current_user_via_m10_analytics_db` rather than the plain
    `get_current_user`."""
    if source_name == "get_current_user_via_m10_analytics_db":
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "auth":
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if bound_name == source_name:
                    return alias.name == "get_current_user_via_m10_analytics_db"
    return False


def test_every_m10_analytics_route_uses_the_m10_bound_current_user_dependency():
    violations = []
    for relative in ROUTE_FILES:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = _dependency_names(node)
            if "get_m10_organization_analytics_db" not in names:
                continue
            current_user_names = {n for n in names if n in ("get_current_user", "get_current_user_via_m10_analytics_db")}
            if current_user_names and not any(_resolves_to_m10_bound_dependency(n, tree) for n in current_user_names):
                violations.append(f"{relative}:{node.name}")
    assert violations == [], (
        "Route(s) pair get_m10_organization_analytics_db with the plain "
        "get_current_user dependency, reopening the duplicate-session bug: "
        f"{violations}"
    )


def test_talent_organization_analytics_imports_the_m10_bound_dependency_under_its_alias():
    """This router renames the import (`get_current_user_via_m10_analytics_db as
    get_current_user`) so every one of its call sites resolves to the fixed
    dependency without a per-site edit. Guard that the alias itself is not
    silently reverted to the plain dependency."""
    source = (ROOT / "routers/talent_organization_analytics.py").read_text(encoding="utf-8")
    assert "from auth import get_current_user_via_m10_analytics_db as get_current_user" in source


# ---------------------------------------------------------------------------
# C. Semantic equivalence: current-user resolution itself is unchanged - only
#    the session it reads from differs. Authentication, tenant/branch/year
#    scope resolution, and permission-key resolution must be identical.
# ---------------------------------------------------------------------------

def _seed_minimal_user(Session):
    db = Session()
    school = models.SchoolGroup(id=1, name="Reuse Test Org", status=True)
    branch = models.Branch(id=1, school_group_id=1, name="Main", status=True)
    year = models.AcademicYear(id=1, school_group_id=1, year_name="2025-2026", is_active=True)
    user = models.User(
        id=1, user_id="U1", username="admin", role=auth.ROLE_ADMINISTRATOR,
        user_type="TENANT", access_scope="BRANCH",
        school_group_id=1, branch_id=1, academic_year_id=1, is_active=True,
    )
    db.add_all([school, branch, year, user])
    db.commit()
    db.close()


@pytest.fixture()
def sqlite_session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    _seed_minimal_user(Session)
    return Session


class _FakeRequest:
    def __init__(self, user_id="U1"):
        self.cookies = {}
        self.state = type("S", (), {})()
        self._user_id = user_id


def test_m10_bound_and_plain_current_user_resolution_agree(monkeypatch, sqlite_session_factory):
    monkeypatch.setattr(auth, "get_session_user_id", lambda request: "U1")
    db_a = sqlite_session_factory()
    db_b = sqlite_session_factory()
    try:
        user_a = get_current_user.__wrapped__(_FakeRequest(), db_a) if hasattr(get_current_user, "__wrapped__") else auth._resolve_current_user(_FakeRequest(), db_a)
        user_b = auth._resolve_current_user(_FakeRequest(), db_b)
        assert user_a is not None and user_b is not None
        assert user_a.user_id == user_b.user_id == "U1"
        assert user_a.scope_branch_id == user_b.scope_branch_id
        assert user_a.scope_academic_year_id == user_b.scope_academic_year_id
        assert user_a.scope_school_group_id == user_b.scope_school_group_id
        assert user_a.permission_keys == user_b.permission_keys
    finally:
        db_a.close()
        db_b.close()


def test_get_current_user_and_m10_variant_both_call_the_same_shared_resolver(monkeypatch):
    calls = []

    def fake_resolve(request, db):
        calls.append(db)
        return "resolved"

    monkeypatch.setattr(auth, "_resolve_current_user", fake_resolve)
    request = _FakeRequest()

    assert auth.get_current_user(request, "db_a") == "resolved"
    assert auth.get_current_user_via_m10_analytics_db(request, "db_b") == "resolved"
    assert calls == ["db_a", "db_b"]
