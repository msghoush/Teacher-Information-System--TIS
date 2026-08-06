import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import saas.models
from saas.existing_workspace_conversion_audit_service import (
    audit_existing_workspace_conversion,
)


@pytest.fixture()
def audit_db():
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


def _seed_workspace(db):
    workspace_uuid = str(uuid.uuid4())
    group = models.SchoolGroup(
        name="Existing Academy",
        workspace_uuid=workspace_uuid,
        workspace_classification="internal_sandbox",
        workspace_lifecycle_status="active",
    )
    unrelated = models.SchoolGroup(
        name="Unrelated Academy",
        workspace_uuid=str(uuid.uuid4()),
        workspace_classification="internal_sandbox",
        workspace_lifecycle_status="active",
    )
    db.add_all([group, unrelated])
    db.flush()
    branch = models.Branch(school_group_id=group.id, name="Main Campus", status=True)
    unrelated_branch = models.Branch(
        school_group_id=unrelated.id, name="Other Campus", status=True
    )
    db.add_all([branch, unrelated_branch])
    db.flush()
    year = models.AcademicYear(
        school_group_id=group.id, year_name="2026-2027", is_active=True
    )
    db.add(year)
    db.flush()
    teacher = models.Teacher(
        teacher_id="T0001",
        first_name="Test",
        last_name="Teacher",
        branch_id=branch.id,
        academic_year_id=year.id,
    )
    db.add(teacher)
    db.flush()
    db.add(
        models.TeacherSubjectAllocation(
            teacher_id=teacher.id,
            subject_code="MATH",
            compatibility_override=False,
        )
    )
    user = models.User(
        user_id="9000000001",
        username="owner.primary",
        email="owner@example.edu",
        email_normalized="owner@example.edu",
        role="Admin",
        user_type="TENANT",
        access_scope="GROUP",
        school_group_id=group.id,
        branch_id=branch.id,
        is_active=True,
    )
    account = saas.models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email="owner@example.edu",
        email_normalized="owner@example.edu",
        status="active",
        onboarding_status="tenant_active",
        account_purpose="internal_test",
        email_verified_at=datetime.utcnow(),
    )
    db.add_all([user, account])
    db.flush()
    db.add(
        saas.models.WorkspaceEntitlement(
            entitlement_uuid=str(uuid.uuid4()),
            school_group_id=group.id,
            entitlement_type="internal_sandbox",
            status="active",
            source="system",
        )
    )
    db.add(
        saas.models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=user.id,
            school_group_id=group.id,
            link_type="tenant_owner",
        )
    )
    db.commit()
    return group, unrelated, branch, unrelated_branch


def _audit(db, group):
    return audit_existing_workspace_conversion(
        db,
        school_group_id=group.id,
        workspace_uuid=group.workspace_uuid,
        expected_name=group.name,
        owner_email=" OWNER@EXAMPLE.EDU ",
    )


def test_audit_resolves_exact_workspace_and_excludes_unrelated_tenant(audit_db):
    group, unrelated, branch, unrelated_branch = _seed_workspace(audit_db)

    report = _audit(audit_db, group)

    assert report["mode"] == "read_only"
    assert report["identity_validation"] == {
        "school_group_resolved": True,
        "workspace_uuid_matches": True,
        "exact_name_matches": True,
        "duplicate_normalized_names": [],
    }
    assert report["workspace"]["school_group"]["id"] == group.id
    assert [item["id"] for item in report["workspace"]["branches"]] == [branch.id]
    rendered = str(report)
    assert unrelated.name not in rendered
    assert str(unrelated_branch.id) not in {
        str(item["id"]) for item in report["workspace"]["branches"]
    }
    assert report["owner_identity"]["saas_accounts"][0]["email_normalized"] == "owner@example.edu"
    assert report["conversion_readiness"]["write_conversion_approved"] is False
    assert report["conversion_readiness"]["hard_delete_approved"] is False


def test_audit_traverses_direct_and_indirect_branch_dependencies(audit_db):
    group, _, branch, _ = _seed_workspace(audit_db)

    report = _audit(audit_db, group)
    branch_report = report["workspace"]["branches"][0]
    paths = {item["path"] for item in branch_report["dependencies"]}

    assert "branches -> teachers" in paths
    assert "branches -> teachers -> teacher_subject_allocations" in paths
    assert branch_report["dependency_record_count"] >= 2
    assert branch_report["safe_for_hard_delete"] is False
    assert report["conversion_readiness"]["status"] == "ready_for_conversion_design"


