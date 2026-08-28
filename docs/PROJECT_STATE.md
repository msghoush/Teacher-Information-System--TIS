---
title: TIS Project State
documentation_version: 3.3
last_updated: 2026-08-26
source_of_truth: true
---

# TIS Project State

## Subject Distribution Rules Generation Wiring Implemented

The resolved Subject Distribution Rule (section over grade over branch
default, `None` for legacy fallback) is now embedded per Planning demand in
the schema-v3 snapshot at creation time; a later rule change never alters an
already-created snapshot. The problem builder carries the resolved rule per
demand, exposes true physical period adjacency per slot, and runs the
arithmetic/feasibility validator as a final pre-solve defense
(`distribution_rule_invalid`). CP-SAT enforces exact non-overlapping
intentional blocks, generalized daily-coverage/spread/max-per-day/
min-teaching-days behavior (hard only when explicitly configured hard), and
exempts declared blocks from the consecutive-avoidance penalty; demands
without a resolved rule keep the exact legacy `quality_rules_json` behavior.
The independent validator mirrors every new hard check. Readiness blocks
genuinely invalid/infeasible normalized configurations while keeping the
existing legacy warning path. Regeneration's `ceil(25% x unlocked placements)`
default, locks, and teacher authority are unchanged; hard distribution rules
remain enforced during regenerate through the same constraint-building path.

## Subject Distribution Rules Foundation Implemented

Migration `20260828_003_subject_distribution_rules_foundation` adds the normalized
`subject_distribution_rules` table (branch/grade/section scope, block/single counts,
min teaching days, max periods per day, daily-coverage/spread/consecutive
preferences, min day gap, hard/soft strictness). `subject_distribution_rules.py`
resolves section-then-grade-then-branch-default precedence with field-level
inheritance and returns `None` for legacy fallback when nothing is configured.
`subject_distribution_validator.py` independently checks the Planning-weekly-total
arithmetic and day/period feasibility. `timetable_slot_service.py` now marks true
physical period adjacency (false across a Break, Prayer, or other non-teaching
item) so a later intentional-block feature can rely on genuine continuity. No
existing solver, validator, readiness, or settings-UI behavior changed, and
`quality_rules_json` remains the active authority for every tenant.

## Smart Timetable Academic Scheduling Quality Implemented

Timetable Settings persist branch/year subject-code mappings and grouped Swimming
configuration through migration
`20260828_002_smart_timetable_academic_quality_rules`. Immutable snapshots, problem
construction, CP-SAT, and independent validation share the normalized authority for
core daily coverage, short-demand spread, ICT daily limits, grouped synchronization,
teacher/resource safety, and configurable regeneration diversity.

## On-Demand Timetable Generation Workflow Implemented

Generate and Regenerate still create the Stage 5.1 durable PostgreSQL run and
immutable snapshot, then the web service dispatches only its public ID to a registered
Render Workflow task. The task reuses the single-run solver/validator/persistence
pipeline, keeps leases, heartbeats, cancellation, staleness, and atomic result guards,
and exits. Duplicate task starts are no-ops after claim or completion. Immediate
dispatch failure safely terminates an unclaimed run and delayed start receives an
honest waiting message. Render retries are explicitly disabled; Generate Again is
the retry authority. No schema or solver behavior changed, and the polling worker is
optional/local only rather than a production service.

## Smart Timetable Stage 5.2 Simplified Workflow Implemented

The manager workspace now emphasizes Create New Timetable, one current Draft
Timetable, readiness, Generate or Regenerate, Approve Draft, and Publish Timetable.
Generation creates an unapproved draft. Approval records the reviewing administrator
only after exact-version validation, every content or authority change invalidates
approval, and publication revalidates before changing the active pointer.
Regenerate, Approve Draft, and Publish Timetable now occupy one primary Draft workflow
area; History retains destructive and technical version actions.
Technical lifecycle controls and permanent unpublished cleanup are secondary
Timetable History features. Draft deletion uses `timetable.delete_versions` and
permanently removes eligible never-published versions without moving the active pointer;
historical archive remains a separate History-only action.

Published-only `/my-timetable` and `/published-timetable` views resolve exclusively
from `TimetableActiveVersion`. My Timetable fails closed without exact-scope teacher
identity and filters to that teacher. `timetable.view`-only users are redirected away
from management. Migration `20260828_001_smart_timetable_stage52_draft_approval`
adds nullable approval timestamp and actor provenance; solver behavior is unchanged.

## Smart Timetable Stage 5.1 Generator Implemented

Authorized administrators can queue Generate or Regenerate from a
`generation_ready` timetable. A separate OR-Tools CP-SAT execution environment uses immutable
schema-v3 input, durable lease/heartbeat/recovery state, exact demand and collision
constraints, Planning/HRT teacher authority, canonical teaching slots, and fixed
locks. A solver-independent validator and final fingerprint/source-revision check
gate atomic creation of one unpublished `publication_ready` version. Regeneration
keeps its source unchanged and enforces the approved unlocked-lesson difference.
The default regeneration difference is 25 percent of unlocked source placements,
rounded up. Infeasible diversity is reported explicitly without weakening hard rules.
The active/published pointer is never changed by generation.

Migration `20260822_001_smart_timetable_stage51_generator` adds progress, attempts,
cancellation audit, worker-claim indexing, and one-active-run-per-scope enforcement.
The page polls real phases and recovers active work after reload. Stage 5.2 UX and
teacher visibility are implemented as documented above.

## Smart Timetable Stage 3.5 Composed Timeline Implemented

The timetable now derives every day from one canonical composer: shift start,
teaching-period count/duration, and applicable inserted blocks. After-period blocks
are first-class; boundary-aligned legacy fixed times remain compatible and ambiguous
overlaps block readiness/assignment. Calculated end time, previews, timetable rows,
snapshots, staleness fingerprints, and exports share the same projection. Migration
`20260821_001_smart_timetable_stage35_composed_timeline` adds placement mode,
after-period boundary, and duration metadata without rewriting legacy times. The
timeline is now consumed by Stage 5.1; availability and room/resource models remain absent.

