---
title: M10 Organization Analytics REPEATABLE READ Transaction Boundary
documentation_version: 1.0
last_updated: 2026-09-09
status: accepted
module: architecture
---

# ADR 0029: M10 Organization Analytics REPEATABLE READ Transaction Boundary

## Context

ADR 0028 governed B11 production qualification and explicitly deferred any
PostgreSQL isolation change: "B11-D qualifies current `READ COMMITTED`
behavior first. `REPEATABLE READ` is not adopted preemptively. Stronger
isolation requires demonstrated inconsistency evidence and a governed ADR."

B11-D (`docs/history/engineering-handbook/2026-09-07-b11d-postgresql-concurrency-consistency-qualification.md`)
supplied that evidence. Under the current default `READ COMMITTED` behavior
(`database.py`'s single process-wide `SessionLocal = sessionmaker(autocommit=False,
autoflush=False, bind=engine)`, one `Session` per request via
`dependencies.get_db`, no explicit isolation level), PostgreSQL takes a fresh
snapshot per SQL statement, not per transaction. Every M10 Organization
Intelligence route builds one lazy population `Query` object once
(`talent_org_intelligence_service.frozen_membership_query`) and passes it to
two or more independent downstream calls, each issuing its own fresh SQL
statement. B11-D proved, live, against a dedicated non-production PostgreSQL
16.15 instance, that a real domain-valid write committed between two of a
route's own statements is observable within that same still-open request:

- **Overview**: `coverage_organization_total` (SQL#1) returned a population
  snapshot unaware of a write; `candidate_membership_counts` (SQL#2),
  executed moments later in the same request, returned a Candidate count
  aware of it (314 -> 315).
- **Student Drill**: `count_distinct_students` (the P7 eligibility gate,
  SQL#1) evaluated a population of 705 Students; `fetch_student_rows` (the
  identifiable page fetch, SQL#2) served a 706th Student not part of the
  gated population the gate decision was actually made against.

B11-D also proved, via an isolated `Connection.execution_options(isolation_level="REPEATABLE READ")`
experiment (never made permanent, never server-wide), that `REPEATABLE READ`
fully resolves both cases, and code-inspected `program-portfolio`,
`branches/{id}`, `talent-map`, and `longitudinal` as sharing the identical
structural mechanism (not independently reproduced live at that time). This
ADR's own qualification work (B11-E,
`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`)
independently reproduced the identical vulnerability live for all five of
those remaining routes as well, using a real, dedicated, non-production
PostgreSQL 16.15 database, confirming the required scope begins even earlier
than the two originally proven statement pairs: before `frozen_membership_query`
is even called, because the transaction's snapshot is already fixed by the
context/access-resolution statement that runs first in every route.

## Decision

Adopt `REPEATABLE READ` for the seven M10 Organization Intelligence routes
only (`overview`, `talent-map`, `program-portfolio`, `branches/{branch_id}`,
`participation-overlap`, `programs/{program_id}/longitudinal`, `students`),
via a dedicated session/dependency. This is the smallest change that resolves
every demonstrated inconsistency; no higher isolation level (e.g.
`SERIALIZABLE`) is adopted, because B11-D's and this ADR's own live
re-testing show `REPEATABLE READ` is sufficient.

### Why `READ COMMITTED` is insufficient

`READ COMMITTED`'s per-statement snapshot allows two statements inside the
same still-open, single-`Session` HTTP request to observe two different
committed database states whenever any concurrent write commits between
them. M10 routes structurally rely on one population `Query` object being
executed multiple times across the same request; B11-D and this ADR's own
qualification proved this is not merely theoretical for every one of the
seven routes.

### Why `REPEATABLE READ` is sufficient

PostgreSQL's `REPEATABLE READ` fixes one snapshot for the entire transaction
at its first statement. Every M10 route's first database statement is
context/access resolution (`talent_org_intelligence_service.resolve_access_context`,
called from `routers/talent_organization_analytics.py`'s `_b7_context`),
which happens before any population, aggregate, Candidate, Identification,
or privacy-closure-input read. Fixing the snapshot there guarantees every
later statement in the same request - including ones issued well after the
population `Query` object is built - observes that same snapshot. B11-D's
isolated experiment and this ADR's own live re-test (Phase 4 below)
confirmed this resolves every reproduced case with no other observed
behavior change.

### Exact scope

The dedicated session begins before the first relevant database statement of
the request (context/access resolution) and remains open for the request's
entire read set: Program/Branch/Academic-Year scope resolution, frozen
population reads, aggregate reads, Candidate inputs, Identification inputs,
Student Drill membership/page reads, longitudinal inputs, and privacy inputs.
Privacy/reconstruction-closure itself issues no SQL (confirmed by B11-D's
code reading, reconfirmed here), so it is automatically covered once every
SQL input it consumes shares one snapshot - no separate closure-specific
transaction handling is required.

This transaction boundary applies ONLY to the seven M10 Organization
Intelligence routes. It does not change the default, process-wide
`SessionLocal`/`get_db`/`database.engine` isolation used by every other route
or module in the application, and it does not apply server-wide (no
PostgreSQL server configuration change).

### Implementation mechanism

`database.py` adds `M10OrganizationAnalyticsSessionLocal`, a `sessionmaker`
bound to `engine.execution_options(isolation_level="REPEATABLE READ")` - a
shallow proxy that shares the same underlying connection pool as `engine`
but does not alter `engine`'s own default isolation for any other session.
This binding is strictly backend-conditional on `DATABASE_URL.startswith("postgresql")`;
on the SQLite fallback (`tis.db`, and every existing in-memory test fixture),
the M10 sessionmaker binds to the plain `engine` unchanged, because
SQLAlchemy's SQLite dialect does not accept a `REPEATABLE READ` isolation
level string. `dependencies.py` adds `get_m10_organization_analytics_db`, a
dependency generator mirroring `get_db`'s exact shape
(`SessionLocal() -> yield -> close()`). `routers/talent_organization_analytics.py`
uses this new dependency (`Depends(get_m10_organization_analytics_db)`)
instead of `Depends(get_db)` for all seven route functions; no other route in
the application is changed.

### Retry / error semantics

Not adopted. B11-D's evidence (zero deadlocks, zero lock-wait timeouts across
every tested concurrency scenario) and this ADR's own live re-testing
(zero serialization failures, zero deadlocks, across every reproduced
scenario and every one of the seven routes) do not demonstrate a practical
retry need for M10's read-only access pattern. `REPEATABLE READ` can in
principle raise a PostgreSQL `40001` serialization failure for read/write
conflict shapes not exercised by this qualification (M10 routes never write);
no retry logic is added speculatively. If future evidence shows a genuine
serialization-failure rate for this access pattern, that is a separate,
future governance decision with its own bounded retry-count/backoff
proposal - not implemented here.

### Observability implications

`talent_organization_analytics_observability.OrganizationAnalyticsObservation`
issues no SQL of its own and is unmodified by this change; a `database_failure`
telemetry classification already exists for any `sqlalchemy`-origin
exception (including a future serialization failure), so no observability
gap is introduced.

### Privacy/consistency implications

Every SQL input to `talent_analytics_relationship_graph`/
`talent_analytics_privacy_closure` now shares one fixed snapshot per request,
closing the specific reconstruction-relevant risk B11-D flagged as
unmeasured: a suppression decision evaluated against a raw value from one
statement while a relationship-linked sibling component was gathered from a
different, inconsistent snapshot. This ADR's own live testing (Phase 5,
using the existing non-production `DeterministicSuppressionTestPolicy`)
confirms this for both a standalone suppressed Cell and a
relationship-linked (complementary-suppression) pair.

### No unrelated change

No PostgreSQL server-wide isolation setting is changed. No other route's
session/transaction behavior is changed. No index, migration, schema,
permission, or entitlement change is made or implied by this ADR. No
numeric privacy threshold, breadth limit, performance SLO, or memory ceiling
is approved by this ADR - those remain governed by ADR 0028's Deferred
Decisions.

## Status

Accepted and implemented for the seven M10 Organization Intelligence routes
only (`database.py`, `dependencies.py`,
`routers/talent_organization_analytics.py`). B11-E qualification and live
re-testing are recorded in
`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`.
Independent review returned PASS WITH NON-BLOCKING OBSERVATIONS. B11-E
implementation is PASSED and checkpointable. As of 2026-09-09
(`docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`,
ADR 0028, ADR 0030), B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT
VERIFICATION ITEM REMAINING and B11 overall is CLOSED on that same basis; B12
is CLOSED.
