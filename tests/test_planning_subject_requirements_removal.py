from types import SimpleNamespace

from fastapi.responses import RedirectResponse

import models
from routers import planning as planning_router
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

    def _fake_render(request, db, current_user, error="", detail_errors=None, open_section_id="", **kwargs):
        captured["error"] = error
        captured["detail_errors"] = detail_errors
        captured["open_section_id"] = open_section_id
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(planning_router, "_render_planning_page", _fake_render)
    return captured


def _remove(db, targets, return_to="/planning/"):
    return planning_router.remove_planning_subject_requirements(
        request=object(), target=targets, return_to=return_to, db=db,
    )


def _add_extra_subject(db, code, weekly_hours=3, grade=1, section_id=None, section_grade="1"):
    db.add(models.Subject(
        subject_code=code, subject_name=code.title(), weekly_hours=weekly_hours,
        grade=grade, branch_id=10, academic_year_id=100,
    ))
    if section_id is not None:
        db.add(models.PlanningSection(
            id=section_id, grade_level=section_grade, section_name="Z",
            class_status="Current", branch_id=10, academic_year_id=100,
        ))
    db.commit()


# ---------------------------------------------------------------------------
# 1-4. classification: removable (explicit), permanent, fallback, not_found
# ---------------------------------------------------------------------------
def test_status_removable_for_untouched_explicit_row(db):
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    ))
    db.commit()

    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT",
    )
    assert status == "removable"


def test_status_permanent_for_curriculum_adjustment_touched_row(db):
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=2, is_active=True,
        updated_by_user_id="U1",
    ))
    db.commit()

    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT",
    )
    assert status == "permanent"


def test_status_fallback_for_legacy_requirement_with_no_explicit_row(db):
    # The shared fixture's Subject "MAT" (grade 1, weekly_hours=4) and
    # PlanningSection 2001 (grade_level "1") have no explicit demand row at
    # all - exactly the Art/Well Being case: a genuine current requirement
    # resolved only from the Subject catalog.
    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT",
    )
    assert status == "fallback"


def test_status_not_found_when_no_active_requirement_exists(db):
    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="NOPE",
    )
    assert status == "not_found"


# ---------------------------------------------------------------------------
# 5. single removal still works - both explicit and fallback targets
# ---------------------------------------------------------------------------
def test_single_removal_deletes_an_untouched_explicit_row(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    ))
    db.commit()

    response = _remove(db, ["2001:MAT"])

    assert isinstance(response, RedirectResponse)
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT",
    ).count() == 0


def test_single_removal_suppresses_a_fallback_requirement_with_a_setup_only_row(db, monkeypatch):
    # The suppression row must NOT look like Curriculum Adjustment history:
    # created_by_user_id records who suppressed it (auditable), but
    # updated_by_user_id stays NULL so it remains classified setup-only /
    # removable rather than instantly becoming permanent.
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)

    response = _remove(db, ["2001:MAT"])

    assert isinstance(response, RedirectResponse)
    row = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT",
    ).one()
    assert (row.is_active, row.weekly_periods) == (False, 0)
    assert row.created_by_user_id == "U1"
    assert row.updated_by_user_id is None
    # no longer an active requirement, so nothing left to "remove" here...
    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT",
    )
    assert status == "not_found"
    # ...but the leftover row is still classified setup-only/removable for
    # Planning-section-delete purposes, not permanent.
    section_demand_status = planning_router._get_planning_section_demand_status(
        db, 2001,
    )
    assert section_demand_status == "removable"


# ---------------------------------------------------------------------------
# 6-7. bulk: multiple removable succeed; one section vs multiple sections
# ---------------------------------------------------------------------------
def test_bulk_removal_of_multiple_removable_requirements_in_one_section_succeeds(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    _add_extra_subject(db, "SCI", weekly_hours=3, grade=1)
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="SCI", weekly_periods=3, is_active=True,
    ))
    db.commit()

    # MAT is fallback-only, SCI is an untouched explicit row - both removable.
    response = _remove(db, ["2001:MAT", "2001:SCI"])

    assert isinstance(response, RedirectResponse)
    # single distinct section -> reopen it even though the form's return_to
    # was the bare default
    assert response.headers["location"] == "/planning/#planning-section-2001"
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="SCI",
    ).count() == 0
    suppressed = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT",
    ).one()
    assert (suppressed.is_active, suppressed.weekly_periods) == (False, 0)


