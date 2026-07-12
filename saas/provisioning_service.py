from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

import auth
import branding_storage
import email_service
import email_templates
import models as operational_models
import permission_registry
import public_url
import role_permission_service
from saas import models, service

READY_FOR_PROVISIONING = "ready_for_provisioning"
PROVISIONING_STARTED = "provisioning_started"
PROVISIONING_COMPLETED = "provisioning_completed"
TENANT_ACTIVE = "tenant_active"
PROVISIONING_RETRYING = "provisioning_retrying"
PROVISIONING_FAILED = "provisioning_failed"

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_RETRYING = "retrying"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_SKIPPED = "skipped"


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _json(value: dict | None = None) -> str | None:
    if not value:
        return None
    return json.dumps(value, separators=(",", ":"))


def _public_base_url() -> str:
    return public_url.public_base_url()


def operational_login_url() -> str:
    return f"{_public_base_url()}/login"


def _email_logo_url() -> str:
    return public_url.public_static_asset_url(
        branding_storage.tis_logo_relative_path(theme="light", compact=True)
    )


def get_tenant_provisioning_link(db: Session, organization):
    return db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == organization.id
    ).first()


def get_latest_provisioning_job(db: Session, organization):
    return db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id == organization.id
    ).order_by(
        models.ProvisioningJob.updated_at.desc(),
        models.ProvisioningJob.id.desc(),
    ).first()


def list_provisioning_jobs(db: Session, *, job_status: str = ""):
    query = db.query(models.ProvisioningJob)
    cleaned_status = str(job_status or "").strip().lower()
    if cleaned_status:
        query = query.filter(models.ProvisioningJob.job_status == cleaned_status)
    return query.order_by(
        models.ProvisioningJob.updated_at.desc(),
        models.ProvisioningJob.id.desc(),
    ).all()


def list_provisioning_job_events(db: Session, job):
    return db.query(models.ProvisioningJobEvent).filter(
        models.ProvisioningJobEvent.provisioning_job_id == job.id
    ).order_by(
        models.ProvisioningJobEvent.created_at.asc(),
        models.ProvisioningJobEvent.id.asc(),
    ).all()


def log_job_event(
    db: Session,
    *,
    job,
    event_type: str,
    event_status: str = "ok",
    details: dict | None = None,
):
    db.add(
        models.ProvisioningJobEvent(
            provisioning_job_id=job.id,
            event_type=str(event_type or "").strip()[:40] or "unknown",
            event_status=str(event_status or "").strip()[:20] or "ok",
            details_json=_json(details),
        )
    )


def _organization_branches(db: Session, organization):
    return db.query(models.PendingOrganizationBranch).filter(
        models.PendingOrganizationBranch.pending_organization_id == organization.id
    ).order_by(
        models.PendingOrganizationBranch.sort_order.asc(),
        models.PendingOrganizationBranch.id.asc(),
    ).all()


def _organization_academic_setup(db: Session, organization):
    return db.query(models.PendingOrganizationAcademicSetup).filter(
        models.PendingOrganizationAcademicSetup.pending_organization_id == organization.id
    ).first()


def _organization_primary_contact(db: Session, organization):
    return db.query(models.PendingOrganizationContact).filter(
        models.PendingOrganizationContact.pending_organization_id == organization.id,
        models.PendingOrganizationContact.is_primary == True,
    ).order_by(models.PendingOrganizationContact.id.asc()).first()


def _normalize_group_name(name: str) -> str:
    return " ".join(str(name or "").split())[:160]


def _generate_unique_school_group_name(db: Session, base_name: str) -> str:
    cleaned = _normalize_group_name(base_name) or "TIS Organization"
    existing = db.query(operational_models.SchoolGroup).filter(
        operational_models.SchoolGroup.name == cleaned
    ).first()
    if not existing:
        return cleaned
    suffix = 2
    while True:
        candidate = f"{cleaned} ({suffix})"[:160]
        existing = db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.name == candidate
        ).first()
        if not existing:
            return candidate
        suffix += 1


def _next_operational_user_id(db: Session) -> str:
    existing_ids = []
    for (value,) in db.query(operational_models.User.user_id).all():
        cleaned = str(value or "").strip()
        if cleaned.isdigit():
            existing_ids.append(int(cleaned))
    next_value = max(existing_ids, default=7000000000) + 1
    return str(next_value)[:10]


