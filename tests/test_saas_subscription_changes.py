from datetime import datetime, timedelta
import json
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import auth
import db_migrations
import main
import models
import saas.models
from dependencies import get_db
from saas import entitlement_service, paddle_client, service, subscription_change_service, subscription_portal_service
from saas.router import router as saas_router


class SaaSSubscriptionChangeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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

    def _fixture(self, *, quantity=3, active_branches=3, role=auth.ROLE_ADMINISTRATOR, email=None):
        db = self.Session()
        unique = uuid.uuid4().hex[:10]
        try:
            email = email or f"billing-{unique}@example.com"
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()), email=email, email_normalized=email,
                password_hash=auth.get_password_hash("billing-password-123"), first_name="Billing",
                last_name="Owner", status="active", onboarding_status="tenant_active",
                email_verified_at=datetime(2026, 7, 1),
            )
            db.add(account); db.flush()
            session_token, csrf_token, _ = service.create_session(db, account)
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").one()
            price = db.query(saas.models.SubscriptionPlanPrice).filter_by(
                plan_id=plan.id, billing_interval="monthly", currency_code="USD", is_active=True
            ).one()
            price.provider_price_id = price.provider_price_id or "pri_01testprofessionalmonthly000"
            group = models.SchoolGroup(name=f"Billing School {unique}")
            db.add(group); db.flush()
            branches = []
            for index in range(active_branches):
                branch = models.Branch(school_group_id=group.id, name=f"Campus {index + 1} {unique}", status=True)
                db.add(branch); branches.append(branch)
            db.flush()
            user = models.User(
                user_id=unique, username=f"billing.{unique}", email=email, email_normalized=email,
                password="unused", role=role, school_group_id=group.id,
                branch_id=branches[0].id if branches else None,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION, is_active=True,
            )
            db.add(user); db.flush()
            organization = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()), owner_saas_account_id=account.id,
                organization_name=f"Billing Organization {unique}", status="tenant_active",
                onboarding_step="completed", billing_status="tenant_active", payment_status="paid",
                payment_confirmed_at=datetime(2026, 7, 1),
            )
            db.add(organization); db.flush()
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id, school_group_id=group.id, plan_id=plan.id,
                billing_interval="monthly", contract_status="tenant_active", payment_status="paid",
                paid_at=datetime(2026, 7, 1), base_currency_code="USD",
                base_amount_minor=price.amount_minor, display_currency_code="USD",
                display_amount_minor=price.amount_minor, billable_branch_count=quantity,
            )
            db.add(contract); db.flush()
            subscription = saas.models.PaymentSubscription(
                pending_organization_id=organization.id, subscription_contract_id=contract.id,
                provider="paddle", provider_subscription_id=f"sub_{uuid.uuid4().hex}",
                provider_price_id=price.provider_price_id, plan_id=plan.id, billing_interval="monthly",
                currency_code="USD", quantity=quantity, unit_amount_minor=price.amount_minor,
                amount_minor=price.amount_minor * quantity, status="active",
                current_period_start=datetime(2026, 7, 1), current_period_end=datetime(2026, 8, 1),
                next_billed_at=datetime(2026, 8, 1),
            )
            db.add(subscription); db.flush()
            db.add(saas.models.TenantProvisioningLink(
                pending_organization_id=organization.id, subscription_contract_id=contract.id,
                school_group_id=group.id, owner_operational_user_id=user.id,
                primary_branch_id=branches[0].id if branches else None,
                tenant_status="tenant_active", activated_at=datetime(2026, 7, 1),
            ))
            db.add(saas.models.SaaSAccountUserLink(
                saas_account_id=account.id, operational_user_id=user.id,
                pending_organization_id=organization.id, school_group_id=group.id,
                link_type="tenant_owner",
            ))
            db.commit()
            return {
                "account_id": account.id, "user_id": user.id, "group_id": group.id,
                "subscription_id": subscription.id, "contract_id": contract.id,
                "provider_subscription_id": subscription.provider_subscription_id,
                "provider_price_id": subscription.provider_price_id,
                "unit_amount": price.amount_minor, "price_id": price.id,
                "session_token": session_token, "csrf_token": csrf_token,
            }
        finally:
            db.close()

    def _account(self, db, fixture):
        return db.query(saas.models.SaaSAccount).filter_by(id=fixture["account_id"]).one()

    @staticmethod
    def _operational_request(path: str, *, method: str = "GET") -> Request:
        return Request({
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
            "app": main.app,
        })

    def _school_management_body(self, fixture) -> str:
        db = self.Session()
        try:
            user = db.query(models.User).filter_by(id=fixture["user_id"]).one()
            with patch("auth.get_current_user", return_value=user):
                response = main.system_configuration_schools(
                    request=self._operational_request("/system-configuration/schools"),
                    db=db,
                )
            self.assertEqual(response.status_code, 200)
            return bytes(response.body).decode("utf-8")
        finally:
            db.close()

    def _provider_subscription(self, fixture, quantity, *, period_start="2026-07-01T00:00:00Z"):
        return {
            "id": fixture["provider_subscription_id"], "status": "active",
            "currency_code": "USD",
            "items": [
                {"quantity": quantity, "price": {"id": fixture["provider_price_id"], "billing_cycle": {"interval": "month"}, "unit_price": {"currency_code": "USD"}}},
                {"quantity": 1, "price": {"id": "pri_01retainedaddon00000000000000", "billing_cycle": {"interval": "month"}, "unit_price": {"currency_code": "USD"}}},
            ],
            "current_billing_period": {"starts_at": period_start, "ends_at": "2026-08-01T00:00:00Z"},
            "next_billed_at": "2026-08-01T00:00:00Z",
            "recurring_transaction_details": {"totals": {"balance": str(fixture["unit_amount"] * quantity), "grand_total": str(fixture["unit_amount"] * quantity), "currency_code": "USD"}},
        }

    def _preview_payload(self, fixture, requested, *, current=3, next_total=None, alternate_nesting=False):
        next_total = next_total if next_total is not None else fixture["unit_amount"] * requested
        recurring_totals = {"balance": str(next_total), "grand_total": str(next_total), "currency_code": "USD"}
        return {
            "id": fixture["provider_subscription_id"],
            "status": "active",
            "currency_code": "USD",
            "items": self._provider_subscription(fixture, requested)["items"],
            "update_summary": {
                "credit": {"amount": "-100", "currency_code": "USD"},
                "charge": {"amount": "900", "currency_code": "USD"},
                "result": {"action": "charge", "amount": "800", "currency_code": "USD"},
            },
            "immediate_transaction": {"details": {"totals": {"balance": "800", "grand_total": "800", "currency_code": "USD"}}} if requested > current else None,
            "recurring_transaction_details": {"details": {"totals": recurring_totals}} if alternate_nesting else {"totals": recurring_totals},
        }

    def _preview(self, fixture, requested, *, current=3, next_total=None, alternate_nesting=False):
        response = self._preview_payload(
            fixture,
            requested,
            current=current,
            next_total=next_total,
            alternate_nesting=alternate_nesting,
        )
        db = self.Session()
        try:
            with (
                patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, current)),
                patch.object(paddle_client, "preview_subscription_update", return_value=response) as preview_call,
                patch("saas.subscription_change_service.audit.write_audit_event"),
            ):
                row = subscription_change_service.preview_quantity_change(db, self._account(db, fixture), requested)
                db.commit()
                row_id = row.id
                preview_kwargs = preview_call.call_args.kwargs
            return row_id, preview_kwargs
        finally:
            db.close()

    def test_increase_preview_uses_complete_retained_items_and_provider_totals(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        row_id, kwargs = self._preview(fixture, 5)
        self.assertEqual(kwargs["proration_billing_mode"], "prorated_immediately")
        self.assertEqual(len(kwargs["items"]), 2)
        self.assertEqual(next(item for item in kwargs["items"] if item["price_id"] == fixture["provider_price_id"])["quantity"], 5)
        db = self.Session()
        try:
            row = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one()
            self.assertEqual((row.current_quantity, row.requested_quantity, row.quantity_delta), (3, 5, 2))
            self.assertEqual((row.previewed_charge_minor, row.previewed_credit_minor, row.previewed_net_minor), (900, 100, 800))
            self.assertEqual(row.next_renewal_total_minor, fixture["unit_amount"] * 5)
        finally:
            db.close()

    def test_branch_management_enables_creation_when_paid_capacity_remains(self):
        fixture = self._fixture(quantity=4, active_branches=3)
        body = self._school_management_body(fixture)

        self.assertIn('data-branch-capacity-state="available"', body)
        self.assertIn("1 branch seat available", body)
        self.assertIn('action="/system-configuration/branches"', body)
        self.assertIn("Add Branch", body)

    def test_at_capacity_hides_creation_and_disables_reactivation(self):
        fixture = self._fixture(quantity=4, active_branches=4)
        db = self.Session()
        try:
            db.add(models.Branch(
                school_group_id=fixture["group_id"],
                name="Inactive Capacity Test",
                status=False,
            ))
            db.commit()
        finally:
            db.close()

        body = self._school_management_body(fixture)

        self.assertIn('data-branch-capacity-state="at-capacity"', body)
        self.assertIn("currently covers 4 active branches", body)
        self.assertIn('href="/saas/subscription"', body)
        self.assertIn("Increase Branch Capacity", body)
        self.assertNotIn('action="/system-configuration/branches"', body)
        self.assertRegex(body, r'<option value="active"[^>]*disabled[^>]*>Active</option>')

    def test_over_capacity_warns_and_direct_creation_remains_blocked(self):
        fixture = self._fixture(quantity=4, active_branches=5)
        body = self._school_management_body(fixture)
        self.assertIn('data-branch-capacity-state="over"', body)
        self.assertIn("5 active branches and confirmed paid capacity for 4", body)
        self.assertNotIn('action="/system-configuration/branches"', body)

        db = self.Session()
        try:
            user = db.query(models.User).filter_by(id=fixture["user_id"]).one()
            before = db.query(models.Branch).filter_by(school_group_id=fixture["group_id"]).count()
            with patch("auth.get_current_user", return_value=user):
                response = main.create_branch(
                    request=self._operational_request("/system-configuration/branches", method="POST"),
                    name="Blocked Fifth Campus",
                    region="Riyadh",
                    country_code="",
                    region_id="",
                    region_manual="",
                    city_id="",
                    city_manual="",
                    district_name="",
                    neighborhood_name="",
                    school_group_id=fixture["group_id"],
                    return_to="/system-configuration/schools",
                    db=db,
                )
            self.assertEqual(response.status_code, 302)
            self.assertIn("No+paid+branch+capacity", response.headers["location"])
            self.assertEqual(
                db.query(models.Branch).filter_by(school_group_id=fixture["group_id"]).count(),
                before,
            )
        finally:
            db.close()

    def test_manual_review_and_missing_permission_hide_branch_creation(self):
        manual_review = self._fixture(quantity=4, active_branches=3)
        db = self.Session()
        try:
            contract = db.query(saas.models.SubscriptionContract).filter_by(
                id=manual_review["contract_id"]
            ).one()
            contract.school_group_id = None
            db.commit()
        finally:
            db.close()
        manual_body = self._school_management_body(manual_review)
        self.assertIn('data-branch-capacity-state="unavailable"', manual_body)
        self.assertIn("Branch capacity information is currently unavailable", manual_body)
        self.assertNotIn('action="/system-configuration/branches"', manual_body)

        no_permission = self._fixture(quantity=4, active_branches=3)
        db = self.Session()
        try:
            db.add(models.RolePermission(
                school_group_id=no_permission["group_id"],
                role=auth.ROLE_ADMINISTRATOR,
                permission_key="branches.create",
                is_allowed=False,
            ))
            db.commit()
        finally:
            db.close()
        permission_body = self._school_management_body(no_permission)
        self.assertIn('data-branch-capacity-state="available"', permission_body)
        self.assertNotIn('action="/system-configuration/branches"', permission_body)

    def test_documented_and_alternate_recurring_total_nesting_are_supported(self):
        documented = self._fixture(quantity=3, active_branches=3)
        documented_id, _ = self._preview(documented, 4)
        alternate = self._fixture(quantity=3, active_branches=3)
        alternate_id, _ = self._preview(alternate, 4, alternate_nesting=True)
        db = self.Session()
        try:
            self.assertEqual(db.query(saas.models.SubscriptionChangeRequest).filter_by(id=documented_id).one().requested_quantity, 4)
            self.assertEqual(db.query(saas.models.SubscriptionChangeRequest).filter_by(id=alternate_id).one().requested_quantity, 4)
        finally:
            db.close()

    def test_documented_preview_without_top_level_subscription_id_succeeds(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        response = self._preview_payload(fixture, 4)
        response.pop("id")
        db = self.Session()
        try:
            with (
                patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 3)),
                patch.object(paddle_client, "preview_subscription_update", return_value=response),
                patch("saas.subscription_change_service.audit.write_audit_event"),
            ):
                row = subscription_change_service.preview_quantity_change(db, self._account(db, fixture), 4)
                db.commit()
            self.assertEqual(row.requested_quantity, 4)
            self.assertEqual(row.previewed_net_minor, 800)
        finally:
            db.close()

    def test_get_subscription_identity_is_still_required(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        provider = self._provider_subscription(fixture, 3)
        provider["id"] = "sub_01wrongsubscriptionidentity"
        db = self.Session()
        try:
            with (
                patch.object(paddle_client, "get_subscription", return_value=provider),
                patch.object(paddle_client, "preview_subscription_update") as preview,
                self.assertRaises(subscription_change_service.SubscriptionChangeError) as caught,
            ):
                subscription_change_service.preview_quantity_change(db, self._account(db, fixture), 4)
            self.assertEqual(caught.exception.code, "provider_subscription_unavailable")
            preview.assert_not_called()
        finally:
            db.close()

    def test_malformed_preview_without_items_still_fails_closed(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        response = self._preview_payload(fixture, 4)
        response.pop("id")
        response.pop("items")
        db = self.Session()
        try:
            with (
                patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 3)),
                patch.object(paddle_client, "preview_subscription_update", return_value=response),
                patch("saas.subscription_change_service.logger.warning"),
                self.assertRaises(subscription_change_service.SubscriptionChangeError) as caught,
            ):
                subscription_change_service.preview_quantity_change(db, self._account(db, fixture), 4)
            self.assertEqual(caught.exception.code, "preview_provider_price_mismatch")
            self.assertEqual(caught.exception.status_code, 502)
        finally:
            db.close()

    def test_unchanged_quantity_stops_before_any_paddle_call(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        db = self.Session()
        try:
            with (
                patch.object(paddle_client, "get_subscription") as get_subscription,
                patch.object(paddle_client, "preview_subscription_update") as preview,
                self.assertRaises(subscription_change_service.SubscriptionChangeError) as caught,
            ):
                subscription_change_service.preview_quantity_change(db, self._account(db, fixture), 3)
            self.assertEqual(caught.exception.code, "unchanged_quantity")
            self.assertEqual(str(caught.exception), "Choose a different branch quantity to preview a change.")
            get_subscription.assert_not_called()
            preview.assert_not_called()
        finally:
            db.close()

    def test_preview_failure_preserves_quantity_and_sandbox_shows_safe_diagnostics(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        incomplete = self._preview_payload(fixture, 4)
        incomplete.pop("recurring_transaction_details")
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, fixture["session_token"])
        self.client.cookies.set(service.SAAS_CSRF_COOKIE, fixture["csrf_token"])
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}),
            patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 3)),
            patch.object(paddle_client, "preview_subscription_update", return_value=incomplete),
            patch("saas.subscription_change_service.logger.warning") as diagnostic_log,
        ):
            response = self.client.post(
                "/saas/subscription/branches/preview",
                data={"requested_quantity": "4", "csrf_token": fixture["csrf_token"]},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="4"', response.text)
        self.assertIn("preview_financial_data_incomplete", response.text)
        self.assertIn("recurring_transaction_details", response.text)
        self.assertNotIn(fixture["provider_subscription_id"], response.text)
        diagnostic_log.assert_called_once()

    def test_missing_financial_data_is_generic_in_production(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        incomplete = self._preview_payload(fixture, 4)
        incomplete["immediate_transaction"] = None
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, fixture["session_token"])
        self.client.cookies.set(service.SAAS_CSRF_COOKIE, fixture["csrf_token"])
        with (
            patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "production"}),
            patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 3)),
            patch.object(paddle_client, "preview_subscription_update", return_value=incomplete),
            patch("saas.subscription_change_service.logger.warning"),
        ):
            response = self.client.post(
                "/saas/subscription/branches/preview",
                data={"requested_quantity": "4", "csrf_token": fixture["csrf_token"]},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="4"', response.text)
        self.assertIn("Secure subscription preview is temporarily unavailable", response.text)
        self.assertNotIn("preview_financial_data_incomplete", response.text)

    def test_increase_submission_is_immediate_idempotent_and_does_not_unlock_capacity(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        row_id, _ = self._preview(fixture, 5)
        db = self.Session()
        try:
            row = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one()
            with (
                patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 3)),
                patch.object(paddle_client, "update_subscription", return_value=self._provider_subscription(fixture, 5)) as update,
                patch("saas.subscription_change_service.audit.write_audit_event"),
            ):
                submitted = subscription_change_service.submit_quantity_change(db, self._account(db, fixture), row.request_uuid)
                db.commit()
                self.assertEqual(submitted.status, "payment_pending")
                self.assertEqual(update.call_args.kwargs["proration_billing_mode"], "prorated_immediately")
                self.assertEqual(update.call_args.kwargs["on_payment_failure"], "prevent_change")
            with patch.object(paddle_client, "update_subscription") as repeated:
                subscription_change_service.submit_quantity_change(db, self._account(db, fixture), row.request_uuid)
                repeated.assert_not_called()
            subscription = db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one()
            self.assertEqual(subscription.quantity, 3)
            resolution = entitlement_service.resolve_entitlements(db, fixture["group_id"])
            self.assertTrue(resolution.is_at_capacity)
            with self.assertRaises(entitlement_service.BranchCapacityError):
                entitlement_service.require_active_branch_capacity(db, fixture["group_id"])
        finally:
            db.close()

    def test_successful_increase_webhooks_unlock_capacity_and_retries_are_idempotent(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        row_id, _ = self._preview(fixture, 5)
        db = self.Session()
        try:
            row = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one()
            row.status = "payment_pending"; row.submitted_at = datetime.utcnow(); db.commit()
            subscription_payload = {"data": self._provider_subscription(fixture, 5)}
            with patch("saas.subscription_change_service.audit.write_audit_event"):
                subscription_change_service.reconcile_quantity_change_webhook(db, subscription_payload, "subscription.updated")
                self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 3)
                transaction_payload = {"data": {"subscription_id": fixture["provider_subscription_id"], "status": "completed", "origin": "subscription_update", "currency_code": "USD", "items": [{"price": {"id": fixture["provider_price_id"]}}]}}
                subscription_change_service.reconcile_quantity_change_webhook(db, transaction_payload, "transaction.completed")
                subscription_change_service.reconcile_quantity_change_webhook(db, transaction_payload, "transaction.completed")
                db.commit()
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 5)
            self.assertEqual(db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one().status, "confirmed")
            entitlement_service.require_active_branch_capacity(db, fixture["group_id"])
        finally:
            db.close()

    def test_failed_payment_and_mismatched_quantity_do_not_change_capacity(self):
        fixture = self._fixture(quantity=3, active_branches=3)
        failed_id, _ = self._preview(fixture, 5)
        db = self.Session()
        try:
            failed = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=failed_id).one()
            failed.status = "payment_pending"; db.commit()
            subscription_change_service.reconcile_quantity_change_webhook(
                db, {"data": {"subscription_id": fixture["provider_subscription_id"], "origin": "subscription_update", "currency_code": "USD", "items": [{"price": {"id": fixture["provider_price_id"]}}]}}, "transaction.payment_failed"
            )
            db.commit()
            self.assertEqual(failed.status, "failed")
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 3)
        finally:
            db.close()
        mismatch_id, _ = self._preview(fixture, 5)
        db = self.Session()
        try:
            mismatch = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=mismatch_id).one()
            mismatch.status = "payment_pending"; db.commit()
            subscription_change_service.reconcile_quantity_change_webhook(
                db, {"data": self._provider_subscription(fixture, 4)}, "subscription.updated"
            )
            db.commit()
            self.assertEqual(mismatch.status, "manual_review")
            self.assertEqual(mismatch.provider_observed_quantity, 4)
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 3)
        finally:
            db.close()

    def test_reduction_rules_schedule_without_refund_or_early_capacity_change(self):
        fixture = self._fixture(quantity=5, active_branches=3)
        row_id, kwargs = self._preview(fixture, 3, current=5)
        self.assertEqual(kwargs["proration_billing_mode"], "prorated_next_billing_period")
        db = self.Session()
        try:
            row = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one()
            self.assertEqual(row.previewed_net_minor, 0)
            before_statuses = [branch.status for branch in db.query(models.Branch).filter_by(school_group_id=fixture["group_id"]).all()]
            with (
                patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 5)),
                patch.object(paddle_client, "update_subscription", return_value=self._provider_subscription(fixture, 3)) as update,
                patch("saas.subscription_change_service.audit.write_audit_event"),
            ):
                subscription_change_service.submit_quantity_change(db, self._account(db, fixture), row.request_uuid)
                db.commit()
            self.assertEqual(update.call_args.kwargs["proration_billing_mode"], "prorated_next_billing_period")
            self.assertEqual(row.status, "scheduled")
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 5)
            self.assertEqual(before_statuses, [branch.status for branch in db.query(models.Branch).filter_by(school_group_id=fixture["group_id"]).all()])
            portal = subscription_portal_service.build_subscription_portal(db, self._account(db, fixture))
            self.assertEqual(portal.pending_change["requested_quantity"], 3)
            self.assertTrue(portal.pending_change["can_cancel"])
        finally:
            db.close()

    def test_reduction_below_usage_is_blocked(self):
        fixture = self._fixture(quantity=5, active_branches=4)
        db = self.Session()
        try:
            with self.assertRaises(subscription_change_service.SubscriptionChangeError) as caught:
                subscription_change_service.preview_quantity_change(db, self._account(db, fixture), 3)
            self.assertEqual(caught.exception.code, "below_active_branch_count")
        finally:
            db.close()

    def test_scheduled_reduction_can_be_canceled_with_complete_items(self):
        fixture = self._fixture(quantity=5, active_branches=3)
        row_id, _ = self._preview(fixture, 3, current=5)
        db = self.Session()
        try:
            row = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one()
            row.status = "scheduled"; db.commit()
            with (
                patch.object(paddle_client, "get_subscription", return_value=self._provider_subscription(fixture, 3)),
                patch.object(paddle_client, "preview_subscription_update", return_value={}) as preview,
                patch.object(paddle_client, "update_subscription", return_value=self._provider_subscription(fixture, 5)) as update,
                patch("saas.subscription_change_service.audit.write_audit_event"),
            ):
                subscription_change_service.cancel_scheduled_reduction(db, self._account(db, fixture), row.request_uuid)
                db.commit()
            self.assertEqual(row.status, "canceled")
            self.assertEqual(len(update.call_args.kwargs["items"]), 2)
            self.assertEqual(preview.call_args.kwargs["proration_billing_mode"], "prorated_next_billing_period")
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 5)
        finally:
            db.close()

    def test_effective_reduction_webhook_updates_quantity_only_at_renewal(self):
        fixture = self._fixture(quantity=5, active_branches=3)
        row_id, _ = self._preview(fixture, 3, current=5)
        db = self.Session()
        try:
            row = db.query(saas.models.SubscriptionChangeRequest).filter_by(id=row_id).one()
            row.status = "scheduled"; db.commit()
            before = {"data": self._provider_subscription(fixture, 3, period_start="2026-07-15T00:00:00Z")}
            subscription_change_service.reconcile_quantity_change_webhook(db, before, "subscription.updated")
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 5)
            effective = {"data": self._provider_subscription(fixture, 3, period_start="2026-08-01T00:00:00Z")}
            with patch("saas.subscription_change_service.audit.write_audit_event"):
                subscription_change_service.reconcile_quantity_change_webhook(db, effective, "subscription.updated")
                db.commit()
            self.assertEqual(row.status, "confirmed")
            self.assertEqual(db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one().quantity, 3)
        finally:
            db.close()

    def test_missing_provider_ambiguous_subscription_and_unauthorized_user_fail_closed(self):
        fixture = self._fixture(quantity=3, active_branches=2)
        db = self.Session()
        try:
            subscription = db.query(saas.models.PaymentSubscription).filter_by(id=fixture["subscription_id"]).one()
            subscription.provider_subscription_id = ""; db.commit()
            with self.assertRaises(subscription_change_service.SubscriptionChangeError):
                subscription_change_service.preview_quantity_change(db, self._account(db, fixture), 4)
        finally:
            db.close()
        ambiguous = self._fixture(quantity=3, active_branches=2)
        db = self.Session()
        try:
            original = db.query(saas.models.PaymentSubscription).filter_by(id=ambiguous["subscription_id"]).one()
            db.add(saas.models.PaymentSubscription(
                pending_organization_id=original.pending_organization_id,
                subscription_contract_id=original.subscription_contract_id,
                provider="paddle",
                provider_subscription_id=f"sub_{uuid.uuid4().hex}",
                provider_price_id=original.provider_price_id,
                plan_id=original.plan_id,
                billing_interval=original.billing_interval,
                currency_code=original.currency_code,
                quantity=original.quantity,
                amount_minor=original.amount_minor,
                status="active",
            ))
            db.commit()
            with self.assertRaises(subscription_change_service.SubscriptionChangeError) as caught:
                subscription_change_service.resolve_change_context(db, self._account(db, ambiguous))
            self.assertEqual(caught.exception.code, "ambiguous_confirmed_subscription")
        finally:
            db.close()
        unauthorized = self._fixture(quantity=3, active_branches=2, role=auth.ROLE_LIMITED)
        db = self.Session()
        try:
            with self.assertRaises(subscription_change_service.SubscriptionChangeError) as caught:
                subscription_change_service.resolve_change_context(db, self._account(db, unauthorized))
            self.assertEqual(caught.exception.status_code, 403)
        finally:
            db.close()

    def test_tenant_isolation_and_http_authorization(self):
        first = self._fixture(quantity=3, active_branches=2)
        second = self._fixture(quantity=8, active_branches=1)
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, first["session_token"])
        self.client.cookies.set(service.SAAS_CSRF_COOKIE, first["csrf_token"])
        response = self.client.get("/saas/subscription/branches", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Paid Branches", response.text)
        self.assertNotIn(second["provider_subscription_id"], response.text)
        limited = self._fixture(quantity=3, active_branches=1, role=auth.ROLE_LIMITED)
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, limited["session_token"])
        self.client.cookies.set(service.SAAS_CSRF_COOKIE, limited["csrf_token"])
        denied = self.client.get("/saas/subscription/branches", follow_redirects=False)
        self.assertEqual(denied.status_code, 403)

    def test_paddle_client_methods_send_supported_payloads(self):
        items = [{"price_id": "pri_01abcdefghijklmnopqrstuvwx", "quantity": 5}]
        with patch.object(paddle_client, "_request", return_value={}) as request:
            paddle_client.preview_subscription_update(
                subscription_id="sub_01abcdefghijklmnopqrstuvwx", items=items,
                proration_billing_mode="prorated_immediately",
            )
            self.assertEqual(request.call_args.args[:2], ("PATCH", "/subscriptions/sub_01abcdefghijklmnopqrstuvwx/preview"))
            self.assertEqual(request.call_args.args[2]["items"], items)
            paddle_client.update_subscription(
                subscription_id="sub_01abcdefghijklmnopqrstuvwx", items=items,
                proration_billing_mode="prorated_immediately", on_payment_failure="prevent_change",
            )
            self.assertEqual(request.call_args.args[2]["on_payment_failure"], "prevent_change")

    def test_migration_is_idempotent_and_catalog_is_unchanged_by_workflow(self):
        fixture = self._fixture(quantity=3, active_branches=2)
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])
        db = self.Session()
        try:
            prices_before = [(row.id, row.amount_minor, row.provider_price_id) for row in db.query(saas.models.SubscriptionPlanPrice).order_by(saas.models.SubscriptionPlanPrice.id).all()]
        finally:
            db.close()
        self._preview(fixture, 4)
        db = self.Session()
        try:
            prices_after = [(row.id, row.amount_minor, row.provider_price_id) for row in db.query(saas.models.SubscriptionPlanPrice).order_by(saas.models.SubscriptionPlanPrice.id).all()]
            self.assertEqual(prices_before, prices_after)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
