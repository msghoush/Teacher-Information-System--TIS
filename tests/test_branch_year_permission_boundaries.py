"""Focused mixed-action and tenant-scope permission qualification."""

import os

os.environ["TIS_SESSION_SECRET"] = "branch-year-permission-test-secret-long-enough"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import auth
import main
import models
import role_permission_service


@pytest.fixture
def scope():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    school = models.SchoolGroup(name="School A", status=True)
    other = models.SchoolGroup(name="School B", status=True)
    db.add_all([school, other])
    db.flush()
    branch = models.Branch(name="Main A", school_group_id=school.id, status=True)
    spare = models.Branch(name="Spare A", school_group_id=school.id, status=True)
    foreign_branch = models.Branch(name="Main B", school_group_id=other.id, status=True)
    db.add_all([branch, spare, foreign_branch])
    db.flush()
    year = models.AcademicYear(school_group_id=school.id, year_name="2026-2027", is_active=True)
    next_year = models.AcademicYear(school_group_id=school.id, year_name="2027-2028", is_active=False)
    foreign_year = models.AcademicYear(school_group_id=other.id, year_name="2026-2027", is_active=True)
    db.add_all([year, next_year, foreign_year])
    db.flush()
    actor = models.User(
        user_id="1001", username="branch_year_admin", first_name="Test", last_name="Admin",
        role=auth.ROLE_ADMINISTRATOR, position="Principal",
        password=auth.get_password_hash("password123"),
        school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id,
        access_scope="ORGANIZATION", is_active=True,
    )
    db.add(actor)
    db.commit()
    try:
        yield db, actor, school, other, branch, spare, foreign_branch, year, next_year, foreign_year
    finally:
        db.close()
        engine.dispose()


def _request(path, actor):
    cookie = f"{auth.SESSION_COOKIE_KEY}={auth.create_session_token(actor)}; branch_id={actor.branch_id}; academic_year_id={actor.academic_year_id}"
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [
            (b"host", b"testserver"), (b"cookie", cookie.encode()),
            (b"accept", b"application/json"),
        ],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("testclient", 50000), "root_path": "", "app": main.app,
    })


def _grant_only(db, actor, school, keys):
    baseline = role_permission_service.get_allowed_permission_keys(
        db, actor.role, school.id,
    )
    bounded = {"branches.edit", "branches.activate_deactivate", "academic_years.create", "academic_years.activate"}
    role_permission_service.apply_role_permission_overrides(
        db, role=actor.role, allowed_keys=(baseline - bounded) | set(keys),
        school_group_id=school.id, updated_by_user_id=actor.user_id,
    )
    db.commit()
    actor._permission_cache = {}


def _update(db, actor, branch, *, name, status):
    # Call the route function directly (bypassing the HTTP/Form layer), so every
    # Form(...) parameter must be given an explicit plain value; an omitted
    # parameter's Python default is the FastAPI `Form()` sentinel object itself
    # (not an empty string), which corrupts change-detection/location-resolution
    # logic that assumes a real string.
    return main.update_branch(
        branch_id=branch.id,
        request=_request(f"/system-configuration/branches/{branch.id}", actor),
        name=name,
        region="",
        country_code="",
        region_id="",
        region_manual="",
        city_id="",
        city_manual="",
        district_name="",
        neighborhood_name="",
        status=status,
        return_to="/system-configuration/branches",
        db=db,
    )


def test_edit_only_can_rename_but_cannot_change_branch_status(scope):
    db, actor, school, _, branch, _, _, _, _, _ = scope
    _grant_only(db, actor, school, {"branches.edit"})
    allowed = _update(db, actor, branch, name="Renamed A", status="active")
    assert allowed.status_code == 302
    db.refresh(branch)
    assert branch.name == "Renamed A" and branch.status is True
    denied = _update(db, actor, branch, name="Unauthorized Rename", status="inactive")
    assert denied.status_code == 403
    db.refresh(branch)
    assert branch.name == "Renamed A" and branch.status is True


