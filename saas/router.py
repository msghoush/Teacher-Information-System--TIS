from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import os
from urllib.parse import quote_plus

import auth
import audit
from dependencies import get_db
import email_service
import location_service
from saas import billing_service, draft_lifecycle_service, models, oauth, orphaned_test_account_service, paddle_client, payment_service, pricing_service, provisioning_service, service, subscription_change_service, subscription_portal_service, test_account_deletion_service, workspace_analysis_service, workspace_deletion_service

templates = Jinja2Templates(directory="templates")
router = APIRouter(prefix="/saas", tags=["saas"])
admin_router = APIRouter(prefix="/saas-admin", tags=["saas-admin"])


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


def _safe_next(next_path: str | None) -> str:
    cleaned = str(next_path or "").strip()
    return cleaned if cleaned.startswith("/saas") else "/saas/account"


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


def _login_required_redirect():
    return RedirectResponse(
        "/saas/login?notice=" + quote_plus("Please sign in to your TIS Account."),
        status_code=302,
    )


def _require_verified_account(request: Request, db: Session):
    account = _current_account(request, db)
    if not account:
        return None, None, _login_required_redirect()
    session_row = service.get_session_from_request(db, request)
    if _account_needs_verification(account):
        return None, None, _verification_required_redirect(str(getattr(account, "email", "") or ""))
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


def _render(request: Request, template_name: str, context: dict, status_code: int = 200):
    merged = {"request": request, **context}
    return templates.TemplateResponse(request, template_name, merged, status_code=status_code)


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
}


def _redirect_error(path: str, message: str):
    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}error={quote_plus(str(message or ''))}", status_code=302)


@router.get("/payment", response_class=HTMLResponse)
def paddle_payment_page(request: Request):
    return _render(
        request,
        "saas/payment.html",
        {
            "title": "Secure Payment | TIS Platform",
            "paddle_client_token": str(os.environ.get("PADDLE_CLIENT_TOKEN") or "").strip(),
            "paddle_environment": _paddle_client_environment(),
        },
    )


