from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import auth
import models
import saas.models as saas_models
from saas import (
    commercial_authority_service,
    promo_branch_entitlement_reconciliation_service as reconciliation,
    promo_grant_service,
)


def _fixture():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    group = models.SchoolGroup(
        name="Promo Reconciliation",
        workspace_classification="customer",
        workspace_lifecycle_status="active",
    )
    account = saas_models.SaaSAccount(
        account_uuid=str(uuid.uuid4()),
        email="promo-reconcile@example.edu",
        email_normalized="promo-reconcile@example.edu",
        status="active",
    )
    plan = saas_models.SubscriptionPlan(
        plan_code="enterprise_ai",
        plan_name="Enterprise AI",
        max_branches=25,
        max_system_users=100,
        max_staff_users=100,
        max_teachers=500,
        is_active=True,
        is_public=True,
    )
    db.add_all((group, account, plan))
    db.flush()
    selected = models.Branch(school_group_id=group.id, name="Selected", status=True)
    inactive = models.Branch(school_group_id=group.id, name="Inactive", status=False)
    year = models.AcademicYear(
        school_group_id=group.id, year_name="2026-2027", is_active=True
    )
    db.add_all((selected, inactive, year))
    db.flush()
    owner = models.User(
        user_id="PROMOREC01",
        username="promo.reconcile.owner",
        user_type=auth.USER_TYPE_TENANT,
        access_scope=auth.ACCESS_SCOPE_ORGANIZATION,
        school_group_id=group.id,
        branch_id=selected.id,
        academic_year_id=year.id,
        is_active=True,
    )
    db.add(owner)
    db.flush()
    now = datetime.utcnow()
    grant = saas_models.PromoGrant(
        promo_redemption_id=999,
        school_group_id=group.id,
        plan_id=plan.id,
        plan_code_snapshot=plan.plan_code,
        plan_name_snapshot=plan.plan_name,
        allowed_branches=4,
        allowed_staff_users=100,
        allowed_teachers=200,
        effective_from=now - timedelta(days=1),
        effective_to=now + timedelta(days=30),
        definition_snapshot_json="{}",
        capacity_snapshot_json="{}",
        scope_snapshot_json="{}",
        immutable_snapshot_hash="a" * 64,
        activated_at=now,
    )
    db.add(grant)
    db.flush()
    workspace = saas_models.WorkspaceEntitlement(
        school_group_id=group.id,
        entitlement_type="promo",
        status="active",
        source="promo",
        promo_grant_id=grant.id,
        effective_from=grant.effective_from,
        effective_to=grant.effective_to,
    )
    db.add(workspace)
    db.flush()
    db.add_all((
        saas_models.TenantProvisioningLink(
            promo_grant_id=grant.id,
            school_group_id=group.id,
            owner_operational_user_id=owner.id,
            primary_branch_id=selected.id,
            primary_academic_year_id=year.id,
            tenant_status="tenant_active",
        ),
        saas_models.SaaSAccountUserLink(
            saas_account_id=account.id,
            operational_user_id=owner.id,
            school_group_id=group.id,
            link_type="tenant_owner",
        ),
        saas_models.PromoGrantBranchAssignment(
            promo_grant_id=grant.id,
            school_group_id=group.id,
            branch_id=selected.id,
            branch_identity_snapshot=str(selected.id),
            branch_name_snapshot=selected.name,
            assigned_by_saas_account_id=account.id,
            assigned_at=now,
        ),
        saas_models.BranchEntitlement(
            school_group_id=group.id,
            branch_id=selected.id,
            workspace_entitlement_id=workspace.id,
            entitlement_mode="active",
            reason_code="promo_grant_selected",
        ),
    ))
    db.commit()
    return SimpleNamespace(
        engine=engine,
        db=db,
        group=group,
        account=account,
        grant=grant,
        workspace=workspace,
        selected=selected,
        inactive=inactive,
    )


def _run(fixture, *, apply=False):
    authority = SimpleNamespace(
        resolved=True,
        access_allowed=True,
        source=commercial_authority_service.PROMO_GRANT,
    )
    with patch.object(
        commercial_authority_service,
        "resolve_commercial_authority",
        return_value=authority,
    ):
        return reconciliation.reconcile_promo_branch_entitlements(
            fixture.db,
            school_group_id=fixture.group.id,
            workspace_uuid=fixture.group.workspace_uuid,
            apply=apply,
        )


def test_dry_run_apply_and_second_apply_are_safe_and_idempotent():
    fixture = _fixture()
    try:
        dry = _run(fixture)
        assert dry.status == "ready"
        assert [row.branch_id for row in dry.planned_actions] == [fixture.inactive.id]
        assert fixture.db.query(saas_models.BranchEntitlement).filter_by(
            branch_id=fixture.inactive.id
        ).count() == 0

        applied = _run(fixture, apply=True)
        fixture.db.commit()
        assert applied.status == "applied"
        assert applied.applied_count == 1
        row = fixture.db.query(saas_models.BranchEntitlement).filter_by(
            branch_id=fixture.inactive.id
        ).one()
        assert row.entitlement_mode == "inactive"
        assert fixture.db.get(models.Branch, fixture.inactive.id).status is False
        assert fixture.db.query(saas_models.PromoGrantBranchAssignment).filter_by(
            branch_id=fixture.inactive.id
        ).count() == 0
        assert _run(fixture, apply=True).status == "no_changes"
    finally:
        fixture.db.close()
        fixture.engine.dispose()


