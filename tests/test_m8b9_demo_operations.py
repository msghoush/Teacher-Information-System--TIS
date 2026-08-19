import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from starlette.requests import Request

import auth
import authorization
import db_migrations
import main
import models
import saas.models
from saas import (
    ai_entitlement_service,
    demo_access_service,
    demo_operations_service,
    entitlement_service,
)
FEATURE = "ai.academic_assistant"


class TestM8B9DemoOperations:
    def setup_method(self):
        from test_saas_demo_request_workflow import SaaSDemoRequestWorkflowTests
        self.workflow = SaaSDemoRequestWorkflowTests()
        self.workflow.setUp()
        self.fixture = self.workflow._activate_demo(
            email=f"m8b9-{uuid.uuid4().hex}@academy.edu",
            owner_user_id=f"9{uuid.uuid4().int % 100000:05d}",
        )

    def teardown_method(self):
        self.workflow.tearDown()

    def _actor(self, db):
        return db.query(models.User).filter(
            models.User.user_type == auth.USER_TYPE_PLATFORM,
            models.User.platform_role == auth.PLATFORM_ROLE_OWNER,
        ).first()

    def _tenant_user(self, db):
        user = db.get(models.User, self.fixture["operational_user_id"])
        user.scope_school_group_id = self.fixture["school_group_id"]
        return user

    def test_expire_and_reactivate_preserve_workspace_data_and_communications(self):
        db = self.workflow._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning, self.fixture["provisioning_id"]
            )
            group_id = provisioning.school_group_id
            branch_ids = {
                row[0] for row in db.query(models.Branch.id).filter_by(
                    school_group_id=group_id
                ).all()
            }
            expired = demo_operations_service.expire_demo_now(
                db, actor=self._actor(db), provisioning_id=provisioning.id,
                reason="Owner requested immediate expiry", operation_key="expire-1",
            )
            db.commit()
            db.refresh(provisioning)
            assert expired.result_status == "success"
            assert expired.previous_values_json and expired.new_values_json
            assert expired.actor_user_id == self._actor(db).id
            assert expired.email_delivery_ids_json != "[]"
            assert expired.notification_ids_json != "[]"
            assert provisioning.expired_at is not None
            assert db.get(models.SchoolGroup, group_id).workspace_classification == "customer_demo"
            assert branch_ids == {
                row[0] for row in db.query(models.Branch.id).filter_by(
                    school_group_id=group_id
                ).all()
            }
            assert db.query(saas.models.SaaSDemoEmailDelivery).filter_by(
                demo_request_id=self.fixture["request_id"], email_type="demo_expired"
            ).count() == 1
            assert db.query(saas.models.SaaSDemoLifecycleNotification).filter_by(
                demo_provisioning_id=provisioning.id, notification_type="demo_expired"
            ).count() >= 1

            future = datetime.now(UTC) + timedelta(days=30)
            reactivated = demo_operations_service.reactivate_demo(
                db, actor=self._actor(db), provisioning_id=provisioning.id,
                new_expiry=future, reason="Continue evaluation",
                operation_key="reactivate-1",
            )
            db.commit()
            db.refresh(provisioning)
            assert reactivated.result_status == "success"
            assert provisioning.expired_at is None
            assert provisioning.demo_expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
            assert provisioning.school_group_id == group_id
            assert db.query(saas.models.SaaSDemoEmailDelivery).filter_by(
                demo_request_id=self.fixture["request_id"], email_type="demo_reactivated"
            ).count() == 1
        finally:
            db.close()

    def test_custom_expiry_has_no_maximum_and_reactivates_expired_demo(self):
        db = self.workflow._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning, self.fixture["provisioning_id"]
            )
            long_future = datetime.now(UTC) + timedelta(days=3650)
            demo_operations_service.set_custom_expiry(
                db, actor=self._actor(db), provisioning_id=provisioning.id,
                new_expiry=long_future, reason="Extended evaluation",
                operation_key="long-expiry",
            )
            db.commit()
            db.refresh(provisioning)
            assert provisioning.expiry_policy == "custom"
            assert provisioning.demo_expires_at.replace(tzinfo=UTC) > datetime.now(UTC) + timedelta(days=3600)

            demo_operations_service.expire_demo_now(
                db, actor=self._actor(db), provisioning_id=provisioning.id,
                reason="Pause", operation_key="expire-before-custom",
            )
            db.commit()
            demo_operations_service.set_custom_expiry(
                db, actor=self._actor(db), provisioning_id=provisioning.id,
                new_expiry=datetime.now(UTC) + timedelta(days=5),
                reason="Resume", operation_key="custom-reactivation",
            )
            db.commit()
            db.refresh(provisioning)
            assert provisioning.expired_at is None
            assert db.get(models.SchoolGroup, provisioning.school_group_id).workspace_lifecycle_status == "active"
        finally:
            db.close()

    def test_final_day_reminders_rotate_and_operation_key_is_idempotent(self):
        db = self.workflow._db()
        try:
            provisioning = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning, self.fixture["provisioning_id"]
            )
            now = datetime.now(UTC)
            provisioning.expiry_policy = "custom"
            provisioning.demo_expires_at = now + timedelta(hours=20)
            provisioning.reminder_due_at = provisioning.demo_expires_at - timedelta(days=1)
            db.commit()
            actor = self._actor(db)
            first = demo_operations_service.send_final_day_reminder(
                db, actor=actor, provisioning_id=provisioning.id,
                operation_key="manual-1", observed_at=now,
            )
            replay = demo_operations_service.send_final_day_reminder(
                db, actor=actor, provisioning_id=provisioning.id,
                operation_key="manual-1", observed_at=now,
            )
            second = demo_operations_service.send_final_day_reminder(
                db, actor=actor, provisioning_id=provisioning.id,
                operation_key="manual-2", observed_at=now,
            )
            db.commit()
            assert replay.id == first.id and second.id != first.id
            emails = db.query(saas.models.SaaSDemoEmailDelivery).filter_by(
                demo_request_id=self.fixture["request_id"],
                email_type="manual_final_day_reminder",
            ).all()
            assert len(emails) == 2
            assert emails[0].payload_json != emails[1].payload_json
            with pytest.raises(demo_operations_service.DemoOperationError):
                demo_operations_service.send_final_day_reminder(
                    db, actor=actor, provisioning_id=provisioning.id,
                    operation_key="too-early", observed_at=now - timedelta(days=2),
                )
        finally:
            db.close()

    def test_access_profiles_branch_scope_and_usage_history(self):
        db = self.workflow._db()
        try:
            group_id = self.fixture["school_group_id"]
            branches = db.query(models.Branch).filter_by(school_group_id=group_id).all()
            actor = self._actor(db)
            user = self._tenant_user(db)
            for key in ("use-1", "use-2"):
                result = ai_entitlement_service.consume_successful_ai_use(
                    db, user=user, school_group_id=group_id,
                    feature_key=FEATURE, operation_key=key,
                )
                assert result.allowed
            db.commit()
            demo_operations_service.change_access_profile(
                db, actor=actor, provisioning_id=self.fixture["provisioning_id"],
                profile="full", reason="Guided workshop", operation_key="full",
            )
            db.commit()
            full = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id, feature_key=FEATURE
            )
            assert full.allowed and full.usage_limit is None
            user.scope_school_group_id = group_id
            user.scope_branch_id = branches[0].id
            assert entitlement_service.can_use_feature(
                db,
                user,
                "feature.advanced_reporting",
                "reports.export",
                branch_id=branches[0].id,
            )
            user.scope_academic_year_id = db.query(models.AcademicYear.id).filter_by(
                school_group_id=group_id
            ).scalar()
            for extension, endpoint in (
                ("xlsx", main.download_report_allocation_plan),
                ("pdf", main.download_report_allocation_plan_pdf),
            ):
                path = f"/reports/allocation-plan.{extension}"
                request = Request({
                    "type": "http",
                    "method": "GET",
                    "path": path,
                    "raw_path": path.encode("ascii"),
                    "query_string": b"",
                    "headers": [],
                    "scheme": "http",
                    "server": ("testserver", 80),
                    "client": ("testclient", 50000),
                    "root_path": "",
                })
                assert authorization.enforce_route_permission(
                    request, db, current_user=user
                ) is None
                with patch("auth.get_current_user", return_value=user):
                    response = endpoint(request=request, section="full", db=db)
                assert response.status_code == 200
            assert db.get(models.SchoolGroup, group_id).workspace_classification == "customer_demo"

            demo_operations_service.change_access_profile(
                db, actor=actor, provisioning_id=self.fixture["provisioning_id"],
                profile="custom", reason="Branch pilot", operation_key="branch-custom",
                branch_id=branches[0].id, ai_features=[FEATURE],
                ai_allowances={FEATURE: 5},
            )
            db.commit()
            first_branch = demo_access_service.resolve_access(
                db, group_id, branch_id=branches[0].id
            )
            other_branch = demo_access_service.resolve_access(
                db, group_id, branch_id=branches[1].id
            )
            assert first_branch.profile == "custom" and first_branch.ai_allowances[FEATURE] == 5
            assert other_branch.profile == "full"

            demo_operations_service.change_access_profile(
                db, actor=actor, provisioning_id=self.fixture["provisioning_id"],
                profile="standard", reason="Return to standard", operation_key="standard",
            )
            db.commit()
            blocked = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id, feature_key=FEATURE
            )
            assert not blocked.allowed
            assert ai_entitlement_service.evaluate_ai_availability(
                db, user=user, school_group_id=group_id, feature_key=FEATURE
            ).allowed
            assert entitlement_service.can_use_feature(
                db,
                user,
                "feature.advanced_reporting",
                "reports.export",
                branch_id=branches[0].id,
            )
            assert db.query(saas.models.AIFeatureUsageEvent).filter_by(
                school_group_id=group_id, feature_key=FEATURE, result_status="successful"
            ).count() == 2
        finally:
            db.close()

    def test_unknown_feature_authorization_expiry_and_failure_audit_fail_closed(self):
        db = self.workflow._db()
        try:
            provisioning_id = self.fixture["provisioning_id"]
            actor = self._actor(db)
            with pytest.raises(demo_access_service.DemoAccessError) as unknown:
                demo_operations_service.change_access_profile(
                    db, actor=actor, provisioning_id=provisioning_id,
                    profile="custom", reason="Invalid request", operation_key="unknown",
                    ai_features=["ai.not_registered"],
                )
            assert unknown.value.reason_code == "unknown_ai_feature"
            db.rollback()
            demo_operations_service.record_failed_operation(
                db, actor=actor, provisioning_id=provisioning_id,
                action="change_access_profile", reason="Invalid request",
                operation_key="unknown", failure_code=unknown.value.reason_code,
            )
            db.commit()
            failure = db.query(saas.models.DemoOperationAudit).filter_by(
                operation_key="unknown"
            ).one()
            assert failure.result_status == "failed"
            assert failure.actor_user_id == actor.id
            assert failure.previous_values_json

            developer = models.User(
                user_id=f"dev{uuid.uuid4().hex[:6]}", username=f"dev.{uuid.uuid4().hex}",
                password="unused", user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_DEVELOPER,
                access_scope=auth.ACCESS_SCOPE_GLOBAL, is_active=True,
            )
            db.add(developer)
            db.commit()
            with pytest.raises(demo_operations_service.DemoOperationError):
                demo_operations_service.expire_demo_now(
                    db, actor=developer, provisioning_id=provisioning_id,
                    reason="Not authorized", operation_key="developer",
                )
        finally:
            db.close()

    def test_demo_specific_and_global_lifecycle_summary_are_tenant_safe(self):
        db = self.workflow._db()
        try:
            summary = demo_operations_service.run_lifecycle_for_demo(
                db, actor=self._actor(db), provisioning_id=self.fixture["provisioning_id"],
                operation_key="single-run",
            )
            db.commit()
            assert summary.demos_checked == 1
            assert (
                summary.reminders_created + summary.demos_expired
                + summary.no_action_count + summary.failures
            ) == 1
            other_group = models.SchoolGroup(
                name="Unrelated paid workspace", workspace_classification="customer_paid",
                workspace_lifecycle_status="active",
            )
            db.add(other_group)
            db.commit()
            factory = self.workflow.Session
            global_summary = demo_operations_service.run_lifecycle_for_all(
                factory, actor=self._actor(db), operation_key="global-run"
            )
            assert global_summary.demos_checked >= 1
            assert db.get(models.SchoolGroup, other_group.id).workspace_lifecycle_status == "active"
        finally:
            db.close()

    def test_required_reasons_custom_entitlements_and_expiry_override_fail_closed(self):
        db = self.workflow._db()
        try:
            actor = self._actor(db)
            group_id = self.fixture["school_group_id"]
            provisioning_id = self.fixture["provisioning_id"]
            branches = db.query(models.Branch).filter_by(school_group_id=group_id).all()
            user = self._tenant_user(db)

            with pytest.raises(demo_operations_service.DemoOperationError) as missing_reason:
                demo_operations_service.expire_demo_now(
                    db, actor=actor, provisioning_id=provisioning_id,
                    reason="", operation_key="missing-reason",
                )
            assert missing_reason.value.reason_code == "reason_required"
            db.rollback()

            demo_operations_service.change_access_profile(
                db, actor=actor, provisioning_id=provisioning_id,
                profile="custom", reason="Limit the guided evaluation",
                operation_key="custom-three", ai_features=[FEATURE],
                ai_allowances={FEATURE: 3},
            )
            db.commit()
            inherited = demo_access_service.resolve_access(
                db, group_id, branch_id=branches[0].id
            )
            assert inherited.profile == "custom"
            assert inherited.ai_allowances[FEATURE] == 3
            selected = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id, feature_key=FEATURE
            )
            unselected = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id,
                feature_key="ai.exam_analysis",
            )
            assert selected.allowed and selected.usage_limit == 3
            assert unselected.allowed
            assert unselected.usage_limit == 2
            policy = db.query(saas.models.DemoAccessPolicy).filter_by(
                school_group_id=group_id, branch_id=None
            ).one()
            policy.product_features_json = "[]"
            db.flush()
            db_migrations._capacity_based_packaging_and_customer_feature_baseline(
                db.get_bind(), db.connection()
            )
            db_migrations._capacity_based_packaging_and_customer_feature_baseline(
                db.get_bind(), db.connection()
            )
            db.refresh(policy)
            assert "feature.advanced_reporting" in json.loads(
                policy.product_features_json
            )
            user.scope_school_group_id = group_id
            user.scope_branch_id = branches[0].id
            assert entitlement_service.can_use_feature(
                db,
                user,
                "feature.advanced_reporting",
                "reports.export",
                branch_id=branches[0].id,
            )

            demo_operations_service.change_access_profile(
                db, actor=actor, provisioning_id=provisioning_id,
                profile="full", reason="Temporarily enable the full workshop",
                operation_key="full-before-expiry",
            )
            demo_operations_service.expire_demo_now(
                db, actor=actor, provisioning_id=provisioning_id,
                reason="Workshop ended", operation_key="expire-full",
            )
            db.commit()
            expired = ai_entitlement_service.evaluate_ai_entitlement(
                db, user=user, school_group_id=group_id, feature_key=FEATURE
            )
            assert not expired.allowed
            assert expired.reason_code != "demo_full_access_allowed"

            with pytest.raises(demo_operations_service.DemoOperationError) as unauthorized:
                demo_operations_service.change_access_profile(
                    db, actor=user, provisioning_id=provisioning_id,
                    profile="standard", reason="Tenant attempted change",
                    operation_key="tenant-access-change",
                )
            assert unauthorized.value.reason_code == "platform_owner_required"
        finally:
            db.close()

    def test_demo_operations_do_not_cross_customer_demo_tenants(self):
        other = self.workflow._activate_demo(
            email=f"m8b9-isolation-{uuid.uuid4().hex}@academy.edu",
            owner_user_id=f"8{uuid.uuid4().int % 100000:05d}",
        )
        db = self.workflow._db()
        try:
            first = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning,
                self.fixture["provisioning_id"],
            )
            second = db.get(
                saas.models.SaaSDemoWorkspaceProvisioning, other["provisioning_id"]
            )
            second_expiry = second.demo_expires_at
            demo_operations_service.expire_demo_now(
                db, actor=self._actor(db), provisioning_id=first.id,
                reason="Isolated lifecycle test", operation_key="tenant-one-only",
            )
            db.commit()
            db.refresh(second)
            assert second.school_group_id == other["school_group_id"]
            assert second.expired_at is None
            assert second.demo_expires_at == second_expiry
            assert db.get(
                models.SchoolGroup, second.school_group_id
            ).workspace_lifecycle_status == "active"
            assert db.query(saas.models.DemoOperationAudit).filter_by(
                demo_provisioning_id=second.id
            ).count() == 0
        finally:
            db.close()
