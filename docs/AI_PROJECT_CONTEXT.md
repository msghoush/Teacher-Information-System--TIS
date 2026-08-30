---
title: TIS AI Project Context
documentation_version: 3.3
last_updated: 2026-08-26
recommended_first_read: true
---

# TIS AI Project Context

## Teacher Scheduling Rules

Administrators with `timetable.manage_teacher_rules` configure teacher-specific
timing policy in Timetable Settings without changing Planning demand or teacher
allocation. The normal form asks only for teacher, rule, days, numbered periods,
and optional Current/New sections with Select All. **Schedule within these
periods** constrains existing eligible lessons to an allowed window without
creating occupancy or demand; **Must teach these periods** requires occupancy in
every selected slot; **Unavailable** prohibits all teacher lessons in those slots.
Existing first/last, grade-target, and preference rules remain compatible but are
not exposed in the simplified normal form.

Schema-v4 immutable snapshots capture canonical resolved teacher rules in the
constraint fingerprint. Rule changes mark unpublished Drafts stale, clear Draft
approval, and require regeneration while published history remains untouched.
Readiness and the problem builder reject deterministic workload, allowed-window
capacity, target, lock, slot, and contradictory hard-rule conflicts; CP-SAT
enforces hard timing and scores existing preferences; the independent validator
repeats hard-rule and window checks. With no rules, generation behavior is
backward compatible.

When more than one Schedule-within rule targets the same teacher demand, their
configured slots form one allowed-window union for that demand. They are not
independent whole-workload restrictions and must not be intersected. The problem
builder computes this combined authority before CP-SAT and performs exact
teacher-slot matching plus deterministic checks for window/unavailability
capacity, Must-teach compatibility, daily coverage, hard maximum-per-day,
minimum-day, and double-block feasibility. Proven conflicts appear as readiness
blockers with required-versus-available guidance instead of reaching a generic
solver-infeasible result. Grouped activities count one teacher occupancy.

If CP-SAT still proves the complete model infeasible after deterministic checks,
the Workflow reruns bounded diagnostic profiles without changing the real run.
It distinguishes base demand/collisions, locks, grouped activities/resources,
Subject Distribution Rules, Teacher Scheduling Rules, and subject/teacher-rule
interaction. The proven family, current lock count, and grouped-activity count are
stored in the Generation Run's customer-safe failure details. A diagnostic timeout
is reported as inconclusive rather than mislabeling a constraint family.
Diagnostic profiles use the dedicated
`TIS_TIMETABLE_DIAGNOSTIC_TIMEOUT_SECONDS` Workflow setting, defaulting to 60
seconds per attempted profile and independent of the main solver timeout. Profiles
for locks or grouped activities are skipped when their captured counts are zero;
successful isolation also reports safe model/rule/window counts where available.

The configuration UI keeps section selection literal: Select All synchronizes
every visible Current/New section, editing restores the exact saved targets, and
saved summaries name selected grade-section labels instead of collapsing them
to an any-class label. Manual Draft placement rejects hard Unavailable and
Schedule-within violations immediately. Complete Draft validation additionally
requires every Must-teach slot to contain an eligible lesson in its configured
section scope; the same validation blocks approval and publication. Soft
preferences remain non-blocking.

## Guided Curriculum Adjustment UI

Administrators with `curriculum.adjust` can enter a five-step, page-based workflow from Planning or Subjects. The UI selects Current/New scope, prepares the existing read-only preview, separates blockers from warnings, requires an explicit eligible teacher decision for every section, and submits the reviewed fingerprint to the atomic apply endpoint. A changed Planning state refreshes the preview without exposing revision terminology. Success links to Timetable and regeneration, but never starts generation automatically.

The entered transfer period count is authoritative: preview computes each section's source and target result from its effective `PlanningSubjectDemand`, rejects non-positive or excessive transfers, and apply persists exactly that reviewed result. Subjects presents those same Current/New Planning values for the active branch/year: a uniform grade-subject demand is shown directly, while section differences display as **Varies** with a section breakdown. `Subject.weekly_hours` remains a catalog/default value and is not rewritten by scoped adjustments.

The same workflow supports `reduce_only`: no target subject or teacher reassignment is required, the requested reduction is applied to each selected source demand, and all existing preview, fingerprint, transaction, Draft invalidation, lock, rule, and publication safeguards remain in force. Subject Details shows current effective Planning periods and offers a permission-gated **Adjust Weekly Periods** link prefilled for that grade-specific subject. Multi-grade reduction is intentionally not combined because subject codes and the atomic review/audit contract are single-subject identities.

## Atomic Curriculum Adjustment Apply

Stage 4 adds `curriculum_adjustment_apply_service.py` and permissioned
`POST /planning/curriculum-adjustments/apply`. The service requires a Stage 3
fingerprint and an explicit target-teacher decision, including intentional
unassigned, for every affected section. In one owned transaction it locks and
revalidates exact-scope Current/New Planning authority, rejects active generation,
stale previews, qualification/capacity failures, rule conflicts, and invalid Draft
locks, then updates source/target demands and assignments and writes one durable
audit. Zero source demand is retired and its active section rule is inactivated.
The current unpublished Draft is preserved but marked stale, approval is cleared,
and later regeneration is required. Published versions and the active pointer are
never mutated. `curriculum.adjust` is a dedicated apply permission.

## Read-Only Curriculum Adjustment Preview

Stage 3 adds `curriculum_adjustment_preview_service.py` and permissioned JSON route
`POST /planning/curriculum-adjustments/preview`. The service previews source-demand
reduction and transfer to a target subject for one grade, selected Current/New
sections, or every active source use in one exact SchoolGroup/branch/year. It reads
explicit-first `PlanningSubjectDemand`, current Planning/HRT teachers, teacher loads
and capacity, normalized Subject Scheduling Rules, grouped legacy configuration,
and the current mutable Draft Timetable revision. It returns per-section before/
after periods, teacher options, blockers/warnings, Draft stale/regeneration impact,
and a deterministic fingerprint that can be rebuilt before a future apply action.
It writes nothing, never assigns a teacher, and never changes timetable history.

## Explicit Planning Subject Demand Foundation

Migration `20260828_004_planning_subject_demands_foundation` adds
`planning_subject_demands`, an explicit branch/year and Planning-section scoped
weekly subject-demand foundation. The migration idempotently backfills matching
grade subjects for Current/New Planning sections only. Composite foreign keys
prevent section or subject scope drift, while a partial unique index permits at
most one active demand for a section and subject and preserves retired rows.
`planning_subject_demand_service.py` resolves explicit active or retired rows before
using legacy `Subject.grade + Subject.weekly_hours` fallback. Operational Planning,
teacher required/allocated/remaining load, timetable readiness/workspace/snapshot/
generation input, Subject Scheduling Rule arithmetic, and required-hours reports
consume that section demand. An explicit inactive or zero row suppresses demand.
Legacy fallback remains only when a section-subject has no explicit row. Published
timetable history remains immutable and unchanged.

## Tenant Report Branding

Tenant-facing operational reports and exports use `tenant_report_branding.py`
as their shared logo authority. It resolves only configured branch/organization
logo slots through the existing tenant-scoped branding resolver. A tenant with no
configured logo receives a clean text header with no image; tenant artifacts must
never fall back to a TIS product logo. Timetable PDF/XLSX exports, academic-calendar
PDF exports, and observation PDFs consume this rule. TIS branding remains valid in
the application shell, login/product surfaces, public/platform-owned materials,
and explicitly internal platform-owner reports.

## Subject Scheduling Rules UI

Timetable Settings now presents a grade-first Subject Scheduling Rules section:
`planning_scope_service.py` is the reusable operational selector authority. The
main and copy-rule grade selectors, timetable workspace section filters, and
calendar/grouped section choices derive only from Current/New `PlanningSection`
rows in the selected branch and academic year, never from the global grade range or a
catalog-only Subject row. An administrator selects one planned grade, can search its compact subject list, and sees
each Planning weekly total, current pattern, and configured/default status without
raw subject codes. The native dialog stays closed on page load and opens only
after Edit has populated the selected Subject + Grade and read-only Planning
total; Cancel/Close restores the closed state. Its compact Session Structure keeps
the aligned double-block and single-session steppers above one full-width live
total. Two-period Separate Sessions and Consecutive Double Block quick choices
remain available. Multiple primary conditions can be combined in a balanced grid;
minimum teaching days, strictness, and section overrides remain progressively
disclosed. Legacy subject-code mappings and Swimming JSON remain available only
inside a secondary Advanced / Legacy area. `subject_distribution_rules_ui.py`
re-validates the fixed two-period block arithmetic authoritatively on save
using the Stage 1 validator. Saving creates or updates only the intended
Grade+Subject (`scope_level="grade"`) row, or a specific section override when
a section is selected from the panel's Section Overrides list. Reset To
Default removes only the grade-level row so resolution falls back to the next
hierarchy tier; Copy Rules From Grade matches subjects across grades by name
(since subject codes are grade-specific) and skips any subject whose
arithmetic does not fit the target grade instead of copying it blindly. No
changes were made to the CP-SAT solver, independent validator, snapshot
immutability, or grouped-activity/Swimming JSON authority.

