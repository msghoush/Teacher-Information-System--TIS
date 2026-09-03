# TIS Claude Code Instructions

Work only within the Teacher Information System (TIS) repository and treat the
repository KMS as the durable source of project knowledge.

## Required onboarding

Before investigating or changing the repository:

1. Read `AGENTS.md` completely and follow it.
2. Read `docs/AI_PROJECT_CONTEXT.md`, `docs/TIS_MASTER_CONTEXT.md`, and
   `docs/PROJECT_STATE.md`.
3. Read the relevant engineering documents, ADRs, and module history.
4. Inspect the affected implementation and tests before editing.
5. Establish the current branch, commit, working-tree state, and deployment
   boundary. Preserve every unrelated or pre-existing change.
6. Assess likely knowledge impact and update `.kms-impact.yml` for the current
   task.

Use the project skill at `.claude/skills/tis-kms/SKILL.md` for TIS work. The
specialized subagent at `.claude/agents/tis-kms-developer.md` may be used for a
bounded delegated TIS investigation or implementation task when delegation is
useful.

## Non-negotiable boundaries

- Preserve SchoolGroup, tenant, branch, academic-year, permission,
  publication, and audit boundaries.
- Never place customer, organization, personal, billing, production,
  credential, secret, environment, webhook, or database-row data in KMS docs.
- Do not modify `tis.db` without explicit approval.
- Do not commit, push, merge, deploy, mutate production data, or communicate
  externally unless the user explicitly requests that exact action.
- Do not broaden work into SaaS, operational logic, migrations, or the landing
  site unless the task explicitly includes that area.
- For Render-backed timetable work, distinguish the Web Service revision from
  the separate `tis-timetable-workflow` revision.

## Implementation and validation

Make the smallest coherent change, follow existing patterns, and add or update
focused tests for behavior changes. Use `rg` for discovery. Do not overwrite
unrelated work.

Complete `.kms-impact.yml` honestly. If knowledge impact is `yes`, update only
the affected authoritative Markdown and run:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py sync
```

Always finish with proportional implementation validation, `git diff --check`,
and the read-only KMS check:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py check
```

Report the objective or root cause, files changed, exact test results, KMS
impact and KMS files updated, migration/database status when applicable,
deployment risks, readiness to commit, and whether Web and Workflow must deploy
together.
