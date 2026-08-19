---
title: Smart Timetable Stage 2 Version Foundation
module: workforce-planning
date: 2026-08-19
knowledge_impact: yes
---

# Smart Timetable Stage 2 Version Foundation

Stage 2 converted timetable storage from one mutable live set into a durable versioned aggregate without adding automatic generation. It added input snapshots, timetable versions, one exact-scope active pointer, future generation-run records, version-owned placements, lock metadata, and version-scoped collision constraints.

Existing populated branch/year timetables are migrated exactly into one imported compatibility version and made operational through an active pointer. Deterministically inconsistent rows remain unchanged and produce safe stale evidence. Empty settings-only scopes are not versioned.

The current assignment experience remains available through a copy-on-write bridge. The first edit of an active imported timetable creates a working draft; later legacy edits reuse that draft. Active history remains immutable, while page views and XLSX/PDF exports resolve the operational version.

No solver, worker, generation endpoint, generation UI, room/resource model, availability model, or new timetable capacity authority was added.

