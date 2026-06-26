---
title: TIS Rejected Architectural Decisions
documentation_version: 3.0
last_updated: 2026-06-26
source_of_truth: true
---

# TIS Rejected Architectural Decisions

This document records significant ideas that were considered and rejected. It helps future developers and AI assistants avoid reopening old decisions without new evidence.

Rejected decisions are not failures. They are part of the design record.

## Single Application For Landing And Portal

Date:
2026-06-26

Context:
TIS needs both a public marketing site and a protected operational app. The public site needs premium storytelling and conversion design; the app needs authenticated academic operations.

Proposed solution:
Use the FastAPI/Jinja app for both the public landing website and the operational portal.

Why rejected:
The two surfaces have different runtimes, audiences, design needs, deployment concerns, and risk profiles. Mixing them would make backend/operational tasks more likely to accidentally change the public website.

Chosen solution:
Keep `tis-landing-website/` as a separate Next.js public landing website and keep the FastAPI app as the operational portal.

Long-term consequences:
Developers must respect the landing/portal boundary. Landing changes require explicit approval and must use the Next.js source of truth.

## Stripe Instead Of Paddle

Date:
2026-06-26

Context:
TIS needs subscription payment collection, billing state, and future subscription lifecycle workflows.

Proposed solution:
Use Stripe as the payment provider.

Why rejected:
The current approved architecture is Paddle-oriented. Changing providers would reopen checkout, webhook, billing, tax/compliance, customer portal, and subscription lifecycle assumptions.

Chosen solution:
Use Paddle behind service/client boundaries in `saas/`.

Long-term consequences:
Provider-specific behavior must remain isolated. A future provider change would require a new ADR and careful migration plan.

## Immediate Tenant Provisioning

Date:
2026-06-26

Context:
Public signup and SaaS onboarding collect organization data before a school is ready for live operational access.

Proposed solution:
Create operational school group, branch, user, and academic records immediately after signup or checkout return.

Why rejected:
Immediate provisioning risks creating live tenant data before payment is verified, before onboarding is complete, or before platform owner review. Checkout return pages are not authoritative payment confirmation.

Chosen solution:
Delay tenant provisioning until payment/readiness is verified and use platform-owner-visible provisioning jobs.

Long-term consequences:
There are more states between signup and operational login, but tenant data is safer and provisioning can be reviewed/retried.

## Public Documentation Access

Date:
2026-06-26

Context:
The KMS generates a PDF under `static/docs/`, but the content includes internal architecture, roadmap, and operational guidance.

Proposed solution:
Link directly to the generated PDF through public static paths.

Why rejected:
Internal documentation should not be exposed as a public asset. Static file serving is not authorization-aware.

Chosen solution:
Expose the PDF through protected Platform Owner routes only.

Long-term consequences:
The UI must not link directly to `/static/docs/...`. Future storage may move generated docs outside public static storage.

## Documentation Without ADRs

Date:
2026-06-26

Context:
TIS decisions span SaaS identity, payments, provisioning, landing architecture, and KMS governance.

Proposed solution:
Keep only a master context and change history.

Why rejected:
Chronological history does not explain major decision tradeoffs deeply enough. Future developers would repeatedly reopen settled architecture questions.

Chosen solution:
Maintain ADRs under `docs/adr/` for major accepted decisions and this rejected-decision record for important alternatives.

Long-term consequences:
Major decisions require explicit traceability. ADRs and rejected decisions must be updated when architecture changes.

## Weak Generic Landing Page Design

Date:
2026-06-26

Context:
The public landing website is the first impression for schools evaluating TIS.

Proposed solution:
Use a generic SaaS layout with vague claims, weak fake 3D visuals, or internal implementation language.

Why rejected:
TIS needs credibility with school leaders. Generic visuals and internal language reduce trust and do not communicate academic operations value.

Chosen solution:
Use premium storytelling, strong visual assets, clear customer language, and the separate Next.js landing visual system.

Long-term consequences:
Landing work should be deliberate, visually strong, and customer-facing. Avoid terms like tenant, provisioning, and internal milestone labels.

## Mixing SaaS Identities With Operational Users

Date:
2026-06-26

Context:
TIS has public SaaS accounts, operational tenant users, and platform identities.

Proposed solution:
Use one identity concept for signup, billing, tenant access, and platform administration.

Why rejected:
This would weaken security and make it easy to confuse pending accounts with live operational users or platform owners.

Chosen solution:
Keep SaaS account identity, operational tenant identity, and platform identity distinct.

Long-term consequences:
Developers must always ask which identity world a change belongs to. Provisioning bridges worlds only through approved flows.

## App-Side Automatic Documentation Rewriting

Date:
2026-06-26

Context:
The KMS requires docs to remain current after meaningful implementation work.

Proposed solution:
Let the running app automatically rewrite Markdown docs when it detects staleness.

Why rejected:
Source-of-truth docs must be reviewed development artifacts. Silent rewriting would damage reviewability and could introduce incorrect historical records.

Chosen solution:
Developers or AI assistants update Markdown docs as part of approved implementation work. The app may detect freshness and expose status, but not rewrite source docs.

Long-term consequences:
Knowledge Impact Assessment remains a required human/AI workflow step. Future regenerate actions may rebuild PDFs only from reviewed Markdown.

## Uncontrolled Regenerate Button

Date:
2026-06-26

Context:
The Knowledge Center can show whether the PDF snapshot is current or stale.

Proposed solution:
Add an immediate button that regenerates docs and/or source files from the app.

Why rejected:
Phase 2C is read-only. Runtime regeneration raises deployment persistence, audit, concurrency, and source-control questions.

Chosen solution:
Do not add regenerate behavior until separately approved. Keep source docs updated through reviewed development work.

Long-term consequences:
A future regenerate action must be explicit, owner-only, audited where appropriate, and must not rewrite Markdown source docs.
