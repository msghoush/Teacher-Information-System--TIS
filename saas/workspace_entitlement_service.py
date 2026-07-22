from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

import models as operational_models
from commercial_entitlements import WorkspaceEntitlementStatus, WorkspaceEntitlementType
from saas import commercial_validation_service, entitlement_service, models
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


RESOLVED = "resolved"
MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class EffectiveEntitlementValue:
    key: str
    display_name: str
    category: str
    scope: str
    value_type: str
    value: Any
    status: str
    source: str

    @property
    def granted(self) -> bool:
        if self.status != "active":
            return False
        if self.value_type == "boolean":
            return self.value is True
        if self.value_type in {"integer", "decimal"}:
            return self.value is not None and self.value > 0
        return bool(self.value)


@dataclass(frozen=True)
class WorkspaceEntitlementResolution:
    resolution_status: str
    reason_code: str
    school_group_id: int | None
    workspace_entitlement_id: int | None = None
    entitlement_uuid: str = ""
    entitlement_type: str = ""
    entitlement_status: str = ""
    source: str = ""
    payment_subscription_id: int | None = None
    effective_from: object | None = None
    effective_to: object | None = None
    entitlements: dict[str, EffectiveEntitlementValue] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return self.resolution_status == RESOLVED

    @property
    def active(self) -> bool:
        return self.resolved and self.entitlement_status == WorkspaceEntitlementStatus.ACTIVE.value


_TYPE_BY_CLASSIFICATION = {
    WorkspaceClassification.INTERNAL_SANDBOX.value: WorkspaceEntitlementType.INTERNAL_SANDBOX.value,
    WorkspaceClassification.CUSTOMER_DEMO.value: WorkspaceEntitlementType.DEMO.value,
    WorkspaceClassification.CUSTOMER_PAID.value: WorkspaceEntitlementType.PAID.value,
}

_STATUS_BY_LIFECYCLE = {
    WorkspaceLifecycleStatus.PROVISIONING.value: WorkspaceEntitlementStatus.PENDING.value,
    WorkspaceLifecycleStatus.ACTIVE.value: WorkspaceEntitlementStatus.ACTIVE.value,
    WorkspaceLifecycleStatus.SUSPENDED.value: WorkspaceEntitlementStatus.SUSPENDED.value,
    WorkspaceLifecycleStatus.ARCHIVED.value: WorkspaceEntitlementStatus.ENDED.value,
}


def _manual_review(school_group_id, reason_code: str) -> WorkspaceEntitlementResolution:
    return WorkspaceEntitlementResolution(
        resolution_status=MANUAL_REVIEW,
        reason_code=reason_code,
        school_group_id=school_group_id,
    )


def _implicit_internal_resolution(group) -> WorkspaceEntitlementResolution:
    return WorkspaceEntitlementResolution(
        resolution_status=RESOLVED,
        reason_code="implicit_internal_sandbox_compatibility",
        school_group_id=group.id,
        entitlement_type=WorkspaceEntitlementType.INTERNAL_SANDBOX.value,
        entitlement_status=_STATUS_BY_LIFECYCLE[group.workspace_lifecycle_status],
        source="system",
    )


def _load_explicit_values(db: Session, row) -> tuple[dict[str, EffectiveEntitlementValue], str]:
    values = db.query(models.WorkspaceEntitlementValue).filter(
        models.WorkspaceEntitlementValue.workspace_entitlement_id == row.id
    ).order_by(models.WorkspaceEntitlementValue.id.asc()).all()
    resolved = {}
    for value_row in values:
        definition = db.query(models.EntitlementDefinition).filter(
            models.EntitlementDefinition.id == value_row.entitlement_definition_id
        ).first()
        if definition is None:
            return {}, "orphan_entitlement_definition"
        if not bool(definition.active):
            return {}, "inactive_entitlement_definition"
        if definition.key in resolved:
            return {}, "duplicate_entitlement_key"
        if str(value_row.status or "").strip().lower() not in {"active", "inactive"}:
            return {}, "invalid_entitlement_value_status"
        try:
            typed_value = commercial_validation_service.parse_entitlement_value(
                value_row.value,
                definition.value_type,
            )
        except commercial_validation_service.CommercialValidationError:
            return {}, "invalid_entitlement_value"
        resolved[definition.key] = EffectiveEntitlementValue(
            key=definition.key,
            display_name=definition.display_name,
            category=definition.category,
            scope=definition.scope,
            value_type=definition.value_type,
            value=typed_value,
            status=str(value_row.status).lower(),
            source="workspace",
        )
    return resolved, ""


