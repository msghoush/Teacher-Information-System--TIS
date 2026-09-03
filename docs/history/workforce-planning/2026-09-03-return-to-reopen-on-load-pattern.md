---
title: Return-To Reopen-On-Load UI Pattern
module: workforce-planning
last_updated: 2026-09-03
---

# Return-To Reopen-On-Load UI Pattern

Server-rendered actions inside an expanded Planning section (native
`<details>`) previously redirected to a fresh `/planning` render with no
memory of which section was open, forcing the administrator to re-expand it
for every follow-up action. This adds a small, reusable fix rather than an
SPA conversion, by finishing wiring together capability that already existed
in the codebase separately.

`redirect_utils.py` is a new shared module holding `safe_redirect_path()`,
`redirect_with_notice()`, and `redirect_with_error()` - moved out of
`main.py`, which now imports them under their original private names so
every existing caller (`_safe_redirect_path`, `_redirect_with_notice`,
`_redirect_with_error`) keeps working unchanged. `safe_redirect_path()` is
the single open-redirect guard: it accepts only a path starting with exactly
one `/`, rejecting `http(s)://` and protocol-relative `//` targets, and
otherwise preserves the given `?query#fragment` unchanged. The notice/error
helpers additionally inject their query parameter while re-appending a
trailing `#fragment` after it, since a fragment must stay after the query
string.

`static/js/reopen-on-load.js`, loaded globally from `base.html`, runs on
`DOMContentLoaded`. It resolves a target element id from
`window.location.hash` (the redirect case) or an optional inline
`window.__tisReopenTargetId` a page can render for a non-redirect, in-place
response, looks it up with `document.getElementById` (which never throws,
unlike a raw CSS-selector lookup), opens it if it is a `<details>`, and
scrolls it into view. A missing, stale, or renamed id is a silent no-op by
design.

Planning is the first and, for now, only consumer. Each section's
`<details class="subject-assignment-details">` now carries a stable
`id="planning-section-{{ record.id }}"`. The "Remove demand" link passes
`return_to=/planning#planning-section-<id>` (URL-encoded); `routers/planning.py:
delete_planning_subject_demand` reads `return_to`, validates it with
`safe_redirect_path(return_to, default="/planning")`, and redirects there on
every outcome that returns to the list (success, and the not-found case),
falling back to plain `/planning` when `return_to` is absent or unsafe. The
in-place render outcomes that stay on the current request (permanent-demand
refusal, the `IntegrityError` fallback, and `delete_planning_section`'s own
blocked-dependency render) instead set `open_section_id` on
`_render_planning_page`, which the template turns into the inline
`window.__tisReopenTargetId` the shared script also understands - the same
reopening behavior without a redirect. Permission-denied and not-authenticated
outcomes are unchanged and never consult `return_to`.

Subjects and Teachers were not touched. This is scoped to Planning as the
first concrete use case; other pages may adopt the same `return_to` +
`#fragment` + shared-script convention later without needing a new mechanism.
