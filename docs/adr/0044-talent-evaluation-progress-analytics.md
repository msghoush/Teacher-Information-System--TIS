---
title: Talent Evaluation Progress Analytics (M4)
documentation_version: 1.6
last_updated: 2026-09-24
status: "Accepted, with the Learning Style Branch-comparison metric removed as of M14 (2026-09-23) and its dead computation code removed as of M18a (2026-09-23) - see the 'M14 Amendment' and 'M18a Amendment' sections at the end of this document. Original text below preserved unmodified as historical record."
---

# ADR 0044: Talent Evaluation Progress Analytics (M4)

## Agent 3 aggregate dashboard amendment (2026-09-25)

The filtered dashboard composes existing authorities in an identity-free
projection. Completion and Classification count Evaluation participations;
Student KPIs and Learning Style count distinct current Students. Current
reassessments resolve through the original Evaluation context. Organization
percentages divide underlying counts, never average Branch percentages.
Result means require one Program, framework and scale; incompatible results
are unavailable, not pooled.

Selected Branch/Grade/Section/Program/Period comparisons are bounded to six groups.
The full authorized comparison family participates in conservative privacy
closure even when only some groups are displayed. Completion uses P2, results
and rubric evidence P3, and Classification P4 provider rules. Suppressed families
emit protected states. Program/Competency/Indicator scope is validated; historical
frameworks retain separate indicators. Ordered periods do not imply growth.

The dashboard reuses M10's read-only repeatable snapshot dependency without changing
global isolation or older endpoint contracts. Requests exceeding 5,000 scoped
population rows fail explicitly for narrowing; totals are never truncated.
The owner-approved Learning Style cohort boundary is recorded in ADR 0031.
Individually authorized operational roster records remain outside aggregate
cohort suppression.

## Context

Following M9 Deterministic Talent Analytics and the M10 Organization
Intelligence family, the Talent & Potential product line still had no
backend-authoritative "Evaluation Progress" contract for Student, Branch,
or Organization scope, and the frontend (`static/js/talent-operations.js`)
computed a client-side average of `overall_result.average` across Review
Candidate rows sharing a common rubric scale. Two design questions were
genuinely ambiguous and were escalated rather than guessed: (1) whether
Evaluation Periods on different governed `framework_version_id`s may be
combined into one Overall Result, and (2) whether an individually
authorized Student's own result should be subject to the same aggregate
cohort-size privacy suppression used for Branch/Organization analytics.

The Owner has now explicitly ratified both decisions below. This ADR
records the M4 architecture and both ratified decisions as the durable
governance artifact.

## Decision

### Canonical Evaluation Period result

The Evaluation Period numerical result input is exactly ADR 0037's Overall
Program Result `normalized_percent` (`talent_student_assessment_service
.overall_program_result`). ADR 0037's rubric-scale/KPI educational
semantics are unchanged; `normalized_percent` is read-only input here.

### Active/opened Evaluation Period predicate (confirmed, not new)

An Evaluation Period is an active/opened weighting position exactly when
`TalentPlannedEvaluationPeriod.status == 'planned'` AND its linked
`TalentAssessmentCycle.status IN ('open', 'closed')`. This was verified
directly against `models.py` and
`talent_evaluation_plan_service.validate_cycle_period_link`/
`validate_linked_cycle_open`, which only ever create or preserve that
link under an Active Plan + Planned Period + Draft-then-Opened Cycle. A
cancelled Period, a not-yet-linked/opened Period, and an ad-hoc (unlinked)
Cycle are never a weighting position. Configured label/short_code never
affect order or weight; only governed `sequence` orders Periods. For A
active Periods, the derived (never persisted) nominal weight is `1/A`.

### DECISION 1 — Framework comparability (owner-ratified)

