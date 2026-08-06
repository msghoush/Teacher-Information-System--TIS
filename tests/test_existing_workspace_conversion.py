import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import db_migrations
import models
import saas.models
from saas import (
    commercial_authority_service,
    customer_journey_service,
    existing_workspace_conversion_service as conversion,
)
from saas.existing_workspace_conversion_audit_service import audit_existing_workspace_conversion


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _workspace(db, *, name="Existing Customer Workspace"):
    group = models.SchoolGroup(
        name=name,
        workspace_uuid=str(uuid.uuid4()),
        workspace_classification="internal_sandbox",
        workspace_lifecycle_status="active",
        country_code="SA",
        country_name="Saudi Arabia",
    )
    db.add(group)
    db.flush()
    branches = []
    for index in range(1, 21):
        branch = models.Branch(
            school_group_id=group.id,
            name=f"Campus {index}",
            status=index <= 5,
        )
        db.add(branch)
        branches.append(branch)
    db.flush()
    year = models.AcademicYear(
        school_group_id=group.id,
        year_name="2026-2027",
        is_active=True,
    )
    db.add(year)
    db.flush()
    for index, branch in enumerate(branches[:5], 1):
        db.add(models.Teacher(
            teacher_id=f"T{index:04d}",
            first_name="Existing",
            last_name=f"Teacher {index}",
            branch_id=branch.id,
            academic_year_id=year.id,
        ))
    entitlement = saas.models.WorkspaceEntitlement(
        entitlement_uuid=str(uuid.uuid4()),
        school_group_id=group.id,
        entitlement_type="internal_sandbox",
        status="active",
        source="system",
    )
    db.add(entitlement)
    db.commit()
    return group, branches, entitlement


def _account(db, email="owner@example.edu", *, verified=True, active=True):
    row = saas.models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email=email,
        email_normalized=email.lower(),
        password_hash="verified-password-hash",
        first_name="Workspace",
        last_name="Owner",
        status="active" if active else "disabled",
        onboarding_status="not_started",
        account_purpose="internal_test",
        email_verified_at=datetime.utcnow() if verified else None,
    )
    db.add(row)
    db.commit()
    return row


def _report(db, group, email="owner@example.edu"):
    return audit_existing_workspace_conversion(
        db,
        school_group_id=group.id,
        workspace_uuid=group.workspace_uuid,
        expected_name=group.name,
        owner_email=email,
    )


def _operation(db, group, account, report, *, status="awaiting_owner_alignment"):
    operation = saas.models.ExistingWorkspaceConversionOperation(
        operation_uuid=str(uuid.uuid4()),
        school_group_id=group.id,
        workspace_uuid_snapshot=group.workspace_uuid,
        expected_organization_name_snapshot=group.name,
        intended_owner_email_normalized=account.email_normalized,
        audit_snapshot_hash=report["snapshot_hash"],
        canonical_parameter_hash="a" * 64,
        stage="owner_alignment" if status == "awaiting_owner_alignment" else "setup_review",
        status=status,
        dry_run=False,
        idempotency_key=f"operation-{uuid.uuid4()}",
        current_classification_snapshot=group.workspace_classification,
        current_lifecycle_snapshot=group.workspace_lifecycle_status,
        current_entitlement_snapshot_json=json.dumps(
            report["commercial_state"]["workspace_entitlements"],
            sort_keys=True,
            separators=(",", ":"),
        ),
        branch_snapshot_json=json.dumps(
            conversion._branch_snapshot(report), sort_keys=True, separators=(",", ":")
        ),
        missing_field_snapshot_json=json.dumps(
            report["setup_field_resolution"]["missing_required_fields"]
        ),
    )
    db.add(operation)
    db.commit()
    return operation


