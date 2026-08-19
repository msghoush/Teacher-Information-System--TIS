import concurrent.futures
import os
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import auth
import db_migrations
import models
import saas.models
from saas import ai_entitlement_service, ai_feature_registry


FEATURE = "ai.academic_assistant"
SECOND_FEATURE = "ai.exam_analysis"


class TestAIEntitlementService:
    def setup_method(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "ai-entitlements.db"
        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 20},
        )
        models.Base.metadata.create_all(self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def teardown_method(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _workspace(self, *, classification="customer_demo", lifecycle="active", role=auth.ROLE_ADMINISTRATOR):
        with self.Session() as db:
            token = uuid.uuid4().hex[:10]
            group = models.SchoolGroup(
                name=f"AI Workspace {token}",
                workspace_classification=classification,
                workspace_lifecycle_status=lifecycle,
            )
            db.add(group)
            db.flush()
            branch = models.Branch(
                school_group_id=group.id,
                name=f"AI Branch {token}",
                status=True,
            )
            db.add(branch)
            db.flush()
            user = models.User(
                user_id=token,
                username=f"ai.{token}",
                password="unused",
                role=role,
                user_type=auth.USER_TYPE_TENANT,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
                school_group_id=group.id,
                branch_id=branch.id,
                is_active=True,
            )
            db.add(user)
            if classification != "internal_sandbox":
                db.add(saas.models.WorkspaceEntitlement(
                    entitlement_uuid=str(uuid.uuid4()),
                    school_group_id=group.id,
                    entitlement_type="demo" if classification == "customer_demo" else "paid",
                    status="active" if lifecycle == "active" else "suspended",
                    source="system",
                ))
            db.commit()
            return group.id, user.id

    def _paid_workspace(self, plan_code):
        with self.Session() as db:
            token = uuid.uuid4().hex[:10]
            plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code=plan_code).one()
            group = models.SchoolGroup(
                name=f"Paid AI Workspace {token}",
                workspace_classification="customer_paid",
                workspace_lifecycle_status="active",
            )
            db.add(group)
            db.flush()
            branch = models.Branch(school_group_id=group.id, name=f"Branch {token}", status=True)
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email=f"{token}@example.com",
                email_normalized=f"{token}@example.com",
                status="active",
                onboarding_status="tenant_active",
            )
            db.add_all([branch, account])
            db.flush()
            organization = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=account.id,
                organization_name=f"Paid AI Organization {token}",
                status="tenant_active",
                billing_status="tenant_active",
                payment_status="paid",
                payment_confirmed_at=datetime(2026, 7, 1),
            )
            user = models.User(
                user_id=token,
                username=f"paid.ai.{token}",
                password="unused",
                role=auth.ROLE_ADMINISTRATOR,
                user_type=auth.USER_TYPE_TENANT,
                access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
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
                base_amount_minor=100,
                display_amount_minor=100,
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
            db.add(saas.models.WorkspaceEntitlement(
                entitlement_uuid=str(uuid.uuid4()),
                school_group_id=group.id,
                entitlement_type="paid",
                status="active",
                source="subscription",
                payment_subscription_id=subscription.id,
            ))
            db.commit()
            return group.id, user.id

    def _user(self, db, user_id, group_id):
        user = db.get(models.User, user_id)
        user.scope_school_group_id = group_id
        return user

    def _consume(self, group_id, user_id, feature=FEATURE, operation_key=None):
        with self.Session() as db:
            result = ai_entitlement_service.consume_successful_ai_use(
                db,
                user=self._user(db, user_id, group_id),
                school_group_id=group_id,
                feature_key=feature,
                operation_key=operation_key,
            )
            db.commit()
            return result

    def test_demo_two_successes_then_third_is_blocked_and_failed_work_is_free(self):
        group_id, user_id = self._workspace()
        with self.Session() as db:
            initial = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, user_id, group_id),
                school_group_id=group_id, feature_key=FEATURE,
            )
            assert initial.allowed and initial.current_usage == 0
            # A failed provider operation never calls consume_successful_ai_use.
            retry = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, user_id, group_id),
                school_group_id=group_id, feature_key=FEATURE,
            )
            assert retry.current_usage == 0
            reservation = ai_entitlement_service.reserve_ai_use(
                db, user=self._user(db, user_id, group_id),
                school_group_id=group_id, feature_key=FEATURE,
                operation_key="failed-provider-operation",
            )
            assert reservation.allowed
            failed = ai_entitlement_service.complete_ai_use(
                db, user=self._user(db, user_id, group_id),
                school_group_id=group_id, feature_key=FEATURE,
                operation_key="failed-provider-operation", successful=False,
            )
            assert not failed.allowed
            db.commit()

        first = self._consume(group_id, user_id, operation_key="one")
        second = self._consume(group_id, user_id, operation_key="two")
        third = self._consume(group_id, user_id, operation_key="three")
        assert first.allowed and first.current_usage == 1
        assert second.allowed and second.current_usage == 2
        assert not third.allowed
        assert third.message == "You have reached the demo limit for this AI feature."
        assert third.cta_label == "Subscribe Now"
        assert third.cta_url == "/saas/subscription"
        with self.Session() as db:
            availability = ai_entitlement_service.evaluate_ai_availability(
                db,
                user=self._user(db, user_id, group_id),
                school_group_id=group_id,
                feature_key=FEATURE,
            )
        assert availability.allowed
        assert availability.reason_code == "ai_feature_available"

    def test_demo_limits_are_independent_per_feature_and_tenant(self):
        first_group, first_user = self._workspace()
        second_group, second_user = self._workspace()
        self._consume(first_group, first_user, operation_key="one")
        self._consume(first_group, first_user, operation_key="two")

        other_feature = self._consume(
            first_group, first_user, feature=SECOND_FEATURE, operation_key="one"
        )
        other_tenant = self._consume(second_group, second_user, operation_key="one")
        assert other_feature.allowed and other_feature.current_usage == 1
        assert other_tenant.allowed and other_tenant.current_usage == 1

    def test_duplicate_operation_is_not_double_counted(self):
        group_id, user_id = self._workspace()
        first = self._consume(group_id, user_id, operation_key="same-operation")
        replay = self._consume(group_id, user_id, operation_key="same-operation")
        assert first.current_usage == 1
        assert replay.current_usage == 1
        assert replay.idempotent_replay
        with self.Session() as db:
            assert db.query(saas.models.AIFeatureUsageEvent).count() == 1

    def test_concurrent_demo_consumption_cannot_exceed_two(self):
        group_id, user_id = self._workspace()
        barrier = threading.Barrier(3)

        def consume(index):
            barrier.wait()
            return self._consume(group_id, user_id, operation_key=f"parallel-{index}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(consume, range(3)))
        assert sum(1 for result in results if result.allowed) == 2
        with self.Session() as db:
            counter = db.query(saas.models.AIFeatureUsageCounter).one()
            assert counter.successful_uses == 2
            assert db.query(saas.models.AIFeatureUsageEvent).count() == 2

    def test_concurrent_reservations_block_third_attempt_before_execution(self):
        group_id, user_id = self._workspace()
        barrier = threading.Barrier(3)

        def reserve(index):
            with self.Session() as db:
                barrier.wait()
                result = ai_entitlement_service.reserve_ai_use(
                    db, user=self._user(db, user_id, group_id),
                    school_group_id=group_id, feature_key=FEATURE,
                    operation_key=f"reservation-{index}",
                )
                db.commit()
                return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(reserve, range(3)))
        assert sum(1 for result in results if result.allowed) == 2
        assert sum(
            result.reason_code == "demo_feature_limit_exhausted"
            for result in results
        ) == 1
        with self.Session() as db:
            counter = db.query(saas.models.AIFeatureUsageCounter).one()
            assert counter.successful_uses == 0
            assert counter.reserved_uses == 2

    def test_paid_enterprise_and_professional_share_ai_availability(self):
        starter_group, starter_user = self._paid_workspace("starter")
        enterprise_group, enterprise_user = self._paid_workspace("enterprise_ai")
        professional_group, professional_user = self._paid_workspace("professional")
        with self.Session() as db:
            starter = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, starter_user, starter_group),
                school_group_id=starter_group, feature_key=FEATURE,
            )
            enterprise = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, enterprise_user, enterprise_group),
                school_group_id=enterprise_group, feature_key=FEATURE,
            )
            professional = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, professional_user, professional_group),
                school_group_id=professional_group, feature_key=FEATURE,
            )
        assert starter.allowed and starter.plan_code == "starter"
        assert enterprise.allowed and enterprise.plan_code == "enterprise_ai"
        assert professional.allowed
        assert professional.reason_code == "paid_plan_allowed"
        assert professional.usage_limit is None

    def test_sandbox_payment_environment_never_promotes_demo_ai_access(self):
        group_id, user_id = self._workspace()
        with patch.dict(os.environ, {"PADDLE_ENVIRONMENT": "sandbox"}, clear=False):
            with self.Session() as db:
                result = ai_entitlement_service.evaluate_ai_entitlement(
                    db, user=self._user(db, user_id, group_id),
                    school_group_id=group_id, feature_key=FEATURE,
                )
        assert result.allowed
        assert result.reason_code == "demo_allowed"
        assert result.workspace_classification == "customer_demo"
        assert result.plan_code == ""

    def test_internal_sandbox_is_unlimited_and_metrics_are_separate(self):
        group_id, user_id = self._workspace(classification="internal_sandbox")
        for index in range(3):
            result = self._consume(group_id, user_id, operation_key=f"sandbox-{index}")
            assert result.allowed
            assert result.usage_limit is None
        with self.Session() as db:
            counter = db.query(saas.models.AIFeatureUsageCounter).one()
            assert counter.metric_context == "internal_sandbox"
            assert counter.successful_uses == 3

    def test_expired_demo_precedes_remaining_allowance(self):
        group_id, user_id = self._workspace(lifecycle="suspended")
        with self.Session() as db:
            result = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, user_id, group_id),
                school_group_id=group_id, feature_key=FEATURE,
            )
            unknown_result = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=self._user(db, user_id, group_id),
                school_group_id=group_id, feature_key="ai.unknown",
            )
        assert not result.allowed
        assert result.reason_code == "demo_expired"
        assert unknown_result.reason_code == "demo_expired"

    def test_permission_and_workspace_scope_fail_closed(self):
        group_id, user_id = self._workspace(role=auth.ROLE_LIMITED)
        other_group, _ = self._workspace()
        with self.Session() as db:
            user = self._user(db, user_id, group_id)
            permission = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id, feature_key=FEATURE,
            )
            tenant = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=other_group, feature_key=FEATURE,
            )
        assert permission.reason_code == "ai_permission_denied"
        assert tenant.reason_code == "workspace_access_denied"

    def test_unknown_and_disabled_features_fail_safely(self):
        group_id, user_id = self._workspace()
        with self.Session() as db:
            user = self._user(db, user_id, group_id)
            unknown = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id, feature_key="ai.unknown",
            )
            disabled = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id,
                feature_key="ai.assessment_quality_review",
            )
        assert unknown.reason_code == "unknown_ai_feature"
        assert disabled.reason_code == "ai_feature_disabled"
        assert ai_feature_registry.get_feature(FEATURE).demo_allowance == 2

    def test_migration_is_idempotent_and_creates_usage_constraints(self):
        assert db_migrations.run_pending_migrations(self.engine) == []
        inspector = inspect(self.engine)
        assert {
            "ai_feature_usage_counters",
            "ai_feature_usage_events",
        }.issubset(inspector.get_table_names())
        assert "uq_ai_feature_usage_counter_scope" in {
            row["name"] for row in inspector.get_indexes("ai_feature_usage_counters")
        }
