---
title: TIS Documentation Index
documentation_version: 2.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Documentation

This folder is the source of truth for the TIS Knowledge Management System (KMS).

Markdown files are authoritative. The PDF booklet is a generated snapshot and must never be edited manually.

## First Read For AI Coding Conversations

For any new Codex or ChatGPT coding conversation, load this file first:

- `docs/AI_PROJECT_CONTEXT.md`

Then load:

- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/DOCUMENTATION_UPDATE_POLICY.md`
- relevant ADRs under `docs/adr/`
- relevant module history under `docs/history/`

If the task touches the public website, also read:

- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`
- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`

## Core Documents

- `docs/AI_PROJECT_CONTEXT.md`: compact onboarding file for future Codex and ChatGPT conversations.
- `docs/TIS_MASTER_CONTEXT.md`: long-term product, architecture, SaaS, workflow, roadmap, and critical-rules source of truth.
- `docs/PROJECT_STATE.md`: living status file for branch strategy, priority, milestones, known issues, and next work.
- `docs/DOCUMENTATION_UPDATE_POLICY.md`: non-negotiable KMS and Knowledge Impact Assessment policy.
- `docs/CHANGE_HISTORY.md`: chronological summary of meaningful changes.

## Decision And History Documents

- `docs/adr/`: Architecture Decision Records for major accepted decisions.
- `docs/history/`: module-based history preserving deeper before/after context.

Current module history areas:

- `docs/history/subscriptions/`
- `docs/history/landing-page/`
- `docs/history/academic-calendar/`
- `docs/history/workforce-planning/`
- `docs/history/saas-onboarding/`
- `docs/history/provisioning/`
- `docs/history/platform-knowledge/`

## Supporting Documents

- `docs/location-data-roadmap.md`: location data roadmap and related implementation notes.
- `docs/marketing/landing_page_source_of_truth.md`: boundary between the public Next.js landing website and the FastAPI application portal.
- `docs/marketing/tis_landing_page_master_content.md`: approved marketing foundation and landing page content direction.

## Generated Snapshot

Generated files:

- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

The PDF is generated from approved Markdown docs. The manifest records the generated timestamp, documentation version, branch, commit SHA, included sources, and source hashes.

## PDF Generation

Regenerate the PDF booklet with:

```powershell
.\.venv\Scripts\python.exe scripts\generate_docs_pdf.py
```

The generator uses existing `reportlab` only. It must not require LaTeX, Playwright, Chromium, network calls, or system fonts.

## Knowledge Impact Assessment

Every future implementation report must include:

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

A task is not complete until KIA is assessed. If included source docs change, regenerate the PDF.

## Phase Boundary

Phase 2A and Phase 2B establish KMS governance, ADRs, module history, AI context, and PDF/manifest generation.

The Platform Owner Knowledge Center is implemented as a read-only owner utility. Do not add a regenerate button or app-side Markdown rewriting unless explicitly approved.
