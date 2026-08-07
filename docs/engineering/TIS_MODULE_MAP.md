---
title: TIS Module Map
documentation_version: 3.1
last_updated: 2026-08-05
source_of_truth: true
---

# TIS Module Map

## M3 Promo Redemption Components

- `saas/promo_redemption_service.py`: secure lookup, owner/context validation,
  resumable review and selection, locking, immutable snapshots, activation,
  idempotency, and redacted durable events.
- `saas/promo_grant_service.py`: read-time grant/expiry resolution and safe
  assignment of a newly created branch from remaining promo capacity.
- `saas/models.py` and `db_migrations.py`: six M3 tables plus promo entitlement
  and tenant-source references under migration
  `20260805_002_promo_redemption_and_grants`.
- `saas/commercial_authority_service.py`, commercial access/state/workspace and
  branch entitlement resolvers, and `auth.py`: M1 promo source composition and
  fail-closed branch enforcement.
- `saas/router.py`, `templates/saas/promo_activation.html`,
  `templates/saas/commercial_choice.html`, and `templates/saas/account.html`:
  owner-only onboarding and existing-organization activation journey.

## Existing Workspace Paid Activation

**Primary files**

- `saas/existing_workspace_paid_activation_service.py`
- `saas/billing_identity_service.py`
- `saas/payment_service.py`
- `templates/saas/existing_workspace_paid_activation.html`

**Responsibility**

Activate a previously converted existing customer workspace through an
authoritative Paddle subscription while preserving the existing SchoolGroup and all
operational data. The module owns direct activation eligibility, branch/capacity
quote snapshots, checkout lineage, workspace billing/customer attribution, and the
atomic webhook-confirmed commercial transition. It does not own tenant provisioning,
normal onboarding checkout, promo redemption, or demo conversion.

M3 never calls Paddle, creates payment evidence, converts internal sandboxes,
or mutates staff/teacher activity. Exactly one paid/demo/promo tenant source is
required.

## M2 Promo Code Components

- `saas/promo_code_service.py`: secure generation and HMAC lookup authority,
  shared plan-capacity validation, controlled scope validation, lifecycle row
  locking, definition duplication/replacement, and redacted durable audit.
- `saas/models.py`: `PromoCode`, `PromoCodeBranchRestriction`, and
  `PromoCodeAuditEvent` remain the M2 definition records; M3 redemption/grant
  records are separate.
- `saas/router.py` and `templates/saas/admin_promo_code*.html`: Platform
  Console list/filter, generated-code one-time response, detail, edit, and
  lifecycle actions under `/saas-admin/promo-codes`.
- `permission_registry.py`: separate `promo_codes.view` and
  `promo_codes.manage` platform permissions. Owner identity is additionally
  required for activation and revocation.
- `db_migrations.py`: additive migration
  `20260805_001_promo_code_foundation` with no data backfill.

M2 definition management does not itself integrate with M1 authority,
WorkspaceEntitlement, TenantProvisioningLink, or Paddle. M3 performs that
integration only after final customer activation.

## M1 Commercial Access And Capacity Components

- `saas/commercial_authority_service.py`: single commercial-access composition,
  authoritative branch/staff/teacher counters, structured decisions, and
  SchoolGroup row locking.
- `saas/commercial_access_service.py`, `saas/commercial_state_service.py`,
  `saas/workspace_entitlement_service.py`, and `saas/entitlement_service.py`:
  existing authorities composed by the facade; they are not duplicated.
- `main.py`, `routers/users.py`, and `routers/teachers.py`: permission- and
  tenant-scoped operational mutation entry points that enforce the shared
  decision before writing.
- `saas/provisioning_service.py` and `saas/demo_provisioning_service.py`: paid
  and demo final-authority invariants inside their existing atomic provisioning
  transactions.

Guardrails: every capacity-increasing mutation locks then recounts in the same
transaction; platform identity never counts as tenant staff; account-only SaaS
identity never counts; demo/internal authority is unmetered only while its
existing lifecycle/access resolver is coherent; contradictory authority fails
closed.

## M8B9 Demo Operations Components

