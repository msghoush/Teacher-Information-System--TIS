import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

import auth
import models as operational_models
from commercial_entitlements import BranchEntitlementMode
from saas import (
    billing_identity_service,
    branch_pricing_quote_service,
    currency_service,
    models,
    paddle_client,
)
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


logger = logging.getLogger(__name__)

OPEN_STATUSES = {
    "draft",
    "checkout_ready",
    "checkout_started",
    "payment_processing",
    "manual_review",
}
PLAN_SELECTION_MUTABLE_STATUSES = {"draft", "checkout_ready"}
STARTER_BRANCH_ENFORCEMENT_PROVEN = False
CUSTOMER_SAFE_ERROR = (
    "Secure payment could not be prepared for this workspace. Please try again "
    "or contact the TIS team."
)


class ExistingWorkspacePaidActivationError(ValueError):
    def __init__(self, reason_code: str, customer_message: str = CUSTOMER_SAFE_ERROR):
        self.reason_code = str(reason_code or "activation_unavailable").strip()
        super().__init__(customer_message)


@dataclass(frozen=True)
class ActivationEligibility:
    eligible: bool
    reason_code: str
    school_group: object | None = None
    owner_link: object | None = None
    branch_count: int = 0
    staff_user_count: int = 0
    teacher_count: int = 0
    commercial_source: str = "activation_required"
    promo_grant_id: int | None = None


@dataclass(frozen=True)
class ExistingWorkspaceQuote:
    plan_id: int
    plan_code: str
    plan_name: str
    plan_version: int
    billing_interval: str
    provider_price_id: str
    currency_code: str
    unit_amount_minor: int
    aggregate_amount_minor: int
    quantity: int
    branch_ids: tuple[int, ...]
    branch_selection_hash: str
    fingerprint: str
    staff_user_count: int
    teacher_count: int
    errors: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors and bool(self.fingerprint)


@dataclass(frozen=True)
class CheckoutLaunch:
    activation_uuid: str
    transaction_id: str
    checkout_url: str
    reused: bool


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _clean(value) -> str:
    return str(value or "").strip()


def _hash(payload) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _safe_event_details(details: dict | None) -> str:
    allowed = {
        "plan_code",
        "billing_interval",
        "quantity",
        "reason_code",
        "status",
        "event_type",
        "reused",
    }
    safe = {
        key: value
        for key, value in dict(details or {}).items()
        if key in allowed and isinstance(value, (str, int, bool, type(None)))
    }
    return json.dumps(safe, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def log_event(
    db: Session,
    activation,
    *,
    event_type: str,
    result: str,
    account=None,
    failure_code: str = "",
    details: dict | None = None,
):
    row = models.ExistingWorkspacePaidActivationEvent(
        paid_activation_id=activation.id,
        event_type=_clean(event_type)[:48],
        result=_clean(result)[:20],
        actor_saas_account_id=getattr(account, "id", None),
        failure_code=_clean(failure_code)[:80] or None,
        details_json=_safe_event_details(details),
    )
    db.add(row)
    return row


def _owner_link(db: Session, school_group_id: int, account_id: int):
    rows = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.school_group_id == int(school_group_id),
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    ).all()
    if len(rows) != 1 or int(rows[0].saas_account_id) != int(account_id):
        return None
    user = db.get(operational_models.User, rows[0].operational_user_id)
    if (
        user is None
        or not bool(getattr(user, "is_active", False))
        or int(getattr(user, "school_group_id", 0) or 0) != int(school_group_id)
    ):
        return None
    return rows[0]


def resolve_eligibility(
    db: Session,
    *,
    school_group_id: int,
    account,
    allow_activation_id: int | None = None,
) -> ActivationEligibility:
    group = db.get(operational_models.SchoolGroup, int(school_group_id))
    if group is None:
        return ActivationEligibility(False, "workspace_not_found")
    classification = _clean(group.workspace_classification)
    lifecycle = _clean(group.workspace_lifecycle_status)
    if classification != WorkspaceClassification.CUSTOMER.value or lifecycle not in {
        WorkspaceLifecycleStatus.PROVISIONING.value,
        WorkspaceLifecycleStatus.ACTIVE.value,
    }:
        return ActivationEligibility(False, "workspace_not_activation_required", group)
    if (
        account is None
        or _clean(getattr(account, "status", "")).lower() != "active"
        or getattr(account, "email_verified_at", None) is None
    ):
        return ActivationEligibility(False, "verified_active_account_required", group)
    owner_link = _owner_link(db, group.id, account.id)
    if owner_link is None:
        return ActivationEligibility(False, "verified_tenant_owner_required", group)

    commercial_source = "activation_required"
    promo_grant_id = None
    if lifecycle == WorkspaceLifecycleStatus.ACTIVE.value:
        from saas import promo_grant_service

        promo = promo_grant_service.resolve_promo_grant(db, group.id)
        if promo.active:
            return ActivationEligibility(False, "active_promo_not_convertible", group, owner_link)
        if not promo.resolved or promo.status not in {"recovery", "expired"}:
            return ActivationEligibility(False, "promo_continuation_not_eligible", group, owner_link)
        links = db.query(models.TenantProvisioningLink).filter(
            models.TenantProvisioningLink.school_group_id == group.id
        ).all()
        entitlements = db.query(models.WorkspaceEntitlement).filter(
            models.WorkspaceEntitlement.school_group_id == group.id,
            models.WorkspaceEntitlement.status == "active",
        ).all()
        if (
            len(links) != 1
            or int(links[0].promo_grant_id or 0) != int(promo.grant_id or 0)
            or links[0].subscription_contract_id is not None
            or links[0].demo_request_id is not None
            or len(entitlements) != 1
            or entitlements[0].entitlement_type != "promo"
            or int(entitlements[0].promo_grant_id or 0) != int(promo.grant_id or 0)
        ):
            return ActivationEligibility(False, "promo_commercial_source_mismatch", group, owner_link)
        commercial_source = "promo"
        promo_grant_id = int(promo.grant_id)
    else:
        if db.query(models.WorkspaceEntitlement.id).filter(
            models.WorkspaceEntitlement.school_group_id == group.id,
            models.WorkspaceEntitlement.status == "active",
        ).first():
            return ActivationEligibility(False, "active_commercial_entitlement_exists", group, owner_link)
        if db.query(models.TenantProvisioningLink.id).filter(
            models.TenantProvisioningLink.school_group_id == group.id
        ).first():
            return ActivationEligibility(False, "commercial_tenant_link_exists", group, owner_link)
    if db.query(models.PromoActivationSession.id).filter(
        models.PromoActivationSession.school_group_id == group.id,
        models.PromoActivationSession.status == "open",
    ).first():
        return ActivationEligibility(False, "promo_activation_in_progress", group, owner_link)
    if commercial_source != "promo" and db.query(models.PromoGrant.id).filter(
        models.PromoGrant.school_group_id == group.id
    ).first():
        return ActivationEligibility(False, "promo_commercial_source_exists", group, owner_link)
    if db.query(models.SaaSDemoWorkspaceProvisioning.id).filter(
        models.SaaSDemoWorkspaceProvisioning.school_group_id == group.id
    ).first():
        return ActivationEligibility(False, "demo_commercial_source_exists", group, owner_link)

    contracts = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.school_group_id == group.id
    ).all()
    allowed_contract_ids = {
        int(row.subscription_contract_id)
        for row in db.query(models.ExistingWorkspacePaidActivation).filter(
            models.ExistingWorkspacePaidActivation.school_group_id == group.id,
            models.ExistingWorkspacePaidActivation.status.in_(
                {"failed", "cancelled", "superseded"}
            ),
        ).all()
        if row.subscription_contract_id
    }
    if allow_activation_id:
        allowed = db.get(models.ExistingWorkspacePaidActivation, allow_activation_id)
        if getattr(allowed, "subscription_contract_id", None):
            allowed_contract_ids.add(int(allowed.subscription_contract_id))
    if any(int(row.id) not in allowed_contract_ids for row in contracts):
        return ActivationEligibility(False, "subscription_contract_conflict", group, owner_link)

    from saas import commercial_authority_service

    usage = commercial_authority_service.count_capacity_usage(db, group.id)
    return ActivationEligibility(
        True,
        "eligible",
        group,
        owner_link,
        usage.branches,
        usage.staff_users,
        usage.teachers,
        commercial_source,
        promo_grant_id,
    )


