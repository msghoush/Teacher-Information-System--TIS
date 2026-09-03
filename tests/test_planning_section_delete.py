from datetime import datetime
from types import SimpleNamespace

from fastapi.responses import RedirectResponse

import models
from routers import planning as planning_router
from timetable_version_service import create_manual_draft
from test_timetable_versioning import db  # noqa: F401 - shared focused fixture


def _user(branch_id=10, academic_year_id=100):
    return SimpleNamespace(user_id="U1", branch_id=branch_id, academic_year_id=academic_year_id)


def _patch_auth(monkeypatch, permission=True, user=None):
    monkeypatch.setattr(
        planning_router, "get_current_user", lambda request, db: (user or _user())
    )
    monkeypatch.setattr(planning_router.auth, "has_permission", lambda *a, **k: permission)


def _patch_render(monkeypatch):
    captured = {}

    def _fake_render(request, db, current_user, error="", **kwargs):
        captured["error"] = error
        return SimpleNamespace(status_code=200, captured_error=error)

    monkeypatch.setattr(planning_router, "_render_planning_page", _fake_render)
    return captured


def test_delete_blocked_by_active_planning_subject_demand_shows_safe_message_and_preserves_data(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    ))
    db.commit()

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert response is not None
    assert "Planning demand history" in rendered["error"]
    assert "cannot be" in rendered["error"]
    # must not instruct the user to retire the demand as a fix - retirement
    # never deletes the row, so it would not make the section deletable
    assert "retire the" not in rendered["error"].lower()
    assert "first" not in rendered["error"].lower()
    # customer-safe: no table/FK/SQL identifiers leaked
    assert "planning_subject_demands" not in rendered["error"]
    assert "IntegrityError" not in rendered["error"]

    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).count() == 1


def test_delete_blocked_by_retired_planning_subject_demand_shows_same_honest_message(db, monkeypatch):
    # Curriculum Adjustment retirement (_set_demand) never deletes the row -
    # it only flips is_active/retired_at - so a fully retired demand row
    # must block deletion identically to an active one, with the same
    # non-promising message.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=0, is_active=False,
        retired_at=datetime.utcnow(),
    ))
    db.commit()

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert response is not None
    assert "Planning demand history" in rendered["error"]
    assert "retire the" not in rendered["error"].lower()
    assert "first" not in rendered["error"].lower()
    assert db.get(models.PlanningSection, 2001) is not None
    demand = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).one()
    assert (demand.is_active, demand.weekly_periods) == (False, 0)


def test_delete_blocked_by_timetable_entry_shows_generic_safe_message_and_preserves_data(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="manual",
    )
    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT", teacher_id=1000,
        day_key="monday", period_index=1,
    ))
    db.commit()

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert response is not None
    assert rendered["error"] == planning_router._PLANNING_SECTION_DELETE_GENERIC_BLOCKED_MESSAGE
    assert "referenced by academic records" in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.TimetableEntry).filter_by(
        planning_section_id=2001
    ).count() == 1


def test_delete_succeeds_for_section_with_no_protected_dependencies(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)  # should not be invoked on the success path

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert isinstance(response, RedirectResponse)
    assert db.get(models.PlanningSection, 2001) is None


def test_existing_teacher_section_assignment_dependency_still_deletes_cleanly(db, monkeypatch):
    # Section 2000 in the shared fixture already has TeacherSectionAssignment id=4000.
    # This is the one dependency the route is intended to purge automatically.
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2000, db=db,
    )

    assert isinstance(response, RedirectResponse)
    assert db.get(models.PlanningSection, 2000) is None
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000
    ).count() == 0


def test_delete_requires_permission(db, monkeypatch):
    _patch_auth(monkeypatch, permission=False)
    rendered = _patch_render(monkeypatch)

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert isinstance(response, RedirectResponse)
    assert "error" not in rendered
    assert db.get(models.PlanningSection, 2001) is not None


def test_delete_is_scoped_to_branch_and_academic_year(db, monkeypatch):
    # planning_pk 2001 belongs to branch 10 / year 100; a user scoped to the
    # other tenant (branch 20 / year 200) must not be able to reach it.
    _patch_auth(monkeypatch, user=_user(branch_id=20, academic_year_id=200))
    rendered = _patch_render(monkeypatch)

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert isinstance(response, RedirectResponse)
    assert "error" not in rendered
    assert db.get(models.PlanningSection, 2001) is not None


def test_integrity_error_fallback_when_precheck_misses_a_dependency(db, monkeypatch):
    # Simulate an unforeseen dependency the read-only pre-check does not know
    # about: force the pre-check to report no blockers even though a real FK
    # dependency (PlanningSubjectDemand) still exists, so the commit itself
    # must fail safely rather than raising an uncaught 500.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    monkeypatch.setattr(
        planning_router, "_get_planning_section_delete_blockers", lambda db, section_id: []
    )

    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    ))
    db.commit()

    response = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )

    assert response is not None
    assert rendered["error"] == planning_router._PLANNING_SECTION_DELETE_GENERIC_BLOCKED_MESSAGE
    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).count() == 1
