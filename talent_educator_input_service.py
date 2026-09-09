"""M6 bounded qualitative Educator Input (Decisions 8-13).

Explicitly NOT a generic note, private diary, assessment score, Official
Identification, Review Candidate state, AI output, or messaging/chat.

Required binding: SchoolGroup, Student, Program, AcademicYear, `observed_at`,
and historical Academic Placement/Branch context. If a frozen Cycle context
(Cycle Population Member, directly or derived from a supplied Assessment/
Review Candidate) is supplied, that frozen member's Branch/Grade/Section is
used - never current Placement. Otherwise the Student's canonical
`StudentAcademicPlacement` effective AT `observed_at` within the specified
AcademicYear is resolved (reusing M4 `derive_eligible_population`'s exact
half-open `[effective_from, effective_to)` interval logic) and snapshotted; no
valid historical Placement at that instant is a clean rejection, never a
silent fallback to current Placement.

Append-only with amendment/supersession lineage via
`supersedes_educator_input_id` - the original row is never edited in place;
`amend_input` creates a new row. Cycle prevention mirrors M3's
`_validate_supersedes` walk exactly.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models

MAX_CONTENT_LENGTH = 2000
CATEGORIES = ("observation", "context", "supporting_evidence")


class TalentEducatorInputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _clean_content(value):
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        raise TalentEducatorInputError("invalid_input", "content is required.")
    if len(cleaned) > MAX_CONTENT_LENGTH:
        raise TalentEducatorInputError("invalid_input", f"content must be at most {MAX_CONTENT_LENGTH} characters.")
    return cleaned


def _validate_category(category):
    if category not in CATEGORIES:
        raise TalentEducatorInputError("invalid_category", "category must be one of: " + ", ".join(CATEGORIES))
    return category


def input_payload(row):
    """Full payload for an authorized direct read - includes the body text."""
    return {
        "id": row.id, "school_group_id": row.school_group_id, "student_id": row.student_id,
        "program_id": row.program_id, "academic_year_id": row.academic_year_id,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "academic_placement_id": row.academic_placement_id, "branch_id": row.branch_id,
        "planning_section_id": row.planning_section_id, "grade_level": row.grade_level,
        "section_name": row.section_name, "cycle_id": row.cycle_id,
        "cycle_population_member_id": row.cycle_population_member_id, "assessment_id": row.assessment_id,
        "review_candidate_id": row.review_candidate_id, "category": row.category, "content": row.content,
        "supersedes_educator_input_id": row.supersedes_educator_input_id,
        "author_user_id": row.author_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _audit_payload(row):
    """Decision 13: structural audit shape WITHOUT the free-text `content` body -
    id, category, author, Student/context ids, supersession relationship, and
    timestamps only, mirroring M5's evidence-stripped `_audit_result`.
    """
    payload = input_payload(row)
    payload.pop("content", None)
    return payload


def _audit(db, row, *, actor, action, before=None, after=None):
    canonical = _json({"action": action, "before": before, "after": after})
    db.add(models.TalentAssessmentAudit(
        school_group_id=row.school_group_id, cycle_id=row.cycle_id,
        program_id=row.program_id, academic_year_id=row.academic_year_id,
        framework_version_id=None, assessment_id=row.assessment_id,
        cycle_population_member_id=row.cycle_population_member_id,
        student_id=row.student_id, actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type="educator_input", resource_id=row.id, action=action,
        before_json=_json(before) if before is not None else None,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def _resolve_optional_context(db, *, school_group_id, student_id, program_id, academic_year_id,
                               cycle_id, cycle_population_member_id, assessment_id, review_candidate_id):
    """Cross-checks whichever optional Cycle/Assessment/Candidate context is
    supplied for exact Student/Program/AcademicYear alignment (Decision 8);
    never trusts the caller. Returns the resolved
    ``(cycle_id, cycle_population_member_id, assessment_id, review_candidate_id, member)``
    tuple, where ``member`` is the frozen Cycle Population Member row (or
    ``None`` if no frozen Cycle context was supplied at all).
    """
    if review_candidate_id is not None:
        candidate = db.query(models.TalentReviewCandidate).filter_by(
            id=review_candidate_id, school_group_id=school_group_id,
        ).one_or_none()
        if candidate is None:
            raise TalentEducatorInputError("invalid_context", "Review Candidate must belong to this SchoolGroup.")
        if assessment_id is not None and assessment_id != candidate.assessment_id:
            raise TalentEducatorInputError("context_mismatch", "Assessment does not match the supplied Review Candidate.")
        if cycle_population_member_id is not None and cycle_population_member_id != candidate.cycle_population_member_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle Population Member does not match the supplied Review Candidate.")
        if cycle_id is not None and cycle_id != candidate.cycle_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle does not match the supplied Review Candidate.")
        assessment_id = candidate.assessment_id
        cycle_population_member_id = candidate.cycle_population_member_id
        cycle_id = candidate.cycle_id
        if candidate.student_id != student_id or candidate.program_id != program_id or candidate.academic_year_id != academic_year_id:
            raise TalentEducatorInputError("context_mismatch", "Review Candidate Student/Program/AcademicYear must match exactly.")

    if assessment_id is not None:
        assessment = db.query(models.TalentStudentAssessment).filter_by(
            id=assessment_id, school_group_id=school_group_id,
        ).one_or_none()
        if assessment is None:
            raise TalentEducatorInputError("invalid_context", "Assessment must belong to this SchoolGroup.")
        if cycle_population_member_id is not None and cycle_population_member_id != assessment.cycle_population_member_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle Population Member does not match the supplied Assessment.")
        if cycle_id is not None and cycle_id != assessment.cycle_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle does not match the supplied Assessment.")
        cycle_population_member_id = assessment.cycle_population_member_id
        cycle_id = assessment.cycle_id
        if assessment.student_id != student_id or assessment.program_id != program_id or assessment.academic_year_id != academic_year_id:
            raise TalentEducatorInputError("context_mismatch", "Assessment Student/Program/AcademicYear must match exactly.")

    member = None
    if cycle_population_member_id is not None:
        member = db.query(models.TalentAssessmentCyclePopulationMember).filter_by(
            id=cycle_population_member_id, school_group_id=school_group_id,
        ).one_or_none()
        if member is None:
            raise TalentEducatorInputError("invalid_context", "Cycle Population Member must belong to this SchoolGroup.")
        if cycle_id is not None and cycle_id != member.cycle_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle does not match the supplied Cycle Population Member.")
        cycle_id = member.cycle_id
        if member.student_id != student_id or member.program_id != program_id or member.academic_year_id != academic_year_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle Population Member Student/Program/AcademicYear must match exactly.")
    elif cycle_id is not None:
        cycle = db.query(models.TalentAssessmentCycle).filter_by(id=cycle_id, school_group_id=school_group_id).one_or_none()
        if cycle is None:
            raise TalentEducatorInputError("invalid_context", "Cycle must belong to this SchoolGroup.")
        if cycle.program_id != program_id or cycle.academic_year_id != academic_year_id:
            raise TalentEducatorInputError("context_mismatch", "Cycle Program/AcademicYear must match exactly.")

    return cycle_id, cycle_population_member_id, assessment_id, review_candidate_id, member


def _resolve_historical_context(db, *, school_group_id, student_id, academic_year_id, observed_at, member):
    """Frozen Cycle context wins when supplied (Decision 8/15); otherwise
    resolves the canonical `StudentAcademicPlacement` effective AT
    ``observed_at`` within ``academic_year_id`` using the same half-open
    `[effective_from, effective_to)` interval logic as M4's
    `derive_eligible_population`. Rejects cleanly if no valid historical
    Placement exists - never falls back to current Placement.
    """
    if member is not None:
        return {
            "academic_placement_id": member.academic_placement_id, "branch_id": member.branch_id,
            "planning_section_id": member.planning_section_id, "grade_level": member.grade_level,
            "section_name": member.section_name,
        }
    placement = db.query(models.StudentAcademicPlacement).filter(
        models.StudentAcademicPlacement.school_group_id == school_group_id,
        models.StudentAcademicPlacement.student_id == student_id,
        models.StudentAcademicPlacement.academic_year_id == academic_year_id,
        models.StudentAcademicPlacement.effective_from <= observed_at,
        or_(
            models.StudentAcademicPlacement.effective_to.is_(None),
            models.StudentAcademicPlacement.effective_to > observed_at,
        ),
    ).order_by(models.StudentAcademicPlacement.effective_from.desc()).first()
    if placement is None:
        raise TalentEducatorInputError(
            "no_historical_placement",
            "No historical Academic Placement exists for this Student at observed_at within the specified Academic Year.",
        )
    return {
        "academic_placement_id": placement.id, "branch_id": placement.branch_id,
        "planning_section_id": placement.planning_section_id, "grade_level": placement.grade_level,
        "section_name": placement.section_name,
    }


def add_input(db: Session, *, school_group_id, student_id, program_id, academic_year_id, observed_at,
              category, content, cycle_id=None, cycle_population_member_id=None, assessment_id=None,
              review_candidate_id=None, actor=None):
    _validate_category(category)
    content = _clean_content(content)
    student = db.query(models.Student).filter_by(id=student_id, school_group_id=school_group_id).one_or_none()
    if student is None:
        raise TalentEducatorInputError("not_found", "Student was not found.")
    program = db.query(models.TalentProgram).filter_by(id=program_id, school_group_id=school_group_id).one_or_none()
    if program is None:
        raise TalentEducatorInputError("not_found", "Talent Program was not found.")
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=school_group_id).one_or_none()
    if year is None:
        raise TalentEducatorInputError("not_found", "Academic Year was not found.")

    cycle_id, cycle_population_member_id, assessment_id, review_candidate_id, member = _resolve_optional_context(
        db, school_group_id=school_group_id, student_id=student_id, program_id=program_id,
        academic_year_id=academic_year_id, cycle_id=cycle_id, cycle_population_member_id=cycle_population_member_id,
        assessment_id=assessment_id, review_candidate_id=review_candidate_id,
    )
    context = _resolve_historical_context(
        db, school_group_id=school_group_id, student_id=student_id, academic_year_id=academic_year_id,
        observed_at=observed_at, member=member,
    )

    row = models.TalentEducatorInput(
        school_group_id=school_group_id, student_id=student_id, program_id=program_id,
        academic_year_id=academic_year_id, observed_at=observed_at,
        academic_placement_id=context["academic_placement_id"], branch_id=context["branch_id"],
        planning_section_id=context["planning_section_id"], grade_level=context["grade_level"],
        section_name=context["section_name"], cycle_id=cycle_id,
        cycle_population_member_id=cycle_population_member_id, assessment_id=assessment_id,
        review_candidate_id=review_candidate_id, category=category, content=content,
        author_user_id=getattr(actor, "user_id", None),
    )
    db.add(row)
    db.flush()
    _audit(db, row, actor=actor, action="add", after=_audit_payload(row))
    return row


def _validate_supersession_chain(db, *, school_group_id, supersedes_id):
    """Mirrors M3's `_validate_supersedes` Framework Version cycle-prevention walk."""
    current = supersedes_id
    seen = set()
    while current is not None:
        if current in seen:
            raise TalentEducatorInputError("invalid_supersession", "Educator Input supersession cannot contain a cycle.")
        seen.add(current)
        row = db.query(models.TalentEducatorInput).filter_by(id=current, school_group_id=school_group_id).one_or_none()
        if row is None:
            raise TalentEducatorInputError("invalid_supersession", "Superseded Educator Input must belong to the same tenant.")
        current = row.supersedes_educator_input_id


