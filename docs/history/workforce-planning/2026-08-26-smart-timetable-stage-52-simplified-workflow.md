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

Timetable History also permits permanent deletion of an unused candidate only when it
is not active and has never been published. The operation removes the candidate's
entries and version, preserves the active pointer and published history, retains shared
snapshots, generation runs, and audit records, and refuses candidates referenced by
later generation work.

Authorized users may drag an unlocked lesson within a mutable Working Timetable to a
canonical teaching slot. Empty destinations produce an immediate move; occupied
destinations attempt one atomic swap. Non-teaching periods, active publication,
locked lessons, class collisions, and teacher collisions fail without a partial edit.
Successful edits increment the existing revision and return the candidate to the
normal re-check workflow. Publishing now requires explicit first-publication or
replacement confirmation and presents Published to Users instead of technical active
version language; publication permissions and transaction semantics are unchanged.

The published-only service resolves strictly from `TimetableActiveVersion`.
`/my-timetable` uses exact-scope teacher identity and exposes only that teacher's
official lessons. A general published page supports other view-only users. Management
drafts, history, solver details, readiness, locks, and controls are not exposed there.
No schema, migration, CP-SAT constraint, deployment, or production action occurred.
