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
