import os
import socket
import subprocess
import sys
import time

from fastapi.testclient import TestClient

import db_migrations
import main
from scripts import run_migrations


def _deployment_environment(database_path):
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
            "RENDER": "true",
            "TIS_SESSION_SECRET": "render-startup-test-secret-at-least-32-chars",
        }
    )
    return environment


def test_importing_main_does_not_run_migrations(tmp_path):
    database_path = tmp_path / "import.db"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import db_migrations; "
                "db_migrations.run_pending_migrations = "
                "lambda *_args, **_kwargs: (_ for _ in ()).throw("
                "AssertionError('web import ran migrations')); "
                "import main; assert main.app is not None"
            ),
        ],
        cwd=os.getcwd(),
        env=_deployment_environment(database_path),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not database_path.exists()


def test_pre_migration_metadata_defers_planning_subject_demands():
    table_names = {table.name for table in run_migrations._baseline_metadata_tables()}
    assert "planning_sections" in table_names
    assert "subjects" in table_names
    assert "planning_subject_demands" not in table_names


def test_fastapi_startup_does_not_run_migrations(monkeypatch):
    monkeypatch.setenv(
        "TIS_SESSION_SECRET",
        "render-startup-test-secret-at-least-32-chars",
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("FastAPI startup ran migrations")

    monkeypatch.setattr(db_migrations, "run_pending_migrations", fail_if_called)
    with TestClient(main.app):
        pass


def test_uvicorn_binds_without_in_process_migration(tmp_path):
    database_path = tmp_path / "uvicorn.db"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=os.getcwd(),
        env=_deployment_environment(database_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        bound = False
        while time.monotonic() < deadline and process.poll() is None:
            with socket.socket() as client:
                client.settimeout(0.2)
                if client.connect_ex(("127.0.0.1", port)) == 0:
                    bound = True
                    break
            time.sleep(0.1)
        assert bound, process.communicate(timeout=2)
        assert not database_path.exists()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_dedicated_migration_command_applies_pending_migrations(tmp_path):
    database_path = tmp_path / "migrations.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

    first = subprocess.run(
        [sys.executable, "scripts/run_migrations.py"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    second = subprocess.run(
        [sys.executable, "scripts/run_migrations.py"],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert first.returncode == 0, first.stderr
    assert "Applied migration:" in first.stderr
    assert second.returncode == 0, second.stderr
    assert "No pending migrations." in second.stderr


def test_dedicated_migration_command_returns_nonzero_on_failure(monkeypatch):
    monkeypatch.setattr(
        run_migrations.models.Base.metadata,
        "create_all",
        lambda **_kwargs: None,
    )

    def fail_migration(_engine):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(
        run_migrations.db_migrations,
        "run_pending_migrations",
        fail_migration,
    )

    assert run_migrations.run() == 1
