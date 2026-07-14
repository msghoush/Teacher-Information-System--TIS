import json
import math
import os
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

import branding_storage
import email_service
import email_templates
import public_url
from saas import draft_lifecycle_service, models


REMINDER_STAGES = ("first", "second", "final")
REMINDER_EVENT_TYPES = {
    "first": "first_reminder_sent",
    "second": "second_reminder_sent",
    "final": "final_reminder_sent",
}
REMINDER_TIMESTAMP_FIELDS = {
    "first": "first_reminder_sent_at",
    "second": "second_reminder_sent_at",
    "final": "final_reminder_sent_at",
}
STEP_LABELS = (
    ("organization_profile_complete", "Organization Profile"),
    ("branches_complete", "Branch Setup"),
    ("academic_setup_complete", "Academic Setup"),
    ("contacts_complete", "Primary Contact"),
    ("review_complete", "Review and Confirmation"),
)
_PROCESS_LOCK = threading.Lock()


@dataclass(frozen=True)
class OnboardingProgressSummary:
    completed_steps: tuple[str, ...]
    total_required_steps: int
    completed_count: int
    completion_percent: int
    progress_text: str
    next_incomplete_step: str
    ready_for_checkout: bool


@dataclass(frozen=True)
class ReminderEligibility:
    eligible: bool
    due_stage: str | None
    reason: str
    activity_at: datetime
    inactivity: timedelta
    deletion_at: datetime


@dataclass
class ReminderBatchResult:
    scanned: int = 0
    first_reminder_sent: int = 0
    second_reminder_sent: int = 0
    final_reminder_sent: int = 0
    skipped: int = 0
    failed: int = 0
    dry_run_due: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def resolve_onboarding_progress(db: Session, organization=None) -> OnboardingProgressSummary:
    if organization is None:
        return OnboardingProgressSummary(
            completed_steps=(),
            total_required_steps=len(STEP_LABELS),
            completed_count=0,
            completion_percent=0,
            progress_text=f"0 of {len(STEP_LABELS)} steps completed",
            next_incomplete_step=STEP_LABELS[0][1],
            ready_for_checkout=False,
        )
    progress = db.query(models.PendingOrganizationProgress).filter(
        models.PendingOrganizationProgress.pending_organization_id == organization.id
    ).first()
    completed_steps = tuple(
        label for field_name, label in STEP_LABELS
        if bool(getattr(progress, field_name, False))
    )
    completed_count = len(completed_steps)
    next_step = next(
        (
            label for field_name, label in STEP_LABELS
            if not bool(getattr(progress, field_name, False))
        ),
        "Subscription Selection",
    )
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    if completed_count == len(STEP_LABELS) and billing_status in {
        "plan_selected", "checkout_ready", "checkout_initiated", "checkout_started"
    }:
        next_step = "Secure Payment"
    ready_for_checkout = bool(
        completed_count == len(STEP_LABELS)
        and str(getattr(organization, "status", "") or "").strip().lower()
        in {"ready_for_checkout", "under_review", "approved"}
    )
    total = len(STEP_LABELS)
    return OnboardingProgressSummary(
        completed_steps=completed_steps,
        total_required_steps=total,
        completed_count=completed_count,
        completion_percent=int(round((completed_count / total) * 100)),
        progress_text=f"{completed_count} of {total} steps completed",
        next_incomplete_step=next_step,
        ready_for_checkout=ready_for_checkout,
    )


def _single_organization(db: Session, account):
    organizations = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account.id
    ).order_by(models.PendingOrganization.id.asc()).all()
    return organizations[0] if len(organizations) == 1 else None


