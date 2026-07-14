import os
import re
import json
import hashlib
import hmac
import time
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"
os.environ["PADDLE_API_KEY"] = "pdl_test_phase4_api_key"
os.environ["PADDLE_WEBHOOK_SECRET"] = "pdl_ntfset_test_phase4_secret"
os.environ["PADDLE_WEBHOOK_TOLERANCE_SECONDS"] = "30"

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import auth
import location_service
import models
import saas.models  # noqa: F401 - register metadata
from dependencies import get_db
from saas import billing_service, branch_pricing_quote_service, draft_lifecycle_service, oauth, paddle_client, payment_service, service
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
        verify_response = self.client.get(f"/saas/auth/verify-email?token={token}", follow_redirects=False)
        self.assertEqual(verify_response.status_code, 302)
        self.assertIn("/saas/login?notice=", verify_response.headers["location"])
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

    def test_customer_account_page_requires_login_without_raw_json(self):
        response = self.client.get("/saas/account", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/login?notice=", response.headers["location"])
        self.assertIn("Please+sign+in+to+your+TIS+Account", response.headers["location"])
        self.assertNotIn('{"detail"', response.text)

        login_response = self.client.get(response.headers["location"])
        self.assertEqual(login_response.status_code, 200)
        self.assertIn("Please sign in to your TIS Account.", login_response.text)
        self.assertIn("Sign in", login_response.text)

    def test_customer_protected_pages_require_login_without_raw_json(self):
        protected_paths = [
            "/saas/account/profile",
            "/saas/account/security",
            "/saas/account/sessions",
            "/saas/account/billing",
            "/saas/onboarding",
            "/saas/onboarding/start",
            "/saas/onboarding/missing-organization/resume",
            "/saas/onboarding/missing-organization/organization",
            "/saas/onboarding/missing-organization/plan",
            "/saas/onboarding/missing-organization/checkout",
            "/saas/onboarding/missing-organization/billing-status",
            "/saas/checkout/return",
            "/saas/checkout/cancel",
        ]
        for path in protected_paths:
            with self.subTest(path=path):
                method = self.client.post if path == "/saas/onboarding/start" else self.client.get
                response = method(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/saas/login?notice=", response.headers["location"])
                self.assertNotIn('{"detail"', response.text)

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

    def test_valid_token_verifies_account_and_redirects_to_login_notice(self):
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "email_valid"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Verify",
                    "last_name": "User",
                    "email": "verify@school.edu",
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                },
                follow_redirects=False,
            )

        token = re.search(r"token=([A-Za-z0-9._\-]+)", sent_messages[0]["text"]).group(1)
        response = self.client.get(f"/saas/auth/verify-email?token={token}", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/login?notice=", response.headers["location"])
        self.assertIn("email=verify%40school.edu", response.headers["location"])

        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(email_normalized="verify@school.edu").first()
            self.assertEqual(account.status, "active")
            self.assertIsNotNone(account.email_verified_at)
        finally:
            db.close()

    def test_expired_token_shows_recovery_resend_path(self):
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "email_expired"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Expired",
                    "last_name": "User",
                    "email": "expired@school.edu",
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                },
                follow_redirects=False,
            )

        token = re.search(r"token=([A-Za-z0-9._\-]+)", sent_messages[0]["text"]).group(1)
        db = self._db()
        try:
            row = db.query(saas.models.SaaSEmailVerificationToken).first()
            row.expires_at = service._utcnow() - timedelta(minutes=1)  # noqa: SLF001 - test-only expiry
            db.commit()
        finally:
            db.close()

        response = self.client.get(f"/saas/auth/verify-email?token={token}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("This email verification link is invalid or expired.", response.text)
        self.assertIn("Send a new verification link", response.text)

    def test_invalid_token_shows_safe_recovery_page(self):
        response = self.client.get("/saas/auth/verify-email?token=not-a-real-token")
        self.assertEqual(response.status_code, 400)
        self.assertIn("This email verification link is invalid or expired.", response.text)
        self.assertIn("Send a new verification link", response.text)
        self.assertIn("/saas/auth/resend-verification", response.text)

    def test_password_reset_flow_updates_password_and_revokes_sessions(self):
        self._signup_and_verify("reset@school.edu")
        self.client.post("/saas/auth/logout", follow_redirects=False)

        login_page = self.client.get("/saas/login?email=reset%40school.edu")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn("Forgot password?", login_page.text)
        self.assertIn("/saas/auth/forgot-password", login_page.text)

        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "reset_email_1"

        with patch("email_service.send_email", side_effect=fake_send_email):
            request_response = self.client.post(
                "/saas/auth/forgot-password",
                data={"email": "reset@school.edu"},
                follow_redirects=False,
            )

        self.assertEqual(request_response.status_code, 302)
        self.assertIn("/saas/auth/forgot-password?notice=", request_response.headers["location"])
        self.assertEqual(len(sent_messages), 1)
        self.assertIn("Reset your TIS Account password", sent_messages[0]["subject"])
        token = re.search(r"token=([A-Za-z0-9._\-]+)", sent_messages[0]["text"]).group(1)

        reset_page = self.client.get(f"/saas/auth/reset-password?token={token}")
        self.assertEqual(reset_page.status_code, 200)
        self.assertIn("Choose a new password", reset_page.text)
        self.assertIn('name="token"', reset_page.text)

        reset_response = self.client.post(
            "/saas/auth/reset-password",
            data={
                "token": token,
                "password": "new-strong-password-456",
                "confirm_password": "new-strong-password-456",
            },
            follow_redirects=False,
        )
        self.assertEqual(reset_response.status_code, 302)
        self.assertIn("/saas/login?notice=", reset_response.headers["location"])

        old_login = self.client.post(
            "/saas/auth/login",
            data={"email": "reset@school.edu", "password": "strong-password-123", "next_path": "/saas/account"},
            follow_redirects=False,
        )
        self.assertIn("Invalid+email+or+password", old_login.headers["location"])

        new_login = self.client.post(
            "/saas/auth/login",
            data={"email": "reset@school.edu", "password": "new-strong-password-456", "next_path": "/saas/account"},
            follow_redirects=False,
        )
        self.assertEqual(new_login.status_code, 302)
        self.assertEqual(new_login.headers["location"], "/saas/account")

        reuse_response = self.client.get(f"/saas/auth/reset-password?token={token}")
        self.assertEqual(reuse_response.status_code, 400)
        self.assertIn("This password reset link is invalid or expired.", reuse_response.text)

    def test_password_reset_request_is_neutral_for_unknown_email(self):
        with patch("email_service.send_email") as fake_send_email:
            response = self.client.post(
                "/saas/auth/forgot-password",
                data={"email": "unknown-reset@school.edu"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("If a TIS Account exists for this email, a password reset link has been sent.", response.text)
        fake_send_email.assert_not_called()

    def test_expired_password_reset_token_shows_recovery_path(self):
        self._signup_and_verify("expired-reset@school.edu")
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return "reset_email_expired"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/forgot-password",
                data={"email": "expired-reset@school.edu"},
                follow_redirects=False,
            )

        token = re.search(r"token=([A-Za-z0-9._\-]+)", sent_messages[0]["text"]).group(1)
        db = self._db()
        try:
            row = db.query(saas.models.SaaSPasswordResetToken).first()
            row.expires_at = service._utcnow() - timedelta(minutes=1)  # noqa: SLF001 - test-only expiry
            db.commit()
        finally:
            db.close()

        response = self.client.get(f"/saas/auth/reset-password?token={token}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("This password reset link is invalid or expired.", response.text)
        self.assertIn("Request a new reset link", response.text)

    def test_resend_verification_issues_new_token_for_unverified_account(self):
        sent_messages = []

        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return f"email_{len(sent_messages)}"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Resend",
                    "last_name": "User",
                    "email": "resend@school.edu",
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                },
                follow_redirects=False,
            )
            response = self.client.post(
                "/saas/auth/resend-verification",
                data={"email": "resend@school.edu"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/auth/verification-sent", response.headers["location"])
        self.assertEqual(len(sent_messages), 2)
        first_token = re.search(r"token=([A-Za-z0-9._\-]+)", sent_messages[0]["text"]).group(1)
        second_token = re.search(r"token=([A-Za-z0-9._\-]+)", sent_messages[1]["text"]).group(1)
        self.assertNotEqual(first_token, second_token)

        db = self._db()
        try:
            rows = db.query(saas.models.SaaSEmailVerificationToken).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(1 for row in rows if row.consumed_at is None), 1)
        finally:
            db.close()

    def test_resend_for_verified_account_redirects_to_safe_sign_in_notice(self):
        self._signup_and_verify("verified-resend@school.edu")

        with patch("email_service.send_email") as fake_send_email:
            response = self.client.post(
                "/saas/auth/resend-verification",
                data={"email": "verified-resend@school.edu"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/login?notice=", response.headers["location"])
        fake_send_email.assert_not_called()

    def test_unknown_email_resend_does_not_reveal_account_existence(self):
        with patch("email_service.send_email") as fake_send_email:
            response = self.client.post(
                "/saas/auth/resend-verification",
                data={"email": "unknown@school.edu"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("If a TIS Account exists for this email, a new verification link has been sent.", response.text)
        fake_send_email.assert_not_called()

    def test_unverified_password_account_cannot_start_onboarding(self):
        captured = {}

        def fake_send_email(**kwargs):
            captured["text"] = kwargs["text"]
            return "email_gate"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Gate",
                    "last_name": "User",
                    "email": "gate@school.edu",
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                },
                follow_redirects=False,
            )

        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(email_normalized="gate@school.edu").first()
            session_token, csrf_token, _session_row = service.create_session(db, account)
            db.commit()
        finally:
            db.close()

        self.client.cookies.set(service.SAAS_SESSION_COOKIE, session_token)
        self.client.cookies.set(service.SAAS_CSRF_COOKIE, csrf_token)
        response = self.client.post("/saas/onboarding/start", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/saas/auth/verification-required", response.headers["location"])

        db = self._db()
        try:
            self.assertEqual(db.query(saas.models.PendingOrganization).count(), 0)
        finally:
            db.close()

    def test_verify_email_then_login_and_logout(self):
        self._signup_and_verify("owner@school.edu")
        self.assertIn(service.SAAS_SESSION_COOKIE, self.client.cookies)
        self.assertIn(service.SAAS_CSRF_COOKIE, self.client.cookies)

        dashboard_response = self.client.get("/saas/account")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn("Start your School Workspace Setup", dashboard_response.text)
        self.assertIn("What should I do next?", dashboard_response.text)
        self.assertIn("TIS Logo", dashboard_response.text)
        self.assertEqual(dashboard_response.text.count('data-primary-cta="true"'), 1)
        expected_steps = [
            "TIS Account",
            "Email Verification",
            "School Workspace Setup",
            "Review &amp; Confirmation",
            "Subscription Selection",
            "Secure Payment",
            "Workspace Activation",
            "Enter TIS Platform",
        ]
        for step_label in expected_steps:
            self.assertIn(step_label, dashboard_response.text)
        self.assertIn('data-setup-step="tis_account" data-setup-state="complete"', dashboard_response.text)
        self.assertIn('data-setup-step="email_verification" data-setup-state="complete"', dashboard_response.text)
        self.assertIn('data-setup-step="school_workspace_setup" data-setup-state="current"', dashboard_response.text)
        self.assertIn('data-setup-step="subscription_selection" data-setup-state="locked"', dashboard_response.text)
        self.assertIn("TIS Platform access becomes available after Workspace Activation.", dashboard_response.text)
        self.assertNotIn("Last seen:", dashboard_response.text)
        self.assertNotIn("active session", dashboard_response.text)
        self.assertNotIn("Current session", dashboard_response.text)
        self.assertNotIn("checkout_ready", dashboard_response.text)
        self.assertNotIn("tenant_active", dashboard_response.text)
        self.assertNotIn("ready_for_provisioning", dashboard_response.text)
        self.assertNotIn(">SaaS<", dashboard_response.text)

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

        organization_get = self.client.get(f"/saas/onboarding/{org_uuid}/organization")
        self.assertEqual(organization_get.status_code, 200)
        self.assertIn("Organization Profile", organization_get.text)
        self.assertIn("Organization identity", organization_get.text)
        self.assertIn("TIS Logo", organization_get.text)
        self.assertEqual(organization_get.text.count('data-primary-cta="true"'), 1)
        self.assertIn('form="organization-form"', organization_get.text)
        self.assertNotIn('href="/saas/account/profile"', organization_get.text)

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

        branches_get = self.client.get(f"/saas/onboarding/{org_uuid}/branches")
        self.assertEqual(branches_get.status_code, 200)
        self.assertIn("Branch Setup", branches_get.text)
        self.assertIn("Branches and campuses", branches_get.text)
        self.assertEqual(branches_get.text.count('data-primary-cta="true"'), 1)
        self.assertIn('form="branches-form"', branches_get.text)
        rendered_branch_list = branches_get.text.split('<div id="branch-list"', 1)[1].split("</div>\n        <button id=\"add-branch\"", 1)[0]
        self.assertEqual(rendered_branch_list.count("data-branch-panel"), 2)
        self.assertIn('<strong id="active-branch-count">2</strong>', branches_get.text)

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

        academic_get = self.client.get(f"/saas/onboarding/{org_uuid}/academic_setup")
        self.assertEqual(academic_get.status_code, 200)
        self.assertIn("Academic Setup", academic_get.text)
        self.assertIn("Initial academic structure", academic_get.text)
        self.assertEqual(academic_get.text.count('data-primary-cta="true"'), 1)
        self.assertIn('form="academic-setup-form"', academic_get.text)

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

        contacts_get = self.client.get(f"/saas/onboarding/{org_uuid}/contacts")
        self.assertEqual(contacts_get.status_code, 200)
        self.assertIn("Primary Contact", contacts_get.text)
        self.assertIn("Primary setup contact", contacts_get.text)
        self.assertEqual(contacts_get.text.count('data-primary-cta="true"'), 1)
        self.assertIn('form="contacts-form"', contacts_get.text)

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
        self.assertIn("Review School Workspace Setup", review_response.text)
        self.assertIn("Ready to continue", review_response.text)
        self.assertEqual(review_response.text.count('data-primary-cta="true"'), 1)
        self.assertIn('form="review-submit-form"', review_response.text)
        self.assertNotIn("ready_for_checkout", review_response.text)

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
        self.assertIn("Choose your subscription", dashboard_response.text)
        self.assertIn('data-setup-step="review_confirmation" data-setup-state="complete"', dashboard_response.text)
        self.assertIn('data-setup-step="subscription_selection" data-setup-state="current"', dashboard_response.text)
        self.assertEqual(dashboard_response.text.count('data-primary-cta="true"'), 1)
        self.assertNotIn("ready_for_checkout", dashboard_response.text)

    def test_onboarding_step_access_allows_reached_steps_and_locks_future_steps(self):
        self._signup_and_verify("wizard-access@academy.edu")
        org_uuid = self._start_pending_organization()

        locked_targets = ("branches", "academic_setup", "contacts", "review")
        for target in locked_targets:
            response = self.client.get(f"/saas/onboarding/{org_uuid}/{target}", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["location"].endswith("/organization"))

        locked_post = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={"branch_name": ["Premature Campus"], "save_action": "continue"},
            follow_redirects=False,
        )
        self.assertEqual(locked_post.status_code, 302)
        self.assertTrue(locked_post.headers["location"].endswith("/organization"))

        organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Wizard Access Academy",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Makkah",
                "city_name": "Jeddah",
                "timezone": "",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(organization_response.status_code, 302)

        branches_page = self.client.get(f"/saas/onboarding/{org_uuid}/branches")
        self.assertEqual(branches_page.status_code, 200)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/organization"', branches_page.text)
        self.assertIn('data-onboarding-step="organization" data-onboarding-state="available"', branches_page.text)
        self.assertIn('data-onboarding-step="branches" data-onboarding-state="current"', branches_page.text)
        self.assertIn('data-onboarding-step="academic_setup" data-onboarding-state="locked"', branches_page.text)
        self.assertNotIn(f'href="/saas/onboarding/{org_uuid}/academic_setup"', branches_page.text)

        branches_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={
                "branch_name": ["Main Campus"],
                "location": ["Central"],
                "country_code": ["SA"],
                "country_name": ["Saudi Arabia"],
                "region_name": ["Makkah"],
                "city_name": ["Jeddah"],
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
                "notes": "Reached review with timezone still missing",
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
                "email": "wizard-access@academy.edu",
                "phone": "+9665111111",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(contacts_response.status_code, 302)
        self.assertTrue(contacts_response.headers["location"].endswith("/review"))

        review_page = self.client.get(f"/saas/onboarding/{org_uuid}/review")
        self.assertEqual(review_page.status_code, 200)
        self.assertIn("Missing: Time Zone", review_page.text)
        self.assertIn("Go to Organization Profile", review_page.text)
        self.assertIn("School Workspace Setup", review_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/organization"', review_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/branches"', review_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/academic_setup"', review_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/contacts"', review_page.text)
        self.assertIn('data-onboarding-step="review" data-onboarding-state="current"', review_page.text)

        for target, title in (
            ("organization", "Organization Profile"),
            ("branches", "Branch Setup"),
            ("academic_setup", "Academic Setup"),
            ("contacts", "Primary Contact"),
            ("review", "Review School Workspace Setup"),
        ):
            response = self.client.get(f"/saas/onboarding/{org_uuid}/{target}", follow_redirects=False)
            self.assertEqual(response.status_code, 200)
            self.assertIn(title, response.text)

        fixed_organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Wizard Access Academy",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Makkah",
                "city_name": "Jeddah",
                "timezone": "Asia/Riyadh",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(fixed_organization_response.status_code, 302)

        submit_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/saas/account?notice=", submit_response.headers["location"])

    def test_onboarding_validation_errors_preserve_submitted_form_values(self):
        self._signup_and_verify("preserve@academy.edu")
        org_uuid = self._start_pending_organization()

        organization_get = self.client.get(f"/saas/onboarding/{org_uuid}/organization")
        self.assertEqual(organization_get.status_code, 200)
        self.assertIn("Select country first", organization_get.text)
        self.assertNotIn('value="Europe/London"', organization_get.text)
        location_fields = organization_get.text.split('data-location-fields', 1)[1].split("</section>", 1)[0]
        self.assertIn("data-location-timezone", location_fields)
        self.assertLess(organization_get.text.index('id="educational_program"'), organization_get.text.index('id="organization_country"'))
        self.assertLess(organization_get.text.index('id="organization_country"'), organization_get.text.index('id="organization_region"'))
        self.assertLess(organization_get.text.index('id="organization_region"'), organization_get.text.index('id="organization_city"'))
        self.assertLess(organization_get.text.index('id="organization_city"'), organization_get.text.index('id="timezone"'))

        organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "",
                "legal_name": "Preserve Academy LLC",
                "website": "https://preserve.example.com",
                "primary_domain": "preserve.example.com",
                "phone": "+9665444444",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Riyadh",
                "city_name": "Riyadh",
                "district_name": "Olaya",
                "neighborhood_name": "North",
                "school_type": "K-12",
                "expected_branch_count": "3",
                "expected_student_count": "900",
                "expected_teacher_count": "70",
                "estimated_staff_users": "25",
                "timezone": "Asia/Riyadh",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(organization_response.status_code, 422)
        self.assertIn("Organization name is required.", organization_response.text)
        self.assertIn('value="Preserve Academy LLC"', organization_response.text)
        self.assertIn('value="https://preserve.example.com"', organization_response.text)
        self.assertIn('value="BOTH" selected', organization_response.text)
        self.assertIn('data-selected-country="SA"', organization_response.text)
        self.assertIn('data-selected-region="Riyadh"', organization_response.text)
        self.assertIn('data-selected-city="Riyadh"', organization_response.text)
        self.assertIn('value="Olaya"', organization_response.text)
        self.assertIn('value="900"', organization_response.text)
        self.assertIn('value="Asia/Riyadh" selected', organization_response.text)
        self.assertNotIn('value="Europe/London"', organization_response.text)

        invalid_timezone_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Preserve Academy",
                "legal_name": "Preserve Academy LLC",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Riyadh",
                "city_name": "Riyadh",
                "timezone": "Not/A_Timezone",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(invalid_timezone_response.status_code, 422)
        self.assertIn("Select a valid time zone.", invalid_timezone_response.text)
        self.assertNotIn('value="Not/A_Timezone" selected', invalid_timezone_response.text)

        continent_timezone_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Preserve Academy",
                "legal_name": "Preserve Academy LLC",
                "educational_program": "BOTH",
                "country_code": "US",
                "country_name": "United States",
                "region_name": "New York",
                "city_name": "New York City",
                "timezone": "Asia",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(continent_timezone_response.status_code, 422)
        self.assertIn("Select a valid time zone.", continent_timezone_response.text)
        self.assertNotIn('value="Asia" selected', continent_timezone_response.text)

        valid_organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Preserve Academy",
                "legal_name": "Preserve Academy LLC",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Riyadh",
                "city_name": "Riyadh",
                "district_name": "Olaya",
                "neighborhood_name": "North",
                "expected_branch_count": "3",
                "expected_student_count": "900",
                "expected_teacher_count": "70",
                "estimated_staff_users": "25",
                "timezone": "Asia/Riyadh",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(valid_organization_response.status_code, 302)

        saved_organization_get = self.client.get(f"/saas/onboarding/{org_uuid}/organization")
        self.assertEqual(saved_organization_get.status_code, 200)
        self.assertIn('value="Asia/Riyadh" selected', saved_organization_get.text)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(organization.timezone, "Asia/Riyadh")
        finally:
            db.close()

        branches_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={
                "branch_name": ["", ""],
                "location": ["Temporary North Campus", "Temporary South Campus"],
                "country_code": ["SA", "SA"],
                "country_name": ["Saudi Arabia", "Saudi Arabia"],
                "region_name": ["Riyadh", "Riyadh"],
                "city_name": ["Riyadh", "Riyadh"],
                "district_name": ["Olaya", "Malaz"],
                "neighborhood_name": ["North", "East"],
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(branches_response.status_code, 422)
        self.assertIn("Every active branch must have a branch name.", branches_response.text)
        self.assertIn('value="Temporary North Campus"', branches_response.text)
        self.assertIn('value="Temporary South Campus"', branches_response.text)
        self.assertIn('value="Malaz"', branches_response.text)

        valid_branches_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={
                "branch_name": ["Main Campus"],
                "location": ["Central"],
                "country_code": ["SA"],
                "country_name": ["Saudi Arabia"],
                "region_name": ["Riyadh"],
                "city_name": ["Riyadh"],
                "district_name": ["Olaya"],
                "neighborhood_name": ["North"],
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(valid_branches_response.status_code, 302)

        academic_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/academic_setup",
            data={
                "first_academic_year_name": "",
                "create_default_branch": "1",
                "notes": "Keep this note after validation fails",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(academic_response.status_code, 422)
        self.assertIn("First academic year is required.", academic_response.text)
        self.assertIn('value="Keep this note after validation fails"', academic_response.text)
        self.assertIn('name="create_default_branch" value="1" checked', academic_response.text)

        valid_academic_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/academic_setup",
            data={
                "first_academic_year_name": "2026-2027",
                "create_default_branch": "1",
                "notes": "Launch year",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(valid_academic_response.status_code, 302)

        contacts_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/contacts",
            data={
                "first_name": "Sara",
                "last_name": "Khan",
                "job_title": "Director",
                "email": "not-an-email",
                "phone": "+9665555555",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(contacts_response.status_code, 422)
        self.assertIn("Primary contact email is invalid.", contacts_response.text)
        self.assertIn('value="Sara"', contacts_response.text)
        self.assertIn('value="Khan"', contacts_response.text)
        self.assertIn('value="Director"', contacts_response.text)
        self.assertIn('value="not-an-email"', contacts_response.text)
        self.assertIn('value="+9665555555"', contacts_response.text)

    def test_country_timezone_metadata_filters_to_valid_iana_timezones(self):
        countries = {country["code"]: country for country in location_service.list_countries()}
        iana_timezones = set(service.list_iana_timezones())

        self.assertEqual(countries["SA"]["timezones"], ["Asia/Riyadh"])
        self.assertEqual(countries["LB"]["timezones"], ["Asia/Beirut"])
        self.assertEqual(countries["EG"]["timezones"], ["Africa/Cairo"])
        self.assertIn("Europe/London", countries["GB"]["timezones"])
        self.assertIn("America/New_York", countries["US"]["timezones"])
        self.assertIn("America/Chicago", countries["US"]["timezones"])
        self.assertIn("America/Denver", countries["US"]["timezones"])
        self.assertIn("America/Phoenix", countries["US"]["timezones"])
        self.assertIn("America/Los_Angeles", countries["US"]["timezones"])
        self.assertIn("America/Anchorage", countries["US"]["timezones"])
        self.assertIn("Pacific/Honolulu", countries["US"]["timezones"])
        self.assertGreater(len(countries["US"]["timezones"]), 1)

        continent_labels = {"Asia", "Europe", "Africa", "America"}
        for country in countries.values():
            for timezone in country.get("timezones") or []:
                self.assertIn(timezone, iana_timezones)
                self.assertNotIn(timezone, continent_labels)

    def test_location_countries_api_returns_country_timezones(self):
        self._signup_and_verify("location-api@academy.edu")

        response = self.client.get("/saas/locations/countries", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 200)
        countries = {country["code"]: country for country in response.json()["items"]}
        united_states = countries["US"]

        self.assertIn("timezones", united_states)
        self.assertIn("America/New_York", united_states["timezones"])
        self.assertIn("America/Chicago", united_states["timezones"])
        self.assertIn("America/Denver", united_states["timezones"])
        self.assertIn("America/Phoenix", united_states["timezones"])
        self.assertIn("America/Los_Angeles", united_states["timezones"])
        self.assertIn("America/Anchorage", united_states["timezones"])
        self.assertIn("Pacific/Honolulu", united_states["timezones"])
        self.assertNotIn("Asia", united_states["timezones"])

    def test_review_identifies_missing_requirements_and_complete_setup_submits(self):
        self._signup_and_verify("review-guidance@academy.edu")
        org_uuid = self._start_pending_organization()

        organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Review Academy",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Makkah",
                "city_name": "Jeddah",
                "timezone": "",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(organization_response.status_code, 302)

        branches_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/branches",
            data={
                "branch_name": ["Main Campus"],
                "location": ["Central"],
                "country_code": ["SA"],
                "country_name": ["Saudi Arabia"],
                "region_name": ["Makkah"],
                "city_name": ["Jeddah"],
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
                "notes": "Ready except timezone",
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
                "email": "review-guidance@academy.edu",
                "phone": "+9665111111",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(contacts_response.status_code, 302)

        review_response = self.client.get(f"/saas/onboarding/{org_uuid}/review")
        self.assertEqual(review_response.status_code, 200)
        self.assertIn("Missing: Time Zone", review_response.text)
        self.assertIn("Time Zone: Not selected", review_response.text)
        self.assertIn("Go to Organization Profile", review_response.text)
        self.assertIn(f'/saas/onboarding/{org_uuid}/organization', review_response.text)
        self.assertNotIn("Complete all onboarding steps before submitting.", review_response.text)

        blocked_submit = self.client.post(
            f"/saas/onboarding/{org_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(blocked_submit.status_code, 422)
        self.assertIn("Complete these items before submitting", blocked_submit.text)
        self.assertIn("Organization Profile: Time Zone", blocked_submit.text)
        self.assertIn("Missing: Time Zone", blocked_submit.text)
        self.assertIn("Go to Organization Profile", blocked_submit.text)

        fixed_organization_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/organization",
            data={
                "organization_name": "Review Academy",
                "educational_program": "BOTH",
                "country_code": "SA",
                "country_name": "Saudi Arabia",
                "region_name": "Makkah",
                "city_name": "Jeddah",
                "timezone": "Asia/Riyadh",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.assertEqual(fixed_organization_response.status_code, 302)

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
        finally:
            db.close()

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
        self._configure_paddle_prices()
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

        plan_page = self.client.get(f"/saas/onboarding/{org_uuid}/plan")
        self.assertEqual(plan_page.status_code, 200)
        self.assertIn("Choose your subscription", plan_page.text)
        self.assertIn("Subscription Selection", plan_page.text)
        self.assertIn("School Workspace Setup", plan_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/review"', plan_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/plan"', plan_page.text)
        self.assertIn('form="plan-selection-form"', plan_page.text)
        self.assertEqual(plan_page.text.count('data-primary-cta="true"'), 1)
        self.assertNotIn("Plan ID", plan_page.text)

        plan_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.assertEqual(plan_response.status_code, 302)
        self.assertIn(f"/saas/onboarding/{org_uuid}/checkout", plan_response.headers["location"])

        checkout_page = self.client.get(f"/saas/onboarding/{org_uuid}/checkout")
        self.assertEqual(checkout_page.status_code, 200)
        self.assertIn("Secure Payment summary", checkout_page.text)
        self.assertIn('id="checkout-start-form"', checkout_page.text)
        self.assertIn('form="checkout-launch-form"', checkout_page.text)
        self.assertIn("Continue to Secure Payment", checkout_page.text)
        self.assertEqual(checkout_page.text.count('data-primary-cta="true"'), 1)
        self.assertIn("School Workspace Setup", checkout_page.text)
        self.assertNotIn("Need to adjust setup details?", checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/organization"', checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/branches"', checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/academic_setup"', checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/contacts"', checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/review"', checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/plan"', checkout_page.text)
        self.assertIn('data-onboarding-step="subscription_selection"', checkout_page.text)
        self.assertIn('data-setup-step="secure_payment" data-setup-state="current"', checkout_page.text)
        self.assertNotIn(f'href="/saas/onboarding/{org_uuid}/billing-status"', checkout_page.text)
        self.assertNotIn("checkout_ready", checkout_page.text)
        self.assertNotIn("provider", checkout_page.text.lower())

        for target, title in (
            ("organization", "Organization Profile"),
            ("branches", "Branch Setup"),
            ("academic_setup", "Academic Setup"),
            ("contacts", "Primary Contact"),
            ("review", "Review School Workspace Setup"),
            ("plan", "Subscription Selection"),
        ):
            response = self.client.get(f"/saas/onboarding/{org_uuid}/{target}", follow_redirects=False)
            self.assertEqual(response.status_code, 200)
            self.assertIn(title, response.text)

        start_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/checkout/start",
            follow_redirects=False,
        )
        self.assertEqual(start_response.status_code, 302)

        ready_checkout_page = self.client.get(f"/saas/onboarding/{org_uuid}/checkout")
        self.assertEqual(ready_checkout_page.status_code, 200)
        self.assertIn('form="checkout-launch-form"', ready_checkout_page.text)
        self.assertIn("Continue to Secure Payment", ready_checkout_page.text)
        self.assertEqual(ready_checkout_page.text.count('data-primary-cta="true"'), 1)
        self.assertIn("School Workspace Setup", ready_checkout_page.text)
        self.assertNotIn("Need to adjust setup details?", ready_checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/organization"', ready_checkout_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/plan"', ready_checkout_page.text)
        self.assertNotIn(f'href="/saas/onboarding/{org_uuid}/billing-status"', ready_checkout_page.text)

        billing_page = self.client.get("/saas/account/billing")
        self.assertEqual(billing_page.status_code, 200)
        self.assertIn("Subscription and activation overview", billing_page.text)
        self.assertIn("TIS Platform access", billing_page.text)
        self.assertEqual(billing_page.text.count('data-primary-cta="true"'), 1)
        self.assertNotIn("checkout_ready", billing_page.text)
        self.assertNotIn("provider", billing_page.text.lower())

        status_page = self.client.get(f"/saas/onboarding/{org_uuid}/billing-status")
        self.assertEqual(status_page.status_code, 200)
        self.assertIn("Subscription and Workspace Activation status", status_page.text)
        self.assertIn("Browser redirects do not activate the workspace by themselves.", status_page.text)
        self.assertEqual(status_page.text.count('data-primary-cta="true"'), 1)
        self.assertIn("School Workspace Setup", status_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/review"', status_page.text)
        self.assertIn(f'href="/saas/onboarding/{org_uuid}/plan"', status_page.text)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            organization.billing_status = "payment_confirmed"
            organization.payment_status = "paid"
            db.commit()
        finally:
            db.close()

        for target in ("organization", "branches", "academic_setup", "contacts", "review", "plan"):
            response = self.client.get(f"/saas/onboarding/{org_uuid}/{target}", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers["location"].endswith("/billing-status"))

    def test_missing_paddle_price_id_blocks_launch_with_customer_safe_message(self):
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("missing-price@academy.edu")

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
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            launch_response = self.client.post(
                f"/saas/onboarding/{org_uuid}/checkout/launch",
                follow_redirects=False,
            )

        self.assertEqual(launch_response.status_code, 302)
        self.assertIn("/saas/onboarding/", launch_response.headers["location"])
        self.assertIn("Secure+payment+is+temporarily+unavailable", launch_response.headers["location"])
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(organization.billing_status, "plan_selected")
            self.assertEqual(
                db.query(saas.models.CheckoutSession).filter_by(pending_organization_id=organization.id).count(),
                0,
            )
            self.assertIsNone(organization.last_payment_attempt_id)
            self.assertEqual(
                db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).count(),
                0,
            )
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
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
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

    def test_phase4_continue_from_plan_selected_prepares_and_launches_checkout(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("one-click@academy.edu")

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

        with (
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch(
                "saas.paddle_client.create_customer",
                return_value={"id": "ctm_one_click_123", "email": "one-click@academy.edu", "name": "One Click", "status": "active"},
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_one_click_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_one_click_123", "url": "https://pay.paddle.test/one-click"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://pay.paddle.test/one-click")
        create_transaction.assert_called_once()

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(organization.billing_status, "checkout_started")
            self.assertEqual(
                db.query(saas.models.CheckoutSession).filter_by(pending_organization_id=organization.id).count(),
                1,
            )
            self.assertEqual(
                db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).count(),
                1,
            )
        finally:
            db.close()

    def test_phase4_checkout_ready_launch_does_not_create_duplicate_session(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("ready-once@academy.edu")

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

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            initial_session_count = db.query(saas.models.CheckoutSession).filter_by(
                pending_organization_id=organization.id
            ).count()
            self.assertEqual(initial_session_count, 1)
        finally:
            db.close()

        with (
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch(
                "saas.paddle_client.create_customer",
                return_value={"id": "ctm_ready_once_123", "email": "ready-once@academy.edu", "name": "Ready Once", "status": "active"},
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_ready_once_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_ready_once_123", "url": "https://pay.paddle.test/ready-once"},
                },
            ),
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(
                db.query(saas.models.CheckoutSession).filter_by(pending_organization_id=organization.id).count(),
                1,
            )
        finally:
            db.close()

    def test_phase4_repeated_checkout_launch_reuses_started_checkout_url(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("repeat-click@academy.edu")

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

        with (
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch(
                "saas.paddle_client.create_customer",
                return_value={"id": "ctm_repeat_click_123", "email": "repeat-click@academy.edu", "name": "Repeat Click", "status": "active"},
            ) as create_customer,
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_repeat_click_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_repeat_click_123", "url": "https://pay.paddle.test/repeat-click"},
                },
            ) as create_transaction,
        ):
            first_response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)
            second_response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(second_response.headers["location"], "https://pay.paddle.test/repeat-click")
        create_customer.assert_called_once()
        create_transaction.assert_called_once()

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(
                db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).count(),
                1,
            )
        finally:
            db.close()

    def test_phase4_checkout_launch_without_plan_fails_safely(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("missing-plan@academy.edu")

        with (
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("Select+a+subscription+plan+before+continuing+to+checkout", response.headers["location"])
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

    def test_phase4_payment_confirmed_cannot_restart_initial_checkout(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("paid-lock@academy.edu")

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

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            organization.billing_status = "payment_confirmed"
            organization.payment_status = "paid"
            db.commit()
        finally:
            db.close()

        with (
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure+Payment+cannot+be+opened", response.headers["location"])
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

    def test_public_paddle_payment_launcher_is_accessible_without_login(self):
        with patch.dict(
            os.environ,
            {
                "PADDLE_CLIENT_TOKEN": "test_publicpaymenttoken123456789",
                "PADDLE_ENVIRONMENT": "sandbox",
                "PADDLE_API_KEY": "pdl_secret_api_key_must_not_render",
            },
            clear=False,
        ):
            response = self.client.get("/saas/payment?_ptxn=txn_01kxpaymentlauncher", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("location"))
        self.assertIn("https://cdn.paddle.com/paddle/v2/paddle.js", response.text)
        self.assertIn("test_publicpaymenttoken123456789", response.text)
        self.assertNotIn("pdl_secret_api_key_must_not_render", response.text)
        self.assertIn('window.Paddle.Environment.set("sandbox")', response.text)
        self.assertIn('.get("_ptxn")', response.text)
        self.assertIn("transactionId: transactionId", response.text)
        self.assertNotIn("checkout_session_id", response.text)
        self.assertNotIn("payment_attempt_uuid", response.text)

    def test_public_paddle_payment_launcher_handles_missing_transaction_safely(self):
        with patch.dict(
            os.environ,
            {
                "PADDLE_CLIENT_TOKEN": "test_publicpaymenttoken123456789",
                "PADDLE_ENVIRONMENT": "sandbox",
            },
            clear=False,
        ):
            response = self.client.get("/saas/payment", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Missing or invalid payment link", response.text)
        self.assertNotIn("txn_01kxpaymentlauncher", response.text)

    def test_public_paddle_payment_launcher_handles_missing_client_token_safely(self):
        with patch.dict(os.environ, {"PADDLE_CLIENT_TOKEN": "", "PADDLE_ENVIRONMENT": "sandbox"}, clear=False):
            response = self.client.get("/saas/payment?_ptxn=txn_01kxpaymentlauncher", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Unable to open secure payment", response.text)
        self.assertIn('const paddleClientToken = "";', response.text)
        self.assertNotIn("PADDLE_API_KEY", response.text)

    def test_phase4_checkout_transaction_uses_configured_payment_launcher_url(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("payment-url@academy.edu")

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
            patch.dict(
                os.environ,
                {"PADDLE_CHECKOUT_BASE_URL": "https://app.tisplatform.com/saas/payment"},
                clear=False,
            ),
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch(
                "saas.paddle_client.create_customer",
                return_value={"id": "ctm_payment_url_123", "email": "payment-url@academy.edu", "name": "Payment URL", "status": "active"},
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_payment_url_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_payment_url_123", "url": "https://app.tisplatform.com/saas/payment?_ptxn=txn_payment_url_123"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://app.tisplatform.com/saas/payment?_ptxn=txn_payment_url_123")
        self.assertEqual(create_transaction.call_args.kwargs["checkout_url"], "https://app.tisplatform.com/saas/payment")

    def test_phase4_reuses_existing_local_paddle_customer_mapping(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("reuse-local@academy.edu")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            account = db.query(saas.models.SaaSAccount).filter_by(id=organization.owner_saas_account_id).first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
            db.add(
                saas.models.PaymentCustomer(
                    pending_organization_id=organization.id,
                    saas_account_id=account.id,
                    provider="paddle",
                    provider_customer_id="ctm_existing_local_123",
                    email="reuse-local@academy.edu",
                    name="Reuse Local",
                    country_code="SA",
                    status="active",
                )
            )
            db.commit()
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        with (
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_reuse_local_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_reuse_local_123", "url": "https://pay.paddle.test/reuse-local"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        list_customers.assert_not_called()
        create_customer.assert_not_called()
        create_transaction.assert_called_once()
        self.assertEqual(create_transaction.call_args.kwargs["customer_id"], "ctm_existing_local_123")

    def test_phase4_links_existing_remote_paddle_customer_by_email(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("remote-link@academy.edu")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            account = db.query(saas.models.SaaSAccount).filter_by(id=organization.owner_saas_account_id).first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
            account_uuid = account.account_uuid
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        remote_customer = {
            "id": "ctm_remote_link_123",
            "email": "remote-link@academy.edu",
            "name": "Remote Link",
            "status": "active",
            "custom_data": {"saas_account_uuid": account_uuid, "pending_organization_uuid": org_uuid},
        }
        with (
            patch("saas.paddle_client.list_customers_by_email", return_value=[remote_customer]) as list_customers,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_remote_link_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_remote_link_123", "url": "https://pay.paddle.test/remote-link"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        list_customers.assert_called_once_with("remote-link@academy.edu")
        create_customer.assert_not_called()
        self.assertEqual(create_transaction.call_args.kwargs["customer_id"], "ctm_remote_link_123")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            payment_customer = db.query(saas.models.PaymentCustomer).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertIsNotNone(payment_customer)
            self.assertEqual(payment_customer.provider_customer_id, "ctm_remote_link_123")
        finally:
            db.close()

    def test_phase4_transaction_failure_preserves_customer_mapping_for_retry(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("retry-customer@academy.edu")

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
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch(
                "saas.paddle_client.create_customer",
                return_value={"id": "ctm_retry_123", "email": "retry-customer@academy.edu", "name": "Retry Customer", "status": "active"},
            ) as create_customer,
            patch("saas.paddle_client.create_transaction", side_effect=paddle_client.PaddleAPIError("Transaction failed")) as create_transaction,
        ):
            first_response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(first_response.status_code, 302)
        create_customer.assert_called_once()
        create_transaction.assert_called_once()

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            payment_customer = db.query(saas.models.PaymentCustomer).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertIsNotNone(payment_customer)
            self.assertEqual(payment_customer.provider_customer_id, "ctm_retry_123")
            self.assertEqual(
                db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).count(),
                0,
            )
        finally:
            db.close()

        with (
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_retry_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_retry_123", "url": "https://pay.paddle.test/retry"},
                },
            ) as create_transaction,
        ):
            second_response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(second_response.status_code, 302)
        list_customers.assert_not_called()
        create_customer.assert_not_called()
        self.assertEqual(create_transaction.call_args.kwargs["customer_id"], "ctm_retry_123")

    def test_phase4_customer_email_conflict_recovers_by_linking_existing_remote_customer(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("conflict-link@academy.edu")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            account = db.query(saas.models.SaaSAccount).filter_by(id=organization.owner_saas_account_id).first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
            account_uuid = account.account_uuid
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        remote_customer = {
            "id": "ctm_conflict_link_123",
            "email": "conflict-link@academy.edu",
            "name": "Conflict Link",
            "status": "active",
            "custom_data": {"saas_account_uuid": account_uuid, "pending_organization_uuid": org_uuid},
        }
        with (
            patch("saas.paddle_client.list_customers_by_email", side_effect=[[], [remote_customer]]),
            patch(
                "saas.paddle_client.create_customer",
                side_effect=paddle_client.PaddleAPIError(
                    "customer email conflicts with customer of id ctm_conflict_link_123",
                    status_code=409,
                    body={"error": {"code": "customer_email_conflict", "detail": "customer email conflicts with customer of id ctm_conflict_link_123"}},
                ),
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_conflict_link_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_conflict_link_123", "url": "https://pay.paddle.test/conflict-link"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_transaction.call_args.kwargs["customer_id"], "ctm_conflict_link_123")

    def test_phase4_unrelated_remote_customer_match_fails_safely(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("unrelated-remote@academy.edu")

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

        remote_customer = {
            "id": "ctm_unrelated_123",
            "email": "unrelated-remote@academy.edu",
            "name": "Unrelated",
            "status": "active",
            "custom_data": {"saas_account_uuid": "different-account"},
        }
        with (
            patch("saas.paddle_client.list_customers_by_email", return_value=[remote_customer]),
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure+payment+is+temporarily+unavailable+for+this+account", response.headers["location"])
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

    def test_phase4_sandbox_relinks_unique_customer_from_deleted_test_context(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("sandbox-relink@academy.edu")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            account = db.query(saas.models.SaaSAccount).filter_by(id=organization.owner_saas_account_id).first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
            account_uuid = account.account_uuid
        finally:
            db.close()

        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        remote_customer = {
            "id": "ctm_sandbox_relink_123",
            "email": "sandbox-relink@academy.edu",
            "name": "Sandbox Relink",
            "status": "active",
            "custom_data": {
                "saas_account_uuid": "deleted-account-uuid",
                "pending_organization_uuid": "deleted-organization-uuid",
                "preserved_reference": "keep-me",
            },
        }
        updated_customer = {
            **remote_customer,
            "custom_data": {
                "saas_account_uuid": account_uuid,
                "pending_organization_uuid": org_uuid,
                "preserved_reference": "keep-me",
            },
        }
        with (
            patch.dict(
                os.environ,
                {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""},
                clear=False,
            ),
            patch("saas.paddle_client.list_customers_by_email", return_value=[remote_customer]),
            patch("saas.paddle_client.update_customer", return_value=updated_customer) as update_customer,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_sandbox_relink_123",
                    "currency_code": "USD",
                    "checkout": {"id": "chk_sandbox_relink_123", "url": "https://pay.paddle.test/sandbox-relink"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "https://pay.paddle.test/sandbox-relink")
        update_customer.assert_called_once_with(
            customer_id="ctm_sandbox_relink_123",
            custom_data={
                "saas_account_uuid": account_uuid,
                "pending_organization_uuid": org_uuid,
                "preserved_reference": "keep-me",
            },
        )
        create_customer.assert_not_called()
        self.assertEqual(create_transaction.call_args.kwargs["customer_id"], "ctm_sandbox_relink_123")
        self.assertEqual(create_transaction.call_args.kwargs["quantity"], 2)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            payment_customer = db.query(saas.models.PaymentCustomer).filter_by(
                pending_organization_id=organization.id
            ).one()
            self.assertEqual(payment_customer.provider_customer_id, "ctm_sandbox_relink_123")
            event = db.query(saas.models.PendingOrganizationEvent).filter_by(
                pending_organization_id=organization.id,
                event_type="paddle_customer_relinked",
            ).one()
            details = json.loads(event.details_json)
            self.assertEqual(details["reason_code"], "sandbox_customer_relinked")
            self.assertEqual(details["result"], "success")
            self.assertEqual(details["previous_context"]["saas_account_uuid"], "deleted-account-uuid")
            self.assertEqual(details["new_context"]["saas_account_uuid"], account_uuid)
            attempt = db.query(saas.models.PaymentAttempt).filter_by(
                pending_organization_id=organization.id
            ).one()
            self.assertEqual(attempt.quantity, 2)
            self.assertEqual(attempt.amount_minor, attempt.unit_amount_minor * 2)
        finally:
            db.close()

    def test_phase4_production_never_relinks_customer_by_email_only(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("production-mismatch@academy.edu")

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

        remote_customer = {
            "id": "ctm_production_mismatch_123",
            "email": "production-mismatch@academy.edu",
            "status": "active",
            "custom_data": {
                "saas_account_uuid": "old-account",
                "pending_organization_uuid": "old-organization",
            },
        }
        with (
            patch.dict(
                os.environ,
                {
                    "PADDLE_ENVIRONMENT": "production",
                    "PADDLE_API_BASE_URL": "https://api.paddle.com",
                    "TIS_ENABLE_PADDLE_TEST_CUSTOMER_RECOVERY": "true",
                    "TIS_ENV": "production",
                },
                clear=False,
            ),
            patch("saas.paddle_client.list_customers_by_email", return_value=[remote_customer]),
            patch("saas.paddle_client.update_customer") as update_customer,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure+payment+is+temporarily+unavailable+for+this+account", response.headers["location"])
        self.assertNotIn("Diagnostic", response.headers["location"])
        update_customer.assert_not_called()
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

    def test_phase4_sandbox_blocks_ambiguous_exact_email_customers(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("ambiguous-paddle@academy.edu")

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

        remote_customers = [
            {
                "id": f"ctm_ambiguous_{index}",
                "email": "ambiguous-paddle@academy.edu",
                "status": "active",
                "custom_data": {
                    "saas_account_uuid": f"old-account-{index}",
                    "pending_organization_uuid": f"old-org-{index}",
                },
            }
            for index in (1, 2)
        ]
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""}, clear=False),
            patch("saas.paddle_client.list_customers_by_email", return_value=remote_customers),
            patch("saas.paddle_client.update_customer") as update_customer,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("ambiguous_exact_email_matches", response.headers["location"])
        update_customer.assert_not_called()
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

    def test_phase4_sandbox_never_relinks_customer_whose_old_context_still_exists(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("owned-elsewhere@academy.edu")

        db = self._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
            db.add(
                saas.models.SaaSAccount(
                    account_uuid="still-existing-old-account",
                    email="different-owner@academy.edu",
                    email_normalized="different-owner@academy.edu",
                    status="active",
                    onboarding_status="not_started",
                )
            )
            db.commit()
        finally:
            db.close()
        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "annual"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        remote_customer = {
            "id": "ctm_owned_elsewhere_123",
            "email": "owned-elsewhere@academy.edu",
            "status": "active",
            "custom_data": {
                "saas_account_uuid": "still-existing-old-account",
                "pending_organization_uuid": "deleted-old-organization",
            },
        }
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""}, clear=False),
            patch("saas.paddle_client.list_customers_by_email", return_value=[remote_customer]),
            patch("saas.paddle_client.update_customer") as update_customer,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("remote_customer_account_context_still_exists", response.headers["location"])
        update_customer.assert_not_called()
        create_customer.assert_not_called()
        create_transaction.assert_not_called()

    def test_phase4_sandbox_email_conflict_relookup_can_relink_deleted_test_context(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("conflict-relink@academy.edu")

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            account = db.query(saas.models.SaaSAccount).filter_by(id=organization.owner_saas_account_id).first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            professional_id = professional.id
            account_uuid = account.account_uuid
        finally:
            db.close()
        self.client.post(
            f"/saas/onboarding/{org_uuid}/plan",
            data={"plan_id": str(professional_id), "billing_interval": "monthly"},
            follow_redirects=False,
        )
        self.client.post(f"/saas/onboarding/{org_uuid}/checkout/start", follow_redirects=False)

        old_customer = {
            "id": "ctm_conflict_relink_123",
            "email": "conflict-relink@academy.edu",
            "status": "active",
            "custom_data": {
                "saas_account_uuid": "deleted-conflict-account",
                "pending_organization_uuid": "deleted-conflict-organization",
            },
        }
        updated_customer = {
            **old_customer,
            "custom_data": {
                "saas_account_uuid": account_uuid,
                "pending_organization_uuid": org_uuid,
            },
        }
        conflict = paddle_client.PaddleAPIError(
            "customer email conflicts with customer of id ctm_conflict_relink_123",
            status_code=409,
            body={
                "error": {
                    "code": "customer_email_conflict",
                    "detail": "customer email conflicts with customer of id ctm_conflict_relink_123",
                }
            },
        )
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""}, clear=False),
            patch("saas.paddle_client.list_customers_by_email", side_effect=[[], [old_customer]]) as lookup,
            patch("saas.paddle_client.create_customer", side_effect=conflict) as create_customer,
            patch("saas.paddle_client.update_customer", return_value=updated_customer) as update_customer,
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_conflict_relink_123",
                    "currency_code": "USD",
                    "checkout": {"url": "https://pay.paddle.test/conflict-relink"},
                },
            ) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(lookup.call_count, 2)
        create_customer.assert_called_once()
        update_customer.assert_called_once()
        self.assertEqual(create_transaction.call_args.kwargs["customer_id"], "ctm_conflict_relink_123")

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
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
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
        self.assertIn("secure verification is processed", return_response.text)
        self.assertIn("This does not by itself confirm payment", return_response.text)
        self.assertEqual(return_response.text.count('data-primary-cta="true"'), 1)
        self.assertNotIn(attempt_uuid, return_response.text)
        self.assertNotIn("checkout_started", return_response.text)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
            self.assertEqual(organization.billing_status, "checkout_started")
            self.assertEqual(organization.payment_status, "pending")
            self.assertEqual(attempt.status, "checkout_started")
        finally:
            db.close()

        cancel_response = self.client.get("/saas/checkout/cancel")
        self.assertEqual(cancel_response.status_code, 200)
        self.assertIn("Secure Payment was not completed", cancel_response.text)
        self.assertIn("Workspace Activation begins only after payment is confirmed.", cancel_response.text)
        self.assertEqual(cancel_response.text.count('data-primary-cta="true"'), 1)

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
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
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
            meaningful_activity_before_webhooks = organization.last_meaningful_activity_at
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
                        "quantity": 2,
                        "price": {
                            "id": "pri_test_2_annual",
                            "unit_price": {"amount": "79000", "currency_code": "USD"},
                            "billing_cycle": {"interval": "year", "frequency": 1},
                        },
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
                "items": [
                    {
                        "quantity": 2,
                        "price": {
                            "id": "pri_test_2_annual",
                            "unit_price": {"amount": "79000", "currency_code": "USD"},
                            "billing_cycle": {"interval": "year", "frequency": 1},
                        },
                    }
                ],
                "details": {
                    "totals": {"subtotal": "158000", "currency_code": "USD"},
                    "line_items": [
                        {
                            "price_id": "pri_test_2_annual",
                            "quantity": 2,
                            "totals": {"subtotal": "158000"},
                        }
                    ],
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
            self.assertEqual(
                organization.last_meaningful_activity_at,
                meaningful_activity_before_webhooks,
            )
            self.assertEqual(attempt.status, "payment_confirmed")
            self.assertEqual(attempt.provider_subscription_id, "sub_webhook_123")
            self.assertEqual(contract.contract_status, "tenant_active")
            self.assertEqual(contract.payment_status, "paid")
            self.assertIsNotNone(payment_subscription)
            self.assertEqual(payment_subscription.provider_subscription_id, "sub_webhook_123")
            self.assertEqual(payment_subscription.status, "active")
            self.assertEqual(payment_subscription.provider_price_id, "pri_test_2_annual")
            self.assertEqual(payment_subscription.quantity, 2)
            self.assertEqual(payment_subscription.unit_amount_minor, 79000)
            self.assertEqual(payment_subscription.amount_minor, 158000)
            self.assertEqual(payment_subscription.currency_code, "USD")
            self.assertEqual(payment_subscription.billing_interval, "annual")
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
        self._configure_paddle_prices()
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

        db = self._db()
        try:
            owner_activity_before = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=org_uuid
            ).one().last_meaningful_activity_at
        finally:
            db.close()

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
        db = self._db()
        try:
            self.assertEqual(
                db.query(saas.models.PendingOrganization).filter_by(
                    organization_uuid=org_uuid
                ).one().last_meaningful_activity_at,
                owner_activity_before,
            )
        finally:
            db.close()

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

    def test_branch_identity_edit_add_remove_and_duplicate_validation(self):
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("stable-branches@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            original = service.list_billable_pending_branches(db, organization)
            original_by_name = {row.branch_name: row.branch_uuid for row in original}
        finally:
            db.close()

        response = self.client.post(f"/saas/onboarding/{org_uuid}/branches", data={
            "branch_uuid": [original_by_name["Girls Campus"], original_by_name["Main Campus"], ""],
            "branch_name": ["Girls Campus Renamed", "Main Campus", "New West Campus"],
            "location": ["North", "Central", "West"],
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            rows = service.list_billable_pending_branches(db, organization)
            by_name = {row.branch_name: row for row in rows}
            self.assertEqual(by_name["Girls Campus Renamed"].branch_uuid, original_by_name["Girls Campus"])
            self.assertEqual(by_name["Main Campus"].branch_uuid, original_by_name["Main Campus"])
            new_uuid = by_name["New West Campus"].branch_uuid
            self.assertNotIn(new_uuid, set(original_by_name.values()))
        finally:
            db.close()

        remove_response = self.client.post(f"/saas/onboarding/{org_uuid}/branches", data={
            "branch_uuid": [original_by_name["Main Campus"], new_uuid],
            "branch_name": ["Main Campus", "New West Campus"],
            "location": ["Central", "West"],
        }, follow_redirects=False)
        self.assertEqual(remove_response.status_code, 302)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            removed = db.query(saas.models.PendingOrganizationBranch).filter_by(
                branch_uuid=original_by_name["Girls Campus"]
            ).first()
            self.assertFalse(removed.status)
            self.assertEqual(service.count_billable_pending_branches(db, organization), 2)
        finally:
            db.close()

        duplicate = self.client.post(f"/saas/onboarding/{org_uuid}/branches", data={
            "branch_uuid": [original_by_name["Main Campus"], new_uuid],
            "branch_name": ["Main Campus", "  MAIN   CAMPUS  "],
        }, follow_redirects=False)
        self.assertEqual(duplicate.status_code, 422)
        self.assertIn("Active branch names must be unique", duplicate.text)

    def test_branch_setup_is_authoritative_for_reductions_and_expansion(self):
        self._configure_paddle_prices()
        scenarios = ((3, 2), (15, 10), (12, 20))
        for index, (initial_count, final_count) in enumerate(scenarios, start=1):
            with self.subTest(initial_count=initial_count, final_count=final_count):
                org_uuid = self._complete_pending_organization_to_ready_for_checkout(
                    f"branch-count-{index}@academy.edu"
                )
                db = self._db()
                try:
                    organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
                    existing = service.list_billable_pending_branches(db, organization)
                    initial_rows = [
                        {
                            "branch_uuid": row.branch_uuid,
                            "branch_name": f"Campus {position + 1}",
                            "location": row.location,
                        }
                        for position, row in enumerate(existing)
                    ]
                    initial_rows.extend(
                        {"branch_name": f"Campus {position + 1}", "location": f"Location {position + 1}"}
                        for position in range(len(initial_rows), initial_count)
                    )
                    service.replace_branches(db, organization, initial_rows)
                    db.flush()
                    initial_active = service.list_billable_pending_branches(db, organization)
                    initial_uuids = {row.branch_uuid for row in initial_active}
                    initial_fingerprint = None
                    starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
                    organization.selected_plan_id = starter.id
                    organization.selected_billing_interval = "monthly"
                    initial_fingerprint = branch_pricing_quote_service.build_quote(db, organization).fingerprint

                    final_rows = [
                        {
                            "branch_uuid": row.branch_uuid,
                            "branch_name": row.branch_name,
                            "location": row.location,
                        }
                        for row in initial_active[:min(initial_count, final_count)]
                    ]
                    final_rows.extend(
                        {"branch_name": f"Expanded Campus {position + 1}", "location": "Expansion"}
                        for position in range(len(final_rows), final_count)
                    )
                    service.replace_branches(db, organization, final_rows)
                    db.flush()
                    active = service.list_billable_pending_branches(db, organization)
                    quote = branch_pricing_quote_service.build_quote(db, organization)
                    self.assertEqual(len(active), final_count)
                    self.assertEqual(organization.expected_branch_count, final_count)
                    self.assertEqual(quote.quantity, final_count)
                    self.assertNotEqual(initial_fingerprint, quote.fingerprint)
                    if final_count < initial_count:
                        inactive = [
                            row for row in service.list_pending_branches(db, organization, include_inactive=True)
                            if not row.status
                        ]
                        self.assertEqual(len(inactive), initial_count - final_count)
                    if final_count > initial_count:
                        added_uuids = {row.branch_uuid for row in active} - initial_uuids
                        self.assertEqual(len(added_uuids), final_count - initial_count)
                        self.assertTrue(added_uuids.isdisjoint(initial_uuids))
                finally:
                    db.close()

    def test_branch_profile_does_not_recreate_removed_rows_and_primary_is_ordered_first(self):
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("branch-authority@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            rows = service.list_billable_pending_branches(db, organization)
            first_uuid, second_uuid = rows[0].branch_uuid, rows[1].branch_uuid
        finally:
            db.close()

        reorder = self.client.post(f"/saas/onboarding/{org_uuid}/branches", data={
            "branch_uuid": [first_uuid, second_uuid],
            "branch_name": ["Main Campus", "Girls Campus"],
            "primary_branch_index": "1",
        }, follow_redirects=False)
        self.assertEqual(reorder.status_code, 302)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            ordered = service.list_billable_pending_branches(db, organization)
            self.assertEqual(ordered[0].branch_uuid, second_uuid)
        finally:
            db.close()

        remove = self.client.post(f"/saas/onboarding/{org_uuid}/branches", data={
            "branch_uuid": [second_uuid],
            "branch_name": ["Girls Campus"],
            "primary_branch_index": "0",
        }, follow_redirects=False)
        self.assertEqual(remove.status_code, 302)
        profile = self.client.post(f"/saas/onboarding/{org_uuid}/organization", data={
            "organization_name": "Example Academy",
            "educational_program": "BOTH",
            "country_code": "SA",
            "country_name": "Saudi Arabia",
            "region_name": "Riyadh",
            "city_name": "Riyadh",
            "expected_branch_count": "99",
            "timezone": "Asia/Riyadh",
            "save_action": "continue",
        }, follow_redirects=False)
        self.assertEqual(profile.status_code, 302)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            self.assertEqual(organization.expected_branch_count, 1)
            self.assertEqual(service.count_billable_pending_branches(db, organization), 1)
            removed = db.query(saas.models.PendingOrganizationBranch).filter_by(branch_uuid=first_uuid).first()
            self.assertFalse(removed.status)
            with self.assertRaisesRegex(ValueError, "Add at least one branch"):
                service.replace_branches(db, organization, [])
        finally:
            db.close()
        branch_page = self.client.get(f"/saas/onboarding/{org_uuid}/branches")
        self.assertIn("At least one branch is required.", branch_page.text)
        self.assertIn("Subscription quantity updates automatically", branch_page.text)
        self.assertIn("data-remove-branch disabled", branch_page.text)
        self.assertIn("Add Branch", branch_page.text)
        self.assertIn('window.confirm(`Remove "${name}" from Branch Setup?`)', branch_page.text)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            organization.payment_status = "paid"
            with self.assertRaisesRegex(ValueError, "cannot be changed after payment"):
                service.replace_branches(db, organization, [{
                    "branch_uuid": second_uuid, "branch_name": "Girls Campus",
                }])
        finally:
            db.close()

    def test_removed_branch_uuid_is_not_reused_and_next_checkout_uses_new_quantity(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("branch-paddle-refresh@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
            billing_service.select_plan(db, organization, plan_id=starter.id, billing_interval="monthly")
            old_checkout = billing_service.create_or_update_checkout_session(db, organization)
            old_checkout.status = "started"
            old_checkout.checkout_url = "https://pay.paddle.test/old-two-branches"
            old_checkout_id = old_checkout.id
            rows = service.list_billable_pending_branches(db, organization)
            kept_uuid, removed_uuid = rows[0].branch_uuid, rows[1].branch_uuid
            service.replace_branches(db, organization, [{
                "branch_uuid": kept_uuid, "branch_name": rows[0].branch_name, "location": rows[0].location,
            }])
            db.flush()
            self.assertEqual(old_checkout.status, "stale")
            organization.status = service.READY_FOR_CHECKOUT_STATUS
            db.commit()
        finally:
            db.close()

        with (
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch("saas.paddle_client.create_customer", return_value={
                "id": "ctm_branch_refresh", "email": "branch-paddle-refresh@academy.edu", "status": "active",
            }),
            patch("saas.paddle_client.create_transaction", return_value={
                "id": "txn_branch_refresh", "currency_code": "USD",
                "checkout": {"url": "https://pay.paddle.test/refreshed-one-branch"},
            }) as create_transaction,
        ):
            response = self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(create_transaction.call_args.kwargs["quantity"], 1)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            fresh_checkout = billing_service.get_current_checkout_session(db, organization)
            self.assertNotEqual(fresh_checkout.id, old_checkout_id)
            self.assertEqual(fresh_checkout.billable_branch_count, 1)
            service.replace_branches(db, organization, [
                {"branch_uuid": kept_uuid, "branch_name": "Main Campus"},
                {"branch_name": "Replacement Campus"},
            ])
            db.flush()
            replacement = service.list_billable_pending_branches(db, organization)[1]
            self.assertNotEqual(replacement.branch_uuid, removed_uuid)
        finally:
            db.close()

    def test_zero_billable_branches_blocks_quote(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("zero-branches@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
            for branch in service.list_pending_branches(db, organization):
                branch.status = False
            organization.selected_plan_id = starter.id
            organization.selected_billing_interval = "monthly"
            quote = branch_pricing_quote_service.build_quote(db, organization)
            self.assertFalse(quote.is_ready)
            self.assertEqual(quote.quantity, 0)
            self.assertIn("Add at least one active branch", quote.errors[0])
        finally:
            db.close()

    def test_branch_quote_exact_starter_and_enterprise_totals(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("quote-totals@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            branches = service.list_billable_pending_branches(db, organization)
            branches[1].status = False
            starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
            organization.selected_plan_id = starter.id
            organization.selected_billing_interval = "monthly"
            one_branch = branch_pricing_quote_service.build_quote(db, organization)
            self.assertEqual((one_branch.unit_amount_minor, one_branch.quantity, one_branch.total_amount_minor), (2900, 1, 2900))
            self.assertEqual(one_branch.formatted_total, "USD 29.00")

            branches[1].status = True
            db.add(saas.models.PendingOrganizationBranch(
                branch_uuid="00000000-0000-0000-0000-000000000303",
                pending_organization_id=organization.id,
                branch_name="West Campus",
                status=True,
                sort_order=2,
            ))
            enterprise = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="enterprise_ai").first()
            organization.selected_plan_id = enterprise.id
            organization.selected_billing_interval = "monthly"
            monthly = branch_pricing_quote_service.build_quote(db, organization)
            self.assertEqual((monthly.quantity, monthly.total_amount_minor, monthly.formatted_total), (3, 44700, "USD 447.00"))
            organization.selected_billing_interval = "annual"
            annual = branch_pricing_quote_service.build_quote(db, organization)
            self.assertEqual((annual.quantity, annual.total_amount_minor, annual.formatted_total), (3, 447000, "USD 4,470.00"))
        finally:
            db.close()

    def test_quote_fingerprint_tracks_plan_interval_price_provider_and_branches(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("quote-fingerprint@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            organization.selected_plan_id = starter.id
            organization.selected_billing_interval = "monthly"
            initial = branch_pricing_quote_service.build_quote(db, organization)
            self.assertEqual(initial.fingerprint, branch_pricing_quote_service.build_quote(db, organization).fingerprint)
            organization.selected_plan_id = professional.id
            plan_changed = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(initial.fingerprint, plan_changed.fingerprint)
            organization.selected_billing_interval = "annual"
            interval_changed = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(plan_changed.fingerprint, interval_changed.fingerprint)
            price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=professional.id, billing_interval="annual", is_active=True
            ).order_by(saas.models.SubscriptionPlanPrice.plan_version.desc()).first()
            price.provider_price_id = "pri_fingerprint_provider_changed"
            provider_changed = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(interval_changed.fingerprint, provider_changed.fingerprint)
            price.amount_minor += 100
            amount_changed = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(provider_changed.fingerprint, amount_changed.fingerprint)
            db.add(saas.models.SubscriptionPlanPrice(
                plan_id=professional.id, billing_interval="annual", currency_code="USD",
                amount_minor=price.amount_minor, provider_price_id="pri_new_price_version",
                plan_version=int(price.plan_version or 1) + 1, is_active=True,
            ))
            db.flush()
            version_changed = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(amount_changed.fingerprint, version_changed.fingerprint)
            added = saas.models.PendingOrganizationBranch(
                branch_uuid="00000000-0000-0000-0000-000000000304",
                pending_organization_id=organization.id, branch_name="Fingerprint Campus", status=True, sort_order=3,
            )
            db.add(added)
            db.flush()
            branch_added = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(version_changed.fingerprint, branch_added.fingerprint)
            added.status = False
            branch_removed = branch_pricing_quote_service.build_quote(db, organization)
            self.assertNotEqual(branch_added.fingerprint, branch_removed.fingerprint)
        finally:
            db.close()

    def test_branch_change_stales_checkout_and_quote_snapshots_are_persisted(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("stale-quote@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            professional = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").first()
            selection = billing_service.select_plan(db, organization, plan_id=professional.id, billing_interval="monthly")
            original = billing_service.create_or_update_checkout_session(db, organization)
            contract = billing_service.get_current_subscription_contract(db, organization)
            self.assertEqual(selection.quote_fingerprint, contract.quote_fingerprint)
            self.assertEqual(selection.quote_fingerprint, original.quote_fingerprint)
            original.status = "started"
            original.checkout_url = "https://checkout.example.test/stale"
            original_id = original.id
            original_fingerprint = original.quote_fingerprint
            branches = service.list_billable_pending_branches(db, organization)
            service.replace_branches(db, organization, [
                {"branch_uuid": row.branch_uuid, "branch_name": row.branch_name, "location": row.location}
                for row in branches
            ] + [{"branch_name": "New Quote Campus", "location": "West"}])
            self.assertEqual(original.status, "stale")
            organization.status = service.READY_FOR_CHECKOUT_STATUS
            fresh = billing_service.create_or_update_checkout_session(db, organization)
            self.assertNotEqual(original_id, fresh.id)
            self.assertNotEqual(original_fingerprint, fresh.quote_fingerprint)
            self.assertIsNone(fresh.checkout_url)
        finally:
            db.close()

    def test_branch_removal_invalidates_started_checkout(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("remove-stale@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
            billing_service.select_plan(db, organization, plan_id=starter.id, billing_interval="monthly")
            checkout = billing_service.create_or_update_checkout_session(db, organization)
            checkout.status = "started"
            checkout.checkout_url = "https://checkout.example.test/remove-stale"
            branches = service.list_billable_pending_branches(db, organization)
            service.replace_branches(db, organization, [{
                "branch_uuid": branches[0].branch_uuid,
                "branch_name": branches[0].branch_name,
                "location": branches[0].location,
            }])
            db.flush()
            self.assertEqual(checkout.status, "stale")
            self.assertIsNotNone(checkout.abandoned_at)
            self.assertEqual(service.count_billable_pending_branches(db, organization), 1)
        finally:
            db.close()

    def test_subscription_and_checkout_pages_show_branch_quote_without_fingerprint(self):
        self._configure_paddle_prices()
        org_uuid = self._complete_pending_organization_to_ready_for_checkout("quote-ui@academy.edu")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
            enterprise = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="enterprise_ai").first()
            billing_service.select_plan(db, organization, plan_id=enterprise.id, billing_interval="monthly")
            db.commit()
        finally:
            db.close()
        plan_page = self.client.get(f"/saas/onboarding/{org_uuid}/plan")
        checkout_page = self.client.get(f"/saas/onboarding/{org_uuid}/checkout")
        self.assertIn("Prices are per branch.", plan_page.text)
        self.assertIn("USD 149.00 per branch x 2 branches", plan_page.text)
        self.assertIn("Total: USD 298.00 per month", plan_page.text)
        self.assertIn("Price per branch", checkout_page.text)
        self.assertIn("Billable branches", checkout_page.text)
        self.assertIn("USD 298.00 per month", checkout_page.text)
        self.assertNotIn("quote_fingerprint", checkout_page.text)

    def test_paddle_launch_uses_authoritative_quantity_and_aggregate_total(self):
        self._configure_paddle_prices()
        scenarios = (
            ("starter", "monthly", 1, 2900),
            ("starter", "monthly", 3, 8700),
            ("enterprise_ai", "monthly", 3, 44700),
            ("enterprise_ai", "annual", 3, 447000),
        )
        for index, (plan_code, interval, quantity, expected_total) in enumerate(scenarios, start=1):
            with self.subTest(plan_code=plan_code, interval=interval, quantity=quantity):
                email = f"quantity-{index}@academy.edu"
                org_uuid = self._complete_pending_organization_to_ready_for_checkout(email)
                db = self._db()
                try:
                    organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
                    branches = service.list_billable_pending_branches(db, organization)
                    if quantity == 1:
                        branches[1].status = False
                    elif quantity == 3:
                        db.add(saas.models.PendingOrganizationBranch(
                            branch_uuid=f"00000000-0000-0000-0000-{index:012d}",
                            pending_organization_id=organization.id,
                            branch_name=f"Quantity Campus {index}",
                            status=True,
                            sort_order=2,
                        ))
                    plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code=plan_code).first()
                    billing_service.select_plan(db, organization, plan_id=plan.id, billing_interval=interval)
                    db.commit()
                finally:
                    db.close()

                with (
                    patch("saas.paddle_client.list_customers_by_email", return_value=[]),
                    patch(
                        "saas.paddle_client.create_customer",
                        return_value={"id": f"ctm_quantity_{index}", "email": email, "status": "active"},
                    ),
                    patch(
                        "saas.paddle_client.create_transaction",
                        return_value={
                            "id": f"txn_quantity_{index}",
                            "currency_code": "USD",
                            "checkout": {"url": f"https://pay.paddle.test/quantity/{index}"},
                        },
                    ) as create_transaction,
                ):
                    response = self.client.post(
                        f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False
                    )

                self.assertEqual(response.status_code, 302)
                call = create_transaction.call_args.kwargs
                self.assertEqual(call["quantity"], quantity)
                db = self._db()
                try:
                    organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
                    selection = billing_service.get_current_plan_selection(db, organization)
                    checkout = billing_service.get_current_checkout_session(db, organization)
                    contract = billing_service.get_current_subscription_contract(db, organization)
                    attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
                    for snapshot in (selection, checkout, contract):
                        self.assertEqual(snapshot.billable_branch_count, quantity)
                        self.assertEqual(snapshot.quoted_base_amount_minor, expected_total)
                    self.assertEqual(checkout.amount_minor, checkout.quoted_display_amount_minor)
                    self.assertEqual(attempt.quantity, quantity)
                    self.assertEqual(attempt.unit_amount_minor * attempt.quantity, expected_total)
                    self.assertEqual(attempt.amount_minor, expected_total)
                    self.assertEqual(attempt.quote_fingerprint, checkout.quote_fingerprint)
                finally:
                    db.close()

    def test_paddle_transaction_quantity_has_no_silent_default(self):
        with self.assertRaises(TypeError):
            paddle_client.create_transaction(customer_id="ctm_test", price_id="pri_test")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            paddle_client.create_transaction(customer_id="ctm_test", price_id="pri_test", quantity=0)
        with patch("saas.paddle_client._request", return_value={"id": "txn_test"}) as request_call:
            paddle_client.create_transaction(customer_id="ctm_test", price_id="pri_test", quantity=3)
        self.assertEqual(request_call.call_args.args[2]["items"], [{"price_id": "pri_test", "quantity": 3}])

    def test_paddle_customer_update_uses_documented_patch_endpoint(self):
        custom_data = {
            "saas_account_uuid": "new-account",
            "pending_organization_uuid": "new-organization",
        }
        with patch(
            "saas.paddle_client._request",
            return_value={"id": "ctm_update_123", "custom_data": custom_data},
        ) as request_call:
            result = paddle_client.update_customer(
                customer_id="ctm_update_123",
                custom_data=custom_data,
            )

        self.assertEqual(result["id"], "ctm_update_123")
        request_call.assert_called_once_with(
            "PATCH",
            "/customers/ctm_update_123",
            {"custom_data": custom_data},
        )

    def test_paddle_test_customer_recovery_gate_never_allows_live_api(self):
        with patch.dict(
            os.environ,
            {
                "PADDLE_ENVIRONMENT": "",
                "PADDLE_API_BASE_URL": "",
                "TIS_ENABLE_PADDLE_TEST_CUSTOMER_RECOVERY": "true",
            },
            clear=False,
        ):
            self.assertTrue(payment_service._sandbox_customer_recovery_enabled())
        with patch.dict(
            os.environ,
            {
                "PADDLE_ENVIRONMENT": "sandbox",
                "PADDLE_API_BASE_URL": "https://api.paddle.com",
                "TIS_ENABLE_PADDLE_TEST_CUSTOMER_RECOVERY": "true",
            },
            clear=False,
        ):
            self.assertFalse(payment_service._sandbox_customer_recovery_enabled())
        with patch.dict(
            os.environ,
            {
                "PADDLE_ENVIRONMENT": "production",
                "PADDLE_API_BASE_URL": "https://api.paddle.com",
                "TIS_ENABLE_PADDLE_TEST_CUSTOMER_RECOVERY": "true",
            },
            clear=False,
        ):
            self.assertFalse(payment_service._sandbox_customer_recovery_enabled())

    def test_webhook_mismatch_blocks_activation_and_preserves_payment_evidence(self):
        self._configure_paddle_prices()
        for index, mismatch in enumerate(("quantity", "price", "stale_quote"), start=1):
            with self.subTest(mismatch=mismatch):
                email = f"reconcile-{index}@academy.edu"
                org_uuid = self._complete_pending_organization_to_ready_for_checkout(email)
                db = self._db()
                try:
                    organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
                    starter = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").first()
                    billing_service.select_plan(db, organization, plan_id=starter.id, billing_interval="monthly")
                    db.commit()
                finally:
                    db.close()
                with (
                    patch("saas.paddle_client.list_customers_by_email", return_value=[]),
                    patch(
                        "saas.paddle_client.create_customer",
                        return_value={"id": f"ctm_reconcile_{index}", "email": email, "status": "active"},
                    ),
                    patch(
                        "saas.paddle_client.create_transaction",
                        return_value={
                            "id": f"txn_reconcile_{index}",
                            "currency_code": "USD",
                            "checkout": {"url": f"https://pay.paddle.test/reconcile/{index}"},
                        },
                    ),
                ):
                    self.client.post(f"/saas/onboarding/{org_uuid}/checkout/launch", follow_redirects=False)

                db = self._db()
                try:
                    organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
                    attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
                    contract = billing_service.get_current_subscription_contract(db, organization)
                    if mismatch == "stale_quote":
                        rows = service.list_billable_pending_branches(db, organization)
                        service.replace_branches(db, organization, [
                            {"branch_uuid": row.branch_uuid, "branch_name": row.branch_name, "location": row.location}
                            for row in rows
                        ] + [{"branch_name": "Paid Stale Campus", "location": "West"}])
                        organization.status = service.READY_FOR_CHECKOUT_STATUS
                        db.commit()
                    attempt_uuid = attempt.attempt_uuid
                    contract_id = contract.id
                    expected_price = attempt.provider_price_id
                    expected_quantity = attempt.quantity
                finally:
                    db.close()

                actual_price = "pri_unexpected_price" if mismatch == "price" else expected_price
                actual_quantity = expected_quantity + 1 if mismatch == "quantity" else expected_quantity
                subtotal = 2900 * actual_quantity
                payload = {
                    "event_id": f"evt_reconcile_{index:02d}_123456789012345678901",
                    "event_type": "transaction.completed",
                    "data": {
                        "id": f"txn_reconcile_{index}",
                        "status": "completed",
                        "subscription_id": f"sub_reconcile_{index}",
                        "custom_data": {
                            "pending_organization_uuid": org_uuid,
                            "payment_attempt_uuid": attempt_uuid,
                            "subscription_contract_id": contract_id,
                        },
                        "items": [{
                            "quantity": actual_quantity,
                            "price": {
                                "id": actual_price,
                                "unit_price": {"amount": "2900", "currency_code": "USD"},
                                "billing_cycle": {"interval": "month", "frequency": 1},
                            },
                        }],
                        "details": {
                            "totals": {"subtotal": str(subtotal), "currency_code": "USD"},
                            "line_items": [{
                                "price_id": actual_price,
                                "quantity": actual_quantity,
                                "totals": {"subtotal": str(subtotal)},
                            }],
                        },
                    },
                }
                signature, body = self._sign_paddle_payload(payload)
                response = self.client.post(
                    "/saas/webhooks/paddle",
                    content=body,
                    headers={"Paddle-Signature": signature, "Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, "manual_review")
                db = self._db()
                try:
                    organization = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=org_uuid).first()
                    attempt = db.query(saas.models.PaymentAttempt).filter_by(pending_organization_id=organization.id).first()
                    webhook = db.query(saas.models.PaymentWebhook).filter_by(provider_event_id=payload["event_id"]).first()
                    self.assertEqual(organization.billing_status, "payment_reconciliation_required")
                    self.assertNotEqual(organization.payment_status, "paid")
                    self.assertEqual(attempt.status, "manual_reconciliation")
                    self.assertIsNotNone(attempt.provider_transaction_id)
                    self.assertEqual(webhook.processing_status, "manual_review")
                    self.assertEqual(
                        db.query(saas.models.TenantProvisioningLink).filter_by(pending_organization_id=organization.id).count(), 0
                    )
                    self.assertEqual(
                        db.query(saas.models.ProvisioningJob).filter_by(pending_organization_id=organization.id).count(), 0
                    )
                finally:
                    db.close()

    def test_branch_quote_migration_backfills_legacy_branch_identity(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        try:
            with legacy_engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE pending_organization_branches ("
                    "id INTEGER PRIMARY KEY, pending_organization_id INTEGER NOT NULL, "
                    "branch_name VARCHAR(160) NOT NULL, status BOOLEAN NOT NULL DEFAULT TRUE)"
                ))
                connection.execute(text(
                    "INSERT INTO pending_organization_branches "
                    "(id, pending_organization_id, branch_name, status) VALUES "
                    "(1, 10, 'Legacy Main', TRUE), (2, 10, 'Legacy West', TRUE)"
                ))
                for table_name in (
                    "pending_organization_plan_selections", "checkout_sessions", "subscription_contracts"
                ):
                    connection.execute(text(f"CREATE TABLE {table_name} (id INTEGER PRIMARY KEY)"))
                db_migrations._branch_billing_quote_foundation(legacy_engine, connection)

            inspector = inspect(legacy_engine)
            branch_columns = {column["name"] for column in inspector.get_columns("pending_organization_branches")}
            self.assertIn("branch_uuid", branch_columns)
            with legacy_engine.connect() as connection:
                branch_uuids = [row[0] for row in connection.execute(text(
                    "SELECT branch_uuid FROM pending_organization_branches ORDER BY id"
                )).all()]
            self.assertEqual(len(branch_uuids), 2)
            self.assertTrue(all(len(value) == 36 for value in branch_uuids))
            self.assertEqual(len(set(branch_uuids)), 2)
            for table_name in (
                "pending_organization_plan_selections", "checkout_sessions", "subscription_contracts"
            ):
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                self.assertTrue({
                    "billable_branch_count", "quoted_base_amount_minor",
                    "quoted_display_amount_minor", "quote_fingerprint",
                }.issubset(columns))
        finally:
            legacy_engine.dispose()

    def test_paddle_quantity_migration_adds_only_reconciliation_snapshots(self):
        legacy_engine = create_engine("sqlite:///:memory:")
        try:
            with legacy_engine.begin() as connection:
                connection.execute(text("CREATE TABLE payment_attempts (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE payment_subscriptions (id INTEGER PRIMARY KEY)"))
                db_migrations._paddle_branch_quantity_reconciliation(legacy_engine, connection)
            inspector = inspect(legacy_engine)
            expected = {
                "provider_price_id", "quantity", "unit_amount_minor", "amount_minor",
                "currency_code", "quote_fingerprint",
            }
            for table_name in ("payment_attempts", "payment_subscriptions"):
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                self.assertTrue(expected.issubset(columns))
        finally:
            legacy_engine.dispose()

    def test_customer_journey_records_only_explicit_meaningful_activity_triggers(self):
        recorded_sources = []
        real_record = draft_lifecycle_service.record_meaningful_activity

        def capture_record(*args, **kwargs):
            recorded_sources.append(kwargs.get("source"))
            return real_record(*args, **kwargs)

        with patch(
            "saas.draft_lifecycle_service.record_meaningful_activity",
            side_effect=capture_record,
        ):
            organization_uuid = self._complete_pending_organization_to_ready_for_checkout(
                "lifecycle.routes@example.com"
            )
            self._configure_paddle_prices()
            db = self._db()
            try:
                plan = db.query(saas.models.SubscriptionPlan).filter_by(
                    plan_code="starter"
                ).first()
                self.assertIsNotNone(plan)
                plan_id = plan.id
            finally:
                db.close()

            plan_response = self.client.post(
                f"/saas/onboarding/{organization_uuid}/plan",
                data={"plan_id": str(plan_id), "billing_interval": "monthly"},
                follow_redirects=False,
            )
            self.assertEqual(plan_response.status_code, 302)
            summary_response = self.client.get(
                f"/saas/onboarding/{organization_uuid}/checkout",
                follow_redirects=False,
            )
            self.assertEqual(summary_response.status_code, 200)
            start_response = self.client.post(
                f"/saas/onboarding/{organization_uuid}/checkout/start",
                follow_redirects=False,
            )
            self.assertEqual(start_response.status_code, 302)
            with patch(
                "saas.payment_service.launch_checkout",
                return_value={"checkout_url": "https://sandbox-checkout.example/launch"},
            ):
                launch_response = self.client.post(
                    f"/saas/onboarding/{organization_uuid}/checkout/launch",
                    follow_redirects=False,
                )
            self.assertEqual(launch_response.status_code, 302)
            self.assertEqual(
                launch_response.headers["location"],
                "https://sandbox-checkout.example/launch",
            )

        self.assertTrue({
            "account_created",
            "successful_login",
            "onboarding_started",
            "organization_profile_saved",
            "branch_setup_saved",
            "academic_setup_saved",
            "contacts_saved",
            "review_submitted",
            "plan_selected",
            "checkout_summary_opened",
            "checkout_started",
            "checkout_launched",
        }.issubset(set(recorded_sources)), recorded_sources)
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            account = db.query(saas.models.SaaSAccount).filter_by(
                id=organization.owner_saas_account_id
            ).one()
            self.assertEqual(
                account.last_meaningful_activity_at,
                organization.last_meaningful_activity_at,
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
