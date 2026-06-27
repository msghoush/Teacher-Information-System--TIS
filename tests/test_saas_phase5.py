import hashlib
import hmac
import json
import os
import re
import time
import unittest
from unittest.mock import patch

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"
os.environ["PADDLE_API_KEY"] = "pdl_test_phase5_api_key"
os.environ["PADDLE_WEBHOOK_SECRET"] = "pdl_ntfset_test_phase5_secret"
os.environ["PADDLE_WEBHOOK_TOLERANCE_SECONDS"] = "30"
os.environ["TIS_PUBLIC_BASE_URL"] = "http://testserver"

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db_migrations
import models
import permission_registry
import saas.models  # noqa: F401
from dependencies import get_db
from saas import provisioning_service
from saas.router import admin_router as saas_admin_router, router as saas_router


class SaaSPhase5ProvisioningTests(unittest.TestCase):
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

    def _configure_paddle_prices(self):
        db = self._db()
        try:
            for row in db.query(saas.models.SubscriptionPlanPrice).all():
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

    def _signup_verify_and_login(self, sent_messages: list[dict], email: str):
        def fake_send_email(**kwargs):
            sent_messages.append(kwargs)
            return f"email_{len(sent_messages)}"

        with patch("email_service.send_email", side_effect=fake_send_email):
            signup_response = self.client.post(
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
            self.assertEqual(signup_response.status_code, 302)
            token_match = re.search(r"token=([A-Za-z0-9._\\-]+)", sent_messages[0]["text"])
            self.assertIsNotNone(token_match)
            verify_response = self.client.get(
                f"/saas/auth/verify-email?token={token_match.group(1)}",
                follow_redirects=False,
            )
            self.assertEqual(verify_response.status_code, 302)
            self.assertIn("/saas/login?notice=", verify_response.headers["location"])

        login_response = self.client.post(
            "/saas/auth/login",
            data={"email": email, "password": "strong-password-123", "next_path": "/saas/account"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers["location"], "/saas/account")

    def _complete_pending_org(self, email: str, sent_messages: list[dict]) -> str:
        self._signup_verify_and_login(sent_messages, email)

        start_response = self.client.post("/saas/onboarding/start", follow_redirects=False)
        self.assertEqual(start_response.status_code, 302)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).order_by(
                saas.models.PendingOrganization.id.desc()
            ).first()
            org_uuid = organization.organization_uuid
        finally:
            db.close()

        self.client.post(
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
        self.client.post(
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
        self.client.post(
            f"/saas/onboarding/{org_uuid}/academic_setup",
            data={
                "first_academic_year_name": "2026-2027",
                "create_default_branch": "1",
                "notes": "Launch year",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.client.post(
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
        submit_response = self.client.post(
            f"/saas/onboarding/{org_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        return org_uuid

    def _prepare_checkout(self, org_uuid: str):
        db = self._db()
        try:
            professional = db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code="professional"
            ).first()
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
                return_value={
                    "id": "ctm_phase5_123",
                    "email": "owner@academy.edu",
                    "name": "Owner User",
                    "status": "active",
                },
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_phase5_123",
                    "status": "ready",
                    "currency_code": "USD",
                    "checkout": {
                        "id": "chk_phase5_123",
                        "url": "https://pay.paddle.test/checkout/phase5",
                    },
                },
            ),
        ):
            launch_response = self.client.post(
                f"/saas/onboarding/{org_uuid}/checkout/launch",
                follow_redirects=False,
            )
        self.assertEqual(launch_response.status_code, 302)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=org_uuid
            ).first()
            attempt = db.query(saas.models.PaymentAttempt).filter_by(
                pending_organization_id=organization.id
            ).first()
            contract = db.query(saas.models.SubscriptionContract).filter_by(
                pending_organization_id=organization.id
            ).first()
            return organization.id, attempt.attempt_uuid, contract.id
        finally:
            db.close()

    def _complete_payment(self, org_uuid: str, attempt_uuid: str, contract_id: int):
        paid_payload = {
            "event_id": "evt_phase5_paid_12345678901234567890",
            "event_type": "transaction.paid",
            "data": {
                "id": "txn_phase5_123",
                "status": "paid",
                "customer_id": "ctm_phase5_123",
                "custom_data": {
                    "pending_organization_uuid": org_uuid,
                    "payment_attempt_uuid": attempt_uuid,
                    "subscription_contract_id": contract_id,
                },
            },
        }
        paid_signature, paid_body = self._sign_paddle_payload(paid_payload)
        self.client.post(
            "/saas/webhooks/paddle",
            content=paid_body,
            headers={"Paddle-Signature": paid_signature, "Content-Type": "application/json"},
        )

        completed_payload = {
            "event_id": "evt_phase5_completed_12345678901234567",
            "event_type": "transaction.completed",
            "data": {
                "id": "txn_phase5_123",
                "status": "completed",
                "customer_id": "ctm_phase5_123",
                "subscription_id": "sub_phase5_123",
                "custom_data": {
                    "pending_organization_uuid": org_uuid,
                    "payment_attempt_uuid": attempt_uuid,
                    "subscription_contract_id": contract_id,
                },
            },
        }
        completed_signature, completed_body = self._sign_paddle_payload(completed_payload)
        return self.client.post(
            "/saas/webhooks/paddle",
            content=completed_body,
            headers={"Paddle-Signature": completed_signature, "Content-Type": "application/json"},
        )

    def test_successful_provisioning_creates_operational_tenant_and_activation_email(self):
        self._configure_paddle_prices()
        sent_messages = []
        org_uuid = self._complete_pending_org("owner@academy.edu", sent_messages)
        organization_id, attempt_uuid, contract_id = self._prepare_checkout(org_uuid)

        with patch(
            "email_service.send_email",
            side_effect=lambda **kwargs: sent_messages.append(kwargs) or f"email_{len(sent_messages)}",
        ):
            completed_response = self._complete_payment(org_uuid, attempt_uuid, contract_id)
        self.assertEqual(completed_response.status_code, 200)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).first()
            contract = db.query(saas.models.SubscriptionContract).filter_by(id=contract_id).first()
            tenant_link = db.query(saas.models.TenantProvisioningLink).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertIsNotNone(tenant_link)
            school_group = db.query(models.SchoolGroup).filter_by(id=tenant_link.school_group_id).first()
            tenant_profile = db.query(models.TenantProfile).filter_by(
                school_group_id=school_group.id
            ).first()
            owner_link = db.query(saas.models.SaaSAccountUserLink).filter_by(
                school_group_id=school_group.id
            ).first()
            owner_user = db.query(models.User).filter_by(id=owner_link.operational_user_id).first()
            job = db.query(saas.models.ProvisioningJob).filter_by(
                pending_organization_id=organization.id
            ).first()
            seeded_permissions = db.query(models.RolePermission).filter(
                models.RolePermission.school_group_id == school_group.id
            ).count()
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized="owner@academy.edu"
            ).first()

            self.assertEqual(organization.billing_status, "tenant_active")
            self.assertEqual(contract.contract_status, "tenant_active")
            self.assertEqual(contract.school_group_id, school_group.id)
            self.assertEqual(job.job_status, "completed")
            self.assertGreaterEqual(seeded_permissions, len(permission_registry.MANAGED_ROLES))
            self.assertEqual(db.query(models.Branch).filter_by(school_group_id=school_group.id).count(), 2)
            self.assertEqual(db.query(models.AcademicYear).filter_by(school_group_id=school_group.id).count(), 1)
            self.assertEqual(owner_user.email, "owner@academy.edu")
            self.assertEqual(owner_user.password, account.password_hash)
            self.assertEqual(owner_user.role, auth.ROLE_ADMINISTRATOR)
            self.assertEqual(owner_user.access_scope, auth.ACCESS_SCOPE_ORGANIZATION)
            self.assertEqual(tenant_profile.website, "https://andalus.example.com")
            self.assertEqual(tenant_profile.timezone, "Asia/Riyadh")
            self.assertEqual(tenant_profile.educational_program, "BOTH")
            self.assertEqual(tenant_profile.school_type, "K-12")
            self.assertEqual(tenant_profile.estimated_staff_users, 35)
            self.assertIsNotNone(auth.authenticate_user(db, "owner@academy.edu", "strong-password-123"))
        finally:
            db.close()

        self.assertGreaterEqual(len(sent_messages), 2)
        activation_email = sent_messages[-1]
        self.assertIn("is now active", activation_email["subject"])
        self.assertIn("http://testserver/login", activation_email["text"])

    def test_provisioning_retry_logic_recovers_after_transient_failure(self):
        self._configure_paddle_prices()
        sent_messages = []
        org_uuid = self._complete_pending_org("retry@academy.edu", sent_messages)
        organization_id, attempt_uuid, contract_id = self._prepare_checkout(org_uuid)

        original_create_school_group = provisioning_service._create_school_group
        call_counter = {"count": 0}

        def flaky_create_school_group(db, organization):
            call_counter["count"] += 1
            if call_counter["count"] == 1:
                raise RuntimeError("temporary provisioning failure")
            return original_create_school_group(db, organization)

        with (
            patch("saas.provisioning_service._create_school_group", side_effect=flaky_create_school_group),
            patch("email_service.send_email", side_effect=lambda **kwargs: sent_messages.append(kwargs) or f"email_{len(sent_messages)}"),
        ):
            completed_response = self._complete_payment(org_uuid, attempt_uuid, contract_id)
        self.assertEqual(completed_response.status_code, 200)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).first()
            contract = db.query(saas.models.SubscriptionContract).filter_by(id=contract_id).first()
            job = db.query(saas.models.ProvisioningJob).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertEqual(organization.billing_status, "provisioning_retrying")
            self.assertEqual(contract.contract_status, "provisioning_retrying")
            self.assertEqual(job.job_status, "retrying")
            job.next_attempt_at = provisioning_service._utcnow()  # noqa: SLF001 - test-only fast-forward
            db.commit()

            provisioning_service.process_pending_jobs(db, limit=5)
            db.commit()

            db.refresh(organization)
            db.refresh(contract)
            db.refresh(job)
            self.assertEqual(organization.billing_status, "tenant_active")
            self.assertEqual(contract.contract_status, "tenant_active")
            self.assertEqual(job.job_status, "completed")
            self.assertEqual(job.attempt_count, 2)
        finally:
            db.close()

    def test_duplicate_protection_and_platform_owner_provisioning_dashboard(self):
        self._configure_paddle_prices()
        sent_messages = []
        org_uuid = self._complete_pending_org("dup@academy.edu", sent_messages)
        organization_id, attempt_uuid, contract_id = self._prepare_checkout(org_uuid)
        with patch(
            "email_service.send_email",
            side_effect=lambda **kwargs: sent_messages.append(kwargs) or f"email_{len(sent_messages)}",
        ):
            completed_response = self._complete_payment(org_uuid, attempt_uuid, contract_id)
        self.assertEqual(completed_response.status_code, 200)

        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).first()
            contract = db.query(saas.models.SubscriptionContract).filter_by(id=contract_id).first()
            counts_before = {
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "academic_years": db.query(models.AcademicYear).count(),
                "users": db.query(models.User).filter(models.User.user_type == auth.USER_TYPE_TENANT).count(),
            }
            self.assertIsNone(
                provisioning_service.enqueue_ready_for_provisioning(db, organization, contract)
            )
            provisioning_service.process_pending_jobs(db, limit=5)
            db.commit()
            counts_after = {
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "academic_years": db.query(models.AcademicYear).count(),
                "users": db.query(models.User).filter(models.User.user_type == auth.USER_TYPE_TENANT).count(),
            }
            self.assertEqual(counts_before, counts_after)

            platform_owner = models.User(
                user_id="9005",
                username="platform.provisioning",
                email="platform.provisioning@example.com",
                email_normalized=auth.normalize_email("platform.provisioning@example.com"),
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
            platform_cookie = auth.create_session_token(platform_owner)
        finally:
            db.close()

        admin_client = TestClient(self.app)
        admin_client.cookies.set(auth.SESSION_COOKIE_KEY, platform_cookie)
        provisioning_dashboard = admin_client.get("/saas-admin/provisioning")
        self.assertEqual(provisioning_dashboard.status_code, 200)
        self.assertIn("Provisioning Queue", provisioning_dashboard.text)
        self.assertIn("completed", provisioning_dashboard.text)
        self.assertIn("Andalus Academy", provisioning_dashboard.text)


if __name__ == "__main__":
    unittest.main()
