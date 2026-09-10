"""Canonical Students UI presentation smoke tests against isolated SQLite."""

import inspect
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

import models
from auth import get_current_user
from dependencies import get_db
from routers import students_ui
from test_talent_org_intelligence_queries import actor, db, permissions


@pytest.fixture
def client(db):
    db.add_all([
        models.Student(id=1001, school_group_id=1, first_name="Alya", last_name="Learner", status="active"),
        models.Student(id=1002, school_group_id=1, first_name="Bilal", last_name="Student", status="inactive"),
        models.Student(id=2001, school_group_id=2, first_name="Foreign", last_name="Learner", status="active"),
    ])
    db.commit()
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    return TestClient(app)


def test_list_requires_students_view(db, client):
    assert client.get("/students/").status_code == 403
    permissions(db, "students.view")
    response = client.get("/students/")
    assert response.status_code == 200
    assert "Students" in response.text
    assert "Alya" in response.text


def test_new_student_workflow(db, client):
    permissions(db, "students.view", "students.create")
    assert client.get("/students/new").status_code == 200
    before = db.query(models.Student).filter_by(school_group_id=1).count()
    response = client.post("/students/new", data={
        "first_name": "Carla", "last_name": "New", "father_name": "", "gender": "Female",
    })
    # TestClient follows the post-login redirect; the student creation is what matters.
    assert response.status_code in (200, 302)
    after = db.query(models.Student).filter_by(school_group_id=1).count()
    assert after == before + 1
    created = db.query(models.Student).filter_by(school_group_id=1, first_name="Carla").one()
    assert created.last_name == "New"
    assert created.status == "active"


def test_profile_sections_render(db, client):
    permissions(db, "students.view", "talent_learner_profiles.view",
                "talent_review_candidates.view", "talent_official_identifications.view")
    for section in ("overview", "placement", "history"):
        response = client.get(f"/students/1001?section={section}")
        assert response.status_code == 200
    talent = client.get("/students/1001?section=talent")
    assert talent.status_code == 200
    assert "Talent" in talent.text


def test_foreign_student_is_not_found(db, client):
    permissions(db, "students.view")
    assert client.get("/students/2001").status_code == 404


def test_history_tab_uses_canonical_audit_service_and_shows_actor(db, client):
    permissions(db, "students.view")
    # actor() (the request identity used by this fixture's dependency override) defaults
    # to school_group_id=1, branch_id=10, which resolves to user_id "u110".
    db.add(models.User(
        user_id="u110", username="u110", first_name="Nadia", last_name="Haddad",
        role="Editor", user_type="TENANT", access_scope="ORGANIZATION",
        school_group_id=1, branch_id=10, academic_year_id=100, is_active=True,
    ))
    db.add_all([
        models.StudentAudit(
            school_group_id=1, student_id=1001, actor_user_id="u110", actor_branch_id=10,
            resource_type="student", resource_id=1001, action="updated",
            created_at=datetime(2026, 1, 5, 9, 30),
        ),
        models.StudentAudit(
            school_group_id=1, student_id=1001, actor_user_id=None, actor_branch_id=None,
            resource_type="student", resource_id=1001, action="created",
            created_at=datetime(2026, 1, 1, 8, 0),
        ),
    ])
    db.commit()

    response = client.get("/students/1001?section=history")
    assert response.status_code == 200
    # (a) real audit rows sourced from the canonical service are rendered.
    assert "Updated" in response.text and "Created" in response.text
    # (b) a resolvable actor's human-readable display name is rendered.
    assert "Nadia Haddad" in response.text
    # No-actor event falls back to a neutral label, never a raw id/blank.
    assert "System" in response.text
    assert "u110" not in response.text

    # (c) foreign-tenant Student History access remains blocked, non-enumerating.
    assert client.get("/students/2001?section=history").status_code == 404

    # (d) the duplicate raw StudentAudit query is gone; the canonical service is used.
    source = inspect.getsource(students_ui)
    assert "db.query(models.StudentAudit" not in source
    assert "list_audit_events(" in source
    assert "audit_event_payload(" in source


