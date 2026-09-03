---
name: tis-kms
description: Develop, investigate, review, and document this TIS repository using its KMS governance, architecture boundaries, tests, and deployment safeguards.
---

# TIS KMS Developer Workflow

Use this skill only inside the Teacher-Information-System--TIS repository.

## Authority and context

Read `AGENTS.md` and `CLAUDE.md` completely before acting. Then read all required
KMS entry points:

- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- relevant engineering documents, ADRs, and module history

Treat the KMS as durable project knowledge, but verify the current code and tests.
When documentation and implementation disagree, report the mismatch and determine
which reflects deployed behavior rather than guessing.

## Scope and safety

- Establish the current branch, commit, working-tree status, and applicable
  deployment boundary.
- Preserve unrelated and pre-existing changes, including untracked files.
- Preserve SchoolGroup, tenant, branch, academic-year, permission, publication,
  and audit boundaries.
- Do not modify `tis.db` unless explicitly requested and repository rules allow it.
- Do not commit, push, merge, deploy, mutate production data, or send external
  communications unless explicitly requested.
- Treat investigation, explanation, review, and diagnosis as read-only unless a
  fix is also requested.
- For Render-backed timetable work, distinguish Web Service code from the
  separate `tis-timetable-workflow` revision and verify both when deployment
  consistency matters.

## Working method

Inspect relevant routes, models, templates, services, workflows, validators,
migrations, and focused tests before editing. Trace behavior end to end.

For implementation:

1. Make the smallest coherent change that satisfies the task.
2. Add or update focused tests for intended behavior and important failures.
3. Run tests in proportion to risk, followed by `git diff --check`.
4. Complete `.kms-impact.yml` honestly for the current task.
5. If knowledge impact is `yes`, update only affected authoritative KMS Markdown
   and run `.\.venv\Scripts\python.exe scripts\kms.py sync`.
6. Run `.\.venv\Scripts\python.exe scripts\kms.py check` as the final
   documentation verification.

Never edit generated KMS artifacts manually; synchronization owns them. Never put
customer, organization, personal, billing, invoice, transaction, production,
webhook, credential, secret, environment, database-row, or test-customer personal
data in KMS sources.

## Completion report

Lead with the outcome and report:

- root cause or behavior implemented;
- files changed;
- tests and exact results;
- KMS impact and exact KMS files updated;
- migration and local-database status when applicable;
- unresolved production or deployment risks;
- whether the result is ready to commit;
- whether Web and Workflow must deploy together.

Separate confirmed evidence from inference and from items requiring production
access.
