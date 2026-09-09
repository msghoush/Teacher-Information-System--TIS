---
title: M10 B11-D PostgreSQL Concurrency And Consistency Qualification
module: engineering-handbook
last_updated: 2026-09-07
---

# 2026-09-07 - M10 B11-D PostgreSQL Concurrency And Consistency Qualification

Module:
Talent & Potential M10 Organization Analytics, PostgreSQL concurrency/
consistency qualification (ADR 0028, B11-D entry)

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-09-07 - M10 B11-D PostgreSQL Concurrency And
Consistency Qualification

Related ADRs:
`docs/adr/0028-b11-production-qualification-policy.md` (governing authority
for B11-D entry criteria, isolation-change gate, and B11-E release gate)

Related prior evidence:
`docs/history/engineering-handbook/2026-09-07-b11c-postgresql-profiling-evidence-remediation.md`
(B11-C dataset-builder pattern, non-production provider convention, Index
Candidate A/B baseline, statistics-freshness cold-start finding)

Reviewer/approval notes:
This is a CONCURRENCY/CONSISTENCY QUALIFICATION task only. It does not
redesign M10, does not implement B11-E, does not implement B12, and does not
merge or deploy. It does not change PostgreSQL isolation permanently, does
not add an index, does not add a migration, and does not choose any
production threshold, breadth limit, SLO, memory ceiling, or commercial
mapping. The evidence-gathering pass did not itself declare closure; subsequent
independent review returned **PASS WITH NON-BLOCKING OBSERVATIONS**, so this
governed checkpoint marks B11-D **CLOSED**. No merge or deployment occurred.
`tis.db` was not touched (confirmed unchanged before and
after this task, including after running the pytest regression suite below).
All measurement used the dedicated non-production `tis_b11c_test_db`
PostgreSQL 16.15 instance at `127.0.0.1`, reached only through the
`TIS_TEST_POSTGRESQL_URL` environment variable (never printed, logged, or
persisted anywhere in this repository), inside ephemeral per-phase schemas
created and dropped by the harness - no rows were left behind in the shared
test database.

Governing checkpoint for this task: `dev`/`origin-dev`
`793c78c882624a7f63402aafe4150d3f69d3132b`.

## Working-Tree Integrity Note (Observed During This Task, Not Authored By It)

While this task was running, `git status` showed several additional
already-tracked KMS files change from clean to uncommitted mid-session
(`docs/adr/0028-b11-production-qualification-policy.md`,
`docs/engineering/USER_AND_SYSTEM_FLOWS.md`, and this document's own
predecessor
`docs/history/engineering-handbook/2026-09-07-b11c-postgresql-profiling-evidence-remediation.md`),
extending the same "B11-C CLOSED -> reverted to NOT CLOSED" /
"M10 B11 Qualification And Release Flow section deleted" pattern already
disclosed as a pre-existing, unresolved discrepancy in the B11-C artifact's
own Files-Touched section (there scoped to `docs/adr/README.md`,
`docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`, and
`docs/PROJECT_STATE.md`/`docs/TIS_MASTER_CONTEXT.md`/`docs/CHANGE_HISTORY.md`).
This task did not author, investigate the origin of, revert, or resolve any
of this; per the delegated task's explicit Repository Safety instruction, all
of it is preserved completely untouched. This document's own Status/Current
Milestone Truth wording below intentionally follows the delegating task's
stated premise (this checkpoint's committed history records B11-C CLOSED) and
is written additively (a new file, plus small additive edits elsewhere) so it
neither depends on nor further disturbs whichever wording of the pre-existing
in-progress edit is present in the working tree at merge time. The repository
owner's explicit reconciliation of the underlying discrepancy is still
required before any commit, exactly as the B11-C artifact already stated.

## Current Milestone Truth

- B0-B10: CLOSED. B11-A: complete. B11-B: CLOSED. B11 production-
  qualification policy (ADR 0028): APPROVED/GOVERNED.
- B11-C: PostgreSQL profiling executed; durable evidence captured in the
  linked B11-C artifact, per this checkpoint's governing history.
- B11-D (this document): PostgreSQL concurrency/consistency qualification
  **executed**; durable evidence **captured**. Independent review:
  **PASS WITH NON-BLOCKING OBSERVATIONS**. B11-D is **CLOSED**.
- No index, migration, permission, entitlement, privacy-semantics change,
  production SLO, production privacy threshold, production breadth limit,
  production memory ceiling, or PostgreSQL isolation change is approved by
  this document.
- B11-E: NOT COMPLETE. B11 overall: NOT CLOSED. B12: NOT IMPLEMENTED.
  Production readiness: NOT achieved.

## Objective

Qualify the seven M10 Organization Intelligence routes under realistic
concurrent read/write PostgreSQL behavior, starting with the current/default
`READ COMMITTED` behavior as ADR 0028 requires, and determine whether M10
query-on-read analytics preserve acceptable consistency under concurrent
application activity, and whether a stronger transaction boundary or
isolation level is actually justified by evidence.

## Phase 0 - Connection Verification (Non-Production)

| Check | Result |
|---|---|
| `TIS_TEST_POSTGRESQL_URL` present in process environment | Yes |
| Connection succeeds | Yes |
| `SELECT version()` | `PostgreSQL 16.15, compiled by Visual C++ build 1944, 64-bit` |
| `SELECT current_database()` | `tis_b11c_test_db` |
| `SELECT inet_server_addr()` | `127.0.0.1` (localhost only) |
| `SHOW transaction_isolation` (server default) | `read committed` |
| Environment | Non-production (dedicated `tis_b11c_test_db`/`tis_b11c_test_role`, localhost-only) |

## Methodology (Reproducible)

Reuses the B11-C pattern exactly: `models.Base.metadata.create_all(engine)`
against an ephemeral, per-phase PostgreSQL schema (`search_path`-scoped, one
`CREATE SCHEMA`/`DROP SCHEMA ... CASCADE` per phase, no rows left behind);
the real M10 routers/services (`routers/talent_organization_analytics.py`,
`talent_org_intelligence_service.py`, `talent_org_talent_map.py`,
`talent_org_b7.py`, `talent_org_participation_overlap.py`,
`talent_org_student_drill.py`, `talent_org_longitudinal.py`) mounted on an
isolated `FastAPI()` app via `fastapi.testclient.TestClient` with
`dependency_overrides` for `get_db`, `get_current_user`, and the same three
non-production provider doubles the existing test suite already uses
(`AllowAvailability`, `AllowBreadth`, `talent_analytics_privacy.AllowAllTestPolicy`
- explicitly labeled NON-PRODUCTION; no production privacy/availability/
breadth provider exists yet per ADR 0028, so every measured behavior reflects
the SQL/ORM/session/transaction/privacy-closure code that exists today, not a
future production threshold decision); a seeded `random.Random(20260907)`
synthetic dataset builder using the exact same field/relationship shape as
B11-C's (bulk `sa.insert(...)` for Student/Placement/PopulationMember/
Assessment/Candidate/Identification rows, one primary `SchoolGroup` plus one
tiny isolated foreign `SchoolGroup` tenant-isolation control).