def amend_input(db: Session, *, school_group_id, student_id, program_id, supersedes_educator_input_id,
                 category, content, observed_at=None, cycle_id=None, cycle_population_member_id=None,
                 assessment_id=None, review_candidate_id=None, actor=None):
    """Append-only amendment: creates a NEW row referencing the row it
    supersedes; the original row is never edited in place or deleted.
    ``student_id``/``program_id`` are required caller inputs (not silently
    inherited) so cross-Student/cross-Program/cross-tenant supersession is
    explicitly validated and rejected, not merely structurally impossible.
    """
    original = db.query(models.TalentEducatorInput).filter_by(
        id=supersedes_educator_input_id, school_group_id=school_group_id,
    ).one_or_none()
    if original is None:
        raise TalentEducatorInputError("not_found", "Educator Input to amend was not found.")
    if original.student_id != student_id:
        raise TalentEducatorInputError("cross_student_supersession", "Amendment Student must match the superseded Educator Input's Student.")
    if original.program_id != program_id:
        raise TalentEducatorInputError("cross_program_supersession", "Amendment Program must match the superseded Educator Input's Program.")
    if db.query(models.TalentEducatorInput).filter_by(
        supersedes_educator_input_id=original.id, school_group_id=school_group_id,
    ).first():
        raise TalentEducatorInputError("already_superseded", "This Educator Input has already been superseded.")
    _validate_supersession_chain(db, school_group_id=school_group_id, supersedes_id=original.id)

    _validate_category(category)
    content = _clean_content(content)
    observed_at = observed_at if observed_at is not None else original.observed_at
    cycle_id = cycle_id if cycle_id is not None else original.cycle_id
    cycle_population_member_id = cycle_population_member_id if cycle_population_member_id is not None else original.cycle_population_member_id
    assessment_id = assessment_id if assessment_id is not None else original.assessment_id
    review_candidate_id = review_candidate_id if review_candidate_id is not None else original.review_candidate_id

    cycle_id, cycle_population_member_id, assessment_id, review_candidate_id, member = _resolve_optional_context(
        db, school_group_id=school_group_id, student_id=original.student_id, program_id=original.program_id,
        academic_year_id=original.academic_year_id, cycle_id=cycle_id, cycle_population_member_id=cycle_population_member_id,
        assessment_id=assessment_id, review_candidate_id=review_candidate_id,
    )
    context = _resolve_historical_context(
        db, school_group_id=school_group_id, student_id=original.student_id, academic_year_id=original.academic_year_id,
        observed_at=observed_at, member=member,
    )

    row = models.TalentEducatorInput(
        school_group_id=school_group_id, student_id=original.student_id, program_id=original.program_id,
        academic_year_id=original.academic_year_id, observed_at=observed_at,
        academic_placement_id=context["academic_placement_id"], branch_id=context["branch_id"],
        planning_section_id=context["planning_section_id"], grade_level=context["grade_level"],
        section_name=context["section_name"], cycle_id=cycle_id,
        cycle_population_member_id=cycle_population_member_id, assessment_id=assessment_id,
        review_candidate_id=review_candidate_id, category=category, content=content,
        supersedes_educator_input_id=original.id, author_user_id=getattr(actor, "user_id", None),
    )
    db.add(row)
    db.flush()
    _audit(db, row, actor=actor, action="amend", before=_audit_payload(original), after=_audit_payload(row))
    return row, original


