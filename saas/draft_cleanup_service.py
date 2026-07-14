import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import audit
import auth
import public_url
from saas import draft_lifecycle_service, models


_PROCESS_LOCK = threading.Lock()


@dataclass(frozen=True)
class CleanupEligibility:
    outcome: str
    reason: str
    lifecycle: draft_lifecycle_service.DraftLifecycleResult

    @property
    def eligible(self) -> bool:
        return self.outcome == "eligible"


@dataclass(frozen=True)
class DraftDeletionResult:
    account_uuid: str
    organization_uuid: str
    normalized_email: str
    deleted_records: int
    record_counts: dict[str, int]


@dataclass
class CleanupBatchResult:
    scanned: int = 0
    eligible: int = 0
    deleted: int = 0
    skipped: int = 0
    manual_review: int = 0
    failed: int = 0
    dry_run_candidates: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _single_organization(db: Session, account):
    organizations = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account.id
    ).order_by(models.PendingOrganization.id.asc()).all()
    return organizations[0] if len(organizations) == 1 else None


def resolve_cleanup_eligibility(
    db: Session,
    account,
    *,
    now: datetime | None = None,
    deletion_after_override: timedelta | None = None,
) -> CleanupEligibility:
    now = now or _utcnow()
    organization = _single_organization(db, account)
    lifecycle = draft_lifecycle_service.resolve_draft_lifecycle(
        db,
        account,
        organization=organization,
        now=now,
        deletion_after_override=deletion_after_override,
    )
    if lifecycle.deletion_status == "manual_review" or lifecycle.warnings:
        return CleanupEligibility("manual_review", "ambiguous_or_unresolved_relationship", lifecycle)
    if not lifecycle.deletion_eligible:
        return CleanupEligibility("ineligible", "lifecycle_ineligible", lifecycle)
    final_sent_at = getattr(account, "final_reminder_sent_at", None)
    if final_sent_at is None or final_sent_at < lifecycle.effective_activity_at:
        return CleanupEligibility("ineligible", "final_reminder_required", lifecycle)
    return CleanupEligibility("eligible", "eligible", lifecycle)


def _safe_identity(account, organization) -> dict:
    return {
        "account_uuid": str(getattr(account, "account_uuid", "") or ""),
        "organization_uuid": str(getattr(organization, "organization_uuid", "") or ""),
        "normalized_email": auth.normalize_email(
            str(getattr(account, "email_normalized", "") or getattr(account, "email", "") or "")
        ),
        "reminder_cycle": int(getattr(account, "reminder_cycle", 1) or 1),
    }


def _audit_event(event_type: str, *, identity: dict, **details):
    audit.write_audit_event({
        "event_type": event_type,
        "source": "abandoned_draft_cleanup",
        **identity,
        **details,
    })


def _record_counts(db: Session, account, organization) -> dict[str, int]:
    account_id = int(account.id)
    organization_id = int(organization.id) if organization is not None else None
    organization_filter = (
        models.PendingOrganization.id == organization_id if organization_id is not None else False
    )
    counts = {
        "saas_accounts": 1,
        "saas_sessions": db.query(models.SaaSSession).filter_by(saas_account_id=account_id).count(),
        "email_verification_tokens": db.query(models.SaaSEmailVerificationToken).filter_by(saas_account_id=account_id).count(),
        "password_reset_tokens": db.query(models.SaaSPasswordResetToken).filter_by(saas_account_id=account_id).count(),
        "auth_identities": db.query(models.SaaSAuthIdentity).filter_by(saas_account_id=account_id).count(),
        "auth_events": db.query(models.SaaSAuthEvent).filter_by(saas_account_id=account_id).count(),
        "pending_organizations": db.query(models.PendingOrganization).filter(organization_filter).count() if organization_id else 0,
    }
    if organization_id is None:
        counts["payment_customers"] = db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.saas_account_id == account_id,
            models.PaymentCustomer.pending_organization_id.is_(None),
        ).count()
        return counts
    scoped_models = (
        ("pending_branches", models.PendingOrganizationBranch),
        ("academic_setup", models.PendingOrganizationAcademicSetup),
        ("contacts", models.PendingOrganizationContact),
        ("progress", models.PendingOrganizationProgress),
        ("notes", models.PendingOrganizationNote),
        ("pending_events", models.PendingOrganizationEvent),
        ("plan_selections", models.PendingOrganizationPlanSelection),
        ("checkout_sessions", models.CheckoutSession),
        ("payment_attempts", models.PaymentAttempt),
        ("subscription_contracts", models.SubscriptionContract),
        ("provisioning_jobs", models.ProvisioningJob),
    )
    for key, model in scoped_models:
        counts[key] = db.query(model).filter(
            model.pending_organization_id == organization_id
        ).count()
    job_ids = [
        row[0] for row in db.query(models.ProvisioningJob.id).filter(
            models.ProvisioningJob.pending_organization_id == organization_id
        ).all()
    ]
    counts["provisioning_job_events"] = (
        db.query(models.ProvisioningJobEvent).filter(
            models.ProvisioningJobEvent.provisioning_job_id.in_(job_ids)
        ).count() if job_ids else 0
    )
    counts["payment_customers"] = db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account_id,
        or_(
            models.PaymentCustomer.pending_organization_id == organization_id,
            models.PaymentCustomer.pending_organization_id.is_(None),
        ),
    ).count()
    return counts


