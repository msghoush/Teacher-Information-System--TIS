from dataclasses import dataclass
from datetime import datetime
import json
import uuid

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from commercial_entitlements import CommercialState
from demo_workflow import (
    DemoRequestActorType,
    DemoRequestEventCategory,
    DemoRequestEventType,
    DemoRequestStatus,
    DemoReviewDecision,
)
from saas import models, service, workspace_classification_service
from workspace_classification import AccountPurpose, WorkspaceIntent


class DemoRequestError(ValueError):
    pass


@dataclass(frozen=True)
class DemoRequestCard:
    request: object
    organization: object
    requester: object
    primary_contact: object | None
    branch_count: int
    review: object | None


STATUS_LABELS = {
    DemoRequestStatus.PENDING_REVIEW.value: "Pending Review",
    DemoRequestStatus.APPROVED.value: "Approved",
    DemoRequestStatus.REJECTED.value: "Rejected",
    DemoRequestStatus.CANCELLED.value: "Cancelled",
}

STATUS_TONES = {
    DemoRequestStatus.PENDING_REVIEW.value: "warning",
    DemoRequestStatus.APPROVED.value: "success",
    DemoRequestStatus.REJECTED.value: "danger",
    DemoRequestStatus.CANCELLED.value: "neutral",
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def status_label(value: str | None) -> str:
    return STATUS_LABELS.get(str(value or "").strip().lower(), "Manual Review Required")


def status_tone(value: str | None) -> str:
    return STATUS_TONES.get(str(value or "").strip().lower(), "danger")


def get_request_by_uuid(db: Session, request_uuid: str):
    cleaned = str(request_uuid or "").strip()
    if not cleaned:
        return None
    return db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.request_uuid == cleaned
    ).first()


def get_latest_for_organization(db: Session, organization):
    if organization is None:
        return None
    return db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.pending_organization_id == organization.id
    ).order_by(
        models.SaaSDemoRequest.submitted_at.desc(),
        models.SaaSDemoRequest.id.desc(),
    ).first()


def get_owned_request(db: Session, account, request_uuid: str):
    if account is None:
        return None
    return db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.request_uuid == str(request_uuid or "").strip(),
        models.SaaSDemoRequest.requester_saas_account_id == account.id,
    ).first()


def _pending_or_approved_request(db: Session, organization):
    return db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.pending_organization_id == organization.id,
        models.SaaSDemoRequest.status.in_((
            DemoRequestStatus.PENDING_REVIEW.value,
            DemoRequestStatus.APPROVED.value,
        )),
    ).order_by(models.SaaSDemoRequest.id.desc()).first()


def _validate_verified_customer(account) -> None:
    if account is None or not getattr(account, "email_verified_at", None):
        raise DemoRequestError("Verify your TIS Account email before continuing.")
    if str(getattr(account, "status", "") or "").strip().lower() != "active":
        raise DemoRequestError("Your TIS Account is not available for this request.")


def _validate_completed_onboarding(db: Session, account, organization) -> None:
    _validate_verified_customer(account)
    if organization is None or int(organization.owner_saas_account_id) != int(account.id):
        raise DemoRequestError("School Workspace Setup was not found.")
    missing = service.get_onboarding_missing_requirements(db, organization)
    progress = service.recalculate_pending_progress(db, organization)
    if missing or not bool(getattr(progress, "review_complete", False)):
        raise DemoRequestError(
            service.format_onboarding_missing_requirements(missing)
            if missing
            else "Review and submit School Workspace Setup before choosing what happens next."
        )
    if str(getattr(organization, "status", "") or "").strip().lower() != service.READY_FOR_CHECKOUT_STATUS:
        raise DemoRequestError("Review and submit School Workspace Setup before choosing what happens next.")
    if service.count_billable_pending_branches(db, organization) <= 0:
        raise DemoRequestError("Add at least one active branch before requesting a demo.")


def _validate_no_commercial_activity(db: Session, organization) -> None:
    if service.initial_checkout_is_closed(db, organization):
        raise DemoRequestError("This workspace already has an active commercial relationship.")
    has_selection = db.query(models.PendingOrganizationPlanSelection.id).filter(
        models.PendingOrganizationPlanSelection.pending_organization_id == organization.id
    ).first()
    has_checkout = db.query(models.CheckoutSession.id).filter(
        models.CheckoutSession.pending_organization_id == organization.id
    ).first()
    has_attempt = db.query(models.PaymentAttempt.id).filter(
        models.PaymentAttempt.pending_organization_id == organization.id
    ).first()
    has_contract = db.query(models.SubscriptionContract.id).filter(
        models.SubscriptionContract.pending_organization_id == organization.id
    ).first()
    has_tenant = db.query(models.TenantProvisioningLink.id).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).first()
    if any((has_selection, has_checkout, has_attempt, has_contract, has_tenant)):
        raise DemoRequestError(
            "A subscription or workspace activation record already exists. Contact TIS Support for review."
        )


