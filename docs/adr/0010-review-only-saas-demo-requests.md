---
title: Review-Only SaaS Demo Requests Before Provisioning
documentation_version: 3.1
last_updated: 2026-07-22
status: accepted
---

# ADR 0010: Review-Only SaaS Demo Requests Before Provisioning

## Context

M8B-3 introduces a customer demo-request workflow after onboarding, while demo provisioning and activation remain explicitly deferred to M8B-4. Existing public marketing demo leads, SaaS onboarding organizations, operational workspaces, and paid subscriptions have different ownership and lifecycle boundaries.

## Decision

Use a dedicated `SaaSDemoRequest` aggregate tied to the verified SaaS requester and `PendingOrganization`. Capture classification, commercial-state, and entitlement context at submission. Store Platform Owner approval/rejection in a separate review record and every transition in append-only audit/internal-notification events.

Approval is review evidence only. It must not create a `SchoolGroup`, workspace entitlement, checkout, payment record, Paddle object, or provisioning job. Subscribe Now continues the existing payment workflow unchanged. The legacy public marketing `DemoRequest` remains independent.

## Consequences

- Customer and Platform Owner views have a durable, permission-scoped request lifecycle.
- Duplicate pending requests and invalid transitions fail closed.
- M8B-4 can consume an approved request without redefining review history.
- Approval does not imply activation, entitlement, or operational access.
- Email delivery, expiration, schedulers, conversion, and provisioning remain future work.

## M8B7 Amendment

M8B7 preserves approval as durable review evidence but makes the normal owner approval route orchestrate the separately callable provisioning service. Failed activation leaves the request Approved and retryable. Request-received, approval, and decline communications are now durable; approval communication is created only after activation succeeds. ADR 0014 owns the orchestration and communication decision.
