---
title: Explicit Planning Subject Demand Foundation
module: workforce-planning
date: 2026-08-28
knowledge_impact: yes
---

# Explicit Planning Subject Demand Foundation

Stage 1 adds `planning_subject_demands` as the normalized future authority for one
Planning section's subject and weekly periods. Rows are branch/year scoped, retain
active or retired state, and carry normal timestamps and optional actor metadata.
Composite section and Subject foreign keys prevent scope drift. A partial unique
index permits one active row per section and subject while preserving retired rows.

Migration `20260828_004_planning_subject_demands_foundation` backfills only Current
and New Planning sections. It joins Subjects by branch, academic year, and grade,
copies the current weekly hours, and inserts only when no prior section-subject demand
exists so reruns neither duplicate demand nor reactivate retirement evidence.

`planning_subject_demand_service.py` resolves explicit rows before legacy grade and
weekly-hours fallback. An inactive explicit row is retirement evidence and suppresses
fallback. No existing consumer changes authority in Stage 1: teacher allocation,
reports, readiness, timetable snapshots and generation, drafts, publication, and UX
remain unchanged. No production or local `tis.db` operation occurred.
