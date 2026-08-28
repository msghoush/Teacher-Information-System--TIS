from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

import models
from homeroom_defaults import is_default_homeroom_subject
from subject_colors import build_subject_theme, resolve_subject_color
from teacher_capacity import get_teacher_international_capacity_hours
from timetable_slot_service import format_time_range


WORKING_DAY_OPTIONS = (
    {"key": "sunday", "label": "Sunday", "short_label": "Sun"},
    {"key": "monday", "label": "Monday", "short_label": "Mon"},
    {"key": "tuesday", "label": "Tuesday", "short_label": "Tue"},
    {"key": "wednesday", "label": "Wednesday", "short_label": "Wed"},
    {"key": "thursday", "label": "Thursday", "short_label": "Thu"},
    {"key": "friday", "label": "Friday", "short_label": "Fri"},
    {"key": "saturday", "label": "Saturday", "short_label": "Sat"},
)
WORKING_DAY_LOOKUP = {
    item["key"]: item
    for item in WORKING_DAY_OPTIONS
}
ALL_DAY_KEY = "all"
DEFAULT_WORKING_DAY_KEYS = [
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
]
BLOCK_TYPE_OPTIONS = (
    {"key": "break", "label": "Break"},
    {"key": "recess", "label": "Recess"},
    {"key": "lunch", "label": "Lunch"},
    {"key": "prayer", "label": "Prayer"},
    {"key": "assembly", "label": "Assembly"},
    {"key": "whole_school_event", "label": "Whole-School Event"},
    {"key": "advisory", "label": "Advisory / Homeroom"},
    {"key": "intervention", "label": "Intervention / Support"},
    {"key": "transition", "label": "Transition"},
    {"key": "dismissal_preparation", "label": "Dismissal Preparation"},
    {"key": "non_teaching", "label": "Non-Teaching"},
    {"key": "other", "label": "Other"},
)
BLOCK_TYPE_LABELS = {
    item["key"]: item["label"]
    for item in BLOCK_TYPE_OPTIONS
}
BLOCK_TYPE_THEMES = {
    "break": {
        "accent": "#C77D19",
        "soft": "#FFF5E8",
        "border": "#F3D3A7",
        "text": "#8A4F00",
    },
    "prayer": {
        "accent": "#0B6A63",
        "soft": "#EEF9F4",
        "border": "#BDE0D2",
        "text": "#0E5A54",
    },
    "non_teaching": {
        "accent": "#475569",
        "soft": "#F3F6F9",
        "border": "#D6E0EA",
        "text": "#334155",
    },
}
DEFAULT_TIMETABLE_SETTINGS = {
    "working_day_keys": list(DEFAULT_WORKING_DAY_KEYS),
    "periods_per_day": 8,
    "period_duration_minutes": 45,
    "school_start_time": "07:00",
}
DEFAULT_TIMETABLE_SETTINGS["school_end_time"] = ""
DEFAULT_TIMETABLE_QUALITY_RULES = {
    "core_subject_codes": {
        "english": ["ENG"],
        "mathematics": ["MAT"],
        "science": ["SCI"],
    },
    "spread_subject_codes": ["ART", "WLB", "SOC", "REF"],
    "ict_subject_codes": ["ICT"],
    "ict_hard_one_per_day": True,
    "avoid_consecutive_subject_codes": ["ENG", "MAT", "SCI", "ART", "WLB", "SOC", "REF", "ICT"],
    "allow_double_period_subject_codes": [],
    "swimming_groups": [],
    "regeneration_diversity_percent": 25,
}


def _normalized_code_list(value) -> list[str]:
    raw = value.split(",") if isinstance(value, str) else (value or [])
    return sorted({str(item or "").strip().upper() for item in raw if str(item or "").strip()})


