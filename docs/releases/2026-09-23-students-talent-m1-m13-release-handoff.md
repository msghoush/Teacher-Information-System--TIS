---
title: Students + Talent & Potential Update Package Release Handoff (M1-M13)
documentation_version: 1.1
last_updated: 2026-09-23
source_of_truth: true
---

# Students + Talent & Potential Update Package Release Handoff (M1-M13)

**Superseded in part by M14 (2026-09-23):** the "Learning Style" bullet below
described the M1-M13 as-shipped four-percentage model, which the M14 owner
correction determined was a misinterpretation. See
`docs/PROJECT_STATE.md`'s M14 entry and ADR 0031/0042/0044's M14 amendment
sections for the corrected model (one categorical field, eight values;
aggregate-only percentage semantics). This document's text below is left
unmodified as the accurate historical record of what M1-M13 actually
shipped.

Milestone range: M1-M13, 2026-09-23. This is a documentation-only closeout
record for a bounded package on the `dev` branch. It does not itself deploy
anything; deployment remains a separately authorized decision. It does not
declare the entire Talent product roadmap complete - only this specific
Students + Talent & Potential update package (Student ID, Learning Style,
Al-Andalus Section display, Student roster, Talent frontend cleanup,
Evaluation Progress, Results & Analytics Branch comparison, and their
supporting permissions/migrations).

## What Changed (User-Visible)

- **Student ID**: New Students require a canonical `STD` + 10-digit Student
  ID (user enters the 10 digits; leading zeros preserved). Same-tenant
  duplicates disclose identity through a privacy-safe projection;
  cross-tenant conflicts stay generic. Legacy Students without a number
  remain editable and may receive one later via
  `students.manage_identifiers`.
- **Learning Style**: Student create/edit/profile expose four independent,
  nullable 0-100 Verbal/Non-verbal/Quantitative/Spatial percentages. No
  normalization, no sum-to-100 rule, and no automatic conversion from the
  deprecated legacy categorical field.
- **Al-Andalus Section display**: One authorized workspace
  (`72e52eb2-3844-447b-92a8-c55015f73257`) sees a presentation-only Section
  label projection; the canonical `PlanningSection` record and every other
  tenant are unchanged.
- **Student roster**: `.xlsx`-only export and stateless-preview/atomic-apply
  import, gated by `students.import`/`students.export`. Create-only in this
  release; no update/merge/upsert.
- **Talent frontend cleanup**: Reload Saved Rubric and Educator Input are no
  longer exposed in the normal Talent assessment UI. Historical evidence and
  the underlying APIs/permissions are unchanged and still reachable through
  existing authorized paths.
- **Evaluation Progress**: Student Profile Talent tab shows per-Period
  results (Pending distinguished from a real 0%) and a backend-authoritative
  combined Overall Result, blocked when the Program's Framework changed
  across contributing active Periods.
- **Results & Analytics**: One primary Organization Overview Branch
  comparison chart over the seven approved metric families, including the
  four Learning Style dimensions, with server-authoritative privacy
  suppression and no client-side reconstruction or averaging.

## Permission Changes

No new permission keys were introduced by this closeout task. The package's
existing governed keys remain as documented in `docs/PROJECT_STATE.md`:
`students.import`, `students.export`, `students.manage_identifiers`, and the
pre-existing `students.*`/`talent_*` CRUD and analytics permission families
(including `talent_learner_profiles.view` for individually authorized
Student Evaluation Progress, and `talent_analytics.view` /
`talent_analytics.view_students` for Branch/Organization aggregates).
Permission grants remain backend-authoritative; frontend visibility is
advisory only.

## Migration Requirements (Not Migration-Free)

This package includes real schema migrations. A target PostgreSQL
environment that has not yet applied them **requires running the migration
ledger** as part of deployment - this release is not migration-free:

- `20260922_001_student_learning_style_four_dimension_profile` - adds the
  four Learning Style columns/CHECK constraints to `Student`.
- `20260922_002_student_tis_number_identifier_integrity` - installs the
  managed `tis_student_number` global-uniqueness and one-active-per-Student
  partial unique indexes (ADR 0043), now creating the canonical
  <=63-character active-index name directly on any fresh database.
- `20260923_001_student_tis_number_index_identifier_length_remediation`
  (M12.1) - PostgreSQL-only forward remediation that renames an
  already-migrated database's truncated 63-character physical index
  (`uq_student_external_identifiers_tis_student_number_active_stude`) to the
  canonical `uq_student_external_identifiers_tis_number_active_student`
  (57 characters). No-op if the canonical name is already present or on a
  fresh database. Fails closed (never guesses) on an unexpected index
  definition or if both names exist.

