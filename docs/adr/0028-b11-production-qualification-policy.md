---
title: B11 Production Qualification Policy
documentation_version: 3.7
last_updated: 2026-09-07
status: accepted
module: architecture
---

# ADR 0028: B11 Production Qualification Policy

## Context

M10 B0-B10 are CLOSED. B11-A completed read-only qualification of the existing
privacy, commercial-availability, and breadth provider seams, and B11-B
observability is CLOSED. B11 overall remains NOT CLOSED. This ADR records the
production-policy boundaries required before B11-C profiling; it implements no
provider, configuration, schema, migration, index, isolation, permission,
entitlement, application behavior, or HTTP-contract change.

## Decision

### Privacy thresholds and provider

Production privacy thresholds are provider-owned external configuration and
must never be hard-coded in application logic, supplied through an implicit
fallback constant, or exposed through telemetry or an API. The provider
interface supports per-P1-P7 values and may support a global default. Missing
configuration, provider-resolution failure, and provider exceptions fail
closed. Environment-scoped configuration is the default governance position;
a tenant-specific override requires a separately governed future requirement.
Test-fixture thresholds are explicitly non-production. No numeric threshold is
approved; values remain deferred to Owner decision informed by evidence.

B11 requires one production `TalentAnalyticsPrivacyPolicy` implementation that
consumes governed external configuration. It must never fall back to
`AllowAllTestPolicy` or a permissive/default threshold. This checkpoint does
not implement that provider.

### Commercial availability

Talent Organization Analytics remains plan-agnostic: M10 feature code contains
no plan name, plan code, price, or packaging logic. Permission and entitlement
remain separate. The availability provider consumes the existing canonical
`entitlement_service`/feature-registry decision pattern and returns only
availability; provider missing, false, or exception remains fail closed.
Whether a new semantic `feature_key` registration is required and the exact
plan-to-feature packaging remain deferred to Owner governance.

### Breadth policy

Production breadth limits are external configuration, never hard-coded in M10
application code. The policy supports per-projection-family limits and may use
a global default. Governed structural dimensions are cell count, relationship
count, and pair count. Provider missing, rejection, or exception remains fail
closed. No numeric limit is approved; limits remain deferred to B11-C/D
evidence and Owner governance.

### Performance evidence and SLOs

No numeric M10 performance SLO is approved before B11-C. B11-C must measure
route latency, query count, query execution time, peak/result memory,
privacy-closure time, and rows/scans/buffers through `EXPLAIN` evidence. Later
SLO approval is an Owner/governance decision; no p95 or p99 target is implied.

### PostgreSQL isolation and indexes

B11-D qualifies current `READ COMMITTED` behavior first. `REPEATABLE READ` is
not adopted preemptively. Stronger isolation requires demonstrated
inconsistency evidence and a governed ADR; if adopted, its transaction scope
must cover the full M10 request evidence set: access context, aggregation,
Candidate/Identification reads, and privacy-closure inputs.

No index migration is approved without `EXPLAIN`/`ANALYZE` evidence of material
plan improvement, redundant/overlapping-index review, migration review,
documented rollback implications, and a governing ADR. This checkpoint
approves no candidate index.

### Memory and release qualification

Evidence required before master/deployment is baseline web RSS,
startup/import memory, per-request peak RSS, privacy-graph memory, query-result
memory, concurrent-request multiplier, and process-count multiplier. No numeric
memory ceiling is approved; it remains an Owner decision informed by evidence.
Memory/OOM qualification blocks release, not the start of B11-C.

### Configuration and failure behavior

Privacy thresholds and breadth limits follow existing external environment/
configuration conventions; M10 does not introduce a new central settings
architecture. Commercial availability uses the existing
`entitlement_service`/feature-registry architecture. KMS must contain no
credentials, secrets, or environment-specific values.

Existing fail-closed behavior remains authoritative for privacy provider
missing/exception; availability provider missing/false/exception; and breadth
provider missing/reject/exception. No HTTP-contract change is approved.

## Qualification Entry And Release Gates

### B11-C entry

B11-C may begin after this policy checkpoint is committed and pushed, the
cumulative KMS check is green, local/staging PostgreSQL is available, a
representative non-production dataset is available, and profiling uses
non-production/test-staging provider configuration. It does not require final
production privacy thresholds, commercial plan mapping, final breadth limits,
a production SLO, or a final isolation change.

### B11-D entry

B11-D requires production-like PostgreSQL, controlled concurrent writers,
representative M10 read paths, and governed non-production provider
configuration. Current `READ COMMITTED` behavior must be tested first.

### B11-E release gate

B11 cannot be CLOSED until all of the following are complete: the production
privacy provider is implemented/configured; privacy-threshold governance and
commercial availability mapping are complete; production breadth configuration
is complete; B11-C PostgreSQL performance evidence and B11-D concurrency/
consistency evidence are complete; memory/OOM evidence is complete; B11-B
observability is present; the integrated seven-route security regression is
green; every approved index/migration is applied and verified in the
qualification environment; and authoritative KMS is updated. B12, master
merge, and deployment remain blocked until B11-E passes.

## Deferred Decisions

The following remain explicitly unresolved: numeric privacy thresholds;
tenant-specific privacy overrides; exact commercial feature/plan mapping;
whether a new semantic `feature_key` is required; numeric breadth limits;
numeric performance SLOs; a numeric memory ceiling; any PostgreSQL isolation
change; and any index addition.

## Status

B10 is CLOSED. B11-A qualification architecture is complete. B11-B
observability is CLOSED. These B11 governance boundaries are APPROVED/GOVERNED.
B11-C completed PostgreSQL 16.15 profiling and is CLOSED after independent
re-review returned PASS WITH NON-BLOCKING OBSERVATIONS. No index or production
policy value was approved.

B11-D subsequently completed PostgreSQL 16.15 READ COMMITTED qualification and
is CLOSED after independent review returned PASS WITH NON-BLOCKING
OBSERVATIONS. Same-request mixed snapshots were proven. REPEATABLE READ remains
PROPOSED - GOVERNANCE REQUIRED and NOT IMPLEMENTED pending a separate governed
decision covering full-request transaction scope and retry/error handling.
B11-E is NOT COMPLETE. B11 overall is NOT CLOSED, B12 is NOT
IMPLEMENTED, and production readiness is NOT achieved.
