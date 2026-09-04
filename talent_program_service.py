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
        "competencies": [{"competency_id": m.talent_competency_id, "order": m.display_order, "label": m.label, "description": m.description} for m in _framework_members(db, framework.id)],
        "m3_configuration": _m3_semantic_payload(db, framework.id)}
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
        _clone_m3_configuration(db, source=source, target=row)
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
    if (db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_competency_id=row.id).first()
            or db.query(models.TalentKpiComponent).filter_by(framework_competency_id=row.id).first()
            or db.query(models.TalentReviewCandidateRule).filter_by(framework_competency_id=row.id).first()):
        raise TalentProgramError("competency_in_use", "Remove rubric descriptors, KPI weighting, and candidate rules referencing this competency first.")
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


def _rubric(db, framework_id):
    return db.query(models.TalentRubric).filter_by(framework_version_id=framework_id).one_or_none()


def _enforce_enabled_kpi_numeric_scale(db, framework_id, numeric_value):
    """An enabled KPI requires every rubric level to keep an in-scale numeric value; this must
    hold continuously, not only at the moment KPI is configured, so a later level add/edit
    cannot silently reintroduce a missing or out-of-scale value."""
    kpi = db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=framework_id, is_enabled=True).one_or_none()
    if kpi is None: return
    if numeric_value is None or not kpi.result_scale_min <= numeric_value <= kpi.result_scale_max:
        raise TalentProgramError("invalid_kpi", "Enabled KPI requires every rubric level to have a numeric value within the declared result scale.")


def _m3_semantic_payload(db, framework_id):
    rubric = _rubric(db, framework_id)
    levels = db.query(models.TalentRubricLevel).filter_by(framework_version_id=framework_id).order_by(models.TalentRubricLevel.display_order).all()
    descriptors = db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_version_id=framework_id).order_by(models.TalentCompetencyRubricDescriptor.framework_competency_id, models.TalentCompetencyRubricDescriptor.rubric_level_id).all()
    kpi = db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=framework_id).one_or_none()
    components = db.query(models.TalentKpiComponent).filter_by(framework_version_id=framework_id).order_by(models.TalentKpiComponent.framework_competency_id).all()
    policy = db.query(models.TalentReviewCandidatePolicy).filter_by(framework_version_id=framework_id).one_or_none()
    rules = db.query(models.TalentReviewCandidateRule).filter_by(framework_version_id=framework_id).order_by(models.TalentReviewCandidateRule.display_order).all()
    return {
        "rubric": None if rubric is None else {"name": rubric.name, "description": rubric.description},
        "levels": [{"code": r.code, "label": r.label, "description": r.description, "order": r.display_order, "numeric_value": r.numeric_value} for r in levels],
        "descriptors": [{"framework_competency_id": r.framework_competency_id, "rubric_level_id": r.rubric_level_id, "descriptor": r.descriptor} for r in descriptors],
        "kpi": None if kpi is None else {"enabled": kpi.is_enabled, "method": kpi.calculation_method, "scale_min": kpi.result_scale_min, "scale_max": kpi.result_scale_max, "interpretation": kpi.interpretation,
            "components": [{"framework_competency_id": r.framework_competency_id, "weight_basis_points": r.weight_basis_points} for r in components]},
        "review_candidate_policy": None if policy is None else {"enabled": policy.is_enabled, "match_mode": policy.match_mode, "description": policy.description,
            "rules": [{"type": r.rule_type, "order": r.display_order, "framework_competency_id": r.framework_competency_id, "rubric_level_id": r.rubric_level_id, "threshold_value": r.threshold_value} for r in rules]},
    }


def get_framework_configuration(db, *, school_group_id, program_id, framework_id):
    framework = _framework(db, school_group_id, program_id, framework_id)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    result = _m3_semantic_payload(db, framework.id)
    result.update({"framework_id": framework.id, "revision": framework.revision, "semantic_fingerprint": framework.semantic_fingerprint})
    return result


