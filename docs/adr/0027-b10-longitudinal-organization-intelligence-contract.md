---
title: B10 Longitudinal Organization Intelligence Contract
documentation_version: 3.7
last_updated: 2026-09-09
status: accepted
module: architecture
---

# ADR 0027: B10 Longitudinal Organization Intelligence Contract

## Context

M10 B0-B9 established a governed, privacy-closed Organization Intelligence
family (`talent_org_intelligence_contract.py`, `talent_analytics_relationship_
graph.py`, `talent_analytics_privacy_closure.py`, `talent_org_intelligence_
service.py`) covering a single Program × single Academic Year snapshot:
Overview (B5), Talent Map (B6), Program Portfolio/Branch Intelligence (B7),
Participation Overlap (B8), and Student Drill (B9). None of these routes
present a Program's results across time. A prior read-only investigation
produced a B10 "Longitudinal Organization Intelligence" architecture
proposal; an independent governance review returned "approve with required
amendments," most significantly correcting an early lean toward the
`TalentAssessmentCycle` as the ordering authority. This ADR records the
amended, approved architecture decision (B10-A). It authorizes no code: B10
itself remains not implemented, and this decision is the prerequisite
checkpoint before B10-B implementation may begin.

## Decision

**Product boundary.** B10 MVP is Longitudinal Organization Intelligence,
strictly bounded to one Talent Program, one Academic Year, aggregate/
non-identifiable output, the ordered M8 `TalentPlannedEvaluationPeriod`
slots within that Academic Year, and exactly one selected metric per
response. B10 MVP explicitly excludes multi-Academic-Year chronology,
matched-cohort analytics, Student growth analytics, Student-level
longitudinal history, cross-Program performance normalization, ranking, and
AI. The M7 Learner Profile remains the governed individual-Student
historical surface; B10 does not duplicate or replace it.

**Route contract.** `GET /api/talent/organization-analytics/programs/
{program_id}/longitudinal`. Required query parameters are `academic_year_id`
and exactly one approved metric. Optional bounded filters are limited to
`branch_id`, `grade_level`, and `planning_section_id`, reusing the existing
frozen-provenance filter semantics already supported by M10 B3/B4; no
arbitrary query grammar is approved. This route is APPROVED ARCHITECTURE,
NOT YET IMPLEMENTED.

**Academic-Year governance.** B10 MVP is single-Academic-Year only;
`academic_year_id` is mandatory. `AcademicYear.year_name`/label remains
purely descriptive and must never be parsed, numerically interpreted,
lexically sorted, or used as chronology authority. Cross-Academic-Year
longitudinal ordering is explicitly deferred pending a future, separately
governed Academic Year chronology/domain contract. No schema change is
approved by this decision.

**Authorization.** Because B10 MVP is single-Academic-Year, it reuses the
existing single-AY `resolve_access_context` for exactly the requested
Academic Year - authentication, SchoolGroup, commercial availability,
`talent_analytics.view`, tenant-bound requested Academic Year, authorized
historical Branch scope, approved filters, Candidate/Identification
secondary permission projection, breadth, aggregation, privacy closure, then
serialization. No multi-AY access resolver is approved or required. Current
`StudentAcademicPlacement` remains non-authoritative for historical scope.

**Time-point model.** One longitudinal presentation point is one M8
`TalentPlannedEvaluationPeriod` slot, ordered only by its governed
`sequence`. The Period is the presentation/order authority; its optional
linked `TalentAssessmentCycle`, when authoritative (Open or Closed), supplies
the factual analytical evidence for that point. This is a deliberate
correction from the original proposal's lean toward the Cycle as ordering
anchor. Required conceptual point identity is `academic_year_id`,
`program_academic_year_configuration_id`, `annual_evaluation_plan_id`,
`evaluation_period_id`, `evaluation_period_sequence`, optional `cycle_id`,
and optional `framework_version_id`. Different Programs may plan different
Period counts; no Baseline/Midyear/Final structure is assumed. The database's
one-Cycle-per-Period uniqueness constraint
(`uq_talent_assessment_cycles_period` on
`TalentAssessmentCycle.planned_evaluation_period_id`) is the schema evidence
for this model; no schema change is approved by B10-A.

