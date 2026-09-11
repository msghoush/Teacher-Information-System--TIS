---
title: TIS Project State
documentation_version: 4.1
last_updated: 2026-09-11
source_of_truth: true
---

# TIS Project State

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
routes are narrowed from `talent_programs.manage` to the new
`talent_programs.delete`, preserving every existing lifecycle/history guard
unchanged. Evaluation Period true-delete is narrowed from
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

## Evaluation Plan Scope Regression Correction

Evaluation Plan capability projection now has explicit regression coverage for both sides of the authority boundary: an organization-scoped manager retains manage/govern actions while working in a selected Branch, while a truly Branch-scoped identity receives no mutation capability even if its role grants the permission key. The Evaluation Plan workspace explains that read-only state before submission.

The sanctioned Local Test Admin source remains organization-scoped with North Campus assigned as its working Branch. A previously created disposable local Talent database may contain a stale `BRANCH` value; the supported correction is the sentinel-guarded `scripts/manage_local_talent_test_db.py reseed --confirm` workflow.

## Talent Completed Program Operational Workspace

Completed active Programs now open as a compact operational summary instead of remaining permanently in onboarding. Explicit Edit Program, Edit What we assess, and Manage Evaluation Plan actions reopen the same hash-backed wizard at Steps 1, 2, and 3. Finish Setup exits the wizard for a completed Program. Incomplete or draft Programs continue to open in setup mode.

The UI now uses Evaluation Plan and Evaluation Period terminology consistently. Step 3 remains embedded. Program Basics reads the selected Academic Year option text rather than displaying its database ID. Organization-authority failures are mapped to clear Evaluation Period access language, and Branch-scoped users are not shown Plan-management controls the API cannot execute.

## Talent Guided Configuration And Student Display Correction

The Owner screenshot follow-up is implemented in the shared Talent workspace. Program Basics is one concise identity/year/Grades form. What we assess renders one of four compact substeps with table rows and on-demand editors. Evaluation Schedule is embedded inside the Program wizard while reusing the existing standalone renderer and backend contracts. Ready shows only completion counts and one next action. Editing a Program from the Programs table opens this same wizard and its hash preserves the main step or assessment substep across refresh.

Student collection presentation now explicitly shows the compact table above 680px and compact cards at or below 680px, never both at once. Active lifecycle state remains in accessible text and filtering but is visually represented by a neutral dash; exceptional statuses keep a visible status chip. Open Evaluation and Talent Review remain compact collection tables with detail shown only after opening one Student.

## Talent Program Setup Wizard Owner Correction

The Programs detail workspace now satisfies the Owner visual structure: Program header, compact four-step progress, one active setup panel, and local Back/Save & Continue or next-action controls. Step selection is stored in the URL hash and restored on refresh. The implementation no longer emits all setup sections or the duplicate Grades/Build your evaluation readiness cards into one long page. Readiness appears in the stepper through completed checks and a concise remaining-item count.

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
`talent_analytics.view_students`. No production `TalentAnalyticsPrivacyPolicy`
is approved - `resolve_privacy_policy_provider()` returns `None` in
production, so every route fails closed until a governed policy is approved
and wired in (open gate, by design, not a defect). Live PostgreSQL
performance/concurrency validation has not been run (open gate, consistent
with every prior milestone) - only SQLite-backed pytest coverage exists.
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
Draft metadata but cannot Open/Close. Governance additionally requires
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
Map, or AI code exists yet.

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
