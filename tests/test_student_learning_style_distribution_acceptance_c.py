"""Deployment Acceptance Correction C: Learning Style distribution.

Authorized Student-domain aggregate: denominator is every authorized Student
in the selection including Unassigned; all nine categories are always
returned; zero categories are 0 / 0%; NO Talent small-cell suppression applies
to this one distribution (it still applies to every other Talent analytics
metric - see the privacy regression proofs at the bottom).
"""

import inspect
import pathlib
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import student_learning_style_analytics as ls_analytics
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.students import router as students_router
from routers.talent_results_analytics import router as results_router
from student_academic_service import create_placement, create_student
from student_learning_style_analytics import build_distribution, resolve_population

ROOT = pathlib.Path(__file__).resolve().parents[1]
ORDER = ["Visual", "Auditory", "Read/Write", "Kinesthetic", "Verbal", "Non-verbal", "Quantitative", "Spatial", "Unassigned"]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    session.commit()
    session.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=11, school_group_id=1, name="One B"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.AcademicYear(id=200, school_group_id=2, year_name="2026-2027"),
    ])
    session.commit()
    yield session
    session.close()


def _seed(db, group, branch, ay, grade, style, n=1, prefix="S"):
    for i in range(n):
        student = create_student(db, school_group_id=group, first_name=f"{prefix}{style}{i}", father_name="F",
                                 last_name="L", gender="female", learning_style=style)
        create_placement(db, school_group_id=group, student_id=student.id, academic_year_id=ay, branch_id=branch,
                         grade_level=grade, section_name="A", effective_from=datetime(2026, 9, 1))
    db.commit()


def _ten(db, branch=10, grade="1"):
    # population 10: Visual 3, Auditory 2, Read/Write 1, Kinesthetic 1, Verbal 1, Unassigned 2
    for style, n in (("Visual", 3), ("Auditory", 2), ("Read/Write", 1), ("Kinesthetic", 1), ("Verbal", 1), (None, 2)):
        _seed(db, 1, branch, 100, grade, style, n)


def _user(db, scope="ORGANIZATION", branch_id=None, uid="1000000001"):
    user = models.User(user_id=uid, username=f"u{uid}", role="Administrator", user_type="TENANT", access_scope=scope,
                       school_group_id=1, branch_id=branch_id, academic_year_id=100, is_active=True)
    db.add(user)
    db.commit()
    user.scope_school_group_id = 1
    return user


def _client(db, user, *routers):
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)  # NO privacy policy override: the distribution needs none


def _by_label(payload):
    return {level["label"]: level for level in payload["levels"]}


def test_ten_student_cohort_is_fully_visible_with_unassigned_in_the_denominator(db):
    _ten(db)
    payload = build_distribution(resolve_population(db, school_group_id=1, user=_user(db), branch_id=10))
    assert payload["state"] == "visible"
    assert payload["total_population"] == payload["total"]["value"] == 10
    assert [level["label"] for level in payload["levels"]] == ORDER  # all 8 + Unassigned, stable order
    counts = {label: level["count"] for label, level in _by_label(payload).items()}
    assert counts == {"Visual": 3, "Auditory": 2, "Read/Write": 1, "Kinesthetic": 1, "Verbal": 1,
                      "Non-verbal": 0, "Quantitative": 0, "Spatial": 0, "Unassigned": 2}
    pcts = {label: level["percentage"] for label, level in _by_label(payload).items()}
    assert pcts == {"Visual": 30.0, "Auditory": 20.0, "Read/Write": 10.0, "Kinesthetic": 10.0, "Verbal": 10.0,
                    "Non-verbal": 0.0, "Quantitative": 0.0, "Spatial": 0.0, "Unassigned": 20.0}
    assert round(sum(pcts.values()), 6) == 100.0
    for level in payload["levels"]:
        assert level["state"] == "visible"  # zero categories are never Unavailable/suppressed
        assert level["count"] is not None and level["percentage"] is not None
    assert [level["display_order"] for level in payload["levels"]] == list(range(9))


def test_percentages_use_the_full_denominator_and_sum_to_about_100_for_uneven_cohorts(db):
    for style, n in (("Visual", 1), ("Spatial", 1), (None, 1)):
        _seed(db, 1, 10, 100, "1", style, n)
    payload = build_distribution(resolve_population(db, school_group_id=1, user=_user(db), branch_id=10))
    assert payload["total_population"] == 3
    assert _by_label(payload)["Unassigned"]["percentage"] == 33.33
    assert abs(sum(level["percentage"] for level in payload["levels"]) - 100) < 0.05


def test_only_unassigned_population_still_reports_full_denominator(db):
    _seed(db, 1, 10, 100, "1", None, 4)
    payload = build_distribution(resolve_population(db, school_group_id=1, user=_user(db), branch_id=10))
    assert payload["total_population"] == 4
    assert _by_label(payload)["Unassigned"]["percentage"] == 100.0
    assert _by_label(payload)["Visual"]["percentage"] == 0.0


def test_empty_population_is_safe_and_not_presented_as_zero_percent(db):
    payload = build_distribution(resolve_population(db, school_group_id=1, user=_user(db), branch_id=10))
    assert payload["state"] == "empty"
    assert payload["total_population"] == 0
    assert [level["label"] for level in payload["levels"]] == ORDER
    assert all(level["count"] == 0 and level["percentage"] is None for level in payload["levels"])
    assert build_distribution([])["state"] == "empty"