def test_audit_snapshot_and_json_model_are_stable_for_identical_state(audit_db):
    group, _, _, _ = _seed_workspace(audit_db)

    first = _audit(audit_db, group)
    second = _audit(audit_db, group)

    assert first == second
    assert len(first["snapshot_hash"]) == 64
    assert first["snapshot_hash"] == second["snapshot_hash"]
    assert "generated_at" not in first


def test_empty_branch_is_the_only_recommended_archival_candidate(audit_db):
    group, _, occupied_branch, _ = _seed_workspace(audit_db)
    empty = models.Branch(
        school_group_id=group.id,
        name="Empty Campus",
        status=True,
    )
    audit_db.add(empty)
    audit_db.commit()

    report = _audit(audit_db, group)

    assert report["conversion_readiness"]["recommended_archival_branch_ids"] == [
        empty.id
    ]
    assert occupied_branch.id not in report["conversion_readiness"][
        "recommended_archival_branch_ids"
    ]
    assert report["conversion_readiness"]["hard_delete_approved"] is False


def test_unknown_foreign_key_and_soft_deleted_dependency_fail_closed(audit_db):
    group, _, _, _ = _seed_workspace(audit_db)
    branch = models.Branch(
        school_group_id=group.id,
        name="Soft Deleted Campus",
        status=True,
    )
    audit_db.add(branch)
    audit_db.commit()
    audit_db.execute(
        text(
            "CREATE TABLE m4a_unknown_soft_links ("
            "id INTEGER PRIMARY KEY, "
            "branch_id INTEGER NOT NULL REFERENCES branches(id), "
            "deleted_at DATETIME)"
        )
    )
    audit_db.execute(
        text(
            "INSERT INTO m4a_unknown_soft_links(id, branch_id, deleted_at) "
            "VALUES (1, :branch_id, CURRENT_TIMESTAMP)"
        ),
        {"branch_id": branch.id},
    )
    audit_db.commit()

    report = _audit(audit_db, group)
    branch_report = next(
        item for item in report["workspace"]["branches"] if item["id"] == branch.id
    )
    dependency = next(
        item
        for item in branch_report["dependencies"]
        if item["table"] == "m4a_unknown_soft_links"
    )

    assert dependency["record_count"] == 1
    assert dependency["soft_deleted_record_count"] == 1
    assert dependency["active_record_count"] == 0
    assert branch_report["safe_for_hard_delete"] is False
    assert report["schema_coverage"]["branch_foreign_key_traversal"] == "manual_review"
    assert report["schema_coverage"]["unknown_branch_foreign_keys"] == [
        {
            "table": "m4a_unknown_soft_links",
            "column": "branch_id",
            "target": "branches.id",
            "on_delete": None,
        }
    ]
    assert report["conversion_readiness"]["recommended_archival_branch_ids"] == []


def test_setup_fields_resolve_from_operational_sources(audit_db):
    group, _, _, _ = _seed_workspace(audit_db)
    group.country_code = "LB"
    group.country_name = "Lebanon"
    audit_db.add(
        models.TenantProfile(
            school_group_id=group.id,
            website="https://example.edu",
            timezone="Asia/Beirut",
            educational_program="National",
            school_type="Private",
        )
    )
    audit_db.commit()

    report = _audit(audit_db, group)
    fields = {
        item["field"]: item for item in report["setup_field_resolution"]["fields"]
    }

    assert fields["display_name"]["source"] == "school_groups"
    assert fields["country_code"]["source"] == "school_groups"
    assert fields["website"]["source"] == "tenant_profiles"
    assert fields["timezone"]["source"] == "tenant_profiles"
    assert "legal_name" in report["setup_field_resolution"]["missing_required_fields"]


def test_audit_identity_mismatch_fails_closed(audit_db):
    group, _, _, _ = _seed_workspace(audit_db)

    report = audit_existing_workspace_conversion(
        audit_db,
        school_group_id=group.id,
        workspace_uuid=str(uuid.uuid4()),
        expected_name="Wrong Academy",
        owner_email="owner@example.edu",
    )

    assert report["conversion_readiness"]["status"] == "manual_review_required"
    assert report["conversion_readiness"]["blockers"] == [
        "workspace_name_mismatch",
        "workspace_uuid_mismatch",
    ]
    assert report["assurances"]["data_changed"] is False