def test_production_shaped_inventory_is_read_only_and_snapshot_mismatch_fails(db):
    group, branches, _ = _workspace(db)
    report = _report(db, group)
    before = [(row.id, row.name, row.status) for row in branches]
    result = conversion.inspect_conversion(
        db,
        school_group_id=group.id,
        workspace_uuid=group.workspace_uuid,
        expected_name=group.name,
        owner_email="owner@example.edu",
        audit_snapshot_hash=report["snapshot_hash"],
        operation_uuid=str(uuid.uuid4()),
        idempotency_key="dry-run-production-shape",
    )
    assert result.status == "awaiting_owner_registration"
    assert result.changed is False
    assert [(row.id, row.name, row.status) for row in branches] == before
    assert sum(1 for row in branches if row.status) == 5
    assert sum(1 for row in branches if not row.status) == 15
    assert db.query(saas.models.ExistingWorkspaceConversionOperation).count() == 0
    with pytest.raises(conversion.ExistingWorkspaceConversionError) as caught:
        conversion.inspect_conversion(
            db,
            school_group_id=group.id,
            workspace_uuid=group.workspace_uuid,
            expected_name=group.name,
            owner_email="owner@example.edu",
            audit_snapshot_hash="0" * 64,
            operation_uuid=str(uuid.uuid4()),
            idempotency_key="stale-snapshot",
        )
    assert caught.value.reason_code == "audit_snapshot_mismatch"


def test_verified_owner_alignment_creates_no_commercial_or_pending_records(db):
    group, branches, _ = _workspace(db)
    account = _account(db)
    report = _report(db, group)
    operation = _operation(db, group, account, report)
    branch_state = [(row.id, row.status) for row in branches]

    aligned, owner_user, link = conversion.align_verified_owner(db, account)
    db.commit()

    assert aligned.id == operation.id
    assert aligned.status == "awaiting_setup"
    assert owner_user.school_group_id == group.id
    assert owner_user.is_active is False
    assert owner_user.password is None
    assert link.pending_organization_id is None
    assert link.link_type == "tenant_owner"
    assert account.account_purpose == "customer"
    assert [(row.id, row.status) for row in branches] == branch_state
    for model in (
        saas.models.PendingOrganization,
        saas.models.TenantProvisioningLink,
        saas.models.SubscriptionContract,
        saas.models.PaymentSubscription,
        saas.models.PromoGrant,
        saas.models.PromoRedemption,
        saas.models.SaaSDemoRequest,
    ):
        assert db.query(model).count() == 0


@pytest.mark.parametrize(
    ("verified", "active", "reason"),
    ((False, True, "account_verification_required"), (True, False, "owner_saas_account_not_active")),
)
def test_unverified_or_suspended_account_cannot_align(db, verified, active, reason):
    group, _, _ = _workspace(db)
    account = _account(db, verified=verified, active=active)
    operation = _operation(db, group, account, _report(db, group))
    with pytest.raises(conversion.ExistingWorkspaceConversionError) as caught:
        conversion.align_verified_owner(db, account)
    db.rollback()
    assert caught.value.reason_code == reason
    assert operation.aligned_saas_account_id is None
    assert db.query(saas.models.SaaSAccountUserLink).count() == 0