def _copy_pending_logo_to_school_group(db: Session, organization, school_group_id: int, owner_user_id: str | None):
    source_relative = str(getattr(organization, "organization_logo_path", "") or "").strip()
    if not source_relative:
        return None
    source_path = (Path(__file__).resolve().parent.parent / "static" / Path(*source_relative.split("/"))).resolve()
    static_root = (Path(__file__).resolve().parent.parent / "static").resolve()
    try:
        source_path.relative_to(static_root)
    except ValueError as exc:
        raise ValueError("Pending organization logo path is invalid.") from exc
    if not source_path.is_file():
        return None

    file_bytes = source_path.read_bytes()
    upload_info = branding_storage.validate_logo_upload(
        file_bytes,
        source_path.name,
        slot_key="primary",
    )
    relative_path = branding_storage.write_logo_file(
        file_bytes,
        school_group_id=school_group_id,
        slot_key="primary",
        extension=upload_info.extension,
    )
    existing_logo = db.query(operational_models.SchoolGroupLogo).filter(
        operational_models.SchoolGroupLogo.school_group_id == school_group_id,
        operational_models.SchoolGroupLogo.slot_key == "primary",
    ).first()
    if existing_logo:
        existing_logo.label = "Main organization logo"
        existing_logo.image_path = relative_path
        existing_logo.content_type = upload_info.content_type
        existing_logo.updated_by_user_id = owner_user_id
        existing_logo.updated_at = _utcnow()
        return existing_logo
    logo_row = operational_models.SchoolGroupLogo(
        school_group_id=school_group_id,
        slot_key="primary",
        label="Main organization logo",
        image_path=relative_path,
        content_type=upload_info.content_type,
        sort_order=1,
        updated_by_user_id=owner_user_id,
    )
    db.add(logo_row)
    db.flush()
    return logo_row


def _upsert_tenant_profile(db: Session, organization, school_group_id: int):
    row = db.query(operational_models.TenantProfile).filter(
        operational_models.TenantProfile.school_group_id == school_group_id
    ).first()
    if not row:
        row = operational_models.TenantProfile(school_group_id=school_group_id)
        db.add(row)
        db.flush()
    row.website = str(getattr(organization, "website", "") or "").strip()[:180] or None
    row.timezone = str(getattr(organization, "timezone", "") or "").strip()[:80] or None
    row.educational_program = str(getattr(organization, "educational_program", "") or "").strip()[:20] or None
    row.school_type = str(getattr(organization, "school_type", "") or "").strip()[:120] or None
    row.estimated_staff_users = getattr(organization, "estimated_staff_users", None)
    return row


