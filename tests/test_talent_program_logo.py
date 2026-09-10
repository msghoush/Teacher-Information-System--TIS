"""Program Identity logo: upload/replace/remove, validation, tenant isolation, and permission tests.

Storage and validation reuse ``branding_storage.py``'s existing organization/branch
logo pattern (Pillow real-image-bytes check, sanitized SVG, 4MB limit, atomic
temp-then-rename writes, opaque filenames) at a new Program-scoped path. This file
never touches ``tis.db`` - it builds a disposable in-memory SQLite database per test.
"""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth import get_current_user
from database import Base
from dependencies import get_db
from routers.talent_programs import router
from talent_program_service import create_program, get_program, transition_program


def _png_bytes(width=200, height=100, color=(10, 20, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([models.SchoolGroup(id=1, name="One"), models.SchoolGroup(id=2, name="Two")])
    session.commit()
    yield session
    session.close()


def _user(db, *, user_id="9000000001", group=1, role="Administrator"):
    user = models.User(user_id=user_id, username=f"admin.{user_id}", role=role, user_type="TENANT",
        access_scope="ORGANIZATION", school_group_id=group, is_active=True)
    db.add(user); db.commit()
    user.scope_school_group_id = group
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_upload_replace_and_remove_round_trip(tmp_path, monkeypatch, db):
    monkeypatch.setattr("branding_storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("branding_storage.BRANDING_ROOT", tmp_path / "branding")
    monkeypatch.setattr("branding_storage.ORGANIZATIONS_ROOT", tmp_path / "branding" / "organizations")
    program = create_program(db, school_group_id=1, name="Mental Math"); db.commit()
    user = _user(db)
    with _client(db, user) as client:
        uploaded = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("logo.png", _png_bytes(), "image/png")},
        )
        assert uploaded.status_code == 200, uploaded.text
        first_url = uploaded.json()["logo_url"]
        assert first_url and first_url.startswith("/organization-assets/1/")
        first_path = get_program(db, 1, program.id).logo_path
        first_file = tmp_path / first_path
        assert first_file.is_file()

        replaced = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("logo2.png", _png_bytes(color=(90, 90, 90)), "image/png")},
        )
        assert replaced.status_code == 200
        second_path = get_program(db, 1, program.id).logo_path
        assert second_path != first_path
        assert (tmp_path / second_path).is_file()
        # The old file must not be left as an orphan after a replace.
        assert not first_file.exists()

        removed = client.delete(f"/api/talent/programs/{program.id}/logo")
        assert removed.status_code == 200
        assert removed.json()["logo_url"] is None
        assert get_program(db, 1, program.id).logo_path is None
        assert not (tmp_path / second_path).exists()


def test_invalid_logo_rejected_wrong_type_and_oversized(tmp_path, monkeypatch, db):
    monkeypatch.setattr("branding_storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("branding_storage.BRANDING_ROOT", tmp_path / "branding")
    monkeypatch.setattr("branding_storage.ORGANIZATIONS_ROOT", tmp_path / "branding" / "organizations")
    program = create_program(db, school_group_id=1, name="Performing Arts"); db.commit()
    user = _user(db)
    with _client(db, user) as client:
        wrong_type = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("notes.txt", b"not an image", "text/plain")},
        )
        assert wrong_type.status_code == 400
        assert get_program(db, 1, program.id).logo_path is None

        oversized = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("big.png", b"\x89PNG\r\n" + b"0" * (4 * 1024 * 1024 + 10), "image/png")},
        )
        assert oversized.status_code == 400
        assert get_program(db, 1, program.id).logo_path is None


