from datetime import datetime

import pytest

import db_migrations
import models
import curriculum_adjustment_apply_service as apply_service
from curriculum_adjustment_apply_service import (
    CurriculumAdjustmentApplyError,
    CurriculumAdjustmentApplyRequest,
    apply_curriculum_adjustment,
)
from curriculum_adjustment_preview_service import build_curriculum_adjustment_preview
from test_curriculum_adjustment_preview import _db, _request, _seed


def _ready_db():
    db = _db(); _seed(db)
    db.add(models.User(
        user_id="U1", username="admin", first_name="Admin", last_name="User",
        school_group_id=1, branch_id=10, academic_year_id=100,
    ))
    for teacher_id in (5000, 5001, 5002):
        db.add(models.TeacherSubjectAllocation(teacher_id=teacher_id, subject_code="WEL3"))
    db.commit()
    return db


def _review(db, request=None):
    request = request or _request("selected_sections", section_ids=(3000,))
    preview = build_curriculum_adjustment_preview(
        db, school_group_id=1, branch_id=10, academic_year_id=100, request=request,
    )
    return request, preview


def _apply(db, request, preview, decisions):
    return apply_curriculum_adjustment(
        db, school_group_id=1, branch_id=10, academic_year_id=100,
        actor_user_id="U1",
        request=CurriculumAdjustmentApplyRequest(
            preview_request=request,
            preview_fingerprint=preview["preview_fingerprint"],
            teacher_decisions=decisions,
        ),
    )


def _demand(db, section_id, code):
    return db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=section_id, subject_code=code,
    ).order_by(models.PlanningSubjectDemand.is_active.desc(), models.PlanningSubjectDemand.id.desc()).first()


def _add_snapshot(db, snapshot_id=7000):
    db.add(models.TimetableInputSnapshot(
        id=snapshot_id, school_group_id=1, branch_id=10, academic_year_id=100,
        snapshot_schema_version=3, canonical_snapshot_json="{}",
        planning_fingerprint="p" * 64, period_configuration_fingerprint="c" * 64,
        constraint_fingerprint="r" * 64, lock_fingerprint="l" * 64,
        full_input_fingerprint="f" * 64,
    ))
    db.commit()


def _add_draft(db, *, approved=True):
    _add_snapshot(db)
    draft = models.TimetableVersion(
        id=7100, school_group_id=1, branch_id=10, academic_year_id=100,
        version_number=1, lifecycle_status="publication_ready", origin="manual",
        input_snapshot_id=7000, authority_fingerprint="a" * 64,
        approved_at=datetime.utcnow() if approved else None,
        approved_by_user_id="U1" if approved else None,
    )
    db.add(draft); db.commit(); return draft


def test_successful_balanced_transfer_is_atomic_audited_and_section_isolated():
    db = _ready_db(); request, preview = _review(db)
    result = _apply(db, request, preview, {3000: 5001})
    source = _demand(db, 3000, "SOC3"); target = _demand(db, 3000, "WEL3")
    assert (source.weekly_periods, source.is_active) == (0, False)
    assert (target.weekly_periods, target.is_active) == (2, True)
    assert (_demand(db, 3001, "SOC3").weekly_periods, _demand(db, 3001, "WEL3").weekly_periods) == (1, 1)
    assert result["affected_sections"] == [3000]
    audit = db.query(models.CurriculumAdjustmentAudit).one()
    assert audit.actor_user_id == "U1" and audit.status == "applied"


def test_partial_transfer_keeps_source_active_and_matches_reviewed_preview():
    db = _ready_db()
    _demand(db, 3000, "SOC3").weekly_periods = 2
    db.commit()
    request, preview = _review(db)
    assert preview["sections"][0]["source"]["after_weekly_periods"] == 1
    assert preview["sections"][0]["target"]["after_weekly_periods"] == 2
    _apply(db, request, preview, {3000: 5001})
    source = _demand(db, 3000, "SOC3")
    target = _demand(db, 3000, "WEL3")
    assert (source.weekly_periods, source.is_active) == (1, True)
    assert (target.weekly_periods, target.is_active) == (2, True)


def test_reduce_only_two_to_one_is_atomic_without_target_or_teacher_decision():
    db = _ready_db()
    _demand(db, 3000, "SOC3").weekly_periods = 2
    db.commit()
    request = _request(
        "selected_sections", section_ids=(3000,), adjustment_type="reduce_only",
        target_subject_code="",
    )
    request, preview = _review(db, request)
    _apply(db, request, preview, {})
    source = _demand(db, 3000, "SOC3")
    assert (source.weekly_periods, source.is_active) == (1, True)
    assert _demand(db, 3000, "WEL3").weekly_periods == 1
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=3000, subject_code="SOC3"
    ).one().teacher_id == 5000


