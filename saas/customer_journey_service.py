from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import (
    commercial_access_service,
    demo_conversion_service,
    demo_lifecycle_service,
    demo_provisioning_service,
    demo_request_service,
    existing_workspace_conversion_service,
    models,
    pricing_service,
    provisioning_service,
    service,
)
from workspace_classification import WorkspaceClassification


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


@dataclass(frozen=True)
class OrganizationAccountAccess:
    organization: object | None
    school_group: object
    operational_user: object | None
    account_link: object | None
    commercial_access: object
    is_owner: bool
    can_view_organization: bool
    can_view_branches: bool
    can_manage_billing: bool

    @property
    def can_manage_account(self) -> bool:
        return bool(
            self.is_owner
            or self.can_view_organization
            or self.can_view_branches
            or self.can_manage_billing
        )

    @property
    def organization_uuid(self) -> str:
        return str(
            getattr(self.organization, "organization_uuid", "")
            or getattr(self.school_group, "workspace_uuid", "")
            or ""
        )

    @property
    def workspace_name(self) -> str:
        return str(
            getattr(self.school_group, "name", "")
            or getattr(self.organization, "organization_name", "")
            or "School Workspace"
        ).strip()


def _has_permission(db: Session, user, permission_key: str, school_group_id: int) -> bool:
    if user is None or not getattr(user, "is_active", False):
        return False
    return bool(
        auth.has_permission(
            db,
            user,
            permission_key,
            school_group_id=school_group_id,
        )
    )


def list_organization_account_accesses(
    db: Session,
    account,
) -> tuple[OrganizationAccountAccess, ...]:
    account_id = int(getattr(account, "id", 0) or 0)
    if not account_id:
        return ()
    links = (
        db.query(models.SaaSAccountUserLink)
        .filter(models.SaaSAccountUserLink.saas_account_id == account_id)
        .order_by(models.SaaSAccountUserLink.id.asc())
        .all()
    )
    accesses = []
    seen_group_ids = set()
    for link in links:
        group_id = int(getattr(link, "school_group_id", 0) or 0)
        if not group_id or group_id in seen_group_ids:
            continue
        group = db.get(operational_models.SchoolGroup, group_id)
        user = db.get(
            operational_models.User,
            int(getattr(link, "operational_user_id", 0) or 0),
        )
        if (
            group is None
            or user is None
            or int(getattr(user, "school_group_id", 0) or 0) != group_id
        ):
            continue
        organization = (
            db.get(
                models.PendingOrganization,
                int(getattr(link, "pending_organization_id", 0) or 0),
            )
            if getattr(link, "pending_organization_id", None)
            else None
        )
        is_owner = bool(
            str(getattr(link, "link_type", "") or "").strip().lower()
            == "tenant_owner"
            or int(getattr(organization, "owner_saas_account_id", 0) or 0)
            == account_id
        )
        can_view_organization = is_owner
        can_view_branches = bool(
            is_owner
            or _has_permission(db, user, "branches.view", group_id)
            or _has_permission(db, user, "branches.create", group_id)
            or _has_permission(db, user, "branches.edit", group_id)
        )
        can_manage_billing = bool(
            is_owner
            or _has_permission(
                db,
                user,
                "subscriptions.manage_billing",
                group_id,
            )
        )
        accesses.append(
            OrganizationAccountAccess(
                organization=organization,
                school_group=group,
                operational_user=user,
                account_link=link,
                commercial_access=commercial_access_service.resolve_workspace_access(
                    db, group_id
                ),
                is_owner=is_owner,
                can_view_organization=can_view_organization,
                can_view_branches=can_view_branches,
                can_manage_billing=can_manage_billing,
            )
        )
        seen_group_ids.add(group_id)
    return tuple(accesses)


def select_organization_account_access(
    db: Session,
    account,
    *,
    organization_uuid: str = "",
) -> tuple[tuple[OrganizationAccountAccess, ...], OrganizationAccountAccess | None]:
    accesses = tuple(
        item for item in list_organization_account_accesses(db, account)
        if item.can_manage_account
    )
    requested = str(organization_uuid or "").strip()
    if requested:
        selected = next(
            (item for item in accesses if item.organization_uuid == requested),
            None,
        )
        return accesses, selected
    return accesses, accesses[0] if len(accesses) == 1 else None


def apply_selected_organization_context(
    db: Session,
    account,
    organization_uuid: str,
) -> OrganizationAccountAccess | None:
    requested = str(organization_uuid or "").strip()
    if not requested:
        return None
    _accesses, selected = select_organization_account_access(
        db,
        account,
        organization_uuid=requested,
    )
    if selected is not None:
        setattr(
            account,
            "_selected_school_group_id",
            int(selected.school_group.id),
        )
    return selected


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
    conversion_claim = existing_workspace_conversion_service.claim_operation_for_account(
        db, account
    )
    if conversion_claim is not None:
        return "/saas/existing-workspace/setup"
    organization = service.get_pending_organization_for_account(db, account)
    if organization is None:
        accesses = list_organization_account_accesses(db, account)
        managed = tuple(item for item in accesses if item.can_manage_account)
        if managed:
            return "/saas/account"
        if accesses:
            access = accesses[0].commercial_access
            if access.allowed_access:
                return "/login"
            return f"/saas/expired-access?kind={access.kind or 'subscription'}"
        return "/saas/account"
    demo_request = demo_request_service.get_latest_for_organization(db, organization)
    provisioning = demo_provisioning_service.get_provisioning_for_request(
        db, demo_request
    )
    if demo_request and demo_request.status == "pending_review":
        return f"/saas/demo-requests/{demo_request.request_uuid}"

    tenant_link = provisioning_service.get_tenant_provisioning_link(db, organization)
    if tenant_link:
        accesses = list_organization_account_accesses(db, account)
        managed = tuple(item for item in accesses if item.can_manage_account)
        if managed:
            return "/saas/account"
        selected = next(
            (
                item
                for item in accesses
                if int(getattr(item.school_group, "id", 0) or 0)
                == int(getattr(tenant_link, "school_group_id", 0) or 0)
            ),
            None,
        )
        if selected and selected.commercial_access.allowed_access:
            return "/login"
        access = (
            selected.commercial_access
            if selected
            else commercial_access_service.resolve_workspace_access(
                db, getattr(tenant_link, "school_group_id", None)
            )
        )
        return f"/saas/expired-access?kind={access.kind or 'subscription'}"

    status = str(organization.status or "").strip().lower()
    if status != service.READY_FOR_CHECKOUT_STATUS:
        return service.organization_step_url(organization)
    return f"/saas/onboarding/{organization.organization_uuid}/plan"
