import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models as operational_models
import auth
import db_migrations
from database import Base
from saas import (
    billing_identity_service,
    commercial_access_service,
    existing_workspace_paid_activation_service as activation_service,
    models,
    payment_service,
    promo_code_service,
    promo_redemption_service,
    service,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _fixture(db, *, branches=5):
    group = operational_models.SchoolGroup(
        name=f"Existing Workspace {uuid.uuid4()}",
        workspace_uuid=str(uuid.uuid4()),
        workspace_classification="customer",
        workspace_lifecycle_status="provisioning",
        country_code="SA",
        country_name="Saudi Arabia",
    )
    db.add(group)
    db.flush()
    branch_rows = []
    for index in range(branches):
        branch = operational_models.Branch(
            school_group_id=group.id,
            name=f"Campus {index + 1}",
            status=True,
        )
        db.add(branch)
        branch_rows.append(branch)
    db.flush()
    year = operational_models.AcademicYear(
        school_group_id=group.id,
        year_name="2026-2027",
        is_active=True,
    )
    db.add(year)
    db.flush()
    user = operational_models.User(
        user_id=f"U{uuid.uuid4().hex[:8]}",
        username=f"owner-{uuid.uuid4().hex}",
        email=f"owner-{uuid.uuid4().hex}@example.edu",
        email_normalized=None,
        first_name="Workspace",
        last_name="Owner",
        role="Admin",
        school_group_id=group.id,
        branch_id=branch_rows[0].id,
        academic_year_id=year.id,
        is_active=True,
    )
    db.add(user)
    account = models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email=user.email,
        email_normalized=user.email.lower(),
        password_hash="test-only-hash",
        first_name="Workspace",
        last_name="Owner",
        status="active",
        onboarding_status="tenant_active",
        account_purpose="customer",
        email_verified_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    link = models.SaaSAccountUserLink(
        saas_account_id=account.id,
        operational_user_id=user.id,
        pending_organization_id=None,
        school_group_id=group.id,
        link_type="tenant_owner",
    )
    db.add(link)
    plans = {}
    limits = {
        "starter": (1, 5, 25, 29_00),
        "professional": (5, 20, 100, 79_00),
        "enterprise_ai": (25, 100, 500, 149_00),
    }
    for order, (code, values) in enumerate(limits.items(), 1):
        max_branches, max_users, max_teachers, monthly = values
        plan = db.query(models.SubscriptionPlan).filter_by(plan_code=code).one_or_none()
        if plan is None:
            plan = models.SubscriptionPlan(plan_code=code)
            db.add(plan)
        plan.plan_name = {
            "starter": "Starter",
            "professional": "Professional",
            "enterprise_ai": "Enterprise AI",
        }[code]
        plan.is_active = True
        plan.is_public = True
        plan.sort_order = order
        plan.max_branches = max_branches
        plan.max_staff_users = max_users
        plan.max_system_users = max_users
        plan.max_teachers = max_teachers
        db.flush()
        plans[code] = plan
        for interval, amount in (("monthly", monthly), ("annual", monthly * 10)):
            price = db.query(models.SubscriptionPlanPrice).filter_by(
                plan_id=plan.id,
                billing_interval=interval,
                currency_code="USD",
                is_active=True,
            ).one_or_none()
            if price is None:
                price = models.SubscriptionPlanPrice(
                    plan_id=plan.id,
                    billing_interval=interval,
                    currency_code="USD",
                    is_active=True,
                    plan_version=1,
                )
                db.add(price)
            price.amount_minor = amount
            price.provider_price_id = f"pri_{code}_{interval}"
    db.commit()
    return group, branch_rows, account, link, plans


def _prepare(db, group, account, plan, *, interval="monthly"):
    billing_identity_service.save_workspace_billing_profile(
        db,
        group,
        billing_email=account.email,
        billing_organization_name=group.name,
        billing_contact_name="Workspace Owner",
        country_code="SA",
        country_name="Saudi Arabia",
        city_name="Riyadh",
    )
    return activation_service.prepare_activation(
        db,
        school_group_id=group.id,
        account=account,
        plan_id=plan.id,
        billing_interval=interval,
        selected_branch_ids=None,
        idempotency_key=f"activation-{uuid.uuid4()}",
    )


def _customer(db, account):
    row = models.PaymentCustomer(
        pending_organization_id=None,
        saas_account_id=account.id,
        provider="paddle",
        provider_customer_id=f"ctm_{uuid.uuid4().hex}",
        provider_address_id=f"add_{uuid.uuid4().hex}",
        provider_business_id=f"biz_{uuid.uuid4().hex}",
        email=account.email,
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def _billed_transaction(kwargs, *, transaction_id):
    interval = "month" if kwargs["custom_data"].get("billing_interval") == "monthly" else None
    if interval is None:
        interval = "month" if "monthly" in kwargs["price_id"] else "year"
    return {
        "id": transaction_id,
        "status": "billed",
        "collection_mode": "automatic",
        "customer_id": kwargs["customer_id"],
        "address_id": kwargs["address_id"],
        "business_id": kwargs["business_id"],
        "currency_code": "USD",
        "custom_data": dict(kwargs["custom_data"]),
        "items": [{
            "quantity": kwargs["quantity"],
            "price": {
                "id": kwargs["price_id"],
                "billing_cycle": {"interval": interval},
            },
        }],
        "details": {"totals": {"subtotal": str(kwargs["expected_subtotal"])}},
        "checkout": {
            "id": f"checkout_{transaction_id}",
            "url": "https://checkout.example.test",
        },
    }


def _completed_payload(activation, customer, *, transaction_id, subscription_id):
    return {
        "id": transaction_id,
        "status": "completed",
        "customer_id": customer.provider_customer_id,
        "address_id": customer.provider_address_id,
        "business_id": customer.provider_business_id,
        "subscription_id": subscription_id,
        "currency_code": activation.quote_currency_code,
        "custom_data": {
            "checkout_context": "existing_workspace_paid_activation",
            "paid_activation_uuid": activation.activation_uuid,
            "workspace_uuid": activation.workspace_uuid_snapshot,
            "saas_account_uuid": activation._account_uuid,
            "payment_attempt_uuid": activation._attempt_uuid,
            "subscription_contract_id": activation.subscription_contract_id,
            "quote_fingerprint": activation.quote_fingerprint,
            "branch_selection_hash": activation.selected_branch_hash,
        },
        "items": [{
            "quantity": activation.branch_quantity,
            "price": {
                "id": activation.provider_price_id,
                "billing_cycle": {
                    "interval": "month" if activation.billing_interval == "monthly" else "year"
                },
            },
        }],
        "details": {"totals": {"subtotal": str(activation.quote_aggregate_amount_minor)}},
    }


def test_eligibility_requires_verified_owner_and_is_tenant_scoped(db):
    group, _branches, account, _link, _plans = _fixture(db)
    assert activation_service.resolve_eligibility(
        db, school_group_id=group.id, account=account
    ).eligible
    account.email_verified_at = None
    assert activation_service.resolve_eligibility(
        db, school_group_id=group.id, account=account
    ).reason_code == "verified_active_account_required"
    other = models.SaaSAccount(
        account_uuid=str(uuid.uuid4()), email="other@example.edu",
        email_normalized="other@example.edu", status="active",
        onboarding_status="not_started", account_purpose="customer",
        email_verified_at=datetime.utcnow(),
    )
    db.add(other)
    db.flush()
    assert activation_service.resolve_eligibility(
        db, school_group_id=group.id, account=other
    ).reason_code == "verified_tenant_owner_required"


def test_professional_and_enterprise_quotes_use_all_five_active_branches(db):
    group, branches, account, _link, plans = _fixture(db)
    eligibility = activation_service.require_eligibility(
        db, school_group_id=group.id, account=account
    )
    professional = activation_service.build_quote(
        db, eligibility=eligibility, plan_id=plans["professional"].id,
        billing_interval="annual", selected_branch_ids=None,
    )
    enterprise = activation_service.build_quote(
        db, eligibility=eligibility, plan_id=plans["enterprise_ai"].id,
        billing_interval="monthly", selected_branch_ids=None,
    )
    assert professional.ready
    assert professional.quantity == len(branches) == 5
    assert professional.unit_amount_minor == 790_00
    assert professional.aggregate_amount_minor == 3_950_00
    assert enterprise.ready and enterprise.quantity == 5
    assert enterprise.aggregate_amount_minor == 5 * 149_00
    assert professional.branch_selection_hash != enterprise.fingerprint


def test_starter_is_fail_closed_until_branch_enforcement_is_proven(db):
    group, branches, account, _link, plans = _fixture(db)
    eligibility = activation_service.require_eligibility(
        db, school_group_id=group.id, account=account
    )
    quote = activation_service.build_quote(
        db, eligibility=eligibility, plan_id=plans["starter"].id,
        billing_interval="monthly", selected_branch_ids=[branches[0].id],
    )
    assert "starter_branch_enforcement_unavailable" in quote.errors
    options = activation_service.list_plan_options(db, eligibility, "monthly")
    starter = next(row for row in options if row["plan"].plan_code == "starter")
    assert not starter["available"]


def test_prepare_is_idempotent_and_creates_no_onboarding_or_provisioning_rows(db):
    group, _branches, account, _link, plans = _fixture(db)
    key = "same-operation"
    billing_identity_service.save_workspace_billing_profile(
        db, group, billing_email=account.email,
        billing_organization_name=group.name, country_code="SA",
    )
    first = activation_service.prepare_activation(
        db, school_group_id=group.id, account=account,
        plan_id=plans["professional"].id, billing_interval="monthly",
        selected_branch_ids=None, idempotency_key=key,
    )
    second = activation_service.prepare_activation(
        db, school_group_id=group.id, account=account,
        plan_id=plans["professional"].id, billing_interval="monthly",
        selected_branch_ids=None, idempotency_key=key,
    )
    assert first.id == second.id
    assert db.query(models.PendingOrganization).count() == 0
    assert db.query(models.ProvisioningJob).count() == 0
    assert db.query(operational_models.SchoolGroup).count() == 1


def test_context_xor_constraints_preserve_onboarding_integrity(db):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    db.commit()
    activation_id = activation.id
    invalid = models.CheckoutSession(
        pending_organization_id=None,
        plan_selection_id=None,
        existing_workspace_paid_activation_id=None,
        status="ready", amount_minor=1, billing_interval="monthly",
    )
    db.add(invalid)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert db.get(models.ExistingWorkspacePaidActivation, activation_id) is not None


def test_launch_reuses_customer_and_sends_authoritative_metadata(db, monkeypatch):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    captured = {}
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    def create_transaction(**kwargs):
        captured.update(kwargs)
        return _billed_transaction(kwargs, transaction_id="txn_workspace_activation")
    monkeypatch.setattr(activation_service.paddle_client, "create_transaction", create_transaction)
    launch = activation_service.launch_checkout(
        db, activation_uuid=activation.activation_uuid, account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    assert launch.transaction_id == "txn_workspace_activation"
    assert captured["quantity"] == 5
    assert captured["price_id"] == "pri_professional_monthly"
    assert captured["expected_subtotal"] == 5 * 79_00
    assert set(captured["custom_data"]) == {
        "checkout_context", "paid_activation_uuid", "workspace_uuid",
        "saas_account_uuid", "payment_attempt_uuid", "subscription_contract_id",
        "quote_fingerprint", "branch_selection_hash",
    }
    assert db.query(models.PaymentCustomerWorkspaceAssociation).filter_by(
        school_group_id=group.id, payment_customer_id=customer.id
    ).one()


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        (lambda row: row.update(status="ready"), "provider_transaction_not_launchable"),
        (lambda row: row.update(collection_mode="manual"), "provider_collection_mode_mismatch"),
        (lambda row: row["items"][0]["price"].update(id="pri_wrong"), "provider_price_mismatch"),
        (lambda row: row["items"][0].update(quantity=4), "provider_quantity_mismatch"),
        (lambda row: row["details"]["totals"].update(subtotal="1"), "provider_total_mismatch"),
        (lambda row: row.update(currency_code="EUR"), "provider_currency_mismatch"),
        (lambda row: row["items"][0]["price"]["billing_cycle"].update(interval="year"), "provider_interval_mismatch"),
        (lambda row: row.update(address_id="add_wrong"), "provider_address_mismatch"),
        (lambda row: row.update(business_id="biz_wrong"), "provider_business_mismatch"),
        (lambda row: row["custom_data"].update(workspace_uuid="wrong"), "provider_transaction_lineage_mismatch"),
    ),
)
def test_launch_rejects_incomplete_or_mismatched_provider_authority(
    db, monkeypatch, mutation, reason_code
):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    db.commit()
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )

    def invalid_transaction(**kwargs):
        row = _billed_transaction(kwargs, transaction_id="txn_invalid_authority")
        mutation(row)
        return row

    monkeypatch.setattr(
        activation_service.paddle_client, "create_transaction", invalid_transaction
    )
    with pytest.raises(activation_service.ExistingWorkspacePaidActivationError) as caught:
        activation_service.launch_checkout(
            db,
            activation_uuid=activation.activation_uuid,
            account=account,
            checkout_url="https://app.example.test/saas/payment",
        )
    assert caught.value.reason_code == reason_code
    db.rollback()
    assert db.query(models.PaymentAttempt).count() == 0
    assert db.query(models.PaymentCustomerWorkspaceAssociation).count() == 0


