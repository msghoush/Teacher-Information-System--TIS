from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from commercial_entitlements import (
    CommercialState,
    WorkspaceEntitlementSource,
    WorkspaceEntitlementStatus,
    WorkspaceEntitlementType,
)
from demo_workflow import (
    DemoProvisioningEventType,
    DemoProvisioningStatus,
    DemoRequestActorType,
    DemoRequestEventCategory,
    DemoRequestStatus,
    DemoReviewDecision,
)
from saas import (
    commercial_state_service,
    demo_lifecycle_service,
    demo_request_service,
    models,
    provisioning_service,
    service,
    workspace_entitlement_service,
)
from workspace_classification import WorkspaceClassification, WorkspaceIntent, WorkspaceLifecycleStatus


class DemoProvisioningError(ValueError):
    def __init__(self, message: str, *, reason_code: str = "demo_provisioning_blocked"):
        super().__init__(message)
        self.reason_code = reason_code


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def get_provisioning_for_request(db: Session, demo_request):
    if demo_request is None:
        return None
    return db.query(models.SaaSDemoWorkspaceProvisioning).filter(
        models.SaaSDemoWorkspaceProvisioning.demo_request_id == demo_request.id
    ).one_or_none()


def list_provisioning_events(db: Session, provisioning):
    if provisioning is None:
        return []
    return db.query(models.SaaSDemoProvisioningEvent).filter(
        models.SaaSDemoProvisioningEvent.demo_provisioning_id == provisioning.id
    ).order_by(
        models.SaaSDemoProvisioningEvent.created_at.asc(),
        models.SaaSDemoProvisioningEvent.id.asc(),
    ).all()


def provisioning_status_label(provisioning) -> str:
    if provisioning is None:
        return "Not Started"
    labels = {
        DemoProvisioningStatus.PROVISIONING.value: "Provisioning In Progress",
        DemoProvisioningStatus.ACTIVE.value: "Demo Active",
        DemoProvisioningStatus.FAILED.value: "Provisioning Failed",
    }
    return labels.get(str(provisioning.provisioning_status or "").strip().lower(), "Manual Review Required")


def provisioning_status_tone(provisioning) -> str:
    if provisioning is None:
        return "neutral"
    tones = {
        DemoProvisioningStatus.PROVISIONING.value: "warning",
        DemoProvisioningStatus.ACTIVE.value: "success",
        DemoProvisioningStatus.FAILED.value: "danger",
    }
    return tones.get(str(provisioning.provisioning_status or "").strip().lower(), "danger")


def _add_event(
    db: Session,
    provisioning,
    *,
    category: DemoRequestEventCategory,
    event_type: DemoProvisioningEventType,
    actor_type: DemoRequestActorType,
    actor_user_id: int | None = None,
    event_status: str = "ok",
    details: dict | None = None,
) -> None:
    db.add(
        models.SaaSDemoProvisioningEvent(
            demo_provisioning_id=provisioning.id,
            event_category=category.value,
            event_type=event_type.value,
            actor_type=actor_type.value,
            actor_user_id=actor_user_id,
            event_status=str(event_status or "ok").strip()[:20],
            details_json=json.dumps(details or {}, separators=(",", ":"), sort_keys=True),
        )
    )


def _record_event_pair(
    db: Session,
    provisioning,
    *,
    event_type: DemoProvisioningEventType,
    actor_user_id: int | None = None,
    event_status: str = "ok",
    details: dict | None = None,
) -> None:
    _add_event(
        db,
        provisioning,
        category=DemoRequestEventCategory.AUDIT,
        event_type=event_type,
        actor_type=(
            DemoRequestActorType.PLATFORM_OWNER
            if actor_user_id is not None
            else DemoRequestActorType.SYSTEM
        ),
        actor_user_id=actor_user_id,
        event_status=event_status,
        details=details,
    )
    _add_event(
        db,
        provisioning,
        category=DemoRequestEventCategory.NOTIFICATION,
        event_type=event_type,
        actor_type=DemoRequestActorType.SYSTEM,
        event_status=event_status,
        details=details,
    )


