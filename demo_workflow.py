from enum import Enum


class DemoRequestStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DemoReviewDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class DemoRequestEventCategory(str, Enum):
    AUDIT = "audit"
    NOTIFICATION = "notification"


class DemoRequestEventType(str, Enum):
    REQUEST_SUBMITTED = "request_submitted"
    REQUEST_APPROVED = "request_approved"
    REQUEST_REJECTED = "request_rejected"
    REQUEST_CANCELLED = "request_cancelled"
    REQUEST_WITHDRAWN = "request_withdrawn"


class DemoRequestActorType(str, Enum):
    CUSTOMER = "customer"
    PLATFORM_OWNER = "platform_owner"
    SYSTEM = "system"


class DemoProvisioningStatus(str, Enum):
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    FAILED = "failed"


class DemoProvisioningEventType(str, Enum):
    PROVISIONING_STARTED = "provisioning_started"
    PROVISIONING_COMPLETED = "provisioning_completed"
    PROVISIONING_FAILED = "provisioning_failed"
    ACTIVATION_COMPLETED = "activation_completed"


class DemoLifecycleState(str, Enum):
    ACTIVE = "active"
    REMINDER_DUE = "reminder_due"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    MANUAL_REVIEW = "manual_review"


class DemoLifecycleProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    EXPIRED = "expired"


class DemoLifecycleEventType(str, Enum):
    REMINDER_BECAME_DUE = "reminder_became_due"
    REMINDER_NOTIFICATION_CREATED = "reminder_notification_created"
    EXPIRATION_PROCESSING_STARTED = "expiration_processing_started"
    DEMO_EXPIRED = "demo_expired"
    WORKSPACE_SUSPENDED = "workspace_suspended"
    ACCESS_BLOCKED = "access_blocked"
    LIFECYCLE_PROCESSING_FAILED = "lifecycle_processing_failed"


class DemoLifecycleNotificationType(str, Enum):
    EXPIRATION_REMINDER = "expiration_reminder"


class DemoLifecycleNotificationRecipient(str, Enum):
    SAAS_ACCOUNT = "saas_account"
    PLATFORM_OWNER = "platform_owner"


DEMO_REQUEST_STATUS_VALUES = tuple(item.value for item in DemoRequestStatus)
DEMO_REVIEW_DECISION_VALUES = tuple(item.value for item in DemoReviewDecision)
DEMO_REQUEST_EVENT_CATEGORY_VALUES = tuple(item.value for item in DemoRequestEventCategory)
DEMO_REQUEST_EVENT_TYPE_VALUES = tuple(item.value for item in DemoRequestEventType)
DEMO_REQUEST_ACTOR_TYPE_VALUES = tuple(item.value for item in DemoRequestActorType)
DEMO_PROVISIONING_STATUS_VALUES = tuple(item.value for item in DemoProvisioningStatus)
DEMO_PROVISIONING_EVENT_TYPE_VALUES = tuple(item.value for item in DemoProvisioningEventType)
DEMO_LIFECYCLE_STATE_VALUES = tuple(item.value for item in DemoLifecycleState)
DEMO_LIFECYCLE_PROCESSING_STATUS_VALUES = tuple(
    item.value for item in DemoLifecycleProcessingStatus
)
DEMO_LIFECYCLE_EVENT_TYPE_VALUES = tuple(item.value for item in DemoLifecycleEventType)
DEMO_LIFECYCLE_NOTIFICATION_TYPE_VALUES = tuple(
    item.value for item in DemoLifecycleNotificationType
)
DEMO_LIFECYCLE_NOTIFICATION_RECIPIENT_VALUES = tuple(
    item.value for item in DemoLifecycleNotificationRecipient
)
