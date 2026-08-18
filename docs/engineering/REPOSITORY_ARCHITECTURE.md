---
title: TIS Repository Architecture
documentation_version: 3.1
last_updated: 2026-08-06
source_of_truth: true
---

# TIS Repository Architecture

## Existing Workspace Controlled Conversion Layer

## Existing Workspace Paid Activation Boundary

`saas/existing_workspace_paid_activation_service.py` owns eligibility, operational
capacity recount, plan/branch quote snapshots, idempotent preparation, workspace
Paddle-customer association, transaction launch, and webhook-only activation for
an existing SchoolGroup. It reuses `saas/billing_identity_service.py`,
`saas/paddle_client.py`, and the centralized commercial resolvers. It never calls
the tenant provisioning engine and never creates a PendingOrganization.

`ExistingWorkspacePaidActivation` is the durable authority context. CheckoutSession
and PaymentAttempt accept exactly one of the established PendingOrganization context
or this context. SchoolGroup-anchored billing profiles, contracts, and subscriptions
support the existing workspace without weakening onboarding constraints.
Payment-customer workspace associations retain the exact provider address and
business lineage used by each SchoolGroup.

The shared Paddle webhook dispatcher recognizes this context before onboarding and
subscription-mutation handlers. Only matching `transaction.completed` evidence can
create paid WorkspaceEntitlement, BranchEntitlement, PaymentSubscription, and the
paid TenantProvisioningLink. Workspace classification remains `customer` and the
lifecycle becomes `active`. A transaction is released only after complete provider
billed-state and quote-lineage validation. Locking queries refresh mapped state
before concurrent idempotency checks.

`saas/existing_workspace_conversion_service.py` owns M4B preparation, verified
owner alignment, setup validation, fresh-audit comparison, row locking,
idempotency, and the final activation-required transition. It composes M4A,
normal SaaS verification, provisioning owner identity conventions, M1, and M3;
it does not duplicate those responsibilities. `ExistingWorkspaceConversionOperation`
is the durable claim/state ledger and `ExistingWorkspaceConversionEvent` is an
append-only redacted event stream.

`scripts/convert_existing_workspace.py` is dry-run by default. PostgreSQL write
mode requires Platform Owner actor IDs plus an exact `PREPARE <operation UUID>`
or `CONVERT <operation UUID>` phrase. Preparation requires the current complete
M4A hash. Final execution performs another M4A audit in the locked transaction
and compares stable branch/dependency and sandbox-entitlement evidence to the
operation baseline; intended owner and setup changes are the only expected
differences. The CLI never creates passwords, sends email, calls Paddle, or
redeems promo codes.

Customer routes under `/saas/existing-workspace/` expose only verified claim
and three-field setup review. `commercial_state_service`,
`commercial_access_service`, and `commercial_authority_service` recognize the
specific `customer / provisioning / no source` result as fail-closed
`activation_required`. The ordinary subscription portal redirects this state
back to Organization Account because existing-workspace Paddle activation is
not yet implemented.

## Existing Workspace Conversion Audit Layer

`saas/existing_workspace_conversion_audit_service.py` is a query-only evidence
collector. It accepts an exact SchoolGroup ID, workspace UUID, organization
name, and owner email; reflects the connected schema; follows branch foreign
keys recursively; identifies unconstrained branch-like columns; and returns
allowlisted identity, lifecycle, ownership, provisioning, and commercial
metadata. It does not own or commit a transaction and exposes provider
references only as presence flags.

`scripts/audit_existing_workspace_conversion.py` is the manual production
entry point. It requires PostgreSQL and `DATABASE_URL`, establishes
`REPEATABLE READ READ ONLY`, invokes the service, emits one sanitized JSON
or text report, then rolls back and closes. The service canonicalizes ordered
evidence into a stable SHA-256 snapshot, classifies soft-deleted rows without
ignoring them, compares reflected branch foreign keys with ORM metadata, and
emits archival candidates only when each referenced count is zero. The CLI
reports transaction settings and uses exit `0` for coherent evidence, `1` for
execution/configuration failure, `2` for manual review, and `3` for workspace
identity mismatch. The script is not imported by application runtime. Audit
readiness means only that later conversion design may proceed; hard deletion
and write conversion remain explicitly unapproved.

## Promo Redemption Layer

`saas/promo_redemption_service.py` is the write boundary between secure M2
definitions and operational commercial authority. It accepts either an owned
completed `PendingOrganization` or an existing aligned `SchoolGroup` with a
tenant-owner account link. The latter path deliberately creates no synthetic
onboarding, contract, subscription, payment, or demo row.

Final activation locks session, definition, and workspace in stable order and
commits immutable `PromoRedemption`/`PromoGrant`, branch assignments and
entitlements, promo `WorkspaceEntitlement`, promo `TenantProvisioningLink`,
lifecycle updates, and audit together. `saas/promo_grant_service.py` resolves
effective grants and expiration and owns atomic assignment/entitlement activation
when a branch is created or reactivated; M1 composes that result. `auth.py`
restricts customer-classified operational branch queries to explicit active promo
branch entitlements. Pending or inconsistent evidence fails closed.

Existing-branch selection does not alter `Branch.status`. Staff and teachers
are organization-wide validation inputs and are never selected, disabled, or
deleted. Normal future branch creation may consume only an unused grant branch
slot. Paddle remains outside this layer.

