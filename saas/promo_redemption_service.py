from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import audit
import auth
import models as operational_models
from commercial_entitlements import BranchEntitlementMode
from saas import (
    commercial_authority_service,
    models,
    promo_code_service,
    provisioning_service,
    service,
)
from workspace_classification import WorkspaceClassification, WorkspaceIntent, WorkspaceLifecycleStatus


GENERIC_INVALID_MESSAGE = "This promo code could not be applied. Check the code and try again."
logger = logging.getLogger(__name__)


class PromoActivationError(ValueError):
    def __init__(self, reason_code: str, message: str = GENERIC_INVALID_MESSAGE):
        self.reason_code = reason_code
        super().__init__(message)


@dataclass(frozen=True)
class PromoActivationReview:
    session: object
    promo: object
    plan: object
    organization: object | None
    school_group: object | None
    branches: tuple
    selected_branch_ids: frozenset[int]
    branch_identity_kind: str
    current_branches: int
    current_staff_users: int
    current_teachers: int
    allowed_branches: int
    allowed_staff_users: int
    allowed_teachers: int
    exceeded_dimensions: tuple[str, ...]
    selection_required: bool
    ready_to_activate: bool


@dataclass(frozen=True)
class ActivatedPromo:
    session: object
    redemption: object
    grant: object
    workspace_entitlement: object
    tenant_link: object
    school_group: object


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _db_time(value: datetime) -> datetime:
    return _utc(value)


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _snapshot_hash(value: dict) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _event(
    db: Session,
    *,
    event_type: str,
    result: str,
    operation_key: str,
    account=None,
    session=None,
    promo=None,
    redemption=None,
    grant=None,
    organization=None,
    school_group=None,
    failure_code: str | None = None,
    details: dict | None = None,
):
    existing = db.query(models.PromoRedemptionEvent).filter(
        models.PromoRedemptionEvent.operation_key == str(operation_key)[:120],
        models.PromoRedemptionEvent.event_type == event_type,
    ).one_or_none()
    if existing:
        return existing
    row = models.PromoRedemptionEvent(
        promo_code_id=getattr(promo, "id", None),
        activation_session_id=getattr(session, "id", None),
        promo_redemption_id=getattr(redemption, "id", None),
        promo_grant_id=getattr(grant, "id", None),
        actor_saas_account_id=getattr(account, "id", None),
        actor_operational_user_id=getattr(session, "operational_user_id", None),
        pending_organization_id=getattr(organization, "id", None),
        school_group_id=getattr(school_group, "id", None),
        event_type=event_type,
        result=result,
        failure_code=failure_code,
        operation_key=str(operation_key)[:120],
        details_json=_canonical_json(details or {}),
    )
    db.add(row)
    db.flush()
    audit.write_audit_event({
        "event_type": f"promo_redemption_{event_type}",
        "result": result,
        "actor_saas_account_id": getattr(account, "id", None),
        "pending_organization_id": getattr(organization, "id", None),
        "school_group_id": getattr(school_group, "id", None),
        "failure_code": failure_code,
    })
    return row


def find_promo_by_code(db: Session, raw_code: str, *, lock: bool = False):
    try:
        lookup_hash, key_id = promo_code_service.promo_lookup_hash(raw_code)
    except promo_code_service.PromoCodeError as exc:
        raise PromoActivationError(exc.reason_code) from exc
    query = db.query(models.PromoCode).filter(
        models.PromoCode.code_lookup_hash == lookup_hash,
        models.PromoCode.code_hash_key_id == key_id,
    )
    return query.with_for_update().one_or_none() if lock else query.one_or_none()


