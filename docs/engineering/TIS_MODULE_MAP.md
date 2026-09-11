---
title: TIS Module Map
documentation_version: 3.5
last_updated: 2026-09-09
source_of_truth: true
---

# TIS Module Map

## Talent Rubric Visuals And Analytics Ownership

- `static/js/talent-rubric-visual.js` and `static/css/talent-rubric-visual.css`: shared arbitrary-label/count rubric ordering, position cue, selected state, and reduced-motion treatment.
- `routers/talent_review_candidates.py`: adds the exact Assessment's highest recorded rubric level to authorized Review read projections only.
- `talent_learner_profile_service.py`: resolves competency and rubric labels/order for authorized historical assessment evidence.
- `static/js/talent.js`: keeps Organization Overview selective and routes detailed Program, Branch, matrix, and longitudinal exploration to their owning views.
- `routers/students_ui.py` and `templates/students.html`: present the existing Learning Style distribution through Planning-derived Branch/Grade/Section choices; the API and privacy provider remain unchanged.

## Talent Program And Evaluation UX Orchestration

- `routers/talent_ui.py`: projects Program, Plan, Cycle, Assessment, and related
  action permissions into the browser; Evaluation Plan manage/govern keys are
  included, and Branch scope suppresses organization-only govern presentation.
- `static/js/talent-program-workspace.js`: searchable Program table and the
  Basics -> What we assess -> Evaluation schedule -> Ready setup journey over
  existing Program/Framework APIs.
- `static/js/talent-evaluation-workspace.js`: standard schedule and simple
  evaluation states; sequences existing Plan, Period, Cycle, population-preview,
  and open APIs without owning domain state.
- `static/css/talent-program-workspace.css`: compact table, guided-step,
  competency/achievement, and schedule presentation.

## Student/Talent Migration Prerequisite

- `db_migrations.py`: migration `20260904_000` ensures PostgreSQL-valid
  `(id, school_group_id)` keys for Branch, Academic Year, and any existing
  Student table, with equivalent-key detection and duplicate-data failure.
  The M4 Cycle creation omits only its future M8 Period FK; M8 adds it after the
  parent exists.
- `scripts/run_migrations.py`: baseline metadata excludes all Student/Talent
  migration-owned tables so the ordered `000` through `20260905_001` chain is
  authoritative on fresh and existing schemas.
- `tests/test_postgresql_migration_transactions.py`: reproduces the prior
  PostgreSQL failure/rollback and validates fresh-chain order, every composite
  target, late prerequisite application, idempotency, and duplicate failure.
- `tests/test_render_startup.py` and `tests/test_student_academic_foundation.py`:
  enforce the baseline deferral and migration registration boundaries.

## Talent Results & Analytics UI (M11 Phase C)

- `routers/talent_ui.py`: permission-gated server-rendered routes and public Results titles.
- `templates/talent/workspace.html`: shared Talent shell, sticky Results subnavigation, Academic Year/Program/metric/dimension controls, and live status region.
- `static/js/talent.js`: consumes only existing M10 API projections and renders Organization, Program, Branch, Talent Map, Students Across Programs, Students, and Progress Over Time views. It owns presentation and navigation only; no metric calculation or authorization.
- `static/css/talent.css`: scoped responsive cards, progress visuals, accessible matrices, categorical privacy/no-data states, focus treatments, sticky context navigation, and reduced-motion behavior using shared TIS design tokens.
- `tests/talent_results_experience.test.cjs`: presentation, friendly-language, privacy-leak, matrix, error-state, responsive, and accessibility invariants.

The UI does not own analytics semantics. M9/M10 privacy closure, access, paging, and comparison rules remain authoritative. Historical Cycle/Population snapshots remain valid analytics provenance where those existing projections consume them, but ADR 0035 supersedes frozen population as the operational eligibility gate for starting Student Assessments.


## B11 Production Qualification Boundary

- `talent_organization_analytics_providers.py`: F1 production provider module.
  It accepts only the externally configured approved cohort value 5 and breadth
  values 1000/1000/1000; missing, invalid, mismatched, rejected, and exceptional
  state fails closed. Its deterministic local path requires non-production and
  the exact `.local_test_data/talent_local_test.db` URL.
- `talent_analytics_privacy.resolve_privacy_policy_provider`: lazily resolves
  the configured P1-P7 cohort policy and retains the existing primary-then-
  complementary suppression engine. There is no permissive fallback.
- `saas.customer_feature_policy` and `saas.demo_feature_registry`: register
  `feature.organization_intelligence` as a normal customer feature.
  `saas.entitlement_service.organization_feature_available` resolves only
  active commercial/feature state and does not perform permission checks.