def test_selected_missing_entitlement_and_mismatched_entitlement_fail_closed():
    fixture = _fixture()
    try:
        selected_row = fixture.db.query(saas_models.BranchEntitlement).filter_by(
            branch_id=fixture.selected.id
        ).one()
        fixture.db.delete(selected_row)
        fixture.db.commit()
        assert _run(fixture).reason_code == "selected_branch_missing_active_entitlement"
        fixture.db.close()
        fixture.engine.dispose()
        fixture = _fixture()
        wrong_workspace = saas_models.WorkspaceEntitlement(
            school_group_id=fixture.group.id,
            entitlement_type="internal_sandbox",
            status="ended",
            source="system",
        )
        fixture.db.add(wrong_workspace)
        fixture.db.flush()
        selected_row = fixture.db.query(saas_models.BranchEntitlement).filter_by(
            branch_id=fixture.selected.id
        ).one()
        selected_row.workspace_entitlement_id = wrong_workspace.id
        fixture.db.commit()
        assert _run(fixture).reason_code == "promo_branch_entitlement_mismatch"
    finally:
        fixture.db.close()
        fixture.engine.dispose()


def test_apply_failure_can_be_rolled_back_without_partial_evidence():
    fixture = _fixture()
    try:
        with patch.object(fixture.db, "flush", side_effect=RuntimeError("forced")):
            try:
                _run(fixture, apply=True)
            except RuntimeError:
                fixture.db.rollback()
        assert fixture.db.query(saas_models.BranchEntitlement).filter_by(
            branch_id=fixture.inactive.id
        ).count() == 0
    finally:
        fixture.db.close()
        fixture.engine.dispose()


def test_unresolved_commercial_authority_fails_closed():
    fixture = _fixture()
    try:
        authority = SimpleNamespace(
            resolved=False,
            access_allowed=False,
            source="conflict",
        )
        with patch.object(
            commercial_authority_service,
            "resolve_commercial_authority",
            return_value=authority,
        ):
            result = reconciliation.reconcile_promo_branch_entitlements(
                fixture.db,
                school_group_id=fixture.group.id,
                workspace_uuid=fixture.group.workspace_uuid,
            )
        assert result.status == "manual_review"
        assert result.reason_code == "promo_commercial_authority_unresolved"
    finally:
        fixture.db.close()
        fixture.engine.dispose()


def test_branch_reactivation_promotes_inactive_evidence_once_and_enforces_capacity():
    fixture = _fixture()
    try:
        _run(fixture, apply=True)
        fixture.db.commit()
        row = promo_grant_service.activate_branch_if_available(
            fixture.db, fixture.inactive
        )
        fixture.db.commit()
        assert row.entitlement_mode == "active"
        assert promo_grant_service.activate_branch_if_available(
            fixture.db, fixture.inactive
        ).id == row.id
        assert fixture.db.query(saas_models.BranchEntitlement).filter_by(
            branch_id=fixture.inactive.id
        ).count() == 1
        assert fixture.db.query(saas_models.PromoGrantBranchAssignment).filter_by(
            branch_id=fixture.inactive.id
        ).count() == 1

        fixture.grant.allowed_branches = 2
        extra = models.Branch(
            school_group_id=fixture.group.id, name="Extra", status=False
        )
        fixture.db.add(extra)
        fixture.db.flush()
        fixture.db.add(saas_models.BranchEntitlement(
            school_group_id=fixture.group.id,
            branch_id=extra.id,
            workspace_entitlement_id=fixture.workspace.id,
            entitlement_mode="inactive",
        ))
        fixture.db.commit()
        try:
            promo_grant_service.activate_branch_if_available(fixture.db, extra)
            assert False, "capacity should block the assignment"
        except promo_grant_service.PromoBranchAssignmentError as exc:
            fixture.db.rollback()
            assert exc.reason_code == "promo_branch_capacity_reached"
        assert fixture.db.get(models.Branch, extra.id).status is False
    finally:
        fixture.db.close()
        fixture.engine.dispose()


def test_cli_defaults_to_dry_run_and_commits_only_on_explicit_apply(capsys):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_promo_branch_entitlements.py"
    source = script_path.read_text(encoding="utf-8")
    assert "paddle" not in source.lower()
    assert "send_email" not in source
    assert 'action="store_true"' in source
    spec = importlib.util.spec_from_file_location("promo_reconcile_cli_test", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = reconciliation.ReconciliationResult(
        "ready", "inactive_branch_entitlements_missing", 1, str(uuid.uuid4())
    )
    dry_db = Mock()
    with (
        patch.object(module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))),
        patch.object(module, "SessionLocal", return_value=dry_db),
        patch.object(module.reconciliation, "reconcile_promo_branch_entitlements", return_value=result),
    ):
        assert module.main(["--school-group-id", "1", "--workspace-uuid", result.workspace_uuid]) == 0
    dry_db.rollback.assert_called_once()
    dry_db.commit.assert_not_called()

    applied = reconciliation.ReconciliationResult(
        "applied", "inactive_branch_entitlements_reconciled", 1, result.workspace_uuid,
        applied_count=1,
    )
    apply_db = Mock()
    with (
        patch.object(module, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))),
        patch.object(module, "SessionLocal", return_value=apply_db),
        patch.object(module.reconciliation, "reconcile_promo_branch_entitlements", return_value=applied),
    ):
        assert module.main([
            "--school-group-id", "1", "--workspace-uuid", result.workspace_uuid, "--apply"
        ]) == 0
    apply_db.commit.assert_called_once()
    apply_db.rollback.assert_not_called()
    assert "inactive_branch_entitlements" in capsys.readouterr().out
