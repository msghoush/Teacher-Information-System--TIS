from __future__ import annotations

from dataclasses import dataclass
import logging

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import models as operational_models
from saas import models, workspace_analysis_service


logger = logging.getLogger(__name__)


class WorkspaceDeletionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class WorkspaceDeletionResult:
    organization_uuid: str
    organization_name: str
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
        "test_workspace_deletion delete_step=begin model=%s table=%s",
        model_name,
        table_name,
    )
    try:
        affected_rows = int(query.delete(synchronize_session=False) or 0)
    except SQLAlchemyError as exc:
        logger.exception(
            "test_workspace_deletion database_failure model=%s table=%s "
            "foreign_key_or_constraint=%s parent_object=selected_workspace "
            "child_object=%s exception=%s",
            model_name,
            table_name,
            _constraint_name(exc),
            model_name,
            exc,
        )
        raise
    logger.info(
        "test_workspace_deletion delete_step=success model=%s table=%s affected_rows=%s",
        model_name,
        table_name,
        affected_rows,
    )
    return affected_rows


def _update(query, values) -> int:
    model_name, table_name = _query_target(query)
    logger.info(
        "test_workspace_deletion update_step=begin model=%s table=%s",
        model_name,
        table_name,
    )
    try:
        affected_rows = int(query.update(values, synchronize_session=False) or 0)
    except SQLAlchemyError as exc:
        logger.exception(
            "test_workspace_deletion database_failure model=%s table=%s "
            "foreign_key_or_constraint=%s parent_object=selected_workspace "
            "child_object=%s exception=%s",
            model_name,
            table_name,
            _constraint_name(exc),
            model_name,
            exc,
        )
        raise
    logger.info(
        "test_workspace_deletion update_step=success model=%s table=%s affected_rows=%s",
        model_name,
        table_name,
        affected_rows,
    )
    return affected_rows


def _analysis_counts(analysis: dict) -> dict[str, int]:
    return {row.table: int(row.count or 0) for row in analysis["counts"]}


_WORKSPACE_DELETION_MODELS = (
    models.ProvisioningJobEvent, models.ProvisioningJob, models.SaaSAccountUserLink,
    models.TenantProvisioningLink, models.SaaSDemoConversionEvent,
    models.SaaSDemoToPaidConversion, models.SaaSDemoLifecycleNotification,
    models.SaaSDemoLifecycleEvent, models.SaaSDemoProvisioningEvent,
    models.SaaSDemoWorkspaceProvisioning, models.SaaSDemoRequestReview,
    models.SaaSDemoRequestEvent, models.SaaSDemoDomainEligibility,
    models.SaaSDemoRequest, operational_models.CalendarEventNotification,
    operational_models.CalendarEventGradeTarget, operational_models.CalendarEventSectionTarget,
    operational_models.CalendarEventAssignment, operational_models.CalendarEvent,
    operational_models.ObservationSelfEvaluationScore, operational_models.ObservationScore,
    operational_models.ObservationSelfEvaluation, operational_models.Observation,
    operational_models.TeacherSubjectAllocation, operational_models.TeacherQualificationSelection,
    operational_models.TeacherSectionAssignment, operational_models.TimetableNonTeachingBlock,
    operational_models.TimetableEntry, operational_models.HiringPlanDraft,
    operational_models.TimetableSetting, operational_models.Teacher, operational_models.Subject,
    operational_models.PlanningSection, operational_models.CalendarEventType,
    operational_models.BranchLogo, operational_models.SystemNotification,
    operational_models.PlatformUserPermission, operational_models.User,
    operational_models.RolePermission, operational_models.SchoolGroupLogo,
    operational_models.VisualDesignSetting, operational_models.TenantProfile,
    operational_models.Branch, operational_models.AcademicYear,
    models.AIFeatureUsageEvent, models.AIFeatureUsageCounter,
    models.WorkspaceEntitlementValue, models.BranchEntitlement, models.WorkspaceEntitlement,
    models.SubscriptionChangeRequest, models.PaymentSubscription, models.PaymentAttempt,
    models.CheckoutSession, models.SubscriptionContract, models.PaymentCustomer,
    models.PendingOrganizationPlanSelection, models.PendingOrganizationBranch,
    models.PendingOrganizationAcademicSetup, models.PendingOrganizationContact,
    models.PendingOrganizationProgress, models.PendingOrganizationNote,
    models.PendingOrganizationEvent, models.PendingOrganization, operational_models.SchoolGroup,
)


