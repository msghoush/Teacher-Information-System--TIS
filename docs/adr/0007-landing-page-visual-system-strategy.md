---
adr: 0007
title: Landing Page Visual System Strategy
status: Accepted
date: 2026-06-26
---

# ADR 0007: Landing Page Visual System Strategy

Status: Accepted

Date: 2026-06-26

## Context

The public landing page must communicate trust, product maturity, and academic operations value. It should not be accidentally changed during backend or operational app work.

## Decision

Treat the Next.js landing website and its visual system as a separate product surface. Keep marketing content references under `docs/marketing/`. Do not modify landing design, copy, or legacy FastAPI landing files unless explicitly approved.

## Alternatives Considered

- Let backend tasks freely alter landing page presentation.
- Continue using legacy FastAPI landing files as the public source.
- Keep marketing strategy only in informal notes.

## Consequences

Positive:

- Protects brand and public conversion strategy.
- Keeps landing work deliberate and reviewable.
- Reduces accidental coupling with operational app changes.

Tradeoffs:

- Landing page changes need explicit planning.
- Developers must check the source-of-truth docs before editing public website files.

## Related Docs / Files

- `tis-landing-website/`
- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`
- `docs/history/landing-page/README.md`