def _load_paid_plan_values(db: Session, group_id: int, row):
    paid_resolution = entitlement_service.resolve_entitlements(db, group_id)
    if not paid_resolution.resolved:
        return {}, f"paid_subscription_{paid_resolution.reason_code}"
    if row.payment_subscription_id != paid_resolution.subscription_id:
        return {}, "paid_subscription_mismatch"
    resolved = {
        key: EffectiveEntitlementValue(
            key=value.key,
            display_name=value.display_name,
            category=value.category,
            scope=value.scope,
            value_type=value.value_type,
            value=value.value,
            status="active" if value.status in {"active", "derived"} else "inactive",
            source="subscription_plan",
        )
        for key, value in paid_resolution.entitlements.items()
    }
    return resolved, ""


def resolve_workspace_entitlement(db: Session, school_group_id: int) -> WorkspaceEntitlementResolution:
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        return _manual_review(None, "invalid_school_group")
    if group_id <= 0:
        return _manual_review(None, "invalid_school_group")

    group = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == group_id
    ).first()
    if group is None:
        return _manual_review(group_id, "missing_school_group")
    try:
        expected_type = _TYPE_BY_CLASSIFICATION[group.workspace_classification]
        _STATUS_BY_LIFECYCLE[group.workspace_lifecycle_status]
    except KeyError:
        return _manual_review(group_id, "invalid_workspace_classification_metadata")

    rows = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.school_group_id == group_id
    ).order_by(models.WorkspaceEntitlement.id.asc()).all()
    active_rows = [row for row in rows if str(row.status or "").lower() == "active"]
    if len(active_rows) > 1:
        return _manual_review(group_id, "ambiguous_active_workspace_entitlement")
    if len(active_rows) == 1:
        row = active_rows[0]
    elif len(rows) == 1:
        row = rows[0]
    elif not rows and expected_type == WorkspaceEntitlementType.INTERNAL_SANDBOX.value:
        return _implicit_internal_resolution(group)
    elif not rows:
        return _manual_review(group_id, "missing_workspace_entitlement")
    else:
        return _manual_review(group_id, "ambiguous_workspace_entitlement_history")

    try:
        entitlement_type = commercial_validation_service.validate_entitlement_type(
            row.entitlement_type
        ).value
        entitlement_status = commercial_validation_service.validate_entitlement_status(
            row.status
        ).value
        source = commercial_validation_service.validate_entitlement_source(row.source).value
    except commercial_validation_service.CommercialValidationError:
        return _manual_review(group_id, "invalid_workspace_entitlement_metadata")
    if entitlement_type != expected_type:
        return _manual_review(group_id, "classification_entitlement_mismatch")
    if row.effective_from and row.effective_to and row.effective_to <= row.effective_from:
        return _manual_review(group_id, "invalid_entitlement_effective_window")
    if entitlement_type != WorkspaceEntitlementType.PAID.value and row.payment_subscription_id:
        return _manual_review(group_id, "unexpected_subscription_link")

    explicit_values, reason = _load_explicit_values(db, row)
    if reason:
        return _manual_review(group_id, reason)
    effective_values = {}
    if entitlement_type == WorkspaceEntitlementType.PAID.value:
        if not row.payment_subscription_id:
            return _manual_review(group_id, "missing_paid_subscription_link")
        plan_values, reason = _load_paid_plan_values(db, group_id, row)
        if reason:
            return _manual_review(group_id, reason)
        duplicate_keys = set(plan_values).intersection(explicit_values)
        if duplicate_keys:
            return _manual_review(group_id, "unsupported_paid_entitlement_override")
        effective_values.update(plan_values)
    effective_values.update(explicit_values)

    return WorkspaceEntitlementResolution(
        resolution_status=RESOLVED,
        reason_code="resolved",
        school_group_id=group_id,
        workspace_entitlement_id=row.id,
        entitlement_uuid=row.entitlement_uuid,
        entitlement_type=entitlement_type,
        entitlement_status=entitlement_status,
        source=source,
        payment_subscription_id=row.payment_subscription_id,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        entitlements=effective_values,
    )


def workspace_entitlement_label(resolution: WorkspaceEntitlementResolution) -> str:
    if not resolution.resolved:
        return "Manual Review Required"
    type_labels = {
        "internal_sandbox": "Internal Sandbox Entitlement",
        "demo": "Demo Entitlement",
        "paid": "Paid Subscription Entitlement",
    }
    status_labels = {
        "pending": "Pending",
        "active": "Active",
        "inactive": "Inactive",
        "suspended": "Suspended",
        "ended": "Ended",
    }
    return f"{type_labels[resolution.entitlement_type]} / {status_labels[resolution.entitlement_status]}"
