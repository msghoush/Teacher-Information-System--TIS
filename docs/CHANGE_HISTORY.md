---
title: TIS Change History
documentation_version: 3.3
last_updated: 2026-08-26
source_of_truth: true
---

# TIS Change History

## 2026-08-28 - Present One Logical Draft Across Generation

- Kept backend generated-result versioning and provenance while presenting the
  generated result as the continuation of the selected Draft Timetable.
- Bound current Draft actions to the selected exact-scope version, refreshed Check
  and Publish state coherently, and added Create New submit feedback.
- Hid obsolete generated-source drafts from normal History cards and separated the
  bulk unpublished action visually.

## 2026-08-28 - Canonical Generation Freshness Authority

- Excluded generation-only runtime metadata from freshness fingerprints while
  retaining it in immutable solve snapshots.
- Aligned generated-result authority with the generation snapshot contract and added
  safe component-level mismatch diagnostics.

## 2026-08-28 - Simplified Draft Ownership And Unpublished Cleanup

- Made the newest mutable non-active exact-scope version the current Draft Timetable,
  including a fresh Create New Timetable draft, and bound Generate to that context.
- Changed customer-facing draft deletion to permanent deletion for eligible
  never-published versions while retaining History-only archive behavior.
- Added exact-scope Delete All Unpublished Timetables with dependency-safe cleanup,
  preserved snapshots and generation audit records, protected publication history,
  and visible partial-failure reporting.
- Reconciled History deletion eligibility with the backend and replaced Create Draft
  Copy with Use as New Draft for immutable historical versions.

## 2026-08-26 - Replaced Always-On Timetable Worker With On-Demand Workflow

- Added a registered Render Workflow task that receives only a durable generation
  run public ID and reuses the Stage 5.1 solve/validate/persist pipeline.
- Added lightweight post-commit web dispatch, terminal handling for immediate
  dispatch failure, delayed-start feedback, and exact-run PostgreSQL claiming.
- Kept leases, heartbeats, cancellation, staleness, independent validation, atomic
  persistence, and duplicate-result guards; solver mathematics and Stage 5.2 UX did
  not change.
- Disabled Render automatic task retries and made the prior infinite polling worker
  optional/local only, removing the always-running production solver requirement.

## 2026-08-26 - Implemented Smart Timetable Stage 5.2 Simplified Workflow

- Simplified management around one Working Timetable and secondary Timetable History.
- Added permissioned Delete Working Timetable archive semantics that preserve history
  and never change the official active pointer.
- Added active-pointer-only official resolution, teacher `/my-timetable`, a general
  published view, and view-only redirection away from drafts.
- Added scoped visibility, deletion, wording, permission, and Stage 4/5.1 regressions.

## 2026-08-22 - Implemented Smart Timetable Stage 5.1 Generation

Added worker-isolated OR-Tools CP-SAT generation, schema-v3 immutable problem
snapshots, an independent candidate validator, and durable PostgreSQL queue leasing,
heartbeat, bounded recovery, cancellation, progress, and active-scope protection.
Generate and Regenerate now create separate validated unpublished versions without
changing published history; regeneration preserves locks and enforces an explicit
minimum difference. Added `timetable.generate`, polling UI, additive migration
`20260822_001_smart_timetable_stage51_generator`, and solver/lifecycle coverage.

## 2026-08-21 - Corrected Timetable Configuration With A Composed Day Timeline

Replaced fixed teaching-period clocks plus overlap classification with one per-day
timeline composer. Blocks may be inserted after a period or preserved as fixed time
when boundary-aligned; later periods and calculated end times shift automatically.
Readiness, assignment validation, snapshots/fingerprints, timetable UI, and exports
now share the projection. Added explicit additive placement metadata and expanded
the controlled school block catalog. No automatic generation was introduced.

## 2026-08-21 - Added Smart Timetable Stage 4 Version Publication

Made timetable lifecycle visible through scoped history selection, immutable-version
draft copies, draft lesson locks, explicit validation, same-scope comparison,
selected-version exports, archive controls, and transactional publication. Publication
revalidates authority and hard validity, checks edit/pointer revisions, supersedes the
previous active version, and preserves history. No schema, solver, worker, generation
endpoint, commit, push, deployment, or production action was included.

## 2026-08-19 - Added Smart Timetable Stage 3 Readiness And Slot Semantics

Added canonical fixed-period teaching/unavailable/invalid slots, server-side
assignment protection, stale-placement preservation, snapshot integration, and an
exact-scope read-only readiness service with customer-safe page status. No schema,
solver, worker, Generate endpoint, commit, push, deployment, or production action
was added.

## 2026-08-19 - Added Smart Timetable Stage 2 Version Foundation

Accepted ADR 0026 and added durable timetable versions, deterministic authority
snapshots and SHA-256 fingerprints, one exact-scope active pointer, persisted
placement locks, future generation-run metadata, and per-version section/teacher
collision constraints. Existing populated timetables migrate without placement
changes into imported compatibility versions; inconsistent rows remain present
with safe version-level stale evidence, and settings-only scopes remain empty.

The current timetable page and exports now read one operational version. The
existing assignment route uses copy-on-write so active history is immutable while
the current editing experience continues through a mutable working draft. No
solver, worker, generation route/UI, availability, room/resource, or rule model
was introduced.

## 2026-08-19 - Restricted Compact Descriptions To Intentional UI Components

Changed the shared compact-description enhancer from broad tag and class-name
inference to explicit `data-compact-description` opt-in plus the maintained
allowlist of approved compact components. Ordinary operational status, helper,
note, subtitle, and supporting text now remains visible inline. Existing
keyboard/focus tooltip behavior and unrelated native accessible titles remain
unchanged.

## 2026-08-19 - Capacity-Based Packaging And Common Customer Feature Baseline

Accepted ADR 0025 and replaced the temporary plan-feature ladder with one normal
customer baseline for coherent active paid, promo, and customer-demo workspaces.
Starter, Professional, and Enterprise AI retain their existing branch, staff, and
teacher ceilings. Advanced Reporting and enabled AI are source-aware and
plan-neutral while permissions, tenant/branch/year scope, commercial lifecycle,
branch entitlement, and globally disabled features remain fail-closed.

Added idempotent migration
`20260819_001_capacity_based_customer_feature_baseline` for plan values, compatible
legacy flags, current active promo operational feature values, and active demo
baseline policy. Exact promo capacity and immutable grant/redemption history are
unchanged. Added a separate minimal AI consumption-policy boundary and retained
reservation, counter, and operation-event accounting. Updated only affected
customer copy; report generators and calculations did not change.

## 2026-08-18 - Enforced SchoolGroup Management Boundary

Direct operational SchoolGroup creation and deletion now require Platform identity,
the matching create/delete permission, and `schools.manage_all_schools`. Tenant role
defaults no longer include top-level create/delete, stale permission state cannot
bypass the handler guard, and tenant updates are limited to the linked SchoolGroup.
Unauthorized requests fail before validation, storage, or database mutation.

School Management now uses unified commercial authority for source-aware branch
capacity presentation, including accurate promo `used of allowed` state. Existing
locked branch enforcement and atomic promo assignment remain unchanged. The
individual last-active-branch safeguard now counts within the target SchoolGroup.
Added a PostgreSQL-only, repeatable-read, rollback-on-exit provenance audit that
reports suspicious unlinked active internal sandboxes for manual review without
repairing them.

## 2026-08-18 - Completed Promo Expiry Recovery And Paid Continuation

Promotional operational access now ends exactly at `PromoGrant.effective_to`.
`grace_period_days` is a commercial recovery window for Organization Account and
paid continuation only; it never extends operational access and does not archive or
delete tenant data.

Verified owners of expired or recovery-period promo workspaces can use the existing
tenant paid-activation flow. Checkout and pending payment leave promo authority
unchanged. Verified provider completion atomically ends the promo entitlement,
relinks the existing tenant source to the paid contract, establishes paid workspace
and branch entitlements, and preserves tenant identity, data, branding, ownership,
and immutable promo history. Active-promo early conversion remains blocked.

Added one authority-driven commercial badge component for Promo, Demo, and Paid
sources in Organization Account and the full commercial view. The normal operational
header intentionally remains focused on tenant context. Expired promo access uses
promo-specific continuation wording, and protected
API responses return a customer-safe generic commercial code while internal reasons
remain in server logs.

## 2026-08-18 - Added Promo-Aware Commercial Access Presentation

Organization Account Billing & Subscription now selects paid, demo, or promo
presentation from the selected workspace's authoritative commercial source. Promo
customers receive a dedicated read-only page for their grant plan, safe access
status and period, masked reference, and centralized branch/system-user/teacher
capacity. The page does not invoke Paddle or expose paid-only billing and mutation
controls. Existing paid and demo journeys remain unchanged, and promo-to-paid
conversion remains deferred.

## 2026-08-17 - Corrected Promo Branch Entitlement Lifecycle

Promo activation now creates explicit active or inactive entitlement evidence for
every preserved branch, including operationally inactive unselected branches that
previously fell outside the selectable-branch query. Individual and bulk branch
reactivation continue through centralized capacity authority and now update branch
status, promo assignment, and entitlement atomically. Capacity exhaustion and
contradictory evidence fail before commit.

Added a generic PostgreSQL-only reconciliation command that defaults to dry-run,
locks and revalidates on explicit apply, and creates only deterministically missing
inactive branch entitlements. It never changes branch status, assignment, grant,
capacity, Paddle, or people records. The Al-Andalus audit now distinguishes broad
operational-user row inventory from M1 authoritative active staff usage.

## 2026-08-13 - Corrected Existing Workspace Plan Selection

Organization Account **Choose a Plan** now reopens eligible paid-plan selection for
an existing workspace while its activation remains `draft` or `checkout_ready`.
The saved plan is highlighted and can be replaced with a newly calculated
authoritative quote. Browsing or replacing a draft creates no Paddle request or
PaymentAttempt and does not mutate branches. Once checkout starts, payment is
processing, or evidence requires manual review, replacement fails closed. Promo,
PendingOrganization checkout, and verified-payment activation authority are
unchanged.

## 2026-08-07 - Corrected Existing Workspace Payment Status Presentation

Organization Account now displays `Activation required` for a converted existing
workspace that has no real unresolved Paddle checkout attempt. Payment processing is
shown only for a current, unexpired `PaymentAttempt` in checkout-started or payment-
processing state. Failed, cancelled, and expired attempts use recovery states, while
completed paid and promo activation continue to show their active commercial state.
No payment, Paddle, promo, capacity, or commercial-authority transition changed.

