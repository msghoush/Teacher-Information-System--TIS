---
title: SaaS Onboarding History
module: saas-onboarding
last_updated: 2026-07-29
---

# SaaS Onboarding History

## 2026-07-29 - Organization Profile Save And Compact Account Setup

Organization Profile now accepts the three approved program labels through a
required selector and returns customer validation errors inline. Pending logo
uploads reuse actual-image validation, the 4 MB limit, minimum dimensions,
opaque UUID filenames, and atomic writes. Newly written files are removed if a
later save fails; empty upload retains the prior logo and successful
replacement safely retires it. Storage and unexpected failures retain
transaction rollback and produce server traceback logs without exposing raw
errors.

The initial Account Setup state now contains one setup title, one explicit POST
start action, and the existing eight-step journey under a smaller official
logo. Repeated status, action, context, and help panels are omitted only before
the pending organization exists.

Pending logos still use application-local
`static/uploads/saas/pending_logos`; durable Render storage remains a separate
persistent-disk or object-storage decision.

The saved logo is now visible in Organization Profile and the shared School
Workspace setup identity. Existing paid and demo provisioning already copied
the pending image into `SchoolGroupLogo`; that path is now explicitly
directory-confined, missing referenced files fail activation instead of being
silently skipped, and the final logo label uses the organization name for
accessible operational-shell rendering. TIS platform branding remains
separate.

Branch Setup no longer performs nullable estimate arithmetic in Jinja.
Python-normalized totals make empty, legacy-null, and mixed rows safe to
render. Customer saves retain required non-negative estimate validation, and
new branch records receive explicit zero defaults.

## 2026-07-29 - Post-Verification Login Method Safety

Fresh verified accounts no longer redirect successful login to the POST-only
onboarding creation endpoint. They open the GET Account Setup dashboard, where
the established explicit POST action starts School Workspace Setup. Sign-in
continuations now accept only known customer GET destinations, and accidental
GET navigation to the credential handler redirects to the normal sign-in page
instead of returning raw HTTP 405 JSON. Same-email re-registration,
subscription intent, and non-authoritative preferred-plan state remain
compatible.

## 2026-07-29 - Public Preferred-Plan Continuity

Public pricing may carry an allowlisted Starter, Professional, or Enterprise AI
preference into TIS Account registration. The preference is stored separately
from commercial records and does not select a plan or create checkout. Once
School Workspace Setup is complete, the existing branch, system-user, and
teacher capacity decision either preselects the eligible preference or clears
it with customer-safe guidance. Missing and malformed values are safe.

## 2026-07-28 - Returning Customer State Routing

Successful SaaS login now derives its destination from onboarding, pending demo,
durable account-to-workspace, lifecycle, classification, and subscription
evidence. Active customers enter the app, incomplete customers resume setup,
unpaid customers reach plans, and expired customers receive branded guidance.
Customer language uses “TIS team,” while internal Platform Owner identifiers
and audits remain intact.

## 2026-07-27 - M8B7 Demo Customer Journey

Normal approval now invokes the existing independently retryable provisioning service. Six branded lifecycle email types use a durable outbox, and Platform Owner events reuse the existing Notification Center. The shared tenant shell displays active Customer Demo status. Day 6 and expiry create communication intents atomically, and coherent expired demos may convert after authoritative confirmed payment by reactivating the same workspace. M8B8 and M8B9 are not included.

This folder tracks meaningful changes to signup, login, account, organization onboarding, contacts, branches, academic setup, review, and account self-service.

## 2026-07-26 - Platform Owner Historical Demo Eligibility Maintenance

Historical detached `SaaSDemoDomainEligibility` rows can outlive the organization/account records that once made them reachable through clean-room reset. Platform Owners now have a separate `/saas-admin/demo-eligibility-maintenance` page that scans the eligibility ledger and explains whether each reservation is safe or protected.

The maintenance analyzer uses authoritative domain normalization and checks for matching pending organizations, SaaS accounts, demo requests, tenant-profile workspaces, paid or demo provisioning, subscription contracts/subscriptions, Demo-to-Paid conversions, and manual-review evidence. Only an exact eligibility ID with no blockers may be deleted. The POST action locks and re-analyzes the row, requires typed-ID and checkbox confirmation, bulk-deletes by primary key only, flushes, verifies absence, and commits or rolls back as one transaction. Successful cleanup is owner-audited.

