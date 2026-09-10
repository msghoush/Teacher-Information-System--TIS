---
title: Draft Talent Program Hard Delete (Scoped Exception)
documentation_version: 1.0
last_updated: 2026-09-10
status: accepted
module: architecture
---

# ADR 0032: Draft Talent Program Hard Delete (Scoped Exception)

## Context

`docs/PROJECT_STATE.md` ("Talent Program Setup Wizard Owner Correction"
section) and `.kms-impact.yml` both record, as of the same day this ADR is
written, an explicit architectural decision: "Programs remain governed by
activate/retire rather than hard delete, and terminal assessments and
historical framework versions remain immutable." That statement is accurate
and remains the governing rule for every Program that has entered the
Talent lifecycle in any meaningful way.

A separate corrective-reconstruction task subsequently asked for a hard
`DELETE` endpoint for Programs. A prior investigation pass correctly
identified that an unscoped reading of that request would contradict the
recorded activate/retire invariant, and declined to implement it without
direct confirmation, since no agent-relayed claim of prior approval is
sufficient authorization to reverse a same-day documented governance
decision. The Owner has now directly confirmed, in this conversation, a
narrower request: a Program may be hard-deleted only while it is still in
`draft` status and has zero rows in every table a real Program actually
has a direct or child relationship to (at minimum, re-verified against
`models.py` at implementation time: `TalentProgramFrameworkVersion`,
`TalentProgramAcademicYearConfiguration`, `TalentCompetency`,
`TalentAssessmentCycle`, `TalentEducatorInput` — the implementer must
re-confirm this list is exhaustive against the actual current schema, not
assume it).

A Program in this exact state has not yet entered the part of the Talent
lifecycle the activate/retire invariant exists to protect - no framework
history, no assessment history, no evaluation cycle, no educator input has
ever been attached to it. It is, in effect, still an in-progress creation
draft rather than a governed Program record.

## Decision

### Scoped exception, not a reversal

Talent Programs remain governed by activate/retire, not hard delete, for
every Program that is not in this exact zero-child draft state. This ADR
does not change that rule for Configured, Active, Retired, or otherwise
historical Programs. Terminal assessments and historical framework versions
remain immutable, unchanged by this ADR.

### The exception, exactly

A Program may be hard-deleted via `DELETE /api/talent/programs/{id}` if and
only if:

- `program.status == 'draft'`, AND
- zero rows exist in every table with a direct or child relationship to
  that Program (re-verified against the actual current schema at
  implementation time, not assumed from this list).

Any other status, or a draft Program with any child row in any such table,
must be rejected with a clear error - never a silent no-op, never a partial
delete.

### Authorization and audit

This action requires the new `talent_programs.delete` permission (grantable
through the existing role-permission system, no hard-coded role names) plus
the same existing organization-scope authorization check already used by
other Program mutation routes. The deletion must be recorded through the
existing `TalentConfigurationAudit` mechanism, the same audit path already
used elsewhere in `talent_program_service.py` - no new audit mechanism is
introduced.

### UI exposure

The "Delete Program" action must be exposed only when the backend already
says it is allowed (a real capability/action the API returns for that
Program), never a client-side guess based on status alone.

## Status

ACCEPTED as of 2026-09-10, per direct Owner instruction in this conversation,
confirming a narrower scope than the reconstruction task's original
unscoped hard-delete request. This ADR exists so that implementation has a
durable, citable authorization artifact - consistent with the same pattern
established in ADR 0031 - rather than relying on an unverifiable in-task
claim that this was "already approved" elsewhere. `docs/PROJECT_STATE.md`'s
and `.kms-impact.yml`'s activate/retire statements remain accurate for every
Program outside this narrow, explicitly-bounded exception and are not being
rewritten.
