from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import entitlement_service, models


@dataclass(frozen=True)
class SubscriptionDiagnosticError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _clean(value) -> str:
    return str(value or "").strip()


def _masked_provider_id(value) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return "missing"
    if len(cleaned) <= 10:
        return f"{cleaned[:3]}..."
    return f"{cleaned[:7]}...{cleaned[-4:]}"


def _find_organization(db: Session, *, email: str | None, organization_uuid: str | None):
    normalized_email = auth.normalize_email(email or "")
    cleaned_uuid = _clean(organization_uuid)
    if bool(normalized_email) == bool(cleaned_uuid):
        raise SubscriptionDiagnosticError(
            "invalid_selector",
            "Provide exactly one SaaS account email or pending organization UUID.",
        )
    if cleaned_uuid:
        organization = db.query(models.PendingOrganization).filter(
            models.PendingOrganization.organization_uuid == cleaned_uuid
        ).one_or_none()
        if organization is None:
            raise SubscriptionDiagnosticError("organization_not_found", "Pending organization was not found.")
        account = db.query(models.SaaSAccount).filter(
            models.SaaSAccount.id == organization.owner_saas_account_id
        ).one_or_none()
        if account is None:
            raise SubscriptionDiagnosticError("account_not_found", "Owning SaaS account was not found.")
        return account, organization

    account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.email_normalized == normalized_email
    ).one_or_none()
    if account is None:
        raise SubscriptionDiagnosticError("account_not_found", "SaaS account was not found.")
    organizations = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account.id
    ).all()
    if len(organizations) != 1:
        raise SubscriptionDiagnosticError(
            "ambiguous_account_organizations",
            "The SaaS account does not resolve to exactly one pending organization.",
        )
    return account, organizations[0]


def _relationship_rows(db: Session, account, organization) -> dict:
    tenant_links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).all()
    contracts = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == organization.id
    ).all()
    subscriptions = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.pending_organization_id == organization.id
    ).all()
    attempts = db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.pending_organization_id == organization.id
    ).all()
    customers = db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account.id
    ).all()
    account_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id
    ).all()
    return {
        "tenant_links": tenant_links,
        "contracts": contracts,
        "subscriptions": subscriptions,
        "attempts": attempts,
        "customers": customers,
        "account_links": account_links,
    }


