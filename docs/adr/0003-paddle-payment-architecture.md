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
- `saas/router.py`
- `docs/TIS_MASTER_CONTEXT.md`