def _m3_mutation(db, framework, *, actor, action, before, resources):
    """Bump the Framework revision/fingerprint once, then append one audit row per
    (resource_type, resource_id) in ``resources`` - the specific M3 child resource(s)
    this mutation touched (rubric, rubric_level, rubric_descriptor, kpi_configuration,
    kpi_component, review_candidate_policy, review_candidate_rule) - not just the
    containing framework_version, matching the existing M2 framework_competency audit
    precedent. Every row shares the same before/after configuration snapshot and
    revision, so the audit shape itself is unchanged - only resource identity is
    additive. Aggregate operations (e.g. reorder_rubric_levels) pass one entry per
    changed child row so each level's own audit identity is preserved."""
    framework.revision += 1; framework.updated_by_user_id = getattr(actor, "user_id", None); _refresh_framework(db, framework)
    after = get_framework_configuration(db, school_group_id=framework.school_group_id, program_id=framework.program_id, framework_id=framework.id)
    audit_before = {"configuration": before, "revision": framework.revision - 1}
    for resource_type, resource_id in resources:
        _audit(db, group_id=framework.school_group_id, program_id=framework.program_id, actor=actor,
               resource_type=resource_type, resource_id=resource_id, action=action,
               before=audit_before, after=after)
    return framework


def upsert_rubric(db, *, school_group_id, program_id, framework_id, expected_revision, name, description=None, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); before = _m3_semantic_payload(db, framework.id)
    row = _rubric(db, framework.id)
    if row is None:
        row = models.TalentRubric(school_group_id=school_group_id, program_id=program_id, framework_version_id=framework.id); db.add(row)
    row.name = _clean(name, "name", required=True); row.description = _clean(description, "description", maximum=4000); row.updated_at = datetime.utcnow(); db.flush()
    _m3_mutation(db, framework, actor=actor, action="rubric_upsert", before=before, resources=[("rubric", row.id)]); return row, framework


def add_rubric_level(db, *, school_group_id, program_id, framework_id, expected_revision, code, label, description=None, numeric_value=None, display_order=None, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); rubric = _rubric(db, framework.id)
    if rubric is None: raise TalentProgramError("rubric_required", "Create the Framework rubric before adding levels.")
    before = _m3_semantic_payload(db, framework.id); code = _clean(code, "code", required=True, maximum=80).upper()
    if db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric.id, code=code).first(): raise TalentProgramError("duplicate_level", "Rubric level code already exists in this Framework.")
    order = display_order or int(db.query(func.max(models.TalentRubricLevel.display_order)).filter_by(rubric_id=rubric.id).scalar() or 0) + 1
    if db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric.id, display_order=order).first(): raise TalentProgramError("duplicate_order", "Rubric level display order already exists.")
    if numeric_value is not None and isinstance(numeric_value, bool): raise TalentProgramError("invalid_kpi", "Numeric level values must be integers.")
    numeric_value = int(numeric_value) if numeric_value is not None else None
    _enforce_enabled_kpi_numeric_scale(db, framework.id, numeric_value)
    row = models.TalentRubricLevel(school_group_id=school_group_id, program_id=program_id, framework_version_id=framework.id, rubric_id=rubric.id,
        code=code, label=_clean(label, "label", required=True, maximum=160), description=_clean(description, "description", maximum=4000),
        display_order=int(order), numeric_value=numeric_value)
    db.add(row); db.flush(); _m3_mutation(db, framework, actor=actor, action="rubric_level_add", before=before, resources=[("rubric_level", row.id)]); return row, framework


def update_rubric_level(db, *, school_group_id, program_id, framework_id, level_id, expected_revision, label=None, description=None, numeric_value="__unchanged__", actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision)
    row = db.query(models.TalentRubricLevel).filter_by(id=level_id, framework_version_id=framework.id, program_id=program_id, school_group_id=school_group_id).one_or_none()
    if row is None: raise TalentProgramError("not_found", "Rubric level was not found.")
    before = _m3_semantic_payload(db, framework.id)
    if label is not None: row.label = _clean(label, "label", required=True, maximum=160)
    if description is not None: row.description = _clean(description, "description", maximum=4000)
    if numeric_value != "__unchanged__":
        if isinstance(numeric_value, bool): raise TalentProgramError("invalid_kpi", "Numeric level values must be integers.")
        numeric_value = int(numeric_value) if numeric_value is not None else None
        _enforce_enabled_kpi_numeric_scale(db, framework.id, numeric_value)
        row.numeric_value = numeric_value
    row.updated_at = datetime.utcnow(); db.flush(); _m3_mutation(db, framework, actor=actor, action="rubric_level_update", before=before, resources=[("rubric_level", row.id)]); return row, framework


