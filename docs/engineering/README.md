---
title: TIS Engineering Handbook
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS Engineering Handbook

This folder turns the TIS KMS into a practical engineering handbook. It is intended for new human developers, future Codex conversations, future ChatGPT conversations, project owners, platform owners, and reviewers.

## Choose A Reading Path

Use the [KMS Navigation Guide](../KMS_NAVIGATION.md) to select the smallest relevant document set for a specific task.

For a broad engineering onboarding, read:

Recommended onboarding order:

1. [AI Project Context](../AI_PROJECT_CONTEXT.md)
2. [TIS Master Context](../TIS_MASTER_CONTEXT.md)
3. [Project State](../PROJECT_STATE.md)
4. [TIS Module Map](TIS_MODULE_MAP.md)
5. [Repository Architecture](REPOSITORY_ARCHITECTURE.md)
6. [User and System Flows](USER_AND_SYSTEM_FLOWS.md)
7. [Database Architecture Overview](DATABASE_ARCHITECTURE_OVERVIEW.md)
8. Relevant [ADRs](../adr/README.md) and [module history](../history/README.md)

## Engineering Documents

- [TIS Module Map](TIS_MODULE_MAP.md): product and system modules, maturity, ownership, risks, and guardrails.
- [Repository Architecture](REPOSITORY_ARCHITECTURE.md): repository structure and responsibilities.
- [User and System Flows](USER_AND_SYSTEM_FLOWS.md): end-to-end public, SaaS, payment, provisioning, operational, owner, and KMS flows.
- [Database Architecture Overview](DATABASE_ARCHITECTURE_OVERVIEW.md): conceptual data relationships and isolation boundaries.
- [Development Standards](DEVELOPMENT_STANDARDS.md): non-negotiable engineering rules for humans and AI assistants.
- [UI/UX Design Philosophy](UI_UX_DESIGN_PHILOSOPHY.md): design principles by product surface.
- [Product Roadmap](PRODUCT_ROADMAP.md): completed, current, next, and future roadmap.
- [Rejected Decisions](REJECTED_DECISIONS.md): significant declined alternatives and their consequences.
- [Visual Documentation Guide](VISUAL_DOCUMENTATION_GUIDE.md): screenshot and diagram standards.
- [AI Optimization Guide](AI_OPTIMIZATION_GUIDE.md): definitive AI onboarding and operating guide.
- [Project Governance](PROJECT_GOVERNANCE.md): ownership, approvals, quality gates, and traceability.
- [Knowledge Lifecycle](KNOWLEDGE_LIFECYCLE.md): documentation and engineering lifecycle.
- [Documentation Automation](DOCUMENTATION_AUTOMATION.md): current and future KMS automation rules.
- [KIA Standard](KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md): formal KIA examples, decision tree, and failure cases.
- [Self-Evolving Workflow](SELF_EVOLVING_WORKFLOW.md): official task-to-deployment workflow.
- [Documentation Dependency Map](DOCUMENTATION_DEPENDENCY_MAP.md): propagation rules across KMS documents.
- [AI Coding Workflow](AI_CODING_WORKFLOW.md): required workflow for future AI coding assistants.
- [Future Automation Roadmap](FUTURE_AUTOMATION_ROADMAP.md): possible future automation improvements.

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

If included source docs changed, synchronize:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py sync
```

Run `.\.venv\Scripts\python.exe scripts\kms.py check` for final read-only validation.