## Smart Timetable Stage 4 Version Publication Implemented

Administrators can review scoped version history, explicitly open historical
versions, copy immutable versions to drafts, lock/unlock draft lessons, validate a
specific draft, compare two same-scope versions, archive drafts/superseded history,
export the selected version, and publish a complete fresh publication-ready draft.

Publication is one transaction using version row locking, `edit_revision`, active
pointer locking/revision, current fingerprint revalidation, and full
solver-independent validation. The former active version becomes superseded and
remains reviewable/exportable; the new active version is immutable. Stage 3 Ready to
Generate remains a separate input-readiness concept. Stage 5.1 now supplies the solver.

## Smart Timetable Stage 3 Readiness Implemented

Stage 3 adds one deterministic canonical projection for fixed teaching periods,
full-period unavailability, between-period display blocks, and invalid partial
overlaps. The projection drives UI availability, assignment validation, snapshots,
exports, and the future solver boundary without shifting period times.

`TimetableReadinessService` evaluates one explicit organization/branch/year scope
against configuration, Planning demand/allocation, HRT, authoritative teacher
capacity, slot sanity, locks, and staleness. Only `generation_ready` is ready, and
it means inputs are coherent enough to attempt solving—not that a feasible global
timetable is guaranteed. No solver or Generate endpoint exists.

## Smart Timetable Stage 2 Version Foundation Implemented

ADR 0026 Stage 2 is implemented. Timetable placements now belong to durable,
SchoolGroup/Branch/Academic-Year-scoped versions with deterministic input
snapshots, a separate exact-scope active pointer, lock metadata, version-scoped
collision guarantees, and a future generation-run record. Migration
`20260819_002_smart_timetable_stage2_version_foundation` imports each populated
legacy timetable exactly, creates one compatibility active version, records safe
staleness evidence without repairing placements, and skips empty settings-only
scopes.

The legacy assignment route remains usable through copy-on-write: its first edit
creates a mutable working draft from the immutable active version. Current views
and XLSX/PDF exports resolve the operational version. Stage 2 adds no solver,
worker, Generate/Regenerate endpoint, generation UI, room/resource authority,
availability rules, or new teacher-capacity authority. Structural readiness and
solver execution remain later stages.

## Capacity-Based Packaging Implemented

ADR 0025 is implemented. Nine normal customer entitlement keys are identical for
Starter, Professional, and Enterprise AI. Paid, promo, and active demo workspaces
resolve those features through one source-aware permission/scope/commercial
decision. Advanced Reporting allocation exports now follow this path. The report
generators and calculations are unchanged.

Migration `20260819_001_capacity_based_customer_feature_baseline` updates plan
values and compatible legacy flags, repairs only currently active promo feature
values, and reconciles active demo baseline policy. It does not change capacity,
priority support, Paddle/payment evidence, immutable promo records, or expired
authority. AI availability is common; demo allowances and future provider limits
resolve through a separate consumption-policy boundary.

## Stage 5 SchoolGroup Boundary Correction Complete

Operational SchoolGroup create/delete actions now require both Platform identity and
global SchoolGroup-management capability. Tenant create/delete permissions were
removed from role defaults, direct stale-permission requests fail before side
effects, and tenant SchoolGroup updates are constrained to the linked workspace.
School Management now presents paid and promo branch capacity from unified
commercial authority, while existing locked mutation enforcement is unchanged. The
individual last-active-branch rule is SchoolGroup-scoped. A sanitized, read-only
PostgreSQL provenance audit is available for later Platform Owner review; no
production audit or remediation has been run.

## Existing Workspace Controlled Conversion

M4B is implemented. Migration
`20260806_001_existing_workspace_controlled_conversion` adds the conversion
operation/event ledger, tenant-profile legal name, append-only event guards,
and a partial unique tenant-owner link constraint with duplicate preflight.
The generic dry-run-first CLI requires exact workspace, owner, M4A hash,
operation, idempotency, and actor parameters; write preparation and final
conversion require explicit phrases and PostgreSQL.

The normal TIS registration and email-verification flow establishes the owner
identity. A verified owner then claims the prepared operation and completes
only legal name, controlled IANA timezone, and educational program. Final
conversion re-audits under row locks, detects branch/dependency or commercial
drift, preserves every branch and operational record, ends internal sandbox
authority, and leaves the customer workspace in coherent `activation_required`
state with no active entitlement or tenant source. Organization Account and M3
promo activation remain available; direct operations and existing-workspace
Paddle activation remain unavailable. No production conversion has been run.

## Existing Workspace Conversion Audit Foundation

M4A is implemented as a read-only prerequisite to any legacy internal-sandbox
conversion. `saas/existing_workspace_conversion_audit_service.py` resolves an
explicit workspace/owner tuple, inventories ownership and commercial evidence,
and traverses reflected branch dependencies without modifying the session.
`scripts/audit_existing_workspace_conversion.py` requires PostgreSQL, starts a
repeatable-read read-only transaction, emits deterministic sanitized JSON or
text with a stable SHA-256 snapshot, and always rolls back. Exit codes separate
coherent (`0`), execution failure (`1`), manual review (`2`), and workspace
identity mismatch (`3`). Reflected model drift, soft-deleted dependencies,
owner conflicts, and paid/demo/promo evidence fail closed. Archival candidate
IDs are emitted only for active branches proven dependency-free.

No target-specific identifier exists in reusable service or CLI logic. No branch,
account, owner, classification, lifecycle, entitlement, tenant link, approval,
Paddle, email, or production data is changed. M4A grants neither hard-delete
approval nor write-conversion authority; those remain later milestones.

## Promo Redemption And Organization Activation

M3 is implemented. Verified organization owners can apply an approved promo
from the post-onboarding commercial choice or an eligible existing Organization
Account. Activation is resumable and idempotent, uses HMAC lookup without
persisting the raw code, and commits the redemption, immutable grant,
entitlement, branch assignments, tenant source, lifecycle, and durable audit as
one transaction.

