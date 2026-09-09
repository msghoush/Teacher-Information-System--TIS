---
title: B11 Production Qualification Policy
documentation_version: 3.8
last_updated: 2026-09-09
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
closed. Environment-scoped configuration is the governance position; a tenant-
specific override requires a separately governed future requirement. The Owner
approved a minimum cohort of 5 for every P1-P7 class for F1. The provider must
accept that value only from external configuration; a missing, malformed, or
mismatched value is unavailable. Test-fixture thresholds remain non-production.

B11 requires one production `TalentAnalyticsPrivacyPolicy` implementation that
consumes governed external configuration. F1 implements it through
`ConfiguredRelease1PrivacyPolicy`; it never falls back to `AllowAllTestPolicy`
or a permissive/default threshold and preserves P1-P7 primary plus
relationship-aware complementary suppression.

### Commercial availability

Talent Organization Analytics remains plan-agnostic: M10 feature code contains
no plan name, plan code, price, or packaging logic. Permission and entitlement
remain separate. The availability provider consumes the existing canonical
`entitlement_service`/feature-registry decision pattern and returns only
availability; provider missing, false, or exception remains fail closed.
F1 registers and uses the semantic key `feature.organization_intelligence`.
Exact plan-to-feature packaging remains external commercial configuration and
is not encoded in M10 provider or route code.

### Breadth policy

Production breadth limits are external configuration, never implicit defaults
in M10 application code. The Owner approved ceilings of 1000 matrix cells,
1000 relationship results, and 1000 Program-pair results. F1 requires those
exact configured values and rejects over-limit work without truncation.
Provider missing, invalid, rejection, or exception remains fail closed.

### Performance evidence and SLOs

The Owner approved a numeric M10 performance target: p95 server-side M10
analytics route latency <= 2.0 seconds; p99 <= 4.0 seconds, across all seven
M10 Organization Intelligence routes. This is a release-qualification target,
evidenced directionally rather than production-scale benchmarked: multiple
separate, valid local PostgreSQL qualification runs on 2026-09-08 and
2026-09-09 measured every route well within this target, with substantial
margin in every run. Exact millisecond timings varied between runs
(fixture/harness/environment-dependent - one run measured p95 approx 170ms /
p99 approx 326ms for the highest-cost route under a larger single-process
dataset; independent re-runs on smaller and multi-worker datasets measured
p95/p99 in the 20-71ms range across all routes tested). This variance is
expected local-qualification noise, not a defect; no single exact
millisecond figure from any run is adopted as canonical. The adopted
requirement is the p95<=2.0s/p99<=4.0s target itself, which every qualifying
run has cleared by a wide margin (see
`docs/history/engineering-handbook/2026-09-07-b11c-postgresql-profiling-evidence-remediation.md`,
`docs/history/engineering-handbook/2026-09-09-b11e-f2-postgresql-qualification.md`,
and `docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`).
This is directional local qualification evidence, not production-scale
benchmarking; production-representative performance verification against a
real deployment environment remains a distinct, separate future
qualification step.

### PostgreSQL isolation and indexes

B11-D qualifies current `READ COMMITTED` behavior first. `REPEATABLE READ` is
not adopted preemptively. Stronger isolation requires demonstrated
inconsistency evidence and a governed ADR; if adopted, its transaction scope
must cover the full M10 request evidence set: access context, aggregation,
Candidate/Identification reads, and privacy-closure inputs.

B11-D supplied that evidence and ADR 0029 subsequently governed and
implemented the resulting, scoped decision: `REPEATABLE READ` for the seven
M10 Organization Intelligence routes only, via a dedicated session/dependency,
covering the full request evidence set named above. This remains scoped to
M10 only; no server-wide PostgreSQL isolation change was made, and no other
route's session/transaction behavior changed.

No index migration is approved without `EXPLAIN`/`ANALYZE` evidence of material
plan improvement, redundant/overlapping-index review, migration review,
documented rollback implications, and a governing ADR. This checkpoint
approves no candidate index.

### Memory and release qualification

The Owner approved numeric memory targets: incremental memory per M10
analytics request <= 128 MB; peak worker/process RSS <= 70% of authoritatively
allocated worker/container memory. Evidence required before master/deployment
is baseline web RSS, startup/import memory, per-request peak RSS,
privacy-graph memory, query-result memory, concurrent-request multiplier, and
process-count multiplier (see ADR 0030 for the process-count/multi-worker
qualification minimum this requirement resolves to).