def resolve_reminder_eligibility(
    db: Session,
    account,
    *,
    now: datetime | None = None,
    stage_filter: str | None = None,
) -> ReminderEligibility:
    now = now or _utcnow()
    stage_filter = str(stage_filter or "").strip().lower() or None
    if stage_filter and stage_filter not in REMINDER_STAGES:
        raise ValueError("Reminder stage must be first, second, or final.")
    organization = _single_organization(db, account)
    lifecycle = draft_lifecycle_service.resolve_draft_lifecycle(
        db, account, organization=organization, now=now
    )
    activity_at = lifecycle.effective_activity_at
    inactivity = max(now - activity_at, timedelta(0))
    status = str(getattr(account, "status", "") or "").strip().lower()
    if status in {"deleted", "disabled", "locked"}:
        return ReminderEligibility(False, None, "account_status_ineligible", activity_at, inactivity, lifecycle.deletion_eligible_at)
    if lifecycle.blocking_reasons or lifecycle.warnings:
        return ReminderEligibility(False, None, "lifecycle_ineligible", activity_at, inactivity, lifecycle.deletion_eligible_at)
    if lifecycle.base_state in {"active", "provisioning", "payment_pending"}:
        return ReminderEligibility(False, None, "lifecycle_ineligible", activity_at, inactivity, lifecycle.deletion_eligible_at)

    settings = draft_lifecycle_service.get_retention_settings(db)
    first_sent = getattr(account, "first_reminder_sent_at", None)
    second_sent = getattr(account, "second_reminder_sent_at", None)
    final_sent = getattr(account, "final_reminder_sent_at", None)
    due_stage = None
    if first_sent is None and inactivity >= settings.first_reminder_after:
        due_stage = "first"
    elif first_sent is not None and second_sent is None and inactivity >= settings.second_reminder_after:
        due_stage = "second"
    elif (
        first_sent is not None
        and second_sent is not None
        and final_sent is None
        and inactivity >= settings.final_reminder_after
    ):
        due_stage = "final"
    if due_stage is None:
        reason = "final_already_sent" if final_sent is not None else "not_due"
        return ReminderEligibility(True, None, reason, activity_at, inactivity, lifecycle.deletion_eligible_at)
    if stage_filter and due_stage != stage_filter:
        return ReminderEligibility(True, None, "stage_filter_mismatch", activity_at, inactivity, lifecycle.deletion_eligible_at)
    return ReminderEligibility(True, due_stage, "due", activity_at, inactivity, lifecycle.deletion_eligible_at)


def _support_contact() -> str:
    return str(os.getenv("TIS_SUPPORT_EMAIL") or os.getenv("EMAIL_REPLY_TO") or "").strip()


def _selected_plan(db: Session, organization):
    plan_id = getattr(organization, "selected_plan_id", None) if organization is not None else None
    if not plan_id:
        return None
    return db.query(models.SubscriptionPlan).filter(models.SubscriptionPlan.id == plan_id).first()


def build_reminder_email(db: Session, account, eligibility: ReminderEligibility):
    stage = str(eligibility.due_stage or "").strip().lower()
    if stage not in REMINDER_STAGES:
        raise ValueError("A due reminder stage is required to build an email.")
    organization = _single_organization(db, account)
    progress = resolve_onboarding_progress(db, organization)
    organization_name = str(getattr(organization, "organization_name", "") or "").strip()
    recipient_name = str(getattr(account, "first_name", "") or "").strip()
    continue_url = f"{public_url.public_base_url()}/saas/login"
    logo_url = public_url.public_static_asset_url(
        branding_storage.tis_logo_relative_path(theme="light", compact=True)
    )
    support_contact = _support_contact()
    plan = _selected_plan(db, organization)
    common = {
        "recipient_name": recipient_name,
        "organization_name": organization_name,
        "progress_text": progress.progress_text,
        "completion_percent": progress.completion_percent,
        "next_step": progress.next_incomplete_step,
        "continue_url": continue_url,
        "logo_url": logo_url,
        "support_contact": support_contact,
    }
    if stage == "first":
        return email_templates.build_first_draft_reminder_email(**common)
    if stage == "second":
        return email_templates.build_second_draft_reminder_email(
            **common,
            include_ai=bool(getattr(plan, "ai_enabled", False)),
        )
    seconds_remaining = max(
        0,
        (eligibility.deletion_at - (eligibility.activity_at + eligibility.inactivity)).total_seconds(),
    )
    days_remaining = int(math.ceil(seconds_remaining / 86400))
    return email_templates.build_final_draft_reminder_email(
        **common,
        deletion_date=eligibility.deletion_at.strftime("%B %d, %Y"),
        days_remaining=days_remaining,
        retention_days=draft_lifecycle_service.get_retention_settings(db).deletion_after.days,
    )


