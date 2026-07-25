from __future__ import annotations

from dataclasses import dataclass
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import auth
import models as operational_models
from saas import models, workspace_analysis_service, workspace_deletion_service


logger = logging.getLogger(__name__)


class TestAccountDeletionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class TestAccountDeletionAnalysis:
    account_id: int
    account_uuid: str
    account_email: str
    organization_name: str
    organization_uuid: str
    workspace_name: str
    school_group_id: int
    total_records: int
    warnings: tuple[str, ...]
    workspace_analysis: dict

    @property
    def safe_to_delete(self) -> bool:
        return not self.warnings and bool(self.school_group_id)


@dataclass(frozen=True)
class TestAccountDeletionResult:
    account_id: int
    account_uuid: str
    account_email: str
    organization_name: str
    organization_uuid: str
    school_group_id: int
    analysis_counts: dict[str, int]
    deleted_records: int


def _query_target(query) -> tuple[str, str]:
    entity = next(
        (
            description.get("entity")
            for description in getattr(query, "column_descriptions", ())
            if description.get("entity") is not None
        ),
        None,
    )
    return (
        str(getattr(entity, "__name__", "UnknownModel")),
        str(getattr(entity, "__tablename__", "unknown_table")),
    )


def _constraint_name(exc: SQLAlchemyError) -> str:
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    return str(
        getattr(diagnostic, "constraint_name", None)
        or getattr(original, "constraint_name", None)
        or "unavailable"
    )


def _delete(query) -> int:
    model_name, table_name = _query_target(query)
    logger.info(
        "test_account_workspace_deletion delete_step=begin model=%s table=%s",
        model_name,
        table_name,
    )
    try:
        affected_rows = int(query.delete(synchronize_session=False) or 0)
    except SQLAlchemyError as exc:
        logger.exception(
            "test_account_workspace_deletion database_failure model=%s table=%s "
            "foreign_key_or_constraint=%s parent_object=selected_test_account "
            "child_object=%s exception=%s",
            model_name,
            table_name,
            _constraint_name(exc),
            model_name,
            exc,
        )
        raise
    logger.info(
        "test_account_workspace_deletion delete_step=success model=%s table=%s affected_rows=%s",
        model_name,
        table_name,
        affected_rows,
    )
    return affected_rows


def deletion_diagnostic_scope(analysis: TestAccountDeletionAnalysis) -> dict[str, object]:
    workspace_scope = workspace_deletion_service.deletion_diagnostic_scope(
        analysis.workspace_analysis
    )
    account_models = (
        models.SaaSAccountUserLink,
        models.PaymentCustomer,
        models.SaaSSession,
        models.SaaSEmailVerificationToken,
        models.SaaSPasswordResetToken,
        models.SaaSAuthIdentity,
        models.SaaSAuthEvent,
        models.SaaSAccount,
    )
    return {
        **workspace_scope,
        "tables_touched": tuple(
            dict.fromkeys(
                (*workspace_scope["tables_touched"], *(model.__tablename__ for model in account_models))
            )
        ),
        "account_record_count": int(
            analysis.total_records
            - int(analysis.workspace_analysis["total_linked_records"] or 0)
        ),
    }


def analyze_test_account(db: Session, organization) -> TestAccountDeletionAnalysis:
    workspace_analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
    warnings = list(workspace_analysis["warnings"])
    account_id = int(getattr(organization, "owner_saas_account_id", 0) or 0)
    account = db.query(models.SaaSAccount).filter(models.SaaSAccount.id == account_id).first()
    if not account:
        warnings.append("The owning TIS Account could not be resolved.")
        return TestAccountDeletionAnalysis(
            account_id=account_id,
            account_uuid="",
            account_email="",
            organization_name=str(organization.organization_name or ""),
            organization_uuid=str(organization.organization_uuid or ""),
            workspace_name=str(workspace_analysis["workspace_name"] or ""),
            school_group_id=int(workspace_analysis["school_group_id"] or 0),
            total_records=int(workspace_analysis["total_linked_records"] or 0),
            warnings=tuple(warnings),
            workspace_analysis=workspace_analysis,
        )

    pending_rows = db.query(models.PendingOrganization).filter(
        models.PendingOrganization.owner_saas_account_id == account_id
    ).all()
    if len(pending_rows) != 1 or int(pending_rows[0].id) != int(organization.id):
        warnings.append("The TIS Account owns another pending organization or workspace.")

    school_group_id = int(workspace_analysis["school_group_id"] or 0)
    links = db.query(models.SaaSAccountUserLink).filter(
        models.SaaSAccountUserLink.saas_account_id == account_id
    ).all()
    if any(
        int(getattr(link, "pending_organization_id", 0) or 0) != int(organization.id)
        or int(getattr(link, "school_group_id", 0) or 0) != school_group_id
        for link in links
    ):
        warnings.append("The TIS Account is linked to another operational tenant or organization.")
    linked_user_ids = [int(link.operational_user_id) for link in links]
    if linked_user_ids:
        linked_users = db.query(operational_models.User).filter(
            operational_models.User.id.in_(linked_user_ids)
        ).all()
        if len(linked_users) != len(set(linked_user_ids)) or any(
            int(getattr(user, "school_group_id", 0) or 0) != school_group_id
            for user in linked_users
        ):
            warnings.append("An account-user link does not belong exclusively to the selected workspace.")

    payment_customers = db.query(models.PaymentCustomer).filter(
        models.PaymentCustomer.saas_account_id == account_id
    ).all()
    if any(int(row.pending_organization_id) != int(organization.id) for row in payment_customers):
        warnings.append("The TIS Account has a payment-customer mapping for another organization.")

    normalized_email = auth.normalize_email(str(account.email_normalized or account.email or ""))
    platform_identity = next(
        (
            user
            for user in db.query(operational_models.User).filter(
                operational_models.User.user_type == auth.USER_TYPE_PLATFORM
            ).all()
            if auth.normalize_email(str(user.email_normalized or user.email or "")) == normalized_email
        ),
        None,
    )
    if platform_identity:
        warnings.append("This email belongs to a Platform Owner or Platform Developer account.")

    account_record_count = sum(
        query.count()
        for query in (
            db.query(models.SaaSAccount).filter(models.SaaSAccount.id == account_id),
            db.query(models.SaaSAuthIdentity).filter(models.SaaSAuthIdentity.saas_account_id == account_id),
            db.query(models.SaaSSession).filter(models.SaaSSession.saas_account_id == account_id),
            db.query(models.SaaSAuthEvent).filter(models.SaaSAuthEvent.saas_account_id == account_id),
            db.query(models.SaaSEmailVerificationToken).filter(models.SaaSEmailVerificationToken.saas_account_id == account_id),
            db.query(models.SaaSPasswordResetToken).filter(models.SaaSPasswordResetToken.saas_account_id == account_id),
        )
    )
    return TestAccountDeletionAnalysis(
        account_id=account_id,
        account_uuid=str(account.account_uuid or ""),
        account_email=str(account.email or ""),
        organization_name=str(organization.organization_name or ""),
        organization_uuid=str(organization.organization_uuid or ""),
        workspace_name=str(workspace_analysis["workspace_name"] or ""),
        school_group_id=school_group_id,
        total_records=int(workspace_analysis["total_linked_records"] or 0) + int(account_record_count),
        warnings=tuple(dict.fromkeys(warnings)),
        workspace_analysis=workspace_analysis,
    )