def test_grade_filter_limits_the_population_and_denominator(db):
    _ten(db, grade="1")
    _seed(db, 1, 10, 100, "2", "Spatial", 5)
    user = _user(db)
    grade_two = build_distribution(resolve_population(db, school_group_id=1, user=user, branch_id=10, grade_level="2"))
    assert grade_two["total_population"] == 5
    assert _by_label(grade_two)["Spatial"]["percentage"] == 100.0
    grade_one = build_distribution(resolve_population(db, school_group_id=1, user=user, branch_id=10, grade_level="1"))
    assert grade_one["total_population"] == 10
    both = build_distribution(resolve_population(db, school_group_id=1, user=user, branch_id=10))
    assert both["total_population"] == 15


def test_cross_tenant_students_are_never_counted(db):
    _ten(db)
    _seed(db, 2, 20, 200, "1", "Visual", 7, prefix="X")
    org = build_distribution(resolve_population(db, school_group_id=1, user=_user(db)))
    assert org["total_population"] == 10
    assert _by_label(org)["Visual"]["count"] == 3


def test_unauthorized_branch_students_are_excluded_and_explicit_branch_is_refused(db):
    _ten(db, branch=10)
    _seed(db, 1, 11, 100, "1", "Kinesthetic", 6, prefix="B")
    branch_user = _user(db, scope="BRANCH", branch_id=10, uid="1000000002")
    assert resolve_population(db, school_group_id=1, user=branch_user, branch_id=11) is None
    own = build_distribution(resolve_population(db, school_group_id=1, user=branch_user))
    assert own["total_population"] == 10
    assert _by_label(own)["Kinesthetic"]["count"] == 1  # Branch 11's six Kinesthetic Students are not visible
    assert build_distribution(resolve_population(db, school_group_id=1, user=_user(db)))["total_population"] == 16


def test_results_analytics_route_serves_small_cohort_without_a_privacy_policy(db):
    _ten(db)
    with _client(db, _user(db), results_router) as client:
        response = client.get("/api/talent/results-analytics/academic-years/100/learning-style?branch_id=10")
    assert response.status_code == 200
    payload = response.json()
    assert payload["family"] == "learning_style"
    assert "privacy_policy_version" not in payload
    distribution = payload["distribution"]
    assert distribution["total_population"] == 10
    assert _by_label(distribution)["Visual"]["percentage"] == 30.0
    assert all(level["state"] == "visible" for level in distribution["levels"])
    # Aggregate only: no Student identity anywhere in the payload.
    assert "SVisual" not in response.text and "first_name" not in response.text


def test_results_analytics_route_still_refuses_unauthorized_branch_and_missing_permission(db):
    _seed(db, 1, 11, 100, "1", "Visual", 2)
    branch_user = _user(db, scope="BRANCH", branch_id=10, uid="1000000003")
    with _client(db, branch_user, results_router) as client:
        denied = client.get("/api/talent/results-analytics/academic-years/100/learning-style?branch_id=11")
    assert denied.status_code == 403
    viewer = models.User(user_id="1000000004", username="viewer4", role="Viewer", user_type="TENANT", access_scope="BRANCH",
                         school_group_id=1, branch_id=10, academic_year_id=100, is_active=True)
    db.add(viewer)
    db.commit()
    viewer.scope_school_group_id = 1
    with _client(db, viewer, results_router) as client:
        assert client.get("/api/talent/results-analytics/academic-years/100/learning-style").status_code in (401, 403)


def test_students_api_route_serves_the_same_unsuppressed_distribution(db):
    _ten(db)
    with _client(db, _user(db), students_router) as client:
        payload = client.get("/api/students/analytics/learning-style-distribution?branch_id=10&grade_level=1").json()
    assert payload["total_population"] == 10
    assert _by_label(payload)["Auditory"]["count"] == 2
    assert all(level["state"] == "visible" for level in payload["levels"])


def test_no_deprecated_percentage_column_or_talent_privacy_pipeline_in_the_distribution_source():
    source = (ROOT / "student_learning_style_analytics.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
    body = code.split('"""', 2)[2]  # drop the module docstring
    for deprecated in ("learning_style_verbal_percentage", "learning_style_non_verbal_percentage",
                       "learning_style_quantitative_percentage", "learning_style_spatial_percentage"):
        assert deprecated not in body
    assert "talent_analytics_privacy" not in body
    assert "apply_primary_privacy" not in body and "run_complementary_suppression" not in body
    assert "policy" not in inspect.signature(ls_analytics.build_distribution).parameters


def test_students_and_results_routes_no_longer_depend_on_the_privacy_policy_for_learning_style():
    from routers import students as students_module
    from routers import talent_results_analytics as results_module

    assert "policy" not in inspect.signature(students_module.student_learning_style_distribution).parameters
    assert "policy" not in inspect.signature(results_module.learning_style).parameters


# ---------------------------------------------------------------------------
# Narrow privacy regression: suppression stays ACTIVE for everything else.
# ---------------------------------------------------------------------------


def test_talent_privacy_suppression_remains_active_for_other_metrics():
    from talent_analytics_privacy import DeterministicSuppressionTestPolicy, Cell, Group, apply_primary_privacy

    policy = DeterministicSuppressionTestPolicy(minimum_cohort=5)
    total = Cell(key=("total", "x"), privacy_class="P3", raw_value=4, depth=0)
    child = Cell(key=("child", "x", "a"), privacy_class="P3", raw_value=2, depth=1)
    apply_primary_privacy(Group(name="x", total=total, children=[child]).all_cells(), policy)
    assert child.state != "visible"  # the shared primitive still suppresses a small P3 cell


def test_classification_and_talented_families_still_use_the_privacy_pipeline():
    source = (ROOT / "talent_results_analytics_service.py").read_text(encoding="utf-8")
    assert "apply_primary_privacy" in source and "run_complementary_suppression" in source
    router = (ROOT / "routers" / "talent_results_analytics.py").read_text(encoding="utf-8")
    assert router.count("Depends(resolve_privacy_policy_provider)") >= 2  # classification + talented still policy-gated
