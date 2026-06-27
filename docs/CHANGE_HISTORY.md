---
title: TIS Change History
documentation_version: 3.0
last_updated: 2026-06-27
source_of_truth: true
---

# TIS Change History

This file is the chronological summary of meaningful TIS changes. It does not replace module history under `docs/history/`; it gives reviewers, developers, Codex, and ChatGPT a fast timeline of what changed and why.

Newest entries should be added first.

## Entry Template

```md
## YYYY-MM-DD - Short Change Title

Area/module:
Previous state:
New state:
Reason:
Files changed:
Documentation updated:
PDF regenerated:
AI project context updated:
Reviewer/approval notes:
```

## 2026-06-27 - Accepted TIS Account Guided Setup Framework Phase 3A

Area/module:
TIS Account customer dashboard, shared SaaS customer shell, setup journey display helper, and KMS documentation

Previous state:
The customer account page still behaved like a dense dashboard with statistics, session details, multiple competing actions, and page-specific journey fragments. The shared customer shell had a logo and onboarding-specific progress UI, but it did not yet provide a reusable 8-step guided setup framework.

New state:
The shared customer shell supports a guided setup console for pages that pass setup context. The TIS Account page now presents an official-logo guided console with an 8-step journey stepper, current-step/status area, one primary next action, concise account/workspace context, and guidance that TIS Platform access becomes available after Workspace Activation. Journey state is calculated from existing account, onboarding, billing, payment, and activation data without changing stored statuses.

Reason:
The accepted Phase 3A scope required only the shared framework and account page foundation for a professional TIS Account / School Workspace Setup experience, while leaving full onboarding and payment page redesigns for later phases.

Files changed:
- `saas/router.py`
- `saas/service.py`
- `templates/saas/base.html`
- `templates/saas/account.html`
- `tests/test_saas_phase1.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 3A shared framework only. Onboarding forms, subscription/payment pages, billing/status pages, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, admin views, commits, and pushes were not changed.

## 2026-06-27 - Accepted TIS Account Customer-Facing Wording And Logo Cleanup

Area/module:
SaaS customer account pages, school workspace setup pages, billing/subscription status views, transactional account emails, and KMS documentation

Previous state:
Customer-facing TIS Account and school workspace setup pages could display internal or technical language such as SaaS-oriented product copy, raw status labels, checkout/payment internals, provider identifiers, tenant/provisioning terms, or account setup labels that were less polished. The shared customer account shell did not consistently present an official TIS logo image across inherited customer forms/pages.

New state:
Customer-facing account/setup pages use professional labels such as TIS Account, Account Dashboard, School Workspace Setup, Organization Profile, Branch Setup, Academic Setup, Subscription Setup, Secure Payment, and Workspace Activation. Customer views use display labels for internal statuses and hide customer-irrelevant provider transaction/subscription IDs, attempt UUIDs, checkout session internals, plan IDs, and school group IDs. The shared customer account shell uses the official full-color horizontal TIS logo, and transactional TIS Account emails use an existing official dark-blue TIS wordmark asset.

Reason:
The accepted Phase 2 plan required a focused customer-facing wording cleanup and official logo usage pass before any larger account setup UI redesign.

Files changed:
- `saas/router.py`
- `saas/service.py`
- `saas/provisioning_service.py`
- `email_templates.py`
- `templates/saas/base.html`
- `templates/saas/signup.html`
- `templates/saas/login.html`
- `templates/saas/account.html`
- `templates/saas/account_billing.html`
- `templates/saas/billing_status.html`
- `templates/saas/onboarding_organization.html`
- `templates/saas/onboarding_branches.html`
- `templates/saas/onboarding_academic_setup.html`
- `templates/saas/onboarding_contacts.html`
- `templates/saas/onboarding_review.html`
- `templates/saas/plan_selection.html`
- `templates/saas/checkout_summary.html`
- `templates/saas/checkout_return.html`
- `templates/saas/checkout_cancel.html`
- `templates/saas/profile.html`
- `templates/saas/security.html`
- `templates/saas/sessions.html`
- `tests/test_saas_phase1.py`
- `tests/test_saas_phase5.py`
- `tests/test_email_templates.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 2 implementation only. No Phase 3 UI redesign, Google/Microsoft login, internal route/module rename, payment behavior change, billing behavior change, provisioning behavior change, database schema change, migration change, operational module change, Next.js landing website change, commit, or push was performed.

## 2026-06-27 - Accepted TIS Account Email Verification Recovery

Area/module:
SaaS onboarding, TIS Account email verification, verification resend recovery, and school workspace setup gate

