from datetime import datetime
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db_migrations
import models
import saas.models
from dependencies import get_db
from saas import service
from saas.router import router as saas_router


class SaaSPostActivationStateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        models.Base.metadata.create_all(bind=self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.app = FastAPI()
        self.app.mount("/static", StaticFiles(directory="static"), name="static")
        self.app.include_router(saas_router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _fixture(self, *, paid=True, provisioned=True):
        db = self.Session()
        unique = uuid.uuid4().hex[:10]
        try:
            email = f"active-{unique}@example.com"
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()), email=email, email_normalized=email,
                password_hash=auth.get_password_hash("account-password-123"), first_name="Active",
                last_name="Owner", status="active", onboarding_status="checkout_ready",
                email_verified_at=datetime(2026, 7, 1),
            )
            db.add(account); db.flush()
            session_token, csrf_token, _ = service.create_session(db, account)
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").one()
            price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=plan.id, billing_interval="monthly", currency_code="USD", is_active=True
            ).one()
            price.provider_price_id = price.provider_price_id or "pri_01postactivationstate000000"
            organization = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()), owner_saas_account_id=account.id,
                organization_name="Confirmed Active Academy", status="ready_for_checkout",
                onboarding_step="review", billing_status="checkout_ready",
                payment_status="paid" if paid else "pending", selected_plan_id=plan.id,
                selected_billing_interval="monthly", educational_program="BOTH", timezone="UTC",
                payment_confirmed_at=datetime(2026, 7, 1) if paid else None,
            )
            db.add(organization); db.flush()
            db.add(saas.models.PendingOrganizationBranch(
                pending_organization_id=organization.id, branch_uuid=str(uuid.uuid4()),
                branch_name="Main Campus", status=True,
            ))
            db.add(saas.models.PendingOrganizationAcademicSetup(
                pending_organization_id=organization.id, first_academic_year_name="2026-2027"
            ))
            db.add(saas.models.PendingOrganizationContact(
                pending_organization_id=organization.id, contact_type="owner", is_primary=True,
                first_name="Active", last_name="Owner", email=email, email_normalized=email,
            ))
            selection = saas.models.PendingOrganizationPlanSelection(
                pending_organization_id=organization.id, plan_id=plan.id, billing_interval="monthly",
                base_currency_code="USD", base_amount_minor=price.amount_minor,
                display_currency_code="USD", display_amount_minor=price.amount_minor,
                selection_status="selected", billable_branch_count=3,
            )
            db.add(selection); db.flush()
            checkout = saas.models.CheckoutSession(
                pending_organization_id=organization.id, plan_selection_id=selection.id,
                status="started", provider="paddle", checkout_url="https://old-checkout.example/transaction",
                currency_code="USD", amount_minor=price.amount_minor * 3,
                billing_interval="monthly", provider_price_id=price.provider_price_id,
                billable_branch_count=3,
            )
            db.add(checkout); db.flush()
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id, plan_id=plan.id, billing_interval="monthly",
                contract_status="tenant_active" if provisioned else "paid_pending_provisioning",
                base_currency_code="USD", base_amount_minor=price.amount_minor,
                display_currency_code="USD", display_amount_minor=price.amount_minor,
                billable_branch_count=3, selected_checkout_session_id=checkout.id,
                payment_status="paid" if paid else "pending",
                paid_at=datetime(2026, 7, 1) if paid else None,
            )
            db.add(contract); db.flush()
            subscription = None
            if paid:
                subscription = saas.models.PaymentSubscription(
                    pending_organization_id=organization.id, subscription_contract_id=contract.id,
                    provider="paddle", provider_subscription_id=f"sub_{uuid.uuid4().hex}",
                    provider_price_id=price.provider_price_id, plan_id=plan.id,
                    billing_interval="monthly", currency_code="USD", quantity=3,
                    unit_amount_minor=price.amount_minor, amount_minor=price.amount_minor * 3,
                    status="active", next_billed_at=datetime(2026, 8, 1),
                )
                db.add(subscription); db.flush()
            group = None
            if provisioned:
                group = models.SchoolGroup(name=f"Confirmed Active Academy {unique}", status=True)
                db.add(group); db.flush()
                branch = models.Branch(school_group_id=group.id, name="Main Campus", status=True)
                db.add(branch); db.flush()
                user = models.User(
                    user_id=unique, username=f"active.{unique}", email=email, email_normalized=email,
                    password="unused", role=auth.ROLE_ADMINISTRATOR, school_group_id=group.id,
                    branch_id=branch.id, access_scope=auth.ACCESS_SCOPE_ORGANIZATION, is_active=True,
                )
                db.add(user); db.flush()
                contract.school_group_id = group.id
                tenant_link = saas.models.TenantProvisioningLink(
                    pending_organization_id=organization.id, subscription_contract_id=contract.id,
                    school_group_id=group.id, owner_operational_user_id=user.id,
                    primary_branch_id=branch.id, tenant_status="tenant_active",
                    activated_at=datetime(2026, 7, 1),
                )
                db.add(tenant_link); db.flush()
                db.add(saas.models.SaaSAccountUserLink(
                    saas_account_id=account.id, operational_user_id=user.id,
                    pending_organization_id=organization.id, school_group_id=group.id,
                    link_type="tenant_owner",
                ))
            if paid:
                db.add(saas.models.ProvisioningJob(
                    pending_organization_id=organization.id, subscription_contract_id=contract.id,
                    job_uuid=str(uuid.uuid4()), idempotency_key=f"state-{unique}",
                    job_status="completed" if provisioned else "queued",
                    target_school_group_id=group.id if group else None,
                    completed_at=datetime(2026, 7, 1) if provisioned else None,
                ))
            db.commit()
            return {
                "account_id": account.id, "organization_id": organization.id,
                "organization_uuid": organization.organization_uuid,
                "subscription_id": subscription.id if subscription else None,
                "session_token": session_token, "csrf_token": csrf_token,
            }
        finally:
            db.close()

    def _authenticate(self, fixture):
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, fixture["session_token"])
        self.client.cookies.set(service.SAAS_CSRF_COOKIE, fixture["csrf_token"])

    def test_active_tenant_outranks_stale_checkout_state_on_account_setup(self):
        fixture = self._fixture(paid=True, provisioned=True)
        self._authenticate(fixture)
        response = self.client.get("/saas/account")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Workspace Activation is complete", response.text)
        self.assertIn("Enter TIS Platform", response.text)
        self.assertNotIn("Continue to Secure Payment", response.text)
        self.assertIn('data-setup-step="secure_payment" data-setup-state="complete"', response.text)
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=fixture["account_id"]).one()
            organization = db.query(saas.models.PendingOrganization).filter_by(id=fixture["organization_id"]).one()
            self.assertEqual(account.onboarding_status, "tenant_active")
            self.assertEqual(organization.billing_status, "checkout_ready")
        finally:
            db.close()

    def test_active_tenant_cannot_reopen_or_reprepare_initial_checkout(self):
        fixture = self._fixture(paid=True, provisioned=True)
        self._authenticate(fixture)
        db = self.Session()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=fixture["organization_id"]).one()
            before = (
                db.query(saas.models.CheckoutSession).filter_by(pending_organization_id=organization.id).count(),
                db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).count(),
                db.query(saas.models.PaymentSubscription).filter_by(pending_organization_id=organization.id).count(),
            )
        finally:
            db.close()
        with patch("saas.paddle_client.create_transaction") as create_transaction:
            for path in (
                f"/saas/onboarding/{fixture['organization_uuid']}/plan",
                f"/saas/onboarding/{fixture['organization_uuid']}/checkout",
            ):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["location"].startswith("/saas/subscription?notice="))
            for path in (
                f"/saas/onboarding/{fixture['organization_uuid']}/checkout/start",
                f"/saas/onboarding/{fixture['organization_uuid']}/checkout/launch",
            ):
                response = self.client.post(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["location"].startswith("/saas/subscription?notice="))
        create_transaction.assert_not_called()
        db = self.Session()
        try:
            after = (
                db.query(saas.models.CheckoutSession).filter_by(pending_organization_id=fixture["organization_id"]).count(),
                db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=fixture["organization_id"]).count(),
                db.query(saas.models.PaymentSubscription).filter_by(pending_organization_id=fixture["organization_id"]).count(),
            )
            self.assertEqual(after, before)
        finally:
            db.close()

    def test_unpaid_ready_account_still_sees_secure_payment(self):
        fixture = self._fixture(paid=False, provisioned=False)
        self._authenticate(fixture)
        response = self.client.get("/saas/account")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Continue to Secure Payment", response.text)
        self.assertIn("Next step: complete Secure Payment", response.text)

    def test_confirmed_payment_with_pending_provisioning_shows_activation_state(self):
        fixture = self._fixture(paid=True, provisioned=False)
        self._authenticate(fixture)
        response = self.client.get("/saas/account")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Workspace Activation is in progress", response.text)
        self.assertIn("Payment is confirmed", response.text)
        self.assertNotIn("Continue to Secure Payment", response.text)
        self.assertIn('data-setup-step="workspace_activation" data-setup-state="current"', response.text)


if __name__ == "__main__":
    unittest.main()
