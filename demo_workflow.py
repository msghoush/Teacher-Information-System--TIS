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


DEMO_REQUEST_STATUS_VALUES = tuple(item.value for item in DemoRequestStatus)
DEMO_REVIEW_DECISION_VALUES = tuple(item.value for item in DemoReviewDecision)
DEMO_REQUEST_EVENT_CATEGORY_VALUES = tuple(item.value for item in DemoRequestEventCategory)
DEMO_REQUEST_EVENT_TYPE_VALUES = tuple(item.value for item in DemoRequestEventType)
DEMO_REQUEST_ACTOR_TYPE_VALUES = tuple(item.value for item in DemoRequestActorType)
