---
title: TIS User And System Flows
documentation_version: 3.7
last_updated: 2026-09-09
source_of_truth: true
---

# TIS User And System Flows

## Owner Video Acceptance Flow Corrections

1. Student Assessments groups configured Programs beneath each user-defined Evaluation Period whether or not an internal Cycle already exists.
2. Selecting a Program with no Cycle does not redirect to Evaluation Plan. With the existing Cycle-manage + Plan-manage + Period-select permissions, the browser creates the internal Cycle, links it to that Planned Period using revision guards, then re-enters Student Assessments with that Period/Program selected.
3. The Student roster is then the operational surface. **Start Assessment** posts the selected Evaluation context and Student, receives the new current Assessment, and opens that Assessment immediately.
4. The opened Assessment resolves its own persisted `program_id` and `framework_version_id`, then renders the exact Grade-applicable Framework Competencies, competency-owned assessment criteria/Levels/descriptions, and any saved results. The browser does not substitute another Program's rubric.
5. Any create/start failure is surfaced in the visible operational alert region; a failed click must not look like a no-op.
6. Delete Competency against an immutable/assessed Framework is a versioned future-change flow only: clone the current Framework, delete from the new Draft using the dedicated permission/revision guard, and preserve old Assessment evidence unchanged.
7. KPI numeric configuration remains separate from assessment criteria and has an explicit disclosure/collapse control.

## Students Branch And Learning Style Presentation Flow

1. Add Student, Delete selected, per-row Open, and per-row Delete are compact icon-only controls with accessible names/tooltips.
2. Cross-Branch Students browsing requires `students.view_all_branches` **and** organization/global access scope. The managed-role policy keeps this permission Administrator-only.
3. Without that authority the list is fixed to the actor's assigned authorized Branch, the Branch selector is replaced by a read-only Branch context, and **All branches** is not offered.
4. Learning Style distribution continues to use the ADR 0031 privacy provider. If that provider is unavailable, the page explains that aggregate statistics are unavailable and emits no chart/count/percentage. If the selected cohort is suppressed, the privacy-protected state remains the only aggregate presentation.

## Talent Selected Evaluation And Recovery Flow

1. Student Assessments lists user-defined Evaluation Periods and their configured Programs. Selecting a Program inside a Period visibly marks that Evaluation/Program as active and loads its currently eligible Students.
2. Start Assessment sends the selected Evaluation Cycle plus Student identity and opens the returned Assessment while retaining the selected Cycle/Program context. Continue/View Assessment opens that exact current attempt.
3. The Assessment workspace loads the exact saved Framework for that attempt and the Student's recorded Grade-scoped competencies/assessment criteria; a click must never silently no-op.
4. If automatic rubric-change comparison reports a completed current attempt as stale, the normal **Re-evaluation required** flow creates a linked replacement under ADR 0036.
5. If an administrator must deliberately reassess a completed current attempt without an automatic stale-rubric condition, `talent_assessments.reset_for_reassessment` marks the prior attempt historical/non-current and audits the reset. It does not delete any evidence.
6. After reset, the same Student/Evaluation row returns to **Not started / Start Assessment**. The next start creates a fresh current attempt with zero competency results; the prior completed attempt remains available only as historical evidence.

## Talent Program Readiness And Authoring Flow

1. Talent's main sidebar tree is the sole primary module navigation; the page does not duplicate that navigation ribbon.
2. Program authoring shows one eligible Grade at a time, defaulting to the first configured Grade, then its Competencies and assessment criteria.
3. Competency and Rubric-Level deletion remains permission/lifecycle controlled by backend actions; UI visibility never grants authority.
4. Program readiness is projected on the Program summary. **Ready** is positive only after Program/Grade setup, assessment criteria, and Evaluation Plan requirements are complete; there is no separate Ready step.
5. The competency-owned rubric structure is labeled **Assessment Criteria** in normal setup. The separate real numeric `TalentKpiConfiguration` is labeled **Key Performance Indicator (KPI)** and supports Add/Edit/Delete while mutable.

## Talent Review Filtering Flow

1. Talent Review starts from all current completed Assessments in the authorized Academic Year/Program context.
2. Branch options are tenant/scope authorized. **All Branches** appears only when the actor can access more than one Branch.
3. Grade options derive from operational Planning within the selected authorized Branch; Section options cascade from selected Branch + Grade.
4. The backend applies Branch/Grade/Section to frozen Assessment placement context before projection.
5. The primary table shows Overall Program Result, Review status, and Official Identification. Deterministic Review Candidate policy remains internal and can still enable review actions, but **Meets criteria** is not presented as a learner classification.

## Talent Rubric And Analytics Closure Flow

1. Rubric configuration establishes arbitrary labels and `display_order`; the shared browser helper derives visual strength and an explicit “position of total” cue from that order.
2. Assessment entry uses the same treatment for selectable levels. Talent Review and Student/Learner Profile resolve the actual persisted level from the exact historical Assessment and Framework.
3. Meets Program Criteria remains the deterministic candidate outcome. Official Identification remains a separate permanent human decision; neither is inferred from the strongest displayed level.
4. Talent Overview links to operational work. Organization Overview shows selective executive results and directs users to Program Results, Branch Results, Talent Map, and Progress Over Time for detail.
5. Learning Style distribution starts at the authorized Organization context, optionally narrows by Branch, then exposes only Planning-configured Grades and Sections. The existing Students analytics endpoint applies permission, tenant/Branch scope, and privacy suppression.

## Evaluation Plan Authority And Local Retest Flow

1. The server requires `talent_evaluation_plans.manage` or `.govern`, as applicable, plus durable organization/global access scope for Evaluation Plan and Evaluation Period mutations.
2. An organization-scoped Program manager may keep a Branch selected as working context; that selection does not suppress its projected Plan actions or backend authority.
3. A truly Branch-scoped user may view the Plan when permitted, but sees a read-only explanation and no add/change controls. Direct mutation calls remain denied.
4. The sanctioned Local Test Admin is seeded with organization scope and North Campus as its working Branch. If the disposable local database predates that seed contract, run `python scripts/manage_local_talent_test_db.py reseed --confirm`; never repair this condition with raw SQL or an authorization bypass.

## Completed Program Operational And Edit Flow

1. Opening an active Program with enabled annual Grades, an active complete assessment setup, and at least one Evaluation Period shows its operational summary without the setup stepper.
2. Edit Program opens `#tp-basics`; Edit What we assess opens the assessment subflow; Manage Evaluation Plan opens `#tp-schedule`. Program and Academic Year query context remain unchanged.
3. The setup stepper labels Step 3 Evaluation Plan. Its embedded table labels each row an Evaluation Period and supports the existing authorized edit, remove, and Start Evaluation actions.
4. The Program summary confirms prerequisites. For a complete Draft Program, Finish Setup is the governed activation boundary: activate the Program, activate the reviewed Draft Framework with its revision/fingerprint, clear setup state, and open that Program's operational summary. Already-active state is not mutated again.
5. The renderer obtains the Academic Year display label from the selected shell option and never presents its internal ID as the normal label.

## Talent Module Navigation And Context Reset Flow

1. While a Talent & Potential page is active, the main application sidebar expands a permission-aware child tree for Overview, Programs, Student Assessments, Talent Review, and Results & Analytics.
2. Choosing any of those top-level destinations is a context reset boundary. The selected Academic Year may carry forward; Program, Cycle, Assessment, Branch, Grade, Section, metric, dimension, and setup hash state do not.
3. Programs opens the searchable Programs collection. Selecting **Open Program** is the explicit transition into one Program workspace; row-level Edit/Rubric shortcuts are not duplicated on the collection screen.
4. Student Assessments opens neutral and shows its own Program filter. A Program is preselected only through an explicit Program-context action such as Open Assessments from inside that Program workspace.
5. Results & Analytics top-level entry also starts from clean module context, while navigation *within* the Results & Analytics family may preserve the active analysis filters.
6. Inside an opened Program, Edit Program, Build/Edit Rubric, Manage Evaluation Plan, Open Assessments, and View Results remain Program-context actions and retain that Program and Academic Year intentionally.

## Talent Re-evaluation Reset And Evaluation Grouping Flow

1. Student Assessments groups each repeated user-facing Evaluation label across Programs, uses configured sequence to order label groups when available, and renders each Program once; duplicate physical Cycles never create duplicate Program cards.
2. A configured Program/Period can be shown before its internal Cycle exists. Starting/opening that Program uses the existing Evaluation Plan/Cycle workflow to materialize provenance when needed.
3. A completed Student whose current rubric has materially changed surfaces **Re-evaluation required**. For forward changes this means a newer assessable Framework Version; for legacy pre-guard data it may also mean that the same Framework now contains a complete competency-owned rubric whose IDs no longer match the completed attempt's persisted rubric/level bindings.
4. Re-evaluation never edits or deletes the prior evidence. The previous completed attempt becomes non-current; the replacement starts current and In Progress with zero competency results, links to the prior attempt, and remains under the original visible Evaluation through `evaluation_context_cycle_id`.
5. Untouched legacy shared rubrics and partially configured competency-owned rubrics do not trigger re-evaluation.

## Talent Guided Program Configuration

1. Open or Edit Program enters the same `/talent/programs` wizard and selects Basics by default.
2. Basics saves draft Program details and the selected Academic Year's enablement/Planning Grades, while logo upload/removal continues through its Program-scoped route.
3. What we assess selects exactly one Competencies, Rubric Levels, Achievement Descriptions, or Review substep from the URL hash. Add/Edit opens only the requested inline editor; supported removals remain draft-only and revision guarded.
4. Evaluation Schedule renders inside the Program panel. Adding, renaming, removing, preparing, previewing, and starting evaluations use the existing Evaluation Plan, Period, and Cycle services without a setup-route change.
5. Ready presents compact completion counts and sends the user back to the embedded schedule to finish or start an evaluation.
6. The Students collection displays a table on desktop and cards on mobile through mutually exclusive CSS. Talent Review and an opened Evaluation use compact tables for their Student collections.

## Talent Program Guided Setup

1. The user opens a Program and sees its identity plus focused Basics, What we assess, and Evaluation Plan entry points; readiness is summarized on the Program itself.
2. The browser reads supported URL hashes and renders the requested edit panel; refresh returns to that panel.
3. Basics saves Program identity/configuration through existing Program and academic-year routes. What we assess edits the selected draft framework through existing revision-guarded competency, rubric, level, and descriptor routes.
4. Evaluation Plan reuses the existing guided Plan/Period/Cycle workspace. When prerequisites are complete, Finish Setup is offered from the Program summary rather than from a separate Ready step.
5. The UI shows edit/remove actions only when the permission payload and entity lifecycle support them. Program lifecycle uses activate/retire; historical versions and terminal assessment evidence stay immutable.

## Talent Program Identity, Planning Scope, And Result Clearing

