"""ADR 0045: Al-Andalus Section display presentation-only formatting.

Pure unit coverage for ``academic_grade.format_section_display`` - the single
shared, authoritative, server-side presentation helper. No database, no
tenant plumbing here; integration wiring (workspace_uuid lookup, canonical
value preservation across Student/Talent surfaces) is covered separately in
``tests/test_al_andalus_section_display.py``.
"""

from academic_grade import AL_ANDALUS_SECTION_DISPLAY_WORKSPACE_UUID, format_section_display

UUID = AL_ANDALUS_SECTION_DISPLAY_WORKSPACE_UUID
OTHER_UUID = "00000000-0000-0000-0000-000000000000"


def test_exact_uuid_activates_numeric_mapping():
    assert format_section_display(UUID, "1", "A") == "1.1"
    assert format_section_display(UUID, "1", "B") == "1.2"
    assert format_section_display(UUID, "2", "A") == "2.1"


def test_wrong_uuid_falls_back_to_canonical_section_name():
    assert format_section_display(OTHER_UUID, "1", "A") == "A"


def test_missing_or_none_uuid_falls_back():
    assert format_section_display(None, "1", "A") == "A"
    assert format_section_display("", "1", "A") == "A"


def test_ordinal_mapping_is_deterministic_a_to_z():
    for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ", start=1):
        assert format_section_display(UUID, "7", letter) == f"7.{index}"
    assert format_section_display(UUID, "1", "Z") == "1.26"


def test_ordinal_mapping_is_case_insensitive():
    assert format_section_display(UUID, "1", "a") == "1.1"
    assert format_section_display(UUID, "3", "z") == "3.26"


def test_grade_value_formats_are_parsed_like_canonical_placement_values():
    # Canonical StudentAcademicPlacement/frozen Talent grade_level values are
    # already constrained to bare "1".."12"/"KG" - confirm those parse.
    assert format_section_display(UUID, "12", "A") == "12.1"
    assert format_section_display(UUID, " 1 ", "A") == "1.1"


def test_fallback_custom_section_name():
    assert format_section_display(UUID, "1", "Falcons") == "Falcons"


def test_fallback_multi_character_section():
    assert format_section_display(UUID, "1", "AB") == "AB"


def test_fallback_non_alphabetic_section():
    assert format_section_display(UUID, "1", "1") == "1"
    assert format_section_display(UUID, "1", "A1") == "A1"


def test_fallback_missing_section():
    assert format_section_display(UUID, "1", "") == ""
    assert format_section_display(UUID, "1", None) == ""


def test_fallback_missing_or_malformed_grade():
    assert format_section_display(UUID, "", "A") == "A"
    assert format_section_display(UUID, None, "A") == "A"
    assert format_section_display(UUID, "Not a grade", "A") == "A"
    assert format_section_display(UUID, "13", "A") == "A"
    assert format_section_display(UUID, "0", "A") == "A"


def test_fallback_kindergarten_never_maps_numerically():
    assert format_section_display(UUID, "KG", "A") == "A"


def test_never_raises_for_any_combination_of_missing_context():
    assert format_section_display(None, None, None) == ""
    assert format_section_display(UUID, None, None) == ""
