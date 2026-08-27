from datetime import datetime

import pytest

import models
from timetable_version_service import (
    TimetableVersionError,
    create_manual_draft,
    delete_unused_timetable_version,
    move_or_swap_timetable_entry,
    set_imported_active_pointer,
)
from test_timetable_versioning import db  # noqa: F401


def _version(db, *, origin="manual"):
    return create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin=origin
    )


def _entry(db, version, *, section=2000, teacher=1000, day="monday", period=1, locked=False):
    row = models.TimetableEntry(
        timetable_version_id=version.id, branch_id=10, academic_year_id=100,
        planning_section_id=section, subject_code="MAT", teacher_id=teacher,
        day_key=day, period_index=period, is_locked=locked,
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("origin", ["generated", "regenerated", "imported", "manual"])
def test_unused_candidate_can_be_permanently_deleted_without_changing_active_pointer(db, origin):
    active = _version(db, origin="imported")
    active.lifecycle_status = "publication_ready"
    set_imported_active_pointer(db, version=active)
    candidate = _version(db, origin=origin)
    entry = _entry(db, candidate)
    candidate_id, entry_id = candidate.id, entry.id

    delete_unused_timetable_version(
        db, version_id=candidate.id, school_group_id=1, branch_id=10,
        academic_year_id=100,
    )

    assert db.get(models.TimetableVersion, candidate_id) is None
    assert db.get(models.TimetableEntry, entry_id) is None
    assert db.query(models.TimetableActiveVersion).one().timetable_version_id == active.id


def test_active_and_previously_published_history_cannot_be_deleted(db):
    active = _version(db, origin="imported")
    active.lifecycle_status = "publication_ready"
    active.published_at = datetime.utcnow()
    set_imported_active_pointer(db, version=active)
    with pytest.raises(TimetableVersionError) as current:
        delete_unused_timetable_version(
            db, version_id=active.id, school_group_id=1, branch_id=10,
            academic_year_id=100,
        )
    assert current.value.code == "published_delete_forbidden"

    historical = _version(db, origin="generated")
    historical.lifecycle_status = "archived"
    historical.published_at = datetime.utcnow()
    with pytest.raises(TimetableVersionError) as prior:
        delete_unused_timetable_version(
            db, version_id=historical.id, school_group_id=1, branch_id=10,
            academic_year_id=100,
        )
    assert prior.value.code == "published_history_delete_forbidden"


def test_move_to_empty_valid_slot_increments_revision(db):
    version = _version(db)
    lesson = _entry(db, version)
    action = move_or_swap_timetable_entry(
        db, version=version, entry_id=lesson.id, destination_section_id=2000,
        destination_day_key="tuesday", destination_period_index=2,
        expected_edit_revision=0,
    )
    assert action == "moved"
    assert (lesson.day_key, lesson.period_index) == ("tuesday", 2)
    assert version.edit_revision == 1
    assert version.lifecycle_status == "draft"


def test_teacher_conflict_and_locked_lesson_are_rejected(db):
    version = _version(db)
    lesson = _entry(db, version)
    _entry(db, version, section=2001, teacher=1000, day="tuesday", period=2)
    with pytest.raises(TimetableVersionError) as conflict:
        move_or_swap_timetable_entry(
            db, version=version, entry_id=lesson.id, destination_section_id=2000,
            destination_day_key="tuesday", destination_period_index=2,
        )
    assert conflict.value.code == "teacher_collision"
    assert (lesson.day_key, lesson.period_index) == ("monday", 1)

    lesson.is_locked = True
    db.flush()
    with pytest.raises(TimetableVersionError) as locked:
        move_or_swap_timetable_entry(
            db, version=version, entry_id=lesson.id, destination_section_id=2000,
            destination_day_key="tuesday", destination_period_index=3,
        )
    assert locked.value.code == "locked_lesson"


def test_non_teaching_destination_and_published_version_are_rejected(db):
    version = _version(db)
    lesson = _entry(db, version)
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    db.add(models.TimetableNonTeachingBlock(
        timetable_setting_id=setting.id, block_type="break", label="Break",
        day_key="tuesday", start_time="08:40", end_time="09:20",
        start_period=2, end_period=2,
    ))
    db.flush()
    with pytest.raises(TimetableVersionError) as blocked:
        move_or_swap_timetable_entry(
            db, version=version, entry_id=lesson.id, destination_section_id=2000,
            destination_day_key="tuesday", destination_period_index=2,
        )
    assert blocked.value.code == "non_teaching_period"

    db.rollback()
    version = _version(db, origin="imported")
    version.lifecycle_status = "publication_ready"
    lesson = _entry(db, version)
    set_imported_active_pointer(db, version=version)
    with pytest.raises(TimetableVersionError) as published:
        move_or_swap_timetable_entry(
            db, version=version, entry_id=lesson.id, destination_section_id=2000,
            destination_day_key="tuesday", destination_period_index=2,
        )
    assert published.value.code == "immutable_active_version"


def test_valid_swap_succeeds_and_invalid_swap_changes_neither_lesson(db):
    version = _version(db)
    first = _entry(db, version, teacher=1000, day="monday", period=1)
    second = _entry(db, version, teacher=1001, day="monday", period=2)
    assert move_or_swap_timetable_entry(
        db, version=version, entry_id=first.id, destination_section_id=2000,
        destination_day_key="monday", destination_period_index=2,
    ) == "swapped"
    assert (first.period_index, second.period_index) == (2, 1)

    third = _entry(db, version, section=2001, teacher=1001, day="tuesday", period=2)
    first.day_key, first.period_index = "tuesday", 2
    second.day_key, second.period_index = "tuesday", 3
    db.flush()
    before = ((first.day_key, first.period_index), (second.day_key, second.period_index))
    with pytest.raises(TimetableVersionError) as invalid:
        move_or_swap_timetable_entry(
            db, version=version, entry_id=first.id, destination_section_id=2000,
            destination_day_key="tuesday", destination_period_index=3,
            expected_edit_revision=version.edit_revision,
        )
    assert invalid.value.code == "teacher_collision"
    assert ((first.day_key, first.period_index), (second.day_key, second.period_index)) == before
    assert (third.day_key, third.period_index) == ("tuesday", 2)


def test_main_ui_history_drag_drop_and_publish_confirmation_language():
    template = open("templates/timetable.html", encoding="utf-8").read()
    assert 'version-select{% if not history_mode %} is-hidden{% endif %}' in template
    assert 'href="/timetable?history=1">Timetable History' in template
    assert 'historyMode && canArchiveVersions' in template
    assert 'addButton("Delete Timetable"' in template
    assert '!version.is_active && !version.was_published' in template
    assert 'dialog.assignment-panel:not([open]) { display: none; }' in template
    assert '<h4 id="publishDialogTitle">Confirm timetable action</h4>' in template
    assert 'id="publishConfirmBtn">Continue</button>' in template
    assert 'className = `inspector-btn ${destructive ? "is-danger" : "is-primary"}`' in template
    assert 'title: "Delete this timetable?"' in template
    assert 'message: "This timetable will be permanently removed. This action cannot be undone."' in template
    assert 'openConfirmation({' in template
    assert 'id="workspaceExportXlsx"' in template
    assert 'id="workspaceExportPdf"' in template
    assert '/versions/${encodeURIComponent(version.public_id)}/export.xlsx' in template
    assert '/versions/${encodeURIComponent(version.public_id)}/export.pdf' in template
    assert 'button.draggable = true' in template
    assert 'addEventListener("drop"' in template
    for text in (
        "Publish this timetable?", "Replace the published timetable?",
        "Publish to Users", "Replace & Publish to Users",
        "Published to Users", "Official timetable currently visible to authorized users.",
    ):
        assert text in template
    assert 'publishDialog.showModal()' in template
    assert 'publishConfirmBtn.addEventListener("click"' in template
