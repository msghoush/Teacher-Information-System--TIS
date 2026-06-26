---
title: TIS AI Optimization Guide
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS AI Optimization Guide

This is the definitive onboarding guide for future AI assistants working on TIS.

## Preferred Onboarding Order

For any new AI coding conversation:

1. Read `docs/AI_PROJECT_CONTEXT.md`.
2. Read `docs/README.md`.
3. Read `docs/PROJECT_STATE.md`.
4. Read `docs/TIS_MASTER_CONTEXT.md`.
5. Read `docs/engineering/README.md`.
6. Read task-specific engineering docs.
7. Read relevant ADRs.
8. Read relevant module history.
9. Inspect code with `rg` before editing.

## Choosing Task-Specific Docs

Use this map:

- SaaS signup/login/account: `docs/history/saas-onboarding/`, ADR 0002.
- Billing/payment/Paddle: `docs/history/subscriptions/`, ADR 0003, ADR 0004.
- Provisioning: `docs/history/provisioning/`, ADR 0005.
- Landing page: `docs/marketing/`, ADR 0001, ADR 0007.
- Platform owner/Knowledge Center: `docs/history/platform-knowledge/`.
- Workforce planning/timetable/teachers/subjects: `docs/history/workforce-planning/`.
- Calendar: `docs/history/academic-calendar/`.
- Architecture/data model: `docs/engineering/REPOSITORY_ARCHITECTURE.md`, `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`.
- Design/UI: `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md`.
- Standards: `docs/engineering/DEVELOPMENT_STANDARDS.md`.
- Roadmap: `docs/engineering/PRODUCT_ROADMAP.md`.

## How To Interpret ADRs

ADRs explain accepted long-term decisions.

When an ADR applies:

- treat it as design authority,
- do not reverse it casually,
- if a change conflicts with it, propose a new ADR or mark it superseded only with approval,
- link related docs/history.

## How To Use Module History

Module history preserves deeper before/after context.

Before changing a module:

- read the module history folder,
- identify the previous documented state,
- update it if the module's meaning changes,
- do not replace chronological `CHANGE_HISTORY.md` with module history.

## How To Complete KIA

Every final response must include:

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

If meaningful behavior, architecture, workflow, roadmap, design, data model, or product state changes, documentation probably changed too.

## Avoiding Architectural Regressions

Do not:

- merge SaaS account identity with operational users,
- treat checkout return as verified payment,
- provision tenants immediately from public signup,
- expose internal docs publicly,
- let platform developers act as platform owners,
- modify landing code during backend tasks,
- rewrite source docs from the running app,
- change database/migrations without explicit approval.

## Preserving Tenant Isolation

Always identify:

- school group,
- branch,
- academic year,
- current user,
- user type,
- role/permissions,
- whether the user is platform, tenant, or SaaS account.

If scope is unclear, inspect code and tests before editing.

## Distinguishing Operational vs SaaS Code

Operational app:

- root FastAPI files,
- `routers/`,
- `templates/` operational templates,
- `models.py`,
- branch/year/teacher/planning/calendar/observation workflows.

SaaS:

- `saas/`,
- `templates/saas/`,
- signup/login/account/onboarding/billing/provisioning readiness.

Landing:

- `tis-landing-website/`,
- `docs/marketing/`.

KMS:

- `docs/`,
- `scripts/generate_docs_pdf.py`,
- `knowledge_service.py`,
- `templates/platform_knowledge_center.html`,
- `static/docs/`.

## Prompt Engineering Recommendations

Future prompts should specify:

- implementation vs planning,
- allowed files,
- forbidden files,
- whether docs must be updated,
- whether PDF regeneration is required,
- whether routes/app behavior can change,
- whether database/migrations are in scope,
- whether landing is in scope.

Good prompt pattern:

```text
Implement [specific goal].
Allowed files: [...]
Do not modify: [...]
Update KMS docs and regenerate PDF if docs change.
Run: [...]
Report KIA.
```

## AI Readiness Review

Current strengths:

- AI context exists.
- Engineering docs cover modules, repository, flows, database, standards, UI/UX, roadmap, rejected decisions, governance, and visual docs.
- ADRs and module history preserve decision context.
- PDF/manifest provide generated snapshot and freshness metadata.

Remaining gaps for future KMS improvements:

- More screenshots and diagrams are needed.
- More module-specific deep docs may be useful for timetable, observations, permissions, and dashboard/reporting.
- Test strategy documentation could be expanded.
- Deployment/runbook documentation could be expanded.
- API/route inventory could be generated or manually documented later.
- Data migration history could be summarized more explicitly.

Do not implement these gaps unless a future phase approves them.
