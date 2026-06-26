---
title: TIS Master Context
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Master Context

Documentation version: 3.0

Last major context update: 2026-06-26

## Product Identity

TIS stands for Teacher Information System. It is a developing SaaS academic operations platform for schools, school groups, academic leaders, supervisors, and platform owners who need one trusted place for academic staffing, teacher records, planning, calendars, observations, branch context, and future intelligence.

TIS is not only a teacher directory. It is intended to become the operational backbone for academic decision-making across a school or multi-branch organization.

Public product presence:

- Public website: `https://tisplatform.com`
- Application portal: `https://app.tisplatform.com`
- Operational login: `/login`
- SaaS signup: `/saas/signup`
- SaaS login: `/saas/login`
- SaaS account area: `/saas/account`

## Product Vision

TIS helps schools move away from scattered spreadsheets and disconnected operational files. The product vision is to give academic leaders a structured, secure, and tenant-isolated platform where teacher information, teaching loads, staffing needs, observations, calendars, and branch-level context can be managed together.

As the platform matures, TIS should also become the trusted data foundation for AI-assisted academic operations. Future AI features should depend on verified school data, clear permissions, and careful subscription packaging.

## Business Goal

The business goal is to establish TIS as a subscription-based SaaS platform for academic operations. The platform should support school onboarding, plan selection, payment, provisioning, account management, and scalable multi-tenant usage.

Near-term business priorities:

- Convert interested schools from public landing page traffic into SaaS accounts.
- Support clear onboarding from signup through school setup.
- Provide reliable billing and payment status visibility.
- Enable platform owners to manage pending organizations and provisioning.
- Preserve trust by keeping tenant data isolated and operational flows stable.

## Educational Goal

The educational goal is to reduce administrative friction so schools can make better academic decisions. TIS should help leadership teams identify staffing gaps, workload problems, incomplete academic coverage, observation follow-up needs, and calendar conflicts earlier.

The platform should support educational quality by making academic operations easier to see, review, and improve.

## Target Customers

Primary customers:

- Private schools
- Multi-branch school groups
- Academic leadership teams
- Principals and vice principals
- Department heads and supervisors
- School operations and HR-adjacent academic staff

Internal platform users:

- Platform Owner
- Platform Co-Owner
- Platform Developer

Tenant users:

- Administrators
- Coordinators
- Supervisors
- Teachers and academic staff, depending on enabled workflows

## FastAPI App Architecture

The operational TIS application is a FastAPI application at the repository root. It uses Python, SQLAlchemy, Jinja templates, static assets, and modular routers.

Core app areas:

- `main.py`: primary FastAPI app, route registration, app-level workflows, startup checks, platform console routes, dashboard and configuration flows.
- `models.py`: main SQLAlchemy models.
- `database.py`: database connection/session setup.
- `db_migrations.py`: local schema migration and repair logic.
- `auth.py`: authentication, role normalization, platform identity helpers, permission helpers, session handling.
- `authorization.py`: route permission rules and access-denied response helpers.
- `permission_registry.py`: permission groups, labels, defaults, developer-assignable permissions, and system owner permissions.
- `role_permission_service.py`: role permission persistence and related helpers.
- `ui_shell.py`: shared application shell context, navigation, visual identity, and page metadata.
- `routers/`: modular feature routers for users, teachers, subjects, planning, timetable, academic calendar, and observations.
- `templates/`: Jinja templates for the operational app and SaaS app pages.
- `static/`: CSS, JavaScript, images, branding assets, and generated public artifacts.
- `tests/`: pytest coverage for tenant isolation, SaaS phases, platform access, permissions, email, branding, and related workflows.

Important operational route families:

- `/login`: operational app login.
- `/dashboard`: tenant operational dashboard.
- `/platform`: platform console for platform identities.
- `/system-configuration`: branch, year, branding, role permissions, and configuration workflows.
- `/teachers`, `/subjects`, `/planning`, `/timetable`, `/academic-calendar`, `/observations`: core academic operations.

## Next.js Landing Architecture

The public marketing website lives in `tis-landing-website/`. It is separate from the FastAPI operational portal.

Landing architecture:

- Runtime: Next.js / Node.
- Public website domain: `https://tisplatform.com`.
- Local development URL: `http://localhost:3000`.
- Main page: `tis-landing-website/src/app/page.tsx`.
- App layout: `tis-landing-website/src/app/layout.tsx`.
- Global styles: `tis-landing-website/src/app/globals.css`.
- Logo component: `tis-landing-website/src/components/tis-logo.tsx`.
- Public assets: `tis-landing-website/public/`.

The application portal remains separate:

- App domain: `https://app.tisplatform.com`.
- Runtime: FastAPI / Python with a relational database.

Legacy landing files in the FastAPI app are not the source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

Those legacy files must not be modified unless explicitly approved.

## Multi-Tenant SaaS Strategy

