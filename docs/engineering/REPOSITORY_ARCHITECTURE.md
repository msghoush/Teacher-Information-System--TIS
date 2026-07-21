---
title: TIS Repository Architecture
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Repository Architecture

This document explains the main repository areas, what each owns, and what must not be changed casually.

## Root FastAPI Application

### `main.py`

Responsibility:
Primary FastAPI app, route registration, many app-level workflows, middleware, startup checks, platform console routes, dashboards, exports, system configuration, scope switching, and operational pages.

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
- `scripts/sync_paddle_price_ids.py`: environment-specific initial checkout price mapping.
- `scripts/diagnose_paddle_plan_preview.py` and `scripts/diagnose_payment_lifecycle.py`: safe subscription/payment diagnostics.
- `scripts/reconcile_finalized_payment_lifecycle.py`: guarded sandbox reconciliation from attributable provider evidence.

Do not change casually:
- PDF generator dependency assumptions,
- source list behavior,
- manifest metadata.

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
