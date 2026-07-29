---
title: TIS AI Project Context
documentation_version: 3.1
last_updated: 2026-07-29
recommended_first_read: true
---

# TIS AI Project Context

## Public Subscription Entry

The landing hero Subscribe Now action scrolls to the public pricing section.
Starter, Professional, and Enterprise AI then enter the public TIS Account
signup route with an allowlisted preferred-plan code. That preference is
non-authoritative: it creates no plan selection, checkout, payment attempt, or
Paddle object, and it is applied only after School Workspace Setup confirms the
plan remains eligible across branches, system users, and teachers. Invalid or
undersized preferences are ignored or cleared safely. Custom remains a
contact-only path.

## Three-Dimension Subscription Capacity

Self-service subscription eligibility is organization-wide across three
independent persisted limits: branches, non-teacher system users, and teacher
records. Branch Setup stores required non-negative system-user and teacher
estimates on each active onboarding branch; legacy organization totals are
assigned to the primary branch only when no branch estimates exist, after
which organization totals are derived summaries.

Before confirmed payment, capacity authority is the active onboarding branch
count plus the greater of each branch-estimate total and the same workspace's
actual active count. After activation, actual active tenant system users and
active teacher records are authoritative. Teacher login accounts do not consume
system-user capacity, but their teacher records consume teacher capacity.
Starter is 1/5/25, Professional 5/20/100, and Enterprise AI 25/100/500.
Exceeding any Enterprise AI limit requires the contact-only Custom path and
cannot create Paddle checkout.

## Returning Customer Journey And Commercial Expiry

Returning SaaS-account login resolves authoritative onboarding, demo request,
account-to-workspace, workspace classification, lifecycle, and subscription
evidence. Incomplete onboarding resumes, pending demos open request status,
active demo or paid tenants enter operational login, unpaid customers reach
subscription setup, and expired customers receive branded expiry guidance.
Operational login and protected requests run the commercial guard before
branch, academic-year, or workspace page work; expected expiry never becomes a
500.

Expired demos select real public plans and intervals against the existing
organization and actual active operational branches. Checkout and confirmed
payment reuse the existing Paddle and conversion authorities, preserving the
SchoolGroup, workspace UUID, tenant link, users, branches, permissions, and
data. The Next.js landing derives Request Demo, Subscribe, Sign In, and Open TIS
App from `NEXT_PUBLIC_TIS_APP_BASE_URL`. Customer communications name the TIS
team; internal role names and audit evidence remain unchanged.

## M8B9 Demo Operations And Access Profiles

M8B9 adds Platform Owner-only orchestration in `saas/demo_operations_service.py`
and policy resolution in `saas/demo_access_service.py`. Owners can expire,
reactivate, set an unbounded future expiry, send final-day reminders, invoke
the existing lifecycle processor, and choose Standard, Full, or Custom access
at workspace or tenant-validated branch scope. M8B8 usage history is never
reset; permissions, commercial lifecycle, and feature entitlement remain
separate fail-closed checks. Material changes reuse M8B7 communications and
every attempt is durably audited.

## M8B8 AI Entitlement Foundation

M8B8 centralizes AI access in `saas.ai_entitlement_service`. A controlled
registry owns stable feature identifiers and temporary reviewed plan mapping.
Customer Demo receives two successful uses per feature; pre-execution
reservations block concurrent excess attempts, while failed/no-result work
releases capacity without consuming. Durable counters and operation events are scoped by
SchoolGroup, feature, and separate internal/demo/paid metric context. Existing
tenant resolution, `ai.use` permission, commercial state, demo expiry, and
paid `module.ai` entitlement remain distinct authorities. No AI business tool
or M8B9 operational control is included.

## M8B7 Demo Customer Journey

M8B7 makes normal Platform Owner approval orchestrate the existing independently retryable provisioning service. It adds a durable branded demo email outbox, deduplicated Platform Owner Notification Center events, a shared-shell active-demo indicator, atomic Day 6/expiry communication intents, and coherent expired-demo conversion after authoritative confirmed payment. The same PendingOrganization and then exactly one SchoolGroup are preserved. Production must schedule `python scripts/process_demo_lifecycle.py --apply`; dry-run remains the default. M8B8 and M8B9 are not included.