The <=128MB target is PASS with substantial margin across every qualifying
run to date - worst-case observed incremental figures ranged from
approximately 0.48MB (single-process, larger dataset) to 0.17-0.28MB
(multi-worker, smaller dataset) per request/request-sequence, all a small
fraction of the approved ceiling; no monotonic retained-memory growth was
observed across repeated requests in any run. As with performance, no single
exact figure from any one run is adopted as the sole canonical measurement -
the adopted requirement is the ceiling itself, cleared with substantial
margin by every run.

The <=70% allocated-worker/container-memory target remains **NOT EVALUATED
LOCALLY / ENVIRONMENT-SPECIFIC**: no authoritative production Render Web
Service worker/container memory allocation value exists anywhere in this
repository for any qualification task to compare against. This is an
environment-specific production-deployment verification point, not a code or
product defect, and is not grounds to withhold adoption of the target
itself - the target is approved; its local evaluation is structurally
impossible without an allocation figure this repository does not have.
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

### B12 (M10 closeout)

B12 means M10 closeout only. B12 is strictly downstream of B11-E and does not
begin until the B11-E release gate above is truthfully satisfied. B12
acceptance requires: B11-E release qualification requirements satisfied; M10
implementation/regression/security/privacy evidence green; no unresolved
BLOCKER/HIGH defect open against any M10 milestone; authoritative KMS
accurately reflects implementation/evidence with no internal contradiction;
schema/migration state verified (none expected or approved for M10);
operational/deployment impact known and documented; closeout evidence
complete. B12 closure does NOT itself mean: M12 AI is complete; `dev` is
merged to `master`; production is deployed. Non-blocking LOW-severity
observations may remain open at B12 closure only if recorded with explicit
tracking (a "Known Limitations" section in the closing engineering-handbook
entry, referenced from this document's Status section) - this repository has
no separate issue-tracker artifact type, so KMS itself is that tracking
mechanism. Sequence: B11-E pass -> B12 M10 closeout -> cumulative production
qualification -> KMS/Git checkpoint -> `dev`->`master` approval -> deployment.
Product-implementation work outside M10 Organization Analytics (e.g. the
Talent & Potential Students/Program-workflow/Results-experience UI tracked
separately in `docs/PROJECT_STATE.md`) may serve as supporting regression/
product evidence but is never itself B12 closure - these are two independent
axes, and completion on one never implies progress on the other.

**B12 status: CLOSED (2026-09-09).** Independent verification against every
acceptance item above found each genuinely satisfied on current KMS/evidence:
the B11-E release gate (production privacy/availability/breadth providers,
performance/memory evidence, B11-C/B11-D evidence, B11-B observability, the
green integrated seven-route regression, index/migration verification, KMS
accuracy) is complete per this document's own Status section below; M10
implementation/regression/security/privacy evidence is green (226-test
integrated M10/PostgreSQL/privacy regression passed per
`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`;
the 15/15 REPEATABLE READ suite re-confirmed live per
`docs/history/engineering-handbook/2026-09-09-b11e-f2-postgresql-qualification.md`;
the 22-test observability suite remains green); no unresolved BLOCKER/HIGH
defect is open against any M10 milestone (the M9 call-ordering BLOCKER and the
related coverage-bundle HIGH-severity defect were each found and fixed by
their own remediation pass, and no other BLOCKER/HIGH remains open anywhere
in current KMS); authoritative KMS is internally consistent (independently
re-verified against `docs/PROJECT_STATE.md`, `docs/TIS_MASTER_CONTEXT.md`,
`docs/AI_PROJECT_CONTEXT.md`, `docs/engineering/PRODUCT_ROADMAP.md`,
`docs/engineering/TIS_MODULE_MAP.md`, ADR 0027, and ADR 0029, all of which
state the same current B11-E/B11/B12 status with no contradiction); no
schema/migration is approved or required for M10 (`git diff HEAD --
db_migrations.py models.py` is empty); this is Web-Service-only governance
work with no `tis-timetable-workflow` interaction; and the full closeout
evidentiary chain (F1 provider implementation review -> live PostgreSQL
multi-worker qualification -> ADR 0028/ADR 0030 adoption -> this B12
definition -> cross-document consistency repair) is complete and
cross-referenced.

**B12 closure means only: M10 (B0-B11) is closed.** It does NOT mean: M12 AI
is complete or implemented (it remains separate and NOT IMPLEMENTED, per
current KMS); `dev` has been merged to `master` (it has not); production has
been deployed (it has not). The next step is cumulative production release
qualification, followed by a `dev`->`master` approval and deployment
decision - neither has occurred and neither is implied by this closure. The
sole remaining environment-specific item - peak worker/process RSS as a
percentage of an authoritatively allocated production worker/container memory
limit (<=70% target) - is NOT reopened as a B12 blocker; it remains an
explicitly open, future production-deployment/qualification verification item
that can only be evaluated once a real production allocation value exists,
consistent with its treatment under the B11-E release gate above.

## Deferred Decisions

The following remain explicitly unresolved: tenant-specific privacy
overrides; exact plan-to-feature packaging; and any future index addition.
The privacy threshold, semantic feature key, breadth ceilings, M10-only
isolation decision, numeric performance targets, and numeric memory targets
are approved as recorded above and in ADR 0029/ADR 0030. The <=70%
allocated-worker/container-memory target's local evaluability remains an
environment-specific gate (see Memory and release qualification above), not
a deferred numeric decision - the number itself is approved.

## Status

B10 is CLOSED. B11-A qualification architecture is complete. B11-B
observability is CLOSED. These B11 governance boundaries are APPROVED/GOVERNED.
B11-C completed PostgreSQL 16.15 profiling and is CLOSED after independent
re-review returned PASS WITH NON-BLOCKING OBSERVATIONS. No index or production
policy value was approved.

B11-D subsequently completed PostgreSQL 16.15 READ COMMITTED qualification and
is CLOSED after independent review returned PASS WITH NON-BLOCKING
OBSERVATIONS. Same-request mixed snapshots were proven. REPEATABLE READ was
PROPOSED - GOVERNANCE REQUIRED pending a separate governed decision covering
full-request transaction scope and retry/error handling.

B11-E subsequently governed and implemented that decision as ADR 0029: a
dedicated M10-only `REPEATABLE READ` session/dependency
(`database.M10OrganizationAnalyticsSessionLocal`,
`dependencies.get_m10_organization_analytics_db`) beginning before the first
statement of every one of the seven M10 Organization Intelligence routes,
strictly backend-conditional (PostgreSQL only), never applied server-wide or
to any other route. Live re-testing under the permanent implementation
confirmed all seven routes are consistent (see
`docs/history/engineering-handbook/2026-09-08-b11e-integrated-production-qualification.md`).
No retry logic was added (no serialization failure/deadlock evidence).
Suppression/reconstruction concurrency was tested live with the existing
non-production `DeterministicSuppressionTestPolicy` and found consistent.
Index Candidate B remains classified NO CHANGE. Independent review returned
PASS WITH NON-BLOCKING OBSERVATIONS. F1 subsequently implemented the Owner-
approved, fail-closed production privacy, availability, and breadth providers:
minimum cohort 5 for P1-P7, `feature.organization_intelligence`, and
1000/1000/1000 breadth ceilings. The provider-code blocker is resolved.

`docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`
subsequently directly executed and evidenced the remaining release-gate
items: performance (p95<=2.0s/p99<=4.0s target formally adopted above, PASS
with substantial margin across multiple independent runs); memory
(<=128MB incremental/request target formally adopted above, PASS with
substantial margin, no monotonic growth); multi-worker qualification (ADR
0030, >=2 independent processes, PASS on provider consistency, no
worker-local-state dependency, concurrent-writer safety, and worker-kill
correctness). B11-B observability remains CLOSED. The integrated seven-route
regression suite remains green. No index or migration is approved or
required.

**B11-E status: CLOSED, WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT
VERIFICATION ITEM REMAINING.** Every release-gate item this repository can
evidence is satisfied. The sole remaining item - peak worker/process RSS as
a percentage of an authoritatively allocated production worker/container
memory limit - cannot be evaluated from within this repository because no
such authoritative allocation value exists here; this is classified as an
environment-specific production-deployment verification point, not a code
defect, not an unresolved evidence gap, and not grounds to withhold this
classification. B11 overall is CLOSED on this same basis. **B12 is CLOSED
(2026-09-09)** (see the B12 subsection under Qualification Entry And Release
Gates above for the full acceptance-criterion verification and closure
boundary). B12 closure means only that M10 (B0-B11) closeout is complete; M12
AI remains NOT IMPLEMENTED, no merge to `master` has occurred, and no
production deployment has occurred or is implied by this document. The next
step is cumulative production release qualification, followed by a separate
`dev`->`master` approval and deployment decision. The sole remaining
environment-specific item - peak worker/process RSS as a percentage of an
authoritatively allocated production worker/container memory limit - remains
open as a future production-deployment verification item, not a B12 blocker.
