---
title: Versioned, Constraint-Based Smart Timetable Generation
documentation_version: 3.4
last_updated: 2026-08-26
status: accepted
module: workforce-planning
---

# ADR 0026: Versioned, Constraint-Based Smart Timetable Generation

## Context

The original Timetable stored one mutable set of placements per branch and academic year. It had no durable draft/history boundary, active-version authority, reproducible input snapshot, regeneration locks, or generation-run record. Automatic generation therefore could not be introduced safely without first separating Planning authority, timetable history, publication, and future solver execution.

## Decision

Migration `20260828_004_planning_subject_demands_foundation` introduces an additive
explicit per-section subject-demand table as the future Planning authority. Its
Stage 1 backfill is limited to grade-matched Subjects for Current/New sections in
the same branch/year. Stage 2 routes timetable readiness, workspace, immutable
snapshot, and snapshot-fed generation input through explicit-first section demand.
A missing explicit row alone uses `Subject.weekly_hours` as transitional fallback;
an inactive or zero row is authoritative retirement. Published and draft lifecycle
semantics do not change.

Planning remains authoritative for section demand, subject requirements, assigned teachers, and HRT fallback. A placement represents one teaching period, not a literal 60-minute hour. `PlanningSubjectDemand.weekly_periods` supplies explicit per-section requirements, with `Subject.weekly_hours` retained only as missing-row compatibility fallback. HRT fallback resolves the real section-subject demands; no generic HRT lesson replaces them.

Stage 3 introduces a read-only curriculum-adjustment preview before any future
late-stage demand mutation. It scopes Current/New sections by grade, explicit IDs,
or all active source uses; projects demand, teacher capacity, distribution rules,
grouped configuration, and mutable Draft impact; and returns a deterministic
authority fingerprint for future stale confirmation. It cannot write demand,
reassign teachers, regenerate a Draft, or mutate published history.

The timetable is a versioned aggregate scoped by SchoolGroup, Branch, and Academic Year. `TimetableVersion` owns placements, provenance, input authority, staleness, lifecycle, manual-edit, quality, and future solver metadata. Draft and non-active publication-ready versions may be edited. Active, superseded, and archived versions are immutable. `TimetableActiveVersion` is the sole active-selection authority and enforces one exact-scope pointer; active is not duplicated as a Boolean on a version.

The existing live timetable is imported exactly once per populated scope with `origin=imported`, a compatibility input snapshot, and an active pointer. Its placement fields are not repaired or normalized. Deterministically detectable inconsistencies are retained and recorded as safe version-level stale evidence. No historical publisher or approval is fabricated. A settings-only scope receives no empty imported version.

Until explicit version UI and publication arrive, the legacy assignment route uses copy-on-write: its first edit copies the active version to a mutable working draft, preserving locks and provenance; subsequent edits reuse that draft. Reads and exports use the operational version, preferring that compatibility draft after an edit while the imported active pointer continues to preserve the historical baseline.

Input snapshots use schema-versioned canonical JSON and SHA-256 component/full fingerprints. They record resolved Planning demand, HRT fallback decisions, timetable settings, canonical slot projection, constraints, and locks without unnecessary personal data. Stage 3.5 makes one composed timeline authoritative: each day starts at the configured shift time, retains the configured number and duration of teaching periods, inserts applicable non-teaching blocks, shifts later periods, and calculates the end. `after_period` is the preferred placement mode. Existing fixed-time blocks remain stored and compose only when their start is a current timeline boundary; ambiguous overlap fails closed without guessing or rewriting the row.

Locks persist on placements with actor and timestamp. A copied draft retains the intended locks. Later regeneration must treat locked placements as fixed decisions, but Stage 2 executes no regeneration.

Stage 4 exposes locks only on mutable drafts. Lock edits increment `edit_revision`,
return publication-ready drafts to draft, and refresh the immutable input snapshot
and authority fingerprint. Invalid locks remain visible and block validation.

Version review is selection-only. The compatibility operational order is the newest
mutable non-active draft in the exact scope, otherwise active, otherwise the newest
scoped mutable draft; a fresh manual draft therefore becomes the current customer
Draft Timetable. Archived and superseded versions are never arbitrary defaults. An
explicit copy is required before editing immutable history.

Draft validation checks freshness, complete demand, Planning teacher authority,
canonical slots, collisions, placement integrity, and locks without a solver.
Successful explicit administrator approval validates the exact draft, records its
actor and timestamp, and transitions it to `publication_ready`; generation alone is
not approval. Any later placement
or lock mutation returns it to `draft`. Publication locks the version and exact-scope
active pointer, checks edit/pointer revisions, reruns validation, supersedes the
previous active version, updates the pointer, and records actor/time atomically.
Regeneration preserves locked placements and requires the ceiling of 25 percent of
unlocked direct-source placements to change. If that hard diversity target is
infeasible, the run terminates with an explicit safe result; existing timetable hard
constraints are never weakened and no near-identical fallback is persisted.
Active status remains derived from the pointer rather than duplicated on the version.

