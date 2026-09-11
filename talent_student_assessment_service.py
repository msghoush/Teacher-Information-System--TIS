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
        "evaluation_context_cycle_id": row.evaluation_context_cycle_id or row.cycle_id,
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
                     cycle_population_member_id=None, student_id=None,
                     evaluation_context_cycle_id=None, actor=None):
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

    # Low-level/legacy callers remain backward-compatible so existing evidence
    # is not stranded. The normal Evaluation workflow is stricter:
    # start_assessment_for_evaluation() selects only a complete competency-owned
    # rubric structure for current user-facing assessment work.
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

    root_cycle_id = int(evaluation_context_cycle_id or cycle.id)
    existing_query = db.query(models.TalentStudentAssessment).filter(
        models.TalentStudentAssessment.school_group_id == school_group_id,
        models.TalentStudentAssessment.student_id == member.student_id,
        models.TalentStudentAssessment.is_current.is_(True),
        (
            (models.TalentStudentAssessment.evaluation_context_cycle_id == root_cycle_id)
            | (
                models.TalentStudentAssessment.evaluation_context_cycle_id.is_(None)
                & (models.TalentStudentAssessment.cycle_id == root_cycle_id)
            )
        ),
    )
    if existing_query.first() is not None:
        raise TalentStudentAssessmentError("duplicate_assessment", "Student already has a current Assessment for this Evaluation.")

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
        school_group_id=school_group_id, cycle_id=cycle.id,
        evaluation_context_cycle_id=root_cycle_id,
        cycle_population_member_id=member.id,
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


def _assessment_semantic_snapshot(db: Session, *, framework, grade, allow_legacy=True):
    """Student-facing assessment structure for one Framework and historical Grade.

    Deliberately excludes Framework version/title/supersession metadata so a
    no-op clone does not trigger re-evaluation. Only assessable content that can
    change what the educator evaluates is compared.
    """
    member_query = db.query(models.FrameworkCompetency).filter_by(
        school_group_id=framework.school_group_id,
        program_id=framework.program_id,
        framework_version_id=framework.id,
    )
    if grade:
        member_query = member_query.filter(
            (models.FrameworkCompetency.grade_level.is_(None))
            | (models.FrameworkCompetency.grade_level == grade)
        )
    members = member_query.order_by(
        models.FrameworkCompetency.display_order,
        models.FrameworkCompetency.id,
    ).all()

    legacy_rubric = None
    if allow_legacy:
        legacy_rubric = db.query(models.TalentRubric).filter(
            models.TalentRubric.framework_version_id == framework.id,
            models.TalentRubric.framework_competency_id.is_(None),
        ).one_or_none()

    result = []
    for member in members:
        rubric = db.query(models.TalentRubric).filter_by(
            framework_version_id=framework.id,
            framework_competency_id=member.id,
        ).one_or_none() or legacy_rubric
        levels = []
        if rubric is not None:
            for level in db.query(models.TalentRubricLevel).filter_by(
                framework_version_id=framework.id,
                rubric_id=rubric.id,
            ).order_by(
                models.TalentRubricLevel.display_order,
                models.TalentRubricLevel.id,
            ):
                grade_descriptor = None
                if grade:
                    grade_descriptor = db.query(
                        models.TalentGradeCompetencyRubricDescriptor
                    ).filter_by(
                        framework_version_id=framework.id,
                        framework_competency_id=member.id,
                        rubric_level_id=level.id,
                        grade_level=grade,
                    ).one_or_none()
                generic_descriptor = db.query(
                    models.TalentCompetencyRubricDescriptor
                ).filter_by(
                    framework_version_id=framework.id,
                    framework_competency_id=member.id,
                    rubric_level_id=level.id,
                ).one_or_none()
                levels.append({
                    "order": level.display_order,
                    "label": level.label,
                    "description": level.description,
                    "numeric_value": level.numeric_value,
                    "achievement_description": (
                        grade_descriptor.descriptor
                        if grade_descriptor is not None
                        else generic_descriptor.descriptor
                        if generic_descriptor is not None
                        else level.description
                    ),
                })
        result.append({
            "order": member.display_order,
            "grade_level": member.grade_level,
            "label": member.label,
            "description": member.description,
            "rubric": None if rubric is None else {
                "name": rubric.name,
                "description": rubric.description,
                "levels": levels,
            },
        })
    return result


