from datetime import UTC, datetime
import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text

from database import Base
from workspace_classification import AccountPurpose, WorkspaceIntent


def _aware_utcnow():
    return datetime.now(UTC)


class SaaSAccount(Base):
    __tablename__ = "saas_accounts"
    __table_args__ = (
        Index(
            "uq_saas_accounts_email_normalized",
            "email_normalized",
            unique=True,
            sqlite_where=text("email_normalized IS NOT NULL"),
            postgresql_where=text("email_normalized IS NOT NULL"),
        ),
        Index("ix_saas_accounts_status", "status"),
        Index("ix_saas_accounts_onboarding_status", "onboarding_status"),
        Index("ix_saas_accounts_last_meaningful_activity", "last_meaningful_activity_at"),
        Index("ix_saas_accounts_account_purpose", "account_purpose"),
        Index("ix_saas_accounts_signup_intent", "signup_intent"),
        CheckConstraint(
            "account_purpose IN ('internal_test','customer')",
            name="ck_saas_accounts_account_purpose",
        ),
    )

    id = Column(Integer, primary_key=True)
    account_uuid = Column(String(36), nullable=False, unique=True, index=True)
    email = Column(String(180), nullable=False, index=True)
    email_normalized = Column(String(180), nullable=False)
    password_hash = Column(String(255))
    first_name = Column(String(120))
    last_name = Column(String(120))
    status = Column(String(20), nullable=False, default="pending_verification")
    onboarding_status = Column(String(30), nullable=False, default="not_started")
    signup_intent = Column(String(20))
    account_purpose = Column(
        String(20), nullable=False, default=AccountPurpose.INTERNAL_TEST.value
    )
    email_verified_at = Column(DateTime)
    last_login_at = Column(DateTime)
    last_meaningful_activity_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    first_reminder_sent_at = Column(DateTime)
    second_reminder_sent_at = Column(DateTime)
    final_reminder_sent_at = Column(DateTime)
    recovered_after_reminder_at = Column(DateTime)
    reminder_cycle = Column(Integer, nullable=False, default=1)
    locked_at = Column(DateTime)
    locked_reason = Column(String(120))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSAuthIdentity(Base):
    __tablename__ = "saas_auth_identities"
    __table_args__ = (
        Index(
            "uq_saas_auth_identities_provider_subject",
            "provider",
            "provider_subject",
            unique=True,
        ),
        Index("ix_saas_auth_identities_account", "saas_account_id"),
        Index("ix_saas_auth_identities_email_normalized", "provider_email_normalized"),
    )

    id = Column(Integer, primary_key=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=False, index=True)
    provider_subject = Column(String(255), nullable=False)
    provider_email = Column(String(180))
    provider_email_normalized = Column(String(180))
    provider_tenant_hint = Column(String(255))
    provider_profile_json = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSSession(Base):
    __tablename__ = "saas_sessions"
    __table_args__ = (
        Index("uq_saas_sessions_token_hash", "session_token_hash", unique=True),
        Index("ix_saas_sessions_account", "saas_account_id"),
        Index("ix_saas_sessions_expires_at", "expires_at"),
        Index("ix_saas_sessions_revoked_at", "revoked_at"),
    )

    id = Column(Integer, primary_key=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    session_token_hash = Column(String(128), nullable=False)
    session_family_id = Column(String(64), nullable=False, index=True)
    csrf_token_hash = Column(String(128))
    ip_address = Column(String(80))
    user_agent = Column(String(255))
    issued_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime)
    revoke_reason = Column(String(80))