def test_stale_remote_transaction_is_replaced_only_after_full_validation(db, monkeypatch):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    calls = []

    def create_transaction(**kwargs):
        calls.append(dict(kwargs))
        transaction_id = "txn_current" if len(calls) == 1 else "txn_replacement"
        return _billed_transaction(kwargs, transaction_id=transaction_id)

    monkeypatch.setattr(
        activation_service.paddle_client, "create_transaction", create_transaction
    )
    first = activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    db.commit()
    stale = _billed_transaction(calls[0], transaction_id=first.transaction_id)
    stale["items"][0]["quantity"] = 1
    monkeypatch.setattr(
        activation_service.paddle_client, "get_transaction", lambda **_kwargs: stale
    )
    second = activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    assert second.transaction_id == "txn_replacement"
    assert not second.reused
    assert len(calls) == 2
    old_attempt = db.query(models.PaymentAttempt).filter_by(
        provider_transaction_id="txn_current"
    ).one()
    assert old_attempt.status == "superseded"


def test_transaction_paid_is_processing_only(db, monkeypatch):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service, "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client, "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_paid"),
    )
    activation_service.launch_checkout(
        db, activation_uuid=activation.activation_uuid, account=account,
        checkout_url="https://app.test/saas/payment",
    )
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.commercial_state == commercial_access_service.PAYMENT_PROCESSING
    result = activation_service.reconcile_webhook(
        db,
        {"data": {
            "id": "txn_paid",
            "custom_data": {
                "checkout_context": "existing_workspace_paid_activation",
                "paid_activation_uuid": activation.activation_uuid,
            },
        }},
        "transaction.paid",
    )
    assert result["status"] == "processed"
    assert activation.status == "payment_processing"
    assert group.workspace_lifecycle_status == "provisioning"
    assert db.query(models.WorkspaceEntitlement).count() == 0
    assert db.query(models.TenantProvisioningLink).count() == 0
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.commercial_state == commercial_access_service.PAYMENT_PROCESSING