## 2026-08-06 - Implemented M4C Existing Workspace Paid Activation

Added a SchoolGroup-anchored paid activation workflow for verified owners of
activation-required existing customer workspaces. The implementation adds additive
schema, strict checkout/payment context constraints, operational capacity and branch
quote snapshots, workspace billing/customer mapping, Paddle transaction launch,
webhook-only atomic paid authority, Organization Account activation UX, centralized
paid entitlement resolution for `customer` classification, and focused regression
coverage. It does not create PendingOrganization or invoke tenant provisioning.

Final PostgreSQL validation hardened reused-transaction verification, persisted
workspace-specific provider address/business lineage, refreshed ORM state after
workspace row locks for concurrent duplicate webhooks, and proved that paid-versus-
promo races create exactly one commercial source with no partial losing records.

Starter remains unavailable until complete restricted-branch enforcement is proven.
No production data or real Paddle records were used during implementation. Live
Paddle Sandbox checkout remains an environment validation gate.

## 2026-08-06 - Controlled Existing Workspace Owner Alignment And Conversion

Added a durable, idempotent conversion ledger and dry-run-first PostgreSQL CLI
for an existing audited internal sandbox. The process prepares an ownership
claim without creating an account, requires normal account verification,
aligns or safely reuses one tenant owner, and collects only legal name, IANA
timezone, and educational program. A database partial unique index now enforces
one active tenant-owner account link per SchoolGroup after duplicate preflight;
conversion events are append-only.

Final conversion locks and re-audits the operation and workspace, validates
unchanged branch/dependency and sandbox-authority snapshots, retires the active
internal entitlement, and sets `customer / provisioning` atomically. It does
not mutate branches or operational records and creates no pending organization,
contract, subscription, demo request, promo grant, active entitlement, or
tenant link. M1 resolves the result as `activation_required`; M3 promo remains
the supported activation path while existing-workspace Paddle activation is
deferred. No production data was modified during implementation or validation.

## 2026-08-05 - Existing Workspace Conversion Read-Only Audit

Added a generic M4A audit service and parameterized PostgreSQL CLI for gathering
sanitized evidence before a legacy internal-sandbox conversion is designed.
The audit validates the exact workspace identity, resolves the intended owner,
inventories tenant/provisioning and paid/demo/promo authority, reflects
SchoolGroup-scoped tables, and traverses direct and indirect branch foreign-key
dependencies. Unconstrained branch-like references and incomplete traversal
fail closed for manual review.

The CLI uses a repeatable-read, read-only transaction, prints one JSON object,
or deterministic text, records its PostgreSQL transaction mode, emits a stable
SHA-256 snapshot hash, and always rolls back. Coherent, execution-failure,
manual-review, and identity-mismatch results use exit codes `0`, `1`, `2`, and
`3`. Soft-deleted dependencies remain blocking, reflected foreign keys absent
from ORM metadata force manual review, and archival recommendations contain
only proven dependency-free active branches. This milestone performs no branch archival, owner
alignment, workspace or entitlement change, tenant-link creation, write-mode
conversion, Paddle call, email, schema change, migration, or production audit.

## 2026-08-05 - Promo Redemption, Immutable Grants, And Activation

Added customer-side secure promo lookup, resumable capacity review, exact
branch selection, and atomic activation for completed onboarding and separately
aligned existing organizations. Migration
`20260805_002_promo_redemption_and_grants` adds activation sessions and branch
selections, immutable redemptions and grants, grant branch assignments, and
redacted redemption events. It also adds promo references to workspace
entitlements and tenant links while enforcing exactly one paid, demo, or promo
source.

M1 commercial authority, commercial access, branch queries, and future branch
creation now resolve active promo grants and explicit branch entitlement.
Organization-wide staff or teacher excess blocks activation without changing
records; unselected branches remain operationally preserved but commercially
inactive. Pending sessions provide no access, expiration fails closed, raw
codes remain absent from storage and logs, internal sandboxes are not converted,
and Paddle/payment behavior is unchanged.

## 2026-08-05 - Promo Code Foundation And Platform Console Management

Added secure definition-only Starter, Professional, and Enterprise AI promos
with exact capacity bounded by the existing plan catalog, controlled targeting,
validity and expiry policy, versioned lifecycle, duplicate/replacement support,
optional branch restrictions, and durable redacted audit. Raw codes use at
least 100 bits of secure randomness, are shown once in a no-store response, and
are represented in storage only by dedicated-secret HMAC lookup authority and
safe masked fragments.

Platform Console now exposes permission-controlled promo list, filter, create,
detail, edit, activate, pause, revoke, duplicate, and replacement-definition
workflows. Platform Developers may manage non-terminal definitions but only a
Platform Owner may activate or revoke. Additive migration
`20260805_001_promo_code_foundation` creates three tables without backfill.
No customer redemption, commercial entitlement, M1 authority, Paddle,
onboarding, provisioning, payment, or tenant behavior changed.

## 2026-08-04 - Unified Commercial Access And Capacity Authority

Operational branch, staff-user, and teacher growth now uses one commercial
authority facade that composes the existing workspace, entitlement, tenant
link, contract, confirmed subscription, commercial-access, demo-lifecycle, and
plan-capacity authorities. Missing or contradictory authority fails closed;
Customer Demo and Internal Sandbox remain explicitly unmetered in M1.

Paid branch limits use confirmed provider-reconciled quantity capped by the
plan branch ceiling. Staff usage counts every distinct active tenant
operational user, including operational owners and teacher-position users;
platform and account-only identities are excluded. Teacher usage deduplicates
normalized known teacher IDs while counting every blank legacy row separately.
The same person may consume both one staff and one teacher slot.

Capacity-increasing branch, user, teacher, academic-year, and provisioning
paths lock the SchoolGroup, recount, evaluate, mutate, and commit in one
transaction. Existing over-capacity tenants retain data and access but cannot
increase an exceeded dimension. Paid and demo provisioning validate final
authority before activation completes. No schema, migration, Paddle, pricing,
webhook, onboarding-transition, permission, or feature-packaging change was
made.

## 2026-08-02 - Billing Contact Editing And Paddle Retry

Subscription Management now presents Billing Contact as read-only organization
identity with an explicit Edit, Save Changes, and Cancel interaction. The legal
identity label now covers an organization or school name, and the billing
country uses the supported country selector.

Valid local billing changes remain committed when Paddle synchronization fails.
A dedicated permission- and tenant-scoped retry reuses the saved profile and
persisted customer, address, and business mappings, avoids duplicate provider
objects, and performs no provider call once synchronized. Customer status copy
distinguishes local save, provider synchronization, and retry failure. Safe
server diagnostics identify the customer, address, business, or subscription
identity step plus provider status/error code. A saved pending or failed billing
identity prevents new plan or quantity changes until provider synchronization
succeeds; cancellation and legacy active subscriptions without a profile remain
unchanged.

## 2026-08-01 - Explicit Organization Billing Identity

Billing & Subscription now stores one explicit organization billing profile
covering billing email, legal/billing name, contact, optional company and tax
identifiers, and the supported address structure. This authority is independent
from SaaS login email. Initial checkout confirms it, while active-tenant changes
require organization ownership or `subscriptions.manage_billing` and revalidate
tenant/provider linkage.

TIS reuses the mapped Paddle customer, synchronizes authorized email/name
changes, creates or reuses one attributable active Paddle Business, persists
the Paddle address/business mappings, updates the active subscription identity,
and includes `business_id` on future initial checkout transactions. Ambiguous
mapping and provider failures fail closed. Existing financial documents are not
silently revised.

Provider transaction presentation now distinguishes `paid` as Payment received
- processing from `completed` as Paid. Subscription change requests record the
payment-received timestamp separately, show that no customer action is required
while provider processing finishes, and retain the existing `completed`
reconciliation authority. Additive migration
`20260801_001_organization_billing_identity` creates
`organization_billing_profiles`, adds Paddle address/business mapping columns,
and adds the separate payment-received timestamp.

## 2026-08-01 - Subscription Capacity Presentation And Billing Navigation

Subscription pages now separate confirmed paid branch quantity from the current
plan's maximum branch ceiling. Review Capacity identifies additional required
branches as additional billed quantity and retains system-user and teacher
counts as non-billed eligibility limits. Unapproved feature claims and empty
feature placeholders were removed from customer plan comparison.

System Configuration now exposes Billing & Subscription only to a linked
organization owner or user with explicit billing authority. The route
revalidates operational tenant scope and the SaaS account-user relationship,
then opens the existing Organization Account subscription page. Password and
social authentication preserve only the allowlisted internal billing return;
external or unrelated destinations fail back to Organization Account. The
public landing label is Organization Sign In and still uses centralized SaaS
authentication. No pricing, Paddle quantity, lifecycle, webhook, entitlement,
schema, or migration behavior changed.

## 2026-08-01 - Unified Active Subscription Capacity Management

Subscription Management previously presented branch quantity as an isolated
commercial action. One authoritative organization-capacity resolver now counts
active branches, active tenant operational staff users, and active teachers. The
portal exposes one Review Capacity flow and displays usage, plan limits, and
remaining capacity for all three dimensions. The highest required dimension
selects the minimum eligible plan: Starter supports 1 branch/5 system users/25
teachers, Professional supports 5/20/100, Enterprise AI supports 25/100/500,
and Custom is required when any Enterprise AI limit is exceeded. Customers may
still select a higher eligible plan for optional feature entitlements. Branch,
system-user, teacher, or mixed growth can trigger an upgrade. Required branch
growth can combine target plan and branch quantity in one provider preview.
Paddle quantity remains active-branch count only; system-user and teacher
capacity affect plan eligibility but never become billed quantity units.

Plan-change previews retain their three-dimension capacity evidence. All three
dimensions are validated before a downgrade is submitted, and downgrades remain
scheduled for the next billing boundary. The same three dimensions are
revalidated when provider evidence reaches the effective date. Capacity growth
that no longer fits enters manual review, does not activate the lower plan, and
preserves the current safe entitlement state. Existing provider-authoritative
proration remains unchanged. Higher entitlements require both provider
subscription and payment confirmation. Cancellation remains scheduled at
paid-period end, preserves access and tenant data through the confirmed date,
and remains reversible when supported by Paddle. No schema or migration change
was required.

## 2026-08-01 - Organization Account Sign-In Routing