def _validate_promo_definition(
    db: Session,
    promo,
    *,
    account,
    organization=None,
    school_group=None,
    now: datetime | None = None,
) -> None:
    current = _utc(now) or utc_now()
    if promo is None or promo_code_service.effective_status(promo, now=current) != "active":
        raise PromoActivationError("promo_not_active")
    if _utc(promo.valid_from) > current or current > _utc(promo.redemption_deadline):
        raise PromoActivationError("promo_outside_redemption_window")
    replacement = db.query(models.PromoCode.id).filter(
        models.PromoCode.supersedes_promo_code_id == promo.id,
        models.PromoCode.status == "active",
    ).first()
    if replacement:
        raise PromoActivationError("promo_replaced")
    if not promo.approved_at or not promo.approved_by_user_id:
        raise PromoActivationError("promo_not_approved")

    email = auth.normalize_email(getattr(account, "email", ""))
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    scope = str(promo.scope_type or "")
    if promo.intended_account_email_normalized and email != promo.intended_account_email_normalized:
        raise PromoActivationError("promo_account_scope_mismatch")
    if promo.permitted_email_domain_normalized and domain != promo.permitted_email_domain_normalized:
        raise PromoActivationError("promo_domain_scope_mismatch")
    if scope == "organization" and int(promo.school_group_id or 0) != int(getattr(school_group, "id", 0) or 0):
        raise PromoActivationError("promo_organization_scope_mismatch")
    if scope == "pending_organization" and int(promo.pending_organization_id or 0) != int(getattr(organization, "id", 0) or 0):
        raise PromoActivationError("promo_pending_scope_mismatch")

    completed_count = db.query(models.PromoRedemption.id).filter(
        models.PromoRedemption.promo_code_id == promo.id,
        models.PromoRedemption.status == "completed",
    ).count()
    if completed_count >= int(promo.max_total_redemptions):
        raise PromoActivationError("promo_redemption_limit_reached")
    target_group_id = int(getattr(school_group, "id", 0) or 0)
    if promo.one_redemption_per_organization and target_group_id:
        prior = db.query(models.PromoRedemption.id).filter(
            models.PromoRedemption.promo_code_id == promo.id,
            models.PromoRedemption.school_group_id == target_group_id,
        ).first()
        if prior:
            raise PromoActivationError("promo_already_redeemed_for_organization")


def _existing_owner_link(db: Session, account, school_group, *, lock: bool = False):
    query = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.school_group_id == school_group.id,
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    )
    link = query.with_for_update().one_or_none() if lock else query.one_or_none()
    if link is None:
        raise PromoActivationError(
            "promo_owner_relationship_required",
            "Only the organization owner can activate this promo.",
        )
    return link


def _validate_existing_workspace(db: Session, account, school_group, *, lock: bool = False):
    if str(school_group.workspace_classification or "") != WorkspaceClassification.CUSTOMER.value:
        raise PromoActivationError("promo_existing_workspace_not_aligned")
    if str(school_group.workspace_lifecycle_status or "") != WorkspaceLifecycleStatus.PROVISIONING.value:
        raise PromoActivationError("promo_existing_workspace_not_activation_required")
    link = _existing_owner_link(db, account, school_group, lock=lock)
    if db.query(models.TenantProvisioningLink.id).filter(
        models.TenantProvisioningLink.school_group_id == school_group.id
    ).first():
        raise PromoActivationError("promo_existing_commercial_source")
    if db.query(models.WorkspaceEntitlement.id).filter(
        models.WorkspaceEntitlement.school_group_id == school_group.id,
        models.WorkspaceEntitlement.status.in_(("pending", "active", "suspended")),
    ).first():
        raise PromoActivationError("promo_existing_workspace_entitlement")
    branches = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == school_group.id,
        operational_models.Branch.status.is_(True),
    ).all()
    if not branches:
        raise PromoActivationError("promo_existing_workspace_setup_incomplete")
    if not db.query(operational_models.AcademicYear.id).filter(
        operational_models.AcademicYear.school_group_id == school_group.id,
        operational_models.AcademicYear.is_active.is_(True),
    ).first():
        raise PromoActivationError("promo_existing_workspace_setup_incomplete")
    return link


def _validate_onboarding(db: Session, account, organization) -> None:
    if int(organization.owner_saas_account_id) != int(account.id):
        raise PromoActivationError("promo_organization_owner_mismatch")
    if service.get_onboarding_missing_requirements(db, organization):
        raise PromoActivationError(
            "promo_onboarding_incomplete",
            "Complete School Workspace Setup before applying a promo code.",
        )
    if str(organization.status or "").lower() != service.READY_FOR_CHECKOUT_STATUS:
        raise PromoActivationError(
            "promo_review_not_submitted",
            "Review and submit School Workspace Setup before applying a promo code.",
        )


