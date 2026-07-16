from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import models


RESOLVED = "resolved"
MANUAL_REVIEW = "manual_review"
ENTITLED_SUBSCRIPTION_STATUSES = {"active", "trialing"}
CONFIRMED_CONTRACT_STATUSES = {"tenant_active"}
CONFIRMED_TENANT_STATUSES = {"tenant_active"}
ACTIVE_ENTITLEMENT_STATUS = "active"
DERIVED_ENTITLEMENT_STATUS = "derived"
OWNER_APPROVAL_REQUIRED = "owner_approval_required"


@dataclass(frozen=True)
class EntitlementValue:
    key: str
    display_name: str
    category: str
    scope: str
    value_type: str
    value: Any
    status: str

    @property
    def granted(self) -> bool:
        if self.status not in {ACTIVE_ENTITLEMENT_STATUS, DERIVED_ENTITLEMENT_STATUS}:
            return False
        if self.value_type == "boolean":
            return self.value is True
        if self.value_type in {"integer", "decimal"}:
            return self.value is not None and self.value > 0
        return bool(self.value)


@dataclass(frozen=True)
class EntitlementResolution:
    resolution_status: str
    reason_code: str
    school_group_id: int | None
    plan_id: int | None = None
    plan_code: str = ""
    plan_name: str = ""
    subscription_id: int | None = None
    subscription_status: str = ""
    billing_interval: str = ""
    paid_branch_quantity: int | None = None
    active_branch_count: int = 0
    remaining_paid_capacity: int | None = None
    is_at_capacity: bool = False
    is_over_capacity: bool = False
    entitlements: dict[str, EntitlementValue] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.resolution_status == RESOLVED


class EntitlementRequiredError(PermissionError):
    def __init__(self, entitlement_key: str, resolution: EntitlementResolution):
        super().__init__("The active subscription does not include this capability.")
        self.entitlement_key = entitlement_key
        self.resolution = resolution


def _clean(value) -> str:
    return str(value or "").strip()


def _manual_review(
    school_group_id: int | None,
    reason_code: str,
    *,
    active_branch_count: int = 0,
) -> EntitlementResolution:
    return EntitlementResolution(
        resolution_status=MANUAL_REVIEW,
        reason_code=reason_code,
        school_group_id=school_group_id,
        active_branch_count=active_branch_count,
    )


def _typed_value(raw_value, value_type: str):
    normalized_type = _clean(value_type).lower()
    if normalized_type == "boolean":
        normalized = _clean(raw_value).lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        raise ValueError("Invalid boolean entitlement value.")
    if normalized_type == "integer":
        return int(raw_value)
    if normalized_type == "decimal":
        try:
            return Decimal(_clean(raw_value))
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal entitlement value.") from exc
    if normalized_type == "text":
        return _clean(raw_value)
    raise ValueError("Unsupported entitlement value type.")


