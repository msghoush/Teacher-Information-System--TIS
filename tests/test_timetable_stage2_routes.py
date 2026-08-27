import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from routers import timetable as timetable_router
from timetable_logic import build_timetable_workspace_payload
from timetable_version_service import create_manual_draft, resolve_active_version, set_imported_active_pointer
import models
from test_timetable_versioning import db  # noqa: F401 - shared focused fixture


def _request(payload):
    body = json.dumps(payload).encode("utf-8")
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/timetable/api/assign", "headers": []},
        receive,
    )


def _seed_active(db):
    imported = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="imported"
    )
    imported.lifecycle_status = "publication_ready"
    db.add(models.TimetableEntry(
        timetable_version_id=imported.id, branch_id=10, academic_year_id=100,
        planning_section_id=2000, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    db.flush()
    set_imported_active_pointer(db, version=imported)
    db.commit()
    return imported


def test_existing_workspace_and_exports_resolve_operational_version(db):
    imported = _seed_active(db)
    payload = build_timetable_workspace_payload(db, 10, 100)
    assert payload["version"]["id"] == imported.id
    assert [(row["day_key"], row["period_index"]) for row in payload["entries"]] == [
        ("monday", 1)
    ]
    assert payload["sections"][0]["section_label"] == "Grade 1-A"
    assert payload["teachers"][0]["scheduled_hours"] == 1

    xlsx = timetable_router._build_timetable_xlsx_bytes(
        payload, "Main", "2026", logo_assets=[]
    )
    pdf = timetable_router._build_timetable_pdf_bytes(
        payload, "Main", "2026", logo_assets=[]
    )
    assert xlsx[:2] == b"PK"
    assert pdf[:4] == b"%PDF"
    assert b"Published Timetable" in pdf


def test_existing_assignment_route_uses_copy_on_write_draft(db, monkeypatch):
    imported = _seed_active(db)
    user = SimpleNamespace(user_id="U1", branch_id=10, academic_year_id=100)
    monkeypatch.setattr(
        timetable_router, "_get_current_user_or_redirect", lambda request, session: (user, None)
    )
    monkeypatch.setattr(timetable_router.auth, "has_any_permission", lambda *args: True)

    response = asyncio.run(timetable_router.assign_timetable_slot(
        _request({
            "section_id": 2000,
            "day_key": "tuesday",
            "period_index": 2,
            "subject_code": "MAT",
        }),
        db,
    ))
    assert response.status_code == 200, response.body
    body = json.loads(response.body)
    assert body["ok"] is True
    draft = db.query(models.TimetableVersion).filter(
        models.TimetableVersion.source_version_id == imported.id
    ).one()
    assert draft.id != imported.id
    assert draft.lifecycle_status == "draft"
    assert draft.has_manual_changes is True
    assert db.query(models.TimetableEntry).filter_by(
        timetable_version_id=imported.id
    ).count() == 1
    assert db.query(models.TimetableEntry).filter_by(
        timetable_version_id=draft.id
    ).count() == 2
    assert resolve_active_version(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    ).id == imported.id
    assert body["payload"]["version"]["id"] == draft.id


def test_platform_style_unselected_scope_cannot_mutate(db, monkeypatch):
    user = SimpleNamespace(user_id="P1", branch_id=None, academic_year_id=None)
    monkeypatch.setattr(
        timetable_router, "_get_current_user_or_redirect", lambda request, session: (user, None)
    )
    monkeypatch.setattr(timetable_router.auth, "has_any_permission", lambda *args: True)
    response = asyncio.run(timetable_router.assign_timetable_slot(
        _request({"section_id": 2000, "day_key": "monday", "period_index": 1, "subject_code": "MAT"}),
        db,
    ))
    assert response.status_code == 400
    assert db.query(models.TimetableVersion).count() == 0
