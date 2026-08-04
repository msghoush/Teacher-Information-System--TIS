import os
import threading
import time
import unittest
import uuid
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

import auth
import db_migrations
import models
import saas.models
from saas import commercial_authority_service, provisioning_service


class CommercialAuthorityServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        models.Base.metadata.create_all(bind=self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=True)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _group(self, *, classification="internal_sandbox", lifecycle="active"):
        group = models.SchoolGroup(
            name=f"Authority {uuid.uuid4().hex[:10]}",
            workspace_classification=classification,
            workspace_lifecycle_status=lifecycle,
        )
        self.db.add(group)
        self.db.flush()
        return group

    def _ensure_plan_catalog(self):
        catalog = {
            "starter": ("Starter", 1, 5, 25),
            "professional": ("Professional", 5, 20, 100),
            "enterprise_ai": ("Enterprise AI", 25, 100, 500),
        }
        for code, (name, branches, staff_users, teachers) in catalog.items():
            if self.db.query(saas.models.SubscriptionPlan).filter_by(
                plan_code=code
            ).first():
                continue
            self.db.add(saas.models.SubscriptionPlan(
                plan_code=code,
                plan_name=name,
                max_branches=branches,
                max_staff_users=staff_users,
                max_system_users=staff_users,
                max_teachers=teachers,
                is_active=True,
                is_public=True,
            ))
        self.db.flush()

    def _paid_workspace(
        self,
        plan_code="professional",
        *,
        quantity=1,
        branches=1,
        with_entitlement=True,
    ):
        self._ensure_plan_catalog()
        group = self._group(classification="customer_paid")
        branch_rows = []
        for index in range(branches):
            branch = models.Branch(
                school_group_id=group.id,
                name=f"Branch {index + 1}",
                status=True,
            )
            self.db.add(branch)
            branch_rows.append(branch)
        account_email = f"{uuid.uuid4().hex}@example.com"
        account = saas.models.SaaSAccount(
            account_uuid=str(uuid.uuid4()),
            email=account_email,
            email_normalized=account_email,
            status="active",
            onboarding_status="tenant_active",
        )
        self.db.add(account)
        self.db.flush()
        organization = saas.models.PendingOrganization(
            organization_uuid=str(uuid.uuid4()),
            owner_saas_account_id=account.id,
            organization_name=group.name,
            status="tenant_active",
            billing_status="tenant_active",
            payment_status="paid",
        )
        self.db.add(organization)
        self.db.flush()
        owner_user = models.User(
            user_id=f"own-{uuid.uuid4().hex[:6]}",
            username=f"owner.{uuid.uuid4().hex[:8]}",
            school_group_id=group.id,
            branch_id=branch_rows[0].id if branch_rows else None,
            user_type=auth.USER_TYPE_TENANT,
            position="Organization Owner",
            is_active=True,
        )
        self.db.add(owner_user)
        self.db.flush()
        plan = self.db.query(saas.models.SubscriptionPlan).filter_by(
            plan_code=plan_code
        ).one()
        contract = saas.models.SubscriptionContract(
            pending_organization_id=organization.id,
            school_group_id=group.id,
            plan_id=plan.id,
            billing_interval="monthly",
            contract_status="tenant_active",
            payment_status="paid",
            paid_at=datetime(2026, 8, 1),
            base_amount_minor=100,
            display_amount_minor=100,
            billable_branch_count=quantity,
        )
        self.db.add(contract)
        self.db.flush()
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
        self.db.add(subscription)
        self.db.flush()
        rows = [
            saas.models.TenantProvisioningLink(
                pending_organization_id=organization.id,
                subscription_contract_id=contract.id,
                school_group_id=group.id,
                owner_operational_user_id=owner_user.id,
                primary_branch_id=branch_rows[0].id if branch_rows else None,
                tenant_status="tenant_active",
            )
        ]
        if with_entitlement:
            rows.append(saas.models.WorkspaceEntitlement(
                school_group_id=group.id,
                entitlement_type="paid",
                status="active",
                source="subscription",
                payment_subscription_id=subscription.id,
            ))
        self.db.add_all(rows)
        self.db.commit()
        return group, branch_rows, subscription

    def test_paid_limits_use_confirmed_quantity_and_plan_ceilings(self):
        cases = (
            ("starter", 3, (1, 5, 25)),
            ("professional", 4, (4, 20, 100)),
            ("enterprise_ai", 20, (20, 100, 500)),
        )
        for plan_code, quantity, expected in cases:
            with self.subTest(plan_code=plan_code):
                group, _branches, _subscription = self._paid_workspace(
                    plan_code, quantity=quantity
                )
                result = commercial_authority_service.resolve_commercial_authority(
                    self.db, group.id
                )
                self.assertTrue(result.resolved)
                self.assertTrue(result.access_allowed)
                self.assertEqual(result.source, "paid_subscription")
                self.assertEqual(
                    (result.limits.branches, result.limits.staff_users, result.limits.teachers),
                    expected,
                )

    def test_paid_provisioning_creates_the_contract_linked_entitlement_authority(self):
        group, _branches, subscription = self._paid_workspace(
            "professional", with_entitlement=False
        )
        contract = self.db.get(
            saas.models.SubscriptionContract,
            subscription.subscription_contract_id,
        )
        entitlement = provisioning_service._ensure_paid_workspace_entitlement(
            self.db,
            contract=contract,
            school_group=group,
        )
        self.db.flush()
        self.assertEqual(entitlement.status, "active")
        self.assertEqual(entitlement.source, "subscription")
        self.assertEqual(entitlement.payment_subscription_id, subscription.id)
        self.assertTrue(
            commercial_authority_service.resolve_commercial_authority(
                self.db, group.id
            ).resolved
        )

    def test_custom_is_derived_when_any_enterprise_ceiling_is_exceeded(self):
        group = self._group()
        self.db.commit()
        result = commercial_authority_service.resolve_commercial_authority(
            self.db,
            group.id,
            usage=commercial_authority_service.CapacityVector(
                branches=26, staff_users=1, teachers=1
            ),
        )
        self.assertTrue(result.resolved)
        self.assertTrue(result.custom_required)
        self.assertEqual(result.minimum_eligible_plan_code, "")

    def test_staff_usage_counts_every_distinct_active_tenant_user_only(self):
        group = self._group()
        other = self._group()
        branch = models.Branch(school_group_id=group.id, name="Main", status=True)
        year = models.AcademicYear(
            school_group_id=group.id, year_name="2026-2027", is_active=True
        )
        self.db.add_all([branch, year])
        self.db.flush()
        self.db.add_all([
            models.User(
                user_id="owner-1", username="owner-1", school_group_id=group.id,
                user_type=auth.USER_TYPE_TENANT, position="Owner", is_active=True,
            ),
            models.User(
                user_id="teacher-user", username="teacher-user", school_group_id=group.id,
                user_type=auth.USER_TYPE_TENANT, position="Teacher", is_active=True,
                is_internal_test_identity=True,
            ),
            models.User(
                user_id="inactive", username="inactive", school_group_id=group.id,
                user_type=auth.USER_TYPE_TENANT, is_active=False,
            ),
            models.User(
                user_id="platform", username="platform", school_group_id=group.id,
                user_type=auth.USER_TYPE_PLATFORM, is_active=True,
            ),
            models.User(
                user_id="other", username="other", school_group_id=other.id,
                user_type=auth.USER_TYPE_TENANT, is_active=True,
            ),
            saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email="account-only@example.com",
                email_normalized="account-only@example.com",
                status="active",
            ),
            models.Teacher(
                teacher_id="teacher-user",
                first_name="Teacher",
                last_name="User",
                branch_id=branch.id,
                academic_year_id=year.id,
            ),
        ])
        self.db.commit()
        self.assertEqual(
            commercial_authority_service.count_active_staff_users(self.db, group.id),
            2,
        )
        self.assertEqual(
            commercial_authority_service.count_active_teachers(self.db, group.id),
            1,
        )

    def test_teacher_usage_deduplicates_known_ids_and_preserves_blank_legacy_rows(self):
        group = self._group()
        active_year = models.AcademicYear(
            school_group_id=group.id, year_name="2026-2027", is_active=True
        )
        inactive_year = models.AcademicYear(
            school_group_id=group.id, year_name="2025-2026", is_active=False
        )
        active_one = models.Branch(school_group_id=group.id, name="One", status=True)
        active_two = models.Branch(school_group_id=group.id, name="Two", status=True)
        inactive_branch = models.Branch(
            school_group_id=group.id, name="Inactive", status=False
        )
        self.db.add_all([active_year, inactive_year, active_one, active_two, inactive_branch])
        self.db.flush()
        self.db.add_all([
            models.Teacher(teacher_id=" T-100 ", first_name="A", last_name="One", branch_id=active_one.id, academic_year_id=active_year.id),
            models.Teacher(teacher_id="t-100", first_name="A", last_name="Two", branch_id=active_two.id, academic_year_id=active_year.id),
            models.Teacher(teacher_id=None, first_name="Blank", last_name="One", branch_id=active_one.id, academic_year_id=active_year.id),
            models.Teacher(teacher_id="", first_name="Blank", last_name="Two", branch_id=active_two.id, academic_year_id=active_year.id),
            models.Teacher(teacher_id="T-200", first_name="Inactive", last_name="Branch", branch_id=inactive_branch.id, academic_year_id=active_year.id),
            models.Teacher(teacher_id="T-300", first_name="Old", last_name="Year", branch_id=active_one.id, academic_year_id=inactive_year.id),
        ])
        self.db.commit()
        self.assertEqual(
            commercial_authority_service.count_active_teachers(self.db, group.id),
            3,
        )

    def test_structured_failure_identifies_dimension_and_safe_recovery(self):
        group, _branches, _subscription = self._paid_workspace("starter")
        decision = commercial_authority_service.evaluate_capacity_change(
            self.db, group.id, proposed_staff_users=6
        )
        self.assertFalse(decision.allowed_action)
        self.assertEqual(decision.code, "capacity_limit_reached")
        self.assertEqual(decision.dimension, "staff_users")
        self.assertEqual(decision.allowed, 5)
        self.assertEqual(decision.current, 1)
        self.assertEqual(decision.proposed_addition, 5)
        self.assertEqual(decision.requested_result, 6)
        self.assertEqual(decision.recovery_action, "upgrade_subscription")
        self.assertNotIn("sub_", decision.message)

    def test_missing_commercial_authority_fails_closed(self):
        group = self._group(classification="customer_paid")
        self.db.commit()
        result = commercial_authority_service.resolve_commercial_authority(
            self.db, group.id
        )
        self.assertFalse(result.resolved)
        self.assertFalse(result.access_allowed)
        with self.assertRaises(commercial_authority_service.CapacityAuthorityError):
            commercial_authority_service.require_capacity_change(
                self.db, group.id, branch_delta=1
            )

    def test_internal_sandbox_is_explicitly_unmetered(self):
        group = self._group()
        self.db.commit()
        result = commercial_authority_service.require_capacity_change(
            self.db,
            group.id,
            proposed_branches=1000,
            proposed_staff_users=1000,
            proposed_teachers=1000,
        )
        self.assertTrue(result.allowed_action)
        self.assertEqual(result.source, "internal_sandbox")
        self.assertTrue(result.authority.limits.unmetered)

    def test_existing_overcapacity_is_preserved_but_cannot_increase(self):
        group, _branches, _subscription = self._paid_workspace(
            "starter", quantity=1, branches=2
        )
        authority = commercial_authority_service.resolve_commercial_authority(
            self.db, group.id
        )
        self.assertTrue(authority.access_allowed)
        self.assertEqual(authority.violations[0].dimension, "branches")
        self.assertTrue(
            commercial_authority_service.evaluate_capacity_change(
                self.db, group.id
            ).allowed_action
        )
        self.assertTrue(
            commercial_authority_service.evaluate_capacity_change(
                self.db, group.id, branch_delta=-1
            ).allowed_action
        )
        self.assertFalse(
            commercial_authority_service.evaluate_capacity_change(
                self.db, group.id, branch_delta=1
            ).allowed_action
        )

    def test_lock_query_is_postgresql_for_update_and_tenant_order_is_stable(self):
        query = self.db.query(models.SchoolGroup).filter(
            models.SchoolGroup.id.in_([2, 1])
        ).order_by(models.SchoolGroup.id.asc()).with_for_update()
        sql = str(query.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ORDER BY school_groups.id ASC", sql)
        self.assertIn("FOR UPDATE", sql)


@unittest.skipUnless(
    os.getenv("TIS_TEST_POSTGRESQL_URL"),
    "TIS_TEST_POSTGRESQL_URL is required for PostgreSQL concurrency tests",
)
class CommercialAuthorityPostgreSQLConcurrencyTests(unittest.TestCase):
    def test_concurrent_final_staff_slot_allows_exactly_one_writer(self):
        database_url = os.environ["TIS_TEST_POSTGRESQL_URL"]
        schema = f"tis_m1_{uuid.uuid4().hex[:12]}"
        admin_engine = create_engine(database_url)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        try:
            models.Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine, autoflush=True)
            db = Session()
            helper = CommercialAuthorityServiceTests()
            helper.db = db
            group, branches, _subscription = helper._paid_workspace(
                "starter", quantity=1, branches=1
            )
            for index in range(3):
                db.add(models.User(
                    user_id=f"seed-{index}",
                    username=f"seed-{index}",
                    school_group_id=group.id,
                    branch_id=branches[0].id,
                    user_type=auth.USER_TYPE_TENANT,
                    is_active=True,
                ))
            db.commit()
            group_id = group.id
            branch_id = branches[0].id
            db.close()

            barrier = threading.Barrier(2)
            results = []
            result_lock = threading.Lock()

            def worker(index):
                session = Session()
                try:
                    barrier.wait()
                    commercial_authority_service.require_capacity_change(
                        session, group_id, staff_user_delta=1
                    )
                    session.add(models.User(
                        user_id=f"conc-{index}",
                        username=f"concurrent-{index}",
                        school_group_id=group_id,
                        branch_id=branch_id,
                        user_type=auth.USER_TYPE_TENANT,
                        is_active=True,
                    ))
                    time.sleep(0.15)
                    session.commit()
                    outcome = ("committed", "", "")
                except commercial_authority_service.CapacityAuthorityError as exc:
                    session.rollback()
                    outcome = (
                        "blocked",
                        exc.decision.code,
                        exc.decision.dimension,
                    )
                finally:
                    session.close()
                with result_lock:
                    results.append(outcome)

            threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(
                sorted(outcome[0] for outcome in results),
                ["blocked", "committed"],
            )
            blocked = next(outcome for outcome in results if outcome[0] == "blocked")
            self.assertEqual(blocked[1:], ("capacity_limit_reached", "staff_users"))
            verify = Session()
            try:
                self.assertEqual(
                    commercial_authority_service.count_active_staff_users(
                        verify, group_id
                    ),
                    5,
                )
                self.assertEqual(
                    verify.query(models.User).filter(
                        models.User.school_group_id == group_id,
                        models.User.user_id.like("conc-%"),
                    ).count(),
                    1,
                )
            finally:
                verify.close()
        finally:
            engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin_engine.dispose()

    def test_concurrent_final_teacher_slot_allows_exactly_one_writer(self):
        database_url = os.environ["TIS_TEST_POSTGRESQL_URL"]
        schema = f"tis_m1_{uuid.uuid4().hex[:12]}"
        admin_engine = create_engine(database_url)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(
            database_url,
            connect_args={"options": f"-csearch_path={schema}"},
        )
        try:
            models.Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine, autoflush=True)
            db = Session()
            helper = CommercialAuthorityServiceTests()
            helper.db = db
            group, branches, _subscription = helper._paid_workspace(
                "starter", quantity=1, branches=1
            )
            year = models.AcademicYear(
                school_group_id=group.id,
                year_name="2026-2027",
                is_active=True,
            )
            db.add(year)
            db.flush()
            for index in range(24):
                db.add(models.Teacher(
                    teacher_id=f"seed-{index}",
                    first_name="Seed",
                    last_name=str(index),
                    branch_id=branches[0].id,
                    academic_year_id=year.id,
                ))
            db.commit()
            group_id = group.id
            branch_id = branches[0].id
            year_id = year.id
            db.close()

            barrier = threading.Barrier(2)
            results = []
            result_lock = threading.Lock()

            def worker(index):
                session = Session()
                try:
                    barrier.wait()
                    commercial_authority_service.require_capacity_change(
                        session, group_id, teacher_delta=1
                    )
                    session.add(models.Teacher(
                        teacher_id=f"final-{index}",
                        first_name="Final",
                        last_name=str(index),
                        branch_id=branch_id,
                        academic_year_id=year_id,
                    ))
                    time.sleep(0.15)
                    session.commit()
                    outcome = ("committed", "", "")
                except commercial_authority_service.CapacityAuthorityError as exc:
                    session.rollback()
                    outcome = (
                        "blocked",
                        exc.decision.code,
                        exc.decision.dimension,
                    )
                finally:
                    session.close()
                with result_lock:
                    results.append(outcome)

            threads = [
                threading.Thread(target=worker, args=(index,))
                for index in range(2)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(
                sorted(outcome[0] for outcome in results),
                ["blocked", "committed"],
            )
            blocked = next(outcome for outcome in results if outcome[0] == "blocked")
            self.assertEqual(blocked[1:], ("capacity_limit_reached", "teachers"))
            verify = Session()
            try:
                self.assertEqual(
                    commercial_authority_service.count_active_teachers(
                        verify, group_id
                    ),
                    25,
                )
                self.assertEqual(
                    verify.query(models.Teacher).filter(
                        models.Teacher.branch_id == branch_id,
                        models.Teacher.teacher_id.like("final-%"),
                    ).count(),
                    1,
                )
            finally:
                verify.close()
        finally:
            engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin_engine.dispose()


if __name__ == "__main__":
    unittest.main()