def validate_commercial_choice(db: Session, account, organization) -> None:
    _validate_completed_onboarding(db, account, organization)
    if service.initial_checkout_is_closed(db, organization):
        raise DemoRequestError("Initial setup is complete. Manage the active subscription from Subscription Management.")


def _entitlement_snapshot(db: Session, organization) -> dict:
    return {
        "resolution_status": "not_provisioned",
        "reason_code": "workspace_not_created",
        "commercial_state": CommercialState.PROVISIONING.value,
        "workspace_entitlement": None,
        "configured_branch_count": service.count_billable_pending_branches(db, organization),
        "effective_feature_entitlements": {},
    }


def _add_event(
    db: Session,
    demo_request,
    *,
    category: DemoRequestEventCategory,
    event_type: DemoRequestEventType,
    actor_type: DemoRequestActorType,
    actor_saas_account_id: int | None = None,
    actor_user_id: int | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        models.SaaSDemoRequestEvent(
            demo_request_id=demo_request.id,
            event_category=category.value,
            event_type=event_type.value,
            actor_type=actor_type.value,
            actor_saas_account_id=actor_saas_account_id,
            actor_user_id=actor_user_id,
            details_json=json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
        )
    )


def _record_action_and_notification(
    db: Session,
    demo_request,
    *,
    audit_event_type: DemoRequestEventType,
    notification_event_type: DemoRequestEventType,
    actor_type: DemoRequestActorType,
    actor_saas_account_id: int | None = None,
    actor_user_id: int | None = None,
    from_status: str = "",
    to_status: str = "",
) -> None:
    details = {"from_status": from_status, "to_status": to_status}
    _add_event(
        db,
        demo_request,
        category=DemoRequestEventCategory.AUDIT,
        event_type=audit_event_type,
        actor_type=actor_type,
        actor_saas_account_id=actor_saas_account_id,
        actor_user_id=actor_user_id,
        details=details,
    )
    _add_event(
        db,
        demo_request,
        category=DemoRequestEventCategory.NOTIFICATION,
        event_type=notification_event_type,
        actor_type=DemoRequestActorType.SYSTEM,
        details=details,
    )


