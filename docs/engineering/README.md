---
title: TIS Engineering Handbook
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Engineering Handbook

This folder turns the TIS KMS into a practical engineering handbook. It is intended for new human developers, future Codex conversations, future ChatGPT conversations, project owners, platform owners, and reviewers.

## Read First

Recommended onboarding order:

1. `docs/AI_PROJECT_CONTEXT.md`
2. `docs/TIS_MASTER_CONTEXT.md`
3. `docs/PROJECT_STATE.md`
4. `docs/engineering/TIS_MODULE_MAP.md`
5. `docs/engineering/REPOSITORY_ARCHITECTURE.md`
6. `docs/engineering/USER_AND_SYSTEM_FLOWS.md`
7. Relevant ADRs under `docs/adr/`
8. Relevant module history under `docs/history/`

## Engineering Documents

- `TIS_MODULE_MAP.md`: product and system module map with purpose, files, maturity, docs, risks, and guardrails.
- `REPOSITORY_ARCHITECTURE.md`: repository structure and responsibilities.
- `USER_AND_SYSTEM_FLOWS.md`: end-to-end public, SaaS, payment, provisioning, operational, platform owner, and KMS flows.
- `DATABASE_ARCHITECTURE_OVERVIEW.md`: high-level data model relationships and isolation boundaries.
- `DEVELOPMENT_STANDARDS.md`: non-negotiable engineering rules for humans and AI assistants.
- `UI_UX_DESIGN_PHILOSOPHY.md`: design principles for operational app, platform owner tools, SaaS onboarding, Knowledge Center, and landing website.
- `PRODUCT_ROADMAP.md`: completed, current, next, and future roadmap.
- `REJECTED_DECISIONS.md`: significant rejected architectural/product alternatives and why they were declined.
- `VISUAL_DOCUMENTATION_GUIDE.md`: future screenshot and diagram standards.
- `AI_OPTIMIZATION_GUIDE.md`: definitive onboarding and operating guide for future AI assistants.
- `PROJECT_GOVERNANCE.md`: ownership, approvals, quality gates, documentation gates, and decision traceability.
- `KNOWLEDGE_LIFECYCLE.md`: documentation, engineering, approval, review, release, and maintenance lifecycle.
- `DOCUMENTATION_AUTOMATION.md`: current and future documentation automation rules.
- `KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md`: formal KIA standard with examples, decision tree, and failure cases.
- `SELF_EVOLVING_WORKFLOW.md`: official task-to-deployment workflow.
- `DOCUMENTATION_DEPENDENCY_MAP.md`: relationships and propagation rules across KMS documents.
- `AI_CODING_WORKFLOW.md`: required workflow for future AI coding assistants.
- `FUTURE_AUTOMATION_ROADMAP.md`: possible future automation improvements.

## Before Coding

Before changing code:

- confirm the approved scope,
- inspect affected files and tests,
- read relevant ADRs,
- read relevant module history,
- preserve tenant isolation,
- preserve identity boundaries,
- avoid touching SaaS, landing, database, or migrations unless explicitly approved.

## After Coding

Every implementation must complete the Knowledge Impact Assessment:

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

If included source docs changed, regenerate:

```powershell
.\.venv\Scripts\python.exe scripts\generate_docs_pdf.py
```