def require_eligibility(db: Session, *, school_group_id: int, account, allow_activation_id=None):
    result = resolve_eligibility(
        db,
        school_group_id=school_group_id,
        account=account,
        allow_activation_id=allow_activation_id,
    )
    if not result.eligible:
        raise ExistingWorkspacePaidActivationError(result.reason_code)
    return result


def list_plan_options(db: Session, eligibility: ActivationEligibility, billing_interval: str):
    interval = _clean(billing_interval).lower()
    rows = db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.plan_code.in_(
            branch_pricing_quote_service.SELF_SERVICE_PLAN_SEQUENCE
        ),
        models.SubscriptionPlan.is_active.is_(True),
        models.SubscriptionPlan.is_public.is_(True),
    ).order_by(models.SubscriptionPlan.sort_order.asc()).all()
    options = []
    for plan in rows:
        price = branch_pricing_quote_service.resolve_active_plan_price(
            db,
            plan_id=plan.id,
            billing_interval=interval,
            currency_code="USD",
        )
        starter = _clean(plan.plan_code).lower() == "starter"
        capacity_branches = 1 if starter else eligibility.branch_count
        capacity = branch_pricing_quote_service.evaluate_plan_capacity(
            plan,
            active_branch_count=capacity_branches,
            active_system_user_count=eligibility.staff_user_count,
            active_teacher_count=eligibility.teacher_count,
        )
        available = bool(
            price
            and _clean(price.provider_price_id)
            and capacity.eligible
            and (not starter or STARTER_BRANCH_ENFORCEMENT_PROVEN)
        )
        reason = capacity.reason
        if starter and capacity.eligible and not STARTER_BRANCH_ENFORCEMENT_PROVEN:
            reason = (
                "Starter is unavailable for this existing workspace until restricted-branch "
                "access enforcement is fully verified."
            )
        options.append({
            "plan": plan,
            "price": price,
            "available": available,
            "reason": reason,
            "quantity": 1 if starter else eligibility.branch_count,
            "requires_branch_selection": starter,
        })
    return tuple(options)


def build_quote(
    db: Session,
    *,
    eligibility: ActivationEligibility,
    plan_id: int,
    billing_interval: str,
    selected_branch_ids: list[int] | tuple[int, ...] | None = None,
) -> ExistingWorkspaceQuote:
    interval = _clean(billing_interval).lower()
    errors = []
    if interval not in {"monthly", "annual"}:
        errors.append("invalid_billing_interval")
    plan = db.get(models.SubscriptionPlan, int(plan_id))
    if plan is None or not bool(plan.is_active) or not bool(plan.is_public):
        raise ExistingWorkspacePaidActivationError("plan_unavailable")
    plan_code = _clean(plan.plan_code).lower()
    if plan_code not in branch_pricing_quote_service.SELF_SERVICE_PLAN_SEQUENCE:
        raise ExistingWorkspacePaidActivationError("plan_not_self_service")
    price = branch_pricing_quote_service.resolve_active_plan_price(
        db,
        plan_id=plan.id,
        billing_interval=interval,
        currency_code="USD",
    )
    if price is None or not _clean(price.provider_price_id):
        raise ExistingWorkspacePaidActivationError("provider_price_unavailable")
    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == eligibility.school_group.id,
        operational_models.Branch.status.is_(True),
    ).order_by(operational_models.Branch.id.asc()).all()
    active_ids = tuple(int(row.id) for row in branches)
    requested = tuple(sorted({int(value) for value in (selected_branch_ids or active_ids)}))
    if any(value not in active_ids for value in requested):
        errors.append("branch_selection_workspace_mismatch")
    if plan_code == "starter":
        if len(requested) != 1:
            errors.append("starter_requires_one_branch")
        if not STARTER_BRANCH_ENFORCEMENT_PROVEN:
            errors.append("starter_branch_enforcement_unavailable")
    elif requested != active_ids:
        errors.append("all_active_branches_required")
    capacity = branch_pricing_quote_service.evaluate_plan_capacity(
        plan,
        active_branch_count=len(requested),
        active_system_user_count=eligibility.staff_user_count,
        active_teacher_count=eligibility.teacher_count,
    )
    if not capacity.eligible:
        errors.append("plan_capacity_exceeded")
    branch_payload = [
        {
            "branch_id": int(row.id),
            "identity": f"{eligibility.school_group.id}:{row.id}",
            "name": _clean(row.name),
        }
        for row in branches
        if int(row.id) in requested
    ]
    branch_hash = _hash(branch_payload)
    quantity = len(requested)
    unit_amount = int(price.amount_minor or 0)
    aggregate = unit_amount * quantity
    canonical = {
        "schema": 1,
        "workspace_uuid": _clean(eligibility.school_group.workspace_uuid),
        "plan_id": int(plan.id),
        "plan_code": plan_code,
        "plan_version": int(price.plan_version or 1),
        "billing_interval": interval,
        "provider_price_id": _clean(price.provider_price_id),
        "currency_code": "USD",
        "unit_amount_minor": unit_amount,
        "quantity": quantity,
        "aggregate_amount_minor": aggregate,
        "staff_user_count": eligibility.staff_user_count,
        "teacher_count": eligibility.teacher_count,
        "branch_selection_hash": branch_hash,
    }
    return ExistingWorkspaceQuote(
        plan_id=plan.id,
        plan_code=plan_code,
        plan_name=_clean(plan.plan_name),
        plan_version=int(price.plan_version or 1),
        billing_interval=interval,
        provider_price_id=_clean(price.provider_price_id),
        currency_code="USD",
        unit_amount_minor=unit_amount,
        aggregate_amount_minor=aggregate,
        quantity=quantity,
        branch_ids=requested,
        branch_selection_hash=branch_hash,
        fingerprint=_hash(canonical),
        staff_user_count=eligibility.staff_user_count,
        teacher_count=eligibility.teacher_count,
        errors=tuple(dict.fromkeys(errors)),
    )


def get_current_activation(db: Session, school_group_id: int):
    return db.query(models.ExistingWorkspacePaidActivation).filter(
        models.ExistingWorkspacePaidActivation.school_group_id == int(school_group_id),
        models.ExistingWorkspacePaidActivation.status.in_(OPEN_STATUSES),
    ).order_by(
        models.ExistingWorkspacePaidActivation.updated_at.desc(),
        models.ExistingWorkspacePaidActivation.id.desc(),
    ).first()