1. Program logos are uploaded, replaced, or removed through organization-scoped Program routes using `talent_programs.manage`; all displays use the same compact logo/initials identity.
2. Talent Grade choices come from operational Planning sections for the selected Academic Year and authorized Branch. Grade changes load matching Planning Sections; no matches disable Section with "No Sections configured for this Grade."
3. Annual Program configuration rejects Grades absent from Planning, including when Planning has no configured Grades.
4. An authorized user may clear one saved competency result only while its assessment remains In Progress, using the existing expected-revision delete action. The UI updates that competency locally and preserves context and scroll.


## Simplified Talent Program And Evaluation Flow

1. A user searches the compact Program list and opens or edits a Program.
2. Basics sets Program information and eligible Grades for the selected year.
3. What we assess shows each competency with every rubric level and achievement
   description. Edit uses the existing draft-version and revision contracts;
   after save, the joined view is shown again.
4. Evaluation schedule accepts a free-text, user-defined evaluation name (for
   example Term 1, Audition, or Spring Review). Adding an evaluation creates
   missing Plan/Period state and activates it when the actor has the existing
   govern permission; none of that Plan/Period/Cycle vocabulary is shown to
   the user.
5. The UI translates saved execution state to Setup, Ready to start, In
   progress, or Complete.
5a. The shared Academic Year/Program/Branch/Grade/Metric/Dimension context
    selector used by this flow and by Organization Overview applies a change
    automatically (debounced); no separate confirm click is required. The
    primary Talent navigation shows one "Results & Analytics" entry rather
    than repeating the sticky analytics sub-nav's individual page links.
6. Start Evaluation prepares a draft Cycle when needed, links it with both
   expected revisions, and requests the authorized population preview.
7. The user sees "X eligible Students will be included based on Academic
   Placement as of DATE" before confirming start.
8. The existing organization-governed open action revalidates Program,
   Framework, Plan, Period, linkage, and revisions, then freezes the historical
   Student population. Assessment entry continues through the existing M5 flow.

## Student/Talent Pre-Deploy Migration Flow

1. The dedicated pre-deploy command creates only baseline metadata; all
   Student/Talent migration-owned tables remain absent.
2. The ledger runs `20260904_000`, accepting equivalent unique parent keys or
   adding `(id, school_group_id)` uniqueness to Branch, Academic Year, and any
   existing Student table. Duplicate data aborts the transaction and marker.
3. Migration `001` creates Students and Academic Placements with the original
   composite tenant-scoped foreign keys intact, followed by the Talent chain.
4. M4 creates Cycles before M8 without binding to a parent that does not exist;
   M8 creates Plans/Periods and adds the nullable composite Cycle-to-Period FK.
5. Each migration and marker commits together. Any failure rolls back that
   migration and stops pre-deploy before web activation; a retry re-evaluates
   only unmarked work.

## M10 Production Provider Resolution Flow

1. Before analytical SQL, the route resolves commercial availability through
   `feature.organization_intelligence` and the active canonical entitlement
   state. A false, missing, invalid, or exceptional result returns unavailable.
2. The existing `talent_analytics.view` permission check then runs separately;
   Student drill and sensitive secondary metrics retain their additional
   permission gates.
3. Breadth configuration must resolve to 1000 matrix cells, 1000 relationship
   results, and 1000 Program-pair results. A request above any applicable limit
   is rejected before aggregation and is never truncated.
4. Privacy configuration must resolve to minimum cohort 5 for P1-P7. Raw cells
   below 5 are suppressed, then existing relationship-aware complementary
   suppression runs before any serializer receives the closed projection.
5. Outside production only, an exact `.local_test_data/talent_local_test.db`
   URL substitutes deterministic privacy, bounded breadth, and local
   availability providers. Production names, `tis.db`, memory databases, and
   every other database path remain on the production fail-closed path.

## Talent Results & Analytics Experience Flow

1. An authorized user opens Results & Analytics and selects an Academic Year. The Organization Overview requests the existing Overview, Program Portfolio, and Talent Map projections for that same authorized context.
2. The page presents returned facts as headline cards, Program progress, non-ranked Branch links, and a Talent Map preview. Only visible backend percentages can set a bar or chart dimension.
3. The user can drill from Organization to Branch, Program, or a visible Talent Map Branch cell. Program and Branch pages call their existing M10 routes and preserve supported Program/Branch filters.
4. Students Across Programs calls the symmetric distinct-participant pair route and explains diagonal versus shared Program participation without inferring similarity or ability.
5. Students requires both analytics and Student-view permissions, retains the P7 privacy gate and max-100 paging, shows frozen historical context, and exposes Candidate/Identification fields only when returned by the separately permissioned queries.
6. Progress Over Time calls one Program/one Academic Year with one allowed metric. It orders Periods by the governed response, translates comparability reasons, and never calculates a delta, trend, or improvement claim.
7. Permission denial, analytics unavailability, no data, and privacy protection are presented as separate plain-language states. A protected result supplies no visual or accessible magnitude.


## M10 B11 Qualification And Release Flow

1. Commit and push the ADR 0028 governance checkpoint and require green
   cumulative KMS.
2. With local/staging PostgreSQL, representative non-production data, and
   non-production provider configuration, B11-C profiles latency, queries,
   memory, privacy closure, and EXPLAIN evidence without requiring final
   production thresholds, packaging, breadth limits, SLOs, or isolation.
   This step is complete and B11-C is CLOSED after independent re-review.
3. B11-D uses production-like PostgreSQL and controlled writers to test current
   READ COMMITTED behavior first. Evidence, a governed ADR, and full-request
   transaction scope are prerequisites for stronger isolation; indexes follow
   the separate evidence/migration/rollback/ADR gate.
   This qualification is complete and B11-D is CLOSED. READ COMMITTED mixed
   snapshots were proven; permanent REPEATABLE READ remains governance-required
   and not implemented.
4. F1 implements the approved production privacy, commercial-availability, and
   breadth providers. As of 2026-09-09 (ADR 0028/ADR 0030), B11-E is CLOSED
   WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM REMAINING and
   B11 overall is CLOSED on that same basis; B12 is CLOSED. Cumulative
   production release qualification and a separate `dev`->`master` approval
   still block master merge and deployment.

## M10 B8 Participation Overlap Flow

An authorized Organization Intelligence request resolves authentication,
SchoolGroup, commercial availability, `talent_analytics.view`, tenant-bound
Academic Year, historical Branch scope, normalized filters, and injected
breadth approval before analytical SQL. The system then deduplicates
Open/Closed frozen Cycle population membership to `(program_id, student_id)`
within that authorized scope and performs one set-based self-join for canonical
Program pairs. Each diagonal is the Program's distinct participants and each
off-diagonal is the distinct intersection; no row or column sums are created.
The P2 pair Cells pass through M9 primary privacy, B2 closure without fabricated
overlap equations, `PrivacyClosedProjectionSet`, and the strict B8 serializer.
The response contains no Student identity or Candidate/Identification overlap.

## M10 B9 Student Drill Flow

An authorized Student Drill request resolves the identical B3/B4 pipeline as
every other M10 route (authentication, SchoolGroup, commercial availability,
`talent_analytics.view`, tenant-bound Academic Year, historical Branch
scope), then explicitly requires `talent_analytics.view_students` (true AND
composition) before any identifiable query. Filters resolve through the
existing `resolve_filters`/`authorized_program_universe` primitives and
breadth is enforced (`projection_family="student_drill"`) before any
identifiable SQL. The system counts distinct authorized Student IDs from frozen
`TalentAssessmentCyclePopulationMember` context (never current Placement) into
one P7 `student_drill_population`/`count`/`distinct_student` Cell, then runs it
through the identical B2 closure pipeline
(`apply_primary_privacy_and_close`/`PrivacyClosedProjectionSet`) every other
M10 route uses. Only a visible gate permits pagination over distinct Students,
followed by page-bounded frozen Program/Cycle contexts and independently
permission-gated Candidate/Identification evidence for those exact contexts.
An advisory Learner Profile capability hint remains top-level. The strict
`StudentDrillClosedProjection` wrapper and its serializer reject any raw SQL
row, raw ORM object, or non-visible gate. The response has no `total_count`,
no Student Talent Score/ranking, and no direct Student-ID filter.

## B10-A Longitudinal Organization Intelligence Flow (Approved Architecture, Not Implemented)

ADR 0027 records the approved flow for a future single-Program, single-
Academic-Year longitudinal request; no route exists yet, and this section
describes governance only. A future request would resolve the identical B3/
B4 access pipeline for exactly the requested Academic Year, then resolve the
Program's ordered M8 `TalentPlannedEvaluationPeriod` slots by governed
`sequence` - the Period is the order authority, and its optional linked
Open/Closed `TalentAssessmentCycle` (never a Draft or missing Cycle) is the
factual evidence source for that point. For the one selected metric (nine of
the fourteen existing `MetricCode` values are approved), each point would be
built as a canonical Cell, pass through primary privacy and B2 closure, and
be wrapped in a strict closed serializer identical in discipline to B8/B9.
Adjacent points would carry `comparable`/`not_comparable` metadata with a
governed reason code - never a server-computed delta, percent-change, or
growth/improvement language. Candidate/Identification metrics would remain
query-skipped before any privacy-sensitive point is selected without their
own permission. `AcademicYear.year_name` would never be parsed or sorted as
chronology; multi-Academic-Year longitudinal ordering remains deferred.

## Deterministic Talent Analytics Flow (M9, Committed/Pushed On dev)

1. An actor with `talent_analytics.view` requests one Program + one Academic
   Year context; context/filters resolve strictly against that scope
   (frozen population, not current Placement).