- `saas/demo_operations_service.py`: owner authorization, lifecycle
  orchestration, communication references, summaries, and durable audits.
- `saas/demo_access_service.py` and `saas/demo_feature_registry.py`: Standard,
  Full, and Custom resolution with workspace defaults and branch overrides.
- `DemoAccessPolicy` and `DemoOperationAudit`: policy and attempt history;
  M8B8 usage counters/events remain unchanged.
- Existing owner demo detail and queue surfaces host the controls.

## M8B8 AI Entitlement Components

- `saas/ai_feature_registry.py`: stable feature identifiers, display labels,
  required permission/entitlement, eligible plans, demo allowance, and enabled
  state.
- `saas/ai_entitlement_service.py`: tenant-safe decisions, consistent denial
  metadata, and the only reservation/finalization/consumption API.
- `AIFeatureUsageCounter` and `AIFeatureUsageEvent`: separated durable
  internal/demo/paid accounting.
- `permission_registry.py`: assignable `ai.use` authorization boundary.

## M8B7 Demo Customer Journey Components

- `saas/demo_email_service.py`: durable demo email intents, branded rendering inputs, provider dispatch, and retries.
- `saas/demo_notification_service.py`: deduplicated Platform Owner Notification Center events.
- Existing demo request, provisioning, lifecycle, and conversion services remain authoritative.
- `ui_shell.py` and `templates/base.html` own the active tenant demo indicator.
- `scripts/process_demo_lifecycle.py` remains dry-run by default and is the production apply/dispatch entry point.

This map describes the known TIS modules, where they live, their maturity, related docs/ADRs, and the guardrails developers must respect.

## Platform Owner

Purpose:
Own global TIS platform operations, owner/co-owner controls, platform developer accounts, cross-organization oversight, and protected KMS access.

Main files/folders:
- `auth.py`
- `main.py`
- `templates/platform_console.html`
- `templates/platform_knowledge_center.html`
- `knowledge_service.py`
- `permission_registry.py`

Maturity/status:
Implemented for owner identity, platform console, developer/co-owner controls, and read-only Knowledge Center.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/history/platform-knowledge/`

Risks/guardrails:
- Do not treat platform developers as owners.
- Do not expose owner utilities to tenant users.
- Reuse `auth.is_platform_owner(...)` and existing owner access helpers.

## Platform Console

Purpose:
Allow platform identities to inspect organizations, switch context, and manage platform owner/developer controls.

Main files/folders:
- `main.py`
- `templates/platform_console.html`
- `ui_shell.py`

Maturity/status:
Implemented and active.

Related docs/ADRs:
- `docs/PROJECT_STATE.md`

Risks/guardrails:
- Context switching must not weaken tenant isolation.
- Owner-only management controls must remain owner-only.

## Knowledge Center

Purpose:
Show KMS health, source coverage, PDF freshness, searchable document metadata, ADRs, module history, change history, and KIA policy to platform owners.

Main files/folders:
- `knowledge_service.py`
- `main.py`
- `templates/platform_knowledge_center.html`
- `static/docs/docs_manifest.json`
- `static/docs/TIS_Project_Reference_Booklet.pdf`

Maturity/status:
Read-only Phase 2C implementation complete and Phase 7C navigation enhanced. The manifest-backed library groups documents by knowledge area, filters locally by category/module/freshness, searches titles/summaries/paths, and links to protected booklet pages. Repository-level impact and freshness enforcement is active; no app regenerate button exists.

Related docs/ADRs:
- `docs/adr/0006-documentation-as-source-knowledge-management-system.md`
- `docs/history/platform-knowledge/`

Risks/guardrails:
- Do not link directly to `/static/docs/...` from UI.
- Treat the generated manifest as the source inventory and `pdf_page` authority; do not create a parallel catalog.
- Do not let the app rewrite Markdown source docs.
- Do not add regenerate behavior without approval.

## SaaS Account System

Purpose:
Handle public SaaS signup/login/account profile, sessions, security, billing visibility, and onboarding status.

Main files/folders:
- `saas/router.py`
- `saas/service.py`
- `saas/models.py`
- `templates/saas/`

Maturity/status:
M1-M5 foundation implemented.

Related docs/ADRs:
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`
- `docs/history/saas-onboarding/`