@pytest.mark.parametrize(
    ("school_group_id_delta", "uuid_override", "name_override", "expected_blocker"),
    [
        (999, None, None, "school_group_not_found"),
        (0, "different", None, "workspace_uuid_mismatch"),
        (0, None, "Different Name", "workspace_name_mismatch"),
    ],
)
def test_exact_workspace_identity_failures_are_distinct(
    audit_db,
    school_group_id_delta,
    uuid_override,
    name_override,
    expected_blocker,
):
    group, _, _, _ = _seed_workspace(audit_db)

    report = audit_existing_workspace_conversion(
        audit_db,
        school_group_id=group.id + school_group_id_delta,
        workspace_uuid=(str(uuid.uuid4()) if uuid_override else group.workspace_uuid),
        expected_name=name_override or group.name,
        owner_email="owner@example.edu",
    )

    assert expected_blocker in report["conversion_readiness"]["blockers"]


def test_owner_resolution_absent_unlinked_same_and_cross_tenant(audit_db):
    group, unrelated, _, _ = _seed_workspace(audit_db)

    absent = audit_existing_workspace_conversion(
        audit_db,
        school_group_id=group.id,
        workspace_uuid=group.workspace_uuid,
        expected_name=group.name,
        owner_email="absent@example.edu",
    )
    assert absent["owner_identity"]["resolution"] == "owner_absent"
    assert "owner_saas_account_absent" in absent["conversion_readiness"]["warnings"]

    link = audit_db.query(saas.models.SaaSAccountUserLink).filter_by(
        school_group_id=group.id
    ).one()
    account_id = link.saas_account_id
    user_id = link.operational_user_id
    audit_db.delete(link)
    audit_db.commit()
    unlinked = _audit(audit_db, group)
    assert unlinked["owner_identity"]["resolution"] == "owner_verified_unlinked"
    assert "owner_account_link_missing" in unlinked["conversion_readiness"]["warnings"]

    audit_db.add(
        saas.models.SaaSAccountUserLink(
            saas_account_id=account_id,
            operational_user_id=user_id,
            school_group_id=group.id,
            link_type="tenant_owner",
        )
    )
    audit_db.commit()
    linked = _audit(audit_db, group)
    assert linked["owner_identity"]["resolution"] == "owner_linked_to_same_tenant"

    audit_db.add(
        saas.models.SaaSAccountUserLink(
            saas_account_id=account_id,
            operational_user_id=user_id,
            school_group_id=unrelated.id,
            link_type="tenant_owner",
        )
    )
    audit_db.commit()
    cross_tenant = _audit(audit_db, group)
    assert cross_tenant["owner_identity"]["resolution"] == "owner_linked_to_another_tenant"
    assert "owner_link_targets_another_workspace" in cross_tenant[
        "conversion_readiness"
    ]["blockers"]


def test_different_existing_owner_blocks_with_single_owner_invariant(audit_db):
    group, unrelated, _, _ = _seed_workspace(audit_db)
    existing_owner_link = audit_db.query(saas.models.SaaSAccountUserLink).filter_by(
        school_group_id=group.id,
        link_type="tenant_owner",
    ).one()
    existing_owner_link.link_type = "former_tenant_owner"
    other_account = saas.models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email="other.owner@example.edu",
        email_normalized="other.owner@example.edu",
        status="active",
        onboarding_status="tenant_active",
        account_purpose="internal_test",
        email_verified_at=datetime.utcnow(),
    )
    other_user = models.User(
        user_id="9000000002",
        username="other.owner",
        email="other.owner@example.edu",
        email_normalized="other.owner@example.edu",
        role="Admin",
        user_type="TENANT",
        access_scope="GROUP",
        school_group_id=group.id,
        is_active=True,
    )
    collision_user = models.User(
        user_id="9000000003",
        username="owner@example.edu",
        email="collision@example.edu",
        email_normalized="collision@example.edu",
        role="Admin",
        user_type="TENANT",
        access_scope="GROUP",
        school_group_id=unrelated.id,
        is_active=True,
    )
    audit_db.add_all([other_account, other_user, collision_user])
    audit_db.flush()
    audit_db.add(
        saas.models.SaaSAccountUserLink(
            saas_account_id=other_account.id,
            operational_user_id=other_user.id,
            school_group_id=group.id,
            link_type="tenant_owner",
        )
    )
    audit_db.commit()

    report = _audit(audit_db, group)

    assert "different_existing_tenant_owner" in report["conversion_readiness"]["blockers"]
    assert "multiple_tenant_owner_links" not in report["conversion_readiness"]["blockers"]


