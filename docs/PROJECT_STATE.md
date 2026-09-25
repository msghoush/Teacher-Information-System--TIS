---
title: TIS Project State
documentation_version: 5.26
last_updated: 2026-09-25
source_of_truth: true
---

# TIS Project State

## Final Production Follow-Up Closure, Part B - central organization Talent configuration authority (2026-09-25)

Implemented on `dev`; Web Service only; not deployed. No schema, migration, new permission key, stored
grant change or `tis.db` change. Owner clarification: there is NO Branch copy/clone/enablement model; the
SchoolGroup-level architecture is desired. Programs, Frameworks/Rubrics, Competencies/Indicators, KPI and
review-candidate policy, annual Program configuration, Evaluation Plans/Periods and Assessment Cycle
definitions are shared configuration created and governed ONCE by the organization Administrator and used
by every Branch. Branch state is only Students, Academic Placements, Cycle population evidence,
Assessments, results and Branch analytics/history. `TalentProgram` still has no `branch_id`.

**Permission reality before Part B (code and tests inspected; production stored rows could not be read).**
The default role matrix is code-defined (`permission_registry.DEFAULT_ROLE_PERMISSIONS`), not seeded data:
Administrator holds every non-platform key including every `talent_*` key; Editor and User hold NO
`talent_*` key (`_EDITOR_LIKE_PERMISSIONS`); Limited holds none and `constrain_role_permissions` strips any
Talent grant; Platform Owner holds all; Platform Developer holds all assignable keys. Stored rows
(`seed_*_role_permissions`, Role Permissions UI) and per-user overrides (ADR 0040: Deny always wins, Allow
only where the role already allows) mean a stored role row can still grant an Editor/User a Talent key, but a per-user Allow cannot add a key the role denies. Route gates: Program /
Framework / Competency / Rubric / KPI / policy / annual-configuration create and edit =
`talent_programs.manage` ONLY (no organization-scope gate: a Branch-scoped Administrator could author
organization-wide configuration, and an existing test pinned it as "Branch author may draft"); framework
activate/retire and Program lifecycle = `talent_programs.govern` + organization scope; Program delete =
`.delete` + organization scope; Competency / Rubric Level delete = `.delete_competency` /
`.delete_rubric_level`; Evaluation Plan create, Period add/edit/reorder/remove, activate, cancel, close,
rollover, Cycle link/unlink = `talent_evaluation_plans.manage/.manage_timeline/.delete_period/.govern`
(+ `talent_assessment_cycles.manage`, `.select_period` for linking) with organization scope; Assessment
Cycle create/edit-Draft = `talent_assessment_cycles.manage` ONLY; Cycle open/close/synchronize =
`.govern` + organization scope. The UI already withheld only `programs.govern`, `plans.manage/.govern` and
`cycles.govern` from Branch scope.

**Change.** Authority = the existing semantic permission (default Administrator-only) AND organization/global
access scope, enforced structurally in each router's `_authorize` (`CONFIG_MUTATION_KEYS`,
`CYCLE_CONFIG_KEYS`, `PLAN_CONFIG_KEYS`; 403 `organization_authority_required`) rather than per handler.
Reads (`.view`), shared-configuration use, `talent_evaluation_plans.select_period` and every assessment /
result / analytics permission are untouched, so a Branch operational user (Start/complete Assessments,
Branch results) is unaffected. Cycle open/close stays configuration governance (it freezes the whole
SchoolGroup population), not a Branch operational action. `talent_ui` now also withholds
`programs.manage`, `programs.delete_competency/.delete_rubric_level` and `cycles.manage` from Branch scope
(server-derived capability hints for the existing `can()` mechanism), publishes `talent_can_configure`, and
the Programs and Evaluation Plan views show "Shared by all Branches" copy (read-only wording for actors who
cannot configure); the Program summary reads "View Evaluation Plan" instead of "Manage" when read-only. No
Program Status lifecycle UI was reintroduced.

**Residual (owner-visible).** (1) A Branch-scoped Administrator LOSES configuration authoring (deliberate;
supersedes the earlier M2/M4 "Branch author may draft" wording, which is preserved as history). (2) Stored
custom grants are NOT revoked: an ORGANIZATION-scoped non-Administrator whom an administrator explicitly
granted a configuration key can still mutate; Branch-scoped holders of any role are denied server-side. If
the owner wants strictly Administrator-role-only mutation, that is a one-line role check plus a stored-grant
review, deliberately not done. (3) Existing duplicate Programs are NOT merged, deleted or rewritten. The
read-only `scripts/audit_talent_program_duplicates_readonly.py` lists suspected duplicates per SchoolGroup
(case/hyphen/whitespace, Branch-name variants, identical framework structure), per-Program framework /
annual-configuration / plan / Period / history-reference counts, whether a merge would be destructive, and
counts of non-Administrator configuration grants; production data was not audited here.

Tests: `tests/test_talent_central_configuration_authority.py` (inventory of all 47 mutating configuration
routes, role x route, per-route permission-key mapping, platform actors, a Branch operational Editor still
starts Assessments, tenant isolation), `tests/test_audit_talent_program_duplicates_readonly.py`, UI additions
in `tests/test_talent_ui.py`, Node additions in `tests/talent_program_workspace.test.cjs`, and the deliberate
replacement of the old Branch-author test in `test_talent_program_framework_foundation.py`.

## Final Production Follow-Up Closure, Part A - Start Assessment must actually work (2026-09-25)

Implemented on `dev`; Web Service only; not deployed. No schema, migration, permission, privacy or
`tis.db` change. Part B (central configuration authority) is separate and not started here.