def test_activation_required_without_checkout_is_not_payment_processing(db):
    group, _branches, _account, _link, _plans = _fixture(db)
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.reason_code == "activation_required"
    assert access.commercial_state == commercial_access_service.ACTIVATION_REQUIRED
    assert access.commercial_state != commercial_access_service.PAYMENT_PROCESSING


def test_prepared_checkout_without_payment_attempt_is_not_payment_processing(db):
    group, _branches, account, _link, plans = _fixture(db)
    _prepare(db, group, account, plans["professional"])
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.reason_code == "activation_required"
    assert access.commercial_state == commercial_access_service.ACTIVATION_REQUIRED


def test_manual_review_activation_is_not_payment_processing(db):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    activation.status = "manual_review"
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.commercial_state == commercial_access_service.INCONSISTENT
    assert access.commercial_state != commercial_access_service.PAYMENT_PROCESSING


@pytest.mark.parametrize(
    ("event_type", "expected_state"),
    (
        ("transaction.payment_failed", commercial_access_service.PAYMENT_FAILED),
        ("transaction.canceled", commercial_access_service.PAYMENT_CANCELLED),
        ("expired", commercial_access_service.PAYMENT_FAILED),
    ),
)
def test_failed_or_cancelled_checkout_uses_recovery_state(
    db, monkeypatch, event_type, expected_state
):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client,
        "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_recovery"),
    )
    activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.test/saas/payment",
    )
    if event_type == "expired":
        attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
        attempt.expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        )
    else:
        result = activation_service.reconcile_webhook(
            db,
            {
                "data": {
                    "id": "txn_recovery",
                    "custom_data": {
                        "checkout_context": "existing_workspace_paid_activation",
                        "paid_activation_uuid": activation.activation_uuid,
                    },
                },
            },
            event_type,
        )
        assert result["status"] == "processed"
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.reason_code == "activation_required"
    assert access.commercial_state == expected_state
    assert access.commercial_state != commercial_access_service.PAYMENT_PROCESSING


