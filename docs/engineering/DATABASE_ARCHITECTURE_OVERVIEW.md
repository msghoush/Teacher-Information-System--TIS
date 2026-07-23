---
title: TIS Database Architecture Overview
documentation_version: 3.1
last_updated: 2026-07-23
source_of_truth: true
---

# TIS Database Architecture Overview

This document explains the conceptual TIS data model. It is intentionally high level and does not list every field. Use `models.py`, `saas/models.py`, and tests for exact implementation details.

## Core Boundary Principle

TIS has three identity/data worlds that must never be casually mixed:

- Platform data: platform owners, co-owners, developers, platform permissions, and cross-organization oversight.
- SaaS account data: public signup, onboarding, billing, pending organizations, and payment/provisioning readiness.
- Operational tenant data: provisioned school groups, branches, academic years, users, teachers, subjects, planning, timetable, calendar, and observations.

The safest mental model:

```text
Platform Owner oversees many organizations.
SaaS account prepares an organization for subscription/provisioning.
Operational tenant data belongs to one provisioned school group/branch/year context.
```

## Platform Identities

Represents:
Platform Owner, Co-Owner, and Platform Developer identities.

Ownership boundary:
Platform identities can operate outside ordinary tenant scope only through approved platform workflows.

Must never be mixed:
- Platform Developer must not become Platform Owner through permission drift.
- Platform users must not be treated as normal tenant users unless an explicit context workflow establishes scope.

Related files:
- `auth.py`
- `models.py`
- `permission_registry.py`
- `main.py`

## SaaS Accounts

Represents:
Public SaaS signup/login/account identities used before or alongside operational tenant access.

Ownership boundary:
SaaS accounts own onboarding and billing/account state, not operational school records directly.

Must never be mixed:
- SaaS account identity is not operational user identity.
- SaaS account creation must not directly create live tenant data.