This is the first file future Codex or ChatGPT coding conversations should load. It is a compact project onboarding reference; detailed source of truth remains in the other Markdown docs.

## What TIS Is

TIS is Teacher Information System, a developing SaaS academic operations platform for schools and school groups. It connects teacher information, staffing and workload planning, academic calendars, observations, branch context, SaaS onboarding, billing, provisioning, and future AI-assisted academic decision support.

Public URLs:

- Public website: `https://tisplatform.com`
- Application portal: `https://app.tisplatform.com`
- Render must set `TIS_PUBLIC_BASE_URL=https://app.tisplatform.com` so transactional emails and background Workspace Activation emails generate production login and static asset URLs instead of local-development fallbacks.

Important routes:

- Operational login: `/login`
- SaaS signup: `/saas/signup`
- SaaS login: `/saas/login`
- SaaS account: `/saas/account`
- Platform console: `/platform`

## Current Architecture

The operational app is a FastAPI application at the repository root.

The FastAPI web process never creates tables or runs pending migrations during
import, startup, middleware, or background threads. Render must run
`python scripts/run_migrations.py` as its Pre-Deploy Command; only after that
command succeeds may Render activate the new web version. The Start Command is
`uvicorn main:app --host 0.0.0.0 --port $PORT`, which constructs the app,
performs only lightweight process-local startup checks, and binds without
PostgreSQL DDL. This boundary applies consistently to production, local
development, and tests.

Key files and folders:

- `main.py`: primary FastAPI app and many route handlers.
- `auth.py`: authentication, roles, platform identity helpers, permissions, sessions.
- `authorization.py`: protected route rules and access-denied handling.
- `permission_registry.py`: permission keys, groups, defaults, and developer-assignable permissions.
- `location_service.py`: global location picker lookup/validation. Must stay memory-conscious and scoped; do not restore full unbounded dataset parsing for normal picker requests.
- `ui_shell.py`: shared app shell/navigation/page metadata.
- `models.py`, `database.py`, `db_migrations.py`: data model, DB setup, local schema repair/migration logic.
- `routers/`: modular operational routes.
- `saas/`: SaaS account, onboarding, payment, billing, and provisioning services/routes.
- `saas/entitlement_service.py`: provider-confirmed commercial entitlement and paid branch-capacity resolution.
- `saas/subscription_portal_service.py`: customer subscription portal view model.
- `saas/subscription_change_service.py`, `saas/subscription_plan_change_service.py`, and `saas/subscription_cancellation_service.py`: provider-authoritative quantity, plan, and cancellation workflows.
- `saas/subscription_lifecycle_service.py`: centralized lifecycle state and allowed-action policy.
- `saas/billing_history_service.py`: provider-sourced billing history and short-lived invoice download resolution.
- `saas/payment_lifecycle_reconciliation_service.py`: guarded reconciliation for attributable finalized payment evidence.
- `scripts/sync_paddle_price_ids.py`: environment-specific Paddle initial checkout price mapping sync into `subscription_plan_prices.provider_price_id`.
- `templates/`: Jinja templates.
- `static/`: static assets and generated documentation output.
- `tests/`: pytest coverage.

The public marketing website is separate:

- `tis-landing-website/`
- Next.js / Node runtime
- Source of truth for public landing implementation
- M8 landing integration exposes two public conversion paths through `NEXT_PUBLIC_TIS_APP_BASE_URL`: Request a Demo routes to `/saas/signup?intent=demo`, while Subscribe Now routes to `/saas/signup?intent=subscribe`.
- The selected intent is preserved through TIS Account signup and School Workspace Setup, then emphasized on the customer-safe commercial-choice page without removing the customer's ability to choose either path.
- Customer demo eligibility is reserved once per normalized organization domain. Existing Customer Demo history, including expired or converted demos, remains ineligible for a second demo; internal sandbox history does not consume customer eligibility.

Legacy FastAPI landing files are not the source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

## Engineering Handbook

For deeper onboarding, read:

- `docs/engineering/README.md`
- `docs/engineering/TIS_MODULE_MAP.md`
- `docs/engineering/REPOSITORY_ARCHITECTURE.md`
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md`
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`
- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md`
- `docs/engineering/PRODUCT_ROADMAP.md`
- `docs/engineering/REJECTED_DECISIONS.md`
- `docs/engineering/VISUAL_DOCUMENTATION_GUIDE.md`
- `docs/engineering/AI_OPTIMIZATION_GUIDE.md`
- `docs/engineering/PROJECT_GOVERNANCE.md`
- `docs/engineering/KNOWLEDGE_LIFECYCLE.md`
- `docs/engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md`
- `docs/engineering/SELF_EVOLVING_WORKFLOW.md`
- `docs/engineering/AI_CODING_WORKFLOW.md`

These files explain module ownership, repository boundaries, end-to-end flows, and what must not be changed casually.

## Paddle Initial Checkout Configuration

Initial subscription checkout uses Paddle price IDs stored in `subscription_plan_prices.provider_price_id`. Use `scripts/sync_paddle_price_ids.py` with a structured sandbox or production mapping JSON to configure these values. Paddle credentials and endpoints remain environment variables. Real mapping files are ignored by Git; keep sandbox and live provider price IDs separate. If a mapping is missing, checkout fails closed before Paddle is called and customers receive a support-oriented Secure Payment message while internal diagnostics keep plan code, billing interval, and currency context.

Paddle transaction checkout uses a dedicated public SaaS payment launcher at `/saas/payment`. Configure `PADDLE_CHECKOUT_BASE_URL` to that page so Paddle returns transaction checkout URLs with `_ptxn` appended to the launcher instead of the operational app root. The launcher uses Paddle.js with `PADDLE_CLIENT_TOKEN` and `PADDLE_ENVIRONMENT`; never expose `PADDLE_API_KEY` in HTML or JavaScript.

## Domains And Routing

The public website lives at `https://tisplatform.com`. The app portal lives at `https://app.tisplatform.com`.

SaaS account routes are under `/saas`. Platform-owner SaaS administration routes are under `/saas-admin`. Operational tenant workflows use routes such as `/dashboard`, `/teachers`, `/subjects`, `/planning`, `/timetable`, `/academic-calendar`, and `/observations`.

## Completed M1-M5 Milestones

M1: SaaS identity foundation and separation between platform, tenant, and SaaS account identities.

M2: SaaS onboarding flow for organization, contacts, branches, academic setup, and review.

M3: Billing and plan foundation with plan catalog, checkout, billing status, and payment service boundaries.

M4: Tenant provisioning foundation with pending organizations, provisioning jobs, retry/run actions, and platform owner oversight.

M5: Platform access and owner controls, including platform owner/developer identities, permissions, and platform console behavior.

Platform Owner pending-organization views use a centralized owner lifecycle projection. The pending queue includes only records still in draft/setup, review, subscription checkout/payment, or incomplete/recoverable workspace activation. An active tenant link plus one coherent confirmed subscription, payment, contract, and active SchoolGroup resolves as Active Tenant and is excluded from pending counts. Completed-provisioning evidence that does not reconcile across those records is excluded from the normal queue and shown as Lifecycle Review Required in retained Organization Records. Historical onboarding fields are not rewritten by this projection.

## Completed M7 Subscription Management

M7 includes a normalized entitlement foundation, a customer Subscription Management portal, paid branch-quantity management, upgrades and scheduled downgrades, Paddle-authoritative previews and proration, scheduled cancellation and reversal, a centralized lifecycle/action policy, provider-sourced billing history, protected invoice downloads, and webhook/reconciliation safeguards.

Commercial state fails closed when ownership, provider evidence, or local relationships are ambiguous. TIS does not independently calculate replacement monetary values. Immediate changes require provider-confirmed outcomes; scheduled changes remain pending until provider/webhook evidence reaches the effective boundary.

## M8B-1 Workspace Classification Foundation

