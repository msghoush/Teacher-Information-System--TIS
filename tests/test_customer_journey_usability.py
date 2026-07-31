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
    payment_service,
    paddle_client,
    service,
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

    def _configure_checkout_price(self):
        db = self.workflow._db()
        try:
            plan = (
                db.query(saas.models.SubscriptionPlan)
                .filter_by(plan_code="professional")
                .one()
            )
            price = (
                db.query(saas.models.SubscriptionPlanPrice)
                .filter_by(
                    plan_id=plan.id,
                    billing_interval="monthly",
                    currency_code="USD",
                    is_active=True,
                )
                .one()
            )
            price.provider_price_id = "pri_expired_demo_identity"
            db.commit()
            return plan.id
        finally:
            db.close()

    def _select_expired_demo_plan(self, fixture, client=None):
        client = client or self.workflow.client
        plan_id = self._configure_checkout_price()
        response = client.post(
            "/saas/subscription/demo/select",
            data={"plan_id": str(plan_id), "billing_interval": "monthly"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        return response.headers["location"]

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
        plan_id = self._configure_checkout_price()

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

    def test_expired_demo_checkout_reuses_authoritative_tenant_identity(self):
        fixture = self._active_demo()
        self._expire(fixture)
        checkout_path = self._select_expired_demo_plan(fixture)
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=fixture["organization_uuid"]
            ).one()
            group = db.get(models.SchoolGroup, fixture["school_group_id"])
            account_uuid = account.account_uuid
            organization_uuid = organization.organization_uuid
            workspace_uuid = group.workspace_uuid
            branch_ids = {
                row[0]
                for row in db.query(models.Branch.id).filter_by(
                    school_group_id=group.id
                ).all()
            }
        finally:
            db.close()
        remote = {
            "id": "ctm_expired_demo_owner",
            "email": account.email,
            "status": "active",
            "custom_data": {
                "saas_account_uuid": "deleted-account",
                "pending_organization_uuid": "deleted-organization",
            },
        }
        updated = {
            **remote,
            "custom_data": {
                "saas_account_uuid": account_uuid,
                "pending_organization_uuid": organization_uuid,
            },
        }
        with (
            patch.dict(
                "os.environ",
                {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""},
                clear=False,
            ),
            patch(
                "saas.paddle_client.list_customers_by_email",
                return_value=[remote],
            ),
            patch(
                "saas.paddle_client.update_customer", return_value=updated
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_expired_demo_owner",
                    "currency_code": "USD",
                    "checkout": {
                        "url": "https://pay.paddle.test/expired-demo"
                    },
                },
            ),
        ):
            launched = self.workflow.client.post(
                checkout_path + "/launch",
                follow_redirects=False,
            )
        assert launched.status_code == 302
        assert launched.headers["location"] == (
            "https://pay.paddle.test/expired-demo"
        )
        db = self.workflow._db()
        try:
            group = db.get(models.SchoolGroup, fixture["school_group_id"])
            assert group.workspace_uuid == workspace_uuid
            assert {
                row[0]
                for row in db.query(models.Branch.id).filter_by(
                    school_group_id=group.id
                ).all()
            } == branch_ids
            assert db.query(models.TenantProfile).filter_by(
                school_group_id=group.id
            ).count() == 1
        finally:
            db.close()

    def test_reregistered_account_safely_supersedes_stale_workspace_link(self):
        fixture = self._active_demo()
        self._expire(fixture)
        password = "Reregistered123!"
        db = self.workflow._db()
        try:
            old_account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            original_email = old_account.email
            old_account.status = "superseded"
            old_account.email = f"superseded-{old_account.id}@invalid.test"
            old_account.email_normalized = old_account.email
            new_account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=original_email,
                email_normalized=original_email,
                password_hash=auth.get_password_hash(password),
                first_name="Re",
                last_name="Registered",
                status="active",
                onboarding_status="active",
                account_purpose="customer",
                email_verified_at=datetime.now(UTC).replace(tzinfo=None),
            )
            db.add(new_account)
            db.flush()
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=fixture["organization_uuid"]
            ).one()
            organization.owner_saas_account_id = new_account.id
            request_row = db.get(
                saas.models.SaaSDemoRequest, fixture["request_id"]
            )
            request_row.requester_saas_account_id = new_account.id
            new_account_id = new_account.id
            new_account_uuid = new_account.account_uuid
            db.commit()
        finally:
            db.close()
        client = TestClient(self.workflow.app)
        self.workflow.extra_clients.append(client)
        login = client.post(
            "/saas/auth/login",
            data={"email": original_email, "password": password},
            follow_redirects=False,
        )
        assert login.status_code == 302
        checkout_path = self._select_expired_demo_plan(fixture, client)
        remote = {
            "id": "ctm_reregistered_demo",
            "email": original_email,
            "status": "active",
            "custom_data": {
                "saas_account_uuid": "deleted-account-uuid",
                "pending_organization_uuid": "deleted-org-uuid",
            },
        }
        updated = {
            **remote,
            "custom_data": {
                "saas_account_uuid": new_account_uuid,
                "pending_organization_uuid": fixture["organization_uuid"],
            },
        }
        with (
            patch.dict(
                "os.environ",
                {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""},
                clear=False,
            ),
            patch(
                "saas.paddle_client.list_customers_by_email",
                return_value=[remote],
            ),
            patch(
                "saas.paddle_client.update_customer", return_value=updated
            ),
            patch(
                "saas.paddle_client.create_transaction",
                return_value={
                    "id": "txn_reregistered_demo",
                    "currency_code": "USD",
                    "checkout": {
                        "url": "https://pay.paddle.test/reregistered"
                    },
                },
            ),
        ):
            launched = client.post(
                checkout_path + "/launch", follow_redirects=False
            )
        assert launched.headers["location"] == (
            "https://pay.paddle.test/reregistered"
        )
        db = self.workflow._db()
        try:
            links = db.query(saas.models.SaaSAccountUserLink).filter_by(
                school_group_id=fixture["school_group_id"]
            ).all()
            assert len(links) == 1
            assert links[0].saas_account_id == new_account_id
            assert db.query(models.SchoolGroup).filter_by(
                id=fixture["school_group_id"]
            ).count() == 1
        finally:
            db.close()

    def test_checkout_identity_failure_is_friendly_and_not_ready(self):
        fixture = self._active_demo()
        self._expire(fixture)
        checkout_path = self._select_expired_demo_plan(fixture)
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            email = account.email
        finally:
            db.close()
        remote = [
            {
                "id": f"ctm_ambiguous_{index}",
                "email": email,
                "status": "active",
                "custom_data": {
                    "saas_account_uuid": f"other-{index}",
                    "pending_organization_uuid": f"other-org-{index}",
                },
            }
            for index in (1, 2)
        ]
        with (
            patch.dict(
                "os.environ",
                {"PADDLE_ENVIRONMENT": "sandbox", "PADDLE_API_BASE_URL": ""},
                clear=False,
            ),
            patch(
                "saas.paddle_client.list_customers_by_email",
                return_value=remote,
            ),
            patch("saas.paddle_client.update_customer") as update_customer,
            patch("saas.paddle_client.create_transaction") as transaction,
        ):
            failed = self.workflow.client.post(
                checkout_path + "/launch", follow_redirects=False
            )
        assert failed.status_code == 302
        assert "exact+matches" not in failed.headers["location"]
        assert "context+matches" not in failed.headers["location"]
        assert "Diagnostic" not in failed.headers["location"]
        update_customer.assert_not_called()
        transaction.assert_not_called()
        page = self.workflow.client.get(failed.headers["location"])
        assert page.status_code == 200
        assert payment_service.CUSTOMER_SAFE_PAYMENT_ACCOUNT_MESSAGE in page.text
        assert "Secure Payment is ready to open" not in page.text
        assert "Retry Secure Payment" in page.text

    def test_state_routing_and_commercial_guard_handle_expected_expiry(self):
        fixture = self._active_demo()
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            account_email = account.email
            assert customer_journey_service.login_destination(db, account) == "/saas/account"
        finally:
            db.close()

        self.workflow.client.cookies.clear()
        login_page = self.workflow.client.get("/saas/login")
        assert login_page.status_code == 200
        authenticated = self.workflow.client.post(
            "/saas/auth/login",
            data={
                "email": account_email,
                "password": "strong-password-123",
                "next_path": "/saas/subscription",
            },
            follow_redirects=False,
        )
        assert authenticated.status_code == 302
        assert authenticated.headers["location"] == "/saas/account"
        public_sign_in = self.workflow.client.get(
            "/saas/login?next_path=/login",
            follow_redirects=False,
        )
        assert public_sign_in.status_code == 302
        assert public_sign_in.headers["location"] == "/saas/account"
        overview = self.workflow.client.get("/saas/account")
        assert overview.status_code == 200
        assert "Organization Account" in overview.text
        assert "Organization Profile" in overview.text
        assert "Branches" in overview.text
        assert "Billing &amp; Subscription" in overview.text
        assert "Account &amp; Security" in overview.text
        assert '>Enter TIS Platform</a>' in overview.text
        assert 'href="/login"' in overview.text

        self._expire(fixture)
        db = self.workflow._db()
        try:
            account = db.get(
                saas.models.SaaSAccount, fixture["saas_account_id"]
            )
            assert customer_journey_service.login_destination(
                db, account
            ) == "/saas/account"
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
        restricted = self.workflow.client.get("/saas/account")
        assert restricted.status_code == 200
        assert "billing recovery options remain available" in restricted.text
        assert 'href="/saas/subscription"' in restricted.text
        assert '>Enter TIS Platform</a>' not in restricted.text
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
            assert customer_journey_service.login_destination(db, account) == "/saas/account"
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
            ) == "/saas/account"
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
        assert "payment is past due" in response.text
        assert "Review Payment" in response.text

    def test_activated_user_without_account_management_uses_role_destination(self):
        fixture = self._active_demo()
        db = self.workflow._db()
        try:
            account = db.get(saas.models.SaaSAccount, fixture["saas_account_id"])
            organization = db.query(saas.models.PendingOrganization).filter_by(
                organization_uuid=fixture["organization_uuid"]
            ).one()
            replacement_email = f"replacement-{uuid.uuid4().hex}@academy.edu"
            replacement_owner = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=replacement_email,
                email_normalized=replacement_email,
                status="active",
                onboarding_status="tenant_active",
                email_verified_at=datetime.now(UTC).replace(tzinfo=None),
            )
            db.add(replacement_owner)
            db.flush()
            organization.owner_saas_account_id = replacement_owner.id
            link = db.query(saas.models.SaaSAccountUserLink).filter_by(
                saas_account_id=account.id,
                school_group_id=fixture["school_group_id"],
            ).one()
            link.link_type = "tenant_member"
            user = db.get(models.User, fixture["operational_user_id"])
            user.role = auth.ROLE_LIMITED
            db.commit()
            assert customer_journey_service.login_destination(db, account) == "/login"
        finally:
            db.close()

        denied = self.workflow.client.get("/saas/account", follow_redirects=False)
        assert denied.status_code == 302
        assert denied.headers["location"] == "/login"

    def test_multiple_managed_organizations_require_selection(self):
        fixture = self._active_demo()
        db = self.workflow._db()
        try:
            account = db.get(saas.models.SaaSAccount, fixture["saas_account_id"])
            group = models.SchoolGroup(
                name=f"Second Workspace {uuid.uuid4().hex[:8]}",
                workspace_classification="customer_demo",
                workspace_lifecycle_status="active",
                status=True,
            )
            db.add(group)
            db.flush()
            second_uuid = str(uuid.uuid4())
            organization = saas.models.PendingOrganization(
                organization_uuid=second_uuid,
                owner_saas_account_id=account.id,
                organization_name=group.name,
                status="activated",
                onboarding_step="completed",
                billing_status="tenant_active",
                payment_status="paid",
            )
            db.add(organization)
            db.flush()
            second_email = f"second-owner-{uuid.uuid4().hex}@academy.edu"
            user = models.User(
                user_id=f"7{uuid.uuid4().int % 100000:05d}",
                username=f"second.owner.{uuid.uuid4().hex[:8]}",
                email=second_email,
                email_normalized=second_email,
                password="unused",
                role=auth.ROLE_ADMINISTRATOR,
                user_type=auth.USER_TYPE_TENANT,
                school_group_id=group.id,
                is_active=True,
            )
            db.add(user)
            db.flush()
            db.add(
                saas.models.SaaSAccountUserLink(
                    saas_account_id=account.id,
                    operational_user_id=user.id,
                    pending_organization_id=organization.id,
                    school_group_id=group.id,
                    link_type="tenant_owner",
                )
            )
            db.commit()
        finally:
            db.close()

        selector = self.workflow.client.get("/saas/account")
        assert selector.status_code == 200
        assert "Choose an organization" in selector.text
        assert selector.text.count("Open Organization Account") == 2
        selected = self.workflow.client.get(
            f"/saas/account?organization_uuid={second_uuid}"
        )
        assert selected.status_code == 200
        assert "Organization Account" in selected.text
        assert self.workflow.client.cookies.get(
            service.SAAS_ORGANIZATION_COOKIE
        ) == second_uuid
        restored = self.workflow.client.get("/saas/account")
        assert restored.status_code == 200
        assert "Choose an organization" not in restored.text
        assert "Second Workspace" in restored.text

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