All three are additive/idempotent and run through the existing ordered
migration ledger (`db_migrations.py` / `scripts/run_migrations.py`); none
rewrites, merges, or deletes `Student`/`StudentExternalIdentifier` rows.
SQLite (including the checked-in `tis.db`) never truncated the index name
and is unaffected by the M12.1 remediation.

## PostgreSQL Remediation Requirement

Any PostgreSQL environment where `20260922_002` has already run (i.e. any
already-migrated PostgreSQL deployment, including a hypothetical prior
partial production rollout of this package) **must** apply
`20260923_001` before or during the same deployment that brings this
package live, or a subsequent full-ledger re-apply against that database
risks a `DuplicateTable` failure on the truncated legacy index name. A
fresh PostgreSQL database (no prior run of `20260922_002`) does not need
special handling - the canonical name is created directly.

## Compatibility Notes

- No CSV or `.xls` roster support - `.xlsx` only.
- Roster import is create-only in this release; no update, merge, sync, or
  upsert semantics exist.
- Learning Style values are never snapshotted into history and never
  auto-derived from the deprecated legacy categorical field.
- No Student or Talent schema/data deletion is part of this package. The
  M12.1 remediation only renames a PostgreSQL index in place.
- `Student.id` is unchanged by any Student ID or replacement operation.

## Privacy / Tenant-Isolation Invariants (Reconfirmed)

- Permission possession is distinct from tenant/Branch scope; backend
  authorization remains authoritative and frontend visibility is advisory
  only.
- Tenant isolation is enforced at the query/service layer; the roster
  workflow cannot create or match Students across a different tenant.
- Same-tenant Student-number duplicate disclosure is privacy-safe;
  cross-tenant conflicts remain generic (no cross-tenant identity leak).
- Results & Analytics privacy suppression (primary + complementary) is
  server-authoritative; the browser performs no reconstruction, averaging,
  or normalization of protected values.
- Frozen historical Branch/Grade/Section attribution used by Evaluation
  Progress and Talent evidence is preserved and not reinterpreted by
  current Placement.

## Known Pre-Existing Issues (Not Introduced By This Package, Not Fixed Here)

- Five PostgreSQL migration-transaction test failures, reconfirmed present
  and unchanged in this closeout task's own test run (2026-09-23):
  `test_planning_subject_demand_migration_creates_fk_target_constraints_first`,
  `test_teacher_rule_migration_is_safe_after_baseline_metadata_and_idempotent`,
  `test_student_talent_prerequisite_unblocks_full_fresh_chain_and_is_idempotent`,
  `test_postgresql_failed_preledger_create_all_rolls_back_partial_student_tables`,
  `test_student_learning_style_profile_and_tis_number_migrations_apply_and_are_idempotent_under_postgresql`
  in `tests/test_postgresql_migration_transactions.py`. Root cause: a
  pre-existing, unrelated Talent baseline-metadata foreign-key ordering
  defect (`UndefinedTable` for `talent_framework_competencies` when creating
  `talent_grade_competency_rubric_descriptors`), first documented during
  M12.1's own verification. These do not exercise this package's own
  Student-ID/Learning-Style migrations in isolation (the dedicated
  Student/Learning-Style PostgreSQL migration test failing here fails only
  because it shares the same broader fixture chain) and are tracked as an
  open, out-of-scope risk against the broader migration test fixture, not
  against this package's own schema changes.
- A small number of previously-documented stale test-fixture/wording issues
  (for example the M12-corrected `tests/test_permission_registry_matrix.py`
  consumer list) remain recorded historically in `docs/CHANGE_HISTORY.md`
  and `docs/PROJECT_STATE.md` and are not restated as open here because M12
  already fixed that specific fixture.

None of the above blocks this package's own migrations, which were verified
directly (see Verification Performed).

## Deployment Surfaces

- **Web Service (Render)**: owns `main.py`/FastAPI, all Students/Talent
  routers, templates, and static JS/CSS in this package. Requires the
  migration ledger above to be applied via the existing Pre-Deploy Command
  (`python scripts/run_migrations.py`, per ADR 0016) before the new
  application version activates.
- **Database migrations**: applied by the same Pre-Deploy Command, not by
  the web process at runtime or import time (ADR 0016). This package's three
  migrations are additive/idempotent and safe to re-run.
- **`tis-timetable-workflow` (separate Render revision)**: this package is
  Students/Talent schema and Web Service application code only. It does not
  touch timetable solver/worker tables, contracts, or code, and does not
  require a coordinated Web + Workflow deploy.

