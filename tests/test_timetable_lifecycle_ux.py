import json
from datetime import datetime

import models
from routers.timetable import _version_error_response
from timetable_conflicts import canonical_conflict_code
from timetable_logic import build_timetable_workspace_payload
from timetable_version_service import (
    TimetableVersionError,
    create_manual_draft,
    set_imported_active_pointer,
)
from test_timetable_versioning import db  # noqa: F401


def test_lifecycle_payload_identifies_current_published_and_exposes_audit_facts(db):
    published = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported"
    )
    published.lifecycle_status = "publication_ready"
    published.approved_at = datetime.utcnow()
    published.approved_by_user_id = "U1"
    db.flush()
    set_imported_active_pointer(db, version=published)
    db.flush()

    payload = build_timetable_workspace_payload(db, 10, 100, version_id=published.id)
    selected = payload["version"]
    history = next(item for item in payload["versions"] if item["public_id"] == published.public_id)

    assert selected["is_active"] is True
    assert selected["is_mutable"] is False
    assert selected["lifecycle_status"] == "publication_ready"
    assert selected["validation_state"] == "validated"
    for key in ("created_at", "generated_at", "approved_at", "published_at", "source_version_number"):
        assert key in selected
    for key in ("generated_at", "approved_at", "published_at", "validation_state"):
        assert key in history


def test_mutation_and_lifecycle_errors_include_canonical_conflict_without_breaking_message():
    response = _version_error_response(
        TimetableVersionError("edit_revision_conflict", "Refresh before changing this draft.")
    )
    body = json.loads(response.body)

    assert response.status_code == 409
    assert body["ok"] is False
    assert body["message"] == "Refresh before changing this draft."
    assert body["conflicts"][0]["code"] == "STALE_EDIT_REVISION"
    assert body["conflicts"][0]["source_code"] == "edit_revision_conflict"
    assert body["conflicts"][0]["provenance"] == "version_lifecycle"
    assert "remediation" in body["conflicts"][0]


def test_release_one_lifecycle_conflict_codes_are_canonical():
    expected = {
        "pointer_revision_conflict": "STALE_PUBLICATION_POINTER",
        "immutable_active_version": "IMMUTABLE_VERSION_MUTATION",
        "draft_not_approved": "APPROVAL_REQUIRED",
        "publication_validation_failed": "STALE_VALIDATION",
        "copy_source_mutable": "INVALID_LIFECYCLE_TRANSITION",
        "blocked_slot": "NON_TEACHING_BLOCK_CONFLICT",
    }
    assert {source: canonical_conflict_code(source) for source in expected} == expected


def test_professional_lifecycle_controls_and_accessibility_are_visible_and_permission_aware():
    template = open("templates/timetable.html", encoding="utf-8").read()

    for label in (
        "CURRENT PUBLISHED",
        "Create Working Draft from Published",
        "Start New Empty Draft",
        "Create Draft from This Version",
        "Generate Draft",
        "Regenerate Draft",
        "Refresh Latest Timetable",
    ):
        assert label in template
    assert 'aria-label="Timetable lifecycle"' in template
    assert 'aria-current="step"' in template
    assert "does not mean the data is corrupt or the timetable is infeasible" in template
    assert "canCreateTimetable" in template
    assert "canModifyTimetable" in template
    assert "canPublishTimetable" in template
    assert "Edit This Timetable" not in template
    assert "Create New Timetable" not in template
    assert "Regenerate Timetable" not in template