Evaluation Period results are combinable into one Overall Result only when
every contributing active Period's linked Cycle shares one identical
governed `framework_version_id`. When active Periods span more than one
`framework_version_id`, every Period is still returned individually
(preserving its own result and nominal weight), the combined Overall
Result is `null`/unavailable, and `comparability_state="not_comparable"` /
`comparability_reason_code="framework_changed"` is reported. No
cross-framework delta/improvement is calculated, no framework-equivalence
mapping is introduced, and no normalization across frameworks is
performed. This is consistent with, and does not weaken, ADR 0027/B10's
existing Framework-sensitivity precedent for longitudinal comparability.

### DECISION 2 — Single-Student disclosure (owner-ratified)

An individually authorized Student's own Evaluation Progress is governed
by normal Student/Talent authorization and tenant/Branch scope - the
existing `talent_learner_profiles.view` permission plus the same
frozen-historical-Branch check `talent_learner_profile_service
.build_learner_profile` already applies - and is NEVER subject to
aggregate cohort-size privacy suppression merely because the result
belongs to one Student. An unauthorized Student's result remains
inaccessible (non-enumerating 404, matching the existing Learner Profile
convention); aggregate Branch/Organization privacy is completely
unaffected by this rule, and this rule never permits exposure of a
suppressed aggregate value or reconstruction of unauthorized cohort
analytics through repeated single-Student reads (the M4 Student route
returns only that one Student's own already-authorized historical facts,
with no cross-Student aggregation capability). This is consistent with,
and generalizes, ADR 0031's existing statement that "Individual Student
Learning Style values remain governed by normal Student-record permissions
and are not a substitute for aggregate analytics."

### Branch / Organization Evaluation Progress

`BranchPeriodResult(B,p)` is the mean of valid governed Student
`normalized_percent` results attributed to Branch B for Period p, using
frozen historical `TalentAssessmentCyclePopulationMember.branch_id`
attribution (never current Placement). `OrganizationPeriodResult(p)` is
computed directly from every valid governed Student result in the
authorized organization scope - never as an average of
`BranchPeriodResult` values. Pending/unavailable Student results are
excluded from both, never treated as zero. Overall Results (across
comparable active Periods) are the mean of the available privacy-safe
Period results; a Pending/suppressed Period is excluded, never zero, and
is never reconstructable from the combined Overall value.

### Privacy

Every Branch/Organization aggregate reuses only the M9 generic privacy
primitives (`Cell`/`Group`/`apply_primary_privacy`/
`run_complementary_suppression` in `talent_analytics_privacy.py`) - never
the M10 `talent_org_intelligence_contract.py` `MetricCode`/`CellIdentity`
vocabulary, which this milestone leaves frozen and unmodified. Every
aggregate is gated on an authorized contributing-count `Cell` (parent
total = sum(per-Branch counts)); a derived mean is only serialized when
its own count `Cell` is independently `visible` after complementary
suppression, exactly mirroring the existing `build_privacy_safe_coverage
_bundle` all-or-nothing convention.

### Branch comparison metrics (exactly seven, no MetricCode extension)

`talent_evaluation_progress_service.branch_comparison_metric` is a bounded
dispatcher supporting exactly: Evaluation Period Result, Current/Overall
Progress (both new M4 contracts above), Assessment Completion, Assessments
Started, Meets Program Criteria, Officially Confirmed (all four reusing
the existing M9 `raw_coverage_by_dimension`/`raw_candidate_by_dimension`/
`raw_identification_by_dimension`/`build_breakdown_group` providers
unchanged), and Learning Style (new). This dispatcher is local to M4 and
does not add to, or otherwise modify, the frozen 14-value M10 `MetricCode`
enum.

### Learning Style Branch aggregate

The Branch aggregate for one selected dimension (Verbal/Non-verbal/
Quantitative/Spatial) is the arithmetic mean of valid (non-null) current
`Student` percentage values (ADR 0042) in the authorized Program-population
cohort; `null` is excluded, `0` is a real included value, there is no sum
rule, no normalization, and no dominant-style derivation. It is protected
by the identical `Cell`/`Group` privacy mechanism used for
Branch/Organization Evaluation Progress, per ADR 0031's existing
requirement that aggregate Learning Style distribution "go through the
same privacy/suppression contract already governing Talent aggregate
analytics."