def test_status_only_can_toggle_but_cannot_rename_branch(scope):
    db, actor, school, _, branch, _, _, _, _, _ = scope
    _grant_only(db, actor, school, {"branches.activate_deactivate"})
    allowed = _update(db, actor, branch, name="Main A", status="inactive")
    assert allowed.status_code == 302
    db.refresh(branch)
    assert branch.name == "Main A" and branch.status is False
    denied = _update(db, actor, branch, name="Unauthorized Rename", status="inactive")
    assert denied.status_code == 403
    db.refresh(branch)
    assert branch.name == "Main A" and branch.status is False


@pytest.mark.parametrize("keys", [{"branches.edit"}, {"branches.activate_deactivate"}, {"branches.edit", "branches.activate_deactivate"}])
def test_branch_update_never_crosses_school_group(scope, keys):
    db, actor, school, _, _, _, foreign_branch, _, _, _ = scope
    _grant_only(db, actor, school, keys)
    response = _update(db, actor, foreign_branch, name="Foreign Changed", status="inactive")
    assert response.status_code == 403
    db.refresh(foreign_branch)
    assert foreign_branch.name == "Main B" and foreign_branch.status is True


@pytest.mark.parametrize("keys", [{"academic_years.create"}, {"academic_years.activate"}, set()])
def test_open_year_requires_both_create_and_activate(scope, keys):
    db, actor, school, _, _, _, _, year, _, _ = scope
    _grant_only(db, actor, school, keys)
    response = main.open_new_academic_year(
        request=_request("/developer/open-academic-year", actor),
        year_name="2028-2029", school_group_id=school.id, db=db,
    )
    assert response.status_code in (302, 403)
    assert db.query(models.AcademicYear).filter_by(school_group_id=school.id, year_name="2028-2029").count() == 0
    db.refresh(year)
    assert year.is_active is True


def test_open_year_with_both_grants_is_scoped_to_own_school_group(scope):
    db, actor, school, other, _, _, _, year, _, foreign_year = scope
    _grant_only(db, actor, school, {"academic_years.create", "academic_years.activate"})
    forged = main.open_new_academic_year(
        request=_request("/developer/open-academic-year", actor),
        year_name="2028-2029", school_group_id=other.id, db=db,
    )
    assert forged.status_code == 403
    assert db.query(models.AcademicYear).filter_by(school_group_id=other.id, year_name="2028-2029").count() == 0
    db.refresh(foreign_year)
    assert foreign_year.is_active is True
    allowed = main.open_new_academic_year(
        request=_request("/developer/open-academic-year", actor),
        year_name="2028-2029", school_group_id=school.id, db=db,
    )
    assert allowed.status_code == 302
    opened = db.query(models.AcademicYear).filter_by(school_group_id=school.id, year_name="2028-2029").one()
    db.refresh(year)
    assert opened.is_active is True and year.is_active is False
    db.refresh(foreign_year)
    assert foreign_year.is_active is True


def test_current_year_activate_only_allows_own_year_not_foreign(scope):
    db, actor, school, _, _, _, _, year, next_year, foreign_year = scope
    _grant_only(db, actor, school, {"academic_years.activate"})
    foreign = main.set_current_year(
        request=_request("/admin/current-year", actor),
        academic_year_id=foreign_year.id, db=db,
    )
    assert foreign.status_code == 403
    db.refresh(year)
    db.refresh(foreign_year)
    assert year.is_active is True and foreign_year.is_active is True
    own = main.set_current_year(
        request=_request("/admin/current-year", actor),
        academic_year_id=next_year.id, db=db,
    )
    assert own.status_code == 302
    db.refresh(year)
    db.refresh(next_year)
    db.refresh(foreign_year)
    assert year.is_active is False and next_year.is_active is True and foreign_year.is_active is True


def test_current_year_create_only_cannot_activate(scope):
    db, actor, school, _, _, _, _, year, next_year, _ = scope
    _grant_only(db, actor, school, {"academic_years.create"})
    response = main.set_current_year(
        request=_request("/admin/current-year", actor),
        academic_year_id=next_year.id, db=db,
    )
    assert response.status_code in (302, 403)
    db.refresh(year)
    db.refresh(next_year)
    assert year.is_active is True and next_year.is_active is False
