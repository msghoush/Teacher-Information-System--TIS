---
title: On-Demand Timetable Generation Workflow
date: 2026-08-26
module: workforce-planning
---

# On-Demand Timetable Generation Workflow

Production timetable generation now provisions compute per durable run through a
Render Workflow task. Generate and Regenerate first commit the existing
`TimetableGenerationRun` and immutable snapshot. The server then starts the configured
task with only the run public ID; PostgreSQL remains authoritative for input, scope,
progress, cancellation, failure, and result.

The focused `timetable_generation_workflow.py` task claims exactly that queued run
and invokes the existing single-run executor. Existing leases and heartbeats reject
duplicate or late executors, and the atomic persistence service still rechecks
staleness and creates at most one unpublished candidate without changing the active
pointer. The solver, validator, regeneration diversity, locks, and Stage 5.2
publication/deletion/visibility rules are unchanged.

The web service uses `render==1.0.1` without OR-Tools. The Workflow runtime installs
`requirements-workflow.txt`, which adds pinned OR-Tools. Render task retries are set
to zero; deterministic and infrastructure outcomes become durable TIS terminal state,
and the user may Generate Again. Immediate dispatch failure ends an unclaimed run
safely. Cooperative database cancellation is retained; calling Render cancellation
is not required for this MVP.

Future Render setup is manual because Workflows are not currently represented by
Blueprints: configure the same repository/revision, `DATABASE_URL`, the TIS solver
settings, and task entry `timetable_generation_workflow:app`. Configure the web with
the server-only `RENDER_API_KEY` and `TIS_TIMETABLE_WORKFLOW_TASK_SLUG`. No Render
resource or production database was changed by this work.