def test_bulk_removal_across_multiple_sections_succeeds(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    _add_extra_subject(db, "SCI", weekly_hours=3, grade=1, section_id=2500, section_grade="1")
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2500,
        subject_code="SCI", weekly_periods=3, is_active=True,
    ))
    db.commit()

    response = _remove(db, ["2001:MAT", "2500:SCI"])

    assert isinstance(response, RedirectResponse)
    # more than one distinct section -> no single section to reopen
    assert response.headers["location"] == "/planning/"
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2500, subject_code="SCI",
    ).count() == 0
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT", is_active=False,
    ).count() == 1


# ---------------------------------------------------------------------------
# 8. one protected item in the selection -> none removed
# ---------------------------------------------------------------------------
def test_bulk_removal_blocks_entire_batch_when_one_item_is_protected(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    _add_extra_subject(db, "ART", weekly_hours=2, grade=1)
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="ART", weekly_periods=2, is_active=True,
        updated_by_user_id="U1",
    ))
    db.commit()

    response = _remove(db, ["2001:MAT", "2001:ART"])

    assert response is not None
    combined = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "Curriculum Adjustment history" in combined
    assert "ART".lower() in combined.lower() or "Art" in combined
    # nothing removed - not even the otherwise-removable MAT fallback
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT",
    ).count() == 0  # still fallback, no row created
    art_row = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="ART",
    ).one()
    assert (art_row.is_active, art_row.weekly_periods) == (True, 2)
    assert rendered["open_section_id"] == "planning-section-2001"


# ---------------------------------------------------------------------------
# 9. cross-branch/year id -> whole request rejected
# ---------------------------------------------------------------------------
def test_bulk_removal_rejects_out_of_scope_section(db, monkeypatch):
    _patch_auth(monkeypatch)  # scoped to branch 10 / year 100
    rendered = _patch_render(monkeypatch)

    # section 2001 exists in scope; section 9999 does not exist at all,
    # simulating a foreign/cross-branch id smuggled into the request.
    response = _remove(db, ["2001:MAT", "9999:MAT"])

    assert response is not None
    combined = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "outside your current scope" in combined
    # atomic: the otherwise-removable MAT fallback was not touched either
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT",
    ).count() == 0


# ---------------------------------------------------------------------------
# 10. permission protection
# ---------------------------------------------------------------------------
def test_removal_requires_permission(db, monkeypatch):
    _patch_auth(monkeypatch, permission=False)

    response = _remove(db, ["2001:MAT"])

    assert isinstance(response, RedirectResponse)
    # fallback was never touched
    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT",
    )
    assert status == "fallback"


# ---------------------------------------------------------------------------
# 11. same-section reopen state preserved via return_to
# ---------------------------------------------------------------------------
def test_single_removal_honors_supplied_return_to_fragment(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)

    response = _remove(db, ["2001:MAT"], return_to="/planning/#planning-section-2001")

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning/#planning-section-2001"


# ---------------------------------------------------------------------------
# 12. no teacher/timetable/history records are deleted
# ---------------------------------------------------------------------------
def test_removal_never_touches_teacher_assignments_or_history(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    # section 2000 in the shared fixture already has TeacherSectionAssignment
    # id=4000 (teacher 1000, subject "MAT"). MAT for 2000 is fallback-only.
    response = _remove(db, ["2000:MAT"])

    assert isinstance(response, RedirectResponse)
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000, subject_code="MAT",
    ).count() == 1
    row = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2000, subject_code="MAT",
    ).one()
    assert (row.is_active, row.weekly_periods) == (False, 0)


