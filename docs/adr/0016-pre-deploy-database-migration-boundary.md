---
title: ADR 0016 - Pre-Deploy Database Migration Boundary
documentation_version: 1.1
last_updated: 2026-09-09
status: accepted
---

# ADR 0016 - Pre-Deploy Database Migration Boundary

## Decision

The TIS FastAPI web process does not create database tables or execute pending
migrations during module import, FastAPI startup, middleware, request handling,
or background threads. Render executes `python scripts/run_migrations.py` as
the service Pre-Deploy Command. The command creates the repository's baseline
SQLAlchemy metadata schema while excluding tables owned by ordered migrations,
then executes
`db_migrations.run_pending_migrations(engine)`, logs newly applied migration
identifiers, and exits nonzero on any failure.

Render activates the new web version only after this command exits zero. The
web Start Command remains
`uvicorn main:app --host 0.0.0.0 --port $PORT`.

## Rationale

PostgreSQL DDL can wait on table locks for longer than Render's port-detection
window. Running DDL inside the web process couples schema lock duration to
service availability and previously required a process-local readiness gate.
A platform pre-deploy step provides the required ordering without exposing a
partially migrated schema or delaying Uvicorn's bind.

## Consequences

- Every deployment must configure the migration command before the Start
  Command is allowed to activate.
- Migration failure blocks deployment with a nonzero exit code.
- Repeated execution is safe because metadata creation is check-first and the
  ordered migration ledger is idempotent.
- Student/Talent tables are owned by the ordered ledger and excluded from
  baseline metadata creation. Migration `20260904_000` establishes legacy
  Branch/Academic-Year/existing-Student composite unique parent keys before
  `20260904_001` creates tenant-scoped Student relationships.
- A migration and its ledger marker share one transaction. Duplicate
  prerequisite data or invalid DDL therefore fails without a marker or data
  rewrite and blocks web activation.
- PostgreSQL connections use a 10-second connection timeout, 5-second lock
  timeout, and 30-second statement timeout before baseline metadata or ledger
  DDL begins. Migration-local protections remain effective.
- Flushed logs identify connection, metadata, ledger, per-migration apply,
  marker, and commit progress. Timeout failures exit nonzero.
- Schema inspection performed during a migration transaction uses that
  transaction's active SQLAlchemy `Connection`, never a secondary connection
  checked out through the `Engine`.
- The former daemon migration worker and readiness middleware are removed.