def can_change_plan_selection(db: Session, activation) -> bool:
    """Return whether an open activation draft may safely be replaced.

    A quote remains editable until Paddle checkout has started. Once a checkout is
    in progress, changing its terms would invalidate provider authority, so the
    owner must finish or recover that checkout before choosing another plan.
    """
    if activation is None:
        return True
    if _clean(getattr(activation, "status", "")).lower() not in (
        PLAN_SELECTION_MUTABLE_STATUSES
    ):
        return False
    return not db.query(models.PaymentAttempt.id).filter(
        models.PaymentAttempt.existing_workspace_paid_activation_id == activation.id,
        models.PaymentAttempt.status.in_({"checkout_started", "payment_processing"}),
    ).first()


def _lock_group(db: Session, school_group_id: int):
    query = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == int(school_group_id)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update().populate_existing()
    return query.one_or_none()


def prepare_activation(
    db: Session,
    *,
    school_group_id: int,
    account,
    plan_id: int,
    billing_interval: str,
    selected_branch_ids: list[int] | tuple[int, ...] | None,
    idempotency_key: str,
):
    group = _lock_group(db, school_group_id)
    if group is None:
        raise ExistingWorkspacePaidActivationError("workspace_not_found")
    current = get_current_activation(db, group.id)
    if current and not can_change_plan_selection(db, current):
        raise ExistingWorkspacePaidActivationError(
            "activation_checkout_in_progress",
            "Secure payment is already in progress for this workspace. "
            "Return to the payment review to continue.",
        )
    eligibility = require_eligibility(
        db,
        school_group_id=group.id,
        account=account,
        allow_activation_id=getattr(current, "id", None),
    )
    quote = build_quote(
        db,
        eligibility=eligibility,
        plan_id=plan_id,
        billing_interval=billing_interval,
        selected_branch_ids=selected_branch_ids,
    )
    if not quote.ready:
        raise ExistingWorkspacePaidActivationError(quote.errors[0])
    operation_key = _clean(idempotency_key)
    if not operation_key:
        raise ExistingWorkspacePaidActivationError("idempotency_key_required")
    if current and current.checkout_idempotency_key == operation_key:
        if current.quote_fingerprint != quote.fingerprint:
            raise ExistingWorkspacePaidActivationError("idempotency_parameter_mismatch")
        return current
    if current:
        current.status = "superseded"
        current.failure_code = "quote_superseded"
        for row in db.query(models.CheckoutSession).filter(
            models.CheckoutSession.existing_workspace_paid_activation_id == current.id
        ).all():
            row.status = "stale"
            row.abandoned_at = _utcnow()
        for row in db.query(models.PaymentAttempt).filter(
            models.PaymentAttempt.existing_workspace_paid_activation_id == current.id
        ).all():
            if _clean(row.status).lower() not in {"payment_confirmed", "completed"}:
                row.status = "superseded"
        log_event(
            db,
            current,
            event_type="activation_superseded",
            result="success",
            account=account,
            details={"reason_code": "quote_superseded"},
        )
    contract = models.SubscriptionContract(
        pending_organization_id=None,
        school_group_id=group.id,
        plan_id=quote.plan_id,
        billing_interval=quote.billing_interval,
        contract_status="draft",
        base_currency_code=quote.currency_code,
        base_amount_minor=quote.aggregate_amount_minor,
        display_currency_code=quote.currency_code,
        display_amount_minor=quote.aggregate_amount_minor,
        billable_branch_count=quote.quantity,
        quoted_base_amount_minor=quote.aggregate_amount_minor,
        quoted_display_amount_minor=quote.aggregate_amount_minor,
        quote_fingerprint=quote.fingerprint,
        contract_type="existing_workspace_self_serve",
        plan_version=quote.plan_version,
        payment_status="pending",
        payment_provider="paddle",
    )
    db.add(contract)
    db.flush()
    activation = models.ExistingWorkspacePaidActivation(
        activation_uuid=str(uuid.uuid4()),
        school_group_id=group.id,
        workspace_uuid_snapshot=_clean(group.workspace_uuid),
        saas_account_id=account.id,
        tenant_owner_link_id=eligibility.owner_link.id,
        selected_plan_id=quote.plan_id,
        selected_plan_code=quote.plan_code,
        plan_version=quote.plan_version,
        provider_price_id=quote.provider_price_id,
        billing_interval=quote.billing_interval,
        status="checkout_ready",
        lifecycle_stage="review",
        quote_version=1,
        branch_quantity=quote.quantity,
        selected_branch_hash=quote.branch_selection_hash,
        quote_fingerprint=quote.fingerprint,
        quote_currency_code=quote.currency_code,
        quote_unit_amount_minor=quote.unit_amount_minor,
        quote_aggregate_amount_minor=quote.aggregate_amount_minor,
        checkout_idempotency_key=operation_key,
        subscription_contract_id=contract.id,
    )
    db.add(activation)
    db.flush()
    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.id.in_(quote.branch_ids)
    ).order_by(operational_models.Branch.id.asc()).all()
    for branch in branches:
        db.add(models.ExistingWorkspacePaidActivationBranch(
            paid_activation_id=activation.id,
            quote_version=activation.quote_version,
            branch_id=branch.id,
            branch_identity_snapshot=f"{group.id}:{branch.id}",
            branch_name_snapshot=_clean(branch.name),
        ))
    checkout = models.CheckoutSession(
        pending_organization_id=None,
        plan_selection_id=None,
        existing_workspace_paid_activation_id=activation.id,
        status="ready",
        provider="paddle",
        provider_price_id=quote.provider_price_id,
        currency_code=quote.currency_code,
        amount_minor=quote.aggregate_amount_minor,
        billing_interval=quote.billing_interval,
        billable_branch_count=quote.quantity,
        quoted_base_amount_minor=quote.aggregate_amount_minor,
        quoted_display_amount_minor=quote.aggregate_amount_minor,
        quote_fingerprint=quote.fingerprint,
    )
    db.add(checkout)
    db.flush()
    activation.current_checkout_session_id = checkout.id
    contract.selected_checkout_session_id = checkout.id
    log_event(
        db,
        activation,
        event_type="activation_prepared",
        result="success",
        account=account,
        details={
            "plan_code": quote.plan_code,
            "billing_interval": quote.billing_interval,
            "quantity": quote.quantity,
        },
    )
    db.flush()
    return activation


def _selected_branch_ids(db: Session, activation) -> tuple[int, ...]:
    rows = db.query(models.ExistingWorkspacePaidActivationBranch).filter(
        models.ExistingWorkspacePaidActivationBranch.paid_activation_id == activation.id,
        models.ExistingWorkspacePaidActivationBranch.quote_version == activation.quote_version,
    ).order_by(models.ExistingWorkspacePaidActivationBranch.branch_id.asc()).all()
    return tuple(int(row.branch_id) for row in rows)