This administrative repair capability does not modify the customer demo request workflow, the durable one-demo-per-domain rule, the existing test workspace/account reset, schema, foreign keys, or customer-facing behavior.

## 2026-07-26 - Internal Test Workspace Commercial Clean-Room Reset

The guarded Platform Owner test workspace/account reset now clears only the selected organization's linked demo request, domain-eligibility reservation, review and event history, demo provisioning and lifecycle records, and demo-to-paid conversion history before deleting parent commercial and workspace records. The same email and organization domain can then complete a new internal M8 journey.

Detached same-domain reservations left by the `ON DELETE SET NULL` relationship are also eligible for removal, but only after the same domain resolver used by Customer Demo submission confirms there is no other organization, request, workspace, or customer account using that domain and the reservation has no historical manual-review evidence. Any conflicting or ambiguous evidence blocks the reset for manual review. This narrow exception does not alter the production Customer Demo policy: normal customer domain reservations remain durable after pending, approved, active, expired, rejected, cancelled, or converted history. Global plans, prices, Paddle records, platform configuration, and other organizations' records remain outside the reset scope. Customer-facing demo wording now identifies the TIS team rather than an internal role.

Reset analysis now publishes the exact detached eligibility IDs that passed those safety checks. The deletion service consumes only that safe list, deletes it before demo-request and parent records, flushes immediately, and verifies that no selected ID remains. Any handoff mismatch or failed verification stops the transaction so the owner route can roll back all changes.

## 2026-07-25 - Landing Intent Continuity And One Customer Demo Per Organization Domain

The public landing conversion paths now enter TIS Account signup with a validated `demo` or `subscribe` intent. The intent is persisted on the SaaS account and copied to School Workspace Setup so the final commercial-choice page can emphasize the customer's original path while still allowing either Request Demo or Subscribe Now.

Customer Demo requests now resolve a normalized organization domain, preferring the organization identity and using a work email only when necessary. Public email providers require an official organization website or domain. A transactionally unique domain-eligibility reservation prevents a second customer demo across pending, approved, active, expired, rejected, cancelled, or converted history. The reservation never causes tenant reprovisioning or Demo-to-Paid workspace replacement, and Internal Sandbox history is excluded.

Migration `20260725_001_demo_domain_eligibility_policy` adds safe historical normalization. It reserves ambiguous duplicate domains for manual review rather than merging, deleting, or guessing across existing customer records. The companion diagnostic command defaults to dry-run and produces the duplicate-domain review list.

## 2026-07-23 - M8B-6 Demo-To-Paid Workspace Conversion

Eligible active Customer Demo workspaces can now enter the unchanged M7 subscription checkout. Provider-confirmed payment triggers a dedicated, idempotent conversion service rather than paid tenant provisioning.

The conversion preserves the SchoolGroup, workspace UUID, tenant link row, pending organization, branches, users, permissions, academic records, and all request/demo/audit history. One atomic transaction ends the demo entitlement, creates the confirmed subscription-backed paid entitlement, relinks branch entitlement rows, changes the workspace classification to Customer Paid, and moves the existing tenant link from demo-request evidence to the confirmed subscription contract.

Conversion Requested, Processing, Completed, and Failed states plus audit/internal-notification events are durable. Failure rolls back workspace mutations while preserving confirmed provider payment records for retry. Completed workspaces no longer enter demo reminder or expiration processing. Expired, ambiguous, cross-tenant, internal-sandbox, already-paid, or incoherent workspaces fail closed.

## 2026-07-23 - M8B-5 Standard Customer Demo Lifecycle

Customer demos now run for exactly seven days from successful workspace activation. The centralized resolver derives Day 6 and Day 7 boundaries in UTC, presents them in the organization timezone, and fails closed on inconsistent lifecycle evidence.

