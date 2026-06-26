---
title: TIS Documentation Automation
documentation_version: 3.0
last_updated: 2026-06-26
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
- The Knowledge Center reads the manifest and checks freshness.

Current automation does not:

- rewrite Markdown docs,
- create ADRs,
- create module history entries,
- decide KIA outcomes,
- commit or push changes.

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
- future CI/hooks/search automation until approved.
