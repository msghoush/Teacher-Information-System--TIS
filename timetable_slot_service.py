from __future__ import annotations

from datetime import datetime
from typing import Any

TEACHING_SLOT = "teaching"
NON_TEACHING_SLOT = "non_teaching"
INVALID_SLOT = "invalid_configuration"
AFTER_PERIOD_MODE = "after_period"
FIXED_TIME_MODE = "fixed_time"


def _parse_time(value: Any) -> int | None:
    try:
        parsed = datetime.strptime(str(value or "").strip(), "%H:%M")
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def _format_time(value: int) -> str:
    value %= 24 * 60
    return f"{value // 60:02d}:{value % 60:02d}"


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _issue(message: str, *, day_key: str = "", label: str = "") -> dict:
    return {"code": "invalid_non_teaching_block", "message": message, "day_key": day_key, "display_label": label}


def _public_block(block: dict) -> dict:
    return {
        "id": block.get("id"),
        "block_type": str(block.get("block_type") or "non_teaching"),
        "block_type_label": str(block.get("block_type_label") or "Non-Teaching"),
        "label": str(block.get("label") or "Non-Teaching Block"),
        "day_key": str(block.get("day_key") or "all"),
        "placement_mode": str(block.get("placement_mode") or FIXED_TIME_MODE),
        "insert_after_period": _safe_int(block.get("insert_after_period")) or None,
        "duration_minutes": _safe_int(block.get("duration_minutes")) or None,
        "start_time": str(block.get("start_time") or ""),
        "end_time": str(block.get("end_time") or ""),
        "time_range": str(block.get("time_range") or ""),
        "accent": str(block.get("accent") or "#475569"), "soft": str(block.get("soft") or "#f3f6f9"),
        "border": str(block.get("border") or "#d6e0ea"), "text": str(block.get("text") or "#334155"),
    }


