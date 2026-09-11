---
title: "ADR 0035: Talent Assessment Eligibility Uses Live Academic Placement"
status: accepted
date: 2026-09-11
decision_owners:
  - Product Owner
  - Engineering Owner
supersedes:
  - ADR 0033
  - M4 frozen-population eligibility gating
---

# Context

The Talent & Potential implementation introduced an operational sequence in
which an Evaluation had to move through Draft/Open lifecycle states, freeze a
population at a configured timestamp, synchronize/reconcile that population,
and require a persisted population member before a teacher could start an
Assessment.

The Product Owner has explicitly rejected that workflow complexity. It was not
an Owner requirement. The intended product is simpler: Students are enrolled
through canonical Academic Placement; Programs define eligible Grades and an
assessment tool/framework; Evaluation Periods provide assessment context; and
teachers assess the Students who are currently enrolled and eligible.

Historical integrity is still required, but it must be captured when an
Assessment is created rather than used as a pre-assessment operational gate.

# Decision

Talent Student Assessment eligibility is determined from canonical current
Academic Placement at the time the assessment is started.

A Student is assessable when:

1. the Student belongs to the same School Group;
2. the Student has an effective Academic Placement in the selected Academic
   Year at the assessment-start time;
3. the Placement Grade is included in the Program's enabled Academic Year
   configuration;
4. the Program has a usable active assessment framework/tool; and
5. the actor holds the existing assessment permission and authorized Branch
   scope.

No additional Draft/Open/frozen-roster/synchronization/reconciliation state is
a user-facing prerequisite to start an Assessment.

Evaluation Periods such as Term 1, Term 2, or Final are assessment context. They
do not require a separate "Open Evaluation" action before eligible Students can
be assessed.

For schema compatibility, the existing Talent Assessment Cycle and Cycle
Population Member records may remain as internal persistence/provenance
structures. When an Assessment is started, the implementation may create or
reuse the internal Cycle context and persist a Population Member snapshot of
the Student's current Placement. That snapshot preserves the exact Branch,
Grade, Section, PlanningSection, Program, Academic Year, framework version, and
effective timestamp used for the Assessment. It is historical provenance, not
an eligibility gate.

Existing completed Assessment evidence remains immutable history.

# Supersession

ADR 0033 is superseded as an operational eligibility model. Its additive-roster
synchronization machinery may remain temporarily for backward compatibility,
but it is no longer required for Student Assessment eligibility and must not be
presented as a normal user workflow.

The earlier M4 frozen-population requirement is likewise superseded only where
it acted as a prerequisite for starting or editing Talent Student Assessments.
Historical snapshots and existing persisted records remain valid.

# Consequences

- Student Assessments lists current eligible enrolled Students directly from
  Academic Placement.
- A newly enrolled eligible Student appears automatically without roster
  reconciliation.
- "Open Evaluation" is removed as a prerequisite for assessment.
- Starting an Assessment captures historical placement/framework context at
  that moment.
- No schema migration is required for this correction.
- Tenant isolation, Branch authorization, assessment permissions, framework
  validity, evidence immutability, and auditability remain enforced.
- No new workflow or lifecycle gate may be added to this module without an
  explicit Owner requirement or an unavoidable security/data-integrity need.
