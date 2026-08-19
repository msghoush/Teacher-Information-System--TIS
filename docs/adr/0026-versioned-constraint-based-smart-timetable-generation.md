---
title: Versioned, Constraint-Based Smart Timetable Generation
documentation_version: 3.1
last_updated: 2026-08-19
status: accepted
module: workforce-planning
---

# ADR 0026: Versioned, Constraint-Based Smart Timetable Generation

## Context

The original Timetable stored one mutable set of placements per branch and academic year. It had no durable draft/history boundary, active-version authority, reproducible input snapshot, regeneration locks, or generation-run record. Automatic generation therefore could not be introduced safely without first separating Planning authority, timetable history, publication, and future solver execution.

## Decision

Planning remains authoritative for section demand, subject requirements, assigned teachers, and HRT fallback. A placement represents one teaching period, not a literal 60-minute hour. Until a later approved migration introduces a new demand unit, `Subject.weekly_hours` supplies required weekly teaching periods. HRT fallback resolves the real section-subject demands; no generic HRT lesson replaces them.

The timetable is a versioned aggregate scoped by SchoolGroup, Branch, and Academic Year. `TimetableVersion` owns placements, provenance, input authority, staleness, lifecycle, manual-edit, quality, and future solver metadata. Draft and non-active publication-ready versions may be edited. Active, superseded, and archived versions are immutable. `TimetableActiveVersion` is the sole active-selection authority and enforces one exact-scope pointer; active is not duplicated as a Boolean on a version.

The existing live timetable is imported exactly once per populated scope with `origin=imported`, a compatibility input snapshot, and an active pointer. Its placement fields are not repaired or normalized. Deterministically detectable inconsistencies are retained and recorded as safe version-level stale evidence. No historical publisher or approval is fabricated. A settings-only scope receives no empty imported version.

Until explicit version UI and publication arrive, the legacy assignment route uses copy-on-write: its first edit copies the active version to a mutable working draft, preserving locks and provenance; subsequent edits reuse that draft. Reads and exports use the operational version, preferring that compatibility draft after an edit while the imported active pointer continues to preserve the historical baseline.

Input snapshots use schema-versioned canonical JSON and SHA-256 component/full fingerprints. They record resolved Planning demand, HRT fallback decisions, timetable settings, constraints, and locks without unnecessary personal data. Display-only timetable blocks remain presentation/configuration evidence and are not automatically promoted into solver constraints.

Locks persist on placements with actor and timestamp. A copied draft retains the intended locks. Later regeneration must treat locked placements as fixed decisions, but Stage 2 executes no regeneration.

`TimetableGenerationRun` reserves durable scope, requester, Generate/Regenerate mode, source version and revision, snapshot, solver/seed/diversity metadata, timing, lease/heartbeat, safe failure, result, and idempotency fields. Its statuses distinguish queued, running, validating, succeeded, infeasible, timed out, stale input, cancellation, internal error, and concurrent-run rejection.

Generate will create a new candidate from current authoritative input. Regenerate will create a new candidate from an explicit source/version context and must never overwrite the active timetable. Later regeneration should support controlled diversity through recorded seeds/preferences. Structural readiness is a deterministic prerequisite check; it is not proof of solver feasibility. Solver-independent validation must verify every candidate before it may become publication-ready. Hard constraints define validity; soft constraints affect quality only.

The initial future generator is branch-scoped. CP-SAT is the recommended solver approach, but no solver dependency is introduced by this decision's Stage 2 implementation. Long-running generation belongs in a future durable background-worker design with idempotency, leasing, heartbeat, cancellation, concurrency control, and safe failure reporting.

Exports are version-aware and preserve their current presentation. Future availability, rooms/resources, cross-campus coordination, normalized teaching/non-teaching slots, rule authoring, and generation preferences require separately approved stages and snapshot-schema evolution.

## Rejected Alternatives

- Random-only generation: it cannot prove constraint satisfaction or explain infeasibility.
- Overwriting the active timetable during regeneration: it destroys operational history and rollback safety.
- Editing active or superseded versions in place: it makes publication evidence unreliable.
- Treating readiness as proof of solver feasibility: structurally complete input may still be mathematically infeasible.
- Running generation without explicit SchoolGroup, Branch, and Academic Year scope: it violates tenant safety.
- Treating existing display-only timetable blocks as solver constraints: their current semantics were not designed as generation authority.

## Consequences

- Existing placements remain operational and historically preserved.
- Version numbering and active selection have database-enforced scope guarantees, with service validation for source/snapshot operations.
- Stage 3 may build readiness and constraint capture on stable snapshots without changing the current timetable UI.
- Stage 4 may add generation, version comparison, and truthful publication workflows without mutating active history.
- PostgreSQL row locking plus a per-scope unique key is the version-number allocation authority; SQLite retains the unique guard for supported local tests.

## Related Files

- `models.py`
- `db_migrations.py`
- `timetable_snapshot_service.py`
- `timetable_version_service.py`
- `timetable_logic.py`
- `routers/timetable.py`