def test_reduce_only_one_to_zero_retires_source_without_touching_target():
    db = _ready_db()
    request = _request(
        "selected_sections", section_ids=(3000,), adjustment_type="reduce_only",
        target_subject_code="",
    )
    request, preview = _review(db, request)
    _apply(db, request, preview, {})
    assert (_demand(db, 3000, "SOC3").weekly_periods, _demand(db, 3000, "SOC3").is_active) == (0, False)
    assert _demand(db, 3000, "WEL3").weekly_periods == 1
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=3000, subject_code="SOC3"
    ).first() is None


def test_reduce_only_selected_section_invalidates_draft_and_preserves_published_history():
    db = _ready_db(); _add_draft(db)
    published = models.TimetableVersion(
        id=7200, school_group_id=1, branch_id=10, academic_year_id=100,
        version_number=2, lifecycle_status="publication_ready", origin="manual",
        input_snapshot_id=7000, authority_fingerprint="b" * 64,
        published_at=datetime.utcnow(), published_by_user_id="U1",
    )
    db.add(published); db.commit()
    request = _request(
        "selected_sections", section_ids=(3000,), adjustment_type="reduce_only",
        target_subject_code="",
    )
    request, preview = _review(db, request)
    result = _apply(db, request, preview, {})
    draft = db.get(models.TimetableVersion, 7100)
    db.refresh(published)
    assert result["draft_stale"] is True and result["regeneration_required"] is True
    assert draft.is_stale is True and draft.approved_at is None
    assert published.is_stale is False and published.edit_revision == 0


@pytest.mark.parametrize("teacher_id", [5001, 5000, None])
def test_confirmed_target_teacher_can_be_unchanged_changed_or_unassigned(teacher_id):
    db = _ready_db(); request, preview = _review(db)
    _apply(db, request, preview, {3000: teacher_id})
    assignment = db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=3000, subject_code="WEL3"
    ).first()
    assert (assignment.teacher_id if assignment else None) == teacher_id
    assert db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=3000, subject_code="SOC3"
    ).first() is None


def test_invalid_qualification_rolls_back_everything():
    db = _ready_db()
    db.query(models.TeacherSubjectAllocation).filter_by(teacher_id=5000, subject_code="WEL3").delete(); db.commit()
    request, preview = _review(db)
    with pytest.raises(CurriculumAdjustmentApplyError) as exc:
        _apply(db, request, preview, {3000: 5000})
    assert exc.value.code == "teacher_not_qualified"
    assert _demand(db, 3000, "SOC3").is_active is True
    assert db.query(models.CurriculumAdjustmentAudit).count() == 0


def test_over_capacity_choice_is_rejected_against_final_load():
    db = _ready_db(); db.get(models.Teacher, 5001).max_hours = 1; db.commit()
    request, preview = _review(db)
    assert not preview["blockers"]
    with pytest.raises(CurriculumAdjustmentApplyError) as exc:
        _apply(db, request, preview, {3000: 5001})
    assert exc.value.code == "teacher_over_capacity"


def test_stale_fingerprint_rejected_before_write():
    db = _ready_db(); request, preview = _review(db)
    _demand(db, 3000, "WEL3").weekly_periods = 2; db.commit()
    with pytest.raises(CurriculumAdjustmentApplyError) as exc:
        _apply(db, request, preview, {3000: 5001})
    assert exc.value.code == "stale_preview"
    assert db.query(models.CurriculumAdjustmentAudit).count() == 0


def test_active_generation_rejected_before_write():
    db = _ready_db(); _add_snapshot(db)
    db.add(models.TimetableGenerationRun(
        school_group_id=1, branch_id=10, academic_year_id=100,
        requested_by_user_id="U1", request_mode="generate", input_snapshot_id=7000,
        status="queued", progress_phase="queued", idempotency_key="active",
    )); db.commit()
    request, preview = _review(db)
    with pytest.raises(CurriculumAdjustmentApplyError) as exc:
        _apply(db, request, preview, {3000: 5001})
    assert exc.value.code == "active_generation_conflict"


