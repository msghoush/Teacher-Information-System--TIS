---
name: tis-kms-developer
description: Investigate, implement, independently review, test, and document TIS tasks under KMS governance, tenant isolation, RBAC, database safety, and deployment safeguards. Use only in Teacher-Information-System--TIS.
---

# TIS KMS Developer Workflow

1. Read `AGENTS.md` and `.clinerules/tis.md` completely and all KMS sources they
   require. Follow AI Project Context's engineering reading sequence, including
   `docs/README.md`, engineering README, Development Standards, AI Optimization
   Guide, AI Coding Workflow, relevant ADRs, and module history. KMS governs;
   verify implementation and tests and report any mismatch with deployed behavior.
2. Establish branch, commit, worktree status, scope, and deployment boundary.
   Preserve unrelated tracked/untracked work and `tis.db`. Read-only investigation
   or review does not authorize implementation. Never commit, push, merge, deploy,
   mutate production, or communicate externally without explicit instructions.
3. Trace applicable routes, models, templates, services, workers, validators,
   migrations, and tests end to end before declaring a missing feature. Identify
   tenant/SchoolGroup, branch/year, RBAC, identity, publication, and audit boundaries.
   For authorized destructive work, inspect dependencies, ORM/database cascades,
   locking, transaction atomicity, rollback, and preservation of protected history.
4. Plan non-trivial work: scope, minimal implementation, acceptance criteria,
   risks, focused tests, broader regressions, KMS impact, and deployment effects.
   Implement only when clear. Follow existing patterns and use `apply_patch` for
   manual edits; avoid unrelated rewrites.
5. For independent review of Codex/Claude work, inspect the diff, reproduce claimed
   behavior and failure cases, and verify scope enforcement independently. Report
   concrete findings with evidence; author self-validation is not independent review.
6. Add/update focused tests for behavior and important failures. Run proportional
   validation and broader relevant regressions where warranted. Configuration-only
   tasks use static/path validation and KMS checks. Inspect the final diff and run
   `git diff --check`.
7. Complete `.kms-impact.yml` honestly without discarding unrelated pending impact.
   For knowledge impact yes, update affected authoritative Markdown and run
   `python scripts/kms.py sync`, preferably via `.\\.venv\\Scripts\\python.exe`.
   Never edit generated PDF/manifest manually. Always finish documentation
   verification with `python scripts/kms.py check`.
8. Report outcome, exact files, validation/results and gaps, KIA (knowledge impact,
   docs, change history, ADR need, module history, PDF regeneration, AI context,
   reasons for omissions), database/migration status, risks, and readiness to commit.
   Report deployment impact: Web Service, Timetable Workflow, migration/schema,
   or none. Shared solver/generation-worker changes require Web + Workflow from
   the same commit. Web-only router/template/state changes are Web only if the
   worker contract is unchanged. Classification never authorizes deployment.

## Invocation

With Skills enabled, select `/tis-kms-developer` from Cline slash suggestions,
or ask Cline to use the `tis-kms-developer` skill. If absent, read this file
explicitly and check the Skills panel/settings. Cline does not document the
Codex `$tis-kms-developer` convention. Rules apply even when skills are disabled.
See `docs/engineering/AI_CODING_WORKFLOW.md` for setup and discovery caveats.
