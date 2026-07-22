from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import uuid

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

import models as operational_models
from saas import models
from workspace_classification import (
    AccountPurpose,
    WorkspaceClassification,
    WorkspaceIntent,
    WorkspaceLifecycleStatus,
)


BACKFILL_MARKER = "20260722_002_workspace_classification_existing_test_data"


@dataclass(frozen=True)
class WorkspaceDiagnostic:
    school_group_id: int
    workspace_uuid: str | None
    workspace_name: str
    current_tenant_status: str
    onboarding_relationship: dict
    paddle_relationship: dict
    current_classification: str | None
    current_lifecycle: str | None
    suggested_classification: str
    suggestion_reason: str


def _subscription_statuses(rows) -> list[str]:
    return sorted({str(row.status or "unknown") for row in rows})


def collect_workspace_diagnostics(db: Session) -> list[dict]:
    report = []
    groups = db.query(operational_models.SchoolGroup).order_by(
        operational_models.SchoolGroup.id.asc()
    ).all()
    for group in groups:
        tenant_link = db.query(models.TenantProvisioningLink).filter(
            models.TenantProvisioningLink.school_group_id == group.id
        ).first()
        contracts = db.query(models.SubscriptionContract).filter(
            models.SubscriptionContract.school_group_id == group.id
        ).order_by(models.SubscriptionContract.id.asc()).all()
        organization_id = (
            tenant_link.pending_organization_id
            if tenant_link
            else (contracts[-1].pending_organization_id if contracts else None)
        )
        organization = (
            db.query(models.PendingOrganization).filter(
                models.PendingOrganization.id == organization_id
            ).first()
            if organization_id
            else None
        )
        subscriptions = []
        if organization_id:
            subscriptions = db.query(models.PaymentSubscription).filter(
                models.PaymentSubscription.pending_organization_id == organization_id
            ).order_by(models.PaymentSubscription.id.asc()).all()
        provider_customer_count = 0
        if organization_id:
            provider_customer_count = db.query(models.PaymentCustomer).filter(
                models.PaymentCustomer.pending_organization_id == organization_id,
                models.PaymentCustomer.provider == "paddle",
            ).count()
        row = WorkspaceDiagnostic(
            school_group_id=group.id,
            workspace_uuid=getattr(group, "workspace_uuid", None),
            workspace_name=group.name,
            current_tenant_status="active" if bool(group.status) else "inactive",
            onboarding_relationship={
                "linked": bool(organization),
                "organization_uuid": getattr(organization, "organization_uuid", None),
                "status": getattr(organization, "status", None),
                "workspace_intent": getattr(organization, "workspace_intent", None),
                "tenant_link_status": getattr(tenant_link, "tenant_status", None),
            },
            paddle_relationship={
                "provider": "paddle" if subscriptions or provider_customer_count else None,
                "customer_mapping_count": provider_customer_count,
                "subscription_count": len(subscriptions),
                "subscription_statuses": _subscription_statuses(subscriptions),
                "has_provider_subscription": any(
                    bool(row.provider_subscription_id) for row in subscriptions
                ),
            },
            current_classification=getattr(group, "workspace_classification", None),
            current_lifecycle=getattr(group, "workspace_lifecycle_status", None),
            suggested_classification=WorkspaceClassification.INTERNAL_SANDBOX.value,
            suggestion_reason="M8B-1 confirmed all pre-existing TIS workspaces are test data.",
        )
        report.append(asdict(row))
    return report


def _ensure_backfill_marker_table(db: Session) -> None:
    db.execute(text(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id VARCHAR(120) PRIMARY KEY,
            description VARCHAR(255) NOT NULL,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    ))


def _backfill_already_applied(db: Session) -> bool:
    if "schema_migrations" not in inspect(db.get_bind()).get_table_names():
        return False
    return bool(db.execute(
        text("SELECT 1 FROM schema_migrations WHERE migration_id = :migration_id"),
        {"migration_id": BACKFILL_MARKER},
    ).scalar())


def build_workspace_classification_backfill_plan(db: Session) -> dict:
    if _backfill_already_applied(db):
        return {
            "status": "already_applied",
            "mode": "dry_run",
            "marker": BACKFILL_MARKER,
            "changes": {},
        }

    groups = db.query(operational_models.SchoolGroup).all()
    organizations = db.query(models.PendingOrganization).all()
    accounts = db.query(models.SaaSAccount).all()
    users = db.query(operational_models.User).all()
    return {
        "status": "ready",
        "mode": "dry_run",
        "marker": BACKFILL_MARKER,
        "changes": {
            "school_groups_classification": sum(
                getattr(row, "workspace_classification", None)
                != WorkspaceClassification.INTERNAL_SANDBOX.value
                for row in groups
            ),
            "school_groups_lifecycle": sum(
                getattr(row, "workspace_lifecycle_status", None)
                != (
                    WorkspaceLifecycleStatus.ACTIVE.value
                    if bool(row.status)
                    else WorkspaceLifecycleStatus.SUSPENDED.value
                )
                for row in groups
            ),
            "school_groups_uuid": sum(not getattr(row, "workspace_uuid", None) for row in groups),
            "pending_organization_intent": sum(
                getattr(row, "workspace_intent", None)
                != WorkspaceIntent.INTERNAL_SANDBOX.value
                for row in organizations
            ),
            "saas_account_purpose": sum(
                getattr(row, "account_purpose", None) != AccountPurpose.INTERNAL_TEST.value
                for row in accounts
            ),
            "internal_test_identity": sum(
                str(getattr(row, "user_type", "") or "").upper() != "PLATFORM"
                and not bool(getattr(row, "is_internal_test_identity", False))
                for row in users
            ),
        },
    }


def apply_workspace_classification_backfill(db: Session) -> dict:
    plan = build_workspace_classification_backfill_plan(db)
    if plan["status"] == "already_applied":
        return {**plan, "mode": "apply"}

    _ensure_backfill_marker_table(db)
    for group in db.query(operational_models.SchoolGroup).all():
        if not getattr(group, "workspace_uuid", None):
            group.workspace_uuid = str(uuid.uuid4())
        group.workspace_classification = WorkspaceClassification.INTERNAL_SANDBOX.value
        group.workspace_lifecycle_status = (
            WorkspaceLifecycleStatus.ACTIVE.value
            if bool(group.status)
            else WorkspaceLifecycleStatus.SUSPENDED.value
        )
    for organization in db.query(models.PendingOrganization).all():
        organization.workspace_intent = WorkspaceIntent.INTERNAL_SANDBOX.value
    for account in db.query(models.SaaSAccount).all():
        account.account_purpose = AccountPurpose.INTERNAL_TEST.value
    for user in db.query(operational_models.User).all():
        if str(getattr(user, "user_type", "") or "").upper() != "PLATFORM":
            user.is_internal_test_identity = True

    db.flush()
    db.execute(
        text(
            """
            INSERT INTO schema_migrations (migration_id, description, applied_at)
            VALUES (:migration_id, :description, :applied_at)
            """
        ),
        {
            "migration_id": BACKFILL_MARKER,
            "description": "Backfill all pre-M8B-1 workspaces and onboarding identities as internal sandbox test data",
            "applied_at": datetime.now(UTC).replace(tzinfo=None),
        },
    )
    return {**plan, "status": "applied", "mode": "apply"}
