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

    def _fake_render(request, db, current_user, error="", detail_errors=None, open_section_id="", **kwargs):
        captured["error"] = error
        captured["detail_errors"] = detail_errors
        captured["open_section_id"] = open_section_id
        return SimpleNamespace(status_code=200, captured_error=error)

    monkeypatch.setattr(planning_router, "_render_planning_page", _fake_render)
    return captured


def _delete(db, planning_pk=2001):
    return planning_router.delete_planning_section(
        request=object(), planning_pk=planning_pk, db=db,
    )


# ---------------------------------------------------------------------------
# 1. no dependencies -> delete succeeds
# ---------------------------------------------------------------------------
def test_delete_succeeds_for_section_with_no_protected_dependencies(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)  # should not be invoked on the success path

    response = _delete(db)

    assert isinstance(response, RedirectResponse)
    assert db.get(models.PlanningSection, 2001) is None


# ---------------------------------------------------------------------------
# 2. teacher assignment exists -> blocked, NOT auto-deleted
# ---------------------------------------------------------------------------
def test_delete_blocked_by_teacher_assignment_and_does_not_auto_delete_it(db, monkeypatch):
    # Section 2000 in the shared fixture already has TeacherSectionAssignment
    # id=4000. TeacherSectionAssignment is now a blocker like every other
    # dependency - it is no longer silently purged by the delete route.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    response = _delete(db, planning_pk=2000)

    assert response is not None
    assert "teacher assignments" in rendered["error"]
    assert "Remove the teacher assignments first" in rendered["error"]
    assert db.get(models.PlanningSection, 2000) is not None
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2000
    ).count() == 1


# ---------------------------------------------------------------------------
# 3. PlanningSubjectDemand exists -> blocked, split into removable vs permanent
# ---------------------------------------------------------------------------
def test_delete_blocked_by_removable_untouched_planning_subject_demand(db, monkeypatch):
    # A row with no updated_by_user_id has never been acted on through
    # Curriculum Adjustment - it is exactly what the one-time setup backfill
    # migration leaves behind - so it must be reported as removable, with a
    # concrete action, not as permanent history.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    ))
    db.commit()

    response = _delete(db)

    assert response is not None
    assert "Planning subject demand" in rendered["error"]
    assert "set automatically during setup" in rendered["error"]
    assert "Remove demand" in rendered["error"]
    assert "TIS preserves" not in rendered["error"]
    # customer-safe: no table/FK/SQL identifiers leaked
    assert "planning_subject_demands" not in rendered["error"]
    assert "IntegrityError" not in rendered["error"]

    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).count() == 1


def test_delete_blocked_by_permanent_curriculum_adjustment_touched_demand(db, monkeypatch):
    # Any row Curriculum Adjustment has created or modified - active or
    # retired - carries a real updated_by_user_id and is genuine history that
    # TIS preserves forever; retirement never deletes the row (only
    # is_active/retired_at change), so it must never promise "remove and
    # retry" the way the removable case does.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=0, is_active=False,
        retired_at=datetime.utcnow(), updated_by_user_id="U1",
    ))
    db.commit()

    response = _delete(db)

    assert response is not None
    assert "Planning subject demand" in rendered["error"]
    assert "TIS preserves" in rendered["error"]
    assert "permanently" in rendered["error"]
    assert "Remove demand" not in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None
    demand = db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).one()
    assert (demand.is_active, demand.weekly_periods) == (False, 0)


# ---------------------------------------------------------------------------
# Remove-demand action: the actual admin path for the removable case
# ---------------------------------------------------------------------------
def _remove_demand(db, demand_id, return_to="/planning"):
    return planning_router.delete_planning_subject_demand(
        request=object(), demand_id=demand_id, return_to=return_to, db=db,
    )


