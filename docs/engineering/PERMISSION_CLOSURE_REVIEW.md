---
title: Independent Permission Closure Review
documentation_version: 1.4
last_updated: 2026-09-19
module: architecture
---

# Independent Permission Closure Review

## Phase 3 — Whole-Application Permission Qualification

Phase 3 audited the whole application against the objective that every surface
(sidebar, Dashboard cards/tabs, direct GET routes, POST mutations, bulk/export/API
paths, configuration controls and server-rendered action affordances) consumes ONE
canonical effective permission result (`auth.get_allowed_permission_keys`), with no
role-name shortcuts, tenant-scope drift, stale caches, or duplicated resolver logic.
ADR 0040 precedence is unchanged; there is no second resolver, no schema change, no
migration, and no new permission key.

### Final registry classification (175 keys, 26 groups)

Machine-checked by `tests/test_permission_registry_matrix.py`. Consumers are
discovered by AST and template scan of non-test source and compared with a reviewed
table. The test fails on an unclassified new key, an active key with no consumer, a
dormant key that gains a guard consumer, a lost consumer, or any unresolved key.

| Status | Count | Meaning |
| --- | --- | --- |
| A active-enforced | 143 | Tenant-assignable key with a discovered route, handler, middleware, service or template consumer |
| B platform-only, enforced | 14 | Platform-only key with a real guard consumer |
| C alias/composite | 5 | Governed by another guard or by identity |
| D dormant/reserved | 13 | No enforcement anywhere |
| E unresolved | 0 | none |

Platform-only keys (24 = 22 developer-only + 4 owner-only, with 2 in both): 14 are B,
5 are C and 5 are D (`dashboard.view_all_schools`,
`configuration.manage_global_defaults`, `system_owner.manage_subscriptions`,
`system_owner.create_subscription_school`, `system_owner.run_startup_repairs`).

Aliases/composites (C): `system_owner.manage_developer_accounts`,
`system_owner.manage_ownership`, `system_owner.transfer_ownership` (owner-identity
gates; the key is only cited in the denial), `system_owner.view_cross_school_audit`
and `system_owner.export_cross_school_data` (`match="any"` aliases of
`configuration.view_audit_log` / `configuration.export_audit_log`).

Dormant/reserved (D, 13): `reports.view`, `teachers.import`, `teachers.export`,
`subjects.manage_colors`, `planning.import`, `planning.export`,
`observations.submit`, `observations.manage_templates`, `dashboard.view_all_schools`,
`configuration.manage_global_defaults`, `system_owner.manage_subscriptions`,
`system_owner.create_subscription_school`, `system_owner.run_startup_repairs`.

Differences from the prior disposition (re-verified rather than trusted):
`planning.import` and `planning.export` were recorded as resolved with real
consumers in `routers/planning.py`; that was stale (no planning import or export
route or literal exists) and both are dormant. `observations.submit` was recorded as
an alias of `observations.sign_evaluator`, but no code evaluates it, so it is dormant
(enforcement is `observations.sign_evaluator` only). `dashboard.view_all_schools` is
only cited in a denial-message label (the all-school scope gate is the access-scope
identity) and is dormant. `dashboard.view_branch_summary` and
`dashboard.view_reports` remain template (presentation) gates on the already
route-guarded `/dashboard` page. `ai.use` is an active service-layer consumer:
`saas/ai_entitlement_service.evaluate_ai_availability` passes the feature definition's
`permission_key` (`ai.use`) to `entitlement_service.evaluate_feature_access`, which
calls `auth.has_permission` with that key. The matrix does not credit the bare constant
in `saas/ai_feature_registry.py`; it credits `saas/ai_entitlement_service.py` only when
an AST check confirms all three links (the `AI_PERMISSION_KEY` constant holds `ai.use`,
the feature definitions pass it as `permission_key=`, and `evaluate_ai_availability`
passes `<feature>.permission_key` to `evaluate_feature_access`); removing any link
fails `tests/test_permission_registry_matrix.py`. Runtime behaviour is proven by
`tests/test_ai_entitlement_service.py::test_ai_use_permission_key_is_the_runtime_gate_for_every_ai_feature`
(every AI feature carries `ai.use`; the real service calls `auth.has_permission` with
`ai.use`; an Administrator is allowed, a school-level Deny of `ai.use` yields
`ai_permission_denied`, and removing the Deny restores access) plus the existing
role-Limited denial test. Not proven: every individual AI feature key end to end (the
runtime test exercises `ai.academic_assistant`; all features share the one
`permission_key` constant and evaluator path), and any HTTP route that fronts AI.

### Route authorization enumeration

