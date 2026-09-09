---
title: M10 Organization Analytics Multi-Worker Qualification Minimum
documentation_version: 1.0
last_updated: 2026-09-09
status: accepted
module: architecture
---

# ADR 0030: M10 Organization Analytics Multi-Worker Qualification Minimum

## Context

ADR 0028's Memory and release qualification section requires a
"process-count multiplier" as part of B11-E memory/OOM evidence but does not
fix a numeric qualification minimum, and every prior B11-C/B11-D/B11-E
qualification task explicitly disclosed its own evidence as single-process
only (`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`,
Known Limitations: "Multi-process/multi-worker ... concurrent-request memory
and consistency qualification remains unmeasured ... not resolved by this
task"). No ADR previously governed a minimum worker/process qualification
count or an explicit correctness requirement against worker-local mutable
state.

`docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`
subsequently supplied that evidence: two genuinely independent `uvicorn`
subprocesses, both against the same live PostgreSQL qualification database,
serving real production-configured F1 providers (`ConfiguredRelease1PrivacyPolicy`,
`ConfiguredRelease1BreadthPolicy`, the real `EntitlementOrganizationAnalyticsAvailabilityProvider`
path), proving byte-identical cross-worker responses, fresh-transaction-per-
request consistency under a concurrent writer, and continued correct
operation of one worker after the other was terminated.

## Decision

### Multi-worker qualification minimum

Release qualification for the seven M10 Organization Intelligence routes
requires evidence gathered across a minimum of 2 concurrent worker/process
instances, not a single process, before any multi-worker PASS is recorded
against the B11-E release gate's "process-count multiplier" requirement.

### Correctness must not depend on worker-local mutable state

M10 route correctness (privacy suppression, breadth limiting, tenant
isolation, availability gating, REPEATABLE READ snapshot consistency) must
not depend on any module-level cache, singleton, or in-memory-only state
that is not independently reconstructed per worker process. A worker-local
cache may be used only as a performance optimization whose absence or
staleness cannot change a response's correctness; it must never be the sole
source of truth for a suppression decision, breadth limit, availability
decision, or tenant-scoping filter. `docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`
confirmed, by direct source inspection of every M10 provider/route/service
module, that no such state currently exists in this code path.

### Not a production topology claim

This ADR does not state, imply, or approve any actual Render Web Service
worker/process count. Real production worker count remains Render-dashboard-
owned configuration, intentionally undocumented in this repository per
existing KMS convention (confirmed absent from `Procfile`, `render.yaml`, and
every deployment workflow in this repository). This ADR governs only the
minimum qualification-evidence bar for release purposes, not a deployment
decision.

### Scope

Engineering/release-qualification scope only. Creates no product/commercial
capability, plan, feature, or customer-facing behavior change, and does not
by itself declare the B11-E release gate fully satisfied - it resolves
specifically the multi-worker/process-count portion of that gate's memory/OOM
evidence requirement.

## Evidence

`docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`:
provider/response consistency across 2 independent workers PASS; no
worker-local correctness dependency PASS (by code inspection, corroborated
behaviorally); concurrent writer safety / fresh-transaction-per-request
semantics across workers PASS; worker-kill correctness PASS; performance
(5 of 7 routes, 20 samples each) PASS against p95<=2.0s/p99<=4.0s with wide
margin; memory (self-measured RSS, real production providers engaged) PASS
against <=128MB incremental/request with wide margin, no monotonic growth.
Tenant isolation within that specific multi-worker harness run was not
independently re-tested (single-tenant fixture, by design, for scope
control); tenant isolation under the identical M10 REPEATABLE READ session
type remains proven live and passing in
`tests/test_talent_organization_repeatable_read.py`.

## Status

ACCEPTED. The multi-worker qualification minimum (>=2 independent
workers/processes), the no-worker-local-state correctness requirement, and
the not-a-topology-claim boundary are governed as of this ADR. This resolves
the "process-count multiplier" component of ADR 0028's B11-E memory/OOM
release-gate requirement. It does not by itself close B11-E - the remaining
release-gate items (KMS accuracy, integrated regression, etc.) are tracked in
ADR 0028's own Status section.