def test_completed_webhook_atomically_activates_existing_workspace(db, monkeypatch):
    group, branches, account, _link, plans = _fixture(db)
    operational_counts = (
        db.query(operational_models.SchoolGroup).count(),
        db.query(operational_models.Branch).count(),
        db.query(operational_models.User).count(),
        db.query(operational_models.AcademicYear).count(),
    )
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service, "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client, "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_complete"),
    )
    activation_service.launch_checkout(
        db, activation_uuid=activation.activation_uuid, account=account,
        checkout_url="https://app.test/saas/payment",
    )
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    payload = _completed_payload(
        activation, customer, transaction_id="txn_complete", subscription_id="sub_complete"
    )
    result = activation_service.reconcile_webhook(
        db, {"data": payload}, "transaction.completed"
    )
    assert result["status"] == "processed"
    assert activation.status == "completed"
    assert group.workspace_classification == "customer"
    assert group.workspace_lifecycle_status == "active"
    assert db.query(models.WorkspaceEntitlement).filter_by(
        school_group_id=group.id, entitlement_type="paid", status="active"
    ).one()
    assert db.query(models.TenantProvisioningLink).filter_by(
        school_group_id=group.id, subscription_contract_id=activation.subscription_contract_id,
        tenant_status="tenant_active",
    ).one()
    branch_entitlements = db.query(models.BranchEntitlement).filter_by(
        school_group_id=group.id
    ).all()
    assert len(branch_entitlements) == len(branches) == 5
    assert all(row.entitlement_mode == "active" for row in branch_entitlements)
    assert operational_counts == (
        db.query(operational_models.SchoolGroup).count(),
        db.query(operational_models.Branch).count(),
        db.query(operational_models.User).count(),
        db.query(operational_models.AcademicYear).count(),
    )
    access = commercial_access_service.resolve_workspace_access(db, group.id)
    assert access.allowed_access and access.current_plan_code == "professional"
    assert access.commercial_state == commercial_access_service.ACTIVE


def test_pending_organization_payment_processing_mapping_is_unchanged(db):
    account = models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email="pending-payment@example.edu",
        email_normalized="pending-payment@example.edu",
        status="active",
        onboarding_status="ready_for_checkout",
        account_purpose="customer",
        email_verified_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    organization = models.PendingOrganization(
        organization_uuid=str(uuid.uuid4()),
        owner_saas_account_id=account.id,
        organization_name="Pending Payment Academy",
        status="ready_for_checkout",
        billing_status="payment_processing",
        payment_status="pending",
    )
    db.add(organization)
    db.flush()
    service.update_pending_dashboard_status(
        account,
        organization,
        type("Progress", (), {"completion_percent": 100})(),
    )
    assert account.onboarding_status == "payment_processing"


def test_shared_webhook_dispatcher_routes_paid_activation_before_onboarding(db, monkeypatch):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service, "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client, "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_dispatch"),
    )
    activation_service.launch_checkout(
        db, activation_uuid=activation.activation_uuid, account=account,
        checkout_url="https://app.test/saas/payment",
    )
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    payload = {
        "event_id": "evt_paid_activation_dispatch",
        "event_type": "transaction.completed",
        "data": _completed_payload(
            activation, customer, transaction_id="txn_dispatch",
            subscription_id="sub_dispatch",
        ),
    }
    monkeypatch.setattr(payment_service, "verify_webhook_signature", lambda *_args: None)
    result = payment_service.process_webhook(
        db,
        raw_body=json.dumps(payload).encode("utf-8"),
        headers={"Paddle-Signature": "test-signature"},
    )
    assert result["status"] == "processed"
    assert group.workspace_lifecycle_status == "active"
    webhook = db.query(models.PaymentWebhook).filter_by(
        provider_event_id="evt_paid_activation_dispatch"
    ).one()
    assert webhook.processing_status == "processed"


def test_completed_webhook_is_idempotent_and_mismatch_fails_closed(db, monkeypatch):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service, "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client, "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_retry"),
    )
    activation_service.launch_checkout(
        db, activation_uuid=activation.activation_uuid, account=account,
        checkout_url="https://app.test/saas/payment",
    )
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    bad = _completed_payload(
        activation, customer, transaction_id="txn_retry", subscription_id="sub_retry"
    )
    bad["items"][0]["quantity"] = 4
    blocked = activation_service.reconcile_webhook(
        db, {"data": bad}, "transaction.completed"
    )
    assert blocked["status"] == "manual_review"
    assert db.query(models.WorkspaceEntitlement).count() == 0
    assert db.query(models.TenantProvisioningLink).count() == 0