Public and onboarding SaaS sign-in previously sent an activated, commercially
allowed organization customer directly to operational `/login`. Authentication,
already-authenticated restoration, and social sign-in now use one customer
journey decision that lands authorized organization account managers on
`/saas/account`. The Organization Account Overview presents only permitted
organization, branch, billing, and security sections, and Enter TIS Platform is
the sole explicit operational entry action.

Incomplete onboarding and pending demo review still resume their authoritative
steps. Restricted or suspended account managers remain in account billing and
recovery context; operational users without account-management permission keep
their role-based destination. Multiple managed organizations require selection
before an overview is rendered. The HTTP-only selected-organization hint is
revalidated against current account links and permissions before the existing
entitlement resolver accepts its tenant scope. Existing commercial access,
permissions, subscription authority, operational authentication, schema, and
tenant isolation remain unchanged.

## 2026-07-31 - Contract-Linked Commercial Access Consistency

Operational access previously selected the newest PaymentSubscription for the
onboarding organization, while Subscription Management and entitlements used
the tenant link and authoritative SubscriptionContract. A pending plan upgrade
or newer stale subscription row could therefore block an otherwise active paid
workspace and every blocked paid state was presented as expired.

Operational login, protected requests, returning-customer routing, and access
pages now consume one contract-linked commercial access projection over the
existing entitlement resolver. The current active/trialing plan remains
authoritative while a plan change is pending, failed, incomplete, canceled, or
abandoned. Canceled subscriptions remain entitled only through the confirmed
paid period end. Restricted states use distinct payment-processing, past-due,
paused, expired, suspended, archived, and verification-required guidance.

The specialized plan-change subscription webhook now applies the same provider
status normalization as the general and quantity-change paths. It does not
complete or activate the target plan without the existing two provider signals.
No schema, migration, pricing, quantity, Paddle request, webhook authority, or
tenant data changed.

## 2026-07-30 - Initial Secure Payment Retry And Lineage Hardening

The Secure Payment summary could be correct while launch rejected an otherwise
eligible unpaid organization whose persisted billing status or checkout
lineage was stale. Plan and interval changes marked the checkout session stale
but did not consistently supersede its unfinished payment attempt. Retry could
therefore repeat a local readiness failure or retain obsolete transaction
authority.

The incident itself occurred before any Paddle API request:
`_ensure_checkout_launchable()` rejected a legacy `ready_for_checkout`
pre-checkout billing state. That state can now be prepared safely. The
Professional Annual mapping was unchanged at USD 790 per active branch, so the
verified two-branch quote remains quantity 2 and USD 1,580 annually.

Checkout recovery now treats plan selection, checkout session, payment attempt,
quote fingerprint, provider price, interval, and quantity as one lineage.
Obsolete sessions and unfinished attempts are superseded, current local
authority is cleared, and Retry prepares a fresh session from the authoritative
quote. Existing started transactions are reused only after remote billed,
automatic-collection, customer, quote, item, quantity, and subtotal validation.
Superseded webhooks cannot activate a subscription or workspace.

Paddle address resolution now reuses an active exact-country address for the
same customer before creating one. Provider and readiness failures retain
status/code and traceback in server logs while the customer sees one safe
retry alert. No pricing, capacity, schema, migration, webhook authority,
provisioning, or checkout architecture changed.

## 2026-07-29 - Organization Profile Save And Account Setup Correction

The Organization Profile POST accepted its program values correctly but used
MIME/extension-only logo checks and wrote directly to the application
filesystem. Its route caught only `ValueError`; an `OSError` while creating or
writing `static/uploads/saas/pending_logos` escaped as raw HTTP 500. Corrupt
and oversized files could also be accepted. The fresh Account Setup page
repeated the same next-step guidance across the status, side action, content,
and help panels.

Pending logos now reuse actual-image decoding, the established 4 MB and
minimum-dimension checks, UUID filenames, pending-directory confinement, and
atomic temporary-file promotion. Empty uploads retain the current reference.
Rollback removes a newly written file; successful replacement removes the old
file after commit. Validation, storage, and unexpected failures all render a
safe page response with preserved entered values, while technical failures
receive traceback logging.

The initial account state now shows a smaller official logo, one "Start Your
School Workspace Setup" title and sentence, the existing eight-step progress
track, and one POST start action. Later setup-console states remain unchanged.
No schema, migration, billing, payment, provisioning lifecycle,
operational-module, or landing-site behavior changed. Provisioning's existing
logo-copy step was hardened without changing activation authority.

The current storage location remains application-local
`static/uploads/saas/pending_logos`. Render durability requires a separately
approved persistent-disk or object-storage decision.

Organization branding now appears in the Organization Profile preview and
shared School Workspace setup identity without replacing the official TIS
logo. Existing paid/demo provisioning continues to promote the pending image
into the primary `SchoolGroupLogo` slot; source resolution is now confined to
the pending directory, a missing referenced file blocks activation rather than
silently losing branding, and the final accessible label includes the
organization name. The existing protected organization-asset route and
operational shell remain the final display path.

Branch Setup previously asked Jinja to sum `estimated_system_users` and
`estimated_teachers` directly. Placeholder and incomplete rows supplied
undefined or `None`, producing `TypeError: unsupported operand type(s) for +:
'int' and 'NoneType'`. Totals now come from a Python helper that normalizes
display-only missing values to zero. Required server validation remains active
for customer saves, and newly created pending branches receive explicit zero
defaults.

## 2026-07-29 - Post-Verification Sign-In 405 Correction

A fresh verified account had no pending organization or operational account
link, so `customer_journey_service.login_destination()` returned
`/saas/onboarding/start`. That route accepts POST only. After successful
credential POST, the 302 caused the browser to request that destination by GET,
and FastAPI returned raw `{"detail":"Method Not Allowed"}` with HTTP 405.
Existing tests supplied `/saas/account` explicitly and therefore masked the
normal browser journey.

Fresh verified accounts now continue to the GET `/saas/account` dashboard;
the existing start-setup action remains the only POST that creates an
organization. Login continuation validation accepts only known customer GET
destinations and rejects POST-only, malformed, traversal, fragment, and
external values. A compatibility GET for `/saas/auth/login` redirects to the
normal GET sign-in page. Verification, password authentication, onboarding
rules, subscription intent, preferred-plan authority, checkout, Paddle,
schema, and landing behavior are unchanged.

## 2026-07-29 - Safe Public Subscription Pricing Entry

The landing hero Subscribe Now action now scrolls to pricing. Starter,
Professional, and Enterprise AI use identical CTA styling and enter the public
TIS Account signup route with distinct allowlisted preferred-plan codes.
Pricing cards no longer show the small description beneath each plan name.
Custom remains contact-only.

The signup GET route previously referenced an undefined `next_path` local,
causing every unauthenticated subscription pricing link to return HTTP 500
before account or onboarding state was evaluated. The route now accepts and
safely normalizes that optional value. A self-service plan preference is
preserved through registration in a secure cookie, creates no plan selection or
payment record, and is applied only when the existing organization-wide
branch, system-user, and teacher checks confirm eligibility. Invalid,
inactive, or undersized preferences are cleared. No price, plan limit, Paddle
quantity, payment authority, or AI entitlement changed.

## 2026-07-29 - Per-Branch System-User And Teacher Subscription Capacity

Branch Setup now stores required non-negative estimates for system users and
teachers on every active branch and presents live organization-wide totals.
Migration `20260729_001_subscription_capacity_dimensions` preserves legacy
organization estimates by assigning them to the primary active branch only
when no branch estimates exist. Derived organization totals remain compatibility
summaries rather than competing authority.

Eligibility checks branches, non-teacher system users, and teacher records
independently. Starter supports 1/5/25, Professional 5/20/100, and Enterprise AI
25/100/500. Before payment, each people dimension uses the greater of branch
estimates and actual same-workspace active data; after activation actual data
is authoritative. The minimum eligible plan is recommended, higher eligible
plans remain available, and exceeding any Enterprise limit selects the
contact-only Custom path.

All quote and checkout fingerprints include both people counts. Capacity
changes supersede stale checkout lineage and clear only an undersized plan.
Paid non-teacher user creation/reactivation, teacher creation and year-copy
preflight, and plan downgrades fail before mutation when capacity would be
exceeded.

## 2026-07-28 - Authoritative Subscription Plan Branch Capacity

Self-service plan eligibility now uses each active plan's persisted
`max_branches`: Starter supports one active billable branch, Professional five,
and Enterprise AI twenty-five. Pricing remains the selected plan's per-branch
price multiplied by the actual authoritative active count.

Plan selection, quote construction, checkout preparation and launch, and
payment validation fail closed when capacity is exceeded. Pre-payment branch
expansion clears an undersized selection and supersedes its quote and checkout
lineage; an eligible higher plan remains selected. Organizations above the
Enterprise AI limit receive a customer-safe custom-plan contact state.

## 2026-07-28 - Pre-Payment Branch Editing And Checkout Supersession

Branch Setup previously rejected any organization with a
`TenantProvisioningLink`, incorrectly treating an unpaid demo or prepared
workspace as paid provisioning. Editing now closes only on authoritative
confirmed-payment or active-paid-subscription evidence. Before that boundary,
customers may add, edit, remove, reorder, and reprioritize branches.

Changing branch count or identity stales the prepared checkout, supersedes its
incomplete payment attempt, clears quote snapshots, and recalculates the next
checkout from the final active count. Late provider events from a superseded
transaction are recorded for manual review without activating or converting the
workspace or disrupting the replacement checkout.

## 2026-07-28 - Fixed Paddle Checkout Branch Quantity

Paddle checkout exposed quantity controls even when the server-created
transaction contained the TIS billable branch count; inline presentation alone
does not make transaction items immutable. TIS now supplies the resolved Paddle
customer address, requires an automatically collected transaction to reach
ready state, validates its quote evidence, and marks it billed before releasing
its transaction ID to Paddle.js.

Billed transaction items cannot be changed. The same catalog price remains
usable with organization-specific quantities; no price mutation or
quantity-specific price is created. Automatically collected payment completion
remains the recurring-subscription, webhook, and demo-conversion authority.
The public payment launcher now explicitly treats `billed` as the only valid
remote launch state and verifies the local attempt, checkout, customer, and
quote context before supplying `transactionId` to Paddle.js. Invalid states
fail closed without exposing provider diagnostics.

## 2026-07-28 - Expired-Demo Checkout Identity Resolution

Expired-demo Paddle checkout could find one active customer by email but reject
it when provider custom data retained a deleted SaaS account context and the
existing operational tenant owner was treated as an unrelated identity. The
checkout guard now accepts or repairs a stale SaaS account-user relationship
only when the authenticated account, owned organization, demo source,
tenant-provisioning link, SchoolGroup, and sole active operational owner form
one coherent relationship. Active previous accounts, unrelated tenants,
multiple identities, and live-mode email-only recovery remain blocked.

