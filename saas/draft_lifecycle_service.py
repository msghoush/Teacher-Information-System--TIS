import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import models


DEFAULT_FIRST_REMINDER_HOURS = 24
DEFAULT_SECOND_REMINDER_DAYS = 7
DEFAULT_FINAL_REMINDER_DAYS = 25
DEFAULT_DELETION_DAYS = 30

ACTIVE_STATES = {"active", "tenant_active", "provisioning_completed"}
PROVISIONING_STATES = {
    "ready_for_provisioning",
    "provisioning_started",
    "provisioning_retrying",
    "provisioning_completed",
}
PAYMENT_PENDING_STATES = {"payment_processing", "payment_reconciliation_required"}
CHECKOUT_STARTED_STATES = {"checkout_initiated", "checkout_started"}
READY_FOR_CHECKOUT_STATES = {"ready_for_checkout", "plan_selected", "checkout_ready"}
CONFIRMED_ATTEMPT_STATES = {"payment_confirmed", "completed", "paid", "succeeded"}
PENDING_PROVISIONING_STATES = {"queued", "processing", "retrying", "pending"}
ACTIVE_SUBSCRIPTION_STATES = {"active", "trialing", "past_due", "paused"}


@dataclass(frozen=True)
class DraftRetentionSettings:
    first_reminder_after: timedelta
    second_reminder_after: timedelta
    final_reminder_after: timedelta
    deletion_after: timedelta


@dataclass(frozen=True)
class DraftLifecycleResult:
    state: str
    base_state: str
    deletion_eligible: bool
    deletion_status: str
    effective_activity_at: datetime
    deletion_eligible_at: datetime
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def get_retention_settings(db: Session) -> DraftRetentionSettings:
    row = db.query(models.SaaSDraftLifecycleSetting).filter(
        models.SaaSDraftLifecycleSetting.id == 1
    ).first()
    first_hours = _positive_int(
        getattr(row, "first_reminder_hours", None), DEFAULT_FIRST_REMINDER_HOURS
    )
    second_days = _positive_int(
        getattr(row, "second_reminder_days", None), DEFAULT_SECOND_REMINDER_DAYS
    )
    final_days = _positive_int(
        getattr(row, "final_reminder_days", None), DEFAULT_FINAL_REMINDER_DAYS
    )
    deletion_days = _positive_int(
        getattr(row, "deletion_days", None), DEFAULT_DELETION_DAYS
    )
    return DraftRetentionSettings(
        first_reminder_after=timedelta(hours=first_hours),
        second_reminder_after=timedelta(days=second_days),
        final_reminder_after=timedelta(days=final_days),
        deletion_after=timedelta(days=deletion_days),
    )


def _owned_organizations(db: Session, account):
    return db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account.id
    ).order_by(models.PendingOrganization.id.asc()).all()


def resolve_activity_timestamp(db: Session, account, organization=None) -> tuple[datetime, tuple[str, ...]]:
    organizations = _owned_organizations(db, account)
    warnings = []
    if organization is not None and getattr(organization, "owner_saas_account_id", None) != account.id:
        warnings.append("The supplied pending organization is not owned by this SaaS account.")
    if len(organizations) == 1:
        timestamp = getattr(organizations[0], "last_meaningful_activity_at", None)
        if timestamp:
            return timestamp, tuple(warnings)
    elif len(organizations) > 1:
        warnings.append("Multiple pending organizations prevent an unambiguous activity owner.")
    timestamp = (
        getattr(account, "last_meaningful_activity_at", None)
        or getattr(account, "updated_at", None)
        or getattr(account, "created_at", None)
        or _utcnow()
    )
    return timestamp, tuple(warnings)


def _add_activity_event(db: Session, account, organization, event_type: str, details: dict):
    details_json = json.dumps(details, separators=(",", ":"))
    if organization is not None:
        db.add(models.PendingOrganizationEvent(
            pending_organization_id=organization.id,
            actor_saas_account_id=account.id,
            event_type=event_type,
            details_json=details_json,
        ))
        return
    db.add(models.SaaSAuthEvent(
        saas_account_id=account.id,
        event_type=event_type,
        event_status="ok",
        details_json=details_json,
    ))