The independently callable processor is dry-run by default. Apply mode creates idempotent internal reminder notifications and atomically ends the demo entitlement and suspends the workspace at expiration. Operational middleware rechecks customer-demo access on every protected request, including existing sessions; web users are routed to subscription guidance and APIs return a safe 403. Workspace users, branches, and all tenant data remain preserved, and Platform Owner inspection remains available.

## 2026-07-23 - M8B-4 Demo Workspace Provisioning And Activation

Platform Owners can now provision an Approved customer-demo request through a separate, fail-closed action. The demo service revalidates the approval, organization, customer-demo intent, commercial snapshot, entitlement snapshot, and duplicate absence before reusing the shared operational workspace builder.

The transaction creates the customer-demo SchoolGroup, branches, academic year, owner user, permissions, account link, explicit demo entitlement, and demo-sourced tenant link, then activates the workspace and entitlement. No Paddle, payment, paid subscription, subscription contract, checkout, or email record is created. Failures roll back all workspace changes, preserve the Approved request, and retain a safe retryable outcome plus audit event.

## 2026-07-22 - M8B-3 Demo Request Workflow

Completed onboarding now presents Request Demo and Subscribe Now. Subscribe Now preserves the existing plan-selection and Paddle lifecycle. Request Demo validates the verified customer and complete onboarding record, stores a review-only commercial snapshot, and prevents duplicate pending requests.

Customers can view request status and withdraw a pending request. Platform Owners have a searchable/filterable review queue and may approve, reject with a mandatory reason, or cancel. Approval creates review evidence only; no SchoolGroup, entitlement, checkout, payment, provisioning, activation, or email is created. Durable audit and internal-notification events record every transition.

## 2026-07-16 - M7 Phase 2 Read-Only Subscription Management Portal

Verified SaaS customers now have a read-only Subscription Management page at `/saas/subscription`. The page presents the confirmed plan, safe subscription health, billing interval, next billing date, paid and active branch quantities, remaining capacity, grouped feature entitlements, and a compact plan comparison. All commercial data is supplied by `saas.entitlement_service`; the portal does not query Paddle or independently calculate subscription state or branch capacity.

Upgrade, branch-addition, billing-history, invoice, pending-change, and subscription-management controls are visible only as disabled Coming Soon options. This phase adds no subscription mutations, Paddle calls, proration, refunds, cancellation, or plan and quantity editing.

## 2026-07-16 - M7 Phase 1 Subscription Entitlement Foundation

Commercial access now resolves through `saas.entitlement_service` from the provisioned SchoolGroup's tenant link, paid operational contract, and one confirmed active Paddle subscription. Onboarding selections, checkout quotes, pending payment attempts, and page values are not entitlement sources. Missing, mismatched, or ambiguous subscription relationships fail closed as `manual_review`.

The initial normalized matrix authoritatively maps only existing plan metadata: Enterprise AI receives `module.ai`; Professional and Enterprise AI receive `feature.advanced_reporting`; Starter does not receive either. Paid active-branch capacity is derived only from `PaymentSubscription.quantity`. Teacher management, branch management, observations, hiring, core reporting, general exports, audit logs, and cross-branch reporting remain `owner_approval_required` until commercial rules are approved.

Pilot enforcement is limited to allocation-plan PDF/XLSX exports. Both the existing `reports.export` user permission and `feature.advanced_reporting` subscription entitlement must succeed. Platform Owner and Developer identities do not bypass subscription entitlements and must operate in a selected tenant scope.

Upgrades, downgrades, proration, refunds, Paddle subscription changes, branch-specific plans, and customer subscription-management UI remain later M7 work.

## 2026-07-26 - Test Workspace Reset Subscription-Change Dependency

The Platform Owner-only test workspace/account reset now deletes `subscription_change_requests` scoped by the selected operational `school_group_id` before deleting that workspace's users. It deletes selected entitlement values and branch-entitlement children before the selected workspace entitlement and final SchoolGroup. These narrow ordering rules prevent foreign-key deletion failures without changing lifecycle rules, customer behavior, or the preservation of records from other workspaces. The reset remains one transaction with the existing validation blocks, rollback behavior, pre-analysis counts, and structured diagnostics.

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
