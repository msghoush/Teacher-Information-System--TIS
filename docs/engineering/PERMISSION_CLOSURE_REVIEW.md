---
title: Independent Permission Closure Review
documentation_version: 1.0
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
registered capabilities protect their associated workflows. In particular,
classification/enforcement needs an Owner decision for unconsumed keys:

- `dashboard.view_branch_summary`, `dashboard.view_reports`, `dashboard.export_reports`;
- `hiring_plan.export`, `reports.view`, `planning.import`, `planning.export`;
- `teachers.import`, `teachers.export`, `subjects.manage_colors`;
- `observations.manage_templates`, `observations.sign_evaluator`,
  `observations.submit`, `observations.view_reports`;
- `configuration.manage_global_defaults`, `configuration.view_audit_log`;
- `system_owner.create_subscription_school`, `system_owner.export_cross_school_data`,
  `system_owner.manage_developer_accounts`, `system_owner.manage_subscriptions`,
  `system_owner.run_startup_repairs`, `system_owner.view_cross_school_audit`.

These cannot silently be declared dormant merely because broader guards exist.
Owner-only commercial identity authority is a distinct governed boundary and is
not automatically removed by an operational role-policy Deny.

Ten-family ON/OFF/ON tests use persisted policies and fresh SQLAlchemy sessions,
real route guards, and navigation builders. They are not full authenticated HTTP
middleware/handler/HTML acceptance tests. Original logo/qualification tests mock
permission and scope decisions; original notification-group tests mock queries
and commit operations. They establish action dispatch, not complete independent
tenant-isolation evidence for those paths. Additional persisted-policy tests
address specific missed paths but do not erase these coverage limits.

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