def get_input(db, *, school_group_id, input_id):
    row = db.query(models.TalentEducatorInput).filter_by(id=input_id, school_group_id=school_group_id).one_or_none()
    if row is None:
        raise TalentEducatorInputError("not_found", "Educator Input was not found.")
    return row


def list_inputs(db, *, school_group_id, student_id=None, program_id=None, current_only=True):
    query = db.query(models.TalentEducatorInput).filter_by(school_group_id=school_group_id)
    if student_id is not None:
        query = query.filter_by(student_id=student_id)
    if program_id is not None:
        query = query.filter_by(program_id=program_id)
    if current_only:
        superseded_ids = db.query(models.TalentEducatorInput.supersedes_educator_input_id).filter(
            models.TalentEducatorInput.school_group_id == school_group_id,
            models.TalentEducatorInput.supersedes_educator_input_id.isnot(None),
        )
        query = query.filter(~models.TalentEducatorInput.id.in_(superseded_ids))
    return query.order_by(models.TalentEducatorInput.id).all()


def input_history(db, *, school_group_id, input_id):
    """Returns the full supersession chain (oldest -> newest) containing ``input_id``."""
    row = get_input(db, school_group_id=school_group_id, input_id=input_id)
    root = row
    seen = {row.id}
    while root.supersedes_educator_input_id is not None:
        parent = db.query(models.TalentEducatorInput).filter_by(
            id=root.supersedes_educator_input_id, school_group_id=school_group_id,
        ).one_or_none()
        if parent is None or parent.id in seen:
            break
        root = parent
        seen.add(parent.id)
    chain = [root]
    current = root
    seen2 = {root.id}
    while True:
        following = db.query(models.TalentEducatorInput).filter_by(
            supersedes_educator_input_id=current.id, school_group_id=school_group_id,
        ).one_or_none()
        if following is None or following.id in seen2:
            break
        chain.append(following)
        seen2.add(following.id)
        current = following
    return chain
