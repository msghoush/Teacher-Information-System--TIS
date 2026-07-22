from dataclasses import dataclass

from workspace_classification import (
    AccountPurpose,
    WorkspaceClassification,
    WorkspaceIntent,
    WorkspaceLifecycleStatus,
)


class WorkspaceClassificationValidationError(ValueError):
    pass


class WorkspaceClassificationTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class WorkspaceClassificationView:
    classification: WorkspaceClassification
    classification_label: str
    lifecycle: WorkspaceLifecycleStatus
    lifecycle_label: str


_CLASSIFICATION_LABELS = {
    WorkspaceClassification.INTERNAL_SANDBOX: "Internal Sandbox",
    WorkspaceClassification.CUSTOMER_DEMO: "Customer Demo",
    WorkspaceClassification.CUSTOMER_PAID: "Customer Paid",
}

_LIFECYCLE_LABELS = {
    WorkspaceLifecycleStatus.PROVISIONING: "Provisioning",
    WorkspaceLifecycleStatus.ACTIVE: "Active",
    WorkspaceLifecycleStatus.SUSPENDED: "Suspended",
    WorkspaceLifecycleStatus.ARCHIVED: "Archived",
}

_LIFECYCLE_TRANSITIONS = {
    WorkspaceLifecycleStatus.PROVISIONING: {
        WorkspaceLifecycleStatus.PROVISIONING,
        WorkspaceLifecycleStatus.ACTIVE,
        WorkspaceLifecycleStatus.SUSPENDED,
        WorkspaceLifecycleStatus.ARCHIVED,
    },
    WorkspaceLifecycleStatus.ACTIVE: {
        WorkspaceLifecycleStatus.ACTIVE,
        WorkspaceLifecycleStatus.SUSPENDED,
        WorkspaceLifecycleStatus.ARCHIVED,
    },
    WorkspaceLifecycleStatus.SUSPENDED: {
        WorkspaceLifecycleStatus.SUSPENDED,
        WorkspaceLifecycleStatus.ACTIVE,
        WorkspaceLifecycleStatus.ARCHIVED,
    },
    WorkspaceLifecycleStatus.ARCHIVED: {WorkspaceLifecycleStatus.ARCHIVED},
}


def _coerce(enum_type, value, field_name: str):
    normalized = str(getattr(value, "value", value) or "").strip().lower()
    try:
        return enum_type(normalized)
    except ValueError as exc:
        raise WorkspaceClassificationValidationError(
            f"Invalid {field_name}: {normalized or 'blank'}."
        ) from exc


def validate_classification(value) -> WorkspaceClassification:
    return _coerce(WorkspaceClassification, value, "workspace classification")


def validate_lifecycle_status(value) -> WorkspaceLifecycleStatus:
    return _coerce(WorkspaceLifecycleStatus, value, "workspace lifecycle status")


def validate_workspace_intent(value) -> WorkspaceIntent:
    return _coerce(WorkspaceIntent, value, "workspace intent")


def validate_account_purpose(value) -> AccountPurpose:
    return _coerce(AccountPurpose, value, "account purpose")


def classification_label(value) -> str:
    return _CLASSIFICATION_LABELS[validate_classification(value)]


def lifecycle_label(value) -> str:
    return _LIFECYCLE_LABELS[validate_lifecycle_status(value)]


def is_internal_sandbox(value) -> bool:
    return validate_classification(value) is WorkspaceClassification.INTERNAL_SANDBOX


def is_customer_workspace(value) -> bool:
    return validate_classification(value) in {
        WorkspaceClassification.CUSTOMER_DEMO,
        WorkspaceClassification.CUSTOMER_PAID,
    }


def validate_classification_transition(current, requested) -> WorkspaceClassification:
    current_value = validate_classification(current)
    requested_value = validate_classification(requested)
    if current_value is not requested_value:
        raise WorkspaceClassificationTransitionError(
            "Workspace classification conversion is not available in M8B-1."
        )
    return current_value


def validate_lifecycle_transition(current, requested) -> WorkspaceLifecycleStatus:
    current_value = validate_lifecycle_status(current)
    requested_value = validate_lifecycle_status(requested)
    if requested_value not in _LIFECYCLE_TRANSITIONS[current_value]:
        raise WorkspaceClassificationTransitionError(
            f"Unsafe workspace lifecycle transition: {current_value.value} to {requested_value.value}."
        )
    return requested_value


def build_read_only_view(classification, lifecycle) -> WorkspaceClassificationView:
    classification_value = validate_classification(classification)
    lifecycle_value = validate_lifecycle_status(lifecycle)
    return WorkspaceClassificationView(
        classification=classification_value,
        classification_label=_CLASSIFICATION_LABELS[classification_value],
        lifecycle=lifecycle_value,
        lifecycle_label=_LIFECYCLE_LABELS[lifecycle_value],
    )
