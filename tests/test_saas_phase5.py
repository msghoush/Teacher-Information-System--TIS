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
from saas import provisioning_service, service as saas_service, workspace_deletion_service
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

    def _complete_pending_org(
        self,
        email: str,
        sent_messages: list[dict],
        *,
        organization_name: str = "Andalus Academy",
        legal_name: str = "Andalus Academy LLC",
        branch_names: list[str] | None = None,
    ) -> str:
        self._signup_verify_and_login(sent_messages, email)
        branch_names = branch_names or ["Main Campus", "Girls Campus"]

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
                "organization_name": organization_name,
                "legal_name": legal_name,
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
                "branch_name": branch_names,
                "location": ["Central" for _branch_name in branch_names],
                "country_code": ["SA" for _branch_name in branch_names],
                "country_name": ["Saudi Arabia" for _branch_name in branch_names],
                "region_name": ["Makkah" for _branch_name in branch_names],
                "city_name": ["Jeddah" for _branch_name in branch_names],
                "district_name": ["Al Zahra" for _branch_name in branch_names],
                "neighborhood_name": ["North" for _branch_name in branch_names],
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
        paddle_suffix = re.sub(r"[^A-Za-z0-9]", "", org_uuid)[:20]
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
            patch("saas.paddle_client.list_customers_by_email", return_value=[]),
            patch(
                "saas.paddle_client.create_customer",
                return_value={
                    "id": f"ctm_phase5_{paddle_suffix}",
                    "email": "owner@academy.edu",
                    "name": "Owner User",
                    "status": "active",
                },
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": f"txn_phase5_{paddle_suffix}",
                    "status": "ready",
                    "currency_code": "USD",
                    "checkout": {
                        "id": f"chk_phase5_{paddle_suffix}",
                        "url": f"https://pay.paddle.test/checkout/phase5/{paddle_suffix}",
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
        paddle_suffix = re.sub(r"[^A-Za-z0-9]", "", org_uuid)[:20]
        event_suffix = re.sub(r"[^A-Za-z0-9]", "", attempt_uuid)[:20]
        db = self._db()
        try:
            attempt = db.query(saas.models.PaymentAttempt).filter_by(attempt_uuid=attempt_uuid).first()
            provider_price_id = attempt.provider_price_id
            quantity = attempt.quantity
            unit_amount_minor = attempt.unit_amount_minor
            amount_minor = attempt.amount_minor
            paddle_interval = "year" if attempt.billing_interval == "annual" else "month"
            currency_code = attempt.currency_code
        finally:
            db.close()
        paid_payload = {
            "event_id": f"evt_phase5_paid_{event_suffix}",
            "event_type": "transaction.paid",
            "data": {
                "id": f"txn_phase5_{paddle_suffix}",
                "status": "paid",
                "customer_id": f"ctm_phase5_{paddle_suffix}",
                "custom_data": {
                    "pending_organization_uuid": org_uuid,
                    "payment_attempt_uuid": attempt_uuid,
                    "subscription_contract_id": contract_id,
                },
                "items": [{
                    "quantity": quantity,
                    "price": {
                        "id": provider_price_id,
                        "unit_price": {"amount": str(unit_amount_minor), "currency_code": currency_code},
                        "billing_cycle": {"interval": paddle_interval, "frequency": 1},
                    },
                }],
                "details": {
                    "totals": {"subtotal": str(amount_minor), "currency_code": currency_code},
                    "line_items": [{
                        "price_id": provider_price_id,
                        "quantity": quantity,
                        "totals": {"subtotal": str(amount_minor)},
                    }],
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
            "event_id": f"evt_phase5_completed_{event_suffix}",
            "event_type": "transaction.completed",
            "data": {
                "id": f"txn_phase5_{paddle_suffix}",
                "status": "completed",
                "customer_id": f"ctm_phase5_{paddle_suffix}",
                "subscription_id": f"sub_phase5_{paddle_suffix}",
                "custom_data": {
                    "pending_organization_uuid": org_uuid,
                    "payment_attempt_uuid": attempt_uuid,
                    "subscription_contract_id": contract_id,
                },
                "items": [{
                    "quantity": quantity,
                    "price": {
                        "id": provider_price_id,
                        "unit_price": {"amount": str(unit_amount_minor), "currency_code": currency_code},
                        "billing_cycle": {"interval": paddle_interval, "frequency": 1},
                    },
                }],
                "details": {
                    "totals": {"subtotal": str(amount_minor), "currency_code": currency_code},
                    "line_items": [{
                        "price_id": provider_price_id,
                        "quantity": quantity,
                        "totals": {"subtotal": str(amount_minor)},
                    }],
                },
            },
        }
        completed_signature, completed_body = self._sign_paddle_payload(completed_payload)
        return self.client.post(
            "/saas/webhooks/paddle",
            content=completed_body,
            headers={"Paddle-Signature": completed_signature, "Content-Type": "application/json"},
        )

    def _complete_paid_provisioning(
        self,
        *,
        email: str,
        organization_name: str,
        legal_name: str = "",
        branch_names: list[str] | None = None,
    ):
        self._configure_paddle_prices()
        sent_messages = []
        org_uuid = self._complete_pending_org(
            email,
            sent_messages,
            organization_name=organization_name,
            legal_name=legal_name,
            branch_names=branch_names,
        )
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
            tenant_link = db.query(saas.models.TenantProvisioningLink).filter_by(
                pending_organization_id=organization.id
            ).first()
            self.assertIsNotNone(tenant_link)
            school_group = db.query(models.SchoolGroup).filter_by(id=tenant_link.school_group_id).first()
            self.assertIsNotNone(school_group)
            return {
                "organization_id": organization_id,
                "school_group_id": school_group.id,
                "school_group_name": school_group.name,
                "sent_messages": sent_messages,
            }
        finally:
            db.close()

    def _platform_client(self, *, user_id: str = "9005", platform_role: str = auth.PLATFORM_ROLE_OWNER):
        db = self._db()
        try:
            platform_user = models.User(
                user_id=user_id,
                username=f"platform.{user_id}",
                email=f"platform.{user_id}@example.com",
                email_normalized=auth.normalize_email(f"platform.{user_id}@example.com"),
                first_name="Platform",
                last_name="User",
                password=auth.get_password_hash("PlatformPass123!"),
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=platform_role,
                platform_owner_kind=auth.PLATFORM_OWNER_PRIMARY if platform_role == auth.PLATFORM_ROLE_OWNER else None,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(platform_user)
            db.commit()
            token = auth.create_session_token(platform_user)
        finally:
            db.close()
        client = TestClient(self.app)
        client.cookies.set(auth.SESSION_COOKIE_KEY, token)
        return client

    def _create_orphaned_test_account(self, *, email: str, organization_name: str):
        result = self._complete_paid_provisioning(
            email=email,
            organization_name=organization_name,
        )
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first()
            account_id = organization.owner_saas_account_id
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).first()
            workspace_deletion_service.delete_test_workspace(
                db,
                organization,
                confirmation_name=organization_name,
                reason="Create orphaned account test fixture",
            )
            db.commit()
            return {
                **result,
                "account_id": account_id,
                "account_uuid": account.account_uuid,
                "email": account.email,
            }
        finally:
            db.close()

    def _create_standalone_platform_email_account(
        self,
        *,
        user_id: str,
        platform_role: str,
    ):
        email = f"standalone.platform.{user_id}@example.com"
        platform_password = "PlatformStandalone123!"
        db = self._db()
        try:
            platform_user = models.User(
                user_id=user_id,
                username=f"standalone.platform.{user_id}",
                email=email,
                email_normalized=auth.normalize_email(email),
                first_name="Standalone",
                last_name="Platform",
                password=auth.get_password_hash(platform_password),
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=platform_role,
                platform_owner_kind=(
                    auth.PLATFORM_OWNER_CO_OWNER
                    if platform_role == auth.PLATFORM_ROLE_OWNER else None
                ),
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(platform_user)
            db.flush()
            account, _policy = saas_service.create_account(
                db,
                email=email,
                password="SaaSStandalone123!",
                first_name="Standalone",
                last_name="Customer",
            )
            db.commit()
            return {
                "account_id": account.id,
                "account_uuid": account.account_uuid,
                "email": email,
                "platform_user_id": platform_user.id,
                "platform_password": platform_password,
                "saas_password": "SaaSStandalone123!",
            }
        finally:
            db.close()

    def _tenant_client(self, *, user_id: str = "7100000010"):
        db = self._db()
        try:
            group = models.SchoolGroup(name=f"Tenant Guard {user_id}", status=True)
            db.add(group)
            db.flush()
            branch = models.Branch(school_group_id=group.id, name="Tenant Branch", status=True)
            db.add(branch)
            db.flush()
            tenant_user = models.User(
                user_id=user_id,
                username=user_id,
                email=f"tenant.{user_id}@example.com",
                email_normalized=auth.normalize_email(f"tenant.{user_id}@example.com"),
                first_name="Tenant",
                last_name="Admin",
                password=auth.get_password_hash("TenantPass123!"),
                user_type=auth.USER_TYPE_TENANT,
                role=auth.ROLE_ADMINISTRATOR,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
                school_group_id=group.id,
                branch_id=branch.id,
                is_active=True,
            )
            db.add(tenant_user)
            db.commit()
            token = auth.create_session_token(tenant_user)
        finally:
            db.close()
        client = TestClient(self.app)
        client.cookies.set(auth.SESSION_COOKIE_KEY, token)
        return client

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
        self.assertIn("Your School Workspace is active", activation_email["html"])
        self.assertIn("Workspace Activation is complete", activation_email["text"])
        self.assertIn("TIS Account", activation_email["text"])
        self.assertIn("TIS%20Wordmark%20Only%20%E2%80%93%20Dark%20Blue.png", activation_email["html"])
        self.assertNotIn("SaaS account", activation_email["text"])
        self.assertIn("http://testserver/login", activation_email["text"])
        self.assertIn("http://testserver/static/branding/tis/logos/", activation_email["html"])
        self.assertNotIn("PADDLE_API_KEY", activation_email["html"])
        self.assertNotIn(os.environ["PADDLE_API_KEY"], activation_email["html"])
        self.assertNotIn("DATABASE_URL", activation_email["html"])

    def test_provisioning_school_group_uses_organization_name_not_legal_name(self):
        result = self._complete_paid_provisioning(
            email="society-owner@academy.edu",
            organization_name="Society for Social Support and Education",
            legal_name="Testing 2",
            branch_names=["Testing 2 Branch"],
        )

        self.assertEqual(result["school_group_name"], "Society for Social Support and Education")
        self.assertNotEqual(result["school_group_name"], "Testing 2")
        activation_email = result["sent_messages"][-1]
        self.assertIn("Society for Social Support and Education", activation_email["text"])
        self.assertNotIn("Testing 2", activation_email["text"])

    def test_provisioning_school_group_uses_organization_name_when_legal_name_is_blank(self):
        result = self._complete_paid_provisioning(
            email="blank-legal@academy.edu",
            organization_name="No Legal Name Academy",
            legal_name="",
        )

        self.assertEqual(result["school_group_name"], "No Legal Name Academy")

    def test_provisioning_duplicate_organization_names_keep_suffix_behavior(self):
        first = self._complete_paid_provisioning(
            email="duplicate-one@academy.edu",
            organization_name="Duplicate Academy",
            legal_name="First Legal Entity",
        )
        second = self._complete_paid_provisioning(
            email="duplicate-two@academy.edu",
            organization_name="Duplicate Academy",
            legal_name="Second Legal Entity",
        )

        self.assertEqual(first["school_group_name"], "Duplicate Academy")
        self.assertEqual(second["school_group_name"], "Duplicate Academy (2)")

    def test_provisioning_branch_name_cannot_become_school_group_name(self):
        result = self._complete_paid_provisioning(
            email="branch-name@academy.edu",
            organization_name="Approved Workspace Academy",
            legal_name="Branch Legal Entity",
            branch_names=["Branch Name Should Not Win"],
        )

        self.assertEqual(result["school_group_name"], "Approved Workspace Academy")
        self.assertNotEqual(result["school_group_name"], "Branch Name Should Not Win")

    def test_platform_owner_can_analyze_provisioned_test_workspace_read_only(self):
        result = self._complete_paid_provisioning(
            email="analysis-owner@academy.edu",
            organization_name="Analysis Academy",
            legal_name="Analysis Legal Entity",
        )
        platform_client = self._platform_client()
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first()
            organization_uuid = organization.organization_uuid
            counts_before = {
                "pending": db.query(saas.models.PendingOrganization).count(),
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "users": db.query(models.User).count(),
                "events": db.query(saas.models.PendingOrganizationEvent).count(),
            }
        finally:
            db.close()

        with (
            patch("saas.paddle_client.create_transaction") as create_transaction,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
        ):
            response = platform_client.get(
                f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Analyze Test Workspace", response.text)
        self.assertIn("Analysis Academy", response.text)
        self.assertIn(str(result["school_group_id"]), response.text)
        self.assertIn("Safe to prepare for deletion", response.text)
        self.assertIn("No data was changed", response.text)
        self.assertIn("<td>pending_organization_branches</td>", response.text)
        self.assertIn("<td>payment_webhooks</td>", response.text)
        self.assertIn("<td>branches</td>", response.text)
        self.assertIn("<td>2</td>", response.text)
        self.assertNotIn(os.environ["PADDLE_API_KEY"], response.text)
        self.assertNotIn("PADDLE_API_KEY", response.text)
        self.assertNotIn("DATABASE_URL", response.text)
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn("payload_json", response.text)
        create_transaction.assert_not_called()
        create_customer.assert_not_called()
        list_customers.assert_not_called()

        db = self._db()
        try:
            counts_after = {
                "pending": db.query(saas.models.PendingOrganization).count(),
                "school_groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "users": db.query(models.User).count(),
                "events": db.query(saas.models.PendingOrganizationEvent).count(),
            }
        finally:
            db.close()
        self.assertEqual(counts_before, counts_after)

    def test_platform_developer_can_access_workspace_analysis(self):
        result = self._complete_paid_provisioning(
            email="analysis-developer@academy.edu",
            organization_name="Developer Analysis Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()

        response = self._platform_client(
            user_id="9006",
            platform_role=auth.PLATFORM_ROLE_DEVELOPER,
        ).get(f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Developer Analysis Academy", response.text)

    def test_platform_developer_detail_page_shows_analysis_without_mutating_controls(self):
        result = self._complete_paid_provisioning(
            email="analysis-developer-detail@academy.edu",
            organization_name="Developer Detail Analysis Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()

        response = self._platform_client(
            user_id="9007",
            platform_role=auth.PLATFORM_ROLE_DEVELOPER,
        ).get(f"/saas-admin/pending-organizations/{organization_uuid}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Analyze Test Workspace", response.text)
        self.assertNotIn("Update status", response.text)
        self.assertNotIn("Add internal note", response.text)
        self.assertNotIn("Reset Test Workspace", response.text)
        self.assertNotIn("Delete Pending Application", response.text)

    def test_customer_and_tenant_users_cannot_access_workspace_analysis(self):
        result = self._complete_paid_provisioning(
            email="analysis-deny@academy.edu",
            organization_name="Denied Analysis Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized=auth.normalize_email("analysis-deny@academy.edu")
            ).first()
            session_token, _csrf_token, _session = saas_service.create_session(db, account)
            db.commit()
        finally:
            db.close()

        customer_client = TestClient(self.app)
        customer_client.cookies.set(saas_service.SAAS_SESSION_COOKIE, session_token)
        customer_response = customer_client.get(
            f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace"
        )
        tenant_response = self._tenant_client().get(
            f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace"
        )

        self.assertEqual(customer_response.status_code, 403)
        self.assertEqual(tenant_response.status_code, 403)

    def test_workspace_analysis_excludes_unrelated_tenant_records(self):
        result = self._complete_paid_provisioning(
            email="analysis-scope@academy.edu",
            organization_name="Scoped Analysis Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
            unrelated_group = models.SchoolGroup(name="Unrelated Workspace", status=True)
            db.add(unrelated_group)
            db.flush()
            db.add(models.Branch(school_group_id=unrelated_group.id, name="Unrelated Branch", status=True))
            db.add(models.AcademicYear(school_group_id=unrelated_group.id, year_name="2099-2100", is_active=True))
            db.commit()
        finally:
            db.close()

        response = self._platform_client().get(
            f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Scoped Analysis Academy", response.text)
        self.assertNotIn("Unrelated Workspace", response.text)
        self.assertNotIn("Unrelated Branch", response.text)
        self.assertIn("<td>branches</td>", response.text)
        self.assertIn("<td>2</td>", response.text)

    def test_workspace_analysis_handles_unprovisioned_pending_organization_conservatively(self):
        sent_messages = []
        org_uuid = self._complete_pending_org(
            "analysis-unprovisioned@academy.edu",
            sent_messages,
            organization_name="Unprovisioned Analysis Academy",
        )

        response = self._platform_client().get(
            f"/saas-admin/pending-organizations/{org_uuid}/analyze-test-workspace"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Unprovisioned Analysis Academy", response.text)
        self.assertIn("Manual review required", response.text)
        self.assertIn("No tenant provisioning link exists", response.text)
        self.assertIn("Not linked", response.text)

    def test_pending_organization_detail_exposes_read_only_analysis_action_to_owner(self):
        result = self._complete_paid_provisioning(
            email="analysis-link@academy.edu",
            organization_name="Analysis Link Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()

        response = self._platform_client().get(f"/saas-admin/pending-organizations/{organization_uuid}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Analyze Test Workspace", response.text)
        self.assertIn("Reset Test Workspace", response.text)
        self.assertNotIn("Delete Pending Application", response.text)
        self.assertIn(f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace", response.text)

    def test_pending_organizations_dashboard_keeps_owner_actions_reachable(self):
        result = self._complete_paid_provisioning(
            email="analysis-table@academy.edu",
            organization_name="Analysis Table Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()

        response = self._platform_client().get("/saas-admin/pending-organizations")
        tenant_response = self._tenant_client().get("/saas-admin/pending-organizations")

        self.assertEqual(response.status_code, 200)
        self.assertIn("pending-org-table-wrap", response.text)
        self.assertIn("overflow-x: auto", response.text)
        self.assertIn("position: sticky", response.text)
        self.assertIn("right: 0", response.text)
        self.assertIn("Analysis Table Academy", response.text)
        self.assertIn("View Details", response.text)
        self.assertIn("Analyze Workspace", response.text)
        self.assertNotIn(
            f'/saas-admin/pending-organizations/{organization_uuid}/delete"',
            response.text,
        )
        self.assertNotIn(">Delete</button>", response.text)
        self.assertIn(f"/saas-admin/pending-organizations/{organization_uuid}", response.text)
        self.assertIn(
            f"/saas-admin/pending-organizations/{organization_uuid}/analyze-test-workspace",
            response.text,
        )
        self.assertEqual(tenant_response.status_code, 403)
        self.assertNotIn("Analyze Workspace", tenant_response.text)

    def test_delete_test_workspace_confirmation_is_owner_only(self):
        result = self._complete_paid_provisioning(
            email="delete-access@academy.edu",
            organization_name="Delete Access Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace"

        owner_response = self._platform_client(user_id="9010").get(path)
        developer_response = self._platform_client(
            user_id="9011", platform_role=auth.PLATFORM_ROLE_DEVELOPER
        ).get(path)
        tenant_response = self._tenant_client(user_id="7100000011").get(path)

        self.assertEqual(owner_response.status_code, 200)
        self.assertIn("Reset Test Workspace", owner_response.text)
        self.assertIn("Delete Access Academy", owner_response.text)
        self.assertIn("Irreversible development/testing reset", owner_response.text)
        self.assertIn("Remote Paddle records remain untouched", owner_response.text)
        self.assertIn("cannot be undone", owner_response.text)
        self.assertNotIn(os.environ["PADDLE_API_KEY"], owner_response.text)
        self.assertEqual(developer_response.status_code, 403)
        self.assertEqual(tenant_response.status_code, 403)

    def test_delete_test_workspace_requires_exact_name_and_reason(self):
        result = self._complete_paid_provisioning(
            email="delete-confirm@academy.edu",
            organization_name="Exact Confirmation Academy",
        )
        owner_client = self._platform_client(user_id="9012")
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace"

        with patch("saas.router.audit.write_audit_event") as write_audit:
            mismatch = owner_client.post(
                path,
                data={"confirmation_name": "exact confirmation academy", "reason": "Reset test"},
                follow_redirects=False,
            )
            missing_reason = owner_client.post(
                path,
                data={"confirmation_name": "Exact Confirmation Academy", "reason": ""},
                follow_redirects=False,
            )

        self.assertEqual(mismatch.status_code, 302)
        self.assertIn("typed+organization+name+does+not+match", mismatch.headers["location"])
        self.assertIn("deletion+reason+is+required", missing_reason.headers["location"])
        self.assertEqual(write_audit.call_count, 2)
        self.assertTrue(all(call.args[0]["result"] == "blocked" for call in write_audit.call_args_list))
        db = self._db()
        try:
            self.assertIsNotNone(db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first())
            self.assertIsNotNone(db.query(models.SchoolGroup).filter_by(id=result["school_group_id"]).first())
        finally:
            db.close()

    def test_delete_test_workspace_blocks_manual_review(self):
        sent_messages = []
        organization_uuid = self._complete_pending_org(
            "delete-unprovisioned@academy.edu",
            sent_messages,
            organization_name="Unprovisioned Delete Academy",
        )
        owner_client = self._platform_client(user_id="9013")
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace"

        page = owner_client.get(path)
        response = owner_client.post(
            path,
            data={"confirmation_name": "Unprovisioned Delete Academy", "reason": "Reset test"},
            follow_redirects=False,
        )

        self.assertIn("Manual review required", page.text)
        self.assertNotIn("Permanently Reset Test Workspace</button>", page.text)
        self.assertEqual(response.status_code, 302)
        self.assertIn("requires+manual+review", response.headers["location"])

    def test_unprovisioned_eligible_detail_shows_only_pending_application_delete(self):
        sent_messages = []
        organization_uuid = self._complete_pending_org(
            "pending-delete-ux@academy.edu",
            sent_messages,
            organization_name="Pending Delete UX Academy",
        )

        response = self._platform_client(user_id="9016").get(
            f"/saas-admin/pending-organizations/{organization_uuid}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Delete unprovisioned pending application", response.text)
        self.assertIn("Delete Pending Application", response.text)
        self.assertNotIn("Reset Test Workspace", response.text)
        self.assertIn("Analyze Test Workspace", response.text)

    def test_delete_test_workspace_removes_only_scoped_local_data_and_preserves_globals(self):
        result = self._complete_paid_provisioning(
            email="delete-success@academy.edu",
            organization_name="Disposable Test Academy",
        )
        owner_client = self._platform_client(user_id="9014")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first()
            organization_uuid = organization.organization_uuid
            preserved_account_id = organization.owner_saas_account_id
            unrelated_group = models.SchoolGroup(name="Preserved Unrelated Academy", status=True)
            db.add(unrelated_group)
            db.flush()
            db.add(models.Branch(school_group_id=unrelated_group.id, name="Preserved Branch", status=True))
            webhook = saas.models.PaymentWebhook(
                provider="paddle",
                provider_event_id="evt_preserved_delete_test",
                event_type="transaction.completed",
                signature_valid=True,
                payload_json="{}",
            )
            db.add(webhook)
            db.commit()
            unrelated_group_id = unrelated_group.id
            plan_count = db.query(saas.models.SubscriptionPlan).count()
            price_count = db.query(saas.models.SubscriptionPlanPrice).count()
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace"

        with (
            patch("saas.router.audit.write_audit_event") as write_audit,
            patch("saas.paddle_client.create_transaction") as create_transaction,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
        ):
            response = owner_client.post(
                path,
                data={"confirmation_name": "Disposable Test Academy", "reason": "Repeat full sandbox journey"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("Test+workspace+permanently+deleted", response.headers["location"])
        create_transaction.assert_not_called()
        create_customer.assert_not_called()
        list_customers.assert_not_called()
        self.assertEqual(write_audit.call_args.args[0]["result"], "success")
        self.assertEqual(write_audit.call_args.args[0]["school_group_id"], result["school_group_id"])
        db = self._db()
        try:
            self.assertIsNone(db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first())
            self.assertIsNone(db.query(models.SchoolGroup).filter_by(id=result["school_group_id"]).first())
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=preserved_account_id).first())
            self.assertEqual(db.query(models.Branch).filter_by(school_group_id=result["school_group_id"]).count(), 0)
            self.assertEqual(db.query(models.User).filter_by(school_group_id=result["school_group_id"]).count(), 0)
            self.assertIsNotNone(db.query(models.SchoolGroup).filter_by(id=unrelated_group_id).first())
            self.assertEqual(db.query(saas.models.SubscriptionPlan).count(), plan_count)
            self.assertEqual(db.query(saas.models.SubscriptionPlanPrice).count(), price_count)
            self.assertIsNotNone(db.query(saas.models.PaymentWebhook).filter_by(provider_event_id="evt_preserved_delete_test").first())
            self.assertIsNotNone(db.query(models.User).filter_by(user_id="9014").first())
        finally:
            db.close()

        repeated = owner_client.post(
            path,
            data={"confirmation_name": "Disposable Test Academy", "reason": "Repeat"},
        )
        self.assertEqual(repeated.status_code, 404)

    def test_delete_test_workspace_rolls_back_every_row_on_failure(self):
        result = self._complete_paid_provisioning(
            email="delete-rollback@academy.edu",
            organization_name="Rollback Test Academy",
        )
        owner_client = self._platform_client(user_id="9015")
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first().organization_uuid
            before = {
                "pending": db.query(saas.models.PendingOrganization).count(),
                "groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "users": db.query(models.User).count(),
            }
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace"

        with (
            patch("saas.workspace_deletion_service.Session.flush", side_effect=RuntimeError("simulated late failure")),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            response = owner_client.post(
                path,
                data={"confirmation_name": "Rollback Test Academy", "reason": "Rollback test"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("All+data+was+preserved", response.headers["location"])
        self.assertEqual(write_audit.call_args.args[0]["result"], "failed_rolled_back")
        db = self._db()
        try:
            after = {
                "pending": db.query(saas.models.PendingOrganization).count(),
                "groups": db.query(models.SchoolGroup).count(),
                "branches": db.query(models.Branch).count(),
                "users": db.query(models.User).count(),
            }
        finally:
            db.close()
        self.assertEqual(before, after)

    def test_delete_test_account_is_owner_only_and_environment_guarded(self):
        result = self._complete_paid_provisioning(
            email="full-reset-access@academy.edu",
            organization_name="Full Reset Access Academy",
        )
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account"
        owner_client = self._platform_client(user_id="9020")

        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "TIS_ENABLE_TEST_ACCOUNT_RESET": ""}):
            unavailable = owner_client.get(path)
            detail = owner_client.get(f"/saas-admin/pending-organizations/{organization_uuid}")
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "TIS_ENABLE_TEST_ACCOUNT_RESET": "true"}):
            feature_flag_available = owner_client.get(path)
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "TIS_ENABLE_TEST_ACCOUNT_RESET": ""}):
            available = owner_client.get(path)
            developer = self._platform_client(
                user_id="9021", platform_role=auth.PLATFORM_ROLE_DEVELOPER
            ).get(path)
            tenant = self._tenant_client(user_id="7100000020").get(path)

        self.assertEqual(unavailable.status_code, 404)
        self.assertNotIn("Delete Test Account and Workspace", detail.text)
        self.assertEqual(feature_flag_available.status_code, 200)
        self.assertEqual(available.status_code, 200)
        self.assertIn("Delete Test Account and Workspace", available.text)
        self.assertIn("full-reset-access@academy.edu", available.text)
        self.assertNotIn(os.environ["PADDLE_API_KEY"], available.text)
        self.assertEqual(developer.status_code, 403)
        self.assertEqual(tenant.status_code, 403)

    def test_delete_test_account_confirmation_fields_and_reason_are_required(self):
        result = self._complete_paid_provisioning(
            email="full-reset-confirm@academy.edu",
            organization_name="Full Reset Confirmation Academy",
        )
        owner_client = self._platform_client(user_id="9022")
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account"

        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            name_mismatch = owner_client.post(path, data={
                "confirmation_name": "Wrong Name",
                "confirmation_email": "full-reset-confirm@academy.edu",
                "reason": "Retest",
            }, follow_redirects=False)
            email_mismatch = owner_client.post(path, data={
                "confirmation_name": "Full Reset Confirmation Academy",
                "confirmation_email": "FULL-RESET-CONFIRM@academy.edu",
                "reason": "Retest",
            }, follow_redirects=False)
            missing_reason = owner_client.post(path, data={
                "confirmation_name": "Full Reset Confirmation Academy",
                "confirmation_email": "full-reset-confirm@academy.edu",
                "reason": "",
            }, follow_redirects=False)

        self.assertIn("organization+name+does+not+match", name_mismatch.headers["location"])
        self.assertIn("account+email+does+not+match", email_mismatch.headers["location"])
        self.assertIn("deletion+reason+is+required", missing_reason.headers["location"])
        self.assertEqual(write_audit.call_count, 3)
        self.assertTrue(all(call.args[0]["result"] == "blocked" for call in write_audit.call_args_list))

    def test_delete_test_account_blocks_shared_and_platform_identities(self):
        shared = self._complete_paid_provisioning(
            email="full-reset-shared@academy.edu",
            organization_name="Shared Reset Academy",
        )
        db = self._db()
        try:
            shared_org = db.query(saas.models.PendingOrganization).filter_by(id=shared["organization_id"]).first()
            shared_uuid = shared_org.organization_uuid
            db.add(saas.models.PendingOrganization(
                organization_uuid="00000000-0000-0000-0000-000000009999",
                owner_saas_account_id=shared_org.owner_saas_account_id,
                organization_name="Second Shared Organization",
            ))
            db.commit()
        finally:
            db.close()
        owner_client = self._platform_client(user_id="9023")

        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            shared_response = owner_client.post(
                f"/saas-admin/pending-organizations/{shared_uuid}/delete-test-account",
                data={
                    "confirmation_name": "Shared Reset Academy",
                    "confirmation_email": "full-reset-shared@academy.edu",
                    "reason": "Retest",
                },
                follow_redirects=False,
            )
        self.assertIn("requires+manual+review", shared_response.headers["location"])

        platform_overlap = self._complete_paid_provisioning(
            email="full-reset-platform@academy.edu",
            organization_name="Platform Overlap Academy",
        )
        db = self._db()
        try:
            platform_org = db.query(saas.models.PendingOrganization).filter_by(
                id=platform_overlap["organization_id"]
            ).first()
            platform_uuid = platform_org.organization_uuid
            tenant_owner = db.query(models.User).filter_by(
                school_group_id=platform_overlap["school_group_id"]
            ).first()
            tenant_owner.user_type = auth.USER_TYPE_PLATFORM
            tenant_owner.platform_role = auth.PLATFORM_ROLE_DEVELOPER
            db.commit()
        finally:
            db.close()

        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            platform_response = owner_client.post(
                f"/saas-admin/pending-organizations/{platform_uuid}/delete-test-account",
                data={
                    "confirmation_name": "Platform Overlap Academy",
                    "confirmation_email": "full-reset-platform@academy.edu",
                    "reason": "Retest",
                },
                follow_redirects=False,
            )
        self.assertIn("requires+manual+review", platform_response.headers["location"])

    def test_delete_test_account_removes_identity_and_allows_same_email_signup(self):
        email = "full-reset-success@academy.edu"
        original_password = "strong-password-123"
        result = self._complete_paid_provisioning(
            email=email,
            organization_name="Full Reset Success Academy",
        )
        unrelated = self._complete_paid_provisioning(
            email="full-reset-unrelated@academy.edu",
            organization_name="Unrelated Full Reset Academy",
        )
        owner_client = self._platform_client(user_id="9024")
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first()
            organization_uuid = organization.organization_uuid
            account = db.query(saas.models.SaaSAccount).filter_by(email_normalized=email).first()
            account_id = account.id
            plan_count = db.query(saas.models.SubscriptionPlan).count()
            price_count = db.query(saas.models.SubscriptionPlanPrice).count()
        finally:
            db.close()
        path = f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account"

        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as write_audit,
            patch("saas.paddle_client.create_transaction") as create_transaction,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
        ):
            response = owner_client.post(path, data={
                "confirmation_name": "Full Reset Success Academy",
                "confirmation_email": email,
                "reason": "Repeat the complete Sandbox signup journey",
            }, follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("email+can+be+registered+again", response.headers["location"])
        self.assertEqual(write_audit.call_args.args[0]["result"], "success")
        create_transaction.assert_not_called()
        create_customer.assert_not_called()
        list_customers.assert_not_called()
        db = self._db()
        try:
            self.assertIsNone(db.query(saas.models.SaaSAccount).filter_by(id=account_id).first())
            self.assertIsNone(db.query(saas.models.PendingOrganization).filter_by(id=result["organization_id"]).first())
            self.assertIsNone(db.query(models.SchoolGroup).filter_by(id=result["school_group_id"]).first())
            self.assertIsNotNone(db.query(saas.models.PendingOrganization).filter_by(id=unrelated["organization_id"]).first())
            self.assertIsNotNone(db.query(models.SchoolGroup).filter_by(id=unrelated["school_group_id"]).first())
            self.assertEqual(db.query(saas.models.SubscriptionPlan).count(), plan_count)
            self.assertEqual(db.query(saas.models.SubscriptionPlanPrice).count(), price_count)
            self.assertIsNone(saas_service.authenticate_account(db, email, original_password))
        finally:
            db.close()

        deleted_login = self.client.post("/saas/auth/login", data={
            "email": email,
            "password": original_password,
            "next_path": "/saas/account",
        }, follow_redirects=False)
        self.assertEqual(deleted_login.status_code, 302)
        self.assertIn("/saas/login", deleted_login.headers["location"])

        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as repeated_audit,
        ):
            repeated = owner_client.post(path, data={
                "confirmation_name": "Full Reset Success Academy",
                "confirmation_email": email,
                "reason": "Repeated request",
            })
        self.assertEqual(repeated.status_code, 404)
        self.assertEqual(repeated_audit.call_args.args[0]["result"], "blocked_not_found")

        sent_messages = []
        with patch("email_service.send_email", side_effect=lambda **kwargs: sent_messages.append(kwargs) or "email_new"):
            signup = self.client.post("/saas/auth/signup", data={
                "first_name": "New",
                "last_name": "Tester",
                "email": email,
                "password": "new-strong-password-123",
                "confirm_password": "new-strong-password-123",
            }, follow_redirects=False)
        self.assertEqual(signup.status_code, 302)
        self.assertTrue(sent_messages)

    def test_delete_test_account_failure_rolls_back_identity_and_workspace(self):
        email = "full-reset-rollback@academy.edu"
        result = self._complete_paid_provisioning(
            email=email,
            organization_name="Full Reset Rollback Academy",
        )
        owner_client = self._platform_client(user_id="9025")
        db = self._db()
        try:
            organization_uuid = db.query(saas.models.PendingOrganization).filter_by(
                id=result["organization_id"]
            ).first().organization_uuid
            before = {
                "accounts": db.query(saas.models.SaaSAccount).count(),
                "pending": db.query(saas.models.PendingOrganization).count(),
                "groups": db.query(models.SchoolGroup).count(),
                "users": db.query(models.User).count(),
            }
        finally:
            db.close()

        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.test_account_deletion_service.Session.flush", side_effect=RuntimeError("simulated failure")),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            response = owner_client.post(
                f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account",
                data={
                    "confirmation_name": "Full Reset Rollback Academy",
                    "confirmation_email": email,
                    "reason": "Rollback test",
                },
                follow_redirects=False,
            )

        self.assertIn("All+data+was+preserved", response.headers["location"])
        self.assertEqual(write_audit.call_args.args[0]["result"], "failed_rolled_back")
        db = self._db()
        try:
            after = {
                "accounts": db.query(saas.models.SaaSAccount).count(),
                "pending": db.query(saas.models.PendingOrganization).count(),
                "groups": db.query(models.SchoolGroup).count(),
                "users": db.query(models.User).count(),
            }
        finally:
            db.close()
        self.assertEqual(before, after)

    def test_orphaned_account_management_owner_access_classification_and_environment_gate(self):
        orphan = self._create_orphaned_test_account(
            email="orphan-list@academy.edu",
            organization_name="Orphan List Academy",
        )
        self._complete_pending_org(
            "draft-account-list@academy.edu",
            [],
            organization_name="Draft Account List Academy",
        )
        owner_client = self._platform_client(user_id="9030")

        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "TIS_ENABLE_TEST_ACCOUNT_RESET": ""}):
            production_list = owner_client.get("/saas-admin/accounts")
            unavailable = owner_client.get(
                f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account"
            )
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "TIS_ENABLE_TEST_ACCOUNT_RESET": ""}):
            sandbox_list = owner_client.get("/saas-admin/accounts")
            confirmation = owner_client.get(
                f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account"
            )
            developer = self._platform_client(
                user_id="9031", platform_role=auth.PLATFORM_ROLE_DEVELOPER
            ).get("/saas-admin/accounts")
            tenant = self._tenant_client(user_id="7100000030").get("/saas-admin/accounts")

        self.assertEqual(production_list.status_code, 200)
        self.assertIn("Orphaned after test reset", production_list.text)
        self.assertIn("Draft/onboarding", production_list.text)
        self.assertNotIn(
            f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account",
            production_list.text,
        )
        self.assertEqual(unavailable.status_code, 404)
        self.assertIn("Delete Orphaned Test Account", sandbox_list.text)
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn(orphan["email"], confirmation.text)
        self.assertIn("Pending organizations: 0", confirmation.text)
        self.assertIn("Tenant provisioning links: 0", confirmation.text)
        self.assertEqual(developer.status_code, 403)
        self.assertEqual(tenant.status_code, 403)

    def test_orphaned_account_management_customer_denied_and_feature_flag_enabled(self):
        orphan = self._create_orphaned_test_account(
            email="orphan-customer-deny@academy.edu",
            organization_name="Orphan Customer Deny Academy",
        )
        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=orphan["account_id"]).first()
            session_token, _csrf, _row = saas_service.create_session(db, account)
            db.commit()
        finally:
            db.close()
        customer_client = TestClient(self.app)
        customer_client.cookies.set(saas_service.SAAS_SESSION_COOKIE, session_token)

        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "TIS_ENABLE_TEST_ACCOUNT_RESET": "true"}):
            owner_response = self._platform_client(user_id="9032").get(
                f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account"
            )
            customer_response = customer_client.get("/saas-admin/accounts")

        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(customer_response.status_code, 403)

    def test_orphaned_account_deletion_blocks_non_orphan_and_unsafe_relationships(self):
        active = self._complete_paid_provisioning(
            email="orphan-active@academy.edu",
            organization_name="Active Account Academy",
        )
        db = self._db()
        try:
            active_org = db.query(saas.models.PendingOrganization).filter_by(id=active["organization_id"]).first()
            active_account = db.query(saas.models.SaaSAccount).filter_by(id=active_org.owner_saas_account_id).first()
            active_uuid = active_account.account_uuid
        finally:
            db.close()
        owner_client = self._platform_client(user_id="9033")
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as blocked_audit,
        ):
            active_response = owner_client.post(
                f"/saas-admin/accounts/{active_uuid}/delete-orphaned-test-account",
                data={"confirmation_email": "orphan-active@academy.edu", "reason": "Retest"},
                follow_redirects=False,
            )
            account_list = owner_client.get("/saas-admin/accounts")
        self.assertIn("not+a+safely+orphaned", active_response.headers["location"])
        self.assertEqual(blocked_audit.call_args.args[0]["result"], "blocked")
        self.assertIn("Active with organization", account_list.text)

        linked = self._create_orphaned_test_account(
            email="orphan-linked@academy.edu",
            organization_name="Orphan Linked Academy",
        )
        db = self._db()
        try:
            group = models.SchoolGroup(name="Unsafe Residual Tenant", status=True)
            db.add(group)
            db.flush()
            branch = models.Branch(school_group_id=group.id, name="Unsafe Branch", status=True)
            db.add(branch)
            db.flush()
            user = models.User(
                user_id="7100000031", username="7100000031",
                email=linked["email"], email_normalized=linked["email"],
                password=auth.get_password_hash("TenantPass123!"),
                user_type=auth.USER_TYPE_TENANT, role=auth.ROLE_ADMINISTRATOR,
                school_group_id=group.id, branch_id=branch.id, is_active=True,
            )
            db.add(user)
            db.flush()
            db.add(saas.models.SaaSAccountUserLink(
                saas_account_id=linked["account_id"], operational_user_id=user.id,
                pending_organization_id=None, school_group_id=group.id,
            ))
            db.commit()
        finally:
            db.close()
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            linked_response = owner_client.post(
                f"/saas-admin/accounts/{linked['account_uuid']}/delete-orphaned-test-account",
                data={"confirmation_email": linked["email"], "reason": "Retest"},
                follow_redirects=False,
            )
        self.assertIn("Manual+review+is+required", linked_response.headers["location"])

    def test_orphaned_account_deletion_blocks_platform_identity_and_bound_payment_mapping(self):
        protected = self._create_orphaned_test_account(
            email="orphan-platform@academy.edu",
            organization_name="Orphan Platform Academy",
        )
        db = self._db()
        try:
            db.add(models.User(
                user_id="9034", username="platform.orphan.9034",
                email=protected["email"], email_normalized=protected["email"],
                password=auth.get_password_hash("PlatformPass123!"),
                user_type=auth.USER_TYPE_PLATFORM, platform_role=auth.PLATFORM_ROLE_DEVELOPER,
                access_scope=auth.ACCESS_SCOPE_GLOBAL, is_active=True,
            ))
            db.commit()
        finally:
            db.close()
        owner_client = self._platform_client(user_id="9035")
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            protected_response = owner_client.get(
                f"/saas-admin/accounts/{protected['account_uuid']}/delete-orphaned-test-account"
            )
        self.assertIn("Standalone SaaS account - protected email match", protected_response.text)
        self.assertNotIn("Permanently Delete Orphaned Test Account</button>", protected_response.text)

        payment = self._create_orphaned_test_account(
            email="orphan-payment@academy.edu",
            organization_name="Orphan Payment Academy",
        )
        sent_messages = []
        other_uuid = self._complete_pending_org(
            "other-payment-owner@academy.edu", sent_messages,
            organization_name="Other Payment Organization",
        )
        db = self._db()
        try:
            other_org = db.query(saas.models.PendingOrganization).filter_by(organization_uuid=other_uuid).first()
            db.add(saas.models.PaymentCustomer(
                pending_organization_id=other_org.id,
                saas_account_id=payment["account_id"],
                provider="paddle", provider_customer_id="ctm_orphan_shared_payment",
                email=payment["email"], status="active",
            ))
            db.commit()
        finally:
            db.close()
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            payment_response = owner_client.get(
                f"/saas-admin/accounts/{payment['account_uuid']}/delete-orphaned-test-account"
            )
        self.assertIn("Manual review required", payment_response.text)
        self.assertIn("payment-customer mapping is associated", payment_response.text)

    def test_orphaned_account_confirmation_and_reason_are_required(self):
        orphan = self._create_orphaned_test_account(
            email="orphan-confirm@academy.edu",
            organization_name="Orphan Confirm Academy",
        )
        owner_client = self._platform_client(user_id="9036")
        path = f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account"
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            mismatch = owner_client.post(path, data={
                "confirmation_email": "ORPHAN-CONFIRM@academy.edu", "reason": "Retest",
            }, follow_redirects=False)
            missing_reason = owner_client.post(path, data={
                "confirmation_email": orphan["email"], "reason": "",
            }, follow_redirects=False)
        self.assertIn("account+email+does+not+match", mismatch.headers["location"])
        self.assertIn("deletion+reason+is+required", missing_reason.headers["location"])
        self.assertEqual(write_audit.call_count, 2)

    def test_orphaned_account_deletion_succeeds_and_allows_email_reuse(self):
        email = "orphan-success@academy.edu"
        orphan = self._create_orphaned_test_account(
            email=email,
            organization_name="Orphan Success Academy",
        )
        unrelated = self._create_orphaned_test_account(
            email="orphan-unrelated@academy.edu",
            organization_name="Orphan Unrelated Academy",
        )
        owner_client = self._platform_client(user_id="9037")
        db = self._db()
        try:
            plan_count = db.query(saas.models.SubscriptionPlan).count()
            price_count = db.query(saas.models.SubscriptionPlanPrice).count()
        finally:
            db.close()
        path = f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account"
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as write_audit,
            patch("saas.paddle_client.create_transaction") as create_transaction,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
        ):
            response = owner_client.post(path, data={
                "confirmation_email": email,
                "reason": "Repeat orphaned Sandbox account journey",
            }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("email+can+be+registered+again", response.headers["location"])
        self.assertEqual(write_audit.call_args.args[0]["result"], "success")
        create_transaction.assert_not_called()
        create_customer.assert_not_called()
        list_customers.assert_not_called()
        db = self._db()
        try:
            self.assertIsNone(db.query(saas.models.SaaSAccount).filter_by(id=orphan["account_id"]).first())
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=unrelated["account_id"]).first())
            self.assertEqual(db.query(saas.models.SubscriptionPlan).count(), plan_count)
            self.assertEqual(db.query(saas.models.SubscriptionPlanPrice).count(), price_count)
            self.assertIsNone(saas_service.authenticate_account(db, email, "strong-password-123"))
        finally:
            db.close()
        deleted_login = self.client.post("/saas/auth/login", data={
            "email": email, "password": "strong-password-123", "next_path": "/saas/account",
        }, follow_redirects=False)
        self.assertIn("/saas/login", deleted_login.headers["location"])
        sent_messages = []
        with patch("email_service.send_email", side_effect=lambda **kwargs: sent_messages.append(kwargs) or "email_reuse"):
            signup = self.client.post("/saas/auth/signup", data={
                "first_name": "New", "last_name": "Tester", "email": email,
                "password": "new-strong-password-123", "confirm_password": "new-strong-password-123",
            }, follow_redirects=False)
        self.assertEqual(signup.status_code, 302)
        self.assertTrue(sent_messages)
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as repeated_audit,
        ):
            repeated = owner_client.post(path, data={"confirmation_email": email, "reason": "Repeat"})
        self.assertEqual(repeated.status_code, 404)
        self.assertEqual(repeated_audit.call_args.args[0]["result"], "blocked_not_found")

    def test_orphaned_account_deletion_rolls_back_all_identity_rows(self):
        orphan = self._create_orphaned_test_account(
            email="orphan-rollback@academy.edu",
            organization_name="Orphan Rollback Academy",
        )
        owner_client = self._platform_client(user_id="9038")
        db = self._db()
        try:
            before = {
                "accounts": db.query(saas.models.SaaSAccount).count(),
                "sessions": db.query(saas.models.SaaSSession).count(),
                "identities": db.query(saas.models.SaaSAuthIdentity).count(),
                "events": db.query(saas.models.SaaSAuthEvent).count(),
            }
        finally:
            db.close()
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.orphaned_test_account_service.Session.flush", side_effect=RuntimeError("simulated failure")),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            response = owner_client.post(
                f"/saas-admin/accounts/{orphan['account_uuid']}/delete-orphaned-test-account",
                data={"confirmation_email": orphan["email"], "reason": "Rollback test"},
                follow_redirects=False,
            )
        self.assertIn("All+data+was+preserved", response.headers["location"])
        self.assertEqual(write_audit.call_args.args[0]["result"], "failed_rolled_back")
        db = self._db()
        try:
            after = {
                "accounts": db.query(saas.models.SaaSAccount).count(),
                "sessions": db.query(saas.models.SaaSSession).count(),
                "identities": db.query(saas.models.SaaSAuthIdentity).count(),
                "events": db.query(saas.models.SaaSAuthEvent).count(),
            }
        finally:
            db.close()
        self.assertEqual(before, after)

    def test_standalone_platform_email_match_is_classified_and_owner_only(self):
        owner_match = self._create_standalone_platform_email_account(
            user_id="9040", platform_role=auth.PLATFORM_ROLE_OWNER,
        )
        developer_match = self._create_standalone_platform_email_account(
            user_id="9041", platform_role=auth.PLATFORM_ROLE_DEVELOPER,
        )
        owner_client = self._platform_client(user_id="9042")
        owner_path = f"/saas-admin/accounts/{owner_match['account_uuid']}/delete-standalone-saas-account"

        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "TIS_ENABLE_TEST_ACCOUNT_RESET": ""}):
            production_list = owner_client.get("/saas-admin/accounts")
            unavailable = owner_client.get(owner_path)
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox", "TIS_ENABLE_TEST_ACCOUNT_RESET": ""}):
            sandbox_list = owner_client.get("/saas-admin/accounts")
            owner_page = owner_client.get(owner_path)
            developer_page = owner_client.get(
                f"/saas-admin/accounts/{developer_match['account_uuid']}/delete-standalone-saas-account"
            )
            denied_developer = self._platform_client(
                user_id="9043", platform_role=auth.PLATFORM_ROLE_DEVELOPER
            ).get(owner_path)
            denied_tenant = self._tenant_client(user_id="7100000040").get(owner_path)

        self.assertIn("Standalone SaaS account - protected email match", production_list.text)
        self.assertNotIn("Delete SaaS Account Only", production_list.text)
        self.assertEqual(unavailable.status_code, 404)
        self.assertIn("Delete SaaS Account Only", sandbox_list.text)
        self.assertIn("Platform identity preserved", sandbox_list.text)
        self.assertIn("Permanently Delete SaaS Account Only", owner_page.text)
        self.assertIn("Permanently Delete SaaS Account Only", developer_page.text)
        self.assertEqual(denied_developer.status_code, 403)
        self.assertEqual(denied_tenant.status_code, 403)

    def test_standalone_saas_account_customer_denied_and_feature_flag_enabled(self):
        standalone = self._create_standalone_platform_email_account(
            user_id="9044", platform_role=auth.PLATFORM_ROLE_OWNER,
        )
        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=standalone["account_id"]).first()
            session_token, _csrf, _row = saas_service.create_session(db, account)
            db.commit()
        finally:
            db.close()
        customer_client = TestClient(self.app)
        customer_client.cookies.set(saas_service.SAAS_SESSION_COOKIE, session_token)
        path = f"/saas-admin/accounts/{standalone['account_uuid']}/delete-standalone-saas-account"
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production", "TIS_ENABLE_TEST_ACCOUNT_RESET": "true"}):
            owner_response = self._platform_client(user_id="9045").get(path)
            customer_response = customer_client.get(path)
        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(customer_response.status_code, 403)

    def test_standalone_saas_account_strict_relationship_and_state_gates(self):
        active = self._create_standalone_platform_email_account(
            user_id="9046", platform_role=auth.PLATFORM_ROLE_OWNER,
        )
        pending = self._create_standalone_platform_email_account(
            user_id="9047", platform_role=auth.PLATFORM_ROLE_DEVELOPER,
        )
        linked = self._create_standalone_platform_email_account(
            user_id="9048", platform_role=auth.PLATFORM_ROLE_OWNER,
        )
        db = self._db()
        try:
            active_account = db.query(saas.models.SaaSAccount).filter_by(id=active["account_id"]).first()
            active_account.status = "active"
            pending_account = db.query(saas.models.SaaSAccount).filter_by(id=pending["account_id"]).first()
            pending_org = saas.models.PendingOrganization(
                organization_uuid="00000000-0000-0000-0000-000000009947",
                owner_saas_account_id=pending_account.id,
                organization_name="Standalone Blocked Organization",
            )
            db.add(pending_org)
            linked_account = db.query(saas.models.SaaSAccount).filter_by(id=linked["account_id"]).first()
            group = models.SchoolGroup(name="Standalone Unsafe Tenant", status=True)
            db.add(group)
            db.flush()
            branch = models.Branch(school_group_id=group.id, name="Standalone Unsafe Branch", status=True)
            db.add(branch)
            db.flush()
            tenant_user = models.User(
                user_id="7100000041", username="7100000041",
                email="standalone-linked-tenant@example.com",
                email_normalized="standalone-linked-tenant@example.com",
                password=auth.get_password_hash("TenantPass123!"),
                user_type=auth.USER_TYPE_TENANT, role=auth.ROLE_ADMINISTRATOR,
                school_group_id=group.id, branch_id=branch.id, is_active=True,
            )
            db.add(tenant_user)
            db.flush()
            db.add(saas.models.SaaSAccountUserLink(
                saas_account_id=linked_account.id,
                operational_user_id=tenant_user.id,
                pending_organization_id=None,
                school_group_id=group.id,
            ))
            db.commit()
        finally:
            db.close()
        owner_client = self._platform_client(user_id="9049")
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            for fixture in (active, pending, linked):
                response = owner_client.post(
                    f"/saas-admin/accounts/{fixture['account_uuid']}/delete-standalone-saas-account",
                    data={"confirmation_email": fixture["email"], "reason": "Retest"},
                    follow_redirects=False,
                )
                self.assertIn("not+a+safely+standalone", response.headers["location"])

    def test_standalone_saas_account_payment_and_provisioning_records_block(self):
        standalone = self._create_standalone_platform_email_account(
            user_id="9050", platform_role=auth.PLATFORM_ROLE_OWNER,
        )
        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=standalone["account_id"]).first()
            plan = db.query(saas.models.SubscriptionPlan).first()
            organization = saas.models.PendingOrganization(
                organization_uuid="00000000-0000-0000-0000-000000009950",
                owner_saas_account_id=account.id,
                organization_name="Standalone Payment Block",
            )
            db.add(organization)
            db.flush()
            selection = saas.models.PendingOrganizationPlanSelection(
                pending_organization_id=organization.id, plan_id=plan.id,
                billing_interval="monthly", base_amount_minor=2900,
                display_amount_minor=2900,
            )
            db.add(selection)
            db.flush()
            checkout = saas.models.CheckoutSession(
                pending_organization_id=organization.id,
                plan_selection_id=selection.id,
                amount_minor=2900, billing_interval="monthly",
            )
            db.add(checkout)
            db.flush()
            payment_customer = saas.models.PaymentCustomer(
                pending_organization_id=organization.id,
                saas_account_id=account.id,
                provider="paddle", provider_customer_id="ctm_standalone_block",
                email=account.email, status="active",
            )
            db.add(payment_customer)
            db.flush()
            db.add(saas.models.PaymentAttempt(
                pending_organization_id=organization.id,
                checkout_session_id=checkout.id,
                plan_selection_id=selection.id,
                payment_customer_id=payment_customer.id,
                attempt_uuid="00000000-0000-0000-0000-000000009950",
                billing_interval="monthly", amount_minor=2900,
            ))
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id,
                plan_id=plan.id, billing_interval="monthly",
                base_amount_minor=2900, display_amount_minor=2900,
                selected_checkout_session_id=checkout.id,
            )
            db.add(contract)
            db.flush()
            job = saas.models.ProvisioningJob(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                job_uuid="00000000-0000-0000-0000-000000009951",
                idempotency_key="standalone-provisioning-block-9951",
            )
            db.add(job)
            db.flush()
            db.add(saas.models.ProvisioningJobEvent(
                provisioning_job_id=job.id,
                event_type="queued",
            ))
            db.commit()
        finally:
            db.close()
        owner_client = self._platform_client(user_id="9051")
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}):
            page = owner_client.get(
                f"/saas-admin/accounts/{standalone['account_uuid']}/delete-standalone-saas-account"
            )
        self.assertIn("does not meet every standalone-account safety requirement", page.text)
        self.assertNotIn("Permanently Delete SaaS Account Only</button>", page.text)
        self.assertIn("Checkout sessions: 1", page.text)
        self.assertIn("Payment attempts: 1", page.text)
        self.assertIn("Provisioning jobs: 1", page.text)

    def test_standalone_saas_account_confirmation_and_reason_are_required(self):
        standalone = self._create_standalone_platform_email_account(
            user_id="9052", platform_role=auth.PLATFORM_ROLE_DEVELOPER,
        )
        owner_client = self._platform_client(user_id="9053")
        path = f"/saas-admin/accounts/{standalone['account_uuid']}/delete-standalone-saas-account"
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            mismatch = owner_client.post(path, data={
                "confirmation_email": standalone["email"].upper(), "reason": "Retest",
            }, follow_redirects=False)
            missing_reason = owner_client.post(path, data={
                "confirmation_email": standalone["email"], "reason": "",
            }, follow_redirects=False)
        self.assertIn("account+email+does+not+match", mismatch.headers["location"])
        self.assertIn("deletion+reason+is+required", missing_reason.headers["location"])
        self.assertEqual(write_audit.call_count, 2)

    def test_standalone_saas_account_deletion_preserves_platform_identity_and_allows_reuse(self):
        standalone = self._create_standalone_platform_email_account(
            user_id="9054", platform_role=auth.PLATFORM_ROLE_OWNER,
        )
        unrelated = self._create_orphaned_test_account(
            email="standalone-unrelated@academy.edu",
            organization_name="Standalone Unrelated Academy",
        )
        owner_client = self._platform_client(user_id="9055")
        db = self._db()
        try:
            platform_user = db.query(models.User).filter_by(id=standalone["platform_user_id"]).first()
            db.add(models.PlatformUserPermission(
                platform_user_id=platform_user.id,
                permission_key="users.view",
                is_allowed=True,
            ))
            db.commit()
            platform_snapshot = {
                "id": platform_user.id,
                "user_id": platform_user.user_id,
                "email": platform_user.email,
                "password": platform_user.password,
                "platform_role": platform_user.platform_role,
                "is_active": platform_user.is_active,
            }
            plan_count = db.query(saas.models.SubscriptionPlan).count()
            permission_count = db.query(models.PlatformUserPermission).filter_by(
                platform_user_id=platform_user.id
            ).count()
        finally:
            db.close()
        path = f"/saas-admin/accounts/{standalone['account_uuid']}/delete-standalone-saas-account"
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as write_audit,
            patch("saas.paddle_client.create_transaction") as create_transaction,
            patch("saas.paddle_client.create_customer") as create_customer,
            patch("saas.paddle_client.list_customers_by_email") as list_customers,
        ):
            response = owner_client.post(path, data={
                "confirmation_email": standalone["email"],
                "reason": "Remove unused standalone SaaS identity",
            }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("Platform+identity+remains+unchanged", response.headers["location"])
        self.assertTrue(write_audit.call_args.args[0]["platform_identity_preserved"])
        create_transaction.assert_not_called()
        create_customer.assert_not_called()
        list_customers.assert_not_called()
        db = self._db()
        try:
            self.assertIsNone(db.query(saas.models.SaaSAccount).filter_by(id=standalone["account_id"]).first())
            preserved_user = db.query(models.User).filter_by(id=standalone["platform_user_id"]).first()
            self.assertEqual({
                "id": preserved_user.id,
                "user_id": preserved_user.user_id,
                "email": preserved_user.email,
                "password": preserved_user.password,
                "platform_role": preserved_user.platform_role,
                "is_active": preserved_user.is_active,
            }, platform_snapshot)
            self.assertIsNotNone(auth.authenticate_user(db, standalone["email"], standalone["platform_password"]))
            self.assertEqual(
                db.query(models.PlatformUserPermission).filter_by(
                    platform_user_id=standalone["platform_user_id"]
                ).count(),
                permission_count,
            )
            self.assertIsNone(saas_service.authenticate_account(db, standalone["email"], standalone["saas_password"]))
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=unrelated["account_id"]).first())
            self.assertEqual(db.query(saas.models.SubscriptionPlan).count(), plan_count)
        finally:
            db.close()
        sent_messages = []
        with patch("email_service.send_email", side_effect=lambda **kwargs: sent_messages.append(kwargs) or "standalone_reuse"):
            signup = self.client.post("/saas/auth/signup", data={
                "first_name": "New", "last_name": "SaaS", "email": standalone["email"],
                "password": "new-standalone-password-123", "confirm_password": "new-standalone-password-123",
            }, follow_redirects=False)
        self.assertEqual(signup.status_code, 302)
        self.assertTrue(sent_messages)
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.router.audit.write_audit_event") as repeated_audit,
        ):
            repeated = owner_client.post(path, data={
                "confirmation_email": standalone["email"], "reason": "Repeat",
            })
        self.assertEqual(repeated.status_code, 404)
        self.assertEqual(repeated_audit.call_args.args[0]["result"], "blocked_not_found")

    def test_standalone_saas_account_deletion_rolls_back_all_saas_rows(self):
        standalone = self._create_standalone_platform_email_account(
            user_id="9056", platform_role=auth.PLATFORM_ROLE_DEVELOPER,
        )
        owner_client = self._platform_client(user_id="9057")
        db = self._db()
        try:
            before = {
                "accounts": db.query(saas.models.SaaSAccount).count(),
                "sessions": db.query(saas.models.SaaSSession).count(),
                "identities": db.query(saas.models.SaaSAuthIdentity).count(),
                "events": db.query(saas.models.SaaSAuthEvent).count(),
                "platform_users": db.query(models.User).filter(models.User.user_type == auth.USER_TYPE_PLATFORM).count(),
            }
        finally:
            db.close()
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch("saas.orphaned_test_account_service.Session.flush", side_effect=RuntimeError("simulated failure")),
            patch("saas.router.audit.write_audit_event") as write_audit,
        ):
            response = owner_client.post(
                f"/saas-admin/accounts/{standalone['account_uuid']}/delete-standalone-saas-account",
                data={"confirmation_email": standalone["email"], "reason": "Rollback test"},
                follow_redirects=False,
            )
        self.assertIn("All+data+was+preserved", response.headers["location"])
        self.assertEqual(write_audit.call_args.args[0]["result"], "failed_rolled_back")
        db = self._db()
        try:
            after = {
                "accounts": db.query(saas.models.SaaSAccount).count(),
                "sessions": db.query(saas.models.SaaSSession).count(),
                "identities": db.query(saas.models.SaaSAuthIdentity).count(),
                "events": db.query(saas.models.SaaSAuthEvent).count(),
                "platform_users": db.query(models.User).filter(models.User.user_type == auth.USER_TYPE_PLATFORM).count(),
            }
        finally:
            db.close()
        self.assertEqual(before, after)

    def test_activation_email_uses_configured_production_public_urls(self):
        sent_messages = []

        class Account:
            email = "owner@academy.edu"

        class Organization:
            organization_name = "Andalus Academy"

        with (
            patch.dict(
                os.environ,
                {
                    "TIS_PUBLIC_BASE_URL": "https://app.tisplatform.com",
                    "TIS_ENV": "production",
                },
                clear=False,
            ),
            patch("email_service.send_email", side_effect=lambda **kwargs: sent_messages.append(kwargs) or "email_activation_prod"),
        ):
            provisioning_service._send_activation_email(Account(), Organization())

        self.assertEqual(len(sent_messages), 1)
        activation_email = sent_messages[0]
        self.assertIn("https://app.tisplatform.com/login", activation_email["text"])
        self.assertIn('href="https://app.tisplatform.com/login"', activation_email["html"])
        self.assertIn("https://app.tisplatform.com/static/branding/tis/logos/", activation_email["html"])
        self.assertIn("TIS%20Wordmark%20Only%20%E2%80%93%20Dark%20Blue.png", activation_email["html"])
        self.assertNotIn("http://localhost:8000", activation_email["html"])
        self.assertNotIn("http://localhost:8000", activation_email["text"])
        self.assertNotIn(os.environ["PADDLE_API_KEY"], activation_email["html"])
        self.assertNotIn("DATABASE_URL", activation_email["html"])

    def test_activation_email_local_fallback_remains_available_outside_production(self):
        with patch.dict(os.environ, {"TIS_PUBLIC_BASE_URL": "", "TIS_ENV": "local"}, clear=False):
            self.assertEqual(provisioning_service.operational_login_url(), "http://localhost:8000/login")
            self.assertIn(
                "http://localhost:8000/static/branding/tis/logos/",
                provisioning_service._email_logo_url(),
            )

    def test_production_missing_public_base_url_does_not_emit_localhost(self):
        with patch.dict(os.environ, {"TIS_PUBLIC_BASE_URL": "", "TIS_ENV": "production"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "TIS_PUBLIC_BASE_URL"):
                provisioning_service.operational_login_url()
            with self.assertRaisesRegex(RuntimeError, "TIS_PUBLIC_BASE_URL"):
                provisioning_service._email_logo_url()

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
