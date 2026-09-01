---
title: Timetable Lesson Requirement Projection
date: 2026-09-01
module: workforce-planning
knowledge_impact: yes
---

# Timetable Lesson Requirement Projection

Advanced Timetable Release 1 now has one internal domain contract between
Planning demand and scheduling. `timetable_requirement_projection.py` resolves
the exact SchoolGroup/Branch/Academic Year, Planning section, subject, effective
weekly periods, existing teacher assignment or HRT fallback, and demand source.
It consumes `PlanningSubjectDemand` first and uses `Subject.weekly_hours` only
when no explicit row exists. Explicit zero and retired rows remain authoritative
and never reactivate fallback.

The internal requirement identity is deterministic over scope and governing
Planning source. A separate source fingerprint detects effective-period,
active-state, and teacher-authority changes without changing the logical identity
of an unchanged explicit source. These values are internal correlation and
freshness evidence, not customer-facing business identifiers.

Schema-v5 snapshots store the requirement identity, source fingerprint, demand
authority, and source ID. The existing problem builder remains compatible with
schema-v3/v4 snapshots, while schema-v5 fails closed if projection provenance is
missing. Readiness and snapshot creation now share the projection; feasibility and
generation consume it through immutable snapshots, and the independent validator
checks captured provenance without depending on CP-SAT.

Grouped Swimming remains its existing specialized equal-demand/common-teacher
synchronization path over projected requirements. This work does not introduce
general co-teaching, a Lesson Requirement table, a CRUD API, Room, generic
availability, or generic Resource authority.
