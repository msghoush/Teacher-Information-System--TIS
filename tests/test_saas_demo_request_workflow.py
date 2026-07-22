import json
import os
import re
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["TIS_SESSION_SECRET"] = "unit-test-session-secret-that-is-long-enough"

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db_migrations
import models
import saas.models
from dependencies import get_db
from saas import demo_request_service
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

    def _signup_verify_login(self, client: TestClient, email: str):
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

    def _complete_onboarding(self, email: str = "demo.requester@academy.edu") -> str:
        self._signup_verify_login(self.client, email)
        self.assertEqual(
            self.client.post("/saas/onboarding/start", follow_redirects=False).status_code,
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
        self.client.post(
            f"/saas/onboarding/{organization_uuid}/organization",
            data={
                "organization_name": "Demo Academy",
                "legal_name": "Demo Academy Legal",
                "website": "https://demo-academy.example.com",
                "primary_domain": "demo-academy.example.com",
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
                "estimated_staff_users": "24",
                "timezone": "Asia/Beirut",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.client.post(
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
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.client.post(
            f"/saas/onboarding/{organization_uuid}/academic_setup",
            data={
                "first_academic_year_name": "2026-2027",
                "create_default_branch": "1",
                "notes": "Demo review setup",
                "save_action": "continue",
            },
            follow_redirects=False,
        )
        self.client.post(
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
        submitted = self.client.post(
            f"/saas/onboarding/{organization_uuid}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 302)
        self.assertEqual(
            submitted.headers["location"],
            f"/saas/onboarding/{organization_uuid}/commercial-choice",
        )
        return organization_uuid

    def _submit_demo(self, organization_uuid: str):
        response = self.client.post(
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

    def test_platform_owner_approval_records_decision_only_and_is_terminal(self):
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
        self.assertIn("provisions or activates a workspace", detail.text)

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
            self.assertEqual(db.query(saas.models.TenantProvisioningLink).count(), 0)
            self.assertEqual(db.query(saas.models.ProvisioningJob).count(), 0)
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

    def test_migration_constraints_and_idempotency(self):
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE saas_demo_request_events"))
            connection.execute(text("DROP TABLE saas_demo_request_reviews"))
            connection.execute(text("DROP TABLE saas_demo_requests"))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE migration_id = '20260722_004_saas_demo_request_workflow'"
            ))
        self.assertEqual(
            db_migrations.run_pending_migrations(self.engine),
            ["20260722_004_saas_demo_request_workflow"],
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


if __name__ == "__main__":
    unittest.main()
