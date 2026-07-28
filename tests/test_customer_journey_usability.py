import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import auth
import authorization
import models
import saas.models
from fastapi.testclient import TestClient
from dependencies import get_db
from saas import (
    commercial_access_service,
    customer_journey_service,
    demo_email_service,
    demo_lifecycle_service,
)


ROOT = Path(__file__).resolve().parents[1]


class TestCustomerJourneyUsability:
    def setup_method(self):
        from test_saas_demo_request_workflow import SaaSDemoRequestWorkflowTests

        self.workflow = SaaSDemoRequestWorkflowTests()
        self.workflow.setUp()

    def teardown_method(self):
        self.workflow.tearDown()

    def _active_demo(self):
        return self.workflow._activate_demo(
            email=f"journey-{uuid.uuid4().hex}@academy.edu",
            owner_user_id=f"8{uuid.uuid4().int % 100000:05d}",
        )

    def _expire(self, fixture):
        started = datetime.now(UTC) - timedelta(days=9)
        self.workflow._set_demo_started_at(fixture, started)
        db = self.workflow._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            demo_lifecycle_service.process_demo_lifecycle(
                db, provisioning, dry_run=False
            )
            db.commit()
        finally:
            db.close()

    def test_expiry_email_subscribe_now_targets_subscription(self):
        fixture = self._active_demo()
        db = self.workflow._db()
        try:
            request_row = db.get(
                saas.models.SaaSDemoRequest, fixture["request_id"]
            )
            delivery = demo_email_service.create_intent(
                db, request_row, "demo_expired"
            )
            content = demo_email_service._content(db, delivery)
            assert "/saas/login?next_path=/saas/subscription" in content.text
            assert "/saas/login?next_path=/saas/subscription" in content.html
        finally:
            db.close()

    def test_expired_demo_subscription_uses_existing_workspace_branches_and_plans(self):
        fixture = self._active_demo()
        self._expire(fixture)
        response = self.workflow.client.get("/saas/subscription")
        assert response.status_code == 200
        assert "Demo Academy" in response.text
        assert "Active branches:</strong> 2" in response.text
        assert "Monthly" in response.text and "Annual" in response.text
        assert "Continue to Checkout" in response.text
        assert "Not Available" not in response.text

        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            journey = customer_journey_service.resolve_demo_subscription_journey(
                db, account
            )
            assert journey.school_group.id == fixture["school_group_id"]
            assert journey.provisioning.school_group_id == fixture["school_group_id"]
            plan_id = journey.plans[0].plan.id
        finally:
            db.close()
        selected = self.workflow.client.post(
            "/saas/subscription/demo/select",
            data={"plan_id": str(plan_id), "billing_interval": "monthly"},
            follow_redirects=False,
        )
        assert selected.status_code == 302
        assert selected.headers["location"].endswith("/checkout")
        db = self.workflow._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                fixture["provisioning_id"],
            )
            assert provisioning.school_group_id == fixture["school_group_id"]
            assert db.query(models.Branch).filter_by(
                school_group_id=fixture["school_group_id"]
            ).count() == 2
        finally:
            db.close()

    def test_missing_pricing_configuration_is_customer_safe(self):
        fixture = self._active_demo()
        self._expire(fixture)
        db = self.workflow._db()
        try:
            db.query(saas.models.SubscriptionPlan).update({"is_active": False})
            db.commit()
        finally:
            db.close()
        response = self.workflow.client.get("/saas/subscription")
        assert response.status_code == 200
        assert "Subscription setup needs assistance" in response.text
        assert "temporarily unavailable" in response.text

    def test_state_routing_and_commercial_guard_handle_expected_expiry(self):
        fixture = self._active_demo()
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            assert customer_journey_service.login_destination(db, account) == "/login"
        finally:
            db.close()

        self._expire(fixture)
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            assert customer_journey_service.login_destination(
                db, account
            ) == "/saas/expired-access?kind=demo"
            user = db.get(models.User, fixture["operational_user_id"])
            user.scope_school_group_id = fixture["school_group_id"]
            response = authorization.enforce_workspace_commercial_access(
                self.workflow._request("/dashboard"), db, current_user=user
            )
            assert response.status_code == 302
            assert response.headers["location"] == "/demo-expired"
            assert (
                authorization.enforce_workspace_commercial_access(
                    self.workflow._request("/saas/subscription"),
                    db,
                    current_user=user,
                )
                is None
            )
        finally:
            db.close()
        friendly = self.workflow.client.get("/saas/expired-access?kind=demo")
        assert friendly.status_code == 403
        assert "Your TIS demo has ended" in friendly.text
        assert "data are safely preserved" in friendly.text

    def test_pending_and_unpaid_login_destinations(self):
        organization_uuid = self.workflow._complete_onboarding(
            f"unpaid-{uuid.uuid4().hex}@academy.edu"
        )
        db = self.workflow._db()
        try:
            account = db.query(saas.models.SaaSAccount).first()
            assert customer_journey_service.login_destination(
                db, account
            ) == f"/saas/onboarding/{organization_uuid}/plan"
        finally:
            db.close()
        request_uuid = self.workflow._submit_demo(organization_uuid)
        db = self.workflow._db()
        try:
            account = db.query(saas.models.SaaSAccount).first()
            assert customer_journey_service.login_destination(
                db, account
            ) == f"/saas/demo-requests/{request_uuid}"
        finally:
            db.close()

    def test_customer_language_login_and_landing_navigation(self):
        acknowledgement = (ROOT / "email_templates.py").read_text(encoding="utf-8")
        assert "The TIS team will review your request." in acknowledgement
        login = self.workflow.client.get("/saas/login")
        assert "Create an Account" in login.text
        assert "Return to TIS Website" in login.text

        landing = (
            ROOT / "tis-landing-website" / "src" / "app" / "page.tsx"
        ).read_text(encoding="utf-8")
        assert 'buildTisAppUrl("/saas/login")' in landing
        assert 'buildTisAppUrl("/login")' in landing
        assert "Sign In" in landing and "Open TIS App" in landing

    def test_expired_paid_subscription_routes_to_friendly_blocked_state(self):
        fixture = self._active_demo()
        commercial = self.workflow._confirmed_subscription_for_demo(fixture)
        self.workflow._convert_demo(fixture, commercial)
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            assert customer_journey_service.login_destination(db, account) == "/login"
            subscription = db.get(
                saas.models.PaymentSubscription, commercial["subscription_id"]
            )
            subscription.status = "past_due"
            db.commit()
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            assert customer_journey_service.login_destination(
                db, account
            ) == "/saas/expired-access?kind=subscription"
            state = commercial_access_service.resolve_workspace_access(
                db, fixture["school_group_id"]
            )
            assert state.blocked and state.kind == "subscription"
            user = db.get(models.User, fixture["operational_user_id"])
            user.scope_school_group_id = fixture["school_group_id"]
            blocked = authorization.enforce_workspace_commercial_access(
                self.workflow._request("/dashboard"), db, current_user=user
            )
            assert blocked.status_code == 302
            assert blocked.headers["location"].endswith("kind=subscription")
        finally:
            db.close()
        response = self.workflow.client.get(
            "/saas/expired-access?kind=subscription"
        )
        assert response.status_code == 403
        assert "subscription has expired" in response.text
        assert "Renew Subscription" in response.text

    def test_operational_login_intercepts_expired_demo_and_paid_states(self):
        from main import app as operational_app

        fixture = self._active_demo()
        self._expire(fixture)
        password = "ExpiredAccess123!"
        db = self.workflow._db()
        try:
            user = db.get(models.User, fixture["operational_user_id"])
            user.password = auth.get_password_hash(password)
            username = user.username
            db.commit()
        finally:
            db.close()

        def override_get_db():
            session = self.workflow._db()
            try:
                yield session
            finally:
                session.close()

        operational_app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(operational_app) as client:
                demo_login = client.post(
                    "/login",
                    data={"username": username, "password": password},
                    follow_redirects=False,
                )
                assert demo_login.status_code == 302
                assert demo_login.headers["location"].endswith("kind=demo")

            commercial = self.workflow._confirmed_subscription_for_demo(fixture)
            self.workflow._convert_demo(fixture, commercial)
            db = self.workflow._db()
            try:
                subscription = db.get(
                    saas.models.PaymentSubscription,
                    commercial["subscription_id"],
                )
                subscription.status = "past_due"
                db.commit()
            finally:
                db.close()

            with TestClient(operational_app) as client:
                paid_login = client.post(
                    "/login",
                    data={"username": username, "password": password},
                    follow_redirects=False,
                )
                assert paid_login.status_code == 302
                assert paid_login.headers["location"].endswith(
                    "kind=subscription"
                )
        finally:
            operational_app.dependency_overrides.pop(get_db, None)

    def test_owner_page_uses_progressive_disclosure_without_removing_operations(self):
        source = (
            ROOT / "templates" / "saas" / "admin_demo_request_detail.html"
        ).read_text(encoding="utf-8")
        for label in (
            "Change Expiry",
            "Expire Demo",
            "Reactivate",
            "Change Feature Access",
            "Send Reminder",
            "More Actions",
            "Advanced Settings",
            "Activity History",
        ):
            assert label in source
        for operation in (
            "/operations/expire",
            "/operations/reactivate",
            "/operations/expiry",
            "/operations/reminder",
            "/operations/lifecycle",
            "/operations/access",
        ):
            assert operation in source
