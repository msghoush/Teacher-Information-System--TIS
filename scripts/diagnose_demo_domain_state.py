"""Read-only Customer Demo domain-state diagnostic.

Examples:
    python scripts/diagnose_demo_domain_state.py --domain his.edu.lb
    python scripts/diagnose_demo_domain_state.py --email administrator@his.edu.lb
    python scripts/diagnose_demo_domain_state.py --domain his.edu.lb --organization-uuid <uuid>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import models as operational_models
from sqlalchemy.exc import SQLAlchemyError
from database import SessionLocal
from saas import demo_request_service, models, service, workspace_analysis_service


def _record(row, *fields: str) -> dict[str, object]:
    return {field: getattr(row, field, None) for field in fields}


def _resolve_organizations(db, domain: str) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for organization in db.query(models.PendingOrganization).order_by(
        models.PendingOrganization.id
    ):
        account = db.query(models.SaaSAccount).filter(
            models.SaaSAccount.id == organization.owner_saas_account_id
        ).first()
        if not account:
            continue
        resolution = demo_request_service.describe_customer_demo_domain_resolution(
            account, organization
        )
        try:
            resolved_domain = demo_request_service.resolve_customer_demo_domain(
                db, account, organization
            )
            resolution_error = ""
        except demo_request_service.DemoRequestError as exc:
            resolved_domain = ""
            resolution_error = str(exc)
        if resolved_domain == domain:
            matches.append(
                {
                    "id": organization.id,
                    "organization_uuid": organization.organization_uuid,
                    "status": organization.status,
                    "workspace_intent": organization.workspace_intent,
                    "owner_saas_account_id": organization.owner_saas_account_id,
                    "resolution_source": resolution["resolution_source"],
                    "resolution_error": resolution_error,
                }
            )
    return matches


def _selected_organization(db, *, organization_uuid: str, email: str):
    if organization_uuid:
        return db.query(models.PendingOrganization).filter(
            models.PendingOrganization.organization_uuid == organization_uuid
        ).first()
    if email:
        account = db.query(models.SaaSAccount).filter(
            models.SaaSAccount.email_normalized == email.strip().lower()
        ).first()
        if account:
            return db.query(models.PendingOrganization).filter(
                models.PendingOrganization.owner_saas_account_id == account.id
            ).order_by(models.PendingOrganization.id.desc()).first()
    return None


def build_report(db, *, domain: str, email: str = "", organization_uuid: str = "") -> dict[str, object]:
    normalized_domain = service.normalize_organization_domain(domain or email)
    if not normalized_domain:
        raise ValueError("Provide a valid --domain or --email value.")

    matching_organizations = _resolve_organizations(db, normalized_domain)
    organization_ids = [int(row["id"]) for row in matching_organizations]
    eligibility_rows = db.query(models.SaaSDemoDomainEligibility).filter(
        models.SaaSDemoDomainEligibility.normalized_domain == normalized_domain
    ).all()
    direct_requests = db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.organization_domain_normalized == normalized_domain
    ).all()
    organization_requests = (
        db.query(models.SaaSDemoRequest).filter(
            models.SaaSDemoRequest.pending_organization_id.in_(organization_ids)
        ).all()
        if organization_ids
        else []
    )
    request_rows = {int(row.id): row for row in [*direct_requests, *organization_requests]}
    request_ids = list(request_rows)
    account_rows = [
        account
        for account in db.query(models.SaaSAccount).all()
        if service.normalize_organization_domain(account.email) == normalized_domain
    ]
    links = (
        db.query(models.TenantProvisioningLink).filter(
            (models.TenantProvisioningLink.pending_organization_id.in_(organization_ids))
            | (models.TenantProvisioningLink.demo_request_id.in_(request_ids))
        ).all()
        if organization_ids or request_ids
        else []
    )
    school_group_ids = [int(link.school_group_id) for link in links if link.school_group_id]
    school_groups = (
        db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id.in_(school_group_ids)
        ).all()
        if school_group_ids
        else []
    )
    demo_provisioning_rows = (
        db.query(models.SaaSDemoWorkspaceProvisioning).filter(
            models.SaaSDemoWorkspaceProvisioning.demo_request_id.in_(request_ids)
        ).all()
        if request_ids
        else []
    )
    contracts = (
        db.query(models.SubscriptionContract).filter(
            models.SubscriptionContract.pending_organization_id.in_(organization_ids)
        ).all()
        if organization_ids
        else []
    )
    subscriptions = (
        db.query(models.PaymentSubscription).filter(
            models.PaymentSubscription.pending_organization_id.in_(organization_ids)
        ).all()
        if organization_ids
        else []
    )
    conversions = (
        db.query(models.SaaSDemoToPaidConversion).filter(
            (models.SaaSDemoToPaidConversion.pending_organization_id.in_(organization_ids))
            | (models.SaaSDemoToPaidConversion.demo_request_id.in_(request_ids))
        ).all()
        if organization_ids or request_ids
        else []
    )
    selected = _selected_organization(
        db, organization_uuid=organization_uuid, email=email
    )
    clean_room = (
        workspace_analysis_service.analyze_orphaned_demo_domain_cleanup(db, selected)
        if selected
        else None
    )
    if eligibility_rows:
        exact_blocker = {
            "stage": "existing_eligibility_lookup",
            "reason": "A matching saas_demo_domain_eligibilities row exists before reservation insert.",
        }
    else:
        exact_blocker = {
            "stage": "not_observable_without_attempt_log",
            "reason": "No existing reservation is present; inspect the new submit-demo diagnostics for an insert or request flush failure.",
        }

    return {
        "read_only": True,
        "normalized_domain": normalized_domain,
        "selected_organization_id": getattr(selected, "id", None),
        "selected_organization_uuid": getattr(selected, "organization_uuid", None),
        "eligibility_reservations": [
            {
                **_record(
                    row,
                    "id",
                    "normalized_domain",
                    "status",
                    "demo_request_id",
                    "manual_review_reason",
                    "created_at",
                    "updated_at",
                ),
                "link_state": "linked" if row.demo_request_id else "detached",
            }
            for row in eligibility_rows
        ],
        "pending_organizations": matching_organizations,
        "saas_accounts": [
            _record(row, "id", "account_uuid", "status", "account_purpose", "created_at", "updated_at")
            for row in account_rows
        ],
        "demo_requests": [
            _record(
                row,
                "id",
                "request_uuid",
                "status",
                "pending_organization_id",
                "requester_saas_account_id",
                "school_group_id",
                "organization_domain_normalized",
                "submitted_at",
                "updated_at",
            )
            for row in request_rows.values()
        ],
        "provisioning_records": [
            _record(row, "id", "demo_request_id", "school_group_id", "provisioning_status", "lifecycle_processing_status", "created_at", "updated_at")
            for row in demo_provisioning_rows
        ],
        "operational_workspaces": [
            _record(row, "id", "workspace_uuid", "workspace_classification", "workspace_lifecycle_status", "created_at", "updated_at")
            for row in school_groups
        ],
        "subscription_contracts": [
            _record(row, "id", "pending_organization_id", "school_group_id", "contract_status", "payment_status", "created_at", "updated_at")
            for row in contracts
        ],
        "payment_subscriptions": [
            _record(row, "id", "pending_organization_id", "subscription_contract_id", "status", "created_at", "updated_at")
            for row in subscriptions
        ],
        "demo_to_paid_conversions": [
            _record(row, "id", "pending_organization_id", "demo_request_id", "school_group_id", "status", "created_at", "updated_at")
            for row in conversions
        ],
        "clean_room_removal": clean_room,
        "exact_current_blocker": exact_blocker,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Customer Demo domain-state report")
    parser.add_argument("--domain", default="", help="Organization domain or website")
    parser.add_argument("--email", default="", help="Optional account email used to select an organization")
    parser.add_argument("--organization-uuid", default="", help="Optional pending organization UUID")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        try:
            report = build_report(
                db,
                domain=args.domain,
                email=args.email,
                organization_uuid=args.organization_uuid,
            )
        except SQLAlchemyError as exc:
            report = {
                "read_only": True,
                "normalized_domain": service.normalize_organization_domain(
                    args.domain or args.email
                ),
                "diagnostic_error": "The configured database schema is not compatible with the current SaaS models.",
                "exception_type": type(exc).__name__,
                "exception": str(exc),
            }
            print(json.dumps(report, default=str, indent=2, sort_keys=True))
            return 2
        print(json.dumps(report, default=str, indent=2, sort_keys=True))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
