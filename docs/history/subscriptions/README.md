---
title: Subscription History
module: subscriptions
last_updated: 2026-07-20
---

# Subscription History

## 2026-07-20 - M7 Phase 6 Billing History and Invoice Management

The customer Subscription Management page now retrieves billing history directly from Paddle's paginated `GET /transactions` API, scoped to the customer's confirmed provider subscription. TIS displays provider transaction totals, statuses, origins, invoice numbers, and returned credit/refund adjustments without creating local financial records or calculating replacement amounts.

Eligible invoice downloads use Paddle's `GET /transactions/{transaction_id}/invoice` API. TIS reauthorizes the current billing user, resolves the invoice against the confirmed customer subscription, and requests a fresh expiring provider URL at download time. The provider URL is not stored locally. No billing-history cache, schema change, migration, or webhook behavior is introduced; temporary provider failures render customer-safe retry states.

## 2026-07-16 - M7 Phase 3 Active Branch Quantity Management

Authorized organization billing administrators can now preview and submit paid branch-quantity changes from `/saas/subscription`. Paddle remains the sole source of financial calculations: TIS sends the complete retained subscription item list to Paddle's subscription-update preview endpoint and stores only customer-safe charge, credit, net, recurring-total, and effective-date summaries.

Increases use `prorated_immediately` with `on_payment_failure=prevent_change`. Local paid capacity does not increase until verified `subscription.updated` and successful `transaction.completed` evidence confirms the requested quantity and subscription-update payment. Reductions use `prorated_next_billing_period`, issue no immediate refund, and remain locally scheduled until a renewal-boundary subscription webhook confirms the reduced quantity. Reductions below active operational branch usage are rejected, and scheduled reductions can be restored before their effective date.

`PaymentSubscription.quantity` remains the only entitlement-capacity authority. Branch creation and individual or bulk reactivation now fail closed for provisioned SaaS tenants when confirmed paid capacity is exhausted. Provider mismatches, unsupported state, stale previews, or ambiguous ownership enter a customer-safe blocked/manual-review path without exposing provider diagnostics.

This folder tracks meaningful changes to TIS subscription plans, pricing, billing status, payment behavior, checkout assumptions, and provider boundaries.

Related docs:

- `docs/adr/0003-paddle-payment-architecture.md`
- `docs/adr/0004-webhook-only-payment-confirmation.md`
- `docs/TIS_MASTER_CONTEXT.md`

## 2026-07-11 - Paddle Transaction Payment Launcher

Paddle transaction checkout now uses a dedicated public SaaS payment launcher page at `/saas/payment` instead of the app root or operational login page. Server-side checkout still creates Paddle transactions through the existing payment service and still redirects to Paddle's returned `transaction.checkout.url`; `PADDLE_CHECKOUT_BASE_URL` should point to `https://app.tisplatform.com/saas/payment` so Paddle appends `_ptxn` to the launcher page.

The launcher page loads Paddle.js from the official Paddle CDN, initializes Paddle with the public `PADDLE_CLIENT_TOKEN`, uses `PADDLE_ENVIRONMENT` for sandbox/live mode, reads `_ptxn`, and opens checkout for the transaction. It does not require SaaS or operational login, does not expose `PADDLE_API_KEY`, and does not change webhook-confirmed payment state, subscription activation, provisioning, pricing, or billing transitions.

## 2026-06-30 - Paddle Initial Checkout Price Mapping Configuration

Initial Paddle checkout now has a script-based configuration path for mapping TIS subscription plan prices to Paddle provider price IDs. The runtime source of truth remains `subscription_plan_prices.provider_price_id`; Paddle credentials and endpoints remain environment variables.

Added configuration support:

- `scripts/sync_paddle_price_ids.py`
- `config/paddle/paddle_prices.sandbox.example.json`
- `config/paddle/paddle_prices.production.example.json`

The sync script validates the six required plan/interval mappings: Starter monthly, Starter annual, Professional monthly, Professional annual, Enterprise AI monthly, and Enterprise AI annual. Real local, sandbox, and production mapping files are ignored by Git so sandbox and live Paddle price IDs remain separated.

If a selected plan price still lacks a Paddle provider price ID, checkout remains fail-closed before calling Paddle. Customers see a support-oriented Secure Payment message while internal diagnostics retain plan code, billing interval, and currency context.
