from enum import Enum


class CommercialState(str, Enum):
    PROVISIONING = "provisioning"
    INTERNAL_SANDBOX_ACTIVE = "internal_sandbox_active"
    CUSTOMER_DEMO_ACTIVE = "customer_demo_active"
    CUSTOMER_PAID_ACTIVE = "customer_paid_active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"
    MANUAL_REVIEW = "manual_review"


class WorkspaceEntitlementType(str, Enum):
    INTERNAL_SANDBOX = "internal_sandbox"
    DEMO = "demo"
    PAID = "paid"


class WorkspaceEntitlementStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    ENDED = "ended"


class WorkspaceEntitlementSource(str, Enum):
    SYSTEM = "system"
    MIGRATION = "migration"
    SUBSCRIPTION = "subscription"
    PLATFORM = "platform"


class BranchEntitlementMode(str, Enum):
    INHERIT = "inherit"
    ACTIVE = "active"
    INACTIVE = "inactive"


COMMERCIAL_STATE_VALUES = tuple(item.value for item in CommercialState)
WORKSPACE_ENTITLEMENT_TYPE_VALUES = tuple(item.value for item in WorkspaceEntitlementType)
WORKSPACE_ENTITLEMENT_STATUS_VALUES = tuple(item.value for item in WorkspaceEntitlementStatus)
WORKSPACE_ENTITLEMENT_SOURCE_VALUES = tuple(item.value for item in WorkspaceEntitlementSource)
BRANCH_ENTITLEMENT_MODE_VALUES = tuple(item.value for item in BranchEntitlementMode)
