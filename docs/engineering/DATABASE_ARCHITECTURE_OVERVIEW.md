---
title: TIS Database Architecture Overview
documentation_version: 3.3
last_updated: 2026-08-26
source_of_truth: true
---

# TIS Database Architecture Overview

## Subject Scheduling Rules UI

No schema change was required. `subject_distribution_rules_ui.py` lists,
creates, updates, resets, and copies `subject_distribution_rules` rows through
the existing Stage 1 table and Stage 1/2 resolver/validator; Timetable
Settings routes under `/system-configuration/timetable-settings/subject-rules`
remain tenant/branch/year-scoped and reuse `timetable.manage_settings`.
The grade-first modal, search, two-period presets, and progressive disclosure are
presentation only; Planning totals, normalized rule persistence, legacy fallback,
and grouped Swimming authority are unchanged.
Operational timetable grade and section selectors use
`planning_scope_service.py`, which reads only Current/New `PlanningSection` rows
for one exact branch and academic year; global grade catalogs remain creation/edit
choices and are not operational selector authority.

## Subject Distribution Rules Generation Wiring

`timetable_snapshot_service.py` resolves and embeds the effective Subject
Distribution Rule per Planning demand at snapshot creation time using
`subject_distribution_rules.resolve_subject_distribution_rule`. The problem
builder, CP-SAT solver, independent validator, and `TimetableReadinessService`
all consume that resolved, per-demand authority; no schema change was
required beyond the Stage 1 table. `TimetableActiveVersion` and the
published/draft/history lifecycle are unaffected.

## Subject Distribution Rules Foundation

`subject_distribution_rules`, added by migration
`20260828_003_subject_distribution_rules_foundation`, is a normalized table scoped
`branch_default`, `grade`, or `section` per branch/academic year, with partial
unique indexes enforcing exactly one row per scope tier. It coexists with
`TimetableSetting.quality_rules_json`; an absent normalized row means the existing
JSON authority applies unchanged for that scope.

## Timetable Academic Quality Configuration

`TimetableSetting.quality_rules_json`, added by migration
`20260828_002_smart_timetable_academic_quality_rules`, stores normalized exact-scope
academic distribution and grouped-activity authority. Generation copies it into an
immutable snapshot; timetable versions and published-pointer relationships are
unchanged.

## On-Demand Generation Execution

No schema migration is required for Render Workflows. The existing generation run
public ID identifies task input; status, exact scope, snapshot, attempt, lease,
heartbeat, cancellation, safe failure, and result columns remain authoritative.
An on-demand task locks and claims exactly its queued public ID. Duplicate task
invocations see an active or terminal row and do not solve or persist again.
Immediate web dispatch failure atomically marks only a still-queued run
`internal_error` with `workflow_dispatch_failed`. The partial unique active-scope
index and atomic candidate transaction remain unchanged.

## Smart Timetable Stage 5.1 Queue Migration

Migration `20260822_001_smart_timetable_stage51_generator` is additive and
idempotent. It extends the existing `timetable_generation_runs` table with
`progress_phase`, non-negative `attempt_count`, `cancel_requested_at`, and a
nullable cancellation actor foreign key. It adds a `(status, lease_expires_at,
queued_at)` claim index and a partial unique exact-scope index for active
statuses. Duplicate active scopes fail migration preflight instead of being guessed
or rewritten. PostgreSQL receives named progress/attempt checks and the actor FK.

No parallel queue table, lesson-instance column, room/resource table, quality score,
or active-pointer mutation is introduced. Successful persistence inserts one
`TimetableVersion`, all `TimetableEntry` rows, snapshot/run linkage, and terminal
run state in one transaction; failure rolls the candidate back.

## Capacity-Based Packaging Reconciliation

Migration `20260819_001_capacity_based_customer_feature_baseline` is additive and
idempotent. It upserts the nine normal customer `PlanEntitlement` booleans to
active/true for Starter, Professional, and Enterprise AI, synchronizes the
legacy AI, Advanced Reporting, and multi-branch availability flags, and leaves
`priority_support` separate. It does not update any branch/staff/teacher ceiling
or Paddle quantity.

For a promo grant that is active at migration time, missing or false normal
customer `WorkspaceEntitlementValue` rows are inserted or corrected. The derived
branch quota, staff/teacher grant capacity, PromoGrant, PromoRedemption, branch
assignments, tenant source, and payment tables are untouched. Expired or
incoherent promo authority is not reactivated or reconciled.

