---
title: TIS Documentation Index
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Documentation

This folder is the source of truth for the TIS Knowledge Management System (KMS).

Markdown files are authoritative. The PDF booklet is a generated snapshot and must never be edited manually.

Repository enforcement begins with root `AGENTS.md` and `.kms-impact.yml`. `scripts/check_kms_impact.py` validates the declaration, changed paths, declared Markdown updates, and generated artifacts. It never rewrites documentation.

## Choose A Reading Path

Open the [KMS Navigation Guide](KMS_NAVIGATION.md) to select a focused reading path by role or task. It covers human and AI onboarding, SaaS and subscriptions, operational modules, database work, Platform Owner tools, the public landing website, location data, design, architecture decisions, and review/KIA work.

For a fast baseline, read:

1. [AI Project Context](AI_PROJECT_CONTEXT.md)
2. [TIS Master Context](TIS_MASTER_CONTEXT.md)
3. [Project State](PROJECT_STATE.md)
4. [Documentation Update Policy](DOCUMENTATION_UPDATE_POLICY.md)

Then follow the relevant task path rather than loading the entire handbook.

## Core Documents

- [KMS Navigation Guide](KMS_NAVIGATION.md): role-based and task-based routes through the KMS.
- [AI Project Context](AI_PROJECT_CONTEXT.md): compact onboarding file for future Codex and ChatGPT conversations.
- [TIS Master Context](TIS_MASTER_CONTEXT.md): long-term product, architecture, SaaS, workflow, roadmap, and critical-rules source of truth.
- [Project State](PROJECT_STATE.md): living status for branch strategy, priorities, milestones, known issues, and next work.
- [Documentation Update Policy](DOCUMENTATION_UPDATE_POLICY.md): non-negotiable KMS and Knowledge Impact Assessment policy.
- [Change History](CHANGE_HISTORY.md): chronological summary of meaningful changes.

## Engineering Handbook

Use the [Engineering Handbook Index](engineering/README.md) for the full engineering document map.

Primary engineering references:

- [TIS Module Map](engineering/TIS_MODULE_MAP.md)
- [Repository Architecture](engineering/REPOSITORY_ARCHITECTURE.md)
- [User and System Flows](engineering/USER_AND_SYSTEM_FLOWS.md)
- [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)
- [Development Standards](engineering/DEVELOPMENT_STANDARDS.md)
- [UI/UX Design Philosophy](engineering/UI_UX_DESIGN_PHILOSOPHY.md)
- [Product Roadmap](engineering/PRODUCT_ROADMAP.md)

## Decision And History Documents

- [ADR Index](adr/README.md): Architecture Decision Records for major accepted decisions.
- [Rejected Decisions](engineering/REJECTED_DECISIONS.md): significant alternatives and why they were declined.
- [Module History Index](history/README.md): module-based history preserving deeper before/after context.

Current module history areas:

- [Subscriptions](history/subscriptions/README.md)
- [Landing Page](history/landing-page/README.md)
- [Academic Calendar](history/academic-calendar/README.md)
- [Workforce Planning](history/workforce-planning/README.md)
- [SaaS Onboarding](history/saas-onboarding/README.md)
- [Provisioning](history/provisioning/README.md)
- [Platform Knowledge](history/platform-knowledge/README.md)
- [Engineering Handbook](history/engineering-handbook/README.md)

## Supporting Documents

- [Location Data Roadmap](location-data-roadmap.md): location data roadmap and related implementation notes.
- [Landing Page Source of Truth](marketing/landing_page_source_of_truth.md): boundary between the public Next.js landing website and the FastAPI application portal.
- [Landing Page Master Content](marketing/tis_landing_page_master_content.md): approved marketing foundation and landing page content direction.

## Generated Snapshot

Generated files:

- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

The PDF is generated from approved Markdown docs. It includes a handbook-use page, a page-numbered table of contents, source-document bookmarks, and child bookmarks for major headings. The manifest records the generated timestamp, documentation version, branch, commit SHA, included sources, source hashes, and each source document's starting PDF page.

## KMS Synchronization

Validate KIA, regenerate the PDF and manifest, and verify freshness with:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py sync
```

Complete read-only validation:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py check
```

The command reuses the dependency-light generator and strict impact checker. It must not require LaTeX, Playwright, Chromium, network calls, or system fonts.

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

Update `.kms-impact.yml` during every task. CI validates it on pull requests and `dev`; deployment from `master` depends on the same KMS gate.

## Phase Boundary

Phase 2A and Phase 2B establish KMS governance, ADRs, module history, AI context, and PDF/manifest generation.

KMS v3.0 Phase 3D completes the KMS v1.0 lifecycle foundation with self-evolving documentation workflow, KIA standard, dependency map, AI coding workflow, and future automation roadmap. The Platform Owner Knowledge Center is implemented as a read-only owner utility. Do not add a regenerate button or app-side Markdown rewriting unless explicitly approved.
