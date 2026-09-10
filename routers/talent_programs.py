from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
import branding_storage
import models
from auth import get_current_user
from dependencies import get_db
from planning_scope_service import list_operational_planning_grades, list_operational_planning_sections
from talent_program_service import (
    TalentProgramError, activate_framework, add_framework_competency, create_competency,
    add_rubric_level, configure_kpi, configure_review_candidate_policy,
    create_framework_draft, create_program, framework_payload, get_program, list_programs,
    get_framework_configuration,
    program_payload, remove_framework_competency, remove_program_logo, reorder_framework_competencies,
    remove_descriptor, remove_kpi, remove_review_candidate_policy, remove_rubric_level,
    reorder_rubric_levels, set_program_logo,
    retire_framework, transition_program, update_competency, update_framework_competency,
    update_framework_draft, update_program, update_rubric_level, upsert_annual_configuration,
    upsert_descriptor, upsert_rubric,
)

router = APIRouter(prefix="/api/talent/programs", tags=["Talent Programs"])


def _scope(db, user): return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, *keys):
    user, denied = authorization.require_any_permission(request, db, *keys, current_user=user, page_key="talent_programs")
    group_id = _scope(db, user) if user else None
    if denied: return None, None, denied
    if not group_id: return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _organization_authorized(user): return auth.get_access_scope(user) in {auth.ACCESS_SCOPE_ORGANIZATION, auth.ACCESS_SCOPE_GLOBAL}


def _error(exc):
    status = 404 if exc.code == "not_found" else 409 if exc.code in {"stale_framework", "duplicate_program", "duplicate_competency", "duplicate_membership", "supersession_required", "duplicate_level", "duplicate_order", "duplicate_rule"} else 403 if exc.code == "organization_authority_required" else 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _run(db, fn, *, created=False):
    try:
        result = fn(); db.commit()
        return JSONResponse(jsonable_encoder(result), status_code=201 if created else 200)
    except TalentProgramError as exc: db.rollback(); return _error(exc)
    except IntegrityError: db.rollback(); return JSONResponse({"detail": "Concurrent or duplicate Talent configuration change.", "code": "configuration_conflict"}, status_code=409)
    except (TypeError, ValueError): db.rollback(); return JSONResponse({"detail": "Invalid Talent configuration payload.", "code": "invalid_input"}, status_code=400)


