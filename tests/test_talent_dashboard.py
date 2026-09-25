"""Agent 3 aggregate privacy/authority adversarial regression."""
import pytest

from talent_analytics_privacy import AllowAllTestPolicy, DeterministicSuppressionTestPolicy
from talent_dashboard_service import build_dashboard, DashboardError
from talent_dashboard_service import result_summary, closed_distribution
from talent_learning_style_privacy import learning_style_projection
from talent_results_analytics_service import build_bucket_projection
from test_talent_classification import db, build_program, complete_with_level


def dashboard(db, **kwargs):
    return build_dashboard(db, group_id=1, year_id=100, visible_branches=None,
                           filters=kwargs.pop('filters', {}), policy=kwargs.pop('policy', AllowAllTestPolicy()),
                           learning_style_allowed=True, **kwargs)


def test_current_canonical_counts_and_style_filter(db):
    program, framework, cycle, member, competency, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, competency, levels[-1])
    data = dashboard(db, filters={'program_id': str(program.id), 'classification': 'Exceptional'})
    assert data['distinct_students']['value'] == 1
    assert data['classification']['total']['value'] == 1
    assert data['learning_style']['total_population'] == 1
    assert len(data['learning_style']['levels']) == 9


def test_suppressed_classification_has_no_secondary_aggregate_numbers(db):
    program, framework, cycle, member, competency, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, competency, levels[-1])
    data = dashboard(db, filters={'classification': 'Exceptional'}, policy=DeterministicSuppressionTestPolicy(minimum_cohort=3))
    assert data['learning_style']['state'] == 'restricted'
    assert data['learning_style']['total_population'] is None
    assert data['learning_style']['levels'] == []
    assert data['distinct_students']['value'] is None
    assert data['participations']['value'] is None


def test_no_classification_filter_keeps_learning_style_exception(db):
    build_program(db, level_count=5)
    data = dashboard(db, policy=DeterministicSuppressionTestPolicy(minimum_cohort=3))
    assert data['learning_style']['total_population'] == 1
    assert data['classification']['total']['value'] is None


def test_tenant_and_branch_ceiling(db):
    build_program(db, level_count=5)
    data = build_dashboard(db, group_id=1, year_id=100, visible_branches=[], filters={}, policy=AllowAllTestPolicy(), learning_style_allowed=True)
    assert data['distinct_students']['value'] == 0
    assert data['learning_style']['total_population'] == 0
    with pytest.raises(DashboardError):
        build_dashboard(db, group_id=999, year_id=100, visible_branches=None, filters={}, policy=AllowAllTestPolicy(), learning_style_allowed=True)


@pytest.mark.parametrize('projection', [None, {'state': 'restricted'}, {'state': 'visible', 'total': {'state': 'suppressed'}, 'buckets': []}])
def test_style_fail_closed_without_publishable_classification(projection):
    data = learning_style_projection([{'learning_style': 'Visual'}], classification='Exceptional', classification_projection=projection)
    assert data['state'] == 'restricted'
    assert data['levels'] == []
    assert data['total_population'] is None


def test_complementary_suppression_blocks_style_even_for_large_bucket():
    projection = build_bucket_projection(name='test', raw_counts={'Exceptional': 9, 'Advanced': 1}, policy=DeterministicSuppressionTestPolicy(minimum_cohort=3))
    data = learning_style_projection([{'learning_style': 'Visual'}] * 9, classification='Exceptional', classification_projection=projection)
    assert data['levels'] == []
    assert data['total_population'] is None


def test_protected_filtered_projection_also_blocks_style():
    base = build_bucket_projection(name='base', raw_counts={'Exceptional': 9}, policy=AllowAllTestPolicy())
    data = learning_style_projection([{'learning_style': 'Visual'}] * 9, classification='Exceptional',
        classification_projection=base, filtered_classification_projection={'state': 'restricted'})
    assert data['levels'] == [] and data['total_population'] is None


def test_rubric_is_program_bound_and_values_are_level_counts(db):
    program, framework, cycle, member, competency, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, competency, levels[-1])
    assert dashboard(db)['rubric']['state'] == 'select_program'
    data = dashboard(db, filters={'program_id': str(program.id), 'competency_id': str(competency.id), 'rubric_id': str(levels[0].rubric_id)})
    assert data['rubric']['distribution']['total']['value'] == 1
    assert data['rubric']['distribution']['buckets'][-1]['count'] == 1
    with pytest.raises(DashboardError):
        dashboard(db, filters={'program_id': str(program.id), 'competency_id': '999999'})