def test_create_placement(db, client):
    permissions(db, "students.view", "students.manage_placements")
    response = client.post("/students/1002/placements", data={
        "academic_year_id": "100", "branch_id": "11", "grade_level": "2",
        "section_name": "B", "effective_from": "2026-09-01", "effective_to": "", "reason": "Test",
    })
    assert response.status_code in (200, 302)
    placements = db.query(models.StudentAcademicPlacement).filter_by(student_id=1002, school_group_id=1).all()
    assert len(placements) == 1
    assert placements[0].branch_id == 11
    assert placements[0].grade_level == "2"


def test_list_is_a_compact_table_with_mobile_only_cards(db, client):
    permissions(db, "students.view")
    response = client.get("/students/")
    assert response.status_code == 200
    text = response.text
    # Real <table> structure with the required columns, not a card-only layout.
    assert "stu-list-table" in text and "stu-list-cards" in text
    for column in ("Student", "Grade", "Section", "Branch", "Learning Style", "Status", "Actions"):
        assert column in text
    css = Path("static/css/students.css").read_text(encoding="utf-8")
    assert ".stu-list-table { display: block; }" in css
    assert ".stu-list-cards { display: none !important; }" in css
    assert "@media (max-width: 680px)" in css
    assert ".stu-list-table { display: none; }" in css
    assert ".stu-list-cards { display: grid !important; }" in css


def test_list_shows_persisted_learning_style_and_neutral_unset_on_desktop_and_mobile(db, client):
    permissions(db, "students.view", "students.edit")
    saved = db.get(models.Student, 1001)
    saved.learning_style = "Read/Write"
    db.commit()

    response = client.get("/students/")
    assert response.status_code == 200
    assert response.text.count("Read/Write") >= 2  # desktop row and mobile card
    assert response.text.count("Not specified") >= 2
    assert "Talent score" not in response.text
    assert "Talent status" not in response.text

    # Persist through the real edit route, reload the list, then clear through
    # the same route and verify the neutral fallback.
    edited = client.post("/students/1001/edit", data={
        "first_name": "Alya", "last_name": "Learner", "father_name": "",
        "gender": "", "learning_style": "Kinesthetic",
    })
    assert edited.status_code in (200, 302)
    assert db.get(models.Student, 1001).learning_style == "Kinesthetic"
    assert "Kinesthetic" in client.get("/students/").text
    cleared = client.post("/students/1001/edit", data={
        "first_name": "Alya", "last_name": "Learner", "father_name": "",
        "gender": "", "learning_style": "",
    })
    assert cleared.status_code in (200, 302)
    assert db.get(models.Student, 1001).learning_style is None
    profile = client.get("/students/1001?section=overview")
    assert 'value="" checked' in profile.text
    assert "Not specified" in client.get("/students/").text


def test_current_placement_uses_change_flow_instead_of_overlapping_add_form(db, client):
    permissions(db, "students.view", "students.manage_placements")
    db.query(models.StudentAcademicPlacement).filter_by(student_id=1001, school_group_id=1).delete()
    db.add(models.StudentAcademicPlacement(
        id=777, school_group_id=1, student_id=1001, academic_year_id=100,
        branch_id=10, grade_level="1", section_name="A",
        effective_from=datetime(2026, 9, 1), status="active",
    ))
    db.commit()
    response = client.get("/students/1001?section=placement")
    assert response.status_code == 200
    assert "already has a current placement" in response.text
    assert "End / Change" in response.text
    assert "Save Placement" not in response.text


