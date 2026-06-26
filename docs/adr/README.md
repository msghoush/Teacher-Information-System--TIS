---
title: TIS Architecture Decision Records
documentation_version: 2.0
last_updated: 2026-06-26
---

# Architecture Decision Records

ADRs record major TIS architectural and product decisions. They explain why the system is shaped the way it is.

## ADR Rules

- Create an ADR for major decisions affecting architecture, identity, SaaS, payment, provisioning, deployment, documentation governance, or long-term product boundaries.
- Do not use ADRs for ordinary bug fixes.
- If a decision is replaced, mark the older ADR as Superseded and link the new ADR.
- ADRs complement `docs/TIS_MASTER_CONTEXT.md`; they do not replace it.

## Status Values

- Proposed
- Accepted
- Superseded
- Deprecated

## ADR Index

- `0001-separate-nextjs-landing-website.md`
- `0002-separate-saas-identity-and-operational-users.md`
- `0003-paddle-payment-architecture.md`
- `0004-webhook-only-payment-confirmation.md`
- `0005-delayed-tenant-provisioning-after-verified-payment.md`
- `0006-documentation-as-source-knowledge-management-system.md`
- `0007-landing-page-visual-system-strategy.md`