def _resolve_payment_customer(db: Session, *, activation, account, profile):
    association = db.query(models.PaymentCustomerWorkspaceAssociation).filter(
        models.PaymentCustomerWorkspaceAssociation.school_group_id == activation.school_group_id
    ).one_or_none()
    if association:
        customer = db.get(models.PaymentCustomer, association.payment_customer_id)
        if customer is None or int(association.saas_account_id) != int(account.id):
            raise ExistingWorkspacePaidActivationError("workspace_customer_mapping_invalid")
        return customer, association
    local_rows = db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account.id,
        models.PaymentCustomer.provider == "paddle",
        models.PaymentCustomer.status == "active",
    ).all()
    if len(local_rows) > 1:
        raise ExistingWorkspacePaidActivationError("ambiguous_local_payment_customer")
    customer = local_rows[0] if local_rows else None
    if customer is None:
        remote_rows = paddle_client.list_customers_by_email(profile.billing_email)
        matching = [
            row for row in remote_rows
            if isinstance(row, dict)
            and _clean(row.get("email")).casefold() == _clean(profile.billing_email).casefold()
            and _clean(row.get("status") or "active").lower() == "active"
            and (
                _clean((row.get("custom_data") or {}).get("saas_account_uuid"))
                == _clean(account.account_uuid)
                or _clean((row.get("custom_data") or {}).get("workspace_uuid"))
                == _clean(activation.workspace_uuid_snapshot)
            )
        ]
        if len(matching) > 1:
            raise ExistingWorkspacePaidActivationError("ambiguous_provider_customer")
        remote = matching[0] if matching else None
        if remote is None:
            try:
                remote = paddle_client.create_customer(
                    email=profile.billing_email,
                    name=profile.billing_contact_name or profile.billing_organization_name,
                    custom_data={
                        "saas_account_uuid": _clean(account.account_uuid),
                        "workspace_uuid": _clean(activation.workspace_uuid_snapshot),
                    },
                )
            except paddle_client.PaddleAPIError:
                remote_rows = paddle_client.list_customers_by_email(profile.billing_email)
                matching = [
                    row for row in remote_rows
                    if isinstance(row, dict)
                    and _clean((row.get("custom_data") or {}).get("saas_account_uuid"))
                    == _clean(account.account_uuid)
                ]
                if len(matching) != 1:
                    raise
                remote = matching[0]
        provider_customer_id = _clean(remote.get("id"))
        if not provider_customer_id.startswith("ctm_"):
            raise ExistingWorkspacePaidActivationError("provider_customer_invalid")
        customer = db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.provider_customer_id == provider_customer_id
        ).one_or_none()
        if customer is None:
            customer = models.PaymentCustomer(
                pending_organization_id=None,
                saas_account_id=account.id,
                provider="paddle",
                provider_customer_id=provider_customer_id,
                email=profile.billing_email_normalized,
                name=profile.billing_contact_name or profile.billing_organization_name,
                country_code=profile.country_code,
                status="active",
            )
            db.add(customer)
            db.flush()
    if int(customer.saas_account_id) != int(account.id):
        raise ExistingWorkspacePaidActivationError("payment_customer_account_mismatch")
    association = models.PaymentCustomerWorkspaceAssociation(
        payment_customer_id=customer.id,
        school_group_id=activation.school_group_id,
        saas_account_id=account.id,
    )
    db.add(association)
    db.flush()
    return customer, association


def _validate_existing_transaction(
    transaction: dict,
    activation,
    customer,
    association,
    account,
    *,
    expected_transaction_id: str = "",
    payment_attempt_uuid: str = "",
) -> str:
    transaction_id = _clean(expected_transaction_id or activation.provider_transaction_id)
    if _clean(transaction.get("id")) != transaction_id:
        raise ExistingWorkspacePaidActivationError("provider_transaction_mismatch")
    if _clean(transaction.get("status")).lower() != "billed":
        raise ExistingWorkspacePaidActivationError("provider_transaction_not_launchable")
    if _clean(transaction.get("collection_mode")).lower() != "automatic":
        raise ExistingWorkspacePaidActivationError("provider_collection_mode_mismatch")
    if _clean(transaction.get("customer_id")) != _clean(customer.provider_customer_id):
        raise ExistingWorkspacePaidActivationError("provider_customer_mismatch")
    if _clean(transaction.get("address_id")) != _clean(association.provider_address_id):
        raise ExistingWorkspacePaidActivationError("provider_address_mismatch")
    if _clean(transaction.get("business_id")) != _clean(association.provider_business_id):
        raise ExistingWorkspacePaidActivationError("provider_business_mismatch")
    custom = transaction.get("custom_data") or {}
    expected_custom = {
        "checkout_context": "existing_workspace_paid_activation",
        "paid_activation_uuid": activation.activation_uuid,
        "workspace_uuid": activation.workspace_uuid_snapshot,
        "saas_account_uuid": account.account_uuid,
        "payment_attempt_uuid": payment_attempt_uuid,
        "subscription_contract_id": activation.subscription_contract_id,
        "quote_fingerprint": activation.quote_fingerprint,
        "branch_selection_hash": activation.selected_branch_hash,
    }
    if any(_clean(custom.get(key)) != _clean(value) for key, value in expected_custom.items()):
        raise ExistingWorkspacePaidActivationError("provider_transaction_lineage_mismatch")
    items = transaction.get("items") if isinstance(transaction.get("items"), list) else []
    if len(items) != 1 or not isinstance(items[0], dict):
        raise ExistingWorkspacePaidActivationError("provider_transaction_item_count_mismatch")
    item = items[0]
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    try:
        quantity = int(item.get("quantity"))
    except (TypeError, ValueError):
        quantity = 0
    if _clean(price.get("id") or item.get("price_id")) != activation.provider_price_id:
        raise ExistingWorkspacePaidActivationError("provider_price_mismatch")
    if quantity != int(activation.branch_quantity):
        raise ExistingWorkspacePaidActivationError("provider_quantity_mismatch")
    currency = _clean(transaction.get("currency_code")).upper()
    if currency != activation.quote_currency_code:
        raise ExistingWorkspacePaidActivationError("provider_currency_mismatch")
    cycle = price.get("billing_cycle") if isinstance(price.get("billing_cycle"), dict) else {}
    interval = {"month": "monthly", "year": "annual"}.get(
        _clean(cycle.get("interval")).lower(), _clean(cycle.get("interval")).lower()
    )
    if interval != activation.billing_interval:
        raise ExistingWorkspacePaidActivationError("provider_interval_mismatch")
    totals = (transaction.get("details") or {}).get("totals") if isinstance(
        transaction.get("details"), dict
    ) else {}
    try:
        subtotal = int((totals or {}).get("subtotal"))
    except (TypeError, ValueError):
        subtotal = -1
    if subtotal != int(activation.quote_aggregate_amount_minor):
        raise ExistingWorkspacePaidActivationError("provider_total_mismatch")
    checkout_url = _clean((transaction.get("checkout") or {}).get("url"))
    if not checkout_url:
        raise ExistingWorkspacePaidActivationError("provider_checkout_url_missing")
    return checkout_url


