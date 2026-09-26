"""Executive Overview semantic and privacy contract."""
from datetime import datetime

import models
import pytest
import talent_executive_overview_service as overview_svc
from dependencies import get_m10_organization_analytics_db
from routers.talent_results_analytics import router as results_router
from student_academic_service import create_placement, create_student
from talent_analytics_privacy import AllowAllTestPolicy, DeterministicSuppressionTestPolicy
from talent_dashboard_service import DashboardError
from talent_executive_overview_service import build_executive_overview
from test_talent_evaluation_progress import (
    _10_level_program, _link_and_open, activate_plan, add_period, create_cycle,
    create_plan, db, scenario,
)


def project(db, **filters):
    return build_executive_overview(
        db, group_id=1, year_id=100, visible_branches=None, filters=filters,
        policy=AllowAllTestPolicy(), identity_allowed=True, can_configure=True,
    )


def test_expected_assessment_grain_and_active_period_rule(db, scenario):
    data = project(db)
    assert data['semantics']['expected_grain'] == 'eligible_student_x_applicable_program_x_opened_period'
    assert data['summary']['students']['value'] == 5
    assert data['summary']['expected']['value'] == 10  # five eligible Students x two opened Periods
    assert data['summary']['completed']['value'] == 4
    assert data['summary']['remaining']['value'] == 6
    assert data['summary']['completed']['percentage'] == 40
    assert {row['id'] for row in data['filters']['periods']} == {str(scenario['p1'].id), str(scenario['p2'].id)}
    assert str(scenario['p3_future'].id) not in {row['id'] for row in data['filters']['periods']}
    assert str(scenario['p4_cancelled'].id) not in {row['id'] for row in data['filters']['periods']}
    assert data['summary']['expected']['value'] == (
        data['summary']['completed']['value'] + data['summary']['remaining']['value']
    )
    completion = {bucket['label']: bucket for bucket in data['completion']['buckets']}
    assert completion['Completed']['count'] == data['summary']['completed']['value']
    assert completion['Remaining']['count'] == data['summary']['remaining']['value']
    assert completion['Completed']['percentage'] == data['summary']['completed']['percentage']


def test_period_program_grade_and_branch_filters_change_one_denominator(db, scenario):
    p1 = project(db, period_id=str(scenario['p1'].id))
    assert (p1['summary']['expected']['value'], p1['summary']['completed']['value']) == (5, 3)
    assert project(db, program_id=str(scenario['program'].id))['summary']['expected']['value'] == 10
    assert project(db, grade_level='1')['summary']['expected']['value'] == 10
    branch_a = project(db, branch_id='10')
    assert (branch_a['summary']['expected']['value'], branch_a['summary']['completed']['value']) == (6, 3)


def test_ineligible_student_is_not_expected_remaining_or_program_cell(db, scenario):
    db.add(models.PlanningSection(id=1002, branch_id=10, academic_year_id=100,
                                  grade_level='5', section_name='C', class_status='Current'))
    db.flush()
    student = create_student(db, school_group_id=1, first_name='Grade Five', last_name='Learner')
    create_placement(db, school_group_id=1, student_id=student.id, academic_year_id=100,
                     branch_id=10, planning_section_id=1002, effective_from=datetime(2026, 9, 1))
    db.flush()
    data = project(db)
    assert data['summary']['students']['value'] == 5
    assert data['summary']['expected']['value'] == 10
    assert all(row['student_id'] != student.id for row in data['students'])


def test_expected_student_missing_from_cycle_population_still_counts_remaining(db, scenario):
    missing = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        cycle_id=scenario['cycle2'].id,
        student_id=scenario['students']['b2'].id,
    ).one()
    db.delete(missing)
    db.commit()
    assert db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        cycle_id=scenario['cycle2'].id,
    ).count() == 4

    data = project(db, branch_id='11', period_id=str(scenario['p2'].id))
    assert data['summary']['students']['value'] == 2
    assert data['summary']['expected']['value'] == 2
    assert data['summary']['completed']['value'] == 0
    assert data['summary']['remaining']['value'] == 2


def test_inactive_student_is_excluded_from_scope_and_every_denominator(db, scenario):
    scenario['students']['b2'].status = 'inactive'
    db.commit()
    data = project(db)
    assert data['summary']['students']['value'] == 4
    assert data['summary']['expected']['value'] == 8
    assert data['summary']['remaining']['value'] == 4
    assert all(row['student_id'] != scenario['students']['b2'].id for row in data['students'])


def test_all_branches_sums_raw_counts_not_branch_percentages(db, scenario):
    data = project(db)
    assert data['summary']['completed']['percentage'] == 40
    rates = {}
    for row in data['branch_breakdown']:
        completed = next(b for b in row['completion']['buckets'] if b['label'] == 'Completed')
        rates[row['id']] = completed['percentage']
    assert rates == {'10': 50, '11': 25}
    assert data['summary']['completed']['percentage'] != sum(rates.values()) / len(rates)


