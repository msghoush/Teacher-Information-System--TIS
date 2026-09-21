---
title: Promo Grant Replacement (Promo-to-Promo)
documentation_version: 1.0
last_updated: 2026-09-21
status: Accepted
amends: "ADR 0020 Consequences: the 'transfer' portion of 'Promo renewal, transfer, communication, automated expiry jobs, and active-promo early conversion remain deferred' (promo-to-promo case only; original wording preserved unmodified in ADR 0020, with an amendment note added alongside it)."
---

# ADR 0041: Promo Grant Replacement (Promo-to-Promo)

## Context

ADR 0020 explicitly deferred "promo renewal, transfer." An operational need
exists for a Platform operator to replace an organization's existing active
`PromoGrant` with a fresh grant against a different, currently valid
`PromoCode` — for example when a customer's original promo offer is retired
and a new, larger offer should take over the same organization's commercial
access. This is a promo-to-promo transition and is distinct from the
promo-to-paid conversion ADR 0024 already governs; ADR 0024's guardrails
(blocking early conversion of an *active* promo, recovery-period eligibility)
are specific to converting to a paid subscription and do not apply here,
since a replacement promo grant is not paid credit and does not require the
existing grant to first expire or enter recovery.

## Decision

A new Platform Console-only operation, "Replace / Extend Promotional
Access," atomically supersedes an organization's single active `PromoGrant`
with a new `PromoRedemption`/`PromoGrant` pair redeemed against a different
`PromoCode`, following the same transactional discipline ADR 0024 already
established for promo-to-paid conversion (end old evidence, create new
evidence, repoint the tenant link, all inside one transaction so there is
never a committed window with zero active commercial source).

The old `PromoGrant` transitions to `status = 'superseded'` (retained, never
deleted) and its paired `WorkspaceEntitlement` transitions to `status =
'ended'`. The new `PromoGrant.supersedes_grant_id` points at the old grant's
id — the new row records which grant it replaced, matching the existing
`PromoCode.supersedes_promo_code_id` convention where a newly created
replacement definition's `supersedes_promo_code_id` points at the id of the
definition it replaces (`promo_code_service.replace_promo`). The single
`TenantProvisioningLink.promo_grant_id` is repointed from the old grant to
the new grant in the same transaction; a new `WorkspaceEntitlement`
(`entitlement_type = 'promo'`, `status = 'active'`) is created against the
new grant with entitlement values (plan features, `quota.active_branches`)
derived from the new promo's plan, so commercial capacity/plan evidence
never points at stale numbers.

This operation changes capacity/limits only. It never creates, modifies, or
deletes a `Branch`, `User`/staff, or `Teacher` row; the organization's
existing operational branches, staff, and teachers are carried forward
unchanged. The branches already active under the old grant (via
`PromoGrantBranchAssignment`) are re-assigned to the new grant so the
existing `promo_grant_service.resolve_promo_grant` and
`commercial_authority_service.resolve_commercial_authority` capacity-display
paths resolve correctly against the new grant with no other change to how
capacity is computed or displayed.

Authorization reuses the existing platform-only `promo_codes.manage`
decision already enforced on every other Platform Console promo-code admin
route (`saas.router._require_promo_permission`), re-checked defensively at
the service layer (matching the existing `promo_code_service.revoke_promo`
precedent of a service-level authorization check). The replacement promo
must itself pass the same `_validate_promo_definition` gate every normal
customer redemption uses (active, approved, within its redemption window,
not itself superseded by a newer definition, scope/redemption-limit rules
satisfied) — this task does not introduce a second, weaker validation path.
A Platform Console confirmation step shows the old grant's limits and the
new promo's limits (branches/system users/teachers, plan, promo reference)
before the operator confirms.

## Consequences

- ADR 0020's "promo renewal, transfer" deferral is resolved for the
  promo-to-promo case only; promo renewal (extending the same promo's
  window) and communication/automated-expiry-job promo transfer remain
  deferred, unchanged.
- Exactly one active `PromoGrant` and one active `WorkspaceEntitlement` per
  organization is preserved throughout (enforced by the existing
  `uq_promo_grants_active_group` / `uq_workspace_entitlements_active_group`
  partial unique indexes); no schema or migration change was required.
- A failure at any point inside the transaction rolls back the entire
  operation; the old grant remains active and no partial state is
  committed, matching ADR 0024's existing rollback discipline.
- This operation is independent of ADR 0024's promo-to-paid conversion; the
  two are not conflated and do not share a code path, though both follow
  the same "end old evidence, create new evidence, repoint the tenant link,
  one transaction" shape.
- Idempotent retry of a replacement request (for example, a duplicate
  operator submission using the same `operation_key`) is not specially
  deduplicated the way `activate_promo`'s activation-session retry is; a
  retried replacement request re-validates against the now-current grant and
  will either succeed against the state left by the first attempt or fail
  closed if there is no longer an active grant to replace. This is recorded
  as a known limitation rather than solved by inventing a new idempotency
  mechanism.
