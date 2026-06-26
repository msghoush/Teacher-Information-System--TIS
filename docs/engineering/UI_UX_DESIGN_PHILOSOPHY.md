---
title: TIS UI UX Design Philosophy
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS UI/UX Design Philosophy

TIS should feel like a clean, premium academic SaaS platform. It should not feel like a generic admin dashboard, spreadsheet wrapper, or decorative marketing shell disconnected from real product value.

## Overall Product Identity

Design principles:

- professional,
- light,
- trustworthy,
- academic,
- calm,
- data-aware,
- premium without being flashy.

The product serves serious academic operations. UI should reduce confusion and support confident decisions.

## Operational FastAPI App

The operational app should prioritize:

- clarity,
- role-based navigation,
- data density,
- fast scanning,
- predictable controls,
- strong permission boundaries,
- branch/year context visibility.

Avoid:

- generic admin clutter,
- decorative cards that do not help workflows,
- large marketing-style hero sections inside operational tools,
- hiding important state behind vague labels,
- layouts that make repeated operational use slow.

Operational pages should help users answer:

- What am I looking at?
- Which school/branch/year is active?
- What needs action?
- What can my role do here?
- What changed after I saved?

## Platform Owner Console

The Platform Owner Console should feel like a controlled operations console.

Priorities:

- global visibility,
- owner/developer separation,
- clear organization switching,
- safe access to sensitive tools,
- explicit status labels,
- no accidental tenant context confusion.

Avoid:

- broad controls without owner-only checks,
- exposing platform tools to developers by appearance alone,
- unclear organization/branch state.

## Knowledge Center

The Knowledge Center is an internal owner utility, not a marketing page.

Priorities:

- KMS health,
- source coverage,
- freshness status,
- protected PDF actions,
- ADR/change/module visibility,
- KIA policy reminder.

Avoid:

- direct public static PDF links,
- regenerate actions until approved,
- app-side Markdown rewriting,
- decorative presentation that hides status.

## SaaS Onboarding Pages

SaaS onboarding should feel guided, calm, and customer-facing.

Priorities:

- clear next step,
- progress visibility,
- plain customer language,
- reassurance around setup and billing,
- no internal engineering terms.

Customer-facing language should avoid:

- tenant,
- provisioning,
- M1/M2/M3/M4/M5,
- schema,
- migration,
- internal role mechanics.

Use customer language such as:

- organization,
- school,
- branch or campus,
- setup,
- plan,
- billing,
- account,
- getting your workspace ready.

## Next.js Landing Website

The landing website should use premium storytelling and strong visual assets.

Priorities:

- clear problem/solution narrative,
- actual product credibility,
- school operations language,
- strong visual hierarchy,
- polished screenshots or generated assets when appropriate,
- conversion path into demo/signup.

Avoid:

- weak fake 3D visuals,
- generic SaaS gradients without product specificity,
- vague claims unsupported by product reality,
- internal terms like tenant/provisioning/milestones,
- cluttered feature walls.

The landing page source of truth is `tis-landing-website/`, not legacy FastAPI landing files.

## Visual System Direction

Future design system should support:

- consistent cards, tables, filters, status badges, and action buttons,
- clear empty/loading/error states,
- accessible contrast,
- stable layouts across modules,
- consistent icon and label patterns,
- role-aware navigation,
- responsive behavior without losing operational density.

## Tone And Copy

Internal app copy:

- concise,
- action-oriented,
- operationally clear.

Customer-facing copy:

- plain,
- confident,
- benefit-oriented,
- free of internal implementation terms.

Platform owner copy:

- precise,
- status-driven,
- explicit about access and risk.
