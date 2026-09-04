from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import auth
import authorization
import models
from auth import get_current_user
from dependencies import get_db
from talent_learner_profile_service import TalentLearnerProfileError, build_learner_profile

router = APIRouter(prefix="/api/talent/learner-profiles", tags=["Talent Learner Profiles"])


@router.get("/{student_id}")
def learner_profile(student_id: int, request: Request, include_competencies: bool = Query(True), include_timeline: bool = Query(True), db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user, denied = authorization.require_any_permission(request, db, "talent_learner_profiles.view", current_user=current_user, page_key="talent_learner_profiles")
    if denied:
        return denied
    group_id = getattr(user, "scope_school_group_id", None) or auth.get_user_school_group_id(db, user)
    if not group_id:
        return JSONResponse({"detail": "Select an organization scope."}, status_code=403)
    candidate_visible = auth.has_permission(db, user, "talent_review_candidates.view", school_group_id=group_id)
    identification_visible = auth.has_permission(db, user, "talent_official_identifications.view", school_group_id=group_id)
    educator_visible = auth.has_permission(db, user, "talent_educator_inputs.view", school_group_id=group_id)
    visible_branches = None if auth.can_access_all_branches(user) else {
        row[0] for row in auth.get_accessible_branch_query(db, user).with_entities(models.Branch.id).all()
    }
    try:
        return build_learner_profile(db, school_group_id=int(group_id), student_id=student_id,
                                     visible_branch_ids=visible_branches, include_competencies=include_competencies,
                                     include_timeline=include_timeline,
                                     include_review_candidates=candidate_visible,
                                     include_identifications=identification_visible,
                                     include_educator_inputs=educator_visible)
    except TalentLearnerProfileError as exc:
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=404)