"""M2 Talent Program, versioned Framework, and competency governance service."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
from academic_grade import GRADE_LEVELS, normalize_grade_level


class TalentProgramError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code; self.message = message


def _clean(value, field, *, required=False, maximum=180):
    cleaned = " ".join(str(value or "").split())
    if required and not cleaned: raise TalentProgramError("invalid_input", f"{field} is required.")
    if len(cleaned) > maximum: raise TalentProgramError("invalid_input", f"{field} is too long.")
    return cleaned or None


def _json(value): return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _audit(db, *, group_id, program_id, actor, resource_type, resource_id, action, before=None, after=None):
    canonical = _json({"action": action, "before": before, "after": after})
    db.add(models.TalentConfigurationAudit(
        school_group_id=group_id, program_id=program_id,
        actor_user_id=getattr(actor, "user_id", None),
        actor_branch_id=getattr(actor, "scope_branch_id", None) or getattr(actor, "branch_id", None),
        resource_type=resource_type, resource_id=resource_id, action=action,
        before_json=_json(before) if before is not None else None,
        after_json=_json(after) if after is not None else None,
        correlation_id=hashlib.sha256(canonical.encode()).hexdigest(),
    ))


def program_payload(row):
    return {"id": row.id, "school_group_id": row.school_group_id, "name": row.name,
            "description": row.description, "status": row.status}


def framework_payload(row):
    return {"id": row.id, "school_group_id": row.school_group_id, "program_id": row.program_id,
            "version_number": row.version_number, "status": row.status, "title": row.title,
            "summary": row.summary, "revision": row.revision,
            "semantic_fingerprint": row.semantic_fingerprint,
            "supersedes_framework_version_id": row.supersedes_framework_version_id,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            "retired_at": row.retired_at.isoformat() if row.retired_at else None}


def get_program(db, group_id, program_id, *, lock=False):
    query = db.query(models.TalentProgram).filter_by(id=program_id, school_group_id=group_id)
    return (query.with_for_update() if lock else query).one_or_none()


def create_program(db: Session, *, school_group_id, name, description=None, actor=None):
    if db.get(models.SchoolGroup, school_group_id) is None: raise TalentProgramError("invalid_scope", "Organization is unavailable.")
    row = models.TalentProgram(school_group_id=school_group_id, name=_clean(name, "name", required=True, maximum=160),
        description=_clean(description, "description", maximum=4000), status="draft",
        created_by_user_id=getattr(actor, "user_id", None), updated_by_user_id=getattr(actor, "user_id", None))
    db.add(row)
    try: db.flush()
    except IntegrityError as exc: raise TalentProgramError("duplicate_program", "A Talent Program with that name already exists.") from exc
    _audit(db, group_id=school_group_id, program_id=row.id, actor=actor, resource_type="program", resource_id=row.id, action="create", after=program_payload(row))
    return row


def list_programs(db, *, school_group_id, search=""):
    query = db.query(models.TalentProgram).filter_by(school_group_id=school_group_id)
    if str(search or "").strip(): query = query.filter(models.TalentProgram.name.ilike(f"%{str(search).strip()}%"))
    return query.order_by(models.TalentProgram.name, models.TalentProgram.id).all()


def update_program(db, *, school_group_id, program_id, name=None, description=None, actor=None):
    row = get_program(db, school_group_id, program_id, lock=True)
    if row is None: raise TalentProgramError("not_found", "Talent Program was not found.")
    if row.status != "draft": raise TalentProgramError("immutable_program", "Only a Draft Talent Program can be edited.")
    before = program_payload(row)
    if name is not None: row.name = _clean(name, "name", required=True, maximum=160)
    if description is not None: row.description = _clean(description, "description", maximum=4000)
    row.updated_by_user_id = getattr(actor, "user_id", None); row.updated_at = datetime.utcnow(); db.flush()
    _audit(db, group_id=school_group_id, program_id=row.id, actor=actor, resource_type="program", resource_id=row.id, action="update", before=before, after=program_payload(row))
    return row


def transition_program(db, *, school_group_id, program_id, target_status, actor=None):
    row = get_program(db, school_group_id, program_id, lock=True)
    if row is None: raise TalentProgramError("not_found", "Talent Program was not found.")
    allowed = {("draft", "active"), ("active", "retired")}
    if (row.status, target_status) not in allowed: raise TalentProgramError("invalid_lifecycle", "Invalid Talent Program lifecycle transition.")
    if target_status == "retired" and db.query(models.TalentProgramFrameworkVersion).filter_by(program_id=row.id, status="active").first():
        raise TalentProgramError("active_framework_exists", "Retire the Active Framework Version before retiring its Talent Program.")
    before = program_payload(row); row.status = target_status; row.updated_by_user_id = getattr(actor, "user_id", None); row.updated_at = datetime.utcnow(); db.flush()
    _audit(db, group_id=school_group_id, program_id=row.id, actor=actor, resource_type="program", resource_id=row.id, action="activate" if target_status == "active" else "retire", before=before, after=program_payload(row))
    return row


def _grades_csv(values):
    if not isinstance(values, (list, tuple, set)) or not values: raise TalentProgramError("invalid_grades", "At least one eligible Grade is required.")
    normalized = {normalize_grade_level(value) for value in values}
    if "" in normalized: raise TalentProgramError("invalid_grades", "Eligible Grades must use KG or 1 through 12.")
    return ",".join(grade for grade in GRADE_LEVELS if grade in normalized)


def upsert_annual_configuration(db, *, school_group_id, program_id, academic_year_id, is_enabled, eligible_grade_levels, actor=None):
    program = get_program(db, school_group_id, program_id)
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=school_group_id).one_or_none()
    if program is None or year is None: raise TalentProgramError("invalid_scope", "Program and Academic Year must belong to the same organization.")
    if program.status == "retired": raise TalentProgramError("retired_program", "A retired Talent Program cannot change annual configuration.")
    row = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(program_id=program_id, academic_year_id=academic_year_id).one_or_none()
    before = {"is_enabled": row.is_enabled, "eligible_grade_levels": row.eligible_grade_levels_csv.split(",")} if row else None
    if row is None:
        row = models.TalentProgramAcademicYearConfiguration(school_group_id=school_group_id, program_id=program_id,
            academic_year_id=academic_year_id, created_by_user_id=getattr(actor, "user_id", None)); db.add(row)
    row.is_enabled = bool(is_enabled); row.eligible_grade_levels_csv = _grades_csv(eligible_grade_levels)
    row.updated_by_user_id = getattr(actor, "user_id", None); row.updated_at = datetime.utcnow(); db.flush()
    after = {"is_enabled": row.is_enabled, "eligible_grade_levels": row.eligible_grade_levels_csv.split(",")}
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="annual_configuration", resource_id=row.id, action="create" if before is None else "update", before=before, after=after)
    return row


def _framework_members(db, framework_id):
    return db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework_id).order_by(models.FrameworkCompetency.display_order).all()


def compute_framework_fingerprint(db, framework):
    payload = {"program_id": framework.program_id, "version_number": framework.version_number,
        "title": framework.title, "summary": framework.summary,
        "supersedes": framework.supersedes_framework_version_id,
        "competencies": [{"competency_id": m.talent_competency_id, "order": m.display_order, "label": m.label, "description": m.description} for m in _framework_members(db, framework.id)]}
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def _refresh_framework(db, framework):
    framework.semantic_fingerprint = compute_framework_fingerprint(db, framework)
    framework.updated_at = datetime.utcnow(); db.flush()


def _framework(db, group_id, program_id, framework_id, *, lock=False):
    query = db.query(models.TalentProgramFrameworkVersion).filter_by(id=framework_id, school_group_id=group_id, program_id=program_id)
    return (query.with_for_update() if lock else query).one_or_none()


def _validate_supersedes(db, *, group_id, program_id, framework_id, supersedes_id):
    if supersedes_id is None: return
    if supersedes_id == framework_id: raise TalentProgramError("invalid_supersession", "A Framework Version cannot supersede itself.")
    current = supersedes_id; seen = {framework_id}
    while current is not None:
        if current in seen: raise TalentProgramError("invalid_supersession", "Framework supersession cannot contain a cycle.")
        seen.add(current)
        row = _framework(db, group_id, program_id, current)
        if row is None: raise TalentProgramError("invalid_supersession", "Superseded Framework must belong to the same Program.")
        current = row.supersedes_framework_version_id


def create_framework_draft(db, *, school_group_id, program_id, title, summary=None, supersedes_framework_version_id=None, clone_from_id=None, actor=None):
    program = get_program(db, school_group_id, program_id, lock=True)
    if program is None: raise TalentProgramError("not_found", "Talent Program was not found.")
    if program.status == "retired": raise TalentProgramError("retired_program", "A retired Talent Program cannot receive new Framework Versions.")
    version = int(db.query(func.max(models.TalentProgramFrameworkVersion.version_number)).filter_by(program_id=program_id).scalar() or 0) + 1
    row = models.TalentProgramFrameworkVersion(school_group_id=school_group_id, program_id=program_id,
        version_number=version, status="draft", title=_clean(title, "title", required=True),
        summary=_clean(summary, "summary", maximum=4000), revision=1, semantic_fingerprint="",
        supersedes_framework_version_id=supersedes_framework_version_id,
        created_by_user_id=getattr(actor, "user_id", None), updated_by_user_id=getattr(actor, "user_id", None))
    db.add(row); db.flush(); _validate_supersedes(db, group_id=school_group_id, program_id=program_id, framework_id=row.id, supersedes_id=supersedes_framework_version_id)
    if clone_from_id is not None:
        source = _framework(db, school_group_id, program_id, clone_from_id)
        if source is None: raise TalentProgramError("invalid_clone", "Clone source must belong to the same Talent Program.")
        for member in _framework_members(db, source.id):
            db.add(models.FrameworkCompetency(school_group_id=school_group_id, program_id=program_id,
                framework_version_id=row.id, talent_competency_id=member.talent_competency_id,
                display_order=member.display_order, label=member.label, description=member.description))
        db.flush()
    _refresh_framework(db, row)
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_version", resource_id=row.id, action="clone" if clone_from_id else "create", after=framework_payload(row))
    return row


def _require_draft(framework, expected_revision=None, expected_fingerprint=None):
    if framework.status != "draft": raise TalentProgramError("immutable_framework", "Active and Retired Framework Versions are immutable.")
    if expected_revision is not None and framework.revision != expected_revision: raise TalentProgramError("stale_framework", "Framework Draft changed; refresh before retrying.")
    if expected_fingerprint is not None and framework.semantic_fingerprint != expected_fingerprint: raise TalentProgramError("stale_framework", "Framework Draft changed; refresh before retrying.")


def update_framework_draft(db, *, school_group_id, program_id, framework_id, expected_revision, title=None, summary=None, supersedes_framework_version_id=None, actor=None):
    row = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if row is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(row, expected_revision); before = framework_payload(row)
    if title is not None: row.title = _clean(title, "title", required=True)
    if summary is not None: row.summary = _clean(summary, "summary", maximum=4000)
    if supersedes_framework_version_id is not None:
        _validate_supersedes(db, group_id=school_group_id, program_id=program_id, framework_id=row.id, supersedes_id=supersedes_framework_version_id)
        row.supersedes_framework_version_id = supersedes_framework_version_id
    row.revision += 1; row.updated_by_user_id = getattr(actor, "user_id", None); _refresh_framework(db, row)
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_version", resource_id=row.id, action="update", before=before, after=framework_payload(row)); return row


def create_competency(db, *, school_group_id, program_id, code, name, description=None, actor=None):
    if get_program(db, school_group_id, program_id) is None: raise TalentProgramError("not_found", "Talent Program was not found.")
    row = models.TalentCompetency(school_group_id=school_group_id, program_id=program_id,
        code=_clean(code, "code", required=True, maximum=80).upper(), name=_clean(name, "name", required=True, maximum=160),
        description=_clean(description, "description", maximum=4000), status="active",
        created_by_user_id=getattr(actor, "user_id", None), updated_by_user_id=getattr(actor, "user_id", None))
    db.add(row)
    try: db.flush()
    except IntegrityError as exc: raise TalentProgramError("duplicate_competency", "Competency code already exists in this Program.") from exc
    after = {"id": row.id, "code": row.code, "name": row.name, "description": row.description, "status": row.status}
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="competency", resource_id=row.id, action="create", after=after); return row


def update_competency(db, *, school_group_id, program_id, competency_id, name=None, description=None, status=None, actor=None):
    row = db.query(models.TalentCompetency).filter_by(id=competency_id, school_group_id=school_group_id, program_id=program_id).with_for_update().one_or_none()
    if row is None: raise TalentProgramError("not_found", "Talent Competency was not found.")
    if row.status == "retired": raise TalentProgramError("immutable_competency", "A retired Talent Competency is immutable.")
    before = {"code": row.code, "name": row.name, "description": row.description, "status": row.status}
    if name is not None: row.name = _clean(name, "name", required=True, maximum=160)
    if description is not None: row.description = _clean(description, "description", maximum=4000)
    if status is not None:
        if status not in {"active", "retired"} or row.status == "retired": raise TalentProgramError("invalid_lifecycle", "Competency may transition only from active to retired.")
        row.status = status
    row.updated_by_user_id = getattr(actor, "user_id", None); row.updated_at = datetime.utcnow(); db.flush()
    after = {"code": row.code, "name": row.name, "description": row.description, "status": row.status}
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="competency", resource_id=row.id, action="retire" if before["status"] != after["status"] else "update", before=before, after=after); return row


def add_framework_competency(db, *, school_group_id, program_id, framework_id, competency_id, expected_revision, label=None, description=None, display_order=None, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision)
    competency = db.query(models.TalentCompetency).filter_by(id=competency_id, school_group_id=school_group_id, program_id=program_id).one_or_none()
    if competency is None or competency.status != "active": raise TalentProgramError("invalid_competency", "Competency must be active and belong to the same Program.")
    if db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework_id, talent_competency_id=competency_id).first(): raise TalentProgramError("duplicate_membership", "Competency is already in this Framework Version.")
    order = display_order or int(db.query(func.max(models.FrameworkCompetency.display_order)).filter_by(framework_version_id=framework_id).scalar() or 0) + 1
    row = models.FrameworkCompetency(school_group_id=school_group_id, program_id=program_id, framework_version_id=framework_id,
        talent_competency_id=competency_id, display_order=order,
        label=_clean(label, "label", maximum=160) or competency.name,
        description=_clean(description, "description", maximum=4000) if description is not None else competency.description)
    db.add(row); db.flush(); framework.revision += 1; _refresh_framework(db, framework)
    after = {"competency_id": competency_id, "display_order": row.display_order, "label": row.label, "description": row.description}
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_competency", resource_id=row.id, action="add", after=after); return row, framework


def reorder_framework_competencies(db, *, school_group_id, program_id, framework_id, competency_ids, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); members = _framework_members(db, framework_id)
    by_id = {m.talent_competency_id: m for m in members}
    if len(competency_ids) != len(set(competency_ids)) or set(competency_ids) != set(by_id): raise TalentProgramError("invalid_order", "Order must contain every Framework competency exactly once.")
    before = [m.talent_competency_id for m in members]
    offset = len(members) + 1000000
    for index, competency_id in enumerate(competency_ids, 1): by_id[competency_id].display_order = offset + index
    db.flush()
    for index, competency_id in enumerate(competency_ids, 1): by_id[competency_id].display_order = index
    framework.revision += 1; _refresh_framework(db, framework)
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_version", resource_id=framework.id, action="reorder", before=before, after=competency_ids); return members, framework


def update_framework_competency(db, *, school_group_id, program_id, framework_id, competency_id,
                                expected_revision, label=None, description=None, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision)
    row = db.query(models.FrameworkCompetency).filter_by(
        framework_version_id=framework_id, talent_competency_id=competency_id
    ).one_or_none()
    if row is None: raise TalentProgramError("not_found", "Framework competency was not found.")
    before = {"competency_id": row.talent_competency_id, "display_order": row.display_order, "label": row.label, "description": row.description}
    if label is not None: row.label = _clean(label, "label", required=True, maximum=160)
    if description is not None: row.description = _clean(description, "description", maximum=4000)
    row.updated_at = datetime.utcnow(); framework.revision += 1; _refresh_framework(db, framework)
    after = {"competency_id": row.talent_competency_id, "display_order": row.display_order, "label": row.label, "description": row.description}
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_competency", resource_id=row.id, action="update", before=before, after=after)
    return row, framework


def remove_framework_competency(db, *, school_group_id, program_id, framework_id, competency_id, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision)
    row = db.query(models.FrameworkCompetency).filter_by(framework_version_id=framework_id, talent_competency_id=competency_id).one_or_none()
    if row is None: raise TalentProgramError("not_found", "Framework competency was not found.")
    before = {"competency_id": row.talent_competency_id, "display_order": row.display_order, "label": row.label, "description": row.description}
    db.delete(row); db.flush()
    for index, member in enumerate(_framework_members(db, framework_id), 1): member.display_order = index
    framework.revision += 1; _refresh_framework(db, framework)
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_competency", resource_id=row.id, action="remove", before=before); return framework


def activate_framework(db, *, school_group_id, program_id, framework_id, expected_revision, expected_fingerprint, organization_authorized, actor=None):
    if not organization_authorized: raise TalentProgramError("organization_authority_required", "Organization authority is required to activate a Framework Version.")
    if not expected_fingerprint: raise TalentProgramError("stale_framework", "The reviewed Framework fingerprint is required for activation.")
    program = get_program(db, school_group_id, program_id, lock=True)
    if program is None: raise TalentProgramError("not_found", "Talent Program was not found.")
    if program.status != "active": raise TalentProgramError("program_not_active", "Activate the Talent Program before activating a Framework Version.")
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision, expected_fingerprint)
    current = db.query(models.TalentProgramFrameworkVersion).filter_by(program_id=program_id, status="active").with_for_update().one_or_none()
    if current is not None:
        if framework.supersedes_framework_version_id != current.id: raise TalentProgramError("supersession_required", "The new Framework must explicitly supersede the current Active version.")
        before_current = framework_payload(current); current.status = "retired"; current.retired_at = datetime.utcnow(); current.retired_by_user_id = getattr(actor, "user_id", None)
        _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_version", resource_id=current.id, action="superseded", before=before_current, after=framework_payload(current))
        db.flush()
    before = framework_payload(framework); framework.status = "active"; framework.activated_at = datetime.utcnow(); framework.activated_by_user_id = getattr(actor, "user_id", None); db.flush()
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_version", resource_id=framework.id, action="activate", before=before, after=framework_payload(framework)); return framework


def retire_framework(db, *, school_group_id, program_id, framework_id, organization_authorized, actor=None):
    if not organization_authorized: raise TalentProgramError("organization_authority_required", "Organization authority is required to retire a Framework Version.")
    row = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if row is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    if row.status != "active": raise TalentProgramError("invalid_lifecycle", "Only an Active Framework Version can be retired.")
    before = framework_payload(row); row.status = "retired"; row.retired_at = datetime.utcnow(); row.retired_by_user_id = getattr(actor, "user_id", None); db.flush()
    _audit(db, group_id=school_group_id, program_id=program_id, actor=actor, resource_type="framework_version", resource_id=row.id, action="retire", before=before, after=framework_payload(row)); return row