def test_event_details_are_redacted_and_append_only_shape(db):
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    event = db.query(models.ExistingWorkspacePaidActivationEvent).filter_by(
        paid_activation_id=activation.id
    ).one()
    details = json.loads(event.details_json)
    assert set(details) <= {
        "plan_code", "billing_interval", "quantity", "reason_code",
        "status", "event_type", "reused",
    }
    assert account.email not in event.details_json
    assert activation.workspace_uuid_snapshot not in event.details_json


def test_m4c_migration_is_registered_and_idempotent_on_disposable_database():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        applied = db_migrations.run_pending_migrations(engine)
        assert "20260806_002_existing_workspace_paid_activation" in applied
        assert db_migrations.run_pending_migrations(engine) == []
    finally:
        engine.dispose()


POSTGRES_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "").strip()


@pytest.fixture()
def pg_db():
    if not POSTGRES_URL.startswith("postgresql"):
        pytest.skip("TIS_TEST_POSTGRESQL_URL is required for M4C PostgreSQL tests")
    schema = f"m4c_{uuid.uuid4().hex}"
    admin = create_engine(POSTGRES_URL)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        POSTGRES_URL,
        connect_args={
            "connect_timeout": 10,
            "options": (
                f"-c search_path={schema} -c lock_timeout=5s "
                "-c statement_timeout=60s"
            ),
        },
    )
    Base.metadata.create_all(engine)
    applied = db_migrations.run_pending_migrations(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    session = session_factory()
    try:
        yield session, engine, session_factory, applied
    finally:
        session.rollback()
        session.close()
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_postgresql_m4c_migration_schema_constraints_indexes_and_events(pg_db):
    db, engine, _factory, applied = pg_db
    assert applied[-1] == "20260806_002_existing_workspace_paid_activation"
    assert db_migrations.run_pending_migrations(engine) == []
    inspector = inspect(engine)
    assert {
        "existing_workspace_paid_activations",
        "existing_workspace_paid_activation_branches",
        "existing_workspace_paid_activation_events",
        "payment_customer_workspace_associations",
    } <= set(inspector.get_table_names())
    checks = {
        table: {row["name"] for row in inspector.get_check_constraints(table)}
        for table in (
            "checkout_sessions",
            "payment_attempts",
            "organization_billing_profiles",
            "subscription_contracts",
        )
    }
    assert "ck_checkout_sessions_context" in checks["checkout_sessions"]
    assert "ck_payment_attempts_context" in checks["payment_attempts"]
    assert "ck_organization_billing_profiles_context" in checks["organization_billing_profiles"]
    assert "ck_subscription_contracts_context" in checks["subscription_contracts"]
    activation_indexes = {
        row["name"] for row in inspector.get_indexes("existing_workspace_paid_activations")
    }
    assert {
        "uq_existing_workspace_paid_activations_unresolved_group",
        "uq_existing_workspace_paid_activations_transaction",
        "uq_existing_workspace_paid_activations_subscription",
    } <= activation_indexes
    attempt_indexes = {
        row["name"] for row in inspector.get_indexes("payment_attempts")
    }
    assert "uq_payment_attempts_provider_transaction_id" in attempt_indexes
    association_columns = {
        row["name"] for row in inspector.get_columns("payment_customer_workspace_associations")
    }
    assert {"provider_address_id", "provider_business_id"} <= association_columns
    triggers = {
        row[0]
        for row in db.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
            "AND tgrelid = 'existing_workspace_paid_activation_events'::regclass"
        ))
    }
    assert triggers == {
        "trg_existing_workspace_paid_activation_events_no_update",
        "trg_existing_workspace_paid_activation_events_no_delete",
    }

    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    db.commit()
    event = db.query(models.ExistingWorkspacePaidActivationEvent).filter_by(
        paid_activation_id=activation.id
    ).one()
    event.result = "failed"
    with pytest.raises(Exception):
        db.commit()
    db.rollback()
    assert db.get(models.ExistingWorkspacePaidActivationEvent, event.id).result == "success"


