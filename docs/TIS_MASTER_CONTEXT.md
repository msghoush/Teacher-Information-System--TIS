---
title: TIS Master Context
documentation_version: 3.2
last_updated: 2026-08-22
source_of_truth: true
---

# TIS Master Context

## Smart Timetable Customer And Published-Visibility Boundary

Stage 5.2 keeps internal versions but presents Configure → Ready → Generate → Review
→ Regenerate/Delete Working Timetable → Publish. One newest mutable non-active
version is the Working Timetable; technical selection, comparison, historical
exports, and archive actions live in Timetable History.

Publishing remains the atomic exact-scope active-pointer swap. Deleting a working
timetable archives it without deleting placements, snapshots, runs, or published
history. Official non-management reads use `timetable_visibility_service.py`, which
accepts only `TimetableActiveVersion`. Teacher identity follows the existing scoped
`User.user_id == Teacher.teacher_id` convention.

## Smart Timetable Generation Authority

Stage 5.1 makes Planning-resolved section/subject/teacher demand, including
subject-specific Grades 1-2 HRT fallback, the only lesson authority for automatic
generation. Schema-v3 snapshots freeze exact SchoolGroup/Branch/Academic-Year
scope, canonical composed teaching slots, demands, locks, source revision and
regeneration arrangement. OR-Tools is worker-only; web processes enqueue and poll.

Hard-valid candidates must pass an independent validator and a current-input check
before atomic persistence as unpublished generated/regenerated publication-ready
versions. Generation never changes `TimetableActiveVersion`. Regeneration preserves
locks and requires a calculated minimum difference; random seed alone is not
diversity authority. Publishing remains a separate permission and transaction.

## Capacity-Based Commercial Packaging

ADR 0025 establishes one normal customer feature baseline for coherent active
paid, promo, and customer-demo workspaces. Starter, Professional, and Enterprise
AI differ by organization capacity and billing context, not by ordinary product
modules. Their established 1/5/25, 5/20/100, and 25/100/500 branch/staff/teacher
ceilings remain unchanged; Custom remains contact-only above Enterprise.

Commercial source and lifecycle decide whether the workspace may operate.
Permissions and tenant/branch/academic-year scope decide what a user may do.
Normal feature policy is resolved centrally, and branch entitlement is required
for branch-scoped actions. Platform, Developer, System Owner, global audit,
promo-admin, and demo-admin capabilities are excluded. AI availability uses the
common baseline, while AI consumption uses a separate policy boundary and the
existing durable accounting model.

## Stage 5 SchoolGroup Management Boundary

Top-level SchoolGroup creation and deletion from operational configuration are
platform-global actions, not tenant administration. Each requires Platform identity,
`schools.manage_all_schools`, and the matching create/delete permission. Tenant
Administrators no longer receive those permissions by default, and stale permission
state cannot bypass the identity guard. Tenant SchoolGroup updates remain available
only for the user's linked SchoolGroup; foreign IDs fail before mutation.

School Management consumes the unified commercial authority facade for branch
capacity presentation. Promo and paid tenants therefore see authoritative used,
allowed, and remaining branch capacity while branch mutations retain the existing
locked, source-aware enforcement and atomic promo evidence. A read-only PostgreSQL
provenance audit can identify active internal sandboxes with missing tenant-link and
workspace-entitlement evidence for Platform Owner review; it performs no repair.

## Controlled Existing Workspace Conversion Boundary

M4B is the only supported bridge from an audited internal sandbox to a customer
workspace awaiting commercial activation. A durable operation binds the exact
SchoolGroup identity, normalized intended owner, approved M4A evidence hash,
canonical parameters, branch/dependency snapshot, sandbox entitlement snapshot,
required setup fields, actors, lifecycle stage, and idempotency key. Conversion
events are append-only and redacted. A partial unique database index permits at
most one active `tenant_owner` account link per SchoolGroup; migration stops for
manual review if legacy duplicates exist.

The operation is also the ownership claim. It does not fabricate an account or
password. The intended owner must use ordinary registration and verification,
then explicitly claim the workspace. Alignment rejects duplicate, suspended,
unverified, platform, or cross-tenant identities and reuses an existing same-
tenant operational User when safe. An existing different owner requires a
separate Platform Owner transfer approval.

Only legal organization name, IANA timezone, and educational program are
collected. Final execution locks and revalidates the operation and workspace,
performs a fresh M4A audit, rejects branch or commercial drift, retires the one
active internal-sandbox entitlement, and transitions to `customer / provisioning`
without creating a replacement entitlement or TenantProvisioningLink. M1 calls
that state `activation_required`; Organization Account remains available while
operational access fails closed. M3 promo activation is available. Paddle
activation for an already existing workspace is a deferred milestone and must
not be inferred from normal new-onboarding checkout support.

## Existing Workspace Conversion Audit Boundary

Before a legacy internal sandbox may enter any controlled customer conversion,
M4A requires an explicit read-only audit keyed by SchoolGroup ID, workspace
UUID, exact organization name, and normalized intended-owner email. The audit
reflects the deployed schema, traverses branch foreign-key descendants,
identifies unconstrained branch references, and inventories ownership,
provisioning, entitlement, subscription, demo, and promo evidence. It emits
counts and allowlisted metadata only; provider identifiers are reduced to
presence flags and secrets or private payloads are never included.

`scripts/audit_existing_workspace_conversion.py` runs only on PostgreSQL in a
repeatable-read, read-only transaction and always rolls back. Deterministic
JSON and text formats expose the observed transaction mode, a stable SHA-256
snapshot, conservative archival candidates, and explicit exit codes: `0`
coherent, `1` execution/configuration failure, `2` manual review, and `3`
workspace identity mismatch. Soft-deleted rows still count as dependencies;
an unmodeled branch foreign key blocks archival recommendations. Its result is
evidence for a later design decision, not conversion authority. It cannot
archive a branch, align an owner, change workspace metadata, create a tenant or
commercial source, call Paddle, send email, approve deletion, or perform the
future conversion. Any identity conflict, commercial conflict, incomplete
schema coverage, or uncertain relationship requires manual review.

## Promo Redemption And Activation Authority

Promo access is an explicit third customer commercial source beside paid
subscription and customer demo. A verified organization owner may redeem an
active, approved, in-window definition from completed onboarding or from an
existing workspace that a separate controlled process already classified as
`customer`, left in `provisioning`, linked to that owner, and left without any
commercial source. Active internal sandboxes are never converted implicitly.

Final activation locks the activation session, promo definition, and target
workspace; revalidates scope, limits, source compatibility, people usage, and
branch selection; then creates immutable redemption/grant evidence, explicit
branch access, a promo workspace entitlement, and the promo tenant link in one
commit. Exactly one tenant-link source is required: `SubscriptionContract`,
`SaaSDemoRequest`, or `PromoGrant`. Pending activation gives no access and
Paddle is not involved.