def test_change_placement_preserves_history_and_reload_shows_new_current(db, client):
    permissions(db, "students.view", "students.manage_placements")
    db.query(models.StudentAcademicPlacement).filter_by(student_id=1001, school_group_id=1).delete()
    old = models.StudentAcademicPlacement(
        id=778, school_group_id=1, student_id=1001, academic_year_id=100,
        branch_id=10, grade_level="1", section_name="A",
        effective_from=datetime(2026, 9, 1), status="active",
    )
    db.add(old)
    db.add(models.PlanningSection(
        id=9010, grade_level="3", section_name="C", class_status="Current",
        branch_id=10, academic_year_id=100,
    ))
    db.commit()

    response = client.post("/students/1001/placements/778/transition", data={
        "academic_year_id": "100", "branch_id": "10", "planning_section_id": "9010",
        "transition_at": "2027-01-01", "reason": "Academic move",
    })
    assert response.status_code in (200, 302)
    rows = db.query(models.StudentAcademicPlacement).filter_by(
        student_id=1001, school_group_id=1
    ).order_by(models.StudentAcademicPlacement.effective_from).all()
    assert len(rows) == 2
    assert rows[0].effective_to == datetime(2027, 1, 1)
    assert rows[0].status == "ended"
    assert (rows[1].planning_section_id, rows[1].grade_level, rows[1].section_name) == (9010, "3", "C")
    assert rows[1].effective_to is None and rows[1].status == "active"
    reloaded = client.get("/students/1001?section=placement")
    assert reloaded.status_code == 200
    assert "Grade 3" in reloaded.text and "Academic move" in reloaded.text


def test_placement_form_has_validation_pending_and_network_error_feedback():
    source = Path("static/js/students.js").read_text(encoding="utf-8")
    assert 'form.addEventListener("submit"' in source
    assert 'submitButton.setAttribute("aria-busy", "true")' in source
    assert 'submitButton.textContent = "Saving placement…"' in source
    assert "Choose a configured Section before saving." in source
    assert "Sections could not be loaded. Check your connection" in source


def test_active_status_is_deemphasized_but_inactive_stays_a_visible_exception(db, client):
    """Active is the normal, expected state for an attending Student (lifecycle
    status, not Talent status). It must not be badged like an exception on every
    row. Inactive - a real exception - keeps its visible chip. Status stays
    available as a filter/column either way."""
    permissions(db, "students.view")
    response = client.get("/students/")
    assert response.status_code == 200
    text = response.text
    assert '<span class="stu-status-quiet"><span class="stu-visually-hidden">Active</span>—</span>' in text
    assert '<span class="stu-chip stu-chip-inactive">Inactive</span>' in text
    assert "stu-chip-active" not in text
    # Status remains a real filter/column, not removed.
    assert 'aria-label="Status filter"' in text
    assert "Status" in text


def test_placement_grade_selector_excludes_kg(db, client):
    permissions(db, "students.view", "students.manage_placements")
    response = client.get("/students/1001?section=placement")
    assert response.status_code == 200
    text = response.text
    assert 'value="KG"' not in text
    assert 'value="1"' not in text and 'value="12"' not in text
    assert "Select academic year and branch first" in text


def test_sections_endpoint_reuses_planning_scope_authority_and_disabled_state(db, client):
    permissions(db, "students.view", "students.manage_placements")
    db.add(models.PlanningSection(
        id=9001, grade_level="1", section_name="A", class_status="current",
        branch_id=10, academic_year_id=100,
    ))
    db.commit()

    configured = client.get("/students/sections", params={"branch_id": 10, "academic_year_id": 100, "grade_level": "1"})
    assert configured.status_code == 200
    assert configured.json() == {"items": [{"id": 9001, "section_name": "A"}]}

    configured_grades = client.get("/students/sections", params={"branch_id": 10, "academic_year_id": 100})
    assert configured_grades.status_code == 200
    assert configured_grades.json() == {"grades": ["1"]}

    # No PlanningSection exists for Grade 2 at this Branch/Year - the real
    # "no Sections configured" signal the UI renders as disabled+explanation.
    unconfigured = client.get("/students/sections", params={"branch_id": 10, "academic_year_id": 100, "grade_level": "2"})
    assert unconfigured.status_code == 200
    assert unconfigured.json() == {"items": []}

    # Foreign-branch access remains blocked, not enumerable.
    foreign = client.get("/students/sections", params={"branch_id": 20, "academic_year_id": 200, "grade_level": "1"})
    assert foreign.status_code == 403


