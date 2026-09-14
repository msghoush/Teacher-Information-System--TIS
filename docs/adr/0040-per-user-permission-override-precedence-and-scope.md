---
title: Per-User Permission Override Precedence, Deny-over-Allow, and Platform-Actor Scope Resolution
documentation_version: 1.0
last_updated: 2026-09-14
status: accepted
module: architecture
---

# ADR 0040: Per-User Permission Override Precedence, Deny-over-Allow, and Platform-Actor Scope Resolution

## Context

The per-user permission override layer (`models.UserPermissionOverride`,
migration `20260913_001_user_permission_overrides`,
`user_permission_service.py`, the Edit User page panel in
`templates/edit_user.html`, and `POST /users/permissions/{user_pk}` in
`routers/users.py`) sits above the existing role-resolved permission set
(built-in role default -> global `RolePermission` override -> tenant
`RolePermission` override). It was implemented and wired across several
prior passes (see `docs/TIS_MASTER_CONTEXT.md`'s "Per-User Permission
Overrides" section and `docs/CHANGE_HISTORY.md`) but three governing
decisions had not yet been recorded in a dedicated ADR: the exact
precedence chain, the Deny-over-Allow rule, and how the route resolves an
override's `school_group_id` when the acting administrator is a
platform-level actor (owner/developer) with no tenant SchoolGroup of their
own. This ADR is that record; it does not change or reopen the already-
implemented resolver/model/UI, except for the platform-actor scope fix
described below.

## Decision

### 1. Precedence chain

Effective permission for a specific user is resolved in exactly this
order: built-in role default -> global (`school_group_id IS NULL`)
`RolePermission` override -> tenant-scoped `RolePermission` override ->
per-user `UserPermissionOverride` -> effective permission. Every consumer
of "the current user's effective permissions" must resolve through
`auth.get_allowed_permission_keys`, the sole integration point that folds
role resolution (`role_permission_service`) and user overrides
(`user_permission_service`) together. Role-only helpers named
`_get_allowed_permission_keys` (in `main.py`, `routers/users.py`,
`ui_shell.py`) compute only the abstract role-level set for reference
summaries and are never a substitute for a specific user's effective
permissions.

### 2. Deny-over-Allow (Allow-over-Deny is NOT approved)

A per-user override has exactly three states: Inherit (no row), Allow,
Deny. `user_permission_service.apply_overrides_to_keys` applies
Deny-over-Allow: a per-user Deny always removes a key from the
role-resolved set. A per-user Allow only has effect when the key is
already present in the role-resolved set -- it can never add a key the
role currently denies (whether denied by default, by a global override, or
by a tenant-scoped override). A stored Allow override on a role-denied key
is preserved (not silently deleted) so that re-granting the key at the role
level immediately reactivates it, but it is inert until then.

This is a deliberate, conservative default. No prior ADR or governance
record ever approved letting an explicit per-user Allow grant access the
resolved role currently denies -- there was no existing authorization to
implement Allow-over-Deny, and building it without one would have been an
unapproved privilege-escalation mechanism. Enabling true Allow-over-Deny
therefore remains an open product/security decision requiring explicit
Owner sign-off before implementation; it is intentionally out of scope
here and must not be implemented without a future decision superseding
this ADR.

### 3. Uniqueness rule: `user_id + permission_key`

`UserPermissionOverride` is unique on `(user_id, permission_key)`, not
`(school_group_id, user_id, permission_key)`. A TIS `User` row has exactly
one `school_group_id` column (no membership table), so SchoolGroup is not
an independent dimension of a per-user override's identity -- a user
cannot simultaneously hold two different override rows for the same
permission key under two different SchoolGroups, because a user belongs to
exactly one SchoolGroup at a time. `school_group_id` is still recorded on
every row and is still validated by `apply_user_override` (the row's
`school_group_id` must equal the target user's own current
`school_group_id`) purely for tenant-isolation enforcement and audit
context, not as part of the row's logical identity.

### 4. Platform-actor scope resolution (this pass's fix)

`POST /users/permissions/{user_pk}` must resolve the `school_group_id`
passed to `apply_user_override`. That value is never accepted from client
request input (query parameter, form field, header, or cookie) as an
authority boundary -- doing so would be a privilege-escalation vector,
since `apply_user_override` itself only uses this value to decide which
tenant's row is written.

Two acting-admin cases exist:

- **Ordinary tenant administrator.** `_get_user_school_group_id(db,
  current_user)` resolves the acting admin's own verified active
  SchoolGroup (their own `school_group_id`/branch-derived scope, or a
  session-verified `scope_school_group_id` established by
  `auth.get_current_user`'s existing branch-selector-cookie resolution
  against real, active `Branch` rows -- never raw, unverified client
  input). `_can_manage_target_user` already requires a non-platform
  actor's target to share this exact SchoolGroup, so this value always
  equals the target's own SchoolGroup for a legitimate same-tenant request.

- **Platform-level actor (owner/developer).** `auth.get_user_school_group_id`
  always returns `None` for a platform user by design (`is_platform_user`
  short-circuits it), regardless of any stale tenant fields on that
  platform user's own row and regardless of whatever branch/SchoolGroup
  their own session happens to have selected via the ordinary
  branch-selector cookie (`auth.get_current_user`'s `scope_school_group_id`
  resolution, which is a real mechanism but answers "what tenant is this
  platform actor currently viewing," not "what tenant does this specific
  target user belong to"). `_can_manage_target_user` /
  `can_manage_target_user_account` already grant a platform actor
  unconditional cross-tenant authority to manage any non-platform target
  user's account (this is the codebase's existing, pre-established
  "platform manages any tenant user" pathway -- no new permission key was
  introduced for it). Consistently with that existing authority and with
  `_build_user_permission_context`'s identical read-side resolution (which
  already computed `target_school_group_id =
  auth.get_user_school_group_id(db, user_row)` for rendering the panel),
  the write path now resolves `school_group_id` from the already
  server-loaded target user's own verified `school_group_id` whenever the
  acting admin `is_platform_user`, unconditionally -- not merely as a
  fallback when the platform actor's own scope happens to be empty. This
  was required because a platform actor's own selected branch/SchoolGroup
  scope can legitimately differ from an arbitrary target's SchoolGroup
  (the platform actor is authorized to manage users across every tenant,
  not only whichever one their session happens to currently be scoped to),
  and using the actor's own scope in that case previously produced a
  spurious `"target user is not in the active SchoolGroup"` rejection for
  an otherwise fully authorized cross-tenant write.

  No new permission key, client-supplied scope parameter, or "select an
  acting SchoolGroup" form control was added. The value used is always
  exactly the value `apply_user_override` would itself require to succeed
  (it independently re-validates `target_user.school_group_id ==
  school_group_id`), so this resolution cannot be used to write into any
  SchoolGroup other than the one the specific target user actually
  belongs to.