- `talent_org_intelligence_service`: availability and breadth dependency seams
  now resolve F1 providers. Availability still runs before the separate
  `talent_analytics.view` permission check, and breadth rejects without
  truncation.
- `tests/test_talent_organization_analytics_providers.py`: cohort boundary,
  complementary suppression, configuration failure, entitlement/permission
  separation, exact breadth boundaries, local-path, seven-route accessibility,
  and production-environment fail-closed coverage.
- ADR 0028 governs the approved provider values and B11-E release gates. F1
  resolved the provider implementation gate. As of 2026-09-09 (ADR 0028/ADR
  0030), B11-E is CLOSED WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT
  VERIFICATION ITEM REMAINING and B11 overall is CLOSED on that same basis;
  B12 is CLOSED.
- B11-C is CLOSED after PostgreSQL 16.15 profiling of all seven routes and a
  PASS WITH NON-BLOCKING OBSERVATIONS independent re-review. Query counts were
  bounded with no N+1; no index, schema, migration, permission, privacy, or
  entitlement semantic change was made.
- B11-D is CLOSED after READ COMMITTED qualification proved mixed snapshots
  within Overview and Student Drill requests. REPEATABLE READ remains a
  governance-required, not-implemented proposal for a dedicated full-request
  M10 transaction boundary. Suppressing-policy concurrency and other route
  reproduction remain B11-E gates; Candidate B trends NO CHANGE and no index
  is approved.

## Talent Organization Intelligence (M10 B0-B9)

- `talent_org_intelligence_contract.py`: non-functional contract types for
  canonical `CellIdentity`, public `PrivacyProjection`, exact `+1`/`-1`
  `RelationshipTerm`, additive `Relationship`, tenant-only future graph
  membership validation, and the V01-V25 ownership/status ledger. Pre-B2
  hardening adds closed string-backed `MetricCode`, `MeasureComponent`, and
  `MembershipGrain` enums plus immutable approved metric mapping metadata;
  coefficient validation requires `type(value) is int` and rejects numeric
  lookalikes that compare equal to `+1`/`-1`.
- `tests/test_talent_org_intelligence_contract.py`: executable B0 conformance
  harness for identity/presentation independence, coefficient and additive
  topology constraints, sign/order/overlap canonicalization, tenant
  separation, inherited privacy-state semantics, forbidden fields/behavior,
  complete vector traceability, and absence of any registered M10 aggregate
  route.
- `talent_analytics_relationship_graph.py`: B1 tenant-bound canonical Cell
  registration, Relationship identity/deduplication, Cell-to-Relationship
  adjacency, structural validation, shared-coordinate reuse, and deterministic
  bipartite connected-component discovery. It imports only the B0 contract and
  Python standard library.
- `tests/test_talent_privacy_relationship_graph.py`: B1 behavioral coverage
  for validation, component topology, bridging, nested Org/Branch/Grade,
  shared Program/Branch coordinates, transposition, overlap symmetry,
  insertion-order independence, and prohibited-dependency boundaries.
- `talent_analytics_privacy_closure.py`: B2 exact `Fraction` RREF and augmented-
  rank analysis, per-coordinate uniqueness, deterministic monotonic closure,
  component-local restriction, structural victim selection, exact-source-only
  derived rates, and all-or-nothing safe derived-payload projection. Its one
  orchestration entry applies M9 primary privacy before closure.
- `tests/test_talent_privacy_reconstruction.py`: executable V05-V25 fixed and
  bounded metamorphic coverage, including free-variable uniqueness, redundant/
  inconsistent systems, nested and row/column attacks, transposition, value
  permutation, no-data/coarsened/restricted semantics, localization, derived
  rates, sibling leakage, monotonicity, and idempotence.
- Boundary: no query/service/router, production privacy threshold/provider,
  permission, entitlement, schema, migration, UI, or production behavior is
  added by B0-B2.
- `talent_org_intelligence_service.py`: B3/B4 immutable access context,
  fail-closed commercial-availability and breadth boundaries, normalized
  context fingerprint, authorized Program universe, frozen-membership base
  query, common status aggregation, Program×Branch/Program×Grade and backend
  totals, independently gated Candidate/Identification membership, Program-
  grain M8 execution, and mandatory `PrivacyClosedProjectionSet` seam.
- `tests/test_talent_org_intelligence_queries.py`: access ordering, tenant/year/
  Branch/filter security, provider injection, current-Placement resistance,
  grouped-query semantics/count, secondary-query omission, M8 grain,
  fingerprint, forbidden vocabulary, and B2 integration-seam coverage.
- `routers/talent_organization_analytics.py`: the single B5
  `/api/talent/organization-analytics/overview` route. It composes scoped
  set-based queries into canonical Cells and equality Relationships, runs M9
  primary privacy then B2 closure, and accepts only
  `PrivacyClosedProjectionSet` at its serializer boundary. Candidate and
  Identification metrics are permission-omitted, and Identification counts
  only `decision == identified`.
