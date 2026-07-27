from dataclasses import dataclass


AI_PERMISSION_KEY = "ai.use"


@dataclass(frozen=True)
class AIFeatureDefinition:
    key: str
    display_name: str
    entitlement_key: str
    permission_key: str
    eligible_plan_codes: tuple[str, ...]
    demo_allowance: int
    enabled: bool = True


_FEATURES = (
    AIFeatureDefinition(
        key="ai.academic_assistant",
        display_name="TIS AI Academic Assistant",
        entitlement_key="module.ai",
        permission_key=AI_PERMISSION_KEY,
        eligible_plan_codes=("enterprise_ai",),
        demo_allowance=2,
    ),
    AIFeatureDefinition(
        key="ai.exam_analysis",
        display_name="AI Exam Analysis",
        entitlement_key="module.ai",
        permission_key=AI_PERMISSION_KEY,
        eligible_plan_codes=("enterprise_ai",),
        demo_allowance=2,
    ),
    AIFeatureDefinition(
        key="ai.coaching_recommendations",
        display_name="AI Coaching Recommendations",
        entitlement_key="module.ai",
        permission_key=AI_PERMISSION_KEY,
        eligible_plan_codes=("enterprise_ai",),
        demo_allowance=2,
    ),
    AIFeatureDefinition(
        key="ai.action_plan_generation",
        display_name="AI Action Plan Generation",
        entitlement_key="module.ai",
        permission_key=AI_PERMISSION_KEY,
        eligible_plan_codes=("enterprise_ai",),
        demo_allowance=2,
    ),
    AIFeatureDefinition(
        key="ai.assessment_quality_review",
        display_name="AI Assessment Quality Review",
        entitlement_key="module.ai",
        permission_key=AI_PERMISSION_KEY,
        eligible_plan_codes=("enterprise_ai",),
        demo_allowance=2,
        enabled=False,
    ),
)

FEATURES = {feature.key: feature for feature in _FEATURES}


def get_feature(feature_key: str) -> AIFeatureDefinition | None:
    return FEATURES.get(str(feature_key or "").strip().lower())


def list_features() -> tuple[AIFeatureDefinition, ...]:
    return _FEATURES
