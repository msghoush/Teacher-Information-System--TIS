"""Student Learning Style V1 (ADR 0031, amended by M14) focused regression
coverage.

Learning Style is Student-domain learner-profile context, optional and
single-select, with exactly eight approved values as of the M14 owner
correction (extended from the original four - Visual, Auditory, Read/Write,
Kinesthetic - by adding Verbal, Non-verbal, Quantitative, Spatial, which
were previously, mistakenly, modeled as an independent four-dimension
percentage profile under ADR 0042). It must have zero effect on Talent
scoring/eligibility/Official Identification and must reuse the existing
`students.edit` permission and the existing Talent privacy/suppression
contract for aggregate distribution - never a new/weaker rule. Aggregate
distribution "percentage" means population/aggregate share, never a
per-Student dimension percentage; the eighth bucket for Students with no
value assigned is labeled "Unassigned" and is always part of the
denominator.

Deployment Acceptance Correction C amendment: the aggregate distribution is
authorized Student-domain aggregation and is NO LONGER subject to the Talent
small-cell/complementary suppression pipeline (the suppression tests that
used to live here were deliberately replaced; the full new distribution
coverage is in test_student_learning_style_distribution_acceptance_c.py).
"""

import pathlib
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.students import router as students_router
from datetime import datetime

from student_academic_service import (
    create_placement,
    LEARNING_STYLES,
    StudentAcademicError,
    create_student,
    get_student,
    update_student,
)
from student_learning_style_analytics import build_distribution, raw_learning_style_counts
from test_talent_org_intelligence_queries import actor, db, permissions


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    db.commit()
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
    ])
    db.commit()
    yield engine, db
    db.close()


def _student(db, group=1, first="Maya", learning_style=None):
    row = create_student(
        db, school_group_id=group, first_name=first, father_name="Samir", last_name="Haddad",
        gender="female", learning_style=learning_style,
    )
    db.commit()
    return row


def _place_all(db, ids):
    # The Students page is Branch-scoped by default, so the fixture Students need a current placement.
    for student_id in ids:
        create_placement(db, school_group_id=1, student_id=student_id, academic_year_id=100, branch_id=10,
                         grade_level="1", section_name="A", effective_from=datetime(2026, 9, 1))
    db.commit()


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def test_migration_is_registered_additive_and_idempotent():
    # Simulate an already-migrated pre-ADR-0031 ``students`` table (no
    # ``learning_style`` column) exactly as an existing deployed database
    # would have it, rather than a fresh ``create_all`` (which would already
    # include the column via the current model metadata and so could not
    # actually exercise this migration's ALTER TABLE ADD COLUMN path).
    from sqlalchemy import text

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE students (id INTEGER PRIMARY KEY, school_group_id INTEGER NOT NULL, "
            "first_name VARCHAR(100) NOT NULL, father_name VARCHAR(100), last_name VARCHAR(100) NOT NULL, "
            "gender VARCHAR(24), status VARCHAR(16) NOT NULL DEFAULT 'active', "
            "created_at DATETIME, updated_at DATETIME, created_by_user_id VARCHAR(10), updated_by_user_id VARCHAR(10))"
        ))
    assert "learning_style" not in {c["name"] for c in inspect(engine).get_columns("students")}
    with engine.begin() as connection:
        db_migrations._student_learning_style_v1(engine, connection)
        db_migrations._student_learning_style_v1(engine, connection)  # idempotent
    columns = {c["name"]: c for c in inspect(engine).get_columns("students")}
    assert "learning_style" in columns
    assert columns["learning_style"]["nullable"] is True
    assert any(m.migration_id == "20260910_002_student_learning_style_v1" for m in db_migrations.MIGRATIONS)
    # Purely additive: only one net-new column, no table rebuild/rename.
    assert {"id", "school_group_id", "first_name", "last_name", "status", "learning_style"}.issubset(columns)