def deletion_diagnostic_scope(analysis: dict) -> dict[str, object]:
    """Return read-only deletion scope metadata for backend diagnostics."""
    record_counts = _analysis_counts(analysis)
    dependency_tables = (
        "branches", "academic_years", "users", "teachers", "planning_sections",
        "calendar_events", "observations", "provisioning_jobs", "payment_subscriptions",
    )
    return {
        "tables_touched": tuple(model.__tablename__ for model in _WORKSPACE_DELETION_MODELS),
        "record_counts": record_counts,
        "demo_domain_cleanup": dict(analysis.get("demo_domain_cleanup") or {}),
        "dependency_counts": {
            table_name: int(record_counts.get(table_name, 0))
            for table_name in dependency_tables
        },
    }


def validate_preflight(db: Session, organization) -> dict:
    analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
    if not analysis["safe_for_future_reset"]:
        logger.info(
            "test_workspace_deletion validation_blocked validation=preflight_safe_for_future_reset "
            "reason=manual_review_required values_checked=%s",
            {"safe_for_future_reset": False, "warnings": analysis["warnings"]},
        )
        raise WorkspaceDeletionBlocked(
            "This workspace requires manual review before it can be deleted. No data was changed."
        )
    if not analysis["school_group_id"]:
        logger.info(
            "test_workspace_deletion validation_blocked validation=linked_workspace "
            "reason=workspace_not_resolved values_checked=%s",
            {"school_group_id": analysis["school_group_id"]},
        )
        raise WorkspaceDeletionBlocked(
            "A linked operational workspace could not be resolved. No data was changed."
        )
    return analysis