Promo-backed workspaces use classification `customer`, lifecycle `active`, and
M1 source `promo_grant`. Access is limited to selected active branch
entitlements and expires from the persisted grant window. Existing aligned
organizations need no `PendingOrganization`; onboarding organizations continue
through the shared workspace builder. Staff/teacher excess blocks without
mutation. Internal sandboxes, incompatible sources, ambiguous links, and
expired grants fail closed. No Paddle or billing object is created.

Promo activation now writes explicit branch evidence for the complete preserved
workspace inventory: selected branches are assigned and active, while unselected
branches are explicitly inactive even when their operational status is inactive.
Individual and bulk branch reactivation enforce grant capacity and update the
operational branch, assignment, and entitlement in one transaction. A generic
PostgreSQL reconciliation CLI defaults to dry-run and may create only safely
attributable missing inactive evidence; contradictory chains remain manual review.

Organization Account Billing & Subscription now selects its presentation from the
authoritative commercial source. Promo-backed customers receive a first-class
Commercial Access page showing their immutable grant plan and period, safe active or
expired status, masked promo reference, and M1-resolved branch, system-user, and
teacher capacity. Paid subscription and demo pages remain separate. Operational promo
access now ends exactly at `effective_to`; grace days are represented as recovery only
and do not authorize tenant operations.

Expired and recovery-period promo workspaces can continue with a paid subscription
through M4C existing-workspace activation. Promo authority is unchanged until a
verified completed Paddle transaction. Completion reuses the tenant and atomically
ends promo entitlement authority, relinks the existing tenant source to the paid
contract, establishes paid workspace and branch entitlements, and retains promo
history. Active promos cannot convert early. A shared source/plan/status badge now
identifies Promo, Demo, and Paid authority in Organization Account and the detailed
commercial page. The normal operational header remains commercial-status free.

## Promo Code Foundation And Platform Management

M2 is implemented as an additive promo-definition layer. `promo_codes` stores
only HMAC lookup authority and masked display fragments, exact capacity,
controlled scope, validity, lifecycle, replacement, and governance metadata.
`promo_code_branch_restrictions` preserves eligible existing-branch snapshots;
`promo_code_audit_events` records allowlisted durable action history. Migration
`20260805_001_promo_code_foundation` performs no backfill.

Platform Owners and permission-authorized Developers can use the Promo Codes
console. Developers may view, create/edit unused drafts, duplicate, pause, and
create replacement definitions; activation and terminal revocation remain
owner-only. M3 now consumes approved definitions through a separate
customer-redemption service; definition management itself remains isolated from
activation, M1 authority, Paddle, onboarding, and tenant operations.

## Unified Commercial Access And Capacity Authority

M1 establishes `saas/commercial_authority_service.py` as the only operational
capacity facade. It composes workspace classification and lifecycle,
WorkspaceEntitlement, TenantProvisioningLink, SubscriptionContract,
PaymentSubscription, commercial state/access, demo lifecycle, and the existing
plan-capacity and feature-entitlement services. It does not persist a second
commercial status or entitlement model. Missing, invalid, ambiguous, or
unsupported authority fails closed.

For active paid workspaces, allowed branches are confirmed subscription
quantity capped by the plan ceiling; staff and teacher limits come from the
confirmed plan. Staff usage includes every distinct active tenant operational
User in the SchoolGroup, including an operational organization owner and users
whose position is Teacher. Platform users and account-only SaaS identities do
not count. Active teacher people are deduplicated by normalized
`Teacher.teacher_id`; blank legacy identities each count separately. A person
represented by both records consumes one staff slot and one teacher slot.

Branch, user, teacher, academic-year, and provisioning growth now acquires a
tenant row lock, recounts authoritative usage, evaluates the proposed final
state, and mutates in the same transaction. Existing over-capacity tenants keep
their data and access but cannot further increase an exceeded dimension. Demo
and Internal Sandbox authority is explicitly unmetered in M1. No schema,
migration, pricing, Paddle, webhook, onboarding-transition, permission, or
feature-packaging change is included.

## Explicit Organization Billing Identity

Organization Account Billing & Subscription now owns a confirmed billing
profile independent from SaaS authentication. The profile stores billing email,
legal/billing organization name, contact, optional company/tax identifiers, and
the existing supported address structure. Initial Secure Payment confirms this
profile; only organization owners or linked users with
`subscriptions.manage_billing` may view or update it for an active tenant.

The mapped Paddle customer is reused and synchronized after an authorized
billing change. Its active address and one attributable Paddle Business are
created or updated and persisted as `PaymentCustomer.provider_address_id` and
`PaymentCustomer.provider_business_id`; the active
subscription identity and future initial transaction use those mappings.
Ambiguous mappings fail closed. Login-email changes never mutate billing email,
billing-email changes never mutate authentication, and historical invoices are
not silently revised.

Billing Contact now renders saved values read-only until an authorized Edit.
Saving commits valid local details even when Paddle cannot be updated. The
customer can retry synchronization directly without changing the profile; the
retry reuses existing customer/address/business mappings and becomes a no-op
after success. Safe server logs identify the failed provider step, error code,
and status without rendering diagnostics to customers. A saved profile in
pending or failed synchronization state blocks new plan and quantity changes
until synchronization succeeds. Cancellation and legacy active subscriptions
without a saved profile are not newly blocked.

Provider `paid` is now presented as payment received while processing and is
recorded separately from final confirmation. Provider `completed` remains the
required reconciliation signal and renders as Paid. No webhook completion rule
or subscription authority changed.

## Subscription Capacity Presentation And Account Billing Access

Subscription Management and Review Capacity now present paid branch quantity
separately from the plan branch ceiling. Additional required branches are
identified as additional billed quantity, while system-user and teacher counts
remain non-billed plan-eligibility ceilings. Customer plan cards no longer show
unapproved feature claims or feature placeholders.

Authorized operational organization owners and explicitly billing-authorized
account managers can open the existing Organization Account Billing &
Subscription page from System Configuration. The bridge and destination both
revalidate tenant/account linkage and permissions. Missing SaaS authentication
preserves only the approved internal subscription continuation through sign-in;
invalid, unrelated, and external destinations fail closed. The Next.js landing
page now labels this centralized customer entry Organization Sign In. Paddle
quantity, pricing, entitlement, lifecycle, webhook, and provider-authority
behavior are unchanged.

