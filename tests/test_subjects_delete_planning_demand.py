from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

import models
from routers import planning as planning_router
from routers import subjects as subjects_router
from timetable_version_service import create_manual_draft
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
    db.add(models.User(
        user_id="U1", username="admin", first_name="Admin", last_name="User",
        school_group_id=1, branch_id=10, academic_year_id=100,
    ))
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
        models.Subject(
            id=9005, subject_code="TT3", subject_name="Theatre",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9006, subject_code="AUD3", subject_name="Audit Trail Subject",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9007, subject_code="SDR3", subject_name="Distribution Ruled Subject",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9008, subject_code="TCH3", subject_name="Teacher Primary Subject",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
        models.Subject(
            id=9009, subject_code="MIX3", subject_name="Mixed Batch Blocked",
            weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
        ),
    ])
    db.commit()

    # ART3: only an untouched PlanningSubjectDemand row - no updated_by_user_id,
    # exactly what the one-time setup backfill migration leaves behind, and no
    # teacher reference at all. This is the "removable" case.
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
    # RET3: a *retired* PlanningSubjectDemand row that Curriculum Adjustment
    # has actually touched (updated_by_user_id set) - exactly what
    # curriculum_adjustment_apply_service._set_demand leaves behind after a
    # zero-out retirement. This is the "permanent" case: genuine history, not
    # setup scaffolding, so it must never be reported as removable.
    db.add(models.PlanningSubjectDemand(
        branch_id=10, academic_year_id=100, planning_section_id=3002,
        subject_code="RET3", weekly_periods=0, is_active=False,
        retired_at=datetime.utcnow(), updated_by_user_id="U1",
    ))
    # CurriculumAdjustmentAudit: AUD3 referenced only as a historical audit
    # source/target code, with no live teacher/assignment/demand row at all.
    db.add(models.CurriculumAdjustmentAudit(
        school_group_id=1, branch_id=10, academic_year_id=100,
        actor_user_id="U1", scope_type="selected_sections",
        source_subject_code="AUD3", target_subject_code="WEL3",
        preview_fingerprint="f" * 64, request_json="{}", per_section_json="[]",
    ))
    # SDR3: only a SubjectDistributionRule (grade-level) row.
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="4", subject_code="SDR3", block_length=2,
        block_count=1, single_count=0,
    ))
    # TCH3: only a Teacher whose primary subject_code is this code.
    db.add(models.Teacher(
        teacher_id="T9", first_name="Prime", last_name="Teacher",
        subject_code="TCH3", branch_id=10, academic_year_id=100,
    ))
    # MIX3: only a TeacherSectionAssignment, used for the mixed-selection test.
    db.add(models.TeacherSectionAssignment(
        teacher_id=5000, planning_section_id=3002, subject_code="MIX3",
    ))
    db.commit()
    # MUS3 and TT3(before its TimetableEntry is added) are left unreferenced.


def _add_timetable_entry_for(db, subject_code, section_id=3002):
    draft = create_manual_draft(
        db, school_group_id=1, branch_id=10, academic_year_id=100, origin="manual",
    )
    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=section_id, subject_code=subject_code, teacher_id=5000,
        day_key="monday", period_index=1,
    ))
    db.commit()


def _patch_auth(monkeypatch, permission=True):
    monkeypatch.setattr(subjects_router, "get_current_user", lambda request, db: _user())
    monkeypatch.setattr(subjects_router.auth, "has_permission", lambda *a, **k: permission)
    # some tests also call routers.planning.delete_planning_subject_demand
    # directly to exercise the cross-page removal flow.
    monkeypatch.setattr(planning_router, "get_current_user", lambda request, db: _user())


def _patch_render(monkeypatch):
    captured = {}

    def _fake_render(request, db, current_user, error="", success="", detail_errors=None, **kwargs):
        captured["error"] = error
        captured["success"] = success
        captured["detail_errors"] = detail_errors
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(subjects_router, "_render_subjects_page", _fake_render)
    return captured


def _subject_id(db, code):
    return db.query(models.Subject).filter_by(subject_code=code).one().id


# ---------------------------------------------------------------------------
# real database FK behavior (documents the constraint this fix is about)
# ---------------------------------------------------------------------------
def test_database_fk_blocks_subject_delete_even_when_demand_is_retired():
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


