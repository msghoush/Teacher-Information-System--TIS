from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import (
    commercial_authority_service,
    existing_workspace_conversion_audit_service,
    models,
    provisioning_service,
    service,
)
from workspace_classification import AccountPurpose, WorkspaceClassification, WorkspaceLifecycleStatus


OPEN_STATUSES = (
    "awaiting_owner_registration",
    "awaiting_owner_verification",
    "awaiting_owner_alignment",
    "awaiting_setup",
    "ready",
    "in_progress",
)
ALLOWED_PREPARATION_WARNINGS = {
    "owner_saas_account_absent",
    "owner_operational_user_missing",
    "owner_account_link_missing",
}
ALLOWED_PREPARATION_BLOCKERS = {"owner_saas_account_unverified"}
REQUIRED_SETUP_FIELDS = ("legal_name", "timezone", "educational_program")
EDUCATIONAL_PROGRAMS = ("NATIONAL", "INTERNATIONAL", "BOTH")


class ExistingWorkspaceConversionError(ValueError):
    def __init__(self, reason_code: str, message: str = "Existing workspace conversion requires review."):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ConversionResult:
    status: str
    reason_code: str
    operation_uuid: str
    school_group_id: int
    stage: str
    changed: bool
    audit_snapshot_hash: str = ""
    current_snapshot_hash: str = ""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json(value) -> str:
    return _canonical(value)


def _load_json(value, fallback):
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def canonical_parameter_hash(
    *,
    school_group_id: int,
    workspace_uuid: str,
    expected_name: str,
    owner_email: str,
    audit_snapshot_hash: str,
    operation_uuid: str,
    idempotency_key: str,
) -> str:
    normalized_email = auth.normalize_email(owner_email)
    try:
        normalized_operation_uuid = str(uuid.UUID(str(operation_uuid).strip()))
        normalized_workspace_uuid = str(uuid.UUID(str(workspace_uuid).strip()))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExistingWorkspaceConversionError("invalid_uuid", "Supply valid workspace and operation UUIDs.") from exc
    snapshot_hash = str(audit_snapshot_hash or "").strip().lower()
    if len(snapshot_hash) != 64 or any(char not in "0123456789abcdef" for char in snapshot_hash):
        raise ExistingWorkspaceConversionError("invalid_audit_snapshot_hash", "Supply the exact M4A snapshot hash.")
    key = str(idempotency_key or "").strip()
    if not normalized_email or not auth.is_valid_email(normalized_email):
        raise ExistingWorkspaceConversionError("invalid_owner_email", "Supply a valid intended owner email.")
    if not key or len(key) > 120:
        raise ExistingWorkspaceConversionError("invalid_idempotency_key", "Supply a valid idempotency key.")
    return _hash({
        "school_group_id": int(school_group_id),
        "workspace_uuid": normalized_workspace_uuid,
        "expected_name": str(expected_name or "").strip(),
        "owner_email_normalized": normalized_email,
        "audit_snapshot_hash": snapshot_hash,
        "operation_uuid": normalized_operation_uuid,
        "idempotency_key": key,
    })


def _event(
    db: Session,
    operation,
    event_type: str,
    *,
    result: str = "success",
    actor_user_id: int | None = None,
    actor_saas_account_id: int | None = None,
    failure_code: str | None = None,
    details: dict | None = None,
):
    row = models.ExistingWorkspaceConversionEvent(
        conversion_operation_id=operation.id,
        event_type=str(event_type)[:48],
        result=result,
        actor_user_id=actor_user_id,
        actor_saas_account_id=actor_saas_account_id,
        failure_code=str(failure_code or "")[:80] or None,
        details_json=_json(details or {}),
    )
    db.add(row)
    return row


def _actor(db: Session, actor_user_id: int | None):
    actor = db.get(operational_models.User, int(actor_user_id or 0)) if actor_user_id else None
    if actor is None or not auth.is_platform_owner(actor):
        raise ExistingWorkspaceConversionError("platform_owner_required", "Platform Owner approval is required.")
    return actor


def _audit(
    db: Session,
    *,
    school_group_id: int,
    workspace_uuid: str,
    expected_name: str,
    owner_email: str,
):
    return existing_workspace_conversion_audit_service.audit_existing_workspace_conversion(
        db,
        school_group_id=school_group_id,
        workspace_uuid=workspace_uuid,
        expected_name=expected_name,
        owner_email=owner_email,
    )


