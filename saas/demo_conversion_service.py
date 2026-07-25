from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

import models as operational_models
from commercial_entitlements import (
    CommercialState,
    WorkspaceEntitlementSource,
    WorkspaceEntitlementStatus,
    WorkspaceEntitlementType,
)
from demo_workflow import (
    DemoConversionActorType,
    DemoConversionEventCategory,
    DemoConversionEventType,
    DemoConversionStatus,
    DemoLifecycleProcessingStatus,
    DemoLifecycleState,
)
from saas import (
    commercial_state_service,
    demo_lifecycle_service,
    entitlement_service,
    models,
    workspace_classification_service,
    workspace_entitlement_service,
)
from workspace_classification import (
    WorkspaceClassification,
    WorkspaceIntent,
    WorkspaceLifecycleStatus,
)


class DemoConversionError(ValueError):
    def __init__(self, message: str, *, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class DemoConversionOutcome:
    status: str
    reason_code: str
    conversion_id: int | None
    school_group_id: int | None

    @property
    def completed(self) -> bool:
        return self.status == DemoConversionStatus.COMPLETED.value


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean(value) -> str:
    return str(value or "").strip()


def get_conversion_for_request(db: Session, demo_request, *, for_update: bool = False):
    if demo_request is None:
        return None
    query = db.query(models.SaaSDemoToPaidConversion).filter(
        models.SaaSDemoToPaidConversion.demo_request_id == demo_request.id
    )
    if for_update:
        query = query.with_for_update()
    return query.one_or_none()


def list_conversion_events(db: Session, conversion):
    if conversion is None:
        return []
    return db.query(models.SaaSDemoConversionEvent).filter(
        models.SaaSDemoConversionEvent.demo_conversion_id == conversion.id
    ).order_by(
        models.SaaSDemoConversionEvent.created_at.asc(),
        models.SaaSDemoConversionEvent.id.asc(),
    ).all()


def _add_event_pair(
    db: Session,
    conversion,
    *,
    event_type: DemoConversionEventType,
    actor_type: DemoConversionActorType,
    actor_saas_account_id: int | None = None,
    event_status: str = "ok",
    reason_code: str | None = None,
    details: dict | None = None,
) -> None:
    serialized = json.dumps(
        details or {},
        separators=(",", ":"),
        sort_keys=True,
    )
    for category in (
        DemoConversionEventCategory.AUDIT,
        DemoConversionEventCategory.NOTIFICATION,
    ):
        db.add(
            models.SaaSDemoConversionEvent(
                demo_conversion_id=conversion.id,
                event_category=category.value,
                event_type=event_type.value,
                actor_type=actor_type.value,
                actor_saas_account_id=actor_saas_account_id,
                event_status=event_status,
                reason_code=reason_code,
                details_json=serialized,
            )
        )


def _load_demo_context(db: Session, organization, *, for_update: bool = False):
    request_query = db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.pending_organization_id == organization.id,
        models.SaaSDemoRequest.status == "approved",
    )
    if for_update:
        request_query = request_query.with_for_update()
    demo_requests = request_query.all()
    if len(demo_requests) != 1:
        raise DemoConversionError(
            "The approved demo request could not be resolved safely.",
            reason_code=(
                "missing_approved_demo_request"
                if not demo_requests
                else "ambiguous_approved_demo_request"
            ),
        )
    demo_request = demo_requests[0]
    provisioning_query = db.query(models.SaaSDemoWorkspaceProvisioning).filter(
        models.SaaSDemoWorkspaceProvisioning.demo_request_id == demo_request.id
    )
    if for_update:
        provisioning_query = provisioning_query.with_for_update()
    provisioning = provisioning_query.one_or_none()
    if (
        provisioning is None
        or provisioning.provisioning_status != "active"
        or not provisioning.school_group_id
    ):
        raise DemoConversionError(
            "The demo workspace was not provisioned successfully.",
            reason_code="demo_not_successfully_provisioned",
        )
    group_query = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == provisioning.school_group_id
    )
    tenant_query = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.id == provisioning.tenant_provisioning_link_id
    )
    entitlement_query = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.id == provisioning.workspace_entitlement_id
    )
    if for_update:
        group_query = group_query.with_for_update()
        tenant_query = tenant_query.with_for_update()
        entitlement_query = entitlement_query.with_for_update()
    group = group_query.one_or_none()
    tenant_link = tenant_query.one_or_none()
    demo_entitlement = entitlement_query.one_or_none()
    if not all((group, tenant_link, demo_entitlement)):
        raise DemoConversionError(
            "The demo workspace relationships are incomplete.",
            reason_code="incomplete_demo_workspace_relationships",
        )
    return demo_request, provisioning, group, tenant_link, demo_entitlement


