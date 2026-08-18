import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db_migrations
import models
import saas.models
from dependencies import get_db
from saas import (
    branch_entitlement_service,
    commercial_access_service,
    commercial_authority_service,
    promo_code_service,
    promo_redemption_service,
    service,
)
from saas.router import router as saas_router


class PromoRedemptionTests(unittest.TestCase):
    def setUp(self):
        self.old_secret = os.environ.get("TIS_PROMO_CODE_HMAC_SECRET")
        os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = "promo-redemption-tests-need-thirty-two-bytes-minimum"
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.Session()
        self.plans = {}
        for order, (code, name, branches, users, teachers) in enumerate((
            ("starter", "Starter", 1, 5, 25),
            ("professional", "Professional", 5, 20, 100),
            ("enterprise_ai", "Enterprise AI", 25, 100, 500),
        ), 1):
            plan = self.db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code=code
            ).one_or_none()
            if plan is None:
                plan = saas.models.SubscriptionPlan(plan_code=code, plan_name=name)
                self.db.add(plan)
            plan.plan_name = name
            plan.sort_order = order
            plan.max_branches = branches
            plan.max_staff_users = users
            plan.max_system_users = users
            plan.max_teachers = teachers
            plan.is_active = True
            plan.is_public = True
            self.db.flush()
            self.plans[code] = plan
        self.actor = models.User(
            user_id="9900000001",
            username="promo.test.owner",
            email="promo.test.owner@example.com",
            email_normalized="promo.test.owner@example.com",
            user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER,
            access_scope=auth.ACCESS_SCOPE_GLOBAL,
            is_active=True,
        )
        self.db.add(self.actor)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        if self.old_secret is None:
            os.environ.pop("TIS_PROMO_CODE_HMAC_SECRET", None)
        else:
            os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = self.old_secret

    def _account(self, email=None):
        email = email or f"{uuid.uuid4().hex}@example.edu"
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=email,
            email_normalized=email,
            status="active",
            onboarding_status="ready_for_checkout",
            account_purpose="customer",
            email_verified_at=datetime.utcnow(),
        )
        self.db.add(account)
        self.db.flush()
        return account

    def _promo(self, plan_code="professional", **overrides):
        now = datetime.now(timezone.utc)
        plan = self.plans[plan_code]
        values = {
            "title": "Customer promo",
            "subscription_plan_id": plan.id,
            "max_branches": plan.max_branches,
            "max_system_users": plan.max_system_users,
            "max_teachers": plan.max_teachers,
            "scope_type": "global",
            "school_group_id": None,
            "pending_organization_id": None,
            "intended_account_email_normalized": None,
            "permitted_email_domain_normalized": None,
            "branch_ids": (),
            "transferable": False,
            "one_redemption_per_organization": True,
            "max_total_redemptions": 10,
            "valid_from": now - timedelta(minutes=1),
            "redemption_deadline": now + timedelta(days=30),
            "fixed_access_expires_at": None,
            "access_duration_days": 90,
            "grace_period_days": 2,
        }
        values.update(overrides)
        with patch("saas.promo_code_service.audit.write_audit_event"):
            created = promo_code_service.create_promo(
                self.db, actor=self.actor, values=values
            )
            promo_code_service.activate_promo(
                self.db, promo_uuid=created.promo.promo_uuid, actor=self.actor
            )
        self.db.commit()
        return created

    def _pending(self, account, branch_count=2, staff=4, teachers=20):
        organization = saas.models.PendingOrganization(
            organization_uuid=str(uuid.uuid4()),
            owner_saas_account_id=account.id,
            workspace_intent="customer_paid",
            organization_name=f"Promo Academy {uuid.uuid4().hex[:6]}",
            status="ready_for_checkout",
            educational_program="NATIONAL",
            timezone="Asia/Beirut",
        )
        self.db.add(organization)
        self.db.flush()
        per_staff = staff // branch_count
        per_teachers = teachers // branch_count
        for index in range(branch_count):
            self.db.add(saas.models.PendingOrganizationBranch(
                pending_organization_id=organization.id,
                branch_name=f"Campus {index + 1}",
                estimated_system_users=per_staff + (staff % branch_count if index == 0 else 0),
                estimated_teachers=per_teachers + (teachers % branch_count if index == 0 else 0),
                status=True,
                sort_order=index,
            ))
        self.db.add(saas.models.PendingOrganizationAcademicSetup(
            pending_organization_id=organization.id,
            first_academic_year_name="2026-2027",
        ))
        self.db.add(saas.models.PendingOrganizationContact(
            pending_organization_id=organization.id,
            contact_type="owner",
            first_name="Promo",
            last_name="Owner",
            email=account.email,
            email_normalized=account.email_normalized,
            is_primary=True,
        ))
        self.db.commit()
        return organization

    @patch("saas.promo_redemption_service.audit.write_audit_event")
    def test_onboarding_activation_creates_immutable_promo_authority(self, _audit):
        account = self._account()
        organization = self._pending(account, branch_count=2)
        created = self._promo("professional")
        review = promo_redemption_service.start_activation(
            self.db,
            account=account,
            raw_code=created.raw_code,
            pending_organization=organization,
            idempotency_key="start-new-org",
        )
        self.assertTrue(review.ready_to_activate)
        result = promo_redemption_service.activate_promo(
            self.db,
            activation_uuid=review.session.activation_uuid,
            account=account,
            idempotency_key="activate-new-org",
        )
        self.db.commit()

        self.assertEqual(result.school_group.workspace_classification, "customer")
        self.assertEqual(result.school_group.workspace_lifecycle_status, "active")
        self.assertEqual(result.grant.plan_code_snapshot, "professional")
        self.assertEqual(result.tenant_link.promo_grant_id, result.grant.id)
        self.assertIsNone(result.tenant_link.subscription_contract_id)
        self.assertIsNone(result.tenant_link.demo_request_id)
        self.assertEqual(organization.payment_status, "not_required")
        authority = commercial_authority_service.resolve_commercial_authority(
            self.db, result.school_group.id
        )
        self.assertTrue(authority.access_allowed)
        self.assertEqual(authority.source, "promo_grant")
        self.assertEqual(authority.plan_code, "professional")

    @patch("saas.promo_redemption_service.audit.write_audit_event")
    def test_existing_aligned_organization_activates_without_pending_record(self, _audit):
        account = self._account()
        group = models.SchoolGroup(
            name="Aligned Customer",
            workspace_classification="customer",
            workspace_lifecycle_status="provisioning",
        )
        self.db.add(group)
        self.db.flush()
        branch = models.Branch(school_group_id=group.id, name="Main", status=True)
        year = models.AcademicYear(school_group_id=group.id, year_name="2026-2027", is_active=True)
        self.db.add_all((branch, year))
        self.db.flush()
        user = models.User(
            user_id="8800000001",
            username="aligned.owner",
            email=account.email,
            email_normalized=account.email_normalized,
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            school_group_id=group.id,
            branch_id=branch.id,
            academic_year_id=year.id,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(saas.models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=user.id,
            pending_organization_id=None,
            school_group_id=group.id,
            link_type="tenant_owner",
        ))
        self.db.commit()
        created = self._promo("starter")
        review = promo_redemption_service.start_activation(
            self.db,
            account=account,
            raw_code=created.raw_code,
            school_group=group,
            operational_user=user,
            idempotency_key="start-existing",
        )
        result = promo_redemption_service.activate_promo(
            self.db,
            activation_uuid=review.session.activation_uuid,
            account=account,
            idempotency_key="activate-existing",
        )
        self.db.commit()
        self.assertIsNone(result.redemption.pending_organization_id)
        self.assertIsNone(result.tenant_link.pending_organization_id)
        self.assertEqual(result.tenant_link.promo_grant_id, result.grant.id)
        self.assertEqual(self.db.query(saas.models.PendingOrganization).count(), 0)
        access = commercial_access_service.resolve_workspace_access(
            self.db, result.school_group.id
        )
        self.assertTrue(access.allowed_access)
        self.assertEqual(access.commercial_state, commercial_access_service.ACTIVE)
        self.assertNotEqual(
            access.commercial_state,
            commercial_access_service.PAYMENT_PROCESSING,
        )

    def test_over_limit_staff_and_teachers_block_without_mutation(self):
        account = self._account()
        organization = self._pending(account, branch_count=1, staff=6, teachers=26)
        created = self._promo("starter")
        review = promo_redemption_service.start_activation(
            self.db,
            account=account,
            raw_code=created.raw_code,
            pending_organization=organization,
            idempotency_key="over-limit",
        )
        self.assertFalse(review.ready_to_activate)
        self.assertEqual(set(review.exceeded_dimensions), {"staff_users", "teachers"})
        with self.assertRaises(promo_redemption_service.PromoActivationError):
            promo_redemption_service.activate_promo(
                self.db,
                activation_uuid=review.session.activation_uuid,
                account=account,
                idempotency_key="blocked-over-limit",
            )
        self.db.rollback()


        self.assertEqual(self.db.query(models.SchoolGroup).filter_by(name=organization.organization_name).count(), 0)
        self.assertEqual(self.db.query(saas.models.PromoGrant).count(), 0)

    @patch("saas.promo_redemption_service.audit.write_audit_event")
    def test_branch_selection_preserves_unselected_operational_branch(self, _audit):
        account = self._account()
        group = models.SchoolGroup(
            name="Branch Selection Customer",
            workspace_classification="customer",
            workspace_lifecycle_status="provisioning",
        )
        self.db.add(group)
        self.db.flush()
        branches = [models.Branch(school_group_id=group.id, name=f"Campus {i}", status=True) for i in range(1, 3)]
        year = models.AcademicYear(school_group_id=group.id, year_name="2026-2027", is_active=True)
        self.db.add_all((*branches, year))
        self.db.flush()
        user = models.User(user_id="7700000001", username="branch.owner", user_type=auth.USER_TYPE_TENANT, access_scope=auth.ACCESS_SCOPE_ORGANIZATION, school_group_id=group.id, branch_id=branches[0].id, academic_year_id=year.id, is_active=True)
        self.db.add(user)
        self.db.flush()
        self.db.add(saas.models.SaaSAccountUserLink(saas_account_id=account.id, operational_user_id=user.id, school_group_id=group.id, link_type="tenant_owner"))
        self.db.commit()
        created = self._promo("starter")
        review = promo_redemption_service.start_activation(self.db, account=account, raw_code=created.raw_code, school_group=group, operational_user=user, idempotency_key="branch-selection")
        self.assertTrue(review.selection_required)
        review = promo_redemption_service.select_branches(self.db, activation_uuid=review.session.activation_uuid, account=account, branch_ids=[branches[0].id])
        self.assertTrue(review.ready_to_activate)
        promo_redemption_service.activate_promo(self.db, activation_uuid=review.session.activation_uuid, account=account, idempotency_key="activate-selection")
        self.db.commit()
        self.db.refresh(branches[1])
        self.assertTrue(branches[1].status)
        inactive = branch_entitlement_service.resolve_branch_entitlement(self.db, branches[1].id)
        self.assertEqual(inactive.effective_status, "inactive")

    @patch("saas.promo_redemption_service.audit.write_audit_event")
    def test_existing_inactive_branch_receives_explicit_inactive_entitlement(self, _audit):
        account = self._account()
        group = models.SchoolGroup(
            name="Inactive Branch Promo Customer",
            workspace_classification="customer",
            workspace_lifecycle_status="provisioning",
        )
        self.db.add(group)
        self.db.flush()
        selected = models.Branch(school_group_id=group.id, name="Selected", status=True)
        other_active = models.Branch(school_group_id=group.id, name="Other Active", status=True)
        preserved_inactive = models.Branch(
            school_group_id=group.id, name="Preserved Inactive", status=False
        )
        year = models.AcademicYear(
            school_group_id=group.id, year_name="2026-2027", is_active=True
        )
        self.db.add_all((selected, other_active, preserved_inactive, year))
        self.db.flush()
        user = models.User(
            user_id="7700000002",
            username="inactive.branch.owner",
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            school_group_id=group.id,
            branch_id=selected.id,
            academic_year_id=year.id,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(saas.models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=user.id,
            school_group_id=group.id,
            link_type="tenant_owner",
        ))
        self.db.commit()
        created = self._promo("starter")
        review = promo_redemption_service.start_activation(
            self.db,
            account=account,
            raw_code=created.raw_code,
            school_group=group,
            operational_user=user,
            idempotency_key="inactive-branch-selection",
        )
        review = promo_redemption_service.select_branches(
            self.db,
            activation_uuid=review.session.activation_uuid,
            account=account,
            branch_ids=[selected.id],
        )
        result = promo_redemption_service.activate_promo(
            self.db,
            activation_uuid=review.session.activation_uuid,
            account=account,
            idempotency_key="activate-inactive-branch-selection",
        )
        self.db.commit()

        rows = {
            row.branch_id: row
            for row in self.db.query(saas.models.BranchEntitlement).filter_by(
                workspace_entitlement_id=result.workspace_entitlement.id
            ).all()
        }
        self.assertEqual(set(rows), {selected.id, other_active.id, preserved_inactive.id})
        self.assertEqual(rows[selected.id].entitlement_mode, "active")
        self.assertEqual(rows[other_active.id].entitlement_mode, "inactive")
        self.assertEqual(rows[preserved_inactive.id].entitlement_mode, "inactive")
        self.assertEqual(result.grant.allowed_branches, 1)
        self.assertFalse(self.db.get(models.Branch, preserved_inactive.id).status)
        assignment_ids = {
            row.branch_id
            for row in self.db.query(saas.models.PromoGrantBranchAssignment).filter_by(
                promo_grant_id=result.grant.id
            ).all()
        }
        self.assertEqual(assignment_ids, {selected.id})

    def test_internal_sandbox_is_not_auto_converted(self):
        account = self._account()
        group = models.SchoolGroup(name="Internal", workspace_classification="internal_sandbox", workspace_lifecycle_status="active")
        self.db.add(group)
        self.db.flush()
        branch = models.Branch(school_group_id=group.id, name="Main", status=True)
        year = models.AcademicYear(school_group_id=group.id, year_name="2026-2027", is_active=True)
        self.db.add_all((branch, year))
        self.db.flush()
        user = models.User(user_id="6600000001", username="internal.owner", user_type=auth.USER_TYPE_TENANT, access_scope=auth.ACCESS_SCOPE_ORGANIZATION, school_group_id=group.id, branch_id=branch.id, academic_year_id=year.id, is_active=True)
        self.db.add(user)
        self.db.flush()
        self.db.add(saas.models.SaaSAccountUserLink(saas_account_id=account.id, operational_user_id=user.id, school_group_id=group.id, link_type="tenant_owner"))
        self.db.commit()
        created = self._promo("starter")
        with self.assertRaises(promo_redemption_service.PromoActivationError) as caught:
            promo_redemption_service.start_activation(self.db, account=account, raw_code=created.raw_code, school_group=group, operational_user=user, idempotency_key="internal-blocked")
        self.assertEqual(caught.exception.reason_code, "promo_existing_workspace_not_aligned")

    def test_existing_aligned_owner_can_reach_promo_journey_with_csrf_protection(self):
        account = self._account()
        group = models.SchoolGroup(
            name="Reachable Promo Customer",
            workspace_classification="customer",
            workspace_lifecycle_status="provisioning",
        )
        self.db.add(group)
        self.db.flush()
        branch = models.Branch(school_group_id=group.id, name="Main", status=True)
        year = models.AcademicYear(
            school_group_id=group.id,
            year_name="2026-2027",
            is_active=True,
        )
        self.db.add_all((branch, year))
        self.db.flush()
        user = models.User(
            user_id="6500000001",
            username="reachable.owner",
            email=account.email,
            email_normalized=account.email_normalized,
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            school_group_id=group.id,
            branch_id=branch.id,
            academic_year_id=year.id,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        self.db.add(saas.models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=user.id,
            school_group_id=group.id,
            link_type="tenant_owner",
        ))
        session_token, csrf_token, _session = service.create_session(self.db, account)
        self.db.commit()

        app = FastAPI()
        app.mount("/static", StaticFiles(directory="static"), name="static")
        app.include_router(saas_router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            client.cookies.set(service.SAAS_SESSION_COOKIE, session_token)
            client.cookies.set(service.SAAS_CSRF_COOKIE, csrf_token)
            overview = client.get(
                f"/saas/account?organization_uuid={group.workspace_uuid}"
            )
            self.assertEqual(overview.status_code, 200)
            self.assertIn("Activation required", overview.text)
            self.assertNotIn("Payment processing", overview.text)
            self.assertIn("Use Promo Code", overview.text)
            self.assertIn(
                f"/saas/promo?organization_uuid={group.workspace_uuid}",
                overview.text,
            )
            entry = client.get(
                f"/saas/promo?organization_uuid={group.workspace_uuid}"
            )
            self.assertEqual(entry.status_code, 200)
            self.assertIn('name="promo_code"', entry.text)
            blocked = client.post(
                "/saas/promo/start",
                data={
                    "organization_uuid": str(group.workspace_uuid),
                    "promo_code": "NOT-A-VALID-CODE",
                    "csrf_token": "wrong-token",
                },
            )
            self.assertEqual(blocked.status_code, 403)

    def test_completed_onboarding_can_start_resume_safe_promo_review(self):
        account = self._account()
        organization = self._pending(account, branch_count=2, staff=4, teachers=20)
        created = self._promo("professional")
        progress = service.recalculate_pending_progress(self.db, organization)
        progress.review_complete = True
        session_token, csrf_token, _session = service.create_session(self.db, account)
        self.db.commit()

        app = FastAPI()
        app.mount("/static", StaticFiles(directory="static"), name="static")
        app.include_router(saas_router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            client.cookies.set(service.SAAS_SESSION_COOKIE, session_token)
            client.cookies.set(service.SAAS_CSRF_COOKIE, csrf_token)
            choice = client.get(
                f"/saas/onboarding/{organization.organization_uuid}/commercial-choice"
            )
            self.assertEqual(choice.status_code, 200)
            self.assertIn("Request Demo", choice.text)
            self.assertIn("Subscribe Now", choice.text)
            self.assertIn("Use Promo Code", choice.text)

            started = client.post(
                "/saas/promo/start",
                data={
                    "organization_uuid": organization.organization_uuid,
                    "promo_code": created.raw_code,
                    "csrf_token": csrf_token,
                },
                follow_redirects=False,
            )
            self.assertEqual(started.status_code, 302)
            self.assertTrue(started.headers["location"].startswith("/saas/promo/"))
            review = client.get(started.headers["location"])
            self.assertEqual(review.status_code, 200)
            self.assertIn("2 / 5", review.text)
            self.assertIn("4 / 20", review.text)
            self.assertIn("20 / 100", review.text)
            self.assertIn("Activate Promo Access", review.text)
            resumed = client.get(
                f"/saas/promo?organization_uuid={organization.organization_uuid}",
                follow_redirects=False,
            )
            self.assertEqual(resumed.status_code, 302)
            self.assertEqual(resumed.headers["location"], started.headers["location"])

    @patch("saas.promo_redemption_service.audit.write_audit_event")
    def test_activation_is_idempotent_and_raw_code_is_never_persisted(self, _audit):
        account = self._account()
        organization = self._pending(account, branch_count=1)
        created = self._promo("starter")
        review = promo_redemption_service.start_activation(
            self.db, account=account, raw_code=created.raw_code,
            pending_organization=organization, idempotency_key="idempotent-start",
        )
        first = promo_redemption_service.activate_promo(
            self.db, activation_uuid=review.session.activation_uuid,
            account=account, idempotency_key="idempotent-activate",
        )
        self.db.commit()
        second = promo_redemption_service.activate_promo(
            self.db, activation_uuid=review.session.activation_uuid,
            account=account, idempotency_key="different-retry-key",
        )
        self.assertEqual(first.redemption.id, second.redemption.id)
        self.assertEqual(self.db.query(saas.models.PromoRedemption).count(), 1)
        persisted = "|".join(
            str(value)
            for model in (
                saas.models.PromoActivationSession,
                saas.models.PromoRedemption,
                saas.models.PromoGrant,
                saas.models.PromoRedemptionEvent,
            )
            for row in self.db.query(model).all()
            for value in row.__dict__.values()
        )
        self.assertNotIn(created.raw_code, persisted)

    @patch("saas.promo_redemption_service.audit.write_audit_event")
    def test_expired_grant_fails_closed_and_branch_query_excludes_unselected(self, _audit):
        account = self._account()
        group = models.SchoolGroup(name="Expiry Customer", workspace_classification="customer", workspace_lifecycle_status="provisioning")
        self.db.add(group)
        self.db.flush()
        branches = [models.Branch(school_group_id=group.id, name=f"Expiry {i}", status=True) for i in range(2)]
        year = models.AcademicYear(school_group_id=group.id, year_name="2026-2027", is_active=True)
        self.db.add_all((*branches, year))
        self.db.flush()
        user = models.User(user_id="5500000001", username="expiry.owner", user_type=auth.USER_TYPE_TENANT, access_scope=auth.ACCESS_SCOPE_ORGANIZATION, school_group_id=group.id, branch_id=branches[0].id, academic_year_id=year.id, is_active=True)
        self.db.add(user)
        self.db.flush()
        self.db.add(saas.models.SaaSAccountUserLink(saas_account_id=account.id, operational_user_id=user.id, school_group_id=group.id, link_type="tenant_owner"))
        self.db.commit()
        created = self._promo("starter")
        review = promo_redemption_service.start_activation(self.db, account=account, raw_code=created.raw_code, school_group=group, operational_user=user, idempotency_key="expiry-start")
        promo_redemption_service.select_branches(self.db, activation_uuid=review.session.activation_uuid, account=account, branch_ids=[branches[0].id])
        activated = promo_redemption_service.activate_promo(self.db, activation_uuid=review.session.activation_uuid, account=account, idempotency_key="expiry-activate")
        self.db.commit()
        accessible = {row.id for row in auth.get_accessible_branch_query(self.db, user).all()}
        self.assertEqual(accessible, {branches[0].id})
        activated.grant.effective_from = datetime.utcnow() - timedelta(days=2)
        activated.grant.effective_to = datetime.utcnow() - timedelta(days=1)
        self.db.commit()
        authority = commercial_authority_service.resolve_commercial_authority(self.db, group.id)
        self.assertFalse(authority.access_allowed)
        self.assertEqual(auth.get_accessible_branch_query(self.db, user).count(), 0)

    def test_migration_is_registered_idempotent_and_source_constraint_is_exclusive(self):
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue({
            "promo_activation_sessions", "promo_activation_branch_selections",
            "promo_redemptions", "promo_grants", "promo_grant_branch_assignments",
            "promo_redemption_events",
        }.issubset(tables))
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = "
                "'20260805_002_promo_redemption_and_grants'"
            )).scalar_one(), 1)
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])
        account = self._account()
        group = models.SchoolGroup(name="Constraint Customer", workspace_classification="customer", workspace_lifecycle_status="provisioning")
        self.db.add(group)
        self.db.flush()
        branch = models.Branch(school_group_id=group.id, name="Main", status=True)
        user = models.User(user_id="4400000001", username="constraint.owner", user_type=auth.USER_TYPE_TENANT, access_scope=auth.ACCESS_SCOPE_ORGANIZATION, school_group_id=group.id, is_active=True)
        self.db.add_all((branch, user))
        self.db.flush()
        invalid = saas.models.TenantProvisioningLink(
            pending_organization_id=None,
            subscription_contract_id=None,
            demo_request_id=None,
            promo_grant_id=None,
            school_group_id=group.id,
            owner_operational_user_id=user.id,
            primary_branch_id=branch.id,
            tenant_status="tenant_active",
        )
        self.db.add(invalid)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()