def _delete(query) -> int:
    return int(query.delete(synchronize_session=False) or 0)


def _delete_eligible_draft(db: Session, account, organization) -> DraftDeletionResult:
    account_id = int(account.id)
    organization_id = int(organization.id) if organization is not None else None
    identity = _safe_identity(account, organization)
    counts = _record_counts(db, account, organization)
    deleted = 0

    if organization_id is not None:
        job_ids = [
            row[0] for row in db.query(models.ProvisioningJob.id).filter(
                models.ProvisioningJob.pending_organization_id == organization_id
            ).all()
        ]
        db.query(models.PendingOrganization).filter_by(id=organization_id).update(
            {models.PendingOrganization.last_payment_attempt_id: None},
            synchronize_session=False,
        )
        db.query(models.CheckoutSession).filter_by(pending_organization_id=organization_id).update(
            {models.CheckoutSession.last_payment_attempt_id: None},
            synchronize_session=False,
        )
        db.query(models.SubscriptionContract).filter_by(pending_organization_id=organization_id).update(
            {models.SubscriptionContract.selected_checkout_session_id: None},
            synchronize_session=False,
        )
        if job_ids:
            deleted += _delete(db.query(models.ProvisioningJobEvent).filter(
                models.ProvisioningJobEvent.provisioning_job_id.in_(job_ids)
            ))
        deleted += _delete(db.query(models.ProvisioningJob).filter_by(
            pending_organization_id=organization_id
        ))
        deleted += _delete(db.query(models.PaymentAttempt).filter_by(
            pending_organization_id=organization_id
        ))
        deleted += _delete(db.query(models.CheckoutSession).filter_by(
            pending_organization_id=organization_id
        ))
        deleted += _delete(db.query(models.SubscriptionContract).filter_by(
            pending_organization_id=organization_id
        ))
        deleted += _delete(db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.saas_account_id == account_id,
            or_(
                models.PaymentCustomer.pending_organization_id == organization_id,
                models.PaymentCustomer.pending_organization_id.is_(None),
            ),
        ))
        deleted += _delete(db.query(models.PendingOrganizationPlanSelection).filter_by(
            pending_organization_id=organization_id
        ))
        for child_model in (
            models.PendingOrganizationBranch,
            models.PendingOrganizationAcademicSetup,
            models.PendingOrganizationContact,
            models.PendingOrganizationProgress,
            models.PendingOrganizationNote,
            models.PendingOrganizationEvent,
        ):
            deleted += _delete(db.query(child_model).filter(
                child_model.pending_organization_id == organization_id
            ))
        deleted += _delete(db.query(models.PendingOrganization).filter_by(id=organization_id))
    else:
        deleted += _delete(db.query(models.PaymentCustomer).filter(
            models.PaymentCustomer.saas_account_id == account_id,
            models.PaymentCustomer.pending_organization_id.is_(None),
        ))

    deleted += _delete(db.query(models.SaaSAccountUserLink).filter_by(saas_account_id=account_id))
    deleted += _delete(db.query(models.SaaSSession).filter_by(saas_account_id=account_id))
    deleted += _delete(db.query(models.SaaSEmailVerificationToken).filter_by(saas_account_id=account_id))
    deleted += _delete(db.query(models.SaaSPasswordResetToken).filter_by(saas_account_id=account_id))
    deleted += _delete(db.query(models.SaaSAuthIdentity).filter_by(saas_account_id=account_id))
    deleted += _delete(db.query(models.SaaSAuthEvent).filter_by(saas_account_id=account_id))
    deleted += _delete(db.query(models.SaaSAccount).filter_by(id=account_id))
    db.flush()
    return DraftDeletionResult(
        account_uuid=identity["account_uuid"],
        organization_uuid=identity["organization_uuid"],
        normalized_email=identity["normalized_email"],
        deleted_records=deleted,
        record_counts=counts,
    )