## Consequences

- The frontend's client-side Review-Candidate-average
  (`talent-operations.js`) is unrelated to, and untouched by, this new
  backend contract; a future frontend milestone may adopt the new
  authoritative endpoints.
- No schema or migration change; no new permission; the M10 `MetricCode`
  registry is unmodified.
- `normalized_percent` is not a stored column, so Branch/Organization
  aggregation calls `overall_program_result` once per Completed Assessment
  in scope rather than a single SQL aggregate - a documented, bounded
  per-assessment cost at the same Program+AcademicYear scale every other
  M9/M10 module already operates at, not a claimed PostgreSQL performance
  qualification.
- The four M9-reused Branch comparison metrics (Assessment Completion,
  Assessments Started, Meets Program Criteria, Officially Confirmed)
  inherit that existing M9 characteristic where an all-zero cohort's total
  `Cell` receives `raw_value=0` rather than `None`, so a policy may label it
  `suppressed` instead of `no_data` - no raw value is ever leaked either
  way (this is a label-only nuance, not a privacy defect), and it is
  unchanged from the existing, already-reviewed `/breakdowns/branch` route
  behavior this milestone reuses rather than duplicates.

## M14 Amendment (2026-09-23): Learning Style Branch Aggregate Removed

Added 2026-09-23, per the same owner-directed M14 correction recorded in
ADR 0031's and ADR 0042's own M14 amendment sections. The text above is
preserved unmodified as the historical record of the seven-metric dispatcher
as originally delivered.

The "Learning Style Branch aggregate" metric above averaged the four
`learning_style_*_percentage` columns (ADR 0042) across a Branch population.
Under the M14-corrected model, "percentage" means population/aggregate
distribution over the single categorical `Student.learning_style` field
(now eight values), never a mean of independent per-Student dimension
scores - so this metric's underlying premise no longer holds. It is REMOVED
from `talent_evaluation_progress_service.APPROVED_BRANCH_METRICS` as of
M14: a request for the `learning_style` metric now receives the same
`invalid_filter`/400 response as any other unrecognized metric value,
rather than continuing to report a semantically wrong number. The
Branch-comparison dispatcher now supports exactly six metrics (the seven
above, minus Learning Style). A categorical distribution replacement for
this specific Branch-comparison surface (if wanted) is out of M14 scope and
is left for a later, separately governed milestone; the Student-domain
aggregate Learning Style distribution required by ADR 0031 continues to be
served by `student_learning_style_analytics.py` (Students page), unaffected
by this removal.

## M18a Amendment (2026-09-23): Dead Learning Style Branch Aggregate Code Removed; is_current Confirmed as Applicable-Current-Result Authority

Added 2026-09-23. Two confirmations, no new rule:

**Dead code removal.** The M14 amendment above removed `learning_style` from
`APPROVED_BRANCH_METRICS` but deliberately kept
`learning_style_branch_aggregate`/`_learning_style_values_by_branch`/
`_LEARNING_STYLE_COLUMNS` in `talent_evaluation_progress_service.py`,
unreferenced by the dispatcher, purely so the deprecated-column mean
computation was not silently mutated. M18a re-verified directly that
`branch_comparison_metric` (`routers/talent_evaluation_progress.py`'s only
caller of any Branch-comparison metric) has rejected `"learning_style"`
before ever reaching that code since M14, confirming the three symbols were
genuinely unreachable from any current endpoint/service path. They were
removed outright, along with their two direct-call tests
(`tests/test_talent_evaluation_progress.py`, formerly "Section 8"). The
`learning_style_dimension` query parameter on
`routers/talent_evaluation_progress.py`'s branch-comparison route remains
present but was already inert (rejected before use) since M14 and is left
untouched - removing that plumbing is a separate, non-blocking cleanup, not
required to close "no current four-dimension Learning Style analytics
authority."

