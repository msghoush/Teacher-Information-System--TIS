---
title: TIS Repository Architecture
documentation_version: 3.1
last_updated: 2026-07-31
source_of_truth: true
---

# TIS Repository Architecture

## Three-Dimension Subscription Capacity Authority

`saas/branch_pricing_quote_service.py` owns one structured plan-capacity
decision across active billable branches, active non-teacher system users, and
active teacher records. `PendingOrganizationBranch` owns onboarding
`estimated_system_users` and `estimated_teachers`; organization-level legacy
values are migration inputs and derived compatibility summaries, not an
independent source of truth.

Before payment, each people count is the greater of the sum across active
onboarding branches and actual active data in the uniquely linked SchoolGroup.
After activation, actual counts are authoritative. System users are active,
non-test tenant `User` rows excluding the Teacher position. Teachers are
`Teacher` records in active branches and active academic years, whether or not
they have login accounts. Platform/internal identities, inactive users,
students, inactive branches, and inactive academic years do not count.

The decision is consumed by selection, quote construction, checkout
preparation/launch, Paddle creation, payment reconciliation, and plan changes.
Both people counts are part of quote fingerprint authority. Branch estimate
changes clear an undersized selected plan, invalidate its quote, mark ready or
started checkout sessions stale, and supersede incomplete payment attempts.
Paid system-user creation/reactivation and teacher creation/year-copy preflight
check the active subscription before mutation; downgrade impact reports branch,
system-user, and teacher conflicts independently. No capacity failure silently
deletes or deactivates operational data.

The current `Teacher` model has no inactive/reactivation lifecycle, and the
repository has no teacher import endpoint. Capacity enforcement therefore
covers the supported teacher-growth paths: individual creation and atomic
academic-year copying. Adding teacher deactivation/reactivation or import
workflows remains a separate lifecycle design task.

Starter persists 1 branch/5 system users/25 teachers, Professional 5/20/100,
and Enterprise AI 25/100/500. The lowest plan passing all dimensions is
recommended while any higher eligible plan remains selectable. The in-app
Custom card is informational and mail-based; exceeding any Enterprise limit
emphasizes it, but it creates no catalog plan, Paddle transaction, or
enterprise-request workflow.

## Subscription Plan Branch-Capacity Authority

`saas/branch_pricing_quote_service.py` evaluates the authoritative active
billable branch count against `SubscriptionPlan.max_branches`. Starter,
Professional, and Enterprise AI retain persisted capacities of one, five, and
twenty-five. The evaluator supplies both server-side rejection and plan-page
eligibility metadata; pricing remains the unit price multiplied by the actual
active count.

Plan selection and every checkout/payment phase consume a fail-closed quote, so
an undersized plan cannot produce a checkout or Paddle transaction. A
pre-payment branch change clears an undersized selection while preserving an
eligible higher plan, and the existing checkout-supersession boundary rejects
stale transaction completion. Counts are resolved only inside the current
pending organization or its same-workspace demo provisioning.

## Paddle Checkout Quantity Authority

`saas/branch_pricing_quote_service.py` supplies the authoritative billable
branch quantity and total to `saas/payment_service.py`. The payment service
sends that exact quantity with the selected catalog price and resolved customer
address when creating an automatically collected Paddle transaction. The
transaction must reach `ready`; returned item quantity, provider price,
subtotal, and quote fingerprint are validated before TIS marks it `billed`.
Only the resulting immutable transaction is released to checkout.

The public `/saas/payment` launcher opens the pre-created transaction with
Paddle’s inline one-page checkout settings and `transactionId`; it never passes
an editable items array. The billed transaction is a fixed financial record, so
item and quantity changes are rejected by Paddle. Automatic
`transaction.completed` webhook evidence remains the recurring-subscription and
conversion authority.

Pre-payment Branch Setup remains authoritative even when an unpaid demo
workspace or tenant link already exists. Only confirmed payment evidence or an
active paid subscription closes onboarding mutation. A branch identity or count
change marks ready/started checkout sessions stale, marks their incomplete
payment attempts superseded, clears quote snapshots, and returns the
organization to plan selection. Late events for superseded transactions are
retained for manual review but cannot change the current organization,
subscription, provisioning, or workspace state.

Before rendering Paddle.js, the launcher requires exactly one local payment
attempt and matching checkout session, organization, customer, quote, and
provider transaction. Remote status must be `billed` with automatic collection;
draft, ready, canceled, past-due, unrelated, or mismatched transactions fail
closed with a customer-safe message.

## Checkout Tenant-Identity Recovery Boundary

`saas/payment_service.py` owns Paddle customer identity resolution. For an
existing demo workspace, a stale `SaaSAccountUserLink` may be reassigned to the
authenticated account only when organization ownership, demo request and
provisioning source, the unique `TenantProvisioningLink`, SchoolGroup, exact
operational owner, and email identity all agree. The current account must have
no conflicting workspace link, and any previous linked account must be absent
or inactive. Missing, unrelated, active-previous-owner, cross-workspace, or
multiple identity evidence fails closed.