def test_remove_demand_deletes_an_untouched_row_and_permission_scope_apply(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    response = _remove_demand(db, demand.id)

    assert isinstance(response, RedirectResponse)
    assert db.get(models.PlanningSubjectDemand, demand.id) is None


def test_remove_demand_refuses_a_curriculum_adjustment_touched_row(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=2, is_active=True,
        updated_by_user_id="U1",
    )
    db.add(demand)
    db.commit()

    response = _remove_demand(db, demand.id)

    assert response is not None
    assert "Curriculum Adjustment history" in rendered["error"]
    assert db.get(models.PlanningSubjectDemand, demand.id) is not None


def test_remove_demand_requires_permission_and_is_scoped(db, monkeypatch):
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    _patch_auth(monkeypatch, permission=False)
    response = _remove_demand(db, demand.id)
    assert isinstance(response, RedirectResponse)
    assert db.get(models.PlanningSubjectDemand, demand.id) is not None


# ---------------------------------------------------------------------------
# return_to: reopen the same Planning section after Remove demand
# ---------------------------------------------------------------------------
def test_remove_demand_success_redirects_back_to_the_same_section_fragment(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    response = _remove_demand(
        db, demand.id, return_to="/planning#planning-section-2001",
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning#planning-section-2001"
    assert db.get(models.PlanningSubjectDemand, demand.id) is None


def test_remove_demand_rejects_external_return_to(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    response = _remove_demand(
        db, demand.id, return_to="http://evil.example.com/steal",
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning"
    assert db.get(models.PlanningSubjectDemand, demand.id) is None


def test_remove_demand_rejects_protocol_relative_return_to(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    response = _remove_demand(db, demand.id, return_to="//evil.example.com/steal")

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning"
    assert db.get(models.PlanningSubjectDemand, demand.id) is None


def test_remove_demand_missing_return_to_falls_back_to_plain_planning(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    response = planning_router.delete_planning_subject_demand(
        request=object(), demand_id=demand.id, db=db,
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning"


def test_remove_demand_permission_denied_ignores_supplied_return_to(db, monkeypatch):
    # An unsafe or foreign return_to must never leak through the permission
    # gate either - the denial path stays a fixed "/planning" regardless.
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    _patch_auth(monkeypatch, permission=False)
    response = _remove_demand(
        db, demand.id, return_to="http://evil.example.com/steal",
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning"
    assert db.get(models.PlanningSubjectDemand, demand.id) is not None


def test_remove_demand_not_found_still_honors_safe_return_to(db, monkeypatch):
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)

    response = _remove_demand(
        db, 999999, return_to="/planning#planning-section-2001",
    )

    assert isinstance(response, RedirectResponse)
    assert response.headers["location"] == "/planning#planning-section-2001"


def test_remove_demand_permanent_block_reopens_the_same_section_in_place(db, monkeypatch):
    # Even the in-place render (no redirect - the row is permanent) should
    # tell the shared client script which section to reopen.
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=2, is_active=True,
        updated_by_user_id="U1",
    )
    db.add(demand)
    db.commit()

    _remove_demand(db, demand.id)

    assert rendered.get("open_section_id") == "planning-section-2001"

    # a user scoped to a different branch/year cannot reach it either
    _patch_auth(monkeypatch, user=_user(branch_id=20, academic_year_id=200))
    response = _remove_demand(db, demand.id)
    assert isinstance(response, RedirectResponse)
    assert db.get(models.PlanningSubjectDemand, demand.id) is not None


# ---------------------------------------------------------------------------
# Complete flow: create -> blocked -> admin removes the dependency -> retry succeeds
# ---------------------------------------------------------------------------
def test_full_flow_setup_only_demand_blocks_then_removal_allows_section_delete(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    # 1. a normal setup-only section and its Planning demand (as the one-time
    #    backfill migration would create it - no updated_by_user_id).
    section = models.PlanningSection(
        grade_level="1", section_name="Z", class_status="Current",
        branch_id=10, academic_year_id=100,
    )
    db.add(section)
    db.flush()
    demand = models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=section.id,
        subject_code="MAT", weekly_periods=4, is_active=True,
    )
    db.add(demand)
    db.commit()

    # 2. attempt delete -> blocked and told exactly what to do
    first_attempt = _delete(db, planning_pk=section.id)
    assert first_attempt is not None
    assert "set automatically during setup" in rendered["error"]
    assert db.get(models.PlanningSection, section.id) is not None

    # 3. admin removes the dependency through the supported action
    removal = _remove_demand(db, demand.id)
    assert isinstance(removal, RedirectResponse)
    assert db.get(models.PlanningSubjectDemand, demand.id) is None

    # 4. retry -> succeeds
    second_attempt = _delete(db, planning_pk=section.id)
    assert isinstance(second_attempt, RedirectResponse)
    assert db.get(models.PlanningSection, section.id) is None


# ---------------------------------------------------------------------------
# 4. scheduling / calendar / rule dependencies -> blocked
# ---------------------------------------------------------------------------
def test_delete_blocked_by_teacher_scheduling_rule_target(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    rule = models.TeacherSchedulingRule(
        id=9000, school_group_id=1, branch_id=10, academic_year_id=100,
        teacher_id=1000, rule_type="unavailable", target_scope="selected_sections",
        strictness="hard",
    )
    db.add(rule)
    db.commit()
    db.add(models.TeacherSchedulingRuleTarget(
        rule_id=rule.id, branch_id=10, academic_year_id=100,
        target_type="section", planning_section_id=2001,
    ))
    db.commit()

    response = _delete(db)

    assert response is not None
    assert "teacher scheduling rules" in rendered["error"]
    assert "Remove this section from that rule's targets first" in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None


def test_delete_blocked_by_academic_calendar_event_target(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    event_type = models.CalendarEventType(
        branch_id=10, academic_year_id=100, name="Type", color="#000000", icon="calendar",
    )
    db.add(event_type)
    db.commit()
    db.add(models.CalendarEvent(
        branch_id=10, academic_year_id=100, event_type_id=event_type.id,
        title="Assembly", event_date="2026-09-10", target_group="Section",
        target_section_id=2001,
    ))
    db.commit()

    response = _delete(db)

    assert response is not None
    assert "academic calendar events" in rendered["error"]
    assert "Remove or retarget those calendar events first" in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None


def test_delete_blocked_by_subject_distribution_rule_section_override(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="section",
        grade_level="1", subject_code="MAT", section_id=2001,
        block_length=2, block_count=1, single_count=0,
    ))
    db.commit()

    response = _delete(db)

    assert response is not None
    assert "subject scheduling rules" in rendered["error"]
    assert "Clear that subject scheduling rule override first" in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None


# ---------------------------------------------------------------------------
# 5. timetable dependency -> blocked
# ---------------------------------------------------------------------------
def test_delete_blocked_by_timetable_entry(db, monkeypatch):
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

    response = _delete(db)

    assert response is not None
    assert "timetable placements" in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.TimetableEntry).filter_by(
        planning_section_id=2001
    ).count() == 1


# ---------------------------------------------------------------------------
# 6. multiple blockers -> one clear combined message
# ---------------------------------------------------------------------------
def test_delete_blocked_by_multiple_dependencies_shows_combined_detail_list(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    db.add(models.TeacherSectionAssignment(
        teacher_id=1000, planning_section_id=2001, subject_code="MAT",
    ))
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=2001,
        subject_code="MAT", weekly_periods=4, is_active=True,
    ))
    db.commit()

    response = _delete(db)

    assert response is not None
    assert rendered["detail_errors"] is not None
    assert len(rendered["detail_errors"]) == 2
    joined = " ".join(rendered["detail_errors"])
    assert "teacher assignments" in joined
    assert "Planning subject demand" in joined
    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2001
    ).count() == 1
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).count() == 1


# ---------------------------------------------------------------------------
# 7. after the blocker is removed -> retry succeeds
# ---------------------------------------------------------------------------
def test_delete_succeeds_after_admin_removes_the_blocking_teacher_assignment(db, monkeypatch):
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)

    assignment = models.TeacherSectionAssignment(
        teacher_id=1000, planning_section_id=2001, subject_code="MAT",
    )
    db.add(assignment)
    db.commit()

    first_attempt = _delete(db)
    assert first_attempt is not None
    assert "teacher assignments" in rendered["error"]
    assert db.get(models.PlanningSection, 2001) is not None

    # Admin manually removes the dependency (e.g. via Edit Planning Section).
    db.delete(assignment)
    db.commit()

    second_attempt = _delete(db)
    assert isinstance(second_attempt, RedirectResponse)
    assert db.get(models.PlanningSection, 2001) is None


# ---------------------------------------------------------------------------
# 8. unexpected IntegrityError -> rollback, safe message, no 500
# ---------------------------------------------------------------------------
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

    response = _delete(db)

    assert response is not None
    assert rendered["error"] == planning_router._PLANNING_SECTION_DELETE_INTEGRITY_FALLBACK_MESSAGE
    assert db.get(models.PlanningSection, 2001) is not None
    assert db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=2001
    ).count() == 1


# ---------------------------------------------------------------------------
# permission / scope
# ---------------------------------------------------------------------------
def test_delete_requires_permission(db, monkeypatch):
    _patch_auth(monkeypatch, permission=False)
    rendered = _patch_render(monkeypatch)

    response = _delete(db)

    assert isinstance(response, RedirectResponse)
    assert "error" not in rendered
    assert db.get(models.PlanningSection, 2001) is not None


def test_delete_is_scoped_to_branch_and_academic_year(db, monkeypatch):
    # planning_pk 2001 belongs to branch 10 / year 100; a user scoped to the
    # other tenant (branch 20 / year 200) must not be able to reach it.
    _patch_auth(monkeypatch, user=_user(branch_id=20, academic_year_id=200))
    rendered = _patch_render(monkeypatch)

    response = _delete(db)

    assert isinstance(response, RedirectResponse)
    assert "error" not in rendered
    assert db.get(models.PlanningSection, 2001) is not None