def test_postgresql_context_and_uniqueness_constraints_fail_closed(pg_db):
    db, _engine, _factory, _applied = pg_db
    group, _branches, account, link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    db.commit()

    invalid_checkout = models.CheckoutSession(
        pending_organization_id=None,
        plan_selection_id=None,
        existing_workspace_paid_activation_id=None,
        status="ready",
        amount_minor=1,
        billing_interval="monthly",
    )
    db.add(invalid_checkout)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    checkout = db.get(models.CheckoutSession, activation.current_checkout_session_id)
    invalid_attempt = models.PaymentAttempt(
        pending_organization_id=None,
        plan_selection_id=None,
        existing_workspace_paid_activation_id=None,
        checkout_session_id=checkout.id,
        attempt_uuid=str(uuid.uuid4()),
        status="checkout_started",
        quantity=1,
        billing_interval="monthly",
    )
    db.add(invalid_attempt)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    duplicate = models.ExistingWorkspacePaidActivation(
        activation_uuid=str(uuid.uuid4()),
        school_group_id=group.id,
        workspace_uuid_snapshot=group.workspace_uuid,
        saas_account_id=account.id,
        tenant_owner_link_id=link.id,
        selected_plan_id=plans["professional"].id,
        selected_plan_code="professional",
        provider_price_id="pri_professional_monthly",
        billing_interval="monthly",
        status="checkout_ready",
        lifecycle_stage="review",
        branch_quantity=5,
        selected_branch_hash="a" * 64,
        quote_fingerprint="b" * 64,
        quote_currency_code="USD",
        quote_unit_amount_minor=7900,
        quote_aggregate_amount_minor=39500,
        checkout_idempotency_key=f"duplicate-{uuid.uuid4()}",
        subscription_contract_id=activation.subscription_contract_id,
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    profile = db.query(models.OrganizationBillingProfile).filter_by(
        school_group_id=group.id
    ).one()
    profile.pending_organization_id = -1
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.query(models.ExistingWorkspacePaidActivation).filter(
        models.ExistingWorkspacePaidActivation.status.in_(activation_service.OPEN_STATUSES)
    ).count() == 1


def test_postgresql_provider_and_workspace_mapping_uniqueness_is_enforced(
    pg_db, monkeypatch
):
    db, _engine, _factory, _applied = pg_db
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client,
        "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_pg_unique"),
    )
    activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    db.commit()
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)

    duplicate_attempt = models.PaymentAttempt(
        pending_organization_id=None,
        plan_selection_id=None,
        existing_workspace_paid_activation_id=activation.id,
        checkout_session_id=activation.current_checkout_session_id,
        attempt_uuid=str(uuid.uuid4()),
        provider_transaction_id=attempt.provider_transaction_id,
        status="checkout_started",
        quantity=activation.branch_quantity,
        billing_interval=activation.billing_interval,
    )
    db.add(duplicate_attempt)
    with pytest.raises(IntegrityError) as duplicate_transaction:
        db.commit()
    assert duplicate_transaction.value.orig.diag.constraint_name == (
        "uq_payment_attempts_provider_transaction_id"
    )
    db.rollback()

    duplicate_association = models.PaymentCustomerWorkspaceAssociation(
        payment_customer_id=customer.id,
        school_group_id=group.id,
        saas_account_id=account.id,
        provider_address_id=customer.provider_address_id,
        provider_business_id=customer.provider_business_id,
    )
    db.add(duplicate_association)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    payload = _completed_payload(
        activation,
        customer,
        transaction_id="txn_pg_unique",
        subscription_id="sub_pg_unique",
    )
    assert activation_service.reconcile_webhook(
        db, {"data": payload}, "transaction.completed"
    )["status"] == "processed"
    db.commit()
    subscription = db.query(models.PaymentSubscription).filter_by(
        provider_subscription_id="sub_pg_unique"
    ).one()
    duplicate_subscription = models.PaymentSubscription(
        pending_organization_id=None,
        subscription_contract_id=subscription.subscription_contract_id,
        payment_customer_id=customer.id,
        provider="paddle",
        provider_subscription_id="sub_pg_unique",
        provider_price_id=activation.provider_price_id,
        plan_id=activation.selected_plan_id,
        billing_interval=activation.billing_interval,
        currency_code="USD",
        quantity=activation.branch_quantity,
        status="active",
    )
    db.add(duplicate_subscription)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_postgresql_school_group_lock_blocks_prepare_without_partial_rows(pg_db):
    db, _engine, factory, _applied = pg_db
    group, _branches, account, _link, plans = _fixture(db)
    billing_identity_service.save_workspace_billing_profile(
        db,
        group,
        billing_email=account.email,
        billing_organization_name=group.name,
        country_code="SA",
    )
    db.commit()
    blocker = factory()
    contender = factory()
    try:
        blocker.query(operational_models.SchoolGroup).filter_by(id=group.id).with_for_update().one()
        contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError):
            activation_service.prepare_activation(
                contender,
                school_group_id=group.id,
                account=contender.get(models.SaaSAccount, account.id),
                plan_id=plans["professional"].id,
                billing_interval="monthly",
                selected_branch_ids=None,
                idempotency_key="lock-timeout-proof",
            )
        contender.rollback()
        assert contender.query(models.ExistingWorkspacePaidActivation).filter_by(
            school_group_id=group.id
        ).count() == 0
        assert contender.query(models.SubscriptionContract).filter_by(
            school_group_id=group.id
        ).count() == 0
    finally:
        blocker.rollback()
        contender.rollback()
        blocker.close()
        contender.close()


def test_postgresql_concurrent_prepare_returns_one_unresolved_idempotent_activation(pg_db):
    db, _engine, factory, _applied = pg_db
    group, _branches, account, _link, plans = _fixture(db)
    billing_identity_service.save_workspace_billing_profile(
        db,
        group,
        billing_email=account.email,
        billing_organization_name=group.name,
        country_code="SA",
    )
    db.commit()
    group_id, account_id, plan_id = group.id, account.id, plans["professional"].id
    barrier = threading.Barrier(2)

    def worker():
        session = factory()
        try:
            barrier.wait(timeout=10)
            row = activation_service.prepare_activation(
                session,
                school_group_id=group_id,
                account=session.get(models.SaaSAccount, account_id),
                plan_id=plan_id,
                billing_interval="monthly",
                selected_branch_ids=None,
                idempotency_key="postgres-concurrent-prepare",
            )
            session.commit()
            return row.activation_uuid
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: worker(), range(2)))
    assert len(set(results)) == 1
    db.expire_all()
    assert db.query(models.ExistingWorkspacePaidActivation).filter(
        models.ExistingWorkspacePaidActivation.status.in_(activation_service.OPEN_STATUSES)
    ).count() == 1
    assert db.query(models.SubscriptionContract).count() == 1


