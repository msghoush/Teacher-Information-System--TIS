---
title: TIS KMS Navigation Guide
documentation_version: 3.1
last_updated: 2026-07-21
source_of_truth: true
---

# TIS KMS Navigation Guide

Use this guide to choose the smallest useful reading path for the work in front of you. Markdown under `docs/` remains authoritative; this file organizes that knowledge but does not replace module, architecture, decision, or history documents.

## Start Here

For any engineering task, begin with:

1. [AI Project Context](AI_PROJECT_CONTEXT.md) for the compact system orientation and current guardrails.
2. [TIS Master Context](TIS_MASTER_CONTEXT.md) for durable product, architecture, SaaS, and workflow truth.
3. [Project State](PROJECT_STATE.md) for current priorities, completed milestones, known issues, and next work.
4. [Documentation Update Policy](DOCUMENTATION_UPDATE_POLICY.md) for KIA and completion requirements.
5. [Development Standards](engineering/DEVELOPMENT_STANDARDS.md) before changing implementation code.

Then select the task path below. Read relevant ADRs and module history before editing.

## New Human Developer

Read in this order:

1. [Engineering Handbook Index](engineering/README.md)
2. [TIS Module Map](engineering/TIS_MODULE_MAP.md)
3. [Repository Architecture](engineering/REPOSITORY_ARCHITECTURE.md)
4. [User and System Flows](engineering/USER_AND_SYSTEM_FLOWS.md)
5. [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)
6. [Development Standards](engineering/DEVELOPMENT_STANDARDS.md)
7. [Project Governance](engineering/PROJECT_GOVERNANCE.md)

## New AI Coding Conversation

Read in this order:

1. [AI Project Context](AI_PROJECT_CONTEXT.md)
2. [AI Optimization Guide](engineering/AI_OPTIMIZATION_GUIDE.md)
3. [AI Coding Workflow](engineering/AI_CODING_WORKFLOW.md)
4. [Repository Architecture](engineering/REPOSITORY_ARCHITECTURE.md)
5. [TIS Module Map](engineering/TIS_MODULE_MAP.md)
6. Relevant [ADRs](adr/README.md) and [module history](history/README.md)

Also follow the repository-level instructions in [`AGENTS.md`](../AGENTS.md).

## SaaS Accounts And Onboarding

Read:

- [User and System Flows](engineering/USER_AND_SYSTEM_FLOWS.md)
- [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)
- [ADR 0002: Separate SaaS Identity and Operational Users](adr/0002-separate-saas-identity-and-operational-users.md)
- [ADR 0005: Delayed Tenant Provisioning](adr/0005-delayed-tenant-provisioning-after-verified-payment.md)
- [SaaS Onboarding History](history/saas-onboarding/README.md)
- [Provisioning History](history/provisioning/README.md)

Guardrail: SaaS accounts, platform identities, and operational users are separate security and ownership concepts.

## Subscriptions, Billing, And Paddle

Read:

- [TIS Module Map](engineering/TIS_MODULE_MAP.md)
- [User and System Flows](engineering/USER_AND_SYSTEM_FLOWS.md)
- [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)
- [ADR 0003: Paddle Payment Architecture](adr/0003-paddle-payment-architecture.md)
- [ADR 0004: Webhook-Only Payment Confirmation](adr/0004-webhook-only-payment-confirmation.md)
- [ADR 0005: Delayed Tenant Provisioning](adr/0005-delayed-tenant-provisioning-after-verified-payment.md)
- [Subscriptions History](history/subscriptions/README.md)

Guardrail: provider-confirmed state remains authoritative for paid entitlements, payment completion, proration, invoices, and lifecycle reconciliation.

## Operational Academic Modules

For teachers, subjects, sections, workforce planning, timetables, calendars, observations, and reports, read:

- [TIS Module Map](engineering/TIS_MODULE_MAP.md)
- [Repository Architecture](engineering/REPOSITORY_ARCHITECTURE.md)
- [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)
- [Development Standards](engineering/DEVELOPMENT_STANDARDS.md)
- [Workforce Planning History](history/workforce-planning/README.md)
- [Academic Calendar History](history/academic-calendar/README.md)

Guardrail: preserve tenant isolation, branch scope, role permissions, and active academic-year context.

