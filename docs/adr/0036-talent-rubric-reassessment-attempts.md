---
title: Talent Rubric Re-evaluation Attempts
documentation_version: 1.5
last_updated: 2026-09-11
status: accepted
module: architecture
---

# ADR 0036: Talent Rubric Re-evaluation Attempts

## Context

The Product Owner simplified the Talent & Potential authoring flow to:

Program + eligible Grades -> Grade-first rubric authoring -> Student Assessment.

The Owner's governing visual example further fixes rubric ownership as:

`Grade -> Competency -> Competency-owned Rubric -> ordered Levels`.

A Framework-wide shared rubric remains readable only as backward-compatible
legacy configuration. New Grade-first authoring creates one rubric per exact
Framework Competency.

A rubric can change after Students have already completed an Evaluation. Reopening
or mutating a completed Assessment against a changed Framework would reinterpret
historical evidence and violate the existing exact-Framework provenance contract.
At the same time, leaving the completed Assessment as the only current result
would hide the fact that the Student has not yet been evaluated against the
new rubric.

## Same-ID semantic-edit compatibility

The legacy compatibility rule is not limited to changed rubric/level identifiers. Before assessed-Framework immutability was consistently enforced, Student-facing rubric semantics such as labels, descriptions, ordering, descriptors, KPI/policy configuration, or other governed Framework content could be edited in place while preserving stable row IDs. Therefore a completed current Assessment is also **Re-evaluation required** when Talent configuration audit evidence shows a semantic Framework/rubric mutation on that exact Framework after the Assessment's `completed_at`, provided the current Grade-applicable competency-owned rubric is complete and assessable.

Lifecycle-only, branding, annual-plan, and unrelated Program changes do not trigger this rule. The replacement attempt remains append-only/current and starts with zero competency results; the prior completed attempt remains immutable historical evidence.

## Legacy same-Version compatibility repair

The forward rule remains unchanged: once a Framework has Student Assessment evidence, Student-facing rubric semantics are immutable and any later material change belongs in a newer Framework Version.

A bounded compatibility exception exists only for data created before that immutability guard was consistently enforced. If a current completed Assessment remains bound to a Framework Version whose persisted competency-result rubric/level bindings no longer match that same Framework's now-complete competency-owned rubric structure for the Student's recorded Grade, the Assessment is treated as **Re-evaluation required**. An untouched legacy shared-rubric Framework, or a partially configured competency-owned rubric, never triggers this repair.

The repair is operational reset, not evidence deletion: the prior completed attempt becomes non-current and remains immutable; the replacement attempt is current, in progress, contains zero competency results, is linked by `reassessment_of_assessment_id`, and keeps the original visible Evaluation/Term through `evaluation_context_cycle_id`. The same Framework Version may be the replacement target only for this historical compatibility case because the current canonical rubric branch already exists there. No future in-place rubric mutation is authorized by this exception.

## Administrator recovery reset

Automatic `Re-evaluation required` remains the preferred path whenever a
materially changed rubric can be detected deterministically. A separate,
explicit operational recovery path is also accepted for a current completed
Assessment when an authorized administrator needs the Student to be assessed
again even though that automatic condition is not present.

The permission is `talent_assessments.reset_for_reassessment`, assigned by
default to Administrator through the standard all-permissions role rule and
not included in Editor/User defaults.

This action is **not deletion** and does not weaken completed-evidence
immutability. It:

1. requires the target Assessment to be Completed and current;
2. marks only that Assessment `is_current = false`;
3. records an audit action `reset_for_reassessment`;
4. preserves every competency result, Review Candidate, Official
   Identification, Educator Input, placement snapshot, Cycle/Framework context,
   and audit row;
5. leaves the original visible Evaluation available so the normal Start
   Assessment flow can create a fresh current attempt with zero results;
6. preserves the existing physical `UNIQUE(cycle_id, student_id)` contract by
   creating a private derived Cycle for that fresh attempt when the prior
   historical Assessment already occupies the visible Evaluation Cycle. The
   replacement keeps `evaluation_context_cycle_id` pointing at the original
   visible Evaluation, so users do not see a second Evaluation/Term.

ADR 0034 remains unchanged: physical Assessment deletion is still allowed only
for zero-evidence Assessments.

## Decision

### Historical Assessment immutability remains

A completed Assessment is never reopened, rewritten onto another Framework, or
silently reinterpreted. Its competency results, Review Candidate records,
Official Identification decisions, Educator Input, frozen placement context,
and exact Framework Version remain historical evidence.

### Re-evaluation is a new Assessment attempt

