import unittest

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import db_migrations
import models
import saas.models
from saas import workspace_classification_service
from saas.workspace_classification_admin_service import (
    apply_workspace_classification_backfill,
    build_workspace_classification_backfill_plan,
    collect_workspace_diagnostics,
)
from workspace_classification import (
    AccountPurpose,
    WorkspaceClassification,
    WorkspaceIntent,
    WorkspaceLifecycleStatus,
)


class WorkspaceClassificationFoundationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        with self.engine.begin() as connection:
            connection.execute(text(
                """
                CREATE TABLE schema_migrations (
                    migration_id VARCHAR(120) PRIMARY KEY,
                    description VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ))
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _seed_legacy_data(self):
        account = saas.models.SaaSAccount(
            account_uuid="00000000-0000-0000-0000-000000000001",
            email="test@example.com",
            email_normalized="test@example.com",
            account_purpose=AccountPurpose.CUSTOMER.value,
        )
        self.db.add(account)
        self.db.flush()
        organization = saas.models.PendingOrganization(
            organization_uuid="00000000-0000-0000-0000-000000000002",
            owner_saas_account_id=account.id,
            organization_name="Existing Test Organization",
            workspace_intent=WorkspaceIntent.CUSTOMER_PAID.value,
        )
        group = models.SchoolGroup(
            name="Existing Test Workspace",
            workspace_classification=WorkspaceClassification.CUSTOMER_PAID.value,
            workspace_lifecycle_status=WorkspaceLifecycleStatus.ACTIVE.value,
            status=False,
        )
        tenant_user = models.User(
            user_id="880001",
            username="legacy.tenant",
            user_type="TENANT",
            is_internal_test_identity=False,
        )
        platform_user = models.User(
            user_id="880002",
            username="legacy.platform",
            user_type="PLATFORM",
            is_internal_test_identity=False,
        )
        self.db.add_all([organization, group, tenant_user, platform_user])
        self.db.commit()
        return account, organization, group, tenant_user, platform_user

    def test_enums_and_validation_helpers_accept_only_supported_values(self):
        self.assertEqual(
            workspace_classification_service.validate_classification("INTERNAL_SANDBOX"),
            WorkspaceClassification.INTERNAL_SANDBOX,
        )
        self.assertEqual(
            workspace_classification_service.validate_lifecycle_status("active"),
            WorkspaceLifecycleStatus.ACTIVE,
        )
        self.assertEqual(
            workspace_classification_service.validate_workspace_intent("customer_demo"),
            WorkspaceIntent.CUSTOMER_DEMO,
        )
        self.assertEqual(
            workspace_classification_service.validate_account_purpose("customer"),
            AccountPurpose.CUSTOMER,
        )
        with self.assertRaises(workspace_classification_service.WorkspaceClassificationValidationError):
            workspace_classification_service.validate_classification("legacy")
        with self.assertRaises(workspace_classification_service.WorkspaceClassificationValidationError):
            workspace_classification_service.validate_lifecycle_status("deleted")

    def test_classification_transitions_are_validation_only_and_conversion_is_blocked(self):
        self.assertEqual(
            workspace_classification_service.validate_classification_transition(
                "internal_sandbox", "internal_sandbox"
            ),
            WorkspaceClassification.INTERNAL_SANDBOX,
        )
        with self.assertRaises(workspace_classification_service.WorkspaceClassificationTransitionError):
            workspace_classification_service.validate_classification_transition(
                "internal_sandbox", "customer_paid"
            )
        self.assertEqual(
            workspace_classification_service.validate_lifecycle_transition(
                "provisioning", "active"
            ),
            WorkspaceLifecycleStatus.ACTIVE,
        )
        with self.assertRaises(workspace_classification_service.WorkspaceClassificationTransitionError):
            workspace_classification_service.validate_lifecycle_transition(
                "archived", "active"
            )

    def test_new_models_have_defaults_indexes_and_named_constraints(self):
        group = models.SchoolGroup(name="Default Workspace")
        account = saas.models.SaaSAccount(
            account_uuid="00000000-0000-0000-0000-000000000010",
            email="defaults@example.com",
            email_normalized="defaults@example.com",
        )
        self.db.add_all([group, account])
        self.db.flush()
        organization = saas.models.PendingOrganization(
            organization_uuid="00000000-0000-0000-0000-000000000011",
            owner_saas_account_id=account.id,
            organization_name="Default Organization",
        )
        user = models.User(user_id="880010", username="default.user")
        self.db.add_all([organization, user])
        self.db.commit()

        self.assertEqual(len(group.workspace_uuid), 36)
        self.assertEqual(group.workspace_classification, "internal_sandbox")
        self.assertEqual(group.workspace_lifecycle_status, "active")
        self.assertEqual(organization.workspace_intent, "internal_sandbox")
        self.assertEqual(account.account_purpose, "internal_test")
        self.assertFalse(user.is_internal_test_identity)

        inspector = inspect(self.engine)
        self.assertIn(
            "ck_school_groups_workspace_classification",
            {row["name"] for row in inspector.get_check_constraints("school_groups")},
        )
        self.assertIn(
            "ck_pending_organizations_workspace_intent",
            {row["name"] for row in inspector.get_check_constraints("pending_organizations")},
        )
        self.assertIn(
            "ck_saas_accounts_account_purpose",
            {row["name"] for row in inspector.get_check_constraints("saas_accounts")},
        )
        self.assertIn(
            "uq_school_groups_workspace_uuid",
            {row["name"] for row in inspector.get_indexes("school_groups")},
        )

    def test_database_rejects_invalid_classification(self):
        self.db.add(models.SchoolGroup(
            name="Invalid Workspace",
            workspace_classification="production",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_diagnostic_is_read_only_and_reports_every_workspace(self):
        group = models.SchoolGroup(name="Diagnostic Workspace")
        self.db.add(group)
        self.db.commit()
        original = (group.workspace_classification, group.workspace_lifecycle_status)

        report = collect_workspace_diagnostics(self.db)

        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["school_group_id"], group.id)
        self.assertFalse(report[0]["onboarding_relationship"]["linked"])
        self.assertFalse(report[0]["paddle_relationship"]["has_provider_subscription"])
        self.assertEqual(report[0]["suggested_classification"], "internal_sandbox")
        self.db.refresh(group)
        self.assertEqual(
            (group.workspace_classification, group.workspace_lifecycle_status), original
        )

    def test_backfill_dry_run_apply_and_idempotency(self):
        account, organization, group, tenant_user, platform_user = self._seed_legacy_data()

        dry_run = build_workspace_classification_backfill_plan(self.db)
        self.assertEqual(dry_run["status"], "ready")
        self.assertEqual(dry_run["mode"], "dry_run")
        self.assertEqual(group.workspace_classification, "customer_paid")
        self.assertEqual(account.account_purpose, "customer")

        applied = apply_workspace_classification_backfill(self.db)
        self.db.commit()
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(group.workspace_classification, "internal_sandbox")
        self.assertEqual(group.workspace_lifecycle_status, "suspended")
        self.assertEqual(organization.workspace_intent, "internal_sandbox")
        self.assertEqual(account.account_purpose, "internal_test")
        self.assertTrue(tenant_user.is_internal_test_identity)
        self.assertFalse(platform_user.is_internal_test_identity)

        repeated = apply_workspace_classification_backfill(self.db)
        self.db.commit()
        self.assertEqual(repeated["status"], "already_applied")
        self.assertEqual(repeated["changes"], {})

    def test_backfill_changes_rollback_as_one_transaction(self):
        account, _organization, group, tenant_user, _platform_user = self._seed_legacy_data()
        apply_workspace_classification_backfill(self.db)
        self.db.rollback()

        self.db.expire_all()
        self.assertEqual(group.workspace_classification, "customer_paid")
        self.assertEqual(account.account_purpose, "customer")
        self.assertFalse(tenant_user.is_internal_test_identity)
        self.assertEqual(build_workspace_classification_backfill_plan(self.db)["status"], "ready")


class WorkspaceClassificationLegacyMigrationTests(unittest.TestCase):
    def test_legacy_migration_adds_and_backfills_columns_indexes_and_guards(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE school_groups (id INTEGER PRIMARY KEY, name VARCHAR(160), status BOOLEAN)"
                ))
                connection.execute(text(
                    "CREATE TABLE pending_organizations (id INTEGER PRIMARY KEY, organization_uuid VARCHAR(36))"
                ))
                connection.execute(text(
                    "CREATE TABLE saas_accounts (id INTEGER PRIMARY KEY, account_uuid VARCHAR(36))"
                ))
                connection.execute(text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, user_type VARCHAR(20))"
                ))
                connection.execute(text(
                    "INSERT INTO school_groups (id, name, status) VALUES (1, 'Active', TRUE), (2, 'Inactive', FALSE)"
                ))
                connection.execute(text("INSERT INTO pending_organizations (id) VALUES (1)"))
                connection.execute(text("INSERT INTO saas_accounts (id) VALUES (1)"))
                connection.execute(text("INSERT INTO users (id, user_type) VALUES (1, 'TENANT')"))
                db_migrations._workspace_classification_foundation(engine, connection)

            inspector = inspect(engine)
            self.assertTrue({
                "workspace_uuid", "workspace_classification", "workspace_lifecycle_status"
            }.issubset({row["name"] for row in inspector.get_columns("school_groups")}))
            self.assertIn(
                "workspace_intent",
                {row["name"] for row in inspector.get_columns("pending_organizations")},
            )
            self.assertIn(
                "account_purpose",
                {row["name"] for row in inspector.get_columns("saas_accounts")},
            )
            self.assertIn(
                "is_internal_test_identity",
                {row["name"] for row in inspector.get_columns("users")},
            )
            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT workspace_uuid, workspace_classification, workspace_lifecycle_status "
                    "FROM school_groups ORDER BY id"
                )).all()
                self.assertTrue(all(len(row[0]) == 36 for row in rows))
                self.assertEqual(rows[0][1:], ("internal_sandbox", "active"))
                self.assertEqual(rows[1][1:], ("internal_sandbox", "suspended"))
                with self.assertRaises(Exception):
                    connection.execute(text(
                        "UPDATE school_groups SET workspace_classification = 'legacy' WHERE id = 1"
                    ))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