def test_teacher_identity_collision_is_reported(audit_db):
    group, _, branch, _ = _seed_workspace(audit_db)
    second = models.Branch(school_group_id=group.id, name="Second Campus", status=True)
    audit_db.add(second)
    audit_db.flush()
    year = audit_db.query(models.AcademicYear).filter_by(school_group_id=group.id).one()
    audit_db.add(
        models.Teacher(
            teacher_id="T0001",
            first_name="Duplicate",
            last_name="Teacher",
            branch_id=second.id,
            academic_year_id=year.id,
        )
    )
    audit_db.commit()

    report = _audit(audit_db, group)

    assert report["workspace"]["teacher_identity_collisions"] == [
        {"teacher_identity": "t0001", "record_count": 2}
    ]
    assert "teacher_identity_collision" in report["conversion_readiness"]["blockers"]


def test_branch_entitlement_and_tenant_primary_branch_are_dependencies(audit_db):
    group, _, branch, _ = _seed_workspace(audit_db)
    entitlement = audit_db.query(saas.models.WorkspaceEntitlement).filter_by(
        school_group_id=group.id
    ).one()
    audit_db.add(
        saas.models.BranchEntitlement(
            branch_entitlement_uuid=str(uuid.uuid4()),
            school_group_id=group.id,
            branch_id=branch.id,
            workspace_entitlement_id=entitlement.id,
            entitlement_mode="inherit",
        )
    )
    owner = audit_db.query(saas.models.SaaSAccount).filter_by(
        email_normalized="owner@example.edu"
    ).one()
    user = audit_db.query(models.User).filter_by(school_group_id=group.id).one()
    pending = saas.models.PendingOrganization(
        organization_uuid=str(uuid.uuid4()),
        workspace_intent="customer_demo",
        owner_saas_account_id=owner.id,
        status="approved",
        onboarding_step="review",
        organization_name=group.name,
        billing_status="not_started",
        payment_status="pending",
    )
    audit_db.add(pending)
    audit_db.flush()
    demo = saas.models.SaaSDemoRequest(
        request_uuid=str(uuid.uuid4()),
        requester_saas_account_id=owner.id,
        pending_organization_id=pending.id,
        school_group_id=group.id,
        workspace_uuid_snapshot=group.workspace_uuid,
        workspace_classification_snapshot="internal_sandbox",
        commercial_state_snapshot="internal_sandbox_active",
        entitlement_snapshot_json="{}",
        status="approved",
        submitted_at=datetime.utcnow(),
        approved_at=datetime.utcnow(),
    )
    audit_db.add(demo)
    audit_db.flush()
    audit_db.add(
        saas.models.TenantProvisioningLink(
            pending_organization_id=pending.id,
            demo_request_id=demo.id,
            school_group_id=group.id,
            owner_operational_user_id=user.id,
            primary_branch_id=branch.id,
            tenant_status="tenant_active",
        )
    )
    audit_db.commit()

    report = _audit(audit_db, group)
    paths = {
        item["path"]
        for item in report["workspace"]["branches"][0]["dependencies"]
    }

    assert "branches -> branch_entitlements" in paths
    assert "branches -> tenant_provisioning_links" in paths
    assert "workspace_already_has_commercial_tenant_source" in report[
        "conversion_readiness"
    ]["blockers"]
    assert "workspace_has_existing_commercial_records" in report[
        "conversion_readiness"
    ]["blockers"]


