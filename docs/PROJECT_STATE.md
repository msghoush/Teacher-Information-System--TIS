---
title: TIS Project State
documentation_version: 3.1
last_updated: 2026-07-22
source_of_truth: true
---

# TIS Project State

## Last Updated

Last updated: 2026-07-22

Update this file after every meaningful milestone, active development change, roadmap shift, known issue change, or documentation/KMS change.

## Current Branch Strategy

Current working branch assumption: `dev`.

Branch strategy:

- Development work should happen on `dev` unless the owner explicitly requests another branch.
- Production/live branch is assumed to be separate from active development.
- Confirm production branch before any deployment, merge, or production-sensitive change.
- Do not push, merge, or commit unless explicitly requested.
- Preserve unrelated local changes.

## Production / Live Branch Assumption

The live production branch is assumed to be the branch deployed to the public app environment, while `dev` is the active development branch. This assumption must be confirmed before deployment.

Production domains:

- Public website: `https://tisplatform.com`
- Application portal: `https://app.tisplatform.com`

## Completed Milestones

M1: Identity and SaaS foundation

- Core SaaS signup/login/account concepts established.
- Platform, tenant, and SaaS account identities separated.
- Identity and SaaS phase tests present.

M2: Onboarding foundation

- SaaS onboarding flow covers organization, contacts, branches, academic setup, and review.
- Pending organization concept supports pre-provisioning state.

M3: Billing and plan foundation

- Plan catalog, checkout, billing status, checkout return, and checkout cancel flows exist.
- Payment and billing code is isolated under `saas/` service modules.
- Initial Paddle checkout price IDs are configured through a script-based mapping sync into `subscription_plan_prices.provider_price_id`.
- Sandbox and production Paddle price mappings must remain separate; real mapping files are ignored and credentials stay in environment variables.

M4: Provisioning foundation

- Platform owner provisioning views and actions exist.
- Pending organization review and provisioning queue behavior exist.
- Provisioning retry/run operations are present.

M5: Platform access and owner controls

- Platform owner and platform developer identities exist.
- Platform console and owner/developer management controls exist.
- Permission registry and platform access tests support this boundary.

SaaS account setup stabilization:

- Phase 1 TIS Account email verification recovery is accepted.
- Valid verification links now redirect to TIS Account login with a professional success notice.
- Expired or invalid verification links now show a recovery page with a resend option.
- Resend verification safely handles unverified, already verified, and unknown-email cases.
- Unverified password-based accounts are blocked from starting or continuing school workspace setup.
- New verification-flow wording uses "TIS Account" and "school workspace setup".
- Payment, billing, provisioning, database schema, migrations, operational modules, and the landing website were not changed.
- Google/Microsoft login remains future work and was not implemented.

SaaS customer-facing wording and branding:

- Phase 2 TIS Account customer-facing wording cleanup is accepted.
- Customer account/setup pages now use professional labels such as TIS Account, Account Dashboard, School Workspace Setup, Organization Profile, Branch Setup, Academic Setup, Subscription Setup, Secure Payment, and Workspace Activation.
- The shared customer account shell uses the official full-color horizontal TIS logo on the light account background.
- Transactional TIS Account emails use an existing official dark-blue TIS wordmark asset.
- Customer views label internal statuses through customer-safe wording instead of exposing raw tenant, provisioning, checkout, provider, plan, school group, or attempt identifiers.
- Internal `/saas` route/module/model names and stored statuses were not renamed.
- Payment, billing, provisioning behavior, database schema, migrations, operational modules, and the landing website were not changed.
- Google/Microsoft login remains future work and was not implemented.

SaaS guided setup framework:

- Phase 3A shared TIS Account guided setup framework is accepted.
- The customer account shell now supports an official-logo guided setup console with an 8-step journey stepper, status banner, one primary next action, main content area, and help/guidance area.
- The account page now uses the framework and removes the old dense dashboard statistics from the customer account landing page.
- Journey state is derived from existing account, onboarding, billing, payment, and activation data without changing stored statuses.
- Onboarding forms, subscription/payment pages, billing/status pages, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, the landing website, internal `/saas` route names, and Google/Microsoft login were not changed.
- Phase 3B redesigned the five School Workspace Setup onboarding pages on top of the shared setup shell.
- Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup now use consistent guided wizard sections, one shared-shell primary CTA, and secondary Back/Save Draft actions.
- Phase 3B preserved backend logic, form actions, field names, validation behavior, draft behavior, onboarding progression, payment/billing/provisioning behavior, database schema, migrations, operational modules, the landing website, internal `/saas` route names, and OAuth behavior.
- Phase 3C redesigned Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages using the same shared setup shell and guided style.
- Phase 3C added customer-safe browser-return/payment confirmation guidance and explicit TIS Platform access-after-activation messaging without changing payment, billing, provisioning, webhook, checkout start/launch, database, migration, operational, landing, route, stored-status, admin, or OAuth behavior.

Documentation/KMS milestones:

- Phase 1 documentation foundation completed and pushed to `dev`.
- Phase 2A and Phase 2B KMS foundation approved for implementation.
- Phase 2C Platform Owner Knowledge Center completed and pushed to `dev`.
- KMS v3.0 Phase 3A Engineering Handbook approved for implementation.
- KMS v3.0 Phase 3B approved for implementation.
- KMS v3.0 Phase 3C approved for implementation.
- KMS v3.0 Phase 3D final phase approved for implementation.
- Automatic KMS enforcement implemented with repository instructions, machine-readable KIA, major-change detection, read-only artifact checks, CI validation, and a deployment prerequisite.
- Phase 6 unified KMS command implemented with `scripts/kms.py sync` and `scripts/kms.py check`.
- Phase 7A navigation foundation implemented with task-based reading paths, improved indexes, and normalized supporting-document titles.
- Phase 7B professional PDF navigation implemented with handbook guidance, a page-numbered table of contents, source and major-heading bookmarks, and manifest source-page metadata.
- Phase 7C Platform Knowledge Center navigation implemented with manifest-backed titles and summaries, logical document groups, client-side search and filters, protected booklet page links, and newest-first knowledge activity.

M7 subscription-management milestones:

- Phase 1 entitlement foundation completed.
- Phase 2 customer Subscription Management portal completed.
- Phase 3 active paid branch-quantity management completed.
- Phase 4 upgrades and scheduled downgrades completed with provider-authoritative previews/proration.
- Phase 5 cancellation/reversal and centralized lifecycle/action policy completed.
- Phase 6 provider billing history and protected invoice management completed.
- Webhook and reconciliation safeguards were added across the M7 lifecycle.

## Current Priority

Current priority: review Phase 7C Knowledge Center navigation and continue improving KMS consumption incrementally while preserving strict synchronization and completed M7 subscription context.

Current enforcement scope:

- Codex reads root `AGENTS.md` and authoritative KMS context.
- Every task updates `.kms-impact.yml`.
- Major-change paths are conservatively classified by `scripts/check_kms_impact.py`.
- Local KMS synchronization runs through `scripts/kms.py sync`.
- Generated artifacts and KIA are validated read-only through `scripts/kms.py check`.
- Pull requests and `dev` pushes run KMS enforcement.
- `master` deployment waits for the KMS gate.
- Automation validates and blocks; it does not rewrite Markdown.

Phase 2A and Phase 2B scope:

- Create documentation update policy.
- Create change history.
- Create ADR foundation and initial accepted ADRs.
- Create module history foundation.
- Create AI project context.
- Update master context, project state, and documentation index.
- Update PDF generator to include KMS docs and manifest metadata.
- Regenerate `static/docs/TIS_Project_Reference_Booklet.pdf`.

Phase 2C completed scope:

- Added read-only `knowledge_service.py` as the single KMS app access layer.
- Added owner-protected `/platform/knowledge` page.
- Added owner-protected PDF view/download routes.
- Added an owner-only Platform Console card.
- Added platform knowledge module history.
- Regenerated the PDF and manifest after documentation updates.
- Phase 7C adds client-side source search, category/module/freshness filters, logical document groups, document titles and summaries, protected booklet page links, and improved ADR/module-history ordering without adding routes or write behavior.

Still out of scope:

- Regenerate button.
- Additional app routes beyond the approved read-only Knowledge Center routes.
- `ui_shell.py` and `authorization.py` changes unless separately approved.
- SaaS flows.
- Operational logic.
- Database, migrations, or `tis.db`.
- Landing page implementation.

KMS v3.0 Phase 3A scope:

- Add complete TIS module map.
- Add repository architecture map.
- Add end-to-end user/system workflows.
- Add clear AI/human developer onboarding structure.
- Update generator to include engineering docs.
- Regenerate the PDF and manifest.

KMS v3.0 Phase 3B scope:

- Add database architecture overview.
- Add development standards and non-negotiable rules.
- Add UI/UX and design philosophy.
- Add product roadmap.
- Strengthen AI/human developer onboarding guidance.
- Update generator to include the new engineering docs.
- Regenerate the PDF and manifest.

KMS v3.0 Phase 3C scope:

- Add rejected architectural decisions.
- Add visual documentation framework.
- Add AI optimization guide.
- Add project governance and decision traceability.
- Update generator to include the new engineering docs.
- Regenerate the PDF and manifest.

KMS v3.0 Phase 3D final scope:

- Add knowledge lifecycle documentation.
- Add documentation automation guide.
- Add formal KIA standard.
- Add self-evolving workflow.
- Add documentation dependency map.
- Add AI coding workflow.
- Add future automation roadmap.
- Regenerate the PDF and manifest.

## Current Known Issues

Known issues and watch points:

- KMS policy depends on future developers and AI agents consistently completing the Knowledge Impact Assessment.
- Generated PDF can become stale during local work, but CI now blocks stale artifacts from integration/deployment.
- The owner-only Knowledge Center is implemented as read-only; there is no regenerate button yet.
- Public static storage is not sufficient access control for sensitive docs; Phase 2C should serve docs through protected owner-only routes.
- Render deployment constraints should continue to guide dependency choices.
- Production memory must be treated as a hard constraint. The 2026-06-27 Render restart/502 investigation found two avoidable memory risks: observation diagnostics doing extra production template renders and global location lookup parsing a 47 MB dataset into a complete in-memory index for simple picker requests. Local stabilization changes now gate observation diagnostics and use scoped location loading; future work must follow the Production Memory and Render Stability standards.
- Broad filesystem scans may warn about `tis_scope_test_5i3yf0h5/` access denial.
- Google/Microsoft login is still future work; password-based accounts must remain email-verified before school workspace setup.
- GitHub repository settings must mark `KMS Enforcement / kms-check` as required on protected branches; this cannot be configured by repository file changes alone.

## Next Planned Work

Next planned work:

- Review the KMS enforcement rules against real pull requests and tune only demonstrated false positives.
- Keep M7 documentation current as subscription fixes evolve.
- Later consider an explicit owner-only regenerate workflow.
- Review, commit, and deploy the production memory stabilization changes when approved, then monitor Render memory, restart count, and route-level 502s after deployment.

## Landing Page Baseline Situation

The public landing page source of truth is:

- `tis-landing-website/`

Marketing docs:

- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`

Relevant ADRs:

- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`

Legacy FastAPI landing files are not the current public website source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

Do not modify landing page design, landing copy, or legacy landing files unless explicitly approved.

## Knowledge Update Policy

Every approved implementation must complete the KIA:

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

A task is not complete until KIA is assessed and `.kms-impact.yml` matches the actual task diff. If included docs change, regenerate:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

Then run `.\.venv\Scripts\python.exe scripts\kms.py check` for final read-only validation. When documentation changes, `.\.venv\Scripts\python.exe scripts\kms.py sync` performs generation and post-generation validation together.

## Scope Guardrails

- Do not touch SaaS flows unless explicitly approved.
- Do not touch operational logic unless required by the approved task.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not change the landing page unless explicitly approved.
- Do not add a KMS regenerate button until separately approved.
- Do not let automation rewrite authoritative Markdown.
- Do not place customer, personal, production, billing-record, transaction, invoice, webhook payload, credential, secret, environment, or database-row data in KMS docs.
- Do not commit or push unless explicitly requested.
