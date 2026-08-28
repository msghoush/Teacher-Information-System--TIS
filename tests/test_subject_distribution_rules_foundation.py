import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db_migrations
import models
from subject_distribution_rules import resolve_subject_distribution_rule
from subject_distribution_validator import (
    is_valid_subject_distribution_rule,
    validate_subject_distribution_rule,
)
from timetable_slot_service import build_canonical_slot_projection, is_true_adjacent_period_pair


def _engine():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            models.SchoolGroup(id=1, name="One"),
            models.Branch(id=10, school_group_id=1, name="Main"),
            models.AcademicYear(id=100, school_group_id=1, year_name="2026"),
            models.PlanningSection(
                id=2000, grade_level="3", section_name="A", class_status="Current",
                branch_id=10, academic_year_id=100,
            ),
            models.PlanningSection(
                id=2001, grade_level="3", section_name="B", class_status="Current",
                branch_id=10, academic_year_id=100,
            ),
        ])
        session.commit()
    return engine


# --- Model scope / uniqueness -------------------------------------------------

def test_branch_default_scope_is_unique_per_branch_year():
    engine = _engine()
    with Session(engine) as session:
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="branch_default",
        ))
        session.commit()
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="branch_default",
        ))
        with pytest.raises(IntegrityError):
            session.commit()


def test_grade_scope_is_unique_per_grade_subject():
    engine = _engine()
    with Session(engine) as session:
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="grade",
            grade_level="3", subject_code="ENG",
        ))
        session.commit()
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="grade",
            grade_level="3", subject_code="ENG",
        ))
        with pytest.raises(IntegrityError):
            session.commit()


def test_section_scope_is_unique_per_section_subject():
    engine = _engine()
    with Session(engine) as session:
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="section",
            grade_level="3", subject_code="ENG", section_id=2000,
        ))
        session.commit()
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="section",
            grade_level="3", subject_code="ENG", section_id=2000,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        # A different section for the same grade+subject is a distinct scope.
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="section",
            grade_level="3", subject_code="ENG", section_id=2001,
        ))
        session.commit()


def test_branch_default_shape_check_rejects_grade_or_subject():
    engine = _engine()
    with Session(engine) as session:
        session.add(models.SubjectDistributionRule(
            branch_id=10, academic_year_id=100, scope_level="branch_default",
            grade_level="3",
        ))
        with pytest.raises(IntegrityError):
            session.commit()


# --- Hierarchy resolution -----------------------------------------------------

def test_resolver_returns_none_for_legacy_fallback_when_unconfigured():
    engine = _engine()
    with Session(engine) as session:
        resolved = resolve_subject_distribution_rule(
            session, branch_id=10, academic_year_id=100,
            grade_level="3", subject_code="ENG",
        )
    assert resolved is None


def test_resolver_precedence_section_over_grade_over_branch_default():
    engine = _engine()
    with Session(engine) as session:
        session.add_all([
            models.SubjectDistributionRule(
                branch_id=10, academic_year_id=100, scope_level="branch_default",
                block_count=0, single_count=8, strictness="soft",
            ),
            models.SubjectDistributionRule(
                branch_id=10, academic_year_id=100, scope_level="grade",
                grade_level="3", subject_code="ENG",
                block_count=2, block_length=2, single_count=4, strictness="hard",
            ),
            models.SubjectDistributionRule(
                branch_id=10, academic_year_id=100, scope_level="section",
                grade_level="3", subject_code="ENG", section_id=2000,
                block_count=1, block_length=2, single_count=6,
            ),
        ])
        session.commit()

        section_scoped = resolve_subject_distribution_rule(
            session, branch_id=10, academic_year_id=100,
            grade_level="3", subject_code="ENG", section_id=2000,
        )
        grade_scoped = resolve_subject_distribution_rule(
            session, branch_id=10, academic_year_id=100,
            grade_level="3", subject_code="ENG", section_id=2001,
        )
        other_subject = resolve_subject_distribution_rule(
            session, branch_id=10, academic_year_id=100,
            grade_level="3", subject_code="MAT",
        )

    assert section_scoped["source_scope_level"] == "section"
    assert section_scoped["block_count"] == 1 and section_scoped["single_count"] == 6
    # Field-level inheritance: strictness is unset on the section row (NULL is
    # not possible here since it defaults to "soft"; explicitly re-check the
    # grade row wins when section is absent instead).
    assert grade_scoped["source_scope_level"] == "grade"
    assert grade_scoped["block_count"] == 2 and grade_scoped["strictness"] == "hard"
    assert other_subject["source_scope_level"] == "branch_default"
    assert other_subject["single_count"] == 8


