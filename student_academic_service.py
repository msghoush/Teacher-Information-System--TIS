"""Canonical Student and effective-dated academic placement application service."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

import auth
import models
from academic_grade import normalize_grade_level


class StudentAcademicError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# Learning Style V1 (ADR 0031, amended by M14): exactly eight approved
# values, no others. Extended from the original four (Visual, Auditory,
# Read/Write, Kinesthetic) to eight (Verbal, Non-verbal, Quantitative,
# Spatial added) by the M14 owner correction - those four were previously,
# mistakenly, modeled as an independent per-Student percentage profile
# (ADR 0042); that model is corrected here to be four more categorical
# Learning Style values on this single-select field, exactly like the
# original four. Student-domain learner-profile context only - never a
# Talent score and never read by any Talent scoring/eligibility/Official
# Identification computation. Optional/nullable; an empty value clears it
# back to "not assigned", mirroring how other optional Student fields (e.g.
# gender) are already cleared by ``_clean`` below.
LEARNING_STYLES = (
    "Visual", "Auditory", "Read/Write", "Kinesthetic",
    "Verbal", "Non-verbal", "Quantitative", "Spatial",
)


# Learning Style four-dimension percentage profile (ADR 0042, amends ADR
# 0031). OPERATIONALLY DEPRECATED as of M14 (owner correction): "percentage"
# was always intended to mean population/aggregate distribution, never a
# per-Student dimension score, so this independent four-percentage profile is
# a corrected/superseded product model. The product no longer writes to,
# exposes, or reads these columns anywhere (see ``routers/students.py`` and
# ``routers/students_ui.py``, which no longer accept these fields as
# create/update input). These validators and columns are kept only so that
# any already-stored value is never silently rewritten or cleared by an
# unrelated Student edit; physical column removal is separately gated on a
# later, explicit data-occupancy verification.
LEARNING_STYLE_PERCENTAGE_FIELDS = (
    "learning_style_verbal_percentage",
    "learning_style_non_verbal_percentage",
    "learning_style_quantitative_percentage",
    "learning_style_spatial_percentage",
)


# TIS Student Number (ADR 0043/M2): the one globally unique, system-managed
# StudentExternalIdentifier namespace. Business/API input is exactly ten ASCII
# digits (leading zeros preserved as a string, never parsed as an integer);
# the service alone controls the canonical "STD" + 10-digit stored format.
# This namespace is blocked from the generic external-identifier create/
# deactivate paths below - it may only be created/replaced through the
# dedicated functions in this section.
STUDENT_NUMBER_NAMESPACE = "tis_student_number"
STUDENT_NUMBER_PREFIX = "STD"
MANAGED_EXTERNAL_IDENTIFIER_NAMESPACES = frozenset({STUDENT_NUMBER_NAMESPACE})
_STUDENT_NUMBER_DIGITS_RE = re.compile(r"^[0-9]{10}$")


def validate_student_number_digits(value):
    """Validate the business-facing Student number input: exactly 10 ASCII digits.

    Leading zeros are preserved because this never parses the value as an
    integer. Rejects short/long/non-digit/whitespace/None/empty input; never
    silently normalizes an arbitrary mixed string.
    """
    if not isinstance(value, str) or not _STUDENT_NUMBER_DIGITS_RE.fullmatch(value):
        raise StudentAcademicError(
            "invalid_student_number",
            "Student number must be exactly 10 digits (0-9 only, leading zeros preserved).",
        )
    return value


def canonical_student_number(value):
    """Server-controlled canonicalization: STD + the validated 10-digit value.

    The client never supplies or controls the ``STD`` prefix.
    """
    return f"{STUDENT_NUMBER_PREFIX}{validate_student_number_digits(value)}"


def _clean_learning_style(value):
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        return None
    if cleaned not in LEARNING_STYLES:
        raise StudentAcademicError(
            "invalid_learning_style",
            "Learning Style must be one of " + ", ".join(LEARNING_STYLES) + ".",
        )
    return cleaned


def _clean_learning_style_percentage(value, field: str):
    """Validate one Learning Style four-dimension percentage (ADR 0042/M3).

    Each dimension is independent: ``None`` is valid ("not assessed"), and an
    integer 0-100 inclusive is valid, including the boundary values 0 and 100
    (0 is a real assessed value, never conflated with "unset"). There is no
    sum-to-100 rule and no derivation from any other field. ``bool`` is
    explicitly rejected even though Python's ``bool`` is an ``int`` subclass;
    a float/decimal or any other non-``int`` type (including a numeric
    string such as ``"75"``) is rejected rather than silently coerced, since
    this dict-based JSON request body performs no schema-level type
    coercion anywhere else in this module.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise StudentAcademicError(
            "invalid_learning_style_percentage",
            f"{field} must be an integer between 0 and 100, or null.",
        )
    if value < 0 or value > 100:
        raise StudentAcademicError(
            "invalid_learning_style_percentage",
            f"{field} must be between 0 and 100 inclusive.",
        )
    return value


