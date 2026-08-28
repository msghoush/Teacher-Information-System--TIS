# Planning Subject Demand Consumer Transition

On 2026-08-28, Stage 2 moved live required-period consumers from direct grade-level
`Subject.weekly_hours` inference to exact-scope, explicit-first
`PlanningSubjectDemand` resolution. Planning totals, teacher workload, timetable
readiness/workspace/snapshot/generation input, Subject Scheduling Rule arithmetic,
and required-hours reporting now honor per-section active, inactive, and zero demand.

Sections without an explicit row retain the Stage 1 legacy fallback during the
transition. Teacher assignment identity, solver behavior, timetable presentation,
and published timetable history were not redesigned or mutated.