def diagnose_subscription_relationships(
    db: Session,
    *,
    email: str | None = None,
    organization_uuid: str | None = None,
) -> dict:
    account, organization = _find_organization(
        db,
        email=email,
        organization_uuid=organization_uuid,
    )
    rows = _relationship_rows(db, account, organization)
    tenant_link = rows["tenant_links"][0] if len(rows["tenant_links"]) == 1 else None
    school_group = None
    if tenant_link:
        school_group = db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id == tenant_link.school_group_id
        ).one_or_none()
    contract = None
    if tenant_link:
        contract = next(
            (row for row in rows["contracts"] if int(row.id) == int(tenant_link.subscription_contract_id)),
            None,
        )
    active_subscriptions = [
        row for row in rows["subscriptions"]
        if _clean(row.status).lower() in entitlement_service.ENTITLED_SUBSCRIPTION_STATUSES
    ]
    subscription = active_subscriptions[0] if len(active_subscriptions) == 1 else None
    plan = None
    price_matches = []
    if subscription:
        plan = db.query(models.SubscriptionPlan).filter(models.SubscriptionPlan.id == subscription.plan_id).one_or_none()
        price_matches = db.query(models.SubscriptionPlanPrice).filter(
            models.SubscriptionPlanPrice.plan_id == subscription.plan_id,
            models.SubscriptionPlanPrice.billing_interval == subscription.billing_interval,
            models.SubscriptionPlanPrice.currency_code == _clean(subscription.currency_code).upper(),
            models.SubscriptionPlanPrice.provider_price_id == subscription.provider_price_id,
            models.SubscriptionPlanPrice.is_active == True,
        ).all()
    resolution = (
        entitlement_service.resolve_entitlements(db, school_group.id)
        if school_group
        else entitlement_service.EntitlementResolution(
            resolution_status=entitlement_service.MANUAL_REVIEW,
            reason_code="missing_school_group",
            school_group_id=None,
        )
    )
    warnings = []
    if len(rows["tenant_links"]) != 1:
        warnings.append("tenant_link_count_not_one")
    if tenant_link and contract is None:
        warnings.append("tenant_link_contract_mismatch")
    if contract and contract.school_group_id is None:
        warnings.append("contract_school_group_missing")
    elif contract and school_group and int(contract.school_group_id) != int(school_group.id):
        warnings.append("contract_school_group_mismatch")
    if len(active_subscriptions) != 1:
        warnings.append("active_subscription_count_not_one")
    if subscription and contract and int(subscription.subscription_contract_id) != int(contract.id):
        warnings.append("subscription_contract_mismatch")
    if subscription and len(price_matches) != 1:
        warnings.append("provider_price_relationship_invalid")
    if subscription and int(subscription.quantity or 0) <= 0:
        warnings.append("subscription_quantity_invalid")
    if (
        contract
        and subscription
        and _clean(contract.payment_status).lower() == "pending"
        and contract.paid_at is not None
        and _clean(subscription.status).lower() in entitlement_service.ENTITLED_SUBSCRIPTION_STATUSES
    ):
        warnings.append("contract_payment_status_stale_pending")

    return {
        "account_uuid": account.account_uuid,
        "pending_organization_uuid": organization.organization_uuid,
        "school_group_id": school_group.id if school_group else None,
        "school_group_active": bool(school_group and school_group.status),
        "tenant_link_count": len(rows["tenant_links"]),
        "tenant_link_status": _clean(tenant_link.tenant_status) if tenant_link else "missing",
        "tenant_link_contract_id": tenant_link.subscription_contract_id if tenant_link else None,
        "contract_count": len(rows["contracts"]),
        "contract_id": contract.id if contract else None,
        "contract_school_group_id": contract.school_group_id if contract else None,
        "contract_status": _clean(contract.contract_status) if contract else "missing",
        "contract_payment_status": _clean(contract.payment_status) if contract else "missing",
        "contract_paid_at_present": bool(contract and contract.paid_at),
        "active_subscription_count": len(active_subscriptions),
        "payment_subscription_id": subscription.id if subscription else None,
        "payment_subscription_contract_id": subscription.subscription_contract_id if subscription else None,
        "payment_subscription_status": _clean(subscription.status) if subscription else "missing_or_ambiguous",
        "payment_subscription_quantity": subscription.quantity if subscription else None,
        "provider_subscription_id_masked": _masked_provider_id(subscription.provider_subscription_id) if subscription else "missing_or_ambiguous",
        "provider_price_id_masked": _masked_provider_id(subscription.provider_price_id) if subscription else "missing_or_ambiguous",
        "plan_code": _clean(plan.plan_code) if plan else "unresolved",
        "active_price_match_count": len(price_matches),
        "payment_customer_count": len(rows["customers"]),
        "payment_attempt_count": len(rows["attempts"]),
        "confirmed_payment_attempt_count": len([
            row for row in rows["attempts"] if _clean(row.status).lower() == "payment_confirmed"
        ]),
        "account_user_link_count": len(rows["account_links"]),
        "entitlement_resolution_status": resolution.resolution_status,
        "entitlement_reason_code": resolution.reason_code,
        "warnings": sorted(set(warnings)),
    }


