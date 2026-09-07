---
title: M10 B11-E Integrated Production Qualification (REPEATABLE READ Implementation)
module: engineering-handbook
last_updated: 2026-09-08
---

# 2026-09-08 - M10 B11-E Integrated Production Qualification

Module:
Talent & Potential M10 Organization Analytics, integrated isolation
governance/implementation and privacy/concurrency release-gate qualification
(ADR 0028, ADR 0029, B11-E entry)

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-09-08 - M10 B11-E Integrated Production
Qualification

Related ADRs:
`docs/adr/0028-b11-production-qualification-policy.md` (governing B11-E
release gate); `docs/adr/0029-m10-organization-analytics-repeatable-read-boundary.md`
(this task's governed isolation decision)

Related prior evidence:
`docs/history/engineering-handbook/2026-09-07-b11c-postgresql-profiling-evidence-remediation.md`
(dataset-builder pattern, query-count baselines, Index Candidate A/B,
statistics-freshness finding);
`docs/history/engineering-handbook/2026-09-07-b11d-postgresql-concurrency-consistency-qualification.md`
(proven READ COMMITTED same-request mixed-snapshot evidence for Overview and
Student Drill; REPEATABLE READ experiment; PROPOSED - GOVERNANCE REQUIRED
disposition)

Reviewer/approval notes:
This task governs (ADR 0029) and IMPLEMENTS the M10-only REPEATABLE READ
transaction boundary B11-D left as PROPOSED - GOVERNANCE REQUIRED, live
re-tests all seven routes under the permanent implementation, tests
suppression/reconstruction concurrency with a real deterministic suppressing
non-production policy, and finalizes Index Candidate B and statistics-
freshness disposition. It does not implement B12, does not merge to master,
and does not deploy. It does not add an index or migration. It does not
change PostgreSQL isolation server-wide or for any route outside M10. It does
not choose or implement a production privacy/availability/breadth provider
value or mapping - those remain Owner decisions per ADR 0028. **Independent
review returned PASS WITH NON-BLOCKING OBSERVATIONS. B11-E implementation is
PASSED and checkpointable, but this document does not declare B11-E production
closure or B11 overall CLOSED.**

`tis.db` was not touched (confirmed unchanged before and after this task's
full regression run). All live measurement used the dedicated non-production
`tis_b11c_test_db` PostgreSQL 16.15 instance at `127.0.0.1`, reached only
through the `TIS_TEST_POSTGRESQL_URL` environment variable (never printed,
logged, or persisted anywhere in this repository), inside ephemeral per-test
schemas (`tis_b11e_<uuid>`) created and dropped by each test - no rows were
left behind in the shared test database (confirmed by an explicit
post-run `information_schema.schemata` check finding zero leftover `tis_b11e_%`
schemas).

## Current Milestone Truth

- B0-B10: CLOSED. B11-A: complete. B11-B: CLOSED. B11 production-qualification
  policy (ADR 0028): APPROVED/GOVERNED. B11-C: CLOSED. B11-D: CLOSED.
- B11-E (this document): REPEATABLE READ governed (ADR 0029) and
  IMPLEMENTED for the seven M10 Organization Intelligence routes only; all
  seven routes live-re-tested under the permanent implementation;
  suppression/reconstruction concurrency tested live with a real
  non-production deterministic suppressing policy; Index Candidate B
  finalized as NO CHANGE; statistics-freshness disposition finalized as
  operational/runbook guidance (no code/migration action). Independent
  review of this document is **PENDING**.
- No index, migration, permission, entitlement, privacy-semantics change,
  production SLO, production privacy threshold, production breadth limit, or
  production memory ceiling is approved by this document. The production
  privacy/availability/breadth providers remain unimplemented and fail-closed
  (`talent_analytics_privacy.resolve_privacy_policy_provider`,
  `talent_org_intelligence_service.resolve_organization_analytics_availability_provider`,
  `talent_org_intelligence_service.resolve_organization_analytics_breadth_policy`
  all return `None` in production, unchanged by this task) - all three remain
  explicit B11-E closure blockers, Owner-decision-dependent per ADR 0028.
- **B11-E implementation is PASSED and checkpointable after independent review
  returned PASS WITH NON-BLOCKING OBSERVATIONS. B11-E production closure remains
  PENDING; B11 overall is NOT CLOSED. B12 is NOT IMPLEMENTED. Production
  readiness is NOT achieved.**

## Phase 0 - Connection Verification (Non-Production)

| Check | Result |
|---|---|
| `TIS_TEST_POSTGRESQL_URL` present in process environment | Yes |
| Connection succeeds | Yes |
| Database | `tis_b11c_test_db` (same dedicated non-production instance B11-C/D used) |
| Host | `127.0.0.1` (localhost only) |
| Value ever printed/logged/persisted | No |

## Phase 1/2 - Governance And Implementation

Recorded in full in ADR 0029
(`docs/adr/0029-m10-organization-analytics-repeatable-read-boundary.md`).
Summary:

- **Mechanism**: `database.py` adds `M10OrganizationAnalyticsSessionLocal`, a
  `sessionmaker` bound to `engine.execution_options(isolation_level="REPEATABLE READ")`
  - a shallow proxy sharing `engine`'s connection pool without altering
  `engine`'s own default isolation. Strictly backend-conditional
  (`DATABASE_URL.startswith("postgresql")`); on SQLite it binds to the plain
  `engine` unchanged.
- **Dependency**: `dependencies.py` adds `get_m10_organization_analytics_db`,
  mirroring `get_db`'s exact `SessionLocal() -> yield -> close()` shape.
- **Wiring**: `routers/talent_organization_analytics.py` uses
  `Depends(get_m10_organization_analytics_db)` instead of `Depends(get_db)`
  for all seven route functions (`overview`, `talent-map`,
  `program-portfolio`, `branches/{branch_id}`, `participation-overlap`,
  `programs/{program_id}/longitudinal`, `students`). No other route/module
  changed.
- **Test wiring**: the eight existing M10 route test files
  (`tests/test_talent_organization_{overview,talent_map,program_portfolio,
  branch_intelligence,participation_overlap,student_drill,longitudinal,
  observability}.py`) were updated to override
  `get_m10_organization_analytics_db` instead of `get_db` (their SQLite `db`
  fixture is unaffected; only the dependency-override target changed). All
  209 pre-existing M10 tests pass unmodified in behavior.
- **Scope begins before the first statement**: confirmed both by code
  reading (context/access resolution is every route's first DB call, via
  `_b7_context` -> `svc.resolve_access_context`) and live-proven in Phase 4C
  below (the interleaved write happens AFTER `frozen_membership_query` is
  called - itself well after context resolution - and is still invisible
  under `REPEATABLE READ`, proving the snapshot was already fixed earlier).

## Phase 3 - Retry / Failure Semantics

No serialization failure, deadlock, or lock-wait timeout was observed in any
live scenario in this task (14 new committed tests, each exercising a real
interleaved concurrent writer against the new `REPEATABLE READ` session; see
Phase 4/5 below). Matches B11-D's own finding. No retry logic was added -
recorded in ADR 0029 as a deliberate non-decision pending future evidence,
not implemented speculatively.

## Phase 4 - Live Consistency Re-Test (All Seven Routes)

New, committed, repository test file:
`tests/test_talent_organization_repeatable_read.py` (14 tests, all passing;
not a throwaway harness - this is real regression coverage going forward).
Methodology: reuses the B11-C/B11-D dataset-builder pattern (`models.Base.metadata.create_all`
against a dedicated ephemeral per-test PostgreSQL schema, the real M10
routers mounted on an isolated `FastAPI()` app via `TestClient`, the
project's existing non-production `AllowAvailability`/`AllowBreadth`/
`AllowAllTestPolicy` doubles from `tests/test_talent_org_intelligence_queries.py`
and `talent_analytics_privacy.py`). Concurrency is exercised via the same
deterministic "commit a real domain-valid write between two of the route's
own statements" technique B11-D used (a `monkeypatch`-wrapped service
function commits a write via a separate writer `Session` immediately after
its own return value is computed, before the caller's next statement runs) -
chosen, as B11-D also chose, for full reproducibility over a non-deterministic
thread-timing race.

Dataset: 2 primary Programs (Alpha, Beta) sharing Student overlap across 3
Cycles, 1 tiny isolated foreign-tenant control; 14 frozen population members,
10 distinct Students, 1 Candidate, 1 Identification; several already-frozen
`unassessed` members reserved as live writer targets.

### 4A - Overview (live, re-tested)

`test_overview_repeatable_read_resolves_candidate_snapshot_mismatch`.
Reproduces B11-D's exact statement pair (`coverage_organization_total` then
`candidate_membership_counts`). **Result: under the permanent
`REPEATABLE READ` implementation, the Candidate count no longer changes
within the same request** (stays at the pre-write value). **Contrast, same
test**: an identical interleave against a plain default (`READ COMMITTED`)
session, run second against the same live dataset, reproduces the original
vulnerability live (the Candidate count reflects the interleaved write) -
confirming the fix is necessary, not merely asserted from the earlier B11-D
document.