def _context_branches(db: Session, session):
    if session.pending_organization_id:
        rows = db.query(models.PendingOrganizationBranch).filter(
            models.PendingOrganizationBranch.pending_organization_id == session.pending_organization_id,
            models.PendingOrganizationBranch.status.is_(True),
        ).order_by(models.PendingOrganizationBranch.sort_order, models.PendingOrganizationBranch.id).all()
        return tuple(rows), "pending"
    rows = db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == session.school_group_id,
        operational_models.Branch.status.is_(True),
    ).order_by(operational_models.Branch.id).all()
    return tuple(rows), "operational"


def _usage(db: Session, session, branches) -> tuple[int, int, int]:
    if session.pending_organization_id:
        organization = db.get(models.PendingOrganization, session.pending_organization_id)
        branch_count, staff, teachers = service.authoritative_capacity_counts(db, organization)
        return int(branch_count), int(staff), int(teachers)
    usage = commercial_authority_service.count_capacity_usage(db, session.school_group_id)
    return usage.branches, usage.staff_users, usage.teachers


def _selection_ids(db: Session, session, identity_kind: str) -> frozenset[int]:
    rows = db.query(models.PromoActivationBranchSelection).filter(
        models.PromoActivationBranchSelection.activation_session_id == session.id
    ).all()
    field = "pending_branch_id" if identity_kind == "pending" else "branch_id"
    return frozenset(int(getattr(row, field)) for row in rows if getattr(row, field))


def _replace_selections(db: Session, session, branches, selected_ids: set[int], identity_kind: str) -> None:
    db.query(models.PromoActivationBranchSelection).filter(
        models.PromoActivationBranchSelection.activation_session_id == session.id
    ).delete(synchronize_session=False)
    for branch in branches:
        branch_id = int(branch.id)
        if branch_id not in selected_ids:
            continue
        pending = identity_kind == "pending"
        db.add(models.PromoActivationBranchSelection(
            activation_session_id=session.id,
            pending_branch_id=branch_id if pending else None,
            branch_id=None if pending else branch_id,
            branch_identity_snapshot=str(
                getattr(branch, "branch_uuid", None) or branch_id
            )[:36],
            branch_name_snapshot=str(
                getattr(branch, "branch_name", None) or getattr(branch, "name", "")
            )[:160],
        ))
    db.flush()


def _allowed_branch_ids(db: Session, promo, branches, identity_kind: str) -> set[int]:
    all_ids = {int(row.id) for row in branches}
    restrictions = db.query(models.PromoCodeBranchRestriction).filter(
        models.PromoCodeBranchRestriction.promo_code_id == promo.id
    ).all()
    if not restrictions:
        return all_ids
    if identity_kind != "operational":
        raise PromoActivationError("promo_branch_scope_incompatible")
    return all_ids.intersection({int(row.branch_id_snapshot) for row in restrictions})


