---
title: SaaS Onboarding History
module: saas-onboarding
last_updated: 2026-06-27
---

# SaaS Onboarding History

This folder tracks meaningful changes to signup, login, account, organization onboarding, contacts, branches, academic setup, review, and account self-service.

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
