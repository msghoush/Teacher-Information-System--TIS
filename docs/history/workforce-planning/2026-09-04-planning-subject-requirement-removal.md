---
title: Planning Subject Requirement Removal (Single And Bulk)
module: workforce-planning
last_updated: 2026-09-04
---

# Planning Subject Requirement Removal (Single And Bulk)

The prior round's "Remove demand" action (`GET /planning/subject-demand/
delete/{demand_id}`) only ever worked for a requirement with an explicit,
untouched `PlanningSubjectDemand` row. A purely legacy-fallback requirement -
resolved only from the Subject catalog's `weekly_hours`, with no explicit row
at all - had no removal action, and the button was simply absent with no
explanation. Reported live example: for one teacher assigned to three
subjects in the same section, only the subject with an explicit row showed
"Remove demand"; the other two, resolved by fallback, showed nothing. The
condition controlling visibility was never about the teacher - it was
whether an explicit `PlanningSubjectDemand` row existed at all for that
section+subject pair, and if so, whether Curriculum Adjustment had ever
touched it.

`_get_planning_requirement_removal_status` (`routers/planning.py`) now
classifies every requirement using `resolve_section_subject_demands` - the
exact same explicit-first/legacy-fallback authority already used to render
the page, so classification can never diverge from what is displayed:

- `removable`: an explicit row exists and `updated_by_user_id IS NULL`
  (never touched by Curriculum Adjustment) - deletable.
- `permanent`: an explicit row exists and has been touched - genuine
  history, shown as "Protected (Curriculum Adjustment history)" instead of
  a hidden or missing action.
- `fallback`: no explicit row exists; the requirement is resolved only from
  the Subject catalog - now removable by creating an explicit
  `is_active=False`/`weekly_periods=0` suppression row. Unlike a Curriculum
  Adjustment zero-out retirement, this row is stamped with only the acting
  admin's `created_by_user_id` (audit trail); `updated_by_user_id` is left
  NULL. Because `updated_by_user_id IS NULL` is exactly the signal every
  removability check in this module treats as "never touched by Curriculum
  Adjustment", the suppression row stays classified `removable`/setup-only
  instead of becoming permanent - see the correction below.
- `not_found`: no active requirement for that pair at all.

`POST /planning/subject-requirements/remove` handles both the single quick
action ("Remove Subject Requirement", one target) and checkbox-selected bulk
removal ("Bulk Remove Subject Requirements"). Targets are
`"<planning_section_id>:<subject_code>"` strings; checkboxes use the
`form="planningBulkRemoveForm"` attribute so selection works across every
section rendered on the page in a single request, not only within one
section - achievable without a frontend redesign since the whole Planning
table is already server-rendered on one page load. Every target is
scope-checked (section and subject must belong to the caller's branch/
academic year) and classified before any mutation; if any target is
`permanent`, `not_found`, unparseable, or out of scope, nothing in the batch
is removed and every blocked target is named with its specific reason,
matching the same all-or-nothing contract established for Subject bulk
delete. On success, a single-section batch reopens that section via the
existing `return_to`/`open_section_id` reopen-on-load pattern; a
multi-section batch returns to the plain Planning list, since there is no
single section to reopen. Confirmation dialogs precede both single and bulk
removal, naming the subject/count being removed.

`TeacherSectionAssignment`, `TimetableEntry`, and `CurriculumAdjustmentAudit`
rows are never touched by this action - verified directly against a teacher
assigned to all three example subjects (one explicit, two fallback), where
the assignment rows remained intact after removing both fallback
requirements. The prior round's `GET /planning/subject-demand/delete/
{demand_id}` route remains fully functional; it is no longer linked from the
rendered page for cases the new route already covers, but it is still the
supported way to fully clear a leftover setup-only suppression row (see
correction below) so that Planning section/Subject deletion can proceed.

No schema or migration change: the suppression row reuses the existing
`PlanningSubjectDemand` table and the previously-unused `created_by_user_id`/
`updated_by_user_id` columns. Subjects and Teachers pages were not changed.
A teacher-based quick-select filter for bulk selection was considered but
left out as an unnecessary frontend addition for this round; the admin
selects the relevant checkboxes directly.

## Correction (2026-09-04): setup-only suppression must not look like Curriculum Adjustment history

The first version of this change stamped a `fallback` suppression row with
`created_by_user_id`/`updated_by_user_id` both set to the acting admin -
mirroring a genuine Curriculum Adjustment retirement exactly. Since
`updated_by_user_id IS NOT NULL` is the sole signal `_get_planning_
requirement_removal_status`, `_get_planning_section_demand_status`, and
`routers.subjects._get_subject_demand_status` use to classify a row as
`permanent`/Curriculum-Adjustment-touched, that stamp made the row
permanently undeletable the instant a plain admin cleanup created it - an
admin removing a fallback requirement to unblock deleting the section could
never actually get there, breaking the remove requirement -> remove section
-> remove subject workflow this action exists for.

Fix (`_apply_planning_requirement_removal` in `routers/planning.py`): the
suppression row now sets `created_by_user_id=<acting admin>` (audit trail
of who suppressed it survives) but leaves `updated_by_user_id=None`. No
schema change. This does not conflict with any existing invariant:
`curriculum_adjustment_apply_service._set_demand` remains the only code
path that ever sets `updated_by_user_id`, so `IS NULL` continues to mean
exactly "not touched by Curriculum Adjustment" regardless of who created
the row or why. A row becomes `permanent` only when Curriculum Adjustment
itself later touches it - never merely by being suppressed from this
action.

Verified end-to-end retry flow: a `fallback` requirement is removed (status
becomes `not_found`, a setup-only row now exists) -> the Planning section
is still blocked from deletion by that leftover row, but the row itself is
still `removable` (not `permanent`) -> an admin clears it via the existing
`GET /planning/subject-demand/delete/{demand_id}` route -> the Planning
section deletes successfully -> the Subject deletes successfully. A row
Curriculum Adjustment has genuinely touched (`updated_by_user_id` set
directly) stays `permanent` throughout and is unaffected by this fix. Bulk
removal of several `fallback` requirements in one request produces only
setup-only rows (`updated_by_user_id IS NULL` on every one). No customer-
facing wording changed: "Remove Subject Requirement" / "Bulk Remove Subject
Requirements" / "Protected (Curriculum Adjustment history)" are unchanged,
and no new lifecycle terminology was introduced - an admin never needs to
know a "suppression row" exists.

## Bulk-action UI completion (2026-09-04)

The first bulk UI exposed row checkboxes but placed its only submit button
below the complete Planning table and provided no Select All control. Each
expanded section now presents a section-scoped **Select all** checkbox beside
the action it drives. The action uses the shared trash icon and reflects the
live selection in its visible label: "Remove Subject Requirement" for one or
"Remove N Subject Requirements" for several. Partial section selection gives
the Select All control an indeterminate state, and removal controls are
disabled with no selection. The existing cross-section form, atomic endpoint,
permission boundary, confirmation, and persistence behavior are unchanged.

## Empty-section deletion correction (2026-09-04)

After removing every fallback requirement, the visible section was empty but
its inactive zero-period setup suppression rows still triggered the generic
Planning-demand blocker. Section deletion now excludes only rows matching all
safe artifact conditions (`is_active=False`, `weekly_periods=0`, and
`updated_by_user_id IS NULL`) from the blocker check, then deletes those exact
branch/year-scoped rows in the same transaction as the otherwise-allowed
section delete. Cleanup does not run when another blocker exists. Active setup
requirements, Curriculum Adjustment history, teacher assignments, timetable
and calendar references, and scheduling rules remain protected. This is a
narrow artifact cleanup, not cascade deletion.