def _clean(value, field: str, *, required: bool = False, maximum: int = 100):
    cleaned = " ".join(str(value or "").split())
    if required and not cleaned:
        raise StudentAcademicError("invalid_student", f"{field} is required.")
    if len(cleaned) > maximum:
        raise StudentAcademicError("invalid_student", f"{field} is too long.")
    return cleaned or None


def _student_payload(student):
    return {
        "id": student.id, "school_group_id": student.school_group_id,
        "first_name": student.first_name, "father_name": student.father_name,
        "last_name": student.last_name, "gender": student.gender, "status": student.status,
        "learning_style": student.learning_style,
        **{field: getattr(student, field) for field in LEARNING_STYLE_PERCENTAGE_FIELDS},
    }


def placement_payload(row):
    return {
        "id": row.id, "school_group_id": row.school_group_id, "student_id": row.student_id,
        "academic_year_id": row.academic_year_id, "branch_id": row.branch_id,
        "planning_section_id": row.planning_section_id, "grade_level": row.grade_level,
        "section_name": row.section_name, "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "status": row.status, "reason": row.reason,
    }


def _audit(db, *, school_group_id, student_id, actor, resource_type, resource_id,
           action, before=None, after=None, correlation_id=None):
    canonical = json.dumps(after or before or {}, sort_keys=True, separators=(",", ":"))
    db.add(models.StudentAudit(
        school_group_id=school_group_id, student_id=student_id,
        actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type=resource_type, resource_id=resource_id, action=action,
        before_json=json.dumps(before, sort_keys=True) if before is not None else None,
        after_json=json.dumps(after, sort_keys=True) if after is not None else None,
        correlation_id=correlation_id or hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def get_student(db: Session, school_group_id: int, student_id: int):
    return db.query(models.Student).filter(
        models.Student.id == student_id,
        models.Student.school_group_id == school_group_id,
    ).one_or_none()


def create_student(db: Session, *, school_group_id: int, first_name, last_name,
                   father_name=None, gender=None, learning_style=None,
                   learning_style_verbal_percentage=None, learning_style_non_verbal_percentage=None,
                   learning_style_quantitative_percentage=None, learning_style_spatial_percentage=None,
                   actor=None):
    if db.get(models.SchoolGroup, school_group_id) is None:
        raise StudentAcademicError("invalid_scope", "The selected organization is unavailable.")
    student = models.Student(
        school_group_id=school_group_id,
        first_name=_clean(first_name, "first_name", required=True),
        father_name=_clean(father_name, "father_name"),
        last_name=_clean(last_name, "last_name", required=True),
        gender=_clean(gender, "gender", maximum=24), status="active",
        learning_style=_clean_learning_style(learning_style),
        learning_style_verbal_percentage=_clean_learning_style_percentage(
            learning_style_verbal_percentage, "learning_style_verbal_percentage"),
        learning_style_non_verbal_percentage=_clean_learning_style_percentage(
            learning_style_non_verbal_percentage, "learning_style_non_verbal_percentage"),
        learning_style_quantitative_percentage=_clean_learning_style_percentage(
            learning_style_quantitative_percentage, "learning_style_quantitative_percentage"),
        learning_style_spatial_percentage=_clean_learning_style_percentage(
            learning_style_spatial_percentage, "learning_style_spatial_percentage"),
        created_by_user_id=getattr(actor, "user_id", None),
        updated_by_user_id=getattr(actor, "user_id", None),
    )
    db.add(student); db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student.id, actor=actor,
           resource_type="student", resource_id=student.id, action="create", after=_student_payload(student))
    return student


def create_student_with_number(db: Session, *, school_group_id: int, student_number, first_name, last_name,
                               father_name=None, gender=None, learning_style=None,
                               learning_style_verbal_percentage=None, learning_style_non_verbal_percentage=None,
                               learning_style_quantitative_percentage=None, learning_style_spatial_percentage=None,
                               actor=None):
    """Create a new Student together with its mandatory managed Student number, atomically.

    ADR 0043/M2: new Students require a Student number (existing legacy
    Students are unaffected and may continue without one - see
    ``create_student`` above, still used unchanged by legacy/UI callers).
    ``student_number`` is exactly 10 business-facing digits; the canonical
    ``STD``-prefixed value is stored via a normal managed
    ``StudentExternalIdentifier`` row. Both writes happen in the same
    uncommitted database transaction: if the identifier insert fails (format
    error surfaces before either write; a uniqueness conflict/race surfaces
    as ``IntegrityError`` from the flush below), the caller must roll back
    the whole transaction so no orphan/partial Student row is left behind -
    this function never commits.

    ``learning_style_*_percentage`` (ADR 0042/M3) are optional and may all be
    omitted/``None``; an invalid dimension raises before either write, so no
    partial Student row is created.
    """
    if student_number is None or str(student_number).strip() == "":
        raise StudentAcademicError("invalid_student_number", "Student number is required.")
    canonical_value = canonical_student_number(student_number)
    student = create_student(
        db, school_group_id=school_group_id, first_name=first_name, last_name=last_name,
        father_name=father_name, gender=gender, learning_style=learning_style,
        learning_style_verbal_percentage=learning_style_verbal_percentage,
        learning_style_non_verbal_percentage=learning_style_non_verbal_percentage,
        learning_style_quantitative_percentage=learning_style_quantitative_percentage,
        learning_style_spatial_percentage=learning_style_spatial_percentage,
        actor=actor,
    )
    _insert_active_student_number(
        db, school_group_id=school_group_id, student_id=student.id,
        canonical_value=canonical_value, actor=actor, action="create",
    )
    return student


def update_student(db: Session, *, school_group_id: int, student_id: int, actor=None, **changes):
    student = get_student(db, school_group_id, student_id)
    if student is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    before = _student_payload(student)
    for field in ("first_name", "father_name", "last_name", "gender"):
        if field in changes:
            setattr(student, field, _clean(changes[field], field, required=field in {"first_name", "last_name"}, maximum=24 if field == "gender" else 100))
    if "learning_style" in changes:
        student.learning_style = _clean_learning_style(changes["learning_style"])
    for field in LEARNING_STYLE_PERCENTAGE_FIELDS:
        if field in changes:
            setattr(student, field, _clean_learning_style_percentage(changes[field], field))
    if "status" in changes:
        status = str(changes["status"] or "").strip().lower()
        if status not in {"active", "inactive"}:
            raise StudentAcademicError("invalid_status", "Student status must be active or inactive.")
        student.status = status
    student.updated_by_user_id = getattr(actor, "user_id", None)
    student.updated_at = datetime.utcnow(); db.flush()
    after = _student_payload(student)
    if after != before:
        action = "status_change" if before["status"] != after["status"] else "update"
        _audit(db, school_group_id=school_group_id, student_id=student.id, actor=actor,
               resource_type="student", resource_id=student.id, action=action, before=before, after=after)
    return student


def student_delete_blockers(db: Session, *, school_group_id: int, student_id: int):
    """Return durable-history blockers for permanent Student deletion.

    Student identity deletion is allowed only before Academic Placement or
    Talent history exists. Creation audit rows and optional external identifiers
    are metadata owned by the otherwise-empty Student and are removed with it.
    """
    student = get_student(db, school_group_id, student_id)
    if student is None:
        raise StudentAcademicError("not_found", "Student was not found.")

    checks = (
        ("academic_placement", models.StudentAcademicPlacement, "Academic Placement history exists."),
        ("talent_population", models.TalentAssessmentCyclePopulationMember, "Talent evaluation history exists."),
        ("talent_assessment", models.TalentStudentAssessment, "Talent Assessment history exists."),
        ("talent_review", models.TalentReviewCandidate, "Talent Review history exists."),
        ("official_identification", models.TalentOfficialIdentification, "Official Identification history exists."),
        ("educator_input", models.TalentEducatorInput, "Educator Input history exists."),
    )
    blockers = []
    for code, model, message in checks:
        if db.query(model).filter_by(school_group_id=school_group_id, student_id=student_id).first() is not None:
            blockers.append({"code": code, "message": message})
    return blockers


def _delete_student_unchecked(db: Session, *, school_group_id: int, student_id: int):
    # These records exist even for a just-created Student and carry no separate
    # historical authority once the empty Student identity is being removed.
    db.query(models.StudentExternalIdentifier).filter_by(
        school_group_id=school_group_id, student_id=student_id
    ).delete(synchronize_session=False)
    db.query(models.StudentAudit).filter_by(
        school_group_id=school_group_id, student_id=student_id
    ).delete(synchronize_session=False)
    student = get_student(db, school_group_id, student_id)
    if student is not None:
        db.delete(student)
        db.flush()


# Every table that carries a ``student_id`` (or a foreign key to ``students``), in
# foreign-key-safe child-before-parent order. Batch 1 data-integrity rule: when a
# Student is permanently deleted, everything the Student owns in Student-domain
# and Talent & Potential must be removed in the SAME transaction so nothing
# orphaned can ever feed current analytics. The set is locked against the ORM
# metadata by ``tests/test_student_delete_completeness_batch1.py`` so a future
# Student-owned table cannot be added without being listed here.
STUDENT_OWNED_MODELS = (
    models.TalentOfficialIdentification,
    models.TalentEducatorInput,
    models.TalentReviewCandidate,
    models.TalentAssessmentAudit,
    models.TalentStudentCompetencyResult,
    models.TalentStudentAssessment,
    models.TalentAssessmentCyclePopulationMember,
    models.StudentAcademicPlacement,
    models.StudentExternalIdentifier,
    models.StudentAudit,
)


def force_delete_student_history(db: Session, *, school_group_id: int, student_id: int):
    """Permanently remove one Student and all Student-owned academic/Talent history.

    This is a deliberately separate destructive authority. Callers must enforce
    the dedicated force-delete permission and obtain explicit user confirmation.
    Deletion order follows the existing foreign-key graph so no historical row
    is silently orphaned. Nothing is retained: there is no separate historical
    retention store, and current Talent analytics additionally exclude any row
    whose Student no longer exists (``talent_current_students``).
    """
    if get_student(db, school_group_id, student_id) is None:
        raise StudentAcademicError("not_found", "Student was not found.")

    scoped = {"school_group_id": school_group_id, "student_id": student_id}
    for model in STUDENT_OWNED_MODELS:
        db.query(model).filter_by(**scoped).delete(synchronize_session=False)

    student = get_student(db, school_group_id, student_id)
    if student is not None:
        db.delete(student)
    db.flush()


def delete_student(db: Session, *, school_group_id: int, student_id: int):
    blockers = student_delete_blockers(
        db, school_group_id=school_group_id, student_id=student_id
    )
    if blockers:
        raise StudentAcademicError(
            "student_delete_blocked",
            "Student cannot be permanently deleted because historical records exist: "
            + " ".join(item["message"] for item in blockers),
        )
    _delete_student_unchecked(db, school_group_id=school_group_id, student_id=student_id)


def delete_students(db: Session, *, school_group_id: int, student_ids):
    """Atomically delete an explicitly selected set of otherwise-empty Students."""
    ids = []
    for value in student_ids or ():
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise StudentAcademicError("invalid_student", "Student selection is invalid.")
        if parsed not in ids:
            ids.append(parsed)
    if not ids:
        raise StudentAcademicError("invalid_student", "Select at least one Student to delete.")

    rows = db.query(models.Student).filter(
        models.Student.school_group_id == school_group_id,
        models.Student.id.in_(ids),
    ).all()
    if len(rows) != len(ids):
        raise StudentAcademicError("not_found", "One or more selected Students were not found.")

    blocked = []
    for row in rows:
        blockers = student_delete_blockers(
            db, school_group_id=school_group_id, student_id=row.id
        )
        if blockers:
            blocked.append(
                f"{row.first_name} {row.last_name}: "
                + " ".join(item["message"] for item in blockers)
            )
    if blocked:
        raise StudentAcademicError(
            "student_delete_blocked",
            "No Students were deleted. " + " ".join(blocked),
        )

    for row in rows:
        _delete_student_unchecked(
            db, school_group_id=school_group_id, student_id=row.id
        )
    return len(rows)


def _current_placement_scope_subquery(db: Session, *, school_group_id: int, at: datetime | None = None):
    """Real, backend-computed "current effective placement" scope per Student.

    Reuses the exact half-open ``[effective_from, effective_to)`` eligibility rule
    ``resolve_placement`` already applies, then picks each Student's latest
    ``effective_from`` among eligible rows (SQLite/PostgreSQL-portable GROUP BY,
    no window function) - the same tie-break ``resolve_placement`` uses. This
    backs real Branch/Grade/Section list filters; it is never a fabricated or
    client-only filter.
    """
    at = at or datetime.utcnow()
    P = models.StudentAcademicPlacement
    eligible = db.query(P).filter(
        P.school_group_id == school_group_id,
        P.effective_from <= at,
        or_(P.effective_to.is_(None), P.effective_to > at),
    ).subquery()
    latest = db.query(
        eligible.c.student_id.label("student_id"),
        func.max(eligible.c.effective_from).label("max_from"),
    ).group_by(eligible.c.student_id).subquery()
    current = db.query(
        eligible.c.student_id.label("student_id"),
        eligible.c.branch_id.label("branch_id"),
        eligible.c.grade_level.label("grade_level"),
        eligible.c.section_name.label("section_name"),
    ).join(
        latest,
        and_(eligible.c.student_id == latest.c.student_id, eligible.c.effective_from == latest.c.max_from),
    ).subquery()
    return current


def list_students(db: Session, *, school_group_id: int, search: str = "", status: str | None = None,
                  branch_id: int | None = None, grade_level: str | None = None,
                  section_name: str | None = None, at: datetime | None = None):
    query = db.query(models.Student).filter(models.Student.school_group_id == school_group_id)
    cleaned = str(search or "").strip()
    if cleaned:
        pattern = f"%{cleaned}%"
        query = query.filter(or_(models.Student.first_name.ilike(pattern), models.Student.father_name.ilike(pattern), models.Student.last_name.ilike(pattern)))
    if status:
        query = query.filter(models.Student.status == str(status).strip().lower())
    if branch_id or grade_level or section_name:
        current = _current_placement_scope_subquery(db, school_group_id=school_group_id, at=at)
        query = query.join(current, current.c.student_id == models.Student.id)
        if branch_id:
            query = query.filter(current.c.branch_id == int(branch_id))
        if grade_level:
            query = query.filter(current.c.grade_level == normalize_grade_level(grade_level))
        if section_name:
            query = query.filter(current.c.section_name == str(section_name).strip())
    return query.order_by(models.Student.last_name, models.Student.first_name, models.Student.id).all()


def add_external_identifier(db: Session, *, school_group_id: int, student_id: int,
                            namespace, value, source=None, actor=None):
    if get_student(db, school_group_id, student_id) is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    namespace = _clean(namespace, "namespace", required=True, maximum=80)
    # TIS Student Number (ADR 0043/M2) is system-managed: block the generic
    # create path from touching it so callers cannot bypass the mandatory
    # ten-digit format validation, canonical STD-prefix, or global-uniqueness
    # conflict handling that only create_student_with_number/set_student_number
    # implement. Every other namespace is unaffected.
    if namespace in MANAGED_EXTERNAL_IDENTIFIER_NAMESPACES:
        raise StudentAcademicError(
            "managed_namespace",
            "This identifier namespace is system-managed and cannot be created directly.",
        )
    value = _clean(value, "value", required=True, maximum=180)
    if db.query(models.StudentExternalIdentifier).filter_by(school_group_id=school_group_id, namespace=namespace, value=value).first():
        raise StudentAcademicError("duplicate_identifier", "That identifier already exists in this organization and namespace.")
    row = models.StudentExternalIdentifier(school_group_id=school_group_id, student_id=student_id,
        namespace=namespace, value=value, source=_clean(source, "source", maximum=120), status="active")
    db.add(row); db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="external_identifier", resource_id=row.id, action="add",
           after={"namespace": row.namespace, "value": row.value, "source": row.source, "status": row.status})
    return row


