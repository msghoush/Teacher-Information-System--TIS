---
title: Subscription History
module: subscriptions
last_updated: 2026-08-04
---

# Subscription History

## 2026-08-04 - Unified Operational Commercial Capacity Authority

One facade now resolves commercial access, capacity source, confirmed plan and
quantity, current branch/staff/teacher usage, remaining capacity, violations,
minimum eligible plan or Custom, and safe recovery. It composes the existing
M7/M8 authorities and fails closed on missing, ambiguous, or contradictory
relationships. Demo and Internal Sandbox are explicitly unmetered in M1.

Staff capacity now correctly counts every distinct active tenant operational
User in the workspace regardless of role, title, position, or internal-test
attribution. An operational owner counts. A teacher-position User counts as
staff, and an associated active Teacher record separately counts as a teacher.
Platform users, inactive users, other tenants, and account-only SaaS identities
do not count. Known teacher IDs deduplicate across branches and academic data;
blank legacy identities never merge.

Capacity-increasing writes lock the SchoolGroup and perform permission/scope
validation, authority resolution, recount, proposed-final-state evaluation,
mutation, and commit as one transaction. This covers branch creation and
reactivation, bulk branch status changes, user growth/reactivation, teacher
creation/year-copy, academic-year activation, and paid/demo provisioning final
validation. Existing over-capacity tenants preserve records and access but may
not further increase an exceeded dimension.

## 2026-07-29 - Per-Branch System-User And Teacher Capacity

Plan eligibility combines persisted `max_branches`, `max_system_users`, and
`max_teachers`. Starter supports 1/5/25, Professional 5/20/100, and Enterprise
AI 25/100/500. Required non-negative estimates are stored per onboarding branch
and summed organization-wide. Legacy organization totals are assigned to the
primary branch when no branch estimates exist.

Before payment, system-user and teacher authority separately uses the greater
of estimated and actual same-workspace counts; paid operations use actual
counts. This milestone originally excluded teacher-position and internal-test
login records from system-user usage. M1 supersedes that operational rule:
every active tenant operational User now consumes staff capacity, while active
Teacher records separately consume teacher capacity. Inactive, platform,
account-only, other-tenant, inactive-branch, and inactive-year data remains
excluded as applicable.

The lowest eligible plan is recommended. The shared decision protects
selection through payment reconciliation and includes both people counts in
quote fingerprints. Estimate changes clear only an undersized plan and
supersede stale checkout lineage. Paid system-user and teacher growth plus
downgrades fail before mutation when capacity would be exceeded. The
always-visible Custom card never creates Paddle checkout and is emphasized
above any Enterprise AI maximum.

The current Teacher model has no inactive/reactivation state and no teacher
import endpoint exists. Current post-activation enforcement covers individual
teacher creation and preflights academic-year copying atomically; future import
or reactivation workflows must adopt the same capacity boundary.

## 2026-07-28 - Authoritative Plan Branch-Capacity Enforcement

Initial self-service selection now enforces the persisted plan limits: Starter
one active billable branch, Professional five, and Enterprise AI twenty-five.
All higher plans remain eligible below their capacity, while organizations
above twenty-five receive the custom-plan contact path. Actual active branches
still determine the per-branch total.

The same fail-closed capacity decision protects selection, quote generation,
checkout preparation and launch, and payment validation. If branch editing
makes the selected plan undersized before payment, its selection and checkout
lineage are superseded; an eligible higher plan remains selected. Tenant-scoped
branch counting prevents another organization from affecting eligibility.

## 2026-07-28 - Pre-Payment Branch Editing And Quote Supersession

Onboarding branches remain editable until confirmed payment. The existence of
an unpaid demo SchoolGroup, tenant link, Paddle customer, checkout session, or
billed-but-unpaid attempt is not paid provisioning evidence. Once payment is
confirmed, branch changes move to Subscription Management.

