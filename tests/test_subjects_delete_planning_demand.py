from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

import models
from routers import subjects as subjects_router
from test_curriculum_adjustment_preview import _db, _seed


def _user():
    return SimpleNamespace(user_id="U1", branch_id=10, academic_year_id=100)


def _extra_seed(db):
    """Add subjects isolating each individual deletion-protection pathway.

    Section 3002 (grade 4, Current) carries no demand or assignment rows in
    the shared `_seed` fixture, so it is used here as a clean scope to attach
    exactly one dependency per subject.
    """
    _seed(db)
    db.add_all([
        models.Subject(
            id=9000, subject_code="ART3", subject_name="Art",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9001, subject_code="PE3", subject_name="Physical Education",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9002, subject_code="DAN3", subject_name="Dance",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9003, subject_code="MUS3", subject_name="Music",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9004, subject_code="RET3", subject_name="Retired Elective",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
    ])
    db.commit()

    # ART3: only an active PlanningSubjectDemand row (no teacher reference at all).
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3002,
        subject_code="ART3", weekly_periods=1, is_active=True,
    ))
    # PE3: only a TeacherSubjectAllocation (existing, non-Planning protection).
    db.add(models.TeacherSubjectAllocation(teacher_id=5000, subject_code="PE3"))
    # DAN3: only a TeacherSectionAssignment (existing, Planning-adjacent protection).
    db.add(models.TeacherSectionAssignment(
        teacher_id=5000, planning_section_id=3002, subject_code="DAN3",
    ))
    # RET3: only a *retired* PlanningSubjectDemand row - exactly what
    # curriculum_adjustment_apply_service._set_demand leaves behind after a
    # zero-out retirement. No active row, no teacher reference at all.
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3002,
        subject_code="RET3", weekly_periods=0, is_active=False,
        retired_at=datetime.utcnow(),
    ))
    db.commit()
    # MUS3 is left with zero references anywhere.


def _patch_auth(monkeypatch, permission=True):
    monkeypatch.setattr(subjects_router, "get_current_user", lambda request, db: _user())
    monkeypatch.setattr(subjects_router.auth, "has_permission", lambda *a, **k: permission)


def _patch_render(monkeypatch):
    captured = {}

    def _fake_render(request, db, current_user, error="", success="", **kwargs):
        captured["error"] = error
        captured["success"] = success
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(subjects_router, "_render_subjects_page", _fake_render)
    return captured


def test_database_fk_blocks_subject_delete_even_when_demand_is_retired():
    """Confirms the real constraint this whole fix is about.

    PlanningSubjectDemand.subject_code participates in a composite FK to
    Subject with no ON DELETE clause, and retirement never deletes the row
    (curriculum_adjustment_apply_service._set_demand only flips is_active and
    sets retired_at). So a fully retired demand row must still block a raw
    ORM delete + commit, independent of any application-level pre-check.
    """
    db = _db(); _extra_seed(db)
    subject = db.query(models.Subject).filter_by(subject_code="RET3").one()

    db.delete(subject)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    assert db.query(models.Subject).filter_by(subject_code="RET3").count() == 1
    assert db.query(models.PlanningSubjectDemand).filter_by(
        subject_code="RET3"
    ).count() == 1


def test_bulk_delete_blocked_by_active_planning_subject_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject = db.query(models.Subject).filter_by(subject_code="ART3").one()

    response = subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject.id], db=db,
    )

    assert response is not None
    assert "active Planning demand" in rendered["error"]
    assert "Curriculum Adjustment" in rendered["error"]
    # the message must not promise that retiring makes the subject deletable
    assert "then delete" not in rendered["error"]
    assert db.get(models.Subject, subject.id) is not None
    demand = db.query(models.PlanningSubjectDemand).filter_by(subject_code="ART3").one()
    assert (demand.is_active, demand.weekly_periods) == (True, 1)


def test_single_delete_blocked_by_active_planning_subject_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject = db.query(models.Subject).filter_by(subject_code="ART3").one()

    response = subjects_router.delete_subject(
        request=object(), subject_id=subject.id, db=db,
    )

    assert response is not None
    assert "active Planning demand" in rendered["error"]
    assert db.get(models.Subject, subject.id) is not None


def test_bulk_delete_blocked_by_retired_planning_subject_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject = db.query(models.Subject).filter_by(subject_code="RET3").one()

    response = subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject.id], db=db,
    )

    assert response is not None
    assert "Planning demand history" in rendered["error"]
    # must not claim retiring is still the outstanding action, since it
    # already happened and the subject is still undeletable
    assert "Retire the Planning demand" not in rendered["error"]
    assert db.get(models.Subject, subject.id) is not None
    demand = db.query(models.PlanningSubjectDemand).filter_by(subject_code="RET3").one()
    assert (demand.is_active, demand.weekly_periods, demand.retired_at is not None) == (False, 0, True)


def test_single_delete_blocked_by_retired_planning_subject_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject = db.query(models.Subject).filter_by(subject_code="RET3").one()

    response = subjects_router.delete_subject(
        request=object(), subject_id=subject.id, db=db,
    )

    assert response is not None
    assert "Planning demand history" in rendered["error"]
    assert db.get(models.Subject, subject.id) is not None


def test_bulk_delete_still_blocked_by_teacher_allocation_when_no_planning_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject = db.query(models.Subject).filter_by(subject_code="PE3").one()

    response = subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject.id], db=db,
    )

    assert response is not None
    assert "assigned to teachers or planning sections" in rendered["error"]
    assert "Planning demand" not in rendered["error"]
    assert db.get(models.Subject, subject.id) is not None


def test_bulk_delete_still_blocked_by_teacher_section_assignment_when_no_planning_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject = db.query(models.Subject).filter_by(subject_code="DAN3").one()

    response = subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject.id], db=db,
    )

    assert response is not None
    assert "assigned to teachers or planning sections" in rendered["error"]
    assert "Planning demand" not in rendered["error"]
    assert db.get(models.Subject, subject.id) is not None


def test_bulk_delete_succeeds_with_no_references(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    subject_id = db.query(models.Subject).filter_by(subject_code="MUS3").one().id

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    assert db.query(models.Subject).filter_by(id=subject_id).first() is None
