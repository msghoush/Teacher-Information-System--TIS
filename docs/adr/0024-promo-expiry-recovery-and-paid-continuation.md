---
title: Promo Expiry Recovery And Paid Continuation
status: Accepted
date: 2026-08-18
---

# Context

Promo grants already provide a distinct non-Paddle commercial source with immutable
effective dates. The product needs an explicit meaning for grace days, source-correct
expired messaging, and a way for an expired promo customer to continue as paid without
recreating or losing the existing tenant.

# Decision

Normal operational access ends exactly at `PromoGrant.effective_to`.
`grace_period_days` defines only a commercial recovery interval. During and after that
interval, authorized owners may use Organization Account and preserved tenant data,
but normal operational routes remain blocked. Grace never changes the grant effective
window, restores branch access, or archives/deletes data.

Only recovery-period and expired promo authority is eligible for paid continuation.
Active-promo early conversion is blocked because promotional value is not paid credit
and TIS will not invent proration. The customer selects an eligible paid plan through
the existing-workspace activation aggregate. Quote preparation, checkout launch,
pending payment, failure, cancellation, expiry, and abandonment leave promo authority
unchanged and do not restore expired access.

A verified `transaction.completed` is the conversion boundary. Under the existing
SchoolGroup and activation locks, TIS revalidates tenant identity, quote, capacity,
provider evidence, the exact promo grant, the active promo workspace entitlement, and
the sole promo-sourced tenant link. One transaction then ends the promo entitlement,
marks the grant converted while retaining its history, relinks the existing tenant
link to the paid contract, creates paid workspace and branch entitlements, and resolves
paid authority before commit. A conflict rolls back the authority transition and
requires manual review. Duplicate provider confirmation is idempotent.

Commercial identity presentation is centralized in `commercial_badge_service`.
Prepared source/status/plan/icon tokens drive one reusable badge for Promo, Demo, and
Paid authority. Templates do not infer authority from historical rows. Compact mode is
available to authorized Organization Account presentation, and full mode is used on
the commercial page. The normal operational header does not render commercial
identity. Unresolved or source-free states do not claim a commercial badge.

# Consequences

- SchoolGroup, workspace UUID, branches, users, teachers, academic data, branding,
  ownership, and tenant data are preserved through conversion.
- Promo redemption/grant history remains immutable and attributable after conversion.
- There is never simultaneous active promo and paid tenant authority.
- Failed or abandoned checkout cannot create operational access.
- Promo, Demo, and Paid customer messaging and badges remain source-aware.
- Long-term data archival and active-promo conversion remain future decisions.
