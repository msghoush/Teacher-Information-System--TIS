from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

import models as operational_models
from saas import models


RESOLVED = "resolved"
MANUAL_REVIEW = "manual_review"


class PromoBranchAssignmentError(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


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
    grace_period_days: int = 0
    recovery_until: datetime | None = None
    status: str = ""
    active_branch_ids: frozenset[int] = frozenset()

    @property
    def resolved(self) -> bool:
        return self.resolution_status == RESOLVED

    @property
    def active(self) -> bool:
        return self.resolved and self.status == "active"

    @property
    def recovery_active(self) -> bool:
        return self.resolved and self.status == "recovery"


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
            grace_days = max(int(latest.grace_period_days or 0), 0)
            recovery_until = _utc(latest.effective_to) + timedelta(days=grace_days)
            in_recovery = grace_days > 0 and current < recovery_until
            return PromoGrantResolution(
                RESOLVED,
                "promo_grant_recovery_period" if in_recovery else "promo_grant_expired",
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
                grace_period_days=grace_days,
                recovery_until=recovery_until,
                status="recovery" if in_recovery else "expired",
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
        grace_period_days=max(int(grant.grace_period_days or 0), 0),
        recovery_until=(
            _utc(grant.effective_to)
            + timedelta(days=max(int(grant.grace_period_days or 0), 0))
        ),
        status="active",
        active_branch_ids=branch_ids,
    )


def activate_branch_if_available(
    db: Session,
    branch,
    *,
    actor_saas_account_id: int | None = None,
    lock: bool = True,
):
    group_id = int(getattr(branch, "school_group_id", 0) or 0)
    group_query = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == group_id
    )
    if lock:
        group_query = group_query.with_for_update()
    group = group_query.one_or_none()
    if group is None or str(group.workspace_classification or "") != "customer":
        return None
    grant_resolution = resolve_promo_grant(db, group.id)
    if not grant_resolution.active:
        raise PromoBranchAssignmentError(
            "promo_branch_capacity_unavailable",
            "Promo branch capacity is unavailable.",
        )
    entitlements = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.promo_grant_id == grant_resolution.grant_id,
        models.WorkspaceEntitlement.status == "active",
    ).all()
    if len(entitlements) != 1:
        raise PromoBranchAssignmentError(
            "promo_workspace_entitlement_ambiguous",
            "Promo branch entitlement is unavailable.",
        )
    entitlement = entitlements[0]
    existing_rows = db.query(models.BranchEntitlement).filter(
        models.BranchEntitlement.branch_id == branch.id
    ).all()
    if len(existing_rows) > 1:
        raise PromoBranchAssignmentError(
            "promo_branch_entitlement_ambiguous",
            "Promo branch entitlement requires review.",
        )
    existing = existing_rows[0] if existing_rows else None
    if existing is not None and (
        int(existing.school_group_id) != group.id
        or int(existing.workspace_entitlement_id) != int(entitlement.id)
    ):
        raise PromoBranchAssignmentError(
            "promo_branch_entitlement_mismatch",
            "Promo branch entitlement requires review.",
        )
    assignments = db.query(models.PromoGrantBranchAssignment).filter(
        models.PromoGrantBranchAssignment.branch_id == branch.id
    ).all()
    if len(assignments) > 1:
        raise PromoBranchAssignmentError(
            "promo_branch_assignment_ambiguous",
            "Promo branch assignment requires review.",
        )
    assignment = assignments[0] if assignments else None
    if assignment is not None and (
        int(assignment.school_group_id) != group.id
        or int(assignment.promo_grant_id) != int(grant_resolution.grant_id)
    ):
        raise PromoBranchAssignmentError(
            "promo_branch_assignment_mismatch",
            "Promo branch assignment requires review.",
        )
    if assignment is not None:
        if existing is None or existing.entitlement_mode != "active":
            raise PromoBranchAssignmentError(
                "promo_branch_assignment_entitlement_conflict",
                "Promo branch assignment requires review.",
            )
        return existing
    if existing is not None and existing.entitlement_mode == "active":
        raise PromoBranchAssignmentError(
            "promo_active_entitlement_missing_assignment",
            "Promo branch assignment requires review.",
        )
    if existing is not None and existing.entitlement_mode != "inactive":
        raise PromoBranchAssignmentError(
            "promo_branch_entitlement_mode_invalid",
            "Promo branch entitlement requires review.",
        )

    assigned_count = db.query(models.PromoGrantBranchAssignment.id).filter(
        models.PromoGrantBranchAssignment.promo_grant_id == grant_resolution.grant_id
    ).count()
    if assigned_count >= int(grant_resolution.allowed_branches or 0):
        raise PromoBranchAssignmentError(
            "promo_branch_capacity_reached",
            "Promo branch capacity has been reached.",
        )
    resolved_actor_id = actor_saas_account_id
    if resolved_actor_id is None:
        owner_links = db.query(models.SaaSAccountUserLink).filter(
            models.SaaSAccountUserLink.school_group_id == group.id,
            models.SaaSAccountUserLink.link_type == "tenant_owner",
        ).all()
        if len(owner_links) != 1:
            raise PromoBranchAssignmentError(
                "promo_owner_mapping_ambiguous",
                "Promo organization owner mapping is unavailable.",
            )
        resolved_actor_id = owner_links[0].saas_account_id
    assignment = models.PromoGrantBranchAssignment(
        promo_grant_id=grant_resolution.grant_id,
        school_group_id=group.id,
        branch_id=branch.id,
        branch_identity_snapshot=str(branch.id),
        branch_name_snapshot=str(branch.name or "")[:160],
        assigned_by_saas_account_id=resolved_actor_id,
        assignment_reason="unused_promo_capacity",
        assigned_at=datetime.now(UTC).replace(tzinfo=None),
    )
    if existing is None:
        existing = models.BranchEntitlement(
            school_group_id=group.id,
            branch_id=branch.id,
            workspace_entitlement_id=entitlement.id,
            entitlement_mode="active",
            reason_code="promo_unused_capacity_assigned",
        )
        db.add(existing)
    else:
        existing.entitlement_mode = "active"
        existing.reason_code = "promo_unused_capacity_assigned"
    db.add(assignment)
    db.flush()
    return existing


def assign_new_branch_if_available(
    db: Session,
    branch,
    *,
    actor_saas_account_id: int | None = None,
):
    return activate_branch_if_available(
        db,
        branch,
        actor_saas_account_id=actor_saas_account_id,
        lock=False,
    )
