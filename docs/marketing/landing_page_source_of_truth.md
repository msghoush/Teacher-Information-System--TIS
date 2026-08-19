---
title: TIS Landing Page Source of Truth
documentation_version: 3.1
last_updated: 2026-08-19
source_of_truth: true
---

# Landing Page Source of Truth

Starter, Professional, and Enterprise AI pricing presentation is capacity-based.
Normal customer feature availability is common across the three plans; AI
consumption allowances may be configured separately. Public copy must not imply
that ordinary modules or enabled AI availability require a higher plan.

The public header and relevant conversion areas expose Request a Demo,
Subscribe, Sign In, and Open TIS App. All app links are constructed here from
`NEXT_PUBLIC_TIS_APP_BASE_URL`; Sign In targets `/saas/login`, Open TIS App
targets `/login`, and the landing site does not duplicate authentication or
customer-state routing.

The hero Subscribe Now action remains within the marketing page and scrolls to
`#pricing`. Starter, Professional, and Enterprise AI pricing actions use the
configured application base URL and public `/saas/signup` route with distinct
allowlisted preferred-plan codes. The application treats those codes as
non-authoritative preferences and revalidates capacity after organization
setup. Custom remains an email/contact action and never enters signup or
checkout.

The official source of truth for the public TIS landing website is:

```text
tis-landing-website/
```

## Public Website

- **Domain:** https://tisplatform.com
- **Runtime:** Next.js / Node
- **Local testing URL:** http://localhost:3000

All future marketing landing page changes must be made inside `tis-landing-website/`.

## Application Portal

The TIS application portal remains separate from the public landing website:

- **Domain:** https://app.tisplatform.com
- **Runtime:** FastAPI / Python with PostgreSQL

## Legacy Landing Page Files

The former FastAPI/Jinja landing page files are now legacy:

- `templates/landing.html`
- `static/landing/landing.css`

Codex and other developers must not modify these legacy files unless explicitly instructed.