def _validate_active_demo_context(
    db: Session,
    *,
    organization,
    account,
    demo_request,
    provisioning,
    group,
    tenant_link,
    demo_entitlement,
) -> None:
    if (
        int(demo_request.requester_saas_account_id) != int(account.id)
        or int(organization.owner_saas_account_id) != int(account.id)
        or int(demo_request.pending_organization_id) != int(organization.id)
    ):
        raise DemoConversionError(
            "The demo organization ownership could not be verified.",
            reason_code="demo_organization_mismatch",
        )
    if (
        group.workspace_classification
        != WorkspaceClassification.CUSTOMER_DEMO.value
        or group.workspace_lifecycle_status
        != WorkspaceLifecycleStatus.ACTIVE.value
    ):
        raise DemoConversionError(
            "Only an active Customer Demo workspace can be converted.",
            reason_code="workspace_not_active_customer_demo",
        )
    if (
        int(demo_request.school_group_id or 0) != int(group.id)
        or _clean(demo_request.workspace_uuid_snapshot) != _clean(group.workspace_uuid)
        or int(tenant_link.pending_organization_id) != int(organization.id)
        or int(tenant_link.school_group_id) != int(group.id)
        or int(tenant_link.demo_request_id or 0) != int(demo_request.id)
        or tenant_link.subscription_contract_id is not None
        or _clean(tenant_link.tenant_status).lower() != "tenant_active"
    ):
        raise DemoConversionError(
            "The demo tenant linkage is inconsistent.",
            reason_code="demo_tenant_link_mismatch",
        )
    if (
        int(demo_entitlement.school_group_id) != int(group.id)
        or demo_entitlement.entitlement_type != WorkspaceEntitlementType.DEMO.value
        or demo_entitlement.status != WorkspaceEntitlementStatus.ACTIVE.value
        or demo_entitlement.payment_subscription_id is not None
    ):
        raise DemoConversionError(
            "The active demo entitlement could not be verified.",
            reason_code="invalid_demo_entitlement",
        )
    lifecycle = demo_lifecycle_service.resolve_demo_lifecycle(
        db,
        provisioning=provisioning,
    )
    if (
        not lifecycle.resolved
        or lifecycle.lifecycle_state
        not in {
            DemoLifecycleState.ACTIVE.value,
            DemoLifecycleState.REMINDER_DUE.value,
        }
    ):
        raise DemoConversionError(
            "Expired or unresolved demo workspaces cannot be converted.",
            reason_code="demo_lifecycle_not_convertible",
        )