def _create_school_group(db: Session, organization):
    group_name = _generate_unique_school_group_name(
        db,
        getattr(organization, "legal_name", None) or getattr(organization, "organization_name", ""),
    )
    school_group = operational_models.SchoolGroup(
        name=group_name,
        country_code=str(getattr(organization, "country_code", "") or "").strip()[:2] or None,
        country_name=str(getattr(organization, "country_name", "") or "").strip()[:120] or None,
        region_name=str(getattr(organization, "region_name", "") or "").strip()[:160] or None,
        city_name=str(getattr(organization, "city_name", "") or "").strip()[:160] or None,
        district_name=str(getattr(organization, "district_name", "") or "").strip()[:160] or None,
        neighborhood_name=str(getattr(organization, "neighborhood_name", "") or "").strip()[:160] or None,
        status=True,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(school_group)
    db.flush()
    branding_storage.ensure_organization_logo_dir(school_group.id)
    _upsert_tenant_profile(db, organization, school_group.id)
    return school_group


def _create_branches(db: Session, organization, school_group):
    pending_branches = _organization_branches(db, organization)
    if not pending_branches:
        raise ValueError("At least one pending branch is required before provisioning.")
    created = []
    for pending_branch in pending_branches:
        branch_row = operational_models.Branch(
            school_group_id=school_group.id,
            name=str(getattr(pending_branch, "branch_name", "") or "").strip()[:160],
            location=str(getattr(pending_branch, "location", "") or "").strip()[:180] or str(getattr(pending_branch, "region_name", "") or "").strip()[:160] or None,
            country_code=str(getattr(pending_branch, "country_code", "") or "").strip()[:2] or None,
            country_name=str(getattr(pending_branch, "country_name", "") or "").strip()[:120] or None,
            region_name=str(getattr(pending_branch, "region_name", "") or "").strip()[:160] or None,
            city_name=str(getattr(pending_branch, "city_name", "") or "").strip()[:160] or None,
            district_name=str(getattr(pending_branch, "district_name", "") or "").strip()[:160] or None,
            neighborhood_name=str(getattr(pending_branch, "neighborhood_name", "") or "").strip()[:160] or None,
            status=True,
        )
        db.add(branch_row)
        db.flush()
        created.append(branch_row)
    return created


def _create_academic_year(db: Session, organization, school_group):
    academic_setup = _organization_academic_setup(db, organization)
    year_name = ""
    if academic_setup:
        year_name = str(getattr(academic_setup, "first_academic_year_name", "") or "").strip()
    year_name = year_name or f"{datetime.utcnow().year}-{datetime.utcnow().year + 1}"
    active_rows = db.query(operational_models.AcademicYear).filter(
        operational_models.AcademicYear.school_group_id == school_group.id,
        operational_models.AcademicYear.is_active == True,
    ).all()
    for row in active_rows:
        row.is_active = False
    academic_year = operational_models.AcademicYear(
        school_group_id=school_group.id,
        year_name=year_name[:40],
        is_active=True,
    )
    db.add(academic_year)
    db.flush()
    return academic_year


def _create_owner_user(db: Session, account, organization, school_group, primary_branch, academic_year):
    primary_contact = _organization_primary_contact(db, organization)
    first_name = (
        str(getattr(primary_contact, "first_name", "") or "").strip()
        or str(getattr(account, "first_name", "") or "").strip()
        or "Organization"
    )
    last_name = (
        str(getattr(primary_contact, "last_name", "") or "").strip()
        or str(getattr(account, "last_name", "") or "").strip()
        or "Owner"
    )
    position = (
        str(getattr(primary_contact, "job_title", "") or "").strip()[:50]
        or "Principal"
    )
    normalized_email = auth.normalize_email(getattr(account, "email", None))
    existing_conflict = db.query(operational_models.User).filter(
        operational_models.User.email_normalized == normalized_email
    ).first()
    if existing_conflict:
        link = db.query(models.SaaSAccountUserLink).filter(
            models.SaaSAccountUserLink.saas_account_id == account.id,
            models.SaaSAccountUserLink.operational_user_id == existing_conflict.id,
            models.SaaSAccountUserLink.school_group_id == school_group.id,
        ).first()
        if link:
            return existing_conflict
        raise ValueError("Operational owner email already exists and is linked to another account.")

    user_id = _next_operational_user_id(db)
    user_row = operational_models.User(
        user_id=user_id,
        username=user_id,
        email=str(getattr(account, "email", "") or "").strip() or None,
        email_normalized=normalized_email,
        email_verified_at=getattr(account, "email_verified_at", None),
        first_name=first_name,
        last_name=last_name,
        position=position,
        password=getattr(account, "password_hash", None),
        role=auth.ROLE_ADMINISTRATOR,
        user_type=auth.USER_TYPE_TENANT,
        platform_role=None,
        access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
        school_group_id=school_group.id,
        branch_id=primary_branch.id if primary_branch else None,
        academic_year_id=academic_year.id if academic_year else None,
        is_active=True,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(user_row)
    db.flush()
    return user_row


def _ensure_account_user_link(db: Session, account, owner_user, organization, school_group):
    link = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account.id,
        models.SaaSAccountUserLink.operational_user_id == owner_user.id,
        models.SaaSAccountUserLink.school_group_id == school_group.id,
    ).first()
    if link:
        return link
    link = models.SaaSAccountUserLink(
        saas_account_id=account.id,
        operational_user_id=owner_user.id,
        pending_organization_id=organization.id,
        school_group_id=school_group.id,
        link_type="tenant_owner",
        linked_at=_utcnow(),
    )
    db.add(link)
    db.flush()
    return link


def _ensure_tenant_provisioning_link(
    db: Session,
    *,
    organization,
    contract,
    school_group,
    owner_user,
    primary_branch,
    academic_year,
):
    link = get_tenant_provisioning_link(db, organization)
    if link:
        return link
    link = models.TenantProvisioningLink(
        pending_organization_id=organization.id,
        subscription_contract_id=contract.id,
        school_group_id=school_group.id,
        owner_operational_user_id=owner_user.id,
        primary_branch_id=getattr(primary_branch, "id", None),
        primary_academic_year_id=getattr(academic_year, "id", None),
        tenant_status=TENANT_ACTIVE,
        activated_at=_utcnow(),
    )
    db.add(link)
    db.flush()
    return link


def _send_activation_email(account, organization):
    email_content = email_templates.build_tenant_activation_email(
        organization_name=str(getattr(organization, "organization_name", "") or "").strip() or "Your organization",
        login_url=operational_login_url(),
        logo_url=_email_logo_url(),
    )
    email_service.send_email(
        to=str(getattr(account, "email", "") or "").strip(),
        subject=email_content.subject,
        text=email_content.text,
        html=email_content.html,
    )


def enqueue_ready_for_provisioning(
    db: Session,
    organization,
    contract,
    *,
    trigger_source: str = "payment_webhook",
):
    existing_link = get_tenant_provisioning_link(db, organization)
    if existing_link:
        return None

    if str(getattr(organization, "billing_status", "") or "").strip().lower() != READY_FOR_PROVISIONING:
        raise ValueError("Pending organization is not ready for provisioning.")
    if str(getattr(contract, "contract_status", "") or "").strip().lower() not in {
        "paid_pending_provisioning",
        READY_FOR_PROVISIONING,
        PROVISIONING_RETRYING,
        PROVISIONING_FAILED,
    }:
        raise ValueError("Subscription contract is not ready for provisioning.")

    active_job = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id == organization.id,
        models.ProvisioningJob.job_status.in_(
            [JOB_STATUS_QUEUED, JOB_STATUS_PROCESSING, JOB_STATUS_RETRYING]
        ),
    ).order_by(models.ProvisioningJob.id.desc()).first()
    if active_job:
        return active_job

    idempotency_key = (
        f"tenant-provisioning:{organization.organization_uuid}:{contract.id}:"
        f"{getattr(contract, 'paid_at', None) or getattr(organization, 'payment_confirmed_at', None) or 'na'}"
    )
    existing_job = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.idempotency_key == idempotency_key
    ).first()
    if existing_job:
        return existing_job

    job = models.ProvisioningJob(
        pending_organization_id=organization.id,
        subscription_contract_id=contract.id,
        job_uuid=str(uuid.uuid4()),
        idempotency_key=idempotency_key[:160],
        trigger_source=str(trigger_source or "payment_webhook")[:40],
        job_status=JOB_STATUS_QUEUED,
        next_attempt_at=_utcnow(),
    )
    db.add(job)
    db.flush()
    log_job_event(
        db,
        job=job,
        event_type="queued",
        details={"organization_uuid": organization.organization_uuid},
    )
    service.log_pending_event(
        db,
        organization=organization,
        event_type="provisioning_queued",
        details={"job_uuid": job.job_uuid},
    )
    return job


