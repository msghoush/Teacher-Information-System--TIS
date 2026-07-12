from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import Session

import models as operational_models
from saas import models


@dataclass(frozen=True)
class AnalysisCount:
    category: str
    table: str
    count: int
    disposition: str


def _count(query) -> int:
    return int(query.count() or 0)


def _ids(query, column) -> list[int]:
    return [int(value) for (value,) in query.with_entities(column).all() if value is not None]


def _string_ids(query, column) -> list[str]:
    return [str(value) for (value,) in query.with_entities(column).all() if str(value or "").strip()]


def _safe_json(value: str | None) -> dict:
    try:
        payload = json.loads(str(value or "") or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _add_count(counts: list[AnalysisCount], *, category: str, table: str, count: int, disposition: str) -> None:
    counts.append(
        AnalysisCount(
            category=category,
            table=table,
            count=int(count or 0),
            disposition=disposition,
        )
    )


def _payment_webhook_count(db: Session, organization, attempts, subscription_rows) -> int:
    organization_uuid = str(getattr(organization, "organization_uuid", "") or "").strip()
    attempt_uuids = {
        str(getattr(attempt, "attempt_uuid", "") or "").strip()
        for attempt in attempts
        if str(getattr(attempt, "attempt_uuid", "") or "").strip()
    }
    provider_transaction_ids = {
        str(getattr(attempt, "provider_transaction_id", "") or "").strip()
        for attempt in attempts
        if str(getattr(attempt, "provider_transaction_id", "") or "").strip()
    }
    provider_subscription_ids = {
        str(getattr(row, "provider_subscription_id", "") or "").strip()
        for row in subscription_rows
        if str(getattr(row, "provider_subscription_id", "") or "").strip()
    }
    matched = 0
    for webhook in db.query(models.PaymentWebhook).filter(models.PaymentWebhook.provider == "paddle").all():
        payload = _safe_json(getattr(webhook, "payload_json", None))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        custom_data = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}
        webhook_org_uuid = str(custom_data.get("pending_organization_uuid") or "").strip()
        webhook_attempt_uuid = str(custom_data.get("payment_attempt_uuid") or "").strip()
        webhook_transaction_id = str(data.get("id") or "").strip()
        webhook_subscription_id = str(data.get("subscription_id") or "").strip()
        if (
            (organization_uuid and webhook_org_uuid == organization_uuid)
            or (webhook_attempt_uuid and webhook_attempt_uuid in attempt_uuids)
            or (webhook_transaction_id and webhook_transaction_id in provider_transaction_ids)
            or (webhook_subscription_id and webhook_subscription_id in provider_subscription_ids)
        ):
            matched += 1
    return matched