def _has_assessable_competency(snapshot):
    """True when at least one Competency in the snapshot has a complete KPI/rubric with levels.

    Per ADR 0039, Start Assessment eligibility requires at least one
    assessable Competency on the framework - not that every Competency in
    the snapshot is complete, and not that assessable content exists
    specifically for the Student's Grade.
    """
    return any(
        item.get("rubric") and item["rubric"].get("levels")
        for item in snapshot
    )


def _newest_assessable_framework(db: Session, *, cycle, grade):
    """Newest Framework Version with at least one usable Competency+KPI+Levels.

    Per ADR 0039, Grade is preferred context, not an eligibility gate: a
    Framework Version is assessable if it has assessable content scoped to
    the Student's Grade (preferred when present) OR assessable content
    anywhere on the Program's saved build (used instead of blocking when no
    Grade-specific content exists).
    """
    candidates = db.query(models.TalentProgramFrameworkVersion).filter_by(
        school_group_id=cycle.school_group_id,
        program_id=cycle.program_id,
    ).order_by(
        models.TalentProgramFrameworkVersion.version_number.desc(),
        models.TalentProgramFrameworkVersion.id.desc(),
    ).all()
    for framework in candidates:
        graded_snapshot = _assessment_semantic_snapshot(
            db, framework=framework, grade=grade, allow_legacy=False
        )
        if _has_assessable_competency(graded_snapshot):
            return framework
        full_snapshot = _assessment_semantic_snapshot(
            db, framework=framework, grade=None, allow_legacy=False
        )
        if _has_assessable_competency(full_snapshot):
            return framework
    return None


def start_assessment_for_evaluation(
    db: Session, *, school_group_id, evaluation_cycle_id, student_id, actor=None
):
    """Start a Student against the newest saved assessable rubric for one Evaluation.

    The visible Evaluation/Term identity remains the original Cycle. When its
    frozen Framework is older than the newest rubric, a private derived Cycle
    captures the newer Framework while the Assessment keeps
    evaluation_context_cycle_id pointing to the original Evaluation.
    """
    root_cycle = _cycle(db, school_group_id, evaluation_cycle_id, lock=True)
    if root_cycle is None:
        raise TalentStudentAssessmentError("not_found", "Talent Assessment context was not found.")
    placement = _current_eligible_placement(
        db, cycle=root_cycle, student_id=int(student_id), at=datetime.utcnow()
    )
    newest = _newest_assessable_framework(
        db, cycle=root_cycle, grade=placement.grade_level
    )
    if newest is None:
        raise TalentStudentAssessmentError(
            "assessment_tool_unavailable",
            "This Program needs at least one Competency with a KPI and at least one Level before Assessment can start.",
        )
    # The physical schema has a durable UNIQUE(cycle_id, student_id)
    # constraint. After an Administrator reset, the completed historical row
    # remains on the original Cycle by design, so a fresh current attempt must
    # use a private derived Cycle even when the assessable Framework itself did
    # not change. The visible Evaluation remains the original root Cycle.
    prior_on_root = db.query(models.TalentStudentAssessment.id).filter_by(
        school_group_id=school_group_id,
        cycle_id=root_cycle.id,
        student_id=int(student_id),
    ).first() is not None

    if newest.id == root_cycle.framework_version_id and not prior_on_root:
        return start_assessment(
            db, school_group_id=school_group_id, cycle_id=root_cycle.id,
            student_id=int(student_id), evaluation_context_cycle_id=root_cycle.id,
            actor=actor,
        )

    derived_cycle = create_cycle(
        db,
        school_group_id=school_group_id,
        program_id=root_cycle.program_id,
        academic_year_id=root_cycle.academic_year_id,
        framework_version_id=newest.id,
        title=(
            f"{root_cycle.title} · Re-assessment"
            if prior_on_root and newest.id == root_cycle.framework_version_id
            else f"{root_cycle.title} · Current rubric"
        ),
        description=(
            "Internal re-assessment attempt context; prior completed evidence remains historical."
            if prior_on_root and newest.id == root_cycle.framework_version_id
            else "Internal rubric-version context for the visible Evaluation."
        ),
        population_effective_at=datetime.utcnow(),
        actor=actor,
    )
    return start_assessment(
        db, school_group_id=school_group_id, cycle_id=derived_cycle.id,
        student_id=int(student_id), evaluation_context_cycle_id=root_cycle.id,
        actor=actor,
    )



