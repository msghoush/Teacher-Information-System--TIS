"""Final-closure Part B: central organization Talent configuration authority.

Programs, Frameworks/Rubrics, Competencies/KPI, annual Program configuration,
Evaluation Plans/Periods and Assessment Cycle definitions are SchoolGroup-level
shared configuration governed once by the organization Administrator. Branches
keep only Students, placements, Cycle population evidence, assessments, results
and analytics. No Branch copy/enablement model exists or is introduced.

Authority = the existing semantic permission (`.manage/.govern/.delete*`, default
Administrator-only in code) AND organization/global access scope. These tests pin:

* the code-defined default role matrix (Editor/User/Limited hold no Talent key);
* an inventory of EVERY mutating Talent configuration route with its permission
  key(s) so a new route forces a decision;
* role x route: organization Administrator allowed, Branch-scoped Administrator and
  a Branch-scoped custom-grant Editor denied server-side (403) even with the UI
  bypassed, default Editor/User/Limited denied;
* per-route permission-key mapping (denying exactly that key denies the route);
* shared-configuration READS and operational assessment stay available to a
  Branch operational user, and tenant isolation holds.
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import models
import permission_registry as pr
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers import talent_assessment_cycles, talent_evaluation_plans, talent_programs
from talent_program_service import create_program

P = "talent_programs."
C = "talent_assessment_cycles."
E = "talent_evaluation_plans."

# (METHOD, route template) -> permission key(s) that route requires (ALL must hold).
EXPECTED_MUTATIONS = {
    ("POST", "/api/talent/programs"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}"): [P + "delete"],
    ("PATCH", "/api/talent/programs/{program_id}"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/logo"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/logo"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/lifecycle/{target_status}"): [P + "govern"],
    ("PUT", "/api/talent/programs/{program_id}/academic-years/{academic_year_id}"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/frameworks"): [P + "manage"],
    ("PATCH", "/api/talent/programs/{program_id}/frameworks/{framework_id}"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/frameworks/{framework_id}/activate"): [P + "govern"],
    ("POST", "/api/talent/programs/{program_id}/frameworks/{framework_id}/retire"): [P + "govern"],
    ("POST", "/api/talent/programs/{program_id}/competencies"): [P + "manage"],
    ("PATCH", "/api/talent/programs/{program_id}/competencies/{competency_id}"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/frameworks/{framework_id}/competencies"): [P + "manage"],
    ("PATCH", "/api/talent/programs/{program_id}/frameworks/{framework_id}/competencies/{competency_id}"): [P + "manage"],
    ("PUT", "/api/talent/programs/{program_id}/frameworks/{framework_id}/competencies/order"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/frameworks/{framework_id}/competencies/{competency_id}"): [P + "delete_competency"],
    ("POST", "/api/talent/programs/{program_id}/frameworks/{framework_id}/grades/copy"): [P + "manage"],
    ("PUT", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/levels"): [P + "manage"],
    ("POST", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/levels/copy"): [P + "manage"],
    ("PATCH", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/levels/{level_id}"): [P + "manage"],
    ("PUT", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/levels/order"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/levels/{level_id}"): [P + "delete_rubric_level"],
    ("PUT", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/descriptors"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/grade-descriptors/{descriptor_id}"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/frameworks/{framework_id}/rubric/descriptors/{descriptor_id}"): [P + "manage"],
    ("PUT", "/api/talent/programs/{program_id}/frameworks/{framework_id}/kpi"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/frameworks/{framework_id}/kpi"): [P + "manage"],
    ("PUT", "/api/talent/programs/{program_id}/frameworks/{framework_id}/review-candidate-policy"): [P + "manage"],
    ("DELETE", "/api/talent/programs/{program_id}/frameworks/{framework_id}/review-candidate-policy"): [P + "manage"],
    ("POST", "/api/talent/assessment-cycles"): [C + "manage"],
    ("PATCH", "/api/talent/assessment-cycles/{cycle_id}"): [C + "manage"],
    ("POST", "/api/talent/assessment-cycles/{cycle_id}/open"): [C + "govern"],
    ("POST", "/api/talent/assessment-cycles/{cycle_id}/close"): [C + "govern"],
    ("POST", "/api/talent/assessment-cycles/{cycle_id}/population/synchronize"): [C + "govern"],
    ("POST", "/api/talent/evaluation-plans"): [E + "manage"],
    ("POST", "/api/talent/evaluation-plans/{plan_id}/periods"): [E + "manage"],
    ("PATCH", "/api/talent/evaluation-periods/{period_id}"): [E + "manage"],
    ("DELETE", "/api/talent/evaluation-periods/{period_id}"): [E + "delete_period"],
    ("POST", "/api/talent/evaluation-plans/{plan_id}/periods/reorder"): [E + "manage_timeline"],
    ("POST", "/api/talent/evaluation-plans/{plan_id}/activate"): [E + "govern"],
    ("POST", "/api/talent/evaluation-periods/{period_id}/cancel"): [E + "govern"],
    ("POST", "/api/talent/evaluation-plans/{plan_id}/close"): [E + "govern"],
    ("POST", "/api/talent/evaluation-plans/{plan_id}/rollover"): [E + "view", E + "manage"],
    ("POST", "/api/talent/assessment-cycles/{cycle_id}/link-period"): [E + "manage", C + "manage", E + "select_period"],
    ("POST", "/api/talent/assessment-cycles/{cycle_id}/unlink-period"): [E + "manage", C + "manage"],
}

ROUTES = sorted(EXPECTED_MUTATIONS)
# Keys that a configuration mutation may require; everything else on these routers is a read.
CONFIG_KEYS = sorted({key for keys in EXPECTED_MUTATIONS.values() for key in keys if not key.endswith(".view")})


def _actual_mutations():
    found = set()
    for module in (talent_programs, talent_assessment_cycles, talent_evaluation_plans):
        for route in module.router.routes:
            for method in route.methods - {"GET", "HEAD", "OPTIONS"}:
                found.add((method, route.path))
    return found


def test_every_mutating_talent_configuration_route_is_inventoried():
    assert _actual_mutations() == set(EXPECTED_MUTATIONS), (
        "A Talent configuration mutation route was added or removed: decide its permission key "
        "and confirm it inherits the organization-scope gate, then update EXPECTED_MUTATIONS."
    )


# ---------------------------------------------------------------------------
# Code-defined default role matrix (no stored rows, no migration involved).
# ---------------------------------------------------------------------------

def test_default_role_matrix_only_administrator_holds_talent_configuration_keys():
    talent_keys = {key for key in pr.ALL_PERMISSION_KEYS if key.startswith("talent_")}
    admin = pr.get_default_permissions_for_role(auth.ROLE_ADMINISTRATOR)
    assert set(CONFIG_KEYS) <= admin
    for role in (auth.ROLE_EDITOR, auth.ROLE_USER, auth.ROLE_LIMITED):
        held = pr.get_default_permissions_for_role(role)
        assert not (held & talent_keys), f"{role} must hold no Talent permission by default"
        assert not (held & set(CONFIG_KEYS))
    # Limited can never be granted a configuration key, even by a stored row.
    assert not (pr.constrain_role_permissions(auth.ROLE_LIMITED, set(CONFIG_KEYS)) & set(CONFIG_KEYS))


# ---------------------------------------------------------------------------
# Role x route behavior.
# ---------------------------------------------------------------------------

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


_counter = iter(range(1, 10_000))


def make_user(db, *, role, scope, platform=None):
    number = next(_counter)
    row = models.User(
        user_id=f"90{number:08d}", username=f"central{number}", role=role,
        user_type="PLATFORM" if platform else "TENANT", platform_role=platform,
        access_scope=scope, school_group_id=None if platform else 1,
        branch_id=None if platform else 10, academic_year_id=100, is_active=True,
    )
    db.add(row)
    db.commit()
    row.scope_school_group_id = 1
    row.scope_branch_id = 10
    return row


def grant_tenant(db, role, keys, *, allowed=True, group=1):
    db.add_all([models.RolePermission(school_group_id=group, role=role, permission_key=key, is_allowed=allowed) for key in keys])
    db.commit()


def api_for(db, actor):
    app = FastAPI()
    for module in (talent_programs, talent_assessment_cycles, talent_evaluation_plans):
        app.include_router(module.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    return TestClient(app, raise_server_exceptions=False)


def call(api, method, template):
    path = re.sub(r"\{target_status\}", "active", template)
    path = re.sub(r"\{[a-z_]+\}", "1", path)
    kwargs = {"params": {"expected_revision": 1}}
    if path.endswith("/logo") and method == "POST":
        kwargs["files"] = {"logo": ("logo.png", b"not-a-real-image", "image/png")}
    else:
        kwargs["json"] = {}
    return api.request(method, path, **kwargs)


@pytest.mark.parametrize("method,template", ROUTES)
def test_organization_administrator_passes_the_gate_on_every_configuration_route(db, method, template):
    actor = make_user(db, role="Administrator", scope="ORGANIZATION")
    response = call(api_for(db, actor), method, template)
    # Junk ids/payload: any outcome except an authority denial proves the gate admitted the actor.
    assert response.status_code not in (401, 403), (method, template, response.status_code, response.text[:120])


@pytest.mark.parametrize("method,template", ROUTES)
def test_platform_developer_still_passes_the_gate(db, method, template):
    actor = make_user(db, role="Administrator", scope="ORGANIZATION", platform="Platform Developer")
    response = call(api_for(db, actor), method, template)
    assert response.status_code not in (401, 403), (method, template, response.status_code, response.text[:120])


@pytest.mark.parametrize("method,template", ROUTES)
def test_branch_scoped_administrator_cannot_mutate_shared_configuration(db, method, template):
    # UI bypassed: the request is sent directly. Holds every default key, still Branch-scoped.
    actor = make_user(db, role="Administrator", scope="BRANCH")
    response = call(api_for(db, actor), method, template)
    assert response.status_code == 403, (method, template, response.status_code, response.text[:120])
    assert response.json()["code"] == "organization_authority_required"
    assert db.query(models.TalentProgram).count() == 0


@pytest.mark.parametrize("method,template", ROUTES)
@pytest.mark.parametrize("role,scope", [("Editor", "ORGANIZATION"), ("User", "ORGANIZATION"), ("Limited", "ORGANIZATION"),
                                        ("Editor", "BRANCH"), ("User", "BRANCH"), ("Limited", "BRANCH")])
def test_default_non_administrator_roles_are_denied_every_configuration_route(db, method, template, role, scope):
    actor = make_user(db, role=role, scope=scope)
    response = call(api_for(db, actor), method, template)
    assert response.status_code == 403, (role, scope, method, template, response.status_code)


@pytest.mark.parametrize("method,template", ROUTES)
def test_branch_scoped_custom_grant_holder_is_still_denied_server_side(db, method, template):
    # A stored tenant grant of every configuration key to Editor (the deployment risk case)
    # does NOT let a Branch-scoped Editor mutate shared configuration.
    grant_tenant(db, "Editor", set(CONFIG_KEYS) | {P + "view", E + "view", C + "view"})
    actor = make_user(db, role="Editor", scope="BRANCH")
    assert set(CONFIG_KEYS) <= auth.get_allowed_permission_keys(db, actor, 1)
    response = call(api_for(db, actor), method, template)
    assert response.status_code == 403 and response.json()["code"] == "organization_authority_required"


@pytest.mark.parametrize("method,template", ROUTES)
def test_each_route_is_gated_by_its_own_permission_key(db, method, template):
    """permission key x route: denying exactly one required key (tenant stored deny) denies the route."""
    for key in EXPECTED_MUTATIONS[(method, template)]:
        grant_tenant(db, "Administrator", [key], allowed=False)
        actor = make_user(db, role="Administrator", scope="ORGANIZATION")
        response = call(api_for(db, actor), method, template)
        assert response.status_code == 403, (method, template, key, response.status_code)
        db.query(models.RolePermission).delete()
        db.commit()


def test_organization_scope_custom_grant_is_respected_not_stripped(db):
    # Stored custom grants are NOT arbitrarily revoked: an ORGANIZATION-scoped Editor an
    # administrator explicitly granted manage still passes (reported as owner-visible residual).
    grant_tenant(db, "Editor", [P + "manage"])
    actor = make_user(db, role="Editor", scope="ORGANIZATION")
    response = api_for(db, actor).post("/api/talent/programs", json={"name": "Granted Organization Editor"})
    assert response.status_code == 201


def test_organization_administrator_can_author_shared_configuration_once(db):
    actor = make_user(db, role="Administrator", scope="ORGANIZATION")
    api = api_for(db, actor)
    created = api.post("/api/talent/programs", json={"name": "One Shared Program", "description": "Purpose"})
    assert created.status_code == 201
    program_id = created.json()["id"]
    assert api.patch(f"/api/talent/programs/{program_id}", json={"name": "One Shared Program"}).status_code == 200
    assert api.post(f"/api/talent/programs/{program_id}/frameworks", json={"title": "Shared Framework"}).status_code == 201
    assert db.query(models.TalentProgram).count() == 1
    # Programs carry no Branch ownership: the model has no Branch column (no Branch copy/enablement).
    assert "branch_id" not in models.TalentProgram.__table__.columns
    branch_tables = [name for name in Base.metadata.tables if "talent" in name and "branch" in name and "enable" in name]
    assert branch_tables == []


# ---------------------------------------------------------------------------
# Shared reads stay available; tenant isolation.
# ---------------------------------------------------------------------------

def test_branch_operational_user_reads_shared_configuration_without_mutation(db):
    program = create_program(db, school_group_id=1, name="Shared Read Program")
    db.commit()
    grant_tenant(db, "Editor", [P + "view", E + "view", C + "view", "talent_assessments.view"])
    actor = make_user(db, role="Editor", scope="BRANCH")
    api = api_for(db, actor)
    assert api.get("/api/talent/programs").status_code == 200
    read = api.get(f"/api/talent/programs/{program.id}")
    assert read.status_code == 200 and "delete" not in read.json()["actions"]
    assert api.get("/api/talent/evaluation-plans").status_code == 200
    assert api.get("/api/talent/assessment-cycles").status_code == 200
    denied = api.patch(f"/api/talent/programs/{program.id}", json={"name": "Renamed by Branch"})
    assert denied.status_code == 403
    db.expire_all()
    assert db.get(models.TalentProgram, program.id).name == "Shared Read Program"


def test_tenant_isolation_holds_for_configuration_reads_and_writes(db):
    outsider = create_program(db, school_group_id=2, name="Other Tenant Program")
    db.commit()
    admin = make_user(db, role="Administrator", scope="ORGANIZATION")
    api = api_for(db, admin)
    assert api.get(f"/api/talent/programs/{outsider.id}").status_code == 404
    assert api.patch(f"/api/talent/programs/{outsider.id}", json={"name": "Hijack"}).status_code == 404
    assert api.get("/api/talent/programs").json() == []
    db.expire_all()
    assert db.get(models.TalentProgram, outsider.id).name == "Other Tenant Program"


# ---------------------------------------------------------------------------
# Branch operational flow is untouched (Part A Start Assessment stays working for
# a non-Administrator Branch user holding only operational permissions).
# ---------------------------------------------------------------------------

def test_branch_operational_editor_still_starts_assessments_but_cannot_configure():
    from test_talent_batch1_data_scope import World
    from test_talent_start_assessment_flow import make_program, roster

    world = World(foreign_keys=True)
    try:
        program, cycle = make_program(world, name="Operational Program", competency_grade=None)
        group = world.group_id
        # World seeds explicit tenant rows mirroring the code defaults (Editor: every Talent key denied);
        # an administrator's custom grant is an UPDATE of that stored row.
        for key in ("talent_programs.view", "talent_evaluation_plans.view", "talent_assessment_cycles.view",
                    "talent_assessments.view", "talent_assessments.manage", "talent_assessments.complete"):
            row = world.db.query(models.RolePermission).filter_by(school_group_id=group, role="Editor", permission_key=key).one_or_none()
            if row is None:
                world.db.add(models.RolePermission(school_group_id=group, role="Editor", permission_key=key, is_allowed=True))
            else:
                row.is_allowed = True
        editor = models.User(
            user_id="OPEDIT01", username="branch_operational_editor", email="op@example.test",
            email_normalized="op@example.test", first_name="Op", last_name="Editor", password="x",
            role="Editor", user_type="TENANT", access_scope="BRANCH", school_group_id=group,
            branch_id=world.north, academic_year_id=world.year, is_active=True,
        )
        world.db.add(editor)
        world.db.commit()
        world.current = {"user_id": "OPEDIT01", "scope_branch_id": world.north}

        members = roster(world, cycle.id)
        assert members
        created = world.client.post("/api/talent/assessments", json={"cycle_id": cycle.id, "student_id": members[0]["student_id"]})
        assert created.status_code == 201, created.text
        assert world.client.get(f"/api/talent/programs/{program.id}").status_code == 200

        # Configuration remains closed to the same actor, server-side.
        assert world.client.post("/api/talent/programs", json={"name": "Branch Duplicate"}).status_code == 403
        assert world.client.patch(f"/api/talent/programs/{program.id}", json={"name": "Renamed"}).status_code == 403
        assert world.client.post("/api/talent/assessment-cycles", json={}).status_code == 403
        world.db.expire_all()
        assert world.db.query(models.TalentProgram).filter_by(name="Branch Duplicate").count() == 0
    finally:
        world.close()