## Database, Migrations, And Tenant Isolation

Read:

- [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)
- [Repository Architecture](engineering/REPOSITORY_ARCHITECTURE.md)
- [Development Standards](engineering/DEVELOPMENT_STANDARDS.md)
- [ADR 0002: Separate SaaS Identity and Operational Users](adr/0002-separate-saas-identity-and-operational-users.md)
- [Project State](PROJECT_STATE.md)

Guardrail: do not modify models, migrations, tenant boundaries, or `tis.db` without explicit approval and focused validation.

## Platform Owner And Knowledge Center

Read:

- [TIS Module Map](engineering/TIS_MODULE_MAP.md)
- [Project Governance](engineering/PROJECT_GOVERNANCE.md)
- [ADR 0006: Documentation as Source](adr/0006-documentation-as-source-knowledge-management-system.md)
- [Documentation Automation](engineering/DOCUMENTATION_AUTOMATION.md)
- [Knowledge Impact Assessment Standard](engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md)
- [Knowledge Lifecycle](engineering/KNOWLEDGE_LIFECYCLE.md)
- [Platform Knowledge History](history/platform-knowledge/README.md)
- [Engineering Handbook History](history/engineering-handbook/README.md)

Guardrail: KMS Markdown is reviewed source material, the PDF is generated, and protected documentation must remain owner-only.

## Public Landing Website

Read:

- [Landing Page Source of Truth](marketing/landing_page_source_of_truth.md)
- [Landing Page Master Content](marketing/tis_landing_page_master_content.md)
- [ADR 0001: Separate Next.js Landing Website](adr/0001-separate-nextjs-landing-website.md)
- [ADR 0007: Landing Page Visual System Strategy](adr/0007-landing-page-visual-system-strategy.md)
- [UI/UX Design Philosophy](engineering/UI_UX_DESIGN_PHILOSOPHY.md)
- [Landing Page History](history/landing-page/README.md)

Guardrail: the public website lives in `tis-landing-website/`; legacy FastAPI landing files are not its source of truth.

## Location Data

Read:

- [Location Data Roadmap](location-data-roadmap.md)
- [Repository Architecture](engineering/REPOSITORY_ARCHITECTURE.md)
- [Database Architecture Overview](engineering/DATABASE_ARCHITECTURE_OVERVIEW.md)

Guardrail: preserve runtime memory limits, local dataset boundaries, and record-level manual fallbacks.

## UI And Visual Design

Read:

- [UI/UX Design Philosophy](engineering/UI_UX_DESIGN_PHILOSOPHY.md)
- [Visual Documentation Guide](engineering/VISUAL_DOCUMENTATION_GUIDE.md)
- [Development Standards](engineering/DEVELOPMENT_STANDARDS.md)
- the relevant module or landing-page path above

## Architecture Decisions And Alternatives

Use:

- [ADR Index](adr/README.md) for accepted architectural and product decisions.
- [Rejected Decisions](engineering/REJECTED_DECISIONS.md) for significant alternatives that should not be reopened without new evidence.
- [Documentation Dependency Map](engineering/DOCUMENTATION_DEPENDENCY_MAP.md) to determine which KMS records a change should propagate through.

## Review, Release, And KIA

Read:

- [Project State](PROJECT_STATE.md)
- [Change History](CHANGE_HISTORY.md)
- [Project Governance](engineering/PROJECT_GOVERNANCE.md)
- [Self-Evolving Workflow](engineering/SELF_EVOLVING_WORKFLOW.md)
- [Knowledge Impact Assessment Standard](engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md)
- [Documentation Automation](engineering/DOCUMENTATION_AUTOMATION.md)

Use `python scripts/kms.py sync` after reviewed documentation changes and `python scripts/kms.py check` for complete read-only validation.

## Document Types

- **Core context:** durable truth, current state, policy, and chronological change summary.
- **Engineering handbook:** modules, repository boundaries, flows, data architecture, standards, design, governance, and roadmap.
- **ADRs:** accepted architectural and product decisions.
- **Rejected decisions:** important alternatives and why they were declined.
- **Module history:** deeper before-and-after records for a specific area.
- **Marketing documents:** approved public positioning and landing implementation boundaries.
- **Generated artifacts:** the PDF snapshot and manifest; never edit them manually.
