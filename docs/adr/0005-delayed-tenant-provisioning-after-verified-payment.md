---
adr: 0005
title: Delayed Tenant Provisioning After Verified Payment
status: Accepted
date: 2026-06-26
---

# ADR 0005: Delayed Tenant Provisioning After Verified Payment

Status: Accepted

Date: 2026-06-26

## Context

Public SaaS onboarding collects organization and branch information before an operational tenant exists. Provisioning creates operational school records and must be safe, reviewable, and recoverable.

## Decision

Delay tenant provisioning until payment is verified and the organization is ready for provisioning. Use platform owner provisioning workflows and jobs to create or update operational tenant structures.

## Alternatives Considered

- Provision immediately after signup.
- Provision immediately after checkout return.
- Let public users create operational tenants directly.

## Consequences

Positive:

- Protects operational tenant data.
- Keeps pending SaaS onboarding separate from live school records.
- Allows platform owner oversight and retry behavior.

Tradeoffs:

- More state transitions exist between signup and operational access.
- Provisioning status must be communicated clearly.

## Related Docs / Files

- `saas/provisioning_service.py`
- `saas/router.py`
- `saas/service.py`
- `templates/saas/admin_provisioning.html`
- `templates/saas/admin_pending_organizations.html`
- `docs/TIS_MASTER_CONTEXT.md`
