"""Canonical Student and effective-dated academic placement application service."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

import models
from academic_grade import normalize_grade_level


class StudentAcademicError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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
                   father_name=None, gender=None, actor=None):
    if db.get(models.SchoolGroup, school_group_id) is None:
        raise StudentAcademicError("invalid_scope", "The selected organization is unavailable.")
    student = models.Student(
        school_group_id=school_group_id,
        first_name=_clean(first_name, "first_name", required=True),
        father_name=_clean(father_name, "father_name"),
        last_name=_clean(last_name, "last_name", required=True),
        gender=_clean(gender, "gender", maximum=24), status="active",
        created_by_user_id=getattr(actor, "user_id", None),
        updated_by_user_id=getattr(actor, "user_id", None),
    )
    db.add(student); db.flush()
    _audit(db, school_group_id=school_group_id, student_id=student.id, actor=actor,
           resource_type="student", resource_id=student.id, action="create", after=_student_payload(student))
    return student


def update_student(db: Session, *, school_group_id: int, student_id: int, actor=None, **changes):
    student = get_student(db, school_group_id, student_id)
    if student is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    before = _student_payload(student)
    for field in ("first_name", "father_name", "last_name", "gender"):
        if field in changes:
            setattr(student, field, _clean(changes[field], field, required=field in {"first_name", "last_name"}, maximum=24 if field == "gender" else 100))
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


def list_students(db: Session, *, school_group_id: int, search: str = "", status: str | None = None):
    query = db.query(models.Student).filter(models.Student.school_group_id == school_group_id)
    cleaned = str(search or "").strip()
    if cleaned:
        pattern = f"%{cleaned}%"
        query = query.filter(or_(models.Student.first_name.ilike(pattern), models.Student.father_name.ilike(pattern), models.Student.last_name.ilike(pattern)))
    if status:
        query = query.filter(models.Student.status == str(status).strip().lower())
    return query.order_by(models.Student.last_name, models.Student.first_name, models.Student.id).all()


def add_external_identifier(db: Session, *, school_group_id: int, student_id: int,
                            namespace, value, source=None, actor=None):
    if get_student(db, school_group_id, student_id) is None:
        raise StudentAcademicError("not_found", "Student was not found.")
    namespace = _clean(namespace, "namespace", required=True, maximum=80)
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
    before = {"namespace": row.namespace, "value": row.value, "source": row.source, "status": row.status}
    row.status = "inactive"; row.updated_at = datetime.utcnow(); db.flush()
    after = {**before, "status": "inactive"}
    _audit(db, school_group_id=school_group_id, student_id=student_id, actor=actor,
           resource_type="external_identifier", resource_id=row.id, action="deactivate", before=before, after=after)
    return row


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
        raise StudentAcademicError("placement_overlap", "Student already has an effective academic placement in this interval.")
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