def record_meaningful_activity(
    db: Session,
    account,
    *,
    organization=None,
    source: str,
    occurred_at: datetime | None = None,
) -> datetime:
    now = occurred_at or _utcnow()
    owned_organizations = _owned_organizations(db, account)
    authoritative_organization = None
    if organization is not None and getattr(organization, "owner_saas_account_id", None) == account.id:
        authoritative_organization = organization
    elif len(owned_organizations) == 1:
        authoritative_organization = owned_organizations[0]

    had_reminders = any((
        getattr(account, "first_reminder_sent_at", None),
        getattr(account, "second_reminder_sent_at", None),
        getattr(account, "final_reminder_sent_at", None),
    ))
    account.last_meaningful_activity_at = now
    if authoritative_organization is not None:
        authoritative_organization.last_meaningful_activity_at = now

    cycle = int(getattr(account, "reminder_cycle", 1) or 1)
    if had_reminders:
        cycle += 1
        account.reminder_cycle = cycle
        account.first_reminder_sent_at = None
        account.second_reminder_sent_at = None
        account.final_reminder_sent_at = None
        account.recovered_after_reminder_at = now

    event_organization = authoritative_organization
    details = {"source": str(source or "customer_action")[:80], "reminder_cycle": cycle}
    _add_activity_event(db, account, event_organization, "meaningful_activity_recorded", details)
    if had_reminders:
        _add_activity_event(db, account, event_organization, "draft_recovered_after_inactivity", details)
        _add_activity_event(db, account, event_organization, "reminder_cycle_reset", details)
    return now


def _base_state(account, organization, *, has_tenant_link: bool, has_active_job: bool) -> str:
    onboarding_status = str(getattr(account, "onboarding_status", "") or "").strip().lower()
    organization_status = str(getattr(organization, "status", "") or "").strip().lower()
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    lifecycle_statuses = {onboarding_status, organization_status, billing_status}
    if has_tenant_link or lifecycle_statuses.intersection(ACTIVE_STATES):
        return "active"
    if has_active_job or lifecycle_statuses.intersection(PROVISIONING_STATES):
        return "provisioning"
    if lifecycle_statuses.intersection(PAYMENT_PENDING_STATES):
        return "payment_pending"
    if lifecycle_statuses.intersection(CHECKOUT_STARTED_STATES):
        return "checkout_started"
    if lifecycle_statuses.intersection(READY_FOR_CHECKOUT_STATES):
        return "ready_for_checkout"
    if organization is not None:
        return "onboarding_in_progress"
    return "account_created"


