---
title: TIS Development Standards
documentation_version: 3.0
last_updated: 2026-06-26
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
