"""Independent regression cases using persisted policy and the canonical resolver."""
import asyncio
import os
from urllib.parse import urlencode

os.environ.setdefault("TIS_SESSION_SECRET", "independent-review-secret-long-enough-for-tests")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request
from fastapi.responses import JSONResponse

import auth
import main
import models
import ui_shell
import user_permission_service
from routers import observations, planning, users


@pytest.fixture
def scope():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    school = models.SchoolGroup(name="Review school", status=True)
    db.add(school)
    db.flush()
    branch = models.Branch(name="Review branch", school_group_id=school.id, status=True)
    year = models.AcademicYear(school_group_id=school.id, year_name="2026-2027", is_active=True)
    db.add_all([branch, year])
    db.flush()
    actor = models.User(user_id="7001", username="review_actor", password="unused",
                        role=auth.ROLE_ADMINISTRATOR, position="Principal", is_active=True,
                        school_group_id=school.id, branch_id=branch.id, academic_year_id=year.id)
    db.add(actor)
    db.commit()
    try:
        yield db, actor
    finally:
        db.close()
        engine.dispose()


def request(path, actor, form=None):
    body = urlencode(form or {}).encode()
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST" if form is not None else "GET",
                    "path": path, "query_string": b"", "scheme": "http",
                    "headers": [(b"host", b"testserver"),
                                (b"content-type", b"application/x-www-form-urlencoded"),
                                (b"accept", b"application/json")],
                    "server": ("testserver", 80), "client": ("testclient", 123),
                    "app": main.app}, receive)


def deny(db, actor, key):
    db.add(models.RolePermission(school_group_id=actor.school_group_id,
                                role=actor.role, permission_key=key, is_allowed=False))
    db.commit()


@pytest.mark.parametrize("platform_role", [auth.PLATFORM_ROLE_OWNER, auth.PLATFORM_ROLE_DEVELOPER])
def test_inactive_platform_helpers_fail_closed(scope, platform_role):
    db, actor = scope
    actor.user_type = auth.USER_TYPE_PLATFORM
    actor.platform_role = platform_role
    actor.is_active = False
    assert auth.get_allowed_permission_keys(db, actor) == set()
    assert not auth.can_modify_data(db, actor)
    assert not auth.can_access_all_years(actor, db)


def test_developer_role_choices_require_real_assign_role_grant(scope):
    db, actor = scope
    actor.user_type = auth.USER_TYPE_PLATFORM
    actor.platform_role = auth.PLATFORM_ROLE_DEVELOPER
    actor.platform_permissions_initialized = True
    db.add(models.PlatformUserPermission(platform_user_id=actor.id,
                                         permission_key="users.create", is_allowed=True))
    db.commit()
    assert users._get_user_roles_for_creator(db, actor) == [auth.ROLE_LIMITED]
    db.add(models.PlatformUserPermission(platform_user_id=actor.id,
                                         permission_key="users.assign_role", is_allowed=True))
    db.commit()
    assert auth.ROLE_ADMINISTRATOR in users._get_user_roles_for_creator(db, actor)


@pytest.mark.parametrize("invalid_scope", ["missing", "orphan_parent", "conflicting_branch", "foreign_selected", "foreign_explicit"])
def test_tenant_resolver_fails_closed_on_ambiguous_or_foreign_ownership(scope, invalid_scope):
    db, actor = scope
    other = models.SchoolGroup(name="Other review school", status=True)
    db.add(other)
    db.flush()
    explicit_scope = None
    if invalid_scope == "missing":
        actor.school_group_id = actor.branch_id = None
    elif invalid_scope == "orphan_parent":
        actor.school_group_id, actor.branch_id = 999, None
    elif invalid_scope == "conflicting_branch":
        foreign_branch = models.Branch(name="Other review branch", school_group_id=other.id, status=True)
        db.add(foreign_branch)
        db.flush()
        actor.branch_id = foreign_branch.id
    elif invalid_scope == "foreign_selected":
        actor.scope_school_group_id = other.id
    else:
        explicit_scope = other.id
    db.commit()
    assert auth.get_allowed_permission_keys(db, actor, explicit_scope) == set()