`TimetableGenerationRun` is the durable PostgreSQL queue and reserves scope,
requester, Generate/Regenerate mode, source version/revision, snapshot,
solver/seed/diversity metadata, progress, attempts, lease/heartbeat, cancellation
audit, safe failure, result, and idempotency. A partial unique index permits only
one queued/running/validating/cancel-requested run per exact scope. The production
web path dispatches an on-demand Render Workflow task containing only the run public
ID. That task claims the exact queued row under a PostgreSQL lock, heartbeats its
lease, and rejects save attempts after lease loss. The former `SKIP LOCKED` polling
loop remains an optional local fallback, not a production requirement.

Stage 5.1 uses Google OR-Tools CP-SAT 9.15.6755 from a workflow-specific dependency
file; no normally loaded web module imports OR-Tools. Schema-v3 immutable snapshots
are the sole solve input. CP-SAT enforces exact demand, section and teacher slot
exclusivity, canonical teaching slots, fixed locks, and regeneration diversity.
Planning/HRT resolution happens before capture and remains subject-specific.

Generate creates a separate generated candidate. Regenerate leaves its source
unchanged, fixes locked lessons, excludes the exact source arrangement, and requires
the ceiling of the configured diversity percentage of unlocked placements to change
(25 percent by default). Seed is recorded only as a secondary reproducibility input.
A solver-independent validator checks scope,
authority, exact demand, collisions, slots, locks, fingerprints, source revision,
and diversity. A final current-input rebuild gates one atomic transaction that
creates a publication-ready unpublished version and entries and completes the run.
Generation never changes `TimetableActiveVersion` or published history.

Stage 5.2 preserves these internals but makes the newest mutable non-active version
the customer Draft Timetable. Delete Draft Timetable permanently removes eligible
never-published versions under exact-scope locks, preserves snapshots, runs, and
history, removes unpublished dependent versions child-first, reports protected
lineage, rejects active generation, and never changes the active pointer. Technical
version controls remain in secondary Timetable History.

Official non-management consumption is separate from operational resolution.
`timetable_visibility_service.py` resolves strictly through `TimetableActiveVersion`.
`/my-timetable` additionally requires exact-scope `User.user_id == Teacher.teacher_id`
identity and filters to that teacher; view-only users cannot consume mutable history.

Academic quality settings are exact-scope explicit subject-code authority captured
inside schema-v3 snapshots. CP-SAT implements daily core coverage when demand reaches
teaching days, distinct-day and non-consecutive preferences, optional hard ICT
one-per-day, and simultaneous configured Swimming groups. Group members may share
their configured common teacher in one slot, while unrelated teacher collisions and
optional shared-resource capacity remain protected. The independent validator repeats
all hard rules. Exports remain version-aware. Future teacher availability, broader
rooms/resources, and cross-campus coordination require separately approved stages.

## Rejected Alternatives

- Random-only generation: it cannot prove constraint satisfaction or explain infeasibility.
- Overwriting the active timetable during regeneration: it destroys operational history and rollback safety.
- Editing active or superseded versions in place: it makes publication evidence unreliable.
- Treating readiness as proof of solver feasibility: structurally complete input may still be mathematically infeasible.
- Running generation without explicit SchoolGroup, Branch, and Academic Year scope: it violates tenant safety.
- Maintaining separate preview, readiness, export, and future-solver clock calculations: competing time authority causes overlaps and stale fingerprints.

## Consequences

- Existing placements remain operational and historically preserved.
- Version numbering and active selection have database-enforced scope guarantees, with service validation for source/snapshot operations.
- Stage 3/3.5 implements composed canonical slot projection and structural readiness on stable snapshots; valid inserted blocks do not consume teaching-period indexes.
- Stage 4 implements version comparison and truthful publication without mutating active history. Stage 5.1 adds generation on this boundary without changing publication authority.
- PostgreSQL row locking plus a per-scope unique key is the version-number allocation authority; SQLite retains the unique guard for supported local tests.
- Stage 5.1 adds durable task execution, real phase polling, and independent validation. Production provisions one Render Workflow task per run and requires no always-on solver worker. Render automatic retries are disabled; TIS terminal state plus Generate Again is the sole retry authority. Stage 5.2 adds simplified workflow and published-only visibility. Academic-quality rules add mapped distribution and grouped activities without changing Workflow or publication authority.

## Related Files

- `models.py`
- `db_migrations.py`
- `timetable_snapshot_service.py`
- `timetable_version_service.py`
- `timetable_problem_builder.py`
- `timetable_cp_sat_solver.py`
- `timetable_solution_validator.py`
- `timetable_generation_service.py`
- `timetable_generation_worker.py`
- `timetable_generation_workflow.py`
- `timetable_workflow_dispatch.py`
- `timetable_visibility_service.py`
- `timetable_logic.py`
- `routers/timetable.py`
