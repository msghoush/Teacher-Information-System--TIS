---
title: Smart Timetable Stage 5.2 Simplified Workflow And Published Visibility
module: workforce-planning
date: 2026-08-26
knowledge_impact: yes
---

# Smart Timetable Stage 5.2 Simplified Workflow And Published Visibility

Stage 5.2 simplified the school workflow to Configure, Ready, Generate, Review,
Regenerate or Delete Working Timetable, and Publish while preserving all Stage 2–5.1
version and solver internals. Customer language replaces technical lifecycle state on
the main page; version selection, comparison, exports, and archive remain in History.

Delete Working Timetable archives the current mutable unpublished candidate under
scope locks. It preserves placements, snapshots, runs, audit fields, official
publication, and history. `timetable.delete_working` controls the action separately.

The published-only service resolves strictly from `TimetableActiveVersion`.
`/my-timetable` uses exact-scope teacher identity and exposes only that teacher's
official lessons. A general published page supports other view-only users. Management
drafts, history, solver details, readiness, locks, and controls are not exposed there.
No schema, migration, CP-SAT constraint, deployment, or production action occurred.
