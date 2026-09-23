---
title: Student Learning Style V1
documentation_version: 1.3
last_updated: 2026-09-23
status: accepted
module: architecture
amended_by: "ADR 0042 (2026-09-22, superseded/corrected by the M14 amendment below) added a separate, independent four-dimension Learning Style percentage profile (Verbal/Non-verbal/Quantitative/Spatial) alongside this ADR's single-select categorical field. M14 (2026-09-23, owner correction) determined that ADR 0042's premise was a misinterpretation - 'percentage' was always intended to mean population/aggregate distribution, never a per-Student dimension score - and corrected the model: Verbal, Non-verbal, Quantitative, and Spatial become four MORE single-select categorical values on THIS field (eight total), not an independent percentage profile. The original four values, this field's single-select nature, and its Student-domain/no-Talent-effect governance are unchanged and remain in effect; only the approved value count changes (four to eight) and ADR 0042's four-percentage product model is corrected/superseded (see ADR 0042's own amendment note)."
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
  - **Amended by ADR 0042** (2026-09-22, unmodified original text above):
    a later, separately governed decision adds an independent
    four-dimension Learning Style percentage profile (Verbal/Non-verbal/
    Quantitative/Spatial) alongside this single-select categorical field.
    That later profile is not a multi-select of the four categorical values
    above and is not the speculative scaffolding this bullet declined; this
    field, its four values, and its single-select nature remain exactly as
    decided here.
- V1 approved value set, exactly these four values, no others:
  - Visual
  - Auditory
  - Read/Write
  - Kinesthetic
  - **Amended by M14** (2026-09-23, unmodified original text above): the
    approved value set is extended to exactly eight values - the original
    four above plus Verbal, Non-verbal, Quantitative, and Spatial (see the
    "M14 Amendment" section at the end of this ADR for the full governance
    record). The field remains single-select; this is not multi-select of
    the four categorical values.
- Server-side validation must reject any value outside this set (now eight
  values as of the M14 amendment). The values are not free text and must not
  be stored as unconstrained free text.

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
`students.view_all_branches` permission is Administrator-only in the managed
role policy and is effective only with organization/global access scope. Without both conditions,
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

## M14 Amendment (2026-09-23): Eight Values, Aggregate-Only Percentage Semantics

Added 2026-09-23. The original text above (as of documentation_version 1.2)
is preserved unmodified; this section records the owner-directed correction
without rewriting the historical decision it amends.

### What was corrected

The M1-M13 delivery history built ADR 0042 as a SEPARATE, independent
four-dimension Student percentage profile (Verbal/Non-verbal/Quantitative/
Spatial), read/written through its own create/update/GET API surface and,
for the four percentages, a real Student create/edit frontend (see ADR 0042's
own M14 amendment note for the full implementation-history record). The
Owner has now directed, via a read-only Post-M13 Correction Review followed
by this M14 correction milestone, that this was a misinterpretation of intent
on two points:

1. Learning Style was always meant to be ONE categorical selection per
   Student - originally four values, now extended to eight (this ADR's
   field), never a set of independent per-Student percentage scores.
2. "Percentage," wherever Learning Style is concerned, was always meant to
   describe a POPULATION/AGGREGATE distribution (what share of an authorized
   Student population selected each category) - never a per-Student
   dimension percentage.

### Corrected model

- `Student.learning_style` (this ADR's field) now accepts exactly eight
  values: Visual, Auditory, Read/Write, Kinesthetic, Verbal, Non-verbal,
  Quantitative, Spatial. Still one nullable, single-select column - no
  second field, no arrays, no weighting, no dominant-style calculation, no
  automatic inference between any value and any other data.
- The four `learning_style_*_percentage` columns (ADR 0042) are
  OPERATIONALLY DEPRECATED: no longer written, exposed, or read as Learning
  Style authority anywhere in the product (Student create/edit, Student
  profile, or Talent Student context). Existing stored values are preserved
  completely untouched - no backfill, no conversion, no clearing - because
  the M14 milestone could not safely verify whether any production row is
  actually non-null before deciding this. Physical column removal is a
  separately gated, later cleanup contingent on that verification.
- Aggregate Learning Style distribution (Branch/Organization) is computed
  over this single categorical field for all eight values plus an
  "Unassigned" bucket, reusing the existing privacy/suppression contract
  this ADR already required (`student_learning_style_analytics.py`,
  extended, not parallel-built). The denominator is every authorized Student
  in the selected scope, including Unassigned Students.
- The M4/M10 Talent Evaluation Progress "Learning Style" Branch-comparison
  metric, which averaged the four now-deprecated percentage columns, is
  REMOVED as of M14 (see ADR 0044's own record for that surface) rather than
  silently continuing to report a semantically wrong number.

### Governance boundary (unchanged)

This amendment does not authorize multi-select, Learning Style influencing
any Talent scoring/eligibility/identification computation, a new or weakened
privacy rule, or any Branch-level override of the Student-domain ownership
model - the original Governance boundary section above continues to apply in
full, now scoped to eight values instead of four.
