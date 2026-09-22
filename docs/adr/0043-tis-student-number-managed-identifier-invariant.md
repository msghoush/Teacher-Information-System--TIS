---
title: TIS Student Number Global Managed-Identifier Invariant (Schema Foundation)
documentation_version: 1.0
last_updated: 2026-09-22
status: Accepted
---

# ADR 0043: TIS Student Number Global Managed-Identifier Invariant (Schema Foundation)

## Context

`Student.id` (see "Student & Academic Placement Foundation",
`docs/AI_PROJECT_CONTEXT.md`) is the internal relational identity for a
Student and is SchoolGroup-owned. It is not, and this ADR does not make it,
a customer-facing managed identifier. The existing
`StudentExternalIdentifier` model (`student_external_identifiers` table,
migration `20260904_001_student_academic_placement_foundation`) already
supports arbitrary `namespace`/`value` cross-system identifiers with
tenant-scoped uniqueness (`school_group_id`, `namespace`, `value`) and an
active/inactive lifecycle. No prior ADR or KMS document records an
authoritative, globally unique, cross-SchoolGroup managed Student
identifier namespace; this ADR is that record for the Students + Talent &
Potential milestone plan's TIS Student ID foundation.

## Decision

### Namespace and canonical format

The managed namespace is exactly `tis_student_number`, stored as a normal
`StudentExternalIdentifier` row (namespace = `tis_student_number`). The
canonical stored format is exactly `STD` followed by exactly 10 digits (for
example `STD1234567891`, `STD0012345678`). This ADR does not authorize a
database-level format constraint in this milestone; format validation is
deferred to the future Student ID create/edit service/API, which is
explicitly not implemented as part of this schema-only foundation.

### Global uniqueness invariant (the exception to tenant-scoped uniqueness)

Every other `StudentExternalIdentifier` namespace keeps its existing
tenant-scoped-only uniqueness (`uq_student_external_identifiers_scope_namespace_value`)
unchanged. `tis_student_number` is the one namespace with an additional,
stricter invariant:

- The canonical `value` must be unique across **every** TIS organization
  (SchoolGroup), not merely within one - enforced by a partial unique index
  on `value` filtered to `namespace = 'tis_student_number'`, covering both
  `active` and `inactive` rows.
- A retired/inactive `tis_student_number` value is permanently reserved and
  can never be reissued to a different Student, in a different SchoolGroup,
  or reactivated for reuse as a distinct identity. This is a direct
  consequence of the same index also covering inactive rows.
- At most one `active` `tis_student_number` row may exist per Student at a
  time - enforced by a second partial unique index on `student_id` filtered
  to `namespace = 'tis_student_number' AND status = 'active'`. Because
  `Student.id` is a single globally unique primary key (not itself
  SchoolGroup-scoped), this index correctly enforces the invariant
  organization-wide without needing `school_group_id` in its key.
- `Student.id` remains the internal relational identity and primary/foreign
  key surface; this ADR adds no new Student identity table and no new
  column on `students`. An existing legacy Student may have zero
  `tis_student_number` rows - this is valid and is never backfilled with a
  fabricated value.

### Governance boundary and milestone scope

This ADR authorizes exactly the database-level integrity foundation above:
two partial unique indexes on the existing `student_external_identifiers`
table, with no new column, no new table, and no rewrite of any existing
row. It does not authorize or claim: a Student ID create/edit API contract,
Student ID UI, duplicate-value user-facing messaging, canonical-format
database enforcement, or automatic backfill/generation of `tis_student_number`
values for existing Students. Those remain separately governed, later
implementation work.

## Status

ACCEPTED as of 2026-09-22. Implementation status (schema/migration only, as
of this ADR) is tracked in `docs/PROJECT_STATE.md`; this ADR is the
governance/authorization record, not a completion record for any API,
service, or frontend surface.
