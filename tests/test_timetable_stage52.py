from types import SimpleNamespace

import models
from timetable_version_service import (
    TimetableVersionError,
    create_manual_draft,
    discard_working_version,
    set_imported_active_pointer,
)
from timetable_visibility_service import (
    build_published_timetable_payload,
    resolve_scoped_teacher,
)
from test_timetable_versioning import db  # noqa: F401


def _published_with_lesson(db):
    version = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported"
    )
    version.lifecycle_status = "publication_ready"
    db.add(models.TimetableEntry(
        timetable_version_id=version.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    db.flush()
    set_imported_active_pointer(db, version=version)
    db.flush()
    return version


def test_delete_working_archives_history_and_preserves_published_pointer(db):
    published = _published_with_lesson(db)
    working = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        origin="generated", source_version_id=published.id,
    )
    entry = models.TimetableEntry(
        timetable_version_id=working.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="tuesday", period_index=1,
    )
    db.add(entry); db.flush()
    discard_working_version(
        db, version_id=working.id, school_group_id=1, branch_id=10,
        academic_year_id=100, actor_user_id="U1",
    )
    pointer = db.query(models.TimetableActiveVersion).one()
    assert pointer.timetable_version_id == published.id
    assert working.lifecycle_status == "archived"
    assert db.get(models.TimetableEntry, entry.id) is not None


def test_delete_working_never_deletes_published(db):
    published = _published_with_lesson(db)
    try:
        discard_working_version(
            db, version_id=published.id, school_group_id=1, branch_id=10,
            academic_year_id=100, actor_user_id="U1",
        )
    except TimetableVersionError as exc:
        assert exc.code == "working_version_changed"
    else:
        raise AssertionError("published timetable deletion must fail")


def test_my_timetable_uses_only_active_version_and_own_lessons(db):
    published = _published_with_lesson(db)
    db.add(models.TimetableEntry(
        timetable_version_id=published.id, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT", teacher_id=1001,
        day_key="monday", period_index=2,
    ))
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="generated"
    )
    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="friday", period_index=4,
    ))
    db.flush()
    teacher = resolve_scoped_teacher(
        db, user=SimpleNamespace(user_id="T1"), branch_id=10, academic_year_id=100
    )
    payload = build_published_timetable_payload(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=teacher.id,
    )
    assert payload["published"] is True
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["day_key"] == "monday"
    assert all("version" not in key for key in payload)


def test_published_view_empty_without_active_pointer(db):
    payload = build_published_timetable_payload(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    assert payload["published"] is False
    assert payload["entries"] == []


def test_stage52_customer_language_and_permissions():
    template = open("templates/timetable.html", encoding="utf-8").read()
    published = open("templates/published_timetable.html", encoding="utf-8").read()
    permissions = open("permission_registry.py", encoding="utf-8").read()
    for label in ("Check Timetable", "Working Timetable", "Ready to Publish", "Published", "Timetable History", "Delete Working Timetable"):
        assert label in template or label in published
    assert "Validate Draft" not in template
    assert "timetable.delete_working" in permissions