M8B-1 adds metadata-only workspace classification without changing customer behavior. `SchoolGroup` now owns an immutable workspace UUID, classification (`internal_sandbox`, `customer_demo`, or `customer_paid`), and lifecycle (`provisioning`, `active`, `suspended`, or `archived`). `PendingOrganization.workspace_intent`, `SaaSAccount.account_purpose`, and `User.is_internal_test_identity` preserve the corresponding pre-provisioning and identity intent.

All records that predate M8B-1 are confirmed test data. The controlled backfill classifies them as internal sandbox/test records; it is dry-run by default, transactional, idempotent, and records completion in `schema_migrations`. The separate diagnostic is read-only and reports tenant, onboarding, and Paddle relationship presence without exposing provider identifiers or secrets. Platform Owners can inspect workspace UUID, classification, and lifecycle in `/platform`; Platform Developers and tenant users do not receive that metadata block.

M8B-1 does not use classification for billing, entitlements, permissions, tenant isolation, reset eligibility, or customer routing. Demo workflows, conversions, Al-Andalus migration, memberships, and commercial-state resolution remain later work.

## M8B-2 Commercial State And Entitlement Foundation

M8B-2 adds a read-only commercial decision layer without changing customer access or billing behavior. `WorkspaceEntitlement` is the workspace-level entitlement envelope, `WorkspaceEntitlementValue` reuses the existing normalized entitlement catalog for features and limits, and `BranchEntitlement` optionally records whether a branch inherits, is explicitly active, or is commercially inactive.

The commercial resolver combines persisted workspace classification/lifecycle metadata with one coherent effective workspace entitlement. Customer-paid workspaces additionally require the existing M7 confirmed subscription entitlement resolution and matching `PaymentSubscription`; M8B-2 does not calculate billing state or contact Paddle. Missing, ambiguous, cross-tenant, orphaned, or invalid relationships fail closed to manual review.

These results are visible only to Platform Owners in `/platform`. They are not wired into tenant authorization, feature restrictions, branch behavior, onboarding, Paddle, demo expiration, or customer workflows. Internal sandbox workspaces created outside the migration retain a compatibility-only implicit entitlement so existing development flows remain unchanged.

## M8B-3 Demo Request Workflow

M8B-3 adds the first customer-facing commercial choice after completed onboarding: Request Demo or Subscribe Now. Subscribe Now continues into the existing plan-selection and Paddle workflow unchanged. Request Demo validates the verified account and completed organization, contact, academic, and branch setup before creating a `SaaSDemoRequest` in Pending Review.

The request records the requester, pending organization, submission time, customer-demo classification intent, provisioning commercial-state snapshot, and a fail-closed pre-provisioning entitlement snapshot. It does not create a SchoolGroup, workspace entitlement, subscription, checkout, or Paddle record. The workflow is separate from the legacy public marketing `DemoRequest` lead table.

Platform Owners have a searchable and sortable review queue. Approval records a review decision only; rejection requires a reason; owner cancellation and customer withdrawal are limited to Pending Review. Every transition creates durable audit and internal-notification events, but M8B-3 sends no email and performs no demo provisioning or activation.

## M8B-4 Demo Workspace Provisioning And Activation

M8B-4 adds a Platform Owner-only provisioning action for an approved SaaS demo request. The service fails closed unless the approval review, organization, customer-demo intent, pre-provisioning commercial snapshot, and entitlement snapshot remain coherent and no workspace has already been provisioned.

Demo provisioning reuses the paid provisioning engine's shared workspace-record builder for the SchoolGroup, branches, academic year, owner user, account link, role permissions, and branding. It creates no Paddle, payment, subscription-contract, payment-subscription, checkout, or billing record. A demo-backed `TenantProvisioningLink` identifies the operational tenant without fabricating a paid contract.

Workspace records, the demo entitlement, tenant link, request linkage, and activation are committed atomically. A failed attempt rolls the workspace changes back, leaves the request Approved and unprovisioned, and records a retryable failure outcome. Successful activation sets the SchoolGroup and demo entitlement active, records activation metadata and audit/internal events, and prevents duplicate provisioning. M8B-4 sends no email and implements no expiration, scheduler, login restriction, or conversion behavior.

## M8B-5 Standard Customer Demo Lifecycle