def test_one_student_row_program_result_and_exceptional_only_talented(db, scenario):
    data = project(db)
    assert len(data['students']) == 5
    a1 = next(row for row in data['students'] if row['student_id'] == scenario['students']['a1'].id)
    assert len(a1['programs']) == 1
    assert a1['programs'][0]['normalized_percent'] == 85
    assert a1['programs'][0]['is_talented'] is (a1['programs'][0]['classification'] == 'Exceptional')
    assert 'review' not in str(a1).lower() and 'identification' not in str(a1).lower()


def test_all_periods_delegates_to_governed_current_overall_authority(db, scenario, monkeypatch):
    calls = []
    real = overview_svc.current_overall_result

    def governed(active_periods, normalized_percent_by_cycle):
        calls.append((active_periods, normalized_percent_by_cycle))
        return real(active_periods, normalized_percent_by_cycle)

    monkeypatch.setattr(overview_svc, 'current_overall_result', governed)
    all_periods = project(db)
    a1 = next(row for row in all_periods['students'] if row['student_id'] == scenario['students']['a1'].id)
    assert a1['programs'][0]['normalized_percent'] == 85
    assert calls and len(calls[0][0]) == 2

    calls.clear()
    selected = project(db, period_id=str(scenario['p1'].id))
    a1 = next(row for row in selected['students'] if row['student_id'] == scenario['students']['a1'].id)
    assert a1['programs'][0]['normalized_percent'] == 80
    assert calls == []


def test_one_student_row_holds_multiple_applicable_program_cells(db, scenario):
    scenario['program'].name = 'Primary Progress Program'
    db.flush()
    second, framework, _, _, _, config = _10_level_program(db)
    plan = create_plan(db, school_group_id=1, configuration_id=config.id)
    plan, period = add_period(
        db, school_group_id=1, plan_id=plan.id,
        expected_plan_revision=plan.revision, label='Semester A',
    )
    plan = activate_plan(db, school_group_id=1, plan_id=plan.id, expected_plan_revision=plan.revision)
    cycle = create_cycle(
        db, school_group_id=1, program_id=second.id, academic_year_id=100,
        framework_version_id=framework.id, title='Semester A Cycle',
        population_effective_at=datetime(2026, 9, 15),
    )
    db.flush()
    _link_and_open(db, plan=plan, period=period, cycle=cycle, close=False)
    db.commit()

    data = project(db)
    assert data['summary']['students']['value'] == 5
    assert data['summary']['expected']['value'] == 15
    assert len(data['students']) == 5
    assert all(len(row['programs']) == 2 for row in data['students'])
    filtered = project(db, program_id=str(second.id))
    assert filtered['summary']['expected']['value'] == 5
    assert all([cell['program_id'] for cell in row['programs']] == [str(second.id)] for row in filtered['students'])


def test_privacy_protects_aggregates_but_separate_identity_permission_controls_rows(db, scenario):
    protected = build_executive_overview(
        db, group_id=1, year_id=100, visible_branches=None, filters={},
        policy=DeterministicSuppressionTestPolicy(minimum_cohort=999),
        identity_allowed=False, can_configure=False,
    )
    assert protected['classification']['total']['value'] is None
    assert all(bucket['count'] is None and bucket['percentage'] is None for bucket in protected['classification']['buckets'])
    assert protected['summary']['expected']['value'] is None
    assert protected['students'] == [] and protected['student_rows_state'] == 'restricted'
    assert protected['can_configure'] is False


def test_learning_style_is_exactly_eight_categories_plus_unassigned(db, scenario):
    labels = [row['label'] for row in project(db)['learning_style']['levels']]
    assert labels == [
        'Visual', 'Auditory', 'Read/Write', 'Kinesthetic', 'Verbal',
        'Non-verbal', 'Quantitative', 'Spatial', 'Unassigned',
    ]


def test_branch_ceiling_and_tenant_scope(db, scenario):
    scoped = build_executive_overview(db, group_id=1, year_id=100, visible_branches=[10], filters={},
                                      policy=AllowAllTestPolicy(), identity_allowed=True)
    assert {row['id'] for row in scoped['filters']['branches']} == {'10'}
    assert {row['student_id'] for row in scoped['students']} == {
        scenario['students']['a1'].id, scenario['students']['a2'].id, scenario['students']['a3'].id,
    }
    empty_foreign_tenant = build_executive_overview(
        db, group_id=2, year_id=200, visible_branches=[20], filters={},
        policy=AllowAllTestPolicy(), identity_allowed=True,
    )
    assert empty_foreign_tenant['summary']['students']['value'] == 0
    assert empty_foreign_tenant['students'] == []
    with pytest.raises(DashboardError):
        build_executive_overview(
            db, group_id=2, year_id=100, visible_branches=[20], filters={},
            policy=AllowAllTestPolicy(), identity_allowed=True,
        )


def test_route_uses_repeatable_snapshot_dependency():
    route = next(route for route in results_router.routes if route.path.endswith('/executive-overview'))
    assert get_m10_organization_analytics_db in {dependency.call for dependency in route.dependant.dependencies}