When a newer saved Framework Version for the same Program changes the
Student-facing assessable structure for the Student's recorded Grade, a
completed current Assessment is reported as **Re-evaluation required**.

The comparison deliberately ignores Framework version number, title, and
supersession metadata. A no-op clone does not require re-evaluation. Changes to
applicable Competencies, competency-owned Rubrics, ordered Levels, level
descriptions/achievement wording, or other assessable rubric semantics do.

An authorized user starts re-evaluation through the Assessment API. The system:

1. marks the prior current attempt non-current inside the same transaction;
2. creates a new physical Assessment Cycle using the newer Framework Version;
3. starts a new Student Assessment using the Student's current effective
   Academic Placement under the existing ADR 0035 eligibility rules;
4. links the new Assessment to the prior Assessment with
   `reassessment_of_assessment_id`;
5. preserves `evaluation_context_cycle_id` as the original visible
   Evaluation/Term;
6. keeps the replacement Assessment `is_current = true`;
7. records the supersession/reassessment linkage in the existing Assessment
   audit stream.

The replacement physical Cycle preserves exact Framework provenance but is not
a second user-visible Evaluation. Student Assessment lists and current-result
analytics project the replacement back to the original Evaluation context.

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

Current-result analytics use only `TalentStudentAssessment.is_current = true`
and resolve the attempt through `evaluation_context_cycle_id` (falling back to
`cycle_id` for pre-migration rows). The physical reassessment Cycle/population
member is excluded as a second eligible row; the replacement result is projected
to the original Evaluation's Student/Branch/Grade/Section context. Historical
views may still read superseded Assessments explicitly.

### Permissions and tenant isolation

Re-evaluation reuses `talent_assessments.manage`. Read access remains
`talent_assessments.view`. Rubric-authoring deletion is independently governed:
`talent_programs.delete_competency` controls removal of a Competency branch from
an editable Framework and `talent_programs.delete_rubric_level` controls true
Rubric Level removal. These do not imply whole-Program delete authority, and
`talent_programs.manage` alone does not imply either delete capability. Every lookup,
new Cycle, new Assessment, Framework resolution, and Student placement check
remains SchoolGroup-scoped and subject to the existing Branch-authorization
checks.

## Persistence

Migration `20260911_003_talent_assessment_reassessment_attempts` adds:

- `talent_student_assessments.is_current BOOLEAN NOT NULL DEFAULT true`
- `talent_student_assessments.reassessment_of_assessment_id INTEGER NULL`
- `talent_student_assessments.evaluation_context_cycle_id INTEGER NULL`,
  backfilled from existing `cycle_id`;
- current-attempt and Evaluation-context lookup indexes.

Migration `20260911_004_talent_competency_specific_rubrics` adds nullable
`talent_rubrics.framework_competency_id`, removes the old one-rubric-per-
Framework uniqueness rule, and enforces one rubric per exact
`Framework Version + Framework Competency`. Existing NULL-owned rubrics remain
legacy shared rubrics only for historical/read-comparison compatibility. Normal
current Evaluation starts select only a complete competency-owned rubric
structure for every applicable Competency; a legacy shared rubric never makes a
new user-facing Assessment assessable.

The linkage is service-validated and intentionally additive so existing
PostgreSQL/SQLite deployments do not require destructive table rewrites.

## UX

Program creation is simplified to Program identity plus eligible Grades.

Programs expose a separate **Rubric** action. Rubric authoring is Grade-first:
each eligible Grade is independently collapsible and contains its Competencies.
Each Competency owns its own Rubric, and that Rubric owns its ordered Levels and
level descriptions. This mirrors the Owner-provided reference structure rather
than presenting one shared rubric scale for the whole Framework.

When an existing legacy shared rubric is explicitly edited for one Competency,
the service copies the legacy scale and that Competency's descriptor content
into a new competency-owned rubric. Merely cloning without a semantic edit does
not trigger re-evaluation.

Student Assessments display **Re-evaluation required** when the current
completed Assessment is superseded by a materially changed, assessable newer
Framework. Starting re-evaluation opens the replacement attempt against the
newer rubric while keeping the original visible Evaluation/Term. The prior
attempt remains preserved evidence but is not listed as a separate History or
Assessment Records table in the normal operational workspace.

## Consequences

- Historical evidence remains stable.
- Rubric changes no longer silently invalidate or reinterpret completed work.
- Re-evaluation is explicit and auditable.
- Current analytics avoid double counting superseded attempts.
- Framework editing after evidence exists requires a new version.
- No destructive data migration or history rewrite is authorized.
