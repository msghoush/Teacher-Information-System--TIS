---
title: TIS Project Governance
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Project Governance

This document defines how TIS engineering decisions, approvals, documentation, and quality gates should be governed.

## Ownership Model

Product/project ownership:
Defines business direction, roadmap priorities, customer experience, and approval for major changes.

Platform Owner:
Owns platform-level operations, platform accounts, provisioning oversight, and KMS visibility.

Engineering implementer:
Human developer, Codex, or ChatGPT-assisted coding session responsible for scoped implementation and validation.

Reviewer:
Reviews implementation, KMS updates, risk boundaries, and validation results.

## Architectural Authority

Architectural authority comes from:

- approved user direction,
- ADRs,
- `docs/TIS_MASTER_CONTEXT.md`,
- engineering handbook docs,
- module history,
- existing code patterns.

If these conflict, pause and clarify before making irreversible changes.

## Approval Workflow

Major work should follow:

1. clarify objective and scope,
2. identify allowed/forbidden files,
3. inspect code/docs,
4. implement scoped change,
5. update KMS,
6. run validation,
7. report KIA,
8. wait for review before broader phases.

## Documentation Authority

Markdown under `docs/` is the source of truth.

Generated artifacts:

- PDF booklet,
- manifest,
- future screenshots/diagrams.

Generated artifacts support the docs; they do not replace them.

## Coding Workflow

Default workflow:

- inspect before editing,
- prefer existing patterns,
- keep changes small,
- preserve tenant isolation,
- preserve identity boundaries,
- avoid unrelated rewrites,
- run targeted validation,
- update KMS when meaningful.

## Review Expectations

Review should check:

- behavior matches scope,
- no forbidden files changed,
- tenant isolation preserved,
- permissions preserved,
- SaaS/payment/provisioning untouched unless approved,
- landing untouched unless approved,
- docs/KIA complete,
- validation credible.

## Branch Strategy

Current assumption:

- active development branch: `dev`,
- production/live branch is separate and must be confirmed before deployment.

Rules:

- do not push unless requested,
- do not commit unless requested,
- do not merge unless requested,
- preserve unrelated local changes.

## Release Philosophy

Prefer:

- small reviewable increments,
- documentation updated with implementation,
- explicit milestone boundaries,
- staged rollout for risky systems,
- no hidden operational changes.

High-risk areas:

- authentication,
- platform owner access,
- tenant isolation,
- payment,
- provisioning,
- database/migrations,
- landing conversion path.

## Quality Gates

Before final report:

- run relevant compile/tests/smoke checks,
- verify generated docs if docs changed,
- inspect working-tree scope,
- mention validation gaps if any.

## Documentation Gates

Every meaningful implementation must answer:

- Did master context change?
- Did project state change?
- Did change history change?
- Is an ADR needed?
- Is module history needed?
- Did AI project context need updating?
- Did engineering docs need updating?
- Was PDF regenerated?

## KIA Requirement

Final reports must include:

```md
Knowledge impact: Yes/No
Docs updated:
Change history updated: Yes/No
ADR needed: Yes/No
Module history updated: Yes/No
PDF regenerated: Yes/No
AI project context updated: Yes/No
Reason if not updated:
```

## Engineering Decision Traceability

Use this traceability model:

- ADR: why a major decision was accepted.
- Rejected decisions: why significant alternatives were not chosen.
- CHANGE_HISTORY: chronological summary of meaningful changes.
- Module history: deeper before/after context for one area.
- Master context: durable current truth.
- Project state: current status, priority, known issues, next work.
- AI project context: compact first-read AI onboarding.
- Engineering handbook: module, architecture, flow, standards, data, UI, roadmap, governance knowledge.
- Generated PDF: snapshot for review/reference.
- Manifest: generated metadata and source freshness basis.

When to update each:

- Update ADRs for major decisions.
- Update rejected decisions when a significant alternative is intentionally declined.
- Update change history for meaningful changes.
- Update module history for area-specific evolution.
- Update master context for durable current truth.
- Update project state for current status and next work.
- Update AI context when first-read onboarding truth changes.
- Update engineering docs when developer understanding changes.
- Regenerate PDF/manifest when included docs change.