**New for B11-D (concurrency-specific):** (1) real `threading`-based
concurrent reader/writer scenarios against `TestClient` calls sharing one
SQLAlchemy `Engine`/connection pool, each `client.get(...)` opening its own
per-request `Session` exactly the way the real `dependencies.get_db`
dependency does (`SessionFactory()` -> `yield` -> `.close()`); (2) direct
calls into the identical production service functions
(`talent_org_intelligence_service.*`, `talent_org_student_drill.*`) in a
single, deliberately-held-open reader `Session`/transaction, with a real,
separately-committing writer `Session` interleaved between two of those
calls, to prove or disprove cross-statement snapshot divergence without
relying on non-deterministic thread-timing races; (3) an isolated
`REPEATABLE READ` experiment using `Connection.execution_options(isolation_level=...)`
on the reader connection only, never a server-wide or application-wide
change; (4) a `LockObserver` classifying every writer-thread SQLAlchemy
exception into deadlock / lock-timeout / other, from the real `psycopg2`
`orig` exception text; (5) `psutil` RSS sampling before/after each
concurrency scenario (DIRECTIONAL LOCAL WINDOWS DEVELOPMENT EVIDENCE only).

The harness (~700 lines across two files) was **not** committed to the
repository, per the same profiling-harness scope-minimization convention
B11-C used; its methodology, exact dataset dimensions, and every numeric
result are reproduced durably below so an independent reviewer can verify
every conclusion without the harness file or a chat transcript.

## Current Isolation/Session Behavior (Code Inspection + Live Confirmation)

`database.py` creates one process-wide `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)`
with **no explicit `isolation_level`** passed to `create_engine(...)`, so the
PostgreSQL server default governs every connection - confirmed live above as
`read committed`. `dependencies.get_db` is the sole session source for every
M10 route:

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Every M10 route function declares exactly one `db: Session = Depends(get_db)`
parameter, so **one HTTP request uses exactly one `Session`/one PostgreSQL
transaction for its entire duration** - with `autocommit=False`, SQLAlchemy
opens the transaction lazily on the first statement and keeps it open (no
explicit `db.commit()`/`db.rollback()` exists anywhere in the seven read-only
M10 routes) until `get_db`'s `finally: db.close()` runs at the end of the
request, which implicitly rolls back/releases that transaction. This means:
one M10 HTTP request currently has **one open transaction but NOT one
snapshot** - under `READ COMMITTED`, PostgreSQL takes a **fresh snapshot per
SQL statement**, not per transaction, so later statements in the same
still-open request transaction can observe commits that happened after the
request started (and after earlier statements in that same request already
ran).

Structurally, every one of the seven routes builds one lazy SQLAlchemy
`Query` object once per request (`svc.frozen_membership_query(...)`, never
executed itself) and then passes that same `Query` object to **two or more
independent downstream functions**, each of which issues its **own fresh
SQL `SELECT`** against it. This is the exact mechanism that makes
cross-statement snapshot divergence possible - confirmed by direct code
reading of every route function in `routers/talent_organization_analytics.py`
and every corresponding service module:

