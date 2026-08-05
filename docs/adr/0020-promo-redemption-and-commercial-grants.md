---
title: Promo Redemption And Commercial Grants
documentation_version: 3.1
last_updated: 2026-08-05
status: Accepted
---

# ADR 0020: Promo Redemption And Commercial Grants

## Context

M2 created secure promo definitions but deliberately granted no customer
access. M3 needs to activate either a newly onboarded organization or a
separately aligned existing tenant without fabricating payment, subscription,
demo, or onboarding evidence. Promo capacity must participate in M1 while
remaining distinct from Paddle-paid authority.

## Decision

Completed activation creates immutable `PromoRedemption` and `PromoGrant`
records. The grant snapshots tier, exact branch/system-user/teacher limits,
scope, and effective window. A promo `WorkspaceEntitlement`, explicit branch
assignments/entitlements, and `TenantProvisioningLink.promo_grant_id` make the
grant operationally attributable. `TenantProvisioningLink` requires exactly
one source: paid contract, approved demo request, or promo grant; its pending
organization reference is optional for already aligned tenants.

Only a verified tenant owner may activate. The final transaction locks the
activation session, promo definition, and target workspace, then revalidates
all scope, lifecycle, redemption, source, capacity, and branch-selection
invariants before one commit. Pending sessions grant no access. M1 and branch
authorization resolve only an effective active grant and coherent entitlement
chain.

Branch selection is explicit and reversible without changing branch status or
deleting data. Organization-wide system-user and teacher counts are validation
inputs only; overage blocks activation and never modifies people or roles.
Active internal sandboxes cannot be converted by this workflow. Paddle and all
payment records remain outside promo activation.

## Consequences

- Existing aligned organizations require a controlled prior classification and
  owner-link operation but no fake `PendingOrganization`.
- Raw promo code material remains absent from persistence, logs, and audit.
- Expired, missing, ambiguous, cross-tenant, or conflicting authority fails
  closed.
- Unused branch capacity may cover future normal branch creation, but staff and
  teacher capacity is never auto-reconciled.
- Promo renewal, transfer, paid conversion, communication, and automated expiry
  jobs remain deferred.
