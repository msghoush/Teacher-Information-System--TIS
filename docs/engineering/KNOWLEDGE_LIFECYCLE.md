---
title: TIS Knowledge Lifecycle
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Knowledge Lifecycle

This document defines how the TIS Knowledge Management System evolves with the software from planning through deployment and maintenance.

## Core Principle

Documentation evolves with implementation. Markdown is the source of truth. The PDF and manifest are generated snapshots. The Knowledge Center is the owner-facing status surface.

No meaningful implementation is complete until the Knowledge Impact Assessment is complete.

## Documentation Lifecycle

1. A task is proposed.
2. Relevant docs, ADRs, and module history are read.
3. The likely documentation impact is identified.
4. Implementation happens within approved scope.
5. KIA is completed.
6. Relevant Markdown docs are updated.
7. ADRs are added or updated if decisions changed.
8. Module history is updated if a module's documented state changed.
9. PDF and manifest are regenerated if included docs changed.
10. Final report describes the knowledge impact.

## Engineering Lifecycle

1. Inspect before editing.
2. Plan the smallest safe implementation.
3. Preserve tenant, identity, permission, SaaS, payment, provisioning, and landing boundaries.
4. Implement scoped changes.
5. Validate with focused checks.
6. Update KMS.
7. Report KIA.
8. Wait for review, commit, push, or deployment approval.

## Approval Lifecycle

1. Owner defines goal and constraints.
2. Implementer confirms scope.
3. Implementer makes only approved changes.
4. Reviewer checks behavior, scope, docs, validation, and KIA.
5. Commit/push/deployment happens only after explicit approval.

## Review Lifecycle

Review should verify:

- no forbidden files changed,
- tenant isolation remains intact,
- SaaS/payment/provisioning boundaries are preserved,
- landing code remains untouched unless approved,
- database/migrations are untouched unless approved,
- KMS docs and generated artifacts are current,
- KIA is complete.

## Release Lifecycle

Before release:

1. Confirm branch and deployment target.
2. Confirm tests/checks.
3. Confirm docs/PDF/manifest are current.
4. Confirm change history and project state.
5. Confirm release notes or owner communication if needed.
6. Deploy only through approved process.

## Maintenance Lifecycle

Maintenance includes:

- periodic KMS freshness review,
- periodic ADR/rejected-decision review,
- module history cleanup for discoverability,
- PDF readability review,
- Knowledge Center health checks,
- updating roadmap/current state after milestones.

## Planning To Production

Planning creates the first knowledge obligation. Production closes it.

Expected path:

```text
Idea / task
  -> scope and constraints
  -> docs and code inspection
  -> implementation
  -> validation
  -> KIA
  -> docs/history/ADR updates
  -> PDF/manifest regeneration
  -> review
  -> commit/push
  -> deployment
  -> post-deployment state update if needed
```

## Guardrails

- The app must not silently rewrite Markdown docs.
- Generated PDFs must not be edited manually.
- Regeneration is artifact generation, not source editing.
- KMS update work must remain reviewable.
