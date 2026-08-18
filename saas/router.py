from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from datetime import datetime, timezone
import json
import logging
import os
import re
import uuid
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, quote_plus, urlsplit

import auth
import audit
import models as operational_models
import permission_registry
from dependencies import get_db
import email_service
import location_service
from demo_workflow import DemoRequestStatus
from saas import ai_feature_registry, billing_history_service, billing_identity_service, billing_service, branch_pricing_quote_service, commercial_authority_service, commercial_portal_service, commercial_state_service, customer_journey_service, demo_access_service, demo_conversion_service, demo_eligibility_maintenance_service, demo_email_service, demo_feature_registry, demo_lifecycle_service, demo_notification_service, demo_operations_service, demo_provisioning_service, demo_request_service, draft_lifecycle_service, existing_workspace_conversion_service, existing_workspace_paid_activation_service, models, oauth, orphaned_test_account_service, paddle_client, payment_service, pricing_service, promo_code_service, promo_redemption_service, provisioning_service, service, subscription_cancellation_service, subscription_change_service, subscription_plan_change_service, subscription_portal_service, test_account_deletion_service, workspace_analysis_service, workspace_deletion_service
from workspace_classification import WorkspaceClassification, WorkspaceLifecycleStatus


logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/saas", tags=["saas"])
admin_router = APIRouter(prefix="/saas-admin", tags=["saas-admin"])


def _dispatch_demo_email_best_effort(db: Session, demo_request_id: int) -> None:
    try:
        factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
        demo_email_service.dispatch_pending(
            factory, limit=10, demo_request_id=demo_request_id
        )
    except Exception:
        logger.warning(
            "Demo email dispatch deferred demo_request_id=%s",
            demo_request_id,
            exc_info=True,
        )


CUSTOMER_STATUS_LABELS = {
    "not_started": "Not started",
    "pending_verification": "Email verification required",
    "active": "Active",
    "draft": "School Workspace Setup in progress",
    "in_progress": "School Workspace Setup in progress",
    "organization_in_progress": "School Workspace Setup in progress",
    "ready_for_checkout": "Subscription Setup ready",
    "under_review": "Setup under review",
    "changes_requested": "Changes requested",
    "rejected": "Setup not approved",
    "plan_selected": "Subscription plan selected",
    "checkout_ready": "Secure Payment ready",
    "checkout_initiated": "Secure Payment started",
    "checkout_started": "Secure Payment started",
    "payment_processing": "Payment processing",
    "payment_confirmed": "Payment confirmed",
    "ready_for_provisioning": "Workspace Activation in progress",
    "provisioning_started": "Workspace Activation in progress",
    "provisioning_retrying": "Workspace Activation in progress",
    "provisioning_completed": "Workspace active",
    "provisioning_failed": "Workspace Activation needs attention",
    "tenant_active": "Workspace active",
    "activation_required": "Activation required",
    "payment_failed": "Payment needs attention",
    "payment_cancelled": "Payment cancelled",
    "payment_refunded": "Payment refunded",
    "organization": "Organization Profile",
    "branches": "Branch Setup",
    "academic_setup": "Academic Setup",
    "contacts": "Primary Contact",
    "review": "Review",
    "pending": "Pending",
    "paid": "Paid",
    "failed": "Needs attention",
    "cancelled": "Cancelled",
    "refunded": "Refunded",
    "ready": "Ready",
    "started": "Started",
    "completed": "Complete",
    "retrying": "In progress",
}

SIGN_IN_METHOD_LABELS = {
    "password": "Email and password",
    "google": "Google",
    "microsoft": "Microsoft",
}


def _display_label(value: str | None, fallback: str = "Not available") -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return fallback
    mapped = CUSTOMER_STATUS_LABELS.get(cleaned.lower())
    if mapped:
        return mapped
    return cleaned.replace("_", " ").strip().capitalize()


def _sign_in_method_label(value: str | None) -> str:
    cleaned = str(value or "").strip().lower()
    return SIGN_IN_METHOD_LABELS.get(cleaned, _display_label(cleaned, "Sign-in method"))


templates.env.globals["customer_status_label"] = _display_label
templates.env.globals["sign_in_method_label"] = _sign_in_method_label


SAFE_LOGIN_CONTINUATION_PATHS = {
    "/saas/account",
    "/saas/account/billing",
    "/saas/account/profile",
    "/saas/account/security",
    "/saas/account/sessions",
    "/saas/expired-access",
    "/saas/onboarding",
    "/saas/plans",
    "/saas/subscription",
    "/saas/subscription/branches",
    "/saas/subscription/cancel",
}
SAFE_LOGIN_CONTINUATION_PATTERNS = (
    re.compile(r"^/saas/demo-requests/[^/]+$"),
    re.compile(
        r"^/saas/onboarding/[^/]+/"
        r"(resume|organization|branches|academic_setup|contacts|review|"
        r"commercial-choice|plan|checkout|billing-status)$"
    ),
)
OAUTH_NEXT_COOKIE = "tis_saas_oauth_next"


def _safe_next(next_path: str | None) -> str:
    cleaned = str(next_path or "").strip()
    if not cleaned or "\\" in cleaned:
        return "/saas/account"
    parsed = urlsplit(cleaned)
    path = parsed.path
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or not path.startswith("/saas")
        or "//" in path
        or ".." in path.split("/")
    ):
        return "/saas/account"
    if path in SAFE_LOGIN_CONTINUATION_PATHS or any(
        pattern.fullmatch(path)
        for pattern in SAFE_LOGIN_CONTINUATION_PATTERNS
    ):
        return cleaned
    return "/saas/account"


def _post_auth_destination(db: Session, account, next_path: str | None = None) -> str:
    default_destination = customer_journey_service.login_destination(db, account)
    requested = str(next_path or "").strip()
    safe_next = _safe_next(requested)
    if not requested or safe_next != requested:
        return default_destination
    parsed = urlsplit(safe_next)
    if parsed.path != "/saas/subscription":
        return default_destination
    params = parse_qs(parsed.query, keep_blank_values=True)
    if set(params) - {"organization_uuid"} or any(len(values) != 1 for values in params.values()):
        return default_destination
    requested_uuid = str((params.get("organization_uuid") or [""])[0]).strip()
    accesses = customer_journey_service.list_organization_account_accesses(db, account)
    billing_accesses = tuple(item for item in accesses if item.can_manage_billing)
    if requested_uuid:
        selected = next(
            (
                item
                for item in billing_accesses
                if item.organization_uuid == requested_uuid
            ),
            None,
        )
        return safe_next if selected is not None else default_destination
    return safe_next if len(billing_accesses) == 1 else default_destination


def _test_deletion_log_context(current_user, organization, *, deletion_mode: str) -> dict[str, object]:
    return {
        "deletion_mode": deletion_mode,
        "organization_id": int(getattr(organization, "id", 0) or 0),
        "organization_uuid": str(getattr(organization, "organization_uuid", "") or ""),
        "workspace_id": 0,
        "account_id": int(getattr(organization, "owner_saas_account_id", 0) or 0),
        "organization_name": str(getattr(organization, "organization_name", "") or ""),
        "normalized_domain": service.normalize_organization_domain(
            str(getattr(organization, "primary_domain", "") or getattr(organization, "website", "") or "")
        ),
        "authenticated_platform_owner": str(getattr(current_user, "user_id", "") or ""),
    }


def _log_test_deletion(event: str, context: dict[str, object], **details) -> None:
    fields = {**context, **details}
    logger.info(
        "test_deletion event=%s %s",
        event,
        " ".join(f"{key}={value}" for key, value in fields.items()),
    )


def _constraint_name(exc: SQLAlchemyError) -> str:
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    return str(
        getattr(diagnostic, "constraint_name", None)
        or getattr(original, "constraint_name", None)
        or "unavailable"
    )


def _current_account(request: Request, db: Session):
    return service.get_current_account(db, request)


def _require_account(request: Request, db: Session):
    account = _current_account(request, db)
    if not account:
        raise HTTPException(status_code=401, detail="Please sign in to your TIS Account.")
    session_row = service.get_session_from_request(db, request)
    return account, session_row


def _account_needs_verification(account) -> bool:
    status = str(getattr(account, "status", "") or "").strip().lower()
    return status == "pending_verification" or not getattr(account, "email_verified_at", None)


def _verification_required_redirect(email: str = ""):
    target = "/saas/auth/verification-required"
    if email:
        target += "?email=" + quote_plus(str(email or ""))
    return RedirectResponse(target, status_code=302)


def _login_required_redirect(next_path: str = ""):
    target = "/saas/login?notice=" + quote_plus("Please sign in to your TIS Account.")
    if next_path:
        target += "&next_path=" + quote_plus(_safe_next(next_path))
    return RedirectResponse(target, status_code=302)


def _require_verified_account(request: Request, db: Session, *, next_path: str = ""):
    account = _current_account(request, db)
    if not account:
        return None, None, _login_required_redirect(next_path)
    session_row = service.get_session_from_request(db, request)
    if _account_needs_verification(account):
        return None, None, _verification_required_redirect(str(getattr(account, "email", "") or ""))
    customer_journey_service.apply_selected_organization_context(
        db,
        account,
        str(request.cookies.get(service.SAAS_ORGANIZATION_COOKIE) or ""),
    )
    return account, session_row, None


def _require_platform_owner(request: Request, db: Session):
    current_user = auth.get_current_user(request, db)
    if not current_user or not auth.is_platform_owner(current_user):
        raise HTTPException(status_code=403, detail="Platform Owner access is required.")
    return current_user


def _require_workspace_analyzer(request: Request, db: Session):
    current_user = auth.get_current_user(request, db)
    if not current_user or not (auth.is_platform_owner(current_user) or auth.is_platform_developer(current_user)):
        raise HTTPException(status_code=403, detail="Platform Owner or Developer access is required.")
    return current_user


def _require_promo_permission(request: Request, db: Session, permission_key: str):
    current_user = auth.get_current_user(request, db)
    if (
        not current_user
        or not auth.is_platform_user(current_user)
        or not auth.has_permission(db, current_user, permission_key)
    ):
        raise HTTPException(status_code=403, detail="Platform promo access is required.")
    return current_user


def _render(request: Request, template_name: str, context: dict, status_code: int = 200):
    merged = {"request": request, **context}
    return templates.TemplateResponse(request, template_name, merged, status_code=status_code)


def _organization_account_shell_context(request: Request, db: Session, account) -> dict | None:
    organization_uuid = str(
        request.cookies.get(service.SAAS_ORGANIZATION_COOKIE) or ""
    ).strip()
    _accesses, selected = customer_journey_service.select_organization_account_access(
        db,
        account,
        organization_uuid=organization_uuid,
    )
    if selected is None:
        _accesses, selected = customer_journey_service.select_organization_account_access(
            db,
            account,
        )
    return {"access": selected} if selected is not None else None


def _existing_workspace_activation_access(db: Session, account, workspace_uuid: str):
    _accesses, selected = customer_journey_service.select_organization_account_access(
        db,
        account,
        organization_uuid=str(workspace_uuid or "").strip(),
    )
    if selected is None or not selected.is_owner or not selected.can_manage_billing:
        raise HTTPException(status_code=404, detail="Workspace activation is unavailable.")
    if str(selected.school_group.workspace_uuid or "").strip() != str(
        workspace_uuid or ""
    ).strip():
        raise HTTPException(status_code=404, detail="Workspace activation is unavailable.")
    return selected


def _usd_amount(amount_minor: int | None) -> str:
    return f"USD {int(amount_minor or 0) / 100:,.2f}"


def _paddle_client_environment() -> str:
    cleaned = str(os.environ.get("PADDLE_ENVIRONMENT") or "").strip().lower()
    return cleaned if cleaned in {"sandbox", "production"} else "production"


def _test_account_reset_enabled() -> bool:
    feature_flag = str(os.environ.get("TIS_ENABLE_TEST_ACCOUNT_RESET") or "").strip().lower()
    return _paddle_client_environment() == "sandbox" or feature_flag in {"1", "true", "yes", "on"}


LAUNCHABLE_BILLING_STATUSES = {
    payment_service.CHECKOUT_READY,
    payment_service.CHECKOUT_STARTED,
    payment_service.PAYMENT_PROCESSING,
    payment_service.PAYMENT_FAILED,
    payment_service.PAYMENT_CANCELLED,
}
PREPARE_BEFORE_LAUNCH_BILLING_STATUSES = {
    billing_service.NOT_STARTED,
    billing_service.PLAN_SELECTED,
    billing_service.CHECKOUT_INITIATED,
    service.READY_FOR_CHECKOUT_STATUS,
}


def _redirect_error(path: str, message: str):
    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}error={quote_plus(str(message or ''))}", status_code=302)


@router.get("/payment", response_class=HTMLResponse)
def paddle_payment_page(request: Request, db: Session = Depends(get_db)):
    transaction_id = str(request.query_params.get("_ptxn") or "").strip()
    launcher_error = ""
    try:
        transaction_id = payment_service.validate_payment_launcher_transaction(
            db, transaction_id
        )
    except (ValueError, paddle_client.PaddleAPIError):
        logger.warning(
            "paddle_checkout_launcher_rejected transaction_id_present=%s",
            bool(transaction_id),
            exc_info=True,
        )
        transaction_id = ""
        launcher_error = (
            "We couldn’t open secure payment right now. "
            "Please try again or contact the TIS team."
        )
    return _render(
        request,
        "saas/payment.html",
        {
            "title": "Secure Payment | TIS Platform",
            "paddle_client_token": str(os.environ.get("PADDLE_CLIENT_TOKEN") or "").strip(),
            "paddle_environment": _paddle_client_environment(),
            "paddle_transaction_id": transaction_id,
            "launcher_error": launcher_error,
        },
    )


def _onboarding_context(db: Session, account, organization):
    summary = service.build_pending_dashboard_summary(db, account)
    progress = summary["progress"] if summary else service.get_or_create_pending_progress(db, organization)
    academic_setup = service.get_or_create_academic_setup(db, organization)
    primary_contact = service.get_primary_contact(db, organization)
    branches = service.list_pending_branches(db, organization)
    branch_capacity_totals = service.pending_branch_capacity_totals(branches)
    onboarding_step_access = service.build_onboarding_step_access(db, organization)
    return {
        "account": account,
        "organization": organization,
        "progress": progress,
        "academic_setup": academic_setup,
        "primary_contact": primary_contact,
        "branches": branches,
        "branch_capacity_totals": branch_capacity_totals,
        "journey_card": summary,
        "onboarding_step_access": onboarding_step_access,
        "timezone_options": service.list_iana_timezones(),
    }


def _render_onboarding_step(
    request: Request,
    db: Session,
    account,
    organization,
    template_name: str,
    step_key: str,
    *,
    error: str = "",
    status_code: int = 200,
    extra_context: dict | None = None,
):
    context = _onboarding_context(db, account, organization)
    missing_requirements = service.get_onboarding_missing_requirements(db, organization) if step_key == "review" else []
    context.update({
        "account": account,
        "error": error,
        "step_key": step_key,
        "setup_console": _onboarding_setup_console(db, account, step_key, organization),
        "form_data": {},
        "form_branches": [],
        "missing_requirements": missing_requirements,
    })
    if extra_context:
        context.update(extra_context)
    return _render(request, template_name, context, status_code=status_code)


ONBOARDING_STEP_CONSOLE = {
    "organization": {
        "title": "Organization Profile",
        "subtitle": "Add the core details that identify your school workspace.",
        "status": "Start with the organization profile. Save and continue when the basics are ready.",
        "label": "Save and continue",
        "form_id": "organization-form",
        "help": "This step captures the official organization profile, brand logo, location, and estimated size.",
    },
    "branches": {
        "title": "Branch Setup",
        "subtitle": "Add the campuses or branches that should be included in this workspace.",
        "status": "Add at least one branch, then continue to Academic Setup.",
        "label": "Save and continue",
        "form_id": "branches-form",
        "help": "Branches help TIS prepare the right school structure before activation.",
    },
    "academic_setup": {
        "title": "Academic Setup",
        "subtitle": "Confirm the first academic year and launch preferences.",
        "status": "Set the academic year that TIS should prepare first.",
        "label": "Save and continue",
        "form_id": "academic-setup-form",
        "help": "This gives the workspace a starting academic structure for activation.",
    },
    "contacts": {
        "title": "Primary Contact",
        "subtitle": "Confirm who should be contacted about this workspace setup.",
        "status": "Add the primary contact, then continue to final review.",
        "label": "Save and continue",
        "form_id": "contacts-form",
        "help": "Use a reliable school contact who can answer setup or activation questions.",
    },
    "review": {
        "title": "Review School Workspace Setup",
        "subtitle": "Check the setup summary before moving to Subscription Selection.",
        "status": "Review the information below. Submit when the setup is ready to continue.",
        "label": "Submit setup",
        "form_id": "review-submit-form",
        "help": "After submission, you will choose a subscription and continue toward Secure Payment.",
    },
}


def _onboarding_setup_console(db: Session, account, step_key: str, organization=None) -> dict:
    console = service.build_setup_console_context(db, account)
    config = ONBOARDING_STEP_CONSOLE.get(step_key, ONBOARDING_STEP_CONSOLE["organization"])
    console.update(
        {
            "title": config["title"],
            "subtitle": config["subtitle"],
            "status_banner": config["status"],
            "current_step": "school_workspace_setup" if step_key != "review" else "review_confirmation",
            "primary_action": {
                "label": config["label"],
                "method": "form",
                "form_id": config["form_id"],
                "name": "save_action",
                "value": "continue",
            },
            "help_title": "What should I do next?",
            "help_text": config["help"],
        }
    )
    if organization is not None:
        console["setup_edit_steps"] = service.build_setup_edit_navigation_steps(
            db,
            organization,
            current_key=step_key,
        )
    for step in console.get("steps", []):
        if step.get("key") == console["current_step"] and step.get("state") != "complete":
            step["state"] = "current"
    return console


def _locked_onboarding_step_redirect(db: Session, organization, requested_step: str):
    access = service.build_onboarding_step_access(db, organization, current_step=requested_step)
    step = access["steps_by_key"].get(requested_step)
    if step and not step["allowed"]:
        return RedirectResponse(access["resume_url"], status_code=302)
    return None


def _locked_pre_payment_edit_redirect(organization):
    if service.is_setup_editing_locked(organization):
        return RedirectResponse(
            f"/saas/onboarding/{organization.organization_uuid}/billing-status",
            status_code=302,
        )
    return None


def _closed_initial_checkout_redirect(db: Session, organization):
    if not service.initial_checkout_is_closed(db, organization):
        return None
    return RedirectResponse(
        "/saas/subscription?notice="
        + quote_plus("Initial checkout is complete. Manage future subscription changes here."),
        status_code=302,
    )


def _payment_setup_console(
    db: Session,
    account,
    page_key: str,
    *,
    organization=None,
    checkout_summary=None,
    onboarding_summary=None,
) -> dict:
    console = service.build_setup_console_context(db, account)
    summary = onboarding_summary or service.build_pending_dashboard_summary(db, account)
    organization = organization or (summary["organization"] if summary else None)
    org_uuid = str(getattr(organization, "organization_uuid", "") or "")
    workspace_name = str(getattr(organization, "organization_name", "") or "").strip() or "School Workspace"

    def action(label: str, url: str, method: str = "get", form_id: str = "") -> dict:
        data = {"label": label, "url": url, "method": method}
        if form_id:
            data["form_id"] = form_id
        return data

    config = {
        "plan": {
            "title": "Choose your subscription",
            "subtitle": f"Select the plan and billing interval for {workspace_name}.",
            "status": "Next step: save your subscription selection to continue to Secure Payment.",
            "current": "subscription_selection",
            "primary": action("Save plan and continue", "", "form", "plan-selection-form"),
            "help": "Your subscription choice prepares Secure Payment. Workspace Activation begins only after payment is confirmed.",
        },
        "checkout": {
            "title": "Secure Payment summary",
            "subtitle": f"Review the selected subscription for {workspace_name}.",
            "status": "Next step: prepare Secure Payment.",
            "current": "secure_payment",
            "primary": action("Prepare Secure Payment", "", "form", "checkout-start-form"),
            "help": "Secure Payment opens after the payment session is prepared. Browser redirects alone do not activate the workspace.",
        },
        "return": {
            "title": "Payment status",
            "subtitle": "Your browser returned from Secure Payment.",
            "status": "Browser return received. Payment confirmation is finalized only after secure verification is processed.",
            "current": "secure_payment",
            "primary": action("View Subscription Status", "/saas/account/billing"),
            "help": "Keep this page as a status checkpoint. If payment is confirmed, Workspace Activation will continue automatically.",
        },
        "cancel": {
            "title": "Payment cancelled",
            "subtitle": "The payment window was closed before confirmation.",
            "status": "Your setup is still saved. You can return to Secure Payment when ready.",
            "current": "secure_payment",
            "primary": action("Return to Secure Payment", f"/saas/onboarding/{org_uuid}/checkout" if org_uuid else "/saas/account/billing"),
            "help": "No workspace activation starts until payment is confirmed. You can safely resume from the Secure Payment summary.",
        },
        "account_billing": {
            "title": "Subscription and activation status",
            "subtitle": "Track Secure Payment, Subscription Setup, and Workspace Activation.",
            "status": "Use this page to understand what happens next before TIS Platform access becomes available.",
            "current": console.get("current_step", "secure_payment"),
            "primary": console.get("primary_action", action("View Account Status", "/saas/account")),
            "help": "TIS Platform access becomes available after Workspace Activation is complete.",
        },
        "billing_status": {
            "title": "Workspace Activation status",
            "subtitle": f"Track subscription and activation progress for {workspace_name}.",
            "status": "Payment confirmation and Workspace Activation status are shown here with customer-safe labels.",
            "current": console.get("current_step", "secure_payment"),
            "primary": action("View Subscription Details", "/saas/account/billing"),
            "help": "Browser redirects do not activate the workspace by themselves. Activation follows secure payment confirmation.",
        },
    }[page_key]

    if page_key == "checkout":
        has_selection = bool(checkout_summary and checkout_summary.get("selection") and checkout_summary.get("plan"))
        quote = checkout_summary.get("quote") if checkout_summary else None
        if not has_selection:
            config["status"] = "Select a subscription before continuing to Secure Payment."
            config["primary"] = action("Choose Subscription", f"/saas/onboarding/{org_uuid}/plan")
        elif not quote or not quote.is_ready:
            config["status"] = "Complete the subscription requirements before continuing to Secure Payment."
            config["primary"] = action("Review Subscription", f"/saas/onboarding/{org_uuid}/plan")
        else:
            config["status"] = "Secure Payment is ready to open."
            config["primary"] = action("Continue to Secure Payment", "", "form", "checkout-launch-form")

    console.update(
        {
            "title": config["title"],
            "subtitle": config["subtitle"],
            "status_banner": config["status"],
            "current_step": config["current"],
            "primary_action": config["primary"],
            "help_title": "What should I do next?",
            "help_text": config["help"],
        }
    )
    if organization is not None:
        current_adjustment_key = "subscription_selection" if page_key == "plan" else ""
        console["setup_edit_steps"] = service.build_setup_edit_navigation_steps(
            db,
            organization,
            current_key=current_adjustment_key,
        )
    for step in console.get("steps", []):
        if step.get("key") == console["current_step"] and step.get("state") != "complete":
            step["state"] = "current"
    return console


