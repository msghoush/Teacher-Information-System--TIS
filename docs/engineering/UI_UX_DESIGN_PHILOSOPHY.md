---
title: TIS UI UX Design Philosophy
documentation_version: 3.0
last_updated: 2026-09-03
source_of_truth: true
---

# TIS UI/UX Design Philosophy

## Restoring Expanded State After A Server Redirect

TIS is server-rendered FastAPI/Jinja, not an SPA, so expand/collapse state
(native `<details>`, dialogs) lives only in the DOM and is normally lost the
moment an action redirects to a fresh render. The sanctioned fix reuses two
things that already existed rather than introducing a new mechanism: the
existing `return_to` form-field/query-param convention, and its `#fragment`
preservation already built into `redirect_utils.redirect_with_notice()` /
`redirect_with_error()` (moved out of `main.py` so any router can share the
same open-redirect guard, `redirect_utils.safe_redirect_path()`).

A route that wants the user to land back on a specific element accepts a
`return_to` value shaped `<path>[?query]#<element-id>`, validates it with
`redirect_utils.safe_redirect_path(return_to, default=<page path>)`, and
redirects there. The shared client script `static/js/reopen-on-load.js`,
loaded globally from `base.html`, runs on `DOMContentLoaded`, resolves a
target id from `window.location.hash` (or an optional inline
`window.__tisReopenTargetId` a page can render for a non-redirect, in-place
response), and if the matching element is a `<details>`, opens it and scrolls
it into view. A missing, stale, or renamed id is a silent no-op by design -
`document.getElementById` never throws, so this can never break a page load.

Do not invent a page-local variant of this pattern. Give the element to
reopen a stable, predictable id, pass `return_to` through the existing
convention, and let the shared script do the reopening. Planning's Remove
Demand action (`routers/planning.py:delete_planning_subject_demand`) is the
reference implementation.

## Progressive Disclosure And Commercial States

Expected commercial states use branded, actionable pages rather than generic
errors or internal state labels. Expired customers see data-preservation, plan
or renewal, support, and sign-out guidance. Dense Platform Owner pages show
only the decision summary and common actions initially; lifecycle processing,
branch/feature overrides, audit evidence, and technical metadata belong under
More Actions, Advanced Settings, and Activity History. Presentation
simplification must not remove operational controls.

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

## Compact Descriptions And Tooltips

Compact-description tooltips are an explicit progressive-disclosure treatment,
not a default for ordinary text. Shared JavaScript may enhance elements marked
with `data-compact-description` and the maintained allowlist of approved compact
components. It must not infer tooltip behavior from generic `p` or `small` tags,
or from broad class fragments such as description, subtitle, note, lede, helper,
or supporting.

Operational status, helper, validation, and record text remains visible inline.
Intentional tooltips must retain keyboard focus behavior, Escape dismissal, and
an accessible relationship between their trigger surface and tooltip content.
Native titles and accessible names on unrelated controls and visualizations are
not removed by compact-description processing.

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