- `tests/test_talent_organization_overview.py`: end-to-end B5 authorization,
  tenant/year, historical Branch, metric omission, privacy/no-data, active
  predicate, and safe-serialization coverage.
- B5 checkpoint boundary: at that checkpoint no additional M10 route, new
  permission, entitlement mapping, production provider/ceiling, schema,
  migration, Talent Map, or UI existed.
- `talent_org_talent_map.py`: B6 canonical Program-by-Branch/Program-by-Grade
  Cell construction, shared row/column/scope totals and Relationships,
  M9/B2 closure orchestration, exact-source rate derivation, and a serializer
  accepting only its privacy-closed wrapper.
  Sparse totals use one shared authoritative-child helper for both arithmetic
  and graph terms; empty totals remain `no_data` and one-child equalities stay
  connected for privacy closure.
- `routers/talent_organization_analytics.py`: additionally exposes only
  `/talent-map`, enforcing metric/dimension/filter/secondary-permission and
  injected breadth boundaries before set-based aggregation.

- `tests/test_talent_organization_talent_map.py`: B6 route, scope, metric,
  permission, breadth, transpose, totals, no-data, serializer, and 2x2
  reconstruction coverage.
- B6 adds no new permission, entitlement, schema, migration, production
  provider, ranking, universal score, Program Portfolio, Branch Intelligence,
  overlap, longitudinal, Student drill, frontend, or B7+ route.
  The targeted independent sparse-matrix re-review passed after remediation;
  B6 is closed.
- `talent_org_b7.py`: B7 canonical Program-series and Branch-series Cells,
  authoritative sparse totals, additive relationships, closure, and strict
  closed-wrapper serialization for Portfolio and Branch Intelligence.
- `routers/talent_organization_analytics.py`: additionally exposes
  `/program-portfolio` and `/branches/{branch_id}` with existing access,
  filter, breadth, historical-scope, and secondary-permission composition.
- `tests/test_talent_organization_program_portfolio.py` and
  `tests/test_talent_organization_branch_intelligence.py`: B7 semantics,
  privacy, omission, historical Branch, identity, and serializer coverage.
- B7 itself added no Grade breakdown, Branch execution attribution, permission,
  entitlement, schema, migration, ranking, score, UI, AI, or overlap route.
- `talent_org_participation_overlap.py`: B8 canonical symmetric Program-pair
  P2 Cells, diagonal distinct-participant semantics, privacy closure without
  fabricated additive overlap equations, and strict closed-only matrix
  serialization.
- `talent_org_intelligence_service.py`: adds one set-based B8 aggregation that
  deduplicates `(program_id, student_id)` in frozen authorized scope before a
  canonical Program-pair self-join; only aggregate rows leave SQL.
- `routers/talent_organization_analytics.py`: additionally exposes only
  `/participation-overlap`, with access/filter/breadth gates before aggregation.
- `tests/test_talent_organization_participation_overlap.py`: B8 route,
  diagonal/symmetry/deduplication, scope, zero/no-data, privacy, serializer,
  deferred-domain omission, and breadth coverage.
- B8 adds exactly one contract metric (`participation_overlap` = P2 `count` at
  `program_participation` grain) and no permission, entitlement, schema,
  migration, ranking, score, UI, AI, Candidate/Identification overlap, or B9+.
- `talent_org_student_drill.py`: B9 gate-level P7
  `student_drill_population`/`count`/`distinct_student` Cell fed by distinct
  authorized Students (no per-Student additive relationship), one minimized
  top-level `StudentDrillRow` per Student with frozen Program/Cycle contexts, a strict
  `StudentDrillClosedProjection` closed wrapper that raises `TypeError` for a
  raw SQL row/ORM object/non-visible gate, distinct-Student pagination,
  page/context-bounded Candidate/Identification fetch, and a closed-only serializer.
- `routers/talent_organization_analytics.py`: additionally exposes only
  `/students` (B9), requiring `talent_analytics.view_students` composed with
  `talent_analytics.view` before any identifiable query, reusing existing
  access/filter/breadth primitives.
- `tests/test_talent_organization_student_drill.py`: B9 route, permission
  composition, historical Branch/current-placement-irrelevance, filters,
  pagination, minimization, P7 gate, Candidate/Identification isolation and
  semantics, Learner Profile hint, serializer strict-typing, bounded query
  family, and aggregate-route regression coverage.
- B9 adds no new permission, entitlement, schema, migration, ranking, score,
  AI field, Educator Input exposure, Student-ID filter, UI, or B10+
  (longitudinal) route.
