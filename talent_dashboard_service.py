"""Bounded, identity-free executive/organization analytics projection.

The population is current Students' historical open/closed Evaluation memberships
with current attempts resolved through evaluation_context_cycle_id (ADR 0036).
Counts retain their grain; results never pool different Program/framework scales.
No Student identity or raw row is returned. Comparison requests choose one axis,
at most six coordinates. Privacy is conservative: a comparison/result family is
published only when every contributing distribution in that family is visible.
This prevents selected-subset totals and cross-chart sums bypassing suppression.
"""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, or_, exists, func

import models
from talent_current_students import current_student_exists
from talent_classification_service import CLASSIFICATION_LABELS, assessment_classification
from talent_student_assessment_service import prime_assessment_batch, overall_program_result
from talent_read_batch import read_batch
from talent_analytics_privacy import Cell, apply_primary_privacy, run_complementary_suppression
from talent_analytics_service import build_breakdown_group
from talent_results_analytics_service import build_bucket_projection
from talent_learning_style_privacy import learning_style_projection, classification_cohort_publishable

MAX_POPULATION = 5000
AXES = ("branch", "grade", "section", "program", "period")


class DashboardError(ValueError):
    pass


def pct(n, d):
    return float((Decimal(n) * 100 / Decimal(d)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if d else None


def closed_distribution(counts, policy, name, privacy_class='P4'):
    if policy is None:
        return {"state": "restricted", "total": {"state": "restricted", "value": None}, "buckets": []}
    if privacy_class == 'P4':
        return build_bucket_projection(name=name, raw_counts=counts, policy=policy)
    total = sum(counts.values())
    group = build_breakdown_group(name=name, privacy_class=privacy_class, total_raw=total, children_raw=counts)
    apply_primary_privacy(group.all_cells(), policy)
    if not run_complementary_suppression([group], policy):
        return {'state': 'restricted', 'total': {'state': 'restricted', 'value': None}, 'buckets': []}
    cells = {c.key[2]: c for c in group.children}
    return {'state': group.total.state, 'total': {'state': group.total.state, 'value': group.total.value},
            'buckets': [{'label': label, 'state': cells[label].state,
                         'count': cells[label].value if cells[label].state == 'visible' else None,
                         'percentage': pct(cells[label].value, total) if cells[label].state == 'visible' and group.total.state == 'visible' else None}
                        for label in counts]}


def wholly_visible(distribution):
    return distribution.get('state') == 'visible' and all(b['state'] == 'visible' for b in distribution.get('buckets', []))


def safe_count(n, policy, privacy_class='P2'):
    if policy is None:
        return {"state": "restricted", "value": None}
    cell = Cell(key=('dashboard', 'distinct_students'), privacy_class=privacy_class, raw_value=n)
    apply_primary_privacy([cell], policy)
    return {"state": cell.state, "value": cell.value if cell.state == 'visible' else None}


def distribution(records, family, policy, name):
    if family == 'classification':
        counts = dict.fromkeys(CLASSIFICATION_LABELS, 0)
        for r in records:
            if r['classification'] in counts:
                counts[r['classification']] += 1
    else:
        # Binary completion partition has an explicit participation denominator.
        counts = {'Completed': sum(r['status'] == 'completed' for r in records)}
        counts['Not completed'] = len(records) - counts['Completed']
    return closed_distribution(counts, policy, name, 'P4' if family == 'classification' else 'P2')


def result_summary(records, policy, name):
    usable = [r for r in records if r.get('result') and r['result'].get('available') is not False]
    if not usable:
        return {'state': 'no_data'}
    identities = {(r['program'], r['framework'], r['result'].get('scale_max')) for r in usable}
    if len(identities) != 1:
        return {'state': 'restricted', 'reason_code': 'incompatible_frameworks'}
    count = safe_count(len(usable), policy, 'P3')
    if count['state'] != 'visible':
        return {'state': count['state']}
    average = (sum(Decimal(str(r['result']['average'])) for r in usable) / len(usable)).quantize(Decimal('.1'), rounding=ROUND_HALF_UP)
    scale = usable[0]['result']['scale_max']
    return {'state': 'visible', 'average': float(average), 'scale_max': scale,
            'normalized_percent': pct(average, scale), 'count': count['value']}


def build_dashboard(db, *, group_id, year_id, visible_branches, filters, policy, learning_style_allowed):
    year = db.query(models.AcademicYear.id).filter_by(id=year_id, school_group_id=group_id).first()
    if year is None:
        raise DashboardError('Academic Year is outside your authorized scope.')
    axis = filters.get('compare_by') or 'branch'
    if axis not in AXES:
        raise DashboardError('Choose a recognized comparison dimension.')
    classification = filters.get('classification') or None
    if classification and classification not in CLASSIFICATION_LABELS:
        raise DashboardError('Choose a recognized Classification.')
    branch_rows = db.query(models.Branch).filter_by(school_group_id=group_id).all()
    allowed = {b.id for b in branch_rows}
    if visible_branches is not None:
        allowed &= set(visible_branches)
    branch_labels = {str(b.id): b.name for b in branch_rows if b.id in allowed}
    if filters.get('branch_id') and int(filters['branch_id']) not in allowed:
        raise DashboardError('Branch is outside your authorized scope.')
    M, C, A, S = models.TalentAssessmentCyclePopulationMember, models.TalentAssessmentCycle, models.TalentStudentAssessment, models.Student
    query = db.query(M, C, A, S.learning_style).join(C, and_(C.id == M.cycle_id, C.school_group_id == group_id)).join(
        S, and_(S.id == M.student_id, S.school_group_id == group_id)
    ).outerjoin(A, and_(A.school_group_id == group_id, A.student_id == M.student_id,
                       func.coalesce(A.evaluation_context_cycle_id, A.cycle_id) == M.cycle_id, A.is_current.is_(True))).filter(
        M.school_group_id == group_id, M.academic_year_id == year_id,
        M.branch_id.in_(allowed or {-1}), C.status.in_(('open', 'closed')), current_student_exists().correlate(M),
        ~exists().where(and_(models.TalentStudentAssessment.cycle_population_member_id == M.id,
                            models.TalentStudentAssessment.evaluation_context_cycle_id.isnot(None),
                            models.TalentStudentAssessment.evaluation_context_cycle_id != models.TalentStudentAssessment.cycle_id)).correlate(M),
    )
    # SQL ceiling applied before materialization; a broad request fails explicitly.
    if filters.get('branch_id'):
        query = query.filter(M.branch_id == int(filters['branch_id']))
    rows = query.order_by(M.id, A.id.desc()).limit(MAX_POPULATION + 1).all()
    if len(rows) > MAX_POPULATION:
        raise DashboardError('This selection is too broad. Choose a Branch to narrow the analysis.')
    program_ids = {m.program_id for m, _, _, _ in rows}
    period_ids = {c.planned_evaluation_period_id for _, c, _, _ in rows if c.planned_evaluation_period_id}
    programs = {str(p.id): p.name for p in db.query(models.TalentProgram).filter(models.TalentProgram.school_group_id == group_id, models.TalentProgram.id.in_(program_ids or {-1})).all()}
    periods = {str(p.id): (p.label, p.sequence) for p in db.query(models.TalentPlannedEvaluationPeriod).filter(models.TalentPlannedEvaluationPeriod.school_group_id == group_id, models.TalentPlannedEvaluationPeriod.id.in_(period_ids or {-1})).all()}
    records, seen = [], set()
    with read_batch(db):
        prime_assessment_batch(db, [a for _, _, a, _ in rows if a is not None])
        for m, cycle, a, style in rows:
            if m.id in seen:
                continue
            seen.add(m.id)
            overall = overall_program_result(db, a) if a and a.status == 'completed' else None
            band = assessment_classification(db, a, overall=overall) if overall is not None else None
            records.append({'student': m.student_id, 'assessment': a.id if a else None,
                            'branch': str(m.branch_id), 'grade': m.grade_level,
                            'section': str(m.planning_section_id or f'{m.branch_id}:{m.grade_level}:{m.section_name}'),
                            'section_label': f'{m.grade_level} · {m.section_name}',
                            'program': str(m.program_id), 'period': str(cycle.planned_evaluation_period_id or f'cycle:{cycle.id}'),
                            'period_label': periods.get(str(cycle.planned_evaluation_period_id), (cycle.title, 0))[0],
                            'sequence': periods.get(str(cycle.planned_evaluation_period_id), ('', 0))[1],
                            'framework': a.framework_version_id if a else cycle.framework_version_id,
                            'status': a.status if a else 'not_started', 'learning_style': style,
                            'classification': band.get('classification') if band and band.get('available') else None,
                            'result': overall})
    options = {'branch': [{'id': k, 'label': v} for k, v in branch_labels.items()]}
    for dim, key in [('grade', 'grade_level'), ('section', 'section_id'), ('program', 'program_id'), ('period', 'period_id')]:
        source = records
        if dim == 'section' and filters.get('grade_level'):
            source = [r for r in source if r['grade'] == str(filters['grade_level'])]
        if dim == 'period' and filters.get('program_id'):
            source = [r for r in source if r['program'] == str(filters['program_id'])]
        labels = {r[dim]: programs.get(r['program'], 'Program') if dim == 'program' else
                  r['section_label'] if dim == 'section' else r['period_label'] if dim == 'period' else r['grade'] for r in source}
        options[dim] = [{'id': k, 'label': v} for k, v in sorted(labels.items())]
        if filters.get(key) and str(filters[key]) not in labels:
            raise DashboardError(f'{dim.title()} is outside the selected context. Clear dependent filters.')
    selected = records
    for dim, key in [('branch','branch_id'),('grade','grade_level'),('section','section_id'),('program','program_id'),('period','period_id')]:
        if filters.get(key):
            selected = [r for r in selected if r[dim] == str(filters[key])]
    base_classification = distribution(selected, 'classification', policy, 'dashboard_classification_scope')
    cohort_safe = classification_cohort_publishable(base_classification, classification)
    metadata_records = selected
    if classification:
        selected = [r for r in selected if r['classification'] == classification]
    completion = distribution(selected, 'completion', policy, 'dashboard_completion')
    classified = distribution(selected, 'classification', policy, 'dashboard_classification')
    cohort_safe = cohort_safe and classification_cohort_publishable(classified, classification)
    styles = learning_style_projection(
        list({r['student']: r for r in selected}.values()), classification=classification,
        classification_projection=base_classification,
        filtered_classification_projection=classified,
    ) if learning_style_allowed else {'state': 'restricted', 'reason_code': 'permission_required', 'levels': []}
    chosen = [s for s in (filters.get('compare_ids') or '').split(',') if s]
    if len(chosen) > 6 or len(set(chosen)) != len(chosen):
        raise DashboardError('Choose up to six distinct comparison groups.')
    axis_labels = {o['id']: o['label'] for o in options[axis]}
    if any(k not in axis_labels for k in chosen):
        raise DashboardError('A comparison group is outside your authorized context.')
    # A publishable overall Classification does not imply publishable Branch,
    # Grade or other sub-cohorts. Close EVERY companion comparison family on
    # the same P4 decisions, even if its own P2/P3 provider would allow a count.
    comparison_cohort_safe = cohort_safe and (not classification or all(
        classification_cohort_publishable(
            distribution([r for r in metadata_records if r[axis] == key], 'classification', policy, f'comparison_scope:{key}'),
            classification,
        ) and classification_cohort_publishable(
            distribution([r for r in selected if r[axis] == key], 'classification', policy, f'comparison_filtered:{key}'), classification,
        ) for key in axis_labels
    ))
    groups = []
    for key in (chosen or list(axis_labels)[:6]):
        subset = [r for r in selected if r[axis] == key]
        groups.append({'id': key, 'label': axis_labels[key],
                       'completion': distribution(subset, 'completion', policy, f'completion:{axis}:{key}'),
                       'classification': distribution(subset, 'classification', policy, f'classification:{axis}:{key}'),
                       'result': result_summary(subset, policy, f'result:{axis}:{key}')})
    # Entire result-set family closes together, including groups not selected for
    # display. Selecting A/C must not undo suppression established over A/B/C.
    for family in ('completion', 'classification'):
        full = [distribution([r for r in selected if r[axis] == key], family, policy, f'closure:{family}:{key}') for key in axis_labels]
        if not comparison_cohort_safe or not all(wholly_visible(d) for d in full):
            for g in groups:
                g[family] = {'state': 'restricted', 'buckets': [], 'total': {'state': 'restricted', 'value': None}}
                g['result'] = {'state': 'restricted'}
    if len({(r['program'], r['framework']) for r in selected if r.get('result')}) > 1:
        for g in groups:
            g['result'] = {'state': 'restricted', 'reason_code': 'incompatible_frameworks'}
    trend = []
    if filters.get('program_id') and all(r['sequence'] > 0 for r in metadata_records):
        keys = sorted({r['period'] for r in metadata_records}, key=lambda k: min(r['sequence'] for r in metadata_records if r['period'] == k))
        for key in keys:
            subset = [r for r in selected if r['period'] == key]
            label = next(r['period_label'] for r in metadata_records if r['period'] == key)
            trend.append({'label': label, 'completion': distribution(subset, 'completion', policy, f'trend:{key}'),
                          'result': result_summary(subset, policy, f'trend_result:{key}'), 'frameworks': {r['framework'] for r in subset}})
        comparable = len({f for t in trend for f in t.pop('frameworks')}) <= 1
        trend_cohort_safe = cohort_safe and (not classification or all(
            classification_cohort_publishable(
                distribution([r for r in metadata_records if r['period'] == key], 'classification', policy, f'trend_scope:{key}'), classification,
            ) and classification_cohort_publishable(
                distribution([r for r in selected if r['period'] == key], 'classification', policy, f'trend_filtered:{key}'), classification,
            ) for key in keys
        ))
        if not trend_cohort_safe or not all(wholly_visible(t['completion']) for t in trend):
            for t in trend:
                t['result'] = {'state': 'restricted', 'reason_code': 'incompatible_or_protected'}
                t['completion'] = {'state': 'restricted', 'buckets': []}
        elif not comparable:
            for t in trend:
                t['result'] = {'state': 'restricted', 'reason_code': 'incompatible_frameworks'}
    rubric = rubric_projection(db, group_id, selected, filters, groups, axis, policy, comparison_cohort_safe, metadata_records)
    if not cohort_safe:
        completion = classified = {'state': 'restricted', 'buckets': [], 'total': {'state': 'restricted', 'value': None}}
    return {'grain': 'Evaluation participations; Students are distinct current identities', 'options': options,
            'distinct_students': safe_count(len({r['student'] for r in selected}), policy) if cohort_safe else {'state': 'restricted', 'value': None},
            'participations': completion.get('total'), 'completion': completion, 'classification': classified,
            'learning_style': styles, 'result': result_summary(selected, policy, 'overall') if cohort_safe and wholly_visible(classified) else {'state': 'restricted'},
            'comparison': {'dimension': axis, 'groups': groups, 'limit': 6}, 'trend': trend, 'rubric': rubric,
            'privacy_policy_version': getattr(policy, 'privacy_policy_version', None)}


def rubric_projection(db, group_id, records, filters, groups, axis, policy, cohort_safe, metadata_records=None):
    if not filters.get('program_id'):
        return {'state': 'select_program', 'competencies': [], 'indicators': []}
    # Selector metadata cannot reveal whether a protected Classification has
    # members: derive it before applying the sensitive Classification filter.
    frameworks = {r['framework'] for r in (metadata_records if metadata_records is not None else records)}
    rubrics = db.query(models.TalentRubric, models.FrameworkCompetency).join(
        models.FrameworkCompetency, and_(
            models.FrameworkCompetency.school_group_id == group_id,
            models.FrameworkCompetency.framework_version_id == models.TalentRubric.framework_version_id,
            or_(models.FrameworkCompetency.id == models.TalentRubric.framework_competency_id,
                models.TalentRubric.framework_competency_id.is_(None))),
    ).filter(models.TalentRubric.school_group_id == group_id,
             models.TalentRubric.framework_version_id.in_(frameworks or {-1})).all()
    competencies = {str(c.id): {'id': str(c.id), 'label': c.label, 'framework_id': c.framework_version_id} for _, c in rubrics}
    cid = str(filters.get('competency_id') or '')
    if cid and cid not in competencies:
        raise DashboardError('Competency is outside this Program and selected result context.')
    indicators = [{'id': str(r.id), 'label': r.name, 'competency_id': str(c.id)} for r, c in rubrics if str(c.id) == cid]
    rid = str(filters.get('rubric_id') or '')
    if rid and rid not in {r['id'] for r in indicators}:
        raise DashboardError('Rubric Indicator is outside the selected Competency.')
    output = {'state': 'select_indicator', 'competencies': list(competencies.values()), 'indicators': indicators}
    if not rid:
        return output
    levels = db.query(models.TalentRubricLevel).filter_by(rubric_id=int(rid), school_group_id=group_id).order_by(models.TalentRubricLevel.display_order, models.TalentRubricLevel.id).all()
    ids = {r['assessment'] for r in records if r['status'] == 'completed' and r['assessment']}
    evidence = db.query(models.TalentStudentCompetencyResult.assessment_id, models.TalentStudentCompetencyResult.rubric_level_id).filter(
        models.TalentStudentCompetencyResult.school_group_id == group_id,
        models.TalentStudentCompetencyResult.assessment_id.in_(ids or {-1}),
        models.TalentStudentCompetencyResult.rubric_id == int(rid),
        models.TalentStudentCompetencyResult.framework_competency_id == int(cid),
    ).all()
    def project(assessment_ids, name):
        counts = Counter(level_id for aid, level_id in evidence if aid in assessment_ids)
        return closed_distribution({f'{i+1}. {l.label}': counts[l.id] for i, l in enumerate(levels)}, policy, name, 'P3')
    aggregate = project(ids, 'rubric_indicator')
    comparisons = [{'label': g['label'], 'distribution': project({r['assessment'] for r in records if r[axis] == g['id']}, f'rubric:{g["id"]}')} for g in groups]
    # No selection-induced disclosure: all coordinates participate in closure.
    safe = cohort_safe and wholly_visible(aggregate) and all(wholly_visible(project({r['assessment'] for r in records if r[axis] == k}, f'rubric_all:{k}')) for k in {r[axis] for r in records})
    if not safe:
        aggregate = {'state': 'restricted', 'buckets': []}
        comparisons = [{'label': g['label'], 'distribution': aggregate} for g in groups]
    return {**output, 'state': aggregate['state'], 'distribution': aggregate, 'comparison': comparisons}
