---
title: Workforce Planning History
module: workforce-planning
last_updated: 2026-06-26
---

# Workforce Planning History

- [2026-08-30 teacher scheduling rules](2026-08-30-teacher-scheduling-rules.md)
- [2026-08-29 reduce-only curriculum adjustment](2026-08-29-reduce-only-curriculum-adjustment.md)
- [2026-08-29 curriculum transfer and Subjects display correction](2026-08-29-curriculum-transfer-and-subjects-display-fix.md)
- [2026-08-29 guided curriculum adjustment UI](2026-08-29-guided-curriculum-adjustment-ui.md)

This folder tracks meaningful changes to teacher information, workload planning, staffing gaps, planning sections, timetable relationships, and related reports.

Related files:

- `routers/teachers.py`
- `routers/planning.py`
- `routers/timetable.py`
- `teacher_capacity.py`
- `timetable_logic.py`

History entries:

- `2026-08-29-curriculum-adjustment-apply.md` — permissioned fingerprint guard,
  atomic apply/audit, explicit teacher decisions, and Draft invalidation.

- `2026-08-29-curriculum-adjustment-preview.md` — read-only scoped transfer preview,
  teacher/capacity options, rule/grouped warnings, Draft impact, and stale guard.

- `2026-08-28-planning-subject-demand-consumers.md` — live Planning, workload,
  timetable, scheduling-rule, and required-hours report consumers adopt explicit
  per-section demand authority with missing-row legacy fallback.

- `2026-08-28-explicit-planning-subject-demand-foundation.md` — normalized future
  section-subject demand, safe backfill, scoped integrity, retirement state, and
  transitional legacy compatibility.

- `2026-08-21-smart-timetable-stage-4-version-publication.md` — visible version history, draft locks/validation, comparison, explicit export, archive, and atomic publication.
- `2026-08-21-smart-timetable-stage-35-composed-timeline.md` — automatic per-day teaching/block composition, calculated end time, explicit placement modes, and shared slot authority.

- `2026-08-19-smart-timetable-stage-3-readiness-and-slot-semantics.md` — canonical fixed-period slot semantics, assignment protection, and solver-independent readiness.

- `2026-08-19-smart-timetable-stage-2-version-foundation.md` — durable timetable versions, snapshots, active pointer, locks, migration, and legacy edit/export compatibility.