Previous state:
Valid verification links rendered a static verification page instead of continuing the customer toward account setup. Expired or invalid verification links could feel like a dead end. Resend verification existed but did not provide a fully professional recovery path for expired links, already verified accounts, and unknown emails. Password-based accounts that were still pending verification could sign in and reach account/setup routes.

New state:
Valid verification links mark the account email verified/active and redirect to the TIS Account login page with a professional success notice. Expired or invalid links show a recovery page with a resend option. Resend verification safely handles unverified accounts, already verified accounts, and unknown-email cases without revealing account existence. Unverified password-based accounts are blocked from starting or continuing school workspace setup. New visible wording in this verification flow uses "TIS Account" and "school workspace setup".

Reason:
Testing showed that the customer account setup journey could be blocked after email verification, especially when a verification link expired or the customer needed to recover/resend the link.

Files changed:
- `saas/router.py`
- `saas/service.py`
- `templates/saas/login.html`
- `templates/saas/verify_email.html`
- `templates/saas/verification_sent.html`
- `email_templates.py`
- `tests/test_saas_phase1.py`
- `tests/test_saas_phase5.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 1 verification recovery implementation accepted. Phase 2 wording cleanup, Phase 3 setup UI redesign, Google/Microsoft login, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, and the Next.js landing website were not changed. No commit or push was performed.

## 2026-06-27 - Added Production Memory Stability Guardrails

Area/module:
Operational app stability, observations, global location lookup, Render deployment constraints, and engineering standards

Previous state:
Production traffic could hit avoidable memory pressure. The observations page included diagnostic stage logging and extra template rendering in the normal request path, and the global location picker could parse a 47 MB reference dataset into a complete in-memory index for simple picker requests. KMS standards did not yet explicitly forbid unbounded caches, duplicate production template renders, or normal-request diagnostic warning spam.

New state:
The local stabilization patch gates observation diagnostics behind `TIS_OBSERVATION_DIAGNOSTICS`, removes duplicate observation template pre-renders, and changes location lookup behavior to use streaming/scoped country loading for normal country, region, city, and validation requests. KMS now documents strict production memory and Render stability rules.

Reason:
Render logs showed app restarts and user-facing 502s around normal app navigation after deployment. A 512 MB service can be enough for TIS only if the app avoids unnecessary full-dataset memory loads, duplicate rendering, and production debug noise.

Files changed:
- `location_service.py`
- `routers/observations.py`
- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/PROJECT_STATE.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/engineering-handbook/2026-06-27-production-memory-stability-guardrails.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Local changes only. No commit, push, migration, database change, SaaS route change, billing change, tenant logic change, or deployment was performed.

## 2026-06-26 - Completed KMS v3.0 Phase 3D Lifecycle Foundation

Area/module:
Knowledge Management System and engineering handbook

Previous state:
KMS v3.0 Phase 3C documented rejected decisions, visual documentation framework, AI optimization, governance, and traceability. It still needed a complete self-evolving lifecycle standard that ties implementation, validation, KIA, documentation updates, generated artifacts, review, commit, push, and deployment together.

New state:
TIS now has final Phase 3D docs for knowledge lifecycle, documentation automation, KIA standard, self-evolving workflow, documentation dependency map, AI coding workflow, and future automation roadmap. This completes the KMS v1.0 lifecycle foundation.

Reason:
Ensure every future approved implementation naturally keeps KMS synchronized without relying on uncontrolled app-side rewriting of source docs.

Files changed:
- `docs/engineering/KNOWLEDGE_LIFECYCLE.md`
- `docs/engineering/DOCUMENTATION_AUTOMATION.md`
- `docs/engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md`
- `docs/engineering/SELF_EVOLVING_WORKFLOW.md`
- `docs/engineering/DOCUMENTATION_DEPENDENCY_MAP.md`
- `docs/engineering/AI_CODING_WORKFLOW.md`
- `docs/engineering/FUTURE_AUTOMATION_ROADMAP.md`
- `docs/engineering/README.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/engineering-handbook/2026-06-26-kms-v3-phase-3d-lifecycle-foundation.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3D final phase only. SaaS flows, landing page code, database models, migrations, `tis.db`, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added KMS v3.0 Phase 3C Governance And AI Traceability

Area/module:
Knowledge Management System and engineering handbook

Previous state:
KMS v3.0 Phase 3B documented database architecture, development standards, UI/UX design philosophy, roadmap, and stronger onboarding guidance. It did not yet preserve rejected decisions, visual documentation standards, a definitive AI optimization guide, project governance, or explicit decision traceability.

New state:
TIS now has Phase 3C engineering docs for rejected decisions, visual documentation framework, AI optimization, project governance, and decision traceability. The PDF generator includes these docs.

Reason:
Future developers and AI assistants need to understand why TIS became what it is, not only what currently exists.

