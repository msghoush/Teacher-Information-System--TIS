import concurrent.futures
import os
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models
from timetable_publication_service import (
    TimetableDraftValidationService,
    TimetablePublicationService,
    compare_timetable_versions,
)
from timetable_version_service import (
    TimetableVersionError,
    archive_version,
    copy_version_to_draft,
    create_manual_draft,
    mutate_draft_placement,
    lock_scoped_version,
    set_entry_lock,
    set_imported_active_pointer,
)
from test_timetable_versioning import db  # noqa: F401


def _planning_complete(db):
    if not db.query(models.TeacherSectionAssignment).filter_by(planning_section_id=2001).first():
        db.add(models.TeacherSectionAssignment(teacher_id=1001, planning_section_id=2001, subject_code="MAT"))
    db.flush()


def _complete_draft(db):
    _planning_complete(db)
    draft = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    for section_id, teacher_id in ((2000, 1000), (2001, 1001)):
        for index, (day, period) in enumerate((("monday", 1), ("monday", 2), ("tuesday", 1), ("tuesday", 2))):
            db.add(models.TimetableEntry(
                timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
                planning_section_id=section_id, subject_code="MAT", teacher_id=teacher_id,
                day_key=day, period_index=period,
            ))
    db.flush()
    return draft


def test_copy_preserves_source_placements_locks_and_provenance(db):
    source = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported")
    source.lifecycle_status = "publication_ready"
    entry = models.TimetableEntry(
        timetable_version_id=source.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1, is_locked=True,
    )
    db.add(entry); db.flush(); set_imported_active_pointer(db, version=source); db.flush()
    draft = copy_version_to_draft(db, source_version=source, actor_user_id="U1")
    copied = db.query(models.TimetableEntry).filter_by(timetable_version_id=draft.id).one()
    assert draft.source_version_id == source.id
    assert draft.edit_revision == 0
    assert copied.is_locked is True
    assert source.lifecycle_status == "publication_ready"
    assert db.query(models.TimetableEntry).filter_by(timetable_version_id=source.id).count() == 1


def test_lock_unlock_refreshes_authority_and_locked_lesson_cannot_change(db):
    draft = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    entry = mutate_draft_placement(db, version=draft, planning_section_id=2000, day_key="monday", period_index=1, subject_code="MAT", teacher_id=1000)
    old_snapshot = draft.input_snapshot_id
    revision = draft.edit_revision
    set_entry_lock(db, version=draft, entry=entry, is_locked=True, actor_user_id="U1", expected_edit_revision=revision)
    assert entry.is_locked is True
    assert draft.input_snapshot_id != old_snapshot
    with pytest.raises(TimetableVersionError, match="Unlock"):
        mutate_draft_placement(db, version=draft, planning_section_id=2000, day_key="monday", period_index=1, subject_code=None, teacher_id=None)
    set_entry_lock(db, version=draft, entry=entry, is_locked=False, actor_user_id="U1", expected_edit_revision=draft.edit_revision)
    assert entry.is_locked is False


def test_lock_and_edit_revision_fail_closed_on_immutable_or_stale_browser(db):
    draft = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    entry = mutate_draft_placement(db, version=draft, planning_section_id=2000, day_key="monday", period_index=1, subject_code="MAT", teacher_id=1000)
    with pytest.raises(TimetableVersionError) as conflict:
        set_entry_lock(db, version=draft, entry=entry, is_locked=True, actor_user_id="U1", expected_edit_revision=0)
    assert conflict.value.code == "edit_revision_conflict"
    draft.lifecycle_status = "superseded"
    db.flush()
    with pytest.raises(TimetableVersionError) as immutable:
        set_entry_lock(db, version=draft, entry=entry, is_locked=True, actor_user_id="U1")
    assert immutable.value.code == "immutable_version"


def test_complete_draft_validates_and_subsequent_edit_returns_to_draft(db):
    draft = _complete_draft(db)
    result = TimetableDraftValidationService(db).validate(version=draft, expected_edit_revision=0, transition=True)
    assert result["valid"] is True
    assert draft.lifecycle_status == "publication_ready"
    mutate_draft_placement(db, version=draft, planning_section_id=2000, day_key="monday", period_index=1, subject_code="MAT", teacher_id=1000, expected_edit_revision=0)
    assert draft.lifecycle_status == "draft"