Customer responses no longer expose identity match counts or internal reason
codes, and a failed preparation displays retry/support guidance rather than a
ready-payment state. No workspace, branch, tenant, payment authority, pricing,
or provider-environment rule changed.

## 2026-07-28 - Returning Customer Journey And Expired Access

Expired demos previously entered the paid subscription portal, whose model
requires paid entitlement evidence, so normal demo values rendered unavailable
and no conversion action existed. Some returning sessions could also reach
workspace setup before expired paid state was intercepted.

TIS now builds demo subscription choice from the existing organization,
workspace, active operational branches, public plans, and intervals, then hands
selection to existing Paddle checkout and same-workspace conversion. SaaS and
operational login route from authoritative state; a shared commercial guard
blocks expected demo or paid expiry before protected page work. Customer
communications use TIS-team terminology. Landing navigation adds Sign In and
Open TIS App. All M8B9 owner controls remain available under progressive
disclosure. No schema, migration, pricing, payment-confirmation, AI-entitlement,
workspace replacement, commit, or push change was made.

## 2026-07-27 - M8B9 Demo Operations, Notifications, And Testing

Added owner-only immediate expiry, same-workspace reactivation, unbounded future
custom expiry, rotating final-day reminders, and manual single/global lifecycle
execution through existing production rules. Added Standard, Full, and Custom
controlled access policies with workspace defaults and isolated branch
overrides, durable audits, and customer communications without usage resets,
classification changes, or customer-specific rules.

## 2026-07-27 - Pre-Deploy Database Migration Boundary

Replaced the temporary Render daemon migration worker and HTTP readiness gate
with a strict deployment boundary. The FastAPI web process no longer creates
tables or runs migrations during import, startup, middleware, or background
execution. `python scripts/run_migrations.py` now owns baseline metadata
creation and the authoritative ordered migration ledger as Render's required
Pre-Deploy Command. A failed migration exits nonzero and prevents activation of
the new web version; a successful or already-current run exits zero and logs
the applied migration identifiers.

The migration process now configures PostgreSQL `connect_timeout=10s`,
`lock_timeout=5s`, and `statement_timeout=30s` at connection creation, before
`metadata.create_all()` or any migration-ledger DDL. Flushed progress records
bracket connection, metadata, ledger, migration apply, marker, and commit
phases. Lock or statement timeout failures therefore identify their boundary
and exit nonzero instead of waiting for the deployment timeout.
Transactional migration helpers now inspect tables, columns, indexes, and
constraints through the active migration connection. They never check out a
second engine connection while the first connection owns uncommitted DDL
locks, preventing the M8B7 `system_notifications` inspection self-deadlock.

## 2026-07-27 - M8B8 AI Entitlements And Commercial Foundation

Added one authoritative AI feature registry and entitlement service. Decisions
compose tenant scope, role permission, commercial state, feature policy, plan
entitlement, and usage without replacing any existing authority. Customer Demo
gets two successful uses per feature; internal, demo, and paid usage is
persisted separately through locked successful/reserved counters and
idempotent operation events. Enterprise AI is the only temporarily mapped paid tier. No AI tool,
pricing change, notification expansion, or M8B9 operational control was added.

## 2026-07-27 - Render Port-Bind Startup Boundary

Render previously executed SQLAlchemy table creation and every pending
migration while importing `main:app`. The initial mitigation moved that work
to a daemon worker behind an HTTP readiness gate. That temporary boundary has
been superseded by the Pre-Deploy Database Migration Boundary above.

## 2026-07-27 - M8B7 Demo Customer Journey

Platform Owner approval now orchestrates the existing independently retryable provisioning service. Durable branded email intents cover request receipt, activation approval, decline, Day 6, expiry, and same-workspace subscription continuation. Demo events reuse the Platform Owner Notification Center, and active tenant workspaces show a responsive demo indicator through the shared shell. Coherent expired demos may convert after authoritative confirmed payment by reactivating and converting the same SchoolGroup and tenant relationship. M8B8, M8B9, pricing redesign, second-workspace provisioning, and sandbox conversion remain out of scope.

This file is the chronological summary of meaningful TIS changes. It does not replace module history under `docs/history/`; it gives reviewers, developers, Codex, and ChatGPT a fast timeline of what changed and why.

Newest entries should be added first.

## 2026-07-26 - Platform Owner Historical Demo Eligibility Maintenance

Area/module:
Platform Owner SaaS Admin and Customer Demo domain eligibility

Previous state:
The organization-scoped clean-room reset safely removed current test data, but a historical detached eligibility reservation could no longer be reached after its organization and account had already been deleted.

New state:
Platform Owners have a separate maintenance page that scans demo-domain eligibility reservations and shows exact blockers. A row is removable only when no matching organization, account, demo request, tenant-profile workspace, provisioning record, subscription evidence, conversion, or manual-review evidence exists. Confirmed deletion rechecks and locks one exact ID, deletes only that ID, flushes, verifies absence, commits atomically, and writes a durable owner audit event.

Reason:
Repair verified historical orphaned reservations without weakening production one-demo-per-domain enforcement or changing the existing clean-room reset.

Files changed:
New demo eligibility maintenance service and templates, SaaS Admin routes/navigation, focused Phase 5 tests, KMS source documents, and regenerated KMS artifacts.

Documentation updated:
AI/master context, project state, change history, SaaS onboarding history, module map, system flows, and database architecture overview.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
No schema, foreign-key, migration, demo-request, clean-room reset, customer workflow, commit, or push change.

## 2026-07-26 - Verified Safe Demo-Domain Reservation Deletion

Area/module:
Platform Owner test workspace/account reset and Customer Demo domain eligibility

Previous state:
Reset analysis identified safe detached eligibility rows, but deletion depended on a second ORM lookup and reconstructed ID list and did not immediately verify removal before continuing with parent deletion.

New state:
Analysis publishes an explicit safe detached-reservation ID list. The owner-only deletion transaction consumes only that list, deletes by primary key before demo requests and parent records, flushes immediately, and verifies that no selected row remains. Structured logs record received IDs, query scope, affected rows, verification count, and the existing transaction commit or rollback.

Reason:
Make clean-room reset completion provable and fail closed while preserving conflict/manual-review protections and the production one-demo-per-domain policy.

Files changed:
Workspace analysis/deletion services, focused Phase 5 and domain diagnostics tests, read-only diagnostic tooling, and KMS sources.

Documentation updated:
AI/master context, project state, change history, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
No schema, foreign-key, unique-constraint, production eligibility, customer-message, commit, or push change.

## 2026-07-26 - Safe Orphaned Demo-Domain Reservation Cleanup

Area/module:
Platform Owner test workspace/account reset and Customer Demo domain eligibility

Previous state:
The clean-room reset removed eligibility rows only while they still referenced a selected demo request. A prior request deletion could leave a detached same-domain row through `ON DELETE SET NULL`, and that row continued to block a later internal demo request.

New state:
The owner-only reset resolves the selected organization's domain through the same Customer Demo domain resolver, counts linked and detached reservations, and checks for another organization, request, workspace, or customer account using that domain. It removes a detached reservation only when that conflict analysis is empty and the row has no historical manual-review evidence; otherwise, reset preflight blocks for manual review and preserves all data. Owner analysis views show the domain-cleanup result.

Reason:
Allow repeatable internal M8 testing without broadly deleting domain reservations or weakening the production one-demo-per-domain policy.

Files changed:
Workspace analysis/deletion services, owner reset-analysis templates, focused Phase 5 regression tests, and KMS sources.

Documentation updated:
AI/master context, project state, change history, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
No schema, foreign-key, cascade, customer demo-policy, payment, Paddle, commit, or push change.

## 2026-07-26 - Internal Test Workspace Commercial Clean-Room Reset

Area/module:
Platform Owner test workspace/account reset, M8 demo-commercial history, and customer-facing demo wording

Previous state:
The guarded reset removed the selected workspace/account data but retained the selected organization's demo request and normalized-domain reservation. A later internal registration for the same organization domain was therefore blocked by the production one-demo policy.

New state:
Within the existing owner-only reset transaction, TIS deletes only the selected pending organization's linked demo request, domain reservation, review/event history, demo provisioning/lifecycle records, and demo-to-paid conversion history before their parent records. The same internal test email and organization domain can complete a new M8 journey. Customer-facing demo review language now refers to the TIS team.

Reason:
Support repeatable internal end-to-end M8 testing without weakening the production Customer Demo one-domain restriction.

Files changed:
Workspace analysis/deletion services, customer demo wording, focused Phase 5 regression tests, and KMS sources.

Documentation updated:
AI/master context, project state, change history, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
Owner-only test reset exception. No schema, foreign-key, cascade, payment, Paddle, normal customer demo-policy, lifecycle, commit, or push change.

## 2026-07-26 - Test Workspace Reset Entitlement Dependency Fix

Area/module:
Platform Owner test workspace/account reset, workspace entitlements, and scoped cleanup dependencies

Previous state:
The controlled reset reached final SchoolGroup deletion while a selected workspace entitlement still referenced that SchoolGroup. Entitlement child values and branch-entitlement rows also required explicit dependency review.

New state:
The reset removes selected `workspace_entitlement_values` and `branch_entitlements`, then the selected `workspace_entitlements` rows, before the final SchoolGroup deletion. Every query is scoped to the selected SchoolGroup or its selected entitlement IDs. Global entitlement definitions, subscription plans, prices, and unrelated workspaces remain unchanged.

Reason:
Preserve entitlement foreign-key integrity while retaining the existing Platform Owner-only test reset guards, transaction rollback, and customer behavior.

Files changed:
Workspace analysis/deletion services, focused Phase 5 regression tests, and KMS sources.

Documentation updated:
AI/master context, project state, change history, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
Minimal scoped dependency fix only. No foreign-key, cascade, entitlement-rule, schema, lifecycle, customer-facing, commit, or push change.

## 2026-07-26 - Test Workspace Reset Subscription-Change Dependency Fix

Area/module:
Platform Owner test workspace/account reset, subscription-change records, and workspace-deletion diagnostics

Previous state:
The controlled test workspace reset deleted scoped operational users before deleting scoped subscription-change requests. A request referencing a workspace user could therefore cause the database to reject the user deletion and roll the transaction back.

