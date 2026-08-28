from __future__ import annotations

from collections import Counter

from timetable_problem_builder import demand_key, placement_key


class TimetableSolutionValidator:
    """Validate generated placements without importing or trusting the solver."""

    def validate(
        self,
        *,
        problem: dict,
        placements: list[dict],
        expected_fingerprint: str,
        current_fingerprint: str,
        expected_source_revision: int | None = None,
        current_source_revision: int | None = None,
        expected_scope: dict | None = None,
        current_scope: dict | None = None,
    ) -> dict:
        errors = []

        def add(code: str, message: str) -> None:
            errors.append({"code": code, "message": message})

        if not expected_fingerprint or expected_fingerprint != current_fingerprint:
            add("stale_input", "Timetable inputs changed while generation was running.")
        if expected_source_revision is not None and (
            current_source_revision is None
            or int(expected_source_revision) != int(current_source_revision)
        ):
            add("stale_source", "The regeneration source changed while generation was running.")

        problem_scope = {
            key: int((problem.get("scope") or {}).get(key) or 0)
            for key in ("school_group_id", "branch_id", "academic_year_id")
        }
        if expected_scope is not None:
            normalized_expected = {key: int(expected_scope.get(key) or 0) for key in problem_scope}
            if problem_scope != normalized_expected:
                add("scope_mismatch", "The candidate problem is outside the requested timetable scope.")
        if current_scope is not None:
            normalized_current = {key: int(current_scope.get(key) or 0) for key in problem_scope}
            if problem_scope != normalized_current:
                add("stale_scope", "The selected timetable scope changed during generation.")

        demand_counts = Counter({
            (item["section_id"], item["subject_code"], item["teacher_id"]):
                int(item["required_weekly_periods"])
            for item in problem["demands"]
        })
        candidate_counts = Counter()
        slot_keys = {(item["day_key"], item["period_index"]) for item in problem["slots"]}
        section_slots = set()
        teacher_slots = {}
        grouped_member = {}
        for group in problem.get("grouped_activities") or []:
            for section_id in group.get("section_ids") or []:
                grouped_member[(int(section_id), str(group["subject_code"]), int(group["teacher_id"]))] = group["key"]
        candidate_keys = set()
        for item in placements:
            key = demand_key(item)
            slot = (
                str(item.get("day_key") or "").strip().lower(),
                int(item.get("period_index") or 0),
            )
            if key not in demand_counts:
                add("extra_lesson", "The candidate contains a lesson outside captured demand.")
            else:
                candidate_counts[key] += 1
            if slot not in slot_keys:
                add("invalid_slot", "The candidate uses a non-canonical teaching slot.")
            section_slot = (key[0], *slot)
            teacher_slot = (key[2], *slot)
            if section_slot in section_slots:
                add("section_collision", "A section has two lessons in the same slot.")
            group_key = grouped_member.get(key)
            if teacher_slot in teacher_slots and (not group_key or teacher_slots[teacher_slot] != group_key):
                add("teacher_collision", "A teacher has two lessons in the same slot.")
            section_slots.add(section_slot)
            teacher_slots[teacher_slot] = group_key
            candidate_keys.add(placement_key(item))

        if len(placements) != sum(demand_counts.values()):
            add("total_demand_mismatch", "The candidate does not contain the exact total demand.")
        for key, required in demand_counts.items():
            if candidate_counts[key] != required:
                add("demand_mismatch", "A section-subject demand is not scheduled exactly.")

        for lock in problem["locks"]:
            if placement_key(lock) not in candidate_keys:
                add("lock_missing", "A locked lesson was not preserved.")

        quality = problem.get("quality_rules") or {}
        core_codes = {
            str(code).upper()
            for values in (quality.get("core_subject_codes") or {}).values()
            for code in values or []
        }
        ict_codes = {str(code).upper() for code in quality.get("ict_subject_codes") or []}
        working_days = list(problem.get("working_days") or [])
        placements_by_demand_day = Counter(
            (demand_key(item), str(item.get("day_key") or "").lower()) for item in placements
        )
        for demand in problem["demands"]:
            key = demand_key(demand)
            code = demand["subject_code"]
            if code in core_codes and int(demand["required_weekly_periods"]) >= len(working_days):
                for day in working_days:
                    if placements_by_demand_day[(key, day)] < 1:
                        add("core_daily_coverage_missing", "A configured core subject is missing from a required teaching day.")
            if code in ict_codes and quality.get("ict_hard_one_per_day") and int(demand["required_weekly_periods"]) <= len(working_days):
                if any(placements_by_demand_day[(key, day)] > 1 for day in working_days):
                    add("ict_daily_max_exceeded", "ICT exceeds the configured maximum of one session per day.")

        resource_slots = Counter()
        for group in problem.get("grouped_activities") or []:
            for day, period in slot_keys:
                present = [
                    (int(section_id), str(group["subject_code"]), int(group["teacher_id"]), day, period) in candidate_keys
                    for section_id in group.get("section_ids") or []
                ]
                if any(present) and not all(present):
                    add("grouped_activity_incomplete", "A grouped Swimming activity is not simultaneous for every configured section.")
                if all(present) and group.get("resource_key"):
                    resource_slots[(group["resource_key"], day, period)] += 1
        for group in problem.get("grouped_activities") or []:
            if group.get("resource_key") and any(
                count > int(group.get("resource_capacity") or 1)
                for (resource, _day, _period), count in resource_slots.items()
                if resource == group["resource_key"]
            ):
                add("grouped_resource_collision", "A grouped activity exceeds its configured shared resource capacity.")

        if problem.get("request_mode") == "regenerate":
            source_unlocked = {
                placement_key(item) for item in problem.get("source_arrangement") or []
                if not item.get("is_locked")
            }
            changed = len(source_unlocked - candidate_keys)
            if changed < int(problem.get("minimum_difference") or 0):
                add(
                    "diversity_insufficient",
                    "The regenerated timetable is not sufficiently different from its source.",
                )

        unique_errors = []
        seen = set()
        for error in errors:
            token = (error["code"], error["message"])
            if token not in seen:
                seen.add(token)
                unique_errors.append(error)
        return {
            "valid": not unique_errors,
            "errors": unique_errors,
            "counts": {
                "required": sum(demand_counts.values()),
                "placements": len(placements),
                "locks": len(problem["locks"]),
            },
        }