def _positive_int_or_default(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalize_timetable_quality_rules(value=None) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except (TypeError, ValueError):
            value = {}
    source = value if isinstance(value, dict) else {}
    core = source.get("core_subject_codes") if isinstance(source.get("core_subject_codes"), dict) else {}
    groups = []
    for index, raw in enumerate(source.get("swimming_groups") or []):
        if not isinstance(raw, dict):
            continue
        section_ids = sorted({int(item) for item in raw.get("section_ids") or [] if str(item).isdigit() and int(item) > 0})
        subject_code = str(raw.get("subject_code") or "").strip().upper()
        if len(section_ids) < 2 or not subject_code:
            continue
        groups.append({
            "key": str(raw.get("key") or f"swimming_group_{index + 1}").strip(),
            "subject_code": subject_code,
            "section_ids": section_ids,
            "teacher_id": _positive_int_or_default(raw.get("teacher_id"), 0) or None,
            "resource_key": str(raw.get("resource_key") or "").strip(),
            "resource_capacity": _positive_int_or_default(raw.get("resource_capacity"), 1),
        })
    try:
        diversity = int(source.get("regeneration_diversity_percent", 25))
    except (TypeError, ValueError):
        diversity = 25
    return {
        "core_subject_codes": {
            key: _normalized_code_list(core.get(key, DEFAULT_TIMETABLE_QUALITY_RULES["core_subject_codes"][key]))
            for key in ("english", "mathematics", "science")
        },
        "spread_subject_codes": _normalized_code_list(source.get("spread_subject_codes", DEFAULT_TIMETABLE_QUALITY_RULES["spread_subject_codes"])),
        "ict_subject_codes": _normalized_code_list(source.get("ict_subject_codes", DEFAULT_TIMETABLE_QUALITY_RULES["ict_subject_codes"])),
        "ict_hard_one_per_day": bool(source.get("ict_hard_one_per_day", True)),
        "avoid_consecutive_subject_codes": _normalized_code_list(source.get("avoid_consecutive_subject_codes", DEFAULT_TIMETABLE_QUALITY_RULES["avoid_consecutive_subject_codes"])),
        "allow_double_period_subject_codes": _normalized_code_list(source.get("allow_double_period_subject_codes", [])),
        "swimming_groups": groups,
        "regeneration_diversity_percent": min(max(diversity, 1), 100),
    }


def _parse_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def get_scope_ids(current_user):
    branch_id = getattr(current_user, "scope_branch_id", current_user.branch_id)
    academic_year_id = getattr(
        current_user,
        "scope_academic_year_id",
        current_user.academic_year_id,
    )
    return branch_id, academic_year_id


def normalize_day_key(value) -> str:
    cleaned = str(value or "").strip().lower().replace(" ", "_")
    if cleaned == ALL_DAY_KEY:
        return ALL_DAY_KEY
    if cleaned in WORKING_DAY_LOOKUP:
        return cleaned
    return ""


def normalize_day_keys(values) -> list[str]:
    normalized_keys = []
    seen_keys = set()
    for raw_value in values or []:
        day_key = normalize_day_key(raw_value)
        if not day_key or day_key == ALL_DAY_KEY or day_key in seen_keys:
            continue
        seen_keys.add(day_key)
        normalized_keys.append(day_key)
    return normalized_keys


def get_working_day_payload(day_keys) -> list[dict]:
    return [
        dict(WORKING_DAY_LOOKUP[day_key])
        for day_key in normalize_day_keys(day_keys)
        if day_key in WORKING_DAY_LOOKUP
    ]


def get_day_label(day_key: str) -> str:
    if normalize_day_key(day_key) == ALL_DAY_KEY:
        return "All Days"
    return WORKING_DAY_LOOKUP.get(normalize_day_key(day_key), {}).get(
        "label",
        "Unknown Day",
    )


def get_day_short_label(day_key: str) -> str:
    if normalize_day_key(day_key) == ALL_DAY_KEY:
        return "All"
    return WORKING_DAY_LOOKUP.get(normalize_day_key(day_key), {}).get(
        "short_label",
        "Day",
    )


def get_default_school_end_time(
    school_start_time: str,
    periods_per_day: int,
    period_duration_minutes: int,
) -> str:
    start_minutes = parse_time_value(school_start_time)
    if start_minutes is None:
        start_minutes = 7 * 60
    return format_minutes_as_time(
        start_minutes + max(periods_per_day, 0) * max(period_duration_minutes, 0)
    )


def parse_time_value(value) -> int | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed_time = datetime.strptime(cleaned, "%H:%M")
    except ValueError:
        return None
    return parsed_time.hour * 60 + parsed_time.minute


def format_minutes_as_time(value: int | None) -> str:
    if value is None:
        return ""
    safe_value = max(0, int(value))
    hours = (safe_value // 60) % 24
    minutes = safe_value % 60
    return f"{hours:02d}:{minutes:02d}"


def build_time_slots(
    periods_per_day: int,
    period_duration_minutes: int,
    school_start_time: str,
    non_teaching_blocks: list[dict] | None = None,
) -> list[dict]:
    safe_periods = max(int(periods_per_day or 0), 0)
    safe_duration = max(int(period_duration_minutes or 0), 0)
    start_minutes = parse_time_value(school_start_time)
    if start_minutes is None:
        start_minutes = 7 * 60

    slots = []
    current_minutes = start_minutes
    for period_index in range(1, safe_periods + 1):
        # Period numbering and times stay fixed. The canonical projection
        # classifies blocks without shifting, shortening, or renumbering them.
        end_minutes = current_minutes + safe_duration
        slots.append(
            {
                "period_index": period_index,
                "label": f"Period {period_index}",
                "short_label": f"P{period_index}",
                "start_time": format_minutes_as_time(current_minutes),
                "end_time": format_minutes_as_time(end_minutes),
                "time_range": format_time_range(
                    format_minutes_as_time(current_minutes), format_minutes_as_time(end_minutes)
                ),
            }
        )
        current_minutes = end_minutes
    return slots


def build_default_timetable_settings_payload() -> dict:
    school_end_time = get_default_school_end_time(
        DEFAULT_TIMETABLE_SETTINGS["school_start_time"],
        DEFAULT_TIMETABLE_SETTINGS["periods_per_day"],
        DEFAULT_TIMETABLE_SETTINGS["period_duration_minutes"],
    )
    return {
        "id": None,
        "is_saved": False,
        "working_day_keys": list(DEFAULT_TIMETABLE_SETTINGS["working_day_keys"]),
        "periods_per_day": DEFAULT_TIMETABLE_SETTINGS["periods_per_day"],
        "period_duration_minutes": DEFAULT_TIMETABLE_SETTINGS["period_duration_minutes"],
        "school_start_time": DEFAULT_TIMETABLE_SETTINGS["school_start_time"],
        "school_end_time": school_end_time,
        "blocks": [],
        "quality_rules": normalize_timetable_quality_rules(),
    }


def get_timetable_setting_row(db, branch_id: int, academic_year_id: int):
    return db.query(models.TimetableSetting).filter(
        models.TimetableSetting.branch_id == branch_id,
        models.TimetableSetting.academic_year_id == academic_year_id,
    ).first()


def get_timetable_block_rows(db, timetable_setting_id: int | None):
    if not timetable_setting_id:
        return []
    return db.query(models.TimetableNonTeachingBlock).filter(
        models.TimetableNonTeachingBlock.timetable_setting_id == timetable_setting_id
    ).order_by(
        models.TimetableNonTeachingBlock.day_key.asc(),
        models.TimetableNonTeachingBlock.start_period.asc(),
        models.TimetableNonTeachingBlock.id.asc(),
    ).all()


def _time_slots_by_period(time_slots: list[dict]) -> dict[int, dict]:
    return {
        int(slot.get("period_index") or 0): slot
        for slot in time_slots or []
        if int(slot.get("period_index") or 0) > 0
    }


def serialize_timetable_block(block_row, working_day_keys, time_slots: list[dict]) -> dict:
    block_type = normalize_block_type(getattr(block_row, "block_type", ""))
    day_key = normalize_day_key(getattr(block_row, "day_key", ""))
    expanded_day_keys = (
        list(working_day_keys)
        if day_key == ALL_DAY_KEY
        else [day_key]
    )
    period_lookup = _time_slots_by_period(time_slots)
    start_period = int(getattr(block_row, "start_period", 0) or 0)
    end_period = int(getattr(block_row, "end_period", 0) or 0)
    start_slot = period_lookup.get(start_period)
    end_slot = period_lookup.get(end_period)
    start_time = str(getattr(block_row, "start_time", "") or "").strip()
    end_time = str(getattr(block_row, "end_time", "") or "").strip()
    placement_mode = str(getattr(block_row, "placement_mode", "") or "fixed_time").strip()
    insert_after_period = int(getattr(block_row, "insert_after_period", 0) or 0) or None
    duration_minutes = int(getattr(block_row, "duration_minutes", 0) or 0) or None
    if placement_mode == "fixed_time" and not start_time and start_slot:
        start_time = str(start_slot.get("start_time") or "").strip()
    if placement_mode == "fixed_time" and not end_time and end_slot:
        end_time = str(end_slot.get("end_time") or "").strip()
    if placement_mode == "fixed_time" and not end_time and start_slot:
        end_time = str(start_slot.get("end_time") or "").strip()
    start_minutes = parse_time_value(start_time)
    end_minutes = parse_time_value(end_time)
    theme = BLOCK_TYPE_THEMES.get(block_type, BLOCK_TYPE_THEMES["non_teaching"])
    return {
        "id": getattr(block_row, "id", None),
        "block_type": block_type,
        "block_type_label": BLOCK_TYPE_LABELS.get(block_type, "Non-Teaching"),
        "label": str(getattr(block_row, "label", "") or "").strip() or "Blocked",
        "day_key": day_key or ALL_DAY_KEY,
        "day_label": get_day_label(day_key or ALL_DAY_KEY),
        "expanded_day_keys": [
            key for key in expanded_day_keys
            if key in working_day_keys
        ],
        "start_period": start_period,
        "end_period": end_period,
        "placement_mode": placement_mode,
        "placement_mode_label": "After Period" if placement_mode == "after_period" else "Fixed Time",
        "insert_after_period": insert_after_period,
        "duration_minutes": duration_minutes,
        "start_time": start_time,
        "end_time": end_time,
        "start_minutes": start_minutes,
        "end_minutes": end_minutes,
        "time_range": format_time_range(start_time, end_time),
        "accent": theme["accent"],
        "soft": theme["soft"],
        "border": theme["border"],
        "text": theme["text"],
    }


def build_non_teaching_slot_map(
    blocks: list[dict],
    working_day_keys: list[str],
    time_slots: list[dict],
) -> dict[tuple[str, int], dict]:
    # Compatibility wrapper: all consumers share the canonical projection.
    from timetable_slot_service import build_canonical_slot_projection

    durations = [
        parse_time_value(slot.get("end_time")) - parse_time_value(slot.get("start_time"))
        for slot in time_slots or []
        if parse_time_value(slot.get("start_time")) is not None
        and parse_time_value(slot.get("end_time")) is not None
    ]
    projection = build_canonical_slot_projection(
        school_group_id=None,
        branch_id=None,
        academic_year_id=None,
        working_day_keys=working_day_keys,
        periods_per_day=len(time_slots or []),
        period_duration_minutes=max(durations) if durations else 0,
        school_start_time=str((time_slots or [{}])[0].get("start_time") or ""),
        school_end_time=str((time_slots or [{}])[-1].get("end_time") or ""),
        time_slots=time_slots,
        blocks=blocks,
    )
    return {
        key: value
        for key, value in projection["slot_map"].items()
        if not value.get("schedulable")
    }


def build_timetable_settings_payload(setting_row=None, block_rows=None) -> dict:
    defaults = build_default_timetable_settings_payload()
    if setting_row is None:
        working_day_keys = list(defaults["working_day_keys"])
        blocks = []
        periods_per_day = defaults["periods_per_day"]
        period_duration_minutes = defaults["period_duration_minutes"]
        school_start_time = defaults["school_start_time"]
        school_end_time = defaults["school_end_time"]
        setting_id = None
        is_saved = False
        quality_rules = normalize_timetable_quality_rules()
    else:
        working_day_keys = normalize_day_keys(
            str(getattr(setting_row, "working_days_csv", "") or "").split(",")
        )
        periods_per_day = int(getattr(setting_row, "periods_per_day", 0) or 0)
        period_duration_minutes = int(
            getattr(setting_row, "period_duration_minutes", 0) or 0
        )
        school_start_time = str(
            getattr(setting_row, "school_start_time", defaults["school_start_time"])
            or ""
        ).strip()
        school_end_time = str(
            getattr(setting_row, "school_end_time", "") or ""
        ).strip() or get_default_school_end_time(
            school_start_time,
            periods_per_day,
            period_duration_minutes,
        )
        setting_id = getattr(setting_row, "id", None)
        is_saved = True
        quality_rules = normalize_timetable_quality_rules(getattr(setting_row, "quality_rules_json", "{}"))
        time_slots = build_time_slots(
            periods_per_day,
            period_duration_minutes,
            school_start_time,
        )
        blocks = [
            serialize_timetable_block(block_row, working_day_keys, time_slots)
            for block_row in block_rows or []
        ]

    time_slots = build_time_slots(
        periods_per_day,
        period_duration_minutes,
        school_start_time,
    )
    from timetable_slot_service import build_canonical_slot_projection

    slot_projection = build_canonical_slot_projection(
        school_group_id=None,
        branch_id=None,
        academic_year_id=None,
        working_day_keys=working_day_keys,
        periods_per_day=periods_per_day,
        period_duration_minutes=period_duration_minutes,
        school_start_time=school_start_time,
        school_end_time=school_end_time,
        time_slots=time_slots,
        blocks=blocks,
    )
    block_slot_map = {}
    blocked_slot_count = (
        slot_projection["counts"]["blocked_slots"]
        + slot_projection["counts"]["invalid_slots"]
    )
    total_slot_count = len(working_day_keys) * periods_per_day
    school_end_time = slot_projection["calculated_school_end_time"]
    time_slots = slot_projection["periods"]

    return {
        "id": setting_id,
        "is_saved": is_saved,
        "working_day_keys": working_day_keys,
        "working_days": get_working_day_payload(working_day_keys),
        "periods_per_day": periods_per_day,
        "period_duration_minutes": period_duration_minutes,
        "school_start_time": school_start_time,
        "school_end_time": school_end_time,
        "time_slots": time_slots,
        "blocks": blocks,
        "composed_blocks": slot_projection["blocks"],
        "block_slot_map": block_slot_map,
        "slot_projection": slot_projection,
        "timelines": slot_projection["timelines"],
        "timeline_rows": slot_projection["timeline_rows"],
        "teaching_slots": slot_projection["teaching_slots"],
        "slot_projection_fingerprint": slot_projection["fingerprint"],
        "configuration_issues": slot_projection["issues"],
        "blocked_slot_count": blocked_slot_count,
        "total_slot_count": total_slot_count,
        "teaching_slot_count": slot_projection["counts"]["teaching_slots"],
        "quality_rules": quality_rules,
    }


def get_timetable_settings_payload(db, branch_id: int, academic_year_id: int) -> dict:
    setting_row = get_timetable_setting_row(db, branch_id, academic_year_id)
    block_rows = get_timetable_block_rows(db, getattr(setting_row, "id", None))
    return build_timetable_settings_payload(setting_row, block_rows)


def normalize_block_type(value) -> str:
    cleaned = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in BLOCK_TYPE_LABELS:
        return cleaned
    return ""


def normalize_timetable_settings_values(
    working_days,
    periods_per_day,
    period_duration_minutes,
    school_start_time,
    school_end_time,
):
    errors = []
    normalized_working_day_keys = normalize_day_keys(working_days)
    if not normalized_working_day_keys:
        errors.append("Select at least one school working day.")

    parsed_periods_per_day = _parse_int(periods_per_day)
    if parsed_periods_per_day is None or parsed_periods_per_day <= 0:
        errors.append("Periods per day must be a positive whole number.")
    elif parsed_periods_per_day > 16:
        errors.append("Periods per day must stay between 1 and 16 for the timetable grid.")

    parsed_period_duration = _parse_int(period_duration_minutes)
    if parsed_period_duration is None or parsed_period_duration <= 0:
        errors.append("Period duration must be a positive whole number of minutes.")
    elif parsed_period_duration < 20 or parsed_period_duration > 120:
        errors.append("Period duration must stay between 20 and 120 minutes.")

    normalized_school_start_time = str(school_start_time or "").strip()
    normalized_school_end_time = str(school_end_time or "").strip()
    parsed_start_minutes = parse_time_value(normalized_school_start_time)
    parsed_end_minutes = parse_time_value(normalized_school_end_time)

    if parsed_start_minutes is None:
        errors.append("School start time must use HH:MM format.")
    if normalized_school_end_time and parsed_end_minutes is None:
        errors.append("School end time must use HH:MM format.")

    computed_school_end_time = ""
    if (
        parsed_start_minutes is not None
        and parsed_periods_per_day is not None
        and parsed_period_duration is not None
        and parsed_periods_per_day > 0
        and parsed_period_duration > 0
    ):
        computed_school_end_time = get_default_school_end_time(
            normalized_school_start_time,
            parsed_periods_per_day,
            parsed_period_duration,
        )

    return {
        "working_day_keys": normalized_working_day_keys,
        "periods_per_day": parsed_periods_per_day,
        "period_duration_minutes": parsed_period_duration,
        "school_start_time": normalized_school_start_time,
        "school_end_time": computed_school_end_time or normalized_school_end_time,
        "computed_school_end_time": computed_school_end_time,
        "errors": errors,
    }


def normalize_non_teaching_block_values(
    *,
    block_type,
    label,
    day_key,
    start_time,
    end_time,
    start_period,
    end_period,
    periods_per_day,
    working_day_keys,
    time_slots,
    placement_mode="fixed_time",
    insert_after_period=None,
    duration_minutes=None,
):
    errors = []
    normalized_block_type = normalize_block_type(block_type)
    if not normalized_block_type:
        errors.append("Select a valid block type.")

    normalized_label = " ".join(str(label or "").split()).strip()
    if not normalized_label:
        errors.append("Block label is required.")

    normalized_day_key = normalize_day_key(day_key)
    if not normalized_day_key:
        errors.append("Select a valid timetable day.")
    elif normalized_day_key != ALL_DAY_KEY and normalized_day_key not in working_day_keys:
        errors.append("Selected day is not part of the configured working week.")

    normalized_placement_mode = str(placement_mode or "fixed_time").strip().lower()
    if normalized_placement_mode not in {"after_period", "fixed_time"}:
        errors.append("Select a valid block placement mode.")
    normalized_start_time = str(start_time or "").strip()
    normalized_end_time = str(end_time or "").strip()
    parsed_start_minutes = parse_time_value(normalized_start_time)
    parsed_end_minutes = parse_time_value(normalized_end_time)

    parsed_start_period = _parse_int(start_period)
    parsed_end_period = _parse_int(end_period)
    safe_periods_per_day = int(periods_per_day or 0)
    period_lookup = _time_slots_by_period(time_slots)
    parsed_insert_after_period = _parse_int(insert_after_period)
    parsed_duration_minutes = _parse_int(duration_minutes)

    # Backward compatibility for rows created before explicit block times were introduced.
    if normalized_placement_mode == "fixed_time" and parsed_start_minutes is None and parsed_start_period in period_lookup:
        parsed_start_minutes = parse_time_value(period_lookup[parsed_start_period].get("start_time"))
        normalized_start_time = str(period_lookup[parsed_start_period].get("start_time") or "").strip()
    if normalized_placement_mode == "fixed_time" and parsed_end_minutes is None and parsed_end_period in period_lookup:
        parsed_end_minutes = parse_time_value(period_lookup[parsed_end_period].get("end_time"))
        normalized_end_time = str(period_lookup[parsed_end_period].get("end_time") or "").strip()

    if normalized_placement_mode == "after_period":
        normalized_start_time = normalized_end_time = ""
        parsed_start_minutes = parsed_end_minutes = None
        if parsed_insert_after_period is None or not 1 <= parsed_insert_after_period <= safe_periods_per_day:
            errors.append("Insert After Period must identify an existing teaching period.")
        if parsed_duration_minutes is None or parsed_duration_minutes <= 0:
            errors.append("Block duration must be a positive whole number of minutes.")
        parsed_start_period = parsed_end_period = parsed_insert_after_period
    elif parsed_start_minutes is None or parsed_end_minutes is None:
        errors.append("Block start and end times must use HH:MM format.")
    elif parsed_start_minutes >= parsed_end_minutes:
        errors.append("Block end time must be after the block start time.")
    else:
        parsed_duration_minutes = parsed_end_minutes - parsed_start_minutes

    overlapping_period_indexes = []
    if normalized_placement_mode == "fixed_time" and not errors:
        for slot in time_slots or []:
            period_index = int(slot.get("period_index") or 0)
            slot_start = parse_time_value(slot.get("start_time"))
            slot_end = parse_time_value(slot.get("end_time"))
            if period_index <= 0 or slot_start is None or slot_end is None or slot_start >= slot_end:
                continue
            if parsed_start_minutes < slot_end and slot_start < parsed_end_minutes:
                overlapping_period_indexes.append(period_index)

        # Non-teaching blocks are independent rows and may sit exactly between
        # two consecutive periods (touching boundaries) without overlapping any
        # period.  Do NOT reject a block just because it falls in a gap.

    if not overlapping_period_indexes and parsed_start_period and parsed_end_period:
        if (
            parsed_start_period > 0
            and parsed_end_period > 0
            and parsed_start_period <= safe_periods_per_day
            and parsed_end_period <= safe_periods_per_day
            and parsed_start_period <= parsed_end_period
        ):
            overlapping_period_indexes = list(range(parsed_start_period, parsed_end_period + 1))

    expanded_day_keys = (
        list(working_day_keys)
        if normalized_day_key == ALL_DAY_KEY
        else [normalized_day_key]
    )
    theme = BLOCK_TYPE_THEMES.get(normalized_block_type, BLOCK_TYPE_THEMES["non_teaching"])
    return {
        "id": None,
        "block_type": normalized_block_type,
        "block_type_label": BLOCK_TYPE_LABELS.get(normalized_block_type, "Non-Teaching"),
        "label": normalized_label,
        "day_key": normalized_day_key or ALL_DAY_KEY,
        "day_label": get_day_label(normalized_day_key or ALL_DAY_KEY),
        "expanded_day_keys": [
            key for key in expanded_day_keys
            if key in working_day_keys
        ],
        "start_time": normalized_start_time,
        "end_time": normalized_end_time,
        "start_minutes": parsed_start_minutes,
        "end_minutes": parsed_end_minutes,
        "time_range": format_time_range(normalized_start_time, normalized_end_time),
        "start_period": (
            min(overlapping_period_indexes)
            if overlapping_period_indexes
            else parsed_start_period
        ),
        "end_period": (
            max(overlapping_period_indexes)
            if overlapping_period_indexes
            else parsed_end_period
        ),
        "placement_mode": normalized_placement_mode,
        "placement_mode_label": "After Period" if normalized_placement_mode == "after_period" else "Fixed Time",
        "insert_after_period": parsed_insert_after_period,
        "duration_minutes": parsed_duration_minutes,
        "accent": theme["accent"],
        "soft": theme["soft"],
        "border": theme["border"],
        "text": theme["text"],
        "errors": errors,
    }


def validate_non_teaching_block_overlap(
    existing_blocks: list[dict],
    candidate_block: dict,
    *,
    ignore_block_id: int | None = None,
) -> list[str]:
    if candidate_block.get("errors"):
        return []

    errors = []
    for block in existing_blocks:
        block_id = block.get("id")
        if ignore_block_id is not None and block_id == ignore_block_id:
            continue

        shared_days = set(block.get("expanded_day_keys") or []) & set(
            candidate_block.get("expanded_day_keys") or []
        )
        if not shared_days:
            continue
        if block.get("placement_mode", "fixed_time") != "fixed_time" or candidate_block.get("placement_mode") != "fixed_time":
            continue

        left_start = parse_time_value(block.get("start_time"))
        left_end = parse_time_value(block.get("end_time"))
        right_start = parse_time_value(candidate_block.get("start_time"))
        right_end = parse_time_value(candidate_block.get("end_time"))
        if None in {left_start, left_end, right_start, right_end}:
            continue
        if left_start < right_end and right_start < left_end:
            shared_day_labels = ", ".join(get_day_short_label(day_key) for day_key in sorted(shared_days))
            errors.append(
                f"{candidate_block.get('label', 'This block')} overlaps with "
                f"{block.get('label', 'another block')} on {shared_day_labels}."
            )
            break

    return errors


def _normalize_grade_label(value) -> str:
    cleaned = str(value or "").strip().upper()
    if cleaned in {"K", "KG", "KINDERGARTEN"}:
        return "KG"
    parsed_value = _parse_int(cleaned)
    if parsed_value is None:
        return cleaned
    return "KG" if parsed_value == 0 else str(parsed_value)


def _grade_sort_value(grade_label: str) -> int:
    if grade_label == "KG":
        return 0
    parsed_value = _parse_int(grade_label)
    if parsed_value is None:
        return 99
    return parsed_value


def build_teacher_display_name(teacher) -> str:
    name_parts = [getattr(teacher, "first_name", "")]
    middle_name = getattr(teacher, "middle_name", "")
    if middle_name:
        name_parts.append(middle_name)
    name_parts.append(getattr(teacher, "last_name", ""))
    full_name = " ".join(part for part in name_parts if part).strip()
    return full_name if full_name else f"Teacher #{getattr(teacher, 'id', '?')}"


def format_section_label(section) -> str:
    grade_label = _normalize_grade_label(getattr(section, "grade_level", ""))
    section_name = str(getattr(section, "section_name", "") or "").strip().upper()
    if grade_label == "KG":
        return f"KG-{section_name}"
    return f"Grade {grade_label}-{section_name}"


def _build_subject_theme_payload(subject_code: str, subject_name: str, stored_color="") -> dict:
    subject_color = resolve_subject_color(
        subject_code,
        stored_color,
        subject_name=subject_name,
    )
    theme = build_subject_theme(subject_color)
    return {
        "subject_color": subject_color,
        "subject_color_soft": theme["soft"],
        "subject_color_surface": theme["surface"],
        "subject_color_border": theme["border"],
        "subject_color_text": theme["text"],
        "subject_color_strong_text": theme["strong_text"],
    }


def build_timetable_workspace_payload(
    db,
    branch_id: int,
    academic_year_id: int,
    *,
    version_id: int | None = None,
    include_validation: bool = True,
) -> dict:
    from timetable_version_service import (
        TimetableVersionError,
        is_logical_draft_source,
        timetable_version_delete_eligibility,
        resolve_operational_version,
        resolve_scope_school_group_id,
        resolve_version,
        resolve_active_version,
    )

    settings_payload = get_timetable_settings_payload(db, branch_id, academic_year_id)
    branch_row = db.query(models.Branch).filter(models.Branch.id == branch_id).first()
    year_row = db.query(models.AcademicYear).filter(models.AcademicYear.id == academic_year_id).first()
    working_day_keys = list(settings_payload["working_day_keys"])
    periods_per_day = int(settings_payload["periods_per_day"] or 0)
    block_slot_map = settings_payload["block_slot_map"]

    planning_sections = db.query(models.PlanningSection).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).order_by(
        models.PlanningSection.grade_level.asc(),
        models.PlanningSection.section_name.asc(),
        models.PlanningSection.id.asc(),
    ).all()

    subjects = db.query(models.Subject).filter(
        models.Subject.branch_id == branch_id,
        models.Subject.academic_year_id == academic_year_id,
    ).order_by(
        models.Subject.grade.asc(),
        models.Subject.subject_code.asc(),
    ).all()

    teachers = db.query(models.Teacher).filter(
        models.Teacher.branch_id == branch_id,
        models.Teacher.academic_year_id == academic_year_id,
    ).order_by(
        models.Teacher.first_name.asc(),
        models.Teacher.last_name.asc(),
        models.Teacher.id.asc(),
    ).all()

    subject_rows_by_grade = defaultdict(list)
    subject_name_lookup = {}
    for subject in subjects:
        subject_code = str(getattr(subject, "subject_code", "") or "").strip().upper()
        if not subject_code:
            continue
        subject_name = str(getattr(subject, "subject_name", "") or "").strip() or "Unnamed Subject"
        grade_label = "KG" if int(getattr(subject, "grade", 0) or 0) == 0 else str(int(getattr(subject, "grade", 0) or 0))
        subject_theme = _build_subject_theme_payload(
            subject_code,
            subject_name,
            getattr(subject, "color", ""),
        )
        subject_payload = {
            "subject_code": subject_code,
            "subject_name": subject_name,
            "weekly_hours": int(getattr(subject, "weekly_hours", 0) or 0),
            "grade_label": grade_label,
            **subject_theme,
        }
        subject_rows_by_grade[grade_label].append(subject_payload)
        subject_name_lookup[subject_code] = subject_name

    teacher_map = {
        teacher.id: teacher
        for teacher in teachers
        if getattr(teacher, "id", None)
    }
    teacher_display_names = {
        teacher_id: build_teacher_display_name(teacher)
        for teacher_id, teacher in teacher_map.items()
    }

    section_assignments = db.query(models.TeacherSectionAssignment).join(
        models.PlanningSection,
        models.PlanningSection.id == models.TeacherSectionAssignment.planning_section_id,
    ).filter(
        models.PlanningSection.branch_id == branch_id,
        models.PlanningSection.academic_year_id == academic_year_id,
    ).all()
    explicit_teacher_by_section_subject = {
        (
            int(assignment.planning_section_id),
            str(assignment.subject_code or "").strip().upper(),
        ): int(assignment.teacher_id)
        for assignment in section_assignments
        if assignment.planning_section_id is not None
        and assignment.teacher_id is not None
        and str(assignment.subject_code or "").strip()
    }

    section_payloads = []
    section_lookup = {}
    section_subject_option_map = {}
    teacher_required_hours = defaultdict(int)
    teacher_commitments = defaultdict(list)

    for section in planning_sections:
        section_id = getattr(section, "id", None)
        if section_id is None:
            continue
        grade_label = _normalize_grade_label(getattr(section, "grade_level", ""))
        section_label = format_section_label(section)
        homeroom_teacher_name = teacher_display_names.get(
            getattr(section, "homeroom_teacher_id", None),
            "",
        )
        options = []
        total_required_hours = 0
        ready_to_schedule_hours = 0
        missing_teacher_hours = 0
        missing_teacher_subjects = 0

        for subject_payload in subject_rows_by_grade.get(grade_label, []):
            subject_code = subject_payload["subject_code"]
            teacher_id = explicit_teacher_by_section_subject.get((section_id, subject_code))
            assignment_source = "manual"
            if (
                teacher_id is None
                and getattr(section, "homeroom_teacher_id", None)
                and is_default_homeroom_subject(
                    grade_label,
                    subject_name=subject_payload["subject_name"],
                    subject_code=subject_code,
                )
            ):
                teacher_id = int(section.homeroom_teacher_id)
                assignment_source = "homeroom_default"

            teacher_name = teacher_display_names.get(teacher_id, "")
            is_schedulable = teacher_id in teacher_map
            weekly_hours = int(subject_payload["weekly_hours"] or 0)
            total_required_hours += weekly_hours
            if is_schedulable:
                ready_to_schedule_hours += weekly_hours
                teacher_required_hours[teacher_id] += weekly_hours
                teacher_commitments[teacher_id].append(
                    {
                        "section_id": section_id,
                        "section_label": section_label,
                        "subject_code": subject_code,
                        "subject_name": subject_payload["subject_name"],
                        "weekly_hours": weekly_hours,
                    }
                )
            else:
                missing_teacher_hours += weekly_hours
                missing_teacher_subjects += 1

            option_payload = {
                **subject_payload,
                "section_id": section_id,
                "section_label": section_label,
                "teacher_id": teacher_id,
                "teacher_name": teacher_name,
                "assignment_source": assignment_source,
                "is_schedulable": is_schedulable,
                "scheduled_count": 0,
                "remaining_hours": weekly_hours,
            }
            options.append(option_payload)
            section_subject_option_map[(section_id, subject_code)] = option_payload

        section_payload = {
            "id": section_id,
            "grade_label": grade_label,
            "section_name": str(getattr(section, "section_name", "") or "").strip().upper(),
            "section_label": section_label,
            "class_status": str(getattr(section, "class_status", "") or "").strip() or "Current",
            "homeroom_teacher_id": getattr(section, "homeroom_teacher_id", None),
            "homeroom_teacher_name": homeroom_teacher_name or "Not assigned",
            "options": options,
            "subject_count": len(options),
            "total_required_hours": total_required_hours,
            "ready_to_schedule_hours": ready_to_schedule_hours,
            "missing_teacher_hours": missing_teacher_hours,
            "missing_teacher_subjects": missing_teacher_subjects,
            "scheduled_hours": 0,
            "stale_entry_count": 0,
            "remaining_hours": total_required_hours,
        }
        section_payloads.append(section_payload)
        section_lookup[section_id] = section_payload

    operational_version = None
    selected_version = None
    active_version = None
    version_history = []
    active_pointer_revision = 0
    try:
        school_group_id = resolve_scope_school_group_id(
            db,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        operational_version = resolve_operational_version(
            db,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        active_version = resolve_active_version(
            db,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
        )
        if version_id is not None:
            selected_version = resolve_version(
                db,
                version_id=int(version_id),
                school_group_id=school_group_id,
                branch_id=branch_id,
                academic_year_id=academic_year_id,
            )
            if selected_version is None:
                raise TimetableVersionError(
                    "version_not_found",
                    "The selected timetable version is outside the current scope.",
                )
        else:
            selected_version = operational_version
        pointer = db.query(models.TimetableActiveVersion).filter(
            models.TimetableActiveVersion.school_group_id == school_group_id,
            models.TimetableActiveVersion.branch_id == branch_id,
            models.TimetableActiveVersion.academic_year_id == academic_year_id,
        ).first()
        active_pointer_revision = int(getattr(pointer, "revision", 0) or 0)
        versions = db.query(models.TimetableVersion).filter(
            models.TimetableVersion.school_group_id == school_group_id,
            models.TimetableVersion.branch_id == branch_id,
            models.TimetableVersion.academic_year_id == academic_year_id,
        ).order_by(models.TimetableVersion.version_number.desc()).all()
        version_history = []
        for row in versions:
            delete_eligibility = timetable_version_delete_eligibility(db, version=row)
            version_history.append({
                "public_id": row.public_id,
                "version_number": int(row.version_number),
                "lifecycle_status": row.lifecycle_status,
                "display_status": "active" if active_version and int(active_version.id) == int(row.id) else row.lifecycle_status,
                "origin": row.origin,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "quality_score": row.quality_score,
                "is_active": bool(active_version and int(active_version.id) == int(row.id)),
                "was_published": bool(row.published_at),
                "is_approved": bool(row.approved_at),
                "is_stale": bool(row.is_stale),
                "has_manual_changes": bool(row.has_manual_changes),
                "source_version_number": next((int(source.version_number) for source in versions if row.source_version_id and int(source.id) == int(row.source_version_id)), None),
                "edit_revision": int(row.edit_revision or 0),
                "is_logical_draft_source": is_logical_draft_source(db, row),
                "can_delete": delete_eligibility["eligible"],
                "delete_blockers": delete_eligibility["reasons"],
            })
    except TimetableVersionError:
        # The existing read-only empty-state behavior remains available while
        # the user is still selecting a complete tenant scope.
        operational_version = None
        selected_version = None

    entry_query = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.branch_id == branch_id,
        models.TimetableEntry.academic_year_id == academic_year_id,
    )
    if selected_version is None:
        entry_query = entry_query.filter(models.TimetableEntry.id == -1)
    else:
        entry_query = entry_query.filter(
            models.TimetableEntry.timetable_version_id == selected_version.id
        )
    entry_rows = entry_query.order_by(
        models.TimetableEntry.day_key.asc(),
        models.TimetableEntry.period_index.asc(),
        models.TimetableEntry.id.asc(),
    ).all()

    entries = []
    teacher_scheduled_hours = defaultdict(int)
    total_stale_entries = 0

    for entry_row in entry_rows:
        section_id = getattr(entry_row, "planning_section_id", None)
        teacher_id = getattr(entry_row, "teacher_id", None)
        subject_code = str(getattr(entry_row, "subject_code", "") or "").strip().upper()
        day_key = normalize_day_key(getattr(entry_row, "day_key", ""))
        period_index = int(getattr(entry_row, "period_index", 0) or 0)
        section_payload = section_lookup.get(section_id)
        teacher = teacher_map.get(teacher_id)
        teacher_name = teacher_display_names.get(teacher_id, "Teacher removed")
        option_payload = section_subject_option_map.get((section_id, subject_code))

        is_slot_valid = (
            not settings_payload.get("configuration_issues")
            and
            day_key in working_day_keys
            and 1 <= period_index <= periods_per_day
            and (day_key, period_index) not in block_slot_map
        )
        status = "scheduled"
        stale_reason = ""

        if not section_payload:
            status = "stale"
            stale_reason = "Section is no longer available in the active planning scope."
        elif not teacher:
            status = "stale"
            stale_reason = "Teacher is no longer available in the active branch/year scope."
        elif not option_payload:
            status = "stale"
            stale_reason = "Subject is no longer part of the selected section plan."
        elif not option_payload.get("is_schedulable"):
            status = "stale"
            stale_reason = "This subject does not currently have a teacher assigned in planning."
        elif int(option_payload.get("teacher_id") or 0) != int(teacher_id or 0):
            status = "stale"
            stale_reason = "Teacher assignment changed after this timetable slot was created."
        elif not is_slot_valid:
            status = "stale"
            stale_reason = "This slot is outside the configured teaching timetable or now blocked."

        subject_name = (
            option_payload.get("subject_name")
            if option_payload
            else subject_name_lookup.get(subject_code, "Unnamed Subject")
        )
        subject_theme = _build_subject_theme_payload(
            subject_code,
            subject_name,
        )
        entry_payload = {
            "id": getattr(entry_row, "id", None),
            "section_id": section_id,
            "section_label": section_payload.get("section_label") if section_payload else "Unknown Section",
            "teacher_id": teacher_id,
            "teacher_name": teacher_name,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "day_key": day_key,
            "day_label": get_day_label(day_key),
            "period_index": period_index,
            "status": status,
            "stale_reason": stale_reason,
            "is_locked": bool(getattr(entry_row, "is_locked", False)),
            **subject_theme,
        }
        entries.append(entry_payload)

        if section_payload:
            if status == "scheduled":
                section_payload["scheduled_hours"] += 1
                teacher_scheduled_hours[teacher_id] += 1
                if option_payload:
                    option_payload["scheduled_count"] += 1
            else:
                section_payload["stale_entry_count"] += 1
                total_stale_entries += 1
        elif status == "stale":
            total_stale_entries += 1

    for section_payload in section_payloads:
        for option_payload in section_payload["options"]:
            option_payload["remaining_hours"] = max(
                int(option_payload["weekly_hours"] or 0)
                - int(option_payload["scheduled_count"] or 0),
                0,
            )
        section_payload["remaining_hours"] = max(
            int(section_payload["total_required_hours"] or 0)
            - int(section_payload["scheduled_hours"] or 0),
            0,
        )

    teacher_payloads = []
    for teacher in teachers:
        teacher_id = getattr(teacher, "id", None)
        if teacher_id is None:
            continue
        capacity_hours = get_teacher_international_capacity_hours(
            teacher,
        )
        required_hours = teacher_required_hours.get(teacher_id, 0)
        scheduled_hours = teacher_scheduled_hours.get(teacher_id, 0)
        teacher_payloads.append(
            {
                "id": teacher_id,
                "teacher_id": str(getattr(teacher, "teacher_id", "") or "").strip(),
                "teacher_name": teacher_display_names.get(teacher_id, f"Teacher #{teacher_id}"),
                "label": (
                    f"{str(getattr(teacher, 'teacher_id', '') or '').strip()} - "
                    f"{teacher_display_names.get(teacher_id, f'Teacher #{teacher_id}')}"
                ).strip(" -"),
                "required_hours": required_hours,
                "scheduled_hours": scheduled_hours,
                "remaining_hours": max(required_hours - scheduled_hours, 0),
                "capacity_hours": capacity_hours,
                "available_capacity_hours": max(capacity_hours - required_hours, 0),
                "commitments": teacher_commitments.get(teacher_id, []),
            }
        )

    section_payloads.sort(
        key=lambda item: (
            _grade_sort_value(item["grade_label"]),
            item["section_name"],
            item["id"],
        )
    )
    teacher_payloads.sort(
        key=lambda item: (
            item["teacher_name"],
            item["id"],
        )
    )
    entries.sort(
        key=lambda item: (
            working_day_keys.index(item["day_key"]) if item["day_key"] in working_day_keys else 99,
            item["period_index"],
            item["section_label"],
            item["subject_code"],
        )
    )

    missing_teacher_subjects = sum(
        int(section_payload["missing_teacher_subjects"] or 0)
        for section_payload in section_payloads
    )
    total_required_hours = sum(
        int(section_payload["total_required_hours"] or 0)
        for section_payload in section_payloads
    )
    total_scheduled_hours = sum(
        int(section_payload["scheduled_hours"] or 0)
        for section_payload in section_payloads
    )

    warnings = []
    if not settings_payload["is_saved"]:
        warnings.append(
            "Timetable Settings are still using the default fallback profile for this branch and academic year. Save the official timetable structure in System Configuration."
        )
    if not section_payloads:
        warnings.append(
            "No planning sections are available in the active branch and academic year. Add sections in Planning before building the timetable."
        )
    if not subjects:
        warnings.append(
            "No subjects are available in the active branch and academic year. Add subjects first to build timetable requirements."
        )
    if missing_teacher_subjects > 0:
        warnings.append(
            f"{missing_teacher_subjects} section-subject requirement(s) still do not have a teacher assignment, so those hours cannot be placed on the timetable yet."
        )
    if total_stale_entries > 0:
        warnings.append(
            f"{total_stale_entries} saved timetable slot(s) no longer match the current planning assignments or timetable settings and should be reviewed."
        )

    from timetable_readiness_service import TimetableReadinessService
    from timetable_slot_service import public_slot_projection

    readiness = TimetableReadinessService(db).evaluate(
        school_group_id if 'school_group_id' in locals() else None,
        branch_id,
        academic_year_id,
    )
    current_authority_fingerprint = readiness.get("authority_fingerprint", "")
    if selected_version is not None:
        from timetable_snapshot_service import build_current_snapshot_data
        selected_snapshot = db.get(
            models.TimetableInputSnapshot, selected_version.input_snapshot_id
        )
        selected_constraints = {}
        if selected_snapshot is not None:
            selected_constraints = json.loads(
                selected_snapshot.canonical_snapshot_json
            ).get("constraints") or {}
        selected_locks = [
            {
                "section_id": row.planning_section_id,
                "subject_code": row.subject_code,
                "teacher_id": row.teacher_id,
                "day_key": row.day_key,
                "period_index": row.period_index,
            }
            for row in entry_rows
            if row.is_locked
        ]
        current_authority_fingerprint = build_current_snapshot_data(
            db,
            school_group_id=school_group_id,
            branch_id=branch_id,
            academic_year_id=academic_year_id,
            locks=selected_locks,
            constraint_configuration=selected_constraints,
        ).authority_fingerprint
    selected_is_stale = bool(
        selected_version
        and (
            selected_version.is_stale
            or (
                not (
                    selected_version.origin == "manual"
                    and selected_version.source_version_id is None
                    and not entry_rows
                )
                and str(selected_version.authority_fingerprint or "") != current_authority_fingerprint
            )
        )
    )
    selected_delete_eligibility = (
        timetable_version_delete_eligibility(db, version=selected_version)
        if selected_version is not None
        else {"eligible": False, "reasons": []}
    )
    validation = None
    if include_validation and selected_version and selected_version.lifecycle_status in {"draft", "publication_ready"}:
        from timetable_publication_service import TimetableDraftValidationService
        validation = TimetableDraftValidationService(db).validate(version=selected_version)
    return {
        "scope": {
            "school_name": str(getattr(db.get(models.SchoolGroup, school_group_id), "name", "") or "School") if 'school_group_id' in locals() else "School",
            "branch_name": str(getattr(branch_row, "name", "") or "Selected Branch"),
            "academic_year_name": str(getattr(year_row, "year_name", "") or "Selected Academic Year"),
        },
        "version": (
            {
                "id": selected_version.id,
                "public_id": selected_version.public_id,
                "version_number": selected_version.version_number,
                "lifecycle_status": selected_version.lifecycle_status,
                "display_status": "active" if active_version and int(active_version.id) == int(selected_version.id) else selected_version.lifecycle_status,
                "origin": selected_version.origin,
                "is_stale": selected_is_stale,
                "is_active": bool(active_version and int(active_version.id) == int(selected_version.id)),
                "is_mutable": selected_version.lifecycle_status in {"draft", "publication_ready"} and not (active_version and int(active_version.id) == int(selected_version.id)),
                "has_manual_changes": bool(selected_version.has_manual_changes),
                "manual_change_count": int(selected_version.manual_change_count or 0),
                "created_at": selected_version.created_at.isoformat() if selected_version.created_at else "",
                "published_at": selected_version.published_at.isoformat() if selected_version.published_at else "",
                "was_published": bool(selected_version.published_at),
                "is_approved": bool(selected_version.approved_at) and not selected_is_stale,
                "edit_revision": int(selected_version.edit_revision or 0),
                "can_delete": selected_delete_eligibility["eligible"],
                "delete_blockers": selected_delete_eligibility["reasons"],
                "is_logical_draft_source": is_logical_draft_source(db, selected_version),
            }
            if selected_version is not None
            else None
        ),
        "versions": version_history,
        "active_pointer_revision": active_pointer_revision,
        "validation": validation,
        "settings": {
            key: value
            for key, value in settings_payload.items()
            if key not in {"block_slot_map", "slot_projection"}
        },
        "slot_projection": public_slot_projection(settings_payload["slot_projection"]),
        "readiness": readiness,
        "working_day_keys": working_day_keys,
        "days": settings_payload["working_days"],
        "time_slots": settings_payload["time_slots"],
        "timeline_rows": settings_payload["timeline_rows"],
        "teaching_slots": settings_payload["teaching_slots"],
        "blocked_slots": [
            {
                **(slot_payload.get("block") or {}),
                "status": slot_payload.get("status"),
                "reason_code": slot_payload.get("reason_code"),
                "label": (slot_payload.get("block") or {}).get("label") or "Unavailable",
                "day_label": get_day_label(day_key),
                "period_index": period_index,
            }
            for (day_key, period_index), slot_payload in sorted(
                block_slot_map.items(),
                key=lambda item: (
                    working_day_keys.index(item[0][0]) if item[0][0] in working_day_keys else 99,
                    item[0][1],
                ),
            )
        ],
        "sections": section_payloads,
        "teachers": teacher_payloads,
        "entries": entries,
        "summary": {
            "section_count": len(section_payloads),
            "teacher_count": len(teacher_payloads),
            "required_hours": total_required_hours,
            "scheduled_hours": total_scheduled_hours,
            "remaining_hours": max(total_required_hours - total_scheduled_hours, 0),
            "blocked_slot_count": settings_payload["blocked_slot_count"],
            "teaching_slot_count": settings_payload["teaching_slot_count"],
        },
        "warnings": warnings,
    }
