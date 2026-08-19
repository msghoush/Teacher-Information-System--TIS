"""Small policy boundary separating AI availability from consumption."""

from dataclasses import dataclass

from saas import ai_feature_registry, demo_access_service


@dataclass(frozen=True)
class AIConsumptionPolicy:
    metric_context: str
    usage_limit: int | None
    unrestricted: bool
    reason_code: str


def metric_context_for_entitlement_type(entitlement_type: str) -> str:
    return {
        "internal_sandbox": "internal_sandbox",
        "demo": "demo",
        "paid": "paid",
        "promo": "promo",
    }.get(str(entitlement_type or "").strip().lower(), "unknown")


def resolve_ai_consumption_policy(
    db,
    *,
    school_group_id: int,
    entitlement_type: str,
    feature_key: str,
    branch_id: int | None = None,
) -> AIConsumptionPolicy:
    """Return execution allowance without deciding commercial availability.

    Paid, promo, and internal workspaces currently have no configured provider
    ceiling because no executable provider-backed AI route exists. Demo limits
    retain their established policy and can be configured independently.
    """

    metric_context = metric_context_for_entitlement_type(entitlement_type)
    if metric_context != "demo":
        return AIConsumptionPolicy(
            metric_context=metric_context,
            usage_limit=None,
            unrestricted=True,
            reason_code="unrestricted_current_policy",
        )

    feature = ai_feature_registry.get_feature(feature_key)
    access = demo_access_service.resolve_access(
        db, school_group_id, branch_id=branch_id
    )
    if feature_key in access.unrestricted_ai_features:
        return AIConsumptionPolicy(
            metric_context=metric_context,
            usage_limit=None,
            unrestricted=True,
            reason_code="demo_unrestricted",
        )
    limit = int(access.ai_allowances.get(feature_key, feature.demo_allowance))
    return AIConsumptionPolicy(
        metric_context=metric_context,
        usage_limit=limit,
        unrestricted=False,
        reason_code="demo_limited",
    )