- ADR 0027 (`docs/adr/0027-b10-longitudinal-organization-intelligence-
  contract.md`) records the B10-A "Longitudinal Organization Intelligence"
  architecture as an APPROVED governance decision, and B10-B has now
  implemented it exactly as governed. The route is bounded to one Program/one
  Academic Year, ordered M8 `TalentPlannedEvaluationPeriod` slots (Period =
  order authority via its governed `sequence`; optional linked Open/Closed
  `TalentAssessmentCycle` = evidence authority, consistent with
  `uq_talent_assessment_cycles_period`), exactly nine of the fourteen
  existing `MetricCode` values, one metric per response, `comparable`/
  `not_comparable` states, and no server-computed delta/percent-change. B9's
  own status above is unchanged; B10-B added no new permission, entitlement,
  schema, or migration.
- `talent_org_longitudinal.py` (B10-B): `GET /api/talent/organization-
  analytics/programs/{program_id}/longitudinal`, the seventh Organization
  Intelligence route, added in `routers/talent_organization_analytics.py`.
  Reuses `resolve_access_context`/`authorized_program_universe`/
  `resolve_filters`/`frozen_membership_query` unchanged; fetches the single
  governed M8 Plan (`uq_talent_annual_evaluation_plans_config`) and its
  Period+linked-Cycle series in one bounded query, then aggregates
  population/completed/started/Candidate/identified counts grouped by Cycle
  id in one bounded query each (never one query per Period, never a Student
  ORM fetch or Student-ID set). Every Cell uses `relationships=()` - no
  same-point or cross-time additive Relationship exists anywhere in the
  module, so no `delta`/`change`/`percent_change` field can ever be produced;
  rates reuse `derive_exact_rate`/`project_safe_derived_payload` unchanged.
  `LongitudinalClosedProjection` is the sole strict closed-wrapper
  serialization boundary (`TypeError` on a raw dict/ORM row/unclosed point),
  matching B8's/B9's discipline. Comparability follows the ADR's governed
  precedence (missing/cancelled/no-population reason, then
  `privacy_protected`, then `framework_changed`, then `comparable`).
  Candidate/Identification SQL is skipped entirely unless the selected
  metric requires it AND the actor holds the matching secondary permission.
- `tests/test_talent_organization_longitudinal.py`: route/contract, exact
  nine-metric allowlist and five-exclusion coverage, authorization
  (unauthenticated/forbidden/foreign-AY/foreign-and-unconfigured-Program
  non-enumeration/unavailable/unauthorized-Branch-filter/historical-scope),
  Period/Cycle/Plan lifecycle states (varying cadence, sequence-not-
  insertion-order, draft Cycle, cancelled Period, missing Cycle, no frozen
  population, empty Plan, unlinked ad-hoc Cycle exclusion), Framework
  sensitivity (including the mandatory missing-reason-overrides-
  framework_changed precedence test), privacy (no delta/change/
  percent_change, provider-exception fail-closed, no_data-is-never-zero,
  factual-zero-passes-privacy, privacy_protected comparisons, no second
  privacy evaluation from comparison metadata), rate arithmetic, secondary
  permission query-skip discipline, breadth-before-aggregation shape and
  fail-closed rejection, bounded (non-per-Period) query count, and strict
  serializer-isolation. Independent B10-B security/privacy review passed with
  non-blocking observations; B10 is CLOSED. B11, B12 (closeout), and every ADR 0027 deferred-
  capability/production-gate item remain open.
- B11-A (read-only qualification, completed) confirmed the privacy,
  commercial-availability, and breadth-policy provider seams used by all 7
  M10 routes then had no production implementation and correctly failed closed;
  the F1 provider module documented above subsequently resolved that code gate.
  `talent_organization_analytics_observability.py` (B11-B) adds one
  reusable `OrganizationAnalyticsObservation` accumulator and a dedicated
  `tis.talent.organization_analytics.observability` logger - separate from
  the immutable business/security audit trail in `audit.py` - emitting only
  a bounded allowlist (`projection_family`, `outcome`, `latency_ms`, safe
  structural counts reused from each route's own existing breadth-policy
  inputs, and each provider's coarse missing/available-or-evaluated/
  rejected-or-unavailable/exception outcome). `routers/
  talent_organization_analytics.py` wires this around all 7 routes purely
  observationally (`_enforce_breadth_observed`/`_privacy_evaluated`/
  `_b7_context` telemetry wrappers reuse the exact shape values/decision
  distinctions each route already computes; they never recompute a
  provider decision or alter a response body). A telemetry emission
  failure is swallowed internally and can never affect the HTTP response
  or weaken a fail-closed decision. Query-count instrumentation is
  explicitly deferred to a future "B11-C profiling" phase - no new
  SQLAlchemy event-listener instrumentation was added. See
  `tests/test_talent_organization_observability.py` (22 tests). B11-B is
  implemented/tested and independently security/privacy reviewed with PASS
  and non-blocking observations; B11-B is CLOSED. No schema,
  migration, permission, entitlement, privacy threshold, or breadth limit was
  added by B11-B; F1 subsequently added the governed provider decisions
  without schema or permission changes. As of 2026-09-09, B11-E is CLOSED
  WITH ONE ENVIRONMENT-SPECIFIC DEPLOYMENT VERIFICATION ITEM REMAINING (ADR
  0028); B11 overall is CLOSED on that same basis; B12 is CLOSED.