def deactivate_external_identifier(db: Session, *, school_group_id: int, student_id: int,
                                   identifier_id: int, actor=None):
    row = db.query(models.StudentExternalIdentifier).filter_by(
        id=identifier_id, school_group_id=school_group_id, student_id=student_id
    ).one_or_none()
    if row is None:
        raise StudentAcademicError("not_found", "Student identifier was not found.")
    # Same managed-namespace boundary as add_external_identifier above: the
    # canonical Student number's active/inactive lifecycle is owned exclusively
    # by set_student_number, so a caller cannot silently retire a Student's
    # current managed number through the generic identifier path.
    if row.namespace in MANAGED_EXTERNAL_IDENTIFIER_NAMESPACES:
        raise StudentAcademicError(
            "managed_namespace",
            "This identifier namespace is system-managed and cannot be deactivated directly.",
        )
    before = {"namespace": row.namespace, "value": row.value, "source": row.source, "status": row.status}
    row.status = "inactive"; row.updated_at = datetime.utcnow(); db.flush()
    after = {**before, "status": "inactive"}
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="external_identifier", resource_id=row.id, action="deactivate", before=before, after=after)
    return row


# ---------------------------------------------------------------------------
# TIS Student Number managed service (ADR 0043/M2)
# ---------------------------------------------------------------------------

