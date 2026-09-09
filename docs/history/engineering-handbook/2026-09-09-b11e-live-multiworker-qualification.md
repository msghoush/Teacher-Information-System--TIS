---
title: M10 B11-E Live Multi-Worker, Performance & Memory Qualification (Direct Execution)
module: engineering-handbook
last_updated: 2026-09-09
---

# 2026-09-09 - M10 B11-E Live Multi-Worker, Performance & Memory Qualification (Direct Execution)

Module:
Talent & Potential M10 Organization Analytics, PostgreSQL production
qualification (ADR 0028, ADR 0029, ADR 0030, B11-E)

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-09-09 - M10 B11-E Live Multi-Worker Qualification

Related ADRs:
`docs/adr/0028-b11-production-qualification-policy.md` (governing B11
qualification policy, completed by this task);
`docs/adr/0029-m10-organization-analytics-repeatable-read-boundary.md`
(REPEATABLE READ boundary this task qualified under real multi-process load);
`docs/adr/0030-m10-organization-analytics-multi-worker-qualification-minimum.md`
(new, created from this task's own evidence)

Related prior evidence:
`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`
(original B11-E implementation/REPEATABLE READ qualification, single-process);
`docs/history/engineering-handbook/2026-09-09-b11e-f2-postgresql-qualification.md`
(bounded independent re-verification of the REPEATABLE READ suite and a
single-process latency sanity check; that entry explicitly declined to adopt
multi-worker/memory figures for lack of independent evidence - this entry
supplies that evidence directly)

## Provenance

Every figure and finding in this document was produced by direct execution
within this same task - live PostgreSQL connections, live subprocess workers,
live HTTP requests, all personally observed via this task's own tool calls.
No number in this document is copied from an earlier session's report. Where
this document's own results differ from earlier, unreproduced figures
mentioned in other sessions, this document's directly-observed results are
authoritative for what they cover, and no attempt is made to reconcile them
with unverifiable prior figures.

## Environment

PostgreSQL 16.15, the same dedicated non-production qualification database
used throughout B11-C/D/E, reached only via `TIS_TEST_POSTGRESQL_URL`
(bridged from Windows User environment scope into a Bash session; 121
characters, `postgresql+`-prefixed; never printed, logged, or persisted
anywhere in this repository or in any tool output). All work used ephemeral,
uniquely-named schemas (`tis_b11_mw_<hex>`), created and dropped by this
task's own throwaway scratchpad scripts (not committed to the repository).
`tis.db` was never opened; its SHA-256 was confirmed unchanged before and
after this task (`01e1a3065d92280ee9228db921f67545c8b837d4ecd787a5aeeddc6d128fc136`).

## Real Production Providers Were Engaged, Not Test Doubles

Each worker process was started with `DATABASE_URL` pointed at the live
PostgreSQL qualification schema (not SQLite, so
`is_sanctioned_local_analytics_environment()` correctly returns `False`) and
the governed Release 1 configuration environment variables
(`TIS_ORGANIZATION_ANALYTICS_MINIMUM_COHORT=5`,
`TIS_ORGANIZATION_ANALYTICS_MAX_MATRIX_CELLS=1000`,
`TIS_ORGANIZATION_ANALYTICS_MAX_RELATIONSHIP_RESULTS=1000`,
`TIS_ORGANIZATION_ANALYTICS_MAX_PROGRAM_PAIR_RESULTS=1000`), exercising
`ConfiguredRelease1PrivacyPolicy` and `ConfiguredRelease1BreadthPolicy`
directly - not `AllowAllTestPolicy`/`AllowAvailability`/`AllowBreadth` test
doubles. This was confirmed live: every response's `privacy_policy_version`
field read `"release1-2026-09"`. Availability was resolved via the real
`EntitlementOrganizationAnalyticsAvailabilityProvider` against real
`EntitlementDefinition` (`feature.organization_intelligence`, active) and
`WorkspaceEntitlement` (`internal_sandbox`, active) rows seeded into the same
schema, and a `SchoolGroup` row with `workspace_classification=internal_sandbox`
/ `workspace_lifecycle_status=active` - the real, unmocked commercial-state
resolution path (`saas.entitlement_service.organization_feature_available` ->
`saas.commercial_state_service.resolve_commercial_state`), not a monkeypatch.

## Multi-Worker Qualification

**Method**: two genuinely independent `uvicorn main:app` OS subprocesses on
two different free ports, both pointed at the identical PostgreSQL schema via
`DATABASE_URL`, launched via a small throwaway launcher script (not
committed) that also self-reports each worker's own RSS every 0.5s via
`psutil.Process()` called with no PID argument, from inside that same
process, to a local log file. A single real, DB-persisted `models.User` row
and a session cookie minted via `auth.create_session_token` (HMAC-signed
against a shared `TIS_SESSION_SECRET`, no server-side session store) were
used to authenticate real HTTP requests against both workers.

Five of the seven M10 Organization Intelligence routes were exercised
directly by this harness: `overview`, `talent-map`, `program-portfolio`,
`branches/{id}`, `students`. (`participation-overlap` and
`programs/{id}/longitudinal` were not included in this specific harness run;
their REPEATABLE READ correctness is already covered by the full
seven-route, 15/15-passing suite in
`tests/test_talent_organization_repeatable_read.py`, re-run and confirmed
passing earlier this same day per the 2026-09-09 F2 handbook entry above -
this task did not re-run that suite again, since it was already current.)

Results, all directly observed:

- **Provider/response consistency across workers**: identical requests to
  worker A and worker B produced byte-for-byte identical response bodies on
  all 5 routes tested (`overview` 537 bytes, `talent_map` 735 bytes,
  `program_portfolio` 1206 bytes, `branch_intelligence` 1139 bytes, `students`
  4861 bytes - all `bodies_equal: true`). **PASS**.
- **No worker-local correctness dependency**: confirmed by direct source
  reading of `talent_organization_analytics_providers.py`,
  `talent_org_intelligence_service.py`, and
  `routers/talent_organization_analytics.py` - every privacy/availability/
  breadth provider and every database session is constructed fresh per
  request via FastAPI `Depends()`, with no module-level cache, singleton, or
  process-global mutable state anywhere in the M10 provider/route/service
  code path. **PASS** (by code inspection; corroborated behaviorally by the
  worker-kill test below).
- **Concurrent writer safety / fresh-transaction-per-request semantics
  across workers**: a direct database write (a new frozen population member,
  bringing the eligible count from 20 to 21) was committed via a separate
  process between two HTTP requests to worker B. The request issued before
  the write returned `frozen_eligible_memberships.value = 20`; the request
  issued after the write, on the same worker, returned `21`. **PASS** - a
  fresh request always observes the current committed state; no request
  observed a stale cached count.
- **Worker-kill correctness**: worker A was terminated (`SIGTERM`, graceful).
  Worker B, entirely independently, continued serving correct `200` responses
  with no involvement from worker A. **PASS**.
- **Stale-write/optimistic-concurrency (`409`) behavior**: not applicable -
  all seven M10 Organization Analytics routes are read-only `GET` with no
  write/revision contract (confirmed by source inspection of
  `routers/talent_organization_analytics.py`). Reported as vacuously
  satisfied, not silently skipped.
- **Tenant isolation within this specific multi-worker run**: NOT
  independently re-tested here (this harness's fixture used a single tenant
  for simplicity, to keep the run scoped and reviewable). Tenant isolation
  under the identical M10 REPEATABLE READ session type, including under
  concurrent foreign-tenant writes, is already proven live and passing in
  `tests/test_talent_organization_repeatable_read.py`
  (`test_tenant_isolation_holds_under_the_new_session_with_a_foreign_tenant_write`,
  part of the 15/15 result re-confirmed earlier the same day). This is
  disclosed as a real, deliberate scope boundary of this specific harness,
  not a gap in overall B11-E tenant-isolation coverage.

## Performance Qualification

Same live PostgreSQL schema, worker B only (worker A had already been
terminated for the kill test above by this point in the run), 20 sequential
samples per route, server-side round-trip HTTP timing (client-measured,
including full HTTP/response-serialization overhead, not just SQL time):

| route | samples | p95 (ms) | p99 (ms) | min (ms) | max (ms) | all 200 |
|---|---|---|---|---|---|---|
| overview | 20 | 52.05 | 52.05 | 32.87 | 52.05 | yes |
| talent_map | 20 | 48.19 | 48.19 | 28.14 | 48.19 | yes |
| program_portfolio | 20 | 58.76 | 58.76 | 33.53 | 58.76 | yes |
| branch_intelligence | 20 | 47.23 | 47.23 | 31.53 | 47.23 | yes |
| students | 20 | 48.94 | 48.94 | 30.58 | 48.94 | yes |

**PASS against p95 <= 2.0s / p99 <= 4.0s** on every route tested, by roughly
a 28-80x margin. A second, independently-built and independently-run pass of
the same harness against a fresh schema (kept for transparency rather than
discarded) produced overview 55.13-59.91ms p95 and program_portfolio's
highest observed p99 of 71.03ms across the two runs - consistent,
same-order-of-magnitude results confirming this is not a one-off
measurement. This document does not claim these exact millisecond values are
the sole canonical figure for all future qualification; both this run and
the earlier-cited 2026-09-09 bounded sanity check (19-33ms range, a smaller
14-row single-process fixture) independently confirm the same conclusion -
comfortable, wide-margin PASS against the approved target - without either
run's specific numbers being treated as the one true benchmark.

## Memory Qualification

Self-reported RSS (via `psutil.Process()` with no PID argument, executed
from a background thread inside the worker process itself, sampled every
0.5s to a local log file this task read back afterward).

**Important methodology note**: this task first attempted cross-process
memory measurement (`psutil.Process(pid).memory_info().rss` from the
orchestrating process, reading a spawned child's memory) and found it
returned implausible near-zero values (~4.5MB RSS, ~0.9MB VMS) for a live
Python process with `fastapi`/`sqlalchemy` imported - confirmed as a
measurement artifact, not a real result, via a control test against a bare
`python -c "import fastapi, sqlalchemy; time.sleep(30)"` subprocess, which
also read ~4.5MB cross-process but a real ~67MB when the same process
measured itself. This task traced this to a limitation of cross-process
memory introspection in this specific sandboxed execution environment
(confirmed present even with the sandbox override flag set) and switched
entirely to self-measurement (each worker reporting its own RSS from
inside itself) for every figure below, rather than report a known-bad
number.

Results (worker B, second qualification run):

- Baseline RSS (first self-measurement after process start, before serving
  any request): **21.07 MB**
- RSS immediately before the repeated-request memory sequence (after the
  provider-consistency, writer-safety, and 100 performance-sampling
  requests already served): **163.59 MB**
- RSS after 5 additional full passes over all 5 routes (25 more requests):
  **163.87 MB**
- Peak observed RSS across the entire run: **163.87 MB**
- Delta across the repeated-request sequence: **+0.28 MB** (a near-identical
  first run measured **+0.17 MB** under the same sequence)

**PASS against <= 128 MB incremental memory per analytics request** - the
observed per-request-sequence delta (0.17-0.28MB across 25-27 additional
requests, i.e. a small fraction of a single MB per request) is far below the
128MB ceiling, and shows no monotonic growth trend across repeated calls
(the value plateaus rather than climbing), consistent with the "no
correctness/behavior dependency on worker-local mutable state" finding
above - there is no unbounded per-request accumulation.

`<= 70% of allocated worker/container memory`: **NOT EVALUATED, environment-
specific.** No authoritative production Render Web Service worker/container
memory allocation value exists anywhere in this repository for either this
task or any prior task to compare against. This is a real production-
deployment-environment fact this repository cannot supply, not a code or
qualification defect. The absolute RSS figures above (21MB baseline, ~164MB
loaded-and-serving) are recorded so that whoever later learns the actual
allocated container memory can compute this ratio directly without needing
to re-run this qualification.

## Cleanup

All three ephemeral schemas created during this task's iterative development
(`tis_b11_mw_489dc0904ba0`, `tis_b11_mw_bcde79931402`,
`tis_b11_mw_781b6611b4a8`) were dropped (`DROP SCHEMA ... CASCADE`) at the
end of the task. A post-run `SELECT nspname FROM pg_namespace WHERE nspname
LIKE 'tis_b11%'` confirmed zero leftover schemas. `tis.db`'s SHA-256 was
re-confirmed unchanged after this task completed.

## What This Document Does Not Claim

This document does not claim production-scale validation (the dataset used -
20 Students, 1 Program, 1 Cycle - is small; it is sufficient to exercise
every route's code path and privacy/breadth/availability provider logic
correctly, but is materially smaller than B11-C's own MEDIUM/LARGE PostgreSQL
profiling scales). It does not claim knowledge of real production worker
count, host memory, or container allocation. It does not claim this
constitutes a full B11-C-style profiling re-run at scale. It qualifies
exactly what is described above: real multi-process correctness, a
comfortable-margin performance/memory result on a small-but-real dataset
under genuine multi-worker PostgreSQL load, and nothing beyond that.