def _branch_snapshot(report: dict) -> list[dict]:
    rows = []
    for branch in report.get("workspace", {}).get("branches", []):
        stable_dependencies = [
            item
            for item in branch.get("dependencies", [])
            if not any(
                table_name in str(item.get("path") or "")
                for table_name in (
                    "existing_workspace_conversion_operations",
                    "existing_workspace_conversion_events",
                    "saas_account_user_links",
                )
            )
        ]
        rows.append({
            "id": int(branch["id"]),
            "name": str(branch.get("name") or ""),
            "status": bool(branch.get("status")),
            "dependency_record_count": sum(
                int(item.get("record_count") or 0) for item in stable_dependencies
            ),
            "soft_deleted_dependency_record_count": sum(
                int(item.get("soft_deleted_record_count") or 0)
                for item in stable_dependencies
            ),
            "dependencies": stable_dependencies,
            "logical_references": branch.get("logical_references", []),
            "traversal_warnings": branch.get("traversal_warnings", []),
        })
    return sorted(rows, key=lambda item: item["id"])


def _entitlement_snapshot(report: dict) -> list[dict]:
    return list(report.get("commercial_state", {}).get("workspace_entitlements", []))


def _validate_preparation_report(
    report: dict,
    *,
    expected_snapshot_hash: str,
    owner_transfer_approved: bool,
) -> None:
    identity = report.get("identity_validation", {})
    if not all((
        identity.get("school_group_resolved"),
        identity.get("workspace_uuid_matches"),
        identity.get("exact_name_matches"),
    )) or identity.get("duplicate_normalized_names"):
        raise ExistingWorkspaceConversionError("workspace_identity_mismatch")
    if str(report.get("snapshot_hash") or "") != str(expected_snapshot_hash or "").lower():
        raise ExistingWorkspaceConversionError("audit_snapshot_mismatch", "The approved M4A snapshot is stale or mismatched.")
    blockers = set(report.get("conversion_readiness", {}).get("blockers", []))
    allowed = set(ALLOWED_PREPARATION_BLOCKERS)
    if owner_transfer_approved:
        allowed.add("different_existing_tenant_owner")
    unresolved = blockers - allowed
    if unresolved:
        raise ExistingWorkspaceConversionError(sorted(unresolved)[0])
    warnings = set(report.get("conversion_readiness", {}).get("warnings", []))
    unresolved_warnings = warnings - ALLOWED_PREPARATION_WARNINGS
    if unresolved_warnings:
        raise ExistingWorkspaceConversionError(sorted(unresolved_warnings)[0])
    if report.get("schema_coverage", {}).get("branch_foreign_key_traversal") != "complete":
        raise ExistingWorkspaceConversionError("branch_dependency_coverage_incomplete")


def inspect_conversion(
    db: Session,
    *,
    school_group_id: int,
    workspace_uuid: str,
    expected_name: str,
    owner_email: str,
    audit_snapshot_hash: str,
    operation_uuid: str,
    idempotency_key: str,
    owner_transfer_approved: bool = False,
) -> ConversionResult:
    canonical_parameter_hash(
        school_group_id=school_group_id,
        workspace_uuid=workspace_uuid,
        expected_name=expected_name,
        owner_email=owner_email,
        audit_snapshot_hash=audit_snapshot_hash,
        operation_uuid=operation_uuid,
        idempotency_key=idempotency_key,
    )
    report = _audit(
        db,
        school_group_id=school_group_id,
        workspace_uuid=workspace_uuid,
        expected_name=expected_name,
        owner_email=owner_email,
    )
    _validate_preparation_report(
        report,
        expected_snapshot_hash=audit_snapshot_hash,
        owner_transfer_approved=owner_transfer_approved,
    )
    owner_resolution = report.get("owner_identity", {}).get("resolution", "owner_absent")
    status = {
        "owner_absent": "awaiting_owner_registration",
        "owner_unverified": "awaiting_owner_verification",
    }.get(owner_resolution, "awaiting_owner_alignment")
    return ConversionResult(
        status=status,
        reason_code="dry_run_complete",
        operation_uuid=str(uuid.UUID(str(operation_uuid))),
        school_group_id=int(school_group_id),
        stage="registration_preparation",
        changed=False,
        audit_snapshot_hash=str(audit_snapshot_hash).lower(),
        current_snapshot_hash=str(report.get("snapshot_hash") or ""),
    )


