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
