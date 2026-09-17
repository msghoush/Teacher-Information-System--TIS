"""Exact scope/kind authority for branding and qualification mutations."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

os.environ["TIS_SESSION_SECRET"] = "configuration-scope-permission-test-secret-long-enough"

import main
import models


BRANDING_KEYS = {
    "school_group": "branding.manage_school_logos",
    "branch": "branding.manage_branch_logos",
}
QUALIFICATION_KEYS = {
    main.QUALIFICATION_KIND_DEGREE: "configuration.manage_degrees",
    main.QUALIFICATION_KIND_SPECIALIZATION: "configuration.manage_specializations",
}


def _request(path):
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"host", b"testserver")], "scheme": "http",
        "server": ("testserver", 80), "client": ("testclient", 50000),
        "root_path": "", "app": main.app,
    })


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _deny(monkeypatch):
    monkeypatch.setattr(
        main.authorization, "build_access_denied_response",
        lambda *args, **kwargs: JSONResponse({"permission": kwargs["permission_keys"][0]}, status_code=403),
    )


@pytest.mark.parametrize("operation", ("save", "reset"))
@pytest.mark.parametrize("granted_scope", BRANDING_KEYS)
@pytest.mark.parametrize("target_scope", BRANDING_KEYS)
def test_logo_mutation_uses_target_scope_permission(
    monkeypatch, db, operation, granted_scope, target_scope,
):
    school = models.SchoolGroup(name="School", status=True)
    db.add(school)
    db.flush()
    branch = models.Branch(name="Branch", school_group_id=school.id, status=True)
    db.add(branch)
    db.flush()
    if target_scope == "school_group":
        logo = models.SchoolGroupLogo(
            school_group_id=school.id, slot_key="primary", label="Before",
            image_path="test/primary.png", content_type="image/png", sort_order=0,
        )
    else:
        logo = models.BranchLogo(
            branch_id=branch.id, slot_key="primary", label="Before",
            image_path="test/primary.png", content_type="image/png", sort_order=0,
        )
    db.add(logo)
    db.commit()
    actor = SimpleNamespace(user_id="actor", school_group_id=school.id,
                            branch_id=branch.id, scope_branch_id=branch.id)
    monkeypatch.setattr(main, "_get_school_branding_access", lambda request, session: (actor, None))
    monkeypatch.setattr(main, "_can_manage_all_school_scopes", lambda session, user: False)
    monkeypatch.setattr(main, "_get_user_school_group_id", lambda session, user: school.id)
    monkeypatch.setattr(
        main.auth, "has_permission",
        lambda session, user, key: key == BRANDING_KEYS[granted_scope],
    )
    monkeypatch.setattr(main.branding_storage, "delete_owned_logo_file", lambda *args, **kwargs: None)
    _deny(monkeypatch)
    kwargs = {
        "request": _request("/system-configuration/logos" + ("/reset" if operation == "reset" else "")),
        "scope_type": target_scope, "school_group_id": school.id,
        "branch_id": branch.id, "slot_key": "primary", "db": db,
    }
    if operation == "save":
        response = asyncio.run(main.save_system_configuration_logo(
            **kwargs, label="After", logo_file=None,
        ))
    else:
        response = main.reset_system_configuration_logo(**kwargs)
    db.expire_all()
    persisted = db.get(type(logo), logo.id)
    if granted_scope == target_scope:
        assert response.status_code == 302
        if operation == "save":
            assert persisted.label == "After"
        else:
            assert persisted is None
    else:
        assert response.status_code == 403
        assert persisted.label == "Before"


@pytest.mark.parametrize("operation", ("create", "update", "delete"))
@pytest.mark.parametrize("granted_kind", QUALIFICATION_KEYS)
@pytest.mark.parametrize("target_kind", QUALIFICATION_KEYS)
def test_qualification_mutation_uses_persisted_or_submitted_kind(
    monkeypatch, db, operation, granted_kind, target_kind,
):
    actor = SimpleNamespace(user_id="actor")
    monkeypatch.setattr(main.auth, "get_current_user", lambda request, session: actor)
    monkeypatch.setattr(
        main.auth, "has_permission",
        lambda session, user, key: key == QUALIFICATION_KEYS[granted_kind],
    )
    monkeypatch.setattr(main, "ensure_qualification_options_seeded", lambda session: [])
    _deny(monkeypatch)
    option = models.QualificationOption(
        qualification_key="before", label="Before", kind=target_kind,
        alignment_keys="", legacy_aliases="before", sort_order=0,
    )
    if operation != "create":
        db.add(option)
        db.commit()
    path = "/system-configuration/qualifications"
    if operation == "create":
        response = main.create_qualification_option(
            _request(path), label="After", kind=target_kind, db=db,
        )
        after = db.query(models.QualificationOption).filter_by(label="After").first()
        assert (after is not None) == (granted_kind == target_kind)
    elif operation == "update":
        response = main.update_qualification_option(
            "before", _request(path + "/before"), label="After", db=db,
        )
        db.expire_all()
        assert db.get(models.QualificationOption, option.id).label == (
            "After" if granted_kind == target_kind else "Before"
        )
    else:
        response = main.delete_qualification_option(
            "before", _request(path + "/before/delete"), db=db,
        )
        db.expire_all()
        assert (db.get(models.QualificationOption, option.id) is None) == (
            granted_kind == target_kind
        )
    assert response.status_code == (302 if granted_kind == target_kind else 403)