2. For every privacy-sensitive metric, the route runs the authorized raw
   aggregate query, builds one or more `Cell`/`Group` structures, then calls
   `apply_primary_privacy` (the injected policy's real per-cell decision)
   BEFORE `run_complementary_suppression` - never the reverse, and never
   skipped, on any of the eight routes.
3. `run_complementary_suppression` repeats reconstruction-breaking passes to
   a fixed point (max 8) using an identity/value-independent tie-break; a
   projection that cannot reach a safe fixed point serializes `restricted`,
   never a best-effort guess.
4. A `coarsened` cell publishes only a safe replacement value that the
   policy itself supplied with its decision; if the policy requests
   `coarsened` with no replacement, the cell fails closed to `suppressed`.
5. Candidate and Identification analytics are query-skipped, not merely
   response-filtered, without the actor's own `talent_review_candidates.view`/
   `talent_official_identifications.view` permission respectively.
6. Student-level drill (`/students`) additionally requires
   `talent_analytics.view_students` AND `talent_analytics.view`, and is
   denied (`analytics_drill_restricted`, no cohort size disclosed) whenever
   the cohort's own privacy cell is not `visible`.
7. Production privacy resolves only when the configured cohort value equals the
   approved value 5. Missing, malformed, mismatched, or exceptional policy state
   fails closed rather than using an implicit permissive threshold.

## Talent Annual Evaluation Plan Flow (M8)

The operational workspace presents the approved cross-milestone journey as:

1. Configure one Program's eligible Grades and exact competencies/rubric version.
2. Create and activate its Annual Evaluation Plan and ordered Periods.
3. Prepare a Draft evaluation, link it to an eligible Period, then open it to
   freeze the historically scoped Student population.
4. Start a Student assessment and save each competency result through M5,
   consuming the returned revision before the next result write.
5. Complete the Assessment, evaluate deterministic Candidate rules, review any
   resulting Candidate, and separately record an authorized human Official
   Identification decision when appropriate.
6. Record or amend Educator Input through its independent M6 permission and
   lineage without changing Assessment, Candidate, or Identification state.

1. An organization-authorized Plan manager creates one Draft Plan from an
   existing Program Academic Year Configuration and authors ordered Periods.
2. Govern activates a non-empty valid Plan. Managers may edit/reorder only
   unused planning context; linked Periods become immutable anchors.
3. Plan-manage AND Cycle-manage may link one Planned Period to one Draft Cycle
   under Plan -> Period -> Cycle locks. Unlink is Draft-only.
4. Existing M4 govern opens a Cycle. If linked, the service revalidates Active
   Plan, Planned Period, same Program/year, and unchanged linkage before the
   existing population freeze. Ad-hoc Cycles skip this step.
5. Govern may cancel an unlinked Planned Period with a reason. Closure allows
   required Periods only when executed through a Closed Cycle or cancelled
   without a Cycle; optional unresolved Periods remain advisory.
6. View+manage may roll an Active/Closed Plan into another enabled annual
   configuration for the same Program. Only label, order, required flag, and
   short code copy; execution and semantic context reset.
7. Without Cycle-view permission, reads omit the cycle key and all derived
   relationship actions, cycle warnings, and per-Period execution resolution.

## Talent Learner Profile Flow (M7, Complete)

1. A user with `talent_learner_profiles.view` requests one same-tenant Student.
2. The service loads only that Student's historical records and filters every
   Placement/Talent record by its own historical Branch; no visible record is a
   non-enumerating not-found result for a Branch actor.
3. The response groups Program, Academic Year, Cycle, exact Framework,
   Assessment, Competency Result, optional persisted KPI, Review Candidate, and
   Official Identification history without inferring a current Talent status.
4. Review Candidate, Official Identification, and Educator Input each require
   their respective independent M6 `.view` permission in addition to base
   profile access; absent domains and related timeline events reveal no
   metadata.

## Talent Review, Official Identification & Educator Input Flow (M6, Complete)

Every Educator Input create/amend flow resolves historical context, checks the
resulting persisted Branch against canonical actor scope before commit, and
rolls back with a non-enumerating response when unauthorized. Later reads use
that same persisted historical Branch rather than current Placement.

1. An authorized actor with `talent_review_candidates.manage` and authorized
   frozen-member Branch/organization scope requests evaluation for one
   Completed Assessment. A non-Completed Assessment is rejected.
2. The server deterministically evaluates the exact M3 Review Candidate
   Policy attached to the Assessment's exact Framework Version, reading only
   existing Assessment/Competency-Result/persisted-KPI evidence - never
   mutating it. No policy attached means no candidate is ever inferred.
3. A qualifying (policy-satisfied) evaluation materializes one durable
   candidate row, starting `status="pending_review"`, with policy identity,
   match mode, a SHA-256 fingerprint, and a full evaluation snapshot;
   re-running evaluation afterward is idempotent and returns the existing row
   unchanged. A non-qualifying evaluation still persists no candidate row,
   but is now structurally audited (assessment identity, Framework/Policy
   context, `outcome=false`, fingerprint - no free text).
4. An authorized human with `talent_review_candidates.manage` marks a
   `pending_review` candidate `reviewed` (`POST .../{id}/review`) - one-way
   only, never reversible, never altering assessment evidence, never
   auto-identifying the Student.
5. Only once a candidate is `reviewed` may an actor with
   `talent_official_identifications.record` AND organization/global access
   scope record exactly one Official Identification decision
   (`identified`/`not_identified`) for it. A Branch-scoped actor is denied
   even if granted `.record`. The decision is durable either way - there is
   no mutation, revocation, second decision, or re-identification path.
6. Independently of the Review/Identification chain, an authorized educator
   with `talent_educator_inputs.add` may record bounded qualitative Educator
   Input for a Student, bound to SchoolGroup/Student/Program/AcademicYear/
   `observed_at` plus a resolved historical Placement/Branch snapshot (frozen
   Cycle context if supplied, otherwise the Student's Placement effective at
   `observed_at` - a clean rejection if none exists). `talent_educator_inputs.amend`
   may append a new version referencing the one it supersedes; the original
   is never edited or deleted, and default reads return only the current
   version of each lineage chain.
7. Review Candidate, Official Identification, and Educator Input remain
   structurally distinct entities: Review Candidate never auto-produces
   Official Identification, and neither carries the other's state in a
   shared mutable field.

Presentation note: the steps above describe the backend `ReviewCandidate`
model, its `/api/talent/review-candidates` routes, and the
`talent_review_candidates.*`/`talent_official_identifications.*` permission
keys, which are unchanged deterministic/audit identifiers. The normal
user-facing Talent UI labels this surface "Talent Review" (nav entry,
breadcrumb, Student Profile Talent tab, and in-page notifications) and no
longer prints "Review Candidate(s)" or "Candidate" in that normal path. The
Talent Review list itself now renders as one compact table (Student, Program,
Grade, Section, Evaluation, Result, Review status, Identification status,
Action) instead of one large card per Student; opening a row (`review_id`)
shows that one Student's full detail, including the Official Identification
decision form, rather than showing every Student's full detail inline.

## Talent Student Assessment Flow

1. An authorized assessor with canonical Branch/organization scope starts one
   In Progress Assessment only for an Open Cycle's visible frozen member.
2. The assessor records or replaces exact Framework Competency/Rubric Level
   results using the Assessment's expected revision. Current Student transfer
   never changes frozen-Branch access.
3. Completion validates that every exact Framework Competency has a result. For
   an enabled KPI, the service validates numeric inputs, calculates integer
   weighted contributions over denominator 10,000, applies ROUND_HALF_UP, and
   persists the Framework-specific result and canonical provenance atomically.
4. A successful Completed Assessment is read-only. The assessor may instead
   finalize Incomplete or Insufficient Evidence, each read-only and without a
   KPI result. Candidate selection, correction/reopen, and assessor assignment
   are not available.

Presentation note: an opened Evaluation's Student list is one compact table
(Student, Grade, Section, Assessment status, Action) rather than one large
card per Student. The Action label is state-driven from the same real
assessment status above, not a separate UI status: no assessment yet shows
"Start Assessment" (only offered while the Cycle is Open and the actor can
manage), an `in_progress` Assessment shows "Continue Assessment", and any
other recorded status (Completed, Incomplete, or Insufficient Evidence) shows
"View Assessment". No new assessment state was introduced.

## Talent Assessment Cycle Population Flow

1. An authorized Draft author creates a SchoolGroup-wide Cycle and explicitly
   selects Program, Academic Year, exact Framework Version, and
   `population_effective_at`.
2. Draft preview resolves effective Academic Placements and annual eligible
   grades dynamically. Organization population readers see the whole preview;
   Branch readers see only authorized Placement branches and a subset count.
3. An organization/global governor opens the Draft. The server locks and
   revalidates it, derives the complete SchoolGroup population, inserts exact
   frozen historical member snapshots, stores full count/fingerprint, changes
   status to Open, and audits the event in one transaction.
4. Open/Closed reads use frozen Branch context. Branch readers never receive
   the full count/fingerprint; later Student transfers do not change their
   historical visibility. A confirmed qualifying Placement may add a missing
   member to an Open Cycle under ADR 0033; the Cycle is locked, revisioned,
   re-counted, re-fingerprinted, and audited in the same transaction. Existing
   members/evidence are unchanged. Close is final and forbids synchronization.

## Configure And Generate With Teacher Scheduling Rules

1. An administrator with `timetable.manage_teacher_rules` opens System
   Configuration → Timetable Settings → Teacher Scheduling Rules in one exact
   SchoolGroup, branch, and academic-year scope.
2. The administrator selects a teacher, Schedule within/Must teach/Unavailable,
   all or selected working days, numbered periods, and Select All or selected
   Current/New Planning sections. Grade and first/last controls are not part of
   the normal form.
3. The service validates scope and rule shape, rejects deterministic hard
   contradictions, persists normalized rule/slot/target rows, and marks only
   unpublished Drafts stale while clearing approval. Published history is not
   modified.
4. Generate or Regenerate captures canonical rules in a schema-v4 immutable
   snapshot. Readiness and the problem builder reject invalid targets, impossible
   workload/availability, conflicting hard rules, and unavailable-period locks.
5. CP-SAT confines existing eligible demand to Schedule-within windows, enforces
   Must teach occupancy and Unavailable slots, and continues scoring saved
   teaching/free preferences. No rule creates demand and hard rules never relax.
6. The independent validator repeats window, required-occupancy, and
   unavailability checks and reports preference satisfaction. Only a valid,
   current-fingerprint candidate may become a new unpublished Draft.
7. Select All mirrors every visible Current/New section and saved-rule summaries
   show either exact grade-section names, All assigned sections, or All classes
   for teacher-wide Unavailable rules. Editing restores the same literal scope.
8. Manual Draft placement rejects hard Unavailable and Schedule-within violations
   before writing. Complete Draft validation also detects missing Must-teach
   occupancy and wrong selected-section occupancy; these hard blockers prevent
   approval and publication, while preferences never block lifecycle actions.
9. Multiple Schedule-within rows that apply to the same scoped demand contribute
   slots to one combined allowed window. Before solving, TIS matches every
   teacher's effective workload to those combined windows and reports provable
   capacity or Subject Distribution Rule conflicts, including unavailable slots,
   Must-teach slots, daily coverage, minimum/maximum days, and double blocks.
10. When the full solver alone proves infeasibility, the Workflow runs bounded
    family-isolation solves over base collisions, locks, grouped activities,
    subject rules, teacher rules, and their interaction. It persists the proven
    customer-safe category and lock/group counts on the same Generation Run; it
    never saves a relaxed candidate or changes the original hard constraints.
    The Workflow uses `TIS_TIMETABLE_DIAGNOSTIC_TIMEOUT_SECONDS` (default 60)
    independently from the primary solve and skips absent lock/group profiles.

## Guided Curriculum Adjustment UI

1. A user with `curriculum.adjust` opens **Adjust Curriculum** from Planning or Subjects.
2. The user chooses grade, selected Current/New sections, or all active source uses, then chooses source, target, and the proposed source reduction.
3. The browser requests the Stage 3 preview and presents section demand changes, teacher/capacity impact, rule and grouped warnings, blockers, and Draft regeneration impact.
4. The user explicitly chooses an eligible, within-capacity teacher or **Leave unassigned** for every affected section. Nothing is preconfirmed.
5. Final review requires confirmation and submits the unchanged preview fingerprint to Stage 4 apply.
6. If Planning changed, the preview is refreshed and the user reviews again; compatible teacher selections are preserved where possible.
7. Success reports affected sections and Draft status and offers Timetable/regeneration links. Regeneration is never automatic.

The period count entered in step 2 is the transfer amount for every selected section. Preview rejects zero/negative transfers and any section whose current source demand is smaller than the request. A partial transfer leaves its remaining source demand active. After apply, Subjects shows the effective Planning value when uniform; differing section values show **Varies** and can be expanded by section. Catalog weekly hours remain secondary defaults.

For **Reduce periods only**, the user selects no target subject. Preview shows the source before/after demand, source teacher load reduction, rule/grouped warnings, and Draft impact. No teacher reassignment is requested. Apply changes only the selected source demands, retires only zero results, and otherwise follows the same fingerprinted atomic transaction. Subject Details can open this flow prefilled for its one grade-specific subject. Multi-grade selection remains outside this single-subject workflow.

## Atomic Curriculum Adjustment Apply

1. A user with `curriculum.adjust` submits the exact reviewed request, Stage 3
   fingerprint, and one explicit target-teacher decision per section.
2. The service owns one transaction, locks exact SchoolGroup/branch/year authority,
   and rejects an active generation run.
3. It rebuilds the preview and rejects stale fingerprints, preview blockers,
   incomplete decisions, invalid qualification/capacity, rule conflicts, or Draft
   locks that cannot survive the proposed demand/teacher state.
4. It updates only selected Current/New source/target demands and confirmed teacher
   assignments. Source zero becomes inactive retirement evidence and any active
   source section rule is inactivated.
5. It marks only the current unpublished Draft stale, clears approval, preserves its
   snapshot/placements/history, and records one durable applied audit.
6. All changes commit together. Any failure rolls back the entire adjustment.
   Regeneration remains a later explicit action; published history is untouched.

## Read-Only Curriculum Adjustment Preview

1. An authorized Planning editor selects grade, selected sections, or all active
   source uses and identifies source/target subjects plus proposed source periods.
2. The service resolves only Current/New sections in the selected SchoolGroup,
   branch, and academic year and reads explicit-first section demand.
3. It projects released/target periods, current teachers, uncommitted teacher
   options and capacity, scheduling-rule arithmetic, grouped warnings, and Draft
   stale/regeneration impact.
4. It returns blockers/warnings and a deterministic preview fingerprint. No row is
   changed and no teacher is automatically selected.
5. A future apply stage must rebuild and compare the fingerprint before any atomic
   mutation. Published timetable history remains outside the write path.

## Simplified Timetable And Official Visibility

1. A manager creates or opens the exact-scope Draft Timetable and configures inputs until Configuration Complete.
2. The manager runs Verify Feasibility. The durable Workflow solves the exact immutable snapshot with every hard constraint and no soft objective, then independently validates one complete solution.
3. Only a validated result produces Feasibility Verified and enables Generate Timetable. Infeasibility exposes the isolated hard-rule family; timeout remains inconclusive and cannot enable generation.
4. The verified placements are retained by full input fingerprint. Any Planning, allocation, rule, slot, lock, grouped-resource, or other snapshot-authority change requires verification again.
5. Full generation optimizes quality from the verified placement hint. If optimization times out, the worker independently validates and persists the verified placement as the Draft fallback instead of returning no timetable.
6. When authority changes after a Draft exists, the Draft remains stale,
   versioned, and unpublishable. If current inputs have no genuine structural
   blocker, the state is Draft Needs Regeneration and still permits Verify
   Feasibility against a fresh immutable snapshot. A verified current fingerprint
   then permits Regenerate; the stale source is never rewritten.
7. The regeneration source is the current populated, mutable, unpublished Draft,
   whether its origin is manual, generated, or regenerated. An empty starter Draft
   has no prior arrangement and therefore follows Generate. Active and historical
   versions cannot be selected directly as regeneration sources.
2. Generate and Regenerate operate against that current draft context; Regenerate retains Stage 5.1 locks and concurrency.
3. Approve Draft validates that exact draft and records the reviewing administrator;
   generation alone never grants approval.
   Regenerate is presented beside Approve Draft and requires at least 25 percent of
   unlocked source placements to change, rounded up.
4. Any placement, drag/drop, swap, lock, regeneration, or stale authority change
   invalidates approval and requires review again.
5. Publish Timetable requires approval, revalidates the draft, atomically makes it
   official, and retains the prior publication in history.
6. `/my-timetable` resolves exact-scope teacher identity, reads only the active pointer,
   and filters to that teacher. View-only non-teachers use the general published page.
   Destructive and technical version actions remain in Timetable History.

## Generate And Regenerate Timetable Flow

Academic Scheduling Quality is configured using explicit subject codes and optional
Swimming section groups. Saved branch/year rules enter the immutable run snapshot.
CP-SAT applies hard daily core coverage when demand permits, optional ICT one-per-day,
simultaneous group/resource constraints, and soft distinct-day/non-consecutive
preferences. Independent validation repeats hard rules before persistence.

1. Require `timetable.generate`, exact tenant branch/year scope,
   `generation_ready`, a current mutable draft context, and no active run.
2. Select Generate for a fresh/manual current draft; select Regenerate for a current
   generated candidate and freeze the source revision, arrangement, and locks.
3. Capture schema-v3 canonical input and fingerprint, commit one durable run, then
   dispatch its public ID to the configured Render Workflow task. Immediate dispatch
   failure ends the still-unclaimed run safely and permits Generate Again.
4. The on-demand task claims that exact run, leases it, builds from only the snapshot,
   solves with CP-SAT, and records Building, Solving, Checking, and Saving phases.
5. The independent validator checks exact demand, scope, Planning/HRT authority,
   canonical slots, collisions, locks, fingerprint/source revision, and diversity.
6. Rebuild current authoritative input. Changed inputs end as `stale_input` and
   create no version.
7. Atomically create one unpublished generated/regenerated publication-ready version,
   its entries, links, and succeeded run state. Do not change the active pointer.
8. Polling selects the result for review. Validation and Publish remain separate.

Cancellation ends queued work immediately or requests cooperative cancellation of
leased work. Reload resolves the active durable run. Infeasibility and timeout create
no version. A queued task delayed beyond the configured threshold reports that it is
waiting for compute. The browser never polls Render. Regeneration is unavailable
when all source lessons are locked.

## Common Customer Feature Decision Flow

1. Resolve the authenticated operational user and authorized SchoolGroup.
2. Require the registered user permission; denial ends the decision.
3. For branch-scoped actions, require accessible tenant branch scope and a
   matching academic year when supplied.
4. Resolve one coherent commercial state and active workspace entitlement.
   Paid, promo, demo, and internal sources remain distinct; inactive,
   expired, suspended, missing, or ambiguous evidence fails closed.
5. Require an active catalog definition. Developer-only `feature.audit_log`
   is explicitly outside the customer baseline.
6. Resolve normal customer availability from the common policy. Optional,
   beta, disabled, or custom features continue through their explicit policy.
7. For branch-scoped work, resolve an active coherent BranchEntitlement.
8. Apply capacity or consumption separately. Feature availability never grants
   additional branches, staff users, teachers, or AI provider usage.

Allocation XLSX/PDF use this flow with `feature.advanced_reporting` and
`reports.export`. Starter, Professional, Enterprise AI, active promo, and active
demo therefore share availability while permission, scope, branch entitlement,
and lifecycle continue to win.

## AI Availability And Consumption Flow

1. Resolve enabled AI definition, tenant workspace, `ai.use`, commercial source,
   and the shared `module.ai` baseline.
2. Return availability independently of consumption. A globally disabled AI
   definition remains unavailable.
3. Resolve consumption policy by entitlement source. Demo Standard retains two
   successful uses per feature; Full is unrestricted; Custom may set legitimate
   allowances. Paid and promo currently have no configured provider ceiling
   because no executable provider-backed AI route exists.
4. Reserve by operation key, execute outside the entitlement service, and
   complete successful or failed accounting exactly as before.

## SchoolGroup Management And Branch Capacity Flow

1. School Management resolves the authenticated identity and registered permission.
2. Direct SchoolGroup create/delete additionally requires a Platform identity and
   `schools.manage_all_schools`; tenant users fail before validation or side effects.
3. A tenant with `schools.edit` may update only the SchoolGroup resolved from the
   tenant link/scope. Platform users require global management capability for an
   arbitrary SchoolGroup.
4. The page resolves branch usage and limits through unified commercial authority.
   It shows customer-safe used/allowed state and only shows branch creation when one
   more active branch is currently permitted.
5. Branch POST requests independently re-resolve tenant scope, lock the SchoolGroup,
   recount capacity, and reject stale or over-limit requests before insertion.
6. For promo authority with remaining capacity, the same transaction creates the
   branch, promo assignment, and active branch entitlement. At capacity it changes
   nothing.
7. The last-active-branch check counts only active branches in the target
   SchoolGroup.

## Existing Workspace Owner Alignment And Conversion

## Existing Workspace Paid Activation

1. A verified tenant owner opens Organization Account and selects **Choose a Plan**.
   TIS displays all currently eligible paid plans. If the open activation is `draft`
   or `checkout_ready`, its plan is highlighted but the owner may select another
   eligible plan. Opening or changing this selection calls no Paddle API and creates
   no PaymentAttempt.
2. TIS locks and validates the `customer`/`provisioning` SchoolGroup, exact owner
   link, absence of commercial authority, and absence of conflicting paid, promo,
   or demo activity.
3. TIS recounts active operational branches and organization-wide staff users and
   teachers. Professional and Enterprise AI require all active branches. Starter
   remains unavailable until complete restricted-branch enforcement is proven.
4. The owner confirms the workspace billing profile. TIS builds an authoritative
   USD quote from the active plan price and stores branch-selection and quote hashes.
   Changing an editable selection recalculates this quote and safely supersedes the
   unfinished local draft without changing any branch.
5. Preparation creates a SchoolGroup-anchored contract, paid-activation aggregate,
   immutable branch snapshot, and checkout session. It creates no pending
   organization, provisioning job, workspace, tenant, or entitlement. Until launch
   creates a real PaymentAttempt, Organization Account continues to show Activation
   required rather than Payment processing.
6. A `checkout_started`, `payment_processing`, manual-review, or inconsistent
   activation cannot be silently replaced; plan changes fail closed until that
   payment path is resolved. Launch revalidates the current quote and either reuses a still-billed matching
   Paddle transaction or creates one automatic-collection transaction with branch
   quantity and stable authority metadata. Customer, address, and business mappings
   are reused only through explicit account/workspace attribution. The workspace
   association records the selected address and business, and every returned or
   reused transaction must match the complete current billed quote and custom lineage.
7. Browser return never activates access. `transaction.paid` displays processing.
   Failed, cancelled, or expired attempts instead display a recovery state.
8. A signature-verified `transaction.completed` locks the SchoolGroup and activation,
   revalidates all local and provider evidence, and atomically creates the paid
   subscription authority, active branch entitlements, and paid tenant link. The
   existing workspace becomes active without tenant provisioning.
9. Duplicate webhooks are idempotent. Quote drift, capacity drift, branch drift,
   stale transactions, provider mismatch, or a competing commercial source fail
   closed without partial authority. PostgreSQL lock acquisition refreshes the
   activation state before duplicate-event decisions.

Guardrails:

- `workspace_classification` remains `customer`; paid versus promo is commercial-source evidence.
- Paddle quantity is branch count only. Staff and teacher totals affect eligibility only.
- Existing operational and academic rows are never recreated or mutated by activation.
- Promo activation and PendingOrganization/new-organization checkout retain their
  existing independent selection and payment behavior.
- Organization Account remains available while operational access is blocked for recovery.

## Controlled Existing Workspace Conversion

1. A Platform Owner runs the M4B CLI in dry-run mode with the exact workspace
   tuple, intended-owner email, current M4A hash, operation UUID, and idempotency
   key. No row is changed.
2. Write preparation requires PostgreSQL, Platform Owner approval/execution
   identities, and `PREPARE <operation UUID>`. It locks the workspace, reruns
   M4A, rejects stale or conflicting evidence, and records an ownership claim.
   It does not create an account or send email.
3. The intended owner registers normally, establishes a password or approved
   external identity, and verifies the exact email. Login continuation opens
   the existing-workspace setup review.
4. The verified owner explicitly claims the workspace. TIS rejects unverified,
   suspended, duplicate, cross-tenant, or platform identities, safely reuses or
   creates the operational owner identity, and creates a `tenant_owner` account
   link with no pending organization. A different current owner requires prior
   transfer approval.
5. The owner confirms existing organization identity and supplies only legal
   name, official IANA timezone, and educational program. Branches and all
   existing operational records remain unchanged.
6. Final CLI execution requires `CONVERT <operation UUID>`. It locks the
   operation and SchoolGroup, performs a fresh M4A audit, and requires unchanged
   identity, branch/dependency evidence, one active internal entitlement, no
   commercial source, complete setup, and unique verified ownership.
7. One commit ends the internal entitlement and sets `customer / provisioning`.
   It creates no replacement entitlement or tenant link. Any failure rolls back
   all conversion changes and records only redacted failure evidence.
8. M1 resolves `activation_required`. Organization Account remains accessible,
   normal operations remain blocked, and M3 promo activation is offered. The
   existing-workspace Paddle path remains hidden until its separate milestone;
   new onboarding checkout is unaffected.

## Existing Workspace Conversion Audit

1. An operator supplies the exact SchoolGroup ID, workspace UUID, expected
   organization name, and intended owner email to the standalone M4A CLI.
2. The CLI requires deployed PostgreSQL and begins a repeatable-read, read-only
   transaction before the first application query.
3. The service validates the exact workspace tuple, resolves normalized owner
   identities and links, and inventories tenant, provisioning, entitlement,
   paid, demo, and promo evidence.
4. For every target branch, the service follows reflected direct and indirect
   foreign-key descendants and separately reports branch-like columns without
   a foreign key. Soft-deleted rows remain blocking. Foreign keys absent from
   ORM metadata force manual review. It returns counts and paths, not private
   row payloads.
5. Identity mismatch, duplicate ownership, existing non-sandbox commercial
   authority, unavailable schema evidence, or uncertain traversal produces
   Manual Review Required. An active internal-sandbox entitlement is expected
   and is not treated as customer authority.
6. The CLI writes deterministic sanitized JSON or text with the observed
   transaction mode and a stable SHA-256 evidence hash. Exit `0` is coherent,
   `1` is execution/configuration failure, `2` is manual review, and `3` is
   identity mismatch. Archival candidates include only active dependency-free
   branches; hard deletion and write conversion remain unapproved.
7. The CLI rolls back and closes. It never archives, deletes, aligns, converts,
   calls Paddle, or sends email.

## Customer Promo Activation

1. A verified organization owner chooses Use Promo Code after setup review or
   from an eligible existing Organization Account.
2. TIS HMAC-normalizes the submitted code, validates approval, lifecycle,
   dates, replacement, target scope, owner relationship, redemption policy,
   source compatibility, and setup readiness, then creates a short-lived
   resumable activation session. The raw code is never stored.
3. TIS shows authoritative branch, system-user, and teacher usage. If eligible
   branches exceed the grant, the owner selects exactly the grant count. If
   fewer exist, all are selected and the remainder stays available for future
   branch creation.
4. Excess staff or teachers blocks activation and identifies each exceeded
   dimension. TIS does not disable, select, delete, or change those records.
5. Final activation locks session, promo, and workspace, then repeats every
   validation and recount. It rejects internal sandboxes and every conflicting
   commercial source.
6. One transaction creates immutable redemption/grant snapshots, explicit
   branch assignments and entitlement states for the complete preserved branch
   inventory, a promo workspace entitlement, the promo-sourced tenant link,
   customer/active lifecycle, and redacted audit. Selected branches are assigned
   and active; every unselected branch is explicitly inactive without changing its
   operational status or consuming grant capacity.
7. A pending session grants nothing. Active access resolves through M1 and only
   selected branches are queryable. Expiry or inconsistent evidence fails
   closed. No Paddle call or payment object is involved.
8. Reactivating an unassigned branch locks the SchoolGroup, recounts M1 usage, and
   either rejects at capacity or commits operational status, one grant assignment,
   and active branch entitlement together. Bulk reactivation applies the same rule
   to the complete batch and rolls back all changes on any conflict.
9. `scripts/reconcile_promo_branch_entitlements.py` targets one SchoolGroup and
   workspace UUID. Dry-run reports only safe missing inactive evidence. Explicit
   apply revalidates under lock and inserts only those inactive entitlements;
   ambiguous authority, ownership, assignments, or entitlement lineage requires
   manual review.
10. An authorized owner opening Organization Account Billing & Subscription is
    routed by the selected workspace's authoritative source. Promo authority renders
    Commercial Access with the grant plan, safe status/window, masked reference, and
    M1 branch/system-user/teacher usage and remaining capacity. It never invokes the
    paid subscription resolver, Paddle billing history, invoices, plan/quantity
    changes, or cancellation while promo access is active.
11. Operational promo access ends exactly at `effective_to`. Before that instant the
    grant is active; at that instant and through `grace_period_days` it is expired in
    a recovery period; after grace it remains expired. Both expired states block all
    normal tenant operations while preserving Organization Account and tenant data.
12. A verified owner may begin paid continuation only for recovery-period or expired
    promo authority. Plan selection and Paddle checkout reuse the existing SchoolGroup
    and M4C quote/identity lineage. Pending, failed, canceled, expired, or abandoned
    checkout does not end promo authority or restore expired operational access.
13. `transaction.completed` locks the SchoolGroup and activation, revalidates current
    capacity, quote, provider identity, promo source, and paid evidence, then atomically
    ends the promo workspace entitlement, relinks the sole tenant source to the paid
    contract, establishes paid workspace and branch entitlements, and records immutable
    conversion audit. Duplicate confirmation is idempotent; conflicts roll back the
    authority transition and enter manual review.
14. Active promo early conversion is blocked. Promotional value is not a paid credit,
    and no proration or unused-promo-value calculation is invented.

## Platform Promo Definition

1. A Platform Owner or permission-authorized Developer opens Promo Codes.
2. Create validates one active Starter, Professional, or Enterprise AI tier,
   exact positive capacity through the shared plan-capacity service, coherent
   scope anchors, dates, expiry XOR, and redemption policy.
3. TIS generates at least 100 bits of secure random code material, normalizes
   with NFKC/uppercase/separator removal, and derives an HMAC-SHA256 lookup hash
   with `TIS_PROMO_CODE_HMAC_SECRET`. Missing configuration fails closed.
4. The draft and allowlisted audit commit. The raw code appears once in a
   no-store/no-referrer response; subsequent pages show only its mask.
5. A Developer may edit Draft, pause Active, duplicate, or create a linked
   replacement definition when authorized. Active material edits first require
   pause, clear approval, increment version, and return to Draft.
6. Only a Platform Owner may approve/activate or terminally revoke with a
   reason. Lifecycle transitions lock the row through validation, mutation,
   audit insertion, and commit.
7. No Platform definition step grants access or calls Paddle. Customer M3
   activation is a separate owner-authorized transaction.

## Organization Profile Save

1. The customer opens the owned pending organization's Organization Profile.
2. The browser submits the existing multipart POST with a required controlled
   educational-program value and an optional logo.
3. TIS normalizes National, International, or Both and validates all profile
   fields. Customer-correctable input returns the same page with preserved
   text/select values.
4. When a logo is supplied, TIS reads no more than the 4 MB boundary, decodes
   the actual image as PNG/JPG/WEBP, checks dimensions, and ignores the
   customer filename when creating the opaque stored filename.
5. TIS writes the new image to a temporary sibling and atomically promotes it.
6. Organization changes, progress, activity, and events commit together.
   Only after commit is an obsolete prior pending logo removed.
7. If logo storage or a later database step fails, TIS rolls back the
   transaction, removes the newly written file, retains the prior logo
   reference, logs the traceback, and renders a customer-safe error.
8. The successful response redirects to Branch Setup. No duplicate pending
   organization or operational workspace is created.

Pending logo files currently live on the application-local filesystem. Durable
Render operation requires a separately approved persistent disk or object
storage architecture. The owner-only workspace deletion workflow currently
removes database records but does not yet perform transactional cleanup of
pending or promoted organization-logo files on the filesystem.

## Organization Logo Activation

1. Successful Organization Profile save stores a safe relative pending-logo
   path; setup and checkout pages render only its public static URL.
2. Organization Profile and the shared setup identity header show the customer
   logo and organization name while the official TIS mark remains platform
   branding.
3. Checkout does not move or remove the pending image.
4. Paid and demo activation both call `create_workspace_records()`.
5. Provisioning resolves the pending path only inside the pending-logo
   directory, requires the file to exist, decodes it again, and writes a new
   organization-owned branding file.
6. A primary `SchoolGroupLogo` row stores the final relative path and an
   organization-name label. `SchoolGroup` has no direct logo field.
7. The operational shell resolves that row through the protected
   organization-asset route, renders it with contain sizing, and keeps the
   official TIS logo separately visible.
8. Missing pending source data blocks activation for correction instead of
   producing an active workspace with silently lost branding.

## Branch Estimate Rendering And Save

1. The service loads active branch rows and computes capacity totals in Python.
2. Null, missing, or malformed display values contribute zero; mixed valid
   integer values continue to total normally.
3. The template receives normalized totals and renders null row fields as zero,
   avoiding Jinja `int + None` failures.
4. Every customer save still requires explicit non-negative whole-number
   values for estimated system users and teachers.
5. Newly created pending branches receive explicit zero defaults before their
   submitted values are applied.

## Combined Subscription Capacity And Custom Contact

1. Each active onboarding branch supplies required non-negative system-user and
   teacher estimates; TIS sums them across the organization.
2. Before payment, system-user and teacher authority is independently the
   greater of the estimate total and actual same-workspace active data. After
   activation, actual active data is authoritative. Every active tenant
   operational User counts as staff regardless of position, so an operational
   teacher-user with a Teacher record consumes one staff slot and one teacher
   slot.
3. A self-service plan is eligible only when all three counts fit: Starter is
   1 branch/5 system users/25 teachers, Professional 5/20/100, and Enterprise AI
   25/100/500.
4. The lowest eligible plan is recommended; higher eligible plans remain
   selectable. Ineligible cards explain every failed dimension. Exceeding
   twenty-five branches, 100 system users, or 500 teachers emphasizes the
   always-visible Custom contact action.
5. Selection and every quote, checkout, Paddle, and payment-validation boundary
   repeats the same server-side decision.
6. A pre-payment branch estimate change retains an eligible higher
   plan, but clears an undersized selection and supersedes its checkout and
   attempt so stale payment cannot activate the workspace.
7. On a paid workspace, every tenant operational-user creation/reactivation and
   teacher creation/year-copy preflight requires remaining capacity. Blocked
   operations create no partial user or teacher data.
8. A downgrade is blocked separately by current branches, system users, or
   teachers. Existing data is preserved.

## M1 Operational Commercial-Capacity Enforcement

1. The route first validates the existing permission and tenant scope.
2. TIS locks the owning SchoolGroup with `SELECT ... FOR UPDATE`; internal
   multi-tenant operations acquire locks in ascending SchoolGroup ID order.
3. The commercial authority facade composes classification/lifecycle,
   workspace entitlement, tenant link, contract, confirmed subscription,
   commercial access, demo lifecycle, and plan capacity.
4. The service recounts active branches, distinct active tenant operational
   users, and active teacher people. Known teacher IDs are normalized and
   deduplicated; blank legacy identities each count independently.
5. Paid limits use confirmed branch quantity capped by plan maximum plus the
   plan staff and teacher limits. Pending subscription changes do not increase
   capacity. Demo and Internal Sandbox are unmetered only when their existing
   authority resolves coherently.
6. TIS evaluates deltas or proposed absolute totals across one or several
   dimensions and returns a structured safe decision.
7. Allowed branch, user, teacher, year-switch, or provisioning mutation occurs
   before the same transaction commits. A denial rolls back and exposes no
   provider or internal identifiers.
8. Existing over-capacity data remains accessible and may be reduced; only a
   further increase in an already exceeded dimension is blocked.

The separate Next.js landing page presents the same four-plan structure and
organization-wide limits. The hero Subscribe Now action scrolls to pricing.
Starter, Professional, and Enterprise AI retain their published monthly and
annual per-active-branch prices and enter the configured public signup route
with an allowlisted preferred-plan code. That code is a presentation
preference only: signup creates no plan selection, checkout, payment attempt,
or Paddle object. After organization setup, TIS applies it only when the live
plan remains active and eligible across branches, system users, and teachers;
otherwise TIS clears it and asks the customer to review eligible plans. Custom
has no fixed public price, uses only the Contact the TIS Team mail action, and
never starts signup or Paddle checkout.

## Initial Subscription Plan Capacity

1. TIS counts the current organization's authoritative active billable
   branches.
2. Starter is eligible for one branch, Professional for up to five, and
   Enterprise AI for up to twenty-five. Higher-capacity plans remain available
   below their limits.
3. Plan cards retain per-branch pricing and explain their branch and staff
   limits. Ineligible plans are disabled; above twenty-five branches the
   customer is directed to contact the TIS team for a custom plan.
4. The server repeats the capacity decision during selection, quote creation,
   checkout preparation and launch, and payment validation.
5. If pre-payment editing makes the selected plan too small, TIS clears that
   selection, supersedes its quote and checkout lineage, and requires a new
   eligible plan. An eligible higher plan remains selected.
6. After activation, branch-capacity changes continue through Subscription
   Management.

## Fixed-Quantity Initial Checkout

1. Before confirmed payment, customers may add, edit, remove, reorder, or
   reprioritize onboarding branches while keeping at least one active branch.
   A demo SchoolGroup, tenant link, customer, or prepared checkout does not
   close editing.
2. A legacy `ready_for_checkout` pre-checkout billing state is eligible for
   safe preparation. The original incident was a local rejection in
   `_ensure_checkout_launchable()` before TIS called Paddle.
3. If the plan, interval, branches, capacity estimates, or authoritative quote
   change after checkout preparation, TIS supersedes the local checkout and
   unfinished attempt, clears the old quote lineage, and recalculates from the
   current selection and active count. A late old transaction event cannot
   activate that quote.
4. TIS resolves the selected plan, billing interval, active billable branches,
   unit price, and total for the current organization.
5. The customer reviews those values in TIS. For Professional Annual, the
   active mapping is USD 790 per branch, so two branches produce quantity 2
   and USD 1,580 annually.
6. TIS creates one Paddle transaction item using the mapped provider price and
   the exact authoritative branch quantity; quantity is never defaulted to one.
7. TIS reuses an active same-country Paddle address for the same customer, or
   creates one when no compatible address exists. The resolved address makes
   the automatically collected transaction ready. Returned item quantity,
   price, subtotal, and quote fingerprint must agree with TIS before the
   transaction is marked billed.
8. The payment launcher passes only the billed transaction ID to Paddle inline
   checkout after verifying the local attempt, organization, customer, quote,
   and remote billed status. Billed transaction items and quantities are
   immutable; draft, ready, canceled, past-due, unrelated, or mismatched
   transactions are not launched.
9. Paddle completion remains the recurring-subscription authority. Later branch
   changes use the established TIS subscription-quantity workflow.
10. Retry revalidates unpaid checkout eligibility and may replace an incomplete
   or non-launchable session. A reusable started transaction must still be
   billed, automatic, customer-matched, and current-quote matched at Paddle.

## Returning Customer Login And Organization Account

1. SaaS login authenticates and resolves authoritative onboarding, demo,
   workspace-link, lifecycle, and subscription state.
2. Incomplete setup resumes; pending demos open request status; and unpaid
   completed setup opens subscription selection.
3. An activated owner or linked user with account-management permission lands
   on `/saas/account`, the Organization Account Overview. Multiple managed
   organizations require selection before the overview is shown. The HTTP-only
   selected UUID is revalidated against the account's current tenant links and
   permissions on every request before entitlement or billing resolution.
4. The overview exposes Organization Profile, Branches, Billing & Subscription,
   and Account & Security only when ownership or existing permissions allow.
   Restricted or suspended account managers retain permitted billing/recovery
   access, but no active Enter TIS Platform action.
5. Enter TIS Platform is the only Organization Account action into `/login`.
   Linked users without account-management permission retain their approved
   role-based destination and cannot see owner or billing controls.
6. Operational login runs the commercial guard before branch and academic-year
   setup. Protected requests run it before page services. Authentication,
   sign-out, SaaS account, subscription/checkout/payment-return, support, and
   expiry routes remain safe and cannot recursively redirect.
7. Expired-demo Subscribe Now resolves the existing organization, SchoolGroup,
   and active operational branches, offers public plans and monthly/annual
   intervals, then launches existing Paddle checkout.
8. Only confirmed provider payment converts the same workspace UUID, tenant
   link, users, permissions, branches, and data.

Password login, social login, already-authenticated sign-in, post-verification
sign-in, and SaaS root/session restoration use the same destination resolver.

## Platform Owner Demo Operations

1. A Platform Owner opens an existing Customer Demo operational detail.
2. The owner supplies required reason/date/configuration and an operation key.
3. The service validates and locks the same workspace and tenant scope.
4. Lifecycle work reuses M8B7 rules; feature policy uses controlled registries.
5. Material changes create durable customer email/Notification Center records,
   and every attempt records before/after/result references.
6. Profile changes retain usage and never convert the Customer Demo to paid.

## M8B8 AI Entitlement And Consumption Flow

1. Resolve the operational SchoolGroup and reject cross-tenant scope.
2. Require the registered feature's underlying `ai.use` permission.
3. Resolve existing commercial state; demo expiry/restriction takes precedence.
4. Resolve the controlled feature definition.
5. Internal Sandbox is unlimited; Customer Demo checks two successful uses per
   feature; Customer Paid checks eligible plan plus `module.ai`.
6. Reserve an operation key under the locked successful-plus-reserved limit.
7. If reserved, execute the real AI operation outside the entitlement service.
8. Finalize a usable result as successful consumption; finalize failure without
   consumption and release the reservation.

There are currently no executable AI routes, so steps 6-8 are a reusable
contract rather than a fabricated customer feature.

## M8B7 Demo Customer Journey

Submission creates pending status, a request-received email intent, and owner Notification Center events. Normal approval records review evidence then invokes the retryable provisioning service; activation communication exists only after success. Day 6 and expiry create lifecycle events, customer notices, owner notifications, and email intents atomically. Provider delivery occurs outside locks. A coherent expired demo may subscribe and, after authoritative confirmed payment, reactivate and convert the same workspace.

This document describes the major end-to-end flows a developer must understand before changing TIS.

## Public Customer Flow

Flow:

1. Public visitor opens `https://tisplatform.com`.
2. Visitor chooses Request a Demo or Subscribe Now.
3. Visitor reaches SaaS signup at `/saas/signup?intent=demo` or `/saas/signup?intent=subscribe`.
4. SaaS account is created.
5. Email verification is completed when required.
6. Email verification redirects by HTTP 302 to the GET `/saas/login` page.
   Its form submits credentials by POST to `/saas/auth/login`.
7. A fresh verified account with no organization enters the GET
   `/saas/account` dashboard. A supplied continuation is used only when it is a
   known customer GET destination; POST-only, malformed, traversal, and
   external values fall back to Account Setup.
8. The user invokes the existing POST start action and completes organization onboarding:
   - organization details,
   - contacts,
   - branches,
   - academic setup,
   - review.
9. The final commercial-choice page emphasizes the saved intent, while the user may still choose Request Demo or Subscribe Now.
10. Subscribe Now continues to plan selection and the existing Paddle checkout path.
11. Paddle handles payment.
12. Return/cancel page informs the user of checkout navigation result.
13. Paddle webhook confirms payment.
14. Local payment/billing state is updated.
15. Pending organization becomes ready for provisioning.
16. Platform owner reviews/runs provisioning.
17. Operational tenant structures are created.
18. Operational login becomes available through `/login`.

Guardrails:

- Checkout return is not authoritative payment confirmation.
- Public signup must not directly create operational tenant data.
- Provisioning should occur only through the approved flow.

## Demo Request Flow

1. A verified customer completes organization, contact, branch, academic, and review onboarding.
2. TIS presents Request Demo and Subscribe Now.
3. Request Demo revalidates account ownership, verification, onboarding completeness, branch configuration, absence of conflicting payment/provisioning state, and normalized organization-domain eligibility.
4. TIS creates one Pending Review SaaS demo request plus a transactionally unique customer-demo eligibility reservation for the normalized organization domain.
5. The customer can view status and withdraw only while Pending Review.
6. A Platform Owner searches, filters, and sorts the review queue.
7. Approval creates a review record only; rejection requires a reason; owner cancellation is allowed only while pending.
8. A Platform Owner separately starts provisioning for an Approved request.
9. TIS revalidates review evidence, customer-demo intent, commercial/entitlement snapshots, organization completeness, and duplicate absence.
10. One atomic transaction creates the operational workspace through the shared provisioning builder, creates the demo entitlement and demo-sourced tenant link, activates both, and links the request.
11. Failure rolls back workspace records, leaves the request Approved and unprovisioned, and records a retryable failure outcome.
12. Each review, provisioning, and activation action creates durable audit and internal-notification events.

Guardrails:

- Request and approval alone create no SchoolGroup or entitlement.
- Demo provisioning creates no checkout, payment, paid subscription, subscription contract, or Paddle record.
- A prior customer demo request, activation, expiry, rejection, cancellation, or demo-to-paid conversion for the same normalized organization domain blocks a new customer demo. Platform Owners extend/reactivate where separately allowed, or the customer subscribes using the existing workspace.
- Public email providers require an official organization website or domain before a demo request. Internal Sandbox workspaces do not consume customer demo eligibility.
- Non-owner platform users and tenant/customer identities cannot access review actions.
- Duplicate, rejected, cancelled, incoherent, or already provisioned requests fail closed.
- M8B-4 sends no email and does not implement expiration, scheduling, login blocking, or conversion.

## Historical Demo Eligibility Maintenance Flow

1. A Platform Owner opens `/saas-admin/demo-eligibility-maintenance`.
2. TIS scans the demo-domain eligibility ledger and resolves matching organization, account, request, tenant-profile workspace, provisioning, subscription, conversion, and manual-review evidence.
3. Linked or ambiguous reservations remain protected and display their exact blockers.
4. A safely detached row exposes a review action for its exact eligibility ID.
5. The owner types the same ID and confirms permanent removal.
6. TIS locks and re-analyzes that exact row before deletion.
7. Any new blocker aborts and rolls back the action.
8. TIS deletes only the selected primary key, flushes, verifies no row remains for that ID, and commits.
9. A durable audit event records the Platform Owner, eligibility ID, normalized domain, previous status, timestamp, and historical-cleanup reason.

Guardrails:

- Never delete by normalized domain.
- Never expose the workflow to customers, tenant users, or Platform Developers.
- Never use this workflow to override a linked, historical, converted, subscribed, provisioned, or manual-review Customer Demo reservation.
- Do not change the normal one-demo-per-domain rule or the organization-scoped clean-room reset.

## Customer Demo Lifecycle Flow

1. Successful M8B-4 activation records the authoritative demo start.
2. TIS derives reminder due at start plus six days and expiration at start plus seven days.
3. Before Day 6, the resolver returns Active and operational access continues.
4. At Day 6, the resolver returns Reminder Due; the processor creates one customer notification and one per active Platform Owner.
5. At Day 7, access fails closed immediately even if scheduled processing has not run.
6. Apply-mode processing atomically ends the demo entitlement, suspends the SchoolGroup, marks the demo tenant link expired, and records lifecycle events.
7. Web requests redirect to the preserved-data and subscription page; API/download requests receive a safe 403.
8. Existing sessions are rechecked on every protected request. Platform users remain able to inspect the workspace.

Guardrails:

- Use `activated_at`, never request submission or approval, for lifecycle calculations.
- Store and calculate in UTC; convert only customer/owner display values to the organization timezone.
- Expiration never deletes, archives, deactivates branches, or mutates operational tenant data.
- Reminder and expiration actions are idempotent and failure-audited.
- No email, Paddle change, conversion, extension, or read-only expired mode is included.

## Demo-To-Paid Conversion Flow

1. An active, coherently provisioned Customer Demo chooses Subscribe Now.
2. TIS records a requested conversion and continues through the existing M7 plan selection and Paddle checkout.
3. No new operational workspace, tenant link, branch, user, permission, or academic record is created.
4. `transaction.completed` remains the payment authority and establishes the confirmed `SubscriptionContract` and active `PaymentSubscription`.
5. If the existing tenant link is demo-sourced, webhook reconciliation invokes the dedicated conversion service instead of paid provisioning.
6. The service locks and revalidates the request, provisioning aggregate, SchoolGroup, demo entitlement, tenant link, contract, subscription, price, interval, quantity, and tenant ownership.
7. One atomic workspace transaction ends the demo entitlement, creates the subscription-backed paid entitlement, relinks branch entitlements, changes the SchoolGroup to Customer Paid Active, and moves the same tenant link to the confirmed contract.
8. Existing M7 entitlement, workspace-entitlement, and commercial-state resolvers validate the resulting Customer Paid Active state before commit.
9. Success records completion and lets the customer continue into the same operational workspace. Completed conversions no longer enter demo lifecycle processing.
10. Failure rolls back workspace mutations, preserves provider-confirmed payment records, records a safe retryable failure, and may be retried from a later subscription webhook.

Guardrails:

- Never infer conversion from checkout return navigation, onboarding selection, or an unconfirmed payment attempt.
- Never run paid tenant provisioning for a valid existing demo tenant.
- Expired, suspended, ambiguous, cross-tenant, internal-sandbox, already-paid, and incoherent workspaces fail closed.
- Conversion does not change Paddle pricing, subscription mutation, webhook authority, tenant isolation, or operational permissions.

## SaaS Identity Flow

Flow:

1. User signs up through `/saas/signup`.
2. SaaS account/session records are created.
3. User signs in through `/saas/login`.
4. Account dashboard is available at `/saas/account`.
5. User can access profile, sessions, security, billing status, and onboarding state.

Important distinction:

- SaaS account identity is not the same as operational tenant user identity.
- Platform identity is also separate.

Guardrails:

- Do not merge SaaS accounts with operational users unless an approved provisioning flow creates the needed operational records.
- Keep SaaS authentication and operational authentication boundaries clear.

## Payment Flow

Flow:

1. User selects a plan.
2. App creates or references a checkout session.
3. User goes to Paddle checkout.
4. User returns through checkout return or cancel pages.
5. Paddle sends webhook events.
6. Webhook-confirmed payment updates local payment/billing state.
7. Verified payment can make a pending organization ready for provisioning.

Guardrails:

- Webhook confirmation is authoritative.
- Do not use return-page navigation as proof of payment.
- Keep Paddle-specific details inside `saas/` payment/client service boundaries.

## Active Subscription Management Flow

1. Authorized billing administrator opens `/saas/subscription`.
2. TIS resolves one confirmed active subscription, entitlements, lifecycle state, allowed actions, and one operational capacity snapshot covering active branches, tenant operational staff users, and teachers. Paid branch quantity is displayed separately from the current plan's maximum branch ceiling; unused ceiling is not prepaid branch capacity.
3. Review Capacity accepts proposed totals for all three dimensions. It shows confirmed paid branches, required active branches, additional billed branches, the plan ceiling, and the resulting minimum eligible plan. Branch growth may create a combined plan-and-quantity upgrade, while system-user and teacher growth affects eligibility without changing Paddle quantity.
4. Quantity or plan changes are previewed through Paddle; TIS displays provider-returned totals and never recalculates proration.
5. Immediate increases/upgrades use provider payment-failure prevention and remain locally pending until authoritative confirmation. The current confirmed plan and workspace access remain authoritative while the plan change is pending, failed, incomplete, expired, canceled, or abandoned. Thus an active Professional subscription remains accessible while an Enterprise AI upgrade is `payment_pending`.
6. Reductions/downgrades are scheduled for the next billing boundary and retain current local access until verified effective evidence. Live branch, system-user, and teacher counts are revalidated at that boundary; a mismatch enters manual review without applying the lower local entitlement.
7. Scheduled plan or quantity changes may be canceled or replaced before their effective boundary when provider state agrees.
8. Cancellation is scheduled at period end; reversal removes the provider-scheduled cancellation after reauthorization and validation.
9. The centralized lifecycle resolver exposes only actions valid for current provider/local state.
10. Billing Contact is explicit organization-owned state. Initial checkout requires a confirmed billing email, legal/billing organization or school name, and supported country/address data. The active portal view is read-only until an authorized owner or `subscriptions.manage_billing` user selects Edit; validation remains in edit mode, Cancel discards unsaved form values, and login identity is unaffected.
11. TIS saves valid local billing changes before attempting provider synchronization. It reuses the mapped Paddle customer, synchronizes its explicit billing email, creates or reuses one attributable active Paddle Business, persists address/business mappings, updates the active subscription identity, and includes `business_id` on future initial transactions. Provider failure leaves the local profile saved with retry-needed status. The dedicated retry revalidates permission and tenant scope, uses the stored profile and mappings, avoids duplicates, and makes no provider call after successful synchronization. Historical billing documents are not silently revised.
12. Billing history is read from Paddle transactions. `paid` displays Payment received - processing; only `completed` displays Paid and satisfies the existing final processing signal. Invoice download reauthorizes the user and requests a fresh provider URL.
13. Operational login, protected requests, and returning-customer routing use the same contract-linked commercial access projection. The specialized plan-change webhook synchronizes provider subscription status, but the target plan becomes authoritative only after the existing required provider signals are both confirmed.
14. If production provider state is confirmed but local commercial status is stale, an operator replays the attributable stored, signature-verified Paddle webhook through the existing reconciliation path. Operators do not edit subscription or lifecycle status fields manually. Replay may synchronize the current `PaymentSubscription.status`, but it cannot bypass the separate provider payment signal required to activate a target plan.

Guardrails:

- provider and local ownership must match,
- active branch usage cannot exceed a requested reduced capacity,
- target-plan eligibility is evaluated across branches, system users, and teachers before submission and again when a scheduled downgrade becomes effective,
- Paddle quantity contains branches only; system-user and teacher counts never become provider quantity units,
- webhook processing is idempotent,
- ambiguous outcomes enter manual review,
- return pages and local requests are not payment confirmation.
- organization billing identity is tenant-scoped and provider mappings are revalidated before synchronization,
- a saved billing profile in pending or failed provider synchronization blocks new plan and quantity mutations until retry succeeds; cancellation and legacy active subscriptions with no saved profile retain their established behavior,
- provider synchronization logs the safe failed step, provider error code, and HTTP status server-side; provider identifiers and raw diagnostics are never rendered to the customer,
- user login email is never an implicit permanent billing-email authority,
- stale or unrelated organization-level subscription rows cannot supersede the TenantProvisioningLink and SubscriptionContract-linked subscription,
- canceled subscriptions retain access only until the confirmed paid period ends; ambiguous evidence fails closed without being mislabeled as expired,
- renewal guidance is shown only for genuine expiration, not payment processing, past due, paused, suspended, archived, or inconsistent commercial evidence.

## Operational Billing Entry Flow

1. System Configuration includes Billing & Subscription only for a linked
   operational organization owner or user with
   `subscriptions.manage_billing` in the selected tenant.
2. The bridge revalidates the operational session, SchoolGroup scope,
   SaaSAccountUserLink, organization/workspace UUID, and billing authority.
3. The bridge opens `/saas/subscription` for that organization; it never
   duplicates billing UI inside operations.
4. If SaaS authentication is missing, password and social sign-in preserve the
   allowlisted internal subscription continuation and revalidate it against the
   signed-in account before rendering billing.
5. Unknown organizations, cross-account links, unauthorized users, duplicate
   continuation parameters, and external return URLs fail closed. A user with
   multiple managed organizations must resolve an organization before billing.
6. The landing-page Organization Sign In action enters `/saas/login` without an
   operational destination. Activated account managers therefore land in
   Organization Account unless they arrived through the validated billing
   continuation. Enter TIS Platform remains the only explicit operational entry.

## Provisioning Flow

Flow:

1. Pending organization has completed required onboarding.
2. Payment is verified or owner-approved readiness is satisfied.
3. Provisioning job is queued or run.
4. Operational records are created or connected:
   - school group,
   - branch,
   - academic year,
   - initial operational user,
   - permissions/role context,
   - required setup defaults.
5. Provisioning status is updated.
6. Activation/access email may be sent.
7. User enters operational portal through `/login`.

Guardrails:

- Keep provisioning idempotent where possible.
- Do not mix school groups.
- Do not skip platform owner visibility.

## Operational Login Flow

Flow:

1. User opens `/login`.
2. Credentials are verified.
3. Active-user status is checked.
4. Platform users route toward platform context.
5. Tenant users receive branch/year scope.
6. Session and scope cookies are set.
7. User lands on `/platform` or `/dashboard`.
8. Middleware enforces route permissions.

Guardrails:

- Preserve platform vs tenant branching.
- Preserve idle timeout behavior for tenant users.
- Do not bypass permission middleware.

## Platform Owner Flow

Flow:

1. Platform owner logs in through `/login`.
2. Owner lands in platform context.
3. Owner uses `/platform` for organization context and owner/developer controls.
4. Platform Console pending counts include only organizations still requiring setup, review, payment, or incomplete/recoverable activation work.
5. Owner opens Pending Queue for current work or Organization Records for active, completed, rejected, and lifecycle-review history.
6. Owner uses SaaS admin pages for payments and provisioning.
7. Owner can inspect Workspace UUID, Classification, and Lifecycle as read-only metadata on `/platform`.
8. Owner uses `/platform/knowledge` to review KMS health.
9. Owner views/downloads the PDF through protected routes:
   - `/platform/knowledge/booklet`
   - `/platform/knowledge/booklet/download`

Guardrails:

- Platform developers are not owners.
- Owner-only pages must use existing owner access helpers.
- Active tenant evidence takes precedence over stale onboarding status; conflicting completed evidence is labeled Lifecycle Review Required and excluded from the normal pending queue.
- Do not expose KMS PDF through direct static links.
- Workspace classification metadata does not authorize access or change commercial state in M8B-1.

## Workspace Classification Diagnostic And Backfill Flow

1. Operator runs `scripts/diagnose_workspace_classification.py` to inspect every SchoolGroup and its tenant, onboarding, and Paddle relationship presence.
2. Operator runs `scripts/backfill_workspace_classification.py` without `--apply` for a read-only plan.
3. After review, operator reruns with `--apply`.
4. One transaction classifies all pre-M8B-1 records as internal sandbox/test data and records an idempotency marker.
5. A repeated apply reports `already_applied` and changes nothing.

Guardrails:
- The diagnostic and dry run do not change rows.
- Apply does not call Paddle, migrate Al-Andalus, convert workspaces, or change payment/provisioning state.
- Failures roll back the full backfill transaction.

## Commercial State Resolution Flow

1. Resolve the SchoolGroup workspace classification and lifecycle.
2. Resolve exactly one effective workspace entitlement, or use the compatibility-only implicit entitlement for an internal sandbox created outside migration.
3. Validate entitlement type against workspace classification and parse explicit values through the shared entitlement catalog.
4. For customer-paid workspaces, resolve the existing M7 confirmed subscription entitlement and require the linked local `PaymentSubscription` to match.
5. Resolve each branch as inherited, explicitly active, or commercially inactive while independently respecting operational branch status.
6. Return a read-only effective commercial state or fail closed to Manual Review Required.

Guardrails:
- No resolver writes rows or calls Paddle.
- No resolver changes current tenant access, feature checks, branch mutations, onboarding, or provisioning.
- Demo expiration and commercial-state mutation remain later work.
- Cross-tenant and orphan branch entitlement relationships fail closed.

## Knowledge Management Flow

Flow:

1. Developer or Codex reads `docs/AI_PROJECT_CONTEXT.md`.
2. Developer reads master context, project state, engineering docs, relevant ADRs, and module history.
3. Approved change is implemented.
4. `.kms-impact.yml` and the human-readable Knowledge Impact Assessment are completed.
5. Relevant docs are updated:
   - master context,
   - project state,
   - change history,
   - ADRs if needed,
   - module history if needed,
   - AI project context if needed,
   - engineering docs if architecture/module/flow understanding changed.
6. PDF generator runs.
7. PDF snapshot and manifest are regenerated.
8. Knowledge Center checks manifest freshness and health.
9. CI compares the declaration with changed files and blocks stale pull requests, `dev` integration, or `master` deployment.

Guardrails:

- Markdown remains source of truth.
- PDF is generated and must not be edited manually.
- App must not silently rewrite source docs.
- Regenerate button is not implemented yet.

## Timetable Version Compatibility Flow

1. A scoped timetable read resolves SchoolGroup, Branch, and Academic Year.
2. It loads the compatibility operational version: a working draft sourced from
   the active version when one exists after an edit, otherwise the active version,
   otherwise the newest scoped draft.
3. Section and teacher views, XLSX, and PDF use only that version's placements.
4. On the first legacy assignment edit of an active timetable, the service copies
   every placement and intended lock into a new mutable draft.
5. The requested edit changes the draft, increments `edit_revision`, and records
   manual-change evidence. The active pointer and imported history do not change.
6. Later legacy edits reuse the same working draft until explicit version and
   publication workflows are introduced.

Migration flow:

1. Find only branch/year scopes with existing placements.
2. verify Branch and Academic Year resolve to one SchoolGroup or fail the whole
   migration transaction;
3. capture current Planning/settings authority in a deterministic snapshot;
4. preserve and attach every placement to one imported compatibility version;
5. record safe stale reason codes without changing a placement; and
6. create one exact-scope active pointer without fabricating publication approval.

Guardrails:

- Active, superseded, and archived versions are not mutated in place.
- No timetable mutation is allowed without explicit valid tenant scope.
- Planning remains authority for real section-subject demand and HRT fallback.
- Stage 2 executes no generation and treats no display-only block as a solver rule.

Stage 3.5 configuration flow:

1. The administrator selects working days, teaching-period count/duration, and shift start.
2. A block is placed after a teaching period with a duration, or retained as fixed time.
3. One composer walks each day, inserts blocks at deterministic boundaries, shifts later
   teaching periods, and calculates day/end metrics.
4. Settings preview, timetable grid, readiness, assignments, snapshots, and exports consume
   that projection. A valid inserted block is not a readiness blocker; an ambiguous fixed
   time, invalid duration/day/boundary, or conflicting block is.
5. Configuration fingerprint changes make existing versions stale without deleting their
   placements or mutating published history.

Stage 3 derives canonical slots, resolves positive Planning demand (including
HRT), checks allocation/capacity/locks/staleness, and returns stable readiness
blockers and warnings for one exact scope. Ready to Generate means only that inputs
can be submitted to a future solver; no generation action runs.

Stage 4 version/publication flow:

1. Default read resolves an active-derived mutable draft, otherwise active, otherwise
   the newest scoped mutable draft; explicit history selection changes only the view.
2. Immutable history may be copied to a new draft with placements, valid locks, and
   source provenance preserved.
3. Draft placements and locks use exact permissions plus `edit_revision`; locks update
   snapshot authority and any edit returns publication-ready state to draft.
4. Validate Draft checks freshness, demand completion, collisions, canonical slots,
   Planning teacher authority, stale placements, and locks without a solver.
5. Publish rechecks scope, permission, revisions, fingerprint, and validation; locks
   the pointer; supersedes prior active history; and activates atomically.
6. Historical versions remain reviewable, comparable, safely archivable, and
   explicitly exportable. Viewing or exporting never publishes.

## Human / AI Developer Onboarding Flow

Flow:

1. Read `docs/AI_PROJECT_CONTEXT.md`.
2. Read `docs/README.md`.
3. Read `docs/TIS_MASTER_CONTEXT.md`.
4. Read `docs/PROJECT_STATE.md`.
5. Read `docs/engineering/TIS_MODULE_MAP.md`.
6. Read `docs/engineering/REPOSITORY_ARCHITECTURE.md`.
7. Read `docs/engineering/USER_AND_SYSTEM_FLOWS.md`.
8. Read relevant ADRs and module history.
9. Inspect code with `rg` before editing.
10. Make scoped changes only.
11. Update KMS docs and regenerate the PDF if needed.
12. Report the KIA.

Before coding, inspect:

- affected routes,
- models and scope fields,
- permission rules,
- templates/forms,
- tests for the touched module,
- related docs/ADRs/history.

After coding, update:

- `docs/CHANGE_HISTORY.md` for meaningful changes,
- module history for area-specific changes,
- ADRs for major decisions,
- engineering docs when module maps, architecture, or flows change,
- AI context when onboarding truth changes,
- project state when priority/status changes.
