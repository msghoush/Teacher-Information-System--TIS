---
title: Smart Timetable Stage 5.2 Simplified Workflow And Published Visibility
module: workforce-planning
date: 2026-08-26
knowledge_impact: yes
---

# Smart Timetable Stage 5.2 Simplified Workflow And Published Visibility

Stage 5.2 simplified the school workflow to Configure, Generate Draft, Review/Edit
Draft, and Publish to Users while preserving all Stage 2–5.1
version and solver internals. Customer language replaces technical lifecycle state on
the main page; version selection, comparison, exports, and archive remain in History.

Delete Draft Timetable permanently removes an eligible current mutable unpublished
candidate under scope locks. It removes version placements, preserves snapshots,
runs, audit fields, official publication, and history, and uses
`timetable.delete_versions`. Historical Archive remains a separate History-only action.

Timetable History permits permanent deletion of any non-active, never-published
candidate regardless of origin or internal draft/archive state. Unpublished dependent
versions are removed child-first, generation source/result links are nulled where
optional, shared snapshots and generation audit records remain, and protected published
lineage or active generation is reported rather than silently removed. The dedicated
assignable `timetable.delete_versions` permission controls this action and is included
in the Administrator defaults. History also provides exact-scope Delete All Unpublished Timetables.

Authorized users may drag an unlocked lesson within a mutable Draft Timetable to a
canonical teaching slot. Empty destinations produce an immediate move; occupied
destinations attempt one atomic swap. Non-teaching periods, active publication,
locked lessons, class collisions, and teacher collisions fail without a partial edit.
Successful edits increment the existing revision and return the candidate to the
normal re-check workflow. Publishing now requires explicit first-publication or
replacement confirmation and presents Published to Users instead of technical active
version language; publication permissions and transaction semantics are unchanged.

The Published Timetable management view offers Edit This Timetable, which copies the
official timetable into an editable draft, and Create New Timetable, which creates a
fresh empty draft from current Planning/configuration authority. Both preserve the
official timetable and active pointer until the draft is explicitly published.

The published-only service resolves strictly from `TimetableActiveVersion`.
`/my-timetable` uses exact-scope teacher identity and exposes only that teacher's
official lessons. A general published page supports other view-only users. Management
drafts, history, solver details, readiness, locks, and controls are not exposed there.
No schema, migration, CP-SAT constraint, deployment, or production action occurred.
