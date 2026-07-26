import os
import subprocess
import sys

import pytest
from fastapi import Request

import main


def test_render_import_defers_database_schema_initialization(tmp_path):
    database_path = tmp_path / "render-startup.db"
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "RENDER": "true",
            "TIS_SESSION_SECRET": "render-startup-test-secret-at-least-32-chars",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import main; "
                "assert main._defer_schema_initialization is True; "
                "assert main.app is not None"
            ),
        ],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


@pytest.mark.anyio
async def test_schema_readiness_gate_does_not_call_application_while_migration_is_pending():
    request = Request({"type": "http", "method": "GET", "path": "/login", "headers": []})
    application_called = False

    async def call_application(_request):
        nonlocal application_called
        application_called = True
        raise AssertionError("Application handler must remain gated.")

    main._schema_initialization_ready.clear()
    try:
        response = await main.database_schema_readiness_middleware(request, call_application)
    finally:
        main._schema_initialization_ready.set()

    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert application_called is False


def test_schema_becomes_ready_only_after_deferred_initialization_succeeds(monkeypatch):
    observed_ready_state = None

    def initialize_schema():
        nonlocal observed_ready_state
        observed_ready_state = main._schema_initialization_ready.is_set()

    monkeypatch.setattr(main, "_initialize_database_schema", initialize_schema)
    main._schema_initialization_ready.clear()
    main._schema_initialization_failure = None

    main._run_deferred_schema_initialization()

    assert observed_ready_state is False
    assert main._schema_initialization_ready.is_set()
    assert main._schema_initialization_failure is None


def test_failed_deferred_initialization_keeps_application_gated(monkeypatch):
    failure = RuntimeError("migration failed")

    def initialize_schema():
        raise failure

    monkeypatch.setattr(main, "_initialize_database_schema", initialize_schema)
    main._schema_initialization_ready.clear()
    main._schema_initialization_failure = None

    main._run_deferred_schema_initialization()

    assert not main._schema_initialization_ready.is_set()
    assert main._schema_initialization_failure is failure

    main._schema_initialization_ready.set()
