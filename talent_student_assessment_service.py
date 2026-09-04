"""M5 canonical Student Assessment and deterministic competency-result authority."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

import models


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
        raise TalentStudentAssessmentError("not_found", "Talent Assessment Cycle was not found.")
    if cycle.status != "open":
        raise TalentStudentAssessmentError("cycle_not_open", "Only an Open Cycle accepts Assessment changes.")
    return cycle


def start_assessment(db: Session, *, school_group_id, cycle_id, cycle_population_member_id, actor=None):
    cycle = _cycle(db, school_group_id, cycle_id, lock=True)
    if cycle is None:
        raise TalentStudentAssessmentError("not_found", "Talent Assessment Cycle was not found.")
    if cycle.status != "open":
        raise TalentStudentAssessmentError("cycle_not_open", "Only an Open Cycle accepts Assessments.")
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=cycle_population_member_id, school_group_id=school_group_id, cycle_id=cycle.id,
        program_id=cycle.program_id, academic_year_id=cycle.academic_year_id,
        framework_version_id=cycle.framework_version_id,
    ).with_for_update().one_or_none()
    if member is None:
        raise TalentStudentAssessmentError("invalid_population_member", "Student must belong to this Cycle's frozen population.")
    if db.query(models.TalentStudentAssessment).filter_by(cycle_id=cycle.id, student_id=member.student_id).first():
        raise TalentStudentAssessmentError("duplicate_assessment", "Student already has an Assessment for this Cycle.")
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
    return assessment


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