## Talent Deterministic Analytics (M9, Committed/Pushed On dev)

- `talent_analytics_service.py`: read-only context/filter resolution and
  authorized raw aggregate queries (coverage, rubric level, competency
  matrix, Candidate/Identification counts, query-skip-on-permission),
  execution-summary/period-timeline derivation, comparability outcome
  derivation, and privacy-safe insight composition. No Talent Score/Index/
  KPI mean/median/percentile/bins.
- `talent_analytics_privacy.py`: the provider/interface boundary
  (`TalentAnalyticsPrivacyPolicy`, `PrivacyDecision`), the `Cell`/`Group`
  model, `apply_primary_privacy`, and the `run_complementary_suppression`
  fixed-point engine (identity/value-independent tie-break, max 8 passes,
  fails to non-convergence rather than guessing). `resolve_privacy_policy_provider()` delegates to the governed configuration-driven provider builder; production returns `None` only when approved deployment configuration is missing/invalid (fail-closed); `AllowAllTestPolicy`/
  `DeterministicSuppressionTestPolicy`/`CoarsenWithReplacementTestPolicy`/
  `CoarsenWithoutReplacementTestPolicy` are test-only fixtures, never a
  production default.
- `routers/talent_analytics.py`: `/api/talent/analytics` route family
  (context, overview, rubric-distribution, kpi-distribution, competencies,
  breakdowns/{branch|grade|section}, period-comparison, students). Every
  route runs `apply_primary_privacy` on every privacy-sensitive cell/group
  before any `run_complementary_suppression` call in the same function - a
  structural test in `tests/test_talent_analytics.py` statically enforces
  this ordering. `permission_registry.py` adds `talent_analytics.view` and
  `talent_analytics.view_students`; `main.py` registers the router.
- Governance: no production `TalentAnalyticsPrivacyPolicy` implementation
  exists (open gate, by design) and PostgreSQL performance/concurrency is
  unvalidated (open gate, consistent with every prior milestone). M9 is
  committed and pushed on `dev` at `23ade9a7c6166197140b48a3edbfac849396d580`
  (commit `feat: add deterministic talent analytics`); it is not deployed,
  not production-released, and not merged to `master`.

## Talent Annual Evaluation Planning (M8)

- Operational UI: `routers/talent_ui.py`, `templates/talent/workspace.html`, and
  the scoped `static/js/talent-*-workspace.js` modules orchestrate existing
  Program, Plan/Period, Cycle, Assessment, Candidate, Identification, and
  Educator Input APIs. They add no persistence authority. API permissions,
  organization scope, frozen historical Branch scope, revisions, and audit
  behavior remain authoritative.

- `talent_evaluation_plan_service.py`: Plan/Period lifecycle, normalized
  identity, future-tail ordering, closure, rollover, warning, capability, and
  the canonical Period/Cycle link validator.
- `routers/talent_evaluation_plans.py`: bounded `/api/talent/evaluation-plans`,
  `/evaluation-periods`, and Assessment-Cycle relationship APIs with true AND
  permission and projection security.
- `talent_assessment_cycle_service.py`: preserves M4 behavior for ad-hoc Cycles
  and validates locked M8 context before opening a linked Cycle.
- `models.py` and `db_migrations.py`: Plan/Period persistence, nullable scoped
  Cycle linkage, and bounded configuration audit expansion.

## Talent Learner Profiles (M7, Complete)

- `talent_learner_profile_service.py`: read-only historical aggregation and
  deterministic timeline for one Student; no source-record mutation or profile
  materialization.
- `routers/talent_learner_profiles.py`: permission-composed profile API: base
  profile permission plus independent M6 view permissions for sensitive
  Candidate, Identification, and Educator Input sections/events.
- `routers/students.py`: direct Placement read endpoints use the same stored
  historical Branch authorization rule.

## Talent Review, Official Identification & Educator Input (M6, Complete)

Independent review added write-time historical-Branch authorization for
Educator Input creation/amendment and uniform non-enumerating direct-ID
handling across all three M6 routers.

