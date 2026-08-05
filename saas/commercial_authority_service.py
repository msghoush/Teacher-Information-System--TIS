from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import unicodedata

from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import (
    branch_pricing_quote_service,
    commercial_access_service,
    commercial_state_service,
    entitlement_service,
    models,
    workspace_entitlement_service,
)
from workspace_classification import WorkspaceClassification


PAID_SUBSCRIPTION = "paid_subscription"
DEMO = "demo"
INTERNAL_SANDBOX = "internal_sandbox"
PROMO_GRANT = "promo_grant"
NO_COMMERCIAL_ACCESS = "no_commercial_access"

ACTIVE = "active"
ACTIVATION_REQUIRED = "activation_required"
PAYMENT_PROCESSING = "payment_processing"
PAST_DUE = "past_due"
ENDING_AT_PERIOD_END = "ending_at_period_end"
EXPIRED = "expired"
SUSPENDED = "suspended"
RESTRICTED = "restricted"
INTERNAL = "internal"
NO_ACCESS = "no_access"

DIMENSIONS = ("branches", "staff_users", "teachers")


@dataclass(frozen=True)
class CapacityVector:
    branches: int = 0
    staff_users: int = 0
    teachers: int = 0

    def value(self, dimension: str) -> int:
        if dimension not in DIMENSIONS:
            raise ValueError("Unknown capacity dimension.")
        return int(getattr(self, dimension))


@dataclass(frozen=True)
class CapacityLimits:
    branches: int | None = None
    staff_users: int | None = None
    teachers: int | None = None
    unmetered: bool = False

    def value(self, dimension: str) -> int | None:
        if dimension not in DIMENSIONS:
            raise ValueError("Unknown capacity dimension.")
        value = getattr(self, dimension)
        return int(value) if value is not None else None


@dataclass(frozen=True)
class CapacityViolation:
    dimension: str
    allowed: int | None
    current: int
    code: str


@dataclass(frozen=True)
class CommercialAuthorityResolution:
    school_group_id: int | None
    classification: str
    source: str
    commercial_status: str
    access_allowed: bool
    resolution_status: str
    reason_code: str
    plan_id: int | None = None
    plan_code: str = ""
    plan_name: str = ""
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    limits: CapacityLimits = field(default_factory=CapacityLimits)
    usage: CapacityVector = field(default_factory=CapacityVector)
    remaining: CapacityVector = field(default_factory=CapacityVector)
    violations: tuple[CapacityViolation, ...] = ()
    minimum_eligible_plan_code: str = ""
    minimum_eligible_plan_name: str = ""
    custom_required: bool = False
    recovery_action: str = "contact_support"
    message_key: str = "commercial_access_unavailable"

    @property
    def resolved(self) -> bool:
        return self.resolution_status == "resolved"


@dataclass(frozen=True)
class CapacityDimensionDecision:
    dimension: str
    allowed: int | None
    current: int
    proposed_addition: int
    requested_result: int
    allowed_action: bool
    code: str


@dataclass(frozen=True)
class CapacityChangeDecision:
    school_group_id: int | None
    source: str
    plan: str
    allowed_action: bool
    code: str
    dimension: str
    allowed: int | None
    current: int
    proposed_addition: int
    requested_result: int
    recovery_action: str
    message: str
    dimensions: tuple[CapacityDimensionDecision, ...]
    authority: CommercialAuthorityResolution


class CapacityAuthorityError(PermissionError):
    def __init__(self, decision: CapacityChangeDecision):
        super().__init__(decision.message)
        self.decision = decision
        self.code = decision.code


def _clean(value) -> str:
    return str(value or "").strip()


def _normalized_teacher_identity(value) -> str:
    cleaned = unicodedata.normalize("NFKC", _clean(value)).casefold()
    return "".join(cleaned.split())


def count_active_branches(
    db: Session,
    school_group_id: int,
    *,
    active_branch_ids: set[int] | None = None,
) -> int:
    if active_branch_ids is not None:
        return len({int(branch_id) for branch_id in active_branch_ids})
    return db.query(operational_models.Branch).filter(
        operational_models.Branch.school_group_id == int(school_group_id),
        operational_models.Branch.status.is_(True),
    ).count()