**Point/state semantics**, using exact existing lifecycle values verified in
`models.py` (`TalentAssessmentCycle.status` is exactly `draft`/`open`/
`closed`; `TalentPlannedEvaluationPeriod.status` is exactly `planned`/
`cancelled`): a linked Open or Closed Cycle is an authoritative factual
point; a missing linked Cycle is `no_data`/`missing_cycle`; a linked Draft
Cycle is `no_data`/`cycle_not_authoritative`; a cancelled Period is
`no_data`/`cancelled_period`; an authoritative point with no frozen
population is `no_data`/`no_frozen_population`. An unlinked/ad-hoc Cycle (no
governed M8 Period) is excluded from B10 MVP entirely. A missing or
non-authoritative annual Plan never fabricates series facts, and historical
facts remain readable for a retired/inactive Program when its requested AY
configuration remains valid and authorized.

**Metric allowlist.** Exactly nine of the fourteen existing `MetricCode`
values (verified in `talent_org_intelligence_contract.py`) are approved for
B10: unconditional `frozen_eligible`, `completed`, `completion_coverage`,
`assessment_started`, `started_coverage`; Candidate-permission-conditional
`candidate_count`, `candidate_of_eligible`; Identification-permission-
conditional `identified_count`, `identified_of_eligible`. Excluded, with
reasons: `required_period_execution` (Plan-wide execution grain, not a
Cycle-population longitudinal point), `programs_configured`/
`active_programs` (organization configuration headline metrics, not
per-Program longitudinal facts), `participation_overlap` (a cross-Program
pair metric, incompatible with a single-Program B10 route),
`student_drill_population` (the P7 Student Drill disclosure gate, not a
longitudinal analytics metric). No new `MetricCode` is approved by B10-A;
the contract remains exactly 14 `MetricCode` / 3 `MeasureComponent` / 7
`MembershipGrain` values. Exactly one metric is selected per response,
deliberately bounding response complexity, privacy topology, breadth, and
redundant disclosure - a multi-metric B10 query is not approved.

**Comparability, not growth.** Each adjacent Period-point pair for the
selected metric is evaluated as exactly `comparable` or `not_comparable`.
The approved `not_comparable` reason codes are `missing_cycle`,
`cycle_not_authoritative`, `cancelled_period`, `no_frozen_population`,
`metric_unavailable`, `framework_changed`, and `privacy_protected`.
"Comparable" means only that two cross-sectional factual points may be
neutrally shown side by side - never that they share the same Student
cohort, and never Student growth, improvement, decline, or progress.

**Framework policy.** Framework sensitivity is metric-specific.
`frozen_eligible`, `completed`, `completion_coverage`, `assessment_started`,
and `started_coverage` remain comparable across a Framework-version change.
Candidate and Identification metrics become `not_comparable` with
`reason_code=framework_changed` when adjacent points use different Framework
versions. Every authoritative point retains its own historical
`framework_version_id`. No KPI/rubric normalization, framework equivalence
mapping, or universal performance scale is approved.

**No server delta.** B10 MVP must not return any server-computed
longitudinal arithmetic between points - no `delta`, `change`, or
`percent_change` field, and no `current = previous + delta` relationship.
This is an intentional privacy decision: an exact derived difference could
reconstruct a protected endpoint. B10 returns only individually
privacy-closed factual points plus safe comparability metadata. Future UI
may use neutral factual language ("higher/lower than previous Period,"
"period-to-period difference," "side-by-side result") only when both
underlying points are already safely visible and comparable, and must not
use `growth`/`improvement`/`decline`/`progress` language; no matched-cohort
authority exists.

**Privacy architecture.** B10 reuses the existing M9/M10 P1-P7 privacy
classes; no new privacy class is introduced. The pipeline per point/
component is authorization -> frozen scope -> canonical Cell -> primary
privacy -> B2 closure -> strict closed wrapper -> serializer. No arithmetic
is derived from raw pre-closure values for longitudinal disclosure, and no
cross-time additive Relationship is fabricated (Period populations are not
presumed disjoint, and no `annual total = sum of Period populations`
identity is asserted). `no_data` remains not zero. Rate metrics
(`completion_coverage`, `started_coverage`, `candidate_of_eligible`,
`identified_of_eligible`) derive each Period point's percentage only from
that Period's own compatible numerator/denominator after privacy closure -
never by averaging percentages across Periods - and never reconstruct a
protected component through the derived rate.

**Candidate/Identification permission.** Candidate metrics require
`talent_review_candidates.view`; without it, no Candidate query, Cell,
field, or placeholder is produced, and a request selecting a Candidate
metric without the permission fails safely before any Candidate analytical
SQL runs. Identification metrics require the equivalent
`talent_official_identifications.view` with identical query-skip discipline.