def _onboarding_context(db: Session, account, organization):
    summary = service.build_pending_dashboard_summary(db, account)
    progress = summary["progress"] if summary else service.get_or_create_pending_progress(db, organization)
    academic_setup = service.get_or_create_academic_setup(db, organization)
    primary_contact = service.get_primary_contact(db, organization)
    branches = service.list_pending_branches(db, organization)
    onboarding_step_access = service.build_onboarding_step_access(db, organization)
    return {
        "account": account,
        "organization": organization,
        "progress": progress,
        "academic_setup": academic_setup,
        "primary_contact": primary_contact,
        "branches": branches,
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
    return {
        "account": account,
        "organization": organization,
        "journey_card": summary,
        "plan_catalog": pricing_service.build_plan_catalog(
            db,
            country_code=str(getattr(organization, "country_code", "") or ""),
        ),
        "billable_branch_count": service.count_billable_pending_branches(db, organization),
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
    return RedirectResponse("/saas/account" if account else "/saas/login", status_code=302)


@router.get("/login", response_class=HTMLResponse, name="saas_login_page")
def login_page(
    request: Request,
    error: str = Query(""),
    notice: str = Query(""),
    email: str = Query(""),
    db: Session = Depends(get_db),
):
    if _current_account(request, db):
        return RedirectResponse("/saas/account", status_code=302)
    return _render(
        request,
        "saas/login.html",
        {
            "error": error,
            "notice": notice,
            "email": email,
            "google_enabled": oauth.is_provider_configured("google"),
            "microsoft_enabled": oauth.is_provider_configured("microsoft"),
        },
    )


@router.get("/auth/forgot-password", response_class=HTMLResponse)
def forgot_password_page(
    request: Request,
    email: str = Query(""),
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
    db: Session = Depends(get_db),
):
    if _current_account(request, db):
        return RedirectResponse("/saas/account", status_code=302)
    return _render(
        request,
        "saas/signup.html",
        {
            "error": error,
            "warning": warning,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "google_enabled": oauth.is_provider_configured("google"),
            "microsoft_enabled": oauth.is_provider_configured("microsoft"),
        },
    )


@router.post("/auth/signup")
def signup(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if service.is_rate_limited(
        db,
        event_type="signup",
        request=request,
        max_attempts=service.SIGNUP_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.SIGNUP_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/signup?error=Too+many+signup+attempts.+Please+try+again+later.",
            status_code=302,
        )
    if str(password or "") != str(confirm_password or ""):
        return RedirectResponse(
            url=(
                "/saas/signup?error=Password+confirmation+does+not+match."
                f"&email={quote_plus(str(email or ''))}"
                f"&first_name={quote_plus(str(first_name or ''))}"
                f"&last_name={quote_plus(str(last_name or ''))}"
            ),
            status_code=302,
        )
    try:
        account, policy = service.create_account(
            db,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            request=request,
        )
        service.send_verification_email(db, account, request)
        db.commit()
    except email_service.EmailDeliveryError:
        db.rollback()
        return RedirectResponse(
            url="/saas/signup?error=Verification+email+could+not+be+sent.+Please+try+again.",
            status_code=302,
        )
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(
            url=(
                "/saas/signup?error="
                + quote_plus(str(exc))
                + f"&email={quote_plus(str(email or ''))}"
                + f"&first_name={quote_plus(str(first_name or ''))}"
                + f"&last_name={quote_plus(str(last_name or ''))}"
            ),
            status_code=302,
        )
    return RedirectResponse(
        url="/saas/auth/verification-sent?email="
        f"{quote_plus(str(account.email or ''))}&warning={quote_plus(str(policy.warning or ''))}",
        status_code=302,
    )


@router.post("/auth/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_path: str = Form("/saas/account"),
    db: Session = Depends(get_db),
):
    if service.is_rate_limited(
        db,
        event_type="login",
        request=request,
        event_status="failed",
        max_attempts=service.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_minutes=service.LOGIN_RATE_LIMIT_WINDOW_MINUTES,
    ):
        return RedirectResponse(
            url="/saas/login?error=Too+many+login+attempts.+Please+wait+before+trying+again.",
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
            url="/saas/login?error=Invalid+email+or+password.&email=" + quote_plus(str(email or "")),
            status_code=302,
        )
    if _account_needs_verification(account):
        return RedirectResponse(
            url=(
                "/saas/auth/verification-required?email="
                + quote_plus(str(getattr(account, "email", "") or email or ""))
            ),
            status_code=302,
        )
    session_token, csrf_token, _session_row = service.create_session(db, account, request=request)
    service.log_auth_event(db, event_type="login", account_id=account.id, request=request)
    draft_lifecycle_service.record_meaningful_activity(
        db, account, source="successful_login"
    )
    db.commit()
    response = RedirectResponse(url=_safe_next(next_path), status_code=302)
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


@router.get("/account", response_class=HTMLResponse)
def account_dashboard(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    setup_console = service.build_setup_console_context(db, account)
    db.commit()
    return _render(
        request,
        "saas/account.html",
        {
            "account": account,
            "notice": request.query_params.get("notice", ""),
            "setup_console": setup_console,
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
    db.commit()
    return _render(
        request,
        "saas/profile.html",
        {
            "account": account,
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
    db.commit()
    return _render(
        request,
        "saas/security.html",
        {"account": account, "identities": identities, "notice": request.query_params.get("notice", "")},
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
def subscription_portal(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    portal = subscription_portal_service.build_subscription_portal(db, account)
    return _render(
        request,
        "saas/subscription.html",
        {
            "account": account,
            "subscription_portal": portal,
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


def _require_saas_csrf(session_row, csrf_token: str):
    if service.hash_value(csrf_token) != str(session_row.csrf_token_hash or ""):
        raise HTTPException(status_code=403, detail="Invalid CSRF token.")


def _subscription_change_error(exc: subscription_change_service.SubscriptionChangeError, path: str):
    if exc.status_code == 403:
        raise HTTPException(status_code=403, detail=str(exc))
    return _redirect_error(path, str(exc))


@router.get("/subscription/branches", response_class=HTMLResponse)
def subscription_branch_management(request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    portal = subscription_portal_service.build_subscription_portal(db, account)
    try:
        subscription_change_service.resolve_change_context(db, account)
        can_manage = portal.pending_change is None
        access_error = ""
    except subscription_change_service.SubscriptionChangeError as exc:
        if exc.status_code == 403:
            raise HTTPException(status_code=403, detail=str(exc))
        can_manage = False
        access_error = str(exc)
    return _render(request, "saas/subscription_branches.html", {
        "account": account,
        "subscription_portal": portal,
        "can_manage": can_manage,
        "access_error": access_error,
        "csrf_token": request.cookies.get(service.SAAS_CSRF_COOKIE, ""),
        "notice": request.query_params.get("notice", ""),
        "error": request.query_params.get("error", ""),
    })


@router.post("/subscription/branches/preview")
def preview_subscription_branch_change(
    request: Request,
    requested_quantity: int = Form(...),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    account, session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    _require_saas_csrf(session_row, csrf_token)
    try:
        row = subscription_change_service.preview_quantity_change(db, account, requested_quantity)
        db.commit()
    except subscription_change_service.SubscriptionChangeError as exc:
        db.commit()
        return _subscription_change_error(exc, "/saas/subscription/branches")
    return RedirectResponse(f"/saas/subscription/branches/{row.request_uuid}/confirm", status_code=302)


@router.get("/subscription/branches/{request_uuid}/confirm", response_class=HTMLResponse)
def confirm_subscription_branch_change_page(request_uuid: str, request: Request, db: Session = Depends(get_db)):
    account, _session_row, redirect = _require_verified_account(request, db)
    if redirect:
        return redirect
    try:
        context = subscription_change_service.resolve_change_context(db, account)
    except subscription_change_service.SubscriptionChangeError as exc:
        return _subscription_change_error(exc, "/saas/subscription/branches")
    row = db.query(models.SubscriptionChangeRequest).filter(
        models.SubscriptionChangeRequest.request_uuid == request_uuid,
        models.SubscriptionChangeRequest.payment_subscription_id == context.subscription.id,
        models.SubscriptionChangeRequest.requested_by_saas_account_id == account.id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Branch-capacity request not found.")
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
    db.commit()
    return _render(
        request,
        "saas/sessions.html",
        {
            "account": account,
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
        service.save_organization_profile(
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
        progress = service.save_draft(db, account, organization, current_step="branches")
        service.log_pending_event(db, organization=organization, account=account, event_type="organization_saved", details={"completion_percent": progress.completion_percent})
        draft_lifecycle_service.record_meaningful_activity(
            db, account, organization=organization, source="organization_profile_saved"
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
            "saas/onboarding_organization.html",
            "organization",
            error=str(exc),
            status_code=422,
            extra_context={
                "form_data": {
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
                },
            },
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
        service.replace_branches(db, organization, branch_rows)
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
            extra_context={"form_branches": branch_rows, "selected_primary_index": 0},
        )
    if str(save_action or "").strip().lower() == "save_exit":
        return RedirectResponse("/saas/account?notice=Draft+saved.", status_code=302)
    return RedirectResponse(f"/saas/onboarding/{organization_uuid}/academic_setup", status_code=302)


@router.get("/onboarding/{organization_uuid}/academic_setup", response_class=HTMLResponse)
def academic_setup_step(
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
    locked_redirect = _locked_onboarding_step_redirect(db, organization, "academic_setup")
    if locked_redirect:
        db.commit()
        return locked_redirect
    context = _onboarding_context(db, account, organization)
    db.commit()
    context.update({
        "account": account,
        "error": error,
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
    return RedirectResponse("/saas/account?notice=Your+School+Workspace+Setup+is+ready+for+Subscription+Setup.", status_code=302)


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
    return _render(request, "saas/plan_selection.html", context)


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
    return RedirectResponse(
        f"/saas/onboarding/{organization_uuid}/checkout?notice={quote_plus('Subscription plan saved.')}",
        status_code=302,
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
    context.update({
        "error": error,
        "notice": notice,
        "setup_console": _payment_setup_console(
            db,
            account,
            "checkout",
            organization=organization,
            checkout_summary=context.get("checkout_summary"),
            onboarding_summary=context.get("journey_card"),
        ),
    })
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
        if billing_service.checkout_quote_is_fresh(db, organization):
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
    except (ValueError, paddle_client.PaddleAPIError) as exc:
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


@admin_router.get("/pending-organizations", response_class=HTMLResponse)
def pending_organizations_dashboard(
    request: Request,
    status: str = Query(""),
    db: Session = Depends(get_db),
):
    current_user = _require_platform_owner(request, db)
    organizations = service.list_pending_organizations(db, status=status)
    cards = [service.build_pending_card(db, organization) for organization in organizations]
    db.commit()
    return _render(
        request,
        "saas/admin_pending_organizations.html",
        {
            "current_user": current_user,
            "cards": cards,
            "status_filter": status,
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
        audit.write_audit_event({
            "event_type": "test_workspace_deletion",
            "result": "blocked_not_found",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "reason": str(reason or "").strip()[:500],
        })
        raise HTTPException(status_code=404, detail="Pending organization not found.")

    organization_name = str(organization.organization_name or "")
    school_group_id = 0
    analysis_counts = {}
    try:
        analysis = workspace_analysis_service.analyze_test_workspace(db, organization)
        school_group_id = int(analysis["school_group_id"] or 0)
        analysis_counts = {row.table: int(row.count or 0) for row in analysis["counts"]}
        result = workspace_deletion_service.delete_test_workspace(
            db,
            organization,
            confirmation_name=confirmation_name,
            reason=reason,
        )
        db.commit()
    except workspace_deletion_service.WorkspaceDeletionBlocked as exc:
        db.rollback()
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
    except Exception:
        db.rollback()
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
        audit.write_audit_event({
            "event_type": "test_account_workspace_deletion",
            "result": "blocked_not_found",
            "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
            "organization_uuid": str(organization_uuid or ""),
            "reason": str(reason or "").strip()[:500],
        })
        raise HTTPException(status_code=404, detail="Pending organization not found.")

    safe_context = {
        "actor_user_id": str(getattr(current_user, "user_id", "") or ""),
        "organization_uuid": str(organization.organization_uuid or ""),
        "organization_name": str(organization.organization_name or ""),
        "reason": str(reason or "").strip()[:500],
    }
    try:
        analysis = test_account_deletion_service.analyze_test_account(db, organization)
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
    except test_account_deletion_service.TestAccountDeletionBlocked as exc:
        db.rollback()
        audit.write_audit_event({"event_type": "test_account_workspace_deletion", "result": "blocked", **safe_context})
        return RedirectResponse(
            f"/saas-admin/pending-organizations/{organization_uuid}/delete-test-account?error={quote_plus(str(exc))}",
            status_code=302,
        )
    except Exception:
        db.rollback()
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
def oauth_start(provider: str, request: Request):
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
    response = RedirectResponse(
        f"/saas/account?notice={notice}" if notice else "/saas/account",
        status_code=302,
    )
    response.delete_cookie(oauth.OAUTH_STATE_COOKIE, **auth.secure_cookie_kwargs(request))
    response.delete_cookie(oauth.OAUTH_PKCE_COOKIE, **auth.secure_cookie_kwargs(request))
    return service.set_session_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
        request=request,
    )
