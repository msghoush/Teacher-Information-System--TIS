import re
from pathlib import Path


SCRIPT_PATH = Path("static/js/compact-descriptions.js")
TEACHERS_TEMPLATE_PATH = Path("templates/teachers.html")
BASE_TEMPLATE_PATH = Path("templates/base.html")


def test_generic_text_and_note_classes_do_not_implicitly_opt_in():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    stripped_lines = {line.strip() for line in source.splitlines()}

    assert '"[data-compact-description]",' in stripped_lines
    assert '"p",' not in stripped_lines
    assert '"small",' not in stripped_lines
    assert '"[class*=\'description\']",' not in stripped_lines
    assert '"[class*=\'subtitle\']",' not in stripped_lines
    assert '"[class*=\'-note\']",' not in stripped_lines
    assert '"[class*=\'-lede\']",' not in stripped_lines
    assert "DESCRIPTION_CLASS_PATTERN" not in source
    assert "COMPONENT_CLASS_PATTERN" not in source


def test_teachers_operational_status_text_remains_inline():
    template = TEACHERS_TEMPLATE_PATH.read_text(encoding="utf-8")
    status_fragments = (
        "No homeroom coverage assigned.",
        "Formal observations: {{ observation_counts.formal }} / {{ observation_counts.target or 6 }}",
        'Extra hours: {{ extra_hours }}h {{ "enabled" if teacher.extra_hours_allowed else "disabled" }}',
    )

    for fragment in status_fragments:
        match = re.search(
            rf"<span(?P<attributes>[^>]*)>{re.escape(fragment)}</span>",
            template,
        )
        assert match, fragment
        assert 'class="hours-status-note"' in match.group("attributes")
        assert "data-compact-description" not in match.group("attributes")


def test_explicit_compact_description_and_keyboard_behavior_remain_supported():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'element.hasAttribute("data-compact-description")' in source
    assert 'description.setAttribute("data-compact-description", "true")' in source
    assert 'tooltip.setAttribute("role", "tooltip")' in source
    assert 'surface.addEventListener("focusin"' in source
    assert 'surface.addEventListener("focusout"' in source
    assert 'if (event.key === "Escape")' in source


def test_shared_script_reference_uses_current_cache_version():
    template = BASE_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "js/compact-descriptions.js') }}?v=20260819a" in template


def test_teacher_edit_delete_accessible_names_and_native_titles_remain_intact():
    template = TEACHERS_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert (
        'aria-label="Edit teacher {{ teacher.first_name }} {{ teacher.last_name }}" '
        'title="Edit teacher"'
    ) in template
    assert (
        'aria-label="Delete teacher {{ teacher.first_name }} {{ teacher.last_name }}" '
        'title="Delete teacher"'
    ) in template
    assert (
        'class="teacher-load-segment"' in template
        and 'title="{{ item.subject_code }} {{ item.hours }}h"' in template
    )
