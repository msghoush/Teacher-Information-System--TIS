---
title: Existing Workspace Paid Activation Through Paddle
status: Accepted
date: 2026-08-06
---

# Context

M4B leaves a preserved existing tenant as classification `customer`, lifecycle
`provisioning`, and commercial state `activation_required`. Promo activation can
establish authority, but normal Paddle onboarding requires PendingOrganization and
tenant provisioning records that must not be fabricated for an existing workspace.

# Decision

TIS uses a dedicated `ExistingWorkspacePaidActivation` aggregate anchored directly
to SchoolGroup, workspace UUID, verified SaaS account, tenant-owner link, plan,
interval, branch selection, quote, checkout, payment attempt, contract, and provider
identity. Existing checkout/payment tables support either PendingOrganization or
this activation through strict XOR constraints. Billing profile and payment-customer
association can be anchored explicitly to SchoolGroup.
Each workspace association records the provider address and business selected for
that SchoolGroup. Account-wide mutable Paddle customer defaults are not sufficient
webhook authority when one SaaS account can own multiple workspaces.

Professional and Enterprise AI include every active operational branch and Paddle
quantity equals active branch count. Organization-wide staff and teacher counts
remain eligibility dimensions, not provider quantity. Starter remains unavailable
until restricted branch access is proven across all operational entry points.

Preparation grants no authority. The shared signature-verified Paddle webhook path
treats `transaction.paid` as processing only. A matching `transaction.completed`
locks the SchoolGroup and activation, revalidates all identity, quote, capacity,
branch, customer, business/address, price, quantity, currency, interval, transaction,
and subscription evidence, then atomically establishes paid commercial authority.
No tenant provisioning engine is called.

The successful workspace remains classification `customer`; paid versus promo is
represented by WorkspaceEntitlement and TenantProvisioningLink source. Lifecycle
becomes `active` and operational access resolves through centralized services.

# Consequences

- Existing branches, users, teachers, academic records, branding, and tenant identity
  are preserved.
- Browser return and incomplete provider events cannot activate access.
- Duplicate launch and webhook handling is idempotent; drift and source conflicts
  fail closed without partial authority.
- Returned or reused transactions are accepted only when billed with automatic
  collection and their item, price, quantity, subtotal, interval, currency,
  customer, address, business, checkout URL, and custom lineage match the current
  activation quote.
- PostgreSQL row-lock reads refresh mapped state before idempotency decisions, so a
  concurrent duplicate webhook cannot act on a pre-lock identity-map snapshot.
- Organization Account payment presentation is attempt-authoritative: lifecycle
  `provisioning` with no current attempt means Activation required, processing needs
  a current unexpired checkout-started or payment-processing attempt, and terminal
  attempts use recovery states.
- Promo, normal onboarding payment, and demo-to-paid flows remain separate.
- The additive migration must be applied before deploying the routes and webhook path.
