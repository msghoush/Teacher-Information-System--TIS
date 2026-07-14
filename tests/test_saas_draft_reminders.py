import os
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db_migrations
import models
import saas.models  # noqa: F401 - register SaaS metadata
from saas import draft_lifecycle_service, draft_reminder_service


class SaaSDraftReminderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(bind=self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.now = datetime(2026, 7, 14, 12, 0, 0)
        self.environment = patch.dict(os.environ, {
            "TIS_PUBLIC_BASE_URL": "https://app.tisplatform.com",
            "EMAIL_REPLY_TO": "support@tisplatform.com",
            "TIS_SUPPORT_EMAIL": "support@tisplatform.com",
        }, clear=False)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.engine.dispose()

    def _create_draft(self, *, days_inactive=2, with_organization=True, email="draft@example.com"):
        db = self.Session()
        try:
            activity_at = self.now - timedelta(days=days_inactive)
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=email,
                email_normalized=email.lower(),
                first_name="Amina",
                last_name="Rahman",
                status="active",
                onboarding_status="organization_in_progress" if with_organization else "not_started",
                last_meaningful_activity_at=activity_at,
            )
            db.add(account)
            db.flush()
            organization = None
            if with_organization:
                organization = saas.models.PendingOrganization(
                    organization_uuid=str(uuid.uuid4()),
                    owner_saas_account_id=account.id,
                    organization_name="Lifecycle Academy",
                    status="in_progress",
                    onboarding_step="organization",
                    billing_status="not_started",
                    payment_status="pending",
                    last_meaningful_activity_at=activity_at,
                )
                db.add(organization)
                db.flush()
                db.add(saas.models.PendingOrganizationProgress(
                    pending_organization_id=organization.id,
                ))
            db.commit()
            return account.id, getattr(organization, "id", None)
        finally:
            db.close()

    def _eligibility(self, account_id, *, now=None, stage_filter=None):
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).one()
            return draft_reminder_service.resolve_reminder_eligibility(
                db, account, now=now or self.now, stage_filter=stage_filter
            )
        finally:
            db.close()

    def _set_reminders(self, account_id, *, first=False, second=False, final=False):
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).one()
            activity = account.last_meaningful_activity_at
            account.first_reminder_sent_at = activity + timedelta(days=1) if first else None
            account.second_reminder_sent_at = activity + timedelta(days=7) if second else None
            account.final_reminder_sent_at = activity + timedelta(days=25) if final else None
            db.commit()
        finally:
            db.close()

    def test_first_reminder_threshold_and_once_per_cycle(self):
        account_id, _ = self._create_draft(days_inactive=1)
        before = self._eligibility(account_id, now=self.now - timedelta(seconds=1))
        due = self._eligibility(account_id)
        self.assertIsNone(before.due_stage)
        self.assertEqual(due.due_stage, "first")
        with patch("email_service.send_email", return_value="email_first") as send:
            first = draft_reminder_service.process_due_draft_reminders(
                self.Session, now=self.now
            )
            repeated = draft_reminder_service.process_due_draft_reminders(
                self.Session, now=self.now
            )
        self.assertEqual(first.first_reminder_sent, 1)
        self.assertEqual(repeated.first_reminder_sent, 0)
        self.assertEqual(send.call_count, 1)

    def test_reminder_thresholds_are_loaded_from_global_settings(self):
        account_id, _ = self._create_draft(days_inactive=2)
        db = self.Session()
        try:
            settings = db.query(saas.models.SaaSDraftLifecycleSetting).filter_by(id=1).one()
            settings.first_reminder_hours = 72
            db.commit()
        finally:
            db.close()
        self.assertIsNone(self._eligibility(account_id).due_stage)
        self.assertEqual(
            self._eligibility(account_id, now=self.now + timedelta(days=1)).due_stage,
            "first",
        )

    def test_second_reminder_requires_first_and_configured_seven_days(self):
        account_id, _ = self._create_draft(days_inactive=7)
        self.assertIsNone(self._eligibility(account_id, stage_filter="second").due_stage)
        self._set_reminders(account_id, first=True)
        self.assertIsNone(
            self._eligibility(account_id, now=self.now - timedelta(seconds=1)).due_stage
        )
        self.assertEqual(self._eligibility(account_id).due_stage, "second")
        with patch("email_service.send_email", return_value="email_second"):
            result = draft_reminder_service.process_due_draft_reminders(
                self.Session, now=self.now
            )
        self.assertEqual(result.second_reminder_sent, 1)

    def test_final_reminder_date_content_and_once_only(self):
        account_id, _ = self._create_draft(days_inactive=25)
        self._set_reminders(account_id, first=True, second=True)
        eligibility = self._eligibility(account_id)
        self.assertEqual(eligibility.due_stage, "final")
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).one()
            message = draft_reminder_service.build_reminder_email(db, account, eligibility)
        finally:
            db.close()
        self.assertEqual(message.subject, "Your TIS draft workspace will expire in 5 days")
        self.assertIn("July 19, 2026", message.text)
        with patch("email_service.send_email", return_value="email_final") as send:
            first = draft_reminder_service.process_due_draft_reminders(self.Session, now=self.now)
            repeated = draft_reminder_service.process_due_draft_reminders(self.Session, now=self.now)
        self.assertEqual(first.final_reminder_sent, 1)
        self.assertEqual(repeated.final_reminder_sent, 0)
        self.assertEqual(send.call_count, 1)

    def test_success_marks_timestamp_and_failure_remains_retryable(self):
        success_id, _ = self._create_draft(email="success@example.com")
        failure_id, _ = self._create_draft(email="failure@example.com")
        delivery_calls = []

        def deliver(**kwargs):
            delivery_calls.append(kwargs["to"])
            if kwargs["to"] == "failure@example.com":
                raise RuntimeError("provider failure with private detail")
            return "email_ok"

        with patch("email_service.send_email", side_effect=deliver):
            result = draft_reminder_service.process_due_draft_reminders(
                self.Session, now=self.now, batch_size=10
            )
        self.assertEqual(result.first_reminder_sent, 1)
        self.assertEqual(result.failed, 1)
        db = self.Session()
        try:
            success = db.query(saas.models.SaaSAccount).filter_by(id=success_id).one()
            failure = db.query(saas.models.SaaSAccount).filter_by(id=failure_id).one()
            self.assertEqual(success.first_reminder_sent_at, self.now)
            self.assertIsNone(failure.first_reminder_sent_at)
            success_organization = db.query(saas.models.PendingOrganization).filter_by(
                owner_saas_account_id=success.id
            ).one()
            self.assertEqual(
                db.query(saas.models.PendingOrganizationEvent).filter_by(
                    pending_organization_id=success_organization.id,
                    event_type="first_reminder_sent",
                ).count(),
                1,
            )
            failure_event = db.query(saas.models.PendingOrganizationEvent).filter_by(
                pending_organization_id=db.query(saas.models.PendingOrganization).filter_by(
                    owner_saas_account_id=failure.id
                ).one().id,
                event_type="reminder_send_failed",
            ).one()
            self.assertIn('"error_type":"RuntimeError"', failure_event.details_json)
            self.assertNotIn("private detail", failure_event.details_json)
        finally:
            db.close()

    def test_dry_run_and_batch_limit_write_nothing(self):
        account_ids = [
            self._create_draft(email=f"batch{index}@example.com")[0]
            for index in range(3)
        ]
        with patch("email_service.send_email") as send:
            result = draft_reminder_service.process_due_draft_reminders(
                self.Session, now=self.now, dry_run=True, batch_size=2
            )
        self.assertEqual(result.scanned, 2)
        self.assertEqual(result.dry_run_due, 2)
        send.assert_not_called()
        db = self.Session()
        try:
            for account_id in account_ids:
                self.assertIsNone(
                    db.query(saas.models.SaaSAccount).filter_by(id=account_id).one().first_reminder_sent_at
                )
        finally:
            db.close()

    def test_paid_provisioning_protected_and_ambiguous_accounts_are_excluded(self):
        paid_id, paid_org_id = self._create_draft(email="paid@example.com")
        provisioning_id, provisioning_org_id = self._create_draft(email="provisioning@example.com")
        protected_id, _ = self._create_draft(email="protected@example.com")
        ambiguous_id, _ = self._create_draft(email="ambiguous@example.com")
        db = self.Session()
        try:
            paid_org = db.query(saas.models.PendingOrganization).filter_by(id=paid_org_id).one()
            paid_org.payment_status = "paid"
            paid_org.payment_confirmed_at = self.now - timedelta(days=1)
            provisioning_org = db.query(saas.models.PendingOrganization).filter_by(id=provisioning_org_id).one()
            provisioning_org.billing_status = "provisioning_started"
            protected = db.query(saas.models.SaaSAccount).filter_by(id=protected_id).one()
            protected.locked_at = self.now - timedelta(days=1)
            db.add(saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=ambiguous_id,
                organization_name="Second Organization",
                last_meaningful_activity_at=self.now - timedelta(days=2),
            ))
            db.commit()
        finally:
            db.close()
        with patch("email_service.send_email") as send:
            result = draft_reminder_service.process_due_draft_reminders(
                self.Session, now=self.now, batch_size=20
            )
        self.assertEqual(result.first_reminder_sent, 0)
        self.assertEqual(result.skipped, 4)
        send.assert_not_called()
        db = self.Session()
        try:
            skipped_events = db.query(saas.models.PendingOrganizationEvent).filter_by(
                event_type="reminder_skipped_ineligible"
            ).count() + db.query(saas.models.SaaSAuthEvent).filter_by(
                event_type="reminder_skipped_ineligible"
            ).count()
            self.assertEqual(skipped_events, 4)
        finally:
            db.close()

    def test_confirmed_attempt_active_subscription_and_active_workspace_are_excluded(self):
        confirmed_id, confirmed_org_id = self._create_draft(email="confirmed@example.com")
        subscription_id, subscription_org_id = self._create_draft(email="subscription@example.com")
        workspace_id, workspace_org_id = self._create_draft(email="workspace@example.com")
        db = self.Session()
        try:
            for organization_id, suffix in ((confirmed_org_id, "confirmed"), (subscription_org_id, "subscription")):
                organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).one()
                plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").one()
                selection = saas.models.PendingOrganizationPlanSelection(
                    pending_organization_id=organization.id,
                    plan_id=plan.id,
                    billing_interval="monthly",
                    base_amount_minor=2900,
                    display_amount_minor=2900,
                )
                db.add(selection)
                db.flush()
                checkout = saas.models.CheckoutSession(
                    pending_organization_id=organization.id,
                    plan_selection_id=selection.id,
                    amount_minor=2900,
                    billing_interval="monthly",
                )
                contract = saas.models.SubscriptionContract(
                    pending_organization_id=organization.id,
                    plan_id=plan.id,
                    billing_interval="monthly",
                    base_amount_minor=2900,
                    display_amount_minor=2900,
                )
                db.add_all([checkout, contract])
                db.flush()
                if suffix == "confirmed":
                    db.add(saas.models.PaymentAttempt(
                        pending_organization_id=organization.id,
                        checkout_session_id=checkout.id,
                        plan_selection_id=selection.id,
                        attempt_uuid=str(uuid.uuid4()),
                        status="payment_confirmed",
                        billing_interval="monthly",
                    ))
                else:
                    db.add(saas.models.PaymentSubscription(
                        pending_organization_id=organization.id,
                        subscription_contract_id=contract.id,
                        provider_subscription_id="sub_reminder_active",
                        plan_id=plan.id,
                        billing_interval="monthly",
                        status="active",
                    ))
            workspace = db.query(saas.models.PendingOrganization).filter_by(id=workspace_org_id).one()
            workspace.billing_status = "tenant_active"
            db.commit()
        finally:
            db.close()
        for account_id in (confirmed_id, subscription_id, workspace_id):
            self.assertFalse(self._eligibility(account_id).eligible)

    def test_pending_job_tenant_link_and_operational_school_group_are_excluded(self):
        job_id, job_org_id = self._create_draft(email="job@example.com")
        tenant_id, tenant_org_id = self._create_draft(email="tenant@example.com")
        db = self.Session()
        try:
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").one()
            job_contract = saas.models.SubscriptionContract(
                pending_organization_id=job_org_id,
                plan_id=plan.id,
                billing_interval="monthly",
                base_amount_minor=2900,
                display_amount_minor=2900,
            )
            db.add(job_contract)
            db.flush()
            db.add(saas.models.ProvisioningJob(
                pending_organization_id=job_org_id,
                subscription_contract_id=job_contract.id,
                job_uuid=str(uuid.uuid4()),
                idempotency_key="reminder-pending-job",
                job_status="queued",
            ))

            school_group = models.SchoolGroup(name="Reminder Provisioned Tenant")
            db.add(school_group)
            db.flush()
            operational_user = models.User(
                user_id="REMIND0001",
                username="reminder.tenant.owner",
                email="reminder.tenant.owner@example.com",
                email_normalized="reminder.tenant.owner@example.com",
                password="not-used",
                role="Admin",
                school_group_id=school_group.id,
            )
            db.add(operational_user)
            db.flush()
            tenant_contract = saas.models.SubscriptionContract(
                pending_organization_id=tenant_org_id,
                school_group_id=school_group.id,
                plan_id=plan.id,
                billing_interval="monthly",
                base_amount_minor=2900,
                display_amount_minor=2900,
            )
            db.add(tenant_contract)
            db.flush()
            db.add(saas.models.TenantProvisioningLink(
                pending_organization_id=tenant_org_id,
                subscription_contract_id=tenant_contract.id,
                school_group_id=school_group.id,
                owner_operational_user_id=operational_user.id,
                tenant_status="tenant_active",
            ))
            db.commit()
        finally:
            db.close()
        self.assertFalse(self._eligibility(job_id).eligible)
        tenant = self._eligibility(tenant_id)
        self.assertFalse(tenant.eligible)

    def test_progress_next_step_and_plan_specific_ai_content_are_accurate(self):
        account_id, organization_id = self._create_draft(days_inactive=7)
        self._set_reminders(account_id, first=True)
        db = self.Session()
        try:
            organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).one()
            progress = db.query(saas.models.PendingOrganizationProgress).filter_by(
                pending_organization_id=organization.id
            ).one()
            progress.organization_profile_complete = True
            progress.branches_complete = True
            enterprise = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="enterprise_ai").one()
            organization.selected_plan_id = enterprise.id
            db.commit()
            summary = draft_reminder_service.resolve_onboarding_progress(db, organization)
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).one()
            eligibility = draft_reminder_service.resolve_reminder_eligibility(db, account, now=self.now)
            message = draft_reminder_service.build_reminder_email(db, account, eligibility)
            self.assertEqual(summary.completed_count, 2)
            self.assertEqual(summary.progress_text, "2 of 5 steps completed")
            self.assertEqual(summary.next_incomplete_step, "Academic Setup")
            self.assertIn("AI-enabled capabilities included with your selected plan", message.text)
        finally:
            db.close()

    def test_urls_logo_and_customer_values_are_safe(self):
        account_id, organization_id = self._create_draft(email="safe@example.com")
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).one()
            organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).one()
            account.first_name = '<script>alert("name")</script>'
            organization.organization_name = '<img src=x onerror="alert(1)">'
            db.commit()
            eligibility = draft_reminder_service.resolve_reminder_eligibility(db, account, now=self.now)
            message = draft_reminder_service.build_reminder_email(db, account, eligibility)
            self.assertIn("https://app.tisplatform.com/saas/login", message.html)
            self.assertIn("https://app.tisplatform.com/static/branding/tis/logos/", message.html)
            self.assertNotIn("<script>", message.html)
            self.assertNotIn("<img src=x", message.html)
            self.assertIn("&lt;script&gt;", message.html)
        finally:
            db.close()

    def test_day_29_recovery_starts_a_new_cycle_and_clears_final_warning(self):
        account_id, organization_id = self._create_draft(days_inactive=29)
        self._set_reminders(account_id, first=True, second=True, final=True)
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=account_id).one()
            organization = db.query(saas.models.PendingOrganization).filter_by(id=organization_id).one()
            draft_lifecycle_service.record_meaningful_activity(
                db,
                account,
                organization=organization,
                source="successful_login",
                occurred_at=self.now,
            )
            db.commit()
            self.assertEqual(account.reminder_cycle, 2)
            self.assertIsNone(account.final_reminder_sent_at)
            before = draft_reminder_service.resolve_reminder_eligibility(
                db, account, now=self.now + timedelta(hours=23, minutes=59)
            )
            due = draft_reminder_service.resolve_reminder_eligibility(
                db, account, now=self.now + timedelta(hours=24)
            )
            self.assertIsNone(before.due_stage)
            self.assertEqual(due.due_stage, "first")
        finally:
            db.close()

    def test_concurrent_processors_send_one_email(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "reminders.db")
            engine = create_engine(
                f"sqlite:///{database_path}",
                connect_args={"check_same_thread": False},
            )
            models.Base.metadata.create_all(bind=engine)
            db_migrations.run_pending_migrations(engine)
            Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            db = Session()
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email="concurrent@example.com",
                email_normalized="concurrent@example.com",
                status="active",
                onboarding_status="not_started",
                last_meaningful_activity_at=self.now - timedelta(days=2),
            )
            db.add(account)
            db.commit()
            db.close()
            send_count = 0
            send_lock = threading.Lock()

            def deliver(**_kwargs):
                nonlocal send_count
                time.sleep(0.05)
                with send_lock:
                    send_count += 1
                return "email_concurrent"

            with patch("email_service.send_email", side_effect=deliver):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(
                        lambda _index: draft_reminder_service.process_due_draft_reminders(
                            Session, now=self.now
                        ),
                        range(2),
                    ))
            self.assertEqual(send_count, 1)
            self.assertEqual(sum(result.first_reminder_sent for result in results), 1)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
