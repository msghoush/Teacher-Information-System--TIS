---
title: Student Learning Style Four-Dimension Profile (Schema Foundation)
documentation_version: 1.2
last_updated: 2026-09-23
status: "Superseded (M14, 2026-09-23) - see 'M14 Correction' section at the end of this document. Original text below preserved unmodified as historical record."
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

**SUPERSEDED as of M14 (2026-09-23) - see "M14 Correction" section below.**
The text above is preserved unmodified as the historical record of what was
actually decided and, subsequently (M2/M3, beyond this ADR's own original
schema-only scope), actually implemented.

## M14 Correction (2026-09-23): This ADR's Product Model Is Corrected/Superseded

Added 2026-09-23, per direct Owner instruction following a read-only
Post-M13 Correction Review. This section does not delete or rewrite any text
above; it records that the decision above was a misinterpretation and states
the corrected model. See ADR 0031's own M14 Amendment section for the full
paired governance record (this is the ADR 0042 half of that same
correction).

### What actually happened after this ADR (verified against code, not assumed)

Contrary to this ADR's own "Governance boundary" section above (which
states this ADR authorizes schema/migration only, and explicitly does NOT
authorize "a create/update API contract for the four percentages" or "any
frontend surface"), the subsequent M2/M3 delivery went further than this
ADR itself authorized: `student_academic_service.py` implemented a full
create/update/GET API for the four percentages
(`LEARNING_STYLE_PERCENTAGE_FIELDS`, `_clean_learning_style_percentage`),
and a real Student create/edit frontend collected and displayed them
(`templates/student_form.html`, `templates/student_profile.html`,
`templates/_learning_style.html`'s `learning_style_percentage_fields`/
`learning_style_profile` macros) - while the ORIGINAL single-select
categorical field from ADR 0031 never received any create/edit frontend
selector at all. This is noted here as a verified implementation-history
fact, not a new authorization for it.

### The correction

"Percentage" here was always intended to mean POPULATION/AGGREGATE
distribution - what share of an authorized Student population selected each
Learning Style category - never an independent per-Student dimension score.
The four-dimension percentage profile this ADR introduced is therefore a
corrected/superseded product model, not a valid alternate representation
alongside the categorical field:

- Verbal, Non-verbal, Quantitative, and Spatial become four MORE values on
  ADR 0031's single categorical `learning_style` field (eight total), not an
  independent numeric profile.
- The four `learning_style_*_percentage` columns this ADR authorized are
  OPERATIONALLY DEPRECATED as of M14: no longer written, exposed in
  Student create/edit, displayed on the Student profile, or read as
  Learning Style authority anywhere, including in Talent Student context.
- Existing stored percentage values are preserved completely untouched - no
  backfill, no conversion, no clearing, no inference of a categorical value
  from a percentage or vice versa. Physical column removal is a separately
  gated, later cleanup contingent on an explicit data-occupancy verification
  that M14 could not safely perform (the local development database has no
  `students` table at all, so M14 could not inspect real occupancy either
  way).
- Aggregate (population) Learning Style percentages are computed by
  `student_learning_style_analytics.py`, extended to all eight categorical
  values plus "Unassigned," reusing the same privacy/suppression contract
  ADR 0031 already required.

This correction does not reauthorize anything this ADR's own "Governance
boundary" section already declined (e.g. it does not retroactively bless
the M2/M3 frontend/API overreach noted above); it corrects the underlying
product model going forward.

## M18a Amendment (2026-09-23): Read-Exposure Deprecation Completed

Added 2026-09-23. M18a independently re-verified the M14 amendment's "no
longer ... exposed" claim above against the actual implementation and found
it was not yet fully true: `routers/students.py`'s `_student_json` and
`routers/students_ui.py`'s `_student_view` still serialized all four
`learning_style_*_percentage` fields in the current normal Student API/UI
projection (including as literal `null` when unset). M18a removed them from
both projections, completing the M14 read-exposure deprecation exactly as
originally intended. Stored columns and any historical values remain
completely untouched (same as M14); physical column removal remains a
separately gated, later decision, unchanged by this amendment.