def test_postgresql_concurrent_launch_creates_one_checkout_lineage(pg_db, monkeypatch):
    db, _engine, factory, _applied = pg_db
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    db.commit()
    activation_uuid, account_id = activation.activation_uuid, account.id
    provider_lock = threading.Lock()
    provider = {"transaction": None, "creates": 0}

    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )

    def create_transaction(**kwargs):
        with provider_lock:
            provider["creates"] += 1
            provider["transaction"] = _billed_transaction(
                kwargs, transaction_id="txn_postgres_concurrent"
            )
            return provider["transaction"]

    def get_transaction(**_kwargs):
        with provider_lock:
            return dict(provider["transaction"])

    monkeypatch.setattr(activation_service.paddle_client, "create_transaction", create_transaction)
    monkeypatch.setattr(activation_service.paddle_client, "get_transaction", get_transaction)
    barrier = threading.Barrier(2)

    def worker():
        session = factory()
        try:
            barrier.wait(timeout=10)
            launch = activation_service.launch_checkout(
                session,
                activation_uuid=activation_uuid,
                account=session.get(models.SaaSAccount, account_id),
                checkout_url="https://app.example.test/saas/payment",
            )
            session.commit()
            return launch.transaction_id, launch.reused
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: worker(), range(2)))
    assert {row[0] for row in results} == {"txn_postgres_concurrent"}
    assert sorted(row[1] for row in results) == [False, True]
    assert provider["creates"] == 1
    db.expire_all()
    assert db.query(models.PaymentAttempt).count() == 1
    assert db.query(models.PaymentCustomerWorkspaceAssociation).count() == 1


def test_postgresql_duplicate_completion_and_out_of_order_subscription_are_safe(
    pg_db, monkeypatch
):
    db, _engine, factory, _applied = pg_db
    group, branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["enterprise_ai"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client,
        "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_pg_complete"),
    )
    activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    subscription_event = {
        "id": "sub_pg_complete",
        "status": "active",
        "custom_data": {
            "checkout_context": "existing_workspace_paid_activation",
            "paid_activation_uuid": activation.activation_uuid,
        },
    }
    assert activation_service.reconcile_webhook(
        db, {"data": subscription_event}, "subscription.created"
    )["status"] == "processed"
    assert group.workspace_lifecycle_status == "provisioning"
    assert db.query(models.WorkspaceEntitlement).filter_by(
        school_group_id=group.id
    ).count() == 0
    payload = _completed_payload(
        activation,
        customer,
        transaction_id="txn_pg_complete",
        subscription_id="sub_pg_complete",
    )
    db.commit()
    barrier = threading.Barrier(2)

    def worker():
        session = factory()
        try:
            barrier.wait(timeout=10)
            result = activation_service.reconcile_webhook(
                session, {"data": payload}, "transaction.completed"
            )
            session.commit()
            return result
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: worker(), range(2)))
    assert all(row["status"] == "processed" for row in results)
    assert sum(bool(row.get("deduplicated")) for row in results) == 1
    db.expire_all()
    assert db.query(models.PaymentSubscription).count() == 1
    assert db.query(models.WorkspaceEntitlement).filter_by(
        school_group_id=group.id
    ).count() == 1
    assert db.query(models.TenantProvisioningLink).filter_by(
        school_group_id=group.id
    ).count() == 1
    assert db.query(models.BranchEntitlement).filter_by(
        school_group_id=group.id
    ).count() == len(branches) == 5
    assert db.get(operational_models.SchoolGroup, group.id).workspace_lifecycle_status == "active"