def request_demo_conversion(db: Session, account, organization):
    demo_request, provisioning, group, tenant_link, demo_entitlement = (
        _load_demo_context(db, organization, for_update=True)
    )
    _validate_active_demo_context(
        db,
        organization=organization,
        account=account,
        demo_request=demo_request,
        provisioning=provisioning,
        group=group,
        tenant_link=tenant_link,
        demo_entitlement=demo_entitlement,
    )
    existing = get_conversion_for_request(db, demo_request)
    if existing:
        if existing.status == DemoConversionStatus.COMPLETED.value:
            raise DemoConversionError(
                "This demo workspace has already been converted.",
                reason_code="already_converted",
            )
        return existing
    row = models.SaaSDemoToPaidConversion(
        conversion_uuid=str(uuid.uuid4()),
        demo_request_id=demo_request.id,
        demo_provisioning_id=provisioning.id,
        school_group_id=group.id,
        pending_organization_id=organization.id,
        requested_by_saas_account_id=account.id,
        previous_demo_entitlement_id=demo_entitlement.id,
        status=DemoConversionStatus.REQUESTED.value,
        requested_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    _add_event_pair(
        db,
        row,
        event_type=DemoConversionEventType.CONVERSION_REQUESTED,
        actor_type=DemoConversionActorType.CUSTOMER,
        actor_saas_account_id=account.id,
        details={"workspace_classification": WorkspaceClassification.CUSTOMER_DEMO.value},
    )
    return row


def demo_conversion_checkout_available(db: Session, organization) -> bool:
    try:
        demo_request, provisioning, group, tenant_link, demo_entitlement = (
            _load_demo_context(db, organization)
        )
        account = db.get(models.SaaSAccount, demo_request.requester_saas_account_id)
        if account is None:
            return False
        _validate_active_demo_context(
            db,
            organization=organization,
            account=account,
            demo_request=demo_request,
            provisioning=provisioning,
            group=group,
            tenant_link=tenant_link,
            demo_entitlement=demo_entitlement,
        )
        conversion = get_conversion_for_request(db, demo_request)
        return not conversion or conversion.status != DemoConversionStatus.COMPLETED.value
    except DemoConversionError:
        return False


def _validate_paid_subscription(
    db: Session,
    *,
    organization,
    contract,
    subscription,
) -> None:
    if (
        contract is None
        or subscription is None
        or int(contract.pending_organization_id) != int(organization.id)
        or int(subscription.pending_organization_id) != int(organization.id)
        or int(subscription.subscription_contract_id) != int(contract.id)
    ):
        raise DemoConversionError(
            "The confirmed subscription does not belong to this organization.",
            reason_code="subscription_organization_mismatch",
        )
    if (
        _clean(contract.payment_status).lower() != "paid"
        or contract.paid_at is None
        or _clean(contract.contract_status).lower()
        not in {"paid_pending_provisioning", "ready_for_provisioning", "tenant_active"}
    ):
        raise DemoConversionError(
            "A confirmed paid subscription contract is required.",
            reason_code="subscription_contract_not_confirmed",
        )
    if (
        _clean(subscription.status).lower()
        not in entitlement_service.ENTITLED_SUBSCRIPTION_STATUSES
        or not _clean(subscription.provider_subscription_id)
        or not _clean(subscription.provider_price_id)
        or int(subscription.quantity or 0) <= 0
        or int(subscription.plan_id) != int(contract.plan_id)
        or _clean(subscription.billing_interval).lower()
        != _clean(contract.billing_interval).lower()
    ):
        raise DemoConversionError(
            "The provider-confirmed subscription is not eligible for conversion.",
            reason_code="subscription_not_confirmed_active",
        )
    active_price_count = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == subscription.plan_id,
        models.SubscriptionPlanPrice.billing_interval == subscription.billing_interval,
        models.SubscriptionPlanPrice.provider_price_id == subscription.provider_price_id,
        models.SubscriptionPlanPrice.is_active.is_(True),
    ).count()
    if active_price_count != 1:
        raise DemoConversionError(
            "The provider subscription price could not be resolved safely.",
            reason_code="subscription_price_mismatch",
        )


