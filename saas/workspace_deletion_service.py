from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models as operational_models
from saas import models, workspace_analysis_service


class WorkspaceDeletionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class WorkspaceDeletionResult:
    organization_uuid: str
    organization_name: str
    school_group_id: int
    analysis_counts: dict[str, int]
    deleted_records: int


def _delete(query) -> int:
    return int(query.delete(synchronize_session=False) or 0)


def _analysis_counts(analysis: dict) -> dict[str, int]:
    return {row.table: int(row.count or 0) for row in analysis["counts"]}


def validate_preflight(db: Session, organization) -> dict:
    analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
    if not analysis["safe_for_future_reset"]:
        raise WorkspaceDeletionBlocked(
            "This workspace requires manual review before it can be deleted. No data was changed."
        )
    if not analysis["school_group_id"]:
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
        raise WorkspaceDeletionBlocked(
            "The typed organization name does not match. No data was changed."
        )
    if not str(reason or "").strip():
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
    provisioning_job_ids = [row[0] for row in db.query(models.ProvisioningJob.id).filter_by(pending_organization_id=pending_id).all()]

    deleted = 0
    if provisioning_job_ids:
        deleted += _delete(db.query(models.ProvisioningJobEvent).filter(models.ProvisioningJobEvent.provisioning_job_id.in_(provisioning_job_ids)))
    deleted += _delete(db.query(models.ProvisioningJob).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.SaaSAccountUserLink).filter_by(pending_organization_id=pending_id))
    deleted += _delete(db.query(models.TenantProvisioningLink).filter_by(pending_organization_id=pending_id))

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

    db.query(models.PendingOrganization).filter_by(id=pending_id).update({models.PendingOrganization.last_payment_attempt_id: None}, synchronize_session=False)
    db.query(models.CheckoutSession).filter_by(pending_organization_id=pending_id).update({models.CheckoutSession.last_payment_attempt_id: None}, synchronize_session=False)
    db.query(models.SubscriptionContract).filter_by(pending_organization_id=pending_id).update({models.SubscriptionContract.selected_checkout_session_id: None}, synchronize_session=False)
    payment_subscription_ids = [row[0] for row in db.query(models.PaymentSubscription.id).filter_by(pending_organization_id=pending_id).all()]
    if payment_subscription_ids:
        deleted += _delete(db.query(models.SubscriptionChangeRequest).filter(models.SubscriptionChangeRequest.payment_subscription_id.in_(payment_subscription_ids)))
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
    db.flush()

    return WorkspaceDeletionResult(
        organization_uuid=organization_uuid,
        organization_name=organization_name,
        school_group_id=school_group_id,
        analysis_counts=_analysis_counts(analysis),
        deleted_records=deleted,
    )