def test_retired_program_cannot_change_logo(tmp_path, monkeypatch, db):
    monkeypatch.setattr("branding_storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("branding_storage.BRANDING_ROOT", tmp_path / "branding")
    monkeypatch.setattr("branding_storage.ORGANIZATIONS_ROOT", tmp_path / "branding" / "organizations")
    program = create_program(db, school_group_id=1, name="Ghers"); db.commit()
    transition_program(db, school_group_id=1, program_id=program.id, target_status="active"); db.commit()
    transition_program(db, school_group_id=1, program_id=program.id, target_status="retired"); db.commit()
    user = _user(db)
    with _client(db, user) as client:
        response = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("logo.png", _png_bytes(), "image/png")},
        )
        assert response.status_code == 400
        assert response.json()["code"] == "retired_program"


def test_cross_tenant_program_logo_access_is_denied(tmp_path, monkeypatch, db):
    monkeypatch.setattr("branding_storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("branding_storage.BRANDING_ROOT", tmp_path / "branding")
    monkeypatch.setattr("branding_storage.ORGANIZATIONS_ROOT", tmp_path / "branding" / "organizations")
    program = create_program(db, school_group_id=1, name="Home Org Program"); db.commit()
    outsider = _user(db, user_id="9000000002", group=2)
    with _client(db, outsider) as client:
        upload = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("logo.png", _png_bytes(), "image/png")},
        )
        assert upload.status_code == 404
        remove = client.delete(f"/api/talent/programs/{program.id}/logo")
        assert remove.status_code == 404
    assert get_program(db, 1, program.id).logo_path is None


def test_view_only_permission_cannot_manage_logo(tmp_path, monkeypatch, db):
    monkeypatch.setattr("branding_storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("branding_storage.BRANDING_ROOT", tmp_path / "branding")
    monkeypatch.setattr("branding_storage.ORGANIZATIONS_ROOT", tmp_path / "branding" / "organizations")
    program = create_program(db, school_group_id=1, name="View Only Program"); db.commit()
    viewer = _user(db, user_id="9000000003", role="Editor")
    with _client(db, viewer) as client:
        upload = client.post(
            f"/api/talent/programs/{program.id}/logo",
            files={"logo": ("logo.png", _png_bytes(), "image/png")},
        )
        assert upload.status_code == 403
        remove = client.delete(f"/api/talent/programs/{program.id}/logo")
        assert remove.status_code == 403


def test_program_list_and_read_include_logo_url_field(tmp_path, monkeypatch, db):
    monkeypatch.setattr("branding_storage.STATIC_ROOT", tmp_path)
    monkeypatch.setattr("branding_storage.BRANDING_ROOT", tmp_path / "branding")
    monkeypatch.setattr("branding_storage.ORGANIZATIONS_ROOT", tmp_path / "branding" / "organizations")
    program = create_program(db, school_group_id=1, name="No Logo Yet"); db.commit()
    user = _user(db)
    with _client(db, user) as client:
        listed = client.get("/api/talent/programs")
        assert listed.status_code == 200
        assert listed.json()[0]["logo_url"] is None
        read = client.get(f"/api/talent/programs/{program.id}")
        assert read.status_code == 200
        assert read.json()["logo_url"] is None


def test_planning_section_cascade_is_scoped_and_grade_filtered(db):
    db.add_all([
        models.Branch(id=10, school_group_id=1, name="One A"),
        models.Branch(id=20, school_group_id=2, name="Two A"),
        models.AcademicYear(id=100, school_group_id=1, year_name="2026-2027"),
        models.PlanningSection(id=901, branch_id=10, academic_year_id=100, grade_level="4", section_name="A", class_status="Current"),
        models.PlanningSection(id=902, branch_id=10, academic_year_id=100, grade_level="5", section_name="B", class_status="Current"),
    ])
    db.commit()
    user = _user(db)
    with _client(db, user) as client:
        response = client.get("/api/talent/programs/planning-sections", params={"academic_year_id": 100, "branch_id": 10, "grade_level": "4"})
        assert response.status_code == 200
        assert response.json() == [{"id": 901, "section_name": "A"}]
        assert client.get("/api/talent/programs/planning-sections", params={"academic_year_id": 100, "branch_id": 20, "grade_level": "4"}).status_code == 404
