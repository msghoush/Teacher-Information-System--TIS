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
4. Regenerate the PDF and manifest after included Markdown changes:

   `python scripts/generate_docs_pdf.py`

5. Run enforcement:

   `python scripts/generate_docs_pdf.py --check`

   `python scripts/check_kms_impact.py`

6. Report the exact KMS files changed and complete the KIA in the final response.

A task is incomplete when required KMS updates, generated artifacts, declaration updates, or validation are missing. Automation validates and blocks stale work; it must never rewrite authoritative Markdown prose.