def test_eight_value_migration_is_registered_no_op_when_table_missing_and_matches_service_values():
    """M14: the widened CHECK constraint migration is registered, is a safe
    no-op against a missing ``students`` table (SQLite has no ALTER-time
    inspection to exercise on this dialect; PostgreSQL coverage of the
    actual DROP/ADD/VALIDATE sequence lives in
    ``tests/test_postgresql_migration_transactions.py`` against a real
    server), and its approved value set matches the service-layer
    authoritative ``LEARNING_STYLES`` exactly."""
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        # Must not raise even though "students" does not exist yet.
        db_migrations._student_learning_style_eight_values(engine, connection)
        db_migrations._student_learning_style_eight_values(engine, connection)  # idempotent
    assert any(
        m.migration_id == "20260923_002_student_learning_style_eight_values"
        for m in db_migrations.MIGRATIONS
    )
    assert LEARNING_STYLES == (
        "Visual", "Auditory", "Read/Write", "Kinesthetic",
        "Verbal", "Non-verbal", "Quantitative", "Spatial",
    )


# ---------------------------------------------------------------------------
# Service-layer validation
# ---------------------------------------------------------------------------

def test_nullable_and_all_eight_valid_values_are_accepted_on_create(database):
    _, db = database
    assert len(LEARNING_STYLES) == 8
    assert _student(db, first="A").learning_style is None
    for style in LEARNING_STYLES:
        row = _student(db, first=f"Student-{style}", learning_style=style)
        assert row.learning_style == style


def test_invalid_value_is_rejected_on_create_and_update(database):
    _, db = database
    with pytest.raises(StudentAcademicError, match="Visual, Auditory"):
        _student(db, learning_style="Kinesthetic-ish")
    student = _student(db)
    with pytest.raises(StudentAcademicError):
        update_student(db, school_group_id=1, student_id=student.id, learning_style="visual")  # case-sensitive, not the canonical value
    db.rollback()


def test_edit_sets_and_clears_learning_style(database):
    _, db = database
    student = _student(db, learning_style="Visual")
    assert student.learning_style == "Visual"
    update_student(db, school_group_id=1, student_id=student.id, learning_style="Kinesthetic")
    db.commit()
    assert get_student(db, 1, student.id).learning_style == "Kinesthetic"
    update_student(db, school_group_id=1, student_id=student.id, learning_style="")
    db.commit()
    assert get_student(db, 1, student.id).learning_style is None


def test_learning_style_is_tenant_scoped_like_every_other_student_field(database):
    _, db = database
    one = _student(db, 1, "One", learning_style="Auditory")
    two = _student(db, 2, "Two", learning_style="Read/Write")
    assert get_student(db, 1, one.id).learning_style == "Auditory"
    assert get_student(db, 2, one.id) is None
    assert get_student(db, 2, two.id).learning_style == "Read/Write"


# ---------------------------------------------------------------------------
# API layer (server-side validation is enforced regardless of UI restriction)
# ---------------------------------------------------------------------------

def _admin_client(db, scope="BRANCH"):
    user = models.User(
        user_id="1000000001", username="student.admin", first_name="Admin", last_name="One",
        role="Administrator", user_type="TENANT", access_scope=scope, school_group_id=1,
        branch_id=10, academic_year_id=None, is_active=True,
    )
    db.add(user)
    db.commit()
    user.scope_school_group_id = 1
    user.scope_branch_id = 10
    app = FastAPI()
    app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_api_accepts_the_four_values_and_rejects_any_other_value(database):
    _, db = database
    client = _admin_client(db)
    created = client.post("/api/students", json={
        "first_name": "Lina", "last_name": "Saleh", "learning_style": "Visual", "student_number": "0000000401",
    })
    assert created.status_code == 201
    assert created.json()["learning_style"] == "Visual"
    student_id = created.json()["id"]

    rejected = client.post("/api/students", json={
        "first_name": "Bad", "last_name": "Value", "learning_style": "Telepathic", "student_number": "0000000402",
    })
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "invalid_learning_style"

    updated = client.patch(f"/api/students/{student_id}", json={"learning_style": "Kinesthetic"})
    assert updated.status_code == 200
    assert updated.json()["learning_style"] == "Kinesthetic"

    rejected_update = client.patch(f"/api/students/{student_id}", json={"learning_style": "<script>alert(1)</script>"})
    assert rejected_update.status_code == 400
    assert rejected_update.json()["code"] == "invalid_learning_style"

    cleared = client.patch(f"/api/students/{student_id}", json={"learning_style": ""})
    assert cleared.status_code == 200
    assert cleared.json()["learning_style"] is None


