import hashlib
import json
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import currency_service, models


@dataclass(frozen=True)
class BillableBranch:
    branch_uuid: str
    branch_name: str


@dataclass(frozen=True)
class PlanCapacityEligibility:
    eligible: bool
    branch_eligible: bool
    staff_eligible: bool
    reason: str
    max_branches: int | None
    max_staff_users: int | None
    active_branch_count: int
    active_staff_count: int
    required_plan_or_custom_state: str

    @property
    def branch_capacity(self) -> int | None:
        return self.max_branches


@dataclass(frozen=True)
class BranchPricingQuote:
    billing_interval: str
    currency_code: str
    plan_id: int | None
    plan_code: str
    plan_price_id: int | None
    plan_version: int | None
    provider_price_id: str
    unit_amount_minor: int
    billable_branch_count: int
    active_staff_count: int
    branches: tuple[BillableBranch, ...]
    quantity: int
    total_amount_minor: int
    display_currency_code: str
    display_total_amount_minor: int
    formatted_unit_amount: str
    formatted_total: str
    fingerprint: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return not self.errors and bool(self.fingerprint)


def normalize_branch_name(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    return unicodedata.normalize("NFKC", cleaned).casefold()


def _clean_branch_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def evaluate_plan_capacity(
    plan,
    *,
    active_branch_count: int,
    active_staff_count: int,
) -> PlanCapacityEligibility:
    branches = max(int(active_branch_count or 0), 0)
    staff = max(int(active_staff_count or 0), 0)
    raw_branch_capacity = getattr(plan, "max_branches", None)
    raw_staff_capacity = getattr(plan, "max_staff_users", None)
    max_branches = (
        int(raw_branch_capacity) if raw_branch_capacity is not None else None
    )
    max_staff_users = (
        int(raw_staff_capacity) if raw_staff_capacity is not None else None
    )
    branch_eligible = bool(max_branches and max_branches > 0 and branches <= max_branches)
    staff_eligible = bool(
        max_staff_users and max_staff_users > 0 and staff <= max_staff_users
    )
    reasons = []
    if max_branches is None or max_branches < 1:
        reasons.append("Branch capacity is unavailable for this plan.")
    elif not branch_eligible:
        reasons.append(
            f"Your organization has {branches} branch"
            f"{'' if branches == 1 else 'es'}. "
            f"{plan.plan_name} supports up to {max_branches}."
        )
    if max_staff_users is None or max_staff_users < 1:
        reasons.append("Staff-user capacity is unavailable for this plan.")
    elif not staff_eligible:
        reasons.append(
            f"Your organization requires capacity for {staff} staff user"
            f"{'' if staff == 1 else 's'}. "
            f"{plan.plan_name} supports up to {max_staff_users}."
        )
    plan_code = str(getattr(plan, "plan_code", "") or "")
    custom_required = plan_code == "enterprise_ai" and (
        not branch_eligible or not staff_eligible
    )
    if custom_required:
        reasons.append(
            "Your organization requires a custom plan. Please contact the TIS team."
        )
    return PlanCapacityEligibility(
        eligible=branch_eligible and staff_eligible,
        branch_eligible=branch_eligible,
        staff_eligible=staff_eligible,
        reason=(
            " ".join(reasons)
            if reasons
            else ""
        ),
        max_branches=max_branches,
        max_staff_users=max_staff_users,
        active_branch_count=branches,
        active_staff_count=staff,
        required_plan_or_custom_state=(
            "eligible"
            if branch_eligible and staff_eligible
            else "custom"
            if custom_required
            else "higher_plan"
        ),
    )


def require_plan_capacity(
    plan,
    *,
    active_branch_count: int,
    active_staff_count: int,
) -> PlanCapacityEligibility:
    capacity = evaluate_plan_capacity(
        plan,
        active_branch_count=active_branch_count,
        active_staff_count=active_staff_count,
    )
    if not capacity.eligible:
        raise ValueError(capacity.reason)
    return capacity


def count_active_staff_users(db: Session, school_group_id: int) -> int:
    return db.query(operational_models.User).filter(
        operational_models.User.school_group_id == int(school_group_id),
        operational_models.User.user_type == auth.USER_TYPE_TENANT,
        operational_models.User.is_active.is_(True),
        operational_models.User.is_internal_test_identity.is_(False),
    ).count()


def require_active_subscription_staff_slot(
    db: Session,
    *,
    school_group_id: int,
    additional_active_staff: int = 1,
) -> PlanCapacityEligibility | None:
    subscriptions = db.query(models.PaymentSubscription).join(
        models.SubscriptionContract,
        models.SubscriptionContract.id
        == models.PaymentSubscription.subscription_contract_id,
    ).filter(
        models.SubscriptionContract.school_group_id == int(school_group_id),
        models.PaymentSubscription.status.in_(("active", "trialing")),
    ).all()
    if not subscriptions:
        return None
    if len(subscriptions) != 1:
        raise ValueError(
            "Staff-user capacity is temporarily unavailable. Please contact the TIS team."
        )
    plan = db.get(models.SubscriptionPlan, subscriptions[0].plan_id)
    if plan is None:
        raise ValueError(
            "Staff-user capacity is temporarily unavailable. Please contact the TIS team."
        )
    branch_count = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == int(school_group_id),
        operational_models.Branch.status.is_(True),
    ).count()
    desired_staff_count = count_active_staff_users(
        db, school_group_id
    ) + max(int(additional_active_staff or 0), 0)
    decision = evaluate_plan_capacity(
        plan,
        active_branch_count=branch_count,
        active_staff_count=desired_staff_count,
    )
    if not decision.staff_eligible:
        raise ValueError(
            f"{decision.reason} Upgrade your subscription before adding another staff user."
        )
    return decision