This recovery does not select a Paddle customer by email in live mode, bypass
provider confirmation, provision a tenant, or create another SchoolGroup.
Internal match diagnostics are logged; customer routes receive only retry and
support guidance.

## Returning Customer And Commercial-Access Boundary

`saas/customer_journey_service.py` owns customer login destinations and the
expired-demo subscription projection. It reads onboarding/request records, the
durable SaaS-account operational link, demo lifecycle, SchoolGroup
classification, actual active Branch rows, public plans, and subscription
evidence. `saas/commercial_access_service.py` is the operational access
projection used after credential validation, by customer journey routing, and
by request authorization. For Customer Paid workspaces it consumes the existing
`saas.entitlement_service` tenant-link and SubscriptionContract-linked
subscription resolution; it never chooses the newest organization-level row.
It adds workspace lifecycle, pending-change context, state-specific messaging,
and the allow/deny decision without replacing payment, entitlement, plan-change,
or demo-lifecycle authorities. Terminal or unresolved plan-change requests do
not replace the current paid entitlement.

`/saas/subscription/demo/select` records conversion intent and reuses existing
plan selection and checkout routes; it never provisions or copies a second
workspace. Public navigation remains in `tis-landing-website/` and builds app
routes exclusively from `NEXT_PUBLIC_TIS_APP_BASE_URL`.

## M8B9 Demo Operations Boundary

The owner HTTP surface delegates mutations to `saas/demo_operations_service.py`,
which validates and locks the Customer Demo context, calls existing lifecycle
and communication services, and writes audit state. Access decisions resolve
through `saas/demo_access_service.py` before the M8B8 counter. Workspace policy
is the default; branch policy requires same-tenant validation. M8B9 DDL runs
only through `python scripts/run_migrations.py` during pre-deploy.

## M8B8 AI Entitlement Boundary

AI route code must never inspect classifications, plans, or usage rows
directly. It requests a decision from `saas.ai_entitlement_service`, performs
the real AI operation only when allowed, and records consumption only after a
usable result. The registry is code-controlled configuration. Commercial state
and permissions remain upstream authorities; accounting is downstream and
tenant-scoped.

## M8B7 Communication Boundaries

Demo email intent creation and dispatch belong to `saas/demo_email_service.py`; Platform Owner Notification Center creation belongs to `saas/demo_notification_service.py`. Routes orchestrate existing services but do not own lifecycle calculations. Provider calls occur outside lifecycle locks. The shared shell consumes the read-only lifecycle resolver and never becomes lifecycle authority.

This document explains the main repository areas, what each owns, and what must not be changed casually.

## Root FastAPI Application

### `main.py`

Responsibility:
Primary FastAPI app, route registration, many app-level workflows, middleware, startup checks, platform console routes, dashboards, exports, system configuration, scope switching, and operational pages.

Render boot boundary:
The ASGI web process never performs SQLAlchemy metadata creation or pending
migrations. `scripts/run_migrations.py` is the sole deployment command for
baseline schema creation plus `db_migrations.run_pending_migrations`; Render
runs it as the Pre-Deploy Command and activates the new version only after exit
code zero. `main:app` startup retains only security configuration validation
and process-local upload-directory creation, so Uvicorn binds without
PostgreSQL DDL. There is no migration daemon or schema-readiness middleware.

Do not change casually:
- authentication/session flow,
- platform owner access checks,
- tenant scope handling,
- route behavior shared by many modules,
- startup/schema repair behavior.

### `auth.py`

Responsibility:
Password hashing/verification, session cookies, current-user lookup, role normalization, platform identity helpers, permission helpers, email verification helpers, and tenant/platform identity boundaries.

Do not change casually:
- `is_platform_owner`, `is_platform_user`, `is_platform_developer`,
- role normalization,
- session cookie behavior,
- permission helper semantics.

### `authorization.py`

Responsibility:
Protected route rules, permission enforcement middleware integration, access-denied responses.

Do not change casually:
- route permission mapping,
- public path patterns,
- permission matching semantics.

### `database.py`

Responsibility:
Database engine/session setup.

Do not change casually:
- database URL handling,
- session creation behavior,
- engine configuration.

### `models.py`

Responsibility:
Primary operational SQLAlchemy models for users, school groups, branches, teachers, planning, timetable, observations, configuration, and related app data.

Do not change casually:
- tenant ownership fields,
- platform user fields,
- relationships used by existing workflows,
- schema without matching migration/repair strategy.

### `db_migrations.py`

Responsibility:
Local schema migration and repair logic used by the app.

Do not change casually:
- migration ordering,
- destructive schema operations,
- production-sensitive repair behavior.

### `permission_registry.py`

Responsibility:
Permission groups, labels, default role permissions, system owner permissions, developer-assignable permission boundaries.

Do not change casually:
- owner/developer permissions,
- defaults for managed roles,
- permission keys referenced by routes/templates/tests.

### `role_permission_service.py`

Responsibility:
Persistence and service helpers for role permission rows.

Do not change casually:
- global vs school-scoped permission behavior,
- role permission constraints.

### `ui_shell.py`