def delete_test_workspace(
    db: Session,
    organization,
    *,
    confirmation_name: str,
    reason: str,
) -> WorkspaceDeletionResult:
    analysis = validate_preflight(db, organization)
    organization_name = str(organization.organization_name or "")
    if confirmation_name != organization_name:
        logger.info(
            "test_workspace_deletion validation_blocked validation=organization_name_confirmation "
            "reason=typed_name_mismatch values_checked=%s",
            {"organization_name": organization_name, "confirmation_matches": False},
        )
        raise WorkspaceDeletionBlocked(
            "The typed organization name does not match. No data was changed."
        )
    if not str(reason or "").strip():
        logger.info(
            "test_workspace_deletion validation_blocked validation=deletion_reason "
            "reason=reason_required values_checked=%s",
            {"reason_present": False},
        )
        raise WorkspaceDeletionBlocked("A deletion reason is required. No data was changed.")

    pending_id = int(organization.id)
    school_group_id = int(analysis["school_group_id"])
    organization_uuid = str(organization.organization_uuid or "")
    branch_ids = [row[0] for row in db.query(operational_models.Branch.id).filter_by(school_group_id=school_group_id).all()]
    year_ids = [row[0] for row in db.query(operational_models.AcademicYear.id).filter_by(school_group_id=school_group_id).all()]
    users = db.query(operational_models.User).filter_by(school_group_id=school_group_id)
    user_pks = [row[0] for row in users.with_entities(operational_models.User.id).all()]
    teacher_ids = [row[0] for row in db.query(operational_models.Teacher.id).filter(
        or_(operational_models.Teacher.branch_id.in_(branch_ids) if branch_ids else False,
            operational_models.Teacher.academic_year_id.in_(year_ids) if year_ids else False)
    ).all()]
    section_ids = [row[0] for row in db.query(operational_models.PlanningSection.id).filter(
        or_(operational_models.PlanningSection.branch_id.in_(branch_ids) if branch_ids else False,
            operational_models.PlanningSection.academic_year_id.in_(year_ids) if year_ids else False)
    ).all()]
    event_ids = [row[0] for row in db.query(operational_models.CalendarEvent.id).filter(
        or_(operational_models.CalendarEvent.branch_id.in_(branch_ids) if branch_ids else False,
            operational_models.CalendarEvent.academic_year_id.in_(year_ids) if year_ids else False)
    ).all()]
    observation_ids = [row[0] for row in db.query(operational_models.Observation.id).filter(
        or_(operational_models.Observation.branch_id.in_(branch_ids) if branch_ids else False,
            operational_models.Observation.academic_year_id.in_(year_ids) if year_ids else False,
            operational_models.Observation.teacher_id.in_(teacher_ids) if teacher_ids else False)
    ).all()]
    self_evaluation_ids = [row[0] for row in db.query(operational_models.ObservationSelfEvaluation.id).filter(
        operational_models.ObservationSelfEvaluation.observation_id.in_(observation_ids)
    ).all()] if observation_ids else []
    timetable_setting_ids = [row[0] for row in db.query(operational_models.TimetableSetting.id).filter(
        or_(operational_models.TimetableSetting.branch_id.in_(branch_ids) if branch_ids else False,
            operational_models.TimetableSetting.academic_year_id.in_(year_ids) if year_ids else False)
    ).all()]
    workspace_entitlement_ids = [row[0] for row in db.query(models.WorkspaceEntitlement.id).filter(
        models.WorkspaceEntitlement.school_group_id == school_group_id
    ).all()]
    provisioning_job_ids = [row[0] for row in db.query(models.ProvisioningJob.id).filter_by(pending_organization_id=pending_id).all()]
    demo_request_ids = [row[0] for row in db.query(models.SaaSDemoRequest.id).filter(
        models.SaaSDemoRequest.pending_organization_id == pending_id
    ).all()]
    demo_provisioning_ids = [row[0] for row in db.query(models.SaaSDemoWorkspaceProvisioning.id).filter(
        models.SaaSDemoWorkspaceProvisioning.demo_request_id.in_(demo_request_ids)
    ).all()] if demo_request_ids else []
    demo_conversion_ids = [row[0] for row in db.query(models.SaaSDemoToPaidConversion.id).filter(
        models.SaaSDemoToPaidConversion.pending_organization_id == pending_id
    ).all()]
    demo_domain_cleanup = dict(analysis.get("demo_domain_cleanup") or {})
    orphaned_eligibility_ids = [
        int(value)
        for value in demo_domain_cleanup.get("orphaned_eligibility_ids", ())
        if value is not None
    ]
    safe_orphaned_eligibility_ids = [
        int(value)
        for value in demo_domain_cleanup.get("safe_orphaned_eligibility_ids", ())
        if value is not None
    ]
    logger.info(
        "test_workspace_deletion safe_orphan_ids_received ids=%s "
        "all_orphan_ids=%s automatic_cleanup_safe=%s",
        safe_orphaned_eligibility_ids,
        orphaned_eligibility_ids,
        bool(demo_domain_cleanup.get("automatic_cleanup_safe")),
    )
    if orphaned_eligibility_ids and not bool(
        demo_domain_cleanup.get("automatic_cleanup_safe")
    ):
        logger.info(
            "test_workspace_deletion validation_blocked validation=orphaned_demo_domain_cleanup "
            "reason=ambiguous_domain_ownership values_checked=%s",
            demo_domain_cleanup,
        )
        raise WorkspaceDeletionBlocked(
            "Detached Customer Demo domain eligibility requires manual review. No data was changed."
        )
    if set(safe_orphaned_eligibility_ids) != set(orphaned_eligibility_ids):
        logger.info(
            "test_workspace_deletion validation_blocked "
            "validation=safe_orphan_id_handoff reason=analysis_id_mismatch "
            "values_checked=%s",
            {
                "orphaned_eligibility_ids": orphaned_eligibility_ids,
                "safe_orphaned_eligibility_ids": safe_orphaned_eligibility_ids,
            },
        )
        raise WorkspaceDeletionBlocked(
            "Detached Customer Demo domain eligibility requires manual review. No data was changed."
        )

    deleted = 0
    if safe_orphaned_eligibility_ids:
        logger.info(
            "test_workspace_deletion orphaned_demo_domain_cleanup "
            "deletion_query_scope=saas_demo_domain_eligibilities.id.in_ ids=%s",
            safe_orphaned_eligibility_ids,
        )
        affected_rows = _delete(
            db.query(models.SaaSDemoDomainEligibility).filter(
                models.SaaSDemoDomainEligibility.id.in_(
                    safe_orphaned_eligibility_ids
                )
            )
        )
        deleted += affected_rows
        logger.info(
            "test_workspace_deletion orphaned_demo_domain_cleanup "
            "affected_rows=%s ids=%s",
            affected_rows,
            safe_orphaned_eligibility_ids,
        )
        db.flush()
        verification_count = int(
            db.query(models.SaaSDemoDomainEligibility).filter(
                models.SaaSDemoDomainEligibility.id.in_(
                    safe_orphaned_eligibility_ids
                )
            ).count()
            or 0
        )
        logger.info(
            "test_workspace_deletion orphaned_demo_domain_cleanup "
            "verification_remaining_count=%s ids=%s",
            verification_count,
            safe_orphaned_eligibility_ids,
        )
        if verification_count:
            raise WorkspaceDeletionBlocked(
                "Detached Customer Demo domain eligibility could not be removed. "
                "No data was changed."
            )
    if provisioning_job_ids:
        deleted += _delete(db.query(models.ProvisioningJobEvent).filter(models.ProvisioningJobEvent.provisioning_job_id.in_(provisioning_job_ids)))
    deleted += _delete(db.query(models.ProvisioningJob).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.SaaSAccountUserLink).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.TenantProvisioningLink).filter_by(pending_organization_id=pending_id))
    if demo_conversion_ids:
        deleted += _delete(db.query(models.SaaSDemoConversionEvent).filter(
            models.SaaSDemoConversionEvent.demo_conversion_id.in_(demo_conversion_ids)
        ))
    deleted += _delete(db.query(models.SaaSDemoToPaidConversion).filter(
        models.SaaSDemoToPaidConversion.pending_organization_id == pending_id
    ))
    if demo_provisioning_ids:
        deleted += _delete(db.query(models.SaaSDemoLifecycleNotification).filter(
            models.SaaSDemoLifecycleNotification.demo_provisioning_id.in_(demo_provisioning_ids)
        ))
        deleted += _delete(db.query(models.SaaSDemoLifecycleEvent).filter(
            models.SaaSDemoLifecycleEvent.demo_provisioning_id.in_(demo_provisioning_ids)
        ))
        deleted += _delete(db.query(models.SaaSDemoProvisioningEvent).filter(
            models.SaaSDemoProvisioningEvent.demo_provisioning_id.in_(demo_provisioning_ids)
        ))
    if demo_request_ids:
        deleted += _delete(db.query(models.SaaSDemoWorkspaceProvisioning).filter(
            models.SaaSDemoWorkspaceProvisioning.demo_request_id.in_(demo_request_ids)
        ))
        deleted += _delete(db.query(models.SaaSDemoRequestReview).filter(
            models.SaaSDemoRequestReview.demo_request_id.in_(demo_request_ids)
        ))
        deleted += _delete(db.query(models.SaaSDemoRequestEvent).filter(
            models.SaaSDemoRequestEvent.demo_request_id.in_(demo_request_ids)
        ))
        deleted += _delete(db.query(models.SaaSDemoDomainEligibility).filter(
            models.SaaSDemoDomainEligibility.demo_request_id.in_(demo_request_ids)
        ))
    deleted += _delete(db.query(models.SaaSDemoRequest).filter(
        models.SaaSDemoRequest.pending_organization_id == pending_id
    ))
    deleted += _delete(db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.school_group_id == school_group_id
    ))
    deleted += _delete(db.query(models.AIFeatureUsageEvent).filter(
        models.AIFeatureUsageEvent.school_group_id == school_group_id
    ))
    deleted += _delete(db.query(models.AIFeatureUsageCounter).filter(
        models.AIFeatureUsageCounter.school_group_id == school_group_id
    ))
    if workspace_entitlement_ids:
        deleted += _delete(db.query(models.WorkspaceEntitlementValue).filter(
            models.WorkspaceEntitlementValue.workspace_entitlement_id.in_(workspace_entitlement_ids)
        ))
    deleted += _delete(db.query(models.BranchEntitlement).filter(or_(
        models.BranchEntitlement.school_group_id == school_group_id,
        models.BranchEntitlement.workspace_entitlement_id.in_(workspace_entitlement_ids) if workspace_entitlement_ids else False,
    )))
    deleted += _delete(db.query(models.WorkspaceEntitlement).filter(
        models.WorkspaceEntitlement.school_group_id == school_group_id
    ))

    assignment_ids = [row[0] for row in db.query(operational_models.CalendarEventAssignment.id).filter(or_(
        operational_models.CalendarEventAssignment.calendar_event_id.in_(event_ids) if event_ids else False,
        operational_models.CalendarEventAssignment.teacher_id.in_(teacher_ids) if teacher_ids else False,
        operational_models.CalendarEventAssignment.user_id.in_(user_pks) if user_pks else False,
    )).all()]
    system_notification_ids = [row[0] for row in db.query(operational_models.SystemNotification.id).filter_by(
        school_group_id=school_group_id
    ).all()]
    deleted += _delete(db.query(operational_models.CalendarEventNotification).filter(or_(
        operational_models.CalendarEventNotification.calendar_event_id.in_(event_ids) if event_ids else False,
        operational_models.CalendarEventNotification.assignment_id.in_(assignment_ids) if assignment_ids else False,
        operational_models.CalendarEventNotification.system_notification_id.in_(system_notification_ids) if system_notification_ids else False,
    )))
    if event_ids:
        deleted += _delete(db.query(operational_models.CalendarEventGradeTarget).filter(operational_models.CalendarEventGradeTarget.calendar_event_id.in_(event_ids)))
    deleted += _delete(db.query(operational_models.CalendarEventSectionTarget).filter(or_(
        operational_models.CalendarEventSectionTarget.calendar_event_id.in_(event_ids) if event_ids else False,
        operational_models.CalendarEventSectionTarget.section_id.in_(section_ids) if section_ids else False,
    )))
    if assignment_ids:
        deleted += _delete(db.query(operational_models.CalendarEventAssignment).filter(operational_models.CalendarEventAssignment.id.in_(assignment_ids)))
    if event_ids:
        deleted += _delete(db.query(operational_models.CalendarEvent).filter(operational_models.CalendarEvent.id.in_(event_ids)))
    if self_evaluation_ids:
        deleted += _delete(db.query(operational_models.ObservationSelfEvaluationScore).filter(operational_models.ObservationSelfEvaluationScore.self_evaluation_id.in_(self_evaluation_ids)))
    if observation_ids:
        deleted += _delete(db.query(operational_models.ObservationScore).filter(operational_models.ObservationScore.observation_id.in_(observation_ids)))
        deleted += _delete(db.query(operational_models.ObservationSelfEvaluation).filter(or_(
            operational_models.ObservationSelfEvaluation.observation_id.in_(observation_ids),
            operational_models.ObservationSelfEvaluation.teacher_id.in_(teacher_ids) if teacher_ids else False,
        )))
        deleted += _delete(db.query(operational_models.Observation).filter(operational_models.Observation.id.in_(observation_ids)))
    if teacher_ids:
        deleted += _delete(db.query(operational_models.TeacherSubjectAllocation).filter(operational_models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids)))
        deleted += _delete(db.query(operational_models.TeacherQualificationSelection).filter(operational_models.TeacherQualificationSelection.teacher_id.in_(teacher_ids)))
    deleted += _delete(db.query(operational_models.TeacherSectionAssignment).filter(or_(
        operational_models.TeacherSectionAssignment.teacher_id.in_(teacher_ids) if teacher_ids else False,
        operational_models.TeacherSectionAssignment.planning_section_id.in_(section_ids) if section_ids else False,
    )))
    if timetable_setting_ids:
        deleted += _delete(db.query(operational_models.TimetableNonTeachingBlock).filter(operational_models.TimetableNonTeachingBlock.timetable_setting_id.in_(timetable_setting_ids)))
    deleted += _delete(db.query(operational_models.TimetableEntry).filter(or_(
        operational_models.TimetableEntry.branch_id.in_(branch_ids) if branch_ids else False,
        operational_models.TimetableEntry.academic_year_id.in_(year_ids) if year_ids else False,
        operational_models.TimetableEntry.planning_section_id.in_(section_ids) if section_ids else False,
        operational_models.TimetableEntry.teacher_id.in_(teacher_ids) if teacher_ids else False)))
    deleted += _delete(db.query(operational_models.HiringPlanDraft).filter(or_(
        operational_models.HiringPlanDraft.branch_id.in_(branch_ids) if branch_ids else False,
        operational_models.HiringPlanDraft.academic_year_id.in_(year_ids) if year_ids else False,
        operational_models.HiringPlanDraft.user_id.in_(user_pks) if user_pks else False)))
    deleted += _delete(db.query(operational_models.TimetableSetting).filter(operational_models.TimetableSetting.id.in_(timetable_setting_ids))) if timetable_setting_ids else 0
    deleted += _delete(db.query(operational_models.Teacher).filter(operational_models.Teacher.id.in_(teacher_ids))) if teacher_ids else 0
    deleted += _delete(db.query(operational_models.Subject).filter(or_(
        operational_models.Subject.branch_id.in_(branch_ids) if branch_ids else False,
        operational_models.Subject.academic_year_id.in_(year_ids) if year_ids else False)))
    deleted += _delete(db.query(operational_models.PlanningSection).filter(operational_models.PlanningSection.id.in_(section_ids))) if section_ids else 0
    deleted += _delete(db.query(operational_models.CalendarEventType).filter(or_(
        operational_models.CalendarEventType.branch_id.in_(branch_ids) if branch_ids else False,
        operational_models.CalendarEventType.academic_year_id.in_(year_ids) if year_ids else False)))
    deleted += _delete(db.query(operational_models.BranchLogo).filter(operational_models.BranchLogo.branch_id.in_(branch_ids))) if branch_ids else 0
    deleted += _delete(db.query(operational_models.SystemNotification).filter(operational_models.SystemNotification.school_group_id == school_group_id))
    deleted += _delete(db.query(operational_models.PlatformUserPermission).filter(operational_models.PlatformUserPermission.platform_user_id.in_(user_pks))) if user_pks else 0
    deleted += _delete(db.query(operational_models.User).filter(operational_models.User.id.in_(user_pks))) if user_pks else 0
    deleted += _delete(db.query(operational_models.RolePermission).filter_by(school_group_id=school_group_id))
    deleted += _delete(db.query(operational_models.SchoolGroupLogo).filter_by(school_group_id=school_group_id))
    deleted += _delete(db.query(operational_models.VisualDesignSetting).filter_by(school_group_id=school_group_id))
    deleted += _delete(db.query(operational_models.TenantProfile).filter_by(school_group_id=school_group_id))
    deleted += _delete(db.query(operational_models.Branch).filter(operational_models.Branch.id.in_(branch_ids))) if branch_ids else 0
    deleted += _delete(db.query(operational_models.AcademicYear).filter(operational_models.AcademicYear.id.in_(year_ids))) if year_ids else 0

    _update(db.query(models.PendingOrganization).filter_by(id=pending_id), {models.PendingOrganization.last_payment_attempt_id: None})
    _update(db.query(models.CheckoutSession).filter_by(pending_organization_id=pending_id), {models.CheckoutSession.last_payment_attempt_id: None})
    _update(db.query(models.SubscriptionContract).filter_by(pending_organization_id=pending_id), {models.SubscriptionContract.selected_checkout_session_id: None})
    deleted += _delete(db.query(models.PaymentSubscription).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.PaymentAttempt).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.CheckoutSession).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.SubscriptionContract).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.PaymentCustomer).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.PendingOrganizationPlanSelection).filter_by(pending_organization_id=pending_id))
    for child in (models.PendingOrganizationBranch, models.PendingOrganizationAcademicSetup,
                  models.PendingOrganizationContact, models.PendingOrganizationProgress,
                  models.PendingOrganizationNote, models.PendingOrganizationEvent):
        deleted += _delete(db.query(child).filter(child.pending_organization_id == pending_id))
    deleted += _delete(db.query(models.PendingOrganization).filter_by(id=pending_id))
    deleted += _delete(db.query(operational_models.SchoolGroup).filter_by(id=school_group_id))
    logger.info("test_workspace_deletion flush=begin")
    db.flush()
    logger.info("test_workspace_deletion flush=success")

    return WorkspaceDeletionResult(
        organization_uuid=organization_uuid,
        organization_name=organization_name,
        school_group_id=school_group_id,
        analysis_counts=_analysis_counts(analysis),
        deleted_records=deleted,
    )
