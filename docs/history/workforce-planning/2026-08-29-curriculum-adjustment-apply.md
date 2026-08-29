---
title: Atomic Curriculum Adjustment Apply
module: workforce-planning
date: 2026-08-29
knowledge_impact: yes
---

# Atomic Curriculum Adjustment Apply

Stage 4 turns an already-reviewed preview into one exact-scope transaction. Dedicated
`curriculum.adjust` authorization, preview-fingerprint revalidation, row locks,
active-generation rejection, explicit teacher decisions, qualification/capacity,
scheduling rules, and Draft locks all gate mutation.

Successful application retires or updates source demand, makes target demand
explicit, applies only confirmed assignment choices, retires an active zero-source
section rule, marks the unpublished Draft stale, clears approval, and inserts one
durable audit. A unique scope/fingerprint prevents duplicate application. Every
affected write rolls back together on failure.

No timetable regeneration occurs. Existing snapshots and placements are preserved,
and published versions plus the active pointer are never mutated.
