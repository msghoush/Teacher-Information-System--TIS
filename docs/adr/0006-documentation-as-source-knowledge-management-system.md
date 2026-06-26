---
adr: 0006
title: Documentation As Source / Knowledge Management System
status: Accepted
date: 2026-06-26
---

# ADR 0006: Documentation As Source / Knowledge Management System

Status: Accepted

Date: 2026-06-26

## Context

TIS is growing across product, SaaS, architecture, payment, provisioning, landing, and operational modules. Future humans and AI coding assistants need reliable context and change history.

## Decision

Use Markdown files under `docs/` as the source of truth. Generate the PDF booklet as a snapshot. Maintain change history, ADRs, module history, project state, master context, and AI project context as part of every meaningful development task.

## Alternatives Considered

- Keep knowledge only in chat history.
- Keep only a generated PDF.
- Let the app rewrite docs automatically.
- Store decisions only in commits.

## Consequences

Positive:

- Project knowledge is reviewable and version-controlled.
- Future Codex and ChatGPT conversations can onboard quickly.
- Major decisions are preserved.

Tradeoffs:

- Developers must maintain the KIA workflow.
- Docs and PDF can become stale if the policy is ignored.

## Related Docs / Files

- `docs/README.md`
- `docs/DOCUMENTATION_UPDATE_POLICY.md`
- `docs/CHANGE_HISTORY.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
