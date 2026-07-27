---
title: Centralized AI Entitlements And Usage Accounting
documentation_version: 3.1
last_updated: 2026-07-27
status: accepted
---

# ADR 0015: Centralized AI Entitlements And Usage Accounting

## Context

TIS has workspace classification, commercial-state resolution, normalized paid
plan entitlements, and role permissions, but no single authority for future AI
features or demo usage. Route-local feature names and counters would risk
cross-tenant leakage, inconsistent plan rules, and double consumption.

## Decision

`saas/ai_entitlement_service.py` is the sole AI entitlement and consumption
authority. Its decision order is tenant/workspace scope, underlying permission,
commercial state, registered AI policy, then successful-use consumption.
Commercial and demo-expiry denial remains authoritative before allowance.

`saas/ai_feature_registry.py` defines stable feature keys, display names,
permission and entitlement keys, eligible plan codes, demo allowance, and
enabled state. The temporary reviewed tier mapping grants registered AI
features to `enterprise_ai`; Starter and Professional receive upgrade guidance.
No price or AI business feature is introduced.

Each active Customer Demo receives two successful uses per registered feature.
Evaluation never consumes. Before provider execution, callers reserve an
operation key; locked successful-plus-reserved capacity prevents concurrent
attempts from exceeding the allowance. Completion converts the reservation to
a successful use only for a usable result, or marks it failed and releases the
capacity. Durable counters and operation events are unique by SchoolGroup,
feature, metric context, and operation key as applicable. Internal Sandbox,
demo, and paid metrics use separate contexts.

## Consequences

- Permissions, commercial access, and AI entitlement remain separate checks.
- Unknown, disabled, expired, restricted, non-entitled, and unauthorized cases
  fail closed with explicit reason codes.
- Demo exhaustion returns the approved message and Subscribe Now destination.
- Internal Sandbox is unlimited but separately measured.
- No failed/no-result operation consumes usage.
- Future M8B9 controls may inspect or extend the persisted model, but M8B8 adds
  no reset, override, expiry, reminder, or lifecycle-control interface.
- No executable AI feature currently exists, so no customer AI route is added.
