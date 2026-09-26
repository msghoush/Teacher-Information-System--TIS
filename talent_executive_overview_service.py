"""Executive Overview projection with one canonical expected-assessment grain.

Expected = current authorized Academic-Year placement x enabled grade-applicable
Program x linked planned Period whose Cycle is open/closed. Draft/unopened and
cancelled Periods never enter the denominator. Missing results are remaining,
never zero-valued results. All aggregate values are privacy-provider projections;
individual rows are returned only under the separate Student-drill permission.
"""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func

import models
from talent_analytics_privacy import resolve_privacy_policy_provider
from talent_classification_service import CLASSIFICATION_LABELS, assessment_classification
from talent_dashboard_service import DashboardError, closed_distribution, safe_count, wholly_visible
from talent_evaluation_progress_service import current_overall_result
from talent_learning_style_privacy import learning_style_projection
from talent_read_batch import read_batch
from talent_student_assessment_service import overall_program_result, prime_assessment_batch

MAX_EXPECTED = 10000


def _percent(n, d):
    return float((Decimal(n) * 100 / Decimal(d)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if d else None


def build_executive_overview(db, *, group_id, year_id, visible_branches, filters,
                             policy=None, identity_allowed=False, can_configure=False):
    if db.query(models.AcademicYear.id).filter_by(id=year_id, school_group_id=group_id).first() is None:
        raise DashboardError('Academic Year is outside your authorized scope.')
    policy = policy or resolve_privacy_policy_provider()
    branch_rows = db.query(models.Branch).filter_by(school_group_id=group_id).all()
    allowed = {b.id for b in branch_rows}
    if visible_branches is not None:
        allowed &= set(visible_branches)
    branch_id = int(filters['branch_id']) if filters.get('branch_id') else None
    if branch_id is not None and branch_id not in allowed:
        raise DashboardError('Branch is outside your authorized scope.')

    P, S = models.StudentAcademicPlacement, models.Student
    latest = db.query(P.student_id.label('student_id'), func.max(P.effective_from).label('effective_from')).filter(
        P.school_group_id == group_id, P.academic_year_id == year_id, P.status == 'active',
        P.branch_id.in_(allowed or {-1}),
    ).group_by(P.student_id).subquery()
    placement_q = db.query(P, S).join(latest, and_(latest.c.student_id == P.student_id,
                                                   latest.c.effective_from == P.effective_from)).join(
        S, and_(S.id == P.student_id, S.school_group_id == group_id, S.status == 'active'),
    ).filter(P.school_group_id == group_id, P.academic_year_id == year_id, P.status == 'active')
    if branch_id is not None:
        placement_q = placement_q.filter(P.branch_id == branch_id)
    placement_scope = placement_q.order_by(S.last_name, S.first_name, S.id).all()
    grade_options = sorted({placement.grade_level for placement, _ in placement_scope})
    if filters.get('grade_level') and str(filters['grade_level']) not in grade_options:
        raise DashboardError('Grade is outside the selected Branch context.')
    placements = [(placement, student) for placement, student in placement_scope
                  if not filters.get('grade_level') or placement.grade_level == str(filters['grade_level'])]

    Cfg, Program, Period, Cycle = (models.TalentProgramAcademicYearConfiguration, models.TalentProgram,
                                    models.TalentPlannedEvaluationPeriod, models.TalentAssessmentCycle)
    context_scope = db.query(Cfg, Program, Period, Cycle).join(
        Program, and_(Program.id == Cfg.program_id, Program.school_group_id == group_id),
    ).join(Period, and_(Period.program_id == Cfg.program_id, Period.academic_year_id == year_id,
                       Period.school_group_id == group_id, Period.status == 'planned')).join(
        Cycle, and_(Cycle.planned_evaluation_period_id == Period.id, Cycle.program_id == Cfg.program_id,
                    Cycle.academic_year_id == year_id, Cycle.school_group_id == group_id,
                    Cycle.status.in_(('open', 'closed'))),
    ).filter(Cfg.school_group_id == group_id, Cfg.academic_year_id == year_id,
             Cfg.is_enabled.is_(True), Program.status != 'retired').all()
    program_options = {str(program.id): program.name for _, program, _, _ in context_scope}
    if filters.get('program_id') and str(filters['program_id']) not in program_options:
        raise DashboardError('Program has no applicable opened Evaluation Period in this context.')
    period_scope = [row for row in context_scope
                    if not filters.get('program_id') or str(row[1].id) == str(filters['program_id'])]
    period_options = {str(period.id): (period.label, period.sequence) for _, _, period, _ in period_scope}
    if filters.get('period_id') and str(filters['period_id']) not in period_options:
        raise DashboardError('Evaluation Period is not opened in this context.')
    contexts = context_scope
    if filters.get('program_id'):
        contexts = [row for row in contexts if str(row[1].id) == str(filters['program_id'])]
    if filters.get('period_id'):
        contexts = [row for row in contexts if str(row[2].id) == str(filters['period_id'])]

    selected_programs = {str(program.id): program.name for _, program, _, _ in contexts}

    expected = []
    for placement, student in placements:
        for config, program, period, cycle in contexts:
            grades = {value for value in (config.eligible_grade_levels_csv or '').split(',') if value}
            if placement.grade_level not in grades:
                continue
            expected.append({'placement': placement, 'student': student, 'program': program,
                             'period': period, 'cycle': cycle})
    if len(expected) > MAX_EXPECTED:
        raise DashboardError('This selection is too broad. Narrow the Branch, Grade, Program, or Evaluation Period.')

    student_ids = {e['student'].id for e in expected}
    cycle_ids = {e['cycle'].id for e in expected}
    A = models.TalentStudentAssessment
    assessments = db.query(A).filter(
        A.school_group_id == group_id, A.student_id.in_(student_ids or {-1}), A.is_current.is_(True),
        func.coalesce(A.evaluation_context_cycle_id, A.cycle_id).in_(cycle_ids or {-1}),
    ).order_by(A.id).all()
    by_key = {(a.student_id, a.evaluation_context_cycle_id or a.cycle_id): a for a in assessments}
    completed, classifications, result_by_key = 0, Counter(), {}
    with read_batch(db):
        prime_assessment_batch(db, assessments)
        for item in expected:
            key = (item['student'].id, item['cycle'].id)
            assessment = by_key.get(key)
            if assessment is None or assessment.status != 'completed':
                continue
            completed += 1
            overall = overall_program_result(db, assessment)
            classified = assessment_classification(db, assessment, overall=overall)
            result_by_key[key] = {'overall': overall, 'classification': classified}
            if classified and classified.get('available'):
                classifications[classified['classification']] += 1

    expected_count, remaining = len(expected), len(expected) - completed
    completion = closed_distribution({'Completed': completed, 'Remaining': remaining}, policy,
                                     'executive_completion', 'P2')
    classification = closed_distribution({label: classifications[label] for label in CLASSIFICATION_LABELS},
                                         policy, 'executive_classification', 'P4')
    scoped_students = {e['student'].id: e['student'] for e in expected}
    styles = learning_style_projection(list(scoped_students.values()))

    branch_breakdown = []
    for bid in sorted({e['placement'].branch_id for e in expected}):
        subset = [e for e in expected if e['placement'].branch_id == bid]
        done = sum((e['student'].id, e['cycle'].id) in result_by_key for e in subset)
        projection = closed_distribution({'Completed': done, 'Remaining': len(subset)-done}, policy,
                                         f'executive_completion_branch:{bid}', 'P2')
        branch_breakdown.append({'id': str(bid), 'label': next((b.name for b in branch_rows if b.id == bid), 'Branch'),
                                 'completion': projection})
    # Comparisons close as a family; no hidden Branch can be reconstructed from
    # the organization total and its visible siblings.
    if not all(wholly_visible(row['completion']) for row in branch_breakdown):
        branch_breakdown = [{'id': row['id'], 'label': row['label'],
                             'completion': {'state': 'restricted', 'buckets': [],
                                            'total': {'state': 'restricted', 'value': None}}}
                            for row in branch_breakdown]

    students = []
    if identity_allowed:
        per_student = defaultdict(list)
        for item in expected:
            per_student[item['student'].id].append(item)
        for sid, items in per_student.items():
            student, placement = items[0]['student'], items[0]['placement']
            program_cells = []
            for program_id in sorted({e['program'].id for e in items}):
                program_items = sorted([e for e in items if e['program'].id == program_id], key=lambda e: e['period'].sequence)
                normalized_by_cycle, latest_classification = {}, None
                done = 0
                for e in program_items:
                    result = result_by_key.get((sid, e['cycle'].id))
                    if not result:
                        continue
                    done += 1
                    overall = result['overall']
                    if overall and overall.get('available') is not False:
                        normalized_by_cycle[e['cycle'].id] = overall['normalized_percent']
                    if result['classification'] and result['classification'].get('available'):
                        latest_classification = result['classification']['classification']
                if filters.get('period_id'):
                    selected_result = normalized_by_cycle.get(program_items[0]['cycle'].id)
                    result_state = 'visible' if selected_result is not None else 'no_result'
                    normalized_percent = selected_result
                else:
                    governed = current_overall_result(
                        [(e['period'], e['cycle']) for e in program_items], normalized_by_cycle,
                    )
                    normalized_percent = governed['current_overall_result']
                    result_state = (
                        'not_comparable' if governed['comparability_state'] == 'not_comparable'
                        else 'visible' if normalized_percent is not None else 'no_result'
                    )
                program_cells.append({
                    'program_id': str(program_id), 'program_name': program_items[0]['program'].name,
                    'expected': len(program_items), 'completed': done,
                    'result_state': result_state,
                    'normalized_percent': normalized_percent,
                    'classification': latest_classification,
                    'is_talented': latest_classification == 'Exceptional',
                })
            students.append({
                'student_id': sid,
                'display_name': ' '.join(v for v in (student.first_name, student.father_name, student.last_name) if v),
                'grade_level': placement.grade_level, 'section_name': placement.section_name,
                'learning_style': student.learning_style, 'programs': program_cells,
                'talented_program_count': sum(cell['is_talented'] for cell in program_cells),
            })

    visible_completion = wholly_visible(completion)
    return {
        'filters': {
            'branches': [{'id': str(b.id), 'label': b.name} for b in branch_rows if b.id in allowed],
            'grades': grade_options,
            'programs': [{'id': key, 'label': value} for key, value in sorted(program_options.items())],
            'periods': [{'id': key, 'label': value[0], 'sequence': value[1]} for key, value in sorted(period_options.items(), key=lambda pair: pair[1][1])],
        },
        'summary': {
            'students': safe_count(len(scoped_students), policy),
            'expected': completion.get('total'),
            'completed': {'state': 'visible', 'value': completed, 'percentage': _percent(completed, expected_count)} if visible_completion else {'state': 'restricted', 'value': None, 'percentage': None},
            'remaining': {'state': 'visible', 'value': remaining, 'percentage': _percent(remaining, expected_count)} if visible_completion else {'state': 'restricted', 'value': None, 'percentage': None},
        },
        'completion': completion, 'classification': classification, 'learning_style': styles,
        'branch_breakdown': branch_breakdown, 'programs': [{'id': key, 'label': value} for key, value in sorted(selected_programs.items())],
        'students': students, 'student_rows_state': 'visible' if identity_allowed else 'restricted',
        'can_configure': bool(can_configure),
        'semantics': {'expected_grain': 'eligible_student_x_applicable_program_x_opened_period',
                      'active_period_rule': 'planned_period_with_open_or_closed_cycle',
                      'completion_formula': 'completed_expected_assessments / expected_assessments'},
    }