def validate_payment_launcher_transaction(
    db: Session,
    *,
    attempt,
    transaction_id: str,
) -> str:
    cleaned_transaction_id = _clean(transaction_id)
    activation_id = getattr(attempt, "existing_workspace_paid_activation_id", None)
    if (
        not cleaned_transaction_id.startswith("txn_")
        or activation_id is None
        or getattr(attempt, "pending_organization_id", None) is not None
    ):
        raise ExistingWorkspacePaidActivationError("launcher_context_invalid")

    activation = db.get(models.ExistingWorkspacePaidActivation, activation_id)
    checkout = db.get(
        models.CheckoutSession,
        getattr(attempt, "checkout_session_id", None),
    )
    customer = db.get(
        models.PaymentCustomer,
        getattr(attempt, "payment_customer_id", None),
    )
    account = db.get(
        models.SaaSAccount,
        getattr(activation, "saas_account_id", None),
    )
    contract = db.get(
        models.SubscriptionContract,
        getattr(activation, "subscription_contract_id", None),
    )
    association = db.query(models.PaymentCustomerWorkspaceAssociation).filter(
        models.PaymentCustomerWorkspaceAssociation.school_group_id
        == getattr(activation, "school_group_id", None),
        models.PaymentCustomerWorkspaceAssociation.payment_customer_id
        == getattr(customer, "id", None),
        models.PaymentCustomerWorkspaceAssociation.saas_account_id
        == getattr(account, "id", None),
    ).one_or_none()
    required_lineage = (activation, checkout, customer, account, contract, association)
    if any(row is None for row in required_lineage):
        raise ExistingWorkspacePaidActivationError("launcher_lineage_missing")

    local_state = (
        _clean(activation.status).lower(),
        _clean(attempt.status).lower(),
        _clean(checkout.status).lower(),
    )
    if local_state not in {
        ("checkout_started", "checkout_started", "started"),
        ("payment_processing", "payment_processing", "processing"),
    }:
        raise ExistingWorkspacePaidActivationError("launcher_state_invalid")
    expires_at = getattr(attempt, "expires_at", None)
    if expires_at is None or expires_at <= _utcnow():
        raise ExistingWorkspacePaidActivationError("launcher_attempt_expired")

    checkout_url = _clean(getattr(checkout, "checkout_url", ""))
    local_lineage_matches = (
        int(activation.current_checkout_session_id or 0) == int(checkout.id)
        and int(activation.current_payment_attempt_id or 0) == int(attempt.id)
        and int(checkout.existing_workspace_paid_activation_id or 0)
        == int(activation.id)
        and int(checkout.last_payment_attempt_id or 0) == int(attempt.id)
        and int(attempt.checkout_session_id or 0) == int(checkout.id)
        and int(attempt.payment_customer_id or 0) == int(customer.id)
        and int(contract.school_group_id or 0) == int(activation.school_group_id)
        and _clean(attempt.provider).lower() == "paddle"
        and _clean(attempt.provider_transaction_id) == cleaned_transaction_id
        and _clean(activation.provider_transaction_id) == cleaned_transaction_id
        and f"_ptxn={cleaned_transaction_id}" in checkout_url
    )
    if not local_lineage_matches:
        raise ExistingWorkspacePaidActivationError("launcher_lineage_mismatch")

    eligibility = require_eligibility(
        db,
        school_group_id=activation.school_group_id,
        account=account,
        allow_activation_id=activation.id,
    )
    quote = build_quote(
        db,
        eligibility=eligibility,
        plan_id=activation.selected_plan_id,
        billing_interval=activation.billing_interval,
        selected_branch_ids=_selected_branch_ids(db, activation),
    )
    attempt_matches_quote = (
        quote.ready
        and quote.fingerprint == activation.quote_fingerprint
        and _clean(attempt.provider_price_id) == quote.provider_price_id
        and int(attempt.quantity or 0) == int(quote.quantity)
        and int(attempt.unit_amount_minor or 0) == int(quote.unit_amount_minor)
        and int(attempt.amount_minor or 0) == int(quote.aggregate_amount_minor)
        and _clean(attempt.currency_code).upper() == quote.currency_code
        and _clean(attempt.billing_interval).lower() == quote.billing_interval
        and _clean(attempt.quote_fingerprint) == quote.fingerprint
    )
    if not attempt_matches_quote:
        raise ExistingWorkspacePaidActivationError("launcher_quote_mismatch")

    transaction = paddle_client.get_transaction(transaction_id=cleaned_transaction_id)
    remote_checkout_url = _validate_existing_transaction(
        transaction,
        activation,
        customer,
        association,
        account,
        expected_transaction_id=cleaned_transaction_id,
        payment_attempt_uuid=attempt.attempt_uuid,
    )
    if f"_ptxn={cleaned_transaction_id}" not in remote_checkout_url:
        raise ExistingWorkspacePaidActivationError("provider_checkout_url_mismatch")
    return cleaned_transaction_id