TIS is designed as a multi-tenant SaaS platform. Tenant isolation is a critical rule. School groups, branches, users, academic years, teachers, planning data, timetable data, observations, and configuration records must remain scoped to the correct organization and branch context.

The platform distinguishes between:

- Platform identities: platform owners, co-owners, and developers.
- Tenant identities: users belonging to a school group and branch context.
- SaaS account identities: accounts that move through signup, onboarding, billing, and provisioning.

Platform users may inspect or switch organization context through controlled platform workflows. Tenant users must remain inside their authorized school, branch, academic year, and permission scope.

Critical tenant strategy:

- Do not weaken tenant isolation.
- Do not bypass permission checks.
- Do not assume a platform identity is a tenant identity.
- Do not assume a SaaS account is already provisioned into an operational tenant.
- Keep onboarding, billing, and tenant provisioning as distinct stages.

## SaaS Routes And Account Experience

Core SaaS routes:

- `/saas/signup`: public SaaS account creation.
- `/saas/login`: SaaS account login.
- `/saas/account`: SaaS account dashboard.

Related SaaS areas include plan selection, onboarding organization details, contacts, branch setup, academic setup, onboarding review, billing status, checkout summary, checkout return, checkout cancel, sessions, security, and profile pages.

Platform owner SaaS administration exists under `/saas-admin` for pending organizations, payments, and provisioning workflows.

## M1-M5 Completed Milestone Summary

M1: Identity and SaaS foundation

- Established core SaaS account concepts.
- Added initial signup/login/account flows.
- Clarified separation between platform, tenant, and SaaS account identities.
- Added supporting tests for identity and SaaS phase behavior.

M2: Onboarding foundation

- Added structured onboarding stages for organization information, contacts, branches, academic setup, and review.
- Improved the path from SaaS signup toward a provisionable organization.
- Preserved the distinction between pending SaaS organizations and operational tenants.

M3: Billing and plan foundation

- Added pricing, plan catalog, billing status, checkout summary, return, and cancel flows.
- Created billing/payment service modules to keep payment logic separate from operational academic logic.
- Prepared the platform for subscription-based SaaS packaging.

M4: Provisioning foundation

- Added pending organization and provisioning workflows for platform owners.
- Added provisioning queue concepts and retry/run operations.
- Created a controlled path for turning a pending SaaS organization into an operational school context.

M5: Platform access, permissions, and owner controls

- Strengthened platform identity handling.
- Added platform owner/developer concepts and owner management controls.
- Improved permission boundaries for platform and tenant users.
- Added tests around platform access and role permissions.

## Paddle And Payment Architecture Summary

The payment architecture is organized under the `saas/` package.

Key modules:

- `saas/pricing_service.py`: plan/pricing behavior.
- `saas/payment_service.py`: payment-related service logic.
- `saas/paddle_client.py`: Paddle integration boundary.
- `saas/billing_service.py`: billing status and related account billing behavior.
- `saas/currency_service.py`: currency-related helpers.
- `saas/router.py`: SaaS and SaaS admin routes.

Architecture rules:

- Keep Paddle-specific details behind service/client boundaries.
- Do not mix payment logic into academic operations.
- Treat payment status, onboarding status, and provisioning status as related but separate concepts.
- Use platform owner admin views for payment/provisioning oversight.
- Avoid changing live SaaS payment flows unless the task explicitly requires it.

## Tenant Provisioning Summary

Tenant provisioning turns a pending SaaS organization into an operational TIS school context. Provisioning should create or connect the required organization records, branches, users, and initial tenant setup while preserving auditability and data isolation.

Key provisioning concepts:

- Pending organization: SaaS onboarding entity not yet fully operational.
- Provisioning job: controlled action to create or update operational tenant structures.
- Platform owner review: human oversight before or during provisioning.
- Retry behavior: failed provisioning work should be recoverable without corrupting tenant data.

Provisioning rules:

- Do not directly create operational tenant data from public signup without the approved provisioning path.
- Keep provisioning idempotent where possible.
- Log or surface errors clearly.
- Do not merge tenant data across school groups.

## Landing Page Strategy

The public landing page exists to explain the product, build trust, capture demand, and route interested schools into SaaS signup or demo request flows.

Source of truth:

- The public website implementation is `tis-landing-website/`.
- Marketing content references live in `docs/marketing/`.

Landing priorities:

- Explain the problem of scattered academic operations.
- Present TIS as a connected academic operations platform.
- Show credible platform capabilities.
- Support early access, demo requests, and signup pathways.
- Keep the landing page separate from operational app templates.

Landing rule:

- Do not change landing page design, copy, or architecture during operational backend tasks unless explicitly approved.

## Customer Experience Roadmap

Near-term customer experience:

- Clear signup and login path.
- Smooth onboarding for organization, contacts, branches, and academic setup.
- Transparent billing/plan status.
- Clear provisioning status after checkout or owner review.
- Reliable operational login once provisioned.

Medium-term customer experience:

- Better account self-service.
- Clearer subscription lifecycle.
- More guided onboarding and implementation support.
- Improved platform owner visibility into pending organizations and payment status.

