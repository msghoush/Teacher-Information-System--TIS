---
title: AI Entitlements History
module: ai-entitlements
last_updated: 2026-08-19
---

# AI Entitlements History

## 2026-08-19 - Availability Separated From Consumption

ADR 0025 supersedes the temporary Enterprise-AI-only availability mapping.
Every enabled registered AI feature is commercially available to coherent paid,
promo, and active demo workspaces with `ai.use`; globally disabled definitions
remain denied. A separate consumption-policy boundary preserves Standard demo
allowances, Full/Custom policy, reservations, idempotency, counters, and durable
events without inventing a provider billing engine.

## 2026-07-27 - M8B8 AI Entitlements And Commercial Foundation

M8B8 adds one tenant-safe AI entitlement authority, a controlled feature
registry, an assignable `ai.use` permission, and durable usage counters plus
reserved/successful/failed operation events. Customer Demo allowance is two successful
uses per feature. Internal Sandbox is unlimited and measured separately.
Customer Paid access follows the existing verified commercial resolver and
`module.ai` plan entitlement; the reviewed foundation mapping is Enterprise AI
only.

There are no executable AI routes in the current product. The service and
denial payload are reusable boundaries for future implementations; M8B8 does
not fabricate an AI tool or add M8B9 reset/override/lifecycle controls.
