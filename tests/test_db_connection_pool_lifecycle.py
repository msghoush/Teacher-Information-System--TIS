"""Regression coverage for the production QueuePool-exhaustion incident.

Root cause: `main.inactivity_timeout_middleware` opened its own SQLAlchemy
session (`db = SessionLocal()`) and, because the `try/finally: db.close()`
wrapped the entire `await call_next(request)` call, held that connection
checked out for the full duration of every authenticated request - on top
of whatever connection the downstream route itself acquired via its own
`Depends(get_db)`. That silently doubled real per-request pool consumption
across the whole application (not only Talent) and, under concurrent
traffic such as the Student Assessments page's several parallel API calls
per load, exhausted the default `QueuePool` (size 5, overflow 10, timeout
30s) exactly as captured in the production traceback. It was not a classic
leak - `db.close()` always ran - but a long-held/duplicated connection
held far longer than the few quick queries it actually needed.

The fix moves `db.close()` to run immediately after the auth/idle-timeout/
commercial-access/route-permission checks complete, before `call_next` is
ever awaited, so this middleware's session is never open while the
downstream route runs.
"""
import asyncio

import pytest
from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

import main


class FakeURL:
    def __init__(self, path):
        self.path = path


class FakeRequest:
    def __init__(self, path, cookies=None):
        self.url = FakeURL(path)
        self.cookies = cookies or {}


class RecordingSession:
    """Wraps a real Session so close()/query() calls append to a shared
    timeline, letting the test prove the exact ordering relative to
    call_next - not just that close() eventually happens."""

    def __init__(self, real_session, events):
        self._real = real_session
        self._events = events

    def query(self, *args, **kwargs):
        self._events.append("query")
        return self._real.query(*args, **kwargs)

    def close(self):
        self._events.append("close")
        self._real.close()


@pytest.fixture()
def fake_user():
    class FakeUser:
        user_id = "U1"
        user_type = "tenant"
        role = "admin"
        is_active = True

    return FakeUser()


def _patch_common(monkeypatch, events, fake_user, *, session_user_id="U1"):
    monkeypatch.setattr(main.auth, "get_session_user_id", lambda request: session_user_id)
    monkeypatch.setattr(main.auth, "is_user_active", lambda user: True)
    monkeypatch.setattr(main.auth, "is_platform_user", lambda user: False)
    monkeypatch.setattr(main.auth, "get_current_user", lambda request, db: fake_user)
    monkeypatch.setattr(main.auth, "secure_cookie_kwargs", lambda request: {})
    monkeypatch.setattr(main.authorization, "enforce_workspace_commercial_access", lambda request, db, current_user=None: None)
    monkeypatch.setattr(main.authorization, "enforce_route_permission", lambda request, db, current_user=None: None)

    real_session = main.SessionLocal()
    real_session.query = lambda *a, **k: type("Q", (), {"filter": lambda self, *a, **k: self, "first": lambda self: fake_user})()
    recording = RecordingSession(real_session, events)
    monkeypatch.setattr(main, "SessionLocal", lambda: recording)
    return recording


def test_middleware_closes_its_session_before_call_next_is_invoked(monkeypatch, fake_user):
    events = []
    _patch_common(monkeypatch, events, fake_user)

    async def call_next(request):
        events.append("call_next_start")
        response = type("R", (), {"set_cookie": lambda self, **kw: None})()
        events.append("call_next_end")
        return response

    request = FakeRequest("/talent/assessments")
    asyncio.run(main.inactivity_timeout_middleware(request, call_next))

    # The middleware's own session must be fully closed before the
    # downstream handler (call_next) ever runs - this is the exact
    # ordering bug that doubled per-request pool consumption.
    close_index = events.index("close")
    call_next_index = events.index("call_next_start")
    assert close_index < call_next_index, f"session closed after call_next started: {events}"


def test_middleware_still_closes_session_when_call_next_raises(monkeypatch, fake_user):
    events = []
    _patch_common(monkeypatch, events, fake_user)

    async def failing_call_next(request):
        events.append("call_next_start")
        raise RuntimeError("downstream failure")

    request = FakeRequest("/talent/assessments")
    with pytest.raises(RuntimeError):
        asyncio.run(main.inactivity_timeout_middleware(request, failing_call_next))

    # Even though call_next raised, the middleware's session was already
    # closed beforehand (never held across call_next at all).
    assert events.index("close") < events.index("call_next_start")


def test_middleware_still_closes_session_when_permission_check_raises(monkeypatch, fake_user):
    events = []
    _patch_common(monkeypatch, events, fake_user)
    monkeypatch.setattr(
        main.authorization, "enforce_route_permission",
        lambda request, db, current_user=None: (_ for _ in ()).throw(RuntimeError("permission check failed")),
    )

    async def call_next(request):
        events.append("call_next_start")
        return type("R", (), {"set_cookie": lambda self, **kw: None})()

    request = FakeRequest("/talent/assessments")
    with pytest.raises(RuntimeError):
        asyncio.run(main.inactivity_timeout_middleware(request, call_next))

    # Exception path: the session is still released (via the surrounding
    # try/finally) and call_next is never reached.
    assert "close" in events
    assert "call_next_start" not in events


