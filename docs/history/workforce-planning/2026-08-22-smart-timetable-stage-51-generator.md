---
title: Smart Timetable Stage 5.1 Generator
module: workforce-planning
date: 2026-08-22
knowledge_impact: yes
---

# Smart Timetable Stage 5.1 Generator

Stage 5.1 added real automatic timetable generation and regeneration. Google
OR-Tools CP-SAT 9.15.6755 is isolated to `requirements-worker.txt` and the dedicated
`python -m timetable_generation_worker` process. Web requests capture immutable
schema-v3 inputs and use the existing PostgreSQL generation-run table as a durable
queue with claim locking, leases, heartbeat, bounded recovery, cancellation,
progress, idempotency, and one active run per SchoolGroup/Branch/Academic Year.

The problem contract preserves exact section-subject-teacher weekly demand,
Planning and subject-specific HRT authority, composed Stage 3.5 teaching slots,
locks, fingerprints, and regeneration source state. CP-SAT enforces exact demand,
section/teacher exclusivity, locks, and explicit diversity. An OR-Tools-independent
validator and a final current-input/source-revision comparison gate persistence.

Successful generation atomically creates a separate unpublished publication-ready
version and all placements while leaving `TimetableActiveVersion` and published
history unchanged. Generate/Regenerate actions, real phase polling, safe terminal
messages, and `timetable.generate` are exposed now. Stage 5.2 simplification,
Delete Working Timetable, Timetable History simplification, teacher My Timetable,
and published-only teacher visibility remain deferred. No production action occurred.

On 2026-08-26, the production execution host changed to an on-demand Render Workflow
task. The solver pipeline and all durable safety described here remain unchanged;
`python -m timetable_generation_worker` is now only an optional local fallback and
`requirements-workflow.txt` is the production task dependency set.