**2026-09-24 Amendment (M18b-1).** The `learning_style_dimension` query
parameter/keyword argument was re-audited directly (grep, not assumed) and
confirmed still genuinely unreferenced inside `branch_comparison_metric`'s
own body - it was removed outright from
`routers/talent_evaluation_progress.py`'s branch-comparison route and from
`branch_comparison_metric`'s signature in
`talent_evaluation_progress_service.py`. No schema/behavior change: the
function still raises `invalid_filter` for any `metric` outside the six
`APPROVED_BRANCH_METRICS`, exactly as before. The governed Family 1 Learning
Style backend contract (categorical distribution, never a per-dimension
mean) is `student_learning_style_analytics.py`, now also reachable through
`talent_results_analytics_service.py`'s bounded M18 Results & Analytics
contract (see the M18b-1 release note).

**Applicable-current-result authority confirmed.** M18a needed to resolve
which `TalentStudentAssessment` governs a Student's current M17
classification when more than one exists for a Program. This ADR's own
"Active/opened Evaluation Period predicate" section already establishes that
only `sequence`-ordered, actually-active Periods weight into a combined
result; separately, `models.TalentStudentAssessment.is_current` (set by the
reassessment flow this repository already implements per ADR 0036) is the
authority for which Assessment attempt is the current one for a given
Program+Cycle+Student, already consumed by
`talent_analytics_service._assessment_ids_subquery` and the B9 Student Drill
before M18a. M18a's `talent_classification_service.assessment_classification`
integrations (Learner Profile, B9 Student Drill) use exactly this same
`status == 'completed' AND is_current == True` predicate - no new business
rule was introduced, and this ADR is not reopened.

## Acceptance C Note (2026-09-24): Learning Style Aggregate Privacy

The "Learning Style Branch aggregate" section above (already removed by M14)
cited ADR 0031's requirement that the aggregate distribution go through the
Talent privacy/suppression contract. ADR 0031's "Acceptance C Amendment"
(2026-09-24, owner decision) supersedes that requirement for the categorical
Learning Style distribution only: it is authorized Student-domain aggregation,
denominator including Unassigned, with no Talent small-cell suppression. This
ADR's own Evaluation Progress metrics and their Cell/Group suppression are
unchanged.

## Batch 1 Amendment (2026-09-24): Distinct-Student Headline And Current-Student Reads


> **Correction (2026-09-25).** Wording elsewhere in the Batch 1 documentation that the
> global Branch is only a "default" Talent scope is superseded: the global Branch is a
> hard ceiling enforced server-side (`talent_branch_scope`; M10 `resolve_access_context`
> becomes Branch-scoped when the actor's global scope is one Branch, so
> `accessible_historical_branch_ids` = that Branch and every Evaluation Progress /
> analytics route inherits it). Branch comparison and the Organization Talent Map remain
> available only under an explicit global All Branches. No `MetricCode`, privacy or
> Evaluation Progress semantics changed.

Owner rule: current Talent figures use only Students that currently exist. This ADR's
population queries (`population_query`, and the M10 `frozen_membership_query`) now
require the Student to exist in the same SchoolGroup, and the Evaluation Progress
Branch/Organization result reads do the same. The Overview headline for "Students" is
the DISTINCT-Student count published through the existing B2 pipeline at class P2 using
the existing `student_drill_population`/`count`/`distinct_student` coordinate in the
`overview` projection family only (no new `MetricCode`, no new `MembershipGrain`; the
B9 P7 Student Drill gate and its identification rules are unchanged). Membership-grain
metrics (`frozen_eligible`, `completed`, coverage) keep their definitions and
denominators; only their user-facing labels changed to state their grain.

## Owner Amendment (2026-09-25): Branch Authority For Organization-Authorized Actors