Active customer-demo policy rows receive the normal baseline while retaining
stored experimental keys and all AI allowance/unrestricted configuration. Paid
workspaces need no value backfill because their workspace entitlement resolves
the current PlanEntitlement matrix. `feature.audit_log` remains
`owner_approval_required`; the implemented audit export is Developer-only.

AI counters now permit the existing `promo` metric context in addition to paid,
demo, and internal contexts through the already text-based field. No new AI
table or provider billing record is introduced.

## SchoolGroup Creation Provenance Audit

No schema or migration is added for the Stage 5 authorization correction. Direct
operational create/delete is restricted to Platform identities with global
SchoolGroup capability, while tenant updates resolve the linked SchoolGroup before a
row is loaded for mutation. Branch capacity continues to lock and recount the owning
SchoolGroup in the mutation transaction.

`scripts/audit_schoolgroup_provenance.py` queries active `internal_sandbox`
SchoolGroups that lack both `TenantProvisioningLink` and explicit
`WorkspaceEntitlement` evidence. It reports only a numeric review key, hashed
workspace reference, timestamp, aggregate operational counts, and review guidance.
The PostgreSQL transaction is repeatable-read and read-only and is always rolled
back. Findings are never automatically linked, reclassified, suspended, or deleted.

## Promo Redemption And Grant Persistence

Migration `20260805_002_promo_redemption_and_grants` creates:

- `promo_activation_sessions` and `promo_activation_branch_selections` for
  short-lived, resumable, non-authoritative customer review state;
- `promo_redemptions` for completed immutable redemption evidence;
- `promo_grants` for immutable plan, capacity, scope, and effective-window
  authority;
- `promo_grant_branch_assignments` for selected covered operational branches;
- `promo_redemption_events` for redacted, idempotent durable outcomes.

Raw promo material is absent from every table. Snapshot hashes bind the
definition, scope, tier, limits, and effective dates used at activation. Unique
and partial indexes protect session/idempotency identity, one redemption per
session, one grant per redemption, one active grant per workspace, branch
assignment uniqueness, and durable operation/event deduplication.

`workspace_entitlements.promo_grant_id` links only promo entitlements.
`tenant_provisioning_links.pending_organization_id` is nullable for an existing
aligned tenant and `promo_grant_id` identifies promo ownership. A check requires
exactly one of subscription contract, demo request, or promo grant. The
migration preserves existing rows, rebuilds equivalent SQLite constraints where
required, installs PostgreSQL foreign keys/checks/indexes, and is idempotent.

## Promo Code Foundation Persistence

`promo_codes` owns UUID identity, HMAC-SHA256 lookup hash and key ID, safe
display fragments, controlled lifecycle, exact plan-bounded capacity, target
anchors and deletion-safe snapshot, redemption-policy definition, one expiry
policy, replacement predecessor, and actor/approval timestamps. Unique indexes
protect UUID, lookup hash, and one replacement per predecessor. CHECK
constraints enforce lifecycle, benefit, scope, positive capacities, version,
redemption limits, date ordering, expiry XOR, and required primary targets.

`promo_code_branch_restrictions` preserves the selected existing branch ID and
name even if the live branch reference is later removed. It grants no access.
`promo_code_audit_events` stores actor, allowlisted before/after JSON, result,
reason, operation/correlation identity, and failure code without raw code,
lookup hash, HMAC key ID, or secret. Organization and actor references use
`ON DELETE SET NULL` while snapshots preserve history. Migration
`20260805_001_promo_code_foundation` is additive, idempotent, transaction-safe,
SQLite/PostgreSQL compatible, and has no data backfill.

## M8B9 Demo Operations Persistence

`demo_access_policies` stores a workspace default and optional branch override
with controlled profile/registry values. `demo_operation_audits` stores actor,
scope, action, reason, before/after JSON, result, communication references,
failure code, and operation key. Provisioning adds `expiry_policy`; email
intents add variant payload JSON. Idempotent migration
`20260727_003_m8b9_demo_operations` uses the active DDL connection and existing
pre-deploy PostgreSQL lock and statement timeout protections.

## Deployment Migration Boundary

Database schema work belongs to `python scripts/run_migrations.py`, never the
FastAPI web process. The command registers core and SaaS metadata, creates the
repository's baseline metadata schema, and then calls the ordered,
authoritative `db_migrations.run_pending_migrations` ledger. It logs each
newly-applied identifier, is idempotent when the ledger is current, and exits
nonzero on any schema or migration failure. Render must use it as a Pre-Deploy
Command so a failed migration prevents the new web version from becoming
active. Migration-owned PostgreSQL lock and statement timeout protections
remain in force. The migration process additionally applies a 10-second
connection timeout, 5-second lock timeout, and 30-second statement timeout at
PostgreSQL connection creation so baseline `metadata.create_all()`,
`schema_migrations` initialization, every ordered migration, and commit are
bounded. Flushed progress logging brackets each phase and migration identifier.
Within a migration transaction, catalog inspection and DDL must use the same
SQLAlchemy `Connection`; helper code must not inspect the `Engine`, because a
second PostgreSQL session can wait on uncommitted DDL locks held by the first
session and self-deadlock the migration process.

