---
title: Talent Overall Program Result
documentation_version: 2.2
last_updated: 2026-09-23
status: accepted
module: architecture
---

# ADR 0037: Talent Overall Program Result

## Context

Talent Programs assess one Student across multiple competencies. The Product Owner
requires each rubric level to show its ordered numeric rank beside its name and
requires one deterministic overall result for the Program Assessment.

The canonical result must remain meaningful to educators using the rubric. A
Mental Math Program using five ordered levels should therefore report a result
such as `4.4 / 5`, rather than replacing the rubric meaning with an invented
0-100 score.

Different Talent Programs remain separate assessment domains. Mental Math,
Performing Arts, Reading Talent, or future Programs must never be combined into
one universal Student Talent score.

## Decision

### Rubric level number

The canonical numeric rank of a rubric level is its governed ordered position
within the competency-owned rubric:

- first level = 1;
- second level = 2;
- and so on.

The UI renders this number directly beside the level name, for example
`1. Beginning`, `2. Approaching`, `3. Meets`.

The displayed rank is not a second manually-entered score and does not depend on
the optional legacy/KPI `numeric_value` field.

### One coherent Program scale

All Grade-applicable competency rubrics participating in one completed Student
Assessment must use the same number of ordered levels.

For example, if Mental Math is a five-level Program scale, every applicable
competency in that Assessment must use five ordered levels.

TIS must not directly average ranks from incompatible scales such as `4 / 5`
and `3 / 3`. An Assessment with inconsistent applicable rubric lengths cannot
be completed until the rubric structure is aligned.

### Overall Program Result

Once every Grade-applicable competency has a valid saved result, TIS derives the
**Overall Program Result** as the arithmetic mean of the selected ordered rubric
ranks.

Example for a five-level Program:

`3, 4, 5, 5, 5, 3, 5, 5, 5 -> 4.4 / 5`.

The result is rounded to one decimal place using deterministic half-up rounding.

The calculation method identifier is:

`arithmetic_mean_rubric_rank`.

### Normalized presentation percentage

TIS may derive a percentage for progress-bar length, color intensity, or other
bounded visualization:

`average / scale_max * 100`.

This percentage is presentation/analytics normalization only. It is not the
canonical educational result and must not replace the displayed rubric-scale
average.

### Persistence

No new result table or schema migration is introduced.

The Overall Program Result is a deterministic read projection from:

- the exact Student Assessment;
- its immutable Framework Version;
- the Grade-applicable Framework Competencies;
- the stored competency results;
- each competency's exact ordered rubric levels.

Completed historical Assessments retain stable meaning because their exact
Framework Version and evidence remain immutable.

Existing optional Framework KPI configuration remains separate. It is not
redefined or silently reused as the Overall Program Result.

### Talent Review and Official Identification

Talent Review surfaces the rubric-scale Overall Program Result prominently.

The result supports educator review and may coexist with deterministic Review
Candidate policy. It does not itself create an Official Identification decision.

Official Identification remains a separate authorized human decision. Neither a
rubric average nor its color treatment is an automatic `talented/not talented`
classification.

### Multiple Programs

A Student may have separate Overall Program Results for multiple Talent Programs.

Each Program result remains separate. TIS may present them together in a
Students Across Programs matrix, but it must not average or otherwise collapse
those Program results into one universal Talent score.

## Consequences

- Educators see the same 1-N scale they used during assessment.
- The Program result is explainable as an arithmetic mean of competency ranks.
- Inconsistent competency rubric lengths are blocked from completion rather than
  being silently normalized into a different educational meaning.
- A normalized percentage remains available only for visual presentation.
- Multi-Program Student results can be compared visually without being combined.
- Review Candidate and Official Identification remain separate governed concepts.
- Historical assessment evidence remains immutable.
- No schema migration is required for the result projection.

## 2026-09-23 Amendment: Governed 1.00-5.00 Classification Authority (M17)

This amendment appends new governed decisions. It does not rewrite or weaken
any decision above: the raw Overall Program Result on the Program's own 1-N
rubric scale, `normalized_percent`, and the arithmetic-mean calculation
method all remain exactly as decided.

### Product direction

M17 introduces automatic Assessment classification. Once a Student Assessment
is Completed, TIS automatically classifies the Overall Program Result into
one of five owner-approved, fixed bands and derives a `Talented` boolean.
These fixed bands are expressed on a governed **1.00-5.00 classification
scale** that is deliberately independent of any one Program's own rubric
level count:

- 1.00-1.99 Needs Improvement
- 2.00-2.99 Developing
- 3.00-3.74 Meets Expectations
- 3.75-4.49 Advanced
- 4.50-5.00 Exceptional

Only Exceptional means Talented. These bands are never expressed or
recomputed as a percentage, and never reuse `normalized_percent` (which
remains presentation/analytics only, unchanged by this amendment).

### Architecture problem this amendment resolves

The classification bands above are literally valid only for a Program whose
rubric scale is exactly five ordered levels. This ADR's own worked example
("a five-level Program") was always one example, not a universal constant -
`scale_max` is a variable throughout this ADR's "Normalized presentation
percentage" section. Real configured Programs in this repository do not
universally use five levels: the realistic local seed dataset
(`talent_local_test_data.py`, built end-to-end through the real
`talent_program_service`/`talent_student_assessment_service` contracts)
configures a 4-level Program, a 3-level Program, and a second 4-level
Program side by side. Mandating a system-wide five-level rubric for every
Talent Program (rejected Option A) would therefore be a breaking change to
existing real Program configurations, not a small formalization, and would
force every Program owner to redesign already-approved rubric structures
purely to satisfy the classification band's five-way shape.