### Rejected alternative

Accepting an explicit client-supplied "acting SchoolGroup" selection for a
platform actor (mirroring how `POST /system-configuration/role-permissions`
lets an actor holding the separate, dedicated
`system_owner.manage_global_role_permissions` permission choose an
explicit target `school_group_id` for a *role-level* policy override) was
considered and rejected for this *user-level* route. Role-permission
overrides configure policy for an arbitrary SchoolGroup chosen by a
dedicated platform authority; per-user overrides always concern one
specific, already-identified target user who has exactly one
SchoolGroup, so deriving scope from that target directly is both simpler
and strictly safer than accepting any client-supplied scope value, and
requires no new dedicated permission.

## Consequences

- `routers/users.py`'s `update_user_permissions` no longer hard-errors for
  a platform-level actor with no tenant SchoolGroup context, and no longer
  spuriously rejects a platform actor's legitimate cross-tenant write when
  their own session scope differs from the target's SchoolGroup.
- No new permission key, schema, or migration was introduced.
- Regression coverage: `tests/test_user_permission_override_routes.py`
  (`test_platform_actor_with_no_own_tenant_scopes_override_to_target_school_group`,
  `test_platform_actor_override_scope_tracks_each_targets_own_school_group_not_a_shared_value`,
  `test_platform_actor_cannot_use_service_layer_to_write_into_a_mismatched_school_group`)
  and a template-render integration test
  (`tests/test_edit_user_template_render.py`) proving the Edit User page
  panel renders all three Inherit/Allow/Deny controls, both the
  inherited-grant and Deny-override reason text, and the exact inert
  markup for platform-only/non-assignable keys.
- Allow-over-Deny remains explicitly unimplemented pending a future,
  separately governed Owner decision.
