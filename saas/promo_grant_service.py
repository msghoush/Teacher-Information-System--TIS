from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

import models as operational_models
from saas import models


RESOLVED = "resolved"
MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class PromoGrantResolution:
    resolution_status: str
    reason_code: str
    school_group_id: int | None
    grant_id: int | None = None
    grant_uuid: str = ""
    plan_id: int | None = None
    plan_code: str = ""
    plan_name: str = ""
    allowed_branches: int | None = None
    allowed_staff_users: int | None = None
    allowed_teachers: int | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    status: str = ""
    active_branch_ids: frozenset[int] = frozenset()

    @property
    def resolved(self) -> bool:
        return self.resolution_status == RESOLVED

    @property
    def active(self) -> bool:
        return self.resolved and self.status == "active"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _manual_review(group_id: int | None, reason: str) -> PromoGrantResolution:
    return PromoGrantResolution(MANUAL_REVIEW, reason, group_id)


def resolve_promo_grant(
    db: Session,
    school_group_id: int,
    *,
    now: datetime | None = None,
) -> PromoGrantResolution:
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        return _manual_review(None, "invalid_school_group")
    current = _utc(now) or datetime.now(UTC)
    rows = db.query(models.PromoGrant).filter(
        models.PromoGrant.school_group_id == group_id,
        models.PromoGrant.status.in_(("active", "expired")),
    ).order_by(models.PromoGrant.id.asc()).all()
    active_rows = [
        row for row in rows
        if str(row.status or "").lower() == "active"
        and (_utc(row.effective_from) is None or current >= _utc(row.effective_from))
        and (_utc(row.effective_to) is None or current < _utc(row.effective_to))
    ]
    if len(active_rows) != 1:
        if not rows:
            return _manual_review(group_id, "missing_promo_grant")
        if len(active_rows) > 1:
            return _manual_review(group_id, "ambiguous_active_promo_grant")
        latest = rows[-1]
        if _utc(latest.effective_to) and current >= _utc(latest.effective_to):
            return PromoGrantResolution(
                RESOLVED,
                "promo_grant_expired",
                group_id,
                grant_id=latest.id,
                grant_uuid=str(latest.grant_uuid or ""),
                plan_id=latest.plan_id,
                plan_code=str(latest.plan_code_snapshot or ""),
                plan_name=str(latest.plan_name_snapshot or ""),
                allowed_branches=int(latest.allowed_branches),
                allowed_staff_users=int(latest.allowed_staff_users),
                allowed_teachers=int(latest.allowed_teachers),
                effective_from=latest.effective_from,
                effective_to=latest.effective_to,
                status="expired",
            )
        return _manual_review(group_id, "promo_grant_not_effective")

    grant = active_rows[0]
    tenant_links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.school_group_id == group_id
    ).all()
    if len(tenant_links) != 1 or tenant_links[0].promo_grant_id != grant.id:
        return _manual_review(group_id, "promo_tenant_link_mismatch")
    assignments = db.query(models.PromoGrantBranchAssignment).filter(
        models.PromoGrantBranchAssignment.promo_grant_id == grant.id,
        models.PromoGrantBranchAssignment.school_group_id == group_id,
    ).all()
    branch_ids = frozenset(int(row.branch_id) for row in assignments)
    if len(branch_ids) > int(grant.allowed_branches):
        return _manual_review(group_id, "promo_branch_assignment_exceeds_grant")
    return PromoGrantResolution(
        RESOLVED,
        "resolved",
        group_id,
        grant_id=grant.id,
        grant_uuid=str(grant.grant_uuid or ""),
        plan_id=grant.plan_id,
        plan_code=str(grant.plan_code_snapshot or ""),
        plan_name=str(grant.plan_name_snapshot or ""),
        allowed_branches=int(grant.allowed_branches),
        allowed_staff_users=int(grant.allowed_staff_users),
        allowed_teachers=int(grant.allowed_teachers),
        effective_from=grant.effective_from,
        effective_to=grant.effective_to,
        status="active",
        active_branch_ids=branch_ids,
    )


def assign_new_branch_if_available(db: Session, branch, *, actor_saas_account_id: int | None = None):
    group = db.get(operational_models.SchoolGroup, int(getattr(branch, "school_group_id", 0) or 0))
    if group is None or str(group.workspace_classification or "") != "customer":
        return None
    grant_resolution = resolve_promo_grant(db, group.id)
    if not grant_resolution.active:
        raise ValueError("Promo branch capacity is unavailable.")
    existing = db.query(models.BranchEntitlement).filter_by(branch_id=branch.id).one_or_none()
    if existing is not None:
        return existing
    assigned_count = db.query(models.PromoGrantBranchAssignment.id).filter(
        models.PromoGrantBranchAssignment.promo_grant_id == grant_resolution.grant_id
    ).count()
    if assigned_count >= int(grant_resolution.allowed_branches or 0):
        raise ValueError("Promo branch capacity has been reached.")
    entitlement = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.promo_grant_id == grant_resolution.grant_id,
        models.WorkspaceEntitlement.status == "active",
    ).one_or_none()
    if entitlement is None:
        raise ValueError("Promo branch entitlement is unavailable.")
    assignment = models.PromoGrantBranchAssignment(
        promo_grant_id=grant_resolution.grant_id,
        school_group_id=group.id,
        branch_id=branch.id,
        branch_identity_snapshot=str(branch.id),
        branch_name_snapshot=str(branch.name or "")[:160],
        assigned_by_saas_account_id=actor_saas_account_id,
        assignment_reason="unused_promo_capacity",
        assigned_at=datetime.now(UTC).replace(tzinfo=None),
    )
    if assignment.assigned_by_saas_account_id is None:
        owner_link = db.query(models.SaaSAccountUserLink).filter(
            models.SaaSAccountUserLink.school_group_id == group.id,
            models.SaaSAccountUserLink.link_type == "tenant_owner",
        ).one_or_none()
        assignment.assigned_by_saas_account_id = getattr(owner_link, "saas_account_id", None)
    if assignment.assigned_by_saas_account_id is None:
        raise ValueError("Promo organization owner mapping is unavailable.")
    row = models.BranchEntitlement(
        school_group_id=group.id,
        branch_id=branch.id,
        workspace_entitlement_id=entitlement.id,
        entitlement_mode="active",
        reason_code="promo_unused_capacity_assigned",
    )
    db.add_all((assignment, row))
    db.flush()
    return row