### Decision: deterministic 1..N -> 1.00-5.00 projection (Option B)

TIS preserves each Program's own configured rubric-level count for the
educational raw result exactly as decided above (the arithmetic-mean rubric
rank on the Program's own 1..N scale is unchanged), and adds one additional,
separately governed **deterministic linear projection** from that raw 1..N
average onto the fixed 1.00-5.00 classification scale:

```
classification_score = 1 + (average - scale_min) * 4 / (scale_max - scale_min)
```

This reuses the exact linear-rescale technique this ADR already approves for
`normalized_percent` (`average / scale_max * 100`), but targets the fixed
classification range `[1.00, 5.00]` instead of a percentage. It is computed
with exact `Decimal` arithmetic directly from the integer `average_tenths`
value already produced by the Overall Program Result projection (never a
second float division of the already-rounded `average`), and the projected
score is rounded deterministically half-up to two decimal places. A
five-level Program's projection is the identity map
(`classification_score == average`), so the M17 product direction's worked
examples remain literally true for a five-level Program while now also being
correct for every other configured scale.

A Program whose rubric scale cannot be projected deterministically - a
degenerate single-level rubric (`scale_max <= scale_min`), or the existing
"inconsistent rubric scale" state this ADR already blocks at completion -
is not compatible with automatic classification. TIS fails closed: no
classification, no Talented state, `available: false` with an explicit
`reason`. This is a new possible outcome, not a new possible error path for
existing consumers of the raw Overall Program Result, which is unchanged.

Implementation: `talent_classification_service.py` (`project_to_
classification_scale`, `classify_score`, `is_talented`,
`assessment_classification`). `overall_program_result` additively exposes
`average_tenths` (the exact integer tenths already computed internally) so
the projection never re-derives precision from a float.

### Persistence

No new result table or schema migration is introduced. Classification, like
the raw Overall Program Result itself, is a deterministic read projection
computed only for a Completed Assessment, from the same immutable inputs
this ADR already establishes as stable (the exact Student Assessment, its
immutable Framework Version, the Grade-applicable Framework Competencies,
the stored competency results, and each competency's exact ordered rubric
levels). A Completed Assessment's classification is therefore exactly as
immutable as its Overall Program Result already is.

### Talent Review and Official Identification (superseded in part)

This ADR's original "Talent Review and Official Identification" section
remains true as a description of the pre-M17 workflow and of the still-
preserved legacy/history surfaces. As of this amendment, for the *current
normal* workflow: automatic classification is a direct backend consequence
of a Completed Assessment. `Talented` (Exceptional classification) no
longer requires a Review Candidate to be materialized, reviewed, or an
Official Identification decision to be recorded. Existing `TalentReview
Candidate` and `TalentOfficialIdentification` rows, including any recorded
before this amendment, are preserved unchanged as legacy/history evidence
and continue to be evaluated/recordable through their existing services for
historical/audit purposes, but they no longer govern current `Talented`
state and are never silently rewritten to match a later automatic
classification.

### Non-negotiable boundaries reaffirmed

- No percentage-band conversion of the classification bands, ever.
- AI has no classification or identification authority.
- The frontend only displays the backend-computed `classification`/
  `is_talented` fields; it never derives or spoofs a band.
- SchoolGroup/tenant/Branch/privacy/audit boundaries are unchanged.

## 2026-09-23 Amendment: Current-Result Authority For Multi-Assessment Students; Learner Profile/Student Drill Integration (M18a)

Added 2026-09-23. Appends only; the M17 amendment above is unchanged.

**Which Assessment is "the applicable current result"?** When a Student has
more than one `TalentStudentAssessment` for a Program (across reassessment
attempts per ADR 0036), the one that governs current M17 classification is
the row where `status == 'completed'` AND `is_current == True`. This was
resolved from existing evidence, not invented: `models
.TalentStudentAssessment.is_current` and its reassessment-flow semantics
already existed before M18a (ADR 0036), and `talent_analytics_service
._assessment_ids_subquery` plus the B9 Student Drill (`talent_org_student
_drill.py`) already used exactly this predicate to select the Assessment
whose Overall Program Result counts for the current Program+Cycle scope.
M18a's own classification integrations use the identical predicate.

**Learner Profile / Student Drill integration.** `talent_learner_profile
_service.build_learner_profile`'s per-Assessment item and `talent_org
_student_drill.py`'s per-context row now additively carry the same
`classification`/`classification_score`/`is_talented` fields already on the
Talent Assessment API (`routers/talent_assessments.py`, since M17), computed
by the same single authority (`talent_classification_service
.assessment_classification`) - never duplicated, never derived from
`TalentReviewCandidate`/`TalentOfficialIdentification`. This closes the
"Current downstream Talented state must use M17 automatic classification"
requirement for per-Student/per-row surfaces. A new org/Branch AGGREGATE
"current Talented count" metric (privacy-safe Cell/Group infrastructure
against a new classification grain) was evaluated and is explicitly deferred
to M18b - see ADR 0044's M18a amendment and this ADR's own frozen `MetricCode`
discipline; it is new analytics infrastructure, not a cleanup-scope change.
