"""Source-level regression guards for the return_to + reopen-on-load pattern.

This repo has no Jinja/browser rendering harness, so these assert directly
against the template/JS source text rather than a rendered DOM - narrow, but
enough to catch the exact regression this bug report was about: something
re-closing ".subject-assignment-details" after DOMContentLoaded without
knowing about the reopen target.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_planning_section_details_has_a_stable_id():
    html = _read("templates/planning.html")
    assert 'id="planning-section-{{ record.id }}"' in html
    # the id must be on the <details> element itself, not a wrapper
    assert '<details class="subject-assignment-details" id="planning-section-{{ record.id }}">' in html


def test_remove_demand_link_passes_a_safe_return_to_matching_the_registered_route():
    html = _read("templates/planning.html")
    assert "/planning/subject-demand/delete/{{ subject.demand_id }}?return_to=" in html
    # must target the section's own route path ("/planning/", trailing slash)
    # so the redirect never takes an extra Starlette redirect_slashes hop
    # before the browser applies the #fragment.
    assert "'/planning/#planning-section-' ~ record.id" in html


def test_collapse_all_details_never_closes_the_active_reopen_target():
    html = _read("templates/planning.html")
    assert "collapseSubjectAssignmentDetails" in html
    # the guard that must exist so the later "pageshow" re-collapse (which
    # fires after DOMContentLoaded on every normal navigation, not only
    # bfcache restores) does not undo reopen-on-load.js's work
    assert "preserveId" in html
    assert 'detail.id === preserveId' in html


def test_reopen_on_load_script_is_loaded_globally_from_base_html():
    base_html = _read("templates/base.html")
    assert "js/reopen-on-load.js" in base_html
    # must be cache-busted using the existing TIS versioning convention,
    # not served without a version query string
    assert "reopen-on-load.js') }}?v=" in base_html


def test_reopen_on_load_script_resolves_hash_and_inline_target_safely():
    script = _read("static/js/reopen-on-load.js")
    assert "window.location.hash" in script
    assert "__tisReopenTargetId" in script
    assert "getElementById" in script
    assert "DETAILS" in script
