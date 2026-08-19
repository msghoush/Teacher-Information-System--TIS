from __future__ import annotations

from datetime import datetime
from typing import Any


TEACHING_SLOT = "teaching"
NON_TEACHING_SLOT = "non_teaching"
INVALID_SLOT = "invalid_configuration"


def _parse_time(value: Any) -> int | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.strptime(cleaned, "%H:%M")
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _public_block(block: dict) -> dict:
    return {
        "id": block.get("id"),
        "block_type": str(block.get("block_type") or "non_teaching"),
        "block_type_label": str(block.get("block_type_label") or "Non-Teaching"),
        "label": str(block.get("label") or "Blocked"),
        "day_key": str(block.get("day_key") or "all"),
        "start_time": str(block.get("start_time") or ""),
        "end_time": str(block.get("end_time") or ""),
        "time_range": str(block.get("time_range") or ""),
        "accent": str(block.get("accent") or "#475569"),
        "soft": str(block.get("soft") or "#f3f6f9"),
        "border": str(block.get("border") or "#d6e0ea"),
        "text": str(block.get("text") or "#334155"),
    }


def _issue(code: str, message: str, *, day_key: str = "", label: str = "") -> dict:
    return {
        "code": code,
        "message": message,
        "day_key": day_key,
        "display_label": label,
    }