def _plan_context(db: Session, account, organization):
    summary = service.build_pending_dashboard_summary(db, account)
    checkout_summary = billing_service.build_checkout_summary(db, organization)
    payment_attempt = payment_service.get_current_payment_attempt(db, organization)
    payment_customer = payment_service.get_payment_customer(db, organization)
    payment_subscription = payment_service.get_payment_subscription(db, organization)
    branch_count = service.count_billable_pending_branches(db, organization)
    (
        _capacity_branch_count,
        system_user_count,
        teacher_count,
    ) = branch_pricing_quote_service.authoritative_capacity_counts(
        db, organization
    )
    plan_catalog = pricing_service.build_plan_catalog(
        db,
        country_code=str(getattr(organization, "country_code", "") or ""),
    )
    minimum_eligible_plan = next(
        (
            plan_view.plan.plan_code
            for plan_view in plan_catalog
            if branch_pricing_quote_service.evaluate_plan_capacity(
                plan_view.plan,
                active_branch_count=branch_count,
                active_system_user_count=system_user_count,
                active_teacher_count=teacher_count,
            ).eligible
        ),
        None,
    )
    minimum_eligible_plan_name = next(
        (
            plan_view.plan.plan_name
            for plan_view in plan_catalog
            if plan_view.plan.plan_code == minimum_eligible_plan
        ),
        None,
    )
    plan_options = []
    for plan_view in plan_catalog:
        capacity = branch_pricing_quote_service.evaluate_plan_capacity(
            plan_view.plan,
            active_branch_count=branch_count,
            active_system_user_count=system_user_count,
            active_teacher_count=teacher_count,
            minimum_eligible_plan=minimum_eligible_plan,
        )
        plan_options.append({
            "plan_view": plan_view,
            "eligible": capacity.eligible,
            "ineligible_reason": capacity.reason,
            "branch_capacity": capacity.branch_capacity,
            "active_branch_count": capacity.active_branch_count,
            "system_user_capacity": capacity.max_system_users,
            "teacher_capacity": capacity.max_teachers,
            "active_system_user_count": capacity.active_system_user_count,
            "active_teacher_count": capacity.active_teacher_count,
            "branch_eligible": capacity.branch_eligible,
            "system_user_eligible": capacity.system_user_eligible,
            "teacher_eligible": capacity.teacher_eligible,
            "required_plan_or_custom_state": capacity.required_plan_or_custom_state,
            "recommended": (
                capacity.eligible
                and plan_view.plan.plan_code == minimum_eligible_plan
            ),
            "monthly_amount_minor": int(plan_view.monthly.base_amount_minor or 0),
            "monthly_formatted": (
                f"USD {int(plan_view.monthly.base_amount_minor or 0) / 100:,.2f}"
            ),
            "annual_amount_minor": int(plan_view.annual.base_amount_minor or 0),
            "annual_formatted": (
                f"USD {int(plan_view.annual.base_amount_minor or 0) / 100:,.2f}"
            ),
            "annual_savings_percent": int(
                plan_view.annual.annual_savings_percent or 0
            ),
        })
    return {
        "account": account,
        "organization": organization,
        "journey_card": summary,
        "plan_catalog": plan_catalog,
        "plan_options": plan_options,
        "self_service_checkout_blocked": bool(plan_options) and not any(
            option["eligible"] for option in plan_options
        ),
        "minimum_eligible_plan": minimum_eligible_plan,
        "minimum_eligible_plan_name": minimum_eligible_plan_name,
        "billable_branch_count": branch_count,
        "active_system_user_count": system_user_count,
        "active_teacher_count": teacher_count,
        "current_plan_selection": checkout_summary["selection"] if checkout_summary else None,
        "checkout_summary": checkout_summary,
        "current_payment_attempt": payment_attempt,
        "current_payment_customer": payment_customer,
        "current_payment_subscription": payment_subscription,
    }


def _resolve_optional_location(
    *,
    country_code: str,
    region_id: str,
    region_manual: str,
    city_id: str,
    city_manual: str,
):
    has_location_picker_input = any(
        str(value or "").strip()
        for value in (region_id, region_manual, city_id, city_manual)
    )
    if not has_location_picker_input:
        return None
    return location_service.resolve_location(
        country_code=country_code,
        region_id=region_id,
        region_manual=region_manual,
        city_id=city_id,
        city_manual=city_manual,
        require_city=False,
    )


