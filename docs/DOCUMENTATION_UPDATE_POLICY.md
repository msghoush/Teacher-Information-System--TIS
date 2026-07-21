---
title: TIS Documentation Update Policy
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Documentation Update Policy

This policy defines the non-negotiable rules for keeping the TIS Knowledge Management System reliable.

## Source Of Truth

Markdown files under `docs/` are the source of truth.

The PDF booklet at `static/docs/TIS_Project_Reference_Booklet.pdf` is a generated snapshot. It must never be edited manually. It must be regenerated whenever included Markdown source files change.

## Required Knowledge Impact Assessment

Every approved implementation must end with a Knowledge Impact Assessment (KIA).

Required final report template:

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

A task is not complete until the KIA is included, even when no documentation changes are needed.

Every task must also update `.kms-impact.yml`. The declaration is the machine-readable form of the KIA and records `knowledge_impact`, a summary, affected areas, KMS files updated, a no-impact reason, and the explicit major-change override. `scripts/check_kms_impact.py` validates it against the actual Git diff.

`knowledge_impact: yes` requires changed authoritative Markdown. `knowledge_impact: no` requires a specific reason. When a path is conservatively classified as major but the change is genuinely non-behavioral, `major_change_override: yes` is allowed only with that written reason.

## When Documentation Must Be Updated

Update documentation when a task changes:

- product vision or positioning,
- architecture or module boundaries,
- SaaS signup, login, onboarding, billing, payment, or provisioning flows,
- platform owner or permission behavior,
- operational workflows such as calendar, planning, timetable, teachers, subjects, or observations,
- deployment assumptions,
- branch/release/project status,
- landing page source-of-truth or visual strategy,
- roadmap or known issues,
- documentation system behavior.

## Which Docs To Update

Use this guide:

- `docs/AI_PROJECT_CONTEXT.md`: compact onboarding context for future AI coding conversations; update when the high-level project situation changes.
- `docs/TIS_MASTER_CONTEXT.md`: durable product, architecture, workflow, roadmap, and critical rules.
- `docs/PROJECT_STATE.md`: current branch strategy, priorities, milestone status, known issues, and next work.
- `docs/CHANGE_HISTORY.md`: chronological summary of meaningful changes.
- `docs/adr/`: major architectural or product decisions.
- `docs/history/`: deeper module-specific before/after history.
- Supporting docs under `docs/marketing/` or other folders when those areas change.

## ADR Rule

Create or update an ADR when a change affects a major long-term decision, including identity boundaries, payment architecture, provisioning strategy, deployment architecture, public website architecture, documentation governance, or visual system strategy.

Do not create ADRs for routine bug fixes unless they introduce or reverse a significant decision.

## Module History Rule

Update `docs/history/<module>/` when a meaningful module area changes and the previous documented state should be preserved.

`docs/CHANGE_HISTORY.md` remains the chronological summary. Module history stores deeper context.

## KMS Synchronization

Validate KIA, regenerate the PDF and manifest, and verify freshness with:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py sync
```

The generator must remain dependency-light:

- use existing `reportlab`,
- no LaTeX,
- no Playwright or Chromium,
- no external network calls,
- no system font dependency.

Complete read-only validation:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py check
```

The `check` command must never write documentation. GitHub Actions run it for pull requests and `dev`; the production deployment workflow requires it before triggering deployment from `master`. The `sync` command writes generated artifacts only and never rewrites authoritative Markdown.

## Prohibited KMS Content

KMS documentation describes system design only. Never include customer or organization information, personal data, subscription rows, invoices, transactions, real production identifiers, real webhook payloads, credentials, secrets, environment values, database row contents, or test-customer personal details.

## Reporting Rule

Every final implementation report must mention:

- whether knowledge was impacted,
- which docs changed,
- whether change history changed,
- whether an ADR was needed,
- whether module history changed,
- whether the PDF was regenerated,
- whether `AI_PROJECT_CONTEXT.md` changed,
- validation results.

## App Behavior Rule

The application may later detect documentation freshness and expose docs through owner-only protected routes. It must not silently rewrite Markdown source docs. Source docs are edited through reviewed development work.