def _load_approved_review(db: Session, demo_request):
    reviews = db.query(models.SaaSDemoRequestReview).filter(
        models.SaaSDemoRequestReview.demo_request_id == demo_request.id
    ).all()
    if len(reviews) != 1 or reviews[0].decision != DemoReviewDecision.APPROVED.value:
        raise DemoProvisioningError(
            "Demo provisioning requires one valid Platform Owner approval.",
            reason_code="missing_valid_approval",
        )
    return reviews[0]


def _validate_submission_snapshot(db: Session, demo_request, organization) -> None:
    if demo_request.workspace_classification_snapshot != WorkspaceClassification.CUSTOMER_DEMO.value:
        raise DemoProvisioningError(
            "The approved request is not classified as a customer demo.",
            reason_code="wrong_workspace_classification",
        )
    if str(getattr(organization, "workspace_intent", "") or "") != WorkspaceIntent.CUSTOMER_DEMO.value:
        raise DemoProvisioningError(
            "The organization is not configured for a customer demo.",
            reason_code="wrong_workspace_intent",
        )
    if demo_request.commercial_state_snapshot != CommercialState.PROVISIONING.value:
        raise DemoProvisioningError(
            "The approved request has an inconsistent commercial state.",
            reason_code="inconsistent_commercial_state",
        )
    try:
        snapshot = json.loads(demo_request.entitlement_snapshot_json or "{}")
    except (TypeError, ValueError) as exc:
        raise DemoProvisioningError(
            "The approved request entitlement snapshot is invalid.",
            reason_code="invalid_entitlement_snapshot",
        ) from exc
    if (
        snapshot.get("resolution_status") != "not_provisioned"
        or snapshot.get("commercial_state") != CommercialState.PROVISIONING.value
        or snapshot.get("workspace_entitlement") is not None
        or int(snapshot.get("configured_branch_count") or 0)
        != service.count_billable_pending_branches(db, organization)
    ):
        raise DemoProvisioningError(
            "The approved request entitlement snapshot no longer matches the organization.",
            reason_code="stale_entitlement_snapshot",
        )


def validate_provisioning_request(db: Session, demo_request):
    if demo_request is None:
        raise DemoProvisioningError("Demo request was not found.", reason_code="missing_demo_request")
    if str(demo_request.status or "").strip().lower() != DemoRequestStatus.APPROVED.value:
        raise DemoProvisioningError(
            "Only an approved demo request can be provisioned.",
            reason_code="request_not_approved",
        )
    if demo_request.cancelled_at or demo_request.rejected_at:
        raise DemoProvisioningError(
            "A cancelled or rejected demo request cannot be provisioned.",
            reason_code="request_closed",
        )
    _load_approved_review(db, demo_request)

    organization = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == demo_request.pending_organization_id
    ).one_or_none()
    account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == demo_request.requester_saas_account_id
    ).one_or_none()
    if organization is None or account is None:
        raise DemoProvisioningError(
            "The approved organization or requester is unavailable.",
            reason_code="missing_request_context",
        )
    try:
        demo_request_service.validate_demo_provisioning_context(db, account, organization)
    except demo_request_service.DemoRequestError as exc:
        raise DemoProvisioningError(str(exc), reason_code="organization_validation_failed") from exc
    _validate_submission_snapshot(db, demo_request, organization)

    existing = get_provisioning_for_request(db, demo_request)
    if existing and existing.provisioning_status == DemoProvisioningStatus.ACTIVE.value:
        raise DemoProvisioningError(
            "This demo workspace is already active.",
            reason_code="already_provisioned",
        )
    if existing and existing.provisioning_status == DemoProvisioningStatus.PROVISIONING.value:
        raise DemoProvisioningError(
            "Demo workspace provisioning is already in progress.",
            reason_code="provisioning_in_progress",
        )
    if demo_request.school_group_id or demo_request.workspace_uuid_snapshot:
        raise DemoProvisioningError(
            "This demo request already contains workspace activation data.",
            reason_code="existing_workspace_reference",
        )
    return organization, account, existing