def _insert_active_student_number(db: Session, *, school_group_id: int, student_id: int,
                                  canonical_value: str, actor=None, action: str):
    """Insert one active managed Student-number row and its audit event.

    Deliberately does not catch ``IntegrityError``: the M1 partial unique
    indexes on ``student_external_identifiers`` remain the final concurrency
    authority for both the global-uniqueness and one-active-per-Student
    invariants, and callers (the API routes) are responsible for rolling
    back the transaction and safely classifying the conflict after a race.
    """
    row = models.StudentExternalIdentifier(
        school_group_id=school_group_id, student_id=student_id,
        namespace=STUDENT_NUMBER_NAMESPACE, value=canonical_value,
        source="managed", status="active",
    )
    db.add(row)
    db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="external_identifier", resource_id=row.id, action=action,
           after={"namespace": row.namespace, "value": row.value, "status": row.status})
    return row


def current_student_number(db: Session, *, school_group_id: int, student_id: int):
    """Return the current active canonical ``STD``-prefixed value, or ``None``.

    A legacy Student with no managed identifier row is valid and returns
    ``None`` - this never fabricates or backfills a value.
    """
    row = db.query(models.StudentExternalIdentifier).filter_by(
        school_group_id=school_group_id, student_id=student_id,
        namespace=STUDENT_NUMBER_NAMESPACE, status="active",
    ).one_or_none()
    return row.value if row else None