Pre-payment branch changes invalidate the old quote and checkout lineage,
supersede incomplete attempts, and force a new immutable transaction using the
new active branch count. Late events for the old transaction cannot activate,
convert, or reprovision the workspace.

## 2026-07-28 - Authoritative Fixed Branch Quantity In Paddle Checkout

Initial checkout now keeps the TIS-calculated billable branch quantity fixed
through payment. The server creates an automatically collected Paddle
transaction with customer, address, catalog price, and exact quantity; verifies
its item, subtotal, and quote-fingerprint evidence; then marks the ready
transaction billed before releasing its transaction ID to Paddle.js.

Quantities of one, two, or more remain data-driven. Branch changes continue
only through TIS branch and subscription-quantity workflows. No shared catalog
price is mutated and no quantity-specific price is created. Automatic payment
completion remains the recurring-subscription, webhook, and conversion
authority.

The public launcher accepts only the unique locally attributable transaction
after Paddle confirms `billed` and automatic collection. It rejects draft,
ready, canceled, past-due, unrelated, and mismatched transactions, while retry
clicks reuse the existing started checkout rather than creating another
transaction.

## 2026-07-28 - Expired-Demo Checkout Identity Repair

Paddle sandbox recovery now recognizes the existing active tenant owner as
authoritative when the authenticated account, owned organization, demo source,
tenant link, SchoolGroup, operational user, and email resolve uniquely. A stale
account-user link from a deleted or inactive account is safely reassigned to
that account/workspace relationship. Unrelated tenants, active former accounts,
multiple identities, and live email-only recovery remain blocked. Failed
checkout preparation exposes no internal diagnostics and shows a retry state;
the same workspace UUID, SchoolGroup, and branches remain unchanged.

## 2026-07-28 - Expired Demo Subscription Continuity

Expired demo subscription selection now reads the preserved SchoolGroup and its
active operational branches, presents real public plans and billing intervals,
and continues through existing Paddle checkout. Confirmed payment still converts
the same workspace; missing configuration produces safe support guidance rather
than unavailable placeholders.

## 2026-07-20 - M7 Phase 5 Lifecycle Policy, Cancellation, And Reversal

The Subscription Management portal now resolves customer-visible state and allowed actions through `saas.subscription_lifecycle_service`. Upgrade, downgrade, branch increase/reduction, cancellation, and cancellation reversal controls are exposed only when authorization, provider subscription state, pending requests, effective dates, and local relationships permit them.

Authorized billing administrators can schedule cancellation at period end and reverse it before the effective boundary. Current paid access remains active until authoritative provider evidence confirms the end of the paid period. Provider conflicts, unknown outcomes, and local/provider mismatches fail closed to manual review.

## 2026-07-18 - M7 Payment Lifecycle And Reconciliation Protections

Initial checkout and post-activation subscription-change transactions are resolved as distinct payment lifecycles. Webhook processing remains signature-verified and idempotent, validates attributable provider subscription/transaction evidence, and prevents change transactions from replaying initial provisioning transitions.

Diagnostics and the sandbox-guarded finalized-lifecycle reconciliation script expose sanitized evidence and default to dry-run behavior. Reconciliation applies only when stored completed webhook evidence and authoritative Paddle transaction data agree; unexpected or ambiguous state is blocked rather than guessed.

## 2026-07-17 - M7 Phase 4 Plan Upgrades And Scheduled Downgrades

Authorized billing administrators can preview and submit plan transitions from `/saas/subscription`. Paddle supplies monetary previews and proration outcomes. Upgrades use immediate provider proration with payment-failure prevention and do not become local entitlement truth before verified completion. Downgrades are scheduled for the next billing period and preserve the current plan until provider/webhook confirmation at the effective boundary.

Customers can cancel or replace an eligible scheduled plan change before it becomes effective. TIS sends complete retained recurring items and enters manual review on provider/local ambiguity.

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