## Organization Account Sign-In Routing

Activated organization owners and account-authorized linked users now land on
the Organization Account Overview after public/onboarding password or social
sign-in, authenticated sign-in restoration, and SaaS root restoration. The
overview filters Organization Profile, Branches, Billing & Subscription, and
Account & Security by existing ownership and operational permissions. Enter TIS
Platform is the only overview action that enters operational login. Restricted
account managers retain billing/recovery access without operational entry;
incomplete onboarding resumes; non-management users retain role-based routing;
and multi-organization identities select the organization first. No schema,
permission semantics, commercial-access decision, or operational login behavior
changed. The selected UUID is stored only in an HTTP-only cookie and validated
against the account's links before the entitlement resolver uses it.

## Initial Secure Payment Recovery

The production-equivalent failure was local and preceded Paddle transaction
creation: `_ensure_checkout_launchable()` rejected the legacy
`ready_for_checkout` pre-checkout billing state. That eligible state is now
prepared safely. Professional Annual remains USD 790 per active branch, and
the verified two-branch checkout uses quantity 2 with a USD 1,580 annual total.

Secure Payment retry now repairs eligible unpaid legacy/stale checkout state
instead of repeatedly rejecting it. Plan, interval, quantity, selection, and
quote changes supersede the old checkout session and unfinished attempt,
clear their local authority, and produce a fresh transaction from the current
server quote. Superseded transaction webhooks remain fail-closed and cannot
create a subscription or workspace.

Paddle customer addresses are reused only when active, customer-matched, and
country-compatible. New and reused transaction URLs are released only through
the billed automatic-collection transaction contract. Provider failures are
logged with status/code/traceback and rendered as one customer-safe retry
alert. Pricing, plan limits, branch authority, webhook confirmation, checkout
architecture, provisioning, and schema are unchanged.

## Organization Profile And Initial Account Setup Correction

Organization Profile now handles approved educational-program values
consistently and maps invalid input back to the same page with preserved form
values. Pending logos are actual-image validated, limited to 4 MB, assigned an
opaque unique filename, written atomically, and cleaned up when a later
database step rolls back. Empty upload retains the existing logo, successful
replacement removes the obsolete file, and storage/unexpected errors are
logged server-side while customers receive a safe inline response.

The fresh verified-account page now presents one compact setup title, one
explicit POST start action, and the existing eight-step progress indicator.
Its smaller header logo and consolidated content remove the repeated status,
action, account/workspace, and guidance panels without changing later
onboarding states.

Pending organization logos still use
`static/uploads/saas/pending_logos`. This local path is not production-durable
on an ephemeral Render filesystem; persistent disk or object storage remains
an owner-approved follow-up. No schema, migration, payment, billing,
operational-module, or Next.js landing change is included; provisioning changed
only to validate and preserve the already-established logo promotion.

The saved pending logo now appears in Organization Profile and the existing
School Workspace identity area with the organization name and a neutral
placeholder when absent. Existing paid/demo workspace creation promotes the
image into the primary `SchoolGroupLogo` slot, whose protected URL is consumed
by the operational header and branding settings. The official TIS logo remains
separate. Provisioning no longer silently ignores a referenced pending logo
whose local file is missing.

Branch Setup totals now come from a Python normalization helper, so placeholder,
legacy-null, and mixed-value rows render without Jinja arithmetic errors.
Customer saves continue to require explicit non-negative system-user and
teacher estimates, and new branches receive zero defaults.

## Post-Verification Login Correction

Fixed the fresh-account login destination that previously redirected a
successful POST login to the POST-only `/saas/onboarding/start` action. The
browser followed that 302 with GET and received raw HTTP 405 JSON. Fresh
verified accounts now open `/saas/account`; onboarding creation remains behind
the existing explicit POST action. Continuations are restricted to known GET
destinations, and accidental GET navigation to `/saas/auth/login` redirects to
the normal sign-in page. Verification, password authentication, subscription
intent, preferred-plan behavior, and onboarding business rules are unchanged.

## Public Subscription Journey

The Next.js hero Subscribe Now CTA now scrolls to the stable pricing section.
Starter, Professional, and Enterprise AI share one CTA presentation and enter
public TIS Account registration with an allowlisted preferred-plan code.
Registration preserves that preference without creating commercial records.
After School Workspace Setup, plan selection reuses the existing
three-dimension capacity authority; an invalid, inactive, or undersized
preference is cleared and the customer reviews eligible plans. Custom remains
mail/contact-only. No plan price, capacity limit, Paddle behavior, or AI
entitlement changed.

## Per-Branch Subscription Capacity

Implemented required system-user and teacher estimates on each onboarding
branch, organization-wide live totals, and one three-dimension capacity
decision covering branches, tenant operational staff users, and teachers. The lowest
eligible self-service plan is recommended while higher eligible plans remain
selectable. Starter limits are 1/5/25, Professional 5/20/100, and Enterprise AI
25/100/500; exceeding any Enterprise limit routes to contact-only Custom.

Before payment, estimates are compared with actual same-workspace counts and
the greater value is authoritative. After activation, every distinct active
tenant operational User counts as staff regardless of position, and active
teacher people count separately. Capacity changes invalidate quote/checkout lineage and clear
only an undersized plan. Paid system-user creation/reactivation, teacher
creation/year-copy preflight, and downgrades fail before mutation when the
result would exceed capacity.

The active customer portal now presents unified Organization Capacity instead
of a branch-only action. Review Capacity compares proposed branches, system
users, and teachers with the current plan and opens either the existing branch
quantity preview or a required plan-upgrade preview. A branch-triggered upgrade
may update plan price and branch quantity together; user and teacher totals
never change Paddle quantity. Scheduled plan downgrades and quantity reductions
revalidate live capacity at the provider-confirmed effective boundary and enter
manual review rather than applying an unsafe local reduction.

## Customer Journey And Expired-Access Correction

