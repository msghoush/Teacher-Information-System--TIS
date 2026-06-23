import os
import re
import unittest
from unittest.mock import patch

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
import saas.models  # noqa: F401 - register metadata
from dependencies import get_db
from saas import oauth, service
from saas.router import router as saas_router


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
        captured = {}

        def fake_send_email(**kwargs):
            captured["text"] = kwargs["text"]
            captured["html"] = kwargs.get("html") or ""
            return "email_456"

        with patch("email_service.send_email", side_effect=fake_send_email):
            self.client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Owner",
                    "last_name": "User",
                    "email": "owner@school.edu",
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
        self.assertIn("verified", verify_response.text.lower())

        login_response = self.client.post(
            "/saas/auth/login",
            data={"email": "owner@school.edu", "password": "strong-password-123", "next_path": "/saas/account"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers["location"], "/saas/account")
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


if __name__ == "__main__":
    unittest.main()
