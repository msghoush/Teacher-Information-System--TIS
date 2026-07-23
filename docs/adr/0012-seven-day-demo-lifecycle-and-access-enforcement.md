---
title: Seven-Day Demo Lifecycle And Access Enforcement
documentation_version: 3.1
last_updated: 2026-07-23
status: accepted
---

# ADR 0012: Seven-Day Demo Lifecycle And Access Enforcement

## Context

M8B-4 activates customer-demo workspaces but intentionally defines no expiration. M8B-5 requires a standard seven-day lifecycle, a Day 6 reminder, data-preserving expiration, and enforcement that cannot be bypassed by a stale authenticated session or a delayed scheduler.

## Decision

Use `SaaSDemoWorkspaceProvisioning.activated_at` as the only demo clock authority. Persist derived reminder and expiration timestamps for querying, but require the lifecycle resolver to verify that they equal activation plus six and seven days. Perform calculations as timezone-aware UTC values and convert only display values to the onboarding organization's validated IANA timezone.

Use one read-only resolver for Active, Reminder Due, Expired, Suspended, and Manual Review. Scheduled processing is independently callable, dry-run by default, row-locked, idempotent, and failure-audited. Day 6 creates internal SaaS-account and Platform Owner notifications. Day 7 atomically ends the demo entitlement, suspends the SchoolGroup, marks the demo tenant link expired, and preserves all tenant data.

Enforce the same resolver in the existing operational authentication middleware. Customer-demo web requests that are expired or ambiguous are redirected to a subscription activation page; APIs and downloads receive a safe 403. Access-block audit is deduplicated. Platform identities, customer-paid workspaces, internal sandboxes, public/authentication routes, secure logout, and SaaS commercial routes bypass the demo-only gate.

## Consequences

- Scheduler delay cannot extend demo access because request-time resolution uses the authoritative timestamp.
- Existing sessions cannot bypass expiration.
- Expiration is reversible by a future approved commercial transition because no tenant data is deleted.
- Processing failure rolls back expiration changes and remains safely retryable.
- External email, conversion, extension, archive/delete, and read-only expired access remain out of scope.