## Smart Timetable Academic Quality Rules

Branch/year Timetable Settings store explicit subject-code mappings for core,
spread, ICT, double-period, and grouped Swimming behavior. Schema-v3 snapshots carry
the normalized rules into the problem builder. CP-SAT requires daily core coverage
when weekly demand reaches the teaching-day count, maximizes distinct-day spread for
shorter core and configured spread subjects, supports hard ICT one-per-day, and keeps
configured Swimming sections simultaneous without weakening section, teacher, or
shared-resource protection. The independent validator repeats every new hard check.
Regeneration diversity remains configurable with a 25 percent default.

## Subject Distribution Rules Generation Wiring

Schema-v3 snapshots now resolve and embed the effective Subject Distribution
Rule (section over grade over branch default, `None` for legacy fallback) on
every Planning demand at snapshot creation time, so a later rule change never
alters an already-created snapshot. The problem builder carries that resolved
rule per demand, exposes true physical period adjacency on every slot, and
runs the arithmetic/feasibility validator as a final pre-solve defense,
failing cleanly with `distribution_rule_invalid` rather than reaching CP-SAT.
CP-SAT enforces an exact partition into intentional two-period blocks and
single-period sessions. Explicit block-start and single-session decisions
channel every occupied period to exactly one session: sessions may touch, so
three consecutive periods can be one double plus one single and four can be
two touching doubles, but session membership never overlaps. Physical timeline
interruptions still break a double. Daily session/load channeling strengthens
hard daily-coverage propagation without relaxing its meaning. CP-SAT also enforces generalized
daily-coverage/spread/max-per-day/min-teaching-days hard-or-soft behavior per
resolved rule, and exempts declared blocks from the consecutive-avoidance
penalty; demands without a resolved rule keep the exact legacy
`quality_rules_json` code-list behavior. The independent validator mirrors
every new hard check (existence of the same exact non-overlapping session
partition via true adjacency, hard daily
coverage, hard max/day, hard min teaching days) alongside the unchanged
grouped-activity and collision checks. Readiness now blocks genuinely invalid
or infeasible normalized configurations before generation while keeping the
existing core-subject warning path for legacy-only scopes. Regeneration is
unchanged: the same constraint-building path applies during regenerate, so
hard distribution rules remain valid while the diversity requirement reshuffles
unlocked placements.

## Subject Distribution Rules Foundation

A normalized `subject_distribution_rules` table (migration
`20260828_003_subject_distribution_rules_foundation`) now exists alongside
`quality_rules_json` without replacing it. Rows are scoped `branch_default`,
`grade`, or `section` per branch/academic year, with block/single counts, min
teaching days, max periods per day, daily-coverage/spread/consecutive
preferences, an optional min day gap, and a hard/soft strictness flag.
`subject_distribution_rules.py` resolves section-over-grade-over-branch-default
precedence with field-level inheritance for nullable fields, and returns `None`
when no normalized row exists so the caller keeps today's `quality_rules_json`
behavior unchanged. `subject_distribution_validator.py` is a pure arithmetic and
feasibility check confirming `block_count * block_length + single_count` equals
the authoritative Planning weekly total and that day/period limits are
feasible. `timetable_slot_service.py` marks each composed teaching period
with true physical adjacency to its next period, false whenever a Break,
Prayer, or other non-teaching item is composed between them, so intentional-block
enforcement can rely on genuine continuity rather than raw period-index
arithmetic.

## Smart Timetable Stage 5.2

Stage 5.2 presents Configure, Generate Draft, Review/Edit Draft, and Publish to Users
while retaining the Stage 2–5.1 version and solver internals.
The primary workspace resolves one exact-scope mutable unpublished Draft Timetable,
including a freshly created draft, and uses Approve Draft, Draft Approved,
Published, and Timetable History language. Generation never approves a draft.
Approval records the reviewing administrator and exact draft state; placement,
lock, regeneration, and stale-authority changes invalidate it. Publication requires
approval and repeats validation before atomically changing the active pointer.
Generated Draft workflow actions are grouped together on the primary workspace;
delete, archive, comparison, and version-specific exports remain in History.

Delete Draft Timetable permanently removes an eligible never-published draft and
preserves the active pointer. Timetable History may permanently delete every
never-published, non-active candidate regardless of origin or internal draft/archive
state; dependent unpublished versions are removed child-first while snapshots,
generation runs, and audit history are preserved. Protected published lineage and
active generation are reported as blockers. The assignable `timetable.delete_versions`
permission controls these actions and is granted to Administrators by default. Mutable working lessons may be moved or atomically swapped
between canonical teaching slots, with lock, class, and teacher conflicts failing the
whole operation. Publication uses explicit first-publish or replacement confirmation
and customer-facing Published to Users language.
Authorized managers may copy the current Published Timetable into an editable draft
or create a fresh empty draft from current Planning/configuration authority. Neither
action changes the active published pointer before explicit publication.
`timetable_visibility_service.py` resolves official reads strictly through
`TimetableActiveVersion`. `/my-timetable` matches scoped `User.user_id` to
`Teacher.teacher_id` and shows only that teacher's published lessons. View-only users
are redirected away from management drafts and history.

## Smart Timetable Stage 5.1

Stage 5.1 implements automatic branch/year timetable generation with Google
OR-Tools CP-SAT 9.15.6755 in a separate task dependency environment. HTTP requests
capture schema-v3 immutable inputs, commit durable PostgreSQL
`TimetableGenerationRun` rows, and use the server-side Render client to start one
on-demand Workflow task with only the run public ID. The task claims that exact row,
leases and heartbeats it, supports cooperative cancellation, solves hard constraints,
and submits candidates to an OR-Tools-independent validator. Render automatic retry
is disabled so TIS terminal state and Generate Again remain the only retry authority.

Generate creates a new unpublished `publication_ready` generated version only in
one atomic transaction after current-fingerprint revalidation. Regenerate preserves
locked placements, excludes the exact source, and requires 25 percent of unlocked
placements to differ, rounded up. An infeasible diversity target fails explicitly
rather than returning a nearly identical result. Neither flow changes published history or the
active pointer. The generated result remains the logical Draft successor of the
fresh source draft; the source is retained for provenance but omitted from normal
History presentation. Freshness fingerprints cover Planning, canonical timetable
configuration, stable generation constraints, and locks; generation-only source
metadata is retained in snapshots but excluded from authority comparison. Safe
component-level diagnostics identify real mismatches. `timetable.generate` is independent of publish authority. Stage 5.2
The old polling worker is optional/local only; production requires no always-on solver
service. Immediate dispatch failure is terminal and customer-safe, while delayed task
start is reported as waiting for compute. Stage 5.2 supplies the simplified workflow,
Delete Working Timetable, and teacher My Timetable.

## Smart Timetable Stage 3.5

`timetable_slot_service.py` is the single clock-time authority. For every working
day it composes the configured shift start, teaching-period count/duration, and
applicable non-teaching blocks into ordered teaching/block items. After-period
blocks are the default and shift every later period; legacy fixed-time blocks are
inserted only at a valid live boundary and otherwise surface a correction blocker.
The calculated end, settings preview, timetable grid, readiness, assignment
validation, snapshots/fingerprints, and XLSX/PDF exports consume this projection.
The additive placement columns preserve existing blocks as `fixed_time`. Stage 3.5
itself added no solver, generation endpoint, availability, or resources; Stage 5.1
now consumes that canonical timeline.

## Smart Timetable Stage 4

The timetable page now exposes exact-scope version history and distinguishes Draft,
Publication Ready, Active/Published, Superseded, and Archived views. Opening a
historical version never changes the active pointer. Operational default resolution
remains: newest mutable draft derived from active, otherwise active, otherwise newest
mutable scope draft. Immutable versions require an explicit copied draft.

Draft lesson locks are explicit future-regeneration commitments. Placement and lock
edits use `edit_revision`; lock edits refresh the version snapshot/fingerprint.
Solver-independent draft validation is separate from Stage 3 generation readiness.
Atomic publication revalidates freshness/completeness, locks the selected version and
active pointer, checks pointer revision, supersedes the old active version, and makes
the selected version immutable through the active pointer. Stage 4 itself added no
solver or worker; Stage 5.1 now builds generation on this boundary.

## Smart Timetable Stage 3

`timetable_slot_service.py` is the single composed-timeline authority for teaching,
non-teaching, and invalid slots. Full coverage disables a slot; a block wholly
between periods removes no slot; partial overlap is invalid; all-day and every-day
rules expand deterministically. Blocks never shift or shorten teaching periods.

