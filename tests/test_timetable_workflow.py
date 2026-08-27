import sys
from pathlib import Path

import pytest

from timetable_workflow_dispatch import (
    TimetableWorkflowDispatchError,
    dispatch_timetable_generation,
    workflow_task_slug,
)


def test_workflow_slug_is_configuration_driven(monkeypatch):
    monkeypatch.setenv(
        "TIS_TIMETABLE_WORKFLOW_TASK_SLUG", "tis-generation/generate-timetable"
    )
    assert workflow_task_slug() == "tis-generation/generate-timetable"
    monkeypatch.delenv("TIS_TIMETABLE_WORKFLOW_TASK_SLUG")
    with pytest.raises(TimetableWorkflowDispatchError):
        workflow_task_slug()


def test_dispatch_passes_only_public_id_and_keeps_secret_server_side(monkeypatch):
    calls = []

    class FakeWorkflows:
        def start_task(self, slug, payload):
            calls.append((slug, payload))
            return type("TaskRun", (), {"id": "task-123"})()

    class FakeRender:
        def __init__(self):
            self.workflows = FakeWorkflows()

    fake_render_module = type(sys)("render")
    fake_render_module.Render = FakeRender
    monkeypatch.setitem(sys.modules, "render", fake_render_module)
    monkeypatch.setenv("RENDER_API_KEY", "server-secret")
    monkeypatch.setenv(
        "TIS_TIMETABLE_WORKFLOW_TASK_SLUG", "tis-generation/generate-timetable"
    )
    assert dispatch_timetable_generation("run-public-id") == "task-123"
    assert calls == [(
        "tis-generation/generate-timetable",
        {"generation_run_public_id": "run-public-id"},
    )]
    assert "server-secret" not in repr(calls)


def test_workflow_task_has_no_render_retries(monkeypatch):
    pytest.importorskip("render")
    pytest.importorskip("ortools")
    import timetable_generation_workflow as workflow

    task = workflow.app._registry.get_task("generate-timetable")
    assert task is not None
    assert task.options.retry.max_retries == 0
    calls = []
    monkeypatch.setattr(
        workflow,
        "execute_generation_run",
        lambda public_id, settings: calls.append(public_id) or False,
    )
    result = workflow.generate_timetable.func(None, "run-public-id")
    assert result == {"generation_run_public_id": "run-public-id", "executed": False}
    assert calls == ["run-public-id"]


def test_generated_version_redirect_is_honored_without_history_mode():
    route_source = (
        Path(__file__).resolve().parents[1] / "routers" / "timetable.py"
    ).read_text(encoding="utf-8")
    assert "if version:\n" in route_source
    assert "if version and history:" not in route_source