def test_middleware_still_sets_idle_timeout_cookie_after_session_is_closed(monkeypatch, fake_user):
    events = []
    _patch_common(monkeypatch, events, fake_user)
    cookies_set = []

    async def call_next(request):
        response = type("R", (), {"set_cookie": lambda self, **kw: cookies_set.append(kw)})()
        return response

    request = FakeRequest("/talent/assessments")
    response = asyncio.run(main.inactivity_timeout_middleware(request, call_next))

    assert response is not None
    assert cookies_set and cookies_set[0]["key"] == main.IDLE_TIMEOUT_COOKIE_KEY


def test_exempt_and_unauthenticated_requests_never_open_a_session(monkeypatch, fake_user):
    events = []
    _patch_common(monkeypatch, events, fake_user, session_user_id="")

    async def call_next(request):
        return "response"

    # No session cookie at all - the middleware must return immediately
    # without ever touching SessionLocal.
    response = asyncio.run(main.inactivity_timeout_middleware(FakeRequest("/talent/assessments"), call_next))
    assert response == "response"
    assert events == []


# ---------------------------------------------------------------------------
# Pool-level proof: reproduce the exact "middleware + route each hold a
# connection across the request" shape against a real, small QueuePool and
# confirm checked-out connections return to baseline and the pool is never
# exhausted under repeated/rapid load - matching the production traceback's
# pool_size=5/overflow=10 defaults at a scale a test can run quickly.
# ---------------------------------------------------------------------------
PoolLifecycleBase = declarative_base()


class Counter(PoolLifecycleBase):
    __tablename__ = "pool_lifecycle_counter"
    id = Column(Integer, primary_key=True)


def _make_pooled_session_factory(pool_size=2, max_overflow=1):
    engine = create_engine(
        "sqlite:///file:pool_lifecycle?mode=memory&cache=shared&uri=true",
        poolclass=QueuePool, pool_size=pool_size, max_overflow=max_overflow, pool_timeout=2,
        connect_args={"check_same_thread": False},
    )
    PoolLifecycleBase.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


async def _old_buggy_request(engine, factory, route_factory):
    """Simulates the pre-fix shape: the middleware's session stays open for
    the whole downstream call, on top of the route's own session."""
    middleware_db = factory()
    try:
        middleware_db.query(Counter).first()
        route_db = route_factory()
        try:
            route_db.query(Counter).first()
            await asyncio.sleep(0)  # the actual downstream work
        finally:
            route_db.close()
    finally:
        middleware_db.close()


async def _fixed_request(engine, factory, route_factory):
    """Simulates the fixed shape: the middleware's session is closed before
    the downstream call/route session is ever acquired."""
    middleware_db = factory()
    try:
        middleware_db.query(Counter).first()
    finally:
        middleware_db.close()
    route_db = route_factory()
    try:
        route_db.query(Counter).first()
        await asyncio.sleep(0)
    finally:
        route_db.close()


def test_fixed_request_shape_never_exceeds_pool_capacity_under_concurrency():
    engine, factory = _make_pooled_session_factory(pool_size=3, max_overflow=3)
    try:
        async def run():
            # 6 total connections available (pool_size=3 + overflow=3); each
            # fixed-shape request only ever needs 1 checked-out connection
            # at a time, so 6 fully concurrent requests must fit exactly.
            await asyncio.gather(*[_fixed_request(engine, factory, factory) for _ in range(6)])
        asyncio.run(run())
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_old_buggy_request_shape_exhausts_a_small_pool_under_concurrency():
    engine, factory = _make_pooled_session_factory(pool_size=3, max_overflow=3)
    try:
        async def run():
            # Same 6-connection budget; the buggy shape needs 2 connections
            # held simultaneously per in-flight request, so the same 6
            # concurrent requests (12 wanted-at-once connections) must
            # exceed capacity and raise a pool timeout - proving the
            # doubling was real and reproducing the production failure at
            # a scale a test can run quickly.
            await asyncio.gather(*[_old_buggy_request(engine, factory, factory) for _ in range(6)])
        with pytest.raises(Exception):
            asyncio.run(run())
    finally:
        engine.dispose()


def test_repeated_sequential_requests_return_to_baseline_checkout_count():
    engine, factory = _make_pooled_session_factory(pool_size=2, max_overflow=1)
    try:
        baseline = engine.pool.checkedout()
        for _ in range(20):
            asyncio.run(_fixed_request(engine, factory, factory))
            assert engine.pool.checkedout() == baseline
    finally:
        engine.dispose()
