---
title: Independent Permission Closure Review
documentation_version: 1.1
last_updated: 2026-09-18
module: architecture
---

# Independent Permission Closure Review

## Review boundary and disposition

The review compares `fix/permission-consistency-closure` commit
`28f98f2ee87c2263698325426d5e42c1e6bd6b8c` with `origin/dev`
`1e5c1797d66a1ff5f24b167a101fe4e2819a956c`. Subsequent corrective work stays
on the review branch. No merge, production migration, data cleanup, deployment,
or complete whole-system security approval is implied.

The original 26 changed files were reviewed: `.kms-impact.yml`; `auth.py`;
`authorization.py`; `db_migrations.py`; `models.py`; `main.py`;
`user_permission_service.py`; `ui_shell.py`; `routers/observations.py`;
`routers/users.py`; `docs/CHANGE_HISTORY.md`; `docs/PROJECT_STATE.md`;
the generated KMS booklet/manifest; `templates/notifications.html`;
`templates/observation_form.html`; `templates/system_configuration_qualifications.html`;
`templates/system_configuration_schools.html`; and these eight test files:
`test_branch_year_permission_boundaries.py`, `test_configuration_scope_permissions.py`,
`test_notification_group_permissions.py`, `test_permission_qualification.py`,
`test_platform_access.py`, `test_role_permission_logical_key_migration.py`,
`test_user_permission_override_routes.py`, `test_user_permission_overrides.py`.

Additional inspection covers teacher and planning routes/forms, the permission
registry, shared shell, application database configuration, migration runner,
Talent guards, commercial/entitlement boundaries, and existing permission,
tenant-isolation, and user-template tests.

## Architecture and classifications

The canonical current-user resolver remains `auth.get_allowed_permission_keys`:
built-in default, global role policy, tenant role policy, then per-user override.
User Deny removes a role grant. User Allow does not resurrect role Deny; its
stored row can reactivate after a role re-grant. ADR 0040 is unchanged.

Current-user authorization (A) and UI capabilities (B) use canonical resolution.
Abstract role summaries (C) in main/users/shell legitimately use the role-only
service. Scope/persona metadata (D), including organization authority and teacher
identity, supplements rather than substitutes for permission guards. Shared
shell `can` uses a canonical, per-render snapshot; it is not a cross-request
permission cache. Remaining `_permission_cache` references are test residue or
comments, not production consumers.

## Confirmed corrections

The independent review corrected notification GET auto-read despite Deny,
inactive platform helper capabilities, Developer creation role choices bypassing
assignment authority, teacher bulk deletion checking the single-delete key, and
teacher/planning edit routes mutating separately protected fields. Read-only
controls do not silently clear persisted values. It also repaired a stale
timetable-block nav assertion and a legacy migration fixture missing the
production bootstrap's role-policy table prerequisite.
The shared Talent/Students test grant helper now updates existing logical keys;
its old duplicate inserts violated the newly installed uniqueness constraints
during re-grant tests.
Tenant resolution now rejects absent ownership, contradictory stored/branch
ownership, missing SchoolGroup parent records, and foreign selected/explicit scopes rather than resolving another
tenant's policy or falling back to global defaults for an unowned actor.
Target management and override writes likewise reject contradictory ownership,
including platform-actor attempts; this does not restrict valid cross-tenant
platform authority.
Branch deletion rejects unowned targets even for platform actors rather than
silently turning a normal delete route into an orphan-data cleanup operation.

## Verification limits and remaining approval blockers

The registry contains 175 keys across 26 groups. Literal consumer coverage is
not proof of enforcement, and route-reference validity is not proof that all
registered capabilities protect their associated workflows.

### 22-key closure pass (this pass)

Every previously-unconsumed key listed in the prior revision of this section
was individually traced against the implemented product (routes, services,
templates, nav, and the route-permission middleware in
`authorization.PROTECTED_ROUTE_RULES`) and classified. `planning.import` and
`planning.export` were already resolved in an earlier corrective pass (real
consumers exist in `routers/planning.py`) and are omitted below; the other 22
keys close as follows.

**Enforced as an existing capability with a dedicated key** (server-side gate
added/aligned; UI aligned to match):

