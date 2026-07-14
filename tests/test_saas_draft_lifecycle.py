import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
import saas.models  # noqa: F401 - register SaaS metadata
from saas import draft_lifecycle_service, service


class SaaSDraftLifecycleTests(unittest.TestCase):
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

    def _account(self, db, email="draft@example.com"):
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=email,
            email_normalized=email.lower(),
            status="active",
            onboarding_status="not_started",
        )
        db.add(account)
        db.flush()
        return account

    @staticmethod
    def _now():
        return datetime.now(UTC).replace(tzinfo=None)

    def _organization(self, db, account, *, activity_at=None):
        organization = saas.models.PendingOrganization(
            organization_uuid=str(uuid.uuid4()),
            owner_saas_account_id=account.id,
            organization_name="Lifecycle Academy",
            status="draft",
            onboarding_step="organization",
            last_meaningful_activity_at=activity_at or datetime.utcnow(),
        )
        db.add(organization)
        db.flush()
        return organization

    def test_new_account_receives_initial_meaningful_activity_timestamp(self):
        db = self.Session()
        try:
            account, _policy = service.create_account(
                db,
                email="new.lifecycle@example.com",
                password="strong-password-123",
            )
            db.flush()
            self.assertIsNotNone(account.last_meaningful_activity_at)
            event = db.query(saas.models.SaaSAuthEvent).filter_by(
                saas_account_id=account.id,
                event_type="meaningful_activity_recorded",
            ).first()
            self.assertIsNotNone(event)
            self.assertIn('"source":"account_created"', event.details_json)
        finally:
            db.close()

    def test_production_activity_writes_are_centralized_in_lifecycle_service(self):
        project_root = Path(__file__).resolve().parent.parent
        allowed_files = {
            project_root / "saas" / "draft_lifecycle_service.py",
            project_root / "saas" / "models.py",
        }
        unexpected_references = []
        for path in (project_root / "saas").glob("*.py"):
            if path in allowed_files:
                continue
            if "last_meaningful_activity_at" in path.read_text(encoding="utf-8"):
                unexpected_references.append(path.name)
        self.assertEqual(unexpected_references, [])

    def test_day_29_activity_restarts_retention_and_resets_reminder_cycle(self):
        db = self.Session()
        try:
            now = datetime(2026, 7, 14, 12, 0, 0)
            old_activity = now - timedelta(days=29)
            account = self._account(db)
            organization = self._organization(db, account, activity_at=old_activity)
            account.last_meaningful_activity_at = old_activity
            account.first_reminder_sent_at = old_activity + timedelta(days=1)
            account.second_reminder_sent_at = old_activity + timedelta(days=7)
            account.final_reminder_sent_at = old_activity + timedelta(days=25)

            before = draft_lifecycle_service.resolve_draft_lifecycle(
                db, account, organization=organization, now=now
            )
            self.assertFalse(before.deletion_eligible)
            self.assertEqual(before.deletion_eligible_at, old_activity + timedelta(days=30))

            draft_lifecycle_service.record_meaningful_activity(
                db,
                account,
                organization=organization,
                source="successful_login",
                occurred_at=now,
            )
            db.flush()
            after = draft_lifecycle_service.resolve_draft_lifecycle(
                db, account, organization=organization, now=now
            )
            self.assertEqual(after.deletion_eligible_at, now + timedelta(days=30))
            self.assertEqual(account.reminder_cycle, 2)
            self.assertIsNone(account.first_reminder_sent_at)
            self.assertIsNone(account.second_reminder_sent_at)
            self.assertIsNone(account.final_reminder_sent_at)
            self.assertEqual(account.recovered_after_reminder_at, now)
            event_types = {
                row.event_type
                for row in db.query(saas.models.PendingOrganizationEvent).filter_by(
                    pending_organization_id=organization.id
                ).all()
            }
            self.assertTrue({
                "meaningful_activity_recorded",
                "draft_recovered_after_inactivity",
                "reminder_cycle_reset",
            }.issubset(event_types), event_types)
        finally:
            db.close()

    def test_configurable_retention_threshold_controls_candidate_date(self):
        db = self.Session()
        try:
            setting = db.query(saas.models.SaaSDraftLifecycleSetting).filter_by(id=1).one()
            setting.first_reminder_hours = 12
            setting.second_reminder_days = 5
            setting.final_reminder_days = 15
            setting.deletion_days = 40
            activity_at = datetime(2026, 5, 1, 9, 0, 0)
            account = self._account(db)
            account.last_meaningful_activity_at = activity_at

            not_due = draft_lifecycle_service.resolve_draft_lifecycle(
                db, account, now=activity_at + timedelta(days=39, hours=23)
            )
            due = draft_lifecycle_service.resolve_draft_lifecycle(
                db, account, now=activity_at + timedelta(days=40)
            )
            settings = draft_lifecycle_service.get_retention_settings(db)
            self.assertEqual(settings.first_reminder_after, timedelta(hours=12))
            self.assertEqual(settings.second_reminder_after, timedelta(days=5))
            self.assertEqual(settings.final_reminder_after, timedelta(days=15))
            self.assertFalse(not_due.deletion_eligible)
            self.assertTrue(due.deletion_eligible)
            self.assertEqual(due.state, "deletion_candidate")
        finally:
            db.close()

    def test_paid_and_confirmed_attempts_are_never_candidates(self):
        db = self.Session()
        try:
            old = self._now() - timedelta(days=60)
            account = self._account(db)
            organization = self._organization(db, account, activity_at=old)
            account.last_meaningful_activity_at = old
            organization.payment_status = "paid"
            organization.payment_confirmed_at = old + timedelta(days=1)
            result = draft_lifecycle_service.resolve_draft_lifecycle(db, account)
            self.assertFalse(result.deletion_eligible)
            self.assertIn("successful_payment", result.blocking_reasons)
        finally:
            db.close()

    def test_active_subscription_and_pending_provisioning_block_deletion(self):
        db = self.Session()
        try:
            old = self._now() - timedelta(days=60)
            account = self._account(db)
            organization = self._organization(db, account, activity_at=old)
            account.last_meaningful_activity_at = old
            plan = saas.models.SubscriptionPlan(plan_code="life", plan_name="Lifecycle")
            db.add(plan)
            db.flush()
            contract = saas.models.SubscriptionContract(
                pending_organization_id=organization.id,
                plan_id=plan.id,
                billing_interval="monthly",
                base_amount_minor=100,
                display_amount_minor=100,
            )
            db.add(contract)
            db.flush()
            db.add(saas.models.PaymentSubscription(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                provider_subscription_id="sub_lifecycle",
                plan_id=plan.id,
                billing_interval="monthly",
                status="active",
            ))
            db.add(saas.models.ProvisioningJob(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                job_uuid=str(uuid.uuid4()),
                idempotency_key="lifecycle-job",
                job_status="queued",
            ))
            db.flush()
            result = draft_lifecycle_service.resolve_draft_lifecycle(db, account)
            self.assertFalse(result.deletion_eligible)
            self.assertEqual(result.state, "provisioning")
            self.assertIn("active_subscription", result.blocking_reasons)
            self.assertIn("active_or_pending_provisioning", result.blocking_reasons)
        finally:
            db.close()

    def test_provisioned_tenant_and_multiple_organizations_are_conservative(self):
        db = self.Session()
        try:
            old = self._now() - timedelta(days=60)
            account = self._account(db)
            first = self._organization(db, account, activity_at=old)
            second = self._organization(db, account, activity_at=old)
            account.last_meaningful_activity_at = old
            result = draft_lifecycle_service.resolve_draft_lifecycle(db, account)
            self.assertFalse(result.deletion_eligible)
            self.assertEqual(result.deletion_status, "manual_review")
            self.assertIn("multiple_pending_organizations", result.blocking_reasons)

            db.delete(second)
            db.flush()
            school_group = models.SchoolGroup(name="Provisioned Lifecycle Academy")
            db.add(school_group)
            db.flush()
            user = models.User(
                user_id="LIFE000001",
                username="lifecycle.owner",
                email="tenant.lifecycle@example.com",
                email_normalized="tenant.lifecycle@example.com",
                password="not-used",
                role="Admin",
                school_group_id=school_group.id,
            )
            db.add(user)
            db.flush()
            db.add(saas.models.SaaSAccountUserLink(
                saas_account_id=account.id,
                operational_user_id=user.id,
                pending_organization_id=first.id,
                school_group_id=school_group.id,
            ))
            db.flush()
            provisioned = draft_lifecycle_service.resolve_draft_lifecycle(db, account)
            self.assertEqual(provisioned.state, "active")
            self.assertFalse(provisioned.deletion_eligible)
            self.assertIn("operational_account_link", provisioned.blocking_reasons)
        finally:
            db.close()

    def test_read_only_analysis_and_webhook_row_do_not_change_activity(self):
        db = self.Session()
        try:
            old = self._now() - timedelta(days=10)
            account = self._account(db)
            account.last_meaningful_activity_at = old
            db.add(saas.models.PaymentWebhook(
                provider="paddle",
                provider_event_id="evt_passive",
                event_type="transaction.updated",
                signature_valid=True,
            ))
            db.flush()
            draft_lifecycle_service.resolve_draft_lifecycle(db, account)
            self.assertEqual(account.last_meaningful_activity_at, old)
        finally:
            db.close()

    def test_migration_backfill_grants_legacy_records_a_fresh_grace_period(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE saas_accounts (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(180),
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            connection.execute(text("""
                CREATE TABLE pending_organizations (
                    id INTEGER PRIMARY KEY,
                    owner_saas_account_id INTEGER,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            connection.execute(text(
                "INSERT INTO saas_accounts (id, email, created_at, updated_at) "
                "VALUES (1, 'legacy@example.com', '2020-01-01', '2020-01-01')"
            ))
            connection.execute(text(
                "INSERT INTO pending_organizations (id, owner_saas_account_id, created_at, updated_at) "
                "VALUES (1, 1, '2020-01-01', '2020-01-01')"
            ))
            db_migrations._draft_account_lifecycle_foundation(engine, connection)
            account_activity = connection.execute(text(
                "SELECT last_meaningful_activity_at FROM saas_accounts WHERE id = 1"
            )).scalar_one()
            organization_activity = connection.execute(text(
                "SELECT last_meaningful_activity_at FROM pending_organizations WHERE id = 1"
            )).scalar_one()
            self.assertIsNotNone(account_activity)
            self.assertIsNotNone(organization_activity)
            self.assertNotIn("2020-01-01", str(account_activity))
            self.assertEqual(
                connection.execute(text(
                    "SELECT deletion_days FROM saas_draft_lifecycle_settings WHERE id = 1"
                )).scalar_one(),
                30,
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
