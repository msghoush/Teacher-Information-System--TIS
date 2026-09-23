---
title: Talent Evaluation Progress Analytics (M4)
documentation_version: 1.1
last_updated: 2026-09-23
status: "Accepted, with the Learning Style Branch-comparison metric removed as of M14 (2026-09-23) - see 'M14 Amendment' section at the end of this document. Original text below preserved unmodified as historical record."
---

# ADR 0044: Talent Evaluation Progress Analytics (M4)

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