- Models: `TalentReviewCandidate` (now with `status`/`reviewed_by_user_id`/
  `reviewed_at`), `TalentOfficialIdentification`, `TalentEducatorInput` in
  `models.py`, with M6 contextual extensions to `TalentAssessmentAudit`
  (`review_candidate`, `review_candidate_review`, `official_identification`,
  `educator_input` resource types).
- Authority: `talent_review_candidate_service.py` deterministically evaluates
  the exact M3 Review Candidate Policy/rules attached to a Completed
  Assessment's exact Framework Version and materializes only a qualifying
  result (starting `pending_review`), plus the one-way `pending_review` ->
  `reviewed` transition; it is read-only against Assessment/Result/frozen-
  population data. `talent_official_identification_service.py` records the
  append-only `identified`/`not_identified` decision, gated on a Reviewed
  candidate, exactly one per candidate. `talent_educator_input_service.py`
  resolves and persists historical Placement/Branch/Grade/Section context
  (frozen Cycle context or effective-dated Placement at `observed_at`) and
  manages append-only amendment/supersession lineage.
- API: `routers/talent_review_candidates.py` (`/api/talent/review-candidates`,
  now including `POST .../{id}/review`), `routers/talent_official_identifications.py`
  (`/api/talent/official-identifications`), `routers/talent_educator_inputs.py`
  (`/api/talent/educator-inputs`); `main.py` registers all three routers.
- Permissions: Administrator-only-by-default `talent_review_candidates.view/manage`,
  `talent_official_identifications.view/record`, and
  `talent_educator_inputs.view/add/amend` - each independent of the other
  Talent permission families. `.record` additionally requires organization/
  global access scope. Branch scope uses frozen-member Branch context for
  Review Candidate/Official Identification, and the row's own persisted
  historical Branch for Educator Input.
- Deferred (explicit, not implemented): Official Identification revocation/
  supersession/second decision/re-identification, a generic review-note/
  case-management system, assessor assignment, Learner Profile, analytics/
  Talent Map, AI, Development and Support, and Educator Input analytics/
  export/AI/attachments - see "M6 Governance Review: Decisions (Resolved)" in
  `docs/AI_PROJECT_CONTEXT.md`.

## Talent Student Assessments

- Models: `TalentStudentAssessment` and `TalentStudentCompetencyResult` in
  `models.py`, with M5 contextual extensions to `TalentAssessmentAudit`.
- Authority: `talent_student_assessment_service.py` owns Open-cycle/frozen-member
  creation, expected-revision result mutation, deterministic completion,
  ROUND_HALF_UP KPI provenance, read-only terminal states, and audit entries.
- API: `routers/talent_assessments.py` exposes bounded operations under
  `/api/talent/assessments`; `main.py` registers the router.
- Permissions: Administrator-only-by-default `talent_assessments.view`,
  `.manage`, and `.complete`; Branch scope is evaluated from frozen-member
  Branch context, not current Student Placement. Assessor assignment is absent.

## Talent Assessment Cycles

- Models: `TalentAssessmentCycle`, `TalentAssessmentCyclePopulationMember`,
  `TalentAssessmentAudit` in `models.py`.
- Authority: `talent_assessment_cycle_service.py` derives Draft eligibility,
  performs atomic Open/Close, freezes historical context, and computes the
  canonical population fingerprint. Accepted ADR 0033 permits placement-triggered,
  additive-only synchronization while Open; it locks and revisions the Cycle,
  updates count/fingerprint, and audits every added member.
- API: `routers/talent_assessment_cycles.py` exposes bounded Cycle and
  authorization-filtered population operations under
  `/api/talent/assessment-cycles`.
- Permissions: dedicated `talent_assessment_cycles.*`; population visibility
  and lifecycle governance are distinct from Talent Program configuration.

## Teacher Scheduling Rules Components

- `teacher_scheduling_rules.py`: exact-scope normalized CRUD, rule-shape and
  deterministic conflict validation, canonical slot/target resolution, UI data,
  and unpublished Draft invalidation.
- `models.py` and migration `20260830_001_teacher_scheduling_rules`: rule headers,
  normalized slots and grade/section targets, composite teacher/section scope
  integrity, and migration-order-safe deferred metadata creation.
- `templates/system_configuration_timetable.html` and `main.py`: permissioned
  Teacher Scheduling Rules configuration under Timetable Settings.
- `timetable_snapshot_service.py`: schema-v4 immutable teacher-rule authority and
  constraint fingerprinting.
- `timetable_readiness_service.py` and `timetable_problem_builder.py`: deterministic
  target, workload, availability, hard-conflict, and lock defenses.
- `timetable_cp_sat_solver.py` and `timetable_solution_validator.py`: hard timing
  enforcement, soft preference scoring, and solver-independent parity.

