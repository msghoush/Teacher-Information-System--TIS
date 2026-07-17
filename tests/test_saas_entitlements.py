from datetime import datetime
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import auth
import authorization
import db_migrations
import models
import saas.models
from saas import entitlement_service
from ui_shell import build_shell_context


class SaaSEntitlementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(bind=self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _request(path="/dashboard", method="GET"):
        return Request({
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
        })

    def _create_subscription(
        self,
        *,
        plan_code,
        quantity,
        active_branches=1,
        email=None,
        role=auth.ROLE_ADMINISTRATOR,
    ):
        db = self.Session()
        try:
            unique = uuid.uuid4().hex[:10]
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code=plan_code).one()
            group = models.SchoolGroup(name=f"Entitlement Group {unique}")
            db.add(group)
            db.flush()
            branches = []
            for index in range(active_branches):
                branch = models.Branch(
                    school_group_id=group.id,
                    name=f"Branch {index + 1} {unique}",
                    status=True,
                )
                db.add(branch)
                branches.append(branch)
            db.flush()
            account_email = email or f"entitlement-{unique}@example.com"
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=account_email,
                email_normalized=account_email,
                status="active",
                onboarding_status="tenant_active",
            )
            db.add(account)
            db.flush()
            organization = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=account.id,
                organization_name=f"Pending {unique}",
                status="tenant_active",
                onboarding_step="completed",
                billing_status="tenant_active",
                payment_status="paid",
                payment_confirmed_at=datetime(2026, 7, 1),
            )
            db.add(organization)
            db.flush()
            user = models.User(
                user_id=unique,
                username=f"user.{unique}",
                email=account_email,
                email_normalized=account_email,
                password="unused",
                role=role,
                school_group_id=group.id,
                branch_id=branches[0].id if branches else None,
                is_active=True,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            )
            db.add(user)
            db.flush()
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id,
                school_group_id=group.id,
                plan_id=plan.id,
                billing_interval="monthly",
                contract_status="tenant_active",
                payment_status="paid",
                paid_at=datetime(2026, 7, 1),
                base_amount_minor=2900,
                display_amount_minor=2900,
            )
            db.add(contract)
            db.flush()
            subscription = saas.models.PaymentSubscription(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                provider="paddle",
                provider_subscription_id=f"sub_{uuid.uuid4().hex}",
                plan_id=plan.id,
                billing_interval="monthly",
                quantity=quantity,
                status="active",
            )
            db.add(subscription)
            db.flush()
            link = saas.models.TenantProvisioningLink(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                school_group_id=group.id,
                owner_operational_user_id=user.id,
                primary_branch_id=branches[0].id if branches else None,
                tenant_status="tenant_active",
                activated_at=datetime(2026, 7, 1),
            )
            db.add(link)
            db.commit()
            return {
                "group_id": group.id,
                "plan_id": plan.id,
                "contract_id": contract.id,
                "organization_id": organization.id,
                "subscription_id": subscription.id,
                "user_id": user.id,
            }
        finally:
            db.close()

    def _user(self, db, fixture):
        user = db.query(models.User).filter_by(id=fixture["user_id"]).one()
        user.scope_school_group_id = fixture["group_id"]
        user.scope_branch_id = user.branch_id
        user.scope_academic_year_id = None
        return user

    def test_migration_seeds_normalized_conservative_matrix(self):
        db = self.Session()
        try:
            self.assertEqual(db.query(saas.models.EntitlementDefinition).count(), 11)
            self.assertEqual(db.query(saas.models.PlanEntitlement).count(), 33)
            export_definition = db.query(saas.models.EntitlementDefinition).filter_by(
                key="feature.export"
            ).one()
            export_rows = db.query(saas.models.PlanEntitlement).filter_by(
                entitlement_definition_id=export_definition.id
            ).all()
            self.assertEqual(
                {row.status for row in export_rows},
                {entitlement_service.OWNER_APPROVAL_REQUIRED},
            )
        finally:
            db.close()

    def test_starter_professional_and_enterprise_resolution(self):
        starter = self._create_subscription(plan_code="starter", quantity=2)
        professional = self._create_subscription(plan_code="professional", quantity=3)
        enterprise = self._create_subscription(plan_code="enterprise_ai", quantity=4)
        db = self.Session()
        try:
            starter_result = entitlement_service.resolve_entitlements(db, starter["group_id"])
            professional_result = entitlement_service.resolve_entitlements(db, professional["group_id"])
            enterprise_result = entitlement_service.resolve_entitlements(db, enterprise["group_id"])
            self.assertEqual(starter_result.plan_code, "starter")
            self.assertFalse(starter_result.entitlements["feature.advanced_reporting"].granted)
            self.assertFalse(starter_result.entitlements["module.ai"].granted)
            self.assertTrue(professional_result.entitlements["feature.advanced_reporting"].granted)
            self.assertFalse(professional_result.entitlements["module.ai"].granted)
            self.assertTrue(enterprise_result.entitlements["feature.advanced_reporting"].granted)
            self.assertTrue(enterprise_result.entitlements["module.ai"].granted)
        finally:
            db.close()

    def test_decimal_and_text_entitlement_values_are_typed(self):
        fixture = self._create_subscription(plan_code="professional", quantity=1)
        db = self.Session()
        try:
            decimal_definition = saas.models.EntitlementDefinition(
                key="feature.decimal_test",
                display_name="Decimal Test",
                category="feature",
                scope="organization",
                value_type="decimal",
                active=True,
            )
            text_definition = saas.models.EntitlementDefinition(
                key="feature.text_test",
                display_name="Text Test",
                category="feature",
                scope="organization",
                value_type="text",
                active=True,
            )
            db.add_all([decimal_definition, text_definition])
            db.flush()
            db.add_all([
                saas.models.PlanEntitlement(
                    subscription_plan_id=fixture["plan_id"],
                    entitlement_definition_id=decimal_definition.id,
                    value="12.50",
                    status="active",
                ),
                saas.models.PlanEntitlement(
                    subscription_plan_id=fixture["plan_id"],
                    entitlement_definition_id=text_definition.id,
                    value="regional",
                    status="active",
                ),
            ])
            db.commit()
            result = entitlement_service.resolve_entitlements(db, fixture["group_id"])
            self.assertEqual(str(result.entitlements["feature.decimal_test"].value), "12.50")
            self.assertEqual(result.entitlements["feature.text_test"].value, "regional")
        finally:
            db.close()

    def test_paid_quantity_is_independent_of_legacy_plan_branch_metadata(self):
        starter = self._create_subscription(plan_code="starter", quantity=100, active_branches=2)
        enterprise = self._create_subscription(plan_code="enterprise_ai", quantity=1, active_branches=1)
        db = self.Session()
        try:
            starter_result = entitlement_service.resolve_entitlements(db, starter["group_id"])
            self.assertEqual(starter_result.paid_branch_quantity, 100)
            self.assertEqual(starter_result.active_branch_count, 2)
            self.assertEqual(starter_result.remaining_paid_capacity, 98)
            self.assertFalse(starter_result.is_at_capacity)
            enterprise_result = entitlement_service.resolve_entitlements(db, enterprise["group_id"])
            self.assertEqual(enterprise_result.paid_branch_quantity, 1)
            self.assertTrue(enterprise_result.is_at_capacity)
            self.assertEqual(
                enterprise_result.entitlements["quota.active_branches"].value,
                1,
            )
        finally:
            db.close()

    def test_over_capacity_is_reported_without_mutation(self):
        fixture = self._create_subscription(plan_code="professional", quantity=1, active_branches=2)
        db = self.Session()
        try:
            result = entitlement_service.resolve_entitlements(db, fixture["group_id"])
            self.assertTrue(result.is_over_capacity)
            self.assertFalse(result.is_at_capacity)
            self.assertEqual(result.remaining_paid_capacity, 0)
            self.assertEqual(db.query(models.Branch).filter_by(school_group_id=fixture["group_id"]).count(), 2)
        finally:
            db.close()

    def test_missing_and_ambiguous_subscription_fail_closed(self):
        missing = self._create_subscription(plan_code="professional", quantity=2)
        ambiguous = self._create_subscription(plan_code="professional", quantity=2)
        db = self.Session()
        try:
            db.query(saas.models.PaymentSubscription).filter_by(id=missing["subscription_id"]).delete()
            first = db.query(saas.models.PaymentSubscription).filter_by(id=ambiguous["subscription_id"]).one()
            db.add(saas.models.PaymentSubscription(
                pending_organization_id=first.pending_organization_id,
                subscription_contract_id=first.subscription_contract_id,
                provider="paddle",
                provider_subscription_id=f"sub_{uuid.uuid4().hex}",
                plan_id=first.plan_id,
                billing_interval=first.billing_interval,
                quantity=first.quantity,
                status="active",
            ))
            db.commit()
            missing_result = entitlement_service.resolve_entitlements(db, missing["group_id"])
            ambiguous_result = entitlement_service.resolve_entitlements(db, ambiguous["group_id"])
            self.assertEqual(missing_result.resolution_status, entitlement_service.MANUAL_REVIEW)
            self.assertEqual(missing_result.reason_code, "missing_confirmed_subscription")
            self.assertEqual(ambiguous_result.resolution_status, entitlement_service.MANUAL_REVIEW)
            self.assertEqual(ambiguous_result.reason_code, "ambiguous_confirmed_subscription")
            self.assertFalse(entitlement_service.has_entitlement(
                db, missing["group_id"], "feature.advanced_reporting"
            ))
        finally:
            db.close()

    def test_active_provider_subscription_outweighs_stale_pending_contract_payment_status(self):
        fixture = self._create_subscription(plan_code="professional", quantity=4, active_branches=3)
        db = self.Session()
        try:
            contract = db.query(saas.models.SubscriptionContract).filter_by(id=fixture["contract_id"]).one()
            contract.payment_status = "pending"
            db.commit()

            result = entitlement_service.resolve_entitlements(db, fixture["group_id"])

            self.assertTrue(result.resolved)
            self.assertEqual(result.reason_code, "resolved")
            self.assertEqual(result.paid_branch_quantity, 4)
            self.assertEqual(result.active_branch_count, 3)
            self.assertEqual(db.query(saas.models.PaymentAttempt).count(), 0)
            self.assertEqual(contract.payment_status, "pending")
        finally:
            db.close()

    def test_stale_pending_contract_still_requires_paid_timestamp_and_active_subscription(self):
        missing_paid_at = self._create_subscription(plan_code="professional", quantity=2)
        inactive_subscription = self._create_subscription(plan_code="professional", quantity=2)
        failed_contract = self._create_subscription(plan_code="professional", quantity=2)
        db = self.Session()
        try:
            missing_contract = db.query(saas.models.SubscriptionContract).filter_by(
                id=missing_paid_at["contract_id"]
            ).one()
            missing_contract.payment_status = "pending"
            missing_contract.paid_at = None

            inactive_contract = db.query(saas.models.SubscriptionContract).filter_by(
                id=inactive_subscription["contract_id"]
            ).one()
            inactive_contract.payment_status = "pending"
            db.query(saas.models.PaymentSubscription).filter_by(
                id=inactive_subscription["subscription_id"]
            ).one().status = "paused"

            failed = db.query(saas.models.SubscriptionContract).filter_by(
                id=failed_contract["contract_id"]
            ).one()
            failed.payment_status = "failed"
            db.commit()

            missing_result = entitlement_service.resolve_entitlements(db, missing_paid_at["group_id"])
            inactive_result = entitlement_service.resolve_entitlements(db, inactive_subscription["group_id"])
            failed_result = entitlement_service.resolve_entitlements(db, failed_contract["group_id"])

            self.assertEqual(missing_result.reason_code, "contract_not_confirmed_paid")
            self.assertEqual(inactive_result.reason_code, "subscription_not_entitled")
            self.assertEqual(failed_result.reason_code, "contract_not_confirmed_paid")
            self.assertFalse(missing_result.resolved)
            self.assertFalse(inactive_result.resolved)
            self.assertFalse(failed_result.resolved)
        finally:
            db.close()

    def test_permission_and_entitlement_must_both_succeed(self):
        starter = self._create_subscription(plan_code="starter", quantity=1)
        professional = self._create_subscription(plan_code="professional", quantity=1)
        no_permission = self._create_subscription(
            plan_code="professional",
            quantity=1,
            role=auth.ROLE_LIMITED,
        )
        db = self.Session()
        try:
            self.assertFalse(entitlement_service.can_use_feature(
                db, self._user(db, starter), "feature.advanced_reporting", "reports.export"
            ))
            self.assertTrue(entitlement_service.can_use_feature(
                db, self._user(db, professional), "feature.advanced_reporting", "reports.export"
            ))
            self.assertFalse(entitlement_service.can_use_feature(
                db, self._user(db, no_permission), "feature.advanced_reporting", "reports.export"
            ))
        finally:
            db.close()

    def test_platform_users_do_not_bypass_entitlements(self):
        starter = self._create_subscription(plan_code="starter", quantity=1)
        professional = self._create_subscription(plan_code="professional", quantity=1)
        db = self.Session()
        try:
            platform_users = []
            for user_id, username, platform_role in (
                ("ENTOWN0001", "entitlement.owner", auth.PLATFORM_ROLE_OWNER),
                ("ENTDEV0001", "entitlement.developer", auth.PLATFORM_ROLE_DEVELOPER),
            ):
                platform_user = models.User(
                    user_id=user_id,
                    username=username,
                    email=f"{username}@example.com",
                    email_normalized=f"{username}@example.com",
                    password="unused",
                    role="Owner" if platform_role == auth.PLATFORM_ROLE_OWNER else "Developer",
                    user_type=auth.USER_TYPE_PLATFORM,
                    platform_role=platform_role,
                    access_scope=auth.ACCESS_SCOPE_GLOBAL,
                    is_active=True,
                )
                db.add(platform_user)
                platform_users.append(platform_user)
            db.flush()
            for platform_user in platform_users:
                platform_user.scope_school_group_id = starter["group_id"]
                self.assertFalse(entitlement_service.can_use_feature(
                    db, platform_user, "feature.advanced_reporting", "reports.export"
                ))
                platform_user.scope_school_group_id = professional["group_id"]
                self.assertTrue(entitlement_service.can_use_feature(
                    db, platform_user, "feature.advanced_reporting", "reports.export"
                ))
                platform_user.scope_school_group_id = None
                self.assertFalse(entitlement_service.can_use_feature(
                    db, platform_user, "feature.advanced_reporting", "reports.export"
                ))
        finally:
            db.close()

    def test_tenant_isolation_blocks_cross_tenant_entitlement_use(self):
        first = self._create_subscription(plan_code="professional", quantity=1)
        second = self._create_subscription(plan_code="professional", quantity=1)
        db = self.Session()
        try:
            user = self._user(db, first)
            self.assertFalse(entitlement_service.can_use_feature(
                db,
                user,
                "feature.advanced_reporting",
                "reports.export",
                school_group_id=second["group_id"],
            ))
        finally:
            db.close()

    def test_require_entitlement_and_module_helper_fail_closed(self):
        starter = self._create_subscription(plan_code="starter", quantity=1)
        enterprise = self._create_subscription(plan_code="enterprise_ai", quantity=1)
        db = self.Session()
        try:
            with self.assertRaises(entitlement_service.EntitlementRequiredError):
                entitlement_service.require_entitlement(
                    db, starter["group_id"], "module.ai"
                )
            result = entitlement_service.require_entitlement(
                db, enterprise["group_id"], "module.ai"
            )
            self.assertTrue(result.resolved)
            self.assertTrue(entitlement_service.can_access_module(
                db,
                self._user(db, enterprise),
                "ai",
                "reports.export",
            ))
        finally:
            db.close()

    def test_template_helper_combines_permission_and_entitlement(self):
        professional = self._create_subscription(plan_code="professional", quantity=1)
        db = self.Session()
        try:
            context = build_shell_context(
                self._request(),
                db,
                self._user(db, professional),
                page_key="dashboard",
            )
            self.assertTrue(context["can_use_feature"](
                "feature.advanced_reporting", "reports.export"
            ))
        finally:
            db.close()

    def test_backend_pilot_enforcement_denies_starter_and_allows_professional(self):
        starter = self._create_subscription(plan_code="starter", quantity=1)
        professional = self._create_subscription(plan_code="professional", quantity=1)
        request = self._request("/reports/allocation-plan.xlsx")
        db = self.Session()
        try:
            denied_marker = object()
            with patch("authorization.build_access_denied_response", return_value=denied_marker):
                denied = authorization.enforce_route_permission(
                    request,
                    db,
                    current_user=self._user(db, starter),
                )
            self.assertIs(denied, denied_marker)
            allowed = authorization.enforce_route_permission(
                request,
                db,
                current_user=self._user(db, professional),
            )
            self.assertIsNone(allowed)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