def count_active_staff_users(db: Session, school_group_id: int) -> int:
    rows = db.query(operational_models.User.id).filter(
        operational_models.User.school_group_id == int(school_group_id),
        operational_models.User.user_type == auth.USER_TYPE_TENANT,
        operational_models.User.is_active.is_(True),
    ).distinct().all()
    return len({int(user_id) for (user_id,) in rows})


def count_active_teachers(
    db: Session,
    school_group_id: int,
    *,
    active_branch_ids: set[int] | None = None,
    active_academic_year_ids: set[int] | None = None,
) -> int:
    identities, legacy_rows = active_teacher_identities(
        db,
        school_group_id,
        active_branch_ids=active_branch_ids,
        active_academic_year_ids=active_academic_year_ids,
    )
    return len(identities) + len(legacy_rows)


def active_teacher_identities(
    db: Session,
    school_group_id: int,
    *,
    active_branch_ids: set[int] | None = None,
    active_academic_year_ids: set[int] | None = None,
) -> tuple[frozenset[str], frozenset[int]]:
    query = db.query(
        operational_models.Teacher.id,
        operational_models.Teacher.teacher_id,
    ).join(
        operational_models.Branch,
        operational_models.Branch.id == operational_models.Teacher.branch_id,
    ).join(
        operational_models.AcademicYear,
        operational_models.AcademicYear.id
        == operational_models.Teacher.academic_year_id,
    ).filter(
        operational_models.Branch.school_group_id == int(school_group_id),
        operational_models.AcademicYear.school_group_id == int(school_group_id),
    )
    if active_branch_ids is None:
        query = query.filter(operational_models.Branch.status.is_(True))
    else:
        branch_ids = sorted({int(branch_id) for branch_id in active_branch_ids})
        if not branch_ids:
            return frozenset(), frozenset()
        query = query.filter(operational_models.Branch.id.in_(branch_ids))
    if active_academic_year_ids is None:
        query = query.filter(operational_models.AcademicYear.is_active.is_(True))
    else:
        year_ids = sorted({int(year_id) for year_id in active_academic_year_ids})
        if not year_ids:
            return frozenset(), frozenset()
        query = query.filter(operational_models.AcademicYear.id.in_(year_ids))

    identities: set[str] = set()
    legacy_rows: set[int] = set()
    for row_id, teacher_id in query.all():
        identity = _normalized_teacher_identity(teacher_id)
        if identity:
            identities.add(identity)
        else:
            # Missing legacy identities are intentionally never merged.
            legacy_rows.add(int(row_id))
    return frozenset(identities), frozenset(legacy_rows)


def normalized_teacher_identity(value) -> str:
    return _normalized_teacher_identity(value)


def count_capacity_usage(
    db: Session,
    school_group_id: int,
    *,
    active_branch_ids: set[int] | None = None,
    active_academic_year_ids: set[int] | None = None,
) -> CapacityVector:
    return CapacityVector(
        branches=count_active_branches(
            db, school_group_id, active_branch_ids=active_branch_ids
        ),
        staff_users=count_active_staff_users(db, school_group_id),
        teachers=count_active_teachers(
            db,
            school_group_id,
            active_branch_ids=active_branch_ids,
            active_academic_year_ids=active_academic_year_ids,
        ),
    )


def lock_school_groups(db: Session, school_group_ids) -> tuple[object, ...]:
    ids = sorted({int(group_id) for group_id in school_group_ids if group_id})
    if not ids:
        return ()
    rows = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id.in_(ids)
    ).order_by(operational_models.SchoolGroup.id.asc()).with_for_update().all()
    if [int(row.id) for row in rows] != ids:
        raise CapacityAuthorityError(
            _missing_group_decision(ids[0] if ids else None)
        )
    return tuple(rows)


def _remaining(limits: CapacityLimits, usage: CapacityVector) -> CapacityVector:
    values = {}
    for dimension in DIMENSIONS:
        allowed = limits.value(dimension)
        values[dimension] = (
            max(allowed - usage.value(dimension), 0)
            if allowed is not None
            else 0
        )
    return CapacityVector(**values)


def _capacity_violations(
    limits: CapacityLimits, usage: CapacityVector
) -> tuple[CapacityViolation, ...]:
    if limits.unmetered:
        return ()
    violations = []
    for dimension in DIMENSIONS:
        allowed = limits.value(dimension)
        current = usage.value(dimension)
        if allowed is None:
            violations.append(
                CapacityViolation(
                    dimension=dimension,
                    allowed=None,
                    current=current,
                    code="commercial_authority_unavailable",
                )
            )
        elif current > allowed:
            violations.append(
                CapacityViolation(
                    dimension=dimension,
                    allowed=allowed,
                    current=current,
                    code="existing_capacity_exceeded",
                )
            )
    return tuple(violations)