def get_activation_review(db: Session, activation_uuid: str, account) -> PromoActivationReview:
    session = db.query(models.PromoActivationSession).filter(
        models.PromoActivationSession.activation_uuid == str(activation_uuid or "").strip(),
        models.PromoActivationSession.saas_account_id == account.id,
    ).one_or_none()
    if session is None:
        raise PromoActivationError("promo_activation_not_found")
    if session.status == "activated":
        promo = db.get(models.PromoCode, session.promo_code_id)
        plan = db.get(models.SubscriptionPlan, promo.subscription_plan_id) if promo else None
        group = db.get(operational_models.SchoolGroup, session.school_group_id)
        return PromoActivationReview(session, promo, plan, None, group, (), frozenset(), "operational", 0, 0, 0, int(promo.max_branches), int(promo.max_system_users), int(promo.max_teachers), (), False, False)
    if session.status != "open" or (_utc(session.expires_at) and utc_now() >= _utc(session.expires_at)):
        raise PromoActivationError("promo_activation_expired", "This promo activation has expired. Start again to continue.")
    promo = db.get(models.PromoCode, session.promo_code_id)
    organization = db.get(models.PendingOrganization, session.pending_organization_id) if session.pending_organization_id else None
    group = db.get(operational_models.SchoolGroup, session.school_group_id) if session.school_group_id else None
    _validate_promo_definition(db, promo, account=account, organization=organization, school_group=group)
    if organization is not None:
        _validate_onboarding(db, account, organization)
    else:
        _validate_existing_workspace(db, account, group)
    branches, identity_kind = _context_branches(db, session)
    branch_count, staff, teachers = _usage(db, session, branches)
    allowed_ids = _allowed_branch_ids(db, promo, branches, identity_kind)
    selected = _selection_ids(db, session, identity_kind).intersection(allowed_ids)
    selection_required = len(allowed_ids) > int(promo.max_branches)
    if not selection_required and selected != allowed_ids:
        _replace_selections(db, session, branches, allowed_ids, identity_kind)
        selected = frozenset(allowed_ids)
    exceeded = tuple(
        dimension for dimension, current, allowed in (
            ("branches", len(selected) if selected else branch_count, int(promo.max_branches)),
            ("staff_users", staff, int(promo.max_system_users)),
            ("teachers", teachers, int(promo.max_teachers)),
        ) if current > allowed
    )
    if staff > int(promo.max_system_users):
        session.stage = "staff_reconciliation_required"
    elif teachers > int(promo.max_teachers):
        session.stage = "teacher_reconciliation_required"
    elif selection_required and len(selected) != int(promo.max_branches):
        session.stage = "branch_selection_required"
    else:
        session.stage = "review_required"
    session.observed_branch_count = branch_count
    session.observed_staff_users = staff
    session.observed_teachers = teachers
    db.flush()
    return PromoActivationReview(
        session=session,
        promo=promo,
        plan=db.get(models.SubscriptionPlan, promo.subscription_plan_id),
        organization=organization,
        school_group=group,
        branches=branches,
        selected_branch_ids=selected,
        branch_identity_kind=identity_kind,
        current_branches=branch_count,
        current_staff_users=staff,
        current_teachers=teachers,
        allowed_branches=int(promo.max_branches),
        allowed_staff_users=int(promo.max_system_users),
        allowed_teachers=int(promo.max_teachers),
        exceeded_dimensions=exceeded,
        selection_required=selection_required,
        ready_to_activate=not exceeded and (not selection_required or len(selected) == int(promo.max_branches)),
    )