### 4B - Student Drill (live, re-tested)

`test_student_drill_repeatable_read_resolves_gate_page_mismatch`. Reproduces
B11-D's exact statement pair (`count_distinct_students` gate, then
`fetch_student_rows` page fetch). **Result: under `REPEATABLE READ`, the
gate count and the page's Student count match exactly, and the newly
committed Student is absent from the page.** **Contrast**: the same
interleave under plain `READ COMMITTED` reproduces the original gate/page
mismatch live (the new Student appears in the page).

### 4C - Talent Map, Program Portfolio, Branch Intelligence, Participation Overlap, Longitudinal (live, newly independently reproduced)

`test_other_routes_repeatable_read_scope_begins_before_first_statement`
(parametrized, one case per route). These four routes were only
code-inspection-extrapolated, not independently live-reproduced, in B11-D.
This task independently reproduces the identical vulnerability live for all
five, using a stronger, earlier interleave point: the writer commits
immediately after `svc.frozen_membership_query` builds its lazy `Query`
object - before ANY of that route's own downstream SQL has executed - proving
the transaction scope genuinely begins before the first statement of the
request (fixed during earlier context/access resolution), not merely between
two already-identified calls. **Result for all five routes: under
`REPEATABLE READ`, the interleaved write is not observable anywhere in the
response (verified via a recursive sum of every JSON `"value"` field);
under plain `READ COMMITTED`, the same interleave IS observable (the sum
increases).** All five routes returned HTTP 200 in every scenario.