Risks/guardrails:
- Do not merge SaaS account identity with operational tenant users.
- Do not bypass verification/security/session boundaries.

## SaaS Onboarding

Purpose:
Collect organization, contact, branch, academic setup, and review data before provisioning.

Main files/folders:
- `saas/router.py`
- `saas/service.py`
- `templates/saas/onboarding_*.html`

Maturity/status:
Implemented foundation.

Related docs/ADRs:
- `docs/history/saas-onboarding/`
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`

Risks/guardrails:
- Pending onboarding data is not the same as operational tenant data.
- Do not create live tenant records directly from public forms.

## SaaS Demo Request Workflow

Purpose:
Offer verified customers a post-onboarding choice between the unchanged subscription workflow and a reviewed customer-demo workspace.

Main files/folders:
- `demo_workflow.py`
- `saas/demo_request_service.py`
- `saas/demo_eligibility_maintenance_service.py`
- `saas/demo_provisioning_service.py`
- `saas/demo_conversion_service.py`
- `saas/provisioning_service.py`
- `saas/router.py`
- `templates/saas/commercial_choice.html`
- `templates/saas/demo_request_status.html`
- `templates/saas/admin_demo_requests.html`
- `templates/saas/admin_demo_request_detail.html`
- `templates/saas/admin_demo_eligibility_maintenance.html`
- `templates/saas/admin_delete_demo_eligibility.html`

Maturity/status:
M8B-6 implemented. Submission, review, atomic provisioning, activation, seven-day lifecycle resolution, Day 6 internal reminders, Day 7 expiration, server-side expired-access enforcement, and provider-confirmed conversion of the existing demo tenant to Customer Paid are available. Manual extension, internal-sandbox conversion, archive/delete, and email delivery are not implemented.

Risks/guardrails:
- Do not confuse SaaS demo requests with legacy public marketing demo leads.
- Approval remains review evidence only; a separate Platform Owner provisioning action creates the workspace.
- Provisioning requires coherent approval, customer-demo intent, commercial state, entitlement snapshot, and organization data.
- Demo provisioning must not create or infer paid subscription evidence.
- Failed provisioning must roll back workspace records and preserve the Approved request for a controlled retry.
- `activated_at` is the only lifecycle clock authority; approval and submission timestamps never determine expiration.
- Expiration preserves tenant data and blocks all normal operational access rather than creating a read-only mode.
- Paid workspaces, internal sandboxes, and Platform Console access must never pass through demo expiration enforcement.
- Demo-to-paid conversion requires an active coherent demo and a confirmed M7 subscription for the same organization.
- Conversion preserves the SchoolGroup and tenant link row; it must never invoke operational reprovisioning.
- A failed workspace conversion preserves confirmed payment evidence, rolls back workspace mutations, records failure, and remains retryable.
- Completed conversions must not re-enter demo reminder or expiration processing.
- Historical eligibility maintenance is Platform Owner-only, deletes by exact eligibility ID only, and must fail closed on any organization, account, request, workspace, provisioning, subscription, conversion, or manual-review evidence.
- Eligibility maintenance must not replace, bypass, or weaken customer demo eligibility or organization-scoped clean-room reset.

Main M8B-5 and M8B-6 files:
- `saas/demo_lifecycle_service.py`
- `saas/demo_conversion_service.py`
- `scripts/process_demo_lifecycle.py`
- `authorization.py`
- `templates/demo_access_blocked.html`
- Subscribe Now must continue through the existing provider-authoritative billing path.
- Only Platform Owners may review, reject, approve, or cancel requests.
- Customer withdrawal is valid only while Pending Review.

## Workspace Classification Foundation

Purpose:
Provide stable, constrained metadata for distinguishing internal sandbox, customer demo, and customer-paid workspaces without changing commercial or customer behavior.

Main files/folders:
- `workspace_classification.py`
- `saas/workspace_classification_service.py`
- `saas/workspace_classification_admin_service.py`
- `saas/commercial_state_service.py`
- `scripts/diagnose_workspace_classification.py`
- `scripts/backfill_workspace_classification.py`

Maturity/status:
M8B-6 commercial transition implemented only for the dedicated active Customer Demo to Customer Paid workflow. Classification, lifecycle, workspace entitlement, branch entitlement, and effective commercial state remain centrally resolved. Other classification conversions remain prohibited.

Related docs/ADRs:
- `docs/adr/0008-workspace-classification-foundation.md`
- `docs/history/workspace-classification/README.md`
- `docs/adr/0009-commercial-state-and-entitlement-resolution.md`

Risks/guardrails:
- Do not use classification as a payment, entitlement, permission, tenant-isolation, or reset gate in M8B-1.
- Permit classification conversion only through the dedicated M8B-6 demo-to-paid service.
- Do not expose workspace metadata outside Platform Owner views.
- Do not infer customer-paid classification from incomplete onboarding or provider records.
- Keep paid plan capabilities authoritative in the existing M7 subscription entitlement resolver.
- Fail closed on missing, ambiguous, orphaned, stale, or cross-tenant entitlement relationships.
- Do not use M8B-2 results for tenant authorization or feature enforcement yet.

### Commercial Entitlement Resolution

Purpose:
Resolve effective workspace entitlement, branch commercial activity, and commercial state from persisted local evidence without modifying rows or calling Paddle.

Main files/folders:
- `commercial_entitlements.py`
- `saas/commercial_validation_service.py`
- `saas/workspace_entitlement_service.py`
- `saas/branch_entitlement_service.py`
- `saas/commercial_state_service.py`
- `saas/models.py`

Maturity/status:
M8B-2 read-only foundation implemented. No customer-facing enforcement, demo expiration, billing mutation, or conversion orchestration.

## Pending Organizations

Purpose:
Represent the Platform Owner work queue for organizations still waiting on setup, review, payment, or incomplete/recoverable provisioning, while preserving completed and historical records separately.

Main files/folders:
- `saas/models.py`
- `saas/service.py`
- `saas/router.py`
- `templates/saas/admin_pending_organizations.html`
- `templates/saas/admin_pending_organization_detail.html`

Maturity/status:
Implemented with lifecycle-aware pending filtering and retained Organization Records.

Related docs/ADRs:
- `docs/adr/0005-delayed-tenant-provisioning-after-verified-payment.md`

Risks/guardrails:
- Keep pending state separate from provisioned tenant state.
- Do not count a row as pending when a tenant link, completed provisioning job, or final tenant billing state exists.
- Resolve active tenant display from coherent payment, active subscription, contract, tenant-link, and active SchoolGroup evidence; conflicting completed evidence must fail closed to Lifecycle Review Required.
- Preserve raw onboarding fields as history rather than rewriting them solely for owner presentation.
- Preserve platform owner review and auditability.

## Plans And Pricing

Purpose:
Define SaaS plan catalog and pricing behavior.

Main files/folders:
- `saas/pricing_service.py`
- `saas/router.py`
- `saas/entitlement_service.py`
- `saas/subscription_portal_service.py`
- `saas/subscription_change_service.py`
- `saas/subscription_plan_change_service.py`
- `saas/subscription_cancellation_service.py`
- `saas/subscription_lifecycle_service.py`
- `templates/saas/plan_catalog.html`
- `templates/saas/plan_selection.html`
- `templates/saas/subscription.html`

Maturity/status:
M7 implemented: entitlement catalog, customer portal, quantity and plan management, scheduled changes, cancellation/reversal, and centralized lifecycle/action policy.

Related docs/ADRs:
- `docs/history/subscriptions/`
- `docs/adr/0003-paddle-payment-architecture.md`

Risks/guardrails:
- Plan changes must update docs and change history.
- Do not hard-code provider behavior outside service boundaries.

## Paddle / Payment

Purpose:
Integrate subscription checkout, payment state, billing status, and provider events.

Main files/folders:
- `saas/paddle_client.py`
- `saas/payment_service.py`
- `saas/billing_service.py`
- `saas/currency_service.py`
- `saas/router.py`
- `saas/billing_history_service.py`
- `saas/payment_lifecycle_reconciliation_service.py`

Maturity/status:
Implemented through M7, including provider-authoritative previews/proration, billing history, invoice access, webhook idempotency, fail-closed reconciliation, diagnostics, and guarded repair tooling.

Related docs/ADRs:
- `docs/adr/0003-paddle-payment-architecture.md`
- `docs/adr/0004-webhook-only-payment-confirmation.md`
- `docs/history/subscriptions/`

Risks/guardrails:
- Webhook-confirmed payment state is authoritative.
- Checkout return alone must not trigger verified payment/provisioning.
- TIS must not calculate replacement financial outcomes when Paddle preview/transaction data is authoritative.
- Scheduled provider changes must not become local entitlement truth before verified effective evidence.
- Invoice URLs must be freshly resolved and must not be stored.

## Provisioning

Purpose:
Convert verified/approved pending organizations into operational tenant structures.

Main files/folders:
- `saas/provisioning_service.py`
- `saas/router.py`
- `templates/saas/admin_provisioning.html`

Maturity/status:
Implemented foundation.

Related docs/ADRs:
- `docs/adr/0005-delayed-tenant-provisioning-after-verified-payment.md`
- `docs/history/provisioning/`

Risks/guardrails:
- Keep provisioning recoverable and reviewable.
- Do not merge tenants or create records in the wrong school group.

## Operational Login

Purpose:
Authenticate operational users and route them into platform or tenant context.

Main files/folders:
- `main.py`
- `auth.py`
- `templates/login.html` if present through root templates

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`

