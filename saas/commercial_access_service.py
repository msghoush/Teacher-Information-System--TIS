from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

import models
from saas import demo_lifecycle_service, models as saas_models
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


@dataclass(frozen=True)
class CommercialAccessState:
    blocked: bool
    kind: str = ""
    reason_code: str = ""


def resolve_workspace_access(
    db: Session, school_group_id: int | None
) -> CommercialAccessState:
    if not school_group_id:
        return CommercialAccessState(False)
    group = db.get(models.SchoolGroup, int(school_group_id))
    if group is None:
        return CommercialAccessState(False)
    if group.workspace_classification == WorkspaceClassification.CUSTOMER_DEMO.value:
        lifecycle = demo_lifecycle_service.resolve_demo_lifecycle(
            db, school_group_id=group.id
        )
        if lifecycle.can_access:
            return CommercialAccessState(False)
        return CommercialAccessState(
            True,
            "demo",
            "demo_expired"
            if lifecycle.lifecycle_state == "expired"
            else "demo_access_unavailable",
        )
    if (
        group.workspace_classification == WorkspaceClassification.CUSTOMER_PAID.value
    ):
        link = db.query(saas_models.TenantProvisioningLink).filter(
            saas_models.TenantProvisioningLink.school_group_id == group.id
        ).one_or_none()
        subscription = (
            db.query(saas_models.PaymentSubscription)
            .filter(
                saas_models.PaymentSubscription.pending_organization_id
                == link.pending_organization_id
            )
            .order_by(
                saas_models.PaymentSubscription.updated_at.desc(),
                saas_models.PaymentSubscription.id.desc(),
            )
            .first()
            if link
            else None
        )
        lifecycle_blocked = group.workspace_lifecycle_status in {
            WorkspaceLifecycleStatus.SUSPENDED.value,
            WorkspaceLifecycleStatus.ARCHIVED.value,
        }
        subscription_blocked = bool(
            subscription
            and str(subscription.status or "").strip().lower()
            not in {"active", "trialing"}
        )
        if lifecycle_blocked or subscription_blocked:
            return CommercialAccessState(
                True, "subscription", "subscription_expired"
            )
    return CommercialAccessState(False)
