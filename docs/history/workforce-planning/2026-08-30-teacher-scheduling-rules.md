---
title: Teacher Scheduling Rules
module: workforce-planning
last_updated: 2026-08-30
---

# Teacher Scheduling Rules

Implemented tenant-scoped teacher timing configuration under Timetable Settings.
Administrators use the dedicated `timetable.manage_teacher_rules` permission to
create, edit, and remove Must teach, Unavailable, Prefer teaching, and Prefer free
rules for configured days, numbered/first/last periods, and assigned-class,
grade, or Current/New section targets.

Migration `20260830_001_teacher_scheduling_rules` creates normalized rule, slot,
and target tables after establishing the composite teacher scope required by
PostgreSQL. The tables are deferred from baseline metadata creation so the
repository's production migration order remains safe and idempotent.

Schema-v4 snapshots include canonical rules in timetable constraint authority.
Required rules are hard CP-SAT constraints, preferences affect only optimization,
and the independent validator repeats hard checks. Readiness/problem construction
reports deterministic rule, workload, availability, target, and lock conflicts.
Rule changes stale unpublished Drafts and clear approval; published timetable
history, Planning demand, and teacher allocation are unchanged. No configured
rules retains the previous generation behavior.