## Guided Curriculum Adjustment UI

- `routers/planning.py`: serves the exact-scope wizard page and continues to own preview/apply HTTP adapters.
- `templates/curriculum_adjustment.html`: five-step selection, impact, teacher-decision, review, and success experience.
- `templates/planning.html` and `templates/subjects.html`: permission-gated entry points.
- `authorization.py`: protects the page and apply operation with `curriculum.adjust`; preview accepts either the established Planning edit permission or the dedicated adjustment permission.
- `curriculum_adjustment_preview_service.py`: exposes target eligibility on teacher suggestions for safe selector filtering.

The preview request carries `requested_transfer_periods`; the preview derives section-specific after values from Planning authority, and apply consumes those fingerprinted values unchanged. `routers/subjects.py` decorates exact-scope catalog rows with effective Current/New Planning demand using `planning_subject_demand_service.py`; `templates/subjects.html` renders uniform values or a **Varies** section breakdown.

`adjustment_type="reduce_only"` uses the same preview/apply services with no target demand or target teacher mutation. `templates/edit_subject.html` and the exact-scope subject route expose effective Planning demand plus a prefilled reduction link when `curriculum.adjust` is allowed.

## Atomic Curriculum Adjustment Apply

- `curriculum_adjustment_apply_service.py`: transaction owner for locking, stale
  revalidation, demand/assignment/rule reconciliation, Draft invalidation, audit,
  concurrency rejection, rollback, and duplicate protection.
- `models.CurriculumAdjustmentAudit` and migration
  `20260829_001_curriculum_adjustment_apply_foundation`: durable applied outcome and
  unique reviewed-fingerprint authority.
- `routers/planning.py`: apply JSON endpoint protected by `curriculum.adjust`.
- `permission_registry.py` and `authorization.py`: dedicated permission registration
  and route enforcement.

## Curriculum Adjustment Preview

- `curriculum_adjustment_preview_service.py`: read-only scope selection, demand
  transfer projection, teacher/capacity suggestions, rule/grouped warnings, Draft
  impact, and deterministic stale-confirmation fingerprint.
- `routers/planning.py`: permissioned JSON preview endpoint; no apply endpoint.
- `authorization.py`: `planning.edit_section` protects the preview route.
- Existing demand, assignment, timetable version, active pointer, and published
  placement models remain read-only inputs in Stage 3.

## Explicit Planning Subject Demand Foundation

- `models.PlanningSubjectDemand`: future section-subject weekly-period authority,
  with scoped integrity, active uniqueness, and retained retirement state.
- `planning_subject_demand_service.py`: single-section and bulk exact-scope
  explicit-first demand resolution with transitional legacy fallback.
- `db_migrations.py`: idempotent Current/New section backfill from grade-matched
  Subjects through migration `20260828_004_planning_subject_demands_foundation`.
- `routers/planning.py`, `routers/teachers.py`, `main.py`, `timetable_logic.py`,
  `timetable_readiness_service.py`, `timetable_snapshot_service.py`, and
  `subject_distribution_rules_ui.py` consume resolved section demand for live
  required-period arithmetic. Snapshot-fed generation therefore receives the same
  authority; publication history remains unchanged.

## Smart Timetable Stage 5.2 Components

- `timetable_visibility_service.py`: active-pointer-only reads and scoped teacher identity.
- `routers/timetable.py`: simplified workflow, working deletion, published routes,
  and backward-compatible canonical lifecycle/mutation conflict responses.
- `timetable_logic.py`: workspace/history lifecycle facts, source linkage,
  mutability, active identity, and validation/approval/publication timestamps.
- `templates/timetable.html`: visible lifecycle steps, immutable history actions,
  Draft-only generation language, and stale concurrency refresh UX.
- `templates/published_timetable.html`: control-free official lesson view.
- `timetable_version_service.py`: working resolution and safe archive/discard.

## Smart Timetable Stage 5.1 Components

- `timetable_conflicts.py`: stable conflict taxonomy, evidence classification,
  safe entity references, public redaction, and legacy adapters.
- `timetable_requirement_projection.py`: deterministic read-only Planning-to-
  timetable requirement contract, exact-scope authority, identity, and provenance.
- `timetable_generation_service.py`: exact-scope enqueue/idempotency, generation
  state, claims, leases, heartbeat, recovery, cancellation, staleness recheck, and
  atomic version persistence; contains no OR-Tools import.
- `timetable_problem_builder.py`: schema-v3 immutable snapshot normalization,
  deterministic lesson IDs, canonical slots, Planning/HRT demand, locks, and
  regeneration source contract.
- `timetable_cp_sat_solver.py`: task-runtime-only CP-SAT model and solve result.
- `timetable_solver.py`: solver-neutral worker contract and the Release 1 CP-SAT
  adapter; it owns no scheduling rules or persistence.
