---
adr: 0003
title: Paddle Payment Architecture
status: Accepted
date: 2026-06-26
---

# ADR 0003: Paddle Payment Architecture

Status: Accepted

Date: 2026-06-26

## Context

TIS requires subscription payments and billing visibility while preserving a clean boundary between academic operations and payment provider behavior.

## Decision

Use Paddle behind service/client boundaries in the `saas/` package. Keep payment, pricing, billing, and currency logic separate from academic modules.

Active branch-quantity changes use `saas.subscription_change_service` and durable `SubscriptionChangeRequest` records. TIS requests Paddle previews and never calculates monetary proration. Immediate increases use `prorated_immediately` and prevent applying the provider change when payment fails. Reductions are billed for the next period without an automatic refund; TIS preserves current local capacity until the renewal boundary is webhook-confirmed. Every update sends Paddle the complete retained recurring item list.

Plan upgrades and downgrades use the same provider-authoritative principles through `saas.subscription_plan_change_service`. Upgrades are immediate only after provider-confirmed payment lifecycle evidence; downgrades are scheduled and preserve current entitlements until effective confirmation. Scheduled changes may be replaced or canceled only while Paddle and local request state agree.

Cancellation and reversal use `saas.subscription_cancellation_service`. Cancellation is scheduled at period end, does not revoke current paid access early, and may be reversed before the effective boundary after provider validation. `saas.subscription_lifecycle_service` centralizes displayed lifecycle state and allowed customer actions.

Billing history and invoices remain provider-owned. `saas.billing_history_service` reads subscription-scoped Paddle transactions and requests fresh expiring invoice URLs without persisting a duplicate financial ledger or provider URL.

Paddle does not support arbitrary client-supplied idempotency keys. TIS therefore serializes unresolved requests per subscription, uses deterministic local request keys, locks request/subscription rows during submission, and reconciles webhook retries by provider event and request state.

## Alternatives Considered

- Inline Paddle calls directly inside route handlers.
- Store provider-specific behavior across operational modules.
- Delay payment architecture until after provisioning.

## Consequences

Positive:

- Provider integration is isolated.
- Academic workflows stay independent of payment details.
- Billing status can be reasoned about separately from onboarding and provisioning.

Tradeoffs:

- Service boundaries must be maintained.
- Webhook/payment state must be carefully tested.

## Related Docs / Files

- `saas/paddle_client.py`
- `saas/payment_service.py`
- `saas/billing_service.py`
- `saas/pricing_service.py`
- `saas/currency_service.py`
- `saas/entitlement_service.py`
- `saas/subscription_portal_service.py`
- `saas/subscription_change_service.py`
- `saas/subscription_plan_change_service.py`
- `saas/subscription_cancellation_service.py`
- `saas/subscription_lifecycle_service.py`
- `saas/billing_history_service.py`
- `saas/router.py`
- `docs/TIS_MASTER_CONTEXT.md`
