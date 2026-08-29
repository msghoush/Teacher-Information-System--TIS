from __future__ import annotations

from collections import Counter, defaultdict

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

        demand_id_by_key = {demand_key(item): item["demand_id"] for item in problem["demands"]}
        teacher_preference_total = 0
        teacher_preference_satisfied = 0
        for rule in problem.get("teacher_scheduling_rules") or []:
            eligible_ids = set(rule.get("eligible_demand_ids") or [])
            allowed_slots = {
                (slot["day_key"], int(slot["period_index"]))
                for slot in rule.get("resolved_slots") or []
            }
            if rule["rule_type"] == "schedule_within":
                if any(
                    demand_id_by_key.get(demand_key(item)) in eligible_ids
                    and (str(item.get("day_key") or "").lower(), int(item.get("period_index") or 0)) not in allowed_slots
                    for item in placements
                ):
                    add("teacher_schedule_window_violated", "A teacher lesson was scheduled outside its required period window.")
                continue
            for slot in rule.get("resolved_slots") or []:
                matching = sum(
                    1 for item in placements
                    if int(item.get("teacher_id") or 0) == int(rule["teacher_id"])
                    and str(item.get("day_key") or "").lower() == slot["day_key"]
                    and int(item.get("period_index") or 0) == int(slot["period_index"])
                    and demand_id_by_key.get(demand_key(item)) in eligible_ids
                )
                any_teacher = sum(
                    1 for item in placements
                    if int(item.get("teacher_id") or 0) == int(rule["teacher_id"])
                    and str(item.get("day_key") or "").lower() == slot["day_key"]
                    and int(item.get("period_index") or 0) == int(slot["period_index"])
                )
                if rule["rule_type"] == "must_teach" and matching != 1:
                    add("teacher_must_teach_missing", "A required teacher scheduling rule was not satisfied.")
                elif rule["rule_type"] == "unavailable" and any_teacher:
                    add("teacher_unavailable_violated", "A teacher was scheduled during a required unavailable period.")
                elif rule["rule_type"] in {"prefer_teaching", "prefer_free"}:
                    teacher_preference_total += 1
                    if (rule["rule_type"] == "prefer_teaching" and matching) or (
                        rule["rule_type"] == "prefer_free" and not any_teacher
                    ):
                        teacher_preference_satisfied += 1

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
        slot_lookup = {(item["day_key"], item["period_index"]): item for item in problem["slots"]}
        placements_by_demand = defaultdict(list)
        for item in placements:
            placements_by_demand[demand_key(item)].append((
                str(item.get("day_key") or "").lower(), int(item.get("period_index") or 0),
            ))
        for demand in problem["demands"]:
            key = demand_key(demand)
            code = demand["subject_code"]
            rule = demand.get("distribution_rule")
            if rule is not None:
                # Generalized Subject Distribution Rule hard checks replace
                # the legacy flat code-list checks for this demand.
                coverage_mode = rule.get("require_daily_coverage") or "auto"
                if coverage_mode != "never" and int(demand["required_weekly_periods"]) >= len(working_days):
                    for day in working_days:
                        if placements_by_demand_day[(key, day)] < 1:
                            add("distribution_daily_coverage_missing", "A configured Subject Distribution Rule requires daily coverage that is missing.")
                max_per_day = rule.get("max_periods_per_day")
                if max_per_day and rule.get("strictness") == "hard":
                    if any(placements_by_demand_day[(key, day)] > int(max_per_day) for day in working_days):
                        add("distribution_max_per_day_exceeded", "A configured Subject Distribution Rule exceeds its hard maximum periods per day.")
                if rule.get("strictness") == "hard" and rule.get("min_teaching_days"):
                    distinct_days = {day for day in working_days if placements_by_demand_day[(key, day)] > 0}
                    if len(distinct_days) < int(rule["min_teaching_days"]):
                        add("distribution_min_teaching_days_missing", "A configured Subject Distribution Rule requires more distinct teaching days than were scheduled.")
                block_count = int(rule.get("block_count") or 0)
                if block_count > 0:
                    total_blocks = 0
                    for day in working_days:
                        selected = sorted(period for (d, period) in placements_by_demand.get(key, []) if d == day)
                        consumed = set()
                        for period in selected:
                            if period in consumed:
                                continue
                            if (period + 1) in selected and (period + 1) not in consumed and (
                                slot_lookup.get((day, period), {}).get("next_period_physically_adjacent")
                            ):
                                total_blocks += 1
                                consumed.update({period, period + 1})
                    if total_blocks != block_count:
                        add("distribution_block_count_mismatch", "A configured Subject Distribution Rule does not contain the exact required number of true consecutive blocks.")
            else:
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
                "teacher_preferences": teacher_preference_total,
                "teacher_preferences_satisfied": teacher_preference_satisfied,
            },
        }
