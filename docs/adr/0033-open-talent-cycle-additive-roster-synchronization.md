---
title: "ADR 0033: Additive Roster Synchronization While A Talent Cycle Is Open"
status: superseded
date: 2026-09-11
superseded_by: ADR 0035
decision_owners:
  - Product Owner
  - Engineering Owner
---

# Context

The approved M4 contract freezes the complete eligible Student population when
an Assessment Cycle opens. Open and Closed population membership is immutable;
post-Open mutation and late-entry exceptions are explicitly out of scope.

The Owner now requires a Student placed after opening into a Program-eligible
Academic Year, Branch, Grade, and Section to become assessable immediately while
that Cycle remains Open. The existing frozen-member model must remain the source
of assessment eligibility and historical context.

# Decision

Permit an organization-governed, additive-only roster synchronization for an
Open Cycle. Synchronization:

1. lock the Open Cycle and use an explicit synchronization timestamp;
2. derive eligibility through canonical effective-dated Academic Placement for
   the Cycle's exact School Group, Academic Year, and enabled Program grades;
3. insert only missing `(cycle_id, student_id)` population members, preserving
   each added member's exact Placement, Branch, Grade, Section, PlanningSection,
   and synchronization-effective timestamp;
4. update population count and fingerprint under the same transaction and
   expected-revision protection;
5. append an operational audit containing the timestamp and added member IDs;
6. never remove or rewrite a population member, assessment, result, Review
   Candidate, Official Identification, or historical snapshot; and
7. reject synchronization unless the Cycle is Open. Closed Cycles remain final.

The operation would reuse `talent_assessment_cycles.govern`, organization/global
scope, existing Branch-filtered population reads, and the existing population
member foreign keys. Assessment creation would continue to require a persisted
population member; it would not query live Placement directly.

# Resolved Conditions

- Synchronization runs automatically, in the same transaction, after an
  authorized user confirms and saves a qualifying Student Placement.
- Opening an existing Open assessment invokes the same organization-governed,
  expected-revision operation before reading its members. This additively
  reconciles Students who were already eligible before ADR 0033 was deployed.
- Students who later become ineligible remain members; removal is prohibited.
- Each affected Cycle is locked, revisioned, re-counted, re-fingerprinted, and
  audited before the placement transaction commits. A concurrent Close wins or
  causes the synchronizer to skip the now-Closed Cycle.
- Analytics reads the current stored count/fingerprint for an Open Cycle. The
  fingerprint may legitimately change after an audited additive synchronization;
  Closed Cycle integrity remains final.

# Consequences

This changes the M4 population invariant for Open Cycles only. No schema
migration is required because the existing member row stores per-member
effective and frozen timestamps. Closed Cycle membership remains immutable.


# Superseded

Superseded on 2026-09-11 by ADR 0035. Additive roster synchronization may
remain as backward-compatible internal machinery, but it is no longer the
eligibility authority or a required user workflow for starting Talent Student
Assessments. Current effective Academic Placement is the assessment-start
eligibility authority.