def reorder_rubric_levels(db, *, school_group_id, program_id, framework_id, level_ids, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); rubric = _rubric(db, framework.id); rows = db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric.id if rubric else -1).all()
    by_id = {row.id: row for row in rows}
    if len(level_ids) != len(set(level_ids)) or set(level_ids) != set(by_id): raise TalentProgramError("invalid_order", "Order must contain every rubric level exactly once.")
    before = _m3_semantic_payload(db, framework.id); offset = len(rows) + 1000000
    for index, level_id in enumerate(level_ids, 1): by_id[level_id].display_order = offset + index
    db.flush()
    for index, level_id in enumerate(level_ids, 1): by_id[level_id].display_order = index
    # Aggregate operation: every touched level keeps its own rubric_level audit
    # identity (one row per level) rather than collapsing to the framework or
    # the rubric, so per-level audit history is preserved for this semantic
    # order (proficiency rank) change.
    _m3_mutation(db, framework, actor=actor, action="rubric_levels_reorder", before=before, resources=[("rubric_level", level_id) for level_id in level_ids]); return framework


def remove_rubric_level(db, *, school_group_id, program_id, framework_id, level_id, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision)
    row = db.query(models.TalentRubricLevel).filter_by(id=level_id, framework_version_id=framework.id).one_or_none()
    if row is None: raise TalentProgramError("not_found", "Rubric level was not found.")
    if db.query(models.TalentCompetencyRubricDescriptor).filter_by(rubric_level_id=row.id).first() or db.query(models.TalentReviewCandidateRule).filter_by(rubric_level_id=row.id).first(): raise TalentProgramError("level_in_use", "Remove descriptors and policy rules that use this level first.")
    before = _m3_semantic_payload(db, framework.id); removed_level_id = row.id; db.delete(row); db.flush()
    for index, remaining in enumerate(db.query(models.TalentRubricLevel).filter_by(rubric_id=row.rubric_id).order_by(models.TalentRubricLevel.display_order), 1): remaining.display_order = index
    _m3_mutation(db, framework, actor=actor, action="rubric_level_remove", before=before, resources=[("rubric_level", removed_level_id)]); return framework


def upsert_descriptor(db, *, school_group_id, program_id, framework_id, framework_competency_id, rubric_level_id, expected_revision, descriptor, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); rubric = _rubric(db, framework.id)
    member = db.query(models.FrameworkCompetency).filter_by(id=framework_competency_id, framework_version_id=framework.id, program_id=program_id, school_group_id=school_group_id).one_or_none()
    level = db.query(models.TalentRubricLevel).filter_by(id=rubric_level_id, framework_version_id=framework.id, program_id=program_id, school_group_id=school_group_id).one_or_none()
    if rubric is None or member is None or level is None or level.rubric_id != rubric.id: raise TalentProgramError("invalid_descriptor_scope", "Descriptor competency and level must belong to this exact Framework.")
    before = _m3_semantic_payload(db, framework.id)
    row = db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_competency_id=member.id, rubric_level_id=level.id).one_or_none()
    if row is None:
        row = models.TalentCompetencyRubricDescriptor(school_group_id=school_group_id, program_id=program_id, framework_version_id=framework.id, rubric_id=rubric.id, framework_competency_id=member.id, rubric_level_id=level.id); db.add(row)
    row.descriptor = _clean(descriptor, "descriptor", required=True, maximum=8000); row.updated_at = datetime.utcnow(); db.flush()
    _m3_mutation(db, framework, actor=actor, action="rubric_descriptor_upsert", before=before, resources=[("rubric_descriptor", row.id)]); return row, framework


