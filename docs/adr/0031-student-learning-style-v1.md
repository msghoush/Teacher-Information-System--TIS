---
title: Student Learning Style V1
documentation_version: 1.1
last_updated: 2026-09-10
status: accepted
module: architecture
---

# ADR 0031: Student Learning Style V1

## Context

`docs/TIS_MASTER_CONTEXT.md`, `docs/PROJECT_STATE.md`, `docs/AI_PROJECT_CONTEXT.md`,
`docs/engineering/PRODUCT_ROADMAP.md`, and `docs/CHANGE_HISTORY.md` have
repeatedly and consistently recorded, across the M7-M10 Talent & Potential
milestone history, that Learning Style has no authoritative data contract and
remains deferred/future-governed work (e.g. `TIS_MASTER_CONTEXT.md`: "No
profile table, current Talent status, cross-Framework score, audit read
event, M8 periods, or Learning Style exists."). Those statements are accurate
historical fact as of the milestones they describe and are not being
rewritten - Learning Style genuinely did not exist in the product before this
ADR.

The Owner has now directed, explicitly and directly, that Learning Style be
introduced as an optional Student-domain learner-profile attribute, V1 scope
only. This ADR is the governed decision that supersedes the prior deferred
status for V1 scope specifically. It does not retroactively alter the
historical record of what earlier milestones shipped.

## Decision

### Domain and scope

Learning Style belongs to the **Student** domain, not the Talent domain. It
is learner-profile context only.

- Optional (nullable) attribute on `Student`.
- V1 supports exactly one primary Learning Style per Student (single-select).
  Multi-style support is explicitly out of scope for V1 and is not to be
  scaffolded speculatively.
- V1 approved value set, exactly these four values, no others:
  - Visual
  - Auditory
  - Read/Write
  - Kinesthetic
- Server-side validation must reject any value outside this set. The four
  values are not free text and must not be stored as unconstrained free text.

### No effect on Talent semantics

Learning Style has zero effect on, and must never be read by:

- Rubric-level computation or any assessment scoring path.
- Program Criteria / Review Candidate eligibility computation.
- Official Identification decision logic.
- Any other deterministic Talent analytics computation.

It may be *displayed* alongside Talent/Student context as informational
learner context, but no Talent-domain scoring or eligibility code path may
depend on it.

### Permissions

Learning Style is edited using the existing `students.edit` permission
(`permission_registry.py`). No new permission is created for this feature.

### Analytics and privacy

Where Learning Style distribution is surfaced in aggregate (Branch or
Organization level), it must go through the same privacy/suppression
contract already governing Talent aggregate analytics (minimum cohort
suppression, complementary suppression, tenant isolation, fail-closed
behavior) - reusing existing enforcement infrastructure rather than a
separate, weaker rule invented for this field. A protected cohort's visual
treatment must not encode hidden magnitude through bar length, color
intensity, percentage, tooltip, or ordering.

### Student list branch scope and unavailable analytics presentation

Cross-Branch Student browsing is explicitly permissioned. The dedicated
`students.view_all_branches` permission is Administrator-default and is
effective only with organization/global access scope. Without both conditions,
the Students list is fixed to the actor's assigned authorized Branch and does
not offer an **All branches** choice.

The aggregate privacy contract remains fail closed. If the governed privacy
provider is unavailable or invalid, the Students page may explain that
Learning Style statistics are unavailable, but it must render **no aggregate
counts, percentages, category bars, or inferred magnitude**. A configured
policy that suppresses the selected cohort continues to show the existing
privacy-protected state instead of raw statistics. Individual Student Learning
Style values remain governed by normal Student-record permissions and are not
a substitute for aggregate analytics.

### Governance boundary

This ADR authorizes exactly the V1 scope above: one nullable single-select
Student field, four fixed values, existing-permission reuse, and
privacy-contract-compliant aggregate display. It does not authorize:
multi-style support, Learning Style influencing any Talent scoring/
eligibility/identification computation, a new or weakened privacy rule, or
any Branch-level override of the Student-domain ownership model.

## Status

ACCEPTED as of 2026-09-10, per direct Owner instruction. Implementation
(schema/migration, API validation, Student create/edit UX, Student profile
display, Talent-context display, Branch/Organization analytics
distribution, and focused tests) is tracked separately and is not itself
part of this governance record; this ADR exists so that implementation work
has a durable, citable authorization artifact rather than relying on
unverifiable in-task claims of authorization.