- `dashboard.view_branch_summary` — gates the dashboard KPI/branch-overview
  section (`templates/dashboard.html`) distinct from the Reports tab.
- `dashboard.view_reports` — gates the dashboard's "Reports" tab and its
  panel (`panel-reports`), a real, distinguishable structure separate from
  the Subjects/Teachers/Planning tabs. The base `/dashboard` route access is
  already enforced by `PROTECTED_ROUTE_RULES`.
- `dashboard.export_reports` — required together with `reports.export` (both
  are now real, independently-enforced keys; removing either blocks
  `/reports/allocation-plan.xlsx|.pdf` at the route-guard layer) and gates
  the "Export Report" menu in the template.
- `hiring_plan.export` — required in addition to the base export gate for
  every report-export section whose generated payload includes the
  hiring-plan sheet/section on the two report-export routes
  (`main._authorize_report_export`, gated on
  `REPORT_EXPORT_SECTIONS_WITH_HIRING_DATA = {"full", "hiring"}`), and gates
  the "Hiring Plan Excel/PDF" links. A PR #360 review finding showed the
  initial implementation checked only the literal `section=hiring` value,
  so a caller who retained the base export permissions but was denied
  `hiring_plan.export` could still obtain the same hiring-plan data via
  `section=full` (both `_build_professional_report_xlsx_bytes` and
  `_build_professional_report_pdf_bytes` include the hiring-plan
  sheet/section for `full`). The gate now checks section membership in
  `REPORT_EXPORT_SECTIONS_WITH_HIRING_DATA`, which must stay aligned with
  every section branch in those two builders that emits hiring-plan data.
- `observations.view_reports` — gates `GET /observations/teacher/{id}/history`
  (the aggregated observation-cycle report) for a non-teacher (evaluator/
  admin) actor and its nav link on the observations list; a teacher viewing
  their own cycle remains self-service and is unaffected.
- `observations.sign_evaluator` — is the dedicated gate for actually
  persisting `evaluator_signature_data` on observation create/edit
  (`routers/observations.py::_can_sign_evaluator`); the signature-capture UI
  panel is now hidden without it.
- `configuration.view_audit_log` — reclassified as platform-only (moved into
  `DEVELOPER_ONLY_PERMISSION_KEYS`, matching its sibling
  `configuration.export_audit_log`) and enforced as an additional
  prerequisite under `/admin/audit-log`, alongside the export gate. See the
  real-conflict note below for why it could not remain tenant-assignable.

**Existing capability governed by an explicit alias/composite** (documented,
not a second independently-built gate):

- `observations.submit` — alias of `observations.sign_evaluator`. The
  implementation has no separate "submit without signature" step: applying
  the evaluator signature is the exact action that submits the observation
  for the teacher's review (`_notify_teacher_observation_ready` fires only
  once `evaluator_signature_data` is set).
- `system_owner.manage_developer_accounts` — alias of the existing
  owner-identity gate (`auth.is_platform_owner`) already used for
  `POST /platform/developers` and `POST /platform/developers/{id}/permissions`.
  Owner-only keys are identity-governed by construction
  (`OWNER_ONLY_PERMISSION_KEYS` are never independently assignable), so the
  identity check *is* the enforcement mechanism; the key is now cited
  explicitly in the denial response for both routes for audit/messaging
  consistency, matching the pre-existing pattern already used for
  `system_owner.manage_ownership` / `.transfer_ownership`.
- `system_owner.view_cross_school_audit` / `system_owner.export_cross_school_data`
  — explicit aliases of `configuration.view_audit_log` /
  `configuration.export_audit_log`. The only implemented audit surface is a
  single, non-tenant-filtered log spanning every SchoolGroup; there is no
  separate cross-school-specific audit feature. Both pairs are platform-only,
  and either key in a pair is independently sufficient (`match="any"` on the
  export route rule; `auth.has_any_permission` for the view prerequisite).

**Capability not implemented — classified dormant/reserved** (no route,
service, or user-facing control exists; no UI implies otherwise):

