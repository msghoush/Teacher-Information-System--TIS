---
title: Controlled Existing Workspace Owner Alignment And Activation-Required Conversion
status: Accepted
date: 2026-08-06
---

# Context

M4A can prove the identity, relationships, branch dependencies, intended owner,
and commercial state of an existing internal sandbox, but it deliberately has
no write authority. TIS needs a controlled bridge that preserves the existing
tenant and its data, establishes a real verified customer owner, and removes
internal commercial authority without fabricating onboarding or billing state.

# Decision

TIS uses a durable conversion operation as both approval ledger and ownership
claim. The operation binds exact workspace identity, intended normalized email,
M4A evidence, canonical parameters, actors, idempotency, branch/dependency and
entitlement snapshots, setup fields, and lifecycle stage. Events are append-only
and redacted. A partial unique database index allows one active `tenant_owner`
link per SchoolGroup, after migration-time duplicate preflight.

Preparation never creates an account or password. The owner registers and
verifies through the existing SaaS authentication architecture, explicitly
claims the operation, and is aligned through shared operational-owner identity
rules. Cross-tenant, duplicate, inactive, unverified, and platform identities
fail closed. A different current owner requires Platform Owner transfer
approval. Only legal name, IANA timezone, and educational program are collected.

Final conversion is PostgreSQL-only. It locks the operation and SchoolGroup,
performs a fresh M4A audit, and compares stable canonical branch/dependency and
sandbox-entitlement evidence to the approved operation. The complete M4A hash
is required at preparation; owner alignment and setup are expected to change
the later full report, so final validation compares the stored invariant
subsets rather than incorrectly requiring the old full hash.

The transaction ends the active internal-sandbox entitlement, preserves its
history, and sets classification `customer` with lifecycle `provisioning`. It
creates no active entitlement, TenantProvisioningLink, PendingOrganization,
contract, subscription, demo request, or promo grant. M1 resolves this exact
source-free state as `activation_required`; Organization Account remains
available and operational access remains blocked.

# Consequences

- Every branch and operational record is preserved; branch archival or deletion
  is outside M4B.
- M3 promo activation can establish the first customer commercial source.
- Existing-workspace Paddle activation is deferred and is not presented as
  available, while the normal new-onboarding Paddle journey is unchanged.
- Dry-run is default. Write preparation and conversion require exact explicit
  confirmation phrases, Platform Owner actors, row locks, and idempotency.
- Parameter drift, audit drift, identity conflicts, setup gaps, new dependencies,
  or commercial evidence block conversion without partial state.