def build_canonical_slot_projection(
    *,
    school_group_id: int | None,
    branch_id: int | None,
    academic_year_id: int | None,
    working_day_keys: list[str],
    periods_per_day: int,
    period_duration_minutes: int,
    school_start_time: str,
    school_end_time: str,
    time_slots: list[dict],
    blocks: list[dict],
) -> dict:
    """Return authoritative fixed teaching/non-teaching slot semantics."""
    from timetable_snapshot_service import canonical_json, fingerprint

    days = [str(day).strip().lower() for day in working_day_keys or [] if str(day).strip()]
    periods = sorted(
        [dict(slot) for slot in time_slots or []],
        key=lambda item: _safe_int(item.get("period_index")),
    )
    issues: list[dict] = []
    expected_periods = _safe_int(periods_per_day)
    duration = _safe_int(period_duration_minutes)
    start_minutes = _parse_time(school_start_time)
    end_minutes = _parse_time(school_end_time)

    if expected_periods <= 0 or duration <= 0 or start_minutes is None:
        issues.append(_issue(
            "period_structure_invalid",
            "The configured teaching-period structure is incomplete or invalid.",
            label="Timetable configuration",
        ))
    expected_indexes = list(range(1, expected_periods + 1)) if expected_periods > 0 else []
    actual_indexes = [_safe_int(slot.get("period_index")) for slot in periods]
    if actual_indexes != expected_indexes:
        issues.append(_issue(
            "period_structure_invalid",
            "Teaching periods must form one complete, ordered sequence.",
            label="Teaching periods",
        ))

    period_intervals: dict[int, tuple[int, int]] = {}
    previous_end = None
    for slot in periods:
        index = _safe_int(slot.get("period_index"))
        slot_start = _parse_time(slot.get("start_time"))
        slot_end = _parse_time(slot.get("end_time"))
        if index <= 0 or slot_start is None or slot_end is None or slot_start >= slot_end:
            issues.append(_issue(
                "period_structure_invalid",
                "One or more teaching periods has an invalid time range.",
                label=str(slot.get("label") or "Teaching period"),
            ))
            continue
        if slot_end - slot_start != duration:
            issues.append(_issue(
                "period_structure_invalid",
                "A teaching period does not match the configured period duration.",
                label=str(slot.get("label") or f"Period {index}"),
            ))
        if previous_end is not None and slot_start < previous_end:
            issues.append(_issue(
                "period_structure_invalid",
                "Teaching period times overlap.",
                label=str(slot.get("label") or f"Period {index}"),
            ))
        previous_end = slot_end
        period_intervals[index] = (slot_start, slot_end)
    if periods and end_minutes is not None and period_intervals:
        if max(interval[1] for interval in period_intervals.values()) > end_minutes:
            issues.append(_issue(
                "period_structure_invalid",
                "Teaching periods extend beyond the configured school end time.",
                label="School day",
            ))

    slots: list[dict] = []
    slot_map: dict[tuple[str, int], dict] = {}
    for day_key in days:
        for slot in periods:
            item = {
                "day_key": day_key,
                "period_index": _safe_int(slot.get("period_index")),
                "status": TEACHING_SLOT,
                "schedulable": True,
                "reason_code": "",
                "block": None,
            }
            slots.append(item)
            slot_map[(day_key, item["period_index"])] = item

    projected_blocks: list[dict] = []
    intervals_by_day: dict[str, list[tuple[int, int, dict]]] = {day: [] for day in days}
    invalid_slot_keys: set[tuple[str, int]] = set()
    for block in blocks or []:
        public_block = _public_block(block)
        day_key = str(block.get("day_key") or "all").strip().lower()
        expanded_days = list(days) if day_key == "all" else [day_key]
        expanded_days = [day for day in expanded_days if day in days]
        block_start = _parse_time(block.get("start_time"))
        block_end = _parse_time(block.get("end_time"))
        label = public_block["label"]
        if not expanded_days:
            issues.append(_issue(
                "invalid_non_teaching_block",
                f"{label} does not apply to a configured working day.",
                day_key=day_key,
                label=label,
            ))
            continue
        if block_start is None or block_end is None or block_start >= block_end:
            issues.append(_issue(
                "invalid_non_teaching_block",
                f"{label} has an invalid time range.",
                day_key=day_key,
                label=label,
            ))
            continue
        block_result = {
            **public_block,
            "expanded_day_keys": expanded_days,
            "classification": "between_periods",
            "covered_slots": [],
            "invalid_slots": [],
        }
        for target_day in expanded_days:
            for period_index, (slot_start, slot_end) in period_intervals.items():
                if block_start >= slot_end or slot_start >= block_end:
                    continue
                key = (target_day, period_index)
                slot_item = slot_map.get(key)
                if slot_item is None:
                    continue
                if block_start <= slot_start and block_end >= slot_end:
                    block_result["covered_slots"].append(
                        {"day_key": target_day, "period_index": period_index}
                    )
                    slot_item.update(
                        status=NON_TEACHING_SLOT,
                        schedulable=False,
                        reason_code="full_period_block",
                        block=public_block,
                    )
                else:
                    block_result["invalid_slots"].append(
                        {"day_key": target_day, "period_index": period_index}
                    )
                    invalid_slot_keys.add(key)
                    issues.append(_issue(
                        "invalid_non_teaching_block",
                        f"{label} partially overlaps Period {period_index} on {target_day.title()}.",
                        day_key=target_day,
                        label=label,
                    ))
            intervals_by_day[target_day].append((block_start, block_end, public_block))
        if block_result["invalid_slots"]:
            block_result["classification"] = "invalid_partial_overlap"
        elif block_result["covered_slots"]:
            block_result["classification"] = "full_period"
        projected_blocks.append(block_result)

    for day_key, intervals in intervals_by_day.items():
        ordered = sorted(intervals, key=lambda item: (item[0], item[1], item[2]["label"]))
        for index, (left_start, left_end, left_block) in enumerate(ordered):
            for right_start, right_end, right_block in ordered[index + 1 :]:
                if right_start >= left_end:
                    break
                if left_start < right_end and right_start < left_end:
                    issues.append(_issue(
                        "invalid_non_teaching_block",
                        f"{left_block['label']} overlaps {right_block['label']} on {day_key.title()}.",
                        day_key=day_key,
                        label=left_block["label"],
                    ))

    for key in invalid_slot_keys:
        item = slot_map.get(key)
        if item is not None:
            item.update(
                status=INVALID_SLOT,
                schedulable=False,
                reason_code="partial_period_overlap",
            )

    deduplicated_issues = []
    seen_issues = set()
    for issue in issues:
        key = (issue["code"], issue["message"], issue["day_key"], issue["display_label"])
        if key not in seen_issues:
            seen_issues.add(key)
            deduplicated_issues.append(issue)

    public_slots = sorted(slots, key=lambda item: (item["day_key"], item["period_index"]))
    fingerprint_payload = {
        "scope": {
            "school_group_id": school_group_id,
            "branch_id": branch_id,
            "academic_year_id": academic_year_id,
        },
        "working_day_keys": days,
        "periods": [
            {
                "period_index": _safe_int(slot.get("period_index")),
                "start_time": str(slot.get("start_time") or ""),
                "end_time": str(slot.get("end_time") or ""),
            }
            for slot in periods
        ],
        "slots": [
            {
                "day_key": item["day_key"],
                "period_index": item["period_index"],
                "status": item["status"],
                "reason_code": item["reason_code"],
                "block_type": (item.get("block") or {}).get("block_type"),
            }
            for item in public_slots
        ],
        "issues": deduplicated_issues,
    }
    return {
        "scope": fingerprint_payload["scope"],
        "valid": not deduplicated_issues,
        "working_day_keys": days,
        "periods": periods,
        "slots": public_slots,
        "slot_map": slot_map,
        "blocks": projected_blocks,
        "issues": deduplicated_issues,
        "counts": {
            "configured_working_days": len(days),
            "configured_periods_per_day": len(periods),
            "total_slots": len(public_slots),
            "teaching_slots": sum(1 for item in public_slots if item["status"] == TEACHING_SLOT),
            "blocked_slots": sum(1 for item in public_slots if item["status"] == NON_TEACHING_SLOT),
            "invalid_slots": sum(1 for item in public_slots if item["status"] == INVALID_SLOT),
        },
        "canonical_json": canonical_json(fingerprint_payload),
        "fingerprint": fingerprint(fingerprint_payload),
    }


def public_slot_projection(projection: dict) -> dict:
    return {
        key: value
        for key, value in projection.items()
        if key not in {"slot_map", "canonical_json"}
    }
