from datetime import datetime
from types import SimpleNamespace

import pytest

import models
import auth
import permission_registry
from routers import timetable as timetable_router
from timetable_logic import build_timetable_workspace_payload
from timetable_version_service import (
    TimetableVersionError,
    create_manual_draft,
    delete_all_unused_timetable_versions,
    delete_unused_timetable_version,
    move_or_swap_timetable_entry,
    resolve_operational_version,
    timetable_version_delete_eligibility,
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


def test_publication_ready_never_published_version_is_deletable(db):
    candidate = _version(db, origin="regenerated")
    candidate.lifecycle_status = "publication_ready"
    candidate_id = candidate.id
    delete_unused_timetable_version(
        db, version_id=candidate.id, school_group_id=1, branch_id=10,
        academic_year_id=100,
    )
    assert db.get(models.TimetableVersion, candidate_id) is None


def test_history_view_payload_opens_exact_version_without_changing_active_pointer(db):
    active = _version(db, origin="imported")
    active.lifecycle_status = "publication_ready"
    set_imported_active_pointer(db, version=active)
    historical = _version(db, origin="generated")
    _entry(db, historical, day="tuesday", period=2)
    db.flush()
    payload = build_timetable_workspace_payload(db, 10, 100, version_id=historical.id)
    assert payload["version"]["id"] == historical.id
    assert [(entry["day_key"], entry["period_index"]) for entry in payload["entries"]] == [("tuesday", 2)]
    assert db.query(models.TimetableActiveVersion).one().timetable_version_id == active.id


def test_move_to_empty_valid_slot_increments_revision(db):
    version = _version(db)
    version.approved_at = datetime.utcnow()
    version.approved_by_user_id = "U1"
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
    assert version.approved_at is None
    assert version.approved_by_user_id is None


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
    version.approved_at = datetime.utcnow()
    version.approved_by_user_id = "U1"
    first = _entry(db, version, teacher=1000, day="monday", period=1)
    second = _entry(db, version, teacher=1001, day="monday", period=2)
    assert move_or_swap_timetable_entry(
        db, version=version, entry_id=first.id, destination_section_id=2000,
        destination_day_key="monday", destination_period_index=2,
    ) == "swapped"
    assert (first.period_index, second.period_index) == (2, 1)
    assert version.approved_at is None
    assert version.approved_by_user_id is None

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
    assert 'id="versionSelector"' not in template
    assert '{% if history_mode %}<div class="history-version-list"' in template
    assert 'href="/timetable?history=1">Timetable History' in template
    assert 'historyMode && canArchiveVersions' in template
    assert 'if (canDeleteVersions && item.can_delete)' in template
    assert 'view.textContent = "View"' in template
    assert '/timetable?history=1&version=${encodeURIComponent(item.public_id)}' in template
    assert 'Viewing Version ${normalizeInt(version.version_number)}' in template
    for value in ("Source:", "Created", "Published history", "Previous Published Timetable"):
        assert value in template
    assert 'remove.textContent = "Delete Timetable"' in template
    assert 'Delete All Unpublished Timetables' in template
    assert 'Delete this draft timetable?' in template
    assert 'This draft timetable will be permanently removed.' in template
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
        "Published Timetable", "Official timetable currently visible to authorized users.",
    ):
        assert text in template
    assert 'publishDialog.showModal()' in template
    assert 'publishConfirmBtn.addEventListener("click"' in template


def test_delete_versions_permission_is_admin_default_and_role_assignable():
    key = "timetable.delete_versions"
    assert key in permission_registry.get_default_permissions_for_role(auth.ROLE_ADMINISTRATOR)
    assert key not in permission_registry.get_default_permissions_for_role(auth.ROLE_EDITOR)
    payload = permission_registry.build_role_permission_payload(auth.ROLE_EDITOR, {key})
    item = next(
        permission for group in payload["groups"] for permission in group["permissions"]
        if permission["key"] == key
    )
    assert item["assignable"] is True
    assert item["allowed"] is True


def test_archived_never_published_admin_can_delete_but_unauthorized_user_cannot(db, monkeypatch):
    archived = _version(db, origin="imported")
    archived.lifecycle_status = "archived"
    db.flush()
    user = SimpleNamespace(user_id="U1")
    monkeypatch.setattr(timetable_router, "_get_current_user_or_redirect", lambda request, session: (user, None))
    monkeypatch.setattr(timetable_router, "get_scope_ids", lambda current: (10, 100))

    monkeypatch.setattr(timetable_router.auth, "has_permission", lambda *args, **kwargs: False)
    denied = timetable_router.delete_timetable_version(archived.public_id, SimpleNamespace(), db)
    assert denied.status_code == 403
    assert db.get(models.TimetableVersion, archived.id) is not None

    monkeypatch.setattr(timetable_router.auth, "has_permission", lambda *args, **kwargs: True)
    allowed = timetable_router.delete_timetable_version(archived.public_id, SimpleNamespace(), db)
    assert allowed.status_code == 200
    assert "Timetable deleted successfully." in allowed.body.decode("utf-8")
    assert db.get(models.TimetableVersion, archived.id) is None


