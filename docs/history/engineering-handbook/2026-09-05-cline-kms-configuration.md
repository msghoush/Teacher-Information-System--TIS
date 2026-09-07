---
title: Cline KMS Configuration And Three-Agent Orchestration
module: engineering-handbook
last_updated: 2026-09-05
---

# Cline KMS Configuration And Three-Agent Orchestration

## Previous State

TIS had AGENTS.md, KMS enforcement, Codex onboarding, and Claude Code's repository
entry point, skill, and subagent. It lacked native Cline project configuration.

## New State And Reason

User-approved Cline rules at `.clinerules/tis.md` and the project skill at
`.cline/skills/tis-kms-developer/SKILL.md` reuse the existing KMS authority.
They require investigation before assumptions, minimal changes, isolation/RBAC,
database/worktree preservation, destructive dependency/transaction checks,
proportional tests, KIA, sync/check, and explicit release authorization.

The master conversation balances Codex, Claude Code, and Cline/ClinePass by
complexity, specialization, risk, review independence, and current usage/load.
Each is a capable developer; preferred tendencies do not create rigid ownership.
See [Project Governance](../../engineering/PROJECT_GOVERNANCE.md) and
[AI Coding Workflow](../../engineering/AI_CODING_WORKFLOW.md) for policy and usage.

## Technical And Deployment Impact

Development configuration/documentation only: no application, schema, migration,
database, production, or worker-contract change. Deployment impact: none.
Shared solver/worker changes in future tasks require Web + Workflow from the
same commit; web-only router/template/state changes require Web only when the
worker contract is unchanged.

## Knowledge And Validation

AI context, master context, project state, change history, engineering workflow,
governance, and this module history record the change. The then-existing M9 KIA state was preserved without modification as part of this configuration-only task. Sync regenerates PDF/manifest from all current KMS
Markdown; no generated artifact is manually edited. No new ADR is needed:
this extends the existing assistant integration under ADR 0006 without replacing
KMS authority, approval gates, or deployment architecture.

Validate skill metadata and referenced paths, KMS sync/check, existing focused
KMS automation tests, and git diff --check. Live Cline discovery/toggles must be
distinguished from static file validation; setup is documented in the workflow.