## M8B8 AI Usage Persistence

`ai_feature_usage_counters` is unique by SchoolGroup, registered feature key,
and metric context (`internal_sandbox`, `demo`, or `paid`). Its locked
successful and reserved counts provide the concurrency-safe allowance boundary.
`ai_feature_usage_events` is the durable operation ledger and uniquely
deduplicates an operation within the same scope. Pending reservations become
successful or failed; failure releases capacity and does not increment usage. Classification and plan
snapshots preserve historical metric separation without changing workspace
classification authority.

## M8B7 Demo Communication Persistence

`saas_demo_email_deliveries` is the durable email outbox. It links each logical message to a demo request and optionally its provisioning aggregate, constrains email type and delivery state, and uniquely deduplicates delivery. `system_notifications` carries destination, deduplication, category, and severity metadata for owner demo events. Existing request, provisioning, lifecycle, entitlement, and conversion rows remain authoritative.

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

Subscription capacity uses three separate persisted dimensions.
`pending_organization_branches.estimated_system_users` and
`estimated_teachers` store required non-negative onboarding estimates.
`subscription_plans.max_branches`, `max_system_users`, and `max_teachers`
store plan limits. Migration
`20260729_001_subscription_capacity_dimensions` adds the new columns and
assigns legacy organization-level system-user and teacher totals to the primary
active branch only when all branch estimates are zero. Subsequent organization
totals are derived compatibility summaries.

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

### Existing Workspace Paid Activation

Migration `20260806_002_existing_workspace_paid_activation` adds a direct paid
activation context for an existing SchoolGroup. `ExistingWorkspacePaidActivation`
stores workspace/account/owner identity, selected plan and interval, provider price,
branch quantity and immutable selection hash, quote fingerprint and amounts,
idempotency, checkout/payment/contract lineage, provider transaction/subscription
identity, lifecycle, and safe failure state. Versioned branch rows retain stable
branch snapshots, and append-only redacted events retain lifecycle evidence.

CheckoutSession and PaymentAttempt enforce an XOR between PendingOrganization and
existing-workspace activation contexts. SubscriptionContract and
PaymentSubscription permit a null PendingOrganization only when commercial authority
is anchored through SchoolGroup/contract. OrganizationBillingProfile supports an
exclusive PendingOrganization or SchoolGroup context. Explicit
PaymentCustomerWorkspaceAssociation rows prevent implicit provider-customer sharing.
They persist the provider address and business selected for each SchoolGroup so
workspace billing identity remains stable even when the underlying customer is shared.
Unique indexes enforce one unresolved activation per SchoolGroup and unique provider
transaction/subscription mappings. No tenant-owned operational table is copied.

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
- `saas_demo_domain_eligibilities`: one unique normalized organization-domain reservation for a Customer Demo opportunity, optionally linked to historical request evidence or marked for manual review when legacy records are ambiguous.

A partial unique index permits only one Pending Review request per pending organization. Check constraints protect request status, review decision, event category/type/actor, classification snapshot, commercial-state snapshot, and rejection-reason requirements. Migration `20260722_004_saas_demo_request_workflow` creates the records without backfill and without changing existing onboarding, payment, or workspace data.

Migration `20260725_001_demo_domain_eligibility_policy` adds customer journey-intent fields, a nullable normalized domain snapshot, and the eligibility table with a database unique invariant. It backfills unambiguous Customer Demo records, reserves ambiguous duplicate domains for manual review, and never merges, deletes, reprovisions, or replaces customer workspaces. `scripts/diagnose_demo_domain_eligibility.py` is dry-run by default and can apply the same safe reservation backfill after review.

Historical detached eligibility rows are handled without schema changes through a Platform Owner-only maintenance service. It treats the eligibility primary key as the only deletion scope and checks domain-bearing organization, account, request, tenant-profile workspace, provisioning, subscription, and conversion relationships plus manual-review evidence before removal. The row is locked and re-analyzed, then deleted by exact ID, flushed, verified absent, and committed atomically with a durable external audit record. Normal customer eligibility rows remain durable.

### Demo Workspace Provisioning Records