def resolve_draft_lifecycle(
    db: Session,
    account=None,
    *,
    organization=None,
    now: datetime | None = None,
) -> DraftLifecycleResult:
    now = now or _utcnow()
    settings = get_retention_settings(db)
    if account is None and organization is not None:
        account = db.query(models.SaaSAccount).filter(
            models.SaaSAccount.id == organization.owner_saas_account_id
        ).first()
    if account is None:
        raise ValueError("A SaaS account or pending organization is required.")
    organizations = _owned_organizations(db, account)
    warnings = []
    blockers = []
    if organization is not None and getattr(organization, "owner_saas_account_id", None) != account.id:
        warnings.append("The supplied pending organization is not owned by this SaaS account.")
        organization = None
    if len(organizations) == 1:
        organization = organizations[0]
    elif len(organizations) > 1:
        warnings.append("Multiple pending organizations require manual review.")
        organization = None

    organization_ids = [row.id for row in organizations]
    tenant_links = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    account_user_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id
    ).all()
    jobs = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    subscriptions = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    contracts = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    attempts = db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.pending_organization_id.in_(organization_ids)
    ).all() if organization_ids else []
    payment_customers = db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account.id
    ).all()

    if len(organizations) > 1:
        blockers.append("multiple_pending_organizations")
    if (
        str(getattr(account, "status", "") or "").strip().lower() in {"locked", "disabled"}
        or getattr(account, "locked_at", None)
        or str(getattr(account, "locked_reason", "") or "").strip()
    ):
        blockers.append("manual_account_protection")
    platform_identity = db.query(operational_models.User).filter(
        operational_models.User.email_normalized == getattr(account, "email_normalized", None)
    ).all()
    if any(auth.is_platform_user(row) for row in platform_identity):
        blockers.append("platform_identity_protected")
    if tenant_links:
        blockers.append("tenant_provisioning_link")
    if account_user_links:
        blockers.append("operational_account_link")
    if any(getattr(row, "school_group_id", None) for row in contracts):
        blockers.append("operational_school_group")
    if any(str(getattr(row, "job_status", "") or "").lower() in PENDING_PROVISIONING_STATES for row in jobs):
        blockers.append("active_or_pending_provisioning")
    if jobs and not any(str(getattr(row, "job_status", "") or "").lower() in PENDING_PROVISIONING_STATES for row in jobs):
        warnings.append("Provisioning history requires manual review.")
        blockers.append("provisioning_history")
    if any(str(getattr(row, "status", "") or "").lower() in ACTIVE_SUBSCRIPTION_STATES for row in subscriptions):
        blockers.append("active_subscription")
    if subscriptions and "active_subscription" not in blockers:
        warnings.append("Subscription history requires manual review.")
        blockers.append("subscription_history")
    if any(
        str(getattr(row, "payment_status", "") or "").lower() == "paid" or getattr(row, "paid_at", None)
        for row in contracts
    ):
        blockers.append("successful_payment")
    if any(str(getattr(row, "status", "") or "").lower() in CONFIRMED_ATTEMPT_STATES for row in attempts):
        blockers.append("confirmed_payment_attempt")
    if any(
        getattr(row, "provider_transaction_id", None)
        and str(getattr(row, "status", "") or "").lower() not in {"failed", "cancelled", "expired"}
        for row in attempts
    ):
        warnings.append("An unresolved provider transaction requires manual review.")
        blockers.append("unresolved_payment_attempt")
    if payment_customers and not organization_ids:
        warnings.append("An account-level payment customer mapping requires manual review.")
        blockers.append("unresolved_payment_customer")
    if any(
        str(getattr(row, "payment_status", "") or "").lower() == "paid"
        or getattr(row, "payment_confirmed_at", None)
        for row in organizations
    ):
        blockers.append("successful_payment")

    has_tenant_link = bool(tenant_links or account_user_links)
    has_active_job = any(
        str(getattr(row, "job_status", "") or "").lower() in PENDING_PROVISIONING_STATES
        for row in jobs
    )
    base_state = _base_state(account, organization, has_tenant_link=has_tenant_link, has_active_job=has_active_job)
    activity_at, activity_warnings = resolve_activity_timestamp(db, account, organization)
    warnings.extend(activity_warnings)
    deletion_at = activity_at + settings.deletion_after
    due = now >= deletion_at
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))

    if base_state in {"active", "provisioning", "payment_pending"}:
        state = base_state
        deletion_status = "ineligible"
    elif blockers or warnings:
        state = "deletion_ineligible"
        deletion_status = "manual_review" if warnings else "ineligible"
    elif due:
        state = "deletion_candidate"
        deletion_status = "candidate"
    else:
        state = base_state
        deletion_status = "not_due"
    return DraftLifecycleResult(
        state=state,
        base_state=base_state,
        deletion_eligible=state == "deletion_candidate",
        deletion_status=deletion_status,
        effective_activity_at=activity_at,
        deletion_eligible_at=deletion_at,
        blocking_reasons=tuple(blockers),
        warnings=tuple(warnings),
    )