Every customer-demo workspace lasts exactly seven days from the M8B-4 `activated_at` timestamp. Day 6 reminder and Day 7 expiration timestamps are derived from that single authority, calculated with timezone-aware UTC values, and displayed in the onboarding organization's IANA timezone. Missing or inconsistent timestamps fail closed.

`saas.demo_lifecycle_service` is the authoritative read-only resolver and independently callable processor. It resolves Active, Reminder Due, Expired, Suspended, or Manual Review; creates idempotent internal Day 6 notifications for the requesting SaaS account and active Platform Owners; and atomically ends the demo entitlement and suspends the SchoolGroup at expiration. Workspace users, branches, and all tenant data remain preserved.

The operational authentication middleware checks customer-demo commercial access on every protected request, including existing sessions. Active and reminder-due demos continue normally. Expired or ambiguous demos are redirected to the subscription activation experience, while protected API/download requests receive a customer-safe 403. Platform users, paid workspaces, internal sandboxes, public/authentication routes, secure logout, and SaaS subscription routes are unaffected. Access-block auditing is deduplicated.

Run the lifecycle processor safely with `python scripts/process_demo_lifecycle.py --dry-run`; use `--apply` only for scheduled execution after validating the report. M8B-5 sends no email and adds no extension, conversion, archive, deletion, or read-only expired mode.

## M8B-6 Demo-To-Paid Conversion

An active Customer Demo may enter the existing subscription checkout without closing or recreating its operational tenant. After `transaction.completed` establishes one confirmed active M7 subscription for the same pending organization, `saas.demo_conversion_service` atomically converts the existing SchoolGroup from `customer_demo` to `customer_paid`.

The conversion preserves the workspace UUID, SchoolGroup, tenant link row, organization, branches, users, permissions, academic data, and all demo/request/audit history. It ends the demo entitlement, creates a paid entitlement linked to the confirmed `PaymentSubscription`, moves branch entitlement links, and replaces the tenant link's demo source with the confirmed `SubscriptionContract`. Existing M7, workspace-entitlement, and commercial-state resolvers must then resolve the same tenant as Customer Paid Active.

Conversion Requested, Processing, Completed, and Failed states are durable and retryable. Any conversion failure rolls back workspace mutations while retaining confirmed provider payment records. Expired, invalid, ambiguous, cross-tenant, internal-sandbox, paid, or already-converted workspaces fail closed. Completed conversions no longer enter demo reminder or expiration processing.

## Test Workspace Reset Dependency Rule

The Platform Owner-only test workspace reset keeps its existing preflight and single-transaction rollback behavior. Before it deletes scoped operational `User` records, it deletes `SubscriptionChangeRequest` rows scoped by the selected workspace's authoritative `school_group_id`. It also deletes selected workspace-entitlement values and branch-entitlement children before the selected `WorkspaceEntitlement`, which is removed before the final `SchoolGroup`. This prevents user, account, contract, subscription, and entitlement foreign-key references from blocking removal while preserving records belonging to every other workspace. Pre-analysis and structured deletion diagnostics report the same scoped record set.

The same Platform Owner-only test reset is a clean-room exception for internal M8 testing only. Within its existing single transaction, it deletes the selected pending organization's linked demo request, domain-eligibility reservation, review and audit history, demo provisioning/lifecycle records, and demo-to-paid conversion history before removing their parents. It also resolves the selected organization's domain through the same customer-demo resolver and may remove a detached reservation only when no other organization, request, workspace, or customer account uses that domain and the reservation has no historical manual-review evidence. Analysis exposes a separate list of safe detached reservation IDs; deletion consumes that exact list, flushes before parent deletion, and verifies that none of those IDs remain. A mismatch, remaining row, conflicting ownership, or historical ambiguity blocks or rolls back the reset. This allows the same test email and organization domain to complete a new internal journey after a reset. The normal customer one-demo-per-domain reservation policy is unchanged; global plans, prices, Paddle records, platform configuration, and records from other organizations remain preserved.

