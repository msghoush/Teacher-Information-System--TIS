# TIS Cline Project Rules

TIS KMS is the governing source of truth. Before substantive work, read
`AGENTS.md` completely, then `docs/AI_PROJECT_CONTEXT.md` first among KMS docs,
`docs/TIS_MASTER_CONTEXT.md`, `docs/PROJECT_STATE.md`, and
`docs/DOCUMENTATION_UPDATE_POLICY.md`. Follow all required engineering reads,
including `docs/engineering/DEVELOPMENT_STANDARDS.md` and
`docs/engineering/AI_CODING_WORKFLOW.md`, relevant ADRs, and module history.
Use `.cline/skills/tis-kms-developer/SKILL.md`; read it directly if skill
activation is unavailable. These rules apply even with skills disabled.

- Investigate existing implementation and tests before assuming a feature is
  missing. Plan non-trivial work first; implement only when scope is clear.
  Investigation and review remain read-only unless implementation is requested.
- Establish branch, commit, and worktree status. Preserve unrelated tracked and
  untracked changes. Use minimal diffs and avoid unrelated rewrites.
- Preserve tenant/SchoolGroup, branch, academic-year isolation, existing RBAC,
  identity, publication, and audit boundaries.
- Never modify `tis.db` without explicit approval. Destructive operations require
  authorization and verified dependency safety, transaction/rollback behavior,
  and absence of hidden ORM/database cascades before mutation.
- Never commit, push, merge, deploy, mutate production, or send external
  communications unless explicitly instructed for that action.
- Run proportional focused tests and broader relevant regressions where warranted.
  Inspect the final diff and run `git diff --check`.
- Assess task-level KMS impact in `.kms-impact.yml`, preserving unrelated pending
  impact. For knowledge impact yes, update affected authoritative Markdown and
  run `python scripts/kms.py sync`; always run `python scripts/kms.py check`
  before reporting completion. Prefer the repository `.venv` Python.
  Never manually edit generated KMS PDF/manifest or place sensitive data in KMS.
- Always report deployment impact: Web Service, Timetable Workflow,
  migration/schema, or none (all that apply). Shared solver/generation-worker
  changes require Web + Workflow deployment from the same commit. Web-only
  router/template/state changes are Web only when the worker contract is unchanged.
  Verify the contract; filenames alone do not prove the boundary.
- When assigned review of Codex or Claude Code changes, independently verify the
  diff, behavior, safety, and test evidence rather than trusting author claims.

Codex, Claude Code, and Cline/ClinePass are approved TIS developers. Follow the
master conversation's allocation under `docs/engineering/PROJECT_GOVERNANCE.md`;
preferences do not grant permanent ownership or automatic delegation authority.