Implemented returning-account state routing, direct expired-demo subscription
selection, operational and SaaS expiry pages, and a pre-workspace commercial
guard for both demo and paid subscriptions. Demo checkout uses the existing
organization, SchoolGroup, and active operational branch quantity and continues
into the existing Paddle conversion workflow. The Next.js landing exposes
Request a Demo, Subscribe, Sign In, and Open TIS App through
`NEXT_PUBLIC_TIS_APP_BASE_URL`. The owner demo page retains all M8B9 operations
behind progressive disclosure, and customer communications identify the TIS
team. No schema, pricing, Paddle-authority, AI-entitlement, migration, or
deployment change is included.

Paid commercial access now consumes the existing contract-linked entitlement
authority instead of selecting the newest subscription for an onboarding
organization. Active or trialing current subscriptions retain operational
access while plan changes await payment/provider confirmation, fail, expire, or
are abandoned. Plan-change subscription webhooks synchronize provider status
without bypassing two-signal plan confirmation. Restricted pages and APIs use
state-specific past-due, paused, expired, suspended, archived, and manual-review
guidance. A canceled subscription remains entitled only through its confirmed
paid period end.

## M8B9 Demo Operations, Notifications, And Testing

Implemented Platform Owner-only demo lifecycle controls, synchronous
single/global lifecycle summaries, Standard/Full/Custom access profiles,
workspace and tenant-safe branch scope, durable success/failure audits, and
M8B7-based customer communications. Migration
`20260727_003_m8b9_demo_operations` remains in the pre-deploy boundary and M8B8
usage history is retained across profile transitions.

## M8B8 AI Entitlements And Commercial Foundation

Completed: centralized AI entitlement decisions, stable feature registry,
assignable AI permission, two-successful-use demo allowances per feature,
Enterprise AI paid mapping, tenant-safe durable counters and operation ledger,
idempotent/concurrency-safe consumption, consistent subscription guidance, and
Render-safe migration. No real AI execution route exists yet, and M8B9
inspection/reset/override/lifecycle controls remain unimplemented.

## M8B7 Demo Customer Journey

Completed: approval-orchestrated activation with safe retry; durable request, approval, decline, reminder, expiry, and continuation email intents; existing Notification Center integration; shared-shell active-demo indicator; lifecycle communication processing; and authoritative-payment conversion of coherent expired demos using the same workspace. M8B8 and M8B9 remain unimplemented.

Render startup no longer executes SQLAlchemy table creation or pending
migrations while importing or starting `main:app`. Render runs that work
through `python scripts/run_migrations.py` as a required Pre-Deploy Command
before activating the new web version. The web process has no migration worker
or schema-readiness middleware and binds independently of PostgreSQL DDL.

## Last Updated

Last updated: 2026-07-29

Update this file after every meaningful milestone, active development change, roadmap shift, known issue change, or documentation/KMS change.

## Current Branch Strategy

Current working branch assumption: `dev`.

Branch strategy:

- Development work should happen on `dev` unless the owner explicitly requests another branch.
- Production/live branch is assumed to be separate from active development.
- Confirm production branch before any deployment, merge, or production-sensitive change.
- Do not push, merge, or commit unless explicitly requested.
- Preserve unrelated local changes.

## Production / Live Branch Assumption

The live production branch is assumed to be the branch deployed to the public app environment, while `dev` is the active development branch. This assumption must be confirmed before deployment.

Production domains:

- Public website: `https://tisplatform.com`
- Application portal: `https://app.tisplatform.com`

## Completed Milestones

M1: Identity and SaaS foundation

- Core SaaS signup/login/account concepts established.
- Platform, tenant, and SaaS account identities separated.
- Identity and SaaS phase tests present.

M2: Onboarding foundation

- SaaS onboarding flow covers organization, contacts, branches, academic setup, and review.
- Pending organization concept supports pre-provisioning state.

M3: Billing and plan foundation

- Plan catalog, checkout, billing status, checkout return, and checkout cancel flows exist.
- Payment and billing code is isolated under `saas/` service modules.
- Initial Paddle checkout price IDs are configured through a script-based mapping sync into `subscription_plan_prices.provider_price_id`.
- Sandbox and production Paddle price mappings must remain separate; real mapping files are ignored and credentials stay in environment variables.

M4: Provisioning foundation

- Platform owner provisioning views and actions exist.
- Pending organization review and provisioning queue behavior exist.
- Provisioning retry/run operations are present.

M5: Platform access and owner controls

- Platform owner and platform developer identities exist.
- Platform console and owner/developer management controls exist.
- Permission registry and platform access tests support this boundary.
- Platform Owner pending counts and lists now use one lifecycle-aware query boundary instead of counting every historical `PendingOrganization` row.
- Active/completed tenants are retained in Organization Records, while unresolved completed-provisioning combinations are surfaced conservatively as Lifecycle Review Required.
- Owner-facing organization lifecycle labels reconcile onboarding, payment, subscription, contract, tenant-link, provisioning-job, and active SchoolGroup evidence without mutating historical status fields.

SaaS account setup stabilization:

- Phase 1 TIS Account email verification recovery is accepted.
- Valid verification links now redirect to TIS Account login with a professional success notice.
- Expired or invalid verification links now show a recovery page with a resend option.
- Resend verification safely handles unverified, already verified, and unknown-email cases.
- Unverified password-based accounts are blocked from starting or continuing school workspace setup.
- New verification-flow wording uses "TIS Account" and "school workspace setup".
- Payment, billing, provisioning, database schema, migrations, operational modules, and the landing website were not changed.
- Google/Microsoft login remains future work and was not implemented.

SaaS customer-facing wording and branding:

- Phase 2 TIS Account customer-facing wording cleanup is accepted.
- Customer account/setup pages now use professional labels such as TIS Account, Account Dashboard, School Workspace Setup, Organization Profile, Branch Setup, Academic Setup, Subscription Setup, Secure Payment, and Workspace Activation.
- The shared customer account shell uses the official full-color horizontal TIS logo on the light account background.
- Transactional TIS Account emails use an existing official dark-blue TIS wordmark asset.
- Customer views label internal statuses through customer-safe wording instead of exposing raw tenant, provisioning, checkout, provider, plan, school group, or attempt identifiers.
- Internal `/saas` route/module/model names and stored statuses were not renamed.
- Payment, billing, provisioning behavior, database schema, migrations, operational modules, and the landing website were not changed.
- Google/Microsoft login remains future work and was not implemented.

