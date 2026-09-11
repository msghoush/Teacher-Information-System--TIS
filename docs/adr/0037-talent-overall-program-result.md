---
title: Talent Overall Program Result
documentation_version: 1.0
last_updated: 2026-09-11
status: accepted
module: architecture
---

# ADR 0037: Talent Overall Program Result

## Context

The Owner requires every Talent rubric level to present a clear ordered number
beside its level name and requires one deterministic overall result per Student
when a Program assesses multiple competencies.

Competencies may use different rubric lengths (for example one competency may
have three levels while another has five). Averaging raw level numbers would
bias the result toward competencies with larger scales.

The result is intended to help educators and leaders review Student performance
inside one Program. It must not collapse Review Candidate, Official
Identification, or cross-Program analytics into one automatic "talented/not
talented" decision.

## Decision

### Rubric level number

The canonical numeric rank of a rubric level is its governed
`TalentRubricLevel.display_order` within that competency-owned rubric.

The UI renders the rank directly beside the level name (for example
`1. Beginning`, `2. Approaching`, `3. Meets`). The rank is not a second
manually-entered score and does not depend on `numeric_value`.

### Overall Program Result

For one Student Assessment, TIS derives an **Overall Program Result** only when
every Grade-applicable Framework Competency has a saved result.

Each competency contributes equally. The selected rubric level is normalized by
its position inside that competency's own ordered rubric:

- first level = 0;
- last level = 100;
- intermediate levels are linearly normalized between 0 and 100.

The Overall Program Result is the deterministic equal-weight mean of those
normalized competency scores, rounded half-up to an integer on a 0-100 scale.

This makes a three-level competency and a five-level competency comparable
without making the longer rubric intrinsically more important.

The calculation method identifier is:

`equal_competency_normalized_rubric_position`.

### Persistence

No new table or migration is introduced.

The Overall Program Result is a deterministic read projection from:

- the exact Student Assessment;
- its exact immutable Framework Version;
- the applicable Framework Competencies;
- the stored competency results;
- each competency's exact rubric and ordered levels.

Completed historical Assessments therefore retain stable results because their
Framework Version and saved evidence are immutable.

Existing optional KPI configuration remains separate. A configured KPI is not
replaced, redefined, or silently reused as the Overall Program Result.

### Talent Review and identification boundary

Talent Review surfaces the Overall Program Result prominently as the primary
cross-competency numeric summary.

The result may support an educator's review and may coexist with governed Review
Candidate rules, but it does not itself create a Review Candidate and does not
record an Official Identification decision.

Official Identification remains a separate authorized human decision. The
overall score and its visual color treatment are never authoritative
"talented/not talented" labels.

### Visual treatment

The result is always displayed numerically as `score / 100`.

A continuous low-to-high visual treatment may be rendered from the already
visible score. Color is supplemental only; the number and accessible label are
always present.

No hidden category thresholds (for example "low", "medium", "high", or
"talented") are introduced by this ADR.

## Consequences

- Rubric level numbering is deterministic and cannot drift from proficiency
  order.
- Multiple competency rubrics with different level counts can contribute fairly
  to one Program result.
- Talent Review gains a clear cross-competency result without changing
  Official Identification authority.
- Historical assessments remain stable.
- No schema migration is required.
- Existing optional KPI and Review Candidate policy architecture remains
  available and independent.