def _create_pending_demo_entitlement(db: Session, school_group):
    entitlement = models.WorkspaceEntitlement(
        entitlement_uuid=str(uuid.uuid4()),
        school_group_id=school_group.id,
        entitlement_type=WorkspaceEntitlementType.DEMO.value,
        status=WorkspaceEntitlementStatus.PENDING.value,
        source=WorkspaceEntitlementSource.PLATFORM.value,
        payment_subscription_id=None,
        effective_from=_utcnow(),
    )
    db.add(entitlement)
    db.flush()
    resolution = workspace_entitlement_service.resolve_workspace_entitlement(db, school_group.id)
    if (
        not resolution.resolved
        or resolution.workspace_entitlement_id != entitlement.id
        or resolution.entitlement_type != WorkspaceEntitlementType.DEMO.value
        or resolution.entitlement_status != WorkspaceEntitlementStatus.PENDING.value
    ):
        raise DemoProvisioningError(
            "The demo workspace entitlement could not be resolved safely.",
            reason_code="pending_entitlement_resolution_failed",
        )
    commercial = commercial_state_service.resolve_commercial_state(db, school_group.id)
    if (
        not commercial.resolved
        or commercial.commercial_state != CommercialState.PROVISIONING.value
    ):
        raise DemoProvisioningError(
            "The demo workspace commercial state is inconsistent before activation.",
            reason_code="provisioning_commercial_state_invalid",
        )
    return entitlement