SaaS guided setup framework:

- Phase 3A shared TIS Account guided setup framework is accepted.
- The customer account shell now supports an official-logo guided setup console with an 8-step journey stepper, status banner, one primary next action, main content area, and help/guidance area.
- The account page now uses the framework and removes the old dense dashboard statistics from the customer account landing page.
- Journey state is derived from existing account, onboarding, billing, payment, and activation data without changing stored statuses.
- Onboarding forms, subscription/payment pages, billing/status pages, payment behavior, billing behavior, provisioning behavior, database schema, migrations, operational modules, the landing website, internal `/saas` route names, and Google/Microsoft login were not changed.
- Phase 3B redesigned the five School Workspace Setup onboarding pages on top of the shared setup shell.
- Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup now use consistent guided wizard sections, one shared-shell primary CTA, and secondary Back/Save Draft actions.
- Phase 3B preserved backend logic, form actions, field names, validation behavior, draft behavior, onboarding progression, payment/billing/provisioning behavior, database schema, migrations, operational modules, the landing website, internal `/saas` route names, and OAuth behavior.
- Phase 3C redesigned Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages using the same shared setup shell and guided style.
- Phase 3C added customer-safe browser-return/payment confirmation guidance and explicit TIS Platform access-after-activation messaging without changing payment, billing, provisioning, webhook, checkout start/launch, database, migration, operational, landing, route, stored-status, admin, or OAuth behavior.

Documentation/KMS milestones:

- Phase 1 documentation foundation completed and pushed to `dev`.
- Phase 2A and Phase 2B KMS foundation approved for implementation.
- Phase 2C Platform Owner Knowledge Center completed and pushed to `dev`.
- KMS v3.0 Phase 3A Engineering Handbook approved for implementation.
- KMS v3.0 Phase 3B approved for implementation.
- KMS v3.0 Phase 3C approved for implementation.
- KMS v3.0 Phase 3D final phase approved for implementation.
- Automatic KMS enforcement implemented with repository instructions, machine-readable KIA, major-change detection, read-only artifact checks, CI validation, and a deployment prerequisite.
- Phase 6 unified KMS command implemented with `scripts/kms.py sync` and `scripts/kms.py check`.
- Phase 7A navigation foundation implemented with task-based reading paths, improved indexes, and normalized supporting-document titles.
- Phase 7B professional PDF navigation implemented with handbook guidance, a page-numbered table of contents, source and major-heading bookmarks, and manifest source-page metadata.
- Phase 7C Platform Knowledge Center navigation implemented with manifest-backed titles and summaries, logical document groups, client-side search and filters, protected booklet page links, and newest-first knowledge activity.
- Phase 7D KMS navigation and catalog enforcement implemented with usable-title checks, approved category/module vocabulary, exact source inventory checks, docs-only navigation links, and generated PDF page-bound validation.

M7 subscription-management milestones:

- Phase 1 entitlement foundation completed.
- Phase 2 customer Subscription Management portal completed.
- Phase 3 active paid branch-quantity management completed.
- Phase 4 upgrades and scheduled downgrades completed with provider-authoritative previews/proration.
- Phase 5 cancellation/reversal and centralized lifecycle/action policy completed.
- Phase 6 provider billing history and protected invoice management completed.
- Webhook and reconciliation safeguards were added across the M7 lifecycle.

M8B-1 workspace-classification foundation:

- Added stable workspace UUID, workspace classification, and workspace lifecycle metadata to `SchoolGroup`.
- Added onboarding workspace intent, SaaS account purpose, and operational internal-test identity metadata.
- Added constrained enums, indexes, validation helpers, conversion rejection, and a commercial-state skeleton with no commercial behavior.
- Added a read-only relationship diagnostic plus dry-run/default and transactional/idempotent apply backfill commands.
- Confirmed pre-M8B-1 records are backfilled as internal sandbox/test data; no Al-Andalus conversion is included.
- Platform Owners can inspect the metadata read-only in Platform Console; developers and tenant users cannot.
- Existing onboarding, authentication, Paddle, provisioning, permissions, tenant isolation, entitlements, and customer flows remain authoritative and unchanged.

M8B-2 commercial-state and entitlement foundation:

- Added normalized workspace entitlement, workspace entitlement value, and branch entitlement records.
- Added read-only workspace, branch, and effective commercial-state resolvers with conservative manual-review outcomes.
- Paid workspace capability resolution reuses the confirmed M7 subscription entitlement engine; no billing calculations or Paddle calls were added.
- Existing internal sandbox workspaces are seeded with foundation entitlements, while newly created internal test workspaces can use a read-only compatibility entitlement.
- Platform Owners can inspect Commercial State, Workspace Entitlement, and Branch Entitlement Summary; developers and tenants cannot.
- No customer access rule, branch behavior, feature restriction, demo lifecycle, onboarding, provisioning, role, or conversion behavior consumes M8B-2 yet.

M8B-3 demo-request workflow:

- Completed onboarding now ends with an explicit Request Demo or Subscribe Now choice.
- Subscribe Now continues the approved plan-selection, checkout, Paddle, and provisioning lifecycle unchanged.
- Demo requests are validated, snapshot commercial context, prevent duplicate pending requests, and never create or activate a workspace.
- Platform Owners can search, filter, sort, approve, reject, or cancel requests; approval records review only and rejection requires a reason.
- Customers can inspect their request and withdraw it only while Pending Review.
- Submit, approve, reject, cancel, and withdraw transitions create durable audit and internal-notification events. No email is sent.

M8B-4 demo workspace provisioning and activation:

- Only a Platform Owner can provision a coherently approved customer-demo request.
- Demo provisioning reuses the shared operational workspace builder and creates no Paddle, checkout, payment, subscription, or paid-contract record.
- Demo workspaces receive an explicit demo entitlement and a tenant link sourced by the demo request rather than a fabricated subscription contract.
- Workspace creation and activation are atomic; failures preserve the Approved request, roll back workspace records, and retain a retryable failure outcome.
- Successful provisioning activates the SchoolGroup and entitlement, links the request to the workspace, records activation metadata and audit/internal events, and blocks duplicates.
- Customers see safe approval/provisioning/active states; Platform Owners see provisioning result and failure details. No email is sent.

