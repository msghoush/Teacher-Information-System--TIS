---
title: TIS Change History
documentation_version: 3.1
last_updated: 2026-07-22
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

## 2026-07-22 - Added Phase 7C Knowledge Center Navigation

Area/module:
Platform Knowledge Center and KMS navigation

Previous state:
The owner-only Knowledge Center showed manifest sources in one path-focused table. It had no document search, category/module/freshness filters, logical source groups, descriptive summaries, or links to the source document's page in the protected booklet. ADRs were listed by ascending filename, and module-history areas were not ordered by recent activity.

New state:
The Knowledge Center enriches manifest-listed sources with Markdown title and summary metadata, groups them into Core, Engineering, Decisions, History, Marketing, and Supporting sections, and provides client-side search plus category, module, and freshness filters. Document and activity links open the existing owner-protected booklet route at the manifest `pdf_page`. ADRs are newest-first, and module-history areas are ordered by their latest dated entry with entry counts.

Reason:
Platform owners need to locate and consume authoritative knowledge quickly without introducing a database, search service, new route, dependency, or public documentation link.

Files changed:
- `knowledge_service.py` manifest presentation metadata and activity ordering
- `templates/platform_knowledge_center.html` grouped library, client-side search/filters, and protected deep links
- focused Knowledge Center service tests
- Platform Knowledge KMS source and module-history documents
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 7C only. Owner access checks, existing routes, application data, KMS source authority, and generator enforcement remain unchanged. No regenerate control was added.

## 2026-07-21 - Added Phase 7B Professional PDF Navigation

Area/module:
KMS generated booklet and manifest

Previous state:
The booklet was a linear concatenation of source documents with page footers and a source-path list. It had no page-numbered table of contents, source destinations, outline hierarchy, or manifest mapping from Markdown sources to PDF pages.

New state:
The ReportLab generator performs a multi-pass build with a "How to Use This Handbook" page, a real table of contents, stable source-document bookmarks, child bookmarks for H2 major headings, and deterministic named destinations. Every manifest source record includes its starting `pdf_page`, and freshness validation requires positive, strictly increasing page values.

Reason:
The engineering handbook must be practical to navigate as a long-form reference while Markdown remains authoritative and generation stays dependency-light.

Files changed:
- ReportLab PDF generator and focused automation tests
- PDF navigation documentation and engineering-handbook history
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; product architecture, current engineering guardrails, and onboarding order are unchanged.

Reviewer/approval notes:
No Knowledge Center UI, route, database, dependency, application behavior, or source-document ordering change was introduced.

## 2026-07-21 - Added Phase 7A KMS Navigation Foundation

Area/module:
KMS information architecture and developer onboarding

Previous state:
The KMS had complete root and engineering indexes, but they were long manually maintained file lists. Readers had to determine their own document set from 53 Markdown sources, and three supporting documents lacked normalized title metadata.

New state:
`docs/KMS_NAVIGATION.md` provides focused reading paths for new humans, new AI conversations, SaaS onboarding, subscriptions, operational modules, database work, Platform Owner tools, landing work, location data, design, decisions, and review/KIA. Root and engineering indexes now use real Markdown links and delegate task selection to the navigation guide. Missing document titles were normalized.

Reason:
Readers should reach relevant source material quickly without changing the established Markdown, manifest, PDF, or Knowledge Center architecture.

Files changed:
- KMS navigation guide and documentation indexes
- title metadata for three supporting documents
- fixed booklet source list entry for the new authoritative guide
- project state, change history, module history, PDF, and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; its existing first-read role and product/architecture guidance remain current.

Reviewer/approval notes:
Phase 7B catalog/PDF navigation, Phase 7C Knowledge Center changes, and Phase 7D enforcement enhancements were not implemented.

## 2026-07-21 - Added Unified Phase 6 KMS Commands

Area/module:
KMS developer workflow, local automation, CI, and deployment validation

Previous state:
Developers separately ran the PDF generator, artifact freshness check, and KIA impact checker. The repository had all required primitives but no single synchronization command or canonical read-only command shared by local work and CI.

New state:
`scripts/kms.py sync` validates the task KIA before writing, regenerates the PDF and manifest through the existing generator, runs complete post-generation validation, and prints a concise summary. `scripts/kms.py check` delegates to the existing read-only enforcement logic. GitHub pull-request, `dev`, and deployment gates use the unified check command.

Reason:
One reliable command reduces missed mechanical steps while preserving reviewed Markdown as the source of truth and keeping enforcement strict.

Files changed:
- KMS command orchestrator and reusable checker API
- KMS automation tests
- repository instructions and CI workflows
- KMS workflow documentation and generated artifacts

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
The command never rewrites authoritative Markdown and does not change application behavior or production data.

## 2026-07-21 - Aligned Push Enforcement With KIA Task Boundaries