def test_incomplete_stale_and_blocked_drafts_fail_validation(db):
    incomplete = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    result = TimetableDraftValidationService(db).validate(version=incomplete, transition=True)
    assert result["valid"] is False
    assert "demand_incomplete" in {item["code"] for item in result["blockers"]}
    db.rollback()

    stale = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    db.query(models.Subject).filter_by(id=3000).one().weekly_hours = 5
    result = TimetableDraftValidationService(db).validate(version=stale)
    assert "stale_input" in {item["code"] for item in result["blockers"]}
    db.rollback()

    blocked = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    setting = db.query(models.TimetableSetting).filter_by(id=5000).one()
    db.add(models.TimetableNonTeachingBlock(timetable_setting_id=setting.id, block_type="assembly", label="Assembly", day_key="monday", start_time="08:10", end_time="08:25", start_period=1, end_period=1))
    db.add(models.TimetableEntry(timetable_version_id=blocked.id, branch_id=10, academic_year_id=100, planning_section_id=2000, subject_code="MAT", teacher_id=1000, day_key="monday", period_index=1, is_locked=True))
    db.flush()
    result = TimetableDraftValidationService(db).validate(version=blocked)
    assert {"stale_input", "invalid_lock"} <= {item["code"] for item in result["blockers"]}


def test_publish_swaps_pointer_supersedes_previous_and_makes_new_active_immutable(db):
    previous = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported")
    previous.lifecycle_status = "publication_ready"; set_imported_active_pointer(db, version=previous)
    draft = _complete_draft(db)
    assert TimetableDraftValidationService(db).validate(version=draft, transition=True)["valid"]
    published = TimetablePublicationService(db).publish(
        version_id=draft.id, school_group_id=1, branch_id=10, academic_year_id=100,
        actor_user_id="U1", expected_edit_revision=draft.edit_revision, expected_pointer_revision=0,
    )
    pointer = db.query(models.TimetableActiveVersion).filter_by(school_group_id=1, branch_id=10, academic_year_id=100).one()
    assert pointer.timetable_version_id == published.id
    assert pointer.revision == 1
    assert previous.lifecycle_status == "superseded"
    assert previous.superseded_by_version_id == published.id
    assert published.published_at is not None
    with pytest.raises(TimetableVersionError, match="active timetable"):
        mutate_draft_placement(db, version=published, planning_section_id=2000, day_key="monday", period_index=1, subject_code=None, teacher_id=None)


def test_publish_rejects_pointer_conflict_wrong_scope_and_incomplete(db):
    draft = _complete_draft(db)
    TimetableDraftValidationService(db).validate(version=draft, transition=True)
    with pytest.raises(TimetableVersionError) as conflict:
        TimetablePublicationService(db).publish(version_id=draft.id, school_group_id=1, branch_id=10, academic_year_id=100, actor_user_id="U1", expected_edit_revision=0, expected_pointer_revision=9)
    assert conflict.value.code == "pointer_revision_conflict"
    with pytest.raises(TimetableVersionError) as scope:
        TimetablePublicationService(db).publish(version_id=draft.id, school_group_id=2, branch_id=20, academic_year_id=200, actor_user_id="U1", expected_edit_revision=0, expected_pointer_revision=0)
    assert scope.value.code == "version_not_found"
    incomplete = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    with pytest.raises(TimetableVersionError) as invalid:
        TimetablePublicationService(db).publish(version_id=incomplete.id, school_group_id=1, branch_id=10, academic_year_id=100, actor_user_id="U1", expected_edit_revision=0, expected_pointer_revision=0)
    assert invalid.value.code == "not_publication_ready"


def test_comparison_detects_unchanged_moved_added_removed_and_scope(db):
    left = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    right = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    for version, rows in ((left, [("MAT", "monday", 1), ("MAT", "monday", 2)]), (right, [("MAT", "monday", 1), ("MAT", "tuesday", 2), ("SCI", "tuesday", 3)])):
        for code, day, period in rows:
            db.add(models.TimetableEntry(timetable_version_id=version.id, branch_id=10, academic_year_id=100, planning_section_id=2000, subject_code=code, teacher_id=1000, day_key=day, period_index=period, is_locked=(period == 1)))
    db.flush()
    result = compare_timetable_versions(db, left=left, right=right)
    assert result["unchanged_lessons"] == 1
    assert result["counts"]["moved"] == 1
    assert result["counts"]["added"] == 1
    assert result["left"]["locked_lessons"] == 1
    other = create_manual_draft(db, school_group_id=2, branch_id=20, academic_year_id=200)
    with pytest.raises(TimetableVersionError) as mismatch:
        compare_timetable_versions(db, left=left, right=other)
    assert mismatch.value.code == "comparison_scope_mismatch"