def _mark_success(db: Session, *, job, organization, contract, tenant_link, school_group):
    organization.billing_status = PROVISIONING_COMPLETED
    contract.contract_status = PROVISIONING_COMPLETED
    service.log_pending_event(
        db,
        organization=organization,
        event_type="provisioning_completed",
        details={"school_group_id": school_group.id},
    )
    organization.billing_status = TENANT_ACTIVE
    contract.contract_status = TENANT_ACTIVE
    contract.school_group_id = school_group.id
    job.job_status = JOB_STATUS_COMPLETED
    job.target_school_group_id = school_group.id
    job.tenant_provisioning_link_id = tenant_link.id
    job.completed_at = _utcnow()
    job.last_error = None
    tenant_link.tenant_status = TENANT_ACTIVE
    tenant_link.activated_at = tenant_link.activated_at or _utcnow()
    service.log_pending_event(
        db,
        organization=organization,
        event_type="tenant_active",
        details={"school_group_id": school_group.id},
    )
    log_job_event(
        db,
        job=job,
        event_type="tenant_active",
        details={"school_group_id": school_group.id},
    )


def _mark_failure(db: Session, *, job, organization, contract, exc: Exception):
    job.last_error = str(exc)[:4000]
    if int(job.attempt_count or 0) < int(job.max_attempts or 3):
        job.job_status = JOB_STATUS_RETRYING
        job.next_attempt_at = _utcnow() + timedelta(minutes=5)
        organization.billing_status = PROVISIONING_RETRYING
        contract.contract_status = PROVISIONING_RETRYING
        log_job_event(
            db,
            job=job,
            event_type="retry_scheduled",
            event_status="retry",
            details={"error": str(exc)},
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="provisioning_retrying",
            details={"error": str(exc)},
        )
    else:
        job.job_status = JOB_STATUS_FAILED
        job.failed_at = _utcnow()
        organization.billing_status = PROVISIONING_FAILED
        contract.contract_status = PROVISIONING_FAILED
        log_job_event(
            db,
            job=job,
            event_type="failed",
            event_status="failed",
            details={"error": str(exc)},
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="provisioning_failed",
            details={"error": str(exc)},
        )


