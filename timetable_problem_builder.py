from __future__ import annotations

import json
from collections import Counter
from typing import Any

from subject_distribution_validator import validate_subject_distribution_rule


class TimetableProblemError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def demand_key(item: dict) -> tuple[int, str, int]:
    return (
        int(item.get("section_id") or 0),
        str(item.get("subject_code") or "").strip().upper(),
        int(item.get("teacher_id") or item.get("assigned_teacher_id") or 0),
    )


def placement_key(item: dict) -> tuple[int, str, int, str, int]:
    section_id, subject_code, teacher_id = demand_key(item)
    return (
        section_id,
        subject_code,
        teacher_id,
        str(item.get("day_key") or "").strip().lower(),
        int(item.get("period_index") or 0),
    )


def _normalized_distribution_rule(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    return {
        "block_length": int(raw.get("block_length") or 0),
        "block_count": int(raw.get("block_count") or 0),
        "single_count": int(raw.get("single_count") or 0),
        "min_teaching_days": (
            int(raw["min_teaching_days"]) if raw.get("min_teaching_days") is not None else None
        ),
        "max_periods_per_day": (
            int(raw["max_periods_per_day"]) if raw.get("max_periods_per_day") is not None else None
        ),
        "require_daily_coverage": str(raw.get("require_daily_coverage") or "auto"),
        "spread_distinct_days": bool(raw.get("spread_distinct_days", True)),
        "avoid_consecutive": bool(raw.get("avoid_consecutive", True)),
        "min_day_gap": (
            int(raw["min_day_gap"]) if raw.get("min_day_gap") is not None else None
        ),
        "strictness": str(raw.get("strictness") or "soft"),
        "source_scope_level": str(raw.get("source_scope_level") or ""),
    }


class TimetableProblemBuilder:
    """Build a solver-ready problem using only one immutable snapshot."""

    def build(self, canonical_snapshot_json: str) -> dict[str, Any]:
        try:
            snapshot = json.loads(canonical_snapshot_json)
        except (TypeError, ValueError) as exc:
            raise TimetableProblemError(
                "snapshot_invalid", "The captured timetable input is invalid."
            ) from exc
        if int(snapshot.get("schema_version") or 0) < 3:
            raise TimetableProblemError(
                "snapshot_schema_unsupported",
                "The captured timetable input predates automatic generation.",
            )

        scope = snapshot.get("scope") or {}
        if not all(int(scope.get(key) or 0) > 0 for key in (
            "school_group_id", "branch_id", "academic_year_id"
        )):
            raise TimetableProblemError(
                "scope_invalid", "The captured timetable scope is incomplete."
            )

        planning = snapshot.get("planning") or {}
        eligible_sections = {
            int(item.get("id") or 0): item
            for item in planning.get("sections") or []
            if str(item.get("class_status") or "").strip().lower()
            in {"current", "new", "active"}
        }
        valid_teachers = {
            int(value) for value in planning.get("valid_teacher_ids") or [] if int(value or 0)
        }
        if not eligible_sections:
            raise TimetableProblemError(
                "sections_missing", "No eligible Planning sections are available."
            )

        demands = []
        seen_demands = set()
        for item in planning.get("demands") or []:
            section_id = int(item.get("section_id") or 0)
            periods = int(item.get("required_weekly_periods") or 0)
            if section_id not in eligible_sections or periods <= 0:
                continue
            teacher_id = int(item.get("assigned_teacher_id") or 0)
            subject_code = str(item.get("subject_code") or "").strip().upper()
            if not subject_code or teacher_id not in valid_teachers:
                raise TimetableProblemError(
                    "teacher_authority_invalid",
                    "A timetable demand has no valid Planning or homeroom teacher.",
                )
            key = (section_id, subject_code, teacher_id)
            if key in seen_demands:
                raise TimetableProblemError(
                    "duplicate_demand", "The captured timetable demand is duplicated."
                )
            seen_demands.add(key)
            demand_id = f"section:{section_id}|subject:{subject_code}|teacher:{teacher_id}"
            demands.append({
                "demand_id": demand_id,
                "section_id": section_id,
                "subject_id": int(item.get("subject_id") or 0),
                "subject_code": subject_code,
                "teacher_id": teacher_id,
                "assignment_source": str(item.get("assignment_source") or "planning"),
                "required_weekly_periods": periods,
                # None means legacy fallback: no normalized rule is configured
                # for this exact section/subject scope.
                "distribution_rule": _normalized_distribution_rule(item.get("distribution_rule")),
            })
        demands.sort(key=lambda item: (
            item["section_id"], item["subject_code"], item["teacher_id"], item["subject_id"]
        ))
        if not demands:
            raise TimetableProblemError(
                "demand_missing", "No positive timetable demand is available."
            )

        raw_quality = ((snapshot.get("period_configuration") or {}).get("settings") or {}).get("quality_rules") or {}
        quality_rules = {
            "core_subject_codes": raw_quality.get("core_subject_codes") or {},
            "spread_subject_codes": list(raw_quality.get("spread_subject_codes") or []),
            "ict_subject_codes": list(raw_quality.get("ict_subject_codes") or []),
            "ict_hard_one_per_day": bool(raw_quality.get("ict_hard_one_per_day")),
            "avoid_consecutive_subject_codes": list(raw_quality.get("avoid_consecutive_subject_codes") or []),
            "allow_double_period_subject_codes": list(raw_quality.get("allow_double_period_subject_codes") or []),
            "regeneration_diversity_percent": int(raw_quality.get("regeneration_diversity_percent") or 25),
        }
        grouped_activities = []
        demand_by_section_subject = {
            (item["section_id"], item["subject_code"]): item for item in demands
        }
        for raw_group in raw_quality.get("swimming_groups") or []:
            subject_code = str(raw_group.get("subject_code") or "").strip().upper()
            section_ids = sorted({int(item) for item in raw_group.get("section_ids") or []})
            members = [demand_by_section_subject.get((section_id, subject_code)) for section_id in section_ids]
            if len(section_ids) < 2 or any(member is None for member in members):
                raise TimetableProblemError("grouped_activity_invalid", "A configured grouped activity does not match current section demand.")
            required_counts = {int(member["required_weekly_periods"]) for member in members}
            teacher_ids = {int(member["teacher_id"]) for member in members}
            configured_teacher = int(raw_group.get("teacher_id") or 0)
            if len(required_counts) != 1 or (configured_teacher and teacher_ids != {configured_teacher}) or len(teacher_ids) != 1:
                raise TimetableProblemError("grouped_activity_authority_invalid", "Grouped Swimming sections must have equal weekly demand and one common assigned teacher.")
            grouped_activities.append({
                "key": str(raw_group.get("key") or "grouped_activity"),
                "subject_code": subject_code,
                "section_ids": section_ids,
                "teacher_id": next(iter(teacher_ids)),
                "required_weekly_periods": next(iter(required_counts)),
                "demand_ids": [member["demand_id"] for member in members],
                "resource_key": str(raw_group.get("resource_key") or ""),
                "resource_capacity": max(int(raw_group.get("resource_capacity") or 1), 1),
            })

        period_configuration = snapshot.get("period_configuration") or {}
        projection = period_configuration.get("canonical_slot_projection") or {}
        slots = []
        seen_slots = set()
        for timeline in projection.get("timelines") or []:
            for item in timeline.get("items") or []:
                if item.get("type") != "teaching" or not item.get("schedulable", True):
                    continue
                key = (
                    str(item.get("day_key") or timeline.get("day_key") or "").lower(),
                    int(item.get("period_index") or 0),
                )
                if not key[0] or key[1] <= 0 or key in seen_slots:
                    continue
                seen_slots.add(key)
                slots.append({
                    "slot_id": f"{key[0]}:{key[1]}",
                    "day_key": key[0],
                    "period_index": key[1],
                    "start_time": str(item.get("start_time") or ""),
                    "end_time": str(item.get("end_time") or ""),
                    # True only when the composed timeline places the next
                    # period immediately after with no Break/Prayer/other
                    # non-teaching item between them.
                    "next_period_physically_adjacent": bool(item.get("next_period_physically_adjacent")),
                })
        slots.sort(key=lambda item: (
            (projection.get("working_day_keys") or []).index(item["day_key"])
            if item["day_key"] in (projection.get("working_day_keys") or []) else 999,
            item["period_index"],
        ))
        if not slots:
            raise TimetableProblemError(
                "insufficient_teaching_slots", "No canonical teaching slots are available."
            )

        slot_keys = {(item["day_key"], item["period_index"]) for item in slots}
        teacher_rules = []
        demands_by_teacher = {}
        for demand in demands:
            demands_by_teacher.setdefault(int(demand["teacher_id"]), []).append(demand)
        hard_by_teacher_slot = {}
        for raw_rule in (snapshot.get("constraints") or {}).get("teacher_scheduling_rules") or []:
            teacher_id = int(raw_rule.get("teacher_id") or 0)
            teacher_demands = demands_by_teacher.get(teacher_id) or []
            if not teacher_demands:
                raise TimetableProblemError("teacher_rule_no_demand", "A teacher scheduling rule has no assigned Planning demand.")
            target_scope = str(raw_rule.get("target_scope") or "any_assigned")
            targets = raw_rule.get("targets") or []
            eligible = list(teacher_demands)
            if target_scope == "selected_sections":
                target_ids = {int(item.get("planning_section_id") or 0) for item in targets}
                eligible = [item for item in eligible if int(item["section_id"]) in target_ids]
            elif target_scope == "selected_grades":
                grades = {str(item.get("grade_level") or "").strip().upper() for item in targets}
                eligible = [item for item in eligible if str(eligible_sections[item["section_id"]].get("grade_level") or "").strip().upper() in grades]
            if not eligible:
                raise TimetableProblemError("teacher_rule_target_unassigned", "A teacher scheduling rule target has no assigned Planning demand.")
            resolved_slots = sorted({
                (str(item.get("day_key") or "").lower(), int(item.get("period_index") or 0))
                for item in raw_rule.get("resolved_slots") or []
            })
            if not resolved_slots or any(slot not in slot_keys for slot in resolved_slots):
                raise TimetableProblemError("teacher_rule_slot_invalid", "A teacher scheduling rule uses an unavailable period.")
            rule = {
                "id": int(raw_rule.get("id") or 0), "teacher_id": teacher_id,
                "rule_type": str(raw_rule.get("rule_type") or ""),
                "strictness": str(raw_rule.get("strictness") or ""),
                "target_scope": target_scope,
                "eligible_demand_ids": sorted(item["demand_id"] for item in eligible),
                "resolved_slots": [{"day_key": day, "period_index": period} for day, period in resolved_slots],
            }
            if rule["rule_type"] in {"must_teach", "unavailable"}:
                for slot in resolved_slots:
                    key = (teacher_id, *slot)
                    existing = hard_by_teacher_slot.setdefault(key, [])
                    if rule["rule_type"] == "unavailable" and any(item["rule_type"] == "must_teach" for item in existing):
                        raise TimetableProblemError("teacher_rule_conflict", "A teacher is both required and unavailable in the same period.")
                    if rule["rule_type"] == "must_teach":
                        if any(item["rule_type"] == "unavailable" for item in existing):
                            raise TimetableProblemError("teacher_rule_conflict", "A teacher is both required and unavailable in the same period.")
                        for item in existing:
                            if item["rule_type"] == "must_teach" and not set(item["eligible_demand_ids"]) & set(rule["eligible_demand_ids"]):
                                raise TimetableProblemError("teacher_rule_conflict", "A teacher is required in different classes in the same period.")
                    existing.append(rule)
            teacher_rules.append(rule)
        for teacher_id, teacher_demands in demands_by_teacher.items():
            if not any(rule["teacher_id"] == teacher_id for rule in teacher_rules):
                continue
            workload = sum(int(item["required_weekly_periods"]) for item in teacher_demands)
            unavailable = {
                (slot["day_key"], slot["period_index"])
                for rule in teacher_rules if rule["teacher_id"] == teacher_id and rule["rule_type"] == "unavailable"
                for slot in rule["resolved_slots"]
            }
            required = {
                (slot["day_key"], slot["period_index"])
                for rule in teacher_rules if rule["teacher_id"] == teacher_id and rule["rule_type"] == "must_teach"
                for slot in rule["resolved_slots"]
            }
            if len(required) > workload:
                raise TimetableProblemError("teacher_rule_workload_infeasible", "Required teaching periods exceed the teacher's assigned weekly workload.")
            if workload > len(slot_keys - unavailable):
                raise TimetableProblemError("teacher_rule_availability_infeasible", "The teacher's workload does not fit around unavailable periods.")
        for rule in teacher_rules:
            if rule["rule_type"] == "must_teach":
                matching_total = sum(int(item["required_weekly_periods"]) for item in demands if item["demand_id"] in rule["eligible_demand_ids"])
                if len(rule["resolved_slots"]) > matching_total:
                    raise TimetableProblemError("teacher_rule_target_workload_infeasible", "Required class periods exceed matching assigned demand.")

        # Final defense-in-depth: an invalid resolved distribution rule must
        # fail cleanly here rather than reach CP-SAT with an unsatisfiable or
        # nonsensical configuration.
        available_teaching_days = len(projection.get("working_day_keys") or [])
        for demand in demands:
            rule = demand.get("distribution_rule")
            if rule is None:
                continue
            rule_errors = validate_subject_distribution_rule(
                rule,
                planning_weekly_periods=demand["required_weekly_periods"],
                available_teaching_days=available_teaching_days,
            )
            if rule_errors:
                raise TimetableProblemError(
                    "distribution_rule_invalid",
                    f"The {demand['subject_code']} distribution rule for section "
                    f"{demand['section_id']} is invalid: {rule_errors[0]['message']}",
                )

        demand_by_key = {
            (item["section_id"], item["subject_code"], item["teacher_id"]): item
            for item in demands
        }
        locks = []
        lock_demand_counts = Counter()
        section_slots = set()
        teacher_slots = {}
        grouped_member_keys = {
            (section_id, group["subject_code"], group["teacher_id"]): group["key"]
            for group in grouped_activities for section_id in group["section_ids"]
        }
        for raw_lock in snapshot.get("locks") or []:
            normalized = {
                "section_id": int(raw_lock.get("section_id") or 0),
                "subject_code": str(raw_lock.get("subject_code") or "").strip().upper(),
                "teacher_id": int(raw_lock.get("teacher_id") or 0),
                "day_key": str(raw_lock.get("day_key") or "").strip().lower(),
                "period_index": int(raw_lock.get("period_index") or 0),
            }
            key = demand_key(normalized)
            slot_key = (normalized["day_key"], normalized["period_index"])
            if key not in demand_by_key:
                raise TimetableProblemError(
                    "lock_authority_invalid",
                    "A locked lesson no longer matches Planning teacher authority.",
                )
            if slot_key not in slot_keys:
                raise TimetableProblemError(
                    "lock_slot_invalid", "A locked lesson uses an unavailable slot."
                )
            for rule in teacher_rules:
                if rule["teacher_id"] == normalized["teacher_id"] and rule["rule_type"] == "unavailable" and any(
                    (item["day_key"], item["period_index"]) == slot_key for item in rule["resolved_slots"]
                ):
                    raise TimetableProblemError("teacher_rule_lock_conflict", "A locked lesson conflicts with a teacher unavailable rule.")
                if rule["teacher_id"] == normalized["teacher_id"] and rule["rule_type"] == "must_teach" and any(
                    (item["day_key"], item["period_index"]) == slot_key for item in rule["resolved_slots"]
                ) and demand_by_key[key]["demand_id"] not in rule["eligible_demand_ids"]:
                    raise TimetableProblemError("teacher_rule_lock_conflict", "A locked lesson prevents a required teacher class in the same period.")
            section_slot = (normalized["section_id"], *slot_key)
            teacher_slot = (normalized["teacher_id"], *slot_key)
            group_key = grouped_member_keys.get(key)
            if section_slot in section_slots or (
                teacher_slot in teacher_slots and (not group_key or teacher_slots[teacher_slot] != group_key)
            ):
                raise TimetableProblemError(
                    "lock_conflict", "Locked lessons conflict in the same timetable slot."
                )
            section_slots.add(section_slot)
            teacher_slots[teacher_slot] = group_key
            lock_demand_counts[key] += 1
            if lock_demand_counts[key] > demand_by_key[key]["required_weekly_periods"]:
                raise TimetableProblemError(
                    "locked_count_exceeds_demand",
                    "Locked lessons exceed the corresponding weekly demand.",
                )
            locks.append(normalized)
        locks.sort(key=placement_key)

        lesson_instances = []
        for demand in demands:
            for ordinal in range(1, demand["required_weekly_periods"] + 1):
                lesson_instances.append({
                    "lesson_instance_id": f"{demand['demand_id']}|ordinal:{ordinal}",
                    "demand_id": demand["demand_id"],
                    "ordinal": ordinal,
                })

        constraints = snapshot.get("constraints") or {}
        generation = constraints.get("generation") or {}
        source_arrangement = []
        for item in generation.get("source_arrangement") or []:
            normalized = {
                "section_id": int(item.get("section_id") or 0),
                "subject_code": str(item.get("subject_code") or "").strip().upper(),
                "teacher_id": int(item.get("teacher_id") or 0),
                "day_key": str(item.get("day_key") or "").strip().lower(),
                "period_index": int(item.get("period_index") or 0),
                "is_locked": bool(item.get("is_locked")),
            }
            if demand_key(normalized) not in demand_by_key or (
                normalized["day_key"], normalized["period_index"]
            ) not in slot_keys:
                raise TimetableProblemError(
                    "source_arrangement_invalid",
                    "The regeneration source no longer matches the captured timetable input.",
                )
            source_arrangement.append(normalized)
        source_arrangement.sort(key=placement_key)

        minimum_difference = int(generation.get("minimum_difference") or 0)
        unlocked_source_count = sum(1 for item in source_arrangement if not item["is_locked"])
        if minimum_difference < 0 or minimum_difference > unlocked_source_count:
            raise TimetableProblemError(
                "diversity_invalid", "The regeneration diversity requirement is invalid."
            )

        return {
            "schema_version": int(snapshot["schema_version"]),
            "scope": {key: int(scope[key]) for key in (
                "school_group_id", "branch_id", "academic_year_id"
            )},
            "working_days": list(projection.get("working_day_keys") or []),
            "slots": slots,
            "sections": [eligible_sections[key] for key in sorted(eligible_sections)],
            "demands": demands,
            "lesson_instances": lesson_instances,
            "locks": locks,
            "request_mode": str(generation.get("request_mode") or "generate"),
            "source_version_id": generation.get("source_version_id"),
            "source_edit_revision": generation.get("source_edit_revision"),
            "source_lifecycle_status": generation.get("source_lifecycle_status"),
            "source_arrangement": source_arrangement,
            "minimum_difference": minimum_difference,
            "quality_rules": quality_rules,
            "grouped_activities": grouped_activities,
            "teacher_scheduling_rules": teacher_rules,
        }
