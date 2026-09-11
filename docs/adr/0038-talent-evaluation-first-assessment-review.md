---
title: Talent Evaluation-First Assessment and Review Workspace
documentation_version: 1.0
last_updated: 2026-09-11
status: accepted
module: architecture
---

# ADR 0038: Talent Evaluation-First Assessment and Review Workspace

## Context

The previous Student Assessments surface rendered one card per Program Cycle,
which could show repeated labels such as `Term 1`, `Term 2`, `Term 1`.
This obscured the fact that one Evaluation Period may contain several Talent
Programs.

Talent Review also used persisted Review Candidate rows as its primary Student
list. A completed Student Assessment without a qualifying/materialized Review
Candidate therefore disappeared from the Review workspace even though it
contained valid assessment evidence and an Overall Program Result.

The Product Owner requires:

- Program setup to expose eligible Grades and configured user-defined Evaluation
  Periods for the selected Academic Year;
- Student Assessments to organize work as Evaluation Period -> Program -> Student;
- every currently eligible Student to be visible for the selected Program and
  Evaluation;
- every current completed Assessment to be available in Talent Review;
- Review Candidate and Official Identification to remain separate statuses.

## Decision

### Program configuration

The existing Annual Evaluation Plan / Planned Evaluation Period architecture
remains the canonical scheduling authority.

Program setup surfaces that configuration alongside eligible Grades. TIS does
not create a duplicate scheduling table or hard-code Term names.

Users may configure labels such as:

- Term 1;
- Term 3;
- Final;
- Baseline;
- Audition;
- or other organization-defined Evaluation labels.

### Evaluation Period grouping correction

The operational Student Assessment hierarchy is **Evaluation Period -> unique Programs -> Students**. The display grouping key is the user-facing Evaluation label plus its configured sequence for the Academic Year, not a physical Cycle id or a Program-specific Planned Period id. Therefore the same label/sequence (for example `Term 1`) across Mental Math and Qaida Nourania renders as one `Term 1` section containing each Program once.

Multiple physical Cycles for the same Program/Period must never duplicate that Program card. Evaluation Plans are also a display source: a configured Program/Period remains visible before its first internal Cycle has been materialized; opening it directs the user through the existing Evaluation Plan/start-assessment workflow. Cycle remains internal provenance/execution context, not a second user-facing Program occurrence.

## Student Assessment information architecture

The primary Student Assessment chooser is:

**Evaluation Period -> Programs -> Students**.

Cycles linked to Planned Evaluation Periods use the Period label and sequence as
the user-facing grouping/order authority. Legacy unlinked Cycles fall back to
their existing title/order behavior.

A repeated Evaluation label is shown once, with participating Programs nested
inside it.

### Eligible Student completeness

For a selected Program/Evaluation, the operational list is driven by the
existing live Academic Placement eligibility rule from ADR 0035, constrained by:

- SchoolGroup tenant;
- Academic Year;
- Program eligible Grades;
- authorized Branch/scope.

Each eligible Student is shown with an operational state such as:

- Not started;
- In progress;
- Completed;
- Re-evaluation required.

Historical/superseded Assessment attempts remain preserved as backend evidence but are not rendered as a separate Assessment Records/History table in the normal Student Assessment workspace. The current eligible Student row and its current status/action are the sole operational surface.

### Re-evaluation

ADR 0036 remains authoritative.

A materially changed newer Grade-applicable rubric causes a current completed
Assessment to surface **Re-evaluation required**. The prior completed attempt
remains immutable historical evidence; reassessment creates a new current
attempt tied to the original visible Evaluation context.

### Talent Review

Talent Review is an educator review workspace over **all current completed
Student Assessments** in the selected authorized context.

A completed Assessment is not hidden merely because no Review Candidate row
exists.

Talent Review displays, as separate facts:

- Overall Program Result;
- Review Candidate state, when a deterministic Candidate exists;
- review status;
- Official Identification state.

Completing an Assessment may deterministically evaluate the existing Framework
Review Candidate policy. A no-policy or non-qualifying outcome does not remove
the completed Assessment from Talent Review.

### Official Identification

Official Identification remains a separately permissioned, permanent human
decision. The presence of a completed Assessment or a high Overall Program
Result does not itself identify a Student.

### Analytics relationship

Results & Analytics may summarize completed/current assessment evidence using
the existing governed analytics and privacy architecture.

Different Program results remain separate. Organization/Branch/Grade analytics
must not manufacture one cross-Program Student Talent score.

## Consequences

- Repeated Term cards are replaced by an Evaluation-first operational hierarchy.
- Program settings make Evaluation Period configuration discoverable without
  duplicating its persistence model.
- Missing eligible Students are treated as a roster/eligibility defect rather
  than an expected consequence of frozen historical membership.
- Talent Review becomes complete for current completed assessments.
- Review Candidate and Official Identification remain distinct governed states.
- Historical evidence and tenant/Branch authorization boundaries are preserved.
