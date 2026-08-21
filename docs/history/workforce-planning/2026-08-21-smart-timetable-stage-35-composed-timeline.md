---
title: Smart Timetable Stage 3.5 Composed Timeline
documentation_version: 1.0
last_updated: 2026-08-21
status: implemented
module: workforce-planning
---

# Smart Timetable Stage 3.5 Composed Timeline

Stage 3.5 corrected the configuration engine so teaching clocks are no longer
calculated independently of non-teaching blocks. One canonical service now composes
each working day from shift start, teaching-period count and duration, and applicable
blocks. After-period blocks insert at a selected teaching boundary and shift every
later period. Fixed-time rows remain compatible only when their stored start is a live
boundary; ambiguous rows remain unchanged and produce an explicit blocker.

The calculated end, configuration preview, main timetable bands, readiness,
assignment validation, snapshot fingerprints, future solver-ready teaching slots,
and XLSX/PDF rows consume the same projection. The migration adds placement mode,
after-period boundary, and duration columns idempotently and defaults legacy rows to
fixed time. Controlled block types were expanded without removing existing keys.

This stage added no solver, OR-Tools package, Generate/Regenerate endpoint,
availability, room/resource, or soft-constraint configuration.
