---
title: Demo Workspace Provisioning And Commercial Source Links
documentation_version: 3.1
last_updated: 2026-07-23
status: accepted
---

# ADR 0011: Demo Workspace Provisioning And Commercial Source Links

## Context

M8B-4 must create an operational customer-demo workspace after Platform Owner approval. The existing tenant-provisioning link required a paid subscription contract, but a demo has no Paddle or billing obligation. Fabricating a contract would weaken commercial-state resolution and confuse demo access with paid ownership.

Provisioning must also reuse the proven operational tenant builder, remain retryable after failure, and preserve M8B-3 approval as review evidence rather than making approval itself activate a workspace.

## Decision

Use a dedicated `SaaSDemoWorkspaceProvisioning` aggregate for attempts, result, activation metadata, and resulting resource references. Store append-only provisioning events separately.

Generalize `TenantProvisioningLink` so exactly one commercial source is required: either `subscription_contract_id` for paid provisioning or `demo_request_id` for customer-demo provisioning. Existing paid rows remain unchanged.

Extract the workspace-record creation sequence from the paid provisioning service into a shared builder. The demo service invokes that builder inside a nested transaction, creates and validates a pending demo entitlement, creates the demo-sourced tenant link, then activates the SchoolGroup and entitlement. A failure rolls back all workspace changes while the outer transaction records a failed provisioning attempt and leaves the demo request Approved.

## Consequences

- Paid and demo tenants share one operational workspace creation engine.
- Demo access has explicit commercial provenance without fabricated payment evidence.
- Duplicate provisioning is prevented by request uniqueness, tenant-link uniqueness, and service validation.
- Customers see safe lifecycle states; Platform Owners retain actionable failure details and audit history.
- Logo filesystem writes remain governed by the existing provisioning engine; database provisioning is atomic.
- Expiration, reminders, schedulers, login restrictions, conversion, email delivery, and billing changes remain future work.