def set_student_number(db: Session, *, school_group_id: int, student_id: int, student_number, actor=None):
    """Assign a Student number to a legacy Student, or replace its current one.

    Validates and canonicalizes ``student_number`` first (format errors never
    touch the database). If the Student already has an active managed number
    with a different value, that row is marked ``inactive`` (never mutated
    into the new value, preserving history/reservation per ADR 0043) and a
    new active row is inserted for the new canonical value in the same
    uncommitted transaction. ``Student.id`` is never changed. Does not catch
    ``IntegrityError``; the caller rolls back and classifies the conflict.
    """
    student = get_student(db, school_group_id, student_id)
    if student is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    canonical_value = canonical_student_number(student_number)
    existing_active = db.query(models.StudentExternalIdentifier).filter_by(
        school_group_id=school_group_id, student_id=student_id,
        namespace=STUDENT_NUMBER_NAMESPACE, status="active",
    ).one_or_none()
    if existing_active is not None and existing_active.value == canonical_value:
        return existing_active
    if existing_active is not None:
        before = {"namespace": existing_active.namespace, "value": existing_active.value, "status": "active"}
        existing_active.status = "inactive"
        existing_active.updated_at = datetime.utcnow()
        db.flush()
        _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
               resource_type="external_identifier", resource_id=existing_active.id, action="replace_retire",
               before=before, after={**before, "status": "inactive"})
    action = "replace" if existing_active is not None else "assign"
    return _insert_active_student_number(
        db, school_group_id=school_group_id, student_id=student_id,
        canonical_value=canonical_value, actor=actor, action=action,
    )


