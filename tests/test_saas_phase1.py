import os
import re
import json
import hashlib
import hmac
import time
import unittest
from unittest.mock import patch

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"
os.environ["PADDLE_API_KEY"] = "pdl_test_phase4_api_key"
os.environ["PADDLE_WEBHOOK_SECRET"] = "pdl_ntfset_test_phase4_secret"
os.environ["PADDLE_WEBHOOK_TOLERANCE_SECONDS"] = "30"

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import auth
import models
import saas.models  # noqa: F401 - register metadata
from dependencies import get_db
from saas import oauth, service
from saas.router import admin_router as saas_admin_router, router as saas_router


class SaaSPhase1Tests(unittest.TestCase):
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
        self.app.include_router(saas_admin_router)

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

    def _db(self):
        return self.Session()

    def _operational_counts(self):
        db = self._db()
        try:
            return {
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "academic_years": db.query(models.AcademicYear).count(),
                "users": db.query(models.User).count(),
                "role_permissions": db.query(models.RolePermission).count(),
            }
        finally:
            db.close()

    def _configure_paddle_prices(self):
        db = self._db()
        try:
            price_rows = db.query(saas.models.SubscriptionPlanPrice).all()
            for row in price_rows:
                row.provider_price_id = f"pri_test_{row.plan_id}_{row.billing_interval}"
            db.commit()
        finally:
            db.close()

    def _sign_paddle_payload(self, payload: dict) -> tuple[str, bytes]:
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(
            os.environ["PADDLE_WEBHOOK_SECRET"].encode("utf-8"),
            f"{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"ts={timestamp};h1={signature}", raw_body

    def _signup_and_verify(self, email="owner@school.edu"):
        captured = {}

        def fake_send_email(**kwargs):
            captured["text"] = kwargs["text"]
            return "email_456"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Owner",
                    "last_name": "User",
                    "email": email,
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                },
                follow_redirects=False,
            )

        token_match = re.search(r"token=([A-Za-z0-9._\-]+)", captured["text"])
        self.assertIsNotNone(token_match)
        token = token_match.group(1)
        verify_response = self.client.get(f"/saas/auth/verify-email?token={token}")
        self.assertEqual(verify_response.status_code, 200)
        login_response = self.client.post(
            "/saas/auth/login",
            data={"email": email, "password": "strong-password-123", "next_path": "/saas/account"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers["location"], "/saas/account")

    def _start_pending_organization(self):
        start_response = self.client.post("/saas/onboarding/start", follow_redirects=False)
        self.assertEqual(start_response.status_code, 302)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).order_by(
                saas.models.PendingOrganization.id.desc()
            ).first()
            self.assertIsNotNone(organization)
            return organization.organization_uuid
        finally:
            db.close()

    def _complete_pending_organization_to_ready_for_checkout(self, email="leader@academy.edu"):
        self._signup_and_verify(email)
        org_uuid = self._start_pending_organization()

        organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Andalus Academy",
                "legal_name": "Andalus Academy LLC",
                "website": "https://andalus.example.com",
                "primary_domain": "andalus.example.com",
                "phone": "+9665000000",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Makkah",
                "city_name": "Jeddah",
                "district_name": "Al Zahra",
                "neighborhood_name": "North",
                "school_type": "K-12",
                "expected_branch_count": "2",
                "expected_student_count": "1200",
                "expected_teacher_count": "90",
                "estimated_staff_users": "35",
                "timezone": "Asia/Riyadh",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(organization_response.status_code, 302)

        branches_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={
                "branch_name": ["Main Campus", "Girls Campus"],
                "location": ["Central", "North"],
                "country_code": ["SA", "SA"],
                "country_name": ["Saudi Arabia", "Saudi Arabia"],
                "region_name": ["Makkah", "Makkah"],
                "city_name": ["Jeddah", "Jeddah"],
                "district_name": ["Al Zahra", "Al Nahda"],
                "neighborhood_name": ["North", "East"],
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(branches_response.status_code, 302)

        academic_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/academic_setup",
            data={
                "first_academic_year_name": "2026-2027",
                "create_default_branch": "1",
                "notes": "Launch year",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(academic_response.status_code, 302)

        contacts_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/contacts",
            data={
                "first_name": "Amina",
                "last_name": "Rahman",
                "job_title": "Principal",
                "email": email,
                "phone": "+9665111111",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(contacts_response.status_code, 302)

        submit_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        return org_uuid

    def test_domain_policy_seeds_warn_and_block_entries(self):
        db = self._db()
        try:
            gmail = db.query(saas.models.BlockedEmailDomain).filter_by(domain="gmail.com").first()
            mailinator = db.query(saas.models.BlockedEmailDomain).filter_by(domain="mailinator.com").first()
            self.assertEqual(gmail.enforcement, "warn")
            self.assertEqual(mailinator.enforcement, "block")
        finally:
            db.close()

    def test_signup_with_personal_email_warns_and_sends_verification(self):
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "email_123"

        with patch("email_service.send_email", side_effect=fake_send_email):
            response = self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Amina",
                    "last_name": "Rashid",
                    "email": "amina@gmail.com",
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/auth/verification-sent", response.headers["location"])
        self.assertTrue(sent_messages)
        self.assertIn("Verify your email address", sent_messages[0]["subject"])

        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(email_normalized="amina@gmail.com").first()
            self.assertIsNotNone(account)
            self.assertEqual(account.status, "pending_verification")
            self.assertEqual(account.onboarding_status, "not_started")
            self.assertEqual(db.query(models.User).count(), 0)
        finally:
            db.close()

    def test_disposable_email_signup_is_blocked(self):
        response = self.client.post(
            "/saas/auth/signup",
            data={
                "first_name": "Temp",
                "last_name": "User",
                "email": "temp@mailinator.com",
                "password": "strong-password-123",
                "confirm_password": "strong-password-123",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/signup?error=", response.headers["location"])

        db = self._db()
        try:
            self.assertIsNone(
                db.query(saas.models.SaaSAccount).filter_by(email_normalized="temp@mailinator.com").first()
            )
        finally:
            db.close()

    def test_verify_email_then_login_and_logout(self):
        self._signup_and_verify("owner@school.edu")
        self.assertIn(service.SAAS_SESSION_COOKIE, self.client.cookies)
        self.assertIn(service.SAAS_CSRF_COOKIE, self.client.cookies)

        dashboard_response = self.client.get("/saas/account")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("SaaS account dashboard", dashboard_response.text)

        logout_response = self.client.post("/saas/auth/logout", follow_redirects=False)
        self.assertEqual(logout_response.status_code, 302)
        self.assertEqual(logout_response.headers["location"], "/saas/login")

        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(email_normalized="owner@school.edu").first()
            self.assertEqual(account.status, "active")
            revoked_sessions = db.query(saas.models.SaaSSession).filter(
                saas.models.SaaSSession.saas_account_id == account.id,
                saas.models.SaaSSession.revoked_at.isnot(None),
            ).count()
            self.assertGreaterEqual(revoked_sessions, 1)
        finally:
            db.close()

    def test_google_callback_creates_saas_identity_only(self):
        state = oauth.create_state_token("google")
        self.client.cookies.set(oauth.OAUTH_STATE_COOKIE, state)
        self.client.cookies.set(oauth.OAUTH_PKCE_COOKIE, "verifier123")

        with (
            patch("saas.oauth.exchange_code_for_tokens", return_value={"id_token": "token"}),
            patch(
                "saas.oauth.verify_identity_token",
                return_value={
                    "sub": "google-user-123",
                    "email": "director@academy.edu",
                    "email_verified": True,
                    "given_name": "Director",
                    "family_name": "User",
                },
            ),
        ):
            response = self.client.get(
                f"/saas/auth/google/callback?code=abc123&state={state}",
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/saas/account")

        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized="director@academy.edu"
            ).first()
            self.assertIsNotNone(account)
            self.assertEqual(account.status, "active")
            identity = db.query(saas.models.SaaSAuthIdentity).filter_by(
                provider="google",
                provider_subject="google-user-123",
            ).first()
            self.assertIsNotNone(identity)
            self.assertEqual(db.query(models.User).count(), 0)
        finally:
            db.close()

    def test_phase3_plan_catalog_is_seeded_and_public(self):
        db = self._db()
        try:
            plans = db.query(saas.models.SubscriptionPlan).order_by(
                saas.models.SubscriptionPlan.sort_order.asc()
            ).all()
            self.assertEqual([plan.plan_name for plan in plans], ["Starter", "Professional", "Enterprise AI"])
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            self.assertTrue(professional.is_most_popular)
            monthly_price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=professional.id,
                billing_interval="monthly",
                currency_code="USD",
                plan_version=1,
            ).first()
            annual_price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=professional.id,
                billing_interval="annual",
                currency_code="USD",
                plan_version=1,
            ).first()
            self.assertEqual(monthly_price.amount_minor, 7900)
            self.assertEqual(annual_price.amount_minor, 79000)
            saudi_map = db.query(saas.models.CountryCurrencyMap).filter_by(country_code="SA").first()
            self.assertEqual(saudi_map.currency_code, "SAR")
        finally:
            db.close()

        public_plans_response = self.client.get("/saas/plans?country_code=SA")
        self.assertEqual(public_plans_response.status_code, 200)
        self.assertIn("Starter", public_plans_response.text)
        self.assertIn("Professional", public_plans_response.text)
        self.assertIn("Most Popular", public_plans_response.text)
        self.assertIn("SAR", public_plans_response.text)

    def test_pending_organization_onboarding_flow_stays_outside_operational_tables(self):
        self._signup_and_verify("leader@academy.edu")

        db = self._db()
        try:
            operational_counts_before = {
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "academic_years": db.query(models.AcademicYear).count(),
                "users": db.query(models.User).count(),
                "role_permissions": db.query(models.RolePermission).count(),
            }
        finally:
            db.close()

        start_response = self.client.post("/saas/onboarding/start", follow_redirects=False)
        self.assertEqual(start_response.status_code, 302)
        self.assertIn("/saas/onboarding/", start_response.headers["location"])

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).first()
            self.assertIsNotNone(organization)
            org_uuid = organization.organization_uuid
        finally:
            db.close()

        organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Andalus Academy",
                "legal_name": "Andalus Academy LLC",
                "website": "https://andalus.example.com",
                "primary_domain": "andalus.example.com",
                "phone": "+9665000000",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Makkah",
                "city_name": "Jeddah",
                "district_name": "Al Zahra",
                "neighborhood_name": "North",
                "school_type": "K-12",
                "expected_branch_count": "2",
                "expected_student_count": "1200",
                "expected_teacher_count": "90",
                "estimated_staff_users": "35",
                "timezone": "Asia/Riyadh",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(organization_response.status_code, 302)
        self.assertTrue(organization_response.headers["location"].endswith("/branches"))

        branches_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={
                "branch_name": ["Main Campus", "Girls Campus", ""],
                "location": ["Central", "North", ""],
                "country_code": ["SA", "SA", ""],
                "country_name": ["Saudi Arabia", "Saudi Arabia", ""],
                "region_name": ["Makkah", "Makkah", ""],
                "city_name": ["Jeddah", "Jeddah", ""],
                "district_name": ["Al Zahra", "Al Nahda", ""],
                "neighborhood_name": ["North", "East", ""],
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(branches_response.status_code, 302)
        self.assertTrue(branches_response.headers["location"].endswith("/academic_setup"))

        academic_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/academic_setup",
            data={
                "first_academic_year_name": "2026-2027",
                "create_default_branch": "1",
                "notes": "Launch year",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(academic_response.status_code, 302)
        self.assertTrue(academic_response.headers["location"].endswith("/contacts"))

        contacts_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/contacts",
            data={
                "first_name": "Amina",
                "last_name": "Rahman",
                "job_title": "Principal",
                "email": "leader@academy.edu",
                "phone": "+9665111111",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(contacts_response.status_code, 302)
        self.assertTrue(contacts_response.headers["location"].endswith("/review"))

        review_response = self.client.get(f"/saas/onboarding/{org_uuid}/review")
        self.assertEqual(review_response.status_code, 200)
        self.assertIn("ready_for_checkout", review_response.text)

        submit_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/saas/account?notice=", submit_response.headers["location"])

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            progress = db.query(saas.models.PendingOrganizationProgress).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertEqual(organization.status, "ready_for_checkout")
            self.assertEqual(progress.completion_percent, 100)
            self.assertEqual(db.query(saas.models.PendingOrganizationBranch).filter_by(
                pending_organization_id=organization.id
            ).count(), 2)
            operational_counts_after = {
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "academic_years": db.query(models.AcademicYear).count(),
                "users": db.query(models.User).count(),
                "role_permissions": db.query(models.RolePermission).count(),
            }
            self.assertEqual(operational_counts_before, operational_counts_after)
        finally:
            db.close()

        dashboard_response = self.client.get("/saas/account")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Pending organization journey", dashboard_response.text)
        self.assertIn("ready_for_checkout", dashboard_response.text)

    def test_plan_selection_requires_ready_for_checkout(self):
        self._signup_and_verify("gated@academy.edu")
        org_uuid = self._start_pending_organization()

        plan_response = self.client.get(
            f"/saas/onboarding/{org_uuid}/plan",
            follow_redirects=False,
        )
        self.assertEqual(plan_response.status_code, 302)
        self.assertIn("/saas/account?notice=", plan_response.headers["location"])

    def test_phase3_plan_selection_and_checkout_foundation_preserves_operational_isolation(self):
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("billing@academy.edu")

        db = self._db()
        try:
            operational_counts_before = {
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "academic_years": db.query(models.AcademicYear).count(),
                "users": db.query(models.User).count(),
                "role_permissions": db.query(models.RolePermission).count(),
            }
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            self.assertIsNotNone(professional)
            professional_id = professional.id
        finally:
            db.close()

    def test_phase4_launches_paddle_checkout_without_operational_side_effects(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("payments@academy.edu")
        operational_counts_before = self._operational_counts()

        db = self._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(
            f"/saas/onboarding/{org_uuid}/checkout/start",
            follow_redirects=False,
        )

        with (
            patch(
                "saas.paddle_client.create_customer",
                return_value={"id": "ctm_test_123", "email": "payments@academy.edu", "name": "Owner User", "status": "active"},
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_test_123",
                    "status": "ready",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_test_123", "url": "https://pay.paddle.test/checkout/123"},
                },
            ),
        ):
            launch_response = self.client.post(
                f"/saas/onboarding/{org_uuid}/checkout/launch",
                follow_redirects=False,
            )

        self.assertEqual(launch_response.status_code, 302)
        self.assertEqual(launch_response.headers["location"], "https://pay.paddle.test/checkout/123")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(organization.billing_status, "checkout_started")
            self.assertEqual(organization.payment_status, "pending")
            payment_customer = db.query(saas.models.PaymentCustomer).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertIsNotNone(payment_customer)
            self.assertEqual(payment_customer.provider_customer_id, "ctm_test_123")
            payment_attempt = db.query(saas.models.PaymentAttempt).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertIsNotNone(payment_attempt)
            self.assertEqual(payment_attempt.status, "checkout_started")
            self.assertEqual(payment_attempt.provider_transaction_id, "txn_test_123")
            checkout_session = db.query(saas.models.CheckoutSession).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertEqual(checkout_session.status, "started")
            self.assertEqual(checkout_session.checkout_url, "https://pay.paddle.test/checkout/123")
            operational_counts_after = self._operational_counts()
            self.assertEqual(operational_counts_before, operational_counts_after)
        finally:
            db.close()

    def test_phase4_browser_return_does_not_confirm_payment(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("return@academy.edu")

        db = self._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "monthly"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        with (
            patch("saas.paddle_client.create_customer", return_value={"id": "ctm_return_123", "email": "return@academy.edu", "name": "Return User", "status": "active"}),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={"id": "txn_return_123", "status": "ready", "currency_code": "USD", "checkout": {"id": "chk_return_123", "url": "https://pay.paddle.test/checkout/return"}},
            ),
        ):
            self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
            attempt_uuid = attempt.attempt_uuid
        finally:
            db.close()

        return_response = self.client.get(f"/saas/checkout/return?attempt={attempt_uuid}")
        self.assertEqual(return_response.status_code, 200)
        self.assertIn("verified webhook processing", return_response.text)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
            self.assertEqual(organization.billing_status, "checkout_started")
            self.assertEqual(organization.payment_status, "pending")
            self.assertEqual(attempt.status, "checkout_started")
        finally:
            db.close()

    def test_phase4_verified_paddle_webhooks_confirm_payment_and_preserve_isolation(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("webhook@academy.edu")
        operational_counts_before = self._operational_counts()

        db = self._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        with (
            patch("saas.paddle_client.create_customer", return_value={"id": "ctm_webhook_123", "email": "webhook@academy.edu", "name": "Webhook User", "status": "active"}),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={"id": "txn_webhook_123", "status": "ready", "currency_code": "USD", "checkout": {"id": "chk_webhook_123", "url": "https://pay.paddle.test/checkout/webhook"}},
            ),
        ):
            self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
            contract = db.query(saas.models.SubscriptionContract).filter_by(pending_organization_id=organization.id).first()
            attempt_uuid = attempt.attempt_uuid
            contract_id = contract.id
        finally:
            db.close()

        paid_payload = {
            "event_id": "evt_paid_test_1234567890123456789012",
            "event_type": "transaction.paid",
            "data": {
                "id": "txn_webhook_123",
                "status": "paid",
                "customer_id": "ctm_webhook_123",
                "custom_data": {
                    "pending_organization_uuid": org_uuid,
                    "payment_attempt_uuid": attempt_uuid,
                    "subscription_contract_id": contract_id,
                },
            },
        }
        paid_signature, paid_body = self._sign_paddle_payload(paid_payload)
        paid_response = self.client.post(
            "/saas/webhooks/paddle",
            content=paid_body,
            headers={"Paddle-Signature": paid_signature, "Content-Type": "application/json"},
        )
        self.assertEqual(paid_response.status_code, 200)

        subscription_payload = {
            "event_id": "evt_sub_test_12345678901234567890123",
            "event_type": "subscription.created",
            "data": {
                "id": "sub_webhook_123",
                "status": "active",
                "transaction_id": "txn_webhook_123",
                "current_billing_period": {
                    "starts_at": "2026-06-23T12:00:00Z",
                    "ends_at": "2027-06-22T12:00:00Z",
                },
                "next_billed_at": "2027-06-22T12:00:00Z",
                "items": [
                    {
                        "price": {"id": "pri_test_2_annual"},
                    }
                ],
            },
        }
        sub_signature, sub_body = self._sign_paddle_payload(subscription_payload)
        sub_response = self.client.post(
            "/saas/webhooks/paddle",
            content=sub_body,
            headers={"Paddle-Signature": sub_signature, "Content-Type": "application/json"},
        )
        self.assertEqual(sub_response.status_code, 200)

        completed_payload = {
            "event_id": "evt_completed_123456789012345678901",
            "event_type": "transaction.completed",
            "data": {
                "id": "txn_webhook_123",
                "status": "completed",
                "customer_id": "ctm_webhook_123",
                "subscription_id": "sub_webhook_123",
                "custom_data": {
                    "pending_organization_uuid": org_uuid,
                    "payment_attempt_uuid": attempt_uuid,
                    "subscription_contract_id": contract_id,
                },
            },
        }
        completed_signature, completed_body = self._sign_paddle_payload(completed_payload)
        completed_response = self.client.post(
            "/saas/webhooks/paddle",
            content=completed_body,
            headers={"Paddle-Signature": completed_signature, "Content-Type": "application/json"},
        )
        self.assertEqual(completed_response.status_code, 200)

        duplicate_response = self.client.post(
            "/saas/webhooks/paddle",
            content=completed_body,
            headers={"Paddle-Signature": completed_signature, "Content-Type": "application/json"},
        )
        self.assertEqual(duplicate_response.status_code, 200)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
            contract = db.query(saas.models.SubscriptionContract).filter_by(pending_organization_id=organization.id).first()
            payment_subscription = db.query(saas.models.PaymentSubscription).filter_by(
                pending_organization_id=organization.id
            ).first()
            tenant_link = db.query(saas.models.TenantProvisioningLink).filter_by(
                pending_organization_id=organization.id
            ).first()
            webhooks = db.query(saas.models.PaymentWebhook).all()
            self.assertEqual(organization.billing_status, "tenant_active")
            self.assertEqual(organization.payment_status, "paid")
            self.assertEqual(attempt.status, "payment_confirmed")
            self.assertEqual(attempt.provider_subscription_id, "sub_webhook_123")
            self.assertEqual(contract.contract_status, "tenant_active")
            self.assertEqual(contract.payment_status, "paid")
            self.assertIsNotNone(payment_subscription)
            self.assertEqual(payment_subscription.provider_subscription_id, "sub_webhook_123")
            self.assertEqual(payment_subscription.status, "active")
            self.assertIsNotNone(tenant_link)
            self.assertEqual(
                db.query(saas.models.PaymentWebhook).filter_by(provider_event_id="evt_completed_123456789012345678901").count(),
                1,
            )
            self.assertGreaterEqual(len(webhooks), 3)
            operational_counts_after = self._operational_counts()
            self.assertGreater(operational_counts_after["school_groups"], operational_counts_before["school_groups"])
            self.assertGreater(operational_counts_after["branches"], operational_counts_before["branches"])
            self.assertGreater(operational_counts_after["academic_years"], operational_counts_before["academic_years"])
            self.assertGreater(operational_counts_after["users"], operational_counts_before["users"])
        finally:
            db.close()

    def test_phase4_invalid_webhook_signature_is_rejected(self):
        payload = {
            "event_id": "evt_invalid_12345678901234567890123",
            "event_type": "transaction.completed",
            "data": {"id": "txn_invalid"},
        }
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        response = self.client.post(
            "/saas/webhooks/paddle",
            content=raw_body,
            headers={"Paddle-Signature": "ts=1;h1=bad", "Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 400)

        db = self._db()
        try:
            webhook_row = db.query(saas.models.PaymentWebhook).filter_by(
                provider_event_id="evt_invalid_12345678901234567890123"
            ).first()
            self.assertIsNotNone(webhook_row)
            self.assertFalse(webhook_row.signature_valid)
            self.assertEqual(webhook_row.processing_status, "rejected")
        finally:
            db.close()

    def test_resume_later_and_platform_owner_pending_dashboard(self):
        self._signup_and_verify("resume@academy.edu")

        start_response = self.client.post("/saas/onboarding/start", follow_redirects=False)
        self.assertEqual(start_response.status_code, 302)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).first()
            org_uuid = organization.organization_uuid
            platform_owner = models.User(
                user_id="9001",
                username="platform.owner",
                email="platform@example.com",
                email_normalized=auth.normalize_email("platform@example.com"),
                first_name="Platform",
                last_name="Owner",
                password=auth.get_password_hash("PlatformPass123!"),
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_OWNER,
                platform_owner_kind=auth.PLATFORM_OWNER_PRIMARY,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(platform_owner)
            db.commit()
            platform_login_cookie = auth.create_session_token(platform_owner)
        finally:
            db.close()

    def test_platform_owner_pending_dashboard_shows_phase3_billing_visibility(self):
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("owner-ops@academy.edu")

        db = self._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            platform_owner = models.User(
                user_id="9002",
                username="platform.billing",
                email="platform.billing@example.com",
                email_normalized=auth.normalize_email("platform.billing@example.com"),
                first_name="Platform",
                last_name="Billing",
                password=auth.get_password_hash("PlatformPass123!"),
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_OWNER,
                platform_owner_kind=auth.PLATFORM_OWNER_PRIMARY,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(platform_owner)
            db.commit()
            platform_login_cookie = auth.create_session_token(platform_owner)
            professional_id = professional.id
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "monthly"},
            follow_redirects=False,
        )
        self.client.post(
            f"/saas/onboarding/{org_uuid}/checkout/start",
            follow_redirects=False,
        )

        admin_client = TestClient(self.app)
        admin_client.cookies.set(auth.SESSION_COOKIE_KEY, platform_login_cookie)

        dashboard_response = admin_client.get("/saas-admin/pending-organizations")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Professional", dashboard_response.text)
        self.assertIn("checkout_ready", dashboard_response.text)

        detail_response = admin_client.get(f"/saas-admin/pending-organizations/{org_uuid}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("Professional", detail_response.text)
        self.assertIn("Checkout: ready", detail_response.text)

        save_draft_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Resume Academy",
                "educational_program": "NATIONAL",
                "timezone": "Asia/Riyadh",
                "save_action": "save_exit",
            },
            follow_redirects=False,
        )
        self.assertEqual(save_draft_response.status_code, 302)
        self.assertEqual(save_draft_response.headers["location"], "/saas/account?notice=Draft+saved.")

        resume_response = self.client.get(f"/saas/onboarding/{org_uuid}/resume", follow_redirects=False)
        self.assertEqual(resume_response.status_code, 302)
        self.assertTrue(resume_response.headers["location"].endswith("/branches"))

        admin_client = TestClient(self.app)
        admin_client.cookies.set(auth.SESSION_COOKIE_KEY, platform_login_cookie)

        dashboard_response = admin_client.get("/saas-admin/pending-organizations")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Pending Organizations", dashboard_response.text)
        self.assertIn("Resume Academy", dashboard_response.text)

        detail_response = admin_client.get(f"/saas-admin/pending-organizations/{org_uuid}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("Pending Organization Detail", detail_response.text)

        note_response = admin_client.post(
            f"/saas-admin/pending-organizations/{org_uuid}/notes",
            data={"note": "Follow up only if exceptions appear."},
            follow_redirects=False,
        )
        self.assertEqual(note_response.status_code, 302)

        status_response = admin_client.post(
            f"/saas-admin/pending-organizations/{org_uuid}/status",
            data={"status": "under_review", "rejection_reason": "Manual exception check"},
            follow_redirects=False,
        )
        self.assertEqual(status_response.status_code, 302)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(organization.status, "under_review")
            self.assertEqual(
                db.query(saas.models.PendingOrganizationNote).filter_by(
                    pending_organization_id=organization.id
                ).count(),
                1,
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
