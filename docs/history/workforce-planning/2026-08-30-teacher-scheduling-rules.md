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

The administrator form was subsequently simplified to Teacher, Rule, Days,
Periods, optional Sections, and Save. It directly displays P1…Pn, uses Current/New
section labels with Select All, and removes normal grade, class-scope, and
first/last controls. Schedule within these periods was added as a distinct hard
semantic through migration `20260830_002_teacher_scheduling_window_semantics`:
existing assigned lessons must fit inside the selected window, but selected slots
do not create or imply extra lessons. Existing Must-teach, first/last, grade-target,
and preference rows retain their original meaning.

Final administrator polish made Select All bidirectionally synchronize the exact
visible Current/New section checkboxes, restored those targets during edit, and
made saved summaries display grade-section names, All assigned sections, or All
classes as appropriate. Selected-section targets remain intact through snapshots,
the problem builder, CP-SAT, and independent validation.

Manual Draft edits now reject hard Unavailable placements and lessons outside an
applicable Schedule-within window. Missing Must-teach occupancy remains permissible
while editing, but complete Draft validation detects it along with unavailable,
window, and selected-section target violations. That shared hard validation blocks
approval and publication; soft preferences remain non-blocking and published
history is unchanged.