Branch selection is the only reversible capacity selection in M3. Existing
branches above the grant require exactly the allowed count; fewer branches are
all selected and unused capacity remains available for normal future branch
creation. The final entitlement inventory covers every preserved branch: selected
branches have an assignment and active entitlement; unselected active or inactive
branches have an explicit inactive entitlement. Operational status is unchanged.
Individual and bulk reactivation acquire the workspace lock, enforce grant capacity,
and update status, assignment, and entitlement atomically. The dry-run-first
`reconcile_promo_branch_entitlements.py` command may add only missing inactive
evidence for a coherent active promo source and otherwise fails closed. Staff and
teachers are never modified. Any organization-wide excess blocks activation until
the owner changes operational usage and resumes.

Billing & Subscription is source-aware after organization selection and permission
validation. Paid workspaces retain the existing Paddle subscription portal; demo
workspaces retain their dedicated demo journey; promo workspaces render a dedicated
Commercial Access page. Promo presentation composes M1 authority for plan,
status, capacity usage, and remaining capacity with the attributable grant/redemption
for effective dates and a masked reference. Normal operational access ends exactly at
the grant's `effective_to`; grace days provide only a customer recovery window and do
not extend access.

Expired and recovery-period promo owners may continue through the existing-workspace
paid plan and Paddle checkout path. Promo remains the sole authority while checkout
is pending, failed, abandoned, or unconfirmed. A verified completed transaction locks
and revalidates the existing tenant and atomically replaces promo source evidence with
paid contract, subscription, workspace entitlement, and branch entitlement evidence.
The SchoolGroup, workspace UUID, branches, users, teachers, academic data, branding,
ownership, and immutable promo records are retained. Active-promo early conversion is
not supported. Shared commercial badges are generated from centralized authority for
Organization Account and full commercial presentation. The normal operational shell
does not expose commercial source, plan, or lifecycle identity.

## Promo Definition And Governance Boundary

Platform Console now manages definition-only promo offers for the three active
self-service plan tiers. A definition selects exact positive capacity within
the existing plan ceilings, a controlled scope, validity and one access-expiry
policy, redemption-policy metadata, and optional eligible existing branches.
Draft, Active, Paused, and Revoked are persisted; Expired is derived. Active
material edits require pause and return the versioned definition to Draft.

Raw promo codes are generated by TIS, shown once, and never persisted. Lookup
authority is a deterministic HMAC-SHA256 hash under a dedicated secret and key
identifier. Platform permission and owner-approval rules are separate from
tenant permissions and capacity. M3 consumes only an approved active
definition through the separate locked redemption path; M2 definition actions
still do not grant access or call Paddle.

## Organization Account Sign-In Boundary

Public SaaS Sign In resolves an activated organization owner or authorized
account manager to `/saas/account`, the Organization Account Overview, rather
than directly to the operational workspace. The overview separates organization
profile, branch visibility, billing/subscription, and account security by the
linked operational user's existing permissions. Enter TIS Platform is the only
customer-account action that enters `/login`, and operational commercial-access
and authorization checks still apply there. Restricted account managers retain
safe account and billing recovery access without operational entry; incomplete
accounts resume onboarding; non-management users retain their approved
role-based destination; and multi-organization accounts select an organization
before its overview is shown. That selection is an HTTP-only UUID hint that is
accepted only after revalidation against the current account links and existing
permissions; it cannot grant cross-tenant access.

## Customer Journey Continuity

TIS treats demo or subscription expiry as an expected commercial state.
Returning routing is derived from SaaS onboarding, request, durable workspace
link, lifecycle, and subscription records. Expired access is intercepted before
protected workspace services and shown with plan, renewal, support, and
sign-out actions. Expired-demo checkout quotes the preserved workspace's active
branches and must never create another organization or SchoolGroup.
Customer-visible language uses “TIS team” or “TIS support team”; Platform Owner
remains an internal role.

## M8B9 Demo Operations, Notifications, And Testing

Customer Demo operations are generic and Platform Owner-only. Immediate expiry
is reversible; reactivation and custom expiry reuse the same workspace and
require a future date with no maximum. Manual reminders are limited to the
final organization-calendar day, and manual lifecycle runs call the production
M8B7 processor. Standard preserves M8B8 usage, Full remains permission/expiry
bound, and Custom supports registry-controlled workspace and branch policy.

## M8B8 AI Entitlements And Commercial Foundation

AI access resolves centrally after tenant scope and `ai.use` permission.
Commercial state remains authoritative: active Internal Sandbox is unlimited,
active Customer Demo receives its configured successful-use allowance per
registered feature, and expired/restricted demos fail closed. Enabled AI
availability uses the common customer `module.ai` baseline for paid, promo, and
active demo authority; globally disabled definitions remain denied. Usage is
durable, auditable, idempotent by operation key, concurrency-safe, and
separated into internal, demo, promo, and paid metric contexts. Availability
and consumption policy are independent. No executable AI tool
or M8B9 owner override/reset operation exists.

## M8B7 Demo Customer Journey

M8B7 projects customer Pending, Active, Expired, and Declined presentation from the existing request, provisioning, and lifecycle sources. Approval invokes the separate retryable provisioning service and creates activation communications only after success. Six email types use the existing branded provider through a durable deduplicated outbox; demo events reuse the Platform Owner Notification Center. The shared tenant shell shows active demo status. A coherent expired demo may convert after authoritative confirmed payment by reactivating and relinking the same SchoolGroup and preserving its UUID and all tenant data. Sandbox, checkout-return, and unverified evidence remain non-authoritative.

Documentation version: 3.0

Last major context update: 2026-06-27

## Product Identity

TIS stands for Teacher Information System. It is a developing SaaS academic operations platform for schools, school groups, academic leaders, supervisors, and platform owners who need one trusted place for academic staffing, teacher records, planning, calendars, observations, branch context, and future intelligence.

TIS is not only a teacher directory. It is intended to become the operational backbone for academic decision-making across a school or multi-branch organization.

Public product presence:

- Public website: `https://tisplatform.com`
- Application portal: `https://app.tisplatform.com`
- Operational login: `/login`
- SaaS signup: `/saas/signup`
- SaaS login: `/saas/login`
- SaaS account area: `/saas/account`

## Product Vision

TIS helps schools move away from scattered spreadsheets and disconnected operational files. The product vision is to give academic leaders a structured, secure, and tenant-isolated platform where teacher information, teaching loads, staffing needs, observations, calendars, and branch-level context can be managed together.

As the platform matures, TIS should also become the trusted data foundation for AI-assisted academic operations. Future AI features should depend on verified school data, clear permissions, and careful subscription packaging.

## Business Goal

The business goal is to establish TIS as a subscription-based SaaS platform for academic operations. The platform should support school onboarding, plan selection, payment, provisioning, account management, and scalable multi-tenant usage.

Near-term business priorities:

- Convert interested schools from public landing page traffic into SaaS accounts.
- Support clear onboarding from signup through school setup.
- Provide reliable billing and payment status visibility.
- Enable platform owners to manage pending organizations and provisioning.
- Preserve trust by keeping tenant data isolated and operational flows stable.

## Educational Goal