def repair_contract_school_group_link(
    db: Session,
    *,
    email: str | None = None,
    organization_uuid: str | None = None,
) -> dict:
    account, organization = _find_organization(db, email=email, organization_uuid=organization_uuid)
    rows = _relationship_rows(db, account, organization)
    if len(rows["tenant_links"]) != 1:
        raise SubscriptionDiagnosticError("ambiguous_tenant_link", "Exactly one tenant provisioning link is required.")
    tenant_link = rows["tenant_links"][0]
    school_group = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == tenant_link.school_group_id,
        operational_models.SchoolGroup.status == True,
    ).one_or_none()
    if school_group is None or _clean(tenant_link.tenant_status).lower() != "tenant_active":
        raise SubscriptionDiagnosticError("inactive_operational_tenant", "An active linked operational tenant is required.")
    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.id == tenant_link.subscription_contract_id,
        models.SubscriptionContract.pending_organization_id == organization.id,
    ).one_or_none()
    if contract is None:
        raise SubscriptionDiagnosticError("contract_link_mismatch", "The tenant link does not resolve to its organization contract.")
    if contract.school_group_id is not None:
        if int(contract.school_group_id) == int(school_group.id):
            return diagnose_subscription_relationships(db, email=email, organization_uuid=organization_uuid)
        raise SubscriptionDiagnosticError("contract_school_group_mismatch", "The contract is linked to a different workspace.")
    subscriptions = [
        row for row in rows["subscriptions"]
        if _clean(row.status).lower() in entitlement_service.ENTITLED_SUBSCRIPTION_STATUSES
        and int(row.subscription_contract_id) == int(contract.id)
    ]
    if len(subscriptions) != 1:
        raise SubscriptionDiagnosticError("ambiguous_active_subscription", "Exactly one active contract subscription is required.")
    subscription = subscriptions[0]
    if (
        not _clean(subscription.provider_subscription_id)
        or int(subscription.plan_id) != int(contract.plan_id)
        or _clean(subscription.billing_interval).lower() != _clean(contract.billing_interval).lower()
        or int(subscription.quantity or 0) <= 0
        or _clean(contract.contract_status).lower() != "tenant_active"
        or _clean(contract.payment_status).lower() != "paid"
        or contract.paid_at is None
    ):
        raise SubscriptionDiagnosticError("commercial_evidence_incomplete", "Confirmed contract and subscription evidence is incomplete.")
    price_matches = db.query(models.SubscriptionPlanPrice).filter(
        models.SubscriptionPlanPrice.plan_id == subscription.plan_id,
        models.SubscriptionPlanPrice.billing_interval == subscription.billing_interval,
        models.SubscriptionPlanPrice.currency_code == _clean(subscription.currency_code).upper(),
        models.SubscriptionPlanPrice.provider_price_id == subscription.provider_price_id,
        models.SubscriptionPlanPrice.is_active == True,
    ).all()
    if len(price_matches) != 1:
        raise SubscriptionDiagnosticError("provider_price_relationship_invalid", "The active provider price relationship is not exact.")
    confirmed_attempts = [
        row for row in rows["attempts"]
        if _clean(row.status).lower() == "payment_confirmed"
        and _clean(row.provider_subscription_id) == _clean(subscription.provider_subscription_id)
        and _clean(row.provider_price_id) == _clean(subscription.provider_price_id)
        and _clean(row.billing_interval).lower() == _clean(subscription.billing_interval).lower()
        and int(row.quantity or 0) == int(subscription.quantity or 0)
    ]
    if len(confirmed_attempts) != 1:
        raise SubscriptionDiagnosticError(
            "confirmed_payment_attempt_mismatch",
            "Exactly one confirmed payment attempt must match the subscription, price, interval, and quantity.",
        )
    account_links = [
        row for row in rows["account_links"]
        if int(row.pending_organization_id or 0) == int(organization.id)
        and int(row.school_group_id) == int(school_group.id)
    ]
    if len(account_links) != 1:
        raise SubscriptionDiagnosticError("account_tenant_link_ambiguous", "The account-to-tenant relationship is not exact.")
    if subscription.payment_customer_id:
        customer = db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.id == subscription.payment_customer_id,
            models.PaymentCustomer.saas_account_id == account.id,
        ).one_or_none()
        if customer is None or (
            customer.pending_organization_id is not None
            and int(customer.pending_organization_id) != int(organization.id)
        ):
            raise SubscriptionDiagnosticError("payment_customer_scope_mismatch", "The payment customer is scoped elsewhere.")

    contract.school_group_id = school_group.id
    db.flush()
    return diagnose_subscription_relationships(db, email=email, organization_uuid=organization_uuid)
