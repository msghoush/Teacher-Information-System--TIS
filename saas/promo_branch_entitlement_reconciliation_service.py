from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

import models as operational_models
from saas import commercial_authority_service, models, promo_grant_service


@dataclass(frozen=True)
class ReconciliationAction:
    branch_id: int
    branch_name: str
    operational_status: str
    action: str = "create_inactive_branch_entitlement"


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    reason_code: str
    school_group_id: int | None
    workspace_uuid: str
    planned_actions: tuple[ReconciliationAction, ...] = ()
    applied_count: int = 0

    @property
    def safe_to_apply(self) -> bool:
        return self.status in {"ready", "no_changes", "applied"}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "school_group_id": self.school_group_id,
            "workspace_uuid": self.workspace_uuid,
            "planned_actions": [asdict(row) for row in self.planned_actions],
            "planned_action_count": len(self.planned_actions),
            "applied_count": self.applied_count,
        }


def _manual_review(group_id: int | None, workspace_uuid: str, reason: str):
    return ReconciliationResult("manual_review", reason, group_id, workspace_uuid)


def reconcile_promo_branch_entitlements(
    db: Session,
    *,
    school_group_id: int,
    workspace_uuid: str,
    apply: bool = False,
) -> ReconciliationResult:
    normalized_uuid = str(workspace_uuid or "").strip()
    query = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == int(school_group_id),
        operational_models.SchoolGroup.workspace_uuid == normalized_uuid,
    )
    if apply:
        query = query.with_for_update()
    group = query.one_or_none()
    if group is None:
        return _manual_review(school_group_id, normalized_uuid, "workspace_identity_mismatch")

    authority = commercial_authority_service.resolve_commercial_authority(db, group.id)
    if (
        not authority.resolved
        or not authority.access_allowed
        or authority.source != commercial_authority_service.PROMO_GRANT
    ):
        return _manual_review(group.id, normalized_uuid, "promo_commercial_authority_unresolved")
    promo = promo_grant_service.resolve_promo_grant(db, group.id)
    if not promo.active:
        return _manual_review(group.id, normalized_uuid, promo.reason_code)

    tenant_links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.school_group_id == group.id
    ).all()
    if (
        len(tenant_links) != 1
        or tenant_links[0].promo_grant_id != promo.grant_id
        or tenant_links[0].subscription_contract_id is not None
        or tenant_links[0].demo_request_id is not None
    ):
        return _manual_review(group.id, normalized_uuid, "promo_tenant_link_mismatch")
    owner_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.school_group_id == group.id,
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    ).all()
    if len(owner_links) != 1:
        return _manual_review(group.id, normalized_uuid, "promo_owner_mapping_ambiguous")

    workspace_entitlements = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.school_group_id == group.id,
        models.WorkspaceEntitlement.entitlement_type == "promo",
        models.WorkspaceEntitlement.status == "active",
    ).all()
    if (
        len(workspace_entitlements) != 1
        or workspace_entitlements[0].promo_grant_id != promo.grant_id
    ):
        return _manual_review(group.id, normalized_uuid, "promo_workspace_entitlement_mismatch")
    workspace_entitlement = workspace_entitlements[0]

    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == group.id
    ).order_by(operational_models.Branch.id.asc()).all()
    if not branches:
        return _manual_review(group.id, normalized_uuid, "promo_workspace_has_no_branches")
    branch_by_id = {int(row.id): row for row in branches}
    assignments = db.query(models.PromoGrantBranchAssignment).filter(
        models.PromoGrantBranchAssignment.branch_id.in_(tuple(branch_by_id))
    ).all()
    assigned_ids = set()
    for assignment in assignments:
        branch = branch_by_id.get(int(assignment.branch_id))
        if (
            branch is None
            or int(assignment.school_group_id) != group.id
            or int(assignment.promo_grant_id) != int(promo.grant_id)
        ):
            return _manual_review(group.id, normalized_uuid, "promo_branch_assignment_mismatch")
        if int(assignment.branch_id) in assigned_ids:
            return _manual_review(group.id, normalized_uuid, "promo_branch_assignment_ambiguous")
        assigned_ids.add(int(assignment.branch_id))
    if len(assigned_ids) > int(promo.allowed_branches or 0):
        return _manual_review(group.id, normalized_uuid, "promo_branch_assignment_exceeds_grant")

    entitlement_rows = db.query(models.BranchEntitlement).filter(
        models.BranchEntitlement.branch_id.in_(tuple(branch_by_id))
    ).all()
    entitlement_by_branch = {}
    for row in entitlement_rows:
        branch_id = int(row.branch_id)
        if (
            branch_id not in branch_by_id
            or int(row.school_group_id) != group.id
            or branch_id in entitlement_by_branch
        ):
            return _manual_review(group.id, normalized_uuid, "promo_branch_entitlement_ambiguous")
        entitlement_by_branch[branch_id] = row

    actions = []
    for branch in branches:
        branch_id = int(branch.id)
        assigned = branch_id in assigned_ids
        row = entitlement_by_branch.get(branch_id)
        if row is None:
            if assigned:
                return _manual_review(
                    group.id,
                    normalized_uuid,
                    "selected_branch_missing_active_entitlement",
                )
            actions.append(
                ReconciliationAction(
                    branch_id=branch_id,
                    branch_name=str(branch.name or "")[:160],
                    operational_status="active" if bool(branch.status) else "inactive",
                )
            )
            continue
        if int(row.workspace_entitlement_id) != int(workspace_entitlement.id):
            return _manual_review(group.id, normalized_uuid, "promo_branch_entitlement_mismatch")
        mode = str(row.entitlement_mode or "").lower()
        if assigned and mode != "active":
            return _manual_review(group.id, normalized_uuid, "promo_selected_branch_not_active")
        if not assigned and mode != "inactive":
            return _manual_review(group.id, normalized_uuid, "promo_unselected_branch_not_inactive")

    planned = tuple(actions)
    if not planned:
        return ReconciliationResult(
            "no_changes", "promo_branch_entitlements_coherent", group.id, normalized_uuid
        )
    if not apply:
        return ReconciliationResult(
            "ready", "inactive_branch_entitlements_missing", group.id, normalized_uuid, planned
        )
    for action in planned:
        db.add(
            models.BranchEntitlement(
                school_group_id=group.id,
                branch_id=action.branch_id,
                workspace_entitlement_id=workspace_entitlement.id,
                entitlement_mode="inactive",
                reason_code="promo_grant_not_selected_reconciled",
            )
        )
    db.flush()
    return ReconciliationResult(
        "applied",
        "inactive_branch_entitlements_reconciled",
        group.id,
        normalized_uuid,
        planned,
        applied_count=len(planned),
    )
