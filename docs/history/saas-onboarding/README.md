---
title: SaaS Onboarding History
module: saas-onboarding
last_updated: 2026-07-14
---

# SaaS Onboarding History

This folder tracks meaningful changes to signup, login, account, organization onboarding, contacts, branches, academic setup, review, and account self-service.

## 2026-07-16 - M7 Phase 1 Subscription Entitlement Foundation

Commercial access now resolves through `saas.entitlement_service` from the provisioned SchoolGroup's tenant link, paid operational contract, and one confirmed active Paddle subscription. Onboarding selections, checkout quotes, pending payment attempts, and page values are not entitlement sources. Missing, mismatched, or ambiguous subscription relationships fail closed as `manual_review`.

The initial normalized matrix authoritatively maps only existing plan metadata: Enterprise AI receives `module.ai`; Professional and Enterprise AI receive `feature.advanced_reporting`; Starter does not receive either. Paid active-branch capacity is derived only from `PaymentSubscription.quantity`. Teacher management, branch management, observations, hiring, core reporting, general exports, audit logs, and cross-branch reporting remain `owner_approval_required` until commercial rules are approved.

Pilot enforcement is limited to allocation-plan PDF/XLSX exports. Both the existing `reports.export` user permission and `feature.advanced_reporting` subscription entitlement must succeed. Platform Owner and Developer identities do not bypass subscription entitlements and must operate in a selected tenant scope.

Upgrades, downgrades, proration, refunds, Paddle subscription changes, branch-specific plans, and customer subscription-management UI remain later M7 work.

## 2026-07-14 - M6 Phase 3 Abandoned Draft Cleanup

Automatic cleanup applies only to unpaid, unprovisioned SaaS drafts. A draft becomes eligible after the globally configured inactivity period (30 days by default) and only after its final reminder was sent successfully for the current activity cycle. Any later meaningful activity restarts the lifecycle and prevents deletion.

Before deleting, the processor locks and rechecks each account and pending organization in its own transaction. Payment success or processing, subscription evidence, provisioning or tenant links, operational identities, protected accounts, shared ownership, and unresolved provider relationships block cleanup. Ambiguous records are retained for manual review. Successful payment evidence, Paddle webhooks and remote Paddle records, global plans/prices, reference data, and unrelated accounts or tenants are always preserved.

Run the bounded processor from the repository root:

```bash
PYTHONPATH=. python scripts/process_abandoned_draft_cleanup.py --dry-run --batch-size 100
PYTHONPATH=. python scripts/process_abandoned_draft_cleanup.py --batch-size 100
PYTHONPATH=. python scripts/process_abandoned_draft_cleanup.py --dry-run --account-email draft@example.com
```

`--max-inactivity-days` is available only for local testing and is rejected in production-like environments. For Render, configure a daily Cron Job using the deployed service environment and `DATABASE_URL`; dry-run should be used before enabling the live command. Each account commits independently, failures roll back completely, concurrent workers skip locked rows, and durable external audit events record deleted, skipped, manual-review, recovery, and rolled-back outcomes.

Platform Owner lifecycle analytics remain future M6 scope.

## 2026-07-14 - M6 Phase 2 Draft Onboarding Reminder Engine

Draft retention remains inactivity-based. The reminder engine sends at most one first, second, and final reminder per activity cycle using the globally configured lifecycle thresholds (defaults: 24 hours, 7 days, and 25 days). The final reminder shows the deletion-eligibility date derived from the configured retention period (default: 30 days). Meaningful customer activity continues to flow through `draft_lifecycle_service.record_meaningful_activity(...)`, which starts a new reminder cycle.

Run the bounded processor from the repository root:

```bash
PYTHONPATH=. python scripts/process_draft_reminders.py --batch-size 100
PYTHONPATH=. python scripts/process_draft_reminders.py --dry-run
PYTHONPATH=. python scripts/process_draft_reminders.py --stage final
```

For Render, use a Cron Job with the service's `DATABASE_URL`, `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_REPLY_TO`, and `TIS_PUBLIC_BASE_URL`. `TIS_SUPPORT_EMAIL` is optional and falls back to `EMAIL_REPLY_TO` in reminder content. An hourly schedule is recommended. PostgreSQL row locking prevents overlapping workers from sending the same reminder stage.

Automatic draft deletion and Platform Owner lifecycle analytics are not enabled in Phase 2.

## 2026-06-27 - Subscription And Workspace Activation Guided Journey Phase 3C

Phase 3C subscription, payment, and activation page redesign is accepted.

What changed:

- Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages now use the Phase 3A shared shell and Phase 3B guided style.
- Each page now has one shared-shell primary CTA and keeps secondary actions visually secondary.
- Secure Payment pages now clearly explain that browser return from checkout does not itself confirm payment.
- Subscription and activation status pages now use concise customer-safe cards for payment, subscription, activation, and TIS Platform access state.
- Customer-facing pages now consistently explain that TIS Platform access becomes available after Workspace Activation.

Scope notes:

- Payment behavior, billing behavior, provisioning behavior, webhook logic, checkout start/launch behavior, stored statuses, database schema, migrations, operational modules, the Next.js landing website, OAuth behavior, internal `/saas` route names, and admin views were not changed.

Related files:

- `saas/router.py`
- `templates/saas/plan_selection.html`
- `templates/saas/checkout_summary.html`
- `templates/saas/checkout_return.html`
- `templates/saas/checkout_cancel.html`
- `templates/saas/account_billing.html`
- `templates/saas/billing_status.html`
- `tests/test_saas_phase1.py`

## 2026-06-27 - School Workspace Setup Guided Wizard Phase 3B

Phase 3B School Workspace Setup onboarding page redesign is accepted.

What changed:

- Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup now use a consistent guided wizard structure on top of the Phase 3A shared shell.
- Each onboarding page now has one shared-shell primary CTA and keeps Back/Save Draft actions visually secondary.
- Organization Profile groups identity, logo upload, program/location, and estimated scale fields.
- Branch Setup uses compact branch panels instead of heavy repeated blank blocks.
- Academic Setup and Primary Contact use focused single-step sections with concise guidance.
- Review School Workspace Setup now presents a clearer ready-to-continue summary before Subscription Selection.

Scope notes:

- Form actions, field names, routes, validation behavior, draft behavior, onboarding progression, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, OAuth behavior, internal `/saas` route names, and admin views were not changed.
- Subscription/payment/status pages remain future Phase 3 work.

Related files:

- `saas/router.py`
- `templates/saas/base.html`
- `templates/saas/onboarding_organization.html`
- `templates/saas/onboarding_branches.html`
- `templates/saas/onboarding_academic_setup.html`
- `templates/saas/onboarding_contacts.html`
- `templates/saas/onboarding_review.html`
- `tests/test_saas_phase1.py`

## 2026-06-27 - TIS Account Guided Setup Framework Phase 3A

Phase 3A shared guided setup framework is accepted.

What changed:

- The shared customer account shell now supports a guided setup console when setup context is provided.
- The TIS Account page now uses an 8-step customer journey: TIS Account, Email Verification, School Workspace Setup, Review & Confirmation, Subscription Selection, Secure Payment, Workspace Activation, and Enter TIS Platform.
- The account page now focuses on the current step, one primary next action, concise account/workspace context, and guidance that TIS Platform access becomes available after Workspace Activation.
- The old customer account dashboard statistics and session detail blocks were removed from the account landing page.
- Journey state is calculated from existing account, onboarding, billing, payment, and activation data without changing stored statuses.

Scope notes:

- Onboarding forms, subscription/payment pages, billing/status pages, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, internal `/saas` route names, admin views, and Google/Microsoft login were not changed.
- This phase prepares the shared framework for later Phase 3 onboarding and payment page redesign work.

Related files:

- `saas/router.py`
- `saas/service.py`
- `templates/saas/base.html`
- `templates/saas/account.html`
- `tests/test_saas_phase1.py`

## 2026-06-27 - TIS Account Customer-Facing Wording And Logo Cleanup

Phase 2 customer-facing wording cleanup is accepted.

What changed:

- Customer account and school workspace setup pages now use professional labels such as "TIS Account", "Account Dashboard", "School Workspace Setup", "Organization Profile", "Branch Setup", "Academic Setup", "Subscription Setup", "Secure Payment", and "Workspace Activation".
- Customer views use customer-safe display labels for internal onboarding, billing, payment, and activation statuses instead of exposing raw tenant/provisioning/checkout status values.
- Customer-facing billing and subscription views hide provider transaction/subscription IDs, attempt UUIDs, checkout session internals, plan IDs, and school group IDs.
- The shared customer account shell now includes the official full-color horizontal TIS logo image so inherited customer account/setup pages carry official branding.
- TIS Account transactional emails use an existing official dark-blue TIS wordmark asset.
- Activation email copy now uses "School Workspace", "Workspace Activation", and "TIS Account" language.

Scope notes:

- Internal `/saas` route/module/model names and stored statuses were not renamed.
- Payment, billing, provisioning behavior, database schema, migrations, operational modules, and the Next.js landing website were not changed.
- Google/Microsoft login remains future work and was not implemented.
- Phase 3 account setup UI redesign was not implemented.

Related files:

- `saas/router.py`
- `saas/service.py`
- `saas/provisioning_service.py`
- `email_templates.py`
- `templates/saas/`
- `tests/test_saas_phase1.py`
- `tests/test_saas_phase5.py`
- `tests/test_email_templates.py`

## 2026-06-27 - TIS Account Email Verification Recovery And Setup Gate

Phase 1 TIS Account email verification recovery is accepted.

What changed:

- Valid email verification links now mark the SaaS account email verified/active and redirect to TIS Account login with a professional success notice.
- Expired or invalid verification links now show a recovery page with a resend verification option.
- Resend verification supports unverified accounts, already verified accounts, and unknown-email cases with safe customer-facing messaging that does not reveal account existence.
- Password-based accounts that remain unverified are blocked from starting or continuing school workspace setup.
- New visible wording in this verification flow uses "TIS Account" and "school workspace setup".

Scope notes:

- Payment, billing, provisioning, database schema, migrations, operational modules, and the Next.js landing website were not changed.
- Google/Microsoft login remains future work and was not implemented.
- Phase 2 customer-facing wording cleanup and Phase 3 account setup UI redesign were not implemented as part of this change.

Related files:

- `saas/router.py`
- `saas/service.py`
- `templates/saas/`
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`