def test_target_rule_conflict_blocks_and_preserves_demands():
    db = _ready_db()
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="section", grade_level="3",
        subject_code="WEL3", section_id=3000, block_length=2, block_count=0,
        single_count=1, strictness="hard",
    )); db.commit()
    request, preview = _review(db)
    assert "subject_distribution_rule_invalid" in {item["code"] for item in preview["blockers"]}
    with pytest.raises(CurriculumAdjustmentApplyError) as exc:
        _apply(db, request, preview, {3000: 5001})
    assert exc.value.code == "preview_blocked"
    assert _demand(db, 3000, "SOC3").is_active is True


def test_source_zero_retires_active_section_rule():
    db = _ready_db()
    rule = models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="section", grade_level="3",
        subject_code="SOC3", section_id=3000, block_length=2, block_count=0,
        single_count=1, strictness="hard",
    )
    db.add(rule); db.commit()
    request, preview = _review(db)
    assert not preview["blockers"]
    _apply(db, request, preview, {3000: 5001})
    assert rule.is_active is False


def test_unexpected_failure_rolls_back_prior_demand_mutation(monkeypatch):
    db = _ready_db(); request, preview = _review(db)
    original = apply_service._set_demand
    calls = {"count": 0}
    def fail_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("forced failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(apply_service, "_set_demand", fail_second)
    with pytest.raises(RuntimeError, match="forced failure"):
        _apply(db, request, preview, {3000: 5001})
    assert _demand(db, 3000, "SOC3").is_active is True
    assert db.query(models.CurriculumAdjustmentAudit).count() == 0


def test_draft_approval_is_cleared_and_draft_marked_stale():
    db = _ready_db(); _add_draft(db)
    request, preview = _review(db)
    result = _apply(db, request, preview, {3000: 5001})
    draft = db.get(models.TimetableVersion, 7100)
    assert draft.is_stale is True and draft.approved_at is None and draft.approved_by_user_id is None
    assert draft.edit_revision == 1
    assert result["draft_stale"] is True and result["regeneration_required"] is True


def test_invalid_source_lock_blocks_and_rolls_back():
    db = _ready_db(); draft = _add_draft(db, approved=False)
    db.add(models.TimetableEntry(
        timetable_version_id=draft.id, branch_id=10, academic_year_id=100,
        planning_section_id=3000, subject_code="SOC3", teacher_id=5000,
        day_key="monday", period_index=1, is_locked=True,
    )); db.commit()
    request, preview = _review(db)
    with pytest.raises(CurriculumAdjustmentApplyError) as exc:
        _apply(db, request, preview, {3000: 5001})
    assert exc.value.code == "invalid_locked_placement"
    assert _demand(db, 3000, "SOC3").is_active is True


def test_published_version_and_active_pointer_are_untouched():
    db = _ready_db(); _add_snapshot(db)
    published = models.TimetableVersion(
        id=7200, school_group_id=1, branch_id=10, academic_year_id=100,
        version_number=1, lifecycle_status="publication_ready", origin="manual",
        input_snapshot_id=7000, authority_fingerprint="a" * 64,
        published_at=datetime.utcnow(), published_by_user_id="U1",
    )
    db.add(published); db.flush()
    pointer = models.TimetableActiveVersion(
        school_group_id=1, branch_id=10, academic_year_id=100,
        timetable_version_id=published.id, activated_by_user_id="U1",
    )
    db.add(pointer); db.commit()
    request, preview = _review(db); _apply(db, request, preview, {3000: 5001})
    db.refresh(published); db.refresh(pointer)
    assert published.is_stale is False and published.edit_revision == 0
    assert pointer.timetable_version_id == 7200 and pointer.revision == 0


def test_duplicate_apply_returns_same_adjustment_without_second_write():
    db = _ready_db(); request, preview = _review(db)
    first = _apply(db, request, preview, {3000: 5001})
    second = _apply(db, request, preview, {3000: 5001})
    assert second["adjustment_id"] == first["adjustment_id"] and second["duplicate"] is True
    assert db.query(models.CurriculumAdjustmentAudit).count() == 1


def test_tenant_scope_mismatch_is_rejected():
    db = _ready_db(); request, preview = _review(db)
    with pytest.raises(ValueError) as exc:
        apply_curriculum_adjustment(
            db, school_group_id=2, branch_id=10, academic_year_id=100,
            actor_user_id="U1", request=CurriculumAdjustmentApplyRequest(
                preview_request=request, preview_fingerprint=preview["preview_fingerprint"],
                teacher_decisions={3000: 5001},
            ),
        )
    assert getattr(exc.value, "code", None) == "scope_mismatch"


def test_migration_registered():
    assert any(
        migration.migration_id == "20260829_001_curriculum_adjustment_apply_foundation"
        for migration in db_migrations.MIGRATIONS
    )