def _activate_workspace(
    db: Session,
    *,
    demo_request,
    provisioning,
    organization,
    workspace,
    entitlement,
):
    tenant_link = provisioning_service.ensure_tenant_provisioning_link(
        db,
        organization=organization,
        demo_request=demo_request,
        school_group=workspace.school_group,
        owner_user=workspace.owner_user,
        primary_branch=workspace.primary_branch,
        academic_year=workspace.academic_year,
    )
    activated_at = _utcnow()
    reminder_due_at, demo_expires_at = demo_lifecycle_service.calculate_lifecycle_dates(
        activated_at
    )
    workspace.school_group.workspace_lifecycle_status = WorkspaceLifecycleStatus.ACTIVE.value
    entitlement.status = WorkspaceEntitlementStatus.ACTIVE.value
    entitlement.effective_from = activated_at
    entitlement.effective_to = demo_lifecycle_service.storage_datetime(demo_expires_at)
    tenant_link.tenant_status = provisioning_service.TENANT_ACTIVE
    tenant_link.activated_at = activated_at
    db.flush()

    commercial = commercial_state_service.resolve_commercial_state(
        db, workspace.school_group.id
    )
    if (
        not commercial.resolved
        or commercial.commercial_state != CommercialState.CUSTOMER_DEMO_ACTIVE.value
        or commercial.workspace_entitlement is None
        or not commercial.workspace_entitlement.active
    ):
        raise DemoProvisioningError(
            "The activated demo workspace did not resolve to an active demo entitlement.",
            reason_code="active_commercial_state_invalid",
        )

    demo_request.school_group_id = workspace.school_group.id
    demo_request.workspace_uuid_snapshot = workspace.school_group.workspace_uuid
    demo_request.commercial_state_snapshot = CommercialState.CUSTOMER_DEMO_ACTIVE.value
    demo_request.entitlement_snapshot_json = json.dumps(
        {
            "resolution_status": commercial.resolution_status,
            "reason_code": commercial.reason_code,
            "commercial_state": commercial.commercial_state,
            "workspace_entitlement": {
                "entitlement_type": commercial.workspace_entitlement.entitlement_type,
                "status": commercial.workspace_entitlement.entitlement_status,
                "source": commercial.workspace_entitlement.source,
            },
            "configured_branch_count": len(workspace.branches),
            "effective_feature_entitlements": {
                key: value.value
                for key, value in commercial.workspace_entitlement.entitlements.items()
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    provisioning.school_group_id = workspace.school_group.id
    provisioning.workspace_entitlement_id = entitlement.id
    provisioning.tenant_provisioning_link_id = tenant_link.id
    provisioning.provisioning_status = DemoProvisioningStatus.ACTIVE.value
    provisioning.result_code = "demo_workspace_active"
    provisioning.failure_reason = None
    provisioning.completed_at = activated_at
    provisioning.activated_at = activated_at
    provisioning.failed_at = None
    provisioning.demo_expires_at = demo_lifecycle_service.storage_datetime(demo_expires_at)
    provisioning.reminder_due_at = demo_lifecycle_service.storage_datetime(reminder_due_at)
    provisioning.reminder_sent_at = None
    provisioning.expired_at = None
    provisioning.lifecycle_processing_status = "pending"
    provisioning.lifecycle_last_processed_at = None
    provisioning.lifecycle_failure_code = None
    return tenant_link, commercial


def provision_demo_workspace(db: Session, demo_request, actor):
    locked_request = db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.id == demo_request.id
    ).with_for_update().one()
    organization, _account, provisioning = validate_provisioning_request(db, locked_request)
    now = _utcnow()
    if provisioning is None:
        provisioning = models.SaaSDemoWorkspaceProvisioning(
            provisioning_uuid=str(uuid.uuid4()),
            demo_request_id=locked_request.id,
            triggered_by_user_id=getattr(actor, "id", None),
            provisioning_status=DemoProvisioningStatus.PROVISIONING.value,
            attempt_count=1,
            started_at=now,
        )
        db.add(provisioning)
        db.flush()
    else:
        provisioning.triggered_by_user_id = getattr(actor, "id", None)
        provisioning.provisioning_status = DemoProvisioningStatus.PROVISIONING.value
        provisioning.attempt_count = int(provisioning.attempt_count or 0) + 1
        provisioning.result_code = None
        provisioning.failure_reason = None
        provisioning.started_at = now
        provisioning.completed_at = None
        provisioning.activated_at = None
        provisioning.failed_at = None
        provisioning.demo_expires_at = None
        provisioning.reminder_due_at = None
        provisioning.reminder_sent_at = None
        provisioning.expired_at = None
        provisioning.lifecycle_processing_status = "pending"
        provisioning.lifecycle_last_processed_at = None
        provisioning.lifecycle_failure_code = None

    _record_event_pair(
        db,
        provisioning,
        event_type=DemoProvisioningEventType.PROVISIONING_STARTED,
        actor_user_id=getattr(actor, "id", None),
        details={"attempt": provisioning.attempt_count},
    )
    db.flush()

    try:
        with db.begin_nested():
            workspace = provisioning_service.create_workspace_records(db, organization)
            if (
                workspace.school_group.workspace_classification
                != WorkspaceClassification.CUSTOMER_DEMO.value
            ):
                raise DemoProvisioningError(
                    "The provisioning engine created the wrong workspace classification.",
                    reason_code="created_workspace_classification_mismatch",
                )
            entitlement = _create_pending_demo_entitlement(db, workspace.school_group)
            _tenant_link, commercial = _activate_workspace(
                db,
                demo_request=locked_request,
                provisioning=provisioning,
                organization=organization,
                workspace=workspace,
                entitlement=entitlement,
            )
            service.log_pending_event(
                db,
                organization=organization,
                event_type="demo_provisioning_completed",
                details={"demo_request_uuid": locked_request.request_uuid},
            )
            service.log_pending_event(
                db,
                organization=organization,
                event_type="demo_activation_completed",
                details={"demo_request_uuid": locked_request.request_uuid},
            )
        _record_event_pair(
            db,
            provisioning,
            event_type=DemoProvisioningEventType.PROVISIONING_COMPLETED,
            actor_user_id=getattr(actor, "id", None),
            details={"result_code": provisioning.result_code},
        )
        _record_event_pair(
            db,
            provisioning,
            event_type=DemoProvisioningEventType.ACTIVATION_COMPLETED,
            details={"commercial_state": commercial.commercial_state},
        )
        return provisioning
    except Exception as exc:
        reason_code = (
            exc.reason_code
            if isinstance(exc, DemoProvisioningError)
            else "workspace_provisioning_failed"
        )
        provisioning.provisioning_status = DemoProvisioningStatus.FAILED.value
        provisioning.result_code = reason_code
        provisioning.failure_reason = str(exc)[:4000]
        provisioning.failed_at = _utcnow()
        provisioning.completed_at = None
        provisioning.activated_at = None
        provisioning.school_group_id = None
        provisioning.workspace_entitlement_id = None
        provisioning.tenant_provisioning_link_id = None
        _record_event_pair(
            db,
            provisioning,
            event_type=DemoProvisioningEventType.PROVISIONING_FAILED,
            actor_user_id=getattr(actor, "id", None),
            event_status="failed",
            details={"reason_code": reason_code},
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="demo_provisioning_failed",
            details={
                "demo_request_uuid": locked_request.request_uuid,
                "reason_code": reason_code,
            },
        )
        return provisioning
