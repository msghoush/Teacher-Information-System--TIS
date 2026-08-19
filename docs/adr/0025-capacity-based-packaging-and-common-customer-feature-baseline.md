---
title: Capacity-Based Packaging And Common Customer Feature Baseline
documentation_version: 3.1
last_updated: 2026-08-19
status: accepted
module: subscriptions
---

# ADR 0025: Capacity-Based Packaging And Common Customer Feature Baseline

## Context

The original subscription entitlement foundation used a temporary feature-tier
matrix: Enterprise AI received commercial AI, Professional and Enterprise AI
received Advanced Reporting, and other catalog features awaited approval. TIS
subsequently established organization-wide branch, staff-user, and teacher
capacity as the authoritative self-service plan-sizing model and added paid,
promo, and demo commercial sources.

That transitional feature matrix contradicted the approved product model. TIS is
sold to organizations, and Starter, Professional, and Enterprise AI represent
organization scale rather than progressively unlocked normal product modules.

## Decision

Starter, Professional, and Enterprise AI share one normal customer feature
baseline. The baseline includes teacher and branch management, observations,
hiring, reporting, enabled commercial AI, Advanced Reporting, general exports,
and customer-facing cross-branch reporting. `feature.audit_log` is explicitly
excluded because the implemented global audit export is Developer-only.

Paid, promo, and active customer-demo authority may use the same baseline only
after coherent source and lifecycle resolution. Permissions, tenant isolation,
branch entitlement, academic-year scope, and operational prerequisites remain
independent mandatory checks. Plan and promo capacity remain unchanged:
Starter 1/5/25, Professional 5/20/100, Enterprise AI 25/100/500, and Custom
above those ceilings.

The shared feature resolver performs the source-aware decision centrally.
PlanEntitlement remains the persisted feature catalog and rollout mechanism;
normal baseline values are identical across the three plans, while capacity,
beta/disabled features, custom contracts, demo safety, and kill switches remain
separate concerns.

Standard, Full, and Custom demos receive the normal customer baseline. Custom
demo policy may still configure scope, safety, experimental features, and AI
consumption, but cannot simulate a lower paid tier by removing normal modules.

AI feature availability is separate from provider consumption. Enabled AI
features share the customer baseline and still require `ai.use`. The existing
reservation, idempotency, counters, and operation events remain authoritative.
A separate consumption-policy boundary supplies demo allowances now and can
later supply paid, promo, rate, budget, or custom-contract limits without
changing feature availability. Globally disabled AI features remain disabled.

## Superseded Decisions

This ADR supersedes only:

- ADR 0009's delegation of paid customer feature availability to a
  differentiated plan matrix; and
- ADR 0015's temporary Enterprise-AI-only availability mapping.

Their commercial-source authority, tenant isolation, fail-closed resolution,
permission separation, AI accounting, idempotency, and concurrency decisions
remain valid.

## Consequences

- Normal customer modules are not hidden because a coherent workspace uses
  Starter, Professional, Enterprise AI, promo, or active demo authority.
- Capacity and Paddle quantity behavior do not change.
- Active promo operational entitlement values require safe idempotent
  reconciliation; immutable grant/redemption evidence is unchanged.
- Existing paid workspaces need no per-workspace feature backfill because paid
  entitlements resolve through the current PlanEntitlement matrix.
- Customer feature universality cannot expose Platform, Developer, System Owner,
  cross-tenant, promo-admin, demo-admin, or global commercial operations.

## Related Files

- `saas/customer_feature_policy.py`
- `saas/entitlement_service.py`
- `saas/ai_consumption_policy.py`
- `saas/ai_entitlement_service.py`
- `saas/demo_access_service.py`
- `saas/promo_redemption_service.py`
- `db_migrations.py`
- `authorization.py`
