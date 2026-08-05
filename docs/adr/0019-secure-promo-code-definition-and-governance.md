---
title: Secure Promo Code Definition And Governance
documentation_version: 3.1
last_updated: 2026-08-05
status: accepted
module: subscriptions
---

# ADR 0019: Secure Promo Code Definition And Governance

## Context

TIS needs owner-governed commercial promo definitions before customer-side
redemption or promo-based tenant grants can be introduced. Promo capacity must
reuse the existing Starter, Professional, and Enterprise AI plan ceilings,
while raw codes, lifecycle transitions, target restrictions, and historical
governance require dedicated security and audit boundaries.

## Decision

M2 adds definition-only `PromoCode`, `PromoCodeBranchRestriction`, and
`PromoCodeAuditEvent` records. Every promo selects one active public TIS tier
and exact positive branch, system-user, and teacher capacities that pass the
existing plan-capacity validator. Scope may be global, organization, pending
organization, account email, or email domain; reinforcing restrictions are
allowed only when coherent. Branch restrictions identify existing eligible
branches but grant no access.

Raw codes contain at least 100 bits of cryptographically secure randomness.
TIS normalizes them with Unicode NFKC, uppercase, and approved separator
removal, then persists only a deterministic HMAC-SHA256 lookup hash, key ID,
and safe display prefix/suffix. `TIS_PROMO_CODE_HMAC_SECRET` is dedicated and
mandatory when generation or lookup is invoked; there is no insecure fallback.
The raw value appears once in a `no-store` response and is never persisted,
logged, audited, or placed in a URL.

Persisted lifecycle states are Draft, Active, Paused, and Revoked; expiration
is derived from the redemption deadline. Active material edits require pause,
clear approval, increment definition version, and return to Draft. Platform
Developers with explicit `promo_codes.view` and `promo_codes.manage` may manage
non-terminal definitions, but only Platform Owners may activate or revoke.
Lifecycle mutations lock the promo row through validation, mutation, durable
audit insertion, and commit.

## Consequences

- Migration `20260805_001_promo_code_foundation` is additive, idempotent, and
  contains no data backfill.
- Platform Console owns list, create, one-time display, detail, edit, activate,
  pause, revoke, duplicate, and replacement-definition routes.
- Durable audit uses an allowlist and the application audit channel; neither
  contains raw codes, lookup hashes, key IDs, or secrets.
- M1 commercial authority, WorkspaceEntitlement, TenantProvisioningLink,
  onboarding, Paddle, payment, provisioning, and tenant capacity behavior do
  not recognize promo as a commercial source in M2.
- Promo redemption and immutable PromoGrant adaptation remain M3 work.