def test_sections_endpoint_requires_manage_placements_permission(db, client):
    permissions(db, "students.view")
    response = client.get("/students/sections", params={"branch_id": 10, "academic_year_id": 100, "grade_level": "1"})
    assert response.status_code == 403


def test_create_placement_with_configured_planning_section_id(db, client):
    permissions(db, "students.view", "students.manage_placements")
    db.add(models.PlanningSection(
        id=9002, grade_level="3", section_name="C", class_status="current",
        branch_id=10, academic_year_id=100,
    ))
    db.commit()

    response = client.post("/students/1002/placements", data={
        "academic_year_id": "100", "branch_id": "10", "planning_section_id": "9002",
        "effective_from": "2026-09-01", "effective_to": "", "reason": "",
    })
    assert response.status_code in (200, 302)
    placement = db.query(models.StudentAcademicPlacement).filter_by(student_id=1002, school_group_id=1).one()
    assert placement.planning_section_id == 9002
    assert placement.grade_level == "3"
    assert placement.section_name == "C"

    # The redirect reload shows the exact persisted canonical placement.
    reloaded = client.get("/students/1002?section=placement")
    assert reloaded.status_code == 200
    assert "Grade 3" in reloaded.text and "C" in reloaded.text


def test_placement_cascade_loads_grades_from_the_same_planning_endpoint():
    source = Path("static/js/students.js").read_text(encoding="utf-8")
    assert "const refreshGrades = async () =>" in source
    assert "payload.grades || []" in source
    assert 'gradeSelect.addEventListener("change", refreshSections)' in source
    assert "Loading configured Grades…" in source
    assert 'submitButton.textContent = "Saving placement…"' in source


def test_list_filters_branch_grade_section_use_real_current_placement_query(db, client):
    permissions(db, "students.view")
    db.add(models.StudentAcademicPlacement(
        id=501, school_group_id=1, student_id=1002, academic_year_id=100,
        branch_id=11, grade_level="4", section_name="Z",
        effective_from=datetime(2026, 1, 1), status="active",
    ))
    # The Section filter's dropdown only ever offers real, configured Planning
    # Section names (never a fabricated/free-typed option); back this "Z" value
    # with a real PlanningSection row so it is a valid, selectable filter value.
    db.add(models.PlanningSection(
        id=9003, grade_level="4", section_name="Z", class_status="current",
        branch_id=11, academic_year_id=100,
    ))
    db.commit()

    by_branch = client.get("/students/", params={"branch_id": 11})
    assert by_branch.status_code == 200
    assert "Bilal" in by_branch.text and "Alya" not in by_branch.text

    by_grade = client.get("/students/", params={"grade": "4"})
    assert "Bilal" in by_grade.text and "Alya" not in by_grade.text

    by_section = client.get("/students/", params={"section": "Z"})
    assert "Bilal" in by_section.text and "Alya" not in by_section.text

    # An out-of-scope/foreign branch id is silently ignored (never trusted as a filter).
    foreign_branch = client.get("/students/", params={"branch_id": 20})
    assert "Bilal" in foreign_branch.text and "Alya" in foreign_branch.text


def test_learning_style_filter_cascade_uses_planning_branch_grade_section(db, client):
    permissions(db, "students.view")
    db.add_all([
        models.PlanningSection(id=9101, grade_level="4", section_name="North A", class_status="Current", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=9102, grade_level="7", section_name="South B", class_status="Current", branch_id=11, academic_year_id=100),
    ])
    db.commit()
    organization = client.get("/students/")
    assert organization.status_code == 200
    assert 'aria-label="Organization scope">Organization' in organization.text
    assert 'value="4"' in organization.text and 'value="7"' in organization.text
    north = client.get("/students/", params={"branch_id": 10})
    assert 'value="4"' in north.text and 'value="7"' not in north.text
    north_grade = client.get("/students/", params={"branch_id": 10, "grade": "4"})
    assert "North A" in north_grade.text and "South B" not in north_grade.text
    assert "data-ls-filter-cascade" in north_grade.text