`tests/test_permission_route_coverage.py` enumerates the real `main.app` route table:
468 routes (215 GET, 224 POST, 12 DELETE, 9 PATCH, 8 PUT; 253 non-GET). Evidence
classes: 136 middleware rule (`authorization.PROTECTED_ROUTE_RULES`), 182 in-handler
permission guard, 10 guard through a same-module helper, 34 platform-identity guard,
65 SaaS account-session guard, and 41 reviewed allowlist entries (public or
pre-authentication routes, provider webhook, scope selectors, and the Talent
organization-analytics routes guarded in the service layer). Zero are uncovered.
Every middleware rule is also proven at runtime to deny a user with an empty
effective permission set. Static guard reachability is necessary but not sufficient
evidence; representative handler-level denials are exercised in
`tests/test_permission_surface_consistency.py`. A full authenticated HTTP sweep of
every handler was not performed.

### Defects found and fixed

1. `POST /scope/organization` selected an organization context for any platform user
   by identity alone, while its denial cited `system_owner.switch_all_schools`. A
   Platform Developer whose switch/manage-all-schools capability had been withheld
   could still switch organization. Proven by a failing test first; fixed by
   requiring platform identity AND the existing canonical helper
   `_can_manage_all_school_scopes` (`schools.manage_all_schools` or
   `system_owner.switch_all_schools`). The Owner (all keys) is unaffected.
2. Four unused duplicate raw `RolePermission` readers named
   `_get_role_permission_rows` (`auth.py`, `main.py`, `routers/users.py`,
   `ui_shell.py`) and three unused `_get_allowed_permission_keys` wrappers were deleted.
   At the base commit each was only defined and never called (the `ui_shell.py` wrapper
   caught any exception and returned role defaults, which would have failed open had it
   ever been reachable, but it was dead code). Removing them eliminates duplicated
   resolver-adjacent code that could be revived as a second resolver. No behaviour
   change.

### Dangerous-pattern scan

`tests/test_permission_dangerous_patterns.py` scans non-test source for role
constants and literals used as authority, admin-style flags, platform identity checks,
raw `RolePermission` / `UserPermissionOverride` access, form-supplied SchoolGroup ids,
per-request permission snapshots stashed on ORM instances, `lru_cache`, module-level
permission caches, and template role gates. Every hit is classified (20 approved
helper, 15 valid identity boundary, 5 legacy safe, 0 escalations, 0 bypass defects) with
exact per-file counts, so a new hit fails the test. Raw policy queries exist only in
the two services (plus tenant purge and count code in `saas/workspace_*`).
`user.permission_keys` snapshots are per-request and have no reader. No
request-independent permission cache exists.

### Freshness, role change, tenant and platform-only results

Allow to Deny to Allow for Role Package, School Override and User Exception is proven
on fresh sessions across resolver, sidebar, Dashboard, route and POST action.
Administrator to Editor to Administrator (and Editor to User) with a user exception
and a tenant School Override present recomputes on the next request and retains the
exception row. School Overrides and user exceptions never cross tenants, a tenant
actor cannot write another tenant's overrides or global Role Packages, user
exception scope uses the target user's school, a Platform Owner management target
never gains tenant membership, platform-only keys cannot be granted through Role
Packages, School Overrides, User Exceptions or crafted role-permission POSTs, and
platform routes stay identity-guarded.

### Verification scope and limits