def delete_test_account_and_workspace(
    db: Session,
    organization,
    *,
    confirmation_name: str,
    confirmation_email: str,
    reason: str,
) -> TestAccountDeletionResult:
    analysis = analyze_test_account(db, organization)
    if not analysis.safe_to_delete:
        logger.info(
            "test_account_workspace_deletion validation_blocked validation=account_workspace_preflight "
            "reason=manual_review_required values_checked=%s",
            {
                "safe_to_delete": False,
                "school_group_id": analysis.school_group_id,
                "warnings": analysis.warnings,
            },
        )
        raise TestAccountDeletionBlocked(
            "This test account requires manual review before it can be deleted. No data was changed."
        )
    if confirmation_name != analysis.organization_name:
        logger.info(
            "test_account_workspace_deletion validation_blocked validation=organization_name_confirmation "
            "reason=typed_name_mismatch values_checked=%s",
            {"organization_name": analysis.organization_name, "confirmation_matches": False},
        )
        raise TestAccountDeletionBlocked(
            "The typed organization name does not match. No data was changed."
        )
    if confirmation_email != analysis.account_email:
        logger.info(
            "test_account_workspace_deletion validation_blocked validation=account_email_confirmation "
            "reason=typed_email_mismatch values_checked=%s",
            {"account_id": analysis.account_id, "confirmation_matches": False},
        )
        raise TestAccountDeletionBlocked(
            "The typed account email does not match. No data was changed."
        )
    if not str(reason or "").strip():
        logger.info(
            "test_account_workspace_deletion validation_blocked validation=deletion_reason "
            "reason=reason_required values_checked=%s",
            {"reason_present": False},
        )
        raise TestAccountDeletionBlocked("A deletion reason is required. No data was changed.")

    workspace_result = workspace_deletion_service.delete_test_workspace(
        db,
        organization,
        confirmation_name=confirmation_name,
        reason=reason,
    )
    account_id = analysis.account_id
    deleted = workspace_result.deleted_records
    deleted += _delete(db.query(models.SaaSAccountUserLink).filter(models.SaaSAccountUserLink.saas_account_id == account_id))
    deleted += _delete(db.query(models.PaymentCustomer).filter(models.PaymentCustomer.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSSession).filter(models.SaaSSession.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSEmailVerificationToken).filter(models.SaaSEmailVerificationToken.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSPasswordResetToken).filter(models.SaaSPasswordResetToken.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSAuthIdentity).filter(models.SaaSAuthIdentity.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSAuthEvent).filter(models.SaaSAuthEvent.saas_account_id == account_id))
    deleted += _delete(db.query(models.SaaSAccount).filter(models.SaaSAccount.id == account_id))
    logger.info("test_account_workspace_deletion flush=begin account_id=%s", account_id)
    db.flush()
    logger.info("test_account_workspace_deletion flush=success account_id=%s", account_id)

    counts = {row.table: int(row.count or 0) for row in analysis.workspace_analysis["counts"]}
    counts["saas_account_identity_records"] = analysis.total_records - int(
        analysis.workspace_analysis["total_linked_records"] or 0
    )
    return TestAccountDeletionResult(
        account_id=analysis.account_id,
        account_uuid=analysis.account_uuid,
        account_email=analysis.account_email,
        organization_name=analysis.organization_name,
        organization_uuid=analysis.organization_uuid,
        school_group_id=analysis.school_group_id,
        analysis_counts=counts,
        deleted_records=deleted,
    )