def find_student_number_holder(db: Session, *, canonical_value: str):
    """Read-only, unauthenticated lookup of who (if anyone) holds a canonical value.

    This must only be called AFTER rolling back a failed insert triggered by
    the M1 global-uniqueness index, and its raw result must never be returned
    to a caller without an explicit authorization decision layered on top
    (see ``routers/students.py``): it deliberately reveals nothing about
    organization/Student identity by itself and does not grant any lookup
    capability beyond a bare ``school_group_id``/``student_id`` pair.
    """
    row = db.query(models.StudentExternalIdentifier).filter_by(
        namespace=STUDENT_NUMBER_NAMESPACE, value=canonical_value,
    ).one_or_none()
    if row is None:
        return None
    return {"school_group_id": row.school_group_id, "student_id": row.student_id}


def describe_student_number_conflict(db: Session, *, requester_school_group_id, actor, canonical_value):
    """Single source of truth for the ADR 0043/M2 privacy-safe Student-number
    conflict disclosure contract.

    Reused by both the direct create/replace API 409 response
    (``routers/students.py``) and the M6 roster import preview/apply conflict
    checks (``student_roster_service.py``), so preview and apply never grow a
    richer or different disclosure path than the one already approved for the
    single-Student API. Returns ``{"available": True}`` when the canonical
    value is free, or ``{"available": False, "student_id": int|None,
    "display_name": str|None}``. ``student_id``/``display_name`` are
    populated only when the conflicting identifier belongs to the SAME
    ``school_group_id`` as the requester AND the actor independently holds
    ``students.view`` for that scope; every other case (cross-tenant,
    unauthorized same-tenant, or a retired/reserved value with no currently
    visible holder) returns the fully generic unavailable signal.
    """
    holder = find_student_number_holder(db, canonical_value=canonical_value)
    if holder is None:
        return {"available": True}
    if holder["school_group_id"] == requester_school_group_id and auth.has_permission(
        db, actor, "students.view", school_group_id=requester_school_group_id
    ):
        student = get_student(db, requester_school_group_id, holder["student_id"])
        if student is not None:
            display_name = " ".join(
                part for part in (student.first_name, student.father_name, student.last_name) if part
            )
            return {"available": False, "student_id": student.id, "display_name": display_name}
    return {"available": False, "student_id": None, "display_name": None}


def _lock_student(db, *, school_group_id, student_id):
    """Acquire the Student row lock every placement write path must hold.

    On PostgreSQL this serializes concurrent placement writes for the same
    Student so overlap checks stay valid until commit. SQLite has no row-level
    locking, so this is a no-op there and offers no concurrency guarantee.
    """
    student = db.query(models.Student).filter(
        models.Student.id == student_id,
        models.Student.school_group_id == school_group_id,
    ).with_for_update().one_or_none()
    if student is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    return student


