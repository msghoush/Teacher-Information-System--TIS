from __future__ import annotations

import os


class TimetableWorkflowDispatchError(RuntimeError):
    """Safe boundary error for an unsuccessful Render task start request."""


def workflow_task_slug() -> str:
    slug = os.getenv("TIS_TIMETABLE_WORKFLOW_TASK_SLUG", "").strip()
    if not slug or "/" not in slug:
        raise TimetableWorkflowDispatchError(
            "Timetable generation service is not configured."
        )
    return slug


def dispatch_timetable_generation(generation_run_public_id: str) -> str:
    """Start one Render Workflow task without importing solver dependencies."""
    if not os.getenv("RENDER_API_KEY", "").strip():
        raise TimetableWorkflowDispatchError(
            "Timetable generation service is not configured."
        )
    try:
        from render import Render

        task_run = Render().workflows.start_task(
            workflow_task_slug(),
            {"generation_run_public_id": generation_run_public_id},
        )
        return str(task_run.id)
    except TimetableWorkflowDispatchError:
        raise
    except Exception as exc:
        raise TimetableWorkflowDispatchError(
            "Timetable generation service could not be started."
        ) from exc
