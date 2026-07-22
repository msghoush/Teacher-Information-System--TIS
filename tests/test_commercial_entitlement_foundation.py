import unittest
import uuid
from datetime import datetime

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import auth
import db_migrations
import models
import saas.models
from commercial_entitlements import CommercialState
from saas import (
    branch_entitlement_service,
    commercial_state_service,
    commercial_validation_service,
    workspace_entitlement_service,
)


class CommercialEntitlementFoundationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _workspace(
        self,
        db,
        *,
        classification="internal_sandbox",
        lifecycle="active",
        entitlement_type=None,
        entitlement_status="active",
    ):
        unique = uuid.uuid4().hex[:10]
        group = models.SchoolGroup(
            name=f"Commercial Workspace {unique}",
            workspace_classification=classification,
            workspace_lifecycle_status=lifecycle,
        )
        db.add(group)
        db.flush()
        entitlement = None
        if entitlement_type:
            entitlement = saas.models.WorkspaceEntitlement(
                entitlement_uuid=str(uuid.uuid4()),
                school_group_id=group.id,
                entitlement_type=entitlement_type,
                status=entitlement_status,
                source="system",
            )
            db.add(entitlement)
            db.flush()
        return group, entitlement

    def _paid_workspace(self, db):
        unique = uuid.uuid4().hex[:10]
        plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="professional").one()
        group = models.SchoolGroup(
            name=f"Paid Workspace {unique}",
            workspace_classification="customer_paid",
            workspace_lifecycle_status="active",
        )
        db.add(group)
        db.flush()
        branch = models.Branch(
            school_group_id=group.id,
            name=f"Paid Branch {unique}",
            status=True,
        )
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=f"paid-{unique}@example.com",
            email_normalized=f"paid-{unique}@example.com",
            status="active",
            onboarding_status="tenant_active",
        )
        db.add_all([branch, account])
        db.flush()
        organization = saas.models.PendingOrganization(
            organization_uuid=str(uuid.uuid4()),
            owner_saas_account_id=account.id,
            organization_name=f"Paid Organization {unique}",
            status="tenant_active",
            billing_status="tenant_active",
            payment_status="paid",
        )
        user = models.User(
            user_id=unique,
            username=f"paid.{unique}",
            role=auth.ROLE_ADMINISTRATOR,
            school_group_id=group.id,
            branch_id=branch.id,
            is_active=True,
        )
        db.add_all([organization, user])
        db.flush()
        contract = saas.models.SubscriptionContract(
            pending_organization_id=organization.id,
            school_group_id=group.id,
            plan_id=plan.id,
            billing_interval="monthly",
            contract_status="tenant_active",
            payment_status="paid",
            paid_at=datetime(2026, 7, 1),
            base_amount_minor=7900,
            display_amount_minor=7900,
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
            quantity=1,
            status="active",
        )
        db.add(subscription)
        db.flush()
        db.add(saas.models.TenantProvisioningLink(
            pending_organization_id=organization.id,
            subscription_contract_id=contract.id,
            school_group_id=group.id,
            owner_operational_user_id=user.id,
            primary_branch_id=branch.id,
            tenant_status="tenant_active",
        ))
        entitlement = saas.models.WorkspaceEntitlement(
            entitlement_uuid=str(uuid.uuid4()),
            school_group_id=group.id,
            entitlement_type="paid",
            status="active",
            source="subscription",
            payment_subscription_id=subscription.id,
        )
        db.add(entitlement)
        db.flush()
        return group, branch, subscription, entitlement

    def test_internal_sandbox_resolves_read_only_with_compatibility_entitlement(self):
        db = self.Session()
        try:
            group, _ = self._workspace(db)
            db.commit()
            entitlement_count = db.query(saas.models.WorkspaceEntitlement).count()

            state = commercial_state_service.resolve_commercial_state(db, group.id)

            self.assertTrue(state.resolved)
            self.assertEqual(state.commercial_state, "internal_sandbox_active")
            self.assertEqual(state.workspace_entitlement.workspace_entitlement_id, None)
            self.assertEqual(
                state.workspace_entitlement.reason_code,
                "implicit_internal_sandbox_compatibility",
            )
            self.assertEqual(db.query(saas.models.WorkspaceEntitlement).count(), entitlement_count)
        finally:
            db.close()

    def test_demo_workspace_and_typed_entitlement_values_resolve(self):
        db = self.Session()
        try:
            group, entitlement = self._workspace(
                db, classification="customer_demo", entitlement_type="demo"
            )
            feature = saas.models.EntitlementDefinition(
                key=f"feature.demo.{uuid.uuid4().hex}",
                display_name="Demo Feature",
                category="demo",
                scope="organization",
                value_type="boolean",
                active=True,
            )
            limit = saas.models.EntitlementDefinition(
                key=f"quota.demo.{uuid.uuid4().hex}",
                display_name="Demo Limit",
                category="demo",
                scope="organization",
                value_type="integer",
                active=True,
            )
            db.add_all([feature, limit])
            db.flush()
            db.add_all([
                saas.models.WorkspaceEntitlementValue(
                    workspace_entitlement_id=entitlement.id,
                    entitlement_definition_id=feature.id,
                    value="true",
                ),
                saas.models.WorkspaceEntitlementValue(
                    workspace_entitlement_id=entitlement.id,
                    entitlement_definition_id=limit.id,
                    value="7",
                ),
            ])
            db.commit()

            resolution = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
            state = commercial_state_service.resolve_commercial_state(db, group.id)

            self.assertTrue(resolution.resolved)
            self.assertTrue(resolution.entitlements[feature.key].granted)
            self.assertEqual(resolution.entitlements[limit.key].value, 7)
            self.assertEqual(state.commercial_state, "customer_demo_active")
        finally:
            db.close()

    def test_paid_workspace_inherits_existing_confirmed_plan_entitlements(self):
        db = self.Session()
        try:
            group, _branch, subscription, entitlement = self._paid_workspace(db)
            db.commit()

            resolution = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
            state = commercial_state_service.resolve_commercial_state(db, group.id)

            self.assertTrue(resolution.resolved)
            self.assertEqual(resolution.payment_subscription_id, subscription.id)
            self.assertEqual(resolution.workspace_entitlement_id, entitlement.id)
            self.assertIn("quota.active_branches", resolution.entitlements)
            self.assertEqual(state.commercial_state, "customer_paid_active")
        finally:
            db.close()

    def test_paid_workspace_without_confirmed_subscription_fails_closed(self):
        db = self.Session()
        try:
            group, _ = self._workspace(
                db, classification="customer_paid", entitlement_type="paid"
            )
            db.commit()
            resolution = workspace_entitlement_service.resolve_workspace_entitlement(db, group.id)
            self.assertFalse(resolution.resolved)
            self.assertEqual(resolution.reason_code, "missing_paid_subscription_link")
            self.assertEqual(
                commercial_state_service.resolve_commercial_state(db, group.id).commercial_state,
                "manual_review",
            )
        finally:
            db.close()

    def test_invalid_entitlement_value_and_classification_mismatch_fail_closed(self):
        db = self.Session()
        try:
            group, entitlement = self._workspace(
                db, classification="customer_demo", entitlement_type="demo"
            )
            definition = saas.models.EntitlementDefinition(
                key=f"quota.invalid.{uuid.uuid4().hex}",
                display_name="Invalid Limit",
                category="test",
                scope="organization",
                value_type="integer",
                active=True,
            )
            db.add(definition)
            db.flush()
            db.add(saas.models.WorkspaceEntitlementValue(
                workspace_entitlement_id=entitlement.id,
                entitlement_definition_id=definition.id,
                value="-1",
            ))
            db.commit()
            self.assertEqual(
                workspace_entitlement_service.resolve_workspace_entitlement(db, group.id).reason_code,
                "invalid_entitlement_value",
            )

            mismatch_group, _ = self._workspace(
                db, classification="customer_demo", entitlement_type="internal_sandbox"
            )
            db.commit()
            self.assertEqual(
                workspace_entitlement_service.resolve_workspace_entitlement(
                    db, mismatch_group.id
                ).reason_code,
                "classification_entitlement_mismatch",
            )
        finally:
            db.close()

    def test_branch_effective_active_inactive_and_inherited_resolution(self):
        db = self.Session()
        try:
            group, entitlement = self._workspace(db, entitlement_type="internal_sandbox")
            inherited_active = models.Branch(
                school_group_id=group.id, name="Inherited Active", status=True
            )
            inherited_inactive = models.Branch(
                school_group_id=group.id, name="Inherited Operational Inactive", status=False
            )
            explicit_inactive = models.Branch(
                school_group_id=group.id, name="Commercial Inactive", status=True
            )
            db.add_all([inherited_active, inherited_inactive, explicit_inactive])
            db.flush()
            db.add(saas.models.BranchEntitlement(
                branch_entitlement_uuid=str(uuid.uuid4()),
                school_group_id=group.id,
                branch_id=explicit_inactive.id,
                workspace_entitlement_id=entitlement.id,
                entitlement_mode="inactive",
                reason_code="not_selected",
            ))
            db.commit()

            first = branch_entitlement_service.resolve_branch_entitlement(
                db, inherited_active.id
            )
            second = branch_entitlement_service.resolve_branch_entitlement(
                db, inherited_inactive.id
            )
            third = branch_entitlement_service.resolve_branch_entitlement(
                db, explicit_inactive.id
            )
            summary = branch_entitlement_service.summarize_branch_entitlements(db, group.id)

            self.assertEqual(first.effective_status, "active")
            self.assertTrue(first.inherits_workspace)
            self.assertEqual(second.effective_status, "inactive")
            self.assertTrue(second.inherits_workspace)
            self.assertEqual(third.effective_status, "inactive")
            self.assertFalse(third.inherits_workspace)
            self.assertEqual((summary.active_count, summary.inactive_count), (1, 2))
            self.assertEqual(summary.inherited_count, 2)
        finally:
            db.close()

    def test_orphan_branch_entitlement_and_cross_tenant_request_fail_closed(self):
        db = self.Session()
        try:
            first_group, _first_entitlement = self._workspace(
                db, entitlement_type="internal_sandbox"
            )
            second_group, second_entitlement = self._workspace(
                db, entitlement_type="internal_sandbox"
            )
            branch = models.Branch(
                school_group_id=first_group.id, name="Scoped Branch", status=True
            )
            db.add(branch)
            db.flush()
            db.add(saas.models.BranchEntitlement(
                branch_entitlement_uuid=str(uuid.uuid4()),
                school_group_id=second_group.id,
                branch_id=branch.id,
                workspace_entitlement_id=second_entitlement.id,
                entitlement_mode="active",
            ))
            db.commit()

            orphan = branch_entitlement_service.resolve_branch_entitlement(db, branch.id)
            cross_tenant = branch_entitlement_service.resolve_branch_entitlement(
                db, branch.id, school_group_id=second_group.id
            )
            self.assertFalse(orphan.resolved)
            self.assertEqual(orphan.reason_code, "orphan_branch_entitlement")
            self.assertFalse(cross_tenant.resolved)
            self.assertEqual(cross_tenant.reason_code, "branch_workspace_mismatch")
        finally:
            db.close()

    def test_invalid_enums_and_duplicate_active_entitlements_are_rejected(self):
        with self.assertRaises(commercial_validation_service.CommercialValidationError):
            commercial_validation_service.validate_commercial_state("demo_expired")
        with self.assertRaises(commercial_validation_service.CommercialValidationError):
            commercial_validation_service.validate_branch_entitlement_mode("enabled")
        self.assertEqual(
            commercial_validation_service.validate_commercial_state("manual_review"),
            CommercialState.MANUAL_REVIEW,
        )

        db = self.Session()
        try:
            group, _ = self._workspace(db, entitlement_type="internal_sandbox")
            db.add(saas.models.WorkspaceEntitlement(
                entitlement_uuid=str(uuid.uuid4()),
                school_group_id=group.id,
                entitlement_type="internal_sandbox",
                status="active",
                source="system",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()


class CommercialEntitlementMigrationTests(unittest.TestCase):
    def test_migration_creates_tables_and_idempotently_seeds_existing_workspace(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    """
                    CREATE TABLE school_groups (
                        id INTEGER PRIMARY KEY,
                        workspace_classification VARCHAR(32) NOT NULL,
                        workspace_lifecycle_status VARCHAR(20) NOT NULL
                    )
                    """
                ))
                connection.execute(text("CREATE TABLE branches (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE payment_subscriptions (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE subscription_contracts (id INTEGER PRIMARY KEY, school_group_id INTEGER)"))
                connection.execute(text("CREATE TABLE entitlement_definitions (id INTEGER PRIMARY KEY)"))
                connection.execute(text(
                    "INSERT INTO school_groups VALUES (1, 'internal_sandbox', 'active')"
                ))
                db_migrations._commercial_entitlement_foundation(engine, connection)
                db_migrations._commercial_entitlement_foundation(engine, connection)

            inspector = inspect(engine)
            self.assertTrue({
                "workspace_entitlements",
                "workspace_entitlement_values",
                "branch_entitlements",
            }.issubset(set(inspector.get_table_names())))
            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT entitlement_type, status, source FROM workspace_entitlements"
                )).all()
            self.assertEqual(rows, [("internal_sandbox", "active", "migration")])
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