def remove_descriptor(db, *, school_group_id, program_id, framework_id, descriptor_id, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); row = db.query(models.TalentCompetencyRubricDescriptor).filter_by(id=descriptor_id, framework_version_id=framework.id).one_or_none()
    if row is None: raise TalentProgramError("not_found", "Rubric descriptor was not found.")
    before = _m3_semantic_payload(db, framework.id); removed_descriptor_id = row.id; db.delete(row); db.flush(); _m3_mutation(db, framework, actor=actor, action="rubric_descriptor_remove", before=before, resources=[("rubric_descriptor", removed_descriptor_id)]); return framework


def configure_kpi(db, *, school_group_id, program_id, framework_id, expected_revision, is_enabled, result_scale_min, result_scale_max, interpretation, components, calculation_method="weighted_level_average", actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); before = _m3_semantic_payload(db, framework.id)
    # Governed, closed KPI primitive set (Decision 1): weighted_level_average is the
    # only approved calculation_method. This is intentionally not an open/scriptable
    # rule engine - no SQL, Python expression, or generic JSON logic is accepted, and
    # any additional primitive requires future governed Product Owner approval plus a
    # matching CheckConstraint/model change, not a runtime-configurable expression.
    if calculation_method != "weighted_level_average": raise TalentProgramError("invalid_kpi", "Only the bounded weighted_level_average KPI method is supported.")
    scale_min, scale_max = int(result_scale_min), int(result_scale_max)
    if scale_max <= scale_min: raise TalentProgramError("invalid_kpi", "KPI result scale maximum must exceed minimum.")
    normalized = components or []
    ids = [int(item.get("framework_competency_id")) for item in normalized]
    weights = [int(item.get("weight_basis_points")) for item in normalized]
    if is_enabled and (not ids or len(ids) != len(set(ids)) or sum(weights) != 10000 or any(weight <= 0 for weight in weights)): raise TalentProgramError("invalid_kpi", "Enabled KPI components must be unique, positive, and total exactly 10000 basis points.")
    members = {row.id for row in _framework_members(db, framework.id)}
    if any(item not in members for item in ids): raise TalentProgramError("invalid_kpi", "Every KPI input must be an exact Framework competency.")
    levels = db.query(models.TalentRubricLevel).filter_by(framework_version_id=framework.id).all()
    if is_enabled and (not levels or any(level.numeric_value is None or not scale_min <= level.numeric_value <= scale_max for level in levels)): raise TalentProgramError("invalid_kpi", "Enabled KPI requires every rubric level to have a numeric value within the declared result scale.")
    row = db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=framework.id).one_or_none()
    if row is None:
        row = models.TalentKpiConfiguration(
            school_group_id=school_group_id, program_id=program_id,
            framework_version_id=framework.id, is_enabled=bool(is_enabled),
            calculation_method=calculation_method, result_scale_min=scale_min,
            result_scale_max=scale_max,
            interpretation=_clean(interpretation, "interpretation", required=True, maximum=4000),
        ); db.add(row); db.flush()
    row.is_enabled = bool(is_enabled); row.calculation_method = calculation_method; row.result_scale_min = scale_min; row.result_scale_max = scale_max; row.interpretation = _clean(interpretation, "interpretation", required=True, maximum=4000); row.updated_at = datetime.utcnow()
    db.query(models.TalentKpiComponent).filter_by(kpi_configuration_id=row.id).delete(synchronize_session=False)
    new_components = []
    for member_id, weight in zip(ids, weights):
        component = models.TalentKpiComponent(school_group_id=school_group_id, program_id=program_id, framework_version_id=framework.id, kpi_configuration_id=row.id, framework_competency_id=member_id, weight_basis_points=weight)
        db.add(component); new_components.append(component)
    db.flush()
    resources = [("kpi_configuration", row.id)] + [("kpi_component", component.id) for component in new_components]
    _m3_mutation(db, framework, actor=actor, action="kpi_configure", before=before, resources=resources); return row, framework


def remove_kpi(db, *, school_group_id, program_id, framework_id, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); row = db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=framework.id).one_or_none()
    if row is None: raise TalentProgramError("not_found", "KPI configuration was not found.")
    if db.query(models.TalentReviewCandidateRule).filter_by(framework_version_id=framework.id, rule_type="kpi_at_or_above").first(): raise TalentProgramError("kpi_in_use", "Remove KPI-based candidate rules before removing KPI configuration.")
    before = _m3_semantic_payload(db, framework.id); removed_kpi_id = row.id; db.query(models.TalentKpiComponent).filter_by(kpi_configuration_id=row.id).delete(synchronize_session=False); db.delete(row); db.flush(); _m3_mutation(db, framework, actor=actor, action="kpi_remove", before=before, resources=[("kpi_configuration", removed_kpi_id)]); return framework


