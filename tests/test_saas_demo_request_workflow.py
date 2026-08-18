import json
import os
import re
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.requests import Request
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import authorization
import db_migrations
import models
import saas.models
import ui_shell
from dependencies import get_db
from saas import (
    commercial_authority_service,
    commercial_state_service,
    demo_conversion_service,
    demo_lifecycle_service,
    demo_provisioning_service,
    demo_request_service,
    entitlement_service,
    provisioning_service,
    service,
    workspace_classification_service,
    workspace_entitlement_service,
)
from saas.router import admin_router as saas_admin_router, router as saas_router


class SaaSDemoRequestWorkflowTests(unittest.TestCase):
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
        self.extra_clients = []

    def tearDown(self):
        for client in self.extra_clients:
            client.close()
        self.client.close()
        self.engine.dispose()

    def _db(self):
        return self.Session()

    def _signup_verify_login(self, client: TestClient, email: str, *, intent: str = ""):
        messages = []

        def fake_send_email(**kwargs):
            messages.append(kwargs)
            return "demo_email"

        with patch("email_service.send_email", side_effect=fake_send_email):
            response = client.post(
                "/saas/auth/signup",
                data={
                    "first_name": "Demo",
                    "last_name": "Requester",
                    "email": email,
                    "password": "strong-password-123",
                    "confirm_password": "strong-password-123",
                    "intent": intent,
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        token = re.search(r"token=([A-Za-z0-9._\-]+)", messages[0]["text"]).group(1)
        self.assertEqual(
            client.get(f"/saas/auth/verify-email?token={token}", follow_redirects=False).status_code,
            302,
        )
        login = client.post(
            "/saas/auth/login",
            data={"email": email, "password": "strong-password-123", "next_path": "/saas/account"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 302)

    def _complete_onboarding(
        self,
        email: str = "demo.requester@academy.edu",
        *,
        client: TestClient | None = None,
        intent: str = "",
        domain: str = "",
    ) -> str:
        client = client or self.client
        organization_domain = domain or (
            f"{email.rsplit('@', 1)[0].replace('.', '-')}.example.edu"
        )
        self._signup_verify_login(client, email, intent=intent)
        self.assertEqual(
            client.post("/saas/onboarding/start", follow_redirects=False).status_code,
            302,
        )
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).order_by(
                saas.models.PendingOrganization.id.desc()
            ).first()
            organization_uuid = organization.organization_uuid
        finally:
            db.close()
        client.post(
            f"/saas/onboarding/{organization_uuid}/organization",
            data={
                "organization_name": "Demo Academy",
                "legal_name": "Demo Academy Legal",
                "website": f"https://{organization_domain}",
                "primary_domain": organization_domain,
                "phone": "+9611000000",
                "educational_program": "BOTH",
                "country_code": "LB",
                "country_name": "Lebanon",
                "region_name": "Beirut",
                "city_name": "Beirut",
                "district_name": "Beirut",
                "neighborhood_name": "Central",
                "school_type": "K-12",
                "expected_branch_count": "2",
                "expected_student_count": "800",
                "expected_teacher_count": "65",
                "estimated_staff_users": "20",
                "timezone": "Asia/Beirut",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        client.post(
            f"/saas/onboarding/{organization_uuid}/branches",
            data={
                "branch_name": ["Main Campus", "North Campus"],
                "location": ["Beirut", "Beirut"],
                "country_code": ["LB", "LB"],
                "country_name": ["Lebanon", "Lebanon"],
                "region_name": ["Beirut", "Beirut"],
                "city_name": ["Beirut", "Beirut"],
                "district_name": ["Beirut", "Beirut"],
                "neighborhood_name": ["Central", "North"],
                "estimated_system_users": ["10", "10"],
                "estimated_teachers": ["33", "32"],
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        client.post(
            f"/saas/onboarding/{organization_uuid}/academic_setup",
            data={
                "first_academic_year_name": "2026-2027",
                "create_default_branch": "1",
                "notes": "Demo review setup",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        client.post(
            f"/saas/onboarding/{organization_uuid}/contacts",
            data={
                "first_name": "Demo",
                "last_name": "Requester",
                "job_title": "Principal",
                "email": email,
                "phone": "+9611000001",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        submitted = client.post(
            f"/saas/onboarding/{organization_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 302)
        self.assertEqual(
            submitted.headers["location"],
            f"/saas/onboarding/{organization_uuid}/commercial-choice",
        )
        return organization_uuid

    def _submit_demo(self, organization_uuid: str, *, client: TestClient | None = None):
        client = client or self.client
        response = client.post(
            f"/saas/onboarding/{organization_uuid}/commercial-choice/request-demo",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        db = self._db()
        try:
            row = db.query(saas.models.SaaSDemoRequest).order_by(
                saas.models.SaaSDemoRequest.id.desc()
            ).first()
            self.assertIsNotNone(row)
            return row.request_uuid
        finally:
            db.close()

    def _platform_client(self, *, role: str = auth.PLATFORM_ROLE_OWNER, user_id: str = "9101"):
        db = self._db()
        try:
            user = models.User(
                user_id=user_id,
                username=f"platform.{user_id}",
                email=f"platform.{user_id}@example.com",
                email_normalized=auth.normalize_email(f"platform.{user_id}@example.com"),
                first_name="Platform",
                last_name="Reviewer",
                password=auth.get_password_hash("PlatformPass123!"),
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=role,
                platform_owner_kind=(
                    auth.PLATFORM_OWNER_PRIMARY if role == auth.PLATFORM_ROLE_OWNER else None
                ),
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(user)
            db.commit()
            token = auth.create_session_token(user)
        finally:
            db.close()
        client = TestClient(self.app)
        client.cookies.set(auth.SESSION_COOKIE_KEY, token)
        self.extra_clients.append(client)
        return client

    def _approve_demo(self, request_uuid: str, *, user_id: str = "9190"):
        owner = self._platform_client(user_id=user_id)
        response = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/approve",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        return owner

    def _activate_demo(
        self,
        *,
        email: str = "lifecycle.demo@academy.edu",
        owner_user_id: str = "9180",
    ):
        organization_uuid = self._complete_onboarding(email)
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._approve_demo(request_uuid, user_id=owner_user_id)
        db = self._db()
        try:
            request_row = db.query(saas.models.SaaSDemoRequest).filter_by(
                request_uuid=request_uuid
            ).one()
            provisioning = db.query(saas.models.SaaSDemoWorkspaceProvisioning).filter_by(
                demo_request_id=request_row.id
            ).one()
            account_link = db.query(saas.models.SaaSAccountUserLink).filter_by(
                saas_account_id=request_row.requester_saas_account_id,
                school_group_id=request_row.school_group_id,
            ).one()
            return {
                "organization_uuid": organization_uuid,
                "request_uuid": request_uuid,
                "request_id": request_row.id,
                "provisioning_id": provisioning.id,
                "school_group_id": request_row.school_group_id,
                "entitlement_id": provisioning.workspace_entitlement_id,
                "tenant_link_id": provisioning.tenant_provisioning_link_id,
                "saas_account_id": request_row.requester_saas_account_id,
                "operational_user_id": account_link.operational_user_id,
                "owner_client": owner,
            }
        finally:
            db.close()

    @staticmethod
    def _request(path: str, *, accept: str = "text/html") -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [(b"accept", accept.encode())],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 443),
            }
        )

    def _set_demo_started_at(self, fixture: dict, started_at: datetime) -> datetime:
        started = demo_lifecycle_service.as_utc(started_at)
        reminder_due, expires = demo_lifecycle_service.calculate_lifecycle_dates(started)
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            entitlement = db.get(
                saas.models.WorkspaceEntitlement,
                fixture["entitlement_id"],
            )
            provisioning.activated_at = demo_lifecycle_service.storage_datetime(started)
            provisioning.reminder_due_at = demo_lifecycle_service.storage_datetime(
                reminder_due
            )
            provisioning.demo_expires_at = demo_lifecycle_service.storage_datetime(expires)
            provisioning.reminder_sent_at = None
            provisioning.expired_at = None
            provisioning.lifecycle_processing_status = "pending"
            provisioning.lifecycle_failure_code = None
            entitlement.effective_from = demo_lifecycle_service.storage_datetime(started)
            entitlement.effective_to = demo_lifecycle_service.storage_datetime(expires)
            db.commit()
        finally:
            db.close()
        return started

    def test_unpaid_demo_tenant_link_does_not_freeze_onboarding_branches(self):
        fixture = self._activate_demo(
            email="editable.demo.branches@academy.edu",
            owner_user_id="9189",
        )
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=fixture["organization_uuid"]
            ).one()
            rows = service.list_billable_pending_branches(db, organization)
            existing_tenant_link_id = fixture["tenant_link_id"]
            existing_school_group_id = fixture["school_group_id"]
            submitted = [
                {
                    "branch_uuid": row.branch_uuid,
                    "branch_name": row.branch_name,
                    "location": row.location,
                    "country_code": row.country_code,
                }
                for row in rows
            ]
            submitted.append(
                {
                    "branch_name": "Future Paid Branch",
                    "location": "Beirut",
                    "country_code": "LB",
                }
            )
            service.replace_branches(db, organization, submitted)
            db.flush()
            self.assertEqual(
                service.count_billable_pending_branches(db, organization), 3
            )
            self.assertEqual(
                db.query(saas.models.TenantProvisioningLink).filter_by(
                    pending_organization_id=organization.id
                ).one().id,
                existing_tenant_link_id,
            )
            self.assertEqual(
                db.query(models.Branch).filter_by(
                    school_group_id=existing_school_group_id,
                    status=True,
                ).count(),
                3,
            )
            self.assertEqual(
                db.query(saas.models.TenantProvisioningLink).filter_by(
                    id=existing_tenant_link_id
                ).one().school_group_id,
                existing_school_group_id,
            )
        finally:
            db.close()

    def _confirmed_subscription_for_demo(
        self,
        fixture: dict,
        *,
        status: str = "active",
        quantity: int = 2,
        request_conversion: bool = True,
    ) -> dict:
        db = self._db()
        try:
            demo_request = db.get(saas.models.SaaSDemoRequest, fixture["request_id"])
            organization = db.get(
                saas.models.PendingOrganization,
                demo_request.pending_organization_id,
            )
            account = db.get(
                saas.models.SaaSAccount,
                demo_request.requester_saas_account_id,
            )
            if request_conversion:
                conversion = demo_conversion_service.request_demo_conversion(
                    db,
                    account,
                    organization,
                )
            else:
                conversion = None
            plan = db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code="professional"
            ).one()
            price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=plan.id,
                billing_interval="monthly",
                currency_code="USD",
                is_active=True,
            ).one()
            price.provider_price_id = (
                price.provider_price_id
                or f"pri_conversion_{fixture['provisioning_id']}"
            )
            now = datetime.now(UTC).replace(tzinfo=None)
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id,
                plan_id=plan.id,
                billing_interval="monthly",
                contract_status="paid_pending_provisioning",
                payment_status="paid",
                paid_at=now,
                base_currency_code="USD",
                base_amount_minor=price.amount_minor * quantity,
                display_currency_code="USD",
                display_amount_minor=price.amount_minor * quantity,
                billable_branch_count=quantity,
            )
            db.add(contract)
            db.flush()
            subscription = saas.models.PaymentSubscription(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                provider="paddle",
                provider_subscription_id=(
                    f"sub_demo_conversion_{fixture['provisioning_id']}"
                ),
                provider_price_id=price.provider_price_id,
                plan_id=plan.id,
                billing_interval="monthly",
                currency_code="USD",
                quantity=quantity,
                unit_amount_minor=price.amount_minor,
                amount_minor=price.amount_minor * quantity,
                status=status,
                current_period_start=now,
                current_period_end=now + timedelta(days=30),
            )
            db.add(subscription)
            db.commit()
            return {
                "organization_id": organization.id,
                "account_id": account.id,
                "contract_id": contract.id,
                "subscription_id": subscription.id,
                "conversion_id": getattr(conversion, "id", None),
            }
        finally:
            db.close()

    def _convert_demo(self, fixture: dict, commercial: dict):
        db = self._db()
        try:
            outcome = demo_conversion_service.convert_confirmed_demo_subscription(
                db,
                organization=db.get(
                    saas.models.PendingOrganization,
                    commercial["organization_id"],
                ),
                contract=db.get(
                    saas.models.SubscriptionContract,
                    commercial["contract_id"],
                ),
                subscription=db.get(
                    saas.models.PaymentSubscription,
                    commercial["subscription_id"],
                ),
            )
            db.commit()
            return outcome
        finally:
            db.close()

    def test_customer_choice_offers_demo_or_existing_subscription_workflow(self):
        organization_uuid = self._complete_onboarding()
        page = self.client.get(f"/saas/onboarding/{organization_uuid}/commercial-choice")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Request Demo", page.text)
        self.assertIn("Subscribe Now", page.text)
        self.assertEqual(page.text.count("Request Demo"), 2)

        with patch("saas.paddle_client.create_transaction") as create_transaction:
            response = self.client.post(
                f"/saas/onboarding/{organization_uuid}/commercial-choice/subscribe",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], f"/saas/onboarding/{organization_uuid}/plan")
        create_transaction.assert_not_called()
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            account = db.query(saas.models.SaaSAccount).filter_by(
                id=organization.owner_saas_account_id
            ).one()
            self.assertEqual(organization.workspace_intent, "customer_paid")
            self.assertEqual(account.account_purpose, "customer")
            self.assertEqual(db.query(saas.models.SaaSDemoRequest).count(), 0)
        finally:
            db.close()

    def test_submission_is_snapshotted_audited_notified_and_duplicate_safe(self):
        self._platform_client(user_id="SUBMIT9100")
        organization_uuid = self._complete_onboarding()
        with patch("saas.router.audit.write_audit_event") as write_audit:
            request_uuid = self._submit_demo(organization_uuid)
        self.assertEqual(write_audit.call_args.args[0]["action"], "submit")
        db = self._db()
        try:
            row = db.query(saas.models.SaaSDemoRequest).filter_by(request_uuid=request_uuid).one()
            organization = db.query(saas.models.PendingOrganization).filter_by(
                id=row.pending_organization_id
            ).one()
            account = db.query(saas.models.SaaSAccount).filter_by(
                id=row.requester_saas_account_id
            ).one()
            snapshot = json.loads(row.entitlement_snapshot_json)
            self.assertEqual(row.status, "pending_review")
            self.assertEqual(row.workspace_classification_snapshot, "customer_demo")
            self.assertEqual(row.commercial_state_snapshot, "provisioning")
            self.assertEqual(snapshot["resolution_status"], "not_provisioned")
            self.assertEqual(snapshot["configured_branch_count"], 2)
            self.assertEqual(organization.workspace_intent, "customer_demo")
            self.assertEqual(account.account_purpose, "customer")
            self.assertEqual(db.query(saas.models.SaaSDemoRequestEvent).count(), 2)
            self.assertEqual(db.query(saas.models.SaaSDemoEmailDelivery).filter_by(
                demo_request_id=row.id, email_type="request_received"
            ).count(), 1)
            self.assertEqual(db.query(models.SystemNotification).filter_by(
                request_type="saas_demo_submitted"
            ).count(), 1)
            self.assertEqual(db.query(saas.models.TenantProvisioningLink).count(), 0)
            self.assertEqual(db.query(saas.models.ProvisioningJob).count(), 0)
        finally:
            db.close()

        duplicate = self.client.post(
            f"/saas/onboarding/{organization_uuid}/commercial-choice/request-demo",
            follow_redirects=False,
        )
        self.assertEqual(duplicate.status_code, 302)
        self.assertIn("error=", duplicate.headers["location"])
        db = self._db()
        try:
            self.assertEqual(db.query(saas.models.SaaSDemoRequest).count(), 1)
        finally:
            db.close()

    def test_customer_visibility_and_pending_withdrawal(self):
        organization_uuid = self._complete_onboarding()
        request_uuid = self._submit_demo(organization_uuid)
        status_page = self.client.get(f"/saas/demo-requests/{request_uuid}")
        self.assertEqual(status_page.status_code, 200)
        self.assertIn("Pending Review", status_page.text)
        self.assertIn("Withdraw Request", status_page.text)

        other_client = TestClient(self.app)
        self.extra_clients.append(other_client)
        self._signup_verify_login(other_client, "other.customer@academy.edu")
        self.assertEqual(other_client.get(f"/saas/demo-requests/{request_uuid}").status_code, 404)

        withdrawn = self.client.post(
            f"/saas/demo-requests/{request_uuid}/withdraw",
            follow_redirects=False,
        )
        self.assertEqual(withdrawn.status_code, 302)
        db = self._db()
        try:
            row = db.query(saas.models.SaaSDemoRequest).filter_by(request_uuid=request_uuid).one()
            self.assertEqual(row.status, "cancelled")
            event_types = [
                event.event_type
                for event in db.query(saas.models.SaaSDemoRequestEvent).filter_by(
                    demo_request_id=row.id
                ).order_by(saas.models.SaaSDemoRequestEvent.id).all()
            ]
            self.assertIn("request_withdrawn", event_types)
            self.assertIn("request_cancelled", event_types)
        finally:
            db.close()
        repeated = self.client.post(
            f"/saas/demo-requests/{request_uuid}/withdraw",
            follow_redirects=False,
        )
        self.assertIn("error=", repeated.headers["location"])

    def test_platform_owner_approval_orchestrates_activation_and_is_terminal(self):
        organization_uuid = self._complete_onboarding()
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._platform_client()
        queue = owner.get("/saas-admin/demo-requests")
        self.assertEqual(queue.status_code, 200)
        self.assertIn("Demo Academy", queue.text)
        self.assertIn("Pending Review", queue.text)
        detail = owner.get(f"/saas-admin/demo-requests/{request_uuid}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Approve Request", detail.text)

        with patch("saas.router.audit.write_audit_event") as write_audit:
            approved = owner.post(
                f"/saas-admin/demo-requests/{request_uuid}/approve",
                follow_redirects=False,
            )
        self.assertEqual(approved.status_code, 302)
        self.assertEqual(write_audit.call_args.args[0]["result"], "success")
        db = self._db()
        try:
            row = db.query(saas.models.SaaSDemoRequest).filter_by(request_uuid=request_uuid).one()
            review = db.query(saas.models.SaaSDemoRequestReview).filter_by(
                demo_request_id=row.id
            ).one()
            self.assertEqual(row.status, "approved")
            self.assertEqual(review.decision, "approved")
            self.assertEqual(db.query(saas.models.TenantProvisioningLink).count(), 1)
            self.assertEqual(db.query(saas.models.ProvisioningJob).count(), 0)
            self.assertEqual(db.query(saas.models.SaaSDemoEmailDelivery).filter_by(
                demo_request_id=row.id, email_type="demo_approved"
            ).count(), 1)
        finally:
            db.close()
        blocked = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/reject",
            data={"reason": "Cannot change an approved request"},
            follow_redirects=False,
        )
        self.assertIn("error=", blocked.headers["location"])

    def test_rejection_requires_reason_and_customer_sees_reason(self):
        organization_uuid = self._complete_onboarding()
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._platform_client(user_id="9102")
        missing = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/reject",
            data={"reason": ""},
            follow_redirects=False,
        )
        self.assertIn("error=", missing.headers["location"])
        db = self._db()
        try:
            self.assertEqual(
                db.query(saas.models.SaaSDemoRequest).filter_by(request_uuid=request_uuid).one().status,
                "pending_review",
            )
        finally:
            db.close()
        reason = "The submitted branch scope requires clarification."
        rejected = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/reject",
            data={"reason": reason},
            follow_redirects=False,
        )
        self.assertEqual(rejected.status_code, 302)
        customer_page = self.client.get(f"/saas/demo-requests/{request_uuid}")
        self.assertIn("Rejected", customer_page.text)
        self.assertIn(reason, customer_page.text)
        self.assertNotIn("Withdraw Request", customer_page.text)

    def test_platform_cancellation_and_permission_guards(self):
        organization_uuid = self._complete_onboarding()
        request_uuid = self._submit_demo(organization_uuid)
        self.assertEqual(self.client.get("/saas-admin/demo-requests").status_code, 403)
        developer = self._platform_client(role=auth.PLATFORM_ROLE_DEVELOPER, user_id="9103")
        self.assertEqual(developer.get("/saas-admin/demo-requests").status_code, 403)
        owner = self._platform_client(user_id="9104")
        cancelled = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/cancel",
            follow_redirects=False,
        )
        self.assertEqual(cancelled.status_code, 302)
        db = self._db()
        try:
            row = db.query(saas.models.SaaSDemoRequest).filter_by(request_uuid=request_uuid).one()
            self.assertEqual(row.status, "cancelled")
            self.assertEqual(db.query(saas.models.SaaSDemoRequestReview).count(), 0)
        finally:
            db.close()

    def test_review_queue_search_filter_sort_and_empty_state(self):
        organization_uuid = self._complete_onboarding()
        self._submit_demo(organization_uuid)
        owner = self._platform_client(user_id="9105")
        filtered = owner.get(
            "/saas-admin/demo-requests?q=Demo+Academy&status=pending_review&sort=organization_asc"
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertIn("Demo Academy", filtered.text)
        self.assertIn("demo.requester@academy.edu", filtered.text)
        empty = owner.get("/saas-admin/demo-requests?q=Unrelated+Organization")
        self.assertEqual(empty.status_code, 200)
        self.assertIn("No demo requests found", empty.text)

    def test_landing_intent_survives_signup_and_is_emphasized_at_commercial_choice(self):
        organization_uuid = self._complete_onboarding(
            email="intent.demo@academy.edu",
            intent="demo",
        )
        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized="intent.demo@academy.edu"
            ).one()
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            self.assertEqual(account.signup_intent, "demo")
            self.assertEqual(organization.commercial_intent, "demo")
        finally:
            db.close()

        choice = self.client.get(
            f"/saas/onboarding/{organization_uuid}/commercial-choice"
        )
        self.assertEqual(choice.status_code, 200)
        self.assertIn("Selected from your TIS journey.", choice.text)
        self.assertIn("Request Demo", choice.text)
        self.assertIn("Subscribe Now", choice.text)

    def test_subscribe_intent_is_preserved_through_school_workspace_setup(self):
        organization_uuid = self._complete_onboarding(
            email="intent.subscribe@academy.edu",
            intent="subscribe",
        )
        db = self._db()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(
                email_normalized="intent.subscribe@academy.edu"
            ).one()
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            self.assertEqual(account.signup_intent, "subscribe")
            self.assertEqual(organization.commercial_intent, "subscribe")
        finally:
            db.close()

        choice = self.client.get(
            f"/saas/onboarding/{organization_uuid}/commercial-choice"
        )
        self.assertEqual(choice.status_code, 200)
        self.assertEqual(choice.text.count("Selected from your TIS journey."), 1)
        self.assertIn("Subscribe Now", choice.text)

    def test_demo_diagnostics_identify_existing_domain_reservation_lookup(self):
        organization_uuid = self._complete_onboarding(
            email="diagnostic.lookup@academy.edu",
            domain="diagnostic-lookup.example.edu",
        )
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            account = db.get(saas.models.SaaSAccount, organization.owner_saas_account_id)
            db.add(saas.models.SaaSDemoDomainEligibility(
                normalized_domain="diagnostic-lookup.example.edu",
                status="reserved",
            ))
            db.commit()
            with self.assertLogs("saas", level="INFO") as logs:
                with self.assertRaisesRegex(
                    demo_request_service.DemoRequestError,
                    "demo opportunity has already been used",
                ):
                    demo_request_service.submit_demo_request(db, account, organization)
            output = "\n".join(logs.output)
            self.assertIn("failure_stage=existing_eligibility_lookup", output)
            self.assertIn("matching_rows=", output)
            self.assertIn("link_state': 'detached'", output)
        finally:
            db.rollback()
            db.close()

    def test_demo_diagnostics_identify_eligibility_reservation_race(self):
        db = self._db()
        try:
            with self.assertLogs("saas", level="ERROR") as logs:
                with patch.object(
                    db,
                    "flush",
                    side_effect=IntegrityError(
                        "INSERT saas_demo_domain_eligibilities", {}, Exception("unique")
                    ),
                ):
                    with self.assertRaisesRegex(
                        demo_request_service.DemoRequestError,
                        "demo opportunity has already been used",
                    ):
                        demo_request_service._reserve_customer_demo_domain(
                            db, "diagnostic-race.example.edu"
                        )
            self.assertIn(
                "failure_stage=eligibility_reservation_insert_flush",
                "\n".join(logs.output),
            )
        finally:
            db.rollback()
            db.close()

    def test_demo_diagnostics_identify_demo_request_insert_failure(self):
        organization_uuid = self._complete_onboarding(
            email="diagnostic.request@academy.edu",
            domain="diagnostic-request.example.edu",
        )
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            account = db.get(saas.models.SaaSAccount, organization.owner_saas_account_id)
            with self.assertLogs("saas", level="ERROR") as logs:
                with patch(
                    "saas.demo_request_service._reserve_customer_demo_domain",
                    return_value=SimpleNamespace(demo_request_id=None),
                ), patch.object(
                    db,
                    "flush",
                    side_effect=IntegrityError(
                        "INSERT saas_demo_requests", {}, Exception("unique")
                    ),
                ):
                    with self.assertRaisesRegex(
                        demo_request_service.DemoRequestError,
                        "demo opportunity has already been used",
                    ):
                        demo_request_service.submit_demo_request(db, account, organization)
            self.assertIn(
                "failure_stage=demo_request_insert_flush",
                "\n".join(logs.output),
            )
        finally:
            db.rollback()
            db.close()

    def test_one_customer_demo_is_reserved_per_normalized_organization_domain(self):
        first_organization_uuid = self._complete_onboarding(
            email="principal@academy.edu",
            domain="demo-academy.example.com",
        )
        first_request_uuid = self._submit_demo(first_organization_uuid)

        second_client = TestClient(self.app)
        self.extra_clients.append(second_client)
        second_organization_uuid = self._complete_onboarding(
            email="ict@academy.edu",
            client=second_client,
            domain="demo-academy.example.com",
        )
        blocked = second_client.post(
            f"/saas/onboarding/{second_organization_uuid}/commercial-choice/request-demo",
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("error=", blocked.headers["location"])
        self.assertIn("demo+opportunity+has+already+been+used+or+requested", blocked.headers["location"])

        db = self._db()
        try:
            request_row = db.query(saas.models.SaaSDemoRequest).filter_by(
                request_uuid=first_request_uuid
            ).one()
            eligibility = db.query(saas.models.SaaSDemoDomainEligibility).filter_by(
                normalized_domain="demo-academy.example.com"
            ).one()
            self.assertEqual(request_row.organization_domain_normalized, "demo-academy.example.com")
            self.assertEqual(eligibility.demo_request_id, request_row.id)
            request_row.status = "approved"
            db.commit()
            self.assertEqual(
                db.query(saas.models.SaaSDemoDomainEligibility).filter_by(
                    normalized_domain="demo-academy.example.com"
                ).count(),
                1,
            )
        finally:
            db.close()

    def test_public_email_requires_an_official_organization_domain_for_demo(self):
        organization_uuid = self._complete_onboarding(
            email="principal@gmail.com"
        )
        db = self._db()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=organization_uuid
            ).one()
            organization.primary_domain = ""
            organization.website = ""
            db.commit()
        finally:
            db.close()

        blocked = self.client.post(
            f"/saas/onboarding/{organization_uuid}/commercial-choice/request-demo",
            follow_redirects=False,
        )
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("official+website+or+primary+domain", blocked.headers["location"])

    def test_domain_eligibility_database_unique_invariant_blocks_races(self):
        db = self._db()
        try:
            db.add(
                saas.models.SaaSDemoDomainEligibility(
                    normalized_domain="race.example.edu",
                    status="reserved",
                )
            )
            db.commit()
            db.add(
                saas.models.SaaSDemoDomainEligibility(
                    normalized_domain="race.example.edu",
                    status="reserved",
                )
            )
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()

    def test_organization_domain_normalization_is_case_whitespace_and_dot_safe(self):
        self.assertEqual(
            service.normalize_organization_domain("  .School.Example.EDU.  "),
            "school.example.edu",
        )
        self.assertEqual(
            service.normalize_organization_domain("HTTPS://School.Example.EDU/setup"),
            "school.example.edu",
        )

    def test_migration_constraints_and_idempotency(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE saas_demo_request_events"))
            connection.execute(text("DROP TABLE saas_demo_request_reviews"))
            connection.execute(text("DROP TABLE saas_demo_requests"))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE migration_id = '20260722_004_saas_demo_request_workflow'"
            ))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE migration_id = '20260725_001_demo_domain_eligibility_policy'"
            ))
        self.assertEqual(
            db_migrations.run_pending_migrations(self.engine),
            [
                "20260722_004_saas_demo_request_workflow",
                "20260725_001_demo_domain_eligibility_policy",
            ],
        )
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue({
            "saas_demo_requests",
            "saas_demo_request_reviews",
            "saas_demo_request_events",
        }.issubset(tables))
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])

        organization_uuid = self._complete_onboarding()
        request_uuid = self._submit_demo(organization_uuid)
        db = self._db()
        try:
            row = db.query(saas.models.SaaSDemoRequest).filter_by(request_uuid=request_uuid).one()
            duplicate = saas.models.SaaSDemoRequest(
                request_uuid="duplicate-pending-request-uuid-0001",
                requester_saas_account_id=row.requester_saas_account_id,
                pending_organization_id=row.pending_organization_id,
                workspace_classification_snapshot="customer_demo",
                commercial_state_snapshot="provisioning",
                entitlement_snapshot_json="{}",
                status="pending_review",
                submitted_at=datetime.utcnow(),
                status_updated_at=datetime.utcnow(),
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()

    def test_demo_workspace_approval_activates_without_billing_or_email(self):
        organization_uuid = self._complete_onboarding()
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._approve_demo(request_uuid, user_id="9191")

        with (
            patch("email_service.send_email") as send_email,
            patch("saas.paddle_client.create_transaction") as create_transaction,
        ):
            response = owner.post(
                f"/saas-admin/demo-requests/{request_uuid}/provision",
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("notice=", response.headers["location"])
        send_email.assert_not_called()
        create_transaction.assert_not_called()

        db = self._db()
        try:
            request_row = db.query(saas.models.SaaSDemoRequest).filter_by(
                request_uuid=request_uuid
            ).one()
            provisioning = db.query(saas.models.SaaSDemoWorkspaceProvisioning).filter_by(
                demo_request_id=request_row.id
            ).one()
            group = db.query(models.SchoolGroup).filter_by(
                id=request_row.school_group_id
            ).one()
            entitlement = db.query(saas.models.WorkspaceEntitlement).filter_by(
                school_group_id=group.id
            ).one()
            tenant_link = db.query(saas.models.TenantProvisioningLink).filter_by(
                pending_organization_id=request_row.pending_organization_id
            ).one()
            self.assertEqual(request_row.status, "approved")
            self.assertEqual(request_row.commercial_state_snapshot, "customer_demo_active")
            self.assertEqual(group.workspace_classification, "customer_demo")
            self.assertEqual(group.workspace_lifecycle_status, "active")
            self.assertEqual(entitlement.entitlement_type, "demo")
            self.assertEqual(entitlement.status, "active")
            self.assertEqual(entitlement.source, "platform")
            self.assertIsNone(entitlement.payment_subscription_id)
            self.assertEqual(tenant_link.demo_request_id, request_row.id)
            self.assertIsNone(tenant_link.subscription_contract_id)
            self.assertEqual(provisioning.provisioning_status, "active")
            self.assertEqual(provisioning.result_code, "demo_workspace_active")
            self.assertIsNotNone(provisioning.activated_at)
            self.assertEqual(
                db.query(models.Branch).filter_by(school_group_id=group.id).count(),
                2,
            )
            self.assertEqual(
                db.query(saas.models.SubscriptionContract).filter_by(
                    pending_organization_id=request_row.pending_organization_id
                ).count(),
                0,
            )
            self.assertEqual(db.query(saas.models.PaymentSubscription).count(), 0)
            self.assertEqual(db.query(saas.models.PaymentAttempt).count(), 0)
            self.assertEqual(db.query(saas.models.ProvisioningJob).count(), 0)
            resolution = commercial_state_service.resolve_commercial_state(db, group.id)
            self.assertTrue(resolution.resolved)
            self.assertEqual(resolution.commercial_state, "customer_demo_active")
            event_types = {
                row.event_type
                for row in db.query(saas.models.SaaSDemoProvisioningEvent).filter_by(
                    demo_provisioning_id=provisioning.id
                ).all()
            }
            self.assertEqual(
                event_types,
                {
                    "provisioning_started",
                    "provisioning_completed",
                    "activation_completed",
                },
            )
        finally:
            db.close()

        customer_page = self.client.get(f"/saas/demo-requests/{request_uuid}")
        self.assertIn("Demo Active", customer_page.text)
        self.assertIn("Enter TIS Platform", customer_page.text)
        account_page = self.client.get("/saas/account")
        self.assertIn('data-commercial-source="demo"', account_page.text)
        self.assertIn("Demo Access", account_page.text)
        self.assertIn("Active", account_page.text)
        self.assertNotIn("Continue to Secure Payment", account_page.text)
        owner_page = owner.get(f"/saas-admin/demo-requests/{request_uuid}")
        self.assertIn("Demo Active", owner_page.text)
        self.assertIn("Demo Workspace Active", owner_page.text)

    def test_demo_provisioning_rolls_back_and_retry_is_safe(self):
        organization_uuid = self._complete_onboarding("rollback.demo@academy.edu")
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._platform_client(user_id="9192")
        db = self._db()
        try:
            initial_group_count = db.query(models.SchoolGroup).count()
            initial_user_count = db.query(models.User).count()
            initial_entitlement_count = db.query(
                saas.models.WorkspaceEntitlement
            ).count()
            initial_tenant_link_count = db.query(
                saas.models.TenantProvisioningLink
            ).count()
            initial_account_link_count = db.query(
                saas.models.SaaSAccountUserLink
            ).count()
        finally:
            db.close()

        with patch(
            "saas.provisioning_service._create_branches",
            side_effect=ValueError("forced branch provisioning failure"),
        ):
            failed = owner.post(
                f"/saas-admin/demo-requests/{request_uuid}/approve",
                follow_redirects=False,
            )
        self.assertIn("error=", failed.headers["location"])
        db = self._db()
        try:
            request_row = db.query(saas.models.SaaSDemoRequest).filter_by(
                request_uuid=request_uuid
            ).one()
            provisioning = db.query(saas.models.SaaSDemoWorkspaceProvisioning).filter_by(
                demo_request_id=request_row.id
            ).one()
            self.assertEqual(request_row.status, "approved")
            self.assertIsNone(request_row.school_group_id)
            self.assertEqual(request_row.commercial_state_snapshot, "provisioning")
            self.assertEqual(provisioning.provisioning_status, "failed")
            self.assertEqual(provisioning.attempt_count, 1)
            self.assertIn("forced branch provisioning failure", provisioning.failure_reason)
            self.assertEqual(db.query(models.SchoolGroup).count(), initial_group_count)
            self.assertEqual(db.query(models.User).count(), initial_user_count)
            self.assertEqual(
                db.query(saas.models.WorkspaceEntitlement).count(),
                initial_entitlement_count,
            )
            self.assertEqual(
                db.query(saas.models.TenantProvisioningLink).count(),
                initial_tenant_link_count,
            )
            self.assertEqual(
                db.query(saas.models.SaaSAccountUserLink).count(),
                initial_account_link_count,
            )
            self.assertTrue(
                db.query(saas.models.SaaSDemoProvisioningEvent).filter_by(
                    demo_provisioning_id=provisioning.id,
                    event_type="provisioning_failed",
                    event_category="audit",
                ).one()
            )
        finally:
            db.close()

        customer_page = self.client.get(f"/saas/demo-requests/{request_uuid}")
        self.assertIn("Workspace Activation Needs Attention", customer_page.text)
        self.assertNotIn("forced branch provisioning failure", customer_page.text)
        owner_page = owner.get(f"/saas-admin/demo-requests/{request_uuid}")
        self.assertIn("forced branch provisioning failure", owner_page.text)
        retry = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/provision",
            follow_redirects=False,
        )
        self.assertIn("notice=", retry.headers["location"])
        db = self._db()
        try:
            provisioning = db.query(saas.models.SaaSDemoWorkspaceProvisioning).one()
            self.assertEqual(provisioning.provisioning_status, "active")
            self.assertEqual(provisioning.attempt_count, 2)
            self.assertEqual(db.query(saas.models.TenantProvisioningLink).count(), 1)
        finally:
            db.close()

    def test_demo_provisioning_validation_and_duplicate_guards(self):
        organization_uuid = self._complete_onboarding("guards.demo@academy.edu")
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._platform_client(user_id="9193")
        pending = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/provision",
            follow_redirects=False,
        )
        self.assertIn("error=", pending.headers["location"])
        db = self._db()
        try:
            self.assertEqual(db.query(saas.models.SaaSDemoWorkspaceProvisioning).count(), 0)
        finally:
            db.close()

        owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/approve",
            follow_redirects=False,
        )
        db = self._db()
        try:
            request_row = db.query(saas.models.SaaSDemoRequest).filter_by(
                request_uuid=request_uuid
            ).one()
            request_row.workspace_classification_snapshot = "customer_paid"
            db.commit()
        finally:
            db.close()
        wrong_classification = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/provision",
            follow_redirects=False,
        )
        self.assertIn("error=", wrong_classification.headers["location"])
        db = self._db()
        try:
            request_row = db.query(saas.models.SaaSDemoRequest).filter_by(
                request_uuid=request_uuid
            ).one()
            request_row.workspace_classification_snapshot = "customer_demo"
            db.commit()
        finally:
            db.close()

        first = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/provision",
            follow_redirects=False,
        )
        self.assertIn("notice=", first.headers["location"])
        db = self._db()
        try:
            counts_before = (
                db.query(models.SchoolGroup).count(),
                db.query(saas.models.WorkspaceEntitlement).count(),
                db.query(saas.models.TenantProvisioningLink).count(),
                db.query(saas.models.SaaSDemoWorkspaceProvisioning).count(),
            )
        finally:
            db.close()
        duplicate = owner.post(
            f"/saas-admin/demo-requests/{request_uuid}/provision",
            follow_redirects=False,
        )
        self.assertIn("notice=", duplicate.headers["location"])
        db = self._db()
        try:
            self.assertEqual(
                (
                    db.query(models.SchoolGroup).count(),
                    db.query(saas.models.WorkspaceEntitlement).count(),
                    db.query(saas.models.TenantProvisioningLink).count(),
                    db.query(saas.models.SaaSDemoWorkspaceProvisioning).count(),
                ),
                counts_before,
            )
        finally:
            db.close()

    def test_demo_provisioning_is_platform_owner_only(self):
        organization_uuid = self._complete_onboarding("permissions.demo@academy.edu")
        request_uuid = self._submit_demo(organization_uuid)
        owner = self._approve_demo(request_uuid, user_id="9194")
        self.assertEqual(
            self.client.post(
                f"/saas-admin/demo-requests/{request_uuid}/provision",
                follow_redirects=False,
            ).status_code,
            403,
        )
        developer = self._platform_client(
            role=auth.PLATFORM_ROLE_DEVELOPER,
            user_id="DEV9195",
        )
        self.assertEqual(
            developer.post(
                f"/saas-admin/demo-requests/{request_uuid}/provision",
                follow_redirects=False,
            ).status_code,
            403,
        )
        self.assertIn(
            "notice=",
            owner.post(
                f"/saas-admin/demo-requests/{request_uuid}/provision",
                follow_redirects=False,
            ).headers["location"],
        )

    def test_m8b4_migration_generalizes_existing_paid_tenant_links(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE saas_demo_provisioning_events"))
            connection.execute(text("DROP TABLE saas_demo_workspace_provisioning"))
            connection.execute(text("DROP TABLE tenant_provisioning_links"))
            connection.execute(text(
                """
                CREATE TABLE tenant_provisioning_links (
                    id INTEGER PRIMARY KEY,
                    pending_organization_id INTEGER NOT NULL,
                    subscription_contract_id INTEGER NOT NULL,
                    school_group_id INTEGER NOT NULL,
                    owner_operational_user_id INTEGER NOT NULL,
                    primary_branch_id INTEGER,
                    primary_academic_year_id INTEGER,
                    tenant_status VARCHAR(30) NOT NULL DEFAULT 'tenant_active',
                    activated_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE migration_id = '20260723_001_demo_workspace_provisioning'"
            ))
        self.assertEqual(
            db_migrations.run_pending_migrations(self.engine),
            ["20260723_001_demo_workspace_provisioning"],
        )
        columns = {
            column["name"]: column
            for column in inspect(self.engine).get_columns("tenant_provisioning_links")
        }
        self.assertIn("demo_request_id", columns)
        self.assertTrue(columns["subscription_contract_id"]["nullable"])
        self.assertTrue({
            "saas_demo_workspace_provisioning",
            "saas_demo_provisioning_events",
        }.issubset(set(inspect(self.engine).get_table_names())))
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])

    def test_demo_lifecycle_uses_exact_activation_based_dates_and_timezone(self):
        fixture = self._activate_demo()
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            started = demo_lifecycle_service.as_utc(provisioning.activated_at)
            reminder = demo_lifecycle_service.as_utc(provisioning.reminder_due_at)
            expires = demo_lifecycle_service.as_utc(provisioning.demo_expires_at)
            self.assertEqual(reminder - started, timedelta(days=6))
            self.assertEqual(expires - started, timedelta(days=7))
            resolution = demo_lifecycle_service.resolve_demo_lifecycle(
                db,
                provisioning=provisioning,
                observed_at=started + timedelta(days=5),
            )
            self.assertTrue(resolution.resolved)
            self.assertEqual(resolution.lifecycle_state, "active")
            self.assertEqual(resolution.timezone_name, "Asia/Beirut")
            self.assertEqual(
                resolution.display_expires_at.utcoffset(),
                timedelta(hours=3),
            )
            reminder_resolution = demo_lifecycle_service.resolve_demo_lifecycle(
                db,
                provisioning=provisioning,
                observed_at=started + timedelta(days=6),
            )
            self.assertEqual(reminder_resolution.lifecycle_state, "reminder_due")
        finally:
            db.close()

    def test_active_demo_resolves_as_explicitly_unmetered_commercial_authority(self):
        fixture = self._activate_demo(
            email="authority.demo@academy.edu",
            owner_user_id="9188",
        )
        db = self._db()
        try:
            authority = commercial_authority_service.resolve_commercial_authority(
                db, fixture["school_group_id"]
            )
            self.assertTrue(authority.resolved)
            self.assertTrue(authority.access_allowed)
            self.assertEqual(authority.source, "demo")
            self.assertTrue(authority.limits.unmetered)
        finally:
            db.close()

    def test_day_six_reminder_is_dry_run_safe_and_idempotent(self):
        fixture = self._activate_demo(
            email="reminder.demo@academy.edu",
            owner_user_id="9181",
        )
        observed = demo_lifecycle_service.utc_now()
        self._set_demo_started_at(fixture, observed - timedelta(days=6))

        dry_run = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=True,
            observed_at=observed,
        )
        self.assertEqual(dry_run.reminders_due, 1)
        db = self._db()
        try:
            self.assertEqual(db.query(saas.models.SaaSDemoLifecycleEvent).count(), 0)
            self.assertEqual(
                db.query(saas.models.SaaSDemoLifecycleNotification).count(),
                0,
            )
        finally:
            db.close()

        applied = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed,
        )
        self.assertEqual(applied.reminders_created, 1)
        repeated = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed + timedelta(minutes=5),
        )
        self.assertEqual(repeated.reminders_created, 0)
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            self.assertIsNotNone(provisioning.reminder_sent_at)
            self.assertEqual(
                db.query(saas.models.SaaSDemoLifecycleNotification).count(),
                2,
            )
            self.assertEqual(
                {
                    row.recipient_type
                    for row in db.query(
                        saas.models.SaaSDemoLifecycleNotification
                    ).all()
                },
                {"saas_account", "platform_owner"},
            )
            self.assertEqual(
                db.query(saas.models.SaaSDemoLifecycleEvent).filter(
                    saas.models.SaaSDemoLifecycleEvent.event_type.in_(
                        ("reminder_became_due", "reminder_notification_created")
                    )
                ).count(),
                2,
            )
        finally:
            db.close()
        customer_page = self.client.get(
            f"/saas/demo-requests/{fixture['request_uuid']}"
        )
        self.assertIn("Your TIS demo expires soon", customer_page.text)
        self.assertIn("workspace data will be preserved", customer_page.text)

    def test_day_seven_expiration_is_idempotent_and_preserves_tenant_data(self):
        fixture = self._activate_demo(
            email="expiration.demo@academy.edu",
            owner_user_id="9182",
        )
        observed = demo_lifecycle_service.utc_now()
        self._set_demo_started_at(fixture, observed - timedelta(days=7))
        db = self._db()
        try:
            counts_before = (
                db.query(models.Branch).filter_by(
                    school_group_id=fixture["school_group_id"]
                ).count(),
                db.query(models.User).filter_by(
                    school_group_id=fixture["school_group_id"]
                ).count(),
                db.query(saas.models.SaaSAccountUserLink).filter_by(
                    school_group_id=fixture["school_group_id"]
                ).count(),
            )
        finally:
            db.close()

        applied = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed,
        )
        self.assertEqual(applied.expired, 1)
        repeated = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed + timedelta(hours=1),
        )
        self.assertEqual(repeated.expired, 0)
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            group = db.get(models.SchoolGroup, fixture["school_group_id"])
            entitlement = db.get(
                saas.models.WorkspaceEntitlement,
                fixture["entitlement_id"],
            )
            tenant_link = db.get(
                saas.models.TenantProvisioningLink,
                fixture["tenant_link_id"],
            )
            request_row = db.get(
                saas.models.SaaSDemoRequest,
                fixture["request_id"],
            )
            self.assertEqual(group.workspace_lifecycle_status, "suspended")
            self.assertEqual(entitlement.status, "ended")
            self.assertEqual(tenant_link.tenant_status, "demo_expired")
            self.assertEqual(request_row.commercial_state_snapshot, "suspended")
            self.assertEqual(provisioning.lifecycle_processing_status, "expired")
            self.assertEqual(
                demo_lifecycle_service.as_utc(provisioning.expired_at),
                demo_lifecycle_service.as_utc(provisioning.demo_expires_at),
            )
            self.assertEqual(
                (
                    db.query(models.Branch).filter_by(
                        school_group_id=fixture["school_group_id"]
                    ).count(),
                    db.query(models.User).filter_by(
                        school_group_id=fixture["school_group_id"]
                    ).count(),
                    db.query(saas.models.SaaSAccountUserLink).filter_by(
                        school_group_id=fixture["school_group_id"]
                    ).count(),
                ),
                counts_before,
            )
            self.assertEqual(
                db.query(saas.models.SaaSDemoLifecycleEvent).filter_by(
                    event_type="demo_expired"
                ).count(),
                1,
            )
        finally:
            db.close()

        customer_page = self.client.get(
            f"/saas/demo-requests/{fixture['request_uuid']}"
        )
        self.assertIn("Demo Expired", customer_page.text)
        self.assertIn("Subscribe Now", customer_page.text)
        self.assertIn("tenant data remain preserved", customer_page.text)
        owner_page = fixture["owner_client"].get(
            f"/saas-admin/demo-requests/{fixture['request_uuid']}"
        )
        self.assertIn("Demo Lifecycle", owner_page.text)
        self.assertIn("Workspace Suspended", owner_page.text)
        self.assertIn("Expired", owner_page.text)

    def test_expiration_rolls_back_atomically_and_retry_succeeds(self):
        fixture = self._activate_demo(
            email="retry.lifecycle@academy.edu",
            owner_user_id="9183",
        )
        observed = demo_lifecycle_service.utc_now()
        self._set_demo_started_at(fixture, observed - timedelta(days=7))
        with patch(
            "saas.demo_lifecycle_service.commercial_state_service.resolve_commercial_state",
            side_effect=RuntimeError("forced lifecycle verification failure"),
        ):
            failed = demo_lifecycle_service.process_due_demo_lifecycles(
                self.Session,
                dry_run=False,
                observed_at=observed,
            )
        self.assertEqual(failed.failed, 1)
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            self.assertEqual(provisioning.lifecycle_processing_status, "failed")
            self.assertEqual(
                db.get(models.SchoolGroup, fixture["school_group_id"]).workspace_lifecycle_status,
                "active",
            )
            self.assertEqual(
                db.get(
                    saas.models.WorkspaceEntitlement,
                    fixture["entitlement_id"],
                ).status,
                "active",
            )
            self.assertIsNone(provisioning.expired_at)
            self.assertEqual(
                db.query(saas.models.SaaSDemoLifecycleEvent).filter_by(
                    event_type="lifecycle_processing_failed"
                ).count(),
                1,
            )
        finally:
            db.close()
        retried = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed + timedelta(minutes=1),
        )
        self.assertEqual(retried.expired, 1)

    def test_demo_access_enforcement_blocks_web_api_and_existing_session(self):
        fixture = self._activate_demo(
            email="access.lifecycle@academy.edu",
            owner_user_id="9184",
        )
        db = self._db()
        try:
            user = db.get(models.User, fixture["operational_user_id"])
            user.scope_school_group_id = fixture["school_group_id"]
            self.assertIsNone(
                authorization.enforce_workspace_commercial_access(
                    self._request("/dashboard"),
                    db,
                    current_user=user,
                )
            )
            shell = ui_shell.build_shell_context(
                self._request("/dashboard"), db, user, page_key="dashboard"
            )["shell"]
            self.assertEqual(shell["demo_workspace"]["label"], "Demo Workspace")
            self.assertIn("Expires in", shell["demo_workspace"]["remaining_label"])
        finally:
            db.close()
        observed = demo_lifecycle_service.utc_now()
        self._set_demo_started_at(fixture, observed - timedelta(days=7))
        demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed,
        )
        db = self._db()
        try:
            user = db.get(models.User, fixture["operational_user_id"])
            user.scope_school_group_id = fixture["school_group_id"]
            web_response = authorization.enforce_workspace_commercial_access(
                self._request("/dashboard"),
                db,
                current_user=user,
            )
            self.assertEqual(web_response.status_code, 302)
            self.assertIn("/demo-expired", web_response.headers["location"])
            api_response = authorization.enforce_workspace_commercial_access(
                self._request(
                    "/dashboard/api/hiring-plan",
                    accept="application/json",
                ),
                db,
                current_user=user,
            )
            self.assertEqual(api_response.status_code, 403)
            self.assertIn(
                b'"code":"commercial_access_unavailable"', api_response.body
            )
            self.assertNotIn(b'"code":"demo_expired"', api_response.body)
            self.assertEqual(
                db.query(saas.models.SaaSDemoLifecycleEvent).filter_by(
                    event_type="access_blocked"
                ).count(),
                1,
            )
        finally:
            db.close()

    def test_internal_sandbox_bypasses_access_enforcement_but_unlinked_paid_fails_closed(self):
        db = self._db()
        try:
            for index, classification in enumerate(
                ("customer_paid", "internal_sandbox"),
                start=1,
            ):
                group = models.SchoolGroup(
                    name=f"Non Demo {index}",
                    workspace_uuid=f"00000000-0000-0000-0000-{index:012d}",
                    workspace_classification=classification,
                    workspace_lifecycle_status="active",
                    status=True,
                )
                db.add(group)
                db.flush()
                user = SimpleNamespace(
                    user_type=auth.USER_TYPE_TENANT,
                    school_group_id=group.id,
                    scope_school_group_id=group.id,
                )
                response = authorization.enforce_workspace_commercial_access(
                    self._request("/dashboard"),
                    db,
                    current_user=user,
                )
                if classification == "customer_paid":
                    self.assertIsNotNone(response)
                    self.assertEqual(response.status_code, 302)
                else:
                    self.assertIsNone(response)
            db.rollback()
        finally:
            db.close()

    def test_inconsistent_demo_lifecycle_fails_closed_without_diagnostics(self):
        fixture = self._activate_demo(
            email="manual.review.lifecycle@academy.edu",
            owner_user_id="9186",
        )
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            provisioning.demo_expires_at = (
                provisioning.activated_at + timedelta(days=8)
            )
            db.commit()
            resolution = demo_lifecycle_service.resolve_demo_lifecycle(
                db,
                provisioning=provisioning,
            )
            self.assertEqual(resolution.lifecycle_state, "manual_review")
            self.assertEqual(
                resolution.reason_code,
                "inconsistent_demo_lifecycle_timestamps",
            )
            user = db.get(models.User, fixture["operational_user_id"])
            user.scope_school_group_id = fixture["school_group_id"]
            response = authorization.enforce_workspace_commercial_access(
                self._request("/dashboard/api/hiring-plan", accept="application/json"),
                db,
                current_user=user,
            )
            self.assertEqual(response.status_code, 403)
            self.assertIn(
                b'"code":"commercial_access_unavailable"', response.body
            )
            self.assertNotIn(b'"code":"demo_access_unavailable"', response.body)
            self.assertNotIn(b"inconsistent_demo_lifecycle_timestamps", response.body)
        finally:
            db.close()

    def test_active_demo_can_enter_subscription_path_without_reprovisioning(self):
        fixture = self._activate_demo(
            email="conversion.checkout@academy.edu",
            owner_user_id="9187",
        )
        page = self.client.get(
            f"/saas/demo-requests/{fixture['request_uuid']}"
        )
        self.assertEqual(page.status_code, 200)
        self.assertIn("Subscribe Now", page.text)
        response = self.client.post(
            f"/saas/onboarding/{fixture['organization_uuid']}/commercial-choice/subscribe",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            f"/saas/onboarding/{fixture['organization_uuid']}/plan",
        )
        db = self._db()
        try:
            conversion = db.query(
                saas.models.SaaSDemoToPaidConversion
            ).one()
            self.assertEqual(conversion.status, "requested")
            self.assertEqual(conversion.school_group_id, fixture["school_group_id"])
            self.assertFalse(
                service.initial_checkout_is_closed(
                    db,
                    db.get(
                        saas.models.PendingOrganization,
                        conversion.pending_organization_id,
                    ),
                )
            )
            self.assertEqual(
                db.query(saas.models.SaaSDemoConversionEvent).filter_by(
                    event_type="conversion_requested"
                ).count(),
                2,
            )
            self.assertEqual(db.query(saas.models.ProvisioningJob).count(), 0)
        finally:
            db.close()

    def test_successful_conversion_preserves_tenant_and_resolves_paid_access(self):
        fixture = self._activate_demo(
            email="conversion.success@academy.edu",
            owner_user_id="9188",
        )
        db = self._db()
        try:
            group = db.get(models.SchoolGroup, fixture["school_group_id"])
            branches = db.query(models.Branch).filter_by(
                school_group_id=group.id
            ).order_by(models.Branch.id).all()
            academic_year = db.query(models.AcademicYear).filter_by(
                school_group_id=group.id
            ).one()
            subject = models.Subject(
                subject_code="M8B6-MATH",
                subject_name="Conversion Mathematics",
                branch_id=branches[0].id,
                academic_year_id=academic_year.id,
            )
            branch_entitlement = saas.models.BranchEntitlement(
                school_group_id=group.id,
                branch_id=branches[0].id,
                workspace_entitlement_id=fixture["entitlement_id"],
                entitlement_mode="inherit",
            )
            db.add_all([subject, branch_entitlement])
            db.commit()
            preserved = {
                "workspace_uuid": group.workspace_uuid,
                "group_name": group.name,
                "branch_ids": tuple(row.id for row in branches),
                "user_ids": tuple(
                    row[0]
                    for row in db.query(models.User.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.User.id).all()
                ),
                "permission_ids": tuple(
                    row[0]
                    for row in db.query(models.RolePermission.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.RolePermission.id).all()
                ),
                "academic_year_ids": tuple(
                    row[0]
                    for row in db.query(models.AcademicYear.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.AcademicYear.id).all()
                ),
                "subject_id": subject.id,
                "tenant_link_id": fixture["tenant_link_id"],
                "group_count": db.query(models.SchoolGroup).count(),
            }
        finally:
            db.close()
        commercial = self._confirmed_subscription_for_demo(fixture)
        outcome = self._convert_demo(fixture, commercial)
        self.assertTrue(outcome.completed)

        db = self._db()
        try:
            group = db.get(models.SchoolGroup, fixture["school_group_id"])
            conversion = db.get(
                saas.models.SaaSDemoToPaidConversion,
                commercial["conversion_id"],
            )
            tenant_link = db.get(
                saas.models.TenantProvisioningLink,
                fixture["tenant_link_id"],
            )
            contract = db.get(
                saas.models.SubscriptionContract,
                commercial["contract_id"],
            )
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            demo_entitlement = db.get(
                saas.models.WorkspaceEntitlement,
                fixture["entitlement_id"],
            )
            paid_entitlement = db.get(
                saas.models.WorkspaceEntitlement,
                conversion.paid_workspace_entitlement_id,
            )
            self.assertEqual(group.workspace_classification, "customer_paid")
            self.assertEqual(group.workspace_lifecycle_status, "active")
            self.assertEqual(group.workspace_uuid, preserved["workspace_uuid"])
            self.assertEqual(group.name, preserved["group_name"])
            self.assertEqual(
                db.query(models.SchoolGroup).count(),
                preserved["group_count"],
            )
            self.assertEqual(
                tuple(
                    row[0]
                    for row in db.query(models.Branch.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.Branch.id).all()
                ),
                preserved["branch_ids"],
            )
            self.assertEqual(
                tuple(
                    row[0]
                    for row in db.query(models.User.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.User.id).all()
                ),
                preserved["user_ids"],
            )
            self.assertEqual(
                tuple(
                    row[0]
                    for row in db.query(models.RolePermission.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.RolePermission.id).all()
                ),
                preserved["permission_ids"],
            )
            self.assertEqual(
                tuple(
                    row[0]
                    for row in db.query(models.AcademicYear.id).filter_by(
                        school_group_id=group.id
                    ).order_by(models.AcademicYear.id).all()
                ),
                preserved["academic_year_ids"],
            )
            self.assertIsNotNone(db.get(models.Subject, preserved["subject_id"]))
            self.assertEqual(tenant_link.id, preserved["tenant_link_id"])
            self.assertIsNone(tenant_link.demo_request_id)
            self.assertEqual(tenant_link.subscription_contract_id, contract.id)
            self.assertEqual(contract.school_group_id, group.id)
            self.assertEqual(contract.contract_status, "tenant_active")
            self.assertEqual(demo_entitlement.status, "ended")
            self.assertEqual(paid_entitlement.status, "active")
            self.assertEqual(paid_entitlement.entitlement_type, "paid")
            self.assertEqual(
                paid_entitlement.payment_subscription_id,
                commercial["subscription_id"],
            )
            self.assertEqual(
                db.query(saas.models.BranchEntitlement).one().workspace_entitlement_id,
                paid_entitlement.id,
            )
            self.assertEqual(provisioning.lifecycle_processing_status, "converted")
            self.assertEqual(conversion.status, "completed")
            self.assertEqual(
                db.get(
                    saas.models.SaaSDemoRequest,
                    fixture["request_id"],
                ).workspace_classification_snapshot,
                "customer_demo",
            )
            paid = entitlement_service.resolve_entitlements(db, group.id)
            workspace = workspace_entitlement_service.resolve_workspace_entitlement(
                db, group.id
            )
            state = commercial_state_service.resolve_commercial_state(db, group.id)
            self.assertTrue(paid.resolved)
            self.assertEqual(paid.subscription_id, commercial["subscription_id"])
            self.assertEqual(workspace.entitlement_type, "paid")
            self.assertEqual(state.commercial_state, "customer_paid_active")
            self.assertEqual(
                {
                    row[0]
                    for row in db.query(
                        saas.models.SaaSDemoConversionEvent.event_type
                    ).all()
                },
                {
                    "conversion_requested",
                    "conversion_started",
                    "conversion_completed",
                },
            )
        finally:
            db.close()

        repeated = self._convert_demo(fixture, commercial)
        self.assertTrue(repeated.completed)
        result = demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=demo_lifecycle_service.utc_now() + timedelta(days=8),
        )
        self.assertEqual(result.scanned, 0)
        customer_page = self.client.get(
            f"/saas/demo-requests/{fixture['request_uuid']}"
        )
        self.assertIn("Subscription Active", customer_page.text)
        self.assertIn("No workspace or data was recreated", customer_page.text)
        owner_page = fixture["owner_client"].get(
            f"/saas-admin/demo-requests/{fixture['request_uuid']}"
        )
        self.assertIn("Demo-to-Paid Conversion", owner_page.text)
        self.assertIn("Converted", owner_page.text)
        self.assertIn("Conversion History", owner_page.text)

    def test_conversion_failure_rolls_back_demo_and_allows_retry(self):
        fixture = self._activate_demo(
            email="conversion.rollback@academy.edu",
            owner_user_id="9189",
        )
        commercial = self._confirmed_subscription_for_demo(fixture)
        unresolved = SimpleNamespace(
            resolved=False,
            commercial_state="manual_review",
        )
        with patch(
            "saas.demo_conversion_service.commercial_state_service.resolve_commercial_state",
            return_value=unresolved,
        ):
            outcome = self._convert_demo(fixture, commercial)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason_code, "paid_commercial_validation_failed")

        db = self._db()
        try:
            group = db.get(models.SchoolGroup, fixture["school_group_id"])
            link = db.get(
                saas.models.TenantProvisioningLink,
                fixture["tenant_link_id"],
            )
            demo_entitlement = db.get(
                saas.models.WorkspaceEntitlement,
                fixture["entitlement_id"],
            )
            conversion = db.get(
                saas.models.SaaSDemoToPaidConversion,
                commercial["conversion_id"],
            )
            self.assertEqual(group.workspace_classification, "customer_demo")
            self.assertEqual(link.demo_request_id, fixture["request_id"])
            self.assertIsNone(link.subscription_contract_id)
            self.assertEqual(demo_entitlement.status, "active")
            self.assertEqual(
                db.query(saas.models.WorkspaceEntitlement).filter_by(
                    entitlement_type="paid"
                ).count(),
                0,
            )
            self.assertEqual(
                db.get(
                    saas.models.PaymentSubscription,
                    commercial["subscription_id"],
                ).status,
                "active",
            )
            self.assertEqual(conversion.status, "failed")
            self.assertEqual(
                db.query(saas.models.SaaSDemoConversionEvent).filter_by(
                    event_type="conversion_failed"
                ).count(),
                2,
            )
        finally:
            db.close()

        retried = self._convert_demo(fixture, commercial)
        self.assertTrue(retried.completed)

    def test_conversion_accepts_expired_demo_and_rejects_unconfirmed_subscription(self):
        expired = self._activate_demo(
            email="conversion.expired@academy.edu",
            owner_user_id="9191",
        )
        expired_commercial = self._confirmed_subscription_for_demo(expired)
        observed = demo_lifecycle_service.utc_now()
        self._set_demo_started_at(expired, observed - timedelta(days=8))
        demo_lifecycle_service.process_due_demo_lifecycles(
            self.Session,
            dry_run=False,
            observed_at=observed,
        )
        expired_outcome = self._convert_demo(expired, expired_commercial)
        self.assertEqual(expired_outcome.status, "completed")

        pending = self._activate_demo(
            email="conversion.pending@academy.edu",
            owner_user_id="PEND9192",
        )
        pending_commercial = self._confirmed_subscription_for_demo(
            pending,
            status="pending",
        )
        pending_outcome = self._convert_demo(pending, pending_commercial)
        self.assertEqual(pending_outcome.status, "failed")
        self.assertEqual(
            pending_outcome.reason_code,
            "subscription_not_confirmed_active",
        )
        db = self._db()
        try:
            self.assertEqual(
                db.get(models.SchoolGroup, pending["school_group_id"]).workspace_classification,
                "customer_demo",
            )
            self.assertEqual(
                db.get(
                    saas.models.SaaSDemoWorkspaceProvisioning,
                    pending["provisioning_id"],
                ).lifecycle_processing_status,
                "pending",
            )
        finally:
            db.close()

    def test_conversion_rejects_cross_tenant_subscription_and_other_classifications(self):
        fixture = self._activate_demo(
            email="conversion.tenant@academy.edu",
            owner_user_id="9193",
        )
        commercial = self._confirmed_subscription_for_demo(fixture)
        db = self._db()
        try:
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email="unrelated.conversion@example.com",
                email_normalized="unrelated.conversion@example.com",
                status="active",
            )
            db.add(account)
            db.flush()
            unrelated = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=account.id,
                organization_name="Unrelated Conversion Organization",
            )
            db.add(unrelated)
            db.flush()
            subscription = db.get(
                saas.models.PaymentSubscription,
                commercial["subscription_id"],
            )
            subscription.pending_organization_id = unrelated.id
            db.commit()
        finally:
            db.close()
        outcome = self._convert_demo(fixture, commercial)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason_code, "subscription_organization_mismatch")
        with self.assertRaises(
            workspace_classification_service.WorkspaceClassificationTransitionError
        ):
            workspace_classification_service.validate_classification_transition(
                "internal_sandbox",
                "customer_paid",
            )
        self.assertEqual(
            workspace_classification_service.validate_classification_transition(
                "customer_demo",
                "customer_paid",
            ).value,
            "customer_paid",
        )

    def test_m8b6_migration_creates_conversion_ledger_and_is_idempotent(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE saas_demo_conversion_events"))
            connection.execute(text("DROP TABLE saas_demo_to_paid_conversions"))
            connection.execute(
                text(
                    "DELETE FROM schema_migrations "
                    "WHERE migration_id = '20260723_003_demo_to_paid_conversion'"
                )
            )
        self.assertEqual(
            db_migrations.run_pending_migrations(self.engine),
            ["20260723_003_demo_to_paid_conversion"],
        )
        self.assertTrue(
            {
                "saas_demo_to_paid_conversions",
                "saas_demo_conversion_events",
            }.issubset(set(inspect(self.engine).get_table_names()))
        )
        fixture = self._activate_demo(
            email="conversion.migration@academy.edu",
            owner_user_id="9194",
        )
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            provisioning.lifecycle_processing_status = "converted"
            db.commit()
            provisioning.lifecycle_processing_status = "unsupported"
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])

    def test_m8b5_migration_backfills_lifecycle_dates_and_is_idempotent(self):
        fixture = self._activate_demo(
            email="migration.lifecycle@academy.edu",
            owner_user_id="9185",
        )
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            started = demo_lifecycle_service.as_utc(provisioning.activated_at)
            provisioning.reminder_due_at = None
            provisioning.demo_expires_at = None
            db.commit()
        finally:
            db.close()
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE saas_demo_lifecycle_notifications"))
            connection.execute(text("DROP TABLE saas_demo_lifecycle_events"))
            connection.execute(text(
                "DELETE FROM schema_migrations "
                "WHERE migration_id = '20260723_002_demo_workspace_lifecycle'"
            ))
        self.assertEqual(
            db_migrations.run_pending_migrations(self.engine),
            ["20260723_002_demo_workspace_lifecycle"],
        )
        db = self._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            self.assertLessEqual(
                abs(
                    (
                        demo_lifecycle_service.as_utc(provisioning.reminder_due_at)
                        - (started + timedelta(days=6))
                    ).total_seconds()
                ),
                1,
            )
            self.assertLessEqual(
                abs(
                    (
                        demo_lifecycle_service.as_utc(provisioning.demo_expires_at)
                        - (started + timedelta(days=7))
                    ).total_seconds()
                ),
                1,
            )
        finally:
            db.close()
        self.assertTrue({
            "saas_demo_lifecycle_events",
            "saas_demo_lifecycle_notifications",
        }.issubset(set(inspect(self.engine).get_table_names())))
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])


if __name__ == "__main__":
    unittest.main()
