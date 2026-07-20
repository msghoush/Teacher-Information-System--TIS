from datetime import datetime
from pathlib import Path
import unittest
import uuid
from unittest.mock import Mock, patch

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
from saas import (
    entitlement_service,
    paddle_client,
    service,
    subscription_change_service,
    subscription_plan_change_service,
    subscription_portal_service,
)
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
        self.billing_transactions_patcher = patch(
            "saas.billing_history_service.paddle_client.list_transactions",
            return_value=[],
        )
        self.billing_transactions_patcher.start()

    def tearDown(self):
        self.billing_transactions_patcher.stop()
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
            return {
                "account_id": account.id,
                "session_token": session_token,
                "csrf_token": _csrf_token,
                "email": email,
            }
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

    def _add_change(
        self,
        fixture,
        *,
        change_type,
        status,
        requested_quantity=None,
        target_plan_code=None,
        effective_at=None,
    ):
        db = self.Session()
        try:
            subscription = db.query(saas.models.PaymentSubscription).filter_by(
                id=fixture["subscription_id"]
            ).one()
            contract = db.query(saas.models.SubscriptionContract).filter_by(
                id=subscription.subscription_contract_id
            ).one()
            account = db.query(saas.models.SaaSAccount).filter_by(
                id=fixture["account_id"]
            ).one()
            current_price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=subscription.plan_id,
                billing_interval=subscription.billing_interval,
                currency_code=subscription.currency_code,
                provider_price_id=subscription.provider_price_id,
                is_active=True,
            ).one()
            target_plan = None
            target_price = None
            if target_plan_code:
                target_plan = db.query(saas.models.SubscriptionPlan).filter_by(
                    plan_code=target_plan_code
                ).one()
                target_price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                    plan_id=target_plan.id,
                    billing_interval=subscription.billing_interval,
                    currency_code=subscription.currency_code,
                    is_active=True,
                ).one()
                target_price.provider_price_id = (
                    target_price.provider_price_id
                    or f"pri_01portal{uuid.uuid4().hex[:12]}target"
                )
            requested_quantity = requested_quantity or subscription.quantity
            row = saas.models.SubscriptionChangeRequest(
                school_group_id=contract.school_group_id,
                subscription_contract_id=contract.id,
                payment_subscription_id=subscription.id,
                provider_subscription_id=subscription.provider_subscription_id,
                requested_by_saas_account_id=account.id,
                change_type=change_type,
                current_quantity=subscription.quantity,
                requested_quantity=requested_quantity,
                quantity_delta=requested_quantity - subscription.quantity,
                current_plan_price_id=current_price.id,
                provider_price_id=subscription.provider_price_id,
                target_plan_id=getattr(target_plan, "id", None),
                target_plan_price_id=getattr(target_price, "id", None),
                target_provider_price_id=getattr(target_price, "provider_price_id", None),
                billing_interval=subscription.billing_interval,
                currency_code=subscription.currency_code,
                effective_mode="next_billing_period",
                status=status,
                next_renewal_total_minor=(
                    target_price.amount_minor * requested_quantity
                    if target_price else subscription.unit_amount_minor * requested_quantity
                ),
                idempotency_key=f"portal-change-{uuid.uuid4().hex}",
                submitted_at=datetime(2027, 7, 18),
                effective_at=effective_at,
            )
            db.add(row)
            db.commit()
            return row.request_uuid
        finally:
            db.close()

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
            self.assertEqual(view.overview_date_label, "Next Renewal")
            self.assertEqual(view.overview_date_value, "January 15, 2027")
            self.assertEqual(view.billing_cadence_label, "year")
            self.assertTrue(view.can_increase_quantity)
            self.assertTrue(view.can_decrease_quantity)
            self.assertIn("Reporting", {group["label"] for group in view.feature_groups})
            reporting = next(group for group in view.feature_groups if group["label"] == "Reporting")
            advanced = next(feature for feature in reporting["features"] if feature["key"] == "feature.advanced_reporting")
            self.assertTrue(advanced["included"])
        finally:
            db.close()

    def test_active_overview_is_dominant_and_has_no_pending_card(self):
        fixture = self._create_subscription(
            plan_code="starter",
            quantity=2,
            active_branches=1,
            next_billed_at=datetime(2027, 8, 18),
        )
        response = self._open(fixture)
        self.assertEqual(response.status_code, 200)
        self.assertIn('aria-label="Subscription overview"', response.text)
        self.assertIn('class="plan-overview"', response.text)
        self.assertIn("Current Plan", response.text)
        self.assertIn("Starter", response.text)
        self.assertIn("Active", response.text)
        self.assertIn("per year", response.text)
        self.assertIn("August 18, 2027", response.text)
        self.assertIn("2 paid / 1 active", response.text)
        self.assertNotIn('<section class="pending-change"', response.text)
        self.assertIn("Features Included", response.text)
        self.assertIn("<details", response.text)

    def test_pending_change_card_renders_scheduled_and_processing_states(self):
        cases = (
            {
                "change_type": subscription_plan_change_service.DOWNGRADE,
                "status": "scheduled",
                "target_plan_code": "starter",
                "effective_at": datetime(2027, 8, 18),
                "expected": ("Scheduled Plan Change", "Starter", "August 18, 2027", "Cancel Scheduled Change"),
            },
            {
                "change_type": subscription_change_service.REDUCTION,
                "status": "scheduled",
                "requested_quantity": 3,
                "effective_at": datetime(2027, 8, 18),
                "expected": ("Pending branch-capacity change", "Target Paid Branches", "3", "Cancel Scheduled Reduction"),
            },
            {
                "change_type": subscription_change_service.INCREASE,
                "status": "payment_pending",
                "requested_quantity": 5,
                "expected": ("Pending branch-capacity change", "Payment confirmation pending", "5", "Processing"),
            },
        )
        for case in cases:
            with self.subTest(change_type=case["change_type"], status=case["status"]):
                fixture = self._create_subscription(
                    plan_code="professional",
                    quantity=4,
                    active_branches=2,
                    next_billed_at=datetime(2027, 9, 1),
                )
                self._add_change(
                    fixture,
                    change_type=case["change_type"],
                    status=case["status"],
                    requested_quantity=case.get("requested_quantity"),
                    target_plan_code=case.get("target_plan_code"),
                    effective_at=case.get("effective_at"),
                )
                response = self._open(fixture)
                self.assertEqual(response.status_code, 200)
                self.assertIn('<section class="pending-change"', response.text)
                for expected in case["expected"]:
                    self.assertIn(expected, response.text)
                self.assertNotIn("Subscription Actions", response.text)
                self.assertNotIn('href="/saas/subscription/cancel"', response.text)

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
        self.assertIn("Status Unavailable", manual_response.text)
        self.assertNotIn("provider_subscription_id", manual_response.text)
        self.assertNotIn("manual_review", manual_response.text)
        self.assertNotIn("Subscription Actions", manual_response.text)
        self.assertNotIn('href="/saas/subscription/branches"', manual_response.text)

    def test_subscription_statuses_are_customer_safe(self):
        for status, expected in (
            ("trialing", "Trial"),
            ("past_due", "Payment Issue"),
            ("paused", "Paused"),
            ("canceled", "Canceled"),
            ("expired", "Expired"),
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
                self.assertNotIn("Subscription Actions", response.text)
                self.assertNotIn('href="/saas/subscription/cancel"', response.text)
                self.assertNotIn('href="/saas/subscription/branches"', response.text)

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
            "Cancel Subscription",
        ):
            self.assertIn(label, response.text)
        self.assertIn("Billing History", response.text)
        self.assertIn("Invoice History", response.text)
        self.assertNotIn("Coming Soon", response.text)
        self.assertIn("Subscription Actions", response.text)
        self.assertIn("features-disclosure", response.text)
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
        self.assertIn("overview-grid", template)
        self.assertIn("plan-overview", template)
        self.assertIn("features-disclosure", template)
        self.assertGreaterEqual(template.lower().count("<form"), 2)
        self.assertIn('/saas/subscription/plans/preview', template)
        self.assertIn("cancel scheduled reduction", template.lower())
        self.assertNotIn("/upgrade", template.lower())
        self.assertNotIn("PADDLE_API_KEY", template)
        self.assertNotIn("provider_", template)
        self.assertNotIn("Coming Soon", template)
        self.assertIn("Billing History", template)
        self.assertIn("Invoice History", template)

    def test_individual_action_visibility_uses_lifecycle_allowed_actions(self):
        fixture = self._create_subscription(
            plan_code="starter",
            quantity=1,
            active_branches=1,
            next_billed_at=datetime(2027, 8, 18),
        )
        response = self._open(fixture)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Add Branch Capacity", response.text)
        self.assertNotIn("Reduce Branch Capacity", response.text)
        self.assertIn("Upgrade Plan", response.text)
        self.assertNotIn("Downgrade Plan", response.text)
        self.assertIn('action="/saas/subscription/plans/preview"', response.text)
        self.assertIn('href="/saas/subscription/branches"', response.text)

    def test_cancellation_actions_follow_central_lifecycle_policy(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=4,
            active_branches=2,
            next_billed_at=datetime(2027, 8, 18),
        )
        active = self._open(fixture)
        self.assertEqual(active.status_code, 200)
        self.assertIn("Cancel Subscription", active.text)
        self.assertIn("Your subscription renews on", active.text)
        self.assertNotIn("tenant_active", active.text)
        self.assertNotIn("payment_processing", active.text)

        confirmation = self.client.get("/saas/subscription/cancel", follow_redirects=False)
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("Cancel subscription at period end", confirmation.text)
        self.assertIn("August 18, 2027", confirmation.text)
        self.assertIn("remains active through the current paid period", confirmation.text)

        db = self.Session()
        try:
            subscription = db.query(saas.models.PaymentSubscription).get(fixture["subscription_id"])
            contract = db.query(saas.models.SubscriptionContract).get(subscription.subscription_contract_id)
            account = db.query(saas.models.SaaSAccount).get(fixture["account_id"])
            plan_price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=subscription.plan_id,
                billing_interval=subscription.billing_interval,
                currency_code=subscription.currency_code,
                provider_price_id=subscription.provider_price_id,
                is_active=True,
            ).one()
            request_row = saas.models.SubscriptionChangeRequest(
                school_group_id=contract.school_group_id,
                subscription_contract_id=contract.id,
                payment_subscription_id=subscription.id,
                provider_subscription_id=subscription.provider_subscription_id,
                requested_by_saas_account_id=account.id,
                change_type="subscription_cancellation",
                current_quantity=subscription.quantity,
                requested_quantity=subscription.quantity,
                quantity_delta=0,
                current_plan_price_id=plan_price.id,
                provider_price_id=subscription.provider_price_id,
                billing_interval=subscription.billing_interval,
                currency_code=subscription.currency_code,
                effective_mode="next_billing_period",
                status="scheduled",
                idempotency_key=f"portal-cancel-{uuid.uuid4().hex}",
                submitted_at=datetime(2027, 7, 18),
                provider_scheduled_at=datetime(2027, 7, 18),
                effective_at=datetime(2027, 8, 18),
            )
            db.add(request_row)
            subscription.cancel_at_period_end = True
            db.commit()
        finally:
            db.close()

        scheduled = self._open(fixture)
        self.assertIn("Scheduled Cancellation", scheduled.text)
        self.assertIn("Cancellation scheduled", scheduled.text)
        self.assertNotIn("Reduction scheduled", scheduled.text)
        self.assertIn("August 18, 2027", scheduled.text)
        self.assertIn("Keep Subscription", scheduled.text)
        self.assertNotIn("Subscription Actions", scheduled.text)
        self.assertNotIn('href="/saas/subscription/cancel"', scheduled.text)
        self.assertNotIn('action="/saas/subscription/plans/preview"', scheduled.text)
        self.assertNotIn('href="/saas/subscription/branches"', scheduled.text)

    def test_unauthorized_customer_never_sees_cancellation_action(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=3,
            active_branches=1,
        )
        db = self.Session()
        try:
            link = db.query(saas.models.SaaSAccountUserLink).filter_by(
                saas_account_id=fixture["account_id"]
            ).one()
            user = db.query(models.User).get(link.operational_user_id)
            user.role = auth.ROLE_LIMITED
            db.commit()
        finally:
            db.close()

        response = self._open(fixture)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Cancel Subscription", response.text)
        self.assertNotIn("Subscription Actions", response.text)
        self.assertNotIn('href="/saas/subscription/branches"', response.text)
        self.assertNotIn('action="/saas/subscription/plans/preview"', response.text)
        denied = self.client.get("/saas/subscription/cancel", follow_redirects=False)
        self.assertEqual(denied.status_code, 302)

    def test_billing_history_and_invoices_use_provider_transactions_in_chronological_order(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=4,
            active_branches=2,
            next_billed_at=datetime(2027, 8, 18),
        )
        db = self.Session()
        try:
            subscription = db.query(saas.models.PaymentSubscription).get(fixture["subscription_id"])
            provider_subscription_id = subscription.provider_subscription_id
        finally:
            db.close()
        transactions = [
            {
                "id": "txn_01failedrenewaltransaction",
                "subscription_id": provider_subscription_id,
                "customer_id": "ctm_01billingcustomer",
                "status": "past_due",
                "origin": "subscription_recurring",
                "collection_mode": "automatic",
                "invoice_number": None,
                "billed_at": "2027-07-18T10:00:00Z",
                "created_at": "2027-07-18T09:00:00Z",
                "currency_code": "USD",
                "details": {"totals": {"grand_total": "31600"}},
                "adjustments": [],
            },
            {
                "id": "txn_01olderbillingtransaction",
                "subscription_id": provider_subscription_id,
                "customer_id": "ctm_01billingcustomer",
                "status": "completed",
                "origin": "web",
                "collection_mode": "automatic",
                "invoice_number": "100-00001",
                "billed_at": "2027-07-01T10:00:00Z",
                "created_at": "2027-07-01T09:00:00Z",
                "currency_code": "USD",
                "details": {"totals": {"grand_total": "31600"}},
                "adjustments": [],
            },
            {
                "id": "txn_01newerbillingtransaction",
                "subscription_id": provider_subscription_id,
                "customer_id": "ctm_01billingcustomer",
                "status": "completed",
                "origin": "subscription_update",
                "collection_mode": "automatic",
                "invoice_number": "100-00002",
                "billed_at": "2027-07-16T10:00:00Z",
                "created_at": "2027-07-16T09:00:00Z",
                "currency_code": "USD",
                "details": {"totals": {"grand_total": "7556"}},
                "adjustments": [{
                    "action": "credit",
                    "status": "approved",
                    "created_at": "2027-07-17T10:00:00Z",
                    "totals": {"total": "1200"},
                }],
            },
        ]
        with patch(
            "saas.billing_history_service.paddle_client.list_transactions",
            return_value=transactions,
        ):
            response = self._open(fixture)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Billing Summary", response.text)
        self.assertIn("Annual Cost", response.text)
        self.assertIn("$316.00", response.text)
        self.assertIn("Prorated subscription change", response.text)
        self.assertIn("Payment Failed", response.text)
        self.assertIn("-$12.00", response.text)
        self.assertIn("100-00001", response.text)
        self.assertIn("100-00002", response.text)
        self.assertIn("Download Invoice", response.text)
        history_section = response.text.split(">Billing History<", 1)[1].split(">Invoice History<", 1)[0]
        self.assertLess(history_section.index("July 18, 2027"), history_section.index("July 17, 2027"))
        self.assertLess(history_section.index("July 17, 2027"), history_section.index("July 16, 2027"))
        self.assertLess(history_section.index("July 16, 2027"), history_section.index("July 01, 2027"))

    def test_empty_billing_history_has_professional_empty_states(self):
        fixture = self._create_subscription(
            plan_code="starter",
            quantity=1,
            active_branches=1,
        )
        response = self._open(fixture)
        self.assertEqual(response.status_code, 200)
        self.assertIn("No billing history is available.", response.text)
        self.assertIn("No invoices yet.", response.text)
        self.assertNotIn("<tbody>\n                </tbody>", response.text)

    def test_provider_failure_is_customer_safe_and_does_not_expose_diagnostics(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=4,
            active_branches=2,
        )
        provider_errors = (
            paddle_client.PaddleAPIError(
                "secret provider detail",
                status_code=503,
                body={"error": {"code": "provider_secret_code", "detail": "secret provider detail"}},
            ),
            paddle_client.httpx.ConnectError("private network diagnostic"),
        )
        for provider_error in provider_errors:
            with self.subTest(error_type=type(provider_error).__name__), patch(
                "saas.billing_history_service.paddle_client.list_transactions",
                side_effect=provider_error,
            ):
                response = self._open(fixture)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Billing history is temporarily unavailable.", response.text)
                self.assertIn("Invoices are temporarily unavailable.", response.text)
                self.assertIn("Try Again", response.text)
                self.assertNotIn("secret provider detail", response.text)
                self.assertNotIn("provider_secret_code", response.text)
                self.assertNotIn("private network diagnostic", response.text)

    def test_unauthorized_user_cannot_see_or_download_billing_documents(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=3,
            active_branches=1,
        )
        db = self.Session()
        try:
            link = db.query(saas.models.SaaSAccountUserLink).filter_by(
                saas_account_id=fixture["account_id"]
            ).one()
            user = db.query(models.User).get(link.operational_user_id)
            user.role = auth.ROLE_LIMITED
            db.commit()
        finally:
            db.close()
        with patch(
            "saas.billing_history_service.paddle_client.list_transactions"
        ) as provider_call:
            response = self._open(fixture)
            denied = self.client.get(
                "/saas/subscription/invoices/100-00001/download",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Billing Summary", response.text)
        self.assertNotIn("Billing History", response.text)
        self.assertNotIn("Invoice History", response.text)
        self.assertEqual(denied.status_code, 403)
        provider_call.assert_not_called()

    def test_invoice_download_reauthorizes_and_redirects_to_fresh_paddle_url(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=4,
            active_branches=2,
        )
        db = self.Session()
        try:
            subscription = db.query(saas.models.PaymentSubscription).get(fixture["subscription_id"])
            provider_subscription_id = subscription.provider_subscription_id
        finally:
            db.close()
        transaction = {
            "id": "txn_01downloadinvoice",
            "subscription_id": provider_subscription_id,
            "customer_id": "ctm_01billingcustomer",
            "status": "completed",
            "origin": "subscription_recurring",
            "collection_mode": "automatic",
            "invoice_number": "100-00009",
            "billed_at": "2027-07-18T10:00:00Z",
            "currency_code": "USD",
            "details": {"totals": {"grand_total": "31600"}},
        }
        invoice_url = "https://paddle-invoices.example.test/invoice.pdf"
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, fixture["session_token"])
        with (
            patch(
                "saas.billing_history_service.paddle_client.list_transactions",
                return_value=[transaction],
            ),
            patch(
                "saas.billing_history_service.paddle_client.get_transaction_invoice",
                return_value={"url": invoice_url},
            ) as invoice_call,
            patch("saas.billing_history_service.audit.write_audit_event") as audit_call,
        ):
            response = self.client.get(
                "/saas/subscription/invoices/100-00009/download",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], invoice_url)
        invoice_call.assert_called_once_with(
            transaction_id="txn_01downloadinvoice",
            disposition="attachment",
        )
        audit_call.assert_called_once()

    def test_invoice_download_rejects_unrelated_provider_transaction(self):
        fixture = self._create_subscription(
            plan_code="professional",
            quantity=4,
            active_branches=2,
        )
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, fixture["session_token"])
        with (
            patch(
                "saas.billing_history_service.paddle_client.list_transactions",
                return_value=[{
                    "id": "txn_01unrelatedinvoice",
                    "subscription_id": "sub_01anothercustomer",
                    "status": "completed",
                    "collection_mode": "automatic",
                    "invoice_number": "100-00010",
                    "details": {"totals": {"grand_total": "31600"}},
                }],
            ),
            patch(
                "saas.billing_history_service.paddle_client.get_transaction_invoice"
            ) as invoice_call,
        ):
            response = self.client.get(
                "/saas/subscription/invoices/100-00010/download",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("Invoice+is+unavailable", response.headers["location"])
        invoice_call.assert_not_called()


class PaddleBillingHistoryClientTests(unittest.TestCase):
    def test_list_transactions_follows_provider_pagination(self):
        first = Mock()
        first.status_code = 200
        first.json.return_value = {
            "data": [{"id": "txn_first"}],
            "meta": {"pagination": {
                "has_more": True,
                "next": "https://sandbox-api.paddle.com/transactions?subscription_id=sub_01valid&after=txn_first&per_page=30",
            }},
        }
        second = Mock()
        second.status_code = 200
        second.json.return_value = {
            "data": [{"id": "txn_second"}],
            "meta": {"pagination": {"has_more": False, "next": None}},
        }
        with (
            patch.dict("os.environ", {"PADDLE_API_KEY": "test-key"}),
            patch("saas.paddle_client.httpx.request", side_effect=[first, second]) as request_call,
        ):
            rows = paddle_client.list_transactions(subscription_id="sub_01valid")
        self.assertEqual([row["id"] for row in rows], ["txn_first", "txn_second"])
        self.assertEqual(request_call.call_count, 2)
        self.assertEqual(request_call.call_args_list[1].kwargs["params"]["after"], "txn_first")

    def test_invoice_client_uses_read_only_invoice_endpoint(self):
        with patch("saas.paddle_client._request", return_value={"url": "https://example.test/invoice.pdf"}) as request_call:
            result = paddle_client.get_transaction_invoice(
                transaction_id="txn_01valid",
                disposition="attachment",
            )
        self.assertEqual(result["url"], "https://example.test/invoice.pdf")
        request_call.assert_called_once_with(
            "GET",
            "/transactions/txn_01valid/invoice",
            params={"disposition": "attachment"},
        )


if __name__ == "__main__":
    unittest.main()
