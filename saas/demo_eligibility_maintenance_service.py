from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models as operational_models
from saas import demo_request_service, models, service


logger = logging.getLogger(__name__)

MAINTENANCE_REASON = "Historical detached demo eligibility cleanup"


class DemoEligibilityMaintenanceBlocked(ValueError):
    pass


@dataclass(frozen=True)
class DemoEligibilityMaintenanceAnalysis:
    eligibility_id: int
    normalized_domain: str
    status: str
    demo_request_id: int | None
    created_at: datetime | None
    updated_at: datetime | None
    manual_review_reason: str
    safe_to_remove: bool
    blockers: tuple[str, ...]
    pending_organization_ids: tuple[int, ...]
    saas_account_ids: tuple[int, ...]
    demo_request_ids: tuple[int, ...]
    workspace_ids: tuple[int, ...]
    provisioning_record_ids: tuple[int, ...]
    subscription_record_ids: tuple[int, ...]
    conversion_ids: tuple[int, ...]

    @property
    def blocker_summary(self) -> str:
        return "; ".join(self.blockers) if self.blockers else "No linked records"


@dataclass(frozen=True)
class DemoEligibilityMaintenanceResult:
    eligibility_id: int
    normalized_domain: str
    previous_status: str


def _unique_ids(values) -> tuple[int, ...]:
    return tuple(sorted({int(value) for value in values if value is not None}))


