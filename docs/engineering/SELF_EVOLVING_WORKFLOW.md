---
title: TIS Self-Evolving Workflow
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Self-Evolving Workflow

This is the official engineering workflow for keeping TIS software and knowledge synchronized.

## Workflow

```text
Task
  -> Implementation
  -> Validation
  -> Knowledge Impact Assessment
  -> Update .kms-impact.yml
  -> Documentation Updates
  -> ADR if required
  -> Module History if required
  -> Regenerate PDF
  -> Regenerate Manifest
  -> KMS Enforcement Check
  -> Review
  -> Commit
  -> Push
  -> Deployment
```

## Task

Clarify:

- objective,
- allowed files,
- forbidden files,
- validation requirements,
- documentation requirements,
- commit/push/deployment instructions.

## Implementation

Implement only the approved scope.

Protect:

- tenant isolation,
- identity boundaries,
- payment/provisioning correctness,
- owner-only controls,
- landing boundaries,
- database/migration safety.

## Validation

Run focused checks:

- compile checks,
- relevant tests,
- route/template smoke checks,
- PDF generation for docs,
- frontend checks if frontend is in scope.

## Knowledge Impact Assessment

Complete KIA before final report.

Do not treat documentation as optional when knowledge changed.

Record the same assessment in `.kms-impact.yml`. The declaration must change with the task and match the actual Git diff.

## Documentation Updates

Update relevant docs:

- master context,
- project state,
- AI context,
- engineering docs,
- change history,
- module history,
- ADRs/rejected decisions.

## ADR If Required

Create/update ADR when architecture or product boundaries change.

## Module History If Required

Update module history when area-specific before/after context matters.

## Regenerate PDF And Manifest

If included Markdown docs changed:

```powershell
.\.venv\Scripts\python.exe scripts\generate_docs_pdf.py
```

Then run:

```powershell
.\.venv\Scripts\python.exe scripts\generate_docs_pdf.py --check
.\.venv\Scripts\python.exe scripts\check_kms_impact.py
```

## Review

Reviewers check:

- scope,
- behavior,
- tests,
- KMS updates,
- generated artifacts,
- KIA.

CI repeats these checks and blocks pull-request completion, `dev` integration, or `master` deployment when declaration or freshness validation fails.

## Commit / Push / Deployment

These are explicit actions, not assumptions.

- Commit only when requested.
- Push only when requested.
- Deploy only through approved process.

## Why This Is Self-Evolving

The workflow makes knowledge updates part of engineering completion. The system evolves because every meaningful change carries its context, history, decisions, and generated reference forward.