`TimetableReadinessService` is read-only, solver-independent, and exact-scope. It
combines configuration, Planning demand, explicit/HRT teacher resolution, existing
teacher capacity, slot sanity, locks, and Stage 2 fingerprints. Generation-ready
means only that a future solve may be attempted, never that feasibility is proven.

## Capacity-Based Packaging And Common Customer Features

Starter, Professional, and Enterprise AI now represent organization scale, not
progressive access to normal customer modules. Their ceilings remain 1/5/25,
5/20/100, and 25/100/500 for active branches, operational staff users, and
teachers. Paid, active promo, and active customer-demo authority share the normal
customer baseline only after source/lifecycle, permission, tenant, branch, and
academic-year checks succeed.

`saas/customer_feature_policy.py` classifies that baseline and explicitly excludes
the Developer-only audit export. `saas.entitlement_service.evaluate_feature_access`
is the shared source-aware decision used by Advanced Reporting. Promo activation
and migration `20260819_001_capacity_based_customer_feature_baseline` persist the
same baseline without changing exact promo capacities or immutable promo history.
Standard, Full, and Custom demos retain the baseline; Custom controls only
legitimate scope, safety, experimental, and consumption policy.

Enabled AI features are commercially available across paid tiers, promo, and
active demo with `ai.use`. `saas/ai_consumption_policy.py` separately resolves
execution allowance. Existing reservations, counters, idempotency, and operation
events remain unchanged, and globally disabled AI definitions remain unavailable.

## Stage 5 SchoolGroup Authorization And Capacity Presentation

Direct operational SchoolGroup creation and deletion are global platform actions.
They require a Platform identity plus `schools.manage_all_schools` and the
corresponding `schools.create` or `schools.delete` permission. Tenant roles cannot
receive those create/delete permissions, and platform identity is checked again in
the handlers so stale permission state cannot cross the boundary. Tenant users with
`schools.edit` may update only their linked SchoolGroup; arbitrary IDs fail before
validation or mutation. Approved paid, demo, promo, and conversion provisioning
remain separate and unchanged.

School Management presents branch usage through
`saas/commercial_authority_service.py`, so paid and promo workspaces use the same
authoritative source-aware counts without exposing source internals. Branch create,
promo assignment, and entitlement remain atomic under the existing SchoolGroup lock.
The individual last-active-branch safeguard now counts only the target SchoolGroup.
`scripts/audit_schoolgroup_provenance.py` is a PostgreSQL-only, repeatable-read,
read-only report for active internal sandboxes that have neither tenant provenance
nor explicit workspace entitlement; it never remediates candidates.

## M4C Existing Workspace Paid Activation

M4C lets a verified tenant owner activate an existing `customer` workspace in
`provisioning` through Paddle without recreating onboarding or tenant data. The
durable `ExistingWorkspacePaidActivation` aggregate is anchored to SchoolGroup,
workspace UUID, SaaS account, tenant-owner link, selected plan, billing interval,
branch snapshot, quote fingerprint, checkout lineage, payment attempt, and a
SchoolGroup-anchored subscription contract. Checkout and payment rows use strict
pending-organization versus paid-activation contexts.

Professional and Enterprise AI quotes include every active operational branch;
Paddle quantity remains active branch count. Starter remains unavailable for
existing workspaces until restricted-branch enforcement is proven across all
operational entry points. Preparation creates no PendingOrganization,
ProvisioningJob, SchoolGroup, or pre-payment entitlement. Organization Account's
**Choose a Plan** action always opens plan selection while the activation is
editable. A saved `draft` or `checkout_ready` selection is highlighted but may be
replaced by another currently eligible plan, which rebuilds the authoritative quote.
Plan browsing and draft replacement make no Paddle API call and create no
PaymentAttempt. Once checkout is `checkout_started`, `payment_processing`, or in a
manual-review/inconsistent state, plan replacement fails closed. Billing identity is
stored against SchoolGroup and explicitly associates any reused Paddle customer
with the workspace. The association also snapshots the provider address and business
used by that workspace, so a shared SaaS account cannot make another workspace's
mutable customer defaults authoritative.

Only a verified matching `transaction.completed` event can activate access. In
one transaction TIS revalidates identity, quote, capacity, selected branches,
provider customer/address/business, price, quantity, currency, interval,
transaction, and subscription identity; then it confirms the contract and
subscription, creates paid workspace and branch entitlements plus the paid
TenantProvisioningLink, and changes lifecycle to `active`. Classification remains
`customer`. `transaction.paid` is processing only, browser return grants nothing,
and conflicting or stale evidence fails closed. Returned and reused transactions
must be billed, automatic-collection transactions whose item, price, quantity,
subtotal, interval, currency, customer, address, business, checkout URL, and full
custom-data lineage match the current quote. PostgreSQL lock acquisition refreshes
mapped state before duplicate webhook decisions. Existing promo, demo-to-paid,
and PendingOrganization checkout paths remain separate.

Organization Account presentation distinguishes commercial activation from payment
processing. A coherent `activation_required` workspace with no current payment
attempt displays **Activation required**. **Payment processing** requires a current,
unexpired existing-workspace `PaymentAttempt` in `checkout_started` or
`payment_processing`; failed, cancelled, and expired attempts display recovery states.
Workspace lifecycle `provisioning` alone is never payment evidence.

## M4B Controlled Existing Workspace Conversion

M4B converts an explicitly audited internal sandbox into a customer workspace
that still requires commercial activation. The durable conversion operation is
the ownership-claim record: it stores the exact workspace tuple, normalized
intended-owner email, approved M4A hash, canonical parameter hash, immutable
branch/commercial snapshots, setup state, actors, stage, status, and failure
code. Append-only conversion events contain only allowlisted redacted details.

Preparation creates no account and sends no email. The intended owner registers
and verifies through the normal TIS Account flow, explicitly claims the approved
workspace, and is aligned through the shared operational-owner identity rules.
No tenant ownership is granted before verification. The setup review accepts
only legal name, an IANA timezone, and educational program; existing display
name, country, branches, academic and operational records remain unchanged.

Final execution is PostgreSQL-only and locks the operation and SchoolGroup. It
re-audits immediately, requires exact identity and unchanged branch/dependency
and sandbox-entitlement evidence, then ends the internal entitlement and sets
`customer / provisioning` in one commit. It creates no active entitlement or
tenant source. M1 resolves this coherent state as `activation_required`, keeps
Organization Account access, and blocks operations until M3 promo activation.
Existing-workspace Paddle activation is deliberately deferred; new-onboarding
Paddle behavior is unchanged.

## M4A Existing Workspace Conversion Audit

M4A adds a generic read-only evidence boundary before any existing internal
sandbox can be considered for customer conversion. The service resolves one
explicit `SchoolGroup.id`, workspace UUID, exact name, and normalized intended
owner email. It inventories workspace metadata, identities, account links,
tenant/provisioning evidence, entitlements, paid/demo/promo records, and every
reflected branch foreign-key descendant. Logical branch references without a
database foreign key are reported separately for manual review.

The production CLI requires PostgreSQL and starts a repeatable-read, read-only
transaction. It outputs deterministic sanitized JSON or text, records the
transaction settings, and provides a stable SHA-256 snapshot hash. Exit `0`
means the audit is coherent, exit `2` requires manual review, exit `3` means
the supplied workspace identity does not match, and exit `1` is an execution
or configuration failure. Provider references remain presence flags. The CLI
always rolls back and performs no conversion, branch change, owner
alignment, entitlement or tenant-link mutation, Paddle call, or email. M4A
never approves hard deletion or write conversion; incomplete traversal,
identity mismatch, duplicate ownership, non-sandbox commercial authority, or
missing schema evidence fails closed for manual review. Recommended archival
IDs include only active branches with zero direct, transitive, logical, or
soft-deleted dependencies and are withheld when unmodeled branch foreign keys
exist.

## M3 Promo Redemption And Commercial Grants

M3 turns an approved promo definition into commercial authority only after an
authenticated, verified organization owner completes a resume-safe activation.
The workflow supports either a completed `PendingOrganization` or a separately
aligned existing `SchoolGroup` with a valid tenant-owner account link; it never
fabricates pending, payment, subscription, contract, or demo records.

Successful activation creates one immutable `PromoRedemption`, one immutable
capacity/plan/scope snapshot in `PromoGrant`, one promo
`WorkspaceEntitlement`, explicit branch entitlements and assignments, and a
promo-sourced `TenantProvisioningLink`. The link requires exactly one source:
paid contract, approved demo request, or promo grant. M1 resolves promo access
from that chain. Pending sessions grant nothing, expired or ambiguous grants
fail closed, and no Paddle API or billing record participates.