- `timetable_solution_validator.py`: solver-independent hard validation.
- `timetable_workflow_dispatch.py`: lightweight server-side Render client and
  environment-driven task slug.
- `timetable_generation_workflow.py`: registered on-demand task accepting only the
  durable generation run public ID.
- `timetable_generation_worker.py`: reusable single-run executor and optional local
  polling fallback; it is not an always-on production requirement.
- `routers/timetable.py` and `templates/timetable.html`: permissioned enqueue,
  scoped status/cancel, polling, generated review selection, and regeneration action.
- `requirements-workflow.txt`: web/runtime requirements plus pinned OR-Tools 9.15.6755.
- `requirements-worker.txt`: compatibility dependency set for the optional local worker.

## Commercial Feature Packaging Components

- `saas/customer_feature_policy.py`: stable normal-customer and internal-feature
  classification. It does not decide permission, scope, lifecycle, or capacity.
- `saas/entitlement_service.py`: centralized source-aware customer feature
  decision, including permission, commercial state, optional branch/year scope,
  catalog state, and BranchEntitlement.
- `saas/ai_consumption_policy.py`: consumption decision separate from commercial
  AI availability; current demo allowances are preserved without creating a
  provider billing engine.
- `saas/demo_feature_registry.py` and `saas/demo_access_service.py`: Standard,
  Full, and Custom retain the normal baseline; Custom continues to control AI
  allowances, scope, safety, and experimental configuration.
- `saas/promo_redemption_service.py`: new promo activation snapshots the common
  baseline and exact grant capacity.
- `db_migrations.py`: migration
  `20260819_001_capacity_based_customer_feature_baseline` reconciles plan, active
  promo, and active demo operational values idempotently.

The boundary excludes Platform Console, Developer/System Owner controls, global
audit/support export, promo administration, demo administration, and payment
administration. Capacity continues through `commercial_authority_service`.

## SchoolGroup Management Boundary Components

- `main.py`: Platform identity/global capability checks for SchoolGroup create and
  delete, tenant-linked update scope, unified branch-capacity presentation, and the
  SchoolGroup-scoped final-active-branch safeguard.
- `permission_registry.py`: top-level `schools.create` and `schools.delete` are
  developer-only; `schools.manage_all_schools` is the global manual-management
  capability.
- `templates/system_configuration_schools.html`: hides global create/delete actions
  from tenants and presents source-neutral authoritative branch usage.
- `saas/commercial_authority_service.py` and `saas/promo_grant_service.py`: unchanged
  authority and atomic capacity/assignment boundary used by the page and mutations.
- `scripts/audit_schoolgroup_provenance.py`: sanitized read-only detection of active,
  unlinked internal sandboxes without explicit workspace entitlement.

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
- `timetable_version_service.py`
- `timetable_snapshot_service.py`
- `timetable_slot_service.py`
- `timetable_readiness_service.py`
- `timetable_publication_service.py`
- `templates/timetable.html`
- `templates/system_configuration_timetable.html`

Maturity/status:
Implemented and evolving.

Related docs/ADRs:
- `docs/history/workforce-planning/`
- `docs/adr/0026-versioned-constraint-based-smart-timetable-generation.md`

Risks/guardrails:
- Timetable rules interact with planning, sections, subjects, and teacher capacity.
- Planning remains demand/assignment/HRT authority. Placements are version-owned;
  the exact-scope active pointer is separate, active/superseded history is
  immutable, and legacy editing uses a copy-on-write working draft.
- Stage 3.5 owns the canonical composed per-day timeline and exact-scope structural readiness.
  The composer outputs ordered teaching/block items and valid teaching slots; after-period
  blocks shift later clocks while invalid fixed-time placement fails closed.
  It has no solver, worker, availability, room/resource, or Generate UI.
- Stage 4 owns draft validation, publication transactions, same-scope comparison,
  lifecycle presentation, explicit version exports, archive, and draft lock actions.

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
- `tenant_report_branding.py`
- report/export helper code
- `templates/dashboard.html`

Maturity/status:
Implemented and evolving.

Related docs/ADRs:
- `docs/history/workforce-planning/`

Risks/guardrails:
- Report data must be permission-checked and tenant scoped.
- Tenant-facing exports may use configured branch/organization logos only. Missing
  tenant branding produces no logo and must never fall back to the TIS product mark.

## Branding / Design Settings

Purpose:
Manage organization logos, design settings, visual shell behavior, and platform visual controls.

Main files/folders:
- `branding_storage.py`
- `design_tokens.py`
- `tenant_report_branding.py`
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
- Keep product-surface branding separate from tenant-facing report branding.

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
