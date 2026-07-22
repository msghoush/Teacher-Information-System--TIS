---
title: Workspace Classification History
module: architecture
last_updated: 2026-07-22
---

# Workspace Classification History

This folder tracks the evolution of workspace identity, classification, lifecycle, intent, and later approved commercial separation rules.

## 2026-07-22 - M8B-1 Foundation

Added stable Workspace UUID, constrained Workspace Classification and Lifecycle metadata, onboarding Workspace Intent, SaaS Account Purpose, and internal-test identity attribution. Added validation-only services, a commercial-state skeleton, Platform Owner read-only display, a relationship diagnostic, and a controlled one-time backfill for confirmed existing test data.

M8B-1 deliberately leaves demo workflows, expiration, entitlements, branch entitlements, conversions, memberships, Al-Andalus migration, and commercial-state decisions unimplemented.

## 2026-07-22 - M8B-2 Commercial Resolution Foundation

Added normalized workspace entitlement envelopes, typed feature/limit values using the existing entitlement catalog, optional branch inherit/active/inactive records, and read-only effective workspace, branch, and commercial-state resolvers. Paid workspaces continue to depend on M7 confirmed local subscription evidence. No customer enforcement, demo lifecycle, conversion, membership, role, Paddle, onboarding, or Al-Andalus behavior changed.

Related docs:
- `docs/adr/0008-workspace-classification-foundation.md`
- `docs/adr/0009-commercial-state-and-entitlement-resolution.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`
