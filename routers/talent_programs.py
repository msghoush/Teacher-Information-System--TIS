from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from talent_program_service import (
    TalentProgramError, activate_framework, add_framework_competency, create_competency,
    create_framework_draft, create_program, framework_payload, get_program, list_programs,
    program_payload, remove_framework_competency, reorder_framework_competencies,
    retire_framework, transition_program, update_competency, update_framework_competency,
    update_framework_draft, update_program, upsert_annual_configuration,
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
    status = 404 if exc.code == "not_found" else 409 if exc.code in {"stale_framework", "duplicate_program", "duplicate_competency", "duplicate_membership", "supersession_required"} else 403 if exc.code == "organization_authority_required" else 400
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
    result = framework_payload(row); result["competencies"] = [{"competency_id": m.talent_competency_id, "display_order": m.display_order, "label": m.label, "description": m.description} for m in db.query(models.FrameworkCompetency).filter_by(framework_version_id=row.id).order_by(models.FrameworkCompetency.display_order)]
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