def test_cross_tenant_account_is_rejected_without_partial_owner(db):
    group, _, _ = _workspace(db)
    account = _account(db)
    operation = _operation(db, group, account, _report(db, group))
    other = models.SchoolGroup(
        name="Other Tenant",
        workspace_uuid=str(uuid.uuid4()),
        workspace_classification="customer",
        workspace_lifecycle_status="active",
    )
    db.add(other)
    db.flush()
    user = models.User(
        user_id="8000000001",
        username="foreign.owner",
        email=account.email,
        email_normalized=account.email_normalized,
        user_type=auth.USER_TYPE_TENANT,
        role=auth.ROLE_ADMINISTRATOR,
        access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
        school_group_id=other.id,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(saas.models.SaaSAccountUserLink(
        saas_account_id=account.id,
        operational_user_id=user.id,
        school_group_id=other.id,
        link_type="tenant_owner",
    ))
    db.commit()
    with pytest.raises(conversion.ExistingWorkspaceConversionError) as caught:
        conversion.align_verified_owner(db, account)
    db.rollback()
    assert caught.value.reason_code == "owner_linked_to_another_tenant"
    assert operation.aligned_saas_account_id is None


def test_existing_operational_user_is_reused(db):
    group, _, _ = _workspace(db)
    account = _account(db)
    user = models.User(
        user_id="8000000002",
        username="existing.owner",
        email=account.email,
        email_normalized=account.email_normalized,
        user_type=auth.USER_TYPE_TENANT,
        role=auth.ROLE_ADMINISTRATOR,
        access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
        school_group_id=group.id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    operation = _operation(db, group, account, _report(db, group))
    _, aligned_user, _ = conversion.align_verified_owner(db, account)
    db.commit()
    assert aligned_user.id == user.id
    assert db.query(models.User).filter_by(email_normalized=account.email_normalized).count() == 1
    assert operation.aligned_operational_user_id == user.id


def test_owner_transfer_requires_explicit_approval(db):
    group, _, _ = _workspace(db)
    prior_account = _account(db, email="prior.owner@example.edu")
    prior_user = models.User(
        user_id="8000000003",
        username="prior.owner",
        email=prior_account.email,
        email_normalized=prior_account.email_normalized,
        user_type=auth.USER_TYPE_TENANT,
        role=auth.ROLE_ADMINISTRATOR,
        access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
        school_group_id=group.id,
        is_active=True,
    )
    db.add(prior_user)
    db.flush()
    db.add(saas.models.SaaSAccountUserLink(
        saas_account_id=prior_account.id,
        operational_user_id=prior_user.id,
        school_group_id=group.id,
        link_type="tenant_owner",
    ))
    db.commit()
    account = _account(db, email="new.owner@example.edu")
    operation = _operation(db, group, account, _report(db, group, account.email))
    with pytest.raises(conversion.ExistingWorkspaceConversionError) as caught:
        conversion.align_verified_owner(db, account)
    db.rollback()
    assert caught.value.reason_code == "owner_transfer_approval_required"

    operation.owner_transfer_approved_at = datetime.utcnow()
    operation.owner_transfer_approved_by_user_id = None
    db.commit()
    conversion.align_verified_owner(db, account)
    db.commit()
    links = db.query(saas.models.SaaSAccountUserLink).filter_by(
        school_group_id=group.id
    ).order_by(saas.models.SaaSAccountUserLink.id).all()
    assert [row.link_type for row in links] == ["former_tenant_owner", "tenant_owner"]


def test_verified_claim_controls_login_continuation(db):
    group, _, _ = _workspace(db)
    account = _account(db)
    _operation(db, group, account, _report(db, group))
    assert customer_journey_service.login_destination(db, account) == "/saas/existing-workspace/setup"
    conversion.align_verified_owner(db, account)
    db.commit()
    assert customer_journey_service.login_destination(db, account) == "/saas/existing-workspace/setup"


def test_setup_review_updates_only_three_fields_and_requires_iana_timezone(db):
    group, branches, _ = _workspace(db)
    profile = models.TenantProfile(
        school_group_id=group.id,
        website="https://existing.example.edu",
        school_type="International School",
    )
    db.add(profile)
    account = _account(db)
    db.commit()
    operation = _operation(db, group, account, _report(db, group))
    conversion.align_verified_owner(db, account)
    db.commit()
    original_group = (group.name, group.country_code, group.country_name)
    original_branches = [(row.id, row.name, row.status) for row in branches]

    with pytest.raises(conversion.ExistingWorkspaceConversionError) as caught:
        conversion.save_setup_review(
            db,
            account,
            legal_name="Existing Customer Legal Name",
            timezone_name="Not/A_Timezone",
            educational_program="NATIONAL",
        )
    db.rollback()
    assert caught.value.reason_code == "invalid_timezone"

    operation = conversion.save_setup_review(
        db,
        account,
        legal_name="Existing Customer Legal Name",
        timezone_name="Asia/Riyadh",
        educational_program="BOTH",
    )
    db.commit()
    assert operation.status == "ready"
    assert profile.legal_name == "Existing Customer Legal Name"
    assert profile.timezone == "Asia/Riyadh"
    assert profile.educational_program == "BOTH"
    assert profile.website == "https://existing.example.edu"
    assert profile.school_type == "International School"
    assert (group.name, group.country_code, group.country_name) == original_group
    assert [(row.id, row.name, row.status) for row in branches] == original_branches


def test_activation_required_is_resolved_fail_closed_and_account_access_remains(db):
    group, _, entitlement = _workspace(db)
    account = _account(db)
    report = _report(db, group)
    _operation(db, group, account, report)
    operation, owner_user, _ = conversion.align_verified_owner(db, account)
    conversion.save_setup_review(
        db,
        account,
        legal_name="Existing Customer Legal Name",
        timezone_name="Asia/Riyadh",
        educational_program="NATIONAL",
    )
    entitlement.status = "ended"
    entitlement.effective_to = datetime.utcnow()
    group.workspace_classification = "customer"
    group.workspace_lifecycle_status = "provisioning"
    owner_user.is_active = True
    operation.status = "completed"
    operation.stage = "converted"
    db.commit()

    authority = commercial_authority_service.resolve_commercial_authority(db, group.id)
    assert authority.resolution_status == "resolved"
    assert authority.commercial_status == "activation_required"
    assert authority.access_allowed is False
    assert authority.source == "no_commercial_access"
    accesses = customer_journey_service.list_organization_account_accesses(db, account)
    assert len(accesses) == 1
    assert accesses[0].is_owner is True
    assert accesses[0].can_manage_account is True
    assert accesses[0].commercial_access.allowed_access is False


def test_migration_adds_ledger_owner_uniqueness_and_append_only_events(tmp_path):
    database_path = tmp_path / "m4b.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        models.Base.metadata.create_all(engine)
        applied = db_migrations.run_pending_migrations(engine)
        assert "20260806_001_existing_workspace_controlled_conversion" in applied
        assert db_migrations.run_pending_migrations(engine) == []
        inspector = inspect(engine)
        assert "existing_workspace_conversion_operations" in inspector.get_table_names()
        assert "existing_workspace_conversion_events" in inspector.get_table_names()
        assert "legal_name" in {row["name"] for row in inspector.get_columns("tenant_profiles")}
        indexes = {row["name"] for row in inspector.get_indexes("saas_account_user_links")}
        assert "uq_saas_account_user_links_tenant_owner_group" in indexes
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO school_groups (name, workspace_uuid, workspace_classification, workspace_lifecycle_status, status, created_at, updated_at) "
                "VALUES ('Ledger Group', :uuid, 'internal_sandbox', 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"uuid": str(uuid.uuid4())})
            connection.execute(text(
                "INSERT INTO existing_workspace_conversion_operations "
                "(operation_uuid, school_group_id, workspace_uuid_snapshot, expected_organization_name_snapshot, intended_owner_email_normalized, audit_snapshot_hash, canonical_parameter_hash, stage, status, dry_run, idempotency_key, current_classification_snapshot, current_lifecycle_snapshot, current_entitlement_snapshot_json, branch_snapshot_json, missing_field_snapshot_json, setup_snapshot_json, created_at, updated_at) "
                "VALUES (:operation_uuid, 1, :workspace_uuid, 'Ledger Group', 'owner@example.edu', :hash, :hash, 'registration_preparation', 'awaiting_owner_registration', 0, 'ledger-test', 'internal_sandbox', 'active', '[]', '[]', '[]', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"operation_uuid": str(uuid.uuid4()), "workspace_uuid": str(uuid.uuid4()), "hash": "a" * 64})
            connection.execute(text(
                "INSERT INTO existing_workspace_conversion_events (conversion_operation_id, event_type, result, details_json, created_at) "
                "VALUES (1, 'prepared', 'success', '{}', CURRENT_TIMESTAMP)"
            ))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(
                    "UPDATE existing_workspace_conversion_events SET result = 'blocked' WHERE id = 1"
                ))
    finally:
        engine.dispose()


def test_cli_is_dry_run_by_default_and_templates_expose_only_supported_activation():
    source = Path("scripts/convert_existing_workspace.py").read_text(encoding="utf-8")
    account_template = Path("templates/saas/account.html").read_text(encoding="utf-8")
    setup_template = Path("templates/saas/existing_workspace_setup.html").read_text(encoding="utf-8")
    assert "if not args.execute" in source
    assert "--confirmation-phrase" in source
    assert "PREPARE {args.operation_uuid}" in source
    assert "CONVERT {normalized_uuid}" in Path(
        "saas/existing_workspace_conversion_service.py"
    ).read_text(encoding="utf-8")
    assert "Online subscription activation for an existing workspace is being prepared" in account_template
    assert "/saas/promo" in account_template
    assert "legal_name" in setup_template
    assert "timezone_name" in setup_template
    assert "educational_program" in setup_template
    assert "Paddle" not in setup_template


POSTGRES_URL = os.getenv("TIS_TEST_POSTGRESQL_URL", "").strip()


@pytest.mark.skipif(not POSTGRES_URL, reason="TIS_TEST_POSTGRESQL_URL is required")
def test_postgresql_final_conversion_is_atomic_idempotent_and_preserves_branches():
    engine = create_engine(POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    models.Base.metadata.create_all(engine)
    db_migrations.run_pending_migrations(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    try:
        group, branches, entitlement = _workspace(session)
        actor = models.User(
            user_id="9900000001",
            username="m4b.platform.owner",
            email="m4b.platform.owner@example.edu",
            email_normalized="m4b.platform.owner@example.edu",
            user_type=auth.USER_TYPE_PLATFORM,
            platform_role=auth.PLATFORM_ROLE_OWNER,
            access_scope=auth.ACCESS_SCOPE_GLOBAL,
            is_active=True,
        )
        account = _account(session)
        session.add(actor)
        session.commit()
        report = _report(session, group)
        operation_uuid = str(uuid.uuid4())
        common = {
            "school_group_id": group.id,
            "workspace_uuid": group.workspace_uuid,
            "expected_name": group.name,
            "owner_email": account.email,
            "audit_snapshot_hash": report["snapshot_hash"],
            "operation_uuid": operation_uuid,
            "idempotency_key": "postgres-final-conversion",
        }
        operation, prepared = conversion.prepare_registration(
            session,
            **common,
            approved_actor_user_id=actor.id,
            execution_actor_user_id=actor.id,
        )
        session.commit()
        assert prepared.status == "awaiting_owner_alignment"
        conversion.align_verified_owner(session, account)
        conversion.save_setup_review(
            session,
            account,
            legal_name="Existing Customer Legal Name",
            timezone_name="Asia/Riyadh",
            educational_program="NATIONAL",
        )
        session.commit()
        before = [(row.id, row.name, row.status) for row in branches]
        parameter_hash = conversion.canonical_parameter_hash(**common)
        actor_id = actor.id
        outcomes = []
        barrier = threading.Barrier(2)

        def worker():
            worker_session = Session()
            try:
                barrier.wait(timeout=10)
                result = conversion.execute_conversion(
                    worker_session,
                    operation_uuid=operation_uuid,
                    idempotency_key=common["idempotency_key"],
                    parameter_hash=parameter_hash,
                    confirmation_phrase=f"CONVERT {operation_uuid}",
                    execution_actor_user_id=actor_id,
                )
                worker_session.commit()
                outcomes.append((result.reason_code, result.changed))
            except conversion.ExistingWorkspaceConversionError as exc:
                worker_session.rollback()
                outcomes.append((exc.reason_code, False))
            finally:
                worker_session.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert len(outcomes) == 2
        assert sum(1 for _reason, changed in outcomes if changed) == 1
        assert {reason for reason, _changed in outcomes}.issubset({
            "conversion_completed",
            "already_completed",
            "conversion_operation_lock_unavailable",
        })
        session.expire_all()
        assert group.workspace_classification == "customer"
        assert group.workspace_lifecycle_status == "provisioning"
        assert entitlement.status == "ended"
        assert session.query(saas.models.WorkspaceEntitlement).filter_by(
            school_group_id=group.id,
            status="active",
        ).count() == 0
        assert session.query(saas.models.TenantProvisioningLink).count() == 0
        assert [(row.id, row.name, row.status) for row in branches] == before
        counts = {
            "pending": session.query(saas.models.PendingOrganization).count(),
            "contract": session.query(saas.models.SubscriptionContract).count(),
            "subscription": session.query(saas.models.PaymentSubscription).count(),
            "demo": session.query(saas.models.SaaSDemoRequest).count(),
            "promo": session.query(saas.models.PromoGrant).count(),
        }
        assert set(counts.values()) == {0}
        repeated = conversion.execute_conversion(
            session,
            operation_uuid=operation_uuid,
            idempotency_key=common["idempotency_key"],
            parameter_hash=parameter_hash,
            confirmation_phrase=f"CONVERT {operation_uuid}",
            execution_actor_user_id=actor.id,
        )
        session.rollback()
        assert repeated.reason_code == "already_completed"
        assert repeated.changed is False

        rollback_group, rollback_branches, rollback_entitlement = _workspace(
            session, name="Rollback Workspace"
        )
        rollback_account = _account(session, email="rollback.owner@example.edu")
        rollback_report = _report(session, rollback_group, rollback_account.email)
        rollback_uuid = str(uuid.uuid4())
        rollback_common = {
            "school_group_id": rollback_group.id,
            "workspace_uuid": rollback_group.workspace_uuid,
            "expected_name": rollback_group.name,
            "owner_email": rollback_account.email,
            "audit_snapshot_hash": rollback_report["snapshot_hash"],
            "operation_uuid": rollback_uuid,
            "idempotency_key": "postgres-rollback-conversion",
        }
        rollback_operation, _ = conversion.prepare_registration(
            session,
            **rollback_common,
            approved_actor_user_id=actor_id,
            execution_actor_user_id=actor_id,
        )
        session.commit()
        conversion.align_verified_owner(session, rollback_account)
        conversion.save_setup_review(
            session,
            rollback_account,
            legal_name="Rollback Customer Legal Name",
            timezone_name="Asia/Riyadh",
            educational_program="INTERNATIONAL",
        )
        session.commit()
        session.add(models.Branch(
            school_group_id=rollback_group.id,
            name="Unexpected Branch",
            status=False,
        ))
        session.commit()
        with pytest.raises(conversion.ExistingWorkspaceConversionError) as caught:
            conversion.execute_conversion(
                session,
                operation_uuid=rollback_uuid,
                idempotency_key=rollback_common["idempotency_key"],
                parameter_hash=conversion.canonical_parameter_hash(**rollback_common),
                confirmation_phrase=f"CONVERT {rollback_uuid}",
                execution_actor_user_id=actor_id,
            )
        session.rollback()
        session.expire_all()
        assert caught.value.reason_code == "branch_inventory_or_dependency_drift"
        assert rollback_group.workspace_classification == "internal_sandbox"
        assert rollback_group.workspace_lifecycle_status == "active"
        assert rollback_entitlement.status == "active"
        assert rollback_operation.status == "ready"
        assert len(rollback_branches) == 20
    finally:
        session.close()
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