def _provision_organization(db: Session, job):
    organization = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == job.pending_organization_id
    ).first()
    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.id == job.subscription_contract_id
    ).first()
    if not organization or not contract:
        raise ValueError("Provisioning references could not be loaded.")

    existing_link = get_tenant_provisioning_link(db, organization)
    if existing_link:
        school_group = db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id == existing_link.school_group_id
        ).first()
        if not school_group:
            raise ValueError("Provisioning link exists but school group is missing.")
        return organization, contract, existing_link, school_group, None, None

    account = db.query(models.SaaSAccount).filter(
        models.SaaSAccount.id == organization.owner_saas_account_id
    ).first()
    if not account:
        raise ValueError("Provisioning owner account is missing.")

    school_group = _create_school_group(db, organization)
    branches = _create_branches(db, organization, school_group)
    primary_branch = branches[0]
    academic_year = _create_academic_year(db, organization, school_group)
    role_permission_service.seed_tenant_role_permissions(
        db,
        school_group_id=school_group.id,
        updated_by_user_id="system",
    )
    owner_user = _create_owner_user(
        db,
        account,
        organization,
        school_group,
        primary_branch,
        academic_year,
    )
    _ensure_account_user_link(db, account, owner_user, organization, school_group)
    _copy_pending_logo_to_school_group(
        db,
        organization,
        school_group.id,
        getattr(owner_user, "user_id", None),
    )
    tenant_link = _ensure_tenant_provisioning_link(
        db,
        organization=organization,
        contract=contract,
        school_group=school_group,
        owner_user=owner_user,
        primary_branch=primary_branch,
        academic_year=academic_year,
    )
    return organization, contract, tenant_link, school_group, owner_user, account


def process_job(db: Session, job):
    organization = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.id == job.pending_organization_id
    ).first()
    contract = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.id == job.subscription_contract_id
    ).first()
    if not organization or not contract:
        job.job_status = JOB_STATUS_FAILED
        job.failed_at = _utcnow()
        log_job_event(
            db,
            job=job,
            event_type="failed",
            event_status="failed",
            details={"error": "Provisioning references are missing."},
        )
        return job

    if get_tenant_provisioning_link(db, organization):
        job.job_status = JOB_STATUS_COMPLETED
        job.completed_at = job.completed_at or _utcnow()
        log_job_event(
            db,
            job=job,
            event_type="duplicate_skipped",
            details={"reason": "tenant_already_exists"},
        )
        return job

    job.job_status = JOB_STATUS_PROCESSING
    job.started_at = _utcnow()
    job.attempt_count = int(job.attempt_count or 0) + 1
    job.next_attempt_at = None
    organization.billing_status = PROVISIONING_STARTED
    contract.contract_status = PROVISIONING_STARTED
    service.log_pending_event(
        db,
        organization=organization,
        event_type="provisioning_started",
        details={"job_uuid": job.job_uuid},
    )
    log_job_event(db, job=job, event_type="started")

    try:
        with db.begin_nested():
            organization, contract, tenant_link, school_group, _owner_user, account = _provision_organization(db, job)
        _mark_success(
            db,
            job=job,
            organization=organization,
            contract=contract,
            tenant_link=tenant_link,
            school_group=school_group,
        )
        if account:
            try:
                _send_activation_email(account, organization)
            except email_service.EmailDeliveryError:
                log_job_event(
                    db,
                    job=job,
                    event_type="activation_email_failed",
                    event_status="warning",
                )
    except Exception as exc:
        _mark_failure(
            db,
            job=job,
            organization=organization,
            contract=contract,
            exc=exc,
        )
    return job


def process_pending_jobs(db: Session, *, limit: int = 10):
    now = _utcnow()
    jobs = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.job_status.in_([JOB_STATUS_QUEUED, JOB_STATUS_RETRYING]),
        or_(
            models.ProvisioningJob.next_attempt_at.is_(None),
            models.ProvisioningJob.next_attempt_at <= now,
        ),
    ).order_by(
        models.ProvisioningJob.created_at.asc(),
        models.ProvisioningJob.id.asc(),
    ).limit(max(1, int(limit or 10))).all()
    processed = []
    for job in jobs:
        processed.append(process_job(db, job))
    return processed


def retry_job(db: Session, job):
    if str(getattr(job, "job_status", "") or "").strip().lower() not in {
        JOB_STATUS_FAILED,
        JOB_STATUS_RETRYING,
    }:
        raise ValueError("Only failed or retrying provisioning jobs can be retried.")
    job.job_status = JOB_STATUS_QUEUED
    job.next_attempt_at = _utcnow()
    job.failed_at = None
    log_job_event(db, job=job, event_type="manual_retry")
    return process_job(db, job)
