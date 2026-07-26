---
title: Demo Customer Communications And Approval Orchestration
documentation_version: 3.1
last_updated: 2026-07-27
status: accepted
---

# ADR 0014: Demo Customer Communications And Approval Orchestration

## Context

M8B-3 through M8B-6 established review, provisioning, lifecycle enforcement, and same-workspace paid conversion, but deliberately omitted customer lifecycle email, shared Notification Center delivery, a workspace-wide demo indicator, approval-driven activation, and expired-demo continuation.

## Decision

M8B7 makes the normal Platform Owner approval route orchestrate the existing approval and provisioning services. Approval evidence remains separate from provisioning, and a failed activation preserves an Approved request plus the existing owner-only retry action. An approval email intent is created only after activation succeeds.

Demo communications use the existing branded email renderer and provider through a durable `SaaSDemoEmailDelivery` outbox. Logical events are uniquely deduplicated and provider calls occur after lifecycle transactions. Platform Owner events use the existing Notification Center with explicit destinations and deduplication keys.

The shared authenticated shell resolves active Customer Demo state through the existing lifecycle resolver and shows a persistent demo indicator only to tenant identities. Expired access remains blocked.

A coherent expired Customer Demo may enter the existing Paddle checkout flow. Only authoritative confirmed payment converts and reactivates the same SchoolGroup, workspace UUID, tenant link, branches, users, permissions, and tenant data.

## Consequences

- Request, approval, decline, reminder, expiry, and continuation communications are durable and retryable.
- Normal approval creates exactly one operational workspace; failed provisioning remains independently retryable.
- Scheduler delay never extends access.
- Expired customers can subscribe without tenant reprovisioning.
- Sandbox, checkout-return, and unverified payment evidence cannot establish Customer Paid state.
- M8B8 AI demo limits and M8B9 lifecycle testing controls remain out of scope.