def launch_checkout(db: Session, *, activation_uuid: str, account, checkout_url: str):
    query = db.query(models.ExistingWorkspacePaidActivation).filter(
        models.ExistingWorkspacePaidActivation.activation_uuid == _clean(activation_uuid)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update().populate_existing()
    activation = query.one_or_none()
    if activation is None or int(activation.saas_account_id) != int(account.id):
        raise ExistingWorkspacePaidActivationError("activation_not_found")
    if activation.status not in {"checkout_ready", "checkout_started"}:
        raise ExistingWorkspacePaidActivationError("activation_not_launchable")
    eligibility = require_eligibility(
        db,
        school_group_id=activation.school_group_id,
        account=account,
        allow_activation_id=activation.id,
    )
    quote = build_quote(
        db,
        eligibility=eligibility,
        plan_id=activation.selected_plan_id,
        billing_interval=activation.billing_interval,
        selected_branch_ids=_selected_branch_ids(db, activation),
    )
    if not quote.ready or quote.fingerprint != activation.quote_fingerprint:
        activation.status = "manual_review"
        activation.failure_code = "quote_drift"
        log_event(
            db, activation, event_type="checkout_blocked", result="blocked",
            account=account, failure_code="quote_drift",
            details={"reason_code": "quote_drift"},
        )
        raise ExistingWorkspacePaidActivationError("quote_drift")
    group = eligibility.school_group
    profile = billing_identity_service.require_confirmed_workspace_billing_profile(db, group)
    customer, association = _resolve_payment_customer(
        db, activation=activation, account=account, profile=profile
    )
    address_id, business_id = billing_identity_service.ensure_provider_workspace_billing_identity(
        db, group, customer
    )
    association.provider_address_id = address_id
    association.provider_business_id = business_id
    db.flush()
    if activation.provider_transaction_id:
        try:
            existing_attempt = db.get(
                models.PaymentAttempt, activation.current_payment_attempt_id
            )
            if existing_attempt is None:
                raise ExistingWorkspacePaidActivationError(
                    "payment_attempt_or_customer_missing"
                )
            existing_checkout = db.get(
                models.CheckoutSession,
                activation.current_checkout_session_id,
            )
            if existing_checkout is None:
                raise ExistingWorkspacePaidActivationError("checkout_lineage_missing")
            validate_payment_launcher_transaction(
                db,
                attempt=existing_attempt,
                transaction_id=activation.provider_transaction_id,
            )
            return CheckoutLaunch(
                activation.activation_uuid,
                activation.provider_transaction_id,
                _clean(existing_checkout.checkout_url),
                True,
            )
        except (ExistingWorkspacePaidActivationError, paddle_client.PaddleAPIError):
            old_attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
            if old_attempt and old_attempt.status not in {"payment_confirmed", "completed"}:
                old_attempt.status = "superseded"
            old_checkout = db.get(
                models.CheckoutSession,
                activation.current_checkout_session_id,
            )
            if old_checkout is not None:
                old_checkout.status = "ready"
                old_checkout.provider_checkout_id = None
                old_checkout.checkout_url = None
                old_checkout.last_payment_attempt_id = None
            activation.current_payment_attempt_id = None
            activation.provider_transaction_id = None
    checkout = db.get(models.CheckoutSession, activation.current_checkout_session_id)
    if checkout is None or checkout.existing_workspace_paid_activation_id != activation.id:
        raise ExistingWorkspacePaidActivationError("checkout_lineage_missing")
    attempt = models.PaymentAttempt(
        pending_organization_id=None,
        checkout_session_id=checkout.id,
        plan_selection_id=None,
        existing_workspace_paid_activation_id=activation.id,
        payment_customer_id=customer.id,
        provider="paddle",
        attempt_uuid=str(uuid.uuid4()),
        status="checkout_started",
        provider_price_id=activation.provider_price_id,
        currency_code=activation.quote_currency_code,
        quantity=activation.branch_quantity,
        unit_amount_minor=activation.quote_unit_amount_minor,
        amount_minor=activation.quote_aggregate_amount_minor,
        billing_interval=activation.billing_interval,
        quote_fingerprint=activation.quote_fingerprint,
        started_at=_utcnow(),
        expires_at=_utcnow() + timedelta(hours=2),
    )
    db.add(attempt)
    db.flush()
    custom_data = {
        "checkout_context": "existing_workspace_paid_activation",
        "paid_activation_uuid": activation.activation_uuid,
        "workspace_uuid": activation.workspace_uuid_snapshot,
        "saas_account_uuid": account.account_uuid,
        "payment_attempt_uuid": attempt.attempt_uuid,
        "subscription_contract_id": activation.subscription_contract_id,
        "quote_fingerprint": activation.quote_fingerprint,
        "branch_selection_hash": activation.selected_branch_hash,
    }
    transaction = paddle_client.create_transaction(
        customer_id=customer.provider_customer_id,
        price_id=activation.provider_price_id,
        quantity=activation.branch_quantity,
        country_code=profile.country_code,
        expected_subtotal=activation.quote_aggregate_amount_minor,
        quote_fingerprint=activation.quote_fingerprint,
        custom_data=custom_data,
        checkout_url=checkout_url,
        address_id=address_id,
        business_id=business_id,
    )
    transaction_id = _clean(transaction.get("id"))
    if not transaction_id.startswith("txn_"):
        raise ExistingWorkspacePaidActivationError("provider_transaction_not_launchable")
    remote_checkout_url = _validate_existing_transaction(
        transaction,
        activation,
        customer,
        association,
        account,
        expected_transaction_id=transaction_id,
        payment_attempt_uuid=attempt.attempt_uuid,
    )
    attempt.provider_transaction_id = transaction_id
    attempt.provider_checkout_id = _clean(
        (transaction.get("checkout") or {}).get("id") or transaction_id
    )
    checkout.status = "started"
    checkout.provider_checkout_id = attempt.provider_checkout_id
    checkout.checkout_url = remote_checkout_url
    checkout.last_payment_attempt_id = attempt.id
    checkout.started_at = _utcnow()
    activation.current_payment_attempt_id = attempt.id
    activation.provider_transaction_id = transaction_id
    activation.status = "checkout_started"
    activation.lifecycle_stage = "checkout"
    log_event(
        db, activation, event_type="checkout_started", result="success",
        account=account,
        details={
            "plan_code": activation.selected_plan_code,
            "billing_interval": activation.billing_interval,
            "quantity": activation.branch_quantity,
            "reused": False,
        },
    )
    db.flush()
    return CheckoutLaunch(
        activation.activation_uuid, transaction_id, remote_checkout_url, False
    )


def _event_activation(db: Session, data: dict):
    custom = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    activation_uuid = _clean(custom.get("paid_activation_uuid"))
    if activation_uuid:
        return db.query(models.ExistingWorkspacePaidActivation).filter(
            models.ExistingWorkspacePaidActivation.activation_uuid == activation_uuid
        ).one_or_none()
    subscription_id = _clean(data.get("id"))
    if subscription_id:
        return db.query(models.ExistingWorkspacePaidActivation).filter(
            models.ExistingWorkspacePaidActivation.provider_subscription_id == subscription_id
        ).one_or_none()
    return None


def _validate_completed_payload(db: Session, activation, data: dict):
    custom = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    expected = {
        "checkout_context": "existing_workspace_paid_activation",
        "paid_activation_uuid": activation.activation_uuid,
        "workspace_uuid": activation.workspace_uuid_snapshot,
        "subscription_contract_id": activation.subscription_contract_id,
        "quote_fingerprint": activation.quote_fingerprint,
        "branch_selection_hash": activation.selected_branch_hash,
    }
    if any(_clean(custom.get(key)) != _clean(value) for key, value in expected.items()):
        return "webhook_lineage_mismatch"
    if _clean(data.get("id")) != _clean(activation.provider_transaction_id):
        return "webhook_transaction_mismatch"
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    customer = db.get(models.PaymentCustomer, getattr(attempt, "payment_customer_id", None))
    association = db.query(models.PaymentCustomerWorkspaceAssociation).filter(
        models.PaymentCustomerWorkspaceAssociation.school_group_id
        == activation.school_group_id,
        models.PaymentCustomerWorkspaceAssociation.payment_customer_id
        == getattr(customer, "id", None),
        models.PaymentCustomerWorkspaceAssociation.saas_account_id
        == activation.saas_account_id,
    ).one_or_none()
    if attempt is None or customer is None or association is None:
        return "payment_attempt_or_customer_missing"
    account = db.get(models.SaaSAccount, activation.saas_account_id)
    if account is None or _clean(custom.get("saas_account_uuid")) != _clean(
        account.account_uuid
    ):
        return "webhook_account_mismatch"
    if _clean(custom.get("payment_attempt_uuid")) != _clean(attempt.attempt_uuid):
        return "webhook_attempt_mismatch"
    if _clean(data.get("customer_id")) != _clean(customer.provider_customer_id):
        return "webhook_customer_mismatch"
    if _clean(data.get("address_id")) != _clean(association.provider_address_id):
        return "webhook_address_mismatch"
    if _clean(data.get("business_id")) != _clean(association.provider_business_id):
        return "webhook_business_mismatch"
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if len(items) != 1:
        return "webhook_item_count_mismatch"
    item = items[0] if isinstance(items[0], dict) else {}
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    price_id = _clean(price.get("id") or item.get("price_id"))
    try:
        quantity = int(item.get("quantity"))
    except (TypeError, ValueError):
        quantity = 0
    if price_id != activation.provider_price_id or quantity != activation.branch_quantity:
        return "webhook_price_or_quantity_mismatch"
    currency = _clean(data.get("currency_code")).upper()
    if currency != activation.quote_currency_code:
        return "webhook_currency_mismatch"
    cycle = price.get("billing_cycle") if isinstance(price.get("billing_cycle"), dict) else {}
    interval = {"month": "monthly", "year": "annual"}.get(
        _clean(cycle.get("interval")).lower(), _clean(cycle.get("interval")).lower()
    )
    if interval and interval != activation.billing_interval:
        return "webhook_interval_mismatch"
    totals = (data.get("details") or {}).get("totals") if isinstance(data.get("details"), dict) else {}
    subtotal = _clean((totals or {}).get("subtotal"))
    try:
        subtotal_minor = int(subtotal)
    except (TypeError, ValueError):
        subtotal_minor = -1
    if subtotal_minor != activation.quote_aggregate_amount_minor:
        return "webhook_total_mismatch"
    subscription_id = _clean(data.get("subscription_id"))
    if not subscription_id.startswith("sub_"):
        return "webhook_subscription_missing"
    if activation.provider_subscription_id and activation.provider_subscription_id != subscription_id:
        return "webhook_subscription_mismatch"
    return ""


def _activation_capacity_is_current(db: Session, activation, account):
    eligibility = require_eligibility(
        db,
        school_group_id=activation.school_group_id,
        account=account,
        allow_activation_id=activation.id,
    )
    quote = build_quote(
        db,
        eligibility=eligibility,
        plan_id=activation.selected_plan_id,
        billing_interval=activation.billing_interval,
        selected_branch_ids=_selected_branch_ids(db, activation),
    )
    return (
        quote.ready and quote.fingerprint == activation.quote_fingerprint,
        eligibility,
    )


def _apply_confirmed_promo_conversion(
    db: Session,
    *,
    activation,
    eligibility: ActivationEligibility,
    group,
    contract,
    subscription,
    owner_link,
):
    from saas import entitlement_service, workspace_entitlement_service

    promo_grant_id = int(eligibility.promo_grant_id or 0)
    link = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.school_group_id == group.id
    ).one_or_none()
    grant = db.get(models.PromoGrant, promo_grant_id) if promo_grant_id else None
    promo_entitlement = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.school_group_id == group.id,
        models.WorkspaceEntitlement.status == "active",
    ).one_or_none()
    if (
        eligibility.commercial_source != "promo"
        or link is None
        or grant is None
        or promo_entitlement is None
        or int(link.promo_grant_id or 0) != promo_grant_id
        or int(promo_entitlement.promo_grant_id or 0) != promo_grant_id
        or promo_entitlement.entitlement_type != "promo"
        or grant.status not in {"active", "expired"}
    ):
        raise ExistingWorkspacePaidActivationError("promo_conversion_source_mismatch")

    now = _utcnow()
    with db.begin_nested():
        promo_entitlement.status = "ended"
        grant.status = "converted_to_paid"
        grant.expired_at = grant.expired_at or grant.effective_to or now
        db.flush()

        paid_entitlement = models.WorkspaceEntitlement(
            school_group_id=group.id,
            entitlement_type="paid",
            status="active",
            source="subscription",
            payment_subscription_id=subscription.id,
            effective_from=now,
        )
        db.add(paid_entitlement)
        db.flush()

        selected_ids = set(_selected_branch_ids(db, activation))
        branches = db.query(operational_models.Branch).filter(
            operational_models.Branch.school_group_id == group.id
        ).order_by(operational_models.Branch.id.asc()).all()
        existing_by_branch = {
            int(row.branch_id): row
            for row in db.query(models.BranchEntitlement).filter(
                models.BranchEntitlement.school_group_id == group.id
            ).all()
        }
        for branch in branches:
            mode = (
                BranchEntitlementMode.ACTIVE.value
                if branch.id in selected_ids and bool(branch.status)
                else BranchEntitlementMode.INACTIVE.value
            )
            reason = None if mode == BranchEntitlementMode.ACTIVE.value else "not_in_paid_branch_selection"
            row = existing_by_branch.get(int(branch.id))
            if row is None:
                row = models.BranchEntitlement(
                    school_group_id=group.id,
                    branch_id=branch.id,
                    workspace_entitlement_id=paid_entitlement.id,
                )
                db.add(row)
            row.workspace_entitlement_id = paid_entitlement.id
            row.entitlement_mode = mode
            row.reason_code = reason

        link.promo_grant_id = None
        link.subscription_contract_id = contract.id
        link.demo_request_id = None
        link.tenant_status = "tenant_active"
        contract.school_group_id = group.id
        group.workspace_classification = WorkspaceClassification.CUSTOMER.value
        group.workspace_lifecycle_status = WorkspaceLifecycleStatus.ACTIVE.value
        db.add(models.PromoRedemptionEvent(
            promo_code_id=None,
            promo_redemption_id=grant.promo_redemption_id,
            promo_grant_id=grant.id,
            actor_saas_account_id=activation.saas_account_id,
            actor_operational_user_id=owner_link.operational_user_id,
            school_group_id=group.id,
            event_type="converted_to_paid",
            result="success",
            operation_key=f"paid-activation:{activation.activation_uuid}",
            details_json=_safe_event_details({
                "plan_code": activation.selected_plan_code,
                "billing_interval": activation.billing_interval,
                "quantity": activation.branch_quantity,
            }),
        ))
        db.flush()

        paid = entitlement_service.resolve_entitlements(db, group.id)
        workspace = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
        if (
            not paid.resolved
            or int(paid.subscription_id or 0) != int(subscription.id)
            or not workspace.resolved
            or workspace.entitlement_type != "paid"
            or int(workspace.payment_subscription_id or 0) != int(subscription.id)
        ):
            raise ExistingWorkspacePaidActivationError("promo_paid_authority_validation_failed")
    return paid_entitlement