def test_no_targets_selected_shows_a_safe_message(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    response = _remove(db, [])

    assert response is not None
    assert "Select at least one" in rendered["error"]


# ---------------------------------------------------------------------------
# Complete admin cleanup flow: remove requirement -> clear the leftover
# setup-only suppression row -> Planning section becomes deletable ->
# Subject becomes deletable. This is the exact workflow the updated_by_user_id
# fix exists to unblock.
# ---------------------------------------------------------------------------
def test_full_flow_remove_requirement_then_delete_planning_section(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    # 1. Section 2001 in the shared fixture has exactly one requirement,
    #    "MAT", resolved only from the Subject catalog (fallback).
    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="MAT",
    )
    assert status == "fallback"

    # 2. Admin removes it -> a setup-only suppression row is created.
    removal = _remove(db, ["2001:MAT"])
    assert isinstance(removal, RedirectResponse)
    demand = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="MAT",
    ).one()
    assert demand.updated_by_user_id is None

    # 3. Planning section delete is still blocked - the row still physically
    #    exists and holds a real FK - but honestly reported as removable,
    #    never as permanent Curriculum Adjustment history.
    blocked = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )
    assert blocked is not None
    assert "TIS preserves" not in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None

    # 4. Admin clears the leftover setup-only row through the existing
    #    demand-id route, which is exactly what "removable" (not "permanent")
    #    means: updated_by_user_id IS NULL, so it is still hard-deletable.
    cleared = planning_router.delete_planning_subject_demand(
        request=object(), demand_id=demand.id, db=db,
    )
    assert isinstance(cleared, RedirectResponse)
    assert db.get(models.PlanningSubjectDemand, demand.id) is None

    # 5. Planning section can now be physically deleted.
    final = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )
    assert isinstance(final, RedirectResponse)
    assert db.get(models.PlanningSection, 2001) is None


def test_full_flow_remove_requirement_then_delete_subject(db, monkeypatch):
    from routers import subjects as subjects_router

    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    monkeypatch.setattr(subjects_router, "get_current_user", lambda request, db: _user())
    monkeypatch.setattr(subjects_router.auth, "has_permission", lambda *a, **k: True)
    subjects_rendered = {}

    def _fake_subjects_render(request, db, current_user, error="", success="", detail_errors=None, **kwargs):
        subjects_rendered["error"] = error
        subjects_rendered["detail_errors"] = detail_errors
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(subjects_router, "_render_subjects_page", _fake_subjects_render)

    # A dedicated, otherwise-unreferenced subject so the only thing blocking
    # its deletion is the Planning demand suppression row this test creates.
    db.add(models.Subject(
        id=9500, subject_code="FREE1", subject_name="Free Elective",
        weekly_hours=2, grade=1, branch_id=10, academic_year_id=100,
    ))
    db.commit()

    status = planning_router._get_planning_requirement_removal_status(
        db, branch_id=10, academic_year_id=100,
        planning_section_id=2001, subject_code="FREE1",
    )
    assert status == "fallback"

    _remove(db, ["2001:FREE1"])
    demand = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001, subject_code="FREE1",
    ).one()
    assert demand.updated_by_user_id is None

    blocked = subjects_router.delete_subject(request=object(), subject_id=9500, db=db)
    assert blocked is not None
    assert "still used in Planning demand" in subjects_rendered["error"]
    assert db.get(models.Subject, 9500) is not None

    cleared = planning_router.delete_planning_subject_demand(
        request=object(), demand_id=demand.id, db=db,
    )
    assert isinstance(cleared, RedirectResponse)
    assert db.get(models.PlanningSubjectDemand, demand.id) is None

    subjects_router.delete_subject(request=object(), subject_id=9500, db=db)
    assert db.get(models.Subject, 9500) is None


def test_curriculum_adjustment_touched_row_remains_permanent(db, monkeypatch):
    # Regression guard: this fix only changes the setup-only suppression
    # path. A row Curriculum Adjustment genuinely created/modified must stay
    # permanent exactly as before.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=0, is_active=False,
        updated_by_user_id="U1",
    ))
    db.commit()

    section_status = planning_router._get_planning_section_demand_status(db, 2001)
    assert section_status == "permanent"

    blocked = planning_router.delete_planning_section(
        request=object(), planning_pk=2001, db=db,
    )
    assert blocked is not None
    assert "TIS preserves" in rendered["error"]
    assert "permanently" in rendered["error"]


def test_bulk_removal_of_multiple_fallback_requirements_creates_only_setup_only_rows(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    _add_extra_subject(db, "SCI", weekly_hours=3, grade=1)
    _add_extra_subject(db, "PE1", weekly_hours=2, grade=1)

    response = _remove(db, ["2001:MAT", "2001:SCI", "2001:PE1"])

    assert isinstance(response, RedirectResponse)
    rows = db.query(models.PlanningSubjectDemand).filter(
        models.PlanningSubjectDemand.planning_section_id == 2001,
        models.PlanningSubjectDemand.subject_code.in_(["MAT", "SCI", "PE1"]),
    ).all()
    assert len(rows) == 3
    assert all(row.updated_by_user_id is None for row in rows)
    assert all((row.is_active, row.weekly_periods) == (False, 0) for row in rows)