def test_postgresql_paid_and_promo_activation_race_creates_one_commercial_source(
    pg_db, monkeypatch
):
    db, _engine, factory, _applied = pg_db
    group, branches, account, _link, plans = _fixture(db, branches=1)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setenv(
        "TIS_PROMO_CODE_HMAC_SECRET",
        "m4c-postgresql-paid-promo-race-secret-long-enough",
    )
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client,
        "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_pg_source_race"),
    )
    activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    paid_payload = _completed_payload(
        activation,
        customer,
        transaction_id="txn_pg_source_race",
        subscription_id="sub_pg_source_race",
    )

    actor_email = f"platform-{uuid.uuid4().hex}@example.test"
    actor = operational_models.User(
        user_id=f"P{uuid.uuid4().hex[:9]}",
        username=f"platform-{uuid.uuid4().hex}",
        email=actor_email,
        email_normalized=actor_email,
        user_type=auth.USER_TYPE_PLATFORM,
        platform_role=auth.PLATFORM_ROLE_OWNER,
        access_scope=auth.ACCESS_SCOPE_GLOBAL,
        is_active=True,
    )
    db.add(actor)
    db.flush()
    now = datetime.now(timezone.utc)
    with patch("saas.promo_code_service.audit.write_audit_event"):
        created = promo_code_service.create_promo(
            db,
            actor=actor,
            values={
                "title": "M4C paid versus promo race",
                "subscription_plan_id": plans["professional"].id,
                "max_branches": 1,
                "max_system_users": 5,
                "max_teachers": 25,
                "scope_type": "global",
                "max_total_redemptions": 1,
                "valid_from": now - timedelta(minutes=1),
                "redemption_deadline": now + timedelta(days=1),
                "access_duration_days": 30,
                "grace_period_days": 0,
            },
        )
        promo_code_service.activate_promo(
            db,
            promo_uuid=created.promo.promo_uuid,
            actor=actor,
        )
    review = promo_redemption_service.start_activation(
        db,
        account=account,
        raw_code=created.raw_code,
        school_group=group,
        operational_user=db.get(
            operational_models.User,
            db.query(models.SaaSAccountUserLink.operational_user_id).filter_by(
                saas_account_id=account.id,
                school_group_id=group.id,
                link_type="tenant_owner",
            ).scalar(),
        ),
        idempotency_key="m4c-source-race:start",
    )
    db.commit()

    barrier = threading.Barrier(2)

    def complete_paid():
        session = factory()
        try:
            barrier.wait(timeout=10)
            result = activation_service.reconcile_webhook(
                session, {"data": paid_payload}, "transaction.completed"
            )
            session.commit()
            return "paid", result["status"]
        finally:
            session.close()

    def activate_promo():
        session = factory()
        try:
            barrier.wait(timeout=10)
            try:
                with patch("saas.promo_redemption_service.audit.write_audit_event"):
                    promo_redemption_service.activate_promo(
                        session,
                        activation_uuid=review.session.activation_uuid,
                        account=session.get(models.SaaSAccount, account.id),
                        idempotency_key="m4c-source-race:activate",
                    )
                session.commit()
                return "promo", "processed"
            except promo_redemption_service.PromoActivationError as exc:
                session.rollback()
                return "promo", exc.reason_code
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(complete_paid),
            executor.submit(activate_promo),
        ]
        outcomes = [future.result() for future in futures]

    db.expire_all()
    paid_count = db.query(models.PaymentSubscription).filter_by(
        subscription_contract_id=activation.subscription_contract_id
    ).count()
    promo_count = db.query(models.PromoGrant).filter_by(
        school_group_id=group.id,
        status="active",
    ).count()
    assert paid_count + promo_count == 1
    assert db.query(models.WorkspaceEntitlement).filter_by(
        school_group_id=group.id,
        status="active",
    ).count() == 1
    assert db.query(models.TenantProvisioningLink).filter_by(
        school_group_id=group.id
    ).count() == 1
    assert db.query(models.BranchEntitlement).filter_by(
        school_group_id=group.id
    ).count() == len(branches) == 1
    assert sorted(status for _source, status in outcomes).count("processed") == 1


@pytest.mark.parametrize(
    "drift",
    ("branch_inventory", "quote_fingerprint", "customer", "subscription"),
)
def test_postgresql_completion_mismatch_rolls_back_all_commercial_authority(
    pg_db, monkeypatch, drift
):
    db, _engine, _factory, _applied = pg_db
    group, _branches, account, _link, plans = _fixture(db)
    activation = _prepare(db, group, account, plans["professional"])
    customer = _customer(db, account)
    monkeypatch.setattr(
        billing_identity_service,
        "ensure_provider_workspace_billing_identity",
        lambda *_args: (customer.provider_address_id, customer.provider_business_id),
    )
    monkeypatch.setattr(
        activation_service.paddle_client,
        "create_transaction",
        lambda **kwargs: _billed_transaction(kwargs, transaction_id="txn_pg_drift"),
    )
    activation_service.launch_checkout(
        db,
        activation_uuid=activation.activation_uuid,
        account=account,
        checkout_url="https://app.example.test/saas/payment",
    )
    attempt = db.get(models.PaymentAttempt, activation.current_payment_attempt_id)
    activation._attempt_uuid = attempt.attempt_uuid
    activation._account_uuid = account.account_uuid
    payload = _completed_payload(
        activation,
        customer,
        transaction_id="txn_pg_drift",
        subscription_id="sub_pg_drift",
    )
    if drift == "branch_inventory":
        db.add(operational_models.Branch(
            school_group_id=group.id, name="New Campus", status=True
        ))
    elif drift == "quote_fingerprint":
        payload["custom_data"]["quote_fingerprint"] = "wrong"
    elif drift == "customer":
        payload["customer_id"] = "ctm_wrong"
    else:
        payload["subscription_id"] = ""
    db.commit()
    result = activation_service.reconcile_webhook(
        db, {"data": payload}, "transaction.completed"
    )
    db.commit()
    assert result["status"] == "manual_review"
    assert db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.subscription_contract_id
        == activation.subscription_contract_id
    ).count() == 0
    assert db.query(models.WorkspaceEntitlement).filter_by(
        school_group_id=group.id
    ).count() == 0
    assert db.query(models.BranchEntitlement).filter_by(
        school_group_id=group.id
    ).count() == 0
    assert db.query(models.TenantProvisioningLink).filter_by(
        school_group_id=group.id
    ).count() == 0
    assert db.get(operational_models.SchoolGroup, group.id).workspace_lifecycle_status == "provisioning"


def test_account_activation_template_exposes_paid_and_promo_choices():
    account_template = open(
        "templates/saas/account.html", encoding="utf-8"
    ).read()
    activation_template = open(
        "templates/saas/existing_workspace_paid_activation.html", encoding="utf-8"
    ).read()
    assert "Choose a Plan" in account_template
    assert "Use Promo Code" in account_template
    assert "Continue to Secure Payment" in activation_template
    assert "Starter is unavailable" not in activation_template
    assert "Operational access begins only after verified payment completion" in activation_template
