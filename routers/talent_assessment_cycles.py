from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import talent_branch_scope as branch_scope
import authorization
import models
from academic_grade import format_section_display
from talent_operational_context import student_identity_metadata
from talent_request_permissions import branch_in_authorized_scope
from talent_classification_service import CLASSIFICATION_LABELS
from talent_results_analytics_service import build_bucket_projection
from talent_analytics_privacy import resolve_privacy_policy_provider
from talent_learning_style_privacy import learning_style_projection, classification_cohort_publishable
from talent_read_batch import read_batch
from talent_student_assessment_service import prime_assessment_batch, roster_start_states
from auth import get_current_user
from dependencies import get_db
from talent_assessment_cycle_service import (
    TalentAssessmentCycleError, close_cycle, create_cycle, cycle_payload,
    current_placements_for_assessment, frozen_population, get_cycle, list_cycles, open_cycle, population_fingerprint,
    population_member_payload, preview_population, reconcile_open_cycle_population,
    update_cycle,
)

router = APIRouter(prefix="/api/talent/assessment-cycles", tags=["Talent Assessment Cycles"])


def _scope(db, user):
    return getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)


def _authorize(request, db, user, key):
    user, denied = authorization.require_any_permission(
        request, db, key, current_user=user, page_key="talent_assessment_cycles"
    )
    group_id = _scope(db, user) if user else None
    if denied:
        return None, None, denied
    if not group_id:
        return user, None, JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    return user, int(group_id), None


def _organization_authorized(user):
    return auth.get_access_scope(user) in {auth.ACCESS_SCOPE_ORGANIZATION, auth.ACCESS_SCOPE_GLOBAL}


def _parse_datetime(value, field, *, required=False):
    if value in (None, "") and not required:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError) as exc:
        raise TalentAssessmentCycleError("invalid_datetime", f"{field} must be an ISO-8601 date-time.") from exc


def _error(exc):
    if exc.code == "not_found":
        status = 404
    elif exc.code in {"stale_cycle", "population_conflict", "invalid_lifecycle"}:
        status = 409
    elif exc.code == "organization_authority_required":
        status = 403
    else:
        status = 400
    return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=status)


def _run(db, work, *, created=False):
    try:
        result = work()
        db.commit()
        return JSONResponse(jsonable_encoder(result), status_code=201 if created else 200)
    except TalentAssessmentCycleError as exc:
        db.rollback()
        return _error(exc)
    except IntegrityError:
        db.rollback()
        return JSONResponse({"detail": "Concurrent or duplicate Cycle change.", "code": "cycle_conflict"}, status_code=409)
    except (TypeError, ValueError):
        db.rollback()
        return JSONResponse({"detail": "Invalid Cycle payload.", "code": "invalid_input"}, status_code=400)


def _visible_branch_ids(db, user):
    # Accessible Branches within the active global Branch ceiling (Batch 1 closure).
    return branch_scope.visible_branch_ids(db, user)


def _student_names(db, group_id, student_ids):
    rows = db.query(models.Student).filter(
        models.Student.school_group_id == group_id,
        models.Student.id.in_(student_ids or [-1]),
    ).all()
    return {row.id: {"first_name": row.first_name, "father_name": row.father_name, "last_name": row.last_name,
                     "student_name": " ".join(filter(None, (row.first_name, row.father_name, row.last_name)))} for row in rows}


def _branch_names(db, group_id, branch_ids):
    return {row.id: row.name for row in db.query(models.Branch).filter(
        models.Branch.school_group_id == group_id,
        models.Branch.id.in_(branch_ids or [-1]),
    ).all()}


