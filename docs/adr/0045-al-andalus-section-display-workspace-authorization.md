---
title: Al-Andalus Section Display - Workspace Authorization (Governance Only)
documentation_version: 1.0
last_updated: 2026-09-22
status: Accepted
---

# ADR 0045: Al-Andalus Section Display - Workspace Authorization (Governance Only)

## Context

`docs/PROJECT_STATE.md` (Students + Talent & Potential M1 milestone summary)
and ADR 0042's governance-boundary note both listed "Al-Andalus Section
display" among items explicitly deferred to later, separately governed
implementation work. No prior ADR or KMS document recorded an authorized
`SchoolGroup.workspace_uuid` for that later work, and no prior ADR
authorized the presentation convention itself.

The Owner has now directed and authorized this bounded, presentation-only
feature and has identified the exact production `SchoolGroup.workspace_uuid`
it applies to, using the repository's existing read-only production audit
(`scripts/audit_al_andalus_readonly.py`) run against the deployed Render
PostgreSQL environment. This ADR is the governance record closing that
deferred status and authorizing implementation for the exact identified
workspace. It is a governance/authorization record only; it does not itself
implement the feature (tracked separately in `docs/PROJECT_STATE.md`).

## Decision

### Authorized workspace identity

The authorized `SchoolGroup.workspace_uuid` for this feature is exactly:

`72e52eb2-3844-447b-92a8-c55015f73257`

Verification provenance: the Owner personally ran the repository's existing
read-only production audit script against the deployed Render production
environment and confirmed this `workspace_uuid` (`exact_name` "Al-Andalus",
`school_group_id` 1 at time of audit, no duplicate-organization conflict,
audit process exit code 0). No credentials, connection strings, or other
production audit detail are recorded here or elsewhere in KMS.

Runtime activation for this feature must key exclusively off this exact
`workspace_uuid` value. Activation must never be derived from
`SchoolGroup.name`, organization display name, domain, email, Branch name,
or any other editable/human-readable label - none of those are stable
tenant identity and none may substitute for the UUID.

### Authorized presentation convention

For the identified workspace only, Grade/Section display formatting may
render as `{grade_number}.{section_ordinal}` (for example Grade 1/Section A
-> `1.1`, Grade 1/Section B -> `1.2`, Grade 2/Section A -> `2.1`), with
Section ordinal derived deterministically from an alphabetic Section name
(A=1, B=2, ... Z=26). Any Grade or Section value that does not
deterministically map under this rule (custom Section name, non-alphabetic
Section, malformed or missing Grade, missing Section) must fall back to the
existing/default canonical presentation unchanged - never an invented
number, and never a hard failure caused solely by unavailable formatting.
Every other workspace continues to use the existing/default presentation
unchanged.

### Presentation-only; canonical identity unaffected

This is a display-label transformation only. It must never replace, and
implementation must never allow it to replace:

- `PlanningSection.id` or any other canonical PlanningSection identity,
- canonical `grade_level` or `section_name` values,
- Student Academic Placement foreign keys,
- frozen historical Talent Grade/Section attribution,
- analytics grouping, query/filter identity, tenant/authorization scope, or
  import/export matching identity.

A rendered value such as `1.1` may appear only as a display field (for
example a bounded `section_display`-style projection alongside the
unchanged canonical value); it must never become a stored identity, a
request/filter parameter, or an import/export match key. No schema or
migration is authorized or required by this ADR.

## Status

### Governance boundary

This ADR authorizes only: (1) the exact workspace identity above, and (2)
the presentation convention and its constraints. It does NOT itself
authorize or claim that a shared presentation helper, API/UI surface
changes, or tests have been implemented - that implementation is separately
governed, later work and is tracked (not-yet-complete as of this ADR) in
`docs/PROJECT_STATE.md`.

ACCEPTED as of 2026-09-22. This ADR is the authorization record for the
workspace identity and presentation convention; it is not a completion
record for any implementation.