def _ensure_requested_conversion(
    db: Session,
    *,
    demo_request,
    provisioning,
    group,
    organization,
    demo_entitlement,
):
    conversion = get_conversion_for_request(db, demo_request, for_update=True)
    if conversion:
        return conversion
    conversion = models.SaaSDemoToPaidConversion(
        conversion_uuid=str(uuid.uuid4()),
        demo_request_id=demo_request.id,
        demo_provisioning_id=provisioning.id,
        school_group_id=group.id,
        pending_organization_id=organization.id,
        requested_by_saas_account_id=demo_request.requester_saas_account_id,
        previous_demo_entitlement_id=demo_entitlement.id,
        status=DemoConversionStatus.REQUESTED.value,
        requested_at=_utcnow(),
    )
    db.add(conversion)
    db.flush()
    _add_event_pair(
        db,
        conversion,
        event_type=DemoConversionEventType.CONVERSION_REQUESTED,
        actor_type=DemoConversionActorType.SYSTEM,
        details={"source": "confirmed_subscription"},
    )
    return conversion


def convert_confirmed_demo_subscription(
    db: Session,
    *,
    organization,
    contract,
    subscription,
) -> DemoConversionOutcome:
    try:
        demo_request, provisioning, group, tenant_link, demo_entitlement = (
            _load_demo_context(db, organization, for_update=True)
        )
        account = db.get(models.SaaSAccount, demo_request.requester_saas_account_id)
        if account is None:
            raise DemoConversionError(
                "The demo requester account is unavailable.",
                reason_code="missing_demo_requester",
            )
        conversion = _ensure_requested_conversion(
            db,
            demo_request=demo_request,
            provisioning=provisioning,
            group=group,
            organization=organization,
            demo_entitlement=demo_entitlement,
        )
        if conversion.status == DemoConversionStatus.COMPLETED.value:
            return DemoConversionOutcome(
                status=conversion.status,
                reason_code="already_converted",
                conversion_id=conversion.id,
                school_group_id=group.id,
            )
        _validate_active_demo_context(
            db,
            organization=organization,
            account=account,
            demo_request=demo_request,
            provisioning=provisioning,
            group=group,
            tenant_link=tenant_link,
            demo_entitlement=demo_entitlement,
        )
        _validate_paid_subscription(
            db,
            organization=organization,
            contract=contract,
            subscription=subscription,
        )
    except DemoConversionError as exc:
        conversion = locals().get("conversion")
        if conversion is None:
            return DemoConversionOutcome(
                status=DemoConversionStatus.FAILED.value,
                reason_code=exc.reason_code,
                conversion_id=None,
                school_group_id=getattr(locals().get("group"), "id", None),
            )
        conversion.status = DemoConversionStatus.FAILED.value
        conversion.reason_code = exc.reason_code
        conversion.failure_reason = str(exc)[:4000]
        conversion.failed_at = _utcnow()
        _add_event_pair(
            db,
            conversion,
            event_type=DemoConversionEventType.CONVERSION_FAILED,
            actor_type=DemoConversionActorType.SYSTEM,
            event_status="failed",
            reason_code=exc.reason_code,
        )
        return DemoConversionOutcome(
            status=conversion.status,
            reason_code=exc.reason_code,
            conversion_id=conversion.id,
            school_group_id=conversion.school_group_id,
        )

    now = _utcnow()
    conversion.status = DemoConversionStatus.PROCESSING.value
    conversion.subscription_contract_id = contract.id
    conversion.payment_subscription_id = subscription.id
    conversion.attempt_count = int(conversion.attempt_count or 0) + 1
    conversion.started_at = now
    conversion.failed_at = None
    conversion.failure_reason = None
    conversion.reason_code = None
    _add_event_pair(
        db,
        conversion,
        event_type=DemoConversionEventType.CONVERSION_STARTED,
        actor_type=DemoConversionActorType.SYSTEM,
        details={"attempt": conversion.attempt_count},
    )
    db.flush()

    try:
        with db.begin_nested():
            requested_classification = (
                workspace_classification_service.validate_classification_transition(
                    group.workspace_classification,
                    WorkspaceClassification.CUSTOMER_PAID.value,
                )
            )
            demo_entitlement.status = WorkspaceEntitlementStatus.ENDED.value
            demo_entitlement.effective_to = now
            paid_entitlement = models.WorkspaceEntitlement(
                entitlement_uuid=str(uuid.uuid4()),
                school_group_id=group.id,
                entitlement_type=WorkspaceEntitlementType.PAID.value,
                status=WorkspaceEntitlementStatus.ACTIVE.value,
                source=WorkspaceEntitlementSource.SUBSCRIPTION.value,
                payment_subscription_id=subscription.id,
                effective_from=now,
            )
            db.add(paid_entitlement)
            db.flush()
            db.query(models.BranchEntitlement).filter(
                models.BranchEntitlement.school_group_id == group.id,
                models.BranchEntitlement.workspace_entitlement_id == demo_entitlement.id,
            ).update(
                {
                    models.BranchEntitlement.workspace_entitlement_id: paid_entitlement.id,
                },
                synchronize_session=False,
            )

            group.workspace_classification = requested_classification.value
            group.workspace_lifecycle_status = WorkspaceLifecycleStatus.ACTIVE.value
            tenant_link.demo_request_id = None
            tenant_link.subscription_contract_id = contract.id
            tenant_link.tenant_status = "tenant_active"
            contract.school_group_id = group.id
            contract.contract_status = "tenant_active"
            organization.workspace_intent = WorkspaceIntent.CUSTOMER_PAID.value
            organization.status = "tenant_active"
            organization.billing_status = "tenant_active"
            organization.payment_status = "paid"
            account.onboarding_status = "tenant_active"
            provisioning.lifecycle_processing_status = (
                DemoLifecycleProcessingStatus.CONVERTED.value
            )
            provisioning.lifecycle_last_processed_at = now
            provisioning.lifecycle_failure_code = None
            conversion.paid_workspace_entitlement_id = paid_entitlement.id
            conversion.status = DemoConversionStatus.COMPLETED.value
            conversion.completed_at = now
            conversion.reason_code = "converted"
            db.flush()

            paid = entitlement_service.resolve_entitlements(db, group.id)
            workspace = workspace_entitlement_service.resolve_workspace_entitlement(
                db, group.id
            )
            commercial = commercial_state_service.resolve_commercial_state(db, group.id)
            if (
                not paid.resolved
                or paid.subscription_id != subscription.id
                or paid.is_over_capacity
                or not workspace.resolved
                or workspace.entitlement_type != WorkspaceEntitlementType.PAID.value
                or workspace.payment_subscription_id != subscription.id
                or not commercial.resolved
                or commercial.commercial_state
                != CommercialState.CUSTOMER_PAID_ACTIVE.value
            ):
                raise DemoConversionError(
                    "The converted workspace did not resolve as an active paid workspace.",
                    reason_code="paid_commercial_validation_failed",
                )
    except Exception as exc:
        reason_code = (
            exc.reason_code
            if isinstance(exc, DemoConversionError)
            else "conversion_transaction_failed"
        )
        conversion.status = DemoConversionStatus.FAILED.value
        conversion.reason_code = reason_code
        conversion.failure_reason = str(exc)[:4000]
        conversion.failed_at = _utcnow()
        conversion.completed_at = None
        conversion.paid_workspace_entitlement_id = None
        _add_event_pair(
            db,
            conversion,
            event_type=DemoConversionEventType.CONVERSION_FAILED,
            actor_type=DemoConversionActorType.SYSTEM,
            event_status="failed",
            reason_code=reason_code,
            details={"exception_type": exc.__class__.__name__},
        )
        return DemoConversionOutcome(
            status=conversion.status,
            reason_code=reason_code,
            conversion_id=conversion.id,
            school_group_id=group.id,
        )

    _add_event_pair(
        db,
        conversion,
        event_type=DemoConversionEventType.CONVERSION_COMPLETED,
        actor_type=DemoConversionActorType.SYSTEM,
        details={
            "workspace_classification": WorkspaceClassification.CUSTOMER_PAID.value,
        },
    )
    return DemoConversionOutcome(
        status=conversion.status,
        reason_code="converted",
        conversion_id=conversion.id,
        school_group_id=group.id,
    )