@pytest.mark.parametrize('filters', [{'compare_by': 'student'}, {'compare_ids': '1,1'}, {'compare_ids': '1,2,3,4,5,6,7'}, {'classification': 'Official Identification'}, {'program_id': '999999'}])
def test_invalid_or_foreign_filters_fail_closed(db, filters):
    build_program(db, level_count=5)
    with pytest.raises(DashboardError):
        dashboard(db, filters=filters)


def test_roster_keeps_authorized_individual_rows_while_style_aggregate_protected(monkeypatch):
    from test_talent_batch1_data_scope import World
    from routers import talent_assessment_cycles
    world = World(foreign_keys=True)
    try:
        policy = DeterministicSuppressionTestPolicy(minimum_cohort=999)
        monkeypatch.setattr(talent_assessment_cycles, 'resolve_privacy_policy_provider', lambda: policy)
        url = f'/api/talent/assessment-cycles/{world.cycle_b}/eligible-students'
        rows = world.get(url).json()
        assert rows['members']
        assert rows['insights']['learning_style']['total_population'] == rows['count']
        found = False
        for band in ('Exceptional', 'Advanced', 'Meets Expectations', 'Developing', 'Needs Improvement'):
            response = world.get(url + '?classification=' + band)
            assert response.status_code == 200
            data = response.json()
            assert data['filter_options'] == rows['filter_options']
            assert data['insights']['learning_style']['levels'] == []
            assert data['insights']['learning_style']['total_population'] is None
            assert data['insights']['classification']['total']['value'] is None
            if data['members']:
                found = True
                assert data['count'] == len(data['members'])
                assert all(row['student_id'] and 'learning_style' in row for row in data['members'])
        assert found, 'fixture must exercise an individually visible classified Student'
        world.as_admin(world.north)
        denied = world.get(url + f'?branch_id={world.south}')
        assert denied.status_code == 403
        scoped = world.get(url).json()
        assert all(row['branch_id'] == world.north for row in scoped['members'])
        empty_search = world.get(url + '?search=__not_a_student__').json()
        assert empty_search['members'] == []
        assert empty_search['filter_options'] == scoped['filter_options']
    finally:
        world.close()


def test_dashboard_route_hard_ceiling_and_no_identity_payload():
    from test_talent_batch1_data_scope import World
    world = World(foreign_keys=True)
    try:
        world.as_admin(world.north)
        url = f'/api/talent/results-analytics/academic-years/{world.year}/dashboard'
        response = world.get(url)
        assert response.status_code == 200, response.text
        data = response.json()
        assert {int(row['id']) for row in data['options']['branch']} == {world.north}
        assert 'student_id' not in response.text and 'first_name' not in response.text
        assert world.get(url + f'?branch_id={world.south}').status_code == 400
        assert world.get(url.replace(str(world.year), '999999')).status_code == 400
    finally:
        world.close()


def test_result_never_averages_different_programs_or_frameworks():
    rows = [{'program': '1', 'framework': 1, 'result': {'average': 2, 'scale_max': 5}},
            {'program': '2', 'framework': 2, 'result': {'average': 4, 'scale_max': 5}}]
    assert result_summary(rows, AllowAllTestPolicy(), 'test') == {'state': 'restricted', 'reason_code': 'incompatible_frameworks'}
    rows[1]['program'] = '1'
    assert result_summary(rows, AllowAllTestPolicy(), 'test')['state'] == 'restricted'
    rows[1]['framework'] = 1
    assert result_summary(rows, AllowAllTestPolicy(), 'test')['average'] == 3


def test_completion_uses_raw_counts_not_mean_of_branch_rates():
    # Unequal Branch populations: 1/2 and 9/90 -> 10/92, never 30%.
    data = closed_distribution({'Completed': 1 + 9, 'Not completed': 1 + 81}, AllowAllTestPolicy(), 'completion', 'P2')
    assert data['total']['value'] == 92
    assert data['buckets'][0]['percentage'] == 10.87


