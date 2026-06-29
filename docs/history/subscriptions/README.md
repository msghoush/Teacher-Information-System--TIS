---
title: Subscription History
module: subscriptions
last_updated: 2026-06-30
---

# Subscription History

This folder tracks meaningful changes to TIS subscription plans, pricing, billing status, payment behavior, checkout assumptions, and provider boundaries.

Related docs:

- `docs/adr/0003-paddle-payment-architecture.md`
- `docs/adr/0004-webhook-only-payment-confirmation.md`
- `docs/TIS_MASTER_CONTEXT.md`

## 2026-06-30 - Paddle Initial Checkout Price Mapping Configuration

Initial Paddle checkout now has a script-based configuration path for mapping TIS subscription plan prices to Paddle provider price IDs. The runtime source of truth remains `subscription_plan_prices.provider_price_id`; Paddle credentials and endpoints remain environment variables.

Added configuration support:

- `scripts/sync_paddle_price_ids.py`
- `config/paddle/paddle_prices.sandbox.example.json`
- `config/paddle/paddle_prices.production.example.json`

The sync script validates the six required plan/interval mappings: Starter monthly, Starter annual, Professional monthly, Professional annual, Enterprise AI monthly, and Enterprise AI annual. Real local, sandbox, and production mapping files are ignored by Git so sandbox and live Paddle price IDs remain separated.

If a selected plan price still lacks a Paddle provider price ID, checkout remains fail-closed before calling Paddle. Customers see a support-oriented Secure Payment message while internal diagnostics retain plan code, billing interval, and currency context.