New state:
The reset deletes `subscription_change_requests` for the selected `school_group_id` before any selected workspace user is deleted. Pre-analysis now counts the same scoped records, existing structured diagnostics retain their model/table/row-count events, and all deletion work remains inside the existing transaction.

Reason:
Preserve foreign-key integrity while allowing Platform Owners to reset only the selected internal test workspace/account and retain all other workspaces unchanged.

Files changed:
Workspace analysis/deletion services, focused Phase 5 regression tests, and KMS sources.

Documentation updated:
AI/master context, project state, change history, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
Minimal dependency-order fix only. No foreign-key, cascade, schema, lifecycle, customer-facing, commit, or push change.

## 2026-07-25 - Landing CTA Consolidation And Customer Demo Domain Policy

Area/module:
Public landing conversion routes, TIS Account signup/onboarding, customer-demo request policy, and Platform Owner demo visibility

Previous state:
The landing website exposed overlapping conversion labels. Signup did not retain a selected commercial path, and demo duplicate protection applied only to a pending request for one onboarding record rather than an organization domain.

New state:
The landing website exposes Request a Demo and Subscribe Now through environment-configured app URLs with explicit `demo` or `subscribe` intent. The selected intent persists through signup and School Workspace Setup, then is emphasized at commercial choice without preventing a change. Customer Demo eligibility now uses a normalized organization-domain reservation with a database unique invariant. Historical duplicate domains are retained as manual-review reservations; no historical request, workspace, or customer data is merged, deleted, migrated, or reprovisioned.

Reason:
Schools should have two unambiguous public conversion paths, while each organization receives at most one Customer Demo opportunity and retains the same workspace for Demo-to-Paid.

Files changed:
Landing CTA source, SaaS models/services/router/templates, database migration, diagnostic command, focused tests, and KMS sources.

Documentation updated:
AI/master context, project state, user/system flows, database architecture, change history, landing history, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
Approved M8 scope only. No M9 work, payment change, workspace conversion change, provisioning redesign, commit, or push.

## Entry Template

```md
## YYYY-MM-DD - Short Change Title

Area/module:
Previous state:
New state:
Reason:
Files changed:
Documentation updated:
PDF regenerated:
AI project context updated:
Reviewer/approval notes:
```

## 2026-07-25 - M8 Landing Integration Open Account Entry Points

Area/module:
Next.js public landing website, public-to-account routing, and deployment configuration

Previous state:
The public landing website explained TIS and supported demo/early-access conversion, but it did not expose a final M8 Open Account entry point into the deployed TIS Account signup journey.

New state:
The Next.js landing website now has Open Account entry points in the navigation, hero CTA area, and final CTA area. All Open Account links use one shared URL derived from `NEXT_PUBLIC_TIS_APP_BASE_URL` and the existing `/saas/signup` account registration path.

Reason:
M8A and M8B-1 through M8B-6 are already completed in the SaaS application. The final M8 integration step is to let visitors on `tisplatform.com` enter the deployed customer account setup flow without coupling the landing project to the FastAPI app.