def analyze_test_workspace(db: Session, organization) -> dict:
    counts: list[AnalysisCount] = []
    warnings: list[str] = []

    if not organization:
        raise ValueError("Pending organization is required.")

    pending_organization_id = int(getattr(organization, "id", 0) or 0)
    owner_account_id = int(getattr(organization, "owner_saas_account_id", 0) or 0)
    organization_uuid = str(getattr(organization, "organization_uuid", "") or "")

    tenant_link = db.query(models.TenantProvisioningLink).filter(
        models.TenantProvisioningLink.pending_organization_id == pending_organization_id
    ).first()
    school_group_id = int(getattr(tenant_link, "school_group_id", 0) or 0) if tenant_link else 0
    school_group = None
    if school_group_id:
        school_group = db.query(operational_models.SchoolGroup).filter(
            operational_models.SchoolGroup.id == school_group_id
        ).first()
        if not school_group:
            warnings.append("Tenant provisioning link references a missing operational SchoolGroup.")
    else:
        warnings.append("No tenant provisioning link exists; no operational workspace is linked yet.")

    contracts = db.query(models.SubscriptionContract).filter(
        models.SubscriptionContract.pending_organization_id == pending_organization_id
    ).all()
    attempts = db.query(models.PaymentAttempt).filter(
        models.PaymentAttempt.pending_organization_id == pending_organization_id
    ).all()
    subscriptions = db.query(models.PaymentSubscription).filter(
        models.PaymentSubscription.pending_organization_id == pending_organization_id
    ).all()
    provisioning_jobs = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.pending_organization_id == pending_organization_id
    )
    provisioning_job_ids = _ids(provisioning_jobs, models.ProvisioningJob.id)

    _add_count(counts, category="SaaS / onboarding", table="pending_organizations", count=1, disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_branches", count=_count(db.query(models.PendingOrganizationBranch).filter(models.PendingOrganizationBranch.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_academic_setup", count=_count(db.query(models.PendingOrganizationAcademicSetup).filter(models.PendingOrganizationAcademicSetup.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_contacts", count=_count(db.query(models.PendingOrganizationContact).filter(models.PendingOrganizationContact.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_progress", count=_count(db.query(models.PendingOrganizationProgress).filter(models.PendingOrganizationProgress.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_notes", count=_count(db.query(models.PendingOrganizationNote).filter(models.PendingOrganizationNote.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_events", count=_count(db.query(models.PendingOrganizationEvent).filter(models.PendingOrganizationEvent.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="pending_organization_plan_selections", count=_count(db.query(models.PendingOrganizationPlanSelection).filter(models.PendingOrganizationPlanSelection.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="checkout_sessions", count=_count(db.query(models.CheckoutSession).filter(models.CheckoutSession.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="payment_attempts", count=len(attempts), disposition="preserve audit/payment-provider")
    _add_count(counts, category="SaaS / onboarding", table="payment_customers", count=_count(db.query(models.PaymentCustomer).filter(models.PaymentCustomer.pending_organization_id == pending_organization_id)), disposition="preserve audit/payment-provider")
    _add_count(counts, category="SaaS / onboarding", table="payment_subscriptions", count=len(subscriptions), disposition="preserve audit/payment-provider")
    _add_count(counts, category="SaaS / onboarding", table="subscription_contracts", count=len(contracts), disposition="preserve audit/payment-provider")
    _add_count(counts, category="SaaS / onboarding", table="payment_webhooks", count=_payment_webhook_count(db, organization, attempts, subscriptions), disposition="preserve audit/payment-provider")
    _add_count(counts, category="SaaS / onboarding", table="provisioning_jobs", count=len(provisioning_job_ids), disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="provisioning_job_events", count=_count(db.query(models.ProvisioningJobEvent).filter(models.ProvisioningJobEvent.provisioning_job_id.in_(provisioning_job_ids))) if provisioning_job_ids else 0, disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="tenant_provisioning_links", count=1 if tenant_link else 0, disposition="tenant-owned")
    _add_count(counts, category="SaaS / onboarding", table="saas_account_user_links", count=_count(db.query(models.SaaSAccountUserLink).filter(models.SaaSAccountUserLink.pending_organization_id == pending_organization_id)), disposition="tenant-owned")
    _add_count(counts, category="SaaS account", table="saas_accounts", count=1 if owner_account_id else 0, disposition="preserved global/reference")
    _add_count(counts, category="SaaS account", table="saas_auth_identities", count=_count(db.query(models.SaaSAuthIdentity).filter(models.SaaSAuthIdentity.saas_account_id == owner_account_id)) if owner_account_id else 0, disposition="preserved global/reference")
    _add_count(counts, category="SaaS account", table="saas_sessions", count=_count(db.query(models.SaaSSession).filter(models.SaaSSession.saas_account_id == owner_account_id)) if owner_account_id else 0, disposition="preserved global/reference")
    _add_count(counts, category="SaaS account", table="saas_auth_events", count=_count(db.query(models.SaaSAuthEvent).filter(models.SaaSAuthEvent.saas_account_id == owner_account_id)) if owner_account_id else 0, disposition="preserved audit/payment-provider")
    _add_count(counts, category="SaaS account", table="saas_email_verification_tokens", count=_count(db.query(models.SaaSEmailVerificationToken).filter(models.SaaSEmailVerificationToken.saas_account_id == owner_account_id)) if owner_account_id else 0, disposition="preserved audit/payment-provider")
    _add_count(counts, category="SaaS account", table="saas_password_reset_tokens", count=_count(db.query(models.SaaSPasswordResetToken).filter(models.SaaSPasswordResetToken.saas_account_id == owner_account_id)) if owner_account_id else 0, disposition="preserved audit/payment-provider")

    branch_ids: list[int] = []
    academic_year_ids: list[int] = []
    user_pks: list[int] = []
    user_ids: list[str] = []
    teacher_ids: list[int] = []
    planning_section_ids: list[int] = []
    calendar_event_ids: list[int] = []
    observation_ids: list[int] = []
    self_evaluation_ids: list[int] = []
    timetable_setting_ids: list[int] = []

    if school_group_id:
        branch_query = db.query(operational_models.Branch).filter(operational_models.Branch.school_group_id == school_group_id)
        academic_year_query = db.query(operational_models.AcademicYear).filter(operational_models.AcademicYear.school_group_id == school_group_id)
        user_query = db.query(operational_models.User).filter(operational_models.User.school_group_id == school_group_id)
        branch_ids = _ids(branch_query, operational_models.Branch.id)
        academic_year_ids = _ids(academic_year_query, operational_models.AcademicYear.id)
        user_pks = _ids(user_query, operational_models.User.id)
        user_ids = _string_ids(user_query, operational_models.User.user_id)

        teacher_query = db.query(operational_models.Teacher).filter(
            or_(
                operational_models.Teacher.branch_id.in_(branch_ids) if branch_ids else False,
                operational_models.Teacher.academic_year_id.in_(academic_year_ids) if academic_year_ids else False,
            )
        )
        teacher_ids = _ids(teacher_query, operational_models.Teacher.id)

        planning_section_query = db.query(operational_models.PlanningSection).filter(
            or_(
                operational_models.PlanningSection.branch_id.in_(branch_ids) if branch_ids else False,
                operational_models.PlanningSection.academic_year_id.in_(academic_year_ids) if academic_year_ids else False,
            )
        )
        planning_section_ids = _ids(planning_section_query, operational_models.PlanningSection.id)

        calendar_event_query = db.query(operational_models.CalendarEvent).filter(
            or_(
                operational_models.CalendarEvent.branch_id.in_(branch_ids) if branch_ids else False,
                operational_models.CalendarEvent.academic_year_id.in_(academic_year_ids) if academic_year_ids else False,
            )
        )
        calendar_event_ids = _ids(calendar_event_query, operational_models.CalendarEvent.id)

        observation_query = db.query(operational_models.Observation).filter(
            or_(
                operational_models.Observation.branch_id.in_(branch_ids) if branch_ids else False,
                operational_models.Observation.academic_year_id.in_(academic_year_ids) if academic_year_ids else False,
                operational_models.Observation.teacher_id.in_(teacher_ids) if teacher_ids else False,
            )
        )
        observation_ids = _ids(observation_query, operational_models.Observation.id)
        self_evaluation_query = db.query(operational_models.ObservationSelfEvaluation).filter(
            operational_models.ObservationSelfEvaluation.observation_id.in_(observation_ids)
        ) if observation_ids else db.query(operational_models.ObservationSelfEvaluation).filter(False)
        self_evaluation_ids = _ids(self_evaluation_query, operational_models.ObservationSelfEvaluation.id)

        timetable_setting_query = db.query(operational_models.TimetableSetting).filter(
            or_(
                operational_models.TimetableSetting.branch_id.in_(branch_ids) if branch_ids else False,
                operational_models.TimetableSetting.academic_year_id.in_(academic_year_ids) if academic_year_ids else False,
            )
        )
        timetable_setting_ids = _ids(timetable_setting_query, operational_models.TimetableSetting.id)

        _add_count(counts, category="Operational tenant", table="school_groups", count=1 if school_group else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="tenant_profiles", count=_count(db.query(operational_models.TenantProfile).filter(operational_models.TenantProfile.school_group_id == school_group_id)), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="branches", count=len(branch_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="academic_years", count=len(academic_year_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="users", count=len(user_pks), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="role_permissions", count=_count(db.query(operational_models.RolePermission).filter(operational_models.RolePermission.school_group_id == school_group_id)), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="school_group_logos", count=_count(db.query(operational_models.SchoolGroupLogo).filter(operational_models.SchoolGroupLogo.school_group_id == school_group_id)), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="branch_logos", count=_count(db.query(operational_models.BranchLogo).filter(operational_models.BranchLogo.branch_id.in_(branch_ids))) if branch_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="system_notifications", count=_count(db.query(operational_models.SystemNotification).filter(operational_models.SystemNotification.school_group_id == school_group_id)), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="visual_design_settings", count=_count(db.query(operational_models.VisualDesignSetting).filter(operational_models.VisualDesignSetting.school_group_id == school_group_id)), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="calendar_event_types", count=_count(db.query(operational_models.CalendarEventType).filter(or_(operational_models.CalendarEventType.branch_id.in_(branch_ids) if branch_ids else False, operational_models.CalendarEventType.academic_year_id.in_(academic_year_ids) if academic_year_ids else False))), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="calendar_events", count=len(calendar_event_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="calendar_event_assignments", count=_count(db.query(operational_models.CalendarEventAssignment).filter(or_(operational_models.CalendarEventAssignment.calendar_event_id.in_(calendar_event_ids) if calendar_event_ids else False, operational_models.CalendarEventAssignment.teacher_id.in_(teacher_ids) if teacher_ids else False, operational_models.CalendarEventAssignment.user_id.in_(user_pks) if user_pks else False))), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="calendar_event_grade_targets", count=_count(db.query(operational_models.CalendarEventGradeTarget).filter(operational_models.CalendarEventGradeTarget.calendar_event_id.in_(calendar_event_ids))) if calendar_event_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="calendar_event_section_targets", count=_count(db.query(operational_models.CalendarEventSectionTarget).filter(or_(operational_models.CalendarEventSectionTarget.calendar_event_id.in_(calendar_event_ids) if calendar_event_ids else False, operational_models.CalendarEventSectionTarget.section_id.in_(planning_section_ids) if planning_section_ids else False))), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="calendar_event_notifications", count=_count(db.query(operational_models.CalendarEventNotification).filter(operational_models.CalendarEventNotification.calendar_event_id.in_(calendar_event_ids))) if calendar_event_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="subjects", count=_count(db.query(operational_models.Subject).filter(or_(operational_models.Subject.branch_id.in_(branch_ids) if branch_ids else False, operational_models.Subject.academic_year_id.in_(academic_year_ids) if academic_year_ids else False))), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="teachers", count=len(teacher_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="teacher_subject_allocations", count=_count(db.query(operational_models.TeacherSubjectAllocation).filter(operational_models.TeacherSubjectAllocation.teacher_id.in_(teacher_ids))) if teacher_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="teacher_qualification_selections", count=_count(db.query(operational_models.TeacherQualificationSelection).filter(operational_models.TeacherQualificationSelection.teacher_id.in_(teacher_ids))) if teacher_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="teacher_section_assignments", count=_count(db.query(operational_models.TeacherSectionAssignment).filter(or_(operational_models.TeacherSectionAssignment.teacher_id.in_(teacher_ids) if teacher_ids else False, operational_models.TeacherSectionAssignment.planning_section_id.in_(planning_section_ids) if planning_section_ids else False))), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="observations", count=len(observation_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="observation_scores", count=_count(db.query(operational_models.ObservationScore).filter(operational_models.ObservationScore.observation_id.in_(observation_ids))) if observation_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="observation_self_evaluations", count=len(self_evaluation_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="observation_self_evaluation_scores", count=_count(db.query(operational_models.ObservationSelfEvaluationScore).filter(operational_models.ObservationSelfEvaluationScore.self_evaluation_id.in_(self_evaluation_ids))) if self_evaluation_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="planning_sections", count=len(planning_section_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="timetable_settings", count=len(timetable_setting_ids), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="timetable_non_teaching_blocks", count=_count(db.query(operational_models.TimetableNonTeachingBlock).filter(operational_models.TimetableNonTeachingBlock.timetable_setting_id.in_(timetable_setting_ids))) if timetable_setting_ids else 0, disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="timetable_entries", count=_count(db.query(operational_models.TimetableEntry).filter(or_(operational_models.TimetableEntry.branch_id.in_(branch_ids) if branch_ids else False, operational_models.TimetableEntry.academic_year_id.in_(academic_year_ids) if academic_year_ids else False, operational_models.TimetableEntry.planning_section_id.in_(planning_section_ids) if planning_section_ids else False, operational_models.TimetableEntry.teacher_id.in_(teacher_ids) if teacher_ids else False))), disposition="tenant-owned")
        _add_count(counts, category="Operational tenant", table="hiring_plan_drafts", count=_count(db.query(operational_models.HiringPlanDraft).filter(or_(operational_models.HiringPlanDraft.branch_id.in_(branch_ids) if branch_ids else False, operational_models.HiringPlanDraft.academic_year_id.in_(academic_year_ids) if academic_year_ids else False, operational_models.HiringPlanDraft.user_id.in_(user_pks) if user_pks else False))), disposition="tenant-owned")
    else:
        _add_count(counts, category="Operational tenant", table="school_groups", count=0, disposition="tenant-owned")

    preserved_reference = (
        "subscription_plans",
        "subscription_plan_prices",
        "currency_profiles",
        "country_currency_map",
        "observation_criteria",
        "qualification_options",
        "system_design_settings",
    )
    for table_name in preserved_reference:
        _add_count(counts, category="Preserved global/reference data", table=table_name, count=0, disposition="preserved global/reference")

    if school_group_id:
        contract_school_group_ids = {
            int(getattr(contract, "school_group_id", 0) or 0)
            for contract in contracts
            if getattr(contract, "school_group_id", None)
        }
        if contract_school_group_ids and contract_school_group_ids != {school_group_id}:
            warnings.append("Subscription contracts reference a different SchoolGroup than the tenant provisioning link.")
        linked_school_group_ids = {
            int(getattr(link, "school_group_id", 0) or 0)
            for link in db.query(models.SaaSAccountUserLink).filter(
                models.SaaSAccountUserLink.pending_organization_id == pending_organization_id
            ).all()
            if getattr(link, "school_group_id", None)
        }
        if linked_school_group_ids and linked_school_group_ids != {school_group_id}:
            warnings.append("SaaS account user links reference a different SchoolGroup than the tenant provisioning link.")

    total_linked_records = sum(row.count for row in counts)
    safe_for_future_reset = not warnings and bool(tenant_link and school_group)
    return {
        "organization_name": str(getattr(organization, "organization_name", "") or ""),
        "organization_uuid": organization_uuid,
        "billing_status": str(getattr(organization, "billing_status", "") or ""),
        "payment_status": str(getattr(organization, "payment_status", "") or ""),
        "subscription_status": str(getattr(contracts[-1], "contract_status", "") or "") if contracts else "none",
        "provisioning_status": str(getattr(tenant_link, "tenant_status", "") or "not_linked") if tenant_link else "not_linked",
        "school_group_id": school_group_id,
        "workspace_name": str(getattr(school_group, "name", "") or "") if school_group else "",
        "counts": counts,
        "warnings": warnings,
        "safe_for_future_reset": safe_for_future_reset,
        "status_label": "Safe to prepare for deletion" if safe_for_future_reset else "Manual review required",
        "total_linked_records": total_linked_records,
        "no_data_changed": True,
    }