def test_archive_allows_draft_and_superseded_but_not_active(db):
    draft = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100)
    archive_version(db, version=draft, actor_user_id="U1")
    assert draft.lifecycle_status == "archived"
    active = create_manual_draft(db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported")
    active.lifecycle_status = "publication_ready"; set_imported_active_pointer(db, version=active)
    with pytest.raises(TimetableVersionError) as exc:
        archive_version(db, version=active, actor_user_id="U1")
    assert exc.value.code == "active_version_archive_forbidden"


def test_stage4_ui_and_permissions_are_declared():
    template = open("templates/timetable.html", encoding="utf-8").read()
    permissions = open("permission_registry.py", encoding="utf-8").read()
    assert "Make Working Copy" in template
    assert "Check Timetable" in template
    assert "Publish Timetable" in template
    assert "Export This Version" in template
    assert "Timetable Readiness" in template
    # Stage 5.1 now builds Generate/Regenerate on the Stage 4 publication boundary.
    assert "Generate Timetable" in template
    assert "timetable.lock_lessons" in permissions
    assert "timetable.archive_versions" in permissions


POSTGRESQL_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "")


@pytest.fixture()
def pg_stage4():
    if not POSTGRESQL_URL.startswith("postgresql"):
        pytest.skip("TIS_TEST_POSTGRESQL_URL is required for Stage 4 PostgreSQL concurrency tests")
    schema_name = f"tis_timetable_s4_{uuid.uuid4().hex}"
    admin = create_engine(POSTGRESQL_URL)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    engine = create_engine(
        POSTGRESQL_URL,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c search_path={schema_name} -c lock_timeout=10s -c statement_timeout=30s",
        },
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    seed = Session()
    seed.add_all([models.SchoolGroup(id=1, name="Stage 4 Scope")])
    seed.commit()
    seed.add_all([
        models.Branch(id=10, school_group_id=1, name="Main"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026"),
    ])
    seed.commit()
    seed.add_all([
        models.User(user_id="U1", username="u1", first_name="One", last_name="Admin", school_group_id=1, branch_id=10, academic_year_id=100),
        models.User(user_id="U2", username="u2", first_name="Two", last_name="Admin", school_group_id=1, branch_id=10, academic_year_id=100),
        models.Teacher(id=1000, teacher_id="T1", first_name="A", last_name="Teacher", branch_id=10, academic_year_id=100),
        models.PlanningSection(id=2000, grade_level="1", section_name="A", class_status="Current", branch_id=10, academic_year_id=100),
        models.Subject(id=3000, subject_code="MAT", subject_name="Mathematics", weekly_hours=1, grade=1, branch_id=10, academic_year_id=100),
        models.TeacherSectionAssignment(id=4000, teacher_id=1000, planning_section_id=2000, subject_code="MAT"),
        models.TimetableSetting(id=5000, branch_id=10, academic_year_id=100, working_days_csv="monday", periods_per_day=2, period_duration_minutes=45, school_start_time="08:00", school_end_time="09:30"),
    ])
    seed.commit()
    seed.close()
    try:
        yield Session
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        admin.dispose()


def _pg_ready_version(db, *, origin="manual"):
    version = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin=origin
    )
    db.add(models.TimetableEntry(
        timetable_version_id=version.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    db.flush()
    assert TimetableDraftValidationService(db).validate(
        version=version, expected_edit_revision=0, transition=True
    )["valid"]
    return version


def _pg_active_and_candidate(Session):
    db = Session()
    active = _pg_ready_version(db, origin="imported")
    set_imported_active_pointer(db, version=active)
    candidate = _pg_ready_version(db)
    db.commit()
    result = (active.id, candidate.id)
    db.close()
    return result


@pytest.mark.parametrize("_attempt", range(5))
def test_postgresql_publication_wins_before_placement_edit(pg_stage4, _attempt):
    Session = pg_stage4
    active_id, candidate_id = _pg_active_and_candidate(Session)
    publisher = Session()
    lock_scoped_version(
        publisher, version_id=candidate_id, school_group_id=1,
        branch_id=10, academic_year_id=100,
    )
    started = threading.Event()

    def edit():
        db = Session()
        try:
            version = db.get(models.TimetableVersion, candidate_id)
            started.set()
            mutate_draft_placement(
                db, version=version, planning_section_id=2000,
                day_key="monday", period_index=1, subject_code=None,
                teacher_id=None, expected_edit_revision=0,
            )
            db.commit()
            return "committed"
        except TimetableVersionError as exc:
            db.rollback()
            return exc.code
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(edit)
        assert started.wait(10)
        TimetablePublicationService(publisher).publish(
            version_id=candidate_id, school_group_id=1, branch_id=10,
            academic_year_id=100, actor_user_id="U1",
            expected_edit_revision=0, expected_pointer_revision=0,
        )
        publisher.commit()
        assert pending.result(timeout=20) == "immutable_active_version"
    publisher.close()
    check = Session()
    version = check.get(models.TimetableVersion, candidate_id)
    pointer = check.query(models.TimetableActiveVersion).filter_by(
        school_group_id=1, branch_id=10, academic_year_id=100
    ).one()
    assert pointer.timetable_version_id == candidate_id
    assert version.lifecycle_status == "publication_ready"
    assert version.edit_revision == 0
    assert check.query(models.TimetableEntry).filter_by(timetable_version_id=candidate_id).count() == 1
    assert check.get(models.TimetableVersion, active_id).lifecycle_status == "superseded"
    check.close()


@pytest.mark.parametrize("_attempt", range(5))
def test_postgresql_placement_edit_wins_before_publication(pg_stage4, _attempt):
    Session = pg_stage4
    active_id, candidate_id = _pg_active_and_candidate(Session)
    editor = Session()
    candidate = editor.get(models.TimetableVersion, candidate_id)
    mutate_draft_placement(
        editor, version=candidate, planning_section_id=2000,
        day_key="monday", period_index=1, subject_code=None,
        teacher_id=None, expected_edit_revision=0,
    )
    started = threading.Event()

    def publish():
        db = Session()
        try:
            started.set()
            TimetablePublicationService(db).publish(
                version_id=candidate_id, school_group_id=1, branch_id=10,
                academic_year_id=100, actor_user_id="U1",
                expected_edit_revision=0, expected_pointer_revision=0,
            )
            db.commit()
            return "committed"
        except TimetableVersionError as exc:
            db.rollback()
            return exc.code
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(publish)
        assert started.wait(10)
        time.sleep(0.1)
        editor.commit()
        assert pending.result(timeout=20) == "edit_revision_conflict"
    editor.close()
    check = Session()
    version = check.get(models.TimetableVersion, candidate_id)
    pointer = check.query(models.TimetableActiveVersion).filter_by(
        school_group_id=1, branch_id=10, academic_year_id=100
    ).one()
    assert pointer.timetable_version_id == active_id
    assert pointer.revision == 0
    assert version.lifecycle_status == "draft"
    assert version.edit_revision == 1
    assert check.query(models.TimetableEntry).filter_by(timetable_version_id=candidate_id).count() == 0
    check.close()


@pytest.mark.parametrize("desired_lock_state", [True, False])
def test_postgresql_publication_blocks_waiting_lock_and_archive(pg_stage4, desired_lock_state):
    Session = pg_stage4
    _, candidate_id = _pg_active_and_candidate(Session)
    expected_revision = 0
    if not desired_lock_state:
        prepare = Session()
        candidate = prepare.get(models.TimetableVersion, candidate_id)
        entry = prepare.query(models.TimetableEntry).filter_by(
            timetable_version_id=candidate_id
        ).one()
        set_entry_lock(
            prepare, version=candidate, entry=entry, is_locked=True,
            actor_user_id="U1", expected_edit_revision=0,
        )
        expected_revision = 1
        assert TimetableDraftValidationService(prepare).validate(
            version=candidate, expected_edit_revision=expected_revision, transition=True
        )["valid"]
        prepare.commit()
        prepare.close()
    publisher = Session()
    lock_scoped_version(
        publisher, version_id=candidate_id, school_group_id=1,
        branch_id=10, academic_year_id=100,
    )
    started = threading.Barrier(3)

    def mutate(kind):
        db = Session()
        try:
            version = db.get(models.TimetableVersion, candidate_id)
            started.wait(timeout=10)
            if kind == "lock":
                entry = db.query(models.TimetableEntry).filter_by(timetable_version_id=candidate_id).one()
                set_entry_lock(
                    db, version=version, entry=entry,
                    is_locked=desired_lock_state, actor_user_id="U2",
                    expected_edit_revision=expected_revision,
                )
            else:
                archive_version(db, version=version, actor_user_id="U2")
            db.commit()
            return "committed"
        except TimetableVersionError as exc:
            db.rollback()
            return exc.code
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        lock_result = pool.submit(mutate, "lock")
        archive_result = pool.submit(mutate, "archive")
        started.wait(timeout=10)
        TimetablePublicationService(publisher).publish(
            version_id=candidate_id, school_group_id=1, branch_id=10,
            academic_year_id=100, actor_user_id="U1",
            expected_edit_revision=expected_revision, expected_pointer_revision=0,
        )
        publisher.commit()
        assert lock_result.result(timeout=20) == "immutable_active_version"
        assert archive_result.result(timeout=20) == "active_version_archive_forbidden"
    publisher.close()
    check = Session()
    version = check.get(models.TimetableVersion, candidate_id)
    entry = check.query(models.TimetableEntry).filter_by(timetable_version_id=candidate_id).one()
    assert version.lifecycle_status == "publication_ready"
    assert version.archived_at is None
    assert version.edit_revision == expected_revision
    assert entry.is_locked is (not desired_lock_state)
    check.close()


def test_postgresql_validation_cannot_overwrite_winning_edit(pg_stage4):
    Session = pg_stage4
    _, candidate_id = _pg_active_and_candidate(Session)
    editor = Session()
    candidate = editor.get(models.TimetableVersion, candidate_id)
    mutate_draft_placement(
        editor, version=candidate, planning_section_id=2000,
        day_key="monday", period_index=1, subject_code=None,
        teacher_id=None, expected_edit_revision=0,
    )
    started = threading.Event()

    def validate():
        db = Session()
        try:
            version = db.get(models.TimetableVersion, candidate_id)
            started.set()
            TimetableDraftValidationService(db).validate(
                version=version, expected_edit_revision=0, transition=True
            )
            db.commit()
            return "committed"
        except TimetableVersionError as exc:
            db.rollback()
            return exc.code
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(validate)
        assert started.wait(10)
        time.sleep(0.1)
        editor.commit()
        assert pending.result(timeout=20) == "edit_revision_conflict"
    editor.close()
    check = Session()
    version = check.get(models.TimetableVersion, candidate_id)
    assert version.lifecycle_status == "draft"
    assert version.edit_revision == 1
    assert check.query(models.TimetableEntry).filter_by(timetable_version_id=candidate_id).count() == 0
    check.close()


def test_postgresql_publication_rollback_restores_all_state(pg_stage4):
    Session = pg_stage4
    active_id, candidate_id = _pg_active_and_candidate(Session)
    db = Session()
    TimetablePublicationService(db).publish(
        version_id=candidate_id, school_group_id=1, branch_id=10,
        academic_year_id=100, actor_user_id="U1",
        expected_edit_revision=0, expected_pointer_revision=0,
    )
    db.rollback()
    db.close()
    check = Session()
    active = check.get(models.TimetableVersion, active_id)
    candidate = check.get(models.TimetableVersion, candidate_id)
    pointer = check.query(models.TimetableActiveVersion).filter_by(
        school_group_id=1, branch_id=10, academic_year_id=100
    ).one()
    assert pointer.timetable_version_id == active_id
    assert pointer.revision == 0
    assert active.lifecycle_status == "publication_ready"
    assert active.superseded_at is None
    assert active.superseded_by_version_id is None
    assert candidate.lifecycle_status == "publication_ready"
    assert candidate.published_at is None
    assert candidate.published_by_user_id is None
    assert check.query(models.TimetableEntry).filter_by(timetable_version_id=candidate_id).count() == 1
    check.close()