def configure_review_candidate_policy(db, *, school_group_id, program_id, framework_id, expected_revision, is_enabled, match_mode, description, rules, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); mode = str(match_mode or "").strip().lower()
    if mode not in {"all", "any"}: raise TalentProgramError("invalid_policy", "Candidate policy match_mode must be all or any.")
    if is_enabled and not rules: raise TalentProgramError("invalid_policy", "Enabled candidate policy requires at least one rule.")
    rubric = _rubric(db, framework.id); member_ids = {row.id for row in _framework_members(db, framework.id)}
    level_ids = {row.id for row in db.query(models.TalentRubricLevel).filter_by(framework_version_id=framework.id)}
    kpi = db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=framework.id, is_enabled=True).one_or_none()
    normalized = []; seen_competencies = set(); kpi_rule_seen = False
    for index, item in enumerate(rules or [], 1):
        rule_type = str(item.get("rule_type") or "")
        # Decision 3: "at or above" is defined purely by the configured rubric level
        # order (TalentRubricLevel.display_order, lowest proficiency first), never by
        # numeric_value, so qualitative Programs with no KPI and no numeric levels
        # still get correct, meaningful thresholds. Storing rubric_level_id here (the
        # exact configured level) is sufficient; evaluation against that level's order
        # is deferred to M4.
        if rule_type == "rubric_level_at_or_above":
            member_id, level_id = int(item.get("framework_competency_id")), int(item.get("rubric_level_id"))
            if member_id not in member_ids or level_id not in level_ids or rubric is None: raise TalentProgramError("invalid_policy", "Rubric candidate rules must reference this exact Framework competency and level.")
            if member_id in seen_competencies: raise TalentProgramError("duplicate_rule", "Each Framework competency can have only one candidate rule.")
            seen_competencies.add(member_id)
            normalized.append((rule_type, index, member_id, rubric.id, level_id, None))
        elif rule_type == "kpi_at_or_above":
            threshold = int(item.get("threshold_value"))
            if kpi is None or not kpi.result_scale_min <= threshold <= kpi.result_scale_max: raise TalentProgramError("invalid_policy", "KPI candidate rules require an enabled KPI and an in-scale threshold.")
            if kpi_rule_seen: raise TalentProgramError("duplicate_rule", "Only one KPI candidate rule is supported.")
            kpi_rule_seen = True
            normalized.append((rule_type, index, None, None, None, threshold))
        else: raise TalentProgramError("invalid_policy", "Unsupported candidate rule type.")
    before = _m3_semantic_payload(db, framework.id); policy = db.query(models.TalentReviewCandidatePolicy).filter_by(framework_version_id=framework.id).one_or_none()
    if policy is None:
        policy = models.TalentReviewCandidatePolicy(
            school_group_id=school_group_id, program_id=program_id,
            framework_version_id=framework.id, is_enabled=bool(is_enabled),
            match_mode=mode,
            description=_clean(description, "description", maximum=4000),
        ); db.add(policy); db.flush()
    policy.is_enabled = bool(is_enabled); policy.match_mode = mode; policy.description = _clean(description, "description", maximum=4000); policy.updated_at = datetime.utcnow()
    db.query(models.TalentReviewCandidateRule).filter_by(policy_id=policy.id).delete(synchronize_session=False)
    new_rules = []
    for rule_type, order, member_id, rubric_id, level_id, threshold in normalized:
        rule = models.TalentReviewCandidateRule(school_group_id=school_group_id, program_id=program_id, framework_version_id=framework.id, policy_id=policy.id,
            rule_type=rule_type, display_order=order, framework_competency_id=member_id, rubric_id=rubric_id, rubric_level_id=level_id, threshold_value=threshold)
        db.add(rule); new_rules.append(rule)
    db.flush()
    resources = [("review_candidate_policy", policy.id)] + [("review_candidate_rule", rule.id) for rule in new_rules]
    _m3_mutation(db, framework, actor=actor, action="review_candidate_policy_configure", before=before, resources=resources); return policy, framework