def prepare_registration(
    db: Session,
    *,
    school_group_id: int,
    workspace_uuid: str,
    expected_name: str,
    owner_email: str,
    audit_snapshot_hash: str,
    operation_uuid: str,
    idempotency_key: str,
    approved_actor_user_id: int,
    execution_actor_user_id: int,
    owner_transfer_approved: bool = False,
):
    if db.get_bind().dialect.name != "postgresql":
        raise ExistingWorkspaceConversionError("postgresql_required", "Write mode requires PostgreSQL.")
    approved_actor = _actor(db, approved_actor_user_id)
    execution_actor = _actor(db, execution_actor_user_id)
    parameter_hash = canonical_parameter_hash(
        school_group_id=school_group_id,
        workspace_uuid=workspace_uuid,
        expected_name=expected_name,
        owner_email=owner_email,
        audit_snapshot_hash=audit_snapshot_hash,
        operation_uuid=operation_uuid,
        idempotency_key=idempotency_key,
    )
    normalized_operation_uuid = str(uuid.UUID(str(operation_uuid)))
    existing_rows = db.query(models.ExistingWorkspaceConversionOperation).filter(
        (models.ExistingWorkspaceConversionOperation.operation_uuid == normalized_operation_uuid)
        | (models.ExistingWorkspaceConversionOperation.idempotency_key == str(idempotency_key).strip())
    ).with_for_update().all()
    if len(existing_rows) > 1:
        raise ExistingWorkspaceConversionError("idempotency_key_collision")
    existing = existing_rows[0] if existing_rows else None
    if existing is not None:
        if existing.canonical_parameter_hash != parameter_hash:
            raise ExistingWorkspaceConversionError("idempotency_parameter_mismatch")
        return existing, ConversionResult(
            status=existing.status,
            reason_code="already_completed" if existing.status == "completed" else "already_prepared",
            operation_uuid=existing.operation_uuid,
            school_group_id=existing.school_group_id,
            stage=existing.stage,
            changed=False,
            audit_snapshot_hash=existing.audit_snapshot_hash,
        )
    try:
        group = db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id == int(school_group_id)
        ).with_for_update(nowait=True).one_or_none()
    except OperationalError as exc:
        raise ExistingWorkspaceConversionError("workspace_lock_unavailable") from exc
    if group is None:
        raise ExistingWorkspaceConversionError("school_group_not_found")
    report = _audit(
        db,
        school_group_id=school_group_id,
        workspace_uuid=workspace_uuid,
        expected_name=expected_name,
        owner_email=owner_email,
    )
    _validate_preparation_report(
        report,
        expected_snapshot_hash=audit_snapshot_hash,
        owner_transfer_approved=owner_transfer_approved,
    )
    normalized_email = auth.normalize_email(owner_email)
    accounts = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.email_normalized == normalized_email
    ).all()
    if len(accounts) > 1:
        raise ExistingWorkspaceConversionError("duplicate_owner_saas_accounts")
    account = accounts[0] if accounts else None
    if account is None:
        status, stage = "awaiting_owner_registration", "registration_preparation"
    elif not account.email_verified_at:
        status, stage = "awaiting_owner_verification", "owner_verification"
    elif str(account.status or "").lower() != "active":
        raise ExistingWorkspaceConversionError("owner_saas_account_not_active")
    else:
        status, stage = "awaiting_owner_alignment", "owner_alignment"
    operation = models.ExistingWorkspaceConversionOperation(
        operation_uuid=normalized_operation_uuid,
        school_group_id=int(group.id),
        workspace_uuid_snapshot=str(group.workspace_uuid),
        expected_organization_name_snapshot=str(group.name),
        intended_owner_email_normalized=normalized_email,
        audit_snapshot_hash=str(audit_snapshot_hash).lower(),
        canonical_parameter_hash=parameter_hash,
        stage=stage,
        status=status,
        dry_run=False,
        idempotency_key=str(idempotency_key).strip(),
        approved_actor_user_id=approved_actor.id,
        execution_actor_user_id=execution_actor.id,
        owner_transfer_approved_by_user_id=approved_actor.id if owner_transfer_approved else None,
        owner_transfer_approved_at=_utcnow() if owner_transfer_approved else None,
        current_classification_snapshot=str(group.workspace_classification),
        current_lifecycle_snapshot=str(group.workspace_lifecycle_status),
        current_entitlement_snapshot_json=_json(_entitlement_snapshot(report)),
        branch_snapshot_json=_json(_branch_snapshot(report)),
        missing_field_snapshot_json=_json(report.get("setup_field_resolution", {}).get("missing_required_fields", [])),
    )
    db.add(operation)
    db.flush()
    _event(
        db,
        operation,
        "registration_prepared",
        actor_user_id=execution_actor.id,
        details={"owner_state": status, "branch_count": len(_branch_snapshot(report))},
    )
    return operation, ConversionResult(
        status=status,
        reason_code="registration_prepared",
        operation_uuid=operation.operation_uuid,
        school_group_id=operation.school_group_id,
        stage=operation.stage,
        changed=True,
        audit_snapshot_hash=operation.audit_snapshot_hash,
    )