def authoritative_staff_count(db: Session, organization) -> int:
    declared = max(int(getattr(organization, "estimated_staff_users", 0) or 0), 0)
    links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).all()
    school_group_ids = {
        int(link.school_group_id) for link in links if link.school_group_id
    }
    if len(school_group_ids) > 1:
        raise ValueError(
            "Staff-user capacity could not be resolved for this organization."
        )
    actual = (
        count_active_staff_users(db, next(iter(school_group_ids)))
        if school_group_ids
        else 0
    )
    return max(declared, actual)


def list_billable_branches(db: Session, organization) -> list:
    rows = db.query(models.PendingOrganizationBranch).filter(
        models.PendingOrganizationBranch.pending_organization_id == organization.id,
        models.PendingOrganizationBranch.status == True,
    ).order_by(
        models.PendingOrganizationBranch.sort_order.asc(),
        models.PendingOrganizationBranch.id.asc(),
    ).all()
    return [row for row in rows if _clean_branch_name(getattr(row, "branch_name", ""))]


def build_quote(
    db: Session,
    organization,
    *,
    plan_id: int | None = None,
    billing_interval: str | None = None,
) -> BranchPricingQuote:
    db.flush()
    selected_plan_id = plan_id if plan_id is not None else getattr(organization, "selected_plan_id", None)
    interval = str(
        billing_interval if billing_interval is not None else getattr(organization, "selected_billing_interval", "")
    ).strip().lower()
    errors: list[str] = []
    warnings: list[str] = []

    demo_provisioning = (
        db.query(models.SaaSDemoWorkspaceProvisioning)
        .join(
            models.SaaSDemoRequest,
            models.SaaSDemoRequest.id
            == models.SaaSDemoWorkspaceProvisioning.demo_request_id,
        )
        .filter(
            models.SaaSDemoRequest.pending_organization_id == organization.id,
            models.SaaSDemoRequest.status == "approved",
            models.SaaSDemoWorkspaceProvisioning.provisioning_status == "active",
        )
        .one_or_none()
    )
    operational_rows = (
        db.query(operational_models.Branch)
        .filter(
            operational_models.Branch.school_group_id
            == demo_provisioning.school_group_id,
            operational_models.Branch.status == True,
        )
        .order_by(operational_models.Branch.id.asc())
        .all()
        if demo_provisioning and demo_provisioning.school_group_id
        else []
    )
    if operational_rows:
        active_rows = operational_rows
        name_attribute = "name"
        uuid_value = lambda row: f"operational-branch-{row.id}"
    else:
        active_rows = db.query(models.PendingOrganizationBranch).filter(
            models.PendingOrganizationBranch.pending_organization_id == organization.id,
            models.PendingOrganizationBranch.status == True,
        ).order_by(
            models.PendingOrganizationBranch.sort_order.asc(),
            models.PendingOrganizationBranch.id.asc(),
        ).all()
        name_attribute = "branch_name"
        uuid_value = lambda row: str(row.branch_uuid or "").strip()
    incomplete = [
        row for row in active_rows
        if not _clean_branch_name(getattr(row, name_attribute, ""))
    ]
    billable_rows = [row for row in active_rows if row not in incomplete]
    if incomplete:
        errors.append("Complete every active branch before continuing.")
    if not billable_rows:
        errors.append("Add at least one active branch before choosing a subscription.")

    branch_names = [
        normalize_branch_name(getattr(row, name_attribute, ""))
        for row in billable_rows
    ]
    if len(branch_names) != len(set(branch_names)):
        errors.append("Active branch names must be unique within the organization.")
    if any(not uuid_value(row) for row in billable_rows):
        errors.append("Branch setup could not be validated. Save Branch Setup and try again.")

    plan = None
    if selected_plan_id:
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == int(selected_plan_id),
            models.SubscriptionPlan.is_active == True,
        ).first()
    if not plan:
        errors.append("Select an available subscription plan.")
    if interval not in {"monthly", "annual"}:
        errors.append("Billing interval must be monthly or annual.")

    price_row = None
    if plan and interval in {"monthly", "annual"}:
        price_row = db.query(models.SubscriptionPlanPrice).filter(
            models.SubscriptionPlanPrice.plan_id == plan.id,
            models.SubscriptionPlanPrice.billing_interval == interval,
            models.SubscriptionPlanPrice.currency_code == "USD",
            models.SubscriptionPlanPrice.is_active == True,
        ).order_by(
            models.SubscriptionPlanPrice.plan_version.desc(),
            models.SubscriptionPlanPrice.id.desc(),
        ).first()
    if plan and interval in {"monthly", "annual"} and not price_row:
        errors.append("Pricing is temporarily unavailable for this subscription option.")

    provider_price_id = str(getattr(price_row, "provider_price_id", "") or "").strip()
    if price_row and not provider_price_id:
        errors.append("Secure payment is temporarily unavailable for this subscription option.")

    branches = tuple(
        BillableBranch(
            branch_uuid=uuid_value(row),
            branch_name=_clean_branch_name(getattr(row, name_attribute, "")),
        )
        for row in sorted(billable_rows, key=uuid_value)
    )
    quantity = len(branches)
    try:
        active_staff_count = authoritative_staff_count(db, organization)
    except ValueError as exc:
        active_staff_count = 0
        errors.append(str(exc))
    if plan:
        capacity = evaluate_plan_capacity(
            plan,
            active_branch_count=quantity,
            active_staff_count=active_staff_count,
        )
        if not capacity.eligible:
            errors.append(capacity.reason)
    unit_amount_minor = int(getattr(price_row, "amount_minor", 0) or 0)
    total_amount_minor = unit_amount_minor * quantity
    display_currency = currency_service.resolve_display_currency(
        db, country_code=str(getattr(organization, "country_code", "") or "")
    )
    display_total = currency_service.convert_minor_from_usd(total_amount_minor, display_currency)

    fingerprint = ""
    if not errors:
        canonical = {
            "schema": 1,
            "billing_interval": interval,
            "currency_code": str(price_row.currency_code or "USD"),
            "plan_id": int(plan.id),
            "plan_code": str(plan.plan_code or ""),
            "plan_price_id": int(price_row.id),
            "plan_version": int(price_row.plan_version or 1),
            "provider_price_id": provider_price_id,
            "unit_amount_minor": unit_amount_minor,
            "quantity": quantity,
            "active_staff_count": active_staff_count,
            "branches": [
                {"branch_uuid": branch.branch_uuid, "branch_name": normalize_branch_name(branch.branch_name)}
                for branch in branches
            ],
        }
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    return BranchPricingQuote(
        billing_interval=interval,
        currency_code=str(getattr(price_row, "currency_code", "") or "USD"),
        plan_id=int(plan.id) if plan else None,
        plan_code=str(getattr(plan, "plan_code", "") or ""),
        plan_price_id=int(price_row.id) if price_row else None,
        plan_version=int(price_row.plan_version or 1) if price_row else None,
        provider_price_id=provider_price_id,
        unit_amount_minor=unit_amount_minor,
        billable_branch_count=quantity,
        active_staff_count=active_staff_count,
        branches=branches,
        quantity=quantity,
        total_amount_minor=total_amount_minor,
        display_currency_code=str(display_currency.currency_code or "USD"),
        display_total_amount_minor=display_total,
        formatted_unit_amount=f"USD {unit_amount_minor / 100:,.2f}",
        formatted_total=f"USD {total_amount_minor / 100:,.2f}",
        fingerprint=fingerprint,
        warnings=tuple(warnings),
        errors=tuple(dict.fromkeys(errors)),
    )


def require_ready_quote(quote: BranchPricingQuote) -> BranchPricingQuote:
    if not quote.is_ready:
        raise ValueError(quote.errors[0] if quote.errors else "Subscription pricing could not be prepared.")
    return quote
