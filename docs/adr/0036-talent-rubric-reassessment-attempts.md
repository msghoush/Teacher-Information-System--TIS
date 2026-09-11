---
title: Talent Rubric Re-evaluation Attempts
documentation_version: 1.0
last_updated: 2026-09-11
status: accepted
module: talent-and-potential
---

# ADR 0036: Talent Rubric Re-evaluation Attempts

## Context

The Product Owner simplified the Talent & Potential authoring flow to:

Program + eligible Grades -> Grade-first rubric authoring -> Student Assessment.

A rubric can change after Students have already completed an Evaluation. Reopening
or mutating a completed Assessment against a changed Framework would reinterpret
historical evidence and violate the existing exact-Framework provenance contract.
At the same time, leaving the completed Assessment as the only current result
would hide the fact that the Student has not yet been evaluated against the
new rubric.

## Decision

### Historical Assessment immutability remains

A completed Assessment is never reopened, rewritten onto another Framework, or
silently reinterpreted. Its competency results, Review Candidate records,
Official Identification decisions, Educator Input, frozen placement context,
and exact Framework Version remain historical evidence.

### Re-evaluation is a new Assessment attempt

When a newer saved Framework Version for the same Program has a different
semantic fingerprint and contains an assessable competency/rubric for the
Student's recorded Grade, a completed current Assessment is reported as
**Re-evaluation required**.

An authorized user starts re-evaluation through the Assessment API. The system:

1. creates a new Assessment Cycle using the newer Framework Version;
2. starts a new Student Assessment using the Student's current effective
   Academic Placement under the existing ADR 0035 eligibility rules;
3. links the new Assessment to the prior Assessment with
   `reassessment_of_assessment_id`;
4. marks the prior Assessment `is_current = false`;
5. keeps the replacement Assessment `is_current = true`;
6. records the supersession/reassessment linkage in the existing Assessment
   audit stream.

The replacement Cycle is an explicit reassessment context. It does not mutate
the original Cycle or its population rows.

### Frameworks with Assessment history are semantically immutable

A Draft/Active/Retired label is not enough to determine whether semantic edits
are safe. Once any Student Assessment references a Framework Version, that
Framework's semantic configuration may no longer be edited in place. A new
Framework Version must be created/cloned before changing competencies, rubric
levels, descriptors, KPI configuration, or candidate-policy configuration.

This closes the historical-corruption gap created by allowing operational
Assessment start against a configured Framework without using lifecycle labels
as a user-facing assessment gate.

### Analytics current-attempt semantics

Current-result analytics use only `TalentStudentAssessment.is_current = true`.
A population member attached only to a superseded Assessment is excluded from
the current analytical population so a reassessment does not double-count one
Student. Historical views may still read superseded Assessments explicitly.

### Permissions and tenant isolation

Re-evaluation reuses `talent_assessments.manage`. Read access remains
`talent_assessments.view`. No new permission key is introduced. Every lookup,
new Cycle, new Assessment, Framework resolution, and Student placement check
remains SchoolGroup-scoped and subject to the existing Branch-authorization
checks.

## Persistence

Migration `20260911_003_talent_assessment_reassessment_attempts` adds:

- `talent_student_assessments.is_current BOOLEAN NOT NULL DEFAULT true`
- `talent_student_assessments.reassessment_of_assessment_id INTEGER NULL`
- a current-attempt lookup index across tenant/program/year/student/current.

The linkage is service-validated and intentionally additive so existing
PostgreSQL/SQLite deployments do not require destructive table rewrites.

## UX

Program creation is simplified to Program identity plus eligible Grades.

Programs expose a separate **Rubric** action. Rubric authoring is Grade-first:
each eligible Grade is independently collapsible and contains its Competencies;
each Competency displays the ordered rubric Levels and Grade-specific
achievement descriptions.

Student Assessments display **Re-evaluation required** when the current
completed Assessment is superseded by a materially changed, assessable newer
Framework. Historical Assessments are labelled historical; the replacement
attempt is the current operational result.

## Consequences

- Historical evidence remains stable.
- Rubric changes no longer silently invalidate or reinterpret completed work.
- Re-evaluation is explicit and auditable.
- Current analytics avoid double counting superseded attempts.
- Framework editing after evidence exists requires a new version.
- No destructive data migration or history rewrite is authorized.
