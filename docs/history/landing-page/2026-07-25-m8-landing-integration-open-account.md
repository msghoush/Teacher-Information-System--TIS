---
title: M8 Landing Integration Open Account
module: landing-page
date: 2026-07-25
---

# 2026-07-25 - M8 Landing Integration Open Account

Module:
Landing Page

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-07-25 - M8 Landing Integration Open Account Entry Points

Related ADRs:
- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`

Reviewer/approval notes:
M8 final landing integration only. No FastAPI SaaS application, authentication, onboarding backend, payment, provisioning, database, operational module, commit, push, or M9 work.

## Previous Documented State

The public Next.js landing website explained TIS, supported demo and early-access interest, and remained separate from the FastAPI application. It did not yet expose the completed customer account setup flow from the public marketing surface.

## New Documented State

The public landing website now includes Open Account entry points in:

- the navigation,
- the hero CTA group,
- the final CTA area.

All Open Account links share one destination derived from `NEXT_PUBLIC_TIS_APP_BASE_URL` and the existing `/saas/signup` path. The landing project remains a marketing website and redirects visitors to the separately deployed TIS Account signup flow.

## Reason For Change

M8A and M8B-1 through M8B-6 completed the SaaS-side customer account, workspace, demo, subscription, and conversion readiness. M8 final integration connects the public website to that existing deployed signup journey without changing the SaaS application.

## User / Business Impact

Visitors can move directly from `tisplatform.com` to account setup. Schools still retain demo and early-access paths, while Open Account becomes the direct signup entry point for M8 production validation.

## Technical Impact

The change is limited to `tis-landing-website/` plus KMS documentation. The FastAPI app, SaaS routes, authentication, onboarding backend, Paddle, database, APIs, demo workflow, provisioning, and commercial state remain unchanged.

## Follow-Up Needed

Set `NEXT_PUBLIC_TIS_APP_BASE_URL` in the landing website hosting environment, deploy the landing project separately from the FastAPI app, and validate that Open Account navigates to the deployed TIS Account signup flow on desktop, tablet, and mobile.