def test_platform_management_and_override_write_reject_contradictory_target_owner(scope):
    db, target = scope
    other = models.SchoolGroup(name="Contradictory target school", status=True)
    db.add(other)
    db.flush()
    branch = models.Branch(name="Contradictory target branch", school_group_id=other.id, status=True)
    db.add(branch)
    db.flush()
    target.branch_id = branch.id
    owner = models.User(user_id="7002", username="review_owner", password="unused",
        user_type=auth.USER_TYPE_PLATFORM, platform_role=auth.PLATFORM_ROLE_OWNER, is_active=True)
    db.add(owner)
    db.commit()
    assert not auth.can_manage_target_user_account(db, owner, target)
    with pytest.raises(ValueError, match="contradictory"):
        user_permission_service.apply_user_override(db, target_user=target,
            permission_key="subjects.view", decision="deny", school_group_id=target.school_group_id)
    assert db.query(models.UserPermissionOverride).count() == 0


def test_platform_branch_delete_rejects_unowned_target(scope, monkeypatch):
    db, actor = scope
    actor.user_type = auth.USER_TYPE_PLATFORM
    actor.platform_role = auth.PLATFORM_ROLE_OWNER
    orphan = models.Branch(name="Unowned review branch", school_group_id=None, status=False)
    db.add(orphan)
    db.commit()
    monkeypatch.setattr(main.auth, "get_current_user", lambda *args: actor)
    response = main.delete_branch(orphan.id, request("/system-configuration/branches/1/delete", actor),
                                  return_to="/system-configuration/branches", db=db)
    assert response.status_code == 403
    assert db.get(models.Branch, orphan.id) is not None


