from dataclasses import dataclass

from sqlalchemy.orm import Session

import models as operational_models
from commercial_entitlements import BranchEntitlementMode
from saas import commercial_validation_service, models, workspace_entitlement_service


RESOLVED = "resolved"
MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class BranchEntitlementResolution:
    resolution_status: str
    reason_code: str
    school_group_id: int | None
    branch_id: int | None
    operationally_active: bool = False
    entitlement_mode: str = ""
    effective_status: str = "manual_review"
    inherits_workspace: bool = False
    workspace_entitlement_id: int | None = None

    @property
    def resolved(self) -> bool:
        return self.resolution_status == RESOLVED


@dataclass(frozen=True)
class BranchEntitlementSummary:
    resolution_status: str
    total_count: int
    active_count: int
    inactive_count: int
    inherited_count: int
    manual_review_count: int


def _manual_review(group_id, branch_id, reason_code: str) -> BranchEntitlementResolution:
    return BranchEntitlementResolution(
        resolution_status=MANUAL_REVIEW,
        reason_code=reason_code,
        school_group_id=group_id,
        branch_id=branch_id,
    )


def resolve_branch_entitlement(
    db: Session,
    branch_id: int,
    *,
    school_group_id: int | None = None,
    workspace_resolution=None,
) -> BranchEntitlementResolution:
    try:
        normalized_branch_id = int(branch_id)
    except (TypeError, ValueError):
        return _manual_review(school_group_id, None, "invalid_branch")
    branch = db.query(operational_models.Branch).filter(
        operational_models.Branch.id == normalized_branch_id
    ).first()
    if branch is None:
        return _manual_review(school_group_id, normalized_branch_id, "missing_branch")
    if school_group_id is not None and branch.school_group_id != int(school_group_id):
        return _manual_review(school_group_id, normalized_branch_id, "branch_workspace_mismatch")
    group_id = branch.school_group_id
    if not group_id:
        return _manual_review(None, normalized_branch_id, "orphan_branch")

    workspace = workspace_resolution or workspace_entitlement_service.resolve_workspace_entitlement(
        db, group_id
    )
    if not workspace.resolved:
        return _manual_review(group_id, normalized_branch_id, "workspace_entitlement_unresolved")

    rows = db.query(models.BranchEntitlement).filter(
        models.BranchEntitlement.branch_id == normalized_branch_id
    ).all()
    if len(rows) > 1:
        return _manual_review(group_id, normalized_branch_id, "ambiguous_branch_entitlement")
    row = rows[0] if rows else None
    if row:
        if row.school_group_id != group_id:
            return _manual_review(group_id, normalized_branch_id, "orphan_branch_entitlement")
        if row.workspace_entitlement_id != workspace.workspace_entitlement_id:
            return _manual_review(group_id, normalized_branch_id, "stale_workspace_entitlement_link")
        try:
            mode = commercial_validation_service.validate_branch_entitlement_mode(
                row.entitlement_mode
            ).value
        except commercial_validation_service.CommercialValidationError:
            return _manual_review(group_id, normalized_branch_id, "invalid_branch_entitlement_mode")
    else:
        mode = BranchEntitlementMode.INHERIT.value

    inherits = mode == BranchEntitlementMode.INHERIT.value
    if mode == BranchEntitlementMode.INACTIVE.value:
        effective_status = "inactive"
        reason_code = str(getattr(row, "reason_code", "") or "commercially_inactive")
    elif not bool(branch.status):
        effective_status = "inactive"
        reason_code = "operational_branch_inactive"
    elif not workspace.active:
        effective_status = "inactive"
        reason_code = "workspace_entitlement_inactive"
    else:
        effective_status = "active"
        reason_code = "inherited_workspace_entitlement" if inherits else "explicit_branch_entitlement"

    return BranchEntitlementResolution(
        resolution_status=RESOLVED,
        reason_code=reason_code,
        school_group_id=group_id,
        branch_id=normalized_branch_id,
        operationally_active=bool(branch.status),
        entitlement_mode=mode,
        effective_status=effective_status,
        inherits_workspace=inherits,
        workspace_entitlement_id=workspace.workspace_entitlement_id,
    )


def summarize_branch_entitlements(db: Session, school_group_id: int) -> BranchEntitlementSummary:
    workspace = workspace_entitlement_service.resolve_workspace_entitlement(db, school_group_id)
    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == school_group_id
    ).order_by(operational_models.Branch.id.asc()).all()
    resolutions = [
        resolve_branch_entitlement(
            db,
            branch.id,
            school_group_id=school_group_id,
            workspace_resolution=workspace,
        )
        for branch in branches
    ]
    manual_review_count = sum(not row.resolved for row in resolutions)
    return BranchEntitlementSummary(
        resolution_status=MANUAL_REVIEW if manual_review_count else RESOLVED,
        total_count=len(resolutions),
        active_count=sum(row.resolved and row.effective_status == "active" for row in resolutions),
        inactive_count=sum(row.resolved and row.effective_status == "inactive" for row in resolutions),
        inherited_count=sum(row.resolved and row.inherits_workspace for row in resolutions),
        manual_review_count=manual_review_count,
    )


def branch_entitlement_summary_label(summary: BranchEntitlementSummary) -> str:
    if summary.manual_review_count:
        return f"{summary.manual_review_count} branch(es) require review"
    return (
        f"{summary.active_count} active / {summary.inactive_count} inactive / "
        f"{summary.inherited_count} inherited"
    )
