---
title: Existing Workspace Conversion Read-Only Audit
documentation_version: 3.1
last_updated: 2026-08-05
status: Accepted
---

# ADR 0021: Existing Workspace Conversion Read-Only Audit

## Context

An operational internal sandbox can contain years of tenant data and partial
identity or commercial relationships. A future conversion to a real customer
must preserve that workspace and cannot rely on a hardcoded tenant script,
model-only assumptions, or a partial branch count. Conversion design therefore
needs reproducible production evidence before any mutation is authorized.

## Decision

M4A introduces a generic query-only service keyed by an explicit SchoolGroup
ID, workspace UUID, exact name, and normalized owner email. It reflects the
connected database schema, inventories ownership, provisioning, entitlement,
paid/demo/promo evidence, traverses branch foreign-key descendants, and reports
unconstrained branch-like references. Output is allowlisted and provider
references are represented only by presence flags.

The standalone CLI is the only production entry point. It requires PostgreSQL,
starts `REPEATABLE READ READ ONLY`, emits deterministic sanitized JSON or text,
and always rolls back and closes. Canonical evidence receives a stable SHA-256
snapshot hash. Exit codes are `0` coherent, `1` execution/configuration failure,
`2` manual review, and `3` workspace identity mismatch. Soft-deleted rows remain
dependencies; an unmodeled branch foreign key suppresses all archival
recommendations. Missing, conflicting, or uncertain evidence fails closed for
manual review. The audit never constitutes approval for hard deletion or
conversion.

## Consequences

- Tenant-specific identifiers remain command inputs and are absent from the
  reusable service and CLI.
- Schema drift and unknown relationships become visible blockers rather than
  silent omissions.
- Archival candidate IDs are advisory only and include active branches proven
  free of direct, transitive, logical, and soft-deleted dependencies.
- The active internal-sandbox entitlement may be reported as expected evidence;
  paid, demo, promo, ambiguous, or duplicate authority blocks conversion design.
- Branch archival, owner alignment, classification changes, approval tokens,
  write-mode conversion, Paddle, email, and all data mutation remain outside
  M4A.