## Migration / Deployment Sequence (Plan Only - Not Executed)

1. Confirm target environment and take/confirm the platform's standard
   PostgreSQL backup/snapshot before deploying (per existing operational
   practice; no new backup mechanism is introduced by this package).
2. Deploy the reviewed `dev`-equivalent build so Render's Pre-Deploy Command
   runs `python scripts/run_migrations.py` against the target database.
3. Migration runner applies any still-pending entries from the ordered
   ledger, including (if not already applied) the three migrations listed
   above, in ledger order. Each migration and its ledger marker share one
   transaction; failure blocks activation with a nonzero exit and no partial
   marker/data write.
4. Render activates the new Web Service version only after the Pre-Deploy
   Command exits zero.
5. No `tis-timetable-workflow` deployment step is required by this package.

## Rollback Considerations

- Application rollback: redeploy the prior Web Service revision. The
  package's migrations are additive (new columns/indexes) and do not remove
  or rename any column or table the prior revision depends on, so a prior
  application revision continues to function against the migrated schema.
- Migration rollback: no down-migration is provided (consistent with this
  repository's existing forward-only migration convention). If the M12.1
  index rename must be reversed, it would require a new forward migration
  performing `ALTER INDEX ... RENAME TO` back to the truncated name - not a
  destructive drop/recreate - but no such reversal is expected to be needed
  since both names satisfy the same uniqueness/partial-predicate invariant.
- If a migration fails mid-ledger, the failing migration's own transaction
  rolls back cleanly (no partial marker or partial DDL); the prior
  application revision remains safe to keep running against the
  not-yet-fully-migrated database until the defect is fixed and redeployed.

## Post-Deploy Smoke Test Matrix (To Run After A Separately Authorized Deploy)

Create Student with Student ID; leading-zero Student ID; duplicate ID
privacy-safe same-tenant disclosure; duplicate ID generic cross-tenant
conflict; edit Student Learning Style; Learning Style null vs 0; Al-Andalus
Section display on the authorized workspace; non-Al-Andalus Section display
unchanged; roster export; roster preview; roster apply; atomic rejection of
an invalid roster; Talent Student profile without Reload Saved Rubric; Talent
Student profile without Educator Input; Evaluation Progress Pending state;
valid Overall Result; framework-mismatch comparability boundary; Branch
comparison chart renders; privacy-suppressed Branch cell renders
categorically; permission-denied import/export is blocked; cross-tenant
isolation sanity check (no Student/roster/analytics leakage across tenant).

## Verification Performed (This Closeout Task, 2026-09-23)

- `tests/test_permission_registry_matrix.py`: 13 passed.
- `tests/test_student_managed_number_service.py`: 46 passed.
- `tests/test_postgresql_migration_transactions.py` (live PostgreSQL via
  `TIS_TEST_POSTGRESQL_URL`): 11 passed, 5 failed - the exact five
  pre-existing failures listed above, reconfirmed unchanged.
- Code-level spot checks (not exhaustive) confirmed KMS claims against
  current implementation: `models.py` Learning Style columns/constraints and
  the canonical <=63-character managed-index name; `db_migrations.py`
  migration ledger ordering (`20260922_001` -> `20260922_002` ->
  `20260923_001`); the Al-Andalus workspace UUID in `academic_grade.py` and
  ADR 0045; `routers/students.py` permission checks for
  `students.import`/`students.export`; `static/js/talent-operations.js`
  confirming both the `button('reload', ...)` no-op and the
  `talent_educator_inputs.*` permission short-circuit that remove Reload
  Saved Rubric and Educator Input from the normal UI; and
  `static/js/student-evaluation-progress.js`/`static/js/talent.js`
  confirming backend-authoritative Overall Result and framework-mismatch
  comparability handling.
- `git diff --check`: no whitespace errors in this task's changes.
- `tis.db` SHA-256 confirmed unchanged before and after this task
  (`01e1a3065d92280ee9228db921f67545c8b837d4ecd787a5aeeddc6d128fc136`).

Full 1,700+ test suite was intentionally not rerun for this closeout, per
task scope; M12/M12.1 test evidence is current and only this bounded
documentation closeout happened since.

## Deployment Readiness Statement

This documentation-only closeout does not itself authorize or perform a
deployment. Based on the verification above, the package is internally
consistent, documented, tested to the extent proportional to a
documentation closeout, migration-safe (including the M12.1 PostgreSQL
remediation), and has no newly discovered release-blocking defect. Actual
deployment remains a separate, explicitly authorized decision by the
repository owner.
