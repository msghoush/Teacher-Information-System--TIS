STANDARD_MAX_HOURS = 24


def _safe_int(value, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def build_capacity_breakdown(
    max_hours,
    *,
    extra_hours_allowed=False,
    extra_hours_count=0,
    teaches_national_section=False,
    national_section_hours=0,
    default_max_hours=STANDARD_MAX_HOURS,
):
    safe_max_hours = _safe_int(max_hours, default_max_hours)
    if safe_max_hours <= 0:
        safe_max_hours = default_max_hours

    safe_extra_hours = (
        max(_safe_int(extra_hours_count, 0), 0)
        if extra_hours_allowed
        else 0
    )
    safe_national_section_hours = (
        max(_safe_int(national_section_hours, 0), 0)
        if teaches_national_section
        else 0
    )
    total_capacity_hours = safe_max_hours + safe_extra_hours
    international_capacity_hours = max(
        total_capacity_hours - safe_national_section_hours,
        0,
    )

    return {
        "max_hours": safe_max_hours,
        "extra_hours": safe_extra_hours,
        "total_capacity_hours": total_capacity_hours,
        "national_section_hours": safe_national_section_hours,
        "international_capacity_hours": international_capacity_hours,
    }


def get_teacher_capacity_breakdown(teacher, default_max_hours=STANDARD_MAX_HOURS):
    return build_capacity_breakdown(
        getattr(teacher, "max_hours", default_max_hours),
        extra_hours_allowed=bool(getattr(teacher, "extra_hours_allowed", False)),
        extra_hours_count=getattr(teacher, "extra_hours_count", 0),
        teaches_national_section=bool(
            getattr(teacher, "teaches_national_section", False)
        ),
        national_section_hours=getattr(teacher, "national_section_hours", 0),
        default_max_hours=default_max_hours,
    )


def get_teacher_total_capacity_hours(teacher, default_max_hours=STANDARD_MAX_HOURS):
    return get_teacher_capacity_breakdown(
        teacher,
        default_max_hours=default_max_hours,
    )["total_capacity_hours"]


def get_teacher_national_section_hours(teacher, default_max_hours=STANDARD_MAX_HOURS):
    return get_teacher_capacity_breakdown(
        teacher,
        default_max_hours=default_max_hours,
    )["national_section_hours"]


def get_teacher_international_capacity_hours(
    teacher,
    default_max_hours=STANDARD_MAX_HOURS,
):
    return get_teacher_capacity_breakdown(
        teacher,
        default_max_hours=default_max_hours,
    )["international_capacity_hours"]