Related files:
- `saas/models.py`
- `saas/service.py`
- `saas/router.py`
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`

## Pending Organizations

Represents:
An organization moving through SaaS onboarding before operational provisioning.

Ownership boundary:
Pending organization data belongs to the SaaS onboarding/provisioning pipeline.

Must never be mixed:
- Pending organization data is not the live school group until provisioning creates or connects operational records.

Related files:
- `saas/models.py`
- `saas/service.py`
- `saas/provisioning_service.py`

## Payment Records

Represents:
Payment, billing, checkout, and provider-confirmed subscription state.

Ownership boundary:
Payment state belongs to SaaS billing/subscription logic and should not be embedded directly into academic modules.

Must never be mixed:
- Checkout return navigation must not be treated as verified payment.
- Payment/provider details must not leak into operational teacher/planning/calendar logic.

Related files:
- `saas/payment_service.py`
- `saas/billing_service.py`
- `saas/paddle_client.py`
- `saas/entitlement_service.py`
- `saas/subscription_change_service.py`
- `saas/subscription_plan_change_service.py`
- `saas/subscription_cancellation_service.py`
- `saas/subscription_lifecycle_service.py`
- `saas/billing_history_service.py`
- `docs/adr/0003-paddle-payment-architecture.md`
- `docs/adr/0004-webhook-only-payment-confirmation.md`

### Entitlement And Subscription-Change Records

`EntitlementDefinition` defines commercial capability keys and value types. `PlanEntitlement` associates reviewed values with subscription plans. Runtime entitlement resolution starts from the provisioned school group, paid operational contract, and one confirmed active `PaymentSubscription`; it does not trust onboarding selections, page values, or pending checkout attempts.

`SubscriptionChangeRequest` is durable workflow/audit state for branch quantity, plan transition, and cancellation actions. It records requested/provider-observed state and lifecycle outcomes, but Paddle remains authoritative for monetary previews, proration, scheduled changes, transactions, and invoice documents.

Guardrails:

- `PaymentSubscription.quantity` is paid branch-capacity authority.
- unresolved ownership, duplicate active relationships, provider mismatches, or incomplete evidence fail closed.
- scheduled changes do not update effective local entitlements before verified provider/webhook evidence.
- billing history is retrieved from Paddle and is not copied into a new local financial ledger.
- invoice URLs are requested fresh and are not persisted.

## Provisioning Jobs

Represents:
Controlled work that turns a ready pending organization into operational school structures.

Ownership boundary:
Provisioning bridges SaaS data and operational tenant data, but only through explicit platform-owner-visible workflows.

Must never be mixed:
- Do not directly create operational tenant records from public signup or checkout return pages.
- Do not create records under the wrong school group.

Related files:
- `saas/provisioning_service.py`
- `saas/router.py`
- `docs/adr/0005-delayed-tenant-provisioning-after-verified-payment.md`

## School Groups / Organizations

Represents:
The top-level operational tenant boundary.

Ownership boundary:
Most tenant operational data belongs to a school group directly or through branch/year relationships.

Must never be mixed:
- Data from one school group must not appear in another school group's operational workflows.

Related files:
- `models.py`
- `main.py`

### Workspace Classification Metadata

`SchoolGroup` is the canonical operational workspace record. M8B-1 adds:

- globally unique, non-null `workspace_uuid`,
- constrained/indexed `workspace_classification`,
- constrained/indexed `workspace_lifecycle_status`.

Pre-provisioning intent remains on `PendingOrganization.workspace_intent`; identity intent remains on `SaaSAccount.account_purpose` and `User.is_internal_test_identity`. These fields are metadata only in M8B-1 and are not joined into payment, entitlement, authorization, or reset decisions.

Allowed workspace classifications are `internal_sandbox`, `customer_demo`, and `customer_paid`. Allowed lifecycle values are `provisioning`, `active`, `suspended`, and `archived`. New-schema tables use named check constraints and non-null columns. The compatibility migration fills legacy values, adds indexes and PostgreSQL constraints, and installs equivalent SQLite value guards without rebuilding existing tables.

The read-only diagnostic resolves relationship presence across `TenantProvisioningLink`, `PendingOrganization`, `SubscriptionContract`, `PaymentSubscription`, and `PaymentCustomer`. It reports no Paddle identifiers. The controlled backfill is one transaction, defaults to dry-run, records a durable marker, and never performs a workspace conversion.

### Commercial Entitlement Records

M8B-2 adds three normalized tables:

- `workspace_entitlements`: one effective entitlement envelope per SchoolGroup, with type, lifecycle status, source, optional confirmed payment-subscription link, and a validity window reserved for later workflows.
- `workspace_entitlement_values`: typed feature/limit values linked to the existing `EntitlementDefinition` catalog.
- `branch_entitlements`: optional branch-level inherit/active/inactive intent linked to the branch, SchoolGroup, and effective workspace entitlement.

A partial unique index permits only one active workspace entitlement per SchoolGroup. Branch entitlement is unique per branch. Check constraints protect entitlement type, status, source, mode, and validity-window ordering. Service validation additionally rejects cross-tenant branch links, stale workspace-entitlement references, invalid typed values, and classification/entitlement mismatches.

Migration `20260722_003_commercial_entitlement_foundation` seeds one foundation entitlement for each existing classified workspace without changing classification. It does not create branch overrides, convert Al-Andalus, or infer demo/paid policy. Paid rows are linked only when exactly one persisted active/trialing subscription can be identified; ambiguity remains unresolved and fails closed.

### SaaS Demo Request Records

M8B-3 adds three review-only tables:

- `saas_demo_requests`: one customer submission with requester, pending organization, optional future workspace reference, immutable classification/commercial/entitlement snapshots, status, and transition timestamps.
- `saas_demo_request_reviews`: one Platform Owner approval or rejection decision per request; rejected reviews require a reason.
- `saas_demo_request_events`: append-only audit and internal-notification events for submission and every status transition.

A partial unique index permits only one Pending Review request per pending organization. Check constraints protect request status, review decision, event category/type/actor, classification snapshot, commercial-state snapshot, and rejection-reason requirements. Migration `20260722_004_saas_demo_request_workflow` creates the records without backfill and without changing existing onboarding, payment, or workspace data.

### Demo Workspace Provisioning Records

M8B-4 adds:

- `saas_demo_workspace_provisioning`: one durable provisioning aggregate per demo request, with optional resulting SchoolGroup, workspace entitlement, and tenant link references; attempt count; status; activation time; and safe result/failure fields.
- `saas_demo_provisioning_events`: append-only provisioning audit/internal events for started, completed, failed, and activation-completed outcomes.

`tenant_provisioning_links` now permits either `subscription_contract_id` or `demo_request_id`, with a check constraint requiring exactly one source. Existing paid links retain their subscription contract. Demo links cannot carry a contract, and request/source uniqueness prevents one approved request from identifying multiple operational tenants.

Migration `20260723_001_demo_workspace_provisioning` generalizes the existing link without changing paid rows and creates the demo provisioning/event tables. Demo workspace, entitlement, link, request association, and activation updates are performed in one savepoint-backed transaction; failed workspace changes roll back while the outer provisioning aggregate retains the failure for audit and retry.

Related files:
- `workspace_classification.py`
- `saas/workspace_classification_service.py`
- `saas/workspace_classification_admin_service.py`
- `scripts/diagnose_workspace_classification.py`
- `scripts/backfill_workspace_classification.py`
- `docs/adr/0008-workspace-classification-foundation.md`
- `commercial_entitlements.py`
- `saas/commercial_validation_service.py`
- `saas/workspace_entitlement_service.py`
- `saas/branch_entitlement_service.py`
- `saas/commercial_state_service.py`
- `docs/adr/0009-commercial-state-and-entitlement-resolution.md`
- `demo_workflow.py`
- `saas/demo_provisioning_service.py`
- `saas/provisioning_service.py`
- `docs/adr/0011-demo-workspace-provisioning-and-commercial-source-links.md`
- `saas/demo_request_service.py`
- `docs/adr/0010-review-only-saas-demo-requests.md`

## Branches

Represents:
Campuses or branches inside a school group.

Ownership boundary:
Branches scope users, teachers, planning, timetable, academic calendar, branding, and reports.

Must never be mixed:
- Branch-scoped data must not silently cross campuses.
- Platform context switching must remain explicit.

Related files:
- `models.py`
- `main.py`
- `ui_shell.py`

## Academic Years

Represents:
The academic period used to scope operational records.

Ownership boundary:
Planning, timetable, subjects, calendar, and related data may depend on active academic year.

Must never be mixed:
- Do not copy or read current-year data into another year unless the workflow explicitly does so.

Related files:
- `models.py`
- `main.py`
- `year_copy.py`

## Operational Users

Represents:
Users who work inside an operational school group/branch/year context.

Ownership boundary:
Operational users belong to tenant structures and are governed by roles, permissions, branch scope, and active status.

Must never be mixed:
- Operational users are not SaaS accounts by default.
- Tenant users should not gain platform owner access.

Related files:
- `models.py`
- `auth.py`
- `routers/users.py`

## Roles And Permissions

Represents:
Role packages, permission keys, platform developer permissions, and route/action authorization.

Ownership boundary:
Permissions decide what a user can view or change in the current scope.

Must never be mixed:
- UI hiding is not enough; protected actions need route/service checks.
- Owner controls must remain outside developer-assignable permission drift.

Related files:
- `permission_registry.py`
- `role_permission_service.py`
- `authorization.py`
- `auth.py`

## Teachers

Represents:
Teacher records, qualifications, capacity, workload, and staffing-relevant academic data.

Ownership boundary:
Teacher records are tenant/branch/year-sensitive operational data.

Must never be mixed:
- Teacher data from one branch or school group must not appear in another tenant's planning/reporting.

Related files:
- `routers/teachers.py`
- `teacher_qualifications.py`
- `teacher_capacity.py`
- `models.py`

## Subjects

Represents:
Subject catalog, colors, requirements, qualification relationships, planning and timetable dependencies.

Ownership boundary:
Subjects are academic configuration data inside tenant/year context.

Must never be mixed:
- Subject changes can affect planning, timetable, teacher matching, and reports; update all affected docs/tests.

Related files:
- `routers/subjects.py`
- `subject_colors.py`
- `models.py`

## Sections / Classes

Represents:
Class sections used by planning and timetabling.

Ownership boundary:
Sections belong to operational branch/year structures.

Must never be mixed:
- Section structures should not cross branch/year boundaries accidentally.

Related files:
- `routers/planning.py`
- `models.py`

## Workforce Planning

Represents:
Teacher assignments, homeroom ownership, capacity, workload, subject coverage, and staffing needs.

Ownership boundary:
Planning is operational data tied to school group, branch, academic year, teachers, subjects, and sections.

Must never be mixed:
- Planning changes can affect dashboards, reports, timetable, and staffing decisions.

Related files:
- `routers/planning.py`
- `teacher_capacity.py`
- `homeroom_defaults.py`

## Timetable

Represents:
Weekly lesson placement and timetable settings.

Ownership boundary:
Timetable data depends on planning, teacher, subject, section, branch, and year context.

Must never be mixed:
- Timetable edits must preserve scheduling constraints and scope.

Related files:
- `routers/timetable.py`
- `timetable_logic.py`

## Academic Calendar

Represents:
Events, academic dates, responsibilities, exports, and calendar settings.

Ownership boundary:
Calendar records are branch/year/tenant scoped.

Must never be mixed:
- Calendar events for one tenant or branch must not appear in another.

Related files:
- `routers/academic_calendar.py`
- `templates/academic_calendar.html`

## Observations

Represents:
Teacher observation records, feedback, scoring, evidence, and history.

Ownership boundary:
Observation data is sensitive tenant operational data.

Must never be mixed:
- Observation records must remain tenant-scoped and permission-protected.

Related files:
- `routers/observations.py`
- `templates/observation_*.html`

## Knowledge Management System Artifacts

Represents:
Markdown docs, ADRs, module history, generated PDF, manifest, and Knowledge Center read-only status.

Ownership boundary:
Markdown under `docs/` is source of truth. Generated artifacts under `static/docs/` are snapshots.

Must never be mixed:
- The app must not silently rewrite Markdown source docs.
- The PDF must not be edited manually.
- Protected documentation access should go through owner-only routes.

Related files:
- `docs/`
- `scripts/generate_docs_pdf.py`
- `static/docs/`
- `knowledge_service.py`

## Tenant Isolation Rules

- Always know the current school group, branch, and academic year.
- Do not assume platform users have tenant scope.
- Do not assume SaaS accounts have operational records.
- Keep pending SaaS organization state separate from provisioned operational data.
- Preserve route permissions and service-level checks.
- Tests touching cross-tenant data should be treated as high value.