# ---------------------------------------------------------------------------
# 9. unused subject -> single delete succeeds
# ---------------------------------------------------------------------------
def test_single_delete_succeeds_for_unused_subject(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    subject_id = _subject_id(db, "MUS3")

    subjects_router.delete_subject(request=object(), subject_id=subject_id, db=db)

    assert db.query(models.Subject).filter_by(id=subject_id).first() is None


# ---------------------------------------------------------------------------
# 10. multiple unused subjects -> bulk delete succeeds
# ---------------------------------------------------------------------------
def test_bulk_delete_succeeds_for_multiple_unused_subjects(monkeypatch):
    db = _db(); _extra_seed(db)
    db.add(models.Subject(
        id=9010, subject_code="FREE3", subject_name="Unused Elective",
        weekly_hours=1, grade=4, branch_id=10, academic_year_id=100,
    ))
    db.commit()
    _patch_auth(monkeypatch)
    _patch_render(monkeypatch)
    ids = [_subject_id(db, "MUS3"), _subject_id(db, "FREE3")]

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=ids, db=db,
    )

    assert db.query(models.Subject).filter(models.Subject.id.in_(ids)).count() == 0


# ---------------------------------------------------------------------------
# 11. teacher-related dependency -> blocked with exact reason
# ---------------------------------------------------------------------------
def test_single_delete_blocked_by_teacher_primary_subject(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "TCH3")

    subjects_router.delete_subject(request=object(), subject_id=subject_id, db=db)

    assert "primary subject" in rendered["error"]
    assert db.get(models.Subject, subject_id) is not None


