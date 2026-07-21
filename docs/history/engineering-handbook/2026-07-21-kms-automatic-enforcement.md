---
title: Automatic KMS Synchronization Enforcement
module: engineering-handbook
date: 2026-07-21
---

# 2026-07-21 - Automatic KMS Synchronization Enforcement

## Previous State

KMS governance was documented but not mechanically enforced. Developers and AI assistants manually decided impact, edited Markdown, and regenerated artifacts. The Knowledge Center could detect stale hashes, but no pull-request or deployment gate consumed that status.

## New State

TIS has a narrow repository enforcement layer:

- `AGENTS.md` makes KMS onboarding and completion rules default for Codex.
- `.kms-impact.yml` records task-level impact, affected areas, updated KMS files, and controlled no-impact overrides.
- `scripts/check_kms_impact.py` compares the declaration with a Git range or local worktree, classifies likely major changes, and validates generated artifacts.
- `scripts/generate_docs_pdf.py --check` verifies source coverage, source hashes, PDF hash/size, version, and manifest consistency without writing.
- GitHub Actions run enforcement for pull requests and `dev`; production deployment from `master` depends on the same gate.

## Cross-Platform Correction

The initial enforcement release exposed two checkout-dependent differences: Markdown hashes reflected raw CRLF/LF bytes, and dynamic source ordering followed native path comparison. The generator and Knowledge Center now hash normalized UTF-8/LF Markdown. The generator also records repository-relative POSIX paths in a deterministic order while continuing to fail on genuine source-list drift. Impact detection includes deleted files so removing behavior or documentation cannot bypass review.

## Task-Boundary Correction

The initial push workflow compared only the previous pushed commit with the new head, while pull requests compared the complete feature branch. Follow-up commits therefore validated a task-level declaration against a commit-level diff. Push checks now derive the task base from the merge base of the default branch and pushed head. Pull-request and push checks consequently enforce the same cumulative KIA scope without allowing undeclared documentation changes.

## Guardrails

Automation does not generate or rewrite Markdown prose. Reviewed Markdown remains authoritative. KMS files must describe engineering design only and must not contain customer, organization, personal, transaction, invoice, production identifier, webhook payload, secret, credential, environment, or database-row data.

## Related Files

- `AGENTS.md`
- `.kms-impact.yml`
- `scripts/check_kms_impact.py`
- `scripts/generate_docs_pdf.py`
- `.github/workflows/kms-enforcement.yml`
- `.github/workflows/deploy-on-master.yml`
- `docs/DOCUMENTATION_UPDATE_POLICY.md`