**Response contract (conceptual).** `projection_family =
program_longitudinal`; Program identity (stable id, descriptive name);
Academic Year identity (id, descriptive label only); the selected metric;
authorized scope/filter description; ordered Period points, each carrying
program configuration identity, annual plan identity, Period id/sequence,
descriptive Period label/status, optional linked Cycle id/status, historical
Framework version id, and a privacy-closed metric result/state; adjacent
comparisons with Period ids, comparability state, and optional governed
reason code. Explicitly absent: server delta, Student identifiers, privacy
threshold, `raw_value`, suppressed underlying count, hidden cohort total,
and mutable current Framework metadata substituted for historical identity.

**Query architecture (conceptual).** Resolve single-AY tenant/Program/Plan/
Period context, resolve historical authorized filters, evaluate breadth,
aggregate the selected metric by authoritative Cycle/Period using bounded
set-based SQL, conditionally query Candidate/Identification only when
authorized and selected, build per-point canonical Cells, apply primary
privacy and B2 closure, derive any rate only from safely closed components,
compute comparability metadata without numeric deltas, and serialize only
through a strict closed wrapper. No Student materialization, no Student ID
sets, no matched cohorts, no per-Period query loop/N+1, and no nested
Session; one caller-owned Session is used throughout. PostgreSQL
consistent-snapshot and performance/concurrency verification remain a
production/B11 qualification gate, not part of this decision.

**Deferred capabilities.** Multi-Academic-Year chronology; multi-AY
longitudinal series; canonical Academic Year ordering; a multi-AY
authorization resolver; matched Student cohorts; retained-Student growth;
Student movement decomposition; per-Student organization longitudinal
analytics; KPI/rubric normalization across Framework versions;
cross-Program performance normalization; server deltas; AI interpretation.

**Production gates (open, not implied ready).** Production privacy
provider/threshold; commercial availability mapping; production breadth
configuration; PostgreSQL consistent-snapshot validation; PostgreSQL
performance/concurrency qualification; future Academic Year chronology
governance before multi-AY support; final M10 security/release
qualification.

**Status.** B10-A architecture contract: APPROVED/GOVERNED by this ADR. B10-B
is implemented and independently security/privacy reviewed with PASS and
non-blocking observations; B10 is CLOSED. As of 2026-09-09 (ADR 0028, ADR
0030), B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION
ITEM REMAINING and B11 overall is CLOSED on that same basis; B12 is CLOSED.
B8 Participation Overlap and B9
Student Drill remain CLOSED after passed targeted independent re-reviews;
their committed/pushed implementations remain part of current dev. This
decision does not reopen either milestone.

## Rejected Alternatives

- Cycle-as-ordering-authority: the original proposal's lean toward treating
  `TalentAssessmentCycle` as the primary ordering anchor was rejected during
  governance review because Cycles are optional/nullable and not guaranteed
  to exist per Period; the governed M8 Period `sequence` is the only stable
  per-Program ordering authority, with the Cycle supplying evidence only.
- Server-computed delta/percent-change: rejected because an exact derived
  difference between two privacy-closed points can reconstruct a protected
  endpoint that neither point alone would expose.
- Multi-Academic-Year longitudinal chronology in B10 MVP: rejected because no
  authoritative Academic Year chronology/ordering contract exists yet;
  `AcademicYear.year_name` is descriptive only and unsafe to sort or parse.
- Matched-cohort/Student-growth semantics: rejected for B10 MVP because no
  governed cross-time Student identity/matching authority exists; this
  remains the province of the M7 Learner Profile at the individual level.
- Multi-metric-per-response: rejected to bound response complexity, privacy
  topology, breadth evaluation, and redundant disclosure risk.

## Consequences

- After the governance checkpoint is committed and pushed, B10-B may proceed using the exact
  route, metric allowlist, time-point model, comparability vocabulary, and
  privacy discipline recorded above, without re-litigating the Period-vs-
  Cycle ordering question.
- The existing M10 B3/B4 access-context and privacy-closure primitives are
  reused unchanged; no new authorization resolver is required for B10 MVP.
- Future M11 visualization work may rely on the approved comparability/
  Framework-change vocabulary without inventing growth language.
- Multi-Academic-Year longitudinal intelligence remains blocked until a
  separate Academic Year chronology decision is governed and approved.

## Related Files

- `talent_org_intelligence_contract.py`
- `talent_org_intelligence_service.py`
- `talent_analytics_privacy_closure.py`
- `talent_analytics_relationship_graph.py`
- `routers/talent_organization_analytics.py`
- `models.py` (`TalentAssessmentCycle`, `TalentPlannedEvaluationPeriod`,
  `TalentAnnualEvaluationPlan`)
