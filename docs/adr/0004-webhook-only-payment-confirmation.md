---
adr: 0004
title: Webhook-Only Payment Confirmation
status: Accepted
date: 2026-06-26
---

# ADR 0004: Webhook-Only Payment Confirmation

Status: Accepted

Date: 2026-06-26

## Context

Checkout return pages can be reached by browser redirects, refreshes, or user navigation. They should not be treated as authoritative proof that payment succeeded.

## Decision

Treat provider webhook confirmation as the authoritative source for successful payment state. Checkout return pages may inform the user but should not independently confirm payment or trigger provisioning as if payment is verified.

## Alternatives Considered

- Confirm payment based on checkout return route.
- Allow manual UI confirmation from the SaaS account page.
- Provision tenant records immediately after checkout redirect.

## Consequences

Positive:

- Reduces risk of false-positive payment confirmation.
- Aligns billing state with provider-confirmed events.
- Supports delayed provisioning after verified payment.

Tradeoffs:

- Users may need clear pending-payment status while webhook processing completes.
- Webhook handling must be reliable and observable.

## Related Docs / Files

- `saas/paddle_client.py`
- `saas/payment_service.py`
- `saas/billing_service.py`
- `saas/router.py`
- `docs/TIS_MASTER_CONTEXT.md`
