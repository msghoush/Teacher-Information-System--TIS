from dataclasses import dataclass

from saas.customer_feature_policy import NORMAL_CUSTOMER_FEATURE_KEYS


@dataclass(frozen=True)
class DemoProductFeature:
    key: str
    display_name: str
    enabled: bool = True


_DISPLAY_NAMES = {
    "module.teacher_management": "Teacher Management",
    "module.branch_management": "Branch Management",
    "module.observation": "Observations",
    "module.hiring": "Hiring Plan",
    "module.reporting": "Reporting",
    "module.ai": "AI-Assisted Academic Operations",
    "feature.advanced_reporting": "Advanced Reporting",
    "feature.export": "Customer Exports",
    "feature.cross_branch_reporting": "Cross-Branch Reporting",
}

_FEATURES = tuple(
    DemoProductFeature(key, _DISPLAY_NAMES[key])
    for key in sorted(NORMAL_CUSTOMER_FEATURE_KEYS)
)

FEATURES = {feature.key: feature for feature in _FEATURES}


def get_feature(feature_key: str) -> DemoProductFeature | None:
    return FEATURES.get(str(feature_key or "").strip().lower())


def list_features() -> tuple[DemoProductFeature, ...]:
    return _FEATURES