Long-term customer experience:

- AI-assisted academic planning and decision support.
- Subscription-gated advanced analytics.
- Intelligent recommendations based on verified tenant data.
- Richer executive visibility across branches and academic years.

## Knowledge Management System

TIS uses a Knowledge Management System (KMS) to preserve source-of-truth documentation, current project state, decision history, module history, and generated snapshots.

KMS source documents:

- `docs/AI_PROJECT_CONTEXT.md`: first-read compact onboarding context for future Codex and ChatGPT conversations.
- `docs/TIS_MASTER_CONTEXT.md`: durable product, architecture, workflow, roadmap, and critical rules.
- `docs/PROJECT_STATE.md`: living project state.
- `docs/DOCUMENTATION_UPDATE_POLICY.md`: mandatory KMS and Knowledge Impact Assessment rules.
- `docs/CHANGE_HISTORY.md`: chronological summary of meaningful changes.
- `docs/adr/`: Architecture Decision Records.
- `docs/history/`: module-specific history.
- `docs/engineering/`: engineering handbook with module map, repository architecture, user/system flows, and developer onboarding.

PDF philosophy:

- Markdown files are the source of truth.
- The PDF booklet is a generated snapshot.
- The PDF must never be edited manually.
- The PDF must be regenerated when included Markdown source docs change.
- The PDF should later be served through owner-only protected routes.

Generated KMS artifacts:

- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Owner-only app access:

- `/platform/knowledge`: read-only Platform Owner Knowledge Center.
- `/platform/knowledge/booklet`: protected inline PDF view.
- `/platform/knowledge/booklet/download`: protected PDF download.

The Knowledge Center is protected by the existing Platform Owner access pattern. It is not public, not a landing page, and does not regenerate or rewrite source docs.

Engineering handbook:

- `docs/engineering/TIS_MODULE_MAP.md` maps product/system modules and guardrails.
- `docs/engineering/REPOSITORY_ARCHITECTURE.md` explains repository ownership and risky files.
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md` documents end-to-end customer, SaaS, payment, provisioning, operational, platform owner, KMS, and developer flows.
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md` explains data areas, ownership boundaries, and tenant isolation rules.
- `docs/engineering/DEVELOPMENT_STANDARDS.md` defines non-negotiable engineering rules.
- `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md` defines design direction for operational, platform, SaaS, Knowledge Center, and landing surfaces.
- `docs/engineering/PRODUCT_ROADMAP.md` records completed, current, next, and future roadmap.
- `docs/engineering/REJECTED_DECISIONS.md` records significant rejected alternatives.
- `docs/engineering/VISUAL_DOCUMENTATION_GUIDE.md` defines future visual documentation standards.
- `docs/engineering/AI_OPTIMIZATION_GUIDE.md` guides future AI assistants.
- `docs/engineering/PROJECT_GOVERNANCE.md` defines ownership, approvals, quality gates, documentation gates, and traceability.

## Development Workflow

Default workflow for approved implementation tasks:

1. Inspect the relevant code and docs before editing.
2. Keep changes scoped to the approved task.
3. Preserve tenant isolation, permission checks, SaaS flows, and landing page boundaries.
4. Update tests or add focused tests when behavior changes.
5. Complete the Knowledge Impact Assessment.
6. Update relevant Markdown docs.
7. Update change history, ADRs, module history, and AI project context when needed.
8. Regenerate the documentation PDF if included docs changed.
9. Run reasonable validation.
10. Report code changes, docs changes, KIA, validation, assumptions, and known issues.

## Knowledge Impact Assessment Rule

Every approved implementation must:

1. Assess knowledge impact.
2. Update relevant Markdown docs.
3. Update `docs/CHANGE_HISTORY.md` for meaningful changes.
4. Create or update ADRs when major decisions change.
5. Update module history when a module's documented state changes.
6. Update `docs/AI_PROJECT_CONTEXT.md` when high-level AI onboarding context changes.
7. Regenerate the PDF booklet if included docs changed.
8. Mention KIA details in the final report.

A task is not complete until the KIA is assessed.

Required final report KIA template:

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

The generated booklet output is:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

## Critical Rules Codex Must Follow

- Do not touch SaaS flows unless the task explicitly requires it.
- Do not touch operational logic unless the approved task requires it.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not weaken tenant isolation.
- Do not bypass route permissions or platform owner checks.
- Do not merge platform user, SaaS account, and tenant user concepts.
- Do not change the landing page design or legacy landing files unless explicitly approved.
- Do not add KMS regenerate behavior unless explicitly approved.
- Do not expose the KMS PDF through direct public static links in the app UI.
- Do not push or commit unless explicitly requested.
- Prefer conservative, dependency-light automation.
- Use `reportlab` for the documentation PDF generator.
- Do not require LaTeX, Playwright, Chromium, external network calls, or system font dependencies for PDF generation.
- Always include a Knowledge Impact Assessment in implementation final reports.