M8B-5 standard customer-demo lifecycle:

- Demo duration is exactly seven days from successful activation; the reminder boundary is exactly Day 6.
- One resolver owns Active, Reminder Due, Expired, Suspended, and Manual Review outcomes using UTC calculations and organization-timezone display.
- The dry-run/default lifecycle command creates idempotent internal reminders and atomically expires due demos only when run with `--apply`.
- Expiration ends the demo entitlement and suspends the workspace while preserving users, branches, and all tenant data.
- Operational middleware blocks expired or ambiguous demos for web, API, download, and existing-session requests; Platform users, paid tenants, and internal sandboxes are unaffected.
- Customer and Platform Owner pages show safe lifecycle state, expiration timing, reminder state, and processing history. No email is sent.

M8B-6 demo-to-paid conversion:

- Active, coherently provisioned Customer Demo workspaces may proceed through the existing subscription checkout.
- Provider-confirmed subscription payment converts the same SchoolGroup and tenant link; no workspace, organization, branch, user, permission, or academic record is recreated.
- The demo entitlement is ended and replaced by a paid entitlement linked to the confirmed M7 subscription.
- The existing tenant link moves from its demo-request source to the confirmed subscription contract in the same atomic conversion transaction.
- Conversion states and audit/internal events remain durable, failures preserve paid records and demo operation for retry, and completed conversions leave demo lifecycle processing.
- Expired, ambiguous, cross-tenant, internal-sandbox, paid, and already-converted workspaces remain fail-closed.

M8 Landing Integration:

- Final M8 landing integration exposes two clear customer paths from the public Next.js landing website: Request a Demo and Subscribe Now.
- All public conversion links use the shared `NEXT_PUBLIC_TIS_APP_BASE_URL`, with `/saas/signup?intent=demo` and `/saas/signup?intent=subscribe` as the only destinations.
- Signup and School Workspace Setup preserve the valid selected intent and emphasize it on the final commercial-choice step without locking the customer into it.
- A normalized organization-domain eligibility ledger enforces one customer demo opportunity across pending, approved, active, expired, rejected, cancelled, and demo-to-paid history. Internal Sandbox records do not reserve customer eligibility; public email providers require an official organization website or domain before a demo can be requested.
- Migration `20260725_001_demo_domain_eligibility_policy` backfills safe historical reservations and marks ambiguous duplicate history for manual review without merging, deleting, reprovisioning, or changing existing workspace data.

Test workspace reset dependency correction:

- The Platform Owner-only test workspace/account reset now removes `subscription_change_requests` by the selected `school_group_id` before deleting that workspace's operational users.
- It removes selected entitlement values and branch-entitlement children before the selected workspace entitlement and final SchoolGroup, without changing global entitlement definitions, plans, or prices.
- The same guarded reset now clears only the selected organization's linked demo request, domain reservation, review/event history, provisioning/lifecycle history, and demo-to-paid conversion history. This permits a clean internal retest with the same email and organization domain while the production one-demo-per-domain policy remains unchanged.
- Detached same-domain reservations are now cleaned only after the shared demo-domain resolver finds no other organization, demo request, workspace, or customer account using that domain and the reservation has no historical manual-review evidence; conflicts or ambiguous history are surfaced as manual review and preserve all data.
- Safe detached reservation IDs now pass explicitly from reset analysis to deletion. The deletion transaction removes only those IDs, flushes before demo-request and parent deletion, and verifies that no selected row remains before continuing.
- The scoped pre-analysis count, deletion diagnostics, affected-row total, transaction rollback, and preservation of other workspaces remain in place.

Platform Owner demo eligibility maintenance:

- `/saas-admin/demo-eligibility-maintenance` lists domain-eligibility reservations and identifies safely removable historical detached rows.
- Safety analysis blocks deletion when any matching organization, TIS Account, demo request, operational workspace, provisioning record, subscription evidence, Demo-to-Paid conversion, or manual-review evidence remains.
- The destructive action requires explicit owner confirmation, re-analyzes under an exact-row lock, deletes only the selected eligibility ID, flushes, verifies absence, and commits or rolls back atomically.
- Successful deletion records the Platform Owner, eligibility ID, normalized domain, previous status, timestamp, and fixed historical-cleanup reason in the durable audit log.
- Customer demo submission, one-demo-per-domain enforcement, clean-room reset, schema, foreign keys, and customer-facing behavior remain unchanged.

## Current Priority

Current priority: validate the final M8 public landing integration before any separately approved M9 work.

Current enforcement scope:

- Codex reads root `AGENTS.md` and authoritative KMS context.
- Every task updates `.kms-impact.yml`.
- Major-change paths are conservatively classified by `scripts/check_kms_impact.py`.
- Local KMS synchronization runs through `scripts/kms.py sync`.
- Generated artifacts and KIA are validated read-only through `scripts/kms.py check`.
- Pull requests and `dev` pushes run KMS enforcement.
- `master` deployment waits for the KMS gate.
- Automation validates and blocks; it does not rewrite Markdown.
- Phase 7D also blocks missing or unusable source titles, unapproved catalog values, invalid KMS navigation targets, source-list drift, and missing, non-positive, non-increasing, or out-of-range manifest PDF pages.

Phase 2A and Phase 2B scope:

- Create documentation update policy.
- Create change history.
- Create ADR foundation and initial accepted ADRs.
- Create module history foundation.
- Create AI project context.
- Update master context, project state, and documentation index.
- Update PDF generator to include KMS docs and manifest metadata.
- Regenerate `static/docs/TIS_Project_Reference_Booklet.pdf`.

Phase 2C completed scope:

- Added read-only `knowledge_service.py` as the single KMS app access layer.
- Added owner-protected `/platform/knowledge` page.
- Added owner-protected PDF view/download routes.
- Added an owner-only Platform Console card.
- Added platform knowledge module history.
- Regenerated the PDF and manifest after documentation updates.
- Phase 7C adds client-side source search, category/module/freshness filters, logical document groups, document titles and summaries, protected booklet page links, and improved ADR/module-history ordering without adding routes or write behavior.

Still out of scope:

- Regenerate button.
- Additional app routes beyond the approved read-only Knowledge Center routes.
- `ui_shell.py` and `authorization.py` changes unless separately approved.
- SaaS flows.
- Operational logic.
- Database, migrations, or `tis.db`.
- Landing page implementation.

KMS v3.0 Phase 3A scope:

- Add complete TIS module map.
- Add repository architecture map.
- Add end-to-end user/system workflows.
- Add clear AI/human developer onboarding structure.
- Update generator to include engineering docs.
- Regenerate the PDF and manifest.

KMS v3.0 Phase 3B scope:

- Add database architecture overview.
- Add development standards and non-negotiable rules.
- Add UI/UX and design philosophy.
- Add product roadmap.
- Strengthen AI/human developer onboarding guidance.
- Update generator to include the new engineering docs.
- Regenerate the PDF and manifest.

KMS v3.0 Phase 3C scope:

- Add rejected architectural decisions.
- Add visual documentation framework.
- Add AI optimization guide.
- Add project governance and decision traceability.
- Update generator to include the new engineering docs.
- Regenerate the PDF and manifest.

KMS v3.0 Phase 3D final scope:

- Add knowledge lifecycle documentation.
- Add documentation automation guide.
- Add formal KIA standard.
- Add self-evolving workflow.
- Add documentation dependency map.
- Add AI coding workflow.
- Add future automation roadmap.
- Regenerate the PDF and manifest.

## Current Known Issues

M4C existing-workspace paid activation is implemented for verified tenant owners.
Professional and Enterprise AI cover all active branches and use branch count as
Paddle quantity. Starter is deliberately fail-closed until complete restricted-
branch enforcement is proven. Deployment still requires migration
`20260806_002_existing_workspace_paid_activation`, environment-specific active Paddle
price mappings, and Sandbox validation before production use. Disposable PostgreSQL
validation covers migration idempotency and rollback, database constraints,
concurrent prepare/launch, duplicate and out-of-order webhooks, drift rollback, and
paid-versus-promo source races. Live Paddle validation was not possible without the
Sandbox API, client, and webhook credentials.

Organization Account status for an activation-required existing workspace is now
derived from its current paid-activation attempt. With no attempt it displays
`Activation required`; only a current unexpired checkout-started or payment-processing
attempt displays `Payment processing`. Terminal attempts display recovery states.

Existing-workspace plan selection is editable only before real checkout begins.
Organization Account reopens the eligible plan-selection surface for `draft` and
`checkout_ready` activations, highlights the saved choice, and recalculates a
replacement quote without creating a Paddle transaction or PaymentAttempt.
Checkout-started, payment-processing, and manual-review/inconsistent activations
remain locked against silent replacement.

Known issues and watch points:

- KMS policy depends on future developers and AI agents consistently completing the Knowledge Impact Assessment.
- Generated PDF can become stale during local work, but CI now blocks stale artifacts from integration/deployment.
- The owner-only Knowledge Center is implemented as read-only; there is no regenerate button yet.
- Public static storage is not sufficient access control for sensitive docs; Phase 2C should serve docs through protected owner-only routes.
- Render deployment constraints should continue to guide dependency choices.
- Production memory must be treated as a hard constraint. The 2026-06-27 Render restart/502 investigation found two avoidable memory risks: observation diagnostics doing extra production template renders and global location lookup parsing a 47 MB dataset into a complete in-memory index for simple picker requests. Local stabilization changes now gate observation diagnostics and use scoped location loading; future work must follow the Production Memory and Render Stability standards.
- The untracked repository-root directory `tis_scope_test_5i3yf0h5/` has a Windows
  security descriptor that denies enumeration and ACL inspection to the normal
  development process. Repository pytest collection is bounded to `tests/` and
  explicitly excludes that orphan directory, so root `pytest` runs do not scan it.
- Google/Microsoft login is still future work; password-based accounts must remain email-verified before school workspace setup.
- GitHub repository settings must mark `KMS Enforcement / kms-check` as required on protected branches; this cannot be configured by repository file changes alone.

## Next Planned Work

Next planned work:

- Review the KMS enforcement rules against real pull requests and tune only demonstrated false positives.
- Keep M7 documentation current as subscription fixes evolve.
- Later consider an explicit owner-only regenerate workflow.
- Review, commit, and deploy the production memory stabilization changes when approved, then monitor Render memory, restart count, and route-level 502s after deployment.

## Landing Page Baseline Situation

The public landing page source of truth is:

- `tis-landing-website/`

Marketing docs:

- `docs/marketing/landing_page_source_of_truth.md`
- `docs/marketing/tis_landing_page_master_content.md`

Relevant ADRs:

- `docs/adr/0001-separate-nextjs-landing-website.md`
- `docs/adr/0007-landing-page-visual-system-strategy.md`

Legacy FastAPI landing files are not the current public website source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

Do not modify landing page design, landing copy, or legacy landing files unless explicitly approved.

## Knowledge Update Policy

Every approved implementation must complete the KIA:

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

A task is not complete until KIA is assessed and `.kms-impact.yml` matches the actual task diff. If included docs change, regenerate:

- `static/docs/TIS_Project_Reference_Booklet.pdf`

Then run `.\.venv\Scripts\python.exe scripts\kms.py check` for final read-only validation. When documentation changes, `.\.venv\Scripts\python.exe scripts\kms.py sync` performs generation and post-generation validation together.

## Scope Guardrails

- Do not touch SaaS flows unless explicitly approved.
- Do not touch operational logic unless required by the approved task.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not change the landing page unless explicitly approved.
- Do not add a KMS regenerate button until separately approved.
- Do not let automation rewrite authoritative Markdown.
- Do not place customer, personal, production, billing-record, transaction, invoice, webhook payload, credential, secret, environment, or database-row data in KMS docs.
- Do not commit or push unless explicitly requested.
