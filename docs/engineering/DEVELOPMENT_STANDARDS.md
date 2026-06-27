---
title: TIS Development Standards
documentation_version: 3.0
last_updated: 2026-06-27
source_of_truth: true
---

# TIS Development Standards

These standards are mandatory for future human developers, Codex conversations, ChatGPT conversations, and technical reviewers working on TIS.

## Inspect Before Editing

Before changing files:

- inspect the current code with `rg` and targeted file reads,
- understand the affected route/service/template/model,
- read relevant docs, ADRs, and module history,
- check tests for the touched module,
- check the current branch and working tree.

Do not code from memory when local context is available.

## Plan Before Implementation

For non-trivial work:

- identify the affected modules,
- identify tenant/permission/identity boundaries,
- identify documentation updates,
- identify tests or smoke checks,
- keep the implementation path small.

Planning does not need to be long, but the risk boundaries must be clear.

## Keep Changes Small And Scoped

- Implement only the approved request.
- Avoid unrelated refactors.
- Avoid formatting churn in unrelated files.
- Preserve existing patterns unless there is a clear reason to change them.
- Do not move code across modules as a side effect.

## Preserve Tenant Isolation

Tenant isolation is non-negotiable.

Always protect:

- school group boundaries,
- branch boundaries,
- academic year scope,
- user role/permission scope,
- observation and teacher data sensitivity.

Any change that touches tenant scope should be treated as high risk.

## Preserve Login And Platform Owner Flows

Do not casually change:

- `/login`,
- session cookies,
- platform owner detection,
- platform developer permissions,
- `/platform`,
- `/platform/knowledge`,
- scope switching,
- access denied handling.

Platform developers are not platform owners unless existing owner logic explicitly treats them that way.

## Protect SaaS, Payment, And Provisioning

Do not casually change:

- `/saas/signup`,
- `/saas/login`,
- `/saas/account`,
- SaaS onboarding steps,
- Paddle checkout/client code,
- payment confirmation logic,
- billing state,
- provisioning readiness,
- provisioning jobs.

Webhook-confirmed payment is authoritative. Checkout return pages are not proof of payment.

## Database And Migration Rules

- Never modify `tis.db` unless explicitly approved.
- Never modify migrations casually.
- Do not change `models.py` without understanding migration/repair implications.
- Do not add schema changes without tests and documentation.
- Never use destructive database operations without explicit approval.

## Landing Website Rule

The public landing website is separate:

- implementation: `tis-landing-website/`,
- marketing docs: `docs/marketing/`,
- ADRs: `0001`, `0007`.

Do not modify landing page code during backend or operational app tasks unless explicitly approved.

## Protected Documentation Rule

- Do not expose generated PDFs through direct public UI links.
- Use owner-protected routes for PDF access.
- Markdown source docs are reviewed development artifacts.
- The app must not silently rewrite Markdown source docs.

## Production Memory And Render Stability

Render memory is a hard production budget. Treat a 512 MB service as constrained and design routes, services, and assets accordingly.

Strict rules:

- Do not load, parse, or cache complete large datasets at startup or on a normal first request when a scoped lookup, streaming parser, pagination, or bounded cache can be used.
- Do not keep both raw and transformed copies of large JSON, CSV, Excel, PDF, image, or uploaded payloads in memory unless explicitly justified and validated.
- Do not run duplicate template renders in production request paths. Diagnostic pre-renders must be removed or gated behind an explicit environment flag.
- Do not emit stage-by-stage debug logs at warning level during normal traffic. Production diagnostics must be opt-in and should use appropriate log levels.
- Filter by tenant, school group, branch, academic year, and permission scope before materializing query results.
- Keep caches bounded by size or scope. Global caches for user-facing lookup data must be justified by measured memory impact.
- Large exports should stream or build bounded artifacts; avoid repeatedly constructing large in-memory workbooks, PDFs, or payloads inside loops.
- New static assets, videos, generated files, and location/reference datasets must be reviewed for repository size, runtime memory, and deployment impact.
- Any feature that adds broad data aggregation, new startup work, large reference files, or route-level diagnostics must include a memory/performance smoke check before deployment.

Minimum validation for memory-sensitive changes:

- run targeted tests for the touched module,
- run a compile/import check for changed Python modules,
- measure peak memory locally when a route or service parses large data,
- review production logs after deployment for restarts, OOM symptoms, and unexpected warning spam.

## Commit And Push Rule

- Do not commit unless explicitly requested.
- Do not push unless explicitly requested.
- Do not merge unless explicitly requested.
- Final reports should describe changes and validation clearly.

## KMS Update Rule

Every meaningful implementation must update KMS if affected:

- `docs/TIS_MASTER_CONTEXT.md`,
- `docs/PROJECT_STATE.md`,
- `docs/CHANGE_HISTORY.md`,
- `docs/AI_PROJECT_CONTEXT.md`,
- ADRs if major decisions changed,
- module history for module-specific before/after state,
- engineering docs if module maps, architecture, data model, standards, design philosophy, roadmap, or flows changed.

Regenerate the PDF if included docs changed.

## Knowledge Impact Assessment

Every final implementation report must include:

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

A task is not complete until KIA is assessed.

## Validation Standards

Run the narrowest meaningful validation:

- compile checks for Python scripts/modules,
- targeted pytest tests when behavior changes,
- route/template smoke checks when pages are touched,
- PDF generation when docs change,
- frontend checks when landing/frontend code changes.

If validation cannot be run, say why.
