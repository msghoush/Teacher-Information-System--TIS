"""Dedicated Teacher action authority and preservation of omitted read-only fields."""
import os

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

os.environ.setdefault("TIS_SESSION_SECRET", "teacher-field-permission-test-secret-long-enough")
import models
import auth
from routers import teachers


@pytest.fixture
def seeded(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(models.SchoolGroup(id=1, name="School", status=True))
    db.add(models.Branch(id=1, name="Branch", school_group_id=1, status=True))
    db.add(models.AcademicYear(id=1, school_group_id=1, year_name="2026-2027", is_active=True))
    db.add(models.User(user_id="901", username="review_actor", password="unused-test-only",
                       role=auth.ROLE_ADMINISTRATOR, is_active=True, school_group_id=1,
                       branch_id=1, academic_year_id=1, position="Principal"))
    teacher = models.Teacher(teacher_id="123", first_name="First", last_name="Last",
                             branch_id=1, academic_year_id=1, subject_code="ENG",
                             max_hours=24, extra_hours_allowed=True, extra_hours_count=2,
                             teaches_national_section=False, national_section_hours=0,
                             is_new_teacher=True)
    db.add(teacher)
    db.flush()
    allocation = models.TeacherSubjectAllocation(teacher_id=teacher.id, subject_code="ENG", compatibility_override=True)
    db.add(allocation)
    db.commit()
    monkeypatch.setattr(teachers, "_get_teacher_qualification_map", lambda *args: {teacher.id: {"keys": ["degree_one"]}})
    monkeypatch.setattr(teachers, "_get_teacher_section_assignment_values", lambda *args: ["ENG:10"])
    try:
        yield db, teacher
    finally:
        db.close()
        engine.dispose()


def omitted():
    return dict.fromkeys(("qualification_keys", "qualification_override_subject_codes", "subject_codes",
                          "section_assignment_values", "max_hours", "extra_hours_allowed", "extra_hours_count",
                          "teaches_national_section", "national_section_hours", "is_new_teacher"))


def actor_with_grants(db, granted=()):
    keys = ("teachers.assign_subjects", "teachers.manage_qualifications", "teachers.manage_capacity",
            "teachers.delete", "teachers.bulk_delete", "teachers.edit")
    for key in keys:
        db.add(models.RolePermission(role=auth.ROLE_ADMINISTRATOR, school_group_id=1,
                                     permission_key=key, is_allowed=key in granted))
    db.commit()
    actor = db.query(models.User).one()
    actor.scope_branch_id, actor.scope_academic_year_id, actor.scope_school_group_id = 1, 1, 1
    return actor


@pytest.mark.parametrize("field,value,key", [
    ("subject_codes", ["MAT"], "teachers.assign_subjects"),
    ("qualification_override_subject_codes", [], "teachers.assign_subjects"),
    ("section_assignment_values", [], "teachers.assign_subjects"),
    ("qualification_keys", [], "teachers.manage_qualifications"),
    ("max_hours", "20", "teachers.manage_capacity"),
    ("extra_hours_allowed", "", "teachers.manage_capacity"),
    ("extra_hours_count", "3", "teachers.manage_capacity"),
    ("teaches_national_section", "on", "teachers.manage_capacity"),
    ("national_section_hours", "1", "teachers.manage_capacity"),
    ("is_new_teacher", "", "teachers.manage_capacity"),
])
def test_changed_field_requires_its_dedicated_permission(seeded, monkeypatch, field, value, key):
    db, teacher = seeded
    submitted = omitted()
    submitted[field] = value
    actor = actor_with_grants(db)
    assert teachers._protect_teacher_update_fields(db, actor, teacher, submitted) == key
    assert teacher.max_hours == 24
    assert db.query(models.TeacherSubjectAllocation).one().subject_code == "ENG"


def test_omitted_denied_fields_restore_original_values(seeded, monkeypatch):
    db, teacher = seeded
    submitted = omitted()
    actor = actor_with_grants(db)
    assert teachers._protect_teacher_update_fields(db, actor, teacher, submitted) is None
    assert submitted["subject_codes"] == ["ENG"]
    assert submitted["qualification_keys"] == ["degree_one"]
    assert submitted["qualification_override_subject_codes"] == ["ENG"]
    assert submitted["section_assignment_values"] == ["ENG:10"]
    assert submitted["extra_hours_allowed"] == "on"
    assert submitted["extra_hours_count"] == 2


def test_unchanged_denied_fields_are_allowed(seeded, monkeypatch):
    db, teacher = seeded
    actor = actor_with_grants(db)
    submitted = omitted()
    submitted.update(subject_codes=["eng"], max_hours="24", extra_hours_count="2")
    assert teachers._protect_teacher_update_fields(db, actor, teacher, submitted) is None


@pytest.mark.parametrize("granted", ["teachers.assign_subjects", "teachers.manage_qualifications", "teachers.manage_capacity"])
def test_matching_grant_allows_field_change(seeded, monkeypatch, granted):
    db, teacher = seeded
    actor = actor_with_grants(db, {granted})
    submitted = omitted()
    field, value = {"teachers.assign_subjects": ("subject_codes", ["MAT"]),
                    "teachers.manage_qualifications": ("qualification_keys", ["degree_two"]),
                    "teachers.manage_capacity": ("max_hours", "20")}[granted]
    submitted[field] = value
    assert teachers._protect_teacher_update_fields(db, actor, teacher, submitted) is None
    assert submitted[field] == value


def test_single_delete_grant_cannot_bulk_delete(seeded, monkeypatch):
    db, teacher = seeded
    actor = actor_with_grants(db, {"teachers.delete"})
    monkeypatch.setattr(teachers, "get_current_user", lambda *args: actor)
    request = Request({"type": "http", "method": "POST", "path": "/teachers/delete-bulk", "headers": []})
    response = teachers.delete_teachers_bulk(request, [teacher.id], db)
    assert response.status_code == 302
    assert db.query(models.Teacher).count() == 1


def test_bulk_grant_without_single_delete_can_bulk_delete(seeded, monkeypatch):
    db, teacher = seeded
    actor = actor_with_grants(db, {"teachers.bulk_delete"})
    monkeypatch.setattr(teachers, "get_current_user", lambda *args: actor)
    monkeypatch.setattr(teachers, "_render_teachers_page", lambda **kwargs: JSONResponse({"ok": True}))
    request = Request({"type": "http", "method": "POST", "path": "/teachers/delete-bulk", "headers": []})
    assert teachers.delete_teachers_bulk(request, [teacher.id], db).status_code == 200
    assert db.query(models.Teacher).count() == 0


def test_profile_only_update_preserves_protected_data_and_relationship_ids(seeded, monkeypatch):
    db, teacher = seeded
    allocation_id = db.query(models.TeacherSubjectAllocation).one().id
    actor = actor_with_grants(db, {"teachers.edit"})
    monkeypatch.setattr(teachers, "get_current_user", lambda *args: actor)
    monkeypatch.setattr(teachers, "_render_teachers_page", lambda **kwargs: JSONResponse({"ok": True}))
    request = Request({"type": "http", "method": "POST", "path": "/teachers/edit/1", "headers": []})
    response = teachers.update_teacher(request, teacher.id, teacher_id="123", first_name="Updated", middle_name="", last_name="Last", db=db, **omitted())
    assert response.status_code == 200
    assert teacher.first_name == "Updated"
    assert teacher.max_hours == 24
    assert teacher.extra_hours_allowed is True
    assert teacher.extra_hours_count == 2
    assert teacher.is_new_teacher is True
    assert db.query(models.TeacherSubjectAllocation).one().id == allocation_id


def test_edit_template_disables_protected_controls_without_hiding_data(seeded):
    from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
    import re
    _, teacher = seeded
    # Render the shipping content; omit unrelated application shell/scripts.
    environment = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"}),
        FileSystemLoader("templates"),
    ]))
    template = environment.get_template("edit_teacher.html")
    source = FileSystemLoader("templates").get_source(environment, "edit_teacher.html")[0]
    assert "extraCountInput.disabled = !canManageCapacity || !enabled" in source
    assert "nationalSectionHoursInput.disabled = !canManageCapacity || !enabled" in source
    assert "if (!canModifyWorkload)" in source
    for granted in (False, True):
        html = template.render(teacher=teacher, selected_qualification_keys=[], qualification_option_groups=[],
                               can_assign_subjects=granted, can_manage_qualifications=granted,
                               can_manage_capacity=granted)
        fieldsets = re.findall(r"<fieldset[^>]*>", html)
        assert len(fieldsets) == 2
        assert all(("disabled" in tag) == (not granted) for tag in fieldsets)
        for name in ("max_hours", "extra_hours_allowed", "extra_hours_count", "teaches_national_section", "national_section_hours", "is_new_teacher"):
            tag = re.search(r'<input[^>]*name="' + name + r'"[^>]*>', html).group()
            assert ("disabled" in tag) == (not granted)
        assert 'value="24"' in html
        assert 'value="First"' in html


def test_user_deny_overrides_role_grant_for_capacity(seeded):
    db, teacher = seeded
    actor = db.query(models.User).one()
    db.add(models.UserPermissionOverride(user_id=actor.id, school_group_id=1,
                                         permission_key="teachers.manage_capacity", is_allowed=False))
    db.commit()
    submitted = omitted()
    submitted["max_hours"] = "20"
    assert teachers._protect_teacher_update_fields(db, actor, teacher, submitted) == "teachers.manage_capacity"
