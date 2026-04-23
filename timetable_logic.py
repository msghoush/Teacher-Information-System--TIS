from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import models
from homeroom_defaults import is_default_homeroom_subject
from subject_colors import build_subject_theme, resolve_subject_color
from teacher_capacity import get_teacher_international_capacity_hours


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
    {"key": "prayer", "label": "Prayer"},
    {"key": "non_teaching", "label": "Non-Teaching"},
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
) -> list[dict]:
    safe_periods = max(int(periods_per_day or 0), 0)
    safe_duration = max(int(period_duration_minutes or 0), 0)
    start_minutes = parse_time_value(school_start_time)
    if start_minutes is None:
        start_minutes = 7 * 60

    slots = []
    current_minutes = start_minutes
    for period_index in range(1, safe_periods + 1):
        end_minutes = current_minutes + safe_duration
        slots.append(
            {
                "period_index": period_index,
                "label": f"Period {period_index}",
                "short_label": f"P{period_index}",
                "start_time": format_minutes_as_time(current_minutes),
                "end_time": format_minutes_as_time(end_minutes),
                "time_range": (
                    f"{format_minutes_as_time(current_minutes)} - "
                    f"{format_minutes_as_time(end_minutes)}"
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


def serialize_timetable_block(block_row, working_day_keys) -> dict:
    block_type = normalize_block_type(getattr(block_row, "block_type", ""))
    day_key = normalize_day_key(getattr(block_row, "day_key", ""))
    expanded_day_keys = (
        list(working_day_keys)
        if day_key == ALL_DAY_KEY
        else [day_key]
    )
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
        "start_period": int(getattr(block_row, "start_period", 0) or 0),
        "end_period": int(getattr(block_row, "end_period", 0) or 0),
        "accent": theme["accent"],
        "soft": theme["soft"],
        "border": theme["border"],
        "text": theme["text"],
    }


def build_non_teaching_slot_map(
    blocks: list[dict],
    working_day_keys: list[str],
) -> dict[tuple[str, int], dict]:
    slot_map = {}
    for block in blocks:
        expanded_day_keys = block.get("expanded_day_keys") or []
        for day_key in expanded_day_keys:
            if day_key not in working_day_keys:
                continue
            for period_index in range(
                int(block.get("start_period", 0) or 0),
                int(block.get("end_period", 0) or 0) + 1,
            ):
                slot_map[(day_key, period_index)] = {
                    "id": block.get("id"),
                    "block_type": block.get("block_type", "non_teaching"),
                    "block_type_label": block.get(
                        "block_type_label",
                        "Non-Teaching",
                    ),
                    "label": block.get("label", "Blocked"),
                    "day_key": day_key,
                    "start_period": int(block.get("start_period", 0) or 0),
                    "end_period": int(block.get("end_period", 0) or 0),
                    "accent": block.get("accent", BLOCK_TYPE_THEMES["non_teaching"]["accent"]),
                    "soft": block.get("soft", BLOCK_TYPE_THEMES["non_teaching"]["soft"]),
                    "border": block.get("border", BLOCK_TYPE_THEMES["non_teaching"]["border"]),
                    "text": block.get("text", BLOCK_TYPE_THEMES["non_teaching"]["text"]),
                }
    return slot_map


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
    else:
        working_day_keys = normalize_day_keys(
            str(getattr(setting_row, "working_days_csv", "") or "").split(",")
        ) or list(defaults["working_day_keys"])
        periods_per_day = int(
            getattr(setting_row, "periods_per_day", defaults["periods_per_day"])
            or defaults["periods_per_day"]
        )
        period_duration_minutes = int(
            getattr(
                setting_row,
                "period_duration_minutes",
                defaults["period_duration_minutes"],
            )
            or defaults["period_duration_minutes"]
        )
        school_start_time = str(
            getattr(setting_row, "school_start_time", defaults["school_start_time"])
            or defaults["school_start_time"]
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
        blocks = [
            serialize_timetable_block(block_row, working_day_keys)
            for block_row in block_rows or []
        ]

    time_slots = build_time_slots(
        periods_per_day,
        period_duration_minutes,
        school_start_time,
    )
    block_slot_map = build_non_teaching_slot_map(
        blocks,
        working_day_keys,
    )
    blocked_slot_count = len(block_slot_map)
    total_slot_count = len(working_day_keys) * len(time_slots)

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
        "block_slot_map": block_slot_map,
        "blocked_slot_count": blocked_slot_count,
        "total_slot_count": total_slot_count,
        "teaching_slot_count": max(total_slot_count - blocked_slot_count, 0),
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
    if parsed_end_minutes is None:
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
        if normalized_school_end_time and computed_school_end_time != normalized_school_end_time:
            errors.append(
                "School end time must match the configured start time plus periods per day "
                f"({computed_school_end_time} based on the current values)."
            )

    return {
        "working_day_keys": normalized_working_day_keys,
        "periods_per_day": parsed_periods_per_day,
        "period_duration_minutes": parsed_period_duration,
        "school_start_time": normalized_school_start_time,
        "school_end_time": normalized_school_end_time or computed_school_end_time,
        "computed_school_end_time": computed_school_end_time,
        "errors": errors,
    }


def normalize_non_teaching_block_values(
    *,
    block_type,
    label,
    day_key,
    start_period,
    end_period,
    periods_per_day,
    working_day_keys,
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

    parsed_start_period = _parse_int(start_period)
    parsed_end_period = _parse_int(end_period)
    safe_periods_per_day = int(periods_per_day or 0)
    if (
        parsed_start_period is None
        or parsed_end_period is None
        or parsed_start_period <= 0
        or parsed_end_period <= 0
    ):
        errors.append("Block period range must use whole-number period values.")
    elif parsed_start_period > safe_periods_per_day or parsed_end_period > safe_periods_per_day:
        errors.append("Block periods must stay within the configured periods per day.")
    elif parsed_start_period > parsed_end_period:
        errors.append("Block end period must be the same as or after the start period.")

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
        "start_period": parsed_start_period,
        "end_period": parsed_end_period,
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

        left_start = int(block.get("start_period", 0) or 0)
        left_end = int(block.get("end_period", 0) or 0)
        right_start = int(candidate_block.get("start_period", 0) or 0)
        right_end = int(candidate_block.get("end_period", 0) or 0)
        if left_start <= right_end and right_start <= left_end:
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


def build_timetable_workspace_payload(db, branch_id: int, academic_year_id: int) -> dict:
    settings_payload = get_timetable_settings_payload(db, branch_id, academic_year_id)
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

    entry_rows = db.query(models.TimetableEntry).filter(
        models.TimetableEntry.branch_id == branch_id,
        models.TimetableEntry.academic_year_id == academic_year_id,
    ).order_by(
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
            default_max_hours=24,
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

    return {
        "settings": {
            key: value
            for key, value in settings_payload.items()
            if key != "block_slot_map"
        },
        "working_day_keys": working_day_keys,
        "days": settings_payload["working_days"],
        "time_slots": settings_payload["time_slots"],
        "blocked_slots": [
            {
                **slot_payload,
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
