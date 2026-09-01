---
title: Advanced Timetable Release 1 Reconciliation And Solver Adapter
date: 2026-09-01
module: workforce-planning
knowledge_impact: yes
---

# Advanced Timetable Release 1 Reconciliation And Solver Adapter

Milestone 0 reconciled the governed timetable design with the implemented
versioned scheduling pipeline. The existing SchoolGroup/Branch/Academic Year
scope, Planning demand authority, immutable snapshots and fingerprints,
version-relative placements, revision-guarded mutation/publication, exclusive
generation runs, CP-SAT execution, independent validation, permissions, and
Render Workflow boundary remain the implementation foundation.

The first additive Release 1 slice introduced `timetable_solver.py`. The Workflow
worker now calls a solver-neutral contract for solving and bounded infeasibility
diagnosis. `CpSatTimetableSolver` delegates to the existing OR-Tools model without
changing the problem or result contracts. No alternate solver, scoring authority,
schema, API, UI state, migration, or service was introduced.

Repository evidence confirms that Planning's explicit-first
`PlanningSubjectDemand` projection already supplies timetable demand; a separate
academic-demand authority must not be added. It also confirms that locks remain
placement metadata, while teacher Unavailable and Schedule-within behavior belongs
to normalized teacher rules. General Room/Classroom/Campus authority and generic
availability remain absent and require separate approval before implementation.