The route coverage test is structural: it matches guard-named calls in each handler's
same-module call closure against the real route table, so a new mutating route with no
guard-named call fails, but a guard that is called and ignored would still pass. The
middleware runtime denial test stubs the resolver to an empty set and proves each
`PROTECTED_ROUTE_RULES` rule fires. Accessibility of the permission-management
templates is verified by template-source assertions plus a rendered-page test in
`tests/test_permission_surfaces_accessibility.py` (the real User Exceptions panel and
School Overrides page are rendered; every colour-classed Allow/Deny element must carry
the same word as visible text, and "Effective", "School Override" and "Using Standard
Role Package" states are asserted as text); no browser rendering was run. The
existing Role Packages / School Overrides split, User Exceptions, permission
management/qualification, tenant-isolation, platform-access and override route/service
suites are the regression evidence for Phase 1 and Phase 2 behaviour. The read-only
diagnostic CLI (`scripts/diagnose_user_permissions.py`) was re-qualified in the final
hardening pass: `tests/test_diagnose_user_permissions.py` passed 6 of 6 (not-found is
safe and minimal, unknown permission key gives no trace, user-override trace, no
password hash or database URL in output, login-equivalent case-insensitive email
resolution, direct invocation without `PYTHONPATH`); a manual direct run reported an
unknown user as `not_found` (exit 1) and an unreachable database as the generic
`database_unavailable` message (exit 2) with no URL, credential or host detail. The
script resolves identity through `auth.resolve_login_user` and contains no commit,
INSERT, UPDATE or DELETE. Read-only behaviour and the database-unavailable path were
confirmed by source inspection and the manual run, not by a dedicated automated test.

### ADR 0040 historical references

ADR 0040 remains authoritative for precedence semantics (built-in role package ->
global `RolePermission` -> SchoolGroup `RolePermission` -> per-user override; user
Deny wins; a user Allow cannot resurrect a role-level Deny). Helper names the ADR
mentions describe the implementation at decision time. Current runtime authority is the
canonical resolver and service path: `auth.get_allowed_permission_keys`,
`role_permission_service` and `user_permission_service`, as documented in current KMS.
The unused duplicate wrappers deleted in Phase 3 do not change the ADR's semantics; the
ADR itself is intentionally left unedited.

### Open Owner/product decisions (unresolved; not invented here)

Exactly four decisions remain open and require an Owner/product decision. None is
resolved by Phase 3.

1. Teacher-create field-level enforcement: `create_teacher` persists subject
   assignments, qualifications and capacity from the create form for any holder of
   `teachers.create`, although the edit route enforces `teachers.assign_subjects`,
   `teachers.manage_qualifications` and `teachers.manage_capacity` field-level.
2. Tenant-toggleable dormant keys: the tenant-assignable dormant keys
   (`reports.view`, `teachers.import`, `teachers.export`, `subjects.manage_colors`,
   `planning.import`, `planning.export`, `observations.submit`,
   `observations.manage_templates`) remain toggleable in the Role Package editor with
   no effect; whether to hide, lock or implement them is undecided.
3. Whether role `User` may ever author observations: `routers/observations._is_teacher_user`
   is a restrictive role-name compatibility rule (role `User` is the observed teacher
   and is denied observation create/edit/delete/evaluator-sign even when granted;
   reads are limited to the caller's own teacher record). It never authorises another
   user's data, so it is not a bypass and does not block this audit.
4. Orphan `UserPermissionOverride` rows on workspace deletion: workspace deletion in
   `saas` purges `RolePermission` rows but no `UserPermissionOverride` rows for the
   deleted tenant (orphan exceptions cannot grant access); whether and how to purge
   them is undecided.

Not a decision: `dashboard.view_branch_summary` and `dashboard.view_reports` gate
presentation only.

## Role Permissions UI — Role Packages / School Overrides Split (Phase 1)

The live Owner reproduction below (Dashboard Tab/Panel Permission-Gate
Closure) surfaced the underlying Role Permissions UI defect this Phase 1
pass corrects: the combined editor's single "Permission Scope: Global
defaults / Selected school" dropdown made a real tenant Deny override
(built-in Allow, global override none, tenant override Deny, effective Deny)
visually indistinguishable from the Global default Allow, and the Platform
Owner UI displayed the selected tenant's name even while "Global defaults"
was selected. `/system-configuration/role-permissions` now serves two
explicit modes (`mode=packages`, `mode=overrides`) reusing the unchanged
`role_permission_service.py` resolver; School Overrides always labels its
SchoolGroup selector as a management target, never as Platform Owner actor
context, and read-only viewing never creates a tenant `RolePermission` row.
An Owner-review pass over the running application (real browser rendering plus
a live save/reset round trip on a throwaway database, never `tis.db`) further
required: a Platform Owner must explicitly choose the School Overrides
management target (no school is pre-selected); groups holding a School
override open by default with an override count; and corrected accessibility
semantics (`aria-current` navigation, no static `aria-expanded`, the Reset
button kept out of the checkbox `<label>`, single-element banner text,
explicit focus outlines). The live round trip confirmed the incident's
resolution path: a tenant Administrator's fresh `GET /subjects` was denied
while the tenant Deny override existed, allowed after "Reset to standard" +
Save removed it, and denied again on re-deny, with no global row touched and a
tenant actor unable to save Role Packages or another school's override.
See `docs/PROJECT_STATE.md` for full detail and
`tests/test_role_permissions_ui_split.py` for the regression matrix,
including a constructed Al-Andalus-style fixture. This is a UI/route
structural correction only; ADR 0040's precedence chain is unchanged and no
permission data was read or mutated on any production row.

## Dashboard Tab/Panel Permission-Gate Closure (Live Owner Reproduction)

A live Owner UI reproduction (Role Permissions -> Administrator -> Global
defaults showing Subjects 8/8, then logging in as a real Al-Andalus tenant
Administrator) found Subjects correctly hidden from the sidebar and
correctly denied at the direct `/subjects` route, but still fully visible on
that same user's Dashboard (tab + Subjects Workspace panel). This was traced
end to end per the required chain: built-in Administrator default -> global
`RolePermission` -> Al-Andalus tenant `RolePermission` -> per-user
`UserPermissionOverride` -> `auth.get_allowed_permission_keys` -> shell/
sidebar context -> Dashboard context -> direct `/subjects` route
authorization. Every layer up to and including `main.dashboard`'s own
`build_shell_context()` call resolves and exposes the same canonical,
per-user effective permission set via the `can(...)` template helper; the
sidebar (`ui_shell._build_nav_items`) and the route guard
(`authorization.enforce_route_permission`) both already consume that same
canonical resolver correctly. The defect was that `templates/dashboard.html`
itself never called `can("subjects.view")` / `can("teachers.view")` /
`can("planning.view")` to gate its Subjects/Teachers/Planning tab buttons and
panels -- they rendered unconditionally regardless of the resolved effective
permission, while the pre-existing Reports tab already correctly called
`can("dashboard.view_reports")`. This is the same defect class as this
review's broader "current-user authorization (A) and UI capabilities (B) use
canonical resolution" principle: (A)/(B) were both actually available in this
template already, and simply were not invoked for these three tabs/panels.

Fix: wrap each of the three tab buttons and their matching panel `<div>`
blocks in the matching `can(...)` check, and replace the previously
hardcoded always-active Subjects tab/panel with a computed `dash_first_tab`
(first permission-visible tab among Subjects, Teachers, Planning, Reports),
so a user holding only `teachers.view` or `planning.view` still gets a valid
default-active panel rather than a blank workspace. No change to `auth.py`,
`authorization.py`, `role_permission_service.py`,
`user_permission_service.py`, `ui_shell.py`, ADR 0040's precedence chain, or
any permission key/schema/migration -- all were inspected and confirmed
already canonical.

Phase-1 read-only diagnosis of the tracked local `tis.db` (hash recorded
before and after; unchanged) found it predates this feature area: no
`user_permission_overrides` table exists, and its `schema_migrations` ledger
ends at `20260822_...`, before both `20260913_001_user_permission_overrides`
and `20260915_001_role_permission_logical_key_uniqueness`; it also contains
no tenant Administrator user matching the reproduced Al-Andalus scenario
(only one platform `developer` identity). Diagnosis and the new regression
suite (`tests/test_dashboard_sidebar_permission_consistency.py`) are
therefore code/template-level trace and fresh in-memory-database test
fixtures, not live-row inspection of that specific file; this limitation is
recorded rather than worked around or fabricated. The new suite proves six
cases (global Allow only; global Allow + tenant Deny; tenant Allow + per-user
Deny; role Deny then re-grant with per-user Inherit; role Deny then re-grant
with a persisted per-user Deny remaining in effect; and cross-tenant
isolation) against sidebar, Dashboard markup, and the direct route guard
together, parametrized over both `subjects.view` and a second, non-Subjects
sentinel (`teachers.view`) to prove the fix is generic.

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
`planning.export` were previously recorded here as resolved with real consumers;
the Phase 3 audit found that stale (no planning import or export route exists) and
classified both dormant. The other 22 keys close as follows.

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

- `observations.submit` — documented as an alias of `observations.sign_evaluator`
  (Phase 3 finds no code evaluates it, so it is now classified dormant). The
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

## User Exceptions UX (Phase 2)

The edit-user per-user panel is now "User Permission Exceptions": binary
Allow/Deny plus Reset to Role Settings (internal inherit == delete the
override row; "Inherit" is never shown). ADR 0040 precedence is unchanged.
`user_permission_service.build_user_permission_payload` projects Effective
(equal to `auth.get_allowed_permission_keys`), Source, exception, and an
`exception_inert` flag. A stored Allow under a role-level Deny is kept,
displayed as Effective Deny and "stored, currently ineffective", and
re-applies if the role re-grants. Tenant/platform scope resolution, the
platform-only and non-assignable rejections, and inactive-user fail-closed
behaviour are unchanged. Locked rows expose no Allow/Deny buttons; a stored
exception on a key that became non-assignable for the user's role (for example
after a role change) is kept, never silently deleted, and the locked row shows
only "Reset to Role Settings" so an operator can remove it (Reset deletes the
row and grants no authority; the service already accepted `inherit` for such
keys, and creating or changing an exception on a locked key is still refused).
The legacy paired-list / `inherit` route contract is unchanged and never shown
in the UI. Coverage: `tests/test_user_exceptions_ui.py`.

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
