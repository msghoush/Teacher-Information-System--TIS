import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db_migrations
import models
import saas.models
from dependencies import get_db
from saas import (
    commercial_authority_service,
    promo_code_service,
    promo_redemption_service,
    service,
    subscription_portal_service,
)
from saas.router import router as saas_router


class PromoCommercialPortalTests(unittest.TestCase):
    def setUp(self):
        self.old_secret = os.environ.get("TIS_PROMO_CODE_HMAC_SECRET")
        os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = (
            "promo-commercial-portal-test-secret-long-enough"
        )
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.db = self.Session()
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
        self.fixture = self._create_promo_workspace()

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()
        if self.old_secret is None:
            os.environ.pop("TIS_PROMO_CODE_HMAC_SECRET", None)
        else:
            os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = self.old_secret

    def _account(self, email: str):
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=email,
            email_normalized=email.lower(),
            password_hash=auth.get_password_hash("promo-portal-password-123"),
            first_name="Promo",
            last_name="Owner",
            status="active",
            onboarding_status="tenant_active",
            account_purpose="customer",
            email_verified_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        self.db.add(account)
        self.db.flush()
        return account

    def _create_promo_workspace(self):
        plan = self.db.query(saas.models.SubscriptionPlan).filter_by(
            plan_code="enterprise_ai"
        ).one()
        plan.plan_name = "Enterprise AI"
        plan.max_branches = 25
        plan.max_staff_users = 100
        plan.max_system_users = 100
        plan.max_teachers = 500
        plan.is_active = True
        plan.is_public = True

        platform_owner = models.User(
            user_id="PROMOPLAT01",
            username="promo.portal.platform",
            email="promo.portal.platform@example.com",
            email_normalized="promo.portal.platform@example.com",
            user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER,
            access_scope=auth.ACCESS_SCOPE_GLOBAL,
            is_active=True,
        )
        account = self._account("promo.portal.owner@example.edu")
        group = models.SchoolGroup(
            name="Promo Portal Academy",
            workspace_classification="customer",
            workspace_lifecycle_status="provisioning",
        )
        self.db.add_all((platform_owner, group))
        self.db.flush()
        branches = [
            models.Branch(
                school_group_id=group.id,
                name=f"Campus {index}",
                status=True,
            )
            for index in range(1, 5)
        ]
        year = models.AcademicYear(
            school_group_id=group.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.db.add_all((*branches, year))
        self.db.flush()
        owner = models.User(
            user_id="PROMOOWN01",
            username="promo.portal.owner",
            email=account.email,
            email_normalized=account.email_normalized,
            user_type=auth.USER_TYPE_TENANT,
            role=auth.ROLE_ADMINISTRATOR,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            school_group_id=group.id,
            branch_id=branches[0].id,
            academic_year_id=year.id,
            is_active=True,
        )
        staff = models.User(
            user_id="PROMOSTAF01",
            username="promo.portal.staff",
            email="promo.portal.staff@example.edu",
            email_normalized="promo.portal.staff@example.edu",
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_BRANCH,
            school_group_id=group.id,
            branch_id=branches[1].id,
            academic_year_id=year.id,
            is_active=True,
        )
        self.db.add_all((owner, staff))
        self.db.flush()
        self.db.add(
            saas.models.SaaSAccountUserLink(
                saas_account_id=account.id,
                operational_user_id=owner.id,
                school_group_id=group.id,
                link_type="tenant_owner",
            )
        )
        for index in range(41):
            self.db.add(
                models.Teacher(
                    teacher_id=f"T{index + 1:09d}",
                    first_name="Teacher",
                    last_name=str(index + 1),
                    branch_id=branches[index % len(branches)].id,
                    academic_year_id=year.id,
                )
            )
        self.db.commit()

        now = datetime.now(timezone.utc)
        with patch("saas.promo_code_service.audit.write_audit_event"):
            created = promo_code_service.create_promo(
                self.db,
                actor=platform_owner,
                values={
                    "title": "Portal access",
                    "subscription_plan_id": plan.id,
                    "max_branches": 4,
                    "max_system_users": 100,
                    "max_teachers": 200,
                    "scope_type": "organization",
                    "school_group_id": group.id,
                    "pending_organization_id": None,
                    "intended_account_email_normalized": account.email_normalized,
                    "permitted_email_domain_normalized": None,
                    "branch_ids": tuple(branch.id for branch in branches),
                    "transferable": False,
                    "one_redemption_per_organization": True,
                    "max_total_redemptions": 1,
                    "valid_from": now - timedelta(minutes=1),
                    "redemption_deadline": now + timedelta(days=30),
                    "fixed_access_expires_at": datetime(2027, 8, 25, tzinfo=timezone.utc),
                    "access_duration_days": None,
                    "grace_period_days": 0,
                },
            )
            promo_code_service.activate_promo(
                self.db,
                promo_uuid=created.promo.promo_uuid,
                actor=platform_owner,
            )
        self.db.commit()
        review = promo_redemption_service.start_activation(
            self.db,
            account=account,
            raw_code=created.raw_code,
            school_group=group,
            operational_user=owner,
            idempotency_key="promo-portal-start",
        )
        if review.selection_required:
            review = promo_redemption_service.select_branches(
                self.db,
                activation_uuid=review.session.activation_uuid,
                account=account,
                branch_ids=[branch.id for branch in branches],
            )
        with patch("saas.promo_redemption_service.audit.write_audit_event"):
            activated = promo_redemption_service.activate_promo(
                self.db,
                activation_uuid=review.session.activation_uuid,
                account=account,
                idempotency_key="promo-portal-activate",
            )
        session_token, _csrf_token, _session = service.create_session(self.db, account)
        self.db.commit()
        return {
            "account": account,
            "group": group,
            "session_token": session_token,
            "raw_code": created.raw_code,
            "masked_reference": activated.redemption.masked_promo_reference,
        }

    def test_promo_customer_receives_source_aware_commercial_access_page(self):
        self.client.cookies.set(
            service.SAAS_SESSION_COOKIE,
            self.fixture["session_token"],
        )
        with (
            patch.object(subscription_portal_service, "build_subscription_portal") as paid_portal,
            patch("saas.billing_history_service.paddle_client.list_transactions") as paddle_transactions,
            patch("saas.paddle_client.create_transaction") as paddle_checkout,
        ):
            response = self.client.get(
                "/saas/subscription?organization_uuid="
                + str(self.fixture["group"].workspace_uuid),
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Commercial Access", response.text)
        self.assertIn("Enterprise AI", response.text)
        self.assertIn("Promotional Access", response.text)
        self.assertIn("Active", response.text)
        self.assertIn("25 Aug 2027", response.text)
        self.assertIn(self.fixture["masked_reference"], response.text)
        self.assertNotIn(self.fixture["raw_code"], response.text)
        self.assertIn("4 of 4 used", response.text)
        self.assertIn("0 available", response.text)
        self.assertIn("2 of 100 used", response.text)
        self.assertIn("98 available", response.text)
        self.assertIn("41 of 200 used", response.text)
        self.assertIn("159 available", response.text)
        self.assertIn("No recurring subscription while promotional access is active.", response.text)
        for paid_only_text in (
            "Billing Interval",
            "Recurring Total",
            "Billing History",
            "Invoice History",
            "Review Capacity",
            "Change Plan",
            "Cancel at Period End",
            "Preview Upgrade",
            "Preview Downgrade",
        ):
            self.assertNotIn(paid_only_text, response.text)
        paid_portal.assert_not_called()
        paddle_transactions.assert_not_called()
        paddle_checkout.assert_not_called()
        authority = commercial_authority_service.resolve_commercial_authority(
            self.db,
            self.fixture["group"].id,
        )
        self.assertEqual(authority.source, commercial_authority_service.PROMO_GRANT)
        self.assertEqual(authority.usage.branches, 4)
        self.assertEqual(authority.usage.staff_users, 2)
        self.assertEqual(authority.usage.teachers, 41)

    def test_billing_permission_and_tenant_selection_remain_enforced(self):
        unauthorized = self._account("promo.portal.member@example.edu")
        user = models.User(
            user_id="PROMOMEM001",
            username="promo.portal.member",
            email=unauthorized.email,
            email_normalized=unauthorized.email_normalized,
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_BRANCH,
            school_group_id=self.fixture["group"].id,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(
            saas.models.SaaSAccountUserLink(
                saas_account_id=unauthorized.id,
                operational_user_id=user.id,
                school_group_id=self.fixture["group"].id,
                link_type="tenant_user",
            )
        )
        unauthorized_token, _csrf, _session = service.create_session(self.db, unauthorized)

        other_owner = self._account("promo.portal.other@example.edu")
        other_group = models.SchoolGroup(
            name="Other Tenant",
            workspace_classification="customer",
            workspace_lifecycle_status="active",
        )
        self.db.add(other_group)
        self.db.flush()
        other_user = models.User(
            user_id="PROMOOTHR01",
            username="promo.portal.other",
            email=other_owner.email,
            email_normalized=other_owner.email_normalized,
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            school_group_id=other_group.id,
            is_active=True,
        )
        self.db.add(other_user)
        self.db.flush()
        self.db.add(
            saas.models.SaaSAccountUserLink(
                saas_account_id=other_owner.id,
                operational_user_id=other_user.id,
                school_group_id=other_group.id,
                link_type="tenant_owner",
            )
        )
        other_token, _csrf, _session = service.create_session(self.db, other_owner)
        self.db.commit()

        target = str(self.fixture["group"].workspace_uuid)
        self.client.cookies.set(service.SAAS_SESSION_COOKIE, unauthorized_token)
        denied = self.client.get(
            f"/saas/subscription?organization_uuid={target}",
            follow_redirects=False,
        )
        self.assertEqual(denied.status_code, 403)

        self.client.cookies.set(service.SAAS_SESSION_COOKIE, other_token)
        isolated = self.client.get(
            f"/saas/subscription?organization_uuid={target}",
            follow_redirects=False,
        )
        self.assertEqual(isolated.status_code, 403)

        self.client.cookies.set(
            service.SAAS_SESSION_COOKIE,
            self.fixture["session_token"],
        )
        invalid = self.client.get(
            "/saas/subscription?organization_uuid=not-a-workspace",
            follow_redirects=False,
        )
        self.assertEqual(invalid.status_code, 403)

    def test_expired_promo_fails_closed_without_internal_diagnostics(self):
        grant = self.db.query(saas.models.PromoGrant).filter_by(
            school_group_id=self.fixture["group"].id
        ).one()
        grant.status = "expired"
        grant.expired_at = datetime.now(timezone.utc).replace(tzinfo=None)
        grant.effective_from = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        grant.effective_to = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
        self.db.commit()
        self.client.cookies.set(
            service.SAAS_SESSION_COOKIE,
            self.fixture["session_token"],
        )

        response = self.client.get(
            "/saas/subscription?organization_uuid="
            + str(self.fixture["group"].workspace_uuid),
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Expired", response.text)
        self.assertIn("promotional access period has ended", response.text)
        self.assertNotIn("4 of 4 used", response.text)
        self.assertNotIn("promo_grant_expired", response.text)
        self.assertNotIn("TenantProvisioningLink", response.text)
        self.assertNotIn("PromoGrant", response.text)


if __name__ == "__main__":
    unittest.main()
