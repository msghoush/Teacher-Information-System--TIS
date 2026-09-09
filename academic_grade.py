"""Canonical academic grade normalization shared by Planning-era domains."""

GRADE_LEVELS = ("KG",) + tuple(str(value) for value in range(1, 13))


def normalize_grade_level(value) -> str:
    cleaned = str(value or "").strip().upper()
    if cleaned in {"K", "KG", "KINDERGARTEN"}:
        return "KG"
    try:
        number = int(cleaned)
    except (TypeError, ValueError):
        return ""
    return str(number) if 1 <= number <= 12 else ""
