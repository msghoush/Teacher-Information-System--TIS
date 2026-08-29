import models
from routers.subjects import _decorate_effective_planning_periods
from test_curriculum_adjustment_preview import _db, _seed


def _subjects(db, branch_id=10, academic_year_id=100):
    rows = db.query(models.Subject).filter_by(
        branch_id=branch_id, academic_year_id=academic_year_id
    ).order_by(models.Subject.id).all()
    _decorate_effective_planning_periods(
        db,
        subjects=rows,
        branch_id=branch_id,
        academic_year_id=academic_year_id,
    )
    return {row.subject_code: row for row in rows}


def test_uniform_explicit_planning_demand_replaces_catalog_value_for_display():
    db = _db(); _seed(db)
    for row in db.query(models.PlanningSubjectDemand).filter_by(subject_code="WEL3").all():
        row.weekly_periods = 2
    db.commit()
    subject = _subjects(db)["WEL3"]
    assert subject.weekly_hours == 1
    assert subject.effective_weekly_periods == 2
    assert subject.effective_weekly_periods_display == "2"
    assert subject.effective_weekly_periods_varies is False


def test_different_section_demands_display_varies_with_section_values():
    db = _db(); _seed(db)
    db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=3001, subject_code="WEL3"
    ).one().weekly_periods = 2
    db.commit()
    subject = _subjects(db)["WEL3"]
    assert subject.effective_weekly_periods_display == "Varies"
    assert subject.effective_weekly_periods_varies is True
    assert [(item["section_id"], item["weekly_periods"]) for item in subject.effective_weekly_periods_sections] == [
        (3000, 1), (3001, 2)
    ]


def test_subject_demand_display_is_branch_year_isolated_and_legacy_safe():
    db = _db(); _seed(db)
    db.query(models.PlanningSubjectDemand).filter_by(
        planning_section_id=3000, subject_code="WEL3"
    ).one().weekly_periods = 2
    db.commit()
    tenant_one = _subjects(db)["WEL3"]
    tenant_two = _subjects(db, branch_id=20, academic_year_id=200)["WEL3"]
    assert tenant_one.effective_weekly_periods_display == "Varies"
    assert tenant_two.effective_weekly_periods_display == "1"