Historical detached demo-domain reservations whose owning organization and account were already removed are managed separately through the Platform Owner-only `/saas-admin/demo-eligibility-maintenance` workflow. It scans eligibility rows, reuses the authoritative domain normalization/resolution rules, and fails closed when any matching organization, account, request, tenant-profile workspace, provisioning record, subscription evidence, conversion, or manual-review marker remains. A confirmed deletion locks and re-analyzes one exact eligibility ID, deletes only that ID, flushes, verifies absence, and commits through the owner route. Durable audit records identify the owner, eligibility ID, domain, previous status, timestamp, and maintenance reason. This administrative repair path does not alter normal Customer Demo eligibility or the clean-room reset.

## Current SaaS Account Verification State

Phase 1 TIS Account email verification recovery is accepted. Valid verification links now mark the SaaS account email verified/active and redirect to the TIS Account login page with a professional success notice so the customer can continue school workspace setup.

Expired or invalid verification links no longer dead-end. They show a recovery page with a resend verification form. Resend verification handles unverified accounts, already verified accounts, and unknown email addresses with safe customer-facing messaging that does not reveal account existence. Password-based accounts that remain unverified are blocked from starting or continuing school workspace setup.

This Phase 1 verification recovery work did not change payment, billing, provisioning, database schema, migrations, operational modules, or the Next.js landing website. Google/Microsoft login remains future work and was not implemented.

## Current SaaS Customer-Facing Language State

Phase 2 TIS Account wording cleanup is accepted for customer-facing account and school workspace setup pages. Customer-visible account/setup pages now avoid presenting "SaaS" and technical identifiers as product language, while internal `/saas` routes, modules, models, and stored statuses remain unchanged.

The customer journey should use professional labels such as "TIS Account", "Account Dashboard", "School Workspace Setup", "Organization Profile", "Branch Setup", "Academic Setup", "Subscription Setup", "Secure Payment", and "Workspace Activation". Customer templates should label internal billing, payment, onboarding, and activation statuses through customer-safe display labels instead of raw database statuses such as `tenant_active`, provisioning states, checkout session states, provider identifiers, plan IDs, school group IDs, attempt UUIDs, or provider subscription/transaction IDs.

The shared TIS Account customer shell uses an official TIS logo image so customer account/setup forms inherit official branding. The light account shell uses the full-color horizontal logo variant, and transactional account emails use an existing official dark-blue wordmark asset. This wording/logo pass did not change payment, billing, provisioning behavior, database schema, migrations, operational modules, or the Next.js landing website. Google/Microsoft login remains future work and was not implemented.

## Current TIS Account Guided Setup Framework State

Phase 3A shared guided setup framework is accepted for the TIS Account dashboard only. The customer account shell now supports a shared setup console with the official TIS logo, an 8-step journey stepper, a current-step/status area, one primary next action, and concise guidance. The account page uses this framework to answer "What should I do next?" without dashboard statistics.

The 8 customer-facing journey steps are TIS Account, Email Verification, School Workspace Setup, Review & Confirmation, Subscription Selection, Secure Payment, Workspace Activation, and Enter TIS Platform. The display state is calculated from existing account, onboarding, billing, payment, and activation data without changing stored statuses.

This Phase 3A work did not redesign onboarding forms, subscription/payment pages, or billing/status pages. It did not change payment, billing, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, or admin views.

Phase 3B redesigned the five School Workspace Setup onboarding pages on top of the Phase 3A shared shell: Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup. The pages now use consistent guided-wizard sections, a single shared-shell primary CTA, secondary Back/Save Draft actions, concise guidance, and lower visual clutter while preserving all existing form actions, field names, validation behavior, draft behavior, and onboarding state transitions.

Phase 3B did not redesign subscription/payment/billing/status pages and did not change payment, billing, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, or admin views.

Phase 3C redesigned the customer-facing Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages on top of the Phase 3A shared shell and Phase 3B guided style. These pages now use one shared-shell primary CTA, customer-safe payment/activation labels, clearer browser-return messaging, and explicit guidance that TIS Platform access becomes available after Workspace Activation.

Phase 3C did not change payment behavior, billing behavior, provisioning behavior, webhook logic, checkout start/launch behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, stored statuses, or admin views.

