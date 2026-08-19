import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import models
from timetable_snapshot_service import build_current_snapshot_data
from timetable_version_service import (
    TimetableVersionError,
    archive_version,
    copy_version_to_draft,
    create_manual_draft,
    mutate_draft_placement,
    resolve_active_version,
    resolve_operational_version,
    resolve_version,
    set_entry_lock,
    set_imported_active_pointer,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add_all([
        models.SchoolGroup(id=1, name="Scope One"),
        models.SchoolGroup(id=2, name="Scope Two"),
    ])
    session.commit()
    session.add_all(
        [
            models.Branch(id=10, school_group_id=1, name="Main"),
            models.Branch(id=20, school_group_id=2, name="Other"),
            models.AcademicYear(id=100, school_group_id=1, year_name="2026"),
            models.AcademicYear(id=200, school_group_id=2, year_name="2026"),
        ]
    )
    session.commit()
    session.add_all(
        [
            models.User(
                user_id="U1", username="u1", first_name="Test", last_name="User",
                school_group_id=1, branch_id=10, academic_year_id=100,
            ),
            models.Teacher(
                id=1000, teacher_id="T1", first_name="A", last_name="Teacher",
                branch_id=10, academic_year_id=100,
            ),
            models.Teacher(
                id=1001, teacher_id="T2", first_name="Z", last_name="Teacher",
                branch_id=10, academic_year_id=100,
            ),
            models.PlanningSection(
                id=2000, grade_level="1", section_name="A", class_status="Current",
                branch_id=10, academic_year_id=100,
            ),
            models.PlanningSection(
                id=2001, grade_level="1", section_name="B", class_status="Current",
                branch_id=10, academic_year_id=100,
            ),
            models.Subject(
                id=3000, subject_code="MAT", subject_name="Mathematics",
                weekly_hours=4, grade=1, branch_id=10, academic_year_id=100,
            ),
            models.TeacherSectionAssignment(
                id=4000, teacher_id=1000, planning_section_id=2000, subject_code="MAT",
            ),
            models.TimetableSetting(
                id=5000, branch_id=10, academic_year_id=100,
                working_days_csv="monday,tuesday", periods_per_day=4,
                period_duration_minutes=45, school_start_time="08:00", school_end_time="11:00",
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_snapshot_is_deterministic_and_contains_no_display_names(db):
    first = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    second = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    assert first == second
    payload = json.loads(first.canonical_json)
    assert payload["planning"]["demands"][0]["required_weekly_periods"] == 4
    assert "A Teacher" not in first.canonical_json
    assert payload["future_extensions"] == {
        "rooms_resources": [],
        "teacher_availability": [],
    }
    db.query(models.Subject).filter_by(id=3000).one().weekly_hours = 5
    changed = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    assert changed.planning_fingerprint != first.planning_fingerprint
    assert changed.period_configuration_fingerprint == first.period_configuration_fingerprint
    assert changed.full_input_fingerprint != first.full_input_fingerprint


def test_snapshot_preserves_resolved_hrt_fallback_as_real_subject_demand(db):
    db.query(models.TeacherSectionAssignment).filter_by(id=4000).delete()
    db.query(models.PlanningSection).filter_by(id=2000).one().homeroom_teacher_id = 1000
    snapshot = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    demand = json.loads(snapshot.canonical_json)["planning"]["demands"][0]
    assert demand["subject_code"] == "MAT"
    assert demand["assigned_teacher_id"] == 1000
    assert demand["assignment_source"] == "homeroom_default"


def test_active_version_is_immutable_and_draft_copy_preserves_placements_and_locks(db):
    imported = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported"
    )
    imported.lifecycle_status = "publication_ready"
    entry = models.TimetableEntry(
        timetable_version_id=imported.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1, is_locked=True,
    )
    db.add(entry)
    db.flush()
    set_imported_active_pointer(db, version=imported)
    db.commit()

    with pytest.raises(TimetableVersionError, match="active timetable"):
        mutate_draft_placement(
            db, version=imported, planning_section_id=2000, day_key="monday",
            period_index=1, subject_code=None, teacher_id=None,
        )

    draft = copy_version_to_draft(db, source_version=imported)
    copied = db.query(models.TimetableEntry).filter_by(
        timetable_version_id=draft.id
    ).one()
    assert draft.origin == "imported"
    assert draft.source_version_id == imported.id
    assert copied.is_locked is True
    assert resolve_active_version(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    ).id == imported.id
    assert resolve_operational_version(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    ).id == draft.id


def test_draft_mutation_is_version_scoped_and_archive_blocks_future_edits(db):
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    placement = mutate_draft_placement(
        db, version=draft, planning_section_id=2000, day_key="monday",
        period_index=1, subject_code="MAT", teacher_id=1000,
    )
    assert placement.timetable_version_id == draft.id
    assert draft.edit_revision == 1
    archive_version(db, version=draft, actor_user_id=None)
    with pytest.raises(TimetableVersionError, match="cannot be edited"):
        mutate_draft_placement(
            db, version=draft, planning_section_id=2000, day_key="monday",
            period_index=1, subject_code=None, teacher_id=None,
        )


def test_lock_metadata_persists_and_superseded_version_is_immutable(db):
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        actor_user_id="U1",
    )
    entry = mutate_draft_placement(
        db, version=draft, planning_section_id=2000, day_key="monday",
        period_index=1, subject_code="MAT", teacher_id=1000,
    )
    set_entry_lock(db, version=draft, entry=entry, is_locked=True, actor_user_id="U1")
    db.commit()
    db.refresh(entry)
    assert entry.is_locked is True
    assert entry.locked_by_user_id == "U1"
    assert entry.locked_at is not None

    draft.lifecycle_status = "superseded"
    db.commit()
    with pytest.raises(TimetableVersionError, match="cannot be edited"):
        set_entry_lock(db, version=draft, entry=entry, is_locked=False, actor_user_id="U1")


def test_scope_mismatch_is_rejected(db):
    with pytest.raises(TimetableVersionError, match="same organization"):
        create_manual_draft(
            db, school_group_id=1, branch_id=10, academic_year_id=200
        )


def test_version_numbering_is_per_scope_and_source_scope_is_enforced(db):
    first = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    second = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    other = create_manual_draft(db, school_group_id=2, branch_id=20, academic_year_id=200)
    assert (first.version_number, second.version_number, other.version_number) == (1, 2, 1)
    with pytest.raises(TimetableVersionError, match="outside the selected scope"):
        create_manual_draft(
            db, school_group_id=2, branch_id=20, academic_year_id=200,
            source_version_id=first.id,
        )
    assert resolve_version(
        db, version_id=first.id, school_group_id=2, branch_id=20, academic_year_id=200
    ) is None


def test_entry_collision_guards_are_per_version_and_exact_scope(db):
    first = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    second = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    for version in (first, second):
        db.add(models.TimetableEntry(
            timetable_version_id=version.id, branch_id=10, academic_year_id=100,
            planning_section_id=2000, subject_code="MAT", teacher_id=1000,
            day_key="monday", period_index=1,
        ))
    db.flush()  # The same placement is legal in two different versions.
    first_id = first.id
    db.commit()
    db.add(models.TimetableEntry(
        timetable_version_id=first_id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    first = db.query(models.TimetableVersion).filter_by(id=first_id).one()
    db.add(models.TimetableEntry(
        timetable_version_id=first.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1001,
        day_key="monday", period_index=1,
    ))
    with pytest.raises(IntegrityError):  # Section collision, different teacher.
        db.flush()
    db.rollback()

    first = db.query(models.TimetableVersion).filter_by(id=first_id).one()
    db.add(models.TimetableEntry(
        timetable_version_id=first.id, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    with pytest.raises(IntegrityError):  # Teacher collision, different section.
        db.flush()
    db.rollback()

    first = db.query(models.TimetableVersion).filter_by(id=first_id).one()
    db.add(models.TimetableEntry(
        timetable_version_id=first.id, branch_id=20, academic_year_id=200,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="tuesday", period_index=1,
    ))
    with pytest.raises(IntegrityError):
        db.flush()


def test_active_pointer_scope_coherence_and_uniqueness_are_database_enforced(db):
    version = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    version_id = version.id
    db.commit()
    db.add(models.TimetableActiveVersion(
        school_group_id=2, branch_id=20, academic_year_id=200,
        timetable_version_id=version_id,
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()

    version = db.query(models.TimetableVersion).filter_by(id=version_id).one()
    version.origin = "imported"
    set_imported_active_pointer(db, version=version)
    db.add(models.TimetableActiveVersion(
        school_group_id=1, branch_id=10, academic_year_id=100,
        timetable_version_id=version.id,
    ))
    with pytest.raises(IntegrityError):
        db.flush()
