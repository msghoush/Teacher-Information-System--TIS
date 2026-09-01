---
title: Structured Timetable Conflict Evidence
date: 2026-09-01
module: workforce-planning
knowledge_impact: yes
---

# Structured Timetable Conflict Evidence

Advanced Timetable Release 1 now uses `timetable_conflicts.py` as its canonical
conflict boundary. The contract records a stable machine code, legacy source code,
HARD/SOFT severity, DURABLE/RECALCULABLE/TRANSIENT evidence class, safe message,
optional safe entities and slots, remediation, provenance, and internal requirement,
allocation, or constraint correlation.

Public conflict serialization deliberately replaces internal correlation values
with presence flags. Internal Lesson Requirement hashes and solver clauses are
never emitted. Same-scope entity references may reuse information already exposed
by the authorized workflow; unauthorized or cross-tenant references are generic
and redacted.

Readiness retains its existing blocker/warning fields and adds canonical conflicts.
Feasibility retains stored diagnostics and adds durable conflict projections.
Generation-run responses derive durable conflict evidence from existing terminal
status, failure category, safe message, and finish time. The independent validator
retains legacy errors and adds recalculable canonical conflicts without importing
CP-SAT.

Infeasibility, timeout, cancellation, stale authority, independent validation
failure, and solver/execution failure remain distinct. Recalculable readiness and
validation evidence is not persisted. No universal conflict table, migration,
Room, generic availability, Resource, co-teaching, or frontend redesign was added.