def _same_framework_results_are_stale(db: Session, assessment, framework, grade):
    """Detect legacy in-place rubric changes against an already-completed Assessment.

    Before Framework immutability was enforced consistently, a completed
    Assessment could remain bound to the same Framework Version while that
    Version moved from a legacy/shared rubric to the current competency-owned
    rubric structure. The persisted competency-result bindings are the immutable
    evidence of what the Student actually used. If those bindings no longer
    match the Framework's current Grade-applicable competency-owned rubrics,
    the current result must be re-evaluated even though the version number did
    not change.
    """
    members = [
        row for row in db.query(models.FrameworkCompetency).filter_by(
            school_group_id=assessment.school_group_id,
            program_id=assessment.program_id,
            framework_version_id=framework.id,
        ).order_by(models.FrameworkCompetency.display_order, models.FrameworkCompetency.id)
        if not row.grade_level or str(row.grade_level) == str(grade or "")
    ]
    if not members:
        return False

    # Only a complete current competency-owned rubric can supersede the
    # completed legacy binding. A still-legacy or partially configured
    # Framework is not a valid reassessment target and must not create a false
    # "Re-evaluation required" state.
    current_rubrics = {}
    current_level_ids = {}
    for member in members:
        rubric = db.query(models.TalentRubric).filter_by(
            school_group_id=assessment.school_group_id,
            program_id=assessment.program_id,
            framework_version_id=framework.id,
            framework_competency_id=member.id,
        ).one_or_none()
        if rubric is None:
            return False
        level_ids = {
            row.id for row in db.query(models.TalentRubricLevel).filter_by(
                school_group_id=assessment.school_group_id,
                program_id=assessment.program_id,
                framework_version_id=framework.id,
                rubric_id=rubric.id,
            ).all()
        }
        if not level_ids:
            return False
        current_rubrics[member.id] = rubric
        current_level_ids[member.id] = level_ids

    results = {
        row.framework_competency_id: row
        for row in db.query(models.TalentStudentCompetencyResult).filter_by(
            school_group_id=assessment.school_group_id,
            assessment_id=assessment.id,
        ).all()
    }
    member_ids = {row.id for row in members}
    if set(results) != member_ids:
        return True

    for member in members:
        result = results.get(member.id)
        rubric = current_rubrics[member.id]
        if result is None or result.rubric_id != rubric.id or result.rubric_level_id not in current_level_ids[member.id]:
            return True
    return False



_SAME_VERSION_SEMANTIC_AUDIT_RESOURCES = {
    "framework_version",
    "framework_competency",
    "rubric",
    "rubric_level",
    "rubric_descriptor",
    "kpi_configuration",
    "kpi_component",
    "review_candidate_policy",
    "review_candidate_rule",
}


def _audit_payload_framework_id(payload):
    if not isinstance(payload, dict):
        return None
    value = payload.get("framework_id")
    if value is not None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    configuration = payload.get("configuration")
    if isinstance(configuration, dict):
        value = configuration.get("framework_id")
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _framework_semantically_changed_after_completion(db: Session, assessment, framework):
    """Detect audited legacy in-place semantic edits after Assessment completion.

    Stable rubric/level IDs are insufficient for pre-immutability data because
    labels, descriptions, ordering, or other Student-facing semantics could have
    been edited in place. TalentConfigurationAudit is the durable evidence of
    those mutations. Only semantic resource types on this exact Framework are
    considered; lifecycle/branding/annual-plan changes do not trigger
    reassessment.
    """
    completed_at = getattr(assessment, "completed_at", None)
    if completed_at is None:
        return False

    audits = db.query(models.TalentConfigurationAudit).filter(
        models.TalentConfigurationAudit.school_group_id == assessment.school_group_id,
        models.TalentConfigurationAudit.program_id == assessment.program_id,
        models.TalentConfigurationAudit.created_at > completed_at,
        models.TalentConfigurationAudit.resource_type.in_(
            _SAME_VERSION_SEMANTIC_AUDIT_RESOURCES
        ),
    ).order_by(models.TalentConfigurationAudit.created_at.asc(), models.TalentConfigurationAudit.id.asc()).all()

    for audit in audits:
        if audit.resource_type == "framework_version":
            if audit.resource_id == framework.id and audit.action == "reorder":
                return True
            continue

        if audit.resource_type == "framework_competency":
            member = db.query(models.FrameworkCompetency.id).filter_by(
                id=audit.resource_id,
                school_group_id=assessment.school_group_id,
                program_id=assessment.program_id,
                framework_version_id=framework.id,
            ).first()
            if member is not None:
                return True
            continue

        for raw in (audit.after_json, audit.before_json):
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if _audit_payload_framework_id(payload) == framework.id:
                return True
    return False