- `hiring_plan.export`'s sibling capability confusion aside, the following
  have zero implementation anywhere in the codebase: `reports.view` (no
  standalone Reports page exists separate from the dashboard's Reports tab,
  which is governed by `dashboard.view_reports`), `teachers.import`,
  `teachers.export` (no import/export route or UI control for teacher data
  exists at all), `subjects.manage_colors` (subject color is always
  auto-derived by `subject_colors.resolve_subject_color`; there is no manual
  color-editing UI or field), `observations.manage_templates` (the
  observation rubric/criteria set is a hardcoded, auto-seeded fixture with no
  create/edit/delete route), `configuration.manage_global_defaults` (no
  "global configuration defaults" workflow exists; already platform-only),
  `system_owner.manage_subscriptions` and `system_owner.create_subscription_school`
  (subscription/billing management is delegated entirely to an external SaaS
  admin surface reachable via `/saas/subscription?...`, outside this Web
  Service's implemented scope), and `system_owner.run_startup_repairs`
  (schema-compatibility repairs — `_ensure_users_table_columns` and siblings —
  run automatically at application startup; there is no user-triggerable
  route this key could gate). None of these keys have any UI control that
  implies a live, independently-gated feature, so no template changes were
  needed to remove misleading affordances.

**Real KMS/implementation conflict (documented, not resolved by invented
policy):**

- `configuration.view_audit_log` was registered as tenant-assignable (not in
  `DEVELOPER_ONLY_PERMISSION_KEYS`) while its only implemented consumer (the
  global `/admin/audit-log` download) is inherently a single,
  non-tenant-filtered log spanning every SchoolGroup. Granting a tenant
  Administrator this key as previously registered would have been a silent
  no-op today, but wiring it naively to the existing endpoint would leak
  cross-tenant audit data — a tenant-isolation violation. Resolved
  fail-closed: the key was reclassified platform-only (matching its export
  sibling) rather than building a new tenant-filtered audit viewer (out of
  scope for this pass) or granting tenant-scoped access to global data. A
  future tenant-scoped audit viewer, if built, is a distinct, separately
  governed feature decision.

Owner-only commercial identity authority is a distinct governed boundary and is
not automatically removed by an operational role-policy Deny.

Ten-family ON/OFF/ON tests use persisted policies and fresh SQLAlchemy sessions,
real route guards, and navigation builders. They are not full authenticated HTTP
middleware/handler/HTML acceptance tests. Original logo/qualification tests mock
permission and scope decisions; original notification-group tests mock queries
and commit operations. They establish action dispatch, not complete independent
tenant-isolation evidence for those paths. Additional persisted-policy tests
address specific missed paths but do not erase these coverage limits.

### PR #360 review-response corrective pass

Two GitHub review findings on PR #360 (Codex automated review, commit
`86fc9a299246ef33a7dba1f546bb6f87e928f3a6`) were inspected against the actual
review comments/diff and corrected:

1. **P1 — hiring-plan export bypass via `section=full`.** Confirmed valid.
   `main._authorize_report_export` compared `normalized_section` against the
   literal string `"hiring"` only, while both professional-report builders
   include the hiring-plan sheet/section whenever `section == "full"` as
   well. A caller retaining `reports.export` / `dashboard.export_reports`
   but denied `hiring_plan.export` could bypass the dedicated gate simply by
   requesting `section=full` instead of `section=hiring`, obtaining the same
   protected hiring data. Fixed by checking membership in a single shared
   constant, `REPORT_EXPORT_SECTIONS_WITH_HIRING_DATA = {"full", "hiring"}`,
   used by the gate and documented as required to stay aligned with the
   builders' own per-section branches. `summary` and `subjects`/`teachers`
   sections (which do not include hiring data) remain unaffected by a
   missing `hiring_plan.export` grant. Regression coverage strengthened in
   `tests/test_permission_closure_22_keys.py::test_report_export_route_hiring_section_requires_hiring_plan_export`
   to assert denial for `hiring` and `full`, continued access for `summary`/
   `subjects`/`teachers`, and full ON→OFF→ON round-trip for both `hiring`
   and `full`.