`saas/promo_branch_entitlement_reconciliation_service.py` is the conservative
repair boundary for legacy incomplete promo evidence. It requires one resolved
active promo authority, tenant source, owner, and workspace entitlement; inventories
all branches, assignments, and entitlement rows; and can create only a missing
inactive entitlement for an unassigned branch. The PostgreSQL CLI defaults to
dry-run, locks and revalidates on apply, and commits or rolls back as one unit.

`saas/commercial_portal_service.py` is the read-only customer presentation adapter
for promo authority. It consumes `commercial_authority_service` rather than
recounting capacity, then resolves the attributable `PromoGrant` and
`PromoRedemption` only for immutable dates and the masked promo reference. The SaaS
subscription route selects this adapter by authoritative source before invoking the
paid portal. Promo, paid, and demo view models remain separate; Jinja templates do
not decide commercial authority. The promo view exposes the existing-workspace paid
continuation entry only when `existing_workspace_paid_activation_service` proves an
expired or recovery-period promo source and verified tenant owner.

`promo_grant_service` derives active, recovery, and expired time states. Recovery is
presentation/conversion eligibility only; commercial access remains blocked from the
exact expiry timestamp. `existing_workspace_paid_activation_service` owns the locked,
provider-confirmed promo-to-paid transition. It keeps promo authority during checkout
and atomically moves the existing `TenantProvisioningLink`, workspace entitlement,
and branch entitlements to the confirmed paid contract/subscription at completion.
No replacement tenant or synthetic onboarding organization is created.

`saas/commercial_badge_service.py` is the sole commercial identity presentation
adapter. It accepts centralized commercial access, rejects unresolved placeholder
sources, and returns semantic source, status, icon, and plan tokens for the reusable
`templates/_commercial_badge.html` component. The operational shell uses compact
mode; Organization Account and commercial access use full mode.

## Promo Definition Layer

Promo administration is an isolated SaaS/Platform layer. The router requires a
Platform identity plus granular promo permission; the service owns validation,
secure generation, lifecycle locking, and safe audit; models and migration own
only definition/history persistence. Templates receive raw code only in the
immediate create/duplicate/replace response and all later views use a masked
representation.

The M3 commercial adapter contract is implemented as a grant identity,
tenant and organization identity, `source=promo`, status, plan, effective
window, three capacity limits, selected branch IDs, immutable snapshot,
resolution status, and reason code. M2 definition operations still provide no
access; only a completed M3 grant is authoritative.

## Three-Dimension Subscription Capacity Authority

`saas/branch_pricing_quote_service.py` owns pre-payment plan eligibility and
quote capacity across active billable branches, system-user estimates, and
teacher estimates. `PendingOrganizationBranch` owns onboarding
`estimated_system_users` and `estimated_teachers`; organization-level legacy
values are migration inputs and derived compatibility summaries, not an
independent source of truth.

Before payment, each people count is the greater of the sum across active
onboarding branches and actual active data in the uniquely linked SchoolGroup.
After activation, `saas/commercial_authority_service.py` is the single facade.
Staff usage is every distinct active tenant operational `User`, including
operational owners, teacher-position users, and internal-test-attributed tenant
users. Platform users, inactive users, account-only SaaS identities, and other
tenants do not count. Teachers are deduplicated by normalized
`Teacher.teacher_id` across active branches and active academic years; every
blank legacy teacher identity counts separately.

The decision is consumed by selection, quote construction, checkout
preparation/launch, Paddle creation, payment reconciliation, and plan changes.
Both people counts are part of quote fingerprint authority. Branch estimate
changes clear an undersized selected plan, invalidate its quote, mark ready or
started checkout sessions stale, and supersede incomplete payment attempts.
Operational branch, staff-user, teacher, and academic-year growth locks the
SchoolGroup, composes the existing commercial authorities, recounts, evaluates
the proposed final state, and mutates in the same transaction. Paid and demo
provisioning perform the same final invariant. Downgrade impact still reports
branch, system-user, and teacher conflicts independently. No capacity failure
silently deletes or deactivates operational data.

Paid limits are provider-confirmed subscription quantity capped by the plan
branch ceiling plus the plan's staff and teacher limits. Customer Demo and
Internal Sandbox are explicitly unmetered in M1 when their existing authority
is coherent. Missing or contradictory authority fails closed. Existing
over-capacity tenants preserve data and access but cannot further increase an
exceeded dimension.

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
evidence. It also resolves linked organization-account management scope from
the existing SaaSAccountUserLink, operational user, ownership, and permission
records. Activated account managers land on `/saas/account`; ambiguous
multi-organization identities select an organization there. The selected UUID
is an HTTP-only request hint that is revalidated against SaaSAccountUserLink,
the operational user, ownership, and permissions before
`saas.entitlement_service` may resolve that SchoolGroup. Linked users with no
account-management permission retain the existing role-based operational
destination. `saas/commercial_access_service.py` is the operational access
projection used after credential validation, by customer journey routing, and
by request authorization. For Customer Paid workspaces it consumes the existing
`saas.entitlement_service` tenant-link and SubscriptionContract-linked
subscription resolution; it never chooses the newest organization-level row.
It adds workspace lifecycle, pending-change context, state-specific messaging,
and the allow/deny decision without replacing payment, entitlement, plan-change,
or demo-lifecycle authorities. Terminal or unresolved plan-change requests do
not replace the current paid entitlement.

`saas/router.py` applies that resolver after password and social login, for an
already-authenticated sign-in page, and from the SaaS root. The Organization
Account Overview is an account-management boundary, not an operational bypass:
it filters sections by existing permissions, suppresses operational entry when
commercial access is restricted, and exposes `/login` only through Enter TIS
Platform. Operational authentication and request authorization remain separate
authorities.

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