def remove_review_candidate_policy(db, *, school_group_id, program_id, framework_id, expected_revision, actor=None):
    framework = _framework(db, school_group_id, program_id, framework_id, lock=True)
    if framework is None: raise TalentProgramError("not_found", "Framework Version was not found.")
    _require_draft(framework, expected_revision); policy = db.query(models.TalentReviewCandidatePolicy).filter_by(framework_version_id=framework.id).one_or_none()
    if policy is None: raise TalentProgramError("not_found", "Review Candidate Policy was not found.")
    before = _m3_semantic_payload(db, framework.id); removed_policy_id = policy.id; db.query(models.TalentReviewCandidateRule).filter_by(policy_id=policy.id).delete(synchronize_session=False); db.delete(policy); db.flush(); _m3_mutation(db, framework, actor=actor, action="review_candidate_policy_remove", before=before, resources=[("review_candidate_policy", removed_policy_id)]); return framework


def _clone_m3_configuration(db, *, source, target):
    rubric = _rubric(db, source.id)
    source_members = {row.id: row.talent_competency_id for row in _framework_members(db, source.id)}
    target_members = {row.talent_competency_id: row.id for row in _framework_members(db, target.id)}
    member_map = {source_id: target_members[competency_id] for source_id, competency_id in source_members.items()}
    level_map = {}
    target_rubric = None
    if rubric:
        target_rubric = models.TalentRubric(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, name=rubric.name, description=rubric.description); db.add(target_rubric); db.flush()
        for level in db.query(models.TalentRubricLevel).filter_by(rubric_id=rubric.id).order_by(models.TalentRubricLevel.display_order):
            copied = models.TalentRubricLevel(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, rubric_id=target_rubric.id, code=level.code, label=level.label, description=level.description, display_order=level.display_order, numeric_value=level.numeric_value); db.add(copied); db.flush(); level_map[level.id] = copied.id
        for descriptor in db.query(models.TalentCompetencyRubricDescriptor).filter_by(framework_version_id=source.id):
            db.add(models.TalentCompetencyRubricDescriptor(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, rubric_id=target_rubric.id, framework_competency_id=member_map[descriptor.framework_competency_id], rubric_level_id=level_map[descriptor.rubric_level_id], descriptor=descriptor.descriptor))
    source_kpi = db.query(models.TalentKpiConfiguration).filter_by(framework_version_id=source.id).one_or_none()
    if source_kpi:
        target_kpi = models.TalentKpiConfiguration(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, is_enabled=source_kpi.is_enabled, calculation_method=source_kpi.calculation_method, result_scale_min=source_kpi.result_scale_min, result_scale_max=source_kpi.result_scale_max, interpretation=source_kpi.interpretation); db.add(target_kpi); db.flush()
        for component in db.query(models.TalentKpiComponent).filter_by(kpi_configuration_id=source_kpi.id):
            db.add(models.TalentKpiComponent(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, kpi_configuration_id=target_kpi.id, framework_competency_id=member_map[component.framework_competency_id], weight_basis_points=component.weight_basis_points))
    source_policy = db.query(models.TalentReviewCandidatePolicy).filter_by(framework_version_id=source.id).one_or_none()
    if source_policy:
        target_policy = models.TalentReviewCandidatePolicy(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, is_enabled=source_policy.is_enabled, match_mode=source_policy.match_mode, description=source_policy.description); db.add(target_policy); db.flush()
        for rule in db.query(models.TalentReviewCandidateRule).filter_by(policy_id=source_policy.id).order_by(models.TalentReviewCandidateRule.display_order):
            db.add(models.TalentReviewCandidateRule(school_group_id=target.school_group_id, program_id=target.program_id, framework_version_id=target.id, policy_id=target_policy.id, rule_type=rule.rule_type, display_order=rule.display_order, framework_competency_id=member_map.get(rule.framework_competency_id), rubric_id=target_rubric.id if rule.rubric_id else None, rubric_level_id=level_map.get(rule.rubric_level_id), threshold_value=rule.threshold_value))
    db.flush()
