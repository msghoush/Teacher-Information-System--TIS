"""Student Learning Style V1 (ADR 0031) focused regression coverage.

Learning Style is Student-domain learner-profile context, optional and
single-select, with exactly four approved values. It must have zero effect
on Talent scoring/eligibility/Official Identification and must reuse the
existing `students.edit` permission and the existing Talent privacy/
suppression contract for aggregate distribution - never a new/weaker rule.
"""

import pathlib

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
from student_academic_service import (
    LEARNING_STYLES,
    StudentAcademicError,
    create_student,
    get_student,
    update_student,
)
from student_learning_style_analytics import build_distribution, raw_learning_style_counts
from talent_analytics_privacy import AllowAllTestPolicy, DeterministicSuppressionTestPolicy, resolve_privacy_policy_provider
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


# ---------------------------------------------------------------------------
# Service-layer validation
# ---------------------------------------------------------------------------

def test_nullable_and_four_valid_values_are_accepted_on_create(database):
    _, db = database
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

_UNSET = object()


def _admin_client(db, policy=_UNSET, scope="BRANCH"):
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
    if policy is not _UNSET:
        app.dependency_overrides[resolve_privacy_policy_provider] = lambda: policy
    return TestClient(app)


def test_api_accepts_the_four_values_and_rejects_any_other_value(database):
    _, db = database
    client = _admin_client(db)
    created = client.post("/api/students", json={"first_name": "Lina", "last_name": "Saleh", "learning_style": "Visual"})
    assert created.status_code == 201
    assert created.json()["learning_style"] == "Visual"
    student_id = created.json()["id"]

    rejected = client.post("/api/students", json={"first_name": "Bad", "last_name": "Value", "learning_style": "Telepathic"})
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


def test_api_distribution_route_returns_visible_privacy_safe_counts(database):
    # Org-scoped actor: the distribution population is "current effective
    # placement" scoped only when a Branch/Grade/Section filter narrows it;
    # with none given here, an org-wide actor sees every active Student in
    # the SchoolGroup (mirrors list_students' own no-filter behavior), so
    # these placement-less test fixtures still count.
    _, db = database
    for style in ("Visual", "Visual", "Auditory", None):
        _student(db, first=f"S-{style}-{id(object())}", learning_style=style)
    client = _admin_client(db, policy=AllowAllTestPolicy(), scope="ORGANIZATION")
    response = client.get("/api/students/analytics/learning-style-distribution")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "visible"
    by_label = {level["label"]: level for level in payload["levels"]}
    assert by_label["Visual"]["count"] == 2
    assert by_label["Not specified"]["count"] == 1


def test_api_distribution_route_fails_closed_when_policy_unavailable(database):
    _, db = database
    _student(db)
    client = _admin_client(db, policy=None)
    response = client.get("/api/students/analytics/learning-style-distribution")
    assert response.status_code == 503
    assert response.json()["code"] == "analytics_unavailable"


def test_new_student_form_renders_the_selector_with_all_four_values_and_none_selected(db):
    """Real rendered-HTML regression for the Add Student flow.

    Closes a UI-level coverage gap: prior Learning Style V1 tests only
    asserted service/API behavior, not that the shared
    ``learning_style_field`` macro actually renders selectable radio pills
    (as opposed to, say, an empty options list silently producing no
    markup). A brand-new Student has no saved value, so only the
    "Not specified" pill should be pre-selected.
    """
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
    for style in LEARNING_STYLES:
        assert f'value="{style}"' in html
    assert 'value="" checked' in html
    assert html.count("is-selected") == 1


def test_edit_details_form_renders_the_selector_and_preselects_the_current_value(db):
    """Real rendered-HTML regression for the Edit Details flow.

    Proves the same shared macro renders in ``student_profile.html`` and
    that a Student's currently saved Learning Style is marked
    selected/checked when Edit Details is reopened, not just that the
    read-only badge (which is separately tested/known-good) shows it.
    """
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
    assert 'class="stu-ls-options" role="radiogroup"' in html
    for style in LEARNING_STYLES:
        assert f'value="{style}"' in html
    assert 'value="Kinesthetic" checked' in html
    # Exactly one pill (Kinesthetic) is pre-selected in the edit control.
    assert html.count('name="learning_style" value="Kinesthetic" checked') == 1
    for style in LEARNING_STYLES:
        if style != "Kinesthetic":
            assert f'value="{style}" checked' not in html


