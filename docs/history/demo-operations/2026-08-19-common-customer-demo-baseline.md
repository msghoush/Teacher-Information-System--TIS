---
title: Common Customer Demo Feature Baseline
documentation_version: 3.1
last_updated: 2026-08-19
module: demo-operations
---

# Common Customer Demo Feature Baseline

Standard, Full, and Custom active customer demos now retain the normal TIS
customer feature baseline. Custom policy can still configure branch scope,
safety, approved experimental features, and AI consumption allowances, but it
cannot remove normal modules to simulate a lower subscription tier.

The migration reconciles only active demo product-feature policy. It preserves
duration, lifecycle, expiry, AI allowance/unrestricted configuration, branch
overrides, Platform Owner controls, and durable audit. Suspended, expired, or
incoherent demos continue to fail closed.
