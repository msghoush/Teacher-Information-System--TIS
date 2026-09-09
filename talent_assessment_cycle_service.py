"""M4 Talent Assessment Cycle and frozen population authority."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models


class TalentAssessmentCycleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _clean(value, field, *, required=False, maximum=180):
    cleaned = " ".join(str(value or "").split())
    if required and not cleaned:
        raise TalentAssessmentCycleError("invalid_input", f"{field} is required.")
    if len(cleaned) > maximum:
        raise TalentAssessmentCycleError("invalid_input", f"{field} is too long.")
    return cleaned or None


def cycle_payload(row, *, include_integrity=True):
    result = {
        "id": row.id,
        "school_group_id": row.school_group_id,
        "program_id": row.program_id,
        "academic_year_id": row.academic_year_id,
        "framework_version_id": row.framework_version_id,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "revision": row.revision,
        "population_effective_at": row.population_effective_at.isoformat() if row.population_effective_at else None,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
    }
    if include_integrity:
        result.update({"population_count": row.population_count, "population_fingerprint": row.population_fingerprint})
    return result


def population_member_payload(row):
    return {
        "id": row.id,
        "cycle_id": row.cycle_id,
        "student_id": row.student_id,
        "academic_placement_id": row.academic_placement_id,
        "academic_year_id": row.academic_year_id,
        "branch_id": row.branch_id,
        "planning_section_id": row.planning_section_id,
        "grade_level": row.grade_level,
        "section_name": row.section_name,
        "population_effective_at": row.population_effective_at.isoformat(),
        "frozen_at": row.frozen_at.isoformat(),
    }


def _cycle(db, school_group_id, cycle_id, *, lock=False):
    query = db.query(models.TalentAssessmentCycle).filter_by(id=cycle_id, school_group_id=school_group_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _context(db, *, school_group_id, program_id, academic_year_id, framework_version_id):
    program = db.query(models.TalentProgram).filter_by(id=program_id, school_group_id=school_group_id).one_or_none()
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=school_group_id).one_or_none()
    framework = db.query(models.TalentProgramFrameworkVersion).filter_by(
        id=framework_version_id, program_id=program_id, school_group_id=school_group_id
    ).one_or_none()
    if program is None or year is None or framework is None:
        raise TalentAssessmentCycleError("invalid_scope", "Cycle Program, Academic Year, and Framework must belong to the same organization and Program.")
    return program, year, framework


def _annual_configuration(db, cycle):
    return db.query(models.TalentProgramAcademicYearConfiguration).filter_by(
        school_group_id=cycle.school_group_id,
        program_id=cycle.program_id,
        academic_year_id=cycle.academic_year_id,
    ).one_or_none()


def _audit(db, cycle, *, actor, action, before=None, after=None):
    canonical = _json({"action": action, "before": before, "after": after})
    db.add(models.TalentAssessmentAudit(
        school_group_id=cycle.school_group_id,
        cycle_id=cycle.id,
        program_id=cycle.program_id,
        academic_year_id=cycle.academic_year_id,
        framework_version_id=cycle.framework_version_id,
        actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_id=cycle.id,
        action=action,
        before_json=_json(before) if before is not None else None,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def create_cycle(db: Session, *, school_group_id, program_id, academic_year_id, framework_version_id,
                 title, description=None, population_effective_at=None, actor=None):
    _context(db, school_group_id=school_group_id, program_id=program_id,
             academic_year_id=academic_year_id, framework_version_id=framework_version_id)
    row = models.TalentAssessmentCycle(
        school_group_id=school_group_id,
        program_id=program_id,
        academic_year_id=academic_year_id,
        framework_version_id=framework_version_id,
        title=_clean(title, "title", required=True),
        description=_clean(description, "description", maximum=4000),
        population_effective_at=population_effective_at,
        status="draft",
        revision=1,
        created_by_user_id=getattr(actor, "user_id", None),
        updated_by_user_id=getattr(actor, "user_id", None),
    )
    db.add(row)
    db.flush()
    _audit(db, row, actor=actor, action="create", after=cycle_payload(row))
    return row


def list_cycles(db, *, school_group_id, program_id=None, academic_year_id=None):
    query = db.query(models.TalentAssessmentCycle).filter_by(school_group_id=school_group_id)
    if program_id is not None:
        query = query.filter_by(program_id=program_id)
    if academic_year_id is not None:
        query = query.filter_by(academic_year_id=academic_year_id)
    return query.order_by(models.TalentAssessmentCycle.created_at.desc(), models.TalentAssessmentCycle.id.desc()).all()


def get_cycle(db, *, school_group_id, cycle_id):
    row = _cycle(db, school_group_id, cycle_id)
    if row is None:
        raise TalentAssessmentCycleError("not_found", "Talent Assessment Cycle was not found.")
    return row


def update_cycle(db, *, school_group_id, cycle_id, expected_revision, title=None,
                 description=None, population_effective_at="__unchanged__", actor=None):
    row = _cycle(db, school_group_id, cycle_id, lock=True)
    if row is None:
        raise TalentAssessmentCycleError("not_found", "Talent Assessment Cycle was not found.")
    if row.status != "draft":
        raise TalentAssessmentCycleError("immutable_cycle", "Only a Draft Cycle can be edited.")
    if row.revision != int(expected_revision):
        raise TalentAssessmentCycleError("stale_cycle", "Cycle changed since it was read.")
    before = cycle_payload(row)
    if title is not None:
        row.title = _clean(title, "title", required=True)
    if description is not None:
        row.description = _clean(description, "description", maximum=4000)
    if population_effective_at != "__unchanged__":
        row.population_effective_at = population_effective_at
    row.revision += 1
    row.updated_by_user_id = getattr(actor, "user_id", None)
    row.updated_at = datetime.utcnow()
    db.flush()
    _audit(db, row, actor=actor, action="update", before=before, after=cycle_payload(row))
    return row


def derive_eligible_population(db, *, cycle):
    if cycle.population_effective_at is None:
        raise TalentAssessmentCycleError("effective_time_required", "population_effective_at is required for population preview and opening.")
    config = _annual_configuration(db, cycle)
    if config is None or not config.is_enabled:
        raise TalentAssessmentCycleError("annual_configuration_unavailable", "An enabled Program Academic Year configuration is required.")
    eligible_grades = {value for value in config.eligible_grade_levels_csv.split(",") if value}
    placements = db.query(models.StudentAcademicPlacement).join(
        models.Student,
        (models.Student.id == models.StudentAcademicPlacement.student_id)
        & (models.Student.school_group_id == models.StudentAcademicPlacement.school_group_id),
    ).filter(
        models.StudentAcademicPlacement.school_group_id == cycle.school_group_id,
        models.StudentAcademicPlacement.academic_year_id == cycle.academic_year_id,
        models.StudentAcademicPlacement.grade_level.in_(eligible_grades),
        models.StudentAcademicPlacement.effective_from <= cycle.population_effective_at,
        or_(models.StudentAcademicPlacement.effective_to.is_(None), models.StudentAcademicPlacement.effective_to > cycle.population_effective_at),
        # Eligibility is derived at the historical population_effective_at instant.
        # Student.status is only current mutable state with no effective-dated
        # history (see models.py Student / student_academic_service.py), so it
        # must never gate a historical derivation: a Student later deactivated
        # (or reactivated) today must not silently alter an already-defined
        # historical population. The join above still enforces stable tenant/
        # identity scope alignment between Student and Placement.
    ).order_by(models.StudentAcademicPlacement.student_id, models.StudentAcademicPlacement.id).all()
    return [{
        "student_id": row.student_id,
        "academic_placement_id": row.id,
        "academic_year_id": row.academic_year_id,
        "branch_id": row.branch_id,
        "planning_section_id": row.planning_section_id,
        "grade_level": row.grade_level,
        "section_name": row.section_name,
        "population_effective_at": cycle.population_effective_at,
    } for row in placements]


def preview_population(db, *, school_group_id, cycle_id):
    cycle = get_cycle(db, school_group_id=school_group_id, cycle_id=cycle_id)
    if cycle.status != "draft":
        raise TalentAssessmentCycleError("preview_unavailable", "Dynamic population preview is available only for a Draft Cycle.")
    _context(db, school_group_id=cycle.school_group_id, program_id=cycle.program_id,
             academic_year_id=cycle.academic_year_id, framework_version_id=cycle.framework_version_id)
    return cycle, derive_eligible_population(db, cycle=cycle)


def population_fingerprint(cycle, members):
    tuples = sorted([
        [int(row["student_id"]), int(row["academic_placement_id"]), int(row["academic_year_id"]),
         int(row["branch_id"]), row["grade_level"], row["section_name"]]
        for row in members
    ])
    payload = {
        "cycle_id": cycle.id,
        "school_group_id": cycle.school_group_id,
        "program_id": cycle.program_id,
        "academic_year_id": cycle.academic_year_id,
        "framework_version_id": cycle.framework_version_id,
        "population_effective_at": cycle.population_effective_at.isoformat(),
        "members": tuples,
    }
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def open_cycle(db, *, school_group_id, cycle_id, expected_revision,
               organization_authorized, actor=None):
    if not organization_authorized:
        raise TalentAssessmentCycleError("organization_authority_required", "Organization authority is required to Open a Cycle.")
    cycle_ref = _cycle(db, school_group_id, cycle_id)
    if cycle_ref is None:
        raise TalentAssessmentCycleError("not_found", "Talent Assessment Cycle was not found.")
    linked_period_id = cycle_ref.planned_evaluation_period_id
    if linked_period_id is not None:
        from talent_evaluation_plan_service import TalentEvaluationPlanError, validate_linked_cycle_open
        try:
            validate_linked_cycle_open(db, cycle=cycle_ref)
        except TalentEvaluationPlanError as exc:
            raise TalentAssessmentCycleError(exc.code, exc.message) from exc
    cycle = _cycle(db, school_group_id, cycle_id, lock=True)
    if cycle is None:
        raise TalentAssessmentCycleError("not_found", "Talent Assessment Cycle was not found.")
    if cycle.status != "draft":
        raise TalentAssessmentCycleError("invalid_lifecycle", "Only a Draft Cycle can be opened.")
    if cycle.revision != int(expected_revision):
        raise TalentAssessmentCycleError("stale_cycle", "Cycle changed since it was read.")
    if cycle.planned_evaluation_period_id != linked_period_id:
        raise TalentAssessmentCycleError("linked_period_context_invalid", "Linked planning context changed while opening the Cycle.")
    program, _, framework = _context(
        db, school_group_id=cycle.school_group_id, program_id=cycle.program_id,
        academic_year_id=cycle.academic_year_id, framework_version_id=cycle.framework_version_id,
    )
    if program.status != "active" or framework.status != "active":
        raise TalentAssessmentCycleError("unusable_framework", "Opening requires an Active Program and exact Active Framework Version.")
    members = derive_eligible_population(db, cycle=cycle)
    if db.query(models.TalentAssessmentCyclePopulationMember).filter_by(cycle_id=cycle.id).first():
        raise TalentAssessmentCycleError("population_conflict", "Draft Cycle already contains frozen population rows.")
    frozen_at = datetime.utcnow()
    for member in members:
        db.add(models.TalentAssessmentCyclePopulationMember(
            school_group_id=cycle.school_group_id,
            cycle_id=cycle.id,
            program_id=cycle.program_id,
            framework_version_id=cycle.framework_version_id,
            frozen_at=frozen_at,
            **member,
        ))
    fingerprint = population_fingerprint(cycle, members)
    before = cycle_payload(cycle)
    cycle.population_count = len(members)
    cycle.population_fingerprint = fingerprint
    cycle.status = "open"
    cycle.opened_at = frozen_at
    cycle.opened_by_user_id = getattr(actor, "user_id", None)
    cycle.updated_by_user_id = getattr(actor, "user_id", None)
    cycle.updated_at = frozen_at
    cycle.revision += 1
    db.flush()
    after = cycle_payload(cycle)
    after["population_provenance"] = {
        "effective_at": cycle.population_effective_at.isoformat(),
        "count": cycle.population_count,
        "fingerprint": cycle.population_fingerprint,
    }
    _audit(db, cycle, actor=actor, action="open", before=before, after=after)
    return cycle


def close_cycle(db, *, school_group_id, cycle_id, expected_revision,
                organization_authorized, actor=None):
    if not organization_authorized:
        raise TalentAssessmentCycleError("organization_authority_required", "Organization authority is required to Close a Cycle.")
    cycle = _cycle(db, school_group_id, cycle_id, lock=True)
    if cycle is None:
        raise TalentAssessmentCycleError("not_found", "Talent Assessment Cycle was not found.")
    if cycle.status != "open":
        raise TalentAssessmentCycleError("invalid_lifecycle", "Only an Open Cycle can be closed.")
    if cycle.revision != int(expected_revision):
        raise TalentAssessmentCycleError("stale_cycle", "Cycle changed since it was read.")
    before = cycle_payload(cycle)
    cycle.status = "closed"
    cycle.closed_at = datetime.utcnow()
    cycle.closed_by_user_id = getattr(actor, "user_id", None)
    cycle.updated_by_user_id = getattr(actor, "user_id", None)
    cycle.updated_at = cycle.closed_at
    cycle.revision += 1
    db.flush()
    _audit(db, cycle, actor=actor, action="close", before=before, after=cycle_payload(cycle))
    return cycle


def frozen_population(db, *, school_group_id, cycle_id):
    cycle = get_cycle(db, school_group_id=school_group_id, cycle_id=cycle_id)
    if cycle.status == "draft":
        raise TalentAssessmentCycleError("population_not_frozen", "Draft Cycle does not have an authoritative frozen population.")
    rows = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
        school_group_id=school_group_id, cycle_id=cycle.id
    ).order_by(models.TalentAssessmentCyclePopulationMember.student_id).all()
    return cycle, rows
