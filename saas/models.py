from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text

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
    billing_status = Column(String(30), nullable=False, default="not_started")
    selected_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), index=True)
    selected_billing_interval = Column(String(20))
    checkout_ready_at = Column(DateTime)
    payment_status = Column(String(30), nullable=False, default="pending")
    payment_confirmed_at = Column(DateTime)
    payment_failed_at = Column(DateTime)
    last_payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id"), index=True)
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
    ai_enabled = Column(Boolean, nullable=False, default=False)
    multi_branch_enabled = Column(Boolean, nullable=False, default=False)
    advanced_reporting_enabled = Column(Boolean, nullable=False, default=False)
    priority_support = Column(Boolean, nullable=False, default=False)
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
    last_payment_attempt_id = Column(Integer, ForeignKey("payment_attempts.id"), index=True)
    started_at = Column(DateTime)
    expires_at = Column(DateTime)
    abandoned_at = Column(DateTime)
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
        Index("ix_payment_customers_pending_org", "pending_organization_id"),
        Index("ix_payment_customers_saas_account", "saas_account_id"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), index=True)
    saas_account_id = Column(Integer, ForeignKey("saas_accounts.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=False, default="paddle")
    provider_customer_id = Column(String(120), nullable=False, unique=True)
    email = Column(String(180))
    name = Column(String(180))
    country_code = Column(String(2))
    status = Column(String(30), nullable=False, default="active")
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
    currency_code = Column(String(3))
    amount_minor = Column(Integer)
    billing_interval = Column(String(20), nullable=False)
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
    status = Column(String(30), nullable=False, default="pending")
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    next_billed_at = Column(DateTime)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    cancelled_at = Column(DateTime)
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
        Index("uq_tenant_provisioning_links_school_group", "school_group_id", unique=True),
        Index("ix_tenant_provisioning_links_status", "tenant_status"),
    )

    id = Column(Integer, primary_key=True)
    pending_organization_id = Column(Integer, ForeignKey("pending_organizations.id"), nullable=False, unique=True, index=True)
    subscription_contract_id = Column(Integer, ForeignKey("subscription_contracts.id"), nullable=False, unique=True, index=True)
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
