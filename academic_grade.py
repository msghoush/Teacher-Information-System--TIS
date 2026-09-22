"""Canonical academic grade normalization shared by Planning-era domains."""

GRADE_LEVELS = ("KG",) + tuple(str(value) for value in range(1, 13))

# ADR 0045: the exact, verified production SchoolGroup.workspace_uuid this
# presentation-only Grade/Section display convention is authorized for.
# Activation must key exclusively off this UUID - never a name/label.
AL_ANDALUS_SECTION_DISPLAY_WORKSPACE_UUID = "72e52eb2-3844-447b-92a8-c55015f73257"


def normalize_grade_level(value) -> str:
    cleaned = str(value or "").strip().upper()
    if cleaned in {"K", "KG", "KINDERGARTEN"}:
        return "KG"
    try:
        number = int(cleaned)
    except (TypeError, ValueError):
        return ""
    return str(number) if 1 <= number <= 12 else ""


def format_section_display(workspace_uuid, grade_level, section_name) -> str:
    """Presentation-only Grade/Section display per ADR 0045.

    Returns ``f"{grade_number}.{section_ordinal}"`` (Section A=1 ... Z=26)
    only when ``workspace_uuid`` exactly equals the ADR 0045-authorized
    workspace UUID (string/UUID equality only - never a name/label match).

    Every other workspace, and any Grade/Section that does not map
    deterministically under this rule (custom Section name, non-alphabetic
    or multi-character Section, missing/malformed Grade, missing Section),
    returns the existing canonical ``section_name`` unchanged. This never
    raises solely because a value is unavailable for formatting, and it
    never mutates or replaces any canonical value - the caller remains
    responsible for keeping canonical ``grade_level``/``section_name``
    separately intact.
    """
    fallback = str(section_name or "").strip()
    if str(workspace_uuid or "").strip() != AL_ANDALUS_SECTION_DISPLAY_WORKSPACE_UUID:
        return fallback
    grade_number = normalize_grade_level(grade_level)
    if not grade_number or grade_number == "KG":
        return fallback
    section = fallback
    if len(section) != 1 or not section.isalpha():
        return fallback
    ordinal = ord(section.upper()) - ord("A") + 1
    if not (1 <= ordinal <= 26):
        return fallback
    return f"{int(grade_number)}.{ordinal}"
