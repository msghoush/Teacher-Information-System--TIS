---
adr: 0008
title: Workspace Classification Foundation
status: Accepted
date: 2026-07-22
---

# ADR 0008: Workspace Classification Foundation

Status: Accepted

Date: 2026-07-22

## Context

TIS needs a permanent distinction between internal sandbox, customer demo, and customer-paid workspaces. Existing onboarding, payment, and provisioning statuses describe workflow evidence, but none is a stable workspace classification authority. All records created before M8B-1 are confirmed test data.

## Decision

Make `SchoolGroup` the canonical owner of stable workspace identity, classification, and lifecycle metadata. Carry pre-provisioning intent on `PendingOrganization`, account purpose on `SaaSAccount`, and internal-test attribution on operational `User`.

M8B-1 is metadata-only. Classification conversion is unavailable. No payment, entitlement, permission, tenant-isolation, reset, or customer workflow consumes the new fields. Existing records are classified through an explicit dry-run/default, transactional, idempotent backfill as internal sandbox/test data.

## Consequences

Positive:
- Later workspace policies have one constrained metadata foundation.
- Stable UUIDs separate workspace identity from numeric database IDs.
- Existing test data is explicitly classified without a legacy/unknown state.
- Platform Owners can inspect metadata without receiving mutation controls.

Tradeoffs:
- M8B-1 does not yet enforce commercial separation.
- Deployment requires running and reviewing the controlled data backfill after schema migration.
- Workspace conversions require a later approved package.

## Related Docs / Files

- `workspace_classification.py`
- `models.py`
- `saas/models.py`
- `saas/workspace_classification_service.py`
- `saas/workspace_classification_admin_service.py`
- `saas/commercial_state_service.py`
- `scripts/diagnose_workspace_classification.py`
- `scripts/backfill_workspace_classification.py`
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`