2. **P2 — `.kms-impact.yml` KIA summary factually inconsistent with the
   branch's database changes.** Confirmed valid. The commit `86fc9a2` KIA
   summary stated "No new permission keys, migrations, or schema changes"
   and dropped `database_schema`/`migrations` from `affected_areas`, even
   though the same `fix/permission-consistency-closure` branch (commit
   `28f98f2`) still carries the non-destructive migration
   `20260915_001_role_permission_logical_key_uniqueness` (two partial-unique
   indexes on `role_permissions`) that is part of this PR's full diff against
   `origin/dev`. The 22-key closure commit itself added no new migration, but
   the KIA declaration governs the PR's cumulative branch knowledge impact,
   not only the most recent commit in isolation. `.kms-impact.yml` was
   rewritten to describe the full three-commit-plus-corrective-pass scope,
   restore `database_schema`/`migrations` to `affected_areas`, and list every
   authoritative KMS Markdown file that differs from `origin/dev`
   (`docs/CHANGE_HISTORY.md`, `docs/PROJECT_STATE.md`,
   `docs/TIS_MASTER_CONTEXT.md`,
   `docs/engineering/DATABASE_ARCHITECTURE_OVERVIEW.md`,
   `docs/engineering/PERMISSION_CLOSURE_REVIEW.md`,
   `docs/engineering/README.md`), matching the range GitHub CI validates for
   this PR (`origin/dev` → the branch's final head commit).

A third item raised in the delegated task description — SchoolGroup
edit/delete/action authorization consistency — was investigated but could
not be substantiated as an actual PR #360 review finding: the PR's full diff
against `origin/dev` (`git diff --stat origin/dev...HEAD`) touches no
SchoolGroup route/model/template file, and neither of the two real review
comments on PR #360 (fetched via the GitHub REST API) reference SchoolGroup
mutation authorization. No SchoolGroup-related code was changed in this
corrective pass; this discrepancy between the delegated task summary and the
actual GitHub review content is recorded here rather than acted on
speculatively.

## Migration and operational safety

The new RolePermission migration is last in the registered ledger sequence,
uses the same connection for transactional PostgreSQL catalog inspection and
DDL, and installs separate global-NULL and tenant-NOT-NULL partial unique
indexes. Distinct tenants can share role/key names. Duplicate preflight raises
before modifying the role-policy table or installing indexes; the runner may
create its empty ledger table first. No rows are deleted or rewritten.

Independent disposable PostgreSQL 16.15 validation covers global and tenant
duplicate rejection with rows retained/no marker, index installation,
idempotency, and rejection of later duplicate writes. SQLite metadata/migration
tests provide additional evidence. Index creation takes ordinary PostgreSQL
locks; plan production maintenance/capacity before running it. There is no
automatic down migration: rollback of an application release need not remove
these compatible constraints, and dropping them requires explicit operational
review. Production duplicates require approved cleanup, not automatic deletion.

Legacy `Limited Access` rows are not canonical managed-role policy; invalid and
platform-only tenant grants are constrained by the resolver. Existing deployed
user-override foundation DDL has no foreign-key clauses whereas the fresh ORM
model references User and SchoolGroup. This pre-existing schema drift means
orphan prevention cannot be assumed on migration-created databases; application
writes validate ownership, but approved inspection/remediation is still needed.
No real database rows were altered by review.

Removing the user-attached cache fixes a proven stale-instance risk. It does
not independently prove the historical production HTTP failure's cause or
cross-request ORM instance reuse. Platform-only user-override keys were already
rejected before the reviewed commit; the new check adds effective-role
assignability validation rather than originating the platform-only prohibition.

## Test database safety

`database.py` defaults the global engine to tracked `tis.db`.
`main._ensure_system_notifications_table_columns` normalizes rows using that
global engine even when a handler receives a different fixture session. Private
test sessions alone therefore do not protect the tracked database. Set an
isolated `DATABASE_URL` before importing application modules or replace the
global engine/normalizer. This identifies a responsible mutation path, not the
historical command that caused an existing local database modification.

## Knowledge Impact Assessment

Knowledge impact is yes: corrective security/capability behavior and honest
verification status. Master Context, Database Architecture, Change History,
Project State, this engineering review/index, and the cumulative impact
declaration record it; canonical tooling regenerates the
PDF/manifest. No new precedence architecture or permission keys are introduced,
so ADR 0040 remains accepted unchanged. No milestone or Talent capability is
changed; AI Project Context and deeper module history are not duplicated.
Deployment classification is Web Service and the original role-policy schema
migration, not Timetable Workflow. Review classification grants no deployment
authority.