When eligible branches exceed promo capacity, the owner selects exactly the
covered branches. Every preserved workspace branch receives explicit evidence:
selected branches receive an assignment and active entitlement, while every
unselected branch, including an operationally inactive branch, receives an
inactive entitlement without consuming grant capacity or changing operational
status. Reactivation locks and rechecks M1 capacity, then activates the branch,
assignment, and entitlement in one commit. A PostgreSQL-only, dry-run-first
reconciliation command can add only deterministically missing inactive evidence;
ambiguous or contradictory chains require manual review. Staff and teacher records
are never selected or deactivated, and their authoritative counts must fit the grant.

Organization Account resolves the authoritative commercial source before choosing
its customer presentation. Paid authority continues through the Paddle-backed
subscription portal, demo authority keeps its dedicated journey, and promo authority
uses `commercial_portal_service` to compose the central commercial authority with
only attributable immutable promo metadata. The promo page shows the grant plan,
safe status and dates, masked reference, and authoritative branch/system-user/teacher
capacity. Operational promo access ends exactly at `PromoGrant.effective_to`;
`grace_period_days` is only a recovery window for Organization Account and paid
continuation and never extends operational access.

An expired or recovery-period promo owned by a verified tenant owner can enter the
existing-workspace paid activation flow. Checkout preparation and pending payment do
not change promo authority. Only verified provider completion locks and revalidates
the tenant, quote, capacity, promo source, and paid evidence, then atomically ends the
promo entitlement, relinks the existing tenant source to the paid contract, creates
paid workspace/branch entitlements, and preserves the SchoolGroup, workspace UUID,
branches, users, teachers, data, branding, and immutable promo history. Active-promo
early conversion remains blocked because promotional value is not paid credit.

`commercial_badge_service` converts centralized commercial access into one reusable,
source-aware Promo, Demo, or Paid badge view model. Organization Account and
commercial templates render that prepared identity and never infer authority from a
historical contract, grant, plan, or subscription row.

## M2 Promo Code Foundation

M2 adds secure, definition-only Starter, Professional, and Enterprise AI promo
administration under `/saas-admin/promo-codes`. Exact positive branch,
system-user, and teacher capacities must pass the existing SubscriptionPlan
ceilings and shared plan-capacity validator. Scope supports global,
organization, pending organization, account email, and email domain targets,
with coherent reinforcing restrictions and optional existing-branch snapshots.

Raw codes use at least 100 bits of secure randomness and are shown exactly once
in a `Cache-Control: no-store` response. TIS stores only an HMAC-SHA256 lookup
hash produced with the dedicated `TIS_PROMO_CODE_HMAC_SECRET`, a key ID, and
safe display prefix/suffix. Missing promo security configuration fails only
promo generation/future lookup, with no insecure fallback. Platform Developers
need `promo_codes.view` or `promo_codes.manage`; only Platform Owners activate
or terminally revoke. Row locks and allowlisted durable audit protect lifecycle
transitions. The M2 definition remains non-authoritative until M3 completes a
valid redemption; definition creation itself creates no entitlement, tenant
access, Paddle object, or M1 commercial-authority source.

## Subscription Capacity Presentation And Billing Entry

Customer subscription pages distinguish confirmed paid branch quantity from
the active plan's branch ceiling. Every active branch remains a Paddle quantity
unit; the plan ceiling describes only the largest organization the plan can
support. System-user and teacher counts remain included eligibility ceilings
and never become provider quantity. Review Capacity shows current paid branches,
required active branches, additional billed branches, the plan ceiling, and the
resulting minimum eligible plan without describing unused plan ceiling as
prepaid capacity. The approved commercial feature matrix is common across the
three self-service plans, so customer plan cards continue to show plan identity,
three capacity ceilings, current/eligibility state, and permitted plan-change
actions rather than a feature ladder.

An authorized operational organization owner or user with
`subscriptions.manage_billing` sees Billing & Subscription under System
Configuration. The bridge revalidates the operational user, selected tenant,
SaaS account-user link, and billing authority, then opens the existing
Organization Account subscription page. If SaaS account authentication is
required, only an allowlisted internal continuation is preserved through
password or social sign-in. Multiple-organization selection remains explicit,
restricted customers retain permitted recovery access, and external return
destinations fail back to Organization Account. The public landing action is
labelled Organization Sign In and continues to use centralized `/saas/login`;
it never defaults an organization owner into operations.

## Organization Account Sign-In Boundary

Public and onboarding SaaS Sign In authenticate through `/saas/login` and then
resolve the customer journey centrally. An activated organization owner or a
linked operational user with account-management permission lands on
`/saas/account`, which is the Organization Account Overview. That overview
exposes only permitted Organization Profile, Branches, Billing & Subscription,
and Account & Security sections. `/login` is never the default destination for
an authorized organization account manager; only the explicit Enter TIS
Platform action enters the operational authentication flow, where commercial
access and operational permissions are checked again.

Incomplete onboarding still resumes its authoritative setup step. Restricted
or suspended account managers remain in Organization Account with permitted
billing/recovery access and no active Enter TIS action. A linked operational
user without account-management permission follows the existing role-based
operational destination and receives no organization-owner or billing controls.
When one SaaS identity manages multiple organizations, `/saas/account` requires
organization selection before rendering the selected account overview. The
selected organization UUID is retained in an HTTP-only cookie, revalidated
against the account's tenant links and permissions on every request, and then
supplied to the existing entitlement resolver so Subscription Management uses
the selected tenant without weakening isolation. Password login, social login,
already-authenticated sign-in, SaaS root restoration, and post-verification
sign-in all use this same resolver.

## Initial Checkout Retry And Lineage Safety

The diagnosed Secure Payment failure was a local readiness rejection before
any Paddle API request. `_ensure_checkout_launchable()` rejected the legacy
`ready_for_checkout` pre-checkout billing state even though it could be
prepared safely. The verified Professional Annual catalog mapping remains USD
790 per active branch; two branches therefore produce Paddle quantity 2 and an
authoritative annual total of USD 1,580.

Initial Secure Payment authority is the current server-built quote plus its
plan selection, checkout session, and payment attempt lineage. A plan,
interval, branch quantity, capacity estimate, provider price, or quote
fingerprint change supersedes unfinished local sessions and attempts. Late
webhooks for those attempts are retained for review but cannot activate a
subscription or workspace.

Retry Secure Payment revalidates otherwise eligible unpaid onboarding state,
normalizes legacy pre-checkout billing status, and creates a fresh checkout
when the prior transaction is missing, incomplete, non-billed, or mismatched.
Compatible active Paddle customer addresses are reused by country. Only an
automatic, billed, launchable transaction for the current customer and quote
may be released to the public payment launcher. Provider diagnostics and
readiness failures remain logged server-side with tracebacks; customers
receive one structured safe alert without provider or internal details.

## Organization Billing Identity

Organization billing identity is explicit persisted organization state, not an
alias for the authenticated user's login identity. `OrganizationBillingProfile`
owns the confirmed billing email, legal/billing name, contact, optional company
and tax identifiers, and the supported billing address fields. Initial checkout
requires this profile. Authorized organization owners or users with
`subscriptions.manage_billing` may update it from Subscription Management;
changing it does not change login credentials, and changing login credentials
does not change billing identity.

`PaymentCustomer` persists the mapped Paddle customer plus
`provider_address_id` and `provider_business_id`. TIS synchronizes explicit
billing changes to the mapped customer, reuses
or updates one tenant-attributable active Paddle Business, updates the active
subscription's customer/address/business identity, and includes the mapped
business in new initial transactions. Ambiguous or failed synchronization fails
closed with customer-safe guidance and server-side diagnostics. Existing
financial documents are never silently rewritten; updated details primarily
apply to future billing documents.

Billing Contact is read-only until an authorized user explicitly selects Edit.
Valid local changes remain saved if Paddle synchronization fails. A dedicated,
tenant-scoped retry reuses the stored profile and existing customer, address,
and business mappings; an already synchronized retry is a provider-call-free
no-op. Provider failures are logged by safe step (`customer`, `address`,
`business`, or active-subscription identity) with provider status and error code,
while the customer sees no provider identifiers or diagnostics. Once a saved
profile is pending or failed, new plan and quantity mutations fail closed until
synchronization succeeds; cancellation and legacy subscriptions that have no
saved billing profile retain their existing behavior.

Paddle transaction states remain distinct. `paid` records that money was
received and is displayed as `Payment received - processing`; it does not
complete subscription reconciliation. `completed` remains the authoritative
processed-payment signal and is displayed as `Paid`.

## Organization Profile Save And Pending Logo Safety

Organization Profile accepts National, International, and Both through a
controlled selector and normalizes those values to the existing uppercase
codes. Missing or invalid customer input returns the same page with preserved
form values. Pending organization logos reuse the established image decoder
and 4 MB limit, allow PNG/JPG/WEBP only, enforce minimum dimensions, and use an
opaque unique filename plus atomic file replacement. A database or later save
failure rolls back organization changes and removes the newly written file;
an empty upload retains the current logo.

