---
title: Smart Timetable Stage 4 Version Publication
module: workforce-planning
date: 2026-08-21
knowledge_impact: yes
---

# Smart Timetable Stage 4 Version Publication

Stage 4 made the Stage 2 lifecycle visible without adding automatic generation.
The timetable page identifies the selected version, lifecycle, origin, freshness,
manual changes, and active state; lists same-scope history; and permits explicit
historical review without changing the active timetable.

Immutable history can be copied to a new draft. Draft lessons can be locked or
unlocked under a dedicated permission, and lock changes refresh snapshot authority.
Version-specific solver-independent validation checks current authority, demand
completion, Planning teachers, canonical slots, collisions, stale placements, and
locks. Generation readiness remains a separate scope-input evaluation.

Publishing a fresh validated draft locks and revalidates the version and revisioned
active pointer, preserves the previous active version as superseded history, records
the actor/time, and makes the published version immutable. Same-scope comparison,
selected-version XLSX/PDF export, and safe draft/superseded archive behavior are also
available. Placement permissions are aligned separately for create, replace, and
clear. No schema, solver, worker, generation endpoint, availability, rooms/resources,
commit, push, deployment, or production action was introduced.