Risks/guardrails:
- Platform users and tenant users follow different context behavior.
- Preserve permission and active-user checks.

## Dashboard

Purpose:
Give tenant users operational visibility into staffing, planning, reports, and current school context.

Main files/folders:
- `main.py`
- `templates/dashboard.html`
- related report/export helpers

Maturity/status:
Implemented and evolving.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Dashboard data must remain scoped to tenant/branch/year context.

## Organizations / School Groups

Purpose:
Represent tenant organizations and top-level school group context.

Main files/folders:
- `models.py`
- `main.py`
- `templates/system_configuration_schools.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`

Risks/guardrails:
- Tenant isolation starts at school group boundaries.

## Branches

Purpose:
Represent campuses/branches inside a school group.

Main files/folders:
- `models.py`
- `main.py`
- `templates/system_configuration_branches.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`

Risks/guardrails:
- Branch scope affects teachers, users, planning, timetable, calendar, branding, and reports.

## Academic Years

Purpose:
Scope operational data by academic year and active-year context.

Main files/folders:
- `models.py`
- `main.py`
- `templates/system_configuration_years.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`

Risks/guardrails:
- Do not mix data across academic years.

## Users And Roles

Purpose:
Manage tenant users, platform users, roles, profile data, active status, and branch/year context.

Main files/folders:
- `auth.py`
- `routers/users.py`
- `models.py`
- `templates/users.html`
- `templates/edit_user.html`

