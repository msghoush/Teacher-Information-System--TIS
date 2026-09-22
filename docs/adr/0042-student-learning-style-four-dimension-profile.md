---
title: Student Learning Style Four-Dimension Profile (Schema Foundation)
documentation_version: 1.0
last_updated: 2026-09-22
status: Accepted
amends: "ADR 0031 Decision > Domain and scope: 'V1 supports exactly one primary Learning Style per Student (single-select). Multi-style support is explicitly out of scope for V1 and is not to be scaffolded speculatively.' (original wording preserved unmodified in ADR 0031, with this amendment note added alongside it - the single-select categorical field itself is unchanged and is not superseded)."
---

# ADR 0042: Student Learning Style Four-Dimension Profile (Schema Foundation)

## Context

ADR 0031 governs and M1 milestone work ("Student Learning Style V1 - Core
Implementation Landed", `docs/PROJECT_STATE.md`) implemented exactly one
optional, single-select, four-value categorical `Student.learning_style`
field (`Visual`/`Auditory`/`Read/Write`/`Kinesthetic`). That decision
explicitly scoped V1 to single-select only and stated multi-style support
"is not to be scaffolded speculatively."

The Owner has now directed a distinct, additional Learning Style data
contract for the Students + Talent & Potential product line: four
independent Student profile percentages - Verbal, Non-verbal, Quantitative,
and Spatial. This is not the categorical multi-select ADR 0031 declined to
scaffold; it is a separate numeric profile representation that coexists with,
and does not replace, the existing categorical field. This ADR is the
governed decision authorizing that coexistence and amending ADR 0031's
"Domain and scope" only to the extent needed to make clear that this later,
separately governed four-percentage profile is not the deferred multi-style
scaffolding ADR 0031 declined - it does not retroactively alter ADR 0031's
historical record of what V1 shipped, and the original categorical field,
its four fixed values, and its single-select nature are unchanged and remain
in effect.

## Decision

### Domain, scope, and independence from the legacy categorical field

Learning Style four-dimension profile belongs to the **Student** domain,
exactly like the legacy categorical field it sits alongside.

- Four independent, optional (nullable) integer Student attributes:
  `learning_style_verbal_percentage`, `learning_style_non_verbal_percentage`,
  `learning_style_quantitative_percentage`, `learning_style_spatial_percentage`.
- Each is validated independently against the range 0-100 inclusive (or
  NULL). There is no sum-to-100 rule and no rule relating the four values to
  each other.
- The legacy categorical `learning_style` column (`Visual`/`Auditory`/
  `Read/Write`/`Kinesthetic`) is explicitly preserved as legacy/deprecated
  data. It is not deleted, rewritten, mapped, or cleared, and no automatic
  conversion between the categorical value and the four percentages exists
  or is authorized.
- No Learning Style history table, profile-version table, Talent snapshot,
  or Talent scoring linkage is introduced. There is no historical Learning
  Style versioning of either the legacy field or the new percentages.

### No effect on Talent semantics

Exactly like the legacy categorical field under ADR 0031, the four-dimension
profile has zero effect on, and must never be read by, any Talent-domain
scoring, Program Criteria / Review Candidate eligibility computation, or
Official Identification decision logic. It may be displayed as
informational learner context only.

### Governance boundary and milestone scope

This ADR authorizes the four-dimension persistence/schema foundation
described above. Consistent with the Students + Talent & Potential M1
milestone, this ADR does not itself authorize or claim: a create/update
API contract for the four percentages, any frontend surface, Evaluation
Progress, roster import/export, or any Talent frontend change. Those remain
separately governed, later implementation work. Al-Andalus Section display
was also out of this ADR's scope at M1; it is now owner-authorized
(presentation-only, for the exact verified `workspace_uuid`
`72e52eb2-3844-447b-92a8-c55015f73257`, canonical identity unchanged,
implementation not yet complete) under ADR 0045, which is the governing
authorization record for that feature - this ADR's scope remains the
Learning Style four-dimension profile only. This ADR also does
not authorize multi-select of the legacy categorical values, which remains
governed exactly as ADR 0031 recorded it.

## Status

ACCEPTED as of 2026-09-22. Implementation status (schema/migration only, as
of this ADR) is tracked in `docs/PROJECT_STATE.md`; this ADR is the
governance/authorization record, not a completion record for any API,
service, or frontend surface.
