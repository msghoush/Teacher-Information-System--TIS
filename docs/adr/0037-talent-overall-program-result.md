---
title: Talent Overall Program Result
documentation_version: 2.0
last_updated: 2026-09-11
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