Files changed:
- `tis-landing-website/src/app/page.tsx`
- `tis-landing-website/.env.example`
- `tis-landing-website/README.md`
- `.kms-impact.yml`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/landing-page/README.md`
- `docs/history/landing-page/2026-07-25-m8-landing-integration-open-account.md`

Documentation updated:
AI/master context, project state, change history, and landing-page history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
M8 landing integration only. No FastAPI SaaS application, authentication, onboarding backend, Paddle, database, API, demo workflow, provisioning, commercial state, commit, push, or M9 work.

## 2026-07-23 - M8B-6 Demo-To-Paid Workspace Conversion

Area/module:
Customer-demo checkout, provider-confirmed subscription reconciliation, workspace classification, commercial entitlements, demo lifecycle, customer status, and Platform Owner inspection

Previous state:
An activated Customer Demo could not become Customer Paid without risking a second provisioning path or leaving paid commercial evidence disconnected from the existing operational workspace.

New state:
An eligible active Customer Demo can use the existing M7 subscription checkout. After provider-confirmed payment, TIS atomically converts the same SchoolGroup and tenant link to Customer Paid, replaces the demo entitlement with the confirmed subscription-backed paid entitlement, preserves all operational data and history, and exits demo lifecycle processing. Durable conversion state and events support idempotency, audit, and retry after failure.

Reason:
Customers must retain one workspace, tenant identity, organization, branches, users, permissions, and academic history when moving from evaluation to a paid subscription.

Files changed:
Conversion enums/models/migration/service, classification transition validation, demo checkout and lifecycle integration, payment-webhook reconciliation, customer/owner UI, tests, ADR, and KMS.

Documentation updated:
AI/master context, project state, database architecture, module map, flows, roadmap, ADR index/0013, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
M8B-6 only. No tenant reprovisioning, Paddle API redesign, pricing change, demo extension, manual conversion override, internal-sandbox conversion, archive/delete, membership, ownership transfer, commit, or push.

## 2026-07-23 - M8B-5 Standard Customer Demo Lifecycle

Area/module:
Customer-demo lifecycle metadata, resolver, scheduled processing, internal notifications, expiration, operational access enforcement, and owner/customer UI

Previous state:
Activated customer-demo workspaces had no standard duration, reminder, expiration transition, or request-time access gate.

New state:
Customer demos last exactly seven days from activation. Day 6 creates idempotent internal customer and Platform Owner notifications. Day 7 processing atomically ends the demo entitlement and suspends the workspace while preserving tenant data. Operational middleware blocks expired or ambiguous demos across web, API, download, and existing-session requests.

Reason:
Customer demos require a predictable, provider-independent lifecycle that cannot be extended by scheduler delay or stale sessions and never destroys evaluation data.

Files changed:
Demo lifecycle enums/models/migration/service/command, M8B-4 activation metadata, authorization middleware, operational and SaaS UI, lifecycle tests, ADR, and KMS.

Documentation updated:
AI/master context, project state, database architecture, module map, flows, roadmap, ADR index/0012, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
M8B-5 only. No demo-to-paid conversion, Paddle change, email, manual extension, archive/delete, read-only expired mode, special migration, membership, ownership transfer, commit, or push.

## 2026-07-23 - M8B-4 Demo Workspace Provisioning And Activation

Area/module:
Approved SaaS demo requests, operational workspace provisioning, commercial entitlement activation, Platform Console, and customer status

Previous state:
Platform Owner approval created review evidence only. No supported path could create or activate a customer-demo workspace without entering the paid subscription lifecycle.

New state:
Platform Owners can provision an approved, coherent customer-demo request. TIS reuses the shared operational workspace builder, creates an explicit demo entitlement and demo-sourced tenant link, activates the workspace atomically, records provisioning and activation events, and prevents duplicate provisioning. Failures roll back workspace changes while preserving the Approved request and retryable failure details.

Reason:
Approved demos require operational access without fabricating Paddle, payment, or subscription-contract evidence.

Files changed:
Demo provisioning enums, models, migration, service, shared provisioning builder, owner/customer routes and templates, lifecycle display, tests, ADR, and KMS.

Documentation updated:
AI context, master context, project state, database architecture, module map, flows, roadmap, ADR, and SaaS onboarding history.

PDF regenerated:
Yes, through `python scripts/kms.py sync`.

AI project context updated:
Yes.

Reviewer/approval notes:
M8B-4 only. No expiration, reminder, scheduler, login blocking, conversion, suspension workflow, billing/Paddle change, membership, Al-Andalus migration, commit, or push.

## 2026-07-22 - M8B-3 Demo Request Workflow

Area/module:
SaaS onboarding commercial choice, demo request lifecycle, Platform Owner review, audit, and internal notifications

Previous state:
Completed onboarding continued directly to subscription plan selection. TIS had no SaaS-owned review lifecycle for a customer demo request.

New state:
Customers can choose Request Demo or Subscribe Now after onboarding. Demo submission records validated commercial context and starts in Pending Review. Customers can inspect and withdraw pending requests. Platform Owners can search/filter/sort requests and approve, reject with a reason, or cancel. Every action creates durable audit and internal-notification events. Approval records review only and does not provision or activate a workspace.

Reason:
Demo requests need a safe, auditable review boundary before separately approved provisioning work begins.

Files changed:
- SaaS demo enums/models/migration/service, customer and owner routes/templates, Platform Console navigation, and focused regression tests

Documentation updated:
- AI context, master context, project state, database architecture, module map, workflows, roadmap, ADR 0010, and SaaS onboarding history

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
M8B-3 only. No demo provisioning, activation, expiration, email delivery, Paddle change, entitlement enforcement, role change, conversion, membership, schema change outside the new review aggregate, commit, or push.

## 2026-07-22 - M8B-2 Commercial State And Entitlement Foundation

Area/module:
Workspace commercial state, entitlement modeling, branch entitlement resolution, database architecture, and Platform Console

Previous state:
M8B-1 stored workspace classification and lifecycle metadata but had no commercial decision engine, effective workspace entitlement, or branch-level commercial entitlement model.

New state:
Added normalized workspace entitlement envelopes, typed entitlement values tied to the existing catalog, and optional branch inherit/active/inactive records. Added separated read-only validation, workspace entitlement, branch entitlement, and commercial-state services. Paid resolution reuses the confirmed M7 subscription entitlement authority. Platform Owners can inspect effective results without mutation controls.

Reason:
Future demo and paid workflows need one conservative commercial decision foundation before any customer access or lifecycle behavior is changed.

Files changed:
- commercial entitlement enums, SaaS models/migration, four resolver/validation services, Platform Console context/template, and focused regression tests

Documentation updated:
- AI context, master context, project state, database architecture, module map, workflows, roadmap, ADR 0009, and workspace-classification history

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
No M8B-3 workflow, enforcement, demo expiration, Paddle change, customer onboarding change, conversion, membership, role, or Al-Andalus migration is included.

## 2026-07-22 - M8B-1 Workspace Classification Foundation

Area/module:
Workspace identity, SaaS onboarding metadata, provisioning metadata, Platform Console, and database migration tooling

Previous state:
Operational SchoolGroup records had no stable workspace UUID, classification, or dedicated lifecycle metadata. Pending organizations and identities could not express workspace/test intent independently of onboarding, payment, and tenant state.

New state:
Added constrained and indexed workspace UUID/classification/lifecycle fields, onboarding workspace intent, SaaS account purpose, and internal-test operational identity metadata. Added centralized validation and conversion rejection, a commercial-state skeleton with no resolution logic, read-only relationship diagnostics, and a dry-run/default transactional idempotent backfill for all confirmed pre-M8B-1 test records. Platform Owners can inspect the metadata read-only. Provisioning only carries intent into metadata and moves the metadata lifecycle from provisioning to active; existing business gates remain unchanged.

Reason:
Establish the durable classification boundary required by later M8B packages without changing current customer, billing, entitlement, permission, or tenant behavior.

Files changed:
- models, migration, workspace classification services, diagnostic/backfill scripts, provisioning metadata assignment, Platform Console template/context, and focused tests

Documentation updated:
- AI context, master context, project state, database architecture, module map, user/system flows, roadmap, ADR 0008, and workspace-classification history

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
M8B-2 and all later demo/commercial/conversion workflows remain out of scope.

## 2026-07-22 - Corrected Platform Owner Pending Organization Lifecycle Views

Area/module:
SaaS onboarding, provisioning lifecycle, and Platform Owner administration

Previous state:
Platform Console counted every `PendingOrganization` row, and the Pending Organizations page listed every row regardless of completed checkout, active subscription, tenant link, or completed provisioning. Historical `ready_for_checkout` values could therefore make active tenants appear pending, while conflicting completed-provisioning records displayed raw internal statuses without a clear review state.

New state:
One shared lifecycle-aware query now defines the pending queue as draft/setup, review, checkout/payment, or incomplete/recoverable activation work with no tenant link, completed provisioning job, or final tenant billing state. A shared owner lifecycle projection reconciles payment, subscription, contract, tenant-link, provisioning-job, and active SchoolGroup evidence. Coherent active tenants move to retained Organization Records; conflicting completed evidence is labeled Lifecycle Review Required. Platform Console counts/actions and the owner table use the same rule and readable labels.

Reason:
The Platform Owner work queue must represent actionable unfinished onboarding rather than historical database rows, without mutating payment, provisioning, or onboarding evidence.

Files changed:
- centralized SaaS owner lifecycle query and projection
- Platform Console summary and owner admin routes
- pending organization list/detail templates
- focused lifecycle, filtering, count, and access tests
- authoritative KMS context, module map, workflow, project state, and provisioning history

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
No schema, migration, payment, checkout, provisioning transition, permission, production data, commit, or push change. Historical records remain directly accessible.

## 2026-07-22 - Added Phase 7D Navigation And Catalog Enforcement

Area/module:
KMS governance, navigation, catalog, and generated-artifact validation

Previous state:
KMS checks enforced KIA, source coverage, deterministic source ordering, normalized hashes, freshness, PDF identity, and positive increasing `pdf_page` values. They did not require usable titles, constrain catalog taxonomy, validate the KMS navigation guide's targets, or prove that source pages existed within the generated PDF.

New state:
`scripts/kms.py check` now uses a shared approved catalog to validate every included Markdown title, category, and module; requires the normalized manifest inventory to exactly match the generator list; validates every KMS Navigation link as an existing listed Markdown source inside `docs/`; and rejects missing, non-positive, non-integer, non-increasing, or out-of-range PDF pages. Existing KIA, hashes, freshness, ordering, coverage, and artifact checks are unchanged.

Reason:
Phase 7A-7C navigation and catalog conventions must be enforceable through the same local and CI gate that protects KMS synchronization.

Files changed:
- shared KMS catalog vocabulary and path classifier
- ReportLab generator/read-only validation
- focused KMS automation tests
- KMS navigation, policy, automation, repository architecture, project state, and module history
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; first-read product, architecture, workflow, and critical-rule context is unchanged.

Reviewer/approval notes:
Phase 7D only. Knowledge Center UI/routes, application behavior, database, dependencies, `tis.db`, commits, and pushes remain unchanged.

## 2026-07-22 - Added Phase 7C Knowledge Center Navigation

Area/module:
Platform Knowledge Center and KMS navigation

Previous state:
The owner-only Knowledge Center showed manifest sources in one path-focused table. It had no document search, category/module/freshness filters, logical source groups, descriptive summaries, or links to the source document's page in the protected booklet. ADRs were listed by ascending filename, and module-history areas were not ordered by recent activity.

New state:
The Knowledge Center enriches manifest-listed sources with Markdown title and summary metadata, groups them into Core, Engineering, Decisions, History, Marketing, and Supporting sections, and provides client-side search plus category, module, and freshness filters. Document and activity links open the existing owner-protected booklet route at the manifest `pdf_page`. ADRs are newest-first, and module-history areas are ordered by their latest dated entry with entry counts.

Reason:
Platform owners need to locate and consume authoritative knowledge quickly without introducing a database, search service, new route, dependency, or public documentation link.

Files changed:
- `knowledge_service.py` manifest presentation metadata and activity ordering
- `templates/platform_knowledge_center.html` grouped library, client-side search/filters, and protected deep links
- focused Knowledge Center service tests
- Platform Knowledge KMS source and module-history documents
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 7C only. Owner access checks, existing routes, application data, KMS source authority, and generator enforcement remain unchanged. No regenerate control was added.

## 2026-07-21 - Added Phase 7B Professional PDF Navigation

Area/module:
KMS generated booklet and manifest

Previous state:
The booklet was a linear concatenation of source documents with page footers and a source-path list. It had no page-numbered table of contents, source destinations, outline hierarchy, or manifest mapping from Markdown sources to PDF pages.

New state:
The ReportLab generator performs a multi-pass build with a "How to Use This Handbook" page, a real table of contents, stable source-document bookmarks, child bookmarks for H2 major headings, and deterministic named destinations. Every manifest source record includes its starting `pdf_page`, and freshness validation requires positive, strictly increasing page values.

Reason:
The engineering handbook must be practical to navigate as a long-form reference while Markdown remains authoritative and generation stays dependency-light.

Files changed:
- ReportLab PDF generator and focused automation tests
- PDF navigation documentation and engineering-handbook history
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; product architecture, current engineering guardrails, and onboarding order are unchanged.

Reviewer/approval notes:
No Knowledge Center UI, route, database, dependency, application behavior, or source-document ordering change was introduced.

## 2026-07-21 - Added Phase 7A KMS Navigation Foundation

Area/module:
KMS information architecture and developer onboarding

Previous state:
The KMS had complete root and engineering indexes, but they were long manually maintained file lists. Readers had to determine their own document set from 53 Markdown sources, and three supporting documents lacked normalized title metadata.

New state:
`docs/KMS_NAVIGATION.md` provides focused reading paths for new humans, new AI conversations, SaaS onboarding, subscriptions, operational modules, database work, Platform Owner tools, landing work, location data, design, decisions, and review/KIA. Root and engineering indexes now use real Markdown links and delegate task selection to the navigation guide. Missing document titles were normalized.

Reason:
Readers should reach relevant source material quickly without changing the established Markdown, manifest, PDF, or Knowledge Center architecture.

Files changed:
- KMS navigation guide and documentation indexes
- title metadata for three supporting documents
- fixed booklet source list entry for the new authoritative guide
- project state, change history, module history, PDF, and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; its existing first-read role and product/architecture guidance remain current.

Reviewer/approval notes:
Phase 7B catalog/PDF navigation, Phase 7C Knowledge Center changes, and Phase 7D enforcement enhancements were not implemented.

## 2026-07-21 - Added Unified Phase 6 KMS Commands

Area/module:
KMS developer workflow, local automation, CI, and deployment validation

Previous state:
Developers separately ran the PDF generator, artifact freshness check, and KIA impact checker. The repository had all required primitives but no single synchronization command or canonical read-only command shared by local work and CI.

New state:
`scripts/kms.py sync` validates the task KIA before writing, regenerates the PDF and manifest through the existing generator, runs complete post-generation validation, and prints a concise summary. `scripts/kms.py check` delegates to the existing read-only enforcement logic. GitHub pull-request, `dev`, and deployment gates use the unified check command.

Reason:
One reliable command reduces missed mechanical steps while preserving reviewed Markdown as the source of truth and keeping enforcement strict.

Files changed:
- KMS command orchestrator and reusable checker API
- KMS automation tests
- repository instructions and CI workflows
- KMS workflow documentation and generated artifacts

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
The command never rewrites authoritative Markdown and does not change application behavior or production data.

## 2026-07-21 - Aligned Push Enforcement With KIA Task Boundaries

Area/module:
GitHub Actions and KMS impact validation

Previous state:
Pull-request enforcement validated the full feature branch against its base, while push enforcement validated only `github.event.before...github.sha`. A follow-up fix commit therefore evaluated a cumulative `.kms-impact.yml` against only the latest commit and incorrectly reported previously updated KMS files as unchanged.

New state:
Pull requests validate the pull-request base SHA against the actual pull-request head SHA. Pushes to `dev` find the merge base between the repository default branch and the pushed head, then validate that complete task range. Both events apply the unchanged strict declaration and generated-artifact checks to the same logical implementation boundary.

Reason:
KIA declarations describe approved implementation tasks, which may contain multiple commits. Event delivery boundaries must not redefine those tasks.

Files changed:
- KMS impact checker
- KMS enforcement workflow
- KMS automation regression tests
- KMS governance documentation and generated artifacts

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; product architecture, developer onboarding order, and application behavior are unchanged.

Reviewer/approval notes:
Enforcement remains strict across the complete task diff. No application behavior or production data changed.

## 2026-07-21 - Made KMS Enforcement Cross-Platform Deterministic

Area/module:
Repository KMS generation, freshness validation, and CI enforcement

Previous state:
Markdown source hashes used raw checkout bytes, and dynamically discovered ADR and history sources used native `Path` ordering. A Windows checkout with CRLF line endings could generate a manifest that passed locally but failed on GitHub Linux, where the same committed text used LF and path ordering differed.

New state:
Markdown is decoded as UTF-8, normalized to LF, and then hashed. Source paths are normalized to repository-relative POSIX paths, dynamic sources use a stable case-insensitive ordering with a deterministic tie-breaker, and source comparison still rejects missing, unexpected, duplicate, or reordered entries. Git diff inspection now includes deleted files.

Reason:
KMS enforcement must evaluate committed content consistently across developer workstations and GitHub Actions without weakening freshness or source-coverage checks.

Files changed:
- KMS generator and impact checker
- Knowledge Center freshness hashing helper
- KMS automation tests and line-ending attributes
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
No; onboarding, architecture, product behavior, and current priorities are unchanged.

Reviewer/approval notes:
Repository-governance correction only. No application behavior, production data, SaaS flows, database, or migrations changed.

## 2026-07-21 - Added Automatic KMS Synchronization Enforcement

Area/module:
Repository governance, KMS automation, CI, deployment gate, and AI workflow

Previous state:
KMS updates depended on developers and AI assistants remembering the written KIA policy. PDF/manifest generation was manually triggered, the Knowledge Center detected stale hashes only when viewed, and no test, commit, pull-request, or deployment gate blocked stale or missing documentation.

New state:
Root `AGENTS.md` makes KMS onboarding mandatory. `.kms-impact.yml` records task-level impact. `scripts/check_kms_impact.py` compares declarations with Git changes, conservatively classifies major paths, validates declared Markdown, and invokes generated-artifact checks. The PDF generator has read-only `--check` mode and manifest PDF hashes. GitHub Actions enforce checks on pull requests and `dev`, and `master` deployment depends on the same gate. Automation never rewrites Markdown.

Reason:
Major TIS work must not be mergeable or deployable while engineering knowledge is stale, while reviewed Markdown must remain authoritative and free from runtime/customer data.

Files changed:
- `AGENTS.md`
- `.kms-impact.yml`
- `.github/pull_request_template.md`
- `.github/workflows/kms-enforcement.yml`
- `.github/workflows/deploy-on-master.yml`
- `scripts/check_kms_impact.py`
- `scripts/generate_docs_pdf.py`
- `tests/test_kms_automation.py`
- relevant KMS Markdown and generated artifacts

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Repository-governance automation only. No application behavior, production/customer/tenant/billing data, runtime records, database, migrations, or business logic changed.

## 2026-07-20 - Backfilled Completed M7 Subscription Management

Area/module:
SaaS entitlements, subscription portal, quantity/plan changes, cancellation, billing history, invoices, Paddle webhooks, and reconciliation

Previous state:
Module history covered M7 Phases 1, 2, 3, and 6 only. Central project state, architecture maps, workflows, roadmap, change history, PDF, and manifest still described the pre-M7 billing foundation; Phases 4 and 5 and reconciliation protections were absent.

New state:
KMS records the completed M7 entitlement foundation, read/write customer portal, paid branch quantity management, upgrades and scheduled downgrades, provider-authoritative proration, cancellation/reversal, centralized lifecycle and allowed-action policy, provider billing history, protected invoice downloads, and fail-closed webhook/reconciliation safeguards.

Reason:
The engineering handbook must describe current implemented subscription behavior before automatic enforcement becomes authoritative.

Files changed:
- central KMS context/state files
- subscription and payment ADRs
- engineering module, repository, database, flow, and roadmap docs
- subscription module history
- generated PDF and manifest

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Documentation backfill only; it records already committed M7 behavior and introduces no SaaS behavior change.

## 2026-06-30 - Paddle Initial Checkout Price Mapping Configuration

Area/module:
SaaS subscriptions, Paddle initial checkout configuration, tests, and KMS documentation

Previous state:
The checkout launch flow safely blocked when the selected subscription plan price did not have `subscription_plan_prices.provider_price_id` configured, but there was no structured mapping sync process and the customer-facing error could expose provider configuration wording.

New state:
Added a script-based Paddle price ID sync process using structured sandbox/production mapping examples. The database remains the source of truth through `subscription_plan_prices.provider_price_id`, real mapping files are ignored, and missing provider price IDs now surface a customer-safe Secure Payment support message while internal diagnostics retain plan code, billing interval, and currency details.

Reason:
Initial subscription checkout needs environment-specific Paddle provider price IDs without hardcoding live IDs in source or changing payment state behavior.

Files changed:
- `.gitignore`
- `scripts/sync_paddle_price_ids.py`
- `config/paddle/paddle_prices.sandbox.example.json`
- `config/paddle/paddle_prices.production.example.json`
- `saas/payment_service.py`
- `saas/router.py`
- `tests/test_paddle_price_sync.py`
- `tests/test_saas_phase1.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/subscriptions/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Initial checkout configuration only. No proration, upgrade, downgrade, cancellation, payment state transition, webhook, provisioning behavior, database schema, migration, operational module, landing website, OAuth, internal route rename, live Paddle ID hardcoding, commit, or push was performed.

