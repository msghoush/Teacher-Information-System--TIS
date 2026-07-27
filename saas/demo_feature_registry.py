from dataclasses import dataclass


@dataclass(frozen=True)
class DemoProductFeature:
    key: str
    display_name: str
    enabled: bool = True


_FEATURES = (
    DemoProductFeature("feature.advanced_reporting", "Advanced Reporting"),
    DemoProductFeature("module.ai", "AI-Assisted Academic Operations"),
)

FEATURES = {feature.key: feature for feature in _FEATURES}


def get_feature(feature_key: str) -> DemoProductFeature | None:
    return FEATURES.get(str(feature_key or "").strip().lower())


def list_features() -> tuple[DemoProductFeature, ...]:
    return _FEATURES