def test_bulk_delete_removes_unpublished_versions_preserves_runs_and_scope(db):
    active = _version(db, origin="imported")
    active.lifecycle_status = "publication_ready"
    set_imported_active_pointer(db, version=active)
    archived = _version(db, origin="manual")
    archived.lifecycle_status = "archived"
    generated = _version(db, origin="generated")
    generated.lifecycle_status = "publication_ready"
    run = models.TimetableGenerationRun(
        school_group_id=1, branch_id=10, academic_year_id=100,
        request_mode="generate", input_snapshot_id=generated.input_snapshot_id,
        status="succeeded", progress_phase="complete", idempotency_key="bulk-run",
        result_version_id=generated.id,
    )
    db.add(run)
    entry = _entry(db, archived)
    other = create_manual_draft(db, school_group_id=2, branch_id=20, academic_year_id=200)
    db.flush()
    snapshot_ids = {archived.input_snapshot_id, generated.input_snapshot_id}

    result = delete_all_unused_timetable_versions(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )

    assert result["remaining"] == []
    assert result["deleted_count"] == 2
    assert db.get(models.TimetableVersion, archived.id) is None
    assert db.get(models.TimetableVersion, generated.id) is None
    assert db.get(models.TimetableEntry, entry.id) is None
    assert db.get(models.TimetableVersion, active.id) is not None
    assert db.get(models.TimetableVersion, other.id) is not None
    assert db.get(models.TimetableGenerationRun, run.id).result_version_id is None
    assert {row.id for row in db.query(models.TimetableInputSnapshot).filter(
        models.TimetableInputSnapshot.id.in_(snapshot_ids)
    ).all()} == snapshot_ids


def test_bulk_delete_reports_protected_published_lineage(db):
    active = _version(db, origin="imported")
    active.lifecycle_status = "publication_ready"
    set_imported_active_pointer(db, version=active)
    protected = _version(db, origin="manual")
    protected.lifecycle_status = "superseded"
    disposable = _version(db, origin="manual")

    result = delete_all_unused_timetable_versions(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )

    assert result["deleted_count"] == 1
    assert result["remaining"] == [{
        "version_id": protected.id,
        "version_number": protected.version_number,
        "reasons": ["This timetable is protected published history."],
    }]
    assert db.get(models.TimetableVersion, disposable.id) is None
    assert db.get(models.TimetableVersion, protected.id) is not None


def test_history_delete_payload_matches_service_eligibility(db):
    active = _version(db, origin="imported")
    active.lifecycle_status = "publication_ready"
    set_imported_active_pointer(db, version=active)
    candidate = _version(db, origin="generated")
    candidate.lifecycle_status = "archived"
    payload = build_timetable_workspace_payload(
        db, branch_id=10, academic_year_id=100, version_id=candidate.id
    )

    eligibility = timetable_version_delete_eligibility(db, version=candidate)
    assert payload["version"]["can_delete"] == eligibility["eligible"]
    assert payload["version"]["delete_blockers"] == eligibility["reasons"]


def test_edit_published_and_create_new_make_drafts_without_changing_active(db, monkeypatch):
    published = _version(db, origin="imported")
    published.lifecycle_status = "publication_ready"
    published_entry = _entry(db, published)
    set_imported_active_pointer(db, version=published)
    db.flush()
    user = SimpleNamespace(user_id="U1")
    monkeypatch.setattr(timetable_router, "_get_current_user_or_redirect", lambda request, session: (user, None))
    monkeypatch.setattr(timetable_router, "get_scope_ids", lambda current: (10, 100))
    monkeypatch.setattr(timetable_router.auth, "has_permission", lambda *args, **kwargs: True)

    edited = timetable_router.edit_published_timetable(SimpleNamespace(), db)
    assert edited.status_code == 303
    edited_draft = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.source_version_id == published.id
    ).order_by(models.TimetableVersion.id.desc()).first()
    assert edited_draft is not None and edited_draft.lifecycle_status == "draft"
    copied = db.query(models.TimetableEntry).filter_by(timetable_version_id=edited_draft.id).one()
    assert copied.subject_code == published_entry.subject_code
    assert db.query(models.TimetableActiveVersion).one().timetable_version_id == published.id
    fresh_response = timetable_router.create_new_timetable_draft(SimpleNamespace(), db)
    assert fresh_response.status_code == 303
    fresh = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.id != published.id,
        models.TimetableVersion.source_version_id.is_(None),
    ).order_by(models.TimetableVersion.id.desc()).first()
    assert fresh is not None and fresh.lifecycle_status == "draft"
    assert db.query(models.TimetableEntry).filter_by(timetable_version_id=fresh.id).count() == 0
    assert db.query(models.TimetableActiveVersion).one().timetable_version_id == published.id
    assert resolve_operational_version(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    ).id == fresh.id


def test_new_empty_manual_draft_is_not_stale_and_generation_action_is_explicit(db):
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    payload = build_timetable_workspace_payload(
        db, branch_id=10, academic_year_id=100, version_id=draft.id
    )

    assert payload["version"]["is_stale"] is False
    template = open("templates/timetable.html", encoding="utf-8").read()
    assert "Generate Timetable" in template
    assert "Regenerate Timetable" in template


def test_draft_published_language_and_actions_are_explicit():
    workspace = open("templates/timetable.html", encoding="utf-8").read()
    published = open("templates/published_timetable.html", encoding="utf-8").read()
    assert "Working Timetable" not in workspace
    for label in ("Draft Timetable", "Not Published Yet", "Publish Timetable", "Publish to Users"):
        assert label in workspace
    assert "This draft will become the official timetable for this branch and academic year." in workspace
    for label in ("Published Timetable", "Published to Users", "Edit This Timetable", "Create New Timetable"):
        assert label in published
    assert 'action="/timetable/drafts/edit-published"' in published
    assert 'action="/timetable/drafts/new"' in published