Pending logos currently use the application-local
`static/uploads/saas/pending_logos` directory and store only a relative public
path in `PendingOrganization`. This is not durable on an ephemeral production
filesystem. Persistent disk or object storage requires a separate deployment
and storage-architecture decision; this correction does not introduce one.
The initial Account Setup state is compact: one setup title, one explicit POST
start action, and the existing eight-step journey.

Branch Setup never totals nullable estimates in Jinja. The service normalizes
legacy/missing display values to zero in Python, while browser saves still
require explicit non-negative whole numbers for every active branch. New
pending branches receive explicit zero defaults.

After a pending logo is saved, Organization Profile and the shared School
Workspace identity area show it beside the organization name while retaining
the official TIS logo as platform branding. Checkout keeps the pending
reference. Paid and demo provisioning already converge on
`create_workspace_records()`, which copies the validated pending image into
the established primary `SchoolGroupLogo` slot. The operational shell renders
that organization-owned asset through its protected route and keeps the TIS
logo separate. A referenced pending file that is missing at activation now
fails provisioning instead of silently activating without the customer logo.

## Post-Verification Sign-In Safety

Successful email verification redirects by HTTP 302 to the GET
`/saas/login` page. The form submits by POST to `/saas/auth/login`. A newly
verified account with no School Workspace Setup record continues to the GET
`/saas/account` dashboard, where the existing explicit start action may create
the setup record by POST. Login continuations accept only known customer GET
destinations; POST-only, malformed, traversal, and external targets fall back
to Account Setup. A defensive GET request to `/saas/auth/login` redirects to
the normal sign-in page instead of exposing FastAPI's raw 405 response.

## Public Subscription Entry

The landing hero Subscribe Now action scrolls to the public pricing section.
Starter, Professional, and Enterprise AI then enter the public TIS Account
signup route with an allowlisted preferred-plan code. That preference is
non-authoritative: it creates no plan selection, checkout, payment attempt, or
Paddle object, and it is applied only after School Workspace Setup confirms the
plan remains eligible across branches, system users, and teachers. Invalid or
undersized preferences are ignored or cleared safely. Custom remains a
contact-only path.

## Three-Dimension Subscription Capacity

Self-service subscription eligibility is organization-wide across three
independent persisted limits: branches, tenant operational staff users, and teacher
records. Branch Setup stores required non-negative system-user and teacher
estimates on each active onboarding branch; legacy organization totals are
assigned to the primary branch only when no branch estimates exist, after
which organization totals are derived summaries.

Before confirmed payment, capacity authority is the active onboarding branch
count plus the greater of each branch-estimate total and the same workspace's
actual active count. After activation, actual active tenant operational users
and active teacher records are authoritative. Every distinct active tenant
User counts as staff regardless of role, title, position, or internal-test
attribution. An operational teacher-user with an active Teacher record
consumes one staff slot and one teacher slot. Platform users and account-only
SaaS identities do not consume tenant staff capacity.
Starter is 1/5/25, Professional 5/20/100, and Enterprise AI 25/100/500.
Exceeding any Enterprise AI limit requires the contact-only Custom path and
cannot create Paddle checkout.

Active Subscription Management uses that same three-dimension authority. The
Review Capacity flow accepts proposed branch, system-user, and teacher totals,
selects the minimum eligible plan from all three, and records the capacity
snapshot on a generated plan-change preview. Branch growth may therefore
produce one combined plan-and-quantity upgrade, while system-user and teacher
growth affects plan eligibility only. Paddle quantity always remains the branch
quantity; user and teacher counts never become billable units.

Plan downgrades remain scheduled for the next billing boundary and are checked
against all three live operational counts both before submission and again when
provider evidence says the downgrade is effective. If capacity no longer fits,
local activation stops in manual review and the current safe entitlement state
is preserved. Quantity reductions receive the same effective-date capacity
check. Cancellation remains provider-scheduled at paid-period end, preserves
tenant data and access through that date, and may be reversed while provider
lifecycle rules allow it.

M1 enforces post-activation growth through
`saas/commercial_authority_service.py`. The facade composes, rather than
duplicates, workspace classification/lifecycle, WorkspaceEntitlement,
TenantProvisioningLink, SubscriptionContract, PaymentSubscription, commercial
state/access, demo lifecycle, and plan capacity. Paid branch capacity is the
confirmed subscription quantity capped by the plan branch ceiling. Known
teacher IDs are normalized and deduplicated; each blank legacy teacher row
counts independently. Customer Demo and Internal Sandbox remain explicitly
unmetered in M1, while missing or contradictory authority fails closed.

Capacity-increasing branch, user, teacher, academic-year, and provisioning
paths lock the owning SchoolGroup, recount, evaluate the proposed final state,
mutate, and commit in one transaction. Existing over-capacity workspaces keep
their data and access but cannot further increase an exceeded dimension.

## Returning Customer Journey And Commercial Expiry

Returning SaaS-account login resolves authoritative onboarding, demo request,
account-to-workspace, workspace classification, lifecycle, and subscription
evidence. Incomplete onboarding resumes, pending demos open request status,
active demo or paid tenants enter operational login, unpaid customers reach
subscription setup, and expired customers receive branded expiry guidance.
Operational login and protected requests run the commercial guard before
branch, academic-year, or workspace page work; expected expiry never becomes a
500.

Paid-workspace access uses the same tenant-link and SubscriptionContract-linked
`PaymentSubscription` selected by `saas.entitlement_service`. A newer stale,
orphaned, or unrelated organization-level subscription row cannot replace that
authority, and Subscription Management and operational access consume that same
resolution. An unresolved, pending, failed, expired, canceled, or abandoned plan
upgrade remains a separate change request and does not revoke the currently
active plan. For example, active Professional access remains available while an
Enterprise AI upgrade is `payment_pending`. The
specialized plan-change `subscription.updated` handler synchronizes provider
subscription status while retaining the existing two-signal rule before the
target plan becomes authoritative.

For a production subscription whose provider state is authoritative but whose
local status is stale, replay the attributable stored, signature-verified
Paddle webhook through the existing webhook reconciliation path. Do not repair
commercial status fields manually. Confirm that `subscription.updated`
synchronizes the current `PaymentSubscription.status`; a pending plan change
must still wait for its separate required provider payment signal before the
target plan becomes authoritative.

Commercial access distinguishes active, trialing, payment processing, past due,
paused, canceled within a paid period, expired, suspended, archived, and
inconsistent states. Canceled subscriptions retain current entitlements only
through their confirmed current-period end. Ambiguous evidence fails closed and
uses verification guidance rather than falsely claiming expiration. Renewal
guidance appears only for a genuinely expired commercial state.

Expired demos select real public plans and intervals against the existing
organization and actual active operational branches. Checkout and confirmed
payment reuse the existing Paddle and conversion authorities, preserving the
SchoolGroup, workspace UUID, tenant link, users, branches, permissions, and
data. The Next.js landing derives Request Demo, Subscribe, Sign In, and Open TIS
App from `NEXT_PUBLIC_TIS_APP_BASE_URL`. Customer communications name the TIS
team; internal role names and audit evidence remain unchanged.

## M8B9 Demo Operations And Access Profiles

M8B9 adds Platform Owner-only orchestration in `saas/demo_operations_service.py`
and policy resolution in `saas/demo_access_service.py`. Owners can expire,
reactivate, set an unbounded future expiry, send final-day reminders, invoke
the existing lifecycle processor, and choose Standard, Full, or Custom access
at workspace or tenant-validated branch scope. M8B8 usage history is never
reset; permissions, commercial lifecycle, and feature entitlement remain
separate fail-closed checks. Material changes reuse M8B7 communications and
every attempt is durably audited.

## M8B8 AI Entitlement Foundation

M8B8 centralizes AI access in `saas.ai_entitlement_service`. A controlled
registry owns stable feature identifiers and temporary reviewed plan mapping.
Customer Demo receives two successful uses per feature; pre-execution
reservations block concurrent excess attempts, while failed/no-result work
releases capacity without consuming. Durable counters and operation events are scoped by
SchoolGroup, feature, and separate internal/demo/paid metric context. Existing
tenant resolution, `ai.use` permission, commercial state, demo expiry, and
paid `module.ai` entitlement remain distinct authorities. No AI business tool
or M8B9 operational control is included.

## M8B7 Demo Customer Journey

M8B7 makes normal Platform Owner approval orchestrate the existing independently retryable provisioning service. It adds a durable branded demo email outbox, deduplicated Platform Owner Notification Center events, a shared-shell active-demo indicator, atomic Day 6/expiry communication intents, and coherent expired-demo conversion after authoritative confirmed payment. The same PendingOrganization and then exactly one SchoolGroup are preserved. Production must schedule `python scripts/process_demo_lifecycle.py --apply`; dry-run remains the default. M8B8 and M8B9 are not included.

