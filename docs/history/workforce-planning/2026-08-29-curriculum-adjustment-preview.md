---
title: Read-Only Curriculum Adjustment Preview
module: workforce-planning
date: 2026-08-29
knowledge_impact: yes
---

# Read-Only Curriculum Adjustment Preview

Stage 3 adds a non-mutating preview for late subject-demand changes after Planning,
teacher allocation, and Draft Timetable data exist. It supports one grade, selected
Current/New sections, or all active source uses within one exact tenant/branch/year.

The result projects source-to-target periods, current teachers, suggested but
uncommitted teacher choices, load/capacity, normalized scheduling-rule arithmetic,
grouped legacy warnings, and Draft stale/regeneration consequences. A deterministic
fingerprint binds the analyzed authority for future stale-confirmation checks.

No demand or assignment is written, no timetable is regenerated, and published
history remains untouched. Apply and atomic rollback behavior are not part of this
stage.