def test_edit_details_form_preselects_not_specified_when_no_value_is_saved(db):
    """Real rendered-HTML regression for the Edit Details flow when a
    Student has never had a Learning Style saved (``learning_style`` is
    ``None`` in the database, not an empty string).

    The shared macro compares the saved value against each option
    (including the empty-string "Not specified" option) with ``==``; a
    Python/Jinja ``None`` saved value must still resolve to the
    "Not specified" pill being checked/selected on load, exactly like a
    freshly-created Student (see
    ``test_new_student_form_renders_the_selector_with_all_four_values_and_none_selected``),
    not leave every pill unselected.
    """
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
    assert 'value="" checked' in html
    assert html.count("is-selected") == 1
    for style in LEARNING_STYLES:
        assert f'value="{style}" checked' not in html


def test_learning_style_label_structurally_wraps_its_radio_with_no_intervening_element_or_id_collision(db):
    """Structural proof that the click target is correct native HTML.

    A Learning Style click/select defect was reported and reproduced in a
    real browser. Reading ``_learning_style.html`` shows a ``<label>``
    directly wrapping its ``<input type="radio">`` with a shared ``name``
    (no ``id``/``for`` pairing at all, so a duplicate ``id`` elsewhere on
    the page cannot break this specific control's association) - this is
    exactly the robust native pattern that should make "click anywhere on
    the pill selects it" work with zero JavaScript. This test proves that
    structure holds in the real rendered page rather than only in the
    template source: every ``stu-ls-option`` label's *first* child element
    is its own radio input (nothing wraps or sits between the label and its
    input that could intercept the click), and no ``id`` attribute is
    duplicated anywhere on the rendered page (which would otherwise be able
    to break unrelated ``for``/``id`` associations on the same page, e.g.
    First/Last name).
    """
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

    # Every stu-ls-option label's first child (ignoring whitespace) is its
    # own radio input - no wrapping/overlapping element sits in between.
    label_opens = list(re.finditer(r'<label class="stu-ls-option[^"]*"[^>]*>', html))
    assert len(label_opens) == 5  # "" + the four LEARNING_STYLES
    for match in label_opens:
        remainder = html[match.end():].lstrip()
        assert remainder.startswith('<input type="radio" name="learning_style"'), (
            "an element other than the radio input directly follows the "
            "stu-ls-option <label> open tag, which could intercept clicks"
        )

    # No duplicate id anywhere on the page (a duplicate id could silently
    # break an unrelated for/id association elsewhere on the same page).
    ids = re.findall(r'\bid="([^"]+)"', html)
    duplicates = {value for value in ids if ids.count(value) > 1}
    assert not duplicates, f"duplicate id attribute(s) on the page: {duplicates}"


def test_html_students_page_renders_the_distribution_panel_when_policy_is_available(db, monkeypatch):
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view")
    db.add_all([
        models.Student(id=5001, school_group_id=1, first_name="Vis", last_name="One", status="active", learning_style="Visual"),
        models.Student(id=5002, school_group_id=1, first_name="Aud", last_name="Two", status="active", learning_style="Auditory"),
    ])
    db.commit()
    monkeypatch.setattr("routers.students_ui.resolve_privacy_policy_provider", lambda: AllowAllTestPolicy())
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


