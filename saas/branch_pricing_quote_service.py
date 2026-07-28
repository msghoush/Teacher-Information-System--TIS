import hashlib
import json
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

import models as operational_models
from saas import currency_service, models


@dataclass(frozen=True)
class BillableBranch:
    branch_uuid: str
    branch_name: str


@dataclass(frozen=True)
class PlanBranchCapacity:
    eligible: bool
    reason: str
    branch_capacity: int | None
    active_branch_count: int


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


def evaluate_plan_branch_capacity(plan, active_branch_count: int) -> PlanBranchCapacity:
    quantity = max(int(active_branch_count or 0), 0)
    raw_capacity = getattr(plan, "max_branches", None)
    capacity = int(raw_capacity) if raw_capacity is not None else None
    if capacity is None or capacity < 1:
        return PlanBranchCapacity(
            eligible=False,
            reason="This subscription plan is not available for self-service checkout.",
            branch_capacity=capacity,
            active_branch_count=quantity,
        )
    if quantity > capacity:
        reason = (
            "Your organization requires a custom plan. Please contact the TIS team."
            if str(getattr(plan, "plan_code", "") or "") == "enterprise_ai"
            else f"This plan supports up to {capacity} active billable branch"
            f"{'' if capacity == 1 else 'es'}."
        )
        return PlanBranchCapacity(
            eligible=False,
            reason=reason,
            branch_capacity=capacity,
            active_branch_count=quantity,
        )
    return PlanBranchCapacity(
        eligible=True,
        reason="",
        branch_capacity=capacity,
        active_branch_count=quantity,
    )


def require_plan_branch_capacity(plan, active_branch_count: int) -> PlanBranchCapacity:
    capacity = evaluate_plan_branch_capacity(plan, active_branch_count)
    if not capacity.eligible:
        raise ValueError(capacity.reason)
    return capacity


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
    if plan:
        capacity = evaluate_plan_branch_capacity(plan, quantity)
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