def _minimum_plan(db: Session, usage: CapacityVector):
    try:
        return branch_pricing_quote_service.resolve_minimum_eligible_plan(
            db,
            active_branch_count=usage.branches,
            active_system_user_count=usage.staff_users,
            active_teacher_count=usage.teachers,
        ), ""
    except ValueError:
        return None, "plan_capacity_catalog_unavailable"


def _canonical_status(group, access, commercial) -> str:
    classification = _clean(group.workspace_classification)
    if classification == WorkspaceClassification.INTERNAL_SANDBOX.value:
        return INTERNAL if access.allowed_access else RESTRICTED
    state = _clean(getattr(access, "commercial_state", "")).lower()
    if access.allowed_access:
        if state in {commercial_access_service.CANCELED} or bool(
            _clean(getattr(access, "subscription_status", "")).lower()
            in {"canceled", "cancelled"}
        ):
            return ENDING_AT_PERIOD_END
        return ACTIVE
    if state == commercial_access_service.PAYMENT_PROCESSING:
        return PAYMENT_PROCESSING
    if state == commercial_access_service.PAST_DUE:
        return PAST_DUE
    if state == commercial_access_service.EXPIRED:
        return EXPIRED
    if state in {
        commercial_access_service.SUSPENDED,
        commercial_access_service.ARCHIVED,
    }:
        return SUSPENDED
    if _clean(getattr(commercial, "commercial_state", "")) == "provisioning":
        return ACTIVATION_REQUIRED
    return RESTRICTED if classification else NO_ACCESS