def test_promo_restriction_and_open_session_branch_references_are_reported(audit_db):
    group, _, branch, _ = _seed_workspace(audit_db)
    owner = audit_db.query(saas.models.SaaSAccount).filter_by(
        email_normalized="owner@example.edu"
    ).one()
    user = audit_db.query(models.User).filter_by(school_group_id=group.id).one()
    plan = saas.models.SubscriptionPlan(
        plan_code="validation-plan",
        plan_name="Validation Plan",
        is_active=True,
        is_public=False,
        max_branches=10,
        max_staff_users=10,
        max_system_users=10,
        max_teachers=10,
    )
    audit_db.add(plan)
    audit_db.flush()
    now = datetime.now(timezone.utc)
    promo = saas.models.PromoCode(
        promo_uuid=str(uuid.uuid4()),
        code_lookup_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        code_hash_key_id="test-key",
        code_display_prefix="TIS",
        code_display_suffix="TEST",
        title="Validation Promo",
        status="active",
        definition_version=1,
        benefit_type="full_access",
        subscription_plan_id=plan.id,
        max_branches=10,
        max_system_users=10,
        max_teachers=10,
        scope_type="organization",
        school_group_id=group.id,
        max_total_redemptions=1,
        valid_from=now - timedelta(days=1),
        redemption_deadline=now + timedelta(days=10),
        fixed_access_expires_at=now + timedelta(days=30),
        grace_period_days=0,
    )
    audit_db.add(promo)
    audit_db.flush()
    audit_db.add(
        saas.models.PromoCodeBranchRestriction(
            promo_code_id=promo.id,
            branch_id=branch.id,
            branch_id_snapshot=branch.id,
            branch_name_snapshot=branch.name,
        )
    )
    session = saas.models.PromoActivationSession(
        activation_uuid=str(uuid.uuid4()),
        promo_code_id=promo.id,
        promo_definition_version=1,
        school_group_id=group.id,
        saas_account_id=owner.id,
        operational_user_id=user.id,
        context_type="existing_organization",
        status="open",
        stage="promo_validated",
        idempotency_key=uuid.uuid4().hex,
        masked_promo_reference="TIS...TEST",
        observed_branch_count=1,
        observed_staff_users=1,
        observed_teachers=1,
        expires_at=now + timedelta(hours=1),
    )
    audit_db.add(session)
    audit_db.flush()
    audit_db.add(
        saas.models.PromoActivationBranchSelection(
            activation_session_id=session.id,
            branch_id=branch.id,
            branch_identity_snapshot=str(branch.id),
            branch_name_snapshot=branch.name,
        )
    )
    audit_db.commit()

    report = _audit(audit_db, group)
    paths = {
        item["path"]
        for item in report["workspace"]["branches"][0]["dependencies"]
    }

    assert "branches -> promo_code_branch_restrictions" in paths
    assert "branches -> promo_activation_branch_selections" in paths


def test_audit_performs_no_database_mutation(audit_db):
    group, _, _, _ = _seed_workspace(audit_db)
    before = {
        table.name: audit_db.execute(select(func.count()).select_from(table)).scalar_one()
        for table in models.Base.metadata.tables.values()
    }

    report = _audit(audit_db, group)

    after = {
        table.name: audit_db.execute(select(func.count()).select_from(table)).scalar_one()
        for table in models.Base.metadata.tables.values()
    }
    assert after == before
    assert not audit_db.new
    assert not audit_db.dirty
    assert not audit_db.deleted
    assert report["assurances"] == {
        "data_changed": False,
        "paddle_called": False,
        "email_sent": False,
        "conversion_performed": False,
    }


def test_audit_rejects_incomplete_identity_inputs(audit_db):
    with pytest.raises(ValueError, match="all audit identity inputs are required"):
        audit_existing_workspace_conversion(
            audit_db,
            school_group_id=0,
            workspace_uuid="",
            expected_name="",
            owner_email="",
        )


def test_audit_masks_provider_identity_and_requires_review(audit_db):
    group, _, _, _ = _seed_workspace(audit_db)
    account = audit_db.query(saas.models.SaaSAccount).filter_by(
        email_normalized="owner@example.edu"
    ).one()
    audit_db.add(
        saas.models.PaymentCustomer(
            saas_account_id=account.id,
            provider="paddle",
            provider_customer_id="ctm_secret_provider_reference",
            provider_address_id="add_secret_provider_reference",
            provider_business_id="biz_secret_provider_reference",
            email=account.email,
            status="active",
        )
    )
    audit_db.commit()

    report = _audit(audit_db, group)

    payment_customer = report["commercial_state"]["payment_customers"][0]
    assert payment_customer["provider_customer_id_present"] is True
    assert payment_customer["provider_address_id_present"] is True
    assert payment_customer["provider_business_id_present"] is True
    assert "ctm_secret_provider_reference" not in str(report)
    assert report["conversion_readiness"]["status"] == "manual_review_required"
    assert "existing_provider_customer_mapping_requires_review" in report[
        "conversion_readiness"
    ]["warnings"]
