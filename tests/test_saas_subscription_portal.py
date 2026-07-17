from datetime import datetime
from pathlib import Path
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
from saas import entitlement_service, paddle_client, service, subscription_portal_service
from saas.router import router as saas_router


class SaaSSubscriptionPortalTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
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

    def _create_account(self, *, email=None):
        db = self.Session()
        try:
            unique = uuid.uuid4().hex[:10]
            email = email or f"portal-{unique}@example.com"
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=email,
                email_normalized=email,
                password_hash=auth.get_password_hash("strong-password-123"),
                first_name="Portal",
                last_name="Customer",
                status="active",
                onboarding_status="tenant_active",
                email_verified_at=datetime(2026, 7, 1),
            )
            db.add(account)
            db.flush()
            session_token, _csrf_token, _session = service.create_session(db, account)
            db.commit()
            return {"account_id": account.id, "session_token": session_token, "email": email}
        finally:
            db.close()

    def _create_subscription(
        self,
        *,
        plan_code,
        quantity,
        active_branches,
        status="active",
        next_billed_at=None,
        email=None,
    ):
        account_data = self._create_account(email=email)
        db = self.Session()
        try:
            unique = uuid.uuid4().hex[:10]
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_data["account_id"]).one()
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code=plan_code).one()
            price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=plan.id,
                billing_interval="annual",
                currency_code="USD",
                is_active=True,
            ).one()
            price.provider_price_id = price.provider_price_id or f"pri_01portal{unique}annualprice"
            group = models.SchoolGroup(name=f"Portal School {unique}")
            db.add(group)
            db.flush()
            branches = []
            for index in range(active_branches):
                branch = models.Branch(
                    school_group_id=group.id,
                    name=f"Portal Branch {index + 1} {unique}",
                    status=True,
                )
                db.add(branch)
                branches.append(branch)
            db.flush()
            owner = models.User(
                user_id=unique,
                username=f"portal.{unique}",
                email=account.email,
                email_normalized=account.email_normalized,
                password="unused",
                role=auth.ROLE_ADMINISTRATOR,
                school_group_id=group.id,
                branch_id=branches[0].id if branches else None,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
                is_active=True,
            )
            db.add(owner)
            db.flush()
            organization = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=account.id,
                organization_name=f"Portal Organization {unique}",
                status="tenant_active",
                onboarding_step="completed",
                billing_status="tenant_active",
                payment_status="paid",
                payment_confirmed_at=datetime(2026, 7, 1),
            )
            db.add(organization)
            db.flush()
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id,
                school_group_id=group.id,
                plan_id=plan.id,
                billing_interval="annual",
                contract_status="tenant_active",
                payment_status="paid",
                paid_at=datetime(2026, 7, 1),
                base_amount_minor=79000,
                display_amount_minor=79000,
            )
            db.add(contract)
            db.flush()
            subscription = saas.models.PaymentSubscription(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                provider="paddle",
                provider_subscription_id=f"sub_{uuid.uuid4().hex}",
                provider_price_id=price.provider_price_id,
                plan_id=plan.id,
                billing_interval="annual",
                currency_code="USD",
                quantity=quantity,
                unit_amount_minor=price.amount_minor,
                amount_minor=price.amount_minor * quantity,
                status=status,
                next_billed_at=next_billed_at,
            )
            db.add(subscription)
            db.flush()
            db.add(saas.models.TenantProvisioningLink(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                school_group_id=group.id,
                owner_operational_user_id=owner.id,
                primary_branch_id=branches[0].id if branches else None,
                tenant_status="tenant_active",
                activated_at=datetime(2026, 7, 1),
            ))
            db.add(saas.models.SaaSAccountUserLink(
                saas_account_id=account.id,
                operational_user_id=owner.id,
                pending_organization_id=organization.id,
                school_group_id=group.id,
                link_type="tenant_owner",
            ))
            db.commit()
            return {
                **account_data,
                "group_id": group.id,
                "subscription_id": subscription.id,
                "plan_name": plan.plan_name,
            }
        finally:
            db.close()

    def _open(self, fixture):
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, fixture["session_token"])
        return self.client.get("/saas/subscription", follow_redirects=False)

    def test_starter_professional_and_enterprise_pages_render(self):
        cases = (
            ("starter", "Starter", "Not Included"),
            ("professional", "Professional", "Advanced Reporting"),
            ("enterprise_ai", "Enterprise AI", "AI"),
        )
        for plan_code, plan_name, expected_feature in cases:
            with self.subTest(plan=plan_code):
                fixture = self._create_subscription(
                    plan_code=plan_code,
                    quantity=5,
                    active_branches=2,
                    next_billed_at=datetime(2027, 7, 1),
                )
                response = self._open(fixture)
                self.assertEqual(response.status_code, 200)
                self.assertIn(plan_name, response.text)
                self.assertIn(expected_feature, response.text)
                self.assertIn("Paid Branches", response.text)
                self.assertIn("Available Branch Capacity", response.text)
                self.assertIn("July 01, 2027", response.text)

    def test_portal_view_uses_resolver_quantities_and_feature_groups(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=20,
            active_branches=16,
            next_billed_at=datetime(2027, 1, 15),
        )
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=fixture["account_id"]).one()
            view = subscription_portal_service.build_subscription_portal(db, account)
            self.assertEqual(view.paid_branch_quantity, 20)
            self.assertEqual(view.active_branch_count, 16)
            self.assertEqual(view.remaining_paid_capacity, 4)
            self.assertEqual(view.next_billing_date_label, "January 15, 2027")
            self.assertIn("Reporting", {group["label"] for group in view.feature_groups})
            reporting = next(group for group in view.feature_groups if group["label"] == "Reporting")
            advanced = next(feature for feature in reporting["features"] if feature["key"] == "feature.advanced_reporting")
            self.assertTrue(advanced["included"])
        finally:
            db.close()

    def test_missing_subscription_and_manual_review_are_customer_safe(self):
        missing = self._create_account(email="missing-portal@example.com")
        missing_response = self._open(missing)
        self.assertEqual(missing_response.status_code, 200)
        self.assertIn("Missing Subscription", missing_response.text)
        self.assertIn("Not Available", missing_response.text)

        manual = self._create_subscription(
            plan_code="professional",
            quantity=3,
            active_branches=1,
        )
        db = self.Session()
        try:
            subscription = db.query(saas.models.PaymentSubscription).filter_by(
                id=manual["subscription_id"]
            ).one()
            subscription.plan_id = db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code="starter"
            ).one().id
            db.commit()
        finally:
            db.close()
        manual_response = self._open(manual)
        self.assertEqual(manual_response.status_code, 200)
        self.assertIn("Manual Review", manual_response.text)
        self.assertNotIn("provider_subscription_id", manual_response.text)

    def test_subscription_statuses_are_customer_safe(self):
        for status, expected in (
            ("trialing", "Trial"),
            ("past_due", "Past Due"),
            ("paused", "Paused"),
            ("canceled", "Canceled"),
        ):
            with self.subTest(status=status):
                fixture = self._create_subscription(
                    plan_code="professional",
                    quantity=2,
                    active_branches=1,
                    status=status,
                )
                response = self._open(fixture)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, response.text)
                if status != "trialing":
                    self.assertIn("Not Included", response.text)

    def test_customer_tenant_isolation_and_read_only_behavior(self):
        first = self._create_subscription(
            plan_code="starter",
            quantity=7,
            active_branches=1,
            next_billed_at=datetime(2027, 3, 11),
        )
        second = self._create_subscription(
            plan_code="enterprise_ai",
            quantity=13,
            active_branches=2,
            next_billed_at=datetime(2028, 4, 22),
        )
        db = self.Session()
        try:
            before = {
                "subscriptions": db.query(saas.models.PaymentSubscription).count(),
                "branches": db.query(models.Branch).count(),
            }
        finally:
            db.close()
        with (
            patch.object(paddle_client, "create_transaction") as create_transaction,
            patch.object(paddle_client, "update_customer") as update_customer,
        ):
            response = self._open(first)
        self.assertEqual(response.status_code, 200)
        self.assertIn("March 11, 2027", response.text)
        self.assertNotIn("April 22, 2028", response.text)
        create_transaction.assert_not_called()
        update_customer.assert_not_called()
        db = self.Session()
        try:
            self.assertEqual(db.query(saas.models.PaymentSubscription).count(), before["subscriptions"])
            self.assertEqual(db.query(models.Branch).count(), before["branches"])
            first_resolution = entitlement_service.resolve_customer_entitlements(
                db,
                db.query(saas.models.SaaSAccount).filter_by(id=first["account_id"]).one(),
            )
            self.assertEqual(first_resolution.school_group_id, first["group_id"])
            self.assertNotEqual(first_resolution.school_group_id, second["group_id"])
        finally:
            db.close()

    def test_navigation_future_actions_and_platform_access_boundary(self):
        fixture = self._create_subscription(plan_code="professional", quantity=2, active_branches=1)
        response = self._open(fixture)
        self.assertIn('href="/saas/subscription"', response.text)
        for label in (
            "Preview Upgrade",
            "Preview Downgrade",
            "Add Branch Capacity",
            "Reduce Branch Capacity",
            "Billing History",
            "Invoices",
            "Manage Subscription",
        ):
            self.assertIn(label, response.text)
        self.assertGreaterEqual(response.text.count("disabled"), 1)
        self.client.cookies.clear()
        db = self.Session()
        try:
            platform_user = models.User(
                user_id="PLAT000001",
                username="portal.platform",
                email="portal-platform@example.com",
                email_normalized="portal-platform@example.com",
                password=auth.get_password_hash("platform-password-123"),
                role=auth.ROLE_ADMINISTRATOR,
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_OWNER,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(platform_user)
            db.commit()
            with patch.dict("os.environ", {"TIS_SESSION_SECRET": "portal-test-secret-at-least-32-characters"}):
                self.client.cookies.set(auth.SESSION_COOKIE_KEY, auth.create_session_token(platform_user))
        finally:
            db.close()
        denied = self.client.get("/saas/subscription", follow_redirects=False)
        self.assertEqual(denied.status_code, 302)
        self.assertTrue(denied.headers["location"].startswith("/saas/login"))

    def test_portal_template_has_responsive_layout_and_only_approved_mutation_control(self):
        template = Path("templates/saas/subscription.html").read_text(encoding="utf-8")
        self.assertIn("@media (max-width:900px)", template)
        self.assertIn("@media (max-width:640px)", template)
        self.assertIn("grid-template-columns:1fr", template)
        self.assertGreaterEqual(template.lower().count("<form"), 2)
        self.assertIn('/saas/subscription/plans/preview', template)
        self.assertIn("cancel scheduled reduction", template.lower())
        self.assertNotIn("/upgrade", template.lower())
        self.assertNotIn("PADDLE_API_KEY", template)
        self.assertNotIn("provider_", template)


if __name__ == "__main__":
    unittest.main()
