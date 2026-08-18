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

The selectable set and entitlement inventory are distinct. Selection considers
eligible operationally active branches. Final activation inventories every
preserved workspace branch: selected branches receive one assignment and active
entitlement, while unselected branches receive an inactive entitlement without an
assignment or operational-status change. Branch reactivation uses the existing M1
SchoolGroup lock and capacity decision, then updates operational status, assignment,
and entitlement in the same transaction.

Legacy missing inactive evidence may be reconciled only when one active promo grant,
one promo tenant source, one owner, one matching workspace entitlement, and coherent
assignments are proven. The generic PostgreSQL CLI is dry-run by default and explicit
apply creates only missing inactive entitlements. It never changes branch status,
assignments, grant capacity, or people records; uncertainty remains manual review.

Customer commercial presentation follows the same source boundary. After
organization and billing permission validation, the subscription route resolves M1
authority first. Paid and demo sources keep their existing dedicated portals; promo
source uses a separate read-only view model. That adapter accepts M1 plan, status,
usage, limits, and remaining capacity and reads the attributable grant/redemption
only for effective dates and the masked reference. It must not query Paddle, expose
paid-only controls, or move commercial decisions into templates.

Operational grant access ends exactly at `PromoGrant.effective_to`.
`grace_period_days` is a recovery and paid-continuation window only and is never
added to the effective operational-access period. Request-time resolution derives
active, recovery, or expired state without mutating the immutable grant history or
tenant data.

## Consequences

- Existing aligned organizations require a controlled prior classification and
  owner-link operation but no fake `PendingOrganization`.
- Raw promo code material remains absent from persistence, logs, and audit.
- Expired, missing, ambiguous, cross-tenant, or conflicting authority fails
  closed.
- Unused branch capacity may cover future normal branch creation, but staff and
  teacher capacity is never auto-reconciled.
- Existing preserved branches always carry explicit active or inactive promo
  entitlement evidence.
- Promo renewal, transfer, communication, automated expiry jobs, and active-promo
  early conversion remain deferred.
- Expired and recovery-period promo authority may enter the separately governed,
  provider-authoritative existing-workspace paid continuation in ADR 0024.