class SaaSEmailVerificationToken(Base):
    __tablename__ = "saas_email_verification_tokens"
    __table_args__ = (
        Index("uq_saas_email_verification_tokens_hash", "token_hash", unique=True),
        Index("ix_saas_email_verification_tokens_account", "saas_account_id"),
        Index("ix_saas_email_verification_tokens_expires_at", "expires_at"),
        Index(
            "ix_saas_email_verification_tokens_account_consumed",
            "saas_account_id",
            "consumed_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False)
    email_normalized = Column(String(180), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime)
    request_ip = Column(String(80))
    user_agent = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SaaSPasswordResetToken(Base):
    __tablename__ = "saas_password_reset_tokens"
    __table_args__ = (
        Index("uq_saas_password_reset_tokens_hash", "token_hash", unique=True),
        Index("ix_saas_password_reset_tokens_account", "saas_account_id"),
        Index("ix_saas_password_reset_tokens_expires_at", "expires_at"),
        Index(
            "ix_saas_password_reset_tokens_account_consumed",
            "saas_account_id",
            "consumed_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    token_hash = Column(String(128), nullable=False)
    email_normalized = Column(String(180), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime)
    request_ip = Column(String(80))
    user_agent = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BlockedEmailDomain(Base):
    __tablename__ = "blocked_email_domains"
    __table_args__ = (
        Index("uq_blocked_email_domains_domain", "domain", unique=True),
        Index("ix_blocked_email_domains_active", "is_active"),
        Index("ix_blocked_email_domains_enforcement", "enforcement"),
    )

    id = Column(Integer, primary_key=True)
    domain = Column(String(180), nullable=False)
    domain_category = Column(String(20), nullable=False, default="blocked")
    enforcement = Column(String(20), nullable=False, default="block")
    reason = Column(String(255))
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSAuthEvent(Base):
    __tablename__ = "saas_auth_events"
    __table_args__ = (
        Index("ix_saas_auth_events_account", "saas_account_id"),
        Index("ix_saas_auth_events_event_type", "event_type"),
        Index("ix_saas_auth_events_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), index=True)
    event_type = Column(String(40), nullable=False)
    event_status = Column(String(20), nullable=False, default="ok")
    ip_address = Column(String(80))
    user_agent = Column(String(255))
    details_json = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PendingOrganization(Base):
    __tablename__ = "pending_organizations"
    __table_args__ = (
        Index("uq_pending_organizations_uuid", "organization_uuid", unique=True),
        Index("ix_pending_organizations_owner", "owner_saas_account_id"),
        Index("ix_pending_organizations_status", "status"),
        Index("ix_pending_organizations_step", "onboarding_step"),
        Index("ix_pending_organizations_name", "organization_name"),
        Index("ix_pending_organizations_last_meaningful_activity", "last_meaningful_activity_at"),
        Index("ix_pending_organizations_workspace_intent", "workspace_intent"),
        Index("ix_pending_organizations_commercial_intent", "commercial_intent"),
        CheckConstraint(
            "workspace_intent IN ('internal_sandbox','customer_demo','customer_paid','customer')",
            name="ck_pending_organizations_workspace_intent",
        ),
    )

    id = Column(Integer, primary_key=True)
    organization_uuid = Column(String(36), nullable=False, unique=True, index=True)
    workspace_intent = Column(
        String(32), nullable=False, default=WorkspaceIntent.INTERNAL_SANDBOX.value
    )
    commercial_intent = Column(String(20))
    owner_saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="draft")
    onboarding_step = Column(String(40), nullable=False, default="organization")
    organization_name = Column(String(160), nullable=False, default="")
    legal_name = Column(String(180))
    website = Column(String(180))
    primary_domain = Column(String(180))
    phone = Column(String(80))
    organization_logo_path = Column(String(255))
    educational_program = Column(String(20))
    country_code = Column(String(2))
    country_name = Column(String(120))
    region_name = Column(String(160))
    city_name = Column(String(160))
    district_name = Column(String(160))
    neighborhood_name = Column(String(160))
    school_type = Column(String(120))
    expected_branch_count = Column(Integer)
    expected_student_count = Column(Integer)
    expected_teacher_count = Column(Integer)
    estimated_staff_users = Column(Integer)
    timezone = Column(String(80))
    draft_saved_at = Column(DateTime)
    submitted_at = Column(DateTime)
    reviewed_at = Column(DateTime)
    reviewed_by_user_id = Column(String(10))
    rejection_reason = Column(Text)
    billing_status = Column(String(30), nullable=False, default="not_started")
    selected_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), index=True)
    selected_billing_interval = Column(String(20))
    checkout_ready_at = Column(DateTime)
    payment_status = Column(String(30), nullable=False, default="pending")
    payment_confirmed_at = Column(DateTime)
    payment_failed_at = Column(DateTime)
    last_payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id"), index=True)
    last_meaningful_activity_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationBranch(Base):
    __tablename__ = "pending_organization_branches"
    __table_args__ = (
        Index("uq_pending_organization_branches_uuid", "branch_uuid", unique=True),
        Index("ix_pending_organization_branches_org", "pending_organization_id"),
        Index("ix_pending_organization_branches_order", "pending_organization_id", "sort_order"),
    )

    id = Column(Integer, primary_key=True)
    branch_uuid = Column(String(36), nullable=False, default=lambda: str(uuid.uuid4()))
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    branch_name = Column(String(160), nullable=False)
    location = Column(String(180))
    country_code = Column(String(2))
    country_name = Column(String(120))
    region_name = Column(String(160))
    city_name = Column(String(160))
    district_name = Column(String(160))
    neighborhood_name = Column(String(160))
    estimated_system_users = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    estimated_teachers = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    status = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationAcademicSetup(Base):
    __tablename__ = "pending_organization_academic_setup"
    __table_args__ = (
        Index("uq_pending_organization_academic_setup_org", "pending_organization_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, unique=True, index=True)
    first_academic_year_name = Column(String(40), nullable=False, default="")
    create_default_branch = Column(Boolean, nullable=False, default=False)
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationContact(Base):
    __tablename__ = "pending_organization_contacts"
    __table_args__ = (
        Index("ix_pending_organization_contacts_org", "pending_organization_id"),
        Index("ix_pending_organization_contacts_email_normalized", "email_normalized"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    contact_type = Column(String(30), nullable=False, default="owner")
    first_name = Column(String(120), nullable=False, default="")
    last_name = Column(String(120), nullable=False, default="")
    job_title = Column(String(120))
    email = Column(String(180), nullable=False, default="")
    email_normalized = Column(String(180))
    phone = Column(String(80))
    is_primary = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationProgress(Base):
    __tablename__ = "pending_organization_progress"
    __table_args__ = (
        Index("uq_pending_organization_progress_org", "pending_organization_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, unique=True, index=True)
    organization_profile_complete = Column(Boolean, nullable=False, default=False)
    branches_complete = Column(Boolean, nullable=False, default=False)
    academic_setup_complete = Column(Boolean, nullable=False, default=False)
    contacts_complete = Column(Boolean, nullable=False, default=False)
    review_complete = Column(Boolean, nullable=False, default=False)
    completion_percent = Column(Integer, nullable=False, default=0)
    last_completed_step = Column(String(40))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationEvent(Base):
    __tablename__ = "pending_organization_events"
    __table_args__ = (
        Index("ix_pending_organization_events_org", "pending_organization_id"),
        Index("ix_pending_organization_events_type", "event_type"),
        Index("ix_pending_organization_events_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    actor_saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), index=True)
    event_type = Column(String(40), nullable=False)
    details_json = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SaaSDemoRequest(Base):
    __tablename__ = "saas_demo_requests"
    __table_args__ = (
        Index("uq_saas_demo_requests_uuid", "request_uuid", unique=True),
        Index("ix_saas_demo_requests_requester", "requester_saas_account_id"),
        Index("ix_saas_demo_requests_organization", "pending_organization_id"),
        Index("ix_saas_demo_requests_workspace", "school_group_id"),
        Index("ix_saas_demo_requests_status", "status"),
        Index("ix_saas_demo_requests_submitted", "submitted_at"),
        Index("ix_saas_demo_requests_domain", "organization_domain_normalized"),
        Index(
            "uq_saas_demo_requests_pending_org",
            "pending_organization_id",
            unique=True,
            sqlite_where=text("status = 'pending_review'"),
            postgresql_where=text("status = 'pending_review'"),
        ),
        CheckConstraint(
            "status IN ('pending_review','approved','rejected','cancelled')",
            name="ck_saas_demo_requests_status",
        ),
        CheckConstraint(
            "workspace_classification_snapshot IN ('internal_sandbox','customer_demo','customer_paid')",
            name="ck_saas_demo_requests_classification",
        ),
        CheckConstraint(
            "commercial_state_snapshot IN ('provisioning','internal_sandbox_active','customer_demo_active','customer_paid_active','inactive','suspended','archived','manual_review')",
            name="ck_saas_demo_requests_commercial_state",
        ),
    )

    id = Column(Integer, primary_key=True)
    request_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    requester_saas_account_id = Column(
        Integer,
        ForeignKey("saas_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pending_organization_id = Column(
        Integer,
        ForeignKey("pending_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_group_id = Column(Integer, ForeignKey("school_groups.id", ondelete="SET NULL"), index=True)
    workspace_uuid_snapshot = Column(String(36))
    workspace_classification_snapshot = Column(String(32), nullable=False)
    commercial_state_snapshot = Column(String(40), nullable=False)
    entitlement_snapshot_json = Column(Text, nullable=False, default="{}")
    organization_domain_normalized = Column(String(180))
    status = Column(String(24), nullable=False, default="pending_review")
    rejection_reason = Column(Text)
    submitted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    approved_at = Column(DateTime)
    rejected_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    status_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSDemoDomainEligibility(Base):
    __tablename__ = "saas_demo_domain_eligibilities"
    __table_args__ = (
        Index("uq_saas_demo_domain_eligibilities_domain", "normalized_domain", unique=True),
        Index("ix_saas_demo_domain_eligibilities_demo_request", "demo_request_id"),
        Index("ix_saas_demo_domain_eligibilities_status", "status"),
        CheckConstraint(
            "status IN ('reserved','manual_review')",
            name="ck_saas_demo_domain_eligibilities_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    normalized_domain = Column(String(180), nullable=False, unique=True)
    demo_request_id = Column(
        Integer,
        ForeignKey("saas_demo_requests.id", ondelete="SET NULL"),
        unique=True,
        index=True,
    )
    status = Column(String(20), nullable=False, default="reserved")
    manual_review_reason = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSDemoRequestReview(Base):
    __tablename__ = "saas_demo_request_reviews"
    __table_args__ = (
        Index("uq_saas_demo_request_reviews_uuid", "review_uuid", unique=True),
        Index("uq_saas_demo_request_reviews_request", "demo_request_id", unique=True),
        Index("ix_saas_demo_request_reviews_reviewer", "reviewer_user_id"),
        Index("ix_saas_demo_request_reviews_decision", "decision"),
        CheckConstraint(
            "decision IN ('approved','rejected')",
            name="ck_saas_demo_request_reviews_decision",
        ),
        CheckConstraint(
            "decision != 'rejected' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_saas_demo_request_reviews_rejection_reason",
        ),
    )

    id = Column(Integer, primary_key=True)
    review_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    demo_request_id = Column(
        Integer,
        ForeignKey("saas_demo_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    reviewer_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    decision = Column(String(20), nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SaaSDemoRequestEvent(Base):
    __tablename__ = "saas_demo_request_events"
    __table_args__ = (
        Index("ix_saas_demo_request_events_request", "demo_request_id"),
        Index("ix_saas_demo_request_events_category", "event_category"),
        Index("ix_saas_demo_request_events_type", "event_type"),
        Index("ix_saas_demo_request_events_created", "created_at"),
        CheckConstraint(
            "event_category IN ('audit','notification')",
            name="ck_saas_demo_request_events_category",
        ),
        CheckConstraint(
            "event_type IN ('request_submitted','request_approved','request_rejected','request_cancelled','request_withdrawn')",
            name="ck_saas_demo_request_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('customer','platform_owner','system')",
            name="ck_saas_demo_request_events_actor_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    demo_request_id = Column(
        Integer,
        ForeignKey("saas_demo_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_category = Column(String(20), nullable=False)
    event_type = Column(String(40), nullable=False)
    actor_type = Column(String(24), nullable=False)
    actor_saas_account_id = Column(
        Integer,
        ForeignKey("saas_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    details_json = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SaaSDemoWorkspaceProvisioning(Base):
    __tablename__ = "saas_demo_workspace_provisioning"
    __table_args__ = (
        Index("uq_saas_demo_workspace_provisioning_uuid", "provisioning_uuid", unique=True),
        Index("uq_saas_demo_workspace_provisioning_request", "demo_request_id", unique=True),
        Index("uq_saas_demo_workspace_provisioning_group", "school_group_id", unique=True),
        Index(
            "uq_saas_demo_workspace_provisioning_entitlement",
            "workspace_entitlement_id",
            unique=True,
        ),
        Index(
            "uq_saas_demo_workspace_provisioning_tenant_link",
            "tenant_provisioning_link_id",
            unique=True,
        ),
        Index("ix_saas_demo_workspace_provisioning_status", "provisioning_status"),
        CheckConstraint(
            "provisioning_status IN ('provisioning','active','failed')",
            name="ck_saas_demo_workspace_provisioning_status",
        ),
        CheckConstraint(
            "lifecycle_processing_status IN ('pending','processing','failed','expired','converted')",
            name="ck_saas_demo_workspace_provisioning_lifecycle_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    provisioning_uuid = Column(
        String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    demo_request_id = Column(
        Integer,
        ForeignKey("saas_demo_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    school_group_id = Column(
        Integer, ForeignKey("school_groups.id", ondelete="SET NULL"), unique=True, index=True
    )
    workspace_entitlement_id = Column(
        Integer,
        ForeignKey("workspace_entitlements.id", ondelete="SET NULL"),
        unique=True,
        index=True,
    )
    tenant_provisioning_link_id = Column(
        Integer,
        ForeignKey("tenant_provisioning_links.id", ondelete="SET NULL"),
        unique=True,
        index=True,
    )
    triggered_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    provisioning_status = Column(String(24), nullable=False, default="provisioning")
    attempt_count = Column(Integer, nullable=False, default=0)
    result_code = Column(String(80))
    failure_reason = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    activated_at = Column(DateTime)
    failed_at = Column(DateTime)
    demo_expires_at = Column(DateTime(timezone=True))
    expiry_policy = Column(String(20), nullable=False, default="standard")
    reminder_due_at = Column(DateTime(timezone=True))
    reminder_sent_at = Column(DateTime(timezone=True))
    expired_at = Column(DateTime(timezone=True))
    lifecycle_processing_status = Column(String(24), nullable=False, default="pending")
    lifecycle_last_processed_at = Column(DateTime(timezone=True))
    lifecycle_failure_code = Column(String(80))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSDemoProvisioningEvent(Base):
    __tablename__ = "saas_demo_provisioning_events"
    __table_args__ = (
        Index("ix_saas_demo_provisioning_events_provisioning", "demo_provisioning_id"),
        Index("ix_saas_demo_provisioning_events_category", "event_category"),
        Index("ix_saas_demo_provisioning_events_type", "event_type"),
        Index("ix_saas_demo_provisioning_events_created", "created_at"),
        CheckConstraint(
            "event_category IN ('audit','notification')",
            name="ck_saas_demo_provisioning_events_category",
        ),
        CheckConstraint(
            "event_type IN ('provisioning_started','provisioning_completed','provisioning_failed','activation_completed')",
            name="ck_saas_demo_provisioning_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('platform_owner','system')",
            name="ck_saas_demo_provisioning_events_actor_type",
        ),
    )

    id = Column(Integer, primary_key=True)
    demo_provisioning_id = Column(
        Integer,
        ForeignKey("saas_demo_workspace_provisioning.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_category = Column(String(20), nullable=False)
    event_type = Column(String(40), nullable=False)
    actor_type = Column(String(24), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    event_status = Column(String(20), nullable=False, default="ok")
    details_json = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SaaSDemoLifecycleEvent(Base):
    __tablename__ = "saas_demo_lifecycle_events"
    __table_args__ = (
        Index("uq_saas_demo_lifecycle_events_dedup", "deduplication_key", unique=True),
        Index("ix_saas_demo_lifecycle_events_provisioning", "demo_provisioning_id"),
        Index("ix_saas_demo_lifecycle_events_type", "event_type"),
        Index("ix_saas_demo_lifecycle_events_created", "created_at"),
        CheckConstraint(
            "event_type IN ('reminder_became_due','reminder_notification_created',"
            "'expiration_processing_started','demo_expired','workspace_suspended',"
            "'access_blocked','lifecycle_processing_failed')",
            name="ck_saas_demo_lifecycle_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('system','tenant_user')",
            name="ck_saas_demo_lifecycle_events_actor_type",
        ),
        CheckConstraint(
            "event_status IN ('ok','failed')",
            name="ck_saas_demo_lifecycle_events_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    demo_provisioning_id = Column(
        Integer,
        ForeignKey("saas_demo_workspace_provisioning.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(48), nullable=False)
    actor_type = Column(String(24), nullable=False, default="system")
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    event_status = Column(String(20), nullable=False, default="ok")
    reason_code = Column(String(80))
    deduplication_key = Column(String(180), nullable=False, unique=True)
    details_json = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SaaSDemoLifecycleNotification(Base):
    __tablename__ = "saas_demo_lifecycle_notifications"
    __table_args__ = (
        Index(
            "uq_saas_demo_lifecycle_notifications_dedup",
            "deduplication_key",
            unique=True,
        ),
        Index(
            "ix_saas_demo_lifecycle_notifications_provisioning",
            "demo_provisioning_id",
        ),
        Index(
            "ix_saas_demo_lifecycle_notifications_saas_account",
            "recipient_saas_account_id",
        ),
        Index(
            "ix_saas_demo_lifecycle_notifications_user",
            "recipient_user_id",
        ),
        CheckConstraint(
            "notification_type IN ('expiration_reminder','demo_expired','demo_reactivated',"
            "'demo_expiry_changed','manual_final_day_reminder','demo_access_profile_changed')",
            name="ck_saas_demo_lifecycle_notifications_type",
        ),
        CheckConstraint(
            "recipient_type IN ('saas_account','platform_owner')",
            name="ck_saas_demo_lifecycle_notifications_recipient",
        ),
        CheckConstraint(
            "(recipient_type = 'saas_account' AND recipient_saas_account_id IS NOT NULL "
            "AND recipient_user_id IS NULL) OR "
            "(recipient_type = 'platform_owner' AND recipient_user_id IS NOT NULL "
            "AND recipient_saas_account_id IS NULL)",
            name="ck_saas_demo_lifecycle_notifications_recipient_target",
        ),
    )

    id = Column(Integer, primary_key=True)
    demo_provisioning_id = Column(
        Integer,
        ForeignKey("saas_demo_workspace_provisioning.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type = Column(String(40), nullable=False)
    recipient_type = Column(String(24), nullable=False)
    recipient_saas_account_id = Column(
        Integer,
        ForeignKey("saas_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    recipient_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    title = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    deduplication_key = Column(String(180), nullable=False, unique=True)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SaaSDemoEmailDelivery(Base):
    __tablename__ = "saas_demo_email_deliveries"
    __table_args__ = (
        Index("uq_saas_demo_email_deliveries_uuid", "delivery_uuid", unique=True),
        Index("uq_saas_demo_email_deliveries_dedup", "deduplication_key", unique=True),
        Index("ix_saas_demo_email_deliveries_request", "demo_request_id"),
        Index("ix_saas_demo_email_deliveries_provisioning", "demo_provisioning_id"),
        Index("ix_saas_demo_email_deliveries_status_created", "status", "created_at"),
        CheckConstraint(
            "email_type IN ('request_received','demo_approved','demo_declined',"
            "'day_six_reminder','demo_expired','subscription_invitation',"
            "'demo_reactivated','demo_expiry_changed','manual_final_day_reminder',"
            "'demo_access_profile_changed')",
            name="ck_saas_demo_email_deliveries_type",
        ),
        CheckConstraint(
            "status IN ('pending','processing','sent','failed')",
            name="ck_saas_demo_email_deliveries_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    delivery_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    demo_request_id = Column(
        Integer, ForeignKey("saas_demo_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    demo_provisioning_id = Column(
        Integer, ForeignKey("saas_demo_workspace_provisioning.id", ondelete="CASCADE"), index=True
    )
    email_type = Column(String(40), nullable=False)
    recipient_email = Column(String(320), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    deduplication_key = Column(String(180), nullable=False, unique=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_attempt_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    provider_message_id = Column(String(180))
    failure_code = Column(String(80))
    payload_json = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DemoAccessPolicy(Base):
    __tablename__ = "demo_access_policies"
    __table_args__ = (
        Index(
            "uq_demo_access_policies_workspace_default",
            "school_group_id",
            unique=True,
            sqlite_where=text("branch_id IS NULL"),
            postgresql_where=text("branch_id IS NULL"),
        ),
        Index(
            "uq_demo_access_policies_branch",
            "school_group_id",
            "branch_id",
            unique=True,
            sqlite_where=text("branch_id IS NOT NULL"),
            postgresql_where=text("branch_id IS NOT NULL"),
        ),
        Index("ix_demo_access_policies_group", "school_group_id"),
        Index("ix_demo_access_policies_branch", "branch_id"),
        CheckConstraint(
            "access_profile IN ('standard','full','custom')",
            name="ck_demo_access_policies_profile",
        ),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    access_profile = Column(String(20), nullable=False, default="standard")
    product_features_json = Column(Text, nullable=False, default="[]")
    ai_features_json = Column(Text, nullable=False, default="[]")
    ai_allowances_json = Column(Text, nullable=False, default="{}")
    unrestricted_ai_features_json = Column(Text, nullable=False, default="[]")
    reason = Column(Text, nullable=False)
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DemoOperationAudit(Base):
    __tablename__ = "demo_operation_audits"
    __table_args__ = (
        Index(
            "uq_demo_operation_audits_operation",
            "school_group_id",
            "action_type",
            "operation_key",
            unique=True,
        ),
        Index("ix_demo_operation_audits_group", "school_group_id"),
        Index("ix_demo_operation_audits_provisioning", "demo_provisioning_id"),
        Index("ix_demo_operation_audits_actor", "actor_user_id"),
        Index("ix_demo_operation_audits_created", "created_at"),
        CheckConstraint(
            "result_status IN ('success','failed','blocked','deduplicated')",
            name="ck_demo_operation_audits_result",
        ),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    demo_request_id = Column(Integer, ForeignKey("saas_demo_requests.id"), nullable=False, index=True)
    demo_provisioning_id = Column(
        Integer, ForeignKey("saas_demo_workspace_provisioning.id"), nullable=False, index=True
    )
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action_type = Column(String(60), nullable=False)
    reason = Column(Text)
    previous_values_json = Column(Text, nullable=False, default="{}")
    new_values_json = Column(Text, nullable=False, default="{}")
    result_status = Column(String(20), nullable=False)
    email_delivery_ids_json = Column(Text, nullable=False, default="[]")
    notification_ids_json = Column(Text, nullable=False, default="[]")
    operation_key = Column(String(120), nullable=False)
    failure_code = Column(String(80))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class SaaSDemoToPaidConversion(Base):
    __tablename__ = "saas_demo_to_paid_conversions"
    __table_args__ = (
        Index("uq_saas_demo_to_paid_conversions_uuid", "conversion_uuid", unique=True),
        Index("uq_saas_demo_to_paid_conversions_request", "demo_request_id", unique=True),
        Index(
            "uq_saas_demo_to_paid_conversions_provisioning",
            "demo_provisioning_id",
            unique=True,
        ),
        Index("uq_saas_demo_to_paid_conversions_group", "school_group_id", unique=True),
        Index("ix_saas_demo_to_paid_conversions_contract", "subscription_contract_id"),
        Index("ix_saas_demo_to_paid_conversions_subscription", "payment_subscription_id"),
        Index("ix_saas_demo_to_paid_conversions_status", "status"),
        CheckConstraint(
            "status IN ('requested','processing','completed','failed')",
            name="ck_saas_demo_to_paid_conversions_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    conversion_uuid = Column(
        String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    demo_request_id = Column(
        Integer,
        ForeignKey("saas_demo_requests.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    demo_provisioning_id = Column(
        Integer,
        ForeignKey("saas_demo_workspace_provisioning.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    school_group_id = Column(
        Integer,
        ForeignKey("school_groups.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    pending_organization_id = Column(
        Integer,
        ForeignKey("pending_organizations.id"),
        nullable=False,
        index=True,
    )
    requested_by_saas_account_id = Column(
        Integer,
        ForeignKey("saas_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    subscription_contract_id = Column(
        Integer,
        ForeignKey("subscription_contracts.id"),
        unique=True,
        index=True,
    )
    payment_subscription_id = Column(
        Integer,
        ForeignKey("payment_subscriptions.id"),
        unique=True,
        index=True,
    )
    previous_demo_entitlement_id = Column(
        Integer,
        ForeignKey("workspace_entitlements.id"),
        index=True,
    )
    paid_workspace_entitlement_id = Column(
        Integer,
        ForeignKey("workspace_entitlements.id"),
        unique=True,
        index=True,
    )
    status = Column(String(24), nullable=False, default="requested")
    attempt_count = Column(Integer, nullable=False, default=0)
    reason_code = Column(String(80))
    failure_reason = Column(Text)
    requested_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    failed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class SaaSDemoConversionEvent(Base):
    __tablename__ = "saas_demo_conversion_events"
    __table_args__ = (
        Index("ix_saas_demo_conversion_events_conversion", "demo_conversion_id"),
        Index("ix_saas_demo_conversion_events_category", "event_category"),
        Index("ix_saas_demo_conversion_events_type", "event_type"),
        Index("ix_saas_demo_conversion_events_created", "created_at"),
        CheckConstraint(
            "event_category IN ('audit','notification')",
            name="ck_saas_demo_conversion_events_category",
        ),
        CheckConstraint(
            "event_type IN ('conversion_requested','conversion_started',"
            "'conversion_completed','conversion_failed')",
            name="ck_saas_demo_conversion_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('customer','system')",
            name="ck_saas_demo_conversion_events_actor_type",
        ),
        CheckConstraint(
            "event_status IN ('ok','failed')",
            name="ck_saas_demo_conversion_events_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    demo_conversion_id = Column(
        Integer,
        ForeignKey("saas_demo_to_paid_conversions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_category = Column(String(20), nullable=False)
    event_type = Column(String(40), nullable=False)
    actor_type = Column(String(24), nullable=False)
    actor_saas_account_id = Column(
        Integer,
        ForeignKey("saas_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    event_status = Column(String(20), nullable=False, default="ok")
    reason_code = Column(String(80))
    details_json = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class PendingOrganizationNote(Base):
    __tablename__ = "pending_organization_notes"
    __table_args__ = (
        Index("ix_pending_organization_notes_org", "pending_organization_id"),
        Index("ix_pending_organization_notes_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    author_type = Column(String(20), nullable=False, default="owner")
    author_ref = Column(String(80))
    note = Column(Text, nullable=False, default="")
    is_internal = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        Index("uq_subscription_plans_code", "plan_code", unique=True),
        Index("ix_subscription_plans_active", "is_active"),
        Index("ix_subscription_plans_public", "is_public"),
        Index("ix_subscription_plans_sort_order", "sort_order"),
    )

    id = Column(Integer, primary_key=True)
    plan_code = Column(String(40), nullable=False, unique=True, index=True)
    plan_name = Column(String(120), nullable=False)
    plan_family = Column(String(80))
    description = Column(Text)
    badge_text = Column(String(60))
    is_most_popular = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_public = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    max_branches = Column(Integer)
    max_staff_users = Column(Integer)
    max_system_users = Column(Integer)
    max_teachers = Column(Integer)
    ai_enabled = Column(Boolean, nullable=False, default=False)
    multi_branch_enabled = Column(Boolean, nullable=False, default=False)
    advanced_reporting_enabled = Column(Boolean, nullable=False, default=False)
    priority_support = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PromoCode(Base):
    __tablename__ = "promo_codes"
    __table_args__ = (
        Index("uq_promo_codes_uuid", "promo_uuid", unique=True),
        Index("uq_promo_codes_lookup_hash", "code_lookup_hash", unique=True),
        Index("uq_promo_codes_supersedes", "supersedes_promo_code_id", unique=True),
        Index("ix_promo_codes_status", "status"),
        Index("ix_promo_codes_plan", "subscription_plan_id"),
        Index("ix_promo_codes_scope", "scope_type"),
        Index("ix_promo_codes_school_group", "school_group_id"),
        Index("ix_promo_codes_pending_org", "pending_organization_id"),
        Index("ix_promo_codes_creator", "created_by_user_id"),
        Index("ix_promo_codes_created", "created_at"),
        Index("ix_promo_codes_validity", "valid_from", "redemption_deadline"),
        CheckConstraint(
            "status IN ('draft','active','paused','revoked')",
            name="ck_promo_codes_status",
        ),
        CheckConstraint(
            "benefit_type = 'full_access'",
            name="ck_promo_codes_benefit_type",
        ),
        CheckConstraint(
            "scope_type IN ('global','organization','pending_organization','account_email','email_domain')",
            name="ck_promo_codes_scope_type",
        ),
        CheckConstraint(
            "max_branches > 0 AND max_system_users > 0 AND max_teachers > 0",
            name="ck_promo_codes_positive_capacity",
        ),
        CheckConstraint(
            "definition_version > 0",
            name="ck_promo_codes_definition_version",
        ),
        CheckConstraint(
            "max_total_redemptions > 0 AND grace_period_days >= 0",
            name="ck_promo_codes_redemption_policy",
        ),
        CheckConstraint(
            "(fixed_access_expires_at IS NOT NULL AND access_duration_days IS NULL) OR "
            "(fixed_access_expires_at IS NULL AND access_duration_days > 0)",
            name="ck_promo_codes_expiry_policy",
        ),
        CheckConstraint(
            "valid_from < redemption_deadline",
            name="ck_promo_codes_validity_order",
        ),
        CheckConstraint(
            "fixed_access_expires_at IS NULL OR fixed_access_expires_at > redemption_deadline",
            name="ck_promo_codes_fixed_expiry_order",
        ),
        CheckConstraint(
            "scope_type <> 'global' OR (school_group_id IS NULL AND pending_organization_id IS NULL "
            "AND intended_account_email_normalized IS NULL AND permitted_email_domain_normalized IS NULL)",
            name="ck_promo_codes_global_scope",
        ),
        CheckConstraint(
            "(scope_type <> 'organization' OR school_group_id IS NOT NULL OR scope_target_snapshot IS NOT NULL) AND "
            "(scope_type <> 'pending_organization' OR pending_organization_id IS NOT NULL OR scope_target_snapshot IS NOT NULL) AND "
            "(scope_type <> 'account_email' OR intended_account_email_normalized IS NOT NULL) AND "
            "(scope_type <> 'email_domain' OR permitted_email_domain_normalized IS NOT NULL)",
            name="ck_promo_codes_primary_scope_target",
        ),
    )

    id = Column(Integer, primary_key=True)
    promo_uuid = Column(
        String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4())
    )
    code_lookup_hash = Column(String(64), nullable=False, unique=True)
    code_hash_key_id = Column(String(40), nullable=False)
    code_display_prefix = Column(String(16), nullable=False)
    code_display_suffix = Column(String(12), nullable=False)
    title = Column(String(160), nullable=False)
    internal_purpose = Column(Text)
    status = Column(String(20), nullable=False, default="draft")
    definition_version = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime(timezone=True))
    paused_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    revocation_reason = Column(Text)
    benefit_type = Column(String(32), nullable=False, default="full_access")
    subscription_plan_id = Column(
        Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True
    )
    max_branches = Column(Integer, nullable=False)
    max_system_users = Column(Integer, nullable=False)
    max_teachers = Column(Integer, nullable=False)
    scope_type = Column(String(32), nullable=False, default="global")
    school_group_id = Column(
        Integer, ForeignKey("school_groups.id", ondelete="SET NULL"), index=True
    )
    pending_organization_id = Column(
        Integer, ForeignKey("pending_organizations.id", ondelete="SET NULL"), index=True
    )
    intended_account_email_normalized = Column(String(180), index=True)
    permitted_email_domain_normalized = Column(String(180), index=True)
    scope_target_snapshot = Column(String(255))
    transferable = Column(Boolean, nullable=False, default=False)
    one_redemption_per_organization = Column(Boolean, nullable=False, default=True)
    max_total_redemptions = Column(Integer, nullable=False, default=1)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    redemption_deadline = Column(DateTime(timezone=True), nullable=False)
    fixed_access_expires_at = Column(DateTime(timezone=True))
    access_duration_days = Column(Integer)
    grace_period_days = Column(Integer, nullable=False, default=0)
    supersedes_promo_code_id = Column(
        Integer, ForeignKey("promo_codes.id", ondelete="SET NULL"), unique=True, index=True
    )
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    updated_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class PromoCodeBranchRestriction(Base):
    __tablename__ = "promo_code_branch_restrictions"
    __table_args__ = (
        Index(
            "uq_promo_code_branch_restrictions_promo_branch",
            "promo_code_id",
            "branch_id_snapshot",
            unique=True,
        ),
        Index("ix_promo_code_branch_restrictions_promo", "promo_code_id"),
        Index("ix_promo_code_branch_restrictions_branch", "branch_id"),
    )

    id = Column(Integer, primary_key=True)
    promo_code_id = Column(
        Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id = Column(
        Integer, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    branch_id_snapshot = Column(Integer, nullable=False)
    branch_name_snapshot = Column(String(160), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class PromoCodeAuditEvent(Base):
    __tablename__ = "promo_code_audit_events"
    __table_args__ = (
        Index(
            "uq_promo_code_audit_events_operation",
            "promo_uuid_snapshot",
            "action",
            "operation_key",
            unique=True,
        ),
        Index("ix_promo_code_audit_events_promo", "promo_code_id"),
        Index("ix_promo_code_audit_events_actor", "actor_user_id"),
        Index("ix_promo_code_audit_events_created", "created_at"),
        CheckConstraint(
            "result IN ('success','failed','blocked','deduplicated')",
            name="ck_promo_code_audit_events_result",
        ),
        CheckConstraint(
            "action IN ('create','edit','activate','pause','revoke','duplicate','replace')",
            name="ck_promo_code_audit_events_action",
        ),
    )

    id = Column(Integer, primary_key=True)
    promo_code_id = Column(
        Integer, ForeignKey("promo_codes.id", ondelete="SET NULL"), index=True
    )
    promo_uuid_snapshot = Column(String(36), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = Column(String(30), nullable=False)
    result = Column(String(20), nullable=False)
    reason = Column(Text)
    previous_values_json = Column(Text, nullable=False, default="{}")
    new_values_json = Column(Text, nullable=False, default="{}")
    operation_key = Column(String(120), nullable=False)
    request_correlation_id = Column(String(120))
    failure_code = Column(String(80))
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class PromoActivationSession(Base):
    __tablename__ = "promo_activation_sessions"
    __table_args__ = (
        Index("uq_promo_activation_sessions_uuid", "activation_uuid", unique=True),
        Index("uq_promo_activation_sessions_idempotency", "idempotency_key", unique=True),
        Index("ix_promo_activation_sessions_promo", "promo_code_id"),
        Index("ix_promo_activation_sessions_pending_org", "pending_organization_id"),
        Index("ix_promo_activation_sessions_group", "school_group_id"),
        Index("ix_promo_activation_sessions_account", "saas_account_id"),
        Index("ix_promo_activation_sessions_status", "status"),
        Index("ix_promo_activation_sessions_stage", "stage"),
        Index(
            "uq_promo_activation_sessions_open_pending_org",
            "pending_organization_id",
            unique=True,
            sqlite_where=text("status = 'open' AND pending_organization_id IS NOT NULL"),
            postgresql_where=text("status = 'open' AND pending_organization_id IS NOT NULL"),
        ),
        Index(
            "uq_promo_activation_sessions_open_group",
            "school_group_id",
            unique=True,
            sqlite_where=text("status = 'open' AND school_group_id IS NOT NULL"),
            postgresql_where=text("status = 'open' AND school_group_id IS NOT NULL"),
        ),
        CheckConstraint(
            "context_type IN ('onboarding','existing_organization')",
            name="ck_promo_activation_sessions_context",
        ),
        CheckConstraint(
            "status IN ('open','activated','cancelled','failed')",
            name="ck_promo_activation_sessions_status",
        ),
        CheckConstraint(
            "stage IN ('promo_validated','branch_selection_required','staff_reconciliation_required',"
            "'teacher_reconciliation_required','review_required','activation_processing','activated','failed','cancelled')",
            name="ck_promo_activation_sessions_stage",
        ),
        CheckConstraint(
            "pending_organization_id IS NOT NULL OR school_group_id IS NOT NULL",
            name="ck_promo_activation_sessions_anchor",
        ),
        CheckConstraint(
            "observed_branch_count >= 0 AND observed_staff_users >= 0 AND observed_teachers >= 0",
            name="ck_promo_activation_sessions_nonnegative_usage",
        ),
    )

    id = Column(Integer, primary_key=True)
    activation_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False, index=True)
    promo_definition_version = Column(Integer, nullable=False)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    operational_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    context_type = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="open")
    stage = Column(String(48), nullable=False, default="promo_validated")
    idempotency_key = Column(String(120), nullable=False, unique=True)
    request_correlation_id = Column(String(120))
    masked_promo_reference = Column(String(48), nullable=False)
    observed_branch_count = Column(Integer, nullable=False, default=0)
    observed_staff_users = Column(Integer, nullable=False, default=0)
    observed_teachers = Column(Integer, nullable=False, default=0)
    last_failure_code = Column(String(80))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    activated_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow, onupdate=_aware_utcnow)


class PromoActivationBranchSelection(Base):
    __tablename__ = "promo_activation_branch_selections"
    __table_args__ = (
        Index(
            "uq_promo_activation_branch_selection_pending",
            "activation_session_id",
            "pending_branch_id",
            unique=True,
        ),
        Index(
            "uq_promo_activation_branch_selection_operational",
            "activation_session_id",
            "branch_id",
            unique=True,
        ),
        Index("ix_promo_activation_branch_selection_session", "activation_session_id"),
        CheckConstraint(
            "(pending_branch_id IS NOT NULL AND branch_id IS NULL) OR "
            "(pending_branch_id IS NULL AND branch_id IS NOT NULL)",
            name="ck_promo_activation_branch_selection_target",
        ),
    )

    id = Column(Integer, primary_key=True)
    activation_session_id = Column(
        Integer, ForeignKey("promo_activation_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pending_branch_id = Column(Integer, ForeignKey("pending_organization_branches.id"), index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    branch_identity_snapshot = Column(String(36), nullable=False)
    branch_name_snapshot = Column(String(160), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow)


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        Index("uq_promo_redemptions_uuid", "redemption_uuid", unique=True),
        Index("uq_promo_redemptions_idempotency", "idempotency_key", unique=True),
        Index("uq_promo_redemptions_activation", "activation_session_id", unique=True),
        Index("ix_promo_redemptions_promo", "promo_code_id"),
        Index("ix_promo_redemptions_group", "school_group_id"),
        Index("ix_promo_redemptions_pending_org", "pending_organization_id"),
        Index("ix_promo_redemptions_account", "redeeming_saas_account_id"),
        CheckConstraint("commercial_source = 'promo'", name="ck_promo_redemptions_source"),
        CheckConstraint("status = 'completed'", name="ck_promo_redemptions_status"),
        CheckConstraint(
            "allowed_branches > 0 AND allowed_staff_users > 0 AND allowed_teachers > 0",
            name="ck_promo_redemptions_positive_capacity",
        ),
        CheckConstraint("effective_to > effective_from", name="ck_promo_redemptions_effective_window"),
    )

    id = Column(Integer, primary_key=True)
    redemption_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    activation_session_id = Column(Integer, ForeignKey("promo_activation_sessions.id"), nullable=False, unique=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False, index=True)
    promo_definition_version = Column(Integer, nullable=False)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), index=True)
    redeeming_saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    redeeming_operational_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    redeemed_at = Column(DateTime(timezone=True), nullable=False)
    commercial_source = Column(String(20), nullable=False, default="promo")
    status = Column(String(20), nullable=False, default="completed")
    idempotency_key = Column(String(120), nullable=False, unique=True)
    request_correlation_id = Column(String(120))
    masked_promo_reference = Column(String(48), nullable=False)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    plan_code_snapshot = Column(String(40), nullable=False)
    plan_name_snapshot = Column(String(120), nullable=False)
    allowed_branches = Column(Integer, nullable=False)
    allowed_staff_users = Column(Integer, nullable=False)
    allowed_teachers = Column(Integer, nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=False)
    grace_period_days = Column(Integer, nullable=False, default=0)
    scope_type_snapshot = Column(String(32), nullable=False)
    scope_snapshot_json = Column(Text, nullable=False, default="{}")
    definition_snapshot_json = Column(Text, nullable=False, default="{}")
    immutable_snapshot_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow)


class PromoGrant(Base):
    __tablename__ = "promo_grants"
    __table_args__ = (
        Index("uq_promo_grants_uuid", "grant_uuid", unique=True),
        Index("uq_promo_grants_redemption", "promo_redemption_id", unique=True),
        Index("ix_promo_grants_group", "school_group_id"),
        Index("ix_promo_grants_plan", "plan_id"),
        Index("ix_promo_grants_status", "status"),
        Index("ix_promo_grants_effective_to", "effective_to"),
        Index(
            "uq_promo_grants_active_group",
            "school_group_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("source = 'promo'", name="ck_promo_grants_source"),
        CheckConstraint(
            "status IN ('active','expired','revoked','superseded','converted_to_paid')",
            name="ck_promo_grants_status",
        ),
        CheckConstraint(
            "allowed_branches > 0 AND allowed_staff_users > 0 AND allowed_teachers > 0",
            name="ck_promo_grants_positive_capacity",
        ),
        CheckConstraint("effective_to > effective_from", name="ck_promo_grants_effective_window"),
    )

    id = Column(Integer, primary_key=True)
    grant_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    promo_redemption_id = Column(Integer, ForeignKey("promo_redemptions.id"), nullable=False, unique=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    plan_code_snapshot = Column(String(40), nullable=False)
    plan_name_snapshot = Column(String(120), nullable=False)
    source = Column(String(20), nullable=False, default="promo")
    allowed_branches = Column(Integer, nullable=False)
    allowed_staff_users = Column(Integer, nullable=False)
    allowed_teachers = Column(Integer, nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=False)
    grace_period_days = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="active")
    definition_snapshot_json = Column(Text, nullable=False, default="{}")
    capacity_snapshot_json = Column(Text, nullable=False, default="{}")
    scope_snapshot_json = Column(Text, nullable=False, default="{}")
    immutable_snapshot_hash = Column(String(64), nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=False)
    expired_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    supersedes_grant_id = Column(Integer, ForeignKey("promo_grants.id"), index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow)


class PromoGrantBranchAssignment(Base):
    __tablename__ = "promo_grant_branch_assignments"
    __table_args__ = (
        Index(
            "uq_promo_grant_branch_assignments_grant_branch",
            "promo_grant_id",
            "branch_id",
            unique=True,
        ),
        Index("ix_promo_grant_branch_assignments_group", "school_group_id"),
        Index("ix_promo_grant_branch_assignments_branch", "branch_id"),
    )

    id = Column(Integer, primary_key=True)
    promo_grant_id = Column(Integer, ForeignKey("promo_grants.id"), nullable=False, index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, index=True)
    branch_identity_snapshot = Column(String(36), nullable=False)
    branch_name_snapshot = Column(String(160), nullable=False)
    assigned_by_saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False)
    assignment_reason = Column(String(80), nullable=False, default="promo_activation")
    assigned_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow)


class PromoRedemptionEvent(Base):
    __tablename__ = "promo_redemption_events"
    __table_args__ = (
        Index("uq_promo_redemption_events_operation", "operation_key", "event_type", unique=True),
        Index("ix_promo_redemption_events_promo", "promo_code_id"),
        Index("ix_promo_redemption_events_session", "activation_session_id"),
        Index("ix_promo_redemption_events_redemption", "promo_redemption_id"),
        Index("ix_promo_redemption_events_grant", "promo_grant_id"),
        Index("ix_promo_redemption_events_account", "actor_saas_account_id"),
        Index("ix_promo_redemption_events_created", "created_at"),
        CheckConstraint(
            "result IN ('success','failed','blocked','deduplicated')",
            name="ck_promo_redemption_events_result",
        ),
    )

    id = Column(Integer, primary_key=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), index=True)
    activation_session_id = Column(Integer, ForeignKey("promo_activation_sessions.id"), index=True)
    promo_redemption_id = Column(Integer, ForeignKey("promo_redemptions.id"), index=True)
    promo_grant_id = Column(Integer, ForeignKey("promo_grants.id"), index=True)
    actor_saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), index=True)
    actor_operational_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    event_type = Column(String(48), nullable=False)
    result = Column(String(20), nullable=False)
    failure_code = Column(String(80))
    operation_key = Column(String(120), nullable=False)
    request_correlation_id = Column(String(120))
    details_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_aware_utcnow)


class EntitlementDefinition(Base):
    __tablename__ = "entitlement_definitions"
    __table_args__ = (
        Index("uq_entitlement_definitions_key", "key", unique=True),
        Index("ix_entitlement_definitions_active", "active"),
    )

    id = Column(Integer, primary_key=True)
    key = Column(String(120), nullable=False, unique=True, index=True)
    display_name = Column(String(160), nullable=False)
    category = Column(String(60), nullable=False)
    scope = Column(String(40), nullable=False, default="organization")
    value_type = Column(String(20), nullable=False, default="boolean")
    description = Column(Text)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PlanEntitlement(Base):
    __tablename__ = "plan_entitlements"
    __table_args__ = (
        Index(
            "uq_plan_entitlements_plan_definition",
            "subscription_plan_id",
            "entitlement_definition_id",
            unique=True,
        ),
        Index("ix_plan_entitlements_plan", "subscription_plan_id"),
        Index("ix_plan_entitlements_definition", "entitlement_definition_id"),
        Index("ix_plan_entitlements_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    subscription_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    entitlement_definition_id = Column(Integer, ForeignKey("entitlement_definitions.id"), nullable=False, index=True)
    value = Column(Text)
    status = Column(String(40), nullable=False, default="owner_approval_required")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkspaceEntitlement(Base):
    __tablename__ = "workspace_entitlements"
    __table_args__ = (
        Index("uq_workspace_entitlements_uuid", "entitlement_uuid", unique=True),
        Index("ix_workspace_entitlements_group", "school_group_id"),
        Index("ix_workspace_entitlements_type", "entitlement_type"),
        Index("ix_workspace_entitlements_status", "status"),
        Index("ix_workspace_entitlements_subscription", "payment_subscription_id"),
        Index("ix_workspace_entitlements_promo_grant", "promo_grant_id"),
        Index(
            "uq_workspace_entitlements_active_group",
            "school_group_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint(
            "entitlement_type IN ('internal_sandbox','demo','paid','promo')",
            name="ck_workspace_entitlements_type",
        ),
        CheckConstraint(
            "status IN ('pending','active','inactive','suspended','ended')",
            name="ck_workspace_entitlements_status",
        ),
        CheckConstraint(
            "source IN ('system','migration','subscription','platform','promo')",
            name="ck_workspace_entitlements_source",
        ),
        CheckConstraint(
            "(entitlement_type = 'paid' AND payment_subscription_id IS NOT NULL AND promo_grant_id IS NULL) OR "
            "(entitlement_type = 'promo' AND promo_grant_id IS NOT NULL AND payment_subscription_id IS NULL) OR "
            "(entitlement_type IN ('internal_sandbox','demo') AND payment_subscription_id IS NULL AND promo_grant_id IS NULL)",
            name="ck_workspace_entitlements_commercial_reference",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="ck_workspace_entitlements_effective_window",
        ),
    )

    id = Column(Integer, primary_key=True)
    entitlement_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    entitlement_type = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    source = Column(String(20), nullable=False, default="system")
    payment_subscription_id = Column(Integer, ForeignKey("payment_subscriptions.id"), index=True)
    promo_grant_id = Column(Integer, ForeignKey("promo_grants.id"), index=True)
    effective_from = Column(DateTime)
    effective_to = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkspaceEntitlementValue(Base):
    __tablename__ = "workspace_entitlement_values"
    __table_args__ = (
        Index(
            "uq_workspace_entitlement_values_definition",
            "workspace_entitlement_id",
            "entitlement_definition_id",
            unique=True,
        ),
        Index("ix_workspace_entitlement_values_workspace", "workspace_entitlement_id"),
        Index("ix_workspace_entitlement_values_definition", "entitlement_definition_id"),
        Index("ix_workspace_entitlement_values_status", "status"),
        CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_workspace_entitlement_values_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    workspace_entitlement_id = Column(
        Integer, ForeignKey("workspace_entitlements.id"), nullable=False, index=True
    )
    entitlement_definition_id = Column(
        Integer, ForeignKey("entitlement_definitions.id"), nullable=False, index=True
    )
    value = Column(Text)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIFeatureUsageCounter(Base):
    __tablename__ = "ai_feature_usage_counters"
    __table_args__ = (
        Index(
            "uq_ai_feature_usage_counter_scope",
            "school_group_id",
            "feature_key",
            "metric_context",
            unique=True,
        ),
        Index("ix_ai_feature_usage_counters_group", "school_group_id"),
        Index("ix_ai_feature_usage_counters_feature", "feature_key"),
        CheckConstraint(
            "metric_context IN ('internal_sandbox','demo','paid')",
            name="ck_ai_feature_usage_counters_context",
        ),
        CheckConstraint(
            "workspace_classification IN ('internal_sandbox','customer_demo','customer_paid')",
            name="ck_ai_feature_usage_counters_classification",
        ),
        CheckConstraint(
            "successful_uses >= 0",
            name="ck_ai_feature_usage_counters_nonnegative",
        ),
        CheckConstraint(
            "reserved_uses >= 0",
            name="ck_ai_feature_usage_counters_reserved_nonnegative",
        ),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    feature_key = Column(String(80), nullable=False)
    metric_context = Column(String(24), nullable=False)
    workspace_classification = Column(String(32), nullable=False)
    plan_code = Column(String(40))
    successful_uses = Column(Integer, nullable=False, default=0)
    reserved_uses = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AIFeatureUsageEvent(Base):
    __tablename__ = "ai_feature_usage_events"
    __table_args__ = (
        Index(
            "uq_ai_feature_usage_event_operation",
            "school_group_id",
            "feature_key",
            "metric_context",
            "operation_key",
            unique=True,
        ),
        Index("ix_ai_feature_usage_events_group_feature", "school_group_id", "feature_key"),
        Index("ix_ai_feature_usage_events_created", "created_at"),
        CheckConstraint(
            "metric_context IN ('internal_sandbox','demo','paid')",
            name="ck_ai_feature_usage_events_context",
        ),
        CheckConstraint(
            "workspace_classification IN ('internal_sandbox','customer_demo','customer_paid')",
            name="ck_ai_feature_usage_events_classification",
        ),
        CheckConstraint(
            "result_status IN ('pending','successful','failed')",
            name="ck_ai_feature_usage_events_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    feature_key = Column(String(80), nullable=False)
    metric_context = Column(String(24), nullable=False)
    workspace_classification = Column(String(32), nullable=False)
    plan_code = Column(String(40))
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    operation_key = Column(String(120), nullable=False)
    result_status = Column(String(20), nullable=False, default="pending")
    completed_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BranchEntitlement(Base):
    __tablename__ = "branch_entitlements"
    __table_args__ = (
        Index("uq_branch_entitlements_uuid", "branch_entitlement_uuid", unique=True),
        Index("uq_branch_entitlements_branch", "branch_id", unique=True),
        Index("ix_branch_entitlements_group", "school_group_id"),
        Index("ix_branch_entitlements_workspace", "workspace_entitlement_id"),
        Index("ix_branch_entitlements_mode", "entitlement_mode"),
        CheckConstraint(
            "entitlement_mode IN ('inherit','active','inactive')",
            name="ck_branch_entitlements_mode",
        ),
    )

    id = Column(Integer, primary_key=True)
    branch_entitlement_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False, unique=True, index=True)
    workspace_entitlement_id = Column(
        Integer, ForeignKey("workspace_entitlements.id"), nullable=False, index=True
    )
    entitlement_mode = Column(String(20), nullable=False, default="inherit")
    reason_code = Column(String(80))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubscriptionPlanPrice(Base):
    __tablename__ = "subscription_plan_prices"
    __table_args__ = (
        Index("ix_subscription_plan_prices_plan", "plan_id"),
        Index("ix_subscription_plan_prices_active", "is_active"),
        Index(
            "uq_subscription_plan_prices_version",
            "plan_id",
            "billing_interval",
            "currency_code",
            "plan_version",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    billing_interval = Column(String(20), nullable=False)
    currency_code = Column(String(3), nullable=False, default="USD")
    amount_minor = Column(Integer, nullable=False)
    compare_at_amount_minor = Column(Integer)
    display_savings_percent = Column(Integer)
    display_savings_amount_minor = Column(Integer)
    provider_price_id = Column(String(120), index=True)
    plan_version = Column(Integer, nullable=False, default=1)
    is_founding_offer = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    effective_from = Column(DateTime)
    effective_to = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CurrencyProfile(Base):
    __tablename__ = "currency_profiles"
    __table_args__ = (
        Index("uq_currency_profiles_code", "currency_code", unique=True),
        Index("ix_currency_profiles_active", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    currency_code = Column(String(3), nullable=False, unique=True, index=True)
    currency_name = Column(String(60), nullable=False)
    currency_symbol = Column(String(8), nullable=False)
    minor_unit = Column(Integer, nullable=False, default=2)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CountryCurrencyMap(Base):
    __tablename__ = "country_currency_map"
    __table_args__ = (
        Index("uq_country_currency_map_country", "country_code", unique=True),
        Index("ix_country_currency_map_currency", "currency_code"),
        Index("ix_country_currency_map_active", "is_active"),
    )

    id = Column(Integer, primary_key=True)
    country_code = Column(String(2), nullable=False, unique=True, index=True)
    currency_code = Column(String(3), ForeignKey("currency_profiles.currency_code"), nullable=False, index=True)
    display_locale = Column(String(20))
    usd_display_rate = Column(Numeric(12, 6), nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationPlanSelection(Base):
    __tablename__ = "pending_organization_plan_selections"
    __table_args__ = (
        Index("ix_pending_organization_plan_selections_org", "pending_organization_id"),
        Index("ix_pending_organization_plan_selections_status", "selection_status"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    billing_interval = Column(String(20), nullable=False)
    base_currency_code = Column(String(3), nullable=False, default="USD")
    base_amount_minor = Column(Integer, nullable=False)
    display_currency_code = Column(String(3), nullable=False, default="USD")
    display_amount_minor = Column(Integer, nullable=False)
    display_exchange_rate = Column(Numeric(12, 6), nullable=False, default=1)
    annual_savings_amount_minor = Column(Integer)
    annual_savings_percent = Column(Integer)
    plan_version = Column(Integer, nullable=False, default=1)
    is_founding_offer = Column(Boolean, nullable=False, default=False)
    selection_status = Column(String(20), nullable=False, default="selected")
    billable_branch_count = Column(Integer, nullable=False, default=0)
    quoted_base_amount_minor = Column(Integer)
    quoted_display_amount_minor = Column(Integer)
    quote_fingerprint = Column(String(64), index=True)
    selected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CheckoutSession(Base):
    __tablename__ = "checkout_sessions"
    __table_args__ = (
        Index("ix_checkout_sessions_org", "pending_organization_id"),
        Index("ix_checkout_sessions_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    plan_selection_id = Column(Integer, ForeignKey("pending_organization_plan_selections.id"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="not_started")
    provider = Column(String(30))
    provider_checkout_id = Column(String(120))
    checkout_url = Column(Text)
    provider_price_id = Column(String(120))
    currency_code = Column(String(3), nullable=False, default="USD")
    amount_minor = Column(Integer, nullable=False)
    billing_interval = Column(String(20), nullable=False)
    billable_branch_count = Column(Integer, nullable=False, default=0)
    quoted_base_amount_minor = Column(Integer)
    quoted_display_amount_minor = Column(Integer)
    quote_fingerprint = Column(String(64), index=True)
    last_payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id"), index=True)
    started_at = Column(DateTime)
    expires_at = Column(DateTime)
    abandoned_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSDraftLifecycleSetting(Base):
    __tablename__ = "saas_draft_lifecycle_settings"

    id = Column(Integer, primary_key=True)
    first_reminder_hours = Column(Integer, nullable=False, default=24)
    second_reminder_days = Column(Integer, nullable=False, default=7)
    final_reminder_days = Column(Integer, nullable=False, default=25)
    deletion_days = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubscriptionContract(Base):
    __tablename__ = "subscription_contracts"
    __table_args__ = (
        Index("ix_subscription_contracts_pending_org", "pending_organization_id"),
        Index("ix_subscription_contracts_status", "contract_status"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    billing_interval = Column(String(20), nullable=False)
    contract_status = Column(String(30), nullable=False, default="draft")
    base_currency_code = Column(String(3), nullable=False, default="USD")
    base_amount_minor = Column(Integer, nullable=False)
    display_currency_code = Column(String(3), nullable=False, default="USD")
    display_amount_minor = Column(Integer, nullable=False)
    billable_branch_count = Column(Integer, nullable=False, default=0)
    quoted_base_amount_minor = Column(Integer)
    quoted_display_amount_minor = Column(Integer)
    quote_fingerprint = Column(String(64), index=True)
    selected_checkout_session_id = Column(Integer, ForeignKey("checkout_sessions.id"), index=True)
    contract_type = Column(String(30), nullable=False, default="self_serve")
    plan_version = Column(Integer, nullable=False, default=1)
    is_founding_offer = Column(Boolean, nullable=False, default=False)
    payment_status = Column(String(30), nullable=False, default="pending")
    paid_at = Column(DateTime)
    payment_provider = Column(String(30))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentCustomer(Base):
    __tablename__ = "payment_customers"
    __table_args__ = (
        Index("uq_payment_customers_provider_customer_id", "provider_customer_id", unique=True),
        Index("uq_payment_customers_provider_address_id", "provider_address_id", unique=True),
        Index("uq_payment_customers_provider_business_id", "provider_business_id", unique=True),
        Index("ix_payment_customers_pending_org", "pending_organization_id"),
        Index("ix_payment_customers_saas_account", "saas_account_id"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), index=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=False, default="paddle")
    provider_customer_id = Column(String(120), nullable=False, unique=True)
    provider_address_id = Column(String(120), unique=True)
    provider_business_id = Column(String(120), unique=True)
    email = Column(String(180))
    name = Column(String(180))
    country_code = Column(String(2))
    status = Column(String(30), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class OrganizationBillingProfile(Base):
    __tablename__ = "organization_billing_profiles"
    __table_args__ = (
        Index(
            "uq_organization_billing_profiles_org",
            "pending_organization_id",
            unique=True,
        ),
        Index(
            "ix_organization_billing_profiles_email",
            "billing_email_normalized",
        ),
        CheckConstraint(
            "provider_sync_status IN ('not_started','pending','synced','failed')",
            name="ck_organization_billing_profiles_sync_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(
        Integer,
        ForeignKey("pending_organizations.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    billing_email = Column(String(180), nullable=False)
    billing_email_normalized = Column(String(180), nullable=False, index=True)
    billing_organization_name = Column(String(180), nullable=False)
    billing_contact_name = Column(String(180))
    company_number = Column(String(180))
    tax_identifier = Column(String(180))
    country_code = Column(String(2), nullable=False)
    country_name = Column(String(120))
    region_name = Column(String(160))
    city_name = Column(String(160))
    district_name = Column(String(160))
    neighborhood_name = Column(String(160))
    confirmed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    provider_sync_status = Column(String(20), nullable=False, default="not_started")
    provider_synced_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        Index("uq_payment_attempts_attempt_uuid", "attempt_uuid", unique=True),
        Index("ix_payment_attempts_pending_org", "pending_organization_id"),
        Index("ix_payment_attempts_checkout_session", "checkout_session_id"),
        Index("ix_payment_attempts_status", "status"),
        Index("ix_payment_attempts_provider_transaction_id", "provider_transaction_id"),
        Index("ix_payment_attempts_provider_subscription_id", "provider_subscription_id"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    checkout_session_id = Column(Integer, ForeignKey("checkout_sessions.id"), nullable=False, index=True)
    plan_selection_id = Column(Integer, ForeignKey("pending_organization_plan_selections.id"), nullable=False, index=True)
    payment_customer_id = Column(Integer, ForeignKey("payment_customers.id"), index=True)
    provider = Column(String(30), nullable=False, default="paddle")
    attempt_uuid = Column(String(36), nullable=False, unique=True)
    provider_checkout_id = Column(String(120))
    provider_transaction_id = Column(String(120))
    provider_subscription_id = Column(String(120))
    status = Column(String(30), nullable=False, default="checkout_started")
    provider_price_id = Column(String(120))
    currency_code = Column(String(3))
    quantity = Column(Integer, nullable=False, default=0)
    unit_amount_minor = Column(Integer)
    amount_minor = Column(Integer)
    billing_interval = Column(String(20), nullable=False)
    quote_fingerprint = Column(String(64), index=True)
    started_at = Column(DateTime)
    expires_at = Column(DateTime)
    completed_at = Column(DateTime)
    failed_at = Column(DateTime)
    cancelled_at = Column(DateTime)
    failure_reason = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentSubscription(Base):
    __tablename__ = "payment_subscriptions"
    __table_args__ = (
        Index("uq_payment_subscriptions_provider_subscription_id", "provider_subscription_id", unique=True),
        Index("ix_payment_subscriptions_pending_org", "pending_organization_id"),
        Index("ix_payment_subscriptions_contract", "subscription_contract_id"),
        Index("ix_payment_subscriptions_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    subscription_contract_id = Column(Integer, ForeignKey("subscription_contracts.id"), nullable=False, index=True)
    payment_customer_id = Column(Integer, ForeignKey("payment_customers.id"), index=True)
    provider = Column(String(30), nullable=False, default="paddle")
    provider_subscription_id = Column(String(120), nullable=False, unique=True)
    provider_price_id = Column(String(120))
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    billing_interval = Column(String(20), nullable=False)
    currency_code = Column(String(3))
    quantity = Column(Integer, nullable=False, default=0)
    unit_amount_minor = Column(Integer)
    amount_minor = Column(Integer)
    quote_fingerprint = Column(String(64), index=True)
    status = Column(String(30), nullable=False, default="pending")
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    next_billed_at = Column(DateTime)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    cancelled_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SubscriptionChangeRequest(Base):
    __tablename__ = "subscription_change_requests"
    __table_args__ = (
        Index("uq_subscription_change_requests_uuid", "request_uuid", unique=True),
        Index("uq_subscription_change_requests_idempotency", "idempotency_key", unique=True),
        Index("ix_subscription_change_requests_group", "school_group_id"),
        Index("ix_subscription_change_requests_subscription", "payment_subscription_id"),
        Index("ix_subscription_change_requests_status", "status"),
        Index(
            "uq_subscription_change_requests_unresolved",
            "payment_subscription_id",
            unique=True,
            sqlite_where=text("status IN ('draft','previewed','awaiting_confirmation','submitted','payment_pending','scheduled','manual_review')"),
            postgresql_where=text("status IN ('draft','previewed','awaiting_confirmation','submitted','payment_pending','scheduled','manual_review')"),
        ),
    )

    id = Column(Integer, primary_key=True)
    request_uuid = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    subscription_contract_id = Column(Integer, ForeignKey("subscription_contracts.id"), nullable=False, index=True)
    payment_subscription_id = Column(Integer, ForeignKey("payment_subscriptions.id"), nullable=False, index=True)
    provider_subscription_id = Column(String(120), nullable=False, index=True)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), index=True)
    requested_by_saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    change_type = Column(String(50), nullable=False)
    current_quantity = Column(Integer, nullable=False)
    requested_quantity = Column(Integer, nullable=False)
    quantity_delta = Column(Integer, nullable=False)
    current_plan_price_id = Column(Integer, ForeignKey("subscription_plan_prices.id"), nullable=False, index=True)
    provider_price_id = Column(String(120), nullable=False)
    target_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), index=True)
    target_plan_price_id = Column(Integer, ForeignKey("subscription_plan_prices.id"), index=True)
    target_provider_price_id = Column(String(120), index=True)
    provider_observed_price_id = Column(String(120))
    entitlement_impact_json = Column(Text)
    provider_scheduled_at = Column(DateTime)
    billing_interval = Column(String(20), nullable=False)
    currency_code = Column(String(3), nullable=False)
    effective_mode = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False, default="draft")
    previewed_charge_minor = Column(Integer)
    previewed_credit_minor = Column(Integer)
    previewed_net_minor = Column(Integer)
    current_renewal_total_minor = Column(Integer)
    next_renewal_total_minor = Column(Integer)
    provider_preview_reference = Column(String(120))
    retained_items_json = Column(Text)
    idempotency_key = Column(String(64), nullable=False, unique=True)
    provider_observed_quantity = Column(Integer)
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    previewed_at = Column(DateTime)
    submitted_at = Column(DateTime)
    provider_payment_received_at = Column(DateTime)
    provider_payment_confirmed_at = Column(DateTime)
    confirmed_at = Column(DateTime)
    effective_at = Column(DateTime)
    canceled_at = Column(DateTime)
    failure_code = Column(String(80))
    failure_message = Column(String(255))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentWebhook(Base):
    __tablename__ = "payment_webhooks"
    __table_args__ = (
        Index(
            "uq_payment_webhooks_provider_event_id",
            "provider_event_id",
            unique=True,
            sqlite_where=text("provider_event_id IS NOT NULL"),
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
        Index("ix_payment_webhooks_event_type", "event_type"),
        Index("ix_payment_webhooks_processing_status", "processing_status"),
        Index("ix_payment_webhooks_received_at", "received_at"),
    )

    id = Column(Integer, primary_key=True)
    provider = Column(String(30), nullable=False, default="paddle")
    provider_event_id = Column(String(120))
    event_type = Column(String(80))
    signature_valid = Column(Boolean, nullable=False, default=False)
    delivery_attempt = Column(Integer, nullable=False, default=1)
    payload_hash = Column(String(128))
    headers_json = Column(Text)
    payload_json = Column(Text)
    received_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime)
    processing_status = Column(String(30), nullable=False, default="pending")
    processing_error = Column(Text)


class ProvisioningJob(Base):
    __tablename__ = "provisioning_jobs"
    __table_args__ = (
        Index("uq_provisioning_jobs_job_uuid", "job_uuid", unique=True),
        Index("uq_provisioning_jobs_idempotency_key", "idempotency_key", unique=True),
        Index("ix_provisioning_jobs_pending_org", "pending_organization_id"),
        Index("ix_provisioning_jobs_status", "job_status"),
        Index("ix_provisioning_jobs_next_attempt_at", "next_attempt_at"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    subscription_contract_id = Column(Integer, ForeignKey("subscription_contracts.id"), nullable=False, index=True)
    job_uuid = Column(String(36), nullable=False, unique=True)
    idempotency_key = Column(String(160), nullable=False, unique=True)
    job_type = Column(String(40), nullable=False, default="tenant_provisioning")
    trigger_source = Column(String(40), nullable=False, default="payment_webhook")
    job_status = Column(String(30), nullable=False, default="queued")
    target_school_group_id = Column(Integer, ForeignKey("school_groups.id"), index=True)
    tenant_provisioning_link_id = Column(Integer, ForeignKey("tenant_provisioning_links.id"), index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_attempt_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    failed_at = Column(DateTime)
    last_error = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProvisioningJobEvent(Base):
    __tablename__ = "provisioning_job_events"
    __table_args__ = (
        Index("ix_provisioning_job_events_job", "provisioning_job_id"),
        Index("ix_provisioning_job_events_type", "event_type"),
        Index("ix_provisioning_job_events_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    provisioning_job_id = Column(Integer, ForeignKey("provisioning_jobs.id"), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    event_status = Column(String(20), nullable=False, default="ok")
    details_json = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class TenantProvisioningLink(Base):
    __tablename__ = "tenant_provisioning_links"
    __table_args__ = (
        Index("uq_tenant_provisioning_links_pending_org", "pending_organization_id", unique=True),
        Index("uq_tenant_provisioning_links_contract", "subscription_contract_id", unique=True),
        Index("uq_tenant_provisioning_links_demo_request", "demo_request_id", unique=True),
        Index("uq_tenant_provisioning_links_promo_grant", "promo_grant_id", unique=True),
        Index("uq_tenant_provisioning_links_school_group", "school_group_id", unique=True),
        Index("ix_tenant_provisioning_links_status", "tenant_status"),
        CheckConstraint(
            "(subscription_contract_id IS NOT NULL AND demo_request_id IS NULL AND promo_grant_id IS NULL) OR "
            "(subscription_contract_id IS NULL AND demo_request_id IS NOT NULL AND promo_grant_id IS NULL) OR "
            "(subscription_contract_id IS NULL AND demo_request_id IS NULL AND promo_grant_id IS NOT NULL)",
            name="ck_tenant_provisioning_links_commercial_source",
        ),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=True, unique=True, index=True)
    subscription_contract_id = Column(Integer, ForeignKey("subscription_contracts.id"), unique=True, index=True)
    demo_request_id = Column(
        Integer,
        ForeignKey("saas_demo_requests.id"),
        unique=True,
        index=True,
    )
    promo_grant_id = Column(Integer, ForeignKey("promo_grants.id"), unique=True, index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, unique=True, index=True)
    owner_operational_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    primary_branch_id = Column(Integer, ForeignKey("branches.id"), index=True)
    primary_academic_year_id = Column(Integer, ForeignKey("academic_years.id"), index=True)
    tenant_status = Column(String(30), nullable=False, default="tenant_active")
    activated_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class SaaSAccountUserLink(Base):
    __tablename__ = "saas_account_user_links"
    __table_args__ = (
        Index(
            "uq_saas_account_user_links_account_user_group",
            "saas_account_id",
            "operational_user_id",
            "school_group_id",
            unique=True,
        ),
        Index("ix_saas_account_user_links_account", "saas_account_id"),
        Index("ix_saas_account_user_links_user", "operational_user_id"),
        Index("ix_saas_account_user_links_school_group", "school_group_id"),
    )

    id = Column(Integer, primary_key=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    operational_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), index=True)
    school_group_id = Column(Integer, ForeignKey("school_groups.id"), nullable=False, index=True)
    link_type = Column(String(30), nullable=False, default="tenant_owner")
    linked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