Area/module:
GitHub Actions and KMS impact validation

Previous state:
Pull-request enforcement validated the full feature branch against its base, while push enforcement validated only `github.event.before...github.sha`. A follow-up fix commit therefore evaluated a cumulative `.kms-impact.yml` against only the latest commit and incorrectly reported previously updated KMS files as unchanged.

New state:
Pull requests validate the pull-request base SHA against the actual pull-request head SHA. Pushes to `dev` find the merge base between the repository default branch and the pushed head, then validate that complete task range. Both events apply the unchanged strict declaration and generated-artifact checks to the same logical implementation boundary.

Reason:
KIA declarations describe approved implementation tasks, which may contain multiple commits. Event delivery boundaries must not redefine those tasks.

Files changed:
- KMS impact checker
- KMS enforcement workflow
- KMS automation regression tests
- KMS governance documentation and generated artifacts

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; product architecture, developer onboarding order, and application behavior are unchanged.

Reviewer/approval notes:
Enforcement remains strict across the complete task diff. No application behavior or production data changed.

## 2026-07-21 - Made KMS Enforcement Cross-Platform Deterministic

Area/module:
Repository KMS generation, freshness validation, and CI enforcement

Previous state:
Markdown source hashes used raw checkout bytes, and dynamically discovered ADR and history sources used native `Path` ordering. A Windows checkout with CRLF line endings could generate a manifest that passed locally but failed on GitHub Linux, where the same committed text used LF and path ordering differed.

New state:
Markdown is decoded as UTF-8, normalized to LF, and then hashed. Source paths are normalized to repository-relative POSIX paths, dynamic sources use a stable case-insensitive ordering with a deterministic tie-breaker, and source comparison still rejects missing, unexpected, duplicate, or reordered entries. Git diff inspection now includes deleted files.

Reason:
KMS enforcement must evaluate committed content consistently across developer workstations and GitHub Actions without weakening freshness or source-coverage checks.

Files changed:
- KMS generator and impact checker
- Knowledge Center freshness hashing helper
- KMS automation tests and line-ending attributes
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; onboarding, architecture, product behavior, and current priorities are unchanged.

Reviewer/approval notes:
Repository-governance correction only. No application behavior, production data, SaaS flows, database, or migrations changed.

## 2026-07-21 - Added Automatic KMS Synchronization Enforcement

Area/module:
Repository governance, KMS automation, CI, deployment gate, and AI workflow

Previous state:
KMS updates depended on developers and AI assistants remembering the written KIA policy. PDF/manifest generation was manually triggered, the Knowledge Center detected stale hashes only when viewed, and no test, commit, pull-request, or deployment gate blocked stale or missing documentation.

New state:
Root `AGENTS.md` makes KMS onboarding mandatory. `.kms-impact.yml` records task-level impact. `scripts/check_kms_impact.py` compares declarations with Git changes, conservatively classifies major paths, validates declared Markdown, and invokes generated-artifact checks. The PDF generator has read-only `--check` mode and manifest PDF hashes. GitHub Actions enforce checks on pull requests and `dev`, and `master` deployment depends on the same gate. Automation never rewrites Markdown.

Reason:
Major TIS work must not be mergeable or deployable while engineering knowledge is stale, while reviewed Markdown must remain authoritative and free from runtime/customer data.

Files changed:
- `AGENTS.md`
- `.kms-impact.yml`
- `.github/pull_request_template.md`
- `.github/workflows/kms-enforcement.yml`
- `.github/workflows/deploy-on-master.yml`
- `scripts/check_kms_impact.py`
- `scripts/generate_docs_pdf.py`
- `tests/test_kms_automation.py`
- relevant KMS Markdown and generated artifacts

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Repository-governance automation only. No application behavior, production/customer/tenant/billing data, runtime records, database, migrations, or business logic changed.

## 2026-07-20 - Backfilled Completed M7 Subscription Management

Area/module:
SaaS entitlements, subscription portal, quantity/plan changes, cancellation, billing history, invoices, Paddle webhooks, and reconciliation

Previous state:
Module history covered M7 Phases 1, 2, 3, and 6 only. Central project state, architecture maps, workflows, roadmap, change history, PDF, and manifest still described the pre-M7 billing foundation; Phases 4 and 5 and reconciliation protections were absent.

New state:
KMS records the completed M7 entitlement foundation, read/write customer portal, paid branch quantity management, upgrades and scheduled downgrades, provider-authoritative proration, cancellation/reversal, centralized lifecycle and allowed-action policy, provider billing history, protected invoice downloads, and fail-closed webhook/reconciliation safeguards.

Reason:
The engineering handbook must describe current implemented subscription behavior before automatic enforcement becomes authoritative.

