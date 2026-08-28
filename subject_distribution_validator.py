"""Pure arithmetic and feasibility validation for one resolved Subject
Distribution Rule. Planning's weekly requirement remains authoritative; this
validator only checks that a configured distribution can express it and that
placement preferences are internally feasible. No database or solver access.
"""
from __future__ import annotations

SUPPORTED_BLOCK_LENGTHS = (2,)


def _error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def validate_subject_distribution_rule(
    rule: dict,
    *,
    planning_weekly_periods: int | None = None,
    available_teaching_days: int | None = None,
) -> list[dict]:
    """Return a list of validation errors; an empty list means the rule is valid."""
    errors: list[dict] = []
    block_length = rule.get("block_length")
    block_count = rule.get("block_count")
    single_count = rule.get("single_count")
    min_teaching_days = rule.get("min_teaching_days")
    max_periods_per_day = rule.get("max_periods_per_day")
    min_day_gap = rule.get("min_day_gap")

    for field_name, value in (
        ("block_length", block_length),
        ("block_count", block_count),
        ("single_count", single_count),
        ("min_teaching_days", min_teaching_days),
        ("min_day_gap", min_day_gap),
    ):
        if value is not None and int(value) < 0:
            errors.append(_error("negative_value", f"{field_name} cannot be negative."))

    if max_periods_per_day is not None and int(max_periods_per_day) <= 0:
        errors.append(_error(
            "invalid_max_periods_per_day",
            "max_periods_per_day must be a positive number when configured.",
        ))

    if block_count and int(block_count) > 0 and int(block_length or 0) not in SUPPORTED_BLOCK_LENGTHS:
        errors.append(_error(
            "unsupported_block_length",
            f"Only block lengths {SUPPORTED_BLOCK_LENGTHS} are currently supported.",
        ))

    if planning_weekly_periods is not None:
        total = int(block_count or 0) * int(block_length or 0) + int(single_count or 0)
        if total != int(planning_weekly_periods):
            errors.append(_error(
                "distribution_total_mismatch",
                f"Configured distribution totals {total} periods but Planning requires "
                f"{int(planning_weekly_periods)}.",
            ))

    if available_teaching_days is not None:
        if min_teaching_days is not None and int(min_teaching_days) > int(available_teaching_days):
            errors.append(_error(
                "min_teaching_days_exceeds_available",
                "min_teaching_days exceeds the available teaching days.",
            ))
        if max_periods_per_day is not None and planning_weekly_periods is not None:
            capacity = int(max_periods_per_day) * int(available_teaching_days)
            if int(planning_weekly_periods) > capacity:
                errors.append(_error(
                    "max_periods_per_day_infeasible",
                    "Weekly demand exceeds the configured maximum periods per day across "
                    "available teaching days.",
                ))

    return errors


def is_valid_subject_distribution_rule(
    rule: dict,
    *,
    planning_weekly_periods: int | None = None,
    available_teaching_days: int | None = None,
) -> bool:
    return not validate_subject_distribution_rule(
        rule,
        planning_weekly_periods=planning_weekly_periods,
        available_teaching_days=available_teaching_days,
    )