The educational goal is to reduce administrative friction so schools can make better academic decisions. TIS should help leadership teams identify staffing gaps, workload problems, incomplete academic coverage, observation follow-up needs, and calendar conflicts earlier.

The platform should support educational quality by making academic operations easier to see, review, and improve.

## Target Customers

Primary customers:

- Private schools
- Multi-branch school groups
- Academic leadership teams
- Principals and vice principals
- Department heads and supervisors
- School operations and HR-adjacent academic staff

Internal platform users:

- Platform Owner
- Platform Co-Owner
- Platform Developer

Tenant users:

- Administrators
- Coordinators
- Supervisors
- Teachers and academic staff, depending on enabled workflows

## FastAPI App Architecture

The operational TIS application is a FastAPI application at the repository root. It uses Python, SQLAlchemy, Jinja templates, static assets, and modular routers.

Core app areas:

- `main.py`: primary FastAPI app, route registration, app-level workflows, startup checks, platform console routes, dashboard and configuration flows.
- `models.py`: main SQLAlchemy models.
- `database.py`: database connection/session setup.
- `db_migrations.py`: local schema migration and repair logic.
- `auth.py`: authentication, role normalization, platform identity helpers, permission helpers, session handling.
- `authorization.py`: route permission rules and access-denied response helpers.
- `permission_registry.py`: permission groups, labels, defaults, developer-assignable permissions, and system owner permissions.
- `role_permission_service.py`: role permission persistence and related helpers.
- `ui_shell.py`: shared application shell context, navigation, visual identity, and page metadata.
- `routers/`: modular feature routers for users, teachers, subjects, planning, timetable, academic calendar, and observations.
- `templates/`: Jinja templates for the operational app and SaaS app pages.
- `static/`: CSS, JavaScript, images, branding assets, and generated public artifacts.
- `tests/`: pytest coverage for tenant isolation, SaaS phases, platform access, permissions, email, branding, and related workflows.

Important operational route families:

- `/login`: operational app login.
- `/dashboard`: tenant operational dashboard.
- `/platform`: platform console for platform identities.
- `/system-configuration`: branch, year, branding, role permissions, and configuration workflows.
- `/teachers`, `/subjects`, `/planning`, `/timetable`, `/academic-calendar`, `/observations`: core academic operations.

## Next.js Landing Architecture

The public marketing website lives in `tis-landing-website/`. It is separate from the FastAPI operational portal.

Landing architecture:

- Runtime: Next.js / Node.
- Public website domain: `https://tisplatform.com`.
- Local development URL: `http://localhost:3000`.
- Main page: `tis-landing-website/src/app/page.tsx`.
- App layout: `tis-landing-website/src/app/layout.tsx`.
- Global styles: `tis-landing-website/src/app/globals.css`.
- Logo component: `tis-landing-website/src/components/tis-logo.tsx`.
- Public assets: `tis-landing-website/public/`.
- M8 landing integration uses `NEXT_PUBLIC_TIS_APP_BASE_URL` as the configurable deployed application base URL. Public Open Account CTAs build one shared registration destination at `/saas/signup`.
- The hero Subscribe Now action scrolls to `#pricing`. Starter, Professional, and Enterprise AI enter public signup with an allowlisted preferred-plan code. The preference creates no plan, checkout, payment, or Paddle record and is applied only after existing branch, system-user, and teacher capacity validation. Custom remains contact-only.

The application portal remains separate:

- App domain: `https://app.tisplatform.com`.
- Runtime: FastAPI / Python with a relational database.

Legacy landing files in the FastAPI app are not the source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

Those legacy files must not be modified unless explicitly approved.

## Multi-Tenant SaaS Strategy

TIS is designed as a multi-tenant SaaS platform. Tenant isolation is a critical rule. School groups, branches, users, academic years, teachers, planning data, timetable data, observations, and configuration records must remain scoped to the correct organization and branch context.

The platform distinguishes between:

- Platform identities: platform owners, co-owners, and developers.
- Tenant identities: users belonging to a school group and branch context.
- SaaS account identities: accounts that move through signup, onboarding, billing, and provisioning.

Platform users may inspect or switch organization context through controlled platform workflows. Tenant users must remain inside their authorized school, branch, academic year, and permission scope.

Critical tenant strategy:

- Do not weaken tenant isolation.
- Do not bypass permission checks.
- Do not assume a platform identity is a tenant identity.
- Do not assume a SaaS account is already provisioned into an operational tenant.
- Keep onboarding, billing, and tenant provisioning as distinct stages.

### Workspace Classification Foundation

M8B-1 introduces a metadata boundary between workspace identity, workspace classification, and operational tenant state:

- `SchoolGroup.workspace_uuid` is the stable unique workspace identifier.
- `SchoolGroup.workspace_classification` accepts only `internal_sandbox`, `customer_demo`, or `customer_paid`.
- `SchoolGroup.workspace_lifecycle_status` accepts only `provisioning`, `active`, `suspended`, or `archived`.
- `PendingOrganization.workspace_intent` carries pre-provisioning intent.
- `SaaSAccount.account_purpose` distinguishes internal-test and customer account purpose.
- `User.is_internal_test_identity` identifies operational identities attributable to internal test data.

The M8B-1 fields are not authorization, entitlement, payment, or reset gates. Existing flows continue unchanged. Classification conversion is rejected except for the dedicated M8B-6 Customer Demo to Customer Paid service, and the commercial-state service remains the authority for the effective commercial result. Every pre-M8B-1 workspace/onboarding record is confirmed test data and is assigned internal sandbox/test metadata by the controlled one-time backfill. No code may infer customer-paid status from Paddle or onboarding fields outside the approved conversion and commercial-resolution boundaries.

M8B-2 implements that commercial resolver as a read-only foundation. Workspace entitlements are separate from classification and lifecycle, and branch commercial activity is separate from operational `Branch.status`. The resolver recognizes provisioning, active internal sandbox, active customer demo, active customer paid, inactive, suspended, archived, and manual-review outcomes. It does not implement demo expiration or authorization enforcement.

Paid workspace resolution delegates plan capabilities and paid branch quantity to the existing M7 entitlement resolver and requires a matching persisted `PaymentSubscription`. Demo and internal entitlements use explicit workspace values tied to the shared `EntitlementDefinition` catalog. Branches inherit their workspace entitlement unless an optional coherent `BranchEntitlement` says active or inactive. All calculations are read-only and fail closed on ambiguity or tenant mismatch.

M1 adds one operational facade over these existing authorities. Paid capacity
uses confirmed `PaymentSubscription.quantity` capped by the plan branch ceiling,
plus plan staff and teacher limits. Staff is every distinct active tenant
operational User in the SchoolGroup, including an operational owner and
teacher-position user; platform and account-only identities are excluded.
Teacher people deduplicate by normalized `Teacher.teacher_id`, while each blank
legacy identity counts separately. A person represented in both models consumes
one staff slot and one teacher slot. Demo and Internal Sandbox are explicitly
unmetered in M1 only when their existing lifecycle/access authority resolves.