def claim_operation_for_account(db: Session, account, *, lock: bool = False):
    query = db.query(models.ExistingWorkspaceConversionOperation).filter(
        models.ExistingWorkspaceConversionOperation.intended_owner_email_normalized
        == auth.normalize_email(getattr(account, "email", "")),
        models.ExistingWorkspaceConversionOperation.status.in_(OPEN_STATUSES),
    ).order_by(models.ExistingWorkspaceConversionOperation.created_at.asc())
    rows = query.with_for_update().all() if lock else query.all()
    if len(rows) > 1:
        raise ExistingWorkspaceConversionError("ambiguous_owner_conversion_claim")
    return rows[0] if rows else None


def _require_verified_intended_account(operation, account) -> None:
    if auth.normalize_email(getattr(account, "email", "")) != operation.intended_owner_email_normalized:
        raise ExistingWorkspaceConversionError("owner_email_mismatch")
    if not getattr(account, "email_verified_at", None):
        raise ExistingWorkspaceConversionError("account_verification_required", "Verify your TIS Account before continuing.")
    if str(getattr(account, "status", "") or "").lower() != "active":
        raise ExistingWorkspaceConversionError("owner_saas_account_not_active")


def align_verified_owner(db: Session, account):
    operation = claim_operation_for_account(db, account, lock=True)
    if operation is None:
        raise ExistingWorkspaceConversionError("conversion_claim_not_found")
    _require_verified_intended_account(operation, account)
    group = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.id == operation.school_group_id
    ).with_for_update().one()
    if str(group.workspace_uuid) != operation.workspace_uuid_snapshot or str(group.name) != operation.expected_organization_name_snapshot:
        raise ExistingWorkspaceConversionError("workspace_identity_mismatch")
    foreign_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.school_group_id != group.id,
    ).count()
    if foreign_links:
        raise ExistingWorkspaceConversionError("owner_linked_to_another_tenant")
    owner_links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.school_group_id == group.id,
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    ).with_for_update().all()
    same_owner = next((row for row in owner_links if row.saas_account_id == account.id), None)
    if (
        same_owner is not None
        and operation.aligned_saas_account_id == account.id
        and operation.aligned_operational_user_id == same_owner.operational_user_id
        and operation.status in {"awaiting_setup", "ready"}
    ):
        return operation, db.get(operational_models.User, same_owner.operational_user_id), same_owner
    if owner_links and same_owner is None:
        if not operation.owner_transfer_approved_at:
            raise ExistingWorkspaceConversionError("owner_transfer_approval_required")
        for row in owner_links:
            row.link_type = "former_tenant_owner"
        _event(
            db,
            operation,
            "previous_owner_superseded",
            actor_user_id=operation.owner_transfer_approved_by_user_id,
            details={"superseded_owner_count": len(owner_links)},
        )
    try:
        owner_user = provisioning_service.ensure_existing_workspace_owner_user(
            db,
            account,
            group,
            activate=False,
        )
    except ValueError as exc:
        raise ExistingWorkspaceConversionError(
            "operational_owner_identity_conflict", str(exc)
        ) from exc
    link = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.operational_user_id == owner_user.id,
        models.SaaSAccountUserLink.school_group_id == group.id,
    ).one_or_none()
    if link is None:
        link = models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=owner_user.id,
            pending_organization_id=None,
            school_group_id=group.id,
            link_type="tenant_owner",
            linked_at=_utcnow(),
        )
        db.add(link)
    elif link.link_type != "tenant_owner":
        link.link_type = "tenant_owner"
    account.account_purpose = AccountPurpose.CUSTOMER.value
    account.onboarding_status = "existing_workspace_setup"
    operation.aligned_saas_account_id = account.id
    operation.aligned_operational_user_id = owner_user.id
    operation.stage = "setup_review"
    operation.status = "awaiting_setup"
    _event(
        db,
        operation,
        "verified_owner_aligned",
        actor_saas_account_id=account.id,
        details={"operational_user_reused": bool(getattr(owner_user, "created_at", None) and owner_user.id)},
    )
    db.flush()
    return operation, owner_user, link