**Root cause (proven by failing-first tests).** The Student Assessments roster is Grade-agnostic
(ADR 0035/0039: every currently placed Student in the Academic Year is listed) while Start Assessment
is Grade-aligned (ADR 0039 amendment 2026-09-12: only criteria for the Student's Grade plus
intentionally unscoped criteria; another Grade's criteria are never substituted). The roster therefore
drew an enabled "Start Assessment" for Students whose Start was guaranteed to fail with the safe 400
code `assessment_tool_unavailable`; Part 1 only curated the copy of that failure. Which exact code
production returned could not be observed here, but every other realistic cause traced (grade format,
string/number ids, planned-but-unmaterialized Periods, Draft/legacy Cycle, Branch filter, post-start
workspace reads) was proven sound; Grade values are DB-constrained to the same canonical set on
Placement and Competency, so a "Grade 3" versus "3" mismatch cannot exist.

**Fix.** One backend predicate. `talent_student_assessment_service.roster_start_states` reuses
`_newest_assessable_framework` (the exact check `start_assessment_for_evaluation` enforces, in the same
order: criteria first, then the duplicate-current-Assessment guard). `GET
/api/talent/assessment-cycles/{id}/eligible-students` now returns per row `can_start`,
`start_block_code` (`assessment_tool_unavailable` or `duplicate_assessment`) and a fixed bounded
`start_block_reason`; roster membership and Branch/Year/tenant scoping are unchanged. The browser
renders the Start button only when `can_start === true` (never derived client-side); a blocked row shows
the bounded reason instead, and names the Program setup as an enabled link only for an actor holding
`talent_programs.manage` (others get text only). `POST /api/talent/assessments` accepts the optional
displayed `program_id` / `academic_year_id` and answers 409 `context_mismatch` if either differs from the
Cycle (the Cycle stays the only authority; nothing starts in another Program/Year); the client sends them
and lists no roster (and offers no Start) when `cycle_id` is not among the server-filtered Evaluation
contexts of the selected Program/Year. `context_mismatch` has curated copy.

**Unchanged and proven.** Tenant isolation, Branch ceiling (a Branch-limited actor cannot start another
Branch's Student; an organization actor can start any authorized Branch's Student under any page
Branch), permission enforcement, immutable evidence, Start on an in-progress or completed Student is a
409 duplicate (the roster opens the existing workspace / reassessment actions instead). Tests:
`tests/test_talent_start_assessment_eligibility.py` (per-row `can_start` versus the real route as a
property over criteria fixtures and three actors), Node additions in `tests/talent_operations.test.cjs`.
Open decisions: a Closed Cycle is not blocked from Start (existing semantics, ADR 0035; unchanged); each
Student started on a newer Framework gets a private derived Cycle (existing behavior, unchanged).
Browser verification not performed.

## Production follow-up Part 2 - chart types, Results & Analytics filter UX, comparisons, Progress Over Time (2026-09-25)

Implemented on `dev`; Web Service only (static JS/CSS and one template script include); not deployed.
No schema, migration, permission, analytics-semantics, privacy-threshold, Classification or Learning
Style policy or `tis.db` change. Verified through the Node stub harness only (no browser).

**D. Chart type semantics.** Root cause: the selector offered "Bar" and "Percentage", which drew the
same picture (Bar already printed the percentage), and Pie beside Doughnut (same reading). Now
`talent-charts.js` switches only genuinely different visualization types and renders no selector when
only one type is valid: Classification and Assessment completion = Bar / Doughnut (only for a full
public partition of at most `MAX_CIRCULAR_CATEGORIES` = 8 categories); Learning Style (eight styles plus
Unassigned = nine) and Rubric levels (ordinal) = Bar only, keeping the stable per-index semantic colours
(Unassigned is always the neutral last colour); time series = Trend / Bar (Trend only with two visible
points); comparisons = one fixed Bar of the backend rate per group. Pie was dropped as a doughnut
without a centre (owner decision open). Exact counts/percentages stay in every type (bar label, legend,
trend legend) and in the accessible table. The Overview defaults Classification and completion to
Doughnut where valid (Bar otherwise); Results & Analytics defaults to Bar. A deliberate choice is
remembered across refetches. The Overview gets ONE restrained CSS entrance (fade, bar grow) on its first
render only, decided in `talent.js` from `prefers-reduced-motion` (reduced or unknown = none), applied
with opacity/transform only, and removed on a chart-type switch.

**E. Results & Analytics filter UX.** Root cause: every dashboard filter change replaced the whole
content root with a loading skeleton (`root.innerHTML = ...` then a second full replacement in `load()`),
collapsing the page height so the browser clamped the scroll to the top, and re-created the form (focus
lost). Now Branch/Grade/Section/Program/Period/Classification/Competency/Indicator/comparison changes
call `refreshDashboard()`: local `params` + `history.replaceState` (no navigation, submit cancelled),
a background fetch with its own `AbortController` and a monotonically increasing token (only the newest
response renders), the previous analysis stays on screen with `aria-busy`, a dimmed region and a thin
bounded progress bar, the region height is held while replacing and the reader position is restored
(focused control re-focused with `preventScroll`, relative `scrollBy` compensation, `scrollTo` only if
the browser clamped anyway). Comparison tick changes are debounced (350 ms). The existing 25 s bounded
request applies; a failure keeps the old analysis and shows an inline retryable error. Chart-type change
is purely client-side (no fetch, no URL change). `load()` also holds height and restores the anchor for
other views. The `scrollIntoView` in `talent-operations.js` belongs to the assessment editor and is not
on this path.

**F. Selected Comparisons.** One dedicated section, last in Results & Analytics, contains the Compare-by
selector, the group checkboxes (up to six; the seventh is disabled/refused, count announced), then the
"Completion rate by group" chart and the per-group Completion/Classification/Result cards, with explicit
empty, protected and unavailable states. The selector was removed from the top filter form. Group values
are the backend's own per-group rates; nothing averages Programs or frameworks.

**G. Progress Over Time - decision: KEEP as a real per-Program longitudinal view.** Evidence: the view is
backed by the governed ADR 0027 route `/api/talent/organization-analytics/programs/{id}/longitudinal`
(one Program x one Academic Year, ordered by governed Evaluation Period, each point independently
privacy-closed, five metrics incl. counts and started coverage, comparability state, no computed
delta). Results & Analytics offers only a completion-by-period line, so the view has distinct value
(counts, started coverage, comparability context). The previous plot drew percentage bars only; it now
uses the shared trend chart with honest gaps (a suppressed or not-yet-available period is a dashed gap
with no coordinate; "No data yet" is never 0%; count metrics plot counts) plus the accessible table, and
Results & Analytics links to it for a chosen Program. Not done (needs new backend semantics or owner
decision): multi-year series, Classification-over-time, Branch comparison trend, rubric-indicator trend.
The nav key and route are unchanged, so old links keep working; the template now loads `talent-charts.js`
on that view.

**I. Cleanup.** Raw arrow glyphs in actions replaced by a shared inline SVG chevron; duplicate chart
controls removed (D). Tests: `tests/talent_part2_experience.test.cjs` (P1-P22) plus deliberate updates to
the old mode pins in the `talent_dashboard`, `talent_visual_system`, `talent_classification_withheld`
and `talent_results_experience` tests and the harness (scroll model, writable hooks).

## Production follow-up Part 1 - Talent Branch authority, Start Assessment, Classification (2026-09-25)

Implemented on `dev`; Web Service only; not deployed. No schema, migration, permission,
privacy-threshold or `tis.db` change.

**A. Branch authority (owner-directed amendment to the Batch 1 closure).** The sidebar
selector lists real Branches only; the Talent "All Branches" option, the `branch_scope=all`
marker cookie, `user.scope_all_branches` and `POST /scope/branch branch_id=all` are removed
(an old cookie is ignored and grants nothing; choosing a Branch still clears it).
`talent_branch_scope.talent_branch_ceiling` is always `None`; `branch_scope_unrestricted`
is `auth.can_access_all_branches`. Organization-authorized actor: ceiling = own authorization
(all Branches of the SchoolGroup); the sidebar Branch is the page default (`tp-config.branch`);
the page-level Branch filter offers All Branches (URL marker `branch_scope=all`, no `branch_id`
sent) and every authorized Branch; a stale marker from another sidebar Branch resets to the new
default. Branch-limited actor: `tp-config.branchLocked`; the ceiling stays their authorized
Branch on every read surface (server enforced, regression: `tests/test_talent_branch_hard_scope.py`);
an explicit foreign or cross-tenant Branch is rejected as before. Omitted `branch_id` = all
authorized Branches (it is how All Branches is expressed); the default is applied by the page.
Branch display: legacy startup seeding uses hyphenated Branch names (`X-Boys`); persisted names
and Talent presentation were NOT changed (reported as a separate data/presentation decision).

**B. Start Assessment.** Trace: roster button (`type="button"`, no form/`#`) -> POST
`/api/talent/assessments {cycle_id, student_id}` -> navigation with `assessment_id`, `cycle_id`,
`academic_year_id`, `program_id` -> workspace reads. Backend regression proves the whole chain for
organization actors under every sidebar Branch and for a Branch-limited actor
(`tests/test_talent_start_assessment_flow.py`); string/number id typing does not matter. Root
cause of the banner: a stable, safe 400 business code (chiefly `assessment_tool_unavailable`, a
Student whose Grade has no saved criteria in the Program; also `student_not_eligible`,
`invalid_student_context`, duplicate/conflict) was collapsed by `talent-api-errors.js` into the
generic 400 copy and shown in the page-top banner via `scrollIntoView`. Fix: curated fixed copy per
code (`CODE_COPY`, backend `detail` still never echoed) shown inline beside the row; no scroll jump,
no navigation on failure. Which code production returned could not be observed here.

**C. Classification "Unavailable".** Diagnosis (reproduced, `tests/test_talent_classification_aggregate_privacy.py`):
every Student is classified; the aggregate is hidden at the PRIMARY privacy stage
(`apply_primary_privacy` inside `build_bucket_projection`, class P4) by the approved Release 1
provider (`ConfiguredRelease1PrivacyPolicy`, minimum cohort 5 per Classification band cell, zero
counts included; ADR 0028, B11-E F1), then complementary suppression; a total below the floor hides
the whole family; an absent provider configuration fails closed (`restricted`). Broader selections
publish exactly the bands that clear the floor. Behavior is unchanged. UI: one uniform, value-free
sentence (`data-chart-withheld-note`) and a precise whole-family message; no threshold, cell-level
reason, or hidden value is emitted. Showing small cohorts would require an owner decision and an
ADR 0028/0044 amendment. Production privacy configuration (the cohort environment value) could not
be verified here; if it were absent every protected metric would read Unavailable.

Tests: Python `test_talent_branch_hard_scope.py`, `test_talent_start_assessment_flow.py`,
`test_talent_classification_aggregate_privacy.py`; Node B1-B10, Start Assessment cases in
`talent_operations.test.cjs`, `talent_classification_withheld.test.cjs`. Browser verification not performed.

## Talent product transformation (Agent 3, 2026-09-25)

Implemented on dev, not deployed or merged. This extends the preserved executive
Overview work into an aggregate-only Results & Analytics workspace: completion
and participation, results and Classification, Learning Style, Program-bound
Rubric Indicators, ordered Evaluation Periods, and selected comparisons.
The shared backend dashboard projection owns filters and all numerical values;
the frontend only renders its safe semantic states. Comparisons select at most
six authorized Branch/Grade/Section/Program/Period groups. Totals use underlying
Evaluation participations, not averages of Branch rates. Distinct Student and
participation grains are labelled separately. Incompatible Program/framework
results are not pooled. Requests exceeding 5,000 scoped population rows fail
explicitly and require a narrower Branch; there is no silent truncation.

The owner-approved privacy amendment fixes Agent 2's Classification-filtered
Learning Style leak: the original selected Classification bucket and denominator
must be visible after provider primary/complementary suppression before either
filtered aggregate can publish. Otherwise Learning Style returns a protected
semantic result with no total, buckets, percentages or chart magnitudes. Individual
authorized roster records retain exact identity, state, Classification and style;
aggregate suppression never removes an individually authorized Student row.
Tenant, Student visibility and the global Branch ceiling remain mandatory.

Overview retains its independent headline projection and adds shared charts.
Programs now uses searchable cards without normal lifecycle-status presentation.
Bar/percentage and applicable pie/doughnut/trend modes retain exact accessible
tables and native keyboard controls; nonvisible cells have no numeric geometry,
tooltips, datasets or ARIA values. Bundles remain surface-specific, bounded reads
retain cancellation/generation guards, and old duplicate rubric reads are removed.
The dashboard uses the existing read-only repeatable snapshot dependency.
No schema, migration, permission, timetable worker or local database change.

Recovery completion (same day): the interrupted local Agent 3 worktree was audited
and completed. Corrections: the generic "Protected for privacy" copy that had
re-entered chart and dashboard scripts was removed again (M18a); a non-visible
cell now reads "Unavailable", and only the backend reason
`classification_cohort_protected` produces the Classification-cohort explanation;
a missing Student-view permission has its own value-free message. The Program
summary Finish Setup control was inert (the summary path returned before click
binding) and was shown for incomplete setups; it is now bound and shown only for
a complete draft setup. Roster avatars and period icons use initials and inline SVG
instead of emoji. A Talent visual system layer (header band, KPI tiles, chart
cards, colour-controlled Program cards, one primary/secondary/destructive action
hierarchy, empty/loading/error states, responsive, reduced-motion and
forced-colors rules) was added in `talent-experience.css`. Visual claims are
structurally verified only; no browser review was performed. The dashboard reuses
the current-Student, classification, assessment and privacy authorities and its
distinct-Student figure is tested equal to Overview's. No schema, migration,
permission or local database change; Web Service only, no Workflow change.

## Student Assessment Filtered Insights (Agent 2, 2026-09-25)

**Status: implemented on `dev` only; not deployed or merged. No schema,
migration, permission, or `tis.db` change.** The Student Assessment roster now
uses request-backed search, Grade, Section, Assessment-state, Classification and
existing Branch ceiling filters. `GET /api/talent/assessment-cycles/{cycle_id}/eligible-students`
applies the active global Branch ceiling before every filter, rejects invalid state
or classification values, and returns the exact filtered roster population plus
backend-produced summaries. Classification is the current completed M17 result
only, uses the canonical service and its existing privacy projection, and remains
Exceptional-only for Talented presentation. Learning Style is the approved eight
categorical values plus Unassigned over this roster population; it is never the
deprecated four-dimension profile or the Students-page organization aggregate.
The browser renders supplied values and accessible tables/progress labels; it does
not calculate classifications or distributions. The former DOM-only roster filter
is no longer attached.


## Batch 1 Closure - The Global Branch Is A Hard Talent Scope (2026-09-25)

> Amended 2026-09-25 (Part 1 production follow-up, owner decision): the ceiling described here now
> applies only to Branch-limited actors. Organization-authorized actors choose All Branches or any
> authorized Branch inside Talent, the sidebar Branch being only the default, and the `branch_scope=all`
> marker cookie / `user.scope_all_branches` were removed. Original text below is preserved as history.

**Status: implemented on `dev` only; not deployed, not merged. Web Service only
(no worker/timetable/workflow change). No schema, migration, permission or `tis.db`
change. Frontend verified only with the DOM-stub harness and Python route/template
tests, not in a real browser.**

**Correction (supersedes the Batch 1 wording below).** The Batch 1 sections state
that the active global Branch is only the workspace *default* and that an
organization actor may widen to all Branches from inside Talent (`branch_scope=all`).
That is withdrawn. Owner decision: **the global Branch is a HARD upper ceiling for
every Talent page/API/filter.** A single-Branch global scope (for example one of two
sibling Branches) -> Talent shows that Branch only; an internal "All Branches" choice
inside Talent can never exceed the global scope. Only an explicit global "All
Branches" (organization-wide) scope lets Talent expose All Branches, the Organization
Talent Map and cross-Branch comparison.

**Finding that shaped the design.** Before this closure there was no global "All
Branches" state at all: every tenant user always resolves to one Branch
(`get_current_user` -> `user.scope_branch_id`), and the sidebar switcher lists
Branches only. A ceiling taken from `scope_branch_id` alone would have removed
organization-wide Talent for every organization user. The closure therefore adds an
explicit organization-wide marker, scoped to Talent: the sidebar switcher shows
"All Branches (Talent & Potential organization-wide)" only on `/talent` pages;
`POST /scope/branch` with `branch_id=all` sets the `branch_scope=all` cookie (only for
an actor who `can_access_all_branches`) and leaves the `branch_id` cookie untouched,
so every other module keeps resolving its single working Branch exactly as before;
choosing a specific Branch, switching organization, login and logout clear it.
`get_current_user` exposes it as `user.scope_all_branches`.

**Enforcement (server-side, one helper).** `talent_branch_scope.py`:
`talent_branch_ceiling(user)` = the single Branch id an actor is confined to in Talent,
or `None`. It is the INTERSECTION of the actor's authorization and the active global
scope: organization/global actor with a single-Branch scope -> that Branch;
organization actor with `scope_all_branches`, or a platform actor with no Branch
selected -> no extra ceiling; Branch-limited actor -> no extra ceiling (their own
Branch is already the only accessible one). It reads the authenticated request user
(never a client parameter). `visible_branch_ids` / `visible_branch_ids_or_none` /
`branch_scope_unrestricted` / `branch_within_ceiling` compose the ceiling into the
existing visible-Branch resolution, so every route inherits it and there is no second
authorization system. A Branch outside the ceiling is treated exactly like a Branch
outside the actor's authorization (same 400/403/404 conventions as the sibling routes);
an omitted Branch resolves to the ceiling, never to every Branch of the organization.

| Surface | Ceiling enforced server-side | How |
| --- | --- | --- |
| `organization-analytics` overview, talent-map, program-portfolio, branches/{id}, participation-overlap, longitudinal, students (drill) | yes | `talent_org_intelligence_service.resolve_access_context`: `all_branches` false + `accessible_historical_branch_ids` = {ceiling}; every population query, filter validation, Branch list and Branch existence check reads it |
| `analytics/...` context, overview, rubric/kpi distribution, competencies, breakdowns, period-comparison, students | yes | `routers/talent_analytics._visible_branches` -> helper; population query + `resolve_filters` branch scope |
| `results-analytics` classification, talented | yes | `_visible_branches` -> helper |
| `results-analytics` learning-style | yes | route clamps `branch_id` to the ceiling (other Branch -> 403 `invalid_filter`), then the existing `resolve_population`; the Students module is unchanged |
| `evaluation-progress` student, branch/{id}, organization, branch-comparison | yes | `_visible_branches` -> helper; `branches/{id}` also requires `branch_within_ceiling` (404) |
| `assessments` list and per-Assessment authorization, start | yes | Branch filters use `visible_branch_ids` / `branch_scope_unrestricted` |
| `assessment-cycles` eligible-students, preview, population | yes | same; explicit `branch_id` via `branch_in_authorized_scope` (ceiling-aware, 403) |
| `learner-profiles/{id}` | yes | `visible_branch_ids_or_none` (profile shows only records inside the ceiling; 404 if none) |
| `review-candidates`, `official-identifications`, `educator-inputs` lists and per-record authorization | yes | same helper |
| `programs/planning-branches`, `planning-grades`, `planning-sections` (selector option lists) | yes | Branch list limited to the ceiling; other Branch -> 404 |
| `/talent/{view}` `tp-config` | presentational | publishes the locked Branch (empty only for global All Branches) |

**Client.** `static/js/talent.js`: `config.branch` is now a ceiling. When set,
`reconcileBranchScope` forces `branch_id` to it and deletes `branch_scope`
(stale/hand-edited URLs and `branch_scope=all` cannot widen), the Branch selector
offers only that Branch (no All Branches), `applyContext` cannot choose another
Branch, and `qs()` clamps any `branch_id` it serialises. With an empty
`config.branch` (global All Branches) All Branches, the Talent Map and individual
Branch comparison behave exactly as before. Acceptance A loader hardening and
section isolation are unchanged.

**Deletion / inactive Students / Talented KPI (owner decisions, unchanged).** No
permission was widened; `force_delete_student_history` (the already-authorized
history-delete path) still removes every Student-owned Talent table and the existing
deletion tests were re-run. Bulk-delete history/force behaviour is out of scope.
ADR 0039 status semantics unchanged. The Talented KPI keeps the honest "Talented
results" grain; no distinct-Student Talented metric was invented.

Tests: `tests/test_talent_branch_hard_scope.py` (real tenants/Branches: mirror
across every read surface, global All Branches keeps organization comparison,
stale explicit Branch rejected, Branch-limited actor and tenant isolation unchanged,
`tp-config`), `tests/talent_branch_scope_and_metrics.test.cjs` (B3/B4/B6 re-pinned,
B6b added). Batch 1 tests that pinned "default, overridable" semantics were updated
deliberately (the shared `World` fixture's org actor now has the explicit global
All Branches scope).

**Not verified / residual.** No real browser. Another already-open tab keeps its own
URL until reloaded but the server ceiling applies to every request. The
`branch_scope=all` marker is a per-browser cookie; it only lifts the Talent ceiling
and never widens authorization. Offering the All Branches option on other modules'
switchers is not done (out of scope).


## Deployment Acceptance Batch 1 - Data Correctness, Scope Integrity, Student Deletion And Loading (2026-09-24)

**Status: implemented on `dev` only; not deployed and not merged to `master`.
Whether production now shows the corrected figures and loads reliably needs
production verification after a deploy; production infrastructure cannot be
measured from the development environment. Web Service only (no worker
contract, no timetable change) - the separate `tis-timetable-workflow`
revision is unaffected. No schema, migration, permission or `tis.db` change.
Frontend verified only with a DOM-stub harness and Python route/template tests;
not exercised in a real browser.**

Owner rule that governs this batch: **Talent & Potential operates from the
Students that currently exist in TIS.** Only current Students and their valid
current Talent data may contribute to any current Talent figure (counts,
participation, completion, Classification, Talented, distributions,
percentages, denominators, trends). This supersedes the M15 reading that the
Student-vs-Talent count difference was purely a population-scope distinction:
the headline was a different *grain*, and orphan/historical rows must never
count.

**Root cause of "Students participating = 63 while 9 Students exist".** The
Overview headline `frozen_eligible_memberships` (labelled "Students
participating" in `static/js/talent.js`) is the frozen-membership row count:
`talent_org_intelligence_service.frozen_membership_query` returns one
`TalentAssessmentCyclePopulationMember` row per Student per Cycle/Program (open
or closed), so, for example, 9 Students spread over 7 open or closed
Program/Cycle contexts is 63 rows (the exact production composition cannot be
observed from the development environment; the mechanism is reproduced by
`tests/test_talent_batch1_data_scope.py`). `MetricCode.FROZEN_ELIGIBLE` has always been defined at
`MembershipGrain.FROZEN_MEMBERSHIP`; only the label called it Students. The
population query also never checked that the Student still exists.

**Fix.** (1) `talent_current_students.current_student_exists` (correlated
EXISTS on the same SchoolGroup) is composed into every governed Talent
population read: `talent_analytics_service.population_query`,
`talent_org_intelligence_service.frozen_membership_query`, the Evaluation
Progress Branch/Organization reads and `list_assessments`, so an orphan or
deleted Student's row can never inflate a count, denominator or result. Student
`status` (active/inactive) is not a Talent population filter (ADR 0039 keeps
eligibility independent of it). (2) `/api/talent/organization-analytics/overview`
adds `distinct_students`: DISTINCT current Students in the authorized scope
(`talent_org_student_drill.count_distinct_students`, the existing distinct-Student
authority, published through the same B2 privacy pipeline at class P2 using the
existing `student_drill_population`/`count`/`distinct_student` coordinate - no new
MetricCode or MembershipGrain; see ADR 0044 Batch 1 amendment). The overview also
accepts an authorized `branch_id`. (3) Labels: "Students participating" is bound
only to `distinct_students`; the membership figures are "Program
participations"; `completed` is "Assessments completed"; the Talented card counts
current completed assessment results, so it reads "Talented (Exceptional)
results" (a Talented *Student* rule across several Periods would need a governed
Period-selection rule and is not invented here).

**Metric grain table** (A = distinct current Students, B = participation/
membership rows, C = assessment/result rows):

| Metric | Label before | Grain before | Label after | Grain after | Authority |
| --- | --- | --- | --- | --- | --- |
| Overview headline Students | "Students participating" (63) | B | "Students participating" (9) | A | `organization_overview` -> `count_distinct_students` |
| `frozen_eligible_memberships` | "Students participating" | B | "Program participations" | B | `coverage_organization_total` |
| `frozen_eligible` (Program card, Talent Map, Longitudinal) | "Students participating" | B | "Program participations" | B | `coverage_by_program_*`, `talent_org_talent_map` |
| `completed` | "Assessed" | B | "Assessments completed" | B | coverage rows |
| `completion_coverage`, `assessment_started`, `started_coverage` | unchanged | ratio/count of B | unchanged | B | valid membership denominators, deliberately unchanged |
| `participation_overlap` diagonal | "Distinct participating Students" | A | unchanged | A | `participation_overlap_counts` |
| Student drill list | Students | A | unchanged | A | `fetch_student_rows` |
| Classification / Talented | "Talented (Exceptional) Students" | C | "Talented (Exceptional) results" | C | `talent_results_analytics_service` |
| Learning Style distribution | Students | A | unchanged | A | `student_learning_style_analytics` |
| Evaluation Period / Branch comparison | results | C | unchanged | C | `talent_evaluation_progress_service` |
| Rubric / competency distribution | results | C | unchanged | C | `routers/talent_analytics.py` |

**Student deletion completeness (exhaustive FK audit).** Ten tables carry a
`student_id` or a foreign key to `students`: `student_academic_placements`,
`student_audits`, `student_external_identifiers`,
`talent_assessment_cycle_population_members`, `talent_student_assessments`,
`talent_student_competency_results`, `talent_assessment_audits`,
`talent_review_candidates`, `talent_official_identifications`,
`talent_educator_inputs`; no other table reaches a Student even transitively.
`force_delete_student_history` already removed all ten in one FK-safe transaction;
the list is now the exported `STUDENT_OWNED_MODELS` and is locked to the ORM
metadata by `tests/test_student_delete_completeness_batch1.py`, so a future
Student-owned table cannot be added without being deleted. Nothing is retained
(no historical retention store) and nothing orphaned can feed current analytics
(the defensive EXISTS above). The permission model is unchanged: normal Delete and
Bulk Delete stay blocked while Placement/Talent history exists
(`students.delete`/`students.bulk_delete`); only `students.force_delete_history`
removes Talent history. Deleting 2 of 10 Students recomputes distinct Students,
memberships, Classification, Talented, Learning Style, roster, drill, Branch and
Grade projections from the remaining 8 (`tests/test_talent_batch1_data_scope.py`).
The historical `test_student_academic_foundation` ObjectDeletedError was a test
defect (reading `.id` of a just-deleted instance), fixed in the test.

**Global Branch context.** *(Correction 2026-09-25: the "default only" / "explicit
All Branches" wording in this paragraph is superseded - the global Branch is a hard
Talent ceiling; see "Batch 1 Closure - The Global Branch Is A Hard Talent Scope".)*
Root cause: the sidebar Branch selector only sets the
session scope Branch; Talent never read it. All-Branch (Organization) actors got
every Branch's Students on every Talent page unless a per-view Branch filter was
chosen, and `/program-portfolio` silently ignored the `branch_id` the Results
view sent. Fix: `routers/talent_ui.py` validates the active Branch (a Branch of
the actor's tenant that they can access) and renders it as `tp-config.branch`;
`static/js/talent.js` `reconcileBranchScope` makes it the default Branch scope of
every Student-data view, drops any Branch/Grade/Section carried by a URL minted
under a different active Branch (`scope_branch_id` marker), and honors an explicit
"All Branches" choice (`branch_scope=all`). The Branch selector is available on
Overview, Assessments, Results, Program Results, Talent Map, Students Across
Programs, Students and Progress Over Time. Backend authority is unchanged and
authoritative: every Branch filter is validated (a foreign-tenant or unauthorized
Branch is rejected, never widened) - added `branch_id` to the Overview, Program
Results (`/program-portfolio`, same authority as `/branches/{id}`) and the
eligible-students roster, and the rubric read now carries the Branch. Residual
risk: another already-open tab keeps its own URL scope until reloaded.

**Loading / performance (fresh investigation, measured).** Confirmed causes:
(1) per-Assessment-row N+1: `/api/talent/assessments` (no filter) re-derived
`overall_program_result`, classification, `reassessment_requirement` and its
Framework/rubric/descriptor snapshots, permission sets and delete probes for
every row - 982 SQL statements for 20 rows (about 49 per row; 1,294 with 6 more
Students) - and the Student Assessments page requested every Assessment in the
organization then filtered client-side; (2) Results/Student Drill/Evaluation
Progress repeated the same per-row derivation (drill 136, classification and
Talented 74 each, branch comparison 84); (3) the access context recomputed the
actor's permission set five times per request (overview 33, every Organization
route 31-34 fixed statements); (4) Evaluation Plans recomputed permissions six
times per Period (140); (5) `/api/talent/programs/summaries` raised HTTP 500 for
any Program with an annual configuration (`annual.eligible_grade_levels` does not
exist; the Programs page silently fell back); (6) Talent static assets had no
cache-busting and `/static` sends no Cache-Control, so a browser could pair the
freshly rendered no-store page with a script copy from an earlier deployment (the
mixed-version state the earlier loader hardening cannot cover). After the fix
(same dataset): assessments 111, drill 24, classification 20, Talented 20, branch
comparison 30, overview 15, evaluation plans 20 statements, and the counts no
longer change when Students are added (guarded by
`test_talent_list_endpoints_do_not_scale_with_the_number_of_assessment_rows`,
which fails on the pre-fix code: 982 -> 1,294). Fix: `talent_read_batch.py`
(opt-in, request-scoped memoization inside `with read_batch(db)` on one
request-owned Session; inactive by default so write paths are untouched;
discarded on exit so it can never serve data across requests or after a Student
deletion), set-based priming of Assessment members/results,
`talent_request_permissions.request_permission_checker` (effective permission set
resolved once per request; per-request only, decisions identical to
`auth.has_permission`), server-side Academic Year/Program filters on the
Assessments list, the `summaries` fix, content-hash `?v=` versions on every
Talent script/style, and an inline 15-second watchdog that turns a still-untouched
server-rendered loader into an explicit "could not finish loading" error with a
Reload button (so a script that never runs, fails to parse or is stale cannot
leave a generic loader indefinitely). The previously known over-budget tests
(overview 31 vs 16, Student Drill 36 vs 12) are resolved (drill's pinned ceiling
is now 18 (fixed family of 17) with the never-row-proportional invariant kept).
**Render capacity is not shown to be implicated:** locally each handler now costs
tens of milliseconds and a bounded statement count; the confirmed causes are
code-level (row-proportional queries, stale-asset mixing, one crashing route),
and the 512 MB / 1 CPU service cannot be measured from here. Production timing
must be confirmed after deploy.

**Open owner decisions (not changed here).** (a) Non-force Delete and Bulk Delete
remain blocked whenever Talent history exists; making an authorized delete remove
Talent data would be a permission-model change (options: keep, add force to Bulk
Delete under `students.force_delete_history`, or let `students.delete` cascade).
(b) Inactive Students still count as current Students (Talent eligibility is
status-independent, ADR 0039). (c) A distinct-Student "Talented Students" headline
would need a governed rule for which Evaluation Period counts.

Tests: `tests/test_talent_batch1_data_scope.py`,
`tests/test_student_delete_completeness_batch1.py`,
`tests/talent_branch_scope_and_metrics.test.cjs`, additions to
`tests/test_talent_ui.py`, plus the shared fixture helper
`tests/talent_test_students.py` (Talent fixtures now create real Students; older
fixtures used bare integer ids, which are orphans under the new rule).

## Deployment Acceptance Correction D - Professional Student Assessment Editor Redesign (2026-09-24)

**Status: implemented on `dev` only; frontend/CSS + tests only. Not deployed
and not merged to `master`. Web Service only - the separate
`tis-timetable-workflow` revision is unaffected. No schema, migration,
permission, scoring, Classification, authorization or `tis.db` change.**

Owner-observed production screenshot showed the Student Assessment editor as
cramped and hard to scan: multiple narrow competency columns with rubric
descriptions wrapping into near-vertical text. The editor is redesigned as a
serious professional assessment workflow (presentation only; every mutation and
result still comes from the real API):

- **One competency per row.** `static/js/talent-operations.js` and
  `static/css/talent-experience.css` replace the auto-fit multi-column
  `.tp-assessment-grid` with a single-column layout, so every competency card
  spans the available width and its description/rubric reads naturally.
- **Readable rubric tiles.** Each rubric choice is a full-width selectable tile
  (`.tp-rubric-tile`) showing a clear rank ("1 / N"), the level title, and the
  descriptor/description on its own horizontal line - never compressed. The
  tile grid adapts (`repeat(auto-fit, minmax(200px,1fr))`) so up to five levels
  sit in one row on wide desktop, fewer as width shrinks, and stack to one
  column on mobile. The whole tile is the `<label>` radio target with native
  keyboard/focus semantics; a visible focus ring, a check marker and a strong
  border/background selected state (never colour-only) are preserved.
- **Evidence entry.** Evidence remains a labelled `<textarea>` bound to its
  competency (`name="evidence-{id}"`), now full-width under the rubric with
  more vertical space; a read-only/completed assessment disables the editor.
- **Progress, save and finalize unchanged.** The progress bar ("N of M
  competencies"), sequential save and the Complete/Incomplete/Insufficient
  outcome actions keep the existing backend semantics; completion still shows
  the backend Overall Program Result and automatic Classification with a
  Talented badge only for Exceptional. Review Candidate / Official
  Identification are not shown as current status.

Tests: `tests/talent_operations.test.cjs` (rubric-tile structure, evidence
binding, single-column/adaptive CSS) plus the existing
`talent_operations`/`talent_runtime_loading`/`talent_student_identity` suites.
Structural HTML/CSS verification only; browser visual acceptance is still
pending.

## Deployment Acceptance Correction C - Learning Style Distribution (2026-09-24)

**Status: implemented on `dev` only; not deployed and not merged to `master`.
Whether production shows the corrected distribution needs production
verification after a deploy. Web Service only - the separate
`tis-timetable-workflow` revision is unaffected. No schema, migration, permission
or `tis.db` change. Frontend structurally verified with a DOM-stub harness and
Python route/template tests; not exercised in a real browser.**

Owner-observed defect: every Learning Style category showed "Unavailable" even
though authorized Students had Learning Styles. Confirmed causes: (1) the
distribution was passed through the Talent P3 primary and complementary
small-cell suppression pipeline, so a small cohort (10 Students, minimum cohort
5) suppressed every per-category cell; (2) independently, the Results &
Analytics frontend consumed a `buckets` key while the Learning Style route
returns `levels`, so a visible distribution rendered no bars. Owner decision
(dated ADR 0031 "Acceptance C Amendment"): the Learning Style distribution is
authorized Student-domain profile aggregation, not Talent scoring output, and
is **not subject to Talent small-cell suppression**.

- **Semantics.** `Student.learning_style` stays one categorical value (eight
  values, or Unassigned); there is no per-Student percentage and the four
  deprecated `learning_style_*_percentage` columns are operationally deprecated
  and excluded from current Learning Style analytics and normal product
  presentation (legacy compatibility paths may still read/write the stored
  values for preservation, never as analytics authority). The
  aggregate returns all nine categories in stable order with key, label, count
  and percentage over one denominator: every authorized Student in the selected
  population **including Unassigned** (`total_population`). Zero categories are
  `0` / `0%` and visible. An empty authorized population returns state `empty`
  with no misleading `0%`.
- **Boundaries kept.** SchoolGroup, Branch, Grade (Section where already
  supported), Student visibility, tenant isolation and the `students.view`
  permission; `resolve_population` is unchanged; only aggregate counts and
  percentages are returned, never Student identity.
- **Scope of the exception.** It applies to this one distribution only.
  `talent_analytics_privacy.py`, its thresholds and P1-P7 suppression remain
  active for Classification, Talented, competency/rubric, result and
  organization Talent metrics; the Classification and Talented Results routes
  still require and apply the privacy provider.
- **Consumers.** The same engine feeds `/api/students/analytics/learning-style-distribution`,
  the Students page panel and `/api/talent/results-analytics/academic-years/{id}/learning-style`;
  all three are corrected consistently and none depends on the privacy provider
  any more (the Results route no longer returns `privacy_policy_version`).
- **Frontend.** Results & Analytics gains `learningStyleDistributionSection`
  (label, "N Students", percentage, progress bar from the backend percentage,
  "N Students in this selection, including Unassigned", accessible table,
  neutral Unassigned row, responsive at 680px); the Students panel shows the same
  fields. Loader hardening (Acceptance A) and identity behavior (Acceptance B)
  are unchanged.
- **Pinned expectations deliberately updated.** The former suppression /
  privacy-unavailable panel tests and the 503-when-policy-missing test in
  `tests/test_student_learning_style_v1.py` were replaced (this also retires the
  previously failing panel-message test); the Students-list "not promoted"
  assertion now excludes the aggregate panel; the Acceptance A loader test uses
  the Learning Style contract body.
- Performance: one authorized-population query plus in-memory aggregation, as
  before; no per-Student or per-category query and no frontend N+1.

## Deployment Acceptance Correction B - Student Identity + Automatic Classification + Current Talent Workflow (2026-09-24)

**Status: implemented on `dev` only; not deployed and not merged to `master`.
Whether production shows the corrected experience needs production verification
after a deploy. Web Service only - the separate `tis-timetable-workflow` revision
is unaffected. Structurally verified with a DOM-stub harness and Python
projection tests; not exercised in a real browser.**

Owner-observed production screenshots showed the old Review Candidate / Official
Identification concepts still presented as the current Talent workflow. The
owner-approved current workflow is: Student -> Program -> Teacher Assessment ->
Complete Assessment -> deterministic backend Automatic Classification. The five
bands are 1.00-1.99 Needs Improvement, 2.00-2.99 Developing, 3.00-3.74 Meets
Expectations, 3.75-4.49 Advanced, 4.50-5.00 Exceptional; **Exceptional is the
only Talented classification**. The authority is unchanged and remains
`talent_classification_service.py` (ADR 0037 2026-09-23 amendment); the frontend
never computes a band. Review Candidate and Official Identification are
**preserved legacy historical data only** (no record deleted, no schema change,
no API removed, no permission relaxed) and are never current Student status,
current Classification, a normal filter/column/action, or the Talented state.

What changed:

- **Student identity in Talent.** Every identifiable Student rendered in Talent
  now uses ONE shared presentation (`static/js/talent-student-identity.js`,
  loaded on every Talent view): name, canonical `Student.learning_style`
  (Visual, Auditory, Read/Write, Kinesthetic, Verbal, Non-verbal, Quantitative,
  Spatial; "Unassigned" when none, never fabricated), and - only where an
  applicable current result exists - the backend Classification, plus a
  Talented badge when and only when the classification is Exceptional. Applicable
  current result = `completed` AND `is_current`. Surfaces: Student Assessments
  roster, Assessment detail header, Students Across Programs (matrix + cards,
  per-Program classification, never one universal label), the dashboard Student
  preview, Learner Profile (Talent section of the Student Profile and the Talent
  `learner-profile` view), legacy history view, Student Drill.
- **Backend projections (smallest extensions, no persistence).**
  `talent_operational_context.authorized_contexts` adds `student_learning_style`
  from its already-batched Student lookup; the assessments list adds
  `classification`/`classification_score`/`is_talented` for current Completed
  rows (reusing the already computed Overall Program Result via
  `assessment_classification(..., overall=)`); eligible-students members carry
  `learning_style`; the learner profile exposes `student.learning_style` and a
  per-assessment `overall_result`; the Student Drill row exposes `learning_style`
  (its approved-field set and breadth accounting were extended by one field).
  No new classification column or table; no new permission; Student visibility is
  never widened (values ride projections that already contained the Student).
- **Legacy removed from the current experience.** "Talent Review" left the
  primary Talent sidebar and the Overview action cards; the route
  `/talent/reviews` remains (same `talent_review_candidates.view` gate) titled
  "Legacy Review & Identification History", with legacy-labeled columns, and is
  reachable from a secondary "Legacy Review & Identification History" link.
  Removed from normal UX: roster Review Status / Official Identification / Open
  Review, the Identification Classification filter, Review/Identification
  states on Students Across Programs, the dashboard Student "Review /
  Identification" column, candidate/identified metrics as normal Talent Map,
  branch-comparison and summary figures, and "Meets Program Criteria" as a
  current status. Learner Profile / Student Profile keep legacy records only in a
  distinct, labeled "Legacy Review & Identification History" section, and only
  when the actor already holds the legacy permission.
- **Fixed defect found on the way.** The Student Drill deduplication key used a
  tuple that could hold the nested `overall_result` dict, raising `TypeError` for
  any Student with a completed Program result; it now uses a canonical JSON key.
- Performance: no per-Student API call, permission query or classification
  endpoint call was added. The assessments list still issues the same per-row
  statements it did before this change (a pre-existing cost, measured at 36 per
  Student at b7e3c6a and unchanged); Acceptance B adds none.
- Pinned expectations deliberately updated: Talent nav no longer includes
  Talent Review, branch-comparison metric options (four current metrics), the
  Student Drill approved identity-field set (+`learning_style`), and the
  removed legacy filter/column assertions.

Open follow-ups: Learning Style aggregate/privacy correction (Acceptance C, since implemented - see the
Acceptance C section above) and
the Assessment entry editor body (Acceptance D, since implemented - see the
Acceptance D section above);
the Student-domain Learning Style badge now renders "Unassigned" (normalized to
match Talent surfaces by the follow-up remediation below).

## Deployment Acceptance Correction B Remediation - ClinePass Precision Remediation (2026-09-24)

**Status: implemented on `dev` only; backend/template/tests + KMS correction. No
schema/migration/tis.db change, no new permission, no new Student-discovery path.
Web Service only; not deployed and not merged to `master`.**

An independent Codex audit of Acceptance B found two blocking defects plus two
small follow-ups, now corrected:

1. **Legacy-history projection gap.** Acceptance B stated the Legacy Review &
   Identification History surface renders the current automatic Classification,
   but `routers/talent_review_candidates.py`'s `talent_review_workspace` did NOT
   return `classification`/`classification_score`/`is_talented`. Fixed by adding
   those fields from the canonical `talent_classification_service`
   `assessment_classification(db, assessment, overall=overall)` (reusing the
   already-computed Overall Program Result, so no per-Student classification or
   Learning Style query is added). The legacy history surface now shows the
   Student's current Learning Style and current automatic Classification where
   applicable. That Classification comes only from the M17 result, never from
   legacy Review Candidate / Official Identification; Exceptional remains the
   only Talented band.
2. **Terminology.** The Student Profile Learning Style badge used "Not assigned"
   while Talent surfaces used "Unassigned"; `templates/_learning_style.html` now
   uses "Unassigned" for Learning Style absence everywhere. Unrelated "Not
   assigned" copy for other concepts (Student ID, Branch, Teacher) is unchanged.
3. **Student Drill dedupe regression test.** A dedicated test now proves the
   canonical JSON dedupe key survives a nested `overall_result` (the former
   unhashable-tuple key raised `TypeError`) and still preserves distinct contexts.

New tests: `tests/test_talent_student_identity_projection.py` (real backend
`/api/talent/review-candidates/workspace` classification tests and the Student
Drill nested-result dedupe test), `tests/test_student_learning_style_v1.py`
("Unassigned"). `tis.db` unchanged.

## Deployment Acceptance Correction A - Talent & Potential Runtime Loading Reliability (2026-09-24)

**Status: implemented on `dev` only (frontend/template/CSS; no backend, schema,
migration, authorization, tenant, privacy-policy, or analytics-semantics
change). Not deployed and not merged to `master`; whether production shows the
defect fixed still needs production verification after a deploy. Web Service
only - the separate `tis-timetable-workflow` revision is unaffected.**

Defect (owner-observed on a deployment): Organization Overview / Results &
Analytics, Talent Review and normal navigation/filter actions stayed on the
server-rendered "Loading your authorized workspace..." placeholder.

Confirmed root cause (reproduced with a stub harness that runs the real script
against a scripted DOM/fetch): M16 made `templates/talent/workspace.html` load
`talent-rubric-visual.js` only on Programs / Evaluation Plans / Assessments /
Talent Review, but `static/js/talent.js` still dereferenced
`window.TalentRubricVisual.intensity` at script-evaluation time. On every other
view (Talent Overview, Organization Overview / Results & Analytics, Talent Map,
Program Results, Branch Results, Students Across Programs, Students, Progress
Over Time, Learner Profile) the script threw a TypeError before `init()` ran, so
no request was ever made and the placeholder and `aria-busy="true"` never
changed. Node unit tests `require()` the module directly and could never see it.
Independent lifecycle weaknesses also fixed: `init()` ran outside any
try/catch (a synchronous exception left the loader and produced an unhandled
rejection); no fetch had a completion bound (a hung connection meant an
indefinite loader); Results & Analytics used one all-or-nothing `Promise.all`
(one rejected request replaced the whole page and a slow one held every
section); the operational delegates (`TalentOperations`,
`TalentProgramWorkspace`, `TalentEvaluationWorkspace`) were dereferenced without
a presence check, showing a raw TypeError message; sequential Branch/Grade/
Program selector lookups could stack unbounded waits before the first data
request. Talent Review's own path was not affected by the missing-script defect
(it loads the rubric module); its exposure was the unbounded request/all-or-
nothing behavior, which is fixed generically (inference: a slow/hung request is
the only remaining way it could have stayed on the loader).

Runtime lifecycle now (page shell -> bounded essential context -> independent
sections):

- The rubric visual module loads on every Talent view (it is tiny and shared);
  `talent.js` additionally resolves it defensively so a missing module degrades
  a helper instead of aborting the script. Operational/workspace bundles remain
  surface-specific (M16 preserved).
- `boot()` is the outermost guard: it replaces the server placeholder
  immediately, wires events, runs `init()`, and turns any failure (including a
  synchronous exception) into an error panel with a real Retry button. A missing
  delegate script shows a "required page component did not load" state whose
  Retry reloads the page. `pageshow` (bfcache restore) reloads content.
- Every read request is bounded: 25 s (`REQUEST_TIMEOUT_MS`) - far above normal
  latency, short enough to end a hung request visibly - and 15 s for the small
  selector lookups (Branch/Grade/Section/Program lists), which run in parallel
  and never delay first load past a 20 s deadline. The bound also covers reading
  the response body and settles even if `fetch` ignores abort. Mutations issued
  by the operational workspaces are deliberately not client-timed-out (aborting a
  write that may already be committed would mislead). The AbortController,
  generation/stale-response guard and `cache: no-store` are unchanged; only a
  superseded generation returns silently, the current generation always reaches
  success, empty, unavailable or error.
- Organization Overview (Talent landing) renders its copy and action cards
  immediately; the headline figures are an independent section with local
  loading, empty, error/timeout and Retry states. Results & Analytics replaces
  `Promise.all` with independent sections (snapshot, Learning Style,
  Classification, Current Talent, Program result, competency averages, rubric,
  Grade results, Evaluation progression, Branch comparison, Student results),
  each ending independently with its own Retry; every request is issued exactly
  once within `talent.js` (memoized, including the shared Talent Map/Branch-name
  lookup). Cross-module rubric-distribution deduplication was NOT part of this
  change and is corrected by the follow-up remediation below; metric semantics,
  endpoints and debounce (250 ms) are unchanged. Program
  Results / Branch Results gate the page on their primary payload only; their
  grade/Branch breakdowns are an independent section.
- Errors were intended to show only messages authored by the UI or mapped from
  an HTTP status, with any other exception text replaced by "This section could
  not finish loading."; at baseline 507dc59 arbitrary backend `data.detail`
  could still reach users in `parseApiResponse`, `operationApi` and `fetchRubric`.
  The follow-up remediation below replaces this with a curated status/code
  mapping. `#tp-status` (`role=status`) and `aria-busy` are updated on every
  terminal state.
- `talent-experience.js` rubric section: bounded request and a concise Retry
  state (its raw `detail` disclosure is corrected in the follow-up remediation).

Verification: `tests/talent_runtime_loading.test.cjs` (23 tests, stub harness in
`tests/talent_runtime_harness.cjs`) and HTML-level per-view script-dependency
tests in `tests/test_talent_ui.py`. These are structural/stub verification, not
a real browser. Not implemented here (later acceptance batches): Learning Style
privacy/distribution correction, Learning Style and Classification beside every
Student, removal of Review/Official Identification from normal UX, Assessment
editor redesign.

## Deployment Acceptance Correction A Remediation - ClinePass Precision Remediation (2026-09-24)

**Status: implemented on `dev` only; frontend/template/tests + KMS correction. No
backend, schema, migration, authorization, tenant, privacy-policy or
analytics-semantics change. Web Service only; not deployed and not merged to
`master`.**

An independent Codex audit of Acceptance A found two blocking defects in the
frontend runtime path plus an overstatement in the closeout above:

1. **Raw backend `data.detail` disclosure.** `talent.js` `parseApiResponse()` and
   `operationApi()`, and `talent-experience.js` `fetchRubric()`, interpolated
   arbitrary backend `detail` strings into user-facing errors. Fixed with one
   shared curated mapper (`static/js/talent-api-errors.js`) keyed by HTTP status
   plus a known stable backend `code`; arbitrary `detail` is never rendered, and
   `safeMessage` now requires `userSafe === true` (a bare HTTP status is no
   longer authority). 401/403/404/400/422/503 and unknown 5xx map to approved
   copy; raw exception/SQL/Python/JS/endpoint/stack/internal text can never
   surface.
2. **Duplicate rubric-distribution request.** `talent.js` `rubricReq()` and
   `talent-experience.js` `fetchRubric()`/`ensureRubricSection()` both requested
   the same Program + Academic Year + `assessment_state=completed` endpoint per
   render generation. Fixed with a shared single-flight read-ownership store
   (`static/js/talent-rubric-request.js`): `talent.js` owns the request and
   publishes its memoized promise keyed by context; `talent-experience.js`
   reuses it for the same context. A different Program selected in that
   section's own filter is a different context and still fetches independently.
   Retry (`force`) re-issues its own bounded request; a Program/year change
   resets the store; the existing generation/stale guards prevent a late
   response from overwriting the current context.

The runtime stub harness (`tests/talent_runtime_harness.cjs`) now executes the
production script composition in order (talent-rubric-visual, talent-api-errors,
talent-rubric-request, talent.js, talent-experience.js) and observes fetches from
both modules, so the "no duplicate request" guarantee is actually proven rather
than assumed. `tests/talent_runtime_loading.test.cjs` grew from 23 to 30 tests
(curated error mapping, no raw-detail rendering, cross-module deduplication,
retry, Program-change invalidation, stale-response safety). Per-view script
dependency tests in `tests/test_talent_ui.py` now also require the two new
shared helpers before `talent.js`. `tis.db` is unchanged.

## M14-M18 Correction Program Closeout - M18b-3 Final Regression / Performance / Privacy Verification (2026-09-24)

**Status: the five-milestone correction program (M14, M15, M16, M17, M18) is
functionally implemented on `dev` and closed for owner-acceptance and release
planning only. Nothing here states that any of it is deployed, merged to
`master`, or live in production; deployment, merge, and any production-state
claim remain separate Owner decisions.** M18b-3 is a verification/KMS
closeout pass, not a feature: no product semantics, analytics family, or
filter was added, and there is no schema or migration change.

**Final current-state truth (verified against code and tests, not only docs):**

- Learning Style (M14): `Student.learning_style` is ONE categorical value from
  exactly eight (Visual, Auditory, Read/Write, Kinesthetic, Verbal, Non-verbal,
  Quantitative, Spatial); the aggregate is those eight plus Unassigned. The four
  legacy percentage columns remain physically in the schema and in the write
  service only so already-stored values are never silently rewritten; no current
  API, UI, or analytics surface reads or exposes them (physical removal stays
  gated on a separate data-occupancy verification).
- Student/Talent scope (M15): the Student vs Talent count difference is
  scope/population semantics, not a deletion defect; a force-deleted Student
  cannot appear on current Talent surfaces; the roster export is re-importable.
- Performance (M16): the common Talent page performs at most 3 effective
  permission projections (governed regression
  `tests/test_talent_ui.py::test_talent_page_bounds_authorized_permission_projection_reuse`
  passed). `authorization.require_any_permission`/`require_all_permissions`
  still resolve the current user and allowed keys on every call; the only reuse
  is `request.state`, which is request-scoped (no global or cross-user cache).
  `templates/talent/workspace.html` still loads the rubric-visual, operations,
  program-workspace, and evaluation-workspace bundles only for the views that
  need them.
- Classification (M17): the raw Program result stays Program-native 1..N and is
  deterministically projected to 1.00-5.00; bands are 1.00-1.99 Needs
  Improvement, 2.00-2.99 Developing, 3.00-3.74 Meets Expectations, 3.75-4.49
  Advanced, 4.50-5.00 Exceptional; ONLY Exceptional is Talented. Authority is
  backend-only (`talent_classification_service.py`); there is no percentage-band
  classification. Legacy Review Candidate and Official Identification records
  are preserved as history/legacy workflow and are not current Talent authority.
- Current Talent authority (M18a): an applicable current result is
  `status == 'completed' AND is_current == True`. Learner Profile and Student
  Drill use the M17 classification authority. The obsolete four-dimension Branch
  aggregation and the visible "Protected for privacy" runtime copy are gone;
  privacy suppression itself is unchanged.
- Results & Analytics backend (M18b-1): one coherent family (Learning Style,
  Classification, Talented) under `/api/talent/results-analytics/...`; frozen
  ADR 0044 `MetricCode` values are not repurposed. Organization aggregation sums
  RAW counts across Branches (Branch A 1/2 + Branch B 9/90 gives Organization
  10/92, never an average of rates such as 30%); competency and progress keep
  the governed pre-existing endpoints.
- Results & Analytics UI (M18b-2/2b): the page consumes those backend families;
  nine sections in order (header, summary cards, Learning Style, Classification,
  Current Talent, Competency Analysis, Results/Evaluation Progress,
  Branch/Organization comparison, navigation); the current Talented summary is
  backend-sourced; the Classification filter is Program-bound, narrow-only, and
  cleared when Program context disappears; `candidate_membership_count` is
  labeled "Legacy: Meets Program Criteria". No client-side classification,
  rate averaging, or new chart library.
- Privacy UX: suppressed values are never rendered as numbers (HTML, chart
  datasets, tooltips, ARIA); primary/complementary suppression, anti-
  reconstruction, Branch isolation, and Organization privacy are unchanged and
  their suites pass.

**Results & Analytics request behavior (structural evidence from
`static/js/talent.js`; no timings measured):** the analytics view issues one
`Promise.all` batch with exactly one request per endpoint (Learning Style,
Classification, Talented each once per context); Classification/Talented are
only requested when a Program is selected; ordinary filter changes go through
the existing `AUTO_APPLY_DEBOUNCE_MS` (250 ms) debounce and `applyContext`,
which uses `history.replaceState` (no full-page navigation); the
generation counter plus `AbortController` in `load()` prevent a stale response
from overwriting a newer one.

**Accessibility / responsive (structural only; no browser was available, so
NOT visually verified):** every distribution has both a `role="group"` bar
rendering and a captioned data table (`bucketBars`/`bucketTable`); the
Classification filter is a native labeled `<select>`; category meaning is
carried by text labels, not color alone; the `.tp-filters` wrap, the 680px/
980px/760px breakpoints, and the `.tp-table-wrap` overflow container exist in
`static/css/talent.css`.

**Bounded fix made in M18b-3:** M18a made the Student Drill call
`assessment_classification`, which recomputed `overall_program_result` a second
time for every current+completed row, doubling per-completed-row query cost
(measured 2 -> 4 queries per completed row; fixed drill total 36 -> 38).
`assessment_classification` now accepts an optional pre-computed `overall`
(default behavior unchanged) and the drill passes its row's existing result,
restoring the pre-M18a cost (2 per row). Regression guard:
`test_completed_row_query_cost_does_not_recompute_overall_result_for_classification`
plus an equivalence test in `tests/test_talent_organization_student_drill.py`.

**Known unresolved PRE-EXISTING issues (identical at the pre-program commit
`50c049f` unless noted; classified with git worktrees, not assumed):**

- Student Drill fixed query budget: `test_query_family_is_bounded_and_not_row_proportional`
  asserts `<= 12` queries but the drill already used 36 (and grows ~2 per
  completed row, an N+1 from per-row `overall_program_result`) before M14; it
  still fails after the M18b-3 fix (36). Post-correction follow-up: batch the
  per-row overall-result computation. Related:
  `test_overview_uses_one_caller_session_and_bounded_set_based_queries` fails at
  31 vs a 16 budget, identical at program start.
- `tests/test_student_learning_style_v1.py::...one_panel_level_protected_message...`
  asserts the chart container is absent while the template deliberately renders
  the category labels with neutral unavailable states and no magnitudes (the
  page leaks no numbers); stale test expectation to reconcile.
- `test_force_delete_student_history_removes_protected_academic_history`
  (`ObjectDeletedError` in the test's own post-delete refresh), four
  `test_talent_assessment_cycle_frozen_population` tests, one
  `test_talent_operational_journey`, one educator-input, and one rubric-policy
  test fail identically at `50c049f`.
- Node: 16 of 188 tests in `tests/talent*.test.cjs` + `tests/student*.test.cjs`
  fail (13 of 179 at `50c049f`). Three are stale expectations of the removed
  M14/M18a four-dimension Learning Style Branch metric in
  `tests/talent_branch_comparison_frontend.test.cjs`; the remaining 13 are old
  program-workspace/operations/experience expectations that predate the program.
- PostgreSQL (`TIS_TEST_POSTGRESQL_URL`, local test database, isolated
  schemas): 11 passed / 5 failed in `tests/test_postgresql_migration_transactions.py`,
  the same 5 (FK creation order) at `50c049f`.
- `tests/test_permission_dangerous_patterns.py` reports unclassified SaaS
  permission-shortcut hits (unrelated to Talent; identical at `50c049f`).
- An unscoped full `pytest tests/` run previously hung in an unrelated
  SaaS/timetable area; M18b-3 did not repeat it and used scoped suites.

**Deployment/boundary:** no Web Service or `tis-timetable-workflow` change; no
migration; `tis.db` unchanged (SHA-256
`01e1a3065d92280ee9228db921f67545c8b837d4ecd787a5aeeddc6d128fc136` before and
after). GitHub Actions status was not verifiable from this environment.

## M18b-2b Results & Analytics IA reorder + Classification filter + accessibility/responsive audit + candidate_membership_count decision (2026-09-24)

Bounded completion pass over the M18b-2 explicit open-item list (a)-(e), on
top of the already-landed M18b-2 first pass. No backend semantic change; the
M18b-1 contract is unchanged; M18b-3 (final broad regression/performance/KMS
closeout for the full M18 milestone) remains separately scoped and still
pending.

**(a) IA reorder (page-content level):** the in-content `lede()` header for
the `analytics` view now reads "Results & Analytics" with a dedicated
subtext, replacing the generic "Your organization at a glance" copy. The
outer page chrome (breadcrumb/`<h2>`/`VIEWS["analytics"]` title, still
"Organization Overview") is deliberately left unchanged - `tests/
test_talent_organization_analytics_providers.py` pins that literal string
for the page shell, and this pass targets the in-content Results & Analytics
header called for by the task, not the shared workspace chrome. The 9
sections now render in the required order: page header -> (context/filters
live in the sticky `tp-filters` form outside this content region) -> summary
cards (Organization snapshot KPI grid + fact strip, now including a single
backend-sourced "Talented (Exceptional) Students" count) -> Learning Style ->
Classification -> Current Talent -> Competency Analysis (Program result +
per-competency averages + rubric distributions, now grouped together -
`rubricSection` moved from the very end of the page to immediately follow
`competencyAverageSection`) -> Results/Evaluation Progress (Grade progress +
Evaluation Period progression, `progressionSection` moved before the Branch
comparison section) -> Branch/Organization comparison (Branch comparison +
the authorized cross-Program Student preview) -> secondary navigation links.

**(b) Progressive Classification filter:** a real `Classification` filter
control (`<select name="classification">`, the exact 5 backend
`CLASSIFICATION_LABELS`) was added to the shared `tp-filters` form and wired
only into the `/results-analytics/.../classification` request (never
`/talented`, which has no such parameter). It is progressive: hidden until a
Program is selected on the `analytics` view (`updateClassificationVisibility`),
and cleared whenever hidden so a stale value can never be submitted for a
different Program. It can only narrow the returned buckets (backend-validated
against `CLASSIFICATION_LABELS`, rejects an unrecognized value), never widen
authorization. Evaluation Period and Competency filters were evaluated and
explicitly NOT added this pass: they would require new supporting
period/competency list endpoints beyond this task's smallest-coherent-change
scope, and are not "just wire the UI" the way Classification was (Classification
already had a dedicated, documented backend query param per M18b-1).
Learning Style's real backend filters (`branch_id`/`grade_level`/
`section_name` only, Student-domain-wide per ADR 0031/M14) are already fully
covered by the existing Branch/Grade selectors - confirmed directly against
`routers/talent_results_analytics.py`, no new Learning-Style-specific
control was added or needed.

**(c) Accessibility audit (performed, not just asserted):** no chart-type
selector exists anywhere in `static/js/talent.js` (grep-verified) - bar-only
charts per the compatibility matrix, so no keyboard/chart-type-selector work
was required. The new Classification filter is a native `<select>` inside a
`<label for>` (identical pattern to every existing filter field), so it is
natively keyboard-operable, has an accessible name, and sits in natural tab
order with no `tabindex` manipulation - traced directly against the existing
`tp-filters` form structure, not assumed.

**(d) Responsive verification (performed, not just asserted):** independently
re-checked `static/css/talent.css`'s breakpoints against every class name the
new M18b-2 markup actually uses - `bucketBars`/`bucketTable` reuse
`.tp-grade-chart`/`.tp-grade-row`/`.tp-table-wrap` (already covered at both
the 680px breakpoint and the general responsive rules), `talentedSection`
reuses `.tp-primary-indicator`/`.tp-grade-chart` (already covered), and the
new Classification filter field reuses the same generic `.tp-filters
label`/`select` styling as every other filter (flex-wrap at desktop, one
field per row via `grid-template-columns:1fr` at the 680px breakpoint). No
CSS gap was found; no CSS change was made in this pass.

**(e) `candidate_membership_count` decision:** kept, not removed - it is a
distinct, still-legitimate Review-Candidate-policy-match count (the legacy
Review Candidate workflow's "meets this Program's eligibility policy"
grain), never the M17 automatic Classification/Talented grain, and never
literally uses "identified"/"candidate_of_eligible" percentage-share
wording. Its Results & Analytics summary-card label is relabeled
`"Legacy: Meets Program Criteria"` (previously unqualified `"Meets Program
Criteria"`) so it can never be read as a current-Talent figure next to the
new Classification/Talented sections on this same page, matching the
existing Legacy-qualifier pattern already used for `candidate_of_eligible`/
`identified_of_eligible`. The underlying metric/data/permission are
completely unchanged; the separate `candidate_count` label (Program
Portfolio/Branch pages, out of scope for this page) is untouched.

**Regression:** `tests/talent_results_experience.test.cjs` - 28 tests (24 ->
28, 4 new), 26 passed/2 failed, the identical 2 pre-existing failures by
exact test name at both this change and the unmodified M18b-2 baseline
`5aa13cb` (git-stash-verified, not assumed). `tests/
talent_branch_comparison_frontend.test.cjs` + `tests/
talent_experience_adjustments.test.cjs` + `tests/talent_ui.test.cjs`: 41
tests/38 passed/3 failed, identical 3 pre-existing failures by exact test
name at both states (git-stash-verified). `tests/test_talent_results_
analytics.py` + `tests/test_talent_ui.py`: 51/51 passed. `tests/
test_talent_organization_analytics_providers.py` (confirms the page-chrome
title assertion is unaffected): 22/22 passed. No schema/migration change;
`tis.db` byte-identical before/after this task (SHA-256 verified
`01e1a3065d92280ee9228db921f67545c8b837d4ecd787a5aeeddc6d128fc136`).

**Still open for M18b-3:** Evaluation Period and Competency filter controls
(would need new supporting list endpoints); a chart-type selector was
evaluated as unnecessary (bar-only compatibility matrix) rather than added;
full broad M14-M18 regression/performance/KMS closeout.

## M18b-2 Results & Analytics Frontend Rebuild - current-Talent indicator + new-family consumption (2026-09-24)

Bounded FRONTEND-ONLY sub-phase consuming the M18b-1 backend contract
(`/api/talent/results-analytics/...`). No backend semantic change; M18b-3
(final broad regression/performance/KMS closeout for the full M18 milestone)
remains separately scoped and still pending.

**What changed:** `static/js/talent.js`'s `analytics` view (Results &
Analytics landing page) now calls all three M18b-1 families - Learning Style
(`/academic-years/{ay}/learning-style`, Student-domain-wide, gated on
`students.view`), Classification (`/programs/{pid}/academic-years/{ay}/
classification`, Program-bound, exactly the 5 backend bands), and Talented
(`/programs/{pid}/academic-years/{ay}/talented`, Program-bound, Exceptional-
only) - and renders them with new reusable helpers: `bucketBars`/
`bucketTable`/`distributionSection` (chart+accessible-table pair for Learning
Style/Classification) and `talentedSection` (primary current-Talent
indicator with an optional per-Branch breakdown, reusing the same visual
classes as the existing `gradeBars`/`branchBars` primitives - no new charting
library, no CSS change). The competency (`/api/talent/analytics/.../
rubric-distribution`) and progress/branch-comparison
(`/api/talent/evaluation-progress/...`) sections were already correctly
wired to the right existing governed endpoints and were left unchanged.

**Legacy-metric removal from the current-Talent section:** the previous
`identifiedIndicator` primary indicator (sourced from the legacy
`identified_of_eligible`/Official Identification `talent-map` projection) is
removed from this view. `talentedSection` (backed by the new M17-
classification-derived Talented family) is now the only current-Talent
indicator here. The underlying legacy Review Candidate/Official
Identification services, routers, data, and the separate Talent Review
workspace are completely unchanged; `identified_of_eligible`/
`candidate_of_eligible` remain valid, unrelabeled options only in the
still-supported legacy Branch-comparison metric selector (a different
control/view), never presented as current Talent state.

**Permission surfacing (small, non-semantic, additive):**
`routers/talent_ui.py` now additively includes `"students.view"` in the
`talent_permissions` dict passed to the template, purely so the frontend can
gate the new Learning Style section's fetch/render on the same permission
its backend route already requires - no new authorization scope, no change
to any endpoint's actual permission check.

**Regression (git-worktree-verified against the unmodified M18b-1 baseline
`2bf9b8c`):** `tests/talent_*.test.cjs` - 170 tests/154 passed/16 failed on
this task's changes versus 165/149/16 at baseline, the identical 16
pre-existing failures by exact test name in both runs, zero new JS
failures. `tests/test_talent_results_analytics.py` + `tests/test_talent_ui.py`
(the exactly-named M18b-2 focused Python/UI regression set): 51/51 passed.
No schema/migration change; `tis.db` byte-identical before/after (SHA-256
verified).

**Explicitly not done in this task (open for M18b-2b/M18b-3):** the full
9-section Results & Analytics information-architecture reorder (page
header, progressive filter bar across Program/Branch/Grade/Section/
Evaluation Period/Competency/Learning Style/Classification, a full chart-
type-selector/keyboard/WCAG audit, and explicit mobile responsive
verification) called for by the M18b-2 task specification was not
completed end-to-end - this pass targeted the highest-value, most
defect-prone item (a legacy metric presented as the current Talent state)
and made the three new backend families reachable from the UI with
accessible chart+table pairs and privacy-safe neutral states, rather than a
full visual rebuild of the page.

## M18b-1 Results & Analytics Backend Contract + Correct Aggregation Authority (2026-09-24)

Bounded BACKEND-ONLY sub-phase of the M18b Results & Analytics rebuild (the
visible page/chart rebuild is the separate, still-pending M18b-2; no
template/chart-rendering change was made here). Delivers the backend
authority M18a explicitly deferred.

**Contract decision:** `talent_org_intelligence_contract.MetricCode` remains
frozen and unmodified (ADR 0044) - the new current-classification/Talented
grain is NOT added to it. A new module,
`talent_results_analytics_service.py`, reuses the existing M9
`talent_analytics_service` Program+AcademicYear context/filter/scope
architecture (`resolve_context`/`resolve_filters`/`population_query`) and the
same generic `Cell`/`Group`/`apply_primary_privacy`/
`run_complementary_suppression` privacy primitives every M9 breakdown already
uses, adding one new opaque privacy class (`"P4"`) for this grain - never the
legacy `CANDIDATE_COUNT`/`IDENTIFIED_COUNT`-family metrics, which remain
legacy-Review/Identification-grain only. One coherent router,
`routers/talent_results_analytics.py` (`/api/talent/results-analytics/...`),
serves three families:

- **Learning Style** (`/academic-years/{academic_year_id}/learning-style`) -
  thin reuse of `student_learning_style_analytics.py` (M14), gated on the
  existing `students.view` permission; no new computation.
- **Classification**
  (`/programs/{id}/academic-years/{id}/classification`) - the current M17
  classification distribution (five owner-approved bands) over the exact
  M18a-governed grain (`TalentStudentAssessment.status == 'completed' AND
  is_current == True`), reusing `talent_classification_service.
  assessment_classification` for every band decision (never a duplicated
  band table; `talent_classification_service.CLASSIFICATION_LABELS` is now
  exported read-only for this purpose). A rubric-incompatible ("available:
  False") Assessment is tracked as `not_currently_classifiable_count`, never
  fabricated into a band.
- **Talented** (`/programs/{id}/academic-years/{id}/talented`) - current
  Talented (Exceptional-only) count, applicable denominator, and rate,
  projected from the same classification computation.

**Correct Organization aggregation (the CRITICAL invariant, regression-
tested exactly):** `talent_results_analytics_service.
sum_raw_counts_across_branches` is a pure function that sums each Branch's
own raw bucket counts - the ONLY Organization/Branch rollup rule anywhere in
this module. Proof case: Branch A 1 Talented/2 applicable (50%), Branch B 9
Talented/90 applicable (10%) -> Organization 10/92 (~10.87%), never the naive
30% average of the two Branch rates (`tests/test_talent_results_analytics.py`,
Sections A and C).

**`learning_style_dimension` dead-parameter cleanup:** re-audited directly
(not assumed) and confirmed still genuinely unreferenced inside
`branch_comparison_metric`'s own body (the "learning_style" metric it
existed to parameterize has never been a member of
`APPROVED_BRANCH_METRICS` since M14) - removed outright from
`routers/talent_evaluation_progress.py`'s branch-comparison route and from
`branch_comparison_metric`'s signature in
`talent_evaluation_progress_service.py`; the one stale frontend-contract test
assertion for the now-nonexistent parameter
(`tests/talent_branch_comparison_frontend.test.cjs`) is removed. No behavior
change: `branch_comparison_metric` still rejects any `metric` outside the six
`APPROVED_BRANCH_METRICS` exactly as before.

**Competency and Progress families are deliberately NOT reimplemented here.**
`routers/talent_analytics.py`'s existing `/rubric-distribution` route
(Program-bound, canonical framework/competency identity, governed
completed/current evidence semantics) and
`routers/talent_evaluation_progress.py`'s existing branch/organization/
branch-comparison routes (ACTIVE/OPENED weighting, framework comparability,
raw Overall Result semantics) already provide governed, privacy-safe backend
analytics for those two families with correct, unaltered semantics - M18b-2's
frontend calls those existing routes directly for Competency/Progress and the
new `/api/talent/results-analytics/...` routes for Learning
Style/Classification/Talented.

**Regression:** full `-k talent` pytest suite (746 passed / 11 failed,
worktree-compared byte-identical by exact test name against the unmodified
81cfa75 baseline - all 11 pre-existing, zero new) and the full
`node --test tests/*.test.cjs` suite (17 unique pre-existing failures,
down from 18 at baseline - `talent_branch_comparison_frontend.test.cjs`'s
stale `learning_style_dimension` assertion fixed, zero new failures). No
schema/migration change; `tis.db` byte-identical before/after (SHA-256
verified). M18b-2 (the visible Results & Analytics page/chart rebuild
consuming this contract) remains explicitly out of scope and was not
implemented here.

## M18a Current Talent Authority Alignment + Learning Style Cleanup + Privacy UX (2026-09-23)

Bounded first half of the M18 milestone (the full Results & Analytics page
rebuild is M18b and remains out of scope here). Four areas, closed:

**Applicable-current-result authority (resolved, not invented):** for a
Talent Program, the Assessment that governs a Student's current M17
classification is the `TalentStudentAssessment` row where
`status == 'completed'` AND `is_current == True` - the exact pre-existing
authority ADR 0036 (Talent Rubric Reassessment Attempts) already established
and that M9 analytics (`talent_analytics_service._assessment_ids_subquery`)
and the B9 Student Drill already consumed before this milestone. No new rule
was introduced.

**Part 1 - current Talented authority:** the Learner Profile
(`talent_learner_profile_service.build_learner_profile`) and the B9 Student
Drill (`talent_org_student_drill.py`) now additively expose the same
backend-authoritative M17 classification (`classification`,
`classification_score`, `is_talented`, via
`talent_classification_service.assessment_classification`) already wired
into `routers/talent_assessments.py` since M17 - reusing the single
classification authority, never a duplicated derivation, never sourced from
`TalentReviewCandidate`/`TalentOfficialIdentification`. Building a NEW
org/Branch AGGREGATE "current Talented count" metric was explicitly
evaluated and deferred to M18b: `talent_org_intelligence_contract.MetricCode`
is a frozen 14-value enum (ADR 0044 explicitly states "no MetricCode
extension"), and the only existing Talent-adjacent aggregate metrics
(`CANDIDATE_COUNT`/`CANDIDATE_OF_ELIGIBLE`/`IDENTIFIED_COUNT`/
`IDENTIFIED_OF_ELIGIBLE`) are grounded in the legacy Review/Identification
membership grains, not an M17-classification grain - adding a privacy-safe
Cell/Group aggregate for the new grain is real new analytics infrastructure
that belongs with the M18b Results & Analytics rebuild, not a cleanup task.
`static/js/talent.js`'s `candidate_of_eligible`/`identified_of_eligible`
labels ("Talent share"/"Officially confirmed share" - which read as CURRENT
Talent-status shares even though their underlying data is the legacy
Review/Identification workflow) are relabeled "Legacy review share"/"Legacy
identification share"; the underlying metrics, data, and permissions are
completely unchanged. `TalentReviewCandidate`/`TalentOfficialIdentification`
rows, services, and routers remain fully preserved as legacy/history,
byte-identical, code-unchanged.

**Part 2 - M14 Learning Style deprecation completed:** `routers/students.py`
(`_student_json`) and `routers/students_ui.py` (`_student_view`) no longer
serialize `learning_style_verbal_percentage`/`learning_style_non_verbal_percentage`/
`learning_style_quantitative_percentage`/`learning_style_spatial_percentage`
in the current normal Student API/UI projection (verified: they still did,
including as literal `null`, before this milestone). Stored DB columns and
historical values are completely untouched - only read exposure is removed.
`talent_evaluation_progress_service.py`'s `learning_style_branch_aggregate`/
`_learning_style_values_by_branch`/`_LEARNING_STYLE_COLUMNS` (dead since the
M14 dispatcher removal, kept only so the deprecated-column computation was
not silently mutated) were confirmed genuinely unreachable from any current
endpoint/service path and removed outright, along with their two stale
direct-call tests. There is no current four-dimension Learning Style
analytics authority anywhere in the repository after M18a. M14's own
governing model (one categorical `learning_style` value; aggregate
distribution over eight categories + Unassigned; no per-Student percentage
dimensions or bars) is unchanged and still served by
`student_learning_style_analytics.py`.

**Part 3 - privacy copy cleanup (presentation only):** the literal visible
phrase "Protected for privacy" is removed from Talent & Potential /
Learning Style UI (`static/js/talent.js`, `talent-rubric-visual.js`,
`talent-experience.js`, `templates/students.html`) and replaced with
context-appropriate neutral copy ("Unavailable", "Not available for this
view", "This distribution/rubric distribution is not available for this
selection", "Distribution unavailable") - never one mechanical replacement
everywhere. The underlying privacy/suppression contract (primary suppression,
complementary suppression, minimum-population rules, anti-reconstruction,
tenant/Branch/organization scope) is completely unchanged; no protected
numeric value was ever in the copy being replaced, and none is introduced by
the new neutral copy.

M18b (the full Results & Analytics page rebuild, including any new org/Branch
aggregate Talented-count analytics) remains explicitly out of scope and was
not implemented here.

## M17 Automatic Assessment Classification + New Normal Talent Workflow (2026-09-23)

Owner-approved product direction: Student -> Program -> Rubric -> Teacher
assesses -> Complete/Submit -> the backend automatically classifies the
result. On a Completed Assessment, TIS derives the ADR 0037 Overall Program
Result as before, then (ADR 0037's 2026-09-23 Amendment) deterministically
projects it onto a governed 1.00-5.00 classification scale and assigns
exactly one fixed, owner-approved band: 1.00-1.99 Needs Improvement,
2.00-2.99 Developing, 3.00-3.74 Meets Expectations, 3.75-4.49 Advanced,
4.50-5.00 Exceptional. Only Exceptional is Talented. These bands are never a
percentage and never reuse `normalized_percent`.

**Architecture decision (Part 1):** real configured Talent Programs do not
universally use a five-level rubric (the realistic seed dataset in
`talent_local_test_data.py` configures 4-level, 3-level, and 4-level
Programs). Mandating a system-wide five-level rubric would have broken real
Program configurations. TIS instead preserves each Program's own configured
1..N rubric scale for the raw educational result exactly as ADR 0037 already
defines it, and adds one additional, separately governed deterministic
linear projection from that raw 1..N average onto the fixed 1.00-5.00
classification scale, reusing the same linear-rescale technique ADR 0037
already approves for `normalized_percent`. See
`talent_classification_service.py` and ADR 0037's 2026-09-23 Amendment.

The normal current workflow no longer requires a manual Review Candidate or
Official Identification step to make a Student Talented - `Talented` is now
a direct backend consequence of a Completed Assessment's automatic
classification. Existing `TalentReviewCandidate`/`TalentOfficialIdentification`
rows (including ones recorded before this milestone) are fully preserved as
legacy/history evidence, remain reachable through their existing services,
and are never silently rewritten to match a later automatic classification -
they simply no longer govern current `Talented` state. No schema migration
was required: classification is a deterministic read projection over the
same immutable Completed-Assessment inputs the Overall Program Result
already uses, computed only when `status == "completed"`.

API: `/api/talent/assessments/*` and `/api/talent/review-candidates/*`
responses additively expose backend-computed `classification`,
`classification_score`, and `is_talented` fields; the frontend only ever
displays these values and never derives or spoofs a band. The Talent
assessment and legacy Review workspaces (`static/js/talent-operations.js`)
show the classification/Talented state, and the legacy Review workspace
copy now describes Review status/Official Identification as preserved
history rather than a required step. M18 (Results & Analytics rebuild,
including the Learner Profile/organization-analytics visible-copy
implications of this new classification authority) remains out of scope and
was not implemented here.

## M16 Talent Module Performance And Student Actions (2026-09-23)

Implemented on the isolated `m16-talent-performance` branch from `50c049f`.
Talent page permission projection calls are bounded at three (previously roughly
28-31 through repeated per-key checks), and unrelated operational JavaScript is
not emitted by Overview/analytics or other non-owning surfaces. Depending on the
surface, two to four of the former six scripts are emitted; Overview/analytics
drop about 135 KB of unminified JavaScript. Student action containers now render
as wrapping horizontal flex rows. No schema, migration, API, authorization,
tenant/Branch isolation, analytics calculation, or product-semantic change was
introduced. Deployment surface is Web Service only; the timetable workflow is
unchanged.

## M14 Students + Talent & Potential — Learning Style Correction + Aggregate Distribution (2026-09-23)

Owner-directed correction milestone following a read-only Post-M13
Correction Review. Two corrections, both governed by amendments to ADR 0031
and ADR 0042 (see each ADR's own "M14 Amendment"/"M14 Correction" section)
and, for the removed Talent metric, ADR 0044's M14 Amendment section:

1. **Learning Style is ONE categorical selection per Student, extended from
   four to eight values.** `Student.learning_style` now accepts Visual,
   Auditory, Read/Write, Kinesthetic (original four, unchanged) plus Verbal,
   Non-verbal, Quantitative, Spatial (added). Those four added values were
   previously, mistakenly, modeled as an independent four-dimension
   percentage profile (`learning_style_verbal_percentage`,
   `learning_style_non_verbal_percentage`,
   `learning_style_quantitative_percentage`,
   `learning_style_spatial_percentage`; ADR 0042/M1-M3). Verified against
   actual code that, contrary to ADR 0042's own stated M1 scope boundary,
   the M2/M3 delivery had already built a full create/update/GET API and a
   real Student create/edit frontend for the four percentages - while the
   ORIGINAL single-select categorical field from ADR 0031 had never received
   any create/edit frontend selector at all until this milestone. Student
   create/edit now shows one Learning Style selector (all eight values, plus
   "Not assigned"); the Student profile shows the one selected value (or
   "Not assigned") instead of four percentage bars; Talent Student context
   reads the current categorical value directly (no historical snapshot, no
   effect on rubric/Assessment/Overall Result/Evaluation
   Progress/classification/Candidate-Identification).
2. **"Percentage" means population/aggregate distribution, never a
   per-Student dimension percentage.** The four
   `learning_style_*_percentage` columns are now OPERATIONALLY DEPRECATED:
   no longer written (API/UI create/edit no longer accept them - silently
   ignored, never a validation error), no longer displayed anywhere, and no
   longer read as Learning Style authority anywhere, including the M4/M10
   Talent Evaluation Progress "Learning Style" Branch-comparison metric
   (which averaged them) - that metric is REMOVED from
   `talent_evaluation_progress_service.APPROVED_BRANCH_METRICS` (six
   approved metrics remain; a request for it now receives the same
   `invalid_filter`/400 as any other unrecognized metric). Existing stored
   percentage values are preserved completely untouched (no backfill, no
   conversion, no clearing) - physical column removal is a separately
   gated, later cleanup contingent on an explicit data-occupancy
   verification this milestone could not safely perform (the local `tis.db`
   has no `students` table at all, so real occupancy could not be inspected
   either way). `student_learning_style_analytics.py` (the existing
   privacy-safe categorical count/percentage/"Unassigned" distribution
   engine, reused and extended rather than parallel-built) now covers all
   eight categorical values plus an "Unassigned" bucket for the authorized
   Student population; the denominator is always every authorized Student in
   scope, including Unassigned Students - this is served at the existing
   Students page summary location, unchanged in scope/authorization/privacy
   contract from ADR 0031.

Database: one forward-only migration
(`20260923_002_student_learning_style_eight_values`) widens
`ck_students_learning_style` from four to eight values on PostgreSQL
(`DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT ... NOT VALID` +
`VALIDATE CONSTRAINT`, mirroring the exact pattern already used elsewhere in
`db_migrations.py` for widening a CHECK constraint under the same name);
SQLite continues to rely on the service-layer guard for an already-migrated
database, exactly like the original `_student_learning_style_v1` migration,
and a fresh SQLite database gets the widened constraint directly from
`models.py`'s current `CheckConstraint`. No column is added or dropped, no
row is rewritten, and `tis.db` is unchanged (verified by SHA-256 before and
after this task).

`student_roster_service.py`'s column contract was inspected and does not
include Learning Style or the four percentage columns at all - roster scope
is therefore untouched by this milestone, per its explicit boundary.

Out of scope for M14 (left for later, separately governed milestones):
Student deletion/count correction, roster redesign, Student action layout,
Talent whole-module performance, assessment classification, the full
Results & Analytics rebuild, and any privacy-copy cleanup beyond the
Learning-Style-specific surfaces touched here.

## M13 Students + Talent & Potential Release Readiness Closeout (2026-09-23)

Final release-readiness verification for the bounded Students + Talent &
Potential update package (Student ID, Learning Style, Al-Andalus Section
display, Student roster, Talent frontend cleanup, Evaluation Progress,
Results & Analytics Branch comparison, M1-M12.1). This is documentation-only
verification/closeout, not new development and not a deployment.

Spot-checked each feature area against current code (not only KMS prose) and
found the implementation matches documented behavior: `models.py` Learning
Style columns/CHECK constraints and the canonical <=63-character managed
active-per-Student index name; `db_migrations.py` ledger ordering
(`20260922_001` -> `20260922_002` -> `20260923_001`); the Al-Andalus
workspace UUID gate; `routers/students.py` permission checks for
`students.import`/`students.export`; `static/js/talent-operations.js`'s
`button('reload', ...)` no-op and `talent_educator_inputs.*` permission
short-circuit removing Reload Saved Rubric and Educator Input from the normal
Talent UI; and the backend-authoritative Overall Result/framework-mismatch
handling in `static/js/student-evaluation-progress.js`/`static/js/talent.js`.

Corrected three stale current-state wording instances left over from before
M11 shipped, found by a repository-wide sweep for "deferred"/"assigned to
M11"/"remains absent" phrasing scoped to this package - `docs/AI_PROJECT_CONTEXT.md`'s
M7 section, `docs/TIS_MASTER_CONTEXT.md`'s M7 section, and
`docs/engineering/TIS_MODULE_MAP.md`'s Students module section each still
said roster import/export was "deferred"/"assigned"/"absent" pending M11,
even though M11 (documented immediately above each of those sections in the
same files) has since implemented it. Each was reworded to state the
now-accurate current fact (M7 was out of scope; M11 implemented it) without
altering the historical description of what M7 itself added. No other stale
"deferred"/"not implemented"/"planned"/"dormant"/"backend only"/"frontend
pending" wording scoped to this package was found; dated
`docs/CHANGE_HISTORY.md` entries and other dated `docs/PROJECT_STATE.md`
section headers describing what was true at the time they were written were
left unchanged, matching the historical-log convention.

Reconfirmed the M12.1 PostgreSQL remediation entry below is complete and
internally consistent (canonical index name, forward migration, no Student
row mutation, `tis.db` SHA-256 unchanged) and that the M12 entry's forward
reference to M12.1 is accurate. Re-ran, on real PostgreSQL
(`TIS_TEST_POSTGRESQL_URL`), `tests/test_postgresql_migration_transactions.py`:
11 passed, 5 failed - the same five pre-existing, unrelated Talent
baseline-metadata foreign-key-ordering failures M12.1 already documented
(`UndefinedTable` for `talent_framework_competencies`), unchanged and not
introduced by this package. `tests/test_permission_registry_matrix.py` (13
passed) and `tests/test_student_managed_number_service.py` (46 passed) were
also re-run and pass.

Added a new durable release-handoff document,
`docs/releases/2026-09-23-students-talent-m1-m13-release-handoff.md`
(indexed in `docs/README.md`), covering user-visible changes, permission
scope, the three required migrations and the PostgreSQL remediation
requirement, compatibility notes, privacy/tenant-isolation invariants, known
pre-existing issues, deployment surfaces (Web Service only - this package
does not require a coordinated `tis-timetable-workflow` deploy), a
migration/deployment sequence plan, rollback considerations, and a
post-deploy smoke-test matrix. No schema, migration, permission, or product
behavior change was made in this closeout task; `tis.db` is verified
byte-identical (SHA-256
`01e1a3065d92280ee9228db921f67545c8b837d4ecd787a5aeeddc6d128fc136`) before and
after. Closing M13 closes only this bounded package, not the entire Talent
product roadmap.

## M12.1 PostgreSQL Managed Student Number Index Identifier Remediation (2026-09-23)

Fixes the PostgreSQL identifier-length risk M12 (below) documented but
deliberately did not fix. The M1 active-per-Student partial unique index was
declared as `uq_student_external_identifiers_tis_student_number_active_student`
(65 characters), exceeding PostgreSQL's 63-character `NAMEDATALEN` limit.
Live verification against a real PostgreSQL test database (`TIS_TEST_POSTGRESQL_URL`)
in this task confirmed PostgreSQL silently truncates it on `CREATE UNIQUE
INDEX` to the 63-character physical name
`uq_student_external_identifiers_tis_student_number_active_stude`, and
confirmed re-running the original migration function a second time against
that truncated physical index fails with `psycopg2.errors.DuplicateTable`,
exactly as M12 predicted.

The canonical replacement name is
`uq_student_external_identifiers_tis_number_active_student` (57 characters).
`models.py`'s `Index` declaration and the original
`20260922_002_student_tis_number_identifier_integrity` migration
(`db_migrations.py`) now create this canonical name directly on any FRESH
database (SQLite or PostgreSQL) - the old 65-character name is never created
anywhere anymore. A new forward migration,
`20260923_001_student_tis_number_index_identifier_length_remediation`,
handles an already-migrated PostgreSQL database: using SQLAlchemy's
PostgreSQL catalog inspection (`inspect(...).get_indexes(...)`, including
the reflected `postgresql_where` partial predicate), it verifies the actual
definition of any index at the old truncated name (columns, uniqueness,
predicate) before renaming it with `ALTER INDEX ... RENAME TO` - never a
drop/recreate, never a row rewrite. It is a no-op if the canonical index is
already present, reuses the original migration's existing
preflight-conflict checks (non-canonical values, cross-SchoolGroup
duplicates, multiple active rows) to create the canonical index directly if
neither name exists, and fails closed with a descriptive `RuntimeError` -
never a silent guess - if both names exist simultaneously or if an
unexpected index occupies either name.

The partial-unique-index semantic invariant (ADR 0043: `UNIQUE (student_id)
WHERE namespace = 'tis_student_number' AND status = 'active'`) is completely
unchanged, and the separate global Student-number value-uniqueness index
(`uq_student_external_identifiers_tis_student_number_value`, 56 characters)
was inspected and confirmed to have no length problem - it was not touched.
No `Student` or `StudentExternalIdentifier` row was read, rewritten, merged,
or deleted. The checked-in `tis.db` is verified byte-identical
(SHA-256 `01e1a3065d92280ee9228db921f67545c8b837d4ecd787a5aeeddc6d128fc136`)
before and after this task; SQLite is unaffected by this fix because it
never truncated the name. This is a PostgreSQL-only physical
schema-identifier correction - no product, API, or frontend change, and it
does not itself require a coordinated Web + Timetable Workflow deploy
(Students/Talent schema only, unrelated to the timetable solver/worker
contract). Tested live against a real PostgreSQL database
(`tests/test_postgresql_migration_transactions.py`): fresh-database
canonical-name creation, truncated-legacy-index rename, idempotent no-op on
rerun, no-op when canonical already present, fail-closed on an unexpected
index at either name, fail-closed when both names exist, row-data and
uniqueness-semantics preservation across the rename, and the migration-ledger
path for a database where the original M1 migration is already recorded as
applied - all passed. `docs/adr/0043-tis-student-number-managed-identifier-invariant.md`
records this as an implementation-detail amendment (physical index name
only; the ADR's governance decision is unchanged).

## M12 Integrated QA / Regression Verification (2026-09-23)

Students + Talent & Potential M1-M11 were re-verified end to end (Student ID,
Learning Style, Al-Andalus Section display, Evaluation Progress, Student
roster backend/frontend, Talent frontend cleanup, Results & Analytics,
permissions, tenant isolation, historical/frozen attribution, privacy/
suppression). No new functional/UX regression was found. One stale test
fixture was corrected: `tests/test_permission_registry_matrix.py` still
listed `routers/students_ui.py` as a live consumer of
`talent_educator_inputs.view` after M8 (commit `b7c4791`) intentionally made
that route pass `include_educator_inputs=False` unconditionally instead of
gating on the permission; the permission itself remains active-enforced via
its two real consumers (`routers/talent_educator_inputs.py`,
`routers/talent_learner_profiles.py`). This is a test-fixture correction
only, matching already-shipped M8 behavior - no product, permission, or
architecture change.

**Deployment risk identified here - remediated the same day by M12.1
above:** the PostgreSQL index name
`uq_student_external_identifiers_tis_student_number_active_student`
(`models.py`; re-declared as raw DDL in `db_migrations.py`, migration
`20260922_002_student_tis_number_identifier_integrity`; introduced in
Student M1 commit `e98214f`) is 65 characters, exceeding PostgreSQL's
63-character `NAMEDATALEN` identifier limit. PostgreSQL silently truncates
the name on `CREATE UNIQUE INDEX` rather than erroring, which breaks this
migration's own idempotency check (`_index_exists()` compares against the
full untruncated 65-character name and will never match the truncated
63-character name PostgreSQL actually stores) - a redeploy that re-applies
the full migration ledger against a real PostgreSQL database would attempt
`CREATE UNIQUE INDEX` a second time and fail with a `DuplicateTable`/
"relation already exists" error, aborting that migration. SQLite (`tis.db`)
has no such identifier-length limit and is unaffected, which is why this was
invisible to all SQLite-backed test runs; it was found and reproduced this
session against a live PostgreSQL test database. Fixing it requires
renaming the index in schema-defining code (`models.py`/`db_migrations.py`)
plus an Owner/architecture decision on rename-and-release coordination for
any environment where this migration may already have run - both explicitly
outside M12's verification-only scope. This must be triaged before any
future PostgreSQL deployment re-applies the migration ledger; it does not
block SQLite-based development/M13 frontend work.

## Student Roster Import / Export Frontend M11 Implemented (2026-09-23)

The existing Students list now presents **Import Students** only with
`students.import` and **Export Students** only with `students.export`; M6 still
authorizes every API request. Export consumes `GET /api/students/roster/export`
as an opaque workbook download and preserves the server filename.

Import uses a transient accessible dialog rather than a persistent page panel.
It accepts `.xlsx` only, shows the selected filename, uploads multipart field
`roster_file` to the M6 preview endpoint, and renders backend-provided totals,
valid rows, row numbers, fields, safe messages, canonical Student/Placement
display fields, and privacy-safe duplicate identity where supplied. The UI uses
text nodes for backend content and does not expose raw exceptions.

Apply requires an explicit confirmation and uploads the original workbook again
to the M6 apply endpoint. It never submits client-generated valid rows or offers
partial import. Successful atomic apply clears stale state and reloads the
Students roster; rejection retains useful preview/file state and explains that
no Students were created. Copy is create-only and does not imply update, merge,
sync, overwrite, or upsert.

Student IDs remain strings with canonical `STD` presentation and leading zeroes.
The browser performs no workbook parsing, uniqueness check, tenant inference,
Branch/Academic-Year/Section authorization, or `section_display` conversion.
No CSV/`.xls`, persistent batch, background job, backend change, schema, or
migration is included.

## Student Integrity, Talent Visibility & Roster Round-Trip M15 Implemented (2026-09-23)

M15 (isolated `m15-student-integrity-roster` feature branch, off `50c049f`)
delivers two owner corrections without schema change.

**Student permanent delete -> Talent visibility.** `force_delete_student_history`
(`student_academic_service.py`) already deletes every Student-owned table in
FK-safe child-before-parent order and never commits itself; Talent current
operational surfaces INNER-join `models.Student`, so a force-deleted Student
cannot appear anywhere in Talent & Potential. The owner's "~9 vs ~13" mismatch
is a population-scope distinction, not a deletion defect: the Students list is
Branch-scoped (single authorized Branch unless `students.view_all_branches` +
organization/global scope) over current effective Placement, while Talent/Review
span frozen `TalentAssessmentCyclePopulationMember` membership (historical,
multi-Branch) and the eligible-students roster intentionally does not filter
`Student.status` (ADR 0039). Locked by
`tests/test_student_delete_talent_visibility.py` (full-chain cascade removal,
blockers, rollback/transaction boundary, tenant isolation).

**Student roster round-trip.** `student_roster_service.py` export now re-imports
cleanly: `section_display` is accepted-but-ignored (display-only, never identity;
`section` remains canonical identity per ADR 0045), and the canonical `STD`
prefix is stripped back to the 10-digit business value on import. Import stays
create-only: unchanged exported rows classify **NO_CHANGE** (managed Student ID
resolves identity; name/gender/status + current Placement Branch/Year/Grade/
Section must match exactly), new rows **CREATE**, and any mutated existing row
stays a blocked `student_id_conflict` (never update/merge/upsert). Apply writes
only CREATE rows, skips NO_CHANGE rows, and stays atomic. Export formatting adds
a bold header, frozen header row, deterministic widths, and autofilter.
`static/js/students-roster.js` renders CREATE / No change / error from backend
row status. Permissions, tenant/Branch scope, uniqueness, and audit unchanged.

## Results & Analytics Branch Comparison Frontend M10 Implemented (2026-09-23)

Organization Overview's prior fixed Branch summary is replaced by one primary,
Program-scoped Branch comparison chart consuming the existing M4
`GET /api/talent/evaluation-progress/programs/{program_id}/academic-years/
{academic_year_id}/branch-comparison` contract. The metric selector exposes
only Evaluation Period Result, Overall Result, Assessment Completion,
Assessments Started, permission-projected Meets Program Criteria and Officially
Confirmed, and Learning Style. Learning Style conditionally exposes only
Verbal, Non-verbal, Quantitative, and Spatial and sends the selected dimension
to the backend.

Backend Branch and Evaluation Period ordering is preserved. Existing Talent Map
Branch columns provide the already-authorized display names for returned Branch
IDs. A numeric bar is rendered only for `state="visible"`; zero is valid, while
suppressed/complementary-suppressed, restricted, coarsened, and no-data states
remain distinct textual categories. Numeric/count fields are ignored for every
non-visible state. Framework-changed Overall Result remains non-numeric and is
explained without cross-version calculation.

The frontend does not calculate Branch or Organization means, derive one metric
from another, normalize Learning Style, inspect privacy thresholds, reconstruct
suppressed values, or group by current Placement. No Organization summary is
added because it is not a uniform field of the seven-metric comparison
contract. Frozen historical Branch attribution remains backend-authoritative.
No second chart, M11 roster frontend, backend semantic change, privacy redesign,
schema, or migration is introduced.

## Student Evaluation Progress Frontend M9 Implemented (2026-09-23)

The existing Student Profile Talent tab now consumes the M4
`GET /api/talent/evaluation-progress/programs/{program_id}/academic-years/
{academic_year_id}/students/{student_id}` contract for every authorized
Program/Academic-Year section already present in the Learner Profile. It shows
the backend-ordered active/opened Evaluation Periods using their configured
labels and explicit result states. Available percentages, including real zero,
are displayed exactly; Pending and other unavailable states are textual and
never rendered as `0%` or as a zero-valued progress bar.

The page renders **Overall Result** only from a backend-provided comparable
`current_overall_result`. A backend `framework_changed` response preserves all
individual Period results, omits the combined number, and explains that the
frameworks are not comparable. The dedicated frontend renderer does not read
`nominal_weight`, sort Periods, calculate averages, select active Periods, or
decide comparability. The endpoint retains existing Student/Talent permission,
tenant, and frozen historical Branch authorization; aggregate suppression is
not applicable to this single-Student contract.

Existing frozen Grade/Section presentation and M5 server-derived
`section_display` remain unchanged. No Branch/Organization Evaluation Progress
UI, M10 Branch comparison chart, M11 roster frontend, backend calculation,
privacy redesign, schema, or migration is introduced.

## Talent Frontend Cleanup M8 Implemented (2026-09-23)

The normal Talent assessment workspace no longer presents the Reload Saved
Rubric action or Educator Input read/create/amend/history controls. Their
obsolete frontend fetch/state/handlers are no longer active. Student Profile's
Talent tab likewise no longer requests or renders Educator Input as a normal
product concept.

This is presentation cleanup only. Historical rubric responses, competency
results, persisted Educator Input rows and amendment lineage, Official Results,
Candidate/Identification evidence, audit history, frozen population context,
and Framework references remain unchanged. Backend APIs/services and permissions
remain available for historical compatibility. Deterministic scoring and M5
server-derived Section presentation are unchanged.

Current four-dimension Learning Style display inside Talent is not assigned to
this cleanup by the authoritative roadmap and was not added. M9 Evaluation
Progress frontend, M10 Branch analytics charts, M11 roster frontend, migrations,
schema changes, new privacy logic, and new Student/Talent business rules remain
out of scope.

## Students M7 Frontend Implemented (2026-09-23)

The existing Students Jinja UI now uses the M2/M3 backend contracts for managed
TIS Student IDs and the current four-dimension Learning Style profile. New
Student creation renders a fixed `STD` prefix and submits exactly ten text
digits through `create_student_with_number`; list/profile render the canonical
value, and a legacy missing value is neutral rather than fabricated. Authorized
assignment/replacement is a separate `students.manage_identifiers` UI action.
Duplicate handling uses `describe_student_number_conflict`, exposing only the
approved minimal same-tenant identity when independently authorized and staying
generic for cross-tenant/unavailable values.

Create/edit expose optional Verbal, Non-verbal, Quantitative, and Spatial
whole-number inputs bounded 0-100. Profile display distinguishes unavailable
from 0%, provides visible text and progress ARIA, and never normalizes the four
values. The deprecated categorical value is preserved as historical data but is
not auto-converted or used as the normal Student profile/list/edit presentation.
Existing Placement and M5 server-produced `section_display` presentation are
consumed unchanged, including historical Placement context.

Implementation is bounded to `routers/students_ui.py`, existing Student
templates/JS/CSS, and focused tests. No schema/migration, backend API contract,
canonical Section identity, Student architecture, Learning Style architecture,
roster import/export frontend, Talent cleanup, Evaluation Progress UI, or
Results/Analytics chart work was introduced.

## Student Roster Import/Export Backend Implemented (M6) (2026-09-23)

Following the M6 governance prerequisite below (permission registration,
2026-09-22), the `students.import`/`students.export` roster import/export
backend is now implemented. First release, .xlsx-only, no frontend (M11,
later), no persistent import-job/batch table, no schema/migration.

**Service**: `student_roster_service.py` is a bounded roster service reusing
`student_academic_service.py`'s canonical Student/TIS Student number/Academic
Placement invariants (`create_student_with_number`,
`create_placement`, `describe_student_number_conflict`) - it never
duplicates canonicalization, uniqueness, or privacy-disclosure logic.
`student_academic_service.py` gained one new shared helper,
`describe_student_number_conflict`, extracted from the existing single-Student
create/replace 409 conflict handler in `routers/students.py` so that the
direct API, roster preview, and roster apply all share exactly one
implementation of the ADR 0043/M2 privacy-safe conflict-disclosure contract
(same-tenant + `students.view` reveals `student_id`/`display_name`;
cross-tenant or unauthorized same-tenant is fully generic) - never a richer or
different disclosure path for either surface.

**Scope decision (judgment call, not previously documented)**: M6 import is
CREATE-ONLY for this first release - every workbook row enrolls a NEW Student
with an initial Academic Placement. Updating an existing Student's identity or
placement through the roster file is out of scope for M6 and was not
attempted, avoiding invented merge/overwrite semantics the KMS does not
authorize.

**Routes** (`routers/students.py`, existing `students.*` permission-check
pattern via `_authorize`/`auth.has_permission`, tenant/Branch scope reused
from existing Student routes):
- `GET /api/students/roster/export` (`students.export`) - streams an `.xlsx`
  workbook (`openpyxl`, matching `routers/subjects.py`'s existing
  `StreamingResponse` convention). Columns: `student_id, first_name,
  father_name, last_name, gender, status, branch, academic_year, grade,
  section, section_display`. Tenant-isolated; a Branch-restricted actor only
  sees Students whose CURRENT effective Academic Placement Branch is in their
  accessible-Branch set (mirrors the existing granular Branch-gating already
  applied to placement data in `routers/students_ui.py`). Student ID is
  written as a canonical `STD`+10-digit TEXT cell (`number_format="@"`,
  Python `str`) so Excel never strips leading zeros or applies scientific
  notation; a legacy Student with no managed Student number gets a blank
  cell, never a fabricated one. `section_display` reuses
  `academic_grade.format_section_display` unchanged (ADR 0045): additive only,
  activates exclusively on the exact Al-Andalus `workspace_uuid`, and the
  canonical `section` column is never replaced by it.
- `POST /api/students/roster/import/preview` (`students.import`) - stateless,
  zero-DB-mutation: parses the uploaded `.xlsx` (`load_workbook(...,
  data_only=True, keep_links=False)`, so a formula cell is read as its cached
  value and never evaluated, and external links are dropped), validates
  workbook structure/headers/every row, normalizes values, resolves Branch/
  Academic Year/Grade/`PlanningSection` by canonical identity only (never the
  ADR 0045 `section_display` label, even for the Al-Andalus workspace), and
  runs the same privacy-safe TIS Student ID conflict check as the direct
  create API. Returns a bounded per-row result:
  `{row, status, data|errors}` with `errors` as
  `{row, field, error_code, safe_message}` - never a raw exception, SQL
  error, or sensitive tenant detail.
- `POST /api/students/roster/import/apply` (`students.import`) - never trusts
  a client-submitted preview payload: it independently re-parses and
  revalidates the freshly uploaded workbook using the identical validation
  core preview uses, then applies atomically inside the existing DB
  transaction pattern. Any row failure - including a `IntegrityError` race
  discovered only at apply time (classified as `student_id_conflict`, never
  the raw database error text) - rolls back the entire apply; there is no
  partial Student/Placement write.

**File safety**: `.xlsx` extension only; 5 MB upload-size and 2000-data-row
bounds (this feature's own explicit judgment call - no existing
repository-wide upload convention was found); malformed/empty/oversized
workbooks are rejected with a bounded file-level error
(`{row: null, field: null, error_code, safe_message}`), never a stack trace.

**Permission status**: `students.import`/`students.export` are reclassified
from dormant/reserved (`D`) to active-enforced (`A`) in
`tests/test_permission_registry_matrix.py`, matching the `subjects.import`/
`subjects.export` precedent (discovered consumer: `routers/students.py`, via
the same `_authorize` guard-call pattern already used by every other
`students.*` key). Dormant count 15→13, active count 143→145; total
registered keys unchanged at 177. No new role grant, no `DEVELOPER_ONLY`/
`OWNER_ONLY`/`ADMINISTRATOR_ONLY`/`LIMITED_READ_ONLY` membership change - the
governance decision recorded below is unchanged, only the enforcement status
now reflects that real routes exist.

**Tests**: `tests/test_student_roster_import_export.py` (40 focused tests
covering export tenant/Branch isolation, deterministic columns, Student-ID
text-cell/leading-zero preservation, legacy-no-ID handling; preview
statelessness, file/structural/row-level error classification, same-tenant
and cross-tenant privacy-safe conflict disclosure, Branch/Grade/Section/
Academic-Year reference validation, formula-cell and oversized-workbook
safety; apply atomicity, independent revalidation, race-conflict rollback,
permission/scope re-checking, and historical-placement non-corruption; and
M5/ADR 0045 regression proving `section_display` is never import matching
identity and stays additive-only on export). `tests/test_permission_registry_
matrix.py`'s classification update keeps all of its own tests passing.

## Student Roster Import/Export — Permission Registration (Governance Prerequisite, M6) (2026-09-22)

The Owner reviewed and approved registering exactly two new semantic
permission keys in the canonical `permission_registry.py` `students` group:
`students.import` ("Import student roster data") and `students.export`
("Export student roster data"). Both follow the exact existing
`students.*` naming/grouping/description/ordering convention and are
classified dormant/reserved (status `D` in
`tests/test_permission_registry_matrix.py`, matching the established
`teachers.import`/`teachers.export` precedent documented under "22-Key
Permission Registry Closure" below): no roster import/export route,
service, or frontend consumes them yet, so no template/nav/guard is wired
to either key. Neither key is added to `DEVELOPER_ONLY_PERMISSION_KEYS`,
`OWNER_ONLY_PERMISSION_KEYS`, `ADMINISTRATOR_ONLY_PERMISSION_KEYS`,
`LIMITED_READ_ONLY_PERMISSION_KEYS`, or `_EDITOR_LIKE_PERMISSIONS` - no new
default-role grant was introduced by this task; each key is assignable to
Administrator/Editor/User (the same class as the rest of the `students`
group) and, like every other `students.*` key, is included in the
Administrator role's default set only because `DEFAULT_ROLE_PERMISSIONS`
already computes Administrator's defaults as "all registered keys except
platform-only" - a pre-existing structural formula unchanged by this task,
not a new grant decision.

`students.import` permits Student roster import operations only within the
caller's already-authorized tenant/Branch/Student-management scope; it does
not expand tenant scope, bypass existing Student create/update
authorization, TIS Student ID rules, or Academic Placement validation,
grant cross-tenant access, or override backend invariant enforcement.
`students.export` permits Student roster export only for Students the
caller is otherwise authorized to access within the existing
tenant/Branch/Student scope; it does not expand Student visibility, grant
cross-tenant access, bypass existing scope restrictions, or authorize
unrelated Student operations. Permission and scope remain separate checks,
per the existing pattern used throughout this codebase.

This task registers only the two permission keys and this KMS record. It
implements no roster import/export service logic, API route, or frontend,
and changes no Student data, schema, or migration. The .xlsx-only,
stateless-preview, atomic-apply M6 roster import/export backend referenced
below (and in "Students + Talent & Potential M1" and "Student & Academic
Placement Foundation And Talent Program & Framework Foundation
Implemented") remains subsequent, separate, not-yet-implemented work; the
prior "deferred to later milestones" wording in those entries described the
pre-registration state and is superseded only insofar as the permission
governance prerequisite is now approved - roster import/export
functionality itself is still not implemented.

## Al-Andalus Section Display - Governance Authorization (2026-09-22)

Per new ADR 0045, the Owner has authorized the previously-deferred
Al-Andalus Section-display presentation convention for the exact verified
production `SchoolGroup.workspace_uuid` `72e52eb2-3844-447b-92a8-c55015f73257`
(identified using the repository's existing read-only production audit,
`scripts/audit_al_andalus_readonly.py`, run by the Owner against the
deployed Render PostgreSQL environment). Runtime implementation keys
exclusively off the exact `workspace_uuid` above (never
`SchoolGroup.name`/domain/email/Branch label), remains presentation-only,
and leaves canonical `PlanningSection`/Student Academic Placement/frozen
historical Talent Grade-Section identity, analytics grouping, and
query/filter/import-export identity completely unchanged - see ADR 0045
for the full authorized convention and fallback rule.

## Al-Andalus Section Display M5 - Shared Presentation Implementation (2026-09-22)

Implements the ADR 0045-authorized presentation convention. One shared,
authoritative helper, `academic_grade.format_section_display(workspace_uuid,
grade_level, section_name) -> str`, activates the numeric
`{grade_number}.{section_ordinal}` mapping only on exact
`SchoolGroup.workspace_uuid` equality to the authorized UUID above; every
other workspace, and any Grade/Section that does not deterministically map
(custom Section name, non-alphabetic/multi-character Section,
missing/malformed Grade, missing Section), returns the existing canonical
`section_name` unchanged. The helper never mutates or replaces canonical
`grade_level`/`section_name` - it is wired in as a bounded, additive
`section_display` projection alongside the unchanged canonical fields.

Wired surfaces (M5 boundary): Students UI current placement and placement
history (`routers/students_ui.py::_placement_view`, `templates/students.html`,
`templates/student_profile.html`), the Academic Placement Section selector
(`GET /students/sections`, `static/js/students.js`), the Students list
Grade/Section filter dropdown, the Talent frozen historical Learner Profile
context (`talent_learner_profile_service.py::build_learner_profile`'s
`frozen_context`, used by both `templates/student_profile.html`'s Talent tab
and the Talent workspace's own `learner-profile` view in
`static/js/talent.js`) - using the frozen `TalentAssessmentCyclePopulationMember`
Grade/Section, never the Student's current placement - the Talent Student
Assessment eligible-students roster (`GET
/api/talent/assessment-cycles/{id}/eligible-students`,
`static/js/talent-operations.js`), and the Talent Results/Analytics
Grade/Section filter (`GET /api/talent/programs/planning-sections`,
`static/js/talent.js`). Organization-analytics Grade/Section grouping
identity (e.g. `organization-analytics` grade-map column totals) is
unchanged and out of scope - ADR 0045 requires analytics grouping identity
to remain canonical.

Focused tests: `tests/test_academic_grade_section_display.py` (pure
formatter edge cases, exact UUID activation, A-Z ordinal spot-checks,
fallback cases) and `tests/test_al_andalus_section_display.py`
(cross-surface wiring: exact-UUID activation, a different-UUID row sharing
the exact organization name, workspace rename stability, other-tenant
isolation, canonical-value-unchanged/no-mutation checks, and frozen Talent
context proven to diverge from a later current-placement change). No
schema, migration, or new permission. No application behavior changed for
any workspace other than the one exact authorized `workspace_uuid`.

## Talent & Potential M4 — Authoritative Evaluation Progress Analytics (2026-09-22)

Implements the complete backend Evaluation Progress contract per ADR 0044,
building on M8 (Evaluation Plans/Periods), M9 (Deterministic Talent
Analytics privacy primitives), ADR 0037 (Overall Program Result), ADR 0031
/ ADR 0042 (Learning Style). New files: `talent_evaluation_progress_service.py`
(core logic) and `routers/talent_evaluation_progress.py` (four routes under
`/api/talent/evaluation-progress`), registered in `main.py` alongside the
other Talent routers. No schema, migration, or new permission.

**Active/opened predicate** (verified, not invented):
`TalentPlannedEvaluationPeriod.status == 'planned'` AND its linked
`TalentAssessmentCycle.status IN ('open', 'closed')`
(`resolve_active_periods`). Nominal weight `1/A` for A active Periods is
derived only, never persisted. Configured label/short_code never affect
order; only `sequence` does.

**Student Progress** (`GET .../students/{student_id}`, permission
`talent_learner_profiles.view`): per-active-Period result state
(`available`/`pending`/`incomplete`/`insufficient_evidence`/`unassessed`/
`not_applicable`), `normalized_percent` only when `available`, `Current
Overall Result` = mean of only the available results (Pending/unavailable
excluded, never zero), plus authoritative
`active_period_count`/`available_result_count`/
`pending_or_unavailable_count` counts. Owner-ratified Decision 2: this
route has NO privacy-policy dependency at all - authorization is frozen-
historical-Branch scope (mirroring `talent_learner_profile_service`)
exactly, never aggregate cohort-size suppression. An out-of-scope Student
is a non-enumerating 404.

**Branch/Organization Progress** (`GET .../branches/{branch_id}` and
`.../organization`, permission `talent_analytics.view`):
`BranchPeriodResult`/`OrganizationPeriodResult` are the direct mean of
valid governed Student `normalized_percent` results via frozen
`TalentAssessmentCyclePopulationMember.branch_id` attribution;
`OrganizationPeriodResult` is computed directly from every Student in the
authorized scope, never as `average(BranchPeriodResult)` (proven by a
dedicated unequal-Branch-size test: Branch A mean 85.0, Branch B mean
60.0, but the direct Organization mean is 76.67, not the naive 72.5
average-of-averages). Every result is gated by one `Cell`/`Group`
(`_privacy_safe_branch_mean_group`): a contributing-count `Cell` per
Branch plus an org-total `Cell`, `apply_primary_privacy` then
`run_complementary_suppression`; a derived mean is serialized only when
its own count `Cell` is `visible` (never for `suppressed`/`restricted`/
`coarsened`/`no_data`). Overall Results across active Periods use only
the `visible` per-Period means (Pending/suppressed excluded, never zero,
never reconstructable from the combined value).

**Framework comparability** (owner-ratified Decision 1): every
Student/Branch/Organization progress payload carries
`comparability_state`/`comparability_reason_code`; when active Periods
span more than one `framework_version_id`, every Period is still returned
individually but the combined Overall Result is `null`
(`{"state": "no_data", "value": None}` for Branch/Organization) with
`reason_code="framework_changed"`.

**Branch comparison metrics** (`GET .../branch-comparison?metric=...`):
`talent_evaluation_progress_service.branch_comparison_metric` is a bounded
local dispatcher for exactly the seven approved metrics -
`evaluation_period_result`, `current_overall_progress` (both new, above),
`assessment_completion`, `assessments_started` (reusing
`svc.raw_coverage_by_dimension` unchanged), `meets_program_criteria`
(reusing `svc.raw_candidate_by_dimension`, requires
`talent_review_candidates.view` or 403 - query-skipped, not merely
filtered), `officially_confirmed` (reusing
`svc.raw_identification_by_dimension`, requires
`talent_official_identifications.view` or 403), and `learning_style`
(new). This dispatcher does not add to, or modify, the frozen 14-value M10
`MetricCode` enum in `talent_org_intelligence_contract.py`.

**Learning Style Branch aggregate** (ADR 0031/ADR 0042 privacy contract):
arithmetic mean of valid (non-null) `learning_style_{verbal,non_verbal,
quantitative,spatial}_percentage` values in the Program's authorized
population cohort; `null` excluded, `0` is a real included value, no sum
rule, no dominant-style derivation, protected by the identical `Cell`/
`Group` mechanism. A Student frozen into more than one Cycle within the
same Program+Year is de-duplicated to one contribution per Branch context
(`DISTINCT` on `branch_id, student_id, value`) since Learning Style is a
per-Student attribute, not a per-membership fact - unlike the reused M9
`frozen_membership`-grain metrics, which intentionally count once per
Cycle a Student was frozen into.

**Known, disclosed, non-blocking characteristic** (inherited from reused
M9 code, not a new M4 defect): `assessment_completion`/
`assessments_started`/`meets_program_criteria`/`officially_confirmed`
reuse `svc.build_breakdown_group` exactly as `/breakdowns/branch` already
does, which does not convert an all-zero cohort's `total_raw=0` to `None`
- a policy may therefore label a genuinely empty cohort `suppressed`
rather than `no_data` for those four metrics only. No raw value is ever
leaked either way (a suppressed cell's `value` is always `None`); the two
NEW aggregates this milestone adds (Branch/Organization Period Result and
Learning Style) explicitly avoid this by converting a falsy total to
`None` before privacy evaluation.

Second-pass adversarial review (required by this milestone, given its
privacy sensitivity) traced all 16 specified risk categories - suppressed-
Period reconstruction through Overall Result, complementary-suppression
failures, sparse-matrix/cell omission, privacy call ordering, hidden raw
values, numerator/denominator leakage, average-of-Branch-averages,
current-placement vs. frozen attribution, cross-tenant contamination,
Framework-version mixing, Pending-as-zero, null-Learning-Style-as-zero,
privacy-provider fail-open, unauthorized single-Student access, M10
registry modification, and client arithmetic becoming authoritative - and
found the implementation clean; no remediation was required beyond the
Learning Style de-duplication fix made during initial test-writing (fixed
before any review pass, not a post-review defect). See ADR 0044 for the
complete governance record and `tests/test_talent_evaluation_progress.py`
(25 tests: active-period predicate, pure worked-example arithmetic,
Student progress including authorization/tenant isolation, Branch/
Organization Period and Overall Result including the unequal-Branch-size
proof, cross-framework comparability blocking combined Overall while
preserving individual Periods, missing-privacy-provider fail-closed,
primary and complementary suppression, Learning Style null/zero handling
and suppression, and all seven Branch comparison metrics including
permission query-skip) for the full test matrix. Regression: the existing
M9/M10 Talent analytics suites, M2 Student number, and M3 Learning Style
CRUD suites all pass unchanged (three pre-existing, unrelated failures -
one query-count assertion in
`tests/test_talent_organization_student_drill.py` and two in
`tests/test_student_learning_style_v1.py`/
`tests/test_talent_rubric_kpi_candidate_policy.py` - were directly
reconfirmed present and unchanged on unmodified `dev` HEAD `96dd454`
before this task).

## Promo Grant Replacement — "Replace / Extend Promotional Access" (2026-09-21)

Per ADR 0041, a new Platform Console-only workflow implements the
promo-to-promo transfer capability ADR 0020 previously deferred
("Promo renewal, transfer, ... remain deferred"). An operator can now
atomically replace an organization's existing active `PromoGrant` with a
fresh grant redeemed against a different, currently valid `PromoCode` -
for example when Al-Andalus's original 4-branch promo (from a now-revoked
`PromoCode`) is replaced by a new 25 branch / 100 system user / 500 teacher
promo. This is a distinct transition from ADR 0024's promo-to-paid
conversion; the two do not share a code path, though both follow the same
"end old evidence, create new evidence, repoint the tenant link, one
transaction" shape (`_apply_confirmed_promo_conversion` for promo-to-paid,
`saas.promo_redemption_service.replace_promo_grant` for promo-to-promo).

Two new functions in `saas/promo_redemption_service.py`,
`preview_grant_replacement` and `replace_promo_grant`, reuse the existing
`_validate_promo_definition` gate (the same promo-definition validation
`activate_promo` uses - active, approved, within its redemption window, not
itself superseded, scope/redemption-limit rules satisfied) rather than a
second, weaker validation path. `replace_promo_grant` locks the target
`SchoolGroup`, the replacement `PromoCode`, the existing active
`PromoGrant`/`TenantProvisioningLink`/`WorkspaceEntitlement`, and the
organization owner's `SaaSAccountUserLink`, then inside one
`db.begin_nested()` transaction: marks the old grant `status='superseded'`
(retained, never deleted) and its `WorkspaceEntitlement`
`status='ended'`; creates a new `PromoActivationSession`
(`context_type='existing_organization'`, already `status='activated'`),
`PromoRedemption`, and `PromoGrant` against the replacement promo, with
`new_grant.supersedes_grant_id = old_grant.id` (the new row records which
grant it replaced - matching the existing
`PromoCode.supersedes_promo_code_id` convention, where
`promo_code_service.replace_promo` sets the newly created replacement
definition's `supersedes_promo_code_id` to the id of the definition it
replaces); creates a new active `WorkspaceEntitlement` with entitlement
values (plan features, `quota.active_branches`) derived from the new
promo's plan via the existing `_create_entitlement_values` helper, so
capacity/plan evidence is never left pointing at stale numbers; re-assigns
the exact same `PromoGrantBranchAssignment` set the old grant had to the
new grant; and repoints the single `TenantProvisioningLink.promo_grant_id`
from the old grant to the new grant. A final in-transaction check re-runs
`promo_grant_service.resolve_promo_grant` and
`workspace_entitlement_service.resolve_workspace_entitlement` and raises
(rolling back the whole operation) unless both resolve cleanly against the
new grant - mirroring the post-validation check `activate_promo` already
performs. No `Branch`, `User`/staff, or `Teacher` row is created, modified,
or deleted by this operation; only the commercial capacity/plan evidence
(`PromoGrant`, `WorkspaceEntitlement`, `TenantProvisioningLink`,
`PromoGrantBranchAssignment`/`BranchEntitlement`) changes. The existing
`uq_promo_grants_active_group` / `uq_workspace_entitlements_active_group`
partial unique indexes continue to guarantee exactly one active grant and
one active entitlement per organization throughout - no schema or
migration change was required or made.

Authorization reuses the same platform-only `promo_codes.manage` decision
already enforced on every other Platform Console promo-code admin route
(`saas.router._require_promo_permission`), re-checked defensively at the
service layer (matching the existing `promo_code_service.revoke_promo`
service-level check precedent); a non-platform actor or an unauthenticated
request (`actor=None`) is denied before any row is read for update. Two new
`saas/router.py` admin routes back the workflow: `GET
/saas-admin/promo-codes/{promo_uuid}/replace-grant?school_group_id=...`
renders a server-rendered confirmation page
(`templates/saas/admin_promo_grant_replace_confirm.html`, styled
consistently with the existing `admin_promo_code_detail.html`) showing the
old grant's limits against the replacement promo's limits (branches/system
users/teachers, plan, promo reference) before the operator confirms; `POST
/saas-admin/promo-codes/{promo_uuid}/replace-grant` executes the
replacement and redirects with a notice. The existing promo code detail
page gained a new "Replace / Extend Promotional Access" section (visible
only to `promo_codes.manage` holders, only for an effective-active promo)
listing organizations that currently have an active promotional grant,
explicitly separated from the pre-existing "Definition Actions" section
whose own copy already states those actions "do not change tenant access or
commercial authority" - this new section does.

Tests: `tests/test_promo_redemption.py::PromoGrantReplacementTests` (service
layer - end-to-end replacement, exact-record branch/user/teacher
preservation, old grant becomes `superseded`, new grant is `active`, only
one active grant per organization, capacity display reflects the new
grant's limits via `commercial_authority_service.resolve_commercial_authority`,
denial for a non-platform/unauthenticated actor, denial for a
revoked/invalid replacement promo leaving all existing rows untouched, and
rollback on a forced mid-transaction failure) and
`tests/test_promo_code_management.py::PromoGrantReplacementRouteTests`
(route-level - the confirmation page renders old-vs-new limits, the execute
route applies the replacement, and a non-platform actor is denied with
403). ADR 0020's "promo renewal, transfer... remain deferred" consequence
is corrected: promo-to-promo transfer is no longer deferred; promo renewal
and automated-expiry-job transfer remain deferred, unchanged. No `tis.db`
change; this task did not touch any pre-existing promo/commercial code path
beyond the two new service functions and two new routes/templates.

## Talent & Potential Sidebar Icon (UI Polish, 2026-09-19)

The Talent & Potential sidebar entry now renders the shared inline-SVG `sparkles`
icon through the existing `icon()` macro (`templates/_app_icons.html`: 24x24
viewBox, stroke-only, styled by `.shell-icon`), consistent with every other module.
The nav item already declared `"icon": "sparkles"` (also used by the Talent page
header); only the `"brand_logo": "img/talent-ghars-symbol.png"` override in
`ui_shell.py` was removed, so the sidebar no longer draws an `<img>` for this
item. Routing, permissions (`permission_keys` / `permission_mode: any`), label,
child tree and all other icons are unchanged; no new icon, asset, dependency, or
schema. The generic `brand_logo` support in `templates/base.html` and the
`.sidebar-brand-symbol` CSS remain available but are unused, and
`static/img/talent-ghars-symbol.png` stays in the repository unreferenced by the
sidebar. Earlier entries below that describe the Ghars PNG in the sidebar are
historical. `tests/talent_results_experience.test.cjs` now asserts the Talent item
uses the shared icon macro instead of the PNG.

## Whole-Application Permission Qualification (Phase 3)

Phase 3 qualified the whole application against the single canonical effective
permission result (`auth.get_allowed_permission_keys`; ADR 0040 precedence
unchanged, no second resolver, no schema/migration, no new key). Final registry
classification of the 175 keys (26 groups): 143 active-enforced, 14 platform-only
enforced, 5 alias/composite, 13 dormant/reserved, 0 unresolved. The prior note that
`planning.import`/`planning.export` had consumers was stale, and
`observations.submit` and `dashboard.view_all_schools` have no enforcement, so all
three are now dormant (13 dormant total). The route table (468 routes, 253 non-GET)
is machine-enumerated: 136 middleware rules, 182 in-handler guards, 10 helper
guards, 34 platform-identity, 65 SaaS-account-session and 41 reviewed allowlist
entries, none uncovered. One real defect was fixed: `POST /scope/organization`
accepted any platform user without the `system_owner.switch_all_schools` /
`schools.manage_all_schools` capability its own denial cited; it now also requires
the canonical `_can_manage_all_school_scopes` helper. Seven unused duplicate raw
`_get_role_permission_rows` / `_get_allowed_permission_keys` helpers were deleted.
Sidebar, Dashboard tab/panel and direct-route consistency is parametrized over every
nav module (including the multi-key Talent and System Configuration gates and the
Talent sub-nav); Allow/Deny/Allow freshness for Role Package, School Override and
User Exception, role change with retained exceptions, tenant isolation and
platform-only protection are covered on fresh sessions. Four Owner/product
decisions remain open and unresolved (teacher-create field-level enforcement,
tenant-toggleable dormant keys, whether role User may author observations, orphan
`UserPermissionOverride` rows on workspace deletion); ADR 0040 remains authoritative
for precedence and its historical helper names are addressed in
`docs/engineering/PERMISSION_CLOSURE_REVIEW.md`. Tests:
`test_permission_registry_matrix.py`, `test_permission_route_coverage.py`,
`test_permission_dangerous_patterns.py`, `test_permission_surface_consistency.py`,
`test_permission_surfaces_accessibility.py`.

## Role Permissions UI — User Exceptions (Phase 2)

Phase 2 replaces the old edit-user "Per-User Permission Overrides" panel
(three-way Inherit / Allow / Deny radios plus one bulk save) with a
"User Permission Exceptions" section on the same edit-user page. Presentation
only: storage, the three-state `user_permission_service` semantics, and the
ADR 0040 precedence (built-in role package -> global `RolePermission` ->
SchoolGroup `RolePermission` -> per-user override -> effective; user Deny
wins; a user Allow can never resurrect a role-level Deny) are unchanged. No
schema, migration, new permission key, or second resolver.

- **Binary UI, hidden inherit.** The normal UI offers only Allow and Deny.
  "Inherit" no longer appears anywhere. An absent override row still means
  "follow role settings", and `apply_user_override(..., "inherit")` remains
  the deletion primitive, now surfaced as the **Reset to Role Settings**
  button, shown only when a direct exception exists. Normal UX is Allow / Deny
  plus Reset to Role Settings; "inherit" remains only the internal,
  backward-compatible API representation of clearing a per-user override (the
  legacy paired `permission_keys` / `permission_decisions` route contract is
  unchanged and is never exposed in the UI).
- **User summary.** The section opens with name, login, effective role,
  School, Branch, and status, built server-side in
  `routers/users.py::_build_user_permission_context`. An inactive account
  shows a notice; effective results come from
  `auth.get_allowed_permission_keys`, which fails closed for inactive users
  and mismatched scope.
- **Per-permission row.** Effective Allow/Deny, Source (User Exception /
  School Override / Standard Role Package), and User Exception (Allow / Deny /
  None - descriptive only). Rows sit in native `<details>` groups (no manual
  `aria-expanded`); groups with an exception open by default with an
  "N exceptions" count. The button matching a stored exception carries
  server-rendered `aria-pressed="true"` and a check-mark cue. Platform-only
  keys render locked with no buttons. A key that is not assignable to the
  user's current role renders locked with no Allow or Deny button; if a stored
  exception already exists on it (for example after a role change made the key
  non-assignable) the row shows only **Reset to Role Settings**, because Reset
  deletes an existing exception and cannot grant authority. Stale exceptions
  are never deleted silently, and creating or changing an exception on a
  locked key remains refused server-side.
- **Inert Allow.** A stored user Allow while the role layer denies shows
  Effective Deny, "Allow (stored, currently ineffective)", and an explanation
  that it cannot override the role denial and applies again if the role
  re-grants. It is never displayed as final Allow and never silently
  deleted; Reset is available.
- **Source projection.** `user_permission_service.build_user_permission_payload`
  (read-only, composes `role_permission_service` and `auth` helpers) gained
  additive fields `standard_allowed`, `school_override`, `exception`,
  `exception_inert`, `has_exception`, `source`, `blocked_by_account`;
  `effective` equals `auth.get_allowed_permission_keys` (tested for
  `subjects.view` and `teachers.view`).
- **Route.** `POST /users/permissions/{user_pk}` stays the single route with
  one guard block (tenant/platform scope resolution unchanged). New optional
  form field `change="<permission_key>|<allow|deny|reset>"` applies exactly one
  change (reset -> `inherit`); malformed values are rejected with no write.
  Without `change` the legacy paired `permission_keys` / `permission_decisions`
  contract is unchanged. Each action button targets `#perm-<key>` so the page
  returns to the edited row.
- **Tests.** `tests/test_user_exceptions_ui.py` (cases for every source /
  inert / reset / role-change / tenant / platform-only / inactive / freshness
  scenario plus template accessibility assertions). One obsolete assertion set
  in `tests/test_edit_user_template_render.py` that encoded the removed
  Inherit radios was rewritten for the new markup.

## Role Permissions UI — Role Packages / School Overrides Split (Phase 1)

A live Owner reproduction proved a real incident on the prior combined Role
Permissions editor: for a real tenant, Administrator -> subjects.view
appeared Allow while "Global defaults" was selected in the single
"Permission Scope: Global defaults / Selected school" dropdown, while that
same tenant's actual Administrator effective permission was Deny (built-in
default = Allow, global `RolePermission` override = none, tenant
`RolePermission` override = Deny, per-user override = Inherit, final
effective = Deny per ADR 0040's precedence). The Platform Owner UI
simultaneously showed the tenant's name even while "Global defaults" was
selected, creating the visual impression the Platform Owner belonged to that
tenant. Root cause was purely presentation/IA: one screen mixed the global
default layer, the tenant override layer, and Platform Owner context behind
one ambiguous dropdown, even though `role_permission_service.py`'s resolver
(built-in -> global `RolePermission` -> tenant `RolePermission`, unchanged by
this pass) was already correct.

`/system-configuration/role-permissions` (GET/POST, unchanged path) now
serves two explicit modes selected by `?mode=packages` (default) and
`?mode=overrides`, both still backed by the same
`role_permission_service.py` resolver/writer - no second resolver was
created. **Role Packages** (`mode=packages`) edits only the standard/global
role layer: no SchoolGroup selector, no tenant name, and no Platform Owner
tenant context appear anywhere on it; editing is restricted to actors holding
`system_owner.manage_global_role_permissions` (Platform Owner today), and a
tenant actor sees the same standard package read-only. **School Overrides**
(`mode=overrides`) is the only place a SchoolGroup appears, always labeled as
an explicit management target ("Managing School: <name> ... management
target only, not your own account context"), never as if the Platform Owner
belongs to that school; a Platform Owner must explicitly choose which
SchoolGroup to manage (no school is ever pre-selected on their behalf: with
none chosen the page shows a prompt and no editable form, and the choice is
submitted with an explicit "Review this school's overrides" button rather
than auto-submitting on change), while a tenant actor is silently locked to their own authorized SchoolGroup
even if a foreign `school_group_id` is supplied in the query string or POST
body (POST additionally hard-rejects a foreign `school_group_id` with a
redirect, matching the pre-existing cross-tenant boundary). Per permission,
School Overrides shows Standard Role Package value, this school's own
override (or "Using Standard Role Package" when none exists), and the
Effective value, via a new read-only `role_permission_service.
build_school_override_payload`. A "Reset to standard" control is UI-only: it
sets the checkbox back to the Standard Role Package value before Save, which
the pre-existing `apply_role_permission_overrides` diff-against-baseline
write path already turns into a clean row delete (no new backend removal
semantics were invented). Viewing School Overrides never writes a tenant
`RolePermission` row (no side effect on GET). So a real override is legible at
a glance, School Overrides states how many School overrides the selected role
has ("No School-specific override. Using Standard Role Package." when none),
opens by default only the permission groups that contain an override, and
tells the editor that "Reset to standard" still requires "Save School
Overrides". School Overrides deliberately has no "Select All" / "Clear All"
(Role Packages keeps them): a School override must stay a sparse, intentional
difference from the Standard Role Package, because bulk select/clear would
write a large explicit tenant policy and make later Standard Role Package
changes ineffective for that school; per-permission "Reset to standard" is
the only reset in Phase 1 (no bulk "Reset All"). Accessibility
(template-source and real-browser verified, no
automation framework exists in this repo): the Role Packages / School
Overrides links are page-navigation links marked `aria-current="page"` (not
`role="tab"`, which would promise unimplemented arrow-key tab behavior);
permission groups rely on native `<details>`/`<summary>` semantics with no
manual `aria-expanded` (which would drift from the real open/closed state);
each School Override row keeps its checkbox label separate from the "Reset to
standard" button (a button nested in a `<label>` is invalid and pollutes the
checkbox's accessible name); banner text is a single element so it wraps as
one sentence; and links, buttons, summaries, the school selector and
checkboxes have an explicit `:focus-visible` outline.

Platform Owner context is unchanged and re-verified: `School`, `Branch`, and
`Academic Year` remain unassigned/`None` for a Platform Owner
(`auth.get_user_school_group_id` already returns `None` unconditionally for
any platform user), and selecting a SchoolGroup as a School Overrides
management target does not write to the Platform Owner's own user row,
session, or `scope_school_group_id`. This is Phase 1 structural correction
only - User Exceptions (per-user overrides) redesign, the full cross-module
permission-consumer audit, and the accessibility qualification matrix are
explicitly deferred to later phases. No schema, migration, permission key,
or precedence-rule change; `tis.db` is unmodified (hash verified unchanged).
See `tests/test_role_permissions_ui_split.py` and the updated
`tests/test_permission_management.py` (its `_update` helper's `scope_type`
parameter is renamed `mode`, matching the route's new form field) for the
complete regression matrix, including a constructed Al-Andalus-style fixture
proving the exact incident scenario, tenant-isolation, and the Platform
Owner identity-preservation proof.

## Dashboard Tab/Panel Permission-Gate Closure (Live Owner Reproduction)

A live Owner reproduction found a real tenant Al-Andalus Administrator whose
Subjects sidebar item was correctly hidden and whose direct `/subjects` route
was correctly denied, while the same current user's Dashboard still showed
the Subjects tab and Subjects Workspace panel. Both the sidebar
(`ui_shell.build_shell_context`/`_build_nav_items`) and the route guard
(`authorization.enforce_route_permission`) already resolved through the
canonical `auth.get_allowed_permission_keys` chain (built-in role default ->
global `RolePermission` -> tenant `RolePermission` -> per-user
`UserPermissionOverride`) and were already correct and consistent with each
other. The defect was isolated to `templates/dashboard.html`: its Subjects,
Teachers, and Planning tab buttons and panels rendered unconditionally, never
calling the `can(...)` helper that `main.dashboard`'s own
`build_shell_context()` call already makes available in the same template
(only the pre-existing Reports tab called `can("dashboard.view_reports")`).

The fix wraps each of the three tab buttons and their matching panel `<div>`s
in `can("subjects.view")`/`can("teachers.view")`/`can("planning.view")`, and
replaces the previously hardcoded "Subjects is always the active default tab"
markup with a computed `dash_first_tab` that becomes the first
permission-visible tab (Subjects, then Teachers, then Planning, then
Reports), so a user who only holds `teachers.view` (used here as the second,
non-Subjects sentinel proving this is a generic gating fix, not a
Subjects-only special case) still gets a valid default-active panel instead
of a blank workspace. No precedence rule, permission key, schema, or
migration changed; `auth.py`, `authorization.py`, `role_permission_service.py`,
`user_permission_service.py`, and `ui_shell.py` were inspected and confirmed
already canonical and were not modified.

Phase-1 read-only diagnosis of the tracked local `tis.db` found it predates
this feature area entirely: it has no `user_permission_overrides` table and
its `schema_migrations` ledger ends at `20260822_...`, well before
`20260913_001_user_permission_overrides` and
`20260915_001_role_permission_logical_key_uniqueness`; it also has no tenant
Administrator user matching the reproduced Al-Andalus scenario (only a single
platform `developer` identity is present). Diagnosis and regression coverage
are therefore code/template-level, not live-row inspection of that file; this
is recorded rather than worked around. `tis.db` was not modified (hash
verified unchanged before and after this task) and was not migrated.

New regression coverage in
`tests/test_dashboard_sidebar_permission_consistency.py` proves, for the same
current user across the same request, that sidebar visibility, Dashboard
tab/panel presence, and the direct route guard all agree with the canonical
resolver's effective permission for six cases (global Allow only; global
Allow + tenant Deny; tenant Allow + per-user Deny; role Deny then re-grant
with per-user Inherit restoring access; role Deny then re-grant with a
persisted per-user Deny remaining in effect per ADR 0040's Deny-over-Allow
rule; and tenant-isolation, where denying one SchoolGroup's Administrator
does not affect another SchoolGroup's Administrator holding the same role),
each parametrized over both `subjects.view` and `teachers.view`.

## PR #360 Review-Response Corrective Pass

Two review findings on PR #360 were verified against the actual GitHub review
comments/diff and corrected. `hiring_plan.export` previously gated only the
literal `section=hiring` export request; `section=full` returns a report
containing the same hiring-plan data (both professional-report builders emit
the hiring-plan sheet/section for `full`) and was not gated, letting a caller
retain the protected data despite a denied `hiring_plan.export`. The gate in
`main._authorize_report_export` now covers every section whose payload
includes hiring data. Separately, this branch's `.kms-impact.yml` had come to
understate its own database impact: it claimed no migrations/schema changes
even though the branch still carries the non-destructive migration
`20260915_001_role_permission_logical_key_uniqueness` (see below); the
declaration is corrected to describe the branch's full cumulative scope. A
third item from the delegated task summary (SchoolGroup edit/delete/action
authorization) was investigated and found to have no corresponding PR #360
review comment and no SchoolGroup file in this PR's diff against
`origin/dev`; no code change was made for it. Full detail in
[the closure review](engineering/PERMISSION_CLOSURE_REVIEW.md#pr-360-review-response-corrective-pass).

## 22-Key Permission Registry Closure

All 22 permission keys left unclassified by the independent review below have
been individually traced against the implemented product and resolved: nine
now have dedicated server-side enforcement aligned with their UI
(`dashboard.view_branch_summary`, `dashboard.view_reports`,
`dashboard.export_reports`, `hiring_plan.export`, `observations.view_reports`,
`observations.sign_evaluator`, `configuration.view_audit_log`), three are
explicit, documented aliases of an already-enforced capability rather than a
second independently-built gate (`observations.submit`,
`system_owner.manage_developer_accounts`,
`system_owner.view_cross_school_audit` /
`system_owner.export_cross_school_data`), nine are classified dormant/reserved
because no implementation exists and no UI implies otherwise (`reports.view`,
`teachers.import`, `teachers.export`, `subjects.manage_colors`,
`observations.manage_templates`, `configuration.manage_global_defaults`,
`system_owner.manage_subscriptions`, `system_owner.create_subscription_school`,
`system_owner.run_startup_repairs`), and one genuine registry/implementation
conflict was resolved fail-closed (`configuration.view_audit_log` moved to
platform-only rather than exposing the global, non-tenant-filtered audit log
to tenant administrators). Full per-key reasoning is in
[the closure review](engineering/PERMISSION_CLOSURE_REVIEW.md). This 22-key
closure pass itself introduced no new permission keys, migrations, or schema
changes; ADR 0040 is unchanged. (The branch/PR as a whole still carries the
earlier `20260915_001_role_permission_logical_key_uniqueness` migration
described below and in the PR #360 corrective-pass note above.)

## Independent Permission Closure Review — Not Yet Whole-System Approval

Independent review of the permission-closure branch found additional bypasses:
notification detail auto-marked messages read despite a dedicated Deny;
inactive platform identities retained helper capabilities; platform Developer
role choices bypassed `users.assign_role`; teacher bulk deletion used the
single-delete key; and teacher/planning edit forms could mutate protected
fields under broader edit grants. Corrective guards now use canonical effective
permissions, reject unauthorized field changes, preserve omitted read-only
values, and project the dedicated capabilities to their forms.
The canonical tenant resolver also fails closed for absent/contradictory
ownership or foreign selected/explicit permission evaluation scope.

The ten-family ON/OFF/ON evidence covers fresh persisted resolver reads,
route-guard calls, and navigation projections, not complete authenticated HTTP
round trips. The role-policy migration was independently exercised on disposable
PostgreSQL as well as SQLite. Whole-system approval remains blocked pending
classification/enforcement of unconsumed registry keys and the coverage gaps
recorded in [the independent review](engineering/PERMISSION_CLOSURE_REVIEW.md).
No permission data cleanup, merge, or deployment is authorized by this review.

## Permission Consistency Closure (Whole-Registry Pass)

A reported `subjects.view` grant/revoke/re-grant regression was investigated
and fixed as a whole permission-system defect rather than a Subjects-only
issue. Root cause: `auth.get_allowed_permission_keys` (the canonical
current-user effective-permission resolver) and several helper functions
(`can_manage_system_settings`, `can_manage_users`, `can_modify_data`,
`can_edit_data`, `can_delete_data`, `can_edit_user_accounts`,
`can_delete_user_accounts`, `can_manage_target_user_account`) used
request-independent caching (`user._permission_cache` and the now-removed
`_has_cached_permission`/`_has_any_cached_permission`/
`_has_cached_permission_prefix`/`get_user_permission_keys` helpers), so a
role-permission toggle could remain stale on a retained user instance.
Independent review does not establish historical production HTTP instance
reuse. The attached result cache is removed (the shell still uses a canonical
per-render snapshot); every one of those helpers now takes an
explicit `db: Session` and resolves fresh through
`has_permission`/`has_any_permission`/`get_allowed_permission_keys` on every
call, matching ADR 0040's precedence chain (built-in role default -> global
`RolePermission` override -> tenant `RolePermission` override -> per-user
`UserPermissionOverride` -> effective permission, Deny-over-Allow).
`can_manage_target_user_account` additionally now fails closed on an
ambiguous (falsy) SchoolGroup comparison instead of defaulting to allow.

Beyond the caching root cause, the full-registry audit found and fixed
several independent stale/incorrect permission paths: `routers/users.py`'s
role-creation and permission-management helpers; `routers/observations.py`'s
create/edit/delete/unlock checks, plus a distinct sibling defect where
holding only `observations.create_formal` or only
`observations.create_non_formal` allowed creating *either* observation type
(fixed with a new per-type `_can_create_observation_type` check reflected in
`templates/observation_form.html`'s Type options); `main.py`'s System
Configuration Qualifications create/update/delete routes, which were gated
by entirely wrong permission keys (`branches.delete`,
`academic_years.activate`, `academic_years.create`) instead of
`configuration.manage_degrees`/`configuration.manage_specializations`;
`update_branch`/`delete_branch` accepting a field change not covered by the
caller's specific `branches.edit`/`branches.activate_deactivate` grant, plus
missing SchoolGroup-scope boundary checks on `delete_branch`,
`set_current_year`, and `open_new_academic_year` (the last of which now
correctly requires both `academic_years.create` AND
`academic_years.activate` rather than the coarse role-prefix
`can_manage_system_settings` check); and notification mark-read/resolve/archive
plus Branch/SchoolGroup logo upload/reset routes, which previously enforced
no dedicated permission at all server-side beyond generic access, now
gated by `notifications.mark_read`/`notifications.resolve`/
`notifications.archive` and `branding.manage_school_logos`/
`branding.manage_branch_logos` respectively, matching (and, for
notifications, adding) the UI-side gates.

Persisted-data integrity: `role_permissions` gained two partial unique
indexes (`uq_role_permissions_global_role_key` for a NULL SchoolGroup scope,
`uq_role_permissions_tenant_role_key` for a tenant scope) via
non-destructive migration `20260915_001_role_permission_logical_key_uniqueness`,
which fails closed with no schema change if a pre-existing duplicate
scope/role/key row is found (no row is ever deleted or rewritten by this
migration). `user_permission_service.apply_user_override` now re-validates
that a permission key is actually assignable to the target user's own
effective role before writing an Allow/Deny (closing a path that could
create an override for an otherwise nonassignable key; platform-only keys
were already rejected), and
`build_user_permission_payload`'s effective-permission projection now
calls the same canonical `auth.get_allowed_permission_keys` resolver instead
of a locally re-implemented merge.

Regression coverage proves ON -> OFF -> ON for `dashboard.view`,
`subjects.view`, `teachers.view`, `students.view`, `planning.view`,
`timetable.view`, `calendar.view`, `observations.view`, `users.view`, and
`configuration.view` against the resolver, direct route/API enforcement,
and navigation visibility, each re-read fresh (no cross-request state), in
`tests/test_permission_qualification.py`; plus new
`tests/test_branch_year_permission_boundaries.py` (mixed-action Branch/
Academic-Year scope), `tests/test_configuration_scope_permissions.py`
(logo/qualification scope-specific gating), `tests/test_notification_group_permissions.py`,
and `tests/test_role_permission_logical_key_migration.py` (migration
duplicate-preflight and idempotency). No Allow-over-Deny behavior exists;
that remains an explicitly deferred, separately-governed decision
(ADR 0040). No new permission key, schema-breaking change, or `tis.db`
change. See `docs/CHANGE_HISTORY.md`'s 2026-09-17 entry for the complete
file-level detail.

## Permission Qualification Drift Closure

The cross-module audit additionally closed three UI/backend mismatches. Edit User
now rechecks profile, position, role, branch/scope, active-status, and password
changes against their exact granular permissions instead of treating any one as
authority for all fields. Single-user and bulk-user delete controls now follow
their respective backend keys. Talent now projects the dedicated Competency and
Rubric-Level delete permissions to the browser, matching the existing API guards.

## Per-User Permission Override — Platform-Actor Scope Fix And Governance Closure

The per-user permission override follow-up, now integrated into `dev`, closed the
remaining platform-actor scope edge case in the already-implemented per-user
permission override layer (`UserPermissionOverride`,
`user_permission_service.py`, the Edit User page panel, and
`POST /users/permissions/{user_pk}`): a platform-level actor
(owner/developer) has no resolvable tenant `school_group_id` of their own,
and `routers/users.py`'s `update_user_permissions` previously either
hard-errored or, when the platform actor's own session happened to have
some unrelated selected branch/SchoolGroup scope, spuriously rejected an
otherwise fully authorized cross-tenant write. The route now derives the
override's `school_group_id` from the already server-loaded target user's
own verified `school_group_id` whenever the acting admin is a platform
user, mirroring `_build_user_permission_context`'s existing identical
read-side resolution; no client-supplied scope, new permission key, or new
UI control was added. See ADR 0040 for the full decision record (this also
formally documents the previously-recorded-but-not-yet-ADR'd precedence
chain, Deny-over-Allow rule, and uniqueness justification).

Added regression coverage: three new route-level tests in
`tests/test_user_permission_override_routes.py` (platform actor with no
own tenant scope; scope correctly tracks each of two different targets in
two different SchoolGroups rather than any shared/actor-controlled value;
the service layer itself rejects a mismatched `school_group_id` even when
called directly) and a new rendered-HTML integration test,
`tests/test_edit_user_template_render.py`, proving the Edit User page's
override panel actually renders all three Inherit/Allow/Deny controls, the
inherited-grant and Deny-override reason-text branches, and the exact
inert markup for a platform-only permission key. Full permission/security
regression (`tests/test_user_permission_overrides.py`,
`tests/test_user_permission_override_routes.py`,
`tests/test_permission_management.py`,
`tests/test_permission_qualification.py`, `tests/test_platform_access.py`,
plus the two new files) passes. No schema migration, new permission key, or
`tis.db` change.

## Role Permission Management Reassessment And Repair

Role-permission management was reassessed end-to-end and repaired. The reported
checkbox defect was not a persistence failure (grant/revoke/re-grant round-trips
were confirmed correct at the route, service, and render layers) but a
direct-vs-effective conflation: the editor bound a single checkbox to the merged
effective permission (defaults + global + tenant) with no inheritance indication.
`role_permission_service.py` is now the canonical resolver (both the Role
Permissions UI and `auth.py` delegate to it); payloads expose
`direct`/`inherited`/`source`; the editor labels inherited grants; and owner-only
controls are locked out of the tenant editable model and Administrator defaults.
The administrator Save path persists only intentional scope-level overrides
(`apply_role_permission_overrides`), so a no-op Save no longer converts
inherited/default/global grants into direct rows and default/global changes
propagate to roles without an explicit override.
Comprehensive regression tests were added (`tests/test_permission_management.py`).
No schema migration and no `tis.db` change.


## Talent Student Assessments — Program Annual-Configuration Enablement Removed As A Gate

Per direct Owner instruction, a further same-day correction on top of the
Grade-gate fix (below): `TalentProgramAcademicYearConfiguration.is_enabled`
(and the configuration row's existence at all) is no longer required by the
normal Student Assessments roster (`current_placements_for_assessment`) or
Start Assessment (`_current_placement_for_assessment`) path. See
`docs/adr/0039-talent-competency-kpi-level-simplification.md`'s "Further
Owner correction" section. The Evaluation/Cycle already supplies the
Academic Year; a Student's valid current Placement in that exact Academic
Year is sufficient. Kept unchanged: School Group isolation, Branch
authorization, Academic Year match, current Student Placement, the saved
Competency+KPI+Level requirement, and immutable historical evidence
protection. `derive_eligible_population` (legacy M4/frozen-population path)
is unchanged and still requires an enabled configuration for its own
callers. New regression proves: a Program with Competency+KPI+Level saved
and no annual configuration row at all (and, separately, an explicitly
disabled one) still shows the Student in the roster and allows Start
Assessment. No schema migration required. Zero new test regressions
(confirmed by direct before/after comparison); the same three pre-existing
failures already present before this pass remain unaffected.

## Talent Competency -> KPI -> Level Simplification — Owner Correction: Grade Removed From Configuration Gates Too

Per direct Owner instruction, a same-day corrective pass on top of the
initial ADR 0039 implementation (below) found and fixed three remaining
places Grade still acted as a gate rather than context, contradicting the
Owner's governing rule ("Competency+KPI+Level+Save=Ready; Grade must not be
a readiness gate, Student-list gate, or Start Assessment gate"). See
`docs/adr/0039-talent-competency-kpi-level-simplification.md`'s "Owner
correction" section for the exact prior/corrected behavior. Summary:
`talent_student_assessment_service._current_placement_for_assessment`
(renamed from `_current_eligible_placement`) no longer filters a Student's
Placement by the Program's `eligible_grade_levels` - only tenant scope, the
Program's Academic Year enablement, and a genuinely current effective
Placement are required. The Student Assessments list
(`GET /api/talent/assessment-cycles/{id}/eligible-students`) now calls a
new `current_placements_for_assessment` (in `talent_assessment_cycle_service.py`)
instead of `derive_eligible_population`, returning every current, validly
placed Student in the authorized tenant/Branch/Academic-Year scope with no
Grade filter; `derive_eligible_population` itself is unchanged and remains
Grade-filtered for its own legacy/frozen-population callers (Cycle
open/preview/ADR 0033 reconciliation), which are historical population
mechanics distinct from the normal live Student Assessments roster.
`static/js/talent-program-workspace.js`'s readiness (`setupComplete`) no
longer includes `basicsComplete` (Program/Academic-Year eligible-Grade
configuration) in its gate - Ready is exactly the assessment build itself
(Competency+KPI+Level, saved); Grade configuration remains available for
context but never blocks Ready. No schema migration was required. Zero new
test regressions were introduced (confirmed by direct before/after
comparison, matching this session's established practice); three
pre-existing failures in `tests/test_talent_assessment_cycle_frozen_population.py`
(already present on the pushed commit this corrects, unrelated to Grade
gating) were confirmed present both before and after this pass and are not
newly introduced.

## Talent Competency -> KPI -> Level Simplification — Implemented

ADR 0039 (see below) is now implemented, not only recorded. Start Assessment
no longer fails when the Student's specific Grade has no separately-authored
Competency: `_newest_assessable_framework` prefers Grade-specific content
but falls back to the Program's full saved build, and the Assessment
editor's own client-side Competency filter carries the identical fallback
so an assessment the backend now allows never renders empty. Program
readiness in the setup workspace is exactly Competency+KPI+Level, saved,
stated as the single missing requirement in plain language when incomplete;
Finish Setup/Framework activation remains available but is no longer
required for or tied to the Ready banner. "Rubric"/"Assessment Criteria" is
relabeled "KPI" in the Competency build/summary UI; the separate numeric
`TalentKpiConfiguration` feature was left untouched, so a real
two-things-called-"KPI" UI collision now exists and needs a follow-up Owner
naming decision (not resolved by this pass). The KPI/rubric `name` field is
now optional and auto-derived from the owning Competency when omitted.
Delete Competency removes its KPI, Levels, and achievement Descriptors as
one subtree action; it still blocks with an exact reason on numeric-KPI
weighting or Program Criteria rules referencing the Competency, since those
remain separate governed structures this pass does not authorize deleting
as a side effect. The Talent & Potential sidebar Ghars logo no longer
suppresses the visible module text and renders at the same size as sibling
navigation icons; the existing SVG asset was confirmed to have no safely
extractable icon-only symbol (one dense unlabeled wordmark path), so a true
hand-extracted mark remains a follow-up design task. "Students" is now the
first child of the Talent & Potential nav tree, gated by the existing
`students.view` permission; the separate top-level Students item is
unchanged. No schema migration was required. Zero test regressions were
introduced, confirmed by direct before/after comparison across the full
Talent Python and Node suites.

## Talent Competency -> KPI -> Level Simplification — Governance Decision Recorded

Per direct Owner instruction on 2026-09-12, see
`docs/adr/0039-talent-competency-kpi-level-simplification.md`. Two policy
changes are now approved: (1) Grade is no longer a Start Assessment
eligibility gate - a Student is assessable once the Program's saved build
has at least one Competency with one KPI/criterion and one Level, regardless
of whether that content was authored under the Student's specific Grade;
Grade remains display/historical context only, per an amendment to ADR 0035
condition 4 (the rest of ADR 0035 is unchanged). (2) The user-facing
authoring/assessment hierarchy is relabeled Competency -> KPI -> Level
("Assessment Criteria" retired as normal-user-facing text); internal
schema/API names may remain unchanged. This explicitly does NOT resolve
whether the separate, pre-existing numeric `TalentKpiConfiguration` feature
needs its own rename to avoid a two-different-things-called-"KPI" collision
- that is flagged as a distinct follow-up decision, not silently resolved.
Program readiness becomes Competency+KPI+Level+Save=Ready with no separate
Finish-Setup/Activate step in the normal flow; Competency delete becomes a
single subtree action (removes its KPI/Levels from the current/future build)
while historical completed Assessment evidence remains immutable. This entry
and the referenced ADR are the authorization record, not a completion
record; implementation is tracked separately.

## Owner Video Acceptance — Immediate Corrective Pass

The latest Owner video/document acceptance pass is implemented on `dev`.
Configured Programs nested under an Evaluation Period are selectable directly
from Student Assessments even before a physical Cycle exists. The authorized
selection reuses the canonical Cycle-create + Period-link contracts and returns
to the same Student Assessments surface with the selected Program roster.
Start Assessment retains the selected Evaluation/Program context and opens the
returned Assessment, whose UI reads that Assessment's exact Program Framework,
Grade-applicable Competencies, competency-owned criteria, Levels, and
descriptions. Action failures now render as visible alerts instead of an
apparently inert click.

Delete Competency is available on immutable Program setup only as a safe
versioned operation: TIS clones a new editable Framework Version, removes the
Competency from that new version, and leaves all historical Assessment evidence
on the old Framework untouched. The KPI disclosure now has a visible collapse
affordance.

The Students list uses icon-only Add/Delete/Open actions with accessible names.
A new `students.view_all_branches` permission controls the cross-Branch
selector and **All branches** option; managed-role constraint keeps it
Administrator-only and it still requires organization/global scope. Without it, the Students list is fixed to
the actor's assigned authorized Branch. Learning Style aggregate privacy is
unchanged: a missing governed privacy provider now produces a clear
"statistics unavailable" panel instead of hiding the whole section, with no
counts/percentages/bars leaked; privacy-suppressed cohorts stay suppressed.
**Superseded 2026-09-24 (Acceptance C):** the Learning Style distribution no longer
depends on the privacy provider and is never suppressed; see the Acceptance C
section at the top of this document.

## Talent Urgent UX And Recovery Adjustment Batch

The Owner-approved urgent adjustment batch is implemented on `dev` with no
schema migration. Talent's sidebar tree is now the only primary module
navigation; the duplicate in-page module ribbon is removed. Program setup
projects readiness on the Program summary and no longer owns a separate Ready
step. A positive **Ready** state is shown only when eligible Grades, assessment
criteria, and Evaluation Period configuration are complete. Competency
authoring uses one selected Grade at a time, defaulting to the first configured
Grade, while dedicated delete permissions continue to govern Competency/Level
destructive actions.

A new Administrator-default permission
`talent_assessments.reset_for_reassessment` provides safe operational
recovery for a current completed Assessment. Reset marks the prior completed
attempt non-current and writes an audit event while preserving every dependent
evidence/history row. The Student therefore returns to Not started in the same
visible Evaluation and may start a fresh current Assessment. This is not ADR
0034 hard-delete; completed evidence is never physically deleted by this path.

Student Assessments now emphasizes the selected Evaluation Period and selected
Program, and Start Assessment carries the selected Cycle/Program into the
opened assessment workspace so the Program's exact competencies and persisted
assessment criteria load immediately. Talent Review accepts authorized
Branch/Grade/Section filters and no longer presents "Meets criteria" as a
primary user classification; deterministic Candidate policy remains internal
and Official Identification remains distinct. Analytics error surfaces now
reuse the backend's specific governed reason where available.

Program setup uses the neutral user-facing phrase **Assessment Criteria** for
the competency-owned rubric structure. The separate real numeric feature is
shown explicitly as **Key Performance Indicator (KPI)** with Add/Edit/Delete
controls. Internal rubric persistence/API terminology is unchanged.

## Talent Assessment Eligibility — Owner Simplification

Per direct Product Owner correction on 2026-09-11, Talent Student Assessment
eligibility now follows ADR 0035. Current effective Academic Placement plus the
Program's configured eligible Grades and usable assessment framework/tool are
the operational authority. Draft/Open Cycle state, frozen population,
synchronization, reconciliation, and persisted population membership are no
longer user-facing prerequisites to start an Assessment. Existing Cycle and
Population Member rows may remain as compatibility/historical provenance
structures. Assessment creation captures the Student's placement/framework
context at the time the Assessment starts. ADR 0033 is superseded as an
eligibility/workflow model.



## Talent Program Finalization, Evaluation Grouping, And Re-evaluation Reset Correction

Per Owner acceptance on 2026-09-11, a fully configured Draft Program no longer remains Draft after the user completes setup. **Finish Setup** is the governed lifecycle boundary: with organization/global authority and `talent_programs.govern`, the UI activates the Program first and then the completed Draft Framework using its current revision and semantic fingerprint, after which the same Program opens in operational summary mode. Already-active state is not activated again.

The Program operational summary's Edit Program, Build/Edit Rubric, and Manage Evaluation Plan links now participate in the same hash-backed renderer before the summary's early return, so those controls actually reopen their intended panels. Open Assessments and View Results continue to use their canonical cross-view routes with Program/Academic Year context.

Student Assessments now projects the configured Evaluation Plan together with physical Cycle contexts. It groups by normalized user-facing Evaluation label, orders those groups by configured sequence when available, then renders unique Programs, so one Program cannot appear twice under the same Period merely because multiple Cycles exist or legacy sequence metadata differs. Programs with a configured Period remain visible before the first internal Cycle is created.

The reassessment compatibility boundary is also closed for legacy data created before assessed-Framework immutability was consistently enforced. Detection now covers both changed rubric/level bindings and same-ID semantic edits proven by Talent configuration audit events after the Student completed. A completed Assessment is marked **Re-evaluation required** when its persisted competency-result rubric/level bindings no longer match a complete current competency-owned rubric on the same Framework Version. Untouched legacy or partially configured rubrics do not trigger this rule. Starting re-evaluation makes the old completed attempt non-current and opens a fresh current in-progress replacement with zero results in the original visible Evaluation; prior evidence is preserved internally rather than deleted.

Normal Grade-level Competency creation no longer synthesizes an ASCII-only code in the browser. Unicode names such as Arabic Competencies are sent without a technical code, and the backend allocates the existing unique Program-scoped internal code. No schema migration was added.

Talent navigation now also follows an explicit module-tree/context-boundary rule. While Talent & Potential is active, the main sidebar expands Overview, Programs, Student Assessments, Talent Review, and Results & Analytics as permission-aware child destinations. Those top-level destinations carry the selected Academic Year only and clear stale Program/Cycle/Assessment and analytics filter context from the page being left. Programs therefore always re-enters the searchable Program list unless an explicit Program-opening link is used, and Student Assessments opens neutral with its own Program selector rather than inheriting a previously selected Program. The Programs table now exposes one normal Open Program entry point per row; Program-specific Edit Program, Build/Edit Rubric, Manage Evaluation Plan, Open Assessments, and View Results remain inside the opened Program workspace.

## Talent Current Rubric, Re-evaluation, And Rubric-Delete Correction

Per direct Owner instruction on 2026-09-11, the normal Student Assessment
workspace is current-only: the selected Evaluation shows the current eligible
Students with Grade, Section, Assessment status, and Action, and no separate
Assessment Records/History table is rendered. Superseded attempts remain
preserved evidence internally.

The canonical current assessment structure is Grade -> Competency ->
competency-owned Rubric -> ordered Levels. Legacy NULL-owned shared rubrics
remain compatibility evidence only; `start_assessment_for_evaluation` selects
only the newest saved Framework that has a complete competency-owned rubric
with levels for every applicable Competency. A completed current Student whose
newer complete rubric is materially different surfaces **Re-evaluation
required**. Re-evaluation creates a new current Assessment against that newer
Framework, links it to the prior attempt, retains the original visible
Evaluation/Term through `evaluation_context_cycle_id`, and opens the replacement
Assessment directly.

All Student-facing Framework mutations for competency/rubric/level/description
authoring are blocked once that exact Framework has Assessment history. The
Rubric tool exposes legal Competency and Rubric Level deletion only when the
actor has the dedicated assignable permission. `talent_programs.delete_competency`
and `talent_programs.delete_rubric_level` are independent from
`talent_programs.delete`; `talent_programs.manage` alone does not imply either
delete authority. Deleting an eligible Competency branch also removes its
owned Rubric and owned Levels in the same mutation after descriptor/KPI/policy
dependency checks, and never applies to an assessed Framework.


## Talent Assessment Delete — Zero-Evidence Governance Exception Recorded

Per direct Owner instruction on 2026-09-11, a narrow Administrator-only
Delete Assessment capability is now approved: see
`docs/adr/0034-assessment-delete-zero-evidence-exception.md`. A
`TalentStudentAssessment` may be permanently deleted only when it has zero
competency results, zero Educator Input, zero Review Candidate membership,
and zero Official Identification decision (the exact dependent-table list is
re-verified against the schema at implementation time). Any Assessment with
any such evidence remains permanent history and is never deletable, exactly
like every other terminal Talent record. This does not authorize deleting
Student placement history, Cycle population records, or any Student/Program
delete capability beyond what ADR 0032 already governs. This entry and the
referenced ADR are the authorization record, not a completion record.

## Talent Corrective Reconstruction Batch 2 — Permissions, Draft Program Delete, Evaluation Timeline

Implements the governance recorded above in "Draft Talent Program Hard
Delete — Scoped Governance Exception Recorded" (ADR 0032) plus a related set
of permission-narrowing changes. Three new permission keys were added to
`permission_registry.py` using the existing additive `(key, description)`
tuple pattern, with no hard-coded role names: `talent_programs.delete`,
`talent_evaluation_plans.delete_period`, `talent_evaluation_plans.manage_timeline`.

`DELETE /api/talent/programs/{program_id}` (`routers/talent_programs.py`,
`talent_program_service.delete_program`/`program_delete_blockers`) permits a
hard delete only when `program.status == 'draft'` AND zero rows exist in
every table with a real, re-verified direct foreign key to
`talent_programs.id`. That re-verification against the current `models.py`
schema confirmed exactly the five tables ADR 0032 named —
`TalentProgramFrameworkVersion`, `TalentProgramAcademicYearConfiguration`,
`TalentCompetency`, `TalentAssessmentCycle`, `TalentEducatorInput` — and no
others; every other Talent table reaches a Program only transitively through
one of these five, so the database's own composite foreign keys already make
a downstream row impossible once these five are confirmed empty. Any other
status, or a Draft Program with a related row, is rejected with a clear
error, never a silent no-op. The route requires `talent_programs.delete`
plus the same organization-scope authorization already used by other
Program mutation routes, and records the deletion through the existing
`TalentConfigurationAudit` mechanism (no new audit path). The Program
list/read payloads now include a real backend-computed `actions` array
(`"delete"` present only when the backend already allows it) so the UI never
client-side-guesses this affordance. No Configured/Active/Retired Program
gained a hard-delete path; the activate/retire invariant is otherwise
unchanged.

The existing Competency framework-membership and Rubric Level true-delete
routes now use dedicated permissions: `talent_programs.delete_competency` and
`talent_programs.delete_rubric_level`. Whole Draft Program deletion remains
separately governed by `talent_programs.delete`; lifecycle/history guards remain
server-enforced. Evaluation Period true-delete is narrowed from
`talent_evaluation_plans.manage` to the new
`talent_evaluation_plans.delete_period`. The new
`talent_evaluation_plans.manage_timeline` permission gates exactly
`planned_start_date`/`planned_end_date` edits and Period
reorder/sequence (`POST .../periods/reorder`); ordinary Period content
editing (label, short code, required flag, notes) stays under the existing
`talent_evaluation_plans.manage`. A single `PATCH` touching both a timeline
field and a content field now requires both permissions — missing either
rejects the whole request before any field is applied, never a partial
save. Viewing dates is unchanged (no new permission required to read them).
`planned_start_date`/`planned_end_date` already existed on
`TalentPlannedEvaluationPeriod` and were already returned/accepted by the
API; this pass did not add new backend date capability. The Talent icon
(`ui_shell.py` `PAGE_META["talent"]["icon"]` and the primary nav item) moved
from the shared `clipboard-check` glyph (still used by Observations,
unchanged) to the existing canonical `sparkles` glyph, so the two modules no
longer share an icon. The Program list/summary "Type" label was renamed to
"Scoring Mode" (derived states unchanged: Not set/Rubric/Numeric + rubric;
no schema/API change), and the operational "Saved assessments" list is now
labeled "Assessment Records" in `static/js/talent-operations.js`, reusing
the existing Start/Continue/View Assessment action distinction unchanged.
The Evaluation Plan workspace now renders the existing server-computed
advisory warnings (`period_window_overlap`, `chronological_inconsistency`,
`cycle_outside_planned_window`, already returned on the Plan payload by
`talent_evaluation_plan_service.plan_warnings`) as a compact, ARIA-labeled
list — presentation only, no new validation math. A completed numeric
assessment result now shows its already-returned scale
(`result_scale_min`/`result_scale_max`) beside the result; `interpretation`
text is not included in that payload and was not fabricated.

Both gaps above were closed in a follow-up verification/closure pass with
UI-only changes and no new backend capability. `static/js/talent-evaluation-workspace.js`
now renders each Period's `planned_start_date`/`planned_end_date` as
always-visible native date inputs, editable only when that Period's
backend-returned `actions` array includes `edit_timeline` (the existing
`talent_evaluation_plans.manage_timeline` gate) and read-only text otherwise;
the date save is its own separate request carrying only the two timeline
fields, never combined with label/content fields, so the existing
mixed-PATCH-requires-both rule is never bypassed by a silently partial
submission; clearing a date sends `null`, matching the already-existing
backend clear support. Separately, the shared Talent context filter
(`static/js/talent.js`) now hides its top compact Program dropdown
specifically on the `/talent/programs` view while no Program is selected,
since that view's own compact Program table (with Program identity/logo) is
already the selection mechanism there; the dropdown remains the sole
selector once a Program is chosen on that view, and remains the sole
selector on every other Talent view, which has no in-content chooser. A
deep link that already carries `program_id` still lands directly in the
selected state with no chooser flash, since the field-visibility decision is
synchronous from the URL before any data fetch. No permission, schema,
migration, tenant, or backend contract changed.

## Talent Corrective Batches 3 And 4 Complete

One shared rubric visual module now renders arbitrary ordered levels across configuration, assessment entry, Talent Review, Student Profile, Learner Profile, and analytics. Review and profile read projections add the actual stored rubric label and its position without changing candidate computation. Official Identification remains a separate permanent human decision.

Talent Overview is reduced to compact operational action cards. Organization Overview no longer duplicates Program Results cards or a Talent Map matrix; it keeps selective progress, Program Criteria, Official Identification, Branch/Grade distribution, selected-Program rubric distribution, and selected-Program Evaluation Period progression. Learning Style distribution continues to use the existing Students endpoint and privacy contract, while its read-only filters now cascade from authorized Organization/Branch context through Planning-derived Grades and Sections.

## Draft Talent Program Hard Delete — Scoped Governance Exception Recorded

Per direct Owner instruction on 2026-09-10, a narrow exception to the
activate/retire-only Program lifecycle (recorded below in "Talent Program
Setup Wizard Owner Correction" and unchanged) is now approved: see
`docs/adr/0032-draft-talent-program-hard-delete-exception.md`. A Program may
be hard-deleted only while `status == 'draft'` and it has zero rows in every
table with a direct/child relationship to it (framework versions, Academic
Year configuration, competencies, assessment cycles, educator input — the
exact list is re-verified against the schema at implementation time). Every
Configured, Active, Retired, or otherwise historical Program remains
governed by activate/retire only, exactly as already recorded; terminal
assessments and historical framework versions remain immutable. This entry
and the referenced ADR are the authorization record, not a completion
record.

## Student Learning Style V1 — Governance Decision Recorded

Per direct Owner instruction on 2026-09-10, Learning Style moves from
deferred/out-of-scope (as recorded throughout the M7-M10 milestone history
below and in `docs/AI_PROJECT_CONTEXT.md`, `docs/TIS_MASTER_CONTEXT.md`, and
`docs/engineering/PRODUCT_ROADMAP.md`) to active V1 scope. See
`docs/adr/0031-student-learning-style-v1.md` for the governed contract:
optional single-select Student-domain field, four fixed values (Visual,
Auditory, Read/Write, Kinesthetic), reuses the existing `students.edit`
permission, zero effect on any Talent scoring/eligibility/Official
Identification computation, and aggregate analytics display only under the
existing Talent privacy/suppression contract. Implementation status is
tracked separately as it lands; this entry and the referenced ADR are the
authorization record, not a completion record. The historical milestone
entries below that describe Learning Style as out of scope remain accurate
as of the dates/milestones they describe and are not being revised.

## Student Learning Style V1 — Core Implementation Landed

Per ADR 0031, the governed V1 contract is now implemented. `Student.learning_style`
is a nullable `VARCHAR(20)` (migration `20260910_002_student_learning_style_v1`,
purely additive - one nullable column, no rewrite; a `NOT VALID`/`VALIDATE`
PostgreSQL CHECK constraint mirrors the fresh-schema SQLAlchemy `CheckConstraint`
for defense in depth) validated server-side in `student_academic_service.py`
against exactly `Visual`/`Auditory`/`Read/Write`/`Kinesthetic` (any other value,
including case variants, is rejected with `invalid_learning_style` at the API
layer regardless of UI restriction). Optional on Student create/edit
(`templates/_learning_style.html`, reused by `student_form.html` and
`student_profile.html`); unset renders as neutral "Not specified", never an
error state. Displayed compactly on the Student Profile Overview and on the
Student Profile Talent tab as explicit, visually distinct learner context
("Learner context (not a Talent signal)"). Editing reuses the existing
`students.edit` permission; no new permission was introduced. Confirmed by
source-scan regression test that no Talent scoring/Program-Criteria/Review/
Official-Identification module reads `learning_style`.

Branch/Organization Learning Style distribution is implemented as a
lightweight Students-domain surface (`student_learning_style_analytics.py`,
`GET /api/students/analytics/learning-style-distribution`, and a compact
panel on the Students list page reusing its existing Branch/Grade/Section
filters) rather than inside the Talent B7 organization-analytics closure,
because its population - "Students with a current effective placement in the
actor's authorized scope" - is never Program/Cycle-scoped like every existing
Talent analytics metric. It reuses the exact governed Talent privacy contract
(`talent_analytics_privacy.py`'s `Cell`/`Group`/`apply_primary_privacy`/
`run_complementary_suppression`, the same "one Group, total = sum(children)"
shape the existing `/rubric-distribution` route already uses) rather than a
separate or weaker rule, and fails closed (503 `analytics_unavailable` on the
API; a hidden panel on the Students page) when no privacy policy is
configured. The Talent Review/Assessment per-Student operational drill-down
in `static/js/talent-operations.js` was deliberately left unchanged in this
pass: its `context` payload is built in `routers/talent_review_candidates.py`
and `routers/talent_assessments.py`, both already carrying substantial
uncommitted in-flight changes from separate concurrent work at the time of
this change, and extending it was judged unsafe to combine with that
in-flight work rather than a scope decision about the feature itself.

## Students + Talent & Potential M1 — Governance Reconciliation And Additive Schema Foundation (2026-09-22)

Per ADR 0042 (amends ADR 0031) and ADR 0043, this milestone adds only the
persistence/schema foundation for two later capabilities: a four-dimension
Student Learning Style profile and the globally unique managed TIS Student
ID namespace. No API, service-layer write path, or frontend was added in
this task; both are explicitly out of scope for M1.

`Student` gains four independent, nullable `INTEGER` columns -
`learning_style_verbal_percentage`, `learning_style_non_verbal_percentage`,
`learning_style_quantitative_percentage`, `learning_style_spatial_percentage`
- each constrained to NULL or 0-100 with no sum rule and no relationship to
any other field. Migration
`20260922_001_student_learning_style_four_dimension_profile` adds the
columns via `ALTER TABLE ... ADD COLUMN` and, on PostgreSQL only, a
non-locking `NOT VALID` + `VALIDATE CONSTRAINT` CHECK per column (SQLite
relies on the fresh-schema SQLAlchemy `CheckConstraint`, matching the
existing `20260910_002_student_learning_style_v1` precedent's documented
dialect asymmetry). The legacy categorical `learning_style` column, its
CHECK constraint, and every existing row are completely unchanged - no
rewrite, no mapping, no automatic conversion in either direction.

The existing `StudentExternalIdentifier` model/table gains no new column.
Migration `20260922_002_student_tis_number_identifier_integrity` adds two
partial unique indexes scoped to `namespace = 'tis_student_number'`:
`uq_student_external_identifiers_tis_student_number_value` (global
uniqueness of `value` across every SchoolGroup, covering active AND
inactive rows, so a retired value can never be reissued) and
`uq_student_external_identifiers_tis_student_number_active_student` (at
most one `active` row per `student_id`, correct organization-wide because
`Student.id` is already a single global primary key). Every other
namespace's existing tenant-scoped uniqueness
(`uq_student_external_identifiers_scope_namespace_value`) is unchanged.
Before installing either index, the migration inspects any existing
`tis_student_number` rows and fails safely with a descriptive
`RuntimeError` (no delete/merge/rename) if it finds a non-canonical value
(not `STD` + exactly 10 digits), a value duplicated across SchoolGroups, or
a Student with more than one active row; the current `tis.db` and every
exercised test/local database had zero pre-existing `tis_student_number`
rows, so this preflight path was exercised only via seeded-conflict tests,
not a real historical blocker.

`Student.id` remains the sole internal relational identity; no new Student
identity table or column was added, and no existing legacy Student was
backfilled with a fabricated `tis_student_number` value - a legacy Student
with zero managed-identifier rows remains valid.

Not implemented: TIS Student ID create/edit API/UI and its duplicate-value
messaging, database-level canonical-format enforcement, Learning Style
percentage API/frontend, Evaluation Progress, and roster import/export -
all explicitly deferred to later milestones at this point in time. (The
`students.import`/`students.export` permission keys were later registered
as a governance prerequisite - see "Student Roster Import/Export —
Permission Registration (Governance Prerequisite, M6)" above - but the
roster import/export feature itself remained, and remains, unimplemented.)
Al-Andalus Section display was
also deferred at M1; per ADR 0045 it was Owner-authorized for the exact
verified `workspace_uuid` `72e52eb2-3844-447b-92a8-c55015f73257`, and its
M5 implementation is now done - see "Al-Andalus Section Display -
Governance Authorization" and "Al-Andalus Section Display M5 - Shared
Presentation Implementation" above.
Focused coverage is in `tests/test_student_learning_style_profile_foundation.py`
and `tests/test_student_tis_number_identifier_foundation.py`; PostgreSQL
migration coverage (upgrade path and preflight-conflict rollback) is added
to `tests/test_postgresql_migration_transactions.py` following its existing
`TIS_TEST_POSTGRESQL_URL` skip-marked convention and auto-skips in this
environment (no local PostgreSQL listener).

## Students + Talent & Potential M3 — Four-Dimensional Learning Style Backend/Service/API (2026-09-22)

Per ADR 0042, this milestone implements the previously-deferred server-side
service/API for the four-dimension Learning Style percentage profile on top
of the M1 schema foundation (no new migration - the four nullable, 0-100
CHECK-constrained `Student` columns already exist). All logic lives in
`student_academic_service.py` and `routers/students.py`; no new table, no
new permission, and no frontend.

`student_academic_service.py` gained `LEARNING_STYLE_PERCENTAGE_FIELDS` (the
four column names) and `_clean_learning_style_percentage`, which validates
each dimension strictly and independently: `None` is valid ("not
assessed"), and an `int` 0-100 inclusive is valid, explicitly including both
boundary values; `bool` is rejected even though it is a Python `int`
subclass, and any other non-`int` type - a float/decimal or a numeric
string such as `"75"` - is rejected rather than coerced, matching this
dict-based JSON body's existing no-schema-coercion convention (there is no
Pydantic model on this route). There is no sum-to-100 rule and no
derivation to or from the legacy categorical `learning_style` column, which
remains completely untouched. `create_student`/`create_student_with_number`
gained the four optional keyword parameters (default `None`, all four may
be omitted); an invalid value raises before any row is added, so an invalid
dimension never leaves a partial/orphan Student, matching the existing M2
atomicity guarantee for `student_number`. `update_student` applies each of
the four fields only when its key is present in the caller's `**changes`
(the same partial-update convention the function already uses for
`learning_style`/`first_name`/etc.), so PATCH's existing partial-payload
semantics (`routers/students.py` only forwards keys actually present in the
request body) mean an unspecified dimension is never cleared and an
explicit `null` does clear it. `_student_payload` (used for the existing
`StudentAudit` before/after snapshots) now includes all four fields, so a
Learning Style percentage update participates in the existing append-only
Student audit trail exactly like every other Student field - no new audit
subsystem, no history/version table, and no Talent snapshot were added,
matching ADR 0042's explicit prohibition.

`routers/students.py`: `POST /api/students` and `PATCH
/api/students/{student_id}` now accept the four fields under the existing
`students.create`/`students.edit` permission gates (no new permission); the
M2 mandatory `student_number`-on-create contract is unchanged and
re-verified by regression. Every Student JSON response
(`GET`/`POST`/`PATCH /api/students...`) now exposes all four fields
alongside the unchanged legacy `learning_style` field, with no derived
dominant-style, total, or normalized field ever added.

Confirmed by source-scan regression (extending the existing M1 pattern) that
no Talent scoring/eligibility module (`talent_program_service.py`,
`talent_analytics_service.py`, `talent_org_intelligence_service.py`,
`talent_analytics_privacy.py`, `talent_student_assessment_service.py`,
`routers/talent_assessments.py`, `routers/talent_review_candidates.py`,
`routers/talent_assessment_cycles.py`, `routers/talent_programs.py`) reads
any of the four percentage fields or the new validator. Focused coverage is
in `tests/test_student_learning_style_four_dimension_api.py` (73 tests:
independent service-level validation of null/partial/0/100/no-sum-rule
profiles, out-of-range and wrong-type rejection per field, create-time
atomicity, partial-update semantics proving sibling/unspecified-field
isolation, legacy-field preservation on create and update, Student-create
API acceptance/omission of all four dimensions with the M2 `student_number`
requirement re-verified intact, Student-update API permission reuse and
cross-tenant denial, response serialization, audit participation, and the
Talent source-scan regression). The full relevant regression sweep
(`tests/` filtered to `student or talent or permission`, excluding the two
`ortools`-dependent Timetable-Workflow-only solver test modules that fail to
import in this environment) passes with exactly the same 13 pre-existing
failures directly confirmed present and unchanged via an explicit
before/after comparison run against unmodified `dev` HEAD `24bdb06` in this
task (not merely cited from the prior M2 note); none are newly introduced
or newly fixed by M3.

## Students + Talent & Potential M2 — Managed Student ID Backend/Service/API (2026-09-22)

Per ADR 0043, this milestone implements the previously-deferred TIS Student
number create/edit service/API and canonical-format validation on top of the
M1 schema foundation (no new migration - the two M1 partial unique indexes on
`student_external_identifiers` remain the sole concurrency authority). All
logic lives in `student_academic_service.py` and `routers/students.py`; no
new table, no new permission, and no frontend.

Business input is exactly ten ASCII digits (leading zeros preserved as a
string, never parsed as an integer); the service alone controls the
canonical `STD` + 10-digit stored format
(`validate_student_number_digits`/`canonical_student_number`). New Students
created through `POST /api/students` now require `student_number` and the
new `create_student_with_number` atomically creates the `Student` row and its
`tis_student_number` `StudentExternalIdentifier` row in one uncommitted
transaction - an `IntegrityError` on the identifier insert (duplicate/race)
is caught by the router, which rolls back the whole transaction first, so no
orphan/partial `Student` row is ever left behind. Existing legacy Students
(and the existing HTML `/students/new` UI creation path, which is
intentionally unmodified and continues to call the original `create_student`
directly) are unaffected and may continue without a number; a legacy Student
may receive or replace its number later via the new
`PUT /api/students/{student_id}/student-number` route, backed by
`set_student_number`, gated by the existing, already-governed
`students.manage_identifiers` permission (no new permission key was needed
or added). Replacing a number never mutates the old row: the old active row
is marked `inactive` (audited as `replace_retire`) and a new row is inserted
active (audited as `replace`) in the same transaction, so `Student.id` is
unchanged and the M1 global-uniqueness index keeps the old value permanently
reserved. The generic `add_external_identifier`/`deactivate_external_identifier`
functions now explicitly reject the `tis_student_number` namespace
(`managed_namespace` error) so the generic external-identifier API cannot
bypass the managed contract in either direction.

Duplicate-value disclosure follows an explicit privacy rule enforced at the
router layer (`routers/students.py::_student_number_conflict_response`),
executed only AFTER the failed insert's transaction is rolled back: a
read-only, unauthenticated lookup
(`student_academic_service.find_student_number_holder`) identifies the
conflicting `school_group_id`/`student_id`, and the router discloses
`student_id`/`display_name` if and only if that identifier belongs to the
requester's own SchoolGroup AND the actor independently holds
`students.view` for that scope; every other case (cross-tenant, unauthorized
same-tenant, or a value retired by a Student the actor cannot/does not
independently view) returns the exact same generic
`{"detail": ..., "code": "student_number_unavailable"}` body, so there is no
enumeration oracle and no cross-tenant/retired-vs-foreign distinction leak.
The raw lookup itself never grants a general Student-lookup capability - it
returns only a bare `school_group_id`/`student_id` pair with no name or
other metadata, and the router's authorization check is applied before any
identity is ever returned.

A canonical `student_number` field (e.g. `"STD0012345678"`, or `null` for a
legacy Student) is now exposed on every Student JSON response
(`GET`/`POST`/`PATCH /api/students...`) via `current_student_number`, without
renaming any existing field or changing unrelated response shape.

Three pre-existing tests that posted to `POST /api/students` without a
`student_number` were updated to supply one, since this endpoint's required-
field contract is the intended M2 behavior change, not a regression:
`tests/test_student_academic_foundation.py` (two call sites, one with an
updated audit-event-count assertion reflecting the one additional
`external_identifier`/`create` audit row every managed-number creation now
also writes), `tests/test_student_learning_style_v1.py` (two call sites), and
`tests/test_permission_surface_consistency.py` (one call site, a permission-
gating test unrelated to the identity field itself). Focused coverage is in
the new `tests/test_student_managed_number_service.py` (46 tests: format
validation, atomicity/no-orphan-Student, legacy assignment, replacement
mechanics, M1 global/same-tenant/cross-tenant/retired-reuse uniqueness, the
IntegrityError race path, privacy-safe duplicate classification for all four
combinations, `students.create`/`students.manage_identifiers` permission
gating, cross-tenant denial, the managed-namespace boundary on the generic
identifier API, audit events for create/assign/replace, and regression for
an unrelated namespace and an existing Academic Placement workflow). The
full relevant regression sweep (`tests/` filtered to
`student or talent or permission`, excluding the two `ortools`-dependent
Timetable-Workflow-only solver test modules that fail to import in this
environment) passes except the same 13 pre-existing failures already present
on unmodified `dev` HEAD `e98214f` before this task (11 unrelated
Talent/permission/SaaS failures plus the two Students failures already
recorded as pre-existing in the M1 entry above); none are newly introduced by
M2, and both this environment's `ortools` absence and those 13 pre-existing
failures are unrelated to this task and unresolved by it.

## Evaluation Plan Scope Regression Correction

Evaluation Plan capability projection now has explicit regression coverage for both sides of the authority boundary: an organization-scoped manager retains manage/govern actions while working in a selected Branch, while a truly Branch-scoped identity receives no mutation capability even if its role grants the permission key. The Evaluation Plan workspace explains that read-only state before submission.

The sanctioned Local Test Admin source remains organization-scoped with North Campus assigned as its working Branch. A previously created disposable local Talent database may contain a stale `BRANCH` value; the supported correction is the sentinel-guarded `scripts/manage_local_talent_test_db.py reseed --confirm` workflow.

## Talent Completed Program Operational Workspace

Completed active Programs open as a compact operational summary instead of remaining permanently in onboarding. Explicit Edit Program, Edit What we assess, and Manage Evaluation Plan actions reopen the same hash-backed wizard at Steps 1, 2, and 3. A fully configured Draft Program crosses into Active state when an authorized user chooses Finish Setup: Program activation occurs before Framework activation, then the Program returns to operational summary. Incomplete Programs remain in setup mode.

The UI now uses Evaluation Plan and Evaluation Period terminology consistently. Step 3 remains embedded. Program Basics reads the selected Academic Year option text rather than displaying its database ID. Organization-authority failures are mapped to clear Evaluation Period access language, and Branch-scoped users are not shown Plan-management controls the API cannot execute.

## Talent Guided Configuration And Student Display Correction

The Owner screenshot follow-up is implemented in the shared Talent workspace. Program Basics is one concise identity/year/Grades form. What we assess uses compact substeps with table rows and on-demand editors. Evaluation Schedule remains embedded inside the Program workspace while reusing the existing standalone renderer and backend contracts. Readiness is now projected on the Program summary instead of a separate Ready panel. Editing a Program from the Programs table opens this same workspace and its hash preserves the selected setup or assessment substep across refresh.

Student collection presentation now explicitly shows the compact table above 680px and compact cards at or below 680px, never both at once. Active lifecycle state remains in accessible text and filtering but is visually represented by a neutral dash; exceptional statuses keep a visible status chip. Open Evaluation and Talent Review remain compact collection tables with detail shown only after opening one Student.

## Talent Program Setup Wizard Owner Correction

The Programs detail workspace uses the Program header plus focused setup panels and local Back/Save & Continue or next-action controls. Step selection remains hash-backed where applicable. The implementation no longer emits all setup sections or duplicate Grades/readiness cards into one long page. Readiness is shown only in the Program summary and becomes positive only when all required setup areas are complete.

The management-action audit confirms the UI exposes existing permission- and lifecycle-authorized edit/remove operations for Program details and logo, draft competencies, rubric levels, achievement descriptions, optional KPI and Program criteria, Evaluation Schedule periods, and in-progress assessment results. Programs remain governed by activate/retire rather than hard delete, and terminal assessments and historical framework versions remain immutable.

## Talent Final Completion Continuation

Program Identity is implemented as optional organization-owned Talent Program branding with additive logo columns, existing `talent_programs.manage` authorization, validated Program-scoped storage, upload/replace/remove actions, and compact initials fallback. The shared Talent surfaces reuse the same logo badge. No Branch override exists.

Talent Program Grades now come only from operational Current/New `PlanningSection` rows. The shared longitudinal context cascades Academic Year to authorized Branch, configured Grade, and Planning Section; an empty section result disables the selector with "No Sections configured for this Grade." Direct annual-configuration writes validate against the same Planning authority, including the empty-Planning case. In-progress assessment competency results expose the existing revision-guarded delete route as "Clear Result"; terminal assessments remain read-only. Workspace mutations preserve URL context and scroll position.


## Talent Review Terminology, List Density, And Active-Status Presentation

Further Owner product-polish direction on the same uncommitted M11 workspace
produced these presentation-only changes, all re-verified against the fresh
current code before editing:

- The normal user-facing "Review Candidates" surface is relabeled "Talent
  Review" throughout the live rendered path: the Talent nav entry and
  breadcrumb title (`routers/talent_ui.py`'s `VIEWS` display label), the
  in-page note/empty-state/confirm/notify text and the "Check Program
  Criteria" action in `static/js/talent-operations.js`, and the Student
  Profile Talent tab (`templates/student_profile.html`). The backend
  `ReviewCandidate` model, its `/api/talent/review-candidates` routes, and
  the `talent_review_candidates.*`/`talent_official_identifications.*`
  permission keys are unchanged deterministic/audit identifiers - only the
  displayed label changed. A dead, unreachable legacy rendering branch in
  `static/js/talent.js` (superseded by `TalentOperations.render` for the
  `programs`/`evaluation-plans`/`assessments`/`reviews` views since an
  earlier pass) still contains the old wording; it was left untouched because
  it never executes and editing it would not change any observed behavior.
- The Talent Review list (`static/js/talent-operations.js`) is now one
  compact table (Student, Program, Grade, Section, Evaluation, Result,
  Review status, Identification status, Action) instead of one large card
  per Student, reusing the existing `.tp-compact-table`/`.tp-table-wrap`
  classes already established by the Programs table
  (`talent-program-workspace.css`). Opening a row (`?review_id=`) shows that
  one Student's full detail - including the Official Identification decision
  form - the same content the card used to show inline for every Student.
  No server-side pagination exists anywhere in Talent to reuse (Programs and
  Students both use a plain table with client-side search, not pagination),
  so none was invented here either.
- An opened Evaluation's Student list is now the same compact-table pattern
  (Student, Grade, Section, Assessment status, Action) instead of one card
  per Student, with a state-driven action label read from the real
  assessment status: no assessment yet - "Start Assessment" (only offered
  while the Cycle is Open and the actor can manage); `in_progress` -
  "Continue Assessment"; any other recorded status (Completed, Incomplete,
  Insufficient Evidence) - "View Assessment". No new assessment state was
  introduced; this is presentation over the existing status values.
- In the Students list (`templates/students.html`), the normal "Active"
  lifecycle status (Student lifecycle, not Talent status - unchanged
  semantics) no longer renders as a colored `stu-chip` badge on every row,
  since Active is the expected state for a normal attending Student. It now
  renders as plain muted text (`.stu-status-quiet`). "Inactive" keeps its
  visible chip as a real exception, and Status remains an available
  filter/column in both the desktop table and mobile cards.
- Investigated and explicitly deferred (not implemented) from the same
  direction: (1) Program Identity/Logo, a new capability requiring a
  `TalentProgram` schema/model change and new upload routes - out of this
  pass's safe bounded scope. Program ownership was confirmed organization-
  scoped (`school_group_id`, no `branch_id`) on the current model, so no
  branch-level Program logo override exists or was added; `branding_storage.py`
  (organization/branch logo upload, including safe SVG sanitization) is the
  correct existing pattern to reuse if this is built later. (2) Planning-
  driven Grade/Section pickers for Talent's own filters/setup screens -
  confirmed still open: the shared Talent context filter's Grade picker in
  `static/js/talent.js` still renders a hardcoded KG+1-12 list rather than
  the Planning-configured subset the Students module already uses.

Presentation-only: no schema, migration, permission, analytics computation,
provider, privacy, tenant, review-candidate/official-identification business
rule, or `tis.db` change.

## Talent Owner Visual Acceptance Corrections

Real Owner visual acceptance of the M11 workspace (as distinct from the prior
code-level trace, which explicitly could not obtain browser screenshots) found
four presentation defects, all corrected in `templates/talent/workspace.html`
and `static/js/talent.js` (the one shared filter form/apply logic every Talent
page reuses) plus `tests/talent_results_experience.test.cjs` and
`tests/test_talent_ui.py` regressions:

- The `tp-filters` context selector (Academic Year/Program/Branch/Grade/
  Metric/Dimension) no longer requires clicking "Apply context" to take
  effect on any page - Programs, Evaluation Schedule, Organization Overview,
  and every other Talent page. A `change` listener on the form calls the same
  `applyContext()` reload path the button already used, debounced 250ms so a
  user clicking through several dropdowns triggers one reload, not one per
  dropdown. The existing URL-query-parameter/`history.replaceState` context
  mechanism is reused unchanged. The button is relabeled "Refresh" and is now
  an optional immediate fallback, not a required confirm step.
- The primary Talent nav no longer repeats the full analytics-family link list
  (Organization Overview, Talent Map, Program Results, Students Across
  Programs, Progress Over Time) directly above the existing sticky analytics
  sub-nav that already lists those same pages plus Students. The primary nav
  now shows exactly one "Results & Analytics" entry; the sub-nav is kept
  because six distinct analytics pages are genuinely more than the primary
  nav should enumerate.
- Confirmed still intact and covered by a fresh rendered-output regression:
  the Evaluation Schedule normal path renders no internal-lifecycle copy
  ("Prepared evaluations", "Ready to link", "Link an evaluation", "No
  Evaluation Plan", "Frozen population", or the bare words Plan/Period/Cycle/
  Link) and evaluation names remain completely free-text/user-defined - both
  already corrected by the immediately preceding Talent UX Simplification
  pass below and re-verified here, not re-implemented.
- Confirmed still intact: the Programs landing screen is a compact searchable
  table with the Create-Program form collapsed behind "New Program", not
  permanently expanded.

Diagnosed and NOT code-changed (environment-setup issue, not a defect):
Organization Overview showing "Analytics unavailable" locally is the correct,
intentional fail-closed M10 behavior whenever the running process's
`DATABASE_URL` does not resolve to exactly `.local_test_data/
talent_local_test.db` (`talent_organization_analytics_providers.
is_sanctioned_local_analytics_environment()`); `database.py`'s
`DEFAULT_SQLITE_URL` falls back to `tis.db` when `DATABASE_URL` is unset, which
is what an ordinary local run does today. The detection logic itself was
verified correct (relative and absolute `sqlite:///` forms both resolve
correctly on Windows); running the app with `DATABASE_URL` set to the
sanctioned local path before process start activates the deterministic local
providers. This is unchanged from the existing B11-E F1 contract described
below and required no code change.

Presentation-only: no schema, migration, permission, analytics computation,
provider, privacy, tenant, or `tis.db` change.

## Talent Program And Evaluation UX Simplification

The Programs and Evaluation Plans surfaces now implement the Owner-directed
simplified journey. Programs use a searchable compact desktop table; the
Create-Program form is not permanently expanded on that landing screen and
opens instead as a collapsed panel behind a "New Program" action. Program
setup is labeled Basics, What we assess, Evaluation schedule, and Ready;
competencies display alongside their rubric levels and achievement descriptions,
while version details remain in the edit disclosure. Saving returns to the
joined view.

Evaluation schedule replaces normal Plan/Period/prepared-Cycle terminology with
a free-text, user-defined evaluation name (for example Term 1, Audition, or
Spring Review) and the states Setup, Ready to start, In progress, Complete;
internal-lifecycle copy ("Prepared evaluations", "Ready to link", "Link an
evaluation", "No Evaluation Plan", "Frozen population") is not rendered in this
normal path. Start Evaluation safely sequences draft preparation,
revision-guarded Period linkage, population preview, explicit count/date
confirmation, and governed open/freeze. The previously omitted Evaluation Plan
manage/govern permissions now reach the browser payload, with govern suppressed
for Branch scope. No schema or backend contract changed.

## Production Student/Talent Migration Blocker Repair

The Render pre-deploy blocker is repaired locally and ready for independent
review. Root cause was pre-ledger `metadata.create_all()` attempting the new
Student/Talent model graph against legacy PostgreSQL parents before migration
`001` could establish required composite uniqueness. `branches(id,
school_group_id)` failed first; `academic_years(id, school_group_id)` was also
missing in the production-style baseline. `students(id, school_group_id)` is
created with its unique constraint on fresh runs and is covered by the new
prerequisite for already-existing schemas.

The runner defers the complete Student/Talent table set and the ledger adds
`20260904_000` before the existing eight migrations. A separate current-model
coupling found by the fresh-chain test is also resolved: M4 Cycle creation no
longer requires the future M8 Period table, while M8 still adds the exact
nullable composite foreign key after creating its parent. PostgreSQL 16 results:
complete 63-entry fresh run PASS, second run no-pending PASS, existing-schema
late-`000` PASS, duplicate preflight rollback PASS, and old-runner partial-DDL
rollback PASS. No production inspection, SQL, deployment, commit, or push was
performed.

## Phase H Cumulative Release Qualification

Phase H is PASS WITH BASELINE EXCLUSIONS. The current full-suite run collected
1,748 parent test items and reported 1,618 passed, 78 failed, and 59 skipped,
plus 87 passed subtests. The sometimes-cited 1,755 is the arithmetic sum of
those headline outcome counters, not a separate collection count. A clean
pre-Talent baseline at `8ed2cc998b8f1c29b5f1d7b34c3b9532deff603e`
reproduced all 78 current failures in the bounded failure-file set; 78/78 are
baseline/environment failures and zero are attributable to Talent changes.
The production-deployment memory-allocation ratio remains environment-specific
and unevaluated until the actual Render allocation and worker count are known.

## M10 B11-E F1 Production Providers

The current working tree implements production-capable provider resolution for
all seven Organization Intelligence routes. `talent_organization_analytics_providers.py`
owns the fail-closed implementations: an externally configured P1-P7 minimum
cohort of 5, the `feature.organization_intelligence` commercial feature check,
and externally configured ceilings of 1000 matrix cells, 1000 relationship
results, and 1000 Program-pair results. The privacy provider keeps primary and
complementary suppression; the breadth provider rejects rather than truncates;
and availability is evaluated before, but independently from, the existing
route permissions.

The exact `.local_test_data/talent_local_test.db` URL activates deterministic
providers only outside production, allowing all seven routes and pages through
normal dependency resolution. `tis.db`, memory/other SQLite databases, and
`prod`/`production`/`live` never activate that path. Missing, invalid, mismatched,
or exceptional provider state remains unavailable. Focused provider, analytics,
entitlement, and demo-registry tests pass, along with real local HTTP checks for
all seven APIs/pages and a production-like fail-closed check. No schema,
migration, new permission, plan/pricing logic, production data, or API response
shape changed. As of 2026-09-09 (ADR 0028/ADR 0030), B11-E is CLOSED WITH ONE
ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM REMAINING and B11 overall is
CLOSED on that same basis; B12 is CLOSED.

## Talent Phase C Results & Analytics Experience

The current integrated working tree adds a presentation-only Phase C layer over the seven existing M10 Organization Analytics routes. The Organization Overview is now an executive dashboard with Academic Year context, governed KPI cards, visual Program summaries, unranked Branch navigation, and a Talent Map preview. Dedicated Program Results, Branch Results, Talent Map, Students Across Programs, Students, and Progress Over Time views use the approved public vocabulary and provide contextual drill-downs.

Visible backend percentages alone drive progress-bar and period-chart dimensions. Counts are displayed as facts without normalization; protected and unavailable results use categorical treatments that carry no magnitude. Student results retain the P7 gate, max-100 paging, frozen context, independent Candidate/Identification fields, and the canonical Profile path. Progress Over Time remains one Program plus one Academic Year and never calculates deltas, trends, or improvement. No analytics service, provider, privacy, permission, tenant, schema, migration, or data behavior changed.

A follow-up Owner-flagged presentation pass adds two more views over the same unchanged backend contracts. The Organization Overview now leads with a single largest-on-page radial gauge showing "How many Students are talented" - drawn only from the existing `identified_of_eligible` M10 Organization Analytics metric's `organization_total` cell (org-wide, or the selected Program's scope when one is chosen), gated by the existing `talent_official_identifications.view` permission. This is the confirmed authoritative "talented" signal: Official Identification, a separate, permanent human decision recorded in Talent Review - not the rubric level and not Meets Program Criteria/Review-Candidate membership on their own, both of which remain displayed as distinct supporting signals. Second, the previously implemented but UI-unused M9 `/rubric-distribution` route is now wired into the Organization Overview (shown only when one Program is selected, reusing the existing `talent_analytics.view` permission): a new shared, order-derived rubric-level visual (`rubricDistribution`/`rubricLevelIntensity` in `static/js/talent.js`) draws each rubric level's intensity purely from its position among its siblings - never from a count/percentage/magnitude - so any Program's arbitrary label set and level count renders safely, including a level whose result is privacy-protected. Bar length for a level continues to come only from an already-visible backend percentage, identical to the existing grade/branch bar pattern. No analytics service, provider, privacy threshold, suppression rule, permission, tenant, schema, migration, or data behavior changed; both additions are pure consumers of already-existing, already-tested backend projections.

Automated Node presentation/privacy/accessibility checks and all seven focused M10 route suites pass. Read-only verification against `.local_test_data/talent_local_test.db` returned HTTP 200 for every analytics API and page. No connected browser was available, so desktop/mobile visual acceptance remains pending independent review.


## Talent Phase B Full Operational Workflow

The current working tree upgrades the M11 Talent & Potential workspace from its
read-only draft into an operational M2-M8 workflow. `static/js/
talent-program-workspace.js` provides Program creation/editing, annual eligible
Grades, version history/cloning/governance, competency and rubric ordering,
descriptor configuration/removal, optional Framework-specific KPI settings,
and Review Candidate rule configuration. `static/js/
talent-evaluation-workspace.js` reuses authoritative M8 action projections to
create Plans and Periods and M4 APIs to prepare, link, and open Cycles.
`static/js/talent-operations.js` starts assessments from authorized frozen
population rows, edits exact competency/rubric results through the real M5
write API, handles sequential revisions and stale conflicts, completes/finalizes
assessments, evaluates/reviews Candidates, records the separate human Official
Identification decision, and adds/amends separately governed Educator Input.

Assessment/Candidate API responses now include a display-only `context` built
after existing tenant and historical-Branch authorization. Population responses
add Student and Branch names while retaining frozen Grade/Section authority.
Framework and rubric read projections expose the stable row IDs required by
writes; descriptor IDs are exposed for precise removal. Public IDs are kept out
of the semantic-fingerprint projection, preserving the original M3 semantic
identity contract.

Focused frontend checks pass, the full Talent pytest selection passes, and a
real-router temporary-SQLite HTTP test covers the complete qualitative workflow,
including partial-save revision sequencing, stale rejection, no automatic
identification, the mandatory review gate, one-decision enforcement, and
Educator Input amendment history. The temporary acceptance harness never opens
`tis.db`. Browser verification is still pending because computer-use reported
no available browser. Detailed Candidate rule-result reasons remain unavailable
because the current read payload does not expose the persisted evaluation
snapshot. This is a Web Service-only change with no Workflow-worker
or migration deployment requirement.

## Student Profile History Read Endpoint (Partial Phase A Core Students Slice)

A delegated "Phase A - Core Students" slice (canonical Students navigation area,
list/add/edit, Academic Placement UI, and a four-section Student Profile with a
read-only Talent & Potential summary) added exactly one backend piece before a
live concurrent-agent collision was found and the remaining UI scope was
deliberately stopped (see below): `GET /api/students/{student_id}/audit`
(`routers/students.py`), backed by new `student_academic_service.
list_audit_events`/`audit_event_payload`. It is a pure read-only projection of
the existing append-only `StudentAudit` rows every Student/placement/identifier
mutation already writes (create/update/status-change, external-identifier
add/deactivate, and placement create/end/correction/transition) - no new
persistence authority, `resource_type`, schema, migration, or permission was
added. It requires the existing `students.view` permission and reuses the same
tenant-scoped non-enumerating 404 discipline as every other direct
Student-scoped read route; actor user ids are resolved to display names via a
plain `models.User` lookup restricted to the returned event set. Regression:
`tests/test_student_academic_foundation.py::test_audit_endpoint_reuses_existing_append_only_trail_and_resolves_actor_names`
and `::test_audit_endpoint_requires_students_view_permission` (16/16 passing in
that file; no regressions in the related `tests/test_talent_learner_profile.py`
suite).

The remainder of that delegated slice (Students list/add/edit screens,
Academic Placement assignment UI, the canonical Student Profile page and its
read-only Talent & Potential summary reusing the existing M7 Learner Profile
read API, main-navigation registration, and replacing the M11 Student Drill
"Open Learner Profile" links to point at the new profile) was NOT implemented:
a separate, live, actively-writing concurrent agent process was found mid-edit
on the exact same new file this task needed to create, `routers/students_ui.py`
(observed twice with materially different content, the second time
syntactically invalid/torn), already independently building the same
list/add/profile/placement/Talent-integration surface under the identical
route prefix and template names. Building competing templates/CSS/JS/nav
wiring in parallel would have risked a destructive overwrite race on that file
and on `ui_shell.py`/`main.py`'s Students navigation wiring, so the remaining
UI implementation was deliberately deferred pending reconciliation. No file was
reverted or repaired by this task.

## M5/M3 Assessment Framework Read-Contract Addition

Fixed a confirmed, independently re-verified read/write API contract gap
blocking any future assessment-entry UI: `GET
/api/talent/programs/{id}/frameworks/{id}` returned each competency keyed only
by `competency_id` (`FrameworkCompetency.talent_competency_id`, the parent
catalog FK), never the row's own `FrameworkCompetency.id`; no read route
exposed `TalentRubricLevel.id` at all (`get_framework_configuration`'s
`levels[]` returned only `code/label/description/order/numeric_value`). The
write route `PUT
/api/talent/assessments/{id}/competency-results/{framework_competency_id}`
(`talent_student_assessment_service.set_competency_result`) is FK-constrained
on exactly `FrameworkCompetency.id` and `TalentRubricLevel.id`. Both read
routes now additively include each row's own `id` field; no migration was
needed (both columns already exist), no permission/privacy semantic changed,
and the write route's contract is untouched. New regression:
`tests/test_talent_student_assessment_competency_results.py::test_framework_read_ids_are_accepted_end_to_end_by_the_write_route`
proves a write built purely from the new read `id` fields succeeds end to end;
`tests/test_talent_rubric_kpi_candidate_policy.py` gained a matching
rubric-level `id` assertion. Full `-k talent` regression: 483 passed, 10
skipped, no failures. This backend fix is included alongside the
M11 Talent & Potential UI work
(`routers/talent_ui.py`, `templates/talent/`, `static/css/talent.css`,
`static/js/talent.js`) that this fix is intended to unblock; no UI work
consuming these new fields was implemented in this pass.

## M10 B11-E Integrated Production Qualification

ADR 0029 governs and implements a dedicated M10-only REPEATABLE READ session/
dependency (`database.M10OrganizationAnalyticsSessionLocal`,
`dependencies.get_m10_organization_analytics_db`) for all seven Organization
Intelligence routes, backend-conditional (PostgreSQL only), with no
server-wide or other-route isolation change. All seven routes were
live-re-tested under the permanent implementation and confirmed consistent;
the two B11-D-proven mismatches (Overview Candidate, Student Drill gate/page)
no longer occur, and the five previously structurally-inferred routes
(talent-map, program-portfolio, branch intelligence, participation-overlap,
longitudinal) were independently reproduced live for the first time and
confirmed resolved.

Suppression/reconstruction concurrency was tested live with the existing
non-production `DeterministicSuppressionTestPolicy` (primary and
complementary suppression); no suppressed value became reconstructable.
Index Candidate B is finalized as NO CHANGE; statistics freshness is
finalized as an operational/runbook disposition (no code/migration change).
F1 subsequently implements the approved fail-closed production privacy,
availability, and breadth providers. That resolves the provider-code blocker,
while all other B11 release gates remain open. 14 earlier committed regression
tests were added; the full 226-test regression passed;
`tis.db` was confirmed unchanged. Independent review returned PASS WITH
NON-BLOCKING OBSERVATIONS; B11-E implementation is PASSED and checkpointable.
**As of 2026-09-09 (`docs/history/engineering-handbook/2026-09-09-b11e-live-multiworker-qualification.md`,
ADR 0028, ADR 0030), B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT
VERIFICATION ITEM REMAINING and B11 overall is CLOSED on that same basis; B12
is CLOSED. Production deployment has not occurred.**

## M10 B11-D PostgreSQL Concurrency Qualification Closure

B11-D is CLOSED after a PASS WITH NON-BLOCKING OBSERVATIONS independent
review. READ COMMITTED mixed snapshots were reproduced within one request:
Overview Candidate count 314 to 315 and Student Drill gate/page population
705 to 706. A non-permanent REPEATABLE READ experiment resolved both cases,
but permanent adoption was then PROPOSED - GOVERNANCE REQUIRED and NOT
IMPLEMENTED. B11-E subsequently governed and implemented a scope beginning
before the first database statement and spanning every M10 evidence input
through privacy/reconstruction.

B11-E subsequently live-qualified all other multi-statement routes and
suppression under concurrency. Candidate B is NO CHANGE with no index approved;
statistics freshness/ANALYZE is operational guidance. Tenant isolation remained
clean. B11-E implementation is PASSED. As of 2026-09-09, B11-E is CLOSED WITH
ONE ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM REMAINING (ADR 0028);
B11 overall is CLOSED on that same basis; B12 is CLOSED.

## M10 B11-C PostgreSQL Qualification Closure

B11-C is CLOSED. PostgreSQL 16.15 profiling of all seven M10 routes produced
durable evidence, bounded query counts across tested scales, no N+1 finding,
Index Candidate A = NO CHANGE, and Candidate B = MORE EVIDENCE REQUIRED. No
index, schema, migration, permission, privacy, or entitlement semantic change
was made. The 209-test regression passed. Memory evidence is directional local
Windows development evidence only; no production threshold, breadth limit,
commercial mapping, SLO, or memory value was selected.

B11-D subsequently completed and is CLOSED. B11-E implementation subsequently
PASSED. As of 2026-09-09, B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC
DEPLOYMENT VERIFICATION ITEM REMAINING (ADR 0028); B11 overall is CLOSED on
that same basis; B12 is CLOSED. Performance SLO, memory
ceiling, and multi-process/multi-worker qualification were subsequently
gathered and adopted per ADR 0028/ADR 0030.

## M10 B11 Production Qualification Governance

ADR 0028 records the approved B11 production-policy boundaries and now records
the F1 Owner decisions: minimum cohort 5 for P1-P7, semantic feature key
`feature.organization_intelligence`, and breadth ceilings of 1000 matrix cells,
1000 relationship results, and 1000 Program-pair results. F1 implements those
decisions through external configuration and the existing entitlement/feature-
registry architecture. Missing/false/reject/exception paths fail closed.
Plan packaging, performance SLOs, memory ceilings, and any future index remain
outside F1 and unresolved where the governing qualification still requires it.

B11-C and B11-D subsequently completed and are CLOSED as recorded above.
The F1 provider implementation is complete; B11-E is PASSED. As of 2026-09-09,
B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM
REMAINING (ADR 0028); B11 overall is CLOSED on that same basis; B12 is
CLOSED. Master merge and deployment remain blocked pending cumulative
production release qualification and a separate `dev`->`master` approval.

## M10 B0-B9 Organization Intelligence

M10 B0-B2 is implemented without an Organization Intelligence route, aggregate
query, privacy threshold, entitlement rule, schema, or migration.
`talent_org_intelligence_contract.py` provides immutable canonical Cell
identity, exact `+1`/`-1` additive Relationships, inherited M9 privacy-state
projection semantics, tenant validation, and the V01-V25 ledger.
`talent_analytics_relationship_graph.py` adds the tenant-bound canonical Cell
registry, Relationship identity/deduplication, Cell-to-Relationship adjacency,
fail-closed structural validation, and deterministic connected components.
`talent_analytics_privacy_closure.py` adds exact Fraction-based RREF,
per-coordinate uniqueness, inconsistent-system detection, monotonic bounded
component-local closure, magnitude-independent victim choice, fail-closed
analyzer handling, exact-source-only derived rates, and all-or-nothing sibling
projection. V01-V25 are executable. No real M10 Organization Intelligence or
Talent Map data can be exposed.

B3/B4 adds `talent_org_intelligence_service.py`: immutable tenant/year/
historical-Branch access context using existing permissions; fail-closed
unconfigured commercial-availability and breadth providers; normalized context
fingerprinting; enabled annual Program universe; frozen-population-only filters;
set-based Program×Branch, Program×Grade, Program/Branch/Organization totals;
permission-skipped Candidate and Identification queries; and Program-grain M8
required-period execution. All primitives share the caller's Session and never
query current Student Placement. Future serialization must accept a B2 closure
result through `PrivacyClosedProjectionSet`.

B5 adds only `GET /api/talent/organization-analytics/overview`. The closed
contract now has 14 MetricCodes and 7 MembershipGrains: B5 added
`programs_configured`, `active_programs`, and `program_configuration`, both
metrics mapped to `count`/`program_configuration` and P1. Configured means an
enabled Program annual configuration; active is exactly its subset whose
durable Program lifecycle status is `active`. The route preserves historical
Branch filtering, skips Candidate/Identification SQL without their independent
permissions, counts only `decision == identified`, and serializes exclusively
after M9 primary privacy and B2 closure.

B6 is implemented, independently reviewed, and closed after the targeted
sparse-matrix re-review passed. It adds only
`GET /api/talent/organization-analytics/talent-map`, supporting
Program-by-Branch and Program-by-Grade. `branch_program` reuses the same
canonical topology and transposes presentation only after closure. Backend
row/column/authorized-scope totals participate in the graph. It supports the
approved frozen/completed/started/Candidate/identified counts and eligible
rates, rejects Program-level required Period execution, and adds no ranking,
universal score, schema, migration, UI, or B7+ route. Production privacy,
commercial availability, and breadth providers remain fail-closed.
The sparse-total fix uses the exact same authoritative numeric child set for
total arithmetic and graph terms, excluding rectangular `no_data` display
coordinates without treating them as zero. Empty totals stay `no_data`; one-
child totals keep an explicit two-term equality. B2 itself is unchanged.

B7 implements Program Portfolio and one-Branch Intelligence. Portfolio uses
Program/Academic-Year common facts and required-Period execution only at that
grain. Branch Intelligence filters frozen Branch before grouping, shares B6
Program/Branch identities, and excludes execution. Candidate/identified fields
are permission-omitted. Both routes use breadth and closed projections. Grade
breakdown, ranking, and scores remain unimplemented.

B8 implements Participation Overlap as distinct Student intersections across
Open/Closed frozen Cycle participation. It adds the sole governed
`participation_overlap` P2 count metric at `program_participation` grain,
deduplicates Program/Student participation before one set-based self-join,
applies historical Branch scope before intersection, and uses one symmetric
canonical Cell per normalized Program pair. Diagonals are distinct Program
participants; absent participation basis is `no_data`, while an authoritative
empty intersection is factual zero subject to privacy. No overlap sums,
Candidate/Identification overlap, ranking, Talent Breadth/score, Student data,
schema, migration, UI, AI, or B9+ route is implemented.
Its initial independent review identified a canonical pair-index mismatch when
Program name order differed from numeric ID order. Construction and every
lookup now use one explicit numeric canonical-pair helper, preserving name/id
presentation order while sharing one Cell/privacy decision across both matrix
orientations. Targeted independent re-review passed; B8 is CLOSED.
Its committed/pushed implementation remains part of current dev.

B9 adds only `GET /api/talent/organization-analytics/students`, the first
M10 Student-identifiable route. It requires `talent_analytics.view` AND
`talent_analytics.view_students` (true AND composition), derives Student
inclusion only from frozen Cycle population context in the authorized
tenant/AY/historical-Branch/Program scope (never current Placement), and
treats every identifiable row as P7 through one gate-level
`student_drill_population`/`count`/`distinct_student` Cell fed by
`COUNT(DISTINCT student_id)` and run through the same B2 closure pipeline (no
per-Student additive relationship graph). Candidate/Identification fields
are independently permissioned and query-skipped, not response-filtered;
Learner Profile access exposes only an advisory `can_view_learner_profile`
hint. One top-level row exists per Student with deterministic frozen
Program/Cycle contexts; pagination is over distinct Students (limit 25/max
100, `has_more`, no `total_count`) and breadth precedes identifiable queries. No
direct Student-ID filter is exposed. No schema, migration, permission,
entitlement, longitudinal/B10, UI, or AI capability was added.
The remediation passed targeted independent re-review; B9 is CLOSED.
Its committed/pushed implementation remains part of current dev.

ADR 0027 records the B10-A "Longitudinal Organization Intelligence"
architecture as an approved governance decision only, following independent
governance review ("approve with required amendments"). B10 itself remains
NOT IMPLEMENTED - no route, query, schema, migration, permission, or
entitlement was added by this decision, and B9's status above is unchanged.
The approved contract: one Program, one Academic Year (`AcademicYear.
year_name` stays descriptive only, never chronology authority), ordered M8
`TalentPlannedEvaluationPeriod` slots as the sole ordering authority (Period
= presentation/order, optional linked Open/Closed Cycle = evidence,
consistent with the existing `uq_talent_assessment_cycles_period`
constraint), exactly nine of the fourteen existing `MetricCode` values
(`frozen_eligible`, `completed`, `completion_coverage`,
`assessment_started`, `started_coverage`, `candidate_count`,
`candidate_of_eligible`, `identified_count`, `identified_of_eligible`), one
metric per response, `comparable`/`not_comparable` states with no growth
language, and no server-computed delta/percent-change between points. See
`docs/adr/0027-b10-longitudinal-organization-intelligence-contract.md`.

B10-B implements the ADR 0027 contract as
`GET /api/talent/organization-analytics/programs/{program_id}/longitudinal`
in `talent_org_longitudinal.py` (the seventh Organization Intelligence
route). It reuses `resolve_access_context`/`authorized_program_universe`/
`resolve_filters`/`frozen_membership_query` unchanged, fetches the single
governed M8 Plan (`uq_talent_annual_evaluation_plans_config` guarantees at
most one Plan per Program/Academic-Year) and its ordered Periods left-joined
to their linked Cycle in one bounded query, and aggregates population/
completed/started/Candidate/identified counts grouped by Cycle id in one
additional bounded query each (never one query per Period). Point status
uses the exact verified lifecycle values: a cancelled Period is
`no_data`/`cancelled_period`; a missing linked Cycle is
`no_data`/`missing_cycle`; a linked Draft Cycle is
`no_data`/`cycle_not_authoritative`; an authoritative (Open/Closed) Cycle
with zero frozen population is `no_data`/`no_frozen_population`; a Program
with no Plan yields an empty, non-fabricated `points`/`comparisons` series.
An unlinked/ad-hoc Cycle is structurally excluded because it is only ever
looked up by Period-linked `cycle_id`. Every Cell/component uses
`relationships=()` - there is no same-point or cross-time additive
Relationship anywhere in this module, so no `delta`/`change`/
`percent_change` field is computed or exposed; rates reuse
`derive_exact_rate`/`project_safe_derived_payload` unchanged. Adjacent-Period
comparisons are `comparable`/`not_comparable` only, evaluated in the ADR's
governed precedence (missing/cancelled/no-population reason, then
`privacy_protected`, then `framework_changed`, then `comparable`); the five
Framework-independent metrics stay comparable across a Framework change,
while the four Candidate/Identification metrics become
`not_comparable`/`framework_changed`. Candidate/Identification SQL is
skipped entirely unless both the selected metric requires it and the actor
holds the corresponding secondary permission. Breadth is enforced (Period
count, 1/2 components, `prospective_pair_count = periods-1`,
`relationship_estimate=0`) before the aggregate queries run. B10-B is
implemented and unit/integration tested. Independent security/privacy review
passed with non-blocking observations; B10 is CLOSED. B11, B12 (closeout),
and every ADR 0027 "Deferred
capabilities"/"Production gates" item remain unimplemented/open.

B11-A (read-only qualification) is completed: it confirmed the privacy,
commercial-availability, and breadth-policy provider seams used by all 7
M10 routes existed with no production implementation and correctly failed
closed at that checkpoint. F1 subsequently implements the governed providers.
B11-B adds safe, non-sensitive operational observability around
all 7 existing routes via a new dedicated logger in
`talent_organization_analytics_observability.py` (separate from the
immutable business/security audit trail in `audit.py`) plus telemetry
wiring in `routers/talent_organization_analytics.py`. Recorded signals are
a bounded allowlist only - `projection_family`, `outcome`, route latency,
safe structural counts reused from each route's own existing breadth-policy
inputs, and each provider's coarse outcome (missing/available/unavailable/
exception for availability; missing/evaluated/exception for privacy;
missing/allowed/rejected/exception for breadth) - never a Student
identifier, raw analytical value, privacy threshold, suppressed value,
Candidate/Identification decision, or `delta`/`change`/`percent_change`/
`total_count`. Every existing fail-closed HTTP outcome is unchanged
byte-for-byte, and a telemetry emission failure is swallowed internally and
can never affect the HTTP response. Query-count instrumentation is
explicitly deferred to a future "B11-C profiling" phase. B11-B is
implemented and unit-tested (`tests/test_talent_organization_observability.py`,
22 tests, full existing B5-B10 regression suites green). Independent
security/privacy review passed with non-blocking observations; B11-B is
CLOSED. No schema, migration, permission, entitlement, privacy threshold,
or production breadth limit was added by B11-B; F1 later adds the governed
provider decisions without schema or permission changes. PostgreSQL performance/concurrency/
memory qualification was subsequently gathered. As of 2026-09-09, B11-E is
CLOSED WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM REMAINING
(ADR 0028); B11 overall is CLOSED on that same basis; B12 is CLOSED.

The pre-B2 hardening gate is implemented: `metric`, `measure_component`, and
`membership_grain` use the approved closed string-backed enum vocabularies and
serialize to their exact governed strings; unknown values are rejected.
`rate`/`percentage` remain derived disclosures, not identity components.
Relationship coefficients require an actual Python `int` and exactly
`+1`/`-1`, so bool, float, `Fraction`, `Decimal`, null, and strings fail.

## M9 Deterministic Talent Analytics Implemented (Committed/Pushed On dev)

M9 adds a read-only, privacy-gated `/api/talent/analytics` aggregate API
(context/overview/rubric-distribution/kpi-distribution/competencies/
breakdowns per branch-grade-section/period-comparison/students) strictly
inside one Program + one Academic Year, over the existing frozen
`TalentAssessmentCyclePopulationMember` historical scope. See "Deterministic
Talent Analytics (M9, Committed/Pushed On dev)" in
`docs/AI_PROJECT_CONTEXT.md` for full architecture: the `Cell`/`Group`
privacy-pipeline model, the mandatory `apply_primary_privacy` ->
`run_complementary_suppression` ordering (now statically regression-guarded),
the Product-Owner-approved fail-closed `coarsened` contract, the enforced
`competency_id` filter, the documented dead/unreachable
`candidate_policy_changed` comparability branch, and the coverage-bundle
privacy fix below.

A second remediation pass fixed a HIGH-severity defect of the same
reconstruction-risk bug class, relocated past the call-ordering guard:
`/rubric-distribution` and `/period-comparison` each privacy-evaluated only
one headline `frozen_eligible` `Cell` and then serialized the entire raw
per-status coverage bundle unconditionally once that one Cell passed -
`/rubric-distribution` did not evaluate the coverage bundle at all, and
`/period-comparison`'s per-side bundle only gated on the total. Both now call
one shared, `/overview`-pattern-derived authority,
`talent_analytics_service.build_privacy_safe_coverage_bundle`, which
independently privacy-evaluates `frozen_eligible` and all 5 per-status
counts as one `Group`, runs complementary suppression across them, and only
publishes the full per-status breakdown (with derived `assessment_started`
and percentages) when every cell in the group is independently visible -
otherwise the whole bundle collapses to a compact state-only projection with
no raw sibling field. A recursive runtime regression test proves no
non-visible-state dict anywhere in the serialized response carries a raw
coverage-shaped sibling field, in addition to the existing static ordering
guard.

New Administrator-only default permissions are `talent_analytics.view` and
`talent_analytics.view_students`. Production privacy-provider construction is
configuration-driven through `talent_organization_analytics_providers.py`.
The provider is returned only when the deployment's governed environment values
match the approved Release 1 policy values; missing or invalid configuration
fails closed. Live PostgreSQL performance/concurrency validation remains a
separate release gate.
Focused coverage is `tests/test_talent_analytics.py`. M9 is committed and
pushed on `dev` at `23ade9a7c6166197140b48a3edbfac849396d580` (commit `feat:
add deterministic talent analytics`). It is not deployed, not production-
released, and not merged to `master`. No Talent Score/Index/Potential Rate,
Talent Map, export, AI, or UI
exists. M10 B0-B5 exists as described above, while other M10 aggregate routes,
Learning Style, and Student evidence remain out of scope.

## M8 Annual Evaluation Plan And Periods Implemented

Migration `20260905_001_talent_annual_evaluation_plan_period_foundation` adds
annual Plan and ordered Period tables, the scoped Program/year/config keys,
and nullable unique Period linkage on Assessment Cycle. Existing Cycles remain
ad-hoc with NULL linkage; no history is inferred. Services and `/api/talent`
routes implement create/read, Period planning, activation, cancellation,
closure preflight/close, rollover, eligible Period selection, and atomic
link/unlink. Plan revision and Cycle revision protect stale writes.

New Administrator-only default permissions are
`talent_evaluation_plans.view/manage/govern`. Every mutation is organization/
global only. Link/unlink and rollover use true AND permission composition.
Branch reads never receive Cycle projection or derived relationship/action/
warning leakage without the separate Cycle-view permission. Linked Cycle Open
revalidation follows Plan -> Period -> Cycle lock order without adding an M8
govern requirement. M9 Deterministic Talent Analytics is now implemented (see
above); M10 B0-B5 exists, while further external execution, Learning
Style, AI, and Student data remain out of scope. Live
PostgreSQL concurrency validation remains a deployment gate.

## M7 Longitudinal Learner Profile Implemented

M7 implements a read-only, no-migration Learner Profile aggregation over M1-M6
canonical history. The profile groups exact historical Assessments, Framework
Versions, Competency Results, optional persisted KPI results, Review Candidates,
and Official Identifications by stable Program and Academic Year while retaining
multiple Cycles. It uses current Student identity only for the header and never
reinterprets historical Talent semantics from current Placement or configuration.
`talent_learner_profiles.view` is a new Administrator-only-by-default base
permission. Review Candidate, Official Identification, and Educator Input each
remain absent, including their timeline events and metadata, without their own
respective view permission.
Branch scope filters each Placement by stored historical Branch and each Talent
record by frozen/persisted Branch; organization/global scope can see complete
same-tenant history. The related M1 direct placement read routes now enforce
the same historical Branch policy. M8 Annual Evaluation Plan & Periods,
Learning Style, analytics, Talent Map, AI, and profile materialization remain
deferred. Live PostgreSQL validation remains outstanding.

## M6 Review, Official Identification & Educator Input Implemented

M6 is complete following 18 approved Product Owner governance decisions that
resolved the 9 previously open questions (see "M6 Governance Review:
Decisions" in `docs/AI_PROJECT_CONTEXT.md`). Migration
`20260904_006_talent_review_candidate_foundation` adds `talent_review_candidates`
(one row per Assessment) and widens `TalentAssessmentAudit.resource_type` to
add `review_candidate`. Migration
`20260904_007_talent_review_workflow_identification_educator_input_foundation`
adds the two-state Review workflow columns to `talent_review_candidates`,
creates `talent_official_identifications` and `talent_educator_inputs`,
widens `resource_type` further to add `review_candidate_review`,
`official_identification`, and `educator_input`, and relaxes
`talent_assessment_audits.cycle_id`/`framework_version_id` to nullable so an
Educator Input audit row (whose Cycle binding is optional) can exist without a
Cycle context.

`talent_review_candidate_service.py` deterministically evaluates the exact M3
Review Candidate Policy/rules attached to a Completed Assessment's exact
Framework Version - `rubric_level_at_or_above` by `TalentRubricLevel.display_order`
(never `numeric_value`), `kpi_at_or_above` by the Assessment's persisted
`kpi_result` (never recomputed) - with `all`/`any` composition. No policy
means no candidate is inferred. Evaluation only reads existing Assessment/
Result/frozen-population data; it never writes to them. A qualifying
evaluation persists one candidate row (starting `pending_review`) with policy
identity, match mode, a deterministic SHA-256 fingerprint, and a full
evaluation snapshot; re-evaluation is idempotent and returns the existing row
unchanged. A non-qualifying evaluation still persists no `TalentReviewCandidate`
row, but is now structurally audited (assessment identity, Framework/Policy
context, `outcome=false`, fingerprint - no free text, no durable negative
entity).

The Review workflow is exactly two states, `pending_review` -> `reviewed`,
one-way, via `talent_review_candidates.manage`; it never alters assessment
evidence and never auto-identifies. `TalentOfficialIdentification` is a new
append-only decision record (`identified`/`not_identified` only - no
`deferred`/`revoked`/`superseded`/`re-identified`) that may be recorded only
once its Review Candidate is `reviewed`, exactly one per candidate
(unique-constraint- and service-enforced), via the dedicated
`talent_official_identifications.record` permission which additionally
requires organization/global access scope - a Branch-scoped actor is denied
even if granted the permission. `not_identified` is exactly as durable as
`identified`; there is no mutation/revocation/second-decision/re-identification
path anywhere. `TalentEducatorInput` is bounded qualitative Student
evidence/context (`observation`/`context`/`supporting_evidence`, <=2000
characters, non-empty) bound to SchoolGroup/Student/Program/AcademicYear/
`observed_at` plus a historical Placement/Branch snapshot - resolved from a
supplied frozen Cycle Population Member when given, otherwise from the
Student's canonical `StudentAcademicPlacement` effective at `observed_at`
(rejecting cleanly with no valid historical Placement, never falling back to
current Placement). It is append-only with `supersedes_educator_input_id`
lineage (cycle-prevention mirrors M3's Framework Version `_validate_supersedes`
walk); default reads return only the current/latest version, an explicit
history read returns the full chain, and the free-text body is stripped from
audit `before_json`/`after_json`. New dedicated Administrator-only-by-default
permission groups: `talent_official_identifications.view/record` and
`talent_educator_inputs.view/add/amend`, each independent of every other
Talent permission family. All new/changed reads use the same frozen historical
Branch discipline as M4/M5 - a current Student transfer never reinterprets
Review Candidate, Official Identification, or Educator Input access.

Deferred (explicit, not implemented): Official Identification revocation/
supersession/second decision/re-identification, a generic review-note/case-
management system, assessor assignment, Learner Profile, Development and
Support, analytics/Talent Map, AI/AI Suggested Review, and Educator Input
analytics/export/AI/attachments. Focused coverage is in
`tests/test_talent_review_candidate_foundation.py` and
`tests/test_talent_review_official_identification_educator_input.py`. Live
PostgreSQL execution remains a follow-up.

Independent review additionally closed four boundary defects: historical
Branch authorization is enforced during Educator Input create/amend;
out-of-scope direct IDs are uniformly non-enumerating; Official Identification
is composite-bound to the Review Candidate's exact historical context; and a
database uniqueness constraint prevents concurrent amendment forks. Focused
M6 coverage is 42 passing tests, and the combined M1-M6/permission/tenant/
migration/startup selection is 137 passed and 3 PostgreSQL-only skips.

## M5 Talent Student Assessment And Competency Results Implemented

Migration `20260904_005_talent_student_assessment_competency_results` adds
canonical Student Assessment and exact Framework Competency Result rows,
extends the existing operational audit, and preserves the scoped composite keys
needed for frozen-member, assessment, competency, and rubric-level integrity.
Only an Open Cycle's frozen members can receive one In Progress assessment;
all mutations use expected-revision protection. Completed requires every exact
Framework Competency result and becomes read-only. Incomplete and Insufficient
Evidence are distinct read-only terminal outcomes and do not represent low
performance or zero results.

The optional enabled Framework KPI is calculated only at successful completion
using exact integer weighted-level arithmetic: numeric rubric value times
basis-point component weight, summed over denominator 10,000 and rounded to
the nearest Framework-scale integer with ROUND_HALF_UP. The persisted result
includes method, scale bounds, numerator, canonical SHA-256 input fingerprint,
and calculation timestamp. Qualitative no-KPI Programs complete without any
numeric score. This is never a universal Talent Score or cross-Program
normalization. M5 adds Administrator-only-by-default
`talent_assessments.view/manage/complete`, frozen-Branch scope enforcement,
the `/api/talent/assessments` API, and focused SQLite coverage. Assessor
assignment, correction/reopen, Review Candidate workflow, Official
Identification, Educator Input, Learner Profile, analytics/Talent Map, AI, and
Development and Support remain deferred. Live PostgreSQL validation remains
outstanding.

## M4 Talent Assessment Cycle And Frozen Population Implemented

Migration `20260904_004_talent_assessment_cycle_frozen_population` adds the
SchoolGroup-wide `TalentAssessmentCycle` (`draft -> open -> closed`, no
`branch_id`), frozen population members, and bounded append-only operational
audit. Draft preview and Open resolve canonical Academic Placement at the
explicit `population_effective_at` against the Program Academic Year
configuration's eligible grades. Open atomically freezes the full organization
population with exact Placement/Academic Year/Branch/grade/section context and
stores a deterministic full count and fingerprint. There is no reopen,
population removal, or assessor assignment. Accepted ADR 0033 permits only
audited additive synchronization of newly eligible Students while Open.

Dedicated `talent_assessment_cycles.view/manage/view_population/govern`
permissions are Administrator-only by default. Branch authors may manage
Draft metadata but cannot Open/Close [superseded 2026-09-25 by Final Closure Part B: Cycle create/edit now also requires organization/global scope]. Governance additionally requires
organization/global scope. Population reads are separately permissioned:
Branch actors see only authorized preview/frozen Branch members and subset
counts, never the full count/fingerprint; organization/global population
readers see the canonical whole. Frozen visibility uses the member's historical
Branch, not current Student Placement. Focused coverage is in
`tests/test_talent_assessment_cycle_frozen_population.py`.

Student Assessment, assessor assignment, results, Review Candidate instances,
Official Identification, analytics, AI, late population exceptions, and UI
remain deferred. Live PostgreSQL execution remains outstanding.

## M3 Governance Closure: KPI Approval, Rubric Ordering, And Audit Granularity

`weighted_level_average` is now Product-Owner-approved as one bounded,
optional, Framework-specific KPI calculation primitive - never a universal or
cross-Program score, enabled only through explicit Framework configuration,
and requiring numeric rubric values only while enabled. Qualitative
no-KPI Programs remain first-class. `rubric_level_at_or_above` candidate
rule semantics are defined by the configured Rubric Level order
(`display_order`, lowest proficiency first), independent of `numeric_value`;
`display_order` was confirmed to safely carry both presentation order and
semantic proficiency rank with no divergence risk, so no new field was added.
`TalentConfigurationAudit.resource_type` was widened (model CHECK plus a
widening step inside the M3 migration, since the audit table itself was
created by the separate already-applied M2 migration) to add `rubric`,
`rubric_level`, `rubric_descriptor`, `kpi_configuration`, `kpi_component`,
`review_candidate_policy`, and `review_candidate_rule`; every M3 mutation now
audits its specific child resource instead of only `framework_version`,
matching the M2 `framework_competency` precedent. Candidate-policy rule
evaluation remains deferred to a later assessment milestone. PostgreSQL live validation remains
outstanding.

## Talent Program Deterministic Framework Configuration Implemented Through M3

Migration `20260904_003_talent_rubric_kpi_candidate_policy_foundation` adds
Framework-versioned configurable rubric levels, exact competency/level
descriptors, optional bounded weighted-level KPI configuration, and a bounded
declarative Review Candidate Policy. All configuration is Draft-only,
expected-revision protected, included in the Framework semantic fingerprint,
independently cloned, tenant-scoped by composite foreign keys, and recorded
through the existing append-only Talent configuration audit. Active/Retired
configuration is immutable. Qualitative Programs can omit KPI and numeric
levels entirely. Existing `talent_programs.view/manage/govern` permissions are
reused; governance scope for activation/retirement is unchanged.

No Student Assessment, evidence/result, candidate instance,
Official Identification, analytics, AI, entitlement, or UI capability is part
of M3. Focused M3 coverage is in
`tests/test_talent_rubric_kpi_candidate_policy.py`.

## Student & Academic Placement Foundation And Talent Program & Framework Foundation Implemented

Migration `20260904_001_student_academic_placement_foundation` adds `Student`
as a canonical SchoolGroup-owned identity distinct from `User`, external
identifiers, an effective-dated Academic Placement authority (no separate
Enrollment entity), and append-only audit. Migration
`20260904_002_talent_program_framework_foundation` adds `TalentProgram` as a
durable organization-owned identity distinct from Subject, annual
configuration, an immutable-once-active Framework Version lifecycle with
deterministic version allocation and one-Active-Framework-per-Program
supersession, competency lineage with version-specific framework
membership snapshots, and append-only configuration audit. Full architecture
and business-rule detail is recorded in `docs/AI_PROJECT_CONTEXT.md` under
"Student & Academic Placement Foundation" and "Talent Program & Framework
Foundation". `tests/test_student_academic_foundation.py` (13 tests) and
`tests/test_talent_program_framework_foundation.py` (15 tests) cover both
foundations, including tenant/branch isolation and permission-boundary cases.

Checkpoint A closed the permission-governance gap in both interim
implementations. `permission_registry.py` adds dedicated `students` (`.view`,
`.create`, `.edit`, `.activate_deactivate`, `.manage_identifiers`,
`.manage_placements`) and `talent_programs` (`.view`, `.manage`, `.govern`)
permission groups, replacing the temporary reuse of the `users.*` keys (for
Student) and the bare, broadly-granted `planning.edit_section` permission
(for both Student Academic Placement mutation and Talent Program/Framework
Draft authorship - the latter previously let any Branch-scoped Editor/User
actor author organization-wide Talent configuration with no Branch-relation
constraint). Both new groups are Administrator-only by default, matching the
existing `users.*` precedent; the M2 organization/global-scope gate on
Framework activate/retire and Program lifecycle transitions was already
correct and is unchanged. `routers/students.py` and `routers/talent_programs.py`
now check the dedicated keys; branch-scope-after-permission-check ordering
and non-enumerating 404/403 discipline are preserved on every route.

PostgreSQL validation (constraints, concurrent placement/framework writes)
has not been executed against live PostgreSQL for these foundations; only
SQLite-backed pytest coverage exists. No Student UI, import/merge,
Assessment, Review/Identification, Learner Profile, analytics/Talent
Map, or AI code exists yet at this point in time. (The `students.import`/
`students.export` permission keys were later registered as a governance
prerequisite only - see "Student Roster Import/Export — Permission
Registration (Governance Prerequisite, M6)" above - roster import/merge
functionality itself remained, and remains, unimplemented.)

## Planning Subject Requirement Removal (Single And Bulk) Implemented

Administrators can now remove a Planning subject requirement whether or not
it has an explicit `PlanningSubjectDemand` row. Previously "Remove demand"
only appeared for a requirement with an untouched explicit row, so a purely
legacy-fallback requirement (resolved only from the Subject catalog, with no
explicit row at all) silently had no removal action - the same teacher could
have some subjects removable and others not, for reasons unrelated to the
teacher. `routers/planning.py` classifies every requirement as `removable`
(untouched explicit row), `permanent` (Curriculum-Adjustment-touched, shown
with an explicit "Protected" explanation instead of a hidden action),
`fallback` (no explicit row - now removable by creating an explicit
`is_active=False`/`weekly_periods=0` suppression row; unlike a Curriculum
Adjustment retirement, this row sets only `created_by_user_id` and leaves
`updated_by_user_id` NULL, so it stays classified `removable`/setup-only
rather than immediately becoming permanent), or `not_found`.

The customer-facing action is "Remove Subject Requirement" (single, per row)
and a checkbox-selected removal action at
`POST /planning/subject-requirements/remove`. Bulk removal is atomic:
every selected target is validated and scope-checked first, and if any is
protected, invalid, or out of scope, nothing is removed and every blocked
target is named with its reason. Confirmation dialogs precede both single
and bulk removal. Each expanded section now places **Select all** beside a
trash-icon action whose label changes to the singular or exact selected count;
the page-level action mirrors that selection state. Selection can still span
multiple sections in one request. Teacher assignments, timetable data, and Curriculum
Adjustment audit records are never touched by this action. The existing
`GET /planning/subject-demand/delete/{demand_id}` route from the prior round
remains available, superseded in the rendered UI, for clearing an active
untouched setup row. An inactive zero-period setup suppression with no
Curriculum Adjustment history no longer blocks an otherwise-empty section:
deletion removes that exact scoped artifact and the section atomically. Active
demands, permanent demand history, assignments, timetable/calendar/rule
dependencies, and all other existing guards still block.

## Cline And Three-Agent Development Pool

Codex, Claude Code, and Cline/ClinePass are approved TIS development agents.
Cline's repository entry points are `.clinerules/tis.md` and
`.cline/skills/tis-kms-developer/SKILL.md`. They require governing KMS onboarding,
implementation inspection, isolation/RBAC and database safety, minimal diffs,
proportional tests, task-level KIA, KMS sync/check, and deployment reporting.

The master conversation balances tasks by complexity, specialization, risk,
independent-review value, and current usage/load, without permanent assignments.
See [Project Governance](engineering/PROJECT_GOVERNANCE.md) for the allocation policy and
[AI Coding Workflow](engineering/AI_CODING_WORKFLOW.md) for Cline setup/invocation.
This configuration changes no application, schema, or production behavior.

## Claude Code KMS Integration

The repository now includes root `CLAUDE.md`, a reusable project skill at
`.claude/skills/tis-kms/SKILL.md`, and a specialized subagent at
`.claude/agents/tis-kms-developer.md`. This gives Claude Code a native entry point
to the same KMS onboarding, scope safeguards, worktree preservation, validation,
and completion reporting already required by `AGENTS.md`; it does not change
application, database, deployment, or customer behavior.

## Return-To Reopen-On-Load UI Pattern Implemented

A shared `redirect_utils.py` module (`safe_redirect_path`,
`redirect_with_notice`, `redirect_with_error`, moved out of `main.py` with
existing callers unchanged) and a shared `static/js/reopen-on-load.js`
(loaded globally from `base.html`) finish wiring the existing `return_to`
convention so a server-rendered action inside an expanded element can land
the user back on that same element, scrolled into view, instead of
collapsing it. Planning's "Remove demand" action is the first and, for now,
only consumer: each section's `<details>` carries a stable id, the link
passes `return_to` to that section's fragment, and the route's in-place
blocked-render outcomes set the same reopen target without a redirect. No
SPA conversion, no new browser storage. Subjects and Teachers were not
changed; the pattern is available for them to adopt later.

## Planning And Subject Delete Dependency Guards Implemented

Planning section delete and Subject delete/Bulk Delete now run a read-only
dependency check before any mutation, naming every blocking category in a
customer-safe message instead of raising an unhandled `IntegrityError`.
Planning section delete checks `TeacherSectionAssignment`,
`PlanningSubjectDemand`, `TimetableEntry`, `TeacherSchedulingRuleTarget`,
`CalendarEvent`/`CalendarEventSectionTarget`, and section-scoped
`SubjectDistributionRule`; `TeacherSectionAssignment` is now a blocker instead
of being auto-deleted. Subject delete/Bulk Delete additionally check
`TimetableEntry`, `CurriculumAdjustmentAudit`, and `SubjectDistributionRule`
subject-code references that previously had no application-level check.
Bulk Subject delete is atomic: any blocked Subject stops the whole batch and
is named with its reason.

Planning subject demand is classified removable or permanent using the
existing `updated_by_user_id` column: Curriculum Adjustment always sets it,
the one-time setup backfill never does. A never-touched row is pure setup
scaffolding and can now be hard-deleted through the new "Remove demand"
action on the Planning page (`GET /planning/subject-demand/delete/{demand_id}`),
after which the section or subject becomes deletable; a row Curriculum
Adjustment has ever touched remains a permanent, honestly-explained blocker.
Published/archived timetable placements follow the same principle without a
new action. No archive/closed/inactive lifecycle, broad schema change,
migration, or cascade deletion was introduced.

## Professional Timetable Lifecycle UX Implemented

The workspace now identifies CURRENT PUBLISHED, editable working Drafts, and
read-only history with visible Draft → Validate → Approve → Publish guidance and
audit facts. Safe actions distinguish copying published/history into a working Draft
from starting an empty Draft, and Generate/Regenerate language makes Draft-only
effects explicit. The active pointer remains unchanged until approval and publication
succeed. Mutation/version errors remain backward-compatible and now add canonical
conflict evidence plus stale-revision refresh remediation. No schema, solver, or
Workflow behavior changed.

## Guided Curriculum Adjustment UI Implemented

Stage 5 adds the permission-gated administrator workflow from Planning and Subjects through scope, change, preview, teacher decisions, final confirmation, and success. It reuses the deployed Stage 3 preview and Stage 4 atomic apply APIs, preserves selections where safe after a refreshed review, and offers timetable/regeneration navigation without automatic generation.

The transfer contract now carries the requested period count instead of deriving an absolute source result from `Subject.weekly_hours`. Subjects also reflects effective Planning weekly periods for Current/New sections, including a section breakdown when values differ.

Curriculum Adjustment now also supports reduction without transfer. Subject Details exposes effective Planning periods and a permissioned prefilled reduction entry point; original catalog periods remain separately editable defaults and are not operational Planning authority.

## Atomic Curriculum Adjustment Apply Implemented

Stage 4 implements a service-owned, one-commit curriculum adjustment transaction
behind dedicated `curriculum.adjust`. It revalidates the reviewed preview fingerprint
under exact-scope locks, rejects active timetable generation and all unresolved
teacher/rule/lock conflicts, applies section-specific source/target demand and the
explicit teacher decision, retires zero demand and its section rule, marks the
unpublished Draft stale, clears approval, and records a durable audit.

Migration `20260829_001_curriculum_adjustment_apply_foundation` adds the audit ledger
and duplicate-fingerprint guard. No guided UI or automatic regeneration is included;
published timetable versions and the active pointer are untouched.

## Curriculum Adjustment Preview Implemented

Stage 3 provides a read-only curriculum adjustment preview service and
`POST /planning/curriculum-adjustments/preview`. Grade, selected-section, and all-
active-use scopes are exact-tenant and Current/New only. Preview output includes
per-section demand transfer, current and suggested teachers, capacity projections,
scheduling-rule and grouped-configuration impacts, blockers/warnings, Draft stale/
regeneration impact, and a deterministic stale-confirmation fingerprint.

No demand, teacher assignment, timetable version, placement, active pointer, or
published history is changed. Apply, teacher confirmation, atomic write, and
regeneration workflows remain future stages.

## Explicit Planning Subject Demand Foundation Implemented

Migration `20260828_004_planning_subject_demands_foundation` adds normalized
`planning_subject_demands` records for section-subject weekly periods. Current/New
Planning sections are backfilled from grade-matched Subjects in the same branch and
academic year. The operation is idempotent; composite scope foreign keys and an
active-row partial unique index protect integrity while allowing retired history.

`planning_subject_demand_service.py` provides exact-scope explicit-first resolution
and legacy fallback, including authoritative inactive rows that suppress fallback.
Stage 2 now routes Planning calculations, teacher workload, timetable readiness,
workspace, snapshots and generation inputs, Subject Scheduling Rule arithmetic,
and required-hours reports through that authority. Missing explicit rows retain
legacy fallback during transition. Published timetable rows are untouched.

## Central Tenant Report Branding Implemented

Tenant-facing operational exports now resolve logo assets through
`tenant_report_branding.py`, which delegates to the existing branch/organization-
scoped branding slots and returns configured tenant logos only. Timetable PDF/XLSX,
academic-calendar PDF, and observation PDF generation share this authority. When
no tenant logo is configured, exports retain their normal report title/header but
render no logo; they never substitute the TIS product mark. Application UI,
login/product, public/platform, and internal platform-owner branding are unchanged.

## Subject Scheduling Rules UI Implemented

The Timetable Settings page presents a grade-first Subject Scheduling Rules table
sourced automatically from Planning. `planning_scope_service.py` supplies one
branch/year-scoped Current/New PlanningSection source to its main/copy grade
selectors, section overrides, the timetable workspace section filters, and directly
related calendar/grouped section choices. Global, non-operational placeholder, and
Subject-catalog-only grades are excluded. Only the selected grade's compact Subject,
read-only Weekly, Current Pattern, Status, and Edit columns are shown, with optional
subject search. The modal uses native closed-dialog behavior on page load and opens
only after Edit populates the selected Subject + Grade rule; Cancel/Close closes it.
Its compact two-column Session Structure aligns double-block/single-session steppers
above a full-width automatic total, while conditions use a balanced two-column grid.
Two-period presets and progressively disclosed advanced settings remain. A Section Overrides list
preserving Stage 1 section-over-grade-over-branch-default precedence, Copy
Rules From Grade (name-matched across grades, skipping arithmetic mismatches),
and Reset To Default (removes only the grade-level row). New routes
`/system-configuration/timetable-settings/subject-rules`
(save/reset/clear-override/copy) reuse the existing `timetable.manage_settings`
permission, remain tenant/branch/year-scoped, and never mutate Planning
weekly totals. `subject_distribution_rules_ui.py` re-validates arithmetic and
feasibility authoritatively before any write. Existing legacy subject-code mappings
and Swimming/grouped JSON remain unchanged but are collapsed inside an Advanced /
Legacy area; Non-Teaching Blocks management is unchanged. Newly
saved/updated rules take effect the next time a Draft Timetable snapshot is
created, through the unchanged Stage 2 resolution/snapshot pipeline; no
already-created snapshot is altered.

## Subject Distribution Rules Generation Wiring Implemented

The resolved Subject Distribution Rule (section over grade over branch
default, `None` for legacy fallback) is now embedded per Planning demand in
the schema-v3 snapshot at creation time; a later rule change never alters an
already-created snapshot. The problem builder carries the resolved rule per
demand, exposes true physical period adjacency per slot, and runs the
arithmetic/feasibility validator as a final pre-solve defense
(`distribution_rule_invalid`). CP-SAT now models explicit double-block starts
and single sessions, channels every occupied period to exactly one session,
and enforces the configured block and single counts exactly. Separate sessions
may touch (including double-plus-single three-period runs and two-double
four-period runs), while physical interruptions break doubles and overlapping
session membership remains impossible. Redundant daily session/load channeling
strengthens daily-coverage propagation. CP-SAT also enforces generalized daily-coverage/spread/max-per-day/
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

Authorized administrators can queue Generate or Regenerate from structurally
complete current inputs. A stale existing Draft is reported as `stale_input` /
Draft Needs Regeneration without becoming configuration-incomplete: it may run a
fresh feasibility verification, then regenerate only after the current fingerprint
is verified. The stale source remains versioned and unpublishable, and obsolete-run
messages from older authority fingerprints do not replace the current state.
Regeneration eligibility is based on the current Draft's lifecycle and populated
placement arrangement rather than creation origin: eligible manual, generated,
and regenerated Drafts regenerate, while empty starters generate and active or
historical versions remain excluded. A durable hard-only feasibility Workflow uses the same immutable snapshot/problem builder and independent validator before full optimization. Its validated solution is cached in `timetable_feasibility_verifications` by exact tenant scope and full input fingerprint; only Feasibility Verified enables generation. Full CP-SAT optimization uses that solution as a hint and validated timeout fallback, while any authority fingerprint change invalidates reuse. A separate OR-Tools CP-SAT execution environment uses immutable
schema-v3 input, durable lease/heartbeat/recovery state, exact demand and collision
constraints, Planning/HRT teacher authority, canonical teaching slots, and fixed
locks. A solver-independent validator and final fingerprint/source-revision check
gate atomic creation of one unpublished `publication_ready` version. Regeneration
keeps its source unchanged and enforces the approved unlocked-lesson difference.
The default regeneration difference is 25 percent of unlocked source placements,
rounded up. Infeasible diversity is reported explicitly without weakening hard rules.
The active/published pointer is never changed by generation.

The Workflow worker now reaches the existing CP-SAT solver and its diagnostic
profiles through `timetable_solver.py`, a solver-neutral adapter boundary. CP-SAT
remains the only Release 1 production implementation. Problem construction,
independent validation, and atomic persistence remain separate authorities.

Planning-to-timetable demand now passes through
`timetable_requirement_projection.py`. The read-only projection preserves
explicit-first demand, authoritative zero/retirement, legacy fallback only when
no explicit row exists, scoped teacher authority, and deterministic internal
identity/provenance. Schema-v5 snapshots freeze the projected requirements;
schema-v3/v4 generation snapshots remain readable. No new table, editable demand
authority, API, or migration was added.

Timetable conflict evidence now passes through `timetable_conflicts.py`.
Readiness exposes additive safe conflicts beside its unchanged blocker/warning
fields; feasibility exposes them beside unchanged diagnostics; generation-run
payloads derive durable conflicts from existing terminal status/category/message;
and the independent validator returns canonical conflicts beside legacy errors.
Internal requirement and solver correlation never appears in public payloads.
No conflict persistence table or migration was added.

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

- Student & Academic Placement Foundation and Talent Program & Framework
  Foundation have no PostgreSQL validation yet (constraints, concurrent
  placement/framework writes); only SQLite-backed pytest coverage exists.
  Neither has a UI, import/merge, or any Rubric/KPI/Assessment/Review/
  Learner-Profile/analytics/AI code, which remain future milestones.
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

## Talent Program Criteria UI Simplification

Owner direction removes Program Criteria from the normal Talent setup and Student Assessment workflow. The Program setup UI no longer exposes Program Criteria configuration, and a completed Student Assessment no longer exposes a manual "Check Program Criteria" action. Existing backend Review Candidate/Official Identification records and historical data are preserved; this change does not delete schema or historical evidence.

## Student Single And Bulk Delete

The Students list now exposes permission-gated single Delete and checkbox-based Bulk Delete. Both use the canonical Student service; no client-side deletion authority exists. Hard deletion is allowed only before Academic Placement or Talent history exists, and bulk deletion is all-or-nothing when any selected Student is blocked. The new permissions are `students.delete` and `students.bulk_delete`; organization/global scope is required for the destructive action. Historical Student/Talent evidence is never cascaded away.

## Permission-Controlled Student Actions And Evaluation Period Selection

Student Delete and Bulk Delete are now first-class System Configuration permissions (`students.delete`, `students.bulk_delete`) and remain backend-enforced. Evaluation Period selection for entering Student Assessments is now separately permissioned as `talent_evaluation_plans.select_period`: Administrator receives it by default; other tenant roles are disabled by default, the UI renders the entry action disabled without it, and the Cycle-to-Period link API requires it. The role-permission configuration remains the owner-controlled override mechanism. The disposable Talent analytics seed now uses Arabic names written with Latin characters and retains its 10-Student Grades 3-5 analytics coverage.

## Grade-Scoped Rubric Structure And Administrator History Delete

Talent rubric authoring now follows `Grade -> Competency -> Level -> Achievement Description`. Framework competency membership has an optional Grade scope added by migration `20260911_002_talent_framework_competency_grade_scope`; NULL remains the backward-compatible all-Grade value. The existing Grade-specific descriptor table remains the description authority at Competency x Level x Grade, with generic descriptor fallback for legacy/unscoped Frameworks. Program setup groups content by Grade and only Grade-applicable competencies are shown in Student Assessment. Compact Talent result surfaces use the ordered rubric number while retaining accessible label text and an order-derived low-to-high visual progression.

Student Assessment Evaluation contexts are ordered by the linked Annual Evaluation Plan Period `sequence`, fixing cases where a later-created Term 2 appeared before Term 1. Creation/id ordering is used only for legacy unlinked Cycles.

Students now also have a separately permissioned force-delete-history path. `students.force_delete_history` is Administrator-default and configurable through System Configuration. The Students UI first previews historical blockers; without the permission the delete remains blocked, while an authorized actor must explicitly confirm deleting the Student together with Academic Placement/Talent history. Normal single Delete and Bulk Delete retain their existing history-protecting semantics. Student row Open/Delete action icons are rendered at a compact 13px size.

## Talent Grade-First Evaluation Workflow Rebuild

The Owner-directed Talent evaluation-process rebuild is implemented on `dev`. Program creation/editing is focused on Program identity plus eligible Grades only. The Programs table exposes a distinct Rubric action. Opening Rubric presents eligible Grades as independent collapsible sections using the Owner-confirmed hierarchy **Grade -> Competency -> Competency-owned Rubric -> Levels**. Each competency can create its own rubric name and ordered levels/descriptions. The old one-shared-rubric-per-Framework rule is retained only for legacy read/migration compatibility; migration `20260911_004_talent_competency_specific_rubrics` enables exact competency ownership. Saving returns to a compact Program/Rubric overview.

ADR 0036 governs re-evaluation semantics. `TalentStudentAssessment` carries `is_current`, `reassessment_of_assessment_id`, and `evaluation_context_cycle_id` via migration `20260911_003_talent_assessment_reassessment_attempts`. Re-evaluation is triggered by actual Student-facing rubric-content changes for the Student's recorded Grade, not by a no-op Framework clone. Starting re-evaluation preserves the completed historical attempt and creates a new current attempt on the newer exact Framework while retaining the original Evaluation/Term identity. New Students in that Evaluation also start on the newest saved assessable rubric. Current-result analytics project the replacement attempt into the original Evaluation context and exclude the private replacement Cycle as a second population row.

Production Results & Analytics still depends on governed external provider configuration under ADR 0028. The implementation already contains configuration-driven privacy-provider resolution and approved-value validation; missing Render environment configuration continues to fail closed rather than exposing unsuppressed indicators.

## Talent Evaluation Workflow, Review, Results, And UI Consolidation

The Owner-approved Talent consolidation is implemented on `dev` under ADR
0036, ADR 0037, and ADR 0038.

Rubric authoring is Grade -> Competency -> competency-owned Rubric -> ordered
Levels. New competency rubrics do not inherit assessed legacy shared-rubric
levels automatically. Authors may explicitly copy level structure from another
competency in the same Draft, with optional descriptions; copied data is
independent afterward.

The canonical Overall Program Result is now the arithmetic mean of selected
rubric ranks on one coherent Program scale (for example `4.4 / 5`). All
applicable competency rubrics must use the same level count before completion.
A normalized percentage may be derived for visual bars only. Different Programs
remain separate and are never combined into one universal Student Talent score.

Student Assessments are organized as Evaluation Period -> Programs -> Students.
Repeated Evaluation labels are grouped once. The selected Program/Evaluation
shows all live-placement eligible Students in authorized scope with Not started,
In progress, Completed, or Re-evaluation required states. Re-evaluation continues
to preserve immutable historical evidence and original Evaluation identity.

Talent Review now includes all current completed Assessments, with Review
Candidate, review status, and Official Identification shown independently.
Assessment completion evaluates any existing deterministic Review Candidate
policy, while no-policy/non-qualifying completed Assessments remain visible.

Program settings surface the existing Annual Evaluation Plan Periods alongside
eligible Grades. No duplicate scheduling persistence is introduced.

Results & Analytics adds privacy-safe competency rank averages and selected
Program average summaries, keeps Branch/Grade/Program organization analytics on
the existing M9/M10 privacy-closed providers, and exposes separate per-Program
Student results through the governed Student drill/Students Across Programs
matrix. Official Identification remains a human decision; Learning Style remains
context only and is not a Talent score input.

The Talent UI has stronger semantic icons/status color, richer Evaluation,
Student, Review, and result surfaces, and responsive low-to-high result visuals.
The Programs list uses a bounded summaries endpoint instead of N+1 per-Program
setup requests. A selected Program is fetched directly, its independent setup
reads are parallelized, and routine Program/rubric saves perform targeted
Framework/configuration or Program refreshes rather than a full workspace
reload. Hash-only wizard navigation and Save Rubric reuse the current bounded
cache without network reads.

Evaluation Plan mutations keep existing content visible and re-read only
Plan/Cycle data. Student Assessment detail loading collapses dependent reads into
one parallel batch after the Assessment is resolved, and an explicitly selected
Evaluation loads its eligible Student roster in parallel with the operational
Assessment/context reads. Full loading is reserved for true initial/context
loads or explicit recovery.

No new schema migration is introduced by this consolidation.

## Talent & Potential Owner Acceptance-Testing Correction Pass (2026-09-12)

A focused UI/UX correction pass over the already-governed ADR 0039 Competency
+ KPI + Level model, driven directly by Owner acceptance testing on top of
pushed commit a173555. This pass changes no eligibility gate and no
architecture; it corrects builder rendering, disclosure, navigation, and
capitalization defects.

Delete Competency is now genuinely always available in the Competency, KPI &
Level builder for every current build - new-from-scratch, previously saved, or
based on a historically-used Framework. Investigation found the true root
cause was not a hidden/blocked action but a rendering bug: a Competency saved
with no explicit Grade on a genuinely new draft Framework
(`framework.in_use_by_assessments === false`) never matched any Grade section
in `rubricGradeSections` at all, so the entire Competency row - and its Delete
action - never rendered. The fix treats "no Grade" as "applies to all eligible
Grades" only for a Framework with no Assessment history yet; a no-Grade
Competency on an already-used Framework remains legacy/pre-migration data and
still stays out of new-Grade authoring, preserving the existing historical
protection. Deleting a Competency (direct on a mutable draft, or via the
existing version-safe clone-then-delete path on an immutable/active Framework)
removes only the current KPI, Levels, and descriptors; completed historical
Assessment evidence is never altered. Both paths now show one unified
confirmation message so the Owner is never asked to reason about Framework
versions to remove a Competency from future setup.

Each Competency card in the builder is now an independent, initially-collapsed
disclosure (native `<details>`/`<summary>`, keyboard-operable, no manual
`aria-expanded` required) showing only a compact header - name plus a
"N KPI · N Levels" count - until the Owner opens it; Grade sections remain
their own independent disclosures as before.

The opened Student Assessment editor now shows an obvious "← Back to
Students" action that returns to the Student Assessments list for the exact
same Academic Year, Program, and Evaluation/Cycle context the Assessment was
opened from - never the Talent landing page. The Assessment editor itself is
otherwise unchanged in this pass.

Talent & Potential capitalization was corrected to consistent Title Case for
Competency/Competencies, KPI, and Level/Levels counters and section/column
headings (e.g. "3 Competencies", "5 Levels", "KPI Overview", "Assessment
Status"), while normal explanatory sentences remain in ordinary sentence case
by design.

The Owner-supplied Ghars sidebar symbol-only asset
(`talent-ghars-symbol.png`) named in this correction request was not actually
present in this environment (confirmed by a full filesystem search); the
sidebar branding swap to that asset is deferred until the file is supplied,
and the current Ghars symbol-and-text sidebar branding from the prior
corrective pass is unchanged. No backend Python files were touched in this
pass, and no new schema migration is introduced.

## Talent & Potential UI Action-Placement Correction (2026-09-12)

A further Owner-driven interaction-pattern correction on top of the
acceptance-testing pass above. Edit and Delete for every created Competency,
KPI, and Level item are now compact icon-only buttons (pencil = Edit,
trash = Delete) placed immediately beside that item, replacing all visible
action text ("Edit Competency", "Delete Competency", "Edit KPI",
"Delete KPI", "Edit Level", "Delete Level"). Each icon button is a real
`<button>` with an `aria-label` and matching `title` naming the exact item
it affects (e.g. "Delete Mental Calculation", "Edit Mental Calculation level
Beginning"), so there is never ambiguity about which row an action targets,
and it inherits the workspace's existing keyboard focus-visible styling and
a compact but sufficient (36px) hit target.

This applies uniformly to both the primary Grade -> Competency -> KPI ->
Level accordion and the older parallel flat-table "What we assess" wizard
view, so the pattern reads the same wherever these actions are reachable.
The Competency header in the accordion also gained an Edit icon (it
previously exposed only Delete there) by surfacing the existing
name/description edit capability already used elsewhere in the workspace -
no new backend behavior was introduced.

Add actions are deliberately unchanged: "+ Add Competency", "+ Add KPI",
"+ Add Level", and "Copy Levels From..." remain visible text and stay in
their existing structural position (the Grade section for adding a
Competency, inside a Competency for adding its KPI, inside the KPI for
adding a Level) rather than sitting beside every existing item. No
hierarchy, CRUD behavior, or eligibility gate changed in this pass, and no
backend Python files were touched.

## Talent & Potential Grade-to-Grade Assessment Criteria Copy (2026-09-12)

An Owner-requested follow-up capability on top of the icon-actions correction
pass, added before deployment. Each Grade section in the Competency, KPI &
Level builder now exposes a structural, always-visible "Copy Criteria From
Grade..." action (not an inline Edit/Delete icon) that copies the complete
source Grade's assessment structure - Competencies, KPI/rubric definitions,
Levels, and generic/Grade-specific achievement descriptors, with ordering
preserved - into an empty destination Grade as entirely independent new
records. Nothing is shared or linked between source and destination:
renaming or editing a copied Competency, KPI, or Level afterward never
changes the source Grade, exactly mirroring the existing "add a Competency
to a Grade" flow's own precedent of minting a new Competency identity per
Grade membership.

An already-populated destination Grade is always rejected rather than
silently merged or overwritten (`target_grade_occupied`) - no automatic
merge algorithm was implemented; the Owner explicitly authorized keeping
this first version to empty-target-only copying, in favor of safety over
hidden merge behavior. The backend service function
(`talent_program_service.copy_grade_criteria`) reuses the existing
`_require_mutable_draft` gate unchanged, so it can never mutate a Framework
with real Assessment history; the client reuses the identical version-safe
clone-then-mutate orchestration already established for versioned Delete
Competency (clone an immutable/active Framework into a new draft, then copy
against that draft) so the Owner never needs to understand Framework
cloning/versioning to use this feature. Copy scope is bounded to the same
SchoolGroup, Program, and Framework as every other Program-service mutation,
reusing the existing authorization/scoping pattern unchanged. Copied items
retain full ordinary Edit/Delete/collapse behavior identical to
manually-created items. No new schema migration was introduced.
## CRITICAL: Production DB Connection-Pool Exhaustion Fixed (2026-09-12)

Root-caused and fixed a confirmed production release blocker:
`sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
connection timed out, timeout 30.00`. The default (unconfigured) SQLAlchemy
QueuePool numbers in the traceback match `database.py`'s `create_engine`
call exactly - no explicit `pool_size`/`max_overflow`/`pool_timeout` was
ever set.

Root cause was `main.py`'s `inactivity_timeout_middleware` - a global
`@app.middleware("http")` that runs on every authenticated request across
the entire application, not only Talent. It opened its own
`SessionLocal()` session and wrapped the entire `await call_next(request)`
call inside the same `try/finally: db.close()` block, holding that
connection checked out for the full duration of every request's
downstream processing on top of the separate connection the route handler
itself acquires via `Depends(get_db)`. Every authenticated request
therefore consumed two simultaneous pool connections for its whole
lifetime instead of one. This was not a classic leak - the connection was
always eventually closed - but a long-held, effectively duplicated
connection held far longer than the few quick scalar queries it actually
needed (session-user lookup, idle-timeout check, `current_user`
resolution, commercial-access/permission checks). Talent Student
Assessments fires several concurrent API requests per page load, so a
single load could require up to double the connections purely from this
doubling, exhausting the default pool under light concurrent traffic -
explaining why Student Assessments failed first, why other pages then
hung (the pool was globally exhausted for the whole application), and why
a Render restart temporarily "fixed" it (restart empties the pool; the
underlying per-request doubling was unchanged and would recur).

Ruled out during investigation: no additional independent
`SessionLocal()`/`sessionmaker()`/`engine.connect()` sources exist
anywhere in the Talent service/router layer (all rely exclusively on the
injected `Depends(get_db)` session); `dependencies.py`'s `get_db()`
canonical dependency correctly implements try/yield/finally with no
rollback gap; the deployment runs a single `uvicorn main:app` process (no
`--workers` flag), so the observed pool numbers are the single-process
SQLAlchemy defaults, not a worker-multiplication effect. No Grade gate or
annual Program-configuration enablement gate was reintroduced -
`current_placements_for_assessment` and
`_current_placement_for_assessment` are unchanged.

Fix: `inactivity_timeout_middleware` now opens its session, completes the
auth/idle-timeout/commercial-access/route-permission checks, and closes
the session entirely before `call_next` is ever awaited - behavior-
preserving (every existing early-return outcome is unchanged, only
restructured through one closing point ahead of `call_next`). New
regression coverage in `tests/test_db_connection_pool_lifecycle.py`
proves the session closes before `call_next` starts (including on
exceptions), proves an unauthenticated/exempt request never opens a
session, and - against a real small QueuePool - proves the fixed shape
never exceeds pool capacity under concurrency while a reconstruction of
the old doubled-checkout shape reliably exhausts the same pool, positively
proving the doubling was real and is now eliminated.

## Start Editing Accidental Empty-Draft Recovery + Mandatory Clone (2026-09-12)

Owner-reported priority incident: a Program with existing Competencies
(reported at approximately 9) showed an empty Draft after Start Editing,
because the old UI made "Copy the current rubric structure" an optional
checkbox - leaving it unchecked produced a genuinely empty new Draft while
the real Competencies remained safe and untouched in the Framework Start
Editing was invoked from.

No live Talent data was reachable from this development environment to
operate on directly (the local `tis.db` has no `talent_*` tables migrated;
the only reachable local Postgres instance is a stale, empty B11C
concurrency-test schema). The actual reported incident lives in a deployed
environment this session has no database access to. Delivered instead: a
governed, fully tested recovery mechanism ready to run against the real
data, plus the permanent fix that prevents recurrence everywhere.

`talent_program_service.recover_accidental_empty_draft` identifies the
correct source Framework (via the accidental empty Draft's own
`supersedes_framework_version_id`, which Start Editing always records
regardless of whether cloning ran) and, after verifying the Draft is
genuinely empty (zero Competencies, zero Assessment history), re-runs the
existing governed `create_framework_draft(clone_from_id=...)` mechanism to
produce a new, fully populated, independently editable Draft with every
Competency, KPI, Level, descriptor, and ordering already in the source.
Nothing is reconstructed by hand, the source Framework and its historical
completed Assessment evidence are never touched, and the accidental empty
Draft itself is left in place (harmless, since the recovered Draft's
higher version number is what Start Editing/rubric mode selects going
forward) rather than deleted. `scripts/recover_talent_accidental_empty_draft.py`
is the operator-facing CLI (dry-run by default, `--apply` to commit).

The permanent fix: Start Editing's "Copy the current rubric structure
(optional)" checkbox is removed entirely - the new-version form submission
now always sends `clone_from_id` unconditionally (naturally omitted only
for the very first Rubric Structure creation, where there is nothing yet
to clone), so a Start Editing action can never again produce an empty
Draft.

## Talent Student Assessment current-rubric + roster-state acceptance correction (2026-09-12)

Opening an Assessment is not learner evidence by itself. A current `in_progress`
Assessment with zero persisted `TalentStudentCompetencyResult` rows now
transparently continues on the newest saved assessable Framework when reopened.
The prior empty attempt becomes non-current provenance and the replacement keeps
the same visible Evaluation through `evaluation_context_cycle_id`. Once any
Competency Result exists, or once an Assessment is terminal, its exact historical
Framework remains authoritative and immutable.

Normal Student Assessment contexts now exclude private physical Cycles used only
for current-rubric/re-evaluation provenance, so "Current rubric" no longer appears
as a duplicate Evaluation. The roster chooses the newest matching current attempt
when legacy/bad data exposes duplicate-current rows, preventing an older In
Progress row from masking a later Completed result.

The Talent & Potential sidebar now uses the Owner-supplied symbol-only Ghars PNG
(`static/img/talent-ghars-symbol.png`) in the existing icon-sized brand slot while
retaining the visible module label and permission-aware child tree.

## Talent Results & Analytics - Commercial Feature Gate Removed (Owner Decision, 2026-09-12)

Per direct Owner instruction, Results & Analytics no longer requires the
`feature.organization_intelligence` commercial entitlement. Production
`build_availability_provider()` now resolves
`PermissionScopedOrganizationAnalyticsAvailabilityProvider`, which accepts
only a valid positive SchoolGroup and Academic Year and performs no subscription,
plan, workspace-entitlement, or feature-registry lookup. The existing
`talent_analytics.view` permission remains mandatory inside
`resolve_access_context`; Student drill, Candidate, Identification, tenant,
Branch, and Academic-Year scope checks remain unchanged. Privacy suppression,
complementary closure, configured cohort-5 policy, 1000/1000/1000 breadth
ceilings, and M10 REPEATABLE READ behavior are unchanged. The legacy semantic
feature key remains in the general catalog for compatibility/history but is no
longer consulted by Organization Analytics runtime availability.

## Talent Owner Adjustment Package - Grade Alignment And Operational Presentation (2026-09-12)

Current Student Assessment criteria are Grade-aligned. The roster remains
Grade-agnostic for eligibility, but `_newest_assessable_framework` no longer
falls back to another Grade's criteria. Start Assessment requires an assessable
Competency -> KPI -> Level structure applicable to the Student's Grade (or
intentionally unscoped), otherwise it returns a Grade-specific setup message.
The browser follows the same rule; historical evidence remains immutable.

Student Assessments has Grade, Section, and Assessment Status collection
filters. Talent Review has Identification Classification filtering. Students is
the first Talent child for Talent-capable users; standalone Students remains
only as a students-only fallback. Desktop Student tables have no nested vertical
scroll. Learning Style keeps categorical style indicators and their established
per-style colors while privacy-suppressed magnitudes stay hidden.

Already-visible analytics magnitudes use an ordered low-to-high blue intensity.
Protected/no-data states never receive magnitude coloring. Student Assessment
Competency/KPI/Level entry uses a responsive professional hierarchy without
changing write contracts. Ghars uses the compact sidebar emblem and the
transparent full wordmark only in Talent Overview. No schema or migration.

## Talent Owner Adjustment Package - Correction (2026-09-12, follow-up)

The Talent Overview full Ghars wordmark remains **blocked pending asset**: a
locally traced/reconstructed SVG was removed from the header wiring (it is not
the Owner-supplied file) and replaced with a documented, not-yet-present path
(`static/img/ghars-full-wordmark-dark.png`); the header renders empty until
the Owner supplies the real asset. The separate duplicated "Selected
Evaluation" panel below the Evaluation Period cards in Student Assessments has
been removed; the selected card's in-place `is-selected`/`aria-current`
marking is now the only selection indicator. No schema/migration change.