def build_canonical_slot_projection(*, school_group_id: int | None, branch_id: int | None,
    academic_year_id: int | None, working_day_keys: list[str], periods_per_day: int,
    period_duration_minutes: int, school_start_time: str, school_end_time: str = "",
    time_slots: list[dict] | None = None, blocks: list[dict] | None = None) -> dict:
    """Compose the authoritative per-day teaching and non-teaching timeline."""
    from timetable_snapshot_service import canonical_json, fingerprint

    days = list(dict.fromkeys(str(day).strip().lower() for day in working_day_keys or [] if str(day).strip()))
    period_count, duration, start = _safe_int(periods_per_day), _safe_int(period_duration_minutes), _parse_time(school_start_time)
    issues: list[dict] = []
    if not days:
        issues.append({"code": "period_structure_invalid", "message": "Select at least one working day.", "day_key": "", "display_label": "Working days"})
    if period_count <= 0 or duration <= 0 or start is None:
        issues.append({"code": "period_structure_invalid", "message": "The teaching-period structure is incomplete or invalid.", "day_key": "", "display_label": "Timetable configuration"})

    normalized_blocks = [_public_block(dict(block)) for block in blocks or []]
    applicable: dict[str, list[dict]] = {day: [] for day in days}
    for order, block in enumerate(normalized_blocks):
        block["source_order"] = order
        target_days = days if block["day_key"] == "all" else [block["day_key"]]
        if any(day not in days for day in target_days):
            issues.append(_issue(f"{block['label']} has an invalid working day.", label=block["label"])); continue
        if block["placement_mode"] == AFTER_PERIOD_MODE:
            boundary, block_duration = block["insert_after_period"], block["duration_minutes"]
            if not boundary or not 1 <= boundary <= period_count:
                issues.append(_issue(f"{block['label']} has an invalid after-period placement.", label=block["label"])); continue
            if not block_duration or block_duration <= 0:
                issues.append(_issue(f"{block['label']} must have a positive duration.", label=block["label"])); continue
        elif block["placement_mode"] == FIXED_TIME_MODE:
            block_start, block_end = _parse_time(block["start_time"]), _parse_time(block["end_time"])
            if block_start is None or block_end is None or block_start >= block_end:
                issues.append(_issue(f"{block['label']} has an invalid fixed time range.", label=block["label"])); continue
            block["duration_minutes"] = block_end - block_start
        else:
            issues.append(_issue(f"{block['label']} has an invalid placement mode.", label=block["label"])); continue
        for day in target_days:
            applicable[day].append(dict(block))

    timelines: list[dict] = []; slots: list[dict] = []; projected_blocks: list[dict] = []; max_end = start or 0
    if period_count > 0 and duration > 0 and start is not None:
        for day in days:
            cursor, sequence, items = start, 1, []
            after_blocks: dict[int, list[dict]] = {}; fixed_blocks = []
            for block in applicable[day]:
                (after_blocks.setdefault(block["insert_after_period"], []).append(block)
                    if block["placement_mode"] == AFTER_PERIOD_MODE else fixed_blocks.append(block))
            fixed_blocks.sort(key=lambda block: (_parse_time(block["start_time"]) or -1, block["source_order"])); used_fixed: set[int] = set()

            def insert_fixed_at_boundary() -> None:
                nonlocal cursor, sequence
                while True:
                    matches = [(index, block) for index, block in enumerate(fixed_blocks) if index not in used_fixed and _parse_time(block["start_time"]) == cursor]
                    if not matches: return
                    index, block = matches[0]; used_fixed.add(index); block_end = _parse_time(block["end_time"]) or cursor
                    resolved = dict(block, day_key=day, start_time=_format_time(cursor), end_time=_format_time(block_end), time_range=f"{_format_time(cursor)}–{_format_time(block_end)}")
                    items.append({"type": NON_TEACHING_SLOT, "status": NON_TEACHING_SLOT, "sequence": sequence, **resolved}); projected_blocks.append(resolved)
                    sequence += 1; cursor = block_end

            insert_fixed_at_boundary()
            for period_index in range(1, period_count + 1):
                period_start, period_end = cursor, cursor + duration
                item = {"type": TEACHING_SLOT, "status": TEACHING_SLOT, "sequence": sequence, "day_key": day,
                    "period_index": period_index, "label": f"Period {period_index}", "start_time": _format_time(period_start),
                    "end_time": _format_time(period_end), "time_range": f"{_format_time(period_start)}–{_format_time(period_end)}",
                    "schedulable": True, "reason_code": ""}
                items.append(item); slots.append(item); sequence += 1; cursor = period_end; insert_fixed_at_boundary()
                for block in sorted(after_blocks.get(period_index, []), key=lambda value: value["source_order"]):
                    block_end = cursor + int(block["duration_minutes"])
                    resolved = dict(block, day_key=day, start_time=_format_time(cursor), end_time=_format_time(block_end), time_range=f"{_format_time(cursor)}–{_format_time(block_end)}")
                    items.append({"type": NON_TEACHING_SLOT, "status": NON_TEACHING_SLOT, "sequence": sequence, **resolved}); projected_blocks.append(resolved)
                    sequence += 1; cursor = block_end
                insert_fixed_at_boundary()
            for index, block in enumerate(fixed_blocks):
                if index in used_fixed: continue
                block_start, label = _parse_time(block["start_time"]), block["label"]
                inside = block_start is not None and any(_parse_time(item["start_time"]) < block_start < _parse_time(item["end_time"]) for item in items if item["type"] == TEACHING_SLOT)
                message = (f"{label} starts inside a teaching period on {day.title()}; choose a valid timeline boundary." if inside
                    else f"{label} does not match a valid timeline boundary on {day.title()}.")
                issues.append(_issue(message, day_key=day, label=label))
            block_minutes = sum(int(item.get("duration_minutes") or 0) for item in items if item["type"] == NON_TEACHING_SLOT)
            timelines.append({"day_key": day, "start_time": _format_time(start), "end_time": _format_time(cursor),
                "teaching_minutes": period_count * duration, "block_minutes": block_minutes, "shift_minutes": cursor - start, "items": items})
            max_end = max(max_end, cursor)

    seen = set(); deduped = []
    for issue in issues:
        token = (issue["code"], issue["message"], issue["day_key"], issue["display_label"])
        if token not in seen: seen.add(token); deduped.append(issue)
    slot_map = {(item["day_key"], item["period_index"]): item for item in slots}
    reference_periods = [dict(item) for item in (timelines[0]["items"] if timelines else []) if item["type"] == TEACHING_SLOT]
    row_keys, timeline_rows = [], []
    for timeline in timelines:
        for item in timeline["items"]:
            key = (item["type"], item.get("period_index") or item.get("id") or f"{item.get('label')}:{item.get('source_order')}")
            if key not in row_keys:
                row_keys.append(key); timeline_rows.append({"type": item["type"], "period_index": item.get("period_index"), "label": item["label"], "items_by_day": {}, "_sort_order": item["sequence"]})
            row = timeline_rows[row_keys.index(key)]
            row["items_by_day"][timeline["day_key"]] = item
            row["_sort_order"] = min(row["_sort_order"], item["sequence"])
    timeline_rows.sort(key=lambda row: (row.pop("_sort_order"), 0 if row["type"] == NON_TEACHING_SLOT else 1))
    fp_payload = {"scope": {"school_group_id": school_group_id, "branch_id": branch_id, "academic_year_id": academic_year_id},
        "working_day_keys": days, "periods_per_day": period_count, "period_duration_minutes": duration,
        "school_start_time": str(school_start_time or ""), "calculated_school_end_time": _format_time(max_end) if start is not None else "",
        "timelines": timelines, "issues": deduped}
    return {"scope": fp_payload["scope"], "valid": not deduped, "working_day_keys": days, "periods": reference_periods,
        "teaching_slots": slots, "slots": slots, "slot_map": slot_map, "blocks": projected_blocks, "timelines": timelines,
        "timeline_rows": timeline_rows, "calculated_school_end_time": fp_payload["calculated_school_end_time"], "issues": deduped,
        "counts": {"configured_working_days": len(days), "configured_periods_per_day": period_count, "total_slots": len(slots),
            "teaching_slots": len(slots), "blocked_slots": len(projected_blocks), "invalid_slots": len(deduped)},
        "canonical_json": canonical_json(fp_payload), "fingerprint": fingerprint(fp_payload)}


def public_slot_projection(projection: dict) -> dict:
    return {key: value for key, value in projection.items() if key not in {"slot_map", "canonical_json"}}
