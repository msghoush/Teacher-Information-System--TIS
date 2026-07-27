---
title: Platform Owner Demo Operations And Access Profiles
documentation_version: 3.1
last_updated: 2026-07-27
status: accepted
module: demo-operations
---

# ADR 0017: Platform Owner Demo Operations And Access Profiles

## Context

M8B7 established Customer Demo provisioning, expiry, durable communications,
and same-workspace conversion. M8B8 established centralized AI entitlement
decisions and durable per-feature usage. Platform Owners need generic testing
controls without customer-specific rules, destructive reprovisioning, usage
resets, or a second lifecycle implementation.

## Decision

`saas/demo_operations_service.py` is the owner-only orchestration boundary. It
may expire an active demo immediately, reactivate an expired demo with a
mandatory future expiry, set an unbounded future custom expiry, send distinct
idempotent final-calendar-day reminders, and synchronously invoke the existing
single-demo or batch lifecycle processor. The same SchoolGroup, workspace UUID,
branches, users, permissions, classification, and data are preserved.

`saas/demo_access_service.py` resolves a workspace default and an optional
tenant-validated branch override. Standard retains M8B8's two successful uses
per enabled AI feature. Full enables every currently enabled controlled demo
feature and unrestricted AI while the demo is active. Custom uses registry
identifiers, selected features, per-feature allowances, and explicit unlimited
selections. Unknown features fail closed. Moving among profiles never deletes
or rewrites usage history.

Every attempted state-changing operation records actor, time, workspace and
optional branch, action, reason, before/after state, result, operation key, and
communication references. Material customer-visible changes use the M8B7
durable email outbox and Notification Center. Required reasons apply to expiry,
reactivation, custom expiry, and access changes.

Permissions, commercial/demo lifecycle access, and feature entitlement remain
separate checks in that order. Full access cannot convert a Customer Demo to
Customer Paid, cannot bypass normal permissions, and cannot bypass expiry.

## Consequences

- Platform Developer status alone never grants these controls.
- Branch overrides cannot affect another branch or tenant.
- Custom expiry has no maximum duration but must be future-dated.
- Manual lifecycle processing reuses production rules and reports bounded
  checked/reminder/expiry/no-action/failure/skipped counts.
- M8B9 adds no usage reset, pricing change, paid-conversion redesign, or
  customer-specific exception.
