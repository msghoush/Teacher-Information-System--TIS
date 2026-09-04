"""M6 Official Identification decision authority (Decisions 3-7, 17).

Records exactly one append-only, durable human decision
(`identified`/`not_identified`, Decision 3) per qualifying `TalentReviewCandidate`.
Recording requires the candidate's review workflow status to already be
`reviewed` (Decision 5 - the mandatory review gate: a `pending_review`
candidate cannot be identified). Authorization (permission + organization/
global access scope) is checked by the caller/router exactly like M4's
`.govern` pattern (`organization_authorized` boolean passed in) - Branch-scoped
actors may never record a decision even if they somehow hold the permission
(Decision 6).

`not_identified` is exactly as durable as `identified` (Decision 4) - neither
is ever mutated, revoked, or superseded, and no second decision for the same
Review Candidate is ever accepted (`uq_talent_official_identifications_candidate`,
enforced both by this service and by the unique constraint itself). Decision
17: revocation, supersession, a second decision, and re-identification are
explicitly NOT implemented anywhere in this module.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

import models


class TalentOfficialIdentificationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _clean(value, field, *, maximum=2000):
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if len(cleaned) > maximum:
        raise TalentOfficialIdentificationError("invalid_input", f"{field} is too long.")
    return cleaned or None


def identification_payload(row):
    return {
        "id": row.id, "school_group_id": row.school_group_id, "cycle_id": row.cycle_id,
        "cycle_population_member_id": row.cycle_population_member_id, "student_id": row.student_id,
        "program_id": row.program_id, "academic_year_id": row.academic_year_id,
        "framework_version_id": row.framework_version_id, "assessment_id": row.assessment_id,
        "review_candidate_id": row.review_candidate_id, "decision": row.decision,
        "rationale": row.rationale, "decided_by_user_id": row.decided_by_user_id,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _audit(db, row, *, actor, action, after=None):
    canonical = _json({"action": action, "after": after})
    db.add(models.TalentAssessmentAudit(
        school_group_id=row.school_group_id, cycle_id=row.cycle_id,
        program_id=row.program_id, academic_year_id=row.academic_year_id,
        framework_version_id=row.framework_version_id, assessment_id=row.assessment_id,
        cycle_population_member_id=row.cycle_population_member_id,
        student_id=row.student_id, actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type="official_identification", resource_id=row.id, action=action,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def record_decision(db: Session, *, school_group_id, review_candidate_id, decision,
                     rationale=None, organization_authorized, actor=None):
    if not organization_authorized:
        raise TalentOfficialIdentificationError(
            "organization_authority_required",
            "Organization or global access scope is required to record an Official Identification decision.",
        )
    if decision not in ("identified", "not_identified"):
        raise TalentOfficialIdentificationError("invalid_decision", "Decision must be 'identified' or 'not_identified'.")

    candidate = db.query(models.TalentReviewCandidate).filter_by(
        id=review_candidate_id, school_group_id=school_group_id,
    ).with_for_update().one_or_none()
    if candidate is None:
        raise TalentOfficialIdentificationError("not_found", "Review Candidate was not found.")
    if candidate.status != "reviewed":
        raise TalentOfficialIdentificationError(
            "candidate_not_reviewed",
            "Official Identification requires the Review Candidate to be Reviewed first.",
        )
    existing = db.query(models.TalentOfficialIdentification).filter_by(
        review_candidate_id=candidate.id, school_group_id=school_group_id,
    ).one_or_none()
    if existing is not None:
        raise TalentOfficialIdentificationError(
            "already_decided",
            "An Official Identification decision has already been recorded for this Review Candidate.",
        )

    row = models.TalentOfficialIdentification(
        school_group_id=school_group_id, cycle_id=candidate.cycle_id,
        cycle_population_member_id=candidate.cycle_population_member_id, student_id=candidate.student_id,
        program_id=candidate.program_id, academic_year_id=candidate.academic_year_id,
        framework_version_id=candidate.framework_version_id, assessment_id=candidate.assessment_id,
        review_candidate_id=candidate.id, decision=decision,
        rationale=_clean(rationale, "rationale"),
        decided_by_user_id=getattr(actor, "user_id", None), decided_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    _audit(db, row, actor=actor, action="record", after=identification_payload(row))
    return row


def get_identification(db, *, school_group_id, identification_id):
    row = db.query(models.TalentOfficialIdentification).filter_by(
        id=identification_id, school_group_id=school_group_id,
    ).one_or_none()
    if row is None:
        raise TalentOfficialIdentificationError("not_found", "Official Identification was not found.")
    return row


def get_identification_for_candidate(db, *, school_group_id, review_candidate_id):
    return db.query(models.TalentOfficialIdentification).filter_by(
        school_group_id=school_group_id, review_candidate_id=review_candidate_id,
    ).one_or_none()


def list_identifications(db, *, school_group_id, cycle_id=None):
    query = db.query(models.TalentOfficialIdentification).filter_by(school_group_id=school_group_id)
    if cycle_id is not None:
        query = query.filter_by(cycle_id=cycle_id)
    return query.order_by(models.TalentOfficialIdentification.id).all()