Dated owner-directed amendment; the Batch 1 closure text above is preserved as history.
The closure statement that the global (sidebar) Branch is a hard Talent ceiling is
superseded for organization-authorized actors only. The sidebar selector lists real Branches.
For an organization-authorized actor (`auth.can_access_all_branches`) the Talent ceiling is
the actor's own authorization (all Branches of the SchoolGroup); the sidebar Branch is only the
default page-level Branch, and the Talent Branch filter offers All Branches and each authorized
Branch. For a Branch-limited actor the ceiling remains their authorized Branch(es) and any
attempt to name another Branch is rejected. An omitted `branch_id` means every authorized
Branch; an explicit `branch_id` is validated server-side, and tenant isolation is unchanged. The
`branch_scope=all` marker cookie and `user.scope_all_branches` are removed (an old cookie is
ignored). No `MetricCode`, privacy, Evaluation Progress or schema change.

Classification note (same date): an aggregate Classification band that reads "Unavailable" is the
approved Release 1 provider withholding a band cell below the minimum cohort (or a total below it,
or a fail-closed absent configuration). No rule changed; the UI states one uniform value-free
explanation. Making small cohorts visible needs an explicit owner decision and an amendment here
and in ADR 0028.

## Final Closure Part A Amendment (2026-09-25): Start Assessment Eligibility Agrees With The Roster

Dated amendment; no `MetricCode`, privacy, suppression or analytics semantics changed. The Student
Assessments roster (`GET /api/talent/assessment-cycles/{id}/eligible-students`) keeps listing every
currently placed Student (ADR 0035/0039), and now also carries, per row, the backend result of the exact
predicate Start Assessment enforces: `can_start`, `start_block_code` (`assessment_tool_unavailable` when the
Student's Grade has no saved assessable criteria in the Program per the ADR 0039 Grade-aligned amendment,
`duplicate_assessment` when a current Assessment already exists in the Evaluation) and a fixed bounded
`start_block_reason`. The client must render Start only when `can_start` is true. `POST
/api/talent/assessments` accepts an optional echoed `program_id` / `academic_year_id` and rejects a mismatch
with the Cycle as 409 `context_mismatch`; the Cycle remains the sole context authority. Authorization,
tenant, Branch, Academic Year and evidence-immutability rules are unchanged.

## Part 2 Amendment (2026-09-25): Chart Types, Background Refresh And Progress Over Time (presentation only)

Dated, presentation-only amendment; no `MetricCode`, privacy, suppression, Classification,
Learning Style or Evaluation Progress semantic changed. (1) Chart types: the selector offers only
materially different types; circular types only for a full public partition of at most eight
categories and never for time series, ordinal Rubric levels or Learning Style (nine categories);
percentages and counts remain visible in every type and in the accessible table; no frontend
threshold or derived value exists. (2) Dashboard filters refetch in the background under the same
authorized read API (`.../dashboard`), with cancellation of superseded requests and only the newest
response rendered. (3) Progress Over Time stays a real per-Program view over the ADR 0027
longitudinal projection; a period that is suppressed or has no Student result yet is a gap
("Unavailable" / "No data yet"), never zero, and different Program frameworks are never combined.

## Final Closure Part B Amendment (2026-09-25): Central Organization Configuration Authority

Dated governance amendment; no `MetricCode`, privacy or analytics semantics changed. Owner decision: Talent
configuration (Programs, Frameworks/Rubrics, Competencies/Indicators, KPI/policy, annual Program
configuration, Evaluation Plans/Periods and Assessment Cycle definitions) is SchoolGroup-level shared
configuration governed once by the organization Administrator; there is no Branch copy or Branch enablement
model and Programs carry no Branch ownership. Branch state is Students, placements, Cycle population
evidence, Assessments, results and Branch analytics. Every configuration mutation route requires its
existing semantic permission (`.manage/.govern/.delete*`, default Administrator-only) and organization/global
access scope; Branch-scoped actors read shared configuration and assess Students in their Branch but never
mutate configuration. This supersedes the earlier statement that a Branch-scoped `.manage` holder may author
Draft Program/Framework/Cycle metadata (preserved in older documents as history). Stored custom grants are not
rewritten. Analytics reads and the Branch authorization above are unchanged.
