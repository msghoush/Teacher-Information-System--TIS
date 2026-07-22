---
adr: 0009
title: Commercial State And Entitlement Resolution
status: Accepted
date: 2026-07-22
---

# ADR 0009: Commercial State And Entitlement Resolution

Status: Accepted

Date: 2026-07-22

## Context

Workspace classification identifies what a workspace is, but it must not be conflated with lifecycle, subscription evidence, feature values, or branch commercial activity. Future demo and paid workflows require one conservative resolution boundary before access enforcement is introduced.

## Decision

Represent the effective commercial grant with `WorkspaceEntitlement`, typed values through `WorkspaceEntitlementValue` and the existing `EntitlementDefinition` catalog, and optional per-branch intent through `BranchEntitlement`.

Resolve commercial state read-only from SchoolGroup classification/lifecycle and one coherent workspace entitlement. Customer-paid resolution delegates plan features, quantity, and confirmed subscription ownership to the existing M7 entitlement resolver. Branches inherit by default; an explicit branch record may state active or inactive but must match the branch tenant and effective workspace entitlement.

M8B-2 does not enforce the result. Missing, invalid, ambiguous, stale, orphaned, or cross-tenant evidence returns manual review.

## Consequences

Positive:
- One extensible commercial decision contract can support later demo and paid workflows.
- Existing M7 subscription authority is preserved.
- Branch commercial intent remains separate from operational branch status.
- Read-only resolution can be inspected safely before enforcement.

Tradeoffs:
- Existing internal development workspaces need a compatibility entitlement until all creation paths persist grants.
- Demo expiration and customer access behavior remain deliberately incomplete.
- Platform review is required for inconsistent persisted relationships.

## Related Docs / Files

- `commercial_entitlements.py`
- `saas/models.py`
- `saas/commercial_validation_service.py`
- `saas/workspace_entitlement_service.py`
- `saas/branch_entitlement_service.py`
- `saas/commercial_state_service.py`
- `saas/entitlement_service.py`
- `docs/adr/0008-workspace-classification-foundation.md`