def resolve_entitlements(
    db: Session,
    school_group_id: int,
) -> EntitlementResolution:
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        return _manual_review(None, "invalid_school_group")
    if group_id <= 0:
        return _manual_review(None, "invalid_school_group")

    school_group = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == group_id
    ).first()
    if school_group is None:
        return _manual_review(group_id, "missing_school_group")

    active_branch_count = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == group_id,
        operational_models.Branch.status == True,
    ).count()
    tenant_links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.school_group_id == group_id
    ).all()
    if len(tenant_links) != 1:
        reason = "missing_operational_subscription_link" if not tenant_links else "ambiguous_operational_subscription_link"
        return _manual_review(group_id, reason, active_branch_count=active_branch_count)
    tenant_link = tenant_links[0]
    if _clean(tenant_link.tenant_status).lower() not in CONFIRMED_TENANT_STATUSES:
        return _manual_review(group_id, "tenant_subscription_not_active", active_branch_count=active_branch_count)

    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.id == tenant_link.subscription_contract_id,
        models.SubscriptionContract.school_group_id == group_id,
        models.SubscriptionContract.pending_organization_id == tenant_link.pending_organization_id,
    ).first()
    if contract is None:
        return _manual_review(group_id, "missing_confirmed_contract", active_branch_count=active_branch_count)
    if (
        _clean(contract.contract_status).lower() not in CONFIRMED_CONTRACT_STATUSES
        or _clean(contract.payment_status).lower() != "paid"
        or contract.paid_at is None
    ):
        return _manual_review(group_id, "contract_not_confirmed_paid", active_branch_count=active_branch_count)

    subscriptions = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.subscription_contract_id == contract.id,
        models.PaymentSubscription.pending_organization_id == contract.pending_organization_id,
    ).all()
    active_subscriptions = [
        row for row in subscriptions
        if _clean(row.status).lower() in ENTITLED_SUBSCRIPTION_STATUSES
    ]
    if len(active_subscriptions) != 1:
        reason = "missing_confirmed_subscription" if not active_subscriptions else "ambiguous_confirmed_subscription"
        return _manual_review(group_id, reason, active_branch_count=active_branch_count)
    subscription = active_subscriptions[0]
    if not _clean(subscription.provider_subscription_id):
        return _manual_review(group_id, "missing_provider_subscription", active_branch_count=active_branch_count)
    if int(subscription.plan_id) != int(contract.plan_id):
        return _manual_review(group_id, "subscription_plan_mismatch", active_branch_count=active_branch_count)
    billing_interval = _clean(subscription.billing_interval).lower()
    if billing_interval not in {"monthly", "annual"} or billing_interval != _clean(contract.billing_interval).lower():
        return _manual_review(group_id, "subscription_interval_mismatch", active_branch_count=active_branch_count)
    try:
        paid_quantity = int(subscription.quantity)
    except (TypeError, ValueError):
        paid_quantity = 0
    if paid_quantity <= 0:
        return _manual_review(group_id, "invalid_paid_branch_quantity", active_branch_count=active_branch_count)

    plan = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.id == subscription.plan_id
    ).first()
    if plan is None:
        return _manual_review(group_id, "missing_subscription_plan", active_branch_count=active_branch_count)

    rows = db.query(models.PlanEntitlement, models.EntitlementDefinition).join(
        models.EntitlementDefinition,
        models.EntitlementDefinition.id == models.PlanEntitlement.entitlement_definition_id,
    ).filter(
        models.PlanEntitlement.subscription_plan_id == plan.id,
        models.EntitlementDefinition.active == True,
    ).all()
    entitlements: dict[str, EntitlementValue] = {}
    try:
        for plan_entitlement, definition in rows:
            key = _clean(definition.key)
            if not key or key in entitlements:
                return _manual_review(group_id, "ambiguous_plan_entitlement", active_branch_count=active_branch_count)
            status = _clean(plan_entitlement.status).lower()
            value = plan_entitlement.value
            if key == "quota.active_branches" and status == DERIVED_ENTITLEMENT_STATUS:
                value = paid_quantity
            elif status == ACTIVE_ENTITLEMENT_STATUS:
                value = _typed_value(value, definition.value_type)
            else:
                value = None
            entitlements[key] = EntitlementValue(
                key=key,
                display_name=_clean(definition.display_name),
                category=_clean(definition.category),
                scope=_clean(definition.scope),
                value_type=_clean(definition.value_type).lower(),
                value=value,
                status=status,
            )
    except (TypeError, ValueError):
        return _manual_review(group_id, "invalid_plan_entitlement_value", active_branch_count=active_branch_count)

    remaining = max(paid_quantity - active_branch_count, 0)
    return EntitlementResolution(
        resolution_status=RESOLVED,
        reason_code="resolved",
        school_group_id=group_id,
        plan_id=plan.id,
        plan_code=_clean(plan.plan_code),
        plan_name=_clean(plan.plan_name),
        subscription_id=subscription.id,
        subscription_status=_clean(subscription.status).lower(),
        billing_interval=billing_interval,
        paid_branch_quantity=paid_quantity,
        active_branch_count=active_branch_count,
        remaining_paid_capacity=remaining,
        is_at_capacity=active_branch_count == paid_quantity,
        is_over_capacity=active_branch_count > paid_quantity,
        entitlements=entitlements,
    )


def has_entitlement(
    db: Session,
    school_group_id: int,
    entitlement_key: str,
    *,
    resolution: EntitlementResolution | None = None,
) -> bool:
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        return False
    resolved = resolution or resolve_entitlements(db, school_group_id)
    if not resolved.resolved or resolved.school_group_id != group_id:
        return False
    value = resolved.entitlements.get(_clean(entitlement_key))
    return bool(value and value.granted)


def require_entitlement(
    db: Session,
    school_group_id: int,
    entitlement_key: str,
) -> EntitlementResolution:
    resolution = resolve_entitlements(db, school_group_id)
    if not has_entitlement(
        db,
        school_group_id,
        entitlement_key,
        resolution=resolution,
    ):
        raise EntitlementRequiredError(entitlement_key, resolution)
    return resolution


def _authorized_school_group_id(db: Session, user, school_group_id: int | None) -> int | None:
    scoped_group_id = getattr(user, "scope_school_group_id", None)
    assigned_group_id = auth.get_user_school_group_id(db, user)
    effective_group_id = scoped_group_id or assigned_group_id
    if school_group_id is not None:
        try:
            requested_group_id = int(school_group_id)
        except (TypeError, ValueError):
            return None
        if effective_group_id != requested_group_id:
            return None
        return requested_group_id
    return int(effective_group_id) if effective_group_id else None


def can_use_feature(
    db: Session,
    user,
    feature_key: str,
    permission_key: str,
    *,
    school_group_id: int | None = None,
) -> bool:
    group_id = _authorized_school_group_id(db, user, school_group_id)
    if group_id is None:
        return False
    if not auth.has_permission(db, user, permission_key, school_group_id=group_id):
        return False
    return has_entitlement(db, group_id, feature_key)


def can_access_module(
    db: Session,
    user,
    module_key: str,
    permission_key: str,
    *,
    school_group_id: int | None = None,
) -> bool:
    key = _clean(module_key)
    if not key.startswith("module."):
        key = f"module.{key}"
    return can_use_feature(
        db,
        user,
        key,
        permission_key,
        school_group_id=school_group_id,
    )