## Phase 5 - Suppression/Reconstruction Concurrency (Real Non-Production Suppressing Policy)

Uses `talent_analytics_privacy.DeterministicSuppressionTestPolicy` - an
existing, already-committed, explicitly test-only/non-production
deterministic policy (`minimum_cohort` threshold; below it, `suppressed`)
already reused by `tests/test_talent_organization_overview.py`'s own
primary-suppression and complementary-suppression regression tests. This
task did NOT invent a new policy or any production-shaped threshold, per the
task's explicit instruction to check for and reuse an existing deterministic
suppressing test policy first.

- **Primary suppression** (`test_primary_suppression_is_immune_to_a_concurrent_write_crossing_the_threshold`):
  `minimum_cohort=2` suppresses the Candidate Cell (raw value 1). The
  interleaved writer commits exactly one more Candidate - enough to cross the
  threshold to `visible` if it were observed. **Result: the response remains
  `{"state": "suppressed"}` regardless of the concurrent write; no raw value
  or threshold text leaks (verified by the same token-based leak check the
  existing Overview test suite already uses).**
- **Complementary suppression** (`test_complementary_suppression_relationship_is_immune_to_a_concurrent_write`):
  `minimum_cohort=3` suppresses `completed` (raw value 2), which is
  relationship-linked to `coverage_n` in the Overview route's own equality
  Relationship. The interleaved writer completes one more Assessment (no
  Candidate) - enough to cross the threshold if observed. **Result: under
  `REPEATABLE READ`, `completion_coverage` remains fully `{"state":
  "suppressed"}` (no partial numerator/denominator/percentage leak).
  Contrast: the identical interleave under plain `READ COMMITTED` DOES flip
  `completion_coverage` to `visible`** - a live, reproduced instance of the
  reconstruction-relevant risk B11-D flagged as structurally possible but
  unmeasured (a suppression decision fed by operands from two different
  snapshots), now proven to be resolved by the ADR 0029 fix.