Every operational capacity increase locks the SchoolGroup, resolves authority,
recounts, evaluates the final proposed totals, writes, and commits in one
transaction. Branch create/reactivation/bulk status, operational user
create/reactivation, teacher create/year-copy, academic-year switching, and
paid/demo provisioning final validation use this boundary. Existing
over-capacity records and access are preserved, but an exceeded dimension
cannot grow further. M1 adds no commercial-state persistence, schema,
migration, Paddle, pricing, webhook, onboarding-transition, permission, or
feature-packaging change.

M8B-3 introduces a separate SaaS demo-request aggregate after onboarding review. The public landing website enters signup with either a Request a Demo or Subscribe Now intent; the valid intent persists through account and School Workspace Setup and is emphasized, but never locked, at the commercial-choice page. A self-service pricing card may also supply an allowlisted preferred-plan code. That preference is not a plan selection and cannot create checkout or bypass the existing branch, system-user, and teacher capacity checks; invalid or ineligible preferences are discarded before the customer selects a plan. Subscribe Now preserves the existing plan-selection and Paddle path. Request Demo captures immutable commercial/classification/entitlement context and starts in Pending Review without creating an operational workspace.

Customer Demo eligibility is keyed by a normalized organization domain. TIS prefers the pending organization's authoritative domain, uses a work email domain only when no organization identity exists, and requires an official website/domain for public email providers. A unique domain-eligibility reservation prevents concurrent or historical duplicate Customer Demo opportunities. The reservation remains after request review, activation, expiry, cancellation, rejection, or Demo-to-Paid conversion; Internal Sandbox history is excluded. The only exception is the separately guarded Platform Owner test workspace/account clean-room reset, which atomically deletes the selected test organization's linked demo-commercial records and reservation so internal M8 testing can begin again; it never changes customer reset or demo rules.

Only Platform Owners can approve, reject, or cancel requests. Approval creates a review record but does not provision or activate a demo. Rejection requires a reason, and customers may withdraw only while review is pending. Durable request events serve both audit and internal-notification purposes; email delivery remains out of scope.

M8B-4 consumes an approved request through a separate demo-provisioning aggregate. Provisioning reuses the shared operational workspace builder but creates a customer-demo SchoolGroup and explicit demo entitlement without a Paddle object, payment subscription, or subscription contract. `TenantProvisioningLink` accepts exactly one commercial source: a paid `SubscriptionContract`, an approved `SaaSDemoRequest`, or an immutable `PromoGrant`.

The workspace, entitlement, tenant link, request linkage, and activation transition are atomic. Failure rolls back those records while preserving the approved request and a retryable provisioning failure record. Success activates the customer-demo workspace and entitlement, records activation metadata and internal audit events, and prevents a second provisioning attempt. Platform Owners see detailed provisioning outcomes; customers see only Approved, Provisioning In Progress, Demo Active, or a safe support state.

M8B-5 makes the M8B-4 activation timestamp the only demo clock authority. The resolver derives Day 6 and Day 7 boundaries, validates persisted lifecycle metadata, converts values to the organization's timezone only for display, and fails closed on inconsistent ownership, entitlement, timestamps, or timezone.

The idempotent lifecycle processor creates internal reminder notifications on Day 6 and atomically expires demos at Day 7. Expiration ends the demo entitlement, suspends the SchoolGroup, marks the demo tenant link expired, updates the commercial snapshot to suspended, and preserves every operational row. The operational request middleware enforces the resolver for customer-demo tenant users on every request, so an existing authenticated session cannot bypass expiration. Web users receive the preserved-data/subscription page; API and download requests receive a safe 403. Platform administration, paid tenants, and internal sandboxes bypass this demo-only gate.

M8B-6 permits one commercial classification transition: an active, valid Customer Demo may become Customer Paid after a provider-confirmed M7 subscription exists for the same pending organization. The existing paid checkout and webhook remain authoritative; no local conversion occurs from page state, onboarding selection, or an unconfirmed payment attempt.

The dedicated conversion service locks and validates the demo request, provisioning record, SchoolGroup, demo entitlement, tenant link, contract, and payment subscription. One atomic transaction ends the demo entitlement, creates the subscription-backed paid entitlement, relinks branch entitlement rows, switches the tenant link from the preserved demo reference to the confirmed contract, and changes the existing SchoolGroup classification. The same workspace UUID, tenant row, organization, branches, users, permissions, academic data, and audit history remain in place.

The Platform Owner-only internal test-workspace reset is a separate controlled cleanup flow. Its dependency order removes the selected pending organization's linked demo request, domain eligibility reservation, review/event history, provisioning/lifecycle records, and conversion records before their commercial and workspace parents. A detached domain reservation is eligible for clean-room removal only after the reset uses the shared customer-demo domain resolver and confirms that no other pending organization, demo request, tenant workspace, or customer account independently uses the domain and that the reservation is not already marked as historically ambiguous; any conflict or historical ambiguity blocks the reset for manual review. Analysis produces an explicit safe detached-reservation ID list. Deletion uses only those IDs, flushes their removal before demo requests or parent records, and verifies inside the transaction that no selected ID remains; an ID mismatch or failed verification aborts the reset. It also removes `subscription_change_requests` scoped to the selected `SchoolGroup` before scoped operational `User` rows, then removes selected `WorkspaceEntitlementValue` and `BranchEntitlement` children before the selected `WorkspaceEntitlement` and final `SchoolGroup`. This permits a clean internal M8 retest using the same email and organization domain without touching global plan, price, entitlement-definition, Paddle, platform, or other-organization records. The existing validation gates, owner access, one-transaction commit/rollback behavior, and production one-demo-per-domain customer policy remain unchanged.

The separate Platform Owner demo-eligibility maintenance area handles historical detached reservations that no longer have an organization/account target for clean-room reset. `/saas-admin/demo-eligibility-maintenance` performs a read-only scan and marks a row removable only when its exact domain has no matching organization, SaaS account, demo request, tenant-profile workspace, provisioning record, subscription evidence, Demo-to-Paid conversion, or manual-review marker. Deletion requires typed-ID and checkbox confirmation, locks and rechecks the exact row, deletes by eligibility primary key only, flushes, verifies zero remaining rows for that ID, and commits atomically. Blockers preserve the row and rollback. Successful maintenance writes a durable owner audit event. This path never deletes by domain and does not weaken the one-demo-per-domain rule.

The existing M7 subscription resolver, workspace-entitlement resolver, and commercial-state resolver verify the post-conversion result before commit. Failure rolls back every workspace mutation while preserving provider-confirmed subscription records and a retryable failure history. Completed conversions are excluded from demo reminder/expiration processing. Expired, suspended, ambiguous, cross-tenant, internal-sandbox, paid, or already-converted workspaces fail closed.

## SaaS Routes And Account Experience

Core SaaS routes:

- `/saas/signup`: public SaaS account creation.
- `/saas/login`: SaaS account login.
- `/saas/account`: SaaS account dashboard.