This is the first file future Codex or ChatGPT coding conversations should load. It is a compact project onboarding reference; detailed source of truth remains in the other Markdown docs.

## What TIS Is

TIS is Teacher Information System, a developing SaaS academic operations platform for schools and school groups. It connects teacher information, staffing and workload planning, academic calendars, observations, branch context, SaaS onboarding, billing, provisioning, and future AI-assisted academic decision support.

Public URLs:

- Public website: `https://tisplatform.com`
- Application portal: `https://app.tisplatform.com`
- Render must set `TIS_PUBLIC_BASE_URL=https://app.tisplatform.com` so transactional emails and background Workspace Activation emails generate production login and static asset URLs instead of local-development fallbacks.

Important routes:

- Operational login: `/login`
- SaaS signup: `/saas/signup`
- SaaS login: `/saas/login`
- SaaS account: `/saas/account`
- Platform console: `/platform`

## Current Architecture

The operational app is a FastAPI application at the repository root.

The FastAPI web process never creates tables or runs pending migrations during
import, startup, middleware, or background threads. Render must run
`python scripts/run_migrations.py` as its Pre-Deploy Command; only after that
command succeeds may Render activate the new web version. The Start Command is
`uvicorn main:app --host 0.0.0.0 --port $PORT`, which constructs the app,
performs only lightweight process-local startup checks, and binds without
PostgreSQL DDL. This boundary applies consistently to production, local
development, and tests.

Key files and folders:

- `main.py`: primary FastAPI app and many route handlers.
- `auth.py`: authentication, roles, platform identity helpers, permissions, sessions.
- `authorization.py`: protected route rules and access-denied handling.
- `permission_registry.py`: permission keys, groups, defaults, and developer-assignable permissions.
- `location_service.py`: global location picker lookup/validation. Must stay memory-conscious and scoped; do not restore full unbounded dataset parsing for normal picker requests.
- `ui_shell.py`: shared app shell/navigation/page metadata.
- `models.py`, `database.py`, `db_migrations.py`: data model, DB setup, local schema repair/migration logic.
- `routers/`: modular operational routes.
- `saas/`: SaaS account, onboarding, payment, billing, and provisioning services/routes.
- `saas/entitlement_service.py`: provider-confirmed commercial entitlement and paid branch-capacity resolution.
- `saas/commercial_authority_service.py`: unified operational commercial access, capacity counters, structured decisions, and tenant row locking.
- `saas/commercial_portal_service.py`: source-aware customer commercial presentation for promo-backed workspaces without duplicating commercial decisions.
- `saas/subscription_portal_service.py`: customer subscription portal view model.
- `saas/subscription_change_service.py`, `saas/subscription_plan_change_service.py`, and `saas/subscription_cancellation_service.py`: provider-authoritative quantity, plan, and cancellation workflows.
- `saas/subscription_lifecycle_service.py`: centralized lifecycle state and allowed-action policy.
- `saas/billing_history_service.py`: provider-sourced billing history and short-lived invoice download resolution.
- `saas/billing_identity_service.py`: explicit organization billing profile validation and Paddle customer/address/business synchronization.
- `saas/payment_lifecycle_reconciliation_service.py`: guarded reconciliation for attributable finalized payment evidence.
- `scripts/sync_paddle_price_ids.py`: environment-specific Paddle initial checkout price mapping sync into `subscription_plan_prices.provider_price_id`.
- `templates/`: Jinja templates.
- `static/`: static assets and generated documentation output.
- `tests/`: pytest coverage.

The public marketing website is separate:

- `tis-landing-website/`
- Next.js / Node runtime
- Source of truth for public landing implementation
- M8 landing integration exposes two public conversion paths through `NEXT_PUBLIC_TIS_APP_BASE_URL`: Request a Demo routes to `/saas/signup?intent=demo`, while Subscribe Now routes to `/saas/signup?intent=subscribe`.
- The selected intent is preserved through TIS Account signup and School Workspace Setup, then emphasized on the customer-safe commercial-choice page without removing the customer's ability to choose either path.
- Customer demo eligibility is reserved once per normalized organization domain. Existing Customer Demo history, including expired or converted demos, remains ineligible for a second demo; internal sandbox history does not consume customer eligibility.

Legacy FastAPI landing files are not the source of truth:

- `templates/landing.html`
- `static/landing/landing.css`

## Engineering Handbook

For deeper onboarding, read:

- `docs/engineering/README.md`
- `docs/engineering/TIS_MODULE_MAP.md`
- `docs/engineering/REPOSITORY_ARCHITECTURE.md`
- `docs/engineering/USER_AND_SYSTEM_FLOWS.md`
- `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`
- `docs/engineering/DEVELOPMENT_STANDARDS.md`
- `docs/engineering/UI_UX_DESIGN_PHILOSOPHY.md`
- `docs/engineering/PRODUCT_ROADMAP.md`
- `docs/engineering/REJECTED_DECISIONS.md`
- `docs/engineering/VISUAL_DOCUMENTATION_GUIDE.md`
- `docs/engineering/AI_OPTIMIZATION_GUIDE.md`
- `docs/engineering/PROJECT_GOVERNANCE.md`
- `docs/engineering/KNOWLEDGE_LIFECYCLE.md`
- `docs/engineering/KNOWLEDGE_IMPACT_ASSESSMENT_STANDARD.md`
- `docs/engineering/SELF_EVOLVING_WORKFLOW.md`
- `docs/engineering/AI_CODING_WORKFLOW.md`

These files explain module ownership, repository boundaries, end-to-end flows, and what must not be changed casually.

## Paddle Initial Checkout Configuration

Initial subscription checkout uses Paddle price IDs stored in `subscription_plan_prices.provider_price_id`. Use `scripts/sync_paddle_price_ids.py` with a structured sandbox or production mapping JSON to configure these values. Paddle credentials and endpoints remain environment variables. Real mapping files are ignored by Git; keep sandbox and live provider price IDs separate. If a mapping is missing, checkout fails closed before Paddle is called and customers receive a support-oriented Secure Payment message while internal diagnostics keep plan code, billing interval, and currency context.

Paddle transaction checkout uses a dedicated public SaaS payment launcher at `/saas/payment`. Configure `PADDLE_CHECKOUT_BASE_URL` to that page so Paddle returns transaction checkout URLs with `_ptxn` appended to the launcher instead of the operational app root. The launcher uses Paddle.js with `PADDLE_CLIENT_TOKEN` and `PADDLE_ENVIRONMENT`; never expose `PADDLE_API_KEY` in HTML or JavaScript.

## Domains And Routing

The public website lives at `https://tisplatform.com`. The app portal lives at `https://app.tisplatform.com`.

SaaS account routes are under `/saas`. Platform-owner SaaS administration routes are under `/saas-admin`. Operational tenant workflows use routes such as `/dashboard`, `/teachers`, `/subjects`, `/planning`, `/timetable`, `/academic-calendar`, and `/observations`.

## Completed M1-M5 Milestones

M1: SaaS identity foundation and separation between platform, tenant, and SaaS account identities.

M2: SaaS onboarding flow for organization, contacts, branches, academic setup, and review.

M3: Billing and plan foundation with plan catalog, checkout, billing status, and payment service boundaries.

M4: Tenant provisioning foundation with pending organizations, provisioning jobs, retry/run actions, and platform owner oversight.

M5: Platform access and owner controls, including platform owner/developer identities, permissions, and platform console behavior.

Platform Owner pending-organization views use a centralized owner lifecycle projection. The pending queue includes only records still in draft/setup, review, subscription checkout/payment, or incomplete/recoverable workspace activation. An active tenant link plus one coherent confirmed subscription, payment, contract, and active SchoolGroup resolves as Active Tenant and is excluded from pending counts. Completed-provisioning evidence that does not reconcile across those records is excluded from the normal queue and shown as Lifecycle Review Required in retained Organization Records. Historical onboarding fields are not rewritten by this projection.

## Completed M7 Subscription Management

M7 includes a normalized entitlement foundation, a customer Subscription Management portal, paid branch-quantity management, upgrades and scheduled downgrades, Paddle-authoritative previews and proration, scheduled cancellation and reversal, a centralized lifecycle/action policy, provider-sourced billing history, protected invoice downloads, and webhook/reconciliation safeguards.

Commercial state fails closed when ownership, provider evidence, or local relationships are ambiguous. TIS does not independently calculate replacement monetary values. Immediate changes require provider-confirmed outcomes; scheduled changes remain pending until provider/webhook evidence reaches the effective boundary.

## M8B-1 Workspace Classification Foundation

M8B-1 adds metadata-only workspace classification without changing customer behavior. `SchoolGroup` now owns an immutable workspace UUID, classification (`internal_sandbox`, `customer_demo`, or `customer_paid`), and lifecycle (`provisioning`, `active`, `suspended`, or `archived`). `PendingOrganization.workspace_intent`, `SaaSAccount.account_purpose`, and `User.is_internal_test_identity` preserve the corresponding pre-provisioning and identity intent.

