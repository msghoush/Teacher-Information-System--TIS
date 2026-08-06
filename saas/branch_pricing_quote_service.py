import hashlib
import json
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

import models as operational_models
from saas import currency_service, models


SELF_SERVICE_PLAN_SEQUENCE = ("starter", "professional", "enterprise_ai")


@dataclass(frozen=True)
class BillableBranch:
    branch_uuid: str
    branch_name: str


@dataclass(frozen=True)
class PlanCapacityEligibility:
    eligible: bool
    branch_eligible: bool
    system_user_eligible: bool
    teacher_eligible: bool
    reason: str
    max_branches: int | None
    max_system_users: int | None
    max_teachers: int | None
    active_branch_count: int
    active_system_user_count: int
    active_teacher_count: int
    minimum_eligible_plan: str | None
    required_plan_or_custom_state: str

    @property
    def branch_capacity(self) -> int | None:
        return self.max_branches

    @property
    def staff_eligible(self) -> bool:
        return self.system_user_eligible

    @property
    def max_staff_users(self) -> int | None:
        return self.max_system_users

    @property
    def active_staff_count(self) -> int:
        return self.active_system_user_count


@dataclass(frozen=True)
class OrganizationCapacitySnapshot:
    active_branch_count: int
    active_system_user_count: int
    active_teacher_count: int
    minimum_eligible_plan_code: str | None
    minimum_eligible_plan_name: str | None
    required_plan_or_custom_state: str
    current_plan_eligibility: PlanCapacityEligibility
    upgrade_trigger_dimensions: tuple[str, ...]

    @property
    def custom_required(self) -> bool:
        return self.required_plan_or_custom_state == "custom"

    @property
    def current_plan_eligible(self) -> bool:
        return self.current_plan_eligibility.eligible


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
    active_system_user_count: int
    active_teacher_count: int
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

    @property
    def active_staff_count(self) -> int:
        return self.active_system_user_count


