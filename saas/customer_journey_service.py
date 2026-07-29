from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

import models as operational_models
from saas import (
    demo_conversion_service,
    demo_lifecycle_service,
    demo_provisioning_service,
    demo_request_service,
    models,
    payment_service,
    pricing_service,
    provisioning_service,
    service,
)
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


@dataclass(frozen=True)
class DemoSubscriptionJourney:
    organization: object
    demo_request: object
    provisioning: object
    school_group: object
    lifecycle: object
    branch_count: int
    plans: tuple
    configuration_error: str


def resolve_demo_subscription_journey(
    db: Session, account
) -> DemoSubscriptionJourney | None:
    organization = service.get_pending_organization_for_account(db, account)
    if organization is None:
        return None
    demo_request = demo_request_service.get_latest_for_organization(db, organization)
    if (
        demo_request is None
        or demo_request.status != "approved"
        or not demo_conversion_service.demo_conversion_checkout_available(db, organization)
    ):
        return None
    provisioning = demo_provisioning_service.get_provisioning_for_request(
        db, demo_request
    )
    if provisioning is None or not provisioning.school_group_id:
        return None
    group = db.get(operational_models.SchoolGroup, provisioning.school_group_id)
    if (
        group is None
        or group.workspace_classification
        != WorkspaceClassification.CUSTOMER_DEMO.value
    ):
        return None
    lifecycle = demo_lifecycle_service.resolve_demo_lifecycle(
        db, provisioning=provisioning
    )
    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == group.id,
        operational_models.Branch.status == True,
    ).all()
    plans = tuple(
        pricing_service.build_plan_catalog(
            db, country_code=str(organization.country_code or "")
        )
    )
    error = ""
    if not branches:
        error = "Your workspace branch configuration needs review before checkout."
    elif not plans:
        error = "Subscription pricing is temporarily unavailable. Please contact the TIS team."
    return DemoSubscriptionJourney(
        organization=organization,
        demo_request=demo_request,
        provisioning=provisioning,
        school_group=group,
        lifecycle=lifecycle,
        branch_count=len(branches),
        plans=plans,
        configuration_error=error,
    )


def login_destination(db: Session, account) -> str:
    organization = service.get_pending_organization_for_account(db, account)
    if organization is None:
        account_link = (
            db.query(models.SaaSAccountUserLink)
            .filter(models.SaaSAccountUserLink.saas_account_id == account.id)
            .order_by(models.SaaSAccountUserLink.id.desc())
            .first()
        )
        group = (
            db.get(operational_models.SchoolGroup, account_link.school_group_id)
            if account_link
            else None
        )
        if group and group.workspace_classification == WorkspaceClassification.CUSTOMER_PAID.value:
            tenant_link = (
                db.query(models.TenantProvisioningLink)
                .filter(models.TenantProvisioningLink.school_group_id == group.id)
                .one_or_none()
            )
            subscription = (
                db.query(models.PaymentSubscription)
                .filter(
                    models.PaymentSubscription.pending_organization_id
                    == tenant_link.pending_organization_id
                )
                .order_by(
                    models.PaymentSubscription.updated_at.desc(),
                    models.PaymentSubscription.id.desc(),
                )
                .first()
                if tenant_link
                else None
            )
            if (
                group.workspace_lifecycle_status
                == WorkspaceLifecycleStatus.ACTIVE.value
                and subscription
                and str(subscription.status or "").strip().lower()
                in {"active", "trialing"}
            ):
                return "/login"
            return "/saas/expired-access?kind=subscription"
        return "/saas/account"
    demo_request = demo_request_service.get_latest_for_organization(db, organization)
    provisioning = demo_provisioning_service.get_provisioning_for_request(
        db, demo_request
    )
    if demo_request and demo_request.status == "pending_review":
        return f"/saas/demo-requests/{demo_request.request_uuid}"

    tenant_link = provisioning_service.get_tenant_provisioning_link(db, organization)
    subscription = payment_service.get_payment_subscription(db, organization)
    if tenant_link and subscription:
        group = db.get(operational_models.SchoolGroup, tenant_link.school_group_id)
        subscription_status = str(subscription.status or "").strip().lower()
        if (
            group
            and group.workspace_classification
            == WorkspaceClassification.CUSTOMER_PAID.value
            and group.workspace_lifecycle_status == WorkspaceLifecycleStatus.ACTIVE.value
            and subscription_status in {"active", "trialing"}
        ):
            return "/login"
        return "/saas/expired-access?kind=subscription"
    if provisioning and provisioning.provisioning_status == "active":
        lifecycle = demo_lifecycle_service.resolve_demo_lifecycle(
            db, provisioning=provisioning
        )
        if lifecycle.lifecycle_state == "expired" or not lifecycle.can_access:
            return "/saas/expired-access?kind=demo"
        return "/login"

    status = str(organization.status or "").strip().lower()
    if status != service.READY_FOR_CHECKOUT_STATUS:
        return service.organization_step_url(organization)
    return f"/saas/onboarding/{organization.organization_uuid}/plan"