@router.get("")
def programs_list(request: Request, search: str = Query(""), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    return denied or [program_payload(row) for row in list_programs(db, school_group_id=group_id, search=search)]


def _grade_sort_key(value: str):
    if value == "KG":
        return (0, 0)
    try:
        return (1, int(value))
    except (TypeError, ValueError):
        return (2, 0)


@router.get("/planning-grades")
def programs_planning_grades(request: Request, academic_year_id: int = Query(...), branch_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Real Grades configured in Planning for the requested Academic Year (optionally one Branch).

    Reuses ``planning_scope_service.list_operational_planning_grades`` (the same
    Current/New PlanningSection authority Subject Scheduling and Students already
    use) rather than a fabricated or blanket KG-12 catalog. Both Program setup
    (organization+Academic-Year scoped, no Branch) and the shared Talent context
    filter (optionally one Branch) call this same endpoint. With no Branch
    selected, this returns the union of configured Grades across every Branch the
    actor may access for that Academic Year.
    """
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.view", "talent_analytics.view")
    if denied:
        return denied
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=group_id).one_or_none()
    if year is None:
        return JSONResponse({"detail": "Academic Year is not available in your organization.", "code": "not_found"}, status_code=404)
    if branch_id is not None:
        branch = db.query(models.Branch).filter_by(id=branch_id, school_group_id=group_id).one_or_none()
        if branch is None or not auth.can_access_branch(db, user, branch_id):
            return JSONResponse({"detail": "Branch is not available in your authorized scope.", "code": "not_found"}, status_code=404)
        return list_operational_planning_grades(db, branch_id, academic_year_id)
    if auth.can_access_all_branches(user):
        branch_ids = [row[0] for row in db.query(models.Branch.id).filter_by(school_group_id=group_id).all()]
    else:
        branch_ids = [row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()]
    combined = set()
    for one_branch_id in branch_ids:
        combined.update(list_operational_planning_grades(db, one_branch_id, academic_year_id))
    return sorted(combined, key=_grade_sort_key)


@router.get("/planning-sections")
def programs_planning_sections(request: Request, academic_year_id: int = Query(...), branch_id: int = Query(...), grade_level: str = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Operational Planning sections for one authorized Branch/Year/Grade."""
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.view", "talent_analytics.view")
    if denied:
        return denied
    year = db.query(models.AcademicYear).filter_by(id=academic_year_id, school_group_id=group_id).one_or_none()
    branch = db.query(models.Branch).filter_by(id=branch_id, school_group_id=group_id).one_or_none()
    if year is None or branch is None or not auth.can_access_branch(db, user, branch_id):
        return JSONResponse({"detail": "Planning context is not available in your authorized scope.", "code": "not_found"}, status_code=404)
    normalized = str(grade_level or "").strip().upper()
    items = [row for row in list_operational_planning_sections(db, branch_id, academic_year_id)
             if str(row.grade_level or "").strip().upper() == normalized]
    return [{"id": row.id, "section_name": row.section_name} for row in items]


@router.post("")
def programs_create(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: program_payload(create_program(db, school_group_id=group_id, name=payload.get("name"), description=payload.get("description"), actor=user)), created=True)


@router.get("/{program_id}")
def programs_read(program_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    row = get_program(db, group_id, program_id)
    return program_payload(row) if row else JSONResponse({"detail": "Talent Program was not found.", "code": "not_found"}, status_code=404)


@router.patch("/{program_id}")
def programs_update(program_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: program_payload(update_program(db, school_group_id=group_id, program_id=program_id, name=payload.get("name") if "name" in payload else None, description=payload.get("description") if "description" in payload else None, actor=user)))


@router.post("/{program_id}/logo")
async def program_logo_upload(program_id: int, request: Request, logo: UploadFile = File(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Upload or replace the Program Identity logo.

    Reuses ``branding_storage.py``'s existing safe-image/SVG validation and
    atomic write pattern at a Program-scoped path; never a parallel upload
    subsystem. One action covers both first upload and replace.
    """
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    existing = get_program(db, group_id, program_id)
    if existing is None:
        return JSONResponse({"detail": "Talent Program was not found.", "code": "not_found"}, status_code=404)
    if existing.status == "retired":
        return JSONResponse({"detail": "A retired Talent Program cannot change its Program Identity logo.", "code": "retired_program"}, status_code=400)
    file_bytes = await logo.read()
    try:
        upload_info = branding_storage.validate_program_logo_upload(file_bytes, logo.filename)
    except branding_storage.BrandingStorageError as exc:
        return JSONResponse({"detail": str(exc), "code": "invalid_logo"}, status_code=400)

    def work():
        relative_path = branding_storage.write_program_logo_file(
            file_bytes, school_group_id=group_id, program_id=program_id, extension=upload_info.extension,
        )
        row, old_logo_path = set_program_logo(
            db, school_group_id=group_id, program_id=program_id,
            logo_path=relative_path, content_type=upload_info.content_type, actor=user,
        )
        if old_logo_path and old_logo_path != relative_path:
            branding_storage.delete_program_logo_file(old_logo_path, school_group_id=group_id, program_id=program_id)
        return program_payload(row)
    return _run(db, work)


@router.delete("/{program_id}/logo")
def program_logo_remove(program_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied

    def work():
        row, old_logo_path = remove_program_logo(db, school_group_id=group_id, program_id=program_id, actor=user)
        if old_logo_path:
            branding_storage.delete_program_logo_file(old_logo_path, school_group_id=group_id, program_id=program_id)
        return program_payload(row)
    return _run(db, work)


@router.post("/{program_id}/lifecycle/{target_status}")
def programs_lifecycle(program_id: int, target_status: str, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.govern")
    if denied: return denied
    if not _organization_authorized(user): return _error(TalentProgramError("organization_authority_required", "Organization authority is required for Program lifecycle governance."))
    return _run(db, lambda: program_payload(transition_program(db, school_group_id=group_id, program_id=program_id, target_status=target_status, actor=user)))


@router.put("/{program_id}/academic-years/{academic_year_id}")
def annual_upsert(program_id: int, academic_year_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row = upsert_annual_configuration(db, school_group_id=group_id, program_id=program_id, academic_year_id=academic_year_id,
            is_enabled=payload.get("is_enabled", True), eligible_grade_levels=payload.get("eligible_grade_levels"), actor=user)
        return {"id": row.id, "program_id": row.program_id, "academic_year_id": row.academic_year_id, "is_enabled": row.is_enabled, "eligible_grade_levels": row.eligible_grade_levels_csv.split(",")}
    return _run(db, work)


@router.get("/{program_id}/academic-years")
def annual_list(program_id: int, request: Request, academic_year_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    if get_program(db, group_id, program_id) is None: return JSONResponse({"detail": "Talent Program was not found.", "code": "not_found"}, status_code=404)
    query = db.query(models.TalentProgramAcademicYearConfiguration).filter_by(school_group_id=group_id, program_id=program_id)
    if academic_year_id is not None: query = query.filter_by(academic_year_id=academic_year_id)
    return [{"id": r.id, "academic_year_id": r.academic_year_id, "is_enabled": r.is_enabled, "eligible_grade_levels": r.eligible_grade_levels_csv.split(",")} for r in query.order_by(models.TalentProgramAcademicYearConfiguration.academic_year_id)]


@router.post("/{program_id}/frameworks")
def frameworks_create(program_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: framework_payload(create_framework_draft(db, school_group_id=group_id, program_id=program_id,
        title=payload.get("title"), summary=payload.get("summary"), supersedes_framework_version_id=payload.get("supersedes_framework_version_id"), clone_from_id=payload.get("clone_from_id"), actor=user)), created=True)


@router.get("/{program_id}/frameworks")
def frameworks_list(program_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    if get_program(db, group_id, program_id) is None: return JSONResponse({"detail": "Talent Program was not found.", "code": "not_found"}, status_code=404)
    rows = db.query(models.TalentProgramFrameworkVersion).filter_by(school_group_id=group_id, program_id=program_id).order_by(models.TalentProgramFrameworkVersion.version_number).all()
    return [framework_payload(row) for row in rows]


@router.get("/{program_id}/frameworks/{framework_id}")
def frameworks_read(program_id: int, framework_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    row = db.query(models.TalentProgramFrameworkVersion).filter_by(id=framework_id, program_id=program_id, school_group_id=group_id).one_or_none()
    if row is None: return JSONResponse({"detail": "Framework Version was not found.", "code": "not_found"}, status_code=404)
    result = framework_payload(row); result["competencies"] = [{"id": m.id, "competency_id": m.talent_competency_id, "display_order": m.display_order, "label": m.label, "description": m.description} for m in db.query(models.FrameworkCompetency).filter_by(framework_version_id=row.id).order_by(models.FrameworkCompetency.display_order)]
    return result


@router.patch("/{program_id}/frameworks/{framework_id}")
def frameworks_update(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: framework_payload(update_framework_draft(db, school_group_id=group_id, program_id=program_id,
        framework_id=framework_id, expected_revision=int(payload.get("expected_revision")), title=payload.get("title") if "title" in payload else None,
        summary=payload.get("summary") if "summary" in payload else None, supersedes_framework_version_id=payload.get("supersedes_framework_version_id"), actor=user)))


@router.post("/{program_id}/frameworks/{framework_id}/activate")
def frameworks_activate(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.govern")
    if denied: return denied
    return _run(db, lambda: framework_payload(activate_framework(db, school_group_id=group_id, program_id=program_id,
        framework_id=framework_id, expected_revision=int(payload.get("expected_revision")), expected_fingerprint=payload.get("expected_fingerprint"),
        organization_authorized=_organization_authorized(user), actor=user)))


@router.post("/{program_id}/frameworks/{framework_id}/retire")
def frameworks_retire(program_id: int, framework_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.govern")
    if denied: return denied
    return _run(db, lambda: framework_payload(retire_framework(db, school_group_id=group_id, program_id=program_id,
        framework_id=framework_id, organization_authorized=_organization_authorized(user), actor=user)))


@router.post("/{program_id}/competencies")
def competencies_create(program_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"id": (row := create_competency(db, school_group_id=group_id, program_id=program_id, code=payload.get("code"), name=payload.get("name"), description=payload.get("description"), actor=user)).id, "code": row.code, "name": row.name, "description": row.description, "status": row.status}, created=True)


@router.get("/{program_id}/competencies")
def competencies_list(program_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    return [{"id": r.id, "code": r.code, "name": r.name, "description": r.description, "status": r.status} for r in db.query(models.TalentCompetency).filter_by(school_group_id=group_id, program_id=program_id).order_by(models.TalentCompetency.code)]


@router.get("/{program_id}/competencies/{competency_id}")
def competencies_read(program_id: int, competency_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    row = db.query(models.TalentCompetency).filter_by(id=competency_id, school_group_id=group_id, program_id=program_id).one_or_none()
    return {"id": row.id, "code": row.code, "name": row.name, "description": row.description, "status": row.status} if row else JSONResponse({"detail": "Talent Competency was not found.", "code": "not_found"}, status_code=404)


@router.patch("/{program_id}/competencies/{competency_id}")
def competencies_update(program_id: int, competency_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row = update_competency(db, school_group_id=group_id, program_id=program_id, competency_id=competency_id,
            name=payload.get("name") if "name" in payload else None, description=payload.get("description") if "description" in payload else None, status=payload.get("status"), actor=user)
        return {"id": row.id, "code": row.code, "name": row.name, "description": row.description, "status": row.status}
    return _run(db, work)


@router.post("/{program_id}/frameworks/{framework_id}/competencies")
def framework_competencies_add(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = add_framework_competency(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id,
            competency_id=int(payload.get("competency_id")), expected_revision=int(payload.get("expected_revision")), label=payload.get("label"), description=payload.get("description"), actor=user)
        return {"id": row.id, "competency_id": row.talent_competency_id, "display_order": row.display_order, "label": row.label, "description": row.description, "framework_revision": framework.revision, "framework_fingerprint": framework.semantic_fingerprint}
    return _run(db, work, created=True)


@router.patch("/{program_id}/frameworks/{framework_id}/competencies/{competency_id}")
def framework_competencies_update(program_id: int, framework_id: int, competency_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = update_framework_competency(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, competency_id=competency_id,
            expected_revision=int(payload.get("expected_revision")), label=payload.get("label") if "label" in payload else None, description=payload.get("description") if "description" in payload else None, actor=user)
        return {"id": row.id, "competency_id": row.talent_competency_id, "display_order": row.display_order, "label": row.label, "description": row.description, "framework_revision": framework.revision}
    return _run(db, work)


@router.put("/{program_id}/frameworks/{framework_id}/competencies/order")
def framework_competencies_reorder(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": reorder_framework_competencies(db, school_group_id=group_id, program_id=program_id,
        framework_id=framework_id, competency_ids=[int(v) for v in payload.get("competency_ids", [])], expected_revision=int(payload.get("expected_revision")), actor=user)[1].revision})


@router.delete("/{program_id}/frameworks/{framework_id}/competencies/{competency_id}")
def framework_competencies_remove(program_id: int, framework_id: int, competency_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": remove_framework_competency(db, school_group_id=group_id, program_id=program_id,
        framework_id=framework_id, competency_id=competency_id, expected_revision=expected_revision, actor=user).revision})


@router.get("/{program_id}/frameworks/{framework_id}/configuration")
def framework_configuration_read(program_id: int, framework_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_programs.view")
    if denied: return denied
    try: return get_framework_configuration(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id)
    except TalentProgramError as exc: return _error(exc)


@router.put("/{program_id}/frameworks/{framework_id}/rubric")
def rubric_upsert(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = upsert_rubric(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, expected_revision=int(payload.get("expected_revision")), name=payload.get("name"), description=payload.get("description"), actor=user)
        return {"id": row.id, "name": row.name, "description": row.description, "framework_revision": framework.revision, "framework_fingerprint": framework.semantic_fingerprint}
    return _run(db, work)


@router.post("/{program_id}/frameworks/{framework_id}/rubric/levels")
def rubric_level_add(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = add_rubric_level(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, expected_revision=int(payload.get("expected_revision")), code=payload.get("code"), label=payload.get("label"), description=payload.get("description"), numeric_value=payload.get("numeric_value"), display_order=payload.get("display_order"), actor=user)
        return {"id": row.id, "code": row.code, "label": row.label, "description": row.description, "display_order": row.display_order, "numeric_value": row.numeric_value, "framework_revision": framework.revision}
    return _run(db, work, created=True)


@router.patch("/{program_id}/frameworks/{framework_id}/rubric/levels/{level_id}")
def rubric_level_update(program_id: int, framework_id: int, level_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = update_rubric_level(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, level_id=level_id, expected_revision=int(payload.get("expected_revision")), label=payload.get("label") if "label" in payload else None, description=payload.get("description") if "description" in payload else None, numeric_value=payload.get("numeric_value", "__unchanged__"), actor=user)
        return {"id": row.id, "label": row.label, "description": row.description, "numeric_value": row.numeric_value, "framework_revision": framework.revision}
    return _run(db, work)


@router.put("/{program_id}/frameworks/{framework_id}/rubric/levels/order")
def rubric_levels_reorder(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": reorder_rubric_levels(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, level_ids=[int(v) for v in payload.get("level_ids", [])], expected_revision=int(payload.get("expected_revision")), actor=user).revision})


@router.delete("/{program_id}/frameworks/{framework_id}/rubric/levels/{level_id}")
def rubric_level_remove(program_id: int, framework_id: int, level_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": remove_rubric_level(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, level_id=level_id, expected_revision=expected_revision, actor=user).revision})


@router.put("/{program_id}/frameworks/{framework_id}/rubric/descriptors")
def descriptor_upsert(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = upsert_descriptor(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, framework_competency_id=int(payload.get("framework_competency_id")), rubric_level_id=int(payload.get("rubric_level_id")), expected_revision=int(payload.get("expected_revision")), descriptor=payload.get("descriptor"), actor=user)
        return {"id": row.id, "framework_competency_id": row.framework_competency_id, "rubric_level_id": row.rubric_level_id, "descriptor": row.descriptor, "framework_revision": framework.revision}
    return _run(db, work)


@router.delete("/{program_id}/frameworks/{framework_id}/rubric/descriptors/{descriptor_id}")
def descriptor_remove(program_id: int, framework_id: int, descriptor_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": remove_descriptor(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, descriptor_id=descriptor_id, expected_revision=expected_revision, actor=user).revision})


@router.put("/{program_id}/frameworks/{framework_id}/kpi")
def kpi_configure(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = configure_kpi(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, expected_revision=int(payload.get("expected_revision")), is_enabled=payload.get("is_enabled", True), result_scale_min=payload.get("result_scale_min"), result_scale_max=payload.get("result_scale_max"), interpretation=payload.get("interpretation"), components=payload.get("components"), calculation_method=payload.get("calculation_method", "weighted_level_average"), actor=user)
        return {"id": row.id, "is_enabled": row.is_enabled, "calculation_method": row.calculation_method, "result_scale_min": row.result_scale_min, "result_scale_max": row.result_scale_max, "interpretation": row.interpretation, "framework_revision": framework.revision, "framework_fingerprint": framework.semantic_fingerprint}
    return _run(db, work)


@router.delete("/{program_id}/frameworks/{framework_id}/kpi")
def kpi_remove(program_id: int, framework_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": remove_kpi(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, expected_revision=expected_revision, actor=user).revision})


@router.put("/{program_id}/frameworks/{framework_id}/review-candidate-policy")
def candidate_policy_configure(program_id: int, framework_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    def work():
        row, framework = configure_review_candidate_policy(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, expected_revision=int(payload.get("expected_revision")), is_enabled=payload.get("is_enabled", True), match_mode=payload.get("match_mode"), description=payload.get("description"), rules=payload.get("rules"), actor=user)
        return {"id": row.id, "is_enabled": row.is_enabled, "match_mode": row.match_mode, "description": row.description, "framework_revision": framework.revision, "framework_fingerprint": framework.semantic_fingerprint}
    return _run(db, work)


@router.delete("/{program_id}/frameworks/{framework_id}/review-candidate-policy")
def candidate_policy_remove(program_id: int, framework_id: int, request: Request, expected_revision: int = Query(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_programs.manage")
    if denied: return denied
    return _run(db, lambda: {"framework_revision": remove_review_candidate_policy(db, school_group_id=group_id, program_id=program_id, framework_id=framework_id, expected_revision=expected_revision, actor=user).revision})
