---
title: TIS Project State
documentation_version: 2.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Project State

## Last Updated

Last updated: 2026-06-26

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

M4: Provisioning foundation

- Platform owner provisioning views and actions exist.
- Pending organization review and provisioning queue behavior exist.
- Provisioning retry/run operations are present.

M5: Platform access and owner controls

- Platform owner and platform developer identities exist.
- Platform console and owner/developer management controls exist.
- Permission registry and platform access tests support this boundary.

Documentation/KMS milestones:

- Phase 1 documentation foundation completed and pushed to `dev`.
- Phase 2A and Phase 2B KMS foundation approved for implementation.

## Current Priority

Current priority: upgrade Phase 1 documentation into the TIS Knowledge Management System.

Phase 2A and Phase 2B scope:

- Create documentation update policy.
- Create change history.
- Create ADR foundation and initial accepted ADRs.
- Create module history foundation.
- Create AI project context.
- Update master context, project state, and documentation index.
- Update PDF generator to include KMS docs and manifest metadata.
- Regenerate `static/docs/TIS_Project_Reference_Booklet.pdf`.

Out of scope for this phase:

- Platform Owner Knowledge Center.
- App routes.
- `main.py`, `ui_shell.py`, `authorization.py`.
- SaaS flows.
- Operational logic.
- Database, migrations, or `tis.db`.
- Landing page implementation.

## Current Known Issues

Known issues and watch points:

- KMS policy depends on future developers and AI agents consistently completing the Knowledge Impact Assessment.
- Generated PDF can become stale if included Markdown docs change without regeneration.
- The owner-only Knowledge Center is not implemented yet.
- Public static storage is not sufficient access control for sensitive docs; Phase 2C should serve docs through protected owner-only routes.
- Render deployment constraints should continue to guide dependency choices.
- Broad filesystem scans may warn about `tis_scope_test_5i3yf0h5/` access denial.

## Next Planned Work

Next planned work after Phase 2A and Phase 2B review:

- Review KMS docs, ADRs, module history, AI context, PDF, and manifest.
- Approve corrections if needed.
- Plan Phase 2C protected Platform Owner Knowledge Center.
- Later add owner-only status page, view/download routes, stale detection UI, source list, and optional explicit regeneration workflow.

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

A task is not complete until KIA is assessed. If included docs change, regenerate:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

## Scope Guardrails

- Do not touch SaaS flows unless explicitly approved.
- Do not touch operational logic unless required by the approved task.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not change the landing page unless explicitly approved.
- Do not add Platform Owner Knowledge Center routes until reviewed and approved.
- Do not commit or push unless explicitly requested.
