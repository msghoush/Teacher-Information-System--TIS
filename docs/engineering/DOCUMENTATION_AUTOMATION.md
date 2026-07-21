---
title: TIS Documentation Automation
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Documentation Automation

This document defines current and future automation expectations for the TIS KMS.

## Current Automation

Current approved automation:

- `scripts/generate_docs_pdf.py` reads approved Markdown sources.
- It generates `static/docs/TIS_Project_Reference_Booklet.pdf`.
- It generates `static/docs/docs_manifest.json`.
- The manifest records documentation version, branch, commit SHA, source paths, mtimes, sizes, and hashes.
- The manifest records the generated PDF hash and size.
- Markdown source hashes are computed from UTF-8 text normalized to LF, so equivalent CRLF and LF checkouts produce the same hash.
- Manifest source paths are repository-relative POSIX paths; dynamically discovered sources use a stable case-insensitive sort with an explicit tie-breaker.
- `scripts/generate_docs_pdf.py --check` validates source coverage, source hashes, PDF identity, manifest metadata, and documentation version without writing files.
- `.kms-impact.yml` records task-level Knowledge Impact in a small machine-readable schema.
- `scripts/check_kms_impact.py` classifies likely major changes, validates the declaration against the Git diff, and runs generated-artifact freshness checks.
- GitHub Actions enforce KMS checks on pull requests, `dev` pushes, and before `master` deployment.
- The Knowledge Center reads the manifest and checks freshness.

Repository owners must configure the `KMS Enforcement / kms-check` status as a required branch-protection check for protected integration branches. Workflow code makes production deployment depend on KMS validation directly; GitHub branch protection is the external setting that makes failed pull requests unmergeable.

Current automation does not:

- rewrite Markdown docs,
- create ADRs,
- create module history entries,
- decide KIA outcomes,
- generate documentation prose,
- commit or push changes.

Automation blocks stale or undeclared work; humans and approved AI assistants remain responsible for reviewed Markdown updates.

Cross-platform normalization does not relax enforcement. Changed text still changes the source hash, and missing, unexpected, duplicate, or reordered source entries still fail validation.

## Git Event Task Boundaries

KIA declarations apply to an implementation task, not to an individual GitHub delivery event. A task may contain an implementation commit followed by one or more review or CI correction commits.

- Pull-request checks compare the pull-request base SHA with the actual pull-request head SHA.
- Push checks on `dev` calculate the merge base between the repository default branch and the pushed head, then compare that merge base with the pushed head.
- Push checks must not use `github.event.before` as the KIA base because it represents only the latest delivery and can split a multi-commit task.
- Both event types use three-dot comparison and validate every changed KMS Markdown file against the cumulative declaration.

This preserves strict checks for undeclared, missing, or falsely declared documentation while allowing a follow-up commit to modify only the subset relevant to that correction.

## Machine-Readable KIA Declaration

Every task updates `.kms-impact.yml`:

```yaml
knowledge_impact: yes
summary: Describe the implemented engineering change.
affected_areas:
  - subscriptions
kms_files_updated:
  - docs/CHANGE_HISTORY.md
no_impact_reason:
major_change_override: no
```

Rules:

- `yes` requires changed authoritative `docs/*.md` files.
- `no` requires a specific reason and no declared KMS Markdown changes.
- a detected major path with `no` also requires `major_change_override: yes`.
- every changed authoritative Markdown file must be listed.
- generated PDF and manifest must be current in both cases.

## When Documentation Must Be Updated

Mandatory updates are required when a task changes:

- architecture,
- data model,
- tenant isolation,
- identity boundaries,
- SaaS/account flows,
- billing/payment/provisioning,
- operational modules,
- platform owner behavior,
- UI/UX philosophy,
- landing strategy,
- roadmap,
- governance,
- development standards,
- KMS behavior.

Optional updates may be skipped for:

- typo-only code comments,
- internal refactors with no behavior, architecture, flow, or ownership change,
- generated files that do not affect source truth.

Even when docs are skipped, KIA must explain why.

## Regeneration Command

Use:

```powershell
.\.venv\Scripts\python.exe scripts\generate_docs_pdf.py
```

Validation:

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\generate_docs_pdf.py
.\.venv\Scripts\python.exe scripts\generate_docs_pdf.py --check
.\.venv\Scripts\python.exe scripts\check_kms_impact.py
```

## Manifest Lifecycle

The manifest is generated every time the PDF is regenerated.

It should be treated as:

- generated metadata,
- source freshness basis,
- Knowledge Center input,
- not the source of truth.

If included Markdown docs change and the manifest is not regenerated, the Knowledge Center should show stale status.

## PDF Lifecycle

The PDF is:

- a generated snapshot,
- owner reference material,
- a reviewable artifact,
- not manually edited.

Regenerate after included Markdown docs change.

## AI Context Lifecycle

Update `docs/AI_PROJECT_CONTEXT.md` when:

- first-read onboarding changes,
- current priority changes,
- critical rules change,
- new major docs are added,
- architecture/identity/flow truth changes.

Do not overload AI context with every detail. It is a compact entry point.

## Handbook Lifecycle

Update engineering handbook docs when:

- module boundaries change,
- repository ownership changes,
- user/system flows change,
- database concepts change,
- standards change,
- design philosophy changes,
- roadmap changes,
- governance changes.

## Module History Lifecycle

Update module history when:

- a specific module's previous documented state should be preserved,
- a feature area changes meaningfully,
- before/after context matters for future implementers.

## ADR Lifecycle

Create or update ADRs when:

- major accepted decisions are made,
- accepted decisions are superseded,
- architecture or product boundaries change.

Use rejected decisions when important alternatives are intentionally declined.

## Mandatory vs Optional Summary

Mandatory:

- KIA in final report,
- docs update for meaningful changes,
- change history for meaningful changes,
- PDF/manifest regeneration when included docs change.

Conditional:

- ADR for major decisions,
- module history for area-specific state changes,
- AI context for first-read truth changes,
- engineering docs for handbook-level knowledge changes.

Optional:

- visual docs until screenshots/diagrams are approved,
- local Git hooks; CI is authoritative because hooks are optional and bypassable.
- future search, semantic indexing, and documentation analytics.
