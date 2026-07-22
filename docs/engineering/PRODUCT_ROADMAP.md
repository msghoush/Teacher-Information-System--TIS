---
title: TIS Product Roadmap
documentation_version: 3.1
last_updated: 2026-07-21
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

### M7 Subscription Management

Completed entitlement foundations, customer Subscription Management portal, paid branch quantity management, upgrades and scheduled downgrades, provider-authoritative proration, cancellation/reversal, centralized lifecycle/action policy, Paddle billing history, protected invoice downloads, and webhook/reconciliation safeguards.

### Automatic KMS Enforcement

Added root AI instructions, machine-readable task KIA, major-change detection, read-only PDF/manifest checks, pull-request and `dev` CI validation, and a required KMS gate before `master` deployment.

### M8B-1 Workspace Classification Foundation

Added constrained workspace identity/classification/lifecycle metadata, pre-provisioning and identity intent fields, validation-only services, read-only owner visibility, and safe diagnostic/backfill tooling. No commercial behavior or conversion workflow consumes the metadata yet.

### M8B-2 Commercial State And Entitlement Foundation

Added normalized workspace and branch entitlement records, typed feature/limit values, read-only effective entitlement/commercial-state resolvers, conservative validation, and Platform Owner-only visibility. No enforcement or customer workflow changed.

## Current

### KMS Enforcement Review

Review enforcement against real development tasks, keep classification conservative, and tune only demonstrated false positives without permitting silent no-impact declarations.

### Landing / Customer Experience Preparation

The product is preparing for stronger public customer journey work from landing page storytelling through SaaS signup, onboarding, billing, and operational access.

## Next

### M8B-3 Commercial Lifecycle Workflows

Proceed only from a separately approved M8B-3 specification after M8B-2 resolution is validated. Demo requests, approval/rejection, provisioning, expiration, schedulers, reminders, enforcement, conversion, memberships, and Al-Andalus migration remain unimplemented.

### Premium Landing Page Redesign

Improve public website quality, product storytelling, visuals, and conversion clarity while preserving the separate Next.js source-of-truth.

### Customer Journey From Landing To Signup

Clarify the path from public website to SaaS signup, plan selection, onboarding, checkout, and workspace readiness.

### SaaS Onboarding Refinement

Improve onboarding language, progress, validation, customer reassurance, and platform owner visibility.

### Paddle Live Configuration

Configure live Paddle behavior when the payment account and production readiness are approved.

### Expand Entitlement Enforcement

Extend plan entitlement checks beyond the current approved pilot only when commercial rules for each module are reviewed.

### Subscription Operations Hardening

Continue production validation, renewal/payment-failure handling, reconciliation observability, and owner support workflows without weakening Paddle authority or tenant isolation.

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
- Do not extend subscription lifecycle actions without verified Paddle behavior, fail-closed reconciliation, and updated KMS records.
- Do not redesign landing/customer journey without preserving the Next.js boundary.
- Do not expose internal terms to customers.
- Update KMS docs and roadmap after meaningful roadmap changes.