def _matching_organizations_and_accounts(
    db: Session,
    normalized_domain: str,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    accounts = db.query(models.SaaSAccount).all()
    accounts_by_id = {int(account.id): account for account in accounts}
    matching_account_ids = {
        int(account.id)
        for account in accounts
        if service.normalize_organization_domain(
            str(account.email_normalized or account.email or "")
        )
        == normalized_domain
    }

    matching_organization_ids = set()
    for organization in db.query(models.PendingOrganization).all():
        account = accounts_by_id.get(int(organization.owner_saas_account_id))
        if account:
            resolution = demo_request_service.describe_customer_demo_domain_resolution(
                account,
                organization,
            )
            organization_domain = str(resolution.get("resolved_domain") or "")
        else:
            organization_domain = (
                service.normalize_organization_domain(organization.primary_domain)
                or service.normalize_organization_domain(organization.website)
            )
        if organization_domain == normalized_domain:
            matching_organization_ids.add(int(organization.id))
            matching_account_ids.add(int(organization.owner_saas_account_id))

    return (
        _unique_ids(matching_organization_ids),
        _unique_ids(matching_account_ids),
    )


def analyze_eligibility(
    db: Session,
    eligibility_id: int,
    *,
    lock_row: bool = False,
) -> DemoEligibilityMaintenanceAnalysis:
    query = db.query(models.SaaSDemoDomainEligibility).filter(
        models.SaaSDemoDomainEligibility.id == int(eligibility_id)
    )
    if lock_row:
        query = query.with_for_update()
    eligibility = query.first()
    if not eligibility:
        raise DemoEligibilityMaintenanceBlocked(
            "The demo eligibility reservation no longer exists."
        )

    normalized_domain = service.normalize_organization_domain(
        eligibility.normalized_domain
    )
    pending_organization_ids, saas_account_ids = (
        _matching_organizations_and_accounts(db, normalized_domain)
        if normalized_domain
        else ((), ())
    )

    request_filters = [
        models.SaaSDemoRequest.organization_domain_normalized == normalized_domain
    ]
    if eligibility.demo_request_id:
        request_filters.append(
            models.SaaSDemoRequest.id == int(eligibility.demo_request_id)
        )
    demo_requests = (
        db.query(models.SaaSDemoRequest)
        .filter(or_(*request_filters))
        .all()
        if normalized_domain
        else []
    )
    demo_request_ids = _unique_ids(row.id for row in demo_requests)
    saas_account_ids = _unique_ids(
        [
            *saas_account_ids,
            *(row.requester_saas_account_id for row in demo_requests),
        ]
    )

    tenant_link_filters = []
    if pending_organization_ids:
        tenant_link_filters.append(
            models.TenantProvisioningLink.pending_organization_id.in_(
                pending_organization_ids
            )
        )
    if demo_request_ids:
        tenant_link_filters.append(
            models.TenantProvisioningLink.demo_request_id.in_(demo_request_ids)
        )
    tenant_links = (
        db.query(models.TenantProvisioningLink)
        .filter(or_(*tenant_link_filters))
        .all()
        if tenant_link_filters
        else []
    )

    profile_workspace_ids = {
        int(profile.school_group_id)
        for profile in db.query(operational_models.TenantProfile).all()
        if service.normalize_organization_domain(profile.website)
        == normalized_domain
    }
    workspace_ids = _unique_ids(
        [
            *profile_workspace_ids,
            *(row.school_group_id for row in demo_requests),
            *(row.school_group_id for row in tenant_links),
        ]
    )

    demo_provisioning_rows = (
        db.query(models.SaaSDemoWorkspaceProvisioning)
        .filter(
            or_(
                models.SaaSDemoWorkspaceProvisioning.demo_request_id.in_(
                    demo_request_ids
                )
                if demo_request_ids
                else False,
                models.SaaSDemoWorkspaceProvisioning.school_group_id.in_(workspace_ids)
                if workspace_ids
                else False,
            )
        )
        .all()
        if demo_request_ids or workspace_ids
        else []
    )
    paid_provisioning_rows = (
        db.query(models.ProvisioningJob)
        .filter(
            models.ProvisioningJob.pending_organization_id.in_(
                pending_organization_ids
            )
        )
        .all()
        if pending_organization_ids
        else []
    )
    provisioning_record_ids = _unique_ids(
        [
            *(row.id for row in demo_provisioning_rows),
            *(row.id for row in paid_provisioning_rows),
        ]
    )

    contract_rows = (
        db.query(models.SubscriptionContract)
        .filter(
            or_(
                models.SubscriptionContract.pending_organization_id.in_(
                    pending_organization_ids
                )
                if pending_organization_ids
                else False,
                models.SubscriptionContract.school_group_id.in_(workspace_ids)
                if workspace_ids
                else False,
            )
        )
        .all()
        if pending_organization_ids or workspace_ids
        else []
    )
    contract_ids = _unique_ids(row.id for row in contract_rows)
    subscription_rows = (
        db.query(models.PaymentSubscription)
        .filter(
            or_(
                models.PaymentSubscription.pending_organization_id.in_(
                    pending_organization_ids
                )
                if pending_organization_ids
                else False,
                models.PaymentSubscription.subscription_contract_id.in_(contract_ids)
                if contract_ids
                else False,
            )
        )
        .all()
        if pending_organization_ids or contract_ids
        else []
    )
    subscription_record_ids = _unique_ids(
        [
            *(row.id for row in contract_rows),
            *(row.id for row in subscription_rows),
        ]
    )

    conversion_rows = (
        db.query(models.SaaSDemoToPaidConversion)
        .filter(
            or_(
                models.SaaSDemoToPaidConversion.pending_organization_id.in_(
                    pending_organization_ids
                )
                if pending_organization_ids
                else False,
                models.SaaSDemoToPaidConversion.demo_request_id.in_(
                    demo_request_ids
                )
                if demo_request_ids
                else False,
                models.SaaSDemoToPaidConversion.school_group_id.in_(workspace_ids)
                if workspace_ids
                else False,
            )
        )
        .all()
        if pending_organization_ids or demo_request_ids or workspace_ids
        else []
    )
    conversion_ids = _unique_ids(row.id for row in conversion_rows)

    blockers = []
    if not normalized_domain:
        blockers.append("The normalized domain is missing or invalid")
    if eligibility.demo_request_id is not None:
        blockers.append(
            f"Eligibility is linked to Demo Request {int(eligibility.demo_request_id)}"
        )
    if (
        str(eligibility.status or "").strip() == "manual_review"
        or str(eligibility.manual_review_reason or "").strip()
    ):
        blockers.append("Reservation contains manual-review evidence")
    if pending_organization_ids:
        blockers.append(
            f"Pending organization exists ({', '.join(map(str, pending_organization_ids))})"
        )
    if saas_account_ids:
        blockers.append(
            f"TIS Account exists ({', '.join(map(str, saas_account_ids))})"
        )
    if demo_request_ids:
        blockers.append(
            f"Demo Request exists ({', '.join(map(str, demo_request_ids))})"
        )
    if workspace_ids:
        blockers.append(
            f"Operational workspace exists ({', '.join(map(str, workspace_ids))})"
        )
    if provisioning_record_ids:
        blockers.append(
            "Provisioning record exists "
            f"({', '.join(map(str, provisioning_record_ids))})"
        )
    if subscription_record_ids:
        blockers.append(
            "Subscription record exists "
            f"({', '.join(map(str, subscription_record_ids))})"
        )
    if conversion_ids:
        blockers.append(
            f"Demo-to-Paid conversion exists ({', '.join(map(str, conversion_ids))})"
        )

    return DemoEligibilityMaintenanceAnalysis(
        eligibility_id=int(eligibility.id),
        normalized_domain=normalized_domain,
        status=str(eligibility.status or ""),
        demo_request_id=(
            int(eligibility.demo_request_id)
            if eligibility.demo_request_id is not None
            else None
        ),
        created_at=eligibility.created_at,
        updated_at=eligibility.updated_at,
        manual_review_reason=str(eligibility.manual_review_reason or ""),
        safe_to_remove=not blockers,
        blockers=tuple(blockers),
        pending_organization_ids=pending_organization_ids,
        saas_account_ids=saas_account_ids,
        demo_request_ids=demo_request_ids,
        workspace_ids=workspace_ids,
        provisioning_record_ids=provisioning_record_ids,
        subscription_record_ids=subscription_record_ids,
        conversion_ids=conversion_ids,
    )


def list_eligibility_analyses(
    db: Session,
) -> list[DemoEligibilityMaintenanceAnalysis]:
    eligibility_ids = [
        int(row_id)
        for (row_id,) in db.query(models.SaaSDemoDomainEligibility.id)
        .order_by(models.SaaSDemoDomainEligibility.id)
        .all()
    ]
    return [
        analyze_eligibility(db, eligibility_id)
        for eligibility_id in eligibility_ids
    ]


def delete_safe_orphan(
    db: Session,
    eligibility_id: int,
) -> DemoEligibilityMaintenanceResult:
    analysis = analyze_eligibility(db, eligibility_id, lock_row=True)
    if not analysis.safe_to_remove:
        logger.info(
            "demo_eligibility_maintenance deletion_blocked eligibility_id=%s "
            "normalized_domain=%s blockers=%s",
            analysis.eligibility_id,
            analysis.normalized_domain,
            analysis.blockers,
        )
        raise DemoEligibilityMaintenanceBlocked(analysis.blocker_summary)

    affected_rows = int(
        db.query(models.SaaSDemoDomainEligibility)
        .filter(
            models.SaaSDemoDomainEligibility.id == analysis.eligibility_id
        )
        .delete(synchronize_session=False)
        or 0
    )
    if affected_rows != 1:
        raise DemoEligibilityMaintenanceBlocked(
            "The selected reservation changed before deletion. No data was changed."
        )

    db.flush()
    verification_count = int(
        db.query(models.SaaSDemoDomainEligibility)
        .filter(
            models.SaaSDemoDomainEligibility.id == analysis.eligibility_id
        )
        .count()
        or 0
    )
    if verification_count:
        raise DemoEligibilityMaintenanceBlocked(
            "The reservation could not be verified as deleted. No data was changed."
        )

    logger.info(
        "demo_eligibility_maintenance deletion_verified eligibility_id=%s "
        "normalized_domain=%s affected_rows=%s verification_remaining_count=%s",
        analysis.eligibility_id,
        analysis.normalized_domain,
        affected_rows,
        verification_count,
    )
    return DemoEligibilityMaintenanceResult(
        eligibility_id=analysis.eligibility_id,
        normalized_domain=analysis.normalized_domain,
        previous_status=analysis.status,
    )
