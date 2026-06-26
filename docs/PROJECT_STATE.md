# TIS Project State

## Last Updated

Last updated: 2026-06-26

Update this date after every approved implementation that changes project behavior, architecture, documentation, deployment, or roadmap status.

## Current Branch Strategy

Current working branch assumption: `dev`.

Branch strategy:

- Development work should happen on `dev` unless the owner explicitly requests another branch.
- Production/live branch is assumed to be separate from active development.
- Do not push, merge, or commit unless explicitly requested.
- Before major implementation work, check the current branch and working tree.
- Preserve unrelated local changes.

## Production / Live Branch Assumption

The live production branch is assumed to be the branch deployed to the public app environment, while `dev` is the active development branch. This assumption must be confirmed before any deployment, merge, or production-sensitive change.

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

## Current Priority

Current priority: establish a permanent documentation source of truth and a reliable generated PDF reference booklet.

Phase 1 priority:

- Create master project documentation.
- Create living project state documentation.
- Create documentation index.
- Add conservative PDF generation foundation.
- Generate `static/docs/TIS_Project_Reference_Booklet.pdf`.

Phase 2 is not yet approved:

- Do not add the Platform Owner documentation center.
- Do not add app routes for documentation.
- Do not modify platform navigation or route permissions for docs yet.

## Current Known Issues

Known issues and watch points:

- `PROJECT_STATE.md` can become stale unless updated as part of every approved implementation.
- Generated PDF can become stale unless regenerated after documentation changes.
- The current documentation center is Phase 1 only; there is not yet a protected in-app owner page for viewing/downloading the booklet.
- Public static storage is not sufficient access control for sensitive platform documentation; Phase 2 should serve the booklet through protected routes.
- Render deployment constraints should continue to guide dependency choices.
- The repository contains a directory named `tis_scope_test_5i3yf0h5` that may deny access during broad filesystem scans.

## Next Planned Work

Next planned work after Phase 1 review:

- Review generated documentation and booklet output.
- Approve, adjust, or expand source documents.
- Plan Phase 2 protected Platform Owner documentation center.
- Add owner-only page, PDF view/download routes, version/date display, source list, and optional regeneration status.
- Add tests for owner-only access before exposing the booklet inside the app.

## Landing Page Baseline Situation

The public landing page source of truth is:

- `tis-landing-website/`

The marketing documentation references are:

- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`

Legacy FastAPI landing files are not the current public website source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

Do not modify landing page design, landing copy, or legacy landing files unless explicitly approved.

## Documentation Update Policy

Every approved implementation must:

1. Check whether documentation is affected.
2. Update relevant Markdown docs.
3. Regenerate the PDF booklet if docs changed.
4. Mention documentation changes in the final report.

A task is not complete until relevant documentation is updated.

Generated booklet path:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

## Scope Guardrails

- Do not touch SaaS flows unless explicitly approved.
- Do not touch operational logic unless required by the approved task.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not change the landing page unless explicitly approved.
- Do not add Phase 2 documentation routes until reviewed and approved.
- Do not commit or push unless explicitly requested.