Files changed:
- central KMS context/state files
- subscription and payment ADRs
- engineering module, repository, database, flow, and roadmap docs
- subscription module history
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Documentation backfill only; it records already committed M7 behavior and introduces no SaaS behavior change.

## 2026-06-30 - Paddle Initial Checkout Price Mapping Configuration

Area/module:
SaaS subscriptions, Paddle initial checkout configuration, tests, and KMS documentation

Previous state:
The checkout launch flow safely blocked when the selected subscription plan price did not have `subscription_plan_prices.provider_price_id` configured, but there was no structured mapping sync process and the customer-facing error could expose provider configuration wording.

New state:
Added a script-based Paddle price ID sync process using structured sandbox/production mapping examples. The database remains the source of truth through `subscription_plan_prices.provider_price_id`, real mapping files are ignored, and missing provider price IDs now surface a customer-safe Secure Payment support message while internal diagnostics retain plan code, billing interval, and currency details.

Reason:
Initial subscription checkout needs environment-specific Paddle provider price IDs without hardcoding live IDs in source or changing payment state behavior.

Files changed:
- `.gitignore`
- `scripts/sync_paddle_price_ids.py`
- `config/paddle/paddle_prices.sandbox.example.json`
- `config/paddle/paddle_prices.production.example.json`
- `saas/payment_service.py`
- `saas/router.py`
- `tests/test_paddle_price_sync.py`
- `tests/test_saas_phase1.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/subscriptions/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Initial checkout configuration only. No proration, upgrade, downgrade, cancellation, payment state transition, webhook, provisioning behavior, database schema, migration, operational module, landing website, OAuth, internal route rename, live Paddle ID hardcoding, commit, or push was performed.

## 2026-06-27 - Accepted Subscription And Workspace Activation Guided Journey Phase 3C

Area/module:
Subscription Selection, Secure Payment summary, Payment Return/Cancel, Subscription Status, Workspace Activation status, tests, and KMS documentation

Previous state:
The subscription, secure payment, billing status, payment return/cancel, and workspace activation pages were functionally correct but still used page-local CTAs, dense status blocks, and inconsistent guidance. Browser return messaging existed but was not part of the shared guided setup experience.

New state:
Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages now use the Phase 3A shared setup shell and Phase 3B guided page style. Each page has one shared-shell primary CTA, customer-safe status labels, concise supporting cards, clear browser-return guidance, and explicit messaging that TIS Platform access becomes available after Workspace Activation.

Reason:
The accepted Phase 3C scope required making subscription/payment/activation pages feel like one guided customer journey while preserving payment, billing, provisioning, webhook, checkout start/launch, database, and operational behavior.

Files changed:
- `saas/router.py`
- `templates/saas/plan_selection.html`
- `templates/saas/checkout_summary.html`
- `templates/saas/checkout_return.html`
- `templates/saas/checkout_cancel.html`
- `templates/saas/account_billing.html`
- `templates/saas/billing_status.html`
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
Phase 3C customer-facing subscription/payment/status redesign only. No payment behavior change, billing behavior change, provisioning behavior change, webhook logic change, checkout start/launch behavior change, database schema change, migration, operational module change, Next.js landing website change, OAuth change, internal `/saas` route rename, stored-status change, admin view change, commit, or push was performed.

## 2026-06-27 - Accepted School Workspace Setup Guided Wizard Phase 3B

Area/module:
School Workspace Setup onboarding templates, shared SaaS customer shell, onboarding setup context, tests, and KMS documentation

Previous state:
The five onboarding pages used functional but dense form layouts with repeated progress notices, mixed card styles, and page-local primary actions. Branch setup felt like repeated blank blocks, organization logo upload was plain, and the review page felt like a basic summary rather than a confident handoff to Subscription Selection.

New state:
Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup now use a consistent guided enterprise setup wizard style on top of the Phase 3A shared shell. Each page has one shared-shell primary CTA, secondary Back/Save Draft actions, grouped form sections, concise guidance, cleaner spacing, a more premium logo upload area, compact branch panels, and a stronger review summary.

Reason:
The accepted Phase 3B scope required redesigning only the School Workspace Setup onboarding pages while preserving all business logic, routes, field names, validation, draft behavior, payment, billing, provisioning, database, and operational boundaries.

Files changed:
- `saas/router.py`
- `templates/saas/base.html`
- `templates/saas/onboarding_organization.html`
- `templates/saas/onboarding_branches.html`
- `templates/saas/onboarding_academic_setup.html`
- `templates/saas/onboarding_contacts.html`
- `templates/saas/onboarding_review.html`
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
Phase 3B onboarding page redesign only. No backend business logic change, route rename, form field rename, validation change, onboarding progression change, draft behavior change, payment behavior change, billing behavior change, provisioning behavior change, database schema change, migration, operational module change, Next.js landing website change, OAuth change, commit, or push was performed.

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
