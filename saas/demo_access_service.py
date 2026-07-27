from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import ai_feature_registry, demo_feature_registry, models
from workspace_classification import WorkspaceClassification


STANDARD = "standard"
FULL = "full"
CUSTOM = "custom"
PROFILES = {STANDARD, FULL, CUSTOM}


class DemoAccessError(ValueError):
    def __init__(self, message: str, *, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class EffectiveDemoAccess:
    profile: str
    school_group_id: int
    branch_id: int | None
    source: str
    product_features: frozenset[str]
    ai_features: frozenset[str]
    ai_allowances: dict[str, int]
    unrestricted_ai_features: frozenset[str]


def _load_list(value) -> frozenset[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        parsed = []
    return frozenset(str(item).strip().lower() for item in parsed if str(item).strip())


def _load_allowances(value) -> dict[str, int]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        parsed = {}
    result = {}
    for key, amount in parsed.items() if isinstance(parsed, dict) else ():
        try:
            normalized = int(amount)
        except (TypeError, ValueError):
            continue
        if normalized >= 0:
            result[str(key).strip().lower()] = normalized
    return result


def _standard(group_id: int, branch_id: int | None = None) -> EffectiveDemoAccess:
    enabled_ai = frozenset(feature.key for feature in ai_feature_registry.list_features() if feature.enabled)
    return EffectiveDemoAccess(
        profile=STANDARD,
        school_group_id=group_id,
        branch_id=branch_id,
        source="standard_default",
        product_features=frozenset(feature.key for feature in demo_feature_registry.list_features() if feature.enabled),
        ai_features=enabled_ai,
        ai_allowances={
            feature.key: int(feature.demo_allowance)
            for feature in ai_feature_registry.list_features()
            if feature.enabled
        },
        unrestricted_ai_features=frozenset(),
    )


def resolve_access(
    db: Session,
    school_group_id: int,
    *,
    branch_id: int | None = None,
) -> EffectiveDemoAccess:
    group_id = int(school_group_id)
    row = None
    if branch_id is not None:
        row = db.query(models.DemoAccessPolicy).filter_by(
            school_group_id=group_id, branch_id=int(branch_id)
        ).one_or_none()
    if row is None:
        row = db.query(models.DemoAccessPolicy).filter(
            models.DemoAccessPolicy.school_group_id == group_id,
            models.DemoAccessPolicy.branch_id.is_(None),
        ).one_or_none()
    if row is None or row.access_profile == STANDARD:
        return _standard(group_id, branch_id)
    if row.access_profile == FULL:
        return EffectiveDemoAccess(
            profile=FULL,
            school_group_id=group_id,
            branch_id=branch_id,
            source="branch_override" if row.branch_id else "workspace_policy",
            product_features=frozenset(
                feature.key for feature in demo_feature_registry.list_features() if feature.enabled
            ),
            ai_features=frozenset(
                feature.key for feature in ai_feature_registry.list_features() if feature.enabled
            ),
            ai_allowances={},
            unrestricted_ai_features=frozenset(
                feature.key for feature in ai_feature_registry.list_features() if feature.enabled
            ),
        )
    return EffectiveDemoAccess(
        profile=CUSTOM,
        school_group_id=group_id,
        branch_id=branch_id,
        source="branch_override" if row.branch_id else "workspace_policy",
        product_features=_load_list(row.product_features_json),
        ai_features=_load_list(row.ai_features_json),
        ai_allowances=_load_allowances(row.ai_allowances_json),
        unrestricted_ai_features=_load_list(row.unrestricted_ai_features_json),
    )


def _validate_scope(db: Session, school_group_id: int, branch_id: int | None):
    group = db.get(operational_models.SchoolGroup, int(school_group_id))
    if (
        group is None
        or group.workspace_classification != WorkspaceClassification.CUSTOMER_DEMO.value
    ):
        raise DemoAccessError("Customer Demo workspace is required.", reason_code="not_customer_demo")
    if branch_id is not None:
        branch = db.get(operational_models.Branch, int(branch_id))
        if branch is None or int(branch.school_group_id or 0) != group.id:
            raise DemoAccessError("Branch is outside the selected workspace.", reason_code="invalid_branch_scope")
    return group


def set_access_policy(
    db: Session,
    *,
    actor,
    school_group_id: int,
    profile: str,
    reason: str,
    branch_id: int | None = None,
    product_features=(),
    ai_features=(),
    ai_allowances=None,
    unrestricted_ai_features=(),
):
    if not auth.is_platform_owner(actor):
        raise DemoAccessError("Platform Owner access is required.", reason_code="platform_owner_required")
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        raise DemoAccessError("A reason is required.", reason_code="reason_required")
    cleaned_profile = str(profile or "").strip().lower()
    if cleaned_profile not in PROFILES:
        raise DemoAccessError("Unknown demo access profile.", reason_code="unknown_access_profile")
    group = _validate_scope(db, school_group_id, branch_id)
    product_keys = {str(key).strip().lower() for key in product_features if str(key).strip()}
    ai_keys = {str(key).strip().lower() for key in ai_features if str(key).strip()}
    unlimited = {
        str(key).strip().lower() for key in unrestricted_ai_features if str(key).strip()
    }
    allowances = {
        str(key).strip().lower(): int(value)
        for key, value in dict(ai_allowances or {}).items()
    }
    if any(demo_feature_registry.get_feature(key) is None for key in product_keys):
        raise DemoAccessError("Unknown product feature.", reason_code="unknown_product_feature")
    if any(ai_feature_registry.get_feature(key) is None for key in ai_keys | unlimited | set(allowances)):
        raise DemoAccessError("Unknown AI feature.", reason_code="unknown_ai_feature")
    if unlimited - ai_keys or set(allowances) - ai_keys:
        raise DemoAccessError("AI configuration must reference selected features.", reason_code="invalid_ai_configuration")
    if any(value < 0 for value in allowances.values()):
        raise DemoAccessError("AI allowances cannot be negative.", reason_code="invalid_ai_allowance")
    if cleaned_profile != CUSTOM:
        product_keys, ai_keys, unlimited, allowances = set(), set(), set(), {}

    query = db.query(models.DemoAccessPolicy).filter(
        models.DemoAccessPolicy.school_group_id == group.id
    )
    query = query.filter(
        models.DemoAccessPolicy.branch_id == int(branch_id)
        if branch_id is not None
        else models.DemoAccessPolicy.branch_id.is_(None)
    )
    row = query.with_for_update().one_or_none()
    previous = resolve_access(db, group.id, branch_id=branch_id)
    if row is None:
        row = models.DemoAccessPolicy(
            school_group_id=group.id,
            branch_id=int(branch_id) if branch_id is not None else None,
        )
        db.add(row)
    row.access_profile = cleaned_profile
    row.product_features_json = json.dumps(sorted(product_keys), separators=(",", ":"))
    row.ai_features_json = json.dumps(sorted(ai_keys), separators=(",", ":"))
    row.ai_allowances_json = json.dumps(allowances, sort_keys=True, separators=(",", ":"))
    row.unrestricted_ai_features_json = json.dumps(sorted(unlimited), separators=(",", ":"))
    row.reason = cleaned_reason
    row.updated_by_user_id = getattr(actor, "id", None)
    db.flush()
    return row, previous, resolve_access(db, group.id, branch_id=branch_id)


def product_feature_allowed(
    db: Session, school_group_id: int, feature_key: str, *, branch_id: int | None = None
) -> bool:
    feature = demo_feature_registry.get_feature(feature_key)
    if feature is None or not feature.enabled:
        return False
    return feature.key in resolve_access(db, school_group_id, branch_id=branch_id).product_features