Files changed:
- `docs/engineering/REJECTED_DECISIONS.md`
- `docs/engineering/VISUAL_DOCUMENTATION_GUIDE.md`
- `docs/engineering/AI_OPTIMIZATION_GUIDE.md`
- `docs/engineering/PROJECT_GOVERNANCE.md`
- `docs/engineering/README.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/engineering-handbook/2026-06-26-kms-v3-phase-3c-governance-ai-traceability.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3C only. App behavior, SaaS flows, landing page code, database, migrations, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added KMS v3.0 Phase 3B Engineering Layers

Area/module:
Knowledge Management System and engineering handbook

Previous state:
KMS v3.0 Phase 3A added module map, repository architecture, user/system flows, and onboarding structure. The handbook still needed database architecture, development standards, UI/UX philosophy, roadmap, and stronger human/AI guidance.

New state:
TIS now has Phase 3B engineering docs for database architecture, development standards, UI/UX design philosophy, and product roadmap. Core KMS docs and AI onboarding guidance reference these layers, and the PDF generator includes them.

Reason:
Make the generated booklet more useful for new senior developers, Codex conversations, ChatGPT conversations, and future technical reviewers.

Files changed:
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`
- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md`
- `docs/engineering/PRODUCT_ROADMAP.md`
- `docs/engineering/README.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3B only. App behavior, SaaS flows, landing page code, database, migrations, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added KMS v3.0 Engineering Handbook

Area/module:
Knowledge Management System and engineering onboarding

Previous state:
The generated booklet included KMS source documents, ADRs, module history, AI context, and the Knowledge Center foundation, but it did not fully onboard a new human developer or future Codex/ChatGPT conversation into TIS modules, repository architecture, and end-to-end flows.

New state:
TIS now has an engineering handbook layer with a complete module map, repository architecture guide, user/system flow guide, and engineering onboarding index. The PDF generator includes these docs and emits documentation version 3.0.

Reason:
Make the generated booklet a true TIS Engineering Handbook rather than only a documentation bundle.

Files changed:
- `docs/engineering/README.md`
- `docs/engineering/TIS_MODULE_MAP.md`
- `docs/engineering/REPOSITORY_ARCHITECTURE.md`
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3A only. App behavior, SaaS flows, landing page code, database, migrations, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added Platform Owner Knowledge Center

Area/module:
Platform Knowledge Center and KMS access

Previous state:
TIS had KMS source docs, ADRs, module history, a generated PDF booklet, and a manifest, but no protected in-app owner page for KMS status or booklet access.

New state:
TIS now has a read-only Platform Owner Knowledge Center with KMS health score, manifest metadata, freshness detection, source document status, coverage checks, latest change-history entries, ADR list, module history areas, KIA checklist, and protected PDF view/download routes.

Reason:
Platform owners need an internal utility for verifying KMS health and accessing the generated PDF without exposing direct public static links.

Files changed:
- `knowledge_service.py`
- `main.py`
- `templates/platform_knowledge_center.html`
- `templates/platform_console.html`
- `scripts/generate_docs_pdf.py`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/history/platform-knowledge/README.md`
- `docs/history/platform-knowledge/2026-06-26-platform-owner-knowledge-center.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for Phase 2C only. Regenerate button, SaaS changes, database changes, migrations, landing page changes, commits, and pushes remain out of scope.

## 2026-06-26 - Established Knowledge Management System Foundation

Area/module:
Documentation and project knowledge management

Previous state:
TIS had Phase 1 documentation source files and a generated PDF booklet, but no formal change history, ADR system, module history foundation, KMS policy, manifest, or compact AI onboarding file.

New state:
TIS now has a Knowledge Management System foundation with chronological change history, documentation update policy, ADR structure and initial accepted ADRs, module history folders, AI project context, updated source docs, and an expanded PDF generator.

Reason:
Preserve project knowledge for future human developers, Codex conversations, ChatGPT conversations, project owners, platform owners, and technical reviewers.

Files changed:
- `docs/CHANGE_HISTORY.md`
- `docs/DOCUMENTATION_UPDATE_POLICY.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/adr/README.md`
- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`
- `docs/adr/0003-paddle-payment-architecture.md`
- `docs/adr/0004-webhook-only-payment-confirmation.md`
- `docs/adr/0005-delayed-tenant-provisioning-after-verified-payment.md`
- `docs/adr/0006-documentation-as-source-knowledge-management-system.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`
- `docs/history/README.md`
- `docs/history/*/README.md`
- `docs/history/provisioning/2026-06-26-kms-foundation.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for Phase 2A and Phase 2B only. Platform Owner Knowledge Center, app routes, SaaS flows, database, migrations, landing page implementation, commits, and pushes remain out of scope.