- **Reconstruction closure**: `talent_analytics_relationship_graph`/
  `talent_analytics_privacy_closure` issue no SQL of their own (confirmed by
  code reading, matching B11-D's conclusion); since every SQL input they
  consume now shares one snapshot per request (Phase 4 above), no additional
  closure-specific concurrency test was needed beyond the two above, which
  already exercise closure end-to-end.
- **No suppressed value became reconstructable**, and no identifiable
  Student data leaked, in any scenario tested.

## Tenant Isolation

`test_tenant_isolation_holds_under_the_new_session_with_a_foreign_tenant_write`.
Every M10 query filters by `context.school_group_id` (confirmed by code
reading, matching B11-D). A foreign-tenant write (a new Student/Placement/
frozen population member in the isolated foreign `SchoolGroup`) committed
immediately before a primary-tenant `REPEATABLE READ` request. **Result: the
primary tenant's response was unaffected** (`frozen_eligible_memberships`
stayed at 14; no foreign identifier appeared anywhere in the response body).
This is a deterministic committed-before-read check, not a true multi-threaded
race, consistent with this task's chosen (and B11-D's own preferred)
deterministic-interleave methodology.

## Provider Readiness (Phase 6)

| Provider | Implemented | Configured | Fail-closed | Blocked on |
|---|---|---|---|---|
| Privacy (`talent_analytics_privacy.resolve_privacy_policy_provider`) | No (returns `None`) | No | Yes (confirmed unchanged) | Owner-approved numeric P1-P7 thresholds/provider (ADR 0028 Deferred Decisions) |
| Organization analytics availability (`talent_org_intelligence_service.resolve_organization_analytics_availability_provider`) | No (returns `None`) | No | Yes (confirmed unchanged) | Owner-approved commercial/plan-feature mapping (ADR 0028 Deferred Decisions) |
| Breadth policy (`talent_org_intelligence_service.resolve_organization_analytics_breadth_policy`) | No (returns `None`) | No | Yes (confirmed unchanged) | Owner-approved numeric breadth limits (ADR 0028 Deferred Decisions) |

No production value, plan name, feature key, or numeric threshold/limit was
invented or implemented by this task, per ADR 0028 and the task's explicit
instruction. These three remain explicit B11-E closure blockers for the
repository owner.

## Index Candidate B - Final Classification: NO CHANGE

B11-C observed non-monotonic MEDIUM/LARGE instability; B11-D isolated the
cause to statistics freshness (a missing post-bulk-load `ANALYZE`), not index
absence, and reconfirmed a good plan shape at a ~2.95x-LARGE ("XL") scale.
This task's own live directional check (Phase 9 below) reconfirms the
`participation-overlap` query count is unchanged (8 queries, matching every
B11-C scale exactly) and low-latency under the new `REPEATABLE READ` session
- the isolation-level change has no mechanism by which it could alter query
planning or statistics, so it does not and cannot affect this classification.
**Final classification: NO CHANGE.** No index is created or approved by this
document. The remaining 10x-100x larger-scale retest B11-D deferred remains
explicitly unfinished (not required to close this classification, per the
task's own "if evidence remains healthy across B11-C/B11-D/B11-E scales:
prefer NO CHANGE" guidance).

## Statistics Freshness - Disposition: Operational/Runbook Guidance (No Code/Migration Action)

B11-C/B11-D's finding (a large synchronous bulk population-freeze load,
before autovacuum's background `ANALYZE` completes, followed immediately by
a `participation-overlap`-shaped read, produces a pathological ~37x-680x
slower Nested-Loop plan that is fully resolved by running `ANALYZE`) is an
operational/runbook concern, not an index or isolation-level defect - the
isolation-level change made by this task has no bearing on it. **Disposition:
an explicit `ANALYZE` step (or equivalent PostgreSQL `autovacuum`/`autoanalyze`
verification) after any large, synchronous bulk Cycle-population-freeze
operation, before the first analytics read, is sufficient.** This is
documented here as the governed disposition; no code, migration, or
server-wide PostgreSQL setting is changed by this document, consistent with
the task's instruction to govern (not implement) any further action this
session.

## Phase 9/11 - Directional Memory/Performance/Query-Count Evidence (DIRECTIONAL LOCAL WINDOWS DEVELOPMENT EVIDENCE)

