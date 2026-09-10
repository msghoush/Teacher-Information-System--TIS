---
title: Talent Student Assessment Delete (Zero-Evidence Exception)
documentation_version: 1.0
last_updated: 2026-09-11
status: accepted
module: architecture
---

# ADR 0034: Talent Student Assessment Delete (Zero-Evidence Exception)

## Context

A prior action-semantics audit this session confirmed no whole-`TalentStudentAssessment`
delete capability exists anywhere in the codebase - only `DELETE
.../competency-results/{id}` to clear a single in-progress competency result
(`talent_assessments.manage`, in-progress only). This means an accidentally
started Assessment with zero recorded competency results, zero Educator
Input, zero Review Candidate membership, and zero Official Identification
decision can never be removed - a genuine product gap, not a defect, since no
governed decision previously authorized a delete path for this entity. The
audit correctly declined to build one without explicit authorization,
consistent with this repository's established discipline (ADR 0031, ADR
0032, ADR 0033) of never adding a new destructive capability on inference
alone.

The Owner has now directly confirmed, in this conversation, that
Administrators need a Delete Assessment action, but strictly bounded to the
case where the Assessment is still safely disposable - i.e. has accumulated
no governed evidence or history.

## Decision

### The exception, exactly

`DELETE /api/talent/assessments/{assessment_id}` (or the equivalent service
function) is permitted if and only if the `TalentStudentAssessment` row has:

- zero `TalentStudentCompetencyResult` rows referencing it
  (`fk_talent_competency_results_assessment_scope`);
- no linked Educator Input record;
- no linked Review Candidate record;
- no linked Official Identification decision;
- no other protected dependent evidence/history discovered by re-inspecting
  the actual current schema at implementation time (the implementer must
  re-verify this list against `models.py`, not assume it is exhaustive from
  this ADR alone, mirroring the same re-verification discipline ADR 0032
  required for the Program delete blocker-table list).

Any Assessment with any such row must be rejected outright - never a silent
no-op, never a partial delete, never a cascade-delete of the dependent
evidence itself. Once any governed evidence/history exists, the Assessment
becomes permanent history exactly like every other terminal Talent record in
this system (completed assessments, historical framework versions, Official
Identification decisions).

### Authorization and audit

This action requires an Administrator-scoped permission (the implementer
determines the exact permission key, following the existing
`(key, description)` additive tuple pattern in `permission_registry.py` -
likely `talent_assessments.delete`, mirroring the `talent_programs.delete` /
`talent_evaluation_plans.delete_period` naming convention already
established by ADR 0032/related work) plus the existing organization/tenant
scope check already used by other Talent mutation routes. The backend must
re-check every dependency server-side at delete time, not trust a
client-supplied "this is safe" claim. If the existing
`TalentAssessmentAudit` architecture (its `resource_type` CHECK constraint
already includes `'student_assessment'`) supports recording a deletion
event, the implementer should append one; if the existing audit action
vocabulary does not yet have a delete-style action for this resource type,
the implementer should extend it additively (widening a CHECK constraint,
the same additive-only pattern already used twice for this exact table per
its own migration history) rather than skip audit recording.

### Explicit non-goals

This ADR does not authorize deleting a `TalentStudentAssessment` with any
evidence attached, under any role, for any reason. It does not authorize
deleting `TalentAssessmentCyclePopulationMember` rows, Student placement
history, or Cycle population records as a side effect of an Assessment
delete - those remain governed entirely by their own existing rules (ADR
0033 for Cycle/roster) and must be structurally untouched by this action.
It does not authorize any Student-level or Program-level delete capability
beyond what ADR 0032 already governs.

## Status

ACCEPTED as of 2026-09-11, per direct Owner instruction in this conversation.
Implementation (permission key, backend route/service function with
server-side dependency re-check, audit recording, and UI wiring following
the same backend-capability-gated pattern already used for Program/
Competency/Rubric-Level/Period delete) is tracked separately and is not
itself part of this governance record; this ADR exists so that
implementation has a durable, citable authorization artifact rather than
relying on an unverifiable in-task claim of approval.
