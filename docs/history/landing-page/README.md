---
title: Landing Page History
module: landing-page
last_updated: 2026-07-29
---

# Landing Page History

## 2026-07-29 - Safe Pricing Subscription Entry

Hero Subscribe Now now scrolls to `#pricing`. The three self-service plans use
the same CTA treatment and link to public TIS Account registration with their
own allowlisted preferred-plan code. Plan descriptions were removed to keep
the cards focused on price, capacity, and action. Custom remains email-only.

## 2026-07-28 - Returning-Customer Navigation

The Next.js landing now exposes Sign In and Open TIS App beside Request a Demo
and Subscribe. Every app link derives from `NEXT_PUBLIC_TIS_APP_BASE_URL`;
authentication and state routing remain in FastAPI.

This folder tracks meaningful changes to the public landing page, marketing positioning, visual system strategy, and source-of-truth boundaries.

Related docs:

- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`
- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`

History entries:

- `2026-07-25-landing-cta-and-demo-domain-policy.md`: replaces overlapping public conversion CTAs with Request a Demo and Subscribe Now, both using configured deployed SaaS signup URLs and explicit onboarding intent.
- `2026-07-25-m8-landing-integration-open-account.md`: final M8 Open Account entry points from the public landing website to the deployed TIS Account signup flow.
