from __future__ import annotations

import os

from render import Retry, TaskContext, Workflows

from timetable_generation_worker import WorkerSettings, execute_generation_run


def _task_timeout_seconds() -> int:
    try:
        return min(
            max(int(os.getenv("TIS_TIMETABLE_WORKFLOW_TASK_TIMEOUT_SECONDS", "900")), 30),
            86400,
        )
    except (TypeError, ValueError):
        return 900


app = Workflows(
    # TIS terminal states and Generate Again are the retry authority. Render
    # must not independently multiply expensive solver attempts.
    default_retry=Retry(max_retries=0, wait_duration_ms=1000),
    default_timeout=_task_timeout_seconds(),
)


@app.task(name="generate-timetable")
def generate_timetable(
    _context: TaskContext,
    generation_run_public_id: str,
) -> dict[str, object]:
    executed = execute_generation_run(
        generation_run_public_id,
        WorkerSettings.from_environment(),
    )
    return {
        "generation_run_public_id": generation_run_public_id,
        "executed": executed,
    }


if __name__ == "__main__":
    app.start()