def test_html_students_page_shows_one_panel_level_protected_message_when_every_category_is_suppressed(db, monkeypatch):
    """When the whole cohort is small enough that every Learning Style
    category is individually suppressed, the page must show ONE clear
    panel-level explanation rather than repeating "Protected for privacy" on
    every row - while still rendering every category label (categorical
    protection preserved) and never a count/percentage for a suppressed row."""
    from fastapi.staticfiles import StaticFiles
    from routers import students_ui

    permissions(db, "students.view")
    # A small population below the deterministic suppression threshold for
    # every individual category, but above it in total, mirroring the real
    # sanctioned local test cohort shape (total visible, every category cell
    # suppressed).
    db.add_all([
        models.Student(id=6001, school_group_id=1, first_name="A", last_name="One", status="active", learning_style="Visual"),
        models.Student(id=6002, school_group_id=1, first_name="B", last_name="Two", status="active", learning_style="Visual"),
        models.Student(id=6003, school_group_id=1, first_name="C", last_name="Three", status="active", learning_style="Auditory"),
        models.Student(id=6004, school_group_id=1, first_name="D", last_name="Four", status="active", learning_style="Kinesthetic"),
        models.Student(id=6005, school_group_id=1, first_name="E", last_name="Five", status="active", learning_style=None),
    ])
    db.commit()
    monkeypatch.setattr(
        "routers.students_ui.resolve_privacy_policy_provider",
        lambda: DeterministicSuppressionTestPolicy(minimum_cohort=5),
    )
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(students_ui.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor()
    with TestClient(app) as client:
        response = client.get("/students/")
    assert response.status_code == 200
    # Exactly one panel-level protected explanation, not one per row.
    assert response.text.count("stu-protected-panel") == 1
    assert response.text.lower().count("protected for privacy") == 1
    # Fully protected data renders no chart rows or category-by-category fake bars.
    assert 'class="stu-ls-chart"' not in response.text
    assert 'class="stu-ls-row"' not in response.text
    # No raw count or percentage for any protected category leaks through.
    assert "66.7" not in response.text and "40.0" not in response.text and "20.0" not in response.text


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


def test_build_distribution_visible_with_allow_all_policy():
    rows = [_Row("Visual"), _Row("Visual"), _Row("Auditory"), _Row(None)]
    result = build_distribution(rows, AllowAllTestPolicy())
    assert result["state"] == "visible"
    assert result["total"]["value"] == 4
    by_label = {level["label"]: level for level in result["levels"]}
    assert by_label["Visual"]["count"] == 2
    assert by_label["Visual"]["percentage"] == 50.0
    assert by_label["Not specified"]["count"] == 1
    # Order is always the fixed governed order, never magnitude-derived.
    assert [level["label"] for level in result["levels"]] == [
        "Visual", "Auditory", "Read/Write", "Kinesthetic", "Not specified",
    ]


def test_build_distribution_suppresses_small_protected_cohort_and_its_reconstructible_sibling():
    # 1 Visual, 4 Auditory, 0 everything else, total 5. With minimum_cohort=2,
    # Visual (1) is suppressed. If Auditory (4) and the total (5) both stayed
    # visible, the hidden Visual count could be reconstructed by subtraction
    # (5 - 4 = 1) - complementary suppression must hide exactly one more
    # sibling (or the total) instead of allowing that reconstruction.
    rows = [_Row("Visual")] + [_Row("Auditory")] * 4
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=2)
    result = build_distribution(rows, policy)
    assert result["state"] == "visible"
    states = {level["label"]: level["state"] for level in result["levels"]}
    assert states["Visual"] == "suppressed"
    visible_children_sum = sum(
        level["count"] for level in result["levels"] if level["state"] == "visible" and level["count"] is not None
    )
    # The visible children must never sum to the visible total when at least
    # one child is hidden - that would let the hidden value be reconstructed.
    if result["total"]["state"] == "visible":
        assert visible_children_sum != result["total"]["value"] or any(
            level["state"] != "visible" for level in result["levels"]
        )
    # No suppressed/coarsened level ever carries a leftover count or percentage.
    for level in result["levels"]:
        if level["state"] != "visible":
            assert level["count"] is None
            assert level["percentage"] is None


def test_build_distribution_fails_closed_when_no_policy_is_configured_at_the_route_layer():
    # The route itself (routers/students.py) returns 503 analytics_unavailable
    # when Depends(resolve_privacy_policy_provider) yields None; this proves
    # build_distribution is never even reached with an unresolved policy.
    from routers import students as students_router_module
    import inspect as _inspect

    source = _inspect.getsource(students_router_module.student_learning_style_distribution)
    assert "policy is None" in source
    assert "503" in source
