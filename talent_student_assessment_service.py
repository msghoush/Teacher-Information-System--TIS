"""M5 canonical Student Assessment and deterministic competency-result authority."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

import models
from talent_assessment_cycle_service import create_cycle, population_fingerprint, population_member_payload


class TalentStudentAssessmentError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _clean(value, field, *, maximum=4000):
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) > maximum:
        raise TalentStudentAssessmentError("invalid_input", f"{field} is too long.")
    return cleaned or None


def assessment_payload(row):
    return {
        "id": row.id, "school_group_id": row.school_group_id, "cycle_id": row.cycle_id,
        "cycle_population_member_id": row.cycle_population_member_id, "student_id": row.student_id,
        "program_id": row.program_id, "academic_year_id": row.academic_year_id,
        "framework_version_id": row.framework_version_id, "status": row.status,
        "is_current": bool(getattr(row, "is_current", True)),
        "reassessment_of_assessment_id": getattr(row, "reassessment_of_assessment_id", None),
        "revision": row.revision, "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "kpi_result": row.kpi_result,
        "kpi": None if row.kpi_result is None else {
            "calculation_method": row.kpi_calculation_method,
            "result": row.kpi_result,
            "result_scale_min": row.kpi_result_scale_min,
            "result_scale_max": row.kpi_result_scale_max,
            "weighted_numerator": row.kpi_weighted_numerator,
            "denominator": 10000,
            "calculation_fingerprint": row.kpi_calculation_fingerprint,
            "calculated_at": row.kpi_calculated_at.isoformat() if row.kpi_calculated_at else None,
        },
    }


def competency_result_payload(row):
    return {
        "id": row.id, "assessment_id": row.assessment_id,
        "framework_competency_id": row.framework_competency_id,
        "rubric_id": row.rubric_id, "rubric_level_id": row.rubric_level_id, "evidence": row.evidence,
    }


def _cycle(db, school_group_id, cycle_id, *, lock=False):
    query = db.query(models.TalentAssessmentCycle).filter_by(id=cycle_id, school_group_id=school_group_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _assessment(db, school_group_id, assessment_id, *, lock=False):
    query = db.query(models.TalentStudentAssessment).filter_by(id=assessment_id, school_group_id=school_group_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _audit(db, assessment, *, actor, action, resource_type="student_assessment", resource_id=None, before=None, after=None):
    canonical = _json({"action": action, "before": before, "after": after})
    db.add(models.TalentAssessmentAudit(
        school_group_id=assessment.school_group_id, cycle_id=assessment.cycle_id,
        program_id=assessment.program_id, academic_year_id=assessment.academic_year_id,
        framework_version_id=assessment.framework_version_id, assessment_id=assessment.id,
        cycle_population_member_id=assessment.cycle_population_member_id,
        student_id=assessment.student_id, actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type=resource_type, resource_id=resource_id or assessment.id, action=action,
        before_json=_json(before) if before is not None else None,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def _assert_editable(db, assessment, expected_revision):
    if assessment.revision != int(expected_revision):
        raise TalentStudentAssessmentError("stale_assessment", "Assessment changed since it was read.")
    if assessment.status != "in_progress":
        raise TalentStudentAssessmentError("immutable_assessment", "Only an In Progress Assessment can be edited.")
    cycle = _cycle(db, assessment.school_group_id, assessment.cycle_id, lock=True)
    if cycle is None:
        raise TalentStudentAssessmentError("not_found", "Talent Assessment context was not found.")
    # ADR 0035: Cycle Draft/Open state is internal compatibility metadata, not
    # an Assessment-editability gate. The Assessment's own terminal state is
    # the historical immutability boundary.
    return cycle


def _current_eligible_placement(db, *, cycle, student_id, at):
    config = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        school_group_id=cycle.school_group_id,
        program_id=cycle.program_id,
        academic_year_id=cycle.academic_year_id,
        is_enabled=True,
    ).one_or_none()
    if config is None:
        raise TalentStudentAssessmentError(
            "annual_configuration_unavailable",
            "This Program is not enabled for the selected Academic Year.",
        )
    eligible_grades = {value for value in (config.eligible_grade_levels_csv or "").split(",") if value}
    placement = db.query(models.StudentAcademicPlacement).filter(
        models.StudentAcademicPlacement.school_group_id == cycle.school_group_id,
        models.StudentAcademicPlacement.student_id == int(student_id),
        models.StudentAcademicPlacement.academic_year_id == cycle.academic_year_id,
        models.StudentAcademicPlacement.grade_level.in_(eligible_grades or {"__none__"}),
        models.StudentAcademicPlacement.effective_from <= at,
        (models.StudentAcademicPlacement.effective_to.is_(None) | (models.StudentAcademicPlacement.effective_to > at)),
    ).order_by(models.StudentAcademicPlacement.effective_from.desc()).one_or_none()
    if placement is None:
        raise TalentStudentAssessmentError(
            "student_not_eligible",
            "Student must have a current Academic Placement in a Grade included in this Program.",
        )
    return placement


def _assessment_member_from_current_placement(db, *, cycle, student_id, at):
    placement = _current_eligible_placement(db, cycle=cycle, student_id=student_id, at=at)
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        school_group_id=cycle.school_group_id, cycle_id=cycle.id, student_id=int(student_id)
    ).with_for_update().one_or_none()
    if member is None:
        member = models.TalentAssessmentCyclePopulationMember(
            school_group_id=cycle.school_group_id,
            cycle_id=cycle.id,
            program_id=cycle.program_id,
            academic_year_id=cycle.academic_year_id,
            framework_version_id=cycle.framework_version_id,
            student_id=placement.student_id,
            academic_placement_id=placement.id,
            branch_id=placement.branch_id,
            planning_section_id=placement.planning_section_id,
            grade_level=placement.grade_level,
            section_name=placement.section_name,
            population_effective_at=at,
            frozen_at=at,
        )
        db.add(member)
        db.flush()
    else:
        # Before an Assessment exists this row is only compatibility/provenance
        # storage. Keep it aligned to the current placement that authorizes the
        # Assessment start; once evidence exists, duplicate-assessment protection
        # prevents this path from rewriting historical context.
        member.academic_placement_id = placement.id
        member.branch_id = placement.branch_id
        member.planning_section_id = placement.planning_section_id
        member.grade_level = placement.grade_level
        member.section_name = placement.section_name
        member.population_effective_at = at
        member.frozen_at = at
        db.flush()
    return member


def start_assessment(db: Session, *, school_group_id, cycle_id,
                     cycle_population_member_id=None, student_id=None, actor=None):
    cycle = _cycle(db, school_group_id, cycle_id, lock=True)
    if cycle is None:
        raise TalentStudentAssessmentError("not_found", "Talent Assessment context was not found.")

    program = db.query(models.TalentProgram).filter_by(
        id=cycle.program_id, school_group_id=school_group_id
    ).one_or_none()
    framework = db.query(models.TalentProgramFrameworkVersion).filter_by(
        id=cycle.framework_version_id, school_group_id=school_group_id, program_id=cycle.program_id
    ).one_or_none()
    if program is None or framework is None:
        raise TalentStudentAssessmentError(
            "assessment_tool_unavailable",
            "This Evaluation does not have an assessment tool/framework.",
        )

    # Owner-directed simple assessment flow: the Evaluation's exact Framework
    # is the assessment authority. Draft/Active lifecycle labels are not an
    # additional gate to starting a Student Assessment. What matters here is
    # whether the referenced tool is actually assessable.
    has_competency = db.query(models.FrameworkCompetency.id).filter_by(
        school_group_id=school_group_id,
        program_id=cycle.program_id,
        framework_version_id=cycle.framework_version_id,
    ).first() is not None
    has_rubric_level = db.query(models.TalentRubricLevel.id).filter_by(
        school_group_id=school_group_id,
        program_id=cycle.program_id,
        framework_version_id=cycle.framework_version_id,
    ).first() is not None
    if not has_competency or not has_rubric_level:
        raise TalentStudentAssessmentError(
            "assessment_tool_unavailable",
            "This Evaluation needs at least one competency and one rubric level before Students can be assessed.",
        )

    if student_id is not None:
        member = _assessment_member_from_current_placement(
            db, cycle=cycle, student_id=int(student_id), at=datetime.utcnow()
        )
    else:
        member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
            id=cycle_population_member_id, school_group_id=school_group_id, cycle_id=cycle.id,
            program_id=cycle.program_id, academic_year_id=cycle.academic_year_id,
            framework_version_id=cycle.framework_version_id,
        ).with_for_update().one_or_none()
        if member is None:
            raise TalentStudentAssessmentError(
                "invalid_student_context",
                "Student Assessment context is unavailable. Reload the eligible Students list and try again.",
            )

    if db.query(models.TalentStudentAssessment).filter_by(cycle_id=cycle.id, student_id=member.student_id).first():
        raise TalentStudentAssessmentError("duplicate_assessment", "Student already has an Assessment for this Evaluation.")

    # Existing schema keeps Cycle status for backward compatibility and analytics.
    # First Assessment activity may mark a legacy Draft context Open internally,
    # but there is no user-facing Open Evaluation prerequisite (ADR 0035).
    context_activated = cycle.status == "draft"
    if context_activated:
        now = datetime.utcnow()
        cycle.status = "open"
        cycle.opened_at = cycle.opened_at or now
        cycle.opened_by_user_id = cycle.opened_by_user_id or getattr(actor, "user_id", None)
        cycle.updated_by_user_id = getattr(actor, "user_id", None)
        cycle.updated_at = now
        cycle.revision += 1

    # Keep legacy aggregate metadata internally consistent for existing
    # analytics/readers. It is no longer an eligibility authority (ADR 0035).
    member_rows = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        school_group_id=school_group_id, cycle_id=cycle.id
    ).all()
    cycle.population_count = len(member_rows)
    if cycle.population_effective_at is not None:
        from talent_assessment_cycle_service import population_fingerprint, population_member_payload
        cycle.population_fingerprint = population_fingerprint(
            cycle, [population_member_payload(row) for row in member_rows]
        )

    assessment = models.TalentStudentAssessment(
        school_group_id=school_group_id, cycle_id=cycle.id, cycle_population_member_id=member.id,
        student_id=member.student_id, program_id=cycle.program_id,
        academic_year_id=cycle.academic_year_id, framework_version_id=cycle.framework_version_id,
        status="in_progress", revision=1, created_by_user_id=getattr(actor, "user_id", None),
        updated_by_user_id=getattr(actor, "user_id", None),
    )
    db.add(assessment)
    db.flush()
    _audit(db, assessment, actor=actor, action="create", after=assessment_payload(assessment))
    if context_activated:
        _audit(
            db, assessment, actor=actor, resource_type="assessment_cycle",
            resource_id=cycle.id, action="assessment_activity",
            before={"status": "draft"}, after={"status": "open"},
        )
    return assessment


def reassessment_requirement(db: Session, assessment):
    """Return the newest materially-changed assessable Framework for a completed current Assessment.

    A cloned-but-unchanged draft does not trigger re-evaluation. Historical
    evidence remains bound to the Assessment's exact Framework; this helper only
    reports whether a newer saved Framework has a different semantic fingerprint.
    """
    if assessment.status != "completed" or not bool(getattr(assessment, "is_current", True)):
        return None
    current_framework = db.query(models.TalentProgramFrameworkVersion).filter_by(
        id=assessment.framework_version_id,
        school_group_id=assessment.school_group_id,
        program_id=assessment.program_id,
    ).one_or_none()
    if current_framework is None:
        return None
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=assessment.cycle_population_member_id,
        school_group_id=assessment.school_group_id,
        student_id=assessment.student_id,
    ).one_or_none()
    grade = member.grade_level if member is not None else None
    candidates = db.query(models.TalentProgramFrameworkVersion).filter(
        models.TalentProgramFrameworkVersion.school_group_id == assessment.school_group_id,
        models.TalentProgramFrameworkVersion.program_id == assessment.program_id,
        models.TalentProgramFrameworkVersion.version_number > current_framework.version_number,
    ).order_by(models.TalentProgramFrameworkVersion.version_number.desc()).all()
    for framework in candidates:
        if framework.semantic_fingerprint == current_framework.semantic_fingerprint:
            continue
        has_level = db.query(models.TalentRubricLevel.id).filter_by(
            school_group_id=assessment.school_group_id,
            program_id=assessment.program_id,
            framework_version_id=framework.id,
        ).first() is not None
        competency_query = db.query(models.FrameworkCompetency.id).filter_by(
            school_group_id=assessment.school_group_id,
            program_id=assessment.program_id,
            framework_version_id=framework.id,
        )
        if grade:
            competency_query = competency_query.filter(
                (models.FrameworkCompetency.grade_level.is_(None))
                | (models.FrameworkCompetency.grade_level == grade)
            )
        if has_level and competency_query.first() is not None:
            return framework
    return None


def start_reassessment(db: Session, *, school_group_id, assessment_id, actor=None):
    """Create a new current Assessment against the newest changed Framework.

    The prior completed Assessment and all of its evidence remain immutable.
    The reassessment receives its own ad-hoc Cycle/population member so existing
    Cycle/Student uniqueness and historical provenance are preserved.
    """
    prior = _assessment(db, school_group_id, assessment_id, lock=True)
    if prior is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    if prior.status != "completed":
        raise TalentStudentAssessmentError("reassessment_not_available", "Only a Completed Assessment can be re-evaluated.")
    if not bool(getattr(prior, "is_current", True)):
        raise TalentStudentAssessmentError("reassessment_not_available", "This historical Assessment has already been superseded.")
    framework = reassessment_requirement(db, prior)
    if framework is None:
        raise TalentStudentAssessmentError("reassessment_not_required", "No newer saved rubric requires re-evaluation for this Student.")
    old_cycle = _cycle(db, school_group_id, prior.cycle_id)
    if old_cycle is None:
        raise TalentStudentAssessmentError("not_found", "Talent Assessment context was not found.")
    cycle = create_cycle(
        db,
        school_group_id=school_group_id,
        program_id=prior.program_id,
        academic_year_id=prior.academic_year_id,
        framework_version_id=framework.id,
        title=f"{old_cycle.title} · Re-evaluation",
        description="Re-evaluation after rubric update; prior completed evidence remains historical.",
        population_effective_at=datetime.utcnow(),
        actor=actor,
    )
    replacement = start_assessment(
        db,
        school_group_id=school_group_id,
        cycle_id=cycle.id,
        student_id=prior.student_id,
        actor=actor,
    )
    before = assessment_payload(prior)
    prior.is_current = False
    prior.updated_by_user_id = getattr(actor, "user_id", None)
    prior.updated_at = datetime.utcnow()
    replacement.is_current = True
    replacement.reassessment_of_assessment_id = prior.id
    replacement.updated_by_user_id = getattr(actor, "user_id", None)
    replacement.updated_at = datetime.utcnow()
    db.flush()
    _audit(
        db, prior, actor=actor, action="superseded_for_reassessment",
        before=before, after=assessment_payload(prior),
    )
    _audit(
        db, replacement, actor=actor, action="reassessment_linked",
        after={"reassessment_of_assessment_id": prior.id, "framework_version_id": framework.id},
    )
    return replacement


def get_assessment(db, *, school_group_id, assessment_id):
    row = _assessment(db, school_group_id, assessment_id)
    if row is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    return row


def list_assessments(db, *, school_group_id, cycle_id=None):
    query = db.query(models.TalentStudentAssessment).filter_by(school_group_id=school_group_id)
    if cycle_id is not None:
        query = query.filter_by(cycle_id=cycle_id)
    return query.order_by(models.TalentStudentAssessment.id).all()


def list_competency_results(db, *, school_group_id, assessment_id):
    assessment = get_assessment(db, school_group_id=school_group_id, assessment_id=assessment_id)
    rows = db.query(models.TalentStudentCompetencyResult).filter_by(
        school_group_id=school_group_id, assessment_id=assessment.id,
    ).order_by(models.TalentStudentCompetencyResult.framework_competency_id).all()
    return assessment, rows


def set_competency_result(db, *, school_group_id, assessment_id, framework_competency_id,
                          rubric_level_id, expected_revision, evidence=None, actor=None):
    assessment = _assessment(db, school_group_id, assessment_id, lock=True)
    if assessment is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    _assert_editable(db, assessment, expected_revision)
    competency = db.query(models.FrameworkCompetency).filter_by(
        id=framework_competency_id, school_group_id=school_group_id,
        program_id=assessment.program_id, framework_version_id=assessment.framework_version_id,
    ).one_or_none()
    level = db.query(models.TalentRubricLevel).filter_by(
        id=rubric_level_id, school_group_id=school_group_id,
        program_id=assessment.program_id, framework_version_id=assessment.framework_version_id,
    ).one_or_none()
    if competency is None or level is None:
        raise TalentStudentAssessmentError("invalid_result_scope", "Competency and rubric level must belong to the Assessment's exact Framework.")
    result = db.query(models.TalentStudentCompetencyResult).filter_by(
        assessment_id=assessment.id, framework_competency_id=competency.id,
    ).one_or_none()
    before = competency_result_payload(result) if result else None
    if result is None:
        result = models.TalentStudentCompetencyResult(
            school_group_id=school_group_id, assessment_id=assessment.id, cycle_id=assessment.cycle_id,
            student_id=assessment.student_id, program_id=assessment.program_id,
            academic_year_id=assessment.academic_year_id, framework_version_id=assessment.framework_version_id,
            framework_competency_id=competency.id, rubric_id=level.rubric_id, rubric_level_id=level.id,
            evidence=_clean(evidence, "evidence"), created_by_user_id=getattr(actor, "user_id", None),
            updated_by_user_id=getattr(actor, "user_id", None),
        )
        db.add(result)
    else:
        result.rubric_level_id = level.id
        if evidence is not None:
            result.evidence = _clean(evidence, "evidence")
        result.updated_by_user_id = getattr(actor, "user_id", None)
        result.updated_at = datetime.utcnow()
    assessment.revision += 1
    assessment.updated_by_user_id = getattr(actor, "user_id", None)
    assessment.updated_at = datetime.utcnow()
    db.flush()
    _audit(db, assessment, actor=actor, resource_type="competency_result", resource_id=result.id,
           action="create" if before is None else "update", before=_audit_result(before),
           after=_audit_result(competency_result_payload(result)))
    return result, assessment


def _audit_result(value):
    if value is None:
        return None
    return {key: value[key] for key in ("id", "assessment_id", "framework_competency_id", "rubric_id", "rubric_level_id")}


def remove_competency_result(db, *, school_group_id, assessment_id, framework_competency_id, expected_revision, actor=None):
    assessment = _assessment(db, school_group_id, assessment_id, lock=True)
    if assessment is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    _assert_editable(db, assessment, expected_revision)
    result = db.query(models.TalentStudentCompetencyResult).filter_by(
        assessment_id=assessment.id, framework_competency_id=framework_competency_id,
    ).one_or_none()
    if result is None:
        raise TalentStudentAssessmentError("not_found", "Competency result was not found.")
    before = _audit_result(competency_result_payload(result))
    result_id = result.id
    db.delete(result)
    assessment.revision += 1
    assessment.updated_by_user_id = getattr(actor, "user_id", None)
    assessment.updated_at = datetime.utcnow()
    db.flush()
    _audit(db, assessment, actor=actor, resource_type="competency_result", resource_id=result_id,
           action="remove", before=before)
    return assessment


def _round_half_up(numerator, denominator=10000):
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) + denominator // 2) // denominator)


def _calculate_kpi(db, assessment):
    kpi = db.query(models.TalentKpiConfiguration).filter_by(
        school_group_id=assessment.school_group_id, program_id=assessment.program_id,
        framework_version_id=assessment.framework_version_id, is_enabled=True,
    ).one_or_none()
    if kpi is None:
        return None
    components = db.query(models.TalentKpiComponent).filter_by(
        school_group_id=assessment.school_group_id, program_id=assessment.program_id,
        framework_version_id=assessment.framework_version_id, kpi_configuration_id=kpi.id,
    ).order_by(models.TalentKpiComponent.framework_competency_id).all()
    if kpi.calculation_method != "weighted_level_average" or not components or sum(row.weight_basis_points for row in components) != 10000:
        raise TalentStudentAssessmentError("invalid_kpi", "Framework KPI configuration is invalid.")
    results = {
        row.framework_competency_id: row for row in db.query(models.TalentStudentCompetencyResult).filter_by(
            school_group_id=assessment.school_group_id, assessment_id=assessment.id,
        ).all()
    }
    inputs = []
    numerator = 0
    for component in components:
        result = results.get(component.framework_competency_id)
        if result is None:
            raise TalentStudentAssessmentError("kpi_input_required", "Completed Assessment requires every configured KPI competency result.")
        level = db.query(models.TalentRubricLevel).filter_by(
            id=result.rubric_level_id, school_group_id=assessment.school_group_id,
            program_id=assessment.program_id, framework_version_id=assessment.framework_version_id,
        ).one_or_none()
        if level is None or level.numeric_value is None or not kpi.result_scale_min <= level.numeric_value <= kpi.result_scale_max:
            raise TalentStudentAssessmentError("kpi_input_required", "Completed Assessment requires numeric KPI inputs within the Framework result scale.")
        contribution = level.numeric_value * component.weight_basis_points
        numerator += contribution
        inputs.append({
            "framework_competency_id": component.framework_competency_id,
            "weight_basis_points": component.weight_basis_points,
            "rubric_level_id": level.id,
            "numeric_value": level.numeric_value,
        })
    result = _round_half_up(numerator)
    payload = {
        "assessment_id": assessment.id, "cycle_id": assessment.cycle_id,
        "framework_version_id": assessment.framework_version_id,
        "calculation_method": kpi.calculation_method,
        "result_scale_min": kpi.result_scale_min, "result_scale_max": kpi.result_scale_max,
        "components": inputs, "weighted_numerator": numerator,
        "denominator": 10000, "result": result,
    }
    return {**payload, "calculation_fingerprint": hashlib.sha256(_json(payload).encode()).hexdigest()}


def _validate_completeness(db, assessment):
    required = {
        row.id for row in db.query(models.FrameworkCompetency).filter_by(
            school_group_id=assessment.school_group_id, program_id=assessment.program_id,
            framework_version_id=assessment.framework_version_id,
        ).all()
    }
    results = db.query(models.TalentStudentCompetencyResult).filter_by(
        school_group_id=assessment.school_group_id, assessment_id=assessment.id,
    ).all()
    actual = {row.framework_competency_id for row in results}
    if not required or actual != required:
        raise TalentStudentAssessmentError("incomplete_assessment", "Completed Assessment requires a valid result for every Framework competency.")


def complete_assessment(db, *, school_group_id, assessment_id, expected_revision, actor=None):
    assessment = _assessment(db, school_group_id, assessment_id, lock=True)
    if assessment is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    _assert_editable(db, assessment, expected_revision)
    _validate_completeness(db, assessment)
    kpi = _calculate_kpi(db, assessment)
    before = assessment_payload(assessment)
    now = datetime.utcnow()
    assessment.status = "completed"
    assessment.completed_at = now
    assessment.completed_by_user_id = getattr(actor, "user_id", None)
    assessment.revision += 1
    assessment.updated_by_user_id = getattr(actor, "user_id", None)
    assessment.updated_at = now
    if kpi is not None:
        assessment.kpi_calculation_method = kpi["calculation_method"]
        assessment.kpi_result = kpi["result"]
        assessment.kpi_result_scale_min = kpi["result_scale_min"]
        assessment.kpi_result_scale_max = kpi["result_scale_max"]
        assessment.kpi_weighted_numerator = kpi["weighted_numerator"]
        assessment.kpi_calculation_fingerprint = kpi["calculation_fingerprint"]
        assessment.kpi_calculated_at = now
    db.flush()
    _audit(db, assessment, actor=actor, action="complete", before=before, after=assessment_payload(assessment))
    return assessment


_ASSESSMENT_DELETE_BLOCKER_TABLES = (
    (models.TalentStudentCompetencyResult, "competency results"),
    (models.TalentReviewCandidate, "a Talent Review Candidate record"),
    (models.TalentOfficialIdentification, "an Official Identification decision"),
    (models.TalentEducatorInput, "Educator Input"),
)


def assessment_delete_blockers(db, *, assessment_id):
    """Real, re-verified list of dependent-evidence labels that block a delete (ADR 0034).

    Every dependent table checked here (`TalentStudentCompetencyResult`,
    `TalentReviewCandidate`, `TalentOfficialIdentification`, `TalentEducatorInput`)
    carries a direct `assessment_id` column in the current schema - re-verified
    against `models.py`, not assumed from ADR 0034's description alone.
    """
    return [label for model, label in _ASSESSMENT_DELETE_BLOCKER_TABLES
            if db.query(model.id).filter_by(assessment_id=assessment_id).first() is not None]


def can_delete_assessment(db, *, assessment_id):
    """Real backend capability check (ADR 0034): zero dependent evidence/history rows."""
    return not assessment_delete_blockers(db, assessment_id=assessment_id)


def delete_assessment(db, *, school_group_id, assessment_id, actor=None):
    """Hard-delete a Student Assessment per ADR 0034's exact, scoped zero-evidence exception.

    Allowed only when zero `TalentStudentCompetencyResult`, `TalentReviewCandidate`,
    `TalentOfficialIdentification`, or `TalentEducatorInput` rows reference this
    Assessment. Any such row is rejected outright - never a silent no-op, never a
    partial delete, never a cascade-delete of the dependent evidence itself. This
    never touches `TalentAssessmentCyclePopulationMember` rows, Student placement
    history, or Cycle population records - only the Assessment row itself is
    removed.
    """
    assessment = _assessment(db, school_group_id, assessment_id, lock=True)
    if assessment is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    blockers = assessment_delete_blockers(db, assessment_id=assessment.id)
    if blockers:
        raise TalentStudentAssessmentError(
            "assessment_has_dependents",
            "This Assessment has recorded " + ", ".join(blockers) + " and cannot be deleted.",
        )
    before = assessment_payload(assessment)
    _audit(db, assessment, actor=actor, action="delete", before=before)
    db.delete(assessment)
    db.flush()
    return assessment.id


def mark_non_complete(db, *, school_group_id, assessment_id, expected_revision, status, actor=None):
    if status not in {"incomplete", "insufficient_evidence"}:
        raise TalentStudentAssessmentError("invalid_status", "Assessment status must be Incomplete or Insufficient Evidence.")
    assessment = _assessment(db, school_group_id, assessment_id, lock=True)
    if assessment is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    _assert_editable(db, assessment, expected_revision)
    before = assessment_payload(assessment)
    assessment.status = status
    assessment.revision += 1
    assessment.updated_by_user_id = getattr(actor, "user_id", None)
    assessment.updated_at = datetime.utcnow()
    db.flush()
    _audit(db, assessment, actor=actor, action="mark_incomplete" if status == "incomplete" else "mark_insufficient_evidence", before=before, after=assessment_payload(assessment))
    return assessment