def test_absent_policy_protects_talent_but_not_unfiltered_style(db):
    build_program(db, level_count=5)
    data = dashboard(db, policy=None)
    assert data['classification']['state'] == 'restricted'
    assert data['completion']['state'] == 'restricted'
    assert data['learning_style']['total_population'] == 1
    filtered = dashboard(db, policy=None, filters={'classification': 'Exceptional'})
    assert filtered['learning_style']['state'] == 'restricted'
    assert filtered['learning_style']['levels'] == []


def test_current_reassessment_uses_original_evaluation_without_double_membership(db):
    from talent_assessment_cycle_service import create_cycle
    from talent_student_assessment_service import start_assessment, set_competency_result, complete_assessment
    from datetime import datetime
    program, framework, cycle, member, competency, levels, student = build_program(db, level_count=5)
    prior = complete_with_level(db, member, competency, levels[0])
    prior.is_current = False
    db.flush()
    physical = create_cycle(db, school_group_id=1, program_id=program.id, academic_year_id=100,
                            framework_version_id=framework.id, title='Private attempt', population_effective_at=datetime.utcnow())
    current = start_assessment(db, school_group_id=1, cycle_id=physical.id, student_id=student.id, evaluation_context_cycle_id=cycle.id)
    _, current = set_competency_result(db, school_group_id=1, assessment_id=current.id, framework_competency_id=competency.id,
                                       rubric_level_id=levels[-1].id, expected_revision=current.revision, evidence='Synthetic evidence')
    complete_assessment(db, school_group_id=1, assessment_id=current.id, expected_revision=current.revision)
    data = dashboard(db)
    assert data['participations']['value'] == 1
    assert data['classification']['total']['value'] == 1
    assert data['classification']['buckets'][-1]['count'] == 1
    assert data['classification']['buckets'][0]['count'] == 0


def test_protected_classification_does_not_change_selector_or_trend_metadata(db):
    program, framework, cycle, member, competency, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, competency, levels[-1])
    policy = DeterministicSuppressionTestPolicy(minimum_cohort=3)
    present = dashboard(db, policy=policy, filters={'program_id': str(program.id), 'classification': 'Exceptional'})
    absent = dashboard(db, policy=policy, filters={'program_id': str(program.id), 'classification': 'Developing'})
    assert present['options'] == absent['options']
    assert present['rubric']['competencies'] == absent['rubric']['competencies']
    assert present['rubric']['indicators'] == absent['rubric']['indicators']
    assert present['trend'] == absent['trend']


def test_dashboard_uses_repeatable_snapshot_dependency():
    from routers.talent_results_analytics import router
    from dependencies import get_m10_organization_analytics_db
    route = next(route for route in router.routes if route.path.endswith('/dashboard'))
    assert get_m10_organization_analytics_db in {d.call for d in route.dependant.dependencies}


def test_classification_subcohorts_cannot_leak_through_completion_or_rubric(db):
    import models
    from talent_analytics_privacy import PrivacyDecision
    from student_academic_service import create_student, create_placement
    from talent_student_assessment_service import start_assessment
    from datetime import datetime

    class ClassificationOnlyMinimum(AllowAllTestPolicy):
        def evaluate_cell(self, *, privacy_class, raw_value, denominator=None, context=None):
            if privacy_class == 'P4' and raw_value is not None and raw_value < 2:
                return PrivacyDecision('suppressed')
            return super().evaluate_cell(privacy_class=privacy_class, raw_value=raw_value, denominator=denominator, context=context)

    program, framework, cycle, member, competency, levels, student = build_program(db, level_count=5)
    complete_with_level(db, member, competency, levels[-1])
    db.add(models.PlanningSection(id=1001, branch_id=10, academic_year_id=100, grade_level='1', section_name='B', class_status='Current'))
    db.flush()
    second = create_student(db, school_group_id=1, first_name='Synthetic', last_name='Second')
    create_placement(db, school_group_id=1, student_id=second.id, academic_year_id=100, branch_id=10,
                     planning_section_id=1001, effective_from=datetime(2026, 1, 1))
    attempt = start_assessment(db, school_group_id=1, cycle_id=cycle.id, student_id=second.id)
    from talent_student_assessment_service import set_competency_result, complete_assessment
    _, attempt = set_competency_result(db, school_group_id=1, assessment_id=attempt.id, framework_competency_id=competency.id,
                                       rubric_level_id=levels[-1].id, expected_revision=attempt.revision, evidence='Synthetic evidence')
    complete_assessment(db, school_group_id=1, assessment_id=attempt.id, expected_revision=attempt.revision)
    data = dashboard(db, policy=ClassificationOnlyMinimum(), filters={'program_id': str(program.id), 'classification': 'Exceptional',
                     'compare_by': 'section', 'competency_id': str(competency.id), 'rubric_id': str(levels[0].rubric_id)})
    assert data['learning_style']['total_population'] == 2  # overall cell is publishable
    assert all(group['completion']['state'] == 'restricted' for group in data['comparison']['groups'])
    assert all(group['classification']['state'] == 'restricted' for group in data['comparison']['groups'])
    assert data['rubric']['state'] == 'restricted'
    assert all(group['distribution']['buckets'] == [] for group in data['rubric']['comparison'])