def _validate_placement_scope(db, *, school_group_id, student_id, branch_id, academic_year_id, planning_section_id):
    _lock_student(db, school_group_id=school_group_id, student_id=student_id)
    branch = db.query(models.Branch).filter_by(id=branch_id, school_group_id=school_group_id).one_or_none()
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=school_group_id).one_or_none()
    if branch is None or year is None:
        raise StudentAcademicError("invalid_scope", "Branch or academic year is outside the Student organization.")
    section = None
    if planning_section_id is not None:
        section = db.query(models.PlanningSection).filter_by(
            id=planning_section_id, branch_id=branch_id, academic_year_id=academic_year_id
        ).one_or_none()
        if section is None:
            raise StudentAcademicError("invalid_section_scope", "Planning section does not match the organization, branch, and academic year.")
    return section


def _validate_range(effective_from, effective_to):
    if effective_to is not None and effective_to <= effective_from:
        raise StudentAcademicError("invalid_effective_range", "effective_to must be later than effective_from.")


def _overlap_query(db, *, school_group_id, student_id, effective_from, effective_to, exclude_id=None):
    query = db.query(models.StudentAcademicPlacement).filter(
        models.StudentAcademicPlacement.school_group_id == school_group_id,
        models.StudentAcademicPlacement.student_id == student_id,
        or_(models.StudentAcademicPlacement.effective_to.is_(None), models.StudentAcademicPlacement.effective_to > effective_from),
    )
    if effective_to is not None:
        query = query.filter(models.StudentAcademicPlacement.effective_from < effective_to)
    if exclude_id is not None:
        query = query.filter(models.StudentAcademicPlacement.id != exclude_id)
    return query


def create_placement(db: Session, *, school_group_id: int, student_id: int, academic_year_id: int,
                     branch_id: int, effective_from: datetime, effective_to: datetime | None = None,
                     planning_section_id: int | None = None, grade_level=None, section_name=None,
                     reason=None, actor=None):
    _validate_range(effective_from, effective_to)
    section = _validate_placement_scope(db, school_group_id=school_group_id, student_id=student_id,
        branch_id=branch_id, academic_year_id=academic_year_id, planning_section_id=planning_section_id)
    if _overlap_query(db, school_group_id=school_group_id, student_id=student_id,
                      effective_from=effective_from, effective_to=effective_to).first():
        raise StudentAcademicError(
            "placement_overlap",
            "This Student already has an effective Academic Placement covering that period. "
            "End or Change the existing placement first, then add the new one.",
        )
    if section is not None:
        normalized_grade, snapshot_section = normalize_grade_level(section.grade_level), str(section.section_name or "").strip()
    else:
        normalized_grade, snapshot_section = normalize_grade_level(grade_level), str(section_name or "").strip()
    if not normalized_grade or not snapshot_section:
        raise StudentAcademicError("invalid_placement", "A canonical grade and section snapshot are required.")
    row = models.StudentAcademicPlacement(school_group_id=school_group_id, student_id=student_id,
        academic_year_id=academic_year_id, branch_id=branch_id, planning_section_id=planning_section_id,
        grade_level=normalized_grade, section_name=snapshot_section, effective_from=effective_from,
        effective_to=effective_to, status="ended" if effective_to else "active", reason=_clean(reason, "reason", maximum=255),
        created_by_user_id=getattr(actor, "user_id", None), updated_by_user_id=getattr(actor, "user_id", None))
    db.add(row); db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="academic_placement", resource_id=row.id, action="create", after=placement_payload(row))
    return row


def list_placements(db: Session, *, school_group_id: int, student_id: int):
    if get_student(db, school_group_id, student_id) is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    return db.query(models.StudentAcademicPlacement).filter_by(
        school_group_id=school_group_id, student_id=student_id
    ).order_by(models.StudentAcademicPlacement.effective_from, models.StudentAcademicPlacement.id).all()