M8B-4 adds:

- `saas_demo_workspace_provisioning`: one durable provisioning aggregate per demo request, with optional resulting SchoolGroup, workspace entitlement, and tenant link references; attempt count; status; activation time; and safe result/failure fields.
- `saas_demo_provisioning_events`: append-only provisioning audit/internal events for started, completed, failed, and activation-completed outcomes.

`tenant_provisioning_links` now permits either `subscription_contract_id` or `demo_request_id`, with a check constraint requiring exactly one source. Existing paid links retain their subscription contract. Demo links cannot carry a contract, and request/source uniqueness prevents one approved request from identifying multiple operational tenants.

Migration `20260723_001_demo_workspace_provisioning` generalizes the existing link without changing paid rows and creates the demo provisioning/event tables. Demo workspace, entitlement, link, request association, and activation updates are performed in one savepoint-backed transaction; failed workspace changes roll back while the outer provisioning aggregate retains the failure for audit and retry.

### Demo Workspace Lifecycle Records

M8B-5 extends `saas_demo_workspace_provisioning` with reminder due/sent, demo expiration, expired, processing-status, last-processed, and failure-code metadata. `activated_at` remains the authority; persisted reminder and expiration timestamps are derived indexes and must validate as activation plus six and seven days.

Two normalized tables support lifecycle history and in-app delivery:

- `saas_demo_lifecycle_events`: deduplicated audit records for reminder due/delivery, expiration start/completion, workspace suspension, access blocking, and processing failure.
- `saas_demo_lifecycle_notifications`: recipient-scoped internal reminder notifications for the requesting SaaS account and active Platform Owners.

Migration `20260723_002_demo_workspace_lifecycle` adds constrained lifecycle metadata, backfills activation-derived timestamps for existing active demos, aligns demo entitlement `effective_to`, and creates the event/notification tables. It does not expire data during migration. The separately scheduled processor performs expiration after a dry run.

### Demo-To-Paid Conversion Records

M8B-6 adds:

- `saas_demo_to_paid_conversions`: one durable conversion aggregate per demo request, provisioning record, and SchoolGroup. It links the existing demo workspace to the confirmed `SubscriptionContract` and `PaymentSubscription`, records the previous demo entitlement and resulting paid entitlement, and tracks requested, processing, completed, or failed status.
- `saas_demo_conversion_events`: append-only audit and internal-notification history for conversion requested, started, completed, and failed outcomes.

Migration `20260723_003_demo_to_paid_conversion` also permits the terminal `converted` demo lifecycle processing status. Conversion never creates another SchoolGroup or tenant link. One atomic workspace transaction ends the demo entitlement, creates the paid entitlement, relinks existing branch entitlements, changes the SchoolGroup classification, and moves the existing tenant link from the preserved demo-request source to the confirmed subscription contract. Provider payment records commit independently and remain intact if workspace conversion rolls back.

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
- `saas/demo_lifecycle_service.py`
- `saas/demo_conversion_service.py`
- `scripts/process_demo_lifecycle.py`
- `authorization.py`
- `saas/provisioning_service.py`
- `docs/adr/0011-demo-workspace-provisioning-and-commercial-source-links.md`
- `docs/adr/0012-seven-day-demo-lifecycle-and-access-enforcement.md`
- `docs/adr/0013-demo-to-paid-workspace-conversion.md`
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
Weekly lesson placement, timetable settings, durable versions, immutable input
snapshots, one active-version pointer per scope, placement locks, and future
generation-run evidence.
`TimetableNonTeachingBlock` retains legacy start/end and period columns and adds
`placement_mode`, `insert_after_period`, and `duration_minutes`. The additive migration
defaults existing rows to `fixed_time`; compatibility composition does not rewrite their
stored clock values. After-period metadata is authoritative for newly inserted blocks.

Ownership boundary:
Timetable data depends on planning, teacher, subject, section, branch, and year context.

Must never be mixed:
- Timetable edits must preserve scheduling constraints and scope.
- `TimetableEntry` belongs to exactly one version and preserves section/teacher
  collision guarantees inside that version. Its branch/year must match the
  pointed version.
- `TimetableActiveVersion` is the only active-selection authority and its
  SchoolGroup/Branch/Academic-Year tuple must match the target version exactly.
- Active, superseded, and archived versions are immutable. Mutable compatibility
  edits occur on a draft copy.

Related files:
- `routers/timetable.py`
- `timetable_logic.py`
- `timetable_version_service.py`
- `timetable_snapshot_service.py`
- `docs/adr/0026-versioned-constraint-based-smart-timetable-generation.md`

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
