"""Secure, definition-only promo code administration for Platform Console."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import secrets
import unicodedata
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import audit
import auth
import models as operational_models
from saas import branch_pricing_quote_service, models


PROMO_STATUSES = ("draft", "active", "paused", "revoked")
PROMO_SCOPE_TYPES = (
    "global",
    "organization",
    "pending_organization",
    "account_email",
    "email_domain",
)
PROMO_PLAN_CODES = ("starter", "professional", "enterprise_ai")
PROMO_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PROMO_CODE_RANDOM_LENGTH = 20
PROMO_CODE_PREFIX = "TIS"
PROMO_HMAC_SECRET_ENV = "TIS_PROMO_CODE_HMAC_SECRET"
PROMO_HMAC_KEY_ID_ENV = "TIS_PROMO_CODE_HMAC_KEY_ID"
PROMO_GRANT_ADAPTER_FIELDS = (
    "grant_uuid",
    "school_group_id",
    "organization_id",
    "source",
    "status",
    "plan_identity",
    "effective_from",
    "effective_to",
    "allowed_branches",
    "allowed_staff_users",
    "allowed_teachers",
    "selected_branch_ids",
    "immutable_snapshot_identity",
    "resolution_status",
    "reason_code",
)


class PromoCodeError(ValueError):
    def __init__(self, reason_code: str, message: str):
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class CreatedPromo:
    promo: models.PromoCode
    raw_code: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_promo_code(value: str) -> str:
    cleaned = unicodedata.normalize("NFKC", str(value or "")).upper()
    for separator in ("-", " ", "\t", "\r", "\n"):
        cleaned = cleaned.replace(separator, "")
    return cleaned


def _hmac_configuration() -> tuple[bytes, str]:
    secret = str(os.getenv(PROMO_HMAC_SECRET_ENV) or "")
    if len(secret.encode("utf-8")) < 32:
        raise PromoCodeError(
            "promo_hmac_unavailable",
            "Promo code security configuration is unavailable.",
        )
    key_id = str(os.getenv(PROMO_HMAC_KEY_ID_ENV) or "v1").strip()
    if not key_id or len(key_id) > 40:
        raise PromoCodeError(
            "promo_hmac_key_id_invalid",
            "Promo code security configuration is unavailable.",
        )
    return secret.encode("utf-8"), key_id


def promo_lookup_hash(value: str) -> tuple[str, str]:
    secret, key_id = _hmac_configuration()
    normalized = normalize_promo_code(value)
    if not normalized:
        raise PromoCodeError("promo_code_invalid", "Promo code is invalid.")
    digest = hmac.new(secret, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest, key_id


def _generate_raw_code() -> str:
    random_part = "".join(
        secrets.choice(PROMO_CODE_ALPHABET) for _ in range(PROMO_CODE_RANDOM_LENGTH)
    )
    groups = [random_part[index:index + 5] for index in range(0, len(random_part), 5)]
    return "-".join((PROMO_CODE_PREFIX, *groups))


def masked_code(promo: models.PromoCode) -> str:
    return f"{promo.code_display_prefix}-*****-*****-{promo.code_display_suffix}"


def effective_status(promo: models.PromoCode, *, now: datetime | None = None) -> str:
    current = _utc(now) or utc_now()
    deadline = _utc(promo.redemption_deadline)
    if promo.status != "revoked" and deadline and current > deadline:
        return "expired"
    return str(promo.status)


def _normalize_domain(value: str | None) -> str | None:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    normalized = normalized.removeprefix("@").rstrip(".")
    if not normalized:
        return None
    if "@" in normalized or "." not in normalized or any(ch.isspace() for ch in normalized):
        raise PromoCodeError("invalid_email_domain", "Enter a valid permitted email domain.")
    return normalized


def _normalize_email(value: str | None) -> str | None:
    normalized = auth.normalize_email(str(value or ""))
    if not normalized:
        return None
    if "@" not in normalized:
        raise PromoCodeError("invalid_account_email", "Enter a valid intended account email.")
    return normalized


def _plan(db: Session, plan_id: int):
    plan = db.query(models.SubscriptionPlan).filter_by(id=int(plan_id or 0)).one_or_none()
    if not plan or not plan.is_active or str(plan.plan_code) not in PROMO_PLAN_CODES:
        raise PromoCodeError("invalid_promo_plan", "Select an active TIS promo tier.")
    return plan


def list_available_plans(db: Session):
    return db.query(models.SubscriptionPlan).filter(
        models.SubscriptionPlan.is_active == True,
        models.SubscriptionPlan.plan_code.in_(PROMO_PLAN_CODES),
    ).order_by(models.SubscriptionPlan.sort_order, models.SubscriptionPlan.id).all()


def _positive_int(value, *, field: str, allow_zero: bool = False) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = -1
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        label = field.replace("_", " ")
        raise PromoCodeError(f"invalid_{field}", f"{label.capitalize()} must be {minimum} or greater.")
    return parsed


def _validate_scope(
    db: Session,
    *,
    scope_type: str,
    school_group_id: int | None,
    pending_organization_id: int | None,
    intended_email: str | None,
    permitted_domain: str | None,
    branch_ids: tuple[int, ...],
) -> tuple[object | None, object | None, str | None]:
    if scope_type not in PROMO_SCOPE_TYPES:
        raise PromoCodeError("invalid_scope", "Select a valid promo scope.")
    group = None
    pending = None
    if school_group_id:
        group = db.query(operational_models.SchoolGroup).filter_by(id=school_group_id).one_or_none()
        if not group:
            raise PromoCodeError("organization_target_missing", "The selected organization is unavailable.")
    if pending_organization_id:
        pending = db.query(models.PendingOrganization).filter_by(id=pending_organization_id).one_or_none()
        if not pending:
            raise PromoCodeError("pending_target_missing", "The selected pending organization is unavailable.")
    anchors = (group, pending, intended_email, permitted_domain)
    if scope_type == "global" and any(anchors):
        raise PromoCodeError("global_scope_has_targets", "Global promos cannot include target restrictions.")
    required = {
        "organization": group,
        "pending_organization": pending,
        "account_email": intended_email,
        "email_domain": permitted_domain,
    }.get(scope_type, True)
    if not required:
        raise PromoCodeError("scope_target_required", "The selected promo scope requires a target.")
    if intended_email and permitted_domain and intended_email.rsplit("@", 1)[-1] != permitted_domain:
        raise PromoCodeError("conflicting_email_scope", "The intended account email does not match the permitted domain.")
    if group and pending:
        tenant_link = db.query(models.TenantProvisioningLink).filter_by(
            pending_organization_id=pending.id,
            school_group_id=group.id,
        ).one_or_none()
        if not tenant_link:
            raise PromoCodeError(
                "conflicting_organization_scope",
                "The selected pending and operational organizations are not linked.",
            )
    branches = []
    if branch_ids:
        if not group:
            raise PromoCodeError(
                "branch_scope_requires_organization",
                "Eligible branch restrictions require an operational organization target.",
            )
        branches = db.query(operational_models.Branch).filter(
            operational_models.Branch.id.in_(branch_ids)
        ).all()
        if len(branches) != len(set(branch_ids)) or any(row.school_group_id != group.id for row in branches):
            raise PromoCodeError(
                "conflicting_branch_scope",
                "Every eligible branch must belong to the selected organization.",
            )
    snapshot_parts = []
    if group:
        snapshot_parts.append(f"organization:{group.id}:{group.name}")
    if pending:
        snapshot_parts.append(f"pending:{pending.id}:{pending.organization_name}")
    if intended_email:
        snapshot_parts.append(f"email:{intended_email}")
    if permitted_domain:
        snapshot_parts.append(f"domain:{permitted_domain}")
    return group, pending, " | ".join(snapshot_parts) or None


def _validated_definition(db: Session, values: dict) -> dict:
    plan = _plan(db, int(values.get("subscription_plan_id") or 0))
    capacities = {
        "max_branches": _positive_int(values.get("max_branches"), field="max_branches"),
        "max_system_users": _positive_int(values.get("max_system_users"), field="max_system_users"),
        "max_teachers": _positive_int(values.get("max_teachers"), field="max_teachers"),
    }
    try:
        branch_pricing_quote_service.require_plan_capacity(
            plan,
            active_branch_count=capacities["max_branches"],
            active_system_user_count=capacities["max_system_users"],
            active_teacher_count=capacities["max_teachers"],
        )
    except ValueError as exc:
        raise PromoCodeError("promo_capacity_exceeds_plan", str(exc)) from exc
    valid_from = _utc(values.get("valid_from"))
    deadline = _utc(values.get("redemption_deadline"))
    fixed_expiry = _utc(values.get("fixed_access_expires_at"))
    duration = values.get("access_duration_days")
    duration = _positive_int(duration, field="access_duration_days") if duration not in (None, "") else None
    if not valid_from or not deadline or valid_from >= deadline:
        raise PromoCodeError("invalid_validity_order", "Valid from must be earlier than the redemption deadline.")
    if (fixed_expiry is None) == (duration is None):
        raise PromoCodeError(
            "invalid_expiry_policy",
            "Choose exactly one access expiry policy: a fixed expiry or an access duration.",
        )
    if fixed_expiry and fixed_expiry <= deadline:
        raise PromoCodeError("invalid_fixed_expiry", "Fixed access expiry must follow the redemption deadline.")
    email = _normalize_email(values.get("intended_account_email_normalized"))
    domain = _normalize_domain(values.get("permitted_email_domain_normalized"))
    scope_type = str(values.get("scope_type") or "").strip()
    branch_ids = tuple(sorted({int(item) for item in values.get("branch_ids", ()) if int(item) > 0}))
    school_group_id = int(values.get("school_group_id") or 0) or None
    pending_id = int(values.get("pending_organization_id") or 0) or None
    group, pending, scope_snapshot = _validate_scope(
        db,
        scope_type=scope_type,
        school_group_id=school_group_id,
        pending_organization_id=pending_id,
        intended_email=email,
        permitted_domain=domain,
        branch_ids=branch_ids,
    )
    title = " ".join(str(values.get("title") or "").split())
    if not title:
        raise PromoCodeError("title_required", "Enter an internal promo title.")
    return {
        "title": title[:160],
        "internal_purpose": str(values.get("internal_purpose") or "").strip() or None,
        "benefit_type": "full_access",
        "subscription_plan_id": plan.id,
        **capacities,
        "scope_type": scope_type,
        "school_group_id": getattr(group, "id", None),
        "pending_organization_id": getattr(pending, "id", None),
        "intended_account_email_normalized": email,
        "permitted_email_domain_normalized": domain,
        "scope_target_snapshot": scope_snapshot,
        "transferable": bool(values.get("transferable", False)),
        "one_redemption_per_organization": bool(values.get("one_redemption_per_organization", True)),
        "max_total_redemptions": _positive_int(values.get("max_total_redemptions", 1), field="max_total_redemptions"),
        "valid_from": valid_from,
        "redemption_deadline": deadline,
        "fixed_access_expires_at": fixed_expiry,
        "access_duration_days": duration,
        "grace_period_days": _positive_int(values.get("grace_period_days", 0), field="grace_period_days", allow_zero=True),
        "branch_ids": branch_ids,
        "plan": plan,
    }


AUDIT_FIELDS = (
    "title", "status", "definition_version", "benefit_type", "subscription_plan_id",
    "max_branches", "max_system_users", "max_teachers", "scope_type", "school_group_id",
    "pending_organization_id", "permitted_email_domain_normalized", "transferable",
    "one_redemption_per_organization",
    "max_total_redemptions", "valid_from", "redemption_deadline", "fixed_access_expires_at",
    "access_duration_days", "grace_period_days", "supersedes_promo_code_id",
)


def _safe_state(promo: models.PromoCode) -> dict:
    state = {}
    for field in AUDIT_FIELDS:
        value = getattr(promo, field, None)
        state[field] = value.isoformat() if isinstance(value, datetime) else value
    state["intended_account_email_restricted"] = bool(
        promo.intended_account_email_normalized
    )
    state["masked_code"] = masked_code(promo)
    return state


def _record_audit(
    db: Session, *, promo: models.PromoCode, actor, action: str, previous: dict,
    new: dict, result: str = "success", reason: str = "", operation_key: str | None = None,
    request_correlation_id: str | None = None, failure_code: str | None = None,
) -> models.PromoCodeAuditEvent:
    key = str(operation_key or uuid.uuid4())[:120]
    existing = db.query(models.PromoCodeAuditEvent).filter_by(
        promo_uuid_snapshot=promo.promo_uuid,
        action=action,
        operation_key=key,
    ).one_or_none()
    if existing:
        return existing
    event = models.PromoCodeAuditEvent(
        promo_code_id=promo.id,
        promo_uuid_snapshot=promo.promo_uuid,
        actor_user_id=getattr(actor, "id", None),
        action=action,
        result=result,
        reason=str(reason or "").strip() or None,
        previous_values_json=json.dumps(previous, sort_keys=True, separators=(",", ":")),
        new_values_json=json.dumps(new, sort_keys=True, separators=(",", ":")),
        operation_key=key,
        request_correlation_id=str(request_correlation_id or "")[:120] or None,
        failure_code=failure_code,
    )
    db.add(event)
    db.flush()
    audit.write_audit_event({
        "event_type": f"promo_code_{action}",
        "promo_uuid": promo.promo_uuid,
        "masked_code": masked_code(promo),
        "actor_user_id": getattr(actor, "id", None),
        "result": result,
        "failure_code": failure_code,
    })
    return event


def record_failed_action(
    db: Session, *, actor, action: str, reason: str, failure_code: str,
    promo_uuid: str | None = None, operation_key: str | None = None,
    request_correlation_id: str | None = None, result: str = "blocked",
) -> models.PromoCodeAuditEvent:
    """Persist a safe failed/blocked attempt after the caller rolls back state."""
    promo = get_promo(db, promo_uuid) if promo_uuid else None
    if promo:
        return _record_audit(
            db,
            promo=promo,
            actor=actor,
            action=action,
            previous=_safe_state(promo),
            new={},
            result=result,
            reason=reason,
            operation_key=operation_key,
            request_correlation_id=request_correlation_id,
            failure_code=failure_code,
        )
    event = models.PromoCodeAuditEvent(
        promo_code_id=None,
        promo_uuid_snapshot=str(uuid.uuid4()),
        actor_user_id=getattr(actor, "id", None),
        action=action,
        result=result,
        reason=str(reason or "").strip() or None,
        previous_values_json="{}",
        new_values_json="{}",
        operation_key=str(operation_key or uuid.uuid4())[:120],
        request_correlation_id=str(request_correlation_id or "")[:120] or None,
        failure_code=str(failure_code or "promo_operation_failed")[:80],
    )
    db.add(event)
    db.flush()
    audit.write_audit_event({
        "event_type": f"promo_code_{action}",
        "actor_user_id": getattr(actor, "id", None),
        "result": result,
        "failure_code": event.failure_code,
    })
    return event


def _replace_branch_restrictions(db: Session, promo: models.PromoCode, branch_ids: tuple[int, ...]) -> None:
    db.query(models.PromoCodeBranchRestriction).filter_by(promo_code_id=promo.id).delete(
        synchronize_session=False
    )
    if not branch_ids:
        return
    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.id.in_(branch_ids)
    ).order_by(operational_models.Branch.id).all()
    for branch in branches:
        db.add(models.PromoCodeBranchRestriction(
            promo_code_id=promo.id,
            branch_id=branch.id,
            branch_id_snapshot=branch.id,
            branch_name_snapshot=branch.name,
        ))


def create_promo(
    db: Session, *, actor, values: dict, action: str = "create",
    supersedes_promo_code_id: int | None = None, operation_key: str | None = None,
    request_correlation_id: str | None = None,
) -> CreatedPromo:
    definition = _validated_definition(db, values)
    for _attempt in range(8):
        raw_code = _generate_raw_code()
        lookup_hash, key_id = promo_lookup_hash(raw_code)
        normalized = normalize_promo_code(raw_code)
        promo = models.PromoCode(
            code_lookup_hash=lookup_hash,
            code_hash_key_id=key_id,
            code_display_prefix=f"{PROMO_CODE_PREFIX}-{normalized[3:8]}",
            code_display_suffix=normalized[-5:],
            status="draft",
            definition_version=1,
            supersedes_promo_code_id=supersedes_promo_code_id,
            created_by_user_id=getattr(actor, "id", None),
            updated_by_user_id=getattr(actor, "id", None),
            **{key: value for key, value in definition.items() if key not in {"branch_ids", "plan"}},
        )
        try:
            with db.begin_nested():
                db.add(promo)
                db.flush()
        except IntegrityError as exc:
            if "lookup_hash" in str(exc).casefold():
                continue
            raise PromoCodeError("promo_definition_conflict", "The promo definition conflicts with an existing record.") from exc
        _replace_branch_restrictions(db, promo, definition["branch_ids"])
        db.flush()
        _record_audit(
            db, promo=promo, actor=actor, action=action, previous={}, new=_safe_state(promo),
            operation_key=operation_key, request_correlation_id=request_correlation_id,
        )
        return CreatedPromo(promo=promo, raw_code=raw_code)
    raise PromoCodeError("promo_code_collision", "A secure promo code could not be generated. Please retry.")


def get_promo(db: Session, promo_uuid: str, *, lock: bool = False):
    query = db.query(models.PromoCode).filter_by(promo_uuid=str(promo_uuid or "").strip())
    return query.with_for_update().one_or_none() if lock else query.one_or_none()


def update_promo(
    db: Session, *, promo_uuid: str, actor, values: dict,
    operation_key: str | None = None, request_correlation_id: str | None = None,
):
    promo = get_promo(db, promo_uuid, lock=True)
    if not promo:
        raise PromoCodeError("promo_not_found", "Promo definition was not found.")
    if promo.status == "active":
        raise PromoCodeError("active_promo_requires_pause", "Pause this promo before editing its definition.")
    if promo.status == "revoked":
        raise PromoCodeError("revoked_promo_terminal", "Revoked promos cannot be edited.")
    definition = _validated_definition(db, values)
    previous = _safe_state(promo)
    for key, value in definition.items():
        if key not in {"branch_ids", "plan"}:
            setattr(promo, key, value)
    promo.status = "draft"
    promo.definition_version = int(promo.definition_version or 0) + 1
    promo.approved_by_user_id = None
    promo.approved_at = None
    promo.activated_at = None
    promo.paused_at = None
    promo.updated_by_user_id = getattr(actor, "id", None)
    _replace_branch_restrictions(db, promo, definition["branch_ids"])
    db.flush()
    _record_audit(
        db, promo=promo, actor=actor, action="edit", previous=previous, new=_safe_state(promo),
        operation_key=operation_key, request_correlation_id=request_correlation_id,
    )
    return promo


def activate_promo(db: Session, *, promo_uuid: str, actor, operation_key: str | None = None):
    if not auth.is_platform_owner(actor):
        raise PromoCodeError("owner_approval_required", "Platform Owner approval is required.")
    promo = get_promo(db, promo_uuid, lock=True)
    if not promo:
        raise PromoCodeError("promo_not_found", "Promo definition was not found.")
    if promo.status != "draft":
        raise PromoCodeError("invalid_activation_state", "Only a draft promo can be activated.")
    if effective_status(promo) == "expired":
        raise PromoCodeError("promo_expired", "An expired promo cannot be activated.")
    _validated_definition(db, _definition_values(db, promo))
    previous = _safe_state(promo)
    now = utc_now()
    promo.status = "active"
    promo.approved_by_user_id = actor.id
    promo.approved_at = now
    promo.activated_at = now
    promo.paused_at = None
    promo.updated_by_user_id = actor.id
    db.flush()
    _record_audit(db, promo=promo, actor=actor, action="activate", previous=previous, new=_safe_state(promo), operation_key=operation_key)
    return promo


def pause_promo(db: Session, *, promo_uuid: str, actor, operation_key: str | None = None):
    promo = get_promo(db, promo_uuid, lock=True)
    if not promo:
        raise PromoCodeError("promo_not_found", "Promo definition was not found.")
    if promo.status != "active":
        raise PromoCodeError("invalid_pause_state", "Only an active promo can be paused.")
    previous = _safe_state(promo)
    promo.status = "paused"
    promo.paused_at = utc_now()
    promo.updated_by_user_id = getattr(actor, "id", None)
    db.flush()
    _record_audit(db, promo=promo, actor=actor, action="pause", previous=previous, new=_safe_state(promo), operation_key=operation_key)
    return promo


def revoke_promo(
    db: Session, *, promo_uuid: str, actor, reason: str, operation_key: str | None = None,
):
    if not auth.is_platform_owner(actor):
        raise PromoCodeError("owner_revocation_required", "Platform Owner approval is required.")
    cleaned_reason = str(reason or "").strip()
    if not cleaned_reason:
        raise PromoCodeError("revocation_reason_required", "Enter a reason for revoking this promo.")
    promo = get_promo(db, promo_uuid, lock=True)
    if not promo:
        raise PromoCodeError("promo_not_found", "Promo definition was not found.")
    if promo.status == "revoked":
        raise PromoCodeError("revoked_promo_terminal", "This promo is already revoked.")
    previous = _safe_state(promo)
    promo.status = "revoked"
    promo.revoked_at = utc_now()
    promo.revocation_reason = cleaned_reason
    promo.updated_by_user_id = actor.id
    db.flush()
    _record_audit(db, promo=promo, actor=actor, action="revoke", previous=previous, new=_safe_state(promo), reason=cleaned_reason, operation_key=operation_key)
    return promo


def _definition_values(db: Session, promo: models.PromoCode) -> dict:
    branch_ids = tuple(row.branch_id for row in db.query(models.PromoCodeBranchRestriction).filter_by(
        promo_code_id=promo.id
    ).all() if row.branch_id)
    return {
        field: getattr(promo, field)
        for field in (
            "title", "internal_purpose", "subscription_plan_id", "max_branches",
            "max_system_users", "max_teachers", "scope_type", "school_group_id",
            "pending_organization_id", "intended_account_email_normalized",
            "permitted_email_domain_normalized", "transferable",
            "one_redemption_per_organization", "max_total_redemptions", "valid_from",
            "redemption_deadline", "fixed_access_expires_at", "access_duration_days",
            "grace_period_days",
        )
    } | {"branch_ids": branch_ids}


def duplicate_promo(db: Session, *, promo_uuid: str, actor, operation_key: str | None = None) -> CreatedPromo:
    source = get_promo(db, promo_uuid, lock=True)
    if not source:
        raise PromoCodeError("promo_not_found", "Promo definition was not found.")
    values = _definition_values(db, source)
    values["title"] = f"{source.title} (Copy)"
    return create_promo(db, actor=actor, values=values, action="duplicate", operation_key=operation_key)


def replace_promo(db: Session, *, promo_uuid: str, actor, operation_key: str | None = None) -> CreatedPromo:
    source = get_promo(db, promo_uuid, lock=True)
    if not source:
        raise PromoCodeError("promo_not_found", "Promo definition was not found.")
    if source.supersedes_promo_code_id == source.id:
        raise PromoCodeError("replacement_cycle", "Promo replacement cycles are not allowed.")
    existing = db.query(models.PromoCode).filter_by(supersedes_promo_code_id=source.id).one_or_none()
    if existing:
        raise PromoCodeError("replacement_exists", "This promo already has a replacement definition.")
    values = _definition_values(db, source)
    values["title"] = f"{source.title} (Replacement)"
    return create_promo(
        db, actor=actor, values=values, action="replace",
        supersedes_promo_code_id=source.id, operation_key=operation_key,
    )


def list_audit_events(db: Session, promo_id: int):
    return db.query(models.PromoCodeAuditEvent).filter_by(promo_code_id=promo_id).order_by(
        models.PromoCodeAuditEvent.created_at.desc(), models.PromoCodeAuditEvent.id.desc()
    ).all()


def list_branch_restrictions(db: Session, promo_id: int):
    return db.query(models.PromoCodeBranchRestriction).filter_by(promo_code_id=promo_id).order_by(
        models.PromoCodeBranchRestriction.branch_name_snapshot,
        models.PromoCodeBranchRestriction.id,
    ).all()