def setup_review_context(db: Session, account) -> dict:
    operation = claim_operation_for_account(db, account)
    if operation is None:
        raise ExistingWorkspaceConversionError("conversion_claim_not_found")
    _require_verified_intended_account(operation, account)
    group = db.get(operational_models.SchoolGroup, operation.school_group_id)
    profile = db.query(operational_models.TenantProfile).filter(
        operational_models.TenantProfile.school_group_id == operation.school_group_id
    ).one_or_none()
    link = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.school_group_id == operation.school_group_id,
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    ).one_or_none()
    return {
        "operation": operation,
        "school_group": group,
        "profile": profile,
        "owner_aligned": link is not None,
        "required_fields": REQUIRED_SETUP_FIELDS,
        "timezone_options": service.list_iana_timezones(),
        "educational_programs": EDUCATIONAL_PROGRAMS,
    }


def save_setup_review(
    db: Session,
    account,
    *,
    legal_name: str,
    timezone_name: str,
    educational_program: str,
):
    operation = claim_operation_for_account(db, account, lock=True)
    if operation is None:
        raise ExistingWorkspaceConversionError("conversion_claim_not_found")
    _require_verified_intended_account(operation, account)
    owner_link = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.school_group_id == operation.school_group_id,
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    ).one_or_none()
    if owner_link is None:
        raise ExistingWorkspaceConversionError("owner_alignment_required")
    cleaned_legal_name = str(legal_name or "").strip()[:180]
    cleaned_timezone = str(timezone_name or "").strip()[:80]
    cleaned_program = str(educational_program or "").strip().upper()[:20]
    if not cleaned_legal_name:
        raise ExistingWorkspaceConversionError("legal_name_required", "Legal organization name is required.")
    try:
        ZoneInfo(cleaned_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ExistingWorkspaceConversionError("invalid_timezone", "Select a valid time zone.") from exc
    if cleaned_program not in EDUCATIONAL_PROGRAMS:
        raise ExistingWorkspaceConversionError("invalid_educational_program", "Select a valid educational program.")
    setup_values = {
        "legal_name": cleaned_legal_name,
        "timezone": cleaned_timezone,
        "educational_program": cleaned_program,
    }
    if operation.status == "ready" and _load_json(operation.setup_snapshot_json, {}) == setup_values:
        return operation
    profile = db.query(operational_models.TenantProfile).filter(
        operational_models.TenantProfile.school_group_id == operation.school_group_id
    ).with_for_update().one_or_none()
    if profile is None:
        profile = operational_models.TenantProfile(school_group_id=operation.school_group_id)
        db.add(profile)
    profile.legal_name = cleaned_legal_name
    profile.timezone = cleaned_timezone
    profile.educational_program = cleaned_program
    operation.setup_snapshot_json = _json(setup_values)
    operation.missing_field_snapshot_json = "[]"
    operation.stage = "conversion_ready"
    operation.status = "ready"
    account.onboarding_status = "activation_required"
    _event(
        db,
        operation,
        "setup_review_completed",
        actor_saas_account_id=account.id,
        details={"fields_completed": list(REQUIRED_SETUP_FIELDS)},
    )
    db.flush()
    return operation


def _validate_final_state(db: Session, operation, group, report: dict) -> tuple[object, object, object]:
    if int(group.id) != int(operation.school_group_id):
        raise ExistingWorkspaceConversionError("school_group_mismatch")
    if str(group.workspace_uuid) != operation.workspace_uuid_snapshot or str(group.name) != operation.expected_organization_name_snapshot:
        raise ExistingWorkspaceConversionError("workspace_identity_mismatch")
    if str(group.workspace_classification) != operation.current_classification_snapshot or str(group.workspace_lifecycle_status) != operation.current_lifecycle_snapshot:
        raise ExistingWorkspaceConversionError("workspace_state_drift")
    if _branch_snapshot(report) != _load_json(operation.branch_snapshot_json, []):
        raise ExistingWorkspaceConversionError("branch_inventory_or_dependency_drift")
    current_entitlements = _entitlement_snapshot(report)
    if current_entitlements != _load_json(operation.current_entitlement_snapshot_json, []):
        raise ExistingWorkspaceConversionError("commercial_entitlement_drift")
    if report.get("tenant_and_provisioning", {}).get("tenant_provisioning_links"):
        raise ExistingWorkspaceConversionError("existing_tenant_provisioning_link")
    commercial = report.get("commercial_state", {})
    for key in ("subscription_contracts", "payment_subscriptions", "promo_grants", "promo_redemptions"):
        if commercial.get(key):
            raise ExistingWorkspaceConversionError("existing_commercial_source")
    if report.get("tenant_and_provisioning", {}).get("pending_organizations"):
        raise ExistingWorkspaceConversionError("existing_pending_organization")
    active_internal = db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.school_group_id == group.id,
        models.WorkspaceEntitlement.entitlement_type == "internal_sandbox",
        models.WorkspaceEntitlement.status == "active",
    ).with_for_update().all()
    if len(active_internal) != 1:
        raise ExistingWorkspaceConversionError("internal_sandbox_entitlement_is_not_exactly_one")
    account = db.get(models.SaaSAccount, operation.aligned_saas_account_id)
    owner_user = db.get(operational_models.User, operation.aligned_operational_user_id)
    if account is None or owner_user is None:
        raise ExistingWorkspaceConversionError("owner_alignment_required")
    _require_verified_intended_account(operation, account)
    owners = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.school_group_id == group.id,
        models.SaaSAccountUserLink.link_type == "tenant_owner",
    ).with_for_update().all()
    if len(owners) != 1 or owners[0].saas_account_id != account.id or owners[0].operational_user_id != owner_user.id:
        raise ExistingWorkspaceConversionError("tenant_owner_uniqueness_violation")
    profile = db.query(operational_models.TenantProfile).filter(
        operational_models.TenantProfile.school_group_id == group.id
    ).with_for_update().one_or_none()
    if profile is None or not str(profile.legal_name or "").strip() or not str(profile.timezone or "").strip() or str(profile.educational_program or "") not in EDUCATIONAL_PROGRAMS:
        raise ExistingWorkspaceConversionError("required_setup_incomplete")
    try:
        ZoneInfo(str(profile.timezone))
    except ZoneInfoNotFoundError as exc:
        raise ExistingWorkspaceConversionError("invalid_timezone") from exc
    return active_internal[0], account, owner_user