Not a production ceiling or SLO; single local Windows PostgreSQL/Python
process, small qualification-scale dataset (14 population members - this is
a functional re-verification after the isolation change, not a new scale
study; B11-C/B11-D's SMALL/MEDIUM/LARGE/XL scale evidence is unaffected and
still authoritative for scale behavior). Each of the seven routes called
twice under the new `REPEATABLE READ` session, via a non-committed local
script following the same `QueryCounter`/`psutil` RSS convention B11-C
established:

| Route | Query count (1st/2nd call) | Latency ms (1st/2nd) | RSS delta across both calls |
|---|---:|---:|---:|
| overview | 10 / 10 | 68.4 / 21.7 | +0.06 MB |
| talent_map | 9 / 9 | 17.8 / 15.2 | +0.05 MB |
| program_portfolio | 11 / 11 | 23.6 / 23.5 | +0.04 MB |
| branch_intelligence | 11 / 11 | 31.5 / 17.3 | +0.06 MB |
| participation_overlap | 8 / 8 | 15.9 / 12.0 | +0.01 MB |
| student_drill (limit=100) | 11 / 11 | 22.9 / 21.3 | +0.05 MB |
| longitudinal | 11 / 11 | 27.1 / 16.6 | +0.04 MB |

**Every query count is IDENTICAL to B11-C's original READ COMMITTED
baseline for every route, at every scale B11-C tested** (overview=10,
talent_map=9, program_portfolio=11, branch_intelligence=11,
participation_overlap=8, student_drill=11, longitudinal=11) - confirming
`REPEATABLE READ` adds zero additional queries and changes no query shape.
Baseline process RSS 96.87 MB; +9.3 MB after dataset build (14 rows,
consistent with B11-C's own sub-linear per-row overhead finding); RSS flat
(<0.1 MB delta per route) across repeated calls to every route - no
retention/leak signature. Privacy-closure timing was not separately
instrumented (same limitation B11-C/B11-D already carried forward - closure
issues no SQL and operates on already-materialized Python values, so its
cost is included in the coarse per-route latency above, not separately
measurable without invasive instrumentation this task does not add).
Multi-process/multi-worker concurrent-request memory (the process-count
multiplier ADR 0028 separately requires) remains unmeasured by this
single-process check, exactly as B11-D already disclosed - not newly
resolved by this task.

## Phase 10 - Observability/Security Regression

`talent_organization_analytics_observability.OrganizationAnalyticsObservation`
was not modified by this task. Every one of the 14 new live tests exercised
it identically to a real request stream (including failure-path emissions
observed during initial debugging, all correctly classified as
`database_failure`/other bounded categories with no SQL text, parameter, or
Student identifier in the emitted telemetry - confirmed by direct inspection
of the emitted JSON during this task's own debugging). Tenant isolation
(above) and permission/authorization behavior (unchanged route logic, only
the `db` dependency's isolation level changed) were confirmed clean.

## Phase 12 - Regression

Commands run (repository venv):

```
.\.venv\Scripts\python.exe -m pytest tests/test_talent_org_intelligence_contract.py tests/test_talent_org_intelligence_queries.py tests/test_talent_organization_overview.py tests/test_talent_organization_talent_map.py tests/test_talent_organization_program_portfolio.py tests/test_talent_organization_branch_intelligence.py tests/test_talent_organization_participation_overlap.py tests/test_talent_organization_student_drill.py tests/test_talent_organization_longitudinal.py tests/test_talent_organization_observability.py tests/test_talent_organization_repeatable_read.py tests/test_postgresql_migration_transactions.py -q
```

Result: **226 passed** (0 failed, 0 errors) - 209 pre-existing M10 tests
(identical count and behavior to B11-C/B11-D, confirming no M10 semantic
change) + 14 new committed `test_talent_organization_repeatable_read.py`
tests (all live-PostgreSQL-gated tests ran, none skipped, since
`TIS_TEST_POSTGRESQL_URL` was present) + 3 pre-existing PostgreSQL migration
tests, unaffected.

```
.\.venv\Scripts\python.exe -m pytest tests/test_talent_privacy_reconstruction.py tests/test_talent_privacy_relationship_graph.py tests/test_talent_analytics.py -q
```

Result: **124 passed** (0 failed, 0 errors) - privacy graph/reconstruction
and broader M9 Talent Analytics regression, confirming no privacy-semantics
change.

`tis.db` was verified unchanged (`git status --porcelain -- tis.db` /
`git diff --stat -- tis.db` both empty) both before and after every
regression run in this task. A post-run `information_schema.schemata` query
confirmed zero leftover `tis_b11e_%` PostgreSQL schemas.

Confirmed by these regression runs plus direct inspection of this task's own
diff: no schema, migration, index, permission, or entitlement change; no M10
route/service/serializer semantics change; no privacy-semantics change (the
existing `AllowAllTestPolicy`/`AllowAvailability`/`AllowBreadth`/
`DeterministicSuppressionTestPolicy` doubles were reused exactly as the
existing suite already uses them); no PostgreSQL server-wide isolation
change (the default remains `READ COMMITTED` for every route/session outside
the seven M10 Organization Intelligence routes).

## Known Limitations

1. Only one actor shape was tested (`ORGANIZATION`-scope, role `Editor`, all
   relevant permission keys granted) - identical limitation to B11-C/B11-D.
2. The tenant-isolation and Phase 4C interleave techniques are deterministic
   "commit before the next statement" interleaves, not true multi-threaded
   timing races - matching B11-D's own stated preference for full
   reproducibility, but this means true thread-scheduling-dependent races
   are not separately exercised by this task (B11-D's own Phase 3
   multi-threaded HTTP-level stress, at 1R/1W, 4R/1W, and 4R/3W, remains the
   authoritative multi-threaded evidence and was not re-run this task, since
   it exercises the same session/statement mechanism this task's Phase 4
   already re-verified is now fixed).
3. The Phase 9 directional check in this document uses a small
   qualification-scale dataset (14 population members) to functionally
   re-verify query-count/latency/RSS after the isolation change; it is not a
   new SMALL/MEDIUM/LARGE/XL scale study - B11-C/B11-D's scale evidence
   remains authoritative and unaffected (isolation level has no mechanism to
   change query plans or scale behavior).
4. Multi-process/multi-worker (e.g., multiple Render Web Service worker
   processes) concurrent-request memory and consistency qualification
   remains unmeasured, exactly as B11-D already disclosed - not resolved by
   this task.
5. No fine-grained privacy-closure phase timing was built - same limitation
   B11-C/B11-D already carried forward.
6. The production privacy/availability/breadth providers remain
   unimplemented; this task did not and could not test real-threshold
   suppression against a production-shaped provider, only the existing
   non-production `DeterministicSuppressionTestPolicy` - appropriate per ADR
   0028's explicit deferral of numeric thresholds to Owner governance.

## Files Touched By This Qualification Task

- `docs/adr/0029-m10-organization-analytics-repeatable-read-boundary.md` (new).
- `docs/adr/0028-b11-production-qualification-policy.md` (Status section and
  PostgreSQL isolation/indexes section updated to record ADR 0029's scoped
  adoption; no other wording changed).
- `docs/adr/README.md` (added ADR 0029 to the index).
- `docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`
  (this file, new).
- `docs/history/engineering-handbook/README.md` (added a navigation bullet).
- `docs/CHANGE_HISTORY.md` (added a new dated entry).
- `docs/PROJECT_STATE.md` (added a new section).
- `docs/TIS_MASTER_CONTEXT.md` (added a new section).
- `.kms-impact.yml` (task-specific declaration).
- `static/docs/TIS_Project_Reference_Booklet.pdf` and
  `static/docs/docs_manifest.json` (regenerated by `python scripts/kms.py sync`).
- `database.py` (added `M10OrganizationAnalyticsSessionLocal`, backend-conditional).
- `dependencies.py` (added `get_m10_organization_analytics_db`).
- `routers/talent_organization_analytics.py` (all seven routes now depend on
  `get_m10_organization_analytics_db` instead of `get_db`).
- `tests/test_talent_organization_{overview,talent_map,program_portfolio,
  branch_intelligence,participation_overlap,student_drill,longitudinal,
  observability}.py` (dependency-override target updated to match; no
  assertions/behavior changed).
- `tests/test_talent_organization_repeatable_read.py` (new, committed, 14
  tests: 4 backend-conditional wiring checks + 10 live PostgreSQL
  qualification tests).

No index, migration, permission, entitlement, or privacy-semantics change
was made. `tis.db` was confirmed unchanged before and after this task,
including after every regression run above.
