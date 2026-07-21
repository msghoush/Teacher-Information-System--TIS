---
title: TIS AI Coding Workflow
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS AI Coding Workflow

This guide defines how future AI assistants should work inside TIS.

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