def submit_demo_request(db: Session, account, organization):
    _validate_completed_onboarding(db, account, organization)
    _validate_no_commercial_activity(db, organization)
    if _pending_or_approved_request(db, organization):
        raise DemoRequestError("A demo request already exists for this school workspace.")

    organization.workspace_intent = workspace_classification_service.validate_workspace_intent(
        WorkspaceIntent.CUSTOMER_DEMO.value
    ).value
    account.account_purpose = workspace_classification_service.validate_account_purpose(
        AccountPurpose.CUSTOMER.value
    ).value
    snapshot = _entitlement_snapshot(db, organization)
    now = _utcnow()
    row = models.SaaSDemoRequest(
        request_uuid=str(uuid.uuid4()),
        requester_saas_account_id=account.id,
        pending_organization_id=organization.id,
        school_group_id=None,
        workspace_uuid_snapshot=None,
        workspace_classification_snapshot=WorkspaceIntent.CUSTOMER_DEMO.value,
        commercial_state_snapshot=CommercialState.PROVISIONING.value,
        entitlement_snapshot_json=json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
        status=DemoRequestStatus.PENDING_REVIEW.value,
        submitted_at=now,
        status_updated_at=now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        raise DemoRequestError("A demo request is already pending for this school workspace.") from exc
    _record_action_and_notification(
        db,
        row,
        audit_event_type=DemoRequestEventType.REQUEST_SUBMITTED,
        notification_event_type=DemoRequestEventType.REQUEST_SUBMITTED,
        actor_type=DemoRequestActorType.CUSTOMER,
        actor_saas_account_id=account.id,
        from_status="",
        to_status=DemoRequestStatus.PENDING_REVIEW.value,
    )
    service.log_pending_event(
        db,
        organization=organization,
        account=account,
        event_type="demo_request_submitted",
        details={"demo_request_uuid": row.request_uuid, "status": row.status},
    )
    return row


def prepare_subscription_choice(db: Session, account, organization) -> None:
    _validate_completed_onboarding(db, account, organization)
    active_request = _pending_or_approved_request(db, organization)
    if active_request:
        raise DemoRequestError(
            "Withdraw the pending demo request before subscribing. Approved demo requests require TIS review."
        )
    organization.workspace_intent = workspace_classification_service.validate_workspace_intent(
        WorkspaceIntent.CUSTOMER_PAID.value
    ).value
    account.account_purpose = workspace_classification_service.validate_account_purpose(
        AccountPurpose.CUSTOMER.value
    ).value
    service.log_pending_event(
        db,
        organization=organization,
        account=account,
        event_type="subscription_path_selected",
        details={"workspace_intent": WorkspaceIntent.CUSTOMER_PAID.value},
    )


def ensure_subscription_path_available(db: Session, organization) -> None:
    if _pending_or_approved_request(db, organization):
        raise DemoRequestError(
            "A demo request is already in progress. View its status before choosing a subscription."
        )


def _require_pending(row) -> None:
    if row is None:
        raise DemoRequestError("Demo request was not found.")
    if str(row.status or "").strip().lower() != DemoRequestStatus.PENDING_REVIEW.value:
        raise DemoRequestError("This demo request can no longer be changed.")


def approve_request(db: Session, row, reviewer) -> object:
    _require_pending(row)
    now = _utcnow()
    previous = row.status
    row.status = DemoRequestStatus.APPROVED.value
    row.approved_at = now
    row.status_updated_at = now
    review = models.SaaSDemoRequestReview(
        review_uuid=str(uuid.uuid4()),
        demo_request_id=row.id,
        reviewer_user_id=getattr(reviewer, "id", None),
        decision=DemoReviewDecision.APPROVED.value,
    )
    db.add(review)
    _record_action_and_notification(
        db,
        row,
        audit_event_type=DemoRequestEventType.REQUEST_APPROVED,
        notification_event_type=DemoRequestEventType.REQUEST_APPROVED,
        actor_type=DemoRequestActorType.PLATFORM_OWNER,
        actor_user_id=getattr(reviewer, "id", None),
        from_status=previous,
        to_status=row.status,
    )
    return review


def reject_request(db: Session, row, reviewer, *, reason: str) -> object:
    _require_pending(row)
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        raise DemoRequestError("A rejection reason is required.")
    now = _utcnow()
    previous = row.status
    row.status = DemoRequestStatus.REJECTED.value
    row.rejection_reason = cleaned_reason[:4000]
    row.rejected_at = now
    row.status_updated_at = now
    review = models.SaaSDemoRequestReview(
        review_uuid=str(uuid.uuid4()),
        demo_request_id=row.id,
        reviewer_user_id=getattr(reviewer, "id", None),
        decision=DemoReviewDecision.REJECTED.value,
        reason=row.rejection_reason,
    )
    db.add(review)
    _record_action_and_notification(
        db,
        row,
        audit_event_type=DemoRequestEventType.REQUEST_REJECTED,
        notification_event_type=DemoRequestEventType.REQUEST_REJECTED,
        actor_type=DemoRequestActorType.PLATFORM_OWNER,
        actor_user_id=getattr(reviewer, "id", None),
        from_status=previous,
        to_status=row.status,
    )
    return review


def cancel_request(db: Session, row, reviewer) -> None:
    _require_pending(row)
    previous = row.status
    row.status = DemoRequestStatus.CANCELLED.value
    row.cancelled_at = _utcnow()
    row.status_updated_at = row.cancelled_at
    _record_action_and_notification(
        db,
        row,
        audit_event_type=DemoRequestEventType.REQUEST_CANCELLED,
        notification_event_type=DemoRequestEventType.REQUEST_CANCELLED,
        actor_type=DemoRequestActorType.PLATFORM_OWNER,
        actor_user_id=getattr(reviewer, "id", None),
        from_status=previous,
        to_status=row.status,
    )


def withdraw_request(db: Session, row, account) -> None:
    _require_pending(row)
    if int(row.requester_saas_account_id) != int(getattr(account, "id", 0) or 0):
        raise DemoRequestError("Demo request was not found.")
    previous = row.status
    row.status = DemoRequestStatus.CANCELLED.value
    row.cancelled_at = _utcnow()
    row.status_updated_at = row.cancelled_at
    _record_action_and_notification(
        db,
        row,
        audit_event_type=DemoRequestEventType.REQUEST_WITHDRAWN,
        notification_event_type=DemoRequestEventType.REQUEST_CANCELLED,
        actor_type=DemoRequestActorType.CUSTOMER,
        actor_saas_account_id=account.id,
        from_status=previous,
        to_status=row.status,
    )


def build_request_card(db: Session, row) -> DemoRequestCard:
    organization = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == row.pending_organization_id
    ).one_or_none()
    requester = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == row.requester_saas_account_id
    ).one_or_none()
    primary_contact = None
    branch_count = 0
    if organization is not None:
        primary_contact = service.get_primary_contact(db, organization)
        branch_count = service.count_billable_pending_branches(db, organization)
    review = db.query(models.SaaSDemoRequestReview).filter(
        models.SaaSDemoRequestReview.demo_request_id == row.id
    ).one_or_none()
    return DemoRequestCard(
        request=row,
        organization=organization,
        requester=requester,
        primary_contact=primary_contact,
        branch_count=branch_count,
        review=review,
    )