def test_editing_learning_style_reuses_students_edit_permission_not_a_new_one(database):
    # Mirrors the existing Editor-denied pattern for other students.* fields:
    # no new permission key is introduced for Learning Style.
    _, db = database
    editor = models.User(
        user_id="1000000002", username="editor.one", first_name="Editor", last_name="One",
        role="Editor", user_type="TENANT", access_scope="BRANCH", school_group_id=1,
        branch_id=10, academic_year_id=None, is_active=True,
    )
    db.add(editor)
    db.commit()
    editor.scope_school_group_id = 1
    editor.scope_branch_id = 10
    student = _student(db)
    app = FastAPI()
    app.include_router(students_router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: editor
    with TestClient(app) as client:
        denied = client.patch(f"/api/students/{student.id}", json={"learning_style": "Visual"})
        assert denied.status_code == 403


def test_api_distribution_route_returns_visible_authorized_counts(database):
    # Org-scoped actor: the distribution population is "current effective
    # placement" scoped only when a Branch/Grade/Section filter narrows it;
    # with none given here, an org-wide actor sees every active Student in
    # the SchoolGroup (mirrors list_students' own no-filter behavior), so
    # these placement-less test fixtures still count.
    _, db = database
    for style in ("Visual", "Visual", "Auditory", None):
        _student(db, first=f"S-{style}-{id(object())}", learning_style=style)
    client = _admin_client(db, scope="ORGANIZATION")
    response = client.get("/api/students/analytics/learning-style-distribution")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "visible"
    by_label = {level["label"]: level for level in payload["levels"]}
    assert by_label["Visual"]["count"] == 2
    assert by_label["Unassigned"]["count"] == 1


def test_api_distribution_route_needs_no_privacy_policy_and_never_suppresses_a_small_cohort(database):
    # Acceptance C: authorized Student-domain aggregation, not Talent scoring
    # output - a tiny cohort still returns real authorized counts.
    _, db = database
    _student(db, first="Solo", learning_style="Visual")
    client = _admin_client(db, scope="ORGANIZATION")
    response = client.get("/api/students/analytics/learning-style-distribution")
    assert response.status_code == 200
    by_label = {level["label"]: level for level in response.json()["levels"]}
    assert by_label["Visual"]["count"] == 1 and by_label["Visual"]["percentage"] == 100.0
    assert by_label["Spatial"]["count"] == 0 and by_label["Spatial"]["state"] == "visible"


def test_new_student_form_shows_the_eight_value_categorical_selector_m14(db):
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.create")
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/new")
    assert response.status_code == 200
    html = response.text
    assert 'class="stu-ls-options" role="radiogroup"' in html
    for field in (
        "learning_style_verbal_percentage", "learning_style_non_verbal_percentage",
        "learning_style_quantitative_percentage", "learning_style_spatial_percentage",
    ):
        assert f'name="{field}"' not in html
    for style in LEARNING_STYLES:
        assert f'value="{style}"' in html


def test_edit_details_form_uses_the_categorical_selector_with_current_value_selected(db):
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view", "students.edit")
    db.add(models.Student(
        id=6001, school_group_id=1, first_name="Rana", last_name="Three",
        status="active", learning_style="Kinesthetic",
    ))
    db.commit()
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/6001?section=overview")
    assert response.status_code == 200
    html = response.text
    assert 'name="learning_style_verbal_percentage"' not in html
    for field in (
        "learning_style_verbal_percentage", "learning_style_non_verbal_percentage",
        "learning_style_quantitative_percentage", "learning_style_spatial_percentage",
    ):
        assert field not in html
    assert html.count("Kinesthetic") >= 2  # Overview display chip + edit-form selected radio
    assert '<input type="radio" name="learning_style" value="Kinesthetic" checked>' in html


def test_edit_details_form_shows_not_assigned_when_learning_style_is_null(db):
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view", "students.edit")
    db.add(models.Student(
        id=6002, school_group_id=1, first_name="Omar", last_name="Four",
        status="active", learning_style=None,
    ))
    db.commit()
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/6002?section=overview")
    assert response.status_code == 200
    html = response.text
    assert "Unassigned" in html
    assert 'name="learning_style"' in html


def test_learning_style_selector_options_are_unique_and_no_duplicate_ids(db):
    import re

    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view", "students.edit")
    db.add(models.Student(
        id=6003, school_group_id=1, first_name="Lina", last_name="Five",
        status="active", learning_style="Visual",
    ))
    db.commit()
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/6003?section=overview")
    assert response.status_code == 200
    html = response.text

    for style in LEARNING_STYLES:
        assert f'value="{style}"' in html

    # No duplicate id anywhere on the page (a duplicate id could silently
    # break an unrelated for/id association elsewhere on the same page).
    ids = re.findall(r'\bid="([^"]+)"', html)
    duplicates = {value for value in ids if ids.count(value) > 1}
    assert not duplicates, f"duplicate id attribute(s) on the page: {duplicates}"


def test_html_students_page_renders_the_distribution_panel(db):
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view")
    db.add_all([
        models.Student(id=5001, school_group_id=1, first_name="Vis", last_name="One", status="active", learning_style="Visual"),
        models.Student(id=5002, school_group_id=1, first_name="Aud", last_name="Two", status="active", learning_style="Auditory"),
    ])
    db.commit()
    _place_all(db, (5001, 5002))
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/")
    assert response.status_code == 200
    assert "Learning Style distribution" in response.text
    assert "not a talent score" in response.text.lower()
    assert "2 Students in this selection, including Unassigned" in response.text
    assert "50.0%" in response.text and "1 Student</small>" in response.text
    assert "Unassigned" in response.text and "0.0%" in response.text  # zero + Unassigned rows stay visible
    assert "Unavailable" not in response.text


def test_learning_style_badge_and_distribution_bar_use_the_same_accent_color_token():
    """Owner correction: whatever color a Learning Style uses in the Student
    row badge/chip (`templates/_learning_style.html`'s shared `ls_accent`
    map) must match the color used for that same style in the distribution
    bar/indicator (`templates/students.html`'s `ls_accent_map`) - one
    semantic token per style, everywhere, not two maps that could drift."""
    root = pathlib.Path(__file__).resolve().parents[1]
    badge_source = (root / "templates" / "_learning_style.html").read_text(encoding="utf-8")
    distribution_source = (root / "templates" / "students.html").read_text(encoding="utf-8")

    badge_match = re.search(r"ls_accent\s*=\s*(\{[^}]*\})", badge_source)
    distribution_match = re.search(r"ls_accent_map\s*=\s*(\{[^}]*\})", distribution_source)
    assert badge_match and distribution_match, "both accent color maps must be present in their templates"

    def _parse_map(literal: str) -> dict:
        return dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", literal))

    badge_accent = _parse_map(badge_match.group(1))
    distribution_accent = _parse_map(distribution_match.group(1))

    assert set(badge_accent) == {
        "Visual", "Auditory", "Read/Write", "Kinesthetic",
        "Verbal", "Non-verbal", "Quantitative", "Spatial",
    }
    for style, token in badge_accent.items():
        assert distribution_accent.get(style) == token, (
            f"{style} uses {token} in the badge but {distribution_accent.get(style)!r} in the distribution bar"
        )


def test_html_students_page_small_cohort_is_never_suppressed_and_has_no_privacy_banner(db):
    """Acceptance C: replaces the former "one panel-level protected message
    when every category is suppressed" and "privacy policy unavailable" tests
    (the stale/failing panel-message test is deliberately superseded). Five
    Students that used to be fully suppressed now render real counts and
    percentages on the shared full denominator, with no protected copy."""
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view")
    db.add_all([
        models.Student(id=6001, school_group_id=1, first_name="A", last_name="One", status="active", learning_style="Visual"),
        models.Student(id=6002, school_group_id=1, first_name="B", last_name="Two", status="active", learning_style="Visual"),
        models.Student(id=6003, school_group_id=1, first_name="C", last_name="Three", status="active", learning_style="Auditory"),
        models.Student(id=6004, school_group_id=1, first_name="D", last_name="Four", status="active", learning_style="Kinesthetic"),
        models.Student(id=6005, school_group_id=1, first_name="E", last_name="Five", status="active", learning_style=None),
    ])
    db.commit()
    _place_all(db, (6001, 6002, 6003, 6004, 6005))
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/")
    assert response.status_code == 200
    text = response.text
    assert "5 Students in this selection, including Unassigned" in text
    assert text.count('class="stu-ls-track"') == 9
    for expected in ("40.0%", "20.0%", "0.0%"):
        assert expected in text
    assert "stu-protected-panel" not in text
    assert "Distribution unavailable" not in text and "statistics unavailable" not in text
    assert "protected for privacy" not in text.lower()


def test_html_students_page_empty_selection_shows_empty_state_not_zero_percent(db):
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view")
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/")
    assert response.status_code == 200
    assert "No Students in the current authorized selection." in response.text
    assert 'class="stu-ls-row' not in response.text


# ---------------------------------------------------------------------------
# Zero effect on Talent scoring/eligibility/Official Identification
# ---------------------------------------------------------------------------

_TALENT_SCORING_MODULES = (
    "talent_program_service.py",
    "talent_analytics_service.py",
    "talent_org_intelligence_service.py",
    "talent_analytics_privacy.py",
    "routers/talent_assessments.py",
    "routers/talent_review_candidates.py",
    "routers/talent_assessment_cycles.py",
    "routers/talent_programs.py",
)


def test_no_talent_scoring_or_eligibility_module_reads_learning_style():
    """Explicit ADR 0031 assertion: Learning Style is never read by any
    Talent scoring/Program-Criteria/Official-Identification code path."""
    root = pathlib.Path(__file__).resolve().parents[1]
    checked = 0
    for relative in _TALENT_SCORING_MODULES:
        path = root / relative
        if not path.exists():
            continue
        checked += 1
        source = path.read_text(encoding="utf-8")
        assert "learning_style" not in source, f"{relative} must never read learning_style"
    assert checked >= 5, "expected to actually check several real Talent scoring modules"


# ---------------------------------------------------------------------------
# Aggregate distribution privacy (reuses the existing Talent privacy contract)
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, learning_style):
        self.learning_style = learning_style