All records that predate M8B-1 are confirmed test data. The controlled backfill classifies them as internal sandbox/test records; it is dry-run by default, transactional, idempotent, and records completion in `schema_migrations`. The separate diagnostic is read-only and reports tenant, onboarding, and Paddle relationship presence without exposing provider identifiers or secrets. Platform Owners can inspect workspace UUID, classification, and lifecycle in `/platform`; Platform Developers and tenant users do not receive that metadata block.

M8B-1 does not use classification for billing, entitlements, permissions, tenant isolation, reset eligibility, or customer routing. Demo workflows, conversions, Al-Andalus migration, memberships, and commercial-state resolution remain later work.

## M8B-2 Commercial State And Entitlement Foundation

M8B-2 adds a read-only commercial decision layer without changing customer access or billing behavior. `WorkspaceEntitlement` is the workspace-level entitlement envelope, `WorkspaceEntitlementValue` reuses the existing normalized entitlement catalog for features and limits, and `BranchEntitlement` optionally records whether a branch inherits, is explicitly active, or is commercially inactive.

The commercial resolver combines persisted workspace classification/lifecycle metadata with one coherent effective workspace entitlement. Customer-paid workspaces additionally require the existing M7 confirmed subscription entitlement resolution and matching `PaymentSubscription`; M8B-2 does not calculate billing state or contact Paddle. Missing, ambiguous, cross-tenant, orphaned, or invalid relationships fail closed to manual review.

These results are visible only to Platform Owners in `/platform`. They are not wired into tenant authorization, feature restrictions, branch behavior, onboarding, Paddle, demo expiration, or customer workflows. Internal sandbox workspaces created outside the migration retain a compatibility-only implicit entitlement so existing development flows remain unchanged.

## M8B-3 Demo Request Workflow

M8B-3 adds the first customer-facing commercial choice after completed onboarding: Request Demo or Subscribe Now. Subscribe Now continues into the existing plan-selection and Paddle workflow unchanged. Request Demo validates the verified account and completed organization, contact, academic, and branch setup before creating a `SaaSDemoRequest` in Pending Review.

The request records the requester, pending organization, submission time, customer-demo classification intent, provisioning commercial-state snapshot, and a fail-closed pre-provisioning entitlement snapshot. It does not create a SchoolGroup, workspace entitlement, subscription, checkout, or Paddle record. The workflow is separate from the legacy public marketing `DemoRequest` lead table.

Platform Owners have a searchable and sortable review queue. Approval records a review decision only; rejection requires a reason; owner cancellation and customer withdrawal are limited to Pending Review. Every transition creates durable audit and internal-notification events, but M8B-3 sends no email and performs no demo provisioning or activation.

## M8B-4 Demo Workspace Provisioning And Activation

M8B-4 adds a Platform Owner-only provisioning action for an approved SaaS demo request. The service fails closed unless the approval review, organization, customer-demo intent, pre-provisioning commercial snapshot, and entitlement snapshot remain coherent and no workspace has already been provisioned.

Demo provisioning reuses the paid provisioning engine's shared workspace-record builder for the SchoolGroup, branches, academic year, owner user, account link, role permissions, and branding. It creates no Paddle, payment, subscription-contract, payment-subscription, checkout, or billing record. A demo-backed `TenantProvisioningLink` identifies the operational tenant without fabricating a paid contract.

Workspace records, the demo entitlement, tenant link, request linkage, and activation are committed atomically. A failed attempt rolls the workspace changes back, leaves the request Approved and unprovisioned, and records a retryable failure outcome. Successful activation sets the SchoolGroup and demo entitlement active, records activation metadata and audit/internal events, and prevents duplicate provisioning. M8B-4 sends no email and implements no expiration, scheduler, login restriction, or conversion behavior.

## M8B-5 Standard Customer Demo Lifecycle

Every customer-demo workspace lasts exactly seven days from the M8B-4 `activated_at` timestamp. Day 6 reminder and Day 7 expiration timestamps are derived from that single authority, calculated with timezone-aware UTC values, and displayed in the onboarding organization's IANA timezone. Missing or inconsistent timestamps fail closed.

`saas.demo_lifecycle_service` is the authoritative read-only resolver and independently callable processor. It resolves Active, Reminder Due, Expired, Suspended, or Manual Review; creates idempotent internal Day 6 notifications for the requesting SaaS account and active Platform Owners; and atomically ends the demo entitlement and suspends the SchoolGroup at expiration. Workspace users, branches, and all tenant data remain preserved.

The operational authentication middleware checks customer-demo commercial access on every protected request, including existing sessions. Active and reminder-due demos continue normally. Expired or ambiguous demos are redirected to the subscription activation experience, while protected API/download requests receive a customer-safe 403. Platform users, paid workspaces, internal sandboxes, public/authentication routes, secure logout, and SaaS subscription routes are unaffected. Access-block auditing is deduplicated.

Run the lifecycle processor safely with `python scripts/process_demo_lifecycle.py --dry-run`; use `--apply` only for scheduled execution after validating the report. M8B-5 sends no email and adds no extension, conversion, archive, deletion, or read-only expired mode.

## M8B-6 Demo-To-Paid Conversion

An active Customer Demo may enter the existing subscription checkout without closing or recreating its operational tenant. After `transaction.completed` establishes one confirmed active M7 subscription for the same pending organization, `saas.demo_conversion_service` atomically converts the existing SchoolGroup from `customer_demo` to `customer_paid`.

The conversion preserves the workspace UUID, SchoolGroup, tenant link row, organization, branches, users, permissions, academic data, and all demo/request/audit history. It ends the demo entitlement, creates a paid entitlement linked to the confirmed `PaymentSubscription`, moves branch entitlement links, and replaces the tenant link's demo source with the confirmed `SubscriptionContract`. Existing M7, workspace-entitlement, and commercial-state resolvers must then resolve the same tenant as Customer Paid Active.

Conversion Requested, Processing, Completed, and Failed states are durable and retryable. Any conversion failure rolls back workspace mutations while retaining confirmed provider payment records. Expired, invalid, ambiguous, cross-tenant, internal-sandbox, paid, or already-converted workspaces fail closed. Completed conversions no longer enter demo reminder or expiration processing.

## Test Workspace Reset Dependency Rule

The Platform Owner-only test workspace reset keeps its existing preflight and single-transaction rollback behavior. Before it deletes scoped operational `User` records, it deletes `SubscriptionChangeRequest` rows scoped by the selected workspace's authoritative `school_group_id`. It also deletes selected workspace-entitlement values and branch-entitlement children before the selected `WorkspaceEntitlement`, which is removed before the final `SchoolGroup`. This prevents user, account, contract, subscription, and entitlement foreign-key references from blocking removal while preserving records belonging to every other workspace. Pre-analysis and structured deletion diagnostics report the same scoped record set.

The same Platform Owner-only test reset is a clean-room exception for internal M8 testing only. Within its existing single transaction, it deletes the selected pending organization's linked demo request, domain-eligibility reservation, review and audit history, demo provisioning/lifecycle records, and demo-to-paid conversion history before removing their parents. It also resolves the selected organization's domain through the same customer-demo resolver and may remove a detached reservation only when no other organization, request, workspace, or customer account uses that domain and the reservation has no historical manual-review evidence. Analysis exposes a separate list of safe detached reservation IDs; deletion consumes that exact list, flushes before parent deletion, and verifies that none of those IDs remain. A mismatch, remaining row, conflicting ownership, or historical ambiguity blocks or rolls back the reset. This allows the same test email and organization domain to complete a new internal journey after a reset. The normal customer one-demo-per-domain reservation policy is unchanged; global plans, prices, Paddle records, platform configuration, and records from other organizations remain preserved.

Historical detached demo-domain reservations whose owning organization and account were already removed are managed separately through the Platform Owner-only `/saas-admin/demo-eligibility-maintenance` workflow. It scans eligibility rows, reuses the authoritative domain normalization/resolution rules, and fails closed when any matching organization, account, request, tenant-profile workspace, provisioning record, subscription evidence, conversion, or manual-review marker remains. A confirmed deletion locks and re-analyzes one exact eligibility ID, deletes only that ID, flushes, verifies absence, and commits through the owner route. Durable audit records identify the owner, eligibility ID, domain, previous status, timestamp, and maintenance reason. This administrative repair path does not alter normal Customer Demo eligibility or the clean-room reset.

## Current SaaS Account Verification State

Phase 1 TIS Account email verification recovery is accepted. Valid verification links now mark the SaaS account email verified/active and redirect to the TIS Account login page with a professional success notice so the customer can continue school workspace setup.

Expired or invalid verification links no longer dead-end. They show a recovery page with a resend verification form. Resend verification handles unverified accounts, already verified accounts, and unknown email addresses with safe customer-facing messaging that does not reveal account existence. Password-based accounts that remain unverified are blocked from starting or continuing school workspace setup.

