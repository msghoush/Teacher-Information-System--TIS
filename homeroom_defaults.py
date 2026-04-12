import re


LOWER_PRIMARY_HOMEROOM_GRADES = {"1", "2"}
LOWER_PRIMARY_HOMEROOM_SUBJECT_PREFIXES = (
    "english",
    "mathematics",
    "math",
    "maths",
    "mental math",
    "performing arts",
    "performing art",
    "science",
    "social studies",
)
LOWER_PRIMARY_HOMEROOM_SUBJECT_LABELS = (
    "English",
    "Mathematics",
    "Mental Math",
    "Performing Arts",
    "Science",
    "Social Studies",
)


def normalize_grade_label(value) -> str:
    cleaned = str(value or "").strip().upper()
    if cleaned in {"K", "KG", "KINDERGARTEN"}:
        return "KG"
    if cleaned.startswith("GRADE "):
        cleaned = cleaned.replace("GRADE ", "", 1).strip()
    if cleaned.startswith("G") and cleaned[1:].isdigit():
        cleaned = cleaned[1:]
    try:
        parsed_value = int(cleaned)
    except (TypeError, ValueError):
        return ""
    if 1 <= parsed_value <= 12:
        return str(parsed_value)
    return ""


def normalize_subject_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def is_lower_primary_homeroom_grade(grade_label) -> bool:
    return normalize_grade_label(grade_label) in LOWER_PRIMARY_HOMEROOM_GRADES


def is_default_homeroom_subject(
    grade_label,
    subject_key: str = "",
    subject_name: str = "",
    subject_code: str = "",
) -> bool:
    if not is_lower_primary_homeroom_grade(grade_label):
        return False

    candidates = (
        normalize_subject_key(subject_key),
        normalize_subject_key(subject_name),
        normalize_subject_key(subject_code),
    )
    for candidate in candidates:
        if candidate and any(
            candidate.startswith(prefix)
            for prefix in LOWER_PRIMARY_HOMEROOM_SUBJECT_PREFIXES
        ):
            return True
    return False