def test_raw_counts_bucket_unset_and_unknown_values_as_not_specified():
    rows = [_Row("Visual"), _Row("Visual"), _Row(None), _Row("Nonsense")]
    counts = raw_learning_style_counts(rows)
    assert counts["Visual"] == 2
    assert counts["not_specified"] == 2
    assert counts["Auditory"] == 0


def test_build_distribution_visible_and_deterministic():
    rows = [_Row("Visual"), _Row("Visual"), _Row("Auditory"), _Row(None)]
    result = build_distribution(rows)
    assert result["state"] == "visible"
    assert result["total"]["value"] == result["total_population"] == 4
    by_label = {level["label"]: level for level in result["levels"]}
    assert by_label["Visual"]["count"] == 2
    assert by_label["Visual"]["percentage"] == 50.0
    assert by_label["Unassigned"]["count"] == 1
    # Order is always the fixed governed order, never magnitude-derived, and
    # covers all eight categorical values plus the Unassigned bucket (M14).
    assert [level["label"] for level in result["levels"]] == [
        "Visual", "Auditory", "Read/Write", "Kinesthetic",
        "Verbal", "Non-verbal", "Quantitative", "Spatial", "Unassigned",
    ]
    # The denominator (total) always includes Unassigned Students (task H).
    unassigned_and_categories = sum(level["count"] for level in result["levels"])
    assert unassigned_and_categories == result["total"]["value"] == 4
    assert build_distribution(rows) == result


def test_build_distribution_never_suppresses_a_small_cohort():
    # Acceptance C: the former suppression/complementary-suppression tests for
    # this distribution were replaced - 1 Visual + 4 Auditory is fully visible.
    result = build_distribution([_Row("Visual")] + [_Row("Auditory")] * 4)
    assert result["state"] == "visible"
    assert all(level["state"] == "visible" for level in result["levels"])
    by_label = {level["label"]: level for level in result["levels"]}
    assert by_label["Visual"]["count"] == 1 and by_label["Visual"]["percentage"] == 20.0
    assert by_label["Auditory"]["count"] == 4 and by_label["Auditory"]["percentage"] == 80.0
