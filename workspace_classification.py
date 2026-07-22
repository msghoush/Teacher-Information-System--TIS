from enum import Enum


class WorkspaceClassification(str, Enum):
    INTERNAL_SANDBOX = "internal_sandbox"
    CUSTOMER_DEMO = "customer_demo"
    CUSTOMER_PAID = "customer_paid"


class WorkspaceLifecycleStatus(str, Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class WorkspaceIntent(str, Enum):
    INTERNAL_SANDBOX = "internal_sandbox"
    CUSTOMER_DEMO = "customer_demo"
    CUSTOMER_PAID = "customer_paid"


class AccountPurpose(str, Enum):
    INTERNAL_TEST = "internal_test"
    CUSTOMER = "customer"


WORKSPACE_CLASSIFICATION_VALUES = tuple(item.value for item in WorkspaceClassification)
WORKSPACE_LIFECYCLE_VALUES = tuple(item.value for item in WorkspaceLifecycleStatus)
WORKSPACE_INTENT_VALUES = tuple(item.value for item in WorkspaceIntent)
ACCOUNT_PURPOSE_VALUES = tuple(item.value for item in AccountPurpose)