def test_resolver_field_level_inheritance_for_nullable_fields():
    engine = _engine()
    with Session(engine) as session:
        session.add_all([
            models.SubjectDistributionRule(
                branch_id=10, academic_year_id=100, scope_level="branch_default",
                min_teaching_days=3, max_periods_per_day=2,
            ),
            models.SubjectDistributionRule(
                branch_id=10, academic_year_id=100, scope_level="grade",
                grade_level="3", subject_code="ENG",
                min_teaching_days=None, max_periods_per_day=1,
            ),
        ])
        session.commit()
        resolved = resolve_subject_distribution_rule(
            session, branch_id=10, academic_year_id=100,
            grade_level="3", subject_code="ENG",
        )
    # min_teaching_days falls through to the branch default; max_periods_per_day
    # is explicitly set on the grade rule and wins.
    assert resolved["min_teaching_days"] == 3
    assert resolved["max_periods_per_day"] == 1


# --- Arithmetic / feasibility validation --------------------------------------

def test_valid_distribution_matches_planning_weekly_total():
    rule = {"block_length": 2, "block_count": 2, "single_count": 4}
    errors = validate_subject_distribution_rule(rule, planning_weekly_periods=8)
    assert errors == []
    assert is_valid_subject_distribution_rule(rule, planning_weekly_periods=8)


def test_invalid_distribution_total_mismatch():
    rule = {"block_length": 2, "block_count": 3, "single_count": 4}
    errors = validate_subject_distribution_rule(rule, planning_weekly_periods=8)
    assert {"distribution_total_mismatch"} == {item["code"] for item in errors}


def test_negative_values_are_rejected():
    rule = {"block_length": 2, "block_count": -1, "single_count": 4}
    errors = validate_subject_distribution_rule(rule)
    assert "negative_value" in {item["code"] for item in errors}


def test_unsupported_block_length_is_rejected():
    rule = {"block_length": 3, "block_count": 2, "single_count": 2}
    errors = validate_subject_distribution_rule(rule, planning_weekly_periods=8)
    assert "unsupported_block_length" in {item["code"] for item in errors}


def test_min_teaching_days_cannot_exceed_available_days():
    rule = {"block_length": 2, "block_count": 0, "single_count": 4, "min_teaching_days": 6}
    errors = validate_subject_distribution_rule(
        rule, planning_weekly_periods=4, available_teaching_days=5,
    )
    assert "min_teaching_days_exceeds_available" in {item["code"] for item in errors}


def test_max_periods_per_day_infeasible_for_weekly_demand():
    rule = {"block_length": 2, "block_count": 0, "single_count": 8, "max_periods_per_day": 1}
    errors = validate_subject_distribution_rule(
        rule, planning_weekly_periods=8, available_teaching_days=5,
    )
    assert "max_periods_per_day_infeasible" in {item["code"] for item in errors}


def test_invalid_max_periods_per_day_value():
    rule = {"block_length": 2, "block_count": 0, "single_count": 1, "max_periods_per_day": 0}
    errors = validate_subject_distribution_rule(rule)
    assert "invalid_max_periods_per_day" in {item["code"] for item in errors}


# --- True adjacency ------------------------------------------------------------

def _project(blocks):
    return build_canonical_slot_projection(
        school_group_id=1, branch_id=10, academic_year_id=100,
        working_day_keys=["monday"], periods_per_day=4,
        period_duration_minutes=45, school_start_time="07:15",
        blocks=blocks,
    )


def test_adjacent_teaching_slots_with_no_interruption_are_block_adjacent():
    result = _project([])
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 1) is True
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 2) is True
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 3) is True
    # No period 5 exists; the last period is never adjacent to a next one.
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 4) is False


def test_break_between_periods_blocks_adjacency():
    result = _project([{
        "block_type": "break", "label": "Break", "day_key": "all",
        "placement_mode": "after_period", "insert_after_period": 2,
        "duration_minutes": 20,
    }])
    assert result["valid"] is True
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 1) is True
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 2) is False
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 3) is True


def test_prayer_between_periods_blocks_adjacency():
    result = _project([{
        "block_type": "prayer", "label": "Prayer", "day_key": "all",
        "placement_mode": "after_period", "insert_after_period": 3,
        "duration_minutes": 15,
    }])
    assert result["valid"] is True
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 3) is False
    assert is_true_adjacent_period_pair(result["slot_map"], "monday", 1) is True


def test_migration_is_registered():
    assert any(
        item.migration_id == "20260828_003_subject_distribution_rules_foundation"
        for item in db_migrations.MIGRATIONS
    )