@router.post("")
def cycles_create(request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.manage")
    if denied:
        return denied
    return _run(db, lambda: cycle_payload(create_cycle(
        db, school_group_id=group_id, program_id=int(payload.get("program_id")),
        academic_year_id=int(payload.get("academic_year_id")),
        framework_version_id=int(payload.get("framework_version_id")),
        title=payload.get("title"), description=payload.get("description"),
        population_effective_at=_parse_datetime(payload.get("population_effective_at"), "population_effective_at"),
        actor=user,
    ), include_integrity=False), created=True)


@router.get("")
def cycles_list(request: Request, program_id: int | None = Query(None), academic_year_id: int | None = Query(None), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view")
    if denied:
        return denied
    return [cycle_payload(row, include_integrity=False) for row in list_cycles(
        db, school_group_id=group_id, program_id=program_id, academic_year_id=academic_year_id
    )]


@router.get("/{cycle_id}")
def cycles_read(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    _, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view")
    if denied:
        return denied
    try:
        return cycle_payload(get_cycle(db, school_group_id=group_id, cycle_id=cycle_id), include_integrity=False)
    except TalentAssessmentCycleError as exc:
        return _error(exc)


@router.patch("/{cycle_id}")
def cycles_update(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.manage")
    if denied:
        return denied
    effective_at = "__unchanged__"
    if "population_effective_at" in payload:
        effective_at = _parse_datetime(payload.get("population_effective_at"), "population_effective_at")
    return _run(db, lambda: cycle_payload(update_cycle(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        title=payload.get("title") if "title" in payload else None,
        description=payload.get("description") if "description" in payload else None,
        population_effective_at=effective_at, actor=user,
    ), include_integrity=False))


@router.get("/{cycle_id}/eligible-students")
def cycles_eligible_students(cycle_id: int, request: Request,
                            branch_id: int | None = Query(None, gt=0),
                            search: str | None = Query(None, max_length=120),
                            grade_level: str | None = Query(None, max_length=8),
                            section_name: str | None = Query(None, max_length=20),
                            assessment_state: str | None = Query(None, max_length=32),
                            classification: str | None = Query(None, max_length=32),
                            db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Current assessable Students for an Evaluation context (ADR 0035).

    This is live Academic Placement eligibility, not a frozen roster and not a
    lifecycle gate. Historical Placement context is captured only when an
    Assessment is actually started.
    """
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessments.view")
    if denied:
        return denied
    try:
        cycle = get_cycle(db, school_group_id=group_id, cycle_id=cycle_id)
        population = current_placements_for_assessment(db, cycle=cycle, effective_at=datetime.utcnow())
    except TalentAssessmentCycleError as exc:
        return _error(exc)
    organization = branch_scope.branch_scope_unrestricted(user)
    if not organization:
        visible = _visible_branch_ids(db, user)
        population = [row for row in population if row["branch_id"] in visible]
    if branch_id is not None:
        # Explicit Branch scope (the Talent workspace defaults to the global active
        # Branch). Authorized by the same backend authority as every other Branch
        # filter: never a Branch outside the actor's tenant/authorized set.
        if not branch_in_authorized_scope(db, user, group_id, branch_id):
            return JSONResponse({"detail": "Branch is outside your authorized scope.", "code": "invalid_filter"}, status_code=403)
        population = [row for row in population if row["branch_id"] == branch_id]
    # Stable authorized metadata precedes search/state/Classification filters.
    # Selecting a protected cohort must not remove options or reveal its shape.
    filter_options = {
        "grades": sorted({str(row['grade_level']) for row in population if row.get('grade_level')}),
        "sections": sorted({str(row['section_name']) for row in population
                            if row.get('section_name') and (not grade_level or row.get('grade_level') == grade_level)}),
    }
    names = _student_names(db, group_id, [row["student_id"] for row in population])
    identity_metadata = student_identity_metadata(db, group_id, [row["student_id"] for row in population])
    assessments = db.query(models.TalentStudentAssessment).filter(
        models.TalentStudentAssessment.school_group_id == group_id,
        func.coalesce(models.TalentStudentAssessment.evaluation_context_cycle_id,
                      models.TalentStudentAssessment.cycle_id) == cycle.id,
        models.TalentStudentAssessment.is_current.is_(True),
        models.TalentStudentAssessment.student_id.in_([row["student_id"] for row in population] or [-1]),
    ).order_by(models.TalentStudentAssessment.id).all()
    assessment_by_student = {row.student_id: row for row in assessments}
    classified_by_student = {}
    def state_for(student_id):
        return getattr(assessment_by_student.get(student_id), "status", "not_started")
    normalized_search = (search or "").strip().lower()
    valid_states = {"not_started", "in_progress", "completed", "incomplete", "insufficient_evidence"}
    if assessment_state and assessment_state not in valid_states:
        return JSONResponse({"detail": "assessment_state is not recognized.", "code": "invalid_filter"}, status_code=400)
    if classification and classification not in CLASSIFICATION_LABELS:
        return JSONResponse({"detail": "classification is not recognized.", "code": "invalid_filter"}, status_code=400)
    # Classification is intentionally not re-derived in the browser.  The
    # roster can only narrow to a classification that the authoritative
    # assessment projection supplied; unavailable/non-completed rows never
    # satisfy this filter.
    completed = [row for row in assessment_by_student.values() if row.status == "completed"]
    from talent_classification_service import assessment_classification
    with read_batch(db):
        prime_assessment_batch(db, completed)
        classified_by_student = {
            row.student_id: result.get("classification")
            for row in completed
            if (result := assessment_classification(db, row)) and result.get("available")
        }
    population = [row for row in population if (
        (not grade_level or row.get("grade_level") == grade_level)
        and (not section_name or row.get("section_name") == section_name)
        and (not normalized_search or normalized_search in " ".join(str(names.get(row["student_id"], {}).get(key, "")) for key in ("first_name", "father_name", "last_name", "student_name")).lower())
        and (not assessment_state or state_for(row["student_id"]) == assessment_state)
    )]
    policy = resolve_privacy_policy_provider()
    raw_base = {label: 0 for label in CLASSIFICATION_LABELS}
    for member in population:
        label = classified_by_student.get(member["student_id"])
        if label in raw_base:
            raw_base[label] += 1
    base_projection = build_bucket_projection(
        name="student_assessment_classification_scope", raw_counts=raw_base, policy=policy,
    ) if policy is not None else {"state": "restricted"}
    population = [row for row in population if not classification or classified_by_student.get(row["student_id"]) == classification]
    raw_classification = {label: 0 for label in CLASSIFICATION_LABELS}
    for row in population:
        label = classified_by_student.get(row['student_id'])
        if label in raw_classification:
            raw_classification[label] += 1
    branches = _branch_names(db, group_id, [row["branch_id"] for row in population])
    school_group = db.get(models.SchoolGroup, group_id)
    workspace_uuid = school_group.workspace_uuid if school_group else None
    # One backend predicate shared with POST /api/talent/assessments: the client
    # renders Start only when can_start is true and otherwise shows the bounded reason.
    with read_batch(db):
        start_states = roster_start_states(
            db, cycle=cycle,
            grades_by_student={row["student_id"]: row.get("grade_level") for row in population},
            students_with_current_assessment=set(assessment_by_student),
        )
    members = [
        {
            **row,
            "can_start": start_states[row["student_id"]][0],
            "start_block_code": start_states[row["student_id"]][1],
            "start_block_reason": start_states[row["student_id"]][2],
            **names.get(row["student_id"], {}),
            # Acceptance B: presentation-only Student identity metadata (the canonical
            # Student-domain Learning Style) from the shared operational-context helper.
            **identity_metadata.get(row["student_id"], {}),
            "branch_name": branches.get(row["branch_id"]),
            # ADR 0045: bounded presentation projection - the canonical
            # grade_level/section_name above remain unchanged.
            "section_display": format_section_display(workspace_uuid, row.get("grade_level"), row.get("section_name")),
        }
        for row in population
    ]
    # Learning Style is a governed eight-category learner-profile distribution
    # over this exact, already-authorized roster population.  It is not the
    # Students-page organization distribution and is never calculated by JS.
    style_rows = [{"learning_style": identity_metadata.get(row["student_id"], {}).get("learning_style")} for row in population]
    classification_distribution = build_bucket_projection(
        name="student_assessment_classification",
        raw_counts={label: raw_classification.get(label, 0) for label in CLASSIFICATION_LABELS},
        policy=policy,
    ) if policy is not None else {"state": "restricted", "total": {"state": "restricted", "value": None}, "buckets": []}
    if not classification_cohort_publishable(base_projection, classification):
        classification_distribution = {"state": "restricted", "total": {"state": "restricted", "value": None}, "buckets": []}
    return jsonable_encoder({
        "cycle_id": cycle.id,
        "eligibility_state": "live_academic_placement",
        "scope": "organization" if organization else "authorized_branches",
        "is_filtered": not organization,
        "count": len(members),
        "members": members,
        "filter_options": filter_options,
        "insights": {
            "learning_style": learning_style_projection(
                style_rows, classification=classification, classification_projection=base_projection,
                filtered_classification_projection=classification_distribution,
            ),
            "classification": classification_distribution,
        },
    })


@router.get("/{cycle_id}/population/preview")
def cycles_preview(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view_population")
    if denied:
        return denied
    try:
        cycle, population = preview_population(db, school_group_id=group_id, cycle_id=cycle_id)
    except TalentAssessmentCycleError as exc:
        return _error(exc)
    organization = branch_scope.branch_scope_unrestricted(user)
    if not organization:
        visible = _visible_branch_ids(db, user)
        population = [row for row in population if row["branch_id"] in visible]
    names = _student_names(db, group_id, [row["student_id"] for row in population])
    branches = _branch_names(db, group_id, [row["branch_id"] for row in population])
    members = [{**row, **names.get(row["student_id"], {}), "branch_name": branches.get(row["branch_id"])} for row in population]
    result = {"cycle_id": cycle.id, "population_state": "preview", "scope": "organization" if organization else "authorized_branches", "is_filtered": not organization, "count": len(members), "members": members}
    if organization:
        result["population_fingerprint"] = population_fingerprint(cycle, population)
    return jsonable_encoder(result)


@router.post("/{cycle_id}/open")
def cycles_open(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.govern")
    if denied:
        return denied
    return _run(db, lambda: cycle_payload(open_cycle(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        organization_authorized=_organization_authorized(user), actor=user,
    )))


@router.post("/{cycle_id}/close")
def cycles_close(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.govern")
    if denied:
        return denied
    return _run(db, lambda: cycle_payload(close_cycle(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        organization_authorized=_organization_authorized(user), actor=user,
    )))


@router.post("/{cycle_id}/population/synchronize")
def cycles_synchronize_population(cycle_id: int, request: Request, payload: dict = Body(...), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.govern")
    if denied:
        return denied
    return _run(db, lambda: _sync_payload(*reconcile_open_cycle_population(
        db, school_group_id=group_id, cycle_id=cycle_id,
        expected_revision=int(payload.get("expected_revision")),
        organization_authorized=_organization_authorized(user), actor=user,
    )))


def _sync_payload(cycle, additions):
    return {"cycle": cycle_payload(cycle), "added_count": len(additions)}


@router.get("/{cycle_id}/population")
def cycles_population(cycle_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, group_id, denied = _authorize(request, db, current_user, "talent_assessment_cycles.view_population")
    if denied:
        return denied
    # ADR 0033 resolved condition: opening an existing Open Cycle's population
    # must additively reconcile eligible-but-missing members before the read,
    # so Students already eligible before a synchronization gap (e.g. placed
    # before this reconciliation was deployed) are not permanently hidden.
    # Reconciliation itself requires organization authority (ADR 0033); a
    # branch-scoped viewer simply reads the current stored population, which
    # organization-authorized synchronization keeps up to date for everyone.
    if _organization_authorized(user):
        try:
            precheck = get_cycle(db, school_group_id=group_id, cycle_id=cycle_id)
        except TalentAssessmentCycleError as exc:
            return _error(exc)
        if precheck.status == "open":
            try:
                reconcile_open_cycle_population(
                    db, school_group_id=group_id, cycle_id=cycle_id,
                    expected_revision=precheck.revision,
                    organization_authorized=True, actor=user,
                )
                db.commit()
            except TalentAssessmentCycleError:
                db.rollback()
    try:
        cycle, rows = frozen_population(db, school_group_id=group_id, cycle_id=cycle_id)
    except TalentAssessmentCycleError as exc:
        return _error(exc)
    organization = branch_scope.branch_scope_unrestricted(user)
    if not organization:
        visible = _visible_branch_ids(db, user)
        rows = [row for row in rows if row.branch_id in visible]
    names = _student_names(db, group_id, [row.student_id for row in rows])
    branches = _branch_names(db, group_id, [row.branch_id for row in rows])
    members = [{**population_member_payload(row), **names.get(row.student_id, {}), "branch_name": branches.get(row.branch_id)} for row in rows]
    result = {"cycle_id": cycle.id, "population_state": "frozen", "scope": "organization" if organization else "authorized_branches", "is_filtered": not organization, "count": len(members), "members": members}
    if organization:
        result["population_count"] = cycle.population_count
        result["population_fingerprint"] = cycle.population_fingerprint
    return result