Maturity/status:
Implemented with platform identity refinements.

Related docs/ADRs:
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`

Risks/guardrails:
- Do not assign owner controls to developers or tenant users.
- Preserve role normalization.

## Permissions

Purpose:
Control route/module actions by permission key and role package.

Main files/folders:
- `authorization.py`
- `permission_registry.py`
- `role_permission_service.py`
- `auth.py`
- `templates/system_configuration_role_permissions.html`

Maturity/status:
Implemented and critical.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`

Risks/guardrails:
- Do not bypass `authorization.enforce_route_permission`.
- Do not rely only on UI hiding for protected actions.

## Teachers

Purpose:
Manage teacher records, qualifications, capacity, workloads, and profile-related academic staffing data.

Main files/folders:
- `routers/teachers.py`
- `teacher_qualifications.py`
- `teacher_capacity.py`
- `models.py`
- `templates/teachers.html`
- `templates/edit_teacher.html`

Maturity/status:
Implemented and central to operational value.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Teacher data must remain tenant/branch/year scoped.

## Subjects

Purpose:
Manage subject catalog, colors, qualifications, and planning/timetable relationships.

Main files/folders:
- `routers/subjects.py`
- `subject_colors.py`
- `models.py`
- `templates/subjects.html`
- `templates/edit_subject.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Subject changes can affect planning, timetable, teacher qualifications, and reports.

## Sections

Purpose:
Represent class/section structures used by planning and timetabling.

Main files/folders:
- `routers/planning.py`
- `models.py`
- `templates/planning.html`

Maturity/status:
Implemented through planning workflows.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Section changes can affect timetable allocation and workload reporting.

## Workforce Planning

Purpose:
Plan assignments, homeroom ownership, workloads, subject coverage, and staffing needs.

Main files/folders:
- `routers/planning.py`
- `teacher_capacity.py`
- `homeroom_defaults.py`
- `templates/planning.html`

Maturity/status:
Implemented and evolving.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Planning logic must preserve branch/year scope and avoid accidental cross-year copies.

## Timetable

Purpose:
Place planned lessons into weekly timetable grids and exports.

Main files/folders:
- `routers/timetable.py`
- `timetable_logic.py`
- `templates/timetable.html`
- `templates/system_configuration_timetable.html`

Maturity/status:
Implemented and evolving.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Timetable rules interact with planning, sections, subjects, and teacher capacity.

## Academic Calendar

Purpose:
Manage academic events, responsibilities, dates, exports, and branch/year scoped calendar views.

Main files/folders:
- `routers/academic_calendar.py`
- `templates/academic_calendar.html`
- `templates/system_configuration_calendar.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/history/academic-calendar/`

Risks/guardrails:
- Calendar permissions and branch/year scoping must remain intact.

## Observations

Purpose:
Support teacher observations, feedback, evidence, scoring, history, and supervision records.

Main files/folders:
- `routers/observations.py`
- `templates/observations.html`
- `templates/observation_form.html`
- `templates/observation_detail.html`
- `templates/observation_history.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`

Risks/guardrails:
- Observation records are sensitive and must remain tenant scoped.

## Reports / Dashboards

Purpose:
Expose operational summaries, exports, allocation reports, and decision visibility.

Main files/folders:
- `main.py`
- report/export helper code
- `templates/dashboard.html`

Maturity/status:
Implemented and evolving.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Report data must be permission-checked and tenant scoped.

## Branding / Design Settings

Purpose:
Manage organization logos, design settings, visual shell behavior, and platform visual controls.

Main files/folders:
- `branding_storage.py`
- `design_tokens.py`
- `visual_design.py`
- `ui_shell.py`
- `static/css/branding.css`
- `static/css/design-studio.css`
- `templates/system_configuration_logos.html`
- `templates/system_configuration_design.html`

Maturity/status:
Implemented.

Related docs/ADRs:
- `docs/adr/0007-landing-page-visual-system-strategy.md`

Risks/guardrails:
- Do not confuse operational app branding with public landing website design.
- Protect uploaded/owned assets.

## Landing Website

Purpose:
Public marketing and conversion surface for TIS.

Main files/folders:
- `tis-landing-website/`
- `docs/marketing/`

Maturity/status:
Implemented as separate Next.js app.

Related docs/ADRs:
- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`
- `docs/marketing/landing_page_source_of_truth.md`

Risks/guardrails:
- Do not modify landing code during operational/backend tasks unless explicitly approved.
- Legacy FastAPI landing files are not the public source of truth.

## AI Future Roadmap

Purpose:
Future subscription-gated AI-assisted planning, analytics, assessment generation, recommendations, and decision support.

Main files/folders:
- No dedicated AI production module yet.
- Future work should be documented before implementation.

Maturity/status:
Roadmap / future.

Related docs/ADRs:
- `docs/TIS_MASTER_CONTEXT.md`
- future ADRs required before major AI architecture decisions.

Risks/guardrails:
- AI features must use verified tenant data and preserve privacy, permissions, and subscription boundaries.