def _complete_paid_activation(db: Session, activation, data: dict):
    group = _lock_group(db, activation.school_group_id)
    query = db.query(models.ExistingWorkspacePaidActivation).filter(
        models.ExistingWorkspacePaidActivation.id == activation.id
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update().populate_existing()
    activation = query.one()
    if activation.status == "completed":
        return {"status": "processed", "event_type": "transaction.completed", "deduplicated": True}
    account = db.get(models.SaaSAccount, activation.saas_account_id)
    owner_link = db.get(models.SaaSAccountUserLink, activation.tenant_owner_link_id)
    if group is None or account is None or owner_link is None:
        raise ExistingWorkspacePaidActivationError("activation_identity_missing")
    capacity_current, eligibility = _activation_capacity_is_current(db, activation, account)
    if not capacity_current:
        raise ExistingWorkspacePaidActivationError("activation_capacity_or_quote_drift")
    reason = _validate_completed_payload(db, activation, data)
    if reason:
        raise ExistingWorkspacePaidActivationError(reason)
    if eligibility.commercial_source != "promo" and db.query(models.TenantProvisioningLink.id).filter(
        models.TenantProvisioningLink.school_group_id == group.id
    ).first():
        raise ExistingWorkspacePaidActivationError("commercial_source_conflict")
    if eligibility.commercial_source != "promo" and db.query(models.WorkspaceEntitlement.id).filter(
        models.WorkspaceEntitlement.school_group_id == group.id,
        models.WorkspaceEntitlement.status == "active",
    ).first():
        raise ExistingWorkspacePaidActivationError("active_entitlement_conflict")
    contract = db.get(models.SubscriptionContract, activation.subscription_contract_id)
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    checkout = db.get(models.CheckoutSession, activation.current_checkout_session_id)
    customer = db.get(models.PaymentCustomer, getattr(attempt, "payment_customer_id", None))
    if not contract or not attempt or not checkout or not customer:
        raise ExistingWorkspacePaidActivationError("activation_commercial_lineage_missing")
    subscription_id = _clean(data.get("subscription_id"))
    existing_subscription = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.provider_subscription_id == subscription_id
    ).one_or_none()
    if existing_subscription and existing_subscription.subscription_contract_id != contract.id:
        raise ExistingWorkspacePaidActivationError("provider_subscription_already_mapped")
    subscription = existing_subscription or models.PaymentSubscription(
        pending_organization_id=None,
        subscription_contract_id=contract.id,
        payment_customer_id=customer.id,
        provider="paddle",
        provider_subscription_id=subscription_id,
        plan_id=activation.selected_plan_id,
        billing_interval=activation.billing_interval,
        quantity=activation.branch_quantity,
        status="active",
    )
    if existing_subscription is None:
        db.add(subscription)
    subscription.payment_customer_id = customer.id
    subscription.provider_price_id = activation.provider_price_id
    subscription.plan_id = activation.selected_plan_id
    subscription.billing_interval = activation.billing_interval
    subscription.currency_code = activation.quote_currency_code
    subscription.quantity = activation.branch_quantity
    subscription.unit_amount_minor = activation.quote_unit_amount_minor
    subscription.amount_minor = activation.quote_aggregate_amount_minor
    subscription.quote_fingerprint = activation.quote_fingerprint
    subscription.status = "active"
    db.flush()
    contract.contract_status = "tenant_active"
    contract.payment_status = "paid"
    contract.paid_at = contract.paid_at or _utcnow()
    contract.payment_provider = "paddle"
    attempt.status = "payment_confirmed"
    attempt.provider_subscription_id = subscription_id
    attempt.completed_at = attempt.completed_at or _utcnow()
    checkout.status = "completed"
    if eligibility.commercial_source == "promo":
        _apply_confirmed_promo_conversion(
            db,
            activation=activation,
            eligibility=eligibility,
            group=group,
            contract=contract,
            subscription=subscription,
            owner_link=owner_link,
        )
    else:
        entitlement = models.WorkspaceEntitlement(
            school_group_id=group.id,
            entitlement_type="paid",
            status="active",
            source="subscription",
            payment_subscription_id=subscription.id,
            effective_from=_utcnow(),
        )
        db.add(entitlement)
        db.flush()
        selected_ids = set(_selected_branch_ids(db, activation))
        branches = db.query(operational_models.Branch).filter(
            operational_models.Branch.school_group_id == group.id
        ).order_by(operational_models.Branch.id.asc()).all()
        for branch in branches:
            db.add(models.BranchEntitlement(
                school_group_id=group.id,
                branch_id=branch.id,
                workspace_entitlement_id=entitlement.id,
                entitlement_mode=(
                    BranchEntitlementMode.ACTIVE.value
                    if branch.id in selected_ids
                    else BranchEntitlementMode.INACTIVE.value
                ),
                reason_code=(None if branch.id in selected_ids else "not_in_paid_branch_selection"),
            ))
        primary_branch = next((row for row in branches if row.id in selected_ids), None)
        primary_year = db.query(operational_models.AcademicYear).filter(
            operational_models.AcademicYear.school_group_id == group.id,
            operational_models.AcademicYear.is_active.is_(True),
        ).order_by(operational_models.AcademicYear.id.desc()).first()
        db.add(models.TenantProvisioningLink(
            pending_organization_id=None,
            subscription_contract_id=contract.id,
            demo_request_id=None,
            promo_grant_id=None,
            school_group_id=group.id,
            owner_operational_user_id=owner_link.operational_user_id,
            primary_branch_id=getattr(primary_branch, "id", None),
            primary_academic_year_id=getattr(primary_year, "id", None),
            tenant_status="tenant_active",
            activated_at=_utcnow(),
        ))
    group.workspace_classification = WorkspaceClassification.CUSTOMER.value
    group.workspace_lifecycle_status = WorkspaceLifecycleStatus.ACTIVE.value
    account.onboarding_status = "tenant_active"
    activation.provider_subscription_id = subscription_id
    activation.status = "completed"
    activation.lifecycle_stage = "completed"
    activation.completed_at = _utcnow()
    activation.failure_code = None
    log_event(
        db, activation, event_type="activation_completed", result="success",
        account=account,
        details={
            "plan_code": activation.selected_plan_code,
            "billing_interval": activation.billing_interval,
            "quantity": activation.branch_quantity,
        },
    )
    db.flush()
    return {"status": "processed", "event_type": "transaction.completed"}