def _event_details(account, organization, eligibility, stage: str, **extra) -> dict:
    details = {
        "reminder_cycle": int(getattr(account, "reminder_cycle", 1) or 1),
        "reminder_stage": stage,
        "inactivity_hours": int(eligibility.inactivity.total_seconds() // 3600),
        "account_uuid": str(getattr(account, "account_uuid", "") or ""),
        "organization_uuid": str(getattr(organization, "organization_uuid", "") or ""),
        "timestamp": _utcnow().isoformat(timespec="seconds") + "Z",
    }
    details.update(extra)
    return details


def _record_event(db: Session, account, organization, event_type: str, details: dict):
    payload = json.dumps(details, separators=(",", ":"))
    if organization is not None:
        db.add(models.PendingOrganizationEvent(
            pending_organization_id=organization.id,
            actor_saas_account_id=None,
            event_type=event_type,
            details_json=payload,
        ))
    else:
        db.add(models.SaaSAuthEvent(
            saas_account_id=account.id,
            event_type=event_type,
            event_status=(
                "failed" if event_type == "reminder_send_failed"
                else "skipped" if event_type == "reminder_skipped_ineligible"
                else "ok"
            ),
            details_json=payload,
        ))


def _skip_event_already_recorded(db: Session, account, organization, cycle: int) -> bool:
    model = models.PendingOrganizationEvent if organization is not None else models.SaaSAuthEvent
    query = db.query(model).filter(model.event_type == "reminder_skipped_ineligible")
    if organization is not None:
        query = query.filter(model.pending_organization_id == organization.id)
    else:
        query = query.filter(model.saas_account_id == account.id)
    marker = f'"reminder_cycle":{cycle}'
    return any(marker in str(row.details_json or "") for row in query.all())


def _process_locked_account(
    db: Session,
    account,
    *,
    now: datetime,
    dry_run: bool,
    stage_filter: str | None,
) -> str:
    organization = _single_organization(db, account)
    eligibility = resolve_reminder_eligibility(
        db, account, now=now, stage_filter=stage_filter
    )
    if not eligibility.eligible:
        if not dry_run and eligibility.inactivity >= draft_lifecycle_service.get_retention_settings(db).first_reminder_after:
            cycle = int(getattr(account, "reminder_cycle", 1) or 1)
            if not _skip_event_already_recorded(db, account, organization, cycle):
                _record_event(
                    db,
                    account,
                    organization,
                    "reminder_skipped_ineligible",
                    _event_details(account, organization, eligibility, "none", reason=eligibility.reason),
                )
        return "skipped"
    if eligibility.due_stage is None:
        return "skipped"
    if dry_run:
        return "dry_run_due"
    stage = eligibility.due_stage
    try:
        message = build_reminder_email(db, account, eligibility)
        email_service.send_email(
            to=str(getattr(account, "email", "") or "").strip(),
            subject=message.subject,
            text=message.text,
            html=message.html,
        )
    except Exception as exc:
        _record_event(
            db,
            account,
            organization,
            "reminder_send_failed",
            _event_details(
                account,
                organization,
                eligibility,
                stage,
                error_type=exc.__class__.__name__,
            ),
        )
        return "failed"
    sent_at = now
    setattr(account, REMINDER_TIMESTAMP_FIELDS[stage], sent_at)
    _record_event(
        db,
        account,
        organization,
        REMINDER_EVENT_TYPES[stage],
        _event_details(account, organization, eligibility, stage, delivered=True),
    )
    return f"{stage}_reminder_sent"


def process_due_draft_reminders(
    session_factory,
    *,
    dry_run: bool = False,
    batch_size: int = 100,
    stage_filter: str | None = None,
    now: datetime | None = None,
) -> ReminderBatchResult:
    try:
        batch_size = int(batch_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("Batch size must be a positive integer.") from exc
    if batch_size <= 0 or batch_size > 1000:
        raise ValueError("Batch size must be between 1 and 1000.")
    stage_filter = str(stage_filter or "").strip().lower() or None
    if stage_filter and stage_filter not in REMINDER_STAGES:
        raise ValueError("Reminder stage must be first, second, or final.")
    now = now or _utcnow()
    result = ReminderBatchResult()

    with _PROCESS_LOCK:
        scan_db = session_factory()
        try:
            settings = draft_lifecycle_service.get_retention_settings(scan_db)
            cutoff = now - settings.first_reminder_after
            account_ids = [
                row[0]
                for row in scan_db.query(models.SaaSAccount.id)
                .outerjoin(
                    models.PendingOrganization,
                    models.PendingOrganization.owner_saas_account_id == models.SaaSAccount.id,
                )
                .filter(or_(
                    models.SaaSAccount.last_meaningful_activity_at <= cutoff,
                    models.PendingOrganization.last_meaningful_activity_at <= cutoff,
                ))
                .distinct()
                .order_by(models.SaaSAccount.id.asc())
                .limit(batch_size)
                .all()
            ]
        finally:
            scan_db.close()

        for account_id in account_ids:
            result.scanned += 1
            db = session_factory()
            outcome = "failed"
            try:
                with db.begin():
                    account = db.query(models.SaaSAccount).filter(
                        models.SaaSAccount.id == account_id
                    ).with_for_update(skip_locked=True).first()
                    if account is None:
                        outcome = "skipped"
                    else:
                        outcome = _process_locked_account(
                            db,
                            account,
                            now=now,
                            dry_run=dry_run,
                            stage_filter=stage_filter,
                        )
            except Exception:
                db.rollback()
                outcome = "failed"
            finally:
                db.close()
            if hasattr(result, outcome):
                setattr(result, outcome, getattr(result, outcome) + 1)
            elif outcome == "dry_run_due":
                result.dry_run_due += 1
            else:
                result.failed += 1
    return result