## Current Priority

Current priority is automatic KMS synchronization enforcement and reliable post-M7 engineering context:

- Markdown is source of truth.
- PDF is generated snapshot.
- Change history preserves chronological change context.
- ADRs preserve major decisions.
- Module history preserves deeper area-specific evolution.
- Platform Owner Knowledge Center is implemented as a read-only owner utility with manifest-backed document titles, summaries, logical groups, client-side search, category/module/freshness filters, and latest-activity ordering.
- The Knowledge Center uses protected routes for PDF view/download and source-specific `pdf_page` deep links; it does not link directly to static PDF paths.
- KMS v3.0 Phase 3A adds a true engineering handbook with module map, repository architecture, workflows, and developer onboarding.
- KMS v3.0 Phase 3B adds database architecture, development standards, UI/UX philosophy, product roadmap, and stronger human/AI developer guidance.
- KMS v3.0 Phase 3C adds rejected decisions, visual documentation framework, AI optimization guidance, project governance, and decision traceability.
- KMS v3.0 Phase 3D completes KMS v1.0 lifecycle standards, dependency mapping, AI coding workflow, and future automation roadmap.
- Root `AGENTS.md` makes KMS onboarding mandatory for Codex tasks.
- `.kms-impact.yml` is the machine-readable task declaration.
- `scripts/kms.py sync` is the single local synchronization command; it validates KIA before writing, regenerates the PDF/manifest, then verifies freshness.
- `scripts/kms.py check` is the single read-only local and CI validation command.
- `scripts/check_kms_impact.py` validates major-change classification, declared Markdown updates, and generated-artifact freshness.
- GitHub Actions block pull-request integration and production deployment when KMS validation fails.

## Critical Rules

- Do not touch SaaS flows unless explicitly approved.
- Do not touch operational logic unless required by the approved task.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not weaken tenant isolation.
- Do not bypass permissions or platform owner checks.
- Do not merge platform user, SaaS account, and tenant user concepts.
- Do not change landing page implementation unless explicitly approved.
- Do not add a KMS regenerate button until explicitly approved.
- Do not push or commit unless explicitly requested.
- Treat production memory as a hard budget. Do not add unbounded full-dataset caches, duplicate production template renders, startup-heavy work, or warning-level debug spam on normal requests.

## KMS Policy

Every implementation must include a Knowledge Impact Assessment:

```md
Knowledge impact: Yes/No
Docs updated:
Change history updated: Yes/No
ADR needed: Yes/No
Module history updated: Yes/No
PDF regenerated: Yes/No
AI project context updated: Yes/No
Reason if not updated:
```

If included docs change, synchronize:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py sync
```

## Development Workflow

1. Read this file first.
2. Read root `AGENTS.md`, `docs/TIS_MASTER_CONTEXT.md`, and `docs/PROJECT_STATE.md`.
3. Read `docs/engineering/README.md`.
4. Read `docs/engineering/DEVELOPMENT_STANDARDS.md`.
5. Read `docs/engineering/AI_OPTIMIZATION_GUIDE.md`.
6. Read `docs/engineering/AI_CODING_WORKFLOW.md`.
7. Read relevant engineering docs, ADRs, module history, and supporting docs.
8. Inspect code before editing.
9. Keep changes scoped.
10. Update `.kms-impact.yml` and affected KMS docs when meaningful behavior, architecture, product state, module map, repository ownership, data model, design philosophy, roadmap, governance, decision traceability, automation, lifecycle, or workflow changes.
11. Run `scripts/kms.py sync` if included source docs changed.
12. Run `scripts/kms.py check` for final read-only validation.
13. Run implementation validation.
14. Report KIA in final response.

## Landing Page Situation

The public landing implementation is in `tis-landing-website/`. Marketing docs live under `docs/marketing/`. Do not modify legacy FastAPI landing files unless explicitly approved.

## Next Planned Work

Review the automatic KMS enforcement baseline, keep M7 subscription documentation synchronized as follow-up fixes evolve, and later consider an explicit owner-only regenerate action. Any regenerate action may rebuild artifacts from reviewed Markdown only and must not rewrite source prose.