| Route | Independent SQL statements against population-derived data (same request) | Structural exposure |
|---|---|---|
| `overview` | `coverage_organization_total` (1) + `candidate_membership_counts` (0-1) + `identification_membership_counts` (0-1) | High (3 max) - **empirically proven below** |
| `program-portfolio` / `branches/{id}` (`_b7_response`) | `coverage_program_totals` (1) + `candidate_membership_counts` (0-1) + `identification_membership_counts` (0-1) + `required_period_execution_counts` (portfolio only, program/plan-derived not population-derived) | High (3 max) - same code path as `overview`, not independently re-run this task |
| `talent-map` | `coverage_by_program_branch`/`_grade` (1) + `sensitive_membership_by_dimension` (0-1) | Medium (2 max) - not independently re-run this task |
| `students` (Student Drill) | `count_distinct_students` (1, the P7 gate) + `fetch_student_rows` (1 page query + 0-2 more Candidate/Identification lookups keyed off the page's member ids) | High (2-4) - **empirically proven below** |
| `programs/{id}/longitudinal` | `coverage_by_cycle` (1) + `candidate_counts_by_cycle` (0-1) + `identified_counts_by_cycle` (0-1) | High (3 max) - same code shape, not independently re-run this task |
| `participation-overlap` | `participation_overlap_counts` (1 single self-join query - the entire Program-pair matrix is produced by ONE statement) | **Low** - the core aggregate cannot internally diverge from itself (one statement = one snapshot); confirmed by direct code reading |

## Phase 1 - Overview Cross-Statement Consistency (READ COMMITTED vs REPEATABLE READ)

Dataset: MEDIUM-shaped (4 Branches, 6 Programs, 150 Students/cycle, 1,501
frozen population rows, 314 Candidates, 154 Identifications, 322
frozen-but-`unassessed` members available as write targets).

Reproduces the real `/overview` route's own statement order in the real
session/session-transaction shape: `coverage_organization_total` (SQL#1)
followed later by `candidate_membership_counts` (SQL#2), both against the
same still-open reader `Session`. Between SQL#1 and SQL#2, a **separate,
already-committed writer `Session`** performs a real domain-valid write - an
Assessment completion (`status: unassessed -> completed`) plus a Candidate
decision creation - for one already-frozen population member that SQL#1 had
just counted as `unassessed`.

| | `READ COMMITTED` (default) | Isolated `REPEATABLE READ` experiment |
|---|---|---|
| Candidate total before write, read in the open reader tx | 314 | 314 |
| Candidate total after write, re-queried in the **same still-open** reader tx (SQL#2) | **315** | 314 |
| Candidate count changed mid-request without a new request | **Yes** | No |
| `completed` count if SQL#1 were re-run in the same tx | 827 (vs. 826 originally observed) | 826 (unchanged) |

**Demonstrated inconsistency (`READ COMMITTED`):** the population/coverage
snapshot the route already returned (`completed=826`, unaware of the write)
and the Candidate count the same route returns moments later in the same
response (`candidate=315`, aware of the write) come from **two different
committed database states** - a live, reproduced instance of exactly the
"Candidate component after write but frozen population before write" example
named in this task's brief. Under the isolated `REPEATABLE READ` experiment,
both statements returned mutually consistent, stable values (the write
becomes visible only to a *subsequent* request/transaction) - the same
technique the task specification calls "synchronized writer barriers /
transactions... to prove or disprove it" was used here via deterministic
statement-order control rather than a timing race, which is more reliable
and fully reproducible.

## Phase 2 - Student Drill Gate-Vs-Page Consistency (READ COMMITTED vs REPEATABLE READ)

Same MEDIUM dataset (rebuilt fresh in its own schema). Reproduces
`count_distinct_students` (the P7 gate SQL) followed later by
`fetch_student_rows` (the page-fetch SQL), both against the same still-open
reader `Session`. Between them, a separate writer `Session` commits one
brand-new frozen population member for a brand-new Student (a valid
population-freeze-style write, not a mutation of any existing frozen row).

| | `READ COMMITTED` (default) | Isolated `REPEATABLE READ` experiment |
|---|---|---|
| Gate eligible-count (SQL#1) | 705 | 705 |
| Page fetch row count (SQL#2, same open tx, limit=1000) | **706** | 705 |
| New Student visible in the page fetch | **Yes** | No |
| Gate-vs-page population mismatch | **Yes** | No |

**Demonstrated inconsistency (`READ COMMITTED`):** the P7 eligibility gate
was evaluated against a population of 705 Students, but the identifiable
page of rows served moments later in the same response includes a 706th
Student who was not part of the gated population the gate decision was
actually made against - a live, reproduced instance of the "Student Drill
page membership... mismatch" example named in the task brief. Under the
isolated `REPEATABLE READ` experiment, the page fetch correctly excluded the
new Student, matching the gate's own snapshot exactly.

## Extrapolation To Other Routes (Not Independently Re-Run This Task)

`program-portfolio`, `branches/{id}`, `talent-map`, and `longitudinal` share
the identical structural mechanism proven above (a lazy `Query` object
re-executed independently by 2-3 downstream calls inside one still-open
`READ COMMITTED` session/transaction, with no code-level guarantee that any
two of those calls observe the same committed state). This is a
code-inspection-based extrapolation from the same functions/pattern already
proven live for `overview` and `students`, not a separately reproduced live
race for each of those four routes - time-bounded within this task; treated
as **high-confidence but not independently empirically verified per-route**,
and should be listed explicitly as such for the independent reviewer.
`participation-overlap`'s core Program-pair matrix is produced by exactly one
SQL statement (confirmed by code reading, not just count), so it does **not**
share this specific cross-statement mechanism for its own aggregate - it
remains exposed only to the much lower-risk case of an unrelated Program
being reconfigured between an earlier `authorized_program_universe`/
`program_rows` lookup and the overlap query itself.

## Privacy / Security Analysis

`talent_analytics_relationship_graph`/`talent_analytics_privacy_closure`
build one `PrivacyClosureResult` per request from whatever raw `Cell` values
the route already gathered in Python before calling
`apply_primary_privacy_and_close` - closure itself does not re-query the
database, so it cannot introduce a *new* cross-snapshot divergence beyond
whatever the route's own SQL calls already produced. Two concrete
consequences, both confirmed by code reading plus Phase 1/2 evidence:

1. **Relationship-linked Cells cannot desynchronize relative to each other**,
   because both sides of every existing M10 `Relationship` (`overview`'s
   `completed<->coverage_n` and `frozen<->coverage_d`) are populated from the
   **same single SQL statement's result** (`coverage_organization_total`),
   which is one atomic `READ COMMITTED` snapshot by definition. No
   relationship-closure equation observed in this codebase can be fed
   internally contradictory operands by concurrency alone.
2. **Every other Cell has no relationship at all** (`candidate`/`identified`
   in `overview`/`portfolio`/`branch`/`longitudinal`, every pair in
   `participation-overlap`, the single gate Cell in `students`) - each such
   Cell is only ever as fresh as its own statement's snapshot, with no
   cross-Cell equation to violate, but also no guarantee that two
   independently-fetched Cells in the same JSON response reflect the same
   moment in time. Phase 1/2 are direct, reproduced instances of this.

**Privacy-reconstruction risk:** this task could not empirically evaluate
whether concurrency creates a genuine complementary-suppression-equation
reconstruction risk, because ADR 0028 explicitly defers the production
`TalentAnalyticsPrivacyPolicy` implementation and every test in this task
(matching B11-C and the existing suite) used the non-production
`AllowAllTestPolicy`, which never suppresses. The structural risk is real in
principle (a future threshold-based policy could evaluate a suppression
decision against a raw value gathered from one statement while a sibling
component used for a complementary equation was gathered from a different,
inconsistent statement/snapshot) but is **not measurable today** without a
real threshold provider - carried forward as an explicit B11-E dependency,
not resolved here. No suppressed value was observed to become
reconstructable in this task because no suppression occurred in any tested
scenario (fail-closed AllowAll semantics were unchanged and behaved
identically under every concurrency scenario tested).

## Tenant Isolation

Every M10 query filters by `context.school_group_id` (confirmed by code
reading of every `talent_org_intelligence_service.py` query). A dedicated
foreign-tenant writer thread ran continuously throughout every Phase 3 stress
scenario (creating foreign-tenant Students/Placements/frozen population
members in a second, isolated `SchoolGroup`) concurrently with the primary
tenant's readers and writers. The primary tenant's final post-burst
`/overview` response (`academic_year_id=100`, `scope="organization"`)
reflected only primary-tenant scope in every scenario; no foreign-tenant
identifier, count, or structural signal was observed to cross into the
primary tenant's response, aggregate counts, or privacy relationships in any
scenario tested.

## Phase 3 - Concurrent HTTP-Level Reader/Writer Stress (All 7 Routes)

Dataset: MEDIUM-shaped (same dims as Phase 1/2), fresh per scenario,
`ANALYZE`d before each stress run. Each `client.get(...)` opens its own
per-call `Session` (matching real `get_db` semantics exactly). Writers
perform real domain-valid flows only: completing an already-frozen
`in_progress`/`incomplete` Assessment, creating a `TalentReviewCandidate` for
an already-completed Assessment that lacks one, and creating a
`TalentOfficialIdentification` for a Candidate that lacks one - never
mutating any frozen population-member row. A dedicated foreign-tenant writer
ran in every scenario (see Tenant Isolation above).

| Scenario | Readers x iterations (all 7 routes/iteration) | Writers | Wall time | HTTP status | Deadlocks | Lock timeouts | Other errors | RSS delta (directional) |
|---|---|---|---|---|---:|---:|---:|---:|
| 1R/1W | 1 x 3 (21 calls) | 1 | 0.86s | 21x `200` | 0 | 0 | 0 | +0.58 MB |
| 4R/1W | 4 x 3 (84 calls) | 1 | 1.8s | 84x `200` | 0 | 0 | 0 | +0.19 MB |
| 4R/3W | 4 x 3 (84 calls) | 3 | 2.11s | 84x `200` | 0 | 0 | 18 (see below) | +2.81 MB |

**Every HTTP call across all three scenarios (189 total) returned `200`** -
no route ever surfaced a 5xx, a stale-serialization error, or an unhandled
exception to the HTTP layer under any tested concurrency level.

**The 18 "other errors" (`4R/3W` only) are a harness artifact, not a
demonstrated application defect.** They are `IntegrityError: duplicate key
value violates unique constraint "talent_review_candidates_pkey"` /
`"uq_talent_review_candidates_assessment"`, caused by this task's own
`writer_worker` test code computing a new primary-key id via
`SELECT max(id)+1` before each concurrent insert - a non-atomic pattern that
is unsafe under concurrent writers by construction. This does **not**
reflect real application behavior: `models.py` declares
`id = Column(Integer, primary_key=True)` for both tables, and real
application insert paths (outside M10, which is read-only) that call
`session.add(...)` without supplying an explicit `id` rely on PostgreSQL's
native per-table identity/sequence-backed auto-increment, which is
atomically safe under concurrent writers by design. What this artifact *does*
usefully confirm: PostgreSQL correctly rejected every conflicting insert with
a clean `IntegrityError`, every writer thread's own `except`/`session.rollback()`
recovered without corrupting state or crashing, and no error of this kind
ever reached or affected the reader/HTTP layer - a real, if incidental,
confirmation of graceful conflict recovery under contention.

Per-route latency (min/p50/p95 ms) at the highest tested concurrency
(4R/3W, 12 samples/route):

| Route | min | p50 | p95 |
|---|---:|---:|---:|
| overview | 50.7 | 110.2 | 178.0 |
| talent_map | 54.2 | 88.9 | 99.7 |
| program_portfolio | 79.7 | 94.9 | 105.9 |
| branch_intelligence | 70.9 | 89.5 | 102.5 |
| participation_overlap | 51.4 | 76.8 | 99.4 |
| student_drill (limit=100) | 100.5 | 153.1 | 244.0 |
| longitudinal | 35.6 | 117.6 | 128.8 |

Local, non-production, in-process `TestClient` latency (no network hop, no
production SLO exists or is implied). Latency increases with concurrency in
every route (expected, single small local PostgreSQL instance) but no route
became pathological or timed out (`statement_timeout=30000ms` was configured
and never triggered).

## Phase 4 - Participation Overlap Under Concurrency, Statistics Freshness, Larger Scale

### 4a. Statistics freshness, MEDIUM scale, controlled cold-vs-warm

Same MEDIUM dataset as Phase 1-3, freshly built, **before any `ANALYZE`**
(`pg_stat_user_tables.last_analyze`/`last_autoanalyze` confirmed `NULL` at
capture time):

| | Cold (no `ANALYZE`) | Warm (after `ANALYZE`) |
|---|---:|---:|
| Plan shape | Nested Loop (planner underestimated `rows=1`, actual `rows=1567`; 1,080-row `Unique`/`Sort` inner re-executed) | Hash Join |
| Execution time (`EXPLAIN ANALYZE`) | 214.8 ms | 5.68 ms |
| Speedup | - | **37.8x** |

This directly reproduces, under fully controlled conditions (this task
explicitly withheld `ANALYZE` rather than relying on incidental timing), the
same MEDIUM-scale Nested-Loop-with-repeated-subplan pathology B11-C observed
under natural profiling-run timing - and shows it is **fully and completely
resolved by `ANALYZE`**, not merely reduced. This is new, more controlled
evidence than B11-C had for the MEDIUM scale specifically (B11-C's MEDIUM
observation was not isolated from ambient autovacuum timing).

### 4b. Concurrent readers, MEDIUM scale, post-`ANALYZE`

4 reader threads x 10 iterations = 40 concurrent `participation-overlap`
HTTP calls against the same warm MEDIUM dataset: **all 40 returned `200`**;
latency 19.7-148.8 ms (avg 60.6 ms). No plan instability, error, or timeout
was observed under concurrent reader pressure once statistics were fresh.

### 4c. Bounded larger-scale ("XL") retest

Target: "10x-100x increase in the dimension that drives Participation
Overlap risk," bounded per this task's explicit resource-safety instruction
("Stop if local resource safety becomes questionable... the objective is
evidence, not maximum scale"). This task built and measured an XL scale of
**~2.95x B11-C's LARGE scale** (10 Branches, 14 Programs, 67,201 frozen
population rows, 30,722 distinct Students, 105 Program pairs, `ANALYZE`d):
build took 25.2s; the same `EXPLAIN (ANALYZE, BUFFERS)` participation-overlap
query executed in **224.8 ms** using a **Hash/Merge Join** plan (not the
pathological Nested Loop) - i.e., the good plan shape continued to hold at
nearly 3x B11-C's LARGE scale with fresh statistics. **A full 10x-100x
retest (roughly 228K-2.28M population rows) was not attempted in this task**
- it was assessed as a materially higher local build-time/resource
commitment than this session's time budget could safely absorb
interactively, and is explicitly deferred to B11-E as unfinished work, not
silently skipped.

### Index Candidate B - Reclassification

B11-C classified Index Candidate B (a `student_id`-leading index on
`talent_assessment_cycle_population_members`) as **MORE EVIDENCE REQUIRED**,
because its observed MEDIUM-scale instability did not monotonically
correlate with scale (MEDIUM was slower than LARGE) and its cause was not
yet isolated. This task's controlled 4a experiment isolates the cause
precisely: **the MEDIUM-scale instability is fully explained by statistics
freshness, not by the absence of a `student_id`-leading index** - the
byte-identical MEDIUM query, on the byte-identical data, with no index added
or removed, goes from a pathological 214.8 ms Nested Loop to a 5.68 ms Hash
Join purely by running `ANALYZE`. Combined with 4c (a ~3x-larger-than-LARGE
scale also produces a good Hash/Merge Join plan without the index, once
`ANALYZE`d) and B11-C's own LARGE-scale evidence (also a good plan without
the index), **every scale tested across both B11-C and this task (SMALL,
MEDIUM, LARGE, XL) produces an acceptable plan without a `student_id`-leading
index once PostgreSQL statistics are fresh.**

**This task's classification: leaning `NO CHANGE`**, on the basis that the
previously-unexplained non-monotonic instability is now fully attributed to
a separate, already-tracked statistics-freshness finding rather than to
index absence. This task does **not** unilaterally close Index Candidate B -
per the governing task's instruction, this remains a
classification-with-evidence for independent review, not a final governance
decision, and **no index is created or approved by this document**.

### Statistics-Freshness Conclusion

The pathological no-statistics plan is real and reproducible (confirmed
again, under tighter control, in 4a), but its practical relevance is bounded:
it requires (a) `n_live_tup`/`last_analyze` to be genuinely absent for the
specific table, and (b) a `participation-overlap`-shaped self-join query to
run before autovacuum's background `ANALYZE` completes. This task's own
Phase 3 writer scenarios (which perform small, normal, one-row-at-a-time
domain writes against an already-`ANALYZE`d table, exactly like real
steady-state application traffic) never reproduced this pathology - it is
specifically tied to a **large, synchronous, bulk-style write** (an import, a
migration, or an unusually large single Cycle-population-freeze operation)
immediately followed by an analytics read, not to normal incremental
steady-state writes. This remains a genuine, actionable **operational/
runbook** finding (e.g., an explicit `ANALYZE` step after any large bulk
population load, before the first analytics read) rather than an index or
isolation-level finding; no server-wide setting was changed and no runbook
was adopted by this document.

## Memory / RSS Evidence (DIRECTIONAL LOCAL WINDOWS DEVELOPMENT EVIDENCE)

Not a production memory ceiling; single local Windows PostgreSQL/Python
process, cumulative across scenarios within one run.

| Scenario | RSS before | RSS after | Delta |
|---|---:|---:|---:|
| 1R/1W (21 calls) | 109.75 MB | 110.33 MB | +0.58 MB |
| 4R/1W (84 calls) | 114.42 MB | 114.61 MB | +0.19 MB |
| 4R/3W (84 calls, incl. 18 rolled-back writer conflicts) | 116.29 MB | 119.10 MB | +2.81 MB |

No unbounded/retained growth pattern was observed across increasing
concurrency; the largest delta (4R/3W) remains a small, one-off increase
consistent with additional concurrent thread/connection/response-buffer
overhead, not a leak signature. This does not establish a multi-process/
multi-worker production memory ceiling (explicitly deferred to B11-E per ADR
0028's separate process-count-multiplier requirement, which this
single-process harness cannot measure).

## Privacy-Closure Timing

Per-route coarse latency under concurrency is captured above (Phase 3 table).
Consistent with B11-C's own deferral, this task did not build separate
fine-grained instrumentation to split SQL-aggregation time from
Cell/Relationship-construction time from privacy-policy-evaluation time from
reconstruction-closure time from serialization time - doing so would require
additional invasive in-process instrumentation not justified purely for
qualification profiling. This limitation is carried forward unresolved to
B11-E, exactly as B11-C already stated.

## Error / Deadlock / Retry Behavior

**Zero deadlocks and zero lock-wait timeouts were observed in any scenario**
(1R/1W, 4R/1W, 4R/3W, or the Phase 4b concurrent-reader participation-overlap
burst) - consistent with this task's writers never taking conflicting
row-level locks on the same row at the same time (each writer iteration
selects a small, essentially-disjoint slice of candidate rows via `LIMIT 5`
before acting on the first eligible one). The only errors observed were the
harness-artifact `IntegrityError`s described in Phase 3, each cleanly
recovered via `session.rollback()`. **No retry logic exists today** in
`dependencies.get_db`, in any M10 route, or anywhere this task added - none
was invented, per this task's explicit instruction. If governance later
judges that serialization-failure/deadlock retry handling is needed (most
relevant if/when a stronger isolation level is ever adopted, since
`REPEATABLE READ` can raise serialization failures that `READ COMMITTED`
cannot), that remains an explicit **B11-E-level implementation proposal**,
not adopted here.

## Observability Validation

`talent_organization_analytics_observability.OrganizationAnalyticsObservation`
was re-inspected under this task's concurrency lens: it issues no SQL of its
own, carries only the existing bounded allowlist
(`SAFE_STRUCTURAL_FIELDS`/`SAFE_PROVIDER_FIELDS` - counts/limits/outcomes
only, never a Student identifier, raw/suppressed analytical value, SQL
parameter, threshold, or request/response body), is instantiated fresh per
request (no shared mutable state across concurrent requests to race on), and
every public method (`record`/`emit`) wraps its own body in
`try/except Exception: pass`-style safe-failure handling that cannot alter
the response already computed by the route. This module was not modified by
this task; the Phase 3 stress scenarios exercised it identically to a
production-shaped request stream (189 requests total) with no import,
logging, or serialization failure observed. No new concurrency-sensitive
code path exists in this module - its safety-by-construction conclusion from
B11-B is unchanged.

## REPEATABLE READ Experiment - Result And Required Scope

Performed for both proven inconsistencies (Phase 1 `overview`, Phase 2
`students`) via `Connection.execution_options(isolation_level="REPEATABLE READ")`
on the reader connection only - never a server-wide or application-wide
change, and never made permanent. **Result: `REPEATABLE READ` fully resolved
both demonstrated inconsistencies** - every statement in the reader's
transaction, however many are issued, observed the same fixed snapshot taken
at the first statement, so no concurrent commit was visible partway through
either request.

**Required scope if ever adopted (per ADR 0028):** the current
`frozen_membership_query` re-execution pattern means a `REPEATABLE READ`
snapshot must be established **before the very first statement of the
request** (i.e., before `authorized_program_universe`/context resolution) to
cover the full evidence set ADR 0028 names - access context, aggregate
reads, Candidate/Identification reads, and privacy-closure inputs (privacy
closure itself issues no SQL, so it is automatically covered once every SQL
input to it shares one snapshot). The current `dependencies.get_db` opens a
default-isolation session with no isolation-level control point; adopting
`REPEATABLE READ` for M10 would require a dedicated session/dependency
(scoped to these seven routes only, not applied repository-wide) that sets
the isolation level before the first query - an application-code change this
task does **not** implement, per its explicit scope boundary.

## Is A Stronger Transaction Scope Justified?

**Yes, evidence now exists** (Phase 1 and Phase 2 above) that `READ
COMMITTED`'s default per-statement-snapshot behavior allows one M10 HTTP
request to combine SQL statements that observe different committed database
states, in ways that match this task's own named risk examples exactly. Per
ADR 0028's explicit gate ("Stronger isolation requires demonstrated
inconsistency evidence and a governed ADR"), the evidence half of that gate
is now satisfied by this document; the governed-ADR half is **not** - no ADR
proposing an isolation change exists yet. This task's evidence supports the
following governance proposal for independent review:

**PROPOSED - GOVERNANCE REQUIRED:** adopt `REPEATABLE READ` (not a higher
level; the Phase 1/2 experiment shows `REPEATABLE READ` is sufficient to
resolve every demonstrated inconsistency) for the seven M10 Organization
Intelligence routes only, scoped from context resolution through
privacy-closure inputs as described above, via a dedicated session/dependency
- not implemented by this document, not adopted, and not applied outside
M10.

## Are Retries Required?

Not demonstrated as required by this task's evidence: no serialization
failure or deadlock was observed in any `READ COMMITTED` scenario tested (see
Error / Deadlock / Retry Behavior above), and the isolated `REPEATABLE READ`
experiment above did not itself trigger a serialization failure in this
task's read-only-reader-vs-independent-writer shape. If `REPEATABLE READ` is
later adopted for these routes, PostgreSQL's serialization-failure
(`40001`) class becomes reachable in principle for read/write conflict
shapes this task did not specifically construct; this task recommends (not
implements) that any future `REPEATABLE READ` adoption proposal separately
evaluate and, if needed, add bounded retry handling for that specific error
class - an explicit B11-E-level implementation proposal, not adopted here.

## Regression

Command run (from repository root, using the pinned repo venv):

```
.\.venv\Scripts\python.exe -m pytest tests/test_talent_org_intelligence_contract.py tests/test_talent_org_intelligence_queries.py tests/test_talent_organization_overview.py tests/test_talent_organization_talent_map.py tests/test_talent_organization_program_portfolio.py tests/test_talent_organization_branch_intelligence.py tests/test_talent_organization_participation_overlap.py tests/test_talent_organization_student_drill.py tests/test_talent_organization_longitudinal.py tests/test_talent_organization_observability.py -q
```

Result: **209 passed** (0 failed, 0 errors) - identical count to B11-C,
confirming this task made no M10 semantic change. `tis.db` was verified
unchanged (`git status --porcelain -- tis.db` / `git diff --stat -- tis.db`
both empty) both immediately before and immediately after this run - no
restoration was needed this time.

Confirmed by this regression run plus direct inspection of this task's own
diff: no schema, migration, index, permission, or entitlement change; no
M10 route/service/serializer semantics change; no privacy-semantics change
(the existing `AllowAllTestPolicy`/`AllowAvailability`/`AllowBreadth` doubles
were reused exactly as the existing suite already uses them); no PostgreSQL
isolation change (the default remains `READ COMMITTED` in application code -
every `REPEATABLE READ` use in this task was an isolated, non-permanent,
reader-connection-only experiment inside the throwaway harness, never
touching `dependencies.py`/`database.py`).

## Exact Dataset Dimensions Used

| Dimension | MEDIUM (Phases 1-4b) | XL (Phase 4c) |
|---|---:|---:|
| Branches | 4 | 10 |
| Programs | 6 | 14 |
| Frozen population members | 1,501 | 67,201 |
| Distinct Students | 707 | 30,722 |
| Assessments | 1,178 | 53,571 |
| Candidates | 314 | 11,134 |
| Identifications | 154 | 5,610 |
| Program pairs (`P(P+1)/2`) | 21 | 105 |
| Unassessed (write-target) members | 322 | 13,629 |

## Known Limitations

1. Only one actor shape was tested (`ORGANIZATION`-scope, role `Editor`, all
   five relevant permission keys granted) - identical limitation to B11-C.
2. Only the non-production `AllowAllTestPolicy` (no suppression) was used;
   the privacy-reconstruction-under-concurrency question cannot be
   empirically evaluated until a real threshold-based provider exists
   (ADR 0028-deferred).
3. `program-portfolio`, `branches/{id}`, `talent-map`, and `longitudinal`
   were confirmed structurally exposed to the same cross-statement mechanism
   by code reading, but were **not** independently reproduced with a live
   concurrent writer in this task (time-bounded); `overview` and `students`
   were.
4. The full 10x-100x Participation Overlap larger-scale retest was not
   attempted; this task reached ~2.95x B11-C's LARGE scale (XL, 67,201
   population rows) and stopped there for session time/resource safety, per
   this task's own explicit instruction to prioritize evidence over maximum
   scale.
5. This harness runs entirely in one local Python process
   (`TestClient`, in-process, no real network hop) with one PostgreSQL
   connection pool; it does not measure multi-process/multi-worker
   (e.g. multiple `gunicorn`/Render Web Service instance) concurrency,
   which ADR 0028 separately requires evidence for (process-count
   multiplier) before B11-E.
6. The 18 `IntegrityError`s in the 4R/3W scenario are a harness-code
   artifact (non-atomic `max(id)+1` in this task's own writer test code),
   not a demonstrated production defect - see Phase 3 discussion.
7. No fine-grained privacy-closure phase timing was built (SQL vs.
   structure-construction vs. policy-evaluation vs. reconstruction-closure
   vs. serialization) - same limitation B11-C already carried forward.
8. Memory/RSS evidence is single-process, cumulative-within-run, directional
   local Windows development evidence only - not a production ceiling.

## Deferred To B11-E

- Production privacy provider implementation/configuration and the
  privacy-reconstruction-under-concurrency question that depends on it.
- Independent, per-route empirical reproduction of the cross-statement
  inconsistency mechanism for `program-portfolio`, `branches/{id}`,
  `talent-map`, and `longitudinal` (currently extrapolated, not each
  independently proven).
- Governance decision (a dedicated ADR) on whether to adopt `REPEATABLE
  READ` for the seven M10 routes, and if adopted, its implementation
  (dedicated session/dependency) and any resulting retry-handling need.
- The remaining 10x-100x Participation Overlap larger-scale retest beyond
  this task's ~2.95x XL result.
- Multi-process/multi-worker concurrent-request memory and consistency
  qualification (this harness is single-process only).
- Fine-grained privacy-closure phase timing, if ever judged necessary
  without invasive production instrumentation.
- Final governance disposition of Index Candidate B (this task's evidence
  leans `NO CHANGE`; no index is created or approved by this document).
- Any numeric privacy threshold, breadth limit, performance SLO, memory
  ceiling, or commercial/plan mapping (ADR 0028 Deferred Decisions -
  unchanged by this document).

## Files Touched By This Qualification Task

- `docs/history/engineering-handbook/2026-09-07-b11d-postgresql-concurrency-consistency-qualification.md`
  (this file, new).
- `docs/history/engineering-handbook/README.md` (added a navigation bullet
  to this file; existing lines otherwise preserved as found).
- `docs/CHANGE_HISTORY.md` (added a new dated entry; no existing lines
  changed).
- `docs/PROJECT_STATE.md` (added a new section; no existing lines changed).
- `docs/adr/0028-b11-production-qualification-policy.md` (appended a new
  B11-D status paragraph after the existing Status section; the pre-existing
  uncommitted B11-C wording already present in that section - see the
  Working-Tree Integrity Note above - was left completely untouched).
- `.kms-impact.yml` (task-specific declaration, including a transparency
  note mirroring the one above).
- `static/docs/TIS_Project_Reference_Booklet.pdf` and
  `static/docs/docs_manifest.json` (regenerated automatically by
  `python scripts/kms.py sync`, not hand-edited).

No application source file (`routers/`, `talent_org_*.py`,
`talent_analytics_*.py`, `models.py`, `db_migrations.py`, `database.py`,
`dependencies.py`) was modified. No index, migration, permission,
entitlement, privacy-semantics, or PostgreSQL isolation change was made.
No harness file was committed to the repository (its full methodology is
reproduced above for reproducibility). `tis.db` was confirmed unchanged
before and after this task, including after the regression run above.