Related SaaS areas include plan selection, onboarding organization details, contacts, branch setup, academic setup, onboarding review, billing status, checkout summary, checkout return, checkout cancel, sessions, security, and profile pages.

Platform owner SaaS administration exists under `/saas-admin` for pending organizations, demo-request review, payments, and provisioning workflows.

The Platform Owner pending queue is an operational work queue, not a list of every `PendingOrganization` row. It includes draft/setup, review, checkout/payment, and incomplete or recoverable provisioning states only while no completed tenant link, completed provisioning job, or final tenant billing state exists. Confirmed active tenants and retained rejected/completed records remain available under Organization Records. When completed provisioning evidence conflicts with payment, subscription, contract, tenant, or SchoolGroup evidence, the owner lifecycle resolver labels the record Lifecycle Review Required and fails closed instead of presenting it as ordinary pending work. Raw onboarding status remains historical and does not override confirmed operational truth.

### TIS Account Email Verification Recovery

The accepted Phase 1 verification recovery improvement strengthens the public TIS Account setup journey without changing payment, billing, provisioning, tenant activation, database schema, migrations, operational modules, or the landing website.

Current verification behavior:

- Valid email verification links mark the account email verified/active and redirect to `/saas/login` with a professional success notice: the customer is told their email has been verified and asked to sign in to continue school workspace setup.
- `/saas/login` is the GET sign-in page and its form submits only by POST to `/saas/auth/login`. Fresh verified accounts with no organization record continue to the GET `/saas/account` dashboard; the existing explicit onboarding-start action remains POST-only.
- Login continuation values are limited to known customer GET destinations. POST-only, malformed, traversal, fragment, and external values fall back to Account Setup. Defensive GET navigation to `/saas/auth/login` redirects to `/saas/login` and never exposes raw FastAPI 405 JSON.
- Expired or invalid verification links show a recovery page instead of a dead-end generic error.
- The recovery page includes a resend verification form.
- Resend verification safely handles unverified accounts, already verified accounts, and unknown email addresses without exposing whether an account exists.
- Password-based accounts that are still pending verification cannot start or continue school workspace setup.
- New customer-facing verification language in this flow uses "TIS Account" and "school workspace setup".

Google and Microsoft sign-in remain future work. OAuth-based verification bypass rules should not be expanded without a separate approved identity decision.

### TIS Account Customer-Facing Wording And Branding

The accepted Phase 2 customer-facing wording cleanup improves the public TIS Account and school workspace setup experience without renaming internal `/saas` routes, modules, models, or stored statuses.

Customer-visible account/setup pages should use professional labels including:

- TIS Account
- Account Setup
- Account Dashboard
- School Workspace Setup
- Organization Profile
- Branch Setup
- Academic Setup
- Subscription Setup
- Secure Payment
- Workspace Activation

Customer pages should not expose "SaaS" as product copy, raw database statuses, tenant/provisioning terminology, provider transaction/subscription identifiers, attempt UUIDs, checkout session internals, plan IDs, or school group IDs. Those internal concepts may remain in backend code, admin views, stored data, tests, and documentation where they describe architecture or platform-owner operations.

The shared customer account shell includes the official full-color horizontal TIS logo on the light account background. Transactional TIS Account emails use an existing official dark-blue TIS wordmark URL. This Phase 2 cleanup did not change payment, billing, provisioning behavior, tenant activation behavior, database schema, migrations, operational modules, or the Next.js landing website. Google/Microsoft login remains future work.

### TIS Account Guided Setup Framework

The accepted Phase 3A implementation introduces the shared customer setup framework for the TIS Account dashboard only. The account page now behaves like a guided onboarding console rather than a dense admin dashboard.

For a verified account that has not created a pending organization, the
initial Account Setup view uses a compact variant: a smaller official logo,
one "Start Your School Workspace Setup" title, one supporting sentence, one
POST action to `/saas/onboarding/start`, and the existing eight-step journey.
Duplicate status, next-action, account/workspace, and guidance panels are
omitted in this initial state. Later setup states retain their existing
contextual console.

The shared framework provides:

- Official TIS logo/header.
- An 8-step customer journey stepper.
- Current step and status banner.
- One primary next action.
- Main content area.
- Help/guidance area.
- Clear messaging that TIS Platform access becomes available after Workspace Activation.

The journey steps are TIS Account, Email Verification, School Workspace Setup, Review & Confirmation, Subscription Selection, Secure Payment, Workspace Activation, and Enter TIS Platform. Step state is derived from existing account, pending organization, onboarding progress, billing, payment, and activation data. Internal route names, stored statuses, billing/payment/provisioning behavior, database schema, migrations, operational modules, the landing website, and OAuth behavior remain unchanged.

Phase 3B applies this shared framework to the five School Workspace Setup onboarding pages: Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup. These pages now use a consistent guided wizard structure with grouped sections, one shared-shell primary CTA, secondary Back/Save Draft actions, concise guidance, and reduced visual clutter.

The Phase 3B onboarding redesign preserves existing form actions, field names, validation behavior, draft behavior, route names, and onboarding state transitions. Subscription/payment/status pages remain future Phase 3 work.

Organization Profile program input is a required controlled selector whose
National, International, and Both labels normalize to the existing uppercase
stored codes. Invalid values render inline without creating another pending
organization. Pending logo uploads are decoded as PNG/JPG/WEBP, limited to
4 MB, checked for minimum dimensions, written under an opaque UUID filename,
and promoted atomically. Empty upload retains the current logo. Replacement
commits the new relative path before safely removing the obsolete pending
file; rollback removes the newly written file and retains the old database
reference. Storage failures are logged with traceback and rendered as
customer-safe page errors.

Pending logo storage remains
`static/uploads/saas/pending_logos` on the application filesystem. Only the
relative path is persisted. An ephemeral Render filesystem is unsuitable for
durable customer branding across restarts or deploys unless a persistent disk
is explicitly mounted. Object storage or persistent disk adoption is a
separate owner-approved architecture and deployment decision.

Organization Profile and the shared School Workspace setup header render the
saved pending logo with contain sizing, organization-name alt text, and a
neutral no-logo/unavailable placeholder. The official TIS logo remains the
separate platform identity. The pending relative path remains authoritative
through checkout. Both paid and demo activation use
`provisioning_service.create_workspace_records()`, which validates the pending
file again and copies it to the primary `SchoolGroupLogo` slot under the
established organization-owned branding directory. `SchoolGroup` has no logo
column; `SchoolGroupLogo` is the final branding authority. The operational
shell and branding settings already consume that record through the protected
organization-asset route. Missing source files now block activation rather
than silently dropping the logo.

Branch Setup capacity summaries are computed in Python with nullable or
incomplete estimate values normalized to zero for display. HTML and server
save validation still require explicit non-negative whole numbers for system
users and teachers on every active branch. Newly created branch rows receive
explicit zero defaults. No schema change is required because current columns
already have non-null zero defaults.

Phase 3C applies the same guided framework to Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages. These pages use one shared-shell primary CTA, customer-safe status labels, concise supporting cards, and explicit messaging that browser return from checkout does not itself confirm payment and that TIS Platform access becomes available after Workspace Activation.