## 2026-06-27 - Accepted Subscription And Workspace Activation Guided Journey Phase 3C

Area/module:
Subscription Selection, Secure Payment summary, Payment Return/Cancel, Subscription Status, Workspace Activation status, tests, and KMS documentation

Previous state:
The subscription, secure payment, billing status, payment return/cancel, and workspace activation pages were functionally correct but still used page-local CTAs, dense status blocks, and inconsistent guidance. Browser return messaging existed but was not part of the shared guided setup experience.

New state:
Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages now use the Phase 3A shared setup shell and Phase 3B guided page style. Each page has one shared-shell primary CTA, customer-safe status labels, concise supporting cards, clear browser-return guidance, and explicit messaging that TIS Platform access becomes available after Workspace Activation.

Reason:
The accepted Phase 3C scope required making subscription/payment/activation pages feel like one guided customer journey while preserving payment, billing, provisioning, webhook, checkout start/launch, database, and operational behavior.

Files changed:
- `saas/router.py`
- `templates/saas/plan_selection.html`
- `templates/saas/checkout_summary.html`
- `templates/saas/checkout_return.html`
- `templates/saas/checkout_cancel.html`
- `templates/saas/account_billing.html`
- `templates/saas/billing_status.html`
- `tests/test_saas_phase1.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 3C customer-facing subscription/payment/status redesign only. No payment behavior change, billing behavior change, provisioning behavior change, webhook logic change, checkout start/launch behavior change, database schema change, migration, operational module change, Next.js landing website change, OAuth change, internal `/saas` route rename, stored-status change, admin view change, commit, or push was performed.

## 2026-06-27 - Accepted School Workspace Setup Guided Wizard Phase 3B

Area/module:
School Workspace Setup onboarding templates, shared SaaS customer shell, onboarding setup context, tests, and KMS documentation

Previous state:
The five onboarding pages used functional but dense form layouts with repeated progress notices, mixed card styles, and page-local primary actions. Branch setup felt like repeated blank blocks, organization logo upload was plain, and the review page felt like a basic summary rather than a confident handoff to Subscription Selection.

New state:
Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup now use a consistent guided enterprise setup wizard style on top of the Phase 3A shared shell. Each page has one shared-shell primary CTA, secondary Back/Save Draft actions, grouped form sections, concise guidance, cleaner spacing, a more premium logo upload area, compact branch panels, and a stronger review summary.

Reason:
The accepted Phase 3B scope required redesigning only the School Workspace Setup onboarding pages while preserving all business logic, routes, field names, validation, draft behavior, payment, billing, provisioning, database, and operational boundaries.

Files changed:
- `saas/router.py`
- `templates/saas/base.html`
- `templates/saas/onboarding_organization.html`
- `templates/saas/onboarding_branches.html`
- `templates/saas/onboarding_academic_setup.html`
- `templates/saas/onboarding_contacts.html`
- `templates/saas/onboarding_review.html`
- `tests/test_saas_phase1.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 3B onboarding page redesign only. No backend business logic change, route rename, form field rename, validation change, onboarding progression change, draft behavior change, payment behavior change, billing behavior change, provisioning behavior change, database schema change, migration, operational module change, Next.js landing website change, OAuth change, commit, or push was performed.

## 2026-06-27 - Accepted TIS Account Guided Setup Framework Phase 3A

Area/module:
TIS Account customer dashboard, shared SaaS customer shell, setup journey display helper, and KMS documentation

Previous state:
The customer account page still behaved like a dense dashboard with statistics, session details, multiple competing actions, and page-specific journey fragments. The shared customer shell had a logo and onboarding-specific progress UI, but it did not yet provide a reusable 8-step guided setup framework.

New state:
The shared customer shell supports a guided setup console for pages that pass setup context. The TIS Account page now presents an official-logo guided console with an 8-step journey stepper, current-step/status area, one primary next action, concise account/workspace context, and guidance that TIS Platform access becomes available after Workspace Activation. Journey state is calculated from existing account, onboarding, billing, payment, and activation data without changing stored statuses.

Reason:
The accepted Phase 3A scope required only the shared framework and account page foundation for a professional TIS Account / School Workspace Setup experience, while leaving full onboarding and payment page redesigns for later phases.

Files changed:
- `saas/router.py`
- `saas/service.py`
- `templates/saas/base.html`
- `templates/saas/account.html`
- `tests/test_saas_phase1.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 3A shared framework only. Onboarding forms, subscription/payment pages, billing/status pages, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, admin views, commits, and pushes were not changed.

## 2026-06-27 - Accepted TIS Account Customer-Facing Wording And Logo Cleanup

Area/module:
SaaS customer account pages, school workspace setup pages, billing/subscription status views, transactional account emails, and KMS documentation

Previous state:
Customer-facing TIS Account and school workspace setup pages could display internal or technical language such as SaaS-oriented product copy, raw status labels, checkout/payment internals, provider identifiers, tenant/provisioning terms, or account setup labels that were less polished. The shared customer account shell did not consistently present an official TIS logo image across inherited customer forms/pages.

New state:
Customer-facing account/setup pages use professional labels such as TIS Account, Account Dashboard, School Workspace Setup, Organization Profile, Branch Setup, Academic Setup, Subscription Setup, Secure Payment, and Workspace Activation. Customer views use display labels for internal statuses and hide customer-irrelevant provider transaction/subscription IDs, attempt UUIDs, checkout session internals, plan IDs, and school group IDs. The shared customer account shell uses the official full-color horizontal TIS logo, and transactional TIS Account emails use an existing official dark-blue TIS wordmark asset.

Reason:
The accepted Phase 2 plan required a focused customer-facing wording cleanup and official logo usage pass before any larger account setup UI redesign.

Files changed:
- `saas/router.py`
- `saas/service.py`
- `saas/provisioning_service.py`
- `email_templates.py`
- `templates/saas/base.html`
- `templates/saas/signup.html`
- `templates/saas/login.html`
- `templates/saas/account.html`
- `templates/saas/account_billing.html`
- `templates/saas/billing_status.html`
- `templates/saas/onboarding_organization.html`
- `templates/saas/onboarding_branches.html`
- `templates/saas/onboarding_academic_setup.html`
- `templates/saas/onboarding_contacts.html`
- `templates/saas/onboarding_review.html`
- `templates/saas/plan_selection.html`
- `templates/saas/checkout_summary.html`
- `templates/saas/checkout_return.html`
- `templates/saas/checkout_cancel.html`
- `templates/saas/profile.html`
- `templates/saas/security.html`
- `templates/saas/sessions.html`
- `tests/test_saas_phase1.py`
- `tests/test_saas_phase5.py`
- `tests/test_email_templates.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 2 implementation only. No Phase 3 UI redesign, Google/Microsoft login, internal route/module rename, payment behavior change, billing behavior change, provisioning behavior change, database schema change, migration change, operational module change, Next.js landing website change, commit, or push was performed.