def reconcile_webhook(db: Session, payload: dict, event_type: str):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    custom = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
    context = _clean(custom.get("checkout_context"))
    if context != "existing_workspace_paid_activation" and not _clean(
        custom.get("paid_activation_uuid")
    ):
        return None
    activation = _event_activation(db, data)
    if activation is None:
        return {
            "status": "manual_review",
            "event_type": event_type,
            "reason_code": "paid_activation_not_found",
        }
    try:
        if event_type == "transaction.paid":
            if _clean(data.get("id")) != _clean(activation.provider_transaction_id):
                raise ExistingWorkspacePaidActivationError("webhook_transaction_mismatch")
            activation.status = "payment_processing"
            activation.lifecycle_stage = "payment"
            attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
            checkout = db.get(models.CheckoutSession, activation.current_checkout_session_id)
            contract = db.get(models.SubscriptionContract, activation.subscription_contract_id)
            if attempt:
                attempt.status = "payment_processing"
            if checkout:
                checkout.status = "processing"
            if contract:
                contract.payment_status = "processing"
            log_event(
                db, activation, event_type="payment_received", result="processing",
                details={"event_type": event_type, "status": "payment_processing"},
            )
            return {"status": "processed", "event_type": event_type}
        if event_type == "transaction.completed":
            return _complete_paid_activation(db, activation, data)
        if event_type.startswith("subscription."):
            subscription_id = _clean(data.get("id"))
            if activation.provider_subscription_id and activation.provider_subscription_id != subscription_id:
                raise ExistingWorkspacePaidActivationError("webhook_subscription_mismatch")
            activation.provider_subscription_id = subscription_id or activation.provider_subscription_id
            if activation.status == "completed":
                subscription = db.query(models.PaymentSubscription).filter(
                    models.PaymentSubscription.provider_subscription_id == subscription_id
                ).one_or_none()
                if subscription:
                    subscription.status = _clean(data.get("status") or subscription.status)
            log_event(
                db, activation, event_type="subscription_reconciled", result="success",
                details={"event_type": event_type, "status": _clean(data.get("status"))},
            )
            return {"status": "processed", "event_type": event_type}
        if event_type in {"transaction.payment_failed", "transaction.past_due", "transaction.canceled"}:
            activation.status = "failed" if event_type != "transaction.canceled" else "cancelled"
            activation.failure_code = event_type.replace(".", "_")
            attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
            if attempt:
                attempt.status = "payment_failed" if activation.status == "failed" else "payment_cancelled"
            log_event(
                db, activation, event_type="payment_failed", result="failed",
                failure_code=activation.failure_code,
                details={"event_type": event_type, "reason_code": activation.failure_code},
            )
            return {"status": "processed", "event_type": event_type}
        return {"status": "ignored", "event_type": event_type}
    except ExistingWorkspacePaidActivationError as exc:
        activation.status = "manual_review"
        activation.failure_code = exc.reason_code
        log_event(
            db, activation, event_type="activation_manual_review", result="blocked",
            failure_code=exc.reason_code,
            details={"event_type": event_type, "reason_code": exc.reason_code},
        )
        logger.error(
            "existing_workspace_paid_activation_webhook_manual_review event_type=%s "
            "reason_code=%s",
            event_type,
            exc.reason_code,
        )
        return {
            "status": "manual_review",
            "event_type": event_type,
            "reason_code": exc.reason_code,
        }