def start_activation(
    db: Session,
    *,
    account,
    raw_code: str,
    pending_organization=None,
    school_group=None,
    operational_user=None,
    idempotency_key: str | None = None,
    request_correlation_id: str | None = None,
) -> PromoActivationReview:
    if not getattr(account, "email_verified_at", None) or str(getattr(account, "status", "")) != "active":
        raise PromoActivationError("promo_verified_account_required")
    if (pending_organization is None) == (school_group is None):
        raise PromoActivationError("promo_activation_context_invalid")
    if pending_organization is not None:
        _validate_onboarding(db, account, pending_organization)
    else:
        owner_link = _validate_existing_workspace(db, account, school_group)
        operational_user = operational_user or db.get(operational_models.User, owner_link.operational_user_id)
    promo = find_promo_by_code(db, raw_code)
    _validate_promo_definition(
        db, promo, account=account, organization=pending_organization, school_group=school_group
    )
    anchor_filter = (
        models.PromoActivationSession.pending_organization_id == pending_organization.id
        if pending_organization is not None
        else models.PromoActivationSession.school_group_id == school_group.id
    )
    existing = db.query(models.PromoActivationSession).filter(
        anchor_filter,
        models.PromoActivationSession.status == "open",
    ).one_or_none()
    if existing:
        if existing.promo_code_id != promo.id:
            existing.status = "cancelled"
            existing.stage = "cancelled"
            existing.cancelled_at = utc_now()
            db.flush()
        else:
            return get_activation_review(db, existing.activation_uuid, account)
    current = utc_now()
    expiry = min(_utc(promo.redemption_deadline), current + timedelta(hours=1))
    session = models.PromoActivationSession(
        promo_code_id=promo.id,
        promo_definition_version=promo.definition_version,
        pending_organization_id=getattr(pending_organization, "id", None),
        school_group_id=getattr(school_group, "id", None),
        saas_account_id=account.id,
        operational_user_id=getattr(operational_user, "id", None),
        context_type="onboarding" if pending_organization is not None else "existing_organization",
        idempotency_key=str(idempotency_key or uuid.uuid4())[:120],
        request_correlation_id=str(request_correlation_id or "")[:120] or None,
        masked_promo_reference=promo_code_service.masked_code(promo),
        expires_at=_db_time(expiry),
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError as exc:
        raise PromoActivationError("promo_activation_conflict", "A promo activation is already in progress.") from exc
    _event(
        db, event_type="activation_started", result="success",
        operation_key=f"{session.idempotency_key}:started", account=account,
        session=session, promo=promo, organization=pending_organization,
        school_group=school_group,
    )
    return get_activation_review(db, session.activation_uuid, account)


def select_branches(db: Session, *, activation_uuid: str, account, branch_ids) -> PromoActivationReview:
    review = get_activation_review(db, activation_uuid, account)
    allowed_ids = _allowed_branch_ids(db, review.promo, review.branches, review.branch_identity_kind)
    selected = {int(value) for value in branch_ids}
    if not selected.issubset(allowed_ids):
        raise PromoActivationError("promo_branch_selection_invalid", "Select only eligible organization branches.")
    required = min(len(allowed_ids), review.allowed_branches)
    if len(selected) != required:
        raise PromoActivationError(
            "promo_branch_selection_count_invalid",
            f"Select exactly {required} branch{'es' if required != 1 else ''} to continue.",
        )
    _replace_selections(db, review.session, review.branches, selected, review.branch_identity_kind)
    _event(
        db, event_type="branches_selected", result="success",
        operation_key=f"{review.session.idempotency_key}:branches:{_snapshot_hash({'ids': sorted(selected)})[:20]}",
        account=account, session=review.session, promo=review.promo,
        organization=review.organization, school_group=review.school_group,
        details={"selected_branch_count": len(selected)},
    )
    return get_activation_review(db, activation_uuid, account)


def _definition_snapshot(promo, plan) -> dict:
    return {
        "promo_uuid": str(promo.promo_uuid),
        "definition_version": int(promo.definition_version),
        "plan_id": int(plan.id),
        "plan_code": str(plan.plan_code),
        "plan_name": str(plan.plan_name),
        "benefit_type": str(promo.benefit_type),
        "max_branches": int(promo.max_branches),
        "max_system_users": int(promo.max_system_users),
        "max_teachers": int(promo.max_teachers),
        "scope_type": str(promo.scope_type),
        "fixed_access_expires_at": _utc(promo.fixed_access_expires_at).isoformat() if promo.fixed_access_expires_at else None,
        "access_duration_days": promo.access_duration_days,
        "grace_period_days": int(promo.grace_period_days),
    }


def _scope_snapshot(db: Session, promo) -> dict:
    restrictions = db.query(models.PromoCodeBranchRestriction).filter(
        models.PromoCodeBranchRestriction.promo_code_id == promo.id
    ).order_by(models.PromoCodeBranchRestriction.branch_id_snapshot).all()
    return {
        "scope_type": str(promo.scope_type),
        "school_group_id": promo.school_group_id,
        "pending_organization_id": promo.pending_organization_id,
        "account_email_restricted": bool(promo.intended_account_email_normalized),
        "email_domain_restricted": bool(promo.permitted_email_domain_normalized),
        "branch_restrictions": [
            {
                "branch_id": int(row.branch_id_snapshot),
                "branch_name": str(row.branch_name_snapshot or "")[:160],
            }
            for row in restrictions
        ],
    }


def _create_entitlement_values(db: Session, workspace_entitlement, plan, allowed_branches: int) -> None:
    from saas.customer_feature_policy import NORMAL_CUSTOMER_FEATURE_KEYS

    rows = db.query(models.PlanEntitlement, models.EntitlementDefinition).join(
        models.EntitlementDefinition,
        models.EntitlementDefinition.id == models.PlanEntitlement.entitlement_definition_id,
    ).filter(
        models.PlanEntitlement.subscription_plan_id == plan.id,
        models.EntitlementDefinition.active.is_(True),
    ).all()
    seen = set()
    for plan_value, definition in rows:
        if definition.key in seen:
            raise PromoActivationError("promo_plan_entitlement_ambiguous")
        seen.add(definition.key)
        is_customer_baseline = definition.key in NORMAL_CUSTOMER_FEATURE_KEYS
        if not is_customer_baseline and str(plan_value.status or "") not in {"active", "derived"}:
            continue
        status = "active"
        value = (
            str(allowed_branches)
            if definition.key == "quota.active_branches"
            else "true"
            if is_customer_baseline
            else plan_value.value
        )
        db.add(models.WorkspaceEntitlementValue(
            workspace_entitlement_id=workspace_entitlement.id,
            entitlement_definition_id=definition.id,
            value=value,
            status=status,
        ))


def activate_promo(
    db: Session,
    *,
    activation_uuid: str,
    account,
    idempotency_key: str,
) -> ActivatedPromo:
    session = db.query(models.PromoActivationSession).filter(
        models.PromoActivationSession.activation_uuid == str(activation_uuid or "").strip(),
        models.PromoActivationSession.saas_account_id == account.id,
    ).with_for_update().one_or_none()
    if session is None:
        raise PromoActivationError("promo_activation_not_found")
    existing = db.query(models.PromoRedemption).filter(
        models.PromoRedemption.activation_session_id == session.id
    ).one_or_none()
    if existing:
        grant = db.query(models.PromoGrant).filter_by(promo_redemption_id=existing.id).one()
        entitlement = db.query(models.WorkspaceEntitlement).filter_by(promo_grant_id=grant.id).one()
        link = db.query(models.TenantProvisioningLink).filter_by(promo_grant_id=grant.id).one()
        group = db.get(operational_models.SchoolGroup, grant.school_group_id)
        return ActivatedPromo(session, existing, grant, entitlement, link, group)
    if session.status != "open" or _utc(session.expires_at) <= utc_now():
        raise PromoActivationError("promo_activation_expired", "This promo activation has expired. Start again to continue.")
    promo = db.query(models.PromoCode).filter(models.PromoCode.id == session.promo_code_id).with_for_update().one()
    organization = (
        db.query(models.PendingOrganization).filter(
            models.PendingOrganization.id == session.pending_organization_id
        ).with_for_update().one()
        if session.pending_organization_id else None
    )
    group = (
        db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id == session.school_group_id
        ).with_for_update().one()
        if session.school_group_id else None
    )
    _validate_promo_definition(db, promo, account=account, organization=organization, school_group=group)
    if organization is not None:
        _validate_onboarding(db, account, organization)
    else:
        owner_link = _validate_existing_workspace(db, account, group, lock=True)
        session.operational_user_id = session.operational_user_id or owner_link.operational_user_id
    review = get_activation_review(db, session.activation_uuid, account)
    if not review.ready_to_activate:
        raise PromoActivationError(
            "promo_capacity_reconciliation_required",
            "Review the current organization capacity before activating this promo.",
        )
    session.stage = "activation_processing"
    db.flush()

    pending_selection_rows = tuple(
        db.query(models.PromoActivationBranchSelection).filter_by(
            activation_session_id=session.id
        ).all()
    )
    if organization is not None:
        organization.workspace_intent = WorkspaceIntent.CUSTOMER.value
        workspace = provisioning_service.create_workspace_records(db, organization)
        group = workspace.school_group
        owner_user = workspace.owner_user
        primary_branch = workspace.primary_branch
        academic_year = workspace.academic_year
        session.school_group_id = group.id
        session.operational_user_id = owner_user.id
        pending_by_uuid = {
            str(row.branch_uuid): row for row in review.branches
        }
        operational_by_name = {row.name: row for row in workspace.branches}
        selected_branch_ids = set()
        selected_pending_ids = {int(row.pending_branch_id) for row in pending_selection_rows}
        for pending in review.branches:
            if int(pending.id) in selected_pending_ids:
                branch = operational_by_name.get(pending.branch_name)
                if branch is None or str(pending.branch_uuid) not in pending_by_uuid:
                    raise PromoActivationError("promo_provisioned_branch_mapping_failed")
                selected_branch_ids.add(int(branch.id))
        all_branches = tuple(workspace.branches)
    else:
        owner_user = db.get(operational_models.User, session.operational_user_id)
        all_branches = tuple(
            db.query(operational_models.Branch).filter(
                operational_models.Branch.school_group_id == group.id,
            ).order_by(operational_models.Branch.id.asc()).all()
        )
        primary_branch = next((row for row in all_branches if row.id == getattr(owner_user, "branch_id", None)), all_branches[0])
        academic_year = db.query(operational_models.AcademicYear).filter(
            operational_models.AcademicYear.school_group_id == group.id,
            operational_models.AcademicYear.is_active.is_(True),
        ).order_by(operational_models.AcademicYear.id).first()
        selected_branch_ids = set(review.selected_branch_ids)

    if len(selected_branch_ids) > int(promo.max_branches) or not selected_branch_ids:
        raise PromoActivationError("promo_branch_selection_invalid")
    source_count = db.query(models.TenantProvisioningLink.id).filter(
        models.TenantProvisioningLink.school_group_id == group.id
    ).count()
    if source_count:
        raise PromoActivationError("promo_existing_commercial_source")

    effective_from = utc_now()
    effective_to = (
        _utc(promo.fixed_access_expires_at)
        if promo.fixed_access_expires_at
        else effective_from + timedelta(days=int(promo.access_duration_days))
    )
    plan = db.get(models.SubscriptionPlan, promo.subscription_plan_id)
    definition = _definition_snapshot(promo, plan)
    scope = _scope_snapshot(db, promo)
    snapshot = {"definition": definition, "scope": scope}
    snapshot_hash = _snapshot_hash(snapshot)
    redemption = models.PromoRedemption(
        activation_session_id=session.id,
        promo_code_id=promo.id,
        promo_definition_version=promo.definition_version,
        school_group_id=group.id,
        pending_organization_id=getattr(organization, "id", None),
        redeeming_saas_account_id=account.id,
        redeeming_operational_user_id=getattr(owner_user, "id", None),
        redeemed_at=_db_time(effective_from),
        idempotency_key=str(idempotency_key)[:120],
        request_correlation_id=session.request_correlation_id,
        masked_promo_reference=session.masked_promo_reference,
        plan_id=plan.id,
        plan_code_snapshot=plan.plan_code,
        plan_name_snapshot=plan.plan_name,
        allowed_branches=promo.max_branches,
        allowed_staff_users=promo.max_system_users,
        allowed_teachers=promo.max_teachers,
        effective_from=_db_time(effective_from),
        effective_to=_db_time(effective_to),
        grace_period_days=promo.grace_period_days,
        scope_type_snapshot=promo.scope_type,
        scope_snapshot_json=_canonical_json(scope),
        definition_snapshot_json=_canonical_json(definition),
        immutable_snapshot_hash=snapshot_hash,
    )
    db.add(redemption)
    db.flush()
    grant = models.PromoGrant(
        promo_redemption_id=redemption.id,
        school_group_id=group.id,
        plan_id=plan.id,
        plan_code_snapshot=plan.plan_code,
        plan_name_snapshot=plan.plan_name,
        allowed_branches=promo.max_branches,
        allowed_staff_users=promo.max_system_users,
        allowed_teachers=promo.max_teachers,
        effective_from=_db_time(effective_from),
        effective_to=_db_time(effective_to),
        grace_period_days=promo.grace_period_days,
        definition_snapshot_json=_canonical_json(definition),
        capacity_snapshot_json=_canonical_json({
            "branches": review.current_branches,
            "staff_users": review.current_staff_users,
            "teachers": review.current_teachers,
            "selected_branch_count": len(selected_branch_ids),
        }),
        scope_snapshot_json=_canonical_json(scope),
        immutable_snapshot_hash=snapshot_hash,
        activated_at=_db_time(effective_from),
    )
    db.add(grant)
    db.flush()
    entitlement = models.WorkspaceEntitlement(
        school_group_id=group.id,
        entitlement_type="promo",
        status="active",
        source="promo",
        promo_grant_id=grant.id,
        effective_from=_db_time(effective_from),
        effective_to=_db_time(effective_to),
    )
    db.add(entitlement)
    db.flush()
    _create_entitlement_values(db, entitlement, plan, int(promo.max_branches))
    for branch in all_branches:
        selected = int(branch.id) in selected_branch_ids
        db.add(models.BranchEntitlement(
            school_group_id=group.id,
            branch_id=branch.id,
            workspace_entitlement_id=entitlement.id,
            entitlement_mode=(BranchEntitlementMode.ACTIVE.value if selected else BranchEntitlementMode.INACTIVE.value),
            reason_code="promo_grant_selected" if selected else "promo_grant_not_selected",
        ))
        if selected:
            db.add(models.PromoGrantBranchAssignment(
                promo_grant_id=grant.id,
                school_group_id=group.id,
                branch_id=branch.id,
                branch_identity_snapshot=str(branch.id),
                branch_name_snapshot=str(branch.name)[:160],
                assigned_by_saas_account_id=account.id,
                assigned_at=_db_time(effective_from),
            ))
    link = provisioning_service.ensure_tenant_provisioning_link(
        db,
        organization=organization,
        school_group=group,
        owner_user=owner_user,
        primary_branch=primary_branch,
        academic_year=academic_year,
        promo_grant=grant,
    )
    group.workspace_classification = WorkspaceClassification.CUSTOMER.value
    group.workspace_lifecycle_status = WorkspaceLifecycleStatus.ACTIVE.value
    group.status = True
    if organization is not None:
        organization.billing_status = "tenant_active"
        organization.payment_status = "not_required"
        organization.status = "activated"
        account.onboarding_status = "tenant_active"
        service.log_pending_event(
            db, organization=organization, account=account,
            event_type="promo_workspace_activated",
            details={"school_group_id": group.id},
        )
    session.status = "activated"
    session.stage = "activated"
    session.activated_at = utc_now()
    db.flush()

    authority = commercial_authority_service.resolve_commercial_authority(db, group.id)
    if not authority.resolved or not authority.access_allowed or authority.source != "promo_grant":
        from saas import commercial_access_service, commercial_state_service, workspace_entitlement_service
        access_check = commercial_access_service.resolve_workspace_access(db, group.id)
        state_check = commercial_state_service.resolve_commercial_state(db, group.id)
        entitlement_check = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
        logger.warning(
            "Promo authority post-validation failed school_group_id=%s resolved=%s access_allowed=%s source=%s reason=%s access_reason=%s state_reason=%s entitlement_reason=%s",
            group.id,
            authority.resolved,
            authority.access_allowed,
            authority.source,
            authority.reason_code,
            access_check.reason_code,
            state_check.reason_code,
            entitlement_check.reason_code,
        )
        raise PromoActivationError("promo_commercial_authority_validation_failed")
    _event(
        db, event_type="activation_completed", result="success",
        operation_key=f"{session.idempotency_key}:completed", account=account,
        session=session, promo=promo, redemption=redemption, grant=grant,
        organization=organization, school_group=group,
        details={"plan_code": plan.plan_code, "selected_branch_count": len(selected_branch_ids)},
    )
    return ActivatedPromo(session, redemption, grant, entitlement, link, group)


def record_failed_activation(
    db: Session,
    *,
    activation_uuid: str,
    account,
    failure_code: str,
    operation_key: str,
):
    session = db.query(models.PromoActivationSession).filter(
        models.PromoActivationSession.activation_uuid == str(activation_uuid or "").strip(),
        models.PromoActivationSession.saas_account_id == getattr(account, "id", None),
    ).one_or_none()
    if session is None:
        return None
    promo = db.get(models.PromoCode, session.promo_code_id)
    organization = db.get(models.PendingOrganization, session.pending_organization_id) if session.pending_organization_id else None
    group = db.get(operational_models.SchoolGroup, session.school_group_id) if session.school_group_id else None
    session.last_failure_code = str(failure_code or "promo_activation_failed")[:80]
    return _event(
        db,
        event_type="activation_failed",
        result="blocked",
        operation_key=str(operation_key or uuid.uuid4()),
        account=account,
        session=session,
        promo=promo,
        organization=organization,
        school_group=group,
        failure_code=session.last_failure_code,
    )