def audit_event_payload(row):
    return {
        "id": row.id, "resource_type": row.resource_type, "resource_id": row.resource_id,
        "action": row.action, "actor_user_id": row.actor_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_audit_events(db: Session, *, school_group_id: int, student_id: int, limit: int = 200):
    """Read-only history trail for the canonical Student Profile History section.

    Reuses the existing append-only StudentAudit rows every mutation in this
    module already writes; this adds no new persistence authority.
    """
    if get_student(db, school_group_id, student_id) is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    return db.query(models.StudentAudit).filter_by(
        school_group_id=school_group_id, student_id=student_id
    ).order_by(models.StudentAudit.created_at.desc(), models.StudentAudit.id.desc()).limit(limit).all()


def resolve_placement(db: Session, *, school_group_id: int, student_id: int, at: datetime,
                      academic_year_id: int | None = None):
    query = db.query(models.StudentAcademicPlacement).filter(
        models.StudentAcademicPlacement.school_group_id == school_group_id,
        models.StudentAcademicPlacement.student_id == student_id,
        models.StudentAcademicPlacement.effective_from <= at,
        or_(models.StudentAcademicPlacement.effective_to.is_(None), models.StudentAcademicPlacement.effective_to > at),
    )
    if academic_year_id is not None:
        query = query.filter(models.StudentAcademicPlacement.academic_year_id == academic_year_id)
    return query.order_by(models.StudentAcademicPlacement.effective_from.desc()).one_or_none()


def end_placement(db: Session, *, school_group_id: int, student_id: int, placement_id: int,
                  effective_to: datetime, reason=None, actor=None):
    _lock_student(db, school_group_id=school_group_id, student_id=student_id)
    row = db.query(models.StudentAcademicPlacement).filter_by(id=placement_id, school_group_id=school_group_id, student_id=student_id).one_or_none()
    if row is None:
        raise StudentAcademicError("not_found", "Academic placement was not found.")
    before = placement_payload(row); _validate_range(row.effective_from, effective_to)
    if _overlap_query(db, school_group_id=school_group_id, student_id=student_id,
                      effective_from=row.effective_from, effective_to=effective_to, exclude_id=row.id).first():
        raise StudentAcademicError("placement_overlap", "The revised interval overlaps another academic placement.")
    row.effective_to = effective_to; row.status = "ended"; row.reason = _clean(reason, "reason", maximum=255) or row.reason
    row.updated_by_user_id = getattr(actor, "user_id", None); row.updated_at = datetime.utcnow(); db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="academic_placement", resource_id=row.id, action="end", before=before, after=placement_payload(row))
    return row


def correct_placement(db: Session, *, school_group_id: int, student_id: int, placement_id: int,
                      academic_year_id: int, branch_id: int, effective_from: datetime,
                      effective_to: datetime | None, planning_section_id: int | None = None,
                      grade_level=None, section_name=None, reason=None, actor=None):
    row = db.query(models.StudentAcademicPlacement).filter_by(
        id=placement_id, school_group_id=school_group_id, student_id=student_id
    ).one_or_none()
    if row is None:
        raise StudentAcademicError("not_found", "Academic placement was not found.")
    _validate_range(effective_from, effective_to)
    section = _validate_placement_scope(db, school_group_id=school_group_id, student_id=student_id,
        branch_id=branch_id, academic_year_id=academic_year_id, planning_section_id=planning_section_id)
    if _overlap_query(db, school_group_id=school_group_id, student_id=student_id,
                      effective_from=effective_from, effective_to=effective_to, exclude_id=row.id).first():
        raise StudentAcademicError("placement_overlap", "The corrected interval overlaps another academic placement.")
    if section is not None:
        grade_level, section_name = section.grade_level, section.section_name
    normalized_grade = normalize_grade_level(grade_level)
    snapshot_section = str(section_name or "").strip()
    if not normalized_grade or not snapshot_section:
        raise StudentAcademicError("invalid_placement", "A canonical grade and section snapshot are required.")
    before = placement_payload(row)
    row.academic_year_id = academic_year_id; row.branch_id = branch_id
    row.planning_section_id = planning_section_id; row.grade_level = normalized_grade
    row.section_name = snapshot_section; row.effective_from = effective_from
    row.effective_to = effective_to; row.status = "ended" if effective_to else "active"
    row.reason = _clean(reason, "reason", maximum=255); row.updated_by_user_id = getattr(actor, "user_id", None)
    row.updated_at = datetime.utcnow(); db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="academic_placement", resource_id=row.id, action="correction",
           before=before, after=placement_payload(row))
    return row


def transition_placement(db: Session, *, school_group_id: int, student_id: int, placement_id: int,
                         transition_at: datetime, actor=None, **new_context):
    old = end_placement(db, school_group_id=school_group_id, student_id=student_id,
                        placement_id=placement_id, effective_to=transition_at,
                        reason=new_context.get("reason"), actor=actor)
    new = create_placement(db, school_group_id=school_group_id, student_id=student_id,
        academic_year_id=new_context["academic_year_id"], branch_id=new_context["branch_id"],
        planning_section_id=new_context.get("planning_section_id"), grade_level=new_context.get("grade_level"),
        section_name=new_context.get("section_name"), effective_from=transition_at,
        effective_to=new_context.get("effective_to"), reason=new_context.get("reason"), actor=actor)
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="academic_placement", resource_id=new.id, action="transition",
           before=placement_payload(old), after=placement_payload(new))
    return old, new
