---
title: Smart Timetable Stage 3 Readiness And Slot Semantics
module: workforce-planning
last_updated: 2026-08-19
---

# Smart Timetable Stage 3 Readiness And Slot Semantics

Stage 3 introduced one deterministic projection from existing timetable settings.
Teaching periods stay fixed. Full-period/all-day blocks disable covered slots,
every-day rules expand across configured days, between-period blocks consume no
lesson slot, and partial overlaps are explicit configuration errors.

The read-only `TimetableReadinessService` evaluates one selected organization,
branch, and academic year against configuration, Planning demand/allocation, HRT,
authoritative teacher capacity, slot sanity, locks, staleness, and active runs. Only
`generation_ready` is ready, and it does not guarantee solver feasibility.

The page shows readiness and corrective links. Unavailable slots cannot be assigned
through either the route or mutation service; existing placements are preserved as
stale. Versions and exports remain compatible. No schema, solver, worker,
generation endpoint, availability, rooms/resources, or Stage 4 publication UI was
introduced.
