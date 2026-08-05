import json
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
import permission_registry
import saas.models
from dependencies import get_db
from saas import commercial_authority_service, promo_code_service
from saas.router import admin_router


TEST_PROMO_SECRET = "promo-unit-test-secret-with-more-than-thirty-two-bytes"


class PromoCodeManagementTests(unittest.TestCase):
    def setUp(self):
        self.old_secret = os.environ.get("TIS_PROMO_CODE_HMAC_SECRET")
        self.old_session_secret = os.environ.get("TIS_SESSION_SECRET")
        os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = TEST_PROMO_SECRET
        os.environ["TIS_SESSION_SECRET"] = "promo-test-session-secret-with-more-than-thirty-two-bytes"
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        models.Base.metadata.create_all(self.engine)
        db_migrations.run_pending_migrations(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.app = FastAPI()
        self.app.mount("/static", StaticFiles(directory="static"), name="static")
        self.app.include_router(admin_router)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)
        self.extra_clients = []
        self._seed()

    def tearDown(self):
        for client in self.extra_clients:
            client.close()
        self.client.close()
        self.engine.dispose()
        if self.old_secret is None:
            os.environ.pop("TIS_PROMO_CODE_HMAC_SECRET", None)
        else:
            os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = self.old_secret
        if self.old_session_secret is None:
            os.environ.pop("TIS_SESSION_SECRET", None)
        else:
            os.environ["TIS_SESSION_SECRET"] = self.old_session_secret

    def _db(self):
        return self.Session()

    def _seed(self):
        db = self._db()
        try:
            plans = (
                ("starter", "Starter", 1, 5, 25),
                ("professional", "Professional", 5, 20, 100),
                ("enterprise_ai", "Enterprise AI", 25, 100, 500),
            )
            for order, (code, name, branches, users, teachers) in enumerate(plans, 1):
                plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code=code).one_or_none()
                if plan is None:
                    plan = saas.models.SubscriptionPlan(plan_code=code, plan_name=name)
                    db.add(plan)
                plan.plan_name = name
                plan.is_active = True
                plan.is_public = True
                plan.sort_order = order
                plan.max_branches = branches
                plan.max_system_users = users
                plan.max_staff_users = users
                plan.max_teachers = teachers
            group = models.SchoolGroup(name="Promo Test Academy")
            db.add(group)
            db.flush()
            db.add_all([
                models.Branch(school_group_id=group.id, name="Main Campus", status=True),
                models.Branch(school_group_id=group.id, name="North Campus", status=True),
            ])
            account = saas.models.SaaSAccount(
                account_uuid=str(uuid.uuid4()),
                email="promo.pending@example.edu",
                email_normalized="promo.pending@example.edu",
                status="active",
                onboarding_status="organization_in_progress",
            )
            db.add(account)
            db.flush()
            pending = saas.models.PendingOrganization(
                organization_uuid=str(uuid.uuid4()),
                owner_saas_account_id=account.id,
                organization_name="Pending Promo Academy",
                status="draft",
            )
            db.add(pending)
            db.commit()
            self.group_id = group.id
            self.pending_id = pending.id
            self.plan_ids = {
                row.plan_code: row.id
                for row in db.query(saas.models.SubscriptionPlan).filter(
                    saas.models.SubscriptionPlan.plan_code.in_(("starter", "professional", "enterprise_ai"))
                ).all()
            }
        finally:
            db.close()

    def _platform_client(self, *, role=auth.PLATFORM_ROLE_OWNER, permissions=()):
        db = self._db()
        try:
            identifier = str(uuid.uuid4())[:8]
            user = models.User(
                user_id=identifier[:8],
                username=f"promo.{identifier}",
                email=f"promo.{identifier}@example.com",
                email_normalized=f"promo.{identifier}@example.com",
                password=auth.get_password_hash("PlatformPass123!"),
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=role,
                platform_owner_kind=(auth.PLATFORM_OWNER_PRIMARY if role == auth.PLATFORM_ROLE_OWNER else None),
                platform_permissions_initialized=(role == auth.PLATFORM_ROLE_DEVELOPER),
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(user)
            db.flush()
            for key in permissions:
                db.add(models.PlatformUserPermission(
                    platform_user_id=user.id,
                    permission_key=key,
                    is_allowed=True,
                ))
            db.commit()
            token = auth.create_session_token(user)
            user_id = user.id
        finally:
            db.close()
        client = TestClient(self.app)
        client.cookies.set(auth.SESSION_COOKIE_KEY, token)
        self.extra_clients.append(client)
        return client, user_id

    def _plan_id(self, code):
        return self.plan_ids[code]

    def _values(self, plan_code="starter", **overrides):
        now = datetime.now(timezone.utc)
        ceilings = {
            "starter": (1, 5, 25),
            "professional": (5, 20, 100),
            "enterprise_ai": (25, 100, 500),
        }
        branches, users, teachers = ceilings[plan_code]
        values = {
            "title": f"{plan_code.replace('_', ' ').title()} launch",
            "internal_purpose": "Approved promo definition test",
            "subscription_plan_id": self._plan_id(plan_code),
            "max_branches": branches,
            "max_system_users": users,
            "max_teachers": teachers,
            "scope_type": "global",
            "school_group_id": None,
            "pending_organization_id": None,
            "intended_account_email_normalized": None,
            "permitted_email_domain_normalized": None,
            "branch_ids": (),
            "transferable": False,
            "one_redemption_per_organization": True,
            "max_total_redemptions": 1,
            "valid_from": now,
            "redemption_deadline": now + timedelta(days=30),
            "fixed_access_expires_at": None,
            "access_duration_days": 90,
            "grace_period_days": 0,
        }
        values.update(overrides)
        return values

    def _create(self, plan_code="starter", actor=None, **overrides):
        db = self._db()
        try:
            if actor is None:
                actor = models.User(
                    user_id=str(uuid.uuid4())[:8], username=f"owner.{uuid.uuid4().hex[:8]}",
                    email=f"owner.{uuid.uuid4().hex[:8]}@example.com",
                    email_normalized=f"owner.{uuid.uuid4().hex[:8]}@example.com",
                    user_type=auth.USER_TYPE_PLATFORM, platform_role=auth.PLATFORM_ROLE_OWNER,
                    access_scope=auth.ACCESS_SCOPE_GLOBAL, is_active=True,
                )
                db.add(actor)
                db.flush()
            with patch("saas.promo_code_service.audit.write_audit_event"):
                created = promo_code_service.create_promo(
                    db, actor=actor, values=self._values(plan_code, **overrides)
                )
            db.commit()
            return created.promo.promo_uuid, created.raw_code, actor.id
        finally:
            db.close()

    def test_valid_starter_professional_and_enterprise_definitions(self):
        for code in ("starter", "professional", "enterprise_ai"):
            promo_uuid, raw, _ = self._create(code)
            self.assertTrue(raw.startswith("TIS-"))
            db = self._db()
            try:
                promo = db.query(saas.models.PromoCode).filter_by(promo_uuid=promo_uuid).one()
                self.assertEqual(promo.status, "draft")
                self.assertEqual(promo.benefit_type, "full_access")
            finally:
                db.close()

    def test_each_capacity_dimension_rejects_above_plan_ceiling(self):
        for field, value in (("max_branches", 2), ("max_system_users", 6), ("max_teachers", 26)):
            db = self._db()
            try:
                with self.assertRaisesRegex(promo_code_service.PromoCodeError, "supports up to"):
                    promo_code_service.create_promo(
                        db, actor=None, values=self._values("starter", **{field: value})
                    )
            finally:
                db.rollback()
                db.close()

    def test_date_order_expiry_xor_and_positive_redemption_rules(self):
        now = datetime.now(timezone.utc)
        invalid = (
            {"valid_from": now + timedelta(days=2), "redemption_deadline": now + timedelta(days=1)},
            {"fixed_access_expires_at": now + timedelta(days=90), "access_duration_days": 90},
            {"fixed_access_expires_at": None, "access_duration_days": None},
            {"max_total_redemptions": 0},
            {"grace_period_days": -1},
        )
        for override in invalid:
            db = self._db()
            try:
                with self.assertRaises(promo_code_service.PromoCodeError):
                    promo_code_service.create_promo(db, actor=None, values=self._values(**override))
            finally:
                db.rollback()
                db.close()

    def test_generated_codes_are_unique_and_normalized_hash_is_case_separator_insensitive(self):
        first_uuid, first_code, _ = self._create()
        second_uuid, second_code, _ = self._create()
        self.assertNotEqual(first_uuid, second_uuid)
        self.assertNotEqual(first_code, second_code)
        digest, key_id = promo_code_service.promo_lookup_hash(first_code)
        alternate = first_code.lower().replace("-", " ")
        self.assertEqual((digest, key_id), promo_code_service.promo_lookup_hash(alternate))

    def test_raw_code_is_absent_from_persisted_data_and_audit_payloads(self):
        promo_uuid, raw_code, _ = self._create()
        db = self._db()
        try:
            promo = db.query(saas.models.PromoCode).filter_by(promo_uuid=promo_uuid).one()
            event = db.query(saas.models.PromoCodeAuditEvent).filter_by(promo_code_id=promo.id).one()
            persisted = "|".join(str(value) for value in promo.__dict__.values())
            audit_payload = event.previous_values_json + event.new_values_json
            self.assertNotIn(raw_code, persisted)
            self.assertNotIn(raw_code, audit_payload)
            self.assertNotIn(promo.code_lookup_hash, audit_payload)
            self.assertNotIn(promo.code_hash_key_id, audit_payload)
        finally:
            db.close()

    def test_raw_code_is_absent_from_application_audit_log_event(self):
        db = self._db()
        try:
            actor = models.User(
                user_id="audit001", username="promo.audit.owner",
                email="promo.audit.owner@example.com",
                email_normalized="promo.audit.owner@example.com",
                user_type=auth.USER_TYPE_PLATFORM,
                platform_role=auth.PLATFORM_ROLE_OWNER,
                access_scope=auth.ACCESS_SCOPE_GLOBAL,
                is_active=True,
            )
            db.add(actor)
            db.flush()
            with patch("saas.promo_code_service.audit.write_audit_event") as write_audit:
                created = promo_code_service.create_promo(
                    db, actor=actor, values=self._values()
                )
            logged = json.dumps(write_audit.call_args.args[0], sort_keys=True)
            self.assertNotIn(created.raw_code, logged)
            self.assertNotIn(created.promo.code_lookup_hash, logged)
            self.assertNotIn(created.promo.code_hash_key_id, logged)
        finally:
            db.rollback()
            db.close()

    def test_missing_hmac_secret_fails_closed_without_disabling_runtime_reads(self):
        promo_uuid, _raw, _ = self._create()
        with patch.dict(os.environ, {"TIS_PROMO_CODE_HMAC_SECRET": ""}):
            with self.assertRaisesRegex(promo_code_service.PromoCodeError, "configuration"):
                promo_code_service.promo_lookup_hash("TIS-AAAAA-BBBBB-CCCCC-DDDDD")
            db = self._db()
            try:
                self.assertIsNotNone(promo_code_service.get_promo(db, promo_uuid))
            finally:
                db.close()

    def test_global_and_targeted_scope_rules_with_reinforcing_email(self):
        self._create(scope_type="global")
        self._create(
            scope_type="organization",
            school_group_id=self.group_id,
            intended_account_email_normalized="OWNER@EXAMPLE.EDU",
            permitted_email_domain_normalized="example.edu",
        )
        self._create(scope_type="pending_organization", pending_organization_id=self.pending_id)
        self._create(scope_type="account_email", intended_account_email_normalized="person@example.edu")
        self._create(scope_type="email_domain", permitted_email_domain_normalized="example.edu")
        db = self._db()
        try:
            with self.assertRaises(promo_code_service.PromoCodeError):
                promo_code_service.create_promo(
                    db, actor=None,
                    values=self._values(scope_type="global", school_group_id=self.group_id),
                )
            with self.assertRaises(promo_code_service.PromoCodeError):
                promo_code_service.create_promo(
                    db, actor=None,
                    values=self._values(
                        scope_type="account_email",
                        intended_account_email_normalized="person@first.edu",
                        permitted_email_domain_normalized="second.edu",
                    ),
                )
        finally:
            db.rollback()
            db.close()

    def test_branch_restrictions_are_definition_only_and_tenant_scoped(self):
        db = self._db()
        try:
            branch_ids = tuple(row.id for row in db.query(models.Branch).filter_by(school_group_id=self.group_id))
            entitlement_count = db.query(saas.models.WorkspaceEntitlement).count()
        finally:
            db.close()
        promo_uuid, _raw, _ = self._create(
            scope_type="organization", school_group_id=self.group_id, branch_ids=branch_ids
        )
        db = self._db()
        try:
            promo = promo_code_service.get_promo(db, promo_uuid)
            self.assertEqual(len(promo_code_service.list_branch_restrictions(db, promo.id)), 2)
            self.assertEqual(db.query(saas.models.WorkspaceEntitlement).count(), entitlement_count)
        finally:
            db.close()

    def test_activation_pause_edit_approval_reset_and_terminal_revocation(self):
        promo_uuid, _raw, actor_id = self._create()
        db = self._db()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            with patch("saas.promo_code_service.audit.write_audit_event"):
                promo = promo_code_service.activate_promo(db, promo_uuid=promo_uuid, actor=actor)
                self.assertEqual(promo.approved_by_user_id, actor.id)
                with self.assertRaises(promo_code_service.PromoCodeError):
                    promo_code_service.update_promo(db, promo_uuid=promo_uuid, actor=actor, values=self._values())
                promo_code_service.pause_promo(db, promo_uuid=promo_uuid, actor=actor)
                promo = promo_code_service.update_promo(
                    db, promo_uuid=promo_uuid, actor=actor,
                    values=self._values(title="Edited definition"),
                )
                self.assertEqual((promo.status, promo.definition_version, promo.approved_at), ("draft", 2, None))
                with self.assertRaises(promo_code_service.PromoCodeError):
                    promo_code_service.revoke_promo(db, promo_uuid=promo_uuid, actor=actor, reason="")
                promo_code_service.revoke_promo(db, promo_uuid=promo_uuid, actor=actor, reason="Retired test")
                with self.assertRaises(promo_code_service.PromoCodeError):
                    promo_code_service.update_promo(db, promo_uuid=promo_uuid, actor=actor, values=self._values())
            db.commit()
        finally:
            db.close()

    def test_derived_expiration_is_not_persisted(self):
        now = datetime.now(timezone.utc)
        promo_uuid, _raw, _ = self._create(
            valid_from=now - timedelta(days=3),
            redemption_deadline=now - timedelta(days=1),
            fixed_access_expires_at=now + timedelta(days=10),
            access_duration_days=None,
        )
        db = self._db()
        try:
            promo = promo_code_service.get_promo(db, promo_uuid)
            self.assertEqual(promo.status, "draft")
            self.assertEqual(promo_code_service.effective_status(promo), "expired")
        finally:
            db.close()

    def test_missing_required_scope_target_preserves_history_but_blocks_activation(self):
        promo_uuid, _raw, actor_id = self._create(
            scope_type="organization", school_group_id=self.group_id
        )
        db = self._db()
        try:
            promo = promo_code_service.get_promo(db, promo_uuid)
            actor = db.query(models.User).filter_by(id=actor_id).one()
            self.assertIn("Promo Test Academy", promo.scope_target_snapshot)
            promo.school_group_id = None
            db.flush()
            with self.assertRaisesRegex(promo_code_service.PromoCodeError, "requires a target"):
                promo_code_service.activate_promo(db, promo_uuid=promo_uuid, actor=actor)
        finally:
            db.rollback()
            db.close()

    def test_duplicate_and_replacement_generate_new_drafts_and_prevent_second_replacement(self):
        promo_uuid, raw, actor_id = self._create()
        db = self._db()
        try:
            actor = db.query(models.User).filter_by(id=actor_id).one()
            with patch("saas.promo_code_service.audit.write_audit_event"):
                duplicate = promo_code_service.duplicate_promo(db, promo_uuid=promo_uuid, actor=actor)
                replacement = promo_code_service.replace_promo(db, promo_uuid=promo_uuid, actor=actor)
                self.assertNotEqual(raw, duplicate.raw_code)
                self.assertEqual(duplicate.promo.status, "draft")
                self.assertEqual(replacement.promo.supersedes_promo_code_id, promo_code_service.get_promo(db, promo_uuid).id)
                with self.assertRaises(promo_code_service.PromoCodeError):
                    promo_code_service.replace_promo(db, promo_uuid=promo_uuid, actor=actor)
            db.commit()
        finally:
            db.close()

    def test_platform_owner_one_time_display_and_no_store(self):
        client, _ = self._platform_client()
        now = datetime.now(timezone.utc)
        response = client.post("/saas-admin/promo-codes/create", data={
            "operation_key": str(uuid.uuid4()), "title": "Console Starter", "internal_purpose": "Console test",
            "subscription_plan_id": str(self._plan_id("starter")), "max_branches": "1",
            "max_system_users": "5", "max_teachers": "25", "scope_type": "global",
            "valid_from": now.strftime("%Y-%m-%dT%H:%M"),
            "redemption_deadline": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M"),
            "access_duration_days": "60", "grace_period_days": "0", "max_total_redemptions": "1",
            "one_redemption_per_organization": "1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        self.assertIn("One-time secure display", response.text)
        db = self._db()
        try:
            promo = db.query(saas.models.PromoCode).order_by(saas.models.PromoCode.id.desc()).first()
            raw_code = response.text.split('<code id="promo-raw-code">', 1)[1].split("</code>", 1)[0]
            detail = client.get(f"/saas-admin/promo-codes/{promo.promo_uuid}")
            self.assertNotIn(raw_code, detail.text)
            self.assertIn(promo_code_service.masked_code(promo), detail.text)
        finally:
            db.close()

    def test_developer_permissions_allow_definition_management_but_not_activation_or_revocation(self):
        promo_uuid, _raw, _ = self._create()
        developer, _ = self._platform_client(
            role=auth.PLATFORM_ROLE_DEVELOPER,
            permissions=("promo_codes.view", "promo_codes.manage"),
        )
        self.assertEqual(developer.get("/saas-admin/promo-codes").status_code, 200)
        activation = developer.post(f"/saas-admin/promo-codes/{promo_uuid}/activate", follow_redirects=False)
        self.assertIn("Platform+Owner+approval", activation.headers["location"])
        revocation = developer.post(
            f"/saas-admin/promo-codes/{promo_uuid}/revoke",
            data={"reason": "Developer attempt"}, follow_redirects=False,
        )
        self.assertIn("Platform+Owner+approval", revocation.headers["location"])

    def test_tenant_and_unassigned_developer_are_denied(self):
        tenant_client, _ = self._platform_client(role=auth.PLATFORM_ROLE_DEVELOPER, permissions=())
        self.assertEqual(tenant_client.get("/saas-admin/promo-codes").status_code, 403)
        db = self._db()
        try:
            tenant = models.User(
                user_id="tenant01", username="tenant.promo", email="tenant.promo@example.edu",
                email_normalized="tenant.promo@example.edu", user_type=auth.USER_TYPE_TENANT,
                role=auth.ROLE_ADMINISTRATOR, access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
                school_group_id=self.group_id, is_active=True,
            )
            db.add(tenant)
            db.commit()
            token = auth.create_session_token(tenant)
        finally:
            db.close()
        client = TestClient(self.app)
        client.cookies.set(auth.SESSION_COOKIE_KEY, token)
        self.extra_clients.append(client)
        self.assertEqual(client.get("/saas-admin/promo-codes").status_code, 403)

    def test_permission_registry_exposes_granular_platform_permissions(self):
        self.assertIn("promo_codes.view", permission_registry.DEVELOPER_ASSIGNABLE_PERMISSION_KEYS)
        self.assertIn("promo_codes.manage", permission_registry.DEVELOPER_ASSIGNABLE_PERMISSION_KEYS)
        platform_group = next(group for group in permission_registry.PERMISSION_GROUPS if group["key"] == "platform")
        self.assertIn(("promo_codes.view", "View promo code definitions"), platform_group["permissions"])

    def test_audit_serializer_is_allowlisted_and_redacted(self):
        promo_uuid, raw, _ = self._create()
        db = self._db()
        try:
            promo = promo_code_service.get_promo(db, promo_uuid)
            event = promo_code_service.list_audit_events(db, promo.id)[0]
            values = json.loads(event.new_values_json)
            self.assertEqual(values["masked_code"], promo_code_service.masked_code(promo))
            self.assertNotIn("code_lookup_hash", values)
            self.assertNotIn("code_hash_key_id", values)
            self.assertNotIn(raw, event.new_values_json)
        finally:
            db.close()

    def test_sqlite_migration_is_additive_idempotent_and_constrained(self):
        inspector = inspect(self.engine)
        self.assertTrue({"promo_codes", "promo_code_branch_restrictions", "promo_code_audit_events"}.issubset(inspector.get_table_names()))
        self.assertIn("20260805_001_promo_code_foundation", {
            row[0] for row in self.engine.connect().execute(text("SELECT migration_id FROM schema_migrations"))
        })
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])
        db = self._db()
        try:
            invalid = saas.models.PromoCode(
                promo_uuid=str(uuid.uuid4()), code_lookup_hash="a" * 64, code_hash_key_id="v1",
                code_display_prefix="TIS-AAAAA", code_display_suffix="BBBBB", title="Invalid",
                status="draft", subscription_plan_id=self._plan_id("starter"), max_branches=0,
                max_system_users=1, max_teachers=1, scope_type="global", max_total_redemptions=1,
                valid_from=datetime.now(timezone.utc), redemption_deadline=datetime.now(timezone.utc) + timedelta(days=1),
                access_duration_days=1, grace_period_days=0,
            )
            db.add(invalid)
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.rollback()
            db.close()

    def test_sqlite_migration_creates_only_promo_tables_and_preserves_existing_rows(self):
        engine = create_engine("sqlite:///:memory:")
        promo_names = {
            "promo_codes",
            "promo_code_branch_restrictions",
            "promo_code_audit_events",
        }
        base_tables = [
            table for table in models.Base.metadata.tables.values()
            if table.name not in promo_names
        ]
        models.Base.metadata.create_all(engine, tables=base_tables)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO school_groups "
                "(id, name, workspace_uuid, workspace_classification, workspace_lifecycle_status, status, created_at, updated_at) "
                "VALUES (991, 'Migration Preserve', '00000000-0000-0000-0000-000000000991', "
                "'internal_sandbox', 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            db_migrations._promo_code_foundation(engine, connection)
            db_migrations._promo_code_foundation(engine, connection)
        inspector = inspect(engine)
        self.assertTrue(promo_names.issubset(inspector.get_table_names()))
        with engine.connect() as connection:
            self.assertEqual(
                connection.execute(text("SELECT name FROM school_groups WHERE id = 991")).scalar_one(),
                "Migration Preserve",
            )
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM promo_codes")).scalar_one(), 0)
        engine.dispose()

    def test_m1_authority_and_paddle_onboarding_boundaries_remain_unchanged(self):
        source = open("saas/commercial_authority_service.py", encoding="utf-8").read()
        self.assertIn('PROMO_GRANT = "promo_grant"', source)
        self.assertIn("resolve_promo_grant", source)
        self.assertIn("grant_uuid", promo_code_service.PROMO_GRANT_ADAPTER_FIELDS)
        self.assertNotIn("paddle", open("saas/promo_code_service.py", encoding="utf-8").read().casefold())


@unittest.skipUnless(os.getenv("TIS_TEST_POSTGRESQL_URL"), "Disposable PostgreSQL URL not configured")
class PromoCodePostgreSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ["TIS_TEST_POSTGRESQL_URL"])
        with cls.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        models.Base.metadata.create_all(cls.engine)
        db_migrations.run_pending_migrations(cls.engine)
        with cls.engine.begin() as connection:
            connection.execute(text("DROP TABLE promo_code_audit_events CASCADE"))
            connection.execute(text("DROP TABLE promo_code_branch_restrictions CASCADE"))
            connection.execute(text("DROP TABLE promo_codes CASCADE"))
            connection.execute(text(
                "DELETE FROM schema_migrations WHERE migration_id = "
                "'20260805_001_promo_code_foundation'"
            ))
        db_migrations.run_pending_migrations(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        os.environ["TIS_PROMO_CODE_HMAC_SECRET"] = TEST_PROMO_SECRET
        db = cls.Session()
        plan = db.query(saas.models.SubscriptionPlan).filter_by(plan_code="starter").one_or_none()
        if plan is None:
            plan = saas.models.SubscriptionPlan(plan_code="starter", plan_name="Starter")
            db.add(plan)
        plan.plan_name = "Starter"
        plan.is_active = True
        plan.is_public = True
        plan.max_branches = 1
        plan.max_system_users = 5
        plan.max_staff_users = 5
        plan.max_teachers = 25
        owner = models.User(
            user_id="pgowner1", username="pg.promo.owner", email="pg.promo.owner@example.com",
            email_normalized="pg.promo.owner@example.com", user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER, access_scope=auth.ACCESS_SCOPE_GLOBAL, is_active=True,
        )
        db.add(owner)
        db.commit()
        cls.plan_id, cls.owner_id = plan.id, owner.id
        db.close()

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        cls.engine.dispose()

    def _values(self):
        now = datetime.now(timezone.utc)
        return {
            "title": "Concurrent activation", "subscription_plan_id": self.plan_id,
            "max_branches": 1, "max_system_users": 5, "max_teachers": 25,
            "scope_type": "global", "max_total_redemptions": 1,
            "valid_from": now, "redemption_deadline": now + timedelta(days=5),
            "access_duration_days": 30, "grace_period_days": 0,
        }

    def test_postgresql_migration_and_concurrent_lifecycle_transition(self):
        inspector = inspect(self.engine)
        self.assertTrue({
            "promo_codes", "promo_code_branch_restrictions", "promo_code_audit_events"
        }.issubset(inspector.get_table_names()))
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(text(
                    "SELECT COUNT(*) FROM schema_migrations "
                    "WHERE migration_id = '20260805_001_promo_code_foundation'"
                )).scalar_one(),
                1,
            )
        self.assertEqual(db_migrations.run_pending_migrations(self.engine), [])
        db = self.Session()
        owner = db.query(models.User).filter_by(id=self.owner_id).one()
        with patch("saas.promo_code_service.audit.write_audit_event"):
            created = promo_code_service.create_promo(db, actor=owner, values=self._values())
        db.commit()
        promo_uuid = created.promo.promo_uuid
        db.close()
        barrier = threading.Barrier(2)
        results = []

        def activate():
            session = self.Session()
            try:
                actor = session.query(models.User).filter_by(id=self.owner_id).one()
                barrier.wait()
                with patch("saas.promo_code_service.audit.write_audit_event"):
                    promo_code_service.activate_promo(
                        session, promo_uuid=promo_uuid, actor=actor,
                        operation_key=str(uuid.uuid4()),
                    )
                session.commit()
                results.append("success")
            except promo_code_service.PromoCodeError:
                session.rollback()
                results.append("blocked")
            finally:
                session.close()

        threads = [threading.Thread(target=activate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertCountEqual(results, ["success", "blocked"])
        db = self.Session()
        self.assertEqual(promo_code_service.get_promo(db, promo_uuid).status, "active")
        db.close()

    def test_postgresql_concurrent_secure_generation_remains_unique(self):
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def generate():
            session = self.Session()
            try:
                actor = session.query(models.User).filter_by(id=self.owner_id).one()
                barrier.wait()
                with patch("saas.promo_code_service.audit.write_audit_event"):
                    created = promo_code_service.create_promo(
                        session, actor=actor, values=self._values(),
                        operation_key=str(uuid.uuid4()),
                    )
                session.commit()
                results.append((created.promo.promo_uuid, created.raw_code))
            except Exception as exc:
                session.rollback()
                errors.append(exc)
            finally:
                session.close()

        threads = [threading.Thread(target=generate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len({value[0] for value in results}), 2)
        self.assertEqual(len({value[1] for value in results}), 2)
        db = self.Session()
        try:
            hashes = [
                row[0] for row in db.query(saas.models.PromoCode.code_lookup_hash).all()
            ]
            self.assertEqual(len(hashes), len(set(hashes)))
        finally:
            db.close()

    def test_postgresql_replacement_predecessor_is_unique_under_concurrency(self):
        db = self.Session()
        try:
            owner = db.query(models.User).filter_by(id=self.owner_id).one()
            with patch("saas.promo_code_service.audit.write_audit_event"):
                source = promo_code_service.create_promo(
                    db, actor=owner, values=self._values(),
                    operation_key=str(uuid.uuid4()),
                )
            db.commit()
            source_uuid = source.promo.promo_uuid
        finally:
            db.close()
        barrier = threading.Barrier(2)
        results = []

        def replace():
            session = self.Session()
            try:
                actor = session.query(models.User).filter_by(id=self.owner_id).one()
                barrier.wait()
                with patch("saas.promo_code_service.audit.write_audit_event"):
                    created = promo_code_service.replace_promo(
                        session, promo_uuid=source_uuid, actor=actor,
                        operation_key=str(uuid.uuid4()),
                    )
                session.commit()
                results.append(("success", created.promo.promo_uuid))
            except promo_code_service.PromoCodeError as exc:
                session.rollback()
                results.append(("blocked", exc.reason_code))
            finally:
                session.close()

        threads = [threading.Thread(target=replace) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual([row[0] for row in results].count("success"), 1)
        self.assertEqual([row[0] for row in results].count("blocked"), 1)
        db = self.Session()
        try:
            source = promo_code_service.get_promo(db, source_uuid)
            self.assertEqual(
                db.query(saas.models.PromoCode).filter_by(
                    supersedes_promo_code_id=source.id
                ).count(),
                1,
            )
        finally:
            db.close()

    def test_postgresql_audit_and_promo_state_roll_back_atomically(self):
        db = self.Session()
        try:
            owner = db.query(models.User).filter_by(id=self.owner_id).one()
            promo_count = db.query(saas.models.PromoCode).count()
            audit_count = db.query(saas.models.PromoCodeAuditEvent).count()
            with (
                patch(
                    "saas.promo_code_service.audit.write_audit_event",
                    side_effect=RuntimeError("simulated audit channel failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "simulated audit channel failure"),
            ):
                promo_code_service.create_promo(
                    db, actor=owner, values=self._values(),
                    operation_key=str(uuid.uuid4()),
                )
            db.rollback()
            self.assertEqual(db.query(saas.models.PromoCode).count(), promo_count)
            self.assertEqual(db.query(saas.models.PromoCodeAuditEvent).count(), audit_count)

            with patch("saas.promo_code_service.audit.write_audit_event"):
                created = promo_code_service.create_promo(
                    db, actor=owner, values=self._values(),
                    operation_key=str(uuid.uuid4()),
                )
            db.commit()
            promo_uuid = created.promo.promo_uuid
            audit_count = db.query(saas.models.PromoCodeAuditEvent).filter_by(
                promo_code_id=created.promo.id
            ).count()
            with (
                patch(
                    "saas.promo_code_service.audit.write_audit_event",
                    side_effect=RuntimeError("simulated lifecycle audit failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "simulated lifecycle audit failure"),
            ):
                promo_code_service.activate_promo(
                    db, promo_uuid=promo_uuid, actor=owner,
                    operation_key=str(uuid.uuid4()),
                )
            db.rollback()
            persisted = promo_code_service.get_promo(db, promo_uuid)
            self.assertEqual(persisted.status, "draft")
            self.assertIsNone(persisted.approved_at)
            self.assertEqual(
                db.query(saas.models.PromoCodeAuditEvent).filter_by(
                    promo_code_id=persisted.id
                ).count(),
                audit_count,
            )
        finally:
            db.rollback()
            db.close()


if __name__ == "__main__":
    unittest.main()
