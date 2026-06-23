from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, text

from database import Base


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
    email_verified_at = Column(DateTime)
    last_login_at = Column(DateTime)
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
    )

    id = Column(Integer, primary_key=True)
    organization_uuid = Column(String(36), nullable=False, unique=True, index=True)
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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PendingOrganizationBranch(Base):
    __tablename__ = "pending_organization_branches"
    __table_args__ = (
        Index("ix_pending_organization_branches_org", "pending_organization_id"),
        Index("ix_pending_organization_branches_order", "pending_organization_id", "sort_order"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, index=True)
    branch_name = Column(String(160), nullable=False)
    location = Column(String(180))
    country_code = Column(String(2))
    country_name = Column(String(120))
    region_name = Column(String(160))
    city_name = Column(String(160))
    district_name = Column(String(160))
    neighborhood_name = Column(String(160))
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
