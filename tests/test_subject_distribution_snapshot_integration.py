"""Stage 2 snapshot/problem-builder integration for resolved Subject
Distribution Rules: resolution precedence at snapshot time, fingerprint
immutability, and a clean pre-solve failure for an invalid configuration."""
import json

import models
from timetable_problem_builder import TimetableProblemBuilder, TimetableProblemError
from timetable_readiness_service import TimetableReadinessService
from timetable_snapshot_service import build_current_snapshot_data
from test_timetable_versioning import db  # noqa: F401 - shared isolated database


def _make_ready(db):
    if not db.query(models.TeacherSectionAssignment).filter_by(
        planning_section_id=2001, subject_code="MAT"
    ).first():
        db.add(models.TeacherSectionAssignment(
            teacher_id=1001, planning_section_id=2001, subject_code="MAT"
        ))
    db.flush()


def test_snapshot_embeds_resolved_distribution_rule_per_demand(db):
    _make_ready(db)
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="1", subject_code="MAT", block_count=1, single_count=2,
    ))
    db.commit()

    snapshot = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    payload = json.loads(snapshot.canonical_json)
    demands = payload["planning"]["demands"]
    assert demands
    for demand in demands:
        assert demand["subject_code"] == "MAT"
        rule = demand["distribution_rule"]
        assert rule is not None
        assert rule["block_count"] == 1 and rule["single_count"] == 2
        assert rule["source_scope_level"] == "grade"


def test_later_rule_change_does_not_alter_an_already_created_snapshot(db):
    _make_ready(db)
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="1", subject_code="MAT", block_count=0, single_count=4,
    ))
    db.commit()
    first = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    first_payload = json.loads(first.canonical_json)

    rule_row = db.query(models.SubjectDistributionRule).filter_by(
        branch_id=10, academic_year_id=100, scope_level="grade",
    ).one()
    rule_row.block_count = 2
    rule_row.single_count = 0
    db.commit()

    # The already-created snapshot's stored JSON is untouched; only a fresh
    # snapshot reflects the new configuration.
    assert json.loads(first.canonical_json) == first_payload
    second = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    assert second.planning_fingerprint != first.planning_fingerprint


def test_precedence_section_override_wins_over_grade_and_branch_default(db):
    _make_ready(db)
    db.add_all([
        models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="branch_default",
            single_count=4,
        ),
        models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="grade",
            grade_level="1", subject_code="MAT", block_count=1, single_count=2,
        ),
        models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="section",
            grade_level="1", subject_code="MAT", section_id=2000,
            block_count=0, single_count=4,
        ),
    ])
    db.commit()

    snapshot = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    payload = json.loads(snapshot.canonical_json)
    by_section = {item["section_id"]: item["distribution_rule"] for item in payload["planning"]["demands"]}
    assert by_section[2000]["source_scope_level"] == "section"
    assert by_section[2000]["single_count"] == 4 and by_section[2000]["block_count"] == 0
    assert by_section[2001]["source_scope_level"] == "grade"
    assert by_section[2001]["block_count"] == 1 and by_section[2001]["single_count"] == 2


def test_invalid_distribution_rule_fails_cleanly_before_solving(db):
    _make_ready(db)
    # Planning demand is 4 weekly periods; this configuration totals 3.
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="1", subject_code="MAT", block_count=1, single_count=1,
    ))
    db.commit()

    snapshot = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    try:
        TimetableProblemBuilder().build(snapshot.canonical_json)
        assert False, "expected TimetableProblemError"
    except TimetableProblemError as exc:
        assert exc.code == "distribution_rule_invalid"


def test_no_normalized_rule_row_falls_back_to_legacy_none(db):
    _make_ready(db)
    snapshot = build_current_snapshot_data(
        db, school_group_id=1, branch_id=10, academic_year_id=100
    )
    payload = json.loads(snapshot.canonical_json)
    for demand in payload["planning"]["demands"]:
        assert demand["distribution_rule"] is None
    problem = TimetableProblemBuilder().build(snapshot.canonical_json)
    assert all(item["distribution_rule"] is None for item in problem["demands"])


def test_readiness_blocks_genuinely_invalid_distribution_configuration(db):
    _make_ready(db)
    db.query(models.TeacherSectionAssignment).filter_by(planning_section_id=2000).delete()
    db.add(models.TeacherSectionAssignment(teacher_id=1000, planning_section_id=2000, subject_code="MAT"))
    # Planning demand is 4 weekly periods; this configuration totals 3.
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="1", subject_code="MAT", block_count=1, single_count=1,
    ))
    db.commit()

    result = TimetableReadinessService(db).evaluate(1, 10, 100)
    blocker_codes = {item["code"] for item in result["blockers"]}
    assert "distribution_rule_distribution_total_mismatch" in blocker_codes
    assert result["status"] != "generation_ready"


def test_readiness_allows_a_valid_distribution_configuration(db):
    _make_ready(db)
    db.add(models.SubjectDistributionRule(
        branch_id=10, academic_year_id=100, scope_level="grade",
        grade_level="1", subject_code="MAT", block_count=0, single_count=4,
    ))
    db.commit()

    result = TimetableReadinessService(db).evaluate(1, 10, 100)
    blocker_codes = {item["code"] for item in result["blockers"]}
    assert not any(code.startswith("distribution_rule_") for code in blocker_codes)
