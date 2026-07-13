from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import models


class OrphanedTestAccountDeletionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class OrphanedAccountAnalysis:
    account: object
    classification: str
    status_label: str
    counts: dict[str, int]
    warnings: tuple[str, ...]

    @property
    def safe_to_delete(self) -> bool:
        return self.classification == "orphaned_after_test_reset" and not self.warnings

    @property
    def total_records(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class OrphanedAccountDeletionResult:
    account_id: int
    account_uuid: str
    account_email: str
    analysis_counts: dict[str, int]
    deleted_records: int


def _delete(query) -> int:
    return int(query.delete(synchronize_session=False) or 0)


def analyze_orphaned_account(db: Session, account) -> OrphanedAccountAnalysis:
    account_id = int(account.id)
    normalized_email = auth.normalize_email(str(account.email_normalized or account.email or ""))
    pending_rows = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account_id
    ).all()
    account_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account_id
    ).all()
    payment_customers = db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account_id
    ).all()
    actor_events = db.query(models.PendingOrganizationEvent).filter(
        models.PendingOrganizationEvent.actor_saas_account_id == account_id
    ).all()
    matching_users = db.query(operational_models.User).filter(or_(
        operational_models.User.email_normalized == normalized_email,
        func.lower(operational_models.User.email) == normalized_email,
    )).all()
    platform_users = [user for user in matching_users if auth.is_platform_user(user)]
    tenant_users = [
        user for user in matching_users
        if int(getattr(user, "school_group_id", 0) or 0) > 0
    ]
    tenant_user_ids = [int(user.id) for user in tenant_users]
    provisioning_links = []
    if tenant_user_ids:
        provisioning_links = db.query(models.TenantProvisioningLink).filter(
            models.TenantProvisioningLink.owner_operational_user_id.in_(tenant_user_ids)
        ).all()

    counts = {
        "saas_account": 1,
        "pending_organizations": len(pending_rows),
        "tenant_provisioning_links": len(provisioning_links),
        "saas_account_user_links": len(account_links),
        "operational_users": len(tenant_users),
        "payment_customers": len(payment_customers),
        "pending_organization_actor_events": len(actor_events),
        "saas_sessions": db.query(models.SaaSSession).filter(models.SaaSSession.saas_account_id == account_id).count(),
        "email_verification_tokens": db.query(models.SaaSEmailVerificationToken).filter(models.SaaSEmailVerificationToken.saas_account_id == account_id).count(),
        "password_reset_tokens": db.query(models.SaaSPasswordResetToken).filter(models.SaaSPasswordResetToken.saas_account_id == account_id).count(),
        "external_auth_identities": db.query(models.SaaSAuthIdentity).filter(models.SaaSAuthIdentity.saas_account_id == account_id).count(),
        "saas_auth_events": db.query(models.SaaSAuthEvent).filter(models.SaaSAuthEvent.saas_account_id == account_id).count(),
    }
    warnings: list[str] = []
    if platform_users:
        warnings.append("The account email belongs to a protected Platform Owner or Developer identity.")
        classification = "protected_platform_identity"
        status_label = "Protected/platform identity"
    elif pending_rows:
        has_provisioned_organization = any(
            db.query(models.TenantProvisioningLink).filter(
                models.TenantProvisioningLink.pending_organization_id == row.id
            ).first()
            for row in pending_rows
        )
        has_active_organization_state = any(
            str(getattr(row, "status", "") or "").strip().lower() == "activated"
            or str(getattr(row, "billing_status", "") or "").strip().lower()
            in {
                "payment_confirmed", "ready_for_provisioning", "provisioning_started",
                "provisioning_retrying", "provisioning_completed", "tenant_active",
            }
            for row in pending_rows
        )
        is_active_with_organization = has_provisioned_organization or has_active_organization_state
        classification = "active_with_organization" if is_active_with_organization else "draft_onboarding"
        status_label = "Active with organization" if is_active_with_organization else "Draft/onboarding"
        warnings.append("The account still owns a pending organization.")
    else:
        classification = "orphaned_after_test_reset"
        status_label = "Orphaned after test reset"

    if account_links:
        warnings.append("The account still has an operational account-user link.")
    if tenant_users:
        warnings.append("An operational user with this email still belongs to a tenant.")
    if provisioning_links:
        warnings.append("An operational user with this email still owns a provisioned tenant.")
    if any(getattr(row, "pending_organization_id", None) is not None for row in payment_customers):
        warnings.append("A local payment-customer mapping is associated with an organization.")
    if actor_events:
        warnings.append("The account is referenced by another pending-organization event.")

    if warnings and classification == "orphaned_after_test_reset":
        classification = "manual_review_required"
        status_label = "Manual review required"
    return OrphanedAccountAnalysis(
        account=account,
        classification=classification,
        status_label=status_label,
        counts=counts,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def list_account_analyses(db: Session) -> list[OrphanedAccountAnalysis]:
    accounts = db.query(models.SaaSAccount).order_by(
        models.SaaSAccount.updated_at.desc(),
        models.SaaSAccount.id.desc(),
    ).all()
    return [analyze_orphaned_account(db, account) for account in accounts]


def delete_orphaned_test_account(
    db: Session,
    account,
    *,
    confirmation_email: str,
    reason: str,
) -> OrphanedAccountDeletionResult:
    analysis = analyze_orphaned_account(db, account)
    if not analysis.safe_to_delete:
        raise OrphanedTestAccountDeletionBlocked(
            "This account is not a safely orphaned test account. Manual review is required."
        )
    if confirmation_email != str(account.email or ""):
        raise OrphanedTestAccountDeletionBlocked(
            "The typed account email does not match. No data was changed."
        )
    if not str(reason or "").strip():
        raise OrphanedTestAccountDeletionBlocked("A deletion reason is required. No data was changed.")

    account_id = int(account.id)
    result = OrphanedAccountDeletionResult(
        account_id=account_id,
        account_uuid=str(account.account_uuid or ""),
        account_email=str(account.email or ""),
        analysis_counts=dict(analysis.counts),
        deleted_records=0,
    )
    deleted = 0
    deleted += _delete(db.query(models.SaaSAccountUserLink).filter(models.SaaSAccountUserLink.saas_account_id == account_id))
    deleted += _delete(db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account_id,
        models.PaymentCustomer.pending_organization_id.is_(None),
    ))
    deleted += _delete(db.query(models.SaaSSession).filter(models.SaaSSession.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSEmailVerificationToken).filter(models.SaaSEmailVerificationToken.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSPasswordResetToken).filter(models.SaaSPasswordResetToken.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSAuthIdentity).filter(models.SaaSAuthIdentity.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSAuthEvent).filter(models.SaaSAuthEvent.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSAccount).filter(models.SaaSAccount.id == account_id))
    db.flush()
    return OrphanedAccountDeletionResult(
        account_id=result.account_id,
        account_uuid=result.account_uuid,
        account_email=result.account_email,
        analysis_counts=result.analysis_counts,
        deleted_records=deleted,
    )