The Phase 3C redesign preserves payment behavior, billing behavior, provisioning behavior, webhook logic, checkout start/launch behavior, stored statuses, route names, database schema, migrations, operational modules, the landing website, OAuth behavior, and admin views.

## M1-M5 Completed Milestone Summary

M1: Identity and SaaS foundation

- Established core SaaS account concepts.
- Added initial signup/login/account flows.
- Clarified separation between platform, tenant, and SaaS account identities.
- Added supporting tests for identity and SaaS phase behavior.

M2: Onboarding foundation

- Added structured onboarding stages for organization information, contacts, branches, academic setup, and review.
- Improved the path from SaaS signup toward a provisionable organization.
- Preserved the distinction between pending SaaS organizations and operational tenants.

M3: Billing and plan foundation

- Added pricing, plan catalog, billing status, checkout summary, return, and cancel flows.
- Created billing/payment service modules to keep payment logic separate from operational academic logic.
- Prepared the platform for subscription-based SaaS packaging.

M4: Provisioning foundation

- Added pending organization and provisioning workflows for platform owners.
- Added provisioning queue concepts and retry/run operations.
- Created a controlled path for turning a pending SaaS organization into an operational school context.

M5: Platform access, permissions, and owner controls

- Strengthened platform identity handling.
- Added platform owner/developer concepts and owner management controls.
- Improved permission boundaries for platform and tenant users.
- Added tests around platform access and role permissions.

### M7: Subscription Management And Entitlements

- Added normalized entitlement definitions and plan entitlement values resolved from one confirmed active provider subscription.
- Added a customer Subscription Management portal with lifecycle state and centrally controlled allowed actions.
- Added paid branch-quantity increases and scheduled reductions with operational branch-capacity enforcement.
- Added plan upgrades and scheduled downgrades using Paddle-authoritative previews and proration behavior.
- Added scheduled cancellation and reversal while preserving paid access through the confirmed effective period.
- Added provider-sourced billing history and protected, freshly resolved invoice downloads.
- Added an explicit organization-owned billing profile for the confirmed billing email, legal/billing identity, contact, optional registration/tax identifiers, and supported address fields. Login email and billing email are independent authorities.
- Mapped Paddle customers now retain `provider_address_id` and `provider_business_id`. Authorized billing changes synchronize the existing customer, reuse or update one attributable active Paddle Business, update the active subscription identity, and attach the business to future initial transactions. Historical invoices are not rewritten automatically.
- Billing Contact is read-only by default and uses an explicit edit interaction. Local profile changes survive provider failure; a permission- and tenant-scoped retry reuses persisted Paddle mappings, is idempotent after success, and records safe step-level provider diagnostics. A saved pending or failed billing identity blocks new plan and quantity mutations until synchronized, without blocking cancellation or changing legacy active subscriptions that have no saved profile.
- Paddle `paid` and `completed` remain separate lifecycle evidence: paid is customer-visible payment receipt while provider processing continues; completed remains required for final reconciliation.
- Added webhook idempotency, strict provider/local relationship validation, manual-review fail-closed paths, diagnostics, and guarded reconciliation tooling.
- Unified active subscription capacity review and operational enforcement across branches, tenant operational staff users, and teachers. Required upgrades use the highest capacity dimension, Paddle quantity remains branch-only, and scheduled downgrades/reductions revalidate capacity at their effective boundary.
- Subscription presentation separates paid branch quantity from the plan's maximum branch ceiling; unused ceiling is never described as prepaid capacity. The approved common customer feature baseline keeps plan comparison focused on identity, capacity, eligibility, and actions rather than a feature ladder.
- Linked operational organization owners and billing-authorized account managers can enter the existing Organization Account subscription page from System Configuration. Tenant/account linkage is revalidated and only an allowlisted internal billing continuation survives SaaS authentication. The public landing customer entry is labelled Organization Sign In and targets centralized SaaS login.

## Paddle And Payment Architecture Summary

Existing customer workspaces in `activation_required` can use a separate
SchoolGroup-anchored paid activation flow. It shares Paddle customer/address/business
and transaction infrastructure but does not create PendingOrganization or run tenant
provisioning. Professional and Enterprise AI quote all active operational branches;
Starter remains disabled until complete branch-entitlement enforcement is proven.
The workspace-customer association persists the address and business used for that
SchoolGroup, and a returned or reused Paddle transaction is accepted only after its
complete billed transaction and current-quote lineage are revalidated.
The existing-workspace **Choose a Plan** entry point remains a selection surface
while the current activation is `draft` or `checkout_ready`. Its selected plan is a
default, not commercial authority: another eligible plan may replace it and produce
a fresh authoritative quote without calling Paddle, creating a PaymentAttempt, or
changing branches. `checkout_started`, `payment_processing`, and manual-review or
inconsistent activations are not silently replaced and fail closed against plan
changes. Promo activation and PendingOrganization checkout remain separate flows.
Verified `transaction.completed` evidence atomically establishes the paid contract,
subscription, workspace/branch entitlements, paid tenant link, and active lifecycle.
Classification remains `customer`, and browser return or `transaction.paid` never
grants access.

Account presentation does not infer payment from workspace lifecycle. A
`customer / provisioning` workspace with no current paid-activation attempt displays
Activation required. Payment processing requires a current unexpired attempt in
checkout-started or payment-processing state; failed, cancelled, and expired attempts
use recovery presentation. PendingOrganization and demo status resolution is separate.

The payment architecture is organized under the `saas/` package.

Key modules:

- `saas/pricing_service.py`: plan/pricing behavior.
- `saas/payment_service.py`: payment-related service logic.
- `saas/paddle_client.py`: Paddle integration boundary.
- `saas/billing_service.py`: billing status and related account billing behavior.
- `saas/currency_service.py`: currency-related helpers.
- `saas/router.py`: SaaS and SaaS admin routes.
- `saas/entitlement_service.py`: provider-confirmed paid subscription entitlement authority.
- `saas/commercial_authority_service.py`: unified operational commercial-access and three-dimension capacity authority.
- `saas/subscription_portal_service.py`: customer portal composition.
- `saas/subscription_change_service.py`: quantity change previews, submissions, schedules, and webhook reconciliation.
- `saas/subscription_plan_change_service.py`: plan upgrade/downgrade lifecycle.
- `saas/branch_pricing_quote_service.py`: shared onboarding and operational three-dimension capacity counts, plan eligibility, and minimum-plan resolution.
- `saas/subscription_cancellation_service.py`: cancellation and reversal lifecycle.
- `saas/subscription_lifecycle_service.py`: lifecycle resolver and allowed-action policy.
- `saas/billing_history_service.py`: Paddle transaction history and invoice access.
- `saas/payment_lifecycle_reconciliation_service.py`: guarded repair from attributable authoritative evidence.

Architecture rules:

- Keep Paddle-specific details behind service/client boundaries.
- Do not mix payment logic into academic operations.
- Treat payment status, onboarding status, and provisioning status as related but separate concepts.
- Use platform owner admin views for payment/provisioning oversight.
- Avoid changing live SaaS payment flows unless the task explicitly requires it.
- Keep Paddle credentials and endpoints in environment variables.
- Keep Paddle price mappings environment-specific and store the runtime mapping in `subscription_plan_prices.provider_price_id`.
- Use `scripts/sync_paddle_price_ids.py` with sandbox or production mapping JSON to configure initial checkout price IDs; never hardcode live Paddle IDs in migrations or source.
- If an initial checkout price mapping is missing, fail closed before calling Paddle and show customers a support-oriented Secure Payment message while retaining internal plan/interval/currency diagnostics.
- Paddle transaction checkout uses the public `/saas/payment` launcher as the payment-link page. Set `PADDLE_CHECKOUT_BASE_URL` to `https://app.tisplatform.com/saas/payment`, configure `PADDLE_CLIENT_TOKEN` and `PADDLE_ENVIRONMENT` for Paddle.js, and never expose `PADDLE_API_KEY` to frontend code.
- Paddle is authoritative for prices, previews, proration, transactions, scheduled changes, and invoice documents. TIS stores workflow/audit state but does not invent monetary outcomes.
- Subscription changes send the complete retained recurring item set. Immediate changes prevent provider mutation on payment failure; scheduled changes do not change local entitlements before verified effective evidence.
- Webhooks are signature-verified and idempotent. Ambiguous, mismatched, or incomplete provider evidence fails closed to manual review.

## Tenant Provisioning Summary

Tenant provisioning turns a pending SaaS organization into an operational TIS school context. Provisioning should create or connect the required organization records, branches, users, and initial tenant setup while preserving auditability and data isolation.

Key provisioning concepts:

- Pending organization: SaaS onboarding entity still requiring setup, review, payment, or incomplete/recoverable activation work, with no completed tenant evidence.
- Provisioning job: controlled action to create or update operational tenant structures.
- Platform owner review: human oversight before or during provisioning.
- Retry behavior: failed provisioning work should be recoverable without corrupting tenant data.

Provisioning rules:

- Do not directly create operational tenant data from public signup without the approved provisioning path.
- Keep provisioning idempotent where possible.
- Log or surface errors clearly.
- Do not merge tenant data across school groups.
- Treat active tenant/subscription evidence as authoritative over stale onboarding status in Platform Owner queue presentation.

## Landing Page Strategy

The public landing page exists to explain the product, build trust, capture demand, and route interested schools into SaaS signup or demo request flows.

Source of truth:

- The public website implementation is `tis-landing-website/`.
- Marketing content references live in `docs/marketing/`.

Landing priorities:

- Explain the problem of scattered academic operations.
- Present TIS as a connected academic operations platform.
- Show credible platform capabilities.
- Present Request a Demo and Subscribe Now as the two public conversion pathways.
- Route both paths through environment-configured deployed TIS Account signup URLs with the selected intent.
- Keep the landing page separate from operational app templates.

Landing rule:

- Do not change landing page design, copy, or architecture during operational backend tasks unless explicitly approved.

## Customer Experience Roadmap

Near-term customer experience:

- Clear signup and login path.
- Smooth onboarding for organization, contacts, branches, and academic setup.
- Transparent billing/plan status.
- Clear provisioning status after checkout or owner review.
- Reliable operational login once provisioned.

Medium-term customer experience:

- Better account self-service.
- Clearer subscription lifecycle.
- More guided onboarding and implementation support.
- Improved platform owner visibility into pending organizations and payment status.

Long-term customer experience:

- AI-assisted academic planning and decision support.
- Subscription-gated advanced analytics.
- Intelligent recommendations based on verified tenant data.
- Richer executive visibility across branches and academic years.

## Knowledge Management System

TIS uses a Knowledge Management System (KMS) to preserve source-of-truth documentation, current project state, decision history, module history, and generated snapshots.

KMS source documents:

- `docs/AI_PROJECT_CONTEXT.md`: first-read compact onboarding context for future Codex and ChatGPT conversations.
- `docs/TIS_MASTER_CONTEXT.md`: durable product, architecture, workflow, roadmap, and critical rules.
- `docs/PROJECT_STATE.md`: living project state.
- `docs/DOCUMENTATION_UPDATE_POLICY.md`: mandatory KMS and Knowledge Impact Assessment rules.
- `docs/CHANGE_HISTORY.md`: chronological summary of meaningful changes.
- `docs/adr/`: Architecture Decision Records.
- `docs/history/`: module-specific history.
- `docs/engineering/`: engineering handbook with module map, repository architecture, user/system flows, and developer onboarding.

PDF philosophy:

- Markdown files are the source of truth.
- The PDF booklet is a generated snapshot.
- The PDF must never be edited manually.
- The PDF must be regenerated when included Markdown source docs change.
- The PDF should later be served through owner-only protected routes.

Generated KMS artifacts:

- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Automatic enforcement:

- root `AGENTS.md` defines mandatory Codex KMS behavior,
- `.kms-impact.yml` records the task-level machine-readable KIA,
- `scripts/kms.py sync` validates KIA before writing, regenerates PDF/manifest artifacts, and runs post-generation freshness checks,
- `scripts/kms.py check` provides the single read-only local and CI validation command,
- `scripts/check_kms_impact.py` compares the declaration with changed files and major-change rules,
- `scripts/generate_docs_pdf.py --check` validates source coverage and snapshot freshness without writing,
- GitHub Actions require validation for pull requests, `dev`, and `master` deployment.

Automation never rewrites Markdown. It detects omissions and blocks stale work so reviewed human/AI updates remain authoritative.

Owner-only app access:

- `/platform/knowledge`: read-only Platform Owner Knowledge Center.
- `/platform/knowledge/booklet`: protected inline PDF view.
- `/platform/knowledge/booklet/download`: protected PDF download.

The Knowledge Center is protected by the existing Platform Owner access pattern. It is not public, not a landing page, and does not regenerate or rewrite source docs. Its manifest-backed library presents document titles and summaries, groups sources into Core, Engineering, Decisions, History, Marketing, and Supporting sections, supports client-side category/module/freshness filtering and search, and opens documents at their recorded `pdf_page` through the protected booklet route.

Engineering handbook:

- `docs/engineering/TIS_MODULE_MAP.md` maps product/system modules and guardrails.
- `docs/engineering/REPOSITORY_ARCHITECTURE.md` explains repository ownership and risky files.
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md` documents end-to-end customer, SaaS, payment, provisioning, operational, platform owner, KMS, and developer flows.
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md` explains data areas, ownership boundaries, and tenant isolation rules.
- `docs/engineering/DEVELOPMENT_STANDARDS.md` defines non-negotiable engineering rules.
- `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md` defines design direction for operational, platform, SaaS, Knowledge Center, and landing surfaces.
- `docs/engineering/PRODUCT_ROADMAP.md` records completed, current, next, and future roadmap.
- `docs/engineering/REJECTED_DECISIONS.md` records significant rejected alternatives.
- `docs/engineering/VISUAL_DOCUMENTATION_GUIDE.md` defines future visual documentation standards.
- `docs/engineering/AI_OPTIMIZATION_GUIDE.md` guides future AI assistants.
- `docs/engineering/PROJECT_GOVERNANCE.md` defines ownership, approvals, quality gates, documentation gates, and traceability.
- `docs/engineering/KNOWLEDGE_LIFECYCLE.md` defines documentation, engineering, approval, review, release, and maintenance lifecycle.
- `docs/engineering/DOCUMENTATION_AUTOMATION.md` defines current automation and future automation rules.
- `docs/engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md` formalizes KIA.
- `docs/engineering/SELF_EVOLVING_WORKFLOW.md` defines the official task-to-deployment workflow.
- `docs/engineering/DOCUMENTATION_DEPENDENCY_MAP.md` explains KMS propagation.
- `docs/engineering/AI_CODING_WORKFLOW.md` defines future AI coding discipline.
- `docs/engineering/FUTURE_AUTOMATION_ROADMAP.md` records future automation opportunities.

KMS v1.0 status:

KMS v3.0 Phase 3D completes the KMS v1.0 lifecycle foundation. Future work should improve automation, search, visuals, route inventories, test strategy docs, deployment runbooks, and deeper module guides only through approved phases.

## Development Workflow

Default workflow for approved implementation tasks:

1. Inspect the relevant code and docs before editing.
2. Keep changes scoped to the approved task.
3. Preserve tenant isolation, permission checks, SaaS flows, and landing page boundaries.
4. Update tests or add focused tests when behavior changes.
5. Complete the Knowledge Impact Assessment and update `.kms-impact.yml`.
6. Update relevant Markdown docs.
7. Update change history, ADRs, module history, and AI project context when needed.
8. Run `scripts/kms.py sync` if included docs changed.
9. Run `scripts/kms.py check` for final read-only enforcement.
10. Run reasonable implementation validation.
11. Report code changes, docs changes, KIA, validation, assumptions, and known issues.

## Smart Timetable Versioning Boundary

Stage 3.5 corrects school-day timing. Start time plus teaching-period count and
duration plus inserted non-teaching durations produces one per-day ordered timeline
and a calculated end. `after_period` blocks shift later teaching periods; preserved
`fixed_time` blocks must begin on a live timeline boundary or configuration fails
closed. The projection is shared by preview, operational grid, readiness,
assignments, snapshots, solver slots, and exports. Existing `break`, `prayer`,
and `non_teaching` keys remain valid and the controlled catalog also includes recess,
lunch, assembly, whole-school event, advisory, intervention, transition, dismissal
preparation, and other. This stage does not generate a timetable.

Stage 4 makes the existing lifecycle operational. Version review is explicit and
does not move the active pointer. Active, superseded, and archived versions are
read-only and may be reused only through an explicit copied draft. Draft validation
checks current fingerprint, complete demand, canonical slots, Planning teacher
authority, collisions, stale placements, and locks; it is distinct from generation
readiness. Publication requires a fresh `publication_ready` draft and atomically
swaps the revisioned active pointer while superseding prior active history.

Placement actions use separate create/edit/delete permissions. Locks use
`timetable.lock_lessons`, publication uses `timetable.publish`, archive uses
`timetable.archive_versions`, and explicit selected-version export uses
`timetable.export`. Every operation remains branch/year/SchoolGroup scoped.

Stage 3.5 makes the composed per-day slot projection authoritative across the page,
assignment service, exports, readiness, and snapshots. Inserted blocks consume no
teaching-period number and shift later clock times; ambiguous fixed-time placement is
invalid. Readiness is an exact-scope, read-only
structural gate; `generation_ready` permits a Stage 5.1 solve attempt and does not
guarantee feasibility. Existing versions and stale placements remain preserved.

The operational timetable uses a versioned aggregate scoped by SchoolGroup,
Branch, and Academic Year. `TimetableVersion` owns placements and lifecycle;
`TimetableActiveVersion` separately selects at most one exact-scope operational
baseline. `TimetableInputSnapshot` preserves deterministic Planning/settings/lock
authority and component fingerprints. `TimetableGenerationRun` is the Stage 5.1
durable PostgreSQL work queue with progress, attempts, lease/heartbeat, cancellation,
safe terminal status, and result linkage.

Planning remains authoritative for section-subject demand, teacher assignments,
and HRT fallback. A timetable placement is one teaching period and current
`Subject.weekly_hours` is the compatibility required-period value. Existing live
placements migrate without normalization into an imported active compatibility
version. The current edit route uses a working draft copied from active history;
current views and exports resolve that operational draft after edits. Active,
superseded, and archived versions cannot be edited in place.

ADR 0026 defines readiness, hard/soft constraint separation, CP-SAT execution,
independent validation, regeneration diversity, and publication boundaries. Stage
5.1 implements the hard-constraint generation slice; availability, rooms/resources,
cross-campus coordination, preferences, and quality scoring remain unimplemented.

## Knowledge Impact Assessment Rule

Every approved implementation must:

1. Assess knowledge impact.
2. Update relevant Markdown docs.
3. Update `docs/CHANGE_HISTORY.md` for meaningful changes.
4. Create or update ADRs when major decisions change.
5. Update module history when a module's documented state changes.
6. Update `docs/AI_PROJECT_CONTEXT.md` when high-level AI onboarding context changes.
7. Regenerate the PDF booklet if included docs changed.
8. Mention KIA details in the final report.

A task is not complete until the KIA is assessed.

Required final report KIA template:

```md
Knowledge impact: Yes/No
Docs updated:
Change history updated: Yes/No
ADR needed: Yes/No
Module history updated: Yes/No
PDF regenerated: Yes/No
AI project context updated: Yes/No
Reason if not updated:
```

The generated booklet output is:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

## Critical Rules Codex Must Follow

- Do not touch SaaS flows unless the task explicitly requires it.
- Do not touch operational logic unless the approved task requires it.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not weaken tenant isolation.
- Do not bypass route permissions or platform owner checks.
- Do not merge platform user, SaaS account, and tenant user concepts.
- Do not change the landing page design or legacy landing files unless explicitly approved.
- Do not add KMS regenerate behavior unless explicitly approved.
- Do not expose the KMS PDF through direct public static links in the app UI.
- Do not push or commit unless explicitly requested.
- Treat production memory as a hard budget. Do not add unbounded full-dataset caches, duplicate production template renders, startup-heavy work, or normal-request diagnostic logging that can trigger Render restarts and 502s.
- Prefer conservative, dependency-light automation.
- Use `reportlab` for the documentation PDF generator.
- Do not require LaTeX, Playwright, Chromium, external network calls, or system font dependencies for PDF generation.
- Always include a Knowledge Impact Assessment in implementation final reports.
- Always keep `.kms-impact.yml` aligned with the task and actual Git diff.
- Never put customer, personal, production, credential, secret, environment, transaction, invoice, webhook payload, or database-row data into KMS documentation.
