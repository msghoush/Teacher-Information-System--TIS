---
title: Unified Commercial Access And Capacity Authority
documentation_version: 3.1
last_updated: 2026-08-04
status: accepted
module: subscriptions
---

# ADR 0018: Unified Commercial Access And Capacity Authority

## Context

TIS already had authoritative workspace classification, commercial-state,
workspace-entitlement, paid-subscription, plan-capacity, and demo-lifecycle
resolvers. Capacity checks were nevertheless split among branch, user, teacher,
subscription, and provisioning code. Some paths counted people differently or
could check capacity outside the transaction that performed the mutation.

## Decision

`saas/commercial_authority_service.py` is the single read-only facade for
effective commercial access and operational capacity. It composes the existing
authorities rather than replacing or persisting them. Paid workspaces require
one contract-linked confirmed subscription and active paid workspace
entitlement. Customer Demo and Internal Sandbox workspaces remain explicitly
unmetered in M1. Missing, contradictory, or unsupported authority fails closed.

Paid branch capacity is the confirmed `PaymentSubscription.quantity` capped by
the plan branch ceiling. Staff capacity counts every distinct active tenant
operational `User` in the SchoolGroup, regardless of role, title, position, or
internal-test attribution. Platform identities and account-only SaaS records do
not count. Teacher capacity counts distinct normalized `Teacher.teacher_id`
values in active branches and active academic years; each blank legacy identity
counts separately and is never silently merged.

Every capacity-increasing mutation locks its owning SchoolGroup with
PostgreSQL `SELECT ... FOR UPDATE`, resolves and recounts authority, evaluates
the proposed final totals, writes, and commits in one transaction. Multi-tenant
internal operations lock SchoolGroups in ascending ID order. Existing
over-capacity tenants keep their records and access, may reduce usage, and may
change unaffected dimensions, but cannot further increase an exceeded
dimension.

## Consequences

- Branch create/reactivation/bulk status updates, operational user
  create/reactivation/cross-tenant activation, teacher create/year-copy, and
  academic-year activation use the same structured capacity decision.
- Paid and demo provisioning validate the final commercial authority before
  their nested transaction may complete.
- Capacity checks supplement existing permissions and tenant isolation.
- Pending plan or quantity changes grant no capacity before provider-confirmed
  subscription reconciliation.
- Paddle quantity remains active branches only; staff and teacher counts affect
  plan eligibility and limits but are never Paddle quantity units.
- M1 adds no schema, migration, pricing, packaging, Paddle, webhook, onboarding,
  authentication, or permission-definition change.
