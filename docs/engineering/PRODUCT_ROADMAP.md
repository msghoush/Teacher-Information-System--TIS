---
title: TIS Product Roadmap
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Product Roadmap

This roadmap summarizes completed, current, next, and future product directions. It is not a release commitment; it is the current planning map for developers, owners, and reviewers.

## Completed

### SaaS Identity Foundation

Established SaaS account signup, login, account area, and the boundary between SaaS accounts, platform identities, and operational tenant users.

### Pending Organizations Zone

Created pending organization structures and owner-facing review concepts for organizations moving through SaaS onboarding.

### Plans And Billing Foundation

Added plan catalog, plan selection, billing status, checkout summary, checkout return/cancel, and payment/billing service boundaries.

### Paddle Payment Collection

Added Paddle-oriented payment architecture with provider logic isolated behind service/client modules.

### Tenant Provisioning Engine

Added provisioning workflows and jobs to create or connect operational school group/branch/year/user records from ready pending organizations.

### KMS Foundation

Created source-of-truth Markdown docs, change history, ADRs, module history, AI project context, generated PDF booklet, and manifest.

### Platform Owner Knowledge Center

Added protected owner-only Knowledge Center for KMS health, source freshness, manifest metadata, ADRs, module history, and protected PDF view/download.

### KMS v3.0 Phase 3A

Added engineering handbook foundation with module map, repository architecture, user/system flows, and onboarding structure.

## Current

### KMS v3.0 Enhancement

Current KMS work expands the engineering handbook with database architecture, development standards, UI/UX philosophy, roadmap, and stronger developer/AI guidance.

### Landing / Customer Experience Preparation

The product is preparing for stronger public customer journey work from landing page storytelling through SaaS signup, onboarding, billing, and operational access.

## Next

### Premium Landing Page Redesign

Improve public website quality, product storytelling, visuals, and conversion clarity while preserving the separate Next.js source-of-truth.

### Customer Journey From Landing To Signup

Clarify the path from public website to SaaS signup, plan selection, onboarding, checkout, and workspace readiness.

### SaaS Onboarding Refinement

Improve onboarding language, progress, validation, customer reassurance, and platform owner visibility.

### Paddle Live Configuration

Configure live Paddle behavior when the payment account and production readiness are approved.

### Subscription Lifecycle Management

Add clearer management for active subscriptions, renewal state, payment failures, and account lifecycle.

### Feature Gating By Plan

Introduce plan-based access control for advanced capabilities, future AI features, and subscription tiers.

### Customer Billing Portal

Provide customer-facing billing management if supported by payment architecture and approved product flow.

### Trial / Upgrade / Downgrade / Cancellation Workflows

Define and implement subscription lifecycle actions safely with provider and local billing state alignment.

## Future

### AI Academic Assistant

Support academic leaders with intelligent recommendations based on verified tenant data.

### AI Assessment Generation

Generate curriculum-aware assessments or question banks when curriculum/planning data is reliable enough.

### AI Observation Improvement Plans

Assist supervisors with improvement plans, follow-up suggestions, and structured feedback from observation records.

### AI Calendar Activity Planning

Suggest academic calendar activities, reminders, and coordination plans.

### AI Dashboards And Academic Analytics

Provide richer academic insight, trends, risks, and multi-branch intelligence.

### Multi-Branch Executive Dashboards

Give leadership cross-branch visibility into staffing, workload, observations, calendar, and planning health.

### Curriculum And Planning Workflows

Expand from operational staffing/planning toward curriculum-aware academic planning if approved.

### Reporting Improvements

Improve exports, dashboards, executive summaries, and decision-support reports.

### Mobile Or Portal Expansion

Explore teacher/mobile/parent-style portals only if later approved and aligned with product strategy.

## Roadmap Guardrails

- Do not build AI features before data quality, permissions, and plan boundaries are clear.
- Do not build subscription lifecycle actions before payment provider behavior is verified.
- Do not redesign landing/customer journey without preserving the Next.js boundary.
- Do not expose internal terms to customers.
- Update KMS docs and roadmap after meaningful roadmap changes.
