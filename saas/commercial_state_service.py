from dataclasses import dataclass

from sqlalchemy.orm import Session

import models as operational_models
from commercial_entitlements import CommercialState
from saas import commercial_validation_service, workspace_entitlement_service
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


@dataclass(frozen=True)
class CommercialStateSnapshot:
    workspace_uuid: str
    workspace_classification: str
    workspace_lifecycle_status: str
    resolution_status: str
    reason_code: str
    commercial_state: str
    workspace_entitlement: workspace_entitlement_service.WorkspaceEntitlementResolution | None = None

    @property
    def resolved(self) -> bool:
        return self.resolution_status == "resolved"


_ACTIVE_STATE_BY_CLASSIFICATION = {
    WorkspaceClassification.INTERNAL_SANDBOX.value: CommercialState.INTERNAL_SANDBOX_ACTIVE,
    WorkspaceClassification.CUSTOMER_DEMO.value: CommercialState.CUSTOMER_DEMO_ACTIVE,
    WorkspaceClassification.CUSTOMER_PAID.value: CommercialState.CUSTOMER_PAID_ACTIVE,
}


_STATE_LABELS = {
    CommercialState.PROVISIONING: "Provisioning",
    CommercialState.INTERNAL_SANDBOX_ACTIVE: "Internal Sandbox Active",
    CommercialState.CUSTOMER_DEMO_ACTIVE: "Customer Demo Active",
    CommercialState.CUSTOMER_PAID_ACTIVE: "Customer Paid Active",
    CommercialState.INACTIVE: "Inactive",
    CommercialState.SUSPENDED: "Suspended",
    CommercialState.ARCHIVED: "Archived",
    CommercialState.MANUAL_REVIEW: "Manual Review Required",
}


def _snapshot(group, *, status: str, reason: str, state: CommercialState, entitlement=None):
    return CommercialStateSnapshot(
        workspace_uuid=str(getattr(group, "workspace_uuid", "") or ""),
        workspace_classification=str(getattr(group, "workspace_classification", "") or ""),
        workspace_lifecycle_status=str(getattr(group, "workspace_lifecycle_status", "") or ""),
        resolution_status=status,
        reason_code=reason,
        commercial_state=state.value,
        workspace_entitlement=entitlement,
    )


def resolve_commercial_state(db: Session, school_group_id: int) -> CommercialStateSnapshot:
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        group_id = 0
    group = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == group_id
    ).first()
    if group is None:
        placeholder = type("MissingWorkspace", (), {
            "workspace_uuid": "",
            "workspace_classification": "",
            "workspace_lifecycle_status": "",
        })()
        return _snapshot(
            placeholder,
            status="manual_review",
            reason="missing_school_group",
            state=CommercialState.MANUAL_REVIEW,
        )
    try:
        classification = WorkspaceClassification(group.workspace_classification)
        lifecycle = WorkspaceLifecycleStatus(group.workspace_lifecycle_status)
    except ValueError:
        return _snapshot(
            group,
            status="manual_review",
            reason="invalid_workspace_classification_metadata",
            state=CommercialState.MANUAL_REVIEW,
        )

    entitlement = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
    if not entitlement.resolved:
        return _snapshot(
            group,
            status="manual_review",
            reason=entitlement.reason_code,
            state=CommercialState.MANUAL_REVIEW,
            entitlement=entitlement,
        )
    if lifecycle is WorkspaceLifecycleStatus.PROVISIONING:
        state = CommercialState.PROVISIONING
    elif lifecycle is WorkspaceLifecycleStatus.SUSPENDED:
        state = CommercialState.SUSPENDED
    elif lifecycle is WorkspaceLifecycleStatus.ARCHIVED:
        state = CommercialState.ARCHIVED
    elif entitlement.entitlement_status == "suspended":
        state = CommercialState.SUSPENDED
    elif entitlement.entitlement_status in {"inactive", "ended"}:
        state = CommercialState.INACTIVE
    elif entitlement.entitlement_status != "active":
        return _snapshot(
            group,
            status="manual_review",
            reason="active_workspace_without_active_entitlement",
            state=CommercialState.MANUAL_REVIEW,
            entitlement=entitlement,
        )
    else:
        state = _ACTIVE_STATE_BY_CLASSIFICATION[classification.value]
    commercial_validation_service.validate_commercial_state(state)
    return _snapshot(
        group,
        status="resolved",
        reason="resolved",
        state=state,
        entitlement=entitlement,
    )


def commercial_state_label(resolution: CommercialStateSnapshot) -> str:
    try:
        state = commercial_validation_service.validate_commercial_state(
            resolution.commercial_state
        )
    except commercial_validation_service.CommercialValidationError:
        return _STATE_LABELS[CommercialState.MANUAL_REVIEW]
    return _STATE_LABELS[state]