This Phase 1 verification recovery work did not change payment, billing, provisioning, database schema, migrations, operational modules, or the Next.js landing website. Google/Microsoft login remains future work and was not implemented.

## Current SaaS Customer-Facing Language State

Phase 2 TIS Account wording cleanup is accepted for customer-facing account and school workspace setup pages. Customer-visible account/setup pages now avoid presenting "SaaS" and technical identifiers as product language, while internal `/saas` routes, modules, models, and stored statuses remain unchanged.

The customer journey should use professional labels such as "TIS Account", "Account Dashboard", "School Workspace Setup", "Organization Profile", "Branch Setup", "Academic Setup", "Subscription Setup", "Secure Payment", and "Workspace Activation". Customer templates should label internal billing, payment, onboarding, and activation statuses through customer-safe display labels instead of raw database statuses such as `tenant_active`, provisioning states, checkout session states, provider identifiers, plan IDs, school group IDs, attempt UUIDs, or provider subscription/transaction IDs.

The shared TIS Account customer shell uses an official TIS logo image so customer account/setup forms inherit official branding. The light account shell uses the full-color horizontal logo variant, and transactional account emails use an existing official dark-blue wordmark asset. This wording/logo pass did not change payment, billing, provisioning behavior, database schema, migrations, operational modules, or the Next.js landing website. Google/Microsoft login remains future work and was not implemented.

## Current TIS Account Guided Setup Framework State

Phase 3A shared guided setup framework is accepted for the TIS Account dashboard only. The customer account shell now supports a shared setup console with the official TIS logo, an 8-step journey stepper, a current-step/status area, one primary next action, and concise guidance. The account page uses this framework to answer "What should I do next?" without dashboard statistics.

The 8 customer-facing journey steps are TIS Account, Email Verification, School Workspace Setup, Review & Confirmation, Subscription Selection, Secure Payment, Workspace Activation, and Enter TIS Platform. The display state is calculated from existing account, onboarding, billing, payment, and activation data without changing stored statuses.

This Phase 3A work did not redesign onboarding forms, subscription/payment pages, or billing/status pages. It did not change payment, billing, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, or admin views.

Phase 3B redesigned the five School Workspace Setup onboarding pages on top of the Phase 3A shared shell: Organization Profile, Branch Setup, Academic Setup, Primary Contact, and Review School Workspace Setup. The pages now use consistent guided-wizard sections, a single shared-shell primary CTA, secondary Back/Save Draft actions, concise guidance, and lower visual clutter while preserving all existing form actions, field names, validation behavior, draft behavior, and onboarding state transitions.

Phase 3B did not redesign subscription/payment/billing/status pages and did not change payment, billing, provisioning behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, or admin views.

Phase 3C redesigned the customer-facing Subscription Selection, Secure Payment summary, Payment Return, Payment Cancel, Subscription Status, and Workspace Activation status pages on top of the Phase 3A shared shell and Phase 3B guided style. These pages now use one shared-shell primary CTA, customer-safe payment/activation labels, clearer browser-return messaging, and explicit guidance that TIS Platform access becomes available after Workspace Activation.

Phase 3C did not change payment behavior, billing behavior, provisioning behavior, webhook logic, checkout start/launch behavior, database schema, migrations, operational modules, the Next.js landing website, Google/Microsoft login, internal `/saas` route names, stored statuses, or admin views.

## Current Priority

Current priority is automatic KMS synchronization enforcement and reliable post-M7 engineering context:

- Markdown is source of truth.
- PDF is generated snapshot.
- Change history preserves chronological change context.
- ADRs preserve major decisions.
- Module history preserves deeper area-specific evolution.
- Platform Owner Knowledge Center is implemented as a read-only owner utility with manifest-backed document titles, summaries, logical groups, client-side search, category/module/freshness filters, and latest-activity ordering.
- The Knowledge Center uses protected routes for PDF view/download and source-specific `pdf_page` deep links; it does not link directly to static PDF paths.
- KMS v3.0 Phase 3A adds a true engineering handbook with module map, repository architecture, workflows, and developer onboarding.
- KMS v3.0 Phase 3B adds database architecture, development standards, UI/UX philosophy, product roadmap, and stronger human/AI developer guidance.
- KMS v3.0 Phase 3C adds rejected decisions, visual documentation framework, AI optimization guidance, project governance, and decision traceability.
- KMS v3.0 Phase 3D completes KMS v1.0 lifecycle standards, dependency mapping, AI coding workflow, and future automation roadmap.
- Root `AGENTS.md` makes KMS onboarding mandatory for Codex tasks.
- `.kms-impact.yml` is the machine-readable task declaration.
- `scripts/kms.py sync` is the single local synchronization command; it validates KIA before writing, regenerates the PDF/manifest, then verifies freshness.
- `scripts/kms.py check` is the single read-only local and CI validation command.
- `scripts/check_kms_impact.py` validates major-change classification, declared Markdown updates, and generated-artifact freshness.
- GitHub Actions block pull-request integration and production deployment when KMS validation fails.

## Smart Timetable Architecture Baseline

ADR 0026 governs timetable evolution. Planning remains authority for section
demand, subject requirements, assigned teachers, and HRT fallback; one placement
means one teaching period, and `Subject.weekly_hours` remains the compatibility
weekly-period authority. Timetables are durable SchoolGroup/Branch/Academic-Year
versions. Active selection is a separate unique exact-scope pointer, not a version
Boolean. Active, superseded, and archived history is immutable; drafts are mutable.

Stages 2–5.1 provide models, migrations, snapshots/fingerprints, lock persistence,
version services, readiness, comparison, validation/publication, durable generation,
and version-aware views/exports. Stage 3.5 supplies one composed per-day timeline and
solver-ready teaching slots. Stage 5.1 adds worker-isolated CP-SAT, independent
candidate validation, Generate/Regenerate actions, and atomic unpublished results.
Existing and published placements remain unchanged unless the separate publication
flow is used. Availability, room/resource, preferences, quality scoring, and broader
Stage 5.2 UX remain future work.

## Critical Rules

- Do not touch SaaS flows unless explicitly approved.
- Do not touch operational logic unless required by the approved task.
- Do not touch database migrations or `tis.db` unless explicitly approved.
- Do not weaken tenant isolation.
- Do not bypass permissions or platform owner checks.
- Do not merge platform user, SaaS account, and tenant user concepts.
- Do not change landing page implementation unless explicitly approved.
- Do not add a KMS regenerate button until explicitly approved.
- Do not push or commit unless explicitly requested.
- Treat production memory as a hard budget. Do not add unbounded full-dataset caches, duplicate production template renders, startup-heavy work, or warning-level debug spam on normal requests.

## KMS Policy

Every implementation must include a Knowledge Impact Assessment:

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

If included docs change, synchronize:

```powershell
.\.venv\Scripts\python.exe scripts\kms.py sync
```

## Development Workflow

1. Read this file first.
2. Read root `AGENTS.md`, `docs/TIS_MASTER_CONTEXT.md`, and `docs/PROJECT_STATE.md`.
3. Read `docs/engineering/README.md`.
4. Read `docs/engineering/DEVELOPMENT_STANDARDS.md`.
5. Read `docs/engineering/AI_OPTIMIZATION_GUIDE.md`.
6. Read `docs/engineering/AI_CODING_WORKFLOW.md`.
7. Read relevant engineering docs, ADRs, module history, and supporting docs.
8. Inspect code before editing.
9. Keep changes scoped.
10. Update `.kms-impact.yml` and affected KMS docs when meaningful behavior, architecture, product state, module map, repository ownership, data model, design philosophy, roadmap, governance, decision traceability, automation, lifecycle, or workflow changes.
11. Run `scripts/kms.py sync` if included source docs changed.
12. Run `scripts/kms.py check` for final read-only validation.
13. Run implementation validation.
14. Report KIA in final response.

## Landing Page Situation

The public landing implementation is in `tis-landing-website/`. Marketing docs live under `docs/marketing/`. Do not modify legacy FastAPI landing files unless explicitly approved.

## Next Planned Work

Review the automatic KMS enforcement baseline, keep M7 subscription documentation synchronized as follow-up fixes evolve, and later consider an explicit owner-only regenerate action. Any regenerate action may rebuild artifacts from reviewed Markdown only and must not rewrite source prose.
## Timetable feasibility authority (2026-08-30)

Deterministic timetable readiness ends at `configuration_complete`. The
`timetable_feasibility_verifications` ledger stores a hard-only CP-SAT result by
SchoolGroup, branch, academic year, immutable snapshot, and full input
fingerprint. Generate is permitted only for an exact verified fingerprint. The
validated placements are reused as an optimization hint and as the independently
validated timeout fallback; soft objectives do not participate in verification.