@unittest.skipUnless(
    os.getenv("TIS_TEST_POSTGRESQL_URL"),
    "Disposable PostgreSQL URL not configured",
)
class PromoRedemptionPostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_secret = os.environ.get("TIS_PROMO_CODE_HMAC_SECRET")
        os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = (
            "promo-redemption-postgresql-test-secret-long-enough"
        )
        cls.engine = create_engine(os.environ["TIS_TEST_POSTGRESQL_URL"])
        with cls.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        models.Base.metadata.create_all(cls.engine)
        db_migrations.run_pending_migrations(cls.engine)
        with cls.engine.begin() as connection:
            connection.execute(text("DROP TABLE promo_redemption_events CASCADE"))
            connection.execute(text("DROP TABLE promo_grant_branch_assignments CASCADE"))
            connection.execute(text("DROP TABLE promo_activation_branch_selections CASCADE"))
            connection.execute(text("DROP TABLE promo_grants CASCADE"))
            connection.execute(text("DROP TABLE promo_redemptions CASCADE"))
            connection.execute(text("DROP TABLE promo_activation_sessions CASCADE"))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE migration_id = "
                "'20260805_002_promo_redemption_and_grants'"
            ))
        cls.installed_migrations = tuple(db_migrations.run_pending_migrations(cls.engine))
        cls.Session = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        db = cls.Session()
        try:
            plan = db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code="starter"
            ).one()
            plan.plan_name = "Starter"
            plan.max_branches = 1
            plan.max_staff_users = 5
            plan.max_system_users = 5
            plan.max_teachers = 25
            plan.is_active = True
            plan.is_public = True
            actor = models.User(
                user_id="pgpromo01",
                username="pg.promo.activation.owner",
                email="pg.promo.activation.owner@example.com",
                email_normalized="pg.promo.activation.owner@example.com",
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_OWNER,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(actor)
            db.flush()
            now = datetime.now(timezone.utc)
            with patch("saas.promo_code_service.audit.write_audit_event"):
                created = promo_code_service.create_promo(
                    db,
                    actor=actor,
                    values={
                        "title": "Single concurrent redemption",
                        "subscription_plan_id": plan.id,
                        "max_branches": 1,
                        "max_system_users": 5,
                        "max_teachers": 25,
                        "scope_type": "global",
                        "max_total_redemptions": 1,
                        "valid_from": now - timedelta(minutes=1),
                        "redemption_deadline": now + timedelta(days=2),
                        "access_duration_days": 30,
                        "grace_period_days": 0,
                    },
                )
                promo_code_service.activate_promo(
                    db,
                    promo_uuid=created.promo.promo_uuid,
                    actor=actor,
                )
            activation_uuids = []
            account_ids = []
            group_ids = []
            for index in range(2):
                account = saas.models.SaaSAccount(
                    account_uuid=str(uuid.uuid4()),
                    email=f"pg-promo-{index}@example.edu",
                    email_normalized=f"pg-promo-{index}@example.edu",
                    status="active",
                    onboarding_status="ready_for_checkout",
                    account_purpose="customer",
                    email_verified_at=datetime.utcnow(),
                )
                group = models.SchoolGroup(
                    name=f"PostgreSQL Promo Customer {index}",
                    workspace_classification="customer",
                    workspace_lifecycle_status="provisioning",
                )
                db.add_all((account, group))
                db.flush()
                branch = models.Branch(
                    school_group_id=group.id,
                    name="Main",
                    status=True,
                )
                year = models.AcademicYear(
                    school_group_id=group.id,
                    year_name="2026-2027",
                    is_active=True,
                )
                db.add_all((branch, year))
                db.flush()
                user = models.User(
                    user_id=f"pgpromo{index + 2:02d}",
                    username=f"pg.promo.customer.{index}",
                    email=account.email,
                    email_normalized=account.email_normalized,
                    user_type=auth.USER_TYPE_TENANT,
                    access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
                    school_group_id=group.id,
                    branch_id=branch.id,
                    academic_year_id=year.id,
                    is_active=True,
                )
                db.add(user)
                db.flush()
                db.add(saas.models.SaaSAccountUserLink(
                    saas_account_id=account.id,
                    operational_user_id=user.id,
                    school_group_id=group.id,
                    link_type="tenant_owner",
                ))
                db.flush()
                review = promo_redemption_service.start_activation(
                    db,
                    account=account,
                    raw_code=created.raw_code,
                    school_group=group,
                    operational_user=user,
                    idempotency_key=f"pg-start-{index}",
                )
                activation_uuids.append(review.session.activation_uuid)
                account_ids.append(account.id)
                group_ids.append(group.id)
            db.commit()
            cls.activation_uuids = tuple(activation_uuids)
            cls.account_ids = tuple(account_ids)
            cls.group_ids = tuple(group_ids)
            cls.plan_id = plan.id
            cls.actor_id = actor.id
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        cls.engine.dispose()
        if cls.old_secret is None:
            os.environ.pop("TIS_PROMO_CODE_HMAC_SECRET", None)
        else:
            os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = cls.old_secret

    def _create_promo(self, db, *, title, max_redemptions=10, branches=1):
        actor = db.get(models.User, self.actor_id)
        now = datetime.now(timezone.utc)
        with patch("saas.promo_code_service.audit.write_audit_event"):
            created = promo_code_service.create_promo(
                db,
                actor=actor,
                values={
                    "title": title,
                    "subscription_plan_id": self.plan_id,
                    "max_branches": branches,
                    "max_system_users": 5,
                    "max_teachers": 25,
                    "scope_type": "global",
                    "max_total_redemptions": max_redemptions,
                    "valid_from": now - timedelta(minutes=1),
                    "redemption_deadline": now + timedelta(days=2),
                    "access_duration_days": 30,
                    "grace_period_days": 0,
                },
            )
            promo_code_service.activate_promo(
                db,
                promo_uuid=created.promo.promo_uuid,
                actor=actor,
            )
        return created

    def _create_context(self, db, *, label, branch_count=1, classification="customer"):
        unique = uuid.uuid4().hex[:10]
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=f"{unique}@example.edu",
            email_normalized=f"{unique}@example.edu",
            status="active",
            onboarding_status="ready_for_checkout",
            account_purpose="customer",
            email_verified_at=datetime.utcnow(),
        )
        group = models.SchoolGroup(
            name=f"{label} {unique}",
            workspace_classification=classification,
            workspace_lifecycle_status=(
                "provisioning" if classification == "customer" else "active"
            ),
        )
        db.add_all((account, group))
        db.flush()
        year = models.AcademicYear(
            school_group_id=group.id,
            year_name="2026-2027",
            is_active=True,
        )
        branches = [
            models.Branch(
                school_group_id=group.id,
                name=f"Campus {index + 1}",
                status=True,
            )
            for index in range(branch_count)
        ]
        db.add_all((year, *branches))
        db.flush()
        user = models.User(
            user_id=unique,
            username=f"promo.{unique}",
            email=account.email,
            email_normalized=account.email_normalized,
            user_type=auth.USER_TYPE_TENANT,
            access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
            school_group_id=group.id,
            branch_id=branches[0].id,
            academic_year_id=year.id,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(saas.models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=user.id,
            school_group_id=group.id,
            link_type="tenant_owner",
        ))
        db.flush()
        return account, group, user, tuple(branches)

    def _activate(self, db, *, created, account, group, user, branches, key):
        review = promo_redemption_service.start_activation(
            db,
            account=account,
            raw_code=created.raw_code,
            school_group=group,
            operational_user=user,
            idempotency_key=f"{key}:start",
        )
        if review.selection_required:
            review = promo_redemption_service.select_branches(
                db,
                activation_uuid=review.session.activation_uuid,
                account=account,
                branch_ids=[branches[0].id],
            )
        with patch("saas.promo_redemption_service.audit.write_audit_event"):
            result = promo_redemption_service.activate_promo(
                db,
                activation_uuid=review.session.activation_uuid,
                account=account,
                idempotency_key=f"{key}:activate",
            )
        return review, result

    def test_active_grant_uniqueness_is_enforced_by_postgresql(self):
        db = self.Session()
        try:
            account, group, user, branches = self._create_context(
                db, label="Unique Active Grant"
            )
            created = self._create_promo(db, title="Unique active grant")
            _review, result = self._activate(
                db,
                created=created,
                account=account,
                group=group,
                user=user,
                branches=branches,
                key="unique-grant",
            )
            db.commit()
            redemption = result.redemption
            grant = result.grant
            session = result.session
            duplicate_session = saas.models.PromoActivationSession(
                promo_code_id=session.promo_code_id,
                promo_definition_version=session.promo_definition_version,
                school_group_id=group.id,
                saas_account_id=account.id,
                operational_user_id=user.id,
                context_type="existing_organization",
                status="activated",
                stage="activated",
                idempotency_key=f"duplicate-session:{uuid.uuid4()}",
                masked_promo_reference=session.masked_promo_reference,
                expires_at=session.expires_at,
                activated_at=datetime.utcnow(),
            )
            db.add(duplicate_session)
            db.flush()
            duplicate_redemption = saas.models.PromoRedemption(
                activation_session_id=duplicate_session.id,
                promo_code_id=redemption.promo_code_id,
                promo_definition_version=redemption.promo_definition_version,
                school_group_id=group.id,
                redeeming_saas_account_id=account.id,
                redeeming_operational_user_id=user.id,
                redeemed_at=redemption.redeemed_at,
                idempotency_key=f"duplicate-redemption:{uuid.uuid4()}",
                masked_promo_reference=redemption.masked_promo_reference,
                plan_id=redemption.plan_id,
                plan_code_snapshot=redemption.plan_code_snapshot,
                plan_name_snapshot=redemption.plan_name_snapshot,
                allowed_branches=redemption.allowed_branches,
                allowed_staff_users=redemption.allowed_staff_users,
                allowed_teachers=redemption.allowed_teachers,
                effective_from=redemption.effective_from,
                effective_to=redemption.effective_to,
                grace_period_days=redemption.grace_period_days,
                scope_type_snapshot=redemption.scope_type_snapshot,
                scope_snapshot_json=redemption.scope_snapshot_json,
                definition_snapshot_json=redemption.definition_snapshot_json,
                immutable_snapshot_hash=redemption.immutable_snapshot_hash,
            )
            db.add(duplicate_redemption)
            db.flush()
            db.add(saas.models.PromoGrant(
                promo_redemption_id=duplicate_redemption.id,
                school_group_id=group.id,
                plan_id=grant.plan_id,
                plan_code_snapshot=grant.plan_code_snapshot,
                plan_name_snapshot=grant.plan_name_snapshot,
                allowed_branches=grant.allowed_branches,
                allowed_staff_users=grant.allowed_staff_users,
                allowed_teachers=grant.allowed_teachers,
                effective_from=grant.effective_from,
                effective_to=grant.effective_to,
                grace_period_days=grant.grace_period_days,
                definition_snapshot_json=grant.definition_snapshot_json,
                capacity_snapshot_json=grant.capacity_snapshot_json,
                scope_snapshot_json=grant.scope_snapshot_json,
                immutable_snapshot_hash=grant.immutable_snapshot_hash,
                activated_at=grant.activated_at,
            ))
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()
            self.assertEqual(
                db.query(saas.models.PromoGrant).filter_by(
                    school_group_id=group.id,
                    status="active",
                ).count(),
                1,
            )
        finally:
            db.close()

    def test_branch_entitlement_activation_and_rollback_are_atomic(self):
        db = self.Session()
        try:
            account, group, user, branches = self._create_context(
                db, label="Atomic Branches", branch_count=2
            )
            created = self._create_promo(db, title="Atomic branch success")
            _review, result = self._activate(
                db,
                created=created,
                account=account,
                group=group,
                user=user,
                branches=branches,
                key="branch-success",
            )
            db.commit()
            modes = {
                row.branch_id: row.entitlement_mode
                for row in db.query(saas.models.BranchEntitlement).filter_by(
                    school_group_id=group.id,
                    workspace_entitlement_id=result.workspace_entitlement.id,
                ).all()
            }
            self.assertEqual(modes, {branches[0].id: "active", branches[1].id: "inactive"})

            account2, group2, user2, branches2 = self._create_context(
                db, label="Atomic Rollback", branch_count=2
            )
            created2 = self._create_promo(db, title="Atomic branch rollback")
            review2 = promo_redemption_service.start_activation(
                db,
                account=account2,
                raw_code=created2.raw_code,
                school_group=group2,
                operational_user=user2,
                idempotency_key="branch-rollback:start",
            )
            promo_redemption_service.select_branches(
                db,
                activation_uuid=review2.session.activation_uuid,
                account=account2,
                branch_ids=[branches2[0].id],
            )
            db.commit()
            with (
                patch(
                    "saas.promo_redemption_service.audit.write_audit_event",
                    side_effect=RuntimeError("forced final audit failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "forced final audit failure"),
            ):
                promo_redemption_service.activate_promo(
                    db,
                    activation_uuid=review2.session.activation_uuid,
                    account=account2,
                    idempotency_key="branch-rollback:activate",
                )
            db.rollback()
            self.assertEqual(db.query(saas.models.PromoRedemption).filter_by(school_group_id=group2.id).count(), 0)
            self.assertEqual(db.query(saas.models.PromoGrant).filter_by(school_group_id=group2.id).count(), 0)
            self.assertEqual(db.query(saas.models.WorkspaceEntitlement).filter_by(school_group_id=group2.id).count(), 0)
            self.assertEqual(db.query(saas.models.BranchEntitlement).filter_by(school_group_id=group2.id).count(), 0)
            self.assertEqual(db.query(saas.models.PromoGrantBranchAssignment).filter_by(school_group_id=group2.id).count(), 0)
            self.assertEqual(db.query(saas.models.TenantProvisioningLink).filter_by(school_group_id=group2.id).count(), 0)
        finally:
            db.close()

    def test_commercial_source_classifications_block_without_partial_promo_rows(self):
        db = self.Session()
        try:
            created = self._create_promo(db, title="Commercial source conflict")
            db.commit()
            for classification in ("customer_paid", "customer_demo", "internal_sandbox"):
                account, group, user, _branches = self._create_context(
                    db,
                    label=f"Blocked {classification}",
                    classification=classification,
                )
                with self.assertRaises(promo_redemption_service.PromoActivationError):
                    promo_redemption_service.start_activation(
                        db,
                        account=account,
                        raw_code=created.raw_code,
                        school_group=group,
                        operational_user=user,
                        idempotency_key=f"blocked:{classification}",
                    )
                self.assertEqual(db.query(saas.models.PromoActivationSession).filter_by(school_group_id=group.id).count(), 0)
                self.assertEqual(db.query(saas.models.PromoRedemption).filter_by(school_group_id=group.id).count(), 0)
                self.assertEqual(db.query(saas.models.PromoGrant).filter_by(school_group_id=group.id).count(), 0)
            db.rollback()
        finally:
            db.close()

    def test_concurrent_final_redemption_allows_exactly_one_activation(self):
        barrier = threading.Barrier(2)
        results = []

        def activate(index):
            db = self.Session()
            try:
                account = db.get(saas.models.SaaSAccount, self.account_ids[index])
                barrier.wait()
                with patch("saas.promo_redemption_service.audit.write_audit_event"):
                    promo_redemption_service.activate_promo(
                        db,
                        activation_uuid=self.activation_uuids[index],
                        account=account,
                        idempotency_key=f"pg-activate-{index}",
                    )
                db.commit()
                results.append(("success", index))
            except promo_redemption_service.PromoActivationError as exc:
                db.rollback()
                results.append((exc.reason_code, index))
            finally:
                db.close()

        threads = [threading.Thread(target=activate, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual([row[0] for row in results].count("success"), 1)
        self.assertEqual(
            [row[0] for row in results].count("promo_redemption_limit_reached"),
            1,
        )
        db = self.Session()
        try:
            redemptions = db.query(saas.models.PromoRedemption).filter(
                saas.models.PromoRedemption.school_group_id.in_(self.group_ids)
            ).all()
            grants = db.query(saas.models.PromoGrant).filter(
                saas.models.PromoGrant.school_group_id.in_(self.group_ids)
            ).all()
            self.assertEqual(len(redemptions), 1)
            self.assertEqual(len(grants), 1)
            winning_group_id = grants[0].school_group_id
            losing_group_id = next(
                group_id for group_id in self.group_ids
                if group_id != winning_group_id
            )
            self.assertEqual(db.query(saas.models.WorkspaceEntitlement).filter(
                saas.models.WorkspaceEntitlement.school_group_id.in_(self.group_ids),
                saas.models.WorkspaceEntitlement.entitlement_type == "promo",
            ).count(), 1)
            self.assertEqual(db.query(saas.models.TenantProvisioningLink).filter(
                saas.models.TenantProvisioningLink.school_group_id.in_(self.group_ids),
                saas.models.TenantProvisioningLink.promo_grant_id.is_not(None),
            ).count(), 1)
            self.assertEqual(db.query(saas.models.PromoGrantBranchAssignment).filter(
                saas.models.PromoGrantBranchAssignment.school_group_id.in_(self.group_ids)
            ).count(), 1)
            self.assertEqual(db.query(saas.models.BranchEntitlement).filter(
                saas.models.BranchEntitlement.school_group_id == losing_group_id
            ).count(), 0)
            self.assertEqual(
                db.query(saas.models.PromoRedemptionEvent)
                .filter(
                    saas.models.PromoRedemptionEvent.school_group_id.in_(self.group_ids),
                    saas.models.PromoRedemptionEvent.event_type == "activation_completed",
                )
                .count(),
                1,
            )
            states = {
                db.get(models.SchoolGroup, group_id).workspace_lifecycle_status
                for group_id in self.group_ids
            }
            self.assertEqual(states, {"active", "provisioning"})
        finally:
            db.close()

    def test_idempotent_activation_retry_creates_no_duplicates(self):
        db = self.Session()
        try:
            account, group, user, branches = self._create_context(
                db, label="Idempotent Activation", branch_count=2
            )
            created = self._create_promo(db, title="Idempotent activation")
            review, first = self._activate(
                db,
                created=created,
                account=account,
                group=group,
                user=user,
                branches=branches,
                key="idempotent",
            )
            db.commit()
            before = {
                "redemptions": db.query(saas.models.PromoRedemption).filter_by(school_group_id=group.id).count(),
                "grants": db.query(saas.models.PromoGrant).filter_by(school_group_id=group.id).count(),
                "entitlements": db.query(saas.models.WorkspaceEntitlement).filter_by(school_group_id=group.id).count(),
                "assignments": db.query(saas.models.PromoGrantBranchAssignment).filter_by(school_group_id=group.id).count(),
                "branch_entitlements": db.query(saas.models.BranchEntitlement).filter_by(school_group_id=group.id).count(),
                "tenant_links": db.query(saas.models.TenantProvisioningLink).filter_by(school_group_id=group.id).count(),
            }
            with patch("saas.promo_redemption_service.audit.write_audit_event"):
                second = promo_redemption_service.activate_promo(
                    db,
                    activation_uuid=review.session.activation_uuid,
                    account=account,
                    idempotency_key="idempotent:activate",
                )
            db.commit()
            after = {
                "redemptions": db.query(saas.models.PromoRedemption).filter_by(school_group_id=group.id).count(),
                "grants": db.query(saas.models.PromoGrant).filter_by(school_group_id=group.id).count(),
                "entitlements": db.query(saas.models.WorkspaceEntitlement).filter_by(school_group_id=group.id).count(),
                "assignments": db.query(saas.models.PromoGrantBranchAssignment).filter_by(school_group_id=group.id).count(),
                "branch_entitlements": db.query(saas.models.BranchEntitlement).filter_by(school_group_id=group.id).count(),
                "tenant_links": db.query(saas.models.TenantProvisioningLink).filter_by(school_group_id=group.id).count(),
            }
            self.assertEqual(after, before)
            self.assertEqual(second.redemption.id, first.redemption.id)
            self.assertEqual(second.grant.id, first.grant.id)
            self.assertIsNone(second.tenant_link.pending_organization_id)
        finally:
            db.close()

    def test_postgresql_migration_and_tenant_source_constraints(self):
        self.assertIn(
            "20260805_002_promo_redemption_and_grants",
            self.installed_migrations,
        )
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])
        tables = set(inspect(self.engine).get_table_names())
        self.assertTrue({
            "promo_activation_sessions",
            "promo_activation_branch_selections",
            "promo_redemptions",
            "promo_grants",
            "promo_grant_branch_assignments",
            "promo_redemption_events",
        }.issubset(tables))
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text(
                "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = "
                "'20260805_002_promo_redemption_and_grants'"
            )).scalar_one(), 1)
            self.assertTrue(connection.execute(text(
                "SELECT is_nullable = 'YES' FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'tenant_provisioning_links' "
                "AND column_name = 'pending_organization_id'"
            )).scalar_one())

        db = self.Session()
        try:
            _account, group, user, branches = self._create_context(
                db, label="Invalid Tenant Source"
            )
            db.add(saas.models.TenantProvisioningLink(
                school_group_id=group.id,
                owner_operational_user_id=user.id,
                primary_branch_id=branches[0].id,
                tenant_status="tenant_active",
            ))
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()
            self.assertEqual(
                db.query(saas.models.TenantProvisioningLink).filter_by(
                    school_group_id=group.id
                ).count(),
                0,
            )
        finally:
            db.close()
