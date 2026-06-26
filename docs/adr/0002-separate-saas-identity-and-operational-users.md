---
adr: 0002
title: Separate SaaS Identity And Operational Users
status: Accepted
date: 2026-06-26
---

# ADR 0002: Separate SaaS Identity And Operational Users

Status: Accepted

Date: 2026-06-26

## Context

TIS has SaaS account users who sign up, select plans, onboard organizations, and manage billing. It also has operational tenant users who work inside a provisioned school context. Platform owners and developers are separate platform identities.

## Decision

Keep SaaS account identity, platform identity, and operational tenant identity distinct.

## Alternatives Considered

- Use one user table concept for all public signup, platform, and tenant users.
- Automatically convert every SaaS signup into an operational tenant user.
- Treat platform users as ordinary tenant administrators.

## Consequences

Positive:

- Clearer security boundaries.
- Safer tenant isolation.
- Billing/onboarding can proceed before operational provisioning.

Tradeoffs:

- Identity flows require careful documentation.
- Developers must avoid mixing account, platform, and tenant assumptions.

## Related Docs / Files

- `auth.py`
- `models.py`
- `saas/models.py`
- `saas/service.py`
- `saas/router.py`
- `docs/TIS_MASTER_CONTEXT.md`
