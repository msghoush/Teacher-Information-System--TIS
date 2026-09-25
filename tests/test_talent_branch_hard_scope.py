"""Talent Branch authority: Branch-limited hard ceiling + organization actor choice.

Owner-directed amendment (Part 1 production follow-up, 2026-09-25) to the Batch 1
closure. Real tenants/Branches/Students/Assessments through the real routers (the
sanctioned local Talent dataset: two Branches, ten Students, three Programs).

* organization/global actor: the sidebar Branch is only the DEFAULT page-level Branch,
  never a ceiling. An omitted branch_id is All Branches; every authorized Branch can
  be named explicitly; a foreign-tenant Branch is rejected;
* Branch-limited actor: the ceiling stays their authorized Branch. Any attempt to name,
  or widen to, another Branch is rejected on every read surface;
* the legacy branch_scope=all marker cookie is ignored and grants nothing.
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

import models
import talent_branch_scope
from routers import talent_learner_profiles, talent_review_candidates
from test_talent_batch1_data_scope import ORG, World, metrics, value

RESULTS = "/api/talent/results-analytics"
ANALYTICS = "/api/talent/analytics"
PROGRESS = "/api/talent/evaluation-progress"


@pytest.fixture()
def world():
    instance = World(foreign_keys=True)
    instance.client.app.include_router(talent_learner_profiles.router)
    instance.client.app.include_router(talent_review_candidates.router)
    yield instance
    instance.close()


def students_of(world, branch_id):
    return {row.student_id for row in world.db.query(models.TalentAssessmentCyclePopulationMember).filter_by(branch_id=branch_id)}


def program_path(world, family, tail=""):
    return f"{family}/programs/{world.program_a}/academic-years/{world.year}{tail}"


def read_surfaces(world, branch_query=""):
    """Every Talent read surface that returns Student- or Branch-derived data."""
    year = world.year
    q = branch_query
    return {
        "overview": f"{ORG}/overview?academic_year_id={year}{q}",
        "talent_map": f"{ORG}/talent-map?academic_year_id={year}&metric=frozen_eligible&dimension=program_branch{q}",
        "portfolio": f"{ORG}/program-portfolio?academic_year_id={year}{q}",
        "overlap": f"{ORG}/participation-overlap?academic_year_id={year}{q}",
        "longitudinal": f"{ORG}/programs/{world.program_a}/longitudinal?academic_year_id={year}&metric=frozen_eligible{q}",
        "drill": f"{ORG}/students?academic_year_id={year}&limit=100&offset=0{q}",
        "learning_style": f"{RESULTS}/academic-years/{year}/learning-style?{q.lstrip('&')}",
        "classification": program_path(world, RESULTS, "/classification") + f"?{q.lstrip('&')}",
        "talented": program_path(world, RESULTS, "/talented") + f"?{q.lstrip('&')}",
        "analytics_students": program_path(world, ANALYTICS, "/students") + f"?{q.lstrip('&')}",
        "analytics_overview": program_path(world, ANALYTICS, "/overview") + f"?{q.lstrip('&')}",
        "rubric": program_path(world, ANALYTICS, "/rubric-distribution") + f"?assessment_state=completed{q}",
        "progress_org": program_path(world, PROGRESS, "/organization"),
        "progress_comparison": program_path(world, PROGRESS, "/branch-comparison") + "?metric=current_overall_progress",
        "assessments": f"/api/talent/assessments?academic_year_id={year}",
        "eligible": f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students?{q.lstrip('&')}",
        "population": f"/api/talent/assessment-cycles/{world.cycle_b}/population",
        "review_candidates": "/api/talent/review-candidates",
        "planning_branches": f"/api/talent/programs/planning-branches?academic_year_id={year}",
    }


def test_sidebar_scope_is_not_a_ceiling_for_org_actor_and_helpers_compose_authorization():
    import auth

    for scope, all_visible in ((auth.ACCESS_SCOPE_ORGANIZATION, True), (auth.ACCESS_SCOPE_BRANCH, False)):
        user = SimpleNamespace(access_scope=scope, user_type="TENANT", scope_branch_id=7,
                               is_active=True, platform_role=None, role="Administrator")
        assert talent_branch_scope.talent_branch_ceiling(user) is None, scope
        assert talent_branch_scope.branch_scope_unrestricted(user) is all_visible, scope
        assert talent_branch_scope.branch_within_ceiling(user, 99) is True
    assert talent_branch_scope.talent_branch_ceiling(None) is None
    assert talent_branch_scope.branch_scope_unrestricted(None) is False


@pytest.mark.parametrize("ceiling_name,other_name", [("north", "south"), ("south", "north")])
def test_branch_limited_actor_is_confined_on_every_read_surface(world, ceiling_name, other_name):
    ceiling, other = getattr(world, ceiling_name), getattr(world, other_name)
    own, foreign = students_of(world, ceiling), students_of(world, other)
    assert own and foreign and not (own & foreign)
    world.branch_limited_user(ceiling)

    # (a)/(b)/(g) omitted Branch -> the ceiling Branch only, on every surface.
    assert value(metrics(world)["distinct_students"]) == 5
    assert {i["student_id"] for i in world.get(read_surfaces(world)["drill"]).json()["items"]} == own
    talent_map = world.get(read_surfaces(world)["talent_map"]).json()
    assert [column["id"] for column in talent_map["columns"]] == [ceiling]
    overlap = world.get(read_surfaces(world)["overlap"]).json()
    diagonal = {tuple(p["program_ids"]): p for p in overlap["canonical_pairs"] if p["program_ids"][0] == p["program_ids"][1]}
    assert diagonal[(world.program_a, world.program_a)]["value"] == 5
    learning = world.get(read_surfaces(world)["learning_style"]).json()
    assert learning["distribution"]["total_population"] == 5
    classification = world.get(read_surfaces(world)["classification"]).json()
    assert classification["distribution"]["total"]["value"] <= 5
    assert {row["student_id"] for row in world.get(read_surfaces(world)["eligible"]).json()["members"]} == own
    assert {row["student_id"] for row in world.get(read_surfaces(world)["population"]).json()["members"]} <= own
    assert {row["student_id"] for row in world.get(read_surfaces(world)["assessments"]).json()} <= own
    candidates = world.get(read_surfaces(world)["review_candidates"])
    assert candidates.status_code == 200
    branches = world.get(read_surfaces(world)["planning_branches"]).json()
    assert [row["id"] for row in branches] == [ceiling]
    comparison = world.get(read_surfaces(world)["progress_comparison"])
    assert comparison.status_code == 200
    assert other not in {row.get("branch_id") for row in comparison.json().get("rows", [])}
    analytics_students = world.get(read_surfaces(world)["analytics_students"]).json()
    assert {item["student_id"] for item in analytics_students["items"]} <= own

    # (a)/(b)/(d) an explicit OTHER Branch (stale URL / hand-crafted query) is rejected, never widened.
    rejected = read_surfaces(world, f"&branch_id={other}")
    for name in ("overview", "talent_map", "portfolio", "overlap", "longitudinal", "drill",
                 "learning_style", "classification", "talented", "analytics_students", "analytics_overview", "rubric", "eligible"):
        response = world.get(rejected[name])
        assert response.status_code in (400, 403, 404), (name, response.status_code)
        for foreign_id in foreign:
            assert f'"student_id":{foreign_id}' not in response.text.replace(" ", ""), name
    assert world.get(f"{ORG}/branches/{other}?academic_year_id={world.year}").status_code == 404
    assert world.get(program_path(world, PROGRESS, f"/branches/{other}")).status_code == 404
    assert world.get(f"/api/talent/programs/planning-grades?academic_year_id={world.year}&branch_id={other}").status_code == 404
    # the ceiling Branch itself keeps working when named explicitly
    assert world.get(f"{ORG}/branches/{ceiling}?academic_year_id={world.year}").status_code == 200
    assert world.get(read_surfaces(world, f"&branch_id={ceiling}")["overview"]).status_code == 200

    # Student-level reads of a Student outside the ceiling are not found (learner profile / progress).
    # A Student with history in BOTH Branches shows only the ceiling Branch's own records.
    for foreign_id in foreign:
        profile = world.get(f"/api/talent/learner-profiles/{foreign_id}")
        assert profile.status_code in (200, 404)
        if profile.status_code == 200:
            body = profile.json()
            assert {row["branch_id"] for row in body["placements"]} <= {ceiling}
            assert {event["branch_id"] for event in body["timeline"] if "branch_id" in event} <= {ceiling}
            for program in body["programs"]:
                for year in program["academic_years"]:
                    assert {c["frozen_context"]["branch_id"] for c in year["cycles"] if c["frozen_context"]} <= {ceiling}
        exclusive = not world.db.query(models.StudentAcademicPlacement).filter_by(student_id=foreign_id, branch_id=ceiling).count()
        if exclusive:
            assert profile.status_code == 404
            assert world.get(program_path(world, PROGRESS, f"/students/{foreign_id}")).status_code == 404
    assert world.get(f"/api/talent/learner-profiles/{next(iter(own))}").status_code == 200


def test_branch_limited_map_and_comparison_never_contain_the_other_branch(world):
    world.branch_limited_user(world.north)
    body = world.get(program_path(world, PROGRESS, "/branch-comparison") + "?metric=assessment_completion").json()
    other_name = world.db.get(models.Branch, world.south).name
    assert other_name not in str(body)
    talent_map = world.get(read_surfaces(world)["talent_map"]).json()
    assert other_name not in str(talent_map)


@pytest.mark.parametrize("sidebar_scope", ["north", "south", None])
def test_org_actor_may_choose_all_or_any_branch_whatever_the_sidebar_branch(world, sidebar_scope):
    """The sidebar Branch is only a default: it never narrows an organization actor."""
    world.as_admin(getattr(world, sidebar_scope) if sidebar_scope else None)
    # omitted Branch == All Branches
    assert value(metrics(world)["distinct_students"]) == 10
    talent_map = world.get(read_surfaces(world)["talent_map"]).json()
    assert {column["id"] for column in talent_map["columns"]} == {world.north, world.south}
    assert {i["student_id"] for i in world.get(read_surfaces(world)["drill"]).json()["items"]} == set(world.student_ids)
    assert world.get(read_surfaces(world)["learning_style"]).json()["distribution"]["total_population"] == 10
    assert {row["id"] for row in world.get(read_surfaces(world)["planning_branches"]).json()} == {world.north, world.south}
    assert world.get(program_path(world, PROGRESS, "/branch-comparison") + "?metric=assessment_completion").status_code == 200
    # every authorized Branch can be selected explicitly, in both directions
    for branch in (world.north, world.south):
        assert value(metrics(world, f"&branch_id={branch}")["distinct_students"]) == 5
        assert world.get(f"{ORG}/branches/{branch}?academic_year_id={world.year}").status_code == 200
        assert {i["student_id"] for i in world.get(read_surfaces(world, f"&branch_id={branch}")["drill"]).json()["items"]} == students_of(world, branch)
        assert world.get(read_surfaces(world, f"&branch_id={branch}")["learning_style"]).json()["distribution"]["total_population"] == 5
        assert {m["student_id"] for m in world.get(
            f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students?branch_id={branch}").json()["members"]} == students_of(world, branch)


def test_sidebar_scope_change_never_changes_org_actor_authority_or_widens_limited_actor(world):
    world.as_admin(world.north)
    assert value(metrics(world)["distinct_students"]) == 10
    world.as_admin(world.south)
    assert value(metrics(world, f"&branch_id={world.north}")["distinct_students"]) == 5
    world.branch_limited_user(world.south)
    assert value(metrics(world)["distinct_students"]) == 5
    assert world.get(read_surfaces(world, f"&branch_id={world.north}")["overview"]).status_code == 400


def test_branch_limited_actor_cannot_escape_their_branch(world):
    world.branch_limited_user(world.north)
    assert value(metrics(world)["distinct_students"]) == 5
    assert world.get(read_surfaces(world, f"&branch_id={world.south}")["overview"]).status_code == 400
    assert world.get(read_surfaces(world, f"&branch_id={world.north}")["overview"]).status_code == 200
    assert world.get(f"{ORG}/branches/{world.south}?academic_year_id={world.year}").status_code == 404


def test_tenant_isolation_is_preserved_under_the_ceiling(world):
    other = models.SchoolGroup(name="Other Tenant")
    world.db.add(other)
    world.db.flush()
    foreign_branch = models.Branch(school_group_id=other.id, name="Foreign Campus", status=True)
    world.db.add(foreign_branch)
    world.db.commit()
    for scope in (world.north, None, "limited"):
        if scope == "limited":
            world.branch_limited_user(world.north)
        else:
            world.as_admin(scope)
        assert world.get(read_surfaces(world, f"&branch_id={foreign_branch.id}")["overview"]).status_code == 400
        assert world.get(f"{ORG}/branches/{foreign_branch.id}?academic_year_id={world.year}").status_code == 404
        assert world.get(f"/api/talent/assessment-cycles/{world.cycle_b}/eligible-students?branch_id={foreign_branch.id}").status_code == 403
        assert world.get(f"{RESULTS}/academic-years/{world.year}/learning-style?branch_id={foreign_branch.id}").status_code == 403


def test_workspace_config_and_sidebar_publish_default_branch_and_lock_state():
    """tp-config publishes the sidebar Branch as the DEFAULT (org actor) or the lock (Branch-limited)."""
    import json
    import re

    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import auth
    from auth import get_current_user
    from database import Base
    from dependencies import get_db
    from routers import talent_ui
    from talent_local_test_data import build_dataset

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    summary = build_dataset(session)
    north, south = summary["branch_ids"]
    state = {"scope": north, "limited": False}

    def request_user():
        user = session.query(models.User).filter_by(user_id=summary["local_test_user_id"]).one()
        user.scope_school_group_id = summary["school_group_id"]
        user.scope_branch_id = state["scope"]
        user.scope_academic_year_id = summary["academic_year_id"]
        user.effective_role = "Administrator"
        if state["limited"]:
            user.access_scope = auth.ACCESS_SCOPE_BRANCH
            user.branch_id = state["scope"]
        else:
            user.access_scope = auth.ACCESS_SCOPE_ORGANIZATION
        return user

    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(talent_ui.router)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = request_user
    client = TestClient(app)

    def page():
        return client.get("/talent/overview").text

    def config():
        return json.loads(re.search(r'<script type="application/json" id="tp-config">(.*?)</script>', page(), re.S).group(1))

    assert config()["branch"] == north and config()["branchLocked"] is False
    state["scope"] = south
    assert config()["branch"] == south and config()["branchLocked"] is False
    html = page()
    assert "All Branches (Talent" not in html
    assert 'value="all"' not in html.split('id="sidebar_scope_branch_id"')[-1].split("</select>")[0]
    state.update(limited=True)
    locked = config()
    assert locked["branchLocked"] is True and locked["branch"] == south
    session.close()


def _cookie_request(world, user, cookies):
    import auth
    import main
    from starlette.requests import Request

    jar = [f"{auth.SESSION_COOKIE_KEY}={auth.create_session_token(user)}",
           f"branch_id={world.north}", f"academic_year_id={world.year}", *cookies]
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET", "path": "/talent/overview", "raw_path": b"/talent/overview",
        "query_string": b"", "headers": [(b"cookie", "; ".join(jar).encode("utf-8"))], "scheme": "http",
        "server": ("testserver", 80), "client": ("testclient", 50000), "root_path": "", "app": main.app,
    })


def test_legacy_branch_scope_marker_cookie_is_ignored_and_grants_nothing(world):
    import auth

    admin = world.db.query(models.User).filter_by(user_id=world.admin_user_id).one()
    plain = auth.get_current_user(_cookie_request(world, admin, []), world.db)
    marked = auth.get_current_user(_cookie_request(world, admin, ["branch_scope=all"]), world.db)
    for resolved in (plain, marked):
        assert resolved.scope_branch_id == world.north
        assert getattr(resolved, "scope_all_branches", False) is False
        assert talent_branch_scope.talent_branch_ceiling(resolved) is None
    assert talent_branch_scope.branch_scope_unrestricted(marked) is talent_branch_scope.branch_scope_unrestricted(plain)
    # The marker never widens a Branch-limited actor.
    world.branch_limited_user(world.north)
    limited = world.db.query(models.User).filter_by(user_id="LTB0001").one()
    limited_scope = auth.get_current_user(_cookie_request(world, limited, ["branch_scope=all"]), world.db)
    assert talent_branch_scope.branch_scope_unrestricted(limited_scope) is False
    assert {row[0] for row in auth.get_accessible_branch_query(world.db, limited_scope).with_entities(models.Branch.id).all()} == {world.north}
    assert talent_branch_scope.visible_branch_ids(world.db, limited_scope) == {world.north}


def test_scope_branch_endpoint_no_longer_offers_all_and_clears_the_legacy_marker(world):
    import main

    admin = world.db.query(models.User).filter_by(user_id=world.admin_user_id).one()

    def cookies(response):
        return b"\n".join(value for key, value in response.raw_headers if key == b"set-cookie").decode("ascii")

    ignored = main.set_scope_branch(request=_cookie_request(world, admin, []), branch_id="all", return_to="/talent/overview", db=world.db)
    header = cookies(ignored)
    assert "branch_scope=all" not in header and "branch_id=" not in header  # nothing is set
    specific = main.set_scope_branch(request=_cookie_request(world, admin, ["branch_scope=all"]), branch_id=str(world.south), return_to="/talent/overview", db=world.db)
    header = cookies(specific)
    assert f"branch_id={world.south}" in header
    assert 'branch_scope=""' in header or "branch_scope=;" in header  # legacy marker cleared
    world.branch_limited_user(world.north)
    limited = world.db.query(models.User).filter_by(user_id="LTB0001").one()
    denied = main.set_scope_branch(request=_cookie_request(world, limited, []), branch_id=str(world.south), return_to="/talent/overview", db=world.db)
    assert "branch_id=" not in cookies(denied)
