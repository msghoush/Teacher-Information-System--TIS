---
title: Professional Timetable Lifecycle UX
module: workforce-planning
date: 2026-09-02
---

# Professional Timetable Lifecycle UX

The timetable workspace now exposes the existing Release 1 lifecycle in customer
language: Draft, Validate, Approve, and Publish. This is not a new persisted state.
Successful validation records approval and moves the Draft to `publication_ready`;
the scoped active pointer identifies the official published version.

Version/history cards show origin/source, created or generated time, validation,
approval, publication, mutability, and current-publication identity. Permissioned
actions create independent working Drafts from current published or immutable
history, while starting an empty Draft is separate. Generate and Regenerate are
explicitly Draft operations.

Stale guidance explains that older inputs are neither corruption nor proof of
infeasibility. Mutation/publication responses retain their message and status behavior
while adding canonical conflicts for revision races, stale validation, approval,
immutability, lifecycle errors, blocked slots, counts, and collisions. The UI offers
a keyboard-accessible refresh action for stale concurrency evidence.

No migration, solver/Workflow behavior, Room, generic availability, Resource,
co-teaching, partial regeneration, AI, or opaque score was added.
