---
title: "ADR 0039: Talent Competency -> KPI -> Level Simplification"
status: accepted
date: 2026-09-12
decision_owners:
  - Product Owner
supersedes:
  - "ADR 0035 (condition 4 of the assessability list, amended below - the rest of ADR 0035 stands unchanged)"
---

# Context

A full operational diagnostic of Talent & Potential (this same day) found two
independent defects: an eligibility check that silently blocks Start
Assessment whenever a Student's Grade has no separately-authored competency,
and a Program-readiness banner that shows "Ready" without verifying every
eligible Grade actually has assessable content. Investigating those defects
surfaced the underlying design: the current implementation treats a
Program's competency set as something that must be authored per-Grade, and
treats "Rubric" as an internal domain object presented only as "Assessment
Criteria" to keep it distinct from the separate numeric `TalentKpiConfiguration`
feature (`docs/AI_PROJECT_CONTEXT.md`, "Talent Rubric Vs Assessment Criteria
Vs KPI Terminology").

The Product Owner has now directly, explicitly rejected both the per-Grade
authoring requirement and the "Assessment Criteria" terminology, in favor of
one deliberately minimal model.

# Decision

## Grade is context, not an eligibility gate

Amending ADR 0035 condition 4 (the rest of ADR 0035's assessability list and
its Supersession/Consequences sections are unchanged): a Student is
assessable once the Evaluation's assessment framework has at least one
Competency with at least one KPI/criterion and at least one Level - full
stop. The implementation must NOT additionally require that Competency to be
scoped to the specific Student's Grade. If Grade-specific content exists for
the Student's Grade, it may be preferred/shown; if it does not, the
Program's saved build is used instead of blocking. Grade remains valid as
display context and as historical provenance captured at assessment-start
time (per ADR 0035's existing snapshot mechanism) - it must never again
cause `assessment_tool_unavailable` or hide an otherwise-eligible Student
from the Student Assessments list.

## User-facing hierarchy: Competency -> KPI -> Level

The user-facing authoring and assessment hierarchy is exactly: Competency,
then KPI (one assessment criterion per Competency, in the normal flow),
then ordered Levels. "Assessment Criteria"/"Rubric" as a normal-user-facing
label is retired in favor of "KPI" for this hierarchy. Internal schema/API
names (`Rubric`, `TalentRubricLevel`, etc.) may remain unchanged where
renaming them would carry unnecessary migration risk - this is a
presentation-layer rename, not a schema rename.

**Explicit terminology-collision requirement, not resolved by this ADR**:
`docs/AI_PROJECT_CONTEXT.md` records a separate, real `TalentKpiConfiguration`
numeric-KPI feature with its own Add/Edit/Delete controls, deliberately kept
distinct from rubric-based Assessment Criteria specifically to avoid this
exact naming collision. This ADR authorizes relabeling the rubric-based
Competency-criterion hierarchy as "KPI" in the primary Competency -> KPI ->
Level flow. It does NOT authorize merging, removing, or silently renaming
the separate `TalentKpiConfiguration` feature. The implementer must
re-verify whether that separate feature still exists and is still exposed
in the UI; if so, the implementer must flag the resulting two-different-
things-both-called-"KPI" collision explicitly for a follow-up Owner naming
decision (e.g., renaming the numeric feature to "Quantitative Score" or
similar) rather than resolving it unilaterally.

## Readiness: Competency + KPI + Level + Save = Ready

A Program's user-facing readiness is exactly: at least one Competency, with
at least one KPI, with at least one Level, saved. No separate Finish
Setup/Activate/Open step is required in the normal user flow. Whatever
internal Framework-version activation/lifecycle bookkeeping the schema
still requires (per ADR 0035, this remains valid as internal provenance) must
happen transparently as part of Save, not as a distinct user-visible step.
When readiness is not met, the UI must name the exact single missing
requirement in plain language, never a generic Draft/Ready binary with no
explanation.

## Competency delete is a subtree operation

Deleting a Competency through the normal UI removes its KPI and Levels from
the current/future build as one action with one confirmation, never a
KPI-then-Levels-then-Competency manual sequence. Historical completed
Assessment evidence referencing that Competency remains immutable and
preserved via the existing version/history architecture (per ADR 0035); the
delete removes the Competency only from the current/future assessment build,
never from completed history. No Draft/version complexity is exposed to the
user to perform this action.

## Explicit non-goals

This ADR does not weaken tenant isolation, Branch authorization, Student
existence checks, Academic Year context requirements, data integrity, or
immutable historical evidence - those remain exactly as ADR 0035 already
established. It does not authorize a schema migration; if the implementer
finds one is genuinely unavoidable (e.g., to make a rubric/KPI name column
nullable), it must be purely additive/backward-compatible and reported, not
silently assumed. It does not retroactively change the framework/version
bound to any already-completed Assessment. It does not resolve the
KPI-naming-collision question above - that is an explicit, separate,
flagged follow-up decision point, not something this ADR silently decides
either way.

# Status

ACCEPTED as of 2026-09-12, per direct Owner instruction in this conversation
(a detailed 20-section implementation brief). This ADR exists so
implementation has a durable, citable authorization artifact for the two
real policy changes it makes (Grade is no longer an eligibility gate;
"Assessment Criteria" is relabeled "KPI" in the primary user-facing
hierarchy) rather than relying on an unverifiable in-task claim of approval.
Every other item in the Owner's brief (navigation, Ghars icon, UI density,
selector placement) is UI/IA work that does not itself require new
governance and is not restated here.