## 2026-06-27 - Accepted TIS Account Email Verification Recovery

Area/module:
SaaS onboarding, TIS Account email verification, verification resend recovery, and school workspace setup gate

Previous state:
Valid verification links rendered a static verification page instead of continuing the customer toward account setup. Expired or invalid verification links could feel like a dead end. Resend verification existed but did not provide a fully professional recovery path for expired links, already verified accounts, and unknown emails. Password-based accounts that were still pending verification could sign in and reach account/setup routes.

New state:
Valid verification links mark the account email verified/active and redirect to the TIS Account login page with a professional success notice. Expired or invalid links show a recovery page with a resend option. Resend verification safely handles unverified accounts, already verified accounts, and unknown-email cases without revealing account existence. Unverified password-based accounts are blocked from starting or continuing school workspace setup. New visible wording in this verification flow uses "TIS Account" and "school workspace setup".

Reason:
Testing showed that the customer account setup journey could be blocked after email verification, especially when a verification link expired or the customer needed to recover/resend the link.

Files changed:
- `saas/router.py`
- `saas/service.py`
- `templates/saas/login.html`
- `templates/saas/verify_email.html`
- `templates/saas/verification_sent.html`
- `email_templates.py`
- `tests/test_saas_phase1.py`
- `tests/test_saas_phase5.py`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/saas-onboarding/README.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Phase 1 verification recovery implementation accepted. Phase 2 wording cleanup, Phase 3 setup UI redesign, Google/Microsoft login, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, and the Next.js landing website were not changed. No commit or push was performed.

## 2026-06-27 - Added Production Memory Stability Guardrails

Area/module:
Operational app stability, observations, global location lookup, Render deployment constraints, and engineering standards

Previous state:
Production traffic could hit avoidable memory pressure. The observations page included diagnostic stage logging and extra template rendering in the normal request path, and the global location picker could parse a 47 MB reference dataset into a complete in-memory index for simple picker requests. KMS standards did not yet explicitly forbid unbounded caches, duplicate production template renders, or normal-request diagnostic warning spam.

New state:
The local stabilization patch gates observation diagnostics behind `TIS_OBSERVATION_DIAGNOSTICS`, removes duplicate observation template pre-renders, and changes location lookup behavior to use streaming/scoped country loading for normal country, region, city, and validation requests. KMS now documents strict production memory and Render stability rules.

Reason:
Render logs showed app restarts and user-facing 502s around normal app navigation after deployment. A 512 MB service can be enough for TIS only if the app avoids unnecessary full-dataset memory loads, duplicate rendering, and production debug noise.

Files changed:
- `location_service.py`
- `routers/observations.py`
- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/PROJECT_STATE.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/engineering-handbook/2026-06-27-production-memory-stability-guardrails.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Local changes only. No commit, push, migration, database change, SaaS route change, billing change, tenant logic change, or deployment was performed.

## 2026-06-26 - Completed KMS v3.0 Phase 3D Lifecycle Foundation

Area/module:
Knowledge Management System and engineering handbook

Previous state:
KMS v3.0 Phase 3C documented rejected decisions, visual documentation framework, AI optimization, governance, and traceability. It still needed a complete self-evolving lifecycle standard that ties implementation, validation, KIA, documentation updates, generated artifacts, review, commit, push, and deployment together.

New state:
TIS now has final Phase 3D docs for knowledge lifecycle, documentation automation, KIA standard, self-evolving workflow, documentation dependency map, AI coding workflow, and future automation roadmap. This completes the KMS v1.0 lifecycle foundation.

Reason:
Ensure every future approved implementation naturally keeps KMS synchronized without relying on uncontrolled app-side rewriting of source docs.

Files changed:
- `docs/engineering/KNOWLEDGE_LIFECYCLE.md`
- `docs/engineering/DOCUMENTATION_AUTOMATION.md`
- `docs/engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md`
- `docs/engineering/SELF_EVOLVING_WORKFLOW.md`
- `docs/engineering/DOCUMENTATION_DEPENDENCY_MAP.md`
- `docs/engineering/AI_CODING_WORKFLOW.md`
- `docs/engineering/FUTURE_AUTOMATION_ROADMAP.md`
- `docs/engineering/README.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/engineering-handbook/2026-06-26-kms-v3-phase-3d-lifecycle-foundation.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3D final phase only. SaaS flows, landing page code, database models, migrations, `tis.db`, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added KMS v3.0 Phase 3C Governance And AI Traceability

Area/module:
Knowledge Management System and engineering handbook

Previous state:
KMS v3.0 Phase 3B documented database architecture, development standards, UI/UX design philosophy, roadmap, and stronger onboarding guidance. It did not yet preserve rejected decisions, visual documentation standards, a definitive AI optimization guide, project governance, or explicit decision traceability.

New state:
TIS now has Phase 3C engineering docs for rejected decisions, visual documentation framework, AI optimization, project governance, and decision traceability. The PDF generator includes these docs.

Reason:
Future developers and AI assistants need to understand why TIS became what it is, not only what currently exists.

Files changed:
- `docs/engineering/REJECTED_DECISIONS.md`
- `docs/engineering/VISUAL_DOCUMENTATION_GUIDE.md`
- `docs/engineering/AI_OPTIMIZATION_GUIDE.md`
- `docs/engineering/PROJECT_GOVERNANCE.md`
- `docs/engineering/README.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `docs/history/engineering-handbook/2026-06-26-kms-v3-phase-3c-governance-ai-traceability.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3C only. App behavior, SaaS flows, landing page code, database, migrations, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added KMS v3.0 Phase 3B Engineering Layers

Area/module:
Knowledge Management System and engineering handbook

Previous state:
KMS v3.0 Phase 3A added module map, repository architecture, user/system flows, and onboarding structure. The handbook still needed database architecture, development standards, UI/UX philosophy, roadmap, and stronger human/AI guidance.

New state:
TIS now has Phase 3B engineering docs for database architecture, development standards, UI/UX design philosophy, and product roadmap. Core KMS docs and AI onboarding guidance reference these layers, and the PDF generator includes them.

Reason:
Make the generated booklet more useful for new senior developers, Codex conversations, ChatGPT conversations, and future technical reviewers.

Files changed:
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`
- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md`
- `docs/engineering/PRODUCT_ROADMAP.md`
- `docs/engineering/README.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3B only. App behavior, SaaS flows, landing page code, database, migrations, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added KMS v3.0 Engineering Handbook

Area/module:
Knowledge Management System and engineering onboarding

Previous state:
The generated booklet included KMS source documents, ADRs, module history, AI context, and the Knowledge Center foundation, but it did not fully onboard a new human developer or future Codex/ChatGPT conversation into TIS modules, repository architecture, and end-to-end flows.

New state:
TIS now has an engineering handbook layer with a complete module map, repository architecture guide, user/system flow guide, and engineering onboarding index. The PDF generator includes these docs and emits documentation version 3.0.

Reason:
Make the generated booklet a true TIS Engineering Handbook rather than only a documentation bundle.

Files changed:
- `docs/engineering/README.md`
- `docs/engineering/TIS_MODULE_MAP.md`
- `docs/engineering/REPOSITORY_ARCHITECTURE.md`
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for KMS v3.0 Phase 3A only. App behavior, SaaS flows, landing page code, database, migrations, routes, commits, and pushes remain out of scope.

## 2026-06-26 - Added Platform Owner Knowledge Center

Area/module:
Platform Knowledge Center and KMS access

Previous state:
TIS had KMS source docs, ADRs, module history, a generated PDF booklet, and a manifest, but no protected in-app owner page for KMS status or booklet access.

New state:
TIS now has a read-only Platform Owner Knowledge Center with KMS health score, manifest metadata, freshness detection, source document status, coverage checks, latest change-history entries, ADR list, module history areas, KIA checklist, and protected PDF view/download routes.

Reason:
Platform owners need an internal utility for verifying KMS health and accessing the generated PDF without exposing direct public static links.

Files changed:
- `knowledge_service.py`
- `main.py`
- `templates/platform_knowledge_center.html`
- `templates/platform_console.html`
- `scripts/generate_docs_pdf.py`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `docs/CHANGE_HISTORY.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/history/platform-knowledge/README.md`
- `docs/history/platform-knowledge/2026-06-26-platform-owner-knowledge-center.md`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for Phase 2C only. Regenerate button, SaaS changes, database changes, migrations, landing page changes, commits, and pushes remain out of scope.

## 2026-06-26 - Established Knowledge Management System Foundation

Area/module:
Documentation and project knowledge management

Previous state:
TIS had Phase 1 documentation source files and a generated PDF booklet, but no formal change history, ADR system, module history foundation, KMS policy, manifest, or compact AI onboarding file.

New state:
TIS now has a Knowledge Management System foundation with chronological change history, documentation update policy, ADR structure and initial accepted ADRs, module history folders, AI project context, updated source docs, and an expanded PDF generator.

Reason:
Preserve project knowledge for future human developers, Codex conversations, ChatGPT conversations, project owners, platform owners, and technical reviewers.

Files changed:
- `docs/CHANGE_HISTORY.md`
- `docs/DOCUMENTATION_UPDATE_POLICY.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/adr/README.md`
- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0002-separate-saas-identity-and-operational-users.md`
- `docs/adr/0003-paddle-payment-architecture.md`
- `docs/adr/0004-webhook-only-payment-confirmation.md`
- `docs/adr/0005-delayed-tenant-provisioning-after-verified-payment.md`
- `docs/adr/0006-documentation-as-source-knowledge-management-system.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`
- `docs/history/README.md`
- `docs/history/*/README.md`
- `docs/history/provisioning/2026-06-26-kms-foundation.md`
- `docs/TIS_MASTER_CONTEXT.md`
- `docs/PROJECT_STATE.md`
- `docs/README.md`
- `scripts/generate_docs_pdf.py`
- `static/docs/TIS_Project_Reference_Booklet.pdf`
- `static/docs/docs_manifest.json`

Documentation updated:
Yes

PDF regenerated:
Yes

AI project context updated:
Yes

Reviewer/approval notes:
Approved for Phase 2A and Phase 2B only. Platform Owner Knowledge Center, app routes, SaaS flows, database, migrations, landing page implementation, commits, and pushes remain out of scope.
