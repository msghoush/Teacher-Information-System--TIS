import re


LOWER_PRIMARY_HOMEROOM_GRADES = {"1", "2"}
HOMEROOM_BUNDLE_SUBJECT_NAME = "Homeroom Teacher - Multiple Subjects"
HOMEROOM_BUNDLE_WEEKLY_HOURS = 22
HOMEROOM_BUNDLE_SUBJECT_LABELS = (
    "English",
    "Mathematics",
    "Mental Math",
    "Performing Arts",
    "Science",
    "Social Studies",
    "Well Being",
)
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
    "well being",
    "wellbeing",
    "well-being",
)
LOWER_PRIMARY_HOMEROOM_SUBJECT_LABELS = HOMEROOM_BUNDLE_SUBJECT_LABELS


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


def normalize_subject_code(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _parse_weekly_hours(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def is_lower_primary_homeroom_grade(grade_label) -> bool:
    return normalize_grade_label(grade_label) in LOWER_PRIMARY_HOMEROOM_GRADES


def is_homeroom_bundle_subject(
    subject_code: str = "",
    subject_name: str = "",
    weekly_hours=None,
    grade_label=None,
) -> bool:
    if grade_label is not None and not is_lower_primary_homeroom_grade(grade_label):
        return False

    normalized_code = normalize_subject_code(subject_code)
    if not normalized_code.startswith("hrt"):
        return False

    normalized_name = normalize_subject_key(subject_name)
    name_matches = (
        normalized_name == normalize_subject_key(HOMEROOM_BUNDLE_SUBJECT_NAME)
        or (
            "homeroom teacher" in normalized_name
            and "multiple subject" in normalized_name
        )
    )
    weekly_hours_matches = _parse_weekly_hours(weekly_hours) == HOMEROOM_BUNDLE_WEEKLY_HOURS
    return name_matches or weekly_hours_matches


def get_homeroom_bundle_subject_labels(
    subject_code: str = "",
    subject_name: str = "",
    weekly_hours=None,
    grade_label=None,
):
    if not is_homeroom_bundle_subject(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=weekly_hours,
        grade_label=grade_label,
    ):
        return ()
    return HOMEROOM_BUNDLE_SUBJECT_LABELS


def get_effective_subject_count(
    subject_code: str = "",
    subject_name: str = "",
    weekly_hours=None,
    grade_label=None,
) -> int:
    bundle_labels = get_homeroom_bundle_subject_labels(
        subject_code=subject_code,
        subject_name=subject_name,
        weekly_hours=weekly_hours,
        grade_label=grade_label,
    )
    return len(bundle_labels) if bundle_labels else 1


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
