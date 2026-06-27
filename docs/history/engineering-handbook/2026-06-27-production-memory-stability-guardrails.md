---
title: Production Memory Stability Guardrails
module: engineering-handbook
date: 2026-06-27
---

# 2026-06-27 - Production Memory Stability Guardrails

Module:
Engineering Handbook and operational app stability

Related change-history entry:
`docs/CHANGE_HISTORY.md` - 2026-06-27 - Added Production Memory Stability Guardrails

Related ADRs:
None. This is a standards and operational guardrail update, not a new architecture decision.

Reviewer/approval notes:
Prepared after a Render restart/502 investigation. Local changes only; no commit, push, migration, database change, or deployment was performed.

## Previous Documented State

The KMS required scoped changes, tenant isolation, validation, and documentation updates, but it did not explicitly define a production memory budget or prohibit common memory hazards such as:

- full large-dataset parsing for normal picker requests,
- duplicate template rendering in production routes,
- warning-level diagnostic stage logs during normal traffic,
- unbounded global caches,
- startup-heavy work without memory review.

## New Documented State

`docs/engineering/DEVELOPMENT_STANDARDS.md` now includes a mandatory Production Memory and Render Stability section.

The standards require future work to:

- treat 512 MB Render memory as a hard production budget,
- avoid full large-dataset loads when scoped or streaming lookup is available,
- avoid duplicate template renders in production request paths,
- keep diagnostics opt-in through explicit environment flags,
- filter data before materializing result sets,
- keep caches bounded and justified,
- include memory/performance smoke checks for memory-sensitive changes.

## Reason For Change

The 2026-06-27 production investigation found avoidable memory pressure risks after deployment:

- `/observations/` had diagnostic logging and extra template pre-renders in the normal route path.
- Global location lookup could parse a 47 MB country/state/city reference dataset into a complete in-memory index for simple picker API calls.

These patterns can trigger process restarts and temporary 502 responses on constrained production instances.

## User / Business Impact

The rule reduces the risk that normal navigation causes Render restarts, temporary 502s, or user-visible instability. It also creates a clear review standard for future SaaS onboarding, dashboard, reports, observations, and large-data changes.

## Technical Impact

Future changes that add broad data loading, reference datasets, exports, diagnostics, or startup work must include memory-conscious design and validation. The local stabilization patch also reduces current risk by gating observation diagnostics and changing location lookup to scoped loading.

## Documentation Updated

- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/PROJECT_STATE.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/CHANGE_HISTORY.md`

## PDF Regenerated

Yes

## Follow-Up Needed

Review, commit, and deploy the stabilization changes when approved. After deployment, monitor Render memory, restart count, warning logs, and 502 frequency.