def test_bulk_delete_blocked_by_teacher_allocation(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "PE3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    detail = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "still allocated to a teacher" in detail
    assert db.get(models.Subject, subject_id) is not None


def test_bulk_delete_blocked_by_teacher_section_assignment(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "DAN3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    detail = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "assigned to a teacher for a Planning section" in detail
    assert db.get(models.Subject, subject_id) is not None


# ---------------------------------------------------------------------------
# 12. Planning demand dependency -> blocked with exact reason
# ---------------------------------------------------------------------------
def test_single_delete_blocked_by_removable_untouched_planning_subject_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "ART3")

    subjects_router.delete_subject(request=object(), subject_id=subject_id, db=db)

    assert "set automatically during setup" in rendered["error"]
    assert "Remove demand" in rendered["error"]
    assert "TIS preserves" not in rendered["error"]
    assert db.get(models.Subject, subject_id) is not None


def test_bulk_delete_blocked_by_permanent_curriculum_adjustment_touched_demand(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "RET3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    detail = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "Planning demand history" in detail
    assert "TIS preserves" in detail
    # must not claim removal is still the outstanding action - a touched row
    # is never removable, so this can never become deletable
    assert "Remove demand" not in detail
    assert db.get(models.Subject, subject_id) is not None
    demand = db.query(models.PlanningSubjectDemand).filter_by(subject_code="RET3").one()
    assert (demand.is_active, demand.weekly_periods) == (False, 0)


# ---------------------------------------------------------------------------
# 13. timetable / rule / audit-history dependency -> blocked with exact reason
# ---------------------------------------------------------------------------
def test_single_delete_blocked_by_timetable_entry(monkeypatch):
    db = _db(); _extra_seed(db)
    _add_timetable_entry_for(db, "TT3")
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "TT3")

    subjects_router.delete_subject(request=object(), subject_id=subject_id, db=db)

    assert "timetable placements" in rendered["error"]
    assert db.get(models.Subject, subject_id) is not None
    assert db.query(models.TimetableEntry).filter_by(subject_code="TT3").count() == 1


def test_bulk_delete_blocked_by_curriculum_adjustment_audit_history(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "AUD3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    detail = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "Curriculum Adjustment history" in detail
    assert db.get(models.Subject, subject_id) is not None
    assert db.query(models.CurriculumAdjustmentAudit).filter_by(
        source_subject_code="AUD3"
    ).count() == 1


def test_bulk_delete_blocked_by_subject_distribution_rule(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "SDR3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    detail = " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert "subject scheduling rule" in detail
    assert db.get(models.Subject, subject_id) is not None


# ---------------------------------------------------------------------------
# 14. mixed bulk selection -> none deleted, blocker details shown
# ---------------------------------------------------------------------------
def test_bulk_delete_mixed_selection_deletes_nothing_and_names_the_blocked_one(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    deletable_id = _subject_id(db, "MUS3")
    blocked_id = _subject_id(db, "MIX3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[deletable_id, blocked_id], db=db,
    )

    # atomic: nothing was deleted, not even the otherwise-deletable one
    assert db.get(models.Subject, deletable_id) is not None
    assert db.get(models.Subject, blocked_id) is not None
    assert rendered["detail_errors"] is not None
    combined = " ".join(rendered["detail_errors"])
    assert "MIX3" in combined or "Mixed Batch Blocked" in combined
    assert "MUS3" not in combined and "Music" not in combined


# ---------------------------------------------------------------------------
# 15. after dependencies are removed -> the same bulk delete succeeds
# ---------------------------------------------------------------------------
def test_bulk_delete_succeeds_after_admin_removes_the_blocking_assignment(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    deletable_id = _subject_id(db, "MUS3")
    blocked_id = _subject_id(db, "MIX3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[deletable_id, blocked_id], db=db,
    )
    assert db.get(models.Subject, blocked_id) is not None

    # Admin manually removes the dependency (e.g. via Subjects edit / Planning).
    db.query(models.TeacherSectionAssignment).filter_by(subject_code="MIX3").delete(
        synchronize_session=False
    )
    db.commit()

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[deletable_id, blocked_id], db=db,
    )

    assert db.query(models.Subject).filter(
        models.Subject.id.in_([deletable_id, blocked_id])
    ).count() == 0


# ---------------------------------------------------------------------------
# permission / scope / no-partial-delete safety net
# ---------------------------------------------------------------------------
def test_single_delete_requires_permission(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch, permission=False)
    subject_id = _subject_id(db, "MUS3")

    subjects_router.delete_subject(request=object(), subject_id=subject_id, db=db)

    assert db.get(models.Subject, subject_id) is not None


def test_bulk_delete_requires_permission(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch, permission=False)
    subject_id = _subject_id(db, "MUS3")

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )

    assert db.get(models.Subject, subject_id) is not None


def test_bulk_delete_is_scoped_to_branch_and_academic_year(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    # id 2001 exists only in the other tenant's scope (branch 20 / year 200)
    other_tenant_subject = db.query(models.Subject).filter_by(
        branch_id=20, academic_year_id=200,
    ).first()

    response = subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[other_tenant_subject.id], db=db,
    )

    assert "not found in your current scope" in rendered["error"]
    assert db.get(models.Subject, other_tenant_subject.id) is not None


# ---------------------------------------------------------------------------
# Complete flow: subject referenced only by removable setup demand ->
# bulk delete blocked -> admin removes it -> the same bulk delete succeeds.
# ---------------------------------------------------------------------------
def test_full_flow_bulk_delete_blocked_by_removable_demand_then_succeeds_after_removal(monkeypatch):
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    subject_id = _subject_id(db, "ART3")
    demand = db.query(models.PlanningSubjectDemand).filter_by(subject_code="ART3").one()

    # 6. bulk delete -> blocked with the exact reason
    first_attempt = subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )
    assert first_attempt is not None
    assert "set automatically during setup" in " ".join(
        rendered["detail_errors"] or [rendered["error"]]
    )
    assert db.get(models.Subject, subject_id) is not None

    # 7. admin removes the dependency through the supported Planning action
    removal = planning_router.delete_planning_subject_demand(
        request=object(), demand_id=demand.id, db=db,
    )
    assert db.get(models.PlanningSubjectDemand, demand.id) is None
    assert removal is not None

    # 8. retry the same bulk delete -> succeeds
    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )
    assert db.get(models.Subject, subject_id) is None


def test_permanent_demand_keeps_subject_undeletable_even_after_remove_demand_is_attempted(monkeypatch):
    # 9. genuine Curriculum Adjustment history stays blocked, honestly, and
    # the remove-demand action itself refuses to touch it.
    db = _db(); _extra_seed(db)
    _patch_auth(monkeypatch)
    rendered = _patch_render(monkeypatch)
    monkeypatch.setattr(
        planning_router, "_render_planning_page",
        lambda *a, **k: SimpleNamespace(status_code=200),
    )
    subject_id = _subject_id(db, "RET3")
    demand = db.query(models.PlanningSubjectDemand).filter_by(subject_code="RET3").one()

    removal_attempt = planning_router.delete_planning_subject_demand(
        request=object(), demand_id=demand.id, db=db,
    )
    assert removal_attempt is not None
    assert db.get(models.PlanningSubjectDemand, demand.id) is not None

    subjects_router.delete_subjects_bulk(
        request=object(), selected_subject_ids=[subject_id], db=db,
    )
    assert "TIS preserves" in " ".join(rendered["detail_errors"] or [rendered["error"]])
    assert db.get(models.Subject, subject_id) is not None