@router.get("/locations/countries")
def saas_location_countries(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    return JSONResponse(
        {"items": location_service.list_countries()},
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/locations/regions")
def saas_location_regions(
    request: Request,
    country_code: str = Query(..., min_length=2, max_length=2),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        items = location_service.list_regions(country_code)
    except location_service.LocationValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(
        {"items": items},
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/locations/cities")
def saas_location_cities(
    request: Request,
    country_code: str = Query(..., min_length=2, max_length=2),
    region_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        items = location_service.list_cities(country_code, region_id)
    except location_service.LocationValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(
        {"items": items},
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("", response_class=HTMLResponse)
def saas_root(request: Request, db: Session = Depends(get_db)):
    account = _current_account(request, db)
    return RedirectResponse(
        customer_journey_service.login_destination(db, account)
        if account
        else "/saas/login",
        status_code=302,
    )


@router.get("/login", response_class=HTMLResponse, name="saas_login_page")
def login_page(
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    email: str = Query(""),
    next_path: str = Query(""),
    db: Session = Depends(get_db),
):
    current_account = _current_account(request, db)
    if current_account:
        return RedirectResponse(
            _post_auth_destination(db, current_account, next_path),
            status_code=302,
        )
    return _render(
        request,
        "saas/login.html",
        {
            "error": error,
            "notice": notice,
            "email": email,
            "next_path": _safe_next(next_path) if next_path else "",
            "google_enabled": oauth.is_provider_configured("google"),
            "microsoft_enabled": oauth.is_provider_configured("microsoft"),
        },
    )


@router.get("/auth/login")
def login_get_redirect(
    email: str = Query(""),
    next_path: str = Query(""),
):
    query_parts = []
    if email:
        query_parts.append("email=" + quote_plus(str(email or "")))
    if next_path:
        query_parts.append("next_path=" + quote_plus(_safe_next(next_path)))
    suffix = "?" + "&".join(query_parts) if query_parts else ""
    return RedirectResponse("/saas/login" + suffix, status_code=302)


@router.get("/auth/forgot-password", response_class=HTMLResponse)
def forgot_password_page(
    request: Request,
    email: str = Query(""),
    next_path: str = Query(""),
    notice: str = Query(""),
    error: str = Query(""),
):
    return _render(
        request,
        "saas/forgot_password.html",
        {"email": email, "notice": notice, "error": error},
    )


@router.post("/auth/forgot-password")
def request_password_reset(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    neutral_notice = "If a TIS Account exists for this email, a password reset link has been sent."
    if service.is_rate_limited(
        db,
        event_type="password_reset_sent",
        request=request,
        max_attempts=service.PASSWORD_RESET_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/auth/forgot-password?notice=" + quote_plus(neutral_notice),
            status_code=302,
        )
    account = service.get_account_by_email(db, email)
    if account and getattr(account, "password_hash", None):
        try:
            service.send_password_reset_email(db, account, request)
            db.commit()
        except email_service.EmailDeliveryError:
            db.rollback()
            return RedirectResponse(
                url="/saas/auth/forgot-password?error="
                + quote_plus("Password reset email could not be sent. Please try again.")
                + "&email="
                + quote_plus(str(email or "")),
                status_code=302,
            )
    else:
        service.log_auth_event(
            db,
            event_type="password_reset_sent",
            event_status="neutral",
            request=request,
            details={"email": auth.normalize_email(email)},
        )
        db.commit()
    return RedirectResponse(
        url="/saas/auth/forgot-password?notice=" + quote_plus(neutral_notice),
        status_code=302,
    )


@router.get("/auth/reset-password", response_class=HTMLResponse)
def reset_password_page(
    request: Request,
    token: str = Query(""),
    db: Session = Depends(get_db),
):
    account, error = service.get_account_for_password_reset_token(db, token)
    db.rollback()
    return _render(
        request,
        "saas/reset_password.html",
        {
            "token": token if account else "",
            "error": error,
            "notice": "",
        },
        status_code=200 if account else 400,
    )


@router.post("/auth/reset-password")
def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if str(password or "") != str(confirm_password or ""):
        return _render(
            request,
            "saas/reset_password.html",
            {
                "token": token,
                "error": "Password confirmation does not match.",
                "notice": "",
            },
            status_code=400,
        )
    try:
        account = service.reset_password_with_token(db, token, password)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _render(
            request,
            "saas/reset_password.html",
            {
                "token": token,
                "error": str(exc),
                "notice": "",
            },
            status_code=400,
        )
    return RedirectResponse(
        "/saas/login?notice="
        + quote_plus("Your password has been updated. Please sign in to continue.")
        + "&email="
        + quote_plus(str(getattr(account, "email", "") or "")),
        status_code=302,
    )


@router.get("/signup", response_class=HTMLResponse, name="saas_signup_page")
def signup_page(
    request: Request,
    error: str = Query(""),
    warning: str = Query(""),
    email: str = Query(""),
    first_name: str = Query(""),
    last_name: str = Query(""),
    intent: str = Query(""),
    preferred_plan: str = Query(""),
    next_path: str = Query(""),
    db: Session = Depends(get_db),
):
    normalized_preferred_plan = service.normalize_preferred_plan_code(
        preferred_plan
    )
    if _current_account(request, db):
        return service.set_preferred_plan_cookie(
            RedirectResponse("/saas/account", status_code=302),
            preferred_plan_code=normalized_preferred_plan,
            request=request,
        )
    response = _render(
        request,
        "saas/signup.html",
        {
            "error": error,
            "warning": warning,
            "email": email,
            "next_path": _safe_next(next_path) if next_path else "",
            "first_name": first_name,
            "last_name": last_name,
            "intent": service.normalize_commercial_intent(intent),
            "preferred_plan": normalized_preferred_plan,
            "google_enabled": oauth.is_provider_configured("google"),
            "microsoft_enabled": oauth.is_provider_configured("microsoft"),
        },
    )
    return service.set_preferred_plan_cookie(
        response,
        preferred_plan_code=normalized_preferred_plan,
        request=request,
    )


@router.post("/auth/signup")
def signup(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    intent: str = Form(""),
    preferred_plan: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_intent = service.normalize_commercial_intent(intent)
    normalized_preferred_plan = service.normalize_preferred_plan_code(
        preferred_plan
    )
    intent_query = f"&intent={quote_plus(normalized_intent)}" if normalized_intent else ""
    preferred_plan_query = (
        f"&preferred_plan={quote_plus(normalized_preferred_plan)}"
        if normalized_preferred_plan
        else ""
    )
    if service.is_rate_limited(
        db,
        event_type="signup",
        request=request,
        max_attempts=service.SIGNUP_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.SIGNUP_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return service.set_preferred_plan_cookie(
            RedirectResponse(
                url=(
                    "/saas/signup?error=Too+many+signup+attempts."
                    "+Please+try+again+later."
                    f"{intent_query}{preferred_plan_query}"
                ),
                status_code=302,
            ),
            preferred_plan_code=normalized_preferred_plan,
            request=request,
        )
    if str(password or "") != str(confirm_password or ""):
        return service.set_preferred_plan_cookie(
            RedirectResponse(
                url=(
                    "/saas/signup?error=Password+confirmation+does+not+match."
                    f"&email={quote_plus(str(email or ''))}"
                    f"&first_name={quote_plus(str(first_name or ''))}"
                    f"&last_name={quote_plus(str(last_name or ''))}"
                    f"{intent_query}"
                    f"{preferred_plan_query}"
                ),
                status_code=302,
            ),
            preferred_plan_code=normalized_preferred_plan,
            request=request,
        )
    try:
        account, policy = service.create_account(
            db,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            signup_intent=normalized_intent,
            request=request,
        )
        service.send_verification_email(db, account, request)
        db.commit()
    except email_service.EmailDeliveryError:
        db.rollback()
        return service.set_preferred_plan_cookie(
            RedirectResponse(
                url=(
                    "/saas/signup?error=Verification+email+could+not+be+sent."
                    "+Please+try+again."
                    f"{intent_query}{preferred_plan_query}"
                ),
                status_code=302,
            ),
            preferred_plan_code=normalized_preferred_plan,
            request=request,
        )
    except ValueError as exc:
        db.rollback()
        return service.set_preferred_plan_cookie(
            RedirectResponse(
                url=(
                    "/saas/signup?error="
                    + quote_plus(str(exc))
                    + f"&email={quote_plus(str(email or ''))}"
                    + f"&first_name={quote_plus(str(first_name or ''))}"
                    + f"&last_name={quote_plus(str(last_name or ''))}"
                    + intent_query
                    + preferred_plan_query
                ),
                status_code=302,
            ),
            preferred_plan_code=normalized_preferred_plan,
            request=request,
        )
    return service.set_preferred_plan_cookie(
        RedirectResponse(
            url="/saas/auth/verification-sent?email="
            f"{quote_plus(str(account.email or ''))}&warning={quote_plus(str(policy.warning or ''))}",
            status_code=302,
        ),
        preferred_plan_code=normalized_preferred_plan,
        request=request,
    )


@router.post("/auth/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_path: str = Form(""),
    db: Session = Depends(get_db),
):
    continuation_query = (
        "&next_path=" + quote_plus(_safe_next(next_path)) if next_path else ""
    )
    if service.is_rate_limited(
        db,
        event_type="login",
        request=request,
        event_status="failed",
        max_attempts=service.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.LOGIN_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url=(
                "/saas/login?error=Too+many+login+attempts."
                "+Please+wait+before+trying+again."
                + continuation_query
            ),
            status_code=302,
        )
    account = service.authenticate_account(db, email, password)
    if not account:
        service.log_auth_event(
            db,
            event_type="login",
            event_status="failed",
            request=request,
            details={"email": auth.normalize_email(email)},
        )
        db.commit()
        return RedirectResponse(
            url=(
                "/saas/login?error=Invalid+email+or+password.&email="
                + quote_plus(str(email or ""))
                + continuation_query
            ),
            status_code=302,
        )
    if _account_needs_verification(account):
        return RedirectResponse(
            url=(
                "/saas/auth/verification-required?email="
                + quote_plus(str(getattr(account, "email", "") or email or ""))
                + continuation_query
            ),
            status_code=302,
        )
    session_token, csrf_token, _session_row = service.create_session(db, account, request=request)
    service.log_auth_event(db, event_type="login", account_id=account.id, request=request)
    draft_lifecycle_service.record_meaningful_activity(
        db, account, source="successful_login"
    )
    db.commit()
    destination = _post_auth_destination(db, account, next_path)
    response = RedirectResponse(url=destination, status_code=302)
    return service.set_session_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        request=request,
    )


@router.post("/auth/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    session_row = service.get_session_from_request(db, request)
    if session_row:
        service.revoke_session(db, session_row, reason="logout")
        service.log_auth_event(
            db,
            event_type="logout",
            account_id=session_row.saas_account_id,
            request=request,
        )
        db.commit()
    response = RedirectResponse("/saas/login", status_code=302)
    return service.clear_session_cookies(response, request)


@router.get("/auth/verification-sent", response_class=HTMLResponse)
def verification_sent_page(
    request: Request,
    email: str = Query(""),
    warning: str = Query(""),
    notice: str = Query(""),
):
    return _render(
        request,
        "saas/verification_sent.html",
        {"email": email, "warning": warning, "notice": notice},
    )


@router.get("/auth/verification-required", response_class=HTMLResponse)
def verification_required_page(
    request: Request,
    email: str = Query(""),
):
    return _render(
        request,
        "saas/verify_email.html",
        {
            "error": "",
            "success": "",
            "email": email,
            "show_resend": True,
            "recovery_message": (
                "Please verify your email before continuing your school workspace setup."
            ),
        },
    )


@router.get("/auth/verify-email", response_class=HTMLResponse)
def verify_email_page(
    request: Request,
    token: str = Query(""),
    db: Session = Depends(get_db),
):
    account, error = service.verify_email_token(db, token)
    if not account:
        db.rollback()
        return _render(
            request,
            "saas/verify_email.html",
            {
                "error": error,
                "success": "",
                "email": "",
                "show_resend": True,
                "recovery_message": (
                    "Enter your email address below and, if a TIS Account exists for it, "
                    "we will send a fresh verification link."
                ),
            },
            status_code=400,
        )
    db.commit()
    return RedirectResponse(
        "/saas/login?notice="
        + quote_plus("Your email has been verified. Please sign in to continue your school workspace setup.")
        + "&email="
        + quote_plus(str(getattr(account, "email", "") or "")),
        status_code=302,
    )


@router.post("/auth/resend-verification")
def resend_verification(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    if service.is_rate_limited(
        db,
        event_type="verification_sent",
        request=request,
        max_attempts=service.VERIFICATION_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.VERIFICATION_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/login?error=Too+many+verification+requests.+Please+try+again+later.&email="
            + quote_plus(str(email or "")),
            status_code=302,
        )
    account = service.get_account_by_email(db, email)
    if account:
        if _account_needs_verification(account):
            try:
                service.send_verification_email(db, account, request)
                db.commit()
            except email_service.EmailDeliveryError:
                db.rollback()
                return RedirectResponse(
                    url="/saas/login?error=Verification+email+could+not+be+sent.&email=" + quote_plus(str(email or "")),
                    status_code=302,
                )
        else:
            db.rollback()
            return RedirectResponse(
                url="/saas/login?notice="
                + quote_plus("This TIS Account is already verified. Please sign in to continue.")
                + "&email="
                + quote_plus(str(email or "")),
                status_code=302,
            )
    return RedirectResponse(
        url="/saas/auth/verification-sent?email="
        + quote_plus(str(email or ""))
        + "&notice="
        + quote_plus("If a TIS Account exists for this email, a new verification link has been sent."),
        status_code=302,
    )


@router.get(
    "/account/workspaces/{workspace_uuid}/activation",
    response_class=HTMLResponse,
)
def existing_workspace_paid_activation(
    workspace_uuid: str,
    request: Request,
    activation_uuid: str = Query(""),
    billing_interval: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(
        request,
        db,
        next_path=f"/saas/account/workspaces/{workspace_uuid}/activation",
    )
    if redirect:
        return redirect
    access = _existing_workspace_activation_access(db, account, workspace_uuid)
    current_activation = existing_workspace_paid_activation_service.get_current_activation(
        db, access.school_group.id
    )
    eligibility = existing_workspace_paid_activation_service.resolve_eligibility(
        db,
        school_group_id=access.school_group.id,
        account=account,
        allow_activation_id=getattr(current_activation, "id", None),
    )
    activation = None
    if activation_uuid:
        activation = db.query(models.ExistingWorkspacePaidActivation).filter(
            models.ExistingWorkspacePaidActivation.activation_uuid == activation_uuid,
            models.ExistingWorkspacePaidActivation.school_group_id
            == access.school_group.id,
            models.ExistingWorkspacePaidActivation.saas_account_id == account.id,
        ).one_or_none()
    selection_draft = None
    if not activation_uuid and existing_workspace_paid_activation_service.can_change_plan_selection(
        db, current_activation
    ):
        # The account entry point is deliberately a plan-selection page. A saved
        # quote supplies the default selection but must not bypass the owner's
        # opportunity to choose another eligible plan before checkout begins.
        selection_draft = current_activation
    elif activation is None:
        activation = current_activation
    context_activation = activation or selection_draft
    requested_interval = str(billing_interval or "").strip().lower()
    if activation is not None:
        # Review is immutable quote presentation; query parameters cannot reprice it.
        interval = str(activation.billing_interval or "monthly").strip().lower()
    elif requested_interval in {"monthly", "annual"}:
        interval = requested_interval
    else:
        interval = str(
            getattr(selection_draft, "billing_interval", "") or "monthly"
        ).strip().lower()
    if interval not in {"monthly", "annual"}:
        interval = "monthly"
    plans = (
        existing_workspace_paid_activation_service.list_plan_options(
            db, eligibility, interval
        )
        if eligibility.eligible
        else ()
    )
    selected_plan = (
        db.get(models.SubscriptionPlan, context_activation.selected_plan_id)
        if context_activation is not None
        else None
    )
    selected_branches = (
        db.query(models.ExistingWorkspacePaidActivationBranch)
        .filter(
            models.ExistingWorkspacePaidActivationBranch.paid_activation_id
            == context_activation.id,
            models.ExistingWorkspacePaidActivationBranch.quote_version
            == context_activation.quote_version,
        )
        .order_by(models.ExistingWorkspacePaidActivationBranch.branch_id.asc())
        .all()
        if context_activation is not None
        else ()
    )
    selected_plan_id = getattr(selected_plan, "id", None)
    if selected_plan_id is None:
        selected_plan_id = next(
            (option["plan"].id for option in plans if option["available"]),
            None,
        )
    billing_contact = billing_identity_service.workspace_billing_identity_form(
        db, access.school_group, account
    )
    db.rollback()
    return _render(
        request,
        "saas/existing_workspace_paid_activation.html",
        {
            "account": account,
            "organization_account": {"access": access},
            "access": access,
            "workspace": access.school_group,
            "eligibility": eligibility,
            "plans": plans,
            "billing_interval": interval,
            "billing_contact": billing_contact,
            "activation": activation,
            "selection_draft": selection_draft,
            "can_change_plan": existing_workspace_paid_activation_service.can_change_plan_selection(
                db, context_activation
            ),
            "selected_plan": selected_plan,
            "selected_plan_id": selected_plan_id,
            "selected_branches": selected_branches,
            "amount_display": _usd_amount(
                getattr(activation, "quote_aggregate_amount_minor", 0)
            ),
            "unit_amount_display": _usd_amount(
                getattr(activation, "quote_unit_amount_minor", 0)
            ),
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "idempotency_key": str(uuid.uuid4()),
            "error": request.query_params.get("error", ""),
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.post("/account/workspaces/{workspace_uuid}/activation/prepare")
def prepare_existing_workspace_paid_activation(
    workspace_uuid: str,
    request: Request,
    plan_id: int = Form(...),
    billing_interval: str = Form(...),
    idempotency_key: str = Form(...),
    selected_branch_ids: str = Form(""),
    billing_email: str = Form(...),
    billing_organization_name: str = Form(...),
    billing_contact_name: str = Form(""),
    company_number: str = Form(""),
    tax_identifier: str = Form(""),
    country_code: str = Form(...),
    country_name: str = Form(""),
    region_name: str = Form(""),
    city_name: str = Form(""),
    district_name: str = Form(""),
    neighborhood_name: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    access = _existing_workspace_activation_access(db, account, workspace_uuid)
    try:
        current_activation = (
            existing_workspace_paid_activation_service.get_current_activation(
                db, access.school_group.id
            )
        )
        if current_activation and not (
            existing_workspace_paid_activation_service.can_change_plan_selection(
                db, current_activation
            )
        ):
            raise existing_workspace_paid_activation_service.ExistingWorkspacePaidActivationError(
                "activation_checkout_in_progress",
                "Secure payment is already in progress for this workspace. "
                "Return to the payment review to continue.",
            )
        billing_identity_service.save_workspace_billing_profile(
            db,
            access.school_group,
            billing_email=billing_email,
            billing_organization_name=billing_organization_name,
            billing_contact_name=billing_contact_name,
            company_number=company_number,
            tax_identifier=tax_identifier,
            country_code=country_code,
            country_name=country_name,
            region_name=region_name,
            city_name=city_name,
            district_name=district_name,
            neighborhood_name=neighborhood_name,
        )
        branch_ids = tuple(
            int(value)
            for value in str(selected_branch_ids or "").split(",")
            if value.strip().isdigit()
        ) or None
        activation = existing_workspace_paid_activation_service.prepare_activation(
            db,
            school_group_id=access.school_group.id,
            account=account,
            plan_id=plan_id,
            billing_interval=billing_interval,
            selected_branch_ids=branch_ids,
            idempotency_key=idempotency_key,
        )
        db.commit()
    except (
        billing_identity_service.BillingIdentityError,
        existing_workspace_paid_activation_service.ExistingWorkspacePaidActivationError,
    ) as exc:
        db.rollback()
        logger.info(
            "Existing-workspace activation preparation blocked school_group_id=%s reason=%s",
            access.school_group.id,
            getattr(exc, "reason_code", exc.__class__.__name__),
        )
        return RedirectResponse(
            f"/saas/account/workspaces/{workspace_uuid}/activation?error="
            + quote_plus(str(exc)),
            status_code=302,
        )
    except OperationalError:
        db.rollback()
        logger.warning(
            "Existing-workspace activation preparation deferred because the workspace "
            "lock was unavailable school_group_id=%s",
            access.school_group.id,
            exc_info=True,
        )
        return RedirectResponse(
            f"/saas/account/workspaces/{workspace_uuid}/activation?error="
            + quote_plus(existing_workspace_paid_activation_service.CUSTOMER_SAFE_ERROR),
            status_code=302,
        )
    return RedirectResponse(
        f"/saas/account/workspaces/{workspace_uuid}/activation?activation_uuid="
        + quote_plus(activation.activation_uuid),
        status_code=302,
    )


@router.post("/account/workspaces/{workspace_uuid}/activation/launch")
def launch_existing_workspace_paid_activation(
    workspace_uuid: str,
    request: Request,
    activation_uuid: str = Form(...),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    access = _existing_workspace_activation_access(db, account, workspace_uuid)
    try:
        launch = existing_workspace_paid_activation_service.launch_checkout(
            db,
            activation_uuid=activation_uuid,
            account=account,
            checkout_url=payment_service.payment_link_base_url(request),
        )
        db.commit()
        return RedirectResponse(launch.checkout_url, status_code=303)
    except (
        billing_identity_service.BillingIdentityError,
        billing_identity_service.BillingIdentitySyncError,
        existing_workspace_paid_activation_service.ExistingWorkspacePaidActivationError,
        paddle_client.PaddleAPIError,
    ) as exc:
        db.rollback()
        logger.warning(
            "Existing-workspace activation launch failed school_group_id=%s reason=%s",
            access.school_group.id,
            getattr(exc, "reason_code", getattr(exc, "error_code", exc.__class__.__name__)),
            exc_info=True,
        )
        return RedirectResponse(
            f"/saas/account/workspaces/{workspace_uuid}/activation?activation_uuid="
            + quote_plus(activation_uuid)
            + "&error="
            + quote_plus(existing_workspace_paid_activation_service.CUSTOMER_SAFE_ERROR),
            status_code=302,
        )
    except OperationalError:
        db.rollback()
        logger.warning(
            "Existing-workspace activation launch deferred because its checkout lock "
            "was unavailable school_group_id=%s",
            access.school_group.id,
            exc_info=True,
        )
        return RedirectResponse(
            f"/saas/account/workspaces/{workspace_uuid}/activation?activation_uuid="
            + quote_plus(activation_uuid)
            + "&error="
            + quote_plus(existing_workspace_paid_activation_service.CUSTOMER_SAFE_ERROR),
            status_code=302,
        )


@router.get("/account", response_class=HTMLResponse)
def account_dashboard(
    request: Request,
    organization_uuid: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    conversion_claim = existing_workspace_conversion_service.claim_operation_for_account(
        db, account
    )
    if conversion_claim is not None:
        db.rollback()
        return RedirectResponse("/saas/existing-workspace/setup", status_code=302)
    requested_organization_uuid = str(organization_uuid or "").strip()
    cookie_organization_uuid = str(
        request.cookies.get(service.SAAS_ORGANIZATION_COOKIE) or ""
    ).strip()
    selection_value = requested_organization_uuid or cookie_organization_uuid
    workspace_options, selected_workspace = (
        customer_journey_service.select_organization_account_access(
            db,
            account,
            organization_uuid=selection_value,
        )
    )
    if requested_organization_uuid and selected_workspace is None:
        db.rollback()
        return RedirectResponse(
            "/saas/account?notice="
            + quote_plus("That organization is not available for this account."),
            status_code=302,
        )
    if cookie_organization_uuid and not requested_organization_uuid and selected_workspace is None:
        workspace_options, selected_workspace = (
            customer_journey_service.select_organization_account_access(
                db,
                account,
            )
        )
    if selected_workspace is not None:
        branch_count = (
            db.query(operational_models.Branch)
            .filter(
                operational_models.Branch.school_group_id
                == selected_workspace.school_group.id,
                operational_models.Branch.status == True,
            )
            .count()
        )
        organization = selected_workspace.organization
        existing_workspace_activation_required = bool(
            selected_workspace.school_group.workspace_classification
            == WorkspaceClassification.CUSTOMER.value
            and selected_workspace.school_group.workspace_lifecycle_status
            == WorkspaceLifecycleStatus.PROVISIONING.value
            and selected_workspace.commercial_access.reason_code
            == "activation_required"
        )
        promo_activation_available = bool(
            selected_workspace.is_owner
            and selected_workspace.school_group.workspace_classification
            == WorkspaceClassification.CUSTOMER.value
            and selected_workspace.school_group.workspace_lifecycle_status
            == WorkspaceLifecycleStatus.PROVISIONING.value
            and selected_workspace.commercial_access.reason_code
            in {"missing_promo_grant", "activation_required"}
        )
        db.commit()
        response = _render(
            request,
            "saas/account.html",
            {
                "account": account,
                "organization": organization,
                "notice": request.query_params.get("notice", ""),
                "setup_console": None,
                "workspace_options": workspace_options,
                "organization_account": {
                    "access": selected_workspace,
                    "branch_count": branch_count,
                    "promo_activation_available": promo_activation_available,
                    "existing_workspace_activation_required": existing_workspace_activation_required,
                    "suppress_commercial_billing": existing_workspace_activation_required,
                },
            },
        )
        if requested_organization_uuid:
            response.set_cookie(
                service.SAAS_ORGANIZATION_COOKIE,
                selected_workspace.organization_uuid,
                **auth.secure_cookie_kwargs(
                    request,
                    max_age=service.session_max_age_seconds(),
                ),
            )
        return response
    if len(workspace_options) > 1:
        db.commit()
        return _render(
            request,
            "saas/account.html",
            {
                "account": account,
                "organization": None,
                "notice": request.query_params.get("notice", ""),
                "setup_console": None,
                "workspace_options": workspace_options,
                "organization_account": None,
            },
        )
    linked_accesses = customer_journey_service.list_organization_account_accesses(
        db, account
    )
    if linked_accesses:
        destination = customer_journey_service.login_destination(db, account)
        db.commit()
        return RedirectResponse(destination, status_code=302)
    setup_console = service.build_setup_console_context(db, account)
    organization = service.get_pending_organization_for_account(db, account)
    current_plan_selection = (
        billing_service.get_current_plan_selection(db, organization)
        if organization is not None
        else None
    )
    demo_request = demo_request_service.get_latest_for_organization(db, organization)
    demo_provisioning = demo_provisioning_service.get_provisioning_for_request(
        db, demo_request
    )
    demo_lifecycle = (
        demo_lifecycle_service.resolve_demo_lifecycle(
            db,
            provisioning=demo_provisioning,
        )
        if demo_provisioning
        and demo_provisioning.provisioning_status == "active"
        else None
    )
    if organization is not None and current_plan_selection is None:
        setup_console = demo_request_service.apply_customer_setup_context(
            setup_console,
            organization,
            demo_request,
            demo_provisioning,
            demo_lifecycle,
        )
    db.commit()
    return _render(
        request,
        "saas/account.html",
        {
            "account": account,
            "organization": organization,
            "notice": request.query_params.get("notice", ""),
            "setup_console": setup_console,
            "demo_request": demo_request,
            "demo_provisioning": demo_provisioning,
            "demo_lifecycle": demo_lifecycle,
        },
    )


@router.get("/plans", response_class=HTMLResponse)
def public_plan_catalog(
    request: Request,
    country_code: str = Query(""),
    db: Session = Depends(get_db),
):
    return _render(
        request,
        "saas/plan_catalog.html",
        {
            "account": _current_account(request, db),
            "plan_catalog": pricing_service.build_plan_catalog(db, country_code=country_code),
        },
    )


@router.get("/account/profile", response_class=HTMLResponse)
def account_profile(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization_account = _organization_account_shell_context(request, db, account)
    db.commit()
    return _render(
        request,
        "saas/profile.html",
        {
            "account": account,
            "organization_account": organization_account,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.post("/account/profile")
def update_profile(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    account.first_name = str(first_name or "").strip()[:120]
    account.last_name = str(last_name or "").strip()[:120]
    db.commit()
    return RedirectResponse("/saas/account/profile?notice=Profile+updated.", status_code=302)


@router.get("/account/security", response_class=HTMLResponse)
def account_security(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    identities = db.query(models.SaaSAuthIdentity).filter(
        models.SaaSAuthIdentity.saas_account_id == account.id
    ).order_by(models.SaaSAuthIdentity.provider.asc()).all()
    organization_account = _organization_account_shell_context(request, db, account)
    db.commit()
    return _render(
        request,
        "saas/security.html",
        {
            "account": account,
            "organization_account": organization_account,
            "identities": identities,
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.get("/account/billing", response_class=HTMLResponse)
def account_billing(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    onboarding_summary = service.build_pending_dashboard_summary(db, account)
    setup_console = _payment_setup_console(
        db,
        account,
        "account_billing",
        onboarding_summary=onboarding_summary,
    )
    db.commit()
    return _render(
        request,
        "saas/account_billing.html",
        {
            "account": account,
            "onboarding_summary": onboarding_summary,
            "setup_console": setup_console,
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.get("/subscription", response_class=HTMLResponse)
def subscription_portal(
    request: Request,
    organization_uuid: str = Query(""),
    db: Session = Depends(get_db),
):
    requested_organization_uuid = str(organization_uuid or "").strip()
    continuation = "/saas/subscription"
    if requested_organization_uuid:
        continuation += "?organization_uuid=" + quote_plus(requested_organization_uuid)
    account, _session_row, redirect = _require_verified_account(
        request,
        db,
        next_path=continuation,
    )
    if redirect:
        return redirect
    account_accesses = customer_journey_service.list_organization_account_accesses(
        db, account
    )
    selected_access = None
    if account_accesses:
        if requested_organization_uuid:
            selected_access = next(
                (
                    item
                    for item in account_accesses
                    if item.organization_uuid == requested_organization_uuid
                ),
                None,
            )
            if selected_access is None:
                raise HTTPException(status_code=403, detail="Billing access is not available.")
        else:
            selected_group_id = int(
                getattr(account, "_selected_school_group_id", 0) or 0
            )
            selected_access = next(
                (
                    item
                    for item in account_accesses
                    if int(getattr(item.school_group, "id", 0) or 0)
                    == selected_group_id
                ),
                None,
            )
            if selected_access is None:
                billing_accesses = tuple(
                    item for item in account_accesses if item.can_manage_billing
                )
                if len(billing_accesses) == 1:
                    selected_access = billing_accesses[0]
                elif len(billing_accesses) > 1:
                    return RedirectResponse(
                        "/saas/account?notice="
                        + quote_plus(
                            "Choose an organization before opening Billing & Subscription."
                        ),
                        status_code=302,
                    )
        if selected_access is None or not selected_access.can_manage_billing:
            raise HTTPException(status_code=403, detail="Billing access is not available.")
        if (
            selected_access.school_group.workspace_classification
            == WorkspaceClassification.CUSTOMER.value
            and selected_access.school_group.workspace_lifecycle_status
            == WorkspaceLifecycleStatus.PROVISIONING.value
            and selected_access.commercial_access.reason_code == "activation_required"
        ):
            return RedirectResponse(
                "/saas/account?notice="
                + quote_plus(
                    "Choose a paid plan or use an eligible promo code to activate this "
                    "existing workspace."
                ),
                status_code=302,
            )
        setattr(account, "_selected_school_group_id", int(selected_access.school_group.id))
    portal_authority = (
        commercial_portal_service.resolve_portal_authority(
            db,
            int(selected_access.school_group.id),
        )
        if selected_access is not None
        else None
    )
    if (
        portal_authority is not None
        and portal_authority.source == commercial_authority_service.PROMO_GRANT
    ):
        promo_portal = commercial_portal_service.build_promo_commercial_portal(
            db,
            int(selected_access.school_group.id),
            authority=portal_authority,
        )
        response = _render(
            request,
            "saas/promo_commercial_access.html",
            {
                "account": account,
                "organization_account": {"access": selected_access},
                "promo_portal": promo_portal,
                "support_email": str(
                    os.environ.get("TIS_SUPPORT_EMAIL")
                    or os.environ.get("EMAIL_REPLY_TO")
                    or "info@tisplatform.com"
                ).strip(),
                "notice": request.query_params.get("notice", ""),
                "error": request.query_params.get("error", ""),
            },
        )
        if requested_organization_uuid:
            response.set_cookie(
                service.SAAS_ORGANIZATION_COOKIE,
                selected_access.organization_uuid,
                **auth.secure_cookie_kwargs(
                    request,
                    max_age=service.session_max_age_seconds(),
                ),
            )
        return response
    demo_journey = customer_journey_service.resolve_demo_subscription_journey(
        db, account
    )
    if demo_journey:
        if demo_journey.configuration_error:
            logger.warning(
                "Demo subscription configuration unavailable account_id=%s "
                "organization_id=%s school_group_id=%s reason=%s",
                account.id,
                demo_journey.organization.id,
                demo_journey.school_group.id,
                demo_journey.configuration_error,
            )
        response = _render(
            request,
            "saas/demo_subscription.html",
            {
                "account": account,
                "organization_account": (
                    {"access": selected_access} if selected_access is not None else None
                ),
                "journey": demo_journey,
                "support_email": str(
                    os.environ.get("TIS_SUPPORT_EMAIL")
                    or os.environ.get("EMAIL_REPLY_TO")
                    or "info@tisplatform.com"
                ).strip(),
                "error": request.query_params.get("error", ""),
            },
        )
        if requested_organization_uuid and selected_access is not None:
            response.set_cookie(
                service.SAAS_ORGANIZATION_COOKIE,
                selected_access.organization_uuid,
                **auth.secure_cookie_kwargs(
                    request,
                    max_age=service.session_max_age_seconds(),
                ),
            )
        return response
    portal = subscription_portal_service.build_subscription_portal(db, account)
    billing_contact = None
    billing_profile = None
    billing_country_options = ()
    if selected_access is not None and selected_access.organization is not None:
        billing_profile = billing_identity_service.get_billing_profile(
            db, selected_access.organization
        )
        billing_contact = billing_identity_service.billing_identity_form(
            db, selected_access.organization, account
        )
        billing_country_options = tuple(location_service.list_countries())
    billing_history = None
    try:
        billing_history = billing_history_service.build_billing_history(db, account, portal)
    except billing_history_service.BillingHistoryAccessError:
        pass
    response = _render(
        request,
        "saas/subscription.html",
        {
            "account": account,
            "organization_account": (
                {"access": selected_access} if selected_access is not None else None
            ),
            "subscription_portal": portal,
            "billing_contact": billing_contact,
            "billing_contact_editing": (
                str(request.query_params.get("billing_edit") or "").strip() == "1"
            ),
            "billing_sync_result": str(
                request.query_params.get("billing_sync") or ""
            ).strip(),
            "billing_country_options": billing_country_options,
            "billing_identity_ready": bool(
                billing_contact
                and (
                    billing_profile is None
                    or billing_contact.sync_status == "synced"
                )
            ),
            "billing_organization_uuid": (
                selected_access.organization_uuid if selected_access else ""
            ),
            "billing_history": billing_history,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
            "support_email": str(
                os.environ.get("TIS_SUPPORT_EMAIL")
                or os.environ.get("EMAIL_REPLY_TO")
                or "info@tisplatform.com"
            ).strip(),
        },
    )
    if requested_organization_uuid and selected_access is not None:
        response.set_cookie(
            service.SAAS_ORGANIZATION_COOKIE,
            selected_access.organization_uuid,
            **auth.secure_cookie_kwargs(
                request,
                max_age=service.session_max_age_seconds(),
            ),
        )
    return response


def _existing_workspace_setup_shell(db: Session, account, school_group_id: int):
    access = next(
        (
            item
            for item in customer_journey_service.list_organization_account_accesses(
                db, account
            )
            if int(item.school_group.id) == int(school_group_id)
        ),
        None,
    )
    if access is None:
        return None
    return {
        "access": access,
        "suppress_operational_entry": True,
        "suppress_commercial_billing": True,
    }


@router.get("/existing-workspace/setup", response_class=HTMLResponse)
def existing_workspace_setup_review(
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        setup = existing_workspace_conversion_service.setup_review_context(db, account)
    except existing_workspace_conversion_service.ExistingWorkspaceConversionError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Workspace setup claim not found.") from exc
    organization_account = _existing_workspace_setup_shell(
        db, account, setup["operation"].school_group_id
    )
    db.commit()
    return _render(
        request,
        "saas/existing_workspace_setup.html",
        {
            "account": account,
            "setup": setup,
            "organization_account": organization_account,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/existing-workspace/claim")
def claim_existing_workspace_owner(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    try:
        existing_workspace_conversion_service.align_verified_owner(db, account)
        db.commit()
    except existing_workspace_conversion_service.ExistingWorkspaceConversionError as exc:
        db.rollback()
        return RedirectResponse(
            "/saas/existing-workspace/setup?error=" + quote_plus(str(exc)),
            status_code=302,
        )
    return RedirectResponse(
        "/saas/existing-workspace/setup?notice="
        + quote_plus("Your verified account is now linked for setup review."),
        status_code=302,
    )


@router.post("/existing-workspace/setup")
def save_existing_workspace_setup_review(
    request: Request,
    legal_name: str = Form(""),
    timezone_name: str = Form(""),
    educational_program: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    try:
        existing_workspace_conversion_service.save_setup_review(
            db,
            account,
            legal_name=legal_name,
            timezone_name=timezone_name,
            educational_program=educational_program,
        )
        db.commit()
    except existing_workspace_conversion_service.ExistingWorkspaceConversionError as exc:
        db.rollback()
        return RedirectResponse(
            "/saas/existing-workspace/setup?error=" + quote_plus(str(exc)),
            status_code=302,
        )
    return RedirectResponse(
        "/saas/existing-workspace/setup?notice="
        + quote_plus("Workspace setup details are complete and ready for controlled conversion."),
        status_code=302,
    )


def _resolve_billing_contact_update_context(
    db: Session,
    account,
    organization_uuid: str,
):
    _accesses, selected_access = (
        customer_journey_service.select_organization_account_access(
            db,
            account,
            organization_uuid=str(organization_uuid or "").strip(),
        )
    )
    if (
        selected_access is None
        or not selected_access.can_manage_billing
        or selected_access.organization is None
    ):
        raise HTTPException(
            status_code=403,
            detail="Billing access is not available.",
        )
    setattr(account, "_selected_school_group_id", int(selected_access.school_group.id))
    context = billing_history_service.resolve_billing_context(db, account)
    if int(context.school_group_id) != int(selected_access.school_group.id):
        raise billing_identity_service.BillingIdentityError(
            "Billing identity does not match this organization."
        )
    if context.customer is None:
        raise billing_identity_service.BillingIdentityError(
            "The billing provider customer mapping is unavailable."
        )
    return selected_access, context


def _billing_country_name(country_code: str, submitted_name: str = "") -> str:
    normalized = str(country_code or "").strip().upper()
    match = next(
        (
            row
            for row in location_service.list_countries()
            if str(row.get("code") or "").strip().upper() == normalized
        ),
        None,
    )
    return str((match or {}).get("name") or submitted_name or "").strip()


@router.post("/subscription/billing-contact")
def update_subscription_billing_contact(
    request: Request,
    organization_uuid: str = Form(...),
    billing_email: str = Form(""),
    billing_organization_name: str = Form(""),
    billing_contact_name: str = Form(""),
    company_number: str = Form(""),
    tax_identifier: str = Form(""),
    country_code: str = Form(""),
    country_name: str = Form(""),
    region_name: str = Form(""),
    city_name: str = Form(""),
    district_name: str = Form(""),
    neighborhood_name: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(
        request,
        db,
        next_path=(
            "/saas/subscription?organization_uuid="
            + quote_plus(str(organization_uuid or "").strip())
        ),
    )
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        selected_access, context = _resolve_billing_contact_update_context(
            db,
            account,
            organization_uuid,
        )
        organization = selected_access.organization
        destination = (
            "/saas/subscription?organization_uuid="
            + quote_plus(selected_access.organization_uuid)
        )
        billing_identity_service.save_billing_profile(
            db,
            organization,
            billing_email=billing_email,
            billing_organization_name=billing_organization_name,
            billing_contact_name=billing_contact_name,
            company_number=company_number,
            tax_identifier=tax_identifier,
            country_code=country_code,
            country_name=_billing_country_name(country_code, country_name),
            region_name=region_name,
            city_name=city_name,
            district_name=district_name,
            neighborhood_name=neighborhood_name,
        )
        billing_identity_service.sync_active_subscription_billing_identity(
            db,
            account=account,
            organization=organization,
            subscription=context.subscription,
            payment_customer=context.customer,
        )
        db.commit()
    except billing_identity_service.BillingIdentitySyncError as exc:
        db.commit()
        logger.warning(
            "billing_contact_save_sync_deferred organization_uuid=%s "
            "provider_step=%s reason=%s status_code=%s",
            str(organization_uuid or ""),
            exc.provider_step,
            exc.reason_code,
            str(exc.provider_status_code or "unavailable"),
        )
        return RedirectResponse(
            destination + "&billing_sync=save_failed",
            status_code=302,
        )
    except (
        billing_identity_service.BillingIdentityError,
        billing_history_service.BillingHistoryAccessError,
    ) as exc:
        db.rollback()
        fallback_destination = (
            "/saas/subscription?organization_uuid="
            + quote_plus(str(organization_uuid or "").strip())
        )
        return _redirect_error(
            locals().get("destination", fallback_destination) + "&billing_edit=1",
            str(exc),
        )
    return RedirectResponse(
        destination
        + "&notice="
        + quote_plus("Billing contact updated and synchronized with Paddle."),
        status_code=302,
    )


@router.post("/subscription/billing-contact/retry")
def retry_subscription_billing_contact_sync(
    request: Request,
    organization_uuid: str = Form(...),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(
        request,
        db,
        next_path=(
            "/saas/subscription?organization_uuid="
            + quote_plus(str(organization_uuid or "").strip())
        ),
    )
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    destination = (
        "/saas/subscription?organization_uuid="
        + quote_plus(str(organization_uuid or "").strip())
    )
    try:
        selected_access, context = _resolve_billing_contact_update_context(
            db,
            account,
            organization_uuid,
        )
        organization = selected_access.organization
        profile = billing_identity_service.require_confirmed_billing_profile(
            db,
            organization,
        )
        if str(profile.provider_sync_status or "").strip().lower() == "synced":
            db.commit()
            return RedirectResponse(
                destination
                + "&notice="
                + quote_plus("Billing details are already synchronized with Paddle."),
                status_code=302,
            )
        profile.provider_sync_status = "pending"
        profile.provider_synced_at = None
        billing_identity_service.sync_active_subscription_billing_identity(
            db,
            account=account,
            organization=organization,
            subscription=context.subscription,
            payment_customer=context.customer,
        )
        db.commit()
    except billing_identity_service.BillingIdentitySyncError as exc:
        db.commit()
        logger.warning(
            "billing_contact_retry_failed organization_uuid=%s provider_step=%s "
            "reason=%s status_code=%s",
            str(organization_uuid or ""),
            exc.provider_step,
            exc.reason_code,
            str(exc.provider_status_code or "unavailable"),
        )
        return RedirectResponse(
            destination + "&billing_sync=retry_failed",
            status_code=302,
        )
    except (
        billing_identity_service.BillingIdentityError,
        billing_history_service.BillingHistoryAccessError,
    ) as exc:
        db.rollback()
        return _redirect_error(destination, str(exc))
    return RedirectResponse(
        destination
        + "&notice="
        + quote_plus("Billing details synchronized with Paddle."),
        status_code=302,
    )


@router.post("/subscription/demo/select")
def select_demo_conversion_plan(
    request: Request,
    plan_id: int = Form(...),
    billing_interval: str = Form(...),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    journey = customer_journey_service.resolve_demo_subscription_journey(db, account)
    if journey is None:
        db.rollback()
        return RedirectResponse(
            "/saas/subscription?error="
            + quote_plus("This subscription path is not available."),
            status_code=302,
        )
    try:
        demo_conversion_service.request_demo_conversion(
            db, account, journey.organization
        )
        journey.organization.status = service.READY_FOR_CHECKOUT_STATUS
        billing_service.select_plan(
            db,
            journey.organization,
            plan_id=plan_id,
            billing_interval=billing_interval,
        )
        db.commit()
    except (ValueError, demo_conversion_service.DemoConversionError) as exc:
        db.rollback()
        logger.warning(
            "Demo subscription selection failed account_id=%s organization_id=%s",
            account.id,
            journey.organization.id,
            exc_info=True,
        )
        return RedirectResponse(
            "/saas/subscription?error=" + quote_plus(str(exc)), status_code=302
        )
    return RedirectResponse(
        f"/saas/onboarding/{journey.organization.organization_uuid}/checkout",
        status_code=302,
    )


@router.get("/expired-access", response_class=HTMLResponse)
def saas_expired_access(
    request: Request,
    kind: str = Query("demo"),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    from saas import commercial_access_service

    commercial = commercial_access_service.resolve_customer_access(db, account)
    if commercial.allowed_access:
        return RedirectResponse("/login", status_code=302)
    normalized = commercial.kind or ("subscription" if kind == "subscription" else "demo")
    access_presentation = commercial_access_service.customer_access_presentation(
        commercial
    )
    return _render(
        request,
        "saas/expired_access.html",
        {
            "account": account,
            "kind": normalized,
            "commercial_access": commercial,
            "access_presentation": access_presentation,
            "support_email": str(
                os.environ.get("TIS_SUPPORT_EMAIL")
                or os.environ.get("EMAIL_REPLY_TO")
                or "info@tisplatform.com"
            ).strip(),
        },
        status_code=403,
    )


@router.get("/subscription/invoices/{invoice_number}/download")
def download_subscription_invoice(
    invoice_number: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        invoice_url = billing_history_service.get_invoice_download_url(
            db, account, invoice_number
        )
    except billing_history_service.BillingHistoryAccessError as exc:
        raise HTTPException(status_code=403, detail="Billing access is not available.") from exc
    except billing_history_service.InvoiceUnavailableError as exc:
        return RedirectResponse(
            "/saas/subscription?error=" + quote_plus(str(exc)),
            status_code=302,
        )
    return RedirectResponse(invoice_url, status_code=302)


@router.get("/subscription/cancel", response_class=HTMLResponse)
def subscription_cancellation_confirmation(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        lifecycle = subscription_cancellation_service.get_cancellation_confirmation(db, account)
        portal = subscription_portal_service.build_subscription_portal(db, account)
    except subscription_change_service.SubscriptionChangeError as exc:
        return _subscription_change_error(exc, "/saas/subscription")
    return _render(request, "saas/subscription_cancel_confirm.html", {
        "account": account,
        "lifecycle": lifecycle,
        "subscription_portal": portal,
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "error": request.query_params.get("error", ""),
    })


@router.post("/subscription/cancel")
def request_subscription_cancellation(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        subscription_cancellation_service.request_cancellation(db, account)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription/cancel")
    return RedirectResponse(
        "/saas/subscription?notice=" + quote_plus("Cancellation request submitted. Paddle confirmation is pending."),
        status_code=302,
    )


@router.post("/subscription/cancellation/undo")
def undo_subscription_cancellation(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        subscription_cancellation_service.request_cancellation_reversal(db, account)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription")
    return RedirectResponse(
        "/saas/subscription?notice=" + quote_plus("Keep Subscription request submitted. Paddle confirmation is pending."),
        status_code=302,
    )


@router.post("/subscription/plans/preview")
def preview_subscription_plan_change(
    request: Request,
    target_plan_code: str = Form(...),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        row = subscription_plan_change_service.preview_plan_change(db, account, target_plan_code)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription")
    return RedirectResponse(f"/saas/subscription/plans/{row.request_uuid}/confirm", status_code=302)


@router.get("/subscription/plans/{request_uuid}/confirm", response_class=HTMLResponse)
def confirm_subscription_plan_change_page(request_uuid: str, request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        row, plan, impact = subscription_plan_change_service.get_confirmation_preview(db, account, request_uuid)
        current_name = subscription_portal_service.build_subscription_portal(db, account).plan_name
        summary = subscription_plan_change_service.customer_summary(row, plan, impact, current_name)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription")
    return _render(request, "saas/subscription_plan_confirm.html", {
        "account": account,
        "change": summary,
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "error": request.query_params.get("error", ""),
    })


@router.post("/subscription/plans/{request_uuid}/confirm")
def confirm_subscription_plan_change(request_uuid: str, request: Request, csrf_token: str = Form(""), db: Session = Depends(get_db)):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        row = subscription_plan_change_service.submit_plan_change(db, account, request_uuid)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, f"/saas/subscription/plans/{request_uuid}/confirm")
    notice = "Plan upgrade is awaiting Paddle confirmation." if row.change_type == subscription_plan_change_service.UPGRADE else "Plan downgrade is scheduled for the next billing period."
    return RedirectResponse("/saas/subscription?notice=" + quote_plus(notice), status_code=302)


@router.get("/subscription/plans/{request_uuid}/replace", response_class=HTMLResponse)
def replace_subscription_plan_change_page(request_uuid: str, target_plan_code: str, request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        row, target_plan, _direction = subscription_plan_change_service.get_replacement_confirmation(db, account, request_uuid, target_plan_code)
        existing_plan_name = db.query(models.SubscriptionPlan.plan_name).filter(models.SubscriptionPlan.id == row.target_plan_id).scalar() or "Scheduled plan"
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription")
    return _render(request, "saas/subscription_plan_replace.html", {
        "account": account, "request_uuid": row.request_uuid,
        "existing_plan_name": existing_plan_name, "target_plan_name": target_plan.plan_name,
        "target_plan_code": target_plan.plan_code, "branch_quantity": row.current_quantity,
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "error": request.query_params.get("error", ""),
    })


@router.post("/subscription/plans/{request_uuid}/replace")
def replace_subscription_plan_change(request_uuid: str, request: Request, target_plan_code: str = Form(...), csrf_token: str = Form(""), db: Session = Depends(get_db)):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        replacement = subscription_plan_change_service.replace_scheduled_plan_change(db, account, request_uuid, target_plan_code)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, f"/saas/subscription/plans/{request_uuid}/replace?target_plan_code={quote_plus(target_plan_code)}")
    return RedirectResponse(f"/saas/subscription/plans/{replacement.request_uuid}/confirm", status_code=302)


@router.post("/subscription/plans/{request_uuid}/cancel")
def cancel_subscription_plan_change(request_uuid: str, request: Request, csrf_token: str = Form(""), db: Session = Depends(get_db)):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        subscription_plan_change_service.cancel_scheduled_plan_change(db, account, request_uuid)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription")
    return RedirectResponse("/saas/subscription?notice=" + quote_plus("Scheduled plan change canceled."), status_code=302)


def _require_saas_csrf(session_row, csrf_token: str):
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def _subscription_change_error(exc: subscription_change_service.SubscriptionChangeError, path: str, *, requested_quantity: int | None = None):
    if exc.status_code == 403:
        raise HTTPException(status_code=403, detail=str(exc))
    message = str(exc)
    if exc.diagnostics and _paddle_client_environment() == "sandbox":
        missing = ", ".join(exc.diagnostics.get("missing_fields") or ()) or "none"
        sections = ", ".join(exc.diagnostics.get("response_sections") or ()) or "none"
        message = f"Preview diagnostic {exc.code}: missing fields [{missing}]; response sections [{sections}]."
    if requested_quantity is not None:
        separator = "&" if "?" in path else "?"
        path = f"{path}{separator}requested_quantity={int(requested_quantity)}"
    return _redirect_error(path, message)


@router.get("/subscription/branches", response_class=HTMLResponse)
def subscription_branch_management(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    portal = subscription_portal_service.build_subscription_portal(db, account)
    change_context = None
    try:
        change_context = subscription_change_service.resolve_change_context(db, account)
        can_manage = portal.pending_change is None
        access_error = ""
    except subscription_change_service.SubscriptionChangeError as exc:
        if exc.status_code == 403:
            raise HTTPException(status_code=403, detail=str(exc))
        can_manage = False
        access_error = str(exc)
    submitted_quantity = request.query_params.get("requested_quantity", "")
    try:
        requested_quantity = int(submitted_quantity)
    except (TypeError, ValueError):
        requested_quantity = portal.paid_branch_quantity or 1
    minimum_branch_proposal = max(int(portal.active_branch_count or 0), 1)
    if requested_quantity < minimum_branch_proposal:
        requested_quantity = max(
            int(portal.paid_branch_quantity or 0), minimum_branch_proposal
        )
    def _proposed_count(name: str, fallback: int) -> int:
        try:
            return max(int(request.query_params.get(name, fallback)), 0)
        except (TypeError, ValueError):
            return fallback
    proposed_system_users = _proposed_count(
        "proposed_system_users", portal.active_system_user_count
    )
    proposed_teachers = _proposed_count(
        "proposed_teachers", portal.active_teacher_count
    )
    resulting_minimum_eligible_plan_name = portal.minimum_eligible_plan_name
    if change_context is not None:
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == change_context.subscription.plan_id,
            models.SubscriptionPlan.is_active.is_(True),
        ).one_or_none()
        if plan is not None:
            try:
                proposed_snapshot = (
                    branch_pricing_quote_service.build_organization_capacity_snapshot(
                        db,
                        school_group_id=change_context.resolution.school_group_id,
                        current_plan=plan,
                        proposed_branch_count=requested_quantity,
                        proposed_system_user_count=proposed_system_users,
                        proposed_teacher_count=proposed_teachers,
                    )
                )
                resulting_minimum_eligible_plan_name = (
                    "Custom"
                    if proposed_snapshot.custom_required
                    else proposed_snapshot.minimum_eligible_plan_name
                    or "Not Available"
                )
            except ValueError:
                resulting_minimum_eligible_plan_name = "Not Available"
    paid_branch_quantity = int(portal.paid_branch_quantity or 0)
    return _render(request, "saas/subscription_branches.html", {
        "account": account,
        "subscription_portal": portal,
        "can_manage": can_manage,
        "requested_quantity": requested_quantity,
        "proposed_system_users": proposed_system_users,
        "proposed_teachers": proposed_teachers,
        "additional_paid_branches_requested": max(
            requested_quantity - paid_branch_quantity,
            0,
        ),
        "resulting_minimum_eligible_plan_name": resulting_minimum_eligible_plan_name,
        "access_error": access_error,
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "notice": request.query_params.get("notice", ""),
        "error": request.query_params.get("error", ""),
    })


@router.post("/subscription/branches/preview")
def preview_subscription_branch_change(
    request: Request,
    requested_quantity: int = Form(...),
    proposed_system_users: int | None = Form(None),
    proposed_teachers: int | None = Form(None),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        context = subscription_change_service.resolve_change_context(db, account, lock=True)
        plan = db.query(models.SubscriptionPlan).filter(
            models.SubscriptionPlan.id == context.subscription.plan_id,
            models.SubscriptionPlan.is_active.is_(True),
        ).one_or_none()
        if plan is None:
            raise subscription_change_service.SubscriptionChangeError(
                "Subscription capacity is temporarily unavailable.",
                code="capacity_plan_unavailable",
                status_code=409,
            )
        snapshot = branch_pricing_quote_service.build_organization_capacity_snapshot(
            db,
            school_group_id=context.resolution.school_group_id,
            current_plan=plan,
            proposed_branch_count=requested_quantity,
            proposed_system_user_count=proposed_system_users,
            proposed_teacher_count=proposed_teachers,
        )
        if snapshot.custom_required:
            raise subscription_change_service.SubscriptionChangeError(
                "This capacity requires a Custom subscription. Please contact the TIS team.",
                code="custom_plan_required",
                status_code=409,
            )
        current_rank = subscription_plan_change_service.PLAN_ORDER.get(
            str(plan.plan_code or ""), 0
        )
        required_rank = subscription_plan_change_service.PLAN_ORDER.get(
            str(snapshot.minimum_eligible_plan_code or ""), 0
        )
        if required_rank > current_rank:
            row = subscription_plan_change_service.preview_plan_change(
                db,
                account,
                snapshot.minimum_eligible_plan_code,
                proposed_branch_count=requested_quantity,
                proposed_system_user_count=proposed_system_users,
                proposed_teacher_count=proposed_teachers,
            )
            destination = f"/saas/subscription/plans/{row.request_uuid}/confirm"
        elif requested_quantity != int(context.subscription.quantity or 0):
            row = subscription_change_service.preview_quantity_change(
                db, account, requested_quantity
            )
            destination = f"/saas/subscription/branches/{row.request_uuid}/confirm"
        else:
            db.commit()
            return RedirectResponse(
                "/saas/subscription/branches?notice="
                + quote_plus(
                    "The proposed capacity fits your current plan and does not change billed branch quantity."
                ),
                status_code=302,
            )
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        params = (
            f"requested_quantity={requested_quantity}"
            f"&proposed_system_users={proposed_system_users if proposed_system_users is not None else ''}"
            f"&proposed_teachers={proposed_teachers if proposed_teachers is not None else ''}"
        )
        return _subscription_change_error(
            exc, f"/saas/subscription/branches?{params}"
        )
    except ValueError as exc:
        db.commit()
        params = (
            f"requested_quantity={requested_quantity}"
            f"&proposed_system_users={proposed_system_users if proposed_system_users is not None else ''}"
            f"&proposed_teachers={proposed_teachers if proposed_teachers is not None else ''}"
        )
        return _redirect_error(
            f"/saas/subscription/branches?{params}", str(exc)
        )
    return RedirectResponse(destination, status_code=302)


@router.get("/subscription/branches/{request_uuid}/confirm", response_class=HTMLResponse)
def confirm_subscription_branch_change_page(request_uuid: str, request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        row = subscription_change_service.get_confirmation_preview(db, account, request_uuid)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription/branches")
    return _render(request, "saas/subscription_branch_confirm.html", {
        "account": account,
        "change": subscription_change_service.customer_summary(row),
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "error": request.query_params.get("error", ""),
    })


@router.post("/subscription/branches/{request_uuid}/confirm")
def confirm_subscription_branch_change(
    request_uuid: str,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        row = subscription_change_service.submit_quantity_change(db, account, request_uuid)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, f"/saas/subscription/branches/{request_uuid}/confirm")
    notice = "Branch capacity payment is being confirmed." if row.change_type == subscription_change_service.INCREASE else "Branch capacity reduction scheduled for the next renewal."
    return RedirectResponse("/saas/subscription?notice=" + quote_plus(notice), status_code=302)


@router.post("/subscription/branches/{request_uuid}/cancel")
def cancel_subscription_branch_reduction(
    request_uuid: str,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        subscription_change_service.cancel_scheduled_reduction(db, account, request_uuid)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription")
    return RedirectResponse("/saas/subscription?notice=" + quote_plus("Scheduled branch reduction canceled."), status_code=302)


@router.get("/account/sessions", response_class=HTMLResponse)
def account_sessions(request: Request, db: Session = Depends(get_db)):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    sessions = db.query(models.SaaSSession).filter(
        models.SaaSSession.saas_account_id == account.id
    ).order_by(models.SaaSSession.last_seen_at.desc()).all()
    organization_account = _organization_account_shell_context(request, db, account)
    db.commit()
    return _render(
        request,
        "saas/sessions.html",
        {
            "account": account,
            "organization_account": organization_account,
            "sessions": sessions,
            "current_session_id": session_row.id,
            "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.post("/account/sessions/revoke-others")
def revoke_other_sessions(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    service.revoke_other_sessions(db, account, session_row.id)
    db.commit()
    return RedirectResponse("/saas/account/sessions?notice=Other+sessions+revoked.", status_code=302)


@router.post("/account/sessions/{session_id}/revoke")
def revoke_single_session(
    session_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, current_session, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    if service.hash_value(csrf_token) != str(current_session.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")
    target = db.query(models.SaaSSession).filter(
        models.SaaSSession.id == session_id,
        models.SaaSSession.saas_account_id == account.id,
    ).first()
    if target and target.id != current_session.id:
        service.revoke_session(db, target, reason="manual_revoke")
    db.commit()
    return RedirectResponse("/saas/account/sessions?notice=Session+revoked.", status_code=302)


@router.get("/onboarding")
def onboarding_root(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_pending_organization_for_account(db, account)
    db.commit()
    if not organization:
        return RedirectResponse("/saas/account", status_code=302)
    return RedirectResponse(service.organization_step_url(organization), status_code=302)


@router.post("/onboarding/start")
def start_onboarding(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.create_pending_organization(db, account, request=request)
    progress = service.recalculate_pending_progress(db, organization)
    service.update_pending_dashboard_status(account, organization, progress)
    db.commit()
    return RedirectResponse(service.organization_step_url(organization), status_code=302)


@router.get("/onboarding/{organization_uuid}/resume")
def resume_onboarding(organization_uuid: str, request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account?notice=No+School+Workspace+Setup+draft+was+found.", status_code=302)
    db.commit()
    return RedirectResponse(service.organization_step_url(organization), status_code=302)


@router.get("/onboarding/{organization_uuid}/organization", response_class=HTMLResponse)
def organization_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "organization")
    if locked_redirect:
        db.commit()
        return locked_redirect
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({
        "account": account,
        "error": error,
        "step_key": "organization",
        "setup_console": _onboarding_setup_console(db, account, "organization", organization),
    })
    return _render(request, "saas/onboarding_organization.html", context)


@router.post("/onboarding/{organization_uuid}/organization")
async def save_organization_step(
    organization_uuid: str,
    request: Request,
    organization_name: str = Form(""),
    legal_name: str = Form(""),
    website: str = Form(""),
    primary_domain: str = Form(""),
    phone: str = Form(""),
    educational_program: str = Form(""),
    country_code: str = Form(""),
    country_name: str = Form(""),
    region_id: str = Form(""),
    region_manual: str = Form(""),
    region_name: str = Form(""),
    city_id: str = Form(""),
    city_manual: str = Form(""),
    city_name: str = Form(""),
    district_name: str = Form(""),
    neighborhood_name: str = Form(""),
    school_type: str = Form(""),
    expected_branch_count: str = Form(""),
    expected_student_count: str = Form(""),
    expected_teacher_count: str = Form(""),
    estimated_staff_users: str = Form(""),
    timezone: str = Form(""),
    save_action: str = Form("continue"),
    organization_logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    form_data = {
        "organization_name": organization_name,
        "legal_name": legal_name,
        "website": website,
        "primary_domain": primary_domain,
        "phone": phone,
        "educational_program": educational_program,
        "country_code": country_code,
        "country_name": country_name,
        "region_id": region_id,
        "region_manual": region_manual,
        "region_name": region_name,
        "city_id": city_id,
        "city_manual": city_manual,
        "city_name": city_name,
        "district_name": district_name,
        "neighborhood_name": neighborhood_name,
        "school_type": school_type,
        "expected_branch_count": expected_branch_count,
        "expected_student_count": expected_student_count,
        "expected_teacher_count": expected_teacher_count,
        "estimated_staff_users": estimated_staff_users,
        "timezone": timezone,
    }
    previous_logo_path = str(organization.organization_logo_path or "").strip()
    new_logo_path = ""

    def render_save_error(message: str, status_code: int):
        refreshed = service.get_owned_pending_organization(
            db, account, organization_uuid
        )
        if not refreshed:
            return RedirectResponse("/saas/account", status_code=302)
        return _render_onboarding_step(
            request,
            db,
            account,
            refreshed,
            "saas/onboarding_organization.html",
            "organization",
            error=message,
            status_code=status_code,
            extra_context={"form_data": form_data},
        )

    try:
        resolved_location = _resolve_optional_location(
            country_code=country_code,
            region_id=region_id,
            region_manual=region_manual,
            city_id=city_id,
            city_manual=city_manual,
        )
        if resolved_location:
            country_code = resolved_location.country_code
            country_name = resolved_location.country_name
            region_name = resolved_location.region_name
            city_name = resolved_location.city_name
            form_data.update(
                {
                    "country_code": country_code,
                    "country_name": country_name,
                    "region_name": region_name,
                    "city_name": city_name,
                }
            )
        new_logo_path = service.save_organization_profile(
            db,
            organization,
            organization_name=organization_name,
            legal_name=legal_name,
            website=website,
            primary_domain=primary_domain,
            phone=phone,
            educational_program=educational_program,
            country_code=country_code,
            country_name=country_name,
            region_name=region_name,
            city_name=city_name,
            district_name=district_name,
            neighborhood_name=neighborhood_name,
            school_type=school_type,
            expected_branch_count=expected_branch_count,
            expected_student_count=expected_student_count,
            expected_teacher_count=expected_teacher_count,
            estimated_staff_users=estimated_staff_users,
            timezone=timezone,
            logo_file=organization_logo,
        )
        progress = service.save_draft(
            db, account, organization, current_step="branches"
        )
        service.log_pending_event(
            db,
            organization=organization,
            account=account,
            event_type="organization_saved",
            details={"completion_percent": progress.completion_percent},
        )
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="organization_profile_saved"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        service.delete_pending_logo_file(new_logo_path)
        return render_save_error(str(exc), 422)
    except service.PendingLogoStorageError:
        db.rollback()
        service.delete_pending_logo_file(new_logo_path)
        logger.exception(
            "Organization Profile logo storage failed account_id=%s organization_id=%s organization_uuid=%s content_type=%s",
            account.id,
            organization.id,
            organization_uuid,
            str(getattr(organization_logo, "content_type", "") or ""),
        )
        return render_save_error(
            "The organization logo could not be saved right now. "
            "Please try again, or continue without replacing it.",
            503,
        )
    except Exception:
        db.rollback()
        service.delete_pending_logo_file(new_logo_path)
        logger.exception(
            "Organization Profile save failed account_id=%s organization_id=%s organization_uuid=%s",
            account.id,
            organization.id,
            organization_uuid,
        )
        return render_save_error(
            "Organization Profile could not be saved. "
            "Your existing information was preserved.",
            500,
        )
    if new_logo_path and previous_logo_path and previous_logo_path != new_logo_path:
        if not service.delete_pending_logo_file(previous_logo_path):
            logger.warning(
                "Previous pending organization logo was not removed account_id=%s organization_id=%s organization_uuid=%s",
                account.id,
                organization.id,
                organization_uuid,
            )
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/branches", status_code=302)


@router.get("/onboarding/{organization_uuid}/branches", response_class=HTMLResponse)
def branches_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "branches")
    if locked_redirect:
        db.commit()
        return locked_redirect
    context = _onboarding_context(db, account, organization)
    if not context.get("branches"):
        initial_count = max(1, int(getattr(organization, "expected_branch_count", 0) or 1))
        context["initial_branch_rows"] = range(initial_count)
    db.commit()
    context.update({
        "account": account,
        "error": error,
        "step_key": "branches",
        "setup_console": _onboarding_setup_console(db, account, "branches", organization),
    })
    return _render(request, "saas/onboarding_branches.html", context)


@router.post("/onboarding/{organization_uuid}/branches")
def save_branches_step(
    organization_uuid: str,
    request: Request,
    branch_uuid: list[str] = Form([]),
    branch_name: list[str] = Form([]),
    location: list[str] = Form([]),
    country_code: list[str] = Form([]),
    country_name: list[str] = Form([]),
    region_name: list[str] = Form([]),
    city_name: list[str] = Form([]),
    district_name: list[str] = Form([]),
    neighborhood_name: list[str] = Form([]),
    estimated_system_users: list[str] = Form([]),
    estimated_teachers: list[str] = Form([]),
    primary_branch_index: str = Form("0"),
    save_action: str = Form("continue"),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "branches")
    if locked_redirect:
        db.commit()
        return locked_redirect
    branch_rows = []
    max_rows = max(
        len(branch_uuid),
        len(branch_name),
        len(location),
        len(country_code),
        len(country_name),
        len(region_name),
        len(city_name),
        len(district_name),
        len(neighborhood_name),
        len(estimated_system_users),
        len(estimated_teachers),
        0,
    )
    for index in range(max_rows):
        branch_rows.append(
            {
                "branch_uuid": branch_uuid[index] if index < len(branch_uuid) else "",
                "branch_name": branch_name[index] if index < len(branch_name) else "",
                "location": location[index] if index < len(location) else "",
                "country_code": country_code[index] if index < len(country_code) else "",
                "country_name": country_name[index] if index < len(country_name) else "",
                "region_name": region_name[index] if index < len(region_name) else "",
                "city_name": city_name[index] if index < len(city_name) else "",
                "district_name": district_name[index] if index < len(district_name) else "",
                "neighborhood_name": neighborhood_name[index] if index < len(neighborhood_name) else "",
                "estimated_system_users": estimated_system_users[index] if index < len(estimated_system_users) else None,
                "estimated_teachers": estimated_teachers[index] if index < len(estimated_teachers) else None,
            }
        )
    try:
        selected_primary_index = int(str(primary_branch_index or "0").strip())
    except ValueError:
        selected_primary_index = 0
    if branch_rows and 0 <= selected_primary_index < len(branch_rows):
        primary_row = branch_rows.pop(selected_primary_index)
        branch_rows.insert(0, primary_row)
    try:
        service.replace_branches(
            db,
            organization,
            branch_rows,
            require_capacity_estimates=True,
        )
        progress = service.save_draft(db, account, organization, current_step="academic_setup")
        service.log_pending_event(db, organization=organization, account=account, event_type="branches_saved", details={"completion_percent": progress.completion_percent})
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="branch_setup_saved"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        organization = service.get_owned_pending_organization(db, account, organization_uuid)
        if not organization:
            return RedirectResponse("/saas/account", status_code=302)
        return _render_onboarding_step(
            request,
            db,
            account,
            organization,
            "saas/onboarding_branches.html",
            "branches",
            error=str(exc),
            status_code=422,
            extra_context={
                "form_branches": branch_rows,
                "branch_capacity_totals": service.pending_branch_capacity_totals(
                    branch_rows
                ),
                "selected_primary_index": 0,
            },
        )
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(
        f"/saas/onboarding/{organization_uuid}/academic_setup?notice="
        + quote_plus(
            "Your branch count was updated. Your subscription total will be recalculated before payment."
        ),
        status_code=302,
    )


@router.get("/onboarding/{organization_uuid}/academic_setup", response_class=HTMLResponse)
def academic_setup_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "academic_setup")
    if locked_redirect:
        db.commit()
        return locked_redirect
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({
        "account": account,
        "error": error,
        "notice": notice,
        "step_key": "academic_setup",
        "setup_console": _onboarding_setup_console(db, account, "academic_setup", organization),
    })
    return _render(request, "saas/onboarding_academic_setup.html", context)


@router.post("/onboarding/{organization_uuid}/academic_setup")
def save_academic_setup_step(
    organization_uuid: str,
    request: Request,
    first_academic_year_name: str = Form(""),
    create_default_branch: str = Form(""),
    notes: str = Form(""),
    save_action: str = Form("continue"),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "academic_setup")
    if locked_redirect:
        db.commit()
        return locked_redirect
    try:
        service.save_academic_setup(
            db,
            organization,
            first_academic_year_name=first_academic_year_name,
            create_default_branch=create_default_branch,
            notes=notes,
        )
        progress = service.save_draft(db, account, organization, current_step="contacts")
        service.log_pending_event(db, organization=organization, account=account, event_type="academic_setup_saved", details={"completion_percent": progress.completion_percent})
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="academic_setup_saved"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        organization = service.get_owned_pending_organization(db, account, organization_uuid)
        if not organization:
            return RedirectResponse("/saas/account", status_code=302)
        return _render_onboarding_step(
            request,
            db,
            account,
            organization,
            "saas/onboarding_academic_setup.html",
            "academic_setup",
            error=str(exc),
            status_code=422,
            extra_context={
                "form_data": {
                    "first_academic_year_name": first_academic_year_name,
                    "create_default_branch": create_default_branch,
                    "notes": notes,
                },
            },
        )
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/contacts", status_code=302)


@router.get("/onboarding/{organization_uuid}/contacts", response_class=HTMLResponse)
def contacts_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "contacts")
    if locked_redirect:
        db.commit()
        return locked_redirect
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({
        "account": account,
        "error": error,
        "step_key": "contacts",
        "setup_console": _onboarding_setup_console(db, account, "contacts", organization),
    })
    return _render(request, "saas/onboarding_contacts.html", context)


@router.post("/onboarding/{organization_uuid}/contacts")
def save_contacts_step(
    organization_uuid: str,
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    job_title: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    save_action: str = Form("continue"),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "contacts")
    if locked_redirect:
        db.commit()
        return locked_redirect
    try:
        service.save_primary_contact(
            db,
            organization,
            first_name=first_name or account.first_name or "",
            last_name=last_name or account.last_name or "",
            job_title=job_title,
            email=email or account.email or "",
            phone=phone,
        )
        progress = service.save_draft(db, account, organization, current_step="review")
        service.log_pending_event(db, organization=organization, account=account, event_type="contacts_saved", details={"completion_percent": progress.completion_percent})
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="contacts_saved"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        organization = service.get_owned_pending_organization(db, account, organization_uuid)
        if not organization:
            return RedirectResponse("/saas/account", status_code=302)
        return _render_onboarding_step(
            request,
            db,
            account,
            organization,
            "saas/onboarding_contacts.html",
            "contacts",
            error=str(exc),
            status_code=422,
            extra_context={
                "form_data": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "job_title": job_title,
                    "email": email,
                    "phone": phone,
                },
            },
        )
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/review", status_code=302)


@router.get("/onboarding/{organization_uuid}/review", response_class=HTMLResponse)
def review_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "review")
    if locked_redirect:
        db.commit()
        return locked_redirect
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({
        "account": account,
        "error": error,
        "step_key": "review",
        "setup_console": _onboarding_setup_console(db, account, "review", organization),
        "missing_requirements": service.get_onboarding_missing_requirements(db, organization),
    })
    return _render(request, "saas/onboarding_review.html", context)


@router.post("/onboarding/{organization_uuid}/save-draft")
def save_draft_exit(
    organization_uuid: str,
    request: Request,
    current_step: str = Form("organization"),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_pre_payment_edit_redirect(organization)
    if locked_redirect:
        db.commit()
        return locked_redirect
    service.save_draft(db, account, organization, current_step=current_step)
    db.commit()
    return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)


@router.post("/onboarding/{organization_uuid}/submit")
def submit_onboarding(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "review")
    if locked_redirect:
        db.commit()
        return locked_redirect
    try:
        service.submit_pending_organization(db, account, organization)
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="review_submitted"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        organization = service.get_owned_pending_organization(db, account, organization_uuid)
        if not organization:
            return RedirectResponse("/saas/account", status_code=302)
        return _render_onboarding_step(
            request,
            db,
            account,
            organization,
            "saas/onboarding_review.html",
            "review",
            error=str(exc),
            status_code=422,
        )
    return RedirectResponse(
        f"/saas/onboarding/{organization_uuid}/commercial-choice",
        status_code=302,
    )


@router.get("/onboarding/{organization_uuid}/commercial-choice", response_class=HTMLResponse)
def commercial_choice_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        demo_request_service.validate_commercial_choice(db, account, organization)
    except demo_request_service.DemoRequestError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas/account?notice={quote_plus(str(exc))}",
            status_code=302,
        )
    demo_request = demo_request_service.get_latest_for_organization(db, organization)
    if demo_request and demo_request.status in {
        DemoRequestStatus.PENDING_REVIEW.value,
        DemoRequestStatus.APPROVED.value,
    }:
        db.commit()
        return RedirectResponse(f"/saas/demo-requests/{demo_request.request_uuid}", status_code=302)
    branch_count = service.count_billable_pending_branches(db, organization)
    preferred_intent = service.normalize_commercial_intent(
        getattr(organization, "commercial_intent", "")
        or getattr(account, "signup_intent", "")
    )
    db.commit()
    return _render(
        request,
        "saas/commercial_choice.html",
        {
            "account": account,
            "organization": organization,
            "demo_request": demo_request,
            "branch_count": branch_count,
            "preferred_intent": preferred_intent,
            "error": error,
            "notice": notice,
        },
    )


@router.post("/onboarding/{organization_uuid}/commercial-choice/request-demo")
def request_demo_step(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        row = demo_request_service.submit_demo_request(db, account, organization)
        draft_lifecycle_service.record_meaningful_activity(
            db,
            account,
            organization=organization,
            source="demo_request_submitted",
        )
        db.commit()
        _dispatch_demo_email_best_effort(db, row.id)
    except demo_request_service.DemoRequestError as exc:
        db.rollback()
        audit.write_audit_event({
            "event_type": "saas_demo_request",
            "action": "submit",
            "result": "blocked",
            "actor_saas_account_id": int(getattr(account, "id", 0) or 0),
            "pending_organization_id": int(getattr(organization, "id", 0) or 0),
        })
        return RedirectResponse(
            f"/saas/onboarding/{organization_uuid}/commercial-choice?error={quote_plus(str(exc))}",
            status_code=302,
        )
    audit.write_audit_event({
        "event_type": "saas_demo_request",
        "action": "submit",
        "result": "success",
        "actor_saas_account_id": int(account.id),
        "pending_organization_id": int(organization.id),
        "demo_request_uuid": row.request_uuid,
    })
    return RedirectResponse(
        f"/saas/demo-requests/{row.request_uuid}?notice="
        + quote_plus("Your demo request has been submitted for review."),
        status_code=302,
    )


@router.post("/onboarding/{organization_uuid}/commercial-choice/subscribe")
def subscribe_now_step(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        demo_request_service.prepare_subscription_choice(db, account, organization)
        draft_lifecycle_service.record_meaningful_activity(
            db,
            account,
            organization=organization,
            source="subscription_path_selected",
        )
        db.commit()
    except demo_request_service.DemoRequestError as exc:
        db.rollback()
        demo_request = demo_request_service.get_latest_for_organization(
            db, organization
        )
        if demo_request and demo_request.status == DemoRequestStatus.APPROVED.value:
            return RedirectResponse(
                f"/saas/demo-requests/{demo_request.request_uuid}?error="
                + quote_plus(str(exc)),
                status_code=302,
            )
        return RedirectResponse(
            f"/saas/onboarding/{organization_uuid}/commercial-choice?error={quote_plus(str(exc))}",
            status_code=302,
        )
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/plan", status_code=302)


def _promo_activation_context(db: Session, account, organization_uuid: str):
    requested = str(organization_uuid or "").strip()
    organization = service.get_owned_pending_organization(db, account, requested) if requested else None
    if organization is not None and not service.initial_checkout_is_closed(db, organization):
        return organization, None, None
    _accesses, selected = customer_journey_service.select_organization_account_access(
        db, account, organization_uuid=requested
    )
    if selected is None and not requested:
        _accesses, selected = customer_journey_service.select_organization_account_access(db, account)
    if selected is None or not selected.is_owner:
        raise promo_redemption_service.PromoActivationError(
            "promo_owner_relationship_required",
            "Only the organization owner can activate a promo.",
        )
    return None, selected.school_group, selected.operational_user


def _promo_customer_error_redirect(organization_uuid: str, message: str):
    target = "/saas/promo?error=" + quote_plus(str(message or promo_redemption_service.GENERIC_INVALID_MESSAGE))
    if organization_uuid:
        target += "&organization_uuid=" + quote_plus(str(organization_uuid))
    return RedirectResponse(target, status_code=302)


@router.get("/promo", response_class=HTMLResponse)
def promo_activation_entry(
    request: Request,
    organization_uuid: str = Query(""),
    error: str = Query(""),
    notice: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db, next_path="/saas/promo")
    if redirect:
        return redirect
    try:
        organization, group, _user = _promo_activation_context(db, account, organization_uuid)
    except promo_redemption_service.PromoActivationError as exc:
        db.rollback()
        return RedirectResponse("/saas/account?notice=" + quote_plus(str(exc)), status_code=302)
    open_query = db.query(models.PromoActivationSession).filter(
        models.PromoActivationSession.saas_account_id == account.id,
        models.PromoActivationSession.status == "open",
    )
    if organization is not None:
        open_query = open_query.filter(models.PromoActivationSession.pending_organization_id == organization.id)
    else:
        open_query = open_query.filter(models.PromoActivationSession.school_group_id == group.id)
    existing = open_query.one_or_none()
    if existing:
        db.commit()
        return RedirectResponse(f"/saas/promo/{existing.activation_uuid}", status_code=302)
    db.commit()
    return _render(request, "saas/promo_activation.html", {
        "account": account,
        "organization": organization,
        "school_group": group,
        "organization_uuid": organization_uuid or str(getattr(group, "workspace_uuid", "") or ""),
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "review": None,
        "error": error,
        "notice": notice,
    })


@router.post("/promo/start")
def promo_activation_start(
    request: Request,
    promo_code: str = Form(""),
    organization_uuid: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db, next_path="/saas/promo")
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    if service.is_rate_limited(
        db, event_type="promo_lookup_failed", request=request,
        account_id=account.id, max_attempts=10, window_minutes=15,
    ):
        db.rollback()
        return _promo_customer_error_redirect(
            organization_uuid,
            "Too many promo attempts were made. Please wait before trying again.",
        )
    try:
        organization, group, operational_user = _promo_activation_context(db, account, organization_uuid)
        review = promo_redemption_service.start_activation(
            db,
            account=account,
            raw_code=promo_code,
            pending_organization=organization,
            school_group=group,
            operational_user=operational_user,
            idempotency_key=str(request.headers.get("x-request-id") or uuid.uuid4()),
            request_correlation_id=str(request.headers.get("x-request-id") or ""),
        )
        service.log_auth_event(
            db, event_type="promo_lookup_succeeded", account_id=account.id,
            request=request, details={"activation_session_id": review.session.id},
        )
        db.commit()
    except promo_redemption_service.PromoActivationError as exc:
        db.rollback()
        service.log_auth_event(
            db, event_type="promo_lookup_failed", event_status="blocked",
            account_id=account.id, request=request,
            details={"reason_code": exc.reason_code},
        )
        db.commit()
        logger.info("Promo activation lookup blocked account_id=%s reason=%s", account.id, exc.reason_code)
        return _promo_customer_error_redirect(organization_uuid, str(exc))
    return RedirectResponse(f"/saas/promo/{review.session.activation_uuid}", status_code=302)


@router.get("/promo/{activation_uuid}", response_class=HTMLResponse)
def promo_activation_review_page(
    activation_uuid: str,
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        review = promo_redemption_service.get_activation_review(db, activation_uuid, account)
        db.commit()
    except promo_redemption_service.PromoActivationError as exc:
        db.rollback()
        return RedirectResponse("/saas/account?notice=" + quote_plus(str(exc)), status_code=302)
    if review.session.status == "activated":
        return RedirectResponse("/saas/account?notice=" + quote_plus("Promo access is active."), status_code=302)
    return _render(request, "saas/promo_activation.html", {
        "account": account,
        "organization": review.organization,
        "school_group": review.school_group,
        "organization_uuid": "",
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "review": review,
        "error": error,
        "notice": notice,
    })


@router.post("/promo/{activation_uuid}/branches")
def promo_activation_select_branches(
    activation_uuid: str,
    request: Request,
    branch_ids: list[int] = Form(default=[]),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        promo_redemption_service.select_branches(
            db, activation_uuid=activation_uuid, account=account, branch_ids=branch_ids
        )
        db.commit()
    except promo_redemption_service.PromoActivationError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas/promo/{activation_uuid}?error={quote_plus(str(exc))}", status_code=302
        )
    return RedirectResponse(
        f"/saas/promo/{activation_uuid}?notice={quote_plus('Branch selection saved.')}", status_code=302
    )


@router.post("/promo/{activation_uuid}/activate")
def promo_activation_complete(
    activation_uuid: str,
    request: Request,
    idempotency_key: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        result = promo_redemption_service.activate_promo(
            db, activation_uuid=activation_uuid, account=account,
            idempotency_key=idempotency_key or f"promo-activate:{activation_uuid}",
        )
        db.commit()
    except promo_redemption_service.PromoActivationError as exc:
        db.rollback()
        promo_redemption_service.record_failed_activation(
            db,
            activation_uuid=activation_uuid,
            account=account,
            failure_code=exc.reason_code,
            operation_key=f"promo-activate-failed:{activation_uuid}:{exc.reason_code}",
        )
        db.commit()
        logger.warning(
            "Promo activation failed account_id=%s activation_uuid=%s reason=%s",
            account.id, activation_uuid, exc.reason_code,
        )
        return RedirectResponse(
            f"/saas/promo/{activation_uuid}?error={quote_plus(str(exc))}", status_code=302
        )
    except Exception:
        db.rollback()
        try:
            promo_redemption_service.record_failed_activation(
                db,
                activation_uuid=activation_uuid,
                account=account,
                failure_code="unexpected_activation_error",
                operation_key=f"promo-activate-failed:{activation_uuid}:unexpected",
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.warning("Promo failure audit could not be persisted", exc_info=True)
        logger.exception(
            "Unexpected promo activation failure account_id=%s activation_uuid=%s",
            account.id,
            activation_uuid,
        )
        return RedirectResponse(
            f"/saas/promo/{activation_uuid}?error="
            + quote_plus("Promo activation could not be completed right now. Please try again."),
            status_code=302,
        )
    return RedirectResponse(
        "/saas/account?notice=" + quote_plus(
            f"{result.school_group.name} promo access is now active."
        ),
        status_code=302,
    )


@router.get("/demo-requests/{request_uuid}", response_class=HTMLResponse)
def customer_demo_request_status(
    request_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    row = demo_request_service.get_owned_request(db, account, request_uuid)
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Demo request not found.")
    card = demo_request_service.build_request_card(db, row)
    demo_conversion = demo_conversion_service.get_conversion_for_request(db, row)
    demo_lifecycle = (
        demo_lifecycle_service.resolve_demo_lifecycle(
            db,
            provisioning=card.provisioning,
        )
        if card.provisioning
        and card.provisioning.provisioning_status == "active"
        and not (
            demo_conversion
            and demo_conversion.status == "completed"
        )
        else None
    )
    lifecycle_notifications = demo_lifecycle_service.list_customer_notifications(
        db,
        card.provisioning,
        account.id,
    )
    db.commit()
    return _render(
        request,
        "saas/demo_request_status.html",
        {
            "account": account,
            "organization": card.organization,
            "demo_request": row,
            "status_label": demo_request_service.status_label(row.status),
            "status_tone": demo_request_service.status_tone(row.status),
            "branch_count": card.branch_count,
            "demo_provisioning": card.provisioning,
            "demo_lifecycle": demo_lifecycle,
            "demo_conversion": demo_conversion,
            "lifecycle_notifications": lifecycle_notifications,
            "format_lifecycle_datetime": demo_lifecycle_service.format_lifecycle_datetime,
            "provisioning_status_label": demo_provisioning_service.provisioning_status_label(
                card.provisioning
            ),
            "provisioning_status_tone": demo_provisioning_service.provisioning_status_tone(
                card.provisioning
            ),
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/demo-requests/{request_uuid}/withdraw")
def withdraw_customer_demo_request(
    request_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    row = demo_request_service.get_owned_request(db, account, request_uuid)
    if not row:
        db.rollback()
        raise HTTPException(status_code=404, detail="Demo request not found.")
    try:
        demo_request_service.withdraw_request(db, row, account)
        db.commit()
    except demo_request_service.DemoRequestError as exc:
        db.rollback()
        audit.write_audit_event({
            "event_type": "saas_demo_request",
            "action": "withdraw",
            "result": "blocked",
            "actor_saas_account_id": int(account.id),
            "demo_request_uuid": request_uuid,
        })
        return RedirectResponse(
            f"/saas/demo-requests/{request_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    audit.write_audit_event({
        "event_type": "saas_demo_request",
        "action": "withdraw",
        "result": "success",
        "actor_saas_account_id": int(account.id),
        "demo_request_uuid": request_uuid,
    })
    return RedirectResponse(
        f"/saas/demo-requests/{request_uuid}?notice=" + quote_plus("Demo request withdrawn."),
        status_code=302,
    )


@router.get("/onboarding/{organization_uuid}/plan", response_class=HTMLResponse)
def plan_selection_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        demo_request_service.ensure_subscription_path_available(db, organization)
    except demo_request_service.DemoRequestError:
        demo_request = demo_request_service.get_latest_for_organization(db, organization)
        db.rollback()
        if demo_request:
            return RedirectResponse(f"/saas/demo-requests/{demo_request.request_uuid}", status_code=302)
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    locked_redirect = _locked_pre_payment_edit_redirect(organization)
    if locked_redirect:
        db.commit()
        return locked_redirect
    try:
        billing_service.ensure_ready_for_checkout(organization)
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(f"/saas/account?notice={quote_plus(str(exc))}", status_code=302)
    context = _plan_context(db, account, organization)
    preferred_plan_code = service.preferred_plan_code_from_request(request)
    preferred_plan_option = next(
        (
            option
            for option in context["plan_options"]
            if option["plan_view"].plan.plan_code == preferred_plan_code
        ),
        None,
    )
    current_plan_selection = context.get("current_plan_selection")
    preferred_plan_is_eligible = bool(
        preferred_plan_option and preferred_plan_option["eligible"]
    )
    context["preferred_plan_code"] = (
        preferred_plan_code
        if preferred_plan_is_eligible and not current_plan_selection
        else ""
    )
    context["preferred_plan_adjusted"] = bool(
        preferred_plan_code
        and not current_plan_selection
        and not preferred_plan_is_eligible
    )
    initial_plan_id = int(
        getattr(current_plan_selection, "plan_id", 0)
        or (
            preferred_plan_option["plan_view"].plan.id
            if preferred_plan_is_eligible and not current_plan_selection
            else 0
        )
        or 0
    )
    initial_billing_interval = str(
        getattr(current_plan_selection, "billing_interval", "") or "monthly"
    ).strip().lower()
    if initial_billing_interval not in {"monthly", "annual"}:
        initial_billing_interval = "monthly"
    initial_plan_option = next(
        (
            option
            for option in context["plan_options"]
            if int(option["plan_view"].plan.id) == initial_plan_id
            and option["eligible"]
        ),
        None,
    )
    initial_plan_summary = None
    if initial_plan_option:
        unit_amount_minor = int(
            initial_plan_option[f"{initial_billing_interval}_amount_minor"]
        )
        total_amount_minor = unit_amount_minor * int(
            context["billable_branch_count"] or 0
        )
        initial_plan_summary = {
            "plan_id": initial_plan_id,
            "plan_name": initial_plan_option["plan_view"].plan.plan_name,
            "billing_interval": initial_billing_interval,
            "unit_formatted": f"USD {unit_amount_minor / 100:,.2f}",
            "total_formatted": f"USD {total_amount_minor / 100:,.2f}",
        }
    context["initial_plan_id"] = initial_plan_id
    context["initial_billing_interval"] = initial_billing_interval
    context["initial_plan_summary"] = initial_plan_summary
    context.update({
        "error": error,
        "setup_console": _payment_setup_console(
            db,
            account,
            "plan",
            organization=organization,
            checkout_summary=context.get("checkout_summary"),
            onboarding_summary=context.get("journey_card"),
        ),
    })
    db.commit()
    response = _render(request, "saas/plan_selection.html", context)
    if (
        request.cookies.get(service.SAAS_PREFERRED_PLAN_COOKIE)
        and (
            current_plan_selection
            or not preferred_plan_code
            or not preferred_plan_is_eligible
        )
    ):
        service.set_preferred_plan_cookie(
            response,
            preferred_plan_code="",
            request=request,
        )
    return response


@router.post("/onboarding/{organization_uuid}/plan")
def select_plan_step(
    organization_uuid: str,
    request: Request,
    plan_id: str = Form(""),
    billing_interval: str = Form("monthly"),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    try:
        demo_request_service.ensure_subscription_path_available(db, organization)
    except demo_request_service.DemoRequestError:
        demo_request = demo_request_service.get_latest_for_organization(db, organization)
        db.rollback()
        if demo_request:
            return RedirectResponse(f"/saas/demo-requests/{demo_request.request_uuid}", status_code=302)
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    locked_redirect = _locked_pre_payment_edit_redirect(organization)
    if locked_redirect:
        db.commit()
        return locked_redirect
    try:
        selection = billing_service.select_plan(
            db,
            organization,
            plan_id=int(plan_id or 0),
            billing_interval=billing_interval,
        )
        service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="plan_selected"
        )
        db.commit()
    except (ValueError, TypeError) as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/plan", str(exc))
    return service.set_preferred_plan_cookie(
        RedirectResponse(
            f"/saas/onboarding/{organization_uuid}/checkout?notice={quote_plus('Subscription plan saved.')}",
            status_code=302,
        ),
        preferred_plan_code="",
        request=request,
    )


@router.get("/onboarding/{organization_uuid}/checkout", response_class=HTMLResponse)
def checkout_summary_step(
    organization_uuid: str,
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    try:
        billing_service.ensure_ready_for_checkout(organization)
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(f"/saas/account?notice={quote_plus(str(exc))}", status_code=302)
    context = _plan_context(db, account, organization)
    checkout_summary = context.get("checkout_summary")
    if not checkout_summary or not checkout_summary.get("selection") or not checkout_summary.get("plan"):
        db.commit()
        return RedirectResponse(f"/saas/onboarding/{organization_uuid}/plan", status_code=302)
    draft_lifecycle_service.record_meaningful_activity(
        db, account, organization=organization, source="checkout_summary_opened"
    )
    safe_error = str(error or "")
    if any(
        marker in safe_error.lower()
        for marker in ("diagnostic:", "exact matches", "context matches")
    ):
        logger.warning(
            "Suppressed internal checkout diagnostic from customer response "
            "account_id=%s organization_id=%s",
            account.id,
            organization.id,
        )
        safe_error = payment_service.CUSTOMER_SAFE_PAYMENT_ACCOUNT_MESSAGE
    context.update({
        "error": safe_error,
        "notice": notice,
        "billing_contact": billing_identity_service.billing_identity_form(
            db, organization, account
        ),
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "setup_console": _payment_setup_console(
            db,
            account,
            "checkout",
            organization=organization,
            checkout_summary=context.get("checkout_summary"),
            onboarding_summary=context.get("journey_card"),
        ),
    })
    if safe_error:
        context["error"] = ""
        context["notice"] = ""
        context["setup_console"]["status_banner"] = (
            f"Secure Payment needs attention. {safe_error}"
        )
        context["setup_console"]["status_role"] = "alert"
        context["setup_console"]["status_tone"] = "attention"
        context["setup_console"]["primary_action"] = {
            "label": "Retry Secure Payment",
            "url": "",
            "kind": "form",
            "form_id": "checkout-launch-form",
        }
    db.commit()
    return _render(request, "saas/checkout_summary.html", context)


@router.post("/onboarding/{organization_uuid}/checkout/start")
def prepare_checkout_step(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    try:
        billing_service.create_or_update_checkout_session(db, organization)
        service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="checkout_started"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/checkout", str(exc))
    return RedirectResponse(
        f"/saas/onboarding/{organization_uuid}/checkout?notice={quote_plus('Secure Payment summary is ready.')}",
        status_code=302,
    )


def _prepare_checkout_for_launch_if_needed(db: Session, account, organization):
    billing_status = str(getattr(organization, "billing_status", "") or "").strip().lower()
    if billing_status in LAUNCHABLE_BILLING_STATUSES:
        if (
            billing_status
            in {payment_service.CHECKOUT_READY, payment_service.CHECKOUT_STARTED}
            and billing_service.checkout_quote_is_fresh(db, organization)
        ):
            return
        if billing_status == payment_service.PAYMENT_PROCESSING:
            raise ValueError("Secure Payment is already processing. Please view Subscription Status.")
        billing_service.create_or_update_checkout_session(db, organization)
        service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))
        return
    if billing_status not in PREPARE_BEFORE_LAUNCH_BILLING_STATUSES:
        raise ValueError("Secure Payment cannot be opened for this subscription. Please view Subscription Status.")
    billing_service.create_or_update_checkout_session(db, organization)
    service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))


@router.post("/onboarding/{organization_uuid}/checkout/launch")
def launch_checkout_step(
    organization_uuid: str,
    request: Request,
    billing_email: str = Form(...),
    billing_organization_name: str = Form(...),
    billing_contact_name: str = Form(""),
    company_number: str = Form(""),
    tax_identifier: str = Form(""),
    country_code: str = Form(...),
    country_name: str = Form(""),
    region_name: str = Form(""),
    city_name: str = Form(""),
    district_name: str = Form(""),
    neighborhood_name: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    closed_redirect = _closed_initial_checkout_redirect(db, organization)
    if closed_redirect:
        db.commit()
        return closed_redirect
    try:
        submitted = billing_identity_service.billing_identity_form(
            db, organization, account
        )
        billing_identity_service.save_billing_profile(
            db,
            organization,
            billing_email=billing_email or submitted.billing_email,
            billing_organization_name=(
                billing_organization_name
                or submitted.billing_organization_name
            ),
            billing_contact_name=(
                billing_contact_name or submitted.billing_contact_name
            ),
            company_number=company_number or submitted.company_number,
            tax_identifier=tax_identifier or submitted.tax_identifier,
            country_code=country_code or submitted.country_code,
            country_name=country_name or submitted.country_name,
            region_name=region_name or submitted.region_name,
            city_name=city_name or submitted.city_name,
            district_name=district_name or submitted.district_name,
            neighborhood_name=(
                neighborhood_name or submitted.neighborhood_name
            ),
        )
        _prepare_checkout_for_launch_if_needed(db, account, organization)
        launch = payment_service.launch_checkout(db, organization, account, request)
        service.update_pending_dashboard_status(account, organization, service.recalculate_pending_progress(db, organization))
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="checkout_launched"
        )
        db.commit()
    except payment_service.MissingPaddlePriceConfiguration:
        db.rollback()
        return _redirect_error(
            f"/saas/onboarding/{organization_uuid}/checkout",
            payment_service.CUSTOMER_SAFE_PAYMENT_CONFIG_MESSAGE,
        )
    except payment_service.PaymentCustomerResolutionError:
        db.rollback()
        return _redirect_error(
            f"/saas/onboarding/{organization_uuid}/checkout",
            payment_service.CUSTOMER_SAFE_PAYMENT_ACCOUNT_MESSAGE,
        )
    except billing_identity_service.BillingIdentitySyncError as exc:
        db.rollback()
        return _redirect_error(
            f"/saas/onboarding/{organization_uuid}/checkout",
            str(exc),
        )
    except paddle_client.PaddleAPIError as exc:
        logger.error(
            "paddle_checkout_launch_failed organization_uuid=%s "
            "error_code=%s status_code=%s error_type=%s",
            organization_uuid,
            str(getattr(exc, "error_code", "") or "unavailable"),
            str(getattr(exc, "status_code", "") or "unavailable"),
            exc.__class__.__name__,
            exc_info=True,
        )
        db.rollback()
        return _redirect_error(
            f"/saas/onboarding/{organization_uuid}/checkout",
            payment_service.CUSTOMER_SAFE_PAYMENT_PROVIDER_MESSAGE,
        )
    except ValueError as exc:
        logger.warning(
            "checkout_launch_rejected organization_uuid=%s "
            "billing_status=%s payment_status=%s error_type=%s error=%s",
            organization_uuid,
            str(getattr(organization, "billing_status", "") or ""),
            str(getattr(organization, "payment_status", "") or ""),
            exc.__class__.__name__,
            str(exc),
            exc_info=True,
        )
        db.rollback()
        return _redirect_error(f"/saas/onboarding/{organization_uuid}/checkout", str(exc))
    checkout_url = str(launch.get("checkout_url") or "").strip()
    if not checkout_url:
        return _redirect_error(
            f"/saas/onboarding/{organization_uuid}/checkout",
            "Secure Payment could not be opened. Please try again.",
        )
    return RedirectResponse(checkout_url, status_code=302)


@router.get("/checkout/return", response_class=HTMLResponse)
def checkout_return_page(
    request: Request,
    attempt: str = Query(""),
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    onboarding_summary = service.build_pending_dashboard_summary(db, account)
    current_attempt = None
    if onboarding_summary and attempt:
        current_attempt = onboarding_summary.get("current_payment_attempt")
        if not current_attempt or str(getattr(current_attempt, "attempt_uuid", "") or "") != str(attempt or "").strip():
            current_attempt = None
    organization = onboarding_summary["organization"] if onboarding_summary else None
    setup_console = _payment_setup_console(
        db,
        account,
        "return",
        organization=organization,
        onboarding_summary=onboarding_summary,
    )
    db.commit()
    return _render(
        request,
        "saas/checkout_return.html",
        {
            "account": account,
            "organization": organization,
            "onboarding_summary": onboarding_summary,
            "current_attempt": current_attempt,
            "setup_console": setup_console,
        },
    )


@router.get("/checkout/cancel", response_class=HTMLResponse)
def checkout_cancel_page(
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    onboarding_summary = service.build_pending_dashboard_summary(db, account)
    organization = onboarding_summary["organization"] if onboarding_summary else None
    setup_console = _payment_setup_console(
        db,
        account,
        "cancel",
        organization=organization,
        onboarding_summary=onboarding_summary,
    )
    db.commit()
    return _render(
        request,
        "saas/checkout_cancel.html",
        {
            "account": account,
            "organization": organization,
            "onboarding_summary": onboarding_summary,
            "setup_console": setup_console,
        },
    )


@router.get("/onboarding/{organization_uuid}/billing-status", response_class=HTMLResponse)
def billing_status_step(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    organization = service.get_owned_pending_organization(db, account, organization_uuid)
    if not organization:
        db.rollback()
        return RedirectResponse("/saas/account", status_code=302)
    context = _plan_context(db, account, organization)
    context.update({
        "setup_console": _payment_setup_console(
            db,
            account,
            "billing_status",
            organization=organization,
            checkout_summary=context.get("checkout_summary"),
            onboarding_summary=context.get("journey_card"),
        )
    })
    db.commit()
    return _render(request, "saas/billing_status.html", context)


@router.post("/webhooks/paddle")
async def paddle_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    try:
        result = payment_service.process_webhook(db, raw_body=raw_body, headers=dict(request.headers))
        db.commit()
    except ValueError as exc:
        db.commit()
        return PlainTextResponse(str(exc), status_code=400)
    except Exception:
        db.rollback()
        return PlainTextResponse("Webhook processing failed.", status_code=500)
    return PlainTextResponse(str(result.get("status") or "ok"), status_code=200)


@admin_router.get("/demo-requests", response_class=HTMLResponse)
def demo_request_review_queue(
    request: Request,
    q: str = Query(""),
    status: str = Query(""),
    sort: str = Query("submitted_desc"),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    error = request.query_params.get("error", "")
    try:
        cards = demo_request_service.list_review_queue(
            db,
            search=q,
            status=status,
            sort=sort,
        )
    except demo_request_service.DemoRequestError as exc:
        cards = []
        error = str(exc)
    counts = {
        "all": demo_request_service.count_requests(db),
        "pending_review": demo_request_service.count_requests(
            db, status=DemoRequestStatus.PENDING_REVIEW.value
        ),
        "approved": demo_request_service.count_requests(
            db, status=DemoRequestStatus.APPROVED.value
        ),
        "rejected": demo_request_service.count_requests(
            db, status=DemoRequestStatus.REJECTED.value
        ),
        "cancelled": demo_request_service.count_requests(
            db, status=DemoRequestStatus.CANCELLED.value
        ),
    }
    db.commit()
    return _render(
        request,
        "saas/admin_demo_requests.html",
        {
            "current_user": current_user,
            "cards": cards,
            "counts": counts,
            "search": q,
            "status_filter": status,
            "sort": sort,
            "status_options": demo_request_service.STATUS_LABELS,
            "status_label": demo_request_service.status_label,
            "status_tone": demo_request_service.status_tone,
            "notice": request.query_params.get("notice", ""),
            "error": error,
        },
    )


@admin_router.get("/demo-requests/{request_uuid}", response_class=HTMLResponse)
def demo_request_review_detail(
    request_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    row = demo_request_service.get_request_by_uuid(db, request_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Demo request not found.")
    card = demo_request_service.build_request_card(db, row)
    demo_conversion = demo_conversion_service.get_conversion_for_request(db, row)
    conversion_events = demo_conversion_service.list_conversion_events(
        db, demo_conversion
    )
    events = demo_request_service.list_events(db, row)
    provisioning_events = demo_provisioning_service.list_provisioning_events(
        db, card.provisioning
    )
    demo_lifecycle = (
        demo_lifecycle_service.resolve_demo_lifecycle(
            db,
            provisioning=card.provisioning,
        )
        if card.provisioning
        and card.provisioning.provisioning_status == "active"
        and not (
            demo_conversion
            and demo_conversion.status == "completed"
        )
        else None
    )
    lifecycle_events = demo_lifecycle_service.list_lifecycle_events(
        db, card.provisioning
    )
    lifecycle_notifications = demo_lifecycle_service.list_lifecycle_notifications(
        db, card.provisioning
    )
    commercial_state = (
        commercial_state_service.resolve_commercial_state(
            db,
            card.provisioning.school_group_id,
        )
        if card.provisioning and card.provisioning.school_group_id
        else None
    )
    try:
        entitlement_snapshot = json.loads(row.entitlement_snapshot_json or "{}")
    except (TypeError, ValueError):
        entitlement_snapshot = {"resolution_status": "manual_review"}
    effective_demo_access = (
        demo_access_service.resolve_access(
            db, card.provisioning.school_group_id
        )
        if card.provisioning and card.provisioning.school_group_id
        else None
    )
    demo_branches = (
        db.query(operational_models.Branch)
        .filter_by(school_group_id=card.provisioning.school_group_id)
        .order_by(operational_models.Branch.name).all()
        if card.provisioning and card.provisioning.school_group_id else []
    )
    demo_operation_audits = (
        db.query(models.DemoOperationAudit)
        .filter_by(demo_provisioning_id=card.provisioning.id)
        .order_by(models.DemoOperationAudit.created_at.desc())
        .limit(100).all()
        if card.provisioning else []
    )
    db.commit()
    return _render(
        request,
        "saas/admin_demo_request_detail.html",
        {
            "current_user": current_user,
            "card": card,
            "demo_request": row,
            "events": events,
            "provisioning_events": provisioning_events,
            "demo_provisioning": card.provisioning,
            "demo_lifecycle": demo_lifecycle,
            "demo_conversion": demo_conversion,
            "conversion_events": conversion_events,
            "lifecycle_events": lifecycle_events,
            "lifecycle_notifications": lifecycle_notifications,
            "effective_commercial_state": commercial_state,
            "format_lifecycle_datetime": demo_lifecycle_service.format_lifecycle_datetime,
            "provisioning_status_label": demo_provisioning_service.provisioning_status_label(
                card.provisioning
            ),
            "provisioning_status_tone": demo_provisioning_service.provisioning_status_tone(
                card.provisioning
            ),
            "entitlement_snapshot": entitlement_snapshot,
            "effective_demo_access": effective_demo_access,
            "demo_branches": demo_branches,
            "demo_operation_audits": demo_operation_audits,
            "demo_product_features": demo_feature_registry.list_features(),
            "demo_ai_features": ai_feature_registry.list_features(),
            "operation_key": str(uuid.uuid4()),
            "status_label": demo_request_service.status_label(row.status),
            "status_tone": demo_request_service.status_tone(row.status),
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


def _demo_operation_context(db: Session, request_uuid: str):
    row = demo_request_service.get_request_by_uuid(db, request_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Demo request not found.")
    provisioning = demo_provisioning_service.get_provisioning_for_request(db, row)
    if not provisioning:
        raise HTTPException(status_code=409, detail="Demo workspace is not provisioned.")
    return row, provisioning


def _demo_operation_redirect(request_uuid: str, *, notice: str = "", error: str = ""):
    name, value = ("error", error) if error else ("notice", notice)
    return RedirectResponse(
        f"/saas-admin/demo-requests/{request_uuid}?{name}={quote_plus(value)}",
        status_code=303,
    )


def _parse_demo_expiry(value: str, timezone_name: str | None):
    try:
        parsed = datetime.fromisoformat(str(value).strip())
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name or "UTC"))
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, KeyError) as exc:
        raise demo_operations_service.DemoOperationError(
            "Enter a valid expiry date and time.", reason_code="invalid_expiry"
        ) from exc


def _perform_demo_operation(
    db, request_uuid, current_user, operation, *, action, dispatch_email=True, **kwargs
):
    row, provisioning = _demo_operation_context(db, request_uuid)
    try:
        result = operation(
            db, actor=current_user, provisioning_id=provisioning.id, **kwargs
        )
        db.commit()
    except (demo_operations_service.DemoOperationError, demo_access_service.DemoAccessError) as exc:
        db.rollback()
        try:
            demo_operations_service.record_failed_operation(
                db, actor=current_user, provisioning_id=provisioning.id,
                action=action, reason=str(kwargs.get("reason") or ""),
                operation_key=kwargs.get("operation_key"),
                failure_code=getattr(exc, "reason_code", "operation_failed"),
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist demo operation failure audit")
        return _demo_operation_redirect(request_uuid, error=str(exc))
    if dispatch_email:
        _dispatch_demo_email_best_effort(db, row.id)
    return _demo_operation_redirect(request_uuid, notice="Demo operation completed.")


@admin_router.post("/demo-requests/{request_uuid}/operations/expire")
def expire_demo_operation(request_uuid: str, request: Request, reason: str = Form(...),
                          operation_key: str = Form(""), db: Session = Depends(get_db)):
    actor = _require_platform_owner(request, db)
    return _perform_demo_operation(
        db, request_uuid, actor, demo_operations_service.expire_demo_now,
        action="expire_demo", reason=reason, operation_key=operation_key,
    )


@admin_router.post("/demo-requests/{request_uuid}/operations/reactivate")
def reactivate_demo_operation(request_uuid: str, request: Request,
                              expires_at: str = Form(...), reason: str = Form(...),
                              operation_key: str = Form(""), db: Session = Depends(get_db)):
    actor = _require_platform_owner(request, db)
    row, provisioning = _demo_operation_context(db, request_uuid)
    organization = db.get(models.PendingOrganization, row.pending_organization_id)
    expiry = _parse_demo_expiry(
        expires_at, getattr(organization, "timezone", None)
    )
    return _perform_demo_operation(
        db, request_uuid, actor, demo_operations_service.reactivate_demo,
        action="reactivate_demo", new_expiry=expiry, reason=reason, operation_key=operation_key,
    )


@admin_router.post("/demo-requests/{request_uuid}/operations/expiry")
def change_demo_expiry_operation(request_uuid: str, request: Request,
                                 expires_at: str = Form(...), reason: str = Form(...),
                                 operation_key: str = Form(""), db: Session = Depends(get_db)):
    actor = _require_platform_owner(request, db)
    row, provisioning = _demo_operation_context(db, request_uuid)
    organization = db.get(models.PendingOrganization, row.pending_organization_id)
    expiry = _parse_demo_expiry(
        expires_at, getattr(organization, "timezone", None)
    )
    return _perform_demo_operation(
        db, request_uuid, actor, demo_operations_service.set_custom_expiry,
        action="set_custom_expiry", new_expiry=expiry, reason=reason, operation_key=operation_key,
    )


@admin_router.post("/demo-requests/{request_uuid}/operations/reminder")
def send_demo_reminder_operation(request_uuid: str, request: Request,
                                 reason: str = Form(""), operation_key: str = Form(""),
                                 db: Session = Depends(get_db)):
    actor = _require_platform_owner(request, db)
    return _perform_demo_operation(
        db, request_uuid, actor, demo_operations_service.send_final_day_reminder,
        action="send_manual_reminder", reason=reason, operation_key=operation_key,
    )


@admin_router.post("/demo-requests/{request_uuid}/operations/lifecycle")
def run_demo_lifecycle_operation(request_uuid: str, request: Request,
                                 reason: str = Form(""), operation_key: str = Form(""),
                                 db: Session = Depends(get_db)):
    actor = _require_platform_owner(request, db)
    return _perform_demo_operation(
        db, request_uuid, actor, demo_operations_service.run_lifecycle_for_demo,
        action="run_lifecycle", reason=reason, operation_key=operation_key,
    )


@admin_router.post("/demo-requests/{request_uuid}/operations/access")
def change_demo_access_operation(
    request_uuid: str, request: Request, profile: str = Form(...),
    reason: str = Form(...), product_features: list[str] = Form([]),
    ai_features: list[str] = Form([]), unrestricted_ai_features: list[str] = Form([]),
    branch_id: int | None = Form(None),
    ai_allowance_academic_assistant: int | None = Form(None),
    ai_allowance_exam_analysis: int | None = Form(None),
    ai_allowance_coaching_recommendations: int | None = Form(None),
    ai_allowance_action_plan_generation: int | None = Form(None),
    operation_key: str = Form(""), db: Session = Depends(get_db),
):
    actor = _require_platform_owner(request, db)
    form = {
        key: value for key, value in {
            "ai.academic_assistant": ai_allowance_academic_assistant,
            "ai.exam_analysis": ai_allowance_exam_analysis,
            "ai.coaching_recommendations": ai_allowance_coaching_recommendations,
            "ai.action_plan_generation": ai_allowance_action_plan_generation,
        }.items() if value is not None
    }
    return _perform_demo_operation(
        db, request_uuid, actor, demo_operations_service.change_access_profile,
        action="change_access_profile", branch_id=branch_id,
        profile=profile, reason=reason, product_features=product_features,
        ai_features=ai_features, unrestricted_ai_features=unrestricted_ai_features,
        ai_allowances=form, operation_key=operation_key,
    )


@admin_router.post("/demo-operations/run-lifecycle")
def run_all_demo_lifecycles(request: Request, reason: str = Form(""),
                            operation_key: str = Form(""),
                            db: Session = Depends(get_db)):
    actor = _require_platform_owner(request, db)
    factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    try:
        summary = demo_operations_service.run_lifecycle_for_all(
            factory, actor=actor, reason=reason, operation_key=operation_key
        )
    except demo_operations_service.DemoOperationError as exc:
        return RedirectResponse(
            f"/saas-admin/demo-requests?error={quote_plus(str(exc))}", status_code=303
        )
    message = (
        f"Lifecycle run: {summary.demos_checked} checked, "
        f"{summary.reminders_created} reminders, {summary.demos_expired} expired, "
        f"{summary.no_action_count} no action, {summary.failures} failures, "
        f"{summary.skipped_or_deduplicated} skipped."
    )
    return RedirectResponse(
        f"/saas-admin/demo-requests?notice={quote_plus(message)}", status_code=303
    )


def _demo_review_audit(current_user, row, *, action: str, result: str) -> None:
    audit.write_audit_event({
        "event_type": "saas_demo_request_review",
        "action": action,
        "result": result,
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "demo_request_uuid": str(getattr(row, "request_uuid", "") or ""),
        "pending_organization_id": int(getattr(row, "pending_organization_id", 0) or 0),
    })


@admin_router.post("/demo-requests/{request_uuid}/provision")
def provision_approved_demo_request(
    request_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    row = demo_request_service.get_request_by_uuid(db, request_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Demo request not found.")
    try:
        provisioning = demo_provisioning_service.get_provisioning_for_request(db, row)
        if provisioning and provisioning.provisioning_status == "active":
            if row.workspace_classification_snapshot != "customer_demo":
                raise demo_provisioning_service.DemoProvisioningError(
                    "The active demo request classification is inconsistent.",
                    reason_code="active_demo_classification_mismatch",
                )
        else:
            provisioning = demo_provisioning_service.provision_demo_workspace(
                db, row, current_user
            )
        db.commit()
    except demo_provisioning_service.DemoProvisioningError as exc:
        db.rollback()
        _demo_review_audit(current_user, row, action="provision", result="blocked")
        return RedirectResponse(
            f"/saas-admin/demo-requests/{request_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except Exception:
        db.rollback()
        _demo_review_audit(current_user, row, action="provision", result="failed")
        return RedirectResponse(
            f"/saas-admin/demo-requests/{request_uuid}?error="
            + quote_plus("Demo workspace provisioning could not be completed safely."),
            status_code=302,
        )
    result = (
        "success"
        if provisioning.provisioning_status == "active"
        else "failed"
    )
    _demo_review_audit(current_user, row, action="provision", result=result)
    message = (
        "Demo workspace provisioned and activated."
        if result == "success"
        else "Demo workspace provisioning failed. The approved request was preserved."
    )
    parameter = "notice" if result == "success" else "error"
    return RedirectResponse(
        f"/saas-admin/demo-requests/{request_uuid}?{parameter}={quote_plus(message)}",
        status_code=302,
    )


@admin_router.post("/demo-requests/{request_uuid}/approve")
def approve_demo_request(
    request_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    row = demo_request_service.get_request_by_uuid(db, request_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Demo request not found.")
    try:
        demo_request_service.approve_request(db, row, current_user)
        db.flush()
        provisioning = demo_provisioning_service.provision_demo_workspace(db, row, current_user)
        if provisioning.provisioning_status != "active":
            db.commit()
            _demo_review_audit(current_user, row, action="approve", result="provisioning_failed")
            return RedirectResponse(
                f"/saas-admin/demo-requests/{request_uuid}?error="
                + quote_plus("Demo approved, but workspace activation failed. Use the retry action."),
                status_code=302,
            )
        demo_notification_service.notify_platform_owners(
            db, row, "approved", provisioning=provisioning
        )
        demo_email_service.create_intent(
            db, row, "demo_approved", provisioning=provisioning
        )
        db.commit()
        _dispatch_demo_email_best_effort(db, row.id)
    except (demo_request_service.DemoRequestError, demo_provisioning_service.DemoProvisioningError) as exc:
        db.rollback()
        _demo_review_audit(current_user, row, action="approve", result="blocked")
        return RedirectResponse(
            f"/saas-admin/demo-requests/{request_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    _demo_review_audit(current_user, row, action="approve", result="success")
    return RedirectResponse(
        f"/saas-admin/demo-requests/{request_uuid}?notice="
        + quote_plus("Demo request approved and workspace activated."),
        status_code=302,
    )


@admin_router.post("/demo-requests/{request_uuid}/reject")
def reject_demo_request(
    request_uuid: str,
    request: Request,
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    row = demo_request_service.get_request_by_uuid(db, request_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Demo request not found.")
    try:
        demo_request_service.reject_request(db, row, current_user, reason=reason)
        db.commit()
        _dispatch_demo_email_best_effort(db, row.id)
    except demo_request_service.DemoRequestError as exc:
        db.rollback()
        _demo_review_audit(current_user, row, action="reject", result="blocked")
        return RedirectResponse(
            f"/saas-admin/demo-requests/{request_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    _demo_review_audit(current_user, row, action="reject", result="success")
    return RedirectResponse(
        f"/saas-admin/demo-requests/{request_uuid}?notice=" + quote_plus("Demo request rejected."),
        status_code=302,
    )


@admin_router.post("/demo-requests/{request_uuid}/cancel")
def cancel_demo_request(
    request_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    row = demo_request_service.get_request_by_uuid(db, request_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Demo request not found.")
    try:
        demo_request_service.cancel_request(db, row, current_user)
        db.commit()
    except demo_request_service.DemoRequestError as exc:
        db.rollback()
        _demo_review_audit(current_user, row, action="cancel", result="blocked")
        return RedirectResponse(
            f"/saas-admin/demo-requests/{request_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    _demo_review_audit(current_user, row, action="cancel", result="success")
    return RedirectResponse(
        f"/saas-admin/demo-requests/{request_uuid}?notice=" + quote_plus("Demo request cancelled."),
        status_code=302,
    )


@admin_router.get("/demo-eligibility-maintenance", response_class=HTMLResponse)
def demo_eligibility_maintenance(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    analyses = demo_eligibility_maintenance_service.list_eligibility_analyses(db)
    safe_count = sum(1 for analysis in analyses if analysis.safe_to_remove)
    return _render(
        request,
        "saas/admin_demo_eligibility_maintenance.html",
        {
            "current_user": current_user,
            "analyses": analyses,
            "safe_count": safe_count,
            "protected_count": len(analyses) - safe_count,
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.get(
    "/demo-eligibility-maintenance/{eligibility_id}/delete",
    response_class=HTMLResponse,
)
def confirm_delete_demo_eligibility(
    eligibility_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    try:
        analysis = demo_eligibility_maintenance_service.analyze_eligibility(
            db,
            eligibility_id,
        )
    except demo_eligibility_maintenance_service.DemoEligibilityMaintenanceBlocked as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _render(
        request,
        "saas/admin_delete_demo_eligibility.html",
        {
            "current_user": current_user,
            "analysis": analysis,
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.post("/demo-eligibility-maintenance/{eligibility_id}/delete")
def delete_demo_eligibility(
    eligibility_id: int,
    request: Request,
    confirmation_id: str = Form(""),
    confirm_delete: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if str(confirmation_id or "").strip() != str(eligibility_id):
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/demo-eligibility-maintenance/{eligibility_id}/delete?error="
            + quote_plus("Type the exact eligibility ID to confirm deletion."),
            status_code=302,
        )
    if str(confirm_delete or "").strip().lower() not in {"1", "true", "yes", "on"}:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/demo-eligibility-maintenance/{eligibility_id}/delete?error="
            + quote_plus("Explicit deletion confirmation is required."),
            status_code=302,
        )

    try:
        result = demo_eligibility_maintenance_service.delete_safe_orphan(
            db,
            eligibility_id,
        )
        db.commit()
    except demo_eligibility_maintenance_service.DemoEligibilityMaintenanceBlocked as exc:
        db.rollback()
        audit.write_audit_event(
            {
                "event_type": "historical_demo_eligibility_cleanup",
                "result": "blocked",
                "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
                "actor_username": str(getattr(current_user, "username", "") or ""),
                "actor_role": "Platform Owner",
                "eligibility_id": int(eligibility_id),
                "reason": str(exc),
            }
        )
        return RedirectResponse(
            "/saas-admin/demo-eligibility-maintenance?error="
            + quote_plus(str(exc)),
            status_code=302,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "demo_eligibility_maintenance database_failure eligibility_id=%s "
            "actor_user_id=%s exception=%s",
            eligibility_id,
            str(getattr(current_user, "user_id", "") or ""),
            exc,
        )
        audit.write_audit_event(
            {
                "event_type": "historical_demo_eligibility_cleanup",
                "result": "failed_rolled_back",
                "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
                "actor_username": str(getattr(current_user, "username", "") or ""),
                "actor_role": "Platform Owner",
                "eligibility_id": int(eligibility_id),
                "reason": demo_eligibility_maintenance_service.MAINTENANCE_REASON,
            }
        )
        return RedirectResponse(
            "/saas-admin/demo-eligibility-maintenance?error="
            + quote_plus("The reservation could not be deleted. All data was preserved."),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        logger.exception(
            "demo_eligibility_maintenance unexpected_failure eligibility_id=%s "
            "actor_user_id=%s exception=%s",
            eligibility_id,
            str(getattr(current_user, "user_id", "") or ""),
            exc,
        )
        audit.write_audit_event(
            {
                "event_type": "historical_demo_eligibility_cleanup",
                "result": "failed_rolled_back",
                "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
                "actor_username": str(getattr(current_user, "username", "") or ""),
                "actor_role": "Platform Owner",
                "eligibility_id": int(eligibility_id),
                "reason": demo_eligibility_maintenance_service.MAINTENANCE_REASON,
            }
        )
        return RedirectResponse(
            "/saas-admin/demo-eligibility-maintenance?error="
            + quote_plus("The reservation could not be deleted. All data was preserved."),
            status_code=302,
        )

    audit.write_audit_event(
        {
            "event_type": "historical_demo_eligibility_cleanup",
            "result": "success",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "actor_username": str(getattr(current_user, "username", "") or ""),
            "actor_role": "Platform Owner",
            "eligibility_id": result.eligibility_id,
            "normalized_domain": result.normalized_domain,
            "previous_status": result.previous_status,
            "reason": demo_eligibility_maintenance_service.MAINTENANCE_REASON,
        }
    )
    return RedirectResponse(
        "/saas-admin/demo-eligibility-maintenance?notice="
        + quote_plus(
            f"Eligibility ID {result.eligibility_id} was safely removed."
        ),
        status_code=302,
    )


@admin_router.get("/pending-organizations", response_class=HTMLResponse)
def pending_organizations_dashboard(
    request: Request,
    status: str = Query(""),
    view: str = Query("pending"),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    view_mode = "history" if str(view or "").strip().lower() == "history" else "pending"
    organizations = (
        service.list_organization_records(db, status=status)
        if view_mode == "history"
        else service.list_pending_organizations(db, status=status)
    )
    cards = [service.build_pending_card(db, organization) for organization in organizations]
    db.commit()
    return _render(
        request,
        "saas/admin_pending_organizations.html",
        {
            "current_user": current_user,
            "cards": cards,
            "status_filter": status,
            "view_mode": view_mode,
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.get("/pending-organizations/{organization_uuid}", response_class=HTMLResponse)
def pending_organization_detail(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_workspace_analyzer(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    card = service.build_pending_card(db, organization)
    academic_setup = service.get_or_create_academic_setup(db, organization)
    primary_contact = service.get_primary_contact(db, organization)
    branches = service.list_pending_branches(db, organization)
    events = service.list_pending_events(db, organization)
    notes = service.list_pending_notes(db, organization)
    can_delete_pending_organization = False
    if auth.is_platform_owner(current_user):
        try:
            service.validate_pending_organization_can_be_deleted(db, organization)
            can_delete_pending_organization = True
        except ValueError:
            pass
    db.commit()
    return _render(
        request,
        "saas/admin_pending_organization_detail.html",
        {
            "current_user": current_user,
            "card": card,
            "organization": organization,
            "academic_setup": academic_setup,
            "primary_contact": primary_contact,
            "branches": branches,
            "events": events,
            "notes": notes,
            "can_manage_pending_organization": auth.is_platform_owner(current_user),
            "can_delete_pending_organization": can_delete_pending_organization,
            "can_delete_test_account": (
                auth.is_platform_owner(current_user)
                and _test_account_reset_enabled()
                and bool(card.current_tenant_link)
            ),
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.get("/pending-organizations/{organization_uuid}/analyze-test-workspace", response_class=HTMLResponse)
def analyze_test_workspace(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_workspace_analyzer(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
    return _render(
        request,
        "saas/admin_workspace_analysis.html",
        {
            "current_user": current_user,
            "organization": organization,
            "analysis": analysis,
            "counts_by_category": {
                category: [row for row in analysis["counts"] if row.category == category]
                for category in dict.fromkeys(row.category for row in analysis["counts"])
            },
        },
    )


@admin_router.get("/pending-organizations/{organization_uuid}/delete-test-workspace", response_class=HTMLResponse)
def confirm_delete_test_workspace(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
    return _render(
        request,
        "saas/admin_delete_test_workspace.html",
        {
            "current_user": current_user,
            "organization": organization,
            "analysis": analysis,
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.post("/pending-organizations/{organization_uuid}/delete-test-workspace")
def delete_test_workspace(
    organization_uuid: str,
    request: Request,
    confirmation_name: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        _log_test_deletion(
            "early_exit",
            {
                "deletion_mode": "workspace_only",
                "organization_uuid": str(organization_uuid or ""),
                "authenticated_platform_owner": str(getattr(current_user, "user_id", "") or ""),
            },
            validation="organization_lookup",
            reason="pending_organization_not_found",
            values_checked={"organization_uuid": str(organization_uuid or "")},
        )
        audit.write_audit_event({
            "event_type": "test_workspace_deletion",
            "result": "blocked_not_found",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "reason": str(reason or "").strip()[:500],
        })
        raise HTTPException(status_code=404, detail="Pending organization not found.")

    diagnostic_context = _test_deletion_log_context(
        current_user,
        organization,
        deletion_mode="workspace_only",
    )
    _log_test_deletion("request_begin", diagnostic_context)
    organization_name = str(organization.organization_name or "")
    school_group_id = 0
    analysis_counts = {}
    _log_test_deletion("transaction_begin", diagnostic_context, transaction="BEGIN")
    try:
        analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
        school_group_id = int(analysis["school_group_id"] or 0)
        analysis_counts = {row.table: int(row.count or 0) for row in analysis["counts"]}
        diagnostic_context["workspace_id"] = school_group_id
        diagnostic_scope = workspace_deletion_service.deletion_diagnostic_scope(analysis)
        _log_test_deletion("pre_analysis", diagnostic_context, **diagnostic_scope)
        result = workspace_deletion_service.delete_test_workspace(
            db,
            organization,
            confirmation_name=confirmation_name,
            reason=reason,
        )
        db.commit()
        _log_test_deletion("transaction_commit", diagnostic_context, transaction="COMMIT")
    except workspace_deletion_service.WorkspaceDeletionBlocked as exc:
        db.rollback()
        _log_test_deletion(
            "transaction_rollback",
            diagnostic_context,
            transaction="ROLLBACK",
            validation="workspace_deletion_preflight",
            reason=str(exc),
            values_checked={
                "organization_name": organization_name,
                "confirmation_name_matches": confirmation_name == organization_name,
                "reason_present": bool(str(reason or "").strip()),
            },
        )
        audit.write_audit_event({
            "event_type": "test_workspace_deletion",
            "result": "blocked",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "organization_name": organization_name,
            "school_group_id": school_group_id,
            "reason": str(reason or "").strip()[:500],
            "analysis_counts": analysis_counts,
        })
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        _log_test_deletion("transaction_rollback", diagnostic_context, transaction="ROLLBACK")
        logger.exception(
            "test_workspace_deletion database_failure model=unknown table=unknown "
            "foreign_key_or_constraint=%s parent_object=pending_organization:%s "
            "child_object=unknown exception=%s",
            _constraint_name(exc),
            diagnostic_context["organization_id"],
            exc,
        )
        audit.write_audit_event({
            "event_type": "test_workspace_deletion",
            "result": "failed_rolled_back",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "organization_name": organization_name,
            "school_group_id": school_group_id,
            "reason": str(reason or "").strip()[:500],
            "analysis_counts": analysis_counts,
        })
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace?error="
            + quote_plus("The workspace could not be deleted. All data was preserved."),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        _log_test_deletion("transaction_rollback", diagnostic_context, transaction="ROLLBACK")
        logger.exception(
            "test_workspace_deletion unexpected_failure parent_object=pending_organization:%s "
            "workspace_id=%s exception_type=%s exception=%s",
            diagnostic_context["organization_id"],
            diagnostic_context["workspace_id"],
            type(exc).__name__,
            exc,
        )
        audit.write_audit_event({
            "event_type": "test_workspace_deletion",
            "result": "failed_rolled_back",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "organization_name": organization_name,
            "school_group_id": school_group_id,
            "reason": str(reason or "").strip()[:500],
            "analysis_counts": analysis_counts,
        })
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-workspace?error="
            + quote_plus("The workspace could not be deleted. All data was preserved."),
            status_code=302,
        )

    audit.write_audit_event({
        "event_type": "test_workspace_deletion",
        "result": "success",
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "organization_uuid": result.organization_uuid,
        "organization_name": result.organization_name,
        "school_group_id": result.school_group_id,
        "reason": str(reason or "").strip()[:500],
        "analysis_counts": result.analysis_counts,
        "deleted_records": result.deleted_records,
    })
    return RedirectResponse(
        "/saas-admin/pending-organizations?notice="
        + quote_plus("Test workspace permanently deleted."),
        status_code=302,
    )


@admin_router.get("/pending-organizations/{organization_uuid}/delete-test-account", response_class=HTMLResponse)
def confirm_delete_test_account(
    organization_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if not _test_account_reset_enabled():
        raise HTTPException(status_code=404, detail="Test account reset is not available.")
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    analysis = test_account_deletion_service.analyze_test_account(db, organization)
    return _render(
        request,
        "saas/admin_delete_test_account.html",
        {
            "current_user": current_user,
            "organization": organization,
            "analysis": analysis,
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.post("/pending-organizations/{organization_uuid}/delete-test-account")
def delete_test_account(
    organization_uuid: str,
    request: Request,
    confirmation_name: str = Form(""),
    confirmation_email: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if not _test_account_reset_enabled():
        raise HTTPException(status_code=404, detail="Test account reset is not available.")
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        _log_test_deletion(
            "early_exit",
            {
                "deletion_mode": "account_and_workspace",
                "organization_uuid": str(organization_uuid or ""),
                "authenticated_platform_owner": str(getattr(current_user, "user_id", "") or ""),
            },
            validation="organization_lookup",
            reason="pending_organization_not_found",
            values_checked={"organization_uuid": str(organization_uuid or "")},
        )
        audit.write_audit_event({
            "event_type": "test_account_workspace_deletion",
            "result": "blocked_not_found",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "reason": str(reason or "").strip()[:500],
        })
        raise HTTPException(status_code=404, detail="Pending organization not found.")

    diagnostic_context = _test_deletion_log_context(
        current_user,
        organization,
        deletion_mode="account_and_workspace",
    )
    _log_test_deletion("request_begin", diagnostic_context)
    safe_context = {
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "organization_uuid": str(organization.organization_uuid or ""),
        "organization_name": str(organization.organization_name or ""),
        "reason": str(reason or "").strip()[:500],
    }
    _log_test_deletion("transaction_begin", diagnostic_context, transaction="BEGIN")
    try:
        analysis = test_account_deletion_service.analyze_test_account(db, organization)
        diagnostic_context.update({
            "workspace_id": analysis.school_group_id,
            "account_id": analysis.account_id,
        })
        diagnostic_scope = test_account_deletion_service.deletion_diagnostic_scope(analysis)
        _log_test_deletion("pre_analysis", diagnostic_context, **diagnostic_scope)
        safe_context.update({
            "account_id": analysis.account_id,
            "account_uuid": analysis.account_uuid,
            "school_group_id": analysis.school_group_id,
            "analysis_counts": {
                row.table: int(row.count or 0)
                for row in analysis.workspace_analysis["counts"]
            },
        })
        result = test_account_deletion_service.delete_test_account_and_workspace(
            db,
            organization,
            confirmation_name=confirmation_name,
            confirmation_email=confirmation_email,
            reason=reason,
        )
        db.commit()
        _log_test_deletion("transaction_commit", diagnostic_context, transaction="COMMIT")
    except test_account_deletion_service.TestAccountDeletionBlocked as exc:
        db.rollback()
        _log_test_deletion(
            "transaction_rollback",
            diagnostic_context,
            transaction="ROLLBACK",
            validation="test_account_workspace_preflight",
            reason=str(exc),
            values_checked={
                "organization_name_matches": confirmation_name == safe_context["organization_name"],
                "account_email_confirmation_present": bool(str(confirmation_email or "").strip()),
                "reason_present": bool(str(reason or "").strip()),
            },
        )
        audit.write_audit_event({"event_type": "test_account_workspace_deletion", "result": "blocked", **safe_context})
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        _log_test_deletion("transaction_rollback", diagnostic_context, transaction="ROLLBACK")
        logger.exception(
            "test_account_workspace_deletion database_failure model=unknown table=unknown "
            "foreign_key_or_constraint=%s parent_object=pending_organization:%s "
            "child_object=selected_test_account:%s exception=%s",
            _constraint_name(exc),
            diagnostic_context["organization_id"],
            diagnostic_context["account_id"],
            exc,
        )
        audit.write_audit_event({"event_type": "test_account_workspace_deletion", "result": "failed_rolled_back", **safe_context})
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account?error="
            + quote_plus("The test account could not be deleted. All data was preserved."),
            status_code=302,
        )
    except Exception as exc:
        db.rollback()
        _log_test_deletion("transaction_rollback", diagnostic_context, transaction="ROLLBACK")
        logger.exception(
            "test_account_workspace_deletion unexpected_failure "
            "parent_object=pending_organization:%s child_object=selected_test_account:%s "
            "workspace_id=%s exception_type=%s exception=%s",
            diagnostic_context["organization_id"],
            diagnostic_context["account_id"],
            diagnostic_context["workspace_id"],
            type(exc).__name__,
            exc,
        )
        audit.write_audit_event({"event_type": "test_account_workspace_deletion", "result": "failed_rolled_back", **safe_context})
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account?error="
            + quote_plus("The test account could not be deleted. All data was preserved."),
            status_code=302,
        )

    audit.write_audit_event({
        "event_type": "test_account_workspace_deletion",
        "result": "success",
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "account_id": result.account_id,
        "account_uuid": result.account_uuid,
        "organization_uuid": result.organization_uuid,
        "organization_name": result.organization_name,
        "school_group_id": result.school_group_id,
        "reason": str(reason or "").strip()[:500],
        "analysis_counts": result.analysis_counts,
        "deleted_records": result.deleted_records,
    })
    return RedirectResponse(
        "/saas-admin/pending-organizations?notice="
        + quote_plus("Test account and workspace permanently deleted. The email can be registered again."),
        status_code=302,
    )


@admin_router.get("/accounts", response_class=HTMLResponse)
def saas_account_management(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    analyses = orphaned_test_account_service.list_account_analyses(db)
    return _render(
        request,
        "saas/admin_accounts.html",
        {
            "current_user": current_user,
            "analyses": analyses,
            "test_account_reset_enabled": _test_account_reset_enabled(),
            "notice": request.query_params.get("notice", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.get("/accounts/{account_uuid}/delete-orphaned-test-account", response_class=HTMLResponse)
def confirm_delete_orphaned_test_account(
    account_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if not _test_account_reset_enabled():
        raise HTTPException(status_code=404, detail="Orphaned test account deletion is not available.")
    account = db.query(models.SaaSAccount).filter(models.SaaSAccount.account_uuid == account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="TIS Account not found.")
    analysis = orphaned_test_account_service.analyze_orphaned_account(db, account)
    return _render(
        request,
        "saas/admin_delete_orphaned_test_account.html",
        {
            "current_user": current_user,
            "account": account,
            "analysis": analysis,
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.post("/accounts/{account_uuid}/delete-orphaned-test-account")
def delete_orphaned_test_account(
    account_uuid: str,
    request: Request,
    confirmation_email: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if not _test_account_reset_enabled():
        raise HTTPException(status_code=404, detail="Orphaned test account deletion is not available.")
    account = db.query(models.SaaSAccount).filter(models.SaaSAccount.account_uuid == account_uuid).first()
    if not account:
        audit.write_audit_event({
            "event_type": "orphaned_test_account_deletion",
            "result": "blocked_not_found",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "account_uuid": str(account_uuid or ""),
            "reason": str(reason or "").strip()[:500],
        })
        raise HTTPException(status_code=404, detail="TIS Account not found.")

    safe_context = {
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "account_id": int(account.id),
        "account_uuid": str(account.account_uuid or ""),
        "reason": str(reason or "").strip()[:500],
    }
    try:
        analysis = orphaned_test_account_service.analyze_orphaned_account(db, account)
        safe_context["analysis_counts"] = dict(analysis.counts)
        result = orphaned_test_account_service.delete_orphaned_test_account(
            db,
            account,
            confirmation_email=confirmation_email,
            reason=reason,
        )
        db.commit()
    except orphaned_test_account_service.OrphanedTestAccountDeletionBlocked as exc:
        db.rollback()
        audit.write_audit_event({
            "event_type": "orphaned_test_account_deletion",
            "result": "blocked",
            **safe_context,
        })
        return RedirectResponse(
            f"/saas-admin/accounts/{account_uuid}/delete-orphaned-test-account?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except Exception:
        db.rollback()
        audit.write_audit_event({
            "event_type": "orphaned_test_account_deletion",
            "result": "failed_rolled_back",
            **safe_context,
        })
        return RedirectResponse(
            f"/saas-admin/accounts/{account_uuid}/delete-orphaned-test-account?error="
            + quote_plus("The orphaned test account could not be deleted. All data was preserved."),
            status_code=302,
        )

    audit.write_audit_event({
        "event_type": "orphaned_test_account_deletion",
        "result": "success",
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "account_id": result.account_id,
        "account_uuid": result.account_uuid,
        "reason": str(reason or "").strip()[:500],
        "analysis_counts": result.analysis_counts,
        "deleted_records": result.deleted_records,
    })
    return RedirectResponse(
        "/saas-admin/accounts?notice="
        + quote_plus("Orphaned test account permanently deleted. The email can be registered again."),
        status_code=302,
    )


@admin_router.get("/accounts/{account_uuid}/delete-standalone-saas-account", response_class=HTMLResponse)
def confirm_delete_standalone_saas_account(
    account_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if not _test_account_reset_enabled():
        raise HTTPException(status_code=404, detail="Standalone SaaS account deletion is not available.")
    account = db.query(models.SaaSAccount).filter(models.SaaSAccount.account_uuid == account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="TIS Account not found.")
    analysis = orphaned_test_account_service.analyze_orphaned_account(db, account)
    return _render(
        request,
        "saas/admin_delete_standalone_saas_account.html",
        {
            "current_user": current_user,
            "account": account,
            "analysis": analysis,
            "error": request.query_params.get("error", ""),
        },
    )


@admin_router.post("/accounts/{account_uuid}/delete-standalone-saas-account")
def delete_standalone_saas_account(
    account_uuid: str,
    request: Request,
    confirmation_email: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    if not _test_account_reset_enabled():
        raise HTTPException(status_code=404, detail="Standalone SaaS account deletion is not available.")
    account = db.query(models.SaaSAccount).filter(models.SaaSAccount.account_uuid == account_uuid).first()
    if not account:
        audit.write_audit_event({
            "event_type": "standalone_saas_account_deletion",
            "result": "blocked_not_found",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "account_uuid": str(account_uuid or ""),
            "reason": str(reason or "").strip()[:500],
        })
        raise HTTPException(status_code=404, detail="TIS Account not found.")

    safe_context = {
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "account_id": int(account.id),
        "account_uuid": str(account.account_uuid or ""),
        "reason": str(reason or "").strip()[:500],
    }
    try:
        analysis = orphaned_test_account_service.analyze_orphaned_account(db, account)
        safe_context["analysis_counts"] = dict(analysis.counts)
        result = orphaned_test_account_service.delete_standalone_saas_account(
            db,
            account,
            confirmation_email=confirmation_email,
            reason=reason,
        )
        db.commit()
    except orphaned_test_account_service.StandaloneSaaSAccountDeletionBlocked as exc:
        db.rollback()
        audit.write_audit_event({
            "event_type": "standalone_saas_account_deletion",
            "result": "blocked",
            **safe_context,
        })
        return RedirectResponse(
            f"/saas-admin/accounts/{account_uuid}/delete-standalone-saas-account?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except Exception:
        db.rollback()
        audit.write_audit_event({
            "event_type": "standalone_saas_account_deletion",
            "result": "failed_rolled_back",
            **safe_context,
        })
        return RedirectResponse(
            f"/saas-admin/accounts/{account_uuid}/delete-standalone-saas-account?error="
            + quote_plus("The standalone SaaS account could not be deleted. All data was preserved."),
            status_code=302,
        )

    audit.write_audit_event({
        "event_type": "standalone_saas_account_deletion",
        "result": "success",
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "account_id": result.account_id,
        "account_uuid": result.account_uuid,
        "reason": str(reason or "").strip()[:500],
        "analysis_counts": result.analysis_counts,
        "deleted_records": result.deleted_records,
        "platform_identity_preserved": True,
    })
    return RedirectResponse(
        "/saas-admin/accounts?notice="
        + quote_plus("Standalone SaaS account deleted. The Platform identity remains unchanged."),
        status_code=302,
    )


@admin_router.get("/payments", response_class=HTMLResponse)
def payment_dashboard(
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    attempts = payment_service.list_payment_attempts(db)
    db.commit()
    return _render(
        request,
        "saas/admin_payments.html",
        {
            "current_user": current_user,
            "attempts": attempts,
            "notice": request.query_params.get("notice", ""),
        },
    )


@admin_router.get("/provisioning", response_class=HTMLResponse)
def provisioning_dashboard(
    request: Request,
    job_status: str = Query(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    jobs = provisioning_service.list_provisioning_jobs(db, job_status=job_status)
    job_cards = []
    for job in jobs:
        organization = db.query(models.PendingOrganization).filter(
            models.PendingOrganization.id == job.pending_organization_id
        ).first()
        contract = db.query(models.SubscriptionContract).filter(
            models.SubscriptionContract.id == job.subscription_contract_id
        ).first()
        tenant_link = None
        if getattr(job, "tenant_provisioning_link_id", None):
            tenant_link = db.query(models.TenantProvisioningLink).filter(
                models.TenantProvisioningLink.id == job.tenant_provisioning_link_id
            ).first()
        job_cards.append(
            {
                "job": job,
                "organization": organization,
                "contract": contract,
                "tenant_link": tenant_link,
            }
        )
    db.commit()
    return _render(
        request,
        "saas/admin_provisioning.html",
        {
            "current_user": current_user,
            "job_cards": job_cards,
            "job_status_filter": job_status,
            "notice": request.query_params.get("notice", ""),
        },
    )


@admin_router.post("/provisioning/run")
def run_provisioning_queue(
    request: Request,
    db: Session = Depends(get_db),
):
    _require_platform_owner(request, db)
    provisioning_service.process_pending_jobs(db, limit=25)
    db.commit()
    return RedirectResponse("/saas-admin/provisioning?notice=Provisioning+queue+processed.", status_code=302)


@admin_router.post("/provisioning/{job_uuid}/retry")
def retry_provisioning_job(
    job_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
):
    _require_platform_owner(request, db)
    job = db.query(models.ProvisioningJob).filter(
        models.ProvisioningJob.job_uuid == str(job_uuid or "").strip()
    ).first()
    if not job:
        db.rollback()
        raise HTTPException(status_code=404, detail="Provisioning job not found.")
    try:
        provisioning_service.retry_job(db, job)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/provisioning?notice={quote_plus(str(exc))}",
            status_code=302,
        )
    return RedirectResponse("/saas-admin/provisioning?notice=Provisioning+job+retried.", status_code=302)


@admin_router.post("/pending-organizations/{organization_uuid}/notes")
def add_pending_organization_note(
    organization_uuid: str,
    request: Request,
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    try:
        service.add_pending_note(
            db,
            organization,
            author_type="platform_owner",
            author_ref=str(getattr(current_user, "user_id", "") or ""),
            note=note,
            is_internal=True,
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="note_added",
            details={"author_user_id": str(getattr(current_user, "user_id", "") or "")},
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    return RedirectResponse(
        f"/saas-admin/pending-organizations/{organization_uuid}?notice=Note+saved.",
        status_code=302,
    )


@admin_router.post("/pending-organizations/{organization_uuid}/status")
def update_pending_organization_status(
    organization_uuid: str,
    request: Request,
    status: str = Form(""),
    rejection_reason: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")
    try:
        service.update_pending_status(
            db,
            organization,
            status=status,
            reviewer_user_id=str(getattr(current_user, "user_id", "") or ""),
            rejection_reason=rejection_reason,
        )
        service.log_pending_event(
            db,
            organization=organization,
            event_type="status_changed",
            details={"status": str(status or "").strip().lower()},
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )
    return RedirectResponse(
        f"/saas-admin/pending-organizations/{organization_uuid}?notice=Status+updated.",
        status_code=302,
    )


@admin_router.post("/pending-organizations/{organization_uuid}/delete")
def delete_pending_organization(
    organization_uuid: str,
    request: Request,
    confirm_delete: str = Form(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organization = service.get_pending_organization_by_uuid(db, organization_uuid)
    if not organization:
        db.rollback()
        raise HTTPException(status_code=404, detail="Pending organization not found.")

    if str(confirm_delete or "").strip().lower() not in {"1", "true", "yes", "on"}:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}?error="
            + quote_plus(
                "Delete confirmation is required before removing this pending organization."
            ),
            status_code=302,
        )

    try:
        service.delete_pending_organization(
            db,
            organization,
            actor_user_id=str(getattr(current_user, "user_id", "") or ""),
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}?error={quote_plus(str(exc))}",
            status_code=302,
        )

    return RedirectResponse(
        "/saas-admin/pending-organizations?notice="
        + quote_plus("Pending organization deleted."),
        status_code=302,
    )


@router.get("/auth/{provider}/start")
def oauth_start(provider: str, request: Request, next_path: str = Query("")):
    authorization_url, state_token, verifier = oauth.build_authorization_url(request, provider)
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        oauth.OAUTH_STATE_COOKIE,
        state_token,
        **auth.secure_cookie_kwargs(request, max_age=oauth.OAUTH_MAX_AGE_SECONDS),
    )
    response.set_cookie(
        oauth.OAUTH_PKCE_COOKIE,
        verifier,
        **auth.secure_cookie_kwargs(request, max_age=oauth.OAUTH_MAX_AGE_SECONDS),
    )
    if next_path:
        response.set_cookie(
            OAUTH_NEXT_COOKIE,
            _safe_next(next_path),
            **auth.secure_cookie_kwargs(
                request,
                max_age=oauth.OAUTH_MAX_AGE_SECONDS,
            ),
        )
    return response


@router.get("/auth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    db: Session = Depends(get_db),
):
    cookie_state = str(request.cookies.get(oauth.OAUTH_STATE_COOKIE) or "").strip()
    code_verifier = str(request.cookies.get(oauth.OAUTH_PKCE_COOKIE) or "").strip()
    if not state or not cookie_state or state != cookie_state:
        return PlainTextResponse("OAuth state validation failed.", status_code=400)
    state_payload = oauth.decode_state_token(state)
    if not state_payload or state_payload.get("provider") != str(provider or "").strip().lower():
        return PlainTextResponse("OAuth state is invalid or expired.", status_code=400)
    try:
        token_payload = oauth.exchange_code_for_tokens(request, provider, code, code_verifier)
        claims = oauth.verify_identity_token(provider, token_payload, state_payload.get("nonce", ""))
        account, policy = service.link_or_create_social_account(
            db,
            provider=provider,
            provider_subject=str(claims.get("sub") or "").strip(),
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            first_name=claims.get("given_name") or "",
            last_name=claims.get("family_name") or "",
            tenant_hint=claims.get("tid") or "",
            profile=claims,
            request=request,
        )
        session_token, csrf_token, _session_row = service.create_session(db, account, request=request)
        draft_lifecycle_service.record_meaningful_activity(
            db, account, source="successful_social_login"
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse("/saas/login?error=" + quote_plus(str(exc)), status_code=302)
    except Exception:
        db.rollback()
        return PlainTextResponse("OAuth sign-in could not be completed.", status_code=400)
    notice = quote_plus(str(policy.warning or ""))
    destination = _post_auth_destination(
        db,
        account,
        str(request.cookies.get(OAUTH_NEXT_COOKIE) or ""),
    )
    if notice and destination == "/saas/account":
        destination += f"?notice={notice}"
    response = RedirectResponse(
        destination,
        status_code=302,
    )
    response.delete_cookie(oauth.OAUTH_STATE_COOKIE, **auth.secure_cookie_kwargs(request))
    response.delete_cookie(oauth.OAUTH_PKCE_COOKIE, **auth.secure_cookie_kwargs(request))
    response.delete_cookie(OAUTH_NEXT_COOKIE, **auth.secure_cookie_kwargs(request))
    return service.set_session_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        request=request,
    )


def _promo_datetime(value: str | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError as exc:
        raise promo_code_service.PromoCodeError(
            "invalid_datetime", "Enter valid UTC dates and times."
        ) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _promo_form_values(form) -> dict:
    branch_ids = []
    for value in form.getlist("branch_ids"):
        try:
            branch_ids.append(int(value))
        except (TypeError, ValueError):
            raise promo_code_service.PromoCodeError(
                "invalid_branch_restriction", "Select valid eligible branches."
            )
    return {
        "title": form.get("title"),
        "internal_purpose": form.get("internal_purpose"),
        "subscription_plan_id": form.get("subscription_plan_id"),
        "max_branches": form.get("max_branches"),
        "max_system_users": form.get("max_system_users"),
        "max_teachers": form.get("max_teachers"),
        "scope_type": form.get("scope_type"),
        "school_group_id": form.get("school_group_id"),
        "pending_organization_id": form.get("pending_organization_id"),
        "intended_account_email_normalized": form.get("intended_account_email"),
        "permitted_email_domain_normalized": form.get("permitted_email_domain"),
        "branch_ids": tuple(branch_ids),
        "transferable": form.get("transferable") == "1",
        "one_redemption_per_organization": form.get("one_redemption_per_organization") == "1",
        "max_total_redemptions": form.get("max_total_redemptions"),
        "valid_from": _promo_datetime(form.get("valid_from")),
        "redemption_deadline": _promo_datetime(form.get("redemption_deadline")),
        "fixed_access_expires_at": _promo_datetime(form.get("fixed_access_expires_at")),
        "access_duration_days": form.get("access_duration_days"),
        "grace_period_days": form.get("grace_period_days"),
    }


def _promo_permissions(db: Session, current_user) -> dict:
    return {
        "can_view": auth.has_permission(db, current_user, "promo_codes.view"),
        "can_manage": auth.has_permission(db, current_user, "promo_codes.manage"),
        "is_owner": auth.is_platform_owner(current_user),
    }


def _promo_form_context(db: Session, current_user, *, promo=None, values=None, error=""):
    selected_branch_ids = set()
    if promo:
        selected_branch_ids = {
            row.branch_id
            for row in promo_code_service.list_branch_restrictions(db, promo.id)
            if row.branch_id
        }
    return {
        "current_user": current_user,
        "promo": promo,
        "form_values": values or {},
        "error": error,
        "plans": promo_code_service.list_available_plans(db),
        "school_groups": db.query(operational_models.SchoolGroup).order_by(
            operational_models.SchoolGroup.name
        ).all(),
        "pending_organizations": db.query(models.PendingOrganization).order_by(
            models.PendingOrganization.organization_name,
            models.PendingOrganization.id,
        ).all(),
        "branches": db.query(operational_models.Branch).order_by(
            operational_models.Branch.school_group_id,
            operational_models.Branch.name,
        ).all(),
        "selected_branch_ids": selected_branch_ids,
        "promo_permissions": _promo_permissions(db, current_user),
    }


def _record_promo_failure(
    db: Session, *, current_user, action: str, exc: promo_code_service.PromoCodeError,
    promo_uuid: str | None = None, operation_key: str | None = None,
    request: Request | None = None,
) -> None:
    try:
        promo_code_service.record_failed_action(
            db,
            actor=current_user,
            action=action,
            reason=str(exc),
            failure_code=exc.reason_code,
            promo_uuid=promo_uuid,
            operation_key=operation_key,
            request_correlation_id=(request.headers.get("x-request-id") if request else None),
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("promo_failure_audit_persist_failed action=%s", action, exc_info=True)


@admin_router.get("/promo-codes", response_class=HTMLResponse)
def promo_code_list(
    request: Request,
    lifecycle: str = Query(""),
    tier: str = Query(""),
    scope: str = Query(""),
    organization_id: int | None = Query(None),
    creator_id: int | None = Query(None),
    created_from: str = Query(""),
    valid_on: str = Query(""),
    expired: str = Query(""),
    db: Session = Depends(get_db),
):
    current_user = _require_promo_permission(request, db, "promo_codes.view")
    query = db.query(models.PromoCode)
    if lifecycle in promo_code_service.PROMO_STATUSES:
        query = query.filter(models.PromoCode.status == lifecycle)
    if tier in promo_code_service.PROMO_PLAN_CODES:
        query = query.join(models.SubscriptionPlan).filter(models.SubscriptionPlan.plan_code == tier)
    if scope in promo_code_service.PROMO_SCOPE_TYPES:
        query = query.filter(models.PromoCode.scope_type == scope)
    if organization_id:
        query = query.filter(models.PromoCode.school_group_id == organization_id)
    if creator_id:
        query = query.filter(models.PromoCode.created_by_user_id == creator_id)
    if created_from:
        parsed = _promo_datetime(created_from)
        if parsed:
            query = query.filter(models.PromoCode.created_at >= parsed)
    if valid_on:
        parsed = _promo_datetime(valid_on)
        if parsed:
            query = query.filter(
                models.PromoCode.valid_from <= parsed,
                models.PromoCode.redemption_deadline >= parsed,
            )
    promos = query.order_by(models.PromoCode.created_at.desc(), models.PromoCode.id.desc()).all()
    if expired in {"yes", "no"}:
        should_be_expired = expired == "yes"
        promos = [
            row for row in promos
            if (promo_code_service.effective_status(row) == "expired") == should_be_expired
        ]
    plan_by_id = {row.id: row for row in promo_code_service.list_available_plans(db)}
    creator_ids = {row.created_by_user_id for row in promos if row.created_by_user_id}
    creators = (
        db.query(operational_models.User).filter(operational_models.User.id.in_(creator_ids)).all()
        if creator_ids else []
    )
    creator_by_id = {row.id: row for row in creators}
    organizations = db.query(operational_models.SchoolGroup).order_by(
        operational_models.SchoolGroup.name
    ).all()
    cards = [{
        "promo": row,
        "masked_code": promo_code_service.masked_code(row),
        "effective_status": promo_code_service.effective_status(row),
        "plan": plan_by_id.get(row.subscription_plan_id),
        "creator": creator_by_id.get(row.created_by_user_id),
    } for row in promos]
    return _render(request, "saas/admin_promo_codes.html", {
        "current_user": current_user,
        "cards": cards,
        "plans": plan_by_id.values(),
        "organizations": organizations,
        "creators": creators,
        "filters": {
            "lifecycle": lifecycle, "tier": tier, "scope": scope,
            "organization_id": organization_id, "creator_id": creator_id,
            "created_from": created_from, "valid_on": valid_on, "expired": expired,
        },
        "promo_permissions": _promo_permissions(db, current_user),
        "notice": request.query_params.get("notice", ""),
        "error": request.query_params.get("error", ""),
    })


@admin_router.get("/promo-codes/create", response_class=HTMLResponse)
def promo_code_create_page(request: Request, db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    return _render(request, "saas/admin_promo_code_form.html", _promo_form_context(
        db, current_user
    ))


@admin_router.post("/promo-codes/create", response_class=HTMLResponse)
async def promo_code_create(request: Request, db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    form = await request.form()
    try:
        values = _promo_form_values(form)
        created = promo_code_service.create_promo(
            db,
            actor=current_user,
            values=values,
            operation_key=str(form.get("operation_key") or uuid.uuid4()),
            request_correlation_id=request.headers.get("x-request-id"),
        )
        db.commit()
    except promo_code_service.PromoCodeError as exc:
        db.rollback()
        _record_promo_failure(
            db, current_user=current_user, action="create", exc=exc,
            operation_key=str(form.get("operation_key") or ""), request=request,
        )
        return _render(request, "saas/admin_promo_code_form.html", _promo_form_context(
            db, current_user, values=dict(form), error=str(exc)
        ), status_code=400)
    response = _render(request, "saas/admin_promo_code_created.html", {
        "current_user": current_user,
        "promo": created.promo,
        "raw_code": created.raw_code,
        "masked_code": promo_code_service.masked_code(created.promo),
        "promo_permissions": _promo_permissions(db, current_user),
    })
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@admin_router.get("/promo-codes/{promo_uuid}", response_class=HTMLResponse)
def promo_code_detail(promo_uuid: str, request: Request, db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.view")
    promo = promo_code_service.get_promo(db, promo_uuid)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo definition not found.")
    plan = db.query(models.SubscriptionPlan).filter_by(id=promo.subscription_plan_id).one_or_none()
    predecessor = (
        db.query(models.PromoCode).filter_by(id=promo.supersedes_promo_code_id).one_or_none()
        if promo.supersedes_promo_code_id else None
    )
    replacement = db.query(models.PromoCode).filter_by(supersedes_promo_code_id=promo.id).one_or_none()
    return _render(request, "saas/admin_promo_code_detail.html", {
        "current_user": current_user,
        "promo": promo,
        "plan": plan,
        "masked_code": promo_code_service.masked_code(promo),
        "effective_status": promo_code_service.effective_status(promo),
        "branch_restrictions": promo_code_service.list_branch_restrictions(db, promo.id),
        "audit_events": promo_code_service.list_audit_events(db, promo.id),
        "predecessor": predecessor,
        "replacement": replacement,
        "promo_permissions": _promo_permissions(db, current_user),
        "notice": request.query_params.get("notice", ""),
        "error": request.query_params.get("error", ""),
    })


@admin_router.get("/promo-codes/{promo_uuid}/edit", response_class=HTMLResponse)
def promo_code_edit_page(promo_uuid: str, request: Request, db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    promo = promo_code_service.get_promo(db, promo_uuid)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo definition not found.")
    return _render(request, "saas/admin_promo_code_form.html", _promo_form_context(
        db, current_user, promo=promo
    ))


@admin_router.post("/promo-codes/{promo_uuid}/edit", response_class=HTMLResponse)
async def promo_code_edit(promo_uuid: str, request: Request, db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    form = await request.form()
    try:
        promo = promo_code_service.update_promo(
            db,
            promo_uuid=promo_uuid,
            actor=current_user,
            values=_promo_form_values(form),
            operation_key=str(form.get("operation_key") or uuid.uuid4()),
            request_correlation_id=request.headers.get("x-request-id"),
        )
        db.commit()
    except promo_code_service.PromoCodeError as exc:
        db.rollback()
        _record_promo_failure(
            db, current_user=current_user, action="edit", exc=exc,
            promo_uuid=promo_uuid, operation_key=str(form.get("operation_key") or ""),
            request=request,
        )
        promo = promo_code_service.get_promo(db, promo_uuid)
        return _render(request, "saas/admin_promo_code_form.html", _promo_form_context(
            db, current_user, promo=promo, values=dict(form), error=str(exc)
        ), status_code=400)
    return RedirectResponse(
        f"/saas-admin/promo-codes/{promo.promo_uuid}?notice={quote_plus('Promo definition updated.')}",
        status_code=302,
    )


def _promo_action_redirect(promo_uuid: str, *, notice: str = "", error: str = ""):
    parameter = f"notice={quote_plus(notice)}" if notice else f"error={quote_plus(error)}"
    return RedirectResponse(f"/saas-admin/promo-codes/{promo_uuid}?{parameter}", status_code=302)


@admin_router.post("/promo-codes/{promo_uuid}/activate")
def promo_code_activate(promo_uuid: str, request: Request, operation_key: str = Form(""), db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    try:
        promo_code_service.activate_promo(db, promo_uuid=promo_uuid, actor=current_user, operation_key=operation_key or None)
        db.commit()
    except promo_code_service.PromoCodeError as exc:
        db.rollback()
        _record_promo_failure(db, current_user=current_user, action="activate", exc=exc, promo_uuid=promo_uuid, operation_key=operation_key, request=request)
        return _promo_action_redirect(promo_uuid, error=str(exc))
    return _promo_action_redirect(promo_uuid, notice="Promo activated.")


@admin_router.post("/promo-codes/{promo_uuid}/pause")
def promo_code_pause(promo_uuid: str, request: Request, operation_key: str = Form(""), db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    try:
        promo_code_service.pause_promo(db, promo_uuid=promo_uuid, actor=current_user, operation_key=operation_key or None)
        db.commit()
    except promo_code_service.PromoCodeError as exc:
        db.rollback()
        _record_promo_failure(db, current_user=current_user, action="pause", exc=exc, promo_uuid=promo_uuid, operation_key=operation_key, request=request)
        return _promo_action_redirect(promo_uuid, error=str(exc))
    return _promo_action_redirect(promo_uuid, notice="Promo paused.")


@admin_router.post("/promo-codes/{promo_uuid}/revoke")
def promo_code_revoke(promo_uuid: str, request: Request, reason: str = Form(""), operation_key: str = Form(""), db: Session = Depends(get_db)):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    try:
        promo_code_service.revoke_promo(db, promo_uuid=promo_uuid, actor=current_user, reason=reason, operation_key=operation_key or None)
        db.commit()
    except promo_code_service.PromoCodeError as exc:
        db.rollback()
        _record_promo_failure(db, current_user=current_user, action="revoke", exc=exc, promo_uuid=promo_uuid, operation_key=operation_key, request=request)
        return _promo_action_redirect(promo_uuid, error=str(exc))
    return _promo_action_redirect(promo_uuid, notice="Promo revoked.")


async def _promo_new_code_action(request: Request, db: Session, *, promo_uuid: str, action: str):
    current_user = _require_promo_permission(request, db, "promo_codes.manage")
    form = await request.form()
    try:
        if action == "duplicate":
            created = promo_code_service.duplicate_promo(db, promo_uuid=promo_uuid, actor=current_user, operation_key=str(form.get("operation_key") or uuid.uuid4()))
        else:
            created = promo_code_service.replace_promo(db, promo_uuid=promo_uuid, actor=current_user, operation_key=str(form.get("operation_key") or uuid.uuid4()))
        db.commit()
    except promo_code_service.PromoCodeError as exc:
        db.rollback()
        _record_promo_failure(
            db, current_user=current_user, action=action, exc=exc,
            promo_uuid=promo_uuid, operation_key=str(form.get("operation_key") or ""),
            request=request,
        )
        return _promo_action_redirect(promo_uuid, error=str(exc))
    response = _render(request, "saas/admin_promo_code_created.html", {
        "current_user": current_user,
        "promo": created.promo,
        "raw_code": created.raw_code,
        "masked_code": promo_code_service.masked_code(created.promo),
        "promo_permissions": _promo_permissions(db, current_user),
    })
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@admin_router.post("/promo-codes/{promo_uuid}/duplicate", response_class=HTMLResponse)
async def promo_code_duplicate(promo_uuid: str, request: Request, db: Session = Depends(get_db)):
    return await _promo_new_code_action(request, db, promo_uuid=promo_uuid, action="duplicate")


@admin_router.post("/promo-codes/{promo_uuid}/replace", response_class=HTMLResponse)
async def promo_code_replace(promo_uuid: str, request: Request, db: Session = Depends(get_db)):
    return await _promo_new_code_action(request, db, promo_uuid=promo_uuid, action="replace")