def execute_conversion(
    db: Session,
    *,
    operation_uuid: str,
    idempotency_key: str,
    parameter_hash: str,
    confirmation_phrase: str,
    execution_actor_user_id: int,
) -> ConversionResult:
    if db.get_bind().dialect.name != "postgresql":
        raise ExistingWorkspaceConversionError("postgresql_required", "Write mode requires PostgreSQL.")
    actor = _actor(db, execution_actor_user_id)
    normalized_uuid = str(uuid.UUID(str(operation_uuid).strip()))
    expected_confirmation = f"CONVERT {normalized_uuid}"
    if str(confirmation_phrase or "").strip() != expected_confirmation:
        raise ExistingWorkspaceConversionError("confirmation_required", f"Type {expected_confirmation} to confirm.")
    try:
        operation = db.query(models.ExistingWorkspaceConversionOperation).filter(
            models.ExistingWorkspaceConversionOperation.operation_uuid == normalized_uuid
        ).with_for_update(nowait=True).one_or_none()
    except OperationalError as exc:
        raise ExistingWorkspaceConversionError("conversion_operation_lock_unavailable") from exc
    if operation is None:
        raise ExistingWorkspaceConversionError("conversion_operation_not_found")
    if operation.idempotency_key != str(idempotency_key or "").strip():
        raise ExistingWorkspaceConversionError("idempotency_parameter_mismatch")
    if operation.canonical_parameter_hash != str(parameter_hash or ""):
        raise ExistingWorkspaceConversionError("idempotency_parameter_mismatch")
    if operation.status == "completed":
        return ConversionResult(
            status="completed",
            reason_code="already_completed",
            operation_uuid=operation.operation_uuid,
            school_group_id=operation.school_group_id,
            stage=operation.stage,
            changed=False,
            audit_snapshot_hash=operation.audit_snapshot_hash,
        )
    if operation.status != "ready" or operation.stage != "conversion_ready":
        raise ExistingWorkspaceConversionError("conversion_not_ready")
    try:
        group = db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id == operation.school_group_id
        ).with_for_update(nowait=True).one()
    except OperationalError as exc:
        raise ExistingWorkspaceConversionError("workspace_lock_unavailable") from exc
    report = _audit(
        db,
        school_group_id=operation.school_group_id,
        workspace_uuid=operation.workspace_uuid_snapshot,
        expected_name=operation.expected_organization_name_snapshot,
        owner_email=operation.intended_owner_email_normalized,
    )
    internal_entitlement, account, owner_user = _validate_final_state(db, operation, group, report)
    operation.status = "in_progress"
    operation.stage = "conversion_processing"
    operation.execution_actor_user_id = actor.id
    now = _utcnow()
    internal_entitlement.status = "ended"
    internal_entitlement.effective_to = now
    group.workspace_classification = WorkspaceClassification.CUSTOMER.value
    group.workspace_lifecycle_status = WorkspaceLifecycleStatus.PROVISIONING.value
    group.updated_at = now
    owner_user.is_active = True
    owner_user.is_internal_test_identity = False
    owner_user.email_verified_at = account.email_verified_at
    owner_user.password = account.password_hash
    owner_user.updated_at = now
    account.account_purpose = AccountPurpose.CUSTOMER.value
    account.onboarding_status = "activation_required"
    db.flush()
    if db.query(models.WorkspaceEntitlement.id).filter(
        models.WorkspaceEntitlement.school_group_id == group.id,
        models.WorkspaceEntitlement.status == "active",
    ).first():
        raise ExistingWorkspaceConversionError("active_entitlement_remains")
    if db.query(models.TenantProvisioningLink.id).filter(
        models.TenantProvisioningLink.school_group_id == group.id
    ).first():
        raise ExistingWorkspaceConversionError("tenant_link_created_unexpectedly")
    authority = commercial_authority_service.resolve_commercial_authority(db, group.id)
    if authority.commercial_status != commercial_authority_service.ACTIVATION_REQUIRED or authority.access_allowed:
        raise ExistingWorkspaceConversionError("activation_required_resolution_failed")
    operation.status = "completed"
    operation.stage = "converted"
    operation.completed_at = now
    operation.failure_code = None
    _event(
        db,
        operation,
        "conversion_completed",
        actor_user_id=actor.id,
        details={"commercial_status": authority.commercial_status, "branch_count": len(_branch_snapshot(report))},
    )
    db.flush()
    return ConversionResult(
        status="completed",
        reason_code="conversion_completed",
        operation_uuid=operation.operation_uuid,
        school_group_id=operation.school_group_id,
        stage=operation.stage,
        changed=True,
        audit_snapshot_hash=operation.audit_snapshot_hash,
        current_snapshot_hash=str(report.get("snapshot_hash") or ""),
    )


def record_failed_execution(
    db: Session,
    *,
    operation_uuid: str,
    actor_user_id: int | None,
    failure_code: str,
) -> None:
    operation = db.query(models.ExistingWorkspaceConversionOperation).filter(
        models.ExistingWorkspaceConversionOperation.operation_uuid == str(operation_uuid)
    ).one_or_none()
    if operation is None or operation.status == "completed":
        return
    operation.failure_code = str(failure_code or "conversion_failed")[:80]
    _event(
        db,
        operation,
        "conversion_failed",
        result="failed",
        actor_user_id=actor_user_id,
        failure_code=operation.failure_code,
    )