def normalize_branch_name(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    return unicodedata.normalize("NFKC", cleaned).casefold()


def _clean_branch_name(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def resolve_active_plan_price(
    db: Session,
    *,
    plan_id: int,
    billing_interval: str,
    currency_code: str = "USD",
):
    """Resolve the newest active catalog price for authoritative quote builders."""
    return db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == int(plan_id),
        models.SubscriptionPlanPrice.billing_interval
        == str(billing_interval or "").strip().lower(),
        models.SubscriptionPlanPrice.currency_code
        == str(currency_code or "").strip().upper(),
        models.SubscriptionPlanPrice.is_active.is_(True),
    ).order_by(
        models.SubscriptionPlanPrice.plan_version.desc(),
        models.SubscriptionPlanPrice.id.desc(),
    ).first()


def evaluate_plan_capacity(
    plan,
    *,
    active_branch_count: int,
    active_system_user_count: int,
    active_teacher_count: int,
    minimum_eligible_plan: str | None = None,
) -> PlanCapacityEligibility:
    branches = max(int(active_branch_count or 0), 0)
    system_users = max(int(active_system_user_count or 0), 0)
    teachers = max(int(active_teacher_count or 0), 0)
    raw_branch_capacity = getattr(plan, "max_branches", None)
    raw_system_user_capacity = getattr(plan, "max_system_users", None)
    raw_teacher_capacity = getattr(plan, "max_teachers", None)
    max_branches = (
        int(raw_branch_capacity) if raw_branch_capacity is not None else None
    )
    max_system_users = (
        int(raw_system_user_capacity)
        if raw_system_user_capacity is not None else None
    )
    max_teachers = (
        int(raw_teacher_capacity) if raw_teacher_capacity is not None else None
    )
    branch_eligible = bool(max_branches and max_branches > 0 and branches <= max_branches)
    system_user_eligible = bool(
        max_system_users
        and max_system_users > 0
        and system_users <= max_system_users
    )
    teacher_eligible = bool(
        max_teachers and max_teachers > 0 and teachers <= max_teachers
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
    if max_system_users is None or max_system_users < 1:
        reasons.append("System-user capacity is unavailable for this plan.")
    elif not system_user_eligible:
        reasons.append(
            f"{plan.plan_name} supports up to {max_system_users} system user"
            f"{'' if max_system_users == 1 else 's'}. "
            f"Your organization requires {system_users}."
        )
    if max_teachers is None or max_teachers < 1:
        reasons.append("Teacher capacity is unavailable for this plan.")
    elif not teacher_eligible:
        reasons.append(
            f"{plan.plan_name} supports up to {max_teachers} teacher"
            f"{'' if max_teachers == 1 else 's'}. "
            f"Your organization requires {teachers}."
        )
    plan_code = str(getattr(plan, "plan_code", "") or "")
    custom_required = plan_code == "enterprise_ai" and (
        not branch_eligible or not system_user_eligible or not teacher_eligible
    )
    if custom_required:
        reasons.append(
            "Your organization requires a custom plan. Please contact the TIS team."
        )
    return PlanCapacityEligibility(
        eligible=branch_eligible and system_user_eligible and teacher_eligible,
        branch_eligible=branch_eligible,
        system_user_eligible=system_user_eligible,
        teacher_eligible=teacher_eligible,
        reason=(
            " ".join(reasons)
            if reasons
            else ""
        ),
        max_branches=max_branches,
        max_system_users=max_system_users,
        max_teachers=max_teachers,
        active_branch_count=branches,
        active_system_user_count=system_users,
        active_teacher_count=teachers,
        minimum_eligible_plan=minimum_eligible_plan,
        required_plan_or_custom_state=(
            "eligible"
            if branch_eligible and system_user_eligible and teacher_eligible
            else "custom"
            if custom_required
            else "higher_plan"
        ),
    )


def require_plan_capacity(
    plan,
    *,
    active_branch_count: int,
    active_system_user_count: int,
    active_teacher_count: int,
) -> PlanCapacityEligibility:
    capacity = evaluate_plan_capacity(
        plan,
        active_branch_count=active_branch_count,
        active_system_user_count=active_system_user_count,
        active_teacher_count=active_teacher_count,
    )
    if not capacity.eligible:
        raise ValueError(capacity.reason)
    return capacity


def count_active_system_users(db: Session, school_group_id: int) -> int:
    from saas import commercial_authority_service

    return commercial_authority_service.count_active_staff_users(
        db, school_group_id
    )


def count_active_teachers(db: Session, school_group_id: int) -> int:
    from saas import commercial_authority_service

    return commercial_authority_service.count_active_teachers(
        db, school_group_id
    )


def operational_capacity_counts(
    db: Session, school_group_id: int
) -> tuple[int, int, int]:
    from saas import commercial_authority_service

    usage = commercial_authority_service.count_capacity_usage(
        db, school_group_id
    )
    return (
        usage.branches,
        usage.staff_users,
        usage.teachers,
    )


def resolve_minimum_eligible_plan(
    db: Session,
    *,
    active_branch_count: int,
    active_system_user_count: int,
    active_teacher_count: int,
):
    rows = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.plan_code.in_(SELF_SERVICE_PLAN_SEQUENCE),
        models.SubscriptionPlan.is_active.is_(True),
        models.SubscriptionPlan.is_public.is_(True),
    ).all()
    by_code = {str(row.plan_code or "").strip().lower(): row for row in rows}
    if any(code not in by_code for code in SELF_SERVICE_PLAN_SEQUENCE):
        raise ValueError("Subscription capacity is temporarily unavailable.")
    for code in SELF_SERVICE_PLAN_SEQUENCE:
        plan = by_code[code]
        if evaluate_plan_capacity(
            plan,
            active_branch_count=active_branch_count,
            active_system_user_count=active_system_user_count,
            active_teacher_count=active_teacher_count,
        ).eligible:
            return plan
    return None


def build_organization_capacity_snapshot(
    db: Session,
    *,
    school_group_id: int,
    current_plan,
    proposed_branch_count: int | None = None,
    proposed_system_user_count: int | None = None,
    proposed_teacher_count: int | None = None,
) -> OrganizationCapacitySnapshot:
    current_branches, current_system_users, current_teachers = (
        operational_capacity_counts(db, school_group_id)
    )
    branches = (
        current_branches
        if proposed_branch_count is None
        else max(int(proposed_branch_count), 0)
    )
    system_users = (
        current_system_users
        if proposed_system_user_count is None
        else max(int(proposed_system_user_count), 0)
    )
    teachers = (
        current_teachers
        if proposed_teacher_count is None
        else max(int(proposed_teacher_count), 0)
    )
    if branches < current_branches:
        raise ValueError("Proposed branch capacity cannot be lower than active branch usage.")
    if system_users < current_system_users:
        raise ValueError("Proposed system-user capacity cannot be lower than current usage.")
    if teachers < current_teachers:
        raise ValueError("Proposed teacher capacity cannot be lower than current usage.")

    minimum_plan = resolve_minimum_eligible_plan(
        db,
        active_branch_count=branches,
        active_system_user_count=system_users,
        active_teacher_count=teachers,
    )
    current_eligibility = evaluate_plan_capacity(
        current_plan,
        active_branch_count=branches,
        active_system_user_count=system_users,
        active_teacher_count=teachers,
        minimum_eligible_plan=(
            str(minimum_plan.plan_code or "") if minimum_plan is not None else None
        ),
    )
    triggers = []
    if not current_eligibility.branch_eligible:
        triggers.append("branches")
    if not current_eligibility.system_user_eligible:
        triggers.append("system_users")
    if not current_eligibility.teacher_eligible:
        triggers.append("teachers")
    return OrganizationCapacitySnapshot(
        active_branch_count=branches,
        active_system_user_count=system_users,
        active_teacher_count=teachers,
        minimum_eligible_plan_code=(
            str(minimum_plan.plan_code or "") if minimum_plan is not None else None
        ),
        minimum_eligible_plan_name=(
            str(minimum_plan.plan_name or "") if minimum_plan is not None else None
        ),
        required_plan_or_custom_state=("eligible" if minimum_plan is not None else "custom"),
        current_plan_eligibility=current_eligibility,
        upgrade_trigger_dimensions=tuple(triggers),
    )


def require_active_subscription_capacity_slot(
    db: Session,
    *,
    school_group_id: int,
    additional_system_users: int = 0,
    additional_teachers: int = 0,
) -> PlanCapacityEligibility | None:
    from saas import commercial_authority_service

    try:
        result = commercial_authority_service.require_capacity_change(
            db,
            school_group_id,
            staff_user_delta=max(int(additional_system_users or 0), 0),
            teacher_delta=max(int(additional_teachers or 0), 0),
        )
    except commercial_authority_service.CapacityAuthorityError as exc:
        raise ValueError(str(exc)) from exc
    return result


def branch_estimate_totals(db: Session, organization) -> tuple[int, int]:
    rows = list_billable_branches(db, organization)
    return (
        sum(max(int(row.estimated_system_users or 0), 0) for row in rows),
        sum(max(int(row.estimated_teachers or 0), 0) for row in rows),
    )


def authoritative_capacity_counts(
    db: Session, organization
) -> tuple[int, int, int]:
    branch_count = len(list_billable_branches(db, organization))
    estimated_system_users, estimated_teachers = branch_estimate_totals(
        db, organization
    )
    links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).all()
    school_group_ids = {
        int(link.school_group_id) for link in links if link.school_group_id
    }
    if len(school_group_ids) > 1:
        raise ValueError(
            "Organization capacity could not be resolved."
        )
    actual_system_users = 0
    actual_teachers = 0
    if school_group_ids:
        school_group_id = next(iter(school_group_ids))
        actual_system_users = count_active_system_users(db, school_group_id)
        actual_teachers = count_active_teachers(db, school_group_id)
    activated = (
        str(getattr(organization, "payment_status", "") or "").lower() == "paid"
        or str(getattr(organization, "status", "") or "").lower()
        == "tenant_active"
    )
    return (
        branch_count,
        actual_system_users
        if activated else max(estimated_system_users, actual_system_users),
        actual_teachers
        if activated else max(estimated_teachers, actual_teachers),
    )


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
        price_row = resolve_active_plan_price(
            db,
            plan_id=plan.id,
            billing_interval=interval,
            currency_code="USD",
        )
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
        _capacity_branches, active_system_user_count, active_teacher_count = (
            authoritative_capacity_counts(db, organization)
        )
    except ValueError as exc:
        active_system_user_count = 0
        active_teacher_count = 0
        errors.append(str(exc))
    if plan:
        plan_catalog = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.is_active.is_(True),
            models.SubscriptionPlan.is_public.is_(True),
        ).order_by(
            models.SubscriptionPlan.sort_order.asc(),
            models.SubscriptionPlan.id.asc(),
        ).all()
        minimum_eligible_plan = next(
            (
                candidate.plan_code
                for candidate in plan_catalog
                if evaluate_plan_capacity(
                    candidate,
                    active_branch_count=quantity,
                    active_system_user_count=active_system_user_count,
                    active_teacher_count=active_teacher_count,
                ).eligible
            ),
            None,
        )
        capacity = evaluate_plan_capacity(
            plan,
            active_branch_count=quantity,
            active_system_user_count=active_system_user_count,
            active_teacher_count=active_teacher_count,
            minimum_eligible_plan=minimum_eligible_plan,
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
            "active_system_user_count": active_system_user_count,
            "active_teacher_count": active_teacher_count,
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
        active_system_user_count=active_system_user_count,
        active_teacher_count=active_teacher_count,
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
