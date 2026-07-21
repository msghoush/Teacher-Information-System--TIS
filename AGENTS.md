# TIS Repository Instructions

These instructions apply to every development task in this repository.

## Before Implementation

1. Read `docs/AI_PROJECT_CONTEXT.md` first.
2. Read `docs/TIS_MASTER_CONTEXT.md`, `docs/PROJECT_STATE.md`, and relevant engineering docs, ADRs, and module history.
3. Inspect the affected code and tests before editing.
4. Assess likely Knowledge Impact and update `.kms-impact.yml` for the current task.

## Knowledge-Impacting Changes

Treat a change as knowledge-impacting when it affects architecture, module or service responsibility, database schema or relationships, migrations, business rules, lifecycle behavior, user/system workflows, permissions, roles, tenant isolation, security, APIs, integrations, background processes, deployment architecture, major feature capability, major configuration behavior, or milestone/roadmap status.

Minor work may use `knowledge_impact: no` only with a specific explanation. Examples include spelling corrections, visual-only styling, isolated test maintenance, non-behavioral internal refactors, and formatting cleanup. If a major-change path is touched for a legitimate no-impact task, set the explicit override and explain why behavior and engineering knowledge did not change.

## During And After Implementation

1. Update affected authoritative Markdown in the same task.
2. Update architecture, workflows, module maps, roadmap, change history, ADRs, and module history only where applicable.
3. Never place customer, organization, personal, billing-record, invoice, transaction, production identifier, webhook payload, credential, secret, environment value, database-row, or test-customer personal data in the KMS.
4. Synchronize the KMS after documentation changes. This validates KIA before writing, regenerates the PDF and manifest, and verifies freshness:

   `python scripts/kms.py sync`

5. Run the complete read-only enforcement command whenever synchronization is not required or as a final confirmation:

   `python scripts/kms.py check`

6. Report the exact KMS files changed and complete the KIA in the final response.

A task is incomplete when required KMS updates, generated artifacts, declaration updates, or validation are missing. Automation validates and blocks stale work; it must never rewrite authoritative Markdown prose.