@pytest.mark.parametrize("decision", ["inherit", "deny", "allow"])
def test_notification_open_respects_persisted_user_mark_read_override(scope, monkeypatch, decision):
    db, actor = scope
    notification = models.SystemNotification(school_group_id=actor.school_group_id,
        recipient_user_id=actor.user_id, request_type="Message", title="Review", status="New")
    db.add(notification)
    if decision != "inherit":
        db.add(models.UserPermissionOverride(user_id=actor.id, school_group_id=actor.school_group_id,
                                             permission_key="notifications.mark_read", is_allowed=decision == "allow"))
    db.commit()
    monkeypatch.setattr(main.auth, "get_current_user", lambda *args: actor)
    # Isolate the unrelated global-engine normalizer and presentation only.
    monkeypatch.setattr(main, "_ensure_system_notifications_table_columns", lambda: None)
    monkeypatch.setattr(main, "build_shell_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(main.templates, "TemplateResponse", lambda *args, **kwargs: JSONResponse({"ok": True}))
    response = main.notification_detail(notification.id, request("/notifications/1", actor), db)
    assert response.status_code == 200
    db.expire_all()
    assert db.get(models.SystemNotification, notification.id).status == ("New" if decision == "deny" else "Seen")


@pytest.mark.parametrize("granted_type,posted_type", [("Formal", "Non-formal"), ("Non-formal", "Formal")])
def test_observation_forged_sibling_type_denied_before_mutation(scope, monkeypatch, granted_type, posted_type):
    db, actor = scope
    denied_key = "observations.create_non_formal" if posted_type == "Non-formal" else "observations.create_formal"
    deny(db, actor, denied_key)
    monkeypatch.setattr(observations, "get_current_user", lambda *args: actor)
    response = asyncio.run(observations.create_observation(
        request("/observations/new", actor, {"observation_type": posted_type}), db))
    assert response.status_code == 302
    assert db.query(models.Observation).count() == 0
    assert observations._can_create_observation_type(db, actor, granted_type)


@pytest.mark.parametrize("key,kwargs", [
    ("planning.manage_homeroom", {"homeroom_teacher_id": "9"}),
    ("planning.assign_teacher", {"assignment_subject_codes": ["ENG"], "assignment_teacher_ids": ["9"]}),
])
def test_planning_edit_cannot_bypass_dedicated_field_deny(scope, monkeypatch, key, kwargs):
    db, actor = scope
    section = models.PlanningSection(branch_id=actor.branch_id, academic_year_id=actor.academic_year_id,
                                    grade_level="Grade 3", section_name="A", class_status="Current")
    db.add(section)
    db.commit()
    deny(db, actor, key)
    monkeypatch.setattr(planning, "get_current_user", lambda *args: actor)
    values = {"homeroom_teacher_id": "", "assignment_subject_codes": [],
              "assignment_teacher_ids": [], "qualification_override": ""}
    values.update(kwargs)
    response = planning.update_planning_section(request("/planning/edit/1", actor), section.id,
        "Grade 3", "A", "Current", db=db, **values)
    assert response.status_code == 403
    db.refresh(section)
    assert section.homeroom_teacher_id is None
    assert db.query(models.TeacherSectionAssignment).count() == 0


@pytest.mark.parametrize("key", ["timetable.manage_teacher_rules", "timetable.manage_blocks"])
def test_configuration_navigation_with_only_independent_timetable_key(key):
    nav = ui_shell._build_nav_items(current_path="/system-configuration",
        can=lambda candidate: candidate == key,
        can_any=lambda *candidates: key in candidates)
    assert "/system-configuration" in {item["href"] for item in nav}


def test_planning_edit_preserves_omitted_readonly_homeroom_and_assignment_rows(scope, monkeypatch):
    db, actor = scope
    teacher = models.Teacher(teacher_id="8001", first_name="Review", last_name="Teacher",
        branch_id=actor.branch_id, academic_year_id=actor.academic_year_id, max_hours=24)
    subject = models.Subject(subject_code="ENG", subject_name="English", grade=3, weekly_hours=2,
        branch_id=actor.branch_id, academic_year_id=actor.academic_year_id)
    db.add_all([teacher, subject])
    db.flush()
    section = models.PlanningSection(branch_id=actor.branch_id, academic_year_id=actor.academic_year_id,
                                    grade_level="3", section_name="A", class_status="Current",
                                    homeroom_teacher_id=teacher.id)
    db.add(section)
    db.flush()
    assignment = models.TeacherSectionAssignment(teacher_id=teacher.id,
                                                 planning_section_id=section.id, subject_code="ENG")
    db.add(assignment)
    db.commit()
    original_id = assignment.id
    deny(db, actor, "planning.manage_homeroom")
    deny(db, actor, "planning.assign_teacher")
    monkeypatch.setattr(planning, "get_current_user", lambda *args: actor)
    monkeypatch.setattr(planning, "_get_teacher_subject_option_map", lambda **kwargs: {"ENG": [{"id": teacher.id}]})
    monkeypatch.setattr(planning, "_build_assignment_alignment_warnings", lambda **kwargs: [])
    monkeypatch.setattr(planning, "_render_planning_page", lambda **kwargs: JSONResponse({"ok": True}))
    response = planning.update_planning_section(request("/planning/edit/1", actor), section.id,
        "3", "A", "New", homeroom_teacher_id=None, assignment_subject_codes=[],
        assignment_teacher_ids=[], qualification_override="", db=db)
    assert response.status_code == 302
    assert response.headers["location"] == "/planning"
    db.refresh(section)
    assert section.class_status == "New"
    assert section.homeroom_teacher_id == teacher.id
    assert db.query(models.TeacherSectionAssignment).one().id == original_id
    forged_clear = planning.update_planning_section(request("/planning/edit/1", actor), section.id,
        "3", "A", "New", homeroom_teacher_id="", assignment_subject_codes=[],
        assignment_teacher_ids=[], qualification_override="", db=db)
    assert forged_clear.status_code == 403
    db.refresh(section)
    assert section.homeroom_teacher_id == teacher.id