def list_review_queue(
    db: Session,
    *,
    search: str = "",
    status: str = "",
    sort: str = "submitted_desc",
) -> list[DemoRequestCard]:
    query = db.query(models.SaaSDemoRequest).join(
        models.PendingOrganization,
        models.PendingOrganization.id == models.SaaSDemoRequest.pending_organization_id,
    ).join(
        models.SaaSAccount,
        models.SaaSAccount.id == models.SaaSDemoRequest.requester_saas_account_id,
    )
    cleaned_status = str(status or "").strip().lower()
    if cleaned_status:
        try:
            cleaned_status = DemoRequestStatus(cleaned_status).value
        except ValueError as exc:
            raise DemoRequestError("Select a valid demo request status.") from exc
        query = query.filter(models.SaaSDemoRequest.status == cleaned_status)
    cleaned_search = str(search or "").strip()[:160]
    if cleaned_search:
        term = f"%{cleaned_search}%"
        query = query.filter(or_(
            models.PendingOrganization.organization_name.ilike(term),
            models.SaaSAccount.email.ilike(term),
            models.SaaSAccount.first_name.ilike(term),
            models.SaaSAccount.last_name.ilike(term),
        ))
    sort_key = str(sort or "").strip().lower()
    orderings = {
        "submitted_asc": (models.SaaSDemoRequest.submitted_at.asc(), models.SaaSDemoRequest.id.asc()),
        "organization_asc": (models.PendingOrganization.organization_name.asc(), models.SaaSDemoRequest.id.asc()),
        "status_asc": (models.SaaSDemoRequest.status.asc(), models.SaaSDemoRequest.submitted_at.desc()),
        "submitted_desc": (models.SaaSDemoRequest.submitted_at.desc(), models.SaaSDemoRequest.id.desc()),
    }
    if sort_key not in orderings:
        sort_key = "submitted_desc"
    return [build_request_card(db, row) for row in query.order_by(*orderings[sort_key]).all()]


def count_requests(db: Session, *, status: str | None = None) -> int:
    query = db.query(models.SaaSDemoRequest.id)
    if status:
        query = query.filter(models.SaaSDemoRequest.status == DemoRequestStatus(status).value)
    return query.count()


def list_events(db: Session, row):
    return db.query(models.SaaSDemoRequestEvent).filter(
        models.SaaSDemoRequestEvent.demo_request_id == row.id
    ).order_by(
        models.SaaSDemoRequestEvent.created_at.asc(),
        models.SaaSDemoRequestEvent.id.asc(),
    ).all()


def apply_customer_setup_context(context: dict, organization, row) -> dict:
    updated = dict(context)
    org_uuid = str(getattr(organization, "organization_uuid", "") or "")
    if row is None:
        updated.update({
            "title": "Choose how to continue",
            "subtitle": f"{updated.get('workspace_name', 'Your school workspace')} is ready for the next step.",
            "status_banner": "Choose a guided demo review or continue directly to Subscription Selection.",
            "primary_action": {
                "label": "Choose Demo or Subscription",
                "url": f"/saas/onboarding/{org_uuid}/commercial-choice",
                "method": "get",
            },
            "help_text": "Your workspace will not be activated until the selected commercial path is completed.",
        })
        return updated
    label = status_label(row.status)
    updated.update({
        "title": f"Demo request: {label}",
        "subtitle": f"TIS has your demo request for {updated.get('workspace_name', 'your school workspace')}.",
        "status_banner": (
            "Your request is waiting for Platform Owner review."
            if row.status == DemoRequestStatus.PENDING_REVIEW.value
            else f"Your demo request status is {label}."
        ),
        "primary_action": {
            "label": "View Demo Request",
            "url": f"/saas/demo-requests/{row.request_uuid}",
            "method": "get",
        },
        "help_text": "Demo approval records the review decision only. Workspace Activation is not part of this stage.",
    })
    return updated