def resolve_commercial_authority(
    db: Session,
    school_group_id: int,
    *,
    usage: CapacityVector | None = None,
) -> CommercialAuthorityResolution:
    try:
        group_id = int(school_group_id)
    except (TypeError, ValueError):
        group_id = 0
    group = db.get(operational_models.SchoolGroup, group_id) if group_id else None
    if group is None:
        return CommercialAuthorityResolution(
            school_group_id=group_id or None,
            classification="",
            source=NO_COMMERCIAL_ACCESS,
            commercial_status=NO_ACCESS,
            access_allowed=False,
            resolution_status="manual_review",
            reason_code="missing_school_group",
            recovery_action="contact_support",
            message_key="commercial_access_unavailable",
        )

    usage = usage or count_capacity_usage(db, group.id)
    classification = _clean(group.workspace_classification)
    commercial = commercial_state_service.resolve_commercial_state(db, group.id)
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    workspace_entitlement = workspace_entitlement_service.resolve_workspace_entitlement(
        db, group.id
    )
    source = NO_COMMERCIAL_ACCESS
    limits = CapacityLimits()
    plan_id = None
    plan_code = ""
    plan_name = ""
    effective_from = getattr(workspace_entitlement, "effective_from", None)
    effective_to = getattr(workspace_entitlement, "effective_to", None)
    reason_code = _clean(getattr(access, "reason_code", "")) or _clean(
        getattr(commercial, "reason_code", "")
    )
    resolved = bool(commercial.resolved and workspace_entitlement.resolved)

    if classification == WorkspaceClassification.INTERNAL_SANDBOX.value:
        source = INTERNAL_SANDBOX
        limits = CapacityLimits(unmetered=True)
    elif classification == WorkspaceClassification.CUSTOMER_DEMO.value:
        source = DEMO
        limits = CapacityLimits(unmetered=True)
    elif classification == WorkspaceClassification.CUSTOMER_PAID.value:
        source = PAID_SUBSCRIPTION
        paid = entitlement_service.resolve_entitlements(db, group.id)
        resolved = bool(resolved and paid.resolved)
        reason_code = paid.reason_code if not paid.resolved else reason_code
        plan_id = paid.plan_id
        plan_code = paid.plan_code
        plan_name = paid.plan_name
        payment_subscription = (
            db.get(models.PaymentSubscription, paid.subscription_id)
            if paid.subscription_id
            else None
        )
        effective_to = (
            getattr(payment_subscription, "current_period_end", None)
            or paid.next_billed_at
            or effective_to
        )
        plan = db.get(models.SubscriptionPlan, paid.plan_id) if paid.plan_id else None
        if plan is not None and paid.paid_branch_quantity is not None:
            raw_limits = (
                getattr(plan, "max_branches", None),
                getattr(plan, "max_system_users", None),
                getattr(plan, "max_teachers", None),
            )
            if all(value is not None and int(value) > 0 for value in raw_limits):
                limits = CapacityLimits(
                    branches=min(int(paid.paid_branch_quantity), int(plan.max_branches)),
                    staff_users=int(plan.max_system_users),
                    teachers=int(plan.max_teachers),
                )
            else:
                resolved = False
                reason_code = "invalid_plan_capacity"
        else:
            resolved = False
            reason_code = reason_code or "missing_paid_capacity"
    elif classification == WorkspaceClassification.CUSTOMER.value:
        from saas import promo_grant_service

        promo = promo_grant_service.resolve_promo_grant(db, group.id)
        resolved = bool(resolved and promo.resolved and promo.active)
        reason_code = promo.reason_code if not promo.active else reason_code
        source = PROMO_GRANT
        plan_id = promo.plan_id
        plan_code = promo.plan_code
        plan_name = promo.plan_name
        effective_from = promo.effective_from
        effective_to = promo.effective_to
        limits = CapacityLimits(
            branches=promo.allowed_branches,
            staff_users=promo.allowed_staff_users,
            teachers=promo.allowed_teachers,
        )
        usage = count_capacity_usage(db, group.id, active_branch_ids=set(promo.active_branch_ids))
    else:
        resolved = False
        reason_code = "unsupported_workspace_classification"

    minimum_plan, minimum_error = _minimum_plan(db, usage)
    if minimum_error and source in {PAID_SUBSCRIPTION, PROMO_GRANT}:
        resolved = False
        reason_code = minimum_error
    minimum_code = _clean(getattr(minimum_plan, "plan_code", ""))
    minimum_name = _clean(getattr(minimum_plan, "plan_name", ""))
    status = _canonical_status(group, access, commercial)
    access_allowed = bool(access.allowed_access and resolved)
    if not access_allowed and status in {ACTIVE, INTERNAL}:
        status = RESTRICTED

    violations = _capacity_violations(limits, usage)
    recovery_action = _clean(getattr(access, "recommended_action", ""))
    if source == PAID_SUBSCRIPTION and violations:
        recovery_action = "upgrade_subscription"
    elif source == PROMO_GRANT and violations:
        recovery_action = "contact_support"
    elif source == NO_COMMERCIAL_ACCESS:
        recovery_action = "contact_support"
    elif not access_allowed and not recovery_action:
        recovery_action = "contact_support"

    return CommercialAuthorityResolution(
        school_group_id=group.id,
        classification=classification,
        source=source,
        commercial_status=status,
        access_allowed=access_allowed,
        resolution_status="resolved" if resolved else "manual_review",
        reason_code=reason_code or ("resolved" if resolved else "commercial_authority_unavailable"),
        plan_id=plan_id,
        plan_code=plan_code,
        plan_name=plan_name,
        effective_from=effective_from,
        effective_to=effective_to,
        limits=limits,
        usage=usage,
        remaining=_remaining(limits, usage),
        violations=violations,
        minimum_eligible_plan_code=minimum_code,
        minimum_eligible_plan_name=minimum_name,
        custom_required=minimum_plan is None and not minimum_error,
        recovery_action=recovery_action or "contact_support",
        message_key=_clean(getattr(access, "customer_message_key", ""))
        or ("commercial_access_active" if access_allowed else "commercial_access_unavailable"),
    )


def _safe_message(dimension: str, allowed: int | None, code: str) -> str:
    labels = {
        "branches": "active branches",
        "staff_users": "active staff users",
        "teachers": "active teachers",
    }
    if code == "commercial_access_inactive":
        return "Commercial access is not currently available for this workspace."
    if code == "commercial_authority_unavailable" or allowed is None:
        return "Capacity information is temporarily unavailable. Please contact the TIS team."
    label = labels[dimension]
    if allowed == 1:
        label = {
            "branches": "active branch",
            "staff_users": "active staff user",
            "teachers": "active teacher",
        }[dimension]
    return f"Your current access allows {allowed} {label}."


