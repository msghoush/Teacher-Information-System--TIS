---
adr: 0001
title: Separate Next.js Landing Website
status: Accepted
date: 2026-06-26
---

# ADR 0001: Separate Next.js Landing Website

Status: Accepted

Date: 2026-06-26

## Context

TIS needs a public marketing website and a protected operational application. The public site has different performance, design, routing, and deployment needs than the FastAPI operational portal.

## Decision

Keep the public landing website in `tis-landing-website/` as a separate Next.js app. Keep the FastAPI app as the operational portal at `https://app.tisplatform.com`.

## Alternatives Considered

- Use FastAPI/Jinja for both marketing and app pages.
- Put marketing pages inside the operational app templates.
- Use a static site generated outside the repository.

## Consequences

Positive:

- Clear separation between marketing and operational concerns.
- Landing page can evolve with a modern frontend stack.
- Operational FastAPI app remains focused on authenticated workflows.

Tradeoffs:

- Two runtimes must be understood.
- Deployment and routing boundaries must be respected.

## Related Docs / Files

- `tis-landing-website/`
- `docs/marketing/landing_page_source_of_truth.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `templates/landing.html`
- `static/landing/landing.css`
