---
title: Planning And Subject Delete Dependency Guards
module: workforce-planning
last_updated: 2026-09-03
---

# Planning And Subject Delete Dependency Guards

Deleting a Planning section or a Subject previously either raised an unhandled
`IntegrityError` (Internal Server Error) once enough dependent authoritative
data existed, or in the Subject case silently succeeded for reference types no
existing check covered. Both routes now perform a read-only, scope-safe
dependency check before any mutation and block deletion with a specific,
customer-safe explanation naming every blocking category and a real next
action, rather than crashing, deleting silently, or leaving the administrator
with no path forward.

Planning section delete (`routers/planning.py:delete_planning_section`) checks
for `TeacherSectionAssignment`, `PlanningSubjectDemand`, `TimetableEntry`,
`TeacherSchedulingRuleTarget`, `CalendarEvent`/`CalendarEventSectionTarget`,
and section-scoped `SubjectDistributionRule` references. `TeacherSectionAssignment`
is no longer silently deleted alongside the section - it is now a blocker like
every other category, since no documented product rule required the previous
cascade; the admin removes it through the existing Edit Planning Section save
flow and retries. Multiple simultaneous blockers are listed individually with
the specific action that resolves each one.

Planning subject demand is split into two honest cases rather than being
treated as uniformly permanent. Curriculum Adjustment
(`curriculum_adjustment_apply_service._set_demand`) always stamps
`updated_by_user_id` on a row it creates or modifies, while the one-time
setup backfill migration never sets it. A demand row with no
`updated_by_user_id` has therefore never been acted on by an admin - it is
pure setup scaffolding - and a new, narrowly scoped action,
`GET /planning/subject-demand/delete/{demand_id}` (surfaced as "Remove
demand" next to the subject on the Planning page), hard-deletes exactly that
row so the section can then be deleted. A row Curriculum Adjustment has ever
touched, active or retired, is genuine history TIS preserves permanently
(retirement never deletes the row), so it remains a permanent blocker with an
honest explanation instead of a false "remove and retry" promise. Timetable
placements follow the equivalent split implicitly: only entries in a mutable
Draft can be removed, while published/active/superseded/archived placements
are permanent history.

Subject delete and Bulk Delete (`routers/subjects.py`) consolidate what were
previously two narrower checks into one `_get_subject_delete_blockers` scan
covering `Teacher.subject_code`, `TeacherSubjectAllocation`,
`TeacherSectionAssignment`, `PlanningSubjectDemand` (using the same
removable/permanent split), `TimetableEntry.subject_code`,
`CurriculumAdjustmentAudit` source/target codes, and
`SubjectDistributionRule.subject_code`. The last three had no prior
application-level check at all - a Subject referenced only by timetable
placements, Curriculum Adjustment history, or a distribution-rule override
could previously be deleted, silently orphaning that historical reference.
Bulk Delete is atomic from the administrator's perspective: if any selected
Subject is blocked, nothing in the batch is deleted, and every blocked
Subject is named with its specific reason so the admin can resolve it (using
the same Planning-page Remove-demand action where applicable) and retry. An
unforeseen dependency reaching the database commit is still caught by an
`IntegrityError` rollback rather than surfacing a raw error.

No archive/closed/inactive lifecycle, broad schema change, migration, or
cascade deletion was introduced. The one new capability is a narrow,
permission-gated hard delete of an untouched `PlanningSubjectDemand` row -
using an existing, unused-until-now column (`updated_by_user_id`) as the
sole eligibility signal - so every blocker shown to an admin now has either a
real removal path or an honest permanent-history explanation.