def _missing_group_decision(school_group_id: int | None) -> CapacityChangeDecision:
    authority = CommercialAuthorityResolution(
        school_group_id=school_group_id,
        classification="",
        source=NO_COMMERCIAL_ACCESS,
        commercial_status=NO_ACCESS,
        access_allowed=False,
        resolution_status="manual_review",
        reason_code="missing_school_group",
    )
    dimension = "branches"
    detail = CapacityDimensionDecision(
        dimension=dimension,
        allowed=None,
        current=0,
        proposed_addition=0,
        requested_result=0,
        allowed_action=False,
        code="commercial_authority_unavailable",
    )
    return CapacityChangeDecision(
        school_group_id=school_group_id,
        source=NO_COMMERCIAL_ACCESS,
        plan="",
        allowed_action=False,
        code=detail.code,
        dimension=dimension,
        allowed=None,
        current=0,
        proposed_addition=0,
        requested_result=0,
        recovery_action="contact_support",
        message=_safe_message(dimension, None, detail.code),
        dimensions=(detail,),
        authority=authority,
    )


def evaluate_capacity_change(
    db: Session,
    school_group_id: int,
    *,
    branch_delta: int = 0,
    staff_user_delta: int = 0,
    teacher_delta: int = 0,
    proposed_branches: int | None = None,
    proposed_staff_users: int | None = None,
    proposed_teachers: int | None = None,
    usage: CapacityVector | None = None,
) -> CapacityChangeDecision:
    authority = resolve_commercial_authority(db, school_group_id, usage=usage)
    deltas = {
        "branches": int(branch_delta or 0),
        "staff_users": int(staff_user_delta or 0),
        "teachers": int(teacher_delta or 0),
    }
    absolutes = {
        "branches": proposed_branches,
        "staff_users": proposed_staff_users,
        "teachers": proposed_teachers,
    }
    details = []
    for dimension in DIMENSIONS:
        current = authority.usage.value(dimension)
        requested = (
            int(absolutes[dimension])
            if absolutes[dimension] is not None
            else current + deltas[dimension]
        )
        if requested < 0:
            raise ValueError("Proposed capacity usage cannot be negative.")
        addition = requested - current
        allowed = authority.limits.value(dimension)
        code = "allowed"
        allowed_action = True
        if addition > 0 and not authority.access_allowed:
            code = (
                "commercial_authority_unavailable"
                if not authority.resolved
                else "commercial_access_inactive"
            )
            allowed_action = False
        elif addition > 0 and not authority.limits.unmetered:
            if allowed is None:
                code = "commercial_authority_unavailable"
                allowed_action = False
            elif current > allowed and requested > current:
                code = "capacity_limit_reached"
                allowed_action = False
            elif current <= allowed and requested > allowed:
                code = "capacity_limit_reached"
                allowed_action = False
        details.append(
            CapacityDimensionDecision(
                dimension=dimension,
                allowed=allowed,
                current=current,
                proposed_addition=addition,
                requested_result=requested,
                allowed_action=allowed_action,
                code=code,
            )
        )

    failed = next((detail for detail in details if not detail.allowed_action), None)
    primary = failed or next(
        (detail for detail in details if detail.proposed_addition != 0),
        details[0],
    )
    recovery = authority.recovery_action
    if failed and authority.source == PAID_SUBSCRIPTION:
        recovery = "upgrade_subscription"
    return CapacityChangeDecision(
        school_group_id=authority.school_group_id,
        source=authority.source,
        plan=authority.plan_code,
        allowed_action=failed is None,
        code=primary.code,
        dimension=primary.dimension,
        allowed=primary.allowed,
        current=primary.current,
        proposed_addition=primary.proposed_addition,
        requested_result=primary.requested_result,
        recovery_action=recovery,
        message=(
            ""
            if failed is None
            else _safe_message(primary.dimension, primary.allowed, primary.code)
        ),
        dimensions=tuple(details),
        authority=authority,
    )


def require_capacity_change(
    db: Session,
    school_group_id: int,
    *,
    lock: bool = True,
    **changes,
) -> CapacityChangeDecision:
    if lock:
        lock_school_groups(db, (school_group_id,))
    decision = evaluate_capacity_change(db, school_group_id, **changes)
    if not decision.allowed_action:
        raise CapacityAuthorityError(decision)
    return decision
