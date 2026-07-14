import json
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

import auth
import db_migrations
import models
import saas.models  # noqa: F401 - register SaaS metadata
from saas import draft_cleanup_service, draft_lifecycle_service, paddle_client, service
from scripts import process_abandoned_draft_cleanup


class SaaSDraftCleanupTests(unittest.TestCase):
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

    def tearDown(self):
        self.engine.dispose()

    def _create_draft(
        self,
        *,
        email="cleanup@example.com",
        days_inactive=31,
        final_reminder=True,
        with_organization=True,
        add_stale_billing=False,
    ):
        db = self.Session()
        try:
            activity = self.now - timedelta(days=days_inactive)
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=email,
                email_normalized=auth.normalize_email(email),
                password_hash=auth.get_password_hash("strong-password-123"),
                first_name="Draft",
                last_name="Owner",
                status="active",
                onboarding_status="organization_in_progress" if with_organization else "not_started",
                last_meaningful_activity_at=activity,
                final_reminder_sent_at=activity + timedelta(days=25) if final_reminder else None,
            )
            db.add(account)
            db.flush()
            db.add_all([
                saas.models.SaaSAuthIdentity(
                    saas_account_id=account.id,
                    provider="password",
                    provider_subject=account.email_normalized,
                    provider_email=email,
                    provider_email_normalized=account.email_normalized,
                ),
                saas.models.SaaSSession(
                    saas_account_id=account.id,
                    session_token_hash=uuid.uuid4().hex,
                    session_family_id=uuid.uuid4().hex,
                    expires_at=self.now + timedelta(days=1),
                ),
                saas.models.SaaSEmailVerificationToken(
                    saas_account_id=account.id,
                    token_hash=uuid.uuid4().hex,
                    email_normalized=account.email_normalized,
                    expires_at=self.now + timedelta(hours=1),
                ),
                saas.models.SaaSPasswordResetToken(
                    saas_account_id=account.id,
                    token_hash=uuid.uuid4().hex,
                    email_normalized=account.email_normalized,
                    expires_at=self.now + timedelta(hours=1),
                ),
                saas.models.SaaSAuthEvent(
                    saas_account_id=account.id,
                    event_type="test_identity_event",
                ),
            ])
            organization = None
            if with_organization:
                organization = saas.models.PendingOrganization(
                    organization_uuid=str(uuid.uuid4()),
                    owner_saas_account_id=account.id,
                    organization_name="Abandoned Draft Academy",
                    status="in_progress",
                    onboarding_step="branches",
                    billing_status="not_started",
                    payment_status="pending",
                    last_meaningful_activity_at=activity,
                )
                db.add(organization)
                db.flush()
                db.add_all([
                    saas.models.PendingOrganizationBranch(
                        pending_organization_id=organization.id,
                        branch_name="Draft Branch",
                    ),
                    saas.models.PendingOrganizationAcademicSetup(
                        pending_organization_id=organization.id,
                        first_academic_year_name="2026-2027",
                    ),
                    saas.models.PendingOrganizationContact(
                        pending_organization_id=organization.id,
                        first_name="Draft",
                        last_name="Owner",
                        email=email,
                        email_normalized=account.email_normalized,
                        is_primary=True,
                    ),
                    saas.models.PendingOrganizationProgress(
                        pending_organization_id=organization.id,
                        organization_profile_complete=True,
                    ),
                    saas.models.PendingOrganizationNote(
                        pending_organization_id=organization.id,
                        note="Draft-only note",
                    ),
                    saas.models.PendingOrganizationEvent(
                        pending_organization_id=organization.id,
                        actor_saas_account_id=account.id,
                        event_type="final_reminder_sent",
                    ),
                ])
                if add_stale_billing:
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
                        status="abandoned",
                        amount_minor=2900,
                        billing_interval="monthly",
                    )
                    contract = saas.models.SubscriptionContract(
                        pending_organization_id=organization.id,
                        plan_id=plan.id,
                        billing_interval="monthly",
                        contract_status="draft",
                        payment_status="failed",
                        base_amount_minor=2900,
                        display_amount_minor=2900,
                    )
                    db.add_all([checkout, contract])
                    db.flush()
                    attempt = saas.models.PaymentAttempt(
                        pending_organization_id=organization.id,
                        checkout_session_id=checkout.id,
                        plan_selection_id=selection.id,
                        attempt_uuid=str(uuid.uuid4()),
                        status="failed",
                        billing_interval="monthly",
                        failed_at=self.now - timedelta(days=30),
                    )
                    customer = saas.models.PaymentCustomer(
                        pending_organization_id=organization.id,
                        saas_account_id=account.id,
                        provider="paddle",
                        provider_customer_id=f"ctm_{uuid.uuid4().hex}",
                        email=email,
                    )
                    db.add_all([attempt, customer])
                    db.flush()
                    organization.last_payment_attempt_id = attempt.id
                    checkout.last_payment_attempt_id = attempt.id
                    job = saas.models.ProvisioningJob(
                        pending_organization_id=organization.id,
                        subscription_contract_id=contract.id,
                        job_uuid=str(uuid.uuid4()),
                        idempotency_key=f"failed-{uuid.uuid4().hex}",
                        job_status="failed",
                        failed_at=self.now - timedelta(days=29),
                    )
                    db.add(job)
                    db.flush()
                    db.add(saas.models.ProvisioningJobEvent(
                        provisioning_job_id=job.id,
                        event_type="failed",
                        event_status="failed",
                    ))
            db.commit()
            return {
                "account_id": account.id,
                "account_uuid": account.account_uuid,
                "email": email,
                "organization_id": getattr(organization, "id", None),
                "organization_uuid": getattr(organization, "organization_uuid", ""),
            }
        finally:
            db.close()

    def _run(self, **kwargs):
        events = []
        with patch("audit.write_audit_event", side_effect=lambda event: events.append(event)):
            result = draft_cleanup_service.process_abandoned_draft_cleanup(
                self.Session, now=self.now, **kwargs
            )
        return result, events

    def test_eligible_draft_deletes_identity_onboarding_and_stale_unpaid_data(self):
        draft = self._create_draft(add_stale_billing=True)
        unrelated = self._create_draft(email="unrelated@example.com", days_inactive=2)
        db = self.Session()
        try:
            plan_count = db.query(saas.models.SubscriptionPlan).count()
            price_count = db.query(saas.models.SubscriptionPlanPrice).count()
            webhook = saas.models.PaymentWebhook(
                provider="paddle",
                provider_event_id="evt_failed_preserved",
                event_type="transaction.payment_failed",
                signature_valid=True,
                payload_json='{"data":{"status":"failed"}}',
            )
            db.add(webhook)
            db.commit()
            webhook_id = webhook.id
        finally:
            db.close()
        with (
            patch.object(paddle_client, "create_customer") as paddle_customer,
            patch.object(paddle_client, "create_transaction") as paddle_transaction,
        ):
            result, events = self._run(account_email=draft["email"])
        self.assertEqual(result.deleted, 1)
        self.assertEqual(result.failed, 0)
        paddle_customer.assert_not_called()
        paddle_transaction.assert_not_called()
        db = self.Session()
        try:
            self.assertIsNone(db.query(saas.models.SaaSAccount).filter_by(id=draft["account_id"]).first())
            self.assertIsNone(db.query(saas.models.PendingOrganization).filter_by(id=draft["organization_id"]).first())
            self.assertEqual(db.query(saas.models.PaymentAttempt).count(), 0)
            self.assertEqual(db.query(saas.models.CheckoutSession).count(), 0)
            self.assertEqual(db.query(saas.models.ProvisioningJob).count(), 0)
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=unrelated["account_id"]).first())
            self.assertEqual(db.query(saas.models.SubscriptionPlan).count(), plan_count)
            self.assertEqual(db.query(saas.models.SubscriptionPlanPrice).count(), price_count)
            self.assertIsNotNone(db.query(saas.models.PaymentWebhook).filter_by(id=webhook_id).first())
            self.assertIsNone(service.authenticate_account(db, draft["email"], "strong-password-123"))
            recreated, _policy = service.create_account(
                db,
                email=draft["email"],
                password="strong-password-456",
            )
            self.assertEqual(recreated.email_normalized, auth.normalize_email(draft["email"]))
        finally:
            db.close()
        success = [event for event in events if event.get("event_type") == "draft_cleanup_deleted"]
        self.assertEqual(len(success), 1)
        self.assertEqual(success[0]["account_uuid"], draft["account_uuid"])
        self.assertGreater(success[0]["deleted_records"], 0)

    def test_threshold_final_reminder_and_dry_run_rules(self):
        before = self._create_draft(email="before@example.com", days_inactive=29)
        missing_notice = self._create_draft(email="notice@example.com", final_reminder=False)
        eligible = self._create_draft(email="dryrun@example.com")
        result, _events = self._run(dry_run=True, batch_size=10)
        self.assertEqual(result.dry_run_candidates, 1)
        self.assertGreaterEqual(result.skipped, 1)
        db = self.Session()
        try:
            for row in (before, missing_notice, eligible):
                self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=row["account_id"]).first())
        finally:
            db.close()

    def test_day_29_activity_and_profile_activity_prevent_cleanup(self):
        login_draft = self._create_draft(email="login29@example.com", days_inactive=29)
        profile_draft = self._create_draft(email="profile@example.com", days_inactive=31)
        db = self.Session()
        try:
            for draft, source in ((login_draft, "successful_login"), (profile_draft, "organization_profile_saved")):
                account = db.query(saas.models.SaaSAccount).filter_by(id=draft["account_id"]).one()
                organization = db.query(saas.models.PendingOrganization).filter_by(id=draft["organization_id"]).one()
                draft_lifecycle_service.record_meaningful_activity(
                    db, account, organization=organization, source=source, occurred_at=self.now
                )
            db.commit()
        finally:
            db.close()
        result, _events = self._run(batch_size=10)
        self.assertEqual(result.deleted, 0)
        db = self.Session()
        try:
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=login_draft["account_id"]).first())
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=profile_draft["account_id"]).first())
        finally:
            db.close()

    def test_scan_snapshot_uses_authoritative_organization_activity(self):
        draft = self._create_draft(email="authoritative-snapshot@example.com", days_inactive=31)
        db = self.Session()
        try:
            account = db.query(saas.models.SaaSAccount).filter_by(id=draft["account_id"]).one()
            account.last_meaningful_activity_at = self.now - timedelta(days=40)
            db.commit()
        finally:
            db.close()

        result, _events = self._run(account_email=draft["email"])

        self.assertEqual(result.deleted, 1)
        self.assertEqual(result.skipped, 0)

    def test_payment_subscription_and_successful_webhook_evidence_block_cleanup(self):
        paid = self._create_draft(email="paid@example.com")
        confirmed = self._create_draft(email="confirmed@example.com", add_stale_billing=True)
        subscribed = self._create_draft(email="subscription@example.com", add_stale_billing=True)
        webhook_draft = self._create_draft(email="webhook@example.com", add_stale_billing=True)
        db = self.Session()
        try:
            paid_org = db.query(saas.models.PendingOrganization).filter_by(id=paid["organization_id"]).one()
            paid_org.payment_status = "paid"
            paid_org.payment_confirmed_at = self.now - timedelta(days=1)
            confirmed_attempt = db.query(saas.models.PaymentAttempt).filter_by(
                pending_organization_id=confirmed["organization_id"]
            ).one()
            confirmed_attempt.status = "payment_confirmed"
            contract = db.query(saas.models.SubscriptionContract).filter_by(
                pending_organization_id=subscribed["organization_id"]
            ).one()
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").one()
            db.add(saas.models.PaymentSubscription(
                pending_organization_id=subscribed["organization_id"],
                subscription_contract_id=contract.id,
                provider_subscription_id="sub_cleanup_active",
                plan_id=plan.id,
                billing_interval="monthly",
                status="active",
            ))
            webhook_attempt = db.query(saas.models.PaymentAttempt).filter_by(
                pending_organization_id=webhook_draft["organization_id"]
            ).one()
            db.add(saas.models.PaymentWebhook(
                provider="paddle",
                provider_event_id="evt_cleanup_completed",
                event_type="transaction.completed",
                signature_valid=True,
                payload_json=json.dumps({
                    "data": {
                        "id": "txn_cleanup",
                        "custom_data": {
                            "pending_organization_uuid": webhook_draft["organization_uuid"],
                            "payment_attempt_uuid": webhook_attempt.attempt_uuid,
                        },
                    },
                }),
            ))
            db.commit()
        finally:
            db.close()
        result, _events = self._run(batch_size=20)
        self.assertEqual(result.deleted, 0)
        for row in (paid, confirmed, subscribed, webhook_draft):
            db = self.Session()
            try:
                self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=row["account_id"]).first())
            finally:
                db.close()

    def test_provisioning_tenant_platform_hold_and_ambiguity_block_cleanup(self):
        pending = self._create_draft(email="pending@example.com", add_stale_billing=True)
        tenant = self._create_draft(email="tenant@example.com", add_stale_billing=True)
        platform = self._create_draft(email="platform@example.com")
        protected = self._create_draft(email="protected@example.com")
        ambiguous = self._create_draft(email="ambiguous@example.com")
        db = self.Session()
        try:
            pending_job = db.query(saas.models.ProvisioningJob).filter_by(
                pending_organization_id=pending["organization_id"]
            ).one()
            pending_job.job_status = "queued"
            tenant_org = db.query(saas.models.PendingOrganization).filter_by(id=tenant["organization_id"]).one()
            school_group = models.SchoolGroup(name="Cleanup Protected Tenant")
            db.add(school_group)
            db.flush()
            operational_user = models.User(
                user_id="CLEAN00001",
                username="cleanup.tenant",
                email="cleanup.tenant@example.com",
                email_normalized="cleanup.tenant@example.com",
                password="unused",
                role="Admin",
                school_group_id=school_group.id,
            )
            db.add(operational_user)
            db.flush()
            tenant_contract = db.query(saas.models.SubscriptionContract).filter_by(
                pending_organization_id=tenant_org.id
            ).one()
            tenant_contract.school_group_id = school_group.id
            db.add(saas.models.TenantProvisioningLink(
                pending_organization_id=tenant_org.id,
                subscription_contract_id=tenant_contract.id,
                school_group_id=school_group.id,
                owner_operational_user_id=operational_user.id,
            ))
            db.add(models.User(
                user_id="CLEAN00002",
                username="cleanup.platform",
                email=platform["email"],
                email_normalized=auth.normalize_email(platform["email"]),
                password="unused",
                role="Developer",
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_DEVELOPER,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            ))
            protected_account = db.query(saas.models.SaaSAccount).filter_by(id=protected["account_id"]).one()
            protected_account.locked_at = self.now - timedelta(days=1)
            db.add(saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=ambiguous["account_id"],
                organization_name="Ambiguous Second Draft",
                last_meaningful_activity_at=self.now - timedelta(days=31),
            ))
            db.commit()
        finally:
            db.close()
        result, events = self._run(batch_size=20)
        self.assertEqual(result.deleted, 0)
        self.assertGreaterEqual(result.manual_review, 1)
        self.assertTrue(any(event.get("event_type") == "draft_cleanup_manual_review" for event in events))

    def test_rollback_restores_every_row_and_writes_safe_failure_audit(self):
        draft = self._create_draft(add_stale_billing=True)

        def fail_after_partial_delete(db, account, organization):
            db.query(saas.models.SaaSSession).filter_by(saas_account_id=account.id).delete(
                synchronize_session=False
            )
            raise RuntimeError("private database detail")

        events = []
        with (
            patch("audit.write_audit_event", side_effect=lambda event: events.append(event)),
            patch("saas.draft_cleanup_service._delete_eligible_draft", side_effect=fail_after_partial_delete),
        ):
            result = draft_cleanup_service.process_abandoned_draft_cleanup(
                self.Session, now=self.now, account_email=draft["email"]
            )
        self.assertEqual(result.failed, 1)
        db = self.Session()
        try:
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=draft["account_id"]).first())
            self.assertEqual(db.query(saas.models.SaaSSession).filter_by(saas_account_id=draft["account_id"]).count(), 1)
        finally:
            db.close()
        failure = [event for event in events if event.get("event_type") == "draft_cleanup_failed_rolled_back"]
        self.assertEqual(failure[0]["failure_type"], "RuntimeError")
        self.assertNotIn("private database detail", str(failure[0]))

    def test_activity_recheck_immediately_before_delete_aborts_cleanup(self):
        draft = self._create_draft()
        real_resolver = draft_cleanup_service.resolve_cleanup_eligibility
        call_count = 0

        def recover_on_first_check(db, account, **kwargs):
            nonlocal call_count
            outcome = real_resolver(db, account, **kwargs)
            call_count += 1
            if call_count == 1:
                organization = db.query(saas.models.PendingOrganization).filter_by(
                    owner_saas_account_id=account.id
                ).one()
                draft_lifecycle_service.record_meaningful_activity(
                    db,
                    account,
                    organization=organization,
                    source="organization_profile_saved",
                    occurred_at=self.now,
                )
            return outcome

        events = []
        with (
            patch("audit.write_audit_event", side_effect=lambda event: events.append(event)),
            patch("saas.draft_cleanup_service.resolve_cleanup_eligibility", side_effect=recover_on_first_check),
        ):
            result = draft_cleanup_service.process_abandoned_draft_cleanup(
                self.Session, now=self.now, account_email=draft["email"]
            )
        self.assertEqual(result.deleted, 0)
        self.assertEqual(result.skipped, 1)
        db = self.Session()
        try:
            self.assertIsNotNone(db.query(saas.models.SaaSAccount).filter_by(id=draft["account_id"]).first())
        finally:
            db.close()
        self.assertTrue(any(event.get("event_type") == "draft_cleanup_recovered_before_delete" for event in events))

    def test_batch_limit_targeting_repeated_run_and_nonproduction_override(self):
        first = self._create_draft(email="batch1@example.com")
        self._create_draft(email="batch2@example.com")
        result, _events = self._run(batch_size=1)
        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.deleted, 1)
        repeated, _events = self._run(account_email=first["email"])
        self.assertEqual(repeated.skipped, 1)
        recent = self._create_draft(email="override@example.com", days_inactive=3)
        override, _events = self._run(
            account_email=recent["email"], max_inactivity_days=2
        )
        self.assertEqual(override.deleted, 1)
        with patch.dict(os.environ, {"TIS_ENV": "production"}, clear=False):
            with self.assertRaises(ValueError):
                draft_cleanup_service.process_abandoned_draft_cleanup(
                    self.Session, max_inactivity_days=2, now=self.now
                )

    def test_concurrent_workers_delete_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(
                f"sqlite:///{os.path.join(temp_dir, 'cleanup.db')}",
                connect_args={"check_same_thread": False},
            )
            models.Base.metadata.create_all(bind=engine)
            db_migrations.run_pending_migrations(engine)
            Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
            activity = self.now - timedelta(days=31)
            db = Session()
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email="concurrent.cleanup@example.com",
                email_normalized="concurrent.cleanup@example.com",
                status="active",
                onboarding_status="not_started",
                last_meaningful_activity_at=activity,
                final_reminder_sent_at=activity + timedelta(days=25),
            )
            db.add(account)
            db.commit()
            db.close()
            audits = []
            audit_lock = threading.Lock()

            def record(event):
                with audit_lock:
                    audits.append(event)

            with patch("audit.write_audit_event", side_effect=record):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(
                        lambda _index: draft_cleanup_service.process_abandoned_draft_cleanup(
                            Session, now=self.now, account_email="concurrent.cleanup@example.com"
                        ),
                        range(2),
                    ))
            self.assertEqual(sum(result.deleted for result in results), 1)
            self.assertEqual(sum(result.skipped for result in results), 1)
            self.assertEqual(sum(1 for event in audits if event.get("event_type") == "draft_cleanup_deleted"), 1)
            engine.dispose()

    def test_cli_dry_run_wiring(self):
        expected = draft_cleanup_service.CleanupBatchResult(scanned=1, dry_run_candidates=1)
        with (
            patch("scripts.process_abandoned_draft_cleanup.draft_cleanup_service.process_abandoned_draft_cleanup", return_value=expected) as processor,
            patch("sys.argv", ["process_abandoned_draft_cleanup.py", "--dry-run", "--batch-size", "5"]),
            patch("builtins.print"),
        ):
            exit_code = process_abandoned_draft_cleanup.main()
        self.assertEqual(exit_code, 0)
        processor.assert_called_once_with(
            process_abandoned_draft_cleanup.SessionLocal,
            dry_run=True,
            batch_size=5,
            account_email=None,
            max_inactivity_days=None,
        )


if __name__ == "__main__":
    unittest.main()