Responsibility:
Shared application shell, navigation, page metadata, scoped organization/year context display, logos, visual design CSS, and permission-based nav generation.

Do not change casually:
- navigation visibility,
- platform-vs-tenant shell behavior,
- design-studio gating,
- scope display.

### `knowledge_service.py` And `kms_catalog.py`

Responsibility:
`knowledge_service.py` reads the generated KMS manifest and approved Markdown metadata for the owner-only Knowledge Center. `kms_catalog.py` provides the dependency-free approved category/module vocabulary and deterministic source-path classification shared by the service and KMS validation tooling.

Do not change casually:
- owner-only read behavior,
- manifest freshness semantics,
- approved category or module slugs,
- path classification without matching KMS tests and documentation.

## Feature Routers: `routers/`

Responsibility:
Modular operational route handlers:

- `routers/users.py`
- `routers/teachers.py`
- `routers/subjects.py`
- `routers/planning.py`
- `routers/timetable.py`
- `routers/academic_calendar.py`
- `routers/observations.py`

Do not change casually:
- tenant/branch/year scoping,
- permission checks,
- import/export behavior,
- bulk operations.

## SaaS Package: `saas/`

Responsibility:
Public SaaS account flows, onboarding, plans, billing, Paddle integration, pending organizations, and provisioning.

Key files:

- `saas/router.py`
- `saas/service.py`
- `saas/models.py`
- `saas/pricing_service.py`
- `saas/payment_service.py`
- `saas/paddle_client.py`
- `saas/billing_service.py`
- `saas/provisioning_service.py`
- `saas/currency_service.py`
- `saas/oauth.py`
- `saas/entitlement_service.py`
- `saas/subscription_portal_service.py`
- `saas/subscription_change_service.py`
- `saas/subscription_plan_change_service.py`
- `saas/subscription_cancellation_service.py`
- `saas/subscription_lifecycle_service.py`
- `saas/billing_history_service.py`
- `saas/payment_lifecycle_reconciliation_service.py`

Do not change casually:
- identity separation,
- payment confirmation rules,
- provisioning readiness,
- Paddle/webhook boundaries,
- public signup/onboarding state transitions.

## Templates: `templates/`

Responsibility:
Jinja templates for operational app, platform console, Knowledge Center, SaaS pages, system configuration, and feature workflows.

Do not change casually:
- form action routes,
- hidden scope fields,
- permission-dependent controls,
- app shell extension patterns.

## Static Assets: `static/`

Responsibility:
Operational CSS/JS, images, branding assets, generated documentation PDF and manifest.

Important:
- `static/docs/TIS_Project_Reference_Booklet.pdf` is a generated snapshot.
- `static/docs/docs_manifest.json` is generated metadata.

Do not change casually:
- generated docs manually,
- shared CSS without checking all templates,
- protected document access assumptions.

## Tests: `tests/`

Responsibility:
Regression coverage for SaaS phases, tenant isolation, platform access, permissions, email, branding, and critical workflows.

Do not change casually:
- tests should follow behavior, not hide regressions.
- update tests when behavior intentionally changes.

## Docs: `docs/`

Responsibility:
KMS source of truth, engineering handbook, ADRs, change history, module history, AI context, marketing docs.

Do not change casually:
- historical records should preserve old/new state.
- update docs through the KIA process.

## Scripts: `scripts/`

Responsibility:
Maintenance, diagnostics, and governance scripts. Important examples:

- `scripts/generate_docs_pdf.py`: generate or read-only validate KMS PDF/manifest artifacts.
- `scripts/check_kms_impact.py`: compare KIA declarations, Git changes, major-path classification, and artifact freshness.
- `scripts/kms.py`: supported Phase 6 command surface for one-step synchronization and complete read-only validation; delegates to the generator and checker.
- `scripts/sync_paddle_price_ids.py`: environment-specific initial checkout price mapping.
- `scripts/diagnose_paddle_plan_preview.py` and `scripts/diagnose_payment_lifecycle.py`: safe subscription/payment diagnostics.
- `scripts/reconcile_finalized_payment_lifecycle.py`: guarded sandbox reconciliation from attributable provider evidence.

Do not change casually:
- PDF generator dependency assumptions,
- source list behavior,
- manifest metadata.
- title, catalog, navigation-link, source-inventory, and PDF page-bound validation.

## Repository Governance

Responsibility:
Make KMS impact visible and enforceable without rewriting documentation.

Key files:

- `AGENTS.md`
- `.kms-impact.yml`
- `.github/pull_request_template.md`
- `.github/workflows/kms-enforcement.yml`
- `.github/workflows/deploy-on-master.yml`

Do not change casually:

- major-path classification,
- explicit no-impact override requirements,
- authoritative Markdown/path rules,
- deployment dependency on KMS validation,
- prohibition on customer/runtime/secrets data in documentation.

## Next.js Landing Website: `tis-landing-website/`

Responsibility:
Public marketing website at `https://tisplatform.com`.

Do not change casually:
- landing implementation during backend tasks,
- visual system without approval,
- public assets/copy without checking marketing docs and ADRs.