def test_dashboard_distinct_students_agrees_with_overview_authority_and_branch_scope():
    """The dashboard reuses the Batch 1 distinct-current-Student grain: it never disagrees with Overview."""
    from test_talent_batch1_data_scope import World, metrics
    world = World(foreign_keys=True)
    try:
        url = f'/api/talent/results-analytics/academic-years/{world.year}/dashboard'
        overview = metrics(world)
        dash = world.get(url).json()
        assert dash['distinct_students']['value'] == overview['distinct_students']['value']
        assert dash['participations']['value'] >= dash['distinct_students']['value']
        north = world.get(url + f'?branch_id={world.north}').json()
        assert north['distinct_students']['value'] == metrics(world, f'&branch_id={world.north}')['distinct_students']['value']
    finally:
        world.close()


def test_dashboard_statement_count_is_bounded_not_row_proportional():
    from test_talent_batch1_data_scope import World
    world = World(foreign_keys=True)
    try:
        url = f'/api/talent/results-analytics/academic-years/{world.year}/dashboard'
        statements, _ = world.count_statements(url)
        with_filters, _ = world.count_statements(url + f'?branch_id={world.north}&compare_by=grade')
        assert statements < 60, statements
        assert with_filters < 60, with_filters
    finally:
        world.close()


def test_dashboard_route_protects_classification_filtered_style_without_any_number(monkeypatch):
    """Route-level proof: a protected Classification cohort serializes no Learning Style number at all."""
    from test_talent_batch1_data_scope import World
    from talent_analytics_privacy import resolve_privacy_policy_provider
    world = World(foreign_keys=True)
    try:
        world.client.app.dependency_overrides[resolve_privacy_policy_provider] = lambda: DeterministicSuppressionTestPolicy(minimum_cohort=999)
        url = f'/api/talent/results-analytics/academic-years/{world.year}/dashboard'
        for band in ('Exceptional', 'Advanced', 'Meets Expectations', 'Developing', 'Needs Improvement'):
            data = world.get(url + '?classification=' + band).json()
            assert data['learning_style'] == {
                'state': 'restricted', 'reason_code': 'classification_cohort_protected',
                'total': {'state': 'restricted', 'value': None}, 'total_population': None, 'levels': [],
            }, band
        # The unfiltered Learning Style keeps the owner-approved Acceptance C exception.
        assert world.get(url).json()['learning_style']['total_population'] == 10
    finally:
        world.close()


def test_dashboard_without_students_view_returns_permission_state_not_a_number(db):
    build_program(db, level_count=5)
    data = build_dashboard(db, group_id=1, year_id=100, visible_branches=None, filters={}, policy=AllowAllTestPolicy(),
                           learning_style_allowed=False)
    assert data['learning_style'] == {'state': 'restricted', 'reason_code': 'permission_required', 'levels': []}


def test_roster_small_cohort_rows_are_exact_while_aggregate_classification_stays_suppressed(monkeypatch):
    """Owner decision 1/2: individually authorized rows are exact; the aggregate keeps primary suppression."""
    from test_talent_batch1_data_scope import World
    from routers import talent_assessment_cycles
    world = World(foreign_keys=True)
    try:
        monkeypatch.setattr(talent_assessment_cycles, 'resolve_privacy_policy_provider',
                            lambda: DeterministicSuppressionTestPolicy(minimum_cohort=999))
        data = world.get(f'/api/talent/assessment-cycles/{world.cycle_b}/eligible-students').json()
        assert data['count'] == len(data['members']) > 0
        assert all(row['student_id'] for row in data['members'])
        assert data['insights']['classification']['total']['value'] is None
        assert all(bucket.get('count') is None for bucket in data['insights']['classification']['buckets'])
    finally:
        world.close()