def _deletion_override(max_inactivity_days: int | None) -> timedelta | None:
    if max_inactivity_days is None:
        return None
    if public_url.is_production_like_environment():
        raise ValueError("The inactivity override is disabled in production-like environments.")
    try:
        days = int(max_inactivity_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("The inactivity override must be a positive number of days.") from exc
    if days <= 0:
        raise ValueError("The inactivity override must be a positive number of days.")
    return timedelta(days=days)


def process_abandoned_draft_cleanup(
    session_factory,
    *,
    dry_run: bool = False,
    batch_size: int = 100,
    account_email: str | None = None,
    max_inactivity_days: int | None = None,
    now: datetime | None = None,
) -> CleanupBatchResult:
    try:
        batch_size = int(batch_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("Batch size must be a positive integer.") from exc
    if batch_size <= 0 or batch_size > 1000:
        raise ValueError("Batch size must be between 1 and 1000.")
    normalized_target = auth.normalize_email(account_email)
    if account_email and not normalized_target:
        raise ValueError("Target account email is invalid.")
    override = _deletion_override(max_inactivity_days)
    now = now or _utcnow()
    result = CleanupBatchResult()

    with _PROCESS_LOCK:
        scan_db = session_factory()
        try:
            threshold = override or draft_lifecycle_service.get_retention_settings(scan_db).deletion_after
            cutoff = now - threshold
            query = scan_db.query(
                models.SaaSAccount.id,
                models.SaaSAccount.last_meaningful_activity_at,
                func.max(models.PendingOrganization.last_meaningful_activity_at),
            ).outerjoin(
                models.PendingOrganization,
                models.PendingOrganization.owner_saas_account_id == models.SaaSAccount.id,
            ).filter(or_(
                models.SaaSAccount.last_meaningful_activity_at <= cutoff,
                models.PendingOrganization.last_meaningful_activity_at <= cutoff,
            ))
            if normalized_target:
                query = query.filter(models.SaaSAccount.email_normalized == normalized_target)
            scanned_rows = query.group_by(
                models.SaaSAccount.id,
                models.SaaSAccount.last_meaningful_activity_at,
            ).order_by(models.SaaSAccount.id.asc()).limit(batch_size).all()
            snapshots = {
                int(row[0]): max(value for value in (row[1], row[2]) if value is not None)
                for row in scanned_rows
            }
        finally:
            scan_db.close()

        if normalized_target and not snapshots:
            result.skipped = 1
            return result

        for account_id, scanned_activity in snapshots.items():
            result.scanned += 1
            db = session_factory()
            post_commit_event = None
            identity = {
                "account_uuid": "",
                "organization_uuid": "",
                "normalized_email": normalized_target or "",
                "reminder_cycle": 0,
            }
            committed = False
            try:
                with db.begin():
                    account = db.query(models.SaaSAccount).filter(
                        models.SaaSAccount.id == account_id
                    ).with_for_update(skip_locked=True).first()
                    if account is None:
                        result.skipped += 1
                    else:
                        organizations = db.query(models.PendingOrganization).filter(
                            models.PendingOrganization.owner_saas_account_id == account.id
                        ).with_for_update().all()
                        organization = organizations[0] if len(organizations) == 1 else None
                        identity = _safe_identity(account, organization)
                        eligibility = resolve_cleanup_eligibility(
                            db,
                            account,
                            now=now,
                            deletion_after_override=override,
                        )
                        locked_activity = eligibility.lifecycle.effective_activity_at
                        if scanned_activity is not None and locked_activity > scanned_activity:
                            post_commit_event = (
                                "draft_cleanup_recovered_before_delete",
                                identity,
                                {"result": "skipped", "reason": "meaningful_activity_recorded"},
                            )
                            result.skipped += 1
                        elif eligibility.outcome == "manual_review":
                            post_commit_event = (
                                "draft_cleanup_manual_review",
                                identity,
                                {"result": "manual_review", "reason": eligibility.reason},
                            )
                            result.manual_review += 1
                        elif not eligibility.eligible:
                            post_commit_event = (
                                "draft_cleanup_skipped_ineligible",
                                identity,
                                {"result": "skipped", "reason": eligibility.reason},
                            )
                            result.skipped += 1
                        else:
                            result.eligible += 1
                            if dry_run:
                                result.dry_run_candidates += 1
                            else:
                                _audit_event(
                                    "draft_cleanup_candidate",
                                    identity=identity,
                                    inactivity_hours=int((now - eligibility.lifecycle.effective_activity_at).total_seconds() // 3600),
                                    deletion_threshold_days=int((override or draft_lifecycle_service.get_retention_settings(db).deletion_after).days),
                                    result="candidate",
                                )
                                final_check = resolve_cleanup_eligibility(
                                    db,
                                    account,
                                    now=now,
                                    deletion_after_override=override,
                                )
                                if not final_check.eligible:
                                    post_commit_event = (
                                        "draft_cleanup_recovered_before_delete",
                                        identity,
                                        {"result": "skipped", "reason": final_check.reason},
                                    )
                                    result.skipped += 1
                                else:
                                    deletion = _delete_eligible_draft(db, account, organization)
                                    post_commit_event = (
                                        "draft_cleanup_deleted",
                                        identity,
                                        {
                                            "result": "deleted",
                                            "deleted_records": deletion.deleted_records,
                                            "record_counts": deletion.record_counts,
                                        },
                                    )
                committed = True
            except Exception as exc:
                db.rollback()
                result.failed += 1
                try:
                    _audit_event(
                        "draft_cleanup_failed_rolled_back",
                        identity=identity,
                        result="failed_rolled_back",
                        failure_type=exc.__class__.__name__,
                    )
                except Exception:
                    pass
            finally:
                db.close()
            if committed and post_commit_event:
                if post_commit_event[0] == "draft_cleanup_deleted":
                    result.deleted += 1
                try:
                    _audit_event(
                        post_commit_event[0],
                        identity=post_commit_event[1],
                        **post_commit_event[2],
                    )
                except Exception:
                    result.failed += 1
    return result
