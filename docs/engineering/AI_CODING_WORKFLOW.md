---
title: TIS AI Coding Workflow
documentation_version: 3.4
last_updated: 2026-09-05
source_of_truth: true
---

# TIS AI Coding Workflow

This guide defines how future AI assistants should work inside TIS.

## Repository-Native Assistant Configuration

Root `AGENTS.md` remains the repository-wide governance authority. Claude Code
also reads root `CLAUDE.md`; its reusable project workflow lives at
`.claude/skills/tis-kms/SKILL.md`, and bounded delegated TIS work may use
`.claude/agents/tis-kms-developer.md`. These files point assistants back to this
KMS rather than embedding a separate architectural source of truth. Configuration
for another assistant must preserve the same KIA, safety, validation, and
completion-report requirements.

## Cline Setup And Use

Cline uses `.clinerules/tis.md` as always-on project rules and
`.cline/skills/tis-kms-developer/SKILL.md` as its reusable project skill.
Both defer to AGENTS.md and KMS, including task-level KIA, focused validation,
sync/check, worktree/database safety, and deployment reporting.

Open TIS as the primary workspace folder. In Cline's Rules/Skills panel, ensure
the TIS project rule and skill are enabled; enable Skills in Settings > Features
if that option is present. Start a new task and select `/tis-kms-developer` from
slash suggestions, or ask to use the named skill. If it is not listed, explicitly
ask Cline to read the skill file; project rules still apply. The literal Codex
`$tis-kms-developer` token is not a documented Cline invocation.

Check for a global skill with the same name, because Cline gives it precedence.
Cline can also discover `.claude/skills/tis-kms/`; it describes the same KMS
workflow and is not a second authority. Prefer the explicit Cline skill for Cline
tasks. No user-global settings, provider, account, or auto-approval defaults are
changed by these repository files.

Compatibility evidence (2026-09-05): installed VS Code Cline extension 4.1.17
includes SKILL.md parsing and use_skill support. Current official documentation
supports project rules, recommended .cline/skills storage, and slash invocation:
- [Cline rules](https://docs.cline.bot/customization/cline-rules)
- [Cline skills](https://docs.cline.bot/customization/skills)
- [Current upstream skills documentation](https://github.com/cline/cline/blob/main/docs/customization/skills.mdx)

Runtime discovery and toggles depend on the active Cline session; file validation
does not prove that a UI session has activated the skill.

Task allocation follows [Project Governance](PROJECT_GOVERNANCE.md): Codex,
Claude Code, and Cline/ClinePass are three capable developers, balanced by
complexity, specialization, risk, independent review, and current usage/load.

## Planning Before Coding

AI assistants must:

- follow root `AGENTS.md`,
- read `docs/AI_PROJECT_CONTEXT.md`,
- read relevant engineering docs,
- read relevant ADRs/module history,
- inspect the codebase with `rg`,
- identify allowed and forbidden files,
- identify likely KMS impact,
- update `.kms-impact.yml` for the current task,
- avoid starting from assumptions.

## Implementation Review Before Editing

Before editing:

- confirm the module boundary,
- confirm tenant/identity/payment/provisioning risk,
- confirm tests or validation,
- confirm docs to update,
- confirm that app, SaaS, landing, database, or routes are in scope before touching them.

## Implementation

During implementation:

- keep changes narrow,
- follow existing patterns,
- avoid unrelated rewrites,
- use `apply_patch` for manual edits,
- do not commit or push,
- do not modify `tis.db` unless explicitly approved.

## Validation Expectations

Run appropriate validation:

- compile checks for Python scripts/modules,
- targeted tests for behavior,
- PDF generation for docs,
- template/route smoke checks for UI routes,
- frontend checks for landing/frontend tasks.

If validation cannot be run, state why.

## Documentation Updates

AI assistants must update KMS when knowledge changes:

- change history,
- project state,
- master context,
- AI context,
- engineering docs,
- ADRs/rejected decisions,
- module history.

## KIA

Every final response must include KIA.

Do not omit KIA because the task "felt small." Assess it.

The machine-readable declaration must agree with the final KIA and actual changed Markdown. Use the explicit major-change override only for a genuinely non-behavioral change and provide a specific explanation.

## Commit Strategy

AI assistants must not commit unless the user explicitly asks.

When committing is approved:

- summarize scope,
- ensure generated docs are current,
- avoid unrelated changes,
- use clear commit messages.

## Push Strategy

AI assistants must not push unless explicitly asked.

Before pushing:

- confirm branch,
- confirm tests/checks,
- confirm KMS artifacts,
- run `scripts/kms.py sync` when documentation changed and `scripts/kms.py check` for final read-only enforcement,
- confirm no forbidden files changed.

## Deployment Strategy

AI assistants must not deploy unless explicitly asked.

Before deployment:

- confirm production branch/environment,
- confirm database/migration implications,
- confirm SaaS/payment/provisioning risks,
- confirm KMS state,
- confirm rollback or recovery expectations.

## Final Response Pattern

Include:

- files changed,
- behavior changed or not,
- validation,
- known issues,
- KIA,
- no vague claims about tests that were not run.
