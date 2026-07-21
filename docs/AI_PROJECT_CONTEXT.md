---
title: TIS AI Project Context
documentation_version: 3.1
last_updated: 2026-07-21
recommended_first_read: true
---

# TIS AI Project Context

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

## Completed M7 Subscription Management

M7 includes a normalized entitlement foundation, a customer Subscription Management portal, paid branch-quantity management, upgrades and scheduled downgrades, Paddle-authoritative previews and proration, scheduled cancellation and reversal, a centralized lifecycle/action policy, provider-sourced billing history, protected invoice downloads, and webhook/reconciliation safeguards.

Commercial state fails closed when ownership, provider evidence, or local relationships are ambiguous. TIS does not independently calculate replacement monetary values. Immediate changes require provider-confirmed outcomes; scheduled changes remain pending until provider/webhook evidence reaches the effective boundary.

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
- Platform Owner Knowledge Center is implemented as a read-only owner utility.
- The Knowledge Center uses protected routes for PDF view/download and does not link directly to static PDF paths.
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
