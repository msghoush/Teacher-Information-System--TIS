---
title: Claude Code KMS Configuration
module: engineering-handbook
last_updated: 2026-09-03
---

# Claude Code KMS Configuration

## Previous state

TIS had repository-wide `AGENTS.md`, authoritative KMS onboarding, and automated
KIA enforcement, but no repository-native Claude Code entry point, project skill,
or specialized subagent definition.

## New state

Root `CLAUDE.md` directs Claude Code to the existing repository and KMS authorities.
`.claude/skills/tis-kms/SKILL.md` packages the reusable TIS investigation,
implementation, validation, KIA, synchronization, and reporting workflow.
`.claude/agents/tis-kms-developer.md` provides the same safeguards for bounded
delegated work.

The configuration preserves existing worktree changes, tenant and academic scope,
permissions, publication history, audit boundaries, database safety, and the
no-commit/no-push default. It does not introduce a competing architecture source or
change application, schema, migration, customer, production, or deployment behavior.

## Validation contract

Claude Code must run proportional implementation checks, `git diff --check`, KMS
sync after authoritative Markdown changes, and final read-only KMS validation. Its
completion report includes exact KMS files and the Knowledge Impact Assessment.
