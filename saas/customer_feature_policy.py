"""Stable classification for customer-visible commercial features.

Commercial source and lifecycle determine whether a workspace may operate.
These keys form the normal customer product baseline once that authority is
active and coherent. Capacity, permissions, scope, and consumption remain
independent decisions.
"""

NORMAL_CUSTOMER_FEATURE_KEYS = frozenset(
    {
        "module.teacher_management",
        "module.branch_management",
        "module.observation",
        "module.hiring",
        "module.reporting",
        "module.ai",
        "feature.advanced_reporting",
        "feature.export",
        "feature.cross_branch_reporting",
    }
)

# The catalog name is intentionally retained for compatibility, but the only
# implemented audit export is a Developer-only control and is never part of the
# customer baseline.
INTERNAL_FEATURE_KEYS = frozenset({"feature.audit_log"})


def normalize_feature_key(feature_key: str) -> str:
    return str(feature_key or "").strip().lower()


def is_normal_customer_feature(feature_key: str) -> bool:
    return normalize_feature_key(feature_key) in NORMAL_CUSTOMER_FEATURE_KEYS


def is_internal_feature(feature_key: str) -> bool:
    return normalize_feature_key(feature_key) in INTERNAL_FEATURE_KEYS