def reassessment_requirement(db: Session, assessment):
    """Return the newest materially-changed assessable Framework for a completed current Assessment.

    A cloned-but-unchanged draft does not trigger re-evaluation. Historical
    evidence remains bound to the Assessment's exact Framework. In addition to
    newer materially changed Framework Versions, this helper detects legacy
    same-Version rubric replacement by comparing the completed Assessment's
    persisted competency/rubric-level bindings with the current canonical
    competency-owned rubric structure.
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
    current_snapshot = _assessment_semantic_snapshot(
        db, framework=current_framework, grade=grade, allow_legacy=True
    )

    # Compatibility repair for real data created before the immutable-version
    # guard was applied consistently. A completed Student whose persisted
    # result bindings no longer match the current competency-owned rubric on
    # the same Framework must be reset operationally through reassessment.
    same_version_stale = _same_framework_results_are_stale(
        db, assessment, current_framework, grade
    )
    if same_version_stale:
        return current_framework

    # Legacy in-place edits can preserve every rubric/level ID while changing
    # Student-facing labels, descriptions, ordering, or policy semantics. The
    # configuration audit timestamp closes that gap: if an audited semantic
    # mutation occurred after this Student completed, the result is stale even
    # when its persisted bindings still point at the same IDs.
    if _framework_semantically_changed_after_completion(
        db, assessment, current_framework
    ):
        current_complete = _assessment_semantic_snapshot(
            db, framework=current_framework, grade=grade, allow_legacy=False
        )
        if current_complete and all(
            item.get("rubric") and item["rubric"].get("levels")
            for item in current_complete
        ):
            return current_framework

    for framework in candidates:
        candidate_snapshot = _assessment_semantic_snapshot(
            db, framework=framework, grade=grade, allow_legacy=False
        )
        if candidate_snapshot == current_snapshot:
            continue
        if candidate_snapshot and all(
            item.get("rubric") and item["rubric"].get("levels")
            for item in candidate_snapshot
        ):
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
    before = assessment_payload(prior)
    prior.is_current = False
    prior.updated_by_user_id = getattr(actor, "user_id", None)
    prior.updated_at = datetime.utcnow()
    db.flush()

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
        evaluation_context_cycle_id=prior.evaluation_context_cycle_id or prior.cycle_id,
        actor=actor,
    )
    replacement.is_current = True
    replacement.reassessment_of_assessment_id = prior.id
    replacement.evaluation_context_cycle_id = prior.evaluation_context_cycle_id or prior.cycle_id
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
        query = query.filter(
            (models.TalentStudentAssessment.evaluation_context_cycle_id == cycle_id)
            | (
                models.TalentStudentAssessment.evaluation_context_cycle_id.is_(None)
                & (models.TalentStudentAssessment.cycle_id == cycle_id)
            )
        )
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
    applicable_ids = {row.id for row in _applicable_competencies(db, assessment)}
    if competency.id not in applicable_ids:
        raise TalentStudentAssessmentError("invalid_result_scope", "Competency is not applicable to the Student's recorded Grade.")
    rubric = db.query(models.TalentRubric).filter_by(
        id=level.rubric_id, school_group_id=school_group_id,
        program_id=assessment.program_id, framework_version_id=assessment.framework_version_id,
    ).one_or_none()
    if rubric is None or (
        rubric.framework_competency_id is not None
        and rubric.framework_competency_id != competency.id
    ):
        raise TalentStudentAssessmentError(
            "invalid_result_scope",
            "Rubric level must belong to this exact Competency rubric.",
        )
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
        result.rubric_id = level.rubric_id
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


def _assessment_grade(db, assessment):
    member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        id=assessment.cycle_population_member_id,
        school_group_id=assessment.school_group_id,
        student_id=assessment.student_id,
    ).one_or_none()
    return member.grade_level if member is not None else None


def _applicable_competencies(db, assessment):
    query = db.query(models.FrameworkCompetency).filter_by(
        school_group_id=assessment.school_group_id,
        program_id=assessment.program_id,
        framework_version_id=assessment.framework_version_id,
    )
    grade = _assessment_grade(db, assessment)
    if grade:
        query = query.filter(
            (models.FrameworkCompetency.grade_level.is_(None))
            | (models.FrameworkCompetency.grade_level == grade)
        )
    return query.all()


def overall_program_result(db: Session, assessment):
    """Deterministic arithmetic mean of rubric ranks on the Program scale.

    The canonical educational result is the mean selected level position, for
    example 4.4 / 5. A percentage is derived only for presentation/analytics.
    All applicable competency rubrics must use the same ordered level count so
    raw rubric ranks have one coherent meaning inside the Program.
    """
    competencies = _applicable_competencies(db, assessment)
    if not competencies:
        return None
    results = {
        row.framework_competency_id: row
        for row in db.query(models.TalentStudentCompetencyResult).filter_by(
            school_group_id=assessment.school_group_id,
            assessment_id=assessment.id,
        ).all()
    }
    if any(item.id not in results for item in competencies):
        return None

    components = []
    total_positions = 0
    scale_max = None
    for competency in competencies:
        result = results[competency.id]
        levels = db.query(models.TalentRubricLevel).filter_by(
            school_group_id=assessment.school_group_id,
            program_id=assessment.program_id,
            framework_version_id=assessment.framework_version_id,
            rubric_id=result.rubric_id,
        ).order_by(
            models.TalentRubricLevel.display_order,
            models.TalentRubricLevel.id,
        ).all()
        if not levels:
            return None
        if scale_max is None:
            scale_max = len(levels)
        elif len(levels) != scale_max:
            return {
                "available": False,
                "reason": "inconsistent_rubric_scale",
                "competency_count": len(competencies),
                "calculation_method": "arithmetic_mean_rubric_rank",
            }
        index = next((idx for idx, level in enumerate(levels) if level.id == result.rubric_level_id), None)
        if index is None:
            return None
        position = index + 1
        total_positions += position
        level = levels[index]
        components.append({
            "framework_competency_id": competency.id,
            "competency_label": competency.label,
            "rubric_id": result.rubric_id,
            "rubric_level_id": level.id,
            "level_label": level.label,
            "position": position,
            "scale_max": len(levels),
        })

    if not scale_max:
        return None
    average_tenths = _round_half_up(total_positions * 10, len(components))
    average = average_tenths / 10
    normalized_percent = _round_half_up(average_tenths * 100, scale_max * 10)
    return {
        "available": True,
        "average": average,
        "scale_min": 1,
        "scale_max": scale_max,
        "normalized_percent": normalized_percent,
        "competency_count": len(components),
        "components": components,
        "calculation_method": "arithmetic_mean_rubric_rank",
    }


def _validate_completeness(db, assessment):
    required = {row.id for row in _applicable_competencies(db, assessment)}
    results = db.query(models.TalentStudentCompetencyResult).filter_by(
        school_group_id=assessment.school_group_id, assessment_id=assessment.id,
    ).all()
    actual = {row.framework_competency_id for row in results}
    if not required or actual != required:
        raise TalentStudentAssessmentError("incomplete_assessment", "Completed Assessment requires a valid result for every Framework competency.")
    overall = overall_program_result(db, assessment)
    if overall and overall.get("available") is False and overall.get("reason") == "inconsistent_rubric_scale":
        raise TalentStudentAssessmentError(
            "inconsistent_rubric_scale",
            "All Competencies in this Program assessment must use the same number of ordered rubric levels before the Assessment can be completed.",
        )


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



def reset_completed_assessment_for_reassessment(db, *, school_group_id, assessment_id, actor=None):
    """Make one Completed current Assessment historical so the same Evaluation can start again.

    This is an operational recovery action, not a hard delete. All competency
    results, review/identification records, educator input, placement context,
    and audit history remain attached to the prior Assessment. Only its current
    pointer is cleared, allowing the normal start path to create a fresh current
    Assessment for the same visible Evaluation.
    """
    assessment = _assessment(db, school_group_id, assessment_id, lock=True)
    if assessment is None:
        raise TalentStudentAssessmentError("not_found", "Student Assessment was not found.")
    if assessment.status != "completed":
        raise TalentStudentAssessmentError(
            "reset_not_available", "Only a Completed Assessment can be reset for re-assessment."
        )
    if not bool(getattr(assessment, "is_current", True)):
        raise TalentStudentAssessmentError(
            "reset_not_available", "This Assessment is already historical."
        )
    before = assessment_payload(assessment)
    assessment.is_current = False
    assessment.updated_by_user_id = getattr(actor, "user_id", None)
    assessment.updated_at = datetime.utcnow()
    db.flush()
    _audit(
        db, assessment, actor=actor, action="reset_for_reassessment",
        before=before, after=assessment_payload(assessment),
    )
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